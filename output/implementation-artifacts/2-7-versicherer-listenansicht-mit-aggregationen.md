# Story 2.7: Versicherer-Listenansicht mit Aggregationen

Status: ready-for-dev

## Story

Als Mitarbeiter mit `registries:view`,
ich möchte eine Liste aller Versicherer mit aggregierten Kennzahlen sehen,
damit ich Portfolio-Entscheidungen (z. B. Konsolidierung eines Anbieters) datengetrieben vorbereiten kann.

## Acceptance Criteria

1. **AC1 — Aggregierter Table:** `GET /registries/versicherer` liefert HTTP 200 mit einer Tabelle, die pro Versicherer eine Zeile mit den Spalten zeigt: Name, Policen-Anzahl, Gesamtprämie p.a. (Summe `InsurancePolicy.praemie` aller Policen), Schadensquote (Gesamtschaden / Gesamtprämie als Prozentwert, 0% wenn keine Prämie), verbundene Objekte (Anzahl distinct `object_id`).
2. **AC2 — HTMX-Sortierung:** Klick auf einen Spalten-Header sendet `GET /registries/versicherer/rows?sort={col}&order={asc|desc}` und tauscht `<tbody id="versicherer-rows">` per HTMX `outerHTML`-Swap aus (unter 500 ms). Sortierbar: Name (asc), Policen-Anzahl (desc), Gesamtprämie (desc), Schadensquote (desc), Objekte (desc).
3. **AC3 — Ungenutzte Versicherer:** Ein Versicherer ohne Policen zeigt "0" für alle numerischen Spalten und einen dezenten "ungenutzt"-Badge im Namensfeld.
4. **AC4 — Permission-Gate:** Ohne `registries:view` → HTTP 403. Nicht eingeloggte User → 302 nach `/auth/google/login`.
5. **AC5 — Sidebar-Link:** In `base.html` erscheint ein "Versicherer"-Eintrag in der Sidebar (nach dem Due-Radar-Link, Story 2.5), nur sichtbar für User mit `registries:view`. Aktiv-State wenn `path.startswith("/registries")`.
6. **AC6 — Performance:** Alle DB-Queries zusammen unter 2 s bei 50 Objekten / ~150 Policen / typischen Schadensfällen.
7. **AC7 — Unit-Tests:** `tests/test_registries_unit.py` — mindestens 8 Tests: leere Liste, Aggregation korrekt, kein Double-Count Prämie bei mehreren Schadensfällen, Schadensquote null-safe (praemie=NULL), Schadensquote=0 bei praemie=0 trotz schaden>0, Versicherer ohne Policen, Sort nach Name asc (Default), Sort nach policen_anzahl desc.
8. **AC8 — Smoke-Tests:** `GET /registries/versicherer` unauthenticated → 302, ohne `registries:view` → 403, mit `registries:view` → 200. Fragment-Endpoint `GET /registries/versicherer/rows` analog — inkl. Sort-Roundtrip (`?sort=policen_anzahl&order=desc`). Sidebar-Gate positive + negative geprüft.

## Tasks / Subtasks

- [ ] Task 1: Service `app/services/registries.py` erstellen (AC: 1, 3, 6, 7)
  - [ ] `VersichererAggRow` Dataclass mit Feldern: `versicherer_id: uuid.UUID`, `name: str`, `policen_anzahl: int`, `gesamtpraemie: Decimal`, `gesamtschaden: Decimal`, `objekte_anzahl: int`, `schadensquote: float`
  - [ ] `list_versicherer_aggregated(db, *, sort: str = "name", order: str = "asc") -> list[VersichererAggRow]` — drei DB-Queries, in Python mergen (Muster analog Due-Radar):
    - Query 1: Alle `Versicherer` laden
    - Query 2: `select(InsurancePolicy.versicherer_id, func.count(InsurancePolicy.id), func.coalesce(func.sum(InsurancePolicy.praemie), 0), func.count(distinct(InsurancePolicy.object_id))) WHERE versicherer_id IS NOT NULL GROUP BY versicherer_id`
    - Query 3: `select(InsurancePolicy.versicherer_id, func.coalesce(func.sum(Schadensfall.amount), 0)) JOIN schadensfaelle ON ... WHERE versicherer_id IS NOT NULL GROUP BY versicherer_id`
  - [ ] In Python: `dict`-Lookup auf versicherer_id für Query 2 + 3; Versicherer ohne Eintrag in Query 2 → `policen_anzahl=0`, `gesamtpraemie=Decimal("0")`, `objekte_anzahl=0`
  - [ ] Schadensquote: `float(gesamtschaden / gesamtpraemie)` wenn `gesamtpraemie > 0`, sonst `0.0`. Kein ZeroDivisionError möglich.
  - [ ] Sort-Allowlist: `_SORT_ALLOWED = {"name", "policen_anzahl", "gesamtpraemie", "schadensquote", "objekte_anzahl"}` — bei unbekanntem Sort-Key Fallback auf `"name"` (kein 422, kein SQL-Injection-Risiko)
  - [ ] Python-Sort: `result.sort(key=lambda r: getattr(r, safe_sort), reverse=(order == "desc"))`

