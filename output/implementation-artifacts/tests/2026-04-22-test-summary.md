# Test-Automation Summary — Scope 1–3 Luecken-Tests

**Datum:** 2026-04-22
**Auslieferung:** 36 neue Tests + 1 Bugfix in Produktionscode
**Baseline:** 272 passed → **308 passed** (alle gruen, keine Regressionen)

Framework: pytest 8 + pytest-asyncio (`asyncio_mode = "auto"`), SQLite-in-memory
via `tests/conftest.py`, Anthropic-/Impower-Calls gemockt (Projektregel aus
`docs/project-context.md` §Testing Rules).

---

## Generierte Tests

### Scope 1 — Story 1.3 (Objekt-Liste + Stammdaten-Detailseite)

**Datei:** `tests/test_steckbrief_service_gaps.py` (8 Tests)

Die vorhandenen 19 Route-Smoke-Tests in `test_steckbrief_routes_smoke.py`
decken die HTTP-Ebene ab. Die Service-Pfade ohne Router-Roundtrip waren offen:

- `test_list_objects_empty_accessible_ids_returns_empty_without_query` —
  Short-Circuit bei `accessible_ids=set()`.
- `test_list_objects_none_accessible_ids_returns_all` — v1-Semantik
  `accessible_ids=None` liefert alle Objekte.
- `test_get_provenance_map_empty_fields_returns_empty` — Early-Return.
- `test_get_provenance_map_unknown_field_returns_none` — `None`-Pill fuer
  Felder ohne jede Provenance-Row.
- `test_get_provenance_map_picks_latest_per_field_by_created_at` — Sort-Key
  `(created_at DESC, id DESC)` identisch zum Write-Gate-Guard. Bei Divergenz
  wuerden Pills und Mirror-Skip-Regel unterschiedliche Rows als "Latest"
  bewerten.
- `test_accessible_object_ids_disabled_user_empty` — disabled User sehen nichts.
- `test_accessible_object_ids_without_view_permission_empty` — Ohne
  `objects:view` leeres Set.
- `test_accessible_object_ids_with_view_returns_all_ids_v1` — Positive Baseline.

### Scope 2a — Stories 1.1/1.2 Write-Gate (Fehler- und Nebenpfade)

**Datei:** `tests/test_write_gate_gaps.py` (10 Tests)

`test_write_gate_unit.py` hatte Happy-Path + JSON-Snapshot + Mirror-Guard +
Pflegegrad-Invalidate. Offen waren die Edge-Cases:

- `test_write_field_human_ai_suggestion_without_user_raises` — Source
  `ai_suggestion` ohne User ist ein Audit-Gap (bricht NFR-S6).
- `test_write_field_ai_proposal_for_encrypted_field_raises` — NFR-S2
  Klartext-Leak-Schutz fuer `entry_code_*`-Felder auch im Proposal-Pfad.
- `test_approve_review_entry_already_decided_raises` — Doppel-Approve.
- `test_approve_review_entry_missing_target_raises` — Ziel-Entity geloescht
  zwischen Proposal und Approve.
- `test_approve_review_entry_unknown_id_raises` — Unbekannte Entry-ID.
- `test_reject_review_entry_already_decided_raises` — Doppel-Reject.
- `test_reject_review_entry_unknown_id_raises` — Unbekannte Entry-ID.
- `test_write_field_human_on_registry_entity_uses_registry_action` — Der
  `_TABLE_TO_ENTITY_TYPE`-Mapper fuer Versicherer schreibt
  `registry_entry_updated`, nicht `object_field_updated` (Filter-Trennung
  in `/admin/logs`).
- `test_write_field_human_on_dienstleister_also_registry_action` —
  Quergegenprobe gegen versehentliches Hardcoding auf `versicherer`.
- `test_write_field_human_entity_without_id_raises` — Entity ohne id
  (nicht geflushed) darf nicht zu `entity_id=None` in Provenance fuehren.

### Scope 2b — Story 1.1 ResourceAccess-Matrix

**Datei:** `tests/test_permissions_resource_access.py` (11 Tests)

`test_permissions.py` testet die Router-Gates, aber die ResourceAccess-Tabelle
war nicht abgedeckt. Wird fuer v1.1 (Objekt-ACL) gebraucht, soll laut
Story 1.1 "ab Tag 1 schreibbar" sein — latente Brueche waeren erst bei
v1.1-Go-Live aufgefallen.

- `test_effective_permissions_merges_role_and_extra_minus_denied`
- `test_effective_permissions_empty_for_disabled_user`
- `test_can_access_resource_role_allow_without_override`
- `test_can_access_resource_user_deny_beats_role_allow` — User-Override
  gewinnt (auch 'deny').
- `test_can_access_resource_user_allow_without_role` — Ad-hoc-Zugriff ohne
  Role.
