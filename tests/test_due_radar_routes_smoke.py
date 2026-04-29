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


# ---------------------------------------------------------------------------
# Story 2.6 — /due-radar/rows Fragment-Endpoint
# ---------------------------------------------------------------------------

def test_rows_fragment_redirects_without_hx_request(due_radar_client):
    """Direkt-Navigation auf /due-radar/rows ohne HX-Request-Header → 302 zu /due-radar."""
    resp = due_radar_client.get("/due-radar/rows")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/due-radar"


def test_rows_fragment_ok_with_hx_request(due_radar_client):
    """Mit HX-Request-Header liefert /due-radar/rows das Fragment (200 + HTML)."""
    resp = due_radar_client.get("/due-radar/rows", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_rows_invalid_type_returns_422(due_radar_client):
    """Ungueltiger ?type-Wert wird von FastAPI/Pydantic als 422 abgewiesen."""
    resp = due_radar_client.get(
        "/due-radar/rows?type=garbage",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 422


def test_rows_invalid_severity_returns_422(due_radar_client):
    """Ungueltiger ?severity-Wert wird von FastAPI/Pydantic als 422 abgewiesen."""
    resp = due_radar_client.get(
        "/due-radar/rows?severity=lt60",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 422


def test_rows_returns_outerhtml_with_tbody_id(due_radar_client):
    """Tranche B: Fragment-Response enthaelt genau ein <tbody id="due-radar-rows">.

    Hintergrund: Story 2.6 hat hx-swap auf outerHTML umgestellt, damit das
    tbody-Element sauber ersetzt wird und keine Verschachtelung entsteht.
    Test pinnt diese Markup-Garantie: kein nested tbody, genau ein Anker.
    """
    resp = due_radar_client.get(
        "/due-radar/rows", headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200
    body = resp.text
    # Genau ein <tbody id="due-radar-rows">
    assert body.count('<tbody id="due-radar-rows"') == 1, (
        "Fragment muss genau einen tbody-Anker fuer outerHTML-Swap haben"
    )
    # Kein nested/duplicated tbody
    assert body.count("<tbody") == 1, (
        "Kein verschachtelter tbody — sonst wuerde HTMX-outerHTML doppelt swappen"
    )


# ---------------------------------------------------------------------------
# Tranche C — Render-Gap (Story 2.5)
# Due-Radar-Eintraege linken via /objects/{id}#versicherungen — der Anchor
# muss als id-Attribut im Detailseiten-DOM existieren, sonst springt der
# Browser nur an den Seitenanfang. (Retro-P1-Patch in Story 2.5 hat
# id="versicherungen" zur <section> ergaenzt.)
# ---------------------------------------------------------------------------


@pytest.fixture
def steckbrief_admin_user_for_anchor(db):
    """Lokaler Admin-User mit objects:view, damit GET /objects/{id} 200 liefert.

    `due_radar_user` reicht hier nicht — der Detail-Render braucht Stammdaten-
    Permissions, die wir hier minimal halten (objects:view + view_confidential
    fuer vollstaendige Section-Liste).
    """
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-anchor-admin",
        email="anchor-admin@dbshome.de",
        name="Anchor Admin",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:view_confidential",
            "registries:view",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def anchor_admin_client(db, steckbrief_admin_user_for_anchor):
    def override_db():
        yield db

    def override_user():
        return steckbrief_admin_user_for_anchor

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c

    app.dependency_overrides.clear()


def test_object_detail_renders_versicherungen_anchor(db, anchor_admin_client):
    """Story 2.5 Retro P1: GET /objects/{id} rendert id="versicherungen" auf der
    Versicherungs-Section, sodass Due-Radar-Links (#versicherungen) tatsaechlich
    scrollen.

    Vor dem Patch hatte die Section nur data-section="versicherungen", kein id-Attribut.
    """
    from app.models import Object

    obj = Object(
        id=uuid.uuid4(),
        short_code="ANC1",
        name="Anchor Testobjekt",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    resp = anchor_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text

    # Pflichtcheck: Anchor existiert als id auf der Versicherungs-Section
    assert 'id="versicherungen"' in body, (
        "Anchor 'versicherungen' fehlt im Detail-DOM — "
        "Due-Radar-Links '/objects/{id}#versicherungen' wuerden nicht scrollen."
    )
