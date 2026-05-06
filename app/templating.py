"""Zentrale Jinja2Templates-Instanz mit projektweiten Globals und Filtern.

Alle Router importieren `templates` von hier, damit Filter (iban_format)
und Globals (has_permission) ueberall verfuegbar sind — sonst crasht
ein Template-Block, der in einem Router definiert ist und eine
Helper-Funktion eines anderen Router erwartet.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import select_autoescape
from markupsafe import Markup, escape
from starlette.requests import Request

from app.db import SessionLocal
from app.models import User, Workflow
from app.permissions import accessible_workflow_ids, has_permission
from app.services.facilioo_tickets import facilioo_ticket_url
from app.services.mietverwaltung import field_source
from app.services.steckbrief import ProvenanceWithUser

_logger = logging.getLogger(__name__)


# Human-readable Labels fuer Steckbrief-Felder (fuer den field_label-Filter).
# Fallback: k.replace("_", " ").title() fuer unbekannte Felder.
FIELD_LABEL_MAP: dict[str, str] = {
    "year_built": "Baujahr",
    "year_roof": "Dachjahr",
    "weg_nr": "WEG-Nr.",
    "impower_property_id": "Impower-ID",
    "full_address": "Adresse",
    "reserve_current": "Rücklage",
    "reserve_target": "Rücklage (Soll)",
    "last_known_balance": "Kontosaldo",
    "short_code": "Kürzel",
    "shutoff_water_location": "Absperrung Wasser",
    "shutoff_electricity_location": "Absperrung Strom",
    "heating_type": "Heizungstyp",
    "sepa_mandate_refs": "SEPA-Mandate",
    "wirtschaftsplan_status": "Wirtschaftsplan-Status",
    "notes_owners": "Eigentümer-Notizen",
    "entry_code_main_door": "Hauseingang",
    "entry_code_garage": "Garage",
    "entry_code_technical_room": "Technikraum",
}


_SIDEBAR_WORKFLOWS_CACHE: dict[uuid.UUID, tuple[float, list[dict[str, Any]]]] = {}
_SIDEBAR_WORKFLOWS_TTL_SECONDS = 30
# Hard-Cap: schuetzt vor Memory-Wachstum bei vielen kurzlebigen Sessions
# (User schliesst Browser ohne Logout — Cache-Eintrag bleibt bis Server-Restart).
_SIDEBAR_WORKFLOWS_CACHE_MAX = 1000


# Pro Workflow-Key: Sidebar-URL + Inline-SVG-Pfad. Halten wir hier zentral,
# damit base.html (Sidebar) und index.html (Tile) nicht aus dem Tritt geraten.
# Default gilt fuer "freshly seeded"-Workflows ohne expliziten Eintrag — sie
# zeigen weiterhin auf die generische Workflow-Konfig-Seite, sind aber sichtbar.
_WORKFLOW_SIDEBAR_META: dict[str, dict[str, str]] = {
    "sepa_mandate": {
        "url": "/documents/",
        "icon": "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
    },
    "mietverwaltung_setup": {
        "url": "/cases/",
        "icon": "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4",
    },
    "etv_signature_list": {
        "url": "/workflows/etv-signature-list/",
        "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4",
    },
    "contact_create": {
        "url": "/contacts/new",
        "icon": "M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z",
    },
}


def sidebar_workflows(user: User | None) -> list[dict[str, Any]]:
    """Liefert die Workflow-Eintraege fuer die linke Sidebar.

    TTL-Cache (30 s) verhindert DB-Hit pro Page-Render. Logout invalidiert
    den Cache-Eintrag (via `_SIDEBAR_WORKFLOWS_CACHE.pop(user.id, None)`
    im Logout-Handler in `app/routers/auth.py`).
    """
    if user is None:
        return []
    now = time.monotonic()
    cached = _SIDEBAR_WORKFLOWS_CACHE.get(user.id)
    if cached is not None and (now - cached[0]) < _SIDEBAR_WORKFLOWS_TTL_SECONDS:
        return cached[1]
    db = SessionLocal()
    try:
        ids = accessible_workflow_ids(db, user)
        if not ids:
            items: list[dict[str, Any]] = []
        else:
            workflows = (
                db.query(Workflow)
                .filter(Workflow.active.is_(True), Workflow.id.in_(ids))
                .order_by(Workflow.name.asc())
                .all()
            )
            items = []
            for wf in workflows:
                meta = _WORKFLOW_SIDEBAR_META.get(wf.key, {"url": f"/workflows/{wf.key}", "icon": ""})
                items.append({"key": wf.key, "name": wf.name, "url": meta["url"], "icon": meta["icon"]})
    finally:
        db.close()
    # Bei Cache-Miss: zuerst abgelaufene Eintraege aufraeumen, sonst waechst
    # der Dict monoton bei vielen verschiedenen Usern (kein LRU noetig — TTL
    # ist die Wahrheit). Hard-Cap als zusaetzliche Sicherheit.
    if len(_SIDEBAR_WORKFLOWS_CACHE) >= _SIDEBAR_WORKFLOWS_CACHE_MAX:
        ttl = _SIDEBAR_WORKFLOWS_TTL_SECONDS
        stale = [k for k, (ts, _) in _SIDEBAR_WORKFLOWS_CACHE.items() if (now - ts) >= ttl]
        for k in stale:
            _SIDEBAR_WORKFLOWS_CACHE.pop(k, None)
        # Falls trotzdem noch ueber dem Cap (kein TTL-Eintrag stale): aeltesten
        # Eintrag entfernen, um den neuen Schluessel reinzukriegen.
        if len(_SIDEBAR_WORKFLOWS_CACHE) >= _SIDEBAR_WORKFLOWS_CACHE_MAX:
            oldest_key = min(_SIDEBAR_WORKFLOWS_CACHE, key=lambda k: _SIDEBAR_WORKFLOWS_CACHE[k][0])
            _SIDEBAR_WORKFLOWS_CACHE.pop(oldest_key, None)
    _SIDEBAR_WORKFLOWS_CACHE[user.id] = (now, items)
    return items


def _format_iban(value: str | None) -> str:
    """Gruppiert eine IBAN in 4er-Blocks (reine Anzeige, Speicherung bleibt kompakt)."""
    if not value:
        return ""
    clean = str(value).replace(" ", "").upper()
    return " ".join(clean[i : i + 4] for i in range(0, len(clean), 4))


# Render-Tabelle fuer Provenance-Pills. Zentral, damit Story 3.5 (Review-Queue-UI)
# dieselben Labels/Farben wiederverwenden kann.
_PROV_RENDER: dict[str, dict[str, str]] = {
    "user_edit": {
        "label": "Manuell",
        "color_class": "bg-emerald-100 text-emerald-800 border border-emerald-200",
    },
    "impower_mirror": {
        "label": "Impower",
        "color_class": "bg-sky-100 text-sky-800 border border-sky-200",
    },
    "facilioo_mirror": {
        "label": "Facilioo",
        "color_class": "bg-sky-100 text-sky-800 border border-sky-200",
    },
    "sharepoint_mirror": {
        "label": "SharePoint",
        "color_class": "bg-sky-100 text-sky-800 border border-sky-200",
    },
    "ai_suggestion": {
        "label": "KI (approved)",
        "color_class": "bg-amber-100 text-amber-800 border border-amber-200",
    },
    "missing": {
        "label": "Leer",
        "color_class": "bg-slate-100 text-slate-500 border border-slate-200",
    },
}


def _prov_tooltip(wrap: ProvenanceWithUser | None) -> str:
    if wrap is None:
        return "Noch nicht gepflegt"
    prov = wrap.prov
    # Timestamps in DB = UTC; fuer CET/CEST korrekte Darstellung ggf. pytz ergaenzen.
    ts = prov.created_at.strftime("%Y-%m-%d %H:%M UTC") if prov.created_at else ""
    if prov.source == "user_edit":
        if wrap.user_email:
            return f"Manuell gepflegt am {ts} von {wrap.user_email}"
        if prov.user_id is None:
            return f"Manuell gepflegt am {ts} [gelöschter Nutzer]"
        return f"Manuell gepflegt am {ts}"
    if prov.source == "impower_mirror":
        ref = f" (Ref {prov.source_ref})" if prov.source_ref else ""
        return f"Aus Impower gespiegelt am {ts}{ref}"
    if prov.source in {"facilioo_mirror", "sharepoint_mirror"}:
        label = _PROV_RENDER[prov.source]["label"]
        ref = f" (Ref {prov.source_ref})" if prov.source_ref else ""
        return f"Aus {label} gespiegelt am {ts}{ref}"
    if prov.source == "ai_suggestion":
        return f"KI-Vorschlag freigegeben am {ts}"
    return f"Quelle {prov.source} am {ts}"


def provenance_pill(wrap: ProvenanceWithUser | None) -> dict[str, Any]:
    """Liefert ein Render-Dict fuer die Feld-Pill auf der Objekt-Detailseite.

    Signature ist bewusst dict-basiert (nicht Dataclass), damit Jinja direkt
    `.source` / `.label` / `.color_class` / `.tooltip` ansprechen kann. Das
    `data-source`-Attribut im Template nutzt dasselbe `source`-Feld und bleibt
    damit stabil fuer Tests + Admin-UI.
    """
    if wrap is None:
        render = _PROV_RENDER["missing"]
        return {
            "source": "missing",
            "label": render["label"],
            "color_class": render["color_class"],
            "tooltip": _prov_tooltip(None),
        }
    # Unbekannte Quellen (Typos, neu hinzugekommene Sources) werden als
    # "Unbekannt" sichtbar gekennzeichnet — nicht mehr stumm auf Impower-Style
    # gemappt (Review-Finding P3).
    source = wrap.prov.source
    if source in _PROV_RENDER:
        render = _PROV_RENDER[source]
        label = render["label"]
        color_class = render["color_class"]
    else:
        label = f"Unbekannt ({source})"
        color_class = "bg-rose-100 text-rose-800 border border-rose-200"
    return {
        "source": source,
        "label": label,
        "color_class": color_class,
        "tooltip": _prov_tooltip(wrap),
    }


def pflegegrad_color(score: int | float | None) -> str:
    """Tailwind-Badge-Klassen fuer Pflegegrad-Score (bg + text + border-color ohne border-Keyword)."""
    if score is None:
        return "bg-slate-100 text-slate-500 border-slate-200"
    # NaN-Guard: defekter Cache-Wert oder Float-NaN soll nicht silent als grün rendern
    # (NaN-Vergleiche kollabieren in min()/max() unvorhersehbar).
    try:
        if score != score:  # NaN-Test
            return "bg-slate-100 text-slate-500 border-slate-200"
    except TypeError:
        return "bg-slate-100 text-slate-500 border-slate-200"
    score = max(0, min(100, score))
    if score >= 70:
        return "bg-green-100 text-green-800 border-green-200"
    if score >= 40:
        return "bg-yellow-100 text-yellow-800 border-yellow-200"
    return "bg-red-100 text-red-800 border-red-200"


def _get_csrf_token(request) -> str:
    """Liest den CSRF-Token aus der Session.

    Faellt auf "" zurueck, wenn (a) `request` ist `None`/Undefined (z. B.
    PDF-Render via `templates.get_template().render(...)` ohne Request),
    oder (b) SessionMiddleware nicht aktiv ist. Beides loggen wir auf
    DEBUG-Level — der Reject-Pfad in CSRFMiddleware ist unsere echte
    Defense, hier ist es ausschliesslich Beobachtbarkeit.
    """
    try:
        return request.session.get("csrf_token", "") or ""
    except Exception as exc:
        _logger.debug("csrf_token global: empty fallback (%s)", exc)
        return ""


def _csrf_input(request) -> Markup:
    """Hidden Input fuer klassische <form method="post">-Submits.

    HTMX-Submits bekommen den Token via `hx-headers` in base.html; klassische
    Browser-Forms haben keinen Header-Mechanismus. Die CSRF-Middleware
    (`app/middleware/csrf.py`) akzeptiert deshalb `_csrf` aus dem Form-Body
    als Fallback. Templates rufen einfach `{{ csrf_input(request) }}` auf.
    """
    token = _get_csrf_token(request)
    return Markup(
        f'<input type="hidden" name="_csrf" value="{escape(token)}">'
    )


templates = Jinja2Templates(directory="app/templates")
# Autoescape explizit aktiviert — versionsstabil. Liste deckt:
#  - html/htm: Standard-Templates fuer Browser
#  - xml: Strukturdaten
#  - svg: SVG kann via <foreignObject>/<script> XSS-Vektor sein
#  - jinja/j2: gaengige Jinja-Datei-Endungen (`*.html.jinja`, `*.html.j2`)
templates.env.autoescape = select_autoescape(["html", "htm", "xml", "svg", "jinja", "j2"])
templates.env.globals["has_permission"] = has_permission
templates.env.globals["csrf_token"] = _get_csrf_token
templates.env.globals["csrf_input"] = _csrf_input
templates.env.globals["field_source"] = field_source
templates.env.globals["provenance_pill"] = provenance_pill
templates.env.globals["pflegegrad_color"] = pflegegrad_color
templates.env.globals["sidebar_workflows"] = sidebar_workflows
templates.env.globals["facilioo_ticket_url"] = facilioo_ticket_url
templates.env.filters["iban_format"] = _format_iban
templates.env.filters["money_de"] = lambda v: f"{float(v):,.0f}".replace(",", ".")
templates.env.filters["field_label"] = lambda k: FIELD_LABEL_MAP.get(k, k.replace("_", " ").title())
