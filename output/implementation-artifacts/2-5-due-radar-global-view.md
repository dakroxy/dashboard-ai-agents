# Story 2.5: Due-Radar Global-View

Status: ready-for-dev

## Story

Als Mitarbeiter mit `due_radar:view`,
ich möchte eine portfolio-weite Liste aller Policen und Wartungspflichten mit Ablauf innerhalb der nächsten 90 Tage sehen,
damit keine Kündigungsfenster unbemerkt verstreichen.

## Acceptance Criteria

1. **AC1 — Liste:** `GET /due-radar` liefert eine HTML-Seite (Status 200) mit einer Tabelle aller Policen (`policen.next_main_due`) und Wartungspflichten (`wartungspflichten.next_due_date`), deren Fälligkeitsdatum `<= today + 90 Tage` liegt. Jede Zeile zeigt: Typ (Police / Wartung), Objekt-`short_code`, Titel, Fälligkeits-Datum, verbleibende Tage, Severity-Badge.
2. **AC2 — Severity-Badge:** Einträge mit `days_remaining < 30` tragen einen roten Badge "< 30 Tage". Einträge mit `30 <= days_remaining < 90` tragen einen orangen Badge "< 90 Tage". Überfällige Einträge (`days_remaining < 0`) werden ebenfalls aufgelistet und als "überfällig" markiert.
3. **AC3 — Leerer State:** Gibt es keine Einträge im 90-Tage-Fenster, erscheint der Text "Keine ablaufenden Einträge in den nächsten 90 Tagen."
4. **AC4 — Permission-Gate:** Ohne `due_radar:view` liefert `/due-radar` HTTP 403. Nicht eingeloggte User werden zu `/auth/login` weitergeleitet (302).
5. **AC5 — Sidebar-Link:** In `base.html` erscheint ein "Due-Radar"-Eintrag in der Sidebar, der nur Usern mit `due_radar:view` angezeigt wird und den Pfad `/due-radar` markiert wenn aktiv.
6. **AC6 — Unit-Tests:** `tests/test_due_radar_unit.py` besteht — mindestens 5 Testfälle: leer bei fehlenden accessible_ids, Police-Eintrag korrekt, Wartung-Eintrag korrekt (JOIN via policen), Severity-Schwellen, leerer State bei 0 Treffern.

## Tasks / Subtasks

- [ ] Task 1: Service `app/services/due_radar.py` erstellen (AC: 1, 2, 3)
  - [ ] `DueRadarEntry` Dataclass mit Feldern: `kind`, `entity_id`, `object_id`, `object_short_code`, `due_date`, `days_remaining`, `severity`, `title`, `link_url`
  - [ ] `list_due_within(db, *, days: int = 90, accessible_object_ids: set[uuid.UUID], severity: str | None = None, types: list[str] | None = None) -> list[DueRadarEntry]` implementieren. `severity`/`types` bleiben in dieser Story ungenutzt (Story 2.6 verdrahtet sie) — aber Signatur jetzt korrekt bauen, verhindert Refactoring in 2.6.
  - [ ] **Early-Return bei leerem Input**: `if not accessible_object_ids: return []` vor den Queries — sonst `SAWarning: The IN-predicate on ... was invoked with an empty sequence` auf Postgres. Muster: `services/steckbrief.py:58–59`.
  - [ ] Police-Query: `select(InsurancePolicy.id, .object_id, .next_main_due, .versicherer_id, Object.short_code, Versicherer.name)` mit `.join(Object, ...).outerjoin(Versicherer, ...)` — filter auf `next_main_due IS NOT NULL AND next_main_due <= cutoff AND object_id IN (accessible_object_ids)` (Set direkt, keine `list(...)`-Konversion — siehe Dev Notes "Was existiert")
  - [ ] Wartung-Query: `select(Wartungspflicht.id, .bezeichnung, .next_due_date, InsurancePolicy.object_id, Object.short_code)` mit `.join(InsurancePolicy, InsurancePolicy.id == Wartungspflicht.policy_id).join(Object, ...)` — filter auf `policy_id IS NOT NULL AND next_due_date IS NOT NULL AND next_due_date <= cutoff AND InsurancePolicy.object_id IN (accessible_object_ids)`
  - [ ] Beide Listen nach `due_date` zusammenführen + sortieren
  - [ ] `days_remaining = (due_date - date.today()).days` — kann negativ sein (überfällig)
  - [ ] Severity: `"< 30 Tage"` wenn `days_remaining < 30` (inkl. negativer Werte für überfällige Einträge), sonst `"< 90 Tage"`. **Keine dritte Severity-Stufe `"überfällig"`** — die "überfällig"-Anzeige ist reine Template-Logik in der Verbleibend-Zelle (Task 3, siehe AC2), der Severity-Badge bleibt rot "< 30 Tage".
  - [ ] Title: Police → `versicherer_name or "Police"`, Wartung → `bezeichnung`
  - [ ] `link_url`: immer `/objects/{object_id}#versicherungen` für beide Typen

