# Story 3.2: Mobile Card-Layout

Status: ready-for-dev

## Story

Als Mitarbeitender im Bereitschaftsdienst (J2 Markus),
möchte ich die Objekt-Liste auf dem Smartphone nutzen und die Stoerungs-Hotline direkt anrufen können,
damit ich unterwegs Objekte schnell finde, öffne und sofort die richtige Nummer tippe.

## Boundary-Klassifikation

`frontend-responsive` — Niedrig-Medium-Risiko. Kein neuer Endpunkt, keine neue Migration.
Risiken: (1) `parse_technik_value()` wirft `ValueError` für unbekannte Kinds — `"tel"` muss dort eingetragen werden, sonst 500 beim Speichern der Hotline. (2) Mobile Card-View ist bewusst statisch (server-rendered, kein HTMX-Sort/Filter auf Mobile). (3) CSS scroll-snap ohne JS — nur Tailwind-Klassen auf dem Photo-Container.

**Abhängigkeit: Story 3.1 muss `done` sein** — `ObjectListRow.saldo` und `ObjectListRow.pflegegrad`
aus Story 3.1 werden im Mobile-Card-View benötigt. Außerdem geht Story 3.2 davon aus, dass
`objects_list.html` nach Story 3.1 die Filter-Bar + Sort-Tabelle enthält (Story 3.2 wickelt diese
in `hidden sm:block`).

## Acceptance Criteria

**AC1 — Mobile Objekt-Liste (Viewport < 640 px)**

**Given** ich bin auf `/objects` als User mit `objects:view` auf einem Smartphone
**When** die Seite rendert
**Then** wird die Tabelle (inkl. Filter-Bar) versteckt (`<div class="hidden sm:block">`)
**And** stattdessen zeigt ein Card-Grid (`<div class="block sm:hidden ...">`) eine Card pro Objekt
**And** jede Card enthält: `short_code`, `name`, `saldo` (oder `—` wenn None), `pflegegrad` (farbcodiert oder `—`)
**And** jede Card ist ein vollständiger `<a>`-Block-Link zu `/objects/{id}`
**And** Touch-Target jeder Card ist >= 44 px (via `min-h-[44px]`)

**AC2 — Desktop Objekt-Liste unverändert**

**Given** ich bin auf `/objects` auf einem Desktop-Browser (Viewport >= 640 px)
**When** die Seite rendert
**Then** verhält sich die Seite identisch zu nach Story 3.1 (Table + Filter + Sort) — keine Regression

**AC3 — Mobile Detailseite: Fotos horizontal scrollbar**

**Given** ich bin auf `/objects/{id}` auf einem Smartphone und Fotos sind vorhanden
**When** die Seite rendert
**Then** sind die Fotos horizontal scrollbar mit CSS scroll-snap (`overflow-x-auto snap-x snap-mandatory`)
**And** jedes Foto-Wrapper-Div hat `snap-start flex-none` (kein Zusammenquetschen der Karten)
**And** auf Desktop (sm+) wrappen Fotos weiterhin zeilenweise (`sm:flex-wrap sm:overflow-x-visible`)

**AC4 — Sektionen vertikal gestapelt auf Mobile — bereits erfüllt**

**Given** `/objects/{id}` auf Smartphone
**When** die Seite rendert
**Then** sind alle Sektions-Grids 1-spaltig auf Mobile — bereits durch `grid-cols-1 md:grid-cols-X` in allen Sub-Templates abgedeckt; keine Template-Änderung nötig

**AC5 — Heizungs-Hotline als Tap-to-Call**

**Given** `Object.heating_hotline` ist gesetzt (nicht leer, nicht None)
**When** die Detailseite rendert
**Then** erscheint der Wert als `<a href="tel:{{ value }}">` mit tap-to-call Styling (grün, underline)
**And** beim Speichern via Edit-Formular liefert `parse_technik_value("heating_hotline", ...)` kein `ValueError` (kein 500)

**Given** `Object.heating_hotline` ist `None` oder leer
**When** die Detailseite rendert
**Then** erscheint weiterhin `—` (kein tel-Link)

