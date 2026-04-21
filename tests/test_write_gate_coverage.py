"""Coverage-Test: kein direkter Feld-Write auf CD1-Haupt-Entitaeten ausserhalb
des Write-Gates (Story 1.2 AC9, architecture.md §CD2).

Stufe 1 (MVP, Textscan). Stufe 2 (AST-basiert) ist auf `deferred-work.md`
verschoben, falls die Heuristik zu viele False-Positives erzeugt.

Heuristik:
  1. Fuer jede `.py`-Datei unter `app/routers/` + `app/services/` ausser
     `app/services/steckbrief_write_gate.py`:
  2. Scanne Zeilen, die wie `<var>.<attr> = <value>` aussehen (keine String-
     Literale, keine Kommentare, keine `==`-Vergleiche, keine Keyword-Args).
  3. Ist `<var>` ueber eine lokale Konstruktion (`<var> = Object(...)` oder
     `<var> = db.query(Object)...` / `db.get(Object, ...)`) erkennbar als
     CD1-Instanz? Dann war das ein Direct-Write — assert fail, wenn nicht
     in der Allow-List.

False-Positive-Escape-Hatches:
  * Inline-Kommentar `# writegate: allow` am Ende der Zeile.
  * Allow-Liste `_ALLOWED_DIRECT_ASSIGNMENTS` (Cache-Felder usw.).
"""
from __future__ import annotations

import re
from pathlib import Path


_CD1_CLASSES: frozenset[str] = frozenset(
    {
        "Object",
        "Unit",
        "InsurancePolicy",
        "Wartungspflicht",
        "Schadensfall",
        "Versicherer",
        "Dienstleister",
        "Bank",
        "Ablesefirma",
        "Eigentuemer",
        "Mieter",
        "Mietvertrag",
        "Zaehler",
        "FaciliooTicket",
    }
)

# (variable_name, field) — direkte Writes, die explizit erlaubt sind.
_ALLOWED_DIRECT_ASSIGNMENTS: frozenset[tuple[str, str]] = frozenset(
    {
        # Pflegegrad-Cache: vom Gate selbst geschrieben, Caller duerfen das
        # theoretisch auch (invalidation-Shortcut) — siehe Gate-Docstring.
        ("obj", "pflegegrad_score_cached"),
        ("obj", "pflegegrad_score_updated_at"),
        ("entity", "pflegegrad_score_cached"),
        ("entity", "pflegegrad_score_updated_at"),
    }
)

_ALLOW_COMMENT = "# writegate: allow"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [
    _PROJECT_ROOT / "app" / "routers",
    _PROJECT_ROOT / "app" / "services",
]
_EXCLUDE_FILES = {
    _PROJECT_ROOT / "app" / "services" / "steckbrief_write_gate.py",
}


# Assignment-Zeilen: `<ident>.<ident> = <irgendwas>` (ohne ==).
_ASSIGN_RE = re.compile(r"^\s*(\w+)\.(\w+)\s*=(?!=)")

# Lokale Konstruktion einer CD1-Klasse:
#   <var> = Object(...)
#   <var> = db.query(Object)...
#   <var> = db.get(Object, ...)
_CONSTRUCT_RE = re.compile(
    r"^\s*(\w+)\s*=\s*(?:.*\b(?:query|get)\s*\()?\s*(\w+)\s*\("
)


def _strip_strings_and_comments(src: str) -> list[tuple[int, str]]:
    """Liefert (lineno, code)-Paare ohne Triple-Quote-Bloecke, mit Kommentar-Rest."""
    out: list[tuple[int, str]] = []
    in_block = False
    block_quote = ""
    for lineno, raw in enumerate(src.splitlines(), start=1):
        line = raw
        if in_block:
            idx = line.find(block_quote)
            if idx >= 0:
                in_block = False
                line = line[idx + len(block_quote):]
            else:
                continue
        for q in ('"""', "'''"):
            if q in line:
                start = line.find(q)
                rest = line[start + len(q):]
                if q in rest:
                    end = rest.find(q)
                    line = line[:start] + line[start + len(q) + end + len(q):]
                else:
                    line = line[:start]
                    in_block = True
                    block_quote = q
                    break
        out.append((lineno, line))
    return out


def _collect_cd1_vars(lines: list[tuple[int, str]]) -> dict[str, str]:
    """Mappt Variable → CD1-Klassenname, wenn die Zuweisung nach CD1 aussieht."""
    local_vars: dict[str, str] = {}
    for _, line in lines:
        m = _CONSTRUCT_RE.match(line)
        if not m:
            continue
        var_name = m.group(1)
        # Finde das ERSTE CD1-Class-Referenz-Wort in der Zeile.
        for cls in _CD1_CLASSES:
            if re.search(rf"\b{re.escape(cls)}\b", line):
                local_vars[var_name] = cls
                break
    return local_vars


def _iter_scan_files():
    for base in _SCAN_DIRS:
        if not base.exists():
            continue
        for py in sorted(base.rglob("*.py")):
            if py in _EXCLUDE_FILES:
                continue
            yield py


def test_no_direct_writes_to_cd1_entities_textscan():
    offenders: list[str] = []

    for path in _iter_scan_files():
        src = path.read_text(encoding="utf-8")
        lines = _strip_strings_and_comments(src)

        cd1_vars = _collect_cd1_vars(lines)
        if not cd1_vars:
            continue

        for lineno, line in lines:
            m = _ASSIGN_RE.match(line)
            if not m:
                continue
            var, field = m.group(1), m.group(2)
            if var not in cd1_vars:
                continue
            if (var, field) in _ALLOWED_DIRECT_ASSIGNMENTS:
                continue
            if _ALLOW_COMMENT in line:
                continue
            try:
                disp = path.relative_to(_PROJECT_ROOT)
            except ValueError:
                disp = path
            offenders.append(
                f"{disp}:{lineno} "
                f"(var={var} cls={cd1_vars[var]} field={field}): {line.strip()}"
            )

    assert not offenders, (
        "Direkte Feld-Writes auf CD1-Entitaeten gefunden — alle Writes muessen "
        "ueber app/services/steckbrief_write_gate.py laufen (Story 1.2 AC9).\n"
        + "\n".join(offenders)
    )


def test_coverage_scan_finds_seeded_violation(tmp_path, monkeypatch):
    """Self-Check: kurzer Probe-File mit direktem Write wird als Verstoss erkannt."""
    import tests.test_write_gate_coverage as mod

    fake = tmp_path / "fake_service.py"
    fake.write_text(
        "from app.models import Object\n"
        "def f(db):\n"
        "    obj = Object(short_code='X', name='x')\n"
        "    obj.year_roof = 2021\n"
    )

    orig_dirs = mod._SCAN_DIRS
    orig_excl = mod._EXCLUDE_FILES
    monkeypatch.setattr(mod, "_SCAN_DIRS", [tmp_path])
    monkeypatch.setattr(mod, "_EXCLUDE_FILES", set())
    try:
        import pytest
        with pytest.raises(AssertionError):
            mod.test_no_direct_writes_to_cd1_entities_textscan()
    finally:
        monkeypatch.setattr(mod, "_SCAN_DIRS", orig_dirs)
        monkeypatch.setattr(mod, "_EXCLUDE_FILES", orig_excl)
