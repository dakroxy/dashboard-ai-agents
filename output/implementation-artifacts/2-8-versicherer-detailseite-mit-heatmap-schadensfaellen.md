# Story 2.8: Versicherer-Detailseite mit Heatmap & Schadensfaellen

Status: ready-for-dev

## Story

Als Mitarbeiter mit `registries:view`,
ich möchte pro Versicherer eine Detailseite mit allen verbundenen Policen, einer Ablauf-Heatmap und der Schadensfall-Historie sehen,
damit ich Kündigungs- und Neuverhandlungs-Entscheidungen datengetrieben vorbereiten kann.

## Acceptance Criteria

1. **AC1 — Kopfbereich:** `GET /registries/versicherer/{id}` liefert HTTP 200 mit Kopfbereich: Name des Versicherers, Adresse + Kontakt aus `contact_info`-JSONB (falls vorhanden), Anzahl Policen, Gesamtprämie p.a., Schadensquote (Gesamtschaden / Gesamtprämie, 0% wenn keine Prämie).
2. **AC2 — Ablauf-Heatmap:** Darunter eine Heatmap aus 12 Monats-Zellen (ab aktuellem Monat), farbcodiert nach dem schlimmsten ablaufenden Policy-Fälligkeitsdatum im jeweiligen Monat: rot (`< 30 Tage`), orange (`< 90 Tage`), grün (≥ 90 Tage), hellgrau (keine Police fällig). Tooltip pro Zelle: Monatsname + Policy-Anzahl.
3. **AC3 — Policen-Tabelle:** Tabelle aller verbundenen Policen: Policen-Nummer, Objekt (Deep-Link zu `/objects/{id}`), Prämie p.a., Fälligkeit, verbleibende Tage (farbcodiert analog Heatmap). Aufsteigende Sortierung nach Fälligkeit (nächste zuerst, NULL ans Ende).
4. **AC4 — Schadensfälle-Liste:** Liste aller Schadensfälle aus den Policen dieses Versicherers: Datum, Objekt (Short Code), Einheit (Unit-Nummer oder "–"), Betrag, Beschreibung. Neueste zuerst.
5. **AC5 — Verbundene Objekte:** Abschnitt "Verbundene Objekte" mit deduplizierter Liste aller Objekte (Short Code + Name, je Deep-Link zu `/objects/{id}`) die mindestens eine Police dieses Versicherers haben.
6. **AC6 — 404 für unbekannte ID:** Unbekannte UUID → HTTP 404.
7. **AC7 — Permission-Gate:** Ohne `registries:view` → 403. Nicht eingeloggt → 302.
8. **AC8 — Performance:** P95 unter 2 s bei bis zu 20 Policen.
9. **AC9 — Unit-Tests:** `tests/test_registries_unit.py` erhält mindestens 9 neue Tests (s. Tasks).
10. **AC10 — Smoke-Tests:** Unauthenticated → 302, kein `registries:view` → 403, unbekannte UUID → 404, berechtigt mit vorhandenem Versicherer → 200.

## Tasks / Subtasks

