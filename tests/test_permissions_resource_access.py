"""ResourceAccess-Matrix-Tests fuer app/permissions.py (Story 1.1).

test_permissions.py prueft die Router-Gates auf Permission-Key-Ebene.
Die Resource-Access-Tabelle (User-override vs. Role-allow) ist dort nicht
getestet — wird aber fuer v1.1 (Objekt-ACL) gebraucht und laut Story 1.1
'ab Tag 1 schreibbar'. Wenn dieser Pfad still bricht, merkt es niemand,
bis v1.1 live geht.
"""
from __future__ import annotations

import uuid

from app.models import ResourceAccess, Role, User, Workflow
from app.permissions import (
    RESOURCE_TYPE_OBJECT,
    RESOURCE_TYPE_WORKFLOW,
    accessible_resource_ids,
    can_access_resource,
    effective_permissions,
)


def _mk_user(db, *, role_id=None, email_suffix="u"):
    user = User(
        id=uuid.uuid4(),
        google_sub=f"sub-{email_suffix}-{uuid.uuid4().hex[:6]}",
        email=f"{email_suffix}-{uuid.uuid4().hex[:6]}@dbshome.de",
        name=email_suffix,
        role_id=role_id,
        permissions_extra=[],
        permissions_denied=[],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _mk_role(db, permissions: list[str]) -> Role:
    role = Role(
        id=uuid.uuid4(),
        key=f"role-{uuid.uuid4().hex[:6]}",
        name="Test-Rolle",
        description="",
        permissions=permissions,
        is_system_role=False,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def _mk_workflow(db, key: str = "wf-test") -> Workflow:
    wf = Workflow(
        id=uuid.uuid4(),
        key=f"{key}-{uuid.uuid4().hex[:6]}",
        name=key,
        description="",
        model="claude-opus-4-7",
        chat_model="claude-sonnet-4-6",
        system_prompt="",
        learning_notes="",
        active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


# ---------------------------------------------------------------------------
# effective_permissions
# ---------------------------------------------------------------------------

def test_effective_permissions_merges_role_and_extra_minus_denied(db):
    role = _mk_role(db, permissions=["workflows:view", "objects:view"])
    user = _mk_user(db, role_id=role.id)
    user.permissions_extra = ["objects:edit"]
    user.permissions_denied = ["objects:view"]
    db.commit()

    result = effective_permissions(user)
    assert result == {"workflows:view", "objects:edit"}


def test_effective_permissions_empty_for_disabled_user(db):
    import datetime as _dt

    role = _mk_role(db, permissions=["workflows:view"])
    user = _mk_user(db, role_id=role.id)
    user.disabled_at = _dt.datetime.now(tz=_dt.timezone.utc)
    db.commit()

    assert effective_permissions(user) == set()


# ---------------------------------------------------------------------------
# can_access_resource — Precedence
# ---------------------------------------------------------------------------

def test_can_access_resource_role_allow_without_override(db):
    role = _mk_role(db, permissions=[])
    user = _mk_user(db, role_id=role.id)
    wf = _mk_workflow(db)

    db.add(ResourceAccess(
        id=uuid.uuid4(),
        role_id=role.id,
        resource_type=RESOURCE_TYPE_WORKFLOW,
        resource_id=wf.id,
        mode="allow",
    ))
    db.commit()

    assert can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id) is True


def test_can_access_resource_user_deny_beats_role_allow(db):
    """User-Override 'deny' muss Role-'allow' ueberschreiben — sonst kann ein
    Admin einem einzelnen User keinen Workflow entziehen, ohne die ganze Rolle
    anzufassen."""
    role = _mk_role(db, permissions=[])
    user = _mk_user(db, role_id=role.id)
    wf = _mk_workflow(db)

    db.add(ResourceAccess(
        id=uuid.uuid4(), role_id=role.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="allow",
    ))
    db.add(ResourceAccess(
        id=uuid.uuid4(), user_id=user.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="deny",
    ))
    db.commit()

    assert can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id) is False


def test_can_access_resource_user_allow_without_role(db):
    """User-Override 'allow' reicht, auch wenn die Rolle selbst nichts erlaubt.
    Use-case: Daniel gibt einem einzelnen User Ad-hoc-Zugriff auf einen
    Workflow, ohne eine neue Rolle anzulegen."""
    user = _mk_user(db, role_id=None)
    wf = _mk_workflow(db)

    db.add(ResourceAccess(
        id=uuid.uuid4(), user_id=user.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="allow",
    ))
    db.commit()

    assert can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id) is True


