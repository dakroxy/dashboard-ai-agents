# Story 3.4: Pflegegrad-Badge & Komposition-Popover

Status: ready-for-dev

## Abhängigkeiten

- **Story 3.3 MUSS implementiert sein**, bevor Story 3.4 begonnen wird. Story 3.3 erstellt `app/services/pflegegrad.py` (inkl. `PflegegradResult`, `get_or_update_pflegegrad_cache`) und integriert `pflegegrad_result` in den Template-Context von `object_detail()`.
- **Story 3.1 MUSS implementiert sein** — Story 3.1 erstellt `app/templates/_obj_table_body.html` mit dem Pflegegrad-Spalten-Fragment, das Story 3.4 zum Badge-Pill upgradet.

## Story

Als Mitarbeiter,
möchte ich den Pflegegrad-Score als Badge auf Liste und Detail sehen und bei Bedarf die Komposition nachvollziehen können,
damit ich verstehe, warum ein Objekt schlecht bewertet ist und welche Felder ich pflegen kann.

## Boundary-Klassifikation

`frontend-template` — Niedrigstes Risiko. Keine neue Route, keine neue Migration, kein neuer Service, keine DB-Schreiboperation.

Risiken:
1. **Jinja2-Crash wenn `pflegegrad_result` fehlt**: Guard mit `{% if pflegegrad_result %}` ist Pflicht — bis Story 3.3 deployed ist, kann der Cache-Key fehlen.
2. **Anchor-IDs stimmen nicht überein**: Deep-Links im Popover führen zu toten Ankern, wenn `id="field-..."` in den Templates fehlen. C1-Felder in `_obj_stammdaten.html` und C6-Felder in `_obj_finanzen.html` haben noch keine Field-IDs (C4-Technik-Felder haben sie bereits via `_obj_technik_field_view.html`).
3. **`pflegegrad_color()` vs. Inline-Logik**: Stories 3.1 und 3.2 setzen die Farb-Logik inline ohne Global. Kein Zwang zur Refaktorierung — beide Varianten erzeugen identisches HTML.

## Acceptance Criteria

**AC1 — Badge auf Detail-Seite mit korrekter Farbkodierung**

**Given** ein Objekt mit `pflegegrad_result.score = 85`
**When** ich `GET /objects/{id}` aufrufe
**Then** enthält das HTML einen Badge mit Text "Pflegegrad 85 %"
**And** der Badge trägt Grün-Klassen (Score ≥ 70)

**Given** Score = 55
**Then** der Badge trägt Gelb-Klassen (40–69)

**Given** Score = 25
**Then** der Badge trägt Rot-Klassen (< 40)

**Given** `pflegegrad_result` ist None (noch nicht berechnet)
**Then** rendert die Seite ohne Fehler (kein 500), Badge-Bereich bleibt leer

**AC2 — Popover mit Cluster-Komposition (Detail-Seite)**

**Given** `pflegegrad_result.per_cluster = {"C1": 1.0, "C4": 0.6, "C6": 0.8, "C8": 1.0}`
**When** das `<details>`-Popover expandiert wird
**Then** enthält der Popover-Inhalt pro Cluster: Name (z.B. "Technik"), Completeness-Prozent (z.B. "60 %") und Gewicht (z.B. "30 %")
**And** alle vier Cluster-Kürzel ("C1", "C4", "C6", "C8") sind im Popover-HTML vertreten

**AC3 — Popover mit weakest_fields und Deep-Links (Detail-Seite)**

**Given** `pflegegrad_result.weakest_fields = ["year_built", "has_police"]`
**When** das Popover zeigt die schwachen Felder
**Then** enthält das HTML `href="#field-year_built"` mit Label "Baujahr"
**And** enthält das HTML `href="#policen-section"` mit Label "Versicherungspolice"

**Given** `pflegegrad_result.weakest_fields = []`
**Then** zeigt das Popover "Alle Pflichtfelder gepflegt." ohne Link-Liste

**AC4 — Anker-IDs existieren in der Detail-Seite**

**Given** die Detail-Seite wird gerendert
**Then** enthält das HTML:
- `id="field-full_address"` (Stammdaten-Sektion)
- `id="field-impower_property_id"` (Stammdaten-Sektion)
- `id="eigentuemer-section"` (Eigentuemer-Sektion)
- `id="field-last_known_balance"` (Finanzen-Sektion)
- `id="field-reserve_current"` (Finanzen-Sektion)
- `id="field-sepa_mandate_refs"` (Finanzen-Sektion)
- `id="policen-section"` (Versicherungen-Sektion)
- `id="wartungen-section"` (Versicherungen-Sektion)