- [ ] Task 2: Router `app/routers/registries.py` erstellen (AC: 1, 2, 4, 8)
  - [ ] `APIRouter(prefix="/registries", tags=["registries"])`
  - [ ] `GET "/versicherer"` Handler: `require_permission("registries:view")`, `list_versicherer_aggregated(db)` → `templates.TemplateResponse(request, "registries_versicherer_list.html", {"rows": rows, "sort": "name", "order": "asc"})` 
  - [ ] `GET "/versicherer/rows"` Handler: gleiche Permission, Query-Params `sort: str = "name"`, `order: str = "asc"` → `list_versicherer_aggregated(db, sort=sort, order=order)` → `templates.TemplateResponse(request, "_versicherer_rows.html", {"rows": rows})`

- [ ] Task 3: Templates erstellen (AC: 1, 2, 3, 5)
  - [ ] `app/templates/registries_versicherer_list.html`:
    - `{% extends "base.html" %}` + `{% block content %}`
    - Seitenheader: "Versicherer" mit Untertitel "Portfolio-Übersicht aller Versicherer mit aggregierten Kennzahlen."
    - `<div class="rounded-lg bg-white border border-slate-200 overflow-hidden">`
    - `<table class="w-full text-sm">`
    - `<thead>`: 5 Spaltenköpfe mit HTMX-Sort-Links für numerische Spalten (Policen, Prämie, Schadensquote, Objekte)
    - `{% include "_versicherer_rows.html" %}` — **kein** `<tbody>`-Wrapper im Parent; das Fragment liefert das `<tbody id="versicherer-rows">` selbst (sonst zwei `<tbody>` mit identischer ID → HTMX-Swap-Bug, siehe Dev-Notes "HTMX-Swap + Fragment-Struktur")
    - Leerer State: "Keine Versicherer vorhanden."-Fallback-Row ist im Fragment (`_versicherer_rows.html`) implementiert, nicht im Parent.
  - [ ] `app/templates/_versicherer_rows.html`:
    - Kein `{% extends %}` (Fragment)
    - `{% for row in rows %}` Zeilen:
      - Name-Zelle: `{{ row.name }}` + wenn `row.policen_anzahl == 0`: `<span class="ml-2 text-xs text-slate-400 italic">ungenutzt</span>`
      - Policen-Anzahl: `{{ row.policen_anzahl }}` (rechts-ausgerichtet, text-slate-400 wenn 0)
      - Gesamtprämie: `{{ "%.0f"|format(row.gesamtpraemie|float) }} €` (rechts, text-slate-400 wenn 0)
      - Schadensquote: `{{ "%.1f"|format(row.schadensquote * 100) }} %` (rechts, text-slate-400 wenn 0)
      - Objekte: `{{ row.objekte_anzahl }}` (rechts, text-slate-400 wenn 0)
    - `{% if not rows %}`: Leere-State-Zeile "Keine Versicherer vorhanden." (colspan=5)
  - [ ] HTMX-Sort-Links in `<thead>` — Beispiel-Muster für Spalte "Policen":
    ```html
    <th class="text-right px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
        hx-get="/registries/versicherer/rows?sort=policen_anzahl&order=desc"
        hx-target="#versicherer-rows"
        hx-swap="outerHTML"
        title="Nach Policen-Anzahl sortieren">
        Policen
    </th>
    ```
    Nicht-numerische Spalte "Name": ohne HTMX-Attribute (statisch, oder `order=asc`)
  - [ ] In `app/templates/base.html` Sidebar-Eintrag nach dem Due-Radar-Block (bzw. nach dem Objekte-Block falls Due-Radar noch nicht implementiert):
    ```html
    {# Versicherer #}
    {% if has_permission(user, "registries:view") %}
    {% set active = path.startswith("/registries") %}
    <a href="/registries/versicherer"
       class="flex items-center gap-3 px-6 py-2.5 text-sm border-l-2 transition-colors pl-[calc(1.5rem-2px)]
              {% if active %}bg-slate-800 text-white border-emerald-400
              {% else %}text-slate-300 hover:bg-slate-800 hover:text-white border-transparent{% endif %}">
        <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
        </svg>
        Versicherer
    </a>
    {% endif %}
    ```

