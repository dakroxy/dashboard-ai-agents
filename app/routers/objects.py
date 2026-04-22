"""Read-only Objekt-Routes fuer Cluster 1 (Stammdaten).

Liste `/objects` + Detailseite `/objects/{id}` mit Stammdaten-Sektion und
Provenance-Pills. Keine Write-Endpoints — Sektion-POSTs fuer Technik,
Finanzen, Versicherungen etc. kommen mit Stories 1.4+.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.permissions import accessible_object_ids, require_permission
from app.services.steckbrief import (
    get_object_detail,
    get_provenance_map,
    has_any_impower_provenance,
    list_objects_with_unit_counts,
)
from app.templating import templates


router = APIRouter(prefix="/objects", tags=["objects"])


STAMMDATEN_FIELDS: tuple[str, ...] = (
    "short_code",
    "name",
    "full_address",
    "weg_nr",
    "impower_property_id",
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
        },
    )
