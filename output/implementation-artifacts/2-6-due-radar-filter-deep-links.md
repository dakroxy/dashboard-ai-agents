# Story 2.6: Due-Radar-Filter & Deep-Links

Status: review

## Change Log

- 2026-04-28: Story 2.6 implementiert — Filter-Controls (Typ + Schwere), HTMX-Fragment-Endpoint `/due-radar/rows`, Versicherer-Deep-Link, Police-Anker-Link. 7 Unit-Tests + 2 Smoke-Tests neu.

## Story

Als Mitarbeiter mit `due_radar:view`,
ich möchte die Due-Radar-Liste nach Typ und Schwere filtern und pro Eintrag direkt in die Quell-Entität springen,
damit ich gezielt priorisieren und Maßnahmen ergreifen kann.

## Acceptance Criteria

1. **AC1 — Typ-Filter:** `GET /due-radar/rows?type=police` liefert nur Police-Zeilen per HTMX-Fragment-Swap (`_due_radar_rows.html`) in <= 500 ms.
2. **AC2 — Severity-Filter:** `GET /due-radar/rows?severity=lt30` zeigt nur Einträge mit `days_remaining < 30`.
3. **AC3 — Kombinierter Filter:** `?type=police&severity=lt30` filtert additiv; beide Bedingungen müssen erfüllt sein.
4. **AC4 — Filter-Controls:** Auf `/due-radar` gibt es zwei `<select>`-Elemente (Typ + Schwere). Beim Ändern eines Selects sendet HTMX automatisch einen GET-Request an `/due-radar/rows` und tauscht `#due-radar-rows` aus.
5. **AC5 — Deep-Link Police:** Klick auf eine Zeile mit `kind="police"` navigiert zu `/objects/{object_id}#policy-{entity_id}`.
6. **AC6 — Deep-Link Versicherer:** Klick auf den Versicherer-Namen in einer Police-Zeile navigiert zu `/registries/versicherer/{versicherer_id}`.
7. **AC7 — Wartungs-Link unverändert:** Klick auf eine Zeile mit `kind="wartung"` navigiert zu `/objects/{object_id}#versicherungen` (kein Versicherer-Link, kein spezifischer Anker).
8. **AC8 — Unit-Tests:** `tests/test_due_radar_unit.py` erhält mindestens 4 neue Tests: Typ-Police-Filter, Typ-Wartung-Filter, Severity-Filter, kombinierter Filter.
9. **AC9 — Smoke-Test:** `GET /due-radar/rows` unauthenticated → 302; ohne `due_radar:view` → 403.

## Tasks / Subtasks

- [x] Task 1: `DueRadarEntry` in `app/services/due_radar.py` um `versicherer_id`-Feld erweitern (AC: 5, 6)
  - [x] `versicherer_id: uuid.UUID | None = None` zu `DueRadarEntry` hinzufügen (Dataclass, `field(default=None)`)
  - [x] Police-Query: `InsurancePolicy.versicherer_id` in `SELECT`-Liste aufnehmen + in `DueRadarEntry`-Mapping setzen
  - [x] Police `link_url` von `/objects/{object_id}#versicherungen` auf `/objects/{object_id}#policy-{entity_id}` ändern (Scroll-Ziel für Story 2-1; Browser-Anker navigiert automatisch)
  - [x] Wartung `link_url` bleibt `/objects/{object_id}#versicherungen` (unverändert)

- [x] Task 2: Filterparameter in `list_due_within()` aktivieren (AC: 1, 2, 3)
  - [x] Signatur auf `list_due_within(db, *, days: int = 90, severity: str | None = None, types: list[str] | None = None, accessible_object_ids: list[uuid.UUID]) -> list[DueRadarEntry]` anpassen (Architecture ID2 bereits so spezifiziert)
  - [x] Police-Query: wenn `types` gesetzt und `"police"` nicht enthalten → leere Liste zurückgeben (skip query)
  - [x] Wartung-Query: wenn `types` gesetzt und `"wartung"` nicht enthalten → leere Liste zurückgeben (skip query)
  - [x] Severity-Filter auf beide Queries anwenden: `severity="< 30 Tage"` → `days_remaining < 30`; `severity="< 90 Tage"` → `days_remaining < 90` (in Python nach dem Merge, nicht als SQL-Predicate, da `days_remaining` erst nach dem Laden berechnet wird)
  - [x] Bestehender `GET /due-radar`-Handler: `list_due_within(db, accessible_object_ids=...)` bleibt unverändert aufgerufen (default `severity=None, types=None` → kein Filter, alles wie bisher)

