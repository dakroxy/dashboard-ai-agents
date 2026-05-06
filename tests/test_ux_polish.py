"""Story 5-5 — UX-Polish & Frontend-Haertung: Tests fuer AC1-AC8."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models import Document, Extraction, Object, User, Workflow
from app.models.governance import ReviewQueueEntry


# ---------------------------------------------------------------------------
# AC1 — Review-Queue Micro-Fixes
# ---------------------------------------------------------------------------

def _make_review_entry(db, **kwargs):
    defaults = dict(
        target_entity_type="object",
        target_entity_id=uuid.uuid4(),
        field_name="heating_type",
        proposed_value={"value": "Fernwaerme"},
        agent_ref="test-agent-v1",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    entry = ReviewQueueEntry(**defaults)
    db.add(entry)
    db.commit()
    return entry


def test_review_queue_micro_fixes(steckbrief_admin_client, db):
    """AC1: Alle 6 Micro-Fixes am Review-Queue-Fragment."""
    now = datetime.now(timezone.utc)
    # agent_ref laenger als 14rem → truncate; confidence > 1.0 → clamped;
    # created_at in der Zukunft → age_days = 0 (max-Guard)
    entry = _make_review_entry(
        db,
        target_entity_type="object",
        target_entity_id=uuid.uuid4(),
        agent_ref="x" * 40,
        confidence=1.5,
        created_at=now + timedelta(seconds=10),
    )
    resp = steckbrief_admin_client.get("/admin/review-queue")
    assert resp.status_code == 200
    body = resp.text

    # #14: max-w-[14rem] und truncate im agent_ref-td
    assert "max-w-[14rem]" in body
    assert "truncate" in body

    # #16: Confidence auf 100% geclampt (nicht 150%)
    assert "100 %" in body
    assert "150 %" not in body

    # #15: age_days >= 0 (kein negativer Wert bei Future-Timestamp)
    assert "0 Tage" in body
    assert "-1 Tage" not in body

    # #17: Anchor-Text hat "object/"-Prefix vor der getrunkten ID
    assert "object/" in body


# ---------------------------------------------------------------------------
# AC2 — Sidebar: kein Doppel-Highlight bei /admin/review-queue
# ---------------------------------------------------------------------------

def test_sidebar_active_no_double_highlight(steckbrief_admin_client):
    """AC2: /admin/review-queue hebt nur den Review-Queue-Link hervor, nicht Admin."""
    resp = steckbrief_admin_client.get("/admin/review-queue")
    assert resp.status_code == 200
    body = resp.text

    # Aktive Links haben `border-emerald-400` in ihrer Klasse.
    # Wir suchen alle <a>-Tags mit aktivem Highlight.
    active_hrefs = re.findall(
        r'<a href="([^"]+)"[^>]*border-emerald-400[^>]*>',
        body,
        re.DOTALL,
    )
    assert any("review-queue" in h for h in active_hrefs), (
        "Review-Queue-Link muss aktiv sein"
    )
    # Der reine /admin-Link (ohne /review-queue) darf nicht aktiv sein
    assert not any(h == "/admin" for h in active_hrefs), (
        "Admin-Link darf bei /admin/review-queue nicht aktiv sein"
    )


# ---------------------------------------------------------------------------
# AC3 — Objekt-Liste: Volle Seite respektiert filter_reserve
# ---------------------------------------------------------------------------

def test_list_objects_full_page_respects_filter_reserve(
    steckbrief_admin_client, db
):
    """AC3: GET /objects?filter_reserve=true filtert auf Objekte unter Rücklage-Ziel."""
    # reserve_current < reserve_target * 6 → below target → erscheint
    obj_below = Object(
        id=uuid.uuid4(),
        short_code="BLW1",
        name="Objekt unter Ziel",
        reserve_current=Decimal("100"),
        reserve_target=Decimal("100"),  # 100 < 600 → below target
    )
    # reserve_current >= reserve_target * 6 → above target → erscheint nicht
    obj_above = Object(
        id=uuid.uuid4(),
        short_code="ABV1",
        name="Objekt über Ziel",
        reserve_current=Decimal("700"),
        reserve_target=Decimal("100"),  # 700 < 600 → False → not below
    )
    db.add_all([obj_below, obj_above])
    db.commit()

    resp = steckbrief_admin_client.get("/objects?filter_reserve=true")
    assert resp.status_code == 200
    body = resp.text

    assert "BLW1" in body, "Objekt unter Ziel muss erscheinen"
    assert "ABV1" not in body, "Objekt über Ziel darf nicht erscheinen"


# ---------------------------------------------------------------------------
# AC4 — money_de Filter (Unit-Test)
# ---------------------------------------------------------------------------

def test_money_de_filter():
    """AC4: money_de-Filter formatiert Zahlen mit deutschem Tausenderpunkt."""
    from app.templating import templates

    money_de = templates.env.filters["money_de"]

    assert money_de(1234567.4) == "1.234.567"
    assert money_de(0) == "0"
    assert money_de(1000) == "1.000"
    assert money_de(999) == "999"
    assert money_de(1234567890) == "1.234.567.890"


# ---------------------------------------------------------------------------
# AC7 — _manual_fields werden in extracted gepflegt
# ---------------------------------------------------------------------------

def _make_sepa_doc_with_extraction(db, user):
    """Erstellt ein SEPA-Lastschrift-Dokument mit einer Initial-Extraction."""
    wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
    assert wf is not None, "sepa_mandate-Workflow muss geseedet sein"

    doc = Document(
        id=uuid.uuid4(),
        uploaded_by_id=user.id,
        workflow_id=wf.id,
        original_filename="mandat.pdf",
        stored_path="test_manual.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        sha256="abcd1234" * 8,
        status="extracted",
    )
    db.add(doc)
    db.flush()

    extraction = Extraction(
        id=uuid.uuid4(),
        document_id=doc.id,
        model="claude-opus-4-7",
        prompt_version="sepa-v1",
        raw_response="{}",
        extracted={
            "owner_name": "Floegel GmbH",
            "iban": "DE89370400440532013000",
            "weg_kuerzel": "HAM61",
        },
        status="ok",
        created_at=datetime.now(timezone.utc),
    )
    db.add(extraction)
    db.commit()
    db.refresh(doc)
    return doc, extraction


def _make_mock_request():
    req = MagicMock()
    req.headers.get.return_value = None
    req.client = MagicMock(host="127.0.0.1")
    req.state = MagicMock()
    req.state._accessible_object_ids = None
    return req


def test_manual_pill_set_on_field_edit(db, auth_client, test_user):
    """AC7: _manual_fields-Liste wird beim Feld-Edit korrekt befuellt."""
    from app.services.document_field_edit import update_extraction_field

    doc, _ = _make_sepa_doc_with_extraction(db, test_user)
    mock_req = _make_mock_request()

    # Erster Edit: owner_name
    result1 = update_extraction_field(db, doc, "owner_name", "Müller GmbH", test_user, mock_req)
    assert result1 is not None
    assert result1.extracted["owner_name"] == "Müller GmbH"
    assert "_manual_fields" in result1.extracted
    assert "owner_name" in result1.extracted["_manual_fields"]

    # Zweiter Edit: weg_kuerzel (Textfeld, keine IBAN-Validierung noetig)
    # Um einen weiteren Edit zu testen, muessen wir doc.status zuruecksetzen
    db.refresh(doc)
    doc.status = "extracted"
    db.commit()

    result2 = update_extraction_field(db, doc, "weg_kuerzel", "HAM62", test_user, mock_req)
    assert result2 is not None
    manual_fields = result2.extracted.get("_manual_fields", [])
    assert "weg_kuerzel" in manual_fields
    # Idempotent: owner_name ist aus der vorherigen Row schon drin (deepcopy der letzten Extraction)
    assert "owner_name" in manual_fields

    # Idempotenz-Check: gleiches Feld nochmals → erscheint nur einmal
    db.refresh(doc)
    doc.status = "extracted"
    db.commit()

    result3 = update_extraction_field(db, doc, "weg_kuerzel", "HAM63", test_user, mock_req)
    assert result3 is not None
    assert result3.extracted["_manual_fields"].count("weg_kuerzel") == 1


# ---------------------------------------------------------------------------
# AC8 — Versicherungen-Formular sichtbar bei Validierungsfehler
# ---------------------------------------------------------------------------

def test_police_form_visible_on_validation_error(steckbrief_admin_client, db):
    """AC8: #neue-police-form ist bei form_error nicht hidden."""
    obj = Object(
        id=uuid.uuid4(),
        short_code="TST1",
        name="Test-Objekt",
    )
    db.add(obj)
    db.commit()

    # end_date vor start_date → validate_police_dates gibt Fehler zurück
    resp = steckbrief_admin_client.post(
        f"/objects/{obj.id}/policen",
        data={
            "start_date": "2025-12-15",
            "end_date": "2025-01-01",
        },
    )
    assert resp.status_code == 422
    body = resp.text

    # Das Formular darf `hidden` NICHT enthalten (weder in id-Nachbarschaft noch generell
    # als Teil des Form-Divs)
    # Wir suchen den Form-Div und prüfen, dass er kein `hidden` in der Klasse hat
    form_match = re.search(r'id="neue-police-form"[^>]*class="([^"]+)"', body)
    if not form_match:
        # Manchmal steht class vor id — beide Richtungen prüfen
        form_match = re.search(r'class="([^"]*)"[^>]*id="neue-police-form"', body)

    assert form_match is not None, "#neue-police-form muss im HTML vorhanden sein"
    form_classes = form_match.group(1)
    # Die Klasse darf nicht mit "hidden " beginnen oder "hidden " enthalten
    assert "hidden" not in form_classes.split(), (
        f"#neue-police-form darf nicht 'hidden' haben, hat aber: {form_classes!r}"
    )
