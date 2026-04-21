from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, Workflow
from app.permissions import require_permission
from app.services.audit import audit
from app.services.claude import AVAILABLE_MODELS
from app.templating import templates

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/", response_class=HTMLResponse)
async def list_workflows(
    request: Request,
    user: User = Depends(require_permission("workflows:view")),
    db: Session = Depends(get_db),
):
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()
    return templates.TemplateResponse(
        request,
        "workflows_list.html",
        {"title": "Workflows", "user": user, "workflows": workflows},
    )


@router.get("/{key}", response_class=HTMLResponse)
async def edit_workflow(
    key: str,
    request: Request,
    user: User = Depends(require_permission("workflows:view")),
    db: Session = Depends(get_db),
):
    wf = db.query(Workflow).filter(Workflow.key == key).first()
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return templates.TemplateResponse(
        request,
        "workflow_edit.html",
        {
            "title": f"Workflow: {wf.name}",
            "user": user,
            "workflow": wf,
            "available_models": AVAILABLE_MODELS,
        },
    )


@router.post("/{key}")
async def update_workflow(
    key: str,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    model: str = Form(...),
    chat_model: str = Form(...),
    system_prompt: str = Form(...),
    learning_notes: str = Form(""),
    user: User = Depends(require_permission("workflows:edit")),
    db: Session = Depends(get_db),
):
    wf = db.query(Workflow).filter(Workflow.key == key).first()
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    valid_models = {m[0] for m in AVAILABLE_MODELS}
    for label, value in (("Erkennungsmodell", model), ("Chat-Modell", chat_model)):
        if value not in valid_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unbekanntes {label}: {value}",
            )

    changes: dict[str, dict[str, str]] = {}
    if wf.name != (name.strip() or wf.name):
        changes["name"] = {"from": wf.name, "to": name.strip()}
    if wf.description != description.strip():
        changes["description"] = {"from": wf.description, "to": description.strip()}
    if wf.model != model:
        changes["model"] = {"from": wf.model, "to": model}
    if wf.chat_model != chat_model:
        changes["chat_model"] = {"from": wf.chat_model, "to": chat_model}
    if wf.system_prompt.rstrip() != system_prompt.rstrip():
        changes["system_prompt"] = {"changed": True}
    if wf.learning_notes.rstrip() != learning_notes.rstrip():
        changes["learning_notes"] = {"changed": True}

    wf.name = name.strip() or wf.name
    wf.description = description.strip()
    wf.model = model
    wf.chat_model = chat_model
    wf.system_prompt = system_prompt.rstrip() + "\n"
    wf.learning_notes = learning_notes.rstrip()

    if changes:
        audit(
            db,
            user,
            "workflow_edited",
            entity_type="workflow",
            entity_id=wf.id,
            details={"key": wf.key, "changes": changes},
            request=request,
        )
    db.commit()

    return RedirectResponse(
        url=f"/workflows/{key}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
