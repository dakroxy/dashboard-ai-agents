"""Read-only Aggregations-Service fuer Registry-Listenansichten (Story 2.7+)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import InsurancePolicy, Schadensfall, Versicherer

_SORT_ALLOWED = frozenset({"name", "policen_anzahl", "gesamtpraemie", "schadensquote", "objekte_anzahl"})


@dataclass
class VersichererAggRow:
    versicherer_id: uuid.UUID
    name: str
    policen_anzahl: int
    gesamtpraemie: Decimal
    gesamtschaden: Decimal
    objekte_anzahl: int
    schadensquote: float


def list_versicherer_aggregated(
    db: Session, *, sort: str = "name", order: str = "asc"
) -> list[VersichererAggRow]:
    """Alle Versicherer mit aggregierten Policen- und Schadensdaten.

    Drei separate Queries + Python-Merge, um Double-Count bei sum(praemie)
    durch mehrere Schadensfaelle je Police zu vermeiden.
    """
    alle_versicherer = db.execute(select(Versicherer)).scalars().all()
    if not alle_versicherer:
        return []

    policen_q = (
        select(
            InsurancePolicy.versicherer_id,
            func.count(InsurancePolicy.id).label("cnt"),
            func.coalesce(func.sum(InsurancePolicy.praemie), 0).label("praemie_sum"),
            func.count(distinct(InsurancePolicy.object_id)).label("obj_cnt"),
        )
        .where(InsurancePolicy.versicherer_id.is_not(None))
        .group_by(InsurancePolicy.versicherer_id)
    )
    policen_by_vid: dict[uuid.UUID, Any] = {
        row.versicherer_id: row for row in db.execute(policen_q).all()
    }

    schaden_q = (
        select(
            InsurancePolicy.versicherer_id,
            func.coalesce(func.sum(Schadensfall.amount), 0).label("schaden_sum"),
        )
        .join(Schadensfall, Schadensfall.policy_id == InsurancePolicy.id)
        .where(InsurancePolicy.versicherer_id.is_not(None))
        .group_by(InsurancePolicy.versicherer_id)
    )
    schaden_by_vid: dict[uuid.UUID, Decimal] = {
        row.versicherer_id: Decimal(str(row.schaden_sum))
        for row in db.execute(schaden_q).all()
    }

    result: list[VersichererAggRow] = []
    for v in alle_versicherer:
        p = policen_by_vid.get(v.id)
        praemie = Decimal(str(p.praemie_sum)) if p else Decimal("0")
        schaden = schaden_by_vid.get(v.id, Decimal("0"))
        schadensquote = float(schaden / praemie) if praemie > 0 else 0.0
        result.append(
            VersichererAggRow(
                versicherer_id=v.id,
                name=v.name,
                policen_anzahl=p.cnt if p else 0,
                gesamtpraemie=praemie,
                gesamtschaden=schaden,
                objekte_anzahl=p.obj_cnt if p else 0,
                schadensquote=schadensquote,
            )
        )

    safe_sort = sort if sort in _SORT_ALLOWED else "name"
    result.sort(key=lambda r: getattr(r, safe_sort), reverse=(order == "desc"))
    return result
