"""Due-Radar — portfolio-weite Liste ablaufender Policen und Wartungen."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.permissions import accessible_object_ids, require_permission
from app.services.due_radar import list_due_within
from app.templating import templates

router = APIRouter(prefix="/due-radar", tags=["due-radar"])


@router.get("", response_class=HTMLResponse)
async def due_radar_view(
    request: Request,
    user: User = Depends(require_permission("due_radar:view")),
    db: Session = Depends(get_db),
):
    accessible = accessible_object_ids(db, user)
    entries = list_due_within(db, accessible_object_ids=accessible)
    return templates.TemplateResponse(
        request,
        "due_radar.html",
        {"title": "Due-Radar", "user": user, "entries": entries},
    )


@router.get("/rows", response_class=HTMLResponse)
async def due_radar_rows(
    request: Request,
    type: str = "all",
    severity: str = "all",
    user: User = Depends(require_permission("due_radar:view")),
    db: Session = Depends(get_db),
):
    accessible = accessible_object_ids(db, user)
    types_filter = None if type == "all" else [type]
    severity_filter = None if severity == "all" else ("< 30 Tage" if severity == "lt30" else "< 90 Tage")
    entries = list_due_within(
        db,
        types=types_filter,
        severity=severity_filter,
        accessible_object_ids=accessible,
    )
    return templates.TemplateResponse(request, "_due_radar_rows.html", {"entries": entries})
