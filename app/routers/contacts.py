"""Contact-Create Sub-Workflow (M5 Paket 6).

Standalone-Formular zum Anlegen eines Impower-Kontakts (Person /
Unternehmen / Verwaltungsunternehmen). Aus anderen Workflows (z. B.
Mietverwaltungs-Anlage) kann per ``?prefill=...``-Query vorbefuellt
werden (JSON-Encodiert), so dass der Eigentuemer-Block aus einem Case
direkt als Vorschlag erscheint.

Duplicate-Check laeuft immer vor der Anlage — Impower hat einen eigenen
Endpunkt dafuer. Der User bestaetigt explizit, bevor wir tatsaechlich
schreiben.
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User, Workflow
from app.permissions import (
    RESOURCE_TYPE_WORKFLOW,
    can_access_resource,
    has_permission,
)
from app.services.audit import audit
from app.services.impower import (
    ImpowerError,
    _build_contact_payload,
    check_contact_duplicates,
    create_contact,
)
from app.templating import templates

CONTACT_CREATE_WORKFLOW_KEY = "contact_create"


router = APIRouter(prefix="/contacts", tags=["contacts"])


def _load_workflow_or_403(db: Session, user: User) -> Workflow:
    wf = (
        db.query(Workflow)
        .filter(Workflow.key == CONTACT_CREATE_WORKFLOW_KEY)
        .first()
    )
    if wf is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow '{CONTACT_CREATE_WORKFLOW_KEY}' nicht gefunden.",
        )
    if not can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für den Kontakt-Anlage-Workflow.",
        )
    return wf


def _form_fields_from_request(form: dict) -> dict[str, Any]:
    """Liest alle Kontakt-Felder aus einem Form-Dict heraus. Wird sowohl vom
    initialen POST als auch vom confirm-POST benutzt."""
    return {
        "type": (form.get("type") or "PERSON").strip().upper(),
        "salutation": (form.get("salutation") or "").strip(),
        "title": (form.get("title") or "").strip(),
        "first_name": (form.get("first_name") or "").strip(),
        "last_name": (form.get("last_name") or "").strip(),
        "company_name": (form.get("company_name") or "").strip(),
        "trade_register_number": (form.get("trade_register_number") or "").strip(),
        "vat_id": (form.get("vat_id") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "phone_business": (form.get("phone_business") or "").strip(),
        "phone_mobile": (form.get("phone_mobile") or "").strip(),
        "phone_private": (form.get("phone_private") or "").strip(),
        "notes": (form.get("notes") or "").strip(),
        # Eine einzelne Adresse im Formular — Impower erlaubt mehrere, aber
        # fuer den MVP reicht eine. Erweiterung spaeter.
        "addr_street": (form.get("addr_street") or "").strip(),
        "addr_number": (form.get("addr_number") or "").strip(),
        "addr_postal_code": (form.get("addr_postal_code") or "").strip(),
        "addr_city": (form.get("addr_city") or "").strip(),
        "addr_country": (form.get("addr_country") or "DE").strip(),
    }


def _build_payload_from_fields(fields: dict) -> dict:
    address = None
    if fields["addr_street"] or fields["addr_postal_code"] or fields["addr_city"]:
        address = {
            "street": fields["addr_street"] or None,
            "number": fields["addr_number"] or None,
            "postalCode": fields["addr_postal_code"] or None,
            "city": fields["addr_city"] or None,
            "country": fields["addr_country"] or "DE",
            "forInvoice": True,
            "forMail": True,
        }
    return _build_contact_payload(
        fields["type"],
        salutation=fields["salutation"] or None,
        title=fields["title"] or None,
        first_name=fields["first_name"] or None,
        last_name=fields["last_name"] or None,
        company_name=fields["company_name"] or None,
        trade_register_number=fields["trade_register_number"] or None,
        vat_id=fields["vat_id"] or None,
        email=fields["email"] or None,
        phone_business=fields["phone_business"] or None,
        phone_mobile=fields["phone_mobile"] or None,
        phone_private=fields["phone_private"] or None,
        addresses=[address] if address else None,
        notes=fields["notes"] or None,
    )


@router.get("/new", response_class=HTMLResponse)
async def new_contact_form(
    request: Request,
    prefill: str = "",
    return_to: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Leeres oder vorbefuelltes Kontakt-Formular.

    ``prefill`` ist ein URL-sicherer JSON-String mit einzelnen Feldern, damit
    das Formular aus anderen Kontexten (z. B. case_detail.html Eigentuemer-
    Sektion) vorbefuellt werden kann. ``return_to`` ist eine interne URL, zu
    der nach erfolgreicher Anlage weitergeleitet wird.
    """
    _load_workflow_or_403(db, user)
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )

    fields: dict[str, Any] = {
        "type": "PERSON",
        "salutation": "",
        "title": "",
        "first_name": "",
        "last_name": "",
        "company_name": "",
        "trade_register_number": "",
        "vat_id": "",
        "email": "",
        "phone_business": "",
        "phone_mobile": "",
        "phone_private": "",
        "notes": "",
        "addr_street": "",
        "addr_number": "",
        "addr_postal_code": "",
        "addr_city": "",
        "addr_country": "DE",
    }
    if prefill:
        try:
            data = json.loads(prefill)
            if isinstance(data, dict):
                for k in fields:
                    if k in data and data[k] is not None:
                        fields[k] = str(data[k])
        except json.JSONDecodeError:
            pass

    return templates.TemplateResponse(
        request,
        "contact_create.html",
        {
            "title": "Kontakt anlegen",
            "user": user,
            "fields": fields,
            "duplicates": None,
            "return_to": return_to or "",
            "error": None,
            "payload_json": None,
        },
    )


