"""Router fuer das ETV-Unterschriftenlisten-Modul.

Read-/Render-Pfad: User waehlt eine Conference, das Modul laedt 6 Facilioo-
Endpunkte (parallel via :func:`fetch_conference_signature_payload`) und
rendert eine druckfertige A4-Querformat-Liste via WeasyPrint.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User, Workflow
from app.permissions import (
    RESOURCE_TYPE_WORKFLOW,
    can_access_resource,
)
from app.services.audit import audit
from app.services.facilioo_client import (
    FaciliooError,
    fetch_conference_signature_payload,
    list_conferences,
    list_conferences_with_properties,
)
from app.templating import templates


ETV_WORKFLOW_KEY = "etv_signature_list"

router = APIRouter(prefix="/workflows/etv-signature-list", tags=["etv"])

_logger = logging.getLogger(__name__)


def _load_workflow_or_403(db: Session, user: User) -> Workflow:
    wf = db.query(Workflow).filter(Workflow.key == ETV_WORKFLOW_KEY).first()
    if wf is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow '{ETV_WORKFLOW_KEY}' nicht gefunden.",
        )
    if not can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung fuer den ETV-Unterschriftenlisten-Workflow.",
        )
    return wf


def _parse_conference_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    # Facilioo liefert ISO-8601, mit oder ohne Zeitzone. fromisoformat ab
    # Python 3.11 toleriert "Z" — sicherheitshalber normalisieren.
    cleaned = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _format_conference_label(conf: dict) -> str:
    """Format fuer das Dropdown: 'YYYY-MM-DD HH:MM · WEG-Kuerzel — title (state)'.

    WEG-Kuerzel kommt aus ``_property_number`` (befuellt von
    ``list_conferences_with_properties``), Fallback bleibt das alte Format.
    """
    dt = _parse_conference_date(conf.get("date"))
    date_part = dt.strftime("%Y-%m-%d %H:%M") if dt else "ohne Datum"
    title = conf.get("title") or "ohne Titel"
    state = conf.get("state")
    state_part = f" ({state})" if state else ""
    weg_number = conf.get("_property_number")
    weg_part = f" · {weg_number}" if weg_number else ""
    return f"{date_part}{weg_part} — {title}{state_part}"


_FILENAME_KEEP = re.compile(r"[^a-z0-9]+")


def _slug(value: str | None, fallback: str = "etv") -> str:
    if not value:
        return fallback
    norm = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    norm = norm.lower()
    norm = _FILENAME_KEEP.sub("-", norm).strip("-")
    return norm or fallback


def _build_filename(conf: dict, property_: dict) -> str:
    dt = _parse_conference_date(conf.get("date"))
    date_part = dt.strftime("%Y-%m-%d") if dt else "no-date"
    return f"etv-{date_part}-{_slug(property_.get('name'), 'unterschriften')}.pdf"


def _build_rows(payload: dict) -> list[dict]:
    """Aggregiert das Facilioo-Payload zu Tabellen-Rows fuers PDF-Template.

    Vollmacht-Box ist genau dann vorgekreuzt, wenn mindestens eine Party der
    Voting-Group als ``propertyOwnerId`` in einem Mandat-Eintrag vorkommt.
    """
    mandate_owner_ids = {
        m.get("propertyOwnerId")
        for m in payload.get("mandates", [])
        if m.get("propertyOwnerId") is not None
    }

    rows: list[dict] = []
    for entry in payload.get("voting_groups", []):
        vg = entry.get("voting_group") or {}
        parties = vg.get("parties") or []
        units = vg.get("units") or []

        owner_names = [
            (p.get("fullName") or "").strip()
            for p in parties
            if (p.get("fullName") or "").strip()
        ]
        unit_labels = []
        for u in units:
            number = (u.get("number") or "").strip()
            position = (u.get("position") or "").strip()
            if number and position:
                unit_labels.append(f"{number} ({position})")
            elif number:
                unit_labels.append(number)
            elif position:
                unit_labels.append(position)

        has_mandate = any(
            (p.get("id") in mandate_owner_ids) for p in parties
        )

        rows.append({
            "owner_names": ", ".join(owner_names) if owner_names else "—",
            "units": " · ".join(unit_labels) if unit_labels else "—",
            "shares": entry.get("shares", "") or "—",
            "has_mandate": has_mandate,
        })
    return rows


def _build_header(payload: dict) -> dict:
    conf = payload.get("conference") or {}
    prop = payload.get("property") or {}
    dt = _parse_conference_date(conf.get("date"))
    return {
        "weg_name": prop.get("name") or "—",
        "date_label": dt.strftime("%d.%m.%Y") if dt else "—",
        "time_label": dt.strftime("%H:%M") if dt else "—",
        "location": conf.get("location") or "",
        "room": conf.get("room") or "",
        "title": conf.get("title") or "",
    }


@router.get("/", response_class=HTMLResponse)
async def select_conference(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _load_workflow_or_403(db, user)

    error: str | None = None
    conferences: list[dict] = []
    try:
        conferences = await list_conferences_with_properties()
    except FaciliooError as exc:
        _logger.warning("Facilioo list_conferences fehlgeschlagen: %s", exc)
        error = (
            "Facilioo aktuell nicht erreichbar — bitte spaeter erneut "
            "versuchen."
        )

    # Sortierung: neueste zuerst (None ans Ende).
    def _sort_key(c: dict) -> tuple[int, str]:
        raw = c.get("date") or ""
        return (0 if raw else 1, raw)

    conferences_sorted = sorted(conferences, key=_sort_key)
    conferences_sorted.reverse()  # desc auf den vorhandenen Datums-Eintraegen

    options = [
        {
            "id": c.get("id"),
            "label": _format_conference_label(c),
        }
        for c in conferences_sorted
        if c.get("id") is not None
    ]

    return templates.TemplateResponse(
        request,
        "etv_signature_list_select.html",
        {
            "title": "ETV-Unterschriftenliste",
            "user": user,
            "options": options,
            "error": error,
        },
    )


@router.post("/generate")
async def generate_pdf(
    request: Request,
    conference_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _load_workflow_or_403(db, user)

    # WeasyPrint-Import erst hier — er zieht zur Importzeit System-Libs
    # (libpango, libcairo). So bleibt der Test-Suite-Import unbelastet,
    # selbst wenn weasyprint lokal noch nicht installiert ist.
    try:
        from weasyprint import HTML  # type: ignore
    except ImportError as exc:  # pragma: no cover — Build-Voraussetzung
        _logger.error("WeasyPrint-Import fehlgeschlagen: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF-Renderer nicht verfuegbar. Bitte Container-Build pruefen.",
        ) from exc

    try:
        payload = await fetch_conference_signature_payload(conference_id)
    except FaciliooError as exc:
        _logger.warning(
            "Facilioo fetch_conference_signature_payload fehlgeschlagen "
            "(conf_id=%s): %s",
            conference_id,
            exc,
        )
        # Auswahl-Screen mit Banner, Status 200 — kein 500er.
        try:
            conferences = await list_conferences_with_properties()
        except FaciliooError:
            conferences = []
        options = [
            {"id": c.get("id"), "label": _format_conference_label(c)}
            for c in conferences
            if c.get("id") is not None
        ]
        message = (
            f"Facilioo konnte die Conference '{conference_id}' nicht laden: "
            f"{exc}"
        )
        return templates.TemplateResponse(
            request,
            "etv_signature_list_select.html",
            {
                "title": "ETV-Unterschriftenliste",
                "user": user,
                "options": options,
                "error": message,
            },
        )

    header = _build_header(payload)
    rows = _build_rows(payload)

    html_str = templates.get_template("etv_signature_list_pdf.html").render(
        {
            "header": header,
            "rows": rows,
            "now": datetime.now(),
        }
    )

    pdf_bytes = HTML(string=html_str).write_pdf()

    audit(
        db,
        user,
        "etv_signature_list_generated",
        entity_type="facilioo_conference",
        entity_id=uuid.uuid4(),  # lokal keine Conference-Entity — Audit-only.
        details={
            "conference_id": conference_id,
            "conference_title": (payload.get("conference") or {}).get("title"),
            "row_count": len(rows),
            "mandate_count": sum(1 for r in rows if r["has_mandate"]),
        },
        request=request,
    )
    db.commit()

    filename = _build_filename(
        payload.get("conference") or {}, payload.get("property") or {}
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
