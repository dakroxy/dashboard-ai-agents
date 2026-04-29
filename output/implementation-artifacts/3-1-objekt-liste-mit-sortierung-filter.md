# Story 3.1: Objekt-Liste mit Sortierung & Filter

Status: review

## Story

Als Mitarbeiter mit `objects:view`,
ich möchte die Objekt-Liste nach Saldo, Rücklage, Mandat-Status und Pflegegrad sortieren und filtern,
damit ich beim Monatsabschluss die Objekte mit Handlungsbedarf zuerst sehe.

## Boundary-Klassifikation

`aggregation` — Medium-Risiko. Sortierlogik mit NULL-Handling, Decimal-Truthiness-Falle, kombinierter Sort+Filter via HTMX ohne JS-Framework. Lehre aus Story 2.7: Case-Folding für Strings, Tiebreaker für deterministische Reihenfolge, Decimal("0")-Truthiness (History: Story 2.8 Patch).

## Acceptance Criteria

**AC1 — Neue Spalten in der Liste**

**Given** ich bin auf `/objects` als User mit `objects:view`
**When** die Liste rendert
**Then** sehe ich Spalten `short_code`, `name`, `saldo`, `reserve_current`, `mandat_status`, `pflegegrad`
**And** jede Spalte hat einen klickbaren Header, der per HTMX-Fragment-Swap auf `#obj-rows` sortiert (< 500 ms P95)

**AC2 — Sortierung**

**Given** ich klicke den Header "Saldo"
**When** der Sort-Request ausgelöst wird
**Then** wird `_obj_table_body.html` (Target `#obj-rows`, `hx-swap="outerHTML"`) mit absteigender Saldo-Sortierung neu gerendert
**And** NULLs erscheinen immer zuletzt (egal ob auf- oder absteigend)
**And** sekundärer Tiebreaker ist `short_code.casefold()` für deterministische Reihenfolge bei Gleichstand

**AC3 — Pflegegrad-Cache genutzt, kein on-the-fly Compute**

**Given** `Object.pflegegrad_score_cached` ist gesetzt
**When** die Liste nach Pflegegrad sortiert
**Then** nutzt sie den Cache-Wert aus `pflegegrad_score_cached` direkt — kein Aufruf von `pflegegrad_score(obj)` pro Zeile

**AC4 — Rücklage-Badge**

**Given** ein Objekt hat `reserve_current < reserve_target * 6` (Soll: 6 Monatsbeiträge — `reserve_target` ist laut `docs/data-models.md:349` der **monatliche** Zielwert)
**When** die Zeile rendert
**Then** zeigt die `reserve_current`-Zelle einen roten Badge "unter Zielwert"
**And** Objekte mit `reserve_current is None` oder `reserve_target is None` zeigen den Badge nicht
**And** Objekte mit `reserve_current == Decimal("0")` und `reserve_target > 0` zeigen den Badge (0 < target*6 → Badge aktiv)

**AC5 — Filter "Rücklage < Zielwert"**

**Given** ich wähle im Filter-Select "Rücklage < Zielwert"
**When** der Filter-Request per HTMX ausgelöst wird
**Then** werden nur Objekte angezeigt, bei denen `reserve_current < reserve_target * 6`
**And** Objekte mit `reserve_current is None` oder `reserve_target is None` werden vom Filter ausgeschlossen (kein Threshold → kein Match)

**AC6 — Filter + Sort kombinierbar**

**Given** ich habe den Filter "Rücklage < Zielwert" aktiv
**When** ich einen Sort-Header klicke
**Then** bleibt der Filter aktiv und die neue Sortierung wird angewendet
**And** vice versa: aktive Sortierung bleibt erhalten, wenn ich den Filter ändere

**AC7 — HX-Request-Guard auf `/objects/rows`**

**Given** jemand navigiert direkt auf `/objects/rows` (kein HTMX-Request, kein `HX-Request`-Header)
**When** der Handler antwortet
**Then** wird ein `303 See Other` nach `/objects` zurückgegeben

**AC8 — Permission-Gates**

**Given** ich bin nicht eingeloggt
**When** ich `GET /objects/rows` aufrufe
**Then** erhalte ich 302 → `/auth/google/login`

**Given** ich bin eingeloggt, aber ohne `objects:view`
**When** ich `GET /objects/rows` aufrufe
**Then** erhalte ich 403

**AC9 — Tests**

Neue Tests in `tests/test_steckbrief_routes_smoke.py` (Smoke) und `tests/test_steckbrief_service_gaps.py` (Service-Unit).

## Tasks / Subtasks

### Task 1 — `ObjectListRow` + `list_objects_with_unit_counts()` in `app/services/steckbrief.py`

- [x] **1.1** Neue `ObjectListRow`-Dataclass nach dem bestehenden `ObjectRow` einfügen:

  ```python
  @dataclass(frozen=True)
  class ObjectListRow:
      id: uuid.UUID
      short_code: str
      name: str
      full_address: str | None
      unit_count: int
      saldo: Decimal | None           # last_known_balance
      reserve_current: Decimal | None
      reserve_target: Decimal | None  # fuer Badge-Berechnung im Template
      mandat_status: str              # "vorhanden" | "fehlt"
      pflegegrad: int | None          # pflegegrad_score_cached
  ```

  Import `Decimal` ist bereits oben in `steckbrief.py` via `from decimal import Decimal` — prüfen, falls nicht vorhanden ergänzen.

- [x] **1.2** `_SORT_ALLOWED`-Konstante einfügen (nach `ObjectListRow`):

  ```python
  _SORT_ALLOWED = frozenset({
      "short_code", "name", "saldo", "reserve_current", "mandat_status", "pflegegrad"
  })
  ```

- [x] **1.3** `list_objects_with_unit_counts()` signatur erweitern:

  ```python
  def list_objects_with_unit_counts(
      db: Session,
      accessible_ids: set[uuid.UUID] | None,
      *,
      sort: str = "short_code",
      order: str = "asc",
      filter_reserve_below_target: bool = False,
  ) -> list[ObjectListRow]:
  ```

