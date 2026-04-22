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
from tests.conftest import _TestSessionLocal


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
        yield c

    app.dependency_overrides.clear()


def test_sync_status_requires_sync_admin_perm_regular(regular_client):
    resp = regular_client.get("/admin/sync-status")
    assert resp.status_code == 403


def test_sync_status_renders_empty_state(sync_admin_client):
    resp = sync_admin_client.get("/admin/sync-status")
    assert resp.status_code == 200
    assert "Sync-Status" in resp.text
    assert "Noch keine Laeufe" in resp.text or "keine Laeufe" in resp.text


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


def test_admin_home_shows_sync_status_link_for_admin(sync_admin_client):
    resp = sync_admin_client.get("/admin")
    assert resp.status_code == 200
    assert "/admin/sync-status" in resp.text
    assert "Sync-Status" in resp.text
