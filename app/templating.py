"""Zentrale Jinja2Templates-Instanz mit projektweiten Globals und Filtern.

Alle Router importieren `templates` von hier, damit Filter (iban_format)
und Globals (has_permission) ueberall verfuegbar sind — sonst crasht
ein Template-Block, der in einem Router definiert ist und eine
Helper-Funktion eines anderen Router erwartet.
"""
from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.permissions import has_permission
from app.services.mietverwaltung import field_source


def _format_iban(value: str | None) -> str:
    """Gruppiert eine IBAN in 4er-Blocks (reine Anzeige, Speicherung bleibt kompakt)."""
    if not value:
        return ""
    clean = str(value).replace(" ", "").upper()
    return " ".join(clean[i : i + 4] for i in range(0, len(clean), 4))


templates = Jinja2Templates(directory="app/templates")
templates.env.globals["has_permission"] = has_permission
templates.env.globals["field_source"] = field_source
templates.env.filters["iban_format"] = _format_iban
