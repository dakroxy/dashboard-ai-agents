"""Service-Helfer fuer Schadensfaelle (Story 2.3)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Schadensfall, User
from app.models.police import InsurancePolicy
from app.services.steckbrief_write_gate import write_field_human


def get_schadensfaelle_for_object(db: Session, object_id: uuid.UUID) -> list[Schadensfall]:
    return (
        db.execute(
            select(Schadensfall)
            .join(InsurancePolicy, Schadensfall.policy_id == InsurancePolicy.id)
            .where(InsurancePolicy.object_id == object_id)
            .options(
                joinedload(Schadensfall.policy).joinedload(InsurancePolicy.versicherer),
                joinedload(Schadensfall.unit),
            )
            .order_by(Schadensfall.occurred_at.desc().nullslast(), Schadensfall.created_at.desc())
        )
        .scalars()
        .all()
    )


def create_schadensfall(
    db: Session,
    policy: InsurancePolicy,
    user: User,
    request: Request | None,
    *,
    occurred_at: date | None,
    amount: Decimal,
    description: str | None,
    unit_id: uuid.UUID | None,
) -> Schadensfall:
    schaden = Schadensfall(policy_id=policy.id)
    db.add(schaden)
    db.flush()

    for field, value in [
        ("amount", amount),
        ("occurred_at", occurred_at),
        ("description", description),
        ("unit_id", unit_id),
    ]:
        if value is not None:
            write_field_human(
                db, entity=schaden, field=field, value=value,
                source="user_edit", user=user, request=request,
            )
    return schaden
