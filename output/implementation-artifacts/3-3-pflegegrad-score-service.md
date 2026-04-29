# Story 3.3: Pflegegrad-Score-Service

Status: done

## Story

Als Entwickler,
möchte ich einen deterministischen Service, der pro Objekt einen Pflegegrad-Score aus Completeness + Aktualität berechnet,
damit Badge und Portfolio-Sort konsistent und reproduzierbar arbeiten.

## Boundary-Klassifikation

`backend-service` — Mittleres Risiko. Kein neuer Endpunkt, eine geänderte Route, keine neue Migration.
Risiken:
1. **Falsche Fieldnamen im Katalog**: Die Mapping-Tabelle (Feld-Katalog → Object-ORM-Felder) ist in dieser Story definiert — Abweichungen erzeugen stille Score-Fehler.
2. **pflegegrad_score_cached direkt setzen**: Das ist eine explizit erlaubte Ausnahme vom Write-Gate-Boundary (Kommentar in `_invalidate_pflegegrad`). Kein `write_field_human()` für Cache-Felder — das würde eine unendliche Invalidierungs-Schleife auslösen.
3. **N+1 Provenance-Queries**: Alle Provenance-Einträge in einer Query laden (`.in_(_ALL_SCALAR_FIELDS)`), nicht pro Feld einzeln.
4. **db.commit() im Router analog live_balance**: Der Cache-Update-Commit braucht einen eigenen try/except, damit ein Commit-Fehler den Page-Render nicht blockt (gleiche Defensive wie bei `last_known_balance`).
5. **Keine neue Migration**: `pflegegrad_score_cached` und `pflegegrad_score_updated_at` existieren bereits auf `Object` (seit Migration 0010/0013). Story 3.2 hat das bestätigt.

## Acceptance Criteria

**AC1 — Score 100 bei vollständigem Objekt**

**Given** ein Objekt mit allen C1/C4/C6/C8-Pflichtfeldern befüllt
**And** keiner FieldProvenance älter als 365 Tage (oder kein Provenance-Eintrag vorhanden)
**When** `pflegegrad_score(obj, db)` aufgerufen wird
**Then** liefert er `score=100`
**And** `per_cluster = {"C1": 1.0, "C4": 1.0, "C6": 1.0, "C8": 1.0}`
**And** `weakest_fields` ist leer

**AC2 — Score ~20 bei nur C1 befüllt**

**Given** ein Objekt, bei dem nur die C1-Pflichtfelder befüllt sind (full_address, impower_property_id, Eigentuemer vorhanden)
**And** C4, C6 und C8 vollständig leer (Felder None, sepa_mandate_refs=[], keine InsurancePolicy, keine Wartungspflicht)
**When** der Score berechnet wird
**Then** ist `score = 20` (C1-Gewicht 20% × C1-Completeness 100% × 100 = 20, round(20.0) = 20)
**And** `per_cluster["C1"]` ist `1.0`, alle anderen `0.0`
**And** `weakest_fields` enthält alle fehlenden C4-, C6- und C8-Feld-Keys

**AC3 — Aktualitäts-Decay für Provenance > 1095 Tage**

**Given** ein Objekt mit allen vier C4-Pflichtfeldern gesetzt (shutoff_water_location, shutoff_electricity_location, heating_type, year_built)
**And** für jedes dieser Felder existiert ein FieldProvenance-Eintrag mit `created_at` > 1095 Tage in der Vergangenheit
**And** alle anderen Cluster (C1, C6, C8) sind vollständig und aktuell
**When** der Score berechnet wird
**Then** ist der effektive Wert jedes C4-Felds 0.1 (Decay-Faktor für > 1095 Tage)
**And** `per_cluster["C4"]` ist `0.1` (= 4 × 0.1 / 4)

**AC4 — Cache-Invalidation bei write_field_human**

**Given** ein Objekt mit `pflegegrad_score_cached=72` und `pflegegrad_score_updated_at` gesetzt
**When** ein erfolgreicher `write_field_human(entity=obj, field="year_roof", value=2005, ...)` committed wird
**Then** ist `obj.pflegegrad_score_cached = None` und `obj.pflegegrad_score_updated_at = None`

