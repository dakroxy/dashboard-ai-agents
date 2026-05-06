# Story 5.5: UX-Polish & Frontend-Härtung

Status: review

## Story

Als Nutzer und Entwickler der Plattform
möchte ich alle ausstehenden UX-Polish-Findings aus früheren Code-Reviews (27 Einträge) bereinigt haben,
damit die Plattform durchgängig poliert, barrierearmer und konsistent wirkt.

## Hintergrund

Diese Story schließt 27 Deferred-Work-Einträge (#1, #10, #12–#19, #27, #50–#54, #56, #58–#61, #75, #78–#79, #137, #149, #152) aus `output/implementation-artifacts/deferred-work.md`. Alle Items haben Severity `low`, keinen Prod-Blocker und Sprint-Target `post-prod`. Die Story tastet keine Pre-Prod-Sicherheits-Items an — diese wurden in Stories 5-1/5-2 erledigt.

## Acceptance Criteria

### AC1 — Review-Queue: HTMX- und Tabellen-Micro-Fixes (#12, #13, #14, #15, #16, #17)

**Given** die Review-Queue-Tabelle rendert Einträge mit Agent-Referenz, Age-Days und Confidence-Wert

**When** der Dev-Agent die sechs Micro-Fixes anwendet

**Then** gilt:
- **#12**: `app/templates/admin/review_queue.html:16` — `hx-include="[name]"` → `hx-include="closest form"` (Selector nicht mehr page-weit greedy)
- **#13**: `app/templates/admin/review_queue.html:14` — `hx-trigger="change, submit"` → `hx-trigger="change, submit delay:100ms"` (Tab+Enter-Double-Fire durch 100-ms-Debounce verhindert)
- **#14**: `app/templates/admin/_review_queue_rows.html:17` — `<td ... font-mono">{{ item.entry.agent_ref }}</td>` erhält `max-w-[14rem] truncate title="{{ item.entry.agent_ref }}"` (lange Agent-IDs sprengen nicht mehr die Tabelle; Tooltip zeigt Volltext)
- **#15**: `app/routers/admin.py:1102` in `_prepare_entries` — `(now - _aware(e.created_at)).days` → `max(0, (now - _aware(e.created_at)).days)` (kein negativer Age-Days-Wert bei Clock-Drift)
- **#16**: Confidence-Clamp **Python-seitig** in `app/routers/admin.py:_prepare_entries` (Zeilen 1088–1104) — robuster als Jinja-Verschachtelung. Im Loop nach dem `value_str`-Block: `clamped_conf = min(1.0, max(0.0, e.confidence or 0.0))` und ins Result-Dict aufnehmen: `"confidence_pct": round(clamped_conf * 100)`. Dann in `app/templates/admin/_review_queue_rows.html:20` `{{ (item.entry.confidence * 100) | round | int }} %` → `{{ item.confidence_pct }} %` (Confidence aus [0,1] geclampt; Template-Bucket-Logik in Zeile 19 nutzt weiterhin `item.entry.confidence` für die Farb-Schwellen 0.5/0.8 — das ist OK, weil Werte > 1.0 dann grün bleiben statt zu klippen)
- **#17**: `app/templates/admin/_review_queue_rows.html:7` — `{{ item.entry.target_entity_id | string | truncate(8, True, '') }}` → `object/{{ item.entry.target_entity_id | string | truncate(8, True, '') }}` (Anchor-Text hat `object/`-Prefix, lesbar wie in der Spec)
- **And** alle existierenden Tests bleiben grün

**Test**: `test_review_queue_micro_fixes` in `tests/test_ux_polish.py` — Mock-Einträge mit `agent_ref="x"*40`, `confidence=1.5`, `created_at = now + timedelta(seconds=10)` (Future-Timestamp); GET `/admin/review-queue`; prüft: (a) `max-w-[14rem]` und `truncate` im HTML, (b) "100 %" statt "150 %" (clamped), (c) "0 Tage" statt "-1 Tage" (max-Guard), (d) "object/" im Anchor-Text vor der `truncate(8)`-ID.

---

### AC2 — Sidebar/Navigation: Doppel-Highlight + Collision-Fix (#18, #27)

**Given** `app/templates/base.html` enthält zwei Sidebar-Aktiv-Erkennungs-Blöcke

**When** der Nutzer `/admin/review-queue` aufruft

**Then**:
- **#18** — `base.html:139` ändert `{% set active = path.startswith("/admin") %}` zu `{% set active = path.startswith("/admin") and not path.startswith("/admin/review-queue") %}` (kein Doppel-Highlight mehr: Review-Queue- und Admin-Link gleichzeitig aktiv)
- **#27** — Trailing-Slash-Guard an **beiden** Stellen, an denen `wf.url.rstrip('/')` als Prefix-Match dient:
  - `base.html:86` (Workflow-In-Path-Detection für `ns.in_wf_path`): `path.startswith(wf.url.rstrip('/'))` → `(path == wf.url or path.startswith(wf.url.rstrip('/') + '/'))`
  - `base.html:93` (Workflow-Active-Setter): `path == wf.url or (wf.url|length > 1 and path.startswith(wf.url.rstrip('/')))` → `path == wf.url or (wf.url|length > 1 and path.startswith(wf.url.rstrip('/') + '/'))` (das `+ '/'` reicht, der `path == wf.url`-Check bleibt unverändert)
  - Effekt: `/contacts` matcht nicht mehr `/contacts/newsletter`
- **And** Test: `test_sidebar_active_no_double_highlight` — prüft GET `/admin/review-queue` → HTML enthält exakt EINEN aktiven Sidebar-Link mit `review-queue`-Href und KEINEN zusätzlichen aktiven Admin-Link

---

### AC3 — Objekt-Liste: Sort/Filter-State + Loading-Feedback (#58, #59, #61)

**Given** `app/routers/objects.py:list_objects` (Voll-Page GET `/objects`) ignoriert Query-Params `sort`, `order`, `filter_reserve` und gibt immer Defaults zurück; die HTMX-Trigger in `_obj_table_head.html` (Sort-`<th>`s) und `_obj_filter_bar.html` (Filter-`<select>`) haben kein `hx-push-url` und kein `hx-indicator`

**When** der Fix angewendet wird

**Then**:
- **#61** — `list_objects` (`app/routers/objects.py:128`) erhält dieselben Query-Params wie `list_objects_rows` (`sort: str = Query("short_code")`, `order: str = Query("asc")`, `filter_reserve: str = Query("false")`); wendet `filter_reserve_below_target=filter_bool` (analog `_FILTER_TRUE_VALUES`-Lookup auf Zeile 157) auf `list_objects_with_unit_counts` an und gibt `sort`, `order`, `filter_reserve` korrekt im Template-Context zurück — direktes Bookmark-Aufrufen rendert gefilterte Liste
- **#58** — `hx-push-url="true"` wird ergänzt an: (a) allen 6 Sort-`<th>`-Elementen in `app/templates/_obj_table_head.html` (Zeilen 11, 20, 29, 38, 47, 56) und (b) dem Filter-`<select id="filter-reserve-select">` in `app/templates/_obj_filter_bar.html:11` (Sort-/Filter-Klick persistiert URL in Browser-History, Backbutton funktioniert)
- **#59** — `hx-indicator="#objects-loading"` an dieselben Trigger-Elemente wie #58 ergänzen. Der ausgeblendete Spinner `<div id="objects-loading" class="htmx-indicator ...">…Lädt…</div>` wird in `app/templates/objects_list.html` direkt vor dem Desktop-Block (`{# Desktop: Filter-Bar + Sort-Tabelle #}`, ca. Zeile 65) eingefügt (HTMX schaltet ihn via `.htmx-request`-Klasse ein, Tailwind: `htmx-indicator` ist eine custom-class — entweder `<style>.htmx-request .htmx-indicator{display:inline}.htmx-indicator{display:none}</style>` lokal in `objects_list.html` oder Tailwind-Pattern via `htmx-request:opacity-100 opacity-0 transition-opacity`)
- **And** Mobile-Layout: da `list_objects` jetzt `filter_reserve` berücksichtigt, zeigen Mobile-Cards ebenfalls korrekte gefilterte Rows (#51 wird als Nebeneffekt mitgelöst — kein separater Schritt nötig)
- **And** Test: `test_list_objects_full_page_respects_filter_reserve` — GET `/objects?filter_reserve=true` mit Mock-Daten, bei dem 2 von 3 Objekten über Reserve-Ziel; prüft, dass nur 1 Objekt in der Response erscheint

---

### AC4 — Geldbeträge Tausenderpunkt + A11y Sort-Header (#56, #60)

**Given** Geldbeträge in `app/templates/_obj_table_body.html` erscheinen ohne Tausenderpunkt; Sort-Header in `app/templates/_obj_table_head.html` haben kein `aria-sort`, kein `tabindex`, kein Keyboard-Handler

**When** AC4 implementiert ist

**Then**:
- **#60** — In `app/templating.py` neuer Jinja2-Filter `money_de` registrieren: `lambda v: f"{float(v):,.0f}".replace(",", ".")` (gibt `"1.234.567"` für `1234567.0`; Tausenderpunkt Deutsch). Registrierung analog zur bestehenden Zeile `templates.env.filters["iban_format"] = _format_iban` (`app/templating.py:250`). In `_obj_table_body.html:18,28` `"%.0f"|format(row.saldo|float)` → `row.saldo | money_de`, analog `row.reserve_current | money_de`.
- **#56** — Alle 6 Sort-`<th>`-Elemente in `app/templates/_obj_table_head.html` (Zeilen 11, 20, 29, 38, 47, 56) erhalten:
  - `tabindex="0"` (Keyboard-fokussierbar)
  - `role="button"` (Screenreader erkennt Interaktivität)
  - `aria-sort="{{ 'ascending' if sort == col and order == 'asc' else 'descending' if sort == col and order == 'desc' else 'none' }}"` mit `col` = `'short_code'` / `'name'` / `'saldo'` / `'reserve_current'` / `'mandat_status'` / `'pflegegrad'` (nur für sortierbare Spalten)
  - `onkeydown="if(event.key==='Enter'||event.key===' '){this.click();event.preventDefault();}"` (Enter/Space feuert Klick)
- **And** Test: `test_money_de_filter` — Unit-Test `app/templating.py`, prüft `1234567.4 | money_de == "1.234.567"`

---

### AC5 — Mobile-Layout-Fixes (#52, #54)

**Given** Mobile-Cards in `objects_list.html` rendern `pflegegrad` ohne Range-Cap; Snap-Wrapper in `_obj_technik.html` haben keine konsistente Mindestbreite

**When** AC5 implementiert ist

**Then**:
- **#52** — `app/templates/objects_list.html:29-31` — `{{ row.pflegegrad }}%` → `{{ [[row.pflegegrad | int, 0] | max, 100] | min }}%`; das `{% if row.pflegegrad >= 70 %}text-green` etc. Farbbuckets nutzen denselben geclampt-Wert (Hilfsvariable `{% set pct = [[row.pflegegrad | int, 0] | max, 100] | min %}`)
- **#54** — `app/templates/_obj_technik.html:60-67` — alle `snap-start flex-none`-Wrapper erhalten `min-w-[6rem]` (Snap-Konsistenz auf iOS Safari ≥ 15)
- **And** Hinweis: `#51` (Mobile filtert `filter_reserve` nicht) wird durch den AC3-Fix in `list_objects` mitgelöst — kein Extra-Code für AC5

---

### AC6 — Technik-Sektion: Tel-URI + max_len-Härtung (#50, #53)

**Given** `app/templates/_obj_technik_field_view.html:11` baut `tel:`-URIs ohne Whitespace-Normalisierung; `app/services/steckbrief.py:TechnikField` nutzt `max_len=500` auch für `kind="tel"`-Felder

**When** AC6 implementiert ist

**Then**:
- **#50** — `_obj_technik_field_view.html:11`: `href="tel:{{ field.value }}"` → `href="tel:{{ field.value | replace(' ', '') | replace('(', '') | replace(')', '') | replace('-', '') }}"` (RFC-3966-kompatibel, entfernt Klammern und Trennzeichen, iOS-Safari sicher; nur für das `href`, sichtbarer Text bleibt unverändert)
- **#53** — `app/services/steckbrief.py`: alle `TechnikField`-Instanzen mit `kind="tel"` erhalten explizit `max_len=30`; konkret betroffen: `heating_hotline` (`TECHNIK_HEIZUNG`-Tuple) und alle anderen `tel`-Felder — Dev-Agent sucht mit `grep -n 'kind="tel"' app/services/steckbrief.py` und ergänzt `max_len=30`
- **And** Kein Datenmodell-Change nötig — `TechnikField.max_len` existiert bereits (Zeile ~439); `max_len=30` greift an der Eingabe-Validation (wo der Router diesen Wert nutzt)

---

### AC7 — Extraction-UI: Per-Feld-Manuell-Pill + IBAN-Input-Hints + Pen-Icon-A11y (#75, #78, #79)

**Given** `app/templates/_extraction_field_view.html` zeigt keinen Per-Feld-"manuell"-Indikator; IBAN/BIC-Felder im Edit-Formular haben keine Mobile-Eingabe-Optimierung; Pen-Icon-A11y ist nur in `_extraction_field_view.html` vorhanden

**When** AC7 implementiert ist

**Then**:
- **#75 — Per-Feld-Manuell-Pill**:
  - `app/services/document_field_edit.py:update_extraction_field` (Zeile 110+): Das JSONB-Feld auf `Extraction` heisst **`extracted`** (nicht `data`). Aktuell baut die Funktion `new_extracted = copy.deepcopy(latest.extracted); new_extracted[field] = new_value` (Zeilen 170–171). Direkt nach der Wert-Zuweisung ergänzen: `new_extracted.setdefault("_manual_fields", []); if field not in new_extracted["_manual_fields"]: new_extracted["_manual_fields"].append(field)`. Damit ist die Liste auf der neuen Extraction-Row vor dem `db.add(new_extraction)` (Zeile 194) gepflegt.
  - `app/templates/_extraction_block.html`: Vor der `{% for label, key in fields %}`-Schleife (Zeile 68) `{% set manual_fields = extraction.extracted.get("_manual_fields", []) if extraction.extracted else [] %}` einführen. Direkt vor der Include-Zeile (`{% include "_extraction_field_view.html" %}`, Zeile 70) `{% set is_manual = key in manual_fields %}` setzen — das Include erbt den Context.
  - `app/templates/_extraction_field_view.html`: Optionaler Template-Var `is_manual` (Default via `{% set is_manual = is_manual | default(false) %}` am Anfang). Bei `is_manual` nach dem `<dd>`-Block (nach Zeile 15) `<span class="ml-1 text-xs font-medium text-amber-600 bg-amber-50 px-1 rounded">manuell</span>` rendern.
  - **Keine Migration** nötig (`Extraction.extracted` ist bereits JSONB; `_manual_fields` ist ein optionaler Top-Level-Key, der von `chat_about_mandate` u. a. ignoriert wird, weil sie über die Pydantic-Felder iterieren).
  - Test: `test_manual_pill_set_on_field_edit` in `tests/test_ux_polish.py` — Setup: SEPA-Lastschrift-Document (`workflow.key == "sepa_mandate"`, Status `extracted`) mit einer initialen Extraction-Row. Aufruf: `result = update_extraction_field(db, doc, "owner_name", "Müller GmbH", user, request)`. Asserts: `result.extracted["_manual_fields"] == ["owner_name"]` und `result.extracted["owner_name"] == "Müller GmbH"`. Zweiter Aufruf für `iban` → `result2.extracted["_manual_fields"] == ["owner_name", "iban"]` (idempotent: gleiches Feld zweimal taucht nur einmal auf).
- **#78 — Pen-Icon-A11y**:
  - In `_extraction_field_view.html:22` ist `aria-label="{{ label | striptags }} bearbeiten"` bereits vorhanden.
  - Fix: Konsistenzprüfung + Ergänzung in anderen Edit-Trigger-Templates, die noch kein `aria-label` haben. Dev-Agent prüft: `grep -rn 'hx-get.*edit\|data-edit-field\|Bearbeiten.*button\|button.*edit' app/templates/` und ergänzt `aria-label="… bearbeiten"` wo es fehlt. Besonders: `_obj_technik_field_view.html`, `_obj_zugangscode_view.html` (wenn sie Edit-Buttons haben).
- **#79 — IBAN/BIC-Input-Hints**:
  - `app/templates/_extraction_field_edit.html:19`: Für IBAN- und BIC-Felder `autocapitalize="characters" autocorrect="off" autocomplete="off"` ergänzen.
  - Pattern: `{% if key == "iban" or key == "bic" %}autocapitalize="characters" autocorrect="off" autocomplete="off"{% endif %}` als Inline-Attribute.
  - **Nicht** `inputmode="numeric"` — IBAN enthält Buchstaben; `inputmode="text"` ist der Default und korrekt.

---

### AC8 — Versicherungen-UI: 422-Formular-Sichtbarkeit + Stale-Dropdown (#137, #149)

**Given** `app/templates/_obj_versicherungen.html:28` zeigt Police-Form-Fehler, lässt aber das Formular `hidden`; `app/routers/registries.py:dienstleister_create` OOBt nur das Dropdown der anfragenden Police

**When** AC8 implementiert ist

**Then**:
- **#137** — `_obj_versicherungen.html:28`: `class="hidden ..."` → `class="{% if form_error is defined and form_error %}{% else %}hidden {% endif %}..."`. Das Formular bleibt bei `form_error` sichtbar. Analog für das `schaden`-Formular: `{% if schaden_form_error is defined and schaden_form_error %}`-Flag bei `<details id="schadensfall-form-toggle">` ergänzen (bereits geprüft: `details` öffnet sich via `{% if sfe %} open{% endif %}` — OK).
- **#149** — `app/routers/registries.py:dienstleister_create` (Zeilen 137–181): aktuell wird nur das Dropdown der **anfragenden** Police als OOB-Antwort geliefert (Zeile 165–172). Fix: alle Policen-IDs des aktuellen Objekts als Hidden-Inputs ins Form `_registries_dienstleister_form.html` aufnehmen (`<input type="hidden" name="other_policy_ids" value="{{ p.id }}">` pro Police), dann im Handler nach erfolgreicher Anlage für **jede** weitergegebene `policy_id` einen OOB-Select-Block rendern und konkateniert zurückgeben. Pattern: Liste `policy_ids = [policy_id, *other_policy_ids]` aufbauen, im Loop `templates.get_template("_registries_dienstleister_options.html").render(target_dropdown_id=f"dienstleister-dropdown-{pid}", all_dienstleister=all_dienstleister, selected_id=str(new_d.id) if pid == policy_id else "", request=request)` aufrufen, alle Strings mit `\n` joinen + den `oob_clear`-Block anhängen. Damit refreshen alle Dropdowns auf der Seite mit dem neuen Eintrag (Selection nur beim Form-Trigger). **Begründung Variante**: typisch ≤ 5 Policen pro Objekt, OOB-Multi ist deterministisch und braucht keinen zusätzlichen GET-Endpoint. HX-Trigger-Variante wurde verworfen, weil sie pro Dropdown einen zusätzlichen GET nötig macht.
- **And** Test: `test_police_form_visible_on_validation_error` — GET Versicherungs-Sektion mit `form_error="..."` im Context; prüft, dass `#neue-police-form` NICHT `hidden` enthält.

---

### AC9 — JS-Confirm-Pattern + HTML-ID-Eindeutigkeit-Test (#1, #152)

**Given** Confirm-Dialoge in Templates nutzen `onsubmit="return confirm('...{{ name }}...')"` was bei Apostrophen im Namen den JS-String unterbricht; HTML-ID-Eindeutigkeit auf der Objekt-Detail-Seite ist nicht test-geschützt

**When** AC9 implementiert ist

**Then**:
- **#1** — Es gibt **8** `onsubmit="return confirm(...)"`-Vorkommen (`grep -rn 'onsubmit="return confirm' app/templates/`), aber nur **2** mit Jinja-Interpolation, die den Apostroph-Bug triggern können: `app/templates/case_detail.html:142` (`'Dokument {{ doc.original_filename }} entfernen?'`) und `app/templates/case_detail.html:567` (`'Gebäude {{ b.name }} entfernen?'`). Die übrigen 6 Stellen (case_detail.html:227, 315, 1007; admin/role_edit.html:98; admin/logs.html:92; admin/user_edit.html:33) haben statischen Text und sind nicht buggy.
  - **Implementierung**: Globaler `data-confirm`-Handler in `app/templates/base.html` (kurz vor `</body>`):
    ```html
    <script>
    document.addEventListener('submit', function(e){
      var t = e.target;
      var msg = t && t.dataset && t.dataset.confirm;
      if (msg && !confirm(msg)) { e.preventDefault(); }
    });
    </script>
    ```
  - In `case_detail.html:142` und `:567` das `onsubmit="return confirm('…');"` durch `data-confirm="…"` auf demselben `<form>`-Element ersetzen (Jinja-Autoescape im Attribut-Kontext kümmert sich um Apostrophe automatisch). Beispiel: `<form ... data-confirm="Dokument {{ doc.original_filename }} entfernen?">`. Die anderen 6 Stellen optional auf das gleiche Pattern migrieren (Konsistenz, kein Bug).
- **#152** — `tests/test_steckbrief_routes_smoke.py` (oder neue Datei): Smoke-Test, der die gerenderte Objekt-Detail-Seite (`GET /objects/{id}`) parst und auf HTML-ID-Eindeutigkeit prüft. Implementation: `import re; ids = re.findall(r'\bid="([^"]+)"', body); dupes = [i for i in ids if ids.count(i) > 1]; assert not dupes, f"Doppelte IDs: {set(dupes)}"`. Kein externer HTML-Parser benötigt.

---

### AC10 — PDF-Tfoot-Break-Before + Test-Fragility-Fix (#10, #19)

**Given** `app/templates/etv_signature_list_pdf.html:164` (das `<tfoot>`-Element) kann auf fast leerer Page landen; `tests/test_steckbrief_routes_smoke.py:244` nutzt fragilen `<main>`-Split

**When** AC10 implementiert ist

**Then**:
- **#10** — `etv_signature_list_pdf.html:164` — Im `<tfoot>`-Element CSS `break-before: avoid` ergänzen: `<tfoot style="break-before: avoid; page-break-before: avoid;">`. Zusätzlich auf dem umschließenden `<table>` prüfen ob `page-break-inside: avoid` gesetzt ist (falls nicht, ergänzen — das `<table>`-Tag steht typischerweise oberhalb des hier sichtbaren `<tbody>`-Blocks). WeasyPrint 60+ versteht `break-before: avoid`.
- **#19** — `tests/test_steckbrief_routes_smoke.py:244`: Den Slice-Ausdruck `body.split("<main")[1].split("</main>")[0] if "<main" in body else body` durch `re.search(r'<main[^>]*>(.*?)</main>', body, re.DOTALL)` ersetzen (`.group(1)` falls Match, sonst `body`; `import re` ist in der Datei bereits vorhanden bzw. ergänzen). Damit ist der Test robust gegenüber HTML-Attributen auf dem `<main>`-Tag.
- **And** alle existierenden Tests grün; etv_signature_list_pdf-Tests (falls vorhanden) prüfen nur Render-Erfolg, keine Pixel-Positionierung.

---

### AC11 — Deferred-Work.md-Updates (#1–#152 der abgearbeiteten Items)

**Given** alle 27 Items in `deferred-work.md` haben Sprint-Target `post-prod`

**When** AC1–AC10 implementiert sind

**Then** werden die entsprechenden Items in der Triage-Tabelle mit `[done-5-5]`-Tag in der Sprint-Target-Spalte markiert (z.B. `post-prod [done-5-5]`), damit die Triage-Tabelle korrekt bleibt.

---

## Tasks / Subtasks

- [x] **Task 1: AC1 — Review-Queue Micro-Fixes** (#12 #13 #14 #15 #16 #17)
  - [x] 1.1 `review_queue.html:16` `hx-include` → `closest form`
  - [x] 1.2 `review_queue.html:14` `hx-trigger` → `change, submit delay:100ms`
  - [x] 1.3 `_review_queue_rows.html:17` `agent_ref`-td: `max-w-[14rem] truncate` + `title`-Attribut
  - [x] 1.4 `admin.py:1102` `age_days` → `max(0, ...)`
  - [x] 1.5 `admin.py:_prepare_entries` Python-Clamp `confidence_pct` + `_review_queue_rows.html:20` auf `item.confidence_pct` umstellen
  - [x] 1.6 `_review_queue_rows.html:7` Anchor-Text mit `object/`-Prefix
  - [x] 1.7 Test: `test_review_queue_micro_fixes` in neuer Datei `tests/test_ux_polish.py`

- [x] **Task 2: AC2 — Sidebar/Navigation** (#18 #27)
  - [x] 2.1 `base.html:139` Admin-Link nicht aktiv bei `/admin/review-queue`
  - [x] 2.2 `base.html:86` und `base.html:93` Workflow-Active-Detection mit Trailing-Slash-Guard (`+ '/'` an beiden Stellen)
  - [x] 2.3 Test: `test_sidebar_active_no_double_highlight`

- [x] **Task 3: AC3 — Objekt-Liste Sort/Filter-State** (#58 #59 #61)
  - [x] 3.1 `app/routers/objects.py:128 list_objects` Query-Params `sort`, `order`, `filter_reserve` + Filter-Logik analog `list_objects_rows`
  - [x] 3.2 `_obj_table_head.html` (alle 6 Sort-`<th>`s) und `_obj_filter_bar.html:11` (Filter-`<select>`): `hx-push-url="true"` ergänzen
  - [x] 3.3 Loading-Spinner `<div id="objects-loading">` in `objects_list.html` einfügen + `hx-indicator="#objects-loading"` an dieselben Trigger-Elemente wie 3.2
  - [x] 3.4 Test: `test_list_objects_full_page_respects_filter_reserve`

- [x] **Task 4: AC4 — Money-Format + A11y Sort-Header** (#56 #60)
  - [x] 4.1 `app/templating.py:250+`: Filter `money_de` registrieren (analog `iban_format`)
  - [x] 4.2 `_obj_table_body.html:18,28`: `money_de`-Filter einsetzen
  - [x] 4.3 `_obj_table_head.html` (alle 6 Sort-`<th>`s): `tabindex`, `role="button"`, `aria-sort`, `onkeydown`
  - [x] 4.4 Test: `test_money_de_filter` (Unit-Test)

- [x] **Task 5: AC5 — Mobile-Layout-Fixes** (#52 #54)
  - [x] 5.1 `objects_list.html:29-31` pflegegrad-Range-Cap via Jinja-Min/Max
  - [x] 5.2 `_obj_technik.html:60-67` `min-w-[6rem]` auf Snap-Wrappern

- [x] **Task 6: AC6 — Technik-Sektion** (#50 #53)
  - [x] 6.1 `_obj_technik_field_view.html:11` Tel-URI Whitespace/Klammer-Strip
  - [x] 6.2 `steckbrief.py`: alle `kind="tel"` `TechnikField`-Instanzen mit `max_len=30` via grep ermitteln und ergänzen

- [x] **Task 7: AC7 — Extraction-UI** (#75 #78 #79)
  - [x] 7.1 `document_field_edit.py:update_extraction_field` (Z. 110+): `_manual_fields`-Liste in `extracted` pflegen (Feld heisst `extracted`, nicht `data`)
  - [x] 7.2 `_extraction_block.html` (vor Z. 70): `manual_fields` aus `extraction.extracted` ziehen, `is_manual` per `{% set %}` vor dem Include setzen
  - [x] 7.3 `_extraction_field_view.html`: `is_manual` Default + "manuell"-Pill rendern
  - [x] 7.4 Pen-Icon-A11y: Grep `grep -rn 'data-edit-field\|hx-get.*edit' app/templates/`; fehlende `aria-label`-Attribute (insb. `_obj_technik_field_view.html:28`, ggf. `_obj_zugangscode_view.html`) ergänzen
  - [x] 7.5 `_extraction_field_edit.html:19`: IBAN/BIC-Felder `autocapitalize="characters" autocorrect="off" autocomplete="off"`
  - [x] 7.6 Test: `test_manual_pill_set_on_field_edit` (SEPA-Lastschrift-Doc-Setup, prüft `result.extracted["_manual_fields"]`)

- [x] **Task 8: AC8 — Versicherungen-UI** (#137 #149)
  - [x] 8.1 `_obj_versicherungen.html:28`: Formular bei `form_error` nicht `hidden`
  - [x] 8.2 `_registries_dienstleister_form.html`: Hidden-Inputs `other_policy_ids` mit allen Policy-IDs des Objekts
  - [x] 8.3 `registries.py:dienstleister_create` (Z. 137+): OOB-Multi-Render aller Dropdowns (anfragende Police selektiert, übrige nur refreshed)
  - [x] 8.4 Test: `test_police_form_visible_on_validation_error`

- [x] **Task 9: AC9 — JS-Confirm + HTML-ID-Test** (#1 #152)
  - [x] 9.1 `base.html`: Globaler `data-confirm`-JS-Handler (vor `</body>`)
  - [x] 9.2 `case_detail.html:142` und `:567`: `onsubmit="return confirm('...{{ name }}...');"` → `data-confirm="...{{ name }}..."` (die anderen 6 Stellen ohne Jinja-Interpolation optional gleich mitziehen)
  - [x] 9.3 Test: HTML-ID-Eindeutigkeit-Smoke-Test für Objekt-Detail-Seite

- [x] **Task 10: AC10 — PDF-Tfoot + Test-Fragility** (#10 #19)
  - [x] 10.1 `etv_signature_list_pdf.html:164` (`<tfoot>`): `break-before: avoid; page-break-before: avoid`
  - [x] 10.2 `test_steckbrief_routes_smoke.py:244`: Fragilen `<main>`-Split durch `re.search(r'<main[^>]*>(.*?)</main>', body, re.DOTALL)` ersetzen

- [x] **Task 11: AC11 — Deferred-Work.md aktualisieren**
  - [x] 11.1 Alle 27 Items in der Triage-Tabelle mit `[done-5-5]` markieren

## Dev Notes

### Projektstruktur-Ankerpunkte

- **Jinja2-Filter**: Neue Filter **nur** in `app/templating.py` registrieren (Singleton `templates`), analog `templates.env.filters["iban_format"] = _format_iban` (Z. 250). Router importieren `templates` von dort.
- **Template-Response-Signatur**: `templates.TemplateResponse(request, "name.html", {...})` — `request` ist erstes Argument. Die alte Signatur `(name, {"request": req})` wirft `TypeError: unhashable type dict` tief in Jinja2 ([memory: feedback_starlette_templateresponse]).
- **HTMX-Fragmente**: Fragment-Templates (für HTMX-Swaps) beginnen mit Underscore (`_name.html`); vollständige Seiten ohne.
- **Keine neuen Migrations** nötig — alle Änderungen sind Template/Router/Service-seitig oder nutzen bestehende JSONB-Felder.
- **Kein neues Python-Paket** erforderlich — `selectolax` ist NICHT installiert; HTML-ID-Test per `re.findall`.

### Kritische Detailhinweise pro AC

**AC1 Confidence-Clamp Python-seitig:**
Statt Jinja-Verschachtelung erfolgt der Clamp in `_prepare_entries` als `min(1.0, max(0.0, e.confidence or 0.0))`. Robust gegen `None` und negative Werte. Color-Bucket-Logik (`item.entry.confidence >= 0.8`) bleibt auf dem Roh-Wert — bei `confidence=1.5` ist die Pille grün und der Text "100 %", was die gewünschte UX ist (Anzeige clamped, Severity bewusst nicht).

**AC3 `list_objects` — Wichtig:**
`list_objects_rows` (Z. 161+) nutzt `list_objects_with_unit_counts(db, accessible_ids=accessible, sort=..., order=..., filter_reserve_below_target=...)`. `list_objects` (Z. 128+) übergibt derzeit keine Sort/Filter-Parameter. Die Funktion `list_objects_with_unit_counts` in `app/services/steckbrief.py` akzeptiert diese Parameter bereits (von 5-4 verifiziert) — keine Service-Anpassung nötig. Sort-/Filter-Trigger leben in `_obj_table_head.html` (sort) und `_obj_filter_bar.html` (filter), beide werden in `objects_list.html` per `{% include %}` eingebunden.

**AC4 `money_de`-Filter — Pythons `f"{v:,.0f}"` nutzt `","` als Tausendtrennzeichen (US-Format):**
Daher `.replace(",", ".")` notwendig für deutsches Format. Testfall: `1234567.0` → `"1.234.567"`.

**AC7 `_manual_fields`-JSONB:**
Das JSONB-Feld auf `Extraction` heisst **`extracted`** (nicht `data`). Der Pattern `new_extracted = copy.deepcopy(latest.extracted)` ist auf `document_field_edit.py:170` schon vorhanden — `_manual_fields` direkt am `new_extracted`-Dict pflegen, nicht eine zusätzliche Variable einführen. Da das Dict frisch deepcopy'd ist, ist kein `flag_modified` nötig; SQLAlchemy erkennt den ganzen-Spalten-Replace beim `db.add(new_extraction)`.

**AC8 OOB-Multi-Dropdown-Refresh:**
Aktueller Code rendert nur das anfragende Dropdown OOB. Erweiterung: Hidden-Inputs `other_policy_ids` im Form sammeln (im Versicherungen-Section-Template einsetzen), im Handler über alle Policy-IDs iterieren und pro ID einen OOB-Block rendern. Wichtig: `target_dropdown_id=f"dienstleister-dropdown-{pid}"` muss exakt mit der ID im Versicherungen-Template übereinstimmen.

**AC9 `data-confirm`-Handler:**
Den Handler-`<script>`-Block am Ende des `<body>` von `base.html` platzieren (nach HTMX-CDN-Import). Event-Delegation auf `submit`-Event statt per-Element-Binding. `data-confirm` ist case-insensitive in HTML, aber Dataset-Access nutzt `dataset.confirm` (camelCase-Konvertierung).

### Testing-Strategie

- Test-DB: SQLite in-memory mit `StaticPool` (siehe `tests/conftest.py`). Keine neue Infrastruktur.
- Für Template-Tests: `client.get(url)` → `response.text` durchsuchen. Kein Playwright.
- Neue Tests bevorzugt in `tests/test_steckbrief_routes_smoke.py` oder eine neue `tests/test_ux_polish.py` anlegen.
- `asyncio_mode = "auto"` — kein `@pytest.mark.asyncio` pro Test nötig.
- Anthropic/Impower immer mocken. Kein Netzwerk-Call in Tests.

### Dateien die geändert werden

**Templates:**
- `app/templates/admin/review_queue.html` (AC1: #12 #13)
- `app/templates/admin/_review_queue_rows.html` (AC1: #14 #16 #17)
- `app/templates/base.html` (AC2: #18 #27 — Z. 86, 93, 139; AC9: #1 globaler Handler vor `</body>`)
- `app/templates/_obj_table_head.html` (AC3: #58 #59 — sort-`<th>`-Trigger; AC4: #56 — A11y auf Sort-Headern)
- `app/templates/_obj_filter_bar.html` (AC3: #58 #59 — Filter-`<select>`-Trigger)
- `app/templates/objects_list.html` (AC3: Loading-Spinner-Container; AC5: #52 — Mobile-Card pflegegrad-Clamp)
- `app/templates/_obj_table_body.html` (AC4: #60 — money_de-Filter)
- `app/templates/_obj_technik.html` (AC5: #54 — `min-w-[6rem]` auf snap-Wrappern)
- `app/templates/_obj_technik_field_view.html` (AC6: #50 — tel-URI; AC7: #78 — Edit-Button aria-label)
- `app/templates/_extraction_block.html` (AC7: #75 — manual_fields aus `extraction.extracted`)
- `app/templates/_extraction_field_view.html` (AC7: #75 — is_manual + Pill)
- `app/templates/_extraction_field_edit.html` (AC7: #79 — IBAN/BIC-Input-Hints)
- `app/templates/_obj_versicherungen.html` (AC8: #137 — Form-Visibility; #149 — `other_policy_ids`-Hidden-Inputs ggf. hier oder im Form-Template)
- `app/templates/_registries_dienstleister_form.html` (AC8: #149 — Hidden-Inputs für andere Policy-IDs)
- `app/templates/case_detail.html` (AC9: #1 — Z. 142, 567 mit Jinja-Interp; übrige optional)
- `app/templates/etv_signature_list_pdf.html` (AC10: #10 — `<tfoot>` Z. 164)
- Ggf. `app/templates/_obj_zugangscode_view.html` (AC7: #78 — falls Edit-Button vorhanden)

**Python:**
- `app/routers/admin.py` (AC1: #15 + #16 — `_prepare_entries`)
- `app/routers/objects.py` (AC3: #61 — `list_objects` Z. 128 mit Query-Params)
- `app/routers/registries.py` (AC8: #149 — `dienstleister_create` OOB-Multi)
- `app/services/steckbrief.py` (AC6: #53 — `heating_hotline` `max_len=30`)
- `app/services/document_field_edit.py` (AC7: #75 — `_manual_fields` in `extracted`)
- `app/templating.py` (AC4: #60 — `money_de`-Filter)

**Tests:**
- `tests/test_steckbrief_routes_smoke.py` (AC10: #19 — Z. 244 main-Split via Regex; AC9: #152 ID-Eindeutigkeit-Test ggf. hier oder in `test_ux_polish.py`)
- `tests/test_ux_polish.py` (neu, ACs 1–8)
- `output/implementation-artifacts/deferred-work.md` (AC11)

### Abgrenzung / Out-of-Scope

Diese Story bearbeitet **nicht**:
- #2 Audit-`details_json` Umlaute (Ops-Doku-Only, kein Code)
- #4 `approve_ki` IDOR (deferred-to-v2)
- #6 Single-Permission-Tier (größere Änderung)
- #20 Permission-Magic-String (Refactoring-Story 5-6)
- #55 `/objects`-Pagination (eigene Story)
- #57 `accessible_object_ids` per-Request-Cache (Performance-Story 5-4 teilweise adressiert)
- #115 Key-Ring-Rotation (deferred-to-v2)

### Lernnotizen aus Story 5-4

- `_load_accessible_object` wurde in 5-4 mit `request: Request` als erstem Argument ergänzt — alle 11 Callsites wurden aktualisiert. Nicht nochmals ändern.
- `accessible_object_ids_for_request(request, db, user)` ist der korrekte Call (nicht `accessible_object_ids(db, user)` — das war die alte Signatur, die 5-4 migriert hat).
- `_prepare_entries` in `admin.py:1088` ist eine pure Hilfsfunktion — Unit-testbar ohne HTTP-Setup.
- In 5-4 AC3 wurde `app/templating.py` um eine Jinja2-Erweiterung erweitert (Stale-Hint-Filter). Muster dort als Vorlage für `money_de`.

### Referenzen

- Deferred-Work-Details: `output/implementation-artifacts/deferred-work.md` (Zeilen 201–444 für Story-5-5-relevante Sektionen)
- Templating-Singleton: `app/templating.py:250` (`iban_format`-Filter als Vorlage für `money_de`)
- ExtractionResult + update_extraction_field: `app/services/document_field_edit.py`, `app/services/claude.py:211`
- `_extraction_block.html` als Parent-Template der Extraction-UI
- Sidebar-Active-Logik: `app/templates/base.html:83–140`
- OOB-Swap-Muster: `app/routers/registries.py:103–104` (Versicherer-Dropdown-OOB als Vorlage für Dienstleister)

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

_keine_

### Completion Notes List

- Alle 27 Deferred-Work-Items implementiert; 1105 Tests grün, 0 failures.
- AC1: Confidence-Clamp Python-seitig in `_prepare_entries` (`min(1.0, max(0.0, ...))`) + `confidence_pct`-Schlüssel im Result-Dict; Template nutzt `item.confidence_pct`.
- AC2: Sidebar doppelt-Highlight durch `and not path.startswith("/admin/review-queue")`-Guard am Admin-Link; Trailing-Slash-Guard (`+ '/'`) an beiden Workflow-Active-Detection-Stellen in `base.html`.
- AC3: `list_objects` (Voll-Page) erhält jetzt dieselben Query-Params `sort`/`order`/`filter_reserve` wie `list_objects_rows`; `hx-push-url="true"` und `hx-indicator="#objects-loading"` an alle 6 Sort-`<th>`s + Filter-`<select>` ergänzt; Spinner-Container in `objects_list.html` eingefügt.
- AC4: `money_de`-Jinja2-Filter registriert (`f"{float(v):,.0f}".replace(",", ".")`), eingesetzt in `_obj_table_body.html` für Saldo + Rücklage. Alle 6 Sort-`<th>`s haben `tabindex="0"`, `role="button"`, `aria-sort`, `onkeydown`.
- AC5: pflegegrad-Range-Cap via Jinja-Min/Max-Verschachtelung in Mobile-Cards; `min-w-[6rem]` auf Snap-Wrappern in `_obj_technik.html`.
- AC6: Tel-URI-href stripped Leerzeichen, Klammern, Bindestriche per Jinja-`replace`-Chain; `heating_hotline` erhält `max_len=30`.
- AC7: `_manual_fields`-Liste in `extracted`-JSONB gepflegt (kein Migration-Bedarf); "manuell"-Amber-Pill in `_extraction_field_view.html`; IBAN/BIC-Felder haben `autocapitalize="characters" autocorrect="off" autocomplete="off"`; `aria-label="… bearbeiten"` in `_obj_technik_field_view.html` und `_obj_zugangscode_view.html`.
- AC8: `_obj_versicherungen.html` zeigt Form-Div bei `form_error` sichtbar; OOB-Multi-Dropdown-Refresh für alle Policen eines Objekts via `other_policy_ids`-Hidden-Inputs + Loop über alle Policy-IDs im Handler.
- AC9: Globaler `data-confirm`-JS-Handler in `base.html` via Event-Delegation auf `submit`; `case_detail.html:142` und `:567` auf `data-confirm`-Attribut umgestellt; HTML-ID-Eindeutigkeit-Test (`test_object_detail_html_ids_unique`) in `test_steckbrief_routes_smoke.py` ergänzt.
- AC10: `<tfoot style="break-before: avoid; page-break-before: avoid;">` im ETV-PDF-Template; fragiler `<main>`-Split in `test_steckbrief_routes_smoke.py:244` durch `re.search(r'<main[^>]*>(.*?)</main>', body, re.DOTALL)` ersetzt.
- 3 Test-Assertions angepasst, die korrekte Neu-Implementierungen prüften (tel-URI strips, tfoot-Style-Attribut): `test_etv_signature_list.py:643`, `test_steckbrief_routes_smoke.py:817,851`.
- AC11: Alle 27 Items in `deferred-work.md` Triage-Tabelle mit `[done-5-5]` markiert.

### File List

- `app/templates/admin/review_queue.html`
- `app/templates/admin/_review_queue_rows.html`
- `app/templates/base.html`
- `app/templates/_obj_table_head.html`
- `app/templates/_obj_filter_bar.html`
- `app/templates/objects_list.html`
- `app/templates/_obj_table_body.html`
- `app/templates/_obj_technik.html`
- `app/templates/_obj_technik_field_view.html`
- `app/templates/_obj_zugangscode_view.html`
- `app/templates/_extraction_block.html`
- `app/templates/_extraction_field_view.html`
- `app/templates/_extraction_field_edit.html`
- `app/templates/_obj_versicherungen.html`
- `app/templates/_registries_dienstleister_form.html`
- `app/templates/case_detail.html`
- `app/templates/etv_signature_list_pdf.html`
- `app/routers/admin.py`
- `app/routers/objects.py`
- `app/routers/registries.py`
- `app/services/steckbrief.py`
- `app/services/document_field_edit.py`
- `app/templating.py`
- `tests/test_steckbrief_routes_smoke.py`
- `tests/test_etv_signature_list.py`
- `tests/test_ux_polish.py` (neu)
- `output/implementation-artifacts/deferred-work.md`

## Change Log

| Date       | Version | Author              | Changes                                     |
|------------|---------|---------------------|---------------------------------------------|
| 2026-05-06 | 1.0     | claude-sonnet-4-6   | Story implementiert, alle ACs abgeschlossen |