- [ ] Task 2: Router `app/routers/due_radar.py` erstellen (AC: 1, 4)
  - [ ] `APIRouter(prefix="/due-radar", tags=["due-radar"])`
  - [ ] `GET ""` Handler: `require_permission("due_radar:view")`, `accessible = accessible_object_ids(db, user)`, `entries = list_due_within(db, accessible_object_ids=accessible)` → `templates.TemplateResponse(request, "due_radar.html", {"title": "Due-Radar", "user": user, "entries": entries})`. Set wird direkt übergeben — kein `list(...)`-Wrapping (Muster: `routers/objects.py:97–98`).
  - [ ] Kein separater HTMX-Fragment-Endpoint in dieser Story — Story 2.6 ergänzt `/due-radar/rows` mit Filterparametern

- [ ] Task 3: Templates erstellen (AC: 1, 2, 3, 5)
  - [ ] `app/templates/due_radar.html` — extends `base.html`, enthält Seitenheader + `<table>` mit `thead` + `{% include "_due_radar_rows.html" %}`
  - [ ] `app/templates/_due_radar_rows.html` — `<tbody id="due-radar-rows">` mit `{% for entry in entries %}` Zeilen + Empty-State-Fallback; tbody-ID ist Pflicht weil Story 2.6 HTMX `hx-target="#due-radar-rows"` nutzt
  - [ ] Tabellenkolumnen: Typ | Objekt | Titel | Fälligkeit (`dd.MM.yyyy`) | Verbleibend | Schwere
  - [ ] Verbleibend-Zelle: `days_remaining < 0` → "überfällig" (rot), sonst `{days_remaining} Tage` (rot < 30, orange sonst)
  - [ ] Severity-Badge: `bg-red-100 text-red-700` für "< 30 Tage", `bg-orange-100 text-orange-700` für "< 90 Tage"
  - [ ] Objekt-Kürzel als `<a href="/objects/{{ entry.object_id }}">` Link
  - [ ] Titel als `<a href="{{ entry.link_url }}">` Link

- [ ] Task 4: Router in `app/main.py` registrieren + Sidebar ergänzen (AC: 4, 5)
  - [ ] In `app/main.py`: `from app.routers import due_radar as due_radar_router` importieren + `app.include_router(due_radar_router.router)` eintragen (analog zu `objects_router`, alphabetisch sortiert)
  - [ ] In `app/templates/base.html`: Due-Radar Sidebar-Link nach dem Objekte-Block einfügen, nur wenn `has_permission(user, "due_radar:view")`. Die `path`-Variable kommt aus `{% set path = request.url.path %}` (bereits in `base.html:26` gesetzt — nicht neu deklarieren); Active-State via `path.startswith("/due-radar")`. Tailwind-Klassen + `<svg>`-Wrapping 1:1 analog zum Objekte-Link-Block in `base.html:41–52` kopieren. Uhr-Icon-Path: `<path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>`

