"""Service-Helfer fuer Wartungspflichten und Dienstleister-Registry (Story 2.2)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import InsurancePolicy, User, Wartungspflicht
from app.models.registry import Dienstleister
from app.services._severity import WartungSeverity
from app.services._time import today_local
from app.services.audit import audit
from app.services.steckbrief_write_gate import write_field_human


def get_all_dienstleister(db: Session) -> list[Dienstleister]:
    stmt = select(Dienstleister).order_by(Dienstleister.name.asc())
    return list(db.execute(stmt).scalars().all())


def get_wartungspflichten_for_policy(
    db: Session, policy_id: uuid.UUID
) -> list[Wartungspflicht]:
    stmt = (
        select(Wartungspflicht)
        .where(Wartungspflicht.policy_id == policy_id)
        .options(joinedload(Wartungspflicht.dienstleister))
        .order_by(
            Wartungspflicht.next_due_date.asc().nulls_last(),
            Wartungspflicht.created_at.asc(),
        )
    )
    return list(db.execute(stmt).scalars().unique().all())


def get_due_severity(next_due_date: date | None) -> WartungSeverity | None:
    if next_due_date is None:
        return None
    today = today_local()
    if next_due_date <= today + timedelta(days=30):
        return WartungSeverity.CRITICAL
    if next_due_date <= today + timedelta(days=90):
        return WartungSeverity.WARNING
    return None


def validate_wartung_dates(
    letzte_wartung: date | None,
    intervall_monate: int | None,
    next_due_date: date | None,
) -> str | None:
    if letzte_wartung is not None and next_due_date is not None:
        if next_due_date <= letzte_wartung:
            return "Nächste Fälligkeit muss nach Letzter Wartung liegen."
    if (
        letzte_wartung is not None
        and next_due_date is not None
        and intervall_monate is not None
    ):
        abstand_tage = (next_due_date - letzte_wartung).days
        erwartete_tage = intervall_monate * 30
        if abs(abstand_tage - erwartete_tage) > 45:
            return "Hinweis: Intervall und Datumsabstand weichen stark voneinander ab."
    return None


def create_wartungspflicht(
    db: Session,
    policy: InsurancePolicy,
    user: User,
    request: Request,
    *,
    bezeichnung: str,
    dienstleister_id: uuid.UUID | None,
    intervall_monate: int | None,
    letzte_wartung: date | None,
    next_due_date: date | None,
) -> Wartungspflicht:
    # bezeichnung ist NOT NULL → leerer Placeholder fuer den INSERT;
    # write_field_human sieht "" != bezeichnung und schreibt die Provenance.
    wart = Wartungspflicht(
        policy_id=policy.id,
        object_id=policy.object_id,
        bezeichnung="",
    )
    db.add(wart)
    db.flush()

    field_values: dict[str, Any] = {
        "bezeichnung": bezeichnung,
        "dienstleister_id": dienstleister_id,
        "intervall_monate": intervall_monate,
        "letzte_wartung": letzte_wartung,
        "next_due_date": next_due_date,
    }
    for field_name, value in field_values.items():
        if value is not None:
            write_field_human(
                db,
                entity=wart,
                field=field_name,
                value=value,
                source="user_edit",
                user=user,
                request=request,
            )

    return wart


def delete_wartungspflicht(
    db: Session, wart: Wartungspflicht, user: User, request: Request
) -> None:
    audit(
        db,
        user,
        "object_field_updated",
        entity_type="wartung",
        entity_id=wart.id,
        details={
            "action": "delete",
            "bezeichnung": wart.bezeichnung,
            "policy_id": str(wart.policy_id),
        },
        request=request,
    )
    db.delete(wart)


def create_dienstleister(
    db: Session,
    user: User,
    request: Request,
    *,
    name: str,
    gewerke_tags: list[str],
) -> Dienstleister:
    d = Dienstleister(name=name, gewerke_tags=gewerke_tags)
    db.add(d)
    db.flush()
    audit(
        db,
        user,
        "registry_entry_created",
        entity_type="dienstleister",
        entity_id=d.id,
        details={"name": name},
        request=request,
    )
    return d
