---
stepsCompleted:
  - step-01-document-discovery
  - step-02-prd-analysis
  - step-03-epic-coverage-validation
  - step-04-ux-alignment
  - step-05-epic-quality-review
  - step-06-final-assessment
filesIncluded:
  prd: output/planning-artifacts/prd.md
  architecture: output/planning-artifacts/architecture.md
  epics: output/planning-artifacts/epics.md
  ux: null
---

# Implementation Readiness Assessment Report

**Datum:** 2026-04-21
**Projekt:** Dashboard KI-Agenten

## 1. Document Discovery

### PRD
**Whole:**
- `output/planning-artifacts/prd.md` (60.217 bytes, geaendert 2026-04-21 12:33)

**Sharded:** keine.

### Architecture
**Whole (fuer die Bewertung gewaehlt):**
- `output/planning-artifacts/architecture.md` (53.623 bytes, geaendert 2026-04-21 14:32) — Planning-/Solution-Architektur aus `bmad-create-architecture`.

**Sharded:** keine.

**Nicht fuer die Bewertung, aber vorhanden als Code-Referenz:**
- `docs/architecture.md` (19.552 bytes, geaendert 2026-04-21 09:20) — Brownfield-Snapshot aus `bmad-document-project`.

### Epics & Stories
**Whole:**
- `output/planning-artifacts/epics.md` (62.792 bytes, geaendert 2026-04-21 15:20)

**Stories:** **nicht vorhanden** — es gibt keinen `stories/`-Ordner und keine separaten Story-Files. Vom User bestaetigt: **Stories noch nicht geschrieben**. Wird im Check als bekannter Gap markiert.

### UX Design
**N/A** — vom User bestaetigt: kein UX-Spec vorhanden, kein separater Prozess geplant. Plattform arbeitet mit HTMX-Fragmenten + ggf. Mockups direkt im Code (Beispiel: `mockups/mietverwaltung_setup.html` wurde in `case_detail.html` umgesetzt).

### Ergaenzende Artefakte (nicht Teil der Kern-Bewertung)
- `docs/project-context.md` — AI-Agenten-Regeln (wird als persistent fact im Check geladen)
- `docs/data-models.md`, `docs/api-contracts.md`, `docs/component-inventory.md`, `docs/source-tree-analysis.md`, `docs/deployment-guide.md`, `docs/development-guide.md`, `docs/project-overview.md`, `docs/index.md` — aus `bmad-document-project`
- `docs/brainstorming/objektsteckbrief-2026-04-21.md`
- `docs/objektsteckbrief-feld-katalog.md`

### Entscheidungen fuer die Bewertung
- Architektur-Quelle: `output/planning-artifacts/architecture.md`.
- UX: als **N/A** gewertet, keine UX-Bewertung.
- Stories: als bekannter Gap gefuehrt; Bewertung erfolgt auf Epic-Ebene aus `epics.md`.

## 2. PRD Analysis

### Funktionale Requirements

**Objekt-Detail & Cluster-Pflege**
- **FR1:** Mitarbeitende koennen eine Objekt-Detailseite aufrufen, die Stammdaten, Technik, Finanzen und Versicherungen in strukturierten Sektionen zeigt.
- **FR2:** Mitarbeitende koennen Stammdatenfelder (Cluster 1) als read-only-Spiegel aus Impower sehen (Adresse, WEG-Nr., Eigentuemerliste mit Stimmrechten).
- **FR3:** Mitarbeitende koennen technische Daten (Cluster 4) pflegen: Absperrpunkte mit Foto + Standortbeschreibung, Heizungs-Steckbrief, Zugangscodes, Objekt-Historie (year_built, year_roof, ...).
- **FR4:** Mitarbeitende koennen Finanzdaten (Cluster 6) als Impower-Spiegel sehen (Ruecklage, Wirtschaftsplan-Status, SEPA-Mandate) und den Bank-Saldo als Live-Wert beim Render.
- **FR5:** Mitarbeitende koennen Versicherungs-Portfolio (Cluster 8) pflegen: Policen, Wartungspflichten mit Policen-Verweis, Schadensfaelle, Risiko-Attribute.
- **FR6:** Mitarbeitende koennen einen neuen Schadensfall direkt aus der Versicherungs-Sektion des Objekts anlegen.
- **FR7:** Mitarbeitende koennen die Ruecklage-Historie als Zeitreihe (sparkline-artig) pro Objekt einsehen.
- **FR8:** Admins koennen Menschen-Notizen zu Eigentuemern pflegen; diese Notizen sind fuer Nicht-Admin-Rollen nicht sichtbar.
- **FR9:** Mitarbeitende koennen Fotos pro Technik-Komponente hochladen und anzeigen; die Fotos werden in SharePoint gespeichert, das System haelt nur Drive-Item-ID + Metadaten.
- **FR10:** Mitarbeitende koennen Zugangscodes erfassen; das System speichert sie verschluesselt und zeigt sie nur authentifizierten Usern mit `objects:view`-Permission entschluesselt an.

**Portfolio-Navigation & Due-Radar**
- **FR11:** Mitarbeitende koennen alle Objekte in einer Listenansicht mit sortierbaren und filterbaren Spalten sehen (mindestens: Saldo, Ruecklage, Mandat-Status, Pflegegrad).
- **FR12:** Mitarbeitende koennen die Objekt-Listenansicht auch mobil nutzen; auf kleinen Viewports faellt die Tabelle in ein Card-Layout zurueck.
- **FR13:** Mitarbeitende koennen eine Due-Radar-Ansicht aufrufen, die portfolio-weit alle Policen, Wartungspflichten und Vertraege mit Ablauf-Datum innerhalb der naechsten 90 Tage listet.
- **FR14:** Mitarbeitende koennen die Due-Radar-Ansicht nach Eintrags-Typ (Police / Wartung / Vertrag) und nach Ablauf-Schwere (< 30 Tage / < 90 Tage) filtern.
- **FR15:** Mitarbeitende koennen von jedem Due-Radar-Eintrag direkt zur Quell-Entitaet (Objekt, Police, Wartungspflicht) oder zur Registry-Detailseite springen.

**Registries & Aggregationen**
- **FR16:** Mitarbeitende koennen eine Versicherer-Listenansicht aufrufen mit Aggregationen pro Versicherer (Policen-Anzahl, Gesamtpraemie p.a., Schadensquote, Anzahl verbundener Objekte).
- **FR17:** Mitarbeitende koennen eine Versicherer-Detailseite aufrufen mit allen verbundenen Policen, Ablauf-Heatmap, Schadensfaellen und einer Aggregation der verbundenen Objekte.
- **FR18:** Das System fuehrt normalisierte Entitaeten fuer Dienstleister/Handwerker, Bank, Ablesefirma, Eigentuemer, Mieter, Mietvertrag, Zaehler sowie Facilioo-Mirror-Entitaeten als eigenstaendige Tabellen mit Objekt-FKs — auch wenn deren Detailseiten erst in v1.1 entstehen.

