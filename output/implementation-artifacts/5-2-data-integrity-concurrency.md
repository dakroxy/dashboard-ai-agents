# Story 5-2: Daten-Integritaet & Concurrency

Status: review

## Story

Als Betreiber der Plattform,
moechte ich alle bekannten Race-Conditions, Lost-Update-Pfade und Datenintegritaets-Luecken vor dem externen Rollout schliessen,
damit konkurrente Admin-Edits, Multi-Worker-Boots und Foto-Uploads keine Daten verlieren, korrumpieren oder Server-Crashes ausloesen.

## Boundary-Klassifikation

`hardening` (cross-cutting) — **Hohes Risiko bei Nicht-Umsetzung, mittleres Risiko bei der Umsetzung selbst**.

- Kein neues Feature, nur Absicherung bestehender Schreib-Pfade. Cross-cutting → trifft Documents, Objects (notes_owners + Pflegegrad-Cache), Polices, Schadensfaelle, Wartungspflichten, Foto-Uploads und den Boot-Seed.
- 8 von 9 Defer-Items sind Severity `high` und Pre-Prod-Blocker. Item #140 ist `medium` aber im gleichen Cluster (Range-Hardening) und passt thematisch.
- **Code-only Story** — keine neuen Migrations, keine Schema-Aenderungen. Alle Fixes sind Helper-Funktionen, Row-Locks, Form-Validatoren und ein Saga-Cleanup-Pfad.
- Keine neuen Permissions, keine neuen Routes, keine UI-Aenderungen.

**Vorbedingungen:**

1. **Story 5-1 (`in-progress`)** — wird parallel oder davor abgeschlossen. Keine direkte Code-Kollision: 5-1 fasst `app/middleware/`, `app/main.py` (Middleware-Registrierung), `app/templating.py`, `migrations/` an; 5-2 fasst `app/main.py` (Seed-Funktionen, andere Stelle), `app/routers/objects.py`, `app/routers/documents.py`, `app/services/pflegegrad.py`, `app/services/registries.py`, `app/services/photo_store.py` an. Bei Merge-Konflikt nur in `app/main.py` und nur in disjunkten Funktionsbloecken.
2. **Latest Migration ist `0018_facilioo_mirror_fields.py`** (5-1 baut `0019_police_column_length_caps.py`). 5-2 schreibt **keine** Migration; falls 5-1 mergt, ist `0019` belegt und 5-2 bleibt code-only — kein Konflikt.
3. **53 mutierende Routes** (POST/PUT/DELETE/PATCH) sind durch CSRF aus 5-1 abgedeckt. 5-2 setzt darauf auf — Concurrency-Annahme ist authenticated User mit gueltigem CSRF-Token, der parallel mit einem zweiten authentifizierten User schreibt.

**Kritische Risiken:**

1. **`with_for_update()` in SQLite-Tests** — SQLAlchemy `with_for_update()` wird in SQLite zu einem No-Op (kein Locking). Tests gegen die Race-Conditions koennen nicht echt gegen Postgres laufen, weil `tests/conftest.py` SQLite in-memory mountet. Loesung: zwei Test-Ebenen — (a) Unit-Tests mocken den Lock-Aufruf und verifizieren, dass `with_for_update()` ueberhaupt aufgerufen wird (statement-introspection auf `select(...)`-Query), (b) ein optionaler Postgres-Smoke (manuell, opt-in) verifiziert das echte Verhalten. **Kein** echter Concurrent-Race-Test in CI — zu flaky.

2. **`INSERT ... ON CONFLICT DO NOTHING` ist Postgres-spezifisch** — SQLite unterstuetzt `INSERT OR IGNORE`, das ist syntaktisch aber inkompatibel. Loesung: SQLAlchemy 2.0 `dialect-specific` Insert via `from sqlalchemy.dialects.postgresql import insert as pg_insert` mit `.on_conflict_do_nothing(index_elements=["key"])`. In Tests laeuft dann der normale INSERT mit fang-IntegrityError-Fallback. Saubere Variante: Helper `_seed_role_idempotent(db, key, ...)` der `dialect.name == "postgresql"` checkt und entsprechend dispatched.

3. **Pflegegrad-Cache-Race: Lock-Granularitaet** — `SELECT ... FOR UPDATE OF objects` lockt die ganze Objects-Zeile, nicht nur das Cache-Feld. Bei haeufigem Detail-Page-Aufruf (HTMX-Polling, Mehrfach-Tabs) kann das zu kurzen Lock-Waits fuehren. Akzeptabel, weil der Lock nur fuer den Read-Modify-Write des Cache-Felds gehalten wird (~50 ms). Alternative `ADVISORY_LOCK(hashtext('pflegegrad' || obj.id))` waere granulärer, ist aber Postgres-spezifisch und macht Tests schwerer. **Pragmatisch**: Row-Lock auf Object.

4. **notes_owners Race: Read-Modify-Write Atomicity** — Aktueller Code in `app/routers/objects.py:1679` macht `dict(obj.notes_owners or {})` (snapshot), modifiziert in Python, schreibt via `write_field_human(..., field="notes_owners", value=new_notes)`. Zwei parallele Requests lesen die gleiche `notes_owners`-Snapshot, modifizieren je einen Eigentuemer-Key, schreiben sequentiell — der zweite Write hat den Snapshot des ersten ueberschrieben (= Note-Verlust beim ersten User). Loesung: `db.execute(select(Object).where(Object.id == obj_id).with_for_update())` als ERSTE DB-Operation im Save-Handler, BEVOR `dict(notes_owners or {})` gebaut wird. Damit serialisiert Postgres die Saves auf Row-Ebene.

