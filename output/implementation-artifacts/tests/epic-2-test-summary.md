---
epic: 2
date: 2026-04-29
scope: "Nachgelagerte QA-Test-Generierung fuer Epic 2 (alle 9 Stories done) + 2 Quick-Win-Fixes"
strategy: "3 parallele Tranchen, fokussiert auf bekannte Coverage-Klassen aus Epic-2-Retro E2"
result: "709 passed, 5 xfailed (vorher 692, +22 Tests, 1 Truthiness-Bug gefixt)"
---

# Epic 2 — Test-Summary (nachtraegliche QA-Coverage)

## Hintergrund

Epic 2 Retro (2026-04-28) hat dokumentiert, dass ~50 % aller Code-Review-Patches Test-Coverage-Luecken waren — die Tests sind reaktiv im Adversarial-Review entstanden, nicht systematisch vorab. Bestehende Coverage war stark **negativ-lastig** (403/404-Gates), Positiv-Paths fuer Admin-User und mehrere bekannte Edge-Cases waren nicht regression-getestet.

Diese Pass schliesst die identifizierten Klassen via 3 parallele Tranchen.

## Vorgehen

3 QA-Agents parallel, jede mit klar umrissenem Liefer-Auftrag. Vorgabe:
- Tests in existierende Files erweitern, kein App-Code-Touch.
- Bei echten Bugs: `@pytest.mark.xfail(reason=...)` mit Verweis auf Story-/Retro-Defer.
- Bestehende Tests nicht duplizieren — wenn Soll-Test bereits unter anderem Namen abgedeckt ist, dokumentieren statt schreiben.

## Tranche A — Permission-Gate Positiv-Path (8 Tests, alle gruen)

| Test | File |
|---|---|
| `test_zugangscode_view_returns_200_for_admin_with_view_confidential` | `tests/test_zugangscodes_routes_smoke.py` |
| `test_zugangscode_edit_returns_200_for_admin_with_view_confidential` | `tests/test_zugangscodes_routes_smoke.py` |
| `test_zugangscode_save_returns_200_for_admin_with_view_confidential` | `tests/test_zugangscodes_routes_smoke.py` |
| `test_create_police_returns_200_for_admin_with_objects_edit` | `tests/test_policen_routes_smoke.py` |
| `test_update_police_returns_200_for_admin` | `tests/test_policen_routes_smoke.py` |
| `test_delete_police_returns_200_for_admin` | `tests/test_policen_routes_smoke.py` |
| `test_menschen_notes_view_returns_200_for_admin_with_view_confidential` | `tests/test_menschen_notizen_unit.py` |
| `test_menschen_notes_save_persists_for_admin` | `tests/test_menschen_notizen_unit.py` |

**Stories:** 2.0, 2.1, 2.4
**Befund:** Mehrere Soll-Tests waren bereits unter anderen Namen abgedeckt (z. B. `test_post_policen_creates_policy_with_all_fields`); Tranche-A-Tests stehen explizit zusaetzlich mit den geforderten Namen + thematisch fokussierten Asserts (Audit-User-ID, Cipher-Persistenz, Decimal-Wert-Roundtrip).

## Tranche B — Numerische Boundaries & Form-Error-UX (10 Tests: 4 gruen, 6 xfail)

### Hinzugefuegt (gruen)

| Test | File |
|---|---|
| `test_amount_validation_e_notation_overflow` | `tests/test_schadensfaelle_unit.py` |
| `test_create_schadensfall_rejects_pre_1900_date` | `tests/test_schadensfaelle_routes_smoke.py` |
| `test_create_schadensfall_rolls_back_on_integrity_error` | `tests/test_schadensfaelle_routes_smoke.py` |
| `test_rows_returns_outerhtml_with_tbody_id` | `tests/test_due_radar_routes_smoke.py` |

### Hinzugefuegt (xfail — dokumentierte Defer-Bugs)

| Test | Bug-Quelle | Stelle |
|---|---|---|
| `test_create_police_rejects_praemie_negative` | Story 2.1 Defer-D | `_parse_decimal` ohne Range-Check |
| `test_create_police_rejects_praemie_overflow` | Story 2.1 Defer-D | `> Numeric(12,2)` crasht am DB-Commit als 500 |
| `test_create_police_rejects_notice_period_negative` | Story 2.1 Defer-D | client-side `min="0"` only, Server prueft nicht |
| `test_create_police_form_error_renders_sticky_form_visible` | Story 2.1 Defer-D2 | Bei 422 bleibt `#neue-police-form class="hidden"` |
| `test_create_wartungspflicht_form_error_renders_with_dienstleister_list_context` | Bewusster Minimal-Fragment-Render | Section-Re-Render-Pattern offen |
| ~~`test_versicherer_detail_renders_zero_praemie_as_value_not_dash`~~ | Story 2.8 Decimal-Truthiness | **GEFIXT** — Template auf `{% if p.praemie is not none %}` umgestellt |