**Datenqualitaet & KI-Governance**
- **FR19:** Das System berechnet pro Objekt einen Pflegegrad-Score auf Basis von Feld-Completeness und Aktualitaet, sichtbar als Badge auf Detail- und Listen-Seite.
- **FR20:** Mitarbeitende koennen die Komposition des Pflegegrad-Scores in einer UI-Erlaeuterung nachvollziehen (welche Felder, welche Gewichte).
- **FR21:** Das System protokolliert fuer jeden Schreibvorgang auf einem Steckbrief-Feld einen Provenance-Eintrag (Quelle, Zeitstempel, User bzw. Sync-Job, Confidence bei KI-Vorschlaegen).
- **FR22:** Das System fuehrt eine Review-Queue fuer KI-Vorschlaege mit Ziel-Entitaet, Feldname, vorgeschlagenem Wert, Confidence und Status (pending / approved / rejected / superseded).
- **FR23:** Mitarbeitende koennen Eintraege in der Review-Queue approven oder rejecten; approve schreibt den Wert mit Provenance-Eintrag `ai_suggestion`, reject verwirft den Vorschlag und markiert ihn als abgelehnt.
- **FR24:** Admins koennen die Review-Queue portfolio-weit einsehen und nach Alter, Feld-Typ und Ziel-User filtern.
- **FR25:** Das System verhindert strukturell, dass ein KI-Agent direkt in Steckbrief-Felder schreibt, ohne zuvor einen Review-Queue-Eintrag zu erzeugen.

**Externe Integrationen & Sync**
- **FR26:** Das System spiegelt Impower-Stammdaten (Cluster 1) und Finanzdaten (Cluster 6) periodisch (nightly) in den Steckbrief; jedes gespiegelte Feld erhaelt einen Provenance-Eintrag `impower_mirror`.
- **FR27:** Das System laedt den Bank-Saldo aus Impower live beim Render der Objekt-Detailseite.
- **FR28:** Das System pollt Facilioo-Tickets in Ein-Minuten-Takt und spiegelt sie als `FaciliooTicket`-Entitaet; wenn der Server ETag/If-Modified-Since unterstuetzt, laedt der Job nur Deltas.
- **FR29:** Das System kann Fotos ueber die Microsoft-Graph-API in definierte SharePoint-Ordner pro Objekt hochladen und haelt lokal nur die drive_item_id + Metadaten.
- **FR30:** Das System toleriert zeitweilige Unerreichbarkeit von Impower, Facilioo oder SharePoint ohne User-Seiten-Crash (UI zeigt gecachten Snapshot mit Stale-Hinweis).

**Zugriff, Rollen & Audit**
- **FR31:** Nur Mitarbeitende mit Google-Workspace-Account unter `@dbshome.de` koennen sich anmelden (bestehendes OAuth-Hosted-Domain-Gate wiederverwendet).
- **FR32:** Das System unterstuetzt die Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `registries:view`, `registries:edit`, zuweisbar ueber Rollen oder User-Overrides.
- **FR33:** Das System schreibt fuer alle Steckbrief-Schreibaktionen (Objekt-Anlage, Feld-Edit, Foto-Upload, Review-Queue-Approve/Reject, Registry-Edit) einen Audit-Log-Eintrag mit User, Zeitpunkt und IP.
- **FR34:** Admins koennen die bestehende Audit-Log-View nach Steckbrief-spezifischen Actions filtern.

**Total FRs: 34**

### Non-Functional Requirements

**Performance (5)**
- **NFR-P1:** Objekt-Detailseite P95 < 2 s bei 50 Objekten inkl. Live-Pull Bank-Saldo; < 3 s bei 150 Objekten.
- **NFR-P2:** Objekt-Listenansicht P95 < 1.5 s bei 50 Zeilen; Sortier-/Filter-Wechsel via HTMX-Swap P95 < 500 ms.
- **NFR-P3:** Due-Radar-Global-View P95 < 2 s bei 20–30 Eintraegen im 90-Tage-Fenster.
- **NFR-P4:** Versicherer-Detailseite P95 < 2 s bei bis zu 20 Policen pro Versicherer.
- **NFR-P5:** Foto-Upload zu SharePoint P95 < 5 s pro Foto (max. 10 MB); groessere Dateien in BackgroundTask.

**Security (7)**
- **NFR-S1:** Jeder Zugriff erfordert authentifizierte Session ueber Google Workspace OAuth mit Hosted-Domain `@dbshome.de`.
- **NFR-S2:** Zugangscodes at-rest verschluesselt (HKDF aus `SECRET_KEY`); nie Klartext in Logs oder Audit-Payload.
- **NFR-S3:** Alle Datenuebertragungen ueber TLS (Elestio Reverse-Proxy).
- **NFR-S4:** Schreibende Operationen + Audit-Log-Eintrag atomar in einer Transaktion.
- **NFR-S5:** Menschen-Notizen nur fuer `admin`-Rolle sichtbar, serverseitig erzwungen.
- **NFR-S6:** KI-Agenten strukturell blockiert von direkten Writes; ohne Review-Queue-Eintrag → Ablehnung + Audit `policy_violation`.
- **NFR-S7:** `X-Robots-Tag: noindex, nofollow` fuer alle Routen.

**Zuverlaessigkeit & Verfuegbarkeit (5)**
- **NFR-R1:** Verfuegbarkeits-Ziel 99 % ueber 30 Tage (ohne externe APIs).
- **NFR-R2:** Externe API unerreichbar → App bedienbar, gecachter Snapshot + Stale-Hinweis, keine 500er.
- **NFR-R3:** Impower-Nightly-Mirror toleriert einzelne Endpoint-Fehler; Fortsetzung im naechsten Lauf.
- **NFR-R4:** Facilioo-1-Min-Mirror hat Error-Budget ≤ 10 % fehlgeschlagene Polls / 24h ohne Alert.
- **NFR-R5:** BackgroundTasks nutzen eigene DB-Session mit `try/finally`-Close.

**Integrations-Zuverlaessigkeit (5)**
- **NFR-I1:** Impower-Client 120 s Timeout + 5xx-Retry Exponential-Backoff (2/5/15/30/60 s, max 5); Rate-Limit-Gate 0.12 s.
- **NFR-I2:** Facilioo-Client Timeout ≥ 30 s, 5xx-Retry mit Backoff, Rate-Limit-Gate (Default 1 req/s).
- **NFR-I3:** SharePoint-Graph mit OAuth-Client-Credentials, Token-Refresh, 429-Retry respektiert `Retry-After`.
- **NFR-I4:** Anthropic-Fehler in KI-Vorschlag-Flows (v1.1) → kein Vorschlag, Audit `ai_suggestion_failed`, kein User-Impact.
- **NFR-I5:** HTML-Response-Bodies externer Systeme werden sanitisiert vor User-facing-Errortext.