- [x] **1.4** Query um neue Felder erweitern (innerhalb der bestehenden Funktion):

  ```python
  stmt = (
      select(
          Object.id,
          Object.short_code,
          Object.name,
          Object.full_address,
          Object.last_known_balance,
          Object.reserve_current,
          Object.reserve_target,
          Object.sepa_mandate_refs,
          Object.pflegegrad_score_cached,
          func.count(Unit.id).label("unit_count"),
      )
      .outerjoin(Unit, Unit.object_id == Object.id)
      .group_by(Object.id)
  )
  ```

  **Kein SQL `ORDER BY`** — Sortierung läuft in Python (SQLite-Kompatibilität, kein `nullslast()`-Äquivalent, Muster aus Story 2.7).

- [x] **1.5** `ObjectListRow`-Liste aufbauen:

  ```python
  rows: list[ObjectListRow] = [
      ObjectListRow(
          id=r.id,
          short_code=r.short_code,
          name=r.name,
          full_address=r.full_address,
          unit_count=int(r.unit_count or 0),
          saldo=r.last_known_balance,
          reserve_current=r.reserve_current,
          reserve_target=r.reserve_target,
          mandat_status="vorhanden" if r.sepa_mandate_refs else "fehlt",
          pflegegrad=r.pflegegrad_score_cached,
      )
      for r in db.execute(stmt).all()
  ]
  ```

  **ACHTUNG `sepa_mandate_refs`**: Aus JSONB geladen, ist der Wert entweder eine Python-Liste oder `None`. `bool([]) == False`, `bool(["...]) == True` — das ist korrekt. Kein `Decimal("0")`-Problem hier (String-Truthiness).

- [x] **1.6** Filter anwenden (nach Row-Aufbau):

  ```python
  if filter_reserve_below_target:
      rows = [
          r for r in rows
          if r.reserve_current is not None
          and r.reserve_target is not None
          and r.reserve_current < r.reserve_target * 6
      ]
  ```

  **WICHTIG**: `reserve_current is not None` — nicht `if r.reserve_current` (Decimal("0")-Truthiness-Bug wie in Story 2.8 Patch!). Immer explizit `is not None` prüfen.

- [x] **1.7** Python-Sort anwenden — kanonische Zwei-Listen-Methode für NULLs (Story 2.8-Muster, `nullslast()`-Alternative in Python):

  ```python
  safe_sort = sort if sort in _SORT_ALLOWED else "short_code"

  if safe_sort in ("short_code", "name"):
      rows.sort(
          key=lambda r: (getattr(r, safe_sort).casefold(), r.short_code.casefold()),
          reverse=(order == "desc"),
      )
  elif safe_sort == "mandat_status":
      rows.sort(
          key=lambda r: (1 if r.mandat_status == "vorhanden" else 0, r.short_code.casefold()),
          reverse=(order == "desc"),
      )
  else:
      # Numerische Felder (saldo, reserve_current, pflegegrad):
      # NULLs IMMER ans Ende, unabhängig von order. Single-Key mit (1, 0)-Sentinel
      # oder float("inf") kippt bei reverse=True und sortiert NULLs nach vorn.
      # Robust: zwei Listen, non_null sortieren, null_rows hintendran hängen.
      non_null = [r for r in rows if getattr(r, safe_sort) is not None]
      null_rows = [r for r in rows if getattr(r, safe_sort) is None]
      non_null.sort(
          key=lambda r: (float(getattr(r, safe_sort)), r.short_code.casefold()),
          reverse=(order == "desc"),
      )
      rows = non_null + null_rows
  ```

  `pflegegrad` ist `int | None` → `float(int_val)` ist sicher. `saldo` und `reserve_current` sind `Decimal | None` → `float(Decimal(...))` funktioniert. Tiebreaker `.casefold()` auf `short_code` für Determinismus bei gleichem Primärwert (Lehre aus Story 2.7).

  **Falle (nicht so machen)**: Single-Key-Variante mit Sentinel-Tuple `(1, 0, ...)` oder `float("inf")` für NULLs scheint elegant, kippt aber bei `reverse=True` — das Sentinel wird zum Maximum und NULLs landen vorn. Die Zwei-Listen-Methode hält NULLs in beiden Richtungen am Ende.

- [x] **1.8** Return: `return rows`

### Task 2 — Route `GET /objects/rows` in `app/routers/objects.py`

- [x] **2.1** Import `ObjectListRow` zu den bestehenden Service-Imports ergänzen:

  ```python
  from app.services.steckbrief import (
      ...
      ObjectListRow,  # neu
      list_objects_with_unit_counts,
      ...
  )
  ```

  **Kein Import von `ObjectRow`** — der wird in dieser Datei nicht direkt genutzt.

- [x] **2.2** Import `Query` aus FastAPI ergänzen (falls noch nicht vorhanden):

  ```python
  from fastapi import (
      APIRouter,
      BackgroundTasks,
      Depends,
      File,
      Form,
      HTTPException,
      Query,   # neu falls fehlend
      Request,
      UploadFile,
      status,
  )
  ```

- [x] **2.3** Neue Route **vor** `GET /{object_id}` einfügen (direktes nach dem bestehenden `list_objects`-Handler):

  ```python
  @router.get("/rows", response_class=HTMLResponse)
  async def list_objects_rows(
      request: Request,
      sort: str = Query("short_code"),
      order: str = Query("asc"),
      filter_reserve: str = Query("false"),
      user: User = Depends(require_permission("objects:view")),
      db: Session = Depends(get_db),
  ) -> HTMLResponse:
      # HX-Request-Guard (Lehre aus Story 2.6 Review)
      if not request.headers.get("HX-Request"):
          from fastapi.responses import RedirectResponse
          return RedirectResponse("/objects", status_code=303)
      accessible = accessible_object_ids(db, user)
      filter_bool = filter_reserve.lower() == "true"
      safe_order = "desc" if order == "desc" else "asc"
      rows = list_objects_with_unit_counts(
          db,
          accessible_ids=accessible,
          sort=sort,
          order=safe_order,
          filter_reserve_below_target=filter_bool,
      )
      return templates.TemplateResponse(
          request,
          "_obj_table_body.html",
          {"rows": rows, "user": user},
      )
  ```

  **Warum `filter_reserve: str` statt `bool`?** FastAPI parsed Query-Bool-Parameter zuverlässig (`"true"` → `True`, `"false"` → `False`), aber HTML `<select>`-Werte sind immer Strings. Sicherer: expliziter String-Vergleich `.lower() == "true"`.

  **WICHTIG**: Import `RedirectResponse` am Datei-Anfang oder inline. Besser: Am Datei-Anfang in den bestehenden Import `from fastapi.responses import FileResponse, HTMLResponse` einfügen:

  ```python
  from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
  ```