- [ ] Task 4: Router in `app/main.py` registrieren (AC: 1, 4)
  - [ ] Import: `from app.routers import registries as registries_router` (analog zu anderen Routern)
  - [ ] `app.include_router(registries_router.router)` — nach `objects_router.router`, vor `workflows_router.router`

- [ ] Task 5: Unit-Tests `tests/test_registries_unit.py` (AC: 7)
  - [ ] `test_empty_list_when_no_versicherer()` — leere DB → `list_versicherer_aggregated(db) == []`
  - [ ] `test_aggregation_counts_one_versicherer()` — 1 Versicherer, 2 Policen (praemie 100+200), 1 Schadensfall (amount 50) → `policen_anzahl=2, gesamtpraemie=Decimal("300"), gesamtschaden=Decimal("50"), schadensquote≈0.167, objekte_anzahl=1`
  - [ ] `test_no_double_count_praemie_with_multiple_schadensfaelle()` — 1 Versicherer, 1 Police praemie=100, 2 Schadensfälle (30+20) → `gesamtpraemie=Decimal("100"), gesamtschaden=Decimal("50")` (NICHT gesamtpraemie=200)
  - [ ] `test_schadensquote_null_safe_when_no_praemie()` — Police ohne praemie (NULL) → `schadensquote=0.0`, kein ZeroDivisionError
  - [ ] `test_versicherer_without_policen_has_zero_counts()` — Versicherer ohne Policen → `policen_anzahl=0, gesamtpraemie=Decimal("0"), objekte_anzahl=0`
  - [ ] `test_sort_by_policen_anzahl_desc()` — 2 Versicherer: A mit 3 Policen, B mit 1 → `sort="policen_anzahl", order="desc"` → A first
  - [ ] `test_sort_by_name_asc_is_default()` — 2 Versicherer mit Namen "Zurich" und "Allianz" → `list_versicherer_aggregated(db)` (ohne Sort-Param) → `result[0].name == "Allianz"` (Default-Sort greift, Python-`str`-Sort ist case-sensitive asc)
  - [ ] `test_schadensquote_zero_when_schaden_without_praemie()` — 1 Versicherer, 1 Police mit `praemie=Decimal("0")`, 1 Schadensfall `amount=Decimal("100")` → `schadensquote == 0.0` (kein ZeroDivisionError; stiller Info-Loss per AC1 intendiert "0% wenn keine Prämie")
  - [ ] Fixtures: `Versicherer`, `InsurancePolicy`, `Schadensfall`, `Object` — direkt via `db.add(...)` anlegen (kein Write-Gate nötig — Test-Fixtures sind Row-Creation, Architektur §CD2 erlaubt). **Import-Idiom**: `from app.models import Versicherer, InsurancePolicy, Schadensfall, Object` (re-exports in `app/models/__init__.py`), nicht aus Submodulen.