- [x] Task 3: `GET /due-radar/rows` HTMX-Fragment-Endpoint im Router `app/routers/due_radar.py` (AC: 1, 2, 3, 9)
  - [x] `GET "/rows"` Handler mit Query-Params: `type: str = "all"` und `severity: str = "all"`
  - [x] `require_permission("due_radar:view")` + `accessible_object_ids` wie im Haupt-Handler
  - [x] Param-Mapping: `type` → `types` für Service: `"all"` → `None`, `"police"` → `["police"]`, `"wartung"` → `["wartung"]`
  - [x] Param-Mapping: `severity` → Service: `"all"` → `None`, `"lt30"` → `"< 30 Tage"`, `"lt90"` → `"< 90 Tage"`
  - [x] Liefert `templates.TemplateResponse(request, "_due_radar_rows.html", {"entries": entries})` (nur Fragment, kein volles Layout)

- [x] Task 4: Filter-Controls in `app/templates/due_radar.html` (AC: 4)
  - [x] Zwei `<select>`-Elemente über der Tabelle in einem `<form>`-Tag:
    - Typ-Select: `name="type"`, Optionen `value="all"` (Alle Typen), `value="police"` (Policen), `value="wartung"` (Wartungspflichten)
    - Schwere-Select: `name="severity"`, Optionen `value="all"` (Alle Schweren), `value="lt30"` (< 30 Tage), `value="lt90"` (< 90 Tage)
  - [x] Auf dem `<form>`: `hx-get="/due-radar/rows"`, `hx-target="#due-radar-rows"`, `hx-trigger="change from:select"`, `hx-swap="innerHTML"`
  - [x] Tailwind-Klassen analog zu Filter-Forms in `app/templates/admin/` (Select-Styling: `border border-slate-300 rounded px-2 py-1 text-sm`)
  - [x] Label-Texte: "Typ:" und "Schwere:"

- [x] Task 5: `_due_radar_rows.html` für Versicherer-Link erweitern (AC: 5, 6, 7)
  - [x] Titel-Zelle für `kind="police"`: `<a href="/registries/versicherer/{{ entry.versicherer_id }}" class="hover:underline text-blue-600">{{ entry.title }}</a>` — nur wenn `entry.versicherer_id` gesetzt, sonst Plaintext `{{ entry.title }}`
  - [x] Zeilen-Link (Typ-Spalte, Fälligkeits-Spalte, Verbleibend-Spalte, Schwere-Spalte): `<a href="{{ entry.link_url }}" class="block px-4 py-3">...` — damit "Klick auf Zeile" zum Object-Detail führt
  - [x] Objekt-Kürzel-Zelle: weiterhin `<a href="/objects/{{ entry.object_id }}">` (generischer Object-Link, kein Anker)
  - [x] Wartung-Zeilen: `entry.versicherer_id` ist `None` → Titel-Zelle rendert Plaintext-Link zu `entry.link_url` (unverändertes 2-5-Verhalten)

- [x] Task 6: Tests `tests/test_due_radar_unit.py` erweitern (AC: 8)
  - [x] `test_filter_type_police_returns_only_police()` — Police + Wartung im DB → `list_due_within(... types=["police"])` gibt nur Police-Einträge zurück
  - [x] `test_filter_type_wartung_returns_only_wartung()` — analog, nur Wartungs-Einträge
  - [x] `test_filter_severity_lt30_excludes_later_entries()` — Police mit `days_remaining=15` + Police mit `days_remaining=45` → `severity="< 30 Tage"` gibt nur die 15-Tage-Police zurück
  - [x] `test_filter_severity_lt30_includes_overdue_entries()` — Police mit `days_remaining=-5` (überfällig) + Police mit `days_remaining=15` + Police mit `days_remaining=45` → `severity="< 30 Tage"` gibt BEIDE ersten Einträge zurück (Überfällige sind strenger als 30 Tage, deshalb eingeschlossen — siehe Dev Notes "Severity-Filterung")
  - [x] `test_filter_combined_additive()` — Police mit 15 Tagen + Wartung mit 15 Tagen → `types=["police"], severity="< 30 Tage"` gibt nur die Police zurück (beide Bedingungen gelten)
  - [x] `test_versicherer_id_on_police_entry()` — Police-Eintrag hat `versicherer_id` gesetzt (nicht None)
  - [x] `test_police_link_url_has_policy_anchor()` — Police-Eintrag `link_url` endet auf `#policy-{id}`

