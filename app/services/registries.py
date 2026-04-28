"""Read-only Aggregations-Service fuer Registry-Listenansichten (Story 2.7+)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import InsurancePolicy, Object, Schadensfall, Unit, Versicherer

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

    def _sort_key(r: VersichererAggRow) -> tuple[Any, str]:
        primary = getattr(r, safe_sort)
        if isinstance(primary, str):
            primary = primary.casefold()
        return (primary, str(r.versicherer_id))

    result.sort(key=_sort_key, reverse=(order == "desc"))
    return result


# ---------------------------------------------------------------------------
# Story 2.8 — Versicherer-Detailseite
# ---------------------------------------------------------------------------

_MONTH_ABBR_DE = ["", "Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


@dataclass
class PolicyDetailRow:
    policy_id: uuid.UUID
    police_number: str | None
    object_id: uuid.UUID
    object_short_code: str
    object_name: str
    praemie: Decimal | None
    next_main_due: date | None
    days_remaining: int | None
    severity: str  # "critical" | "warning" | "normal" | "none"


@dataclass
class SchadensfallDetailRow:
    schadensfall_id: uuid.UUID
    occurred_at: date | None
    object_short_code: str
    unit_number: str | None
    amount: Decimal | None
    description: str | None


@dataclass
class VerbundeneObjektRow:
    object_id: uuid.UUID
    short_code: str
    name: str


@dataclass
class HeatmapBucket:
    year: int
    month: int
    label: str        # z.B. "Apr 2026"
    policy_count: int
    severity: str     # "critical" | "warning" | "normal" | "empty"


@dataclass
class VersichererDetailData:
    versicherer: Versicherer
    policen_anzahl: int
    gesamtpraemie: Decimal
    gesamtschaden: Decimal
    schadensquote: float
    policen: list[PolicyDetailRow]
    schadensfaelle: list[SchadensfallDetailRow]
    verbundene_objekte: list[VerbundeneObjektRow]
    heatmap: list[HeatmapBucket]


def _build_heatmap(policen: list[PolicyDetailRow], today: date) -> list[HeatmapBucket]:
    buckets: list[HeatmapBucket] = []
    for i in range(12):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + ((today.month - 1 + i) // 12)
        bucket_policen = [
            p for p in policen
            if p.next_main_due and p.next_main_due.year == y and p.next_main_due.month == m
        ]
        if not bucket_policen:
            severity = "empty"
        else:
            min_days = min(
                p.days_remaining for p in bucket_policen if p.days_remaining is not None
            )
            if min_days < 30:
                severity = "critical"
            elif min_days < 90:
                severity = "warning"
            else:
                severity = "normal"
        buckets.append(HeatmapBucket(
            year=y,
            month=m,
            label=f"{_MONTH_ABBR_DE[m]} {y}",
            policy_count=len(bucket_policen),
            severity=severity,
        ))
    return buckets


def get_versicherer_detail(
    db: Session, versicherer_id: uuid.UUID
) -> VersichererDetailData | None:
    # Step 1
    versicherer = db.execute(
        select(Versicherer).where(Versicherer.id == versicherer_id)
    ).scalar_one_or_none()
    if versicherer is None:
        return None

    # Step 2
    policen_q = (
        select(
            InsurancePolicy.id,
            InsurancePolicy.police_number,
            InsurancePolicy.object_id,
            InsurancePolicy.praemie,
            InsurancePolicy.next_main_due,
            Object.short_code,
            Object.name,
        )
        .join(Object, Object.id == InsurancePolicy.object_id)
        .where(InsurancePolicy.versicherer_id == versicherer_id)
    )
    policen_raw = db.execute(policen_q).all()

    # Step 3
    today = date.today()
    policen: list[PolicyDetailRow] = []
    gesamtpraemie = Decimal("0")
    for r in policen_raw:
        dr = (r.next_main_due - today).days if r.next_main_due else None
        if dr is None:
            sev = "none"
        elif dr < 30:
            sev = "critical"
        elif dr < 90:
            sev = "warning"
        else:
            sev = "normal"
        gesamtpraemie += Decimal(str(r.praemie)) if r.praemie else Decimal("0")
        policen.append(PolicyDetailRow(
            policy_id=r.id,
            police_number=r.police_number,
            object_id=r.object_id,
            object_short_code=r.short_code,
            object_name=r.name,
            praemie=Decimal(str(r.praemie)) if r.praemie else None,
            next_main_due=r.next_main_due,
            days_remaining=dr,
            severity=sev,
        ))
    policen.sort(key=lambda p: (p.next_main_due or date.max, p.policy_id))

    # Step 4
    policy_ids = [r.id for r in policen_raw]
    if policy_ids:
        schaden_q = (
            select(
                Schadensfall.id,
                Schadensfall.occurred_at,
                Schadensfall.amount,
                Schadensfall.description,
                Schadensfall.unit_id,
                Object.short_code.label("object_short_code"),
            )
            .join(InsurancePolicy, InsurancePolicy.id == Schadensfall.policy_id)
            .join(Object, Object.id == InsurancePolicy.object_id)
            .where(Schadensfall.policy_id.in_(policy_ids))
        )
        schaden_raw = db.execute(schaden_q).all()
    else:
        schaden_raw = []

    # Step 5
    unit_ids = [r.unit_id for r in schaden_raw if r.unit_id]
    unit_map: dict[uuid.UUID, str | None] = {}
    if unit_ids:
        units = db.execute(select(Unit.id, Unit.unit_number).where(Unit.id.in_(unit_ids))).all()
        unit_map = {u.id: u.unit_number for u in units}

    # Step 6
    schadensfaelle: list[SchadensfallDetailRow] = []
    gesamtschaden = Decimal("0")
    for r in schaden_raw:
        gesamtschaden += Decimal(str(r.amount)) if r.amount else Decimal("0")
        schadensfaelle.append(SchadensfallDetailRow(
            schadensfall_id=r.id,
            occurred_at=r.occurred_at,
            object_short_code=r.object_short_code,
            unit_number=unit_map.get(r.unit_id) if r.unit_id else None,
            amount=Decimal(str(r.amount)) if r.amount else None,
            description=r.description,
        ))
    schadensfaelle.sort(
        key=lambda s: (s.occurred_at or date.min, s.schadensfall_id), reverse=True
    )

    # Step 7
    schadensquote = float(gesamtschaden / gesamtpraemie) if gesamtpraemie > 0 else 0.0

    # Step 8
    seen_obj_ids: set[uuid.UUID] = set()
    verbundene_objekte: list[VerbundeneObjektRow] = []
    for r in policen_raw:
        if r.object_id not in seen_obj_ids:
            seen_obj_ids.add(r.object_id)
            verbundene_objekte.append(VerbundeneObjektRow(
                object_id=r.object_id,
                short_code=r.short_code,
                name=r.name,
            ))

    # Step 9
    heatmap = _build_heatmap(policen, today)

    return VersichererDetailData(
        versicherer=versicherer,
        policen_anzahl=len(policen),
        gesamtpraemie=gesamtpraemie,
        gesamtschaden=gesamtschaden,
        schadensquote=schadensquote,
        policen=policen,
        schadensfaelle=schadensfaelle,
        verbundene_objekte=verbundene_objekte,
        heatmap=heatmap,
    )
