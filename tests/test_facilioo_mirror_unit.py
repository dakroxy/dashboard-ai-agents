"""Unit-Tests fuer app/services/facilioo_mirror.py — Story 4.3.

Abdeckung:
  AC1: Lifespan/Idempotenz (start_poller doppelt)
  AC2: Lock-Skip, Unmapped-Object-Tracking, Cross-Object-Move
  AC4: Reconcile INSERT / UPDATE (no-op bei Identitaet) / ARCHIVE
       + Mass-Archive-Schutz, Per-Property-Failure-Isolation
  AC5: Error-Budget-Alert, Idempotenz, Sample-Limit, Run-Counting

Hinweis: ETag-Tests entfallen (Decision 1, 2026-04-30) — Code-Pfad raus.
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
    _reset_properties_cache_for_tests,
    run_facilioo_mirror,
    start_poller,
    stop_poller,
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
        "property_fetch_failures": [],
        "archive_skipped_empty_api": [],
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
    """Setzt Lock, Properties-Cache und Rate-Gate vor jedem Test zurueck."""
    _reset_poller_lock_for_tests()
    _reset_properties_cache_for_tests()
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
    """AC4 / Test 8.8: UPDATE bei Diff; identische zweite Iteration darf KEINE
    UPDATE-Statements absetzen (verifiziert via session.dirty)."""
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

    # Zweite Iteration mit identischer Response → KEINE Updates.
    # session.dirty muss leer sein nach dem Reconcile.
    api_tickets_round2 = [
        {"id": 200, "subject": "Neu", "isFinished": True, "deleted": None,
         "lastModified": "2026-02-01T12:00:00Z"},
        {"id": 201, "subject": "Gleich", "isFinished": False, "deleted": None,
         "lastModified": "2026-01-01T00:00:00Z"},
    ]
    counters2 = _make_counters()
    _reconcile_object_tickets(
        {"object_id": obj.id, "impower_property_id": "22222", "tickets": api_tickets_round2},
        db,
        counters2,
    )
    assert counters2["tickets_updated"] == 0
    assert counters2["tickets_inserted"] == 0
    assert len(db.dirty) == 0


def test_full_pull_archives_missing_ticket(db):
    """AC4: DB-Ticket, das nicht mehr in der API erscheint → is_archived=True."""
    obj = _seed_object(db, short_code="ARC1", impower_property_id="33333")
    # Damit der Mass-Archive-Schutz nicht greift: zweites Ticket bleibt in der
    # API-Response, sodass api_tickets nicht leer ist.
    ticket_gone = _seed_ticket(db, obj=obj, facilioo_id="300", status="open",
                               title="Verschwunden")
    ticket_keep = _seed_ticket(db, obj=obj, facilioo_id="301", status="open",
                               title="Bleibt")

    api_tickets = [
        {"id": 301, "subject": "Bleibt", "isFinished": False, "deleted": None,
         "lastModified": None},
    ]
    bundle = {"object_id": obj.id, "impower_property_id": "33333", "tickets": api_tickets}
    counters = _make_counters()

    _reconcile_object_tickets(bundle, db, counters)
    db.commit()
    db.refresh(ticket_gone)
    db.refresh(ticket_keep)

    assert counters["tickets_archived"] == 1
    assert ticket_gone.is_archived is True
    assert ticket_keep.is_archived is False


def test_mass_archive_skipped_when_api_returns_empty_with_active_db_tickets(db):
    """Mass-Archive-Schutz: leere API-Response + aktive DB-Tickets → kein Archive,
    statt dessen archive_skipped_empty_api-Eintrag im counters."""
    obj = _seed_object(db, short_code="EMPTY1", impower_property_id="44444")
    t = _seed_ticket(db, obj=obj, facilioo_id="400", status="open", title="Aktiv")

    bundle = {"object_id": obj.id, "impower_property_id": "44444", "tickets": []}
    counters = _make_counters()

    _reconcile_object_tickets(bundle, db, counters)
    db.commit()
    db.refresh(t)

    assert counters["tickets_archived"] == 0
    assert t.is_archived is False
    assert len(counters["archive_skipped_empty_api"]) == 1
    assert counters["archive_skipped_empty_api"][0]["active_tickets_count"] == 1


def test_cross_object_ticket_move_updates_object_id(db):
    """Wenn ein Ticket von Object A zu Object B wandert, wird object_id
    umgehaengt statt INSERT (der gegen UNIQUE(facilioo_id) liefe)."""
    obj_a = _seed_object(db, short_code="MOV-A", impower_property_id="55555")
    obj_b = _seed_object(db, short_code="MOV-B", impower_property_id="66666")
    t = _seed_ticket(db, obj=obj_a, facilioo_id="500", status="open",
                     title="Wandert", last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # Object A bekommt KEINEN Ticket-Pull mehr; Object B bekommt das gleiche Ticket.
    # Bei API-Empty fuer A waere normalerweise Mass-Archive-Schutz aktiv —
    # hier: A liefert ein Dummy-Ticket damit Archive-Sweep nicht greift.
    bundle_b = {
        "object_id": obj_b.id,
        "impower_property_id": "66666",
        "tickets": [
            {"id": 500, "subject": "Wandert", "isFinished": False, "deleted": None,
             "lastModified": "2026-02-01T00:00:00Z"},
        ],
    }
    counters = _make_counters()

    _reconcile_object_tickets(bundle_b, db, counters)
    db.commit()
    db.refresh(t)

    # Kein neuer Row, sondern object_id umgehaengt + UPDATE-Counter
    assert counters["tickets_inserted"] == 0
    assert counters["tickets_updated"] == 1
    assert t.object_id == obj_b.id


def test_invalid_ticket_id_skipped(db):
    """Defensive: ticket id=None / leerer String → kein INSERT."""
    obj = _seed_object(db, short_code="DEF1", impower_property_id="77777")
    api_tickets = [
        {"id": None, "subject": "kein id"},
        {"id": "", "subject": "leer"},
        {"id": 700, "subject": "ok", "isFinished": False, "deleted": None,
         "lastModified": "2026-01-01T00:00:00Z"},
    ]
    bundle = {"object_id": obj.id, "impower_property_id": "77777", "tickets": api_tickets}
    counters = _make_counters()
    _reconcile_object_tickets(bundle, db, counters)
    db.commit()
    assert counters["tickets_inserted"] == 1


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
# AC2 + AC4: Unmapped Object
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_pull_unmapped_object_audited_not_inserted(db, monkeypatch):
    """AC2+AC4: Object mit impower_property_id ohne Facilioo-Match → kein
    INSERT, objects_unmapped=1 in sync_finished.details_json."""
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
    details = audit_row.details_json
    assert details.get("objects_unmapped") == 1
    unmapped = details.get("unmapped_objects") or []
    assert len(unmapped) == 1
    assert unmapped[0]["impower_property_id"] == "99999"


# ---------------------------------------------------------------------------
# AC5: Error-Budget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_budget_alert_fires_when_threshold_exceeded(db):
    """AC5: > 10 % Fehlerrate bei >= 10 Laeufen → sync_failed alert=error_budget_exceeded."""
    _JOB = "facilioo_ticket_mirror"
    # 10 OK-Laeufe + 2 Fehler-Laeufe → 16.7 % > 10 %
    for _ in range(10):
        _write_run(db, job=_JOB, objects_failed=0)
    for _ in range(2):
        _write_run(db, job=_JOB, objects_failed=1)
    db.commit()

    result = await _check_error_budget(uuid.uuid4(), _TestSessionLocal)

    assert result is not None
    assert result["alert"] == "error_budget_exceeded"
    assert result["failed_runs"] == 2
    assert result["total_runs"] == 12

    alert_row = db.execute(
        select(AuditLog).where(AuditLog.action == "sync_failed")
    ).scalars().first()
    assert alert_row is not None
    assert alert_row.details_json.get("alert") == "error_budget_exceeded"


@pytest.mark.asyncio
async def test_error_budget_alert_idempotent_within_24h_window(db):
    """AC5: Zweiter Check innerhalb 24 h → kein doppelter Alert (Sub-Query Idempotenz)."""
    _JOB = "facilioo_ticket_mirror"
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
    for _ in range(10):
        _write_run(db, job=_JOB, objects_failed=0)
    for _ in range(2):
        _write_run(db, job=_JOB, objects_failed=1)
    db.commit()

    result = await _check_error_budget(uuid.uuid4(), _TestSessionLocal)

    assert result is None


@pytest.mark.asyncio
async def test_error_budget_skipped_when_sample_too_small(db):
    """AC5: Weniger als min_sample completed Runs → kein Alert."""
    _JOB = "facilioo_ticket_mirror"
    for _ in range(5):
        _write_run(db, job=_JOB, objects_failed=1)
    db.commit()

    result = await _check_error_budget(uuid.uuid4(), _TestSessionLocal)

    assert result is None


@pytest.mark.asyncio
async def test_error_budget_only_completed_runs_count_in_total(db):
    """Run-Counting: nur Runs mit sync_finished/sync_failed-Audit zaehlen.
    Pure sync_started-Eintraege (mid-flight oder gecrashed) deflationieren
    Failure-Rate sonst — Spec-Konformitaet vs. Code-Review-Fix."""
    _JOB = "facilioo_ticket_mirror"
    # 12 completed, alle gescheitert → 100 % Failure-Rate
    for _ in range(12):
        _write_run(db, job=_JOB, objects_failed=1)
    # 50 mid-flight Runs (nur sync_started, NIE finished) → duerfen NICHT in
    # total_runs einfliessen, sonst 12/(12+50)=19% < z. B. extreme Threshold.
    for _ in range(50):
        rid = str(uuid.uuid4())
        audit(
            db, None, "sync_started",
            entity_type="sync_run", entity_id=uuid.UUID(rid),
            details={"job": _JOB, "run_id": rid},
            user_email="system",
        )
    db.commit()

    result = await _check_error_budget(uuid.uuid4(), _TestSessionLocal)

    assert result is not None
    assert result["total_runs"] == 12  # nur die completed Runs
    assert result["failed_runs"] == 12


# ---------------------------------------------------------------------------
# AC1: Lifespan-Idempotenz
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_poller_is_idempotent_against_double_call(monkeypatch):
    """AC1: Zweiter start_poller-Aufruf darf den Task nicht duplizieren."""
    # Lange poll_interval setzen, damit der Loop nicht durchspielt
    monkeypatch.setattr(mirror.settings, "facilioo_poll_interval_seconds", 999.0)
    try:
        await start_poller()
        first_task = mirror._poller_task
        assert first_task is not None
        assert not first_task.done()

        # Zweiter Call: gibt Warning + return, aendert NICHT _poller_task
        await start_poller()
        second_task = mirror._poller_task
        assert second_task is first_task
    finally:
        await stop_poller()
        assert mirror._poller_task is None
