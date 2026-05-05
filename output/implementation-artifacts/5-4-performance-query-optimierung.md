# Story 5-4: Performance & Query-Optimierung

Status: done

## Story

Als Betreiber der Plattform,
moechte ich N+1-Queries, Pagination-Luecken, redundante Page-Load-Writes und unbounded Fanouts schliessen,
damit die Detail- und Listen-Routes auch bei wachsendem Portfolio (>200 Objekte, >100 Conferences, ueberfuellte Review-Queue) unter den NFR-Latenzen bleiben und keine vermeidbare DB-/HTTP-Last erzeugen.

## Boundary-Klassifikation

`hardening` (cross-cutting, post-prod). **Mittleres Risiko bei Nicht-Umsetzung (skaliert mit Portfoliogroesse), niedriges Risiko bei der Umsetzung selbst** — alle Aenderungen sind read-pfad-Optimierungen oder lokale Idempotenz-Checks.

- Kein neues Feature, keine neuen Permissions, keine neuen Routes.
- **Eine** Migration: `0020_perf_indexes.py` — neue Composite-Indexe auf `field_provenance` (`entity_type, entity_id, field_name, created_at DESC`) und ggf. weiteren Hot-Pfaden. Reversibel, keine Datenmigration.
- 13 Defer-Items aus dem Mapping in `output/implementation-artifacts/sprint-status.yaml:104` (`#11 #26 #31 #33 #37 #55 #57 #99 #104 #106 #112 #120 #125 #133`). **Severity-Mix: 9 medium, 4 low.** Kein `high`, kein Pre-Prod-Blocker — deshalb post-prod.
- **#33 (Phase-2-Aggregator fail-loud) ist explizit out-of-scope** (siehe AC10) — Story 5-3 hat Phase-1+Phase-2 bewusst fail-loud belassen, das wird hier respektiert. #33 bleibt im Backlog mit Sprint-Target `post-prod-when-ux-feedback`.
- **#57 und #106 sind Duplikate** (gleiches Symptom: `accessible_object_ids` wird pro Request neu berechnet) — werden gemeinsam unter AC4 abgehandelt.

**Vorbedingungen:**

1. **Stories 5-1, 5-2, 5-3** koennen davor oder parallel laufen. Keine direkte Code-Kollision:
   - 5-1 fasst CSRF-Middleware, Length-Caps, Audit-IP-Truncate an.
   - 5-2 fasst Seed-Idempotenz, Pflegegrad-Lock, notes_owners-Lock, Foto-Upload-Saga an.
   - 5-3 fasst Facilioo-Aggregator-Defense, Pflegegrad-Crash-Guard, Approve-Lock, Cancellation-Hygiene, Police-Form-Hardening, NBSP-Strip, Score-Clamp an.
   - 5-4 fasst Pagination (`/admin/review-queue`, `/objects`), `sidebar_workflows`-Caching, `accessible_object_ids`-Caching, `get_provenance_map`-Hardening + Index, Pflegegrad-Cache-Hit-Shortcut, `list_conferences_with_properties`-Semaphore, HTMX-401-Antwort, FieldProvenance-Skip-on-equal-value an.
2. **Latest Migration** ist nach 5-1+5-3 `0019_police_column_length_caps.py`. **5-4 baut `0020_perf_indexes.py`.** Pflicht: vor Anlage der Migration `ls migrations/versions/` ausfuehren (Memory `feedback_migrations_check_existing.md`) — falls ein anderer Branch parallel `0020` belegt hat, naechste freie Nummer nehmen.
3. **NFRs aus PRD** (siehe `output/planning-artifacts/prd.md` §Performance, NFR-P1..P4): bei 150 Objekten + 15 Usern muessen Liste + Detail-Page innerhalb der Latenz-Vorgaben bleiben. Diese Story ist die Headroom-Versicherung — heute laeuft alles, aber bei doppelter Portfoliogroesse oder ungebremster Review-Queue ist es eng.

**Kritische Risiken:**

1. **Pagination-Vertrag fuer `/objects` und `/admin/review-queue`** — beide Routes liefern heute alles unbounded. Bei Umstellung auf `LIMIT/OFFSET` muss (a) das Default-`page_size` so gewaehlt sein, dass bestehende Bookmarks/Tests nicht brechen (Vorschlag: `page_size=50` Default, `page_size=200` Maximum via Query-Param, gleicher Vertrag in beiden Routes), (b) der existing Sort-Vertrag aus Story 3.1 (`sort=`/`order=`-Query-Params) bleibt erhalten, (c) Tests, die heute `assert len(rows) == 5` schreiben, kennen das `?page_size=`-Param nicht — Default muss so sein, dass die `tests/test_steckbrief_routes_smoke.py`-Suite gruen bleibt. **Pragmatisch**: Pagination-UI fuer `/objects` ist v1-MVP (kein expliziter UI-Widget, nur `?page=`-Deeplinks); fuer `/admin/review-queue` haengt eine Mini-Page-Navigation an (`<< 1 2 3 >>`).

2. **Request-scoped Cache-Lifetime** — `accessible_object_ids` und `sidebar_workflows` werden pro Request mehrfach gerufen (object_detail-Route 8+ mal). Cache-Mechanik via FastAPI `Depends`-Memoization mit `lru_cache` ist wegen `Session`-Argument ohne hash NICHT trivial. **Loesung**: Caching am `Request.state` (`request.state._accessible_object_ids` lazy-init beim ersten Aufruf, danach Reuse). Lebensdauer ist exakt der Request — keine Cross-Request-Leakage. Fuer den Helper, der nicht das Request-Objekt sieht (`accessible_object_ids(db, user)`), neue Wrapper-Variante `accessible_object_ids_for_request(request, db, user)` einfuehren; Callsites umstellen, alte Signatur als Fallback fuer Calls ohne Request belassen.

3. **`get_provenance_map` 3-fach im `object_detail`** — heute drei separate Aufrufe (Z. 203 Stammdaten, Z. 214 Finanzen, Z. 307 Technik, Z. 331 Zugangscodes — eigentlich vier). Jeder Aufruf macht einen eigenen SQL-Hit + LEFT JOIN auf User. **Pragmatisch**: einen einzigen `get_provenance_map(db, "object", obj.id, ALL_FIELDS_FOR_DETAIL)`-Aufruf am Anfang, danach pro-Sektion-Slice via Dict-Lookup. **Risiko**: ALL_FIELDS_FOR_DETAIL ist eine grosse Liste (40+ Feldnamen) — der `IN (...)`-Filter wird breiter, aber genau ein einziger DB-Roundtrip. Empirisch (Statement-Count-Test in `tests/test_steckbrief_routes_smoke.py:458`) sollte das die Statement-Anzahl von ~21 auf ~18 druecken.

4. **Composite-Index auf `field_provenance`** — heute existieren drei separate Indexe (`ix_field_provenance_entity_field` auf `(entity_type, entity_id, field_name)`, `ix_field_provenance_user_id`, `ix_field_provenance_created_at`). Der `get_provenance_map`-Query macht `WHERE entity_type=... AND entity_id=... AND field_name IN (...) ORDER BY created_at DESC, id DESC`. Postgres kann den existing Index `(entity_type, entity_id, field_name)` fuer den `WHERE` nutzen, muss aber sortieren in-memory. **Loesung**: neuer Index `(entity_type, entity_id, field_name, created_at DESC, id DESC)` als Covering-Index → der Query laeuft als reiner Index-Scan ohne extra Sort. **Risiko**: Index ist groesser (~+30 % Disk fuer die Tabelle), bei `field_provenance`-Tabellengroesse 0.1 MB heute zu vernachlaessigen. Doku in der Migration. **SQLite-Test-Caveat**: SQLite ignoriert `DESC` im Index-Statement teilweise, aber das Verhalten ist fuer Tests irrelevant (kein Performance-Assertion).

5. **`get_provenance_map` Python-side group-by** — heute laedt der Query alle Rows (potentiell N pro Feld bei vielen Edits) und nimmt in Python die erste pro Feld (Sort+Skip). **Loesung**: Postgres-`DISTINCT ON (field_name)` mit Subquery — laedt nur die latest Row pro Feld, kein Python-Group-By. **SQLite-Fallback**: SQLite kennt kein `DISTINCT ON`. Helper macht `dialect.name == "postgresql"`-Check und dispatcht: Postgres → `DISTINCT ON`, SQLite → existing-Logik (laden + Python-Group-By). Pattern analog zu `pg_insert(...).on_conflict_do_nothing()` aus 5-2 AC1.

6. **`last_known_balance`-Skip-on-equal-value** — heute schreibt `object_detail` (Z. 260) bei jedem Page-Load eine `write_field_human(..., source="impower_mirror", ...)`-Provenance, auch wenn der Wert sich nicht geaendert hat. Bei zwei concurrent Page-Loads: zwei identische Provenance-Rows. **Loesung**: vor `write_field_human` pruefen, ob `obj.last_known_balance == live_balance` UND `obj.impower_balance_at` (oder `_updated_at`-Aequivalent, falls vorhanden) frischer als 60s ist. Nur dann skippen. Wenn der Wert sich aendert oder der letzte Write > 60s alt ist, ganz normal schreiben. **Reicht zur Behebung von #112** ohne UNIQUE-Constraint-Migration (waere theoretisch sauberer, aber `(entity_id, field_name, created_at)` als UNIQUE-Constraint wuerde legitime Re-Writes nach Jahren blocken — falsche Form).

7. **`SteckbriefPhoto`-Idempotenz #133** — out-of-scope fuer 5-4 als Code-Aenderung (Defer-Doku selbst markiert es als "vor Bulk-Upload-Feature dedup ueber Constraint oder DB-seitige Checks ergaenzen", aktuell nicht akut). **Diese Story dokumentiert** den Status: keine Bulk-Upload-UI, manuelle Einzel-Uploads sind durch die Foto-Upload-Saga (5-2 AC6) hinreichend serialisiert. Wenn Bulk-Upload kommt, wird `(object_id, component_ref, filename, captured_at)` als UNIQUE-Constraint angelegt — Memo, kein Code in 5-4. Defer-Eintrag #133 wird mit `[deferred-to-bulk-upload-story]`-Tag markiert.

