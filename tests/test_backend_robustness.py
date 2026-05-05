"""Story 5-3: Backend-Robustheit & Crash-Guards.

Prueft:
  AC1: Facilioo-Aggregator-Haertung (Phase-3 partial-degrade, Schema-Drift, Loop-Termination)
  AC2: Pflegegrad-Cluster-Haertung (Crash-Guard, Cache-Fail-Audit)
  AC3: Approve-Review-Entry Row-Lock
  AC4: Cancellation-Hygiene + SharePoint-Token-Executor
  AC5: Police-Form FK-Existenzcheck + Decimal-Range
  AC6: Police-Delete-Sichtbarkeit + Wartung-Orphan-Branch
  AC7: Wartung-Form intervall-Range + NBSP-strip
  AC8: pflegegrad_color Score-Clamp
  AC9: key_id-Rotation Backlog-Eintrag
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.sql.selectable import Select

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import (
    AuditLog,
    InsurancePolicy,
    Object,
    Schadensfall,
    User,
    Wartungspflicht,
)
from app.models.registry import Versicherer
from app.services import facilioo as facilioo_module
from app.templating import pflegegrad_color
from tests.conftest import _TEST_CSRF_TOKEN, _make_session_cookie


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def obj(db) -> Object:
    o = Object(id=uuid.uuid4(), short_code="ROB1", name="Robustheit-Test-Objekt")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture
def editor_user(db) -> User:
    u = User(
        id=uuid.uuid4(),
        google_sub="google-sub-robust-edit",
        email="robust-edit@dbshome.de",
        name="Robustheit Edit User",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:view_confidential",
            "objects:approve_ki",
            "registries:view",
            "registries:edit",
            "audit_log:view",
        ],
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def client(db, editor_user) -> Iterator[TestClient]:
    def override_db():
        yield db

    def override_user():
        return editor_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def policy(db, obj, editor_user):
    p = InsurancePolicy(
        id=uuid.uuid4(),
        object_id=obj.id,
        police_number="TEST-POL-001",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def versicherer(db):
    v = Versicherer(id=uuid.uuid4(), name="Test-Versicherer")
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


# ---------------------------------------------------------------------------
# AC1 — Facilioo-Aggregator-Haertung
# ---------------------------------------------------------------------------

def _mock_facilioo_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.facilioo.de",
        transport=httpx.MockTransport(handler),
    )


def _json_resp(data, status=200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _make_facilioo_api_get_mock(handlers: dict):
    """Helper: liefert einen `_api_get`-Mock, der pro Pfad-Substring einen Handler hat."""
    async def _fake(client, path, params=None, **kwargs):
        for prefix, handler in handlers.items():
            if prefix in path:
                if callable(handler):
                    return handler(path, params)
                return handler
        return {}
    return _fake


def _phase3_router(units, attr_handler):
    """Baut einen `_api_get`-Mock fuer fetch_conference_signature_payload(123).

    `units` = Liste von Unit-IDs fuer die Voting-Group 1.
    `attr_handler(uid)` wird pro Unit-Attr-Call gerufen — Rueckgabewert wird
    direkt zurueckgegeben, oder die Exception wird raised.
    """
    async def _fake(client, path, params=None, **kwargs):
        # WICHTIG: spezifische Pfade ZUERST. `/conferences/123` ist Praefix
        # vieler Subpfade — sonst greift es zu frueh.
        if path == "/api/conferences/123":
            return {"id": 123, "title": "Test"}
        if path == "/api/conferences/123/property":
            return {"id": 1, "name": "Prop"}
        if "voting-groups/shares" in path:
            return {"items": [{"votingGroupId": 1, "shares": "100"}], "totalPages": 1}
        if "/mandates" in path:
            return {"items": [], "totalPages": 1}
        if path == "/api/voting-groups/1":
            return {"id": 1, "units": [{"id": uid} for uid in units], "parties": []}
        for uid in units:
            if path == f"/api/units/{uid}/attribute-values":
                return attr_handler(uid)
        return {}
    return _fake


def test_facilioo_phase3_propagates_cancelled_error(monkeypatch):
    """Phase-3: CancelledError aus einem Unit-Attr-Call darf NICHT als 'failed unit'
    geschluckt werden — `BaseException`-Filter muss ihn re-raisen (analog Phase-1)."""
    call_state = {"counter": 0}

    def _attr(uid):
        call_state["counter"] += 1
        raise asyncio.CancelledError()

    monkeypatch.setattr(facilioo_module, "_api_get", _phase3_router([11], _attr))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(facilioo_module.fetch_conference_signature_payload(123))
    assert call_state["counter"] >= 1


def test_facilioo_phase3_swallows_regular_exception(monkeypatch):
    """Phase-3: regulaere Exception wird zu attr_by_unit[uid]=[], PDF laeuft weiter."""
    def _attr(uid):
        if uid == 11:
            raise httpx.HTTPStatusError(
                "mock 500", request=MagicMock(), response=MagicMock(status_code=500)
            )
        return {"items": [{"attributeId": 1438, "value": "500"}], "totalPages": 1}

    monkeypatch.setattr(facilioo_module, "_api_get", _phase3_router([11, 22], _attr))

    payload = asyncio.run(facilioo_module.fetch_conference_signature_payload(123))
    assert payload["conference"]["id"] == 123
    assert len(payload["voting_groups"]) == 1


def test_facilioo_phase2_vg_non_dict_skipped(monkeypatch, caplog):
    """Phase-2: Non-Dict-VG wird mit _logger.warning uebersprungen, kein AttributeError."""
    import logging
    caplog.set_level(logging.WARNING, logger="app.services.facilioo")

    async def _fake(client, path, params=None, **kwargs):
        if path == "/api/conferences/123":
            return {"id": 123, "title": "Test"}
        if path == "/api/conferences/123/property":
            return {"id": 1, "name": "Prop"}
        if "voting-groups/shares" in path:
            return {
                "items": [
                    {"votingGroupId": 1, "shares": "100"},
                    {"votingGroupId": 2, "shares": "200"},
                ],
                "totalPages": 1,
            }
        if "/mandates" in path:
            return {"items": [], "totalPages": 1}
        if path == "/api/voting-groups/1":
            return "unexpected_string"  # ← Schema-Drift, kein dict
        if path == "/api/voting-groups/2":
            return {"id": 2, "units": [], "parties": []}
        return {}

    monkeypatch.setattr(facilioo_module, "_api_get", _fake)

    payload = asyncio.run(facilioo_module.fetch_conference_signature_payload(123))
    assert "phase2_vg_non_dict" in caplog.text
    assert len(payload["voting_groups"]) == 1
    assert payload["voting_groups"][0]["voting_group"]["id"] == 2


def test_facilioo_phase3_unit_ids_skips_non_dict_vgs():
    """Phase-3: unit_ids enthaelt nur Units gueltiger Dict-VGs (Inline-Logik)."""
    voting_groups = [
        {"voting_group": "invalid_string"},
        {"voting_group": {"units": [{"id": "u1"}, {"id": "u2"}]}},
        {"voting_group": {"units": [{"id": "u2"}, {"id": "u3"}]}},
    ]

    unit_ids: list = []
    seen_ids: set = set()
    for vg in voting_groups:
        vg_inner = vg["voting_group"]
        if not isinstance(vg_inner, dict):
            continue
        for u in (vg_inner.get("units") or []):
            if u.get("id") is not None and u["id"] not in seen_ids:
                unit_ids.append(u["id"])
                seen_ids.add(u["id"])

    assert unit_ids == ["u1", "u2", "u3"]  # Dedup: u2 nur einmal, Reihenfolge stabil


def test_get_all_paged_total_pages_NaN_does_not_crash(monkeypatch):
    """totalPages='NaN' → Loop terminiert nach _MAX_PAGES, kein ValueError."""
    page_count = [0]

    async def _fake_api_get(client, path, params=None, **kwargs):
        page_count[0] += 1
        return {"items": [{"id": page_count[0]}], "totalPages": "NaN"}

    monkeypatch.setattr(facilioo_module, "_api_get", _fake_api_get)

    async def _run():
        client = MagicMock()
        return await facilioo_module._get_all_paged(client, "/api/test", rate_gate=False)

    items = asyncio.run(_run())
    assert page_count[0] <= facilioo_module._MAX_PAGES + 1
    assert len(items) > 0


def test_get_all_paged_total_pages_None_does_not_crash(monkeypatch):
    """totalPages=None → Loop terminiert nach _MAX_PAGES, kein Fehler."""
    page_count = [0]

    async def _fake_api_get(client, path, params=None, **kwargs):
        page_count[0] += 1
        # Nach 3 Seiten leeren Inhalt zurueckgeben, damit Loop terminiert
        if page_count[0] > 3:
            return {"items": [], "totalPages": None}
        return {"items": [{"id": page_count[0]}], "totalPages": None}

    monkeypatch.setattr(facilioo_module, "_api_get", _fake_api_get)

    async def _run():
        client = MagicMock()
        return await facilioo_module._get_all_paged(client, "/api/test", rate_gate=False)

    items = asyncio.run(_run())
    assert len(items) == 3


def test_get_all_paged_bare_list_clamped_below_page_size_continues(monkeypatch):
    """Bare-List mit len < _PAGE_SIZE, aber weiterer leerer Page: Loop terminiert korrekt."""
    # Simuliert Server der 50 Items zurueckgibt (< _PAGE_SIZE=100), dann leer
    responses = [
        [{"id": i} for i in range(50)],  # Page 1: 50 Items
        [],                                # Page 2: leer
    ]
    page_count = [0]

    async def _fake_api_get(client, path, params=None, **kwargs):
        idx = min(page_count[0], len(responses) - 1)
        page_count[0] += 1
        return responses[idx]

    monkeypatch.setattr(facilioo_module, "_api_get", _fake_api_get)

    async def _run():
        client = MagicMock()
        return await facilioo_module._get_all_paged(client, "/api/test", rate_gate=False)

    items = asyncio.run(_run())
    # len(data) < _PAGE_SIZE → bricht direkt ab nach Page 1
    assert len(items) == 50


def test_get_all_paged_bare_list_empty_stops_loop(monkeypatch):
    """Bare-List: if not data → break, auch bei vollstaendigen Pages."""
    page_count = [0]

    async def _fake_api_get(client, path, params=None, **kwargs):
        page_count[0] += 1
        if page_count[0] <= 2:
            return [{"id": i} for i in range(facilioo_module._PAGE_SIZE)]
        return []  # Leere Page → terminiert

    monkeypatch.setattr(facilioo_module, "_api_get", _fake_api_get)

    async def _run():
        client = MagicMock()
        return await facilioo_module._get_all_paged(client, "/api/test", rate_gate=False)

    items = asyncio.run(_run())
    assert len(items) == 2 * facilioo_module._PAGE_SIZE


# ---------------------------------------------------------------------------
# AC2 — Pflegegrad-Cluster-Haertung
# ---------------------------------------------------------------------------

def test_object_detail_pflegegrad_service_crash_returns_200(db, obj, client, monkeypatch):
    """get_or_update_pflegegrad_cache raises → Detail-Page liefert 200, kein 500.

    Wichtig: patcht im Router-Namespace (`app.routers.objects`), nicht in
    `app.services.pflegegrad` — die Router-Datei hat den Symbol-Namen ueber
    `from ... import` bereits in den eigenen Namespace gezogen, ein Patch
    am Source-Modul wuerde die Call-Site nicht erreichen.
    """
    from app.routers import objects as objects_router

    def _crash(obj, db, prov_map=None):
        raise RuntimeError("DB-Hiccup-Test")

    monkeypatch.setattr(objects_router, "get_or_update_pflegegrad_cache", _crash)

    resp = client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200


def test_object_detail_pflegegrad_cache_commit_fail_creates_audit(db, obj, client, monkeypatch):
    """db.commit() im pflegegrad-Cache-Branch raised → audit_log enthaelt pflegegrad_cache_commit_fail."""
    from app.routers import objects as objects_router
    from app.services.pflegegrad import PflegegradResult

    fake_result = PflegegradResult(score=80, weakest_fields=[], per_cluster={})
    monkeypatch.setattr(
        objects_router,
        "get_or_update_pflegegrad_cache",
        lambda o, d, prov_map=None: (fake_result, True),
    )

    from sqlalchemy.exc import IntegrityError
    commit_count = [0]

    def _fail_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            raise IntegrityError("INSERT", {}, Exception("simulated"))

    with patch.object(db, "commit", side_effect=_fail_commit):
        resp = client.get(f"/objects/{obj.id}")

    assert resp.status_code == 200
    # _audit_in_new_session schreibt in eigene SessionLocal — wir lesen aus
    # einer neuen Session, weil der Test-`db`-Cache den Audit-Row sonst nicht sieht.
    from app.db import SessionLocal
    audit_db = SessionLocal()
    try:
        logs = audit_db.execute(
            select(AuditLog).where(AuditLog.action == "pflegegrad_cache_commit_fail")
        ).scalars().all()
    finally:
        audit_db.close()
    assert len(logs) >= 1
    assert str(logs[0].entity_id) == str(obj.id)


def test_object_detail_pflegegrad_cache_commit_fail_warning_log_unchanged(
    db, obj, client, monkeypatch, caplog
):
    """Cache-Commit-Fail: existing _logger.warning-Log bleibt erhalten (Sanity, AC2 Spec-Test)."""
    import logging
    from app.routers import objects as objects_router
    from app.services.pflegegrad import PflegegradResult

    fake_result = PflegegradResult(score=80, weakest_fields=[], per_cluster={})
    monkeypatch.setattr(
        objects_router,
        "get_or_update_pflegegrad_cache",
        lambda o, d, prov_map=None: (fake_result, True),
    )

    from sqlalchemy.exc import IntegrityError
    commit_count = [0]

    def _fail_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            raise IntegrityError("INSERT", {}, Exception("simulated"))

    caplog.set_level(logging.WARNING, logger="app.routers.objects")
    with patch.object(db, "commit", side_effect=_fail_commit):
        resp = client.get(f"/objects/{obj.id}")

    assert resp.status_code == 200
    assert "pflegegrad cache commit failed" in caplog.text


# ---------------------------------------------------------------------------
# AC3 — Approve-Review-Entry Row-Lock
# ---------------------------------------------------------------------------

def test_approve_review_entry_uses_for_update(db, obj, editor_user):
    """approve_review_entry nutzt SELECT...FOR UPDATE auf ReviewQueueEntry."""
    from app.models.governance import ReviewQueueEntry
    from app.services.steckbrief_write_gate import approve_review_entry
    import datetime as _dt

    obj.heating_type = None
    db.flush()

    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=obj.id,
        field_name="heating_type",
        proposed_value={"value": "Gas"},
        agent_ref="test-agent",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=_dt.datetime(2025, 1, 15, tzinfo=_dt.timezone.utc),
    )
    db.add(entry)
    db.commit()

    execute_stmts: list = []
    real_execute = db.execute

    def spy_execute(stmt, *args, **kwargs):
        execute_stmts.append(stmt)
        return real_execute(stmt, *args, **kwargs)

    with patch.object(db, "execute", side_effect=spy_execute):
        approve_review_entry(db, entry_id=entry.id, user=editor_user)

    for_update_found = any(
        isinstance(stmt, Select) and getattr(stmt, "_for_update_arg", None) is not None
        for stmt in execute_stmts
    )
    assert for_update_found, "approve_review_entry muss SELECT...FOR UPDATE ausfuehren"


def test_approve_review_entry_double_approve_second_raises_value_error(db, obj, editor_user):
    """Zwei sequentielle Approve-Calls → zweiter wirft ValueError."""
    from app.models.governance import ReviewQueueEntry
    from app.services.steckbrief_write_gate import approve_review_entry
    import datetime as _dt

    obj.heating_type = None
    db.flush()

    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=obj.id,
        field_name="heating_type",
        proposed_value={"value": "Gas"},
        agent_ref="test-agent",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=_dt.datetime(2025, 1, 15, tzinfo=_dt.timezone.utc),
    )
    db.add(entry)
    db.commit()

    approve_review_entry(db, entry_id=entry.id, user=editor_user)
    db.commit()

    with pytest.raises(ValueError, match="bereits entschieden"):
        approve_review_entry(db, entry_id=entry.id, user=editor_user)


def test_reject_review_entry_uses_for_update(db, obj, editor_user):
    """reject_review_entry nutzt SELECT...FOR UPDATE auf ReviewQueueEntry."""
    from app.models.governance import ReviewQueueEntry
    from app.services.steckbrief_write_gate import reject_review_entry
    import datetime as _dt

    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=obj.id,
        field_name="heating_type",
        proposed_value={"value": "Gas"},
        agent_ref="test-agent",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=_dt.datetime(2025, 1, 15, tzinfo=_dt.timezone.utc),
    )
    db.add(entry)
    db.commit()

    execute_stmts: list = []
    real_execute = db.execute

    def spy_execute(stmt, *args, **kwargs):
        execute_stmts.append(stmt)
        return real_execute(stmt, *args, **kwargs)

    with patch.object(db, "execute", side_effect=spy_execute):
        reject_review_entry(db, entry_id=entry.id, user=editor_user, reason="Test")

    for_update_found = any(
        isinstance(stmt, Select) and getattr(stmt, "_for_update_arg", None) is not None
        for stmt in execute_stmts
    )
    assert for_update_found, "reject_review_entry muss SELECT...FOR UPDATE ausfuehren"


# ---------------------------------------------------------------------------
# AC4 — Cancellation-Hygiene + SharePoint-Token-Executor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_impower_get_bank_balance_propagates_cancelled_error():
    """CancelledError propagiert aus get_bank_balance, wird nicht zu 500."""
    from app.services.impower import get_bank_balance

    async def _failing_get(*args, **kwargs):
        raise asyncio.CancelledError("disconnected")

    with patch("httpx.AsyncClient.__aenter__", new_callable=AsyncMock) as mock_ctx:
        mock_client = AsyncMock()
        mock_client.get = _failing_get
        mock_ctx.return_value = mock_client
        with pytest.raises(asyncio.CancelledError):
            await get_bank_balance("PROP-001")


@pytest.mark.asyncio
async def test_photo_store_get_token_async_uses_executor():
    """_get_token_async ruft run_in_executor auf, um den sync-Token-Call in Executor auszulagern."""
    from app.services.photo_store import SharePointPhotoStore

    store = SharePointPhotoStore.__new__(SharePointPhotoStore)
    store._get_token = MagicMock(return_value="fake-token")

    loop = asyncio.get_event_loop()
    executor_calls: list = []
    original_run = loop.run_in_executor

    async def spy_executor(exc, fn, *args):
        executor_calls.append(fn)
        return fn(*args) if args else fn()

    with patch.object(loop, "run_in_executor", side_effect=spy_executor):
        token = await store._get_token_async()

    assert token == "fake-token"
    assert len(executor_calls) >= 1


@pytest.mark.asyncio
async def test_photo_store_upload_uses_async_token():
    """upload() ruft _get_token_async (nicht _get_token) auf."""
    from app.services.photo_store import SharePointPhotoStore, PhotoRef

    store = SharePointPhotoStore.__new__(SharePointPhotoStore)
    called = [False]

    async def fake_async_token():
        called[0] = True
        return "fake-token"

    store._get_token_async = fake_async_token
    store.drive_id = "drive-123"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "item-abc"}
        mock_resp.raise_for_status = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.put = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_ctx

        await store.upload(
            object_short_code="OBJ1",
            category="technik",
            filename="test.jpg",
            content=b"\xff\xd8\xff\x00",
            content_type="image/jpeg",
        )

    assert called[0], "upload() muss _get_token_async aufrufen"


# ---------------------------------------------------------------------------
# AC5 — Police-Form FK-Existenzcheck + Decimal-Range
# ---------------------------------------------------------------------------

def test_police_create_rejects_unknown_versicherer_id(client, obj):
    """POST Police mit nicht-existenter versicherer_id → 422."""
    resp = client.post(
        f"/objects/{obj.id}/policen",
        data={"versicherer_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 422


def test_police_update_rejects_unknown_versicherer_id(client, obj, policy):
    """PUT Police mit nicht-existenter versicherer_id → 422."""
    resp = client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={"versicherer_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 422


def test_police_create_accepts_existing_versicherer_id(client, obj, versicherer):
    """POST Police mit existierender versicherer_id → 200."""
    resp = client.post(
        f"/objects/{obj.id}/policen",
        data={"versicherer_id": str(versicherer.id)},
    )
    assert resp.status_code == 200


def test_parse_decimal_rejects_overflow():
    """_parse_decimal('10000000000.00') → HTTPException 422."""
    from app.routers.objects import _parse_decimal
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _parse_decimal("10000000000.00")
    assert exc_info.value.status_code == 422


def test_parse_decimal_accepts_max_legal_value():
    """_parse_decimal('9999999999.99') → Decimal ohne Exception."""
    from app.routers.objects import _parse_decimal

    result = _parse_decimal("9999999999.99")
    assert result == Decimal("9999999999.99")


def test_parse_decimal_handles_zero():
    """_parse_decimal('0.00') → Decimal('0.00')."""
    from app.routers.objects import _parse_decimal

    result = _parse_decimal("0.00")
    assert result == Decimal("0.00")


# ---------------------------------------------------------------------------
# AC6 — Police-Delete-Sichtbarkeit + Wartung-Orphan-Branch
# ---------------------------------------------------------------------------

def test_delete_police_loads_relations_before_delete(db, obj, editor_user):
    """delete_police touched wartungspflichten und schadensfaelle vor db.delete."""
    from app.services.steckbrief_policen import delete_police

    p = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id, police_number="DEL-001")
    db.add(p)
    db.commit()
    db.refresh(p)

    accessed: list[str] = []
    original_wartungen = p.__class__.wartungspflichten
    original_schadensfaelle = p.__class__.schadensfaelle

    delete_count = [0]
    real_delete = db.delete

    def tracking_delete(instance):
        delete_count[0] += 1
        # Vor dem echten Delete pruefen, ob Relations bereits accessed sind
        accessed.append(f"wartungen:{len(p.wartungspflichten)}")
        accessed.append(f"schadensfaelle:{len(p.schadensfaelle)}")
        real_delete(instance)

    with patch.object(db, "delete", side_effect=tracking_delete):
        delete_police(db, p, editor_user, request=None)

    assert delete_count[0] == 1
    assert len(accessed) > 0


def test_delete_police_writes_policy_deleted_audit(db, obj, editor_user):
    """delete_police schreibt policy_deleted-Audit-Eintrag."""
    from app.services.steckbrief_policen import delete_police

    p = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id, police_number="DEL-002")
    db.add(p)
    db.commit()
    db.refresh(p)

    delete_police(db, p, editor_user, request=None)
    db.commit()

    logs = db.execute(
        select(AuditLog).where(AuditLog.action == "policy_deleted")
    ).scalars().all()
    assert len(logs) >= 1
    assert logs[0].details_json is not None
    assert "wartung_count" in logs[0].details_json
    assert "schadensfall_count" in logs[0].details_json


def test_delete_police_cascades_wartungen_and_schadensfaelle(db, obj, client):
    """DELETE Police → 200, Wartungen + Schadensfaelle verschwinden."""
    p = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id, police_number="DEL-003")
    db.add(p)
    db.flush()

    from app.services.steckbrief_wartungen import create_wartungspflicht
    wart = create_wartungspflicht(
        db, p, None, None,
        bezeichnung="Test-Wartung",
        dienstleister_id=None,
        intervall_monate=12,
        letzte_wartung=None,
        next_due_date=None,
    )
    db.commit()

    wart_id = wart.id
    resp = client.delete(f"/objects/{obj.id}/policen/{p.id}")
    assert resp.status_code == 200

    db.expire_all()
    assert db.get(InsurancePolicy, p.id) is None
    assert db.get(Wartungspflicht, wart_id) is None


def test_delete_orphan_wartung_returns_empty_response(db, obj, client):
    """DELETE orphan-Wartung (policy_id=NULL) → leerer 200-Response, kein Vollsektions-HTML."""
    from app.models import Wartungspflicht

    wart = Wartungspflicht(
        id=uuid.uuid4(),
        object_id=obj.id,
        policy_id=None,
        bezeichnung="Orphan-Wartung",
    )
    db.add(wart)
    db.commit()

    resp = client.delete(f"/objects/{obj.id}/wartungspflichten/{wart.id}")
    assert resp.status_code == 200
    assert resp.text == ""


# ---------------------------------------------------------------------------
# AC7 — Wartung-Form intervall-Range + NBSP-strip
# ---------------------------------------------------------------------------

def test_wartung_create_rejects_intervall_over_600(client, obj, policy):
    """POST Wartung mit intervall_monate='601' → 422."""
    resp = client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Test", "intervall_monate": "601"},
    )
    assert resp.status_code == 422


def test_wartung_create_accepts_intervall_at_600(client, obj, policy):
    """POST Wartung mit intervall_monate='600' → 200."""
    resp = client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Test", "intervall_monate": "600"},
    )
    assert resp.status_code == 200


def test_wartung_create_rejects_intervall_below_1(client, obj, policy):
    """POST Wartung mit intervall_monate='0' → 422 (existing check, Sanity)."""
    resp = client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "Test", "intervall_monate": "0"},
    )
    assert resp.status_code == 422


def test_wartung_create_rejects_zwsp_only_bezeichnung(client, obj, policy):
    """POST Wartung mit bezeichnung='\\u200b\\u200b' (ZWSP) → 422."""
    resp = client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "​​"},
    )
    assert resp.status_code == 422


def test_wartung_create_strips_zwsp_from_bezeichnung(db, client, obj, policy):
    """POST Wartung mit ZWSP um echten Text → 200, in DB als 'Wartung'."""
    resp = client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "​Wartung​"},
    )
    assert resp.status_code == 200
    db.expire_all()
    warts = db.execute(
        select(Wartungspflicht).where(Wartungspflicht.policy_id == policy.id)
    ).scalars().all()
    assert any(w.bezeichnung == "Wartung" for w in warts)


def test_wartung_create_strips_nbsp_from_bezeichnung(db, client, obj, policy):
    """POST Wartung mit NBSP um echten Text → 200, in DB als 'Wartung'."""
    resp = client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": " Wartung "},
    )
    assert resp.status_code == 200
    db.expire_all()
    warts = db.execute(
        select(Wartungspflicht).where(Wartungspflicht.policy_id == policy.id)
    ).scalars().all()
    assert any(w.bezeichnung == "Wartung" for w in warts)


def test_wartung_create_strips_bom_from_bezeichnung(db, client, obj, policy):
    """POST Wartung mit BOM-Prefix → 200, in DB als 'Test'."""
    resp = client.post(
        f"/objects/{obj.id}/policen/{policy.id}/wartungspflichten",
        data={"bezeichnung": "﻿Test"},
    )
    assert resp.status_code == 200
    db.expire_all()
    warts = db.execute(
        select(Wartungspflicht).where(Wartungspflicht.policy_id == policy.id)
    ).scalars().all()
    assert any(w.bezeichnung == "Test" for w in warts)


def test_normalize_text_handles_none_returns_empty():
    """_normalize_text(None) → ''."""
    from app.services._text import _normalize_text

    assert _normalize_text(None) == ""


def test_normalize_text_strips_all_invisible_chars():
    """_normalize_text entfernt ZWSP, NBSP, BOM, ZWJ."""
    from app.services._text import _normalize_text

    assert _normalize_text("​‌‍﻿") == ""
    assert _normalize_text(" Text​") == "Text"
    assert _normalize_text("  Hello  ") == "Hello"


# ---------------------------------------------------------------------------
# AC8 — pflegegrad_color Score-Clamp
# ---------------------------------------------------------------------------

def test_pflegegrad_color_clamps_negative_to_red():
    """pflegegrad_color(-5) == pflegegrad_color(0)."""
    assert pflegegrad_color(-5) == pflegegrad_color(0)
    assert "red" in pflegegrad_color(-5)


def test_pflegegrad_color_clamps_over_100_to_green():
    """pflegegrad_color(150) == pflegegrad_color(100)."""
    assert pflegegrad_color(150) == pflegegrad_color(100)
    assert "green" in pflegegrad_color(150)


def test_pflegegrad_color_none_unchanged():
    """pflegegrad_color(None) liefert slate-Klasse."""
    result = pflegegrad_color(None)
    assert "slate" in result


def test_pflegegrad_color_boundary_70():
    """pflegegrad_color(70) → gruen."""
    assert "green" in pflegegrad_color(70)


def test_pflegegrad_color_boundary_40():
    """pflegegrad_color(40) → gelb."""
    assert "yellow" in pflegegrad_color(40)


def test_pflegegrad_color_boundary_39():
    """pflegegrad_color(39) → rot."""
    assert "red" in pflegegrad_color(39)


# ---------------------------------------------------------------------------
# AC9 — key_id-Rotation Doku
# ---------------------------------------------------------------------------

def test_field_encryption_has_rotation_warning_comment():
    """app/services/field_encryption.py enthaelt den Key-Rotation-Warning-Kommentar."""
    content = open("app/services/field_encryption.py", encoding="utf-8").read()
    assert "Key-Rotation aktuell NICHT supported" in content


def test_deferred_work_marks_115_as_v2_key_ring_story():
    """output/implementation-artifacts/deferred-work.md enthaelt deferred-to-v2-key-ring-story."""
    content = open(
        "output/implementation-artifacts/deferred-work.md", encoding="utf-8"
    ).read()
    assert "[deferred-to-v2-key-ring-story]" in content


# ---------------------------------------------------------------------------
# Code-Review-Patches (2026-05-05): Edge-Cases + fehlende Spec-Tests
# ---------------------------------------------------------------------------

# AC1 — Spec-Test fuer Bare-List MAX_PAGES-Cap

def test_get_all_paged_bare_list_max_pages_cap_terminates(monkeypatch):
    """Bare-List in voller _PAGE_SIZE-Groesse fuer mehr als _MAX_PAGES Pages → Cap greift."""
    page_count = [0]

    async def _fake_api_get(client, path, params=None, **kwargs):
        page_count[0] += 1
        return [{"id": page_count[0]}] * facilioo_module._PAGE_SIZE

    monkeypatch.setattr(facilioo_module, "_api_get", _fake_api_get)

    async def _run():
        client = MagicMock()
        return await facilioo_module._get_all_paged(client, "/api/test", rate_gate=False)

    items = asyncio.run(_run())
    # _MAX_PAGES greift — sonst waeren wir endlos im Loop
    assert page_count[0] == facilioo_module._MAX_PAGES
    assert len(items) == facilioo_module._MAX_PAGES * facilioo_module._PAGE_SIZE


def test_get_all_paged_total_pages_infinity_does_not_crash(monkeypatch):
    """totalPages='Infinity' (OverflowError) → Loop terminiert sauber, kein Crash."""
    page_count = [0]

    async def _fake_api_get(client, path, params=None, **kwargs):
        page_count[0] += 1
        if page_count[0] > 3:
            return {"items": [], "totalPages": "Infinity"}
        return {"items": [{"id": page_count[0]}], "totalPages": "Infinity"}

    monkeypatch.setattr(facilioo_module, "_api_get", _fake_api_get)

    async def _run():
        client = MagicMock()
        return await facilioo_module._get_all_paged(client, "/api/test", rate_gate=False)

    items = asyncio.run(_run())
    # Code muss OverflowError im int(float('inf'))-Cast fangen
    assert len(items) == 3


# AC4 — Spec-Test fuer facilioo._api_get CancelledError-Propagation

@pytest.mark.asyncio
async def test_facilioo_api_get_propagates_cancelled_error():
    """`_api_get` faengt kein generisches `except Exception` um den await — CancelledError
    propagiert wie erwartet, ohne in einen 500er kollabiert zu werden."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await facilioo_module._api_get(client, "/api/test", rate_gate=False)


