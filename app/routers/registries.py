"""Registry-Routen — Versicherer, Dienstleister etc. (Story 2.1+)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.permissions import require_permission
from app.services.registries import get_versicherer_detail, list_versicherer_aggregated
from app.services.steckbrief_policen import create_versicherer, get_all_versicherer
from app.services.steckbrief_wartungen import create_dienstleister, get_all_dienstleister
from app.templating import templates

router = APIRouter(prefix="/registries", tags=["registries"])


@router.get("/versicherer", response_class=HTMLResponse)
async def versicherer_list(
    request: Request,
    user: User = Depends(require_permission("registries:view")),
    db: Session = Depends(get_db),
):
    rows = list_versicherer_aggregated(db)
    return templates.TemplateResponse(
        request,
        "registries_versicherer_list.html",
        {"user": user, "rows": rows, "sort": "name", "order": "asc"},
    )


@router.get("/versicherer/rows", response_class=HTMLResponse)
async def versicherer_rows(
    request: Request,
    sort: str = Query("name"),
    order: str = Query("asc"),
    user: User = Depends(require_permission("registries:view")),
    db: Session = Depends(get_db),
):
    rows = list_versicherer_aggregated(db, sort=sort, order=order)
    return templates.TemplateResponse(
        request,
        "_versicherer_rows.html",
        {"rows": rows},
    )


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


@router.get("/versicherer/{versicherer_id}")
async def versicherer_detail(
    versicherer_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("registries:view")),
) -> HTMLResponse:
    detail = get_versicherer_detail(db, versicherer_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Versicherer nicht gefunden")
    return templates.TemplateResponse(request, "registries_versicherer_detail.html", {
        "detail": detail, "user": user
    })


@router.get("/dienstleister/new-form", response_class=HTMLResponse)
async def dienstleister_new_form(
    request: Request,
    policy_id: uuid.UUID | None = Query(None),
    user: User = Depends(require_permission("registries:edit")),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "_registries_dienstleister_form.html",
        {"user": user, "policy_id": policy_id, "error": None},
    )


@router.post("/dienstleister", response_class=HTMLResponse)
async def dienstleister_create(
    request: Request,
    name: str = Form(...),
    gewerke_tags_raw: str | None = Form(None),
    policy_id: uuid.UUID | None = Form(None),
    user: User = Depends(require_permission("registries:edit")),
    db: Session = Depends(get_db),
):
    if not name.strip():
        return templates.TemplateResponse(
            request,
            "_registries_dienstleister_form.html",
            {"user": user, "policy_id": policy_id, "error": "Name ist Pflichtfeld"},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    gewerke_tags = (
        [t.strip() for t in gewerke_tags_raw.split(",") if t.strip()]
        if gewerke_tags_raw
        else []
    )
    new_d = create_dienstleister(db, user, request, name=name.strip(), gewerke_tags=gewerke_tags)
    db.commit()
    db.refresh(new_d)

    all_dienstleister = get_all_dienstleister(db)

    if policy_id is not None:
        target_id = f"dienstleister-dropdown-{policy_id}"
        dropdown_html = templates.get_template("_registries_dienstleister_options.html").render(
            target_dropdown_id=target_id,
            all_dienstleister=all_dienstleister,
            selected_id=str(new_d.id),
            request=request,
        )
        oob_clear = f'<div id="new-dienstleister-inline-{policy_id}" hx-swap-oob="true"></div>'
        return HTMLResponse(content=dropdown_html + "\n" + oob_clear)
    else:
        dropdown_html = templates.get_template("_registries_dienstleister_options.html").render(
            target_dropdown_id="dienstleister-dropdown",
            all_dienstleister=all_dienstleister,
            selected_id=str(new_d.id),
            request=request,
        )
        return HTMLResponse(content=dropdown_html)
