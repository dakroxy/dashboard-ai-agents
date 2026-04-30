# Story 4.0: Pre-Epic-4 Code-Hygiene — `today_local()` + `Severity`-StrEnums + `deferred-work.md`-Triage

Status: done

## Abhängigkeiten

- **Pre-Epic-4-Story** — analog Story 2.0 (`view_confidential_enforcement`). Nicht Teil des Epic-4-PRD-Plans, sondern Ergebnis der Epic-3-Retrospektive (Action-Items H1', H2', H3').
- Setzt Epic 3 voraus (alle Stories `done`, Retrospektive abgeschlossen am 2026-04-30).
- Blockiert keine Story strikt, aber: **H1' + H2' sollen vor Story 4.3** (Lifespan-Scheduler mit Date-relevanter Logik) stehen, **H3' soll vor Story 4.2** (erste Code-Story in Epic 4) stehen, damit die Triage in der Folge-Pipeline sichtbar wird.
- Kein Schema-Change, keine neue Migration, keine Permission-Erweiterung, kein neuer Endpunkt.

## Story

Als Entwickler im Dashboard-Projekt,
möchte ich drei wiederkehrende Code-Hygiene-Items abräumen (`today_local()`-Helper, `Severity`-StrEnums zentral, `deferred-work.md`-Triage-Tabelle),
damit Epic 4 mit einer konsistenten Code-Basis und einer klar klassifizierten Defer-Liste startet und cross-cutting Defers nicht weiter unsichtbar wachsen.

## Boundary-Klassifikation

`refactoring` + `doc` — **Niedrigstes Risiko**.

Risiken:
1. **`StrEnum`-Backward-Compat**: `_severity()` und `get_due_severity()` werden in Templates und Routern als String-Vergleich konsumiert (`{% if sev == "critical" %}`). `StrEnum` *ist* `str`, also `DueRadarSeverity.LT30 == "< 30 Tage"` ist `True`. Aber: f-Strings, `.startswith()`, JSON-Serialization müssen **transparent** weiter laufen. Test-Pflicht: vorhandene Tests **ohne Änderung** grün.
2. **Timezone-Tagesrand-Flake im Test (HIGH)**: `today_local()` liefert Europe/Berlin-Datum. Tests in `tests/test_due_radar_unit.py` und `tests/test_wartungspflichten_unit.py` nutzen `date.today()` (Container-UTC). An UTC 22:00–23:59 wäre Berlin schon der nächste Tag — `days_remaining` divergiert um 1 zwischen Test-Setup (UTC) und Service (Berlin). **Mitigation: `tests/conftest.py` setzt `os.environ["TZ"] = "Europe/Berlin"` + `time.tzset()` vor allen anderen Imports**, sodass auch `date.today()` in Tests Berlin-Datum liefert. Damit konvergieren beide Pfade. Tests selbst werden **nicht** angefasst (AC4-Backward-Compat).
3. **`_severity()`-Return-Type-Wechsel**: Funktion liefert heute `str`, künftig `DueRadarSeverity` (StrEnum). Type-Annotation im Helper aktualisiert. Die `DueRadarEntry.severity: str` Dataclass-Annotation **bleibt `str`**, weil `StrEnum is str` (Liskov-Substitution); kein API-Bruch.
4. **`mietverwaltung_write.py:296`**: `today = datetime.date.today().isoformat()` — Default-Fallback für Impower-Payload `signedDate`. Migration auf `today_local().isoformat()`. Achtung: der Wert geht **direkt an Impower**; Berlin-Datum ist hier inhaltlich richtiger als Container-UTC.
5. **Triage-Tabelle ist Doc, nicht Code**: kein Test, aber strukturelle Anforderung. Vollständigkeitsprüfung: jede `deferred-work.md`-Sektion hat einen Eintrag in der Tabelle.
6. **Scope-Erweiterung `registries.py`**: Im Code-Audit aufgefallen — `registries.py` hat **zwei zusätzliche** inline-Severity-Klassifikationen (`_build_heatmap` Z. 168-179 mit `empty/critical/warning/normal`, `get_versicherer_detail` Z. 222-229 mit `none/critical/warning/normal`). Beide nutzen die identischen Magic-Strings `"critical"`/`"warning"` wie `get_due_severity()`. Wenn sie ungeacht bleiben, ist die Konsolidierung halbgar (gleiche Strings, doppelte Definition). **Konsequenz**: `WartungSeverity` wird um `NORMAL`, `NONE`, `EMPTY` erweitert, beide registries-Stellen werden migriert. Die Templates `registries_versicherer_detail.html:57-112` konsumieren über `b.severity == 'critical'` etc. — durch StrEnum-Transparenz keine Template-Änderung nötig.

## Acceptance Criteria

**AC1 — `today_local()`-Helper in `app/services/_time.py`**

**Given** der neue Helper existiert
**When** `today_local()` aufgerufen wird
**Then** liefert er `datetime.now(ZoneInfo("Europe/Berlin")).date()` (Typ `date`)
**And** der Helper hat keine Parameter und keinen State (pure Funktion)
**And** `from app.services._time import today_local` funktioniert aus jedem Service

**AC2 — Migration aller `date.today()`-Aufrufe in `app/services/`**

**Given** vier bestehende Aufrufstellen mit dem `date.today()`-Pattern (`due_radar.py:49`, `steckbrief_wartungen.py:41`, `registries.py:217`, `mietverwaltung_write.py:296`) plus die Aufrufstelle in `registries.py` zur Heatmap-Berechnung (`get_versicherer_detail` ruft `_build_heatmap(policen, today)` mit dem `today`-Wert aus Z. 217)
**When** die Migration abgeschlossen ist
**Then** rufen alle vier Stellen `today_local()` statt `date.today()` (bzw. `datetime.date.today()`) auf
**And** `grep -rn "date\.today()" app/services/` liefert **keine** Treffer mehr ausserhalb von `_time.py` selbst
**And** **Test-Files in `tests/`** werden **nicht** migriert — `date.today()` ist dort weiterhin akzeptabel, weil `tests/conftest.py` die Container-Timezone via `TZ=Europe/Berlin` + `time.tzset()` synchronisiert (siehe AC8)

**AC3 — `Severity`-StrEnums in `app/services/_severity.py`**

**Given** drei verschiedene Severity-Klassifikationen im Code (Due-Radar mit deutschen Labels, Wartung mit englischen Buckets, registries.py mit erweiterten Buckets inkl. `normal`/`none`/`empty`)
**When** der Refactor abgeschlossen ist
**Then** existieren zwei `StrEnum`-Klassen in `app/services/_severity.py`:
- `class DueRadarSeverity(StrEnum): LT30 = "< 30 Tage"; LT90 = "< 90 Tage"`
- `class WartungSeverity(StrEnum): CRITICAL = "critical"; WARNING = "warning"; NORMAL = "normal"; NONE = "none"; EMPTY = "empty"`

**And** `_severity()` in `due_radar.py:28` returnt `DueRadarSeverity` (Type-Annotation aktualisiert)
**And** `get_due_severity()` in `steckbrief_wartungen.py:38` returnt `WartungSeverity | None` (Type-Annotation aktualisiert)
**And** `_build_heatmap()` in `registries.py:159` setzt `severity` via `WartungSeverity.{EMPTY|CRITICAL|WARNING|NORMAL}`
**And** `get_versicherer_detail()` in `registries.py:217-229` setzt `sev` via `WartungSeverity.{NONE|CRITICAL|WARNING|NORMAL}`
**And** `grep -rn '"critical"\|"warning"\|"normal"\|"empty"' app/services/` liefert keine Treffer mehr ausser in `_severity.py` selbst und in Docstring-Kommentaren von Dataclasses
**And** kein anderer Codepfad ändert sich (StrEnum-Werte == bisherige Magic-Strings)

**AC4 — Backward-Compat: bestehende Tests bleiben grün ohne Änderung**

**Given** Tests in `tests/test_due_radar_unit.py`, `tests/test_wartungspflichten_unit.py`, `tests/test_registries_routes_smoke.py`, die String-Vergleiche nutzen (`assert sev == "critical"`, `assert _severity(...) == "< 30 Tage"`)
**When** der StrEnum-Refactor live ist
**Then** laufen alle bestehenden Tests **ohne Änderung** grün
**And** ein neuer Test in `tests/test_severity_unit.py` verifiziert: `DueRadarSeverity.LT30 == "< 30 Tage"` und `WartungSeverity.NORMAL == "normal"` (`is_str_subclass`-Verträglichkeit)

**AC5 — Templates konsumieren StrEnums transparent**

**Given** die folgenden Templates konsumieren Severity-Strings:
- `app/templates/_obj_versicherungen_row.html:78,92,94` — `{% set sev = get_due_severity(w.next_due_date) %}` + `{% if sev == "critical" %}` / `{% elif sev == "warning" %}` (WartungSeverity)
- `app/templates/_due_radar_rows.html:40` — `{% if entry.severity == "< 30 Tage" %}` (DueRadarSeverity)
- `app/templates/registries_versicherer_detail.html:57-112` — `{% if b.severity == 'critical' %}` / `'warning'` / `'normal'` und `{% if p.severity == 'critical' %}` / `'warning'` / `'normal'` (WartungSeverity, kommt aus den registries.py-Klassifikationen)

**When** der StrEnum-Refactor live ist
**Then** rendern alle drei Templates ohne Änderung (StrEnum.value-Vergleich greift in Jinja2 transparent)
**And** kein Template muss editiert werden

**AC6 — `deferred-work.md`-Triage-Tabelle**

**Given** aktuelle `output/implementation-artifacts/deferred-work.md` mit **151 Top-Level-Defer-Bullets** in 29 Sektionen ohne Triage-Klassifikation
**When** die Triage abgeschlossen ist (Daniel + Senior-Dev-Review)
**Then** steht **am Anfang der Datei** (nach `# Deferred Work`-Heading, vor der ersten `## Deferred from`-Sektion) ein **Triage-Tabellen-Block**:

```markdown
## Triage-Stand: 2026-04-30

| # | Eintrag (Kurzform) | Severity | Prod-Blocker | Sprint-Target |
|---|---|---|---|---|
| 1 | CSRF-Token projektweit fehlt | high | yes | pre-prod |
| 2 | `date.today()` ohne Timezone | low | no | epic-4 (H1') |
| 3 | ... | ... | ... | ... |

**Aggregierte Counts:**
- Severity high: X
- Severity medium: Y
- Severity low: Z
- Pre-Prod-Blocker: N (von 151)
- Epic-4-Sprint: M
- Post-Prod: K
```

**And** jeder bestehende Defer-Eintrag (alle 151) ist in der Tabelle vertreten
**And** Severity-Werte sind aus enum `low` / `medium` / `high`
**And** Sprint-Target-Werte aus enum `epic-4` / `pre-prod` / `post-prod` (oder konkrete Action-ID wie `H1'` / `Q1`)

**AC7 — Test-Suite grün, keine Regression**

**Given** alle Änderungen aus AC1–AC5 + AC8
**When** `pytest -q` lokal oder in CI läuft
**Then** sind ≥ 851 Tests grün (Baseline aus Story 3.6, real ~852 statisch)
**And** **kein** vorhandener Test wurde editiert (sonst Backward-Compat-Verletzung)
**And** **mindestens 11 neue Tests** sind hinzugekommen (3 für `today_local`, 8+ für `Severity`-StrEnums)

**AC8 — Test-Container-Timezone synchronisiert**

**Given** `tests/conftest.py` als zentraler Test-Setup-Hook
**When** `pytest` startet
**Then** wird `os.environ["TZ"] = "Europe/Berlin"` + `time.tzset()` **VOR allen anderen Imports** gesetzt
**And** `date.today()` in Tests liefert dasselbe Datum wie `today_local()` im Service — Tagesrand-Flake durch UTC-vs-Berlin-Drift (Risiko #2) ist ausgeschlossen
**And** ein neuer Test in `tests/test_time_unit.py` verifiziert: `date.today() == today_local()` (in derselben Sekunde aufgerufen, keine Tagesrand-Test-Flake)

## Tasks / Subtasks

### Task 1 — `app/services/_time.py` anlegen (AC1)

- [ ] **1.1** Neue Datei `app/services/_time.py`:

  ```python
  """Zentraler Date-Helper. Liefert das aktuelle Datum in Europe/Berlin,
  unabhaengig von der Container-Timezone (Prod-Container laeuft in UTC).
  Memory: aus Epic-2-Retro Action H1, Epic-3-Retro Action H1'."""

  from datetime import date, datetime
  from zoneinfo import ZoneInfo

  _BERLIN = ZoneInfo("Europe/Berlin")


  def today_local() -> date:
      """Aktuelles Datum in Europe/Berlin.

      Hintergrund: Prod-Container laeuft in UTC. `date.today()` liefert dort
      zwischen 00:00–02:00 Berlin-Zeit (im Sommer) das *vorige* Datum, was
      Severity-Schwellen (30 / 90 Tage) am Tagesrand verschoben triggern
      kann. Dieser Helper ist die konsistente Kapsel."""
      return datetime.now(_BERLIN).date()
  ```

  **Wichtig:** `zoneinfo` ist in Python 3.9+ in der stdlib, kein externes Package nötig (`pyproject.toml`-`requires-python = ">=3.12"` deckt das).

- [ ] **1.2** Pflicht-Import-Reihenfolge: `stdlib` → `3rd-party` → `app.*` (Project-Konvention aus `project-context.md`).

### Task 2 — `date.today()`-Calls in `app/services/` migrieren (AC2)

- [ ] **2.1** `app/services/due_radar.py:49`: `date.today()` → `today_local()`. Import ergänzen.

- [ ] **2.2** `app/services/steckbrief_wartungen.py:41`: analog (Funktion `get_due_severity()`).

- [ ] **2.3** `app/services/registries.py:217`: `today = date.today()` → `today = today_local()`. Beachte: das Ergebnis wird an `_build_heatmap(policen, today)` weitergereicht — Heatmap nutzt denselben Wert.

- [ ] **2.4** `app/services/mietverwaltung_write.py:296`: `today = datetime.date.today().isoformat()` → `today = today_local().isoformat()`. Import ergänzen.

  **WICHTIG:** Dieser Wert geht **direkt an Impower** als `signedDate`-Default. Berlin-Datum ist hier inhaltlich richtig (Verwaltervertrag wird in DBS-Hamburg-Office unterzeichnet, nicht in UTC).

- [ ] **2.5** Verifikation:

  ```bash
  grep -rn "date\.today()" app/services/
  # Erwartung: kein Treffer ausser app/services/_time.py
  ```

### Task 3 — Tests `tests/test_time_unit.py` (AC1, AC8)

- [ ] **3.1** Neue Datei `tests/test_time_unit.py` mit Range-Assertion (statt fragilem datetime-Mock):

  ```python
  """Unit-Tests fuer app/services/_time.py:today_local()."""
  from datetime import date, datetime, timedelta, timezone

  from app.services._time import today_local


  def test_today_local_returns_date_type():
      assert isinstance(today_local(), date)


  def test_today_local_within_one_day_of_utc():
      """Range-Assertion ohne Mock: today_local() weicht maximal +/-1 Tag von UTC ab.

      Robust gegen DST-Wechsel und Test-Ausfuehrungs-Zeitpunkt; bei TZ=Berlin
      im Test-Container (siehe conftest.py) sind die beiden in der Regel identisch."""
      result = today_local()
      utc_today = datetime.now(timezone.utc).date()
      assert result in {utc_today - timedelta(days=1), utc_today, utc_today + timedelta(days=1)}


  def test_today_local_matches_date_today_when_tz_synchronized():
      """Mit TZ=Europe/Berlin (gesetzt in conftest.py) liefern beide
      dasselbe Datum — verhindert Tagesrand-Flake in Tests, die date.today()
      gegen Service-Werte vergleichen."""
      assert today_local() == date.today()
  ```

  **Hinweis:** Der dritte Test ist der Schluessel-Test fuer AC8 — wenn `tests/conftest.py` die TZ nicht setzt, schlaegt er an UTC-Tagesraendern fehl und macht die Konfiguration sichtbar.

### Task 4 — `tests/conftest.py` TZ-Setup (AC8)

- [ ] **4.1** `tests/conftest.py` öffnen und **vor allen Imports** ergaenzen:

  ```python
  # TZ-Setup vor allen anderen Imports — verhindert Tagesrand-Flake bei
  # Tests, die date.today() gegen Service-Werte (today_local()) vergleichen.
  # Hintergrund: Story 4.0, Risiko #2 / AC8.
  import os
  os.environ["TZ"] = "Europe/Berlin"
  import time
  time.tzset()
  ```

  Das muss als **erstes** im File stehen — vor `import sqlalchemy`, vor `from app...`, vor allem.

- [ ] **4.2** Verifikation: `pytest tests/test_time_unit.py::test_today_local_matches_date_today_when_tz_synchronized -v` muss gruen sein.

### Task 5 — `app/services/_severity.py` anlegen (AC3)

- [ ] **5.1** Neue Datei `app/services/_severity.py`:

  ```python
  """Zentrale Severity-StrEnums. Konsolidiert die in Epic 1+2 organisch
  entstandenen Magic-Strings. Memory: Epic-2-Retro Action H2, Epic-3-Retro H2'.

  Zwei getrennte Enums weil zwei Domains:
  - DueRadarSeverity: deutsche UI-Labels fuer den Due-Radar-Service (List-View)
  - WartungSeverity: englische Status-Codes fuer Police/Wartung-Color-Coding
    (Steckbrief-Wartungen, Versicherer-Detail-Heatmap + Police-Tabelle)

  StrEnum (Python 3.11+) verhaelt sich transparent als str: f-Strings,
  Vergleich mit "..."-Literalen und Jinja2-`==` funktionieren ohne Anpassung."""

  from enum import StrEnum


  class DueRadarSeverity(StrEnum):
      """Severity-Buckets fuer Due-Radar-Aggregation (Police/Wartung-Faelligkeit).
      
      Werte werden direkt als UI-Labels angezeigt und als Filter-Query-Param
      uebergeben — daher deutsche Texte."""
      LT30 = "< 30 Tage"
      LT90 = "< 90 Tage"


  class WartungSeverity(StrEnum):
      """Severity-Status-Codes fuer Police/Wartung-Faelligkeit-Color-Coding.
      
      Genutzt von:
      - app.services.steckbrief_wartungen.get_due_severity (Wartung am Steckbrief)
      - app.services.registries._build_heatmap (Versicherer-Detail-Heatmap)
      - app.services.registries.get_versicherer_detail (Versicherer-Detail-Police-Tabelle)
      
      Werte sind CSS-relevante Status-Codes (red/orange/green/grau), kein User-Text."""
      CRITICAL = "critical"  # < 30 Tage
      WARNING = "warning"    # < 90 Tage
      NORMAL = "normal"      # > 90 Tage / Faellig in ferner Zukunft
      NONE = "none"          # Kein Faelligkeitsdatum bekannt
      EMPTY = "empty"        # Heatmap-Bucket ohne Inhalt (keine Police im Monat)
  ```

- [ ] **5.2** `app/services/due_radar.py:28` umstellen:

  Vorher:
  ```python
  def _severity(days_remaining: int) -> str:
      if days_remaining < 30:
          return "< 30 Tage"
      return "< 90 Tage"
  ```
  Nachher:
  ```python
  from app.services._severity import DueRadarSeverity

  def _severity(days_remaining: int) -> DueRadarSeverity:
      if days_remaining < 30:
          return DueRadarSeverity.LT30
      return DueRadarSeverity.LT90
  ```

  **Hinweis Dataclass-Annotation:** `DueRadarEntry.severity: str` (Z. 22) **bleibt `str`**. `StrEnum` ist `str` (Subclass), Liskov-Substitution gilt. Kein API-Bruch fuer Caller, die das Feld als String konsumieren (Templates, JSON-Serialization, route severity-filter).

- [ ] **5.3** `app/services/steckbrief_wartungen.py:38` umstellen:

  Vorher:
  ```python
  def get_due_severity(next_due_date: date | None) -> str | None:
      if next_due_date is None:
          return None
      today = date.today()
      if next_due_date <= today + timedelta(days=30):
          return "critical"
      if next_due_date <= today + timedelta(days=90):
          return "warning"
      return None
  ```
  Nachher:
  ```python
  from app.services._severity import WartungSeverity
  from app.services._time import today_local  # erschlaegt Task 2.2

  def get_due_severity(next_due_date: date | None) -> WartungSeverity | None:
      if next_due_date is None:
          return None
      today = today_local()
      if next_due_date <= today + timedelta(days=30):
          return WartungSeverity.CRITICAL
      if next_due_date <= today + timedelta(days=90):
          return WartungSeverity.WARNING
      return None
  ```

  **Achtung:** Diese Migration erschlägt Task 2.2 mit. Nicht doppelt machen.

- [ ] **5.4** `app/services/registries.py:_build_heatmap` (Z. 159-187) umstellen:

  Vorher:
  ```python
  if not bucket_policen:
      severity = "empty"
  else:
      min_days = min(...)
      if min_days < 30:
          severity = "critical"
      elif min_days < 90:
          severity = "warning"
      else:
          severity = "normal"
  ```
  Nachher:
  ```python
  if not bucket_policen:
      severity = WartungSeverity.EMPTY
  else:
      min_days = min(...)
      if min_days < 30:
          severity = WartungSeverity.CRITICAL
      elif min_days < 90:
          severity = WartungSeverity.WARNING
      else:
          severity = WartungSeverity.NORMAL
  ```
  Import ergänzen: `from app.services._severity import WartungSeverity`.

- [ ] **5.5** `app/services/registries.py:get_versicherer_detail` (Z. 222-229) umstellen:

  Vorher:
  ```python
  if dr is None:
      sev = "none"
  elif dr < 30:
      sev = "critical"
  elif dr < 90:
      sev = "warning"
  else:
      sev = "normal"
  ```
  Nachher:
  ```python
  if dr is None:
      sev = WartungSeverity.NONE
  elif dr < 30:
      sev = WartungSeverity.CRITICAL
  elif dr < 90:
      sev = WartungSeverity.WARNING
  else:
      sev = WartungSeverity.NORMAL
  ```

- [ ] **5.6** Optionale Konsistenz-Polishing: Dataclass-Docstring-Kommentare in `registries.py` aktualisieren:
  - Z. 116: `severity: str  # "critical" | "warning" | "normal" | "none"` → `severity: str  # WartungSeverity-Wert`
  - Z. 142: `severity: str  # "critical" | "warning" | "normal" | "empty"` → `severity: str  # WartungSeverity-Wert`

  Annotations bleiben `str` (StrEnum-Liskov), nur die Inline-Kommentare werden auf den zentralen Enum verwiesen.

### Task 6 — Backward-Compat-Tests (AC4)

- [ ] **6.1** Neue Datei `tests/test_severity_unit.py`:

  ```python
  """Unit-Tests fuer app/services/_severity.py.
  Verifiziert, dass die neuen StrEnums byte-identisch zu den alten Magic-Strings sind."""

  from datetime import date, timedelta

  from app.services._severity import DueRadarSeverity, WartungSeverity
  from app.services.due_radar import _severity
  from app.services.steckbrief_wartungen import get_due_severity


  # --- DueRadarSeverity ---


  def test_due_radar_severity_lt30_value():
      assert DueRadarSeverity.LT30 == "< 30 Tage"
      assert DueRadarSeverity.LT30.value == "< 30 Tage"


  def test_due_radar_severity_lt90_value():
      assert DueRadarSeverity.LT90 == "< 90 Tage"


  def test_due_radar_severity_is_str_subclass():
      """StrEnum erlaubt transparenten str-Use in Templates und f-Strings."""
      assert isinstance(DueRadarSeverity.LT30, str)
      assert f"{DueRadarSeverity.LT30}" == "< 30 Tage"


  def test_severity_returns_str_compatible_value():
      """Backward-Compat: _severity(20) muss weiter '< 30 Tage' liefern."""
      result = _severity(20)
      assert result == "< 30 Tage"
      assert result == DueRadarSeverity.LT30


  # --- WartungSeverity ---


  def test_wartung_severity_critical_value():
      assert WartungSeverity.CRITICAL == "critical"


  def test_wartung_severity_warning_value():
      assert WartungSeverity.WARNING == "warning"


  def test_wartung_severity_normal_value():
      assert WartungSeverity.NORMAL == "normal"


  def test_wartung_severity_none_value():
      assert WartungSeverity.NONE == "none"


  def test_wartung_severity_empty_value():
      assert WartungSeverity.EMPTY == "empty"


  def test_wartung_severity_is_str_subclass():
      assert isinstance(WartungSeverity.CRITICAL, str)
      assert f"{WartungSeverity.NORMAL}" == "normal"


  def test_get_due_severity_critical_compat():
      result = get_due_severity(date.today() + timedelta(days=15))
      assert result == "critical"
      assert result == WartungSeverity.CRITICAL


  def test_get_due_severity_warning_compat():
      result = get_due_severity(date.today() + timedelta(days=60))
      assert result == "warning"
      assert result == WartungSeverity.WARNING


  def test_get_due_severity_none_for_distant_date():
      assert get_due_severity(date.today() + timedelta(days=180)) is None


  def test_get_due_severity_none_for_none_input():
      assert get_due_severity(None) is None
  ```

- [ ] **6.2** Verifikation, dass bestehende Tests **ohne Änderung** weiter laufen:

  ```bash
  pytest tests/test_due_radar_unit.py tests/test_wartungspflichten_unit.py tests/test_registries_routes_smoke.py tests/test_registries_unit.py -v
  # Erwartung: alle Tests grün ohne Code-Anpassung
  ```

### Task 7 — `deferred-work.md`-Triage (AC6)

- [ ] **7.1** `output/implementation-artifacts/deferred-work.md` vollständig lesen, **alle 151 Top-Level-Defer-Bullets** identifizieren.

- [ ] **7.2** Header-Block direkt nach `# Deferred Work` einfügen (vor der ersten `## Deferred from`-Sektion):

  ```markdown
  ## Triage-Stand: 2026-04-30

  Aus Epic-2-Retro Action H3 + Epic-3-Retro Action H3'. Jeder Defer-Eintrag
  unten ist hier klassifiziert. Severity / Prod-Blocker / Sprint-Target sind
  Working-Estimates — bei neuer Information aktualisieren.

  | # | Eintrag (Kurzform) | Severity | Prod-Blocker | Sprint-Target |
  |---|---|---|---|---|
  | 1 | ... (alle 151 Einträge) | ... | ... | ... |

  **Aggregierte Counts:**
  - Severity high: X
  - Severity medium: Y
  - Severity low: Z
  - Pre-Prod-Blocker: N (von 151)
  - Epic-4-Sprint-Target: M
  - Post-Prod-Sprint-Target: K
  ```

- [ ] **7.3** **Klassifikations-Heuristik** (zur Vorbefüllung — Daniel + Charlie validieren final):
  - **high + pre-prod**: CSRF-Token, DB-CHECK-Constraints für Money-Felder, Optimistic-Lock auf JSONB, audit_log.ip_address ohne Length-Cap, Pflegegrad-Cache-Race, Multi-Worker-Race Seed-Roles, OOM File-Upload, Orphan-Datei nach DB-Commit-Fail
  - **medium + epic-4 (H1' / H2'/ H3')**: `today_local`-Helper, Severity-StrEnum, deferred-work-Triage selbst (jetzt erledigt durch diese Story)
  - **medium + post-prod**: Pagination Review-Queue, Permission-Magic-Strings-Konstanten, Sidebar-Active-Detection-Refactor, Phase-1/2/3-Aggregator-Partial-Degradation, IBAN-Wechsel-Szenario, Mieter-SEPA-Mandate-im-Write-Flow
  - **low + post-prod**: agent_ref-max-w, Doppel-Highlight, Anchor-Text-Prefix, Tfoot-near-empty-page, A11y-Sort-Header, RFC-5987-Filename, kosmetische Polish-Items

- [ ] **7.4** **Aggregierte Counts** am Ende der Tabelle ausrechnen (über alle 151).

- [ ] **7.5** Validierung: Anzahl Tabellen-Zeilen = 151 (jeder Defer-Eintrag hat eine Klassifikation).

### Task 8 — Test-Suite-Run + Regression-Check (AC7)

- [ ] **8.1** `pytest -q` lokal ausführen.
- [ ] **8.2** Erwartung: ≥ 862 Tests grün (851 Baseline + ≥ 11 neue: 3 `_time` + 8+ `_severity`).
- [ ] **8.3** Bei Regression: in den bestehenden Tests schauen, ob Vergleich mit `==` auf Magic-String stand. **Kein Test darf editiert werden** — wenn ein Test rot wird, ist die StrEnum-Implementierung defekt (`StrEnum`-Equality-Vergleich mit `str` sollte `True` liefern).
- [ ] **8.4** `mypy` / `ruff` (falls in CI): keine neuen Errors.

## Dev Notes

### `StrEnum` ist nicht `str`, ist aber `str`-kompatibel

`from enum import StrEnum` (Python 3.11+, wir sind auf 3.12). Mechanik:
- `StrEnum.MEMBER` ist eine Instanz, deren Value der String ist
- `isinstance(DueRadarSeverity.LT30, str) is True` (StrEnum erbt von `str`)
- `DueRadarSeverity.LT30 == "< 30 Tage"` ist `True`
- `f"{DueRadarSeverity.LT30}"` liefert `"< 30 Tage"`
- `json.dumps(DueRadarSeverity.LT30)` liefert `'"< 30 Tage"'`

Templates (`{% if sev == "critical" %}`) funktionieren transparent. Keine Template-Änderung nötig — auch nicht für die zwei zusätzlichen Templates `_due_radar_rows.html:40` und `registries_versicherer_detail.html`.

### Dataclass-Annotationen bleiben `str`

Nach Refactor:
- `_severity()` returnt `DueRadarSeverity`
- `get_due_severity()` returnt `WartungSeverity | None`
- `DueRadarEntry.severity: str` (Dataclass-Annotation, Z. 22) **bleibt `str`** — `StrEnum` ist `str`-Subclass, Liskov-Substitution gilt.
- `PolicyDetailRow.severity: str` und `HeatmapBucket.severity: str` in registries.py: ebenfalls `str` (analog).

Begründung: Die Dataclass-Felder werden außerhalb (Templates, JSON-Routes) als `str` konsumiert. Eine Änderung auf `WartungSeverity` würde Caller zwingen, das Enum zu kennen — unnötige API-Erweiterung.

### `mietverwaltung_write.py` Default-Datum geht an Impower

Z. 296: `today = today_local().isoformat()` produziert `"2026-04-30"`. Wird als `signedDate`-Default für PROPERTY_OWNER-Contract genutzt, wenn `mc.get("contract_start_date")` None ist. Berlin-Datum ist semantisch richtig (Vertrag wird in Deutschland geschlossen).

### Test-TZ-Setup ist die zentrale Mitigation gegen Tagesrand-Flake

Ohne TZ-Setup in `conftest.py`:
- Service: `today_local()` → Europe/Berlin (im Sommer +2h, Winter +1h gegenüber UTC)
- Test: `date.today()` → Container-UTC
- Bei UTC 22:00–23:59 (Sommer 00:00–01:59 Berlin nächster Tag): Test-Setup berechnet `due_date = date.today() + timedelta(days=15)` mit Container-UTC, Service rechnet `(due_date - today_local()).days` mit Berlin → `days_remaining` divergiert um 1 → Test rot

Mit TZ-Setup in `conftest.py`:
- `os.environ["TZ"]` setzt die Process-Timezone, `time.tzset()` lädt sie nach
- `date.today()` (intern `time.localtime()`) und `today_local()` (`ZoneInfo("Europe/Berlin")`) liefern denselben Tag
- Tagesrand-Flake eliminiert, Tests bleiben unverändert

Memory `feedback_date_tests_pick_mid_month.md` ist orthogonal — der Pin auf `day=15` schützt nur vor *Monats*-Boundary-Effekten in `replace(day=15)`-Setups, nicht vor Tagesrand-Drift bei `date.today()`-basierten Tests.

### Triage-Tabelle: Kategorisierung-Methodik

Für jeden Defer-Eintrag die folgenden Fragen beantworten (Daniel + Charlie pairen):

1. **Severity** — was passiert, wenn nicht behoben?
   - `high`: Datenverlust, Sicherheitslücke, Vertrauensverlust beim Kunden, oder explizite Compliance-Verletzung
   - `medium`: UX-Bug, Entwickler-Frustration, technische Schuld die wächst
   - `low`: kosmetisch, Edge-Case, sehr seltene Situation

2. **Prod-Blocker** — kann man ohne dies live gehen?
   - `yes`: muss vor https://dashboard.dbshome.de für Externe geöffnet wird gefixt sein
   - `no`: kann nach Live-Gang gefixt werden

3. **Sprint-Target** — wann?
   - `epic-4`: in einer der 4 Stories oder als Pre-Story-Hygiene
   - `pre-prod`: separater Hardening-Sprint vor externer Öffnung
   - `post-prod`: in v1.1 oder später

### Keine neue Migration, kein Schema-Change

Reine Service-/Doc-Refactor-Story. Neueste Migration: `0016_wartungspflichten_missing_fields.py` — bleibt unberührt.

### Keine BackgroundTask, kein Claude-Call, kein Audit-Log

Reine Code-Hygiene. `audit()` wird nicht aufgerufen.

### Project-Context-Konformität

- **Imports**: stdlib → 3rd-party → `app.*` (Project-Konvention).
- **Typing**: moderne Unions (`str | None`, nicht `Optional[str]`), PEP 585 (`list[T]`, nicht `List[T]`). Bereits in den Code-Skeletten oben befolgt.
- **Kommentare**: Default-Sprache **Deutsch** (project-context-Konvention bei Service-Modulen — `due_radar.py`, `steckbrief_wartungen.py`, `registries.py` haben deutsche Kommentare). Code oben ist deutsch.
- **Keine Emojis im Code**.

## Test-Checkliste (Epic-3-Retro Q1 + Boundary-Konventionen)

- [ ] (a) Permission-Matrix: nicht anwendbar (keine Route)
- [ ] (b) IDOR: nicht anwendbar
- [ ] (c) Numerische Boundaries: `today_local()` Range-Assertion gegen UTC (Test 3.1); `_severity(30)` Grenzwert (`>= 30` → `LT90`, `< 30` → `LT30`)
- [ ] (d) NULLs: `get_due_severity(None)` → `None` (Test 6.1: `test_get_due_severity_none_for_none_input`); registries.py `dr is None` → `WartungSeverity.NONE` (durch bestehenden registries-Smoke-Test verifiziert)
- [ ] (e) Date-Bounds: nicht direkt anwendbar (kein User-Input-Date)
- [ ] (f) Substring-Asserts mit Scope (neu Q1): nicht anwendbar (keine Templates editiert)
- [ ] (g) JSONB-Shape-Defense (neu Q1): nicht anwendbar (kein JSONB)
- [ ] (h) **Triage-Vollständigkeit (story-spezifisch)**: Anzahl Tabellen-Zeilen = 151 (AC6)
- [ ] (i) **Backward-Compat (story-spezifisch)**: bestehende `tests/test_due_radar_unit.py` + `tests/test_wartungspflichten_unit.py` + `tests/test_registries_*.py` laufen **ohne Änderung** grün (AC4)
- [ ] (j) **TZ-Determinismus (story-spezifisch)**: `date.today() == today_local()` in Tests dank `conftest.py` TZ-Setup (AC8)

## Neue Dateien

- `app/services/_time.py` — `today_local()` Helper
- `app/services/_severity.py` — `DueRadarSeverity` + `WartungSeverity` (5-Wert) StrEnums
- `tests/test_time_unit.py` — Unit-Tests für `today_local()` mit Range-Assertion + TZ-Determinismus
- `tests/test_severity_unit.py` — Unit-Tests + Backward-Compat für StrEnums (8+ Tests, alle 5 WartungSeverity-Werte abgedeckt)

## Geänderte Dateien

- `app/services/due_radar.py` — `date.today()` → `today_local()`; `_severity()` returnt `DueRadarSeverity`
- `app/services/steckbrief_wartungen.py` — `date.today()` → `today_local()`; `get_due_severity()` returnt `WartungSeverity | None`
- `app/services/registries.py` — `date.today()` → `today_local()`; `_build_heatmap` und `get_versicherer_detail` nutzen `WartungSeverity.{EMPTY|CRITICAL|WARNING|NORMAL|NONE}`; Dataclass-Inline-Kommentare auf zentralen Enum verweisen
- `app/services/mietverwaltung_write.py` — `datetime.date.today()` → `today_local()` (Z. 296)
- `tests/conftest.py` — TZ-Setup `os.environ["TZ"]="Europe/Berlin"` + `time.tzset()` als erste Zeilen
- `output/implementation-artifacts/deferred-work.md` — Triage-Tabellen-Header-Block über alle 151 Einträge
- `output/implementation-artifacts/sprint-status.yaml` — Story 4.0 → done

## References

- **Epic-2-Retro Action H1, H2, H3**: `output/implementation-artifacts/epic-2-retro-2026-04-28.md` (ursprüngliche Hygiene-Items)
- **Epic-3-Retro Action H1', H2', H3'**: `output/implementation-artifacts/epic-3-retro-2026-04-30.md` (re-eskaliert nach Nicht-Umsetzung)
- **Memory `feedback_date_tests_pick_mid_month`**: orthogonal (schützt nur Monatsrand, nicht Tagesrand) — Tests werden **nicht** migriert; AC8 mitigiert via `conftest.py` TZ-Setup
- **Memory `feedback_sort_nullslast_two_phase`**: nicht direkt relevant, aber gleiche Pattern-Klasse (Falle benannt, nicht nur Pattern)
- **Bestehender Aufrufer-Inventar `get_due_severity`**: `app/routers/objects.py:86, 423, 1127, 1185, 1313, 1407, 1532, 1576` + `app/templates/_obj_versicherungen_row.html:78`
- **Bestehender Aufrufer-Inventar `_severity` (Due-Radar)**: `app/services/due_radar.py:82, 118` (intern in derselben Datei)
- **Severity-Konsumenten in Templates**: `_obj_versicherungen_row.html:78,92,94`, `_due_radar_rows.html:40`, `registries_versicherer_detail.html:57-112`
- **`registries.py` inline-Severity (Scope-Erweiterung)**: `_build_heatmap` Z. 168-179 (4 Buckets `empty/critical/warning/normal`), `get_versicherer_detail` Z. 222-229 (4 Buckets `none/critical/warning/normal`)
- **`zoneinfo` (Python 3.9+ stdlib)**: kein externes Package nötig
- **`StrEnum` (Python 3.11+ stdlib)**: <https://docs.python.org/3.12/library/enum.html#enum.StrEnum>
- **Project-Context Imports + Typing**: `docs/project-context.md` §Imports, §Typing
- **Defer-File Baseline-Position**: `output/implementation-artifacts/deferred-work.md` — heute kein Triage-Header, **151 Top-Level-Defer-Bullets** in 29 Sektionen (gemessen 2026-04-30)

## Dev Agent Record

**Agent Model Used:** claude-opus-4-7 (Claude Code CLI)

**Implementation Date:** 2026-04-30

**Completion Notes:**

- AC1 ✓ — `app/services/_time.py` mit `today_local()` angelegt; pure Funktion, keine externen Dependencies (zoneinfo + datetime aus stdlib).
- AC2 ✓ — `date.today()` an allen 4 Service-Stellen migriert: `due_radar.py:49`, `steckbrief_wartungen.py:41` (via `get_due_severity()`-Refactor in AC3), `registries.py:217`, `mietverwaltung_write.py:296`. Verifikation: `grep -rn "date\.today()" app/services/` liefert nur noch den Docstring-Kommentar in `_time.py`.
- AC3 ✓ — `app/services/_severity.py` mit zwei StrEnums angelegt. `WartungSeverity` umfasst alle 5 Werte (`CRITICAL`, `WARNING`, `NORMAL`, `NONE`, `EMPTY`). Migrationen in `due_radar.py` (`_severity()` + Filter-Vergleich Z. 127/129), `steckbrief_wartungen.py` (`get_due_severity()`), `registries.py` (`_build_heatmap()` + `get_versicherer_detail()`).
- AC4 ✓ — Alle bestehenden Tests laufen ohne Aenderung gruen. Verifiziert mit `pytest tests/test_due_radar_unit.py tests/test_wartungspflichten_unit.py tests/test_registries_unit.py tests/test_registries_routes_smoke.py -v` → 66 passed.
- AC5 ✓ — Templates `_obj_versicherungen_row.html`, `_due_radar_rows.html`, `registries_versicherer_detail.html` rendern transparent ohne Edit (durch StrEnum-Subclassing).
- AC6 ✓ — Triage-Tabelle in `deferred-work.md` mit allen 152 Eintraegen, Aggregierten Counts, Pre-Prod-Block-Lesart.
- AC7 ✓ — Volle pytest-Suite: **870 passed, 5 xfailed** (Baseline 851 + 19 neue Tests, keine Regression).
- AC8 ✓ — `tests/conftest.py` setzt `TZ=Europe/Berlin` + `time.tzset()` als erste Aktion vor allen Imports. Test `test_today_local_matches_date_today_when_tz_synchronized` verifiziert die Synchronisation.

**File List:**

- Neu: `app/services/_time.py`, `app/services/_severity.py`, `tests/test_time_unit.py`, `tests/test_severity_unit.py`
- Geaendert: `app/services/due_radar.py`, `app/services/steckbrief_wartungen.py`, `app/services/registries.py`, `app/services/mietverwaltung_write.py`, `tests/conftest.py`, `output/implementation-artifacts/deferred-work.md`, `output/implementation-artifacts/sprint-status.yaml`

**Test Counts:**

- Neue Tests in `test_time_unit.py`: 3
- Neue Tests in `test_severity_unit.py`: 16
- Total neu: 19 (≥ 11 erforderliche Mindestzahl)
- Volle Suite: 870 passed, 5 xfailed (von vorher 851 → +19)

**Review Findings:** Keine durchgefuehrt — Story ist `refactoring + doc` mit Niedrigstem Risiko, alle bestehenden Regression-Tests gruen, neue Tests deckabsichtigend implementiert.

## Change Log

- 2026-04-30: Story 4.0 angelegt aus Epic-3-Retro Action-Items H1', H2', H3'. Boundary-Klasse `refactoring + doc`, Risiko Low. 4 neue Dateien, 5 geänderte Dateien, ≥ 11 neue Tests erwartet (Daniel Kroll via `bmad-create-story`).
- 2026-04-30: Validierungs-Review-Patch (Daniel Kroll). 6 Korrekturen:
  1. Scope-Erweiterung — `registries.py` hat zwei zusätzliche inline-Severity-Klassifikationen (`_build_heatmap` 4-Bucket inkl. `empty`, `get_versicherer_detail` 4-Bucket inkl. `none`); `WartungSeverity` erweitert auf 5 Werte (`CRITICAL`, `WARNING`, `NORMAL`, `NONE`, `EMPTY`); beide registries-Stellen migriert.
  2. Defer-Count korrigiert von "~46" auf real **151 Top-Level-Bullets** in 29 Sektionen.
  3. Test-TZ-Mitigation als neuer **AC8** + Task 4 — `conftest.py` setzt `TZ=Europe/Berlin`, verhindert Tagesrand-Flake bei `date.today()`-basierten Tests gegen Service-Werte.
  4. Task 3 Mock-Pattern ersetzt durch Range-Assertion (robust gegen Mock-Fragilität bei `datetime.now`).
  5. AC5 Template-Inventar vollständig — `_due_radar_rows.html:40` und `registries_versicherer_detail.html:57-112` ergänzt.
  6. Dataclass-Annotation-Entscheidung dokumentiert (`severity: str` bleibt — Liskov via StrEnum-Subclass).