- [ ] Task 1: Dataclasses + Service-Funktion in `app/services/registries.py` ergänzen (AC: 1–5, 8, 9)
  - [ ] `PolicyDetailRow` Dataclass am Ende der Datei ergänzen:
    ```python
    @dataclass
    class PolicyDetailRow:
        policy_id: uuid.UUID
        police_number: str | None
        object_id: uuid.UUID
        object_short_code: str
        object_name: str
        praemie: Decimal | None
        next_main_due: date | None
        days_remaining: int | None
        severity: str  # "critical" | "warning" | "normal" | "none"
    ```
  - [ ] `SchadensfallDetailRow` Dataclass:
    ```python
    @dataclass
    class SchadensfallDetailRow:
        schadensfall_id: uuid.UUID
        occurred_at: date | None
        object_short_code: str
        unit_number: str | None
        amount: Decimal | None
        description: str | None
    ```
  - [ ] `VerbundeneObjektRow` Dataclass:
    ```python
    @dataclass
    class VerbundeneObjektRow:
        object_id: uuid.UUID
        short_code: str
        name: str
    ```
  - [ ] `HeatmapBucket` Dataclass:
    ```python
    @dataclass
    class HeatmapBucket:
        year: int
        month: int
        label: str        # z.B. "Apr 2026"
        policy_count: int
        severity: str     # "critical" | "warning" | "normal" | "empty"
    ```
  - [ ] `VersichererDetailData` Dataclass:
    ```python
    @dataclass
    class VersichererDetailData:
        versicherer: Versicherer
        policen_anzahl: int
        gesamtpraemie: Decimal
        gesamtschaden: Decimal
        schadensquote: float
        policen: list[PolicyDetailRow]
        schadensfaelle: list[SchadensfallDetailRow]
        verbundene_objekte: list[VerbundeneObjektRow]
        heatmap: list[HeatmapBucket]
    ```
  - [ ] `_MONTH_ABBR_DE = ["", "Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]` als Modul-Konstante
  - [ ] Hilfsfunktion `_build_heatmap(policen: list[PolicyDetailRow], today: date) -> list[HeatmapBucket]`:
    - 12 Schleifen-Iterationen i=0..11
    - Monat: `m = (today.month - 1 + i) % 12 + 1`, Jahr: `y = today.year + ((today.month - 1 + i) // 12)`
    - Policen in diesem Monat: `[p for p in policen if p.next_main_due and p.next_main_due.year == y and p.next_main_due.month == m]`
    - Severity: wenn keine Policen → `"empty"`; sonst: kleinster `days_remaining` der Policen in diesem Bucket → `< 30` → `"critical"`, `< 90` → `"warning"`, sonst `"normal"`
    - Achtung: Policies mit `days_remaining is None` (kein next_main_due) tauchen NICHT in Heatmap-Buckets auf
    - Label: `f"{_MONTH_ABBR_DE[m]} {y}"`
  - [ ] Hauptfunktion `get_versicherer_detail(db: Session, versicherer_id: uuid.UUID) -> VersichererDetailData | None`:
    - **Step 1**: `versicherer = db.execute(select(Versicherer).where(Versicherer.id == versicherer_id)).scalar_one_or_none()` → `None` zurückgeben wenn nicht gefunden
    - **Step 2**: Policen laden mit Object via JOIN (Models via Top-Level-Import `from app.models import Object, Unit, Versicherer, InsurancePolicy, Schadensfall` — nicht aus Submodulen, siehe Dev Notes):
      ```python
      policen_q = (
          select(
              InsurancePolicy.id,
              InsurancePolicy.police_number,
              InsurancePolicy.object_id,
              InsurancePolicy.praemie,
              InsurancePolicy.next_main_due,
              Object.short_code,
              Object.name,
          )
          .join(Object, Object.id == InsurancePolicy.object_id)
          .where(InsurancePolicy.versicherer_id == versicherer_id)
      )
      policen_raw = db.execute(policen_q).all()
      ```
    - **Step 3**: `PolicyDetailRow`-Liste bauen. `today = date.today()`. Pro Zeile: `dr = (r.next_main_due - today).days if r.next_main_due else None`, severity aus `dr` (`< 30` → `"critical"`, `< 90` → `"warning"`, `>= 90` → `"normal"`, `None` → `"none"`). Überfällige Policen (`dr < 0`) sind ebenfalls `"critical"` (fällt automatisch unter `< 30`). Gesamtprämie: `Decimal(str(r.praemie)) if r.praemie else Decimal("0")` akkumulieren. **Python-Sort**: `policen.sort(key=lambda p: (p.next_main_due or date.max, p.policy_id))` — Aufsteigend nach Fälligkeit (nächste zuerst), NULL ans Ende; Sekundär-Key `policy_id` für deterministische Reihenfolge bei gleichem Datum (kein `nullslast()` für SQLite-Kompatibilität).
    - **Step 4**: Schadensfälle laden — nur wenn `policy_ids` nicht leer (ACHTUNG: ORM-Feld heißt `occurred_at`, NICHT `occurrence_date`):
      ```python
      policy_ids = [r.id for r in policen_raw]
      if policy_ids:
          schaden_q = (
              select(
                  Schadensfall.id,
                  Schadensfall.occurred_at,
                  Schadensfall.amount,
                  Schadensfall.description,
                  Schadensfall.unit_id,
                  Object.short_code.label("object_short_code"),
              )
              .join(InsurancePolicy, InsurancePolicy.id == Schadensfall.policy_id)
              .join(Object, Object.id == InsurancePolicy.object_id)
              .where(Schadensfall.policy_id.in_(policy_ids))
          )
          schaden_raw = db.execute(schaden_q).all()
      else:
          schaden_raw = []
      ```
    - **Step 5**: Unit-Nummern per Bulk-Load holen:
      ```python
      unit_ids = [r.unit_id for r in schaden_raw if r.unit_id]
      unit_map: dict[uuid.UUID, str | None] = {}
      if unit_ids:
          units = db.execute(select(Unit.id, Unit.unit_number).where(Unit.id.in_(unit_ids))).all()
          unit_map = {u.id: u.unit_number for u in units}
      ```
    - **Step 6**: `SchadensfallDetailRow`-Liste bauen. Gesamtschaden akkumulieren: `Decimal(str(r.amount)) if r.amount else Decimal("0")`. **Python-Sort**: `schadensfaelle.sort(key=lambda s: (s.occurred_at or date.min, s.schadensfall_id), reverse=True)` — Neueste zuerst, Sekundär-Key für Determinismus bei gleichem Datum.
    - **Step 7**: Schadensquote: `float(gesamtschaden / gesamtpraemie) if gesamtpraemie > 0 else 0.0`
    - **Step 8**: Verbundene Objekte deduplizieren (Reihenfolge aus `policen_raw` beibehalten):
      ```python
      seen_obj_ids: set[uuid.UUID] = set()
      verbundene_objekte = []
      for r in policen_raw:
          if r.object_id not in seen_obj_ids:
              seen_obj_ids.add(r.object_id)
              verbundene_objekte.append(VerbundeneObjektRow(...))
      ```
    - **Step 9**: `heatmap = _build_heatmap(policen, today)`
    - `VersichererDetailData` zurückgeben

