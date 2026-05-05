import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import get_optional_user
from app.config import settings
from app.db import SessionLocal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

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
from app.routers import due_radar as due_radar_router
from app.routers import etv_signature_list as etv_signature_list_router
from app.routers import impower as impower_router
from app.routers import objects as objects_router
from app.routers import registries as registries_router
from app.routers import workflows as workflows_router
from app.services._sync_common import (
    MIRROR_RUN_HOUR,
    MIRROR_RUN_MINUTE,
    next_daily_run_at,
)
from app.services.claude import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT,
    DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
)
from app.middleware.csrf import CSRFMiddleware
from app.services.photo_store import LocalPhotoStore, create_photo_store
from app.services.facilioo_mirror import (
    start_poller as start_facilioo_poller,
    stop_poller as stop_facilioo_poller,
)
from app.services.steckbrief_impower_mirror import run_impower_mirror
from app.templating import templates


_BERLIN_TZ = ZoneInfo("Europe/Berlin")
# Hard timeout for a single mirror run — ein haengender Impower-Call darf
# den Scheduler nicht fuer Tage blockieren. 30 min sollte bei ~50 Objekten
# mit bis zu 60 s Impower-Response-Time komfortabel reichen.
_MIRROR_RUN_TIMEOUT_SECONDS = 30 * 60
# Mindest-Cooldown NACH einem Lauf vor der naechsten next_run-Berechnung.
# Schuetzt gegen Hot-Loop bei Clock-Jump/NTP-Resync.
_MIRROR_POST_RUN_COOLDOWN_SECONDS = 60


_logger = logging.getLogger(__name__)


_DEFAULT_WORKFLOWS: tuple[dict[str, str], ...] = (
    {
        "key": "sepa_mandate",
        "name": "SEPA-Lastschriftmandate",
        "description": (
            "Extraktion von Eigentümer, WEG, IBAN und SEPA-Datum aus "
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
            "(Verwaltervertrag, Grundbuch, Mieterliste, Mietverträge). "
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
            "aus Mietverwaltung heraus für Eigentümer/Mieter)."
        ),
        "system_prompt": DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT,
    },
    {
        "key": "etv_signature_list",
        "name": "ETV-Unterschriftenliste",
        "description": (
            "Druckfertige Unterschriftenliste für eine Eigentümer-"
            "versammlung (ETV). Liest Conferences + Voting-Groups + "
            "Mandate aus Facilioo und rendert ein A4-Querformat-PDF. "
            "Kein Claude — reiner Read-/Render-Pfad."
        ),
        # Kein KI-Modul — model/system_prompt bleiben leer (Workflow-Tabelle
        # erlaubt keine NULL, aber leere Strings sind okay).
        "system_prompt": "",
    },
)


