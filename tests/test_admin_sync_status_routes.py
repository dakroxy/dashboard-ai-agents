"""Tests fuer /admin/sync-status (GET + POST)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import AuditLog, User
from app.services.audit import audit
from tests.conftest import _TestSessionLocal, _make_session_cookie, _TEST_CSRF_TOKEN


def _make_sync_admin(db) -> User:
    user = User(
        id=uuid.uuid4(),
        google_sub=f"google-sub-sync-admin-{uuid.uuid4()}",
        email="sync-admin@dbshome.de",
        name="Sync Admin",
        permissions_extra=[
            "sync:admin",
            "users:manage",
            "audit_log:view",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_regular_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        google_sub=f"google-sub-regular-{uuid.uuid4()}",
        email="regular@dbshome.de",
        name="Regular",
        permissions_extra=["documents:upload"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def sync_admin_client(db):
    user = _make_sync_admin(db)

    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def regular_client(db):
    user = _make_regular_user(db)

    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        yield c

    app.dependency_overrides.clear()


def test_sync_status_requires_sync_admin_perm_regular(regular_client):
    resp = regular_client.get("/admin/sync-status")
    assert resp.status_code == 403


def test_sync_status_renders_empty_state(sync_admin_client):
    resp = sync_admin_client.get("/admin/sync-status")
    assert resp.status_code == 200
    assert "Sync-Status" in resp.text
    assert "Noch keine Läufe" in resp.text or "keine Läufe" in resp.text


def test_sync_status_renders_last_run_summary(sync_admin_client, db):
    run_id = str(uuid.uuid4())
    started = audit(
        db,
        None,
        "sync_started",
        entity_type="sync_run",
        entity_id=uuid.UUID(run_id),
        details={
            "job": "steckbrief_impower_mirror",
            "run_id": run_id,
            "started_at": "2026-04-22T02:30:00+00:00",
        },
        user_email="system",
    )
    finished = audit(
        db,
        None,
        "sync_finished",
        entity_type="sync_run",
        entity_id=uuid.UUID(run_id),
        details={
            "job": "steckbrief_impower_mirror",
            "run_id": run_id,
            "objects_ok": 49,
            "objects_failed": 1,
            "fields_updated": 120,
        },
        user_email="system",
    )
    db.commit()

    resp = sync_admin_client.get("/admin/sync-status")
    assert resp.status_code == 200
    assert "49" in resp.text
    assert "120" in resp.text


def test_sync_status_renders_failed_objects_table(sync_admin_client, db):
    run_id = str(uuid.uuid4())
    audit(
        db,
        None,
        "sync_started",
        entity_type="sync_run",
        entity_id=uuid.UUID(run_id),
        details={"job": "steckbrief_impower_mirror", "run_id": run_id},
        user_email="system",
    )
    audit(
        db,
        None,
        "sync_failed",
        entity_type="object",
        entity_id=uuid.UUID(run_id),
        details={
            "job": "steckbrief_impower_mirror",
            "run_id": run_id,
            "item_id": "12345",
            "phase": "cluster_6",
            "error": "HTTP 503 Gateway",
        },
        user_email="system",
    )
    audit(
        db,
        None,
        "sync_finished",
        entity_type="sync_run",
        entity_id=uuid.UUID(run_id),
        details={
            "job": "steckbrief_impower_mirror",
            "run_id": run_id,
            "objects_ok": 49,
            "objects_failed": 1,
        },
        user_email="system",
    )
    db.commit()

    resp = sync_admin_client.get("/admin/sync-status")
    assert resp.status_code == 200
    assert "12345" in resp.text
    assert "Gateway" in resp.text or "503" in resp.text


def test_trigger_mirror_run_redirects_303(sync_admin_client, monkeypatch):
    # background_tasks.add_task ruft run_impower_mirror spaeter — wir mocken
    # die Funktion hier weg, damit kein echter Lauf passiert.
    calls = []

    async def fake_mirror(*args, **kwargs):
        calls.append(1)

    monkeypatch.setattr(
        "app.routers.admin.run_impower_mirror", fake_mirror
    )
    resp = sync_admin_client.post("/admin/sync-status/run")
    assert resp.status_code == 303
    assert "/admin/sync-status" in resp.headers["location"]


def test_trigger_mirror_run_hx_request_returns_hx_redirect_header(
    sync_admin_client, monkeypatch
):
    """HTMX-idiomatisch: bei `HX-Request: true` wird statt 303 ein 200
    mit `HX-Redirect`-Header geliefert — so swappt HTMX nicht den aktuellen
    Content, sondern laedt die Ziel-URL neu."""
    async def fake_mirror(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.routers.admin.run_impower_mirror", fake_mirror
    )
    resp = sync_admin_client.post(
        "/admin/sync-status/run", headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200
    assert "/admin/sync-status" in resp.headers.get("HX-Redirect", "")


def test_sync_status_anonymous_access_redirects_to_login(db):
    """AC9: Anon-Zugriff auf /admin/sync-status liefert 302 nach /auth/google/login.

    get_current_user wirft HTTPException(302) bei fehlender Session — das
    muss unverfaelscht durchkommen (kein dependency_override auf
    get_current_user).
    """
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    # KEIN override fuer get_current_user/get_optional_user — damit laeuft
    # der Auth-Decorator so, wie er in Prod laeuft.
    try:
        with TestClient(app, raise_server_exceptions=False, follow_redirects=False) as c:
            c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            resp = c.get("/admin/sync-status")
            assert resp.status_code == 302
            assert "/auth/google/login" in resp.headers.get("location", "")
    finally:
        app.dependency_overrides.clear()


def test_admin_home_shows_sync_status_link_for_admin(sync_admin_client):
    resp = sync_admin_client.get("/admin")
    assert resp.status_code == 200
    assert "/admin/sync-status" in resp.text
    assert "Sync-Status" in resp.text


# ---------------------------------------------------------------------------
# Story 4.3: Zwei-Job-Layout + Facilioo-Alert + Job-Name-Routing
# ---------------------------------------------------------------------------

def test_sync_status_shows_two_job_blocks(sync_admin_client):
    """AC7: Seite rendert sowohl Impower- als auch Facilioo-Job-Block."""
    resp = sync_admin_client.get("/admin/sync-status")
    assert resp.status_code == 200
    assert "Impower Nightly Mirror" in resp.text
    assert "Facilioo Ticket Mirror" in resp.text
    # Jeder Job hat seinen eigenen "Jetzt ausführen"-Button
    assert resp.text.count("Jetzt ausführen") >= 2
    # Hidden-Inputs fuer job_name
    assert "steckbrief_impower_mirror" in resp.text
    assert "facilioo_ticket_mirror" in resp.text


def test_facilioo_alert_banner_renders_on_error_budget(sync_admin_client, db):
    """AC5+AC7: Error-Budget-Alert fuer Facilioo → rotes Banner auf der Seite."""
    _JOB = "facilioo_ticket_mirror"
    audit(
        db, None, "sync_failed",
        entity_type="sync_run", entity_id=None,
        details={
            "job": _JOB,
            "run_id": str(uuid.uuid4()),
            "alert": "error_budget_exceeded",
            "failure_rate": 0.20,
            "total_runs": 15,
            "failed_runs": 3,
            "window_hours": 24,
            "current_run_id": str(uuid.uuid4()),
        },
        user_email="system",
    )
    db.commit()

    resp = sync_admin_client.get("/admin/sync-status")
    assert resp.status_code == 200
    assert "Error-Budget" in resp.text
    # Spezifischer Match (statt brittle bg-red-100): das Banner traegt ein
    # data-Attribute mit dem Job-Namen, das nur am Alert-Banner erscheint.
    assert 'data-error-budget-alert="facilioo_ticket_mirror"' in resp.text


def test_manual_trigger_routes_to_facilioo_job_when_job_name_param_set(
    sync_admin_client, monkeypatch
):
    """AC7: POST mit job_name=facilioo_ticket_mirror → Facilioo-Mirror wird gestartet."""
    async def fake_facilioo(*args, **kwargs):
        pass

    monkeypatch.setattr("app.routers.admin.run_facilioo_mirror", fake_facilioo)
    resp = sync_admin_client.post(
        "/admin/sync-status/run",
        data={"job_name": "facilioo_ticket_mirror"},
    )
    assert resp.status_code == 303
    assert "/admin/sync-status" in resp.headers["location"]


def test_manual_trigger_unknown_job_name_returns_400(sync_admin_client):
    """AC7: Unbekannter job_name → 400 Bad Request."""
    resp = sync_admin_client.post(
        "/admin/sync-status/run",
        data={"job_name": "totally_unknown_job_xyz"},
    )
    assert resp.status_code == 400


def test_manual_trigger_default_job_name_uses_impower(sync_admin_client, monkeypatch):
    """AC7: POST ohne job_name → Default steckbrief_impower_mirror wird gestartet."""
    async def fake_impower(*args, **kwargs):
        pass

    monkeypatch.setattr("app.routers.admin.run_impower_mirror", fake_impower)
    resp = sync_admin_client.post("/admin/sync-status/run")
    assert resp.status_code == 303
    assert "triggered=1" in resp.headers["location"]