_(C4-Felder haben `id="field-{key}"` bereits seit Story 1.6 via `_obj_technik_field_view.html` — kein Change nötig.)_

**AC5 — Badge-Pill auf Listen-Seite (kein Popover)**

**Given** ein Objekt mit `pflegegrad_score_cached = 85`
**When** die Objekt-Liste gerendert wird
**Then** enthält die Pflegegrad-Zelle einen Pill-Badge mit Text "85 %" und Grün-Klassen
**And** kein `<details>`-Element in der Pflegegrad-Zelle (nur die Score-Ganzzahl, kein Popover)

## Tasks / Subtasks

- [ ] **Task 1**: `pflegegrad_color()` in `app/templating.py` hinzufügen (AC1, AC5)
  - [ ] 1.1: Funktion `pflegegrad_color(score: int | None) -> str` definieren — gibt kombinierte Tailwind-Badge-Klassen zurück (bg + text + border-color, ohne `border`-Keyword selbst)
  - [ ] 1.2: `templates.env.globals["pflegegrad_color"] = pflegegrad_color` nach der `provenance_pill`-Zeile registrieren

- [ ] **Task 2**: `WEAKEST_FIELD_LABELS` in `app/services/pflegegrad.py` hinzufügen (AC3)
  - [ ] 2.1: Dict `WEAKEST_FIELD_LABELS: dict[str, tuple[str, str]]` als Modul-Konstante definieren — Key → `(deutsches Label, Anker-ID)` für alle 12 Pflichtfeld-Keys
  - [ ] 2.2: In `app/routers/objects.py` importieren und `"weakest_field_labels": WEAKEST_FIELD_LABELS` ins Template-Context-Dict in `object_detail()` einfügen

- [ ] **Task 3**: Anker-IDs in `_obj_stammdaten.html` hinzufügen (AC4)
  - [ ] 3.1: Im `{% for item in stammdaten %}`-Loop den äußeren `<div>` zu `<div id="field-{{ item.field }}">` ändern
  - [ ] 3.2: Die `<section>` für den Eigentuemer-Block (zweite section in dieser Datei) auf `<section id="eigentuemer-section" ...>` ändern

- [ ] **Task 4**: Anker-IDs in `_obj_finanzen.html` hinzufügen (AC4)
  - [ ] 4.1: Im `fin_mirror_fields`-Loop jeden Field-Container zu `<div id="field-{{ field.key }}">` verallgemeinern (erfasst `reserve_current`, `reserve_target`, `wirtschaftsplan_status` ohne Sonderbehandlung)
  - [ ] 4.2: Dem Live-Saldo-Container `id="field-last_known_balance"` hinzufügen (eigener Block, nicht im Mirror-Fields-Loop)
  - [ ] 4.3: Dem SEPA-Mandate-Container `id="field-sepa_mandate_refs"` hinzufügen

- [ ] **Task 5**: Anker-IDs in `_obj_versicherungen.html` hinzufügen (AC4)
  - [ ] 5.1: Unbedingten Wrapper `<div id="policen-section">` um die gesamte conditional Policen-Logik (`{% if policen %}...{% else %}...{% endif %}`, aktuell ab Z.105) ziehen — sodass der Anker auch dann existiert, wenn `policen=[]` (das ist genau der Fall, in dem `weakest_fields` `"has_police"` enthält)
  - [ ] 5.2: Direkt nach dem `policen-section`-Wrapper einen leeren Anker-`<div id="wartungen-section" class="sr-only" aria-hidden="true"></div>` einfügen — Wartungspflichten leben innerhalb der Policen-`<details>`-Blöcke (`_obj_versicherungen_row.html:57`), nicht in einer eigenen Sub-Sektion; der Anker dient nur als Sprungziel und der User sieht die Policen-Liste mit aufklappbaren Wartungen
  - [ ] 5.3: **NICHT** das bestehende `id="versicherungen"` auf der `<section>` ändern — wird von HTMX-Targets (`hx-target="[data-section='versicherungen']"`) und ggf. anderen Deep-Links referenziert