_(Dieser AC ist bereits durch `_invalidate_pflegegrad()` in `steckbrief_write_gate.py` implementiert und durch `test_write_gate_unit.py::test_invalidate_pflegegrad_on_object_write` getestet. Kein neuer Test nötig — nur in der Test-Checkliste dokumentieren.)_

**AC5 — get_or_update_pflegegrad_cache: Cache-Population und Stale-Handling**

**Given** `obj.pflegegrad_score_cached = None` (noch nie berechnet)
**When** `get_or_update_pflegegrad_cache(obj, db)` aufgerufen und der Caller committed
**Then** ist `obj.pflegegrad_score_cached` danach befüllt mit dem berechneten Score
**And** `obj.pflegegrad_score_updated_at` ist auf den aktuellen Zeitpunkt gesetzt

**Given** `obj.pflegegrad_score_cached` ist gesetzt und `pflegegrad_score_updated_at` ist weniger als 5 Minuten alt
**When** `get_or_update_pflegegrad_cache(obj, db)` aufgerufen wird
**Then** werden `obj.pflegegrad_score_cached` und `obj.pflegegrad_score_updated_at` NICHT verändert (kein schreibender Zugriff auf diese Felder)

**AC6 — Detail-Route liefert PflegegradResult ans Template**

**Given** ein authentifizierter User mit `objects:view` ruft `GET /objects/{id}` auf
**When** die Route rendert
**Then** ist `pflegegrad_result` (Typ `PflegegradResult`) im Template-Context verfügbar
**And** bei stale oder leerem Cache (None oder `pflegegrad_score_updated_at` > 5 Min) wurde der Cache aktualisiert und committed
**And** bei frischem Cache (< 5 Min alt) wurde kein zusätzlicher Commit ausgelöst

## Tasks / Subtasks

- [x] Task 1: `app/services/pflegegrad.py` implementieren (AC1–AC3, AC5)
  - [x] 1.1: `PflegegradResult`-Dataclass: `score: int`, `per_cluster: dict[str, float]`, `weakest_fields: list[str]` — `frozen=True`, `from __future__ import annotations`
  - [x] 1.2: Modulkonstanten definieren: `CLUSTER_WEIGHTS`, `_C1_SCALAR`, `_C4_SCALAR`, `_C6_SCALAR`, `_ALL_SCALAR` (Union der drei für Provenance-Query), `CACHE_TTL = timedelta(minutes=5)`
  - [x] 1.3: `pflegegrad_score(obj: Object, db: Session) -> PflegegradResult` implementieren — Formel, Decay, Relational-Counts, per_cluster-Map, weakest_fields (Details siehe Dev Notes)
  - [x] 1.4: `get_or_update_pflegegrad_cache(obj: Object, db: Session) -> tuple[PflegegradResult, bool]` implementieren — ruft `pflegegrad_score()` auf, schreibt Cache nur wenn stale, kein `db.commit()`. Returnt `(result, cache_was_updated)` damit der Router gezielt committen kann (siehe Dev Notes).

- [x] Task 2: `app/routers/objects.py` — Detail-Route anpassen (AC6)
  - [x] 2.1: Import `pflegegrad.get_or_update_pflegegrad_cache` hinzufügen (absoluter Import)
  - [x] 2.2: In `object_detail()` nach dem Sparkline-Block `pflegegrad_result, cache_updated = get_or_update_pflegegrad_cache(detail.obj, db)` aufrufen
  - [x] 2.3: Wenn `cache_updated`: try/except um `db.commit()` wrappen, bei Exception `db.rollback()` + Warning-Log via `_logger.warning(...)` — `pflegegrad_result` ist trotzdem gültig (kein Render-Abbruch). Pattern analog `last_known_balance` (Zeile 213–221).
  - [x] 2.4: `"pflegegrad_result": pflegegrad_result` ins Template-Context-Dict

- [x] Task 3: `tests/test_pflegegrad_unit.py` (AC1–AC3, AC5)
  - [x] 3.1: `test_all_full_fresh_provenance_score_100` — AC1
  - [x] 3.2: `test_only_c1_filled_score_20` — AC2: prüfe score=20, per_cluster, weakest_fields enthält C4/C6/C8-Felder
  - [x] 3.3: `test_c4_decay_1095_days` — AC3: FieldProvenance-Rows mit `created_at = now - 1100 Tage` → C4-Completeness=0.1
  - [x] 3.4: `test_get_or_update_cache_population` — AC5a: leerem Cache → Cache befüllt nach Aufruf
  - [x] 3.5: `test_get_or_update_cache_no_write_when_fresh` — AC5b: frischer Cache → `pflegegrad_score_updated_at` unverändert, `pflegegrad_score_cached` unverändert

