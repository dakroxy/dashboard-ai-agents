"""Admin-Router: User-/Rollen-Verwaltung und Audit-Log.

Jede Route erzwingt eine konkrete Permission. Die UI blendet Links
nur ein, wenn der User die Permission hat — Server-seitig wird trotzdem
hart geprueft.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, ResourceAccess, Role, User, Workflow
from app.models.governance import ReviewQueueEntry
from app.permissions import (
    PERMISSIONS_BY_GROUP,
    PERMISSION_KEYS,
    RESOURCE_TYPE_WORKFLOW,
    effective_permissions,
    require_any_permission,
    require_permission,
)
from app.services._sync_common import (
    MIRROR_RUN_HOUR,
    MIRROR_RUN_MINUTE,
    next_daily_run_at,
)
from app.services.audit import KNOWN_AUDIT_ACTIONS, audit
from app.services.steckbrief_impower_mirror import run_impower_mirror
from app.templating import templates

_BERLIN_TZ = ZoneInfo("Europe/Berlin")
_MIRROR_JOB_NAME = "steckbrief_impower_mirror"
# Runs die seit mehr als dieser Zeit im Status "started" haengen, ohne
# `sync_finished`, werden als "crashed" markiert — typischerweise Container-
# Restart oder OOM-Kill mitten im Lauf.
_MIRROR_STALE_RUNNING_AFTER_SECONDS = 60 * 60

router = APIRouter(prefix="/admin", tags=["admin"])


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    user: User = Depends(
        require_any_permission("users:manage", "audit_log:view")
    ),
    db: Session = Depends(get_db),
):
    counts = {
        "users": db.query(User).count(),
        "roles": db.query(Role).count(),
        "audit_entries": db.query(AuditLog).count(),
    }
    recent_logs = (
        db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(10).all()
    )
    return templates.TemplateResponse(
        request,
        "admin/home.html",
        {
            "title": "Admin",
            "user": user,
            "counts": counts,
            "recent_logs": recent_logs,
            "photo_backend_warning": getattr(
                request.app.state, "photo_backend_warning", None
            ),
        },
    )


# ---------------------------------------------------------------------------
# User-Verwaltung
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.email.asc()).all()
    return templates.TemplateResponse(
        request,
        "admin/users_list.html",
        {"title": "User", "user": user, "users": users},
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def edit_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    roles = db.query(Role).order_by(Role.name.asc()).all()
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()

    wf_overrides = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.user_id == target.id,
            ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
        )
        .all()
    )
    wf_override_map = {ov.resource_id: ov.mode for ov in wf_overrides}

    role_workflow_ids: set[uuid.UUID] = set()
    if target.role_id is not None:
        role_wf = (
            db.query(ResourceAccess)
            .filter(
                ResourceAccess.role_id == target.role_id,
                ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
                ResourceAccess.mode == "allow",
            )
            .all()
        )
        role_workflow_ids = {ra.resource_id for ra in role_wf}

    return templates.TemplateResponse(
        request,
        "admin/user_edit.html",
        {
            "title": target.email,
            "user": user,
            "target": target,
            "roles": roles,
            "workflows": workflows,
            "permissions_by_group": PERMISSIONS_BY_GROUP,
            "effective": effective_permissions(target),
            "wf_override_map": wf_override_map,
            "role_workflow_ids": role_workflow_ids,
            "is_self": target.id == user.id,
        },
    )


@router.post("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    request: Request,
    role_id: str = Form(""),
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    form = await request.form()
    extras = set(form.getlist("permissions_extra"))
    denied = set(form.getlist("permissions_denied"))

    unknown = (extras | denied) - PERMISSION_KEYS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannte Permission-Keys: {', '.join(sorted(unknown))}",
        )
    # Wenn derselbe Key in extra UND denied gesetzt ist, gewinnt denied —
    # fehlkonfigurationen wuerden sonst unerwartet sein. Wir droppen aus extras.
    extras -= denied

    changes: dict = {}

    # Rolle
    new_role_id: uuid.UUID | None = None
    if role_id:
        try:
            new_role_id = uuid.UUID(role_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungueltige Rolle.",
            )
        if db.query(Role).filter(Role.id == new_role_id).first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rolle nicht gefunden.",
            )
    if target.role_id != new_role_id:
        changes["role_id"] = {
            "from": str(target.role_id) if target.role_id else None,
            "to": str(new_role_id) if new_role_id else None,
        }
        target.role_id = new_role_id

    prev_extra = sorted(target.permissions_extra or [])
    prev_denied = sorted(target.permissions_denied or [])
    new_extra = sorted(extras)
    new_denied = sorted(denied)
    if prev_extra != new_extra:
        changes["permissions_extra"] = {"from": prev_extra, "to": new_extra}
    if prev_denied != new_denied:
        changes["permissions_denied"] = {"from": prev_denied, "to": new_denied}
    target.permissions_extra = new_extra
    target.permissions_denied = new_denied

    # Workflow-Overrides: key 'wf_<workflow_id>' -> 'default' | 'allow' | 'deny'
    workflows = db.query(Workflow).all()
    wf_changes: list[dict] = []
    for wf in workflows:
        mode = form.get(f"wf_{wf.id}") or "default"
        existing = (
            db.query(ResourceAccess)
            .filter(
                ResourceAccess.user_id == target.id,
                ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
                ResourceAccess.resource_id == wf.id,
            )
            .first()
        )
        if mode == "default":
            if existing is not None:
                db.delete(existing)
                wf_changes.append({"workflow": wf.key, "from": existing.mode, "to": "default"})
        elif mode in ("allow", "deny"):
            if existing is None:
                db.add(
                    ResourceAccess(
                        id=uuid.uuid4(),
                        user_id=target.id,
                        resource_type=RESOURCE_TYPE_WORKFLOW,
                        resource_id=wf.id,
                        mode=mode,
                    )
                )
                wf_changes.append({"workflow": wf.key, "from": "default", "to": mode})
            elif existing.mode != mode:
                wf_changes.append({"workflow": wf.key, "from": existing.mode, "to": mode})
                existing.mode = mode
    if wf_changes:
        changes["workflow_overrides"] = wf_changes

    if changes:
        audit(
            db,
            user,
            "user_updated",
            entity_type="user",
            entity_id=target.id,
            details={"target_email": target.email, "changes": changes},
            request=request,
        )
    db.commit()
    return RedirectResponse(
        url=f"/admin/users/{target.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if target.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Man kann sich nicht selbst deaktivieren.",
        )
    if target.disabled_at is None:
        target.disabled_at = datetime.now(timezone.utc)
        target.disabled_by_id = user.id
        audit(
            db,
            user,
            "user_disabled",
            entity_type="user",
            entity_id=target.id,
            details={"target_email": target.email},
            request=request,
        )
        db.commit()
    return RedirectResponse(
        url=f"/admin/users/{target.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if target.disabled_at is not None:
        target.disabled_at = None
        target.disabled_by_id = None
        audit(
            db,
            user,
            "user_enabled",
            entity_type="user",
            entity_id=target.id,
            details={"target_email": target.email},
            request=request,
        )
        db.commit()
    return RedirectResponse(
        url=f"/admin/users/{target.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Rollen-Verwaltung
# ---------------------------------------------------------------------------

@router.get("/roles", response_class=HTMLResponse)
async def list_roles(
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    roles = db.query(Role).order_by(Role.name.asc()).all()
    user_counts: dict[uuid.UUID, int] = {}
    for r in roles:
        user_counts[r.id] = db.query(User).filter(User.role_id == r.id).count()
    return templates.TemplateResponse(
        request,
        "admin/roles_list.html",
        {
            "title": "Rollen",
            "user": user,
            "roles": roles,
            "user_counts": user_counts,
        },
    )


@router.get("/roles/new", response_class=HTMLResponse)
async def new_role_form(
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()
    return templates.TemplateResponse(
        request,
        "admin/role_edit.html",
        {
            "title": "Neue Rolle",
            "user": user,
            "role": None,
            "workflows": workflows,
            "permissions_by_group": PERMISSIONS_BY_GROUP,
            "role_permissions": set(),
            "role_workflow_ids": set(),
        },
    )


@router.post("/roles")
async def create_role(
    request: Request,
    key: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    key = key.strip().lower()
    name = name.strip()
    if not _KEY_RE.match(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key muss mit Kleinbuchstaben beginnen und nur a-z/0-9/_ enthalten.",
        )
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Name ist Pflicht."
        )
    if db.query(Role).filter(Role.key == key).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Key '{key}' ist bereits vergeben.",
        )

    form = await request.form()
    perms = set(form.getlist("permissions")) & PERMISSION_KEYS

    role = Role(
        id=uuid.uuid4(),
        key=key,
        name=name,
        description=description.strip(),
        permissions=sorted(perms),
        is_system_role=False,
    )
    db.add(role)
    db.flush()

    # Workflow-Zuweisungen uebernehmen
    workflow_ids = [
        uuid.UUID(v) for v in form.getlist("workflows") if _is_uuid(v)
    ]
    for wf_id in workflow_ids:
        db.add(
            ResourceAccess(
                id=uuid.uuid4(),
                role_id=role.id,
                resource_type=RESOURCE_TYPE_WORKFLOW,
                resource_id=wf_id,
                mode="allow",
            )
        )

    audit(
        db,
        user,
        "role_created",
        entity_type="role",
        entity_id=role.id,
        details={
            "key": role.key,
            "name": role.name,
            "permissions": role.permissions,
            "workflow_ids": [str(w) for w in workflow_ids],
        },
        request=request,
    )
    db.commit()
    return RedirectResponse(
        url=f"/admin/roles/{role.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/roles/{role_id}", response_class=HTMLResponse)
async def edit_role(
    role_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()
    role_wf = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.role_id == role.id,
            ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
            ResourceAccess.mode == "allow",
        )
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/role_edit.html",
        {
            "title": f"Rolle: {role.name}",
            "user": user,
            "role": role,
            "workflows": workflows,
            "permissions_by_group": PERMISSIONS_BY_GROUP,
            "role_permissions": set(role.permissions or []),
            "role_workflow_ids": {ra.resource_id for ra in role_wf},
        },
    )


@router.post("/roles/{role_id}")
async def update_role(
    role_id: uuid.UUID,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    form = await request.form()
    new_perms = sorted(set(form.getlist("permissions")) & PERMISSION_KEYS)
    workflow_ids = {
        uuid.UUID(v) for v in form.getlist("workflows") if _is_uuid(v)
    }

    changes: dict = {}
    if role.name != name.strip():
        changes["name"] = {"from": role.name, "to": name.strip()}
    if (role.description or "") != description.strip():
        changes["description"] = {
            "from": role.description or "",
            "to": description.strip(),
        }
    if sorted(role.permissions or []) != new_perms:
        changes["permissions"] = {
            "from": sorted(role.permissions or []),
            "to": new_perms,
        }

    role.name = name.strip() or role.name
    role.description = description.strip()
    role.permissions = new_perms

    # Workflow-Zuweisungen synchronisieren
    existing = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.role_id == role.id,
            ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
        )
        .all()
    )
    existing_ids = {ra.resource_id: ra for ra in existing}
    wf_added: list[uuid.UUID] = []
    wf_removed: list[uuid.UUID] = []
    for wf_id in workflow_ids - existing_ids.keys():
        db.add(
            ResourceAccess(
                id=uuid.uuid4(),
                role_id=role.id,
                resource_type=RESOURCE_TYPE_WORKFLOW,
                resource_id=wf_id,
                mode="allow",
            )
        )
        wf_added.append(wf_id)
    for wf_id, ra in existing_ids.items():
        if wf_id not in workflow_ids:
            db.delete(ra)
            wf_removed.append(wf_id)
    if wf_added or wf_removed:
        changes["workflows"] = {
            "added": [str(w) for w in wf_added],
            "removed": [str(w) for w in wf_removed],
        }

    if changes:
        audit(
            db,
            user,
            "role_updated",
            entity_type="role",
            entity_id=role.id,
            details={"key": role.key, "changes": changes},
            request=request,
        )
    db.commit()
    return RedirectResponse(
        url=f"/admin/roles/{role.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/roles/{role_id}/delete")
async def delete_role(
    role_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if role.is_system_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System-Rollen koennen nicht geloescht werden.",
        )
    in_use = db.query(User).filter(User.role_id == role.id).count()
    if in_use > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rolle ist noch {in_use} User(n) zugeordnet — erst umziehen.",
        )
    audit(
        db,
        user,
        "role_deleted",
        entity_type="role",
        entity_id=role.id,
        details={"key": role.key, "name": role.name},
        request=request,
    )
    db.delete(role)
    db.commit()
    return RedirectResponse(
        url="/admin/roles",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Audit-Log
# ---------------------------------------------------------------------------

@router.get("/logs", response_class=HTMLResponse)
async def list_logs(
    request: Request,
    user_email: str | None = Query(None),
    action: str | None = Query(None),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    user: User = Depends(require_permission("audit_log:view")),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f"%{user_email}%"))
    if action:
        query = query.filter(AuditLog.action == action)
    if from_date:
        try:
            dt_from = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            pass
    if to_date:
        try:
            dt_to = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at <= dt_to)
        except ValueError:
            pass

    logs = query.limit(500).all()

    db_distinct = {
        r[0]
        for r in db.query(AuditLog.action).distinct().all()
        if r[0]
    }
    distinct_actions = sorted(db_distinct | set(KNOWN_AUDIT_ACTIONS))

    return templates.TemplateResponse(
        request,
        "admin/logs.html",
        {
            "title": "Audit-Log",
            "user": user,
            "logs": logs,
            "distinct_actions": distinct_actions,
            "filter_user_email": user_email or "",
            "filter_action": action or "",
            "filter_from": from_date or "",
            "filter_to": to_date or "",
            "can_delete": "audit_log:delete" in effective_permissions(user),
        },
    )


@router.post("/logs/{log_id}/delete")
async def delete_log(
    log_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("audit_log:delete")),
    db: Session = Depends(get_db),
):
    entry = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    audit(
        db,
        user,
        "audit_entry_deleted",
        entity_type="audit_log",
        entity_id=entry.id,
        details={
            "deleted_action": entry.action,
            "deleted_user_email": entry.user_email,
            "deleted_created_at": entry.created_at.isoformat(),
        },
        request=request,
    )
    db.delete(entry)
    db.commit()
    return RedirectResponse(
        url="/admin/logs",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Sync-Status (Impower-Nightly-Mirror)
# ---------------------------------------------------------------------------

def _load_recent_mirror_runs(
    db: Session, *, job_name: str, limit: int = 10
) -> list[dict]:
    """Rekonstruiert die letzten `limit` Laeufe aus audit_log.

    Zwei-stufig (AC9):
      1. Sub-Query auf die letzten `limit` distinct `run_id`-Werte aus
         audit_log, gefiltert auf job + sync_*-Actions.
      2. Alle Audit-Rows zu diesen run_ids laden und in Python zu
         Run-Tupeln gruppieren.

    So fallen Laeufe mit vielen sync_failed-Rows nicht aus der Historie,
    wenn ein einzelner Lauf ueber einem Heuristik-Limit liegt.
    """
    run_id_col = AuditLog.details_json["run_id"].as_string()
    job_col = AuditLog.details_json["job"].as_string()
    action_filter = AuditLog.action.in_(
        ("sync_started", "sync_finished", "sync_failed")
    )

    # Stufe 1: letzte `limit` distinct run_ids (nach juengster created_at
    # jedes Runs).
    run_ids_subq = (
        db.query(run_id_col.label("rid"))
        .filter(action_filter)
        .filter(job_col == job_name)
        .group_by(run_id_col)
        .order_by(func.max(AuditLog.created_at).desc())
        .limit(limit)
        .all()
    )
    ordered_ids = [row.rid for row in run_ids_subq if row.rid]
    if not ordered_ids:
        return []

    # Stufe 2: alle Rows zu diesen run_ids.
    rows = (
        db.query(AuditLog)
        .filter(action_filter)
        .filter(run_id_col.in_(ordered_ids))
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    runs_by_id: dict[str, dict] = {
        rid: {"run_id": rid, "started": None, "finished": None, "failures": []}
        for rid in ordered_ids
    }
    for row in rows:
        details = row.details_json or {}
        rid = details.get("run_id")
        bucket = runs_by_id.get(rid)
        if bucket is None:
            continue
        if row.action == "sync_started":
            bucket["started"] = row
        elif row.action == "sync_finished":
            bucket["finished"] = row
        elif row.action == "sync_failed":
            bucket["failures"].append(row)

    now = datetime.now(tz=timezone.utc)

    def _aware(dt: datetime | None) -> datetime | None:
        # Legacy-Rows koennten naive `created_at` haben (z. B. wenn die
        # Spalte historisch mal ohne `timezone=True` war). Verrechnen mit
        # `now` (tz-aware) wuerde sonst TypeError werfen.
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    out: list[dict] = []
    for rid in ordered_ids:
        bucket = runs_by_id[rid]
        started = bucket["started"]
        finished = bucket["finished"]
        failures = bucket["failures"]

        started_details = (started.details_json or {}) if started else {}
        fin_details = (finished.details_json or {}) if finished else {}

        fetch_failed = bool(fin_details.get("fetch_failed"))
        if started_details.get("skipped"):
            status_ = "skipped"
        elif finished is None:
            started_at_local = _aware(started.created_at) if started else None
            if (
                started_at_local is not None
                and (now - started_at_local).total_seconds()
                > _MIRROR_STALE_RUNNING_AFTER_SECONDS
            ):
                status_ = "crashed"
            else:
                status_ = "running"
        elif fetch_failed:
            status_ = "failed"
        else:
            objects_failed = int(fin_details.get("objects_failed") or 0)
            if objects_failed > 0:
                status_ = "partial"
            else:
                status_ = "ok"

        started_at = _aware(started.created_at) if started else None
        finished_at = _aware(finished.created_at) if finished else None
        if started_at is not None and finished_at is not None:
            duration = (finished_at - started_at).total_seconds()
        elif started_at is not None and finished is None:
            # Running or crashed: Laufzeit-Timer live fuer die UI.
            duration = (now - started_at).total_seconds()
        else:
            duration = None

        counters = dict(fin_details) if fin_details else {}
        if finished is None and started_details:
            counters.update(
                {
                    k: v
                    for k, v in started_details.items()
                    if k
                    in {
                        "objects_ok",
                        "objects_failed",
                        "fields_updated",
                        "skipped_user_edit_newer",
                        "objects_skipped_no_impower_id",
                        "objects_skipped_no_impower_data",
                    }
                }
            )

        out.append(
            {
                "run_id": rid,
                "status": status_,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": duration,
                "counters": counters,
                "failures": [
                    {
                        "item_id": (f.details_json or {}).get("item_id"),
                        "impower_property_id": (f.details_json or {}).get(
                            "impower_property_id"
                        ),
                        "entity_id": (f.details_json or {}).get("entity_id"),
                        "phase": (f.details_json or {}).get("phase"),
                        "error": (f.details_json or {}).get("error"),
                    }
                    for f in failures
                ],
                "skip_reason": started_details.get("skip_reason"),
            }
        )
    return out


def _to_berlin(dt: datetime | None) -> datetime | None:
    """Konvertiert tz-aware `datetime` nach Europe/Berlin. None bleibt None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BERLIN_TZ)


