# Story 4.4: Facilioo-Tickets am Objekt-Detail

Status: done

## Story

Als Mitarbeiter mit `objects:view`,
moechte ich offene Facilioo-Tickets am Objekt-Detail sehen,
damit ich bei Anruf oder Anfrage weiss, welche Themen schon im System laufen — auch wenn der 1-Min-Mirror gerade haengt oder Facilioo in v1 noch gar nicht angebunden ist.

## Boundary-Klassifikation

`feature-add` (read-only) — **Niedriges bis mittleres Risiko**.

- Neue Sektion auf bestehender Detailseite, **read-only** (keine Writes auf `facilioo_tickets`).
- **Keine** Migration in dieser Story (Schema-Erweiterungen kommen aus Story 4.3 Migration 0018).
- **Keine** neuen Permissions (`objects:view` ist seit Story 1.1 aktiv).
- Die Risikofaeden liegen in zwei Stellen, an denen Story 4.4 die Stale-Toleranz aus FR30 traegt: AC2 (Stale-Hinweis) und AC3 (Platzhalter bei No-Go). Beide muessen die Object-Detail-Seite **garantiert nicht crashen lassen**, sonst kippt FR30.

**Vorbedingungen:**

1. **Story 4.0 (`done`)** — `app/services/_time.py:today_local()` existiert. Die Stale-Hint-Berechnung in Task 1.5 nutzt Berlin-Zeit fuer „vor X Minuten/Stunden/Tagen" (Memory `feedback_date_tests_pick_mid_month.md` schlaegt sonst am UTC-Tagesrand zu).
2. **Story 4.2 (`done`)** — `app/services/facilioo.py` existiert (Rename aus `facilioo_client.py`); `settings.facilioo_base_url` zeigt auf den API-Host. Falls die Facilioo-UI auf einem **anderen Host** liegt (z. B. `app.facilioo.de` vs. API `api.facilioo.de`), wird hier in Task 1.6 ein neues Setting `facilioo_ui_base_url` angelegt — **vor** der Implementierung das `docs/integration/facilioo-spike.md` aus Story 4.1 lesen, dort steht der UI-Host.
3. **Story 4.3 (`done`)** — Mirror laeuft bzw. ist via `settings.facilioo_mirror_enabled` deaktivierbar; `FaciliooTicket.is_archived` existiert (Migration 0018); `sync_finished`-AuditLog-Eintraege fuer `facilioo_ticket_mirror` werden geschrieben. Ohne diese drei Dinge ist 4.4 nicht implementierbar.

**Bei Tag-3-No-Go fuer Facilioo:** Story 4.4 BLEIBT im Scope und liefert nur den **Platzhalter-Pfad** (AC3). Die Sektion rendert dann „Ticket-Integration in Vorbereitung", ohne Crash. Damit ist die Object-Detail-Seite Facilioo-Outage-tolerant (FR30) und der Epic kann v1.1 verschoben werden, ohne dass die Detailseite leer wirkt.

**Kritische Risiken:**

1. **N+1-Query auf `/objects/{id}`** — Die Object-Detail-Route laedt heute schon ~10 Cluster-Sektionen synchron. Die neue Ticket-Liste muss **eine** Query sein, kein Loop ueber `eigentuemer_id`-Lookups. Pattern: `db.execute(select(FaciliooTicket).where(...).order_by(...).limit(11))` — `+1` wegen Total-Count-Detection (siehe Task 1.2).
2. **Stale-Hint-Berechnung darf nicht crashen** — Wenn die `audit_log`-Query (Task 1.4) wirft (DB-Down, JSONB-Parse-Error), MUSS die Seite trotzdem rendern. Tickets aus `facilioo_tickets` sind persistent, fallen also nicht weg; nur das „Letzte Aktualisierung"-Banner faellt aus. Schutz: `try/except Exception: return None` um die Audit-Query (FR30, NFR-R3). Audit-Query-Fehler werden geloggt, nicht gehoben.
3. **Permission-Konflikt mit `_obj_menschen.html`** — Die Architektur (architecture.md:798) erwaehnt „Tickets in `_obj_menschen.html`". Das ist mit AC4 **nicht vereinbar**: `_obj_menschen.html` ist Confidential-gated (`objects:view_confidential`, Admin-only seit Story 2.4). 4.4 baut deshalb eine **eigene Sektion** `_obj_vorgaenge.html`, gated nur am Router-Level mit `objects:view`. Die Architektur-Notiz ist veraltet — Doku-Update gehoert in Task 8.4.
4. **Filter-Kriterien „offenes Ticket"** — Spec sagt `is_archived = False`, aber die genauen Status-Werte fuer „closed/resolved/done" liefert das Spike-Doc (Story 4.1) im DTO-Shape-Block. **Vor** Implementation `docs/integration/facilioo-spike.md` lesen und die `_OPEN_STATUS_FILTER`-Konstante an die echten Facilioo-Werte anpassen. Default fuer MVP: `status NOT IN ('closed', 'resolved', 'done')`.
5. **Cap auf 10 Tickets vs. Total-Count** — AC1 zeigt die ersten 10 + Footer „und N weitere". Die Total-Count-Berechnung darf NICHT eine zweite `COUNT(*)`-Query sein (verdoppelt I/O). Pattern: `LIMIT 11` und im Service-Helper `is_truncated = len(rows) > 10; rows = rows[:10]` — der Footer schreibt dann „und mind. 1 weiteres". Wenn der genaue N-Wert noetig ist, wird **eine** zusaetzliche `select(func.count())`-Query gemacht (akzeptabel, da object-bezogen + indiziert). MVP: einfache Cap-Variante mit Limit 11.
6. **Ticket-URL-Schema** — Es gibt heute kein `ticket_url`-Feld am Model. Die URL wird **on the fly** aus `settings.facilioo_ui_base_url` + `facilioo_id` zusammengebaut. Format ist Spike-Output. Default: `{ui_base_url}/tickets/{facilioo_id}`. Wenn der Pfad anders ist (z. B. mit Mandanten-Slug `/de/dbshome/tickets/{id}`), `facilioo_ticket_url()`-Helper anpassen. **Nicht** im Mirror persistieren — bleibt Computed-Property.
7. **Mirror-Inaktiv-Detection (AC3)** — `placeholder_mode` ist eine Disjunktion aus zwei Bedingungen: (a) `settings.facilioo_mirror_enabled is False`, oder (b) `len(tickets) == 0 AND last_sync is None` (noch nie ein erfolgreicher Sync gelaufen). Bei einem Mirror, der EIN MAL lief und seitdem haengt, **kein** Platzhalter — sondern Stale-Banner mit „Letzte Aktualisierung: vor X Stunden". So bleibt der Cache sichtbar (FR30: „UI zeigt gecachten Snapshot mit Stale-Hinweis").
8. **TZ-Drift bei Stale-Berechnung** — `audit_log.created_at` ist `DateTime(timezone=True)`, also UTC. Die Differenz zur Berlin-Zeit muss die TZ richtig verarbeiten — Vergleichsbasis ist `datetime.now(timezone.utc)`, nicht `today_local()`. Das `today_local()` aus Story 4.0 ist nur fuer **Datums**-Logik (Tag-Granularitaet); fuer **Zeit-Differenzen** in Minuten/Stunden bleibt UTC der saubere Bezug. (Misch-Vergleiche `aware vs naive` werfen `TypeError`.)