**AC6 — Tests**

Neue Tests in `tests/test_steckbrief_routes_smoke.py`.

## Tasks / Subtasks

### Task 1 — `app/services/steckbrief.py`: `"tel"`-Kind + `parse_technik_value()`

- [ ] **1.1** `parse_technik_value()` erweitern — `"tel"` wie `"text"` behandeln.

  **Aktuelle Zeile (ca. 333):**
  ```python
  if field.kind == "text":
      if len(stripped) > field.max_len:
          return None, f"Maximal {field.max_len} Zeichen erlaubt."
      return stripped, None
  raise ValueError(f"Unbekannter Feld-Typ: {field.kind!r}")
  ```

  **Nach Änderung:**
  ```python
  if field.kind in ("text", "tel"):
      if len(stripped) > field.max_len:
          return None, f"Maximal {field.max_len} Zeichen erlaubt."
      return stripped, None
  raise ValueError(f"Unbekannter Feld-Typ: {field.kind!r}")
  ```

  **WARUM**: Ohne diesen Zweig wirft `parse_technik_value()` bei `kind == "tel"` einen `ValueError`
  → 500 im `POST /objects/{id}/technik/field`-Handler. Dieser Guard muss VOR dem `raise` stehen.

- [ ] **1.2** `TECHNIK_HEIZUNG` — `heating_hotline` kind von `"text"` auf `"tel"` ändern (Zeile 286):

  ```python
  TECHNIK_HEIZUNG: tuple[TechnikField, ...] = (
      TechnikField("heating_type",    "Heizungs-Typ",      "text"),
      TechnikField("year_heating",    "Baujahr Heizung",   "int_year"),
      TechnikField("heating_company", "Wartungsfirma",     "text"),
      TechnikField("heating_hotline", "Stoerungs-Hotline", "tel"),   # war: "text"
  )
  ```

  `max_len` bleibt Default 500 — ausreichend für jedes Telefonnummer-Format inklusive Klammern/Leerzeichen.

### Task 2 — Templates fuer `"tel"`-Kind: View → `<a href="tel:">`, Edit → `type="tel"`

- [ ] **2.1** Den Value-Rendering-Block anpassen. Aktuell (ca. Zeile 8–14):

  ```html
  <div class="text-sm text-slate-900 truncate">
      {% if field.value is not none and field.value != "" %}
          {{ field.value }}
      {% else %}
          <span class="text-slate-400">&mdash;</span>
      {% endif %}
  </div>
  ```

  **Nach Änderung:**
  ```html
  <div class="text-sm text-slate-900 truncate">
      {% if field.value is not none and field.value != "" %}
          {% if field.kind == "tel" %}
              <a href="tel:{{ field.value }}"
                 class="text-green-600 hover:text-green-700 underline font-medium">{{ field.value }}</a>
          {% else %}
              {{ field.value }}
          {% endif %}
      {% else %}
          <span class="text-slate-400">&mdash;</span>
      {% endif %}
  </div>
  ```

  **Jinja2-Kontext**: `field` ist ein dict (`{"key": ..., "label": ..., "kind": ..., "value": ..., "prov": ...}`).
  `field.kind` in Jinja2 = `field["kind"]` — funktioniert für beides.

- [ ] **2.2** `_obj_technik_field_edit.html` — Input-Type-Dispatch um `"tel"` erweitern (Zeile 21–23):

  **Vorher:**
  ```html
  <input id="input-{{ field.key }}"
         name="value"
         type="{{ 'number' if field.kind == 'int_year' else 'text' }}"
  ```

  **Nachher:**
  ```html
  <input id="input-{{ field.key }}"
         name="value"
         type="{{ 'number' if field.kind == 'int_year' else ('tel' if field.kind == 'tel' else 'text') }}"
  ```

  **WARUM**: `<input type="tel">` triggert auf Smartphones den Ziffern-Keypad statt der vollen
  QWERTZ-Tastatur — direkt relevant fuer J2 Markus, der die Hotline unterwegs eintippt.
  Server-seitige Validierung bleibt unveraendert (`parse_technik_value()` akzeptiert beliebigen
  Text-Inhalt fuer `"tel"`-Kind via `("text", "tel")`-Branch aus Task 1.1).

