"""Tests for document upload validation and document management routes."""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# Minimal but valid PDF magic bytes
MINIMAL_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


class TestUploadValidation:
    """POST /documents/ — validates file before background task runs."""

    def test_rejects_non_pdf_content_type(self, auth_client):
        resp = auth_client.post(
            "/documents/",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_rejects_empty_file(self, auth_client):
        resp = auth_client.post(
            "/documents/",
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        )
        assert resp.status_code == 400

    def test_rejects_file_without_pdf_magic_bytes(self, auth_client):
        resp = auth_client.post(
            "/documents/",
            files={"file": ("fake.pdf", io.BytesIO(b"This is not a PDF"), "application/pdf")},
        )
        assert resp.status_code == 400

    def test_rejects_oversized_file(self, auth_client):
        # 21 MB file > default max of 20 MB
        big_content = b"%PDF" + b"x" * (21 * 1024 * 1024)
        resp = auth_client.post(
            "/documents/",
            files={"file": ("big.pdf", io.BytesIO(big_content), "application/pdf")},
        )
        assert resp.status_code == 413

    def test_requires_auth(self, anon_client_with_csrf):
        # Fixture mit CSRF-Token-Bypass, damit wir die Auth-Layer-Logik
        # pruefen koennen (302/307 Redirect zur Login-Page) statt am
        # CSRF-Reject (403) haengen zu bleiben.
        resp = anon_client_with_csrf.post(
            "/documents/",
            files={"file": ("test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        assert resp.status_code in (302, 307)

    def test_csrf_blocks_anonymous_post_without_token(self, anon_client):
        # Production-Realitaet: ein Drittangreifer ohne Session-Cookie und
        # ohne X-CSRF-Token-Header bekommt 403 von der CSRFMiddleware,
        # nicht 302/307 vom Auth-Layer. Auth-Schutz greift sekundaer.
        resp = anon_client.post(
            "/documents/",
            files={"file": ("test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        assert resp.status_code == 403

    @patch("app.routers.documents._run_extraction")
    def test_valid_pdf_returns_redirect(self, mock_run, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.routers.documents.UPLOAD_DIR", tmp_path)
        resp = auth_client.post(
            "/documents/",
            files={"file": ("mandat.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        assert resp.status_code == 303
        location = resp.headers.get("location", "")
        assert "/documents/" in location

    @patch("app.routers.documents._run_extraction")
    def test_valid_pdf_creates_document_record(self, mock_run, auth_client, db, tmp_path, monkeypatch):
        from app.models import Document

        monkeypatch.setattr("app.routers.documents.UPLOAD_DIR", tmp_path)
        auth_client.post(
            "/documents/",
            files={"file": ("mandat.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        doc = db.query(Document).first()
        assert doc is not None
        assert doc.original_filename == "mandat.pdf"
        assert doc.status == "uploaded"

    @patch("app.routers.documents._run_extraction")
    def test_duplicate_upload_reuses_stored_file(self, mock_run, auth_client, db, tmp_path, monkeypatch):
        """Same PDF uploaded twice should share the same stored file (deduplication by SHA256)."""
        from app.models import Document

        monkeypatch.setattr("app.routers.documents.UPLOAD_DIR", tmp_path)
        auth_client.post(
            "/documents/",
            files={"file": ("first.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        auth_client.post(
            "/documents/",
            files={"file": ("second.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        docs = db.query(Document).all()
        assert len(docs) == 2
        # Both docs point to the same stored file
        assert docs[0].stored_path == docs[1].stored_path


class TestDocumentDetailRoute:
    @patch("app.routers.documents._run_extraction")
    def test_own_document_returns_200(self, mock_run, auth_client, db, test_user, tmp_path, monkeypatch):
        from app.models import Document

        monkeypatch.setattr("app.routers.documents.UPLOAD_DIR", tmp_path)
        # Upload a document so it exists in DB
        resp = auth_client.post(
            "/documents/",
            files={"file": ("doc.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        location = resp.headers["location"]
        doc_id = location.rstrip("/").split("/")[-1]

        resp = auth_client.get(f"/documents/{doc_id}")
        assert resp.status_code == 200

    def test_nonexistent_document_returns_404(self, auth_client):
        resp = auth_client.get(f"/documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_other_users_document_hidden_without_view_all(self, auth_client, db):
        """Ohne `documents:view_all` darf ein User keine fremden Docs sehen.

        Der conftest-`test_user` hat `documents:view_all` per Default — hier
        tauschen wir den Override auf einen restricted User ohne dieses Recht.
        Die `auth_client`-Fixture hat lifespan bereits ausgefuehrt, damit ist
        der sepa_mandate-Workflow geseedet.
        """
        from app.auth import get_current_user, get_optional_user
        from app.main import app as _app
        from app.models import Document, ResourceAccess, User, Workflow
        from app.permissions import RESOURCE_TYPE_WORKFLOW

        wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()

        restricted = User(
            id=uuid.uuid4(),
            google_sub="restricted-sub",
            email="restricted@dbshome.de",
            name="Restricted",
            permissions_extra=["documents:upload"],  # kein view_all
        )
        db.add(restricted)
        db.add(
            ResourceAccess(
                id=uuid.uuid4(),
                user_id=restricted.id,
                resource_type=RESOURCE_TYPE_WORKFLOW,
                resource_id=wf.id,
                mode="allow",
            )
        )

        other_user = User(
            id=uuid.uuid4(),
            google_sub="other-sub",
            email="other@dbshome.de",
            name="Other User",
        )
        db.add(other_user)
        doc = Document(
            id=uuid.uuid4(),
            uploaded_by_id=other_user.id,
            workflow_id=wf.id,
            original_filename="other.pdf",
            stored_path="deadbeef.pdf",
            content_type="application/pdf",
            size_bytes=100,
            sha256="deadbeef" * 8,
            status="uploaded",
        )
        db.add(doc)
        db.commit()

        _app.dependency_overrides[get_current_user] = lambda: restricted
        _app.dependency_overrides[get_optional_user] = lambda: restricted

        resp = auth_client.get(f"/documents/{doc.id}")
        assert resp.status_code == 404


class TestApproveRoute:
    def _create_doc(self, db, user, status: str) -> "Document":  # noqa: F821
        from app.models import Document, Workflow

        wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
        doc = Document(
            id=uuid.uuid4(),
            uploaded_by_id=user.id,
            workflow_id=wf.id,
            original_filename="mandat.pdf",
            stored_path="aabbccdd.pdf",
            content_type="application/pdf",
            size_bytes=len(MINIMAL_PDF),
            sha256="aabbccdd" * 8,
            status=status,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    def test_approve_wrong_status_returns_400(self, auth_client, db, test_user):
        doc = self._create_doc(db, test_user, "uploading")
        resp = auth_client.post(f"/documents/{doc.id}/approve")
        assert resp.status_code == 400

    @patch("app.routers.documents._run_write")
    def test_approve_valid_status_redirects(self, mock_write, auth_client, db, test_user):
        doc = self._create_doc(db, test_user, "matched")
        resp = auth_client.post(f"/documents/{doc.id}/approve")
        assert resp.status_code == 303

    @patch("app.routers.documents._run_write")
    def test_approve_creates_audit_log(self, mock_write, auth_client, db, test_user):
        from app.models import AuditLog

        doc = self._create_doc(db, test_user, "matched")
        auth_client.post(f"/documents/{doc.id}/approve")
        log = db.query(AuditLog).filter_by(document_id=doc.id).first()
        assert log is not None
        assert log.action == "document_approved"
        assert log.user_email == "test@dbshome.de"

    @patch("app.routers.documents._run_write")
    def test_approve_sets_status_approved(self, mock_write, auth_client, db, test_user):
        from app.models import Document

        doc = self._create_doc(db, test_user, "needs_review")
        auth_client.post(f"/documents/{doc.id}/approve")
        db.refresh(doc)
        assert doc.status == "approved"

    def test_approve_nonexistent_returns_404(self, auth_client):
        resp = auth_client.post(f"/documents/{uuid.uuid4()}/approve")
        assert resp.status_code == 404