**Observability (5)**
- **NFR-O1:** Jede schreibende Aktion erzeugt `AuditLog`-Eintrag (`user_id`, `user_email`, `action`, `entity_type`, `entity_id`, `ip_address`, `details_json`, `created_at`).
- **NFR-O2:** Bekannte Action-Liste um Steckbrief-Actions erweitert (`docs/architecture.md` §8 aktualisiert).
- **NFR-O3:** BackgroundTasks loggen Start/Ende/Fehler mit Timestamp in stdout + Audit-Entry bei Lauf-Fehler.
- **NFR-O4:** Pflegegrad-Score reproduzierbar aus DB, deterministisch (nur `now()` als Zeitabhaengigkeit).
- **NFR-O5:** Feld-Wert-Rueckverfolgung via `field_provenance` (wann / wer / welcher Wert).

**Skalierung (3)**
- **NFR-SC1:** Ziel v1: 50 Objekte, 7 User, ~10k Audit-Log-Eintraege/Monat. Keine Autoscaling-Strategie.
- **NFR-SC2:** Headroom 150 Objekte / 15 User ohne Architektur-Umbau — via Indexierung + Query-Disziplin.
- **NFR-SC3:** Kein Caching-Layer v1 (kein Redis/Memcached); strukturell offen fuer spaeter.

**Total NFRs: 30**

### Additional Requirements / Constraints / Assumptions

- **Launch-Window 9 Tage** (2026-04-22 bis ~2026-04-30), 1 Entwickler (Daniel) in Vollzeit, parallele Wartung M3/M5 erlaubt.
- **Launch-Blocker extern**: (a) M365-Admin-Ticket fuer SharePoint-App-Registration **Tag 1**, (b) Facilioo-API-Anbindung **Tag 3 Go/No-Go** — No-Go → Cluster 3.3 `open_tickets` auf v1.1.
- **Scope-Cut**: Cluster 1/4/6/8 komplett; Cluster 2/3/5/7/9/10 nur Teil-Abdeckung, wo fuer MVP-Journey noetig (`current_owner`/`current_tenant` am Objekt).
- **Registry-Cut**: nur Versicherer-Detailseite in v1; Dienstleister/Bank/Ablesefirma/Eigentuemer/Mieter als Tabellen mit FKs, Detailseiten v1.1.
- **v1 hat keine aktiven KI-Agenten** — nur Review-Queue-Infrastruktur (Policen sollen manuell geseedet werden, KI-Extract v1.1).
- **Read-only Sync v1**: Impower/Facilioo werden nur gespiegelt, kein Write-Back. Write-Back pro Feld ab v1.1.
- **SharePoint bleibt DMS**: Steckbrief haelt nur `drive_item_id` + Metadaten, keine Blobs lokal.
- **Rechtsgrundlage DSGVO**: Art. 6 Abs. 1 lit. b (Vertragserfuellung); AVV Anthropic ueber Commercial-API geklaert; DSFA-Light spaeter bei erstem KI-Flow.
- **Encryption-Key-Design v1**: HKDF aus `SECRET_KEY`; Rotations-Plan dokumentiert (separater `STECKBRIEF_FIELD_KEY` v1.1).
- **Access-Control v1**: alle 7 User sehen alle 50 Objekte; objekt-basierte `resource_access` v1.1.
- **Browser-Matrix**: Evergreen (Chrome/Edge/Firefox/Safari latest + N-1) + iOS Safari 17+/Chrome Android latest fuer J2 mobil.
- **Fallbacks**: Facilioo-Fail → Cluster 3.3 verschieben; SharePoint-Fail → lokaler `uploads/`-Ordner v1.
- **Tech-Stack-Leitplanken** (aus Brownfield): FastAPI + HTMX + Jinja2 + Tailwind + SQLAlchemy 2.0 + Postgres 16 + Alembic (manuell); Python 3.12; keine neuen Runtime-Komponenten; kein npm/node.

### PRD Completeness Assessment (Initial)

**Staerken:**
- Requirements sauber nummeriert, testbar, implementation-agnostisch (keine UI-Details, keine Tech-Wahl in FRs).
- Expliziter Traceability-Check FR ↔ Journey + FR ↔ Differentiator im PRD bereits enthalten (Zeilen 581–588).
- Klare Scope-Grenze (v1 vs. v1.1 vs. v2), Launch-Risiken mit Mitigationen.
- Domain-, Innovation-, Performance- und Integrations-Constraints ausformuliert.
- NFRs mit messbaren Zahlen (P95-Targets, Error-Budgets, Retry-Parameter).

**Potenzielle Luecken fuer die spaetere Abgleich-Phase:**
- **Pflegegrad-Score-Formel** ist in FR19/FR20 postuliert, aber die konkrete Komposition (welche Felder, welche Gewichte, welcher Aktualitaets-Decay) ist **nicht** festgeschrieben — nur in Risiko-Tabelle als "einfache Formel" skizziert. Muss Architektur oder Story abdecken.
- **Facilioo-DTOs + Auth-Flow** stehen explizit unter "noch zu klaeren" — Architektur muss das aufgreifen, sonst bleibt FR28 implementierungs-offen.
- **Encryption-Schluessel-Ableitung** (HKDF-Salt) nicht vollstaendig spezifiziert — Architektur- oder Story-Detail.
- **Review-Queue-Schema** (Pflicht-Felder, Statuswechsel-Regeln) ist in FR22–25 gefordert, aber der konkrete Flow (wer darf was, wie supersedet ein neuer Vorschlag einen alten) noch abstrakt.
- **Due-Radar-Datenquellen**: FR13 nennt Policen/Wartungspflichten/Vertraege — aber die "Vertraege"-Kategorie ist im MVP-Scope explizit nicht vollstaendig (Verwaltervertrag ist Cluster 7, v1.1). Klaerung noetig, welche Vertragstypen v1 wirklich liefert.
- **Mobile Card-Layout** (FR12) ist gefordert, aber ohne UX-Doku bleibt die Ausgestaltung undefiniert. Kein Blocker (interner Nutzer, HTMX-Fragment einfach), aber erwartbar ein Review-Punkt.
- **`resource_type="object"` Migration** (aus Risiko-Tabelle) ist im PRD als "v1: alle User sehen alle Objekte" entschaerft, aber weder FR noch NFR sprechen das explizit aus — Traceability-Luecke: wird objekt-ACL in v1 nun gebaut oder nicht? FR32 nennt Permissions, aber nicht resource-level Scoping.

## 3. Epic Coverage Validation

### Epic-Struktur (26 Stories in 4 Epics)