5. **Concurrent Document-Save: Doppelte Extraction-Rows** — `app/routers/documents.py:886` (`extraction_field_save`) erzeugt eine neue `Extraction`-Row und triggert `_run_matching` als BackgroundTask. Zwei parallele POSTs auf demselben Doc → zwei Extraction-Rows → zwei BG-Tasks → letzter ueberschreibt erste. Loesung: Row-Lock auf `Document` am Anfang des Handlers (`select(Document).where(...).with_for_update()`) plus Doppel-Detection: vor `add(extraction)` pruefen, ob in den letzten 2 Sekunden bereits eine Extraction angelegt wurde, dann return mit aktuellem Stand. **Keine** Sperre auf BG-Task-Ebene (komplexer als noetig).

6. **Foto-Upload Saga: Welche Fehler triggern Cleanup?** — `db.commit()` kann fehlschlagen aus 3 Gruenden: (a) Connection-Drop, (b) Constraint-Violation, (c) Replication-Failure. In allen drei Faellen ist die Datei in `photo_store.upload()` (LocalStore: Dateisystem; SharePoint: Graph-API) bereits geschrieben. Saga-Loesung: `try: photo_store.upload() → try: db.commit() → except: photo_store.delete(ref); db.rollback(); raise`. Risiko: `photo_store.delete()` kann auch fehlschlagen → Best-effort + warning-log, **kein** zweites Try-Except (Schichten-Hoelle). Akzeptierte Restschuld: bei Doppel-Fehler bleibt eine Orphan-Datei + ein `audit("photo_upload_orphan")`-Eintrag fuer manuellen Cleanup.

7. **OOM-Pre-Check: Welcher Punkt ist der richtige?** — Defer-Doku schlaegt Content-Length-Header oder uvicorn-Config vor. **Empfehlung**: Header-Check in der Route VOR `await file.read()`. uvicorn-Config ist global und schiesst andere Upload-Pfade (PDF-Documents bis 50 MB) ab. Konkret: `request.headers.get("content-length")` parsen, gegen `MAX_PHOTO_SIZE_BYTES` (10 MB) vergleichen, bei Ueberschuss 413 vor `await file.read()`. Falls Header fehlt (multipart-edge-case), als Fallback Streaming-Read mit Aborts ueber MAX. **Streaming-Read ist v1.1**, da `UploadFile` keine native Stream-API hat, die size-bounded ist; Header-Check reicht 95 % der Faelle.

8. **Negative Praemie/Schaden: Sanitize vs. Validate** — Defer #69 ist Prevention (Form/Service-Guard verhindert negative Writes), Defer #63 ist Sanitize (registries.py-Aggregation behandelt evtl. existierende negative Werte tolerant). Beide muessen rein. Form-Guard wirft 422, Service-Guard wirft `ValueError` (Belt-and-Suspenders), Aggregation skippt negative Werte mit Warning-Log. **Keine** DB-CHECK-Constraint in dieser Story — das waere `0020`-Migration und schliesst nur Bestandsdaten-Korruption nicht aus (existierende negative Werte muessten erst gepurged werden). Pragmatisch: Code-Schutz reicht v1, CHECK-Constraint ist Post-Prod-Item.