- [ ] **Task 6**: Badge + Popover in `object_detail.html` (AC1, AC2, AC3)
  - [ ] 6.1: Rechten Bereich des Header-`<div class="flex items-center justify-between mb-6">` zu einem `flex gap-4`-Container umbauen
  - [ ] 6.2: `{% if pflegegrad_result %}`-Guard + `<details class="relative">`-Struktur einbauen
  - [ ] 6.3: `<summary>` = Pill-Badge mit `pflegegrad_color(pflegegrad_result.score)` und Text `"Pflegegrad {{ pflegegrad_result.score }} %"`
  - [ ] 6.4: Popover-Inhalt: Cluster-Kompositions-Tabelle mit 4 Zeilen (C1/C4/C6/C8) + weakest_fields-Liste mit Deep-Links über `weakest_field_labels`
  - [ ] 6.5: `onclick` auf Deep-Links: `this.closest('details').removeAttribute('open')` — schließt Popover nach Scroll-Klick
  - [ ] 6.6: Bestehender `<a href="/objects">← Zurück`-Link bleibt rechts neben dem Badge

- [ ] **Task 7**: Listen-Badge in `_obj_table_body.html` upgraden (AC5)
  - [ ] 7.1: Bestehenden Text-Span (`text-green-600`/`text-yellow-600`/`text-red-600`) durch Pill-Badge mit `pflegegrad_color()` ersetzen
  - [ ] 7.2: Sicherstellen: kein `<details>`-Element in der Pflegegrad-Zelle

- [ ] **Task 8**: Tests `tests/test_pflegegrad_badge_smoke.py` (AC1–AC5)
  - [ ] 8.1: `test_detail_badge_green` — AC1 grün (score=85)
  - [ ] 8.2: `test_detail_badge_yellow` — AC1 gelb (score=55)
  - [ ] 8.3: `test_detail_badge_red` — AC1 rot (score=25)
  - [ ] 8.4: `test_detail_no_crash_when_pflegegrad_result_none` — AC1 Edge Case
  - [ ] 8.5: `test_detail_popover_cluster_names` — AC2
  - [ ] 8.6: `test_detail_popover_weakest_field_links` — AC3
  - [ ] 8.7: `test_detail_popover_empty_weakest_fields` — AC3 Edge Case (leere Liste)
  - [ ] 8.8: `test_detail_anchor_ids_present` — AC4 (alle 8 IDs im HTML)
  - [ ] 8.9: `test_pflegegrad_color_unit` — pflegegrad_color(85)→Grün, pflegegrad_color(55)→Gelb, pflegegrad_color(25)→Rot, pflegegrad_color(None)→Grau

## Dev Notes

### Task 1: `pflegegrad_color()` in `app/templating.py`

Neue Funktion **vor** der `templates = Jinja2Templates(...)`-Zeile (Zeile 113):

```python
def pflegegrad_color(score: int | None) -> str:
    """Tailwind-Badge-Klassen fuer Pflegegrad-Score (bg + text + border-color ohne border-Keyword)."""
    if score is None:
        return "bg-slate-100 text-slate-500 border-slate-200"
    if score >= 70:
        return "bg-green-100 text-green-800 border-green-200"
    if score >= 40:
        return "bg-yellow-100 text-yellow-800 border-yellow-200"
    return "bg-red-100 text-red-800 border-red-200"
```

Global-Registrierung nach `templates.env.globals["provenance_pill"] = provenance_pill` (Zeile 116):
```python
templates.env.globals["pflegegrad_color"] = pflegegrad_color
```

**Wichtig**: Der Rückgabe-String enthält `border-slate-200` / `border-green-200` etc. — das ist der Border-Color-Wert. Das `border`-Keyword (ohne Suffix) muss im Template selbst stehen: `class="border {{ pflegegrad_color(...) }}"`.

### Task 2: `WEAKEST_FIELD_LABELS` in `app/services/pflegegrad.py`

Story 3.3 erstellt diese Datei. `WEAKEST_FIELD_LABELS` als Modul-Konstante hinzufügen, nach `CACHE_TTL`, vor den Service-Funktionen:

