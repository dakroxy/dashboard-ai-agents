"""Permissions-Registry und Helper fuer Rollen-/Resource-basierten Zugriff.

Zwei Ebenen:

1. Flache Permission-Keys (string) — granulare Feature-Berechtigungen.
   Resolvierung: Role.permissions ∪ User.permissions_extra \\ User.permissions_denied.

2. Resource-Access via ResourceAccess-Tabelle — Workflow/Objekt/Task/CRM-Sichtbarkeit.
   User-Overrides (allow/deny) gewinnen immer ueber Role-Defaults.

Jedes neue Modul registriert seine Permission-Keys in PERMISSIONS und
nutzt ggf. einen neuen RESOURCE_TYPE_*-Konstanten.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import ResourceAccess, User, Workflow


# ---------------------------------------------------------------------------
# Permission-Konstanten (Quelle der Wahrheit fuer Permission-Keys)
# ---------------------------------------------------------------------------

PERM_OBJECTS_VIEW = "objects:view"
PERM_OBJECTS_EDIT = "objects:edit"
PERM_OBJECTS_APPROVE_KI = "objects:approve_ki"
PERM_OBJECTS_VIEW_CONFIDENTIAL = "objects:view_confidential"
PERM_REGISTRIES_VIEW = "registries:view"
PERM_REGISTRIES_EDIT = "registries:edit"
PERM_DUE_RADAR_VIEW = "due_radar:view"
PERM_SYNC_ADMIN = "sync:admin"


# ---------------------------------------------------------------------------
# Permission-Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    group: str


PERMISSIONS: list[Permission] = [
    # Dokumente
    Permission("documents:upload", "Dokumente hochladen", "Dokumente"),
    Permission(
        "documents:view_all",
        "Alle Dokumente sehen (auch von anderen Usern)",
        "Dokumente",
    ),
    Permission("documents:approve", "Dokumente freigeben / Impower-Schreibpfad auslösen", "Dokumente"),
    Permission("documents:delete", "Dokumente löschen", "Dokumente"),
    # Workflows
    Permission("workflows:view", "Workflow-Übersicht ansehen", "Workflows"),
    Permission("workflows:edit", "Workflows/Prompts editieren", "Workflows"),
    # Objekte (Steckbrief)
    Permission("objects:view", "Objekte ansehen", "Objekte"),
    Permission("objects:edit", "Objekte bearbeiten", "Objekte"),
    # v2-TODO: Per-Object-IDOR (siehe deferred-work.md #4). Aktuell portfolio-weit als bewusste v1-Design-Entscheidung — alle Approver sehen alle Reviews.
    Permission("objects:approve_ki", "KI-Vorschläge freigeben", "Objekte"),
    Permission(
        "objects:view_confidential",
        "Vertrauliche Felder lesen",
        "Objekte",
    ),
    # Registries (Versicherer, Dienstleister, ...)
    Permission("registries:view", "Registries ansehen", "Registries"),
    Permission("registries:edit", "Registries bearbeiten", "Registries"),
    # Due-Radar
    Permission("due_radar:view", "Due-Radar ansehen", "Due-Radar"),
    # Admin
    Permission("users:manage", "User und Rollen verwalten", "Admin"),
    Permission("audit_log:view", "Audit-Log ansehen", "Admin"),
    Permission("audit_log:delete", "Audit-Log-Einträge löschen", "Admin"),
    Permission("impower:debug", "Impower-Debug-Endpoints nutzen", "Admin"),
    Permission(
        "sync:admin",
        "Sync-Status + Nightly-Jobs verwalten",
        "Admin",
    ),
]

PERMISSION_KEYS: frozenset[str] = frozenset(p.key for p in PERMISSIONS)

PERMISSIONS_BY_GROUP: dict[str, list[Permission]] = {}
for _p in PERMISSIONS:
    PERMISSIONS_BY_GROUP.setdefault(_p.group, []).append(_p)


# Resource-Types — erweitert sich pro neuem Modul.
RESOURCE_TYPE_WORKFLOW = "workflow"
RESOURCE_TYPE_OBJECT = "object"


# Defaults fuers Seeding der System-Rollen.
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": sorted(PERMISSION_KEYS),
    "user": sorted(
        [
            "documents:upload",
            "documents:view_all",
            "documents:approve",
            "workflows:view",
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "registries:view",
            "registries:edit",
            "due_radar:view",
        ]
    ),
}


# ---------------------------------------------------------------------------
# Permission-Checks
# ---------------------------------------------------------------------------

def effective_permissions(user: User) -> set[str]:
    """Wirksame Permissions: Role-Defaults + extra - denied."""
    if user.disabled_at is not None:
        return set()
    base: set[str] = set()
    if user.role is not None:
        base.update(user.role.permissions or [])
    base.update(user.permissions_extra or [])
    for denied in user.permissions_denied or []:
        base.discard(denied)
    return base


def has_permission(user: User | None, key: str) -> bool:
    if user is None:
        return False
    return key in effective_permissions(user)


def require_permission(key: str):
    """FastAPI-Dependency: gibt den User zurueck ODER wirft 403."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Keine Berechtigung: {key}",
            )
        return user

    return dep


