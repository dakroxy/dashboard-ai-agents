# Implementation Readiness Assessment Report

**Datum:** 2026-04-23
**Projekt:** Dashboard KI-Agenten
**Scope:** Story 1.6 — Technik-Sektion mit Inline-Edit

---

## Dokument-Inventar

| Dokument | Pfad | Status |
|----------|------|--------|
| Epics & Stories | `output/planning-artifacts/epics.md` | ✓ Gefunden |
| PRD | `output/planning-artifacts/prd.md` | ✓ Gefunden (FRs in epics.md extrahiert) |
| Architektur | `output/planning-artifacts/architecture.md` | ✓ Gefunden |
| UX-Design | — | ⚠️ Nicht vorhanden (bewusst — UI-Conventions aus project-context.md + Bestand) |
| Story-Datei | `output/implementation-artifacts/1-6-technik-sektion-mit-inline-edit.md` | ✓ Gefunden, Status: `ready-for-dev` |

**Sprint-Status:** Alle Vorgänger-Stories 1.1–1.5 `done`. Story 1.6 `ready-for-dev`.

---

## PRD-Analyse (Story-1.6-Scope)

Die vollständige FR/NFR-Extraktion ist in `epics.md` enthalten (34 FRs, Requirements Inventory-Abschnitt). Für Story 1.6 relevante Anforderungen:

### Abgedeckte FRs

| FR | Anforderung | Abdeckung in Story 1.6 |
|----|-------------|------------------------|
| FR3 | Technik-Pflege: Absperrpunkte + Foto + Standortbeschreibung, Heizungs-Steckbrief, Zugangscodes, Objekt-Historie | ✓ Absperrpunkte + Heizung + Objekt-Historie; Fotos → 1.8 (korrekt zurückgestellt); Zugangscodes → 1.7 (korrekt zurückgestellt) |
| FR21 | FieldProvenance via Write-Gate bei jedem Schreibvorgang | ✓ AC2 + Task 5.3 — ausschliesslich `write_field_human` |
| FR32 | Permission `objects:edit` zuweisbar und erzwungen | ✓ AC3 + `Depends(require_permission("objects:edit"))` auf allen 3 Endpoints |
| FR33 | Audit-Log-Eintrag für alle Schreibaktionen | ✓ Via `write_field_human` automatisch — `action="object_field_updated"` |
| FR25 | KI-Agenten können nicht direkt in Steckbrief-Felder schreiben | ✓ Nicht relevant für Story 1.6 (rein Human-Edit), aber Write-Gate-Coverage-Scanner schützt strukturell |

### Korrekt auf Folge-Stories verschobene FRs

| FR | Verschoben nach | Begründung |
|----|-----------------|------------|
| FR3 (Fotos) | Story 1.8 | SharePoint + Local-Fallback, separater Scope |
| FR10 (Zugangscodes) | Story 1.7 | Fernet-Encryption + UI gemeinsam, bewusste Scope-Trennung |

### Relevante NFRs

| NFR | Anforderung | Abdeckung |
|-----|-------------|-----------|
| NFR-S2 | Zugangscodes at-rest verschlüsselt | Scoped out (Story 1.7). TECHNIK_FIELD_KEYS enthält keine entry_code_* — strukturelle Blockade ✓ |
| NFR-S4 | Schreib-Audit atomar in einer Transaktion | ✓ write_field_human: Feld-Set + FieldProvenance + AuditLog in einer Transaktion |
| NFR-O1 | Audit-Log mit vollständigen Feldern | ✓ Via write_field_human: user_id, action, entity_type, entity_id, details_json |

---

## Epic Coverage Validation

**Story 1.6 in epics.md (Seite 471–494):** Korrekt abgebildet mit 4 ACs.

**Story-Datei vs. Epic-ACs:**

| Epic-AC | Story-Datei-AC | Bewertung |
|---------|---------------|-----------|
| Rendert mit Edit-Buttons für objects:edit | AC1 (3 Sub-Blöcke, 10 Felder, Provenance-Pill, Entry-Codes excluded) | ✓ Erweitert und präzisiert |
| Edit → write_field_human → HTMX-Swap + Pill + AuditLog | AC2 | ✓ Detailgetreu |
| Ohne objects:edit → unsichtbar + POST 403 | AC3 (erweitert: GET edit + GET view + POST alle 403) | ✓ Security-seitig vollständiger |
| Pflichtfeld leer → Validierungsmeldung | AC4 (int_year + text + empty-OK-Klarstellung) | ✓ Ausgebaut, aber s. Befunde unten |
| — (nicht in Epic) | AC5: Pflegegrad-Cache-Invalidierung | ✓ Korrekte Ergänzung (aus ID3-Architektur) |
| — (nicht in Epic) | AC6: Empty-String → NULL (bewusste Löschung) | ✓ Korrekte Ergänzung |
| — (nicht in Epic) | AC7: Tests + Regression grün | ✓ Standard-Abschluss-AC |

**Fazit Coverage:** Story 1.6 übererfüllt die Epic-ACs (7 vs. 4). Alle Epic-ACs korrekt und vollständig abgedeckt.

