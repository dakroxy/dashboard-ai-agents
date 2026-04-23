"""Read-only Objekt-Routes fuer Cluster 1 (Stammdaten).

Liste `/objects` + Detailseite `/objects/{id}` mit Stammdaten- und Finanzen-
Sektion (Story 1.5). Keine Write-Endpoints — Sektion-POSTs fuer Technik,
Versicherungen etc. kommen mit Stories 1.6+.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.permissions import accessible_object_ids, require_permission
from app.services.impower import get_bank_balance
from app.services.steckbrief import (
    build_sparkline_svg,
    get_object_detail,
    get_provenance_map,
    has_any_impower_provenance,
    list_objects_with_unit_counts,
    reserve_history_for_sparkline,
)
from app.services.steckbrief_write_gate import write_field_human
from app.templating import templates


_logger = logging.getLogger(__name__)


router = APIRouter(prefix="/objects", tags=["objects"])


STAMMDATEN_FIELDS: tuple[str, ...] = (
    "short_code",
    "name",
    "full_address",
    "weg_nr",
    "impower_property_id",
)


FINANZEN_FIELDS: tuple[str, ...] = (
    "reserve_current",
    "reserve_target",
    "wirtschaftsplan_status",
    "sepa_mandate_refs",
    "last_known_balance",
)


@router.get("", response_class=HTMLResponse)
async def list_objects(
    request: Request,
    user: User = Depends(require_permission("objects:view")),
    db: Session = Depends(get_db),
):
    accessible = accessible_object_ids(db, user)
    rows = list_objects_with_unit_counts(db, accessible_ids=accessible)
    return templates.TemplateResponse(
        request,
        "objects_list.html",
        {
            "title": "Objekte",
            "user": user,
            "rows": rows,
        },
    )


@router.get("/{object_id}", response_class=HTMLResponse)
async def object_detail(
    object_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:view")),
    db: Session = Depends(get_db),
):
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )

    prov_map = get_provenance_map(
        db, "object", detail.obj.id, STAMMDATEN_FIELDS
    )
    has_impower_prov = has_any_impower_provenance(db, "object", detail.obj.id)

    stammdaten = [
        {"field": f, "value": getattr(detail.obj, f), "prov": prov_map.get(f)}
        for f in STAMMDATEN_FIELDS
    ]

    # ---- Finanzen-Sektion (Story 1.5) ----
    fin_prov_map = get_provenance_map(
        db, "object", detail.obj.id, FINANZEN_FIELDS
    )

    # Mirror-Felder vorberechnet ans Template (gleiches Muster wie stammdaten).
    fin_mirror_fields = [
        {
            "key": "reserve_current",
            "label": "Ruecklage aktuell",
            "value": detail.obj.reserve_current,
            "format": "money",
            "prov": fin_prov_map.get("reserve_current"),
        },
        {
            "key": "reserve_target",
            "label": "Ruecklage-Ziel",
            "value": detail.obj.reserve_target,
            "format": "money",
            "prov": fin_prov_map.get("reserve_target"),
        },
        {
            "key": "wirtschaftsplan_status",
            "label": "Wirtschaftsplan",
            "value": detail.obj.wirtschaftsplan_status,
            "format": "text",
            "prov": fin_prov_map.get("wirtschaftsplan_status"),
        },
    ]

    live_balance: Decimal | None = None
    live_balance_at_local: str | None = None
    balance_error = False
    if detail.obj.impower_property_id:
        result = await get_bank_balance(detail.obj.impower_property_id)
        if result is not None:
            live_balance = result["balance"]
            live_balance_at_local = (
                result["fetched_at"]
                .astimezone(ZoneInfo("Europe/Berlin"))
                .strftime("%d.%m.%Y %H:%M")
            )
            # Persistieren via Write-Gate (Mirror-Source). AC2 verlangt KEIN 500
            # bei DB-/Commit-Fehler — wir fangen den Commit-Fehler hier ab,
            # der Render selbst geht trotzdem durch (Saldo bleibt sichtbar,
            # `balance_error=True` triggert den Fallback-Hinweis).
            try:
                write_field_human(
                    db,
                    entity=detail.obj,
                    field="last_known_balance",
                    value=live_balance,
                    source="impower_mirror",
                    source_ref=detail.obj.impower_property_id,
                    user=None,
                )
                db.commit()
            except Exception as exc:
                db.rollback()
                balance_error = True
                _logger.warning(
                    "last_known_balance commit failed for object=%s: %s",
                    detail.obj.id,
                    exc,
                )
        else:
            balance_error = True

    sparkline_points = reserve_history_for_sparkline(db, detail.obj.id)
    sparkline_svg = build_sparkline_svg(sparkline_points)

    return templates.TemplateResponse(
        request,
        "object_detail.html",
        {
            "title": f"{detail.obj.short_code} · {detail.obj.name}",
            "user": user,
            "obj": detail.obj,
            "eigentuemer": detail.eigentuemer,
            "stammdaten": stammdaten,
            "has_impower_prov": has_impower_prov,
            "fin_mirror_fields": fin_mirror_fields,
            "sepa_mandate_refs_prov": fin_prov_map.get("sepa_mandate_refs"),
            "live_balance": live_balance,
            "live_balance_at_local": live_balance_at_local,
            "balance_error": balance_error,
            "sparkline_svg": sparkline_svg,
        },
    )
