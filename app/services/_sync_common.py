"""Generischer Sync-Job-Wrapper fuer Nightly-Mirrors und Polls (CD3).

Nutzung: jeder Mirror (Impower, Facilioo, SharePoint, ...) implementiert
`fetch_items()` + `reconcile_item(item, db)` und delegiert den gemeinsamen
Ablauf (Lock, Audit-Start, per-Item-Session, Fehler-Isolation, Audit-Finish)
an `run_sync_job()`. Damit bleibt der Nightly-Mirror-Orchestrator in
`steckbrief_impower_mirror.py` auf das reine Mapping fokussiert.

Keine Impower-/Facilioo-Kenntnisse hier — das Modul ist bewusst neutral,
damit Story 4.3 (Facilioo-Poll) denselben Wrapper wiederverwendet.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.services.audit import audit


T = TypeVar("T")

_logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Taegliche Run-Zeit fuer den Nightly-Mirror (Europe/Berlin). Wird von
# main.py (Scheduler) und admin.py (UI "Naechster Lauf") importiert — sonst
# muessten beide ihre eigenen Konstanten fuehren und koennten driften.
MIRROR_RUN_HOUR: int = 2
MIRROR_RUN_MINUTE: int = 30


# ---------------------------------------------------------------------------
# Dataclasses + Exceptions
# ---------------------------------------------------------------------------

class SyncItemFailure(Exception):
    """Raised von `reconcile_item`, um den per-Item-Fehler-Audit mit
    Kontext (phase, external_id, entity_id) anzureichern.

    Der generische Wrapper faengt jede Exception, aber wenn es eine
    `SyncItemFailure` ist, fliessen die Felder direkt in
    `sync_failed.details_json` + `entity_id` fuer den indizierten Link.
    """

    def __init__(
        self,
        *,
        phase: str,
        external_id: str | None = None,
        entity_id: uuid.UUID | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.phase = phase
        self.external_id = external_id
        self.entity_id = entity_id
        self.cause = cause
        label = f"[{phase}]"
        if external_id:
            label += f" {external_id}"
        if cause is not None:
            label += f": {type(cause).__name__}: {cause}"
        super().__init__(label)


@dataclass
class ReconcileStats:
    """Rueckgabe von `reconcile_item` — aggregiert in SyncRunResult."""

    fields_updated: int = 0
    skipped_user_edit_newer: int = 0
    eigentuemer_inserted: int = 0
    eigentuemer_updated: int = 0
    # Orphan-Entries tragen Objekt-Kontext, damit die Audit-Payload
    # (same contact_id in mehreren Objekten) nachvollziehbar bleibt.
    eigentuemer_orphans: list[dict[str, Any]] = field(default_factory=list)
    skipped_no_external_id: bool = False
    skipped_no_external_data: bool = False


@dataclass
class SyncRunResult:
    job_name: str
    run_id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None = None
    items_total: int = 0
    items_ok: int = 0
    items_failed: int = 0
    items_skipped_no_external_id: int = 0
    items_skipped_no_external_data: int = 0
    items_discovered: int = 0
    fields_updated: int = 0
    skipped_user_edit_newer: int = 0
    eigentuemer_orphans: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None
    # True wenn der Lauf schon in der Fetch-Phase gescheitert ist — die
    # Admin-UI zeigt dann Status "failed" statt "partial".
    fetch_failed: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_html_error(resp_text: str | None, limit: int = 500) -> str:
    """Entfernt HTML-Tags + collapst Whitespace; schneidet auf `limit`.

    Impower-Fehler kommen teils als HTML-Error-Pages zurueck. Rohe Markup-
    Dumps in audit_log.details_json wuerden die Admin-Tabelle unlesbar
    machen und sind zudem unnoetig gross.
    """
    if resp_text is None:
        return ""
    cleaned = _HTML_TAG_RE.sub("", str(resp_text))
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if len(cleaned) > limit:
        return cleaned[:limit]
    return cleaned


def next_daily_run_at(
    now: datetime, *, hour: int, minute: int, tz: ZoneInfo
) -> datetime:
    """Naechste taegliche Run-Zeit ab `now` (timezone-aware-Rueckgabe in `tz`).

    DST-robust: arbeitet auf `date()`-Ebene (nicht via `timedelta(days=1)`,
    das addiert UTC-Sekunden und ueberspringt / dupliziert Tage am DST-Rand).
    Der finale UTC-Roundtrip normalisiert nicht-existente Lokalzeiten
    (Spring-Forward 02:30 → wird auf 03:30 verschoben) auf einen gueltigen
    Instant; ambige Zeiten (Fall-Back, 02:30 zweimal) werden via `fold=0`
    auf die frueheste Auspraegung gezogen.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_local = now.astimezone(tz)

    def _at(date_obj, h: int, m: int) -> datetime:
        return datetime(
            date_obj.year, date_obj.month, date_obj.day, h, m,
            tzinfo=tz,
        )

    candidate = _at(now_local.date(), hour, minute)
    # UTC-Roundtrip normalisiert DST-Grenzfaelle.
    candidate = candidate.astimezone(timezone.utc).astimezone(tz)
    if candidate <= now_local:
        next_date = now_local.date() + timedelta(days=1)
        candidate = _at(next_date, hour, minute)
        candidate = candidate.astimezone(timezone.utc).astimezone(tz)
    return candidate


