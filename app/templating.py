"""Zentrale Jinja2Templates-Instanz mit projektweiten Globals und Filtern.

Alle Router importieren `templates` von hier, damit Filter (iban_format)
und Globals (has_permission) ueberall verfuegbar sind — sonst crasht
ein Template-Block, der in einem Router definiert ist und eine
Helper-Funktion eines anderen Router erwartet.
"""
from __future__ import annotations

from typing import Any

from fastapi.templating import Jinja2Templates

from app.db import SessionLocal
from app.models import User, Workflow
from app.permissions import accessible_workflow_ids, has_permission
from app.services.mietverwaltung import field_source
from app.services.steckbrief import ProvenanceWithUser


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

    Eigene DB-Session, damit der Helper aus jedem Template heraus aufrufbar ist
    ohne dass die Route die Liste manuell durchreichen muss.
    """
    if user is None:
        return []
    db = SessionLocal()
    try:
        ids = accessible_workflow_ids(db, user)
        if not ids:
            return []
        workflows = (
            db.query(Workflow)
            .filter(Workflow.active.is_(True), Workflow.id.in_(ids))
            .order_by(Workflow.name.asc())
            .all()
        )
    finally:
        db.close()
    items: list[dict[str, Any]] = []
    for wf in workflows:
        meta = _WORKFLOW_SIDEBAR_META.get(wf.key, {"url": f"/workflows/{wf.key}", "icon": ""})
        items.append({"key": wf.key, "name": wf.name, "url": meta["url"], "icon": meta["icon"]})
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
    ts = prov.created_at.strftime("%Y-%m-%d %H:%M") if prov.created_at else ""
    if prov.source == "user_edit":
        if wrap.user_email:
            return f"Manuell gepflegt am {ts} von {wrap.user_email}"
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


def pflegegrad_color(score: int | None) -> str:
    """Tailwind-Badge-Klassen fuer Pflegegrad-Score (bg + text + border-color ohne border-Keyword)."""
    if score is None:
        return "bg-slate-100 text-slate-500 border-slate-200"
    if score >= 70:
        return "bg-green-100 text-green-800 border-green-200"
    if score >= 40:
        return "bg-yellow-100 text-yellow-800 border-yellow-200"
    return "bg-red-100 text-red-800 border-red-200"


templates = Jinja2Templates(directory="app/templates")
templates.env.globals["has_permission"] = has_permission
templates.env.globals["field_source"] = field_source
templates.env.globals["provenance_pill"] = provenance_pill
templates.env.globals["pflegegrad_color"] = pflegegrad_color
templates.env.globals["sidebar_workflows"] = sidebar_workflows
templates.env.filters["iban_format"] = _format_iban