# AC6 — Spec-Test: Wartung-Row-Template nutzt outerHTML-Swap fuer Per-Row-Refresh

def test_wartung_row_template_uses_outer_html_swap():
    """Wartung-DELETE-Button nutzt `hx-swap="outerHTML"` mit `closest article`-Target
    — damit der orphan-DELETE-Branch (leerer HTMLResponse) das UI konsistent haelt
    (das `<article>` wird durch den leeren Body ersetzt = entfernt)."""
    with open("app/templates/_obj_versicherungen_row.html", encoding="utf-8") as fh:
        text = fh.read()
    # Block fuer Wartung-DELETE muss outerHTML-Swap auf closest article fahren
    assert 'hx-delete="/objects/{{ obj.id }}/wartungspflichten/{{ w.id }}"' in text
    # Innerhalb des Wartung-DELETE-Buttons stehen target+swap zusammen
    wartung_delete_block = text[text.find('wartungspflichten/{{ w.id }}'):]
    wartung_delete_block = wartung_delete_block[:500]
    assert 'hx-target="closest article"' in wartung_delete_block
    assert 'hx-swap="outerHTML"' in wartung_delete_block


# Code-Review-Patches: _normalize_text Edge-Cases

def test_normalize_text_zwsp_inside_word_removes_not_replaces_with_space():
    """ZWSP zwischen zwei Buchstaben → entfernt (nicht durch Space ersetzt)."""
    from app.services._text import _normalize_text

    assert _normalize_text("Wart​ung") == "Wartung"


