"""Story 1.7 — Route-Smoke-Tests fuer die Zugangscode-Endpoints.

Deckt alle ACs ab:
  * AC1: Ciphertext in DB, kein Klartext in Provenance/Audit
  * AC2: Decrypt beim Render
  * AC3: Decrypt-Fehler → Placeholder + Audit
  * AC4: Leerer Wert → NULL
  * AC5: Viewer ohne objects:edit sieht kein Edit; POST/Edit-GET 403
  * AC6: Technik-Endpoint lehnt entry_code_* weiter ab; unbekanntes Feld 400
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import AuditLog, FieldProvenance, Object, User
from app.services.field_encryption import encrypt_field
from app.services.steckbrief_write_gate import write_field_human


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_zug_object(db):
    def _make(short_code: str) -> Object:
        obj = Object(
            id=uuid.uuid4(),
            short_code=short_code,
            name=f"Zugangscode-Objekt {short_code}",
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    return _make


@pytest.fixture
def zug_admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-zug-admin",
        email="zug-admin@dbshome.de",
        name="Zug Admin",
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
def zug_admin_client(db, zug_admin_user):
    def override_db():
        yield db

    def override_user():
        return zug_admin_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user
    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def viewer_zug_client(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-viewer-zug",
        email="viewer-zug@dbshome.de",
        name="Viewer Zug",
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
def zug_editor_no_confidential_client(db):
    """User mit objects:view + objects:edit, aber OHNE view_confidential.

    Deckt die Luecke zwischen viewer_zug_client (kein edit) und
    zug_admin_client (alle Rechte) fuer die Story-2.0-403-Pfade auf den
    edit/save-Endpoints. Hier greift nicht die Dependency, sondern der
    In-Handler-Check auf view_confidential.
    """
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-zug-editor-noconf",
        email="zug-editor-noconf@dbshome.de",
        name="Zug Editor No Confidential",
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


# ---------------------------------------------------------------------------
# AC1 + AC2 — Write verschluesselt, Render decrypted
# ---------------------------------------------------------------------------

def test_zugangscode_save_encrypts_and_decrypts_roundtrip(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG1")
    resp = zug_admin_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_main_door", "value": "1234-AB"},
    )
    assert resp.status_code == 200
    # Fragment enthaelt den Klartext nach dem Save-Roundtrip.
    assert "1234-AB" in resp.text

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    # AC1: DB-Spalte haelt Ciphertext, keinen Klartext.
    assert refreshed.entry_code_main_door is not None
    assert refreshed.entry_code_main_door.startswith("v1:")
    assert "1234-AB" not in refreshed.entry_code_main_door

    # AC2: GET /objects/{id} decrypted beim Render.
    detail_resp = zug_admin_client.get(f"/objects/{obj.id}")
    assert detail_resp.status_code == 200
    assert "1234-AB" in detail_resp.text


def test_zugangscode_save_no_plaintext_in_provenance(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG2")
    resp = zug_admin_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_main_door", "value": "1234-AB"},
    )
    assert resp.status_code == 200

    prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
            FieldProvenance.field_name == "entry_code_main_door",
        )
        .all()
    )
    assert len(prov) == 1
    snapshot = prov[0].value_snapshot
    assert snapshot == {
        "old": {"encrypted": True},
        "new": {"encrypted": True},
    }
    # Serializer-Roundtrip zur Sicherheit: auch als JSON-String kein Klartext.
    assert "1234-AB" not in json.dumps(snapshot)


def test_zugangscode_save_no_plaintext_in_audit(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG3")
    resp = zug_admin_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_main_door", "value": "SECRET-42"},
    )
    assert resp.status_code == 200

    audits = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "object_field_updated",
            AuditLog.entity_id == obj.id,
        )
        .all()
    )
    assert len(audits) == 1
    assert "SECRET-42" not in json.dumps(audits[0].details_json)
    # AC1: Positiv-Assertion — Encrypted-Marker statt Klartext.
    assert audits[0].details_json.get("old") == {"encrypted": True}
    assert audits[0].details_json.get("new") == {"encrypted": True}


# ---------------------------------------------------------------------------
# AC4 — Empty-String loescht den Code
# ---------------------------------------------------------------------------

def test_zugangscode_save_empty_deletes_code(
    db, zug_admin_client, zug_admin_user, make_zug_object
):
    obj = make_zug_object("ZUG4")
    # Vorbelegen ueber das Write-Gate, damit Provenance + Ciphertext konsistent sind.
    write_field_human(
        db,
        entity=obj,
        field="entry_code_garage",
        value="INITIAL",
        source="user_edit",
        user=zug_admin_user,
    )
    db.commit()

    resp = zug_admin_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_garage", "value": ""},
    )
    assert resp.status_code == 200

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.entry_code_garage is None

    # AC4: Provenance-Snapshot zeigt encrypted-Marker auch beim NULL-Write.
    del_prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
            FieldProvenance.field_name == "entry_code_garage",
        )
        .order_by(FieldProvenance.created_at.desc())
        .first()
    )
    assert del_prov is not None
    assert del_prov.value_snapshot == {
        "old": {"encrypted": True},
        "new": {"encrypted": True},
    }

    detail_resp = zug_admin_client.get(f"/objects/{obj.id}")
    assert detail_resp.status_code == 200
    # Das Garage-Feld rendert jetzt den Placeholder — fuer keinen Code.
    body = detail_resp.text
    assert 'id="field-entry_code_garage"' in body


# ---------------------------------------------------------------------------
# AC5 / Story 2.0 — view_confidential Enforcement
# Viewer ohne objects:edit bekommt 403 auf edit/save (Dependency-Ebene).
# User mit objects:edit aber ohne view_confidential bekommt 403 auf alle
# Zugangscode-Endpoints (In-Handler-Check bzw. view-Dependency).
# Detailseite versteckt die gesamte Sektion fuer jeden User ohne
# view_confidential.
# ---------------------------------------------------------------------------

def test_zugangscode_post_returns_403_for_viewer(
    db, viewer_zug_client, make_zug_object
):
    obj = make_zug_object("ZUG6")
    resp = viewer_zug_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_main_door", "value": "1234"},
    )
    assert resp.status_code == 403

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.entry_code_main_door is None


def test_zugangscode_edit_get_returns_403_for_viewer(
    viewer_zug_client, make_zug_object
):
    obj = make_zug_object("ZUG7")
    resp = viewer_zug_client.get(
        f"/objects/{obj.id}/zugangscodes/edit",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 403


def test_zugangscode_view_blocked_without_view_confidential(
    db, zug_editor_no_confidential_client, zug_admin_user, make_zug_object
):
    """Story 2.0: View-Endpoint ist jetzt hinter view_confidential — ein User
    mit objects:view + objects:edit aber OHNE view_confidential bekommt 403."""
    obj = make_zug_object("ZUG-VC1")
    write_field_human(
        db,
        entity=obj,
        field="entry_code_main_door",
        value="SHOULD-NOT-LEAK",
        source="user_edit",
        user=zug_admin_user,
    )
    db.commit()

    resp = zug_editor_no_confidential_client.get(
        f"/objects/{obj.id}/zugangscodes/view",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 403
    assert "SHOULD-NOT-LEAK" not in resp.text


def test_zugangscode_edit_blocked_without_view_confidential(
    zug_editor_no_confidential_client, make_zug_object
):
    """Story 2.0: Edit-Endpoint hat objects:edit-Dependency, der In-Handler-
    Check greift nach und liefert 403 fuer User ohne view_confidential."""
    obj = make_zug_object("ZUG-VC2")
    resp = zug_editor_no_confidential_client.get(
        f"/objects/{obj.id}/zugangscodes/edit",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 403


def test_zugangscode_save_blocked_without_view_confidential(
    db, zug_editor_no_confidential_client, make_zug_object
):
    """Story 2.0: Save-Endpoint ebenfalls; der 403 greift VOR der Parse-
    Validierung — kein 422."""
    obj = make_zug_object("ZUG-VC3")
    resp = zug_editor_no_confidential_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_main_door", "value": "1234"},
    )
    assert resp.status_code == 403

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.entry_code_main_door is None


def test_detail_page_hides_zugangscodes_section_without_view_confidential(
    db, viewer_zug_client, zug_admin_user, make_zug_object
):
    """Story 2.0 (AC4): Auf der Detailseite fehlt die komplette Zugangscodes-
    Sektion — nicht nur die Edit-Buttons, auch die Ueberschrift + Platzhalter-
    Container sind weg. Klartextcode wird im Handler gar nicht erst decrypted."""
    obj = make_zug_object("ZUG-VC4")
    write_field_human(
        db,
        entity=obj,
        field="entry_code_main_door",
        value="HIDDEN-CODE",
        source="user_edit",
        user=zug_admin_user,
    )
    db.commit()

    resp = viewer_zug_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    # Technik-Sektion bleibt sichtbar (Absperrpunkte, Heizung, Historie).
    assert 'data-section="technik"' in body
    # Aber die Zugangscodes-Sektion (Headline + Felder) ist komplett weg.
    assert "Zugangscodes" not in body
    assert 'id="field-entry_code_main_door"' not in body
    assert 'id="field-entry_code_garage"' not in body
    assert 'id="field-entry_code_technical_room"' not in body
    # Und die dekryptete Klartext-Form taucht nirgends auf.
    assert "HIDDEN-CODE" not in body


def test_zugangscode_view_blocked_for_pure_viewer(
    viewer_zug_client, make_zug_object
):
    """Story 2.0 (P1): Reiner objects:view-User (kein edit, kein view_confidential)
    bekommt 403 auf dem View-Endpoint — View-Dependency greift."""
    obj = make_zug_object("ZUG-VC5")
    resp = viewer_zug_client.get(
        f"/objects/{obj.id}/zugangscodes/view",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 403


def test_zugangscode_view_accessible_for_view_confidential_user(
    zug_admin_client, make_zug_object
):
    """Story 2.0 (P2a): Positiv-Pfad — User MIT view_confidential erhaelt 200
    auf dem View-Endpoint (Fragment wird gerendert)."""
    obj = make_zug_object("ZUG-VC6")
    resp = zug_admin_client.get(
        f"/objects/{obj.id}/zugangscodes/view",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 200


def test_zugangscode_edit_accessible_for_view_confidential_user(
    zug_admin_client, make_zug_object
):
    """Story 2.0 (P2b): Positiv-Pfad — User MIT view_confidential + objects:edit
    erhaelt 200 auf dem Edit-Endpoint (Formular wird gerendert)."""
    obj = make_zug_object("ZUG-VC7")
    resp = zug_admin_client.get(
        f"/objects/{obj.id}/zugangscodes/edit",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tranche A — Permission-Gate Positiv-Path (Story 2.0)
# Drei explizit benannte Admin-200-Tests, die View/Edit/Save je auf einer
# eigenen Test-Funktion verifizieren. Erfasst Regression-Risiko bei
# Dependency-Upgrade auf das view_confidential-Gate.
# ---------------------------------------------------------------------------

def test_zugangscode_view_returns_200_for_admin_with_view_confidential(
    db, zug_admin_client, zug_admin_user, make_zug_object
):
    """Tranche A: Admin mit view_confidential erhaelt das View-Fragment des
    Zugangscodes inklusive entschluesseltem Klartext-Wert."""
    obj = make_zug_object("ZUG-A1")
    write_field_human(
        db,
        entity=obj,
        field="entry_code_main_door",
        value="ADMIN-VIEW-OK",
        source="user_edit",
        user=zug_admin_user,
    )
    db.commit()

    resp = zug_admin_client.get(
        f"/objects/{obj.id}/zugangscodes/view",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 200
    body = resp.text
    # View-Fragment-Container traegt die feldspezifische ID.
    assert 'id="field-entry_code_main_door"' in body
    # Klartext wird im Fragment dekrypted dargestellt.
    assert "ADMIN-VIEW-OK" in body


def test_zugangscode_edit_returns_200_for_admin_with_view_confidential(
    db, zug_admin_client, zug_admin_user, make_zug_object
):
    """Tranche A: Admin mit view_confidential + objects:edit erhaelt das
    Edit-Form-Fragment mit vorausgefuelltem Wert."""
    obj = make_zug_object("ZUG-A2")
    write_field_human(
        db,
        entity=obj,
        field="entry_code_main_door",
        value="ADMIN-EDIT-OK",
        source="user_edit",
        user=zug_admin_user,
    )
    db.commit()

    resp = zug_admin_client.get(
        f"/objects/{obj.id}/zugangscodes/edit",
        params={"field": "entry_code_main_door"},
    )
    assert resp.status_code == 200
    body = resp.text
    # Edit-Fragment enthaelt den Form-Input-Namen + dekrypteten Wert.
    assert 'name="value"' in body
    assert "ADMIN-EDIT-OK" in body


def test_zugangscode_save_returns_200_for_admin_with_view_confidential(
    db, zug_admin_client, make_zug_object
):
    """Tranche A: Admin POSTet einen Wert via Save-Endpoint → 200, Wert
    persistiert verschluesselt (v1:-Praefix), Klartext nicht in DB-Spalte."""
    obj = make_zug_object("ZUG-A3")
    resp = zug_admin_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_garage", "value": "SAVE-OK-99"},
    )
    assert resp.status_code == 200
    # Save-Roundtrip rendert den frischen View-Fragment mit Klartext.
    assert "SAVE-OK-99" in resp.text

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.entry_code_garage is not None
    assert refreshed.entry_code_garage.startswith("v1:")
    # DB-Spalte haelt Ciphertext, nicht den Klartext.
    assert "SAVE-OK-99" not in refreshed.entry_code_garage


# ---------------------------------------------------------------------------
# AC6 — Technik-Endpoint weist entry_code_* weiter ab; unbekannte Felder 400
# ---------------------------------------------------------------------------

def test_technik_endpoint_still_rejects_entry_code(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG9")
    resp = zug_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "entry_code_main_door", "value": "1234"},
    )
    assert resp.status_code == 400

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.entry_code_main_door is None


def test_zugangscode_view_endpoint_unknown_field_returns_400(
    zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG10")
    resp = zug_admin_client.get(
        f"/objects/{obj.id}/zugangscodes/view",
        params={"field": "year_roof"},
    )
    assert resp.status_code == 400


def test_zugangscode_edit_endpoint_unknown_field_returns_400(
    zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG11")
    resp = zug_admin_client.get(
        f"/objects/{obj.id}/zugangscodes/edit",
        params={"field": "year_roof"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# AC3 — Decryption-Failure: UI zeigt Placeholder, AuditLog entsteht
# ---------------------------------------------------------------------------

def test_zugangscode_decryption_failure_shows_placeholder(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG12")
    # Invalid Ciphertext direkt in die DB setzen — das `v1:`-Praefix passt, aber
    # der Token ist Muell. Kein Write-Gate, bewusst um den Fernet-Fail-Pfad zu
    # testen.
    obj.entry_code_main_door = "v1:INVALIDTOKEN"  # writegate: allow
    db.add(obj)
    db.commit()

    resp = zug_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    assert "Code nicht verfügbar" in resp.text


def test_zugangscode_decryption_failure_writes_audit(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG13")
    obj.entry_code_main_door = "v1:INVALIDTOKEN"  # writegate: allow
    db.add(obj)
    db.commit()

    resp = zug_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200

    audits = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "encryption_key_missing",
            AuditLog.entity_id == obj.id,
        )
        .all()
    )
    assert len(audits) >= 1
    assert audits[0].details_json == {"field": "entry_code_main_door"}


# ---------------------------------------------------------------------------
# AC2 — NULL-Feld rendert Placeholder
# ---------------------------------------------------------------------------

def test_zugangscode_null_shows_placeholder(
    zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG14")
    resp = zug_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="field-entry_code_main_door"' in body
    # Der Haustuer-Code hat keinen Wert → Placeholder (mdash) in derselben Box.
    assert "&mdash;" in body


# ---------------------------------------------------------------------------
# AC1 — alle drei Felder koennen gesetzt werden
# ---------------------------------------------------------------------------

def test_zugangscode_all_three_fields_work(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG15")
    cases = {
        "entry_code_main_door": "HAUS-1",
        "entry_code_garage": "GARAGE-2",
        "entry_code_technical_room": "TECHNIK-3",
    }
    for field, plain in cases.items():
        resp = zug_admin_client.post(
            f"/objects/{obj.id}/zugangscodes/field",
            data={"field_name": field, "value": plain},
        )
        assert resp.status_code == 200, (field, resp.status_code)

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    for field, plain in cases.items():
        ct = getattr(refreshed, field)
        assert ct is not None and ct.startswith("v1:"), field
        assert plain not in ct, field

    detail_resp = zug_admin_client.get(f"/objects/{obj.id}")
    assert detail_resp.status_code == 200
    for plain in cases.values():
        assert plain in detail_resp.text


# ---------------------------------------------------------------------------
# Hilfstest: Validierungsfehler → Fragment mit 422, kein Write
# ---------------------------------------------------------------------------

def test_zugangscode_save_too_long_returns_422(
    db, zug_admin_client, make_zug_object
):
    obj = make_zug_object("ZUG16")
    long_value = "x" * 201
    resp = zug_admin_client.post(
        f"/objects/{obj.id}/zugangscodes/field",
        data={"field_name": "entry_code_main_door", "value": long_value},
    )
    assert resp.status_code == 422
    assert "Maximal 200 Zeichen" in resp.text

    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.entry_code_main_door is None


# ---------------------------------------------------------------------------
# Direkt-Encryption + Decrypt-Roundtrip ueber den Write-Pfad
# ---------------------------------------------------------------------------

def test_preencrypted_value_decrypts_on_detail(
    db, zug_admin_user, zug_admin_client, make_zug_object
):
    """Ciphertext direkt via encrypt_field in die DB schreiben und dann die
    Detailseite anfragen — das simuliert einen Write aus einem anderen Pfad
    (z.B. Nightly-Mirror in v1.1) und pruft den Render-Weg strikt isoliert vom
    POST-Endpoint."""
    obj = make_zug_object("ZUG17")
    ct = encrypt_field(
        "PRE-ENC",
        entity_type="object",
        field="entry_code_technical_room",
    )
    obj.entry_code_technical_room = ct  # writegate: allow
    db.add(obj)
    db.commit()

    resp = zug_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    assert "PRE-ENC" in resp.text