- [ ] Task 2: Router `app/routers/registries.py` erweitern (AC: 1, 6, 7, 10)
  - [ ] Neuen Handler **nach** dem `/versicherer/rows`-Handler in derselben Datei einfügen:
    ```python
    @router.get("/versicherer/{versicherer_id}")
    async def versicherer_detail(
        versicherer_id: uuid.UUID,
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission("registries:view")),
    ) -> TemplateResponse:
        detail = get_versicherer_detail(db, versicherer_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Versicherer nicht gefunden")
        return templates.TemplateResponse(request, "registries_versicherer_detail.html", {
            "detail": detail, "user": user
        })
    ```
  - [ ] Import `get_versicherer_detail` + neue Dataclasses aus `app.services.registries` ergänzen
  - [ ] Import `uuid` am Dateianfang ergänzen (falls noch nicht vorhanden)

- [ ] Task 3: Template `app/templates/registries_versicherer_detail.html` erstellen (AC: 1–5)
  - [ ] `{% extends "base.html" %}` + `{% block content %}`
  - [ ] **Zurück-Link**: `<a href="/registries/versicherer" class="text-sm text-slate-500 hover:text-slate-700">← Alle Versicherer</a>` als Breadcrumb oben
  - [ ] **Kopfbereich** (`bg-white rounded-lg border border-slate-200 p-6`):
    - `<h1>{{ detail.versicherer.name }}</h1>`
    - Kontakt/Adresse: `{% if detail.versicherer.contact_info %}...{{ detail.versicherer.contact_info.get("address", "") }}...{% endif %}`
    - 3-Spalten-Kennzahlen-Grid: Policen / Gesamtprämie / Schadensquote (Muster: `{{ "%.0f"|format(detail.gesamtpraemie|float) }} €` / `{{ "%.1f"|format(detail.schadensquote * 100) }} %`)
  - [ ] **Ablauf-Heatmap** Abschnitt:
    ```html
    <div class="bg-white rounded-lg border border-slate-200 p-6">
      <h2 class="text-sm font-semibold text-slate-700 mb-4">Ablauf-Heatmap (12 Monate)</h2>
      <div class="grid grid-cols-12 gap-1">
        {% for b in detail.heatmap %}
        <div class="flex flex-col items-center" title="{{ b.label }}: {{ b.policy_count }} {% if b.policy_count == 1 %}Police{% else %}Policen{% endif %}">
          <div class="w-full h-10 rounded
            {% if b.severity == 'critical' %}bg-red-500
            {% elif b.severity == 'warning' %}bg-orange-400
            {% elif b.severity == 'normal' %}bg-green-400
            {% else %}bg-slate-100{% endif %}">
          </div>
          <span class="text-xs text-slate-400 mt-1 text-center leading-tight">{{ b.label }}</span>
        </div>
        {% endfor %}
      </div>
      <p class="text-xs text-slate-400 mt-3">
        <span class="inline-block w-3 h-3 rounded bg-red-500 mr-1"></span>&lt; 30 Tage ·
        <span class="inline-block w-3 h-3 rounded bg-orange-400 mr-1 ml-2"></span>&lt; 90 Tage ·
        <span class="inline-block w-3 h-3 rounded bg-green-400 mr-1 ml-2"></span>≥ 90 Tage
      </p>
    </div>
    ```
  - [ ] **Policen-Tabelle** Abschnitt (`bg-white rounded-lg border border-slate-200`):
    - Spalten: Policen-Nr. | Objekt | Prämie p.a. | Fälligkeit | Verbleibend
    - Pro Zeile: `<a href="/objects/{{ p.object_id }}">{{ p.object_short_code }}</a>`, Fälligkeit `{{ p.next_main_due.strftime("%d.%m.%Y") if p.next_main_due else "–" }}`
    - Verbleibend-Zelle farbcodiert: `{% if p.severity == 'critical' %}text-red-600 font-medium{% elif p.severity == 'warning' %}text-orange-500{% elif p.severity == 'normal' %}text-slate-600{% else %}text-slate-400{% endif %}` + Wert `{{ p.days_remaining }} Tage` oder `"–"`
    - Leerer State: `{% if not detail.policen %}<tr><td colspan="5" ...>Keine Policen vorhanden.</td></tr>{% endif %}`
  - [ ] **Schadensfälle-Liste** Abschnitt:
    - Spalten: Datum | Objekt | Einheit | Betrag | Beschreibung
    - Datum: `{{ s.occurred_at.strftime("%d.%m.%Y") if s.occurred_at else "–" }}`
    - Einheit: `{{ s.unit_number or "–" }}`
    - Betrag: `{{ "%.0f"|format(s.amount|float) }} €` if amount else `"–"`
    - Leerer State: "Keine Schadensfälle vorhanden."
  - [ ] **Verbundene Objekte** Abschnitt:
    - `<ul>` mit `<li>` pro Objekt: `<a href="/objects/{{ o.object_id }}" class="text-blue-600 hover:underline">{{ o.short_code }} — {{ o.name }}</a>`
    - Leerer State: "Keine verbundenen Objekte."