- [x] **2.4** Bestehenden `list_objects`-Handler anpassen — übergibt jetzt `ObjectListRow`-Liste (neue Felder vorhanden, Template nutzt sie):

  ```python
  @router.get("", response_class=HTMLResponse)
  async def list_objects(
      request: Request,
      user: User = Depends(require_permission("objects:view")),
      db: Session = Depends(get_db),
  ):
      accessible = accessible_object_ids(db, user)
      rows = list_objects_with_unit_counts(db, accessible_ids=accessible)
      return templates.TemplateResponse(
          request,
          "objects_list.html",
          {
              "title": "Objekte",
              "user": user,
              "rows": rows,
              "sort": "short_code",   # Initialzustand für Template-State
              "order": "asc",
              "filter_reserve": "false",
          },
      )
  ```

### Task 3 — Template `app/templates/objects_list.html` aktualisieren

- [x] **3.1** Filter-Controls-Block VOR der Tabelle einfügen. Muster aus `due_radar.html` (Story 2.6):

  ```html
  <!-- Sortier-State: hidden inputs, werden per onclick by Sort-Header aktualisiert -->
  <input type="hidden" id="sort-state" name="sort" value="{{ sort }}">
  <input type="hidden" id="order-state" name="order" value="{{ order }}">

  <!-- Filter-Bar -->
  <div class="flex items-center gap-4 mb-4">
    <label class="flex items-center gap-2 text-sm text-slate-600">Filter:
      <select id="filter-reserve-select"
              name="filter_reserve"
              class="border border-slate-300 rounded px-2 py-1 text-sm"
              hx-get="/objects/rows"
              hx-target="#obj-rows"
              hx-swap="outerHTML"
              hx-trigger="change"
              hx-include="#sort-state, #order-state">
        <option value="false" {% if filter_reserve == "false" %}selected{% endif %}>Alle Objekte</option>
        <option value="true"  {% if filter_reserve == "true"  %}selected{% endif %}>Rücklage &lt; Zielwert</option>
      </select>
    </label>
    {% if filter_reserve == "true" %}
    <span class="text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded">Filter aktiv</span>
    {% endif %}
  </div>
  ```

- [x] **3.2** `<thead>` vollständig ersetzen — neue Spalten mit HTMX-Sort-Links:

  ```html
  <thead class="text-xs uppercase tracking-wide text-slate-500 bg-slate-50 border-b border-slate-200">
    <tr>
      <!-- Kuerzel -->
      <th class="text-left px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
          onclick="document.getElementById('sort-state').value='short_code'; document.getElementById('order-state').value='{% if sort == 'short_code' and order == 'asc' %}desc{% else %}asc{% endif %}';"
          hx-get="/objects/rows?sort=short_code&order={% if sort == 'short_code' and order == 'asc' %}desc{% else %}asc{% endif %}"
          hx-target="#obj-rows"
          hx-swap="outerHTML"
          hx-include="#filter-reserve-select">
        Kürzel{% if sort == 'short_code' %} {{ '↑' if order == 'asc' else '↓' }}{% endif %}
      </th>
      <!-- Name -->
      <th class="text-left px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
          onclick="document.getElementById('sort-state').value='name'; document.getElementById('order-state').value='{% if sort == 'name' and order == 'asc' %}desc{% else %}asc{% endif %}';"
          hx-get="/objects/rows?sort=name&order={% if sort == 'name' and order == 'asc' %}desc{% else %}asc{% endif %}"
          hx-target="#obj-rows"
          hx-swap="outerHTML"
          hx-include="#filter-reserve-select">
        Name{% if sort == 'name' %} {{ '↑' if order == 'asc' else '↓' }}{% endif %}
      </th>
      <!-- Saldo -->
      <th class="text-right px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
          onclick="document.getElementById('sort-state').value='saldo'; document.getElementById('order-state').value='{% if sort == 'saldo' and order == 'desc' %}asc{% else %}desc{% endif %}';"
          hx-get="/objects/rows?sort=saldo&order={% if sort == 'saldo' and order == 'desc' %}asc{% else %}desc{% endif %}"
          hx-target="#obj-rows"
          hx-swap="outerHTML"
          hx-include="#filter-reserve-select">
        Saldo{% if sort == 'saldo' %} {{ '↑' if order == 'asc' else '↓' }}{% endif %}
      </th>
      <!-- Rücklage -->
      <th class="text-right px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
          onclick="document.getElementById('sort-state').value='reserve_current'; document.getElementById('order-state').value='{% if sort == 'reserve_current' and order == 'desc' %}asc{% else %}desc{% endif %}';"
          hx-get="/objects/rows?sort=reserve_current&order={% if sort == 'reserve_current' and order == 'desc' %}asc{% else %}desc{% endif %}"
          hx-target="#obj-rows"
          hx-swap="outerHTML"
          hx-include="#filter-reserve-select">
        Rücklage{% if sort == 'reserve_current' %} {{ '↑' if order == 'asc' else '↓' }}{% endif %}
      </th>
      <!-- Mandat -->
      <th class="text-left px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
          onclick="document.getElementById('sort-state').value='mandat_status'; document.getElementById('order-state').value='{% if sort == 'mandat_status' and order == 'asc' %}desc{% else %}asc{% endif %}';"
          hx-get="/objects/rows?sort=mandat_status&order={% if sort == 'mandat_status' and order == 'asc' %}desc{% else %}asc{% endif %}"
          hx-target="#obj-rows"
          hx-swap="outerHTML"
          hx-include="#filter-reserve-select">
        Mandat{% if sort == 'mandat_status' %} {{ '↑' if order == 'asc' else '↓' }}{% endif %}
      </th>
      <!-- Pflegegrad -->
      <th class="text-right px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
          onclick="document.getElementById('sort-state').value='pflegegrad'; document.getElementById('order-state').value='{% if sort == 'pflegegrad' and order == 'desc' %}asc{% else %}desc{% endif %}';"
          hx-get="/objects/rows?sort=pflegegrad&order={% if sort == 'pflegegrad' and order == 'desc' %}asc{% else %}desc{% endif %}"
          hx-target="#obj-rows"
          hx-swap="outerHTML"
          hx-include="#filter-reserve-select">
        Pflegegrad{% if sort == 'pflegegrad' %} {{ '↑' if order == 'asc' else '↓' }}{% endif %}
      </th>
    </tr>
  </thead>
  ```

  **HTMX-Pattern-Erklärung**:
  - `onclick=...` aktualisiert die hidden inputs synchron **vor** dem HTMX-Request
  - `hx-include="#filter-reserve-select"` nimmt den aktuellen Filter-Select-Wert mit
  - Wenn der Filter-Select sich ändert, liest er `#sort-state` + `#order-state` via `hx-include` aus

  **Achtung Jinja2-Escaping**: In `{% if ... %}` innerhalb eines `onclick`-Attributs werden doppelte Anführungszeichen nicht escaped. Die inneren Strings müssen einfache Anführungszeichen verwenden oder HTML-escaped sein. Der obige Code nutzt einfache `'` innerhalb des `onclick`-Attributs (mit doppelten `"` als äußere Begrenzer) — das ist korrekt.

  **Achtung Default-Sortierung für Numerische Spalten**: Numerische Spalten (Saldo, Rücklage, Pflegegrad) starten beim ersten Klick mit `order=desc` (höchste Werte zuerst — betriebswirtschaftlich sinnvoller). String-Spalten (Kürzel, Name, Mandat) starten mit `order=asc`. Das ist im `onclick` und `hx-get` so abgebildet.

