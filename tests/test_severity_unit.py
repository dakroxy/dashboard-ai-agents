"""Story 4.0 — Unit-Tests fuer app/services/_severity.py.

Verifiziert, dass die neuen StrEnums byte-identisch zu den alten Magic-Strings sind
(Backward-Compat zu Templates und bestehenden Tests).
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services._severity import DueRadarSeverity, WartungSeverity
from app.services.due_radar import _severity
from app.services.steckbrief_wartungen import get_due_severity


# ---------------------------------------------------------------------------
# DueRadarSeverity
# ---------------------------------------------------------------------------


def test_due_radar_severity_lt30_value():
    assert DueRadarSeverity.LT30 == "< 30 Tage"
    assert DueRadarSeverity.LT30.value == "< 30 Tage"


def test_due_radar_severity_lt90_value():
    assert DueRadarSeverity.LT90 == "< 90 Tage"


def test_due_radar_severity_is_str_subclass():
    """StrEnum erlaubt transparenten str-Use in Templates und f-Strings."""
    assert isinstance(DueRadarSeverity.LT30, str)
    assert f"{DueRadarSeverity.LT30}" == "< 30 Tage"


def test_severity_returns_str_compatible_value():
    """Backward-Compat: _severity(20) muss weiter '< 30 Tage' liefern."""
    result = _severity(20)
    assert result == "< 30 Tage"
    assert result == DueRadarSeverity.LT30


def test_severity_boundary_at_30_returns_lt90():
    """days_remaining=30 ist die Grenze: NICHT < 30 → LT90."""
    assert _severity(30) == DueRadarSeverity.LT90


def test_severity_negative_days_returns_lt30():
    """Ueberfaellige Eintraege (days_remaining < 0) bleiben LT30."""
    assert _severity(-5) == DueRadarSeverity.LT30


# ---------------------------------------------------------------------------
# WartungSeverity
# ---------------------------------------------------------------------------


def test_wartung_severity_critical_value():
    assert WartungSeverity.CRITICAL == "critical"


def test_wartung_severity_warning_value():
    assert WartungSeverity.WARNING == "warning"


def test_wartung_severity_normal_value():
    assert WartungSeverity.NORMAL == "normal"


def test_wartung_severity_none_value():
    assert WartungSeverity.NONE == "none"


def test_wartung_severity_empty_value():
    assert WartungSeverity.EMPTY == "empty"


def test_wartung_severity_is_str_subclass():
    assert isinstance(WartungSeverity.CRITICAL, str)
    assert f"{WartungSeverity.NORMAL}" == "normal"


def test_get_due_severity_critical_compat():
    result = get_due_severity(date.today() + timedelta(days=15))
    assert result == "critical"
    assert result == WartungSeverity.CRITICAL


def test_get_due_severity_warning_compat():
    result = get_due_severity(date.today() + timedelta(days=60))
    assert result == "warning"
    assert result == WartungSeverity.WARNING


def test_get_due_severity_none_for_distant_date():
    assert get_due_severity(date.today() + timedelta(days=180)) is None


def test_get_due_severity_none_for_none_input():
    assert get_due_severity(None) is None