- [ ] Task 5: Tests `tests/test_due_radar_unit.py` (AC: 6)
  - [ ] `test_empty_when_no_accessible_ids()` — `list_due_within(db, accessible_object_ids=set())` → `[]` (Early-Return ohne DB-Roundtrip)
  - [ ] `test_police_entry_included_within_90_days()` — Police mit `next_main_due = today + 30` erscheint im Ergebnis, `kind="police"`, `title == versicherer.name`
  - [ ] `test_wartung_entry_via_police_join()` — Wartung ohne direktes `object_id`, erfordert JOIN via `policen`; `kind="wartung"`, `title == bezeichnung`
  - [ ] `test_severity_under_30_days_red()` — `days_remaining=15` → `severity="< 30 Tage"`
  - [ ] `test_severity_30_to_90_days_orange()` — `days_remaining=45` → `severity="< 90 Tage"`
  - [ ] `test_overdue_entry_included_and_severity_stays_red()` — `next_main_due = today - 5` (überfällig, `days_remaining < 0`) erscheint im Ergebnis (Cutoff `<= today + 90`) und hat `severity="< 30 Tage"` (keine separate "überfällig"-Severity)

- [ ] Task 6: Smoke-Tests + Sidebar-Gate + Regression (AC: 4, 5)
  - [ ] Neue Datei `tests/test_due_radar_routes_smoke.py` anlegen — eigene Datei pro Feature ist die aktuelle Konvention seit Story 1.3 (siehe `test_technik_routes_smoke.py`, `test_zugangscodes_routes_smoke.py`, `test_foto_routes_smoke.py`). **Nicht** in `test_routes_smoke.py` einfügen.
  - [ ] Lokale Fixture `due_radar_user` (analog `steckbrief_admin_user` in `test_steckbrief_routes_smoke.py:19–45`) mit `permissions_extra=["due_radar:view", "objects:view"]` — `objects:view` ist nötig, damit `accessible_object_ids` nicht leer zurückkommt (v1-Semantik `permissions.py:257–270`).
  - [ ] Lokale Fixture `due_radar_client` (analog `steckbrief_admin_client`) mit `app.dependency_overrides` für diesen User.
  - [ ] `test_requires_login(anon_client)` — unauthenticated → 302, `location` startet mit `/auth/google/login`
  - [ ] `test_forbidden_without_due_radar_view(auth_client)` — `test_user` aus `conftest.py` hat `due_radar:view` **nicht** → 403, Detail-Meldung enthält `"due_radar:view"`
  - [ ] `test_ok_for_user_with_permission(due_radar_client)` — 200, `"text/html"` im Content-Type
  - [ ] `test_empty_state_text(due_radar_client)` — AC3: bei 0 Einträgen erscheint "Keine ablaufenden Einträge in den nächsten 90 Tagen"
  - [ ] `test_sidebar_link_visible_for_permitted_user(due_radar_client)` — GET `/` → Body enthält `'href="/due-radar"'` (AC5 positive)
  - [ ] `test_sidebar_link_hidden_for_unpermitted_user(auth_client)` — GET `/` → weder `'href="/due-radar"'` noch das Wort "Due-Radar" im Body (AC5 negative; Muster: `test_steckbrief_routes_smoke.py:388–396`)
  - [ ] `pytest tests/` grün (aktuell 478 Tests nach Story 1.8)

## Dev Notes

### Was existiert — NICHT neu bauen

- **Permission `due_radar:view`**: bereits registriert in `app/permissions.py:PERMISSIONS` und bereits in `DEFAULT_ROLE_PERMISSIONS["user"]` — keine Änderung an `permissions.py` nötig.
- **Tabellen `policen` + `wartungspflichten`**: angelegt in Migration `0010_steckbrief_core.py` — keine neue Migration nötig.
- **`accessible_object_ids(db, user)`** in `app/permissions.py`: gibt `set[uuid.UUID]` zurück. Direkt ans Service übergeben — SQLAlchemy 2.0 `.in_(accessible_set)` akzeptiert Sets (bestehende Muster: `services/steckbrief.py:50,74` und `main.py:362`). Keine `list(...)`-Konversion nötig oder erwünscht.
- **v1-ACL-Semantik** (`permissions.py:257–270`): wer `objects:view` hat, sieht **alle** Objekte; wer `objects:view` nicht hat, bekommt `set()` zurück → Due-Radar bleibt leer, auch wenn User `due_radar:view` hat. Das ist erwünscht (kein Lookup auf Objekt-Daten ohne Objekt-Sichtbarkeit). Test-User für die Smoke-Tests brauchen deshalb **beide** Permissions (`due_radar:view` + `objects:view`).
- **`require_permission("...")`**: FastAPI-Dependency in `app/permissions.py` — gleich einbinden wie in allen anderen Routern.
- **`templates.TemplateResponse(request, "name.html", {...})`**: Request muss ERSTES Argument sein (Memory: `feedback_starlette_templateresponse`).
- **Sidebar-Pattern in `base.html`**: Exaktes Tailwind-Muster für Nav-Links liegt bereits dreifach vor (Dashboard, Objekte, Workflows, Admin) — kopieren und anpassen, nicht erfinden.