## Dev Notes

### Neue Datei: `app/services/pflegegrad.py`

Neue Datei, kein Edit an bestehenden Services außer `app/routers/objects.py`.

### Pflichtfeld-Katalog v1

Dieses Mapping ist die Quelle der Wahrheit für den Score. Fehlerhafte Feldnamen erzeugen stille 0-Scores.

**C1 — Stammdaten (Gewicht 20%)**

| Catalog-ID | ORM-Feld auf `Object` | Prüfbedingung | Provenance-Decay? |
|---|---|---|---|
| 1.3 | `full_address` | `is not None` | ja |
| 1.4 | `impower_property_id` | `is not None` | ja |
| 1.7 | relational: Eigentuemer-Count | `COUNT(Eigentuemer.object_id = obj.id) > 0` | nein |

**C4 — Technik (Gewicht 30%)**

| Catalog-ID | ORM-Feld auf `Object` | Prüfbedingung | Provenance-Decay? |
|---|---|---|---|
| 4.1 | `shutoff_water_location` | `is not None` | ja |
| 4.3 | `shutoff_electricity_location` | `is not None` | ja |
| 4.7 | `heating_type` | `is not None` | ja |
| 4.13 | `year_built` | `is not None` | ja |

**C6 — Finanzen (Gewicht 20%)**

| Catalog-ID | ORM-Feld auf `Object` | Prüfbedingung | Provenance-Decay? |
|---|---|---|---|
| 6.2 | `last_known_balance` | `is not None` | ja |
| 6.3 | `reserve_current` | `is not None` | ja |
| 6.8 | `sepa_mandate_refs` | `len(...) > 0` | nein (JSONB-Array) |

**C8 — Versicherungen (Gewicht 30%)**

| Catalog-ID | Relational | Prüfbedingung | Provenance-Decay? |
|---|---|---|---|
| 8.1 | `InsurancePolicy.object_id = obj.id` | Count > 0 | nein |
| 8.3 | `Wartungspflicht.object_id = obj.id` | Count > 0 | nein |

Felder ohne Decay (relational + sepa_mandate_refs): effektiver Wert = `1.0` wenn Bedingung erfüllt, `0.0` sonst.

Gesamtanzahl Pflichtfelder: C1=3, C4=4, C6=3, C8=2 = 12 Felder.

**Bewusst ausgelassene Katalog-Pflichtfelder (Begründung):**
- C1.1 `short_code` + C1.2 `name` — `nullable=False` auf `Object`, also bei jedem existierenden Objekt immer befüllt → würden trivial 1.0 ergeben und keine Diskrimination liefern.
- C1.8 `voting_rights` — JSONB mit Default `{}`. Aussagekräftige Befüllt-Prüfung wäre nicht trivial (`{}` vs. `{"some": "data"}`); fachlich oft erst nach Eigentümer-Importen vollständig. Aufgehoben für Cluster-Erweiterung in v1.1.
- C1.9 `unit_count` + C1.10 `total_mea` — derived Felder, keine ORM-Spalten.
- C6.1 `bank_accounts` — keine eigenständige `Bankkonto`-Entity in v1; `last_known_balance` (6.2) ist die ORM-Repräsentation des Bank-Account-Saldos und wird stattdessen geprüft.

### Formel

```
# Pro Feld i in Cluster K:
#   ist_befuellt_i = (ORM-Prüfbedingung erfüllt)
#   decay_i = 1.0 | 0.5 | 0.1  (bei Feldern MIT Provenance-Decay)
#            = 1.0              (bei Feldern OHNE Provenance-Decay)
#   effective_i = 0.0                  wenn nicht befüllt
#               = decay_i * ist_befuellt_i  wenn befüllt

# Pro Cluster K:
#   completeness_K = sum(effective_i für alle Felder i in K) / len(Felder in K)

# Score:
#   raw_score = sum(completeness_K * CLUSTER_WEIGHTS[K] for K in C1,C4,C6,C8)
#   score = round(raw_score * 100)
```