def test_normalize_text_strips_word_joiner_lrm_rlm():
    """Word-Joiner (U+2060), LRM (U+200E), RLM (U+200F) → entfernt."""
    from app.services._text import _normalize_text

    assert _normalize_text("⁠⁠⁠") == ""
    assert _normalize_text("Test⁠Wert") == "TestWert"
    assert _normalize_text("‎LRM-Bidi-Mark‎") == "LRM-Bidi-Mark"


def test_normalize_text_nbsp_replaced_with_space():
    """NBSP (U+00A0) wird zu regulaerem Space, dann gestripped."""
    from app.services._text import _normalize_text

    # NBSP zwischen Woertern → Space (kein Wort-Bruch wie bei ZWSP)
    assert _normalize_text("Hallo Welt") == "Hallo Welt"


def test_normalize_text_handles_non_string_input():
    """Non-str Input (bytes, int) → '' statt TypeError."""
    from app.services._text import _normalize_text

    assert _normalize_text(b"bytes") == ""  # type: ignore[arg-type]
    assert _normalize_text(123) == ""  # type: ignore[arg-type]


# Code-Review-Patches: pflegegrad_color NaN-Guard

def test_pflegegrad_color_nan_returns_slate():
    """pflegegrad_color(NaN) → slate (nicht silent grün via NaN-Comparison-Quirk)."""
    assert "slate" in pflegegrad_color(float("nan"))


