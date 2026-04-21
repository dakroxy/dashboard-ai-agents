import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import get_optional_user
from app.config import settings
from app.db import SessionLocal
from app.models import ResourceAccess, Role, User, Workflow
from app.permissions import (
    DEFAULT_ROLE_PERMISSIONS,
    RESOURCE_TYPE_WORKFLOW,
    accessible_workflow_ids,
)
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import cases as cases_router
from app.routers import contacts as contacts_router
from app.routers import documents as documents_router
from app.routers import impower as impower_router
from app.routers import workflows as workflows_router
from app.services.claude import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT,
    DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
)
from app.templating import templates


_DEFAULT_WORKFLOWS: tuple[dict[str, str], ...] = (
    {
        "key": "sepa_mandate",
        "name": "SEPA-Lastschriftmandate",
        "description": (
            "Extraktion von Eigentuemer, WEG, IBAN und SEPA-Datum aus "
            "eingescannten SEPA-Lastschriftmandaten. Ziel: automatische "
            "Pflege in Impower nach Human-in-the-Loop-Freigabe."
        ),
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    },
    {
        "key": "mietverwaltung_setup",
        "name": "Mietverwaltung anlegen",
        "description": (
            "Neuanlage einer kompletten Mietverwaltung in Impower aus 1-n PDFs "
            "(Verwaltervertrag, Grundbuch, Mieterliste, Mietvertraege). "
            "Fall-basiert: mehrere Dokumente bilden zusammen einen Fall."
        ),
        "system_prompt": DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT,
    },
    {
        "key": "contact_create",
        "name": "Kontakt anlegen",
        "description": (
            "Sub-Workflow zum Anlegen eines Impower-Kontakts (Person oder "
            "Unternehmen). Wiederverwendbar aus anderen Workflows (z. B. "
            "aus Mietverwaltung heraus fuer Eigentuemer/Mieter)."
        ),
        "system_prompt": DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT,
    },
)


def _seed_default_workflow() -> None:
    """Legt die Default-Workflows an, falls sie noch nicht existieren. Ueberschreibt
    bestehende Workflows NICHT — User-Aenderungen bleiben erhalten."""
    db = SessionLocal()
    try:
        for wf_data in _DEFAULT_WORKFLOWS:
            exists = (
                db.query(Workflow).filter(Workflow.key == wf_data["key"]).first()
            )
            if exists:
                continue
            db.add(
                Workflow(
                    id=uuid.uuid4(),
                    key=wf_data["key"],
                    name=wf_data["name"],
                    description=wf_data["description"],
                    model=DEFAULT_MODEL,
                    chat_model=DEFAULT_CHAT_MODEL,
                    system_prompt=wf_data["system_prompt"],
                    learning_notes="",
                    active=True,
                )
            )
        db.commit()
    finally:
        db.close()


_ROLE_META: dict[str, dict[str, str]] = {
    "admin": {
        "name": "Administrator",
        "description": "Vollzugriff auf alle Bereiche und Admin-Funktionen.",
    },
    "user": {
        "name": "Standard-User",
        "description": "Dokumente hochladen, bearbeiten, freigeben.",
    },
}


def _seed_default_roles() -> None:
    """Seeded System-Rollen admin + user. Permissions werden NUR bei
    Neuanlage gesetzt — spaetere Permission-Aenderungen im Admin-UI
    bleiben beim App-Restart erhalten."""
    db = SessionLocal()
    try:
        for key, perms in DEFAULT_ROLE_PERMISSIONS.items():
            existing = db.query(Role).filter(Role.key == key).first()
            if existing is not None:
                existing.is_system_role = True
                continue
            meta = _ROLE_META.get(key, {"name": key.title(), "description": ""})
            db.add(
                Role(
                    id=uuid.uuid4(),
                    key=key,
                    name=meta["name"],
                    description=meta["description"],
                    permissions=perms,
                    is_system_role=True,
                )
            )
        db.commit()
    finally:
        db.close()


def _seed_default_workflow_access() -> None:
    """Beide System-Rollen bekommen Default-Zugriff auf alle Default-Workflows.
    Per Admin-UI kann das spaeter angepasst werden."""
    db = SessionLocal()
    try:
        keys = [wf["key"] for wf in _DEFAULT_WORKFLOWS]
        workflows = (
            db.query(Workflow).filter(Workflow.key.in_(keys)).all()
        )
        for wf in workflows:
            for role_key in ("admin", "user"):
                role = db.query(Role).filter(Role.key == role_key).first()
                if role is None:
                    continue
                already = (
                    db.query(ResourceAccess)
                    .filter(
                        ResourceAccess.role_id == role.id,
                        ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
                        ResourceAccess.resource_id == wf.id,
                    )
                    .first()
                )
                if already is not None:
                    continue
                db.add(
                    ResourceAccess(
                        id=uuid.uuid4(),
                        role_id=role.id,
                        resource_type=RESOURCE_TYPE_WORKFLOW,
                        resource_id=wf.id,
                        mode="allow",
                    )
                )
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_default_workflow()
    _seed_default_roles()
    _seed_default_workflow_access()
    yield


app = FastAPI(title="Dashboard KI-Agenten", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.app_env != "development",
    max_age=60 * 60 * 24 * 7,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router.router)
app.include_router(documents_router.router)
app.include_router(cases_router.router)
app.include_router(contacts_router.router)
app.include_router(workflows_router.router)
app.include_router(impower_router.router)
app.include_router(admin_router.router)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request, user: User | None = Depends(get_optional_user)
):
    workflows: list[Workflow] = []
    if user is not None:
        db = SessionLocal()
        try:
            accessible_ids = accessible_workflow_ids(db, user)
            if accessible_ids:
                workflows = (
                    db.query(Workflow)
                    .filter(Workflow.active.is_(True))
                    .filter(Workflow.id.in_(accessible_ids))
                    .order_by(Workflow.name.asc())
                    .all()
                )
        finally:
            db.close()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Dashboard", "user": user, "workflows": workflows},
    )