- **E1 Objekt-Zugriff & Pflege** (8 Stories 1.1–1.8): Permissions + Audit-Actions, Datenmodell + Write-Gate, Objekt-Liste + Stammdaten-Detail, Impower-Mirror, Finanzen + Live-Saldo, Technik-Edit, Zugangscodes-Encryption, Foto-Upload mit Fallback.
- **E2 Versicherungen & Due-Radar** (8 Stories 2.1–2.8): Policen, Wartungspflichten, Schadensfall, Menschen-Notizen admin-only, Due-Radar-Global, Filter + Deep-Links, Versicherer-Liste, Versicherer-Detail.
- **E3 Portfolio-UX & KI-Governance** (6 Stories 3.1–3.6): Objekt-Liste Sort/Filter, Mobile Card-Layout, Pflegegrad-Score-Service, Badge + Popover, Review-Queue-Admin-UI, Approve/Reject-Flow.
- **E4 Facilioo-Ticket-Integration (Launch-Optional)** (4 Stories 4.1–4.4): Spike, Client mit Retry, 1-Min-Poll, Tickets am Detail.

### Coverage Matrix (FR ↔ Story, unabhaengig verifiziert)

| FR | PRD-Kern | Epic/Story-Zuordnung | Status |
|----|----------|----------------------|--------|
| FR1 | Detailseite mit Sektionen | E1/1.3 (Stammdaten), 1.5 (Finanzen), 1.6 (Technik) + E2/2.x (Versicherungen) | ✓ Abgedeckt |
| FR2 | Stammdaten read-only Impower-Spiegel | E1/1.3 + 1.4 | ✓ Abgedeckt |
| FR3 | Technik pflegen (Absperrpunkte+Foto, Heizung, Codes, Historie) | E1/1.6 + 1.7 + 1.8 | ✓ Abgedeckt |
| FR4 | Finanzen-Spiegel + Live-Saldo | E1/1.4 + 1.5 | ✓ Abgedeckt |
| FR5 | Versicherungs-Portfolio (Policen, Wartungen, Schadensfaelle, **Risiko-Attribute**) | E2/2.1 + 2.2 + 2.3 | ⚠ Teil-Gap — **Risiko-Attribute** aus FR5 werden in keiner Story explizit genannt |
| FR6 | Schadensfall aus Versicherungs-Sektion | E2/2.3 | ✓ Abgedeckt |
| FR7 | Ruecklage-Historie Sparkline | E1/1.5 | ✓ Abgedeckt |
| FR8 | Menschen-Notizen admin-only | E2/2.4 | ✓ Abgedeckt |
| FR9 | Fotos in SharePoint, nur drive_item_id lokal | E1/1.8 | ✓ Abgedeckt |
| FR10 | Zugangscodes verschluesselt | E1/1.7 | ✓ Abgedeckt |
| FR11 | Objekt-Liste mit Sort/Filter (Saldo, Ruecklage, Mandat-Status, Pflegegrad) | E1/1.3 (Basic) + E3/3.1 (Enhanced) | ✓ Abgedeckt |
| FR12 | Mobile Card-Layout | E3/3.2 | ✓ Abgedeckt |
| FR13 | Due-Radar 90 Tage: Policen / Wartungen / **Vertraege** | E2/2.5 | ⚠ Inkonsistenz — Story 2.5 macht UNION mit `management_contract.next_main_due`; PRD legt Cluster 7 (Verwaltervertrag) explizit in v1.1, damit ist die Quelle fuer den "Vertraege"-Teil in v1 offen |
| FR14 | Due-Radar Filter Typ + Schwere | E2/2.6 | ✓ Abgedeckt |
| FR15 | Due-Radar Deep-Links | E2/2.6 | ✓ Abgedeckt |
| FR16 | Versicherer-Liste Aggregationen | E2/2.7 | ✓ Abgedeckt |
| FR17 | Versicherer-Detailseite | E2/2.8 | ✓ Abgedeckt |
| FR18 | Normalisierte Entitaeten als Tabellen mit FKs | E1/1.2 (Migration 0010) | ✓ Abgedeckt |
| FR19 | Pflegegrad-Score + Badge | E3/3.3 + 3.4 | ✓ Abgedeckt |
| FR20 | Score-Komposition UI-Erlaeuterung | E3/3.4 | ✓ Abgedeckt |
| FR21 | Field-Provenance pro Schreibvorgang | E1/1.2 (Write-Gate) | ✓ Abgedeckt |
| FR22 | Review-Queue mit Status pending/approved/rejected/superseded | E1/1.2 + E3/3.5 + 3.6 | ✓ Abgedeckt |
| FR23 | Approve/Reject-Flow | E3/3.6 | ✓ Abgedeckt |
| FR24 | Admin-Filter Alter / Feld-Typ / **Ziel-User** | E3/3.5 | ⚠ Feld-Mapping-Gap — PRD sagt "Ziel-User" (wem zugewiesen), Story 3.5 nennt `decided_by_user_id` (wer hat entschieden). Ziel-User-Feld fehlt im Review-Queue-Schema |
| FR25 | strukturelle KI-Blockade | E1/1.2 (`write_field_ai_proposal`) | ✓ Abgedeckt |
| FR26 | Nightly-Mirror Cluster 1 + 6 | E1/1.4 | ✓ Abgedeckt |
| FR27 | Live-Pull Bank-Saldo | E1/1.5 | ✓ Abgedeckt |
| FR28 | Facilioo 1-Min-Polling + Delta | E4/4.1–4.3 | ⚠ **Launch-optional** — bei Tag-3 No-Go faellt FR28 raus und geht v1.1 |
| FR29 | SharePoint Graph-API, nur drive_item_id lokal | E1/1.8 | ✓ Abgedeckt |
| FR30 | Toleranz externe Unerreichbarkeit, Stale-Hinweis | E1/1.3 + 1.5 + E4/4.4 | ✓ Abgedeckt |
| FR31 | Google OAuth `@dbshome.de` | Bestands-Infrastruktur, implizit in allen Routen-Stories | ✓ Abgedeckt (Wiederverwendung) |
| FR32 | Permissions `objects:view/edit/approve_ki`, `registries:view/edit` | E1/1.1 | ✓ Abgedeckt + Erweiterung (siehe unten) |
| FR33 | Audit-Log fuer alle Schreibaktionen | E1/1.1 (Seed) + durchgehend in allen Stories | ✓ Abgedeckt |
| FR34 | Audit-Log-View-Filter nach Steckbrief-Actions | E1/1.1 | ✓ Abgedeckt |

### NFR-Coverage (Stichprobe)