### Kritisches Schema-Detail: Wartungspflichten hat KEIN `object_id`

`Wartungspflicht.policy_id → InsurancePolicy.id → InsurancePolicy.object_id`. Die Wartungs-Query muss **zwei JOINs** machen: erst `JOIN policen ON policen.id = wartungspflichten.policy_id`, dann `JOIN objects ON objects.id = policen.object_id`. Wartungspflichten mit `policy_id IS NULL` können nicht zugeteilt werden — explizit `WHERE policy_id IS NOT NULL` filtern.

### Query-Ansatz: Zwei separate Queries, in Python mergen (weicht bewusst von Architecture ID2 ab)

Architecture ID2 definiert die **Funktionssignatur** und die **Rückgabe-Dataclass** `DueRadarEntry` — beides ist verbindlich. Das dort skizzierte UNION-ALL-Query-Pattern wird in dieser Story **bewusst nicht** übernommen: Spalten-Mapping bei `union_all()` mit heterogenen Typen (Police liefert `versicherer_id`, Wartung liefert `bezeichnung`; `policen.next_main_due` vs. `wartungspflichten.next_due_date`) ist fehleranfällig und erzeugt SQLAlchemy-Warnings, wenn die Typen nicht exakt übereinstimmen. Stattdessen: zwei separate `db.execute(select(...))` Aufrufe (Police-Query + Wartung-Query), Ergebnisse zu `DueRadarEntry`-Instanzen mappen, dann gemeinsam nach `due_date` sortieren. Volume ist < 30 Zeilen → kein Performance-Problem, NFR-P3 (P95 < 2 s) trivial erfüllt.

### Template-Fragment-Namenskonvention

`_due_radar_rows.html` mit Underscore-Prefix (Fragment) gemäss Convention in `docs/project-context.md`. Der `<tbody>` braucht `id="due-radar-rows"` — Story 2.6 nutzt `hx-target="#due-radar-rows"` für Filter-HTMX-Swaps. Jetzt schon korrekt benennen, damit Story 2.6 kein Refactoring braucht.

### Kein BackgroundTask, kein Claude-Call

Diese Story ist pure Read-Query. Keine `BackgroundTasks`, keine Sessions-Fallstricke, kein `asyncio.run()`.

### Security-AC (Epic-1-Retro Action P2 — Permission + accessible_object_ids)

**P2-konform** via zwei Schichten:

1. **Permission-Gate am Router**: `Depends(require_permission("due_radar:view"))`.
2. **Objekt-ACL am Service-Boundary**: Router ruft `accessible_object_ids(db, user)` und übergibt das Set an `list_due_within(...)`. Der Service enforced es in `WHERE object_id IN (accessible_object_ids)` (Police-Query) bzw. `WHERE InsurancePolicy.object_id IN (accessible_object_ids)` (Wartung-Query). Bei leerem Set → Early-Return `[]` (siehe Task 1).

Kein `/due-radar/{id}`-Detail-Endpoint in dieser Story — die Seite ist reine Aggregat-View, deshalb keine weitere Router-Level-ACL nötig. Kein Datenleck möglich.

### InsurancePolicy `versicherer`-Relationship noch nicht definiert

Das ORM-Model `app/models/police.py` hat aktuell nur `object: relationship("Object", ...)`. Die `versicherer`-Relationship fehlt (Story 2.1 fügt sie ggf. hinzu). Deshalb: `outerjoin(Versicherer, Versicherer.id == InsurancePolicy.versicherer_id)` direkt in der Query — KEIN lazy-loaded Relationship nutzen. Das ist sicherer und verhindert N+1.

### Kein Audit-Log nötig

`list_due_within` ist ein reiner Read-Service. Kein `audit()`-Call.