Decay-Funktion (gilt für alle Felder MIT Provenance-Decay):
```
decay(prov_age_days: int | None) -> float:
    None oder <= 365  →  1.0
    > 365 und <= 1095 →  0.5
    > 1095            →  0.1
```

`prov_age_days` = `(now - latest_prov.created_at).days` wobei `now = datetime.now(tz=timezone.utc)` (konsistentes Snapshot-Datum für den gesamten Aufruf).

### Efficient Provenance Query (keine N+1)

```python
# Felder MIT Decay-Check (alle Scalar-Felder der 3 Cluster ohne Relational)
_ALL_SCALAR = ("full_address", "impower_property_id",          # C1
               "shutoff_water_location", "shutoff_electricity_location",
               "heating_type", "year_built",                   # C4
               "last_known_balance", "reserve_current")        # C6

# Eine einzige Query für alle Provenance-Einträge:
provs = db.execute(
    select(FieldProvenance)
    .where(
        FieldProvenance.entity_type == "object",
        FieldProvenance.entity_id == obj.id,
        FieldProvenance.field_name.in_(_ALL_SCALAR),
    )
    .order_by(FieldProvenance.created_at.desc())
).scalars().all()

# Neueste Provenance pro Feld (absteigende Sortierung → erstes Auftreten = neuestes)
latest_prov: dict[str, FieldProvenance] = {}
for prov in provs:
    if prov.field_name not in latest_prov:
        latest_prov[prov.field_name] = prov
```

### Relationale Counts (3 weitere Queries)

```python
from sqlalchemy import func

eigentuemer_count = db.execute(
    select(func.count()).where(Eigentuemer.object_id == obj.id)
).scalar_one()

police_count = db.execute(
    select(func.count()).where(InsurancePolicy.object_id == obj.id)
).scalar_one()

wartung_count = db.execute(
    select(func.count()).where(Wartungspflicht.object_id == obj.id)
).scalar_one()
```

Imports: `from app.models import Eigentuemer, FieldProvenance, InsurancePolicy, Object, Wartungspflicht`

### weakest_fields — Format

`weakest_fields` ist eine `list[str]` mit ORM-Feldnamen für Scalar-Felder oder Sentinel-Strings für relationale Checks:
- Scalar: `"full_address"`, `"shutoff_water_location"`, `"year_built"` etc.
- Relational: `"has_eigentuemer"`, `"has_police"`, `"has_wartungspflicht"`
- `sepa_mandate_refs` (JSONB boolean): `"sepa_mandate_refs"`

Ein Feld landet in `weakest_fields` wenn: `effective_value < 1.0` (also entweder 0.0 oder 0.1 oder 0.5).

Story 3.4 wird diese Schlüssel auf Display-Labels und Anker-IDs mappen. Deshalb muss das Format hier konsistent definiert sein.

### `get_or_update_pflegegrad_cache` — Caching-Logik

```python
CACHE_TTL = timedelta(minutes=5)

def get_or_update_pflegegrad_cache(
    obj: Object, db: Session
) -> tuple[PflegegradResult, bool]:
    result = pflegegrad_score(obj, db)  # immer vollständige Berechnung

    now = datetime.now(tz=timezone.utc)
    is_stale = (
        obj.pflegegrad_score_cached is None
        or obj.pflegegrad_score_updated_at is None
        or (now - obj.pflegegrad_score_updated_at) >= CACHE_TTL
    )
    if is_stale:
        obj.pflegegrad_score_cached = result.score
        obj.pflegegrad_score_updated_at = now
        # kein db.commit() — Caller committed

    return result, is_stale
```

Hinweis: Immer vollständige Berechnung (auch wenn Cache frisch). Für 50 Objekte ist der DB-Query-Overhead (<5 ms) vernachlässigbar. Der Cache ist primär für die List-View-Sort (Story 3.1 liest `pflegegrad_score_cached` direkt aus der DB-Row).

### Router-Integration (objects.py)