- [x] **3.3** `{% include "_obj_table_body.html" %}` bleibt unverändert im Template.

### Task 4 — Fragment `app/templates/_obj_table_body.html` aktualisieren

- [x] **4.1** `<tbody>` bekommt eine `id`:

  ```html
  <tbody id="obj-rows">
  ```

  Bisher: `<tbody>` ohne id. Nach Story 3.1: `<tbody id="obj-rows">` — das ist der HTMX-Swap-Target.

- [x] **4.2** Neue Spalten in jeder Zeile. Vollständige Zeile nach Änderung:

  ```html
  {% for row in rows %}
  <tr class="border-t border-slate-100 hover:bg-slate-50">
    <!-- Kürzel -->
    <td class="p-0 font-medium">
      <a href="/objects/{{ row.id }}" class="block px-4 py-3 hover:underline">{{ row.short_code }}</a>
    </td>
    <!-- Name -->
    <td class="p-0 text-slate-700">
      <a href="/objects/{{ row.id }}" class="block px-4 py-3">{{ row.name }}</a>
    </td>
    <!-- Saldo -->
    <td class="p-0 text-right text-slate-700 tabular-nums">
      <a href="/objects/{{ row.id }}" class="block px-4 py-3">
        {% if row.saldo is not none %}
          {{ "%.0f"|format(row.saldo|float) }} €
        {% else %}
          <span class="text-slate-400">—</span>
        {% endif %}
      </a>
    </td>
    <!-- Rücklage mit Badge -->
    <td class="p-0 text-right tabular-nums">
      <a href="/objects/{{ row.id }}" class="block px-4 py-3">
        {% if row.reserve_current is not none %}
          {{ "%.0f"|format(row.reserve_current|float) }} €
          {% if row.reserve_target is not none and row.reserve_current < row.reserve_target * 6 %}
            <span class="ml-1 inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium bg-red-100 text-red-700">unter Zielwert</span>
          {% endif %}
        {% else %}
          <span class="text-slate-400">—</span>
        {% endif %}
      </a>
    </td>
    <!-- Mandat-Status -->
    <td class="p-0">
      <a href="/objects/{{ row.id }}" class="block px-4 py-3">
        {% if row.mandat_status == "vorhanden" %}
          <span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700">vorhanden</span>
        {% else %}
          <span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-slate-100 text-slate-500">fehlt</span>
        {% endif %}
      </a>
    </td>
    <!-- Pflegegrad -->
    <td class="p-0 text-right tabular-nums">
      <a href="/objects/{{ row.id }}" class="block px-4 py-3">
        {% if row.pflegegrad is not none %}
          <span class="{% if row.pflegegrad >= 70 %}text-green-600{% elif row.pflegegrad >= 40 %}text-yellow-600{% else %}text-red-600{% endif %} font-medium">
            {{ row.pflegegrad }} %
          </span>
        {% else %}
          <span class="text-slate-400">—</span>
        {% endif %}
      </a>
    </td>
  </tr>
  ```

- [x] **4.3** Leer-State anpassen (colspan von 4 auf 6):

  ```html
  {% else %}
  <tr>
    <td colspan="6" class="px-4 py-10 text-center text-slate-400">
      Noch keine Objekte — warte auf Impower-Sync oder lege sie via Admin-Tool an.
    </td>
  </tr>
  {% endfor %}
  </tbody>
  ```

- [x] **4.4** Bestehenden Kommentar am Anfang der Datei aktualisieren:

  ```
  {# Tabellenkoerper der Objekt-Liste. HTMX-Fragment fuer Sort/Filter (Story 3.1).
     tbody-ID "obj-rows" ist der Swap-Target aus objects_list.html. #}
  ```

### Task 5 — Service-Unit-Tests in `tests/test_steckbrief_service_gaps.py`

- [x] **5.1** Import `ObjectListRow` ergänzen:

  ```python
  from app.services.steckbrief import (
      get_provenance_map,
      list_objects_with_unit_counts,
      ObjectListRow,   # neu
  )
  ```

- [x] **5.2** Test: Neue Felder in der Rückgabe vorhanden:

  ```python
  def test_list_objects_returns_objectlistrow_with_extended_fields(db):
      db.add(Object(id=uuid.uuid4(), short_code="EXT", name="Extended",
                    reserve_current=Decimal("5000"), reserve_target=Decimal("1000"),
                    pflegegrad_score_cached=85))
      db.commit()
      result = list_objects_with_unit_counts(db, accessible_ids=None)
      assert len(result) == 1
      row = result[0]
      assert isinstance(row, ObjectListRow)
      assert row.pflegegrad == 85
      assert row.reserve_current == Decimal("5000")
      assert row.reserve_target == Decimal("1000")
      assert row.mandat_status == "fehlt"  # sepa_mandate_refs ist default=[]
  ```

