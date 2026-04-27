"""Story 2.3 — Unit-Tests fuer steckbrief_schadensfaelle Service.

Prueft:
  - create_schadensfall Provenance (AC1)
  - None-Felder werden nicht geschrieben (AC1)
  - Summen-Validierung 0, negativ, Komma-Notation (AC3)
  - Policy-Objekt-Mismatch 404 (AC1)
  - Permission-Gate 403 (AC4)
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import FieldProvenance, InsurancePolicy, Object, Schadensfall, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def obj(db):
    o = Object(id=uuid.uuid4(), short_code="SCH1", name="Test-Objekt Schaden")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture
def user(db):
    u = User(
        id=uuid.uuid4(),
        google_sub="google-sub-schaden-unit",
        email="schaden-unit@dbshome.de",
        name="Schaden Unit User",
        permissions_extra=["objects:view", "objects:edit"],
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def policy(db, obj):
    p = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def admin_client(db, user):
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


# ---------------------------------------------------------------------------
# create_schadensfall Provenance
# ---------------------------------------------------------------------------

def test_create_schadensfall_writes_provenance(db, policy, user):
    from app.services.steckbrief_schadensfaelle import create_schadensfall

    schaden = create_schadensfall(
        db, policy, user, None,
        occurred_at=date(2024, 3, 15),
        amount=Decimal("500.00"),
        description="Wasserschaden",
        unit_id=None,
    )
    db.flush()

    provs = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "schaden",
            FieldProvenance.entity_id == schaden.id,
            FieldProvenance.source == "user_edit",
        )
        .all()
    )
    field_names = {p.field_name for p in provs}
    # amount + occurred_at + description sind gesetzt; unit_id ist None → kein Row
    assert "amount" in field_names
    assert "occurred_at" in field_names
    assert "description" in field_names
    assert "unit_id" not in field_names


def test_create_schadensfall_no_unit(db, policy, user):
    from app.services.steckbrief_schadensfaelle import create_schadensfall

    schaden = create_schadensfall(
        db, policy, user, None,
        occurred_at=None,
        amount=Decimal("250.00"),
        description=None,
        unit_id=None,
    )
    db.flush()

    provs = (
        db.query(FieldProvenance)
        .filter(FieldProvenance.entity_id == schaden.id)
        .all()
    )
    field_names = {p.field_name for p in provs}
    assert "unit_id" not in field_names
    assert "occurred_at" not in field_names
    assert "description" not in field_names
    assert "amount" in field_names


# ---------------------------------------------------------------------------
# Summen-Validierung (AC3)
# ---------------------------------------------------------------------------

def test_amount_validation_zero(db, admin_client, obj, policy):
    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={"policy_id": str(policy.id), "estimated_sum": "0"},
    )
    assert resp.status_code == 422
    assert db.query(Schadensfall).filter(Schadensfall.policy_id == policy.id).count() == 0


def test_amount_validation_negative(db, admin_client, obj, policy):
    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={"policy_id": str(policy.id), "estimated_sum": "-10"},
    )
    assert resp.status_code == 422
    assert db.query(Schadensfall).filter(Schadensfall.policy_id == policy.id).count() == 0


def test_amount_validation_comma_decimal(db, admin_client, obj, policy):
    # "1.500,50" — Deutsche Notation mit Tausender-Punkt + Komma-Dezimal
    # Decimal("1.500,50".replace(",", ".")) → Decimal("1.500.50") → InvalidOperation → 422
    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={"policy_id": str(policy.id), "estimated_sum": "1.500,50"},
    )
    assert resp.status_code == 422
    assert db.query(Schadensfall).filter(Schadensfall.policy_id == policy.id).count() == 0


# ---------------------------------------------------------------------------
# Policy-Objekt-Mismatch (AC1)
# ---------------------------------------------------------------------------

def test_policy_object_mismatch_gives_404(db, admin_client, obj):
    # Policy gehoert einem anderen Objekt
    other_obj = Object(id=uuid.uuid4(), short_code="SCH-OTHER", name="Anderes Objekt")
    db.add(other_obj)
    db.commit()
    other_policy = InsurancePolicy(id=uuid.uuid4(), object_id=other_obj.id)
    db.add(other_policy)
    db.commit()

    resp = admin_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={"policy_id": str(other_policy.id), "estimated_sum": "500"},
    )
    assert resp.status_code == 404
    assert db.query(Schadensfall).filter(Schadensfall.policy_id == other_policy.id).count() == 0


# ---------------------------------------------------------------------------
# Permission-Gate (AC4)
# ---------------------------------------------------------------------------

def test_permission_gate_returns_403(db, obj, policy):
    viewer = User(
        id=uuid.uuid4(),
        google_sub="google-sub-viewer",
        email="viewer@dbshome.de",
        name="Viewer",
        permissions_extra=["objects:view"],
    )
    db.add(viewer)
    db.commit()

    def override_db():
        yield db

    def override_user():
        return viewer

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        resp = c.post(
            f"/objects/{obj.id}/schadensfaelle",
            data={"policy_id": str(policy.id), "estimated_sum": "500"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 403
    assert db.query(Schadensfall).filter(Schadensfall.policy_id == policy.id).count() == 0
