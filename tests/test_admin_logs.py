"""Story 1.1 — Audit-Log-Filter-Dropdown zeigt Known-Actions auch ohne Log-Eintrag."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import User
from tests.conftest import _TestSessionLocal, _make_session_cookie, _TEST_CSRF_TOKEN  # type: ignore


@pytest.fixture
def admin_client(db):
    user = User(
        id=uuid.uuid4(),
        google_sub=f"google-sub-{uuid.uuid4().hex[:12]}",
        email="admin@dbshome.de",
        name="Admin Test",
        permissions_extra=["audit_log:view", "users:manage"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_db():
        session = _TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        yield c

    app.dependency_overrides.clear()


class TestAuditLogFilterDropdown:
    def test_dropdown_contains_object_created_without_existing_log(self, admin_client):
        # Frische DB — keine AuditLog-Rows mit "object_created".
        # Dropdown muss die Action trotzdem als Option anbieten.
        resp = admin_client.get("/admin/logs")
        assert resp.status_code == 200
        assert 'value="object_created"' in resp.text

    def test_dropdown_contains_all_new_steckbrief_actions(self, admin_client):
        resp = admin_client.get("/admin/logs")
        assert resp.status_code == 200
        for action in [
            "object_field_updated",
            "object_photo_uploaded",
            "object_photo_deleted",
            "registry_entry_created",
            "registry_entry_updated",
            "review_queue_created",
            "review_queue_approved",
            "review_queue_rejected",
            "sync_started",
            "sync_finished",
            "sync_failed",
            "policy_violation",
            "encryption_key_missing",
        ]:
            assert f'value="{action}"' in resp.text, (
                f"Action {action} fehlt im Dropdown"
            )

    def test_dropdown_contains_existing_actions(self, admin_client):
        resp = admin_client.get("/admin/logs")
        assert resp.status_code == 200
        assert 'value="login"' in resp.text
        assert 'value="document_uploaded"' in resp.text
