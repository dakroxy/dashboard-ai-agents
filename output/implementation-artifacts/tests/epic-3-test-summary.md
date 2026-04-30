---
date: 2026-04-30
scope: Epic 3 — Portfolio-UX & KI-Governance-Oberflaeche (Stories 3.1–3.6)
framework: pytest 8 + pytest-asyncio (asyncio_mode=auto), TestClient, SQLite in-memory
suite_before: 870 passed, 5 xfailed (875 collected)
suite_after: 875 passed, 5 xfailed (880 collected)
new_tests: 5
---

# Test-Audit Epic 3

## Vorgehen

QA-Audit der vorhandenen Test-Coverage gegen die in Epic-3-Retro identifizierten Faellen-Klassen:

- **Q1(f)** Substring-Asserts mit Scope-Helper (Slice-Helper als Test-Convention)
- **Q1(g)** JSONB-Shape-Defense (Service liest defekte Shape ohne 500)
- **E4** Trust-Internal-Data-Shape (interne JSONB-Daten als 2. Boundary-Klasse)

Keine Implementierungs-Aenderungen — reines Test-Schliessen vorhandener Coverage-Luecken.

## Story-Mapping (Tests vor Audit)

| Story | Test-Datei(en) | Tests | Befund |
|---|---|---|---|
| 3.1 Sortierung/Filter | `test_steckbrief_routes_smoke.py`, `test_steckbrief_service_gaps.py` | 47 | Sehr dicht: Two-Phase-Sort, NULLs-last, Tiebreaker-stable bei `desc`, casefold, mandat_status, OOB-Swap, Order-Param-Robustheit |
| 3.2 Mobile-Card-Layout | `test_steckbrief_routes_smoke.py` | 4 | `_mobile_cards_slice`-Helper als Scope-Discipline; Touch-Target 44px, Required-Fields, Reihenfolge, Desktop-Ko-Existenz |
| 3.3 Pflegegrad-Score-Service | `test_pflegegrad_unit.py` | 5 | Stale-Cache-Recompute fehlte (TTL-Boundary) |
| 3.4 Pflegegrad-Badge & Popover | `test_pflegegrad_badge_smoke.py` | 10 | Mapping-Completeness fuer `WEAKEST_FIELD_LABELS` fehlte |
| 3.5 Review-Queue Admin-UI | `test_review_queue_routes_smoke.py` | 10 | JSONB-Shape-Defense fuer `proposed_value` (non-dict) ungetestet |
| 3.6 Review-Queue Approve/Reject | `test_review_queue_approve_reject.py` | 16 | Inkl. `FOR UPDATE`-Lock-Semantik, Auto-Supersede, NFKC-Whitespace, HX-Redirect-Filter, Length-Cap, Timing-Felder |

Slice-Helper-Convention (`_tbody_slice`, `_mobile_cards_slice`) ist umgesetzt. Q1(f) ist abgehakt.

## Generierte Tests (Q1(g) + Trust-Internal-Shape)

### `tests/test_pflegegrad_unit.py`

- `test_get_or_update_cache_recomputes_when_stale` — Cache mit `now − (CACHE_TTL + 1s)` → `updated=True`, neuer TS > stale TS. Verifiziert Stale-Branch in `get_or_update_pflegegrad_cache`. Story 3.3 AC5.
- `test_weakest_field_labels_cover_all_score_emissions` — Komplett leeres Objekt liefert `score=0` und `weakest_fields` mit allen Pflichtfeld-Keys. Jeder Key MUSS in `WEAKEST_FIELD_LABELS` stehen, sonst verschluckt das Template (`{% if label_anchor %}`-Branch in `object_detail.html:56`) den Eintrag still. Schliesst Edge-Case-Hunter-Finding aus Story 3.4 als Regression.

### `tests/test_review_queue_routes_smoke.py`

JSONB-Shape-Defense fuer `proposed_value` — Konvention ist `{"value": ...}`, der Listen-Render in `app/routers/admin.py:_prepare_entries` defendiert aber gegen Abweichungen. Drei realistische Abweichungs-Shapes:

- `test_review_queue_list_renders_dict_without_value_key` — `proposed_value={"foo": "bar"}` → `.get("value", "")` liefert leer; 200 OK, Eintrag sichtbar.
- `test_review_queue_list_renders_list_proposed_value` — `proposed_value=["a", "b"]` (`isinstance(dict)`-Check faengt es); 200 OK.
- `test_review_queue_list_renders_scalar_proposed_value` — `proposed_value="bare-string"` (Skalar); 200 OK + Wert sichtbar.

Helper `_make_entry_with_value` als lokale Test-Convenience eingefuehrt — die bestehende `_make_entry` ist auf den Konventions-Shape festgelegt.

## Suite-Status

```
Before:  870 passed, 5 xfailed in 38.93s
After:   875 passed, 5 xfailed in 39.82s
Delta:   +5 Tests, +0.89s
```

Alle 880 Collections (875 passed + 5 xfailed) gruen.

## Coverage-Lage Epic 3

| Klasse | Status |
|---|---|
| Q1(f) Substring-Asserts mit Scope | OK — Slice-Helper konsequent eingesetzt |
| Q1(g) JSONB-Shape-Defense | OK — mit dieser Runde geschlossen (Listen-View) |
| E4 Trust-Internal-Data-Shape | OK — Tests fuer Stories 3.4 (weakest_fields) + 3.5 (proposed_value) ergaenzt |
| E2 Pattern + Falle | OK — Sort-Tiebreaker-reverse + Two-Phase-Sort als eigene Tests vorhanden |
| Sicherheit | OK — Permission-Matrix (302/403), IDOR (404 fuer fremde IDs), Reason-NFKC, Length-Cap |
| Date/Time-Boundaries | OK — `min_age_days=0`, NULL-Exclusion, Cache-TTL-Boundary jetzt eigener Test |

## Restliche Defers (Test-Layer, kein Block fuer Epic 3-Done)

Aus Retro uebernommen, Test-relevant:

- **Cache-Race in `pflegegrad_score`**: zwei parallele Detail-Requests, beide lesen `is_stale=True`. Heute akzeptabel (1-User-System); vor Multi-User-Rollout `with_for_update`-Test ergaenzen.
- **`approve_review_entry`-Shape-Defense**: `entry.proposed_value["value"]` (`steckbrief_write_gate.py:441,475`) wirft `KeyError`/`TypeError` bei Convention-Verletzung. Aktuell durch Convention abgesichert (write-Pfad wraps stets korrekt). Kein Test, weil das defensive Verhalten heute "raise" ist — Anpassung erst, falls Convention bewusst aufgeweicht wird.

## Naechste Schritte

1. **Vor Epic 4** Live-Verifikation Epic 2+3 auf https://dashboard.dbshome.de (C1' aus Retro).
2. **Bei Epic 4 Story 4.x mit Sort-Logik**: Memory-Notiz `feedback_sort_nullslast_two_phase.md` zitieren + Two-Phase-Stable-Sort als Default uebernehmen.
3. **Bei Story 4.4 (Tickets-am-Objekt-Detail)** ggf. `_check_fk_belongs_to_object`-Helfer einfuehren falls FK-aus-Form-Body-Pfad noetig (A2 aus Retro).
