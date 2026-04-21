---
session_topic: 'Dokumentenerkennung — Architektur-, Kosten- und Priorisierungs-Konsens fuer die vier Workflows der DBS-Plattform'
session_goals: 'Klaerung der KI-Pipeline fuer Dokumentenverarbeitung (Azure DI vs. Claude-only), Identifikation der vier Workflow-Lanes mit Anforderungen, Priorisierung + Roadmap-Skizze, Aufsatzpunkt fuer Folge-Gespraeche.'
format: 'party-mode roundtable, 5 Runden'
participants: 'Daniel Kroll + Party-Mode-Agents (Winston/Amelia/John/Mary/Sally)'
status: 'konsens-level-1'
follow_up_required: true
---

# Dokumentenerkennung — Konsens-Skizze fuer die vier Workflows

**Owner:** Daniel Kroll
**Datum:** 2026-04-21
**Format:** Party-Mode-Roundtable (5 Runden), Agenten-Perspektiven konsolidiert

---

## tl;dr

- **Die Plattform hat vier strukturell unterschiedliche Dokument-Workflows** (SEPA, Anlage MV/WEG/SEV, Objekt-Onboarding, Teilungserklaerungs-Analyse). Jeder hat eigene Volumen, Tiefe, Kosten-Profile und Write-Targets — aber alle ruhen auf einem gemeinsamen Plattform-Fundament.
- **Architektur-Muster:** Azure Document Intelligence als deterministischer Pre-Prozessor (OCR + Layout + Bounding-Boxes + Confidence) → Claude als semantischer Mapper auf strukturiertes Schema → Validator-Kette (schwifty, Datum, Betrag) → Review-Queue bei Low-Confidence. Das ist Industry-Standard (LayoutLM, Unstructured.io, Rossum) und keine experimentelle Idee.
- **Kosten:** Das gesamte 4-Workflow-System kostet geschaetzt **$780/Jahr** an KI/OCR-Gebuehren — irrelevant gegenueber Entwickler-Zeit. Der eigentliche Kosten-Hebel liegt nicht "Azure billiger als Claude", sondern "Azure + Haiku statt Claude-Opus/Sonnet-alleine", weil Azure-Vorkontext Claude auf das billigere Modell herunterzieht.
- **Priorisierung:** Phase 0 M3+M5 live-verifizieren → Phase 1 Plattform-Layer (Azure DI, Taxonomie, Confidence, Review-Queue) → Phase 2 W3 Onboarding-MVP (akuter Volumen-Pain, 30-40 Objekte/Jahr) → Phase 3 W1 Handschrift-Revision → Phase 4 Objektsteckbrief v1 → Phase 5 W2-Erweiterung → Phase 6 W4 Teilungserklaerung.
- **Evidenz-Luecke:** heute fehlt ein Eval-Framework. M5-Code ist komplett, aber nie validiert. Das muss parallel zur Plattform-Arbeit entstehen — selbstwachsend durch Production-Correction-Sammlung + Kalibrierungs-Laeufe pro Onboarding.
- **Sechs Entscheidungen stehen offen** (siehe § "Offene Fragen"), insbesondere: Impower-DMS-API-Existenz fuer Tagging und Objektsteckbrief v1-Spec-Fertigstellung.

---

## 1. Ausgangslage

Die Plattform verarbeitet heute Dokumente mit **Claude direkt** (PDF → `messages.create` mit Vision). Zwei Workflows sind in Produktion (SEPA-Mandat M1-M3, Mietverwaltungs-Anlage M5 — M5 noch nicht live verifiziert). Die Session startete mit der Frage "gibt es bessere Modelle / kann der Workflow optimiert werden?" und entwickelte sich ueber fuenf Runden zu einer vollstaendigen Plattform-Architektur-Skizze fuer vier Workflows.

**Zentrale Einsichten, die sich ueber die Session herauskristallisiert haben:**

1. **Modell-Swap allein ist der falsche Hebel** — Tool-Use-Schema + Validator-Retry-Loop + Prompt-Caching wirken staerker als Modell-Upgrade allein.
2. **Spezialisierter OCR-Service (Azure DI) als Pre-Prozessor vor LLM** ist Industry-Standard, entkoppelt deterministische Text-Extraktion von semantischer Interpretation.
3. **Kostenoptimierung ist bei aktuellem Volumen (<400 Docs/Monat) Nebenschauplatz** — wird erst bei W3 (30-40 Onboardings/Jahr × 500-2000 Docs) wirklich relevant.
4. **Vier Workflows brauchen gemeinsames Plattform-Fundament**, sonst baut sich ein 1-Entwickler-Team in Silos-Schulden.
5. **Evidenz/Eval-Infrastruktur fehlt komplett heute** — ohne diese sind alle Modell- und Prompt-Entscheidungen Bauchgefuehl.

---

## 2. Die vier Workflows

| # | Name | Kurzbeschreibung | Heute | Volumen/Jahr | Tiefe | Write-Target |
|---|------|------------------|-------|--------------|-------|--------------|
| W1 | **SEPA-Lastschriftmandat** | Einzelnes Mandat → Impower-Mandat-Anlage | M1-M3 live (Idempotenz ok, Neuanlage-Zweig offen) | ~500-1500 (Schaetzung offen) | flach (5 Felder) | Impower SEPA-Create |
| W2 | **Anlage MV/WEG/SEV** | Multi-Doc-Case (Verwaltervertrag + Grundbuch + Mieterliste + Mietvertraege) → Impower-Setup | M5 komplett, Live-Tests offen | ~30-40 Cases | mittel (7 Sektionen, 200+ Felder) | Impower Setup + Objektsteckbrief |
| W3 | **Objekt-Onboarding (DMS-Tagging)** | Aktenberg einer uebernommenen WEG → automatisch taggen + ablegen | **komplett neu** | ~15k-80k Docs (30-40 Objekte × ~10 Ordner × 50-200 Docs) | nur Tag + Ablage | Impower DMS |
| W4 | **Teilungserklaerungs-Tiefenanalyse** | 20-50-seitiges juristisches Volldokument → strukturierte Extraktion | **komplett neu** | ~30-40 Docs | sehr tief (Miteigentumsanteile, Sondereigentum, Dienstbarkeiten) | Objektsteckbrief |

