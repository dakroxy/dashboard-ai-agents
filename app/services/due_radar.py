"""Read-only-Service fuer den Due-Radar: Policen und Wartungen mit Ablauf in N Tagen."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InsurancePolicy, Object, Versicherer, Wartungspflicht
from app.services._severity import DueRadarSeverity
from app.services._time import today_local


@dataclass(frozen=True)
class DueRadarEntry:
    kind: str  # "police" | "wartung"
    entity_id: uuid.UUID
    object_id: uuid.UUID
    object_short_code: str
    due_date: date
    days_remaining: int
    severity: str  # DueRadarSeverity-Wert (StrEnum, str-kompatibel)
    title: str
    link_url: str
    versicherer_id: uuid.UUID | None = None


def _severity(days_remaining: int) -> DueRadarSeverity:
    if days_remaining < 30:
        return DueRadarSeverity.LT30
    return DueRadarSeverity.LT90


def list_due_within(
    db: Session,
    *,
    days: int = 90,
    accessible_object_ids: set[uuid.UUID],
    severity: str | None = None,
    types: list[str] | None = None,
) -> list[DueRadarEntry]:
    """Alle Policen und Wartungen mit Fälligkeit innerhalb der nächsten `days` Tage.

    Early-Return bei leerem `accessible_object_ids` — verhindert SAWarning auf Postgres.
    """
    if not accessible_object_ids:
        return []

    today = today_local()
    cutoff = today + timedelta(days=days)
    entries: list[DueRadarEntry] = []

    # Police-Query — skip wenn types gesetzt und "police" nicht enthalten
    if types is None or "police" in types:
        police_stmt = (
            select(
                InsurancePolicy.id,
                InsurancePolicy.object_id,
                InsurancePolicy.versicherer_id,
                InsurancePolicy.next_main_due,
                Object.short_code,
                Versicherer.name.label("versicherer_name"),
            )
            .join(Object, Object.id == InsurancePolicy.object_id)
            .outerjoin(Versicherer, Versicherer.id == InsurancePolicy.versicherer_id)
            .where(
                InsurancePolicy.next_main_due.is_not(None),
                InsurancePolicy.next_main_due <= cutoff,
                InsurancePolicy.object_id.in_(accessible_object_ids),
            )
        )
        for row in db.execute(police_stmt).all():
            dr = (row.next_main_due - today).days
            entries.append(
                DueRadarEntry(
                    kind="police",
                    entity_id=row.id,
                    object_id=row.object_id,
                    object_short_code=row.short_code,
                    due_date=row.next_main_due,
                    days_remaining=dr,
                    severity=_severity(dr),
                    title=row.versicherer_name or "Police",
                    link_url=f"/objects/{row.object_id}#policy-{row.id}",
                    versicherer_id=row.versicherer_id,
                )
            )

    # Wartung-Query — skip wenn types gesetzt und "wartung" nicht enthalten
    if types is None or "wartung" in types:
        wartung_stmt = (
            select(
                Wartungspflicht.id,
                Wartungspflicht.bezeichnung,
                Wartungspflicht.next_due_date,
                InsurancePolicy.object_id,
                Object.short_code,
            )
            .join(InsurancePolicy, InsurancePolicy.id == Wartungspflicht.policy_id)
            .join(Object, Object.id == InsurancePolicy.object_id)
            .where(
                Wartungspflicht.policy_id.is_not(None),
                Wartungspflicht.next_due_date.is_not(None),
                Wartungspflicht.next_due_date <= cutoff,
                InsurancePolicy.object_id.in_(accessible_object_ids),
            )
        )
        for row in db.execute(wartung_stmt).all():
            dr = (row.next_due_date - today).days
            entries.append(
                DueRadarEntry(
                    kind="wartung",
                    entity_id=row.id,
                    object_id=row.object_id,
                    object_short_code=row.short_code,
                    due_date=row.next_due_date,
                    days_remaining=dr,
                    severity=_severity(dr),
                    title=row.bezeichnung,
                    link_url=f"/objects/{row.object_id}#versicherungen",
                )
            )

    # Severity-Filter in Python (days_remaining wird erst nach DB-Load berechnet)
    if severity == DueRadarSeverity.LT30:
        entries = [e for e in entries if e.days_remaining < 30]
    elif severity == DueRadarSeverity.LT90:
        entries = [e for e in entries if e.days_remaining < 90]

    entries.sort(key=lambda e: (e.due_date, e.entity_id))
    return entries