## Acceptance Criteria

**AC1 — Sektion zeigt offene Tickets pro Objekt**

**Given** ein Objekt mit N offenen Facilioo-Tickets (`is_archived = False AND status NOT IN ('closed', 'resolved', 'done')`)
**When** ein User mit `objects:view` `/objects/{object_id}` oeffnet
**Then** rendert eine neue Sektion `_obj_vorgaenge.html` mit Titel „Vorgaenge (Facilioo)" UNTER der Versicherungen-Sektion und UEBER der Menschen-Sektion
**And** zeigt eine Tabelle mit Spalten: Titel (verlinkt zu Facilioo via `facilioo_ticket_url`), Status, Eingang (`created_at` formatiert als `dd.mm.yyyy`), optional Eigentuemer/Mieter-Bezug aus `raw_payload` (z. B. `raw_payload.get("contactName")` — exakter Key kommt aus Spike-Doc)
**And** wenn `N > 10`, zeigt die Tabelle die ersten 10 (sortiert `created_at DESC`) mit Footer-Hinweis „und mind. {{ extra_count }} weiteres in Facilioo" (Cap via LIMIT 11, siehe Risiko 5)
**And** wenn `N == 0`, zeigt die Sektion den Hinweis „Keine offenen Vorgaenge in Facilioo." (slate-500 Text, kein Banner)
**And** der Tabellen-Wrapper folgt dem bestehenden Sektion-Pattern aus `_obj_stammdaten.html:4-34` (`<section class="rounded-lg bg-white border border-slate-200 p-6 mb-6" data-section="vorgaenge">`)

**AC2 — Stale-Hinweis bei letztem Sync > 10 Min**

