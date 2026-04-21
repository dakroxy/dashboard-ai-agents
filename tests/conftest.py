"""Pytest fixtures and DB patching.

Must run from the project root:  pytest
The test DB is SQLite in-memory (StaticPool so all sessions share one connection).
"""
from __future__ import annotations

import os
import uuid

# Set env vars before any app import so pydantic-settings picks them up.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use")
os.environ.setdefault("POSTGRES_PASSWORD", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("IMPOWER_BEARER_TOKEN", "")

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
from app.models import AuditLog, ChatMessage, Document, Extraction, User, Workflow  # noqa: F401, E402
from app.db import Base  # noqa: E402

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
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-test-123",
        email="test@dbshome.de",
        name="Test User",
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
        yield c

    app.dependency_overrides.clear()