### Router-Imports in `main.py`

Bestehende Imports folgen dem Schema:
```python
from app.routers import due_radar as due_radar_router
# ...
app.include_router(due_radar_router.router)
```
Alphabetisch sortiert nach den anderen Router-Importen einfügen.

### Test-Setup

SQLite-in-memory via `tests/conftest.py`. Vorhandene Fixtures:

- `db` — frische DB-Session pro Test
- `test_user` — Default-User mit nur `["documents:upload", "documents:view_all", "documents:approve", "workflows:view"]` (**nicht** `due_radar:view`) — perfekt für 403-Tests
- `auth_client` — TestClient mit `test_user` als Dependency-Override
- `steckbrief_admin_client` / `steckbrief_admin_user` (in `test_steckbrief_routes_smoke.py`) — Admin-User mit vielen Objekt-Perms; **nicht** direkt wiederverwendbar, da er `due_radar:view` nicht hat
- `anon_client` — unauthenticated
- `test_object` / `make_object` — Test-Objekte

**Kein `user`-Fixture, kein `workflow`-Fixture.** Für Tests, die einen User mit `due_radar:view` brauchen, eigene Fixture bauen — Muster: `steckbrief_admin_user` in `test_steckbrief_routes_smoke.py:19–45` (`User(...)` mit `permissions_extra=[...]`, `db.add`, `db.commit`, `db.refresh`). Für Client analog `steckbrief_admin_client` in `conftest.py:199–236`.

Import-Idiom: `from app.models import InsurancePolicy, Wartungspflicht, Versicherer, Object` — alle sind in `app/models/__init__.py` re-exportiert (verwendet z. B. `services/steckbrief.py:18`). Nicht aus den Submodulen importieren.

### Deferred (nicht in dieser Story)

- Filter-Controls (Typ-Filter, Severity-Filter) → Story 2.6
- Deep-Links zu spezifischen Policen/Wartungen in der Zielseite → Story 2.6
- Verwaltervertrag (`management_contract`-Tabelle) im Due-Radar — Tabelle existiert noch nicht, Story 2.5 scope ist nur policen + wartungspflichten

### Project Structure Notes

Neue Dateien dieser Story:
- `app/services/due_radar.py` — neuer Service (Pattern: `app/services/steckbrief.py` als Referenz für Query-Dataclass-Pattern)
- `app/routers/due_radar.py` — neuer Router (Pattern: `app/routers/objects.py` erste 100 Zeilen)
- `app/templates/due_radar.html` — neue Seite (Pattern: `app/templates/objects_list.html`)
- `app/templates/_due_radar_rows.html` — neues Fragment (Pattern: `app/templates/_obj_table_body.html`)
- `tests/test_due_radar_unit.py` — Unit-Tests für `list_due_within` (Task 5)
- `tests/test_due_radar_routes_smoke.py` — Smoke-Tests inkl. Sidebar-Gate (Task 6; Pattern: `tests/test_technik_routes_smoke.py`)

Geänderte Dateien:
- `app/main.py` — Router-Import + `include_router`
- `app/templates/base.html` — Sidebar-Link

### References

- Epic 2, Story 2.5 AC: `output/planning-artifacts/epics.md` Zeilen 652–668
- Architecture Decision ID2 (Funktionssignatur + `DueRadarEntry`-Dataclass sind verbindlich; Query-Pattern weicht bewusst ab, siehe Dev Notes "Query-Ansatz"): `output/planning-artifacts/architecture.md` §ID2
- Permission-Registry: `app/permissions.py:PERMISSIONS` + `DEFAULT_ROLE_PERMISSIONS`
- DB-Schema `policen`/`wartungspflichten`: `migrations/versions/0010_steckbrief_core.py`
- Sidebar-Muster: `app/templates/base.html`
- Service-Dataclass-Muster: `app/services/steckbrief.py` (`ObjectRow`, `ObjectDetail`)
- TemplateResponse-Signatur: Memory `feedback_starlette_templateresponse`
- Epic-1-Retro Security-Action P2: `output/implementation-artifacts/epic-1-retro-2026-04-24.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6[1m]

### Debug Log References

### Completion Notes List

### File List
