"""Story 1.1 — Steckbrief Permissions + Audit-Actions + Seed-Merge."""
from __future__ import annotations

import uuid

from app.main import _seed_default_roles
from app.models import Role
from app.permissions import (
    DEFAULT_ROLE_PERMISSIONS,
    PERMISSION_KEYS,
    PERMISSIONS_BY_GROUP,
)
from app.services.audit import KNOWN_AUDIT_ACTIONS
from tests.conftest import _TestSessionLocal  # type: ignore


NEW_STECKBRIEF_KEYS = {
    "objects:view",
    "objects:edit",
    "objects:approve_ki",
    "objects:view_confidential",
    "registries:view",
    "registries:edit",
    "due_radar:view",
    "sync:admin",
}

USER_SUBSET_KEYS = {
    "objects:view",
    "objects:edit",
    "objects:approve_ki",
    "registries:view",
    "registries:edit",
    "due_radar:view",
}


def test_new_permissions_registered():
    assert NEW_STECKBRIEF_KEYS <= PERMISSION_KEYS


def test_permission_groups_populated():
    assert "Objekte" in PERMISSIONS_BY_GROUP
    assert "Registries" in PERMISSIONS_BY_GROUP
    assert "Due-Radar" in PERMISSIONS_BY_GROUP

    objekte_keys = {p.key for p in PERMISSIONS_BY_GROUP["Objekte"]}
    assert objekte_keys == {
        "objects:view",
        "objects:edit",
        "objects:approve_ki",
        "objects:view_confidential",
    }

    registries_keys = {p.key for p in PERMISSIONS_BY_GROUP["Registries"]}
    assert registries_keys == {"registries:view", "registries:edit"}

    due_keys = {p.key for p in PERMISSIONS_BY_GROUP["Due-Radar"]}
    assert due_keys == {"due_radar:view"}

    admin_keys = {p.key for p in PERMISSIONS_BY_GROUP["Admin"]}
    assert "sync:admin" in admin_keys


def test_default_user_role_has_steckbrief_subset():
    user_perms = set(DEFAULT_ROLE_PERMISSIONS["user"])
    assert USER_SUBSET_KEYS <= user_perms
    assert "objects:view_confidential" not in user_perms
    assert "sync:admin" not in user_perms


def test_default_admin_role_has_all_permissions():
    admin_perms = set(DEFAULT_ROLE_PERMISSIONS["admin"])
    assert admin_perms == PERMISSION_KEYS
    assert NEW_STECKBRIEF_KEYS <= admin_perms


def test_seed_merges_new_permissions_into_existing_user_role(db):
    session = _TestSessionLocal()
    try:
        # Alte Bestands-Rolle: nur eine Permission, kein is_system_role-Flag.
        session.add(
            Role(
                id=uuid.uuid4(),
                key="user",
                name="Standard-User",
                description="Legacy role",
                permissions=["documents:upload"],
                is_system_role=False,
            )
        )
        session.commit()
    finally:
        session.close()

    _seed_default_roles()

    session = _TestSessionLocal()
    try:
        role = session.query(Role).filter(Role.key == "user").one()
        perms = set(role.permissions or [])
        # Alte Custom-Permission bleibt erhalten.
        assert "documents:upload" in perms
        # Neue Default-Keys sind dazugekommen.
        assert USER_SUBSET_KEYS <= perms
        # Und is_system_role wird (wie zuvor) auf True gezogen.
        assert role.is_system_role is True
    finally:
        session.close()


def test_seed_merge_preserves_orphan_permission_keys():
    """Characterization-Test: der `set | set`-Merge in `_seed_default_roles`
    ist rein additiv — Keys, die NICHT (mehr) in PERMISSION_KEYS stehen,
    bleiben in `role.permissions` erhalten.

    Aktuell bewusst akzeptiert (siehe `output/implementation-artifacts/
    deferred-work.md` > "Waise-Permission-Keys"). Wenn spaeter eine
    Intersection gegen PERMISSION_KEYS eingezogen wird, muss dieser Test
    entsprechend gespiegelt werden.
    """
    orphan_key = "retired:permission_keep_me_out"
    assert orphan_key not in PERMISSION_KEYS

    session = _TestSessionLocal()
    try:
        session.add(
            Role(
                id=uuid.uuid4(),
                key="user",
                name="Standard-User",
                description="Legacy role with stale key",
                permissions=["documents:upload", orphan_key],
                is_system_role=False,
            )
        )
        session.commit()
    finally:
        session.close()

    _seed_default_roles()

    session = _TestSessionLocal()
    try:
        role = session.query(Role).filter(Role.key == "user").one()
        perms = set(role.permissions or [])
        # Waise bleibt erhalten — kein Cleanup gegen PERMISSION_KEYS.
        assert orphan_key in perms
        # Default-Merge laeuft trotzdem durch.
        assert USER_SUBSET_KEYS <= perms
        assert "documents:upload" in perms
    finally:
        session.close()


def test_known_audit_actions_includes_new_and_existing():
    known = set(KNOWN_AUDIT_ACTIONS)
    # Bestehende (Spot-Check)
    assert "document_uploaded" in known
    assert "login" in known
    assert "case_created" in known

    # Die 14 neuen Steckbrief-Actions
    expected_new = {
        "object_created",
        "object_field_updated",
        "object_photo_uploaded",
        "object_photo_deleted",
        "registry_entry_created",
        "registry_entry_updated",
        "review_queue_created",
        "review_queue_approved",
        "review_queue_rejected",
        "sync_started",
        "sync_finished",
        "sync_failed",
        "policy_violation",
        "encryption_key_missing",
    }
    assert expected_new <= known
