"""Story 1.6 — Unit-Tests fuer parse_technik_value (ohne TestClient).

Testet die reine Validator-Logik: Leerstring-Semantik (AC6), Jahr-Range,
Text-Laengen-Limit, Whitespace-Trim, Unbekannte-Felder-Guard.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.steckbrief import parse_technik_value


def test_parse_empty_returns_none_no_error():
    """AC6: leerer Input ist bewusste Loeschung → (None, None)."""
    assert parse_technik_value("year_roof", "") == (None, None)


def test_parse_empty_text_field_returns_none():
    """Gleiche Semantik fuer Text-Felder."""
    assert parse_technik_value("heating_type", "") == (None, None)


def test_parse_year_valid():
    assert parse_technik_value("year_roof", "2021") == (2021, None)


def test_parse_year_too_low():
    parsed, err = parse_technik_value("year_built", "1700")
    assert parsed is None
    assert err is not None
    assert "Jahr muss zwischen 1800 und" in err


def test_parse_year_too_high():
    parsed, err = parse_technik_value("year_heating", "3000")
    assert parsed is None
    assert err is not None
    assert "Jahr muss zwischen 1800 und" in err


def test_parse_year_upper_bound_is_current_year_plus_one():
    """Die Obergrenze ist dynamisch: current_year + 1 ist erlaubt,
    current_year + 2 nicht."""
    current_year = datetime.now().year
    ok_val, ok_err = parse_technik_value("year_heating", str(current_year + 1))
    assert ok_val == current_year + 1 and ok_err is None

    bad_val, bad_err = parse_technik_value("year_heating", str(current_year + 2))
    assert bad_val is None and bad_err is not None


def test_parse_year_non_numeric():
    parsed, err = parse_technik_value("year_built", "abc")
    assert parsed is None
    assert err == "Bitte eine ganze Zahl (Jahr) eingeben."


def test_parse_year_whitespace_trimmed():
    assert parse_technik_value("year_built", "  2020  ") == (2020, None)


def test_parse_text_valid():
    assert parse_technik_value("heating_type", "Viessmann") == ("Viessmann", None)


def test_parse_text_too_long():
    parsed, err = parse_technik_value("shutoff_water_location", "x" * 501)
    assert parsed is None
    assert err == "Maximal 500 Zeichen erlaubt."


def test_parse_text_whitespace_trimmed():
    assert parse_technik_value("shutoff_water_location", "  Keller  ") == ("Keller", None)


def test_parse_unknown_field_raises():
    """entry_code_* ist bewusst nicht in TECHNIK_FIELD_KEYS — der Parser
    verweigert jeden Versuch, darueber einen Zugangscode zu schreiben.
    Encrypted-Scope bleibt Story 1.7."""
    with pytest.raises(ValueError):
        parse_technik_value("entry_code_main_door", "1234")