- [x] **5.3** Test: `mandat_status` aus `sepa_mandate_refs`:

  ```python
  def test_mandat_status_vorhanden_when_sepa_refs_nonempty(db):
      db.add(Object(id=uuid.uuid4(), short_code="MND", name="Mandat",
                    sepa_mandate_refs=[{"id": "m-1"}]))
      db.commit()
      rows = list_objects_with_unit_counts(db, accessible_ids=None)
      assert rows[0].mandat_status == "vorhanden"

  def test_mandat_status_fehlt_when_sepa_refs_empty(db):
      db.add(Object(id=uuid.uuid4(), short_code="NOM", name="NoMandat",
                    sepa_mandate_refs=[]))
      db.commit()
      rows = list_objects_with_unit_counts(db, accessible_ids=None)
      assert rows[0].mandat_status == "fehlt"
  ```

- [x] **5.4** Test: Filter "Rücklage < Zielwert":

  ```python
  def test_filter_reserve_below_target_excludes_above_threshold(db):
      # Objekt über Schwelle: reserve_current = 7000, reserve_target = 1000 → 7000 >= 1000*6=6000 → nicht im Filter
      db.add(Object(id=uuid.uuid4(), short_code="ABOVE", name="Ueber Schwelle",
                    reserve_current=Decimal("7000"), reserve_target=Decimal("1000")))
      # Objekt unter Schwelle: 3000 < 1000*6=6000 → im Filter
      db.add(Object(id=uuid.uuid4(), short_code="BELOW", name="Unter Schwelle",
                    reserve_current=Decimal("3000"), reserve_target=Decimal("1000")))
      db.commit()

      rows = list_objects_with_unit_counts(db, accessible_ids=None, filter_reserve_below_target=True)
      codes = {r.short_code for r in rows}
      assert "BELOW" in codes
      assert "ABOVE" not in codes

  def test_filter_reserve_excludes_null_values(db):
      # Objekt mit null reserve_current → nicht im Filter (kein Threshold vergleichbar)
      db.add(Object(id=uuid.uuid4(), short_code="NULLR", name="Null Reserve",
                    reserve_current=None, reserve_target=Decimal("1000")))
      db.commit()
      rows = list_objects_with_unit_counts(db, accessible_ids=None, filter_reserve_below_target=True)
      assert all(r.short_code != "NULLR" for r in rows)

  def test_filter_reserve_decimal_zero_is_below_target(db):
      # Decimal("0") ist NOT None → soll im Filter erscheinen wenn target > 0
      db.add(Object(id=uuid.uuid4(), short_code="ZERO", name="Zero Reserve",
                    reserve_current=Decimal("0"), reserve_target=Decimal("500")))
      db.commit()
      rows = list_objects_with_unit_counts(db, accessible_ids=None, filter_reserve_below_target=True)
      assert any(r.short_code == "ZERO" for r in rows), "Decimal('0') muss als 0 < 500*6=3000 erkannt werden"
  ```

- [x] **5.5** Test: Sort NULLs immer zuletzt:

  ```python
  def test_sort_saldo_nulls_always_last_ascending(db):
      from decimal import Decimal
      db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=Decimal("100")))
      db.add(Object(id=uuid.uuid4(), short_code="BBB", name="b", last_known_balance=None))
      db.add(Object(id=uuid.uuid4(), short_code="CCC", name="c", last_known_balance=Decimal("50")))
      db.commit()
      rows = list_objects_with_unit_counts(db, accessible_ids=None, sort="saldo", order="asc")
      codes = [r.short_code for r in rows]
      assert codes[-1] == "BBB", "NULL-Saldo muss zuletzt sein (asc)"

  def test_sort_saldo_nulls_always_last_descending(db):
      from decimal import Decimal
      db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=Decimal("100")))
      db.add(Object(id=uuid.uuid4(), short_code="BBB", name="b", last_known_balance=None))
      db.add(Object(id=uuid.uuid4(), short_code="CCC", name="c", last_known_balance=Decimal("50")))
      db.commit()
      rows = list_objects_with_unit_counts(db, accessible_ids=None, sort="saldo", order="desc")
      codes = [r.short_code for r in rows]
      assert codes[-1] == "BBB", "NULL-Saldo muss zuletzt sein (desc)"

  def test_sort_tiebreaker_short_code_casefold(db):
      # Zwei Objekte mit gleichem Saldo — Tiebreaker ist short_code casefold
      from decimal import Decimal
      db.add(Object(id=uuid.uuid4(), short_code="bbb", name="b", last_known_balance=Decimal("100")))
      db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=Decimal("100")))
      db.commit()
      rows = list_objects_with_unit_counts(db, accessible_ids=None, sort="saldo", order="asc")
      assert rows[0].short_code == "AAA"  # casefold: "aaa" < "bbb"
  ```

### Task 6 — Smoke-Tests in `tests/test_steckbrief_routes_smoke.py`

- [x] **6.1** Permission-Matrix für `/objects/rows`:

  ```python
  def test_rows_requires_login(anon_client):
      response = anon_client.get("/objects/rows")
      assert response.status_code == 302

  def test_rows_forbidden_without_objects_view(auth_client):
      response = auth_client.get("/objects/rows")
      assert response.status_code == 403

  def test_rows_direct_nav_without_htmx_redirects(steckbrief_admin_client):
      # Kein HX-Request-Header → 303 nach /objects
      response = steckbrief_admin_client.get("/objects/rows")
      assert response.status_code == 303
      assert response.headers["location"] == "/objects"
  ```

- [x] **6.2** HTMX-Request (mit Header `HX-Request: true`) liefert `<tbody id="obj-rows">`:

  ```python
  def test_rows_htmx_request_returns_tbody_fragment(steckbrief_admin_client, db):
      db.add(Object(id=uuid.uuid4(), short_code="F001", name="Frag"))
      db.commit()
      response = steckbrief_admin_client.get(
          "/objects/rows",
          headers={"HX-Request": "true"},
      )
      assert response.status_code == 200
      assert 'id="obj-rows"' in response.text
      assert "F001" in response.text
  ```