### Task 3 — `app/templates/_obj_technik.html`: Foto-Container scroll-snap

- [ ] **3.1** Foto-Flex-Container (Zeile 57) ersetzen:

  **Vorher:**
  ```html
  <div class="flex flex-wrap gap-3 items-start">
  ```

  **Nachher:**
  ```html
  <div class="flex gap-3 overflow-x-auto snap-x snap-mandatory sm:flex-wrap sm:overflow-x-visible items-start pb-2 sm:pb-0">
  ```

  Tailwind-Klassen:
  - `snap-x snap-mandatory` — horizontales scroll-snap (Tailwind Play CDN enthält alle Snap-Utilities)
  - `overflow-x-auto` — Scrollbar erscheint nur wenn nötig
  - `sm:flex-wrap` — Desktop: Fotos wrappen statt scrollen
  - `sm:overflow-x-visible` — Desktop: kein Scroll-Abschneiden (nötig, sonst Fotos clipped)
  - `pb-2 sm:pb-0` — Platz für Scrollbar-Track auf Mobile

- [ ] **3.2** Jedes include in einen `snap-start flex-none`-Wrapper einwickeln (Zeilen 58–63):

  **Vorher:**
  ```html
  {% for photo in photos_by_component.get(component_ref, []) %}
      {% include "_obj_photo_card.html" %}
  {% endfor %}
  {% if has_permission(user, "objects:edit") %}
      {% include "_obj_photo_upload_form.html" %}
  {% endif %}
  ```

  **Nachher:**
  ```html
  {% for photo in photos_by_component.get(component_ref, []) %}
  <div class="snap-start flex-none">
      {% include "_obj_photo_card.html" %}
  </div>
  {% endfor %}
  {% if has_permission(user, "objects:edit") %}
  <div class="snap-start flex-none">
      {% include "_obj_photo_upload_form.html" %}
  </div>
  {% endif %}
  ```

  **WARUM `flex-none`**: `_obj_photo_card.html` rendert ein 96×96px-Element (`w-24 h-24`).
  Ohne `flex-none` (= `flex: 0 0 auto`) würden die Karten auf Mobile zusammengedrückt.
  Auf Desktop schadet `flex-none` nicht — `sm:flex-wrap` erlaubt trotzdem Zeilenumbrüche.

### Task 4 — `app/templates/objects_list.html`: Mobile Card-Grid + Desktop-Toggle

**Voraussetzung: Task 4 erst implementieren, wenn Story 3.1 vollständig done ist.**

- [ ] **4.1** Mobile Card-Grid **vor** dem bestehenden Filter+Table-Block einfügen:

  ```html
  {# Mobile Card-Grid (< 640 px) — zeigt short_code, name, saldo, pflegegrad.
     Statisch server-rendered; kein HTMX-Sort/Filter auf Mobile (MVP). #}
  <div class="block sm:hidden space-y-3 mb-6">
    {% for row in rows %}
    <a href="/objects/{{ row.id }}"
       class="flex justify-between items-center rounded-lg bg-white border border-slate-200 px-4 py-3 min-h-[44px] hover:border-slate-300 active:bg-slate-50 no-underline">
      <div class="min-w-0 flex-1 pr-3">
        <div class="font-mono text-sm font-semibold text-slate-900">{{ row.short_code }}</div>
        <div class="text-sm text-slate-600 truncate mt-0.5">{{ row.name }}</div>
        {% if row.saldo is not none %}
        <div class="text-xs text-slate-500 tabular-nums mt-1">{{ "%.0f"|format(row.saldo|float) }} €</div>
        {% endif %}
      </div>
      <div class="shrink-0 text-right">
        {% if row.pflegegrad is not none %}
        <span class="text-sm font-medium tabular-nums
          {% if row.pflegegrad >= 70 %}text-green-600
          {% elif row.pflegegrad >= 40 %}text-yellow-600
          {% else %}text-red-600{% endif %}">{{ row.pflegegrad }}%</span>
        {% else %}
        <span class="text-sm text-slate-400">—</span>
        {% endif %}
      </div>
    </a>
    {% else %}
    <div class="py-10 text-center text-slate-400 text-sm rounded-lg bg-white border border-slate-200">
      Noch keine Objekte &mdash; warte auf Impower-Sync oder lege sie via Admin-Tool an.
    </div>
    {% endfor %}
  </div>
  ```

  **WICHTIG**: `row.saldo is not none` — nicht `if row.saldo` (Decimal("0")-Truthiness-Falle,
  Muster aus Story 2.8 Patch). Gleiches Muster für `row.pflegegrad is not none`.