- [ ] Task 6: Smoke-Tests `tests/test_registries_routes_smoke.py` (AC: 4, 5, 8)
  - [ ] **Neue Datei** `tests/test_registries_routes_smoke.py` anlegen — eigene Datei pro Feature ist die Konvention seit Story 1.3 (siehe `test_technik_routes_smoke.py`, `test_zugangscodes_routes_smoke.py`, `test_foto_routes_smoke.py`). **Nicht** in `test_steckbrief_routes_smoke.py` einfügen — dieses File ist für Objekt-Smoke-Tests reserviert.
  - [ ] Stil: Module-Level `def test_...`-Funktionen, **keine** `class Test...`-Struktur (Projekt-Konvention, verifiziert in allen bestehenden Smoke-Test-Files).
  - [ ] `test_unauthenticated_redirects(anon_client)` — `GET /registries/versicherer` → 302, `location` beginnt mit `/auth/google/login`
  - [ ] `test_no_permission_returns_403(auth_client)` — `test_user` in `conftest.py:127-132` hat `registries:view` **nicht** → 403, Detail enthält `"registries:view"`
  - [ ] `test_permitted_user_returns_200(steckbrief_admin_client)` — Fixture in `conftest.py:199-236` hat `registries:view` (Zeile 214) → 200
  - [ ] `test_rows_fragment_unauthenticated_redirects(anon_client)` — `GET /registries/versicherer/rows` → 302
  - [ ] `test_rows_fragment_no_permission_returns_403(auth_client)` — 403
  - [ ] `test_rows_fragment_sort_roundtrip(steckbrief_admin_client, db)` — 2 Versicherer mit unterschiedlicher Policen-Anzahl anlegen, `GET /registries/versicherer/rows?sort=policen_anzahl&order=desc` → 200; im Response-Body steht der Versicherer mit mehr Policen vor dem anderen (End-to-End-Verifikation des Param-Mappings, AC2).
  - [ ] `test_sidebar_link_visible_for_permitted_user(steckbrief_admin_client)` — AC5 positive: `GET /` → Body enthält `href="/registries/versicherer"`
  - [ ] `test_sidebar_link_hidden_for_unpermitted_user(auth_client)` — AC5 negative: `GET /` → weder `href="/registries/versicherer"` noch das Wort "Versicherer" im Body (Muster: `test_steckbrief_routes_smoke.py:388-396`)

## Dev Notes

### Was existiert — NICHT neu bauen

- **`registries:view` Permission**: bereits in `app/permissions.py:62` registriert und in `DEFAULT_ROLE_PERMISSIONS["user"]` (Zeile 102) enthalten — **keine Änderung an `permissions.py` nötig**.
- **Tabelle `versicherer`**: angelegt in Migration `0010_steckbrief_core.py` — **keine neue Migration nötig**.
- **`Versicherer`-Modell**: `app/models/registry.py:14` — Felder: `id`, `name`, `contact_info (JSONB)`, `created_at`, `updated_at`. Keine `relationship`-Attribute auf Policen (Abfrage via SQL direkt).
- **`InsurancePolicy`-Modell**: `app/models/police.py:15` — relevante Felder: `id`, `object_id`, `versicherer_id`, `praemie: Decimal | None`. Relationship zu `Object` vorhanden.
- **`Schadensfall`-Modell**: `app/models/police.py:103` — relevantes Feld: `amount: Decimal | None`. **ACHTUNG: Nicht `estimated_sum`** (→ Abweichung Epics vs. Modell, s. u.).
- **`steckbrief_admin_client` Fixture**: hat bereits `registries:view` in `permissions_extra` (conftest.py:214) — kann direkt für Smoke-Tests genutzt werden, kein neues Fixture nötig.
- **Kein Audit-Log nötig**: `list_versicherer_aggregated` ist ein reiner Read-Service.

### KRITISCH: `Schadensfall.amount` vs. `estimated_sum`

Die Epics AC spricht von "Summe `Schadensfall.estimated_sum`", aber das tatsächliche ORM-Feld ist **`Schadensfall.amount`** (`app/models/police.py:124`). Das Feld `estimated_sum` existiert nicht. Der Dev muss `amount` verwenden. Die Schadensquoten-Anzeige im UI kann trotzdem "Schadensquote" heißen — nur der Feldname im Code ist `amount`.

### KRITISCH: Kein Double-Count bei Aggregation

Wenn man `JOIN policen JOIN schadensfaelle GROUP BY versicherer_id` als eine einzige Abfrage schreibt, wird `sum(policen.praemie)` falsch hochgezählt (jede Police wird für jeden zugehörigen Schadensfall wiederholt). **Deshalb drei separate Queries + Python-Merge**:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import InsurancePolicy, Schadensfall, Versicherer

_SORT_ALLOWED = frozenset({"name", "policen_anzahl", "gesamtpraemie", "schadensquote", "objekte_anzahl"})


@dataclass
class VersichererAggRow:
    versicherer_id: uuid.UUID
    name: str
    policen_anzahl: int
    gesamtpraemie: Decimal
    gesamtschaden: Decimal
    objekte_anzahl: int
    schadensquote: float


