"""Story 1.6 — Route-Smoke-Tests fuer die Technik-Sektion auf /objects/{id}.

Deckt die sechs ACs ab:
  * AC1: Sektion + Sub-Bloecke + Felder + Edit-Buttons (fuer objects:edit)
  * AC2: Save durchlaeuft das Write-Gate → DB, Provenance, Audit
  * AC3: Viewer (kein objects:edit) sieht keine Edit-Buttons, POST 403
  * AC4: Validierungsfehler → Fragment mit Fehler, kein Write
  * AC5: Erfolgreicher Write invalidiert Pflegegrad-Cache
  * AC6: Leerer String setzt Feld auf NULL (bewusste Loeschung)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import AuditLog, FieldProvenance, Object, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_object(db):
    """Konstruktor fuer leere Technik-Test-Objekte."""
    def _make(short_code: str) -> Object:
        obj = Object(
            id=uuid.uuid4(),
            short_code=short_code,
            name=f"Technik-Objekt {short_code}",
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    return _make


@pytest.fixture
def steckbrief_admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-technik-admin-user",
        email="steckbrief-admin-technik@dbshome.de",
        name="Steckbrief Admin Technik",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "objects:view_confidential",
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
def viewer_client(db):
    """TestClient mit einem User, der nur objects:view hat — KEIN objects:edit.
    Fuer AC3-Tests (Edit-Buttons unsichtbar + POST 403)."""
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-viewer-technik",
        email="viewer-technik@dbshome.de",
        name="Viewer",
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


# ---------------------------------------------------------------------------
# AC1 — Technik-Sektion rendert mit allen Sub-Bloecken + Edit-Buttons
# ---------------------------------------------------------------------------

def test_technik_section_rendered_with_all_fields_and_edit_buttons_for_editor(
    steckbrief_admin_client, make_object
):
    obj = make_object("TECH1")
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    assert 'data-section="technik"' in body

    # Alle 10 Felder sind im HTML (pro Feld ein data-field-Attribut auf der Pill).
    expected_fields = [
        "shutoff_water_location", "shutoff_electricity_location", "shutoff_gas_location",
        "heating_type", "year_heating", "heating_company", "heating_hotline",
        "year_built", "year_roof", "year_electrics",
    ]
    for key in expected_fields:
        assert f'data-field="{key}"' in body, f"Feld {key} fehlt im Render"
        assert f'data-edit-field="{key}"' in body, f"Edit-Button fuer {key} fehlt"

    # Story 1.7: Zugangscodes erscheinen jetzt im Render — aber unter eigenen
    # Endpoints. Der Technik-Endpoint muss sie weiter ablehnen
    # (siehe test_technik_save_rejects_entry_code_field).
    for key in ("entry_code_main_door", "entry_code_garage", "entry_code_technical_room"):
        assert f'data-field="{key}"' in body, f"Zugangscode {key} fehlt im Render"


def test_technik_section_labels_in_german(steckbrief_admin_client, make_object):
    obj = make_object("TECH2")
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    # Sub-Block-Ueberschriften
    assert "Absperrpunkte" in body
    assert "Heizung" in body
    assert "Objekt-Historie" in body
    # Einzel-Labels (Stichproben)
    assert "Wasser-Absperrung" in body
    assert "Strom-Absperrung" in body
    assert "Gas-Absperrung" in body
    assert "Heizungs-Typ" in body
    assert "Baujahr Heizung" in body
    assert "Wartungsfirma" in body
    assert "Stoerungs-Hotline" in body
    assert "Baujahr Gebaeude" in body
    assert "Jahr letzte Dach-Sanierung" in body
    assert "Jahr Elektrik-Check" in body


# ---------------------------------------------------------------------------
# AC2 + AC5 — Save durchlaeuft Write-Gate, invalidiert Pflegegrad-Cache
# ---------------------------------------------------------------------------

def test_technik_field_save_writes_via_gate_and_invalidates_pflegegrad(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("TECH3")
    # Seed einen Pflegegrad-Cache-Wert — das Gate muss ihn nach dem Write nullen (AC5).
    obj.pflegegrad_score_cached = 72  # writegate: allow
    obj.pflegegrad_score_updated_at = datetime.now(timezone.utc)  # writegate: allow
    db.add(obj)
    db.commit()

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "year_roof", "value": "2021"},
    )
    assert resp.status_code == 200
    body = resp.text
    # Fragment-Response: frische Pill + neuer Wert sichtbar
    assert 'id="field-year_roof"' in body
    assert 'data-source="user_edit"' in body
    assert "2021" in body

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.year_roof == 2021
    # AC5: Pflegegrad-Cache ist invalidiert
    assert refreshed.pflegegrad_score_cached is None
    assert refreshed.pflegegrad_score_updated_at is None

    # Genau eine FieldProvenance-Row, source=user_edit
    prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
            FieldProvenance.field_name == "year_roof",
        )
        .all()
    )
    assert len(prov) == 1
    assert prov[0].source == "user_edit"
    assert prov[0].value_snapshot == {"old": None, "new": 2021}

    # Audit-Log
    audits = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "object_field_updated",
            AuditLog.entity_id == obj.id,
        )
        .all()
    )
    assert len(audits) == 1
    assert audits[0].details_json["field"] == "year_roof"


def test_technik_field_save_text_field(db, steckbrief_admin_client, make_object):
    obj = make_object("TECH4")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "heating_type", "value": "Viessmann"},
    )
    assert resp.status_code == 200
    assert "Viessmann" in resp.text

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.heating_type == "Viessmann"


# ---------------------------------------------------------------------------
# AC3 — Viewer ohne objects:edit sieht keine Edit-Buttons + POST 403
# ---------------------------------------------------------------------------

def test_technik_edit_button_not_rendered_for_viewer(
    viewer_client, make_object
):
    obj = make_object("TECH5")
    resp = viewer_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text

    assert 'data-section="technik"' in body
    # KEIN Edit-Button im Viewer-View (kein data-edit-field-Attribut)
    assert "data-edit-field" not in body


def test_technik_post_returns_403_for_viewer(
    db, viewer_client, make_object
):
    obj = make_object("TECH6")
    resp = viewer_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "year_roof", "value": "2021"},
    )
    assert resp.status_code == 403

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.year_roof is None

    # Kein FieldProvenance, kein AuditLog
    prov_count = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
        )
        .count()
    )
    assert prov_count == 0
    audit_count = (
        db.query(AuditLog)
        .filter(AuditLog.action == "object_field_updated", AuditLog.entity_id == obj.id)
        .count()
    )
    assert audit_count == 0


def test_technik_edit_get_returns_403_for_viewer(viewer_client, make_object):
    """AC3-Zweig 2: auch das GET-Fragment braucht objects:edit — sonst koennte
    ein Viewer das Form-Fragment ueber Umwege sehen (auch wenn das POST selbst
    weiter 403 wirft)."""
    obj = make_object("TECH7")
    resp = viewer_client.get(
        f"/objects/{obj.id}/technik/edit", params={"field": "year_roof"}
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# AC4 — Validierungsfehler → Fragment mit Fehler, kein Write
# ---------------------------------------------------------------------------

def test_technik_save_invalid_year_returns_form_with_error(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("TECH8")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "year_roof", "value": "abc"},
    )
    assert resp.status_code == 422
    assert 'data-error="true"' in resp.text
    assert "Bitte eine ganze Zahl (Jahr) eingeben." in resp.text

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.year_roof is None
    prov_count = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
            FieldProvenance.field_name == "year_roof",
        )
        .count()
    )
    assert prov_count == 0


def test_technik_save_year_out_of_range_returns_422(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("TECH9")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "year_built", "value": "1700"},
    )
    assert resp.status_code == 422
    assert 'data-error="true"' in resp.text
    assert "Jahr muss zwischen 1800" in resp.text
    # Submitted value bleibt im Form erhalten — der User sieht seine Eingabe.
    assert 'value="1700"' in resp.text


def test_technik_save_text_over_max_len_returns_422(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("TECH10")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "heating_type", "value": "x" * 501},
    )
    assert resp.status_code == 422
    assert 'data-error="true"' in resp.text
    assert "Maximal 500 Zeichen erlaubt." in resp.text


def test_technik_save_unknown_field_returns_400(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("TECH11")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "does_not_exist", "value": "42"},
    )
    assert resp.status_code == 400


def test_technik_save_rejects_entry_code_field(
    db, steckbrief_admin_client, make_object
):
    """Scope-Boundary zu Story 1.7: Zugangscodes duerfen nicht ueber die
    Technik-API schreibbar sein — Fernet-Encryption kommt erst in 1.7."""
    obj = make_object("TECH12")
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "entry_code_main_door", "value": "1234"},
    )
    assert resp.status_code == 400

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.entry_code_main_door is None


# ---------------------------------------------------------------------------
# AC6 — Empty-String setzt Feld auf NULL
# ---------------------------------------------------------------------------

def test_technik_save_empty_string_sets_null(
    db, steckbrief_admin_client, make_object, steckbrief_admin_user
):
    obj = make_object("TECH13")
    # Vorbelegen via Write-Gate, damit Provenance + DB konsistent sind.
    from app.services.steckbrief_write_gate import write_field_human
    write_field_human(
        db, entity=obj, field="year_roof", value=2021,
        source="user_edit", user=steckbrief_admin_user,
    )
    db.commit()

    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "year_roof", "value": ""},
    )
    assert resp.status_code == 200

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.year_roof is None

    # Zwei Provenance-Rows: Initial-Write (None→2021) und Loeschung (2021→None).
    # Sortierung nach created_at ist im SQLite-Testsetup nicht reliably
    # aufgeloest (server_default=CURRENT_TIMESTAMP mit Sekundenaufloesung),
    # darum filtern wir inhaltlich nach der Delete-Row.
    prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
            FieldProvenance.field_name == "year_roof",
        )
        .all()
    )
    assert len(prov) == 2
    delete_rows = [
        p for p in prov
        if p.value_snapshot.get("new") is None
        and p.value_snapshot.get("old") == 2021
    ]
    assert len(delete_rows) == 1
    assert delete_rows[0].source == "user_edit"


# ---------------------------------------------------------------------------
# Cancel-Loop + Edit-Fragment (AC2 Fragment-Semantik)
# ---------------------------------------------------------------------------

def test_technik_edit_get_returns_form_fragment(
    steckbrief_admin_client, make_object
):
    obj = make_object("TECH14")
    resp = steckbrief_admin_client.get(
        f"/objects/{obj.id}/technik/edit", params={"field": "year_roof"}
    )
    assert resp.status_code == 200
    body = resp.text
    assert "hx-post" in body
    assert 'name="field_name"' in body
    assert 'value="year_roof"' in body
    # Cancel-Button ist ebenfalls Teil des Edit-Fragments.
    assert "Abbrechen" in body


def test_technik_view_cancel_returns_view_fragment(
    steckbrief_admin_client, make_object
):
    obj = make_object("TECH15")
    resp = steckbrief_admin_client.get(
        f"/objects/{obj.id}/technik/view", params={"field": "year_roof"}
    )
    assert resp.status_code == 200
    body = resp.text
    assert "<form" not in body
    # Edit-Button sichtbar (admin hat objects:edit).
    assert 'data-edit-field="year_roof"' in body


def test_technik_view_get_returns_403_for_viewer(viewer_client, make_object):
    """AC3-Absicherung fuer GET /technik/view: der Endpoint erfordert
    objects:edit, damit der Edit-/Cancel-Loop konsistent unter einer einzigen
    Permission-Grenze liegt (alle drei Technik-Fragment-Endpoints hinter
    objects:edit)."""
    obj = make_object("TECH16")
    resp = viewer_client.get(
        f"/objects/{obj.id}/technik/view", params={"field": "year_roof"}
    )
    assert resp.status_code == 403