def _localize_run(run: dict) -> dict:
    """Rendert `started_at`/`finished_at` in Berlin-Zeit — im Template reicht
    dann `strftime` ohne `astimezone()`, das sonst Container-UTC nimmt.
    """
    run = dict(run)
    run["started_at"] = _to_berlin(run.get("started_at"))
    run["finished_at"] = _to_berlin(run.get("finished_at"))
    return run


@router.get("/sync-status", response_class=HTMLResponse)
async def sync_status_home(
    request: Request,
    triggered: int = Query(0),
    user: User = Depends(require_permission("sync:admin")),
    db: Session = Depends(get_db),
):
    raw_runs = _load_recent_mirror_runs(db, job_name=_MIRROR_JOB_NAME)
    runs = [_localize_run(r) for r in raw_runs]
    last_run = runs[0] if runs else None
    next_run = next_daily_run_at(
        datetime.now(tz=timezone.utc),
        hour=MIRROR_RUN_HOUR,
        minute=MIRROR_RUN_MINUTE,
        tz=_BERLIN_TZ,
    )
    return templates.TemplateResponse(
        request,
        "admin/sync_status.html",
        {
            "title": "Sync-Status",
            "user": user,
            "last_run": last_run,
            "runs": runs,
            "next_run": next_run,
            "triggered": bool(triggered),
        },
    )