Die Architektur-Notizen und Stories greifen NFRs explizit auf:
- **NFR-P1/P2/P3/P4**: P95-Targets wiederholen sich in Stories 1.3, 1.5, 2.5, 2.7, 2.8 als Acceptance-Kriterien ✓
- **NFR-P5** (Foto-Upload): Story 1.8 (Size-Limit + BackgroundTask bei > 3 MB) ✓
- **NFR-S1** (OAuth-Gate): impliziert + getestet via Smoke-Tests ✓
- **NFR-S2** (Encryption): Story 1.7 ✓
- **NFR-S4** (atomare Audit+Write): Story 1.2 + durchgaengig ✓
- **NFR-S5** (Menschen-Notizen serverseitig): Story 2.4 ✓
- **NFR-S6** (KI-Gate): Story 1.2 ✓
- **NFR-S7** (X-Robots-Tag): Story 1.1 ✓
- **NFR-R3** (Mirror-Toleranz): Story 1.4 ✓
- **NFR-R5** (BackgroundTask-Session): Story 1.8 + 1.4 + 4.3 ✓
- **NFR-I1** (Impower-Retry): Platform-Bestand, NFR-I2 (Facilioo-Retry) Story 4.2 ✓
- **NFR-I3** (SharePoint OAuth-CC + 429-Retry): Story 1.8 impliziert via MSAL ✓
- **NFR-O4** (deterministischer Score): Story 3.3 ✓
- **NFR-O5** (Field-Provenance-Rueckverfolgung): Story 1.2 ✓

NFRs ohne explizites Story-Acceptance-Mapping (implizit via Platform-Bestand):
- **NFR-S3** (TLS): Elestio-Reverse-Proxy, kein Story-Aspekt.
- **NFR-R1** (99 % Verfuegbarkeit): Betriebs-KPI, nicht Story-skopiert.
- **NFR-R4** (Facilioo-Error-Budget): Story 4.3 ("Alert bei > 10 %") ✓
- **NFR-SC1/2/3** (Skalierungs-Headroom): Architektur-Entscheidungen, keine dedizierte Story — akzeptabel fuer Launch.

### Coverage-Statistik

- **Total PRD FRs:** 34
- **FRs mit sauberem Story-Mapping:** 30 (✓ Abgedeckt)
- **FRs mit Detail-Gap oder Inkonsistenz:** 4 (FR5, FR13, FR24, FR28)
- **FRs ohne Abdeckung:** 0
- **Coverage-Prozentsatz (strukturell):** 100 %
- **Coverage-Prozentsatz (mit sauberem Detail-Mapping):** ~88 % (30/34)

### Missing / Gap Analysis

**Keine kritisch fehlende FR-Abdeckung** — alle 34 FRs haben einen Ziel-Epic. Die folgenden vier Positionen sind **Detail-Gaps**, die vor Story-Implementierung abgeraeumt werden sollten:

#### Kritische Gaps

- **Stories fehlen vollstaendig** (bekannt, vom User bestaetigt). Es gibt `epics.md` mit Story-Definitionen + Acceptance-Criteria; der erwartete separate `stories/`-Ordner ist nicht angelegt. Fuer die Implementierungs-Phase empfehle ich die Story-Artefakte (`bmad-create-story`) fuer mindestens die erste Epic-Tranche (E1, 8 Stories) zu generieren, da jede Story noch Test-Plan, Risiko-Check und Dev-Notes ergaenzt bekommen sollte.

#### Hohe Prioritaet

- **FR5 "Risiko-Attribute" nicht in Stories ausgearbeitet** — PRD nennt Policen + Wartungspflichten + Schadensfaelle + **Risiko-Attribute**; Stories 2.1–2.3 decken die ersten drei, aber Risiko-Attribute sind weder in E2 genannt noch als eigenes Modell-Feld in E1/1.2 spezifiziert. Empfehlung: Story 2.1 um AC erweitern (z. B. `risk_category`, `risk_severity` an `InsurancePolicy` und/oder `Object`), oder explizit als v1.1-Verschiebung im Epic markieren.
- **FR13/Story 2.5 Inkonsistenz `management_contract`** — PRD fuehrt Cluster 7 (Verwaltervertrag) als v1.1, Story 2.5 UNION-ALL-Query nimmt aber `management_contract.next_main_due` bereits in v1. Entweder: (a) Cluster 7 in MVP ziehen (mindestens Vertrags-Ablaufdatum als Feld auf `Object`), oder (b) FR13 auf "Policen + Wartungspflichten" in v1 reduzieren und Vertraege aus Story 2.5 streichen.
- **FR24 Feld-Mapping `target_user` fehlt** — PRD fordert Filter nach "Ziel-User" (wem ist der Vorschlag zugewiesen); `ReviewQueueEntry` hat laut Story 1.2 `target_entity_type/id` + `decided_by_user_id`, aber kein `assigned_user_id` o.ae. Fuer v1 mit leerer Queue niedrig-kritisch, fuer v1.1 (erste KI-Agenten) aufzuloesen.

#### Mittel / Informativ

- **FR28 ist launch-optional** — Facilioo an Tag-3 Go/No-Go gebunden. Klar dokumentiert, **kein Gap**, aber die Readiness-Matrix sollte das ausweisen.

### Ueber-Coverage (Epic > PRD) — nicht negativ, aber traceability-relevant

Folgendes ist in den Epics definiert, **aber nicht im PRD als FR/NFR formuliert**:

- **Neue Permissions `objects:view_confidential`, `due_radar:view`, `sync:admin`** (Story 1.1) — PRD FR32 nennt nur `objects:view/edit/approve_ki`, `registries:view/edit`. Drei Permissions kommen oben drauf. Davon wandert `objects:view_confidential` aus der PRD-Risiko-Tabelle "Menschen-Notizen admin-only" zu einem expliziten Permission-Key; `due_radar:view` und `sync:admin` sind neu. Empfehlung: PRD-FR32 bei Gelegenheit um diese drei Permissions aktualisieren oder im Epic begruenden.
- **Audit-Action `encryption_key_missing`, `sharepoint_init_failed`** — logische Ableitungen aus NFR-O3, aber nicht direkt in PRD formuliert. Akzeptabel.
- **Konvention "User-Edit gewinnt gegen Mirror"** (Architektur "Gap G8-Klaerung") — in Story 1.4 als AC enthalten. PRD macht dazu keine explizite Aussage. Gute Detail-Entscheidung; sollte in PRD (oder Architektur-ADR) als dokumentierte Regel fixiert werden.

## 4. UX Alignment Assessment

### UX Document Status

**Nicht vorhanden (N/A).** Bewusste Entscheidung — vom User in Step 1 bestaetigt; im Epic-Dokument Zeile 238–240 dokumentiert: "Kein formelles UX-Design-Dokument im Scope vorhanden. UI-Conventions ergeben sich aus `docs/project-context.md` und dem Bestand der Plattform (Sidebar-Layout, Jinja2 + HTMX + Tailwind, Fragment-Templates mit Underscore-Prefix, Status-Pills analog zu M5)."

### UI-Impliziert-Analyse

Die Anwendung ist **stark UI-lastig** — das PRD und die Epics definieren UI-Verhalten explizit, auch ohne UX-Dokument:

