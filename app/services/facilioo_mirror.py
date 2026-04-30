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
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import AuditLog, Object
from app.models.facilioo import FaciliooTicket
from app.services._sync_common import SyncRunResult, strip_html_error
from app.services.audit import audit
from app.services.facilioo import (
    FaciliooError,
    _get_all_paged,
    _make_client,
    derive_status,
    parse_facilioo_datetime,
)


_logger = logging.getLogger(__name__)

_JOB_NAME = "facilioo_ticket_mirror"
_POLL_RUN_TIMEOUT_SECONDS = 5 * 60  # 5 min — Worst-Case aus Story 4.2 + Diff

# Lazy-Lock + Task (analog steckbrief_impower_mirror.py:77-91).
_poller_lock: asyncio.Lock | None = None
_poller_task: asyncio.Task | None = None

# Properties-Cache (TTL 5 min) — reduziert /api/properties-Calls von 1440/Tag
# auf ~288/Tag. Boundary-konform hier (im Mirror-Modul) statt in facilioo.py.
_properties_cache: list[dict] | None = None
_properties_cache_ts: float = 0.0
_PROPERTIES_CACHE_TTL: float = 5 * 60.0


def _get_poller_lock() -> asyncio.Lock:
    global _poller_lock
    if _poller_lock is None:
        _poller_lock = asyncio.Lock()
    return _poller_lock


def _reset_poller_lock_for_tests() -> None:
    """Test-Hook: Lock droppen, damit Lazy-Getter im naechsten Lauf frisch baut."""
    global _poller_lock
    _poller_lock = None


def _reset_properties_cache_for_tests() -> None:
    """Test-Hook: Properties-Cache leeren."""
    global _properties_cache, _properties_cache_ts
    _properties_cache = None
    _properties_cache_ts = 0.0