def _audit_sync(
    db: Session,
    *,
    action: str,
    run_id: uuid.UUID,
    job_name: str,
    details: dict[str, Any],
    entity_type: str = "sync_run",
    entity_id: uuid.UUID | None = None,
) -> None:
    """Wrapper um audit() mit stabilen Defaults fuer Sync-Events."""
    payload: dict[str, Any] = {
        "job": job_name,
        "run_id": str(run_id),
        **details,
    }
    audit(
        db,
        None,
        action,
        entity_type=entity_type,
        entity_id=entity_id if entity_id is not None else run_id,
        details=payload,
        user_email="system",
    )


# ---------------------------------------------------------------------------
# run_sync_job
# ---------------------------------------------------------------------------

async def run_sync_job(
    *,
    job_name: str,
    fetch_items: Callable[[], Awaitable[list[T] | tuple[list[T], int]]],
    reconcile_item: Callable[[T, Session], Awaitable[ReconcileStats]],
    db_factory: Callable[[], Session],
    lock: asyncio.Lock,
    item_identity: Callable[[T], str] | None = None,
) -> SyncRunResult:
    """Fuehrt einen kompletten Sync-Lauf aus: Lock, Audit, per-Item-Session,
    Fehler-Isolation, Audit-Finish.

    - `fetch_items` laedt die Liste zu verarbeitender Items. Wirft es, wird
      `fetch_failed=True` gesetzt, sync_failed + sync_finished geaudited.
    - `reconcile_item(item, db)` darf werfen — entweder als
      `SyncItemFailure` (mit phase/external_id/entity_id) oder als
      generische Exception. Der Wurf wird gefangen, sync_failed pro Item,
      die anderen laufen weiter.
    - `item_identity(item)` liefert einen String fuer die Fehler-Zuordnung
      (z. B. impower_property_id). Fallback: str(index).
    """
    run_id = uuid.uuid4()
    started_at = datetime.now(tz=timezone.utc)
    result = SyncRunResult(
        job_name=job_name, run_id=run_id, started_at=started_at
    )

    # Check-and-acquire ist in Single-Thread-asyncio atomar, solange zwischen
    # `lock.locked()` und `await lock.acquire()` KEIN `await` steht — der
    # Event-Loop kann ohne await nicht zu einer anderen Coroutine wechseln.
    if lock.locked():
        result.skipped = True
        result.skip_reason = "already_running"
        # Audit-Entry fuer skipped-Run (nur sync_started, kein sync_finished).
        # Falls die DB down ist oder das Audit-Write wirft, soll der Skip
        # trotzdem sauber zurueckkehren — sonst crasht der Scheduler, wenn
        # gleichzeitig ein Lauf laeuft UND die DB kurzzeitig nicht
        # erreichbar ist.
        try:
            db = db_factory()
            try:
                _audit_sync(
                    db,
                    action="sync_started",
                    run_id=run_id,
                    job_name=job_name,
                    details={"skipped": True, "skip_reason": "already_running"},
                )
                db.commit()
            finally:
                db.close()
        except Exception:
            _logger.exception(
                "skipped-run audit write failed (run_id=%s)", run_id
            )
        result.finished_at = datetime.now(tz=timezone.utc)
        return result

    await lock.acquire()
    try:
        # --- sync_started ---
        db = db_factory()
        try:
            _audit_sync(
                db,
                action="sync_started",
                run_id=run_id,
                job_name=job_name,
                details={"started_at": started_at.isoformat()},
            )
            db.commit()
        finally:
            db.close()

        # --- fetch_items ---
        try:
            fetched = await fetch_items()
            if isinstance(fetched, tuple):
                items, discovered = fetched
                result.items_discovered = int(discovered)
            else:
                items = fetched
        except Exception as exc:
            err_msg = strip_html_error(f"{type(exc).__name__}: {exc}")
            result.items_failed = 1
            result.fetch_failed = True
            result.errors.append({"phase": "fetch", "error": err_msg})
            db = db_factory()
            try:
                _audit_sync(
                    db,
                    action="sync_failed",
                    run_id=run_id,
                    job_name=job_name,
                    details={"phase": "fetch", "error": err_msg},
                )
                db.commit()
            finally:
                db.close()
            result.finished_at = datetime.now(tz=timezone.utc)
            # Auch bei fetch-Fehler finaler sync_finished, damit die
            # Status-UI einen Abschluss hat.
            db = db_factory()
            try:
                _audit_sync(
                    db,
                    action="sync_finished",
                    run_id=run_id,
                    job_name=job_name,
                    details=_finish_details(result),
                )
                db.commit()
            finally:
                db.close()
            return result

        result.items_total = len(items)

        # --- Pro Item verarbeiten ---
        orphan_accu: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            item_id = (
                item_identity(item) if item_identity is not None else str(idx)
            )
            db = db_factory()
            try:
                stats = await reconcile_item(item, db)
                if stats.skipped_no_external_id:
                    result.items_skipped_no_external_id += 1
                elif stats.skipped_no_external_data:
                    result.items_skipped_no_external_data += 1
                else:
                    result.items_ok += 1
                result.fields_updated += stats.fields_updated
                result.skipped_user_edit_newer += stats.skipped_user_edit_newer
                if stats.eigentuemer_orphans:
                    orphan_accu.extend(stats.eigentuemer_orphans)
                db.commit()
            except SyncItemFailure as exc:
                db.rollback()
                cause = exc.cause if exc.cause is not None else exc
                err_msg = strip_html_error(
                    f"{type(cause).__name__}: {cause}"
                )
                result.items_failed += 1
                result.errors.append(
                    {
                        "item_id": item_id,
                        "external_id": exc.external_id,
                        "phase": exc.phase,
                        "error": err_msg,
                    }
                )
                fail_db = db_factory()
                try:
                    _audit_sync(
                        fail_db,
                        action="sync_failed",
                        run_id=run_id,
                        job_name=job_name,
                        entity_type=(
                            "object" if exc.entity_id is not None else "sync_run"
                        ),
                        entity_id=exc.entity_id,
                        details={
                            "item_id": item_id,
                            "impower_property_id": exc.external_id,
                            "entity_id": (
                                str(exc.entity_id)
                                if exc.entity_id is not None
                                else None
                            ),
                            "phase": exc.phase,
                            "error": err_msg,
                        },
                    )
                    fail_db.commit()
                finally:
                    fail_db.close()
            except Exception as exc:
                db.rollback()
                err_msg = strip_html_error(f"{type(exc).__name__}: {exc}")
                result.items_failed += 1
                result.errors.append(
                    {"item_id": item_id, "error": err_msg}
                )
                fail_db = db_factory()
                try:
                    _audit_sync(
                        fail_db,
                        action="sync_failed",
                        run_id=run_id,
                        job_name=job_name,
                        entity_type="sync_run",
                        entity_id=None,
                        details={
                            "item_id": item_id,
                            "error": err_msg,
                        },
                    )
                    fail_db.commit()
                finally:
                    fail_db.close()
            finally:
                db.close()

        result.eigentuemer_orphans = orphan_accu

        # --- sync_finished ---
        result.finished_at = datetime.now(tz=timezone.utc)
        db = db_factory()
        try:
            _audit_sync(
                db,
                action="sync_finished",
                run_id=run_id,
                job_name=job_name,
                details=_finish_details(result),
            )
            db.commit()
        finally:
            db.close()

        return result
    finally:
        lock.release()


def _finish_details(result: SyncRunResult) -> dict[str, Any]:
    return {
        "started_at": result.started_at.isoformat(),
        "finished_at": (
            result.finished_at.isoformat()
            if result.finished_at is not None
            else None
        ),
        "objects_total": result.items_total,
        "objects_ok": result.items_ok,
        "objects_failed": result.items_failed,
        "objects_skipped_no_impower_id": result.items_skipped_no_external_id,
        "objects_skipped_no_impower_data": result.items_skipped_no_external_data,
        "objects_discovered": result.items_discovered,
        "fields_updated": result.fields_updated,
        "skipped_user_edit_newer": result.skipped_user_edit_newer,
        "eigentuemer_orphans": result.eigentuemer_orphans,
        "fetch_failed": result.fetch_failed,
    }
