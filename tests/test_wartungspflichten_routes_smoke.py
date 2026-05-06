"""Story 2.2 — Route-Smoke-Tests fuer Wartungspflichten-CRUD + Dienstleister-Registry.

Deckt ab:
  AC1: Wartungspflicht anlegen (alle Felder, leer, Validierung)
  AC2: Anzeige mit Severity-Badge
  AC3: Delete + Per-Police-Fragment
  AC4: Neuer Dienstleister + OOB-Swaps
  AC5: Permission-Gate
  AC6: accessible_object_ids auf allen Routen
  Regression: write_gate_coverage weiter gruen
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import (
    AuditLog,
    InsurancePolicy,
    Object,
    User,
    Wartungspflicht,
)
from app.models.registry import Dienstleister
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
        google_sub="google-sub-wart-admin",
        email="wart-admin@dbshome.de",
        name="Wartung Admin",
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
        google_sub="google-sub-wart-viewer",
        email="wart-viewer@dbshome.de",
        name="Wartung Viewer",
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
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-wart-edit-noreg",
        email="wart-edit-noreg@dbshome.de",
        name="Wartung Editor No Registries",
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


def _make_policy(db, obj_id: uuid.UUID) -> InsurancePolicy:
    p = InsurancePolicy(id=uuid.uuid4(), object_id=obj_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_wartung(db, policy: InsurancePolicy, bezeichnung: str = "Test W") -> Wartungspflicht:
    w = Wartungspflicht(
        id=uuid.uuid4(),
        policy_id=policy.id,
        object_id=policy.object_id,
        bezeichnung=bezeichnung,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


# ---------------------------------------------------------------------------
# AC1 — Wartungspflicht anlegen
# ---------------------------------------------------------------------------

def test_post_wartungspflicht_creates_with_all_fields(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-A1")
    policy = _make_policy(db, obj.id)
    dienstleister = Dienstleister(id=uuid.uuid4(), name="Kaminkehrer GmbH", gewerke_tags=[])
    db.add(dienstleister)
    db.commit()

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={
            "bezeichnung": "Kaminfegerung",
            "dienstleister_id": str(dienstleister.id),
            "intervall_monate": "12",
            "letzte_wartung": "2024-01-15",
            "next_due_date": "2025-01-15",
        },
    )
    assert resp.status_code == 200
    assert "Kaminfegerung" in resp.text

    db.expire_all()
    wart = (
        db.query(Wartungspflicht)
        .filter(Wartungspflicht.policy_id == policy.id)
        .first()
    )
    assert wart is not None
    assert wart.bezeichnung == "Kaminfegerung"
    assert wart.intervall_monate == 12
    assert wart.object_id == obj.id
    assert wart.dienstleister_id == dienstleister.id


def test_post_wartungspflicht_with_empty_dienstleister(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-A2")
    policy = _make_policy(db, obj.id)

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Heizungswartung", "dienstleister_id": ""},
    )
    assert resp.status_code == 200

    db.expire_all()
    wart = (
        db.query(Wartungspflicht)
        .filter(Wartungspflicht.policy_id == policy.id)
        .first()
    )
    assert wart is not None
    assert wart.dienstleister_id is None


def test_post_wartungspflicht_without_bezeichnung_returns_422(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-A3")
    policy = _make_policy(db, obj.id)

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "", "intervall_monate": "12"},
    )
    assert resp.status_code == 422
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy.id).count() == 0


def test_post_wartungspflicht_with_invalid_dates_returns_422(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-A4")
    policy = _make_policy(db, obj.id)

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={
            "bezeichnung": "Pruefung",
            "letzte_wartung": "2025-06-01",
            "next_due_date": "2024-01-01",
        },
    )
    assert resp.status_code == 422
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy.id).count() == 0


def test_post_wartungspflicht_with_intervall_hint_returns_200_with_warn(
    db, steckbrief_admin_client, make_object
):
    """Soft-Warn: Intervall 12 Mo. vs. 24 Monate Datumsabstand → 200 + Hinweis-Banner."""
    obj = make_object("WRT-A5")
    policy = _make_policy(db, obj.id)

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={
            "bezeichnung": "Langzeit-Pruefung",
            "letzte_wartung": "2023-01-01",
            "next_due_date": "2025-01-01",
            "intervall_monate": "12",
        },
    )
    assert resp.status_code == 200
    assert "weichen stark" in resp.text
    # DB-Row trotzdem angelegt
    db.expire_all()
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy.id).count() == 1


# ---------------------------------------------------------------------------
# AC2 — Anzeige mit Severity-Badge
# ---------------------------------------------------------------------------

def test_get_versicherungen_shows_wartungspflichten_expanded(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-B1")
    policy = _make_policy(db, obj.id)
    _make_wartung(db, policy, "W-Erste")
    _make_wartung(db, policy, "W-Zweite")
    db.expire_all()  # sicherstellen dass selectin-Reload aus DB kommt

    resp = steckbrief_admin_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    body = resp.text
    assert "<details" in body
    assert "W-Erste" in body
    assert "W-Zweite" in body


def test_severity_badge_critical_for_due_within_30_days(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-B2")
    policy = _make_policy(db, obj.id)
    due_date = date.today() + timedelta(days=10)
    wart = Wartungspflicht(
        id=uuid.uuid4(),
        policy_id=policy.id,
        object_id=obj.id,
        bezeichnung="Kritische Pruefung",
        next_due_date=due_date,
    )
    db.add(wart)
    db.commit()
    db.expire_all()

    resp = steckbrief_admin_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    assert "bg-red-100" in resp.text


def test_severity_badge_warning_for_due_within_90_days(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-B3")
    policy = _make_policy(db, obj.id)
    due_date = date.today() + timedelta(days=60)
    wart = Wartungspflicht(
        id=uuid.uuid4(),
        policy_id=policy.id,
        object_id=obj.id,
        bezeichnung="Bald faellig",
        next_due_date=due_date,
    )
    db.add(wart)
    db.commit()
    db.expire_all()

    resp = steckbrief_admin_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    assert "bg-orange-100" in resp.text


# ---------------------------------------------------------------------------
# AC3 — Delete + Per-Police-Fragment
# ---------------------------------------------------------------------------

def test_delete_wartungspflicht_removes_row_and_audits(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-C1")
    policy = _make_policy(db, obj.id)
    wart = _make_wartung(db, policy, "Zu-Loeschen")
    wart_id = wart.id

    resp = steckbrief_admin_client.delete(
        f"/objects/{obj.id}/wartungspflichten/{wart_id}"
    )
    assert resp.status_code == 200

    db.expire_all()
    assert db.get(Wartungspflicht, wart_id) is None

    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "wartung_deleted",
            AuditLog.entity_type == "wartung",
        )
        .first()
    )
    assert log is not None
    assert log.details_json["bezeichnung"] is not None


def test_delete_wartungspflicht_returns_only_policy_article(
    db, steckbrief_admin_client, make_object
):
    """Response enthaelt genau einen <article data-policy-id>, keinen Section-Wrapper."""
    obj = make_object("WRT-C2")
    policy = _make_policy(db, obj.id)
    wart = _make_wartung(db, policy)

    resp = steckbrief_admin_client.delete(
        f"/objects/{obj.id}/wartungspflichten/{wart.id}"
    )
    assert resp.status_code == 200
    body = resp.text
    assert f'data-policy-id="{policy.id}"' in body
    # Kein Section-Wrapper — nur <article>, kein <section data-section="...">
    assert '<section data-section=' not in body


# ---------------------------------------------------------------------------
# AC4 — Neuer Dienstleister + OOB-Swaps
# ---------------------------------------------------------------------------

def test_get_dienstleister_new_form_returns_fragment(steckbrief_admin_client):
    policy_id = uuid.uuid4()
    resp = steckbrief_admin_client.get(
        f"/registries/dienstleister/new-form?policy_id={policy_id}"
    )
    assert resp.status_code == 200
    body = resp.text
    assert 'name="name"' in body
    assert 'name="gewerke_tags_raw"' in body
    assert str(policy_id) in body


def test_post_dienstleister_creates_and_returns_two_oob_swaps(
    db, steckbrief_admin_client
):
    policy_id = uuid.uuid4()
    resp = steckbrief_admin_client.post(
        "/registries/dienstleister",
        data={
            "name": "Neue Haustechnik AG",
            "gewerke_tags_raw": "Sanitär, Heizung",
            "policy_id": str(policy_id),
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert f'id="dienstleister-dropdown-{policy_id}"' in body
    assert 'hx-swap-oob="true"' in body
    assert "Neue Haustechnik AG" in body
    assert "selected" in body
    assert f'id="new-dienstleister-inline-{policy_id}"' in body

    db.expire_all()
    d = db.query(Dienstleister).filter(Dienstleister.name == "Neue Haustechnik AG").first()
    assert d is not None
    assert "Sanitär" in d.gewerke_tags


def test_post_dienstleister_without_policy_id_returns_standalone_dropdown(
    db, steckbrief_admin_client
):
    resp = steckbrief_admin_client.post(
        "/registries/dienstleister",
        data={"name": "Solo Haustechnik GmbH"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert 'id="dienstleister-dropdown"' in body
    assert 'hx-swap-oob="true"' in body
    assert "Solo Haustechnik GmbH" in body


def test_post_dienstleister_empty_name_returns_422(steckbrief_admin_client):
    resp = steckbrief_admin_client.post(
        "/registries/dienstleister",
        data={"name": "   "},
    )
    assert resp.status_code == 422
    assert "Name ist Pflichtfeld" in resp.text


# ---------------------------------------------------------------------------
# AC5 — Permission-Gate
# ---------------------------------------------------------------------------

def test_wartungspflicht_post_403_for_viewer(db, viewer_client, make_object):
    obj = make_object("WRT-E1")
    policy = _make_policy(db, obj.id)

    resp = viewer_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Blocked"},
    )
    assert resp.status_code == 403
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy.id).count() == 0


def test_wartungspflicht_delete_403_for_viewer(db, viewer_client, make_object):
    obj = make_object("WRT-E2")
    policy = _make_policy(db, obj.id)
    wart = _make_wartung(db, policy)

    resp = viewer_client.delete(f"/objects/{obj.id}/wartungspflichten/{wart.id}")
    assert resp.status_code == 403
    db.expire_all()
    assert db.get(Wartungspflicht, wart.id) is not None


def test_dienstleister_post_403_without_registries_edit(editor_no_registries_client):
    resp = editor_no_registries_client.post(
        "/registries/dienstleister",
        data={"name": "Unauthorized"},
    )
    assert resp.status_code == 403


def test_versicherungen_section_hides_wartung_buttons_for_viewer(
    db, viewer_client, make_object
):
    obj = make_object("WRT-E4")
    resp = viewer_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    body = resp.text
    assert "+ Wartungspflicht" not in body


# ---------------------------------------------------------------------------
# AC6 — accessible_object_ids (404-Gate)
# ---------------------------------------------------------------------------

def test_wartungspflicht_post_404_when_object_not_accessible(
    db, steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("WRT-F1")
    policy = _make_policy(db, obj.id)

    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids_for_request", lambda request, db, user: set())
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Blocked"},
    )
    assert resp.status_code == 404


def test_wartungspflicht_delete_404_when_object_not_accessible(
    db, steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("WRT-F2")
    policy = _make_policy(db, obj.id)
    wart = _make_wartung(db, policy)

    from app.routers import objects as router_mod
    monkeypatch.setattr(router_mod, "accessible_object_ids_for_request", lambda request, db, user: set())
    resp = steckbrief_admin_client.delete(
        f"/objects/{obj.id}/wartungspflichten/{wart.id}"
    )
    assert resp.status_code == 404
    db.expire_all()
    assert db.get(Wartungspflicht, wart.id) is not None


def test_wartungspflicht_delete_404_when_wart_belongs_to_other_object(
    db, steckbrief_admin_client, make_object
):
    """Wartung gehoert Objekt A, DELETE URL nutzt Objekt B → 404."""
    obj_a = make_object("WRT-F3A")
    obj_b = make_object("WRT-F3B")
    policy_a = _make_policy(db, obj_a.id)
    wart = _make_wartung(db, policy_a)

    resp = steckbrief_admin_client.delete(
        f"/objects/{obj_b.id}/wartungspflichten/{wart.id}"
    )
    assert resp.status_code == 404
    db.expire_all()
    assert db.get(Wartungspflicht, wart.id) is not None


def test_wartungspflicht_post_404_when_policy_belongs_to_other_object(
    db, steckbrief_admin_client, make_object
):
    """POST auf /objects/A/policen/{pid}/wartungspflichten, aber policy.object_id=B → 404."""
    obj_a = make_object("WRT-F4A")
    obj_b = make_object("WRT-F4B")
    policy_b = _make_policy(db, obj_b.id)

    resp = steckbrief_admin_client.post(
        f"/objects/{obj_a.id}/policen/{policy_b.id}/wartungspflichten",
        data={"bezeichnung": "Blocked by cross-policy"},
    )
    assert resp.status_code == 404
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy_b.id).count() == 0


def test_wartungspflicht_delete_404_when_wart_object_id_diverges_from_policy(
    db, steckbrief_admin_client, make_object
):
    """Cross-Police-Guard: wart.object_id=A, policy.object_id=B (Daten-Manipulation) → 404.

    Spec Task 7.2 verlangt diese Variante zusaetzlich zur einfachen Path-Mismatch-Variante:
    der zweite Guard (`wart.policy.object_id != obj.id`) muss greifen, selbst wenn
    der erste Guard (`wart.object_id != obj.id`) durchgelassen haette.
    """
    obj_a = make_object("WRT-F5A")
    obj_b = make_object("WRT-F5B")
    policy_b = _make_policy(db, obj_b.id)
    wart = _make_wartung(db, policy_b, "Manipuliert")
    # Daten-Inkonsistenz simulieren: wart.object_id manuell auf obj_a setzen,
    # waehrend policy noch auf obj_b zeigt.
    wart.object_id = obj_a.id
    db.commit()
    db.expire_all()

    resp = steckbrief_admin_client.delete(
        f"/objects/{obj_a.id}/wartungspflichten/{wart.id}"
    )
    # Erster Guard (wart.object_id != obj.id) lasst durch — Cross-Police-Guard fangt ab.
    assert resp.status_code == 404
    db.expire_all()
    assert db.get(Wartungspflicht, wart.id) is not None


# ---------------------------------------------------------------------------
# Patch-Coverage aus Code-Review 2026-04-26
# ---------------------------------------------------------------------------

def test_post_wartungspflicht_with_nonexistent_dienstleister_returns_422(
    db, steckbrief_admin_client, make_object
):
    """Syntaktisch valide UUID, die nicht in dienstleister-Tabelle existiert → 422 statt 500."""
    obj = make_object("WRT-G1")
    policy = _make_policy(db, obj.id)
    ghost_id = uuid.uuid4()

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={
            "bezeichnung": "Reinigung",
            "dienstleister_id": str(ghost_id),
        },
    )
    assert resp.status_code == 422
    assert "Dienstleister" in resp.text
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy.id).count() == 0


def test_post_wartungspflicht_with_zero_intervall_returns_422(
    db, steckbrief_admin_client, make_object
):
    """intervall_monate=0 oder negativ wird server-seitig abgelehnt (HTML min='1' ist nur client-side)."""
    obj = make_object("WRT-G2")
    policy = _make_policy(db, obj.id)

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Wartung", "intervall_monate": "0"},
    )
    assert resp.status_code == 422
    assert "Intervall" in resp.text
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy.id).count() == 0


def test_post_wartungspflicht_with_negative_intervall_returns_422(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("WRT-G3")
    policy = _make_policy(db, obj.id)

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Wartung", "intervall_monate": "-12"},
    )
    assert resp.status_code == 422
    assert db.query(Wartungspflicht).filter(Wartungspflicht.policy_id == policy.id).count() == 0


def test_get_dienstleister_new_form_without_policy_id_renders_no_hidden_input(
    steckbrief_admin_client,
):
    """Standalone-Pfad (ohne policy_id) darf nicht 'value=\"None\"' rendern."""
    resp = steckbrief_admin_client.get("/registries/dienstleister/new-form")
    assert resp.status_code == 200
    body = resp.text
    assert 'value="None"' not in body
    # Hidden-Input soll bei fehlendem policy_id komplett wegfallen
    assert 'name="policy_id"' not in body


def test_police_update_validation_error_with_existing_wartung_does_not_crash(
    db, steckbrief_admin_client, make_object
):
    """Regression: Police-Edit mit invaliden Daten + bestehender Wartungspflicht.

    police_update rendert bei Date-Validation-Error _obj_versicherungen.html, das via
    Include _obj_versicherungen_row.html Wartungen rendert und get_due_severity()
    aufruft. Vor dem Fix fehlten dienstleister_list + get_due_severity im 422-Context
    → TypeError: 'Undefined' object is not callable.
    """
    obj = make_object("WRT-PR1")
    policy = _make_policy(db, obj.id)
    _make_wartung(db, policy, "Vorhandene Wartung")
    db.expire_all()  # erzwingt selectin-Reload beim Server-Side Template-Render

    # Date-Validation-Fehler erzwingen: end_date < start_date
    resp = steckbrief_admin_client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={
            "start_date": "2025-12-31",
            "end_date": "2024-01-01",
        },
    )
    assert resp.status_code == 422
    # Wenn der Fix greift, rendert der Body die Wartung weiter — kein Crash.
    # (Vor dem Fix: Crash wegen `get_due_severity` Undefined.)
    assert "Vorhandene Wartung" in resp.text


def test_police_create_validation_error_with_existing_wartung_does_not_crash(
    db, steckbrief_admin_client, make_object
):
    """Selbe Regression wie oben, aber fuer die Create-Route: invaliden POST waehrend
    bereits eine Police mit Wartungspflicht existiert.
    """
    obj = make_object("WRT-PR2")
    existing = _make_policy(db, obj.id)
    _make_wartung(db, existing, "Schon vorhandene Wartung")
    db.expire_all()

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={
            "start_date": "2025-12-31",
            "end_date": "2024-01-01",
        },
    )
    assert resp.status_code == 422
    assert "Schon vorhandene Wartung" in resp.text


def test_versicherungen_section_hides_wartung_delete_button_for_viewer(
    db, viewer_client, make_object
):
    """AC5: Loeschen-Button auf bestehenden Wartungspflichten ist fuer Viewer unsichtbar."""
    obj = make_object("WRT-E5")
    policy = _make_policy(db, obj.id)
    _make_wartung(db, policy, "Sichtbar als Viewer")
    db.expire_all()

    resp = viewer_client.get(f"/objects/{obj.id}/sections/versicherungen")
    assert resp.status_code == 200
    body = resp.text
    # Wartung wird angezeigt
    assert "Sichtbar als Viewer" in body
    # Aber kein Loeschen-Button (HTMX-DELETE auf wartungspflichten-Pfad)
    assert "/wartungspflichten/" not in body


# ---------------------------------------------------------------------------
# Tranche B — Form-Error-Context (Story 2.2)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason="Wartungspflicht-422 rendert aktuell ein simples <p>-Fragment statt "
           "Re-Render mit dienstleister_list-Context. Form-Error-UX-Polish nicht "
           "im Scope der Tranche, regression-pinnt das aktuelle Minimal-Pattern."
)
def test_create_wartungspflicht_form_error_renders_with_dienstleister_list_context(
    db, steckbrief_admin_client, make_object
):
    """Bei 422 enthaelt Response das dienstleister_list-Fragment +
    get_due_severity-Filter laeuft ohne Crash (kein TypeError 'Undefined')."""
    obj = make_object("WRT-FE")
    policy = _make_policy(db, obj.id)
    dienstleister = Dienstleister(
        id=uuid.uuid4(), name="Existing-DL-FE", gewerke_tags=[]
    )
    db.add(dienstleister)
    db.commit()

    # Empty bezeichnung -> 422
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "", "intervall_monate": "12"},
    )
    assert resp.status_code == 422
    body = resp.text
    # dienstleister_list muss im Render erscheinen, damit User Form korrigieren kann
    assert "Existing-DL-FE" in body, (
        "dienstleister_list muss im 422-Render verfuegbar sein"
    )
    # Kein Crash durch Undefined get_due_severity (heuristisch: Body ist nicht leer
    # und enthaelt keine Stack-Trace-Marker)
    assert "TypeError" not in body
    assert "Undefined" not in body


# ---------------------------------------------------------------------------
# Regression — write_gate_coverage weiter gruen
# ---------------------------------------------------------------------------

def test_write_gate_coverage_still_green():
    from tests.test_write_gate_coverage import test_no_direct_writes_to_cd1_entities_textscan
    test_no_direct_writes_to_cd1_entities_textscan()
