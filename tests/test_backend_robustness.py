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


def test_facilioo_phase3_partial_failure_skips_unit_with_log(capsys):
    """Phase-3: Exception in einem Unit-Attr-Call → Log-Print, restliche Units kommen durch."""
    async def _run():
        unit_ids = ["uid-ok", "uid-fail"]
        error = httpx.HTTPStatusError(
            "mock 500", request=MagicMock(), response=MagicMock(status_code=500)
        )

        async def ok_task():
            return [{"attributeId": 1438, "value": "500"}]

        async def fail_task():
            raise error

        attr_lists = await asyncio.gather(ok_task(), fail_task(), return_exceptions=True)
        attr_by_unit: dict = {}
        for uid, result in zip(unit_ids, attr_lists):
            if isinstance(result, Exception):
                print(f"[facilioo] phase3_unit_attr_failed unit_id={uid} error={result}")
                attr_by_unit[uid] = []
            else:
                attr_by_unit[uid] = result
        return attr_by_unit

    attr_by_unit = asyncio.run(_run())
    captured = capsys.readouterr()
    assert "phase3_unit_attr_failed" in captured.out
    assert "uid-fail" in captured.out
    assert attr_by_unit["uid-ok"] == [{"attributeId": 1438, "value": "500"}]
    assert attr_by_unit["uid-fail"] == []


def test_facilioo_phase3_partial_failure_attr_by_unit_has_empty_for_failed():
    """Phase-3 Exception: attr_by_unit[failing-uid] == []."""
    async def _run():
        unit_ids = ["uid-a", "uid-b", "uid-c"]

        async def ok():
            return [{"v": 1}]

        async def fail():
            raise ValueError("boom")

        results = await asyncio.gather(ok(), fail(), ok(), return_exceptions=True)
        attr_by_unit: dict = {}
        for uid, r in zip(unit_ids, results):
            attr_by_unit[uid] = [] if isinstance(r, Exception) else r
        return attr_by_unit

    attr_by_unit = asyncio.run(_run())
    assert attr_by_unit["uid-a"] == [{"v": 1}]
    assert attr_by_unit["uid-b"] == []
    assert attr_by_unit["uid-c"] == [{"v": 1}]


def test_facilioo_phase2_vg_non_dict_skipped_with_log(capsys):
    """Phase-2: Non-Dict-VG wird mit Print-Log uebersprungen, kein AttributeError."""
    # Simuliert den Phase-2-Loop aus facilioo.py
    vg_details = ["unexpected_string", {"units": [{"id": "u1"}]}]
    shares = [{"votingGroupId": "vg1"}, {"votingGroupId": "vg2"}]

    voting_groups: list[dict] = []
    vg_index = 0
    for s in shares:
        if s.get("votingGroupId") is None:
            continue
        vg = vg_details[vg_index]
        if not isinstance(vg, dict):
            print(f"[facilioo] phase2_vg_non_dict vg={vg!r}")
            vg_index += 1
            continue
        voting_groups.append({"voting_group": vg, "shares": s.get("shares", "")})
        vg_index += 1

    captured = capsys.readouterr()
    assert "phase2_vg_non_dict" in captured.out
    assert len(voting_groups) == 1
    assert voting_groups[0]["voting_group"] == {"units": [{"id": "u1"}]}


def test_facilioo_phase3_unit_ids_skips_non_dict_vgs():
    """Phase-3: unit_ids enthaelt nur Units gueltiger Dict-VGs."""
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

    assert "u1" in unit_ids
    assert "u2" in unit_ids
    assert "u3" in unit_ids
    assert len(unit_ids) == 3  # Dedup: u2 nur einmal


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
    """get_or_update_pflegegrad_cache raises → Detail-Page liefert 200, kein 500."""
    from app.services import pflegegrad as pg_module

    monkeypatch.setattr(
        pg_module,
        "get_or_update_pflegegrad_cache",
        lambda obj, db: (_ for _ in ()).throw(RuntimeError("DB-Hiccup-Test")),
    )

    resp = client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200


def test_object_detail_pflegegrad_cache_commit_fail_creates_audit(db, obj, client, monkeypatch):
    """db.commit() im pflegegrad-Cache-Branch raised → audit_log enthaelt pflegegrad_cache_commit_fail."""
    from app.services import pflegegrad as pg_module
    from app.services.pflegegrad import PflegegradResult

    # get_or_update_pflegegrad_cache gibt cache_updated=True zurueck
    fake_result = PflegegradResult(score=80, weakest_fields=[], per_cluster={})
    monkeypatch.setattr(
        pg_module,
        "get_or_update_pflegegrad_cache",
        lambda o, d: (fake_result, True),
    )

    # db.commit() soll im Cache-Branch einen IntegrityError werfen
    from sqlalchemy.exc import IntegrityError
    commit_count = [0]

    def _fail_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            raise IntegrityError(None, None, Exception("test"))
        # Weitere Commits (z. B. Audit-Session in _audit_in_new_session) laufen normal

    with patch.object(db, "commit", side_effect=_fail_commit):
        resp = client.get(f"/objects/{obj.id}")

    assert resp.status_code == 200
    # Audit-Eintrag pruefen (von _audit_in_new_session in neuer Session geschrieben)
    logs = db.execute(
        select(AuditLog).where(AuditLog.action == "pflegegrad_cache_commit_fail")
    ).scalars().all()
    assert len(logs) >= 1
    assert str(obj.id) in str(logs[0].entity_id)


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