### Bereits abgedeckt (12 Tests, nicht dupliziert)

- `test_post_policen_with_invalid_dates_returns_422` (next_main_due < start_date)
- `test_severity_badge_warning_for_due_within_90_days` (60d → bg-orange-100)
- `test_post_wartungspflicht_with_zero_intervall_returns_422`, `test_post_wartungspflicht_with_negative_intervall_returns_422`
- `test_post_wartungspflicht_with_nonexistent_dienstleister_returns_422`
- `test_amount_validation_inf_nan_overflow` (Inf, NaN, 10000000000.00)
- `test_amount_validation_comma_decimal` (3 Faelle)
- `test_unit_id_from_other_object_returns_404`
- `test_occurred_at_future_returns_422`
- `test_rows_fragment_redirects_without_hx_request`, `test_rows_invalid_type_returns_422`, `test_rows_invalid_severity_returns_422`

## Tranche C — Render-Gaps (4 Tests, alle gruen)

| Test | File |
|---|---|
| `test_menschen_notizen_view_renders_owner_list_with_existing_note` | `tests/test_menschen_notizen_unit.py` |
| `test_menschen_notizen_view_renders_edit_button_for_admin_with_view_confidential` | `tests/test_menschen_notizen_unit.py` |
| `test_menschen_notizen_view_hides_section_for_user_without_view_confidential` | `tests/test_menschen_notizen_unit.py` |
| `test_object_detail_renders_versicherungen_anchor` | `tests/test_due_radar_routes_smoke.py` |

**Befund:** Severity-Badge-Render-Tests (Orange + Rot) waren bereits abgedeckt unter `test_severity_badge_warning_for_due_within_90_days` und `test_severity_badge_critical_for_due_within_30_days`. Anchor `id="versicherungen"` (Story 2.5 Retro-Patch P1) ist live in `app/templates/_obj_versicherungen.html:6` und jetzt regression-festgenagelt.

## Gesamt-Test-Lauf

```
709 passed, 5 xfailed, 38 warnings in 16.23s
```

Vorher (laut Epic-2-Retro): 692 Tests. Jetzt: **+22 Tests** (17 neue passing, 5 xfail).

## Quick-Win-Fixes (im selben Pass)

1. **Template-Fix `app/templates/registries_versicherer_detail.html:104`** — `{% if p.praemie %}` → `{% if p.praemie is not none %}`. Loest den Decimal('0')-Truthiness-Bug aus Story 2.8 Review. Test `test_versicherer_detail_renders_zero_praemie_as_value_not_dash` ist jetzt gruen (vorher xfail).
2. **Setup-Friction beseitigt:**
   - `docker-compose.yml`: Bind-Mount fuer `./tests:/app/tests` + `./conftest.py:/app/conftest.py` ergaenzt — kuenftige Test-Iterationen brauchen kein `docker cp` mehr.
   - `Dockerfile`: `pip install -e ".[dev]"` (statt `-e .`) — pytest + pytest-asyncio sind jetzt im Image, kein nachtraegliches Installieren mehr noetig.

## Verbleibende Defer-Bugs (5 xfails)

Die 5 verbleibenden xfails sind Bugs aus Story 2.1, die im Adversarial-Review als Defer markiert wurden. Wenn ein Bug gefixt wird, schlaegt der Test automatisch um (xpassed). Klare Backlog-Items:

1. **Police Praemie/Notice-Period Range-Check** — Server-seitige Validierung in `_parse_decimal` + Notice-Period-Field. Bundle mit `praemie >= 0`-DB-Constraint aus Retro-Defer. (3 xfails: negative, overflow, notice-period)
2. **Sticky-Form bei 422 in Police-Create** — `#neue-police-form` darf bei Validation-Error nicht `hidden` bleiben.
3. **Wartungspflicht Form-Error-Section-Re-Render** — Aktuell minimal, Pattern-Goal aus Retro.

Empfehlung: Pre-Prod-Hardening-Story (analog Retro Action H1–H3) buendelt 1+2+3.

## Cross-Cutting Befunde fuer Epic 3

- Hinweise aus Memory `feedback_date_tests_pick_mid_month` sind in den **bestehenden** Severity-Tests noch nicht angewendet (`date.today()` direkt). Bei naechster Beruehrung umstellen.
- Tranche A hat gezeigt, dass Soll-Test-Namen aus dem Retro-Befund teilweise unter anderen Namen leben. Test-Inventur via `pytest --collect-only` waere ein guter Pre-Story-Schritt.
