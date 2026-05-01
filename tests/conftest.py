"""Pytest fixtures and DB patching.

Must run from the project root:  pytest
The test DB is SQLite in-memory (StaticPool so all sessions share one connection).
"""
from __future__ import annotations

import os
import time
import uuid

# Story 4.0 / AC8 — Test-Container-Timezone auf Europe/Berlin pinnen, BEVOR
# irgendwo date.today() oder datetime.now() bei Modul-Import laeuft. Damit
# liefert date.today() in Tests dasselbe Datum wie today_local() im Service —
# Tagesrand-Flake durch UTC-vs-Berlin-Drift ausgeschlossen.
os.environ["TZ"] = "Europe/Berlin"
time.tzset()

# Set env vars before any app import so pydantic-settings picks them up.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use")
os.environ.setdefault("POSTGRES_PASSWORD", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("IMPOWER_BEARER_TOKEN", "")
# Default: im Testsuite-Lauf kein Nightly-Scheduler-Task anlegen. Tests, die
# den Scheduler explizit verifizieren, setzen settings.impower_mirror_enabled
# per monkeypatch auf True, bevor der Lifespan-Enter laeuft.
os.environ.setdefault("IMPOWER_MIRROR_ENABLED", "false")
os.environ.setdefault("FACILIOO_MIRROR_ENABLED", "false")

import json as _json
from base64 import b64encode as _b64encode

import itsdangerous as _itsdangerous
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Stabiles Test-CSRF-Token — in allen Fixtures identisch, damit Middleware-Check besteht.
_TEST_CSRF_TOKEN = "csrf-test-token-dbshome-dev"


def _make_session_cookie(data: dict) -> str:
    """Erzeugt einen signierten Starlette-Session-Cookie fuer Tests.

    Benutzt dieselbe Signing-Logik wie Starletttes SessionMiddleware
    (itsdangerous.TimestampSigner + b64encode(json)).
    """
    secret = os.environ.get("SECRET_KEY", "test-secret-key-do-not-use")
    signer = _itsdangerous.TimestampSigner(secret)
    payload = _b64encode(_json.dumps(data).encode())
    return signer.sign(payload).decode()

# Teach SQLite how to render Postgres-specific column types used in the models.
# This only affects DDL (CREATE TABLE) — DML type processors are inherited from
# the base JSON/UUID types and work correctly on SQLite.
SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "TEXT"  # type: ignore[attr-defined]
SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"  # type: ignore[attr-defined]

# --- Patch DB before any app router is imported ---
import app.db as _db_module  # noqa: E402

_TEST_ENGINE = sa.create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(
    bind=_TEST_ENGINE,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
_db_module.engine = _TEST_ENGINE
_db_module.SessionLocal = _TestSessionLocal

# Import models so Base.metadata is populated, then create all tables.
# Transitiver Import ueber app.models/__init__.py — alle neuen Submodule
# (Steckbrief-Core, Governance) werden automatisch auf Base.metadata registriert.
import app.models  # noqa: F401, E402
from app.models import (  # noqa: F401, E402
    AuditLog,
    ChatMessage,
    Document,
    Extraction,
    Object,
    ResourceAccess,
    Role,
    User,
    Workflow,
)
from app.db import Base  # noqa: E402
from app.permissions import RESOURCE_TYPE_WORKFLOW  # noqa: E402

Base.metadata.create_all(_TEST_ENGINE)

# Patch the SessionLocal references that routers imported directly.
import app.main as _main_module  # noqa: E402
import app.routers.documents as _docs_router  # noqa: E402

_main_module.SessionLocal = _TestSessionLocal
_docs_router.SessionLocal = _TestSessionLocal

# Now it's safe to import the app and its dependencies.
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import get_current_user, get_optional_user  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# DB reset between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_db():
    yield
    session = _TestSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_user(db):
    # Standard-Default-Perms der Rolle `user` (vgl. app/permissions.py
    # DEFAULT_ROLE_PERMISSIONS["user"]). Direkt ueber `permissions_extra`
    # gesetzt, damit wir in Tests ohne Role-Seeding auskommen. Tests, die
    # explizit eine andere Permission-Konstellation brauchen, bauen sich
    # ihren User selbst (siehe test_permissions.py).
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-test-123",
        email="test@dbshome.de",
        name="Test User",
        permissions_extra=[
            "documents:upload",
            "documents:view_all",
            "documents:approve",
            "workflows:view",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_client(db, test_user):
    """TestClient with an authenticated user via dependency override."""
    def override_db():
        yield db

    def override_user():
        return test_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        # CSRF-Session-Cookie + Header setzen, damit Middleware-Check besteht.
        c.cookies.set(
            "session",
            _make_session_cookie({"user_id": str(test_user.id), "csrf_token": _TEST_CSRF_TOKEN}),
        )
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN

        # Lifespan hat die Default-Workflows geseedet; der test_user hat aber
        # keine Rolle, ueber die Resource-Access auf diese Workflows vererbt
        # wuerde. Um die bestehenden Router-Tests (Upload/Approve) nicht bei
        # `can_access_workflow` zu blocken, geben wir dem test_user direkt
        # User-Level-Zugriff auf alle geseedeten Workflows.
        for wf in db.query(Workflow).all():
            exists = (
                db.query(ResourceAccess)
                .filter(
                    ResourceAccess.user_id == test_user.id,
                    ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
                    ResourceAccess.resource_id == wf.id,
                )
                .first()
            )
            if exists is None:
                db.add(
                    ResourceAccess(
                        id=uuid.uuid4(),
                        user_id=test_user.id,
                        resource_type=RESOURCE_TYPE_WORKFLOW,
                        resource_id=wf.id,
                        mode="allow",
                    )
                )
        db.commit()
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def test_object(db):
    """Minimal-Object fuer Write-Gate-Tests."""
    obj = Object(
        id=uuid.uuid4(),
        short_code="TST1",
        name="Test-Objekt",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@pytest.fixture
def steckbrief_admin_client(db):
    """TestClient mit einem User, der alle Steckbrief-Admin-Permissions hat
    (objects:view/edit/approve_ki + audit_log:view). Fuer Folge-Stories 1.3ff
    schon vorbereitet."""
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-admin-steckbrief",
        email="steckbrief-admin@dbshome.de",
        name="Steckbrief Admin",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "objects:view_confidential",
            "registries:view",
            "registries:edit",
            "audit_log:view",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set(
            "session",
            _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}),
        )
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def anon_client():
    """TestClient without any authenticated user."""
    def override_db():
        session = _TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    def override_optional_user():
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_optional_user] = override_optional_user

    with TestClient(app, raise_server_exceptions=False, follow_redirects=False) as c:
        # CSRF-Token setzen, damit anon-POST-Tests nicht schon an CSRF-403 scheitern.
        # Auth-Fehler (302 redirect oder 403 forbidden) kommen danach aus der Route.
        c.cookies.set(
            "session",
            _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}),
        )
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        yield c

    app.dependency_overrides.clear()