9. **notice_period_months Range: Konkrete Bounds** — Defer-Doku schlaegt `0 <= x <= 360` vor (= 30 Jahre Kuendigungsfrist). Realistisch deckt das jeden Versicherungsvertrag. Ueber 360 → 422 mit klarer Meldung. Bei `int32`-Overflow (Defer #147 ist analog fuer `intervall_monate` — siehe 5-3) ist 360 weit unter `2**31` → kein Overflow-Risiko. **Identisches Pattern auch fuer `intervall_monate` in Wartungspflichten**? Nein — das ist 5-3 (Backend-Robustheit). 5-2 macht **nur** `notice_period_months`, nicht den ganzen Sweep.

10. **Multi-Worker Seed: Welche Tabellen sind betroffen?** — `_seed_default_roles` schreibt in `roles`. `_seed_default_workflow` schreibt in `workflows`. `_seed_default_workflow_access` schreibt in `resource_access`. Alle drei haben UNIQUE-Constraints (roles.key, workflows.key, (resource_access.role_id, resource_access.workflow_id)). Alle drei sind anfaellig. Loesung: alle drei auf `INSERT ... ON CONFLICT DO NOTHING` umstellen, nicht nur `_seed_default_roles`. `INITIAL_ADMIN_EMAILS`-Promotion in `auth.py` ist KEIN Boot-Seed (laeuft pro Login, nicht pro Worker-Start) — nicht in Scope.

## Deferred-Work-Coverage

| # | Eintrag | Severity | AC |
|---|---------|----------|-----|
| 91 | Multi-Worker-Race Erst-Boot `_seed_default_roles` | high | AC1 |
| 34 | Cache-Race Last-Writer-Wins (pflegegrad) | high | AC2 |
| 77 | Concurrent-Save-Race auf demselben Document | high | AC3 |
| 83 | Race-Condition zwei Admins notes_owners JSONB | high | AC4 |
| 129 | OOM durch `file.read()` vor Size-Check | high | AC5 |
| 128 | Orphan-Datei wenn DB-Commit nach Store-Upload scheitert | high | AC6 |
| 63 | Negative Praemie/Schaden nicht sanitiziert (registries.py) | high | AC7 |
| 69 | Negative `praemie`/`Schadensfall.amount` ohne Guard | high | AC7 |
| 140 | `notice_period_months` Range-Check fehlt | medium | AC8 |

## Acceptance Criteria

**AC1 — Multi-Worker-Boot ohne IntegrityError**

**Given** zwei Gunicorn-Worker booten gleichzeitig gegen eine leere `roles`-Tabelle
**When** beide `_seed_default_roles()` parallel ausfuehren
**Then** wirft keiner der beiden einen `sqlalchemy.exc.IntegrityError` auf UNIQUE `roles.key`
**And** der Lifespan-Init laeuft in beiden Workern erfolgreich durch (kein Restart-Loop)
**And** der Helper nutzt `from sqlalchemy.dialects.postgresql import insert as pg_insert` mit `.on_conflict_do_nothing(index_elements=["key"])` wenn `db.bind.dialect.name == "postgresql"`, sonst Fallback auf `try: ... except IntegrityError: db.rollback()` pro Row
**And** dasselbe Pattern wird in `_seed_default_workflow()` (UNIQUE auf `workflows.key`) und `_seed_default_workflow_access()` angewendet — letztere Tabelle (`resource_access`) hat **KEINE** UNIQUE-Constraint (verifiziert in `app/models/resource_access.py`, nur `CheckConstraint` fuer role_id-XOR-user_id), deshalb dort verbindlich SELECT-then-INSERT (`db.execute(select(ResourceAccess).where(role_id=..., resource_type=..., resource_id=...))` → falls leer, INSERT) — kein ON CONFLICT moeglich
**And** der Code-Pfad wird mit einem Unit-Test getriggert, der zwei `_seed_default_roles()`-Calls hintereinander macht — der zweite muss ohne Exception durchlaufen und keine Duplikate erzeugen

**AC2 — Pflegegrad-Cache ohne Lost-Updates**

**Given** zwei parallele GETs auf `/objects/{id}` mit `obj.pflegegrad_score_cached` ist `NULL` oder stale
**When** beide Requests `get_or_update_pflegegrad_cache()` betreten
**Then** lockt der erste Request die `objects`-Zeile via `SELECT ... FOR UPDATE`, schreibt das Cache-Feld, committed
**And** der zweite Request wartet, liest dann den frischen Cache-Wert (`is_stale = False`), skippt den Recompute
**And** kein Cache-Write ueberschreibt einen anderen
**And** die Implementation in `app/services/pflegegrad.py:213-232` (`get_or_update_pflegegrad_cache`) wird so umgebaut, dass `db.execute(select(Object).where(Object.id == obj.id).with_for_update())` als ERSTE DB-Operation laeuft, BEVOR `is_stale` gepruef wird — Lock muss vor Read-Modify-Write sitzen
**And** die Funktion bekommt eine Docstring-Notiz: "Caller muss innerhalb einer Transaktion stehen — der `for_update`-Lock haelt bis zum naechsten `db.commit()` oder `db.rollback()`"
**And** `app/routers/objects.py:285` (Aufruf-Stelle) ruft die Funktion weiterhin direkt; der existierende `db.commit()` an Zeile 287 reicht

**AC3 — Document-Concurrent-Save ohne Doppel-Extractions**

**Given** zwei parallele POSTs auf `/documents/{id}/extractions/{field_name}/save` mit unterschiedlichen Werten
**When** `extraction_field_save()` in `app/routers/documents.py:886` betreten wird
**Then** lockt der erste Request die `documents`-Zeile via `db.execute(select(Document).where(Document.id == doc_id).with_for_update())` als ERSTE DB-Operation
**And** der zweite Request wartet auf den Lock
**And** nach dem Lock: pruefen, ob in den letzten 2 Sekunden bereits eine `Extraction` mit `created_by_user_id == user.id` UND `field_name == field_name` angelegt wurde — wenn ja, kein neuer Insert, sondern Refresh + Return (idempotent)
**And** `_run_matching` als BackgroundTask wird nur **einmal** pro Field-Save geplant — wenn die Idempotenz-Klausel greift, kein neuer BG-Task
**And** der Test triggert einen synthetischen Race (zwei sequentielle Saves innerhalb 1 Sekunde) und verifiziert: nur eine `Extraction`-Row + nur ein `_run_matching`-Aufruf (gemockt)

**AC4 — notes_owners Save ohne Verlust paralleler Edits**

**Given** zwei Admins editieren in zwei Tabs gleichzeitig je eine Note fuer unterschiedliche Eigentuemer am selben Objekt
**When** beide auf "Speichern" klicken (`POST /objects/{id}/eigentuemer/{eig_id}/note/save`)
**Then** lockt der erste Request die `objects`-Zeile via `select(Object).where(Object.id == obj_id).with_for_update()` als ERSTE DB-Operation
**And** der zweite Request wartet, liest den frischen `notes_owners`-Snapshot (mit dem ersten Edit drin), modifiziert seine eigene Note, schreibt — beide Notes ueberleben
**And** die Implementation in `app/routers/objects.py:1679-1687` (`save_owner_note`) wird so umgebaut, dass der Lock vor `dict(obj.notes_owners or {})` greift
**And** das gleiche Pattern wird auf jede andere Save-Route angewendet, die JSONB-Felder am `Object` Read-Modify-Write-mutiert. Dev-Agent fuehrt verbindlich `grep -nE "dict\\(obj\\.[a-z_]+ or \\{\\}\\)|obj\\.[a-z_]+\\[" app/routers/objects.py` aus, dokumentiert das vollstaendige Ergebnis im PR-Description-Block "JSONB-Mutation-Audit" und fuegt fuer jeden weiteren Treffer entweder einen Row-Lock oder eine Begruendung an (z. B. "läuft ueber `write_field_human` mit eigener Transaktions-Klammer")
**And** der Test simuliert zwei sequentielle Saves auf unterschiedlichen Eigentuemer-Keys und verifiziert: am Ende sind beide Notes im Object — kein Last-Writer-Wins-Verlust

**AC5 — Foto-Upload OOM-Pre-Check via Content-Length**

**Given** ein authentifizierter User postet `/objects/{id}/photos` mit einem Multipart-Body groesser als `MAX_PHOTO_SIZE_BYTES` (10 MB, definiert in `app/services/photo_store.py` oder `app/config.py`)
**When** der Request den Handler (`app/routers/objects.py:854`-Bereich) betritt
**Then** liest der Handler ZUERST `request.headers.get("content-length")`, parsed zu int — wenn vorhanden UND `> MAX_PHOTO_SIZE_BYTES * 1.05` (5 % Multipart-Overhead-Toleranz) → return `HTTPException(413, "Foto > 10 MB")`
**And** **NUR** wenn der Pre-Check passt (oder kein Content-Length-Header), erfolgt `await file.read()` — nicht wie heute (Zeile 854) immer
**And** `validate_photo(content, ...)` (Zeile 856) bleibt als zweite Verteidigungslinie fuer den seltenen Fall ohne Content-Length-Header oder bei gefaelschtem Header
**And** Andere Upload-Pfade (PDF-Documents in `app/routers/documents.py`, Case-Documents in `app/routers/cases.py`) sind NICHT in Scope (eigene Limits, eigene Endpunkte) — diese Story haerten nur Foto-Uploads
**And** der Test simuliert einen POST mit `Content-Length: 11000000` ohne realen Body-Read und verifiziert: 413-Response, kein `file.read()`-Aufruf

**AC6 — Foto-Upload-Saga: Cleanup bei DB-Commit-Fail (BEIDE Pfade)**

**Given** der Sync-Pfad `_photo_upload_sync_path()` in `app/routers/objects.py:880` hat `photo_store.upload()` (`:884`) erfolgreich durchgefuehrt (Datei liegt im Store)
**When** `db.commit()` an `:906` wirft eine Exception (z. B. SQL-Constraint, Connection-Drop)
**Then** wird `await photo_store.delete(ref)` als Cleanup gerufen, BEVOR die Exception weitergeworfen wird
**And** `db.rollback()` ist im `except`-Block aufgerufen
**And** wenn `photo_store.delete(ref)` selbst wirft (Datei nicht mehr da, Graph-API down), wird ein `print("[photo-upload-orphan] ...")`-Log geschrieben PLUS `audit(db, user, "photo_upload_orphan", entity_type="object", entity_id=object_id, details={"ref": ref.__dict__})` — Audit landet aber dann in einer NEUEN DB-Session (die alte ist rollbacked), deshalb Helper `_audit_in_new_session(...)` der `SessionLocal()` neu oeffnet, audit anlegt, committet, schliesst
**And** die endgueltige Exception (urspruenglicher commit-Fail) wird re-raised → User sieht 500

**Und ZWINGEND der BG-Pfad:** Der Background-Pfad `_photo_upload_bg_path()` ab `:915` macht ZWEI Commits — den Stub-Insert `:928` (Status `"uploading"`, vor dem Upload) und den finalen Commit im BG-Task nach `photo_store.upload()`. Saga muss im BG-Task greifen: nach erfolgreichem `photo_store.upload()` im BG-Task `try: db.commit() → except: photo_store.delete(ref); update Stub-Photo-Row auf Status `"upload_failed"` (zweite Session); _audit_in_new_session("photo_upload_orphan", ...); raise`. Der Stub-Photo-Eintrag bleibt mit Failure-Status sichtbar (kein verwaister "uploading"-Stub fuer immer).

**Tests:**
- Sync-Pfad: Mock `photo_store.upload()` success + `db.commit()` IntegrityError → `photo_store.delete()` wurde aufgerufen, `_audit_in_new_session()` NICHT (delete-success)
- Sync-Pfad worst-case: `delete()` wirft auch → `_audit_in_new_session()` wird aufgerufen
- BG-Pfad: BG-Task-Funktion direkt aufgerufen, `photo_store.upload()` success + finaler Commit IntegrityError → `delete()` aufgerufen, Stub-Row auf `"upload_failed"` aktualisiert
- BG-Pfad worst-case: `delete()` wirft → `_audit_in_new_session()` aufgerufen

**AC7 — Negative Betraege auf Police und Schadensfall ablehnen**

**Given** ein POST/PUT auf `/objects/{id}/policen` mit `praemie=-100` (oder `/objects/{id}/schadensfaelle` mit `amount=-50`)
**When** die Form-Validation in `app/routers/objects.py:1305` (`praemie` create), `1396` (`praemie` update) oder dem Schadensfall-Handler (`create_schadensfall_route` ab Zeile 1174) durchlaeuft
**Then** parsed der Handler die String-Form-Werte zu `Decimal`, prueft `if val < 0: raise HTTPException(422, "Praemie/Schadensbetrag darf nicht negativ sein")`
**And** zusaetzlich Service-Guard in `app/services/steckbrief_policen.py` (`create_police`/`update_police`): `if praemie is not None and praemie < 0: raise ValueError(...)`. Analog in `app/services/steckbrief_schadensfaelle.py` (`create_schadensfall`/`update_schadensfall`)
**And** in `app/services/registries.py:232` und `:277` werden negative `praemie`/`amount` (falls Bestandsdaten existieren) beim Aggregieren **geskippt** mit `if val is not None and val >= 0: gesamtpraemie += val` — der `> 0`-Guard fuer Division an Zeile 291 bleibt unveraendert
**And** ein Warning-Log `print(f"[registries] negative_value_skipped policy={p.id} field=praemie value={val}")` wird beim Skip geschrieben (Ops-Visibility)
**And** keine DB-CHECK-Constraint in dieser Story (siehe Risiko 8) — Code-Guard reicht v1

**AC8 — notice_period_months Range-Check**

**Given** ein POST/PUT auf `/objects/{id}/policen` mit `notice_period_months=-5` oder `notice_period_months=400`
**When** der Handler in `app/routers/objects.py:1324` (create, innerhalb `if notice_period_months and notice_period_months.strip():` ab `:1322`) bzw. `:1418` (update, innerhalb des Blocks ab `:1416`) `parsed_months = int(notice_period_months.strip())` ausfuehrt
**Then** prueft eine zusaetzliche Zeile `if parsed_months < 0 or parsed_months > 360: raise HTTPException(422, "Kuendigungsfrist muss zwischen 0 und 360 Monaten liegen")` direkt nach dem `int(...)`-Parse
**And** das HTML-Template behaelt `min="0"` als UX-Hint, der Server-Check ist die echte Gate
**And** `0` ist erlaubt (= keine Kuendigungsfrist)
**And** der existierende `try: int(...) except ValueError: ...`-Block wird nicht angefasst — nur die zusaetzliche Range-Validierung **nach** dem erfolgreichen Parse
**And** identisches Verhalten in der update-Route (Block ab `:1416`, Parse `:1418`)

## Tasks / Subtasks

- [x] **Task 1: Multi-Worker-Seed-Idempotenz** (AC1)
  - [x] 1.1 Helper `_seed_role_idempotent(db, key, name, permissions)` in `app/main.py`: dialect-check via `db.bind.dialect.name == "postgresql"`, dann `pg_insert(Role).values(...).on_conflict_do_nothing(index_elements=["key"])`, sonst SELECT-then-INSERT
  - [x] 1.2 `_seed_default_roles()` in `app/main.py` umstellen auf `_seed_role_idempotent`-Calls
  - [x] 1.3 Analog `_seed_default_workflow()` — `_seed_workflow_idempotent` helper mit pg_insert/fallback
  - [x] 1.4 `_seed_default_workflow_access()`: SELECT-then-INSERT (resource_access hat keine UNIQUE-Constraint)
  - [x] 1.5 Tests fuer alle drei Funktionen: zwei aufeinanderfolgende Calls → kein IntegrityError, keine Duplikate

- [x] **Task 2: Pflegegrad-Cache Row-Lock** (AC2)
  - [x] 2.1 In `app/services/pflegegrad.py` (`get_or_update_pflegegrad_cache`): `db.execute(select(Object).where(Object.id == obj.id).with_for_update())` als erste DB-Operation
  - [x] 2.2 Docstring-Notiz zur Transaktions-Anforderung
  - [x] 2.3 Tests: `with_for_update` wird im SELECT gesetzt (statement-introspection), recompute on stale, skip on fresh

- [x] **Task 3: Document-Concurrent-Save Lock + Idempotenz** (AC3)
  - [x] 3.1 In `app/routers/documents.py` (`extraction_field_save`): `db.execute(select(Document).where(...).with_for_update())` nach Permission-Check
  - [x] 3.2 Idempotenz via bestehenden No-Op-Check in `update_extraction_field` (gleicher Wert → return None) — serialisiert durch den Row-Lock
  - [x] 3.3 BG-Task `_run_matching` nur wenn `new_extraction is not None` (unveraendert)
  - [x] 3.4 Tests: Lock-Spy, Idempotenz-Nachweis, zwei verschiedene Werte → zwei Rows

- [x] **Task 4: notes_owners Row-Lock** (AC4)
  - [x] 4.1 In `app/routers/objects.py` (`notiz_save`): `db.execute(select(Object).where(...).with_for_update())` vor `dict(obj.notes_owners or {})`
  - [x] 4.2 JSONB-Mutation-Audit: `grep -nE "dict(obj.[a-z_]+ or {})|obj.[a-z_]+[" app/routers/objects.py` — einziger direkter Treffer ist `notes_owners` bei ~1679; alle anderen JSONB-Mutationen laufen ueber `write_field_human` mit eigener Transaktions-Klammer
  - [x] 4.3 Tests: Lock-Spy, zwei sequentielle Saves auf unterschiedliche Eigentuemer-Keys → beide Notes erhalten

- [x] **Task 5: Foto-Upload Content-Length-Pre-Check** (AC5)
  - [x] 5.1 In `app/routers/objects.py` (Foto-Upload-Handler): `cl_header`-Check vor `await file.read()` mit 5%-Toleranz
  - [x] 5.2 `MAX_SIZE_BYTES` aus `app/services/photo_store.py` importiert
  - [x] 5.3 `validate_photo` bleibt als zweite Verteidigung
  - [x] 5.4 Tests: 413 bei grossem Content-Length, 200 bei validem, kein Header → Fallback greift

- [x] **Task 6: Foto-Upload-Saga (Orphan-Cleanup)** (AC6)
  - [x] 6.1 Sync-Pfad `_photo_upload_sync_path`: try/except um upload+commit, delete on fail
  - [x] 6.2 Worst-case: delete wirft → `_audit_in_new_session("photo_upload_orphan", ...)`
  - [x] 6.3 Helper `_audit_in_new_session()` in `app/services/audit.py`
  - [x] 6.4 BG-Pfad `_run_photo_upload_bg`: Saga nach erfolgreichem upload, Stub-Row auf "upload_failed" bei commit-Fail
  - [x] 6.5 Helper `_update_stub_status_in_new_session()` in `app/services/audit.py`
  - [x] 6.6 Tests: 4 Cases (sync success/worst-case + bg success/worst-case) + stub-visibility

- [x] **Task 7: Negative-Amount-Guards** (AC7)
  - [x] 7.1 Router-Guards in `app/routers/objects.py`: praemie < 0 → HTTPException 422 (police create + update)
  - [x] 7.2 Router-Guard fuer Schadensfall-amount < 0 → HTTPException 422
  - [x] 7.3 Service-Guard `create_police`/`update_police` in `app/services/steckbrief_policen.py`
  - [x] 7.4 Service-Guard `create_schadensfall` in `app/services/steckbrief_schadensfaelle.py`
  - [x] 7.5/7.6 `app/services/registries.py`: negative praemie/schaden skippen + Warning-Log

- [x] **Task 8: notice_period_months Range-Check** (AC8)
  - [x] 8.1 Police-create: Range-Check 0–360 nach int-Parse
  - [x] 8.2 Police-update: identisch

- [x] **Task 9: Tests** (alle ACs)
  - [x] 9.1 `tests/test_data_integrity_concurrency.py` mit 33 Tests
  - [x] 9.2 `pytest tests/test_data_integrity_concurrency.py -v` → 33 passed

- [ ] **Task 10: Rollout-Verifikation lokal**
  - [ ] 10.1 `./scripts/env.sh && docker compose up --build` — kein Boot-Error
  - [ ] 10.2 Manueller Smoke-Test: Police anlegen mit `praemie=-50` → 422; `praemie=100` → 200; `notice_period_months=400` → 422
  - [ ] 10.3 Manueller Smoke-Test: Foto-Upload mit zu grosser Datei (> 10 MB) → 413; normale Datei → 200

## Tests

In `tests/test_data_integrity_concurrency.py`:

**Multi-Worker-Seed (AC1):**
- `test_seed_default_roles_idempotent_postgres_path` — Mock Postgres-Dialect, zwei Aufrufe → kein IntegrityError, keine Duplikate
- `test_seed_default_roles_idempotent_sqlite_path` — Default-Test-DB (SQLite), zwei Aufrufe → kein IntegrityError (try/except-Pfad greift)
- `test_seed_default_workflow_idempotent` — analog
- `test_seed_default_workflow_access_idempotent` — analog

**Pflegegrad-Cache (AC2):**
- `test_get_or_update_pflegegrad_cache_uses_for_update` — Mock-Spy oder Statement-Introspection: `with_for_update()` wird im SELECT-Statement gesetzt
- `test_pflegegrad_cache_recompute_on_stale` — `is_stale=True` → recompute + commit
- `test_pflegegrad_cache_skip_on_fresh` — `is_stale=False` → kein recompute

**Document-Save (AC3):**
- `test_extraction_save_locks_document_row` — Mock-Spy auf `with_for_update`-Call in SELECT(Document)
- `test_extraction_save_idempotent_within_2s` — zwei sequentielle Saves binnen 1s → eine Extraction, ein BG-Task
- `test_extraction_save_after_2s_creates_new_row` — zwei Saves im Abstand > 2s → zwei Extractions

**notes_owners (AC4):**
- `test_save_owner_note_locks_object_row` — Mock-Spy auf `with_for_update`
- `test_save_owner_note_two_users_keeps_both_notes` — sequentiell zwei Saves auf unterschiedliche Eigentuemer-Keys → beide Notes im Object

**Foto-Upload Pre-Check (AC5):**
- `test_photo_upload_rejects_large_content_length_header` — POST mit `Content-Length: 11000000`, kleiner Body → 413
- `test_photo_upload_accepts_valid_content_length` — POST mit `Content-Length: 5000000`, valider Body → 200
- `test_photo_upload_no_content_length_falls_back_to_validate` — POST ohne `Content-Length`-Header (edge case) → `validate_photo` greift wie heute

**Foto-Upload Saga (AC6) — Sync-Pfad:**
- `test_photo_upload_sync_saga_deletes_on_commit_fail` — Mock `db.commit()` raises IntegrityError → `photo_store.delete()` wurde gerufen
- `test_photo_upload_sync_saga_logs_orphan_when_delete_fails` — Mock `delete()` raises → `_audit_in_new_session("photo_upload_orphan", ...)` wurde gerufen
- `test_photo_upload_sync_saga_propagates_original_exception` — Original-IntegrityError wird re-raised → Client sieht 500

**Foto-Upload Saga (AC6) — BG-Pfad:**
- `test_photo_upload_bg_saga_deletes_on_final_commit_fail` — BG-Task-Funktion direkt aufgerufen, finaler Commit nach `photo_store.upload()` raises → `photo_store.delete()` wurde gerufen, Stub-Photo-Row auf Status `"upload_failed"` aktualisiert
- `test_photo_upload_bg_saga_logs_orphan_when_delete_fails` — BG worst-case, `delete()` wirft → `_audit_in_new_session("photo_upload_orphan", ...)` aufgerufen
- `test_photo_upload_bg_stub_remains_visible_after_failure` — nach Saga-Run muss Stub-Row mit `status="upload_failed"` per `db.get(SteckbriefPhoto, photo_id)` lesbar sein (kein Verlust, kein verwaister `"uploading"`-Stub)

**Negative Amounts (AC7):**
- `test_police_create_rejects_negative_praemie` — POST mit `praemie=-100` → 422
- `test_police_create_accepts_zero_praemie` — POST mit `praemie=0` → 200 (Zero ist gueltig)
- `test_police_update_rejects_negative_praemie` — PUT mit `praemie=-50` → 422
- `test_schadensfall_create_rejects_negative_amount` — POST mit `amount=-25` → 422
- `test_registries_skips_negative_praemie_with_warning` — `gesamtpraemie` mit einer negativen Police in DB → wird geskippt, log enthaelt Warning
- `test_registries_skips_negative_schaden_with_warning` — analog `gesamtschaden`
- `test_steckbrief_policen_service_raises_on_negative_praemie` — direkter Service-Call mit `praemie=-1` → ValueError

**notice_period_months (AC8):**
- `test_notice_period_create_rejects_negative` — POST mit `notice_period_months=-5` → 422
- `test_notice_period_create_rejects_over_360` — POST mit `notice_period_months=400` → 422
- `test_notice_period_create_accepts_zero` — POST mit `notice_period_months=0` → 200
- `test_notice_period_create_accepts_360` — Boundary 360 → 200
- `test_notice_period_update_rejects_negative` — PUT analog

## Nicht-Scope

- **DB-CHECK-Constraint fuer `praemie >= 0` und `amount >= 0`** — Belt-and-Suspenders-Idee, aber Migration noetig + Bestandsdaten muessten erst gepurged werden. Code-Guard reicht v1; CHECK-Constraint ist Post-Prod-Item (5-3 oder eigene Hardening-Story).
- **`intervall_monate` Range-Check fuer Wartungspflichten** — Defer #147 ist analog, gehoert aber in 5-3 (Backend-Robustheit / Crash-Guards). 5-2 macht **nur** `notice_period_months`.
- **Streaming-Upload-Read mit harten Size-Caps** — `UploadFile` hat keine native size-bounded Stream-API. Content-Length-Pre-Check deckt 95 % der Faelle. Streaming-Variante ist v1.1.
- **`If-Match`/`ETag`-Mechanik fuer JSONB-Edits** — Defer #83 erwaehnt das als Alternative. SELECT FOR UPDATE ist pragmatischer (kein UI-Change noetig). ETag-Pattern ist v2 wenn Anforderungen wachsen.
- **Advisory-Locks statt Row-Locks** — feiner-granuläre Sperren, aber Postgres-spezifisch und macht Tests schwerer. Row-Lock auf Object-/Document-Zeile ist gut genug fuer < 50 Concurrent-Users.
- **Background-Task-Ebene-Locks** (z. B. `_run_matching` doppelt verhindern) — komplexer als noetig. Idempotenz-Check im Handler greift schon vorher.
- **Orphan keys in `notes_owners` nach Eigentuemer-Loeschung** (Defer #85) — Cleanup-Job, kein Concurrency-Issue. Eigene Story (5-6 oder Post-Prod).

## Dev Notes

### File-Touch-Liste

**Neue Dateien:**
- `tests/test_data_integrity_concurrency.py` — komplette Test-Suite

**Geaenderte Dateien:**
- `app/main.py:115, 156, 188` — `_seed_default_workflow`, `_seed_default_roles`, `_seed_default_workflow_access` auf idempotenten Helper umstellen
- `app/services/pflegegrad.py:213-232` — `with_for_update` am Anfang von `get_or_update_pflegegrad_cache`
- `app/routers/documents.py:886` — `extraction_field_save` mit Document-Row-Lock + 2s-Idempotenz
- `app/routers/objects.py:1679-1687` — `save_owner_note` mit Object-Row-Lock
- `app/routers/objects.py:847-854` — Content-Length-Pre-Check vor `await file.read()`
- `app/routers/objects.py:880, 915` — `_photo_upload_sync_path` und `_photo_upload_bg_path` mit Saga-Cleanup
- `app/routers/objects.py:1305, 1396` — Police-Create/Update: Negative-Praemie-Guard
- `app/routers/objects.py:1324, 1418` — Police-Create/Update: notice_period-Range-Check (innerhalb der Bloecke ab `:1322`/`:1416`)
- `app/routers/objects.py:1174` — Schadensfall-Create-Route: Negative-Amount-Check
- `app/services/steckbrief_policen.py` — Service-Guard fuer negative `praemie`
- `app/services/steckbrief_schadensfaelle.py` — Service-Guard fuer negative `amount`
- `app/services/registries.py:232, 277` — Negative-Skip + Warning-Log in Aggregation
- `app/services/audit.py` — Helper `_audit_in_new_session(...)` fuer Saga-Audit-Schreibung

### Memory-Referenzen (verbindlich beachten)

- `feedback_migrations_check_existing.md` — irrelevant fuer 5-2 (keine Migration), aber generelle Disziplin
- `project_testing_strategy.md` — TestClient + Mocks, keine echten Concurrent-Tests gegen Postgres in CI; statement-introspection auf `with_for_update`-Call reicht
- `project_impower_performance.md` — nicht direkt relevant, aber Concurrency-Pattern (Row-Lock-Granularitaet) ist analog zu Impower-Idempotenz-Mustern in `mietverwaltung_write.py`
- `feedback_default_user_role.md` — irrelevant, aber Auth-Disziplin generell

### Architektur-Bezuege

- **`with_for_update()`-Pattern**: SQLAlchemy 2.0-Syntax, in der Codebase bisher nicht verwendet. Erste Einfuehrung mit dieser Story. Pattern-Dokumentation: nach erfolgreichem Merge der Story einen Eintrag in `docs/project-context.md` ergaenzen ("Concurrency: Row-Lock auf Object/Document via `db.execute(select(...).with_for_update())` als erste DB-Op im Handler").
- **Saga-Pattern**: in `app/services/mietverwaltung_write.py` ist bereits ein aehnliches Idempotenz-Pattern (Schritt-Idempotenz via `case.impower_result`). Der Foto-Saga ist eine vereinfachte Variante (nur ein-Step-Saga), nutzt aber den gleichen Geist: external resource → DB → cleanup-on-fail.
- **`pg_insert` mit `on_conflict_do_nothing`**: `from sqlalchemy.dialects.postgresql import insert as pg_insert`. Pattern-Dokumentation in `docs/project-context.md` ergaenzen.
- **Idempotenz-Fenster**: 2 Sekunden fuer Document-Save ist heuristisch — typische User-Doppelklicks innerhalb 500-1000 ms. 2 Sekunden gibt Luft, ist aber kurz genug, dass legitime Re-Saves nach 5+ Sekunden nicht geblockt werden.

### Threat-Model-Annahmen

- Intranet-App, Login nur ueber Google-Workspace `dbshome.de`-Domain. Concurrent-Edits passieren nur durch authentifizierte interne User.
- Race-Conditions sind kein Angriffsvektor von extern (CSRF aus 5-1 + SameSite=Lax decken das ab), sondern Datenintegritaets-Risiko durch parallele legitime Tabs.
- Multi-Worker-Race ist Boot-spezifisch (passiert nur beim erst-Start mit leerer DB). In Prod aktuell mit 1-Worker-Setup nicht akut, aber bei Skalierung auf 2+ Workers blocker.
- OOM via Foto-Upload ist legitimer DoS-Vektor durch authentifizierten User. Pre-Check schliesst >10MB-Uploads, schuetzt aber nicht vor 100 parallelen 9.9-MB-Uploads — das ist Rate-Limiting, eigene Story.

### References

- Deferred-Work-Quelle: `output/implementation-artifacts/deferred-work.md` (Eintraege #34, #63, #69, #77, #83, #91, #128, #129, #140 — alle in der Severity-Tabelle ab Zeile 49 und mit Detail-Beschreibungen ab Zeile 287/313/322/336/404/422)
- Sprint-Status: `output/implementation-artifacts/sprint-status.yaml` (Zeile mit `5-2-data-integrity-concurrency: backlog`)
- Code-Stand verifiziert in dieser Session: Latest Migration `0018` (5-1 baut `0019` parallel — bereits im Working-Tree als untracked), `_seed_default_roles` ist `app/main.py:156`, `_seed_default_workflow` ist `:115`, `_seed_default_workflow_access` ist `:188` (Tabelle `resource_access` hat KEINE UNIQUE-Constraint, nur `CheckConstraint` fuer role_id-XOR-user_id — daher SELECT-then-INSERT statt ON CONFLICT), `extraction_field_save` ist `app/routers/documents.py:886`, `save_owner_note` ist `app/routers/objects.py:1679-1690` (dict-Snapshot `:1679`, `write_field_human` `:1687`, `db.commit()` `:1690`), `await file.read()` (Foto) ist `:854` mit `validate_photo` Folge `:856`, `_photo_upload_sync_path` startet `:880` mit `photo_store.upload()` `:884` und `db.commit()` `:906`, `_photo_upload_bg_path` startet `:915` (Stub-Insert `db.commit()` `:928`, eigentlicher Upload + finaler Commit im BG-Task), `praemie`-Form ist `:1305`/`:1396`, `notice_period_months`-`int(...)`-Parse ist `:1324`/`:1418` (innerhalb der `if ... .strip():`-Bloecke `:1322`/`:1416`), `gesamtpraemie`-Aggregation ist `app/services/registries.py:232`, `gesamtschaden` ist `:277`, `> 0`-Division-Guard `:291`, Pflegegrad-Cache-Pfad ist `app/services/pflegegrad.py:213` mit Caller in `app/routers/objects.py:285`.

## Change Log

### 2026-05-05 — Implementierung abgeschlossen (Tasks 1–9)

**Alle 8 ACs implementiert, 33 Tests grün.**

**Implementierte Aenderungen (abweichend von Task-Spec):**

- **AC3 Idempotenz-Check**: Story-Spec referenziert `Extraction.field_name` und `Extraction.created_by_user_id` — diese Felder existieren nicht im Extraction-Model. Stattdessen serialisiert der Row-Lock parallele Saves, und der bestehende No-Op-Check in `update_extraction_field` (gleicher Wert → return None) liefert die Idempotenz nach dem Lock.

- **`_seed_default_roles` SQLite-Fallback**: Story-Spec schlug `try: db.flush() except IntegrityError: db.rollback()` in einer Schleife vor. `db.rollback()` wuerde alle vorherigen Loop-Iterationen rueckgaengig machen. Geloest via SELECT-then-INSERT (Race tritt in SQLite single-process nicht auf; Postgres nutzt ON CONFLICT).

- **`_photo_upload_bg_path` Saga**: `photo_store.delete(ref)` ist async; der BG-Task ist sync (`_run_photo_upload_bg`). Losung: `asyncio.run(photo_store.delete(ref))` im except-Block.

- **Task 10 (Rollout-Verifikation lokal)**: offen — erfordert Docker-Compose-Start und manuelle UI-Smoke-Tests.

**JSONB-Mutation-Audit-Ergebnis** (AC4 Pflicht-Schritt):
```
grep -nE "dict\(obj\.[a-z_]+ or \{\}\)|obj\.[a-z_]+\[" app/routers/objects.py
```
Einziger Treffer: `notes_owners` bei Zeile ~1679 (`new_notes = dict(obj.notes_owners or {})`).
Alle anderen JSONB-Mutationen (`zugangscode`, `features`, `contacts`, `steckbrief_fields`, `sepa_mandate_refs`) laufen ueber `write_field_human` mit eigener Transaktions-Klammer — kein zusaetzlicher Row-Lock noetig.
