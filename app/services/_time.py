"""Zentraler Date-Helper. Liefert das aktuelle Datum in Europe/Berlin,
unabhaengig von der Container-Timezone (Prod-Container laeuft in UTC).

Story 4.0 / Epic-2-Retro Action H1 / Epic-3-Retro Action H1'.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo("Europe/Berlin")


def today_local() -> date:
    """Aktuelles Datum in Europe/Berlin.

    Hintergrund: Prod-Container laeuft in UTC. ``date.today()`` liefert dort
    zwischen 00:00 und 02:00 Berlin-Zeit (im Sommer) das *vorige* Datum, was
    Severity-Schwellen (30 / 90 Tage) am Tagesrand verschoben triggern kann.
    Dieser Helper ist die konsistente Kapsel.
    """
    return datetime.now(_BERLIN).date()