- [ ] Task 4: Unit-Tests in `tests/test_registries_unit.py` ergänzen (AC: 9)
  - [ ] `test_get_versicherer_detail_returns_none_for_unknown_id(db)` — nicht-existierende UUID → `None`
  - [ ] `test_get_versicherer_detail_header_aggregations(db)` — 1 Versicherer, 2 Policen (praemie=100+200), 1 Schadensfall (amount=50) → `policen_anzahl=2`, `gesamtpraemie=Decimal("300")`, `gesamtschaden=Decimal("50")`, `schadensquote == pytest.approx(0.1667, abs=1e-3)` (50/300 = 0.1666…, exakte `float`-Assertion driftet)
  - [ ] `test_get_versicherer_detail_heatmap_has_12_months(db)` — Versicherer ohne Policen → `len(detail.heatmap) == 12`, alle Buckets `severity="empty"`
  - [ ] `test_heatmap_marks_expiring_policy_as_critical(db, monkeypatch)` — Police mit `next_main_due = date.today() + timedelta(days=10)` → Bucket für aktuellen Monat hat `severity="critical"`
  - [ ] `test_heatmap_marks_overdue_policy_as_critical(db, monkeypatch)` — Police mit `next_main_due = date.today() - timedelta(days=5)` (überfällig) → Bucket für aktuellen Monat hat `severity="critical"` (negativer `days_remaining` fällt unter `< 30`)
  - [ ] `test_heatmap_marks_expiring_policy_as_warning(db, monkeypatch)` — Police mit `next_main_due = date.today() + timedelta(days=60)` → entsprechender Bucket hat `severity="warning"`
  - [ ] `test_schadensfaelle_sorted_newest_first(db)` — 2 Schadensfälle mit `occurred_at=date(2024,6,1)` und `occurred_at=date(2025,3,1)` → `detail.schadensfaelle[0].occurred_at == date(2025,3,1)`
  - [ ] `test_verbundene_objekte_deduplicates(db)` — 2 Policen auf demselben Objekt → `len(detail.verbundene_objekte) == 1`
  - [ ] `test_detail_handles_empty_contact_info(db)` — Versicherer mit `contact_info={}` (Default) → `get_versicherer_detail(...)` wirft nicht; `detail.versicherer.contact_info == {}` (Template-Seite via Smoke-Test abgedeckt)
  - [ ] Fixtures-Muster (analog Story 2.7 `test_no_double_count_praemie_with_multiple_schadensfaelle`) — **Import-Idiom: Top-Level-Re-Exports aus `app.models` nutzen, nicht aus Submodulen** (verifiziert in `app/models/__init__.py`):
    ```python
    import pytest
    from app.models import InsurancePolicy, Object, Schadensfall, Versicherer
    from app.services.registries import get_versicherer_detail

    def test_get_versicherer_detail_returns_none_for_unknown_id(db):
        assert get_versicherer_detail(db, uuid.uuid4()) is None
    ```
  - [ ] **Kein Write-Gate in Fixtures** — direkt `db.add(...)` / `db.commit()` (Registry-Row-Creation ist Write-Gate-exempt per Architektur §CD2)

