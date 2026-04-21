# Test-Automatisierung — Objektsteckbrief Stories 1.1 + 1.2 (Luecken-Fill)

**Datum:** 2026-04-21
**Skill:** `bmad-qa-generate-e2e-tests`
**Scope:** Gezielte Ergaenzungen zu Story 1.1 + 1.2 nach dem initialen Sprint-Commit `4a2311c`. Ergaenzt `1-1-test-summary.md`.

## Ausgangslage

Der Commit `4a2311c` liefert Stories 1.1 + 1.2 mit bereits sehr dichter Abdeckung (248 Tests gruen). Vorhandene Testdateien zum Thema:

- `test_steckbrief_bootstrap.py` — Registry / Groups / Default-Rollen / Seed-Merge / Known-Audit-Actions
- `test_steckbrief_models.py` — Tabellen-Registrierung + Minimal-Roundtrip
- `test_admin_role_edit.py` + `test_admin_logs.py` — AC1/AC4/AC5 (UI-Render)
- `test_write_gate_unit.py` (20 Tests) — AC4–AC8, AC10 inkl. Mirror, No-Op, Encrypted
- `test_write_gate_coverage.py` — Textscan-Stufe-1
- `test_routes_smoke.py::TestXRobotsTagHeader` — AC3 auf 200/302/403/500

Fokus dieses Runs: **verbleibende realistisch testbare Luecken** — keine Duplikate bestehender Pfade, keine Infra-Umbauten.

## Ergebnis

**252 Tests gruen / 0 rot** (vorher: 248 gruen). 4 neue Tests in 3 Dateien.

| Gap | AC / Defer-Referenz | Datei | Test-Name |
|---|---|---|---|
| HTMX-Fragment-Response + `X-Robots-Tag` | AC3 (1-1-summary "Naechste Schritte" Pkt. 1) | `tests/test_routes_smoke.py` | `TestXRobotsTagHeader::test_set_on_htmx_request` |
| Orphan-Permission-Keys im Seed-Merge | `deferred-work.md` Story 1.1 > "Waise-Permission-Keys" | `tests/test_steckbrief_bootstrap.py` | `test_seed_merge_preserves_orphan_permission_keys` |
| Full-Lifecycle `user_edit → ai_proposal → approve` (Komposition der Helper) | AC4–AC7 integrativ (bislang nur einzeln gepruft) | `tests/test_write_gate_unit.py` | `test_full_lifecycle_user_edit_then_ai_proposal_then_approve` |
| Stale-Proposal / Approve bypasst spaeteren User-Edit | `deferred-work.md` Story 1.2 > "Stale-Proposal-Check beim Approve" | `tests/test_write_gate_unit.py` | `test_approve_silently_overwrites_user_edit_made_after_proposal` |

## Test-Details

### 1) `test_set_on_htmx_request` (routes smoke)

HTMX-Request (`HX-Request: true`) gegen `/workflows/` — auth-client bekommt 200 plus `X-Robots-Tag: noindex, nofollow`. Belegt, dass die Security-Headers-Middleware nicht auf Full-Page-Renders beschraenkt ist.

### 2) `test_seed_merge_preserves_orphan_permission_keys` (bootstrap)

Characterization-Test: legt eine `user`-Rolle mit einem fiktiven Orphan-Key an, ruft `_seed_default_roles()` — Orphan bleibt drin, Default-Merge fuellt trotzdem korrekt auf. Dokumentiert bewusst den aktuellen `set | set`-Merge; wird bei der Einfuehrung einer Intersection gegen `PERMISSION_KEYS` gespiegelt/entfernt.

### 3) `test_full_lifecycle_user_edit_then_ai_proposal_then_approve` (write gate)

Kette `write_field_human` → `write_field_ai_proposal` → `approve_review_entry` in einer Test-DB. Verifiziert:
- KI-Proposal beruehrt Zielfeld nicht (NFR-S6).
- Nach Approve: Zielwert = KI-Wert, zwei `FieldProvenance`-Rows (`{user_edit, ai_suggestion}`), korrekte `source_ref`/`confidence`/`user_id` auf dem AI-Row.
- `ReviewQueueEntry.status == "approved"` mit `decided_by_user_id`.
- Audit-Chain: 2x `object_field_updated` + 1x `review_queue_created` + 1x `review_queue_approved`.

### 4) `test_approve_silently_overwrites_user_edit_made_after_proposal` (write gate)

Regression-Anker fuer das als deferred dokumentierte Stale-Proposal-Szenario. Wenn der User nach Proposal-Erstellung dasselbe Feld manuell editiert, bypasst Approve diesen Edit heute stumm — der Test fixiert dieses Verhalten, damit die UX-Entscheidung aus Story 3.5/3.6 (Warnung / Stale-Status / Force-Flag) sichtbar als Bruch erscheint.

## Run-Command

```bash
docker compose exec app python -m pytest
# 252 passed, 3 warnings in ~0.9s
```

Hinweis: `docker-compose.yml` mountet `./app` und `./migrations`, **nicht** `./tests`. Fuer diesen Run wurden die drei geaenderten Dateien per `docker cp tests/<file> <container>:/app/tests/` reinkopiert.

## Explizit NICHT abgedeckt (Infra-Grenzen)

- **Multi-Worker-Seed-Race** — braucht echten Postgres-UNIQUE; SQLite in-memory ignoriert das stumm. Defer unveraendert.
- **FK `ON DELETE SET NULL` Integration** — braucht Postgres-Testcontainer. Metadaten-Pruefung existiert bereits (`test_review_queue_source_doc_fk_on_delete_set_null`).
- **Approve-Row-Lock-Race** — braucht paralleles Postgres. Defer unveraendert.
- **AST-Stufe-2 Write-Gate-Coverage** — groesserer Eigenbau, bewusst zurueckgestellt bis Textscan-False-Positives relevant werden.
- **Decimal/Date-Roundtrip im Approve** — wird erst mit Story 1.5 (Finanzen-KI-Proposals) scharf. Dann eigener Characterization-Test + Fix.

## Deltas gegen deferred-work.md

Keine Deferred-Items sind durch diese Ergaenzungen obsolet geworden — die Tests dokumentieren aktuelle Zustaende fuer Items, deren Behebung erst mit Folge-Stories sinnvoll ist. `deferred-work.md` bleibt unveraendert.