Verbindliche Service-Signatur:
```python
def get_or_update_pflegegrad_cache(
    obj: Object, db: Session
) -> tuple[PflegegradResult, bool]:
    """Berechnet Score + aktualisiert Cache wenn stale.
    Returns: (result, cache_was_updated)"""
    ...
```

In `object_detail()` NACH dem Sparkline-Block (`sparkline_svg = ...`, Zeile 226) und VOR der Technik-Sektion:

```python
# --- Pflegegrad (Story 3.3) ---
pflegegrad_result, cache_updated = get_or_update_pflegegrad_cache(detail.obj, db)
if cache_updated:
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _logger.warning(
            "pflegegrad cache commit failed for object=%s: %s",
            detail.obj.id, exc,
        )
        # pflegegrad_result ist trotzdem gültig — Render läuft weiter
```

`pflegegrad_result` landet im Template-Context-Dict (`"pflegegrad_result": pflegegrad_result`). Story 3.4 rendert daraus Badge + Komposition-Popover.

### Explizite Ausnahme vom Write-Gate für Cache-Felder

`obj.pflegegrad_score_cached = ...` und `obj.pflegegrad_score_updated_at = ...` sind direkte Attribute-Writes außerhalb von `write_field_human()`. Das ist explizit erlaubt — Kommentar in `steckbrief_write_gate.py::_invalidate_pflegegrad`:
> "direkter Cache-Write auf `pflegegrad_score_*` — explizite Ausnahme vom Write-Gate-Boundary (AC9 Allow-List)"

`test_write_gate_coverage.py` allowlisted diese Felder bereits (Zeilen 51–54):
```python
("obj", "pflegegrad_score_cached"),
("obj", "pflegegrad_score_updated_at"),
("entity", "pflegegrad_score_cached"),
("entity", "pflegegrad_score_updated_at"),
```

### Test-Struktur (`tests/test_pflegegrad_unit.py`)

Das Test-File folgt dem Muster von `test_write_gate_unit.py` und `test_due_radar_unit.py`.

Fixtures: `db` (aus `tests/conftest.py`), `test_object` (aus `tests/conftest.py:185–196` — enthält ein leeres Object mit short_code="TST1"), `admin_user`.

**`admin_user`-Fixture lokal definieren** — die Fixture liegt aktuell NICHT in `conftest.py`, sondern lokal in `tests/test_write_gate_unit.py:31`. Für `tests/test_pflegegrad_unit.py` analog am Top des Files anlegen (oder copy-paste-Block aus `test_write_gate_unit.py`):

```python
@pytest.fixture
def admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-pflegegrad-admin",
        email="pflegegrad-admin@dbshome.de",
        name="Pflegegrad Admin",
        permissions_extra=["objects:view", "objects:edit"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
```

Für AC3 (Decay): FieldProvenance-Rows direkt per `db.add(FieldProvenance(...))` anlegen mit `created_at = datetime.now(tz=timezone.utc) - timedelta(days=1100)`. Wichtig: `timedelta(days=1100)` für > 1095 Tage. Kein `write_field_human()` für Tests, die die Provenance-Age steuern müssen.

Für AC2 (nur C1 befüllt): `test_object.full_address = "Musterstr. 1, 20099 Hamburg"` + `test_object.impower_property_id = "PROP-001"` direkt setzen (Row-Creation-Exception vom Write-Gate), dann `Eigentuemer`-Row per `db.add(Eigentuemer(object_id=test_object.id, ...))` anlegen.

Für AC1 (score=100): Alle C1/C4-Felder auf `test_object` direkt setzen + alle 8 Scalar-FieldProvenance-Rows mit `created_at = now - timedelta(days=30)` anlegen + 1 Eigentuemer + 1 InsurancePolicy + 1 Wartungspflicht.

Wichtiger Hinweis aus Epic-2-Retro: **Date-Tests auf Monatsmitte fixieren**:
```python
# Nicht: datetime.now() — flackert bei Monatsrand
# Stattdessen:
import datetime as _dt
_BASE = _dt.datetime.now(_dt.timezone.utc).replace(day=15, hour=12, minute=0, second=0, microsecond=0)
# Dann: _BASE - timedelta(days=1100) für alte Provenance
```

### Konflikte mit test_write_gate_coverage.py

