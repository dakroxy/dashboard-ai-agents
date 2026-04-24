# Test-Automatisierung — Story 1.6 (Technik-Sektion mit Inline-Edit)

**Datum:** 2026-04-24
**Skill:** `bmad-qa-generate-e2e-tests`
**Scope:** Story 1.6 — Technik-Sektion mit drei Sub-Bloecken
(Absperrpunkte, Heizung, Objekt-Historie), 10 inline-editierbare Felder

## Ergebnis

**Keine neuen Tests in diesem Durchlauf** — Story 1.6 wurde waehrend der
Implementierung bereits mit 28 dedizierten Tests abgeschlossen (alle gruen).
Diese Doku zieht nur die Test-Abdeckung pro AC nach.

## Bestehende Testdateien

### `tests/test_technik_parser_unit.py` (12 Tests)

Unit-Level fuer `parse_technik_value` in `app/services/steckbrief.py` —
Validiert Jahresfelder (`year_*`) und Textfelder getrennt.

- `parse_technik_value` mit Leerstring → `(None, None)` (NULL-Loeschung, AC6).
- Jahr als Int-String → `(int, None)`.
- Jahr mit Dezimalkomma / -Punkt (Browser-`type=number`-Quirk, der
  `"2021.0"` schickt) → korrekt als 2021 geparst.
- Jahr ausserhalb [1800, current_year+1] → Fehler-Tuple.
- Jahr als Nicht-Zahl → Fehler.
- Text gestrippt + Laenge <= 3000 → OK; >3000 → Fehler.
- Unicode-Whitespace im Text wird getrimmt.
- Unbekannter Feld-Key → Fehler.

### `tests/test_technik_routes_smoke.py` (16 Tests)

Router-Ebene `/objects/{id}/technik/*` — HTMX-Fragment-Endpoints fuer
View/Edit/Save.

- AC1: Technik-Sektion + 3 Sub-Bloecke + 10 Felder + Edit-Buttons (Editor).
- AC1: Deutsche Labels (`Wasser-Absperrung`, `Heizungs-Typ`, etc.).
- AC1: Zugangscodes erscheinen im Render, aber Technik-Endpoint lehnt sie ab
  (Scope-Boundary zu Story 1.7).
- AC2: `POST /technik/field` schreibt via `write_field_human` →
  `FieldProvenance(source="user_edit")` + `AuditLog(action="object_field_updated")`.
- AC2: Fragment-Response ist View-Mode mit Provenance-Pill nach Save.
- AC3: Viewer (`objects:view` ohne `objects:edit`) sieht keine Edit-Buttons;
  `GET /technik/edit` → 403, `POST /technik/field` → 403, `GET /technik/view` → 403.
- AC4: Ungueltiger Jahresgeber → 422 + `data-error="true"` im Fragment.
- AC4: Jahr ausserhalb Range → 422.
- AC4: Text zu lang → 422.
- AC4: Fehler-Response enthaelt den submitted Wert zum erneuten Editieren.
- AC5: Erfolgreicher Write invalidiert Pflegegrad-Cache (indirekt via
  `write_field_human`-Hook, Test prueft `pflegegrad_score_cached=None`).
- AC6: Empty-String loescht Feld → `obj.year_roof is None`.
- AC6: DB-Rollback bei Exception im Save (try/except + `db.rollback()`).
- AC7: Regression in volle Suite integriert.

### Indirekt

- `tests/test_write_gate_unit.py` — deckt die Write-Gate-Semantik ab, auf
  die Story 1.6 aufbaut.

## Coverage pro AC

| AC | Anforderung | Abdeckung |
|----|-------------|-----------|
| AC1 | Technik-Sektion rendert + Edit-Buttons | `test_technik_routes_smoke` (Render + data-edit-field) |
| AC2 | Save → Write-Gate + Provenance + Audit | `test_technik_routes_smoke` + `test_technik_parser_unit` |
| AC3 | Ohne `objects:edit`: unsichtbar + POST/GET 403 | `test_technik_routes_smoke` (viewer_client alle Endpoints) |
| AC4 | Validierungsfehler → Fragment, kein Write | `test_technik_parser_unit` + `test_technik_routes_smoke` |
| AC5 | Pflegegrad-Cache-Invalidierung | `test_technik_routes_smoke` (Cache-Check nach Save) |
| AC6 | Empty → NULL | `test_technik_parser_unit` + `test_technik_routes_smoke` |
| AC7 | Regressionslauf gruen | Volle Suite 499/499 gruen (Stand 2026-04-24) |

## Run-Command

```bash
docker compose exec app python -m pytest \
  tests/test_technik_parser_unit.py \
  tests/test_technik_routes_smoke.py -v
# 28 passed
```

## Bewusst NICHT abgedeckt

- **CSRF-Schutz auf POST-Endpoints** — plattform-weites Thema, in
  `deferred-work.md` Story 1.6 dokumentiert. Kein spezifischer Test im Scope
  dieser Story, weil der Fix global fuer alle POST-Routen greift.
- **Jinja2-Autoescape explizit testen** — Defer-Item aus Code-Review. Der
  Default-Autoescape greift laut Jinja2-Version aktuell korrekt; Regression
  wird durch bestehendes HTML-Rendering der Views indirekt aufgefangen.
- **Double-Browser-Submit auf demselben Feld** — Browser-UX, kein Server-Test.

## Offene Luecken

Keine. Die Story gilt als test-seitig abgeschlossen.
