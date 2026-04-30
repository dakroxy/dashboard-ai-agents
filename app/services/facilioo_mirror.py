"""Facilioo-Ticket-Mirror — 1-Min-Poll-Job (Story 4.3).

Spiegelt pro Objekt (Object mit impower_property_id) die Facilioo-Prozesse
(intern als "Tickets" bezeichnet) in die lokale facilioo_tickets-Tabelle.

Kein ETag/Delta-Support (Spike-Befund 2026-04-30) → Full-Pull pro Property
mit lokalem facilioo_last_modified-Vergleich. Pro Lauf werden alle Objects mit
Impower-Mapping durchlaufen; fehlende Tickets werden soft-archiviert.

Lock-Semantik: Lazy-asyncio.Lock (wie steckbrief_impower_mirror). Zweiter
Trigger waehrend laufendem Run → skipped=already_running.

Architektur-Verankerung: CD3 Sync-Orchestrator (architecture.md:284).
Boundary: dieser Code darf ausschliesslich ueber app.services.facilioo zugreifen.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Object
from app.models.facilioo import FaciliooTicket
from app.services import facilioo as facilioo_svc
from app.services.audit import audit
from app.services.facilioo import (
    FaciliooError,
    _get_all_paged,
    _get_properties_cached,
    _make_client,
    derive_status,
    parse_facilioo_datetime,
)
from app.services._sync_common import SyncRunResult, strip_html_error


_logger = logging.getLogger(__name__)

_JOB_NAME = "facilioo_ticket_mirror"
_POLL_RUN_TIMEOUT_SECONDS = 5 * 60  # 5 min — Worst-Case aus Story 4.2 + Diff

# ETag-State (in-memory, kein Persist — nach Restart leer, naechster Tick
# laedt voll, akzeptable ueberzaehlige Iteration, siehe Dev Notes).
_last_etag: str | None = None

# Lazy-Lock + Task (analog steckbrief_impower_mirror.py:77-91).
_poller_lock: asyncio.Lock | None = None
_poller_task: asyncio.Task | None = None


def _get_poller_lock() -> asyncio.Lock:
    global _poller_lock
    if _poller_lock is None:
        _poller_lock = asyncio.Lock()
    return _poller_lock


def _reset_poller_lock_for_tests() -> None:
    """Test-Hook: Lock droppen, damit Lazy-Getter im naechsten Lauf frisch baut."""
    global _poller_lock
    _poller_lock = None


# ---------------------------------------------------------------------------
# Audit-Helper
# ---------------------------------------------------------------------------

def _write_audit(
    *,
    action: str,
    run_id: uuid.UUID,
    details: dict[str, Any],
    db_factory: Any = SessionLocal,
) -> None:
    payload = {"job": _JOB_NAME, "run_id": str(run_id), **details}
    db = db_factory()
    try:
        audit(
            db,
            None,
            action,
            entity_type="sync_run",
            entity_id=run_id,
            details=payload,
            user_email="system",
        )
        db.commit()
    except Exception:
        _logger.exception("audit write failed (action=%s, run_id=%s)", action, run_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fetch: Properties-Mapping + per-Object Ticket-Fetch
# ---------------------------------------------------------------------------

async def _fetch_all_ticket_bundles(
    client: Any,
    db_factory: Any,
    counters: dict[str, Any],
    etag_meta: dict[str, Any],
) -> list[dict]:
    """Ladet Tickets fuer alle Objects mit Facilioo-Mapping.

    Gibt pro Object ein Bundle zurueck:
      {object_id, impower_property_id, tickets: [...]}

    Unmapped Objects (kein passender externalId in Facilioo) werden in
    counters["unmapped_objects"] gesammelt — kein INSERT.
    """
    global _last_etag

    # ETag-Probe (Shortcircuit bei 304 — Facilioo unterstuetzt das Stand
    # 2026-04-30 nicht, aber der Code-Pfad ist vorbereitet fuer spaeteren Support).
    if settings.facilioo_etag_enabled and _last_etag is not None:
        result = await facilioo_svc._api_get(
            client, "/api/properties",
            params={"pageNumber": 1, "pageSize": 1},
            etag=_last_etag,
            return_response=True,
        )
        body, hdrs, status = result
        etag_meta["etag_used"] = True
        if status == 304:
            etag_meta["etag_unchanged"] = True
            return []
        new_etag = (hdrs or {}).get("etag") or (hdrs or {}).get("ETag")
        if new_etag:
            _last_etag = new_etag
            etag_meta["new_etag"] = new_etag

    # Eigenschaften-Cache laden (5-min-TTL — ~288 Calls/Tag statt 1440).
    all_properties = await _get_properties_cached(client)

    # Mapping: impower_property_id (numerischer String) → Facilioo-property-id (int).
    # Haertung analog Spike-Abschnitt "Mapping-Algorithmus":
    #   - leerer/fehlender externalId → skip
    #   - nicht-numerischer externalId → skip
    #   - Duplicate externalId → WARN + ersten Eintrag behalten
    impower_to_facilioo: dict[str, int] = {}
    for prop in all_properties:
        ext = (prop.get("externalId") or "").strip()
        if not ext.isdigit():
            continue
        if ext in impower_to_facilioo:
            _logger.warning(
                "Facilioo duplicate externalId=%s (property_id=%s) — skipped",
                ext, prop.get("id"),
            )
            continue
        impower_to_facilioo[ext] = prop["id"]

    # Objects aus DB laden.
    db = db_factory()
    try:
        objects: list[Object] = list(
            db.execute(
                select(Object).where(Object.impower_property_id.is_not(None))
            ).scalars().all()
        )
    finally:
        db.close()

    bundles: list[dict] = []
    for obj in objects:
        pid_str = str(obj.impower_property_id)
        facilioo_id = impower_to_facilioo.get(pid_str)
        if facilioo_id is None:
            counters["unmapped_objects"].append({
                "object_id": str(obj.id),
                "impower_property_id": pid_str,
            })
            continue
        tickets = await _get_all_paged(
            client, f"/api/properties/{facilioo_id}/processes"
        )
        bundles.append({
            "object_id": obj.id,
            "impower_property_id": pid_str,
            "tickets": tickets,
        })

    # Nach erfolgreicher Full-Pull-Iteration: ETag fuer naechsten Lauf captur:
    # Falls Facilioo irgendwann ETag unterstuetzt, liegt er im Response-Header.
    if settings.facilioo_etag_enabled and etag_meta.get("new_etag") is None:
        try:
            _, hdrs, status = await facilioo_svc._api_get(
                client, "/api/properties",
                params={"pageNumber": 1, "pageSize": 1},
                return_response=True,
            )
            if status == 200:
                new_etag = (hdrs or {}).get("etag") or (hdrs or {}).get("ETag")
                if new_etag:
                    _last_etag = new_etag
                    etag_meta["new_etag"] = new_etag
        except Exception:
            pass

    return bundles


# ---------------------------------------------------------------------------
# Reconcile: Diff + Upsert + Archive pro Object
# ---------------------------------------------------------------------------

def _reconcile_object_tickets(
    bundle: dict,
    db: Session,
    counters: dict[str, Any],
) -> None:
    """INSERT neuer, UPDATE geaenderter, ARCHIVE fehlender Tickets fuer 1 Object.

    Two-Phase-Sicherheit: Archivierung (SET is_archived=True) erfolgt nur,
    wenn der komplette Ticket-Pull fuer dieses Object erfolgreich war.
    Partieller Pull (Exception) wird vom Aufrufer als Fehler behandelt.
    """
    object_id: uuid.UUID = bundle["object_id"]
    api_tickets: list[dict] = bundle["tickets"]

    # Bestehende DB-Tickets fuer dieses Object laden.
    existing: dict[str, FaciliooTicket] = {
        t.facilioo_id: t
        for t in db.execute(
            select(FaciliooTicket).where(FaciliooTicket.object_id == object_id)
        ).scalars().all()
    }

    api_facilioo_ids: set[str] = set()

    for raw in api_tickets:
        facilioo_id = str(raw.get("id", ""))
        if not facilioo_id or facilioo_id == "None":
            continue
        api_facilioo_ids.add(facilioo_id)

        new_status = derive_status(raw)
        new_title = raw.get("subject") or ""
        new_is_archived = new_status == "deleted"
        new_last_modified = parse_facilioo_datetime(raw.get("lastModified"))

        ticket = existing.get(facilioo_id)
        if ticket is None:
            # INSERT
            ticket = FaciliooTicket(
                id=uuid.uuid4(),
                object_id=object_id,
                facilioo_id=facilioo_id,
                status=new_status,
                title=new_title,
                raw_payload=raw,
                is_archived=new_is_archived,
                facilioo_last_modified=new_last_modified,
            )
            db.add(ticket)
            counters["tickets_inserted"] += 1
        else:
            # UPDATE: nur wenn lastModified neuer als gespeicherter Wert
            # ODER wenn gespeicherter Wert fehlt (Legacy-Row ohne lastModified).
            should_update = (
                ticket.facilioo_last_modified is None
                or new_last_modified is None
                or (
                    new_last_modified is not None
                    and ticket.facilioo_last_modified is not None
                    and new_last_modified > _aware(ticket.facilioo_last_modified)
                )
            )
            if should_update and (
                ticket.status != new_status
                or ticket.title != new_title
                or ticket.is_archived != new_is_archived
                or ticket.facilioo_last_modified != new_last_modified
            ):
                ticket.status = new_status
                ticket.title = new_title
                ticket.raw_payload = raw
                ticket.is_archived = new_is_archived
                ticket.facilioo_last_modified = new_last_modified
                counters["tickets_updated"] += 1
            elif ticket.is_archived and not new_is_archived:
                # Re-Aktivierung: Ticket war archiviert, taucht wieder in API auf.
                ticket.is_archived = False
                ticket.status = new_status
                ticket.title = new_title
                ticket.raw_payload = raw
                ticket.facilioo_last_modified = new_last_modified
                counters["tickets_updated"] += 1

    # ARCHIVE: DB-Tickets, die nicht mehr in der API-Response sind.
    # Nur wenn Pull vollstaendig war (Two-Phase: Exception-Pfad archiviert nicht).
    for facilioo_id, ticket in existing.items():
        if facilioo_id not in api_facilioo_ids and not ticket.is_archived:
            ticket.is_archived = True
            counters["tickets_archived"] += 1


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Error-Budget (AC5)
# ---------------------------------------------------------------------------

def _check_error_budget(run_id: uuid.UUID, db_factory: Any) -> dict | None:
    """Prueft ob das Error-Budget in den letzten 24 h ueberschritten wurde.

    Query auf audit_log aggregiert per run_id. Threshold: > 10 % (default)
    fehlgeschlagene Laeufe bei N >= 10 Laeufen. Idempotenz: in den letzten
    24 h schon ein alert=error_budget_exceeded fuer diesen Job → kein zweiter.

    Fehler in dieser Funktion werden geloggt und nicht propagiert (Risiko 6:
    der Loop darf nicht sterben wenn die Budget-Query fehlschlaegt).
    """
    from app.models import AuditLog
    from sqlalchemy import text as sa_text

    window_hours = settings.facilioo_error_budget_window_hours
    threshold = settings.facilioo_error_budget_threshold
    min_sample = settings.facilioo_error_budget_min_sample

    try:
        db = db_factory()
        try:
            # SQLite (Tests) und Postgres unterstuetzen JSON-Extraktion unterschiedlich.
            # Wir laden die relevanten Rows und aggregieren in Python.
            from datetime import timedelta
            window_start = datetime.now(tz=timezone.utc) - timedelta(hours=window_hours)

            rows = db.execute(
                select(AuditLog).where(
                    AuditLog.action.in_(("sync_started", "sync_finished", "sync_failed")),
                    AuditLog.created_at >= window_start,
                )
            ).scalars().all()

            # Pro run_id aggregieren.
            runs: dict[str, dict] = {}
            for row in rows:
                details = row.details_json or {}
                if details.get("job") != _JOB_NAME:
                    continue
                rid = details.get("run_id")
                if not rid:
                    continue
                if rid not in runs:
                    runs[rid] = {"fetch_failed": False, "items_failed": False, "sync_failed": False}
                if row.action == "sync_finished":
                    if details.get("fetch_failed"):
                        runs[rid]["fetch_failed"] = True
                    if (details.get("objects_failed") or 0) > 0:
                        runs[rid]["items_failed"] = True
                elif row.action == "sync_failed" and details.get("alert") != "error_budget_exceeded":
                    runs[rid]["sync_failed"] = True

            total_runs = len(runs)
            if total_runs < min_sample:
                return None

            failed_runs = sum(
                1 for r in runs.values()
                if r["fetch_failed"] or r["items_failed"] or r["sync_failed"]
            )
            failure_rate = failed_runs / total_runs

            if failure_rate <= threshold:
                return None

            # Idempotenz: schon ein Alert in den letzten 24 h?
            existing_alert = db.execute(
                select(AuditLog).where(
                    AuditLog.action == "sync_failed",
                    AuditLog.created_at >= window_start,
                )
            ).scalars().all()
            for row in existing_alert:
                details = row.details_json or {}
                if (
                    details.get("job") == _JOB_NAME
                    and details.get("alert") == "error_budget_exceeded"
                ):
                    return None  # Schon ein Alert vorhanden.

            # Alert schreiben.
            alert_details = {
                "alert": "error_budget_exceeded",
                "failure_rate": round(failure_rate, 4),
                "total_runs": total_runs,
                "failed_runs": failed_runs,
                "window_hours": window_hours,
                "current_run_id": str(run_id),
            }
            audit(
                db,
                None,
                "sync_failed",
                entity_type="sync_run",
                entity_id=None,
                details={"job": _JOB_NAME, "run_id": str(run_id), **alert_details},
                user_email="system",
            )
            db.commit()
            return alert_details
        finally:
            db.close()
    except Exception:
        _logger.exception("error_budget check failed")
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_facilioo_mirror(
    db_factory: Any = SessionLocal,
    http_client_factory: Any = _make_client,
) -> SyncRunResult:
    """Fuehrt einen kompletten Facilioo-Ticket-Mirror-Lauf aus.

    Baut die Properties-Mapping-Tabelle (externalId → Facilioo-ID), laedt
    Tickets pro Object und spiegelt INSERT/UPDATE/ARCHIVE in facilioo_tickets.

    Hinweis: Wird als asyncio-Task vom 1-Min-Poller aufgerufen. Bei Doppel-
    Trigger (laufender Lauf) wird sofort skipped zurueckgegeben.

    Doppellauf bei uvicorn --reload (Dev): zwei Worker pollen parallel.
    Der asyncio.Lock schuetzt nur innerhalb eines Processes. Akzeptiert fuer
    v1 (Elestio Single-Worker-Prod).
    """
    lock = _get_poller_lock()
    run_id = uuid.uuid4()
    started_at = datetime.now(tz=timezone.utc)
    result = SyncRunResult(job_name=_JOB_NAME, run_id=run_id, started_at=started_at)

    # --- Lock-Check (atomar in Single-Thread-asyncio) ---
    if lock.locked():
        result.skipped = True
        result.skip_reason = "already_running"
        _write_audit(
            action="sync_started",
            run_id=run_id,
            details={"skipped": True, "skip_reason": "already_running"},
            db_factory=db_factory,
        )
        result.finished_at = datetime.now(tz=timezone.utc)
        return result

    await lock.acquire()
    try:
        # --- sync_started ---
        _write_audit(
            action="sync_started",
            run_id=run_id,
            details={"started_at": started_at.isoformat()},
            db_factory=db_factory,
        )

        counters: dict[str, Any] = {
            "tickets_inserted": 0,
            "tickets_updated": 0,
            "tickets_archived": 0,
            "unmapped_objects": [],
        }
        etag_meta: dict[str, Any] = {
            "etag_used": False,
            "etag_unchanged": False,
            "new_etag": None,
        }

        # --- Fetch-Phase ---
        bundles: list[dict] = []
        try:
            async with http_client_factory() as client:
                bundles = await _fetch_all_ticket_bundles(
                    client, db_factory, counters, etag_meta
                )
        except FaciliooError as exc:
            err_msg = strip_html_error(f"{type(exc).__name__}: {exc}")
            result.fetch_failed = True
            result.items_failed = 1
            _write_audit(
                action="sync_failed",
                run_id=run_id,
                details={"phase": "fetch", "error": err_msg},
                db_factory=db_factory,
            )
            result.finished_at = datetime.now(tz=timezone.utc)
            _write_finish_audit(result, run_id, counters, etag_meta, db_factory)
            return result
        except Exception as exc:
            err_msg = strip_html_error(f"{type(exc).__name__}: {exc}")
            result.fetch_failed = True
            result.items_failed = 1
            _write_audit(
                action="sync_failed",
                run_id=run_id,
                details={"phase": "fetch", "error": err_msg},
                db_factory=db_factory,
            )
            result.finished_at = datetime.now(tz=timezone.utc)
            _write_finish_audit(result, run_id, counters, etag_meta, db_factory)
            return result

        # ETag shortcircuit: nichts zu tun.
        if etag_meta.get("etag_unchanged"):
            result.finished_at = datetime.now(tz=timezone.utc)
            _write_finish_audit(result, run_id, counters, etag_meta, db_factory)
            return result

        result.items_total = len(bundles)

        # --- Reconcile-Phase (pro Object) ---
        run_start_wall = time.monotonic()
        for bundle in bundles:
            db = db_factory()
            try:
                _reconcile_object_tickets(bundle, db, counters)
                db.commit()
                result.items_ok += 1
            except Exception as exc:
                db.rollback()
                err_msg = strip_html_error(f"{type(exc).__name__}: {exc}")
                result.items_failed += 1
                _write_audit(
                    action="sync_failed",
                    run_id=run_id,
                    details={
                        "phase": "reconcile",
                        "impower_property_id": bundle.get("impower_property_id"),
                        "error": err_msg,
                    },
                    db_factory=db_factory,
                )
            finally:
                db.close()

        elapsed = time.monotonic() - run_start_wall
        if elapsed > 50:
            _logger.warning(
                "facilioo_mirror: Lauf dauerte %.1f s (Watchdog-Schwelle 50 s)",
                elapsed,
            )

        result.finished_at = datetime.now(tz=timezone.utc)
        _write_finish_audit(result, run_id, counters, etag_meta, db_factory)

        # --- Error-Budget (nach Abschluss, Fehler werden nicht propagiert) ---
        _check_error_budget(run_id, db_factory)

        return result
    finally:
        lock.release()


def _write_finish_audit(
    result: SyncRunResult,
    run_id: uuid.UUID,
    counters: dict[str, Any],
    etag_meta: dict[str, Any],
    db_factory: Any,
) -> None:
    unmapped = counters.get("unmapped_objects", [])
    _write_audit(
        action="sync_finished",
        run_id=run_id,
        details={
            "started_at": result.started_at.isoformat(),
            "finished_at": (
                result.finished_at.isoformat() if result.finished_at else None
            ),
            "objects_total": result.items_total,
            "objects_ok": result.items_ok,
            "objects_failed": result.items_failed,
            "fetch_failed": result.fetch_failed,
            "tickets_inserted": counters.get("tickets_inserted", 0),
            "tickets_updated": counters.get("tickets_updated", 0),
            "tickets_archived": counters.get("tickets_archived", 0),
            "tickets_unmapped": len(unmapped),
            "unmapped_tickets": unmapped[:50],
            "etag_used": etag_meta.get("etag_used", False),
            "etag_unchanged": etag_meta.get("etag_unchanged", False),
        },
        db_factory=db_factory,
    )


# ---------------------------------------------------------------------------
# Poller-Lifecycle (Lifespan-Integration)
# ---------------------------------------------------------------------------

async def _poll_loop() -> None:
    """Dauerschleife: alle `facilioo_poll_interval_seconds` run_facilioo_mirror aufrufen."""
    while True:
        await asyncio.sleep(settings.facilioo_poll_interval_seconds)
        try:
            await asyncio.wait_for(
                run_facilioo_mirror(),
                timeout=_POLL_RUN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _logger.error(
                "facilioo_mirror_poller: run exceeded %s s timeout",
                _POLL_RUN_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("facilioo_mirror_poller: run failed")


async def start_poller() -> None:
    """Startet den 1-Min-Poll-Loop als asyncio.Task (idempotent).

    Zweiter Aufruf im selben Process gibt Warnung + kehrt sofort zurueck.
    Hinweis: bei uvicorn --reload starten zwei Worker — der Lock ist pro-Process
    und schuetzt nicht ueber Worker hinweg.
    """
    global _poller_task
    if _poller_task is not None and not _poller_task.done():
        _logger.warning(
            "facilioo_mirror_poller: start_poller() bereits aktiv — doppelter Aufruf ignoriert"
        )
        return
    _poller_task = asyncio.create_task(
        _poll_loop(), name="facilioo_ticket_mirror_poller"
    )
    _logger.info("facilioo_mirror_poller: gestartet (interval=%ss)", settings.facilioo_poll_interval_seconds)


async def stop_poller() -> None:
    """Bricht den Poll-Loop-Task sauber ab (Lifespan-finally)."""
    global _poller_task
    if _poller_task is None:
        return
    _poller_task.cancel()
    try:
        await _poller_task
    except asyncio.CancelledError:
        pass
    finally:
        _poller_task = None