def _seed_workflow_idempotent(db, wf_data: dict) -> None:
    """INSERT fuer einen Workflow — ON CONFLICT DO NOTHING (Postgres) oder
    SELECT-then-INSERT (SQLite). Verhindert IntegrityError bei Multi-Worker-Boot."""
    try:
        is_postgres = db.bind.dialect.name == "postgresql"
    except Exception:
        is_postgres = False

    if is_postgres:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = (
            pg_insert(Workflow)
            .values(
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
            .on_conflict_do_nothing(index_elements=["key"])
        )
        db.execute(stmt)
    else:
        existing = db.query(Workflow).filter(Workflow.key == wf_data["key"]).first()
        if existing is None:
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


def _seed_role_idempotent(
    db, key: str, name: str, description: str, permissions: list
) -> None:
    """INSERT fuer eine Rolle — ON CONFLICT DO NOTHING (Postgres) oder
    SELECT-then-INSERT (SQLite). Verhindert IntegrityError bei Multi-Worker-Boot."""
    try:
        is_postgres = db.bind.dialect.name == "postgresql"
    except Exception:
        is_postgres = False

    if is_postgres:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = (
            pg_insert(Role)
            .values(
                id=uuid.uuid4(),
                key=key,
                name=name,
                description=description,
                permissions=permissions,
                is_system_role=True,
            )
            .on_conflict_do_nothing(index_elements=["key"])
        )
        db.execute(stmt)
    else:
        existing = db.query(Role).filter(Role.key == key).first()
        if existing is None:
            db.add(
                Role(
                    id=uuid.uuid4(),
                    key=key,
                    name=name,
                    description=description,
                    permissions=permissions,
                    is_system_role=True,
                )
            )


def _seed_default_workflow() -> None:
    """Legt die Default-Workflows an, falls sie noch nicht existieren. Ueberschreibt
    bestehende Workflows NICHT — User-Aenderungen bleiben erhalten."""
    db = SessionLocal()
    try:
        for wf_data in _DEFAULT_WORKFLOWS:
            _seed_workflow_idempotent(db, wf_data)
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
    """Seeded System-Rollen admin + user.

    Defaults werden bei jedem Start additiv gemerged — User-Customizations
    bleiben erhalten, aber neue Default-Keys kommen automatisch mit Deploy an.
    """
    db = SessionLocal()
    try:
        for key, perms in DEFAULT_ROLE_PERMISSIONS.items():
            existing = db.query(Role).filter(Role.key == key).first()
            if existing is not None:
                existing.is_system_role = True
                existing.permissions = sorted(
                    set(existing.permissions or []) | set(perms)
                )
                continue
            meta = _ROLE_META.get(key, {"name": key.title(), "description": ""})
            _seed_role_idempotent(
                db,
                key=key,
                name=meta["name"],
                description=meta["description"],
                permissions=perms,
            )
        db.commit()
    finally:
        db.close()


def _seed_default_workflow_access() -> None:
    """Beide System-Rollen bekommen Default-Zugriff auf alle Default-Workflows.
    Per Admin-UI kann das spaeter angepasst werden.

    resource_access hat KEINE UNIQUE-Constraint, deshalb SELECT-then-INSERT
    statt ON CONFLICT DO NOTHING.
    """
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
                existing = db.execute(
                    select(ResourceAccess).where(
                        ResourceAccess.role_id == role.id,
                        ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
                        ResourceAccess.resource_id == wf.id,
                    )
                ).scalar_one_or_none()
                if existing is not None:
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


async def _mirror_scheduler_loop() -> None:
    """Dauerschleife: bis zum naechsten 02:30 Uhr Europe/Berlin schlafen, dann
    run_impower_mirror aufrufen. Fehler des einzelnen Laufs werden geloggt,
    der Scheduler stirbt nicht.

    Schutzen gegen Clock-Jumps (NTP-Resync, Host-Suspend, DST) via:
      - Gesamt-Timeout pro Lauf (_MIRROR_RUN_TIMEOUT_SECONDS) gegen
        haengende Calls.
      - Post-Run-Cooldown, damit ein Lauf, der unerwartet schnell endet,
        nicht sofort den naechsten triggert.
    """
    while True:
        next_run = next_daily_run_at(
            datetime.now(tz=timezone.utc),
            hour=MIRROR_RUN_HOUR,
            minute=MIRROR_RUN_MINUTE,
            tz=_BERLIN_TZ,
        )
        wait_seconds = max(
            0.0,
            (next_run - datetime.now(tz=timezone.utc)).total_seconds(),
        )
        _logger.info(
            "mirror_scheduler: next run at %s (in %.0f s)",
            next_run.isoformat(),
            wait_seconds,
        )
        await asyncio.sleep(wait_seconds)
        try:
            await asyncio.wait_for(
                run_impower_mirror(),
                timeout=_MIRROR_RUN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _logger.error(
                "mirror_scheduler: run exceeded %s s timeout",
                _MIRROR_RUN_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("mirror_scheduler: run failed")
        # Cooldown, damit der Lauf nicht sofort re-triggert wird, falls
        # `next_daily_run_at` aus irgendeinem Grund denselben Instant
        # zurueckgibt (Clock-Skew, DST-Edge).
        await asyncio.sleep(_MIRROR_POST_RUN_COOLDOWN_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_default_workflow()
    _seed_default_roles()
    _seed_default_workflow_access()

    if not settings.steckbrief_field_key:
        _logger.warning(
            "STECKBRIEF_FIELD_KEY ist nicht gesetzt — Fallback auf SECRET_KEY "
            "fuer Field-Level-Encryption. Fuer Prod eigenen Schluessel setzen."
        )

    scheduler_task: asyncio.Task | None = None
    if settings.impower_mirror_enabled:
        scheduler_task = asyncio.create_task(
            _mirror_scheduler_loop(), name="steckbrief_impower_mirror_scheduler"
        )
    else:
        _logger.info(
            "mirror_scheduler: disabled via settings.impower_mirror_enabled"
        )

    # --- Facilioo-Ticket-Mirror (Story 4.3) ---
    if settings.facilioo_mirror_enabled:
        await start_facilioo_poller()
    else:
        _logger.info(
            "facilioo_mirror_poller: disabled via settings.facilioo_mirror_enabled"
        )

    # --- PhotoStore-Init (ID1) ---
    _photo_store = await create_photo_store(settings)
    if isinstance(_photo_store, LocalPhotoStore) and settings.photo_backend == "sharepoint":
        _logger.warning("SharePoint-Init fehlgeschlagen — LocalPhotoStore aktiv")
        _ls_db = SessionLocal()
        try:
            from app.services.audit import audit as _audit
            _audit(
                _ls_db, None, "sharepoint_init_failed",
                details={"reason": "MSAL-Client-Credentials-Flow fehlgeschlagen"},
            )
            _ls_db.commit()
        finally:
            _ls_db.close()
        app.state.photo_backend_warning = (
            "SharePoint-Init fehlgeschlagen — Fotos werden lokal gespeichert."
        )
    else:
        app.state.photo_backend_warning = None
    app.state.photo_store = _photo_store

    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        await stop_facilioo_poller()


app = FastAPI(title="Dashboard KI-Agenten", lifespan=lifespan)

# Middleware-Reihenfolge (Starlette: letzter add_middleware-Call = aeusserste Schicht):
#
#   1. @app.middleware SecurityHeaders  — Basis, innerste Schicht
#   2. add_middleware(CSRFMiddleware)   — innen, laeuft NACH Session
#   3. add_middleware(SessionMiddleware) — aeusserste Schicht, laeuft ZUERST
#
# Request-Flow: Session → CSRF → SecurityHeaders → Router
# Response-Flow: Router → SecurityHeaders (Headers setzen) → CSRF → Session
#
# CSRF liest scope["session"]["csrf_token"] — Session muss dafuer zuerst laufen.


@app.middleware("http")
async def set_default_security_headers(request: Request, call_next):
    # Starlette's ServerErrorMiddleware wrappt unsere Chain von aussen — bei
    # unhandled Exceptions wuerde unsere Header-Logik sonst uebersprungen.
    # Darum hier faangen, 500er selbst bauen, Stacktrace loggen und Header setzen.
    try:
        response = await call_next(request)
    except Exception:
        _logger.exception("Unhandled exception in request %s %s", request.method, request.url.path)
        response = PlainTextResponse("Internal Server Error", status_code=500)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


app.add_middleware(CSRFMiddleware)

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
app.include_router(due_radar_router.router)
app.include_router(objects_router.router)
app.include_router(registries_router.router)
app.include_router(workflows_router.router)
app.include_router(impower_router.router)
app.include_router(etv_signature_list_router.router)
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