### 2.1 Workflow 1 — SEPA-Lastschriftmandat

**Bestehend aus M1-M3.** Der Neuanlage-Zweig (PUT Contact mit neuem Bank-Account + POST Mandat + POST UCM-Array) ist noch nicht live verifiziert (Tilker GVE1 / Kulessa BRE11 stehen als Test-Faelle an).

**Neuer Aspekt aus der Session:** Daniel hat klargestellt, dass SEPA-Mandate **meist handgeschriebene Seiten** sind. Das revidiert die Runde-3-Empfehlung, W1 bei reinem Claude-Claude-Pfad zu belassen. Handschrift ist empirisch Domaene von OCR-Spezialisten (FUNSD/CORD-1k-Benchmarks zeigen 5-15 Prozentpunkte Vorsprung vor generischen LLMs bei Handschrift). Azure DI Read ist hier Pflicht, nicht Option.

**Revidierte Pipeline:** Azure Read (Handschrift-gehaertet) + Claude Haiku (Mapping auf 5 Felder, billig) + schwifty/NFKC-Validator (bereits vorhanden).

### 2.2 Workflow 2 — Anlage MV / WEG / SEV

**Bestehend aus M5 (`mietverwaltung_setup`).** Heute ist das ein Spezialfall fuer Mietverwaltung. WEG-Verwaltung und SEV (Sondereigentumsverwaltung) haben **andere Impower-Setup-Schritte**, aber aehnliche Multi-Doc-Struktur.

**Architektur-Entscheidung (Konsens):** Das ist **ein Workflow mit drei Varianten**, nicht drei separate Workflows. Generalisierung ueber `Case.object_type` als Enum (`RENTAL | WEG | SEV`) mit bedingten Write-Pipelines.

**Erweiterung (neu):** Teile des Objektsteckbriefs ausfuellen (Stammdaten, Eigentuemer, Einheiten, Verwalter). Das macht Objektsteckbrief v1 zum **Gatekeeper** fuer diese Phase.

### 2.3 Workflow 3 — Objekt-Onboarding (NEU)

Bei Uebernahme einer neuen WEG kommen hunderte bis tausende Dokumente auf einmal — **2026 sind 30-40 Onboardings geplant**, je ~10 Ordner, geschaetzt 500-2000 Docs pro Objekt. Aufgabe: Klassifikation gegen Impower-Tag-Taxonomie (9 Gruppen, ~80 Subkategorien) + Ablage + DMS-Tagging.

**Architektur-Muster:** Dreistufig.

```
┌─ Stage 1: TRIAGE (Batch, Nacht-Job) ──────────────────────┐
│  Azure Read (Seite 1) → Claude Haiku Stage A (9 Gruppen)  │
│                      → Claude Haiku Stage B (Subkategorie)│
│                      → Tag(s) + Confidence                │
└────────────────────────────────────────────────────────────┘
                        │
                        ▼  (~20-30% der Docs, kritische Tags)
┌─ Stage 2: EXTRACTION (on-demand, pro Doc-Klick) ──────────┐
│  Azure Layout (alle Seiten) → Claude Mapper → Validator    │
└────────────────────────────────────────────────────────────┘
                        │
                        ▼  (Low-Confidence oder Pflicht-Review-Tags)
┌─ Stage 3: REVIEW-QUEUE (User-intensiv) ───────────────────┐
│  HTMX-Liste, sortiert nach Confidence, Bulk-Approve        │
└────────────────────────────────────────────────────────────┘
```

**Begruendung fuer Triage-Pattern:** Naiver Ansatz (alles durch Opus/Vollanalyse) kostet ca. **$300-500 pro Onboarding**. Triage-First (erste Seite Azure Read + Haiku-Klassifikation + gezielte Extraktion der 20-30% kritischen Docs) kostet **~$35-55 pro Onboarding**. Faktor 10x.

**Der Kostenhebel ist aber nicht primaer Geld** (bei 30-40 Onboardings = ~$1400-2200/Jahr irrelevant gegen Entwicklerzeit), **sondern Performance/Throughput** — sonst laeuft der Batch bei 1000 Docs mit Opus-Vollanalyse Tage, mit Triage-Pattern ueber Nacht.

### 2.4 Workflow 4 — Teilungserklaerungs-Analyse (NEU)

Vollstaendiges juristisches Dokument (20-50 Seiten) mit komplexer Struktur: Miteigentumsanteile, Sondereigentum, Sondernutzungsrechte, Dienstbarkeiten, Gebaeude-Struktur, Grundbuchblatt-Referenzen.

**Pipeline:** Azure Layout (vollstaendige Seiten) + Claude Sonnet oder Opus (strukturierte Extraktion, Tool-Use mit Pydantic-Schema) → Objektsteckbrief-Write.

**Volumen-Realitaet:** ~30-40/Jahr (1 pro Uebernahme). Bei 30-60 Min manueller Extraktion pro Dokument = 15-40 Stunden/Jahr Aufwand. Entwicklungsaufwand ~5 Tage = 40 Stunden. **Break-even erst im zweiten Jahr.** Das ist einer der Gruende, warum W4 in der Priorisierung den letzten Platz einnimmt.

---

## 3. Architektur-Konsens

### 3.1 Gemeinsames Plattform-Fundament

Sieben Services, die alle Workflows nutzen:

```
app/services/
  azure_di.py           # Azure Document Intelligence Wrapper (Read | Layout)
  claude.py             # bestehend, refactor auf mapper-pattern
  taxonomy.py           # Impower-Tag-Registry, DB-gepflegt, versioniert
  confidence.py         # Worst-of-Components-Score + Thresholds
  impower.py            # bestehend, erweitert um DMS-Tag-Write (falls API vorhanden)
  objektsteckbrief.py   # NEU: zentraler Writer, Querschnitt W2+W4
  chat.py               # bestehend (Delta-Patch-Chat, ueber alle Workflows)
```