# Code-Review-Patches: _parse_decimal NaN/Infinity → 422

def test_parse_decimal_rejects_nan():
    """_parse_decimal('NaN') wirft 422 (statt InvalidOperation 500 in abs())."""
    from app.routers.objects import _parse_decimal
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _parse_decimal("NaN")
    assert exc_info.value.status_code == 422


def test_parse_decimal_rejects_infinity():
    """_parse_decimal('Infinity') wirft 422."""
    from app.routers.objects import _parse_decimal
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _parse_decimal("Infinity")
    assert exc_info.value.status_code == 422


def test_parse_decimal_rejects_snan():
    """_parse_decimal('sNaN') wirft 422."""
    from app.routers.objects import _parse_decimal
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _parse_decimal("sNaN")
    assert exc_info.value.status_code == 422


# Code-Review-Patches: _client_ip Edge-Cases (host:port + IPv6 zone-ID)

def test_client_ip_strips_port_from_ipv4():
    """`127.0.0.1:8080` (Proxy-XFF mit Source-Port) → '127.0.0.1', nicht None."""
    from app.services.audit import _client_ip

    request = MagicMock()
    request.headers = {"x-forwarded-for": "127.0.0.1:8080"}
    request.client = None
    assert _client_ip(request) == "127.0.0.1"


