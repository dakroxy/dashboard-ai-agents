"""Story 4.0 — Unit-Tests fuer app/services/_time.py:today_local().

Verifiziert:
- AC1: today_local() liefert ein date-Objekt
- AC1: Range-Assertion gegen UTC (max +/-1 Tag Drift)
- AC8: Mit TZ=Europe/Berlin (gesetzt in conftest.py) liefert date.today()
       dasselbe Datum wie today_local() — Tagesrand-Flake ausgeschlossen.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.services._time import today_local


def test_today_local_returns_date_type():
    assert isinstance(today_local(), date)


def test_today_local_within_one_day_of_utc():
    """Range-Assertion ohne Mock: today_local() weicht maximal +/-1 Tag von UTC ab.

    Robust gegen DST-Wechsel und Test-Ausfuehrungs-Zeitpunkt.
    """
    result = today_local()
    utc_today = datetime.now(timezone.utc).date()
    assert result in {
        utc_today - timedelta(days=1),
        utc_today,
        utc_today + timedelta(days=1),
    }


def test_today_local_matches_date_today_when_tz_synchronized():
    """Mit TZ=Europe/Berlin (gesetzt in conftest.py) liefern beide
    dasselbe Datum. Verhindert Tagesrand-Flake in Tests, die date.today()
    gegen Service-Werte (today_local()) vergleichen."""
    assert today_local() == date.today()
