"""Zentrale Jinja2Templates-Instanz mit projektweiten Globals und Filtern.

Alle Router importieren `templates` von hier, damit Filter (iban_format)
und Globals (has_permission) ueberall verfuegbar sind — sonst crasht
ein Template-Block, der in einem Router definiert ist und eine
Helper-Funktion eines anderen Router erwartet.
"""
from __future__ import annotations

from typing import Any

from fastapi.templating import Jinja2Templates

from app.permissions import has_permission
from app.services.mietverwaltung import field_source
from app.services.steckbrief import ProvenanceWithUser


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


templates = Jinja2Templates(directory="app/templates")
templates.env.globals["has_permission"] = has_permission
templates.env.globals["field_source"] = field_source
templates.env.globals["provenance_pill"] = provenance_pill
templates.env.filters["iban_format"] = _format_iban
