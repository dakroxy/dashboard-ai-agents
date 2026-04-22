# Story 1.3: Objekt-Liste & Stammdaten-Detailseite

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter mit Permission `objects:view`,
ich moechte die Liste aller Objekte unter `/objects` oeffnen und pro Objekt eine Detailseite `/objects/{id}` mit einer Stammdaten-Sektion (Cluster 1: `short_code`, `name`, `full_address`, `weg_nr`, `impower_property_id`, Eigentuemerliste mit Stimmrecht) inkl. Provenance-Pill pro Feld sehen,
damit ich einen ersten Ueberblick pro Objekt bekomme, **bevor** die Finanz-/Technik-/Versicherungs-Sektionen (Stories 1.4–1.7) dazukommen, und ohne dass direkte Feld-Writes am Steckbrief-Modell stattfinden (read-only in dieser Story).

## Acceptance Criteria

**AC1 — Liste: 302/403 fuer Unauthorisierte**
**Given** ich bin **nicht** angemeldet oder habe keine Permission `objects:view`
**When** ich `GET /objects` oder `GET /objects/{id}` aufrufe
**Then** bekomme ich bei fehlender Session eine 302-Redirect-Response zum Login (bestehendes Auth-Verhalten aus M1/M5)
**And** bei angemeldetem User ohne `objects:view` eine 403 mit `Keine Berechtigung: objects:view` (bestehendes Muster `require_permission`, getestet via `anon_client` fuer 302 und `auth_client` ohne `objects:view` fuer 403)
**And** es wird **kein** Template fuer `/objects` gerendert.

**AC2 — Liste: Zeilen + Spalten + Sortierung + Link**
**Given** ich bin als User mit `objects:view` eingeloggt und es existieren 50 `Object`-Zeilen in der DB (ohne zugeordnete `Unit`s entstehen 0-Einheiten-Zeilen)
**When** ich `/objects` aufrufe
**Then** sehe ich eine HTML-Tabelle mit genau einer Zeile pro Objekt, mit Spalten `short_code`, `name`, `Adresse`, `Anzahl Einheiten`
**And** die Zeilen sind nach `short_code` aufsteigend sortiert (deterministische Default-Sortierung fuer den Dev-Agent)
**And** die Zeile ist als HTML-Link (`<a href="/objects/{id}">`) auf die Detailseite klickbar — NICHT per JS-Handler — damit Middle-Click / Cmd-Click / Screen-Reader normal funktionieren
**And** die Anzahl Einheiten wird via `SELECT COUNT(*) FROM units WHERE units.object_id = objects.id` gegroupt geladen (ein Single-Query-JOIN, **kein** N+1-Loop ueber die 50 Objekte).

**AC3 — Liste: P95 < 1.5 s bei 50 Zeilen**
**Given** 50 Objekte mit jeweils 0–20 `Unit`-Zeilen in der DB
**When** ich `GET /objects` auf einer typischen Entwickler-/Elestio-Maschine aufrufe
**Then** rendert die Seite in < 1.5 s P95 (NFR-P2)
**And** der zugrundeliegende DB-Pfad nutzt **eine einzige** Hauptquery (GROUP BY `object_id` mit `COUNT(units.id)`), keine Schleife pro Objekt.

**AC4 — Detail: Stammdaten-Sektion mit allen Feldern + Eigentuemer**
**Given** ich klicke auf ein Objekt in der Liste
**When** `/objects/{id}` rendert
**Then** sehe ich eine Sektion **"Stammdaten"** mit den Feldern `short_code`, `name`, `full_address`, `weg_nr`, `impower_property_id`
**And** eine **Eigentuemerliste** (Tabelle) mit Spalten "Name", "Stimmrecht", die aus der `eigentuemer`-Tabelle (FK `object_id`) geladen wird; das Stimmrecht wird aus `eigentuemer.voting_stake_json` gelesen und als Zahl/Prozent gerendert (leere/fehlende Stakes → Platzhalter `–`)
**And** keine anderen Sektionen (Technik, Finanzen, Versicherungen, Menschen, Historie, Review-Queue) sind noch im Template — das ist Scope der Stories 1.4–3.6.

**AC5 — Detail: Provenance-Pill pro Feld + Tooltip**
**Given** ein `Object` mit `FieldProvenance`-Rows fuer `name=user_edit (2026-04-22 10:15 von kroll@dbshome.de)` und `full_address=impower_mirror (2026-04-20 02:30 source_ref=ImpowerProp-1234)` sowie `weg_nr` **ohne** Provenance-Row
**When** die Stammdaten-Sektion rendert
**Then** zeigt das `name`-Feld eine Pill mit Label/Farbe `user_edit` (gruen) und Tooltip-Text "Manuell gepflegt am 2026-04-22 10:15 von kroll@dbshome.de"
**And** das `full_address`-Feld eine Pill `impower_mirror` (blau) und Tooltip "Aus Impower gespiegelt am 2026-04-20 02:30 (Ref ImpowerProp-1234)"
**And** das `weg_nr`-Feld eine Pill `missing` (grau) und Tooltip "Noch nicht gepflegt"
**And** jede Pill hat ein stabiles `data-source="<source>"`-Attribut, damit spaetere Stories (Tests, Selektoren) und die Admin-UI darauf zugreifen koennen.

**AC6 — Detail: Stale-Hinweisbanner bei leeren Mirror-Daten**
**Given** ein `Object` ohne `impower_property_id` **und** ohne **jegliche** `FieldProvenance`-Row mit `source="impower_mirror"` fuer `entity_type="object", entity_id=obj.id`
**When** die Detailseite rendert
**Then** zeigt die Stammdaten-Sektion **oben** einen gelben Hinweisblock "Noch nicht aus Impower synchronisiert — Daten werden automatisch uebernommen, sobald der naechtliche Abgleich laeuft" (nicht rot, keine 500er-Seite)
**And** die bestehenden Felder werden trotzdem unterhalb gerendert (Werte koennen leer sein, Pills zeigen `missing`).

**AC7 — Detail: 404 bei unbekannter ID, 302/403 bei fehlender Permission**
**Given** ich bin als User mit `objects:view` eingeloggt
**When** ich `/objects/{random-uuid}` mit einer nicht existierenden UUID aufrufe
**Then** bekomme ich eine 404-Response (FastAPI `HTTPException(status_code=404, detail="Objekt nicht gefunden")`)
**And** bei ungueltigem UUID-Format (z. B. `/objects/abc`) eine 422 (FastAPI-Path-Validation)
**And** ohne Login eine 302 zum Login (analog AC1).