```python
# (deutsches Label, Anker-ID) pro weakest-field-Key.
# Anker-IDs korrespondieren mit id="..." in den Templates (AC4).
WEAKEST_FIELD_LABELS: dict[str, tuple[str, str]] = {
    # C1 — Stammdaten (ids via Task 3 in Story 3.4 hinzugefuegt)
    "full_address": ("Adresse", "#field-full_address"),
    "impower_property_id": ("Impower-Eigenschaft", "#field-impower_property_id"),
    "has_eigentuemer": ("Eigentuemer", "#eigentuemer-section"),
    # C4 — Technik (ids bereits vorhanden via _obj_technik_field_view.html)
    "shutoff_water_location": ("Absperrung Wasser", "#field-shutoff_water_location"),
    "shutoff_electricity_location": ("Absperrung Strom", "#field-shutoff_electricity_location"),
    "heating_type": ("Heizungstyp", "#field-heating_type"),
    "year_built": ("Baujahr", "#field-year_built"),
    # C6 — Finanzen (ids via Task 4 in Story 3.4 hinzugefuegt)
    "last_known_balance": ("Kontosaldo", "#field-last_known_balance"),
    "reserve_current": ("Ruecklage aktuell", "#field-reserve_current"),
    "sepa_mandate_refs": ("SEPA-Mandate", "#field-sepa_mandate_refs"),
    # C8 — Versicherungen (ids via Task 5 in Story 3.4 hinzugefuegt)
    "has_police": ("Versicherungspolice", "#policen-section"),
    "has_wartungspflicht": ("Wartungspflicht", "#wartungen-section"),
}
```

In `app/routers/objects.py` (nach den bestehenden Imports aus `pflegegrad`):
```python
from app.services.pflegegrad import WEAKEST_FIELD_LABELS, get_or_update_pflegegrad_cache
```

Im `TemplateResponse`-Dict in `object_detail()` (neben `"pflegegrad_result"`):
```python
"weakest_field_labels": WEAKEST_FIELD_LABELS,
```

### Task 3: Anker-IDs in `_obj_stammdaten.html`

**Änderung 3.1** — Stammdaten-Loop (`{% for item in stammdaten %}`):

Bestehend (`app/templates/_obj_stammdaten.html`): Die inneren `<div>`-Container im Grid haben keine ID. Statt:
```html
<div>
    <div class="text-xs uppercase ...">{{ item.field }}</div>
    ...
</div>
```
zu:
```html
<div id="field-{{ item.field }}">
    <div class="text-xs uppercase ...">{{ item.field }}</div>
    ...
</div>
```

**Änderung 3.2** — Eigentuemer-Section:
Die zweite `<section>` (ab ca. Zeile 37 in `_obj_stammdaten.html`) enthält den Eigentuemer-Block. `id="eigentuemer-section"` hinzufügen:
```html
<section id="eigentuemer-section" class="rounded-lg bg-white border border-slate-200 p-6">
```

### Task 4: Anker-IDs in `_obj_finanzen.html`

**Lies die Datei vollständig** bevor du editierst — die Struktur ist komplex (Mirror-Felder-Loop + Live-Saldo-Block + SEPA-Block).

**Änderung 4.1** — Mirror-Felder-Loop: Alle Mirror-Feld-Container mit `id="field-{{ field.key }}"` versehen. Das gilt für `reserve_current`, `reserve_target`, `wirtschaftsplan_status` automatisch. Muster analog `_obj_technik_field_view.html`.

**Änderung 4.2** — Live-Saldo-Block (`last_known_balance`): Dieser Block wird separat vom Mirror-Loop gerendert. Den äußeren Container auf `id="field-last_known_balance"` setzen.

**Änderung 4.3** — SEPA-Block: Der Block, der `sepa_mandate_refs` rendert, bekommt `id="field-sepa_mandate_refs"`. Achtung: `data-field="sepa_mandate_refs"` existiert bereits an einem inneren Element — das ist ein separates Attribut für andere Zwecke, das bleibt bestehen.

### Task 5: Anker-IDs in `_obj_versicherungen.html`

**Lies die Datei vollständig** bevor du editierst.

**Strukturelles Problem:** Wartungspflichten sind keine separate Untersektion — sie leben pro Police als `<details>`-Block innerhalb von `_obj_versicherungen_row.html:57`. Die Policen-Liste selbst ist nur conditional gerendert (`{% if policen %}<div class="space-y-3">...{% endif %}`, aktuell ab Z.105); ohne Policen existiert der Container nicht. Beide Anker müssen daher als unbedingte Wrapper bzw. leere Anker-Marker eingefügt werden.

**Änderung 5.1** — `id="policen-section"`-Wrapper um die conditional Policen-Logik (ersetzt aktuell Z.105–123):