- [x] Task 7: Smoke-Test für neuen Endpoint (AC: 9)
  - [x] In `tests/test_routes_smoke.py` neue Klasse `TestDueRadarRowsEndpoint`:
    - `test_unauthenticated_redirects()` — `GET /due-radar/rows` → 302
    - `test_no_permission_returns_403()` — Auth aber ohne `due_radar:view` → 403

## Dev Notes

### Abhängigkeit: Story 2-5 muss zuerst fertig sein

Story 2-6 erweitert ausschließlich Dateien, die Story 2-5 erstellt. Wenn 2-5 noch nicht implementiert ist:
- `app/services/due_radar.py` (Service mit `DueRadarEntry` + `list_due_within()`) — erstellt in 2-5
- `app/routers/due_radar.py` (Router mit `GET /due-radar`) — erstellt in 2-5
- `app/templates/due_radar.html` (Haupt-Template) — erstellt in 2-5
- `app/templates/_due_radar_rows.html` (Fragment mit `<tbody id="due-radar-rows">`) — erstellt in 2-5, ID `due-radar-rows` ist in 2-5 spec bereits korrekt vorgegeben

### Architecture ID2 war von Anfang an Filter-fähig geplant

Die Architektur-Entscheidung ID2 (`output/planning-artifacts/architecture.md`) spezifiziert die Service-Signatur:
```python
def list_due_within(db, *, days: int, severity: str | None, types: list[str] | None,
                    accessible_object_ids: list[UUID]) -> list[DueRadarEntry]:
```
Story 2-5 durfte diese Parameter bereits vorsehen oder als Defaults None-setzen. Story 2-6 aktiviert sie.

### Severity-Filterung: in Python, nicht per SQL

`days_remaining` wird erst nach dem Datenbankaufruf berechnet (`(due_date - date.today()).days`). Der Severity-Filter muss deshalb **nach** dem Python-Merge angewendet werden, nicht per SQL-WHERE. Volume ist klein (< 50 Zeilen) — kein Performance-Problem.

```python
if severity == "< 30 Tage":
    entries = [e for e in entries if e.days_remaining < 30]
elif severity == "< 90 Tage":
    entries = [e for e in entries if e.days_remaining < 90]
```

Überfällige Einträge (`days_remaining < 0`) bleiben bei `severity="< 30 Tage"` enthalten — sie sind strenger als 30 Tage.

### HTMX-Fragment-Endpoint: nur Fragment, kein Layout

`GET /due-radar/rows` liefert **ausschließlich** das `_due_radar_rows.html`-Fragment (kein `{% extends "base.html" %}`). Der Response-Content ist der nackte `<tbody>`, den HTMX in `#due-radar-rows` swappt.

```python
@router.get("/rows")
async def due_radar_rows(
    request: Request,
    type: str = "all",
    severity: str = "all",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("due_radar:view")),
):
    accessible_ids = list(accessible_object_ids(db, user))
    types_filter = None if type == "all" else [type]
    severity_filter = None if severity == "all" else ("< 30 Tage" if severity == "lt30" else "< 90 Tage")
    entries = list_due_within(db, types=types_filter, severity=severity_filter,
                               accessible_object_ids=accessible_ids)
    return templates.TemplateResponse(request, "_due_radar_rows.html", {"entries": entries})
```

### HTMX Filter-Form: `hx-trigger="change from:select"`

Beide Selects senden beim Change-Event. Alle Query-Params werden per `hx-include` automatisch eingeschlossen wenn sie im gleichen `<form>` sind:

```html
<form hx-get="/due-radar/rows"
      hx-target="#due-radar-rows"
      hx-trigger="change from:select"
      hx-swap="innerHTML"
      class="flex gap-4 mb-4 items-center">
  <label>Typ:
    <select name="type" class="border border-slate-300 rounded px-2 py-1 text-sm">
      <option value="all">Alle Typen</option>
      <option value="police">Policen</option>
      <option value="wartung">Wartungspflichten</option>
    </select>
  </label>
  <label>Schwere:
    <select name="severity" class="border border-slate-300 rounded px-2 py-1 text-sm">
      <option value="all">Alle</option>
      <option value="lt30">&lt; 30 Tage</option>
      <option value="lt90">&lt; 90 Tage</option>
    </select>
  </label>
</form>
```

Kein separates `hx-include` nötig — HTMX serialisiert alle Formfelder automatisch beim Submit.

### Deep-Link Anchor `#policy-{id}` — Abhängigkeit zu Story 2-1

Der Police-Link `/objects/{object_id}#policy-{entity_id}` erfordert, dass die Versicherungs-Sektion im Object-Detail (`_obj_versicherungen.html`, erstellt in Story 2-1) pro Police ein Wrapper-Element mit `id="policy-{id}"` rendert. **Story 2-1 setzt dieses Attribut explizit in Task 6.1** (`<article id="policy-{{ p.id }}" data-police-id="{{ p.id }}">`) und Regression-Test `8.2.3` prueft es — Koordination zwischen 2-1 und 2-6 ist damit dokumentiert, kein Gap.

Sollte 2-1 zum Dev-Zeitpunkt von 2-6 noch nicht live sein, bricht nichts — der Browser ignoriert unbekannte Anker still, der Deep-Link landet auf `/objects/{id}` ohne Scroll. Sobald 2-1 gemergt ist, greift das Scroll automatisch.

### Versicherer-Link: Route `/registries/versicherer/{id}` noch nicht implementiert

`/registries/versicherer/{id}` wird erst in Story 2-8 gebaut. Der Link-HTML wird in 2-6 korrekt generiert, liefert aber bis Story 2-8 ein 404. Das ist akzeptabel (Link schon heute korrekt in `href`, kein Rework nötig).

### `versicherer_id` in `DueRadarEntry` — Wartung-Rows bleiben `None`

Wartungspflichten haben keinen direkten `versicherer_id`-Bezug (nur via `policy_id → InsurancePolicy.versicherer_id`, 2 JOINs). Story 2-6 setzt `versicherer_id=None` für Wartungs-Einträge — Versicherer-Link wird im Template geskippt. Kein Aufwand.

### Kein URL-State-Update beim Filtern

Der Filter-HTMX-Swap aktualisiert **nicht** die Browser-URL. Seiten-Reload setzt Filter zurück auf "Alle". Das ist für MVP akzeptabel; URL-State-Persistenz (`hx-push-url`) kann Story 3.1 ergänzen.

### Keine neue Migration

Story 2-6 ändert keine DB-Schema. Alle benötigten Felder (`InsurancePolicy.versicherer_id`, `Wartungspflicht.policy_id`) sind bereits in Migration `0010_steckbrief_core.py` vorhanden.

### HTMX-Response-Header (optional, aber sauber)

Für HTMX-Fragment-Endpoints empfiehlt sich `HX-Trigger`-Header zurückzugeben wenn Status-Feedback nötig ist. Für diesen Filter-Endpoint nicht nötig — direkte Fragment-Rückgabe reicht.

### Test-Setup: `Versicherer`-Fixture nötig

Für den `test_versicherer_id_on_police_entry`-Test muss ein `Versicherer`-Objekt in der SQLite-In-Memory-DB angelegt werden. Import: `from app.models.registry import Versicherer`. Das Fixture-Muster aus `tests/conftest.py` (frische DB pro Test) gilt weiterhin.

### Tabellen-Spalten in `_due_radar_rows.html`

Bestehend (Story 2-5): Typ | Objekt | Titel | Fälligkeit | Verbleibend | Schwere

