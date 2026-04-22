# Story 1.4: Impower-Nightly-Mirror fuer Cluster 1 + 6

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter,
ich moechte, dass Stammdaten (Cluster 1) und Finanzdaten (Cluster 6) der Objekte **nachts automatisch aus Impower gespiegelt** werden,
damit ich morgens auf der Objekt-Detailseite (Story 1.3) aktuelle Werte sehe und in Story 1.5 eine konsistente Datenbasis fuer Live-Saldo + Ruecklage-Sparkline vorliegt — alles ohne manuellen Aufwand, ohne User-Edits zu ueberschreiben, und ohne dass einzelne Impower-Fehler die 49 anderen Objekte blocken.

Diese Story legt die **Fundamente der Sync-Orchestrator-Schicht** (CD3): neuer Mirror-Service, gemeinsames `_sync_common`-Muster, im Lifespan registrierter Scheduler-Task, Admin-Statusseite + Manual-Trigger — und erweitert das `Object`-Datenmodell um die Cluster-6-Finanzfelder, die Story 1.5 konsumieren wird. Alle Mirror-Writes laufen durch das in Story 1.2 gebaute Write-Gate (`write_field_human` mit `source="impower_mirror"`), dessen Mirror-Guard bereits strukturell verhindert, dass User-Edits (Provenance zuletzt `user_edit`/`ai_suggestion`) ueberschrieben werden.

## Acceptance Criteria

**AC1 — Lifespan startet BackgroundTask, der um 02:30 Uhr lokaler Zeit taeglich den Mirror-Job ausloest**
**Given** die App startet (FastAPI-Lifespan-`__aenter__` laeuft durch)
**When** ich die Routen-Liste und laufende Tasks inspiziere
**Then** laeuft **genau ein** `asyncio.Task` mit dem Namen `steckbrief_impower_mirror_scheduler` (via `asyncio.create_task(..., name=...)` angelegt)
**And** die Scheduler-Loop ruft `next_daily_run_at(now, hour=2, minute=30, tz=ZoneInfo("Europe/Berlin"))` und schlaeft genau bis zu diesem Zeitpunkt (unit-test-bar ohne echtes Warten ueber `monkeypatch` von `asyncio.sleep` + Time-Provider-Injection)
**And** beim App-Shutdown (`__aexit__`) wird der Task sauber `cancel()`-d und `await`-d — der Event-Loop schlaegt in den Tests **keinen** `Task was destroyed but it is pending`-Warning.

**AC2 — Cluster-1-Felder werden aus Impower gemirrored, Provenance + Audit entstehen**
**Given** ein `Object` mit `impower_property_id="12345"` existiert in der DB und Impower liefert zu Property 12345 die Felder `name="Hausstrasse 1"`, `addressStreet="Hausstrasse 1"`, `addressZip="22769"`, `addressCity="Hamburg"`, `weg_nr="HAM61"` (Mapping siehe Dev Notes)
**When** `await run_impower_mirror(db_factory=SessionLocal)` einmal durchlaeuft
**Then** sind auf dem DB-Object die Felder `full_address="Hausstrasse 1, 22769 Hamburg"` (zusammengebaut aus street + zip + city) und `weg_nr="HAM61"` geschrieben
**And** fuer **jedes** dieser geschriebenen Felder existiert eine `FieldProvenance`-Zeile mit `entity_type="object"`, `entity_id=obj.id`, `source="impower_mirror"`, `source_ref="12345"`, `user_id=None`. Beim **Erstwrite auf leere Felder** ist zu beachten: wenn das alte Object-Feld bereits denselben Wert traegt (`old == new`), fired der No-Op-Guard (`skip_reason="noop_unchanged"`, keine Provenance) — das ist Soll. Fuer neue Objekte/Felder mit echten Impower-Daten entsteht die Row normal.
**And** es existiert genau ein `AuditLog`-Eintrag mit `action="sync_started"` und einer mit `action="sync_finished"`, beide mit `entity_type="sync_run"`, `details_json` enthaelt `{"job":"steckbrief_impower_mirror","objects_total":<n>,"fields_updated":<k>,"objects_failed":<f>}` — die Counter sind konsistent mit der tatsaechlichen Write-Anzahl.

**AC3 — Cluster-6-Felder werden gemirrored (Ruecklage, Zielwert, Wirtschaftsplan-Status, SEPA-Mandat-Refs)**
**Given** dasselbe `Object` + Impower liefert zu Property 12345 die Cluster-6-Daten `reserveCurrent=45000.00`, `reserveTargetMonthly=500.00`, `economicPlanStatus="RESOLVED"` und 2 aktive Mandate (via `GET /services/pmp-accounting/api/v1/direct-debit-mandate?propertyId=12345` — Filter auf `state="BOOKED"`)
**When** derselbe Mirror-Lauf durch die Cluster-6-Phase geht
**Then** sind auf dem Object gesetzt: `reserve_current=Decimal("45000.00")`, `reserve_target=Decimal("500.00")`, `wirtschaftsplan_status="beschlossen"` (Mapping `RESOLVED→beschlossen`, `IN_PREPARATION→in_vorbereitung`, sonst Roh-String lowercase)
**And** `sepa_mandate_refs=[{"mandate_id":<id>,"bank_account_id":<bid>,"state":"BOOKED"}, {...}]` als JSONB-Liste (stabil sortiert nach `mandate_id`, damit der No-Op-Check `_latest_provenance`-Gleichheit korrekt greift)
**And** fuer jedes der 4 Felder entsteht eine `FieldProvenance`-Zeile mit `source="impower_mirror"`, `source_ref="12345"`
**And** `last_known_balance` wird in dieser Story **nicht** gemirrored — das ist Story 1.5 (Live-Pull). Wenn Impower-Property-Daten zufaellig eine `balance` enthalten, bleibt sie **ignoriert**.

**AC4 — Eigentuemer-Reconcile aus Impower `OWNER`-Contracts (Cluster 1)**
**Given** Impower liefert via `load_owner_contracts()` fuer Property 12345 zwei Eigentuemer (Contact-IDs 701 / 702) mit `contact.displayName` + `votingShare` (Bruchanteil oder Prozent je nach Contract-Feld, siehe Dev Notes)
**When** der Mirror-Lauf die Eigentuemer-Phase durchlaeuft
**Then** existieren in der `eigentuemer`-Tabelle fuer dieses Object **zwei** Rows mit `impower_contact_id="701"` / `"702"`, `name=<displayName>`, `voting_stake_json={"percent": <fraction*100 als float>}` (oder `{"fraction": <raw>}` falls Impower direkt Prozent liefert — Konvention siehe Dev Notes)
**And** Felder an **bestehenden** Eigentuemer-Rows (Match ueber `impower_contact_id`) werden via `write_field_human(eig, field="name"|"voting_stake_json", ..., source="impower_mirror", source_ref="701")` geschrieben — dadurch greift der Mirror-Guard auch hier (ein User-Edit an `name` wird nicht vom Mirror ueberschrieben)
**And** **neue** Eigentuemer-Rows (kein Match) werden direkt per `db.add(Eigentuemer(object_id=..., name="", impower_contact_id=...))` + `db.flush()` mit **Platzhalter-`name=""`** angelegt (Constructor-kwargs werden vom Write-Gate-Coverage-Scanner aus `test_write_gate_coverage.py` nicht erfasst — er scannt nur post-Instanziierungs-Zuweisungen via `<var>.<attr> = ...`); unmittelbar danach wird pro Feld `name` und `voting_stake_json` via `write_field_human` der echte Wert geschrieben. Der Platzhalter `name=""` ist erforderlich, damit der No-Op-Guard (`noop_unchanged`) beim Erstwrite nicht zuschlaegt — siehe Task 4.5 fuer das Code-Muster
**And** Eigentuemer-Rows, deren `impower_contact_id` **nicht mehr** im Impower-Set vorkommt, werden in dieser Story **NICHT automatisch geloescht** (Datenerhalt-Semantik v1; Loesch-Mechanik ist v1.1-Scope). Ein `AuditLog`-Eintrag `action="sync_started"` mit `details_json.eigentuemer_orphans=[<id>,...]` listet sie aber auf, damit der Admin sie in Story 1.4 Admin-UI sehen kann.

**AC5 — User-Edit gewinnt gegen Mirror (Write-Gate-Mirror-Guard ist strukturell)**
**Given** ein `Object` mit `full_address="Altstrasse 2"` und einer existierenden `FieldProvenance`-Row fuer `full_address` mit `source="user_edit"`, `created_at=<letzte Nacht>`
**When** der Mirror-Lauf aufruft `write_field_human(obj, field="full_address", value="Neustrasse 3", source="impower_mirror", user=None, source_ref="12345")`
**Then** liefert `WriteResult` `written=False, skipped=True, skip_reason="user_edit_newer"` — das Feld bleibt `"Altstrasse 2"`, es entsteht **keine** neue Provenance-Row, **kein** `sync_failed`-Audit (das ist kein Fehler, sondern Soll-Verhalten)
**And** der Skip wird im Mirror-Zusammenfassungs-Audit (`sync_finished.details_json.skipped_user_edit_newer=<n>`) gezaehlt — beobachtbar fuer die Admin-UI.

**AC6 — Einzel-Objekt-Fehler brechen den Job nicht ab**
**Given** 50 Objekte in der DB, Impower wirft bei Property 12345 einen `503 Service Unavailable` (nach allen Retries des Impower-Clients), die anderen 49 Properties kommen sauber zurueck
**When** der Mirror-Lauf durchlaeuft
**Then** laufen die 49 Objekte erfolgreich durch (Felder + Provenance + keine Teilfehler)
**And** fuer das eine gescheiterte Objekt existiert **genau ein** `AuditLog`-Eintrag mit `action="sync_failed"`, `entity_type="object"`, `entity_id=<obj.id>`, `details_json={"impower_property_id":"12345","phase":"cluster_6"|"cluster_1"|"eigentuemer","error":"<sanitisierte_fehlermeldung>"}`
**And** die Fehlermeldung ist via `strip_html_error`-Helper in `_sync_common.py` entschaerft (kein HTML-Markup, max. 500 Zeichen — falls Impower HTML-Error-Pages zurueckliefert)
**And** der finale `sync_finished`-Eintrag enthaelt `objects_failed=1, objects_ok=49`
**And** der Job endet mit Status `ok` (nicht `error`) — die Policy ist "teilweise erfolgreich reicht, der naechste Lauf holt das eine Objekt nach".

Zusaetzlich zur Fehler-Semantik: **DB-Objekte ohne Match im Impower-Snapshot** (Impower kennt die `impower_property_id` nicht mehr — z. B. geloescht oder getyppt) sind **kein Fehler**. Der Mirror zaehlt sie in `sync_finished.details_json.objects_skipped_no_impower_data=<n>` und **nicht** in `objects_failed`. Objekte **ohne `impower_property_id`** werden genauso separat in `objects_skipped_no_impower_id=<n>` gezaehlt. Beide Skip-Kategorien sind in Admin-UI sichtbar (AC9), loesen aber keinen roten Status aus.

