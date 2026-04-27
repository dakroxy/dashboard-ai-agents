"""Story 2.3 — Route-Smoke-Tests fuer Schadensfaelle-CRUD.

Deckt ab:
  AC2: Schadensfall anlegen + Liste anzeigen
  AC4: Button hidden ohne edit-Permission (UI-Seite)
  AC5: accessible_object_ids-Gate → 404
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import InsurancePolicy, Object, Schadensfall, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_object(db):
    def _make(short_code: str) -> Object:
        obj = Object(id=uuid.uuid4(), short_code=short_code, name=f"Objekt {short_code}")
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    return _make


@pytest.fixture
def admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-sch-admin",
        email="sch-admin@dbshome.de",
        name="Schaden Admin",
        permissions_extra=["objects:view", "objects:edit", "registries:view"],
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
def viewer_client(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-sch-viewer",
        email="sch-viewer@dbshome.de",
        name="Schaden Viewer",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user
    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _make_policy(db, obj_id: uuid.UUID) -> InsurancePolicy:
    p = InsurancePolicy(id=uuid.uuid4(), object_id=obj_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ---------------------------------------------------------------------------
# AC2 — Schadensfall anlegen + in Liste sehen
# ---------------------------------------------------------------------------

def test_post_schadensfall_creates_record(db, admin_client, make_object):
    obj = make_object("SCH-A1")
    policy = _make_policy(db, obj.id)

    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={
            "policy_id": str(policy.id),
            "estimated_sum": "1500.00",
            "occurred_at": "2024-06-01",
            "description": "Rohrbruch Keller",
        },
    )
    assert resp.status_code == 200

    db.expire_all()
    schaden = db.query(Schadensfall).filter(Schadensfall.policy_id == policy.id).first()
    assert schaden is not None
    assert schaden.occurred_at == date(2024, 6, 1)
    assert schaden.description == "Rohrbruch Keller"


def test_post_schadensfall_renders_in_list(db, admin_client, make_object):
    obj = make_object("SCH-A2")
    policy = _make_policy(db, obj.id)

    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={
            "policy_id": str(policy.id),
            "estimated_sum": "800",
            "description": "Glasbruch Fenster",
        },
    )
    assert resp.status_code == 200
    assert "Glasbruch Fenster" in resp.text
    assert "Schadensfälle" in resp.text


def test_get_versicherungen_shows_existing_schadensfaelle(db, admin_client, make_object):
    obj = make_object("SCH-A3")
    policy = _make_policy(db, obj.id)
    schaden = Schadensfall(
        id=uuid.uuid4(),
        policy_id=policy.id,
        description="Sturmschaden Dach",
    )
    db.add(schaden)
    db.commit()
    db.expire_all()

    resp = admin_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    assert "Sturmschaden Dach" in resp.text


# ---------------------------------------------------------------------------
# AC4 — Button hidden ohne edit-Permission (UI)
# ---------------------------------------------------------------------------

def test_button_hidden_without_edit_permission(db, viewer_client, make_object):
    obj = make_object("SCH-E1")
    resp = viewer_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    assert "Schadensfall melden" not in resp.text


def test_button_visible_with_edit_permission(db, admin_client, make_object):
    obj = make_object("SCH-E2")
    resp = admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    assert "Schadensfall melden" in resp.text


# ---------------------------------------------------------------------------
# AC5 — accessible_object_ids-Gate → 404
# ---------------------------------------------------------------------------

def test_accessible_object_ids_gate_returns_404(
    db, admin_client, make_object, monkeypatch
):
    obj = make_object("SCH-F1")
    policy = _make_policy(db, obj.id)

    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids", lambda db, user: set())

    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={"policy_id": str(policy.id), "estimated_sum": "500"},
    )
    assert resp.status_code == 404
    # Kein Schadensfall angelegt
    assert db.query(Schadensfall).filter(Schadensfall.policy_id == policy.id).count() == 0


def test_accessible_object_ids_gate_no_audit_no_db_write(
    db, admin_client, make_object, monkeypatch
):
    from app.models import AuditLog
    from app.routers import objects as router_mod

    obj = make_object("SCH-F2")
    policy = _make_policy(db, obj.id)

    monkeypatch.setattr(router_mod, "accessible_object_ids", lambda db, user: set())

    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={"policy_id": str(policy.id), "estimated_sum": "500"},
    )
    assert resp.status_code == 404

    db.expire_all()
    # Kein AuditLog-Eintrag fuer diesen Schaden
    assert db.query(Schadensfall).count() == 0
    # Kein Audit-Row fuer entity_type=schaden
    assert (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "schaden")
        .count()
    ) == 0
