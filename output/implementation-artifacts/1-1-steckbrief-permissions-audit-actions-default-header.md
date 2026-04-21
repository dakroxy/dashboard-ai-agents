# Story 1.1: Steckbrief-Permissions, Audit-Actions & Default-Header

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Admin der Plattform,
ich moechte die neuen Steckbrief-Permissions in der Admin-UI zuweisen koennen und die neuen Audit-Actions im Audit-Log-Filter sehen,
damit ich Rollen fuer das kommende Steckbrief-Modul vorbereiten und Nachvollziehbarkeit sicherstellen kann.

## Acceptance Criteria

**AC1 — 8 neue Permissions in Admin-UI zuweisbar**
Given ich bin als Admin eingeloggt,
when ich `/admin/users/{id}` oder `/admin/roles/{id}` oeffne,
then sehe ich die neuen Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `objects:view_confidential`, `registries:view`, `registries:edit`, `due_radar:view`, `sync:admin` als zuweisbare Eintraege in den gruppierten Checkbox-Listen.

**AC2 — Default-Rolle `user` enthaelt 6er-Subset (admin alle)**
Given eine frisch aufgesetzte Instanz oder ein Deploy auf Bestand,
when `_seed_default_roles()` im Lifespan laeuft,
then enthaelt die System-Rolle `user` die Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `registries:view`, `registries:edit`, `due_radar:view` (ohne `objects:view_confidential` / `sync:admin`),
and die System-Rolle `admin` enthaelt **alle** Permission-Keys (inkl. der 8 neuen),
and admin-seitig vorgenommene Custom-Permission-Eintraege auf System-Rollen bleiben erhalten (Seed addiert nur fehlende Default-Keys, entfernt nichts).

**AC3 — Default-Header `X-Robots-Tag: noindex, nofollow`**
Given eine beliebige HTTP-Response der App (auch `/health`, auch HTMX-Fragmente, auch 302/403/500),
when der Browser die Antwort-Header inspiziert,
then ist der Header `X-Robots-Tag: noindex, nofollow` gesetzt.

**AC4 — 14 neue Audit-Actions im Filter-Dropdown**
Given ich bin als Admin eingeloggt und oeffne `/admin/logs`,
when ich den Action-Filter aufklappe,
then erscheinen die 14 neuen Actions `object_created`, `object_field_updated`, `object_photo_uploaded`, `object_photo_deleted`, `registry_entry_created`, `registry_entry_updated`, `review_queue_created`, `review_queue_approved`, `review_queue_rejected`, `sync_started`, `sync_finished`, `sync_failed`, `policy_violation`, `encryption_key_missing` in der Auswahl — **auch wenn noch kein Log-Eintrag mit dieser Action existiert** (Known-Actions-Konstante, nicht nur DB-Distinct).

**AC5 — Keine "unknown Permission"-Fehler**
Given die Plattform-Regel "Permissions zuerst in PERMISSIONS registrieren",
when die Lifespan-Seed-Routine laeuft und ein Admin die Rollen-Bearbeitungs-Seite oeffnet,
then wirft weder der Seed noch das Rendering einen Fehler wegen unbekannter Permission-Keys,
and die Default-Rollen-Tabelle enthaelt die korrekten Zuweisungen aus AC2.

## Tasks / Subtasks

