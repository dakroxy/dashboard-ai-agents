"""Read-only-Service fuer den Due-Radar: Policen und Wartungen mit Ablauf in N Tagen."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InsurancePolicy, Object, Versicherer, Wartungspflicht


@dataclass(frozen=True)
class DueRadarEntry:
    kind: str  # "police" | "wartung"
    entity_id: uuid.UUID
    object_id: uuid.UUID
    object_short_code: str
    due_date: date
    days_remaining: int
    severity: str
    title: str
    link_url: str


def _severity(days_remaining: int) -> str:
    if days_remaining < 30:
        return "< 30 Tage"
    return "< 90 Tage"


def list_due_within(
    db: Session,
    *,
    days: int = 90,
    accessible_object_ids: set[uuid.UUID],
    severity: str | None = None,
    types: list[str] | None = None,
) -> list[DueRadarEntry]:
    """Alle Policen und Wartungen mit Fälligkeit innerhalb der nächsten `days` Tage.

    `severity` und `types` sind für Story 2.6 vorgesehen und bleiben hier ungenutzt.
    Early-Return bei leerem `accessible_object_ids` — verhindert SAWarning auf Postgres.
    """
    if not accessible_object_ids:
        return []

    today = date.today()
    cutoff = today + timedelta(days=days)
    entries: list[DueRadarEntry] = []

    # Police-Query
    police_stmt = (
        select(
            InsurancePolicy.id,
            InsurancePolicy.object_id,
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
                link_url=f"/objects/{row.object_id}#versicherungen",
            )
        )

    # Wartung-Query — JOIN via policy_id -> policen -> objects (kein direktes object_id nutzen)
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

    entries.sort(key=lambda e: e.due_date)
    return entries