- [ ] Task 5: Smoke-Tests in `tests/test_registries_routes_smoke.py` ergänzen (AC: 10)
  - [ ] **Datei**: Story 2.7 erstellt `tests/test_registries_routes_smoke.py` als eigene Feature-Datei (Konvention seit Story 1.3 — pro Feature eine Smoke-Test-Datei). Story 2.8 fügt in diese Datei hinzu — **nicht** in `test_steckbrief_routes_smoke.py` (dort nur Objekt-Smoke-Tests).
  - [ ] **Stil**: Module-Level `def test_...`-Funktionen, **keine** `class Test...`-Struktur (Projekt-Konvention, verifiziert in allen bestehenden Smoke-Test-Files: `test_technik_routes_smoke.py`, `test_zugangscodes_routes_smoke.py`, `test_foto_routes_smoke.py`).
  - [ ] `test_detail_unauthenticated_redirects(anon_client)` — `GET /registries/versicherer/{uuid.uuid4()}` → 302, `location` beginnt mit `/auth/google/login`
  - [ ] `test_detail_no_permission_returns_403(auth_client)` — `test_user` in `conftest.py` hat `registries:view` nicht → 403
  - [ ] `test_detail_unknown_versicherer_returns_404(steckbrief_admin_client)` — `GET /registries/versicherer/{uuid.uuid4()}` → 404
  - [ ] `test_detail_permitted_user_returns_200(steckbrief_admin_client, db)` — Versicherer via `db.add(...)` anlegen → `GET /registries/versicherer/{v.id}` → 200

## Dev Notes

