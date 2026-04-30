"""Zentrale Severity-StrEnums. Konsolidiert die in Epic 1+2 organisch
entstandenen Magic-Strings.

Story 4.0 / Epic-2-Retro Action H2 / Epic-3-Retro Action H2'.

Zwei getrennte Enums weil zwei Domains:

- ``DueRadarSeverity`` — deutsche UI-Labels fuer den Due-Radar-Service
  (List-View, Filter-Query-Param). Werte werden direkt als Text gerendert.
- ``WartungSeverity`` — englische Status-Codes fuer Police/Wartung-Color-
  Coding. Genutzt von Steckbrief-Wartungen, Versicherer-Detail-Heatmap,
  Versicherer-Detail-Police-Tabelle. Werte sind CSS-relevante Status-Codes
  (red/orange/green/grau), kein User-Text.

``StrEnum`` (Python 3.11+) verhaelt sich transparent als ``str``: f-Strings,
Vergleich mit ``"..."``-Literalen und Jinja2-``==`` funktionieren ohne
Anpassung. Tests, die ``assert sev == "critical"`` schreiben, bleiben gruen.
"""
from __future__ import annotations

from enum import StrEnum


class DueRadarSeverity(StrEnum):
    """Severity-Buckets fuer Due-Radar-Aggregation (Police/Wartung-Faelligkeit).

    Werte werden direkt als UI-Labels angezeigt und als Filter-Query-Param
    uebergeben — daher deutsche Texte.
    """

    LT30 = "< 30 Tage"
    LT90 = "< 90 Tage"


class WartungSeverity(StrEnum):
    """Severity-Status-Codes fuer Police/Wartung-Faelligkeit-Color-Coding.

    Genutzt von:

    - ``app.services.steckbrief_wartungen.get_due_severity`` (Wartung am Steckbrief)
    - ``app.services.registries._build_heatmap`` (Versicherer-Detail-Heatmap)
    - ``app.services.registries.get_versicherer_detail`` (Versicherer-Detail-Police-Tabelle)

    Werte sind CSS-relevante Status-Codes (red/orange/green/grau), kein User-Text.
    """

    CRITICAL = "critical"  # < 30 Tage
    WARNING = "warning"    # < 90 Tage
    NORMAL = "normal"      # > 90 Tage / Faellig in ferner Zukunft
    NONE = "none"          # Kein Faelligkeitsdatum bekannt
    EMPTY = "empty"        # Heatmap-Bucket ohne Inhalt (keine Police im Monat)