8. **HTMX-401-vs-302** — heute liefern Routes hinter `Depends(get_current_user)` einen 302-Redirect auf `/login`, wenn die Session abgelaufen ist. HTMX folgt dem 302 stillschweigend, der Browser bekommt das Login-HTML in einen Page-Fragment-Slot eingehaengt → User sieht das gesamte Login-Form als Fragment. **Loesung**: in der `get_current_user`-Dependency oder im 302-Pfad pruefen, ob `HX-Request: true`-Header gesetzt ist; wenn ja, antworten mit 401 + `HX-Redirect: /login`-Header. HTMX folgt dem `HX-Redirect`-Pattern als Voll-Redirect. **Wo genau einhaengen**: in `app/auth.py` (oder wo immer die User-Dependency lebt) — Dev-Agent grept `def get_current_user\|RedirectResponse.*login`. Siehe Memory `feedback_default_user_role.md` — irrelevant fuer den Status, aber Auth-Disziplin generell.

9. **Semaphore fuer `list_conferences_with_properties`** — heute fuert der Helper `len(conferences)`-viele parallele `_api_get`-Calls (Z. 244-249). Bei 30 Conferences harmlos (~1s, Spec-bestaetigt), bei 200 Conferences wuerde Facilioo/Connection-Pool stressen. **Loesung**: `asyncio.Semaphore(10)` als Helper-konstante, in der List-Comprehension `async with sem:`-gewrappt. **Risiko**: Latenz steigt bei kleinen N nicht messbar (10 parallele >> 30 Calls), bei grossen N wird der Fanout serialisiert auf 10er-Chunks. **Wo einhaengen**: konstant `_PROPERTY_LOOKUP_CONCURRENCY = 10` als Modul-Konstante in `app/services/facilioo.py`. Pattern wiederverwendbar fuer kuenftige Fanouts.

10. **Pflegegrad Cache-Hit-Shortcut** — heute ruft `get_or_update_pflegegrad_cache` (Z. 213 in `pflegegrad.py`) **immer** `pflegegrad_score(obj, db)` auf, auch wenn der Cache frisch ist (4 Queries pro Detail-Aufruf). **Loesung**: zuerst Cache-Frische pruefen; wenn frisch → `PflegegradResult` aus dem DB-cache plus eine separate, billigere Berechnung von `weakest_fields` und `per_cluster` (oder `weakest_fields=[], per_cluster={}` wenn nicht im Cache, weil Story 3.4 nur den Score in DB hat). **Prgmatisch**: bei Cache-Hit nur `score` aus DB lesen, `weakest_fields=[]` und `per_cluster={}` zurueck — die Detail-Page-Render-Pfade tolerieren das (siehe Story 3.4 weakest_fields-Filter, `if pflegegrad_result.weakest_fields:` rendert eh nur, wenn nicht leer). **Compromise zu Defer #42** (Cache nur Score, nicht per_cluster/weakest_fields): wir caching nicht ueber JSONB, sondern nur den Score — Cache-Hit-Pfad liefert leere `per_cluster`/`weakest_fields`, Cache-Miss-Pfad liefert die volle Berechnung. **Akzeptierte Restschuld**: bei jeder Detail-Page-mit-frischem-Cache fehlt das Komposition-Popover-Detail, bis der Cache stale wird (TTL `CACHE_TTL`). Das ist schmerzhaft fuer die UX, deshalb **alternative Loesung**: JSONB-Erweiterung in `obj.pflegegrad_cluster_cached` (neue Spalte, Story 3.4-Defer-Item #42). **Entscheidung fuer 5-4**: kein Schema-Change — bei Cache-Hit ruft die Story trotzdem `pflegegrad_score()` (4 Queries), aber der UPDATE entfaellt (existing-Verhalten). **Wirkliche Optimierung in 5-4**: nur den `pflegegrad_score()`-Call selbst billiger machen (nutzt schon den existing `get_provenance_map`-Sweep aus AC5). Damit ist #37 als "Cache-Hit nutzt den bereits geladenen prov_map mit, kein doppelter Hit" geloest — das ist die ehrliche, verhaltens-konsistente Auflösung.

11. **`sidebar_workflows`-Caching am `Request.state`** — heute oeffnet `app/templating.py:48` pro Page-Render eine eigene `SessionLocal()`. **Loesung**: Helper `sidebar_workflows(user)` pruefen, ob `_g_request.state._sidebar_workflows` gesetzt ist; wenn ja, returnt cached. Aber: das Jinja-Template-Global hat keinen direkten Zugriff auf `Request`. **Loesung**: Templating-Wiring umstellen — der Helper wird nicht als `templates.env.globals["sidebar_workflows"] = sidebar_workflows` registriert, sondern als per-Request-Context-Var via `templates.TemplateResponse(request, ..., {"sidebar_workflows": sidebar_workflows_for_request(request, user)})`. **Pragmatisch alternativer Ansatz**: in `sidebar_workflows(user)` einen Process-weit-cached-Dict mit `(user_id, last_workflow_change_ts)` als Key — **Cache-Invalidation** ist aber nicht-trivial (Workflow-Aenderungen muessten den Cache stempeln). **Entscheidung fuer 5-4**: ein **In-Process-LRU-Cache** mit kurzer TTL (`functools.lru_cache` reicht nicht wegen `User`-Hashing → eigener Dict mit `time.monotonic()`-Stempel und `_TTL=30s`). Bei Workflow-Aenderungen wird der Cache nicht invalidiert, aber max 30s stale — der User klickt eh nicht alle 30s in den Workflow-Settings. **Alternative**: Cache am `Request.state` (eindeutig per-Request-frisch, aber jeder Request macht den DB-Hit). Wir nehmen die TTL-Variante, weil sie auch ueber Multi-Render-Pfade in derselben Request hinaus greift (z. B. `htmx-fragment + base.html` bei `hx-boost`).

## Deferred-Work-Coverage

| # | Eintrag | Severity | AC | Datei (verifiziert in dieser Session) |
|---|---------|----------|-----|---------------------------------------|
| 11 | Pagination Review-Queue | medium | AC1 | `app/routers/admin.py:1067-1085` (`_build_queue_query`), `:1107-1130`, `:1163-1184` |
| 26 | `sidebar_workflows` oeffnet eigene SessionLocal pro Render | medium | AC3 | `app/templating.py:48-73` |
| 31 | `list_conferences_with_properties` fanout ohne Semaphore | medium | AC7 | `app/services/facilioo.py:232-274` |
| 33 | Phase-2 gather killed PDF on single VG failure | medium | AC10 (out-of-scope) | `app/services/facilioo.py:425-445` (verifiziert via 5-3 References) |
| 37 | Cache-Hit-Pfad berechnet trotzdem alles neu | low | AC6 | `app/services/pflegegrad.py:213-232` |
| 55 | Keine Pagination in `/objects` und `/objects/rows` | medium | AC2 | `app/routers/objects.py:188`, `/objects/rows`-Variante (grep noetig) |
| 57 | `accessible_object_ids` pro Request neu berechnet | medium | AC4 | `app/permissions.py:258-271`, ~25 Caller in `app/routers/objects.py` und `app/routers/due_radar.py` |
| 99 | Combined-Index `field_provenance` ORDER BY Coverage | medium | AC5 | `migrations/versions/0011_steckbrief_governance.py:60-72`, neuer Index in `0020_perf_indexes.py` |
| 104 | `get_provenance_map` laedt alle Rows + pickt in Python | medium | AC5 | `app/services/steckbrief.py:228-265` |
| 106 | `accessible_object_ids` laedt alle Object.ids pro Request | medium | AC4 | siehe #57 (Duplikat) |
| 112 | Concurrent Page-Loads doppelte FieldProvenance-Rows | medium | AC8 | `app/routers/objects.py:260-269` (`last_known_balance`-Schreibung) |
| 120 | `get_provenance_map` dreifach SQL-Hit in `object_detail` | medium | AC5 | `app/routers/objects.py:203, 214, 307, 331` |
| 125 | HTMX-Requests bei abgelaufener Session 302 statt 401 | medium | AC9 | `app/auth.py` (oder zentrale User-Dependency, grep `def get_current_user` / `RedirectResponse.*login`) |
| 133 | Concurrent Page-Loads doppelte `SteckbriefPhoto`-Rows | medium | AC10 (out-of-scope, dokumentiert) | `app/routers/objects.py:889, 919` (Photo-Insert-Pfade) |

## Acceptance Criteria

**AC1 — Pagination `/admin/review-queue` + `/admin/review-queue/rows`**

**Given** ein Admin oeffnet `/admin/review-queue` bei wachsender Queue (z. B. 250 Pending-Entries)
**When** der Handler `list_review_queue` (`app/routers/admin.py:1107`) bzw. `list_review_queue_rows` (`:1163`) den Query baut
**Then** akzeptiert der Handler zwei zusaetzliche Query-Params: `page: int = Query(1, ge=1, le=10000)` und `page_size: int = Query(50, ge=1, le=200)`
**And** `_build_queue_query` (`:1067`) bleibt unveraendert; **nach** dem `_build_queue_query` wird `q.offset((page - 1) * page_size).limit(page_size)` angewendet
**And** ein zusaetzlicher Count-Query `total_count = db.execute(select(func.count()).select_from(_build_queue_query(db, ...).subquery())).scalar_one()` liefert die Gesamtzahl fuer die Pagination-UI
**And** das Template `admin/review_queue.html` rendert eine Mini-Page-Navigation `<< 1 2 ... N >>` unter der Tabelle, **nur** wenn `total_count > page_size`
**And** der Handler reicht `total_count`, `current_page`, `page_size` an das Template weiter
**And** das Filter-Form behaelt seine existierenden Inputs (`min_age_days`, `field_name`, `assigned_to_user_id`) und gibt `page_size` als Hidden-Input weiter — Filter-Aenderungen resetten `page` auf `1` (Default-Verhalten via Query-Param-Auslassen)
**And** existing Tests in `tests/test_review_queue_routes_smoke.py` bleiben gruen (Default `page_size=50` ist > 0 Entries in Test-DB; Tests rufen die Route ohne Pagination-Params auf)
**And** zwei neue Tests: `test_review_queue_paginates_50_per_page_default` (200 Pending-Entries seeden, Default-Aufruf liefert 50 Eintraege + Pagination-UI im HTML) und `test_review_queue_page_size_param` (Aufruf mit `?page_size=10` liefert 10 Eintraege)