**AC7 — Idempotenz: doppelter Trigger erzeugt keine Duplikate**
**Given** der Mirror-Lauf laeuft bereits (asyncio.Lock ist acquired) und ein zweiter Trigger kommt via Manual-Trigger-Endpoint (AC9) rein
**When** der zweite `run_impower_mirror()`-Aufruf startet
**Then** kehrt der zweite Aufruf sofort mit `MirrorRunResult(skipped=True, reason="already_running")` zurueck, **ohne** Impower-Calls, **ohne** DB-Writes
**And** es entsteht **genau ein** `AuditLog`-Eintrag `action="sync_started"` mit `details_json.skipped=true, skip_reason="already_running"` — **kein** `sync_finished` fuer diesen skipped-Run (der erste Lauf besitzt den `run_id` fuer Start+Finish; der Skip ist ein eigener `run_id` ohne Pair). Die AC9-Status-Rekonstruktion muss das tolerieren (fehlendes `sync_finished` → Status `skipped`, Dauer `None`)
**And** der erste Lauf laeuft unveraendert zu Ende.

Zusaetzlich fuer den Normalfall (zwei Laeufe hintereinander auf demselben Object ohne neue Impower-Daten):
**Given** Mirror-Lauf A ist durchgelaufen und hat `full_address="Hausstrasse 1, 22769 Hamburg"` gesetzt; Mirror-Lauf B startet 24h spaeter mit identischen Impower-Daten
**When** Lauf B durchlaeuft
**Then** liefert jeder `write_field_human`-Call `WriteResult(written=False, skipped=True, skip_reason="noop_unchanged")` zurueck (bestehende Short-Circuit-Logik des Write-Gates)
**And** es entstehen **keine** neuen FieldProvenance-Rows (sonst wuerde die Historie verrauscht; ist fuer Story 1.5-Sparkline kritisch)
**And** `sync_finished.details_json.fields_updated=0` ist konsistent.

**AC8 — Datenmodell-Erweiterung + Migration 0012 ist vorwaerts **und** rueckwaerts lauffaehig**
**Given** wir sind auf `alembic current == 0011` (Repo-Konvention: kurze numerische Revision-IDs wie `"0010"`, `"0011"` — NICHT `0011_steckbrief_governance`)
**When** `alembic upgrade head` laeuft
**Then** wird Migration `0012_steckbrief_finance_mirror_fields` (Datei-Name) mit `revision = "0012"` angewendet und folgende Spalten existieren:
- `objects.reserve_current NUMERIC(12,2) NULL`
- `objects.reserve_target NUMERIC(12,2) NULL`
- `objects.wirtschaftsplan_status VARCHAR NULL`
- `objects.sepa_mandate_refs JSONB NOT NULL DEFAULT '[]'`
- `eigentuemer.impower_contact_id VARCHAR NULL` mit Index `ix_eigentuemer_impower_contact_id (object_id, impower_contact_id)` (composite, damit der Reconcile-Match per-Object indexiert ist)

**And** `alembic downgrade -1` entfernt diese Spalten ohne Datentyp-Fehler; Alembic wirft keinen `ModuleNotFoundError` (`down_revision = "0011"` — verifiziert via `grep 'revision: str' migrations/versions/0011_*.py`, nicht blind aus CLAUDE.md uebernehmen)
**And** Write-Gate akzeptiert die neuen Feld-Namen (`reserve_current`, `reserve_target`, `wirtschaftsplan_status`, `sepa_mandate_refs`, `impower_contact_id`) automatisch via `setattr` — **kein** Touch auf `steckbrief_write_gate.py` noetig
**And** das JSONB-Default `[]` + Reassignment-Disziplin (`obj.sepa_mandate_refs = [...]`) verhindert die in-place-Mutation-Falle (siehe `docs/project-context.md` "JSONB-Fallen").

