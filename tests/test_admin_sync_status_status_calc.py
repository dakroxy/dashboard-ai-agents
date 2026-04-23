"""Unit-Tests fuer _load_recent_mirror_runs: Status-Kalkulation pro Run.

Aus audit_log-Rows leitet der Helper pro run_id einen Status ab:
  * "ok"       — sync_finished ohne failures
  * "partial"  — sync_finished mit objects_failed > 0
  * "failed"   — sync_finished mit fetch_failed=True
  * "running"  — sync_started ohne sync_finished, nicht stale
  * "crashed"  — sync_started ohne sync_finished, > _MIRROR_STALE_RUNNING_AFTER_SECONDS
  * "skipped"  — sync_started mit skipped=True

Diese Klassifikation treibt die Badges + Color-Coding in
admin/sync_status.html. Ohne Unit-Tests wuerden Regressionen (z. B. Fall
"sync_finished mit fetch_failed gilt als ok") erst in der UI auffallen.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.routers.admin import (
    _MIRROR_STALE_RUNNING_AFTER_SECONDS,
    _load_recent_mirror_runs,
)
from app.services.audit import audit


_JOB = "steckbrief_impower_mirror"


def _write_run(
    db,
    *,
    run_id: str,
    started_details: dict | None = None,
    finished_details: dict | None = None,
    failures: list[dict] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Schreibt pro Run die drei Audit-Typen. `started_at`/`finished_at`
    werden NACH commit ueberschrieben, falls gesetzt — damit koennen wir
    "stale running"-Cases deterministisch simulieren.
    """
    from app.models import AuditLog

    run_uuid = uuid.UUID(run_id)
    started = audit(
        db,
        None,
        "sync_started",
        entity_type="sync_run",
        entity_id=run_uuid,
        details={"job": _JOB, "run_id": run_id, **(started_details or {})},
        user_email="system",
    )
    db.flush()
    if started_at is not None:
        started.created_at = started_at
    for f in failures or []:
        audit(
            db,
            None,
            "sync_failed",
            entity_type="sync_run",
            entity_id=run_uuid,
            details={"job": _JOB, "run_id": run_id, **f},
            user_email="system",
        )
    if finished_details is not None:
        finished = audit(
            db,
            None,
            "sync_finished",
            entity_type="sync_run",
            entity_id=run_uuid,
            details={"job": _JOB, "run_id": run_id, **finished_details},
            user_email="system",
        )
        db.flush()
        if finished_at is not None:
            finished.created_at = finished_at
    db.commit()


def test_status_ok_when_finished_without_failures(db):
    run_id = str(uuid.uuid4())
    _write_run(
        db,
        run_id=run_id,
        started_details={"started_at": "2026-04-22T02:30:00+00:00"},
        finished_details={
            "objects_ok": 50,
            "objects_failed": 0,
            "fetch_failed": False,
            "fields_updated": 120,
        },
    )
    runs = _load_recent_mirror_runs(db, job_name=_JOB)
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert runs[0]["counters"].get("fields_updated") == 120


def test_status_partial_when_objects_failed_positive(db):
    run_id = str(uuid.uuid4())
    _write_run(
        db,
        run_id=run_id,
        started_details={},
        failures=[
            {
                "item_id": "222",
                "impower_property_id": "222",
                "phase": "cluster_6",
                "error": "HTTP 503 Gateway",
            }
        ],
        finished_details={
            "objects_ok": 49,
            "objects_failed": 1,
            "fetch_failed": False,
        },
    )
    runs = _load_recent_mirror_runs(db, job_name=_JOB)
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "partial"
    assert len(run["failures"]) == 1
    fail = run["failures"][0]
    assert fail["phase"] == "cluster_6"
    assert fail["impower_property_id"] == "222"


def test_status_failed_when_fetch_failed_flag_set(db):
    run_id = str(uuid.uuid4())
    _write_run(
        db,
        run_id=run_id,
        started_details={},
        failures=[{"phase": "fetch", "error": "Connection refused"}],
        finished_details={
            "objects_ok": 0,
            "objects_failed": 1,
            "fetch_failed": True,
        },
    )
    runs = _load_recent_mirror_runs(db, job_name=_JOB)
    assert runs[0]["status"] == "failed"


def test_status_skipped_when_started_has_skipped_flag(db):
    """Zweiter Trigger bei laufendem Lauf: nur sync_started mit
    skipped=True, kein sync_finished. Status muss "skipped" sein.
    """
    run_id = str(uuid.uuid4())
    _write_run(
        db,
        run_id=run_id,
        started_details={"skipped": True, "skip_reason": "already_running"},
    )
    runs = _load_recent_mirror_runs(db, job_name=_JOB)
    assert runs[0]["status"] == "skipped"
    assert runs[0]["skip_reason"] == "already_running"


def test_status_running_when_started_without_finished_and_fresh(db):
    run_id = str(uuid.uuid4())
    _write_run(
        db,
        run_id=run_id,
        started_details={"started_at": datetime.now(tz=timezone.utc).isoformat()},
        # Kein sync_finished → running.
    )
    runs = _load_recent_mirror_runs(db, job_name=_JOB)
    assert runs[0]["status"] == "running"


def test_status_crashed_when_started_stale_without_finished(db):
    """sync_started > _MIRROR_STALE_RUNNING_AFTER_SECONDS alt + kein
    sync_finished → der Lauf hat wahrscheinlich gecrashed / Container wurde
    recycled. UI zeigt "crashed" statt ewig "running".
    """
    run_id = str(uuid.uuid4())
    stale_started_at = datetime.now(tz=timezone.utc) - timedelta(
        seconds=_MIRROR_STALE_RUNNING_AFTER_SECONDS + 120
    )
    _write_run(
        db,
        run_id=run_id,
        started_details={"started_at": stale_started_at.isoformat()},
        started_at=stale_started_at,
    )
    runs = _load_recent_mirror_runs(db, job_name=_JOB)
    assert runs[0]["status"] == "crashed"


def test_limit_caps_history_to_requested_count(db):
    """Wenn mehr als `limit` Laeufe existieren, werden nur die neuesten
    geliefert — sonst platzt die Admin-UI bei langer Historie.
    """
    base = datetime.now(tz=timezone.utc) - timedelta(days=20)
    for i in range(5):
        rid = str(uuid.uuid4())
        started_at = base + timedelta(days=i)
        finished_at = started_at + timedelta(seconds=10)
        _write_run(
            db,
            run_id=rid,
            started_details={"started_at": started_at.isoformat()},
            finished_details={
                "objects_ok": i,
                "objects_failed": 0,
                "fetch_failed": False,
            },
            started_at=started_at,
            finished_at=finished_at,
        )
    runs = _load_recent_mirror_runs(db, job_name=_JOB, limit=3)
    assert len(runs) == 3
    # Neueste zuerst: letzte drei objects_ok-Werte sind 4, 3, 2.
    oks = [r["counters"].get("objects_ok") for r in runs]
    assert oks == [4, 3, 2]