- [ ] **4.2** Bestehenden Filter+Table-Block in `<div class="hidden sm:block">` einwickeln:

  ```html
  {# Desktop: Filter-Bar + Sort-Tabelle (sm+, hidden auf Mobile) #}
  <div class="hidden sm:block">
    <!-- hier der komplette Block aus Story 3.1:
         - hidden inputs #sort-state, #order-state
         - Filter-Select-Bar
         - <div class="rounded-lg bg-white border ..."> mit der Tabelle
    -->
  </div>
  ```

  **Kontext nach Story 3.1**: `objects_list.html` hat einen Block mit:
  1. `<input type="hidden" id="sort-state" ...>` und `<input type="hidden" id="order-state" ...>`
  2. Filter-Bar (`<div class="flex items-center gap-4 mb-4">`)
  3. `<div class="rounded-lg bg-white ...">` mit `<table>` und `{% include "_obj_table_body.html" %}`

  Dieser gesamte Block kommt in den `hidden sm:block`-Wrapper. Die hidden inputs für
  HTMX-State sind dann auf Mobile nicht im DOM — korrekt, weil Mobile den HTMX-Flow
  nicht nutzt (keine HTMX-Requests von Mobile).

### Task 5 — `tests/test_steckbrief_routes_smoke.py`: Neue Tests

- [ ] **5.1** Mobile Card-Section vorhanden:

  ```python
  def test_list_mobile_card_section_present(steckbrief_admin_client, db):
      db.add(Object(id=uuid.uuid4(), short_code="MOB1", name="Mobil Eins"))
      db.commit()
      response = steckbrief_admin_client.get("/objects")
      assert response.status_code == 200
      assert "sm:hidden" in response.text, "Mobile Card-Section nicht gefunden (class sm:hidden fehlt)"
      assert "hidden sm:block" in response.text, "Desktop-Table-Toggle nicht gefunden"
  ```

- [ ] **5.2** Mobile Cards enthalten required Felder (short_code, name, saldo):

  ```python
  def test_list_mobile_cards_contain_required_fields(steckbrief_admin_client, db):
      from decimal import Decimal
      db.add(Object(id=uuid.uuid4(), short_code="MOB2", name="Mobil Zwei",
                    last_known_balance=Decimal("1234"), pflegegrad_score_cached=75))
      db.commit()
      response = steckbrief_admin_client.get("/objects")
      assert response.status_code == 200
      assert "MOB2" in response.text
      assert "Mobil Zwei" in response.text
      assert "1234" in response.text   # Saldo via "%.0f"-Format
  ```

- [ ] **5.3** Heating-Hotline rendert als `<a href="tel:...">`:

  ```python
  def test_detail_heating_hotline_renders_tel_link(steckbrief_admin_client, db):
      obj = Object(id=uuid.uuid4(), short_code="HOT1", name="Hotline Test",
                   heating_hotline="040 123456")
      db.add(obj); db.commit()
      response = steckbrief_admin_client.get(f"/objects/{obj.id}")
      assert response.status_code == 200
      assert 'href="tel:040 123456"' in response.text

  def test_detail_heating_hotline_empty_shows_no_tel_link(steckbrief_admin_client, db):
      obj = Object(id=uuid.uuid4(), short_code="HOT2", name="Hotline Leer",
                   heating_hotline=None)
      db.add(obj); db.commit()
      response = steckbrief_admin_client.get(f"/objects/{obj.id}")
      assert response.status_code == 200
      assert 'href="tel:' not in response.text
  ```