| UI-Aspekt | Definitions-Ort | Ausreichend dokumentiert? |
|-----------|-----------------|---------------------------|
| Objekt-Detail-Layout mit 7 Sektions-Fragmenten | Architektur (`_obj_stammdaten`, `_obj_technik`, ...) + Stories 1.3, 1.5, 1.6 | ✓ Sektionsnamen + Provenance-Pill-Muster definiert; Reihenfolge/Grid nicht festgeschrieben (uebernimmt aus Bestand) |
| Objekt-Liste Spalten + Sort/Filter | Story 3.1 (Spalten benannt: `short_code`, `name`, `saldo`, `reserve_current`, `mandat_status`, `pflegegrad`) | ✓ |
| Mobile Card-Layout | Story 3.2 (Touch-Targets >= 44 px, Tap-to-call fuer Heizung, vertikal gestapelt) | ✓ |
| Pflegegrad-Badge Farbkodierung | Story 3.4 (Gruen ≥ 70, Gelb 40–69, Rot < 40) | ✓ |
| Pflegegrad-Popover Inhalt | Story 3.4 (Cluster-Completeness + Gewicht + weakest_fields mit Deep-Links) | ✓ |
| Review-Queue-Admin-UI | Stories 3.5 + 3.6 (Spalten, Filter, Approve/Reject-Flow) | ✓ |
| Due-Radar-Liste + Filter | Stories 2.5 + 2.6 (Severity-Badges, Deep-Links) | ✓ |
| Versicherer-Detail: Heatmap + Aggregationen | Story 2.8 | ✓ dem Namen nach; Heatmap-Details (Binning, Farbskala) offen |
| Error/Empty-States | punktuell pro Story (z. B. "keine Eintraege in den naechsten 90 Tagen", "noch nicht gesynced") | ⚠ kein einheitliches Muster, aber konsistent mit Bestand |
| Validierungs-Fehler-UX | punktuell (z. B. Story 1.6 "Validierungs-Meldung") | ⚠ kein Error-Component-Standard definiert, erbt aus Bestand |
| Design-Tokens / Color-System | nicht spezifiziert | Erbt aus Tailwind-Bestand (konservativer Default) |

### UX ↔ PRD ↔ Architecture Alignment

**Alignment ist durch die Stories hergestellt**, nicht durch ein separates UX-Dokument:

- PRD-Journey J2 Markus fordert Mobile-Notfall-Flow → Story 3.2 liefert Card-Layout + Tap-to-call + prominente Heizungs-Hotline.
- PRD-Journey J4 Julia fordert Due-Radar + Versicherer-Aggregation → Stories 2.5–2.8 liefern Listenansicht, Heatmap, Deep-Links.
- PRD-Journey J5 Daniel fordert Review-Queue-Triage → Stories 3.5–3.6 liefern Filter + Approve/Reject.
- NFR-P1/P2/P3/P4 (P95-Targets) sind als AC in den entsprechenden Stories angelegt — Architektur unterstuetzt via HTMX-Fragment-Swaps.

### Warnungen

- **⚠ Design-Token / Visuelles Regelwerk nicht dokumentiert.** Fuer eine 7-User-interne-App mit bestehendem Template-Set (SEPA + M5 Mietverwaltung) ist das pragmatisch vertretbar, aber: sobald ein externer Designer oder ein zweiter Entwickler in das Projekt kommt, fehlt ihm ein Referenz-Punkt. **Empfehlung:** ein `docs/ux-conventions.md` mit 10–20 Zeilen (Farben, Pill-Muster, Fragment-Benennung, Empty-State-Wording) waere niedrig-invasiv und schliesst die Luecke.
- **⚠ Heatmap in Story 2.8 offen** — "Ablauf-Heatmap (zeitlicher Balken ueber 12 Monate, rote Markierungen bei ablaufenden Policen < 90 Tage)" — Bucket-Granularitaet (monatsweise? wochenweise?), Farbverlauf und Mobile-Fallback nicht definiert. Sollte im Story-Review geklaert werden.
- **⚠ Wireframes / Low-Fi-Screens fehlen fuer die Objekt-Detailseite.** 7 Sektions-Fragmente sind benannt, aber die Reihenfolge und Gewichtung (welche Sektion zuerst, welche als Collapse, welche mobil oben) ist nicht festgeschrieben. Fuer J1 Lena ist "Stammdaten oben → Pflegegrad-Badge → Technik mit Fotos → Finanzen → Versicherungen" im PRD beschrieben (Zeile 248), aber nicht als bindendes Layout.

### Zusammenfassung

UX-Alignment ist **praktisch ausreichend** fuer die v1-Implementierung: alle kritischen UI-Entscheidungen sind als Acceptance-Criteria in den Stories fixiert, und die Plattform-Konventionen (HTMX, Tailwind, Sektions-Fragmente mit Provenance-Pills) sind durch die Bestands-Module SEPA + M5 etabliert. **Kein Blocker**, aber die oben genannten Warnungen sollten vor Epic-Start einmal vom Entwickler (Daniel) mental durchgegangen werden.

## 5. Epic Quality Review

Strikter Abgleich gegen die `create-epics-and-stories`-Standards (User-Value, Epic-Unabhaengigkeit, Story-Dependencies, AC-Qualitaet, Sizing).

### Epic-Struktur-Validierung

| Epic | User-centric Title | User-Value liefert? | Unabhaengig von Folge-Epics? | Bewertung |
|------|--------------------|---------------------|-------------------------------|-----------|
| E1 Objekt-Zugriff & Pflege | ✓ | ✓ — auch allein nutzbarer Steckbrief (Stammdaten/Technik/Finanzen) | ✓ — E1 braucht keine andere Epic | ✓ |
| E2 Versicherungen & Due-Radar | ✓ | ✓ — Versicherungs-Portfolio + Differentiator Due-Radar | ✓ — nutzt E1, braucht aber kein E3/E4 | ✓ |
| E3 Portfolio-UX & KI-Governance | ✓ | ✓ — erweiterte Liste + Mobile + Governance-Queue | ✓ — Score laeuft auch ohne E2-Daten (leere Werte); Queue-UI testet bewusst mit leerer Queue | ✓ |
| E4 Facilioo-Ticket-Integration | ⚠ Technisch formuliert ("Ticket-Integration") statt user-centric ("Offene Tickets am Objekt sehen") | ✓ — Story 4.4 liefert User-Value | ✓ — optional, braucht nur E1 | ⚠ Minor |

### Story-Quality-Assessment

**Stichprobe je Epic — alle Stories wurden einzeln gegen die AC-Qualitaets-Kriterien geprueft.**

Allgemeine Qualitaets-Indikatoren (durchgaengig ueber 26 Stories erfuellt):
- ✓ **G/W/T-Format** mit fett markierten Keywords in allen 26 Stories.
- ✓ **Spezifitaet**: Feldnamen, Enum-Werte, HTTP-Status-Codes, Pfade, Audit-Action-Namen stehen exakt drin.
- ✓ **Testbarkeit**: jede AC kann als Unit- oder Smoke-Test formuliert werden.
- ✓ **Error-Paths**: 403-Fallbacks, Validation-Fehler, Stale-Snapshots, 5xx-Gateway-Faelle sind pro Story dokumentiert.
- ✓ **Happy-Path + Negative-Path** ausbalanciert.