```html
<div id="policen-section">
    {% if policen %}
    <div class="space-y-3">
        {% for policy in policen %}
        {% include "_obj_versicherungen_row.html" %}
        {% endfor %}
    </div>
    {% else %}
    <p class="text-sm text-slate-400 italic">
        Keine Policen angelegt.
        {% if has_permission(user, "objects:edit") %}
        Erste Police anlegen →
        <button type="button"
                onclick="document.getElementById('neue-police-form').classList.remove('hidden')"
                class="underline text-indigo-600">
            Neue Police
        </button>
        {% endif %}
    </p>
    {% endif %}
</div>
```

So existiert der Anker auch wenn `policen=[]` — und das ist genau der Fall, in dem `weakest_fields` `"has_police"` enthält.

**Änderung 5.2** — `id="wartungen-section"`-Anker direkt nach dem Policen-Wrapper:

```html
<div id="wartungen-section" class="sr-only" aria-hidden="true"></div>
```

Leerer, screen-reader-versteckter Anker. Wartungspflichten werden in den `<details>`-Blöcken pro Police angezeigt (eingeklappt by default); der Deep-Link springt zum Anker direkt nach dem Policen-Wrapper, der User sieht die Policen-Liste mit aufklappbaren Wartungen. Wenn keine Policen existieren, springt der Link auf denselben Bereich wie `#policen-section` (Empty-State-Hinweis "Keine Policen angelegt"). Für die MVP-UX akzeptabel — eine eigenständige Wartungspflichten-Übersicht ist Backlog.

**Änderung 5.3** — KEINE Änderung an `<section id="versicherungen">` (Z.6). Diese ID ist HTMX-Target (`hx-target="[data-section='versicherungen']"`) und ggf. Sprungziel anderer Stellen.

### Task 6: Badge + Popover in `object_detail.html`

**Ausgangszustand** (`app/templates/object_detail.html:4–18`):
```html
<div class="flex items-center justify-between mb-6">
    <div>
        <h1 class="text-2xl font-semibold">{{ obj.short_code }} &middot; {{ obj.name }}</h1>
        <p class="text-sm text-slate-500 mt-1">Objekt-Detail, Cluster 1 (Stammdaten).</p>
    </div>
    <a href="/objects" class="text-sm text-slate-500 hover:text-slate-900">&larr; Zurueck zur Liste</a>
</div>
```

**Neue Version** — den `<a>`-Link in einen `flex items-center gap-4`-Container verschieben und den Badge davor platzieren:

```html
<div class="flex items-center justify-between mb-6">
    <div>
        <h1 class="text-2xl font-semibold">{{ obj.short_code }} &middot; {{ obj.name }}</h1>
        <p class="text-sm text-slate-500 mt-1">Objekt-Detail, Cluster 1 (Stammdaten).</p>
    </div>
    <div class="flex items-center gap-4">
        {% if pflegegrad_result %}
        <details class="relative">
            <summary class="cursor-pointer list-none inline-flex items-center gap-1
                            text-sm font-medium px-3 py-1 rounded-full border
                            {{ pflegegrad_color(pflegegrad_result.score) }}">
                Pflegegrad {{ pflegegrad_result.score }}&nbsp;%
                <span class="text-xs opacity-60">&#9660;</span>
            </summary>
            <div class="absolute right-0 mt-2 w-80 bg-white border border-slate-200
                        rounded-lg shadow-lg p-4 z-10 text-sm">
                <p class="font-semibold text-slate-800 mb-2">Score-Komposition</p>
                <table class="w-full mb-3 text-xs">
                    <thead class="text-slate-500 border-b border-slate-100">
                        <tr>
                            <th class="text-left pb-1">Cluster</th>
                            <th class="text-right pb-1">Vollstaendigkeit</th>
                            <th class="text-right pb-1">Gewicht</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% set cluster_meta = [
                            ("C1", "Stammdaten", 20),
                            ("C4", "Technik", 30),
                            ("C6", "Finanzen", 20),
                            ("C8", "Versicherungen", 30),
                        ] %}
                        {% for ckey, cname, cweight in cluster_meta %}
                        <tr class="border-t border-slate-50">
                            <td class="py-1 text-slate-700">{{ cname }}</td>
                            <td class="py-1 text-right tabular-nums
                                {% if pflegegrad_result.per_cluster[ckey] >= 0.7 %}text-green-700
                                {% elif pflegegrad_result.per_cluster[ckey] >= 0.4 %}text-yellow-700
                                {% else %}text-red-700{% endif %}">
                                {{ (pflegegrad_result.per_cluster[ckey] * 100) | round | int }}&nbsp;%
                            </td>
                            <td class="py-1 text-right text-slate-500">{{ cweight }}&nbsp;%</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% if pflegegrad_result.weakest_fields %}
                <p class="font-semibold text-slate-800 mb-1">Fehlende Felder</p>
                <ul class="space-y-0.5">
                    {% for wf in pflegegrad_result.weakest_fields %}
                    {% set label_anchor = weakest_field_labels.get(wf) %}
                    {% if label_anchor %}
                    <li>
                        <a href="{{ label_anchor[1] }}"
                           onclick="this.closest('details').removeAttribute('open')"
                           class="text-sky-600 hover:text-sky-900 hover:underline">
                            {{ label_anchor[0] }}
                        </a>
                    </li>
                    {% endif %}
                    {% endfor %}
                </ul>
                {% else %}
                <p class="text-slate-500 text-xs">Alle Pflichtfelder gepflegt.</p>
                {% endif %}
            </div>
        </details>
        {% endif %}
        <a href="/objects" class="text-sm text-slate-500 hover:text-slate-900">&larr; Zurueck zur Liste</a>
    </div>
</div>
```