def list_versicherer_aggregated(
    db: Session, *, sort: str = "name", order: str = "asc"
) -> list[VersichererAggRow]:
    # Query 1: Alle Versicherer
    alle_versicherer = db.execute(select(Versicherer)).scalars().all()
    if not alle_versicherer:
        return []

    # Query 2: Policen-Aggregation pro versicherer_id
    policen_q = (
        select(
            InsurancePolicy.versicherer_id,
            func.count(InsurancePolicy.id).label("cnt"),
            func.coalesce(func.sum(InsurancePolicy.praemie), 0).label("praemie_sum"),
            func.count(distinct(InsurancePolicy.object_id)).label("obj_cnt"),
        )
        .where(InsurancePolicy.versicherer_id.is_not(None))
        .group_by(InsurancePolicy.versicherer_id)
    )
    policen_by_vid: dict[uuid.UUID, Any] = {
        row.versicherer_id: row for row in db.execute(policen_q).all()
    }

    # Query 3: Schaden-Aggregation pro versicherer_id
    schaden_q = (
        select(
            InsurancePolicy.versicherer_id,
            func.coalesce(func.sum(Schadensfall.amount), 0).label("schaden_sum"),
        )
        .join(Schadensfall, Schadensfall.policy_id == InsurancePolicy.id)
        .where(InsurancePolicy.versicherer_id.is_not(None))
        .group_by(InsurancePolicy.versicherer_id)
    )
    schaden_by_vid: dict[uuid.UUID, Decimal] = {
        row.versicherer_id: Decimal(str(row.schaden_sum))
        for row in db.execute(schaden_q).all()
    }

    result: list[VersichererAggRow] = []
    for v in alle_versicherer:
        p = policen_by_vid.get(v.id)
        praemie = Decimal(str(p.praemie_sum)) if p else Decimal("0")
        schaden = schaden_by_vid.get(v.id, Decimal("0"))
        schadensquote = float(schaden / praemie) if praemie > 0 else 0.0
        result.append(VersichererAggRow(
            versicherer_id=v.id,
            name=v.name,
            policen_anzahl=p.cnt if p else 0,
            gesamtpraemie=praemie,
            gesamtschaden=schaden,
            objekte_anzahl=p.obj_cnt if p else 0,
            schadensquote=schadensquote,
        ))

    safe_sort = sort if sort in _SORT_ALLOWED else "name"
    result.sort(key=lambda r: getattr(r, safe_sort), reverse=(order == "desc"))
    return result
```

### `Decimal(str(...))` für SQLite-Kompatibilität

`func.sum(Numeric)` liefert in SQLite einen `float`, in Postgres ein `Decimal`. Der `Decimal(str(row.praemie_sum))`-Wrap stellt sicher, dass beide Environments korrekt rechnen. Gleiches für `schaden_sum`.

### HTMX-Swap + Fragment-Struktur (wichtig — sonst stale `<tbody>`)

Das Fragment `_versicherer_rows.html` liefert das vollständige `<tbody id="versicherer-rows">...</tbody>`. Das Parent-Template `registries_versicherer_list.html` macht deshalb **keinen** eigenen `<tbody>`-Wrapper — sonst entstehen zwei `<tbody>`-Elemente mit identischer ID, HTMX-`outerHTML`-Swap trifft nur den ersten und der zweite bleibt zurück.

**Parent korrekt**:

```html
<table class="w-full text-sm">
    <thead>...</thead>
    {% include "_versicherer_rows.html" %}