- [ ] **5.4** Foto-Container hat scroll-snap-Klassen:

  ```python
  def test_detail_photo_container_has_scroll_snap_classes(steckbrief_admin_client, db):
      obj = Object(id=uuid.uuid4(), short_code="PH01", name="Photo Test")
      db.add(obj); db.commit()
      # Objekt ohne Fotos — Container wird trotzdem gerendert (alle Komponenten in Registry)
      response = steckbrief_admin_client.get(f"/objects/{obj.id}")
      assert response.status_code == 200
      assert "snap-x" in response.text
      assert "snap-mandatory" in response.text
  ```

- [ ] **5.5** `parse_technik_value` verarbeitet `"tel"`-Kind ohne ValueError (kein 500):

  ```python
  def test_technik_field_save_heating_hotline_tel_kind_no_500(steckbrief_admin_client, db):
      obj = Object(id=uuid.uuid4(), short_code="TEL1", name="Tel Test")
      db.add(obj); db.commit()
      response = steckbrief_admin_client.post(
          f"/objects/{obj.id}/technik/field",
          data={"field_name": "heating_hotline", "value": "040 99887766"},
      )
      # 200 = erfolgreich gespeichert + View-Fragment zurück
      # 500 = BUG — parse_technik_value wirft ValueError für "tel"-Kind
      assert response.status_code == 200, (
          "500 deutet auf fehlenden 'tel'-Zweig in parse_technik_value() hin — Task 1.1 prüfen"
      )
      assert 'href="tel:040 99887766"' in response.text
  ```

- [ ] **5.6** Desktop-Tabelle bleibt nach Mobile-Erweiterung gerendert (AC2 Regression):

  ```python
  def test_list_desktop_table_still_rendered_after_mobile_addition(steckbrief_admin_client, db):
      db.add(Object(id=uuid.uuid4(), short_code="DSK1", name="Desktop Eins"))
      db.commit()
      response = steckbrief_admin_client.get("/objects")
      assert response.status_code == 200
      # Desktop-Wrapper + Sort-Tabelle muessen weiterhin im DOM sein:
      assert "hidden sm:block" in response.text
      assert "<table" in response.text
      assert 'id="obj-rows"' in response.text  # _obj_table_body.html ist still included
  ```

- [ ] **5.7** Edit-Form fuer `heating_hotline` rendert `type="tel"` (Mobile-Keypad):

  ```python
  def test_technik_field_edit_form_renders_type_tel_for_hotline(steckbrief_admin_client, db):
      obj = Object(id=uuid.uuid4(), short_code="EDT1", name="Edit Tel Test")
      db.add(obj); db.commit()
      response = steckbrief_admin_client.get(
          f"/objects/{obj.id}/technik/field/heating_hotline/edit"
      )
      assert response.status_code == 200
      # Smartphone-Keypad-Trigger:
      assert 'type="tel"' in response.text
  ```

## Dev Notes

### Abhängigkeit: Story 3.1 MUSS `done` sein vor Task 4

Task 1–3 (service, templates) sind unabhängig von Story 3.1 und können vorab implementiert werden.
**Task 4** (`objects_list.html` Mobile Card-Grid + Desktop-Toggle) setzt voraus, dass Story 3.1
den Filter-Bar-Block und die Sort-Tabelle bereits eingebaut hat. Ohne Story 3.1 gibt es nichts,
was in `hidden sm:block` eingewickelt werden kann.

### KRITISCH: `parse_technik_value()` — `"tel"` vor `raise ValueError`

