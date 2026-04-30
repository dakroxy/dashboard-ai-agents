"""Unit-Tests fuer app/services/facilioo_mirror.py — Story 4.3.

Abdeckung:
  AC2: Lock-Skip, Unmapped-Property-Tracking
  AC3: ETag-Shortcircuit, ETag-Capture, ETag-disabled
  AC4: Reconcile INSERT / UPDATE / ARCHIVE
  AC5: Error-Budget-Alert, Idempotenz, Sample-Limit
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, Object
from app.models.facilioo import FaciliooTicket
from app.services import facilioo as facilioo_svc
from app.services import facilioo_mirror as mirror
from app.services.audit import audit
from app.services.facilioo_mirror import (
    _check_error_budget,
    _reconcile_object_tickets,
    _reset_poller_lock_for_tests,
    run_facilioo_mirror,
)
from tests.conftest import _TestSessionLocal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(status: int, *, json=None, headers: dict | None = None) -> httpx.Response:
    if json is not None:
        return httpx.Response(status, json=json, headers=headers or {})
    return httpx.Response(status, headers=headers or {})


def _make_mock_http_factory(handler):
    """Gibt eine async-context-manager-Factory fuer Mock-HTTP-Calls zurueck."""
    @asynccontextmanager
    async def _factory():
        async with httpx.AsyncClient(
            base_url="https://api.facilioo.de",
            transport=httpx.MockTransport(handler),
        ) as client:
            yield client
    return _factory


def _make_counters() -> dict:
    return {
        "tickets_inserted": 0,
        "tickets_updated": 0,
        "tickets_archived": 0,
        "unmapped_objects": [],
    }


def _seed_object(db, *, short_code: str, impower_property_id: str | None) -> Object:
    obj = Object(
        id=uuid.uuid4(),
        short_code=short_code,
        name=f"Objekt {short_code}",
        impower_property_id=impower_property_id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _seed_ticket(
    db,
    *,
    obj: Object,
    facilioo_id: str,
    status: str = "open",
    title: str = "Test",
    last_modified: datetime | None = None,
    is_archived: bool = False,
) -> FaciliooTicket:
    ticket = FaciliooTicket(
        id=uuid.uuid4(),
        object_id=obj.id,
        facilioo_id=facilioo_id,
        status=status,
        title=title,
        raw_payload={},
        is_archived=is_archived,
        facilioo_last_modified=last_modified,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _write_run(db, *, job: str, objects_failed: int = 0) -> None:
    """Schreibt ein vollstaendiges sync_started + sync_finished-Paar."""
    rid = str(uuid.uuid4())
    audit(
        db, None, "sync_started",
        entity_type="sync_run", entity_id=uuid.UUID(rid),
        details={"job": job, "run_id": rid},
        user_email="system",
    )
    audit(
        db, None, "sync_finished",
        entity_type="sync_run", entity_id=uuid.UUID(rid),
        details={"job": job, "run_id": rid, "objects_failed": objects_failed},
        user_email="system",
    )


@pytest.fixture(autouse=True)
def _reset_mirror_state(monkeypatch):
    """Setzt Lock, ETag, Properties-Cache und Rate-Gate vor jedem Test zurueck."""
    _reset_poller_lock_for_tests()
    monkeypatch.setattr(mirror, "_last_etag", None)
    facilioo_svc._reset_properties_cache_for_tests()
    # Rate-Gate: kein Warten in Tests (vermeidet 1-s-Delays pro API-Call)
    monkeypatch.setattr(facilioo_svc, "_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(facilioo_svc, "_last_request_time", 0.0)


# ---------------------------------------------------------------------------
# AC4: Reconcile — INSERT / UPDATE / ARCHIVE
# ---------------------------------------------------------------------------

def test_full_pull_inserts_new_ticket_with_object_match(db):
    """AC4: Neues API-Ticket → INSERT in facilioo_tickets."""
    obj = _seed_object(db, short_code="INS1", impower_property_id="11111")

    api_ticket = {
        "id": 101,
        "subject": "Dachschaden",
        "isFinished": False,
        "deleted": None,
        "lastModified": "2026-01-15T10:00:00Z",
    }
    bundle = {"object_id": obj.id, "impower_property_id": "11111", "tickets": [api_ticket]}
    counters = _make_counters()

    _reconcile_object_tickets(bundle, db, counters)
    db.commit()

    assert counters["tickets_inserted"] == 1
    assert counters["tickets_updated"] == 0
    ticket = db.execute(
        select(FaciliooTicket).where(FaciliooTicket.facilioo_id == "101")
    ).scalars().first()
    assert ticket is not None
    assert ticket.title == "Dachschaden"
    assert ticket.status == "open"
    assert ticket.is_archived is False


def test_full_pull_updates_changed_status_no_op_on_identical(db):
    """AC4: UPDATE bei neuerem lastModified; No-Op bei identischem Ticket."""
    obj = _seed_object(db, short_code="UPD1", impower_property_id="22222")
    old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

    t1 = _seed_ticket(db, obj=obj, facilioo_id="200", status="open",
                      title="Alt", last_modified=old_ts)
    t2 = _seed_ticket(db, obj=obj, facilioo_id="201", status="open",
                      title="Gleich", last_modified=old_ts)

    api_tickets = [
        # t1: neuer Timestamp + geaenderter Status → Update
        {"id": 200, "subject": "Neu", "isFinished": True, "deleted": None,
         "lastModified": "2026-02-01T12:00:00Z"},
        # t2: gleicher Timestamp + gleicher Inhalt → No-Op
        {"id": 201, "subject": "Gleich", "isFinished": False, "deleted": None,
         "lastModified": "2026-01-01T00:00:00Z"},
    ]
    bundle = {"object_id": obj.id, "impower_property_id": "22222", "tickets": api_tickets}
    counters = _make_counters()

    _reconcile_object_tickets(bundle, db, counters)
    db.commit()

    assert counters["tickets_updated"] == 1
    assert counters["tickets_inserted"] == 0
    db.refresh(t1)
    assert t1.status == "finished"
    assert t1.title == "Neu"
    db.refresh(t2)
    assert t2.status == "open"  # unveraendert


def test_full_pull_archives_missing_ticket(db):
    """AC4: DB-Ticket, das nicht mehr in der API erscheint → is_archived=True."""
    obj = _seed_object(db, short_code="ARC1", impower_property_id="33333")
    ticket = _seed_ticket(db, obj=obj, facilioo_id="300", status="open",
                          title="Altes Ticket")

    # API liefert keine Tickets mehr fuer dieses Object
    bundle = {"object_id": obj.id, "impower_property_id": "33333", "tickets": []}
    counters = _make_counters()

    _reconcile_object_tickets(bundle, db, counters)
    db.commit()
    db.refresh(ticket)

    assert counters["tickets_archived"] == 1
    assert ticket.is_archived is True


# ---------------------------------------------------------------------------
# AC2: Lock-Skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lock_skip_when_already_running(db):
    """AC2: Zweiter Trigger waehrend laufendem Run → skipped=already_running."""
    lock = mirror._get_poller_lock()
    await lock.acquire()
    try:
        result = await run_facilioo_mirror(
            db_factory=_TestSessionLocal,
            http_client_factory=lambda: None,  # nie aufgerufen (Lock-Early-Return)
        )
    finally:
        lock.release()

    assert result.skipped is True
    assert result.skip_reason == "already_running"
    row = db.execute(
        select(AuditLog).where(AuditLog.action == "sync_started")
    ).scalars().first()
    assert row is not None
    assert row.details_json.get("skipped") is True


# ---------------------------------------------------------------------------
# AC3: ETag-Support
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_etag_unchanged_short_circuits_reconcile(db, monkeypatch):
    """AC3: ETag-304-Probe → kein Reconcile, sync_finished etag_unchanged=True."""
    monkeypatch.setattr(mirror, "_last_etag", "stale-etag")
    monkeypatch.setattr(facilioo_svc.settings, "facilioo_etag_enabled", True)

    def handler(request):
        if request.headers.get("if-none-match"):
            return httpx.Response(304)
        raise AssertionError(f"unerwarteter Aufruf ohne ETag-Header: {request.url}")

    result = await run_facilioo_mirror(
        db_factory=_TestSessionLocal,
        http_client_factory=_make_mock_http_factory(handler),
    )

    assert result.skipped is False
    assert result.fetch_failed is False
    row = db.execute(
        select(AuditLog).where(AuditLog.action == "sync_finished")
    ).scalars().first()
    assert row is not None
    assert row.details_json.get("etag_unchanged") is True


@pytest.mark.asyncio
async def test_etag_extracted_and_persisted_across_runs(monkeypatch):
    """AC3: ETag aus Response-Header → in _last_etag gespeichert fuer naechsten Lauf."""
    monkeypatch.setattr(facilioo_svc.settings, "facilioo_etag_enabled", True)

    def handler(request):
        params = dict(request.url.params)
        if params.get("pageSize") == "1":
            # ETag-Capture-Aufruf nach Full-Pull
            return _resp(200, json={"items": []}, headers={"ETag": "fresh-etag-abc"})
        # Normaler paginierter Aufruf
        return _resp(200, json={"items": [], "totalPages": 1})

    await run_facilioo_mirror(
        db_factory=_TestSessionLocal,
        http_client_factory=_make_mock_http_factory(handler),
    )

    assert mirror._last_etag == "fresh-etag-abc"


@pytest.mark.asyncio
async def test_etag_disabled_via_settings_skips_header(monkeypatch):
    """ETag-Probe und ETag-Capture werden uebersprungen wenn facilioo_etag_enabled=False."""
    monkeypatch.setattr(mirror, "_last_etag", "existing-etag")
    monkeypatch.setattr(facilioo_svc.settings, "facilioo_etag_enabled", False)

    probe_calls: list[str] = []

    def handler(request):
        if request.headers.get("if-none-match"):
            probe_calls.append(str(request.url))
        return _resp(200, json={"items": [], "totalPages": 1})

    await run_facilioo_mirror(
        db_factory=_TestSessionLocal,
        http_client_factory=_make_mock_http_factory(handler),
    )

    assert len(probe_calls) == 0


# ---------------------------------------------------------------------------
# AC2 + AC4: Unmapped Property
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_pull_unmapped_property_id_audited_not_inserted(db, monkeypatch):
    """AC2+AC4: Object mit impower_property_id ohne Facilioo-Match → kein INSERT,
    tickets_unmapped=1 in sync_finished."""
    monkeypatch.setattr(facilioo_svc.settings, "facilioo_etag_enabled", False)

    # Facilioo kennt externalId="11111"; Object hat impower_property_id="99999" → kein Match
    _seed_object(db, short_code="NMAP1", impower_property_id="99999")

    def handler(request):
        path = str(request.url.path)
        if "/api/properties" in path:
            return _resp(200, json={"items": [{"id": 42, "externalId": "11111"}], "totalPages": 1})
        raise AssertionError(f"unerwarteter Pfad: {path}")

    result = await run_facilioo_mirror(
        db_factory=_TestSessionLocal,
        http_client_factory=_make_mock_http_factory(handler),
    )

    assert result.fetch_failed is False
    tickets = db.execute(select(FaciliooTicket)).scalars().all()
    assert len(tickets) == 0
    audit_row = db.execute(
        select(AuditLog).where(AuditLog.action == "sync_finished")
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.details_json.get("tickets_unmapped", 0) == 1


# ---------------------------------------------------------------------------
# AC5: Error-Budget
# ---------------------------------------------------------------------------

def test_error_budget_alert_fires_when_threshold_exceeded(db):
    """AC5: > 10 % Fehlerrate bei >= 10 Laeufen → sync_failed alert=error_budget_exceeded."""
    _JOB = "facilioo_ticket_mirror"
    # 10 OK-Laeufe + 2 Fehler-Laeufe → 16.7 % > 10 %
    for _ in range(10):
        _write_run(db, job=_JOB, objects_failed=0)
    for _ in range(2):
        _write_run(db, job=_JOB, objects_failed=1)
    db.commit()

    result = _check_error_budget(uuid.uuid4(), _TestSessionLocal)

    assert result is not None
    assert result["alert"] == "error_budget_exceeded"
    assert result["failed_runs"] == 2
    assert result["total_runs"] == 12

    alert_row = db.execute(
        select(AuditLog).where(AuditLog.action == "sync_failed")
    ).scalars().first()
    assert alert_row is not None
    assert alert_row.details_json.get("alert") == "error_budget_exceeded"


def test_error_budget_alert_idempotent_within_24h_window(db):
    """AC5: Zweiter Check innerhalb 24 h → kein doppelter Alert."""
    _JOB = "facilioo_ticket_mirror"
    # Bereits vorhandener Alert
    audit(
        db, None, "sync_failed",
        entity_type="sync_run", entity_id=None,
        details={
            "job": _JOB, "run_id": str(uuid.uuid4()),
            "alert": "error_budget_exceeded",
            "failure_rate": 0.5, "total_runs": 10, "failed_runs": 5,
            "window_hours": 24, "current_run_id": str(uuid.uuid4()),
        },
        user_email="system",
    )
    # 12 Laeufe mit 2 Fehlern (ueber Threshold)
    for _ in range(10):
        _write_run(db, job=_JOB, objects_failed=0)
    for _ in range(2):
        _write_run(db, job=_JOB, objects_failed=1)
    db.commit()

    result = _check_error_budget(uuid.uuid4(), _TestSessionLocal)

    # Idempotenz: schon ein Alert → kein zweiter
    assert result is None


def test_error_budget_skipped_when_sample_too_small(db):
    """AC5: Weniger als 10 Laeufe → kein Alert (Min-Sample nicht erreicht)."""
    _JOB = "facilioo_ticket_mirror"
    # Nur 5 Laeufe — alle fehlgeschlagen, aber unter Minimum
    for _ in range(5):
        _write_run(db, job=_JOB, objects_failed=1)
    db.commit()

    result = _check_error_budget(uuid.uuid4(), _TestSessionLocal)

    assert result is None
