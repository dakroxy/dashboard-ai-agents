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


# ---------------------------------------------------------------------------
# Review-Patches Story 2.4 (Code-Review 2026-04-27)
# ---------------------------------------------------------------------------


def test_notiz_save_max_length_enforced(admin_client, test_obj, test_eig):
    """Patch P1: 4001 Zeichen werden vom Form-Validator auf 422 gemappt."""
    too_long = "x" * 4001
    resp = admin_client.post(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}",
        data={"note": too_long},
    )
    assert resp.status_code == 422


def test_notiz_save_cross_object_returns_404(db, admin_client, admin_user, test_obj, test_eig):
    """Patch P3: Eigentuemer aus Objekt A via URL Objekt B → 404 (IDOR-Guard)."""
    other_obj = Object(
        id=uuid.uuid4(),
        short_code="MN02",
        name="MNotiz anderes Objekt",
        notes_owners={},
    )
    db.add(other_obj)
    db.commit()
    db.refresh(other_obj)

    resp = admin_client.post(
        f"/objects/{other_obj.id}/menschen-notizen/{test_eig.id}",
        data={"note": "darf nicht durchgehen"},
    )
    assert resp.status_code == 404


def test_notiz_save_whitespace_only_deletes(db, admin_client, test_obj, test_eig):
    """Patch P4: Whitespace-only-Notiz triggert nach `.strip()` den Delete-Branch."""
    test_obj.notes_owners = {str(test_eig.id): "Alt"}
    db.add(test_obj)
    db.commit()

    resp = admin_client.post(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}",
        data={"note": "   \t\n  "},
    )
    assert resp.status_code == 200

    db.expire_all()
    refreshed = db.get(Object, test_obj.id)
    assert refreshed.notes_owners.get(str(test_eig.id)) is None


def test_notiz_view_escapes_html_payload(db, admin_client, test_obj, test_eig):
    """Patch P5: XSS-Payload wird durch Jinja-Autoescape escapt, nicht roh ausgegeben."""
    payload = "<script>alert('xss')</script>"
    save_resp = admin_client.post(
        f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}",
        data={"note": payload},
    )
    assert save_resp.status_code == 200

    body = save_resp.text
    assert "<script>" not in body
    assert "&lt;script&gt;" in body or "&#x3C;script&#x3E;" in body or "&#60;script&#62;" in body
