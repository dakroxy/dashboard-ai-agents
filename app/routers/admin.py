"""Admin-Router: User-/Rollen-Verwaltung und Audit-Log.

Jede Route erzwingt eine konkrete Permission. Die UI blendet Links
nur ein, wenn der User die Permission hat — Server-seitig wird trotzdem
hart geprueft.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, ResourceAccess, Role, User, Workflow
from app.permissions import (
    PERMISSIONS_BY_GROUP,
    PERMISSION_KEYS,
    RESOURCE_TYPE_WORKFLOW,
    effective_permissions,
    require_any_permission,
    require_permission,
)
from app.services.audit import KNOWN_AUDIT_ACTIONS, audit
from app.templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    user: User = Depends(
        require_any_permission("users:manage", "audit_log:view")
    ),
    db: Session = Depends(get_db),
):
    counts = {
        "users": db.query(User).count(),
        "roles": db.query(Role).count(),
        "audit_entries": db.query(AuditLog).count(),
    }
    recent_logs = (
        db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(10).all()
    )
    return templates.TemplateResponse(
        request,
        "admin/home.html",
        {
            "title": "Admin",
            "user": user,
            "counts": counts,
            "recent_logs": recent_logs,
        },
    )


# ---------------------------------------------------------------------------
# User-Verwaltung
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.email.asc()).all()
    return templates.TemplateResponse(
        request,
        "admin/users_list.html",
        {"title": "User", "user": user, "users": users},
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def edit_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    roles = db.query(Role).order_by(Role.name.asc()).all()
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()

    wf_overrides = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.user_id == target.id,
            ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
        )
        .all()
    )
    wf_override_map = {ov.resource_id: ov.mode for ov in wf_overrides}

    role_workflow_ids: set[uuid.UUID] = set()
    if target.role_id is not None:
        role_wf = (
            db.query(ResourceAccess)
            .filter(
                ResourceAccess.role_id == target.role_id,
                ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
                ResourceAccess.mode == "allow",
            )
            .all()
        )
        role_workflow_ids = {ra.resource_id for ra in role_wf}

    return templates.TemplateResponse(
        request,
        "admin/user_edit.html",
        {
            "title": target.email,
            "user": user,
            "target": target,
            "roles": roles,
            "workflows": workflows,
            "permissions_by_group": PERMISSIONS_BY_GROUP,
            "effective": effective_permissions(target),
            "wf_override_map": wf_override_map,
            "role_workflow_ids": role_workflow_ids,
            "is_self": target.id == user.id,
        },
    )


@router.post("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    request: Request,
    role_id: str = Form(""),
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    form = await request.form()
    extras = set(form.getlist("permissions_extra"))
    denied = set(form.getlist("permissions_denied"))

    unknown = (extras | denied) - PERMISSION_KEYS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannte Permission-Keys: {', '.join(sorted(unknown))}",
        )
    # Wenn derselbe Key in extra UND denied gesetzt ist, gewinnt denied —
    # fehlkonfigurationen wuerden sonst unerwartet sein. Wir droppen aus extras.
    extras -= denied

    changes: dict = {}

    # Rolle
    new_role_id: uuid.UUID | None = None
    if role_id:
        try:
            new_role_id = uuid.UUID(role_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungueltige Rolle.",
            )
        if db.query(Role).filter(Role.id == new_role_id).first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rolle nicht gefunden.",
            )
    if target.role_id != new_role_id:
        changes["role_id"] = {
            "from": str(target.role_id) if target.role_id else None,
            "to": str(new_role_id) if new_role_id else None,
        }
        target.role_id = new_role_id

    prev_extra = sorted(target.permissions_extra or [])
    prev_denied = sorted(target.permissions_denied or [])
    new_extra = sorted(extras)
    new_denied = sorted(denied)
    if prev_extra != new_extra:
        changes["permissions_extra"] = {"from": prev_extra, "to": new_extra}
    if prev_denied != new_denied:
        changes["permissions_denied"] = {"from": prev_denied, "to": new_denied}
    target.permissions_extra = new_extra
    target.permissions_denied = new_denied

    # Workflow-Overrides: key 'wf_<workflow_id>' -> 'default' | 'allow' | 'deny'
    workflows = db.query(Workflow).all()
    wf_changes: list[dict] = []
    for wf in workflows:
        mode = form.get(f"wf_{wf.id}") or "default"
        existing = (
            db.query(ResourceAccess)
            .filter(
                ResourceAccess.user_id == target.id,
                ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
                ResourceAccess.resource_id == wf.id,
            )
            .first()
        )
        if mode == "default":
            if existing is not None:
                db.delete(existing)
                wf_changes.append({"workflow": wf.key, "from": existing.mode, "to": "default"})
        elif mode in ("allow", "deny"):
            if existing is None:
                db.add(
                    ResourceAccess(
                        id=uuid.uuid4(),
                        user_id=target.id,
                        resource_type=RESOURCE_TYPE_WORKFLOW,
                        resource_id=wf.id,
                        mode=mode,
                    )
                )
                wf_changes.append({"workflow": wf.key, "from": "default", "to": mode})
            elif existing.mode != mode:
                wf_changes.append({"workflow": wf.key, "from": existing.mode, "to": mode})
                existing.mode = mode
    if wf_changes:
        changes["workflow_overrides"] = wf_changes

    if changes:
        audit(
            db,
            user,
            "user_updated",
            entity_type="user",
            entity_id=target.id,
            details={"target_email": target.email, "changes": changes},
            request=request,
        )
    db.commit()
    return RedirectResponse(
        url=f"/admin/users/{target.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if target.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Man kann sich nicht selbst deaktivieren.",
        )
    if target.disabled_at is None:
        target.disabled_at = datetime.now(timezone.utc)
        target.disabled_by_id = user.id
        audit(
            db,
            user,
            "user_disabled",
            entity_type="user",
            entity_id=target.id,
            details={"target_email": target.email},
            request=request,
        )
        db.commit()
    return RedirectResponse(
        url=f"/admin/users/{target.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if target.disabled_at is not None:
        target.disabled_at = None
        target.disabled_by_id = None
        audit(
            db,
            user,
            "user_enabled",
            entity_type="user",
            entity_id=target.id,
            details={"target_email": target.email},
            request=request,
        )
        db.commit()
    return RedirectResponse(
        url=f"/admin/users/{target.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Rollen-Verwaltung
# ---------------------------------------------------------------------------

@router.get("/roles", response_class=HTMLResponse)
async def list_roles(
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    roles = db.query(Role).order_by(Role.name.asc()).all()
    user_counts: dict[uuid.UUID, int] = {}
    for r in roles:
        user_counts[r.id] = db.query(User).filter(User.role_id == r.id).count()
    return templates.TemplateResponse(
        request,
        "admin/roles_list.html",
        {
            "title": "Rollen",
            "user": user,
            "roles": roles,
            "user_counts": user_counts,
        },
    )


@router.get("/roles/new", response_class=HTMLResponse)
async def new_role_form(
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()
    return templates.TemplateResponse(
        request,
        "admin/role_edit.html",
        {
            "title": "Neue Rolle",
            "user": user,
            "role": None,
            "workflows": workflows,
            "permissions_by_group": PERMISSIONS_BY_GROUP,
            "role_permissions": set(),
            "role_workflow_ids": set(),
        },
    )


@router.post("/roles")
async def create_role(
    request: Request,
    key: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    key = key.strip().lower()
    name = name.strip()
    if not _KEY_RE.match(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key muss mit Kleinbuchstaben beginnen und nur a-z/0-9/_ enthalten.",
        )
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Name ist Pflicht."
        )
    if db.query(Role).filter(Role.key == key).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Key '{key}' ist bereits vergeben.",
        )

    form = await request.form()
    perms = set(form.getlist("permissions")) & PERMISSION_KEYS

    role = Role(
        id=uuid.uuid4(),
        key=key,
        name=name,
        description=description.strip(),
        permissions=sorted(perms),
        is_system_role=False,
    )
    db.add(role)
    db.flush()

    # Workflow-Zuweisungen uebernehmen
    workflow_ids = [
        uuid.UUID(v) for v in form.getlist("workflows") if _is_uuid(v)
    ]
    for wf_id in workflow_ids:
        db.add(
            ResourceAccess(
                id=uuid.uuid4(),
                role_id=role.id,
                resource_type=RESOURCE_TYPE_WORKFLOW,
                resource_id=wf_id,
                mode="allow",
            )
        )

    audit(
        db,
        user,
        "role_created",
        entity_type="role",
        entity_id=role.id,
        details={
            "key": role.key,
            "name": role.name,
            "permissions": role.permissions,
            "workflow_ids": [str(w) for w in workflow_ids],
        },
        request=request,
    )
    db.commit()
    return RedirectResponse(
        url=f"/admin/roles/{role.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/roles/{role_id}", response_class=HTMLResponse)
async def edit_role(
    role_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()
    role_wf = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.role_id == role.id,
            ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
            ResourceAccess.mode == "allow",
        )
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/role_edit.html",
        {
            "title": f"Rolle: {role.name}",
            "user": user,
            "role": role,
            "workflows": workflows,
            "permissions_by_group": PERMISSIONS_BY_GROUP,
            "role_permissions": set(role.permissions or []),
            "role_workflow_ids": {ra.resource_id for ra in role_wf},
        },
    )


@router.post("/roles/{role_id}")
async def update_role(
    role_id: uuid.UUID,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    form = await request.form()
    new_perms = sorted(set(form.getlist("permissions")) & PERMISSION_KEYS)
    workflow_ids = {
        uuid.UUID(v) for v in form.getlist("workflows") if _is_uuid(v)
    }

    changes: dict = {}
    if role.name != name.strip():
        changes["name"] = {"from": role.name, "to": name.strip()}
    if (role.description or "") != description.strip():
        changes["description"] = {
            "from": role.description or "",
            "to": description.strip(),
        }
    if sorted(role.permissions or []) != new_perms:
        changes["permissions"] = {
            "from": sorted(role.permissions or []),
            "to": new_perms,
        }

    role.name = name.strip() or role.name
    role.description = description.strip()
    role.permissions = new_perms

    # Workflow-Zuweisungen synchronisieren
    existing = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.role_id == role.id,
            ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
        )
        .all()
    )
    existing_ids = {ra.resource_id: ra for ra in existing}
    wf_added: list[uuid.UUID] = []
    wf_removed: list[uuid.UUID] = []
    for wf_id in workflow_ids - existing_ids.keys():
        db.add(
            ResourceAccess(
                id=uuid.uuid4(),
                role_id=role.id,
                resource_type=RESOURCE_TYPE_WORKFLOW,
                resource_id=wf_id,
                mode="allow",
            )
        )
        wf_added.append(wf_id)
    for wf_id, ra in existing_ids.items():
        if wf_id not in workflow_ids:
            db.delete(ra)
            wf_removed.append(wf_id)
    if wf_added or wf_removed:
        changes["workflows"] = {
            "added": [str(w) for w in wf_added],
            "removed": [str(w) for w in wf_removed],
        }

    if changes:
        audit(
            db,
            user,
            "role_updated",
            entity_type="role",
            entity_id=role.id,
            details={"key": role.key, "changes": changes},
            request=request,
        )
    db.commit()
    return RedirectResponse(
        url=f"/admin/roles/{role.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/roles/{role_id}/delete")
async def delete_role(
    role_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if role.is_system_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System-Rollen koennen nicht geloescht werden.",
        )
    in_use = db.query(User).filter(User.role_id == role.id).count()
    if in_use > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rolle ist noch {in_use} User(n) zugeordnet — erst umziehen.",
        )
    audit(
        db,
        user,
        "role_deleted",
        entity_type="role",
        entity_id=role.id,
        details={"key": role.key, "name": role.name},
        request=request,
    )
    db.delete(role)
    db.commit()
    return RedirectResponse(
        url="/admin/roles",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Audit-Log
# ---------------------------------------------------------------------------

@router.get("/logs", response_class=HTMLResponse)
async def list_logs(
    request: Request,
    user_email: str | None = Query(None),
    action: str | None = Query(None),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    user: User = Depends(require_permission("audit_log:view")),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f"%{user_email}%"))
    if action:
        query = query.filter(AuditLog.action == action)
    if from_date:
        try:
            dt_from = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            pass
    if to_date:
        try:
            dt_to = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at <= dt_to)
        except ValueError:
            pass

    logs = query.limit(500).all()

    db_distinct = {
        r[0]
        for r in db.query(AuditLog.action).distinct().all()
        if r[0]
    }
    distinct_actions = sorted(db_distinct | set(KNOWN_AUDIT_ACTIONS))

    return templates.TemplateResponse(
        request,
        "admin/logs.html",
        {
            "title": "Audit-Log",
            "user": user,
            "logs": logs,
            "distinct_actions": distinct_actions,
            "filter_user_email": user_email or "",
            "filter_action": action or "",
            "filter_from": from_date or "",
            "filter_to": to_date or "",
            "can_delete": "audit_log:delete" in effective_permissions(user),
        },
    )


@router.post("/logs/{log_id}/delete")
async def delete_log(
    log_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("audit_log:delete")),
    db: Session = Depends(get_db),
):
    entry = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    audit(
        db,
        user,
        "audit_entry_deleted",
        entity_type="audit_log",
        entity_id=entry.id,
        details={
            "deleted_action": entry.action,
            "deleted_user_email": entry.user_email,
            "deleted_created_at": entry.created_at.isoformat(),
        },
        request=request,
    )
    db.delete(entry)
    db.commit()
    return RedirectResponse(
        url="/admin/logs",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False
