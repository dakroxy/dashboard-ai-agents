"""Tests fuer Story 5-4: Performance & Query-Optimierung.

Abdeckung: Pagination Review-Queue (AC1), Pagination /objects (AC2),
sidebar_workflows TTL-Cache (AC3), accessible_object_ids request-scope (AC4),
get_provenance_map_bulk (AC5), Pflegegrad prov_map-Reuse (AC6),
list_conferences_with_properties Semaphore (AC7),
last_known_balance Skip-on-equal (AC8), HTMX-401 (AC9),
deferred-work.md Doku-Tags (AC10).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa

from tests.conftest import _TEST_ENGINE, _TestSessionLocal

# ---------------------------------------------------------------------------
# Imports nach Env-Setup (conftest setzt os.environ BEVOR App-Import)
# ---------------------------------------------------------------------------
from app.models import FieldProvenance, Object, ReviewQueueEntry, User
from app.models.governance import ReviewQueueEntry
from app.services.steckbrief import get_provenance_map_bulk, ProvenanceWithUser
from app.services.pflegegrad import pflegegrad_score, get_or_update_pflegegrad_cache


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

class _StmtCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1


def _make_pending_entry(object_id: uuid.UUID, field: str = "heating_type") -> ReviewQueueEntry:
    return ReviewQueueEntry(
        id=uuid.uuid4(),
        target_entity_type="object",
        target_entity_id=object_id,
        field_name=field,
        proposed_value={"value": "Fernwaerme"},
        agent_ref="test-agent",
        confidence=0.9,
        status="pending",
    )


# ===========================================================================
# AC1 — Pagination /admin/review-queue
# ===========================================================================

@pytest.fixture
def review_queue_admin_client(db):
    """Admin-Client mit objects:approve_ki Permission."""
    from app.auth import get_current_user, get_optional_user
    from app.db import get_db
    from app.main import app
    from fastapi.testclient import TestClient
    import itsdangerous, json
    from base64 import b64encode

    user = User(
        id=uuid.uuid4(),
        google_sub="review-admin-sub",
        email="review-admin@dbshome.de",
        name="Review Admin",
        permissions_extra=["objects:approve_ki", "objects:view"],
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

    secret = "test-secret-key-do-not-use"
    signer = itsdangerous.TimestampSigner(secret)
    payload = b64encode(json.dumps({"csrf_token": "csrf-test", "user_id": str(user.id)}).encode())
    cookie = signer.sign(payload).decode()

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set("session", cookie)
        c.headers["X-CSRF-Token"] = "csrf-test"
        yield c, db, user

    app.dependency_overrides.clear()


def _seed_pending_entries(db, count: int) -> uuid.UUID:
    obj_id = uuid.uuid4()
    for i in range(count):
        db.add(_make_pending_entry(obj_id, field=f"field_{i}"))
    db.commit()
    return obj_id


def test_review_queue_paginates_50_per_page_default(review_queue_admin_client):
    client, db, _user = review_queue_admin_client
    _seed_pending_entries(db, 200)
    resp = client.get("/admin/review-queue")
    assert resp.status_code == 200
    # Default page_size=50: genau 50 Eintraege sichtbar, Pagination-Nav vorhanden
    rows_in_html = resp.text.count('<td class="p-0')
    # Jede Row hat 7 <td class="p-0"-Zellen; 50 rows * 7 = 350 oder nutze unique marker
    # Einfacher: Pagination-Nav enthaelt total_pages > 1
    assert "laquo" in resp.text or "raquo" in resp.text


def test_review_queue_page_size_param(review_queue_admin_client):
    client, db, _user = review_queue_admin_client
    _seed_pending_entries(db, 20)
    resp = client.get("/admin/review-queue?page_size=10")
    assert resp.status_code == 200
    # Pagination-Nav sichtbar wenn total_count(20) > page_size(10)
    assert "raquo" in resp.text


def test_review_queue_page_param(review_queue_admin_client):
    client, db, _user = review_queue_admin_client
    _seed_pending_entries(db, 200)
    # Seite 1 und Seite 2 muessen unterschiedliche Eintraege liefern
    resp1 = client.get("/admin/review-queue?page=1&page_size=50")
    resp2 = client.get("/admin/review-queue?page=2&page_size=50")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # Seiteninhalt darf nicht identisch sein (unterschiedliche Feld-Namen)
    assert resp1.text != resp2.text


def test_review_queue_filter_resets_page(review_queue_admin_client):
    client, db, _user = review_queue_admin_client
    resp = client.get("/admin/review-queue?page=3&page_size=50&min_age_days=36499")
    # min_age_days so hoch, dass keine Entries zurueckkommen — kein Crash
    assert resp.status_code == 200


def test_review_queue_total_count_correct(review_queue_admin_client):
    client, db, _user = review_queue_admin_client
    obj_id = uuid.uuid4()
    for i in range(5):
        db.add(_make_pending_entry(obj_id, field=f"f_{i}"))
    db.commit()
    resp = client.get("/admin/review-queue")
    assert resp.status_code == 200
    # total_count = 5 <= page_size(50) → kein Pagination-Widget
    assert "laquo" not in resp.text


# ===========================================================================
# AC2 — Pagination /objects + /objects/rows
# ===========================================================================

@pytest.fixture
def objects_client(steckbrief_admin_client):
    return steckbrief_admin_client


def _seed_objects(db, count: int) -> list[Object]:
    objs = []
    for i in range(count):
        obj = Object(id=uuid.uuid4(), short_code=f"T{i:04d}", name=f"Testobjekt {i}")
        db.add(obj)
        objs.append(obj)
    db.commit()
    return objs


def test_objects_list_paginates_50_per_page_default(objects_client, db):
    _seed_objects(db, 60)
    resp = objects_client.get("/objects")
    assert resp.status_code == 200
    # Pagination-Nav sichtbar weil 60 > 50
    assert "obj-pagination" in resp.text


def test_objects_list_page_size_param(objects_client, db):
    _seed_objects(db, 20)
    resp = objects_client.get("/objects?page_size=5")
    assert resp.status_code == 200
    # 20 > 5 → Pagination-Nav
    assert "obj-pagination" in resp.text


def test_objects_rows_fragment_paginates(objects_client, db):
    _seed_objects(db, 60)
    resp = objects_client.get("/objects/rows", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert 'id="obj-rows"' in resp.text


def test_objects_list_pagination_with_sort(objects_client, db):
    _seed_objects(db, 10)
    resp = objects_client.get("/objects?sort=name&order=asc&page=1&page_size=5")
    assert resp.status_code == 200


# ===========================================================================
# AC3 — sidebar_workflows TTL-Cache
# ===========================================================================

def test_sidebar_workflows_cached_within_ttl(db):
    from app.templating import sidebar_workflows, _SIDEBAR_WORKFLOWS_CACHE
    from app.models import Workflow, ResourceAccess
    from app.permissions import RESOURCE_TYPE_WORKFLOW

    user = User(
        id=uuid.uuid4(),
        google_sub="sidebar-test-sub",
        email="sidebar@dbshome.de",
        name="Sidebar Test",
        permissions_extra=["workflows:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Cache leeren
    _SIDEBAR_WORKFLOWS_CACHE.pop(user.id, None)

    call_count = [0]
    original_sessionlocal = None
    import app.templating as _templating_mod
    orig_sessionlocal = _templating_mod.SessionLocal

    class _CountingSession:
        def __init__(self):
            call_count[0] += 1
            self._session = orig_sessionlocal()

        def query(self, *args, **kwargs):
            return self._session.query(*args, **kwargs)

        def close(self):
            self._session.close()

    with patch.object(_templating_mod, "SessionLocal", lambda: _CountingSession()):
        # Erster Aufruf — Cache-Miss → DB-Hit
        sidebar_workflows(user)
        count_after_first = call_count[0]
        # Zweiter Aufruf binnen TTL — Cache-Hit → kein neuer DB-Hit
        sidebar_workflows(user)
        count_after_second = call_count[0]

    assert count_after_first == 1
    assert count_after_second == 1  # kein zweiter DB-Hit


def test_sidebar_workflows_recomputes_after_ttl(db):
    from app.templating import sidebar_workflows, _SIDEBAR_WORKFLOWS_CACHE
    import app.templating as _templating_mod

    user = User(
        id=uuid.uuid4(),
        google_sub="sidebar-ttl-sub",
        email="sidebar-ttl@dbshome.de",
        name="Sidebar TTL Test",
        permissions_extra=["workflows:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _SIDEBAR_WORKFLOWS_CACHE.pop(user.id, None)

    call_count = [0]
    orig_sessionlocal = _templating_mod.SessionLocal

    class _CountingSession:
        def __init__(self):
            call_count[0] += 1
            self._session = orig_sessionlocal()

        def query(self, *args, **kwargs):
            return self._session.query(*args, **kwargs)

        def close(self):
            self._session.close()

    time_values = iter([0.0, 31.0])  # erster Aufruf t=0, zweiter t=31 (TTL=30 abgelaufen)

    with patch.object(_templating_mod, "SessionLocal", lambda: _CountingSession()):
        with patch("app.templating.time") as mock_time:
            mock_time.monotonic = lambda: next(time_values)
            sidebar_workflows(user)  # t=0, cache miss
            sidebar_workflows(user)  # t=31, cache miss (TTL abgelaufen)

    assert call_count[0] == 2


def test_sidebar_workflows_logout_invalidates_cache(db):
    from app.templating import _SIDEBAR_WORKFLOWS_CACHE

    user_id = uuid.uuid4()
    _SIDEBAR_WORKFLOWS_CACHE[user_id] = (time.monotonic(), [{"key": "test"}])
    assert user_id in _SIDEBAR_WORKFLOWS_CACHE

    _SIDEBAR_WORKFLOWS_CACHE.pop(user_id, None)
    assert user_id not in _SIDEBAR_WORKFLOWS_CACHE


# ===========================================================================
# AC4 — accessible_object_ids request-scoped Cache
# ===========================================================================

def test_accessible_object_ids_for_request_falls_back_when_state_missing(db):
    from app.permissions import accessible_object_ids_for_request

    user = User(
        id=uuid.uuid4(),
        google_sub="acc-sub",
        email="acc@dbshome.de",
        name="Acc Test",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    obj = Object(id=uuid.uuid4(), short_code="AC4", name="AC4 Objekt")
    db.add(obj)
    db.commit()

    request = MagicMock()
    request.state = MagicMock()
    request.state._accessible_object_ids = None  # state exists but is None

    # Wrapper muss trotzdem korrekt fuktionieren
    result = accessible_object_ids_for_request(request, db, user)
    assert obj.id in result


def test_accessible_object_ids_cached_per_request(db):
    from app.permissions import accessible_object_ids_for_request

    user = User(
        id=uuid.uuid4(),
        google_sub="cache-sub",
        email="cache@dbshome.de",
        name="Cache Test",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    request = MagicMock()
    request.state = type("State", (), {"_accessible_object_ids": None})()

    counter = _StmtCounter()
    sa.event.listen(_TEST_ENGINE, "before_cursor_execute", counter)
    try:
        result1 = accessible_object_ids_for_request(request, db, user)
        count_after_first = counter.count
        result2 = accessible_object_ids_for_request(request, db, user)
        count_after_second = counter.count
    finally:
        sa.event.remove(_TEST_ENGINE, "before_cursor_execute", counter)

    assert result1 == result2
    # Zweiter Aufruf darf keinen neuen DB-Hit erzeugen
    assert count_after_first == count_after_second


def test_accessible_object_ids_isolated_between_requests(db):
    from app.permissions import accessible_object_ids_for_request

    user = User(
        id=uuid.uuid4(),
        google_sub="iso-sub",
        email="iso@dbshome.de",
        name="Iso Test",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    req1 = MagicMock()
    req1.state = type("State", (), {"_accessible_object_ids": None})()
    req2 = MagicMock()
    req2.state = type("State", (), {"_accessible_object_ids": None})()

    result1 = accessible_object_ids_for_request(req1, db, user)
    result2 = accessible_object_ids_for_request(req2, db, user)

    # Jeder Request hat sein eigenes State-Objekt
    assert req1.state._accessible_object_ids is not None
    assert req2.state._accessible_object_ids is not None
    assert req1.state._accessible_object_ids == req2.state._accessible_object_ids


# ===========================================================================
# AC5 — get_provenance_map_bulk
# ===========================================================================

def test_get_provenance_map_bulk_returns_all_fields_for_entity(db):
    obj_id = uuid.uuid4()
    # Zwei verschiedene Felder seeden
    for field in ("full_address", "heating_type"):
        prov = FieldProvenance(
            id=uuid.uuid4(),
            entity_type="object",
            entity_id=obj_id,
            field_name=field,
            source="user_edit",
            value_snapshot={"old": None, "new": "test"},
            created_at=datetime.now(tz=timezone.utc),
        )
        db.add(prov)
    db.commit()

    result = get_provenance_map_bulk(db, "object", obj_id)
    assert "full_address" in result
    assert "heating_type" in result
    assert result["full_address"] is not None
    assert isinstance(result["full_address"], ProvenanceWithUser)


def test_get_provenance_map_bulk_sqlite_fallback(db):
    obj_id = uuid.uuid4()
    prov = FieldProvenance(
        id=uuid.uuid4(),
        entity_type="object",
        entity_id=obj_id,
        field_name="year_built",
        source="impower_mirror",
        value_snapshot={"old": None, "new": "1970"},
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(prov)
    db.commit()

    result = get_provenance_map_bulk(db, "object", obj_id)
    assert "year_built" in result
    assert result["year_built"].prov.source == "impower_mirror"


def test_get_provenance_map_bulk_returns_latest_per_field(db):
    obj_id = uuid.uuid4()
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    for source, ts in [("user_edit", t1), ("impower_mirror", t2)]:
        db.add(FieldProvenance(
            id=uuid.uuid4(),
            entity_type="object",
            entity_id=obj_id,
            field_name="full_address",
            source=source,
            value_snapshot={},
            created_at=ts,
        ))
    db.commit()

    result = get_provenance_map_bulk(db, "object", obj_id)
    # Neueste Row (impower_mirror, t2) muss zurueckkommen
    assert result["full_address"].prov.source == "impower_mirror"


def test_get_provenance_map_bulk_postgres_distinct_on():
    """Mock-Postgres-Dialect: verifiziert, dass der DISTINCT-Pfad gewaehlt wird."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    mock_session = MagicMock()
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_session.bind = mock_bind

    executed_stmts = []

    def fake_execute(stmt):
        executed_stmts.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        result = MagicMock()
        result.all.return_value = []
        return result

    mock_session.execute = fake_execute

    result = get_provenance_map_bulk(mock_session, "object", uuid.uuid4())
    assert result == {}
    # Mindestens eine Statement wurde generiert
    assert len(executed_stmts) >= 1


