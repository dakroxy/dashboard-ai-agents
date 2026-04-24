# Test-Automatisierung — Story 1.8 (Foto-Upload mit SharePoint + Local-Fallback)

**Datum:** 2026-04-24
**Skill:** `bmad-qa-generate-e2e-tests`
**Scope:** Story 1.8 — Foto-Endpoints auf `/objects/{id}/photos/*`,
SharePoint-Backend mit LocalPhotoStore-Fallback, Nightly-Mirror-Discover

## Ausgangslage

Die Implementierung lieferte 6 Unit-Tests in `tests/test_photo_store_unit.py`
(`validate_photo` + `LocalPhotoStore` + `create_photo_store`-Fallback-Matrix)
und 2 Discover-Tests in `tests/test_steckbrief_impower_mirror_unit.py`
(AC8: Nightly-Mirror legt neue `Object`-Rows fuer unbekannte Impower-PIDs an).

**Die Router-Ebene der vier neuen Foto-Endpoints war komplett nicht
abgedeckt** — keine Tests fuer Upload-Happy-Path, keine fuer BG-Task
+ Status-Polling, keine fuer Delete, keine fuer File-Serve, keine fuer
Permission-Matrix. Dieser Durchlauf schliesst genau diese Luecke.

## Ergebnis

**499 Tests gruen / 0 rot** (vorher: 478). **21 neue Tests** in einer neuen
Datei `tests/test_foto_routes_smoke.py`. Keine Regressionen in bestehenden
Tests.

## Neue Tests

### `tests/test_foto_routes_smoke.py` (neu, 21 Tests)

Router-Ebene fuer `POST /{object_id}/photos`, `GET ...status`,
`DELETE ...`, `GET ...file`. Der Foto-Store wird per Fixture gegen einen
`LocalPhotoStore` auf `tmp_path` getauscht, damit keine echten Dateien
unter `uploads/` entstehen. Einziger Test, der das hart-codierte
`uploads/`-Security-Root braucht (File-Serve-Happy-Path), arbeitet mit
echtem Store und raeumt die Test-Datei im `finally`-Block auf.

**AC2 — Upload (sync, <3 MB)** (2)

- `test_upload_sync_happy_path_creates_photo_row_and_audit` — JPEG +
  `component_ref="heizung_typenschild"`, HTTP 200, Card-Fragment,
  `SteckbriefPhoto`-Row + `AuditLog(action="object_photo_uploaded")`.
- `test_upload_sync_png_also_accepted` — PNG-Pfad.

**AC3 — Upload (BG, >=3 MB) + Status-Polling** (4)

- `test_upload_large_triggers_background_task_and_returns_pending` — Upload
  mit `>= LARGE_UPLOAD_THRESHOLD` Bytes liefert Pending-Fragment mit
  HTMX-Poll-Hint; Photo-Row existiert sofort mit `status="uploading"`.
- `test_status_polling_returns_pending_fragment_while_uploading` — direkter
  GET auf `/photos/{id}/status` liefert Pending-Template, solange
  `photo_metadata.status == "uploading"`.
- `test_status_polling_returns_card_when_done` — bei `status="done"`
  rendert der Endpoint das Card-Fragment.
- `test_status_polling_unknown_photo_returns_404` — fremde Photo-ID in der
  URL → 404.

**AC4 — Ungueltige Uploads** (4)

- `test_upload_unknown_component_ref_returns_400` — Registry lehnt unbekannte
  Komponente ab (z. B. `backofen_typenschild`), keine DB-Row.
- `test_upload_wrong_content_type_returns_400` — PDF mit falschem
  Content-Type → `PhotoValidationError` → 400 + Error-Fragment.
- `test_upload_mismatched_magic_bytes_returns_400` — Content-Type sagt JPEG,
  aber Magic-Bytes sind PNG → 400.
- `test_upload_for_unknown_object_returns_404` — Objekt-ID existiert nicht →
  404.

**AC5 — File-Serve + Delete** (6)

- `test_file_serve_local_returns_file_bytes` — Happy-Path: Upload +
  File-Serve liefern identische Bytes (SHA256-Deduplication).
- `test_file_serve_sharepoint_backed_returns_404_in_v1` — Photo-Row mit
  `backend="sharepoint"` → 404 (v1 liefert keine temporaeren
  Graph-Download-URLs; Defer fuer v1.1).
- `test_file_serve_path_traversal_rejected` — Manipulierter `local_path` auf
  `/etc/passwd` → 403 (Defense-in-Depth gegen kompromittierte DB-Werte).
- `test_delete_removes_row_and_writes_audit` — Delete loescht DB-Row +
  Audit-Log-Eintrag `object_photo_deleted`.
- `test_delete_store_error_does_not_block_db_delete` — Store-Backend wirft
  bei `delete()` → DB-Row wird trotzdem geloescht (Saga-Regel aus
  Story 1.8: lieber File-Leiche als DB-Zombie).
- `test_delete_unknown_photo_returns_404` — fremde Photo-ID → 404.

**AC6 — Permission-Gates** (5)

- `test_upload_forbidden_for_viewer` — User mit `objects:view`, aber ohne
  `objects:edit`, wird bei POST mit 403 abgewiesen; keine DB-Row.
- `test_delete_forbidden_for_viewer` — gleicher User bei DELETE → 403.
- `test_status_polling_requires_objects_view` — User ohne `objects:view`
  kommt an `/status` nicht vorbei (403).
- `test_file_serve_requires_objects_view` — gleiches Muster fuer `/file`.
- `test_upload_anonymous_redirects_to_login` — Anonym: 302/307/401/403
  (je nach Auth-Middleware-Chain).

### Bestehend und unveraendert