Geändert in Story 2-6:
- **Titel-Spalte Police:** Versicherer-Name als `<a href="/registries/versicherer/{id}">` — Link zur Registry
- **Titel-Spalte Wartung:** Bezeichnung als `<a href="{link_url}">` (unverändert)
- **Typ/Fälligkeit/Verbleibend/Schwere-Spalten:** Alle per `<a href="{{ entry.link_url }}">` verlinkt (Deep-Link in Object-Detail)
- **Objekt-Spalte:** Bleibt `<a href="/objects/{{ entry.object_id }}">` (kein Anker)

### Scope-Grenze

**Nicht in Story 2-6:**
- Verwaltervertrags-Einträge im Due-Radar (Tabelle `management_contracts` existiert noch nicht)
- Mobile-Ansicht / Card-Layout (Story 3-2)
- URL-State-Persistenz der Filter (Story 3-1)
- `/registries/versicherer/{id}` Zielseite (Story 2-8)

### Project Structure Notes

Geänderte Dateien dieser Story:
- `app/services/due_radar.py` — `DueRadarEntry.versicherer_id` hinzufügen, Filter-Params aktivieren
- `app/routers/due_radar.py` — `GET /rows` Endpoint hinzufügen
- `app/templates/due_radar.html` — Filter-Form-Controls hinzufügen
- `app/templates/_due_radar_rows.html` — Versicherer-Link + zeilenweise Deep-Links
- `tests/test_due_radar_unit.py` — neue Filtертесты (erstellt in 2-5)
- `tests/test_routes_smoke.py` — `TestDueRadarRowsEndpoint`-Klasse hinzufügen

**Keine neuen Dateien** — alles ist Erweiterung von 2-5-Artefakten.

### References

- Epic 2, Story 2.6 AC: `output/planning-artifacts/epics.md`
- Architecture ID2 (Due-Radar-Query + Signatur): `output/planning-artifacts/architecture.md`
- Architecture ID4 (HTMX-Fragment-Strategie Due-Radar): `output/planning-artifacts/architecture.md`
- Story 2-5 (Basis-Implementierung): `output/implementation-artifacts/2-5-due-radar-global-view.md`
- `DueRadarEntry`-Definition und Queries: `app/services/due_radar.py` (erstellt in 2-5)
- Modell `InsurancePolicy.versicherer_id`: `app/models/police.py:31`
- Modell `Versicherer`: `app/models/registry.py:14`
- Permission `due_radar:view`: `app/permissions.py:65`
- HTMX-Fragment-Muster: `app/templates/_obj_table_body.html`
- Zellen-als-Links-Muster: `app/templates/_obj_table_body.html`
- TemplateResponse-Signatur: Memory `feedback_starlette_templateresponse`
- SQLite Monkey-Patch für Tests: `tests/conftest.py`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6[1m]

### Debug Log References

### Completion Notes List

- `DueRadarEntry` um `versicherer_id: uuid.UUID | None = None` erweitert (frozen dataclass, Default am Ende).
- Police-Query selektiert jetzt `InsurancePolicy.versicherer_id`; `link_url` auf `#policy-{entity_id}` umgestellt.
- `list_due_within()`: Type-Filter per early-skip der jeweiligen Query, Severity-Filter in Python nach dem Merge (< 30 Tage schließt negative days_remaining ein).
- Neuer HTMX-Fragment-Endpoint `GET /due-radar/rows` mit `require_permission("due_radar:view")`, Param-Mapping `type`/`severity` → Service.
- Filter-Form (2 Selects) über der Tabelle in `due_radar.html`; `hx-trigger="change from:select"` serialisiert automatisch beide Params.
- `_due_radar_rows.html`: Titel-Zelle Police zeigt Versicherer-Link (`/registries/versicherer/{id}`) wenn `versicherer_id` gesetzt; Typ/Fälligkeit/Verbleibend/Schwere-Zellen als Block-Link auf `entry.link_url`.
- 7 neue Unit-Tests (alle Filter-Kombinationen + versicherer_id + link_url-Anker), 2 neue Smoke-Tests (401-Redirect + 403).
- Vollständige Regression: 657/657 Tests grün.

### File List

- `app/services/due_radar.py`
- `app/routers/due_radar.py`
- `app/templates/due_radar.html`
- `app/templates/_due_radar_rows.html`
- `tests/test_due_radar_unit.py`
- `tests/test_routes_smoke.py`
