"""Code-Qualitäts-Tests fuer Story 5-6.

Statische Checks und Boundary-Tests fuer Refactoring-Massnahmen.
"""
from __future__ import annotations

import pathlib
import re
import uuid
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# AC1 — Permission-Konstanten
# ---------------------------------------------------------------------------

def test_no_permission_magic_strings():
    """Keine hardkodierten Permission-Strings fuer die 5-6-Namespaces in app/routers/ und app/services/.

    Scope: objects:, registries:, due_radar:, sync: — die in Story 5-6 (AC1) auf PERM_*-
    Konstanten umgestellten Namespaces. Andere Namespaces (documents:, workflows:, users:,
    audit_log:, impower:) sind out-of-scope und haben eigene Konstanten-Stories.
    Template-Strings (app/templates/) bleiben als String-Literale.
    """
    pattern = re.compile(r'"(objects|registries|due_radar|sync):[a-z_]+"')
    violations: list[str] = []

    for base_dir in ("app/routers", "app/services"):
        for py_file in sorted(pathlib.Path(base_dir).rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            text = py_file.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                violations.append(f"{py_file}: {match.group()}")

    assert not violations, (
        "Hardkodierte Permission-Strings gefunden (PERM_*-Konstanten verwenden):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# AC3 — proposed_value Decimal/Date Envelope
# ---------------------------------------------------------------------------

def test_proposed_value_decimal_roundtrip(db):
    """Decimal-Vorschlag ueberlebt write_field_ai_proposal → approve_review_entry
    ohne Typ-Fehler (kein String im DB-Wert, kein commit()-Fehler)."""
    from app.models import Object, Role, User
    from app.services.steckbrief_write_gate import approve_review_entry, write_field_ai_proposal

    role = Role(
        id=uuid.uuid4(),
        key="admin_cq_test",
        name="Admin CQ",
        permissions=["objects:view", "objects:edit", "objects:approve_ki"],
    )
    db.add(role)
    user = User(
        id=uuid.uuid4(),
        google_sub="sub-decimal-test",
        email="decimal@test.de",
        name="Decimal Tester",
        role=role,
    )
    db.add(user)
    obj = Object(
        id=uuid.uuid4(),
        short_code="DEC1",
        name="Decimal Test Objekt",
        full_address="Teststr. 1",
    )
    db.add(obj)
    db.commit()

    entry = write_field_ai_proposal(
        db,
        target_entity_type="object",
        target_entity_id=obj.id,
        field="reserve_current",
        proposed_value=Decimal("1234.56"),
        agent_ref="test-agent",
        confidence=0.9,
        source_doc_id=None,
        user=user,
    )
    db.commit()

    # Envelope-Shape im DB-Wert pruefen
    raw = entry.proposed_value
    assert isinstance(raw, dict), "proposed_value muss ein dict sein"
    assert "value" in raw, "proposed_value muss 'value'-Key haben"
    inner = raw["value"]
    assert isinstance(inner, dict) and inner.get("__type__") == "decimal", (
        f"proposed_value['value'] muss Decimal-Envelope sein, bekommen: {inner!r}"
    )

    # Approve — darf keinen Exception werfen
    approve_review_entry(db, entry_id=entry.id, user=user)
    db.commit()

    db.refresh(obj)
    # Wert ist jetzt auf dem Objekt gesetzt — nicht None
    assert obj.reserve_current is not None


# ---------------------------------------------------------------------------
# AC4 — Schadensquote Division-by-Zero
# ---------------------------------------------------------------------------

def test_versicherer_schadensquote_zero_praemie(db, auth_client):
    """Schadensquote rendert '–' statt Fehler wenn Gesamtprämie = 0."""
    import uuid as _uuid
    from app.models import Object, Role, User
    from app.models.registry import Versicherer

    role = Role(
        id=_uuid.uuid4(),
        key="reg_view_cq",
        name="Reg View",
        permissions=["registries:view", "objects:view"],
    )
    db.add(role)
    user = User(
        id=_uuid.uuid4(),
        google_sub="sub-reg-cq",
        email="regcq@test.de",
        name="Reg CQ",
        role=role,
    )
    db.add(user)
    v = Versicherer(
        id=_uuid.uuid4(),
        name="Nullprämien-Versicherer",
    )
    db.add(v)
    db.commit()

    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        resp = client.get(f"/registries/versicherer/{v.id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    # Muss "–" oder "0" rendern, NICHT "inf" oder Exception
    assert "inf" not in resp.text.lower()
    assert "ZeroDivisionError" not in resp.text


# ---------------------------------------------------------------------------
# AC5 — update_police partieller Body
# ---------------------------------------------------------------------------

def test_update_police_partial_body(db, steckbrief_admin_client):
    """update_police: Nur gesendete Felder werden geändert, Rest bleibt erhalten."""
    import uuid as _uuid
    from decimal import Decimal as _Dec
    from app.models import Object, InsurancePolicy

    obj = Object(
        id=_uuid.uuid4(),
        short_code="POL1",
        name="Police Test Objekt",
        full_address="Policenstr. 1",
    )
    db.add(obj)
    db.commit()

    policy = InsurancePolicy(
        id=_uuid.uuid4(),
        object_id=obj.id,
        police_number="POL-001",
        produkt_typ="Haftpflicht",
        praemie=_Dec("500.00"),
    )
    db.add(policy)
    db.commit()

    # Route ist PUT; steckbrief_admin_client traegt CSRF-Token automatisch.
    # Nur police_number + produkt_typ senden — praemie wird weggelassen.
    resp = steckbrief_admin_client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={
            "police_number": "POL-UPDATED",
            "produkt_typ": "Haftpflicht",
        },
    )

    assert resp.status_code == 200
    db.refresh(policy)
    # Prämie muss unverändert bleiben
    assert policy.praemie == _Dec("500.00"), f"Prämie wurde unerwartet geändert: {policy.praemie}"


# ---------------------------------------------------------------------------
# AC6 — Zugangscode view-Permission
# ---------------------------------------------------------------------------

def test_entry_code_write_requires_view_permission(db):
    """User mit objects:edit + view_confidential aber OHNE objects:view bekommt 403."""
    import uuid as _uuid
    from tests.conftest import _TEST_CSRF_TOKEN, _make_session_cookie
    from app.models import Object, Role, User
    from app.auth import get_current_user
    from fastapi.testclient import TestClient
    from app.main import app

    role = Role(
        id=_uuid.uuid4(),
        key="edit_noview_cq",
        name="Edit No View",
        permissions=["objects:edit", "objects:view_confidential"],
    )
    db.add(role)
    user = User(
        id=_uuid.uuid4(),
        google_sub="sub-noview-cq",
        email="noview@test.de",
        name="No View",
        role=role,
    )
    db.add(user)
    obj = Object(
        id=_uuid.uuid4(),
        short_code="NVW1",
        name="No View Objekt",
        full_address="Teststr. 1",
    )
    db.add(obj)
    db.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    session_cookie = _make_session_cookie({"user_id": str(user.id), "csrf_token": _TEST_CSRF_TOKEN})
    try:
        resp = client.post(
            f"/objects/{obj.id}/zugangscodes/field",
            data={"field_name": "entry_code_main_door", "value": "1234"},
            headers={"X-CSRF-Token": _TEST_CSRF_TOKEN},
            cookies={"session": session_cookie},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403, f"Erwartet 403, bekommen {resp.status_code}"


# ---------------------------------------------------------------------------
# AC7 — Audit-Action wartung_deleted
# ---------------------------------------------------------------------------

def test_wartung_deleted_audit_action(db):
    """delete_wartungspflicht erzeugt AuditLog mit action='wartung_deleted'."""
    import uuid as _uuid
    from app.models import AuditLog, Object, Role, User
    from app.models import InsurancePolicy, Wartungspflicht
    from app.services.steckbrief_wartungen import delete_wartungspflicht

    role = Role(id=_uuid.uuid4(), key="audit_cq", name="Audit CQ", permissions=["objects:edit"])
    db.add(role)
    user = User(
        id=_uuid.uuid4(),
        google_sub="sub-audit-cq",
        email="auditcq@test.de",
        name="Audit CQ",
        role=role,
    )
    db.add(user)
    obj = Object(
        id=_uuid.uuid4(), short_code="AUD1", name="Audit Objekt", full_address="Auditstr. 1"
    )
    db.add(obj)
    policy = InsurancePolicy(id=_uuid.uuid4(), object_id=obj.id)
    db.add(policy)
    wart = Wartungspflicht(
        id=_uuid.uuid4(), policy_id=policy.id, object_id=obj.id, bezeichnung="Heizung", intervall_monate=12
    )
    db.add(wart)
    db.commit()

    delete_wartungspflicht(db, wart, user, request=None)
    db.commit()

    log = db.query(AuditLog).filter(AuditLog.action == "wartung_deleted").first()
    assert log is not None, "Kein AuditLog-Eintrag mit action='wartung_deleted' gefunden"
    assert str(log.entity_id) == str(wart.id)


# ---------------------------------------------------------------------------
# AC8 — field_label Filter
# ---------------------------------------------------------------------------

def test_field_label_filter():
    """field_label gibt human-readable Labels zurueck, Fallback ist Titlecase."""
    from app.templating import templates

    label_fn = templates.env.filters.get("field_label")
    assert label_fn is not None, "field_label-Filter nicht in templates.env.filters registriert"

    assert label_fn("year_built") == "Baujahr"
    assert label_fn("unknown_field") == "Unknown Field"
    assert label_fn("weg_nr") == "WEG-Nr."