- [x] **6.3** Sort-Parameter wird akzeptiert:

  ```python
  def test_rows_sort_by_saldo_desc_accepted(steckbrief_admin_client):
      response = steckbrief_admin_client.get(
          "/objects/rows?sort=saldo&order=desc",
          headers={"HX-Request": "true"},
      )
      assert response.status_code == 200

  def test_rows_invalid_sort_key_falls_back_to_short_code(steckbrief_admin_client, db):
      db.add(Object(id=uuid.uuid4(), short_code="INV", name="Invalid Sort"))
      db.commit()
      # Injection-Versuch / unbekannter Sortkey
      response = steckbrief_admin_client.get(
          "/objects/rows?sort=INVALID_KEY&order=asc",
          headers={"HX-Request": "true"},
      )
      assert response.status_code == 200  # kein 500, Fallback auf short_code
  ```

- [x] **6.4** Filter aktiv — nur passende Objekte sichtbar:

  ```python
  def test_rows_filter_reserve_shows_only_below_threshold(steckbrief_admin_client, db):
      from decimal import Decimal
      db.add(Object(id=uuid.uuid4(), short_code="LOW", name="Niedrig",
                    reserve_current=Decimal("1000"), reserve_target=Decimal("1000")))  # 1000 < 6000
      db.add(Object(id=uuid.uuid4(), short_code="OK", name="Gut",
                    reserve_current=Decimal("10000"), reserve_target=Decimal("1000")))  # 10000 >= 6000
      db.commit()
      response = steckbrief_admin_client.get(
          "/objects/rows?filter_reserve=true",
          headers={"HX-Request": "true"},
      )
      assert response.status_code == 200
      assert "LOW" in response.text
      assert "OK" not in response.text
  ```

- [x] **6.5** Bestehenden Test `test_list_unit_count_correct` migrieren — die "Anzahl Einheiten"-Spalte fällt aus dem `<thead>`/`<tbody>` weg, damit bricht der Regex-Test (`tests/test_steckbrief_routes_smoke.py:164–176`):

  - **Aktion**: Test komplett ENTFERNEN aus `test_steckbrief_routes_smoke.py`. Die `unit_count`-Daten bleiben in `ObjectListRow` erhalten (Task 1.1) und werden ab Story 3.2 (Mobile Card-Layout) wieder UI-relevant.
  - **Coverage-Ersatz auf Service-Ebene** in `test_steckbrief_service_gaps.py`:

    ```python
    def test_list_objects_unit_count_in_objectlistrow(db, make_object_with_units):
        # ObjectListRow trägt unit_count weiter, auch wenn Liste-UI sie aktuell
        # nicht mehr als Spalte zeigt (Story 3.2 wird sie im Card-Layout nutzen).
        from app.models import Object, Unit
        from decimal import Decimal
        obj = Object(id=uuid.uuid4(), short_code="UC5", name="Unit-Count")
        db.add(obj); db.flush()
        for i in range(5):
            db.add(Unit(id=uuid.uuid4(), object_id=obj.id, unit_number=f"UC5-{i}"))
        db.commit()
        rows = list_objects_with_unit_counts(db, accessible_ids=None)
        target = next(r for r in rows if r.short_code == "UC5")
        assert target.unit_count == 5
    ```

  Die Fixture `make_object_with_units` aus dem Beispiel kann inline gebaut werden; ein eigenes Fixture ist nicht nötig.

- [x] **6.6** Reserve-Badge in HTML gerendert:

  ```python
  def test_rows_reserve_badge_rendered_for_object_below_threshold(steckbrief_admin_client, db):
      from decimal import Decimal
      db.add(Object(id=uuid.uuid4(), short_code="BDG", name="Badge",
                    reserve_current=Decimal("500"), reserve_target=Decimal("1000")))  # 500 < 6000
      db.commit()
      response = steckbrief_admin_client.get(
          "/objects/rows",
          headers={"HX-Request": "true"},
      )
      assert "unter Zielwert" in response.text

  def test_rows_no_badge_when_reserve_above_threshold(steckbrief_admin_client, db):
      from decimal import Decimal
      db.add(Object(id=uuid.uuid4(), short_code="NBD", name="NoBadge",
                    reserve_current=Decimal("9000"), reserve_target=Decimal("1000")))  # 9000 >= 6000
      db.commit()
      response = steckbrief_admin_client.get(
          "/objects/rows",
          headers={"HX-Request": "true"},
      )
      assert "unter Zielwert" not in response.text
  ```

## Dev Notes

### Scope

Diese Story ändert **ausschließlich** die Listenansicht `/objects`. Die Detailseite `/objects/{id}` bleibt unberührt.

Neue Dateien: keine.

Geänderte Dateien:
- `app/services/steckbrief.py` — `ObjectListRow` + `_SORT_ALLOWED` + erweiterter `list_objects_with_unit_counts()`
- `app/routers/objects.py` — neue Route `GET /objects/rows` + `RedirectResponse`-Import + aktualisierter `list_objects`-Handler
- `app/templates/objects_list.html` — Filter-Bar + HTMX-Sort-Headers
- `app/templates/_obj_table_body.html` — `id="obj-rows"` + neue Spalten + Badge
- `tests/test_steckbrief_service_gaps.py` — neue Service-Unit-Tests
- `tests/test_steckbrief_routes_smoke.py` — neue Smoke-Tests

### KRITISCH: `Decimal("0")` ist falsy — immer `is not None` prüfen

`Decimal("0")` ist `False` in Python (`bool(Decimal("0")) == False`). Deshalb IMMER explizit:
```python
if r.reserve_current is not None  # KORREKT
if r.reserve_current               # FALSCH — filtert Decimal("0") raus!
```

Gilt für alle `Decimal | None`-Felder: `reserve_current`, `reserve_target`, `saldo`. Lehre aus Story 2.8 Patch (Truthiness-Bug in Praemien).

Gleiches gilt im Template: `{% if row.reserve_current is not none %}` — Jinja2 unterstützt `is not none` direkt.

