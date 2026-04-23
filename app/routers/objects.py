"""Read-only Objekt-Routes fuer Cluster 1 (Stammdaten).

Liste `/objects` + Detailseite `/objects/{id}` mit Stammdaten- und Finanzen-
Sektion (Story 1.5). Keine Write-Endpoints — Sektion-POSTs fuer Technik,
Versicherungen etc. kommen mit Stories 1.6+.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Object, User
from app.permissions import accessible_object_ids, require_permission
from app.services.impower import get_bank_balance
from app.services.audit import audit
from app.services.field_encryption import DecryptionError, decrypt_field
from app.services.steckbrief import (
    TECHNIK_ABSPERRPUNKTE,
    TECHNIK_FIELD_KEYS,
    TECHNIK_FIELDS,
    TECHNIK_HEIZUNG,
    TECHNIK_HISTORIE,
    ZUGANGSCODE_FIELD_KEYS,
    ZUGANGSCODE_FIELDS,
    TechnikField,
    build_sparkline_svg,
    get_object_detail,
    get_provenance_map,
    has_any_impower_provenance,
    list_objects_with_unit_counts,
    parse_technik_value,
    parse_zugangscode_value,
    reserve_history_for_sparkline,
)
from app.services.steckbrief_write_gate import write_field_human
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

    # --- Zugangscodes (Fernet-decrypted, AC2/AC3) ---
    zug_prov_map = get_provenance_map(
        db, "object", detail.obj.id,
        tuple(f.key for f in ZUGANGSCODE_FIELDS),
    )
    tech_zugangscodes: list[dict] = []
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
                    "Code nicht verfuegbar — Schluessel-Konfiguration pruefen"
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
                "Code nicht verfuegbar — Schluessel-Konfiguration pruefen"
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
    user: User = Depends(require_permission("objects:view")),
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