def require_any_permission(*keys: str):
    """Wie require_permission, aber erlaubt mehrere Alternativ-Keys."""

    def dep(user: User = Depends(get_current_user)) -> User:
        effective = effective_permissions(user)
        if not any(k in effective for k in keys):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Keine Berechtigung: {' oder '.join(keys)}",
            )
        return user

    return dep


# ---------------------------------------------------------------------------
# Resource-Access
# ---------------------------------------------------------------------------

def can_access_resource(
    db: Session,
    user: User,
    resource_type: str,
    resource_id: uuid.UUID,
) -> bool:
    """Prueft, ob der User auf die Ressource zugreifen darf.

    Reihenfolge: User-deny > User-allow > Role-allow (sonst kein Zugriff).
    """
    if user.disabled_at is not None:
        return False

    user_override = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.user_id == user.id,
            ResourceAccess.resource_type == resource_type,
            ResourceAccess.resource_id == resource_id,
        )
        .first()
    )
    if user_override is not None:
        return user_override.mode == "allow"

    if user.role_id is None:
        return False

    role_allow = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.role_id == user.role_id,
            ResourceAccess.resource_type == resource_type,
            ResourceAccess.resource_id == resource_id,
            ResourceAccess.mode == "allow",
        )
        .first()
    )
    return role_allow is not None


def accessible_resource_ids(
    db: Session, user: User, resource_type: str
) -> set[uuid.UUID]:
    """Alle Resource-IDs eines Typs, auf die der User zugreifen darf."""
    if user.disabled_at is not None:
        return set()

    overrides = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.user_id == user.id,
            ResourceAccess.resource_type == resource_type,
        )
        .all()
    )
    denied: set[uuid.UUID] = set()
    allowed: set[uuid.UUID] = set()
    for ov in overrides:
        if ov.mode == "allow":
            allowed.add(ov.resource_id)
        else:
            denied.add(ov.resource_id)

    if user.role_id is not None:
        role_allows = (
            db.query(ResourceAccess)
            .filter(
                ResourceAccess.role_id == user.role_id,
                ResourceAccess.resource_type == resource_type,
                ResourceAccess.mode == "allow",
            )
            .all()
        )
        for ra in role_allows:
            if ra.resource_id not in denied:
                allowed.add(ra.resource_id)

    return allowed


def can_access_workflow(db: Session, user: User, workflow: Workflow) -> bool:
    return can_access_resource(
        db, user, RESOURCE_TYPE_WORKFLOW, workflow.id
    )


def accessible_workflow_ids(db: Session, user: User) -> set[uuid.UUID]:
    return accessible_resource_ids(db, user, RESOURCE_TYPE_WORKFLOW)


def accessible_object_ids(db: Session, user: User) -> set[uuid.UUID]:
    """v1-Semantik: sobald der User `objects:view` hat, sieht er ALLE Objekte.
    resource_access-Rows fuer resource_type="object" werden in v1 ignoriert,
    duerfen aber ab Tag 1 geschrieben werden (siehe Story 1.1). v1.1 schaltet
    auf `accessible_resource_ids(db, user, RESOURCE_TYPE_OBJECT)` um — dann
    greift die ACL scharf."""
    # Import hier, um Zirkularitaet mit app.models zu vermeiden.
    from app.models import Object

    if user.disabled_at is not None:
        return set()
    if not has_permission(user, "objects:view"):
        return set()
    return set(db.execute(select(Object.id)).scalars().all())


def accessible_object_ids_for_request(
    request: Request | None, db: Session, user: User
) -> set[uuid.UUID]:
    """Request-scoped Cache fuer `accessible_object_ids`.

    Speichert das Ergebnis auf `request.state._accessible_object_ids`; alle
    weiteren Aufrufe im selben Request lesen aus dem State ohne DB-Hit.
    Lebensdauer ist exakt ein Request — kein Cross-Request-Leak.
    Fallback fuer Background-Tasks oder Tests ohne Request: ruft direkt
    `accessible_object_ids` auf (dann kein State-Caching).
    """
    if request is None:
        return accessible_object_ids(db, user)
    cached = getattr(request.state, "_accessible_object_ids", None)
    if cached is not None:
        return cached
    result = accessible_object_ids(db, user)
    request.state._accessible_object_ids = result
    return result