- `test_can_access_resource_no_override_no_role_defaults_false`
- `test_can_access_resource_disabled_user_always_false`
- `test_accessible_resource_ids_user_deny_filters_role_allow`
- `test_accessible_resource_ids_user_allow_adds_to_role_allows`
- `test_accessible_resource_ids_scoped_to_resource_type` — `workflow`-allow
  leaked nicht in `object`-Query (selbe UUID, anderer Typ).
- `test_accessible_resource_ids_disabled_user_empty`

### Scope 3 — M5 Mietverwaltung-Write-Orchestrator

**Datei:** `tests/test_mietverwaltung_write_orchestrator.py` (7 Tests)

`test_mietverwaltung_write.py` deckt `_write_all_steps` (innere Pipeline).
Der BackgroundTask-Orchestrator `run_mietverwaltung_write` hatte **null
Coverage**, obwohl er Status-Transitions (writing/written/partial/error),
Preflight, Audit-Dispatch und die Fehler-Taxonomie verantwortet.

- `test_run_write_happy_path_sets_written_and_audits`
- `test_run_write_preflight_fail_sets_error_status_and_audits` — Pipeline
  darf bei Preflight-Fail **nicht** laufen.
- `test_run_write_impower_error_sets_partial_when_steps_done` — ImpowerError
  nach mindestens einem abgeschlossenen Step → `partial` (Retry-faehig).
- `test_run_write_impower_error_before_any_step_sets_error` — ImpowerError
  ohne Fortschritt → `error` (nicht partial — waere unehrlich).
- `test_run_write_unexpected_exception_sets_error_and_audits_crashed` —
  Nicht-Impower-Exception trennt Bug vom API-Fehler
  (`mietverwaltung_write_crashed`).
- `test_run_write_unknown_case_id_noops` — Case geloescht zwischen Trigger
  und Task-Start → silent no-op (sonst killt das den BackgroundTask-Worker).
- `test_run_write_sets_writing_status_before_pipeline` — Regressions-Anker
  fuer UI-Meta-Refresh (Spinner statt alter `draft`-Stand).

---

## Bugfix in Produktionscode (aus Test-Generation entdeckt)

**Datei:** `app/services/mietverwaltung_write.py::_commit_state`

**Symptom:** Zweiter `_commit_state(case, ir) + db.commit()` im Fehler-Pfad
persistierte **nichts** — weder `errors[]`, noch Contact-IDs aus Partial-
Success. `case.status` wurde dagegen korrekt aktualisiert. Retries/Idempotenz
waeren damit ausgehebelt, Fehler nicht im Audit-Kanal sichtbar.

**Root Cause:** `_ensure_impower_result` gibt `dict(case.impower_result or {})`
zurueck — flacher Shallow-Copy mit shared nested refs. Spaetere In-Place-
Mutationen an `ir["contacts"]` mutieren damit auch das bestehende
`case.impower_result`-Dict. Beim zweiten `_commit_state` ist `dict(ir)`
value-equal zum alten Attribut → SQLAlchemy sieht "no change" und emittiert
kein UPDATE. Deckt sich mit `project-context.md` §JSONB-Fallen.

**Fix:** `flag_modified(case, "impower_result")` nach dem Reassign.
Ein-Zeiler + erweiterter Docstring.

**Validierung:** Die 4 Orchestrator-Tests im State-Mutations-Pfad haben vor
dem Fix versagt und nach dem Fix gruen geschaltet.

---

## Coverage

| Scope | Bereich | Neue Tests | Bestehende | Summe |
|-------|---------|-----------:|-----------:|------:|
| 1 | Steckbrief-Service (Story 1.3) | 8 | 19 (Routes) + 16 (Bootstrap) | 43 |
| 2a | Write-Gate (Story 1.2) | 10 | 17 | 27 |
| 2b | ResourceAccess (Story 1.1) | 11 | 20 (Router-Gates) | 31 |
| 3 | M5 Write-Orchestrator | 7 | 19 (Pipeline) | 26 |
| **Gesamt** | | **36** | | **308** |

---

## Run-Befehl

```bash
docker compose exec app python -m pytest tests/ -q
# → 308 passed, ~1.5s
```

Gezielt fuer neue Dateien:

```bash
docker compose exec app python -m pytest \
  tests/test_steckbrief_service_gaps.py \
  tests/test_write_gate_gaps.py \
  tests/test_permissions_resource_access.py \
  tests/test_mietverwaltung_write_orchestrator.py \
  -v
```

---

## Offene Luecken (nicht im Scope 1–3)

- **M5 Paket 7 Live-Tests** gegen Impower — Exchange-Plan-Schema muss beim
  ersten realen POST validiert werden (`templateExchanges[]`-Granularitaet).
- **M3 SEPA Neuanlage-Zweig Live-Verifikation** (Tilker GVE1 / Kulessa BRE11).
- **IBAN-Wechsel-Szenario** (M3 Backlog) — Handler noch nicht implementiert.
- **`_address_payload` / `_display_name`** in `mietverwaltung_write` —
  triviale Formatter, indirekt durch Pipeline-Tests abgedeckt.
