"""Smoke tests for all major routes — auth protection and basic responses."""
from __future__ import annotations

import pytest

from app.main import app


class TestHealthEndpoint:
    def test_returns_200(self, anon_client):
        resp = anon_client.get("/health")
        assert resp.status_code == 200

    def test_returns_ok_status(self, anon_client):
        data = anon_client.get("/health").json()
        assert data["status"] == "ok"

    def test_returns_env(self, anon_client):
        data = anon_client.get("/health").json()
        assert "env" in data


class TestIndexPage:
    def test_anonymous_gets_200(self, anon_client):
        resp = anon_client.get("/")
        assert resp.status_code == 200

    def test_authenticated_gets_200(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200

    def test_content_type_is_html(self, anon_client):
        resp = anon_client.get("/")
        assert "text/html" in resp.headers["content-type"]


class TestAuthRoutes:
    def test_google_login_redirects(self, anon_client):
        resp = anon_client.get("/auth/google/login")
        # Authlib or similar will redirect to Google; expect a redirect response
        assert resp.status_code in (302, 307)

    def test_logout_clears_session_and_redirects(self, anon_client):
        resp = anon_client.get("/auth/logout")
        assert resp.status_code in (302, 303, 307)
        # Must redirect to / or similar, not to a broken page
        location = resp.headers.get("location", "")
        assert location in ("/", "http://testserver/")


class TestDocumentsListRoute:
    def test_unauthenticated_redirects_to_login(self, anon_client):
        resp = anon_client.get("/documents/")
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "google/login" in location or "login" in location

    def test_authenticated_returns_200(self, auth_client):
        resp = auth_client.get("/documents/")
        assert resp.status_code == 200

    def test_authenticated_returns_html(self, auth_client):
        resp = auth_client.get("/documents/")
        assert "text/html" in resp.headers["content-type"]


class TestImpowerRoutes:
    def test_health_requires_auth(self, anon_client):
        resp = anon_client.get("/impower/health")
        assert resp.status_code in (302, 307)

    def test_properties_requires_auth(self, anon_client):
        resp = anon_client.get("/impower/properties")
        assert resp.status_code in (302, 307)


class TestWorkflowsRoutes:
    def test_list_requires_auth(self, anon_client):
        resp = anon_client.get("/workflows/")
        assert resp.status_code in (302, 307)

    def test_authenticated_returns_200(self, auth_client):
        resp = auth_client.get("/workflows/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# X-Robots-Tag Default-Header (Story 1.1, AC3)
# ---------------------------------------------------------------------------


@pytest.fixture
def boom_route():
    async def _boom():
        raise RuntimeError("boom")

    app.add_api_route("/_test/boom", _boom, methods=["GET"])
    try:
        yield "/_test/boom"
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes
            if getattr(r, "path", None) != "/_test/boom"
        ]


class TestXRobotsTagHeader:
    def test_set_on_health(self, anon_client):
        resp = anon_client.get("/health")
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_set_on_index(self, anon_client):
        # / rendert index.html direkt (kein Redirect) — auch hier Header pruefen.
        resp = anon_client.get("/")
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_set_on_redirect(self, anon_client):
        # Logout redirect → 302/303 — Header muss auch da drauf sein.
        resp = anon_client.get("/auth/logout")
        assert resp.status_code in (302, 303, 307)
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_set_on_500(self, anon_client, boom_route):
        resp = anon_client.get(boom_route)
        assert resp.status_code == 500
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_set_on_403(self, auth_client):
        # test_user hat weder audit_log:view noch users:manage -> 403
        resp = auth_client.get("/admin/logs")
        assert resp.status_code == 403
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_set_on_htmx_request(self, auth_client):
        # HTMX-Fragment-Response: Middleware darf nicht auf Full-Page-Rendern
        # beschraenkt sein. 1-1-test-summary "Naechste Schritte" hatte das
        # als nur implizit abgedeckt markiert; hier explizit.
        resp = auth_client.get("/workflows/", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"