</table>
```

**Parent falsch** (nicht bauen):

```html
<tbody id="versicherer-rows">{% include "_versicherer_rows.html" %}</tbody>
```

HTMX-Swap bleibt `outerHTML` (nicht `innerHTML` — das würde `<tbody>` in `<tbody>` schachteln):

```html
hx-target="#versicherer-rows"
hx-swap="outerHTML"
```

### Sort-Sicherheit (kein SQL-Injection-Risiko)

Sortierung erfolgt in Python via `getattr`, nicht per SQL `ORDER BY`. Unbekannte `sort`-Params werden auf `"name"` zurückgefallen — kein 422, kein SQL-Injection-Pfad.

### Write-Gate-Boundary

Diese Story schreibt keine Steckbrief-Felder. Registry-Row-Creation ist vom Write-Gate explizit ausgenommen (Architektur §CD2: "Ausnahme: Row-Creation selbst ist erlaubt"). `list_versicherer_aggregated` ist reine Leseoperation.

### Registry-Aggregationen sind portfolio-weit — kein Object-ACL-Filter (Design-Entscheidung)

Anders als Due-Radar (Story 2-5) filtert diese Story **nicht** nach `accessible_object_ids(db, user)`. Begründung: Versicherer-Aggregationen sind Portfolio-Kennzahlen (Insurer-Performance, Konsolidierungs-Entscheidungen) — die Antwort auf "welcher Versicherer deckt wieviele Objekte und mit welcher Schadensquote" ist unabhängig davon, welche einzelnen Objekte der User aufklappen darf.

Heute konsistent: `DEFAULT_ROLE_PERMISSIONS["user"]` (`permissions.py:93-106`) enthält `objects:view` und `registries:view` gemeinsam — jeder User mit Registry-Zugriff sieht ohnehin alle Objekte. Sobald Object-ACL v1.1 scharfgeschaltet wird (`permissions.py:257-270`), bleiben die Aggregationen portfolio-weit sichtbar — bewusste Entscheidung, kein Bug. Falls später revidiert: `list_versicherer_aggregated(db, ..., accessible_object_ids=...)` um optionales Filter-Set erweitern, Queries 2+3 um `.where(InsurancePolicy.object_id.in_(accessible_object_ids))` ergänzen, Early-Return bei leerem Set (Muster Due-Radar).

### Sidebar: Position des Versicherer-Links

Der Due-Radar-Link wird in Story 2-5 nach dem Objekte-Block eingefügt. Story 2-7 fügt den Versicherer-Link **nach** dem Due-Radar-Block ein. Wenn Story 2-5 noch nicht implementiert ist (in dieser Sprint-Reihenfolge unwahrscheinlich), Versicherer nach Objekte einfügen.

Aktueller Sidebar-Stand nach Story 2-5 (erwartet):
1. Dashboard
2. Objekte (if `objects:view`)
3. Due-Radar (if `due_radar:view`) ← Story 2-5
4. **Versicherer (if `registries:view`) ← HIER einfügen**
5. Workflows (if `workflows:view`)
6. Admin (if `users:manage` or `audit_log:view`)

### `registries_versicherer_list.html`: Sortier-Header-Muster

Alle 4 numerischen Spalten (Policen, Prämie, Schadensquote, Objekte) erhalten HTMX-Attribute. Name-Spalte optional mit `sort=name&order=asc`-Link. Beispiel für eine numerische Spalte:

```html
<th class="text-right px-4 py-3 font-semibold cursor-pointer select-none hover:bg-slate-100"
    hx-get="/registries/versicherer/rows?sort=policen_anzahl&order=desc"
    hx-target="#versicherer-rows"
    hx-swap="outerHTML"
    title="Nach Policen-Anzahl absteigend sortieren">
    Policen
    <svg class="inline h-3 w-3 ml-1 text-slate-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4"/>
    </svg>
</th>
```

### `_versicherer_rows.html`: Fragment-Struktur

```html
<tbody id="versicherer-rows">
{% for row in rows %}
<tr class="border-b border-slate-100 hover:bg-slate-50">
    <td class="px-4 py-3">
        {{ row.name }}
        {% if row.policen_anzahl == 0 %}
        <span class="ml-2 text-xs text-slate-400 italic">ungenutzt</span>
        {% endif %}
    </td>
    <td class="text-right px-4 py-3 {% if row.policen_anzahl == 0 %}text-slate-400{% endif %}">
        {{ row.policen_anzahl }}
    </td>
    <td class="text-right px-4 py-3 {% if row.gesamtpraemie == 0 %}text-slate-400{% endif %}">
        {{ "%.0f"|format(row.gesamtpraemie|float) }} €
    </td>
    <td class="text-right px-4 py-3 {% if row.schadensquote == 0 %}text-slate-400{% endif %}">
        {{ "%.1f"|format(row.schadensquote * 100) }} %
    </td>
    <td class="text-right px-4 py-3 {% if row.objekte_anzahl == 0 %}text-slate-400{% endif %}">
        {{ row.objekte_anzahl }}
    </td>
</tr>
{% endfor %}
{% if not rows %}
<tr>
    <td colspan="5" class="px-4 py-8 text-center text-slate-400">Keine Versicherer vorhanden.</td>