- [x] **Task 1:** Permissions registrieren (AC1, AC5)
  - [x] **Vorab:** Templates `app/templates/admin/users/*.html` + `app/templates/admin/roles/*.html` pruefen — bestaetigen, dass die Permission-Checkbox-Liste generisch ueber `PERMISSIONS_BY_GROUP.items()` rendert (keine hardcoded Gruppen-Namen). Falls Gruppen hardcoded sind, Template-Loop vorher umbauen, sonst tauchen `"Objekte"` / `"Registries"` / `"Due-Radar"` nicht im UI auf.
  - [x] In `app/permissions.py` in der `PERMISSIONS`-Liste 8 neue `Permission(...)`-Eintraege anfuegen. Gruppen-Labels (fuer die Admin-UI-Overschrift via `PERMISSIONS_BY_GROUP`): `"Objekte"` fuer `objects:*`, `"Registries"` fuer `registries:*`, `"Due-Radar"` fuer `due_radar:view`, `"Admin"` fuer `sync:admin`.
  - [x] Labels auf Deutsch, praegnant (z.B. `"Objekte ansehen"`, `"Objekte bearbeiten"`, `"KI-Vorschlaege freigeben"`, `"Vertrauliche Notizen lesen"`, `"Registries ansehen"`, `"Registries bearbeiten"`, `"Due-Radar ansehen"`, `"Sync-Status + Nightly-Jobs verwalten"`).
  - [x] `DEFAULT_ROLE_PERMISSIONS["user"]` um die 6 neuen User-Default-Keys erweitern: `objects:view`, `objects:edit`, `objects:approve_ki`, `registries:view`, `registries:edit`, `due_radar:view`. `admin` bleibt bei `sorted(PERMISSION_KEYS)` (bekommt dadurch automatisch alle 8).
  - [x] `RESOURCE_TYPE_OBJECT = "object"`-Konstante in `app/permissions.py` **nicht** in dieser Story anlegen — das gehoert in Story 1.2 (Migration 0010 + Write-Gate).

- [x] **Task 2:** Merge-basiertes Seed-Verhalten fuer System-Rollen (AC2, AC5)
  - [x] `_seed_default_roles()` in `app/main.py` aendern: wenn die System-Rolle bereits existiert, **fehlende Default-Keys hinzumergen**, Custom-Keys NICHT entfernen. Konkret: `existing.permissions = sorted(set(existing.permissions or []) | set(perms))`. Kommentar im Code anpassen: "Defaults werden bei jedem Start additiv gemerged — User-Customizations bleiben erhalten, aber neue Default-Keys kommen automatisch mit Deploy an."
  - [x] Sicherstellen, dass `is_system_role=True` weiter gesetzt wird (fuer die Delete-Sperre in `/admin/roles`).

- [x] **Task 3:** Known-Audit-Actions-Konstante + Filter-Erweiterung (AC4)
  - [x] In `app/services/audit.py` eine neue Konstante `KNOWN_AUDIT_ACTIONS: list[str]` anlegen mit der kompletten Liste der aktuell bekannten Actions aus `docs/architecture.md` §8 (33 Stueck) **plus** die 14 neuen Steckbrief-Actions aus AC4. Alphabetisch sortiert.
  - [x] In `app/routers/admin.py::list_logs` (`GET /admin/logs`) die Dropdown-Quelle anpassen: `distinct_actions = sorted(set(db_distinct) | set(KNOWN_AUDIT_ACTIONS))`. `db_distinct` ist der bisherige `db.query(AuditLog.action).distinct()`-Lauf.
  - [x] **Template-Check vorab:** `app/templates/admin/logs.html` oeffnen und bestaetigen, dass der Action-Filter generisch ueber `distinct_actions` iteriert (typischerweise `{% for a in distinct_actions %}<option value="{{ a }}">...`). Wenn das Template zusaetzlich filtert (z.B. "nur Actions mit existierenden Logs anzeigen"), den Filter entfernen — sonst schlaegt AC4 fehl, obwohl Backend die Union liefert.
  - [x] Keine AuditLog-Eintraege selbst mit den neuen Actions erzeugen — Emit erfolgt in spaeteren Stories.

- [x] **Task 4:** Default-Middleware `X-Robots-Tag: noindex, nofollow` (AC3)
  - [x] In `app/main.py` einen `@app.middleware("http")`-Dekorator unterhalb der `app`-Instantiierung (und vor den Router-Mounts ist OK — Middleware-Registrations-Reihenfolge ist bei diesem Header egal). Der Middleware-Handler ruft `response = await call_next(request)` und setzt anschliessend `response.headers["X-Robots-Tag"] = "noindex, nofollow"`.
  - [x] Muss fuer **alle** Responses greifen, inkl. Exceptions (Middleware laeuft auch bei HTTPException-Returns, da FastAPI intern die Response zurueckliefert). Fuer `StaticFiles` (`/static/*`) ebenfalls — Starlette laeuft durch die globale Middleware-Chain.
  - [x] Keine Custom-Middleware-Klasse bauen — der Dekorator-Stil reicht fuer einen einzigen Header. Kein Positionstausch mit `SessionMiddleware`; der Header-Setz-Middleware darf davor oder dahinter stehen.