---

## UX Alignment Assessment

### UX-Dokument-Status

Nicht vorhanden — bewusste Entscheidung, dokumentiert in `epics.md` §UX Design Requirements:
> "Kein formelles UX-Design-Dokument im Scope vorhanden. UI-Conventions ergeben sich aus `docs/project-context.md` und dem Bestand der Plattform (Sidebar-Layout, Jinja2 + HTMX + Tailwind, Fragment-Templates mit Underscore-Prefix, Status-Pills analog zu M5)."

### UX-Alignment-Prüfung (aus Bestand)

| UX-Convention | Story 1.6 |
|---------------|-----------|
| Fragment-Templates mit `_`-Prefix | ✓ `_obj_technik.html`, `_obj_technik_field_view.html`, `_obj_technik_field_edit.html` |
| `hx-swap="outerHTML"` für Feld-Swaps | ✓ Task 7 + 8 |
| Provenance-Pills (gleiche Farben wie Stammdaten/Finanzen) | ✓ `provenance_pill` Global in AC1 explizit |
| `data-section="..."` Attribut auf Sektions-Container | ✓ Task 6 (`data-section="technik"`) |
| Edit-Button-Style: `text-xs text-sky-600` | ✓ Task 7 konsistent mit Stammdaten |
| `—` Placeholder für NULL-Felder | ✓ Task 7: `&mdash;` |
| Deutsche Labels statt snake_case | ✓ `TechnikField.label` Pflicht, explizit dokumentiert in Dev Notes |

**Keine UX-Alignment-Lücken gefunden.**

---

## Epic Quality Review — Story 1.6

### Struktur-Validierung

**User Value:** ✓ Klarer User-Nutzen ("Wissen aus Begehungen sofort dokumentieren")
**Unabhängigkeit:** ✓ Keine Forward-Abhängigkeiten; alle Abhängigkeiten (1.2, 1.3, 1.4, 1.5) sind `done`
**Story-Sizing:** ✓ Angemessen — 12 Tasks, 2–3 Entwicklertage, kein künstlicher Split nötig

### Acceptance Criteria Review

**AC1 — Rendert mit 3 Sub-Blöcken:**
- BDD: ✓ | Testbar: ✓ | Vollständig: ✓
- Scope-Boundary zu Story 1.7 explizit dokumentiert ✓

**AC2 — Edit → Save:**
- BDD: ✓ | Testbar: ✓ | Vollständig: ✓
- Atomizität (FieldProvenance + AuditLog in einer Transaktion) explizit ✓

**AC3 — Ohne objects:edit:**
- BDD: ✓ | Testbar: ✓ | Vollständig: ✓
- Erweitert gegenüber Epic (GET edit + GET view ebenfalls 403) — sicherheitstechnisch korrekt ✓

**AC4 — Validierungsfehler:**
- BDD: ✓ | Testbar: ✓
- ⚠️ Siehe Befund B3 unten

**AC5 — Pflegegrad-Cache:**
- BDD: ✓ | Testbar: ✓ | "geschenkt" via write_field_human ✓

**AC6 — Empty → NULL:**
- BDD: ✓ | Testbar: ✓ | Konsistent mit parse_technik_value ✓

**AC7 — Regression:**
- Konkret: ≥405 Tests ✓

### Dependency-Analyse

| Abhängigkeit | Status | Verifiziert |
|--------------|--------|-------------|
| Story 1.2 (write_field_human) | ✓ `done` | `app/services/steckbrief_write_gate.py:194` existiert |
| Story 1.3 (object_detail Handler) | ✓ `done` | `app/routers/objects.py` existiert |
| Story 1.4 (Migration 0012 als down_revision) | ✓ `done` | Task 1.1 prüft per `ls migrations/versions/` |
| Story 1.5 (Finanzen-Pattern als Referenz) | ✓ `done` | `_obj_finanzen.html`, get_provenance_map existieren |

**Keine Forward-Abhängigkeiten.**

### Task-Qualitäts-Check

| Task | Vollständigkeit | Anmerkung |
|------|-----------------|-----------|
| Task 1 (Migration 0013) | ✓ | ⚠️ Befund B1: "9 neue Spalten" — sind 8 |
| Task 2 (ORM) | ✓ | Korrekt "8 neue Mapped[...]" |
| Task 3 (Validator) | ✓ | TechnikField-Registry + parse_technik_value vollständig spezifiziert |
| Task 4 (Router Read) | ✓ | _build_section Helper sauber |
| Task 5 (Router Endpoints) | ✓ | Alle 3 Endpoints mit korrekter Permission |
| Task 6 (Template Sektion) | ✓ | 3 Sub-Blöcke mit data-section ✓ |
| Task 7 (View-Fragment) | ✓ | Container-ID `field-<key>` für HTMX-Target ✓ |
| Task 8 (Edit-Fragment) | ✓ | Fehler-Zweig, submitted_value, max=3000 begründet ✓ |
| Task 9 (object_detail.html) | ✓ | Minimaler Touch: ein include + Kommentar |
| Task 10 (Unit-Tests Parser) | ✓ | 10 Tests, alle Zweige abgedeckt |
| Task 11 (Route-Smoke-Tests) | ✓ | 16 Tests, alle 7 ACs abgedeckt |
| Task 12 (Regression) | ✓ | No-Op-Verhalten dokumentiert |