### 🔴 Critical Violations

**Keine kritischen Violations gefunden.** Kein Forward-Dependency bricht die Implementierungs-Reihenfolge; kein Epic ist rein technisch ohne User-Value; keine User-Story ist unvollendet.

### 🟠 Major Issues

1. **Story 2.5 (Due-Radar Global-View): Entity `management_contract` nicht definiert.**
   Acceptance-Kriterium in Story 2.5: "UNION-ALL-Abfrage ueber `policen`, `wartungspflichten`, `management_contract` (Feld `next_main_due`)". Story 1.2 (Datenmodell) listet 16 Entitaeten auf — `management_contract` ist **nicht darunter**. Laut PRD liegt Cluster 7 (Verwaltervertrag) in v1.1. Entweder:
   - (a) `management_contract` als Tabelle / Objekt-Feld in Story 1.2 ergaenzen und PRD-Scope um Cluster-7-Mini-Anteil erweitern, oder
   - (b) Story 2.5 auf `policen` + `wartungspflichten` reduzieren und FR13 entsprechend anpassen.
   Blocker, wenn nicht geklaert, weil Story 2.5 sonst ein nicht-existentes Schema-Element referenziert.

2. **Story 3.5/3.6 (Review-Queue): Feld fuer "Ziel-User" fehlt im Entity.**
   Die PRD-Journey J5 beschreibt Daniel's Filter nach "Ziel-User" (= wem ist der Vorschlag zugewiesen). Story 1.2 definiert `ReviewQueueEntry` mit `target_entity_type`, `target_entity_id`, `decided_by_user_id`, aber ohne `assigned_to_user_id` o.ae. Story 3.5 filtert nur nach `decided_by_user_id` (wer hat entschieden). Fuer v1 mit leerer Queue niedrig kritisch, aber das Schema steht danach fest und braucht in v1.1 eine Migration. Empfehlung: `assigned_to_user_id: UUID | None` bei Story 1.2 ergaenzen und Story 3.5 darauf filtern.

3. **Story 1.2: Datenbank-Tabellen werden alle vorab angelegt ("alle 16 Tabellen upfront").**
   Nach striktem Best-Practice-Kriterium ("Tabellen erst wenn Story sie braucht") eine Verletzung. In diesem Brownfield-Kontext mit Alembic-Migrations, die manuell geschrieben werden (keine Autogenerate!), sind zwei Migrations (0010 + 0011) pragmatisch vertretbar — eine Migration pro Entity waere in 9 Tagen nicht leistbar und wuerde Merge-Konflikte produzieren. **Dokumentiert als bewusste Abweichung.**

### 🟡 Minor Concerns

1. **Story 1.2 ist eine Entwickler-Story ("Ich moechte ein Write-Gate zur Verfuegung haben")** statt einer klassischen User-Story. Das liefert keinen direkt user-facing Wert, ist aber harte Voraussetzung fuer FR21/FR25 (strukturelle KI-Blockade, Provenance-Pflicht). Vertretbar als Fundament-Story, weil das Write-Gate selbst eine Innovation mit Policy-Gewicht ist. Alternative waere, 1.2 in 1.3 zu integrieren — dann wird 1.3 zu gross fuer 1 Tag.
2. **Story 3.3 (Pflegegrad-Service) ist Entwickler-Story** — gleiche Bewertung wie 1.2: harte Voraussetzung fuer 3.4-Badge-UI. Vertretbar.
3. **Story 4.1 (Facilioo-Spike) liefert keinen User-Value.** Spike-Stories sind eine etablierte Praxis; der AC-Output ist ein Entscheidungsdokument — OK fuer ein optionales Epic.
4. **Story 4.2 (Facilioo-Client)** technische Voraussetzung ohne User-Value. Vertretbar als interner Client-Baustein.
5. **Story-Sizing**: 26 Stories auf 9 Tage Entwicklungszeit = ~2.9 Stories/Tag. Einzelne Stories sind klein (1.1 Permissions-Seed), andere gross (1.8 Foto-Upload mit SharePoint + Local-Fallback + BackgroundTask). **Ambitioniert, aber konsistent mit der im PRD angekuendigten 7-Tage-Implementierung + 2 Tagen Puffer.** Launch-Risiko, kein Quality-Issue.
6. **E4 Epic-Titel technisch**: "Facilioo-Ticket-Integration" statt "Offene Tickets am Objekt sichtbar". Namensmaengel, inhaltlich korrekt.
7. **FR5 Risiko-Attribute** (schon in Step 3 notiert): kein Story-AC — muss vor Implementierung in Story 2.1 ergaenzt oder klar auf v1.1 verschoben werden.
8. **Story 1.1 ergaenzt die Permissions-Liste um drei Keys** (`objects:view_confidential`, `due_radar:view`, `sync:admin`), die nicht im PRD FR32 stehen. Gute Erweiterung, aber PRD sollte das gespiegelt bekommen.

### Within-Epic-Dependencies (Pruefung auf Forward-Dep)

Alle Stories wurden auf Forward-Dependencies geprueft — **kein unzulaessiger Fall gefunden**:

- E1: 1.1 (standalone) → 1.2 (standalone, legt Schema) → 1.3 (nutzt 1.1 Permissions + 1.2 Schema) → 1.4 (nutzt 1.2) → 1.5/1.6/1.7/1.8 (nutzen 1.2 + 1.3). Sauber.
- E2: 2.1 (Policen) → 2.2 (Wartungen, nutzt 2.1) → 2.3 (Schadensfaelle, nutzt 2.1) → 2.4 (unabhaengig, nutzt E1/1.2) → 2.5 (Due-Radar, braucht 2.1/2.2) → 2.6 (nutzt 2.5) → 2.7 (Registry-Liste, nutzt 2.1) → 2.8 (Registry-Detail, nutzt 2.7). Sauber.
- E3: 3.1 (Liste mit Sort) → 3.2 (Mobile) → 3.3 (Score-Service) → 3.4 (Badge, nutzt 3.3) → 3.5 (Queue-UI) → 3.6 (Approve/Reject, nutzt 3.5). Sauber.
- E4: 4.1 (Spike) → 4.2 (Client) → 4.3 (Poll-Job, nutzt 4.2) → 4.4 (UI, nutzt 4.3). Sauber.

### Starter-Template- und Brownfield-Indikatoren

- ✓ **Kein Starter-Template gefordert** — Architektur sagt explizit Brownfield-Extension. Story 1.1 ist korrekt als Permissions+Audit+Header-Seed und nicht als Repo-Init formuliert.
- ✓ **Brownfield-Muster erkennbar**: Integration mit Impower/Facilioo/SharePoint, Migrations-Reihenfolge auf 0010/0011 aufbauend, Nutzung des bestehenden `audit()`-Helpers, Permissions-System + Default-Rollen-Seed-Pattern.

### Quality-Assessment-Zusammenfassung