### Abhängigkeit: Story 2.7 muss vorher implementiert sein

Story 2.8 erweitert ausschließlich Dateien, die Story 2.7 erstellt:
- `app/services/registries.py` — Story 2.7 erstellt diese Datei neu (mit `VersichererAggRow` + `list_versicherer_aggregated`)
- `app/routers/registries.py` — Story 2.7 erstellt diese Datei neu (mit `GET /versicherer` + `GET /versicherer/rows`)
- `tests/test_registries_unit.py` — Story 2.7 erstellt diese Datei neu
- `tests/test_registries_routes_smoke.py` — Story 2.7 erstellt diese Datei neu (eigene Feature-Datei, Module-Level-`def test_*`-Funktionen)

Story 2.8 fügt zu diesen Dateien hinzu — **nicht neu anlegen**.

### Route-Reihenfolge: `/versicherer/rows` VOR `/versicherer/{id}`

In `app/routers/registries.py` müssen die Routen in dieser Reihenfolge stehen:
1. `GET /versicherer` — Liste (Story 2.7)
2. `GET /versicherer/rows` — HTMX-Fragment (Story 2.7)
3. `GET /versicherer/{versicherer_id}` — Detail **(Story 2.8, NACH rows)**

Da `versicherer_id: uuid.UUID` typisiert ist, akzeptiert FastAPI "rows" nicht als gültige UUID und routet korrekt auf `/versicherer/rows`. Zur Sicherheit trotzdem specifischere Routen voran.

### KRITISCH: `Schadensfall.amount` (nicht `estimated_sum`)

Wie in Story 2.7 dokumentiert: Tatsächliches ORM-Feld ist `Schadensfall.amount` (`app/models/police.py:124`). Das Feld `estimated_sum` existiert nicht. Gilt auch für diese Story.

### KRITISCH: `Schadensfall.occurred_at` (nicht `occurrence_date`)

Tatsächliches ORM-Feld für das Schadensdatum ist `Schadensfall.occurred_at` (`app/models/police.py:125`, `Mapped[date | None]`). Das Feld `occurrence_date` existiert nicht. Gilt in Query, Dataclass-Feld, Sort-Key, Template und Tests konsistent.

### Heatmap-Farbschema bewusst verfeinert gegenüber Epic AC

Epic AC beschreibt die Heatmap als "rote Markierungen bei ablaufenden Policen < 90 Tage" (einfarbig). Diese Story verfeinert zu 3 Stufen (rot `< 30` / orange `< 90` / grün `≥ 90` / hellgrau `keine Police`), weil eine reine Rot-Grün-Skala die Handlungspriorisierung zwischen "dringend" und "planbar" verliert. Die differenzierte Skala bleibt AC-konform (alle `< 90`-Fälle sind farblich markiert) und ist bewusst.

### `Decimal(str(...))` für SQLite-Kompatibilität

`func.sum(Numeric)` liefert in SQLite `float`, in Postgres `Decimal`. Der `Decimal(str(...))` Wrap (Muster aus Story 2.7) ist zwingend für korrekte Arithmetik in Tests. Gleiches für `praemie` und `amount`.

### Python-Sort statt SQL ORDER BY für SQLite-Compat

`nullslast()` in SQLAlchemy zeigt in SQLite unterschiedliches Verhalten. Beide Sortierungen **in Python** durchführen, mit Sekundär-Key für deterministische Reihenfolge bei Gleichstand:
- Policen: `policen.sort(key=lambda p: (p.next_main_due or date.max, p.policy_id))` — fälligste zuerst, NULL ans Ende, bei gleichem Datum stabil nach `policy_id`
- Schadensfälle: `schadensfaelle.sort(key=lambda s: (s.occurred_at or date.min, s.schadensfall_id), reverse=True)` — neueste zuerst, bei gleichem Datum stabil nach `schadensfall_id`

### `date` Import in `registries.py`

Oben in `app/services/registries.py` hinzufügen: `from datetime import date`. Der Import für `Decimal` ist bereits vorhanden (Story 2.7).

