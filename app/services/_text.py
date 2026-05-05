"""Text-Normalisierungs-Hilfsfunktionen fuer freie Eingabefelder.

Default-Pattern fuer alle freien Text-Inputs (Bezeichnungen, Notizen, etc.):
Ruf `_normalize_text(s)` auf, bevor du einen Leer-Check machst oder den Wert
in der DB speicherst.

Aufrufpunkte (Stand Story 5-3):
  - `app/routers/objects.py:wartungspflicht_create` (bezeichnung)

Weitere Stellen (Notes, Descriptions, Names usw.) werden in Story 5-6 systematisch
auf diesen Helper migriert.
"""
from __future__ import annotations

import unicodedata

# Zero-Width-Spaces + BOM + Non-Breaking Space, die str.strip() nicht entfernt.
_INVISIBLE_CHARS = "​‌‍﻿ "


def _normalize_text(s: str | None) -> str:
    """NFKC-Normalize, unsichtbare Whitespace-Zeichen ersetzen, strip.

    Schuetzt gegen Zero-Width-Spaces, NBSPs und BOMs, die LLM-Ausgaben
    (und Copy-Paste aus PDFs) einschmuggeln koennen.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    for ch in _INVISIBLE_CHARS:
        s = s.replace(ch, " ")
    return s.strip()