---

## Befunde

### 🔴 Kritische Probleme

_Keine gefunden._

### 🟠 Größere Probleme

_Keine gefunden._

### 🟡 Kleinere Befunde

**B1 — Typo: Spalten-Zählung in Task 1 (AC1, AC5)**
- Task 1 schreibt: "9 neue Spalten anlegen"
- Der `upgrade()`-Code im selben Task-Block enthält exakt 8 `op.add_column`-Aufrufe (korrekte Implementierung)
- Task 2 schreibt korrekt: "8 neue typed Mapped[...]"
- **Impact:** Dev-Agent liest "9" → sucht das 9. op.add_column → findet keines → könnte irritiert sein
- **Empfehlung:** "9 neue Spalten" → "8 neue Spalten" in Task 1 korrigieren

**B2 — Typo: "NICL" in AC4**
- AC4: "leerer Pflichtfeld-Case `value=""` darf NICL geschrieben werden"
- Sollte: "darf NICHT geschrieben werden"
- **Impact:** Minimal — Kontext macht die Intention klar
- **Empfehlung:** Typo korrigieren vor Dev-Start

**B3 — Missverständliches Einstiegs-Statement in AC4**
- AC4 beginnt: "leerer Pflichtfeld-Case `value=""` darf NICHT geschrieben werden — null zurücksetzen ist OK"
- Das klingt wie: leerer Input = verboten. Tatsächlich ist leerer Input = NULL-Schreibung (AC6), also erlaubt.
- Der klärende Text am Ende von AC4 ("In v1 gibt es keine echten Pflichtfelder in Cluster 4...") korrigiert das — aber ein Dev-Agent der AC4 oben liest könnte den falschen Validator bauen
- Der Task 3.2 spezifiziert `stripped == "" → return None, None` (korrekt) und widerspricht dem AC4-Einstieg
- **Impact:** Konfusionsrisiko für Dev-Agent: liest AC4 oben → baut "empty = error" → schlägt AC6-Test an
- **Empfehlung:** AC4 Einstieg präzisieren: "Ungültige Werte (z.B. `value='abc'` oder Jahr außerhalb [1800, current_year+1]) → Fragment mit Fehlermeldung, kein Write. Leerstring → AC6 (NULL-Schreibung, erlaubt)."

**B4 — Epics.md Typo (Story korrekt, Quelle falsch)**
- Epic-AC zu Story 1.6 (epics.md:487): `details_json.field_name == "year_roof"`
- Tatsächlicher write_field_human-Code (`steckbrief_write_gate.py:305`): `"field": field` → `details_json["field"]`
- Story 1.6 AC2 + Test 11.3 verwenden korrekt `details_json["field"]`
- **Impact:** Für Story 1.6 kein Problem (Story ist korrekt). Für künftige Stories die epics.md als Referenz lesen: werden fälschlich `field_name` suchen
- **Empfehlung:** epics.md Story 1.6 AC korrigieren: `field_name` → `field`

---

## Summary and Recommendations

### Overall Readiness Status

**✅ READY FOR DEV**

Story 1.6 ist implementierungsbereit. Alle Abhängigkeiten sind erfüllt, alle Architektur-Entscheidungspunkte sind korrekt adressiert, und die Test-Abdeckung ist umfassend.

### Kritische Aktionen vor Dev-Start (empfohlen)

1. **B3 zuerst beheben** — AC4-Einstiegs-Statement präzisieren, um Dev-Agent-Konfusion bei leerer Eingabe zu verhindern. Risiko ohne Fix: Test-Failure bei AC6 durch falsch implementierten Validator.

2. **B1 + B2 korrigieren** — Typos in Task 1 ("9" → "8") und AC4 ("NICL" → "NICHT"). Kostet 2 Minuten, reduziert Fragezeichen.

3. **B4 in epics.md** — `field_name` → `field` im Epic-AC, damit künftige Story-Autoren nicht fehlgeleitet werden.

### Empfohlene nächste Schritte

1. Befunde B1–B3 in der Story-Datei direkt fixen (2-Minuten-Änderungen)
2. Befund B4 in epics.md korrigieren
3. Dev-Agent mit `bmad-dev-story` starten → story 1.6

### Abschluss-Note

Diese Validierung hat **4 kleinere Befunde** (3× Typos/Wording in Story-Datei, 1× Typo in epics.md) identifiziert. Kein kritisches Problem, kein Implementierungsblocker.

Die Story ist architektonisch vollständig spezifiziert, alle Vorgänger sind fertig gestellt, und der Testplan deckt sämtliche 7 ACs systematisch ab.

---

_Erstellt: 2026-04-23 | Validiert gegen: epics.md, steckbrief_write_gate.py:194–317, sprint-status.yaml_
