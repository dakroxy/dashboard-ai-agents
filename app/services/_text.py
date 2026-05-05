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

# Zero-Width-Chars: werden ENTFERNT (ohne Substitut), damit "Wart​ung"
# zu "Wartung" wird, nicht zu "Wart ung". Deckt Zero-Width-Space, ZW-Non-Joiner,
# ZW-Joiner, Word-Joiner, BOM, LRM, RLM, Mongolian Vowel Separator.
_ZERO_WIDTH_CHARS = "​‌‍⁠﻿‎‏᠎"

# Whitespace-aequivalente Chars, die str.strip() nicht erfasst: NBSP, Narrow-NBSP,
# Figure-Space, Ideographic-Space. Werden zu " " ersetzt + dann gestripped.
_NBSP_CLASS_CHARS = "   　"


def _normalize_text(s: str | None) -> str:
    """NFKC-Normalize, unsichtbare Whitespace-Zeichen ersetzen, strip.

    Schuetzt gegen Zero-Width-Spaces, NBSPs und BOMs, die LLM-Ausgaben
    (und Copy-Paste aus PDFs) einschmuggeln koennen.

    Zero-Width-Chars werden komplett entfernt (kein Wort-Bruch via Substitut-Space);
    NBSP-Klassen-Chars werden zu Space ersetzt und mitgestripped.
    """
    if not isinstance(s, str) or not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    for ch in _ZERO_WIDTH_CHARS:
        s = s.replace(ch, "")
    for ch in _NBSP_CLASS_CHARS:
        s = s.replace(ch, " ")
    return s.strip()
