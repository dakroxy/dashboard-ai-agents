"""Read-only Objekt-Routes fuer Cluster 1 (Stammdaten).

Liste `/objects` + Detailseite `/objects/{id}` mit Stammdaten- und Finanzen-
Sektion (Story 1.5). Keine Write-Endpoints — Sektion-POSTs fuer Technik,
Versicherungen etc. kommen mit Stories 1.6+.
"""
from __future__ import annotations

import dataclasses
import logging
import pathlib
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Eigentuemer, InsurancePolicy, Object, Schadensfall, Unit, User, Wartungspflicht
from app.models.object import SteckbriefPhoto
from app.models.registry import Dienstleister, Versicherer
from app.services._text import _normalize_text
from app.permissions import accessible_object_ids, has_permission, require_permission
from app.services.impower import get_bank_balance
from app.services.audit import audit, _audit_in_new_session
from app.services.field_encryption import DecryptionError, decrypt_field
from app.services.photo_store import (
    LARGE_UPLOAD_THRESHOLD,
    MAX_SIZE_BYTES,
    PhotoRef,
    PhotoValidationError,
    validate_photo,
)
from app.services.steckbrief import (
    PHOTO_COMPONENT_REFS,
    TECHNIK_ABSPERRPUNKTE,
    TECHNIK_FIELD_KEYS,
    TECHNIK_FIELDS,
    TECHNIK_HEIZUNG,
    TECHNIK_HISTORIE,
    ZUGANGSCODE_FIELD_KEYS,
    ZUGANGSCODE_FIELDS,
    ObjectListRow,
    TechnikField,
    build_sparkline_svg,
    get_object_detail,
    get_provenance_map,
    has_any_impower_provenance,
    list_objects_with_unit_counts,
    normalize_sort_order,
    parse_technik_value,
    parse_zugangscode_value,
    reserve_history_for_sparkline,
)
from app.services.steckbrief_policen import (
    create_police,
    delete_police,
    get_all_versicherer,
    get_policen_for_object,
    update_police,
    validate_police_dates,
)
from app.services.steckbrief_schadensfaelle import (
    create_schadensfall,
    get_schadensfaelle_for_object,
)
from app.services.steckbrief_wartungen import (
    create_wartungspflicht,
    delete_wartungspflicht,
    get_all_dienstleister,
    get_due_severity,
    validate_wartung_dates,
)
from app.services.facilioo_tickets import (
    compute_placeholder_mode,
    format_stale_hint,
    get_last_facilioo_sync,
    get_open_tickets_for_object,
)
from app.services.pflegegrad import WEAKEST_FIELD_LABELS, get_or_update_pflegegrad_cache
from app.services.steckbrief_write_gate import WriteGateError, write_field_human
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
            "sort": "short_code",
            "order": "asc",
            "filter_reserve": "false",
        },
    )


_FILTER_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})