@router.post("/sync-status/run")
async def trigger_mirror_run(
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission("sync:admin")),
):
    # FastAPI BackgroundTasks fuehrt async-Callables auf dem Event-Loop aus —
    # kein Sync-Shim noetig. Der Mirror-Lock verhindert Doppellaeufe.
    background_tasks.add_task(run_impower_mirror)
    target = "/admin/sync-status?triggered=1"
    # HTMX-idiomatisch: bei HX-Request via `HX-Redirect`-Header umleiten.
    # Ohne HTMX (Form-Fallback) weiterhin 303.
    if request.headers.get("HX-Request") == "true":
        return Response(
            status_code=status.HTTP_200_OK,
            headers={"HX-Redirect": target},
        )
    return RedirectResponse(
        url=target,
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

def _aware(dt: datetime | None) -> datetime | None:
    """SQLite strippt tzinfo beim Roundtrip. Coercen auf UTC damit Subtraktion
    mit tz-aware `now` keinen TypeError wirft."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _build_queue_query(
    db: Session,
    min_age_days: int | None,
    field_name: str | None,
    assigned_to_user_id: str | None,
):
    q = select(ReviewQueueEntry).where(ReviewQueueEntry.status == "pending")
    if min_age_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
        q = q.where(ReviewQueueEntry.created_at <= cutoff)
    if field_name:
        q = q.where(ReviewQueueEntry.field_name == field_name)
    if assigned_to_user_id:
        try:
            uid = uuid.UUID(assigned_to_user_id)
            q = q.where(ReviewQueueEntry.assigned_to_user_id == uid)
        except ValueError:
            pass
    return q.order_by(ReviewQueueEntry.created_at.asc())


def _prepare_entries(entries):
    now = datetime.now(timezone.utc)
    result = []
    for e in entries:
        raw_value = e.proposed_value.get("value", "") if e.proposed_value else ""
        value_str = str(raw_value)
        if len(value_str) > 100:
            value_str = value_str[:100] + "…"
        result.append({
            "entry": e,
            "value_str": value_str,
            "age_days": (now - _aware(e.created_at)).days,
        })
    return result


@router.get("/review-queue", response_class=HTMLResponse)
async def list_review_queue(
    request: Request,
    min_age_days: int | None = Query(None, ge=0),
    field_name: str | None = Query(None),
    assigned_to_user_id: str | None = Query(None),
    user: User = Depends(require_permission("objects:approve_ki")),
    db: Session = Depends(get_db),
):
    q = _build_queue_query(db, min_age_days, field_name, assigned_to_user_id)
    entries = _prepare_entries(db.execute(q).scalars().all())
    users_for_filter = db.execute(select(User).order_by(User.email)).scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/review_queue.html",
        {
            "entries": entries,
            "users_for_filter": users_for_filter,
            "filter_min_age_days": min_age_days if min_age_days is not None else "",
            "filter_field_name": field_name or "",
            "filter_assigned_to_user_id": assigned_to_user_id or "",
            "user": user,
        },
    )


@router.get("/review-queue/rows", response_class=HTMLResponse)
async def list_review_queue_rows(
    request: Request,
    min_age_days: int | None = Query(None, ge=0),
    field_name: str | None = Query(None),
    assigned_to_user_id: str | None = Query(None),
    user: User = Depends(require_permission("objects:approve_ki")),
    db: Session = Depends(get_db),
):
    q = _build_queue_query(db, min_age_days, field_name, assigned_to_user_id)
    entries = _prepare_entries(db.execute(q).scalars().all())
    return templates.TemplateResponse(
        request,
        "admin/_review_queue_rows.html",
        {
            "entries": entries,
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False
