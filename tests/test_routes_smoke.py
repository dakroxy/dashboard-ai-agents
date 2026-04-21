"""Smoke tests for all major routes — auth protection and basic responses."""
from __future__ import annotations


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