@router.get("/rows", response_class=HTMLResponse)
async def list_objects_rows(
    request: Request,
    sort: str = Query("short_code"),
    order: str = Query("asc"),
    filter_reserve: str = Query("false"),
    user: User = Depends(require_permission("objects:view")),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not request.headers.get("HX-Request"):
        return RedirectResponse("/objects", status_code=303)
    accessible = accessible_object_ids(db, user)
    safe_sort, safe_order = normalize_sort_order(sort, order)
    filter_bool = filter_reserve.strip().lower() in _FILTER_TRUE_VALUES
    rows = list_objects_with_unit_counts(
        db,
        accessible_ids=accessible,
        sort=safe_sort,
        order=safe_order,
        filter_reserve_below_target=filter_bool,
    )
    # Fragment liefert tbody (primary swap) + thead und filter-bar via OOB,
    # damit ↑/↓-Indikator, hx-get-URLs und "Filter aktiv"-Pille nach jedem
    # Sort/Filter aktuell sind (Review-Patch D1).
    return templates.TemplateResponse(
        request,
        "_obj_table_swap.html",
        {
            "rows": rows,
            "user": user,
            "sort": safe_sort,
            "order": safe_order,
            "filter_reserve": "true" if filter_bool else "false",
            "oob_swap": True,
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

    # --- Pflegegrad (Story 3.3) ---
    try:
        pflegegrad_result, cache_updated = get_or_update_pflegegrad_cache(detail.obj, db)
    except Exception as exc:
        _logger.warning("pflegegrad_score_failed object=%s: %s", detail.obj.id, exc)
        pflegegrad_result, cache_updated = None, False
    if cache_updated:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            _logger.warning(
                "pflegegrad cache commit failed for object=%s: %s",
                detail.obj.id, exc,
            )
            _audit_in_new_session(
                "pflegegrad_cache_commit_fail",
                entity_type="object",
                entity_id=detail.obj.id,
                details={"error": str(exc)[:500]},
            )
            # pflegegrad_result ist trotzdem gueltig — Render laeuft weiter
    # Unbekannte weakest_field-Keys ausfiltern, sonst leeres <ul> ohne Empty-State.
    if pflegegrad_result is not None:
        pflegegrad_result = dataclasses.replace(
            pflegegrad_result,
            weakest_fields=[
                wf for wf in pflegegrad_result.weakest_fields
                if wf in WEAKEST_FIELD_LABELS
            ],
        )

    # ---- Technik-Sektion (Story 1.6) ----
    tech_prov_map = get_provenance_map(
        db, "object", detail.obj.id,
        tuple(f.key for f in TECHNIK_FIELDS),
    )

    def _build_section(fields: tuple[TechnikField, ...]) -> list[dict]:
        return [
            {
                "key": f.key,
                "label": f.label,
                "kind": f.kind,
                "value": getattr(detail.obj, f.key),
                "prov": tech_prov_map.get(f.key),
            }
            for f in fields
        ]

    tech_absperrpunkte = _build_section(TECHNIK_ABSPERRPUNKTE)
    tech_heizung = _build_section(TECHNIK_HEIZUNG)
    tech_historie = _build_section(TECHNIK_HISTORIE)

    # --- Zugangscodes (Fernet-decrypted, nur fuer view_confidential, Story 2.0) ---
    tech_zugangscodes: list[dict] = []
    if has_permission(user, "objects:view_confidential"):
        zug_prov_map = get_provenance_map(
            db, "object", detail.obj.id,
            tuple(f.key for f in ZUGANGSCODE_FIELDS),
        )
        _zug_decrypt_failed = False
        for _zf in ZUGANGSCODE_FIELDS:
            _raw = getattr(detail.obj, _zf.key)
            if _raw is None:
                _dec_value, _dec_error = None, None
            else:
                try:
                    _dec_value = decrypt_field(
                        _raw, entity_type="object", field=_zf.key
                    )
                    _dec_error = None
                except DecryptionError:
                    _dec_value = None
                    _dec_error = (
                        "Code nicht verfügbar — Schlüssel-Konfiguration prüfen"
                    )
                    _zug_decrypt_failed = True
                    audit(
                        db,
                        user,
                        "encryption_key_missing",
                        entity_type="object",
                        entity_id=detail.obj.id,
                        details={"field": _zf.key},
                        request=request,
                    )
            tech_zugangscodes.append({
                "key": _zf.key,
                "label": _zf.label,
                "kind": _zf.kind,
                "value": _dec_value,
                "error": _dec_error,
                "prov": zug_prov_map.get(_zf.key),
            })
        if _zug_decrypt_failed:
            try:
                db.commit()
            except Exception:
                pass  # Audit-Commit-Fehler darf Page-Render nicht blockieren

    # --- Menschen-Notizen (Story 2.4, nur fuer view_confidential) ---
    notes_owners: dict | None = None
    if has_permission(user, "objects:view_confidential"):
        notes_owners = dict(detail.obj.notes_owners or {})

    # ---- Versicherungs-Sektion (Story 2.1+2.2+2.3) ----
    policen = get_policen_for_object(db, detail.obj.id)
    versicherer_list = get_all_versicherer(db)
    dienstleister_list = get_all_dienstleister(db)
    schadensfaelle = get_schadensfaelle_for_object(db, detail.obj.id)
    units = db.scalars(
        select(Unit).where(Unit.object_id == detail.obj.id).order_by(Unit.unit_number)
    ).all()

    # --- Fotos pro Komponente (Story 1.8) ---
    photos_raw = (
        db.execute(
            select(SteckbriefPhoto)
            .where(SteckbriefPhoto.object_id == detail.obj.id)
            .order_by(SteckbriefPhoto.captured_at.desc())
        )
        .scalars()
        .all()
    )
    photos_by_component: dict[str, list] = defaultdict(list)
    for _p in photos_raw:
        photos_by_component[_p.component_ref or "sonstige"].append(_p)

    # ---- Facilioo-Vorgaenge-Sektion (Story 4.4) ----
    facilioo_tickets, facilioo_truncated = get_open_tickets_for_object(db, detail.obj.id)
    # try/except: get_last_facilioo_sync hat intern try/except, aber monkeypatch in
    # Tests (und unvorhergesehene Fehler) koennen trotzdem werfen (FR30 / AC2).
    try:
        facilioo_last_sync = get_last_facilioo_sync(db)
    except Exception:
        _logger.exception("facilioo_last_sync im Route-Handler fehlgeschlagen")
        facilioo_last_sync = None
    facilioo_stale_hint = format_stale_hint(
        facilioo_last_sync,
        threshold_minutes=settings.facilioo_stale_threshold_minutes,
    )
    facilioo_placeholder = compute_placeholder_mode(
        db,
        last_sync=facilioo_last_sync,
    )

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
            "tech_absperrpunkte": tech_absperrpunkte,
            "tech_heizung": tech_heizung,
            "tech_historie": tech_historie,
            "tech_zugangscodes": tech_zugangscodes,
            "photos_by_component": dict(photos_by_component),
            "photo_component_refs": PHOTO_COMPONENT_REFS,
            "policen": policen,
            "versicherer_list": versicherer_list,
            "dienstleister_list": dienstleister_list,
            "schadensfaelle": schadensfaelle,
            "units": units,
            "get_due_severity": get_due_severity,
            "notes_owners": notes_owners,
            "pflegegrad_result": pflegegrad_result,
            "weakest_field_labels": WEAKEST_FIELD_LABELS,
            "facilioo_tickets": facilioo_tickets,
            "facilioo_truncated": facilioo_truncated,
            "facilioo_stale_hint": facilioo_stale_hint,
            "facilioo_placeholder": facilioo_placeholder,
        },
    )


# ---------------------------------------------------------------------------
# Technik-Sektion Inline-Edit (Story 1.6)
# ---------------------------------------------------------------------------

def _technik_field_ctx(obj: Object, field_key: str, db: Session) -> dict:
    """Baut das Render-Dict fuer ein einzelnes Technik-Feld-Fragment.

    Eigener Helper, damit GET edit / GET view / POST save alle dasselbe Shape
    nutzen. Die Provenance-Row muss frisch aus der DB kommen (nach Save),
    deshalb wird sie hier on-demand geladen.
    """
    tf = next(f for f in TECHNIK_FIELDS if f.key == field_key)
    prov = get_provenance_map(db, "object", obj.id, (field_key,))
    return {
        "key": tf.key,
        "label": tf.label,
        "kind": tf.kind,
        "value": getattr(obj, field_key),
        "prov": prov.get(field_key),
    }


@router.get("/{object_id}/technik/edit", response_class=HTMLResponse)
async def technik_field_edit(
    object_id: uuid.UUID,
    request: Request,
    field: str,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    if field not in TECHNIK_FIELD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unbekanntes Technik-Feld",
        )
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )
    return templates.TemplateResponse(
        request,
        "_obj_technik_field_edit.html",
        {
            "obj": detail.obj,
            "field": _technik_field_ctx(detail.obj, field, db),
            "user": user,
            "error": None,
        },
    )


@router.get("/{object_id}/technik/view", response_class=HTMLResponse)
async def technik_field_view(
    object_id: uuid.UUID,
    request: Request,
    field: str,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    """Cancel-Button rendert den View-Zustand wieder — gleicher Permission-
    Check wie Edit: Viewer haben ueberhaupt keinen Edit-/Cancel-Loop."""
    if field not in TECHNIK_FIELD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unbekanntes Technik-Feld",
        )
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )
    return templates.TemplateResponse(
        request,
        "_obj_technik_field_view.html",
        {
            "obj": detail.obj,
            "field": _technik_field_ctx(detail.obj, field, db),
            "user": user,
        },
    )