- [x] **Task 5:** Tests (AC1, AC2, AC3, AC4)
  - [x] Neue Datei `tests/test_steckbrief_bootstrap.py`:
    - `test_new_permissions_registered`: prueft `PERMISSION_KEYS` enthaelt alle 8 neuen Keys.
    - `test_permission_groups_populated`: prueft `PERMISSIONS_BY_GROUP` enthaelt die neuen Gruppen-Labels (`"Objekte"`, `"Registries"`, `"Due-Radar"`), Laenge der jeweiligen Liste stimmt.
    - `test_default_user_role_has_steckbrief_subset`: prueft `DEFAULT_ROLE_PERMISSIONS["user"]` enthaelt die 6 Subset-Keys **und nicht** `objects:view_confidential` / `sync:admin`.
    - `test_default_admin_role_has_all_permissions`: prueft `DEFAULT_ROLE_PERMISSIONS["admin"]` enthaelt alle Keys aus `PERMISSION_KEYS`, inkl. der 8 neuen.
    - `test_seed_merges_new_permissions_into_existing_user_role`: schreibt manuell eine Rolle `user` mit altem Perm-Set (nur `["documents:upload"]`) in die Test-DB → ruft `_seed_default_roles()` → prueft, dass die neuen Default-Keys jetzt drin sind **und** `documents:upload` nicht verloren ging.
    - `test_known_audit_actions_includes_new_and_existing`: prueft `KNOWN_AUDIT_ACTIONS` enthaelt die 14 neuen und Spot-Check `"document_uploaded"`, `"login"`, `"case_created"`.
  - [x] In `tests/test_routes_smoke.py` neue Tests `TestXRobotsTagHeader` (health, index, redirect, 500).
  - [x] Admin-Filter-Test als neue Datei `tests/test_admin_logs.py` mit eigenem `admin_client`-Fixture (`audit_log:view` + `users:manage`): `GET /admin/logs` → HTML enthaelt `value="object_created"` + alle weiteren 13 neuen Actions, auch ohne Log-Rows.

### Review Findings

Quellen: Blind Hunter (diff-only) + Edge Case Hunter (diff + repo) + Acceptance Auditor (diff + spec). Triage 2026-04-21 (Reviewer: Opus 4.7).

- [x] [Review][Patch] Filter-Dropdown-Test deckt nur 8 von 14 neuen Actions ab [tests/test_admin_logs.py:40-49] — Spec Task 5 verlangt `value="object_created"` + **alle 13 weiteren** neuen Actions. `test_dropdown_contains_all_new_steckbrief_actions` listet nur 8; `object_photo_deleted`, `registry_entry_updated`, `review_queue_created`, `review_queue_rejected`, `sync_finished` fehlen. AC4 ist durch den Bootstrap-Test trotzdem abgedeckt, aber die im Task zugesagte End-to-End-Dropdown-Verifikation ist unvollstaendig. **Fix: alle 13 ergaenzt.**
- [x] [Review][Patch] `test_known_audit_actions_sorted_alphabetically` ist tautologisch [tests/test_steckbrief_bootstrap.py:140-141] — Konstante ist `sorted([...])` per Konstruktion, Test kann nie fehlschlagen. Entweder Test droppen oder die Konstante als Literal definieren und den Literal-Aufbau pruefen. **Fix: Test entfernt.**
- [x] [Review][Patch] `traceback.print_exc()` umgeht die Logging-Pipeline [app/main.py:209] — Schreibt direkt auf stderr, umgeht den App-Logger und zukuenftige Handler (Sentry, JSON-Log). `logging.getLogger(__name__).exception("unhandled")` ergibt dasselbe Stacktrace plus strukturierte Routing. **Fix: auf `logging.getLogger(__name__).exception(...)` umgestellt, `traceback`-Import entfernt.**
- [x] [Review][Patch] `_ensure_boom_route` mutiert globales `app`-Objekt ohne Cleanup [tests/test_routes_smoke.py:84-95] — Route `/_test/boom` bleibt nach dem Test auf dem App-Objekt und leakt in alle spaeteren Tests im selben Prozess. Entweder als pytest-Fixture mit Teardown oder via temporaeres `FastAPI()`-Sub-App. Low risk heute, aber Footgun fuer spaetere Test-Dateien. **Fix: `boom_route`-Fixture mit Teardown, Route wird nach dem Test aus `app.router.routes` entfernt.**
- [x] [Review][Defer] Multi-Worker-Race bei Erst-Boot: `_seed_default_roles` kann `IntegrityError` auf UNIQUE `roles.key` werfen [app/main.py:119-137] — deferred, pre-existing. Existierte vor dieser Story; in der Neuanlage-Zweig des Seeds koennen zwei parallele Gunicorn-Worker beide gleichzeitig `INSERT`-en. In Elestio-Praxis bisher nicht aufgetreten (Healthcheck faengt Restarts), aber vor echtem Multi-Worker-Produktiv-Rollout zu fixen (z.B. `ON CONFLICT DO NOTHING` oder advisory lock).
- [x] [Review][Defer] `X-Robots-Tag` nicht setzbar auf Responses, deren Body nach `http.response.start` scheitert [app/main.py:201-212] — deferred, pre-existing-design. Betrifft `StreamingResponse`/`FileResponse` (Dokumenten-Downloads). Header und Status-Code sind beim Stream-Abbruch bereits gesendet; die Mitte kann nicht korrigiert werden. Architektonische Grenze, bewusst akzeptiert fuer Story 1.1.
- [x] [Review][Defer] Entfernte Permission-Keys bleiben als Waisen in `Role.permissions` [app/main.py:123-125] — deferred, low. Merge macht `set |`, nie `&`. Ein Key, der spaeter aus `PERMISSIONS` rausgenommen wird, bleibt fuer immer in der JSONB-Spalte. Aktuell kein Enforcement-Pfad betroffen, aber beim naechsten Permission-Cleanup (vermutlich nicht in Epic 1) mitbedenken.