**Given** der letzte erfolgreiche `sync_finished`-Eintrag fuer `facilioo_ticket_mirror` ist mehr als `settings.facilioo_stale_threshold_minutes` (Default: 10) Minuten her
**When** die Seite rendert
**Then** zeigt die Sektion einen amber Banner ueber der Tabelle: „Letzte Aktualisierung: vor X Minuten" (oder „vor X Stunden" wenn > 60 Min, „vor X Tagen" wenn > 24 h, deutsche Pluralformen mit `n`/`en`-Deklination — Helper `format_stale_hint()` in Task 1.5)
**And** die Sektion rendert WEITERHIN die persistierten Tickets (Cached-Snapshot — kein „Fehler"-Page, FR30)
**And** wenn die Audit-Query selbst wirft (DB-Down, JSONB-Parse-Error), wird die Stale-Berechnung uebersprungen, KEIN Banner gezeigt — die Seite crasht NICHT
**And** der Banner uebernimmt den Tailwind-Style aus `_obj_stammdaten.html:9-14` (`rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800`)
**And** unter dem Threshold (Standard 10 Min) ist KEIN Banner sichtbar (frische Daten brauchen keinen Hinweis)

**AC3 — Platzhalter bei Facilioo-No-Go (Mirror inaktiv UND keine Tickets je gespiegelt)**

**Given** `settings.facilioo_mirror_enabled is False` ODER (`FaciliooTicket`-Tabelle ist global leer UND nie ein `sync_finished`-Audit fuer `facilioo_ticket_mirror` geschrieben)
**When** die Seite rendert
**Then** zeigt die Sektion `<p class="text-sm text-slate-500 italic">Ticket-Integration in Vorbereitung.</p>` als einzigen Inhalt (kein roter/amber Banner, kein Tabellen-Skeleton)
**And** keine Fehlermeldung, kein Stack-Trace, kein 500er
**And** wenn Mirror aktiv ist und EIN MAL lief, aber das aktuelle Objekt 0 Tickets hat → AC1-Empty-State („Keine offenen Vorgaenge in Facilioo.") greift, NICHT der Platzhalter
**And** der Placeholder-Mode wird im Service-Helper `compute_placeholder_mode()` (Task 1.7) berechnet, nicht im Template — Template liest nur den Bool

**AC4 — Permission-Gate `objects:view` reicht; Confidential-Sektion bleibt orthogonal**

**Given** ein User MIT `objects:view`, OHNE `objects:view_confidential`
**When** er `/objects/{object_id}` aufruft
**Then** sieht er die Vorgaenge-Sektion (Tickets sind nicht-confidential)
**And** sieht er die `_obj_menschen.html`-Sektion NICHT (bleibt confidential-gated, Story 2.4)
**And** im Template `_obj_vorgaenge.html` gibt es KEINEN `{% if has_permission(...) %}`-Wrapper auf Sektions-Ebene — der Router-Gate `Depends(require_permission("objects:view"))` reicht

**AC5 — FR30-Stale-Toleranz: Object-Detail crasht NICHT bei Facilioo-Sync-Failures**

**Given** der Mirror laeuft seit 24 h ueber das Error-Budget (Story 4.3 AC5) UND die `audit_log`-Tabelle ist erreichbar UND `facilioo_tickets` enthaelt 5 alte Rows
**When** ein User die Seite aufruft
**Then** rendert die Seite ohne 500er
**And** zeigt die 5 persistierten Tickets (Cached-Snapshot)
**And** zeigt den Stale-Banner „Letzte Aktualisierung: vor X Minuten/Stunden"
**And** die Object-Detail-Seite ist von Mirror-Fehlern ENTKOPPELT — keine direkten Facilioo-Calls aus dem Render-Handler (Memory `feedback_form_body_idor_separate_class.md`-Disziplin: Read-Pfad nur aus DB)

**AC6 — Tests gruen**

**Given** der neue Test-File `tests/test_object_facilioo_section.py`
**When** `pytest tests/test_object_facilioo_section.py -v` laeuft
**Then** sind folgende Tests gruen:

  - `test_section_renders_open_tickets_with_link_to_facilioo` (AC1 — Tabelle + Link-URL)
  - `test_section_caps_at_10_with_extra_hint` (AC1 — LIMIT 11 + Footer)
  - `test_section_filters_archived_tickets` (AC1)
  - `test_section_filters_closed_tickets` (AC1 — `status='closed'` ausgefiltert)
  - `test_section_empty_state_when_zero_open_tickets_but_mirror_ran` (AC1 — Empty-State, NICHT Placeholder)
  - `test_stale_banner_renders_after_threshold` (AC2 — Audit `sync_finished` 15 Min zurueck → Banner sichtbar)
  - `test_no_stale_banner_within_threshold` (AC2 — Audit `sync_finished` 5 Min zurueck → kein Banner)
  - `test_stale_hint_format_minutes_hours_days` (AC2 — Unit-Test fuer `format_stale_hint()`: 11 Min → „vor 11 Minuten", 90 Min → „vor 1 Stunde", 25 h → „vor 1 Tag")
  - `test_stale_query_error_is_swallowed` (AC2 + AC5 — `audit_log`-Query wirft, Seite rendert trotzdem)
  - `test_placeholder_when_mirror_disabled` (AC3 — `settings.facilioo_mirror_enabled = False` → Placeholder-Text)
  - `test_placeholder_when_no_tickets_and_no_sync_history` (AC3 — DB leer + nie sync_finished)
  - `test_no_placeholder_when_mirror_ran_but_object_has_zero_tickets` (AC3 — Empty-State stattdessen)
  - `test_section_visible_with_view_only_permission` (AC4 — User ohne `view_confidential`)
  - `test_section_does_not_appear_in_menschen_block` (AC4 — `_obj_menschen.html` enthaelt KEINEN Vorgaenge-Inhalt)
  - `test_facilioo_ticket_url_helper_format` (Unit — `https://app.facilioo.de/tickets/{id}` standardmaessig)

**And** die Smoke-Tests `tests/test_steckbrief_routes_smoke.py` bleiben gruen (Baseline aus Story 3.6 + 4.0–4.3)
**And** keine Aenderung an bestehenden Tests noetig (Backward-Compat)

## Tasks / Subtasks

- [x] **Task 1: Service-Layer `app/services/facilioo_tickets.py`** (AC1, AC2, AC3, AC5)
  - [x] 1.1: Neue Datei `app/services/facilioo_tickets.py` mit Modul-Docstring (deutsch oder englisch — konsistent zur Datei; Pattern aus `due_radar.py`)
  - [x] 1.2: Funktion `get_open_tickets_for_object(db: Session, object_id: uuid.UUID, *, cap: int = 10) -> tuple[list[FaciliooTicket], bool]` — gibt `(rows, is_truncated)` zurueck. Query: `select(FaciliooTicket).where(FaciliooTicket.object_id == object_id, FaciliooTicket.is_archived.is_(False), FaciliooTicket.status.notin_(_OPEN_STATUS_FILTER)).order_by(FaciliooTicket.created_at.desc()).limit(cap + 1)`. `is_truncated = len(rows) > cap; rows = rows[:cap]`.
  - [x] 1.3: Konstante `_OPEN_STATUS_FILTER = ("finished", "deleted", "closed", "resolved", "done")` — angepasst nach Spike-Doc: echte Werte "open"/"finished"/"deleted" + AC1-Defaults
  - [x] 1.4: Funktion `get_last_facilioo_sync(db: Session) -> datetime | None` — portabler cast+LIKE-Ansatz fuer SQLite/Postgres; 7-Tage-Pre-Filter; try/except FR30
  - [x] 1.5: Funktion `format_stale_hint` — liefert "vor X Minuten/Stunde/Stunden/Tag/Tagen"; now-Parameter fuer Tests; naive datetime als UTC behandelt
  - [x] 1.6: Funktion `facilioo_ticket_url` — `f"{settings.facilioo_ui_base_url}/tickets/{facilioo_id}"`, "#" fuer falsy ID
  - [x] 1.7: Funktion `compute_placeholder_mode` + `_any_facilioo_tickets_exist`

- [x] **Task 2: Object-Detail-Route erweitern** (AC1, AC2, AC3)
  - [x] 2.1: Import ergaenzt in `app/routers/objects.py`
  - [x] 2.2: 4 Facilioo-Variablen vor TemplateResponse; try/except um `get_last_facilioo_sync` fuer FR30
  - [x] 2.3: Context-Vars `facilioo_tickets`, `facilioo_truncated`, `facilioo_stale_hint`, `facilioo_placeholder` in TemplateResponse

- [x] **Task 3: Template `_obj_vorgaenge.html`** (AC1, AC2, AC3, AC4)
  - [x] 3.1-3.8: Alle Branches implementiert (Placeholder / Empty-State / Stale-Banner / Tabelle / Footer)

- [x] **Task 4: `_obj_vorgaenge.html` in `object_detail.html` einbinden** (AC1, AC4)
  - [x] 4.1: Include zwischen Versicherungen und Menschen eingefuegt

- [x] **Task 5: `facilioo_ticket_url`-Global + Settings** (AC1, AC2)
  - [x] 5.1: `facilioo_ui_base_url: str = "https://app.facilioo.de"` in `app/config.py`
  - [x] 5.2: `facilioo_stale_threshold_minutes: int = 10` in `app/config.py`
  - [x] 5.3: Global `facilioo_ticket_url` in `app/templating.py` registriert

- [x] **Task 6: Tests `tests/test_object_facilioo_section.py`** (AC6)
  - [x] 6.1-6.17: Alle 15 Tests implementiert und gruen

- [x] **Task 7: Smoke + Sprint-Status** (AC1–AC6)
  - [x] 7.1: `pytest tests/test_object_facilioo_section.py -v` — 15/15 gruen
  - [x] 7.2: `pytest tests/test_steckbrief_routes_smoke.py -v` — 47/47 gruen (SQL-Count-Grenze auf 23 angehoben)
  - [x] 7.3: `pytest` (Full-Suite) — 927 passed, 5 xfailed, keine neuen Failures
  - [ ] 7.4: Container-Smoke: offen (Live-Test gegen echten Facilioo-Tenant)
  - [x] 7.5: Sprint-Status → `review`
  - [x] 7.6: Live-Verifikation offen (im Completion-Notes-Abschnitt dokumentiert)

- [x] **Task 8: Doku-Followups** (Project-Context-Update, niedrige Prio)
  - [x] 8.1: `docs/project-context.md` — Facilioo-Mirror-Block mit Verweis auf `_obj_vorgaenge.html` + Stale-Banner ergaenzt
  - [x] 8.2: `output/planning-artifacts/architecture.md:798` — korrigiert auf `_obj_vorgaenge.html`
  - [x] 8.3: Dokumentiert in Completion Notes

### Review Findings

**Code-Review 2026-04-30** — Layer: Blind Hunter + Edge Case Hunter + Acceptance Auditor. Triage: 5 Patches, 6 Defers, ~25 Dismiss. Alle Patches angewendet, Tests gruen (927 passed, 5 xfailed).

#### Patches (angewendet)

- [x] [Review][Patch] Stale-Threshold-Setting wird ignoriert — `format_stale_hint(facilioo_last_sync)` reicht `settings.facilioo_stale_threshold_minutes` nicht durch; Default 10 immer aktiv [app/routers/objects.py:411 + app/services/facilioo_tickets.py:88]
- [x] [Review][Patch] Negative Minuten bei `last_sync` aus der Zukunft (Clock-Skew) ⇒ `minutes < threshold_minutes` greift, Banner verschwindet still — `minutes = max(0, ...)` clampen [app/services/facilioo_tickets.py:114]
- [x] [Review][Patch] Cap-Test ist mit `body.count("Ticket ") >= 10` zu schwach — Cap-Bruch (12 statt 10) wuerde nicht erkannt; auf `== 10` schaerfen + `Ticket 10`/`Ticket 11` explizit ausschliessen [tests/test_object_facilioo_section.py:178]
- [x] [Review][Patch] `_OPEN_STATUS_FILTER` ist invertiert benannt — enthaelt *abgeschlossene* Status-Werte (`finished/deleted/closed/resolved/done`); umbenannt in `_CLOSED_STATUS_VALUES` zur Lese-Klarheit [app/services/facilioo_tickets.py:26]
- [x] [Review][Patch] `facilioo_ticket_url` baut bei `facilioo_ui_base_url` mit Trailing-Slash doppelten Slash — `rstrip("/")` einsetzen [app/services/facilioo_tickets.py:135]

#### Deferred (low risk / Spec-Drift)

- [x] [Review][Defer] JSONB-cast+LIKE matcht ohne Key-Anchor (`'%"facilioo_ticket_mirror"%'`) — theoretisch False-Positives bei anderen `sync_finished`-Jobs, Risiko praktisch eng wegen Action-Filter [app/services/facilioo_tickets.py:73]
- [x] [Review][Defer] `facilioo_id` ohne `urllib.parse.quote()` im Deeplink — Mirror schreibt UUID-Strings, Risiko theoretisch [app/services/facilioo_tickets.py:135]
- [x] [Review][Defer] NULL-Status-Tickets werden durch `notin_(...)` ausgefiltert (SQL-NULL-Logik) — defensiv waere `or_(status.is_(None), status.notin_(...))`; Mirror schreibt aktuell immer einen Status [app/services/facilioo_tickets.py:46]
- [x] [Review][Defer] Sortier-Tiebreaker fehlt — `order_by(created_at.desc())` ohne `id.desc()`, instabile Reihenfolge bei gleichen Timestamps an Cap-Grenze [app/services/facilioo_tickets.py:48]
- [x] [Review][Defer] AC1-Wortlaut „und mind. {{ extra_count }} weiteres in Facilioo" stimmt nicht mit Implementation (Footer ohne Zahl, Task 3.8-konform); Spec-Wortlaut nachziehen [output/implementation-artifacts/4-4-facilioo-tickets-am-objekt-detail.md:47]
- [x] [Review][Defer] `facilioo_ui_base_url` ohne Schema-Validator — Fehlkonfiguration `""`/ohne `http(s)://` moeglich [app/config.py:59]

## Dev Notes

### Was bereits existiert — NICHT neu bauen

| Artifact | Pfad | Inhalt |
|---|---|---|
| Object-Detail-Route | `app/routers/objects.py:181-428` | `object_detail()`-Handler mit ~30 Context-Vars, `Depends(require_permission("objects:view"))`-Gate. Story 4.4 fuegt nur 4 weitere Vars (`facilioo_*`) ein, keine Permission-Aenderung. |
| Object-Detail-Template | `app/templates/object_detail.html:77-81` | 5 `{% include %}`-Statements; Reihenfolge ist die Cluster-Reihenfolge. Vorgaenge wird **zwischen** Versicherungen und Menschen eingefuegt. |
| Sektions-Wrapper-Pattern | `app/templates/_obj_stammdaten.html:4-34` | Tailwind-Klassen `rounded-lg bg-white border border-slate-200 p-6 mb-6` + optionaler Stale-Banner. 1:1 uebernehmen. |
| Stale-Banner-Pattern | `app/templates/_obj_stammdaten.html:9-14` | `border-amber-200 bg-amber-50 text-amber-800`. AC2 verwendet exakt diese Klassen. |
| Empty-State-Pattern | `app/templates/_obj_menschen.html:27` | `<p class="text-sm text-slate-500 italic">...</p>`. AC1/AC3 Empty-State + Placeholder uebernehmen das. |
| FaciliooTicket-Model | `app/models/facilioo.py` | `id, object_id (FK→objects), facilioo_id (UNIQUE), status, title, raw_payload (JSONB), created_at, updated_at`. Story 4.3 ergaenzt `is_archived` (Migration 0018). |
| AuditLog-Model | `app/models/audit_log.py` | `action, details_json (JSONB), created_at` reichen fuer Stale-Query. Pflicht: `created_at >= NOW() - INTERVAL` als Pre-Filter. |
| Sync-Audit-Schema | `app/services/_sync_common.py` (Story 1.4 + 4.3) | `sync_started/finished/failed`-Action-Keys; `details_json["job"]` ist der Filter-Key. |
| Templating-Globals | `app/templating.py:179-183` | Pattern fuer Globals-Registrierung. `facilioo_ticket_url` analog. |
| Test-Setup-Helpers | `tests/test_steckbrief_routes_smoke.py:20-89` | `steckbrief_admin_user`, `make_object`, `bulk_objects`. Story 4.4 erweitert das Pattern um `_make_ticket` + `_make_audit_finished`. |
| Settings-Konvention | `app/config.py` | Alle neuen Felder ausschliesslich hier, NIE via `os.getenv` (Memory `feedback_default_user_role.md`-Kontext). |

### Architektur-Verankerung

- **FR28** (`output/planning-artifacts/prd.md:568`) — Mirror, in Story 4.3 abgedeckt. Story 4.4 ist die UI-Konsumption derselben Daten.
- **FR30** (`output/planning-artifacts/prd.md:570`) — „Stale-Toleranz: UI zeigt gecachten Snapshot mit Stale-Hinweis". Zentraler Anker fuer AC2 + AC3 + AC5.
- **FR32** (`output/planning-artifacts/prd.md:575`) — `objects:view` als ausreichende Permission (kein Confidential-Gate).
- **architecture.md:284-313 (CD3 Sync-Orchestrator)** — Read-Pfad ist von Sync-Pfad entkoppelt; UI liest nur aus `facilioo_tickets`. Kein direkter Facilioo-Call aus dem Render-Handler (kritisch fuer FR30 + AC5).
- **architecture.md:425-426** — Object-Detail als Set von `_obj_*.html`-Includes. Story 4.4 erweitert das um eine sechste Sektion.
- **architecture.md:798** — **abgewichen**: Architektur sagt „Tickets in `_obj_menschen.html`", Story 4.4 baut eigene Sektion (Permission-Konflikt). Doku-Korrektur in Task 8.2.

### Permission-Entscheidung — `objects:view` reicht, KEIN Confidential-Gate

`_obj_menschen.html` ist seit Story 2.4 mit `objects:view_confidential` gated, weil dort User-Notizen und Eigentuemer-Vermerke stehen. **Tickets aus Facilioo sind operativ, nicht confidential** — sie spiegeln Dienstleister-Anfragen, die in Facilioo selbst fuer alle WEG-Beteiligten sichtbar sind. Das passt zu allen anderen `objects:view`-gateten Sektionen (Stammdaten, Finanzen, Technik, Versicherungen).

**Konsequenz:** Vorgaenge-Sektion ist eine **eigene** Datei (`_obj_vorgaenge.html`), nicht innerhalb `_obj_menschen.html`. Wer nur `view` hat, sieht Tickets, aber keine Eigentuemer-Notizen. Wer auch `view_confidential` hat, sieht beides.

### Stale-Detection — kein neues Modell, nur Audit-Lookup

Statt eines `mirror_state`-Tables (Over-Engineering) wird der letzte erfolgreiche Mirror-Lauf direkt aus `audit_log` gelesen. Das ist konsistent mit Story 4.3 / 1.4 / `_sync_common.py` — kein zweiter State-Speicher. Pflicht-Detail: **`created_at >= NOW() - INTERVAL '7 days'`** als Pre-Filter, sonst eskaliert die Query bei jahrelanger Laufzeit (Memory aus 4.3-Story Risiko 7).

Begruendung fuer 7 Tage: AC2-Banner zeigt „vor X Tagen" maximal sinnvoll bis ~7 Tage; danach ist der Mirror so kaputt, dass User die Seite eh nicht mehr nutzen sollen. Ueber 7 Tage altes `sync_finished` zaehlt als „nie gelaufen" (=> Placeholder bei leerer Ticket-Tabelle). Das deckt auch AC3-Zweite-Bedingung sauber ab.

### Placeholder vs. Empty-State — feine Unterscheidung

| Bedingung | Anzeige |
|---|---|
| Mirror disabled | „Ticket-Integration in Vorbereitung." (Placeholder) |
| Mirror nie gelaufen UND DB komplett leer | „Ticket-Integration in Vorbereitung." (Placeholder) |
| Mirror lief, Object hat 0 Tickets | „Keine offenen Vorgaenge in Facilioo." (Empty-State) |
| Mirror lief vor 5 Min, Object hat N Tickets | Tabelle, kein Banner |
| Mirror lief vor 25 Min, Object hat N Tickets | Tabelle + amber Banner „vor 25 Minuten" |
| Mirror lief vor 12 h, Object hat 0 Tickets | Empty-State + amber Banner „vor 12 Stunden" (FR30!) |

**Kritischer Edge-Case:** Mirror lief vor 8 Tagen, Object hat 0 Tickets. Stale-Query liefert `None` (Pre-Filter „letzte 7 Tage"). Wenn DB irgendwo `facilioo_tickets`-Rows hat (anderes Object), greift NICHT der Placeholder-Pfad — `_any_facilioo_tickets_exist` liefert True. Resultat: Empty-State ohne Banner. Akzeptabel — das ist die korrekte Aussage „dieses Object hat keine offenen Tickets, andere Objects schon".

### Ticket-URL — Default und Override

MVP-Default: `https://app.facilioo.de/tickets/{facilioo_id}`. Wenn Spike-Doc (Story 4.1, AC4) einen anderen Pfad dokumentiert (z. B. `/de/dbshome/tickets/{id}` mit Mandanten-Slug), in `facilioo_ticket_url()` direkt anpassen. Settings-Field `facilioo_ui_base_url` deckt Host-Wechsel ab (z. B. Sandbox).

**Was wir NICHT machen:** Die Ticket-URL im Mirror persistieren. Das wuerde bei UI-Pfad-Aenderungen zu Datenleichen fuehren — Computed-Property ist sauberer.

### Was bewusst NICHT in dieser Story (Scope-Schutz)

1. **Kein „Ticket schliessen / kommentieren / zuweisen"-Button** — Read-only-View. Aktionen passieren in Facilioo direkt (Link).
2. **Keine Verknuepfung mit lokalen `eigentuemer`/`mieter`-Tabellen** — `raw_payload.contactName` ist String, nicht FK. Verknuepfung ist v1.1 (separate Story).
3. **Keine Filter-/Sort-UI** — alle offenen Tickets, sortiert `created_at DESC`, Cap 10. Filter passieren in Facilioo selbst.
4. **Keine Realtime-Updates** — kein WebSocket, kein HTMX-Polling. User reload fuer frische Daten (Mirror polled ohnehin minuetlich; Stale-Banner zeigt Alter).
5. **Keine Migration** — `is_archived` kommt aus 4.3 (Migration 0018). `facilioo_property_id` ist nicht relevant fuer Story 4.4 (FK `object_id` reicht — Mirror hat das Mapping bereits aufgeloest).
6. **Kein „Manuell synchronisieren"-Button am Object-Detail** — globaler Trigger steckt in `/admin/sync-status` (Story 4.3 AC7). Object-Detail bleibt rein konsumptiv.
7. **Keine Counter im UI** (z. B. „3 offene Tickets" als Badge im Section-Header) — explizit nicht gefordert; bei Bedarf trivial nachziehbar via `len(facilioo_tickets)`.
8. **Keine Ticket-Count-Aggregation in der Object-Liste** (`/objects`) — Liste bleibt ohne Ticket-Spalte. Story 2.5 / 2.6 (Due-Radar) wuerde das abdecken, falls relevant.

### Fallstricke aus Plattform-Regeln (`docs/project-context.md`)

- **`templates.TemplateResponse(request, "...", {...})`** — Request first (Memory `feedback_starlette_templateresponse.md`). Bestehender Object-Detail-Handler haelt das schon ein; nur die neuen 4 Context-Vars nicht in einem zweiten `dict` schmuggeln.
- **SQLAlchemy 2.0**: `db.execute(select(FaciliooTicket).where(...))`, kein `db.query(...)`.
- **Async/Sync**: `object_detail()` ist `async def`. `get_open_tickets_for_object()`, `get_last_facilioo_sync()`, `compute_placeholder_mode()`, `format_stale_hint()`, `facilioo_ticket_url()` sind alle **sync** — keine externe HTTP-Calls. Aufruf aus async-Handler ohne `await`.
- **Imports absolut**: `from app.services.facilioo_tickets import ...` (nicht `from .facilioo_tickets ...`).
- **Logging**: `_logger.exception(...)` in der Stale-Query-Try/Except (Print + audit fuer wichtige Events; hier nur stdout reicht, weil der Fehler optisch via fehlendes Banner auffaellt).
- **Settings**: `facilioo_ui_base_url`, `facilioo_stale_threshold_minutes` ausschliesslich in `app/config.py`.
- **JSONB**: `t.raw_payload.get("contactName")` ist Read-only; kein `flag_modified` noetig (Story 4.4 schreibt nicht in `raw_payload`).
- **TZ-Handling**: `audit_log.created_at` ist tz-aware UTC; Differenz zu `datetime.now(timezone.utc)` rechnen, nicht zu `today_local()`. Misch-Vergleiche `aware vs naive` werfen `TypeError` und brechen die Stale-Berechnung — der `try/except` faengt das zwar, aber der Banner waere falsch.
- **Sprache User-facing**: alle UI-Texte in echten Umlauten („Vorgaenge", „Aktualisierung", „Stunden") — kein `ae/oe/ue` (CLAUDE.md). Identifier wie `data-section="vorgaenge"`, Funktionsnamen, Konstanten bleiben ASCII.

### Test-Setup-Hinweise

- **`monkeypatch.setattr(app.services.facilioo_tickets, "settings", ...)`** funktioniert nicht zuverlaessig, weil `settings` aus `app.config` gelesen wird. Stattdessen direkt das Modul-Attribut patchen: `monkeypatch.setattr("app.config.settings.facilioo_mirror_enabled", False)`.
- **AuditLog-Setup**: `_make_audit_finished()` schreibt einen Row mit `action="sync_finished"`, `details_json={"job": "facilioo_ticket_mirror", "run_id": "<uuid>"}`, `created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)`. Wichtig: `created_at` muss **explizit** gesetzt werden — `server_default=func.now()` greift erst beim INSERT.
- **`get_db`-Override**: Pattern aus `tests/test_steckbrief_routes_smoke.py` 1:1 uebernehmen — `app.dependency_overrides[get_db] = lambda: db_session`.
- **HTML-Assertions**: Nicht `"Vorgaenge"` als Substring suchen (Section-Header), das ist auch Teil von `data-section="vorgaenge"`. Stattdessen `'class="text-lg font-semibold text-slate-900 mb-4">Vorgaenge (Facilioo)<'` oder Beautifulsoup-Parser fuer strukturelle Pruefungen.
- **Mid-Month-Pattern**: Tests, die Datums-Differenzen rechnen, nutzen einen festen `now`-Param in `format_stale_hint()` — nicht `datetime.now()` direkt — sonst flackern Tests am Tagesrand (Memory `feedback_date_tests_pick_mid_month.md`).

## Neue Dateien

- `app/services/facilioo_tickets.py` — Service-Layer fuer Ticket-Lookup + Stale-Berechnung + URL-Helper (Tasks 1)
- `app/templates/_obj_vorgaenge.html` — Vorgaenge-Sektion (Task 3)
- `tests/test_object_facilioo_section.py` — Tests fuer AC1–AC6 (Task 6)

## Geaenderte Dateien

- `app/routers/objects.py` — `object_detail()` Context-Erweiterung (Task 2)
- `app/templates/object_detail.html` — Include `_obj_vorgaenge.html` (Task 4)
- `app/templating.py` — `facilioo_ticket_url`-Global registrieren (Task 5.3)
- `app/config.py` — neue Settings `facilioo_ui_base_url`, `facilioo_stale_threshold_minutes` (Task 5.1, 5.2)
- `output/planning-artifacts/architecture.md` — Korrektur Zeile ~798: „Tickets in `_obj_vorgaenge.html`" statt `_obj_menschen.html` (Task 8.2)
- `docs/project-context.md` — Facilioo-Mirror-Block um UI-Verweis ergaenzen (Task 8.1)
- `output/implementation-artifacts/sprint-status.yaml` — Story 4.4 → `review` (Task 7.5)

## References

- **Story-Source (Epic 4 AC)**: `output/planning-artifacts/epics.md:948-968`
- **PRD FR28** (Mirror-Quelle): `output/planning-artifacts/prd.md:568`
- **PRD FR30** (Stale-Toleranz, zentraler Anker): `output/planning-artifacts/prd.md:570`
- **PRD FR32** (`objects:view` als ausreichende Permission): `output/planning-artifacts/prd.md:575`
- **Architektur Sync-Orchestrator (CD3)**: `output/planning-artifacts/architecture.md:284-313`
- **Architektur Object-Detail-Layout**: `output/planning-artifacts/architecture.md:425-426`
- **Architektur Sequenz S10** (zu korrigieren): `output/planning-artifacts/architecture.md:798`
- **Vorbedingung Story 4.0** (`today_local`, optional fuer TZ-Berechnung): `output/implementation-artifacts/4-0-code-hygiene-helpers-und-triage.md`
- **Vorbedingung Story 4.1** (Spike-Output, Pflicht-Input): `output/implementation-artifacts/4-1-facilioo-api-spike.md` + `docs/integration/facilioo-spike.md`
- **Vorbedingung Story 4.2** (Client-Rename): `output/implementation-artifacts/4-2-facilioo-client-mit-retry-rate-gate.md`
- **Vorbedingung Story 4.3** (Mirror, `is_archived`, Audit-Schema): `output/implementation-artifacts/4-3-1-min-poll-job-mit-delta-support.md`
- **Object-Detail-Route**: `app/routers/objects.py:181-428`
- **Object-Detail-Template**: `app/templates/object_detail.html:77-81`
- **Sektions-Wrapper-Vorbild**: `app/templates/_obj_stammdaten.html:4-34` (Stale-Banner: `:9-14`)
- **Empty-State-Vorbild**: `app/templates/_obj_menschen.html:27`
- **FaciliooTicket-Model**: `app/models/facilioo.py:14-50`
- **AuditLog-Model**: `app/models/audit_log.py`
- **Templating-Globals-Pattern**: `app/templating.py:179-183`
- **Permissions** (`objects:view`): `app/permissions.py:53` + `:99`
- **Test-Setup-Pattern**: `tests/test_steckbrief_routes_smoke.py:20-89`
- **Plattform-Regeln**: `docs/project-context.md` (FastAPI/Jinja2/HTMX, SQLAlchemy 2.0, Settings, Async/Sync)
- **Memory: Date-Tests Mid-Month**: `~/.claude/projects/-Users-daniel-Desktop-Vibe-Coding-Dashboard-KI-Agenten/memory/feedback_date_tests_pick_mid_month.md`
- **Memory: Templates-Request-First**: `~/.claude/projects/-Users-daniel-Desktop-Vibe-Coding-Dashboard-KI-Agenten/memory/feedback_starlette_templateresponse.md`
- **Memory: Default-User-Role**: `~/.claude/projects/-Users-daniel-Desktop-Vibe-Coding-Dashboard-KI-Agenten/memory/feedback_default_user_role.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- TZ-Bug: SQLite gibt naive datetimes zurueck; `format_stale_hint()` normalisiert naive auf UTC via `replace(tzinfo=timezone.utc)`.
- `bg-amber-50` erscheint auch in `_obj_stammdaten.html` → Test-Assertions auf spezifischen Text "Letzte Aktualisierung" umgestellt.
- `_OPEN_STATUS_FILTER` aus Spike-Doc angepasst: echte Facilioo-Werte "finished"/"deleted" + AC1-Defaults "closed"/"resolved"/"done" kombiniert.
- JSONB-Portabilitaet: `cast(AuditLog.details_json, String).like(...)` statt `['job'].astext` fuer SQLite-Kompatibilitaet in Tests.
- Route: `try/except` um `get_last_facilioo_sync`-Aufruf fuer FR30 (monkeypatch in `test_stale_query_error_is_swallowed` ersetzt die Funktion komplett, internes try/except greift nicht).
- SQL-Count-Test: +2 Queries durch `get_open_tickets_for_object` + `get_last_facilioo_sync`; Limit von 21 auf 23 angehoben.

### Completion Notes List

- Neuer Service `app/services/facilioo_tickets.py` mit 5 oeffentlichen Funktionen + 1 Hilfsfunktion.
- Template `_obj_vorgaenge.html`: 3 Branches (Placeholder / Empty-State+Stale-Banner / Tabelle+Footer), kein Permission-Wrapper, Deeplinks via `facilioo_ticket_url` Global.
- Route `object_detail()`: +4 Context-Vars (facilioo_*), +FR30-try/except um Sync-Query.
- Settings: `facilioo_ui_base_url` + `facilioo_stale_threshold_minutes` in `app/config.py`.
- Templating: `facilioo_ticket_url` als Jinja2-Global registriert.
- 15 neue Tests, alle gruen. Smoke-Tests angepasst (SQL-Count-Limit). Full-Suite: 927 passed.
- **Live-Verifikation offen**: Docker-Container + echte Facilioo-Tenant-Daten (Tickets sichtbar, URL funktioniert, Stale-Banner testen via Mirror-Pause).
- Bei Tag-3-No-Go fuer Facilioo: Story 4.4 ist trotzdem `done` — Placeholder-Pfad (AC3) stellt sicher, dass die Objekt-Detail-Seite nie crasht.

### File List

- `app/services/facilioo_tickets.py` (neu)
- `app/templates/_obj_vorgaenge.html` (neu)
- `tests/test_object_facilioo_section.py` (neu)
- `app/routers/objects.py` (geaendert: Import + 4 Context-Vars + try/except)
- `app/templates/object_detail.html` (geaendert: Include _obj_vorgaenge.html)
- `app/templating.py` (geaendert: facilioo_ticket_url Global)
- `app/config.py` (geaendert: 2 neue Settings)
- `tests/test_steckbrief_routes_smoke.py` (geaendert: SQL-Count-Limit 21→23)
- `output/planning-artifacts/architecture.md` (geaendert: S10 Korrektur)
- `docs/project-context.md` (geaendert: Facilioo-Mirror-Block)
- `output/implementation-artifacts/sprint-status.yaml` (geaendert: 4.4 → review)
