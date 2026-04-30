"""Service-Layer fuer Facilioo-Ticket-Anzeige am Objekt-Detail (Story 4.4).

Alle Funktionen sind sync — kein Live-Call nach aussen; UI liest nur aus
der lokalen `facilioo_tickets`-Tabelle (CD3 Read/Write-Trennung, FR30).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import cast, String, literal, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.facilioo import FaciliooTicket

_logger = logging.getLogger(__name__)

# Status-Werte, die als "abgeschlossen" gelten und damit aus der Vorgaenge-
# Liste herausgefiltert werden. Enthaelt sowohl die echten Facilioo-Werte aus
# dem Spike-Doc (Story 4.1 — derive_status() liefert "open"/"finished"/
# "deleted") als auch die AC1-Defaults ("closed"/"resolved"/"done"), damit der
# Filter auch nach kuenftigen Facilioo-Schema-Aenderungen greift.
# Hinweis: Tickets MIT diesen Status werden via `notin_(...)` ausgefiltert —
# der Filter listet absichtlich die *abgeschlossenen*, nicht die offenen Werte.
_CLOSED_STATUS_VALUES = ("finished", "deleted", "closed", "resolved", "done")


def get_open_tickets_for_object(
    db: Session,
    object_id: uuid.UUID,
    *,
    cap: int = 10,
) -> tuple[list[FaciliooTicket], bool]:
    """Gibt (rows, is_truncated) zurueck.

    rows: bis zu `cap` offene Tickets sortiert nach created_at DESC.
    is_truncated: True wenn es mehr als `cap` Tickets gibt.
    """
    rows = list(
        db.execute(
            select(FaciliooTicket)
            .where(
                FaciliooTicket.object_id == object_id,
                FaciliooTicket.is_archived.is_(False),
                FaciliooTicket.status.notin_(_CLOSED_STATUS_VALUES),
            )
            .order_by(FaciliooTicket.created_at.desc())
            .limit(cap + 1)
        )
        .scalars()
        .all()
    )
    is_truncated = len(rows) > cap
    return rows[:cap], is_truncated


def get_last_facilioo_sync(db: Session) -> datetime | None:
    """Letzter erfolgreicher sync_finished-Audit fuer facilioo_ticket_mirror.

    Pre-Filter auf 7 Tage — Eintraege aelter als 7 Tage zaehlen als
    "nie gelaufen" (fuer Placeholder-Logik und Stale-Banner, Story 4.4).

    Portabel ueber SQLite (Tests) und PostgreSQL (Prod): JSONB-Zugriff via
    cast+LIKE statt Postgres-spezifischem ['key'].astext-Operator.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        row = db.execute(
            select(AuditLog.created_at)
            .where(
                AuditLog.action == "sync_finished",
                cast(AuditLog.details_json, String).like('%"facilioo_ticket_mirror"%'),
                AuditLog.created_at >= cutoff,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row
    except Exception:
        _logger.exception("get_last_facilioo_sync fehlgeschlagen")
        return None


def format_stale_hint(
    last_sync: datetime | None,
    *,
    threshold_minutes: int = 10,
    now: datetime | None = None,
) -> str | None:
    """Gibt eine deutsch formatierte Zeitdifferenz zurueck oder None.

    None wird zurueckgegeben wenn:
    - last_sync ist None, oder
    - Differenz < threshold_minutes (frische Daten, kein Hinweis noetig).

    Stufen (Minuten-Granularitaet):
      threshold..59   -> "vor X Minuten"
      60..119         -> "vor 1 Stunde"
      120..1439       -> "vor X Stunden"
      1440..2879      -> "vor 1 Tag"
      >= 2880         -> "vor X Tagen"
    """
    if last_sync is None:
        return None
    ref = now if now is not None else datetime.now(timezone.utc)
    # SQLite gibt naive datetimes zurueck; als UTC behandeln (audit_log.created_at
    # ist immer UTC, server_default=func.now() in UTC-Kontext).
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    delta = ref - last_sync
    # Clock-Skew-Schutz: last_sync in der Zukunft → 0 statt negative Minuten,
    # sonst springt der Banner unter den Threshold und verschwindet still.
    minutes = max(0, int(delta.total_seconds() / 60))
    if minutes < threshold_minutes:
        return None
    if minutes < 60:
        return f"vor {minutes} Minuten"
    if minutes < 120:
        return "vor 1 Stunde"
    if minutes < 1440:
        return f"vor {minutes // 60} Stunden"
    if minutes < 2880:
        return "vor 1 Tag"
    return f"vor {minutes // 1440} Tagen"


def facilioo_ticket_url(facilioo_id: str | None) -> str:
    """Baut den Deep-Link zur Facilioo-UI fuer ein Ticket.

    Gibt '#' zurueck wenn facilioo_id leer/None ist (Defensive-Default).
    """
    if not facilioo_id:
        return "#"
    base = settings.facilioo_ui_base_url.rstrip("/")
    return f"{base}/tickets/{facilioo_id}"


def _any_facilioo_tickets_exist(db: Session) -> bool:
    """Prueft ob irgendein Ticket in der Tabelle vorhanden ist (Existenz-Check, kein COUNT)."""
    return (
        db.execute(select(literal(1)).select_from(FaciliooTicket).limit(1)).scalar()
        is not None
    )


def compute_placeholder_mode(db: Session, *, last_sync: datetime | None) -> bool:
    """True wenn die Vorgaenge-Sektion den Platzhalter 'Ticket-Integration in Vorbereitung.' zeigen soll.

    Bedingungen (Disjunktion):
    - Mirror ist deaktiviert (settings.facilioo_mirror_enabled == False), ODER
    - Mirror hat noch nie gelaufen (last_sync is None) UND DB enthaelt keine Tickets.
    """
    if not settings.facilioo_mirror_enabled:
        return True
    if last_sync is None and not _any_facilioo_tickets_exist(db):
        return True
    return False
