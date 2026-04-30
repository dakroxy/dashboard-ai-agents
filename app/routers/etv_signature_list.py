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
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

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
from app.services.facilioo import (
    FaciliooError,
    fetch_conference_signature_payload,
    list_conferences,
    list_conferences_with_properties,
)
from app.templating import templates


ETV_WORKFLOW_KEY = "etv_signature_list"

router = APIRouter(prefix="/workflows/etv-signature-list", tags=["etv"])

_logger = logging.getLogger(__name__)
_BERLIN_TZ = ZoneInfo("Europe/Berlin")


class _WorkflowMissing(Exception):
    """Wird geworfen wenn die Workflow-Row im DB-Seed fehlt — der Caller
    rendert den Auswahl-Screen mit Banner statt einer 500."""


def _load_workflow_or_403(db: Session, user: User) -> Workflow:
    wf = db.query(Workflow).filter(Workflow.key == ETV_WORKFLOW_KEY).first()
    if wf is None:
        # Kein 500er ans Browser-Frame — Spec-Boundary "Always: HTTP-Errors
        # → user-friendly Meldung, niemals 500er". Caller behandelt das
        # ueber den Banner-Pfad.
        raise _WorkflowMissing()
    if not can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für den ETV-Unterschriftenlisten-Workflow.",
        )
    return wf


_MEA_PLACEHOLDER = "—"


def _format_decimal(d: Decimal) -> str:
    """Decimal in Fixed-Notation, Trailing-Zeros + Trailing-Punkt entfernt.

    `Decimal("128").normalize()` rutscht in Exponential-Notation (`1.28E+2`),
    was im PDF unleserlich waere. `format(d, "f")` zwingt Fixed-Notation, der
    rstrip-Schritt bringt `128.00` zu `128` und `98.50` zu `98.5`.
    """
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _format_mea(d: Decimal | None) -> str:
    """`Decimal | None` → Display-String fuer die MEA-Spalte."""
    if d is None:
        return _MEA_PLACEHOLDER
    return _format_decimal(d)


def _compute_total_mea(payload: dict) -> str:
    """Summiert alle gepflegten MEA-Werte aller Voting-Groups."""
    total = Decimal("0")
    seen = False
    for entry in payload.get("voting_groups", []):
        d = entry.get("mea_decimal")
        if d is None:
            continue
        total += d
        seen = True
    return _format_decimal(total) if seen else _MEA_PLACEHOLDER


def _parse_conference_date(raw: str | None) -> datetime | None:
    """Parst Facilioo-Datum als tz-aware Europe/Berlin.

    Facilioo liefert ISO-8601 mit oder ohne Zeitzone. ``fromisoformat`` ab
    Python 3.11 toleriert ``Z``. Werte ohne Zone werden als Europe/Berlin
    interpretiert (Facilioo-Server steht in DE und schreibt Termine lokal),
    Werte mit Zone werden nach Europe/Berlin konvertiert. Damit rendern
    ``%H:%M`` / ``%d.%m.%Y`` deterministisch (AC4: "PLS22 18:30").
    """
    if not raw:
        return None
    cleaned = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_BERLIN_TZ)
    return dt.astimezone(_BERLIN_TZ)


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

    Wir vergleichen ``voting_group.parties[].id`` direkt mit
    ``mandates[].propertyOwnerId``. Live-Smoke 2026-04-29 (PLS22 Hildesheim,
    conference_id=6944) hat exakt 3 vorgekreuzte Boxes erzeugt — genau wie
    erwartet. Damit ist die Aequivalenz fuer den DBS-Datenstand belegt; falls
    Facilioo das ID-Schema mal aendert (Vertreter-Parties mit eigener ID etc.),
    wuerde sich das in falschen Box-Counts zeigen.
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
            "shares": _format_mea(entry.get("mea_decimal")),
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
    try:
        _load_workflow_or_403(db, user)
    except _WorkflowMissing:
        return _render_select_error(
            request,
            user,
            options=[],
            message=(
                "ETV-Unterschriftenliste-Workflow ist in der Datenbank nicht "
                "geseedet. Bitte App neu starten oder Admin kontaktieren."
            ),
        )

    error: str | None = None
    conferences: list[dict] = []
    try:
        conferences = await list_conferences_with_properties()
    except FaciliooError as exc:
        _logger.warning("Facilioo list_conferences fehlgeschlagen: %s", exc)
        error = (
            "Facilioo aktuell nicht erreichbar — bitte später erneut "
            "versuchen."
        )

    # Sortierung: neueste zuerst (None ans Ende). Sortiert auf geparstem
    # Datum, damit gemischte Timezone-Offsets (`+02:00` vs `Z`) korrekt
    # vergleichen — naive String-Sortierung wuerde sonst kippen.
    def _sort_key(c: dict) -> tuple[int, float]:
        dt = _parse_conference_date(c.get("date"))
        if dt is None:
            return (1, 0.0)
        return (0, dt.timestamp())

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


