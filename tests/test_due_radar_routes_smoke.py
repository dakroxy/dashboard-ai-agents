"""Story 2.5 — Route-Smoke-Tests fuer Due-Radar."""
from __future__ import annotations

import uuid

import pytest

from app.models import User
from app.auth import get_current_user, get_optional_user
from app.db import get_db
from fastapi.testclient import TestClient
from tests.conftest import _TestSessionLocal
from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def due_radar_user(db):
    """User mit due_radar:view + objects:view (beide noetig: objects:view liefert
    accessible_object_ids, sonst bleibt Due-Radar leer — v1-ACL-Semantik)."""
    user = db.query(User).filter(User.email == "due-radar@dbshome.de").first()
    if user is not None:
        return user
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-due-radar",
        email="due-radar@dbshome.de",
        name="Due Radar User",
        permissions_extra=["due_radar:view", "objects:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def due_radar_client(db, due_radar_user):
    def override_db():
        yield db

    def override_user():
        return due_radar_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_requires_login(anon_client):
    """Unauthenticated → 302 zu Google-Login."""
    resp = anon_client.get("/due-radar")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/auth/google/login")


def test_forbidden_without_due_radar_view(auth_client):
    """`test_user` hat kein due_radar:view → 403 mit Hinweis auf fehlende Permission."""
    resp = auth_client.get("/due-radar")
    assert resp.status_code == 403
    assert "due_radar:view" in resp.text


def test_ok_for_user_with_permission(due_radar_client):
    """User mit due_radar:view bekommt 200 + HTML."""
    resp = due_radar_client.get("/due-radar")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_empty_state_text(due_radar_client):
    """AC3: Bei 0 Eintraegen erscheint der Empty-State-Text."""
    resp = due_radar_client.get("/due-radar")
    assert resp.status_code == 200
    assert "Keine ablaufenden Einträge in den nächsten 90 Tagen." in resp.text


def test_sidebar_link_visible_for_permitted_user(due_radar_client):
    """AC5 positiv: Sidebar zeigt Due-Radar-Link fuer berechtigten User."""
    resp = due_radar_client.get("/")
    assert resp.status_code == 200
    assert 'href="/due-radar"' in resp.text


def test_sidebar_link_hidden_for_unpermitted_user(auth_client):
    """AC5 negativ: Sidebar zeigt keinen Due-Radar-Link fuer unberechtigten User."""
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert 'href="/due-radar"' not in resp.text
    assert "Due-Radar" not in resp.text