```python
# FALSCH — führt zu 500 beim POST /objects/{id}/technik/field für heating_hotline:
if field.kind == "text":
    ...
raise ValueError(f"Unbekannter Feld-Typ: {field.kind!r}")  # feuert für "tel"!

# RICHTIG:
if field.kind in ("text", "tel"):
    ...
raise ValueError(...)  # nur für wirklich unbekannte Kinds
```

Test 5.5 fängt diesen Bug: 500 statt 200 ist ein klares Signal.

### Tailwind-Breakpoint: `sm:` = 640 px (NICHT `md:` = 768 px)

Bestehende Inhaltslayouts nutzen `md:` für Zwei-/Drei-Spalten-Grids. Story 3.2 nutzt `sm:`
für den Table/Card-Toggle, weil 640 px der Standard-Grenzwert für Smartphones ist.
`sm:hidden` / `hidden sm:block` ist bewusst `sm:`, nicht `md:`.

### Mobile Card-View ist statisch — kein HTMX-Sort/Filter

Der Sort/Filter-Flow (HTMX, `hx-target="#obj-rows"`) liegt ausschließlich in der Desktop-Tabelle.
Auf Mobile zeigen Cards immer den server-rendered Default-Sort (`short_code asc`). Die Hidden-Inputs
`#sort-state` und `#order-state` aus Story 3.1 sind auf Mobile nicht im DOM — korrekt, da kein
HTMX-Request auf Mobile ausgelöst wird.

### `Decimal("0")` ist falsy — immer `is not none` prüfen

In der Mobile Card-Section und im Template:
```html
{% if row.saldo is not none %}   {# KORREKT — zeigt 0 € an #}
{% if row.saldo %}               {# FALSCH — versteckt Decimal("0") #}
```
Gilt für: `row.saldo` (`Decimal | None`) und `row.pflegegrad` (`int | None`).
Pattern aus Story 2.8 Patch (Truthiness-Bug bei Rücklage-Feldern).

### `sm:overflow-x-visible` ist nötig — sonst Desktop-Fotos geclipped

Ohne `sm:overflow-x-visible` würde der Scroll-Container auf Desktop bestehen bleiben und
Fotos am Rand der Section abschneiden. Das override ist explizit notwendig.

### `_obj_technik_field_edit.html` Input-Type-Dispatch

Das Edit-Fragment dispatcht den Input-Type ueber `field.kind`. Story 3.2 erweitert den
Dispatch um den `"tel"`-Zweig (Task 2.2) → `<input type="tel">` triggert auf Smartphones
den Ziffern-Keypad. Server-seitig wird der Wert weiterhin als String entgegengenommen
(`parse_technik_value()` `("text", "tel")`-Branch); kein Browser-Formular-Validator,
freie Telefon-Format-Eingabe (Klammern, Leerzeichen, +49 …).

### Money-Format `"%.0f"` in Mobile-Cards

Konsistent mit dem Desktop-Listen-Pattern aus `_obj_table_body.html` (nach Story 3.1) und
`_versicherer_rows.html`. Keine Cents in Listen. Detail-Views nutzen `"%.2f"`.

### Sektionen vertikal gestapelt: bereits erfüllt (AC4)

Alle Section-Sub-Templates (`_obj_stammdaten.html`, `_obj_finanzen.html`, `_obj_technik.html`,
`_obj_versicherungen.html`, `_obj_menschen.html`) nutzen `grid-cols-1 md:grid-cols-X`.
Auf Mobile (< 768 px) sind alle Grids automatisch 1-spaltig. Keine Änderung nötig.

### Pflegegrad-Farben: Schwellen 70/40 (konsistent mit Story 3.1)

Mobile Cards nutzen dieselben Farbschwellen wie `_obj_table_body.html` (nach Story 3.1):
- ≥ 70: `text-green-600`
- ≥ 40: `text-yellow-600`
- < 40: `text-red-600`

### Keine neue Migration

Alle Felder (`heating_hotline`, `pflegegrad_score_cached`, `last_known_balance`, `reserve_current`)
existieren bereits in der `objects`-Tabelle. Neueste Migration: `0016_wartungspflichten_missing_fields.py`.