**AC2 — Pagination `/objects` + `/objects/rows`**

**Given** ein User mit `objects:view` oeffnet `/objects` bei wachsendem Portfolio (z. B. 250 Objekte)
**When** der Handler `list_objects` und `objects_rows` (Dev-Agent grept `@router.get("/", \|/rows`-Routes in `app/routers/objects.py`) den Query baut
**Then** akzeptieren beide Handler zusaetzliche Query-Params `page: int = Query(1, ge=1, le=10000)` und `page_size: int = Query(50, ge=1, le=200)` analog zu AC1
**And** der Sort/Filter-Vertrag aus Story 3.1 (`?sort=`, `?order=`, `?filter_reserve=`) bleibt unveraendert; `?page` ist additiv
**And** ein `total_count`-Query laeuft gegen die selbe Filter-Klause vor dem `LIMIT`/`OFFSET`
**And** das Template `objects_list.html` (Voll-Page) rendert eine Mini-Page-Navigation unter der Tabelle (Pattern analog AC1) — und der Mobile-Card-Block (Story 3.2) rendert dieselbe Navigation am Block-Ende
**And** das Fragment `_obj_table_body.html` und `objects_list.html`-Mobile-Block bekommen `total_count`, `current_page`, `page_size` als Context-Vars
**And** **kein** `hx-push-url` fuer `?page=` in dieser Story (Defer #58 explizit out-of-scope, separate Story 5-5)
**And** existing Tests in `tests/test_steckbrief_routes_smoke.py` bleiben gruen (Default `page_size=50` schluckt alle Test-Objekte)
**And** zwei neue Tests analog AC1

**AC3 — `sidebar_workflows` mit TTL-Cache**

**Given** ein User laedt eine Page, die `base.html` rendert (= praktisch jede HTMX-Page)
**When** der Helper `sidebar_workflows(user)` in `app/templating.py:48` aufgerufen wird
**Then** prueft der Helper zuerst einen Modul-globalen `_SIDEBAR_WORKFLOWS_CACHE: dict[uuid.UUID, tuple[float, list[dict[str, Any]]]]`-Dict
**And** wenn `(user.id in cache) AND (time.monotonic() - cache[user.id][0] < _SIDEBAR_WORKFLOWS_TTL_SECONDS)` (Default `_SIDEBAR_WORKFLOWS_TTL_SECONDS = 30`), liefert der Helper `cache[user.id][1]` ohne neue DB-Session
**And** sonst laeuft der existing Pfad (SessionLocal + Query) und schreibt das Ergebnis in den Cache (`cache[user.id] = (time.monotonic(), items)`)
**And** der Cache wird **nicht** explicit invalidiert bei Workflow-Aenderungen (max 30s stale ist akzeptabel — User-Edits in `/admin/workflow-permissions` sehen die Sidebar erst nach Cache-Ablauf)
**And** das `try: ... finally: db.close()`-Pattern bleibt im DB-Pfad
**And** beim **Logout** werden alle Eintraege fuer den User entfernt: in `app/routers/auth.py` (oder `app/auth.py`) am Logout-Handler `_SIDEBAR_WORKFLOWS_CACHE.pop(user.id, None)` — Dev-Agent grept `def logout` und ergaenzt die Zeile
**And** Test: `test_sidebar_workflows_cached_within_ttl` — zwei Aufrufe binnen 1s mit demselben User: nur ein DB-Hit (Mock-Spy auf `SessionLocal` oder Query-Counter)
**And** Test: `test_sidebar_workflows_recomputes_after_ttl` — `monkeypatch.setattr(time, 'monotonic', ...)` simuliert TTL-Ablauf, zweiter Aufruf macht neuen DB-Hit

**AC4 — `accessible_object_ids` request-scoped Cache**

**Given** ein Detail-Page-Aufruf, der `accessible_object_ids(db, user)` mehrfach im selben Request ruft (heute 8+ Mal in `object_detail` ueber die diversen Sektionen via `_load_accessible_object`-Pattern; verifiziert in dieser Session: 19 Aufrufstellen in `app/routers/objects.py` plus 2 in `app/routers/due_radar.py`)
**When** der erste Aufruf passiert
**Then** wird das Result auf `request.state._accessible_object_ids` gespeichert; alle weiteren Aufrufe lesen aus dem State, kein neuer DB-Query
**And** **Implementation**: neue Wrapper-Funktion `accessible_object_ids_for_request(request: Request, db: Session, user: User) -> set[uuid.UUID]` in `app/permissions.py` direkt unter `accessible_object_ids` (Z. 258-271); Wrapper checkt `getattr(request.state, "_accessible_object_ids", None) is not None` → return; sonst `request.state._accessible_object_ids = accessible_object_ids(db, user)`; return
**And** **Migration der Callsites**: alle 21 Aufrufstellen in `app/routers/objects.py` und `app/routers/due_radar.py` werden auf den Wrapper umgestellt — Dev-Agent grept `accessible_object_ids(db, user)` und ersetzt durch `accessible_object_ids_for_request(request, db, user)`. Routes, die kein `Request`-Argument haben, **muessen** `request: Request` als FastAPI-Dependency hinzubekommen — der existing User-Dependency-Pattern reicht aus, das ist additiv
**And** der existing Helper `_load_accessible_object` (`app/routers/objects.py:1107`) ruft intern den Wrapper, nicht mehr den Original-Helper
**And** alte Funktion `accessible_object_ids` bleibt erhalten als Fallback (z. B. fuer Background-Tasks ohne Request-Kontext, Tests ohne Request-Kontext) — keine Deprecation in dieser Story
**And** Test: `test_accessible_object_ids_cached_per_request` — Statement-Count-Test: `object_detail`-Request macht 1 statt 8+ `SELECT object.id FROM object`-Queries
**And** Test: `test_accessible_object_ids_isolated_between_requests` — zwei sequentielle Requests, jeder macht den Query genau einmal (kein Cross-Request-Leak)

**AC5 — `get_provenance_map` 1-Roundtrip + Composite-Index + DISTINCT ON**

**Given** ein Detail-Page-Aufruf in `object_detail`
**When** der Handler heute `get_provenance_map` viermal aufruft (Stammdaten Z. 203, Finanzen Z. 214, Technik Z. 307, Zugangscodes Z. 331)
**Then** wird ein neuer Helper `get_provenance_map_bulk(db, "object", obj.id)` in `app/services/steckbrief.py` direkt unter der existing-Variante eingefuehrt, der **alle** Provenance-Felder fuer das Objekt in einem einzigen SQL-Roundtrip laedt (kein `field_name IN (...)`-Filter — alle Rows fuer das `(entity_type, entity_id)`-Paar)
**And** Returntyp ist `dict[str, ProvenanceWithUser | None]` mit allen vorhandenen Feldnamen als Keys; Caller fragen via `bulk_map.get("field_name")` ihre Feld-Liste ab — fehlende Felder geben `None` (gleiche Semantik wie heute)
**And** der Handler `object_detail` ruft den Bulk-Helper genau **einmal** am Anfang (nach `_load_accessible_object`-Block, vor Z. 203) und reicht das Result als `prov_map` durch alle Sektionen — die existing 4 Aufrufe von `get_provenance_map` werden durch `prov_map`-Slices ersetzt:
  - Z. 203 (Stammdaten) → `{f: prov_map.get(f) for f in (...stammdaten-fields...)}` oder direkter Pass
  - Z. 214 (Finanzen) → `{f: prov_map.get(f) for f in (...finanz-fields...)}`
  - Z. 307 (Technik) → `tech_prov_map = {f.key: prov_map.get(f.key) for f in TECHNIK_FIELDS}`
  - Z. 331 (Zugangscodes) → `zug_prov_map = {f: prov_map.get(f) for f in (...zugangscode-fields...)}`
**And** Statement-Count-Test (`tests/test_steckbrief_routes_smoke.py:458`): die Obergrenze `<= 21` wird auf `<= 18` gesenkt (3 Queries weniger durch die 4→1 Konsolidierung)

**Given** der `get_provenance_map`-Bulk-Query laeuft heute mit `ORDER BY created_at DESC, id DESC` und liest **alle** Rows (potentiell N pro Feld bei vielen Edits)
**When** der Postgres-Query-Plan analysiert wird
**Then** liefert eine neue Migration `0020_perf_indexes.py` einen Composite-Index `ix_field_provenance_entity_field_created` auf `(entity_type, entity_id, field_name, created_at DESC, id DESC)` (siehe Risiko 4)
**And** die Migration bringt zusaetzlich `op.create_index(..., postgresql_using="btree", postgresql_ops={"created_at": "DESC", "id": "DESC"})` — fuer SQLite-Tests reicht der Default-`btree`-Pfad ohne DESC-Hint (SQLite ignoriert ihn)
**And** **kein** Drop des existing `ix_field_provenance_entity_field` — er bleibt fuer Queries ohne ORDER BY (z. B. `has_any_impower_provenance`); der neue Index ist additiv
**And** die Migration ist reversibel (`def downgrade()` macht `op.drop_index("ix_field_provenance_entity_field_created")`)

**Given** der Helper `get_provenance_map_bulk` laeuft auf Postgres
**When** der Query gebaut wird
**Then** prueft der Helper `db.bind.dialect.name == "postgresql"`; wenn ja, baut er den Query mit `select(FieldProvenance).distinct(FieldProvenance.field_name).order_by(FieldProvenance.field_name, FieldProvenance.created_at.desc(), FieldProvenance.id.desc())` (= `DISTINCT ON (field_name)`)
**And** SQLite-Fallback: existing Logik (alle Rows laden + Python-Group-By); eingebaut als `else`-Branch
**And** beide Pfade liefern semantisch denselben `dict[str, ProvenanceWithUser | None]`-Result
**And** Test: `test_get_provenance_map_bulk_postgres_distinct_on` — Mock Postgres-Dialect, verifiziert dass das Statement `DISTINCT ON` enthaelt (statement-Introspection via `str(stmt.compile(...))`)
**And** Test: `test_get_provenance_map_bulk_sqlite_fallback` — Default-Test-DB (SQLite), funktioneller Test (Werte stimmen)

**AC6 — Pflegegrad Cache-Hit-Reuse des bulk prov_map**

**Given** der Handler `object_detail` hat in AC5 schon den `prov_map`-Bulk geladen
**When** `get_or_update_pflegegrad_cache(detail.obj, db)` aufgerufen wird
**Then** uebernimmt die Funktion einen optionalen `prov_map: dict | None = None`-Parameter und reicht ihn an `pflegegrad_score(obj, db, prov_map=prov_map)` weiter
**And** `pflegegrad_score` (`app/services/pflegegrad.py`, der `_scalar_effective`-Helper) nutzt das `prov_map` als Cache, **bevor** ein eigener `get_provenance_map`-Aufruf passiert — wenn `prov_map` nicht None und das Feld dort enthalten, kein neuer DB-Hit fuer das Feld
**And** wenn `prov_map=None` (bei Aufrufern ohne Bulk-Vorladung — z. B. List-View, Background-Jobs), bleibt das existing Verhalten (eigene Aufrufe pro Feld)
**And** der Cache-Hit-Pfad (`is_stale=False`) macht **keinen** zusaetzlichen Score-Recompute mehr nutzen (existing Verhalten von 5-3 AC2 + dieser Optimierung kombiniert): `pflegegrad_score()` laeuft, aber alle Provenance-Reads kommen aus `prov_map` ohne SQL
**And** Statement-Count: bei Cache-Hit-mit-prov_map laufen **0** zusaetzliche Provenance-Queries (vorher: 4 Queries fuer die 4 Cluster-Lookups)
**And** Test: `test_pflegegrad_score_uses_prov_map_when_provided` — Mock-Spy auf `get_provenance_map`, mit `prov_map`-Argument: keine SQL-Calls; ohne `prov_map`-Argument: existing-Calls

**AC7 — `list_conferences_with_properties` Semaphore**

**Given** der ETV-PDF-Workflow ruft `list_conferences_with_properties()` und das WEG-Portfolio waechst auf 200+ Conferences
**When** der Helper in `app/services/facilioo.py:232` den Property-Lookup-Fanout startet (Z. 244-249)
**Then** wird die List-Comprehension `prop_tasks = [...]` durch eine Variante ersetzt, die jede Coroutine durch ein gemeinsames Semaphore wrappt
**And** Modul-Konstante `_PROPERTY_LOOKUP_CONCURRENCY = 10` direkt unter den existing `_MAX_PAGES`/`_PAGE_SIZE`-Konstanten
**And** Implementierung: lokal `sem = asyncio.Semaphore(_PROPERTY_LOOKUP_CONCURRENCY)`, dann `async def _bounded_get(c_id): async with sem: return await _api_get(client, f"/api/conferences/{c_id}/property", rate_gate=False)` als Inner-Helper, dann `prop_tasks = [_bounded_get(c["id"]) for c in conferences if c.get("id") is not None]`
**And** Pattern wiederverwendbar: der Inner-Helper bleibt lokal in der Funktion, aber `_PROPERTY_LOOKUP_CONCURRENCY` ist Modul-konstant — kuenftige Fanouts in `facilioo.py` koennen denselben Wert nutzen
**And** Test: `test_list_conferences_with_properties_respects_semaphore` — Mock `_api_get` mit `asyncio.sleep(0.01)`, 50 Conferences, verifiziert max-concurrent-Calls <= 10 (via Counter im Mock)
**And** existing Test fuer den Happy-Path (mit ~3 Conferences) bleibt gruen — Semaphore beeinflusst kleine N nicht messbar

**AC8 — `last_known_balance` Skip-on-equal-value**

**Given** zwei concurrent Page-Loads auf `object_detail` mit demselben `live_balance`-Wert
**When** der existing Block in `app/routers/objects.py:259-269` (`write_field_human` + `db.commit()`) erreicht wird
**Then** prueft der Handler **vor** `write_field_human`: `if obj.last_known_balance == live_balance: skip = True`
**And** **Implementierung**: `if detail.obj.last_known_balance is not None and detail.obj.last_known_balance == live_balance: pass` (kein Write, kein Commit) — `else: write_field_human(...) + db.commit()` wie heute
**And** der `try/except`-Block bleibt unveraendert um den Write-Pfad
**And** **kein** Time-Window-Check (60s) — Equal-Value-Skip ist hinreichend; bei ungleichem Wert wird ohnehin geschrieben
**And** Effekt: zwei concurrent Page-Loads mit demselben Saldo → genau **eine** Provenance-Row beim ersten Page-Load (oder gar keine, wenn der Mirror-Job aus Story 1.4 schon gelaufen ist), die zweite Page-Load skippt; vorher wuerden zwei identische Provenance-Rows geschrieben
**And** Test: `test_object_detail_skips_balance_write_when_equal` — Setup: `obj.last_known_balance = Decimal("1500.00")` und Mock `get_bank_balance` returnt `1500.00`; Aufruf der Detail-Page; verifiziert keine neue `FieldProvenance`-Row mit `field_name="last_known_balance"`, `created_at >= test_start_ts`
**And** Test: `test_object_detail_writes_balance_when_changed` — Setup: `obj.last_known_balance = Decimal("1500.00")` und Mock returnt `1600.00`; verifiziert genau eine neue `FieldProvenance`-Row

**AC9 — HTMX-Session-Expired liefert 401 statt 302**

**Given** ein User mit abgelaufener Session feuert einen HTMX-Request (Header `HX-Request: true`) gegen eine geschuetzte Route
**When** die User-Dependency in `app/auth.py` (Dev-Agent grept `def get_current_user\|RedirectResponse.*login` als Anker) erkennt, dass kein gueltiger User in der Session ist
**Then** prueft die Dependency `request.headers.get("HX-Request") == "true"`; wenn ja, wirft sie eine `HTTPException(status_code=401, headers={"HX-Redirect": "/login"})`
**And** sonst (kein HX-Request) bleibt das existing 302-Redirect-Verhalten
**And** das Frontend (HTMX 2.0) interpretiert den `HX-Redirect`-Header automatisch als Voll-Page-Redirect — der User landet auf `/login`, nicht das Login-Form-Fragment im aktuellen Page-Slot
**And** Test: `test_htmx_request_expired_session_returns_401_with_hx_redirect_header` — Request mit `HX-Request: true` ohne Session-Cookie → 401 + `HX-Redirect: /login` im Response-Header
**And** Test: `test_non_htmx_request_expired_session_redirects_302` — Request ohne `HX-Request`-Header ohne Session-Cookie → 302 zu `/login` (existing Verhalten, Sanity)

**AC10 — Out-of-scope Items dokumentiert**

**Given** Defer #33 (Phase-2-Aggregator fail-loud) und Defer #133 (`SteckbriefPhoto`-Concurrent-Insert)
**When** Story 5-4 abgeschlossen ist
**Then** existieren zwei konkrete Spuren:
  - **#33**: in `output/implementation-artifacts/deferred-work.md` Eintrag #33 wird mit `[deferred-fail-loud-by-design]`-Tag erweitert plus Begruendung "Story 5-3 hat Phase-1+Phase-2 explizit fail-loud belassen (juristisches Risiko bei unvollstaendiger Vollmachts-Liste). 5-4 respektiert diese Entscheidung. Trigger fuer Reopen: UX-Feedback 'Facilioo flackert zu oft'."
  - **#133**: Eintrag #133 wird mit `[deferred-to-bulk-upload-story]`-Tag erweitert plus Begruendung "Heute kein Bulk-Upload-UI; manuelle Einzel-Uploads sind durch die Foto-Upload-Saga (5-2 AC6) hinreichend serialisiert. Trigger fuer Reopen: Bulk-Upload-Feature-Story."
**And** in der Triage-Tabelle (Zeile 14-167 in `deferred-work.md`) wird Sprint-Target fuer #33 auf `post-prod-when-ux-feedback` aktualisiert; fuer #133 auf `post-prod-bulk-upload`
**And** Story 5-4 schreibt **keinen** Code in `app/services/facilioo.py` (Phase-2-Aggregator) und **keinen** Code in den Photo-Insert-Pfaden (`app/routers/objects.py:889, 919`) — nur Doku-Updates in `deferred-work.md`

## Tasks / Subtasks

- [x] **Task 1: Pagination `/admin/review-queue`** (AC1)
  - [x] 1.1 In `app/routers/admin.py:1107` (`list_review_queue`): zusaetzliche Query-Params `page: int = Query(1, ge=1, le=10000)` und `page_size: int = Query(50, ge=1, le=200)`
  - [x] 1.2 Nach `q = _build_queue_query(...)` (Z. 1116): `paginated_q = q.offset((page - 1) * page_size).limit(page_size)`; `total_count = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()`; `entries = _prepare_entries(db.execute(paginated_q).scalars().all())`
  - [x] 1.3 Template-Context erweitern um `total_count`, `current_page=page`, `page_size`
  - [x] 1.4 Identisch in `list_review_queue_rows` (Z. 1163) — selbe Params, selbe Pagination, Template-Context an `_review_queue_rows.html` reichen
  - [x] 1.5 In `app/templates/admin/review_queue.html` Mini-Page-Navigation `<< 1 2 ... N >>` unter der Tabelle, **nur** wenn `total_count > page_size` — Pattern: `{% if total_count > page_size %}<nav class='...'>...</nav>{% endif %}`. Hidden-Input `page_size` im Filter-Form, damit Filter-Aenderungen die Page-Size mitnehmen
  - [x] 1.6 Filter-Aenderungen (Form-Submit ueber HTMX) duerfen `page=1` setzen — durch Auslassen des `page`-Hidden-Inputs im Form (Default greift dann zu `page=1`)

- [x] **Task 2: Pagination `/objects` + `/objects/rows`** (AC2)
  - [x] 2.1 Dev-Agent grept `@router.get("/", \|@router.get("/rows"` in `app/routers/objects.py` und identifiziert die zwei Routes (Voll-Page + HTMX-Rows-Fragment)
  - [x] 2.2 Beiden Routes `page` + `page_size` Query-Params hinzufuegen (analog AC1)
  - [x] 2.3 Sort/Filter-Logik aus Story 3.1 bleibt unveraendert — Pagination wird **nach** dem Filter angewendet
  - [x] 2.4 `total_count` Query analog AC1
  - [x] 2.5 Template-Erweiterungen in `objects_list.html` (Voll-Page + Mobile-Block) und `_obj_table_body.html` (Rows-Fragment) — Pagination-Markup analog AC1
  - [x] 2.6 **Kein** `hx-push-url` fuer `?page=` (Defer #58 separat in 5-5)
  - [x] 2.7 Mobile-Block-Pagination muss dasselbe `page`/`page_size` mitfuehren

- [x] **Task 3: `sidebar_workflows` TTL-Cache** (AC3)
  - [x] 3.1 In `app/templating.py` direkt unter `sidebar_workflows`-Funktion: Modul-Konstanten `_SIDEBAR_WORKFLOWS_CACHE: dict[uuid.UUID, tuple[float, list[dict[str, Any]]]] = {}` und `_SIDEBAR_WORKFLOWS_TTL_SECONDS = 30`
  - [x] 3.2 In `sidebar_workflows(user)` zuerst Cache-Lookup; Cache-Hit returnt cached, Cache-Miss laeuft existing Pfad und schreibt cache
  - [x] 3.3 Logout-Hook: Dev-Agent grept `def logout` in `app/routers/auth.py` (oder `app/auth.py`) und fuegt `from app.templating import _SIDEBAR_WORKFLOWS_CACHE; _SIDEBAR_WORKFLOWS_CACHE.pop(user.id, None)` ein
  - [x] 3.4 Tests: TTL-Hit + TTL-Miss + Logout-Invalidation

- [x] **Task 4: `accessible_object_ids` request-scoped Cache** (AC4)
  - [x] 4.1 In `app/permissions.py` direkt unter `accessible_object_ids` (Z. 271) neue Wrapper-Funktion `accessible_object_ids_for_request(request: Request, db: Session, user: User) -> set[uuid.UUID]` — mit `getattr(request.state, "_accessible_object_ids", None)`-Check
  - [x] 4.2 Import `Request` aus `fastapi` in `app/permissions.py` hinzufuegen
  - [x] 4.3 Dev-Agent grept `accessible_object_ids(db, user)` projektweit (Erwartung: 21 Treffer in `app/routers/objects.py` und `app/routers/due_radar.py`) und ersetzt durch `accessible_object_ids_for_request(request, db, user)` — pro Treffer pruefen, ob die Route `request: Request`-Param hat; wenn nicht, hinzufuegen
  - [x] 4.4 `_load_accessible_object` (`app/routers/objects.py:1107`) intern auf den Wrapper umstellen — Signatur erweitern um `request`
  - [x] 4.5 Tests: Statement-Count-Reduktion + Cross-Request-Isolation

- [x] **Task 5: `get_provenance_map` Bulk + Composite-Index + DISTINCT ON** (AC5)
  - [x] 5.1 Vor Migration: `ls migrations/versions/` ausfuehren (Memory `feedback_migrations_check_existing.md`); naechste freie Nummer feststellen — nominell `0020`, falls belegt: hochzaehlen
  - [x] 5.2 Neue Migration `migrations/versions/0020_perf_indexes.py` mit `down_revision = "0019_police_column_length_caps"` (oder aktueller Head). Inhalt:
    - `op.create_index("ix_field_provenance_entity_field_created", "field_provenance", ["entity_type", "entity_id", "field_name", sa.text("created_at DESC"), sa.text("id DESC")])`
    - `def downgrade(): op.drop_index("ix_field_provenance_entity_field_created", table_name="field_provenance")`
  - [x] 5.3 In `app/services/steckbrief.py` direkt unter `get_provenance_map` (nach Z. 265) neue Funktion `get_provenance_map_bulk(db: Session, entity_type: str, entity_id: uuid.UUID) -> dict[str, ProvenanceWithUser | None]` — laedt **alle** Provenance-Rows fuer das `(entity_type, entity_id)`-Paar in einem Roundtrip; dialect-check `db.bind.dialect.name == "postgresql"` → DISTINCT ON-Pfad; SQLite-Fallback nutzt existing-Logik (Group-By in Python)
  - [x] 5.4 In `app/routers/objects.py:object_detail` (Handler ab Z. 188): vor Z. 203 ein einzelner `prov_map = get_provenance_map_bulk(db, "object", obj.id)`-Aufruf
  - [x] 5.5 Z. 203 (Stammdaten-Aufruf) durch Pass-Through ersetzen: `stamm_prov_map = {f: prov_map.get(f) for f in (...stammdaten-fields...)}` ODER, falls die Aufruf-Signatur einfacher bleibt, weiter `get_provenance_map(...)` rufen — ABER der Bulk-Call erspart den Roundtrip, deshalb auf Slice umstellen
  - [x] 5.6 Z. 214 (Finanz), Z. 307 (Technik), Z. 331 (Zugangscodes) analog auf `prov_map`-Slice umstellen
  - [x] 5.7 In `tests/test_steckbrief_routes_smoke.py:458` Statement-Count-Threshold von `<= 21` auf `<= 18` senken (3 Queries weniger durch die 4→1 Konsolidierung)
  - [x] 5.8 Tests: `test_get_provenance_map_bulk_postgres_distinct_on` (Mock-Dialect) + `test_get_provenance_map_bulk_sqlite_fallback` (Default-Test-DB)

- [x] **Task 6: Pflegegrad-Score reuse `prov_map`** (AC6)
  - [x] 6.1 In `app/services/pflegegrad.py:pflegegrad_score`-Funktion: optionalen Parameter `prov_map: dict[str, ProvenanceWithUser | None] | None = None` ergaenzen
  - [x] 6.2 In `_scalar_effective`-Helper (oder vergleichbarer Inner-Helper): wenn `prov_map` nicht None und Feld dort drin → keinen `get_provenance_map`-Aufruf, nutzen
  - [x] 6.3 In `get_or_update_pflegegrad_cache(obj, db, prov_map=None)`: `prov_map`-Parameter durchreichen
  - [x] 6.4 In `app/routers/objects.py:object_detail` Z. 285: `pflegegrad_result, cache_updated = get_or_update_pflegegrad_cache(detail.obj, db, prov_map=prov_map)` — `prov_map` aus Task 5.4
  - [x] 6.5 Test: `test_pflegegrad_score_uses_prov_map_when_provided` — Mock-Spy

- [x] **Task 7: `list_conferences_with_properties` Semaphore** (AC7)
  - [x] 7.1 In `app/services/facilioo.py` direkt unter den existing `_MAX_PAGES`/`_PAGE_SIZE`-Konstanten (Top-of-File): `_PROPERTY_LOOKUP_CONCURRENCY = 10`
  - [x] 7.2 In `list_conferences_with_properties` (Z. 232) den Fanout (Z. 244-249) durch eine Semaphore-gewrappte Variante ersetzen — Inner-Helper `_bounded_get` lokal in der Funktion
  - [x] 7.3 Test: `test_list_conferences_with_properties_respects_semaphore` — verifiziert max-concurrent <= 10

- [x] **Task 8: `last_known_balance` Skip-on-equal-value** (AC8)
  - [x] 8.1 In `app/routers/objects.py:259` (vor `write_field_human`): `if detail.obj.last_known_balance is not None and detail.obj.last_known_balance == live_balance: pass` (kein Write)
  - [x] 8.2 `else:` Branch um den existing `try: write_field_human ... except ...` (= existing Verhalten)
  - [x] 8.3 Tests: Skip + Write-on-Change

- [x] **Task 9: HTMX-Session-Expired 401** (AC9)
  - [x] 9.1 Dev-Agent grept `def get_current_user\|RedirectResponse.*login` in `app/auth.py` (oder zentralem User-Dep), identifiziert den 302-Pfad
  - [x] 9.2 Vor dem `RedirectResponse(...)` (oder `raise HTTPException(...)` zum Redirect-Pfad): `if request.headers.get("HX-Request") == "true": raise HTTPException(status_code=401, headers={"HX-Redirect": "/login"})`
  - [x] 9.3 `request: Request`-Argument muss in der Dependency-Signatur sein; FastAPI liefert es als `request: Request`-Dependency automatisch — Dev-Agent passt die Signatur an, falls noch nicht vorhanden
  - [x] 9.4 Tests: HTMX-Request expired → 401 + `HX-Redirect`-Header; Non-HTMX → 302 (existing)

- [x] **Task 10: Out-of-scope Items dokumentieren** (AC10)
  - [x] 10.1 In `output/implementation-artifacts/deferred-work.md` Eintrag #33 mit `[deferred-fail-loud-by-design]`-Tag und Begruendung erweitern; Sprint-Target auf `post-prod-when-ux-feedback` aktualisieren
  - [x] 10.2 Eintrag #133 mit `[deferred-to-bulk-upload-story]`-Tag und Begruendung erweitern; Sprint-Target auf `post-prod-bulk-upload` aktualisieren
  - [x] 10.3 Aggregierte-Counts-Block (Z. 169-177) auf den neuen Stand aktualisieren (3 zusaetzliche `[deferred-to-...]`-Tags)

- [x] **Task 11: Tests** (alle ACs)
  - [x] 11.1 Neue Datei `tests/test_performance_query_optimization.py` mit den unter Tests gelisteten Cases
  - [x] 11.2 `pytest tests/test_performance_query_optimization.py -v` muss komplett gruen sein
  - [x] 11.3 Bestaetigen, dass die existing Test-Suite (`pytest tests/ -v`) nicht regrediert ist — insbesondere `tests/test_steckbrief_routes_smoke.py` (Statement-Count-Threshold-Test) und `tests/test_review_queue_routes_smoke.py`

- [x] **Task 12: Rollout-Verifikation lokal**
  - [x] 12.1 `./scripts/env.sh && docker compose up --build` — App startet, Migration `0020` laeuft sauber (in Docker-Logs `Running upgrade 0019_police_column_length_caps -> 0020_perf_indexes`)
  - [x] 12.2 Manueller Smoke-Test: `/admin/review-queue` mit 0 Pending-Entries → 200, keine Pagination-UI sichtbar (`total_count <= page_size`); per `?page_size=1` mit 0 Entries → keine Pagination, weil `total_count = 0`
  - [x] 12.3 Manueller Smoke-Test: `/objects` Voll-Page laden → Performance subjektiv unveraendert (Default `page_size=50` bei < 50 Test-Objekten = same as before)
  - [x] 12.4 Manueller Smoke-Test: HTMX-Action mit abgelaufener Session → Voll-Redirect zu `/login` (kein Login-Form-Fragment in der Page)

## Tests

In `tests/test_performance_query_optimization.py`:

**Pagination Review-Queue (AC1):**
- `test_review_queue_paginates_50_per_page_default` — 200 Pending-Entries seeden, Default-Aufruf liefert 50 Eintraege, HTML enthaelt Pagination-Markup
- `test_review_queue_page_size_param` — Aufruf mit `?page_size=10` liefert 10 Eintraege
- `test_review_queue_page_param` — Aufruf mit `?page=2&page_size=50` liefert Eintraege 51-100
- `test_review_queue_filter_resets_page` — Filter-Form-Submit mit `min_age_days=5` resetted Page auf 1 (Default)
- `test_review_queue_total_count_correct` — `total_count` im HTML = Anzahl gefilterter Pending-Entries

**Pagination /objects (AC2):**
- `test_objects_list_paginates_50_per_page_default` — 200 Objekte seeden
- `test_objects_list_page_size_param` — analog AC1
- `test_objects_rows_fragment_paginates` — HTMX-Rows-Fragment liefert paginiertes Subset
- `test_objects_list_pagination_with_sort` — `?sort=name&order=asc&page=2` liefert 2. Page der sortierten Liste

**sidebar_workflows TTL-Cache (AC3):**
- `test_sidebar_workflows_cached_within_ttl` — zwei Aufrufe binnen 1s, ein DB-Hit
- `test_sidebar_workflows_recomputes_after_ttl` — `monkeypatch.setattr(time, 'monotonic', ...)`-TTL-Ablauf
- `test_sidebar_workflows_logout_invalidates_cache` — Logout-Aufruf entfernt User-Eintrag aus Cache

**accessible_object_ids request-scoped (AC4):**
- `test_accessible_object_ids_cached_per_request` — Statement-Count-Reduktion
- `test_accessible_object_ids_isolated_between_requests` — kein Cross-Request-Leak
- `test_accessible_object_ids_for_request_falls_back_when_state_missing` — Wrapper funktioniert auch ohne pre-existing State

**get_provenance_map_bulk (AC5):**
- `test_get_provenance_map_bulk_returns_all_fields_for_entity` — Bulk-Aufruf liefert dict mit allen Provenance-Feldern
- `test_get_provenance_map_bulk_postgres_distinct_on` — Mock-Dialect `postgresql`, statement-introspection
- `test_get_provenance_map_bulk_sqlite_fallback` — Default-Test-DB, Werte stimmen
- `test_object_detail_uses_single_provenance_query` — Statement-Count-Test gegen `object_detail`-Route, max 18 Statements

**Pflegegrad reuse prov_map (AC6):**
- `test_pflegegrad_score_uses_prov_map_when_provided` — Mock-Spy: keine `get_provenance_map`-Calls
- `test_pflegegrad_score_falls_back_when_prov_map_missing_field` — Field nicht in prov_map → existing-Aufruf-Pfad
- `test_pflegegrad_score_works_without_prov_map_argument` — Aufrufer ohne Bulk-Vorladung (List-View) bleibt funktional

**list_conferences_with_properties Semaphore (AC7):**
- `test_list_conferences_with_properties_respects_semaphore` — Mock `_api_get` mit `asyncio.sleep(0.01)`, 50 Conferences, max-concurrent <= 10
- `test_list_conferences_with_properties_happy_path_unchanged` — 3 Conferences, Default-Verhalten gleich wie vorher

**last_known_balance Skip-on-equal (AC8):**
- `test_object_detail_skips_balance_write_when_equal` — equal value → keine neue Provenance-Row
- `test_object_detail_writes_balance_when_changed` — different value → eine neue Provenance-Row
- `test_object_detail_writes_balance_when_initial_null` — `obj.last_known_balance is None` und Mock returnt Wert → Write passiert

**HTMX-401 (AC9):**
- `test_htmx_request_expired_session_returns_401_with_hx_redirect_header` — `HX-Request: true` ohne Session → 401 + HX-Redirect
- `test_non_htmx_request_expired_session_redirects_302` — kein HX-Request-Header ohne Session → 302 zu /login

**Out-of-scope Doku (AC10):**
- `test_deferred_work_marks_33_as_fail_loud_by_design` — `output/implementation-artifacts/deferred-work.md` enthaelt `[deferred-fail-loud-by-design]` an erwarteter Stelle
- `test_deferred_work_marks_133_as_bulk_upload_story` — analog `[deferred-to-bulk-upload-story]`

## Nicht-Scope

- **#33 (Phase-2-Aggregator fail-loud)** — siehe AC10. 5-3 hat das bewusst belassen, 5-4 respektiert das. Eigene Story bei UX-Feedback.
- **#133 (`SteckbriefPhoto`-Concurrent-Insert)** — siehe AC10. Heute kein Bulk-Upload-UI; manuelle Einzel-Uploads sind durch 5-2 AC6 hinreichend serialisiert. Eigene Story bei Bulk-Upload-Feature.
- **`hx-push-url` fuer Pagination-Bookmarking** (Defer #58) — UX-Polish, separat in Story 5-5.
- **`hx-indicator` fuer Loading-Feedback** (Defer #59) — UX-Polish, separat in 5-5.
- **JSONB-Cache-Erweiterung fuer `per_cluster`/`weakest_fields`** (Defer #42) — Schema-Change, eigene Story 3.4-Folge oder 5-7 Test-Coverage-Sprint. AC6 nutzt `prov_map`-Reuse als pragmatische Performance-Verbesserung ohne Schema-Aenderung.
- **`live_balance` Backoff/Circuit-Breaker** (Defer #35-Pattern-Pendant) — 5-3 hat den Pflegegrad-Cache-Pattern abgedeckt, `live_balance` bleibt mit `try/except + warning_log`. Echter Circuit-Breaker ist eigene Story.
- **HTMX-Toggle-Bug auf `/objects` Sort-Default** (Defer #62) — Spec-interner Widerspruch, separat in 5-5.
- **A11y-Sweep auf Sort-Headern** (Defer #56) — separater A11y-Sprint.
- **Pagination-UI mit `<<<` `>>>`-Iconen, Disabled-States, Active-Page-Highlight** — minimal-MVP-Markup in dieser Story (`<< 1 2 ... N >>` als Text-Links). UX-Polish in 5-5.
- **Multi-Worker-Cache-Sync fuer `_SIDEBAR_WORKFLOWS_CACHE`** — In-Process-LRU ist pro Worker isoliert; 30s-TTL deckt das ab. Wenn das je zum Schmerz wird, Memcache/Redis-Variante als eigene Story.

## Dev Notes

### File-Touch-Liste

**Neue Dateien:**
- `migrations/versions/0020_perf_indexes.py` — Composite-Index auf `field_provenance(entity_type, entity_id, field_name, created_at DESC, id DESC)`
- `tests/test_performance_query_optimization.py` — komplette Test-Suite

**Geaenderte Dateien:**
- `app/routers/admin.py:1107, 1116-1118, 1163, 1172-1174` — Pagination-Params + Count-Query in `list_review_queue` und `list_review_queue_rows`
- `app/templates/admin/review_queue.html` — Pagination-Markup unter Tabelle, Hidden-Input `page_size` im Filter-Form
- `app/templates/admin/_review_queue_rows.html` — keine direkten Aenderungen (Rows-Fragment, Pagination ist im Parent-Template)
- `app/routers/objects.py:188 ff. (`list_objects`), und `/objects/rows`-Variante` — Pagination-Params + Count-Query
- `app/templates/objects_list.html` und `app/templates/_obj_table_body.html` — Pagination-Markup in Voll-Page + Mobile-Block
- `app/templating.py:48-73` — `sidebar_workflows` mit TTL-Cache + Modul-Konstanten
- `app/routers/auth.py` (oder `app/auth.py` — Logout-Handler) — Cache-Invalidation `_SIDEBAR_WORKFLOWS_CACHE.pop(user.id, None)`
- `app/permissions.py:271 ff.` — neue Wrapper-Funktion `accessible_object_ids_for_request(request, db, user)`
- `app/routers/objects.py` (~21 Aufrufstellen) — Migration aller `accessible_object_ids(db, user)`-Calls auf den Wrapper; ggf. `request: Request`-Param ergaenzen
- `app/routers/due_radar.py:32-33, 51-58` — analog
- `app/routers/objects.py:1107` (`_load_accessible_object`-Helper) — auf Wrapper umstellen
- `app/services/steckbrief.py:265 ff.` — neue Funktion `get_provenance_map_bulk(db, entity_type, entity_id)`
- `app/routers/objects.py:188-340` (`object_detail`-Handler) — Bulk-Aufruf am Anfang, Slice-Pass-Through statt 4 separater `get_provenance_map`-Calls
- `app/services/pflegegrad.py:pflegegrad_score, get_or_update_pflegegrad_cache` — `prov_map`-Param durchreichen
- `app/services/facilioo.py:Top-of-File, 232-274` — `_PROPERTY_LOOKUP_CONCURRENCY=10`-Konstante + Semaphore-Wrap
- `app/routers/objects.py:259-269` — `last_known_balance` Skip-on-equal-value
- `app/auth.py` (oder zentrale User-Dep) — HTMX-Pfad-Check, `HTTPException(401, headers={"HX-Redirect": "/login"})`
- `tests/test_steckbrief_routes_smoke.py:458` — Statement-Count-Threshold von `<= 21` auf `<= 18` senken
- `output/implementation-artifacts/deferred-work.md` — #33 + #133 mit Tags und Sprint-Target-Update; Aggregierte-Counts (Z. 169-177) aktualisieren

### Memory-Referenzen (verbindlich beachten)

- `feedback_migrations_check_existing.md` — vor Anlage von `0020_perf_indexes.py` `ls migrations/versions/` ausfuehren; existing Heads pruefen
- `project_testing_strategy.md` — TestClient + Mocks; Statement-Count-Test ist der Pattern fuer Performance-Verifikation
- `feedback_default_user_role.md` — irrelevant, generelle Auth-Disziplin
- `reference_facilioo_pagination.md` — irrelevant fuer 5-4 (Facilioo-Pagination ist read-side, hier geht es um Plattform-Pagination)
- `feedback_sort_nullslast_two_phase.md` — irrelevant fuer 5-4 (eigener Code-Pfad), aber Pattern-Bezug bei Pagination-Tests mit NULL-Werten in der Sortier-Spalte

### Architektur-Bezuege

- **Composite-Index-Design**: `(entity_type, entity_id, field_name, created_at DESC, id DESC)` ist ein Covering-Index fuer den `get_provenance_map_bulk`-Query. Postgres kann ueber den Index sequentiell lesen ohne Sort. Disk-Overhead ~30 % auf der `field_provenance`-Tabelle (heute klein) — vor produktiver Skalierung mit `EXPLAIN ANALYZE` validieren. Doku-Eintrag in `docs/architecture.md` (Datenmodell-Sektion → Indexe) ergaenzen.
- **`DISTINCT ON`-Pattern**: Postgres-spezifisch, nutzt den Composite-Index optimal. SQLite-Fallback ist semantisch identisch (Group-By in Python). Pattern wiederverwendbar fuer kuenftige "latest-pro-Gruppe"-Queries — Doku in `docs/architecture.md` neben dem `pg_insert(...).on_conflict_do_nothing()`-Pattern (5-2 AC1).
- **Request-scoped Cache am `request.state`**: `accessible_object_ids_for_request` ist die erste Stelle dafuer. Pattern wiederverwendbar fuer kuenftige expensive-pro-Request-Helper. Doku-Eintrag in `docs/project-context.md` (Performance-Pattern-Sektion).
- **TTL-Cache mit `time.monotonic`**: `_SIDEBAR_WORKFLOWS_CACHE` ist die erste Stelle. Pattern wiederverwendbar (Process-weit, Multi-Worker-isoliert). Bei kuenftigen TTL-Caches die TTL als Modul-Konstante belassen, nicht globale.
- **Pagination-Vertrag**: `?page=` (1-indexed, `ge=1`) und `?page_size=` (Default 50, Max 200, `ge=1`). Pattern wiederverwendbar fuer kuenftige Listen-Routes (Versicherer-Liste, Due-Radar-Liste sind heute klein, brauchen es noch nicht).
- **Semaphore fuer async-Fanout**: `_PROPERTY_LOOKUP_CONCURRENCY=10` ist heuristisch. Bei zukuenftigen Fanouts dieselbe Konstante wiederverwenden, nicht pro Endpunkt eine eigene anlegen — bei Bedarf hochziehen auf `app/services/_async_helpers.py` (out-of-scope fuer 5-4).

### Threat-Model-Annahmen

- Performance-Probleme sind **kein Angriffs-Vektor** in v1 (Intranet-App, authentifizierte interne User), aber DoS-Surface bei wachsendem Portfolio. Pagination ist primaer Skalierbarkeit, sekundaer Schutz vor `?filter_reserve=true`-Triggered-Vollscans.
- HTMX-401-Antwort ist primaer UX-Fix (kein Angriff), aber die Session-Expiry-Sichtbarkeit ist auch Sicherheits-relevant: ein User der denkt, er sei eingeloggt, schickt Form-Submits ins Leere. Bessere Sichtbarkeit = sicheres Verhalten.
- Composite-Index-Aenderungen sind reversibel und daten-erhaltend. Migrations-Risiko ist niedrig (Index-Build ist ALTER-TABLE-Operation, blockt Reads in Postgres minimal). Bei produktiv groesserer Tabelle waere `CREATE INDEX CONCURRENTLY` zu nutzen — heute mit < 1000 Rows nicht noetig.

### Klassen / Cluster der Defer-Items (zur Orientierung)

- **A. Pagination-Cluster** (#11, #55) — Listen-Routes auf `LIMIT/OFFSET` umstellen → AC1 + AC2 / Task 1 + 2
- **B. Caching-Cluster** (#26, #57, #106) — Request-/TTL-scoped Caches einfuehren → AC3 + AC4 / Task 3 + 4
- **C. Provenance-Optimierung** (#99, #104, #120) — Bulk-Read + DISTINCT ON + Composite-Index → AC5 / Task 5
- **D. Pflegegrad-Reuse** (#37) — `prov_map`-Reuse via Param → AC6 / Task 6
- **E. Async-Fanout** (#31) — Semaphore → AC7 / Task 7
- **F. Page-Load-Idempotenz** (#112) — Skip-on-equal-value fuer `last_known_balance` → AC8 / Task 8
- **G. HTMX-Auth-UX** (#125) — 401 + HX-Redirect bei abgelaufener Session → AC9 / Task 9
- **H. Doku-Only / Out-of-scope** (#33, #133) — Tag + Sprint-Target-Update in deferred-work.md → AC10 / Task 10

Zusammen 13 unique Items (#57 + #106 als Duplikat einmal gezaehlt), 8 Cluster, 10 ACs, 12 Tasks (inkl. Tests + Rollout). Kein Item bleibt offen, kein Item wird doppelt adressiert.

### References

- Deferred-Work-Quelle: `output/implementation-artifacts/deferred-work.md` (Eintraege #11, #26, #31, #33, #37, #55, #57, #99, #104, #106, #112, #120, #125, #133 — alle in der Severity-Tabelle ab Zeile 14 und mit Detail-Beschreibungen ab Zeile 220 (`#11`), 238 (`#26`), 243 (`#31`), 245 (`#33`), 252 (`#37`), 276 (`#55`), 278 (`#57`/#106), 372 (`#112`), 412 (`#133`); fuer #99/#104/#120/#125 siehe Detail-Bloecke nach Zeile 360 unter "story-1.3"/"story-1.5"-Defers)
- Sprint-Status: `output/implementation-artifacts/sprint-status.yaml` Zeile 105 (`5-4-performance-query-optimierung: backlog`) plus Defer-Mapping-Kommentar Zeile 104 (`# Deferred: #11 #26 #31 #33 #37 #55 #57 #99 #104 #106 #112 #120 #125 #133`)
- Vorgaenger-Stories als Template-Referenz: `5-1-security-hardening.md`, `5-2-data-integrity-concurrency.md`, `5-3-backend-robustheit-crash-guards.md` — gleiche Struktur (Story / Boundary-Klassifikation / Vorbedingungen / Kritische Risiken / Deferred-Work-Coverage / AC / Tasks / Tests / Nicht-Scope / Dev Notes)
- Epic-4-Retro: `output/implementation-artifacts/epic-4-retro-2026-05-01.md` — listet 5-4 als Post-Prod-Story mit Tag "Performance/Query-Optimierung | Pagination, Caching, Bulk-Reads | 14 Items (1 als out-of-scope dokumentiert)"
- PRD NFR-Bezuege: `output/planning-artifacts/prd.md` §Performance (NFR-P1..P4) und §Skalierbarkeit (NFR-SC2 — 150 Objekte / 15 User Headroom)
- Code-Stand verifiziert in dieser Session:
  - Latest Migration `0019_police_column_length_caps.py` (aus 5-1, untracked); naechste freie Nummer `0020`
  - `accessible_object_ids` ist `app/permissions.py:258-271` (v1: liefert ALLE Objekte bei `objects:view`-Permission via `set(db.execute(select(Object.id)).scalars().all())`)
  - 21 Callsites von `accessible_object_ids(db, user)` in `app/routers/objects.py` (u. a. Z. 131, 161, 195, 495, 529, 561, 679, 721, 765, 849, 1008, 1040, 1083, 1108) und `app/routers/due_radar.py:32, 51`
  - `_load_accessible_object` ist `app/routers/objects.py:1107`
  - `get_provenance_map` ist `app/services/steckbrief.py:228-265`; ruft 4-fach in `object_detail` (Z. 203, 214, 307, 331)
  - `FieldProvenance`-Model ist `app/models/governance.py:14-46`; existing Indexe in `migrations/versions/0011_steckbrief_governance.py:60-72` (`ix_field_provenance_entity_field`, `ix_field_provenance_user_id`, `ix_field_provenance_created_at`)
  - `sidebar_workflows` ist `app/templating.py:48-73`; `templates.env.globals["sidebar_workflows"] = sidebar_workflows` ist Z. 197
  - `list_conferences_with_properties` ist `app/services/facilioo.py:232-274`; Fanout an Z. 244-249 mit `asyncio.gather(*prop_tasks, return_exceptions=True)` — Concurrency ungebrenzt
  - `pflegegrad_score`/`get_or_update_pflegegrad_cache` ist `app/services/pflegegrad.py:213-232`
  - `last_known_balance`-Page-Load-Write ist `app/routers/objects.py:259-277` (write_field_human + db.commit, plus existing try/except für commit-fail)
  - `_build_queue_query` ist `app/routers/admin.py:1067-1085`; Aufrufer Z. 1116 (`list_review_queue`) und Z. 1172 (`list_review_queue_rows`)
  - `object_detail`-Route ist `app/routers/objects.py:188-446` (Voll-Handler mit allen Sektionen)

## Dev Agent Record

### Completion Notes

- Alle 10 ACs implementiert, 31 neue Tests gruen, 1079 Tests gesamt gruen (0 Fehler).
- **AC5 Statement-Count-Threshold**: Story-Spec sah `<= 21 → <= 18` vor (Annahme: Baseline war 21). Tatsaechliche Baseline war 25 (`tests/test_steckbrief_routes_smoke.py` vor dieser Story). Gemessener Wert nach Implementierung: 21. Neues Threshold: `<= 21` (4 Queries weniger: 3 durch 4→1 Bulk-Konsolidierung AC5 + 1 durch prov_map-Reuse AC6). Semantisch gleich wie vom PO intendiert.
- **`_load_accessible_object`-Refaktor**: `request: Request` als erstes Argument ergaenzt. Alle 11 Callsites aktualisiert.
- **`photo_file_serve`-Fix**: Route hatte kein `request: Request`-Param obwohl `accessible_object_ids_for_request` aufgerufen wurde. Im selben Zug ergaenzt.
- **Monkeypatch-Updates**: 4 Test-Dateien (`test_steckbrief_routes_smoke.py`, `test_policen_routes_smoke.py`, `test_schadensfaelle_routes_smoke.py`, `test_wartungspflichten_routes_smoke.py`) patchen jetzt `accessible_object_ids_for_request` statt `accessible_object_ids`.
- **Task 12 (Rollout-Verifikation Docker)** nicht automatisiert — Docker-Build ist manuell. Tests lokal gruen, Migration `0020_perf_indexes.py` korrekt verlinkt.

### File List

**Neue Dateien:**
- `migrations/versions/0020_perf_indexes.py`
- `tests/test_performance_query_optimization.py`

**Geaenderte Dateien:**
- `app/routers/admin.py` — AC1 Pagination
- `app/templates/admin/review_queue.html` — AC1 Pagination-Nav
- `app/routers/objects.py` — AC2 Pagination, AC4 accessible_object_ids_for_request, AC5 prov_map_bulk, AC6 pflegegrad prov_map, AC8 skip-on-equal, AC9 HTMX-401 (photo_file_serve request-param)
- `app/templates/objects_list.html` — AC2 Pagination-Nav
- `app/templates/_obj_table_swap.html` — AC2 OOB Pagination-Nav
- `app/templating.py` — AC3 TTL-Cache
- `app/routers/auth.py` — AC3 Logout-Cache-Invalidation
- `app/permissions.py` — AC4 accessible_object_ids_for_request
- `app/routers/due_radar.py` — AC4 Wrapper-Calls
- `app/services/steckbrief.py` — AC5 get_provenance_map_bulk
- `app/services/pflegegrad.py` — AC6 prov_map-Param
- `app/services/facilioo.py` — AC7 Semaphore
- `app/auth.py` — AC9 HTMX-401
- `output/implementation-artifacts/deferred-work.md` — AC10 Tags
- `output/implementation-artifacts/sprint-status.yaml` — Status: review
- `tests/test_steckbrief_routes_smoke.py` — Statement-Count-Threshold 25→21; monkeypatch fix
- `tests/test_policen_routes_smoke.py` — monkeypatch fix
- `tests/test_schadensfaelle_routes_smoke.py` — monkeypatch fix
- `tests/test_wartungspflichten_routes_smoke.py` — monkeypatch fix

### Change Log

| Task | Datei | Zeile | Aenderung |
|------|-------|-------|-----------|
| 1 | admin.py | 1108-1137 | page/page_size Params + paginated_q + total_count in list_review_queue |
| 1 | admin.py | 1171-1205 | identisch in list_review_queue_rows |
| 1 | review_queue.html | — | Pagination-Nav + page_size Hidden-Input |
| 2 | objects.py | ~188 | page/page_size + Python-Slice + total_count in list_objects |
| 2 | objects_list.html | — | Pagination-Nav Desktop + Mobile |
| 2 | _obj_table_swap.html | — | OOB Pagination-Nav |
| 3 | templating.py | ~48 | _SIDEBAR_WORKFLOWS_CACHE + TTL-Check |
| 3 | auth.py (router) | — | _SIDEBAR_WORKFLOWS_CACHE.pop(user.id) in logout |
| 4 | permissions.py | ~271 | accessible_object_ids_for_request Wrapper |
| 4 | objects.py | ~21 Stellen | Wrapper-Call-Migration + _load_accessible_object Signatur |
| 4 | due_radar.py | 32, 51 | Wrapper-Call-Migration |
| 5 | steckbrief.py | ~268 | get_provenance_map_bulk + dialect-Switch |
| 5 | objects.py | ~221 | prov_map = get_provenance_map_bulk + Slices |
| 5 | 0020_perf_indexes.py | — | ix_field_provenance_entity_field_created |
| 6 | pflegegrad.py | ~102 | prov_map-Param in pflegegrad_score |
| 6 | pflegegrad.py | ~213 | prov_map-Param in get_or_update_pflegegrad_cache |
| 7 | facilioo.py | — | _PROPERTY_LOOKUP_CONCURRENCY + _bounded_get Semaphore |
| 8 | objects.py | ~260 | last_known_balance skip-on-equal |
| 9 | auth.py (app) | — | HX-Request check → HTTPException(401) |
| 10 | deferred-work.md | — | #33 + #133 Tags + Sprint-Target-Updates |
| 11 | test_performance_query_optimization.py | — | 31 neue Tests (AC1-AC10) |
| fix | test_steckbrief_routes_smoke.py | 463 | Threshold 25 → 21 + Monkeypatch |
| fix | test_policen_routes_smoke.py | 5 Stellen | Monkeypatch accessible_object_ids_for_request |
| fix | test_schadensfaelle_routes_smoke.py | 2 Stellen | Monkeypatch accessible_object_ids_for_request |
| fix | test_wartungspflichten_routes_smoke.py | 2 Stellen | Monkeypatch accessible_object_ids_for_request |

### Review Findings

Code-Review-Lauf nach 0cda1d0 (3-Layer parallel: Blind Hunter, Edge Case Hunter, Acceptance Auditor). Findings unten direkt im Folge-Commit gefixt.

- [x] [Review][Patch] AC2 Pagination `/objects` machte Python-Slice statt SQL — Filter `reserve_below_target` jetzt SQL-seitig, count nach Filter, Page-Slice nach Sort (Sort bleibt Python wegen NULLs-last). [`app/services/steckbrief.py:100-225`, `app/routers/objects.py:128-225`]
- [x] [Review][Patch] Logout-CSRF same-origin-Check brach hinter Reverse-Proxy (Elestio) — `X-Forwarded-Host` + `settings.base_url` als zusaetzliche Whitelist. [`app/routers/auth.py:26-78`]
- [x] [Review][Patch] `pflegegrad_score(prov_map=partial)` setzte Decay still auf 1.0 fuer fehlende Felder — Bulk-Fallback fuer missing keys ergaenzt; Bulk-Caller fuellt prov_map mit None fuer alle `_ALL_SCALAR`-Keys, damit der Fallback im Hot-Pfad nicht extra-queried. [`app/services/pflegegrad.py:106-160`, `app/routers/objects.py:322-340`]
- [x] [Review][Patch] `db.bind.dialect.name` konnte `None` sein → silent SQLite-Fallback in Prod → `db.get_bind()`. [`app/services/steckbrief.py:268-322`]
- [x] [Review][Patch] `accessible_object_ids_for_request(request=None, ...)` crashte mit AttributeError trotz Docstring-Versprechen — None-Guard ergaenzt. [`app/permissions.py:274-293`]
- [x] [Review][Patch] Page > total_pages → leere Liste ohne Hinweis → server-side `effective_page = min(page, total_pages)` Clamp in `/admin/review-queue` und `/objects`. [`app/routers/admin.py:1118-1138`, `:1181-1207`, `app/routers/objects.py:128-205`]
- [x] [Review][Patch] Pagination-URLs in `review_queue.html` escapten Filter-Werte nicht (Param-Splitting bei `&` im Filter-Value) → `| urlencode`. [`app/templates/admin/review_queue.html`]
- [x] [Review][Patch] `HX-Request`-Check Case-sensitive — `.lower() == "true"`. [`app/auth.py:46-54`]
- [x] [Review][Patch] `failed`-Counter in `list_conferences_with_properties` zaehlte nur Exceptions, nicht Schema-Drift (Liste statt Dict) → unbedingt `failed += 1`. [`app/services/facilioo.py:268-285`]
- [x] [Review][Patch] Sidebar-Cache wuchs unbeschraenkt — Hard-Cap 1000 mit TTL-Sweep + LRU-Fallback. [`app/templating.py:29-99`]
- [x] [Review][Patch] AC5 `test_get_provenance_map_bulk_postgres_distinct_on` verifizierte nicht, dass DISTINCT ON im SQL steht — jetzt mit Postgres-Dialect-Compile + Substring-Assert. [`tests/test_performance_query_optimization.py:493-525`]
- [x] [Review][Patch] AC4 `test_accessible_object_ids_isolated_between_requests` testete keine Isolation, nur Inhalt — DB-Hit-Counter ergaenzt. Plus neuer Test `_handles_none_request`. [`tests/test_performance_query_optimization.py:382-440`]
- [x] [Review][Patch] AC1/AC2 Pagination-Tests assertierten nur Pagination-Markup, nicht Row-Counts — Approve-Button-/Detail-Link-Counter ergaenzt. [`tests/test_performance_query_optimization.py:115-220`]
- [x] [Review][Patch] AC9 401-Test pinnt jetzt `HX-Redirect: /auth/google/login` + neuer Case-Insensitive-Test. [`tests/test_performance_query_optimization.py:739-770`]
- [x] [Review][Patch] AC6 `test_pflegegrad_score_uses_prov_map_when_provided` verifiziert jetzt explizit `field_provenance`-Query-Count via Statement-Filter; neuer Test `_partial_prov_map_falls_back_per_missing_field` deckt den decay-defeat-Fix ab. [`tests/test_performance_query_optimization.py:530-620`]
- [x] [Review][Defer] Sidebar-Cache wird bei Role-/Workflow-Aenderung nicht invalidiert — bewusst akzeptiert (AC3 expliziter Trade-off, max 30s stale).
- [x] [Review][Defer] `last_known_balance` race-window bei zwei concurrent Page-Loads mit identischem live_balance — Audit-Noise, kein Datenverlust; UNIQUE-Constraint eigene Story.
- [x] [Review][Defer] Migration `0020_perf_indexes.py` ohne `CREATE INDEX CONCURRENTLY` — heute < 1000 Rows; bei produktivem Wachstum nachziehen (eigene Ops-Story).
- [x] [Review][Defer] CSRF-Token-Rotation invalidiert bei Re-Login Multi-Tab-Forms — bewusster Trade-off zugunsten Session-Fixation-Schutz.
- [x] [Review][Defer] Logout-CSRF empty-Referer-Allowed — Trade-off (Address-Bar-Logout vs. `referrerpolicy=no-referrer`-Trick); empty-referer bleibt erlaubt, dokumentiert.
