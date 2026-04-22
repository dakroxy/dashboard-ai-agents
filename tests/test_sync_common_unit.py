"""Unit-Tests fuer _sync_common: strip_html_error, next_daily_run_at, run_sync_job."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models import AuditLog
from app.services._sync_common import (
    ReconcileStats,
    run_sync_job,
    next_daily_run_at,
    strip_html_error,
)
from tests.conftest import _TestSessionLocal


_BERLIN = ZoneInfo("Europe/Berlin")


# ---------------------------------------------------------------------------
# strip_html_error
# ---------------------------------------------------------------------------

def test_strip_html_error_removes_tags():
    assert strip_html_error("<html><body>Fehler <b>503</b></body></html>") == (
        "Fehler 503"
    )


def test_strip_html_error_truncates():
    long = "x" * 1000
    assert len(strip_html_error(long, limit=200)) == 200


def test_strip_html_error_none_returns_empty():
    assert strip_html_error(None) == ""


# ---------------------------------------------------------------------------
# next_daily_run_at
# ---------------------------------------------------------------------------

def test_next_daily_run_at_same_day_future():
    now = datetime(2026, 5, 12, 1, 0, tzinfo=_BERLIN)
    result = next_daily_run_at(now, hour=2, minute=30, tz=_BERLIN)
    assert result.date() == now.date()
    assert result.hour == 2
    assert result.minute == 30


def test_next_daily_run_at_past_rolls_to_tomorrow():
    now = datetime(2026, 5, 12, 14, 0, tzinfo=_BERLIN)
    result = next_daily_run_at(now, hour=2, minute=30, tz=_BERLIN)
    assert result.date() == (now + timedelta(days=1)).date()
    assert result.hour == 2
    assert result.minute == 30


def test_next_daily_run_at_exact_boundary_rolls_to_tomorrow():
    # Bei now == 02:30:00.001 wuerde heute greifen sein, 02:30 gleich ist past.
    now = datetime(2026, 5, 12, 2, 30, 0, 1_000, tzinfo=_BERLIN)
    result = next_daily_run_at(now, hour=2, minute=30, tz=_BERLIN)
    assert result.date() == (now + timedelta(days=1)).date()


def test_next_daily_run_at_accepts_utc_input():
    now_utc = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)  # = 02:00 Berlin
    result = next_daily_run_at(now_utc, hour=2, minute=30, tz=_BERLIN)
    assert result.tzinfo == _BERLIN
    assert result.hour == 2 and result.minute == 30


def test_next_daily_run_at_dst_spring_forward_normalizes():
    # Am letzten Maerz-Sonntag springt die Uhr 02:00 → 03:00; 02:30 existiert nicht.
    # astimezone-Roundtrip muss einen gueltigen Instant zurueckgeben.
    now = datetime(2026, 3, 28, 14, 0, tzinfo=_BERLIN)  # Samstag vor Umstellung
    result = next_daily_run_at(now, hour=2, minute=30, tz=_BERLIN)
    assert result.tzinfo == _BERLIN
    # Darf nicht crashen, Rueckgabe muss in der Zukunft liegen.
    assert result > now


# ---------------------------------------------------------------------------
# run_sync_job
# ---------------------------------------------------------------------------

def _make_stats(**kw) -> ReconcileStats:
    return ReconcileStats(**kw)


def test_run_sync_job_happy_path_counts_items(db):
    async def fetch():
        return ["a", "b", "c"]

    async def reconcile(item, session):
        return _make_stats(fields_updated=2)

    lock = asyncio.Lock()
    def factory():
        return _TestSessionLocal()

    result = asyncio.run(
        run_sync_job(
            job_name="test_job",
            fetch_items=fetch,
            reconcile_item=reconcile,
            db_factory=factory,
            lock=lock,
        )
    )
    assert result.items_ok == 3
    assert result.items_failed == 0
    assert result.fields_updated == 6
    assert result.finished_at is not None
    assert result.skipped is False

    db.expire_all()
    actions = [a.action for a in db.query(AuditLog).order_by(AuditLog.created_at).all()]
    assert "sync_started" in actions
    assert "sync_finished" in actions
    assert "sync_failed" not in actions


def test_run_sync_job_item_error_continues(db):
    async def fetch():
        return ["ok1", "fail", "ok2"]

    async def reconcile(item, session):
        if item == "fail":
            raise RuntimeError("boom")
        return _make_stats()

    lock = asyncio.Lock()
    def factory():
        return _TestSessionLocal()

    result = asyncio.run(
        run_sync_job(
            job_name="test_job",
            fetch_items=fetch,
            reconcile_item=reconcile,
            db_factory=factory,
            lock=lock,
            item_identity=lambda x: x,
        )
    )
    assert result.items_ok == 2
    assert result.items_failed == 1
    assert len(result.errors) == 1
    assert result.errors[0]["item_id"] == "fail"

    db.expire_all()
    failed = db.query(AuditLog).filter(AuditLog.action == "sync_failed").all()
    assert len(failed) == 1


def test_run_sync_job_lock_skips_second_call(db):
    lock = asyncio.Lock()

    async def fetch():
        return ["x"]

    async def reconcile(item, session):
        return _make_stats()

    def factory():
        return _TestSessionLocal()

    async def run_both():
        # Lock schon vorher halten, damit run_sync_job den Skip-Pfad nimmt.
        await lock.acquire()
        try:
            res = await run_sync_job(
                job_name="test_job",
                fetch_items=fetch,
                reconcile_item=reconcile,
                db_factory=factory,
                lock=lock,
            )
        finally:
            lock.release()
        return res

    result = asyncio.run(run_both())
    assert result.skipped is True
    assert result.skip_reason == "already_running"
    assert result.items_ok == 0

    db.expire_all()
    started_rows = (
        db.query(AuditLog).filter(AuditLog.action == "sync_started").all()
    )
    assert len(started_rows) == 1
    assert (started_rows[0].details_json or {}).get("skipped") is True
    finished_rows = (
        db.query(AuditLog).filter(AuditLog.action == "sync_finished").all()
    )
    assert len(finished_rows) == 0
