# Test Automation Summary — Story 1.4 Impower-Nightly-Mirror Gap-Tests

Datum: 2026-04-22
Scope: Story 1.4 (Impower-Nightly-Mirror Cluster 1 + 6) — gezielt Test-Gaps schliessen, ohne bestehende Tests zu duplizieren.

## Ausgangslage

Story 1.4 hatte bereits 5 Test-Dateien mit solider Basis-Abdeckung:

- `tests/test_sync_common_unit.py` (11 Tests)
- `tests/test_steckbrief_impower_mirror_unit.py` (27 Tests)
- `tests/test_mirror_scheduler.py` (2 Tests)
- `tests/test_admin_sync_status_routes.py` (8 Tests)
- `tests/test_migration_0012_roundtrip.py` (2 Tests)

Die Gap-Analyse identifizierte **7 Bereiche mit echtem Mehrwert** (Data-Safety, Error-Reporting, Edge-Cases), die noch nicht abgedeckt waren.

## Generierte Tests (19 neue)

### P1 — Data-Safety (Prod-Schaden bei Regression)

**`tests/test_steckbrief_impower_mirror_unit.py`** (+10)

- `test_mirror_mandate_503_preserves_existing_sepa_refs`
  Mandate-Fetch-503 (`mandates_unavailable=True`) darf bestehende `sepa_mandate_refs` nicht auf `[]` ueberschreiben.
- `test_mirror_eigentuemer_without_display_name_not_inserted`
  Contact im OWNER-Contract referenziert, aber fehlt im contacts[]-Snapshot → displayName=None → Insert uebersprungen (kein `#999` als Name persistiert).
- `test_normalize_mandate_refs_deduplicates_mixed_int_str_ids`
  `{id: 7}` und `{id: "7"}` werden nach str-Coercion als Duplikat erkannt.
- `test_normalize_mandate_refs_skips_items_without_id`
  Mandate mit `id=None` oder fehlendem id-Key werden uebersprungen, kein TypeError beim Sort.
- `test_normalize_voting_stake_nan_returns_empty`
- `test_normalize_voting_stake_inf_returns_empty`
- `test_normalize_voting_stake_negative_returns_empty`
- `test_normalize_voting_stake_boundary_zero_still_returns_percent`
- `test_normalize_voting_stake_non_numeric_string_returns_empty`
- `test_normalize_voting_stake_caps_float_drift` — `0.1*100` wird auf `10.0` gekappt, damit Folgelaeufe No-Op werden.

### P2 — Error-Reporting (UI zeigt sonst falschen Status)

**`tests/test_sync_common_unit.py`** (+1)

- `test_run_sync_job_fetch_items_error_sets_fetch_failed`
  Wenn `fetch_items` wirft: `result.fetch_failed=True`, `items_failed=1`, Audit-Chain sync_started → sync_failed(phase=fetch) → sync_finished. HTML-Tags werden aus der Fehlermeldung gestrippt.

**`tests/test_admin_sync_status_status_calc.py`** (+7, neues File)
Unit-Tests fuer die Status-Kalkulation in `_load_recent_mirror_runs`:

- `test_status_ok_when_finished_without_failures`
- `test_status_partial_when_objects_failed_positive`
- `test_status_failed_when_fetch_failed_flag_set`
- `test_status_skipped_when_started_has_skipped_flag`
- `test_status_running_when_started_without_finished_and_fresh`
- `test_status_crashed_when_started_stale_without_finished` — Stale-Running-Schwelle (1 h) erkennt crashed Laeufe.
- `test_limit_caps_history_to_requested_count` — Historien-Limit schneidet auf die juengsten N.

### P3 — Edge-Cases

**`tests/test_sync_common_unit.py`** (+1)

- `test_next_daily_run_at_dst_fall_back_returns_valid_instant` — 26. Oktober 2026 (Berlin fall-back), 02:30 existiert zweimal → `fold=0`-Pfad liefert gueltigen Instant, strikt > now.

## Coverage-Delta

| Datei | Vorher | Nachher |
|-------|--------|---------|
| `test_sync_common_unit.py` | 11 | 13 |
| `test_steckbrief_impower_mirror_unit.py` | 27 | 37 |
| `test_admin_sync_status_status_calc.py` | — (neu) | 7 |
| Story-1.4-Tests gesamt | 50 | 69 |

## Ausfuehrung

```bash
docker compose exec -T app python -m pytest \
  tests/test_sync_common_unit.py \
  tests/test_steckbrief_impower_mirror_unit.py \
  tests/test_admin_sync_status_status_calc.py \
  tests/test_admin_sync_status_routes.py \
  tests/test_mirror_scheduler.py \
  tests/test_migration_0012_roundtrip.py
```

Ergebnis: **61/61 passed in 8.03 s**.
Volle Suite: **369/369 passed in 9.36 s** (keine Regressionen).

## Bewusst NICHT abgedeckt

Aus Over-Testing-Disziplin (Project-Rule: "drei aehnliche Zeilen besser als praemature Helper"):

- `_build_full_address` ohne ZIP/City — Code trivial, Mehrwert niedrig.
- `_mirror_scheduler_loop` Timeout-Pfad (`asyncio.wait_for`) — `while True`-Loop, direkter Test nur mit aufwaendiger Extraktion moeglich; produktiv wird der Pfad via Logging im Betrieb sichtbar.
- Weitere `_load_recent_mirror_runs`-Details (duration-Berechnung, next_run-Banner) — Smoke-Tests in `test_admin_sync_status_routes.py` decken das UI-Verhalten bereits ab.

## Naechste Schritte

- Story 1.4 Live-Verifikation: erster geplanter Lauf 02:30 Europe/Berlin, Status per `/admin/sync-status` am Folgemorgen oder sofort via "Jetzt ausfuehren"-Button.
- Bei erstem realen Lauf: Logging auf `_normalize_voting_stake`-WARNINGs achten (Boundary 0/1, NaN), um die Heuristik kalibrieren zu koennen.
