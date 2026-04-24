"""Story 2.1 — Route-Smoke-Tests fuer Policen-CRUD + Versicherer-Registry.

Deckt ab:
  AC1: Neue Police anlegen (alle Felder + Teilfelder)
  AC2: Policen-Liste anzeigen + Edit + Delete
  AC3: Neuer Versicherer via Inline-Sub-Formular
  AC4: Datumsvalidierung
  AC5: Permission-Gate
  AC6: accessible_object_ids auf allen Policen-Routes
  AC7: Tests laufen gruenthrough (write_gate_coverage weiter gruen)
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import AuditLog, FieldProvenance, InsurancePolicy, Object, User, Versicherer


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
        google_sub="google-sub-pol-admin",
        email="pol-admin@dbshome.de",
        name="Policen Admin",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "registries:view",
            "registries:edit",
            "audit_log:view",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def steckbrief_admin_client(db, admin_user):
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
        google_sub="google-sub-pol-viewer",
        email="pol-viewer@dbshome.de",
        name="Policen Viewer",
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


@pytest.fixture
def editor_no_registries_client(db):
    """User mit objects:edit aber OHNE registries:edit."""
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-pol-edit-noreg",
        email="pol-edit-noreg@dbshome.de",
        name="Editor No Registries",
        permissions_extra=["objects:view", "objects:edit"],
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


@pytest.fixture
def restricted_admin_client(db):
    """Admin-User, dem ein Objekt explizit via resource_access verweigert wird."""
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-pol-restricted",
        email="pol-restricted@dbshome.de",
        name="Restricted Admin",
        permissions_extra=["objects:view", "objects:edit", "registries:edit"],
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
        yield c, user
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC1 — Neue Police anlegen
# ---------------------------------------------------------------------------

def test_post_policen_creates_policy_with_all_fields(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("POL-A1")
    v = Versicherer(id=uuid.uuid4(), name="Allianz AG", contact_info={})
    db.add(v)
    db.commit()

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={
            "versicherer_id": str(v.id),
            "police_number": "12345/2024",
            "produkt_typ": "Haftpflicht",
            "start_date": "2024-01-01",
            "end_date": "2025-12-31",
            "next_main_due": "2025-12-31",
            "notice_period_months": "3",
            "praemie": "1200.00",
        },
    )
    assert resp.status_code == 200

    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None
    assert policy.police_number == "12345/2024"
    assert policy.produkt_typ == "Haftpflicht"
    assert str(policy.versicherer_id) == str(v.id)


def test_post_policen_with_partial_fields(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("POL-A2")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "500.00"},
    )
    assert resp.status_code == 200

    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None
    assert policy.police_number is None
    assert policy.produkt_typ is None


# ---------------------------------------------------------------------------
# AC2 — Policen-Liste + Edit + Delete
# ---------------------------------------------------------------------------

def test_get_versicherungen_section_shows_existing_policies(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("POL-B1")
    p1 = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id, police_number="P001")
    p2 = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id, police_number="P002")
    db.add_all([p1, p2])
    db.commit()

    resp = steckbrief_admin_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    body = resp.text
    assert "P001" in body
    assert "P002" in body
    # AC2 + Deep-Link (Story 2.6) + Wartungs-Sub-Block (Story 2.2)
    assert f'id="policy-{p1.id}"' in body
    assert f'data-police-id="{p1.id}"' in body
    assert f'id="policy-{p2.id}"' in body
    assert f'data-police-id="{p2.id}"' in body
    # Edit + Delete-Buttons (Admin hat objects:edit)
    assert "Bearbeiten" in body
    assert "Löschen" in body


def test_delete_police_removes_row_and_writes_audit(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("POL-B2")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={"police_number": "TO-DELETE"},
    )
    assert resp.status_code == 200
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None

    resp2 = steckbrief_admin_client.delete(f"/objects/{obj.id}/policen/{policy.id}")
    assert resp2.status_code == 200

    db.expire_all()
    assert db.get(InsurancePolicy, policy.id) is None
    assert "TO-DELETE" not in resp2.text

    audit_entry = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "registry_entry_updated",
            AuditLog.entity_type == "police",
        )
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.details_json["action"] == "delete"


def test_put_police_updates_fields(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("POL-B3")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "1000.00", "police_number": "P-EDIT"},
    )
    assert resp.status_code == 200

    db.expire_all()
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    prov_count_before = (
        db.query(FieldProvenance)
        .filter(FieldProvenance.entity_id == policy.id)
        .count()
    )

    resp2 = steckbrief_admin_client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={"praemie": "1500.00", "police_number": "P-EDIT"},
    )
    assert resp2.status_code == 200

    db.expire_all()
    updated = db.get(InsurancePolicy, policy.id)
    assert updated.praemie is not None
    from decimal import Decimal
    assert updated.praemie == Decimal("1500.00")


# ---------------------------------------------------------------------------
# AC3 — Neuer Versicherer
# ---------------------------------------------------------------------------

def test_get_versicherer_new_form_returns_fragment(steckbrief_admin_client):
    resp = steckbrief_admin_client.get("/registries/versicherer/new-form")
    assert resp.status_code == 200
    body = resp.text
    assert 'name="name"' in body
    assert 'name="adresse"' in body
    assert 'name="kontakt_email"' in body
    assert 'name="kontakt_tel"' in body


def test_post_versicherer_creates_and_returns_oob_swap(db, steckbrief_admin_client):
    resp = steckbrief_admin_client.post(
        "/registries/versicherer",
        data={"name": "Neue Versicherung AG", "adresse": "Teststr. 1"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert 'id="versicherer-dropdown"' in body
    assert 'hx-swap-oob="true"' in body
    assert "Neue Versicherung AG" in body
    # Neuer Versicherer ist selected
    assert "selected" in body

    db.expire_all()
    v = db.query(Versicherer).filter(Versicherer.name == "Neue Versicherung AG").first()
    assert v is not None
    assert v.contact_info.get("adresse") == "Teststr. 1"


def test_post_versicherer_empty_name_returns_422_with_error(steckbrief_admin_client):
    resp = steckbrief_admin_client.post(
        "/registries/versicherer",
        data={"name": "   "},
    )
    assert resp.status_code == 422
    assert "Name ist Pflichtfeld" in resp.text


# ---------------------------------------------------------------------------
# AC4 — Datumsvalidierung
# ---------------------------------------------------------------------------

def test_post_policen_with_invalid_dates_returns_422(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("POL-D1")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={
            "start_date": "2025-06-01",
            "next_main_due": "2025-01-01",
        },
    )
    assert resp.status_code == 422
    assert "Ablauf-Datum" in resp.text
    assert db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).count() == 0


def test_put_policen_with_invalid_dates_returns_422(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("POL-D2")
    steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "100.00"},
    )
    db.expire_all()
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None

    resp2 = steckbrief_admin_client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={
            "start_date": "2025-06-01",
            "next_main_due": "2025-01-01",
        },
    )
    assert resp2.status_code == 422
    # Felder unveraendert
    db.expire_all()
    unchanged = db.get(InsurancePolicy, policy.id)
    assert unchanged.start_date is None
    assert unchanged.next_main_due is None


# ---------------------------------------------------------------------------
# AC5 — Permission-Gate
# ---------------------------------------------------------------------------

def test_policen_post_403_for_viewer(db, viewer_client, make_object):
    obj = make_object("POL-E1")
    resp = viewer_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "100.00"},
    )
    assert resp.status_code == 403
    assert db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).count() == 0


def test_policen_delete_403_for_viewer(
    db, viewer_client, make_object
):
    obj = make_object("POL-E2")
    # Police direkt in DB anlegen — kein zweiter Client noetig
    policy = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id, police_number="STAY")
    db.add(policy)
    db.commit()

    resp = viewer_client.delete(f"/objects/{obj.id}/policen/{policy.id}")
    assert resp.status_code == 403
    db.expire_all()
    assert db.get(InsurancePolicy, policy.id) is not None


def test_policen_edit_form_get_403_for_viewer(
    db, viewer_client, make_object
):
    obj = make_object("POL-E3")
    policy = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id, police_number="X")
    db.add(policy)
    db.commit()

    resp = viewer_client.get(f"/objects/{obj.id}/policen/{policy.id}/edit-form")
    assert resp.status_code == 403


def test_versicherer_post_403_for_user_without_registries_edit(
    editor_no_registries_client,
):
    resp = editor_no_registries_client.post(
        "/registries/versicherer",
        data={"name": "Unauthorized"},
    )
    assert resp.status_code == 403


def test_versicherungen_section_hides_buttons_for_viewer(
    db, viewer_client, make_object
):
    obj = make_object("POL-E5")
    resp = viewer_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    body = resp.text
    assert "Neue Police" not in body
    assert "Löschen" not in body


# ---------------------------------------------------------------------------
# AC6 — accessible_object_ids (Retro-P2-Regression)
# Monkeypatch-basiert (wie test_detail_404_when_object_not_in_accessible_ids),
# weil v1 von accessible_object_ids alle Objekte zurueckgibt. Die Tests
# verifizieren dass der Check strukturell in jeder Route vorhanden ist.
# ---------------------------------------------------------------------------

def test_policen_post_404_when_object_not_accessible(
    steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("AC6-P")
    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids", lambda db, user: set())
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen", data={"praemie": "100.00"}
    )
    assert resp.status_code == 404


def test_policen_put_404_when_object_not_accessible(
    db, steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("AC6-U")
    policy = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(policy)
    db.commit()
    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids", lambda db, user: set())
    resp = steckbrief_admin_client.put(
        f"/objects/{obj.id}/policen/{policy.id}", data={"praemie": "99.00"}
    )
    assert resp.status_code == 404


def test_policen_delete_404_when_object_not_accessible(
    db, steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("AC6-D")
    policy = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(policy)
    db.commit()
    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids", lambda db, user: set())
    resp = steckbrief_admin_client.delete(f"/objects/{obj.id}/policen/{policy.id}")
    assert resp.status_code == 404


def test_sections_versicherungen_404_when_object_not_accessible(
    steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("AC6-S")
    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids", lambda db, user: set())
    resp = steckbrief_admin_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 404


def test_policen_edit_form_404_when_object_not_accessible(
    db, steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("AC6-E")
    policy = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(policy)
    db.commit()
    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids", lambda db, user: set())
    resp = steckbrief_admin_client.get(f"/objects/{obj.id}/policen/{policy.id}/edit-form")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cross-Object-Policy-Guard
# ---------------------------------------------------------------------------

def test_put_police_from_wrong_object_returns_404(
    db, steckbrief_admin_client, make_object
):
    obj_a = make_object("POL-CO1")
    obj_b = make_object("POL-CO2")
    policy_a = InsurancePolicy(id=uuid.uuid4(), object_id=obj_a.id)
    db.add(policy_a)
    db.commit()

    resp = steckbrief_admin_client.put(
        f"/objects/{obj_b.id}/policen/{policy_a.id}",
        data={"praemie": "99.00"},
    )
    assert resp.status_code == 404


def test_delete_police_from_wrong_object_returns_404(
    db, steckbrief_admin_client, make_object
):
    obj_a = make_object("POL-CO3")
    obj_b = make_object("POL-CO4")
    policy_a = InsurancePolicy(id=uuid.uuid4(), object_id=obj_a.id)
    db.add(policy_a)
    db.commit()

    resp = steckbrief_admin_client.delete(
        f"/objects/{obj_b.id}/policen/{policy_a.id}"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression — write_gate_coverage
# ---------------------------------------------------------------------------

def test_write_gate_coverage_still_green():
    from tests.test_write_gate_coverage import test_no_direct_writes_to_cd1_entities_textscan
    test_no_direct_writes_to_cd1_entities_textscan()