@router.post("/new", response_class=HTMLResponse)
async def check_and_confirm_contact(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 1: Duplicate-Check. Rendert Form mit Duplicate-Warnungen + hidden
    Payload-JSON. Der User klickt dann entweder auf "Bestaetigen und Anlegen"
    (-> POST /contacts/confirm) oder auf einen bestehenden Treffer."""
    _load_workflow_or_403(db, user)
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )

    form = await request.form()
    fields = _form_fields_from_request(dict(form))
    return_to = (form.get("return_to") or "").strip()

    # Minimale Validierung: entweder last_name oder company_name muss da sein
    minimal_ok = fields["last_name"] or fields["company_name"]
    if not minimal_ok:
        return templates.TemplateResponse(
            request,
            "contact_create.html",
            {
                "title": "Kontakt anlegen",
                "user": user,
                "fields": fields,
                "duplicates": None,
                "return_to": return_to,
                "error": "Bitte mindestens Nachname ODER Firma angeben.",
                "payload_json": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    payload = _build_payload_from_fields(fields)
    duplicates: list[dict] = []
    error: str | None = None
    try:
        duplicates = await check_contact_duplicates(payload)
    except ImpowerError as exc:
        # Duplicate-Check-Fehler ist kein harter Blocker — der User kann
        # trotzdem anlegen (Impower haette sonst beim Create ebenfalls haken).
        error = f"Duplicate-Check fehlgeschlagen: {exc}"

    return templates.TemplateResponse(
        request,
        "contact_create.html",
        {
            "title": "Kontakt anlegen",
            "user": user,
            "fields": fields,
            "duplicates": duplicates,
            "return_to": return_to,
            "error": error,
            "payload_json": json.dumps(payload, ensure_ascii=False),
        },
    )


@router.post("/confirm")
async def confirm_create_contact(
    request: Request,
    payload_json: str = Form(...),
    return_to: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 2: tatsaechliche Anlage. Nutzt den im Duplicate-Check gebauten
    Payload direkt aus dem Hidden-Field (damit Felder 100% gleich sind wie
    beim Check)."""
    _load_workflow_or_403(db, user)
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )

    try:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise ValueError("payload nicht Objekt")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültiger payload_json: {exc}",
        )

    try:
        contact = await create_contact(payload)
    except ImpowerError as exc:
        # Fallback: Formular mit Fehler rendern
        return templates.TemplateResponse(
            request,
            "contact_create.html",
            {
                "title": "Kontakt anlegen",
                "user": user,
                "fields": {
                    "type": payload.get("type", "PERSON"),
                    "salutation": payload.get("salutation", ""),
                    "title": payload.get("title", ""),
                    "first_name": payload.get("firstName", ""),
                    "last_name": payload.get("lastName", ""),
                    "company_name": payload.get("companyName", ""),
                    "trade_register_number": payload.get("tradeRegisterNumber", ""),
                    "vat_id": payload.get("vatId", ""),
                    "email": payload.get("email", ""),
                    "phone_business": payload.get("phoneBusiness", ""),
                    "phone_mobile": payload.get("phoneMobile", ""),
                    "phone_private": payload.get("phonePrivate", ""),
                    "notes": payload.get("notes", ""),
                    "addr_street": (payload.get("addresses") or [{}])[0].get("street", ""),
                    "addr_number": (payload.get("addresses") or [{}])[0].get("number", ""),
                    "addr_postal_code": (payload.get("addresses") or [{}])[0].get("postalCode", ""),
                    "addr_city": (payload.get("addresses") or [{}])[0].get("city", ""),
                    "addr_country": (payload.get("addresses") or [{}])[0].get("country", "DE"),
                },
                "duplicates": None,
                "return_to": return_to,
                "error": f"Anlage fehlgeschlagen: {exc}",
                "payload_json": payload_json,
            },
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    audit(
        db,
        user,
        "contact_created",
        entity_type="contact",
        entity_id=uuid.uuid4(),  # lokaler Audit-Eintrag (kein internes Contact-Model)
        details={
            "impower_contact_id": contact.get("id"),
            "type": payload.get("type"),
            "display_name": (
                payload.get("companyName")
                or f"{payload.get('firstName', '')} {payload.get('lastName', '')}".strip()
            ),
        },
        request=request,
    )
    db.commit()

    if return_to:
        sep = "&" if "?" in return_to else "?"
        url = (
            f"{return_to}{sep}contact_created_id={contact.get('id')}"
            f"&contact_created_name={quote(str(payload.get('companyName') or payload.get('lastName') or ''))}"
        )
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    # Kein return_to → zurueck zum Formular mit Success-Message
    return templates.TemplateResponse(
        request,
        "contact_create.html",
        {
            "title": "Kontakt anlegen",
            "user": user,
            "fields": None,  # leeres Formular fuer den naechsten Kontakt
            "duplicates": None,
            "return_to": "",
            "error": None,
            "payload_json": None,
            "success_contact": contact,
        },
    )
