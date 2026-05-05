"""Service-Helfer fuer Policen und Versicherer-Registry (Story 2.1)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import InsurancePolicy, Object, User, Versicherer
from app.services.audit import audit
from app.services.steckbrief_write_gate import WriteGateError, write_field_human


def get_policen_for_object(
    db: Session, object_id: uuid.UUID
) -> list[InsurancePolicy]:
    stmt = (
        select(InsurancePolicy)
        .where(InsurancePolicy.object_id == object_id)
        .options(joinedload(InsurancePolicy.versicherer))
        .order_by(
            InsurancePolicy.next_main_due.asc().nulls_last(),
            InsurancePolicy.created_at.asc(),
        )
    )
    return list(db.execute(stmt).scalars().unique().all())


def get_all_versicherer(db: Session) -> list[Versicherer]:
    stmt = select(Versicherer).order_by(Versicherer.name.asc())
    return list(db.execute(stmt).scalars().all())


def validate_police_dates(
    start_date: date | None,
    end_date: date | None,
    next_main_due: date | None,
) -> str | None:
    if next_main_due is not None and start_date is not None:
        if next_main_due < start_date:
            return "Ablauf-Datum darf nicht vor Start-Datum liegen."
    if end_date is not None and start_date is not None:
        if end_date < start_date:
            return "Ende-Datum darf nicht vor Start-Datum liegen."
    return None


def create_police(
    db: Session,
    obj: Object,
    user: User,
    request: Request | None,
    *,
    versicherer_id: uuid.UUID | None,
    police_number: str | None,
    produkt_typ: str | None,
    start_date: date | None,
    end_date: date | None,
    next_main_due: date | None,
    notice_period_months: int | None,
    praemie: Decimal | None,
) -> InsurancePolicy:
    if praemie is not None and praemie < 0:
        raise ValueError("praemie must be >= 0")
    policy = InsurancePolicy(object_id=obj.id)
    db.add(policy)
    db.flush()

    fields: dict[str, Any] = {
        "versicherer_id": versicherer_id,
        "police_number": police_number,
        "produkt_typ": produkt_typ,
        "start_date": start_date,
        "end_date": end_date,
        "next_main_due": next_main_due,
        "notice_period_months": notice_period_months,
        "praemie": praemie,
    }
    for field_name, value in fields.items():
        if value is not None:
            write_field_human(
                db,
                entity=policy,
                field=field_name,
                value=value,
                source="user_edit",
                user=user,
                request=request,
            )
    return policy


def update_police(
    db: Session,
    policy: InsurancePolicy,
    user: User,
    request: Request | None,
    **fields: Any,
) -> InsurancePolicy:
    if "praemie" in fields and fields["praemie"] is not None and fields["praemie"] < 0:
        raise ValueError("praemie must be >= 0")
    for field_name, value in fields.items():
        write_field_human(
            db,
            entity=policy,
            field=field_name,
            value=value,
            source="user_edit",
            user=user,
            request=request,
        )
    return policy


def delete_police(
    db: Session,
    policy: InsurancePolicy,
    user: User,
    request: Request | None,
) -> None:
    # Selectin-Relations vorladen, damit ORM-Cascade sauber ablaufen kann.
    _ = (policy.wartungspflichten, policy.schadensfaelle)
    audit(
        db,
        user,
        "registry_entry_updated",
        entity_type="police",
        entity_id=policy.id,
        details={"action": "delete", "police_number": policy.police_number},
        request=request,
    )
    audit(
        db,
        user,
        "policy_deleted",
        entity_type="police",
        entity_id=policy.id,
        details={
            "police_number": policy.police_number,
            "wartung_count": len(policy.wartungspflichten),
            "schadensfall_count": len(policy.schadensfaelle),
        },
        request=request,
    )
    db.delete(policy)


def create_versicherer(
    db: Session,
    user: User,
    request: Request | None,
    *,
    name: str,
    contact_info: dict,
) -> Versicherer:
    v = Versicherer(name=name, contact_info=contact_info)
    db.add(v)
    db.flush()
    audit(
        db,
        user,
        "registry_entry_created",
        entity_type="versicherer",
        entity_id=v.id,
        details={"name": name},
        request=request,
    )
    return v