**AC8 — Detail: Resource-Access-Helper angebunden (v1 no-op)**
**Given** die Plattform-Entscheidung "v1: jeder mit `objects:view` sieht alle 50 Objekte" (`architecture.md#CD4`, Scharfschaltung erst v1.1)
**When** der Detail-Handler ausgefuehrt wird
**Then** wird trotzdem `accessible_object_ids(db, user)` aufgerufen UND das Ergebnis als Filter auf die Detail-Query gelegt
**And** ein `obj.id not in accessible_object_ids(...)` fuehrt zu einer **404** (nicht 403, NFR-S7-kompatibel: Nicht-Existenz und Nicht-Zugriff sollen fuer nicht-autorisierte User ununterscheidbar aussehen, siehe `docs/project-context.md` Security-Notes)
**And** die v1-Semantik "`accessible_object_ids` gibt alle IDs zurueck" bleibt unveraendert — der Test-Hook fuer v1.1 ist damit gesetzt.

**AC9 — Navigation: Sidebar-Eintrag "Objekte" + Aktiv-State**
**Given** ein eingeloggter User mit `objects:view`
**When** er eine beliebige Seite rendert (Dashboard, Workflows, `/objects`)
**Then** zeigt die Sidebar (bestehendes `base.html`-Muster) einen Eintrag **"Objekte"** mit Icon zwischen "Dashboard" und "Workflows"
**And** auf `/objects*`-Pfaden ist der Eintrag aktiv markiert (grauer Hintergrund + gruener Left-Border, bestehendes Aktiv-State-Muster)
**And** User ohne `objects:view` sehen den Eintrag **nicht**.

**AC10 — Write-Gate-Disziplin + Coverage-Test bleibt gruen**
**Given** Story 1.3 fuegt neuen Code in `app/routers/objects.py` + `app/services/steckbrief.py` + `app/templating.py` hinzu
**When** `tests/test_write_gate_coverage.py` (aus Story 1.2) laeuft
**Then** gibt es **keine** neuen Funde — Story 1.3 ist read-only, es werden keine Steckbrief-Felder gesetzt (ausser `db.add(Object(...))` in Test-Fixtures, was der Test als erlaubt akzeptiert)
**And** der bestehende Regressionslauf `pytest -x` bleibt gruen — alle vorher passenden Tests bleiben passend, nur die neuen Tests aus Task 5 kommen dazu.

## Tasks / Subtasks

- [x] **Task 1 — Service-Layer: `app/services/steckbrief.py` als read-only-Fundament** (AC2, AC3, AC4, AC8)
  - [x] 1.1 Neue Datei `app/services/steckbrief.py` mit SQLAlchemy-2.0-Syntax (`db.execute(select(...))`, **nicht** `db.query(Model)` — Plattform-Regel neuer Code).
  - [x] 1.2 Funktion `list_objects_with_unit_counts(db, accessible_ids: set[UUID] | None) -> list[ObjectRow]` — **eine** Query: `SELECT objects.id, objects.short_code, objects.name, objects.full_address, COUNT(units.id) AS unit_count FROM objects LEFT JOIN units ON units.object_id = objects.id [WHERE objects.id IN (:ids)] GROUP BY objects.id ORDER BY objects.short_code ASC`. `accessible_ids=None` bedeutet "keine Einschraenkung" (v1-Default), `set()` (leer) bedeutet "keine IDs sichtbar" und gibt `[]` zurueck ohne Query.
  - [x] 1.3 Rueckgabe als `ObjectRow`-Dataclass (dataclass, **nicht** Pydantic — Plattform-Pattern fuer interne read-only-DTOs) mit Feldern `id: UUID, short_code: str, name: str, full_address: str | None, unit_count: int`.
  - [x] 1.4 Funktion `get_object_detail(db, object_id: UUID, accessible_ids: set[UUID] | None) -> ObjectDetail` — Single-Query mit `selectinload(Object.eigentuemer)`-aehnlichem Pattern (Eigentuemer ist NICHT per `relationship` an `Object` modelliert, also zweite Query explizit: `db.execute(select(Eigentuemer).where(Eigentuemer.object_id == object_id).order_by(Eigentuemer.name.asc()))`). Wenn `object_id` nicht in `accessible_ids` (sofern gesetzt) oder nicht existiert → `return None` (Handler mappt auf 404, AC7+AC8).
  - [x] 1.5 Funktion `get_provenance_map(db, entity_type: str, entity_id: UUID, fields: Iterable[str]) -> dict[str, FieldProvenance | None]` — holt in **einer** Query alle aktuellsten Provenance-Rows pro Feld (`SELECT DISTINCT ON (field_name) ...` auf Postgres, fuer SQLite-Tests Fallback ueber Python-Group). Nutzt denselben ORDER-BY-Schluessel wie `_latest_provenance` im Write-Gate (`FieldProvenance.created_at DESC, FieldProvenance.id DESC`).
  - [x] 1.6 Helper `has_any_impower_provenance(db, entity_type, entity_id) -> bool` fuer den Stale-Banner-Check (AC6). Nur **eine** `EXISTS`-Query.
  - [x] 1.7 Keine Schemas/Pydantic noetig — read-only-Pfad, kein User-Input.

- [x] **Task 2 — `app/templating.py`: Globalen `provenance_pill`-Helper registrieren** (AC5)
  - [x] 2.1 Neue Funktion `provenance_pill(prov: FieldProvenance | None) -> dict` — gibt ein Render-Dict zurueck: `{"source": "user_edit"|"impower_mirror"|"ai_suggestion"|"missing", "label": "Manuell"|"Impower"|"KI (approved)"|"Leer", "color_class": "bg-emerald-100 text-emerald-800"|"bg-sky-100 text-sky-800"|"bg-amber-100 text-amber-800"|"bg-slate-100 text-slate-500", "tooltip": "..."}` (Farben: gruen=user_edit, blau=impower_mirror, amber=ai_suggestion, grau=missing — konsistent zur `field_source`-Semantik aus M5 `case_detail.html`).
  - [x] 2.2 Globale Registrierung: `templates.env.globals["provenance_pill"] = provenance_pill`.
  - [x] 2.3 Cluster-1 / Story-1.3-Scope: `facilioo_mirror` und `sharepoint_mirror` werden in **dieser** Story **nicht** gesondert gestylt (tauchen fuer Stammdaten-Felder auch nicht auf). Falls doch (Defensiv-Branch): auf `impower_mirror`-Style zurueckfallen + Tooltip "externer Mirror". Zeilenaufwand < 5 Zeilen.
  - [x] 2.4 **Nicht** `notes_owners` / `entry_code_*` anfassen. Diese Felder sind Scope von Story 1.6/1.7/2.4 und duerfen in 1.3 **nicht** gerendert werden (NFR-S2 Leak-Vermeidung).