### 3.2 Workflow-spezifische Module

```
app/workflows/
  sepa/                 # W1, generalisiert aus bestehenden claude.py + impower.py
  object_setup/         # W2, generalisiert aus mietverwaltung_setup
  onboarding/           # W3, komplett neu
  teilungserklaerung/   # W4, komplett neu
```

Breaking-Rename von `app/services/mietverwaltung*.py` nach `app/workflows/object_setup/` — separater Commit, keine Logik-Aenderung, dann bedingte MV/WEG/SEV-Pipelines dazu.

### 3.3 Preprocessor-Pattern (Azure DI → Claude-Mapper)

**Daniels Kern-Idee aus Runde 3:** Azure extrahiert deterministisch (OCR + Layout + Bounding-Boxes + Confidence), Claude ordnet semantisch zu ("Text 'Eigentuemer:' links vom Namen → das ist das Eigentuemer-Feld"). **Das ist Separation of Concerns** — OCR ist deterministische Computer-Vision, semantisches Mapping ist Sprachverstaendnis. Beide werden auf ihre Kernkompetenz eingesetzt.

**Vorteile:**
- Ziffern-Drift (Haiku verliert letzte IBAN-Ziffer, Sonnet schmuggelt Zero-Width-Spaces) wird strukturell entschaerft — Claude referenziert Ziffern aus Azure's deterministischem Output, reproduziert sie nicht selbst.
- Tabellen-Parsing (Mieterliste 40 Zeilen × 8 Spalten) wird fuer Azure-DI zum Sweet-Spot, nicht zur LLM-Halluzinationsquelle.
- Handschrift-Robustheit steigt deutlich (Azure's dediziertes Handschrift-Modell vs. Claude-Vision).
- Bounding-Boxes ermoeglichen UX-Feature "zeig mir wo im PDF der Wert herkommt" (Phase 2).

**Nachteile (ehrlich benannt):**
- Zweit-Provider-Ops dauerhaft (Azure-Subscription, Secrets, AVV, Monitoring) — ~2-3 h/Monat Overhead.
- Latenz: Azure-Polling addiert 3-15s pro Dokument zu Claude-Zeit (bei Batch egal, bei Single-Upload-UX spuerbar → Progress-Indicator noetig).
- Zweiter SPOF: Fallback-Pfad "wenn Azure 503 → Claude-only mit Warning" muss mitgebaut werden.
- Fehler-Diagnose komplexer (Azure-OCR vs. JSON-Uebergabe vs. Claude-Mapping).

### 3.4 Objektsteckbrief als Shared Destination

**Wichtige neue Erkenntnis:** W2 und W4 schreiben beide in denselben Objektsteckbrief. W2 liefert Stammdaten, Eigentuemer-Liste, Einheiten-Liste. W4 liefert Miteigentumsanteile, Sondereigentum, Grundbuch-Referenzen.

**Konsequenz fuer das Datenmodell:**
- Objektsteckbrief-Felder sind **optional + quellen-markiert** (`source: "w2" | "w4" | "manual"`)
- Jede Schreiboperation updatet nur die Felder, die der Workflow tatsaechlich befuellt
- Das `_overrides`-Pattern aus M5 wird wiederverwendet — manuelle User-Korrekturen haben Vorrang
- **Cross-Workflow-Konsistenz-Check:** Wenn W2 und W4 dasselbe Feld liefern (z.B. "Anzahl Einheiten"), muessen sie uebereinstimmen. Differenz = Bug.

### 3.5 Multi-Label als Default

Ein Versicherungs-Rechnung traegt zwei Tags (`20 Versicherungen/Wohngebaeude` + `80 Buchhaltung/Rechnung`). Ein Beschluss-Protokoll auch (`60 Beschluesse/Verwalter-Bestellung` + `70 Eigentuemer+Mieter/Eigentuemerliste`). Datenmodell: Join-Tabelle `document_tags(document_id, tag_id, confidence, source: 'ai'|'user')`. Prompt-Schema returnt Array statt Einzelwert.

### 3.6 Confidence-Architektur

Drei-Ebenen-Score mit Worst-of-Komposition:

| Ebene | Quelle | Komposition |
|---|---|---|
| **OCR-Confidence** | Azure Read per-token | Aggregiere zu Page-Level (avg) + Field-Level (min im Bounding-Box) |
| **Klassifikations-Confidence** | Claude self-reported im Tool-Schema; optional 3x-Sample bei Low-Conf | Bei <70% self-reported → Self-Consistency-Check auslosen |
| **Feld-Confidence** | Claude self-reported + Validator (schwifty, Datum, Betrag) | Validator-Fail clampt hart auf 0.4, sonst worst(OCR, Claude) |
| **Dokument-Confidence** | worst-of(Klassifikation, alle Felder) | Fuer Threshold-Entscheidung |

**Thresholds** (kalibrierbar, nicht hardcoded):
- `≥ 0.9` → auto-filed, kein User-Touch
- `0.7 - 0.9` → auto-filed mit sichtbarer Warnung
- `< 0.7` → Review-Queue, blockiert Weiterverarbeitung

**Wichtig:** Claude-Confidence ist nicht perfekt kalibriert, Modell eher ueberkonfident. Deshalb **Kalibrierungs-Lauf pro Kunde**: erste N (z.B. 50-100) Docs eines Onboardings komplett durch User-Review, Claude-Confidence vs. User-Korrektur loggen, Threshold empirisch nachjustieren. Ohne Kalibrierung sind Auto-Filing-Zahlen bestenfalls Hausnummer.

---

## 4. Modell- und Service-Auswahl

### 4.1 Verfuegbare Modelle (Stand 2026-04)

- **Claude Opus 4.7** — $15/M input, $75/M output — strongest reasoning, tief juristisch
- **Claude Sonnet 4.6** — $3/M input, $15/M output — Sweet-Spot fuer strukturelle Extraktion
- **Claude Haiku 4.5** — $1/M input, $5/M output — billig, aber verliert Ziffern in freier Ausgabe (bekanntes Memory-Findung)
- **Azure DI Read** — $1.50/1000 pages — reiner OCR mit Handschrift-Support
- **Azure DI Layout** — $10/1000 pages — OCR + Tabellen + Bounding-Boxes
- **Azure DI Custom** — $50/1000 pages training + $10/1000 inference — nicht MVP

### 4.2 Default pro Workflow

| Workflow-Key | Azure-Modus | Extract-Modell | Chat-Modell | Begruendung |
|---|---|---|---|---|
| `sepa_mandate` | Read (1-2 S.) | Haiku (Handschrift: Sonnet-Fallback) | Sonnet | Handschrift, wenige Felder |
| `object_setup` | Layout | Sonnet | Sonnet | Multi-Doc, mittlere Tiefe |
| `onboarding_triage` | Read (1 S.) | Haiku | — | Massen, flache Klassifikation |
| `onboarding_extract_generic` | Layout | Haiku | — | Gezielte Felder auf kritischen Tags |
| `teilungserklaerung` | Layout (alle S.) | Sonnet (Opus A/B-Test) | Sonnet | Juristisches Volldokument |

Defaults sind DB-Config (`workflows.model`, `workflows.chat_model`), daher ohne Deployment editierbar.

### 4.3 Alternative Provider — bewusst nicht verfolgt

Evaluiert, aber bewusst nicht im MVP:
- **Google Document AI** — vergleichbare Layout-Leistung, aber Google-AVV-Prozess waere zusaetzlicher Aufwand neben bereits geklaertem Anthropic-AVV.
- **Mindee / Rossum / Klippa** — purpose-built fuer Formular-Extraktion, teils besser bei Invoices (spaetere Nebenkosten-Workflows). Evaluieren wenn Rechnungs-Workflow scharf wird.
- **Open-Source (LayoutLMv3, Donut, Unstructured.io)** — DSGVO-perfekt, aber Infrastruktur-Aufwand fuer einen Solo-Entwickler nicht realistisch.
- **AWS Textract** — US-zentriert, fuer DE-Kontext schwaecher.

**Leitlinie:** Ein Provider bleibt Default (Anthropic + Azure fuer OCR). Provider-Diversifizierung ist Thema ab M8+, wenn externe Kunden es fordern.

---

## 5. Kosten-Landschaft

### 5.1 Pro-Flow-Rechnung

| Flow | Claude Opus | Claude Sonnet | Claude Haiku | Azure Layout | **Azure + Haiku** |
|------|---:|---:|---:|---:|---:|
| SEPA-Mandat (2 S.) | $0.11 | $0.022 | $0.0075 | $0.02 | **$0.0275** |
| Mietverwaltungs-Case (~50 S.) | $4.13 | $0.83 | $0.28 | $0.50 | **$0.78** |
| Teilungserklaerung (~50 S.) | $3.00 | $0.60 | $0.20 | $0.50 | **$0.70** |

**Zwei interpretative Befunde:**
1. Bei kleinen Docs (SEPA) ist **Haiku-solo sogar billiger** als Azure+Haiku — der Grund fuer Azure ist hier Robustheit (Handschrift, Ziffern-Determinismus), nicht Kosten.
2. Bei grossen Docs (Teilungserklaerung) ist Azure+Haiku **Faktor 4 billiger** als Opus-solo und etwa gleich wie Sonnet-solo. Dort wird der Kostenhebel real, aber nicht bahnbrechend (bei 30-40 Docs/Jahr).

### 5.2 Jahres-Hochrechnung fuer das 4-Workflow-System

| # | Workflow | Volumen/Jahr | Pipeline | Kosten/Jahr |
|---|----------|---|---|---|
| W1 | SEPA ~500 × 2 Seiten | 500 Docs | Azure Read + Haiku | ~$15 |
| W2 | Object-Setup 30-40 × ~50 Docs | ~1.750 Docs | Azure Layout + Sonnet | ~$250 |
| W3a | Onboarding Triage | ~30k Docs | Azure Read + Haiku | ~$105 |
| W3b | Onboarding gezielte Extraktion (20%) | ~6k Docs | Azure Layout + Haiku | ~$380 |
| W4 | Teilungserklaerung 40 × ~35 Seiten | 40 Docs | Azure Layout + Sonnet | ~$30 |
| | **Total** | | | **~$780/Jahr** |

**$780/Jahr ist irrelevant** gegen Entwickler-Stunden. Der wichtigere Metrik-Raum ist:
- Qualitaet pro Extrahiertes-Feld (False-Positive-Rate, Korrektur-Rate durch User)
- Onboarding-Tage pro Objekt (Throughput)
- Automatisierungs-Anteil (wie viele Docs landen ohne User-Touch korrekt in Impower)

### 5.3 Break-even-Rechnung W4 Teilungserklaerung (John's Punkt)

- Manuelle Extraktion: 30-40 Docs/Jahr × 30-60 Min = **15-40 Stunden/Jahr**
- Entwicklungsaufwand: ~5 Tage = ~40 Stunden
- **Break-even frueheste im zweiten Jahr** — im ersten Jahr kostet Entwicklung mehr als manuelle Arbeit einsparen wuerde.
- → **W4 ist nice-to-have, kein Must-have 2026.**

---

## 6. Evidenz- und Eval-Strategie

### 6.1 Der blinde Fleck heute

- M5 ist Code, aber nicht validiert. Kein Live-Test durchgelaufen.
- M3 Neuanlage-Zweig ist Code, aber nicht live-getestet.
- **Kein systematisches Eval-Set.** Die 3 bekannten SEPA-PDFs (Floegel, Tilker, Kulessa) sind Anekdoten, kein Eval-Set.
- **Keine Handschrift-Fixtures** — obwohl W1 explizit Handschrift-Case ist.
- Keine Production-Telemetrie darueber, wie oft User im Chat korrigieren, welche Felder, wie oft Guards schlagen.

Ohne diese Infrastruktur sind alle Modell- und Prompt-Entscheidungen Bauchgefuehl.

### 6.2 Workflow-spezifische Metriken

| Workflow | Primaer-Metrik | Ground-Truth-Set | Special-Cases | Annotations-Aufwand |
|---|---|---|---|---|
| **W1 SEPA** | Field-Accuracy pro Feld (IBAN, Name, Objekt, Glaeubiger-ID) | 20 PDFs: 10 gedruckt + 10 handgeschrieben | Handschrift-Varianten, IBAN-Drift via Zero-Width-Spaces | 5-8 h |
| **W2 MV/WEG/SEV** | Multi-Doc-Merge-Accuracy ueber 200+ Felder | 5 komplette Cases (~50 Docs) | Mieterliste-Vollstaendigkeit (320 Zellen), Feld-Cross-Refs | 10-15 h |
| **W3 Onboarding** | Klassifikations-Accuracy + Confusion-Matrix + Recall | 200 Docs, Cross-Section aller 9 Taxonomie-Gruppen | Multi-Label, OCR-Failures, "nicht lesbar"-Gruppe | 20-30 h |
| **W4 Teilungserklaerung** | Strukturierte Extraktions-Accuracy | 5-10 annotierte Teilungserklaerungen | Tabellen-Parsing, Miteigentumsanteile, Sondernutzungsrechte | 15-25 h |

**Gesamt-Annotations-Aufwand: 50-80 Stunden** — einmalig, ueber mehrere Wochen in Tages-Happen streubar. Zahlt sich bei jedem Modell-Swap und Prompt-Aenderung zurueck.

### 6.3 Gemeinsames Eval-Rueckgrat

```
tests/
  fixtures/eval/
    sepa/
      *.pdf
      *.expected.json
    object_setup/
    onboarding/
    teilungserklaerung/
  eval_harness.py   # generisches Framework, laeuft Workflow × Fixture-Set
```

**CI-Integration:** Bei jedem Modell-Swap oder Prompt-Aenderung laeuft `eval_harness.py`, bricht bei Regression ab.

**Metriken-Dashboard** (simpel, HTML-Export): Zeitverlauf pro Workflow, welche Commits haben welche Scores bewegt.

### 6.4 Selbstwachsendes Eval-Set (Production-Corrections)

Jede User-Korrektur in Production (Chat-Korrektur, Review-Queue-Override, Feld-Edit) ist ein Evidenz-Signal. Neue Tabelle:

```sql
CREATE TABLE production_corrections (
  id SERIAL PRIMARY KEY,
  workflow_key TEXT NOT NULL,
  document_id INT REFERENCES documents(id),
  field_path TEXT NOT NULL,
  original_ai_value JSONB,
  user_corrected_value JSONB,
  corrected_by INT REFERENCES users(id),
  corrected_at TIMESTAMPTZ DEFAULT now()
);
```

Periodisch (alle 2-4 Wochen) werden Eintraege ins Eval-Set migriert — wachsende Ground-Truth-Basis ohne zusaetzlichen Annotations-Aufwand.

### 6.5 Kalibrierungs-Modus pro Onboarding

Die ersten N Dokumente (z.B. N=50) jedes neuen Objekt-Onboardings laufen durch **komplettes User-Review** — unabhaengig von Confidence. Das erzeugt ein **kundenspezifisches Eval-Set** und erlaubt empirische Threshold-Kalibrierung pro Kunde. Nebennutzen: das Eval-Set waechst automatisch mit jedem neuen Kunden.

### 6.6 Cross-Workflow-Konsistenz

W2 und W4 schreiben beide in den Objektsteckbrief. Automatisch pruefbar: Wenn beide Pipelines denselben Wert liefern, muss er uebereinstimmen (z.B. "Anzahl Einheiten"). Differenz → Bug-Alert, nicht silent fix.

---

## 7. UX-Prinzipien

### 7.1 Confidence-Kommunikation

- **Pills pro Feld:** Farbton gruen/gelb/rot, Prozent-Zahl. Tooltip mit Microcopy: *"95% Confidence bedeutet: die KI sieht den Text klar. Es bedeutet nicht: der Tag ist definitiv richtig."* Trust-Kalibrierung via Microcopy.
- **Partielle Analyse markieren:** Wenn nur erste Seite analysiert wurde (bei Teilungserklaerung): kleines Badge *"📄 Analysiert: Seite 1 von 24"*. Sonst falsches Vertrauen.
- **OCR-Failure ≠ Low-Confidence:** "Kann ich nicht lesen" ist eigene Gruppe, nicht Low-Conf-Unterklasse. Unterschiedliches User-Verhalten.

### 7.2 Onboarding-Cockpit (W3, Sally's Pitch)

Cockpit-Dashboard statt 1000-Zeilen-Tabelle. In 2 Sekunden lesbar:

- **Gesundheits-Donut:** `847 gruen / 103 gelb / 50 rot / 27 grau (OCR)`
- **Haupt-CTA:** *"Du musst heute 77 Dokumente anschauen"* (nicht 1247)
- **Tag-Cluster-Karten:** 9 Karten pro Top-Gruppe mit Anzahl, durchschnittlicher Confidence, Review-Bedarf
- **Pflicht-Review-Sektion:** Tags wie Teilungserklaerung, Verwaltervertrag, Kaufvertrag, Beschluesse mit Schloss-Badge — **immer manueller Review, egal wie hoch Confidence**. Haftungsschutz.

### 7.3 Bulk-Approve mit Stichproben-Hygiene

Fuer homogene Hoch-Confidence-Cluster (>50 Docs, >90% avg): Bulk-Approve-Button, aber Modal zeigt Tag-Verteilung und fordert bei Varianz 2-3 Stichproben-Klicks. Schutz gegen Bulk-Killing einer Gutschrift zwischen 500 Rechnungen.

### 7.4 Progressive Disclosure

Default zeigt nur Low/Medium-Confidence. 90%+ ist ausgeblendet mit Counter. Klick zeigt auch die erledigten. Default = Aufmerksamkeits-Allokation.

### 7.5 Feedback-Micro-Moment

Bei User-Korrektur: kleines "Danke. KI lernt mit." unten rechts. Gefuehlter Feedback-Loop ist zentral fuer Sorgfalt, auch wenn Learning initially nur in Threshold-Nachkalibrierung landet.

### 7.6 UX-Phasierung (orthogonal zum Backend)

- **Phase 1:** Confidence-Pills pro Feld, Cockpit-Donut, Tag-Cluster, Bulk-Approve. 80% UX-Gewinn fuer 20% Aufwand.
- **Phase 2:** PDF-Overlay-Viewer (Bounding-Box-Highlight, click-to-source). Separater Frontend-Scope mit PDF.js.
- **Phase 3:** Vertrauens-Kalibrierungs-Widget ("Letzte 3 Onboardings: 94% korrekt"). Smart-Suggestions (Duplikat-Erkennung).

---

## 8. Priorisierung und Roadmap

### 8.1 Konsens-Reihenfolge

| Phase | Zeitbox | Inhalt | Begruendung |
|---|---|---|---|
| **0** | 1-2 Wochen | M3 Neuanlage-Zweig live verifizieren + M5 Live-Tests + Fixes | Halbe Features = null Wert. Abschliessen vor Neuanlauf. |
| **1** | 2-3 Wochen | Plattform-Layer: Azure DI, Taxonomie, Confidence-Scoring, Review-Queue, Eval-Harness | Fundament fuer Phasen 2-6. Einmaliger Invest. |
| **2** | 3-4 Wochen | **W3 Onboarding MVP** — Triage, Bulk-Upload, DMS-Tag-Write, Cockpit-UI | Akuter Volumen-Pain, 30-40 Objekte/Jahr. Strategie-kritisch. |
| **3** | 1 Woche | W1 Handschrift-Revision — Azure Read vor W1-Pipeline | Klein, entschaerft bekanntes Problem, Doppelnutzung des Azure-Layers. |
| **4** | 2-3 Wochen | Objektsteckbrief v1 Implementation | Gatekeeper fuer Phase 5 und 6. |
| **5** | 1-2 Wochen | W2-Erweiterung: MV/WEG/SEV-Generalisierung + Objektsteckbrief-Integration | Abhaengig von Phase 4. |
| **6** | 2-3 Wochen | W4 Teilungserklaerungs-Volldokument-Analyse → Objektsteckbrief | Niedrigstes Volumen, Break-even Jahr 2, daher zuletzt. |

**Gesamt-Zeitbox:** 12-18 Kalenderwochen bei Daniels 50% Entwicklungs-Zeit — realistisch ist das der Horizont **bis Ende 2026**.

### 8.2 Scope-Aufweichung fuer 2026

- **Must-have 2026:** M3 live, M5 live, W3 MVP, W1 Handschrift-Revision
- **Should-have 2026:** Objektsteckbrief v1, W2-Erweiterung
- **Nice-to-have (kann 2027):** W4 Teilungserklaerung

### 8.3 Commit-Granularitaet (Amelia's Vorschlag, revidiert)

```
Phase 0 — bestehendes abschliessen                          2.5d
  A-1 Live-Test M3 Neuanlage (Tilker/Kulessa)              0.5d
  A-2 Live-Test M5 inkl. Exchange-Plan                     1.0d
  A-3 M5-Fixups aus Live-Test                              1.0d

Phase 1 — Plattform-Fundament                               4.5d
  B-1 feat(azure-di): read+layout wrappers + secret        1.0d
  B-2 feat(taxonomy): impower_tags schema + yaml seed      0.5d
  B-3 feat(confidence): scoring + thresholds               1.0d
  B-4 refactor(workflows): app/workflows/* modul-split     1.0d
  B-5 test(platform): fixtures + offline mocks             1.0d

Phase 2 — W3 Onboarding MVP                                10.0d
  C-1 feat(onboarding): triage two-stage classifier        1.5d
  C-2 feat(onboarding): bulk-upload + jobs + worker        2.0d
  C-3 feat(onboarding): review-queue route                 1.0d
  C-4 feat(onboarding): impower dms-tag-write              1.5d  (abh. API-Check)
  C-5 ui(onboarding): cockpit + tag-cluster + bulk         2.5d
  C-6 test(onboarding): e2e fixtures 50 mixed docs         1.5d

Phase 3 — SEPA-Revision (Handschrift)                       1.5d
Phase 4 — Objektsteckbrief v1                             5-10d   (eigenes Epic)
Phase 5 — W2-Erweiterung                                    3.5d
Phase 6 — W4 Teilungserklaerung                             4.0d

Grand Total: 31-36 Entwickler-Tage + Buffer
```

### 8.4 Halt-Punkt nach Phase 2

Nach Phase 2 (W3 MVP live) **bewusster Review-Punkt:**
- Hat W3 funktioniert?
- Was ist der tatsaechliche Pain jetzt?
- Erst dann Phasen 3-6 final priorisieren — nicht jetzt in einem 36-Tage-Masterplan festbetonieren.

---

## 9. Offene Fragen / Blocker

Sechs konkrete Entscheidungen, die Daniel treffen bzw. klaeren muss, bevor Phase 2 scharf geht:

| # | Frage | Warum wichtig | Effort zur Klaerung |
|---|---|---|---|
| 1 | **Impower-DMS-Tag-API existiert?** | Ohne API bleibt W3 halbe Loesung (Tags nur in unserer DB). | 30 Min Swagger-Check (beide Specs ohne Auth abrufbar) |
| 2 | **Objektsteckbrief v1 Spec fertig?** | Gatekeeper fuer Phase 4 und damit W2-Erweiterung + W4. | Daniels Planungsartefakte review |
| 3 | **Wann naechstes Onboarding konkret?** | Bestimmt Deadline-Druck fuer W3. Erstes Onboarding laeuft voraussichtlich noch manuell. | DBS-interner Check |
| 4 | **SEPA-Volumen heute real: 500 oder 1500/Jahr?** | Prio fuer W1-Handschrift-Revision. | DB-Query |
| 5 | **Taxonomie-Stabilisierung** — Daniel sagt "werden wir noch ueberarbeiten". | Wenn Taxonomie kippt, Refactor-Welle durch Prompts + Evals. | Mit DBS-Team durchsprechen vor Phase 1 |
| 6 | **Lohnt sich W4 wirklich 2026?** | Break-even erst Jahr 2. Kann auch 2027 rutschen. | Strategie-Entscheidung — Datenqualitaets-Wert im Objektsteckbrief vs. Entwickler-Zeit-Opportunitaet |

---

## 10. Risiken

### 10.1 Technische Risiken

- **Zweit-Provider-SPOF (Azure + Anthropic):** Fallback-Strategie "wenn Azure 503 → Claude-only mit Warnung" muss in Phase 1 Commit B-1 mit.
- **Azure-Latenz:** 3-15s Polling addiert zu Claude-Zeit. Bei Batch (W3) egal, bei Single-Upload-UX (W1, W2) Progress-Indicator noetig.
- **Mocking in Tests:** Azure-SDK ist polling-basiert und aufwendiger zu mocken als Anthropic-SDK. `AzureDIClient`-Interface-Wrapper + `FakeAzureDIClient` fuer Tests in Phase 1.
- **Peak-Load bei W3:** 30-40 Objekt-Uebernahmen nicht gleichmaessig verteilt. Wenn 4 Objekte parallel starten = 10k+ Docs gleichzeitig. `asyncio.Semaphore(10)` gegen Azure-Rate-Limit, BackgroundTask mit `jobs`-Tabelle fuer Progress-Tracking.
- **Azure-OCR-Fehler bei sehr schlechten Scans:** Fallback-Pfad auf direkter Claude-Vision bei Azure-Confidence <0.6.

### 10.2 Architektur-Risiken

- **Taxonomie-Drift:** Impower-Tag-Taxonomie wird sich aendern. Versionierung in DB-Tabelle `impower_tags(version, active)`, pro-Dokument-Speicherung welche Taxonomie-Version zur Klassifikations-Zeit aktiv war.
- **Objektsteckbrief-Schema-Drift:** Wenn Schema nach W2-Erweiterung kippt, muessen Migrations-Pfade her. `objektsteckbrief.schema_version`-Feld pro Instanz.
- **Multi-Label-Konflikte:** Stage A und Stage B widersprechen sich → Low-Confidence-Flag + Review-Queue (nicht automatisch reparieren).
- **Confidence-Ueberkonfidenz:** Claude schaetzt sich zu sicher ein. Kalibrierungs-Lauf pro Kunde + Threshold-Nachjustierung dagegen.

### 10.3 Produkt- und Scope-Risiken

- **"Alle vier Workflows parallel" ist unmoeglich** fuer Solo-Entwickler. Phasen-Disziplin einhalten, sonst landet alles halbfertig.
- **Scope-Creep durch neue Doc-Typen:** Wenn waehrend Phase 2 weitere Workflow-Ideen kommen (z.B. Rechnungen, Versicherungspolicen, Wartungsprotokolle), diese erstmal in Backlog parken, nicht einbauen.
- **M3/M5-Live-Test-Verzoegerung:** Phase 0 kann laenger dauern als 2 Wochen, wenn M5 Exchange-Plan-Schema beim ersten Write kippt. Das waere ein Re-Design-Impulse, nicht ein Bug-Fix.

### 10.4 Geschaefts-Risiken

- **Onboarding-Aufkommen stimmt nicht mit Plan:** 30-40 ist eine Plan-Zahl. Wenn's nur 15 werden, hat W3 weniger ROI. Wenn's 80 werden, muss W3 ernsthaft Peak-Load ertragen. Regelmaessig mit DBS-Geschaeft abgleichen.
- **Impower-API-Aenderungen:** Impower hat die Write-API schon ueberraschend umgestellt (Memory `project_impower_bank_account_flow.md`). Weitere Aenderungen moeglich, unsere Integration bleibt fragil.

---

## 11. Konsens-Entscheidungen aus der Session

1. **Azure DI + Claude-Mapper-Pattern als Default-Pipeline** fuer alle Workflows. Azure extrahiert deterministisch, Claude mapped semantisch.
2. **Plattform-Layer vor Workflow-Ausbau.** 2-3 Wochen Vorlauf, dann Wiederverwendung in allen vier Workflows.
3. **W2 als Sammel-Workflow fuer MV/WEG/SEV** (nicht drei separate Workflows). Generalisierung ueber `object_type`-Enum.
4. **W3 Onboarding ist Prio 1** (nach M3/M5-Abschluss). 30-40 Objekte/Jahr ist klarer Business-Case.
5. **W4 Teilungserklaerung ist Prio 5-6**, ggf. 2027. Break-even erst Jahr 2.
6. **Objektsteckbrief ist Gatekeeper** fuer W2-Erweiterung und W4.
7. **Multi-Label als Default-Datenmodell**, nicht als Spezialfall.
8. **Confidence-Thresholds werden pro Kunde kalibriert**, nicht hardcoded.
9. **Eval-Framework parallel zur Plattform**, nicht nachtraeglich. Production-Corrections-Tabelle von Anfang an.
10. **Keine Custom-Modell-Trainings (Azure DI) im MVP** — Labeling-Effort zu gross fuer Solo-Entwickler, Prebuilt-Layout reicht.
11. **Kein zweiter KI-Provider als Zwischenschritt** — Anthropic + Azure bleibt fuer absehbare Zukunft das Duo.

---

## 12. Naechste Schritte

### 12.1 Innerhalb der naechsten Woche (vor Phase-1-Start)

- [ ] Impower-DMS-Tag-API pruefen (Swagger-Check, 30 Min)
- [ ] Objektsteckbrief v1 Spec-Fertigstellung pruefen, ggf. finalisieren
- [ ] SEPA-Volumen aus DB ermitteln (Real-Zahlen der letzten 3 Monate)
- [ ] Taxonomie-Stabilitaet mit DBS-Team klaeren
- [ ] 10-20 handschriftlich ausgefuellte SEPA-Mandate aus Produktion als Handschrift-Fixture-Korpus sammeln
- [ ] Eval-Ground-Truth fuer 3 bestehende SEPA-PDFs anlegen (als Pilot fuer Harness)

### 12.2 Phase 0 — M3 + M5 live (2-3 Wochen)

- M3 Neuanlage-Zweig mit Tilker GVE1 oder Kulessa BRE11 durchspielen
- M5 Case mit Verwaltervertrag + Grundbuch + Mieterliste + Mietvertrag komplett durch POST /cases/{id}/write jagen
- Exchange-Plan-Schema Live-Test (Schwerpunkt: wo kippt es falls 400/422?)
- Ground-Truth-Check: Stimmen die extrahierten Werte?

### 12.3 Phase 1 (sobald Phase 0 abgeschlossen)

- Plattform-Layer aufsetzen (B-1 bis B-5)
- Parallel: Eval-Harness + Production-Corrections-Tabelle
- Parallel: Sally kann UX-Konzept fuer W3-Cockpit entwerfen

### 12.4 Re-Assessment-Punkt

**Nach Phase 2 (W3 MVP live):** Review-Runde mit neuem Brainstorming, ob Phasen 3-6 so wie skizziert bleiben oder ob Reality-Check Anpassungen erzwingt. Explizit kein 36-Tage-Masterplan in Beton.

---

## Anhang A — Impower-Tag-Taxonomie (Arbeitsstand)

9 Top-Gruppen mit numerischem Prefix, insgesamt ~80 Subkategorien. Volltext siehe Daniels Eingabe in der Session; hier nur die Top-Gruppen:

| Prefix | Gruppe | Beispiele fuer Subkategorien |
|---|---|---|
| 10 | Stammdaten | Teilungserklaerung, Verwaltervertrag, Grundbuch, Hausordnung, Energieausweis, Plaene, Objektvertraege, Abrechnungsschluessel |
| 20 | Versicherungen | Wohngebaeude, Haftpflicht, Beirat, SV-Versicherung |
| 30 | Versorger | Aufzug, Heizung+Sanitaer, Strom, Wasser, Brandschutz, Elektroanlagen, Muell, Telko, ... |
| 40 | Gebaeudedienst | Vertrag Hausmeister, Personalakte, SV-Gebaeudedienst |
| 50 | Objektreporting | Hausmeisterprotokoll, Objektbegehung, Wartungsbericht, Zaehlerstand |
| 60 | Beschluesse | Protokoll ETV, Beschluss-Sammlung, Versammlung, Sitzung |
| 70 | Eigentuemer+Mieter | Kaufvertrag, Mietvertrag, SEPA Mandat, Stammdaten, SV-Eigentuemer/Mieter, Nutzerwechsel |
| 80 | Buchhaltung | Rechnung, Abrechnung, Wirtschaftsplan, Kontoauszug, Sonderumlage, Buchungsjournal, Buergschaft |
| 90 | Projekte | Projekt, Projekt Archiv |

**Status laut Daniel:** "werden wir noch ueberarbeiten vermutlich". → Daher DB-Tabelle mit Versioning statt Hard-Coding im Prompt.

### Kritische Tags (MVP-Whitelist fuer Extraction-Profiles)

10-15 Tags bekommen ein eigenes Pydantic-Schema + dedizierten Prompt, alle anderen nur Ablage:

| Tag | Felder | Modell |
|---|---|---|
| 10 Teilungserklaerung | miteigentumsanteile, einheiten_liste, sondereigentum, dienstbarkeiten | Sonnet (bzw. Opus-Test) |
| 10 Verwaltervertrag | vertragspartner, laufzeit, verguetung, kuendigungsfristen | Sonnet |
| 10 Grundbuch | grundbuchblatt, amtsgericht, lasten_abt_ii_iii | Sonnet |
| 20 * (Versicherungen) | versicherer, police_nr, deckungssumme, praemie, laufzeit | Haiku |
| 60 Protokoll | datum, beschluesse[], stimmverhaeltnis | Sonnet |
| 70 Kaufvertrag | kaeufer, verkaeufer, datum, kaufpreis, objekt_ref | Sonnet |
| 70 Mietvertrag | mieter, einheit, kaltmiete, nebenkosten, beginn, kaution | Haiku |
| 70 SEPA Mandat | (bestehender SEPA-Flow, W1) | — |
| 80 Rechnung | rechnungsnr, datum, betrag, iban, lieferant | Haiku |
| 80 Abrechnung | abrechnungszeitraum, gesamtkosten, anteile[] | Sonnet |

---

## Anhang B — Wichtige Referenzen

- **Code-Stellen heute:**
  - `app/services/claude.py` — Claude-Basis, Extract + Chat, wird Mapper-Pattern
  - `app/services/mietverwaltung.py` / `mietverwaltung_write.py` — M5, umzieht nach `app/workflows/object_setup/`
  - `app/services/impower.py` — Impower-Client, wird um DMS-Tag-Write erweitert
- **Memory-Referenzen:**
  - `memory/reference_impower_api.md` — zwei Swagger-Specs
  - `memory/reference_impower_mietverwaltung_api.md` — Write-Reihenfolge
  - `memory/feedback_haiku_unreliable_for_long_digits.md` — Ziffern-Drift-Problem
  - `memory/feedback_llm_iban_unicode_normalize.md` — Zero-Width-Space-Problem
  - `memory/project_anthropic_avv_cleared.md` — DSGVO-Status Anthropic
  - `memory/project_testing_strategy.md` — TestClient + Mocks als Default
- **Swagger-Specs (ohne Auth abrufbar):**
  - `https://api.app.impower.de/v2/api-docs` (Read, 57 Pfade)
  - `https://api.app.impower.de/services/pmp-accounting/v2/api-docs` (Write, 358 Pfade)
- **Parallel-Brainstorming:** `docs/brainstorming/objektsteckbrief-2026-04-21.md` — die zentrale Objektsicht, in die W2 und W4 schreiben.

---

**Versions-Log**

- **v1 (2026-04-21):** Erstfassung nach 5-Runden-Party-Mode-Session. Konsens-Level: Architektur + Priorisierung geklaert, sechs offene Fragen dokumentiert. Naechstes Update nach Phase 0 abgeschlossen bzw. bei Aenderungen der offenen Fragen.