**Wichtige Jinja2-Details:**
- `list-none` auf `<summary>` entfernt das native Browser-Dreieck (Disclosure-Marker)
- `&#9660;` = ▼ als manuelles Collapse-Indikator
- `class="relative"` auf `<details>` ist Voraussetzung für `absolute right-0` auf dem Popover-Div
- `z-10` verhindert, dass der Popover von anderen Sektionen überdeckt wird
- `onclick="this.closest('details').removeAttribute('open')"` schließt den Popover nach dem Deep-Link-Klick

### Task 7: Listen-Badge in `_obj_table_body.html`

Story 3.1 definiert die Pflegegrad-Zelle. Wenn Story 3.1 implementiert ist, ersetzt Story 3.4 den Text-Span:

Bestehend (Story 3.1 Pattern):
```html
<span class="{% if row.pflegegrad >= 70 %}text-green-600{% elif row.pflegegrad >= 40 %}text-yellow-600{% else %}text-red-600{% endif %} font-medium">
    {{ row.pflegegrad }} %
</span>
```

Durch Pill-Badge:
```html
<span class="inline-flex items-center px-2 py-0.5 rounded-full border text-xs font-medium
             {{ pflegegrad_color(row.pflegegrad) }}">
    {{ row.pflegegrad }}&nbsp;%
</span>
```

Der `{% else %}<span class="text-slate-400">&mdash;</span>{% endif %}` für `None` bleibt unverändert.

**Kein `<details>`-Element in der Pflegegrad-Zelle** — die Liste hat nur den gecachten Integer, nicht `PflegegradResult`. Der Badge auf der Liste ist rein visuell; für die Komposition klickt der User auf den Objekt-Namen (Detailseite).

### Task 8: Tests `tests/test_pflegegrad_badge_smoke.py`

**Fixtures aus `tests/conftest.py`** (bereits vorhanden, kein lokales Anlegen nötig):
- `db` (Datenbankverbindung)
- `test_object` (minimales Object `TST1`)
- `steckbrief_admin_client` (TestClient mit allen `objects:*`-Permissions)

**Mock-Strategie**: Story 3.3 integriert `get_or_update_pflegegrad_cache` in `app.routers.objects`. Dieser Pfad wird per `unittest.mock.patch` überschrieben:

```python
from unittest.mock import patch
from app.services.pflegegrad import PflegegradResult, WEAKEST_FIELD_LABELS

RESULT_GREEN = PflegegradResult(
    score=85,
    per_cluster={"C1": 1.0, "C4": 1.0, "C6": 0.75, "C8": 1.0},
    weakest_fields=["reserve_current"],
)
RESULT_YELLOW = PflegegradResult(
    score=55,
    per_cluster={"C1": 1.0, "C4": 0.5, "C6": 0.5, "C8": 0.5},
    weakest_fields=["shutoff_water_location", "has_police"],
)
RESULT_RED = PflegegradResult(
    score=25,
    per_cluster={"C1": 0.3, "C4": 0.2, "C6": 0.3, "C8": 0.2},
    weakest_fields=["year_built", "has_police", "has_wartungspflicht"],
)


def _patch_pflegegrad(result):
    return patch(
        "app.routers.objects.get_or_update_pflegegrad_cache",
        return_value=(result, False),
    )


def test_detail_badge_green(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_GREEN):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    assert "Pflegegrad 85" in resp.text
    assert "bg-green-100" in resp.text


def test_detail_badge_yellow(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_YELLOW):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    assert "Pflegegrad 55" in resp.text
    assert "bg-yellow-100" in resp.text


def test_detail_badge_red(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_RED):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    assert "Pflegegrad 25" in resp.text
    assert "bg-red-100" in resp.text


def test_detail_no_crash_when_pflegegrad_result_none(steckbrief_admin_client, test_object):
    # Edge Case: Service liefert (None, False) ins Template — der
    # {% if pflegegrad_result %}-Guard in object_detail.html muss greifen,
    # Page rendert ohne Badge, kein 500.
    with patch(
        "app.routers.objects.get_or_update_pflegegrad_cache",
        return_value=(None, False),
    ):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    # Kein "Pflegegrad <Zahl>"-Badge im HTML (Guard hat gegriffen)
    import re
    assert not re.search(r"Pflegegrad\s+\d+", resp.text)


def test_detail_popover_cluster_names(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_YELLOW):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    for cluster_name in ["Stammdaten", "Technik", "Finanzen", "Versicherungen"]:
        assert cluster_name in resp.text


def test_detail_popover_weakest_field_links(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_YELLOW):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert 'href="#field-shutoff_water_location"' in resp.text
    assert 'href="#policen-section"' in resp.text


def test_detail_popover_empty_weakest_fields(steckbrief_admin_client, test_object):
    result_full = PflegegradResult(
        score=100,
        per_cluster={"C1": 1.0, "C4": 1.0, "C6": 1.0, "C8": 1.0},
        weakest_fields=[],
    )
    with _patch_pflegegrad(result_full):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert "Alle Pflichtfelder gepflegt" in resp.text


def test_detail_anchor_ids_present(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_GREEN):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    for anchor_id in [
        'id="field-full_address"',
        'id="field-impower_property_id"',
        'id="eigentuemer-section"',
        'id="field-last_known_balance"',
        'id="field-reserve_current"',
        'id="field-sepa_mandate_refs"',
        'id="policen-section"',
        'id="wartungen-section"',
    ]:
        assert anchor_id in resp.text, f"Missing anchor: {anchor_id}"


def test_pflegegrad_color_unit():
    from app.templating import pflegegrad_color
    assert "green" in pflegegrad_color(85)
    assert "green" in pflegegrad_color(70)
    assert "yellow" in pflegegrad_color(69)
    assert "yellow" in pflegegrad_color(40)
    assert "red" in pflegegrad_color(39)
    assert "red" in pflegegrad_color(0)
    assert "slate" in pflegegrad_color(None)
```

**Hinweis zu Test 8.4** (`test_detail_no_crash_when_pflegegrad_result_none`): Der Guard `{% if pflegegrad_result %}` in Task 6 verhindert den 500. Story 3.3 selbst wirft keine Exception ab — `pflegegrad_score()` liefert immer ein `PflegegradResult`. Der Edge Case "pflegegrad_result=None" ist nur erreichbar, wenn der Service-Aufruf im Router gepatcht wird (siehe Test-Body mit `return_value=(None, False)`) oder wenn Story 3.3 später um defensives `None`-Handling erweitert wird. Der Test sichert beide Fälle ab, indem er das Service-Return mockt.

### Kein Konflikt mit `test_write_gate_coverage.py`

Story 3.4 schreibt **keine** direkten ORM-Attribute auf `Object`. Das Write-Gate bleibt unberührt.

### `list-none` auf `<summary>` — Browserkompabilität

`list-none` in Tailwind entspricht `list-style: none`. Ältere Firefox-Versionen zeigen den Disclosure-Triangle trotzdem an; robustere Lösung:
```html
<summary class="... list-none [&::-webkit-details-marker]:hidden">
```
Tailwind-CDN (v3) unterstützt `[&::-webkit-details-marker]:hidden` via JIT — verwenden wenn Browsersupport kritisch ist.

### Jinja2-Pipe `| round | int`

`pflegegrad_result.per_cluster["C1"]` ist ein `float` (0.0–1.0). Um als Ganzzahl-Prozent zu rendern:
```
{{ (pflegegrad_result.per_cluster[ckey] * 100) | round | int }}
```
`round` gibt float zurück, `int` schneidet Dezimalstellen ab → "100", "60" etc.