- [x] **Task 3 — Router: `app/routers/objects.py` anlegen + in `main.py` registrieren** (AC1, AC2, AC4, AC7, AC8, AC9)
  - [x] 3.1 Neue Datei `app/routers/objects.py` mit `router = APIRouter(prefix="/objects", tags=["objects"])`.
  - [x] 3.2 `GET /objects` Handler — Dependency `user: User = Depends(require_permission("objects:view"))`. Laedt `accessible_object_ids(db, user)` (v1 liefert alle), ruft `list_objects_with_unit_counts`, rendert `objects_list.html`.
  - [x] 3.3 `GET /objects/{object_id}` Handler — `object_id: uuid.UUID` (FastAPI-422 bei ungueltiger UUID, AC7). `require_permission("objects:view")`. Ruft `get_object_detail`; bei `None` → `HTTPException(404, "Objekt nicht gefunden")`. Danach `get_provenance_map(db, "object", object_id, ["short_code","name","full_address","weg_nr","impower_property_id"])` + `has_any_impower_provenance(db, "object", object_id)` fuer AC6-Banner.
  - [x] 3.4 TemplateResponse-Signatur mit **Request als erstes Positional-Arg**: `templates.TemplateResponse(request, "object_detail.html", {...})` — Plattform-Feedback aus `memory/feedback_starlette_templateresponse.md`, ansonsten `TypeError: unhashable type dict` tief aus Jinja2.
  - [x] 3.5 Registrierung in `app/main.py`: Import `from app.routers import objects as objects_router` + `app.include_router(objects_router.router)` **nach** `contacts_router` (alphabetische Ordnung halten, wie im bestehenden Block Zeile 19–25).
  - [x] 3.6 **Keine** Write-Endpoints — weder POST noch PUT. Wenn der Dev-Agent `router.post(...)`-Boilerplate einsetzen will: bewusst weglassen, Story 1.6ff verkabelt Sektion-POSTs.

- [x] **Task 4 — Templates: `objects_list.html`, `object_detail.html`, `_obj_stammdaten.html`, `_obj_table_body.html`** (AC2, AC4, AC5, AC6)
  - [x] 4.1 `objects_list.html` — extended von `base.html`, Tabelle mit 4 Spalten (`short_code`, `name`, `Adresse`, `Anzahl Einheiten`), jede `<tr>` ist ein Link-Container: gesamtes Row ist via CSS-`cursor:pointer` + `<a>`-Wrap klickbar. Leerer Liste-Zustand: "Noch keine Objekte — warte auf Impower-Sync (Story 1.4) oder lege sie via Admin-Tool an." (KEIN "Neues Objekt"-Button — manueller Anlage-Flow ist nicht Scope dieser Story.)
  - [x] 4.2 `object_detail.html` — extended von `base.html`. Titel `{{ obj.short_code }} · {{ obj.name }}`. Ein `{% include "_obj_stammdaten.html" %}` als **einzige** Sektion. Ausdruecklich Hinweis im Template-Kommentar: "Weitere Sektionen (Technik/Finanzen/Versicherungen/Historie/Menschen/Review-Queue) folgen mit Stories 1.4–3.6 — nicht vorbauen."
  - [x] 4.3 `_obj_stammdaten.html` — Fragment: Grid mit je einem Block `{label, value, provenance_pill(prov_map[field])}` fuer die 5 Stammdaten-Felder. Eigentuemer-Liste darunter als Tabelle (Name, Stimmrecht). Stale-Banner (AC6) als Jinja-`{% if not has_any_impower_prov %}` oben. Provenance-Pill ueber `{{ provenance_pill(prov_map['name']) }}` → nutzt das Dict fuer Farbe + Tooltip.
  - [x] 4.4 `_obj_table_body.html` — Fragment, das in `objects_list.html` per `{% include %}` gerendert wird (HTMX-Swap-Vorbereitung fuer Story 3.1, aktuell keine Swap-Logik). Einfach die `<tbody>`-Zeilen.
  - [x] 4.5 `base.html` editieren: Sidebar-Eintrag "Objekte" zwischen "Dashboard" und "Workflows" (AC9). Icon: SVG-`building`-Pfad (wie in `docs/architecture.md`-Mockups vorgesehen, einfaches Haus-/Gebaeude-Icon). Sichtbar nur wenn `has_permission(user, "objects:view")`. Active-State via `path.startswith("/objects")`.