**Dismissed als false positive / by design (14):** `broad except` in Security-Headers-Middleware (explizit fuer AC3), `X-Robots-Tag` auf `/static/*` (Spec: "jede Antwort"), `KNOWN_AUDIT_ACTIONS` typed als `list` (sorted-Reihenfolge bewusst), Seed re-added removed perms (Spec-Entscheidung Task 2 "additiv"), `admin_client` `raise_server_exceptions=True` contradicts 500-test (falsche Fixture-Zuordnung, 500-Test nutzt `anon_client`), `_seed_default_roles` missing commit (commit auf Zeile 138 existiert), Test nutzt Prod-`SessionLocal` (via `conftest.py:67` monkey-patched), `test_seed_merges` UNIQUE-Konflikt durch Lifespan (autouse `_reset_db` cleared Tabellen), `admin_client` lacks User cleanup (covered by `_reset_db`), HTML-Assertion brittle (akzeptabel), Locale-Sort-Nicht-Issue (ASCII keys), `admin_client` zwei disjoint sessions (StaticPool trivial), whitespace-only actions (action keys sind Konstanten), `KNOWN_AUDIT_ACTIONS` pre-registers future actions (Spec AC4 explizit so).

## Dev Notes

### Warum die Merge-Logik im Seed noetig ist
Die aktuelle `_seed_default_roles`-Implementierung skippt existierende Rollen komplett (`if existing is not None: existing.is_system_role = True; continue`). Das verhindert bisher absichtlich, dass Admin-Customizations beim Restart zurueckgesetzt werden. Beim Rollout neuer Default-Permissions (Story 1.1) wuerde das aber bedeuten, dass Bestandsinstanzen die neuen Keys **nicht** bekommen — der `user` auf `dashboard.dbshome.de` haette `objects:view` dauerhaft nicht. Die vom Architekten in `architecture.md` geforderte Zusage "Deploy laedt automatisch in die Default-Rollen; bestehende User-spezifische Overrides bleiben" bezieht sich auf `user.permissions_extra`/`user.permissions_denied` (per-User-Overrides, pro User im Admin-UI gesetzt) — die bleiben durch die Merge-Logik unberuehrt, weil die Merge-Logik nur `role.permissions` modifiziert. Merge (`set |`) statt Replace erlaubt gleichzeitig: neue Defaults kommen rein, admin-seitig hinzugefuegte Custom-Keys (falls jemand in `/admin/roles/{id}` der System-Rolle `user` eine zusaetzliche Permission angeklickt haette) bleiben drin.

