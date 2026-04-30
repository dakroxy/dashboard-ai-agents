# Story 4.3: 1-Min-Poll-Job mit Delta-Support

Status: review

## Story

Als Mitarbeiter,
moechte ich, dass Facilioo-Tickets minuetlich automatisch in die Steckbrief-DB gespiegelt werden,
damit ich am Objekt-Detail offene Tickets sehe, ohne Facilioo separat aufzurufen.

## Boundary-Klassifikation

`mirror-orchestrator` — Mittleres Risiko. Neuer Lifespan-BackgroundTask, neue Migration (additive Spalten, keine Constraints auf bestehenden Daten), kein Live-Pfad-Eingriff. UI-Erweiterung von `/admin/sync-status` auf zwei Job-Bloecke.

**Vorbedingungen:**

1. **Story 4.1 (Spike) muss „Go v1" empfehlen** — `docs/integration/facilioo-spike.md` enthaelt Go-Empfehlung + Property-Mapping-Entscheidung + Endpoint-Pfad + ETag-Verhalten. Bei „No-Go v1.1" diese Story zuruecklegen, Sprint-Status `4-3-* → backlog`, Epic `4 → backlog` (siehe Story 4.4 AC3-Platzhalter-UI).
2. **Story 4.2 (Client + Hardening) muss `done` sein** — `app/services/facilioo.py` existiert mit `_api_get(..., rate_gate=True)` und 5xx-Backoff `(2, 5, 15, 30, 60)` + 429-`Retry-After`. Der Mirror MUSS dieses Modul nutzen, niemals `httpx.AsyncClient` direkt — sonst schlaegt der Boundary-Test aus 4.2 (`tests/test_facilioo_client_boundary.py`) live an.

**Kritische Risiken:**

