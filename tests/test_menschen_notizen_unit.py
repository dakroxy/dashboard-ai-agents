"""Story 2.4 — Menschen-Notizen admin-only.

Deckt ACs ab:
  * AC2: normaler User ohne view_confidential bekommt 403 auf alle Endpoints
  * AC3: Notiz schreiben via write_field_human + AuditLog + FieldProvenance
  * AC5: alle Tests gruen mit pytest -x
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import AuditLog, Eigentuemer, FieldProvenance, Object, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-mnotiz-admin",
        email="mnotiz-admin@dbshome.de",
        name="MNotiz Admin",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:view_confidential",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def normal_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-mnotiz-normal",
        email="mnotiz-normal@dbshome.de",
        name="MNotiz Normal",
        permissions_extra=["objects:view", "objects:edit"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_client(db, admin_user):
    def override_db():
        yield db

    def override_user():
        return admin_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user
    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def normal_client(db, normal_user):
    def override_db():
        yield db

    def override_user():
        return normal_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user
    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def test_obj(db):
    obj = Object(
        id=uuid.uuid4(),
        short_code="MN01",
        name="MNotiz Testobjekt",
        notes_owners={},
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@pytest.fixture
def test_eig(db, test_obj):
    eig = Eigentuemer(
        id=uuid.uuid4(),
        object_id=test_obj.id,
        name="Max Mustermann",
    )
    db.add(eig)
    db.commit()
    db.refresh(eig)
    return eig


# ---------------------------------------------------------------------------
# AC3 — Notiz schreiben via Write-Gate + AuditLog + FieldProvenance
# ---------------------------------------------------------------------------

def test_notiz_save_writes_via_write_gate(db, admin_client, test_obj, test_eig):
    resp = admin_client.post(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}",
        data={"note": "Beirat"},
    )
    assert resp.status_code == 200

    prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == test_obj.id,
            FieldProvenance.field_name == "notes_owners",
            FieldProvenance.source == "user_edit",
        )
        .first()
    )
    assert prov is not None

    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "object_field_updated",
            AuditLog.entity_id == test_obj.id,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.details_json["field"] == "notes_owners"

    db.expire_all()
    refreshed = db.get(Object, test_obj.id)
    assert refreshed.notes_owners[str(test_eig.id)] == "Beirat"


# ---------------------------------------------------------------------------
# Leere Notiz loescht den Eintrag
# ---------------------------------------------------------------------------

def test_notiz_delete_on_empty_string(db, admin_client, test_obj, test_eig):
    test_obj.notes_owners = {str(test_eig.id): "Alt"}
    db.add(test_obj)
    db.commit()

    resp = admin_client.post(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}",
        data={"note": ""},
    )
    assert resp.status_code == 200

    db.expire_all()
    refreshed = db.get(Object, test_obj.id)
    assert refreshed.notes_owners.get(str(test_eig.id)) is None


# ---------------------------------------------------------------------------
# AC2 — 403 fuer User ohne view_confidential
# ---------------------------------------------------------------------------

def test_notiz_save_blocked_without_view_confidential(
    db, normal_client, test_obj, test_eig
):
    resp = normal_client.post(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}",
        data={"note": "X"},
    )
    assert resp.status_code == 403


def test_notiz_edit_get_blocked_without_view_confidential(
    normal_client, test_obj, test_eig
):
    resp = normal_client.get(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}/edit",
    )
    assert resp.status_code == 403


def test_notiz_view_get_blocked_without_view_confidential(
    normal_client, test_obj, test_eig
):
    resp = normal_client.get(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}/view",
    )
    assert resp.status_code == 403
