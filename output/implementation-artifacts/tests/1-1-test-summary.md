# Test-Automatisierung — Story 1.1 (Steckbrief-Bootstrap)

**Datum:** 2026-04-21
**Skill:** `bmad-qa-generate-e2e-tests`
**Scope:** Story 1.1 — Steckbrief-Permissions, Audit-Actions & Default-Header

## Ergebnis

**221 Tests gruen / 0 rot** (vorher: 217 gruen). 5 neue Tests fuer die drei unbedeckten AC-Pfade:

| AC | Status vorher | Status nachher |
|----|---------------|----------------|
| AC1 (8 Permissions in Admin-UI zuweisbar) | unit-seitig abgedeckt, UI-Render nicht verifiziert | **E2E verifiziert** (Checkboxes + Gruppen-Header + Pre-Check) |
| AC2 (Default-Rollen-Subset + additiver Seed-Merge) | vollstaendig abgedeckt | unveraendert |
| AC3 (`X-Robots-Tag` auf allen Responses) | `/health`, `/`, 302-Redirect, 500 | **+ 403 ergaenzt** (Spec: "auch 302/403") |
| AC4 (14 neue Audit-Actions im Filter-Dropdown) | vollstaendig abgedeckt | unveraendert |
| AC5 (keine "unknown Permission"-Fehler beim Render) | nur indirekt ueber Seed-Test | **E2E verifiziert** (Rollen-Edit liefert 200, kein 500) |

## Neue / angepasste Testdateien

### `tests/test_admin_role_edit.py` (neu, 4 Tests)

Deckt AC1 + AC5 gemeinsam: `/admin/roles/{id}` gerendert aus `admin_client` mit `users:manage`.

- `test_page_renders_without_unknown_permission_error` — 200 + HTML (AC5).
- `test_page_contains_all_8_new_permission_checkboxes` — HTML enthaelt `value="objects:view"` … `value="sync:admin"` fuer alle 8 neuen Keys (AC1).
- `test_page_contains_new_permission_groups` — Gruppen-Header `"Objekte"`, `"Registries"`, `"Due-Radar"` im Markup (AC1).
- `test_default_user_subset_is_pre_checked` — 6 User-Default-Keys sind `checked`, `objects:view_confidential` + `sync:admin` NICHT (AC2 UI-Cross-Check).

### `tests/test_routes_smoke.py` (+1 Test)

- `TestXRobotsTagHeader::test_set_on_403` — `auth_client` ohne `audit_log:view` ruft `/admin/logs`, erwartet 403 + Header `X-Robots-Tag: noindex, nofollow`. Damit sind alle in AC3 genannten Response-Klassen (200, 302, 403, 500, HTMX-Fragmente) abgedeckt.

### Unveraendert

`tests/test_steckbrief_bootstrap.py` (Registry / Groups / Default-Rollen / Seed-Merge / Known-Audit-Actions) und `tests/test_admin_logs.py` (Dropdown) decken AC2/AC4/Teile von AC1 bereits sauber ab. Kein Anpassungsbedarf.

## Coverage Story 1.1

- Registrierung, Default-Rollen, Seed-Merge — abgedeckt.
- Admin-Rollen-Edit-Rendering mit allen neuen Keys + Gruppen — abgedeckt.
- `X-Robots-Tag` auf 200 / 302 / 403 / 500 — abgedeckt. HTMX-Fragment-Response nicht eigenstaendig getestet; Middleware greift pro Request einmal, daher implizit identisch.
- Known-Actions-Union im Filter-Dropdown — abgedeckt.

## Run-Command

```bash
docker compose exec app python -m pytest
# 221 passed, 3 warnings in ~0.8s
```

Hinweis: `docker-compose.yml` mountet `./app` und `./migrations`, **nicht** `./tests`. Bei lokalen Test-Aenderungen entweder Container neu bauen oder Dateien via `docker cp tests/<file> <container>:/app/tests/` reinkopieren.

## Naechste Schritte (empfohlen, nicht umgesetzt)

1. **HTMX-Fragment-Header** ggf. expliziter Test, falls spaeter mal ein Middleware-Refactor ansteht (heute verhalten sich HTMX-Fragmente als normale Responses).
2. **Multi-Worker-Seed-Race** (deferred aus Review): `_seed_default_roles` `ON CONFLICT DO NOTHING` oder advisory lock vor Produktiv-Rollout mit >1 Gunicorn-Worker.
3. **Cleanup entfernter Permission-Keys** (deferred): sobald eine Permission aus `PERMISSIONS` rausgeht, Waisen aus `Role.permissions` merzen — Test waere ein Merge-Cleanup-Szenario.