- `tests/test_photo_store_unit.py` (6 Tests) — `validate_photo` (JPEG, PNG,
  PDF, Magic-Mismatch, Oversized), `LocalPhotoStore`-Upload / SHA256-Dedup /
  Delete, `LARGE_UPLOAD_THRESHOLD`-Konstante, `create_photo_store`-
  Fallback-Matrix (local-Backend, fehlende SharePoint-Creds, MSAL-Auth-Fail).
- `tests/test_steckbrief_impower_mirror_unit.py::test_mirror_discover_*` —
  2 Tests fuer AC8 (Discover-Pfad im Nightly-Mirror).
- `tests/test_steckbrief_models.py::test_steckbrief_photo_attr_not_metadata` —
  Regression-Anker: JSONB-Feld heisst `photo_metadata`, nicht `metadata`
  (SQLAlchemy-Reserved-Name-Falle).

## Coverage pro AC

| AC | Anforderung | Abdeckung |
|----|-------------|-----------|
| AC1 | SharePoint-Init → Fallback auf LocalPhotoStore | `test_photo_store_unit` (3 Fallback-Tests: local-Backend, fehlende Creds, MSAL-Fail) |
| AC2 | Validierter Upload Route-Ebene | `test_foto_routes_smoke` (2 Happy-Paths + DB-Row + Audit) |
| AC3 | Grosser Upload → BG + HTMX-Polling | `test_foto_routes_smoke` (4 Tests: Trigger-BG, 2× Polling-Status, 404) |
| AC4 | Ungueltige Dateitypen → 400 | `test_foto_routes_smoke` (4 Tests) + `test_photo_store_unit` (validate_photo) |
| AC5 | File-Serve + Delete | `test_foto_routes_smoke` (6 Tests: Happy, SP→404, Path-Traversal, Delete-OK, Delete-mit-Store-Error, Delete-404) |
| AC6 | Permission-Gate | `test_foto_routes_smoke` (5 Tests: Viewer-Matrix + Anon) |
| AC7 | Regressionslauf gruen | Volle Suite 499/499 gruen (Stand 2026-04-24) |
| AC8 | Impower-Nightly-Mirror Discover | `test_steckbrief_impower_mirror_unit` (2 Tests: Create + Idempotenz) |

## Run-Command

```bash
docker compose exec app python -m pytest \
  tests/test_foto_routes_smoke.py \
  tests/test_photo_store_unit.py -v
# 27 passed
```

Volle Suite: `docker compose exec app python -m pytest tests/ -q` → `499 passed`.

## Besonderheiten

### SharePoint-URL-Rendering (v1: nicht implementiert)

`test_file_serve_sharepoint_backed_returns_404_in_v1` dokumentiert bewusst,
dass Fotos mit `backend="sharepoint"` im v1 nicht ausgeliefert werden. Die
Graph-API liefert temporaere Download-URLs (Ablauf ~1 h), die das Backend
pro Render abrufen muesste — das ist als `deferred-work.md` Story 1.8-Item
"SharePoint-Foto-Anzeige via temporaerer Download-Link" notiert und wird
in v1.1 nachgezogen.

### File-Serve vs. tmp_path-Store

Der Router prueft `is_relative_to(pathlib.Path("uploads").resolve())` als
Path-Traversal-Guard. Das ist ein Security-Boundary und bewusst hart
codiert. Der einzelne Test `test_file_serve_local_returns_file_bytes`
arbeitet daher mit einem Store, der in den echten `uploads/`-Ordner
schreibt, und raeumt via `shutil.rmtree("uploads/objects/FS1", ...)` in
`finally` auf. Alle anderen Tests bleiben auf `tmp_path` und stoeren die
Produktion-Upload-Struktur nicht.

### Store-Error bei Delete ist nicht-blockierend

`test_delete_store_error_does_not_block_db_delete` fixiert die bewusste
Entscheidung aus `deferred-work.md` Story 1.8 ("Orphan-Datei wenn DB-Commit
nach Store-Upload scheitert"): ein Backend-Fehler beim Delete blockiert den
DB-Delete nicht. Das entscheidet sich damit fuer "File-Leiche" statt
"DB-Zombie"; sobald die Saga-Pattern-Implementierung kommt, wird dieser
Test angepasst.

## Bewusst NICHT abgedeckt

- **Echter SharePoint-Graph-Roundtrip** — MSAL-Auth + Graph-API-Upload
  werden nur ueber das `create_photo_store`-Fallback-Gate getestet
  (`test_create_photo_store_returns_local_when_msal_token_fails`). Echter
  Upload waere nur gegen einen Testtenant moeglich; out-of-scope.
- **BackgroundTask-Completion-Timing** — `test_upload_large_...` akzeptiert
  bewusst sowohl `uploading` als auch `done` als Status nach dem Request,
  weil der TestClient BG-Tasks nach dem Response synchron ausfuehrt und die
  Reihenfolge nicht deterministisch ist.
- **Orphan-Datei-Cleanup bei DB-Commit-Fail nach Store-Upload** — Saga-
  Pattern noch nicht implementiert; `deferred-work.md` Story 1.8.
- **OOM-Schutz vor `file.read()`** — FastAPI liest Upload-Body vollstaendig
  vor dem Validation-Gate. Vor dem Prod-Rollout durch `Content-Length`-
  Header-Check ergaenzen; dokumentiert in `deferred-work.md`.

## Offene Luecken (nicht im Scope dieser Runde)

- **SharePoint Live-Smoke** beim ersten realen Deploy gegen M365-Testtenant.
  Einmaliger Validierungslauf, kein Dauer-Test.
- **Saga-Cleanup** bei DB-Commit-Fail nach erfolgreichem Store-Upload. Wenn
  implementiert, Test in `test_foto_routes_smoke.py` ergaenzen.
