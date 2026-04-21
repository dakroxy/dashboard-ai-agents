"""Permission-Matrix fuer Router-Gates.

Prueft pro Route-Kategorie:
- unauthenticated → 302/307 Redirect zur Login-Seite
- authenticated, aber ohne benoetigte Permission → 403
- authenticated + Permission in `permissions_extra` → 200

Permissions werden ohne Role direkt via `permissions_extra` gesetzt, damit wir
keine Role-Fixtures und keine default_role-Seed-Logik mit in den Testpfad
ziehen muessen.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import User, Workflow
from tests.conftest import _TestSessionLocal  # type: ignore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def user_factory(db):
    """Erstellt einen User mit gesetzten Extra-Permissions (ohne Role)."""
    created: list[User] = []

    def _make(permissions: list[str] | None = None) -> User:
        user = User(
            id=uuid.uuid4(),
            google_sub=f"google-sub-{uuid.uuid4().hex[:12]}",
            email=f"test-{uuid.uuid4().hex[:8]}@dbshome.de",
            name="Perm Test User",
            permissions_extra=permissions or [],
            permissions_denied=[],
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        created.append(user)
        return user

    return _make


@pytest.fixture
def client_as():
    """Factory liefert einen TestClient mit User-Override auf den uebergebenen User."""

    def _client(user: User | None) -> TestClient:
        def override_db():
            session = _TestSessionLocal()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_db

        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_optional_user] = lambda: user
        else:
            app.dependency_overrides[get_optional_user] = lambda: None

        return TestClient(app, raise_server_exceptions=False, follow_redirects=False)

    yield _client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Admin-Routes (users:manage / audit_log:view)
# ---------------------------------------------------------------------------

class TestAdminDashboardGate:
    def test_anonymous_gets_redirect(self, client_as):
        resp = client_as(None).get("/admin")
        assert resp.status_code in (302, 307)

    def test_authenticated_without_perm_gets_403(self, user_factory, client_as):
        resp = client_as(user_factory([])).get("/admin")
        assert resp.status_code == 403

    def test_with_users_manage_gets_200(self, user_factory, client_as):
        resp = client_as(user_factory(["users:manage"])).get("/admin")
        assert resp.status_code == 200

    def test_with_audit_log_view_alone_also_ok(self, user_factory, client_as):
        # /admin nutzt require_any_permission("users:manage", "audit_log:view")
        resp = client_as(user_factory(["audit_log:view"])).get("/admin")
        assert resp.status_code == 200


class TestAdminUsersRoute:
    def test_anonymous_gets_redirect(self, client_as):
        resp = client_as(None).get("/admin/users")
        assert resp.status_code in (302, 307)

    def test_without_perm_gets_403(self, user_factory, client_as):
        resp = client_as(user_factory(["audit_log:view"])).get("/admin/users")
        assert resp.status_code == 403

    def test_with_users_manage_gets_200(self, user_factory, client_as):
        resp = client_as(user_factory(["users:manage"])).get("/admin/users")
        assert resp.status_code == 200


class TestAdminRolesRoute:
    def test_without_perm_gets_403(self, user_factory, client_as):
        resp = client_as(user_factory([])).get("/admin/roles")
        assert resp.status_code == 403

    def test_with_users_manage_gets_200(self, user_factory, client_as):
        resp = client_as(user_factory(["users:manage"])).get("/admin/roles")
        assert resp.status_code == 200


class TestAdminLogsRoute:
    def test_without_perm_gets_403(self, user_factory, client_as):
        # users:manage ist nicht ausreichend
        resp = client_as(user_factory(["users:manage"])).get("/admin/logs")
        assert resp.status_code == 403

    def test_with_audit_log_view_gets_200(self, user_factory, client_as):
        resp = client_as(user_factory(["audit_log:view"])).get("/admin/logs")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Impower-Debug-Routes (impower:debug)
# ---------------------------------------------------------------------------

class TestImpowerDebugRoutes:
    def test_anonymous_health_redirects(self, client_as):
        resp = client_as(None).get("/impower/health")
        assert resp.status_code in (302, 307)

    def test_without_perm_health_403(self, user_factory, client_as):
        resp = client_as(user_factory([])).get("/impower/health")
        assert resp.status_code == 403

    def test_without_perm_properties_403(self, user_factory, client_as):
        resp = client_as(user_factory([])).get("/impower/properties")
        assert resp.status_code == 403

    def test_without_perm_contracts_403(self, user_factory, client_as):
        resp = client_as(user_factory([])).get("/impower/contracts")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Workflows (workflows:view / workflows:edit)
# ---------------------------------------------------------------------------

class TestWorkflowsViewGate:
    def test_anonymous_redirects(self, client_as):
        resp = client_as(None).get("/workflows/")
        assert resp.status_code in (302, 307)

    def test_without_perm_403(self, user_factory, client_as):
        resp = client_as(user_factory([])).get("/workflows/")
        assert resp.status_code == 403

    def test_with_view_perm_200(self, user_factory, client_as):
        resp = client_as(user_factory(["workflows:view"])).get("/workflows/")
        assert resp.status_code == 200


class TestWorkflowsEditGate:
    def test_edit_requires_edit_permission(self, db, user_factory, client_as):
        # Workflow fuer den Update-Aufruf seed-en
        wf = Workflow(
            id=uuid.uuid4(),
            key="test_wf",
            name="Test WF",
            description="",
            model="claude-opus-4-7",
            chat_model="claude-sonnet-4-6",
            system_prompt="prompt",
            learning_notes="",
            active=True,
        )
        db.add(wf)
        db.commit()

        form_data = {
            "name": "Test WF",
            "description": "",
            "model": "claude-opus-4-7",
            "chat_model": "claude-sonnet-4-6",
            "system_prompt": "prompt",
            "learning_notes": "",
        }

        # view allein reicht NICHT fuer POST
        resp_view_only = client_as(user_factory(["workflows:view"])).post(
            "/workflows/test_wf", data=form_data,
        )
        assert resp_view_only.status_code == 403

    def test_edit_with_edit_permission_succeeds(self, db, user_factory, client_as):
        wf = Workflow(
            id=uuid.uuid4(),
            key="test_wf_edit",
            name="Test WF",
            description="",
            model="claude-opus-4-7",
            chat_model="claude-sonnet-4-6",
            system_prompt="prompt",
            learning_notes="",
            active=True,
        )
        db.add(wf)
        db.commit()

        form_data = {
            "name": "Test WF",
            "description": "",
            "model": "claude-opus-4-7",
            "chat_model": "claude-sonnet-4-6",
            "system_prompt": "prompt",
            "learning_notes": "",
        }

        resp = client_as(user_factory(["workflows:edit"])).post(
            "/workflows/test_wf_edit", data=form_data,
        )
        # 303 See Other Redirect auf die Edit-Seite
        assert resp.status_code in (200, 303)


# ---------------------------------------------------------------------------
# effective_permissions — Denied beats Extra
# ---------------------------------------------------------------------------

class TestEffectivePermissionsDenied:
    def test_denied_overrides_extra(self, user_factory, client_as):
        user = user_factory(["users:manage"])
        # User hat die Perm, aber denies she → 403
        user.permissions_denied = ["users:manage"]

        resp = client_as(user).get("/admin/users")
        assert resp.status_code == 403

    def test_disabled_user_has_no_permissions(self, user_factory, client_as):
        import datetime

        user = user_factory(["users:manage"])
        user.disabled_at = datetime.datetime.utcnow()

        resp = client_as(user).get("/admin/users")
        assert resp.status_code == 403