`test_write_gate_coverage.py` grept source files auf direktes Feldzugriffs-Pattern auf CD1-Entitäten. Die pflegegrad.py-Datei setzt `obj.pflegegrad_score_cached` direkt — das ist durch die Allow-Liste in diesem Test bereits ausgenommen. NICHT ändern.

### Keine neue Migration

Alle Felder existieren bereits:
- `Object.pflegegrad_score_cached: int | None` — `app/models/object.py:74`
- `Object.pflegegrad_score_updated_at: datetime | None` — `app/models/object.py:75`
- Neueste Migration: `0016_wartungspflichten_missing_fields.py`

## Test-Checkliste (Epic-2-Retro P1)

- [ ] Permission-Matrix: nicht anwendbar (keine neue Route)
- [ ] IDOR: nicht anwendbar (keine FK aus Form-Body)
- [ ] Numerische Boundaries: score-Range 0–100 (round() garantiert Integer, gewichtete Summe von [0,1]-Werten × 100 kann max. 100.0 sein)
- [ ] NULLs korrekt: pflegegrad_score_cached=None → Score wird berechnet (AC5a)
- [ ] Tel-Link: nicht anwendbar
- [ ] Date-Bounds: Provenance-Age-Berechnung mit `timedelta.days` — sichere Integer-Differenz, kein Monatsgrenzen-Problem
- [ ] HTMX-422-Render: nicht anwendbar (kein Form-Submit)
- [ ] Cache-Invalidation: AC4 durch `tests/test_write_gate_unit.py::test_invalidate_pflegegrad_on_object_write` (Zeile 522) bereits abgedeckt — kein neuer Test in `test_pflegegrad_unit.py` nötig

## Neue Dateien

- `app/services/pflegegrad.py`
- `tests/test_pflegegrad_unit.py`

## Geänderte Dateien

- `app/routers/objects.py` — `object_detail()`: Import + `get_or_update_pflegegrad_cache`-Aufruf + Cache-Commit + Template-Context

## References