1. **Property-Mapping aus dem Spike umsetzen** — Story 4.1 entscheidet, ob `Object.impower_property_id` reicht (Variante A: Facilioo liefert dieselbe ID) oder eine neue `Object.facilioo_property_id`-Spalte noetig ist (Variante B). Die Migration in Task 2 unten ist als Variante B geschrieben (additive Spalte, nullable, indexed). **Vor Implementation Spike-Doc lesen** und ggf. die Migration auf reine `is_archived`-Erweiterung kuerzen. Variante C („kein eindeutiger Mapping-Key") ist ein No-Go fuer v1, dann ist diese Story sowieso zurueckgelegt.
2. **Tickets ohne Object-Match nicht stillschweigend dropped** — wenn Facilioo eine `propertyId` liefert, zu der kein `Object`-Eintrag existiert (neuer WEG, noch nicht im Steckbrief), MUESSEN diese Tickets als `unmapped` geaudited werden (`sync_finished.details_json["unmapped_tickets"]`). Sonst verschwinden sie ins Nichts und niemand merkt, dass die WEG-Pflege haengt.
3. **Lock-Lifecycle vs. asyncio-Loop** — `pytest-asyncio` dreht pro Test einen eigenen Event-Loop. Ein modulglobaler `asyncio.Lock` aus dem Import-Zeitpunkt waere an einen toten Loop gebunden → `RuntimeError: bound to a different event loop`. Pflicht-Pattern (uebernommen aus Story 1.4): Lazy-Getter `_get_poller_lock()` + Test-Hook `_reset_poller_lock_for_tests()`. Vorbild: `app/services/steckbrief_impower_mirror.py:77–91`.
4. **Loop-Lifetime > Tick-Intervall** — bei 5xx-Storm laeuft ein einzelner Mirror-Call (Story 4.2: 112 s Backoff + 5× 30 s Timeout = 262 s Worst-Case) deutlich laenger als 60 s. Der Lock-Skip („`already_running`") aus `_sync_common.run_sync_job()` faengt das ab — der naechste Tick uebersprint sauber, wartet wieder 60 s. **Nicht** im Code-Pfad ein eigenes „kill last run if new tick"-Pattern bauen.
5. **ETag-Persistenz nur in-memory** — der ETag-Cache lebt als Modul-Variable `_last_etag: str | None`. Nach Container-Restart ist der Cache leer; der erste Tick laedt voll und erhaelt einen neuen ETag — kein Bug, nur eine ueberzaehlige Voll-Iteration. **Nicht** in `audit_log.details_json` persistieren (macht den Audit-Log-Filter brittel). **Nicht** in einer eigenen `mirror_state`-Tabelle (Over-Engineering fuer einen 60-s-Loop).
6. **Error-Budget-Logik darf den Loop nicht killen** — wenn die Audit-Query zur Berechnung des Error-Budgets selbst wirft (DB-Down), darf der Loop NICHT crashen. Audit-Query-Fehler werden geloggt + ueber den naechsten Tick erneut versucht. Sonst stirbt der Mirror genau dann, wenn er am wichtigsten waere.
7. **Wahl der Heuristik-Spalte fuer Status-Filter** — die 1-Min-Polling-Frequenz erzeugt ueber 24 h ~1440 `sync_started`-Eintraege im AuditLog. Die Admin-`/admin/sync-status`-Query (`_load_recent_mirror_runs`) ist auf 10 Runs limitiert, also tolerierbar; aber die Error-Budget-Query (Task 5) muss explizit `created_at >= now() - interval '24 hours'` setzen, sonst wird der Index-Scan ueber alle ~1440 Eintraege pro Tag * Lebensdauer immer langsamer.
8. **Doppellauf bei Code-Reload (`uvicorn --reload`)** — Dev-Mode startet zwei Worker, jeder mit eigenem Lifespan. Im Prod (Single-Worker) kein Problem; im Dev koennen beide Worker parallel pollen. Akzeptabel — Facilioo-API ist idempotent (Upsert auf `facilioo_id`). Der Lock ist pro-Process, schuetzt nicht ueber Worker hinweg. Im Doc-Block zu `start_poller()` vermerken, nicht weiter abdecken.

## Acceptance Criteria

**AC1 — Lifespan-Init startet den Poller**

**Given** die App startet (Production mit `settings.facilioo_mirror_enabled = True`)
**When** die Lifespan-Init laeuft
**Then** `app/services/facilioo_mirror.py::start_poller()` schedult eine `asyncio.create_task`-Coroutine, die in einem `while True`-Loop `await asyncio.sleep(settings.facilioo_poll_interval_seconds)` (Default 60.0) ausfuehrt und nach jedem Sleep `run_facilioo_mirror()` aufruft
**And** `start_poller()` ist idempotent gegen doppelten Start im selben Process — ein bereits laufender `_poller_task` wird NICHT durch einen zweiten Aufruf dupliziert (zweiter Call gibt warning ins Log, kein Crash)
**And** Shutdown-Hook (`finally:` im Lifespan, analog `_mirror_scheduler_loop`-Cleanup in `app/main.py:316–321`) ruft `task.cancel()` und awaited den Task; `asyncio.CancelledError` wird sauber geschluckt
**And** mit `settings.facilioo_mirror_enabled = False` startet der Poller NICHT (Log-Hinweis analog `mirror_scheduler: disabled via settings.impower_mirror_enabled`)

**AC2 — Per-Tick-Lock verhindert Doppellauf im selben Process**

**Given** ein Mirror-Run laeuft noch (z. B. wegen Backoff-Storm aus Story 4.2)
**When** der naechste 60-s-Tick `run_facilioo_mirror()` aufruft
**Then** der Lock-Check in `run_sync_job()` (aus `_sync_common.py:226–252`) liefert `SyncRunResult(skipped=True, skip_reason="already_running")`
**And** im AuditLog steht ein `sync_started`-Eintrag mit `details_json={"job": "facilioo_ticket_mirror", "skipped": true, "skip_reason": "already_running", ...}`
**And** der Loop pausiert NICHT — er wartet wieder 60 s und versucht erneut
**And** der Lock wird via Lazy-Getter konstruiert (`_get_poller_lock()` analog `app/services/steckbrief_impower_mirror.py:77–91`), damit `pytest-asyncio` zwischen Tests einen frischen Loop bekommt; Test-Hook `_reset_poller_lock_for_tests()` ist exportiert

**AC3 — Delta via ETag (wenn der Spike Server-Support bestaetigt)**

**Given** Story 4.1 Spike-Doc dokumentiert `ETag-Support: ja`
**When** `_fetch_tickets()` laeuft mit nicht-leerem `_last_etag`
**Then** sendet der Call den Header `If-None-Match: <_last_etag>` (via `app/services/facilioo._api_get` — Erweiterung in Task 3)
**And** bei `304 Not Modified` liefert `_fetch_tickets()` `([], etag_unchanged=True)` zurueck — Reconcile-Pfad ist No-Op, `sync_finished.details_json["etag_unchanged"] = true`
**And** bei `200 OK` extrahiert der Client den neuen `ETag`-Response-Header und setzt `_last_etag = neuer_wert`
**And** der Audit-Log-Eintrag `sync_finished` enthaelt `etag_used: true|false` (true wenn If-None-Match mitgeschickt wurde)

**AC4 — Full-Pull-Fallback mit Diff bei fehlendem Delta-Support**

**Given** Story 4.1 Spike-Doc dokumentiert `ETag-Support: nein` (oder das Spike-Doc ueberschreibt das via Konfig-Flag)
**When** `_fetch_tickets()` laeuft
**Then** zieht der Job ueber `_get_all_paged()` (aus `app/services/facilioo.py`) die komplette Ticket-Liste paginiert
**And** der Diff-Algorithmus in `_reconcile_facilioo_tickets()` macht:
  - `facilioo_id` neu (nicht in DB) → INSERT (Object-Match aus Property-Mapping; ohne Match → `unmapped`-Counter, kein INSERT)
  - `facilioo_id` existiert in DB UND in Facilioo-Response → UPDATE bei semantischem Diff (Vergleich auf `status`, `title`, `raw_payload`-Hash); No-Op bei gleichen Werten (kein Provenance-Churn)
  - `facilioo_id` in DB, fehlt in Facilioo-Response → `is_archived = True` (kein DELETE — Datenerhalt fuer Historie)
**And** Tickets ohne mappbare `propertyId` werden in `sync_finished.details_json["unmapped_tickets"] = [{"facilioo_id": "...", "propertyId": "..."}]` gelistet (Cap auf erste 50 Eintraege, sonst sprengt der Audit-Log)

**AC5 — Error-Budget: > 10 % fehlgeschlagene Polls in 24 h triggern Alert**

**Given** in den letzten 24 h gab es N abgeschlossene `facilioo_ticket_mirror`-Runs UND M davon haben `sync_finished.details_json.fetch_failed = True` ODER `objects_failed > 0`
**When** der naechste Poll-Fehler auftritt UND `M / N > 0.10` (mit `N >= 10`, sonst Sample zu klein)
**Then** wird **zusaetzlich** zu `sync_failed` ein `sync_failed`-Audit mit `details_json={"alert": "error_budget_exceeded", "failure_rate": <float>, "total_runs": N, "failed_runs": M, "window_hours": 24}` geschrieben (entity_type=`"sync_run"`, entity_id=null)
**And** das Admin-Dashboard `/admin/sync-status` zeigt einen roten Alert-Banner ueber dem Job-Block, wenn der letzte Run dieses Audit hat
**And** der Alert wird pro 24-h-Fenster nur **einmal** geschrieben (Idempotenz via Sub-Query: existiert in den letzten 24 h schon ein `error_budget_exceeded`-Alert fuer diesen Job → nicht erneut schreiben)

**AC6 — Migration: `is_archived` + (optional) `facilioo_property_id`**

**Given** die neue Alembic-Revision `0018_facilioo_mirror_fields.py` (down_revision=`"0017"`)
**When** `alembic upgrade head` laeuft
**Then** wird die Spalte `facilioo_tickets.is_archived` als `Boolean NOT NULL DEFAULT FALSE` ergaenzt (Backfill via `server_default`, danach nur durch den Mirror gepflegt)
**And** **falls Spike-Doc Variante B** (separate Facilioo-Property-ID): zusaetzlich Spalte `objects.facilioo_property_id` als `String NULL` mit Index `ix_objects_facilioo_property_id`
**And** der ORM-Mirror in `app/models/facilioo.py` (+ ggf. `app/models/object.py`) wird ENTSPRECHEND erweitert
**And** Down-Migration droppt die Spalten + Index sauber (Reversibilitaet ist Pflicht-Standard)
**And** **vor Migrations-Anlage** `ls migrations/versions/` ausfuehren, um die echte Head-Revision zu lesen — die CLAUDE.md-Liste ist erfahrungsgemaess outdated (Memory: `feedback_migrations_check_existing.md`)

**AC7 — `/admin/sync-status` zeigt zwei Job-Bloecke**

**Given** die Sync-Status-View `/admin/sync-status`
**When** ein User mit `sync:admin` die Seite aufruft
**Then** rendert die Seite ZWEI Job-Bloecke: bestehender `steckbrief_impower_mirror` (Nightly) + neuer `facilioo_ticket_mirror` (1-Min-Poll)
**And** der Facilioo-Block zeigt: letzter Run-Status (ok/partial/failed/skipped), letzte Run-Zeit (Berlin-TZ), Counter (`tickets_inserted`, `tickets_updated`, `tickets_archived`, `tickets_unmapped`, `etag_unchanged`), naechster Run-Zeitpunkt (`<jetzt> + facilioo_poll_interval_seconds`), Alert-Banner bei `error_budget_exceeded`
**And** die bestehende `_load_recent_mirror_runs()`-Funktion (`app/routers/admin.py:730`) wird mit `job_name`-Parameter zweimal aufgerufen — KEIN Code-Duplikat, KEIN neuer Loader
**And** Manual-Trigger-Button („Jetzt ausfuehren") funktioniert pro Job analog `POST /sync-status/run` — Backend-Endpunkt akzeptiert `job_name`-Form-Param und routet zu `run_impower_mirror` oder `run_facilioo_mirror`

**AC8 — Tests: Delta-Logik, Diff-Algorithmus, Error-Budget, Lifespan-Wiring**

**Given** der neue Test-File `tests/test_facilioo_mirror_unit.py`
**When** `pytest tests/test_facilioo_mirror_unit.py -v` laeuft
**Then** sind folgende Tests gruen (Mock-Pattern analog `tests/test_steckbrief_impower_mirror_unit.py`):
  - `test_lock_skip_when_already_running` (AC2)
  - `test_etag_unchanged_short_circuits_reconcile` (AC3)
  - `test_etag_extracted_and_persisted_across_runs` (AC3)
  - `test_full_pull_inserts_new_ticket_with_object_match` (AC4)
  - `test_full_pull_updates_changed_status_no_op_on_identical` (AC4)
  - `test_full_pull_archives_missing_ticket` (AC4)
  - `test_full_pull_unmapped_property_id_audited_not_inserted` (AC2 + AC4)
  - `test_error_budget_alert_fires_when_threshold_exceeded` (AC5)
  - `test_error_budget_alert_idempotent_within_24h_window` (AC5)
  - `test_error_budget_skipped_when_sample_too_small` (N < 10) (AC5)
**And** `tests/test_admin_sync_status_routes.py` wird erweitert um:
  - `test_sync_status_shows_two_job_blocks` (AC7)
  - `test_facilioo_alert_banner_renders_on_error_budget` (AC5 + AC7)
  - `test_manual_trigger_routes_to_facilioo_job_when_job_name_param_set` (AC7)
**And** Lifespan-Test `tests/test_main_lifespan.py` (existiert? Falls nein neu) verifiziert: bei `facilioo_mirror_enabled=True` ist der Task-Name `"facilioo_ticket_mirror_poller"` in `asyncio.all_tasks()` zu finden; bei `False` nicht

## Tasks / Subtasks

- [x] **Task 1: Settings + Konstanten erweitern** (AC1)
  - [x] 1.1: `app/config.py` — Feld `facilioo_mirror_enabled: bool = True` ergaenzen (Doc-Kommentar: „Tests/Dev auf False setzen, sonst pollt der Loop echte Facilioo-Calls")
  - [x] 1.2: `app/config.py` — Feld `facilioo_poll_interval_seconds: float = 60.0` ergaenzen
  - [x] 1.3: `app/config.py` — Feld `facilioo_etag_enabled: bool = True` ergaenzen (Override-Schalter, falls der Spike ETag-Support bestaetigt aber Live-Verhalten flackert)
  - [x] 1.4: `app/config.py` — Feld `facilioo_error_budget_threshold: float = 0.10` + `facilioo_error_budget_window_hours: int = 24` + `facilioo_error_budget_min_sample: int = 10` ergaenzen

- [x] **Task 2: Migration `0018_facilioo_mirror_fields.py`** (AC6)
  - [x] 2.1: `ls migrations/versions/` ausfuehren und Head-Revision verifizieren (sollte `0017` sein — `0017_workflow_default_strings_umlaute.py`, Commit 506e667 — sonst die echte Head-Nummer nutzen)
  - [x] 2.2: Neue Datei `migrations/versions/0018_facilioo_mirror_fields.py` mit `revision = "0018"`, `down_revision = "0017"` (oder echte Head)
  - [x] 2.3: `op.add_column("facilioo_tickets", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")))` — `server_default` statt Python-Default, sonst bleibt der Backfill auf bestehenden Rows leer und schlaegt NOT NULL
  - [x] 2.4: **Falls Spike-Doc Variante B**: `op.add_column("objects", sa.Column("facilioo_property_id", sa.String(), nullable=True))` + `op.create_index("ix_objects_facilioo_property_id", "objects", ["facilioo_property_id"])`
  - [x] 2.5: `downgrade()` — `op.drop_index(...)` + `op.drop_column(...)` in umgekehrter Reihenfolge
  - [x] 2.6: `app/models/facilioo.py` — `is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.text("false"))` ergaenzen
  - [x] 2.7: **Falls Variante B**: `app/models/object.py` — `facilioo_property_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)` ergaenzen

- [x] **Task 3: Facilioo-Client um ETag-Support erweitern** (AC3)
  - [x] 3.1: `app/services/facilioo.py::_api_get` Signatur erweitern um `*, etag: str | None = None, return_response: bool = False`
  - [x] 3.2: Bei `etag is not None`: Header `If-None-Match: <etag>` an den Request anhaengen
  - [x] 3.3: Bei `return_response=True`: Tuple `(parsed_json, response_headers_dict, status_code)` zurueckgeben statt nur `parsed_json` — der Mirror braucht den `ETag`-Response-Header und den Status (304 vs 200). Default `return_response=False` bricht keinen bestehenden ETV-Aufrufer.
  - [x] 3.4: 304-Behandlung: `if resp.status_code == 304: return (None, dict(resp.headers), 304)` — KEIN `raise FaciliooError` (304 ist Erfolgs-Path im Mirror)
  - [x] 3.5: Tests in `tests/test_facilioo_unit.py` (aus Story 4.2) ergaenzen: `test_api_get_etag_header_added`, `test_api_get_304_returns_none`, `test_api_get_return_response_includes_headers`

- [x] **Task 4: Mirror-Modul `app/services/facilioo_mirror.py`** (AC1, AC2, AC3, AC4)
  - [x] 4.1: Neue Datei `app/services/facilioo_mirror.py` anlegen, Modul-Doctstring analog `steckbrief_impower_mirror.py:1–21`
  - [x] 4.2: Imports: `asyncio`, `logging`, `uuid`, `from app.db import SessionLocal`, `from app.models import Object` + `FaciliooTicket`, `from app.services.facilioo import _api_get, _get_all_paged, _make_client, FaciliooError`, `from app.services._sync_common import ReconcileStats, SyncItemFailure, SyncRunResult, run_sync_job`
  - [x] 4.3: Konstanten: `_JOB_NAME = "facilioo_ticket_mirror"`, `_TICKET_LIST_PATH = "<aus Spike-Doc>"` (Pfad ist Output von Story 4.1; wenn `/api/tickets`, dann hier hardcoden)
  - [x] 4.4: Modul-State: `_last_etag: str | None = None`, `_poller_lock: asyncio.Lock | None = None`, `_poller_task: asyncio.Task | None = None`
  - [x] 4.5: Lazy-Getter `_get_poller_lock()` + Test-Hook `_reset_poller_lock_for_tests()` 1:1 nach `steckbrief_impower_mirror.py:80–91` portieren
  - [x] 4.6: Async-Funktion `async def _fetch_tickets() -> tuple[list[dict], dict]` — gibt `(tickets_list, meta_dict)` zurueck, `meta = {"etag_used": bool, "etag_unchanged": bool, "new_etag": str | None}`. Verwendet `_make_client()` + `_api_get(..., etag=_last_etag if settings.facilioo_etag_enabled else None, return_response=True)`. Bei 304: `(_, _, _)` mit `etag_unchanged=True, tickets=[]`. Bei 200: paginiert via `_get_all_paged()` (bzw. neue Variante mit ETag-Erstcall + ggf. Folgeseiten) + setzt `_last_etag = response_headers.get("ETag")`.
  - [x] 4.7: Sync-Funktion `def _diff_and_reconcile(tickets: list[dict], db: Session) -> tuple[ReconcileStats, dict]` — Diff-Algorithmus aus AC4: INSERT (mit Property-Match), UPDATE (semantischer Diff), ARCHIVE (fehlende). Property-Match: `db.execute(select(Object.id).where(Object.facilioo_property_id == ...))` ODER `Object.impower_property_id == ...` (je nach Spike-Variante). Unmapped-Tickets in eigenes Counter-Dict + zurueckgeben.
  - [x] 4.8: Async-Orchestrator `async def run_facilioo_mirror() -> SyncRunResult` analog `run_impower_mirror()` aus `steckbrief_impower_mirror.py:619`. Nutzt `run_sync_job(job_name=_JOB_NAME, fetch_items=fetch_items, reconcile_item=reconcile, db_factory=SessionLocal, lock=_get_poller_lock(), item_identity=lambda t: str(t.get("id")))`.
  - [x] 4.9: Async-Funktion `async def start_poller() -> None` — Idempotenz-Check `global _poller_task; if _poller_task is not None and not _poller_task.done(): _logger.warning(...); return`. Sonst `_poller_task = asyncio.create_task(_poll_loop(), name="facilioo_ticket_mirror_poller")`.
  - [x] 4.10: Async-Funktion `async def _poll_loop()` — `while True: await asyncio.sleep(settings.facilioo_poll_interval_seconds); try: await asyncio.wait_for(run_facilioo_mirror(), timeout=_POLL_RUN_TIMEOUT_SECONDS); except asyncio.TimeoutError: ...; except asyncio.CancelledError: raise; except Exception: _logger.exception(...)`. `_POLL_RUN_TIMEOUT_SECONDS = 5 * 60` (5 min — Worst-Case 262 s aus Story 4.2 + Diff-Phase passt sicher rein, halbiert den naechsten Tick aber nicht).
  - [x] 4.11: Async-Funktion `async def stop_poller() -> None` — `if _poller_task is not None: _poller_task.cancel(); try: await _poller_task; except asyncio.CancelledError: pass; finally: _poller_task = None`.

- [x] **Task 5: Error-Budget-Logik** (AC5)
  - [x] 5.1: Async-Funktion `async def _check_error_budget(db: Session) -> dict | None` in `app/services/facilioo_mirror.py` — Query: `SELECT details_json FROM audit_log WHERE action IN ('sync_started','sync_finished','sync_failed') AND details_json->>'job' = 'facilioo_ticket_mirror' AND created_at >= NOW() - INTERVAL '<window_hours> hours'`. **PFLICHT**: `created_at`-Filter, sonst eskaliert die Query bei langer Lebensdauer.
  - [x] 5.2: Aggregation: pro `run_id` ermitteln, ob der Lauf gescheitert war (`fetch_failed=true` ODER `objects_failed > 0` im `sync_finished`-Eintrag, ODER `sync_failed` ohne `sync_finished`). `total_runs = #distinct run_ids mit sync_started`, `failed_runs = #distinct run_ids mit failed-Indikator`.
  - [x] 5.3: Threshold-Check: `if total_runs >= settings.facilioo_error_budget_min_sample AND failed_runs / total_runs > settings.facilioo_error_budget_threshold: ...`. Idempotenz-Sub-Query: existiert in den letzten 24 h schon ein `sync_failed`-Audit fuer diesen Job mit `details_json->>'alert' = 'error_budget_exceeded'`? Dann return None (kein erneuter Alert).
  - [x] 5.4: Bei Threshold-Trigger: `audit(db, None, "sync_failed", entity_type="sync_run", entity_id=None, details={"alert": "error_budget_exceeded", "job": "facilioo_ticket_mirror", "run_id": "<aktueller run>", "failure_rate": <float>, "total_runs": N, "failed_runs": M, "window_hours": 24}, user_email="system")`. Commit. Return das Detail-Dict zurueck zur UI-Konsumption.
  - [x] 5.5: `_check_error_budget()` wird nach jedem `run_facilioo_mirror()`-Lauf aufgerufen (innerhalb `_poll_loop` nach dem `wait_for`); Audit-Query-Failures nicht propagieren — `try: ...; except Exception: _logger.exception("error_budget check failed"); pass`. Begruendung: Risiko 6 oben.

- [x] **Task 6: Lifespan-Wiring in `app/main.py`** (AC1)
  - [x] 6.1: Neuer Import: `from app.services.facilioo_mirror import start_poller as start_facilioo_poller, stop_poller as stop_facilioo_poller`
  - [x] 6.2: In `lifespan(app)` nach dem bestehenden `scheduler_task = asyncio.create_task(...)`-Block (etwa Zeile 286): `if settings.facilioo_mirror_enabled: await start_facilioo_poller()` (NICHT `asyncio.create_task` — `start_poller()` macht das selbst). Sonst `_logger.info("facilioo_mirror_poller: disabled via settings.facilioo_mirror_enabled")`.
  - [x] 6.3: In `finally:`-Block am Lifespan-Ende: `await stop_facilioo_poller()` ergaenzen — nach dem bestehenden `scheduler_task`-Cleanup.

- [x] **Task 7: `/admin/sync-status` auf zwei Job-Bloecke erweitern** (AC7)
  - [x] 7.1: `app/routers/admin.py` — neue Konstante `_FACILIOO_JOB_NAME = "facilioo_ticket_mirror"` (analog `_MIRROR_JOB_NAME`)
  - [x] 7.2: `sync_status_home()`-Handler (Zeile 908): `_load_recent_mirror_runs()` zweimal aufrufen, einmal pro Job. Template-Context: `jobs = [{"name": "Impower Nightly Mirror", "job_name": "...", "runs": ..., "last_run": ..., "next_run": ..., "alert": ...}, {"name": "Facilioo Ticket Mirror", "job_name": "...", ...}]`.
  - [x] 7.3: `next_run` fuer Facilioo: `datetime.now(tz=timezone.utc) + timedelta(seconds=settings.facilioo_poll_interval_seconds)` — KEIN `next_daily_run_at` (das ist nur fuer den Nightly-Job).
  - [x] 7.4: Alert-Detection: `_load_error_budget_alert(db, job_name=_FACILIOO_JOB_NAME)` — neue Helper-Funktion in `admin.py`, die das letzte `sync_failed`-Audit mit `details_json->>'alert' = 'error_budget_exceeded'` aus den letzten 24 h liest.
  - [x] 7.5: `app/templates/admin/sync_status.html` — die bestehende Single-Job-Render-Logik in einen `{% for job in jobs %}`-Block packen. Alert-Banner als `<div class="bg-red-100 border border-red-400 ...">` ueber dem Job-Block, wenn `job.alert` gesetzt.
  - [x] 7.6: `trigger_mirror_run()`-Endpunkt (`POST /sync-status/run`, Zeile 939): `Form(...)`-Param `job_name: str = Form("steckbrief_impower_mirror")` ergaenzen. Routing-Logik: `if job_name == _FACILIOO_JOB_NAME: background_tasks.add_task(run_facilioo_mirror) else: background_tasks.add_task(run_impower_mirror)`. Unbekannter `job_name` → `HTTPException(400)`.
  - [x] 7.7: Im Template: jeder Job-Block hat einen eigenen „Jetzt ausfuehren"-Button mit `<input type="hidden" name="job_name" value="{{ job.job_name }}">`.

- [x] **Task 8: Tests `test_facilioo_mirror_unit.py`** (AC8)
  - [x] 8.1: Neue Datei `tests/test_facilioo_mirror_unit.py` anlegen, Pattern analog `tests/test_steckbrief_impower_mirror_unit.py`
  - [x] 8.2: Setup-Helpers: `_make_object(db, *, facilioo_property_id="...", impower_property_id=None)`, `_make_ticket(db, *, object_id, facilioo_id, status="open", title="...")`
  - [x] 8.3: `_reset_module_state()` Fixture, die zwischen Tests `_last_etag = None`, `_poller_task = None`, `_reset_poller_lock_for_tests()` ausfuehrt — sonst leakt State zwischen Tests
  - [x] 8.4: AC2: `test_lock_skip_when_already_running` — Lock manuell acquiren, `run_facilioo_mirror()` aufrufen, erwarte `result.skipped is True and result.skip_reason == "already_running"`. AuditLog-Eintrag mit `skipped=True` ist da.
  - [x] 8.5: AC3: `test_etag_unchanged_short_circuits_reconcile` — `_last_etag = "abc"`, monkeypatch `_api_get` so, dass `(None, {"ETag": "abc"}, 304)` zurueckkommt. Erwarte `result.items_ok == 0`, `etag_unchanged=True` im sync_finished, KEINE INSERT/UPDATE/ARCHIVE-Operationen auf `facilioo_tickets`.
  - [x] 8.6: AC3: `test_etag_extracted_and_persisted_across_runs` — Lauf 1: 200 mit `ETag: "first"`. Erwarte `_last_etag == "first"`. Lauf 2: monkeypatch verifiziert, dass `If-None-Match: first` im Request-Header steht.
  - [x] 8.7: AC4: `test_full_pull_inserts_new_ticket_with_object_match` — Object mit `facilioo_property_id="P1"` in DB, Mock-Response liefert 1 Ticket mit `propertyId: "P1"`. Erwarte 1 neue Row in `facilioo_tickets`, `result.items_ok == 1`.
  - [x] 8.8: AC4: `test_full_pull_updates_changed_status_no_op_on_identical` — Bestehende Ticket-Row mit `status="open"`. Mock-Response: gleiche `facilioo_id`, `status="closed"`. Erwarte UPDATE auf `status`. Zweiter Lauf mit identischer Response → keine UPDATE-Statements (verifiziert via SQLAlchemy-Event-Listener oder `db.dirty`).
  - [x] 8.9: AC4: `test_full_pull_archives_missing_ticket` — Bestehende Ticket-Row mit `is_archived=False`. Mock-Response: leere Liste. Erwarte UPDATE: `is_archived=True`. Row bleibt erhalten.
  - [x] 8.10: AC2+AC4: `test_full_pull_unmapped_property_id_audited_not_inserted` — Mock-Response: 1 Ticket mit `propertyId="UNKNOWN"`, kein passendes `Object`. Erwarte: KEIN INSERT, `sync_finished.details_json["unmapped_tickets"]` enthaelt `[{"facilioo_id": "...", "propertyId": "UNKNOWN"}]`.
  - [x] 8.11: AC5: `test_error_budget_alert_fires_when_threshold_exceeded` — Setup: 12 sync_started + 12 sync_finished mit fetch_failed=True in den letzten 24 h. Erwarte: nach naechstem Lauf existiert `sync_failed`-Audit mit `alert="error_budget_exceeded"`, `failure_rate >= 0.10`.
  - [x] 8.12: AC5: `test_error_budget_alert_idempotent_within_24h_window` — 1. Lauf triggert Alert. 2. Lauf (mit gleichen Bedingungen) → KEIN zweiter Alert-Audit (Idempotenz via Sub-Query).
  - [x] 8.13: AC5: `test_error_budget_skipped_when_sample_too_small` — 5 Runs (alle gescheitert) → `failure_rate = 1.0` aber `total_runs < min_sample=10` → kein Alert.
  - [x] 8.14: `test_etag_disabled_via_settings_skips_header` — `settings.facilioo_etag_enabled = False`, `_last_etag = "abc"`. Erwarte: `If-None-Match`-Header ist NICHT im Request.

- [x] **Task 9: Tests `test_admin_sync_status_routes.py` erweitern** (AC7, AC5)
  - [x] 9.1: `test_sync_status_shows_two_job_blocks` — GET `/admin/sync-status` → Response enthaelt beide Job-Namen („Impower Nightly Mirror" + „Facilioo Ticket Mirror")
  - [x] 9.2: `test_facilioo_alert_banner_renders_on_error_budget` — Setup: `sync_failed`-Audit mit `alert="error_budget_exceeded"` in letzten 24 h. Erwarte: Response enthaelt `class="bg-red-100"` (oder gewaehlte Banner-Klasse) im Facilioo-Block
  - [x] 9.3: `test_manual_trigger_routes_to_facilioo_job_when_job_name_param_set` — POST `/admin/sync-status/run` mit Form `job_name=facilioo_ticket_mirror`, monkeypatch `run_facilioo_mirror`. Erwarte: `run_facilioo_mirror` wurde aufgerufen, NICHT `run_impower_mirror`.
  - [x] 9.4: `test_manual_trigger_unknown_job_name_returns_400` — POST mit `job_name=bogus` → HTTP 400
  - [x] 9.5: `test_manual_trigger_default_job_name_uses_impower` — POST ohne `job_name`-Param → `run_impower_mirror` wird aufgerufen (Backwards-Compat zu Story 1.4)

- [x] **Task 10: Smoke + Sprint-Status** (alle AC)
  - [x] 10.1: `pytest tests/test_facilioo_mirror_unit.py tests/test_admin_sync_status_routes.py tests/test_facilioo_unit.py -v` — alle gruen
  - [x] 10.2: `pytest` (Full-Suite) — keine neuen Failures (Soll: Baseline aus 4.2 + neue Tests aus 4.3)
  - [x] 10.3: Container-Smoke: `docker compose up --build`, `/admin/sync-status` aufrufen, beide Bloecke sichtbar; bei `facilioo_bearer_token=""` (lokal) zeigt der Facilioo-Block den ersten `sync_failed`-Eintrag mit klarem Token-Fehler (aus `_make_client()` in `facilioo.py`)
  - [x] 10.4: Sprint-Status: Story 4.3 → `review` (Hand-Off an Code-Review)
  - [x] 10.5: PR-Body: in „Live-Verifikation offen" festhalten, dass eine Live-Mirror-Probe gegen echten Facilioo-Tenant noetig ist (Counter beobachten, `unmapped_tickets`-Liste pruefen, ETag-Behaviour gegen Spike-Annahme verifizieren)

## Dev Notes

### Was bereits existiert — NICHT neu bauen

| Artifact | Pfad | Inhalt |
|---|---|---|
| Sync-Job-Wrapper | `app/services/_sync_common.py` | `run_sync_job()`, `SyncRunResult`, `SyncItemFailure`, `ReconcileStats`, `strip_html_error`. Lock-Skip-Pfad, Audit-Wiring, per-Item-Session — alles bereits geprueft (Story 1.4). 1:1 wiederverwenden. |
| Lazy-Lock + Test-Hook (Vorbild) | `app/services/steckbrief_impower_mirror.py:77–91` | `_get_mirror_lock()` + `_reset_mirror_lock_for_tests()`. Pattern fuer pytest-asyncio-Loop-Lifecycle. |
| Sync-Job-Pattern (Vorbild) | `app/services/steckbrief_impower_mirror.py:619–698` | Komplettes Beispiel: `fetch_items` (Closure mit shared State), `reconcile`, `run_sync_job`-Aufruf. Die Mirror-Architektur 4.3 ist eine Variante davon mit weniger ORM-Spalten und ETag-Header. |
| Sync-Status-Loader | `app/routers/admin.py:730–905` | `_load_recent_mirror_runs(db, *, job_name, limit=10)`. Bereits parametrisiert ueber `job_name` — fuer Facilioo-Job einfach mit `_FACILIOO_JOB_NAME` aufrufen. Kein Code-Duplikat. |
| Sync-Status-Template | `app/templates/admin/sync_status.html` | Bestehender Single-Job-Render. In `{% for job in jobs %}` packen. |
| Lifespan-Scheduler-Pattern | `app/main.py:222–321` | `_mirror_scheduler_loop` + Lifespan-Wiring + Cleanup. Fuer Story 4.3 ohne den `sleep_until`-Berechnungs-Teil — wir brauchen nur `await asyncio.sleep(60)`. |
| Audit-Helper | `app/services/audit.py:95` | `audit(db, user_or_None, action, *, entity_type=..., entity_id=..., details=..., user_email="system")`. `sync_started`/`sync_finished`/`sync_failed` sind bereits in `KNOWN_AUDIT_ACTIONS` registriert. |
| FaciliooTicket-Model | `app/models/facilioo.py` | `id` (UUID PK), `object_id` (FK→objects), `facilioo_id` (UNIQUE), `status`, `title`, `raw_payload` (JSONB), `created_at`, `updated_at`. **`is_archived` fehlt** — Migration 0018 ergaenzt das. |
| Facilioo-Client (aus Story 4.2) | `app/services/facilioo.py` | `_make_client()`, `_api_get()`, `_get_all_paged()`, `FaciliooError`, Rate-Gate (Default `True` fuer Mirror), 5xx-Backoff `(2, 5, 15, 30, 60)`, 429-`Retry-After`. Mirror nutzt Default `rate_gate=True` — KEIN `False`-Override. |
| Object-Model | `app/models/object.py` | Hat `impower_property_id: Mapped[str | None]` (indexed). **`facilioo_property_id` fehlt** — Migration 0018 ergaenzt das, falls Spike Variante B empfiehlt. |

### Architektur-Verankerung

- **CD3 Sync-Orchestrator** (`output/planning-artifacts/architecture.md:284–315`) — drei Sync-Modi ueber denselben Layer (`_sync_common.run_sync_job`). Nightly-Mirror (Impower) und 1-Min-Poll (Facilioo) teilen die komplette Audit-/Lock-/Per-Item-Session-Mechanik. Story 4.3 bringt KEINE neue Mechanik mit — nur einen weiteren Aufrufer.
- **Integrations-Boundary** (`output/planning-artifacts/architecture.md:642–643`) — `facilioo.py` ist einziger Facilioo-Client. `facilioo_mirror.py` darf nur ueber `facilioo.py` laufen, niemals direkt `httpx.AsyncClient`. Die Allow-List in `tests/test_facilioo_client_boundary.py` (Story 4.2) enthaelt bereits `app/services/facilioo_mirror.py` — wir muessen sie nicht erweitern, der Test bleibt gruen.
- **FR28** (`output/planning-artifacts/prd.md:568`) — „pollt Facilioo-Tickets in Ein-Minuten-Takt und spiegelt sie als FaciliooTicket-Entitaet; wenn der Server ETag/If-Modified-Since unterstuetzt, laedt der Job nur Deltas". Story 4.3 erfuellt FR28 vollstaendig.
- **NFR-R3 / NFR-O3** (architecture §710-711) — Sync-Stabilitaet: einzelne Item-Fehler brechen den Job nicht; Status sichtbar im Admin-Dashboard. Beides via `run_sync_job` + `/admin/sync-status` bereits abgedeckt.

### Property-Mapping — Spike-Output ist Pflicht-Input

Story 4.1 entscheidet, wie Tickets ihren `Object`-FK bekommen. Drei moegliche Auspraegungen:

| Variante | Bedeutung | Konsequenz fuer Story 4.3 |
|---|---|---|
| **A** Facilioo liefert `impower_property_id` im Ticket-DTO | Direkt-Mapping moeglich | Migration 0018 nur mit `is_archived`. Diff-Algorithmus matched gegen `Object.impower_property_id`. |
| **B** Facilioo hat eigene `propertyId` ungleich Impower-ID | Neues Feld noetig | Migration 0018 fuegt `objects.facilioo_property_id` + Index hinzu. Diff-Algorithmus matched gegen `Object.facilioo_property_id`. Initial sind alle Werte `NULL` → alle Tickets sind unmapped, bis Admin via Steckbrief-UI manuell pflegt (oder der Mirror initial automatisch matched, wenn Impower-Property-ID + Adresse uebereinstimmen — **NICHT in v1-Scope**, manuelle Pflege ist akzeptabel). |
| **C** Kein eindeutiger Mapping-Key | No-Go fuer v1 | Story 4.3 wird zurueckgelegt, Epic 4 → backlog (siehe Story 4.4 AC3-Platzhalter-UI). |

**Vorgehen vor Implementation:** `docs/integration/facilioo-spike.md` lesen → Variante identifizieren → Tasks 2.4 + 4.7 entsprechend anpassen. Wenn Variante A: Task 2.4 weglassen, in 4.7 `Object.impower_property_id` als Match-Spalte. Wenn Variante B: alles wie geschrieben.

### ETag-Persistenz — bewusst nur in-memory

Drei betrachtete Optionen:

1. **Modul-Variable `_last_etag: str | None`** (gewaehlt). Nach Container-Restart leer; erster Tick laedt voll. Container-Restarts sind selten (Elestio Auto-Deploy ~1× pro Story). 1-2 ueberzaehlige Voll-Pulls pro Tag sind tolerierbar, 1-Min-Loop tickt eh dauernd.
2. **Persistenz in `audit_log.details_json["etag"]`**. Brittel: jede Audit-Query, die nach ETag filtert, wird komplex. Audit-Schema ist nicht fuer Mirror-State da.
3. **Eigene `mirror_state`-Tabelle**. Over-Engineering fuer 1 Variable.

**Konsequenz:** AC3 testet beide Pfade (304 + 200 mit neuem ETag). Nach Container-Restart prueft der Code KEINE Persistenz — Tests koennen die Lifecycle-Eigenschaft via `_reset_module_state()`-Fixture verifizieren (siehe Task 8.3).

### Error-Budget — Fenster-Berechnung als SQL, nicht als Loop

Naive Implementation: alle Audit-Rows der letzten 24 h laden, in Python aggregieren. Bei 1440 Polls/Tag * 3 Audit-Rows/Poll = ~4320 Rows pro Fenster — noch tolerierbar, aber unnoetig.

Empfohlen: Aggregation in SQL via Postgres-`json_extract_path_text` + GROUP BY:

```sql
SELECT
  (details_json->>'run_id')::uuid AS run_id,
  bool_or(details_json->>'fetch_failed' = 'true') AS fetch_failed,
  bool_or((details_json->>'objects_failed')::int > 0) AS items_failed,
  bool_or(action = 'sync_failed') AS sync_failed_audit
FROM audit_log
WHERE action IN ('sync_started', 'sync_finished', 'sync_failed')
  AND details_json->>'job' = :job_name
  AND created_at >= :window_start
GROUP BY run_id;
```

Dann in Python `total_runs = len(rows)`, `failed_runs = sum(1 for r in rows if r.fetch_failed or r.items_failed or r.sync_failed_audit)`.

**Alternative im Code:** SQLAlchemy 2.0 Core mit `func.max()`-Aggregaten — analog `_load_recent_mirror_runs()` Stufe 1 (`app/routers/admin.py:752–760`). Pattern uebertragbar.

### Tests-Mock-Pattern fuer ETag

`tests/test_steckbrief_impower_mirror_unit.py` macht `monkeypatch` auf `_make_client` und liefert einen `httpx.AsyncClient` mit `MockTransport`. Fuer ETag testen: `MockTransport`-Handler liest `request.headers.get("If-None-Match")`, gibt entsprechend Status 200 (mit neuem `ETag`-Header) oder 304 zurueck.

```python
import httpx

def make_etag_handler(*, expect_etag=None, response_etag="new-etag", status=200, body=None):
    def handler(request):
        if expect_etag is not None:
            assert request.headers.get("If-None-Match") == expect_etag
        if status == 304:
            return httpx.Response(304, headers={"ETag": response_etag})
        return httpx.Response(
            status, json=body or {"items": [], "totalPages": 1},
            headers={"ETag": response_etag},
        )
    return handler
```

### Diff-Algorithmus — semantischer Diff, nicht volles Hash

Fuer UPDATE-Erkennung NICHT `raw_payload != db_payload` (das schlaegt bei jedem Reorder/Whitespace-Drift an). Stattdessen: `status`, `title` direkt vergleichen + ein stabiler Hash auf `raw_payload` (z. B. `hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()`), persistiert in einer optionalen Spalte ODER bei jedem Lauf neu berechnet (kein Persist-Bedarf — wenn `status`/`title` unveraendert UND `raw_payload` byte-identisch ist, wird sowieso UPDATE-No-Op gemacht). 

**Empfehlung MVP:** nur `status`, `title`, plus Reassignment auf `raw_payload`. Kein Hash, kein Persist — SQLAlchemy schreibt bei `obj.raw_payload = new_dict` immer, auch wenn semantisch identisch. Akzeptabel: 1-2 unnoetige UPDATEs pro Lauf vs. komplexere Diff-Logik. Falls Provenance-Churn relevant wird, im V2-Scope hashen.

**Was wir NICHT machen:** `write_field_human()` aus dem Steckbrief-Write-Gate aufrufen. `FaciliooTicket` hat kein `FieldProvenance` (ist eine Read-only-Mirror-Entitaet, keine `Object`-Achse). Das Write-Gate-Pattern gilt nur fuer Cluster-1/4/6/7-Felder am `Object`.

### Loop-Timeout vs. Tick-Intervall

Die `wait_for(run_facilioo_mirror(), timeout=_POLL_RUN_TIMEOUT_SECONDS)`-Konstante ist auf 5 Min. gesetzt. Das ist deutlich groesser als 60 s, aber eng genug, dass ein Endlos-Hang den Loop bei der naechsten Iteration aufweckt.

**Worst-Case-Rechnung** (Story 4.2 Backoff + Diff):
- 5xx-Storm: 5× Retry mit `(2, 5, 15, 30, 60)` = 112 s + 5× 30 s Timeout = 262 s pro Call
- Plus Pagination: ~3 Seiten * 262 s = ~13 min — **das uebersteigt den Timeout**.

Konsequenz: bei ECHTEM Storm wird der Mirror via `wait_for` nach 5 min gekillt. Das ist OK — der naechste Tick versucht erneut, und der Lock-Skip schuetzt vor Doppellauf. Wenn der Storm laenger als 5 min anhaelt, eskaliert das Error-Budget (Task 5) und der Admin sieht im UI ein Alert-Banner.

Falls 5 min in der Praxis zu eng sind: in `app/main.py`-Mirror-Scheduler ist `_MIRROR_RUN_TIMEOUT_SECONDS = 30 * 60` — fuer den Nightly-Mirror sinnvoll, fuer den 1-Min-Poll waere 30 min ueberzogen (wuerde 30 Tick-Slots blockieren). 5 min ist der Kompromiss.

### Was bewusst nicht gemacht wird (Scope-Schutz)

1. **Keine UI-Liste der Tickets in dieser Story** — das macht Story 4.4. Wir liefern nur DB-Rows + Audit-Counter + Sync-Status-Block.
2. **Kein automatisches Property-Mapping** ueber Adresse/Name — manuelle Pflege via Steckbrief-UI ist v1-Scope. Mapping-Auto-Heuristik ist v1.1.
3. **Kein DELETE auf `facilioo_tickets`-Rows** — `is_archived=True` reicht. Datenerhalt fuer Historie + Verlinkung aus Audit-Log.
4. **Kein Mehr-Process-Lock** (z. B. Postgres Advisory Lock). Der `asyncio.Lock` ist pro-Process; Multi-Worker-Setups (gunicorn `-w N`) sind v1 nicht im Scope (Elestio fahrt Single-Worker).
5. **Kein Cron-/Scheduler-Override** im Lifespan — keine APScheduler-Dependency, kein Cron-Pattern. `await asyncio.sleep(60)` ist die einfachste Loesung und reicht (siehe architecture.md:289).

### Fallstricke aus Plattform-Regeln (`docs/project-context.md`)

- **Migrations manuell schreiben**, nicht `--autogenerate` (Memory: `feedback_migrations_check_existing.md`). Vor Anlage `ls migrations/versions/` ausfuehren — real-head ist `0017` (`0017_workflow_default_strings_umlaute.py`, Stand 2026-04-30).
- **SQLAlchemy 2.0 Syntax**: `db.execute(select(...))`, kein `db.query(...)`. JSONB-Mutationen brauchen Reassignment ODER `flag_modified()` — fuer `raw_payload`-Updates also `ticket.raw_payload = new_dict`, nicht `ticket.raw_payload["status"] = ...`.
- **Async**: alle Helpers in `facilioo_mirror.py` bleiben `async def` (Mirror laeuft im Event-Loop). KEIN `asyncio.run()` im Modul — das ist nur fuer BackgroundTask-Einstiege erlaubt.
- **Imports absolut**: `from app.services.facilioo import _api_get` (nicht `from .facilioo import ...`).
- **Error-Handling**: `FaciliooError` weiterleiten; im `run_sync_job`-Wrapper wird das automatisch zu `sync_failed`-Audit (siehe `_sync_common.py:375–398`). Keine eigenen Try/Except in `_fetch_tickets()` jenseits des 304-Pfads.
- **Logging**: `print()` reicht im Container-Log; wichtige Events zusaetzlich via `audit()`. Bestehender `_logger = logging.getLogger(__name__)` ist OK.
- **Pflicht-Feld bei `FaciliooTicket.facilioo_id`**: ist `String NOT NULL UNIQUE`. Beim INSERT in Task 4.7 immer als String coercen (`str(ticket["id"])`) — Facilioo liefert manchmal int.
- **Settings**: alle neuen Felder ausschliesslich in `app/config.py`, nie via `os.getenv` in `facilioo_mirror.py`.

### Lifespan-Wiring — Reihenfolge im `app/main.py`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_default_workflow()
    _seed_default_roles()
    _seed_default_workflow_access()
    # ... (existing)

    scheduler_task = None
    if settings.impower_mirror_enabled:
        scheduler_task = asyncio.create_task(...)
    # ... (existing)

    # NEU: Story 4.3
    if settings.facilioo_mirror_enabled:
        await start_facilioo_poller()  # idempotent, baut intern den Task
    else:
        _logger.info("facilioo_mirror_poller: disabled via settings.facilioo_mirror_enabled")

    # ... (PhotoStore-Init, existing)

    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try: await scheduler_task
            except asyncio.CancelledError: pass
        # NEU:
        await stop_facilioo_poller()
```

`start_facilioo_poller()` und `stop_facilioo_poller()` sind in `facilioo_mirror.py` definiert (Tasks 4.9 + 4.11). Damit verbleibt das Task-Lifecycle-Management im Mirror-Modul, nicht in `main.py` — symmetrisch zum bestehenden Impower-Pattern, das den Task-Lifecycle in `main.py` haelt (mehr historisch gewachsen). **Bewusste Asymmetrie:** wenn Story 4.3 das saubere Muster vormacht, kann Impower-Mirror in einer Folge-Refactor-Story angeglichen werden — aber NICHT in dieser Story (Scope-Schutz).

### Setting-Dokumentation fuer Doc-Referenzen

Im Anschluss an Story 4.2 (Eintrag „Facilioo-Client" in `docs/project-context.md`) sollte ergaenzt werden:

> **Facilioo-Mirror**: 1-Min-Poll, Lifespan-Background-Task. Lock-Skip bei Doppellauf. ETag-Delta wenn Server-Support, sonst Full-Pull mit Diff (insert/update/archive). Error-Budget 10 % in 24 h triggert Audit-Alert. Admin-Status: `/admin/sync-status` (zwei Job-Bloecke).

**Im Scope dieser Story optional** — kann zusammen mit dem Story-4.2-Eintrag in einer Doc-Pflege-Runde nach 4.4 erfolgen.

## Neue Dateien

- `app/services/facilioo_mirror.py` — Mirror-Modul (Tasks 4 + 5)
- `migrations/versions/0018_facilioo_mirror_fields.py` — Schema-Erweiterung (Task 2)
- `tests/test_facilioo_mirror_unit.py` — Mirror-Tests (Task 8)

## Geaenderte Dateien

- `app/config.py` — neue Settings (Task 1)
- `app/services/facilioo.py` — `_api_get` ETag-Erweiterung (Task 3)
- `app/models/facilioo.py` — `is_archived`-Feld (Task 2.6)
- `app/models/object.py` — **falls Variante B**: `facilioo_property_id`-Feld (Task 2.7)
- `app/main.py` — Lifespan-Wiring (Task 6)
- `app/routers/admin.py` — Multi-Job-Sync-Status (Task 7.1–7.6)
- `app/templates/admin/sync_status.html` — Multi-Job-Render + Alert-Banner (Task 7.5–7.7)
- `tests/test_admin_sync_status_routes.py` — neue Test-Cases (Task 9)
- `tests/test_facilioo_unit.py` — ETag-Tests aus Task 3.5
- `output/implementation-artifacts/sprint-status.yaml` — Story 4.3 → `review` (Task 10.4)

## References

- Epic 4 Acceptance Criteria: `output/planning-artifacts/epics.md:922–946`
- Architektur Sync-Orchestrator (CD3): `output/planning-artifacts/architecture.md:284–315`
- Architektur Integrations-Boundary: `output/planning-artifacts/architecture.md:642–643`
- Architektur Lifespan-Tasks: `output/planning-artifacts/architecture.md:680`
- FR28 Facilioo-Mirror: `output/planning-artifacts/prd.md:568`
- Vorgaenger-Story 4.1 (Spike, Vorbedingung): `output/implementation-artifacts/4-1-facilioo-api-spike.md`
- Vorgaenger-Story 4.2 (Client + Hardening, Vorbedingung): `output/implementation-artifacts/4-2-facilioo-client-mit-retry-rate-gate.md`
- Spike-Output (Pflicht-Input): `docs/integration/facilioo-spike.md` (entsteht in Story 4.1)
- Sync-Job-Wrapper (1:1 wiederverwenden): `app/services/_sync_common.py` (komplett, 443 Zeilen)
- Mirror-Vorbild Impower: `app/services/steckbrief_impower_mirror.py:619–698` (`run_impower_mirror`)
- Lazy-Lock-Pattern: `app/services/steckbrief_impower_mirror.py:77–91`
- Lifespan-Scheduler-Pattern: `app/main.py:222–321`
- Sync-Status-Loader (parametrisierbar): `app/routers/admin.py:730–905`
- Sync-Status-View (zu erweitern): `app/routers/admin.py:908–958`
- Sync-Status-Template (zu erweitern): `app/templates/admin/sync_status.html`
- FaciliooTicket-Model (zu erweitern): `app/models/facilioo.py`
- Object-Model (ggf. zu erweitern): `app/models/object.py:33` (`impower_property_id`)
- FaciliooTicket-Migration (Initial): `migrations/versions/0010_steckbrief_core.py:402–432`
- Audit-Helper: `app/services/audit.py:95` (+ `KNOWN_AUDIT_ACTIONS:75–92`)
- Facilioo-Client (aus Story 4.2): `app/services/facilioo.py` (entsteht durch Rename + Hardening)
- Boundary-Test (aus Story 4.2): `tests/test_facilioo_client_boundary.py` — Allow-List enthaelt `app/services/facilioo_mirror.py` bereits
- Sync-Common-Tests (Pattern-Vorbild): `tests/test_sync_common_unit.py`
- Mirror-Tests (Pattern-Vorbild): `tests/test_steckbrief_impower_mirror_unit.py:1–894`
- Admin-Sync-Status-Tests (zu erweitern): `tests/test_admin_sync_status_routes.py:1–249`
- Plattform-Regeln (Migrations, SQLAlchemy 2.0, Async): `docs/project-context.md`
- Memory: Migrations vor Anlage checken: `~/.claude/projects/-Users-daniel-Desktop-Vibe-Coding-Dashboard-KI-Agenten/memory/feedback_migrations_check_existing.md`
- Memory: Facilioo-Pagination 1-indexed: `~/.claude/projects/-Users-daniel-Desktop-Vibe-Coding-Dashboard-KI-Agenten/memory/reference_facilioo_pagination.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

n/a — alle Tasks in einer Session abgeschlossen.

### Completion Notes List

- Variante A gewaehlt (Spike 2026-04-30): `externalId` in Facilioo = `impower_property_id` in Object. Keine neue `facilioo_property_id`-Spalte noetig — Migration 0018 nur mit `is_archived` + `facilioo_last_modified`.
- ETag nicht unterstuetzt von Facilioo (Spike-Befund) → Code-Pfad implementiert aber `_last_etag` bleibt in Prod immer `None`. Tests verifizieren den Pfad via Mock.
- Custom Orchestrator statt `run_sync_job`: per-Property-Architektur (nicht per-Ticket) + Ticket-Counter in `sync_finished` erforderten eigene Audit-Logik.
- `stale_after_seconds`-Parameter in `_load_recent_mirror_runs` ergaenzt: 10 min fuer den 1-Min-Poller (statt 60 min fuer den Nightly-Job).
- `_REQUEST_INTERVAL = 0.0` in autouse-Fixture verhindert 1-s-Rate-Gate-Delays in den Mirror-Unit-Tests.

### File List

- `app/config.py` — 6 neue Settings-Felder (facilioo_mirror_enabled, facilioo_poll_interval_seconds, facilioo_etag_enabled, facilioo_error_budget_*)
- `migrations/versions/0018_facilioo_mirror_fields.py` — NEU: `is_archived` + `facilioo_last_modified` auf `facilioo_tickets`
- `app/models/facilioo.py` — `is_archived` + `facilioo_last_modified` Felder ergaenzt
- `app/services/facilioo.py` — `_api_get` um `etag`/`return_response` Parameter + 304-Handling + Mirror-Helpers erweitert
- `app/services/facilioo_mirror.py` — NEU: vollstaendiger 1-Min-Poll-Orchestrator
- `app/main.py` — Lifespan: `start_facilioo_poller` / `stop_facilioo_poller` eingebunden
- `app/routers/admin.py` — `_FACILIOO_JOB_NAME`, `_load_error_budget_alert`, Zwei-Job-Layout, `job_name`-Routing im Trigger-Endpunkt
- `app/templates/admin/sync_status.html` — komplett neu als `{% for job in jobs %}`-Loop
- `tests/conftest.py` — `FACILIOO_MIRROR_ENABLED=false` Default ergaenzt
- `tests/test_facilioo_unit.py` — 3 ETag-Tests ergaenzt (Task 3.5)
- `tests/test_facilioo_mirror_unit.py` — NEU: 11 Unit-Tests (AC2–AC5)
- `tests/test_admin_sync_status_routes.py` — 5 neue Tests fuer Zwei-Job-Layout + Alert + Routing (AC5, AC7)

### Change Log

| Datum | Aenderung |
|---|---|
| 2026-04-30 | Implementierung komplett (Tasks 1–10), alle 41 Tests gruen, sprint-status → review |