async def _get_properties_cached(client: Any) -> list[dict]:
    """Gibt gecachte Facilioo-Property-Liste zurueck (TTL 5 min)."""
    global _properties_cache, _properties_cache_ts
    now = time.monotonic()
    if _properties_cache is not None and (now - _properties_cache_ts) < _PROPERTIES_CACHE_TTL:
        return _properties_cache
    props = await _get_all_paged(client, "/api/properties")
    _properties_cache = props
    _properties_cache_ts = time.monotonic()
    return props


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
        # Session in invalid-state → rollback bevor close, sonst risk Connection-
        # Pool-Reuse-Fehler bei naechstem checkout.
        try:
            db.rollback()
        except Exception:
            pass
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
) -> list[dict]:
    """Ladet Tickets fuer alle Objects mit Facilioo-Mapping.

    Gibt pro Object ein Bundle zurueck:
      {object_id, impower_property_id, tickets: [...]}

    Unmapped Objects (kein passender externalId in Facilioo) werden in
    counters["unmapped_objects"] gesammelt — kein Ticket-Fetch.
    Doppelte impower_property_ids in der DB werden geloggt + dedupliziert
    (zweites Object wird uebersprungen, sonst UNIQUE-Konflikt auf facilioo_id).
    Per-Property-Fehler im Ticket-Fetch isolieren wir, damit eine kaputte
    Property nicht den ganzen Tick killt.
    """
    # Eigenschaften-Cache laden (5-min-TTL — ~288 Calls/Tag statt 1440).
    all_properties = await _get_properties_cached(client)

    # Mapping: impower_property_id (numerischer String) → Facilioo-property-id (int).
    # Defensive Validierung:
    #   - prop ist dict
    #   - prop["id"] ist int
    #   - externalId ist non-empty + nur Ziffern
    #   - Duplicate externalId → WARN + ersten Eintrag behalten
    impower_to_facilioo: dict[str, int] = {}
    for prop in all_properties:
        if not isinstance(prop, dict):
            continue
        pid = prop.get("id")
        if not isinstance(pid, int):
            continue
        ext = (prop.get("externalId") or "").strip()
        if not ext.isdigit():
            continue
        if ext in impower_to_facilioo:
            _logger.warning(
                "Facilioo duplicate externalId=%s (property_id=%s) — skipped",
                ext, pid,
            )
            continue
        impower_to_facilioo[ext] = pid

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
    seen_pids: set[str] = set()  # Dedup gegen UNIQUE-Konflikte auf facilioo_id
    for obj in objects:
        pid_str = str(obj.impower_property_id)
        if pid_str in seen_pids:
            _logger.warning(
                "Object %s teilt impower_property_id=%s mit fruehrer Object-Row — skipped",
                obj.id, pid_str,
            )
            continue
        seen_pids.add(pid_str)
        facilioo_id = impower_to_facilioo.get(pid_str)
        if facilioo_id is None:
            counters["unmapped_objects"].append({
                "object_id": str(obj.id),
                "impower_property_id": pid_str,
            })
            continue
        try:
            tickets = await _get_all_paged(
                client, f"/api/properties/{facilioo_id}/processes"
            )
        except FaciliooError as exc:
            # Per-Property-Failure-Isolation: kaputte Property kippt nicht den
            # gesamten Tick. Audit + weiter zur naechsten Property.
            err_msg = strip_html_error(f"{type(exc).__name__}: {exc}")
            counters["property_fetch_failures"].append({
                "object_id": str(obj.id),
                "impower_property_id": pid_str,
                "error": err_msg,
            })
            continue
        bundles.append({
            "object_id": obj.id,
            "impower_property_id": pid_str,
            "tickets": tickets,
        })

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

    Two-Phase-Sicherheit:
      - Archivierung (SET is_archived=True) erfolgt nur, wenn der API-Pull
        Tickets geliefert hat. Bei API-Empty-Response trotz aktiver DB-Tickets
        skipt der Archive-Sweep (Mass-Archive-Schutz, audit anomaly).
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
    active_existing_count = sum(1 for t in existing.values() if not t.is_archived)

    api_facilioo_ids: set[str] = set()

    for raw in api_tickets:
        # Defensive: id muss int oder non-empty-String sein, sonst skip.
        raw_id = raw.get("id")
        if not isinstance(raw_id, (int, str)):
            continue
        facilioo_id = str(raw_id).strip()
        if not facilioo_id or facilioo_id == "None":
            continue
        api_facilioo_ids.add(facilioo_id)

        new_status = derive_status(raw)
        # Defensive: subject coerce zu String (Facilioo-DTO-Drift-Schutz).
        new_title = str(raw.get("subject") or "")
        new_is_archived = new_status == "deleted"
        new_last_modified = parse_facilioo_datetime(raw.get("lastModified"))

        ticket = existing.get(facilioo_id)
        if ticket is None:
            # Globaler Cross-Object-Lookup: ein Ticket kann von einer Property
            # zu einer anderen wandern (z. B. Rebooking). UNIQUE(facilioo_id)
            # wuerde den blinden INSERT killen — wir holen das Ticket und
            # haengen es an das neue Object.
            ticket = db.execute(
                select(FaciliooTicket).where(
                    FaciliooTicket.facilioo_id == facilioo_id
                )
            ).scalars().first()
            if ticket is not None:
                ticket.object_id = object_id

        if ticket is None:
            # INSERT (echtes neues Ticket, weder lokal-pro-Object noch global)
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
            continue

        # UPDATE — semantischer Diff (status/title/is_archived) ODER
        # progressed lastModified. Beide Pfade muenden in dieselbe
        # Update-Logik (Re-Aktivierung wird mit-erfasst, kein elif-Toter-Pfad).
        new_lm_aware = _aware(new_last_modified) if new_last_modified is not None else None
        old_lm_aware = _aware(ticket.facilioo_last_modified) if ticket.facilioo_last_modified is not None else None

        # P-D4: Wenn neuer lastModified None ist (Parser-Fehler, Drift),
        # progressed=False — sonst wuerde das Ticket bei jedem Tick re-written.
        lastmod_progressed = new_lm_aware is not None and (
            old_lm_aware is None or new_lm_aware > old_lm_aware
        )
        semantic_changed = (
            ticket.status != new_status
            or ticket.title != new_title
            or ticket.is_archived != new_is_archived
        )

        if lastmod_progressed or semantic_changed:
            ticket.status = new_status
            ticket.title = new_title
            ticket.raw_payload = raw
            ticket.is_archived = new_is_archived
            if new_last_modified is not None:
                ticket.facilioo_last_modified = new_last_modified
            counters["tickets_updated"] += 1

    # ARCHIVE: DB-Tickets, die nicht mehr in der API-Response sind.
    # Mass-Archive-Schutz: Wenn API leer geliefert hat UND wir aktive DB-Tickets
    # haben, ist das verdaechtig (Facilioo-Hick) — wir archivieren NICHT.
    if not api_tickets and active_existing_count > 0:
        counters["archive_skipped_empty_api"].append({
            "object_id": str(object_id),
            "active_tickets_count": active_existing_count,
        })
        return

    for facilioo_id, ticket in existing.items():
        if facilioo_id not in api_facilioo_ids and not ticket.is_archived:
            ticket.is_archived = True
            counters["tickets_archived"] += 1