- **Kritische Violations:** 0
- **Major Issues:** 3 (Entity `management_contract` fehlt in Schema, `assigned_to_user_id`-Feld fehlt fuer FR24, Alle-Tabellen-upfront-Abweichung)
- **Minor Concerns:** 8 (Entwickler-Stories 1.2/3.3/4.2, Spike-Story 4.1, E4-Epic-Name, Sizing-Tempo, FR5 Risiko-Attribute, PRD-FR32-Spiegeln)

Die Epic/Story-Struktur ist **implementierungs-ready**, sobald die drei Major-Issues pre-Sprint abgeraeumt sind (Entscheidung zu `management_contract`, Schema-Update fuer `assigned_to_user_id`, FR5 Risiko-Attribute klaeren oder schieben). Alle anderen Minor Concerns sind Transparenz-Punkte, keine Blocker.

## 6. Summary and Recommendations

### Overall Readiness Status

**🟠 NEEDS WORK — Implementation-Ready mit 3–4 klar benannten Vorarbeiten.**

Das Projekt ist **kein** "Not Ready". Planning ist inhaltlich vollstaendig, gut strukturiert, konsistent zwischen PRD → Architektur → Epics → Acceptance-Criteria. 34/34 FRs haben eine Story-Zielkoordinate; NFRs sind mehrheitlich in Stories verankert; Brownfield-Muster korrekt umgesetzt.

Gleichzeitig sind drei inhaltliche Klaerungen faellig, bevor die erste Story in Entwicklung geht, plus eine strukturelle Entscheidung zur Story-Artefakt-Erzeugung. Ohne diese Klaerung entstehen in den ersten Tagen Friktion und potenziell eine Migrations-Nachziehschleife.

### Critical Issues Requiring Immediate Action

**Blocker-Kandidat vor Story-Start:**

1. **`management_contract`-Entity in Story 2.5 klaeren.** Story-AC referenziert eine Tabelle/ein Feld, das weder in Story 1.2 (Schema-Migration 0010/0011) noch im PRD Cluster-7-Scope steht. Zwei Wege: (a) `Object.management_contract_next_main_due`-Feld zu Story 1.2 ergaenzen und FR13 bei Verwaltervertrag auf Einzelwert reduzieren, oder (b) Story 2.5 auf `policen` + `wartungspflichten` zuschneiden und FR13 entsprechend kuerzen. **Entscheidung vor Story 1.2 noetig** (sonst landet Migration 0010 ohne das Feld und Story 2.5 schlaegt spaeter fehl).

2. **`ReviewQueueEntry.assigned_to_user_id` in Story 1.2 ergaenzen (oder explizit verwerfen).** Fuer v1 mit leerer Queue nicht kritisch, aber das Schema wird in Story 1.2 gegossen — eine spaetere Migration nur fuer ein UUID-Feld waere vermeidbar. Empfehlung: Feld mit `nullable=True` hinzufuegen, Story 3.5 um den Filter "Ziel-User" erweitern (matched PRD-FR24 exakt).

3. **FR5 Risiko-Attribute entscheiden**: entweder in Story 2.1 als AC (`risk_category`, `risk_severity` an `InsurancePolicy` oder `Object`) ergaenzen oder FR5 + PRD explizit auf v1.1 zuruecksetzen. Aktuell schwebt es zwischen PRD-Pflicht und nicht-gecoverter Story.

**Prozessualer Punkt:**

4. **Stories noch nicht als separate Artefakte angelegt.** `epics.md` enthaelt vollstaendige Story-Definitionen inkl. Acceptance-Criteria — das reicht technisch zum Implementieren, bewahrt aber nicht den ueblichen Workflow mit Task-Breakdown + Dev-Notes pro Story-File. Drei Optionen:
   - (a) Pragmatisch: direkt implementieren aus `epics.md` heraus, pro Story ein `bmad-create-story` laufen lassen **only fuer E1** (Fundament-Epic) und bei E2/E3/E4 mit dem Epic-Content arbeiten.
   - (b) Sauber: `bmad-create-epics-and-stories` oder `bmad-create-story` fuer alle 26 Stories laufen lassen. Kostet mind. einen halben Tag, liefert aber pro Story eine Datei mit Test-Plan + Risk-Check.
   - (c) Minimal: nur die drei Major-Issue-Stories (1.2, 2.1, 2.5) nach der Klaerung neu als Story-Files anlegen, Rest direkt aus `epics.md`.

### Recommended Next Steps

1. **Klaerungs-Runde (30–60 Min)** mit sich selbst:
   - `management_contract` Scope in v1 oder v1.1?
   - `assigned_to_user_id` Feld ja/nein?
   - FR5 Risiko-Attribute in Story 2.1 oder v1.1?

2. **Updates in den Planning-Artefakten** (≤ 1 Stunde): PRD-FR13 + FR5 praezisieren, Story 1.2 + 2.1 + 2.5 ACs anpassen. Optional: PRD-FR32 um die drei zusaetzlichen Permission-Keys aus Story 1.1 aktualisieren (`objects:view_confidential`, `due_radar:view`, `sync:admin`).

3. **Story-Artefakte erzeugen (je nach gewaehlter Option aus Punkt 4 oben)**. Bei Option (c) minimal fuer die drei angepassten Stories.

4. **Parallel — Tag-1-Tickets oeffnen** (stehen bereits im Epic):
   - M365-Admin-Ticket: SharePoint-App-Registration (`Files.ReadWrite.All`, `Sites.Read.All`).
   - Facilioo-API-Spike (Story 4.1): Zugang klaeren, Swagger oder Dokumentation besorgen.

5. **Optional, aber klein**: `docs/ux-conventions.md` (10–20 Zeilen) als UX-Referenz fuer spaeteren Zweitentwickler — Farben, Pill-Muster, Empty-State-Wording, Fragment-Benennung.

6. **Dann Implementation starten** mit E1/Story 1.1 → 1.2 → 1.3 ... . Reihenfolge E1 → E2 → E3 → E4 (letzteres Tag-3-Go/No-Go).

### Final Note

Dieses Assessment identifizierte **0 kritische Violations, 3 Major Issues und 8 Minor Concerns** ueber 5 Kategorien (Discovery, PRD, Coverage, UX, Epic-Quality). Von 34 Funktionalen Requirements haben **34** eine Epic-Zuordnung; davon haben **30** ein sauberes Story-Mapping und **4** ein Detail-Gap. Der Planungsstand ist qualitativ hochwertig und implementierungs-tauglich, nach den drei Klaerungen in der obigen Critical-Issues-Sektion kann E1 ohne Friktion starten.

**Assessor:** Implementation-Readiness-Check (`bmad-check-implementation-readiness`)
**Datum:** 2026-04-21
**Review-Basis:** PRD v1 (642 Zeilen), Architecture v1 (53.6 KB), Epic-Breakdown (968 Zeilen, 4 Epics, 26 Stories), `project-context.md` als persistente Fakten.