### Deep-Link-Konsistenz mit Story 2.6

Story 2.6 (Due-Radar-Filter) generiert bereits Links auf `/registries/versicherer/{versicherer_id}` im `_due_radar_rows.html`. Diese Route liefert bis Story 2.8 ein 404. Nach Story 2.8 funktionieren diese Links korrekt — kein Rework in Story 2.6 nötig.

### Versicherer-`contact_info` JSONB

`Versicherer.contact_info` ist `JSONB | None`. Im Template mit `.get(key, "")` auf mögliche Felder zugreifen. In v1 sind keine Pflichtfelder definiert — defensiv rendern:
```html
{% if detail.versicherer.contact_info %}
  {% set ci = detail.versicherer.contact_info %}
  {% if ci.get("address") %}<p>{{ ci.get("address") }}</p>{% endif %}
  {% if ci.get("phone") %}<p>{{ ci.get("phone") }}</p>{% endif %}
{% endif %}
```

### Model-Imports: Re-Exports aus `app.models`, nicht Submodule

Projekt-Konvention (verifiziert in `app/models/__init__.py` + Story 2.7): Top-Level-Import aus `app.models` nutzen, nicht aus Submodulen. Für diese Story:

```python
from app.models import InsurancePolicy, Object, Schadensfall, Unit, Versicherer
```

`Unit` liegt physisch in `app/models/object.py` (gleiches File wie `Object`), ist aber in `__init__.py` re-exportiert.

### Keine neue Migration

Alle Tabellen (`versicherer`, `policen`, `schadensfaelle`, `units`) sind seit Migration `0010_steckbrief_core.py` vorhanden. Neueste Migration: `0014_steckbrief_photos_fields.py`. **Keine neue Migration anlegen.**

### Keine BackgroundTask, kein Claude-Call, kein Audit-Log

Reine Read-View. Keine `BackgroundTasks`, kein `asyncio.run()`, kein `audit()`. Damit entfallen alle BackgroundTask-Fallstricke (Session-Lifecycle etc.).

### Kein Write-Gate in Service-Funktion

`get_versicherer_detail` ist ein reiner Lese-Service. Keine `write_field_human()`-Aufrufe. Fixtures in Tests legen direkt via `db.add()` an (Registry-Row-Creation ist Write-Gate-exempt per Architektur §CD2).

### `TemplateResponse`-Signatur (kritisch)

**Request als erstes Argument**: `templates.TemplateResponse(request, "registries_versicherer_detail.html", {...})`. Alte Signatur wirft `TypeError: unhashable type dict`. Memory: `feedback_starlette_templateresponse`.

### `hx-swap="outerHTML"` vs. `innerHTML`

Diese Detailseite hat kein HTMX-Fragment (keine Sortierung / kein Filter in MVP). Daher kein Fragment-Template nötig. Kein HTMX-Swap auf dieser Seite.

### Heatmap: Negativer `days_remaining` (überfällig)

Policen mit `days_remaining < 0` (bereits abgelaufen) werden im Heatmap-Bucket für ihren Ablauf-Monat mit `severity="critical"` markiert (Wert ist < 30). Sie erscheinen trotzdem in der Policen-Tabelle mit roter Farbe. Das ist korrekt — Überliegen ist kritischer als bevorstehender Ablauf.

### Scope-Grenze

**Nicht in Story 2.8:**
- Versicherer anlegen / bearbeiten (kein `registries:edit`-Flow)
- HTMX-Sort auf Policen-Tabelle (statische Liste in MVP)
- Andere Registries (Dienstleister, Bank, Ablesefirma)
- Mobile Card-Layout (Story 3-2)

### Neue Dateien dieser Story

- `app/templates/registries_versicherer_detail.html` (neu)

### Geänderte Dateien dieser Story