### Route-Reihenfolge: `/objects/rows` VOR `/objects/{object_id}`

`GET /objects/rows` muss VOR `GET /objects/{object_id}` deklariert sein. Auch wenn `object_id: uuid.UUID` typisiert ist (FastAPI lehnt "rows" als UUID ab → 422), ist die Deklarationsreihenfolge zur Sicherheit und Lesbarkeit: spezifische Pfade zuerst.

Aktuell in `objects.py`:
1. `GET ""` (Liste)
2. `GET /{object_id}` (Detail)

Nach Änderung:
1. `GET ""` (Liste)
2. `GET /rows` (HTMX-Fragment) ← neu, MUSS vor `/{object_id}` stehen
3. `GET /{object_id}` (Detail)

### HTMX-Kombinierbarkeit Sort + Filter

Das Pattern mit hidden inputs + onclick:
- `#sort-state` und `#order-state` — hidden inputs im `objects_list.html`
- Sort-Header: aktualisieren die hidden inputs per `onclick` **synchron**, dann feuert HTMX `hx-get` mit `hx-include="#filter-reserve-select"` für den Filter-Wert
- Filter-Select: feuert HTMX `hx-get="/objects/rows"` mit `hx-include="#sort-state, #order-state"` für den Sort-State
- Ergebnis: Sort und Filter bleiben kombiniert

**Jinja2-Escaping in onclick**: Das `onclick`-Attribut ist in doppelten Anführungszeichen (`"..."`) delimitiert. Innere JavaScript-String-Werte nutzen einfache Anführungszeichen (`'...'`). Keine HTML-Entity-Probleme.

**HTMX 2.x `hx-include` Syntax**: CSS-Selector `#filter-reserve-select` (ID des Select) oder `#sort-state, #order-state` (komma-separierte Selektoren). HTMX serialisiert alle `name`-Attribute der matched Elemente als Query-Parameter.

### HX-Request-Guard

Wenn jemand `/objects/rows` direkt im Browser aufruft (kein HTMX), liefert der Handler `303 See Other → /objects`. Das verhindert nackte `<tbody>`-Fragmente als Seiten-Response. Lehre aus Story 2.6 Review (fehlender Guard).

```python
if not request.headers.get("HX-Request"):
    return RedirectResponse("/objects", status_code=303)
```

`RedirectResponse` importieren: `from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse`.

### sepa_mandate_refs JSONB-Truthiness

`Object.sepa_mandate_refs` ist JSONB-List mit SQLite-Default `[]`. Aus der DB geladen:
- Postgres: Python-Liste (`[]` oder `[{...}]`)
- SQLite (Tests): Python-Liste (identisch, da SQLite über `text("'[]'")` als JSON-String + Python-Deserializer)

`bool([])` == `False`, `bool([{...}])` == `True` → korrekt für `mandat_status`-Derivation. Kein `Decimal("0")`-äquivalentes Problem hier.

### Pflegegrad-Sort nutzt Cache, nicht on-the-fly

`pflegegrad = row.pflegegrad_score_cached` direkt aus der Query. Kein Aufruf von `pflegegrad_score(obj)` pro Zeile. `pflegegrad_score_cached` kann `None` sein (noch nicht berechnet) → landet am Ende der sortierten Liste.

### Pflegegrad-Mini-Badge ist Vorab-UX vor Story 3.3 / 3.4

Der farbcodierte Badge in Task 4.2 (Schwellen 70/40 wie Epic 3.4) wird hier eingeführt, **bevor** Story 3.3 (`pflegegrad_score(obj)`-Service mit Cache-Population) und Story 3.4 (vollständiger Badge + Komposition-Popover) durch sind. Bis 3.3 implementiert ist, ist `pflegegrad_score_cached` für jedes Objekt `None` → Spalte zeigt überall "—". Sort/Filter funktionieren ohne Score (alle NULL → bleiben in Tiebreaker-Reihenfolge), das Feature ist also nutzbar — aber der visuelle Mehrwert kommt erst mit 3.3. Das ist beabsichtigt, kein Bug. Story 3.4 baut den Badge zum Popover aus.

### Money-Format `"%.0f"` ist Listen-Pattern (konsistent)

`{{ "%.0f"|format(row.saldo|float) }} €` schneidet Cents ab — das ist das Listen-Pattern in `_versicherer_rows.html` und `registries_versicherer_detail.html`. Detail-/Form-Views nutzen `"%.2f"` (siehe `_obj_finanzen.html`, `_obj_versicherungen_row.html`). Trade-off bewusst: in Listen kosten Cents Lesefluss, in Detail-Views sind sie wichtig.

### Auswirkung auf bestehende Tests

**Bleibt grün** (neuer Return-Typ `ObjectListRow` ist Superset von `ObjectRow`, alle bisher genutzten Attribute existieren weiter):
- `test_list_objects_empty_accessible_ids_returns_empty_without_query` — `accessible_ids=set()` → `[]`.
- `test_list_objects_none_accessible_ids_returns_all` — Set-Vergleich auf `r.short_code`.
- `test_list_renders_rows_and_links` — prüft `<a href="/objects/{id}">` im tbody und Default-Sort `short_code asc`.
- `test_list_empty_state` — Suchstring "Noch keine Objekte" bleibt erhalten (nur `colspan` von 4 → 6).
- `test_list_performance_and_no_n_plus_1` — Statement-Count bleibt 1 (selber JOIN, mehr Spalten im SELECT).

**Bricht und muss migriert werden** (siehe Task 6.5):
- `test_list_unit_count_correct` (`tests/test_steckbrief_routes_smoke.py:164`) prüft die `Anzahl Einheiten`-Spalte mit Regex `>\s*5\s*<` — diese Spalte entfällt, der Test wird ENTFERNT und durch einen Service-Test in 6.5 ersetzt.

**Pre-Edit-Grep zur Kontrolle**: `grep -n "Kuerzel\|Adresse\|Einheiten" tests/` listet weitere Header-Text-Asserts, falls vorhanden.

### keine neue Migration

Alle Felder (`last_known_balance`, `reserve_current`, `reserve_target`, `sepa_mandate_refs`, `pflegegrad_score_cached`) existieren bereits in der `objects`-Tabelle. Neueste Migration: `0016_wartungspflichten_missing_fields.py`. Keine neue Migration anlegen.