### X-Robots-Tag — warum Decorator-Middleware
FastAPI unterstuetzt zwei Middleware-Styles: `app.add_middleware(MiddlewareClass, ...)` und `@app.middleware("http")`-Decorator. Fuer einen einzigen statischen Header ist der Decorator-Stil deutlich weniger Boilerplate. Der Decorator muss **vor** dem ersten Request registriert werden, aber nicht zwingend vor `SessionMiddleware` — die Reihenfolge beeinflusst nur, wer Request/Response in welcher Reihenfolge sieht, und dieser Header wird am Ende der Response-Chain gesetzt (nach `await call_next(request)`).

**500er-Fall:** Bei unbehandelten Exceptions liefert Starlette's `ServerErrorMiddleware` die 500-Response zurueck. Ob die User-Middleware den Header dann noch setzen kann, haengt von der Middleware-Reihenfolge ab. Sauberer Pattern: `call_next` in try/except packen und Header **nach** jeder Response setzen (Success + errorResponse aus dem Handler). Beispiel-Skizze:

```python
@app.middleware("http")
async def set_noindex_header(request: Request, call_next):
    response = await call_next(request)  # Starlette liefert hier auch 500-Responses zurueck
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
```

Starlette konvertiert unbehandelte Exceptions in der inneren Chain bereits zu 500-Responses bevor die User-Middleware zurueckbekommt — der Header wird dann korrekt gesetzt. Der 500-Test aus Task 5 verifiziert das End-to-End.

### Audit-Action-Filter — DB-Distinct vs. Known-Set
Die bisherige Implementierung (`db.query(AuditLog.action).distinct()`) zeigt nur Actions, fuer die bereits Log-Eintraege existieren. Damit sind die 14 neuen Steckbrief-Actions im Filter-Dropdown frisch nach Deploy leer, bis die ersten Writes laufen — das widerspricht AC4 ("erscheinen ... in der Auswahl"). Loesung: Union aus DB-Distinct + `KNOWN_AUDIT_ACTIONS`-Konstante. Die Konstante lebt in `app/services/audit.py` (gleicher Speicherort wie der `audit()`-Helper), damit neue Actions in zukuenftigen Stories beim Hinzufuegen sofort im Dropdown landen, wenn der Entwickler die Konstante miterweitert.

### Nicht im Scope dieser Story (explizit spaeter)
- `RESOURCE_TYPE_OBJECT = "object"`-Konstante → Story 1.2 (braucht `resource_access.resource_type`-Erweiterung, die Teil von Migration 0010/0011 ist).
- Migration `0010_steckbrief_core.py` → Story 1.2 (inklusive aller ORM-Modelle + Governance-Tabellen).
- Write-Gate-Service `steckbrief_write_gate.py` → Story 1.2.
- Tatsaechliches **Emittieren** der neuen Audit-Actions → jeweilige spaetere Stories (1.4 sync, 1.6 object_field_updated, 1.7 encryption_key_missing, 1.8 photo_uploaded, 3.5/3.6 review_queue_*).

### Source tree — zu aendernde Dateien
- `app/permissions.py` — Liste `PERMISSIONS` erweitert; `DEFAULT_ROLE_PERMISSIONS["user"]` erweitert.
- `app/main.py` — `_seed_default_roles()` Merge-Logik; neuer `@app.middleware("http")`-Handler fuer den Default-Header.
- `app/services/audit.py` — neue Konstante `KNOWN_AUDIT_ACTIONS`.
- `app/routers/admin.py::list_logs` — Dropdown-Quelle Union mit `KNOWN_AUDIT_ACTIONS`.
- `tests/test_steckbrief_bootstrap.py` — neue Datei.
- `tests/test_routes_smoke.py` — zwei neue Tests fuer den Header.
- `tests/test_admin_logs.py` — neue Datei (oder in `test_routes_smoke.py` anhaengen), Filter-Dropdown-Test.