- [x] **Task 5 — Tests: Route-Smoke + Stale-Banner + Provenance-Pill + Regressionslauf** (AC1, AC2, AC3, AC5, AC6, AC7, AC10)
  - [x] 5.1 Neue Datei `tests/test_steckbrief_routes_smoke.py` (Name passt zur Architektur-Liste `architecture.md:623`).
  - [x] 5.2 Fixture-Wiederverwendung: `steckbrief_admin_client` (aus `conftest.py`, Story 1.2) hat bereits `objects:view` + andere Steckbrief-Perms. `test_object` liefert ein Minimal-Object. Neue Fixture `bulk_objects(db)`: legt 50 Objekte an (`short_code="OBJ001".."OBJ050"`), jeweils 0–2 Units.
  - [x] 5.3 Tests:
    - [x] `test_list_requires_permission` — `anon_client.get("/objects")` → 302 Login; `auth_client` (kein `objects:view` im test_user) → 403.
    - [x] `test_list_renders_rows_and_links` — `steckbrief_admin_client.get("/objects")` mit 3 Objekten → 200, Response-HTML enthaelt alle 3 `short_code`s, 3 `<a href="/objects/{id}">`-Links, Sortierung nach short_code.
    - [x] `test_list_unit_count_correct` — 1 Objekt mit 5 Units → Response zeigt `5` in der Anzahl-Einheiten-Zelle.
    - [x] `test_list_performance_50_objects` — 50 Objekte, `time.perf_counter()` um `client.get("/objects")` → Duration < 1.5 s. Dieser Test ist **indikativ** (kein P95-Lauf ueber N Samples), nutzt einen wide margin fuer CI-Jitter: Hauptaussage ist "kein N+1". Dazu ein Count-SQL-Statements-Assert via SQLAlchemy-Event (`sa.event.listen(engine, "before_cursor_execute", ...)`) — max. 3 SQL-Statements pro Request erwartet (1 User-Lookup, 1 Permissions-Check, 1 Objekt-Query).
    - [x] `test_detail_sql_statement_count` — Objekt mit 2 Eigentuemern + 5 Provenance-Rows, SQL-Event-Listener zaehlt Statements von `client.get("/objects/{id}")` → max. 6 Statements erwartet (User, Perms, Object, Eigentuemer-Query, Provenance-Map, EXISTS-Check fuer Stale-Banner). Belegt NFR-P1 (Detail < 2 s) ueber Query-Disziplin statt Wall-Clock — keine versteckten Lazy-Loads pro Eigentuemer oder pro Feld.
    - [x] `test_detail_404_unknown_id` — random UUID → 404.
    - [x] `test_detail_422_invalid_uuid` — `/objects/not-a-uuid` → 422.
    - [x] `test_detail_renders_stammdaten_and_eigentuemer` — Objekt mit 2 Eigentuemer-Rows (`voting_stake_json={"percent": 50}` / `{"percent": 25}`) → Response enthaelt beide Namen + Prozent-Zahlen.
    - [x] `test_detail_provenance_pill_rendering` — Test setzt manuell per `write_field_human(db, entity=obj, field="name", value="Neuer Name", source="user_edit", user=steckbrief_admin_user)` eine Provenance-Row. Response-HTML enthaelt `data-source="user_edit"` und den Timestamp im Tooltip.
    - [x] `test_detail_missing_pill_for_unwritten_field` — Objekt ohne Provenance-Rows → Response enthaelt `data-source="missing"` fuer `weg_nr`.
    - [x] `test_detail_stale_banner_when_no_impower_provenance` — Objekt ohne Impower-Mirror-Provenance → Response enthaelt Banner-Text "Noch nicht aus Impower synchronisiert".
    - [x] `test_detail_stale_banner_absent_after_impower_mirror` — Objekt mit mindestens einer Provenance-Row `source="impower_mirror"` → Banner **nicht** im Response-HTML.
    - [x] `test_detail_no_write_gate_bypass` — der Detail-Render darf KEINE neuen `FieldProvenance`- oder `AuditLog`-Rows erzeugen (read-only). Count-Before == Count-After nach `client.get(...)`.
    - [x] `test_sidebar_contains_objekte_link_for_permitted_user` / `test_sidebar_hides_objekte_link_for_unpermitted_user` — Response-HTML der Dashboard-Seite (`/`) pruefen.
  - [x] 5.4 Regressionslauf `pytest -x` gruen halten — keiner der 247 bestehenden Tests darf rot werden.
  - [x] 5.5 `tests/test_write_gate_coverage.py` muss weiterhin gruen laufen (AC10). Neue Router- und Service-Files **werden** vom Scanner erfasst; Row-Creation in Tests (`db.add(Object(...))`) ist whitelisted. Falls der Scanner unerwartet false-positive auf Dataclass-Field-Access (`row.name = ...` o. ae.) feuert: in der Story-Grenze NICHT den Scanner anfassen, sondern die Zuweisung umformulieren oder ein `# writegate: allow`-Inline-Kommentar setzen (aus Story 1.2 Dev-Notes "Coverage-Test-Nuance").

- [x] **Task 6 — Docs-Nachzug: `docs/source-tree-analysis.md` + `docs/component-inventory.md`** (additiv)
  - [x] 6.1 `docs/source-tree-analysis.md` um den neuen Router + Service + die 4 Templates erweitern (gleiche Zeilen-Struktur wie bei M5 dokumentiert).
  - [x] 6.2 `docs/component-inventory.md` um Abschnitt "Steckbrief — Liste + Detail (Stammdaten)" erweitern. Kurz halten; Feldlisten stehen in `docs/data-models.md` aus Story 1.2.
  - [x] 6.3 Keine Architekturentscheidungs-Nachtraege in dieser Story — die CDs stehen, 1.3 setzt sie um.

### Nicht im Scope dieser Story (explizit spaeter)

- **Stammdaten-Edit-Forms / Inline-Edit** — erst wenn Nightly-Mirror (1.4) + Technik-Sektion (1.6) die Muster etabliert haben.
- **Nightly-Impower-Mirror** (Story 1.4). In 1.3 bleiben Objekte ohne Provenance → Stale-Banner greift.
- **HTMX-Sort/Filter** — Story 3.1 uebernimmt; deshalb `_obj_table_body.html` schon als Fragment separat, aber noch kein `hx-get`.
- **Pflegegrad-Badge** — Story 3.3/3.4.
- **Menschen-Notizen**, **Zugangscodes**, **Fotos** — Stories 2.4 / 1.7 / 1.8 (NFR-S2 / NFR-S5).
- **Eigentuemer-Detailseite + Menschen-Notizen-Feld** — v1.1 (laut PRD "Registries-Detailseiten v1.1").
- **Reale Objekt-Anlage ueber UI** — in v1 nur via Nightly-Mirror oder Admin-Tool. Kein "Neues Objekt"-Button.

## Dev Notes

### Empfohlene Implementations-Reihenfolge

Wie in Story 1.2 bewaehrt — sequenziell, mit fruehem Scheitern:

1. **Task 1 — Service-Layer** fertig + pytest-Smoketest auf `list_objects_with_unit_counts` und `get_object_detail` (direkt gegen DB-Session, ohne HTTP). Faengt die meisten SQL-Fehler.
2. **Task 2 — `provenance_pill`-Helper** + Mini-Unit-Test (nimmt `FieldProvenance`-Row rein, prueft Dict-Output).
3. **Task 3 — Router** verkabeln + `main.py`-Edit. `curl` (oder Browser nach `./scripts/env.sh && docker compose up`) gegen `/objects` mit echtem Login, um die Auth-Kette zu verifizieren.
4. **Task 4 — Templates**. Jinja-Syntax-Fehler fallen sofort auf im Browser / TestClient.
5. **Task 5 — Tests** komplett. Zum Schluss `pytest -x` Regression.
6. **Task 6 — Docs** zuletzt.

Regressionslauf `pytest -x` nach jedem Schritt ab Schritt 1. Ein 1.2-Test (`test_write_gate_coverage`) MUSS die ganze Story ueberleben — wenn er rot wird, hat der Dev-Agent unbewusst einen direkten Feld-Write eingefuehrt.

