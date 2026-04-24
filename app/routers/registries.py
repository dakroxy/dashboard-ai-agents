"""Registry-Routen — Versicherer, Dienstleister etc. (Story 2.1+)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.permissions import require_permission
from app.services.steckbrief_policen import create_versicherer, get_all_versicherer
from app.templating import templates

router = APIRouter(prefix="/registries", tags=["registries"])


@router.get("/versicherer/new-form", response_class=HTMLResponse)
async def versicherer_new_form(
    request: Request,
    user: User = Depends(require_permission("registries:edit")),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "_registries_versicherer_form.html",
        {"user": user, "error": None},
    )


@router.post("/versicherer", response_class=HTMLResponse)
async def versicherer_create(
    request: Request,
    name: str = Form(...),
    adresse: str | None = Form(None),
    kontakt_email: str | None = Form(None),
    kontakt_tel: str | None = Form(None),
    user: User = Depends(require_permission("registries:edit")),
    db: Session = Depends(get_db),
):
    if not name.strip():
        return templates.TemplateResponse(
            request,
            "_registries_versicherer_form.html",
            {"user": user, "error": "Name ist Pflichtfeld"},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    contact_info = {
        k: v
        for k, v in {
            "adresse": adresse,
            "email": kontakt_email,
            "tel": kontakt_tel,
        }.items()
        if v
    }
    new_v = create_versicherer(
        db, user, request, name=name.strip(), contact_info=contact_info
    )
    db.commit()
    db.refresh(new_v)

    versicherer_list = get_all_versicherer(db)
    dropdown_html = templates.get_template("_registries_versicherer_options.html").render(
        versicherer_list=versicherer_list,
        selected_id=str(new_v.id),
        request=request,
    )
    oob_clear = '<div id="new-versicherer-inline" hx-swap-oob="true"></div>'
    return HTMLResponse(content=dropdown_html + "\n" + oob_clear)