**AC9 — Admin-Statusseite `/admin/sync-status` + Manual-Trigger + Sidebar-Link**
**Given** ich bin als User mit `sync:admin` eingeloggt
**When** ich `GET /admin/sync-status` aufrufe
**Then** sehe ich eine Uebersicht mit: (a) letzter Lauf mit Status (ok/partial/failed/skipped), Start-Timestamp (Europe/Berlin formatiert), Dauer (Sekunden — bei skipped-Run `None`/„–"), Counter (`objects_ok`, `objects_failed`, `fields_updated`, `skipped_user_edit_newer`, `objects_skipped_no_impower_id`, `objects_skipped_no_impower_data`), (b) naechster geplanter Lauf als absolutes Datum+Uhrzeit, (c) Liste der fehlgeschlagenen Objekte des letzten Laufs (Object-Link, `impower_property_id`, Phase, Fehlermeldung), (d) Link "Jetzt ausfuehren" (HTMX-`hx-post` an `/admin/sync-status/run`)
**And** die Daten werden aus `AuditLog` rekonstruiert. Die 50er-LIMIT-Heuristik schneidet grosse Laeufe mittendurch ab (ein Lauf produziert `sync_started` + `sync_finished` + bis zu 50 `sync_failed` — das sind >50 Rows). Besser: **Sub-Query auf die letzten 10 distinct `run_id`**-Werte aus `audit_log WHERE entity_type='sync_run' AND action IN ('sync_started','sync_finished','sync_failed')` (per `details_json->>'run_id'`), dann alle Audit-Rows zu diesen run_ids laden und in Python zu Run-Tupeln gruppieren. Fuer Runs mit **fehlendem `sync_finished`** (skipped-Case, AC7) zeigt die UI Status `skipped`, Dauer `None`, Counter aus `sync_started.details_json` — nicht NPE werfen
**And** `POST /admin/sync-status/run` laeuft permission-gated (`require_permission("sync:admin")`), legt einen `BackgroundTask` an (`background_tasks.add_task(_trigger_mirror_once)`) und redirected via 303 zurueck auf `/admin/sync-status` mit Flash-Info "Lauf gestartet — Status aktualisiert sich beim naechsten Reload"
**And** `GET /admin/sync-status` + `POST .../run` liefern ohne `sync:admin` eine 403 (fuer `user`-Default-Rolle) bzw. 302 fuer Anon
**And** die Admin-Landing-Seite (`/admin`) bekommt in der Karten-/Link-Uebersicht einen neuen Eintrag "Sync-Status" mit kurzer Beschreibung — konsistent zu den bestehenden Admin-Links (User, Rollen, Logs).

**AC10 — Tests + Regressionslauf + Write-Gate-Coverage-Scanner bleibt gruen**
**Given** Story 1.4 fuegt Code in `app/services/steckbrief_impower_mirror.py`, `app/services/_sync_common.py`, `app/routers/admin.py`, `app/models/object.py`, `app/models/person.py`, `migrations/versions/0012_*.py` und Templates hinzu
**When** `pytest -x` laeuft
**Then** sind alle in Task 7 definierten neuen Tests gruen (Mirror-Unit, Sync-Common-Unit, Scheduler-Unit, Admin-Routes-Smoke, Migration-Roundtrip, End-to-End mit 3 Objekten + 1 Fehler)
**And** der bestehende Regressionslauf (>=272 Tests aus Story 1.3 + 4 Luecken-Tests aus 1.1/1.2) bleibt **vollstaendig gruen** — keine Anpassung bestehender Tests erlaubt, ausser die neuen Migrationen verlangen eine bulk_fixture-Aktualisierung (dann additiv)
**And** `tests/test_write_gate_coverage.py` (Meta-Scanner aus Story 1.2) bleibt gruen — die neuen Mirror-Writes laufen ALLE durch `write_field_human`, es gibt keine direkten `entity.field = value`-Zuweisungen auf CD1-Entitaeten im Mirror-Service ausser strukturelle Row-Creation fuer neue Eigentuemer (whitelisted)
**And** `anthropic`- und `httpx`-Mocks werden konsequent verwendet — **kein** echter Impower-Call in Tests (Memory: "Impower hat keinen Sandbox-Tenant, echte Calls sind Prod-Writes").

## Tasks / Subtasks

- [x] **Task 1 — Datenmodell-Erweiterung + Migration 0012** (AC3, AC4, AC8)
  - [x] 1.1 **Vor Anlage** der Migration `ls migrations/versions/` + `grep "^revision" migrations/versions/0011_*.py` ausfuehren — Dev-Agent MUSS die tatsaechlich neueste Revision-ID als `down_revision` nehmen (Memory `feedback_migrations_check_existing`). **Repo-Konvention: kurze numerische IDs** (`"0010"`, `"0011"`, …). Beim Verifikations-Stand: `revision: str = "0011"`. **NICHT** den Datei-Namen-Suffix (`0011_steckbrief_governance`) als Revision-ID uebernehmen — das bricht `alembic upgrade head`.
  - [x] 1.2 Neue Datei `migrations/versions/0012_steckbrief_finance_mirror_fields.py`. `revision: str = "0012"`, `down_revision: Union[str, None] = "0011"` (konform mit allen bestehenden Migrationen 0001–0011), `branch_labels = None`, `depends_on = None`.
  - [x] 1.3 `upgrade()` fuegt vier Spalten zu `objects` hinzu: `reserve_current NUMERIC(12,2) NULL`, `reserve_target NUMERIC(12,2) NULL`, `wirtschaftsplan_status VARCHAR NULL`, `sepa_mandate_refs JSONB NOT NULL SERVER_DEFAULT '[]'`. Zu `eigentuemer`: `impower_contact_id VARCHAR NULL`. Index `ix_eigentuemer_impower_contact` auf `(object_id, impower_contact_id)` (composite, NICHT unique — Impower kann theoretisch einen Contact zweimal als Owner fuehren, wir wollen keinen Insert-Abbruch).
  - [x] 1.4 `downgrade()` loescht Spalten + Index in umgekehrter Reihenfolge. Downgrade muss OHNE DB-Fehler laufen (Test in Task 7).
  - [x] 1.5 `app/models/object.py` erweitern: `Object`-Klasse bekommt 4 neue Mapped-Spalten mit exakt denselben Typ-Signaturen wie `last_known_balance` (fuer `reserve_current`/`reserve_target`: `Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)`; `wirtschaftsplan_status: Mapped[str | None] = mapped_column(String, nullable=True)`; `sepa_mandate_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")`).
  - [x] 1.6 `app/models/person.py` erweitern: `Eigentuemer.impower_contact_id: Mapped[str | None] = mapped_column(String, nullable=True, index=False)` (Index liegt composite in der Migration).
  - [x] 1.7 **NICHT** `app/services/steckbrief_write_gate.py` anfassen — das Gate schreibt via `setattr`, neue Felder sind automatisch abgedeckt. Auch `_ENCRYPTED_FIELDS` nicht erweitern (Cluster-6-Finanzfelder sind NICHT encrypted; Story 1.7 behandelt entry_codes).

- [x] **Task 2 — `_sync_common.py`: run_sync_job + strip_html_error + backoff + next_daily_run_at** (AC1, AC6)
  - [x] 2.1 Neue Datei `app/services/_sync_common.py`. Modul-Dokstring verweist kurz auf `architecture.md#CD3`.
  - [x] 2.2 Dataclass `SyncRunResult`: `job_name: str`, `started_at: datetime`, `finished_at: datetime`, `items_ok: int`, `items_failed: int`, `items_skipped_no_external_id: int` (Object ohne Mapping-ID), `items_skipped_no_external_data: int` (ID bekannt, aber im externen System nicht mehr vorhanden), `fields_updated: int`, `skipped_user_edit_newer: int`, `errors: list[dict]` (`{item_id, phase, error}`), `skipped: bool = False` (gesamter Job geskipped wegen `already_running`), `skip_reason: str | None = None`, `run_id: uuid.UUID`.
  - [x] 2.3 Funktion `strip_html_error(resp_text: str | None, limit: int = 500) -> str` — Entfernt HTML-Tags (`re.sub(r"<[^>]+>", "", s)`), collapst Whitespace, schneidet auf `limit`. None → `""`. Wird fuer `sync_failed.details_json.error` genutzt.
  - [x] 2.4 Funktion `next_daily_run_at(now: datetime, *, hour: int, minute: int, tz: ZoneInfo) -> datetime` — rechnet den naechsten Run-Zeitpunkt aus: heute `hour:minute` in `tz`, falls schon vorbei → morgen. Rueckgabe als **timezone-aware** datetime in `tz`. Test: `now=Mi 14:00` → `Do 02:30`; `now=Di 02:00` → `Di 02:30`; `now=Di 02:30:00.001` → `Mi 02:30`.
  - [x] 2.5 Async-Funktion `run_sync_job(*, job_name: str, fetch_items: Callable[[], Awaitable[list[T]]], reconcile_item: Callable[[T, Session], Awaitable[ReconcileStats]], db_factory: Callable[[], Session], lock: asyncio.Lock) -> SyncRunResult`. Ablauf: (a) `lock.acquire(non_blocking)` mit `lock.locked()`-Check — wenn bereits locked → `SyncRunResult(skipped=True, skip_reason="already_running")` + `sync_started`-Audit mit `details_json.skipped=True`. (b) `sync_started`-Audit. (c) `fetch_items()` — Exception → `sync_failed` fuer den Job (entity_type="sync_run"), lock release, return result mit `items_failed=1`. (d) Pro Item **eigene DB-Session** (`db_factory()`), `reconcile_item(item, db)` in try/except — bei Exception `sync_failed`-Audit pro Item + continue. (e) Nach allen Items `sync_finished`-Audit mit Counters. (f) `lock.release()` im `finally`.
  - [x] 2.6 Dataclass `ReconcileStats`: `fields_updated: int = 0`, `skipped_user_edit_newer: int = 0`, `eigentuemer_inserted: int = 0`, `eigentuemer_updated: int = 0`, `eigentuemer_orphans: list[str] = []`. Wird aus `reconcile_item` zurueckgegeben und in `SyncRunResult` aggregiert.
  - [x] 2.7 Function `_audit_sync(db, *, action, run_id, job_name, details)` — interner Helper, ruft `audit()` mit `entity_type="sync_run"`, `entity_id=<run_id>`, `user=None`, `user_email="system"`, `details={"job": job_name, "run_id": str(run_id), **details}`. Commit macht `run_sync_job` (ein Commit pro Item-Session + ein finaler Commit auf eigener Session fuer `sync_started`/`sync_finished`).
  - [x] 2.8 Keine `Impower`-Kenntnisse in `_sync_common.py` — Modul ist generisch (wird in Story 1.4 Facilioo-Mirror wiederverwendet).

- [x] **Task 3 — `steckbrief_impower_mirror.py`: Service-Kern** (AC2, AC3, AC4, AC5, AC6, AC7)
  - [x] 3.1 Neue Datei `app/services/steckbrief_impower_mirror.py`. **Lock lazy konstruieren**, nicht als Modul-Globale: `_mirror_lock: asyncio.Lock | None = None` + `def _get_mirror_lock() -> asyncio.Lock: global _mirror_lock; if _mirror_lock is None: _mirror_lock = asyncio.Lock(); return _mirror_lock`. Grund: `asyncio.Lock()` bindet an den Event-Loop, der beim Import aktiv ist. pytest-asyncio mit `asyncio_mode="auto"` dreht pro Test einen eigenen Loop — ein Modul-global angelegtes Lock wirft `RuntimeError: <Lock ...> is bound to a different event loop` beim zweiten Test. Der Lazy-Getter loest das Lock beim ersten `acquire()` im richtigen Loop. Fuer Tests zusaetzlich Reset-Fixture (`_mirror_lock = None` in `conftest.py`-autouse) — Details siehe Task 7.2.
  - [x] 3.2 Funktion `_build_full_address(property_dict: dict) -> str | None`: baut `"{street}, {zip} {city}"` aus `addressStreet`/`addressZip`/`addressCity`. Falls street fehlt → None (Mirror-Guard skippt auf None ueber write-gate-No-Op).
  - [x] 3.3 Funktion `_map_wirtschaftsplan_status(raw: str | None) -> str | None`: `RESOLVED→beschlossen`, `IN_PREPARATION→in_vorbereitung`, `DRAFT→entwurf`, sonst `str.lower(raw)` bzw. None. Mapping-Dict als Modul-Konstante, damit Story 1.5 den Display-Wert im Template sichten kann.
  - [x] 3.4 Funktion `_normalize_mandate_refs(mandates: list[dict]) -> list[dict]`: Filter auf `state == "BOOKED"`, Projektion auf Dict mit **fester Key-Reihenfolge** (Python-Dicts sind insertion-ordered — immer `{"mandate_id": ..., "bank_account_id": ..., "state": "BOOKED"}` in dieser Reihenfolge konstruieren), **stabile Sortierung nach `mandate_id` asc** (`sorted(..., key=lambda m: m["mandate_id"])`). Grund: `write_field_human` macht einen Deep-Equality-Vergleich mit dem alten Listen-Wert — ohne Stable-Sort + stabile Dict-Keys entstehen bei jedem Lauf FieldProvenance-Rows wegen Reordering-Rauschen. Listen-Gleichheit in Python ist ordnungs-sensitiv; Dict-Gleichheit nicht, aber der JSONB-Roundtrip serialisiert Python-Dicts der Reihe nach — mit identischer Insertion-Order bleibt die ServerSeitigen JSON-Repr identisch.
  - [x] 3.5 Async-Funktion `_fetch_impower_snapshot(client: httpx.AsyncClient) -> dict[str, dict]`: Ein Aufruf `_get_all_paged(client, "/v2/properties")` + Map `property_id_str → property_dict`. Zusaetzlich pro Property ein paralleler Fetch der Mandate: **NICHT** parallel fuer alle 50 Properties (Rate-Gate 0.12 s), sondern seriell mit `_api_get(client, f"/services/pmp-accounting/api/v1/direct-debit-mandate?propertyId={pid}")`. Ergebnis-Dict: `{pid: {"property": dict, "mandates": list}}`. Bei Einzel-Fehler (503 o. ae.) wirft der Impower-Client `ImpowerError` → propagieren; `run_sync_job` katcht pro Item.
  - [x] 3.6 Async-Funktion `_fetch_owner_contracts_by_property(client: httpx.AsyncClient) -> dict[str, list[dict]]`: einmaliger `_get_all_paged(client, "/v2/contracts", {"type": "OWNER"})` + Gruppierung nach `contract.propertyId`. Jeder Eintrag enthaelt `contactId` + `contactDisplayName` + `votingShare` (Felder-Namen gem. Swagger verifizieren — wenn abweichend, dann Mapping-Layer mit Fallbacks; Dev Notes nennen die drei Kandidaten).
  - [x] 3.7 Async-Funktion `_reconcile_object(obj_id: UUID, impower_data: dict | None, owner_data: list[dict], db: Session) -> ReconcileStats`: (a) Object laden. (b) Wenn `obj.impower_property_id is None`: `stats.items_skipped_no_external_id=1`, kein Write, return. (c) Wenn `impower_data is None` (Object hat ID, aber Impower liefert dazu keine Property): `stats.items_skipped_no_external_data=1`, kein Write, return. (d) write-gate-Calls fuer `full_address`, `weg_nr`, `reserve_current`, `reserve_target`, `wirtschaftsplan_status`, `sepa_mandate_refs` — jeweils `source="impower_mirror"`, `source_ref=<impower_property_id>`, `user=None`; Counter je nach `WriteResult.written`/`skipped_user_edit_newer`. (e) Eigentuemer-Reconcile (Task 4). (f) `db.commit()` genau einmal am Ende. (g) Rueckgabe `ReconcileStats`.
  - [x] 3.8 Async-Funktion `run_impower_mirror(db_factory=SessionLocal, http_client_factory=_make_client) -> SyncRunResult`: Wrapper um `run_sync_job(job_name="steckbrief_impower_mirror", fetch_items=_load_objects_with_impower_id, reconcile_item=<partial(_reconcile_object, impower_snapshot, owner_snapshot)>, db_factory=db_factory, lock=_mirror_lock)`. **Lock-Acquire** BEVOR Impower geladen wird — sonst doppelter Netzwerk-Roundtrip bei Dauerlauf-Ueberlappung.
  - [x] 3.9 **Kein** separater Sync-Einstieg noetig: FastAPI `BackgroundTasks.add_task(...)` akzeptiert `async`-Callables direkt (sie werden auf dem Event-Loop ausgefuehrt) und sync-Callables via Threadpool. Admin-Trigger (Task 6.4) registriert deshalb direkt `background_tasks.add_task(run_impower_mirror)` — spart den Sync-Shim. Lifespan-Scheduler ruft `await run_impower_mirror()` direkt (er laeuft bereits im Event-Loop). Falls doch ein sync-Einstieg entsteht (z. B. fuer CLI-Debug), minimal `def run_impower_mirror_sync(): asyncio.run(run_impower_mirror())` — aber im MVP nicht eingebaut.

- [x] **Task 4 — Eigentuemer-Reconcile-Logik in `steckbrief_impower_mirror.py`** (AC4)
  - [x] 4.1 Funktion `_reconcile_eigentuemer(db, obj_id: UUID, impower_property_id: str, owners: list[dict], stats: ReconcileStats) -> None` — operiert innerhalb der Object-Session aus 3.7.
  - [x] 4.2 Laden bestehender Eigentuemer: `db.execute(select(Eigentuemer).where(Eigentuemer.object_id == obj_id)).scalars().all()`. Index-Map `by_contact_id = {e.impower_contact_id: e for e in existing if e.impower_contact_id}`.
  - [x] 4.3 Voting-Stake-Normalisierung `_normalize_voting_stake(raw: Any) -> dict`: wenn raw ein `float` zwischen 0 und 1 → `{"percent": raw*100}`. Wenn `int/float > 1` → `{"percent": raw}` (Annahme: schon Prozent). Wenn `None` → `{}`. Schluessel stabil halten, damit No-Op-Check in write-gate greift.
  - [x] 4.4 Pro Impower-Owner: Match ueber `impower_contact_id` (String!). Wenn **vorhanden**: `write_field_human(eig, field="name", value=displayName, source="impower_mirror", source_ref=contact_id, user=None)` + dasselbe fuer `voting_stake_json`. `stats.eigentuemer_updated += <Anzahl tatsaechlich geschriebener Felder>` — `WriteResult.written=True` zaehlt, `skipped=True` nicht.
  - [x] 4.5 Wenn **nicht vorhanden**: Row **mit Platzhalter-Werten** bootstrappen, damit `write_field_human` im naechsten Schritt `old != new` sieht und den No-Op-Guard NICHT ausloest. Hintergrund: `steckbrief_write_gate.py:250-266` skippt bei `old == value` UND `last is None` mit `skip_reason="noop_unchanged"` (bewusst, damit Mirror-Laeufe ohne Datenaenderung keine Provenance-Rows produzieren). Erstwrite auf frisch-erzeugte Rows ist davon genauso betroffen — deshalb Placeholder. Konkret:
    ```python
    new = Eigentuemer(
        object_id=obj_id,
        name="",                 # Placeholder: NOT NULL erfuellt, write_field_human schreibt den echten Wert
        impower_contact_id=contact_id,
        # voting_stake_json uebernimmt server_default='{}' aus der DB — nicht setzen
    )
    db.add(new)
    db.flush()                   # new.id gesetzt
    write_field_human(db, entity=new, field="name", value=displayName, source="impower_mirror", source_ref=contact_id, user=None)
    write_field_human(db, entity=new, field="voting_stake_json", value=_normalize_voting_stake(raw), source="impower_mirror", source_ref=contact_id, user=None)
    ```
    Damit entsteht pro Feld **genau eine** Provenance-Row mit `old={"":""}`/`{}` → `new=<echter Wert>`, und AC4 („unmittelbar danach wird pro Feld eine Provenance-Row nachgezogen") ist erfuellt. Wenn `_normalize_voting_stake(raw)` den leeren Default `{}` zurueckgibt (kein Voting-Share in Impower), greift der No-Op-Guard — das ist gewollt (kein Rauschen fuer leere Felder). `stats.eigentuemer_inserted += 1`.
  - [x] 4.6 Bestehende Eigentuemer ohne Match im Impower-Set → NICHT loeschen. `orphan_ids = [str(e.impower_contact_id or e.id) for e in existing if e.impower_contact_id and e.impower_contact_id not in impower_contact_ids]`. `stats.eigentuemer_orphans.extend(orphan_ids)`. Die Liste geht in das `sync_started`-Audit der Mirror-Zusammenfassung (AC4).
  - [x] 4.7 **Rationale im Service-Code dokumentieren** (kurzes Modul-Kommentar, kein Docstring-Roman): "Orphan-Owner werden in v1 nicht auto-geloescht. Grund: Datenverlust-Risiko bei Impower-Ausfall, der zeitweise leere Listen zurueckliefert." Das ist das **Warum**, das nicht aus dem Code ablesbar ist.

- [x] **Task 5 — Scheduler-Integration in `app/main.py`** (AC1)
  - [x] 5.1 `app/main.py` Lifespan erweitern. Nach den bestehenden Seed-Calls ein `scheduler_task = asyncio.create_task(_scheduler_loop(), name="steckbrief_impower_mirror_scheduler")`. Vor `yield` stellen; im `finally`/nach `yield`: `scheduler_task.cancel(); try: await scheduler_task except asyncio.CancelledError: pass`.
  - [x] 5.2 Funktion `_scheduler_loop() -> None` (async, lokal in `app/main.py` oder in `steckbrief_impower_mirror.py` als `mirror_scheduler_loop()`): Endlosschleife `while True: next_run = next_daily_run_at(now=datetime.now(tz), hour=2, minute=30, tz=BERLIN_TZ); await asyncio.sleep((next_run - datetime.now(tz)).total_seconds()); try: await run_impower_mirror() except Exception as exc: print(f"[mirror_scheduler] run failed: {exc}")`.
  - [x] 5.3 **Keine** externe Scheduler-Dependency (APScheduler o.ae.) hinzufuegen — Architektur-Entscheidung CD3 verlangt ausdruecklich "keine neue Dependency".
  - [x] 5.4 Env-Flag als Safety-Net: `settings.impower_mirror_enabled: bool = True` (in `app/config.py` neu). Wenn `False` → Scheduler-Loop wird gar nicht gestartet (Log: `[mirror_scheduler] disabled via settings`). Hintergrund: Fuer Tests + Dev-Lokalstart soll der Nightly-Job nicht blind echte Impower-Calls ausloesen. In Tests ist das Default-Verhalten trotzdem "kein echter Impower-Call", weil Tests den Lifespan via `TestClient` zwar starten, die `impower.py`-Calls aber ueber `monkeypatch`/`respx` gemockt sind — trotzdem ist das Flag zusaetzlicher Gurt.
  - [x] 5.5 Fuer Prod **true** (default). Env-Var `IMPOWER_MIRROR_ENABLED=true` dokumentiert in `.env.op` als Platzhalter — kein Neueintrag ins 1Password noetig.

- [x] **Task 6 — Admin-UI: `/admin/sync-status` + Manual-Trigger + Landing-Link** (AC9)
  - [x] 6.1 `app/routers/admin.py` erweitern. Neue Handler `sync_status_home` (GET) und `trigger_mirror_run` (POST) jeweils mit `Depends(require_permission("sync:admin"))`.
  - [x] 6.2 GET `/admin/sync-status` — laedt aus `AuditLog` die letzten 10 Laeufe: Sub-Query holt die letzten 10 distinct `details_json->>'run_id'`-Werte aus `audit_log WHERE entity_type='sync_run' AND action IN ('sync_started','sync_finished','sync_failed') ORDER BY created_at DESC`; dann Haupt-Query alle Rows zu diesen `run_id`s (`... WHERE details_json->>'run_id' IN (:ids)`). Python-seitig zu Run-Tupeln gruppieren: `started` (Pflicht), `finished` (optional — fehlt bei skipped-Run), `failures` (Liste). Fuer den **letzten** Lauf: wenn `finished` vorhanden → Dauer = `finished.created_at - started.created_at`, Counter aus `finished.details_json`; wenn nur `started` mit `details_json.skipped=True` → Status `skipped`, Dauer `None`, Counter leer. Kein NPE bei fehlendem `finished`.
  - [x] 6.3 Template `app/templates/admin/sync_status.html` (neu) — extended `base.html`. Sektion "Letzter Lauf" (Status-Badge + Counter-Grid + Dauer), Sektion "Fehlgeschlagene Objekte" (Tabelle: Object-Link `/objects/{id}`, `impower_property_id`, Phase, Fehler), Sektion "Naechster geplanter Lauf" (absolute Zeit in Europe/Berlin). Button "Jetzt ausfuehren" als `<form hx-post="/admin/sync-status/run" hx-swap="none">`.
  - [x] 6.4 POST `/admin/sync-status/run` — `background_tasks.add_task(run_impower_mirror)` (async-Callable direkt, siehe Task 3.9) + `RedirectResponse(url="/admin/sync-status?triggered=1", status_code=303)`. Flash-Message via URL-Param `?triggered=1` (bestehendes Muster aus Workflows-Router).
  - [x] 6.5 `app/templates/admin/home.html` um eine neue Admin-Kachel "Sync-Status" erweitern mit Link `/admin/sync-status` und Kurzbeschreibung "Impower-Nightly-Mirror Status + Manual-Trigger". Nur sichtbar fuer User mit `sync:admin`.
  - [x] 6.6 **Keine** neue Route-Permission noetig — `sync:admin` ist seit Story 1.1 in `PERMISSIONS` registriert + via `admin`-Rolle zugewiesen (siehe `app/permissions.py:71-75, 91-107`). Verifizieren, NICHT neu registrieren.

- [x] **Task 7 — Tests: Mirror-Unit, Scheduler-Unit, Migration-Roundtrip, Admin-Routes-Smoke, End-to-End** (alle AC + AC10)
  - [x] 7.1 Neue Datei `tests/test_sync_common_unit.py` — 9 Tests: `test_next_daily_run_at_same_day_future`, `test_next_daily_run_at_past_rolls_to_tomorrow`, `test_next_daily_run_at_dst_spring_forward` (Europe/Berlin, Uhr springt 2→3 Uhr am letzten Maerz-Sonntag, 02:30 existiert nicht → naechstes 02:30 am Folgetag; in `next_daily_run_at` via `astimezone(UTC).astimezone(tz)`-Roundtrip normalisieren), `test_next_daily_run_at_dst_fall_back` (Europe/Berlin, letzter Oktober-Sonntag, 02:30 existiert **zweimal** — `ZoneInfo` default `fold=0` waehlt die fruehere CEST-Instanz, Job laeuft einmal; Test dokumentiert das Default-Verhalten, auch wenn in Prod harmlos), `test_strip_html_error_removes_tags`, `test_strip_html_error_truncates`, `test_run_sync_job_happy_path_counts_items`, `test_run_sync_job_item_error_continues`, `test_run_sync_job_lock_skips_second_call`.
  - [x] 7.2 Neue Datei `tests/test_steckbrief_impower_mirror_unit.py` — mockt `app.services.impower._make_client` via `monkeypatch` mit einem `httpx.AsyncClient(transport=httpx.MockTransport(...))`, der kuratierte JSON-Responses liefert. **Pro Test Lock-Reset** via autouse-Fixture: `app.services.steckbrief_impower_mirror._mirror_lock = None` (Reset zwischen Tests, damit der Lazy-Getter aus Task 3.1 pro Event-Loop neu konstruiert). Tests: `test_mirror_writes_cluster_1_fields`, `test_mirror_writes_cluster_6_fields`, `test_mirror_skips_user_edit_via_mirror_guard`, `test_mirror_eigentuemer_insert_new_creates_provenance_rows` (verifiziert Platzhalter-Pattern aus Task 4.5: Erstwrite mit echtem Wert erzeugt Provenance, leere Voting-Stake-Default bleibt ohne Row), `test_mirror_eigentuemer_update_existing_via_write_gate`, `test_mirror_eigentuemer_orphan_preserved_listed_in_audit`, `test_mirror_mandate_refs_stable_sort_prevents_noise_provenance`, `test_mirror_one_property_503_others_succeed`, `test_mirror_object_without_impower_id_skipped_not_failed` (zaehlt `items_skipped_no_external_id`), `test_mirror_object_with_unknown_impower_id_skipped_not_failed` (zaehlt `items_skipped_no_external_data`), `test_mirror_second_call_while_running_skips` (verifiziert `skipped=True` + `sync_started.details_json.skipped=True`, **kein** `sync_finished`-Eintrag fuer den skipped-Run), `test_mirror_second_call_after_finish_noop_unchanged_no_new_provenance`.
  - [x] 7.3 Neue Datei `tests/test_migration_0012_roundtrip.py` — minimaler Test: `alembic upgrade head` (aus 0011) setzt Spalten, `alembic downgrade -1` entfernt sie. Kann mit In-Memory-SQLite + `alembic.config.Config`-Objekt aufgesetzt werden (bestehendes Muster aus `tests/test_migrations_*.py` falls vorhanden — sonst skippen, wenn das Projekt keine Migration-Tests hat; dann alternativ ein `test_models_load_cleanly_after_migration` via `Base.metadata.create_all`).
  - [x] 7.4 Tests in `tests/test_steckbrief_routes_smoke.py` (bestehend aus Story 1.3) **nicht** erweitern — Mirror-Admin-Tests liegen in neuer Datei `tests/test_admin_sync_status_routes.py`: `test_sync_status_requires_sync_admin_perm` (anon → 302, auth_client ohne sync:admin → 403, admin_client → 200), `test_sync_status_renders_last_run_summary`, `test_sync_status_renders_failed_objects_table`, `test_trigger_mirror_run_redirects_303`, `test_admin_home_shows_sync_status_link_for_admin`.
  - [x] 7.5 End-to-End-Test `test_mirror_e2e_three_objects_one_failure` in `test_steckbrief_impower_mirror_unit.py`: 3 Objekte mit impower_property_id, MockTransport gibt fuer 2 gueltige Daten zurueck, fuer 1 ein 503. Nach `await run_impower_mirror()`: 2 Objekte haben neue Provenance-Rows, 1 hat `sync_failed`-Audit, `sync_finished.details_json.objects_ok=2, objects_failed=1`.
  - [x] 7.6 **Write-Gate-Coverage-Scanner** (Story 1.2) MUSS gruen bleiben. Neue Datei `steckbrief_impower_mirror.py` wird vom Scanner erfasst — alle Feld-Writes muessen durch `write_field_human` laufen. Die strukturelle Eigentuemer-Row-Creation (`db.add(Eigentuemer(...))`) ist whitelistet. Falls der Scanner an der `Eigentuemer`-Constructor-Name-Zuweisung (`name=displayName` im Constructor) anschlaegt: Konstruktor-Args sind whitelistet (Scanner aus Story 1.2 erfasst `entity.field = value` post-Instanziierung, nicht Constructor-kwargs). Verifizieren via `pytest tests/test_write_gate_coverage.py`.
  - [x] 7.7 **Regression**: `pytest -x` volles Suite nach Abschluss aller Tasks. Erwartung: alle bestehenden 272+ Tests gruen, plus die neuen Tests aus Task 7. Falls ein bestehender Test rot wird → root-cause ermitteln, NICHT den Test patchen.

- [x] **Task 8 — Docs-Nachzug** (additiv)
  - [x] 8.1 `docs/source-tree-analysis.md` — neue Service-Dateien + Migration + Templates + Tests eintragen.
  - [x] 8.2 `docs/component-inventory.md` — Abschnitt "Steckbrief — Impower-Nightly-Mirror" mit Service-Exports, Scheduler-Verankerung, Admin-Routen.
  - [x] 8.3 `docs/data-models.md` — `Object`-Feldliste um die 4 neuen Spalten erweitern, `Eigentuemer` um `impower_contact_id`.
  - [x] 8.4 `docs/architecture.md` §8 (Audit-Actions) ist bereits vollstaendig (sync_started/finished/failed). **Nicht** ergaenzen.
  - [x] 8.5 `CLAUDE.md` bekommt einen Statuseintrag unter M5/Backlog (oder neuer "Epic 1 Story 1.4" Abschnitt): "M5 Paket 7 Live-Test" bleibt offen, neuer Bullet "Story 1.4: Impower-Nightly-Mirror Cluster 1+6 — Code fertig, Live-Verifikation in Prod steht aus (erster Lauf 02:30 Uhr, pruefen per /admin/sync-status am naechsten Morgen)".

### Nicht im Scope dieser Story (explizit spaeter)

- **Live-Pull-Saldo** (`last_known_balance`) — ist Scope von Story 1.5 (synchron im Render-Handler, kein Nightly-Write).
- **Ruecklage-Historie-Snapshots / dedizierte `reserve_snapshots`-Tabelle** — Story 1.5 entscheidet, ob die Sparkline aus `FieldProvenance.value_snapshot[old/new]` rekonstruiert wird oder eine separate Tabelle bekommt.
- **Auto-Delete verwaister Eigentuemer** — v1.1, zu riskant fuer MVP (Impower-Teil-Ausfall koennte zu Massen-Deletes fuehren).
- **Mieter-Reconcile** — Story 1.4 mirrort **keine** Mieter aus Impower. Mieter kommen ueber den M5-Mietverwaltungs-Flow oder eine spaetere Story.
- **Facilioo-Mirror** (1-Min-Poll) — Story 4.3. Teilt aber `_sync_common.run_sync_job`-Wrapper (der in dieser Story entsteht).
- **SharePoint-Mirror** — Story 1.8 / separat.
- **Retry-Logik ueber den Impower-Client hinaus** — Der bestehende Client retried 5xx mit Exponential-Backoff (2/5/15/30/60 s, max 5 Versuche). Mirror addiert keine zusaetzliche Retry-Schleife — wenn der Client aufgibt, ist das Objekt fuer diesen Lauf fertig (AC6).
- **Multi-Container-Leader-Election** — v1 laeuft 1 Container in Prod. Advisory PG Lock / Leader-Election ist YAGNI.
- **Per-Eigentuemer-Feld-Provenance vs. Snapshot-Audit** — Eigentuemer-Felder laufen durch `write_field_human` (Provenance pro Feld). Keine zusaetzliche Snapshot-Table fuer Historie.

### Review Findings

Runde 1 (Prod-Code + Migration) aus `bmad-code-review`, 2026-04-22. Drei parallele Layer: Blind Hunter, Edge Case Hunter, Acceptance Auditor. Runde 2 (Tests + conftest) separat.

**Decision-needed (entschieden, dann patched):**

- [x] [Review][Decision] voting_stake-Heuristik: **Heuristik belassen, WARNING-Log bei Grenzwerten** (val==0, val==1) — Spec erlaubt die Heuristik, Live-Validierung beim ersten realen Lauf. Code in `_normalize_voting_stake`.
- [x] [Review][Decision] Pflegegrad-Cache Invalidierung bei Mirror-Writes: **dismiss, kein Bug** — No-Op-Guard greift bei semantisch unveraenderten Writes bereits (keine Invalidierung), echte Aenderungen SOLLEN den Cache invalidieren, weil der Score von den Feldern abhaengt.
- [x] [Review][Decision] Orphan-Audit-Position: **`sync_finished` bleibt** (AC4-Spec ist logisch unmoeglich — Orphans sind erst nach Eigentuemer-Phase bekannt). Orphan-Entries tragen jetzt **Objekt-Kontext** (`object_id`, `impower_contact_id`, `display_name`) statt rohes contact_id-String.
- [x] [Review][Decision] `mietverwaltung_write.py flag_modified`: **bleibt drin** — ist ein legit Dirty-Flag-Bugfix (Shared-Ref-Problem nach Shallow-Copy), im Commit separat dokumentiert.

**Patch (eindeutig fixbar, noch offen):**

- [x] [Review][Patch] Impower-Error-Sentinel bei Mandate-Fetch ignoriert → silent Overwrite mit `[]` [app/services/steckbrief_impower_mirror.py:224-240] — `_api_get` liefert `{"_error": -1, ...}` bei 4xx/Timeout; `isinstance(mandates_raw, list)` ist False, `mandates=[]`, write_field_human ueberschreibt bestehende `sepa_mandate_refs` mit Leerliste. **Critical**
- [x] [Review][Patch] Fetch-Fail wird als Run-Status "partial" mit Phantom-Object klassifiziert [app/services/_sync_common.py:147-162 + app/routers/admin.py:740] — Bei Impower-Komplettausfall zeigt Admin-UI "1 Objekt fehlgeschlagen" ohne Item-Kontext; es gibt keinen Run-Status "failed". Fix: bei `items_failed > 0 && items_ok == 0 && kein erfolgreiches Item` → status="failed". **Critical**
- [x] [Review][Patch] `_fetch_owner_contracts_by_property` fallback `display_name = str(cid)` ueberschreibt bestehende Namen [app/services/steckbrief_impower_mirror.py:262-277] — Wenn `contacts_by_id[cid]` fehlt (Paging-Trunkation, Impower liefert Contact nicht), schreibt der Mirror die rohe numerische Contact-ID ins `name`-Feld. Fix: Skip write_field_human wenn display_name der str(cid)-Fallback ist. **Critical**
- [x] [Review][Patch] Lock-Check nicht atomar — Race zwischen `lock.locked()` und `lock.acquire()` [app/services/_sync_common.py:178-197] — Zwei parallele Trigger (Scheduler + Manual) koennen beide `locked()==False` sehen und beide in `acquire()` springen; zweiter wartet blockierend statt skip. Fix: `try: await asyncio.wait_for(lock.acquire(), timeout=0); except TimeoutError: return skipped` oder separaten Guard-Flag. **High**
- [x] [Review][Patch] `next_daily_run_at` DST-unsicher: Fruehjahr 02:30 nicht existent, Herbst 02:30 doppelt, `timedelta(days=1)` addiert UTC-Seconds statt Lokalzeit [app/services/_sync_common.py:100-115] — Am 29.03.2026 und 25.10.2026 laeuft der Job zur falschen Uhrzeit. Fix: Nach `+timedelta(days=1)` explizit `astimezone(tz).replace(hour=2, minute=30, fold=0)` + Check via `zoneinfo`. Auch: `candidate.replace(day=candidate.day)` ist dead-code (No-Op) — loeschen. **High**
- [x] [Review][Patch] `asyncio.sleep` Clock-Jump → Hot-Loop / uebersprungene Laeufe [app/main.py:201-228] — Bei NTP-Sprung, Host-Suspend oder DST-Shift kann `next_run - now` negativ/0 werden → Busy-Loop mit Impower-Calls. Fix: nach `run_impower_mirror()` mindestens 60 s Cooldown; Check ob `next_run` sinnvoll > now+60. **High**
- [x] [Review][Patch] `_build_full_address` liefert `None` bei leerer Street → existierende User-Adresse wird auf NULL ueberschrieben [app/services/steckbrief_impower_mirror.py:101-109] — Write-Gate macht nur No-Op wenn `old == new`; bei `old="Beispielstr. 1, 10115 Berlin"` und `new=None` schreibt es NULL. Fix: wenn `_build_full_address` None zurueckgibt, `write_field_human` **nicht** aufrufen (early-skip). Gleiches Muster fuer alle `_to_decimal`-None-Returns pruefen. **High**
- [x] [Review][Patch] `sync_failed.details_json` fehlt `impower_property_id` + `phase` (AC6-Verletzung) [app/services/_sync_common.py:276-289] — Generischer Wrapper kennt keine Phasen; AC6 verlangt aber `{"impower_property_id": ..., "phase": "cluster_1"|"cluster_6"|"eigentuemer", "error": ...}`. Fix: `reconcile_item` gibt `phase`-Info im Exception-Context mit, oder per-Item-Fehler-Audit wird im Mirror-Service statt im Wrapper emittiert. **High**
- [x] [Review][Patch] `sync_failed.entity_id = None` statt `obj.id` (AC6-Verletzung) [app/services/_sync_common.py:283-284] — Admin-UI extrahiert `item_id` nur aus `details_json`, indizierter Link ueber `entity_id` fehlt. Fix: `reconcile_item` liefert auch `entity_id` zurueck. **High**
- [x] [Review][Patch] Migration-`server_default` vs Model-`server_default` Drift [migrations/versions/0012_steckbrief_finance_mirror_fields.py:35-43 + app/models/object.py] — Migration nutzt `sa.text("'[]'::jsonb")`, Model nutzt `server_default="[]"` (String). `Base.metadata.create_all` (Tests) erzeugt nicht dieselbe Spalten-Definition wie Alembic. Fix: Model auf `server_default=sa.text("'[]'::jsonb")` angleichen. **High**
- [x] [Review][Patch] `_load_recent_mirror_runs` Limit `limit*60` Heuristik unzuverlaessig (AC9 verlangt Sub-Query auf distinct run_ids) [app/routers/admin.py:712-725] — Bei partiellem Lauf mit vielen Failures (&gt;52 Rows) fallen aeltere Laeufe aus der Historie. Fix: Sub-Query `SELECT DISTINCT details_json->>'run_id' ORDER BY created_at DESC LIMIT <limit>`, dann Rows zu diesen run_ids laden. **Medium**
- [x] [Review][Patch] `objects_total` fehlt in `sync_finished.details_json` (AC2-Verletzung) [app/services/_sync_common.py:318-333] — AC2 verlangt explizit `objects_total`. Fix: Feld in `_finish_details` aufnehmen. **Medium**
- [x] [Review][Patch] Kein Gesamt-Lauf-Timeout — haengender Impower-Call kann Scheduler mehrere Tage blockieren [app/services/steckbrief_impower_mirror.py:222-240 + app/main.py] — Parallelisierung ist per Spec explizit out-of-scope, aber Gesamt-Lauf-Deadline fehlt. Fix: `asyncio.wait_for(run_impower_mirror(), timeout=30*60)` im Scheduler-Loop; bei Timeout `sync_failed` + Lock freigeben. **Medium**
- [x] [Review][Patch] `_normalize_mandate_refs` Sort crasht bei gemischten int/str `mandate_id` [app/services/steckbrief_impower_mirror.py:115-124] — Python 3 wirft `TypeError` beim Sort von `[1, "2"]`. Fix: `mandate_id` vor Sort einheitlich zu `str(mid)` coercen. **Medium**
- [x] [Review][Patch] Template `astimezone()` ohne tz-Arg zeigt Container-UTC statt Berlin-Zeit [app/templates/admin/sync_status.html:35,120] — Elestio-Container TZ=UTC; Admin sieht Zeiten verschoben. Fix: `astimezone(ZoneInfo("Europe/Berlin"))` via Jinja-Filter oder im Router vor-formatieren. **Medium**
- [x] [Review][Patch] HTMX-Trigger nicht idiomatisch — RedirectResponse statt `HX-Redirect`-Header [app/routers/admin.py:797-806] — Form funktioniert via `action=`-Fallback, aber HTMX-Pfad laedt volle Seite statt Snippet. Fix: bei `HX-Request`-Header `Response` mit `HX-Redirect: /admin/sync-status?triggered=1` statt 303. **Medium**
- [x] [Review][Patch] Name-Compare ohne NFKC-Normalize triggert Provenance-Churn bei Whitespace/Unicode-Drift [app/services/steckbrief_impower_mirror.py:355-395] — Impower liefert "Mueller" vs "Müller": `old == new` ist False, Mirror schreibt "Update" ohne Semantik-Change. Fix: in `_reconcile_eigentuemer` NFKC-normalisierter Vergleich vor `write_field_human`. **Medium**
- [x] [Review][Patch] `entity_type`-Filter in Query fehlt (Folge von entity_id-Fix) [app/routers/admin.py:712-716] — Nach Fix von sync_failed auf `entity_type="sync_run"` (siehe Finding oben) muss Query wieder `AuditLog.entity_type == "sync_run"` einbauen. **Low**
- [x] [Review][Patch] Scheduler-Loop nutzt `print()` statt `_logger` [app/main.py:213-228] — `_logger` ist in main.py bereits importiert aber ungenutzt. Fix: auf `_logger.info/error` umstellen. **Low**
- [x] [Review][Patch] Admin-Route hardcoded `hour=2, minute=30` statt Modul-Konstante [app/routers/admin.py:324-326] — `_MIRROR_RUN_HOUR`/`_MIRROR_RUN_MINUTE` aus `main.py` duplizieren. Fix: Konstanten in `_sync_common.py` exportieren, beide Stellen importieren. **Low**
- [x] [Review][Patch] `eigentuemer_inserted += 1` unabhaengig von `name_res.written` [app/services/steckbrief_impower_mirror.py:315-325] — Falls `write_field_human` stillschweigend skipt, steht im Audit "20 Inserts", in DB aber `name=""`. Fix: nur ++ wenn `name_res.written`. **Low**
- [x] [Review][Patch] `hx-swap="none"` fehlt auf Trigger-Form (Task 6.3) [app/templates/admin/sync_status.html:79-84] — Funktional harmlos dank action-Fallback, aber Task-Spec verlangt es explizit. **Low**
- [x] [Review][Patch] Stale "running"-Runs nie finalisiert nach Prozess-Crash [app/routers/admin.py:740-744] — `sync_started` ohne `sync_finished` erscheint dauerhaft als "Laeuft". Fix: wenn `started_at > 1h` und kein finished → status="crashed". **Low**
- [x] [Review][Patch] `?triggered=1` nicht repost-safe (F5 zeigt Flash erneut) [app/routers/admin.py:784-806] — Option: Flash via Session-Cookie statt Query-Param. **Low**
- [x] [Review][Patch] Running-Run zeigt `duration_seconds=None` als "– s" statt Elapsed [app/templates/admin/sync_status.html:62-69] — Fix: fuer running status `(now - started_at).total_seconds()` live zeigen. **Low**

**Defer (pre-existing / real aber nicht akut):**

- [x] [Review][Defer] Index-Name `ix_eigentuemer_impower_contact` vs Spec-AC8 `ix_eigentuemer_impower_contact_id` [migrations/versions/0012_steckbrief_finance_mirror_fields.py:62-66] — deferred, Spec widerspricht sich selbst (AC8 vs Task 1.3); Rename-Migration in v1.1 wenn gewuenscht.
- [x] [Review][Defer] `_audit_sync` nutzt eigene DB-Session via `db_factory()` — Session-Mix-Risiko bei Tests mit transactional scope [app/services/_sync_common.py:127-144] — deferred, Tests aktuell gruen (347/347); Doc-String an `_audit_sync` hinzufuegen, wenn Session-Convention spaeter formalisiert wird.

**Dismissed (11):** Multi-Worker-Lock (Spec YAGNI); sepa_mandate_refs JSONB-Roundtrip (hypothetisch); strip_html_error dead branch; Template-XSS (Jinja autoescape greift); `_reset_mirror_lock_for_tests` (test-only); voting fallback readability; `percent` vs `fraction` Key (task-spec conform); plus 4 non-violation Auditor-Findings.

## Dev Notes

### Empfohlene Implementations-Reihenfolge

1. **Task 1 Migration + Model-Edits** zuerst. `docker compose exec app alembic upgrade head` → Tabellen-Check in psql. Dann `alembic downgrade -1` → `alembic upgrade head` (Roundtrip) — faengt 80 % der Schema-Fehler.
2. **Task 2 `_sync_common.py`** + 7.1 Unit-Tests. Tests koennen komplett ohne Impower laufen — gibt sofortiges Feedback zum Job-Wrapper-Kern + DST-Edge-Case.
3. **Task 3/4 Mirror-Service** ohne Scheduler. `pytest tests/test_steckbrief_impower_mirror_unit.py -x`. MockTransport statt echter Calls.
4. **Task 5 Scheduler** + smoke-Verifikation: App starten, `docker compose logs app | grep scheduler` — der Task muss auftauchen + den naechsten Run-Zeitpunkt loggen.
5. **Task 6 Admin-UI** + 7.4-Tests. Browser-Smoketest gegen `/admin/sync-status`.
6. **Task 7 End-to-End** + Regressionslauf `pytest -x`.
7. **Task 8 Docs**.

Nach jedem Schritt `pytest -x` gruen halten. **Write-Gate-Coverage-Scanner** MUSS die gesamte Story ueberleben — wenn er rot wird, hat der Dev-Agent unbewusst einen direkten Feld-Write eingefuehrt (Eigentuemer-Constructor ist OK, post-Instanziierung-Zuweisungen nicht).

### Warum `write_field_human`, NICHT direkter `setattr` im Mirror-Service

Das Write-Gate aus Story 1.2 enthaelt zwei Features, die der Mirror dringend braucht:
1. **Mirror-Guard** (`write_field_human` Zeile 243–248): wenn der letzte Provenance-Eintrag ein `user_edit` oder `ai_suggestion` ist, skippt der Mirror das Feld strukturell. **Ohne** Gate muesste der Mirror-Service selbst die Provenance-Historie pruefen → redundant und fehleranfaellig.
2. **No-Op-Short-Circuit** (Zeile 250–266): unveraendertes Feld + gleiche Source → kein Write, keine Provenance, kein Audit. Ohne Short-Circuit produziert jeder Nightly-Lauf 200 FieldProvenance-Rows pro Objekt, selbst wenn sich nichts geaendert hat → Ruecklage-Sparkline in Story 1.5 wird verrauscht.

Direkt `setattr(obj, field, value)` zu benutzen bricht BEIDE Features und den Write-Gate-Coverage-Scanner. Auch bei vermeintlich "schreib-lastigen" Mirror-Loops: immer durch das Gate.

### Impower-Feld-Mapping (Property → Object)

Swagger (`/v2/api-docs` → Properties-DTO, aus `memory/reference_impower_api.md` + Live-Verifikation in M2/M3):

| DB-Feld (`objects.*`) | Impower-Property-Feld | Typ | Kommentar |
|---|---|---|---|
| `full_address` | `"{addressStreet}, {addressZip} {addressCity}"` | `str \| None` | Zusammengebaut; falls street fehlt → None, write-gate skippt |
| `weg_nr` | `name` oder `wegNumber` | `str` | **Feldname im Property-DTO verifizieren** — in M2 haben wir `name` genutzt (z. B. "HAM61"); wenn das Property-DTO inzwischen `wegNumber` hat, dann dort lesen. Fallback in Code: `property.get("wegNumber") or property.get("name")` |
| `reserve_current` | `reserveCurrent` oder `financeSummary.reserveCurrent` | `Decimal` | Swagger-Pfad beim ersten Live-Lauf verifizieren; falls leer → write-gate No-Op |
| `reserve_target` | `reserveTargetMonthly` oder `financeSummary.reserveTarget` | `Decimal` | dito |
| `wirtschaftsplan_status` | `economicPlanStatus` oder `wirtschaftsplanStatus` | `str` | Mapping `RESOLVED→beschlossen`, `IN_PREPARATION→in_vorbereitung`, `DRAFT→entwurf` |
| `sepa_mandate_refs` | NICHT aus Property — separater Call `GET /services/pmp-accounting/api/v1/direct-debit-mandate?propertyId=<pid>` | `list[dict]` | Filter `state=BOOKED`, Projektion `{mandate_id, bank_account_id, state}`, **stable sort** |

**Verifikation beim ersten Live-Lauf**: Der Dev-Agent soll im Dev-Container einmalig `curl` oder ein kleines Python-Snippet gegen einen der Test-Properties (z. B. HAM61) fahren, das tatsaechliche Property-DTO pretty-printen und die Feld-Namen abgleichen. Swagger-Felder driften leicht. Falls abweichend: Mapping in Task 3.2-3.4 anpassen, **NICHT** das Objekt-Schema umschreiben.

### Impower-Feld-Mapping (OWNER-Contract → Eigentuemer)

Aus `load_owner_contracts()` (existierend in `app/services/impower.py:159`) kommt eine Liste von Contract-Dicts mit mindestens `{id, propertyId, contactId, ...}`. Das Contact-Display + Voting-Share ist NICHT direkt im Contract — man braucht einen Lookup via `load_all_contacts()` (cached pro Mirror-Run) oder einen Join auf `contacts[contactId]`.

Praktisches Muster (einmal pro Lauf):
```python
properties = await _fetch_impower_snapshot(client)
contracts = await client.get("/v2/contracts?type=OWNER")  # via _get_all_paged
contacts = await load_all_contacts()  # liefert Dict mit bankAccounts bereits angereichert
contacts_by_id = {str(c["id"]): c for c in contacts}

for prop_id, bucket in properties.items():
    owner_ids_for_prop = [c["contactId"] for c in contracts if c["propertyId"] == prop_id]
    owners = [{
        "contactId": str(cid),
        "displayName": _contact_display_name(contacts_by_id.get(str(cid), {})),
        "votingShare": <contract["votingShare"] or fallback>,
    } for cid in owner_ids_for_prop]
```

`_contact_display_name()` existiert schon in `impower.py:211` — wiederverwenden. Voting-Share-Feld im Contract-DTO: Kandidaten `votingShare`, `sharePercent`, `voteFraction` — Dev-Agent verifiziert am Live-Beispiel, nimmt ersten non-None.

### Scheduler-Design: warum `asyncio.create_task` im Lifespan, nicht APScheduler

CD3 (`architecture.md:284-309`) legt fest: **keine neue Dependency**. Ein `asyncio.create_task(_scheduler_loop())` im Lifespan + Cancel im Shutdown reicht fuer den 1-Container-Case. Vorteile gegenueber APScheduler/cron:
- Kein Persistenz-Store noetig (Status wird aus AuditLog gelesen, siehe AC9).
- Kein Dependency-Upgrade-Risiko.
- Einheitlich mit dem Facilioo-Poll aus Story 4.3 (CD3 verlangt denselben Mechanismus dort).

Tradeoff: bei Container-Neustart zwischen 02:30 und 02:31 koennte ein Lauf ausfallen. Akzeptiert fuer v1 — der Admin sieht es in `/admin/sync-status`, kann manuell triggern.

### Idempotenz-Design: `asyncio.Lock` auf Modul-Ebene

Der lazy konstruierte `_mirror_lock` (siehe Task 3.1) in `steckbrief_impower_mirror.py` ist **pro Process**. Bei Elestio-Singleton-Container reicht das. Falls spaeter horizontal skaliert wird:
- Option 1: advisory PG lock via `pg_try_advisory_lock(hash_of_"steckbrief_impower_mirror")`.
- Option 2: Redis mit SETNX + Expiry.
- Option 3: Leader-Election via Kubernetes-Lease.

Alle drei sind v1.1-Scope. Der Code-Locator (`_mirror_lock`-Modul-Global) ist der Anker fuer den spaeteren Ersatz — eine Zeile.

### Mirror-Guard-Skip ist KEIN Fehler

Ein Skip mit `skip_reason="user_edit_newer"` darf nicht als `sync_failed` gezaehlt werden — sonst laeuft das Admin-UI bei jedem zweiten Lauf rot an (wenn es User-Edits gab). AC5 verlangt explizit, dass der Skip im `sync_finished.details_json.skipped_user_edit_newer`-Counter sichtbar wird, **nicht** im `objects_failed`-Counter. Testsliebes Muster: vergleiche `WriteResult.written` UND `WriteResult.skip_reason` explizit, leg beide Counter separat ab.

### Stable-Sort bei JSONB-Listen vermeidet Provenance-Noise

`sepa_mandate_refs` ist eine Liste. `write_field_human` vergleicht `old == new` via Python-Gleichheit. `[{"mandate_id":1,...},{"mandate_id":2,...}] == [{"mandate_id":2,...},{"mandate_id":1,...}]` → **False** (Listen sind ordnungs-empfindlich). Ohne stable sort fliegen bei jedem Lauf neue Provenance-Rows, das Write-Gate denkt "Feld hat sich geaendert". Loesung: `_normalize_mandate_refs` sortiert nach `mandate_id` asc, bevor die Liste in das Feld geht.

Gleiches Argument fuer `voting_stake_json` (Dict): Keys in Dicts sind **nicht** reihenfolge-relevant in Python-3.7+-Gleichheit, aber der JSONB-Schreibpfad serialisiert nach `json.dumps(..., sort_keys=False)`. Um auf der sicheren Seite zu bleiben: Dict-Keys im Normalisierungspfad stabil halten (`{"percent": ...}`, immer derselbe Schluessel).

### Edge-Cases, die der Dev-Agent beim Test-Design beachten sollte

- **Objekt ohne `impower_property_id`**: wird vom Mirror geskippt. Test: `test_mirror_skips_object_without_impower_id`. Kein `sync_failed`, kein Write, aber in `sync_finished.details_json.objects_skipped_no_impower_id` zaehlen.
- **Impower-Property existiert in DB aber nicht mehr in Impower**: Mirror findet sie nicht im Snapshot. Kein Write, kein Fehler. Admin-UI koennte das spaeter anzeigen — **out of scope** fuer 1.4.
- **Property-DTO ohne `addressStreet`**: `_build_full_address` liefert None → write-gate macht No-Op. Kein Fehler.
- **Leere Owner-Liste fuer ein Property**: keine Eigentuemer-Writes, existierende bleiben erhalten (AC4.6 Orphan-Logik).
- **Mandat-Liste leer**: `sepa_mandate_refs = []`, beim ersten Write entsteht eine Provenance-Row mit `{"old": null, "new": []}`. Folgende Laeufe sind No-Op. Richtig.
- **`voting_stake_json` als leeres Dict** `{}`: `write_field_human` schreibt nur, wenn `old != new`. `{} == {}` → No-Op. Richtig.
- **DST-Uebergang**: 02:30 Europe/Berlin existiert am Fruehjahrs-Sonntag nicht (Uhr springt 02:00→03:00). `next_daily_run_at` muss den Fall behandeln: ZoneInfo wirft `NonExistentTimeError` nicht, Python macht einen "fold" — der zurueckgegebene datetime kann "nicht existiert haben" Semantik haben. Pragmatischer Workaround in Task 2.4: nach Berechnung von `tomorrow 02:30` einmal `datetime.astimezone(UTC).astimezone(tz)` normalisieren; das liefert einen gueltigen Instant.

### Previous-Story-Learnings (aus 1.1 + 1.2 + 1.3)

1. **`_ALLOWED_SOURCES` umfasst `impower_mirror`** (Story 1.2, `_ALLOWED_SOURCES` in `steckbrief_write_gate.py`). Nichts neu registrieren.
2. **SQLAlchemy 2.0 Syntax** — Queries via `db.execute(select(...))`. **Nicht** `db.query(Model)`. Gilt auch fuer den Mirror-Service.
3. **Audit-Actions registriert**: `sync_started`, `sync_finished`, `sync_failed` (Story 1.2, `KNOWN_AUDIT_ACTIONS` in `audit.py`). Nicht neu eintragen.
4. **Permissions-Registry**: `sync:admin` ist in Story 1.1 registriert, admin-Rolle hat es, `user`-Rolle NICHT (bewusst). Story 1.4 muss nur `Depends(require_permission("sync:admin"))` nutzen — keine Registry-Aenderung.
5. **TemplateResponse: Request first** (Memory `feedback_starlette_templateresponse`). Gilt fuer `sync_status.html`.
6. **`_reset_db`-Fixture** iteriert `sorted_tables` — neue Spalten greifen automatisch, neue Tabellen werden automatisch zurueckgesetzt. Keine conftest-Anpassung noetig.
7. **Impower-Calls in Tests immer mocken** (`memory/project_testing_strategy.md`, `docs/project-context.md`). `httpx.MockTransport` ist das etablierte Muster.
8. **BackgroundTask-Pattern**: eigene `SessionLocal()`-Session pro Item (run_sync_job macht das), kein Sync-Shim noetig — `BackgroundTasks.add_task(run_impower_mirror)` reicht (FastAPI runs async callables auf dem Loop). Lifespan-Scheduler ruft `await run_impower_mirror()` direkt.
9. **JSONB-Mutation**: `obj.sepa_mandate_refs = [...]` (Reassignment) ist **Pflicht**. `obj.sepa_mandate_refs.append(...)` wird NICHT persistiert (Memory/Project-Context "JSONB-Fallen"). Der Mirror-Service baut die Liste neu und schreibt sie via write-gate — das Gate ruft intern `flag_modified`, wenn der Wert ein Dict/List ist.
10. **Eigentuemer ist in `_TABLE_TO_ENTITY_TYPE`** mappt auf `"eigentuemer"` (Story 1.2, `_TABLE_TO_ENTITY_TYPE` in `steckbrief_write_gate.py`). Mirror-Writes auf Eigentuemer-Feldern produzieren Audit-Action `registry_entry_updated`.

### Source tree — Regressions-sensitiv (NICHT anfassen)

**Unveraendert:** `steckbrief_write_gate.py` (Mirror-Guard + No-Op-Short-Circuit decken den Mirror schon ab; neue Felder via `setattr` automatisch), `audit.py` (Sync-Actions registriert), `impower.py` (Client-Primitiven werden wiederverwendet), `permissions.py` (`sync:admin` + admin-Rolle), `steckbrief.py`, `templating.py`, `objects.py`, alle Migrationen `0001_*` bis `0011_*`.

Fuer die Liste der **neuen + zu editierenden** Dateien siehe Task 8 (Docs-Nachzug).

### Plattform-Regeln, die gelten (aus `docs/project-context.md`)

- **SQLAlchemy 2.0 typed ORM + `db.execute(select(...))`** — Pflicht in neuem Code.
- **Alembic-Migrations: per Hand schreiben**, `down_revision` **vor** Anlage verifizieren (`ls migrations/versions/`).
- **Absolute Imports** (`from app.services.steckbrief_impower_mirror import ...`).
- **Eigene Exceptions aus Services** — falls der Mirror eine neue braucht (unwahrscheinlich; `ImpowerError` deckt externe Fehler ab, `WriteGateError` deckt interne Write-Fehler), dann `MirrorError(Exception)`. Default: keine neue Exception, Impower-Fehler propagieren unveraendert.
- **Services kennen keine HTTP-Typen** — kein `Request`, kein `BackgroundTasks` im Service-Layer. `run_impower_mirror` ist async und bekommt `db_factory` + `http_client_factory` als Injection-Punkte (fuer Tests).
- **`print()` + `audit()` fuer Logging** — Scheduler-Task logt via `print("[mirror_scheduler] ...")`.
- **Keine Kommentare, die das WAS beschreiben** — nur das WARUM (z. B. "Stable-Sort verhindert Provenance-Noise"), und nur dort, wo nicht aus dem Code ablesbar.
- **Keine TODO/FIXME-Kommentare.**
- **JSONB-Fallen**: Reassignment statt In-Place-Mutation.
- **Impower-Client-Regeln**: Rate-Gate, Server-Fields-Strip (bei PUT — in dieser Story kein PUT), 120 s Timeout + 5xx-Retry (schon im Client).

### Testing standards summary

- Pytest mit `asyncio_mode = "auto"`, SQLite in-memory (StaticPool). Migration-Roundtrip-Test ggf. mit eigener In-Memory-Engine (siehe Task 7.3).
- `httpx.MockTransport` fuer alle Impower-Calls — **NIE** echter Netzwerk-Call in Tests.
- Zeit-Abhaengigkeit testen ohne `sleep`: `monkeypatch.setattr(asyncio, "sleep", AsyncMock())` + Time-Provider-Injection fuer `next_daily_run_at` + `datetime.now`.
- SQLAlchemy-Event-Listener-Muster aus Story 1.3 (`test_list_performance_and_no_n_plus_1`) kann fuer den Mirror-Statement-Count-Test wiederverwendet werden — der Mirror MUSS O(objects) Queries bleiben, nicht O(objects * fields).
- Coverage-Ziel: alle 10 AC durch mindestens einen positiven + einen negativen Test gedeckt. Write-Gate-Coverage-Scanner + Regressionslauf MUESSEN gruen sein.
- Kein Playwright.

### Project Structure Notes

Die Dateistruktur bleibt strikt additiv. Keine Router- oder Service-Refactorings. Naming:
- Python-Klassen englisch PascalCase (`SyncRunResult`, `ReconcileStats`).
- Service-Funktionen snake_case englisch wo klar (`run_impower_mirror`, `_reconcile_object`).
- Template-Namen: `admin/sync_status.html` (fortsetzung der `admin/`-Unterordner-Konvention aus `admin/home.html`, `admin/users_list.html`).
- URL-Pfade englisch (`/admin/sync-status`, `/admin/sync-status/run`).

### References

**Primaer (diese 5 zuerst lesen):**

- [Source: output/planning-artifacts/architecture.md#CD3 — Sync-Orchestrator] — Zeilen 284–315: Scheduler-Design, `run_sync_job`-Muster, Rate-Limit-Respektierung, Fallback-Pfade.
- [Source: output/planning-artifacts/architecture.md#CD1 — Datenarchitektur] — Zeilen 165–197: Entity-Uebersicht, Cluster-Spalten.
- [Source: output/planning-artifacts/epics.md#Story 1.4] — Zeilen 415–445: 5 BDD-Kriterien (erweitert in dieser Story auf 10).
- [Source: output/implementation-artifacts/1-3-objekt-liste-stammdaten-detailseite.md] — Vorgaenger-Story: `provenance_pill`-Helper, `get_provenance_map`, conftest-Fixtures (werden in sync_status.html wiederverwendet, falls Status-Zeile Provenance-Context braucht).
- [Source: output/implementation-artifacts/1-2-objekt-datenmodell-write-gate-provenance-infrastruktur.md] — Vor-Vorgaenger: Write-Gate-API, Mirror-Guard-Logik (AC8 dort), `test_write_gate_coverage.py`-Scanner-Regeln, `_ALLOWED_SOURCES`, `_TABLE_TO_ENTITY_TYPE`.

**Sekundaer (bei Bedarf):**

- [Source: output/planning-artifacts/prd.md#FR26 / FR27 / FR30] — Zeilen 566–570: Mirror-Anforderung, Live-Saldo-Abgrenzung, Fallback-UI.
- [Source: output/planning-artifacts/prd.md#NFR-R2 / NFR-R3 / NFR-O3] — Zeilen 617–618, 634: Kein 500er bei Ausfall, Teil-Fehler-Toleranz, Start/Ende/Fehler in stdout + Audit.
- [Source: output/planning-artifacts/architecture.md#CD4 — Authentication, Authorization, Audit] — Zeilen 316–346: `sync:admin` Permission, `sync_started`/`_finished`/`_failed` Audit-Actions.
- [Source: output/planning-artifacts/architecture.md#Implementation Patterns & Consistency Rules] — Zeilen 463–537: BackgroundTask-Muster, Integrations-Patterns, Naming, Fehlerbehandlung.
- [Source: output/planning-artifacts/architecture.md#Project Structure & Boundaries] — Zeilen 540–625: komplette File-Liste inkl. Templates/Router/Services; Admin-Sync-Status-Template ist dort explizit gelistet.
- [Source: docs/project-context.md] — Plattform-Regeln: JSONB-Fallen, SQLAlchemy-2.0, Alembic manuell, BackgroundTask-Fallen, Template-Response-Signatur, Impower-Client-Regeln.
- [Source: docs/architecture.md] — §8 Audit-Actions-Liste.
- [Source: docs/data-models.md] — Cluster-6-Finanz-Felder dort nach Task 8.3 nachziehen.

**Code-Referenzen (beim Bauen konsultieren):**

- `app/services/steckbrief_write_gate.py` — `write_field_human()` (Mirror-Guard + No-Op-Short-Circuit fuer `user_edit_newer` / `noop_unchanged`), `_ALLOWED_SOURCES`, `_MIRROR_SOURCES`, `_TABLE_TO_ENTITY_TYPE`, `_latest_provenance`, `WriteResult`, `_invalidate_pflegegrad`. **Nicht anfassen.**
- `app/services/impower.py` — `_api_get`, `_get_all_paged`, `_rate_limit_gate`, `_make_client`, `load_properties`, `load_owner_contracts`, `load_all_contacts`, `load_unit_contract_mandates`, `_contact_display_name` — Wiederverwendungs-Primitiven. **Nicht anfassen.**
- `app/services/mietverwaltung_write.py` — `run_mietverwaltung_write` als Muster fuer BackgroundTask (eigene Session, audit-Flow, partial/error-Status).
- `app/services/audit.py` — `audit()`-Helper + `KNOWN_AUDIT_ACTIONS`-Liste (Sync-Actions schon enthalten).
- `app/permissions.py` — `PERMISSIONS`-Registry (inkl. `sync:admin`), `DEFAULT_ROLE_PERMISSIONS`, `accessible_object_ids`, `require_permission` / `require_any_permission`.
- `app/models/object.py` — `Object`-Feldliste (Ziel der 4 neuen Spalten).
- `app/models/person.py` — `Eigentuemer`-Feldliste (Ziel des neuen `impower_contact_id`). Achtung: `name` ist `nullable=False`, `voting_stake_json` ist `nullable=False, server_default='{}'`.
- `app/main.py` — `lifespan()`-Hook (Ziel der `scheduler_task`-Integration).
- `app/routers/admin.py` — `admin_home`, `list_users`, etc. als Muster fuer Admin-Route (Permission-Dep, Template-Render mit `request` first).
- `app/templates/admin/home.html` — Ziel der neuen "Sync-Status"-Kachel (bestehendes Muster: `{% if has_permission(user, "…") %}`-Block pro Karte).
- `migrations/versions/0011_steckbrief_governance.py` — Muster fuer manuelle Alembic-Revision. **Revision-ID-Convention: `"0011"` (kurz numerisch).**
- `tests/conftest.py` — `test_object`, `steckbrief_admin_client`, `anon_client`, `auth_client`, `_reset_db`, `_TEST_ENGINE`.
- `tests/test_steckbrief_routes_smoke.py` — SQL-Event-Listener-Muster fuer Statement-Count-Assertions.
- `tests/test_write_gate_coverage.py` — Scanner-Regel: post-Instanziierungs-`<var>.<attr> = ...` auf CD1-Klassen verboten; Constructor-kwargs sind **nicht** erfasst.
- `output/implementation-artifacts/deferred-work.md` — neue Defers aus 1.4-Review dort anhaengen (nicht vorbeugend).

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context)

### Debug Log References

- Volle Suite `pytest` im Container: 347 passed, 7.13 s. Dazu gehoeren die 46 neuen Tests dieser Story (sync_common 11, impower_mirror 18, migration 2, admin 6, scheduler 2, plus bestehende Regression).
- Das initiale Scheitern von `test_sync_status_renders_failed_objects_table` wurde behoben: `_load_recent_mirror_runs` darf nicht auf `entity_type="sync_run"` filtern, da `sync_failed` pro Object `entity_type="object"` traegt. Korrektur: nur auf `action IN (...)` + `details_json.job` filtern.
- 117 s → 7 s Laufzeit: Retry-Delays `_RETRY_DELAYS_5XX=(2,5,15,30,60)` im e2e-Test per monkeypatch auf 0 gezogen — sonst schluckt der 503-Pfad 112 s Warte-Backoff pro fehlerhaftem Property.

### Completion Notes List

- **Migration 0012** `0012_steckbrief_finance_mirror_fields.py`, `revision="0012"` / `down_revision="0011"` — fuegt vier Spalten auf `objects` (`reserve_current`, `reserve_target`, `wirtschaftsplan_status`, `sepa_mandate_refs`) und `eigentuemer.impower_contact_id` hinzu, composite Index `ix_eigentuemer_impower_contact (object_id, impower_contact_id)`. ORM-Models in `app/models/object.py` + `app/models/person.py` analog erweitert.
- **`_sync_common.py`** generisch gehalten (keine Impower-Kenntnisse, wiederverwendbar fuer Facilioo-Poll in Story 4.3). Exports: `SyncRunResult`, `ReconcileStats`, `run_sync_job`, `strip_html_error`, `next_daily_run_at`. Skip-Pfad (`already_running`) erzeugt ausschliesslich `sync_started` mit `skipped=True`, kein `sync_finished` — konform AC7.
- **`steckbrief_impower_mirror.py`** nutzt den lazy `_mirror_lock` (pro Event-Loop konstruiert) + Test-Reset-Hook. Alle Feld-Writes laufen durch `write_field_human(source="impower_mirror")` — Mirror-Guard + No-Op-Short-Circuit sind strukturell abgedeckt. Neue Eigentuemer werden mit Platzhalter-Name `""` gebootstrapped, damit der No-Op-Guard beim Erstwrite nicht zuschlaegt (AC4.5-Muster).
- **Lifespan-Scheduler** in `app/main.py`: `asyncio.create_task(_mirror_scheduler_loop(), name="steckbrief_impower_mirror_scheduler")` bei `settings.impower_mirror_enabled=True`. Shutdown cancelt + await-d den Task. Env-Flag default `True` (Prod), in Tests via conftest auf `false`.
- **Admin-UI**: `GET /admin/sync-status` rekonstruiert Laeufe aus `audit_log` via `run_id`-Gruppierung; `POST /admin/sync-status/run` triggert via `BackgroundTasks.add_task(run_impower_mirror)`. Beide `sync:admin`-gated. Template `admin/sync_status.html` mit Status-Badge, Counter-Grid, Fehler-Tabelle und Historie. Neue Kachel auf `admin/home.html`.
- **Tests**: Regressions-Suite 347/347 gruen. `test_write_gate_coverage` gruen — Eigentuemer-Bootstrap verwendet nur Constructor-kwargs, keine direkten Post-Instanziierungs-Zuweisungen.
- **Offen vor Prod-Rollout**: Live-Verifikation gegen echtes Impower. Property-DTO-Feldnamen (`wegNumber` vs `name`, `reserveCurrent` vs `financeSummary.reserveCurrent`) erst beim ersten Lauf bestaetigen — der Code probiert beide Varianten (`or`-Chain), schreibt `None` wenn beide leer (write-gate macht dann No-Op statt Fehler).

### File List

Neu angelegt:
- `migrations/versions/0012_steckbrief_finance_mirror_fields.py`
- `app/services/_sync_common.py`
- `app/services/steckbrief_impower_mirror.py`
- `app/templates/admin/sync_status.html`
- `tests/test_sync_common_unit.py`
- `tests/test_steckbrief_impower_mirror_unit.py`
- `tests/test_migration_0012_roundtrip.py`
- `tests/test_admin_sync_status_routes.py`
- `tests/test_mirror_scheduler.py`

Modifiziert:
- `app/models/object.py` (+4 Mapped-Spalten)
- `app/models/person.py` (+impower_contact_id)
- `app/config.py` (+impower_mirror_enabled)
- `app/main.py` (+Scheduler-Loop + Lifespan-Integration)
- `app/routers/admin.py` (+GET/POST sync-status + `_load_recent_mirror_runs`)
- `app/templates/admin/home.html` (+Sync-Status-Kachel)
- `tests/conftest.py` (+IMPOWER_MIRROR_ENABLED=false Default)
- `CLAUDE.md` (+Naechste-Schritte-Eintrag Story 1.4)
- `docs/data-models.md` (+4 objects-Spalten, +eigentuemer.impower_contact_id, +Migration 0012-Zeile)
- `docs/source-tree-analysis.md` (+`steckbrief_impower_mirror.py`, +`_sync_common.py`, +`sync_status.html`)
- `docs/component-inventory.md` (+Services-Zeilen, +Admin-Template-Zeile, +Sync-Mirror-Sektion)

### Change Log

- 2026-04-22: Story 1.4 implementiert (Migration 0012 + `_sync_common.py` + `steckbrief_impower_mirror.py` + Lifespan-Scheduler + `/admin/sync-status` + 46 neue Tests). Regression 347/347 gruen. Status → review.