</tr>
{% endif %}
</tbody>
```

### Test-Fixtures: Versicherer + InsurancePolicy + Schadensfall

Die Tests legen Entities direkt via `db.add(...)` an (kein Write-Gate nötig — nur `list_versicherer_aggregated` wird getestet). Vollständiges Muster:

```python
import uuid
from decimal import Decimal

from app.models import InsurancePolicy, Object, Schadensfall, Versicherer


def test_no_double_count_praemie_with_multiple_schadensfaelle(db):
    obj = Object(id=uuid.uuid4(), short_code="TST1", name="Test")
    db.add(obj)
    v = Versicherer(id=uuid.uuid4(), name="Testversicherer")
    db.add(v)
    p = InsurancePolicy(
        id=uuid.uuid4(), object_id=obj.id, versicherer_id=v.id,
        praemie=Decimal("100")
    )
    db.add(p)
    db.add(Schadensfall(id=uuid.uuid4(), policy_id=p.id, amount=Decimal("30")))
    db.add(Schadensfall(id=uuid.uuid4(), policy_id=p.id, amount=Decimal("20")))
    db.commit()

    from app.services.registries import list_versicherer_aggregated
    rows = list_versicherer_aggregated(db)
    assert len(rows) == 1
    assert rows[0].policen_anzahl == 1
    assert rows[0].gesamtpraemie == Decimal("100")   # nicht 200!
    assert rows[0].gesamtschaden == Decimal("50")
```

### Kein Audit-Log, kein BackgroundTask, kein Claude-Call

Diese Story ist pure Read-Query. Keine `BackgroundTasks`, keine Sessions-Fallstricke, kein `asyncio.run()`, kein `audit()`.

### Keine neue Migration

Alle benötigten Tabellen (`versicherer`, `policen`, `schadensfaelle`) sind seit Migration `0010` vorhanden. Die neueste Migration ist aktuell `0014_steckbrief_photos_fields.py`. **Keine neue Migration anlegen.**

### `TemplateResponse`-Signatur

Immer `templates.TemplateResponse(request, "name.html", {...})` — Request als erstes Argument. Memory: `feedback_starlette_templateresponse`.

### Scope-Grenze

**Nicht in Story 2-7:**
- Detailseite `/registries/versicherer/{id}` — das ist Story 2.8 (schon korrekt als 404 aus Story 2-6 verlinkt)
- Versicherer anlegen / bearbeiten (CRUD) — kein `registries:edit`-Flow in dieser Story
- Andere Registries (Dienstleister, Bank, Ablesefirma) — spätere Stories
- URL-State-Persistenz der Sort-Parameter — nicht in MVP

### Neue Dateien dieser Story

- `app/services/registries.py` (neu)
- `app/routers/registries.py` (neu)
- `app/templates/registries_versicherer_list.html` (neu)
- `app/templates/_versicherer_rows.html` (neu)
- `tests/test_registries_unit.py` (neu)
- `tests/test_registries_routes_smoke.py` (neu) — eigene Smoke-Test-Datei pro Feature (Konvention seit Story 1.3)

### Geänderte Dateien dieser Story

- `app/main.py` — Router-Import + `app.include_router(registries_router.router)`
- `app/templates/base.html` — Versicherer-Sidebar-Eintrag

### References

- Epic 2, Story 2.7 AC: `output/planning-artifacts/epics.md:692`
- Architecture FR16/FR17: `output/planning-artifacts/architecture.md` §CD1, §Requirements-to-Structure-Mapping
- `Versicherer`-Modell: `app/models/registry.py:14`
- `InsurancePolicy`-Modell: `app/models/police.py:15`
- `Schadensfall.amount`-Feld (NICHT `estimated_sum`): `app/models/police.py:124`
- Permission `registries:view`: `app/permissions.py:62`
- Sidebar-Muster: `app/templates/base.html:40–52` (Objekte-Block als Vorlage)
- Due-Radar-Muster (3 Queries + Python-Merge): Story 2-5 Dev Notes
- HTMX-Fragment-Muster (outerHTML-Swap): Story 2-6 Dev Notes + Story 2-5 Task 3
- `steckbrief_admin_client`-Fixture (hat `registries:view`): `tests/conftest.py:199`
- Write-Gate-Grenze (Registry-Row-Creation exempt): `output/planning-artifacts/architecture.md:638`
- `Decimal(str(...))` für SQLite-Kompatibilität: analog `app/services/mietverwaltung.py`
- Tailwind-Tabellen-Muster: `app/templates/objects_list.html`

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