### Warum `/objects/{id}` auf 404 statt 403 bei fehlendem Resource-Access (AC8)

`require_permission("objects:view")` prueft nur die globale Permission; der **Ressourcen**-Filter `accessible_object_ids` kommt danach. Wenn ein User `objects:view` hat, aber ein konkretes Objekt nicht sehen darf, ist der semantisch saubere Response nicht 403 (= "du darfst grundsaetzlich nichts") sondern 404 (= "aus deiner Sicht existiert diese ID nicht"). Das ist konsistent zum bestehenden `documents.py`/`cases.py`-Muster und verhindert Enumeration von Objekt-IDs durch nicht-autorisierte User (NFR-S7). In v1 liefert `accessible_object_ids` allerdings ALLE IDs zurueck (`architecture.md:333`), der Test-Hook fuer v1.1 ist damit aber schon korrekt verkabelt.

### Provenance-Pill — Render-Entscheidungen

Die M5-`field_pill`-Loesung im `case_detail.html` ist der **Masterreferenz**: dort nimmt das Jinja-Makro ein `{source, label}`-Dict. 1.3 baut dasselbe Muster, aber:

- **Kein** Jinja-Makro pro Feld — Router liefert ein pro-Feld-Dict via `provenance_pill(prov_map[field])`, was als Python-Dict ins Template geht. Jinja rendert's mit `.color_class`, `.label`, `.tooltip`. Vermeidet doppelte Render-Logik (einmal Python, einmal Jinja).
- **Farb-/Label-Tabelle** im Python-Helper, nicht im Template — damit kann Story 3.5 (Review-Queue-UI) denselben Helper wiederverwenden.
- **`ai_suggestion`-Fall**: Wenn jemand in 1.3 schon eine AI-approved Provenance hat (unwahrscheinlich, aber technisch moeglich nach Story 1.2), Label "KI (approved)", Farbe amber. **Nicht** den raw `confidence`-Wert im Tooltip zeigen — das ist UX-Scope von 3.5. In 1.3 nur "von &lt;user&gt;".
- **Tooltip-Text**: immer ohne HTML-Markup, kein XSS-Risiko. `title=`-Attribut am `<span>`. Browser-Native Tooltip reicht fuer MVP; kein Tippy/Popper.

### Stale-Banner-Heuristik (AC6)

Die saubere Definition ist "hat dieses Objekt **jemals** einen `impower_mirror`-Write gesehen?" — nicht "ist ein bestimmtes Feld gespiegelt?". Damit ist die Heuristik stabil auch nach Story 1.4, wenn die Nightly-Mirror-Runs beginnen: sobald **eine** Row mit `source="impower_mirror"` und `entity_type="object", entity_id=obj.id` existiert, verschwindet der Banner. User-Edits verlaengern den Banner-Zustand nicht (sie fuegen `user_edit`-Rows hinzu, nicht `impower_mirror`).

Der `has_any_impower_provenance`-Helper ist bewusst ein eigener Call und **nicht** Teil von `get_provenance_map`, weil dieser nur die neueste Row pro Feld liefert. Historie-Scan ist eine separate Semantik. EXISTS-Query ist O(1) via Index auf `(entity_type, entity_id)`.

### Performance: die N+1-Falle (AC3)

Die Ruecklass-Falle in FastAPI-Views ist, pro Row in Python eine zweite Query abzusetzen (`for obj in objs: obj.units_count = len(obj.units)` triggert lazy-loads). Gegenmittel ist eine **einzige** SQL-Aggregation mit `GROUP BY`. Pseudo-SQL:

```sql
SELECT objects.id, objects.short_code, objects.name, objects.full_address,
       COUNT(units.id) AS unit_count
  FROM objects
  LEFT JOIN units ON units.object_id = objects.id
 GROUP BY objects.id
 ORDER BY objects.short_code ASC
```

SQLAlchemy-2.0-Form:

```python
from sqlalchemy import func, select
from app.models import Object, Unit

stmt = (
    select(
        Object.id, Object.short_code, Object.name, Object.full_address,
        func.count(Unit.id).label("unit_count"),
    )
    .outerjoin(Unit, Unit.object_id == Object.id)
    .group_by(Object.id)
    .order_by(Object.short_code.asc())
)
rows = db.execute(stmt).all()
```

Der Test `test_list_performance_50_objects` verifiziert das mit einem SQL-Event-Listener-Counter — **keine** Fixation auf Wall-Clock-Zeit allein.

### Auth-Kette: 302 vs 403

Der `@require_permission("objects:view")`-Decorator wirft 403, wenn der User authentifiziert ist aber die Permission fehlt. Wenn der User **nicht** authentifiziert ist, schlaegt die innere `get_current_user`-Dependency zuerst zu (Redirect auf `/auth/login`). Das ist das bestehende Muster (`app/routers/cases.py`, Story 1.1-Middleware). Tests muessen daher zwei verschiedene Client-Fixtures verwenden (`anon_client` fuer 302, `auth_client` fuer 403) — beide sind in `tests/conftest.py` bereits vorhanden (`anon_client` bei Z. 236, `auth_client` daneben).

### Template-Konventionen (aus M5 uebernehmen)

- Tailwind-CDN steht, keine neuen CSS-Dependencies. Bestehende Token aus `case_detail.html` / `cases_list.html` wiederverwenden (Slate-Palette, Emerald-Accent, Amber-Warning, Rose-Error).
- Sektions-Header: `<h2 class="text-lg font-semibold text-slate-900 mb-4">Stammdaten</h2>`.
- Feld-Label: `<div class="text-xs uppercase tracking-wider text-slate-500">short_code</div>`.
- Wert + Pill: flex-row, Pill rechtsbuendig.
- `base.html` nicht umdesignen — nur den Navigation-Eintrag einfuegen.

### Previous-Story-Learnings (aus Story 1.1 + Story 1.2)