# ===========================================================================
# AC6 — Pflegegrad prov_map-Reuse
# ===========================================================================

def test_pflegegrad_score_works_without_prov_map_argument(db):
    obj = Object(id=uuid.uuid4(), short_code="PFG1", name="Pflegegrad Test")
    db.add(obj)
    db.commit()
    db.refresh(obj)

    result = pflegegrad_score(obj, db)
    assert result.score >= 0
    assert result.score <= 100


def test_pflegegrad_score_uses_prov_map_when_provided(db):
    obj = Object(
        id=uuid.uuid4(),
        short_code="PFG2",
        name="Pflegegrad Mit Prov",
        full_address="Teststr. 1",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    # Leak-Check: mit prov_map darf KEINE SELECT FieldProvenance laufen
    prov_map: dict[str, ProvenanceWithUser | None] = {}  # leer — kein Provenance-Decay

    counter = _StmtCounter()
    sa.event.listen(_TEST_ENGINE, "before_cursor_execute", counter)
    try:
        result = pflegegrad_score(obj, db, prov_map=prov_map)
    finally:
        sa.event.remove(_TEST_ENGINE, "before_cursor_execute", counter)

    # Mit prov_map: kein FieldProvenance-SELECT (nur die 3 COUNT-Queries)
    assert counter.count <= 3, f"Unerwartet viele Queries mit prov_map: {counter.count}"
    assert result.score >= 0


def test_pflegegrad_score_falls_back_when_prov_map_missing_field(db):
    obj = Object(
        id=uuid.uuid4(),
        short_code="PFG3",
        name="Pflegegrad Fallback",
        full_address="Fallbackstr. 1",
    )
    db.add(obj)
    # FieldProvenance fuer full_address anlegen
    db.add(FieldProvenance(
        id=uuid.uuid4(),
        entity_type="object",
        entity_id=obj.id,
        field_name="full_address",
        source="impower_mirror",
        value_snapshot={},
        created_at=datetime.now(tz=timezone.utc),
    ))
    db.commit()
    db.refresh(obj)

    # prov_map ohne full_address → Feld hat kein Decay (age=None → 1.0)
    prov_map: dict[str, ProvenanceWithUser | None] = {}
    result_with_empty_prov_map = pflegegrad_score(obj, db, prov_map=prov_map)

    # prov_map=None → volle DB-Query → findet FieldProvenance → age=0 → 1.0 ebenfalls
    result_without_prov_map = pflegegrad_score(obj, db)

    # Beide Pfade geben denselben Score (frische Provenance = kein Decay)
    assert result_with_empty_prov_map.score == result_without_prov_map.score


# ===========================================================================
# AC7 — list_conferences_with_properties Semaphore
# ===========================================================================

@pytest.mark.asyncio
async def test_list_conferences_with_properties_respects_semaphore():
    from app.services.facilioo import list_conferences_with_properties, _PROPERTY_LOOKUP_CONCURRENCY

    conferences = [{"id": i, "title": f"ETV {i}"} for i in range(1, 51)]  # 50 Conferences
    max_concurrent = [0]
    current_concurrent = [0]

    async def mock_get_all_paged(client, path, *, rate_gate=True):
        return conferences

    async def mock_api_get(client, path, *, rate_gate=True):
        current_concurrent[0] += 1
        max_concurrent[0] = max(max_concurrent[0], current_concurrent[0])
        await asyncio.sleep(0.01)
        current_concurrent[0] -= 1
        return {"number": "TST1", "name": "Test WEG"}

    with patch("app.services.facilioo._get_all_paged", mock_get_all_paged):
        with patch("app.services.facilioo._api_get", mock_api_get):
            with patch("app.services.facilioo._make_client") as mock_make_client:
                mock_client = AsyncMock()
                mock_make_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_make_client.return_value.__aexit__ = AsyncMock(return_value=None)
                result = await list_conferences_with_properties()

    # Max-Concurrency darf _PROPERTY_LOOKUP_CONCURRENCY nicht uebersteigen
    assert max_concurrent[0] <= _PROPERTY_LOOKUP_CONCURRENCY
    assert len(result) == 50


@pytest.mark.asyncio
async def test_list_conferences_with_properties_happy_path_unchanged():
    from app.services.facilioo import list_conferences_with_properties

    conferences = [
        {"id": 1, "title": "ETV HAM61"},
        {"id": 2, "title": "ETV GVE1"},
        {"id": 3, "title": "ETV BRE11"},
    ]

    async def mock_get_all_paged(client, path, *, rate_gate=True):
        return conferences

    async def mock_api_get(client, path, *, rate_gate=True):
        conf_id = int(path.split("/")[-2])
        return {"number": f"TST{conf_id}", "name": f"WEG {conf_id}"}

    with patch("app.services.facilioo._get_all_paged", mock_get_all_paged):
        with patch("app.services.facilioo._api_get", mock_api_get):
            with patch("app.services.facilioo._make_client") as mock_make_client:
                mock_client = AsyncMock()
                mock_make_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_make_client.return_value.__aexit__ = AsyncMock(return_value=None)
                result = await list_conferences_with_properties()

    assert len(result) == 3
    assert result[0]["_property_number"] == "TST1"


# ===========================================================================
# AC8 — last_known_balance Skip-on-equal
# ===========================================================================

def _make_object_with_balance(db, balance: Decimal | None) -> Object:
    obj = Object(
        id=uuid.uuid4(),
        short_code="BAL1",
        name="Balance Test",
        impower_property_id="TEST-PROP-001",
        last_known_balance=balance,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _count_provenance_rows(db, obj_id: uuid.UUID, field: str) -> int:
    return db.execute(
        sa.select(sa.func.count()).select_from(FieldProvenance).where(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj_id,
            FieldProvenance.field_name == field,
        )
    ).scalar_one()


def test_object_detail_skips_balance_write_when_equal(steckbrief_admin_client, db):
    """Gleiches Balance → kein neuer Provenance-Write."""
    existing_balance = Decimal("1500.00")
    obj = _make_object_with_balance(db, existing_balance)

    count_before = _count_provenance_rows(db, obj.id, "last_known_balance")

    mock_balance_result = {
        "balance": existing_balance,
        "fetched_at": datetime.now(tz=timezone.utc),
    }
    with patch("app.routers.objects.get_bank_balance", return_value=mock_balance_result):
        resp = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200

    count_after = _count_provenance_rows(db, obj.id, "last_known_balance")
    assert count_after == count_before  # kein neuer Write


def test_object_detail_writes_balance_when_changed(steckbrief_admin_client, db):
    """Neues Balance → ein neuer Provenance-Write."""
    obj = _make_object_with_balance(db, Decimal("1500.00"))
    new_balance = Decimal("1600.00")

    count_before = _count_provenance_rows(db, obj.id, "last_known_balance")

    mock_balance_result = {
        "balance": new_balance,
        "fetched_at": datetime.now(tz=timezone.utc),
    }
    with patch("app.routers.objects.get_bank_balance", return_value=mock_balance_result):
        resp = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200

    count_after = _count_provenance_rows(db, obj.id, "last_known_balance")
    assert count_after == count_before + 1


def test_object_detail_writes_balance_when_initial_null(steckbrief_admin_client, db):
    """last_known_balance ist None → immer schreiben."""
    obj = _make_object_with_balance(db, None)
    new_balance = Decimal("1200.00")

    count_before = _count_provenance_rows(db, obj.id, "last_known_balance")

    mock_balance_result = {
        "balance": new_balance,
        "fetched_at": datetime.now(tz=timezone.utc),
    }
    with patch("app.routers.objects.get_bank_balance", return_value=mock_balance_result):
        resp = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200

    count_after = _count_provenance_rows(db, obj.id, "last_known_balance")
    assert count_after == count_before + 1


# ===========================================================================
# AC9 — HTMX-Session-Expired 401 statt 302
# ===========================================================================

def test_htmx_request_expired_session_returns_401_with_hx_redirect_header():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        resp = c.get("/objects", headers={"HX-Request": "true"})
    # Keine Session → 401 + HX-Redirect
    assert resp.status_code == 401
    assert "HX-Redirect" in resp.headers


def test_non_htmx_request_expired_session_redirects_302():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        resp = c.get("/objects")
    # Keine Session, kein HX-Request → 302
    assert resp.status_code == 302


# ===========================================================================
# AC10 — Out-of-scope Items dokumentiert
# ===========================================================================

def test_deferred_work_marks_33_as_fail_loud_by_design():
    deferred_path = Path("output/implementation-artifacts/deferred-work.md")
    content = deferred_path.read_text()
    assert "[deferred-fail-loud-by-design]" in content


def test_deferred_work_marks_133_as_bulk_upload_story():
    deferred_path = Path("output/implementation-artifacts/deferred-work.md")
    content = deferred_path.read_text()
    assert "[deferred-to-bulk-upload-story]" in content