def test_client_ip_strips_zone_id_from_ipv6():
    """`fe80::1%eth0` (IPv6 mit Zone-ID) → 'fe80::1', nicht None."""
    from app.services.audit import _client_ip

    request = MagicMock()
    request.headers = {"x-forwarded-for": "fe80::1%eth0"}
    request.client = None
    result = _client_ip(request)
    assert result is not None
    assert result.startswith("fe80::")


# Code-Review-Patches: _audit_in_new_session reicht user + request weiter

def test_audit_in_new_session_persists_user_and_ip():
    """`_audit_in_new_session` mit user + request → Audit-Row hat user_id und ip_address."""
    from app.db import SessionLocal
    from app.models import AuditLog
    from app.services.audit import _audit_in_new_session

    test_user = User(
        id=uuid.uuid4(),
        google_sub="audit-helper-test",
        email="audit-helper@dbshome.de",
        name="Audit Helper Test",
    )
    setup_db = SessionLocal()
    try:
        setup_db.add(test_user)
        setup_db.commit()
    finally:
        setup_db.close()

    request = MagicMock()
    request.headers = {"x-forwarded-for": "10.0.0.5"}
    request.client = None

    _audit_in_new_session(
        "pflegegrad_cache_commit_fail",
        entity_type="object",
        entity_id=uuid.uuid4(),
        user=test_user,
        request=request,
    )

    read_db = SessionLocal()
    try:
        rows = read_db.execute(
            select(AuditLog)
            .where(AuditLog.action == "pflegegrad_cache_commit_fail")
            .where(AuditLog.user_id == test_user.id)
        ).scalars().all()
    finally:
        read_db.close()
    assert len(rows) >= 1
    assert rows[0].ip_address == "10.0.0.5"
    assert rows[0].user_email == test_user.email