### Keine neue Route, kein Claude-Call, kein Audit-Log

Reine Frontend-Änderung. Kein BackgroundTask, kein `asyncio.run()`.

## Test-Checkliste (Epic 2 Retro P1)

- [x] Permission-Matrix: nicht anwendbar (keine neue Route)
- [x] IDOR: nicht anwendbar (kein FK aus Form-Body in neuen Templates)
- [x] Numerische Boundaries: `Decimal("0")` korrekt in Card-Section (Dev-Note + `is not none`)
- [x] NULLs korrekt: saldo/pflegegrad None → `—` (Tests 5.2 + Dev-Note)
- [x] Tel-Link nur wenn Wert gesetzt (Tests 5.3)
- [x] `parse_technik_value("tel")` kein ValueError (Test 5.5)
- [x] Desktop-Tabelle nicht regredieren durch Mobile-Erweiterung (Test 5.6)
- [x] Edit-Input rendert `type="tel"` fuer Mobile-Keypad (Test 5.7)
- [ ] Date-Bounds: nicht anwendbar
- [ ] HTMX-422-Render: nicht anwendbar (kein neuer Form-Submit mit Validierung)

## Neue Dateien

_(keine)_

## Geänderte Dateien

- `app/services/steckbrief.py` — `TECHNIK_HEIZUNG[3].kind` `"text"` → `"tel"` + `parse_technik_value()` `"tel"`-Zweig
- `app/templates/_obj_technik_field_view.html` — `"tel"`-Kind-Rendering als `<a href="tel:">`
- `app/templates/_obj_technik_field_edit.html` — Input-Type-Dispatch um `"tel"` erweitert (`type="tel"` fuer Mobile-Keypad)
- `app/templates/_obj_technik.html` — Foto-Container scroll-snap + `flex-none`-Wrapper per Foto
- `app/templates/objects_list.html` — Mobile Card-Grid (`block sm:hidden`) + Desktop-Toggle (`hidden sm:block`) — erst nach Story 3.1 implementieren!
- `tests/test_steckbrief_routes_smoke.py` — Tests 5.1–5.7

## References

- Story 3.2 in Epics-File: `output/planning-artifacts/epics.md` §Epic 3 Story 3.2
- Story 3.1 Story-File (Abhängigkeit + ObjectListRow-Felder): `output/implementation-artifacts/3-1-objekt-liste-mit-sortierung-filter.md`
- Epic 2 Retrospektive (Test-Checkliste P1, Boundary-Klassifikation): `output/implementation-artifacts/epic-2-retro-2026-04-28.md`
- `TechnikField` Dataclass (kind-Attribut): `app/services/steckbrief.py:263`
- `parse_technik_value()` (kind-Dispatch, Zeile 321–337): `app/services/steckbrief.py:303`
- `TECHNIK_HEIZUNG` (heating_hotline, Zeile 286): `app/services/steckbrief.py:282`
- `_technik_field_ctx()` Router-Helper (field-Dict-Shape): `app/routers/objects.py:362`
- `_obj_technik_field_view.html` (Value-Block): `app/templates/_obj_technik_field_view.html`
- `_obj_technik_field_edit.html` (kind-Dispatch für Edit-Input): `app/templates/_obj_technik_field_edit.html`
- `_obj_technik.html` (Foto-Container, Zeile 57): `app/templates/_obj_technik.html`
- `objects_list.html` (nach Story 3.1): `app/templates/objects_list.html`
- `_obj_photo_card.html` (96×96 px Karten): `app/templates/_obj_photo_card.html`
- Decimal-Truthiness Bug (Story 2.8 Patch 1): `output/implementation-artifacts/2-8-versicherer-detailseite-mit-heatmap-schadensfaellen.md`
- `steckbrief_admin_client` Fixture: `tests/conftest.py:199`
- Tailwind scroll-snap (CDN enthält alle Utilities): `docs/project-context.md` §Frontend
- React-Mockup (Design-Referenz, Desktop-First, Hanseatic Terminal): `mockups/objektsteckbrief-react/README.md`