def _aware(dt: datetime) -> datetime:
    """Coerce naive datetime auf UTC-aware. SQLite-Tests strippen tzinfo;
    Postgres-Prod liefert tzaware. Beide Wege landen hier symmetrisch."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Error-Budget (AC5)
# ---------------------------------------------------------------------------

async def _check_error_budget(run_id: uuid.UUID, db_factory: Any) -> dict | None:
    """Prueft ob das Error-Budget in den letzten 24 h ueberschritten wurde.

    Lädt Audit-Rows der letzten N Stunden und aggregiert pro run_id. Threshold:
    > 10 % (default) fehlgeschlagene Laeufe bei N >= 10 *abgeschlossenen* Laeufen.

    Run-Counting: nur Runs mit `sync_finished` ODER `sync_failed`-Audit zaehlen
    als completed. Pure `sync_started`-Runs (mid-flight oder gecrashed) zaehlen
    NICHT in `total_runs`, sonst deflationiert die Failure-Rate.

    Idempotenz: in den letzten 24 h schon ein alert=error_budget_exceeded fuer
    diesen Job → kein zweiter Alert. Job-Filter wird im SQL-WHERE per JSON-cast
    ausgewertet (Postgres-tauglich; SQLite-Tests nutzen TEXT-Spalte).

    Fehler in dieser Funktion werden geloggt und nicht propagiert (Risiko 6:
    der Loop darf nicht sterben wenn die Budget-Query fehlschlaegt).
    """
    window_hours = settings.facilioo_error_budget_window_hours
    threshold = settings.facilioo_error_budget_threshold
    min_sample = max(1, settings.facilioo_error_budget_min_sample)

    try:
        db = db_factory()
        try:
            window_start = datetime.now(tz=timezone.utc) - timedelta(hours=window_hours)

            # SQL-Filter auf JSON-Job-Key. Postgres: JSONB->>'job', SQLite-Test:
            # JSONB ist als TEXT gerendert, der CAST + LIKE-Match faengt das.
            # Wir laden nur die fuer diesen Job relevanten Rows.
            rows = db.execute(
                select(AuditLog).where(
                    AuditLog.action.in_(("sync_started", "sync_finished", "sync_failed")),
                    AuditLog.created_at >= window_start,
                    cast(AuditLog.details_json, String).like(f'%"job": "{_JOB_NAME}"%'),
                )
            ).scalars().all()

            # Pro run_id aggregieren.
            runs: dict[str, dict] = {}
            existing_alert = False
            for row in rows:
                details = row.details_json or {}
                if details.get("job") != _JOB_NAME:
                    # Defensive: doppelter Filter falls SQL-LIKE zu breit matcht
                    continue
                rid = details.get("run_id")
                if not rid:
                    continue
                state = runs.setdefault(rid, {
                    "completed": False,
                    "fetch_failed": False,
                    "items_failed": False,
                    "sync_failed_marker": False,
                })
                if row.action == "sync_finished":
                    state["completed"] = True
                    if details.get("fetch_failed"):
                        state["fetch_failed"] = True
                    if (details.get("objects_failed") or 0) > 0:
                        state["items_failed"] = True
                elif row.action == "sync_failed":
                    if details.get("alert") == "error_budget_exceeded":
                        existing_alert = True
                    else:
                        state["completed"] = True
                        state["sync_failed_marker"] = True

            # Idempotenz: schon ein Alert in den letzten 24 h?
            if existing_alert:
                return None

            completed_runs = [r for r in runs.values() if r["completed"]]
            total_runs = len(completed_runs)
            if total_runs < min_sample:
                return None
            if total_runs == 0:  # paranoia ZeroDiv-Guard
                return None

            failed_runs = sum(
                1 for r in completed_runs
                if r["fetch_failed"] or r["items_failed"] or r["sync_failed_marker"]
            )
            failure_rate = failed_runs / total_runs

            if failure_rate <= threshold:
                return None

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

    # Lock-Check: in single-thread-asyncio race-frei, weil zwischen .locked()
    # und dem skip-Pfad bzw. .acquire() KEIN await liegt — keine andere
    # Coroutine kann den Lock dazwischen umschalten.
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
            "property_fetch_failures": [],
            "archive_skipped_empty_api": [],
        }

        # --- Fetch-Phase ---
        bundles: list[dict] = []
        try:
            async with http_client_factory() as client:
                bundles = await _fetch_all_ticket_bundles(
                    client, db_factory, counters
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
            _write_finish_audit(result, run_id, counters, db_factory)
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
            _write_finish_audit(result, run_id, counters, db_factory)
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
        _write_finish_audit(result, run_id, counters, db_factory)
        return result
    finally:
        lock.release()


def _write_finish_audit(
    result: SyncRunResult,
    run_id: uuid.UUID,
    counters: dict[str, Any],
    db_factory: Any,
) -> None:
    unmapped = counters.get("unmapped_objects", [])
    fetch_failures = counters.get("property_fetch_failures", [])
    archive_skipped = counters.get("archive_skipped_empty_api", [])
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
            # Counter misst Objects-ohne-Facilioo-Mapping (DB-Object hat
            # impower_property_id, Facilioo hat keine matchende externalId).
            "objects_unmapped": len(unmapped),
            "unmapped_objects": unmapped[:50],
            # Per-Property-Failures aus dem Fetch-Loop (Single-Property-Isolation).
            "property_fetch_failures_count": len(fetch_failures),
            "property_fetch_failures": fetch_failures[:50],
            # Mass-Archive-Schutz: Bundles, deren Archive-Sweep wegen leerer
            # API-Response uebersprungen wurde (Facilioo-Hick-Schutz).
            "archive_skipped_empty_api_count": len(archive_skipped),
            "archive_skipped_empty_api": archive_skipped[:50],
        },
        db_factory=db_factory,
    )


# ---------------------------------------------------------------------------
# Poller-Lifecycle (Lifespan-Integration)
# ---------------------------------------------------------------------------

async def _poll_loop() -> None:
    """Dauerschleife: alle `facilioo_poll_interval_seconds` run_facilioo_mirror aufrufen.

    Nach jedem Lauf: Error-Budget-Check (separate Coroutine, Audit-Query-Failures
    werden geschluckt). Manueller Trigger ueber /admin/sync-status/run laeuft
    nicht durch _poll_loop und triggert keinen Budget-Check — gewollt, sonst
    werden manuelle Tests den Budget-Counter aufblasen.
    """
    while True:
        await asyncio.sleep(settings.facilioo_poll_interval_seconds)
        try:
            run_result = await asyncio.wait_for(
                run_facilioo_mirror(),
                timeout=_POLL_RUN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _logger.error(
                "facilioo_mirror_poller: run exceeded %s s timeout",
                _POLL_RUN_TIMEOUT_SECONDS,
            )
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("facilioo_mirror_poller: run failed")
            continue

        # Error-Budget-Check NACH wait_for (Spec Task 5.5). Failures werden
        # in _check_error_budget selbst geschluckt → der Loop ueberlebt.
        if run_result is not None and run_result.run_id is not None:
            try:
                await _check_error_budget(run_result.run_id, SessionLocal)
            except Exception:
                _logger.exception("facilioo_mirror_poller: budget check failed")


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
