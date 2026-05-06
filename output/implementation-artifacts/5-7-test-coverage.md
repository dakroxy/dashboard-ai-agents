# Story 5.7: Test-Coverage & Lücken-Schliessen

Status: ready-for-dev

## Story

Als Entwickler der Plattform
möchte ich die 16 aufgelaufenen Test-Qualitäts-Findings aus früheren Code-Reviews schliessen, Coverage-Reporting aufsetzen und die Gesamt-Abdeckung auf >= 85 % heben,
damit Regressions-Schutz messbar und die Test-Suite als Gate in CI nutzbar ist.

## Hintergrund

Die Plattform hat nach Epic 1–5 bereits 62 Test-Dateien mit ~24 000 Zeilen. Diese Story ist kein "Test-Suite-Neubau", sondern eine gezielte **Lücken-Schliess-Runde**: 16 Deferred-Items (#21 #28 #32 #40 #41 #42 #47 #48 #49 #67 #74 #86 #94 #95 #97 #124) aus früheren Code-Reviews adressieren konkrete Test-Schwächen (fehlende Positiv-Pendant-Tests, fehlende Edge-Case-Assertions, fragile Thresholds, fehlende AST-Stufe-2 im Write-Gate-Scanner). Zusätzlich wird `pytest-cov` eingerichtet, ein Baseline-Report erstellt und die Lücken über 85 % gezielt geschlossen.

> **#152 (HTML-ID-Eindeutigkeit)** ist nicht Teil dieser Story — laut `sprint-status.yaml` zu Story 5-5 (AC9) verschoben (passt thematisch besser zum UX-/Smoke-Test-Bereich).

**Scope-Grenze**: Diese Story tastet App-Code **nicht** an. Alle Änderungen sind ausschliesslich in `tests/`, `pyproject.toml` und möglicherweise einem neuen `tests/test_write_gate_coverage_ast.py`. Kein Migrations-File, keine Router-Änderung.

**Vorbedingungen**: Stories 5-1 bis 5-6 sollten committed sein (Tests grün). Falls 5-5/5-6 noch parallel laufen: Baseline-Coverage-Lauf (Task 1.4) am Ende erneut durchführen, damit der Wert nicht durch nachgezogene App-Änderungen veraltet.

## Acceptance Criteria

---

### AC1 — Coverage-Infrastruktur aufsetzen

**Given** `pytest-cov` ist noch nicht in `pyproject.toml` eingetragen

**When** AC1 implementiert ist

**Then**:
- `pyproject.toml` hat `pytest-cov>=5.0` in der `[dependency-groups] dev`-Sektion
- `pyproject.toml` enthält eine `[tool.coverage.run]`- und `[tool.coverage.report]`-Sektion (s. Dev Notes für den exakten Config-Block)
- `pytest --cov=app --cov-report=term-missing` läuft durch und gibt einen Summary aus
- `pytest --cov=app --cov-report=html` erzeugt `htmlcov/index.html`
- `htmlcov/` ist in `.gitignore` eingetragen (falls noch nicht vorhanden)

---

### AC2 — Baseline messen & Gesamtabdeckung >= 85 %

**Given** Coverage-Infrastruktur aus AC1 existiert

**When** `pytest --cov=app --cov-report=term-missing` durchläuft

**Then**:
- Gesamtabdeckung (Statement-Coverage) `app/` >= 85 %
- Falls die Baseline unter 85 % liegt: fehlende Lines per `--cov-report=term-missing` identifizieren → Tests für die grössten Lücken ergänzen, bis die Grenze erreicht ist (Priorität: Service-Logik > Router > Templates-irrelevant)
- Kritische Module erreichen >= 90 % Line-Coverage: `app/services/steckbrief_write_gate.py`, `app/services/pflegegrad.py`, `app/services/due_radar.py`, `app/services/audit.py`, `app/permissions.py`
- Akzeptable Ausnahmen (via `omit`): `app/main.py` (Lifespan/asyncio), `app/config.py` (Env-Parsing), Migrations
- Completion Notes enthalten den tatsächlichen Baseline-Wert und den Endwert

---

### AC3 — Pflegegrad Unit-Test-Lücken schliessen (#40, #41)

**Given** `tests/test_pflegegrad_unit.py` hat zwei bekannte Lücken in den Edge-Case-Pfaden

**When** AC3 implementiert ist

**Then**:
- **#40** — neuer Test `test_scalar_effective_with_provenance_but_none_on_object`:
  ```python
  # Provenance-Eintrag vorhanden, obj.year_built ist aber None (z.B. nach Reset).
  # _scalar_effective() soll 0.0 returnen und das Feld in weakest_fields aufnehmen.
  ```
  Prüft: `pflegegrad_score()` läuft durch (kein Exception), Feld erscheint in `result.weakest_fields`
- **#41** — neuer Test `test_score_for_completely_empty_object`:
  ```python
  # Objekt ohne jede Provenance → Score == 0, alle gewichteten Felder in weakest_fields.
  ```
  Prüft: `result.score == 0`, `result.weakest_fields` ist nicht leer (enthält mindestens die 4 Cluster-Sentinel-Felder)
- **#48** — **bereits in der bestehenden Test-Suite abgedeckt** (`test_pflegegrad_unit.py` Z. 89: `assert result.score == 100` plus `result.per_cluster == {...}`). Item kann ohne Code-Änderung als geschlossen abgehakt werden — Vermerk in Completion Notes.
- Alle bestehenden Tests in `test_pflegegrad_unit.py` bleiben grün

---

### AC4 — Steckbrief Route-Test-Lücken schliessen (#47, #49, #124)

**Given** `tests/test_steckbrief_routes_smoke.py` hat drei bekannte Test-Schwächen

**When** AC4 implementiert ist

**Then**:
- **#47** — neuer Test `test_object_detail_pflegegrad_result_in_response`:
  Authenticated-Client ruft `GET /objects/{id}` auf, prüft `resp.status_code == 200` UND, dass der Body einen pflegegrad-bezogenen Marker enthält (z.B. `b"pflegegrad"` oder ein konkretes Score-Fragment). Deckt den Template-Context-Pfad ab, den `test_detail_sql_statement_count` nur implizit deckt.
- **#49** — `test_detail_sql_statement_count` wird robuster gemacht: der bestehende `assert statement_count <= 21` bleibt als Obergrenze; ein zusätzliches `assert statement_count >= 12` gibt eine Untergrenze (verhindert, dass ein wegfallender Query-Pfad unbemerkt bleibt). Beide Bounds in einem Kommentar begründen.
- **#124** — neuer Test `test_object_detail_sql_count_without_view_confidential`:
  User-Client **ohne** `objects:view_confidential` ruft `GET /objects/{id}` auf; zählt SQL-Statements analog zu `test_detail_sql_statement_count`; erwartet, dass die Anzahl **kleiner** ist als die des Admin-Clients (weil Zugangscode-Provenance-Query übersprungen wird). Exakte Untergrenze aus dem bestehenden Admin-Test minus 1..2 ableiten und als `assert count_without_conf < count_with_conf` formulieren.
- Alle bestehenden Tests grün

---

### AC5 — ETV Signature-List Test-Qualität (#28, #32)

**Given** `tests/test_etv_signature_list.py` hat zwei fragile Tests

**When** AC5 implementiert ist

**Then**:
- **#28** — `test_generate_returns_403_without_workflow_access` erhält ein Positiv-Pendant `test_generate_returns_200_with_workflow_access`: User **mit** korrekter Permission und gültigem Objekt-Zugriff → `POST /.../generate` gibt 200 (oder Redirect auf Success, je nach Router-Vertrag). Damit ist der Gate-Check beidseitig abgedeckt.
- **#32** — separater Test `test_generate_returns_404_when_object_missing` vs bestehender 5xx-Test (oder umbenannt): beide Fehlerpfade (404 Objekt nicht gefunden, 5xx FaciliooError) testen getrennt, statt in einem kombinierten Catch-all.
- Kein Rewrite des gesamten Files — nur die zwei genannten Tests ergänzen/aufteilen.

---

### AC6 — Review-Queue & Registries Test-Lücken (#21, #67)

**Given** `tests/test_review_queue_routes_smoke.py` und `tests/test_registries_routes_smoke.py` haben je eine bekannte Test-Schwäche

**When** AC6 implementiert ist

**Then**:
- **#21** — `test_review_queue_unauthenticated` prüft zusätzlich zur 302-Statuscode-Assertion den `Location`-Header: `assert "/login" in resp.headers["location"]`. Schützt vor Open-Redirect-Regression. (Einzeiler-Ergänzung im bestehenden Test.)
- **#67** — `test_versicherer_detail_permits_render_check`: bestehender Smoke-Test `test_detail_permitted_user_returns_200` wird um Body-Assertions erweitert: prüft dass der Response-Body `b"heatmap"` oder einen Versicherer-spezifischen Marker enthält, und dass `b"Schadensfälle"` vorhanden ist. Hält die Template-Vollständigkeit gegen künftige Template-Refactors.

---

### AC7 — Write-Gate AST-Scanner Stufe 2 (#94, #95)

**Given** `tests/test_write_gate_coverage.py` implementiert nur die Text-Scan-Stufe 1 (Regex-basiert); der AST-Ansatz wurde in Story 1.2 explizit auf 5-7 verschoben

**When** AC7 implementiert ist

**Then**:
- Neue Datei `tests/test_write_gate_coverage_ast.py` mit mindestens zwei Tests:
  - **`test_no_direct_attribute_assign_on_steckbrief_models`**: Nutzt Pythons `ast`-Modul um alle `.py`-Dateien in `app/routers/` und `app/services/` auf direkte Attribut-Zuweisungen (`ast.Assign` mit `ast.Attribute`-Target) zu scannen, wobei das Zielobjekt einem bekannten Model-Typ entspricht (mindestens `SteckbriefObject`). False-Positive-Ausnahmen: Assignments in `write_field_human`, `write_field_ai_proposal`, `approve_review_entry` selbst (diese sind die autorisierten Schreibpfade). Test schlägt fehl wenn unerlaubte Direkt-Zuweisungen gefunden werden.
  - **`test_no_setattr_bypass_on_steckbrief_models`**: Scannt `app/routers/` und `app/services/` auf `setattr(obj, "field_name", ...)` Calls wo `obj` als `SteckbriefObject` erkennbar ist (per Typkommentar oder Variablenname-Heuristik, zumindest via `re.search(r'setattr\(obj,', line)` als Ergänzung zum AST-Check). Deckt Lücke #95a ab.
- Bekannte False-Positive-Quellen aus #95 (Multi-Line-Konstruktoren, Variable-Shadowing) werden im Test-Docstring als "known limitation" dokumentiert — kein Anspruch auf Vollständigkeit, nur struktureller Basisschutz
- Beide Tests laufen rein statisch (kein DB, kein Client) und sind < 100 ms schnell

---

### AC8 — Dokumentations-Bereinigung & manuelles Smoke-Gate (#74, #86)

**Given** Zwei Items aus der Deferred-Liste sind keine Code-Änderungen sondern Verifikations-/Doku-Schritte

**When** AC8 abgehakt ist

**Then**:
- **#74** — In `tests/test_wartungspflichten_routes_smoke.py` Docstring/Modul-Kommentar prüfen: falls ein irreführender Kommentar im Stil *"Wartung ohne direktes object_id"* vorhanden ist, korrigieren zu *"Wartung-Query über PolicyJOIN (Wartungspflicht.object_id ist NOT NULL — der JOIN läuft via InsurancePolicy.object_id)"*. **Hinweis**: Bei Validierung der Story 5-7 wurde der Kommentar im aktuellen File **nicht gefunden** — Item ggf. bereits geschlossen. Verifikation per `grep -n "Wartung ohne direktes object_id" tests/`. Falls Treffer: korrigieren. Falls kein Treffer: in Completion Notes als "bereits erledigt" vermerken.
- **#86** — Manuelles Browser-Smoke-Gate (Menschen-Notizen): Admin öffnet `/objects/{id}` → sieht Notizen-Sektion → speichert eine Notiz; Normal-User öffnet `/objects/{id}` → sieht Sektion nicht. **Einmalig manuell durchklicken** vor Story-Done; nicht automatisierbar (kein Browser in Test-Suite). In Completion Notes mit Datum + Tester abhaken.

Done-Definition: `pytest tests/ -x` läuft durch (kein Skip, kein Ignore, kein roter Test); coverage-Endwert in Completion Notes festgehalten.

---

## Tasks / Subtasks

- [ ] **Task 0: Baseline-Vorab-Lauf (Aufwandsschätzung)**
  - [ ] 0.1 Vor Story-Start temporär `pytest-cov` lokal installieren (`uv pip install pytest-cov`) und einmal `pytest --cov=app --cov-report=term-missing` durchlaufen lassen — Wert in Completion Notes als **Baseline** eintragen. Damit ist der Aufwand in Task 2 abschätzbar (bei Baseline >= 85 % entfällt Task 2.2 ganz).

- [ ] **Task 1: Coverage-Setup (AC1)**
  - [ ] 1.1 `pytest-cov>=5.0` in `pyproject.toml` `[dependency-groups] dev` ergänzen
  - [ ] 1.2 `[tool.coverage.run]` und `[tool.coverage.report]` Config-Block in `pyproject.toml` einfügen (s. Dev Notes)
  - [ ] 1.3 `htmlcov/` in `.gitignore` prüfen, ggf. ergänzen
  - [ ] 1.4 Re-Lauf: `pytest --cov=app --cov-report=term-missing` mit Config — Prozentwert bestätigen

- [ ] **Task 2: Baseline >= 85 % (AC2)**
  - [ ] 2.1 Falls Baseline < 85 %: `--cov-report=term-missing` Ausgabe analysieren → grösste Lücken identifizieren
  - [ ] 2.2 Tests für die Lücken ergänzen bis >= 85 % (typisch: ungetestete Service-Pfade in kleinen Hilfsfunktionen)
  - [ ] 2.3 Kritische Module auf >= 90 % prüfen (write_gate, pflegegrad, due_radar, audit, permissions)
  - [ ] 2.4 Endwert im Completion Notes festhalten

- [ ] **Task 3: Pflegegrad-Tests (AC3)**
  - [ ] 3.1 `test_scalar_effective_with_provenance_but_none_on_object` in `tests/test_pflegegrad_unit.py` ergänzen (#40)
  - [ ] 3.2 `test_score_for_completely_empty_object` ergänzen (#41)
  - [ ] 3.3 #48 verifizieren (`grep -n "result.score" tests/test_pflegegrad_unit.py`) und in Completion Notes als bereits erledigt vermerken
  - [ ] 3.4 `pytest tests/test_pflegegrad_unit.py -v` → alle grün

- [ ] **Task 4: Steckbrief-Route-Tests (AC4)**
  - [ ] 4.1 `test_object_detail_pflegegrad_result_in_response` in `test_steckbrief_routes_smoke.py` ergänzen (#47)
  - [ ] 4.2 `test_detail_sql_statement_count` um Untergrenze-Assert erweitern (#49)
  - [ ] 4.3 `test_object_detail_sql_count_without_view_confidential` ergänzen (#124)
  - [ ] 4.4 `pytest tests/test_steckbrief_routes_smoke.py -v` → alle grün

- [ ] **Task 5: ETV Signature-List (AC5)**
  - [ ] 5.1 `test_generate_returns_200_with_workflow_access` in `test_etv_signature_list.py` ergänzen (#28)
  - [ ] 5.2 5xx- vs 404-Test trennen (#32)
  - [ ] 5.3 `pytest tests/test_etv_signature_list.py -v` → alle grün

- [ ] **Task 6: Review-Queue & Registries (AC6)**
  - [ ] 6.1 Location-Header-Assert in `test_review_queue_unauthenticated` (#21)
  - [ ] 6.2 Body-Assert in Versicherer-Detail-Smoke-Test (#67)
  - [ ] 6.3 Beide Files grün

- [ ] **Task 7: AST Write-Gate Scanner (AC7)**
  - [ ] 7.1 Neue Datei `tests/test_write_gate_coverage_ast.py` anlegen
  - [ ] 7.2 `test_no_direct_attribute_assign_on_steckbrief_models` implementieren (#94)
  - [ ] 7.3 `test_no_setattr_bypass_on_steckbrief_models` implementieren (#95)
  - [ ] 7.4 False-Positive-Ausnahmen (write_field_human etc.) in Allowlist konfigurieren
  - [ ] 7.5 `pytest tests/test_write_gate_coverage_ast.py -v` → beide grün

- [ ] **Task 8: Doku-Bereinigung & Manuelles Smoke-Gate (AC8)**
  - [ ] 8.1 `grep -n "Wartung ohne direktes object_id" tests/` — falls Treffer: korrigieren (#74); falls leer: Completion Note "bereits erledigt"
  - [ ] 8.2 Manueller Browser-Smoke Menschen-Notizen (#86) durchklicken — Admin sieht/speichert, Normal-User sieht nicht. Datum + Tester in Completion Notes festhalten
  - [ ] 8.3 Falls 5-5 oder 5-6 nach Story-Beginn noch gemerged werden: Baseline-Coverage-Lauf erneut ausführen, Endwert in Completion Notes aktualisieren

- [ ] **Task 9: Gesamt-Grün-Lauf**
  - [ ] 9.1 `pytest tests/ -x --cov=app --cov-report=term-missing` durchlaufen lassen
  - [ ] 9.2 Coverage-Wert >= 85 % bestätigt (Endwert in Completion Notes)
  - [ ] 9.3 Kein Skip, kein Ignore, kein roter Test

## Dev Notes

### Scope-Klarstellung

Diese Story enthält **ausschliesslich Test-Code** und `pyproject.toml`-Ergänzungen. Kein App-Code-Change. Falls ein Test eine Lücke aufdeckt, die einen App-Bug voraussetzt (nicht nur fehlende Abdeckung), ist das ein separates Deferred-Item — kein Scope-Creep in 5-7.

Items, die bewusst **out-of-scope** bleiben:
- **#42** (Cache nur `score`, nicht `per_cluster`/`weakest_fields`) — ist ein Design-Issue, kein Test-Gap. Test ist nicht möglich ohne Code-Change.
- **#97** (Stale-Proposal beim Approve) — UX-Entscheidung, kein Test-Gap.
- **#152** (HTML-ID-Eindeutigkeit) — laut `sprint-status.yaml` zu Story 5-5 (AC9) verschoben, nicht in 5-7 doppelt aufnehmen.
- #86 wird in AC8 dokumentiert, ist aber ein manuelles Smoke-Gate und nicht in der pytest-Suite.

### Coverage-Config für pyproject.toml

```toml
[tool.coverage.run]
source = ["app"]
branch = true
omit = [
    "*/tests/*",
    "*/migrations/*",
    "app/main.py",
    "app/config.py",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
precision = 2
fail_under = 85
```

Das `fail_under = 85` lässt `pytest --cov=app --cov-fail-under=85` als Gate laufen. Ohne `--cov-fail-under`-Flag im manuellen Lauf ist es informational only.

### AST-Scanner Muster (#94, #95)

```python
import ast, pathlib

AUTHORIZED_WRITERS = {"write_field_human", "write_field_ai_proposal", "approve_review_entry"}
MODEL_NAMES = {"SteckbriefObject", "obj"}  # ggf. erweitern

def _scan_direct_assigns(root: pathlib.Path) -> list[str]:
    findings = []
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        # attr-Zuweisung auf Objekt → verdächtig
                        findings.append(f"{py}:{node.lineno}")
    return findings
```

**Wichtig**: der Scanner hat bekannte False-Positives (Multi-Line, `setattr`, Variable-Shadowing — #95). Das ist akzeptiert. Test-Docstring dokumentiert das.

**Allowlist-Mechanik**: Aktuell ist `AUTHORIZED_WRITERS = {"write_field_human", "write_field_ai_proposal", "approve_review_entry"}` ein hardcoded-Set. Bei jedem Hinzufügen eines neuen legitimen Write-Pfads muss das Set angepasst werden, sonst False-Positive. **Failure-Message muss daher explizit sein**: *"Direkter Schreibzugriff auf SteckbriefObject in {file}:{lineno}. Entweder den Schreibpfad refactoren (über `write_field_human`/`write_field_ai_proposal`/`approve_review_entry`) ODER `AUTHORIZED_WRITERS` in `tests/test_write_gate_coverage_ast.py` ergänzen, falls der neue Pfad bewusst autorisiert ist."* Optional als Folge-Story: Decorator `@steckbrief_writer` einführen und der AST-Scanner liest die Decorated-Funktionen automatisch aus, statt Namen-Set zu pflegen.

### Pflegegrad-Test-Fixtures (#40, #41)

```python
def test_score_for_completely_empty_object(db, test_object):
    # kein FieldProvenance-Eintrag → Score = 0
    result = pflegegrad_score(test_object, db)
    assert result.score == 0
    assert len(result.weakest_fields) > 0  # alle gewichteten Felder sind schwach
```

Fixture `test_object` (nicht `steckbrief_object`) kommt aus `tests/conftest.py` und liefert ein frisches Objekt. Auth-Clients in conftest heissen `auth_client` (Standard-User) bzw. `steckbrief_admin_client` (alle Steckbrief-Permissions) — Story-Code-Beispiele NICHT auf erfundene Fixture-Namen wie `steckbrief_client`/`steckbrief_object` verlassen.

### SQL-Statement-Count-Test Bounds (#49, #124)

Für #49: Untergrenze auf `>= 12` setzen (empirisch aus dem bestehenden Test: ein frisches Objekt ohne Cache macht typisch 15–21 Statements; 12 ist konservativ genug um Leer-Pfade zu fangen). Kommentar im Test: `# Untergrenze 12: schützt vor versehentlich kurzgeschlossenem Query-Pfad`.

Für #124: `count_with_conf` aus dem Admin-Client-Test-Lauf ermitteln, dann `count_without_conf < count_with_conf` assertieren. Die Differenz kommt aus dem Zugangscode-Provenance-Query-Skip bei fehlendem `view_confidential`.

### Datei-Referenzen

| File | Relevante ACs |
|------|---------------|
| `pyproject.toml` | AC1, AC2 |
| `.gitignore` | AC1 (htmlcov/) |
| `tests/test_pflegegrad_unit.py` | AC3 (#40, #41) |
| `tests/test_steckbrief_routes_smoke.py` | AC4 (#47, #49, #124) |
| `tests/test_etv_signature_list.py` | AC5 (#28, #32) |
| `tests/test_review_queue_routes_smoke.py` | AC6 (#21) |
| `tests/test_registries_routes_smoke.py` | AC6 (#67) |
| `tests/test_write_gate_coverage_ast.py` | AC7 (neu, #94, #95) |
| `tests/test_wartungspflichten_routes_smoke.py` | AC8 (#74, nur Kommentar — falls vorhanden) |

### Deferred-Work-Coverage

| # | Eintrag | Severity | AC | Datei |
|---|---------|----------|----|-------|
| 21 | `test_review_queue_unauthenticated` ohne Location-Header-Check | low | AC6 | `tests/test_review_queue_routes_smoke.py` |
| 28 | Negativ-Only-Test ohne Positiv-Pendant (ETV generate) | low | AC5 | `tests/test_etv_signature_list.py` |
| 32 | 5xx vs 404 zusammengelegt (ETV generate) | low | AC5 | `tests/test_etv_signature_list.py` |
| 40 | Fehlender Test: Provenance vorhanden, Wert None | low | AC3 | `tests/test_pflegegrad_unit.py` |
| 41 | Fehlender Test: komplett leeres Objekt → Score 0 | low | AC3 | `tests/test_pflegegrad_unit.py` |
| 42 | Cache-Divergenz per_cluster/weakest_fields | low | **out-of-scope** | Design-Issue, kein Test-Gap |
| 47 | AC6 ohne dedizierten Route-Test (pflegegrad_result) | low | AC4 | `tests/test_steckbrief_routes_smoke.py` |
| 48 | AC3-Test prüft nur per_cluster, nicht Gesamt-Score | low | **bereits erledigt** (Z. 89 hat `assert result.score == 100`) — nur Verifikations-Vermerk in Completion Notes |
| 49 | Statement-Count-Threshold <= 21 nur Obergrenze | low | AC4 | `tests/test_steckbrief_routes_smoke.py` |
| 67 | Versicherer-Detail-Smoke ohne Render-Check | low | AC6 | `tests/test_registries_routes_smoke.py` |
| 74 | Spec-Doc-Wording Wartung object_id | low | AC8 | `tests/test_wartungspflichten_routes_smoke.py` (Kommentar laut Validierung evtl. bereits weg) |
| 86 | Manuelles Browser-Smoke-Gate Menschen-Notizen offen | low | AC8 | manuell |
| 94 | AST-basierter Write-Gate-Coverage-Scanner Stufe 2 | low | AC7 | `tests/test_write_gate_coverage_ast.py` (neu) |
| 95 | Coverage-Scanner-Lücken (Multi-Line, setattr etc.) | low | AC7 | `tests/test_write_gate_coverage_ast.py` (neu) |
| 97 | Stale-Proposal-Check beim Approve | low | **out-of-scope** | UX-Entscheidung |
| 124 | SQL-Statement-Count ohne Non-Confidential-Pfad | low | AC4 | `tests/test_steckbrief_routes_smoke.py` |
| ~~152~~ | ~~HTML-id-Eindeutigkeit~~ | — | **gehört zu Story 5-5 AC9**, nicht zu 5-7 (laut sprint-status.yaml verschoben) | — |

### Test-Infrastruktur (bestehend, nicht anfassen)

- `tests/conftest.py` mit `TestClient`, SQLite-in-memory, StaticPool, Fixtures für User/Object/Session
- `asyncio_mode = "auto"` in `pyproject.toml` — kein `@pytest.mark.asyncio` nötig
- SQLiteTypeCompiler-Monkey-Patch für JSONB→TEXT und UUID→CHAR(32) — bereits aktiv, keine Änderung nötig
- Timezone-Pin `TZ=Europe/Berlin` am Teststart — bereits aktiv

### Learnings aus früheren Epic-5-Stories

- **Date-Tests auf Monatsmitte fixieren** (`today.replace(day=15)`) — Memory `feedback_date_tests_pick_mid_month.md`. Gilt für alle neuen Tests die Datumslogik berühren.
- **SQLite-Kompatibilität**: Kein `DISTINCT ON`, kein `ON CONFLICT DO UPDATE` mit Returning in Tests — bestehende Patterns in conftest respektieren.
- **BackgroundTask-Tests**: DB-Session per BackgroundTask selbst öffnen, nicht die Test-Session weitergeben — für diese Story nicht relevant (kein App-Code).
- **Keine echten API-Calls**: Anthropic/Impower/Facilioo immer mocken. Für AST-Scanner (AC7) kein Mock nötig (rein statisch).

### Referenzen

- `output/planning-artifacts/epics.md` §5.7 — Basis-Story-Beschreibung
- `output/implementation-artifacts/deferred-work.md` — vollständige Item-Beschreibungen für #21/#28/#32/#40/#41/#47/#48/#49/#67/#74/#86/#94/#95/#97/#124 (#152 → Story 5-5)
- `tests/conftest.py` — Fixture-Inventar
- `docs/project-context.md` §Testing-Rules — Testkonventionen
- Memory `feedback_date_tests_pick_mid_month.md`, `feedback_migrations_check_existing.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- [ ] Baseline-Coverage-Wert vor Änderungen (Task 0.1): ____%
- [ ] End-Coverage-Wert nach allen Tests: ____%
- [ ] #48 verifiziert (`assert result.score == ...` bereits in `test_pflegegrad_unit.py` Z. 89 vorhanden): ja/nein, Datum
- [ ] #74 Wartungs-Kommentar `grep`-Verifikation: Treffer korrigiert / kein Treffer (bereits erledigt) — Datum
- [ ] Manueller Browser-Smoke #86 (Menschen-Notizen Admin/User-Sicht) durchgeklickt: ja/nein, Datum + Tester
- [ ] Re-Lauf nach 5-5/5-6-Merge erforderlich gewesen: ja/nein

### File List
