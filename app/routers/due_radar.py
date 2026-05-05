"""Due-Radar — portfolio-weite Liste ablaufender Policen und Wartungen."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.permissions import accessible_object_ids_for_request, require_permission
from app.services.due_radar import list_due_within
from app.templating import templates

router = APIRouter(prefix="/due-radar", tags=["due-radar"])


_SEVERITY_MAP: dict[str, str | None] = {
    "all": None,
    "lt30": "< 30 Tage",
    "lt90": "< 90 Tage",
}


@router.get("", response_class=HTMLResponse)
async def due_radar_view(
    request: Request,
    user: User = Depends(require_permission("due_radar:view")),
    db: Session = Depends(get_db),
):
    accessible = accessible_object_ids_for_request(request, db, user)
    entries = list_due_within(db, accessible_object_ids=accessible)
    return templates.TemplateResponse(
        request,
        "due_radar.html",
        {"title": "Due-Radar", "user": user, "entries": entries},
    )


@router.get("/rows", response_class=HTMLResponse)
async def due_radar_rows(
    request: Request,
    type: Literal["all", "police", "wartung"] = "all",
    severity: Literal["all", "lt30", "lt90"] = "all",
    user: User = Depends(require_permission("due_radar:view")),
    db: Session = Depends(get_db),
):
    if "hx-request" not in request.headers:
        return RedirectResponse(url="/due-radar", status_code=302)
    accessible = accessible_object_ids_for_request(request, db, user)
    types_filter = None if type == "all" else [type]
    severity_filter = _SEVERITY_MAP[severity]
    entries = list_due_within(
        db,
        types=types_filter,
        severity=severity_filter,
        accessible_object_ids=accessible,
    )
    return templates.TemplateResponse(request, "_due_radar_rows.html", {"entries": entries})