- `app/services/registries.py` — neue Dataclasses + `_MONTH_ABBR_DE` + `_build_heatmap` + `get_versicherer_detail` (Story 2.7 erstellt die Datei, diese Story erweitert)
- `app/routers/registries.py` — neuer `GET /versicherer/{versicherer_id}` Handler + Imports (Story 2.7 erstellt die Datei, diese Story erweitert)
- `tests/test_registries_unit.py` — 9 neue Unit-Tests (Story 2.7 erstellt die Datei, diese Story erweitert)
- `tests/test_registries_routes_smoke.py` — 4 neue Smoke-Tests als Module-Level-Funktionen (Story 2.7 erstellt die Datei, diese Story erweitert)

### Project Structure Notes

- Service in `app/services/registries.py` (Story 2.7 erstellt, diese Story erweitert)
- Router in `app/routers/registries.py` (Story 2.7 erstellt, diese Story erweitert)
- Template-Konvention: vollständige Seite ohne Underscore-Prefix (`registries_versicherer_detail.html`)
- Python-Klasse `Versicherer` ist in `app/models/registry.py:14`; Tabellenname `versicherer`
- Python-Klasse `InsurancePolicy` ist in `app/models/police.py:15`; Tabellenname `policen`
- Python-Klasse `Schadensfall` ist in `app/models/police.py:103`; Tabellenname `schadensfaelle`; Felder `amount` (nicht `estimated_sum`) + `occurred_at` (nicht `occurrence_date`)
- Python-Klassen `Object` + `Unit` sind in `app/models/object.py` — beide via `from app.models import Object, Unit` re-exportiert
- `steckbrief_admin_client`-Fixture hat `registries:view` (conftest.py:199) — direkt für Smoke-Tests verwendbar
- Smoke-Test-Datei: `tests/test_registries_routes_smoke.py` (von Story 2.7 erstellt) — Module-Level `def test_*`-Funktionen, keine `class Test...`-Struktur

### References

- Epic 2, Story 2.8 AC: `output/planning-artifacts/epics.md`
- Architecture §CD1 (Datennormalisierung, Write-Gate-Grenze für Registry): `output/planning-artifacts/architecture.md`
- Architecture §CD4 (Permission `registries:view`): `output/planning-artifacts/architecture.md`
- Story 2.7 (Basis-Infrastruktur registries.py/router/tests): `output/implementation-artifacts/2-7-versicherer-listenansicht-mit-aggregationen.md`
- Story 2.6 Dev Notes (Deep-Link-Hinweis: `/registries/versicherer/{id}` schon generiert, bis 2.8 = 404): `output/implementation-artifacts/2-6-due-radar-filter-deep-links.md`
- `Versicherer`-Modell (id, name, contact_info JSONB): `app/models/registry.py:14`
- `InsurancePolicy`-Modell (id, object_id, versicherer_id, police_number, praemie, next_main_due): `app/models/police.py:15`
- `Schadensfall.amount`-Feld (NICHT `estimated_sum`): `app/models/police.py:124`
- `Schadensfall.occurred_at`-Feld (NICHT `occurrence_date`): `app/models/police.py:125`
- Model-Re-Exports (Top-Level-Import-Idiom): `app/models/__init__.py`
- Smoke-Test-Datei-Konvention (eine Datei pro Feature, `def test_*` statt `class Test...`): `tests/test_technik_routes_smoke.py`, `tests/test_zugangscodes_routes_smoke.py`, `tests/test_foto_routes_smoke.py`
- `Object` + `Unit` (object_id FK, unit_number): `app/models/object.py`
- Permission `registries:view`: `app/permissions.py:62`
- `Decimal(str(...))` für SQLite-Kompatibilität: `app/services/registries.py` (Story 2.7 Muster)
- Python-Sort statt nullslast(): Story 2.7 Dev Notes §HTMX-Sort
- TemplateResponse-Signatur: Memory `feedback_starlette_templateresponse`
- Tailwind-Tabellen-Muster: `app/templates/registries_versicherer_list.html` (Story 2.7)
- `steckbrief_admin_client`-Fixture: `tests/conftest.py:199`
- Write-Gate-Boundary (Registry-Row-Creation exempt): `output/planning-artifacts/architecture.md:638`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6[1m]

### Debug Log References

### Completion Notes List

### File List