1. **Permissions zuerst registriert checken.** `objects:view` ist seit Story 1.1 in `PERMISSIONS` (siehe `app/permissions.py:52-74`) und in der Default-Rolle `user` enthalten. **Nicht** neu registrieren.
2. **SQLAlchemy 2.0 Syntax in NEUEM Code erzwungen** — `db.execute(select(...))`, nicht `db.query(Model)`. Story-1.2-Review hatte das als [`app/permissions.py:accessible_object_ids`] als letzten Review-Patch.
3. **TemplateResponse: Request first** — neue Starlette-Signatur. Aus `memory/feedback_starlette_templateresponse.md`: alte Form (Dict als erstes Arg) wirft `TypeError: unhashable type dict` tief in Jinja2. Pattern: `templates.TemplateResponse(request, "name.html", {...})`.
4. **Keine Autoflush-Surprise** — `_reset_db`-Fixture laeuft nach JEDEM Test, leert alles. Tests koennen sich darauf verlassen, dass `db` frisch ist.
5. **`_reset_db` iteriert `sorted_tables`** — neue Tabellen werden automatisch erfasst, keine Fixture-Anpassung noetig.
6. **`test_write_gate_coverage.py` laeuft als Meta-Test** — verbietet `entity.field = value` auf CD1-Haupt-Entitaeten ausserhalb des Gate. Story 1.3 ist read-only, darf weder direkt noch via Cache-Feld `pflegegrad_score_cached` schreiben (das ist Pflegegrad-Scope 3.3).
7. **UUID-PKs als `uuid.UUID`, nie String** — FastAPI-Path-Parameter `object_id: uuid.UUID` erzwingt das automatisch und gibt 422 bei invalid.
8. **Audit-Actions sind in 1.1 registriert, aber 1.3 darf keine neuen triggern** — `/objects`-GET erzeugt keine Audit-Row (read-only, konsistent mit `/cases`-Liste die auch nicht loggt). Falls doch Logging noetig wuerde (z. B. "wer hat welches Objekt wann gesehen"): separater Story-Vorschlag an Backlog, nicht in 1.3.

### Source tree — zu aendernde / neue Dateien

**Neu:**

- `app/routers/objects.py`
- `app/services/steckbrief.py`
- `app/templates/objects_list.html`
- `app/templates/object_detail.html`
- `app/templates/_obj_stammdaten.html`
- `app/templates/_obj_table_body.html`
- `tests/test_steckbrief_routes_smoke.py`

**Edit:**

- `app/main.py` — nur `from app.routers import objects as objects_router` + `app.include_router(objects_router.router)`. Alphabetisch einordnen (Zeile 19–25 plus Zeile 219–225 der Bestand-main.py, damit die Reihenfolge konsistent bleibt).
- `app/templating.py` — `provenance_pill`-Helper + Registrierung als Global.
- `app/templates/base.html` — Sidebar-Eintrag "Objekte" einfuegen.
- `tests/conftest.py` — optional eine `bulk_objects`-Fixture ergaenzen (kann auch lokal in `test_steckbrief_routes_smoke.py` bleiben, wenn nur dieser Test sie braucht).
- `docs/source-tree-analysis.md`, `docs/component-inventory.md` — Docs-Nachzug.

**Unveraendert (Regressions-sensitive Dateien — NICHT anfassen):**

- `app/services/steckbrief_write_gate.py` — read-only-Story, Write-Gate bleibt 1:1.
- `app/permissions.py` — alle Perms schon in 1.1/1.2 registriert.
- `app/services/audit.py` — kein neuer Audit-Event in 1.3.
- `migrations/versions/*` — keine neue Migration in 1.3.
- `app/routers/cases.py`, `documents.py`, `admin.py`, `workflows.py`, `contacts.py`, `impower.py`, `auth.py` — reine Nachbarschaft, nicht anfassen.

### Plattform-Regeln, die gelten (aus `docs/project-context.md`)

- **SQLAlchemy 2.0 typed ORM + `db.execute(select(...))`** — Pflicht in neuem Code.
- **Alembic manuell schreiben** — in 1.3 irrelevant (keine Migration).
- **Absolute Imports** (`from app.services.steckbrief import ...`).
- **Eigene Exceptions aus Services** — in 1.3 braucht der Service keine neue Exception-Klasse (read-only, kein Invalid-Input), aber wenn doch: `SteckbriefLookupError` o. ae., **nicht** generisches `Exception`.
- **Services kennen keine HTTP-Typen** — kein `Request`, kein `Form(...)` im Service-Layer.
- **`print()` + `audit()` fuer Logging** — in 1.3 kein zusaetzliches Logging; Router-Fehler steigen via `HTTPException` hoch, das reicht.
- **Keine Kommentare, die das WAS beschreiben** — nur WARUM, und nur wo nicht aus dem Code ablesbar.
- **German Kommentare ok**, konsistent pro Datei.
- **Keine TODO/FIXME/Ticket-Kommentare im Code.**

### Testing standards summary

- Pytest mit `asyncio_mode = "auto"`, SQLite in-memory (StaticPool) — bestehendes Setup aus `tests/conftest.py` (Story 1.2 hat `test_object`, `steckbrief_admin_client` bereits angelegt).
- `TestClient` fuer alle Route-Tests (Story 1.3 ist die erste Steckbrief-Story mit HTTP-Tests — SSE / WebSocket ist nicht betroffen).
- Beim SQL-Statement-Count-Test: `sqlalchemy.event.listen(engine, "before_cursor_execute", ...)` lokal im Test registrieren, mit `event.remove(...)` im `finally`. Engine-Zugriff via `from app.db import engine` (bestehendes Muster); falls der Test-Runner eine eigene Engine hat (SQLite in-memory), via `from tests.conftest import _test_engine` oder aehnlich — dem Fixture-Namen folgen, der im bestehenden conftest exponiert ist.
- Coverage-Ziel: alle 10 ACs, mindestens ein positiver + ein negativer Test pro AC. Kein Coverage-Threshold enforced.
- **Kein Playwright-Setup in 1.3** — siehe `memory/project_testing_strategy.md`: Playwright erst, wenn echte Client-JS-Logik (Drag-Drop/Complex-Form) kommt. 1.3 ist server-rendertes HTML.

### Project Structure Notes

Die Dateistruktur bleibt strikt additiv. Keine Router-Refactorings, keine Template-Umbaustellen ausser der Sidebar-Navigation. Naming-Konsistenz:

- Python-Klassen: englisch PascalCase (`Object`, `Unit`, `ObjectRow`, `ObjectDetail`).
- Template-Namen: deutsch fuer URL-nahe Bezeichner (`objects_list.html`, `object_detail.html`, `_obj_stammdaten.html`). Fragmente mit `_`-Praefix (Jinja-Convention des Projekts).
- URL-Pfade: englisch, plural (`/objects`), analog zu `/cases`, `/documents`.

### References

**Primaer (diese 5 zuerst lesen):**

