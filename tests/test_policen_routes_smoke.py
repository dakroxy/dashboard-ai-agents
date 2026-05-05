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
from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN


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
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
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
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
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
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
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
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
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
    assert f'data-policy-id="{p1.id}"' in body
    assert f'id="policy-{p2.id}"' in body
    assert f'data-policy-id="{p2.id}"' in body
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
    monkeypatch.setattr(router_mod, "accessible_object_ids_for_request", lambda request, db, user: set())
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
    monkeypatch.setattr(router_mod, "accessible_object_ids_for_request", lambda request, db, user: set())
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
    monkeypatch.setattr(router_mod, "accessible_object_ids_for_request", lambda request, db, user: set())
    resp = steckbrief_admin_client.delete(f"/objects/{obj.id}/policen/{policy.id}")
    assert resp.status_code == 404


def test_sections_versicherungen_404_when_object_not_accessible(
    steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("AC6-S")
    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids_for_request", lambda request, db, user: set())
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
    monkeypatch.setattr(router_mod, "accessible_object_ids_for_request", lambda request, db, user: set())
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
# Tranche A — Permission-Gate Positiv-Path (Story 2.1)
# Explizit benannte Admin-200-Tests fuer Create/Update/Delete. Schuetzen
# gegen Regression bei Dependency- oder Schema-Aenderungen, die den
# autorisierten Happy-Path brechen koennten.
# ---------------------------------------------------------------------------

def test_create_police_returns_200_for_admin_with_objects_edit(
    db, steckbrief_admin_client, make_object
):
    """Tranche A: Admin mit objects:edit POSTet eine vollstaendige Police →
    200, neue Row in DB inkl. FK auf Versicherer + Praemie."""
    obj = make_object("POL-A-OK1")
    v = Versicherer(id=uuid.uuid4(), name="Tranche-A Allianz", contact_info={})
    db.add(v)
    db.commit()

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={
            "versicherer_id": str(v.id),
            "police_number": "TA-001",
            "produkt_typ": "Wohngebaeude",
            "praemie": "850.00",
        },
    )
    # Whole-Section-Render → 200, kein Redirect.
    assert resp.status_code == 200

    db.expire_all()
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None
    assert policy.police_number == "TA-001"
    assert policy.produkt_typ == "Wohngebaeude"
    assert str(policy.versicherer_id) == str(v.id)
    from decimal import Decimal
    assert policy.praemie == Decimal("850.00")


def test_update_police_returns_200_for_admin(
    db, steckbrief_admin_client, make_object
):
    """Tranche A: Admin PUTet eine bestehende Police mit geaendertem Feld →
    200, neuer Wert in DB."""
    obj = make_object("POL-A-OK2")
    policy = InsurancePolicy(
        id=uuid.uuid4(),
        object_id=obj.id,
        police_number="TA-OLD",
    )
    db.add(policy)
    db.commit()

    resp = steckbrief_admin_client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={
            "police_number": "TA-NEW",
            "praemie": "999.00",
        },
    )
    assert resp.status_code == 200

    db.expire_all()
    updated = db.get(InsurancePolicy, policy.id)
    assert updated is not None
    assert updated.police_number == "TA-NEW"
    from decimal import Decimal
    assert updated.praemie == Decimal("999.00")


def test_delete_police_returns_200_for_admin(
    db, steckbrief_admin_client, make_object
):
    """Tranche A: Admin DELETEt eine bestehende Police → 200, Police-Row
    nicht mehr in der DB."""
    obj = make_object("POL-A-OK3")
    policy = InsurancePolicy(
        id=uuid.uuid4(),
        object_id=obj.id,
        police_number="TA-DEL",
    )
    db.add(policy)
    db.commit()
    policy_id = policy.id

    resp = steckbrief_admin_client.delete(f"/objects/{obj.id}/policen/{policy_id}")
    assert resp.status_code == 200

    db.expire_all()
    assert db.get(InsurancePolicy, policy_id) is None


# ---------------------------------------------------------------------------
# Tranche B — Numerische Boundaries + Form-Error-UX (Story 2.1 Review-Defer)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason="Story 2.1 Review-Defer: _parse_decimal hat keinen Negative-Check "
           "(notice_period_months akzeptiert ebenfalls negative Werte). "
           "Range-Check vor Produktiv-Rollout aufnehmen."
)
def test_create_police_rejects_praemie_negative(
    db, steckbrief_admin_client, make_object
):
    """negative Praemie -> 422, keine DB-Row."""
    obj = make_object("POL-NEG")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "-100"},
    )
    assert resp.status_code == 422
    assert db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).count() == 0


@pytest.mark.xfail(
    reason="Story 2.1 Review-Defer: Praemie > Numeric(12,2) fuehrt zu 500 "
           "beim DB-Commit, kein expliziter Overflow-Check im Router."
)
def test_create_police_rejects_praemie_overflow(
    db, steckbrief_admin_client, make_object
):
    """Praemie > 12,2 Numeric -> 422 oder klar gehandhabt (kein 500)."""
    obj = make_object("POL-OF")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "99999999999999.99"},
    )
    assert resp.status_code in {422, 400}
    assert db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).count() == 0


@pytest.mark.xfail(
    reason="Story 2.1 Review-Defer: notice_period_months akzeptiert negative "
           "Werte; HTML min='0' ist nur client-side. Range-Check fehlt."
)
def test_create_police_rejects_notice_period_negative(
    db, steckbrief_admin_client, make_object
):
    """notice_period_months=-1 -> 422, keine DB-Row."""
    obj = make_object("POL-NMO")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "100.00", "notice_period_months": "-1"},
    )
    assert resp.status_code == 422
    assert db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).count() == 0


@pytest.mark.xfail(
    reason="Story 2.1 Review-Defer (UX-Polish): Bei 422 wird form_error "
           "gerendert, aber #neue-police-form bleibt class='hidden' -> User "
           "sieht den Fehlertext ohne das Form. Sticky-Form-Visible nicht im Scope."
)
def test_create_police_form_error_renders_sticky_form_visible(
    db, steckbrief_admin_client, make_object
):
    """Bei 422 ist die Form sichtbar (nicht hidden) und enthaelt Werte."""
    obj = make_object("POL-STK")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={
            "police_number": "STICKY-001",
            "start_date": "2025-06-01",
            "next_main_due": "2025-01-01",
        },
    )
    assert resp.status_code == 422
    body = resp.text
    # Form-Error im Body
    assert "Ablauf-Datum" in body
    # Form-Container darf nicht class="hidden" haben (sticky-visible)
    # Heuristik: Sucht nach `id="neue-police-form"` ohne `hidden`-Klasse
    assert 'id="neue-police-form" class="hidden' not in body, (
        "Form muss sichtbar bleiben, damit User den Fehler korrigieren kann"
    )
    # Sticky-Form-Daten: User-Eingabe bleibt erhalten
    assert "STICKY-001" in body


# ---------------------------------------------------------------------------
# Regression — write_gate_coverage
# ---------------------------------------------------------------------------

def test_write_gate_coverage_still_green():
    from tests.test_write_gate_coverage import test_no_direct_writes_to_cd1_entities_textscan
    test_no_direct_writes_to_cd1_entities_textscan()