@router.post("/{object_id}/technik/field", response_class=HTMLResponse)
async def technik_field_save(
    object_id: uuid.UUID,
    request: Request,
    field_name: str = Form(...),
    value: str = Form(""),
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    if field_name not in TECHNIK_FIELD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unbekanntes Technik-Feld",
        )
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )

    parsed, error = parse_technik_value(field_name, value)
    if error is not None:
        return templates.TemplateResponse(
            request,
            "_obj_technik_field_edit.html",
            {
                "obj": detail.obj,
                "field": _technik_field_ctx(detail.obj, field_name, db),
                "user": user,
                "error": error,
                "submitted_value": value,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    try:
        write_field_human(
            db,
            entity=detail.obj,
            field=field_name,
            value=parsed,
            source="user_edit",
            user=user,
            request=request,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return templates.TemplateResponse(
        request,
        "_obj_technik_field_view.html",
        {
            "obj": detail.obj,
            "field": _technik_field_ctx(detail.obj, field_name, db),
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Zugangscode-Endpoints (Story 1.7) — Fernet-Encryption beim Write, Decrypt
# beim Render. View/Cancel hinter `objects:view`, Edit/Save hinter
# `objects:edit` (bewusst asymmetrisch, siehe AC5).
# ---------------------------------------------------------------------------

def _zugangscode_field_ctx(
    obj: Object,
    field_key: str,
    db: Session,
    request: Request,
    user: User,
) -> dict:
    """Baut das Render-Dict fuer ein einzelnes Zugangscode-Fragment.

    Laedt Provenance und decrypted Wert frisch. Bei Decryption-Fehler
    wird ein Audit-Eintrag gestaged (NICHT committed) — der Caller
    ist verantwortlich fuer db.commit() wenn field["error"] gesetzt ist.
    """
    lookup = {f.key: f for f in ZUGANGSCODE_FIELDS}
    zf = lookup[field_key]
    prov_map = get_provenance_map(db, "object", obj.id, (field_key,))
    raw = getattr(obj, field_key)
    if raw is None:
        dec_value: str | None = None
        dec_error: str | None = None
    else:
        try:
            dec_value = decrypt_field(
                raw, entity_type="object", field=field_key
            )
            dec_error = None
        except DecryptionError:
            dec_value = None
            dec_error = (
                "Code nicht verfügbar — Schlüssel-Konfiguration prüfen"
            )
            audit(
                db,
                user,
                "encryption_key_missing",
                entity_type="object",
                entity_id=obj.id,
                details={"field": field_key},
                request=request,
            )
    return {
        "key": zf.key,
        "label": zf.label,
        "kind": zf.kind,
        "value": dec_value,
        "error": dec_error,
        "prov": prov_map.get(field_key),
    }


@router.get("/{object_id}/zugangscodes/view", response_class=HTMLResponse)
async def zugangscode_field_view(
    object_id: uuid.UUID,
    request: Request,
    field: str,
    user: User = Depends(require_permission("objects:view_confidential")),
    db: Session = Depends(get_db),
):
    if field not in ZUGANGSCODE_FIELD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unbekanntes Zugangscode-Feld",
        )
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )
    _field_ctx = _zugangscode_field_ctx(detail.obj, field, db, request, user)
    if _field_ctx["error"] is not None:
        try:
            db.commit()
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "_obj_zugangscode_view.html",
        {
            "obj": detail.obj,
            "field": _field_ctx,
            "user": user,
        },
    )


@router.get("/{object_id}/zugangscodes/edit", response_class=HTMLResponse)
async def zugangscode_field_edit(
    object_id: uuid.UUID,
    request: Request,
    field: str,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "objects:view_confidential"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für Zugangscodes",
        )
    if field not in ZUGANGSCODE_FIELD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unbekanntes Zugangscode-Feld",
        )
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )
    _field_ctx = _zugangscode_field_ctx(detail.obj, field, db, request, user)
    if _field_ctx["error"] is not None:
        try:
            db.commit()
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "_obj_zugangscode_edit.html",
        {
            "obj": detail.obj,
            "field": _field_ctx,
            "user": user,
            "error": None,
        },
    )