## Test-Checkliste (Epic-2-Retro P1)

- [ ] Permission-Matrix: nicht anwendbar (keine neue Route — bestehende `objects:view`-Berechtigung unverändert)
- [ ] IDOR: nicht anwendbar (kein FK aus Form-Body)
- [ ] Numerische Boundaries: `pflegegrad_color(0)` → Rot, `pflegegrad_color(100)` → Grün, `pflegegrad_color(None)` → Grau, `pflegegrad_color(70)` → Grün (Grenze inklusive), `pflegegrad_color(40)` → Gelb (Grenze inklusive) — in `test_pflegegrad_color_unit` abgedeckt
- [ ] NULLs korrekt: `pflegegrad_result=None` → Badge-Bereich leer (Test 8.4)
- [ ] Tel-Link: nicht anwendbar
- [ ] Date-Bounds: nicht anwendbar
- [ ] HTMX-422-Render: nicht anwendbar (kein Form-Submit in dieser Story)
- [ ] Anchor-IDs: alle 8 Anker via Test 8.8 (`test_detail_anchor_ids_present`) verifiziert

## Neue Dateien

- `tests/test_pflegegrad_badge_smoke.py`

## Geänderte Dateien

- `app/templating.py` — `pflegegrad_color()` hinzufügen + Global registrieren
- `app/services/pflegegrad.py` — `WEAKEST_FIELD_LABELS` dict hinzufügen (**Story 3.3 erstellt diese Datei**)
- `app/routers/objects.py` — Import `WEAKEST_FIELD_LABELS` + `"weakest_field_labels"` im Template-Context von `object_detail()`
- `app/templates/object_detail.html` — Badge + Popover im Header-Bereich
- `app/templates/_obj_stammdaten.html` — `id="field-{{ item.field }}"` auf Loop-Items, `id="eigentuemer-section"` auf Eigentuemer-Section
- `app/templates/_obj_finanzen.html` — `id="field-{{ field.key }}"` auf Mirror-Felder, `id="field-last_known_balance"` auf Live-Saldo-Block, `id="field-sepa_mandate_refs"` auf SEPA-Block
- `app/templates/_obj_versicherungen.html` — `id="policen-section"` + `id="wartungen-section"`
- `app/templates/_obj_table_body.html` — Pill-Badge statt reinen Text-Span (**Story 3.1 erstellt diese Datei**)

## References

- Story 3.3 (Abhängigkeit): `output/implementation-artifacts/3-3-pflegegrad-score-service.md`
  - weakest_fields-Format: §Dev Notes / weakest_fields — Format
  - Router-Integration (Zeile 228ff.): §Dev Notes / Router-Integration (objects.py)
  - PflegegradResult-Dataclass: §Tasks / Task 1.1
- Story 3.1 — Pflegegrad-Zelle und Farb-Schwellen: `output/implementation-artifacts/3-1-objekt-liste-mit-sortierung-filter.md` §Pflegegrad-Mini-Badge ist Vorab-UX vor Story 3.3/3.4
- Story 3.2 — Pflegegrad in Mobile-Cards (Schwellen 70/40): `output/implementation-artifacts/3-2-mobile-card-layout.md` §Pflegegrad-Farben
- Bestehende `<details>/<summary>`-Popover-Pattern: `app/templates/_obj_versicherungen.html:130–199`
- Bestehende Technik-Feld-ID (`id="field-{key}"`): `app/templates/_obj_technik_field_view.html:5`
- `templating.py` — bestehende Globals: `app/templating.py:113–117`
- object_detail.html Header (Ausgangspunkt Task 6): `app/templates/object_detail.html:4–18`
- Architecture ID3 — Pflegegrad-Score-Komposition: `output/planning-artifacts/architecture.md:411–421`
- Architecture ID4 — HTMX-Fragment-Strategie: `output/planning-artifacts/architecture.md:423–434`
- STAMMDATEN_FIELDS / FINANZEN_FIELDS in Router: `app/routers/objects.py:95–110`
- `steckbrief_admin_client` + `test_object` Fixtures: `tests/conftest.py:186–225`
- Epic-2-Retro Test-Checkliste P1: `output/implementation-artifacts/epic-2-retro-2026-04-28.md`
- Date-Bounds Memory: `memory/feedback_date_tests_pick_mid_month.md` (hier nicht direkt relevant — keine Datums-Logik)

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

### Completion Notes List

### File List