### Plattform-Regeln, die gelten
- **Permissions-Reihenfolge zwingend:** (1) Key in `PERMISSIONS` registrieren, (2) Default-Rollen-Seed ergaenzen, (3) Handler schuetzen. Schritt 3 entfaellt in Story 1.1 (es gibt noch keine Handler, die die neuen Keys gaten — das kommt ab Story 1.2). Admin-UI darf trotzdem nicht kaputtgehen, solange Schritt 1 erledigt ist.
- **Migrations nicht autogenerieren.** In Story 1.1 werden aber ohnehin keine angelegt — Schema bleibt unveraendert.
- **`print` + `audit()` statt Logging-Framework** (project-context §Logging). In Story 1.1 kein neuer Log-Output noetig.
- **Tests laufen auf SQLite-in-Memory** (`conftest.py`). Der `_seed_default_roles`-Merge-Test muss die Rolle **vor** Aufruf der Seed-Funktion manuell anlegen (SQLAlchemy-Model `Role` direkt), dann Seed, dann refresh und assertion.
- **German-Commit-Messages ok** (konsistent mit bisherigen Commits laut `git log`).

### Testing standards summary
- Pytest `asyncio_mode = "auto"`, keine Marker-Dekoration noetig.
- `auth_client`/`anon_client`-Fixtures nutzen. Fuer Admin-Tests eigenen Fixture `admin_client` bauen — TestClient mit User, der `audit_log:view` + `users:manage` via `permissions_extra` hat.
- Keine echten Anthropic/Impower-Calls; hier ohnehin nicht relevant.
- TestClient `raise_server_exceptions=True` (default im `auth_client`) — Header-Assertion laeuft gegen echte Middleware-Kette.
- Test-DB wird pro Test zurueckgesetzt (`_reset_db`-Autouse-Fixture); beim Merge-Test ist die Rolle danach wieder weg, andere Tests nicht beeinflusst.

### Project Structure Notes

Die Dateistruktur bleibt streng additiv: keine Router-Refactorings, keine Template-Umbauten. Alle Aenderungen in dieser Story wirken Plattform-Core-weit (`main.py`, `permissions.py`, `audit.py`, ein Router-Handler), das ist gewollt — Story 1.1 ist die "Bootstrap"-Story der Steckbrief-Epic und legt die Schienen fuer Story 1.2+ (Schema) und alle nachfolgenden Feature-Stories. Keine neuen Folder; keine neuen Jinja-Globals/Filter (`templating.py` unveraendert).

Naming: Permission-Keys bleiben im Lower-Case-Colon-Format (`objects:view`, wie bisher `documents:upload`). Audit-Actions snake_case (wie bisher). Permission-Gruppen-Labels sind Deutsch (wie bisher `"Dokumente"`, `"Workflows"`, `"Admin"`), damit die Admin-UI konsistent bleibt.

### References