def _render_select_error(
    request: Request,
    user: User,
    *,
    options: list[dict],
    message: str,
) -> HTMLResponse:
    """Rendert den Auswahl-Screen mit Banner — gemeinsamer Pfad fuer alle
    User-facing-Errors auf POST/GET. HTTP 200, kein 500er."""
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


async def _options_for_error_screen() -> list[dict]:
    try:
        conferences = await list_conferences_with_properties()
    except FaciliooError:
        return []
    return [
        {"id": c.get("id"), "label": _format_conference_label(c)}
        for c in conferences
        if c.get("id") is not None
    ]


@router.post("/generate")
async def generate_pdf(
    request: Request,
    conference_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        _load_workflow_or_403(db, user)
    except _WorkflowMissing:
        return _render_select_error(
            request,
            user,
            options=await _options_for_error_screen(),
            message=(
                "ETV-Unterschriftenliste-Workflow ist in der Datenbank nicht "
                "geseedet. Bitte App neu starten oder Admin kontaktieren."
            ),
        )

    # WeasyPrint-Import erst hier — er zieht zur Importzeit System-Libs
    # (libpango, libcairo). So bleibt der Test-Suite-Import unbelastet,
    # selbst wenn weasyprint lokal noch nicht installiert ist.
    try:
        from weasyprint import HTML  # type: ignore
    except ImportError as exc:  # pragma: no cover — Build-Voraussetzung
        _logger.error("WeasyPrint-Import fehlgeschlagen: %s", exc)
        return _render_select_error(
            request,
            user,
            options=await _options_for_error_screen(),
            message=(
                "PDF-Renderer (WeasyPrint) ist im Container nicht verfügbar. "
                "Bitte Container-Build / Image prüfen."
            ),
        )

    try:
        payload = await fetch_conference_signature_payload(conference_id)
    except FaciliooError as exc:
        _logger.warning(
            "Facilioo fetch_conference_signature_payload fehlgeschlagen "
            "(conf_id=%s): %s",
            conference_id,
            exc,
        )
        return _render_select_error(
            request,
            user,
            options=await _options_for_error_screen(),
            message=(
                f"Facilioo konnte die Conference '{conference_id}' nicht "
                f"laden: {exc}"
            ),
        )

    header = _build_header(payload)
    rows = _build_rows(payload)
    mea_total = _compute_total_mea(payload)

    html_str = templates.get_template("etv_signature_list_pdf.html").render(
        {
            "header": header,
            "rows": rows,
            "mea_total": mea_total,
        }
    )

    try:
        pdf_bytes = HTML(string=html_str).write_pdf()
    except Exception as exc:  # noqa: BLE001 — WeasyPrint kann beliebige Render-Errors werfen
        _logger.exception(
            "WeasyPrint-Render fehlgeschlagen (conf_id=%s)", conference_id
        )
        return _render_select_error(
            request,
            user,
            options=await _options_for_error_screen(),
            message=(
                f"PDF-Erzeugung für Conference '{conference_id}' ist "
                f"fehlgeschlagen: {type(exc).__name__}. Bitte Logs prüfen."
            ),
        )

    audit(
        db,
        user,
        "etv_signature_list_generated",
        entity_type="facilioo_conference",
        # Conference ist eine externe Entity (Facilioo) — wir haben keine
        # lokale UUID dafuer. entity_id bleibt None, conference_id steht in
        # details.
        entity_id=None,
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
