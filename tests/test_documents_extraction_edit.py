"""Tests fuer das Inline-Edit der SEPA-Extraktionsfelder.

Deckt:
- Happy-Path Text-Feld
- IBAN-Validierung (gueltig / ungueltig / Zero-Width-Space)
- SEPA-Datum-Validierung
- Status-Sperre + Whitelist + Permission-Check
- Audit-Row + neue Extraction-Row pro Save
- GET edit-form mit korrektem Wert

Re-Match wird per BackgroundTask getriggert; im Test wird `_run_matching`
gemockt, damit kein echter Impower-Call faellt.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models import AuditLog, Document, Extraction, User, Workflow


SAMPLE_EXTRACTION: dict[str, Any] = {
    "weg_kuerzel": "HAM61",
    "weg_name": "WEG Floegel",
    "weg_adresse": "Floegelstrasse 1, 22177 Hamburg",
    "unit_nr": "5",
    "owner_name": "Max Floegel",
    "iban": "DE72200505501050170859",
    "bic": "HASPDEHHXXX",
    "bank_name": "Hamburger Sparkasse",
    "sepa_date": "2026-04-15",
    "creditor_id": "DE71ZZZ00002822264",
    "confidence": "high",
    "notes": "OCR sauber",
}


def _create_doc_with_extraction(
    db,
    user: User,
    status: str = "needs_review",
    extracted: dict[str, Any] | None = None,
) -> Document:
    wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
    doc = Document(
        id=uuid.uuid4(),
        uploaded_by_id=user.id,
        workflow_id=wf.id,
        original_filename="mandat.pdf",
        stored_path=f"{uuid.uuid4().hex}.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="a" * 64,
        status=status,
    )
    db.add(doc)
    extr = Extraction(
        id=uuid.uuid4(),
        document_id=doc.id,
        model="claude-opus-4-7",
        prompt_version="sepa-v1",
        raw_response="{}",
        extracted=dict(extracted or SAMPLE_EXTRACTION),
        status="ok",
    )
    db.add(extr)
    db.commit()
    db.refresh(doc)
    return doc


@pytest.fixture(autouse=True)
def _mock_run_matching(monkeypatch):
    """Verhindert echte Impower-Calls im BackgroundTask."""
    monkeypatch.setattr(
        "app.routers.documents._run_matching",
        lambda *a, **kw: None,
    )


# ---------------------------------------------------------------------------
# POST /documents/{id}/extraction/field — Happy-Path
# ---------------------------------------------------------------------------

class TestSaveHappyPath:
    def test_save_text_field_creates_new_extraction_row(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "weg_kuerzel", "value": "BRE11"},
        )
        assert resp.status_code == 200

        rows = (
            db.query(Extraction)
            .filter(Extraction.document_id == doc.id)
            .order_by(Extraction.created_at.desc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].model == "manual"
        assert rows[0].extracted["weg_kuerzel"] == "BRE11"
        assert rows[0].extracted["iban"] == SAMPLE_EXTRACTION["iban"]  # andere Felder unangetastet

    def test_save_text_field_resets_status_to_matching(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user, status="needs_review")
        auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "weg_kuerzel", "value": "BRE11"},
        )
        db.refresh(doc)
        assert doc.status == "matching"
        assert doc.matching_result is None
        assert doc.impower_result is None

    def test_save_iban_happy_path(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)
        new_iban = "DE89370400440532013000"

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "iban", "value": new_iban},
        )
        assert resp.status_code == 200

        rows = (
            db.query(Extraction)
            .filter(Extraction.document_id == doc.id)
            .order_by(Extraction.created_at.desc())
            .all()
        )
        assert rows[0].extracted["iban"] == new_iban

    def test_save_iban_with_zero_width_space_is_normalized(
        self, auth_client, db, test_user
    ):
        # Zero-Width-Space (U+200B) zwischen Ziffern — Sonnet faengt das im Chat
        # und der gleiche Guard muss hier greifen.
        doc = _create_doc_with_extraction(db, test_user)
        iban_with_zwsp = "DE89​37040044​0532013000"

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "iban", "value": iban_with_zwsp},
        )
        assert resp.status_code == 200

        rows = (
            db.query(Extraction)
            .filter(Extraction.document_id == doc.id)
            .order_by(Extraction.created_at.desc())
            .all()
        )
        assert rows[0].extracted["iban"] == "DE89370400440532013000"

    def test_save_empty_value_persists_null(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "unit_nr", "value": ""},
        )
        assert resp.status_code == 200

        rows = (
            db.query(Extraction)
            .filter(Extraction.document_id == doc.id)
            .order_by(Extraction.created_at.desc())
            .all()
        )
        assert rows[0].extracted["unit_nr"] is None

    def test_save_creates_audit_row(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)

        auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "owner_name", "value": "Marlene Floegel"},
        )

        audit_rows = (
            db.query(AuditLog)
            .filter(
                AuditLog.document_id == doc.id,
                AuditLog.action == "extraction_field_updated",
            )
            .all()
        )
        assert len(audit_rows) == 1
        details = audit_rows[0].details_json
        assert details["field"] == "owner_name"
        assert details["old"] == SAMPLE_EXTRACTION["owner_name"]
        assert details["new"] == "Marlene Floegel"

    def test_save_no_op_when_value_unchanged(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)
        existing_value = SAMPLE_EXTRACTION["weg_kuerzel"]

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "weg_kuerzel", "value": existing_value},
        )
        assert resp.status_code == 200

        rows = (
            db.query(Extraction)
            .filter(Extraction.document_id == doc.id)
            .all()
        )
        assert len(rows) == 1  # keine neue Row
        audit_rows = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .all()
        )
        assert len(audit_rows) == 0

    def test_three_consecutive_saves_create_three_rows(self, auth_client, db, test_user):
        """Zwischen den Saves wird der Status zurueck auf needs_review gesetzt,
        weil der erste Save status="matching" setzt — in Production wuerde der
        BG-Re-Match anschliessend status auf "matched"/"needs_review" updaten;
        im Test ist der BG-Task gemockt, also setzen wir den Status manuell."""
        doc = _create_doc_with_extraction(db, test_user)

        for i, new_val in enumerate(["BRE11", "GVE1", "HAM62"]):
            if i > 0:
                # BG-Re-Match ist gemockt: wir simulieren hier sein Ergebnis
                doc.status = "needs_review"
                db.commit()
            resp = auth_client.post(
                f"/documents/{doc.id}/extraction/field",
                data={"field": "weg_kuerzel", "value": new_val},
            )
            assert resp.status_code == 200

        rows = db.query(Extraction).filter(Extraction.document_id == doc.id).all()
        assert len(rows) == 4  # 1 LLM + 3 manual
        # prompt_version-Suffix darf NICHT compounding -manual-manual-manual werden
        manual_rows = [r for r in rows if r.model == "manual"]
        for r in manual_rows:
            assert r.prompt_version.count("-manual") == 1, r.prompt_version
        audit_rows = (
            db.query(AuditLog)
            .filter(
                AuditLog.document_id == doc.id,
                AuditLog.action == "extraction_field_updated",
            )
            .all()
        )
        assert len(audit_rows) == 3


# ---------------------------------------------------------------------------
# Validierungsfehler (422)
# ---------------------------------------------------------------------------

class TestSaveValidation:
    def test_invalid_iban_renders_form_error(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "iban", "value": "DE25XYZ"},
        )
        # HTTP 200, weil HTMX 2.x default 4xx nicht swappt — Server liefert
        # die Edit-Form mit Inline-Fehler als 200-Response.
        assert resp.status_code == 200
        assert "Ung" in resp.text  # Fehler-Text "Ungültige IBAN" gerendert
        assert "<form" in resp.text  # Edit-Form ist im Markup
        # Keine neue Extraction-Row
        rows = db.query(Extraction).filter(Extraction.document_id == doc.id).all()
        assert len(rows) == 1
        # Kein Audit
        audit_rows = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .all()
        )
        assert len(audit_rows) == 0

    def test_invalid_sepa_date_renders_form_error(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "sepa_date", "value": "04.05.26"},
        )
        assert resp.status_code == 200
        assert "Datum" in resp.text
        rows = db.query(Extraction).filter(Extraction.document_id == doc.id).all()
        assert len(rows) == 1

    def test_iban_only_garbage_chars_renders_form_error(self, auth_client, db, test_user):
        """Eingabe non-empty, aber nach NFKC-Normalize keine Alphanumerik
        → 422-Pfad statt silent-clear."""
        doc = _create_doc_with_extraction(db, test_user)
        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "iban", "value": "!!!"},
        )
        assert resp.status_code == 200
        assert "Ung" in resp.text
        rows = db.query(Extraction).filter(Extraction.document_id == doc.id).all()
        assert len(rows) == 1  # keine neue Row, IBAN nicht ueberschrieben


# ---------------------------------------------------------------------------
# Gates: Status, Whitelist, Permission
# ---------------------------------------------------------------------------

class TestSaveGates:
    def test_status_writing_returns_400(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user, status="writing")

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "weg_kuerzel", "value": "BRE11"},
        )
        assert resp.status_code == 400

    def test_field_not_in_whitelist_returns_400(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)

        resp = auth_client.post(
            f"/documents/{doc.id}/extraction/field",
            data={"field": "confidence", "value": "low"},
        )
        assert resp.status_code == 400

    def test_without_documents_approve_returns_403(self, auth_client, db, test_user):
        # auth_client hat lifespan + workflow-seed gemacht; jetzt User ohne
        # documents:approve einsetzen und in den Override stecken — und die
        # Overrides am Ende restoren, damit nachfolgende Tests den test_user
        # zurueckbekommen.
        from app.auth import get_current_user, get_optional_user
        from app.main import app
        from app.models import ResourceAccess
        from app.permissions import RESOURCE_TYPE_WORKFLOW

        no_approve = User(
            id=uuid.uuid4(),
            google_sub="no-approve-sub",
            email="noapprove@dbshome.de",
            name="No Approve",
            permissions_extra=["documents:upload", "documents:view_all"],
        )
        db.add(no_approve)

        wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
        assert wf is not None, "sepa_mandate workflow muss von der lifespan geseedet sein"
        db.add(
            ResourceAccess(
                id=uuid.uuid4(),
                user_id=no_approve.id,
                resource_type=RESOURCE_TYPE_WORKFLOW,
                resource_id=wf.id,
                mode="allow",
            )
        )
        db.commit()

        doc = _create_doc_with_extraction(db, no_approve)

        prev_get_current = app.dependency_overrides.get(get_current_user)
        prev_get_optional = app.dependency_overrides.get(get_optional_user)
        app.dependency_overrides[get_current_user] = lambda: no_approve
        app.dependency_overrides[get_optional_user] = lambda: no_approve
        try:
            resp = auth_client.post(
                f"/documents/{doc.id}/extraction/field",
                data={"field": "weg_kuerzel", "value": "BRE11"},
            )
            assert resp.status_code == 403
        finally:
            if prev_get_current is not None:
                app.dependency_overrides[get_current_user] = prev_get_current
            if prev_get_optional is not None:
                app.dependency_overrides[get_optional_user] = prev_get_optional


# ---------------------------------------------------------------------------
# GET edit/view fragments
# ---------------------------------------------------------------------------

class TestEditFormGet:
    def test_get_edit_form_returns_current_value(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)

        resp = auth_client.get(
            f"/documents/{doc.id}/extraction/edit",
            params={"field": "weg_kuerzel"},
        )
        assert resp.status_code == 200
        assert SAMPLE_EXTRACTION["weg_kuerzel"] in resp.text
        assert "field" in resp.text  # hidden input
        # Form-Tag muss vorhanden sein
        assert "<form" in resp.text

    def test_get_edit_form_for_iban_uses_text_input(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)
        resp = auth_client.get(
            f"/documents/{doc.id}/extraction/edit",
            params={"field": "iban"},
        )
        assert resp.status_code == 200
        assert SAMPLE_EXTRACTION["iban"] in resp.text

    def test_get_edit_form_for_sepa_date_uses_date_input(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)
        resp = auth_client.get(
            f"/documents/{doc.id}/extraction/edit",
            params={"field": "sepa_date"},
        )
        assert resp.status_code == 200
        assert 'type="date"' in resp.text

    def test_get_edit_form_invalid_field_returns_400(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)
        resp = auth_client.get(
            f"/documents/{doc.id}/extraction/edit",
            params={"field": "confidence"},
        )
        assert resp.status_code == 400

    def test_get_view_fragment_returns_value(self, auth_client, db, test_user):
        doc = _create_doc_with_extraction(db, test_user)
        resp = auth_client.get(
            f"/documents/{doc.id}/extraction/view",
            params={"field": "weg_kuerzel"},
        )
        assert resp.status_code == 200
        assert SAMPLE_EXTRACTION["weg_kuerzel"] in resp.text

    def test_get_edit_form_without_extraction_returns_400(self, auth_client, db, test_user):
        """Doc ohne jegliche Extraction-Row sollte gar nicht erst eine Form anbieten."""
        wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
        doc = Document(
            id=uuid.uuid4(),
            uploaded_by_id=test_user.id,
            workflow_id=wf.id,
            original_filename="leer.pdf",
            stored_path=f"{uuid.uuid4().hex}.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256="b" * 64,
            status="needs_review",
        )
        db.add(doc)
        db.commit()

        resp = auth_client.get(
            f"/documents/{doc.id}/extraction/edit",
            params={"field": "iban"},
        )
        assert resp.status_code == 400