- [Source: output/planning-artifacts/epics.md#Story 1.1: Steckbrief-Permissions, Audit-Actions & Default-Header]
- [Source: output/planning-artifacts/architecture.md#CD4 — Authentication, Authorization, Audit] — 8 Permissions + Default-Rollen-Aufteilung admin/user; 14 Audit-Actions.
- [Source: output/planning-artifacts/architecture.md#Runtime Operability] — NFR-S7 `X-Robots-Tag` als Default-Header, "trivial, in Fundament-Story mitnehmen".
- [Source: output/planning-artifacts/prd.md#FR32] — Permissions `objects:*` + `registries:*` ueber Rollen/User-Overrides.
- [Source: output/planning-artifacts/prd.md#NFR-S7] — `X-Robots-Tag: noindex, nofollow` fuer alle Routen.
- [Source: docs/project-context.md#Critical Implementation Rules > Permissions-Erweiterung] — Reihenfolge Key-Register → Seed → Handler.
- [Source: docs/project-context.md#Rollen-Vergabe] — INITIAL_ADMIN_EMAILS + Default-Rolle `user` (Memory `feedback_default_user_role`).
- [Source: docs/architecture.md#8. Audit-Trail] — aktuelle Known-Actions-Liste (33 Stueck) fuer `KNOWN_AUDIT_ACTIONS`.
- [Source: app/permissions.py:38-80] — aktuelle `PERMISSIONS`-Liste + `DEFAULT_ROLE_PERMISSIONS` als Erweiterungs-Anker.
- [Source: app/main.py:110-134] — aktuelle `_seed_default_roles`-Implementierung, die Merge-Logik bekommt.
- [Source: app/routers/admin.py:606-655] — `list_logs`-Handler mit `distinct_actions`-Query, der um Known-Set-Union erweitert wird.
- [Source: app/services/audit.py] — Ort fuer `KNOWN_AUDIT_ACTIONS`-Konstante.
- [Source: tests/conftest.py:107-174] — Fixtures `test_user`/`auth_client`/`anon_client` als Basis fuer neue Tests; `admin_client` noch zu bauen.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context)

### Debug Log References

- Templates vorab geprueft: `app/templates/admin/user_edit.html` und `app/templates/admin/role_edit.html` iterieren generisch via `{% for group, perms in permissions_by_group.items() %}` — kein Umbau noetig. `app/templates/admin/logs.html` iteriert ueber `{% for a in distinct_actions %}` ohne zusaetzliche Filter — Backend-Union wirkt direkt.
- Middleware-Verhalten: `@app.middleware("http")` liegt **innerhalb** von Starlettes `ServerErrorMiddleware`. Bei unhandled Exceptions erreicht die User-Middleware die 500-Response nicht mehr, solange sie nicht selbst fangt. Umgesetzt mit `try/except` + `traceback.print_exc()` + manueller `PlainTextResponse("Internal Server Error", 500)`. Der `test_set_on_500`-Case verifiziert das.
- Testlauf: komplette Suite gruen, 217 passed, keine Regressionen.

### Completion Notes List

- 8 neue Permission-Keys in `PERMISSIONS` + 6 davon in `DEFAULT_ROLE_PERMISSIONS["user"]`. `admin` erhaelt durch `sorted(PERMISSION_KEYS)` automatisch alle 8.
- `_seed_default_roles()` additiv gemerged via `set |`; `is_system_role=True` bleibt erhalten.
- `KNOWN_AUDIT_ACTIONS` in `app/services/audit.py`: 33 bestehende + 14 neue = 47 Eintraege alphabetisch sortiert. `list_logs` nutzt Union mit DB-Distinct.
- `X-Robots-Tag: noindex, nofollow` wird in `set_default_security_headers`-Middleware auf **alle** Responses gesetzt — inkl. 500er, Redirects, HTMX, Health.
- Tests: 7 neue Bootstrap-Tests, 4 Header-Tests, 3 Admin-Logs-Filter-Tests. Alle neuen 29 Tests gruen, Gesamtsuite 217 passed.

### File List

- `app/permissions.py` — 8 neue Permissions + 6 neue Default-Keys fuer `user`.
- `app/main.py` — `_seed_default_roles()` Merge-Logik; neue `@app.middleware("http")`-Funktion `set_default_security_headers` (inkl. Exception-Fang fuer 500er); Imports `traceback` + `PlainTextResponse`.
- `app/services/audit.py` — Konstante `KNOWN_AUDIT_ACTIONS: list[str]` (47 Actions).
- `app/routers/admin.py` — `list_logs` baut `distinct_actions` als Union aus DB-Distinct und `KNOWN_AUDIT_ACTIONS`; Import erweitert.
- `tests/test_steckbrief_bootstrap.py` — NEU, 7 Tests (Permission-Registry, Default-Rollen, Seed-Merge, Known-Actions).
- `tests/test_routes_smoke.py` — neue `TestXRobotsTagHeader`-Klasse (health, index, redirect, 500) + Import `app`.
- `tests/test_admin_logs.py` — NEU, 3 Tests (`admin_client`-Fixture + Dropdown-Options).

## Change Log

- 2026-04-21 — Story 1.1 umgesetzt: 8 Steckbrief-Permissions, additives Seed-Merge-Verhalten, `KNOWN_AUDIT_ACTIONS`-Union im `/admin/logs`-Filter, `X-Robots-Tag`-Default-Header als Middleware. 29 neue Tests, Gesamtsuite 217 passed.
- 2026-04-21 — Code-Review durchgelaufen (Opus 4.7, 3 parallele Reviewer). 4 Patches angewandt: (1) Filter-Dropdown-Test auf alle 14 neuen Actions ausgeweitet, (2) tautologischen Sort-Test entfernt, (3) `traceback.print_exc()` → `logger.exception()`, (4) `/_test/boom`-Route in pytest-Fixture mit Teardown. 3 Findings nach `deferred-work.md` verschoben. Gesamtsuite weiterhin 217 passed.