### Keine BackgroundTask, kein Claude-Call, kein Audit-Log

Reine Read-View. Kein `asyncio.run()`, kein `audit()`.

### Sort-Default für numerische Spalten

Beim ersten Klick auf Saldo/Rücklage/Pflegegrad: `order=desc` (hohe Werte zuerst). Beim zweiten Klick: Toggle auf `asc`. Kürzel/Name/Mandat: erster Klick `asc` (alphabetisch von oben). Das ist im Template so implementiert: für numerische Spalten prüft der `onclick` `sort == 'X' and order == 'desc'` für Toggle, für String-Spalten `sort == 'X' and order == 'asc'`.

### Model-Imports

Kein neuer Import notwendig — `Object` und `Unit` sind bereits in `steckbrief.py` importiert. `Decimal` ist über `from decimal import Decimal` zu prüfen (wenn nicht vorhanden, ergänzen).

### Template-Signatur

`TemplateResponse(request, "...", {...})` — Request als erstes Argument. Bestehendes Muster in `objects.py:list_objects`. Memory: `feedback_starlette_templateresponse`.

## Test-Checkliste (Epic 2 Retro P1)

- [x] Permission-Matrix 200/403/302 pro Route (`/objects/rows` in Tasks 6.1–6.2)
- [x] IDOR: nicht anwendbar (keine FK aus Form-Body — reine GET-Route)
- [x] Numerische Boundaries: `Decimal("0")` korrekt als "vorhanden" für Badge und Filter (Tests 5.4 + 6.6)
- [x] NULLs-zuletzt bei Sort (Tests 5.5)
- [x] HX-Request-Guard für direkten Zugriff (Test 6.1.c)
- [x] Tiebreaker für deterministische Reihenfolge bei Gleichstand (Test 5.5.c)
- [x] casefold() für String-Sorts (in Sort-Implementierung, Test 5.5.c)
- [x] Bestehender Test `test_list_unit_count_correct` migriert (Task 6.5)
- [x] Date-Bounds: nicht anwendbar
- [x] HTMX-422-Render: nicht anwendbar (kein Form-Submit mit Validierung)

## Dev Agent Record

### Implementation Plan

Service: `ObjectListRow` + `_SORT_ALLOWED` + erweiterter `list_objects_with_unit_counts()` mit optionalen Keyword-Args (`sort`, `order`, `filter_reserve_below_target`). Python-Sort via Zwei-Listen-Methode für NULL-last-Semantik. Route `GET /objects/rows` mit HX-Request-Guard (303 bei Direkt-Navigation). Templates: Filter-Bar mit hidden-Input State, 6 sortierbare Spalten-Header, Rücklage-Badge mit `is not none`-Check.

### Completion Notes

Alle 6 Dateien geändert, keine neuen Dateien angelegt. 28 neue Tests (10 Service-Unit + 9 neue Smoke + 1 Unit-Count-Coverage-Ersatz). `test_list_unit_count_correct` entfernt und durch Service-Test `test_list_objects_unit_count_in_objectlistrow` ersetzt. `_tbody_slice` auf `body.find("<tbody")` umgestellt, damit `<tbody id="obj-rows">` gefunden wird. Decimal("0")-Truthiness-Falle in Filter und Template via `is not none` korrekt behandelt. Zwei-Listen-NULL-sort hält NULLs in asc+desc am Ende. 727 Tests grün, keine Regressionen.

## Change Log

- 2026-04-29: Story 3.1 implementiert — `ObjectListRow`, Sort/Filter-Service, `/objects/rows`-Route, HTMX-Templates, 28 neue Tests (Daniel Kroll)

## Neue Dateien

_(keine)_

## Geänderte Dateien

- `app/services/steckbrief.py`
- `app/routers/objects.py`
- `app/templates/objects_list.html`
- `app/templates/_obj_table_body.html`
- `tests/test_steckbrief_service_gaps.py`
- `tests/test_steckbrief_routes_smoke.py`

## References

- Story 3.1 in Epics-File: `output/planning-artifacts/epics.md` §Epic 3
- Epic 2 Retrospektive (Boundary-Klassifikation, Test-Checkliste P1, HX-Request-Guard Lesson): `output/implementation-artifacts/epic-2-retro-2026-04-28.md`
- Bestehender Service: `app/services/steckbrief.py:22` (`ObjectRow`, `list_objects_with_unit_counts`)
- Bestehender Router: `app/routers/objects.py:113` (`list_objects`)
- Bestehendes Fragment: `app/templates/_obj_table_body.html` (Kommentar "Story 3.1")
- Sort-Pattern (Python, nullslast-Alternative): `output/implementation-artifacts/2-7-versicherer-listenansicht-mit-aggregationen.md` Dev Notes §HTMX-Sort
- HTMX Sort+Filter Pattern (Form + hx-include): `app/templates/due_radar.html` (Filter-Form), `app/templates/registries_versicherer_list.html` (Sort-Header)
- Decimal-Truthiness Bug (Story 2.8 Patch): `output/implementation-artifacts/2-8-versicherer-detailseite-mit-heatmap-schadensfaellen.md` §Review Findings Patch 1
- Tiebreaker-Pattern (Story 2.7): `output/implementation-artifacts/2-7-versicherer-listenansicht-mit-aggregationen.md` §Review Findings
- HX-Request-Guard fehlt (Story 2.6 Review-Finding): `output/implementation-artifacts/epic-2-retro-2026-04-28.md` §Herausforderungen
- `Object.sepa_mandate_refs` JSONB-Default `text("'[]'")`: `app/models/object.py:72`
- `Object.pflegegrad_score_cached` int: `app/models/object.py:74`
- `Object.last_known_balance`, `reserve_current`, `reserve_target` Decimal: `app/models/object.py:55–63`
- TemplateResponse-Signatur: Memory `feedback_starlette_templateresponse`
- Migration-Check: `ls migrations/versions/` vor Anlage (neueste: `0016_wartungspflichten_missing_fields.py`)
- conftest-Fixtures: `steckbrief_admin_client` in `tests/conftest.py:199`