def test_can_access_resource_no_override_no_role_defaults_false(db):
    user = _mk_user(db, role_id=None)
    wf = _mk_workflow(db)

    assert can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id) is False


def test_can_access_resource_disabled_user_always_false(db):
    import datetime as _dt

    role = _mk_role(db, permissions=[])
    user = _mk_user(db, role_id=role.id)
    user.disabled_at = _dt.datetime.now(tz=_dt.timezone.utc)
    wf = _mk_workflow(db)

    db.add(ResourceAccess(
        id=uuid.uuid4(), role_id=role.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="allow",
    ))
    db.commit()

    assert can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id) is False


# ---------------------------------------------------------------------------
# accessible_resource_ids
# ---------------------------------------------------------------------------

def test_accessible_resource_ids_user_deny_filters_role_allow(db):
    """Wenn die Rolle auf Workflow A erlaubt, der User aber explizit A deniet,
    darf A NICHT im Ergebnis-Set landen."""
    role = _mk_role(db, permissions=[])
    user = _mk_user(db, role_id=role.id)
    wf_a = _mk_workflow(db, "wfa")
    wf_b = _mk_workflow(db, "wfb")

    db.add_all([
        ResourceAccess(
            id=uuid.uuid4(), role_id=role.id,
            resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf_a.id, mode="allow",
        ),
        ResourceAccess(
            id=uuid.uuid4(), role_id=role.id,
            resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf_b.id, mode="allow",
        ),
        ResourceAccess(
            id=uuid.uuid4(), user_id=user.id,
            resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf_a.id, mode="deny",
        ),
    ])
    db.commit()

    result = accessible_resource_ids(db, user, RESOURCE_TYPE_WORKFLOW)
    assert result == {wf_b.id}


def test_accessible_resource_ids_user_allow_adds_to_role_allows(db):
    """User-'allow' ergaenzt die Role-allows um eine zusaetzliche Ressource."""
    role = _mk_role(db, permissions=[])
    user = _mk_user(db, role_id=role.id)
    wf_a = _mk_workflow(db, "wfa")
    wf_b = _mk_workflow(db, "wfb")

    db.add_all([
        ResourceAccess(
            id=uuid.uuid4(), role_id=role.id,
            resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf_a.id, mode="allow",
        ),
        ResourceAccess(
            id=uuid.uuid4(), user_id=user.id,
            resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf_b.id, mode="allow",
        ),
    ])
    db.commit()

    result = accessible_resource_ids(db, user, RESOURCE_TYPE_WORKFLOW)
    assert result == {wf_a.id, wf_b.id}


def test_accessible_resource_ids_scoped_to_resource_type(db):
    """Ein allow fuer resource_type='object' darf nicht in einer Workflow-Query
    landen — das Feld trennt die Scopes sauber."""
    role = _mk_role(db, permissions=[])
    user = _mk_user(db, role_id=role.id)
    wf = _mk_workflow(db)

    db.add_all([
        ResourceAccess(
            id=uuid.uuid4(), role_id=role.id,
            resource_type=RESOURCE_TYPE_OBJECT, resource_id=wf.id, mode="allow",
        ),
    ])
    db.commit()

    # Same UUID, different resource_type → must not leak into workflow access.
    assert accessible_resource_ids(db, user, RESOURCE_TYPE_WORKFLOW) == set()
    assert accessible_resource_ids(db, user, RESOURCE_TYPE_OBJECT) == {wf.id}


def test_accessible_resource_ids_disabled_user_empty(db):
    import datetime as _dt

    role = _mk_role(db, permissions=[])
    user = _mk_user(db, role_id=role.id)
    user.disabled_at = _dt.datetime.now(tz=_dt.timezone.utc)
    wf = _mk_workflow(db)

    db.add(ResourceAccess(
        id=uuid.uuid4(), role_id=role.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="allow",
    ))
    db.commit()

    assert accessible_resource_ids(db, user, RESOURCE_TYPE_WORKFLOW) == set()
