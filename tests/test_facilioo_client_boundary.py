"""Boundary-Test: kein Facilioo-Call ausserhalb von app/services/facilioo.py.

Story 4.2 AC4 — Pattern analog tests/test_write_gate_coverage.py.

Heuristik (Textscan, kein AST):
  1. Walk app/**/*.py.
  2. Skip Allow-List: app/config.py, app/services/facilioo.py,
     app/services/facilioo_mirror.py (entsteht in Story 4.3).
  3. Suche literal 'facilioo_bearer_token' oder 'facilioo_base_url'.
  4. Hits = Verstoss (nur das Gate-Modul + Settings duerfen den Token referenzieren).

Tests in tests/ sind NICHT im Scan (Tests duerfen patchen).
"""
from __future__ import annotations

from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SCAN_DIRS = [
    _PROJECT_ROOT / "app",
]

_ALLOW_LIST: frozenset[Path] = frozenset({
    _PROJECT_ROOT / "app" / "config.py",
    _PROJECT_ROOT / "app" / "services" / "facilioo.py",
    _PROJECT_ROOT / "app" / "services" / "facilioo_mirror.py",
})

_BOUNDARY_TOKENS: tuple[str, ...] = ("facilioo_bearer_token", "facilioo_base_url")


def _iter_scan_files():
    for base in _SCAN_DIRS:
        if not base.exists():
            continue
        for py in sorted(base.rglob("*.py")):
            if py in _ALLOW_LIST:
                continue
            yield py


def test_no_facilioo_calls_outside_gate():
    offenders: list[str] = []

    for path in _iter_scan_files():
        src = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(src.splitlines(), start=1):
            for token in _BOUNDARY_TOKENS:
                if token in line:
                    try:
                        disp = path.relative_to(_PROJECT_ROOT)
                    except ValueError:
                        disp = path
                    offenders.append(f"{disp}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Facilioo-Boundary verletzt — facilioo_bearer_token oder facilioo_base_url "
        "ausserhalb der Allow-List gefunden. Alle Facilioo-Calls muessen ueber "
        "app/services/facilioo.py laufen (Story 4.2 AC4).\n"
        + "\n".join(offenders)
    )


def test_boundary_scan_finds_seeded_violation(tmp_path, monkeypatch):
    """Self-Check: synthetisches File mit Boundary-Token wird als Verstoss erkannt."""
    import pytest

    import tests.test_facilioo_client_boundary as mod

    fake = tmp_path / "fake_service.py"
    fake.write_text(
        "import httpx\n"
        "from app.config import settings\n"
        "async def bad_call():\n"
        "    client = httpx.AsyncClient(\n"
        "        headers={'Authorization': f'Bearer {settings.facilioo_bearer_token}'}\n"
        "    )\n"
    )

    monkeypatch.setattr(mod, "_SCAN_DIRS", [tmp_path])
    monkeypatch.setattr(mod, "_ALLOW_LIST", frozenset())
    with pytest.raises(AssertionError):
        mod.test_no_facilioo_calls_outside_gate()
