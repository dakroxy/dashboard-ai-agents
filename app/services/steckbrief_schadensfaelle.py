"""Service-Helfer fuer Schadensfaelle (Story 2.3)."""
from __future__ import annotations

import unicodedata
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
    if amount < 0:
        raise ValueError("amount must be >= 0")
    if description is not None:
        # NFKC-Normalize verhindert Codepoint-Inflation (Word-Paste mit
        # Zero-Width-Spaces, Kompatibilitaets-Codepoints) — sonst wuerde ein
        # 5000-char-Text mit unsichtbaren Insertions am Cap-Check scheitern.
        description = unicodedata.normalize("NFKC", description).strip()
    if description and len(description) > 5000:
        raise ValueError("description exceeds 5000 chars")
    schaden = Schadensfall(policy_id=policy.id)
    db.add(schaden)
    db.flush()

    # FK-Felder (unit_id) werden durch write_field_human geleitet (Provenance),
    # auch beim Row-Create. Spec-AC1 sagt "alle Feld-Writes"; Dev-Notes-Task-2.3
    # erlaubt FK-Ausnahme beim Create. Aktuell: beide durch Gate → Provenance-Konsistenz gewährt.
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