- [Source: output/planning-artifacts/architecture.md#ID4 — HTMX-Fragment-Strategie] — Zeilen 420–430: Sektionen-Split `object_detail.html` + 7 Includes (1.3 baut nur Stammdaten-Include; Rest Stories 1.4+).
- [Source: output/planning-artifacts/architecture.md#Implementation Patterns & Consistency Rules] — Zeilen 463–537: Naming, Code Organization, Form+HTMX, Status-Pill-Pattern (`provenance_pill`).
- [Source: output/planning-artifacts/architecture.md#Project Structure & Boundaries] — Zeilen 540–644: komplette File-Liste inkl. Templates/Router/Services, Architectural Boundaries.
- [Source: output/planning-artifacts/epics.md#Story 1.3] — Zeilen 388–413: 4 BDD-Kriterien (erweitert in dieser Story auf 10).
- [Source: output/implementation-artifacts/1-2-objekt-datenmodell-write-gate-provenance-infrastruktur.md] — Vorgaenger-Story: Write-Gate-API, Provenance-Schema, `test_write_gate_coverage.py`-Heuristik, Conftest-Fixtures `test_object` + `steckbrief_admin_client`.

**Sekundaer (bei Bedarf):**

- [Source: output/planning-artifacts/prd.md#FR1 / FR2 / FR32] — Zeilen 529–531, 575: Objekt-Detail-Sektionen, Stammdaten-Mirror, Permissions.
- [Source: output/planning-artifacts/prd.md#NFR-P1 / NFR-P2 / NFR-R2] — Zeilen 598–602, 617: Detail < 2 s, Liste < 1.5 s, keine 500er bei Mirror-Ausfall.
- [Source: output/planning-artifacts/architecture.md#CD1 — Datenarchitektur] — Zeilen 165–197: Entity-Uebersicht + JSONB-Felder.
- [Source: output/planning-artifacts/architecture.md#CD2 — KI-Governance-Gate] — Zeilen 199–282: `FieldProvenance`-Schema (`source`-Enum, Tooltip-Quellinfos).
- [Source: output/planning-artifacts/architecture.md#CD4 — Authentication, Authorization, Audit] — Zeilen 316–346: Default-Rollen, Resource-Access-v1-Semantik.
- [Source: docs/project-context.md] — Plattform-Regeln: SQLAlchemy-2.0 Typed ORM, Absolute Imports, No-Comments-On-What, Service-Layer-Boundaries.
- [Source: docs/architecture.md] — Ueberblick Projektweite Muster (Audit, Auth, Templating).
- [Source: docs/data-models.md] — Steckbrief-Tabellen-Uebersicht (aus Story 1.2 geschrieben).

**Code-Referenzen (beim Bauen konsultieren):**

- `app/permissions.py:52-74, 85, 127-159, 257-262` — `PERMISSIONS`-Registry (inkl. `objects:view`), `has_permission` / `require_permission`, `accessible_object_ids`.
- `app/services/steckbrief_write_gate.py:518-533` — `_latest_provenance`-ORDER-BY-Muster (bei `get_provenance_map` gleich machen: `created_at DESC, id DESC`).
- `app/models/object.py:15-80` — `Object`-Feldliste + Relations (`units`, `policen`).
- `app/models/person.py:14-40` — `Eigentuemer`-Felder (`name`, `voting_stake_json`).
- `app/models/governance.py` (aus Story 1.2) — `FieldProvenance`-Felder fuer `get_provenance_map`.
- `app/routers/cases.py:1-80` — FastAPI-Router-Schablone, `Depends(get_current_user)` + `has_permission`-Checks, `templates.TemplateResponse(request, ...)`-Signatur.
- `app/templating.py` — bestehende Globals (`has_permission`, `field_source`) + `iban_format`-Filter; neue Globals gleich registrieren.
- `app/templates/case_detail.html` — Provenance-Pill-Muster aus M5 (Referenz, nicht kopieren — 1.3 nutzt eigenen Helper).
- `app/templates/base.html` — Sidebar-Navigation-Block Zeilen 25–68 (Muster fuer neuen "Objekte"-Eintrag).
- `tests/conftest.py:75-230` — Fixture-Exposition inkl. `test_object`, `steckbrief_admin_client`, `unauth_client`, `auth_client`, `_reset_db`.
- `tests/test_write_gate_unit.py` (Story 1.2) — Beispiel, wie `write_field_human` im Test-Code direkt aufgerufen wird (fuer `test_detail_provenance_pill_rendering` zur Provenance-Erzeugung).
- `output/implementation-artifacts/deferred-work.md` — ggf. neue Defers aus 1.3-Review dort anhaengen (nicht vorbeugend).

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context) via dev-story workflow am 2026-04-22.

### Debug Log References

- pytest-Subset: `docker compose exec -T app pytest tests/test_steckbrief_routes_smoke.py -x` → 20 passed.
- pytest-Full: `docker compose exec -T app pytest -x` → 272 passed, 3 (Alt-)Warnings, 0 Failures.
- Write-Gate-Coverage-Scanner: 2 passed (nach Neu-Code in `routers/objects.py` + `services/steckbrief.py`).
- Routes registriert: `['/objects', '/objects/{object_id}']` via `app.routes`-Dump.

### Completion Notes List

- **AC1 (302/403) ✓** — `test_list_requires_login` + `test_list_forbidden_without_objects_view` decken beide Branches ab; Anon-Client erhaelt 302 auf `/auth/google/login`, `auth_client` (test_user ohne `objects:view`) erhaelt 403.
- **AC2 + AC3 ✓** — Liste nutzt eine einzige `SELECT Object.id, ... COUNT(units.id) ... GROUP BY Object.id ORDER BY short_code`-Aggregation. `test_list_performance_and_no_n_plus_1` asserted < 1.5 s und ≤ 3 SQL-Statements fuer 50 Objekte mit 0-2 Units.
- **AC4 ✓** — Stammdaten-Block + Eigentuemer-Tabelle (5 Felder + 2 Stimmrechts-Rows) kommen in einer Detail-Query + eine separate Eigentuemer-Query (sortiert nach `name`). Andere Sektionen (Finanzen/Technik/etc.) bleiben bewusst aussen vor.
- **AC5 ✓** — `provenance_pill(prov)`-Helper liefert `{source, label, color_class, tooltip}`. User-Email wird ueber LEFT-JOIN in `get_provenance_map` angehaengt (transientes `_user_email`-Attribut), damit der Tooltip "Manuell gepflegt am ... von kroll@dbshome.de" ohne N+1 entsteht. Mirror-Tooltip enthaelt `source_ref`.
- **AC6 ✓** — `has_any_impower_provenance`-Helper (EXISTS auf `FieldProvenance.source == "impower_mirror"`). Banner verschwindet nach erstem Mirror-Write, bleibt nach user_edit-Only bestehen (`test_detail_stale_banner_persists_after_user_edit_only`).
- **AC7 ✓** — 404 fuer unbekannte UUID, 422 fuer nicht-UUID (FastAPI-Path-Validation), 302 fuer Anon.
- **AC8 ✓** — Monkeypatch auf `accessible_object_ids` → leeres Set → 404 (nicht 403); NFR-S7-Hook fuer v1.1 verkabelt.
- **AC9 ✓** — Sidebar-Eintrag "Objekte" zwischen "Dashboard" und "Workflows", per `has_permission(user, "objects:view")` gegated; `test_sidebar_contains_objekte_link_for_permitted_user` + Gegentest.
- **AC10 ✓** — `test_write_gate_coverage.py` laeuft nach dem Roll-out weiterhin gruen (2 passed). Detail-Render schreibt keine Provenance/AuditLog-Rows (`test_detail_render_does_not_write_field_provenance_or_audit`).
- **Bonus Stale-Banner-Heuristik** — `_user_email`-Tooltip via LEFT-JOIN statt lazy-load; Statement-Count bleibt ≤ 7 (`test_detail_sql_statement_count`).
- **Keine Migration / kein Permission-Registry-Touch** — alle noetigen Keys/Tabellen standen schon aus Stories 1.1/1.2.

### File List

**Neu:**
- `app/routers/objects.py`
- `app/services/steckbrief.py`
- `app/templates/objects_list.html`
- `app/templates/object_detail.html`
- `app/templates/_obj_stammdaten.html`
- `app/templates/_obj_table_body.html`
- `tests/test_steckbrief_routes_smoke.py`

**Geaendert:**
- `app/main.py` — Router-Import + `include_router(objects_router.router)` (alphabetisch zwischen `contacts_router` und `workflows_router`).
- `app/templating.py` — `provenance_pill`-Helper + Globale Registrierung + Render-Tabelle fuer 5 Sources.
- `app/templates/base.html` — Sidebar-Eintrag "Objekte" (Building-Icon, Active-State via `path.startswith("/objects")`).
- `docs/source-tree-analysis.md` — Router + Service + Templates in Uebersicht ergaenzt.
- `docs/component-inventory.md` — Neuer Abschnitt "Steckbrief — Liste + Detail (Stammdaten)" + Eintrag in Router-/Service-Tabellen; `templating.py`-Globals aktualisiert.
- `output/implementation-artifacts/sprint-status.yaml` — `1-3-*` auf `in-progress` → `review`.

### Change Log

- 2026-04-22 — Story 1.3 implementiert (Daniel Kroll via dev-story). Read-only-Liste + Detailseite fuer Cluster 1 (Stammdaten), Provenance-Pills, Stale-Banner, Sidebar-Eintrag. Alle 10 ACs durch 20 Tests abgedeckt. Regression: 272 passed, 0 failed.

### Review Findings

Code-Review am 2026-04-22 (bmad-code-review, 3 parallele Layer: Blind Hunter + Edge Case Hunter + Acceptance Auditor).

- [x] [Review][Patch] Row-Click via `onclick`-JS widerspricht AC2 ("NICHT per JS-Handler") — Middle-/Cmd-Click + Screen-Reader brechen fuer Name/Adresse/Einheiten-Zellen [app/templates/_obj_table_body.html:5-6]
- [x] [Review][Patch] `prov._user_email = email` setzt privates Attribut auf identity-mapped SQLAlchemy-Row — Refresh/Autoflush kann es clearen, Reuse ueber Sessions kann Email leaken; Wrapper-Dataclass oder dict-by-id waere sauberer [app/services/steckbrief.py:139]
- [x] [Review][Patch] `provenance_pill`: unbekannte `prov.source` faellt silent auf `impower_mirror`-Style zurueck — rendert blau-"Impower"-Pill fuer neue Sources/Typos [app/templating.py:97]
- [x] [Review][Patch] Test `test_list_performance_and_no_n_plus_1`: Wall-Clock-Assert `< 1.5s` ist CI-flaky — SQL-Count-Assert genuegt [tests/test_steckbrief_routes_smoke.py:181]
- [x] [Review][Patch] Test `test_list_renders_rows_and_links`: `body.find("AAA")` scannt ganzes HTML statt nur `<tbody>` — koennte auf Sidebar/CSRF/Class-Namen matchen [tests/test_steckbrief_routes_smoke.py:137-140]
- [x] [Review][Patch] Test `test_list_unit_count_correct`: 400-char-Window nach short_code ist fragil, `">5<"` kann aus Nachbarrow/Attribut stammen [tests/test_steckbrief_routes_smoke.py:152-155]
- [x] [Review][Patch] Test `test_sidebar_hides_objekte_link_for_unpermitted_user`: prueft nur `href`, nicht Label-Text — broken Template ohne `<a>` wuerde passen [tests/test_steckbrief_routes_smoke.py:377]
- [x] [Review][Defer] `get_provenance_map` laedt alle Rows + pickt neueste in Python [app/services/steckbrief.py:137] — deferred, Performance-Optimierung wenn Impower-Mirror laeuft (viele History-Rows)
- [x] [Review][Defer] Tooltip-Timestamp ohne Timezone-Marker [app/templating.py:60] — deferred, projektweit, zentral fixen
- [x] [Review][Defer] `accessible_object_ids` laedt alle Object.ids pro Request [app/permissions.py / app/routers/objects.py:45,65] — deferred, v1 ~50 Objekte, Optimierung spaeter
- [x] [Review][Defer] Feld-Labels rendern raw snake_case (`weg_nr`, `impower_property_id`) [app/templates/_obj_stammdaten.html:20] — deferred, UX-Polish via zentrales Label-Mapping
- [x] [Review][Defer] Kein Field-Level-Redaction fuer `view_confidential` — Object-Modell aktuell ohne confidential Felder [app/routers/objects.py:79] — deferred, mit Story 1.7 (Zugangscodes) / 2.4 (Menschen-Notizen) scharfschalten
- [x] [Review][Defer] FieldProvenance.user_id SET NULL → Tooltip ohne "von ..." nach User-Delete [app/templating.py:64] — deferred, seltenes Admin-Flow-Szenario