@router.post("/{object_id}/zugangscodes/field", response_class=HTMLResponse)
async def zugangscode_field_save(
    object_id: uuid.UUID,
    request: Request,
    field_name: str = Form(...),
    value: str = Form(""),
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "objects:view_confidential"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für Zugangscodes",
        )
    if field_name not in ZUGANGSCODE_FIELD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unbekanntes Zugangscode-Feld",
        )
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )

    parsed, error = parse_zugangscode_value(field_name, value)
    if error is not None:
        _field_ctx_err = _zugangscode_field_ctx(
            detail.obj, field_name, db, request, user
        )
        if _field_ctx_err["error"] is not None:
            try:
                db.commit()
            except Exception:
                pass
        return templates.TemplateResponse(
            request,
            "_obj_zugangscode_edit.html",
            {
                "obj": detail.obj,
                "field": _field_ctx_err,
                "user": user,
                "error": error,
                "submitted_value": value,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    try:
        write_field_human(
            db,
            entity=detail.obj,
            field=field_name,
            value=parsed,
            source="user_edit",
            user=user,
            request=request,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    _field_ctx = _zugangscode_field_ctx(detail.obj, field_name, db, request, user)
    if _field_ctx["error"] is not None:
        try:
            db.commit()
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "_obj_zugangscode_view.html",
        {
            "obj": detail.obj,
            "field": _field_ctx,
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Foto-Endpoints (Story 1.8) — Upload (sync + BG), Status-Polling, Delete,
# File-Serve. Backend-Auswahl via app.state.photo_store (Lifespan-Init).
# ---------------------------------------------------------------------------


@router.post("/{object_id}/photos", response_class=HTMLResponse)
async def photo_upload(
    object_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    component_ref: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    """Upload-Endpoint mit Validierung. Splittet nach Content-Groesse in
    sync (<3 MB) oder BackgroundTask (>=3 MB). Rendert je nach Pfad
    Card-Fragment, Pending-Card oder Fehlermeldung."""
    if component_ref not in PHOTO_COMPONENT_REFS:
        raise HTTPException(400, f"Unbekannte Komponente: {component_ref!r}")
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(404, "Objekt nicht gefunden")

    # OOM-Pre-Check via Content-Length-Header (Defer #129) — vor file.read().
    # 5 % Overhead-Toleranz fuer Multipart-Framing.
    cl_header = request.headers.get("content-length")
    if cl_header:
        try:
            cl_int = int(cl_header)
            if cl_int > int(MAX_SIZE_BYTES * 1.05):
                raise HTTPException(413, "Foto > 10 MB (Pre-Check via Content-Length-Header)")
        except (ValueError, OverflowError):
            pass  # fehlerhafter Header — validate_photo prueft spaeter die echte Groesse

    content = await file.read()
    try:
        validate_photo(content, file.content_type or "")
    except PhotoValidationError as exc:
        return templates.TemplateResponse(
            request,
            "_obj_photo_upload_result.html",
            {"obj": detail.obj, "component_ref": component_ref,
             "error": str(exc), "user": user},
            status_code=400,
        )

    photo_store = request.app.state.photo_store
    short_code = detail.obj.short_code

    if len(content) >= LARGE_UPLOAD_THRESHOLD:
        return await _photo_upload_bg_path(
            db, request, background_tasks, detail, component_ref,
            file, content, photo_store, short_code, object_id, user,
        )
    return await _photo_upload_sync_path(
        db, request, detail, component_ref, file, content, photo_store,
        short_code, object_id, user,
    )


async def _photo_upload_sync_path(
    db, request, detail, component_ref, file, content, photo_store,
    short_code, object_id, user,
):
    ref = None
    try:
        ref = await photo_store.upload(
            object_short_code=short_code, category="technik",
            filename=file.filename or "foto.jpg", content=content,
            content_type=file.content_type or "image/jpeg",
        )
        photo = SteckbriefPhoto(
            object_id=object_id,
            backend=ref.backend,
            drive_item_id=ref.drive_item_id,
            local_path=ref.local_path,
            filename=ref.filename,
            component_ref=component_ref,
            uploaded_by_user_id=user.id,
        )
        db.add(photo)
        audit(
            db, user, "object_photo_uploaded",
            entity_type="object", entity_id=object_id,
            details={"component_ref": component_ref, "filename": ref.filename,
                     "backend": ref.backend},
            request=request,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if ref is not None:
            # Upload war erfolgreich, DB-Commit fehlgeschlagen — Saga: Datei loeschen
            try:
                await photo_store.delete(ref)
            except Exception as del_exc:
                from app.services.audit import _audit_in_new_session
                print(f"[photo-upload-orphan] delete fehlgeschlagen object_id={object_id}: {del_exc}")
                _audit_in_new_session(
                    "photo_upload_orphan",
                    entity_type="object",
                    entity_id=object_id,
                    details={
                        "ref": {"backend": ref.backend, "filename": ref.filename,
                                "local_path": ref.local_path},
                        "error": str(exc),
                        "delete_error": str(del_exc),
                    },
                )
        raise  # Original-Exception re-raisen → User sieht 500
    db.refresh(photo)
    return templates.TemplateResponse(
        request,
        "_obj_photo_card.html",
        {"photo": photo, "obj": detail.obj, "user": user},
    )


async def _photo_upload_bg_path(
    db, request, background_tasks, detail, component_ref, file, content,
    photo_store, short_code, object_id, user,
):
    photo = SteckbriefPhoto(
        object_id=object_id,
        backend=photo_store.backend_name,
        filename=file.filename or "foto.jpg",
        component_ref=component_ref,
        uploaded_by_user_id=user.id,
        photo_metadata={"status": "uploading"},
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    background_tasks.add_task(
        _run_photo_upload_bg,
        photo_id=photo.id,
        content=content,
        content_type=file.content_type or "image/jpeg",
        filename=file.filename or "foto.jpg",
        short_code=short_code,
        category="technik",
        photo_store=photo_store,
        user_id=user.id,
        object_id=object_id,
    )
    return templates.TemplateResponse(
        request,
        "_obj_photo_pending.html",
        {"photo": photo, "obj": detail.obj, "user": user},
    )


def _run_photo_upload_bg(
    *, photo_id: uuid.UUID, content: bytes, content_type: str,
    filename: str, short_code: str, category: str, photo_store,
    user_id: uuid.UUID, object_id: uuid.UUID,
) -> None:
    """BackgroundTask: laedt Content via photo_store hoch und aktualisiert
    die zuvor angelegte SteckbriefPhoto-Row. ``asyncio.run()`` ist hier OK
    (sync BackgroundTask), AuditLog direkt via ``db.add(...)`` weil kein
    Request fuer den ``audit()``-Helper verfuegbar ist.

    Saga-Schutz: wenn DB-Commit nach erfolgreichem Upload fehlschlaegt,
    wird die Datei im Store geloescht und der Stub-Status auf
    ``"upload_failed"`` gesetzt.
    """
    import asyncio
    from app.db import SessionLocal as _SL
    from app.models import AuditLog
    from app.services.audit import _audit_in_new_session, _update_stub_status_in_new_session
    db = _SL()
    try:
        # Phase 1: Upload
        try:
            ref = asyncio.run(photo_store.upload(
                object_short_code=short_code, category=category,
                filename=filename, content=content, content_type=content_type,
            ))
        except Exception as exc:
            _logger.exception("_run_photo_upload_bg: Upload fehlgeschlagen: %s", exc)
            _update_stub_status_in_new_session(photo_id, "error", error=str(exc))
            return

        # Phase 2: DB-Update (Saga-kritisch: Datei ist bereits im Store)
        photo = db.get(SteckbriefPhoto, photo_id)
        if photo is not None:
            photo.backend = ref.backend
            photo.drive_item_id = ref.drive_item_id
            photo.local_path = ref.local_path
            photo.filename = ref.filename
            photo.photo_metadata = {"status": "done"}
            db.add(AuditLog(
                action="object_photo_uploaded",
                user_id=user_id,
                entity_type="object",
                entity_id=object_id,
                details_json={"component_ref": photo.component_ref,
                              "filename": ref.filename, "backend": ref.backend},
            ))
            try:
                db.commit()
            except Exception as commit_exc:
                db.rollback()
                # Saga: Datei aus Store loeschen (Upload war erfolgreich, Commit nicht)
                try:
                    asyncio.run(photo_store.delete(ref))
                except Exception as del_exc:
                    print(f"[photo-upload-orphan] delete fehlgeschlagen photo_id={photo_id}: {del_exc}")
                    _audit_in_new_session(
                        "photo_upload_orphan",
                        entity_type="object",
                        entity_id=object_id,
                        details={
                            "ref": {"backend": ref.backend, "filename": ref.filename,
                                    "local_path": ref.local_path},
                            "error": str(commit_exc),
                            "delete_error": str(del_exc),
                        },
                    )
                _update_stub_status_in_new_session(photo_id, "upload_failed", error=str(commit_exc))
                _logger.exception("_run_photo_upload_bg: DB-Commit fehlgeschlagen (Saga): %s", commit_exc)
    finally:
        db.close()


@router.get("/{object_id}/photos/{photo_id}/status", response_class=HTMLResponse)
async def photo_status(
    object_id: uuid.UUID,
    photo_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:view")),
    db: Session = Depends(get_db),
):
    """Polling-Endpoint waehrend BG-Upload laeuft. Liefert je nach Status
    Pending- oder Card-Fragment zurueck."""
    accessible = accessible_object_ids(db, user)
    if object_id not in accessible:
        raise HTTPException(404)
    photo = db.get(SteckbriefPhoto, photo_id)
    if photo is None or photo.object_id != object_id:
        raise HTTPException(404)
    current = (photo.photo_metadata or {}).get("status", "done")
    if current == "uploading":
        return templates.TemplateResponse(
            request,
            "_obj_photo_pending.html",
            {"photo": photo, "obj": None, "user": user},
        )
    return templates.TemplateResponse(
        request,
        "_obj_photo_card.html",
        {"photo": photo, "obj": None, "user": user},
    )


@router.delete("/{object_id}/photos/{photo_id}", response_class=HTMLResponse)
async def photo_delete(
    object_id: uuid.UUID,
    photo_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    """Loescht Foto aus Backend + DB-Row. Backend-Fehler sind nicht-blockierend
    (Datei-Leichen sind ein kleineres Problem als ein nicht loeschbarer
    DB-Eintrag im UI). Audit + DB-Commit erfolgen immer.
    """
    accessible = accessible_object_ids(db, user)
    if object_id not in accessible:
        raise HTTPException(404)
    photo = db.get(SteckbriefPhoto, photo_id)
    if photo is None or photo.object_id != object_id:
        raise HTTPException(404)
    photo_store = request.app.state.photo_store
    ref = PhotoRef(
        backend=photo.backend,
        drive_item_id=photo.drive_item_id,
        local_path=photo.local_path,
        filename=photo.filename or "",
    )
    try:
        await photo_store.delete(ref)
    except Exception as exc:
        _logger.warning(
            "photo_delete: store.delete fehlgeschlagen (nicht blockierend): %s",
            exc,
        )
    audit(
        db, user, "object_photo_deleted",
        entity_type="object", entity_id=object_id,
        details={"component_ref": photo.component_ref, "filename": photo.filename},
        request=request,
    )
    db.delete(photo)
    db.commit()
    return HTMLResponse("")


@router.get("/{object_id}/photos/{photo_id}/file")
async def photo_file_serve(
    object_id: uuid.UUID,
    photo_id: uuid.UUID,
    user: User = Depends(require_permission("objects:view")),
    db: Session = Depends(get_db),
):
    """Liefert lokal gespeicherte Foto-Dateien (backend='local') aus.
    Path-Traversal-Schutz: ``local_path`` kommt aus DB, aber ``.resolve()``
    + ``is_relative_to``-Check ist Defense-in-Depth gegen kompromittierte
    DB-Werte.
    """
    accessible = accessible_object_ids(db, user)
    if object_id not in accessible:
        raise HTTPException(404)
    photo = db.get(SteckbriefPhoto, photo_id)
    if photo is None or photo.object_id != object_id:
        raise HTTPException(404)
    if photo.backend != "local" or not photo.local_path:
        raise HTTPException(404)
    safe = pathlib.Path(photo.local_path).resolve()
    root = pathlib.Path("uploads").resolve()
    if not safe.is_relative_to(root):
        raise HTTPException(403, "Pfad außerhalb des Upload-Verzeichnisses")
    if not safe.exists():
        raise HTTPException(404)
    return FileResponse(safe)


# ---------------------------------------------------------------------------
# Versicherungs-Sektion (Story 2.1) — Policen-CRUD
# ---------------------------------------------------------------------------

def _load_accessible_object(
    db: Session, object_id: uuid.UUID, user: User
) -> Object:
    """Laedt Object oder wirft 404 — prueft accessible_object_ids."""
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )
    return detail.obj


def _parse_date(val: str | None) -> date | None:
    if not val or not val.strip():
        return None
    try:
        return date.fromisoformat(val.strip())
    except ValueError:
        raise HTTPException(422, detail=f"Ungültiges Datum: {val!r}")


def _parse_decimal(val: str | None) -> Decimal | None:
    if not val or not val.strip():
        return None
    try:
        parsed = Decimal(val.strip().replace(",", "."))
    except InvalidOperation:
        raise HTTPException(422, detail=f"Ungültige Zahl: {val!r}")
    if abs(parsed) >= Decimal("1e10"):
        raise HTTPException(422, detail="Wert zu groß (max 9.999.999.999,99)")
    return parsed


def _render_versicherungen(
    request: Request, obj: Object, db: Session, user: User
):
    policen = get_policen_for_object(db, obj.id)
    versicherer_list = get_all_versicherer(db)
    dienstleister_list = get_all_dienstleister(db)
    schadensfaelle = get_schadensfaelle_for_object(db, obj.id)
    units = db.scalars(
        select(Unit).where(Unit.object_id == obj.id).order_by(Unit.unit_number)
    ).all()
    return templates.TemplateResponse(
        request,
        "_obj_versicherungen.html",
        {
            "obj": obj,
            "policen": policen,
            "versicherer_list": versicherer_list,
            "dienstleister_list": dienstleister_list,
            "schadensfaelle": schadensfaelle,
            "units": units,
            "get_due_severity": get_due_severity,
            "user": user,
        },
    )


@router.get("/{object_id}/sections/versicherungen", response_class=HTMLResponse)
async def versicherungen_section(
    object_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:view")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)
    return _render_versicherungen(request, obj, db, user)


@router.post("/{object_id}/schadensfaelle", response_class=HTMLResponse)
async def create_schadensfall_route(
    request: Request,
    object_id: uuid.UUID,
    policy_id: str = Form(""),
    unit_id: str | None = Form(None),
    occurred_at: str | None = Form(None),
    estimated_sum: str = Form(""),
    description: str | None = Form(None, max_length=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("objects:edit")),
):
    # AC5: accessible_object_ids-Gate als ERSTER Aufruf
    obj = _load_accessible_object(db, object_id, user)

    form_data = {
        "policy_id": policy_id or "",
        "unit_id": unit_id or "",
        "occurred_at": occurred_at or "",
        "estimated_sum": estimated_sum or "",
        "description": description or "",
    }

    def _render_with_error(err: str) -> HTMLResponse:
        policen = get_policen_for_object(db, obj.id)
        versicherer_list = get_all_versicherer(db)
        dienstleister_list = get_all_dienstleister(db)
        schadensfaelle = get_schadensfaelle_for_object(db, obj.id)
        units = db.scalars(
            select(Unit).where(Unit.object_id == obj.id).order_by(Unit.unit_number)
        ).all()
        return templates.TemplateResponse(
            request,
            "_obj_versicherungen.html",
            {
                "obj": obj,
                "policen": policen,
                "versicherer_list": versicherer_list,
                "dienstleister_list": dienstleister_list,
                "schadensfaelle": schadensfaelle,
                "units": units,
                "get_due_severity": get_due_severity,
                "user": user,
                "schaden_form_error": err,
                "schaden_form_data": form_data,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Police: Pflichtfeld + Cross-Object-Check via 404 (Security)
    if not policy_id or not policy_id.strip():
        return _render_with_error("Bitte eine Police auswählen.")
    try:
        policy_uuid = uuid.UUID(policy_id.strip())
    except ValueError:
        return _render_with_error("Ungültige Police-ID.")
    policy = db.get(InsurancePolicy, policy_uuid)
    if not policy or policy.object_id != obj.id:
        raise HTTPException(404, detail="Police nicht gefunden")

    # Unit: optional + Cross-Object-Check via 404 (IDOR-Gate, Security)
    unit_uuid: uuid.UUID | None = None
    if unit_id and unit_id.strip():
        try:
            unit_uuid = uuid.UUID(unit_id.strip())
        except ValueError:
            return _render_with_error("Ungültige Einheit-ID.")
        unit = db.get(Unit, unit_uuid)
        if not unit or unit.object_id != obj.id:
            raise HTTPException(404, detail="Einheit nicht gefunden")

    # AC3: Summen-Validierung — strikt Punkt als Dezimaltrenner, Inf/NaN/Overflow gefiltert
    estimated_sum_clean = (estimated_sum or "").strip()
    if not estimated_sum_clean:
        return _render_with_error("Bitte eine geschätzte Summe angeben.")
    if "," in estimated_sum_clean:
        return _render_with_error(
            "Bitte Punkt als Dezimaltrenner verwenden (z. B. 1500.50)."
        )
    try:
        amount = Decimal(estimated_sum_clean)
    except InvalidOperation:
        return _render_with_error("Summe muss eine Zahl sein.")
    if not amount.is_finite():
        return _render_with_error("Summe ist ungültig.")
    if amount <= 0:
        return _render_with_error("Geschätzte Summe muss größer als 0 sein.")
    if amount > Decimal("9999999999.99"):
        return _render_with_error("Summe ist zu groß (max. 9.999.999.999,99 €).")
    amount = amount.quantize(Decimal("0.01"))

    # Datum: optional, kein zukünftiges Schadensdatum, nicht vor 1900
    occ_date: date | None = None
    if occurred_at and occurred_at.strip():
        try:
            occ_date = date.fromisoformat(occurred_at.strip())
        except ValueError:
            return _render_with_error(f"Ungültiges Datum: {occurred_at!r}.")
        if occ_date > date.today():
            return _render_with_error("Schadensdatum darf nicht in der Zukunft liegen.")
        if occ_date.year < 1900:
            return _render_with_error("Schadensdatum vor 1900 ist unzulässig.")

    description_clean = (description or "").strip() or None

    try:
        create_schadensfall(
            db, policy, user, request,
            occurred_at=occ_date,
            amount=amount,
            description=description_clean,
            unit_id=unit_uuid,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_with_error("Speichern fehlgeschlagen — bitte erneut versuchen.")
    except (ValueError, WriteGateError) as exc:
        # Service-Guards (description-Cap, Double-Encrypt-Guard, ...) muessen
        # User-sichtbar als 422 landen, nicht als 500. WriteGateError beim
        # Double-Encrypt-Schutz ist heuristisch und kann auch fuer legitime
        # User-Inputs auf v1: feuern (siehe deferred-work.md D3).
        db.rollback()
        return _render_with_error(f"Eingabe ungültig: {exc}")

    return _render_versicherungen(request, obj, db, user)


@router.post("/{object_id}/policen", response_class=HTMLResponse)
async def police_create(
    object_id: uuid.UUID,
    request: Request,
    versicherer_id: str | None = Form(None),
    police_number: str | None = Form(None, max_length=50),
    produkt_typ: str | None = Form(None, max_length=100),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    next_main_due: str | None = Form(None),
    notice_period_months: str | None = Form(None),
    praemie: str | None = Form(None),
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)

    parsed_versicherer_id: uuid.UUID | None = None
    if versicherer_id and versicherer_id.strip():
        try:
            parsed_versicherer_id = uuid.UUID(versicherer_id.strip())
        except ValueError:
            raise HTTPException(422, detail="Ungültige Versicherer-ID")
        if db.get(Versicherer, parsed_versicherer_id) is None:
            raise HTTPException(422, detail="Versicherer nicht gefunden")

    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)
    parsed_due = _parse_date(next_main_due)
    parsed_months: int | None = None
    if notice_period_months and notice_period_months.strip():
        try:
            parsed_months = int(notice_period_months.strip())
        except ValueError:
            raise HTTPException(422, detail="Ungültige Monatsangabe")
        if parsed_months < 0 or parsed_months > 360:
            raise HTTPException(422, detail="Kündigungsfrist muss zwischen 0 und 360 Monaten liegen")
    parsed_praemie = _parse_decimal(praemie)
    if parsed_praemie is not None and parsed_praemie < 0:
        raise HTTPException(422, detail="Prämie darf nicht negativ sein")

    err = validate_police_dates(parsed_start, parsed_end, parsed_due)
    if err:
        policen = get_policen_for_object(db, obj.id)
        versicherer_list = get_all_versicherer(db)
        dienstleister_list = get_all_dienstleister(db)
        return templates.TemplateResponse(
            request,
            "_obj_versicherungen.html",
            {
                "obj": obj,
                "policen": policen,
                "versicherer_list": versicherer_list,
                "dienstleister_list": dienstleister_list,
                "get_due_severity": get_due_severity,
                "user": user,
                "form_error": err,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    create_police(
        db, obj, user, request,
        versicherer_id=parsed_versicherer_id,
        police_number=police_number or None,
        produkt_typ=produkt_typ or None,
        start_date=parsed_start,
        end_date=parsed_end,
        next_main_due=parsed_due,
        notice_period_months=parsed_months,
        praemie=parsed_praemie,
    )
    db.commit()
    return _render_versicherungen(request, obj, db, user)


@router.get("/{object_id}/policen/{policy_id}/edit-form", response_class=HTMLResponse)
async def police_edit_form(
    object_id: uuid.UUID,
    policy_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)
    policy = db.get(InsurancePolicy, policy_id)
    if policy is None or policy.object_id != obj.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Police nicht gefunden")
    versicherer_list = get_all_versicherer(db)
    return templates.TemplateResponse(
        request,
        "_obj_policen_edit_form.html",
        {"obj": obj, "policy": policy, "versicherer_list": versicherer_list, "user": user},
    )


@router.put("/{object_id}/policen/{policy_id}", response_class=HTMLResponse)
async def police_update(
    object_id: uuid.UUID,
    policy_id: uuid.UUID,
    request: Request,
    versicherer_id: str | None = Form(None),
    police_number: str | None = Form(None, max_length=50),
    produkt_typ: str | None = Form(None, max_length=100),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    next_main_due: str | None = Form(None),
    notice_period_months: str | None = Form(None),
    praemie: str | None = Form(None),
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)
    policy = db.get(InsurancePolicy, policy_id)
    if policy is None or policy.object_id != obj.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Police nicht gefunden")

    parsed_versicherer_id: uuid.UUID | None = None
    if versicherer_id and versicherer_id.strip():
        try:
            parsed_versicherer_id = uuid.UUID(versicherer_id.strip())
        except ValueError:
            raise HTTPException(422, detail="Ungültige Versicherer-ID")
        if db.get(Versicherer, parsed_versicherer_id) is None:
            raise HTTPException(422, detail="Versicherer nicht gefunden")

    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)
    parsed_due = _parse_date(next_main_due)
    parsed_months: int | None = None
    if notice_period_months and notice_period_months.strip():
        try:
            parsed_months = int(notice_period_months.strip())
        except ValueError:
            raise HTTPException(422, detail="Ungültige Monatsangabe")
        if parsed_months < 0 or parsed_months > 360:
            raise HTTPException(422, detail="Kündigungsfrist muss zwischen 0 und 360 Monaten liegen")
    parsed_praemie = _parse_decimal(praemie)
    if parsed_praemie is not None and parsed_praemie < 0:
        raise HTTPException(422, detail="Prämie darf nicht negativ sein")

    err = validate_police_dates(parsed_start, parsed_end, parsed_due)
    if err:
        policen = get_policen_for_object(db, obj.id)
        versicherer_list = get_all_versicherer(db)
        dienstleister_list = get_all_dienstleister(db)
        return templates.TemplateResponse(
            request,
            "_obj_versicherungen.html",
            {
                "obj": obj,
                "policen": policen,
                "versicherer_list": versicherer_list,
                "dienstleister_list": dienstleister_list,
                "get_due_severity": get_due_severity,
                "user": user,
                "form_error": err,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    changed_fields: dict = {
        "versicherer_id": parsed_versicherer_id,
        "police_number": police_number or None,
        "produkt_typ": produkt_typ or None,
        "start_date": parsed_start,
        "end_date": parsed_end,
        "next_main_due": parsed_due,
        "notice_period_months": parsed_months,
        "praemie": parsed_praemie,
    }
    update_police(db, policy, user, request, **changed_fields)
    db.commit()
    return _render_versicherungen(request, obj, db, user)


@router.delete("/{object_id}/policen/{policy_id}", response_class=HTMLResponse)
async def police_delete(
    object_id: uuid.UUID,
    policy_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)
    policy = db.get(InsurancePolicy, policy_id)
    if policy is None or policy.object_id != obj.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Police nicht gefunden")
    delete_police(db, policy, user, request)
    db.commit()
    return _render_versicherungen(request, obj, db, user)


# ---------------------------------------------------------------------------
# Wartungspflichten (Story 2.2)
# ---------------------------------------------------------------------------


@router.post(
    "/{object_id}/policen/{policy_id}/wartungspflichten",
    response_class=HTMLResponse,
)
async def wartungspflicht_create(
    object_id: uuid.UUID,
    policy_id: uuid.UUID,
    request: Request,
    bezeichnung: str = Form(""),
    dienstleister_id: str | None = Form(None),
    intervall_monate: str | None = Form(None),
    letzte_wartung: str | None = Form(None),
    next_due_date: str | None = Form(None),
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)
    policy = db.get(InsurancePolicy, policy_id)
    if policy is None or policy.object_id != obj.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Police nicht gefunden")

    bezeichnung = _normalize_text(bezeichnung)
    if not bezeichnung:
        return HTMLResponse(
            content="<p class='text-red-600 text-sm p-2'>Bezeichnung ist Pflichtfeld.</p>",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    parsed_dienstleister_id: uuid.UUID | None = None
    if dienstleister_id and dienstleister_id.strip():
        try:
            parsed_dienstleister_id = uuid.UUID(dienstleister_id.strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="Ungültige Dienstleister-ID")
        if db.get(Dienstleister, parsed_dienstleister_id) is None:
            return HTMLResponse(
                content="<p class='text-red-600 text-sm p-2'>Dienstleister nicht gefunden.</p>",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    parsed_intervall: int | None = None
    if intervall_monate and intervall_monate.strip():
        try:
            parsed_intervall = int(intervall_monate.strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="Ungültige Intervall-Angabe")
        if parsed_intervall is not None and parsed_intervall < 1:
            return HTMLResponse(
                content="<p class='text-red-600 text-sm p-2'>Intervall muss mindestens 1 Monat sein.</p>",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if parsed_intervall is not None and parsed_intervall > 600:
            return HTMLResponse(
                content="<p class='text-red-600 text-sm p-2'>Intervall zu groß (max 600 Monate / 50 Jahre).</p>",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    parsed_letzte = _parse_date(letzte_wartung)
    parsed_next = _parse_date(next_due_date)

    warn = validate_wartung_dates(parsed_letzte, parsed_intervall, parsed_next)
    if warn and "muss nach" in warn:
        return HTMLResponse(
            content=f"<p class='text-red-600 text-sm p-2'>{warn}</p>",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    wart = create_wartungspflicht(
        db,
        policy,
        user,
        request,
        bezeichnung=bezeichnung,
        dienstleister_id=parsed_dienstleister_id,
        intervall_monate=parsed_intervall,
        letzte_wartung=parsed_letzte,
        next_due_date=parsed_next,
    )
    db.commit()
    db.refresh(wart)
    db.refresh(policy)

    dienstleister_list = get_all_dienstleister(db)
    ctx = {
        "obj": obj,
        "policy": policy,
        "dienstleister_list": dienstleister_list,
        "get_due_severity": get_due_severity,
        "user": user,
    }
    if warn:
        ctx["soft_warn"] = warn
    return templates.TemplateResponse(request, "_obj_versicherungen_row.html", ctx)


@router.delete(
    "/{object_id}/wartungspflichten/{wart_id}",
    response_class=HTMLResponse,
)
async def wartungspflicht_delete(
    object_id: uuid.UUID,
    wart_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)
    wart = db.get(Wartungspflicht, wart_id)
    if wart is None or wart.object_id != obj.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wartungspflicht nicht gefunden")

    # Cross-Police-Guard: defense in depth gegen manipulierte Daten
    if wart.policy and wart.policy.object_id != obj.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wartungspflicht nicht gefunden")

    policy = wart.policy
    delete_wartungspflicht(db, wart, user, request)
    db.commit()

    if policy is None:
        return HTMLResponse(content="", status_code=200)

    db.refresh(policy)
    dienstleister_list = get_all_dienstleister(db)
    return templates.TemplateResponse(
        request,
        "_obj_versicherungen_row.html",
        {
            "obj": obj,
            "policy": policy,
            "dienstleister_list": dienstleister_list,
            "get_due_severity": get_due_severity,
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Menschen-Notizen (Story 2.4) — Inline-Edit fuer Eigentuemer-Notizen.
# view_confidential ist Pflicht fuer alle drei Endpoints.
# ---------------------------------------------------------------------------


@router.get("/{object_id}/menschen-notizen/{eigentuemer_id}/view", response_class=HTMLResponse)
async def notiz_view(
    object_id: uuid.UUID,
    eigentuemer_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:view_confidential")),
    db: Session = Depends(get_db),
):
    obj = _load_accessible_object(db, object_id, user)
    eig = db.get(Eigentuemer, eigentuemer_id)
    if not eig or eig.object_id != obj.id:
        raise HTTPException(404, detail="Eigentümer nicht gefunden")
    note_text = (obj.notes_owners or {}).get(str(eigentuemer_id)) or ""
    return templates.TemplateResponse(
        request, "_obj_notiz_view.html",
        {"obj": obj, "eig": eig, "note_text": note_text, "user": user},
    )


@router.get("/{object_id}/menschen-notizen/{eigentuemer_id}/edit", response_class=HTMLResponse)
async def notiz_edit(
    object_id: uuid.UUID,
    eigentuemer_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "objects:view_confidential"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für vertrauliche Felder",
        )
    obj = _load_accessible_object(db, object_id, user)
    eig = db.get(Eigentuemer, eigentuemer_id)
    if not eig or eig.object_id != obj.id:
        raise HTTPException(404, detail="Eigentümer nicht gefunden")
    note_text = (obj.notes_owners or {}).get(str(eigentuemer_id)) or ""
    return templates.TemplateResponse(
        request, "_obj_notiz_edit.html",
        {"obj": obj, "eig": eig, "note_text": note_text, "user": user},
    )


@router.post("/{object_id}/menschen-notizen/{eigentuemer_id}", response_class=HTMLResponse)
async def notiz_save(
    object_id: uuid.UUID,
    eigentuemer_id: uuid.UUID,
    request: Request,
    note: str | None = Form(None, max_length=4000),
    user: User = Depends(require_permission("objects:edit")),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "objects:view_confidential"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für vertrauliche Felder",
        )
    obj = _load_accessible_object(db, object_id, user)
    eig = db.get(Eigentuemer, eigentuemer_id)
    if not eig or eig.object_id != obj.id:
        raise HTTPException(404, detail="Eigentümer nicht gefunden")

    # Row-Lock VOR dem JSONB-Snapshot: serialisiert parallele notes_owners-Saves
    # (Race-Condition zwei Admins, Defer #83).
    db.execute(select(Object).where(Object.id == object_id).with_for_update())

    new_notes = dict(obj.notes_owners or {})
    note_clean = (note or "").strip()
    if note_clean:
        new_notes[str(eigentuemer_id)] = note_clean
    else:
        new_notes.pop(str(eigentuemer_id), None)

    write_field_human(
        db, entity=obj, field="notes_owners", value=new_notes,
        source="user_edit", user=user, request=request,
    )
    db.commit()

    note_text = new_notes.get(str(eigentuemer_id)) or ""
    return templates.TemplateResponse(
        request, "_obj_notiz_view.html",
        {"obj": obj, "eig": eig, "note_text": note_text, "user": user},
    )