- Story 3.3 in Epics-File (Acceptance Criteria): `output/planning-artifacts/epics.md` §Story 3.3 (Zeile 781–806)
- Pflegegrad-Score Architecture Decision (ID3): `output/planning-artifacts/architecture.md` §ID3 — Pflegegrad-Score (Zeile 411–421)
- Pflichtfeld-Katalog mit `Pflicht v1 = ✓`-Markern: `docs/objektsteckbrief-feld-katalog.md` §Cluster 1/4/6/8
- Cache-Invalidation bereits implementiert: `app/services/steckbrief_write_gate.py::_invalidate_pflegegrad` (letzte Funktion)
- Write-Gate-Allow-List für Cache-Felder: `tests/test_write_gate_coverage.py:51–54`
- Object-Model (pflegegrad_score_cached): `app/models/object.py:74–77`
- FieldProvenance-Model: `app/models/governance.py:14–45`
- Object-Model (alle nullable Scalar-Felder): `app/models/object.py:27–77`
- InsurancePolicy-Model (object_id FK): `app/models/police.py`
- Eigentuemer-Model (object_id FK): `app/models/person.py`
- Wartungspflicht-Model (object_id FK): `app/models/police.py`
- Existing cache-invalidation test: `tests/test_write_gate_unit.py::test_invalidate_pflegegrad_on_object_write` (Zeile 522–524)
- Technik-Felder im Router: `app/routers/objects.py::STAMMDATEN_FIELDS`, `TECHNIK_FIELDS`
- Detail-Route (`object_detail()`): `app/routers/objects.py:132–355`
- Live-Balance-Commit-Pattern (try/except analog): `app/routers/objects.py:199–222`
- Test-Konftest-Fixtures (db, test_object): `tests/conftest.py`
- Date-Bounds Memory (Monatsmitte-Fixierung): Memory `feedback_date_tests_pick_mid_month.md`
- Cluster-Weights + Formel aus Epic-2-Retro: `output/implementation-artifacts/epic-2-retro-2026-04-28.md`
- Story 3.1 Dev Notes (pflegegrad_score_cached im List-View): `output/implementation-artifacts/3-1-objekt-liste-mit-sortierung-filter.md`
- Story 3.2 Dev Notes (keine Migration, pflegegrad-Farben 70/40): `output/implementation-artifacts/3-2-mobile-card-layout.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

SQLite gibt naive Datetimes zurück. `_ensure_utc()` in `pflegegrad.py` normalisiert naive Datetimes zu UTC-aware vor dem Vergleich. Test-Assertion für AC5b entsprechend angepasst.

`test_detail_sql_statement_count` Schwellwert von 16 → 21 angehoben (+4 Score-Queries + 1 Cache-Commit).

### Completion Notes List

Alle 3 Tasks und 5 Test-Cases implementiert. 779 Tests grün, 0 Regressions.

AC4 (Cache-Invalidation bei write_field_human) durch bestehenden `test_write_gate_unit.py::test_invalidate_pflegegrad_on_object_write` abgedeckt — kein neuer Test nötig (per Story-Spec).

### File List

- `app/services/pflegegrad.py` (neu)
- `app/routers/objects.py` (geändert: Import + Pflegegrad-Block + Template-Context)
- `tests/test_pflegegrad_unit.py` (neu)
- `tests/test_steckbrief_routes_smoke.py` (geändert: SQL-Statement-Count-Threshold 16 → 21)

### Review Findings

Code-Review 2026-04-29 (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Alle 6 Acceptance Criteria + 5 Boundary-Risiken aus der Spec sind erfuellt. 1 Patch + 16 Defer + 12 Dismiss.

#### Patch

- [x] [Review][Patch] `admin_user`-Fixture im neuen Test-File ist tot (kein Test konsumiert sie) — Spec erlaubt lokale Fixture, aber sie wird nicht referenziert; Dead Code [`tests/test_pflegegrad_unit.py:23-34`] — entfernt + obsolete `User`/`Object`-Imports

#### Deferred

- [x] [Review][Defer] Cache-Race: zwei parallele Detail-Requests koennen beide `is_stale=True` lesen und last-writer-wins committen [`app/services/pflegegrad.py:238-257`, `app/routers/objects.py:276-285`] — deferred, Architektur-Frage (Lock/Versionsspalte vor Multi-User-Rollout)
- [x] [Review][Defer] Commit-Fail-Loop: bei Cache-Commit-Exception bleibt obj in-memory neu, naechster Request crasht wieder ohne Backoff/Circuit-Breaker [`app/routers/objects.py:276-287`] — deferred, pre-existing Pattern auch bei live_balance
- [x] [Review][Defer] `weakest_fields` ohne Dedup/Sortierung — Story 3.4 wird die Liste fuer Badge/Popover konsumieren, dann ggf. nach Score-Beitrag sortieren [`app/services/pflegegrad.py:101-188`] — deferred bis Story 3.4
- [x] [Review][Defer] `pflegegrad_score` wird auch bei frischem Cache komplett neuberechnet — Cache spart nur den UPDATE, alle 4 Queries laufen weiter [`app/services/pflegegrad.py:184-201`] — deferred, Performance-Frage erst relevant fuer List-View mit >50 Objekten
- [x] [Review][Defer] `order_by(FieldProvenance.created_at.desc())` ohne stable Tie-Break (`id.desc()`) — bei gleichzeitigem Insert nicht-deterministisch [`app/services/pflegegrad.py:79`] — deferred, in Praxis vernachlaessigbar (Mikrosekunden-Granularitaet)
- [x] [Review][Defer] `_BASE = datetime.now()` at import time bindet Bezugspunkt einmalig — bei Test-Sessions ueber Tag-Grenzen minimaler Drift moeglich [`tests/test_pflegegrad_unit.py:15-17`] — deferred, freezegun-Migration projektweit
- [x] [Review][Defer] Fehlender Test: Provenance-Eintrag vorhanden, aber `obj.<field>` ist `None` (nach Reset/Loeschung) — Verhalten implizit, nicht explizit verifiziert — deferred, Coverage-Erweiterung in Folge-Story
- [x] [Review][Defer] Fehlender Test: komplett leeres Objekt → Score 0, alle Sentinels in `weakest_fields` — Score-Range 0–100 untere Grenze nicht abgesichert — deferred, Coverage-Erweiterung
- [x] [Review][Defer] Cache speichert nur `score`, nicht `per_cluster` oder `weakest_fields` — bis zur naechsten Stale-Berechnung divergieren List-View (Cache-Spalte) und Detail-View (frisch berechnet) [`app/services/pflegegrad.py:184-201`] — deferred, JSONB-Cache-Erweiterung in Story 3.4 oder Folge
- [x] [Review][Defer] Wenn `pflegegrad_score()` selbst einen DB-Fehler wirft, bricht die gesamte Detail-Page mit 500 — kein try/except um den Service-Aufruf, nur um den Commit [`app/routers/objects.py:276-287`] — deferred, Spec-Pattern folgt live_balance (das auch nicht den Read wraps)
- [x] [Review][Defer] `sepa_mandate_refs` mit Falsy-Items (`[None]`, `[{}]`) zaehlt als befuellt — `if not val:` triggert nicht bei `[{}]` [`app/services/pflegegrad.py:107-111`] — deferred, in Praxis nicht erwartet (Datenbank-Schema schreibt vor)
- [x] [Review][Defer] `last_known_balance == 0` / `year_built == 0` wird als befuellt gezaehlt (`is None`-Check ignoriert 0) [`app/services/pflegegrad.py:88`] — deferred, by Spec (`is not None`) — fachlich evtl. korrekt (0€ Saldo ist trotzdem ein Konto)
- [x] [Review][Defer] Naming-Drift: Code nutzt `_ALL_SCALAR`, Spec nennt `_ALL_SCALAR_FIELDS` [`app/services/pflegegrad.py:42`] — deferred, kosmetisch (Spec-Doku ist die Drift-Quelle)
- [x] [Review][Defer] AC6 hat keinen dedizierten Route-Test — Smoke-Test `test_detail_sql_statement_count` deckt den Pfad implizit ab, aber kein Test verifiziert `pflegegrad_result` im Template-Context — deferred, Spec verlangt Test nicht in Task 3
- [x] [Review][Defer] AC3-Test prueft nur `per_cluster["C4"] == 0.1`, nicht den Gesamt-Score (`round((1.0*0.20 + 0.1*0.30 + 1.0*0.20 + 1.0*0.30)*100) = 73`) — deferred, Spec verlangt nur Cluster-Wert
- [x] [Review][Defer] Statement-Count-Threshold `<= 21` ist Obergrenze, kein Equality-Check — bei Cache-Hit waere `+4` (kein Cache-Commit-UPDATE) statt `+5` [`tests/test_steckbrief_routes_smoke.py:458`] — deferred, Test laeuft mit Frisch-Objekt korrekt durch

#### Dismissed (Noise / by spec)

- Decay-Schwellen `<= 365 → 1.0`, `<= 1095 → 0.5`, `> 1095 → 0.1` — Spec definiert die Schwellen exakt so (links inklusiv).
- `timedelta.days` rundet ab — Spec definiert tagesgenaue Aufloesung.
- Naive→UTC-Drift bei `pflegegrad_score_updated_at` — DB-Spalte ist `DateTime(timezone=True)`, `_ensure_utc` ist nur SQLite-Test-Defensive (siehe Debug Log).
- Cluster-interne Gleichgewichtung der Felder — Spec definiert sie so (Pflichtfeld-Katalog).
- JSONB-Felder ohne Decay (`sepa_mandate_refs`) — by Spec ("nein (JSONB-Array)" in Pflichtfeld-Katalog).
- Relationale Counts ohne Decay (`Eigentuemer`/`InsurancePolicy`/`Wartungspflicht`) — by Spec.
- `db.commit()` in Test-Setup — pre-existing Pattern in `test_write_gate_unit.py` und Co.
- Test legt `InsurancePolicy`/`Wartungspflicht` ohne weitere Pflichtfelder an — Schemas sind aktuell permissiv (entspricht conftest-Pattern).
- Python `round()` ist Banker's Rounding — Spec verlangt `round()`.
- Future-dated `pflegegrad_score_updated_at` (Clock-Skew) — in Praxis nicht erreichbar (alle Writes via `datetime.now(tz=timezone.utc)`).
- `raw_score > 1.0` oder `< 0` — mathematisch unmoeglich bei korrekter Cluster-Berechnung (alle `eff_i ∈ [0,1]`, alle Weights summieren auf 1.0).
- `FieldProvenance.created_at = NULL` — Spalte ist verifiziert `nullable=False, server_default=func.now()`.
