---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete']
status: 'complete'
completedAt: '2026-04-21'
releaseMode: 'phased'
portfolio_context:
  active_objects: 50
  internal_users: 7
  launch_target: '2026-04 Ende'
vision:
  summary: 'Zentrale DBS-eigene Objektsicht, die (a) Read-Daten aus Impower + Facilioo buendelt und (b) Datenbereiche strukturiert pflegt, die in Impower/Facilioo nicht pflegbar sind — Technik, Fotos, Versicherungen + Wartungsnachweise, Verwaltervertrag, Menschen-Notizen. Sekundaer: Ground-Truth fuer KI-Agenten der Plattform.'
  differentiators:
    - 'Due-Radar global — portfolio-weite Ablauf-Ansicht (Versicherung/Wartung/Vertrag < 90 Tage), heute unmoeglich'
    - 'Pflegegrad-Score pro Objekt — Datenqualitaet quantifizierbar'
    - 'Normalisierte Seiten-Entitaeten + Registries ab v1 (Versicherer, Dienstleister, Handwerker, Bank)'
  core_insights:
    - 'KI schlaegt vor, Mensch entscheidet — Review-Queue mit Provenance, kein stiller KI-Write (plattformweites Prinzip)'
    - 'SharePoint bleibt DMS; Steckbrief haelt Links + Metadaten, kein Blob-Duplikat'
    - 'Read-only Sync v1; Write-Back pro Feld schrittweise ab v1.1 — keine Konfliktbehandlung'
    - 'Steckbrief ergaenzt strukturelle Luecken in Impower/Facilioo, ist nicht nur Aggregations-Layer'
classification:
  projectType: 'web_app'
  domain: 'general (Immobilien-/Hausverwaltung)'
  complexity: 'medium-high'
  projectContext: 'brownfield'
inputDocuments:
  - docs/brainstorming/objektsteckbrief-2026-04-21.md
  - docs/objektsteckbrief-feld-katalog.md
  - docs/index.md
  - docs/project-overview.md
  - docs/architecture.md
  - docs/data-models.md
  - CLAUDE.md
workflowType: 'prd'
project_name: 'Dashboard KI-Agenten'
author: 'Daniel Kroll'
date: '2026-04-21'
topic: 'Objektsteckbrief v1 — zentrale Objektsicht ueber Impower + Facilioo'
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 1
  projectDocs: 5
  additional: 1
projectType: 'brownfield'
---

# Product Requirements Document - Dashboard KI-Agenten

**Author:** Daniel Kroll
**Date:** 2026-04-21
**Topic:** Objektsteckbrief v1

## Executive Summary

Der **Objektsteckbrief** ist das dritte Modul der Dashboard-KI-Agenten-Plattform (nach SEPA-Mandat M1–M3 und Mietverwaltung M5) und erweitert die Plattform von **prozessorientierten Einzel-Workflows** zu einer **zentralen Stammdaten- und Pflegesicht pro Immobilienobjekt**. Zielnutzer sind die Mitarbeitenden der DBS Home GmbH in der WEG- und Mietverwaltung; sekundaer konsumieren die bestehenden und kuenftigen KI-Agenten der Plattform den Steckbrief als gemeinsame Ground-Truth.

Der Steckbrief loest zwei strukturelle Probleme, die heute im Alltag parallel auftreten: (1) **Daten-Fragmentierung** — operative Informationen liegen verteilt in Impower (Stammdaten, Finanzen), Facilioo (Beschluesse, Tickets), SharePoint (Dokumente) und Excel/Kopf (der Rest), ohne objekt-zentrierte Gesamtsicht; (2) **Fehlende Pflegerouten fuer Daten, die keines der SoR-Systeme strukturiert abbildet** — Absperrpunkte mit Foto, Heizungs-Steckbrief, Versicherungs-Portfolio mit Wartungsnachweisen als Deckungsbedingung, Verwaltervertrag-Strukturfelder, Grundbuch-Pflichtangaben, Menschen-Notizen zu Eigentuemern. v1 loest Problem (1) via Read-only-Mirror + Live-Pull und Problem (2) via eigenem Datenmodell mit Foto-Pipeline gegen SharePoint.

Ein gleichrangiges Ziel ist der **Beitrag zur KI-Strategie der Plattform**: der Steckbrief wird zur maschinenlesbaren Ground-Truth, die kuenftige Agenten (TE-Scan, Beschluss-Analyse, Versicherungs-Check) ueber einen Context-Pack-Endpoint konsumieren — ohne dass jeder Agent seine eigene Datenextraktion wiederholt.

### What Makes This Special

Drei Eigenschaften heben den Steckbrief strukturell von dem ab, was Impower, Facilioo, SharePoint und Excel heute im Zusammenspiel leisten:

1. **Due-Radar global** — eine portfolio-weite Ablauf-Ansicht (Versicherungen, Wartungen, Vertraege mit Ablauf < 90 Tage) ueber alle Objekte. Heute unmoeglich, weil kein System das Portfolio querschneidet. Killer-Use-Case aus der Brainstorming-Session.
2. **Pflegegrad-Score pro Objekt** — macht Datenqualitaet quantifizierbar (Completeness-Rate, aeltestes "Letzte Aktualisierung") und priorisierbar. Ersetzt das "Bauchgefuehl", welche Objekte pflegeseitig unterversorgt sind.
3. **Normalisierte Seiten-Entitaeten + Registries ab v1** — Versicherer, Dienstleister/Handwerker, Bank, Ablesefirma, Eigentuemer, Mieter sind eigene Tabellen mit Detailseiten und Aggregationen (Gesamtpraemie pro Versicherer, Gewerke-Historie pro Handwerker, verbrannte-Erde-Flag global sichtbar). Das ist der Unterschied zwischen "noch einem Formular" und einem **Portfolio-faehigen** Datenmodell.

Getragen wird das Ganze von drei architektonischen Leitplanken, die als plattformweite Prinzipien gelten:

- **"KI schlaegt vor, Mensch entscheidet"** — jede KI-Aussage landet in einer Review-Queue mit Provenance-Eintrag; es gibt keinen stillen KI-Write. Feld-Provenance-Tabelle (Quelle, Zeitstempel, Confidence) macht jeden Wert genealogisch nachvollziehbar.
- **Read-only Sync in v1, Write-Back pro Feld ab v1.1** — keine Konfliktbehandlung, deutlich einfachere Implementation, Praxis-getriebenes Wachstum statt Big-Bang-Bidirektionalitaet.
- **SharePoint bleibt DMS** — der Steckbrief haelt Drive-Item-IDs + Metadaten, kein Blob-Duplikat, keine parallele Dokumentenverwaltung.

### Portfolio & Classification

| Dimensionierung | Wert |
|---|---|
| **Aktives Portfolio** | ~50 Objekte (DBS Immobilienverwaltung GmbH) |
| **Primaer-User** | 7 interne Mitarbeitende |
| **Launch-Ziel v1** | Ende April 2026 (~9 Tage ab 2026-04-21) |
| **KPI-Messzeitraum-Start** | Go-Live-Datum, nicht Projekt-Start |

| Projekt-Dimension | Wert |
|---|---|
| **Projekt-Typ** | Web-App — FastAPI-Backend mit Jinja2 + HTMX, server-rendered (kein SPA, kein npm-Stack) |
| **Domain** | Immobilien-/Hausverwaltung (kein regulierter Sektor; DSGVO-relevant wegen personenbezogener Daten + Anthropic-Drittland-Uebermittlung, AVV geklaert) |
| **Komplexitaet** | medium–high — nicht wegen Regulierung, sondern wegen Integrations-Oberflaeche (Impower Read+Write, Facilioo Read, SharePoint Graph-API, Anthropic LLM) und der Normalisierung neuer Entitaeten (Police, Wartungspflicht, Dienstleister, Schadensfall, Bank) als eigenstaendige Registries |
| **Kontext** | Brownfield — neuer Modul-Strang parallel zu SEPA (M1–M3) und Mietverwaltung (M5) im bestehenden Python-3.12-Monolithen; nutzt Platform-Core (Auth, Permissions, Audit, Claude-Client, Impower-Connector) ohne Core-Investment |

## Success Criteria

### User Success

- **Onboarding-Geschwindigkeit:** Ein neuer Mitarbeiter findet an Tag 1 zu einem zugewiesenen Objekt alle relevanten Infos (Absperrpunkte, Heizung, Verwaltervertrag, Beiraete, offene Pendenzen) in **≤ 10 Min** ohne Rueckfrage. Baseline heute: 1–2 Std + Rueckfragen.
- **Notfall-Zugriff:** Wasser-/Strom-Absperrung + Heizungs-Stoerungsnummer sind vom Objekt-Detail in **≤ 30 Sek** erreichbar, auch mobil.
- **Review-Queue-Latenz:** KI-Vorschlaege werden im **Median ≤ 1 Arbeitstag** approved/rejected, **P95 ≤ 5 Arbeitstage**. Low-Confidence-Vorschlaege landen nicht stumm auf Halde.
- **Due-Radar-Wirkung:** Null unbeabsichtigte Kuendigungsfenster-Misses bei Policen/Wartungen nach v1 — Aufmerksamkeit wird frueh getriggert statt am Ablauftag.

### Business Success

**12-Monats-Ziele:**

- **Pflegegrad portfolio-weit:** **≥ 80 %** der aktiven Objekte (≥ 40 von 50) erreichen Pflegegrad-Score **≥ 50 %**; Top-10-Objekte (nach Einheiten) erreichen **≥ 70 %**.
- **Portfolio-Transparenz wird genutzt:** Mindestens **eine** datengetriebene Portfolio-Entscheidung innerhalb von 6 Monaten nach v1 (Versicherer-Konsolidierung, Dienstleister-Rauswurf oder aehnliches).
- **Wartungsnachweis-Compliance:** **≥ 95 %** der Policen haben ihre verknuepften Wartungspflichten mit aktuellem Nachweis — direkte Deckungs-Absicherung.
- **KI-Strategie-Baustein:** Mindestens ein weiterer KI-Agent (TE-Scan oder Beschluss-Analyse) nutzt den Steckbrief-Context in v1.1, ohne eigene Datenextraktion.

**3-Monats-Zwischenziele (Kurs-Indikator, ~Ende Juli 2026):**

- **≥ 10 Objekte** (20 % des Portfolios) auf Pflegegrad **≥ 50 %** — Signal, dass das Pflegeverhalten angelaufen ist.
- **Review-Queue wird regelmaessig geleert** (Median-Latenz halten).
- **Due-Radar hat mindestens einmal frueh alarmiert** (Ablauf < 90 Tage entdeckt vor manueller Meldung).

### Technical Success

- **Sync-Stabilitaet:** Impower-Mirror Nightly (Stammdaten/Finanzen); Facilioo-Tickets **1-Min-Polling, Delta-Only** wenn Server `ETag` / `If-Modified-Since` unterstuetzt (Default Full-Pull); Bank-Saldo Live-Pull beim Render. Fehlerrate **< 1 %** ueber 30 Tage.
- **Performance:** Objekt-Detailseite laedt **< 2 s P95** (inkl. Live-Pull-Saldo) bei 50 Objekten, Headroom fuer 150.
- **Provenance-Vollstaendigkeit:** **100 %** der Schreibvorgaenge (auch Mirror) haben einen `field_provenance`-Eintrag — keine verwaisten Werte.
- **KI-Hart-Grenze:** **0** Befunde im Audit-Log, wo ein KI-Agent ohne Review-Queue-Eintrag in den Steckbrief geschrieben hat. Strukturell erzwungen, nicht nur per Policy.
- **Review-Queue-Praezision:** Approve-Rate **≥ 70 %** im ersten Quartal nach Launch — darunter → Prompt-Nachsteuerung noetig.

### Measurable Outcomes (3 Leit-KPIs)

1. **Pflegegrad-Score-Median** ueber alle aktiven Objekte, 12M nach Launch — Ziel **≥ 60 %**.
2. **Verhinderte Ablauf-Ueberraschungen** via Due-Radar, 12M nach Launch — dokumentiert **≥ 10** Faelle.
3. **Notfall-Zeit-bis-zur-Info** Median vom Objekt-Detail — **≤ 30 Sek**.

## Product Scope

### MVP — v1 (Launch-Ziel Ende April 2026)

**Cluster-Abdeckung (aus Feld-Katalog):**

- **Cluster 1 Stammdaten & Einheiten-Struktur** komplett — ID-Kette (Impower/Facilioo/WEG-Nr./short_code), Eigentuemerliste mit Stimmrechten (Mirror).
- **Cluster 4 Technik & Gebaeudesubstanz** komplett — Absperrpunkte mit Foto, Heizungs-Steckbrief (inkl. Stoerungsnummer), Zugangscodes (encrypted), Objekt-Historie strukturiert (year_built, year_roof, …), bekannte Handwerker als FK-Liste.
- **Cluster 6 Finanzen** komplett — Bankkonten + Saldo (Live-Pull), Ruecklage + Historie, Wirtschaftsplan-Status, SEPA-Mandate, Sonderumlagen.
- **Cluster 8 Versicherungen & Wartungspflichten** komplett — `Police`-Tabelle, `Wartungspflicht`-Tabelle mit Policen-Verweis, `Schadensfall`-Tabelle, Risiko-Attribute.
- **Cluster 2/3/5/7/9/10 nur Teil-Abdeckung, wo fuer MVP noetig** — z.B. `current_owner`/`current_tenant` als FK am Objekt fuer Notfall-Use-Case; Rest folgt in v1.1.

**Registries v1:**

- **Versicherer-Detailseite + Listenansicht** (Gesamtpraemie p.a., Schadensquote, Ablauf-Heatmap < 90 Tage, verbundene Objekte).
- Dienstleister-Tabelle existiert (FK aus Cluster 4 + 7), aber **Dienstleister-Detailseite folgt in v1.1**.
- Alle weiteren normalisierten Entitaeten (Bank, Eigentuemer, Mieter, Ablesefirma, Zaehler) als Tabellen mit FKs angelegt, Detailseiten in v1.1.

**System-Features v1:**

- **Pflegegrad-Score** pro Objekt (Cluster 1/4/6/8 als Basis; spaetere Cluster erweitern Score-Basis).
- **Feld-Provenance** (Tabelle + Audit-Trail pro Feld).
- **Review-Queue** (Tabelle + UI-Badge "N Vorschlaege offen" pro Objekt).
- **Due-Radar global** — portfolio-weite Ablauf-Ansicht (Policen, Wartungspflichten, Verwaltervertraege < 90 Tage).

**Sync & Integration v1:**

- **Impower-Mirror Nightly** (Cluster 1 + 6), Swagger-getriebene DTOs.
- **Facilioo-Ticket-Mirror 1-Min** (`FaciliooTicket`-Entitaet), Delta-Only wenn Server-Support.
- **Bank-Saldo Live-Pull** beim Objekt-Detail-Render.
- **SharePoint Graph-API** — Foto-Upload fuer Cluster 4 (Absperrhaehne, Heizung, Sicherungskasten). DMS-Browse + Linking folgt in v1.1.

**Quer-Funktionen (aus Plattform-Core, kein Neu-Invest):**

- Rollen-Zugriff auf Objekt-Ebene via existierendes Permissions-Modell.
- Audit-Log fuer alle Schreibaktionen ueber existierenden `audit()`-Helper.
- HTMX-Swaps + Sidebar-Layout konsistent mit SEPA/Mietverwaltung.

### Growth Features (v1.1+, Wochen nach Launch)

- **Cluster 2 Einheits-Steckbrief** komplett (Grundriss, Ausstattung, Zaehler, Unit-Bilder).
- **Cluster 3 Personen & Vorgaenge** komplett (Tenant-History, Offene Vorgaenge aggregiert, Menschen-Notizen).
- **Cluster 5 Medien** komplett (Objekt-Galerie, Unit-Galerie, POI strukturiert).
- **Cluster 7 Verwaltervertrag + Dienstleister-Registry** — eigene Detailseite mit Gewerke-Historie + verbrannte-Erde-Flag.
- **Cluster 9 Recht & Governance** (Facilioo-Beschluesse/Pendenzen, TE strukturiert, Rechtsstreitigkeiten, Meeting-Minutes-Links).
- **Cluster 10 Baurecht-Kern** (Grundbuch, Energieausweis, Maengel-Stau, Denkmalschutz).
- **Write-Back** pro Feld schrittweise nach Praxis-Bedarf (keine Big-Bang-Bidirektionalitaet).
- **Registries-Detailseiten** fuer Bank · Eigentuemer · Mieter · Ablesefirma.
- **Event-Stream-Fundament** als Basis fuer den Notification-Hub.
- **Mieter-SEPA-Mandate** im Write-Flow (M5-Nachzug).

### Vision (v2+)

- **Custom-Module-Baukasten** — UI fuer neue Pflegebloecke ohne Programmierung (JSONB-Extension pro Objekt).
- **Feld-Level-ACL** → Cluster 11 Vertrauliches aktivieren (stille Risiken, verbrannte-Erde-Notizen rollen-gesichert).
- **TE-Scan-Agent** als eigener KI-Workflow (analog SEPA/Mietverwaltung, scannt Teilungserklaerung).
- **Context-Pack-Endpoint** `/objects/{id}/context` fuer LLM-Agenten.
- **Stichtags-Snapshot** fuer Uebergaben.
- **Semantische Suche** ueber Freitexte (Embeddings).
- **DD-Erweitert + ESG-Vollumfang** aus Cluster 10 (Gutachten, Foerder-Status, GEG/CO2/iSFP/Ladeinfra/PV/Wasser/Barrierefreiheit).

### MVP Strategy & Philosophy

**MVP-Typ: Problem-Solving MVP mit Platform-Primitive.** Zwei Ziele gleichzeitig:

1. **Problem-Solving** — konkrete User-Pains loesen, die heute in Impower/Facilioo/Excel nicht loesbar sind: Due-Radar global, Pflegegrad-Score, zentrale Objekt-Detailseite fuer die 7 Mitarbeitenden. Orientiert an den 5 User-Journeys, nicht an Feature-Katalogen.
2. **Platform-Primitive** — Review-Queue und Feld-Provenance als Fundament fuer alle kuenftigen KI-Agenten. Der v1-MVP **implementiert keine KI-Workflows**, baut aber die Infrastruktur, damit v1.1-Agenten (TE-Scan, Policen-Scan) ohne Datenmodell-Umbau andocken koennen.

**Warum nicht nur Problem-Solving?** Ohne die Primitive baut jeder spaetere KI-Agent einen eigenen Datenpfad — genau das Chaos, das die Plattform-Architektur vermeiden soll.

**Warum nicht reines Platform-MVP?** 7 User in 9 Tagen brauchen etwas, das direkt Wert bringt. Abstrakte Infrastruktur allein waere fuer den internen Akzeptanzaufbau falsch.

### Resource Requirements

- **Entwicklung**: 1 Entwickler (Daniel Kroll), Hauptzeit-Allocation fuer 9 Tage (~2026-04-22 bis 2026-04-30).
- **Parallele Wartung**: Bestehende Module M3 (SEPA Neuanlage-Zweig Live-Verifikation) und M5 (Mietverwaltungs-Write Live-Test) bleiben aktiv — **keine Unterbrechung erlaubt**, weil beide noch Live-Tests offen haben.
- **Testing-User**: 7 DBS-Mitarbeitende fuer User-Feedback ab Tag 5 (erste halbe Durchstich-Version verfuegbar). Mini-Umfrage Tag 30 nach Launch.
- **External Dependencies**: M365-Admin-Ticket fuer SharePoint-App-Registration (nicht von Daniel selbst schaltbar). Muss **Tag 1** gestellt werden.
- **Infrastruktur**: Kein zusaetzlicher Provider-Onboarding-Aufwand — Impower- und Anthropic-Zugaenge existieren, Facilioo-API-Zugang haengt als offener Punkt.

### Journey Coverage durch v1

| Journey | v1-Abdeckung |
|---|---|
| J1 Lena (Onboarding) | ✓ vollstaendig — Objekt-Detail mit Cluster 1/4/6/8 |
| J2 Markus (Bereitschaft, mobile) | ✓ vollstaendig — Mobile + Technik-Fotos + Dienstleister-Liste |
| J3 Petra (Buchhalterin) | ✓ Kern — Objekt-Liste + Finanzen + SEPA-Link; Sonderumlagen-Pflege v1.1 |
| J4 Julia (Versicherungen) | ✓ vollstaendig — Due-Radar + Versicherer-Registry mit Aggregationen |
| J5 Daniel (Admin) | ✓ vollstaendig — Review-Queue + Audit-Log-Erweiterung |

Alle 5 Journeys sind durch v1 abgedeckt. Integritaetscheck: der MVP-Cut laeuft nicht an der Praxis vorbei.

### Launch-Risiken (9-Tage-Window)

Domain- und Innovations-spezifische Risiken stehen thematisch in den Sektionen "Domain-Specific Requirements → Risiken und Mitigationen" und "Innovation & Novel Patterns → Risk Mitigation". Hier nur die **Launch-Perspektive**: wenn etwas schiefgeht, wie bleibt das 9-Tage-Ziel erreichbar?

**Technische Launch-Blocker:**

- **Facilioo-Integration nicht in 9 Tagen anbindbar** — Tag-3-Go/No-Go. No-Go → Cluster 3.3 (`open_tickets`) in v1.1 verschieben. MVP bleibt launch-faehig, weil keiner der MVP-Journeys kritisch an Facilioo haengt.
- **SharePoint Graph-API-Setup verzoegert sich durch M365-Admin-Ticket** — **Tag 1** anfragen, parallel zur Entwicklung. Fallback: Foto-Upload in lokalen `uploads/`-Ordner, SharePoint-Push auf v1.1.

**Akzeptanz-Risiko:**

- **7 User nehmen das Tool nicht an** — Mitigation: Journey 1 und 2 als "Killer-Erlebnisse" priorisieren + Onboarding-Session mit dem Team in der Launch-Woche.

**Ressourcen-Risiko:**

- **Parallele Wartung an M3/M5** — Prio-Regel: Prod-Fix vor v1-Feature. v1-Scope hat in den letzten beiden Tagen Puffer (Implementation-faehig in 7 Tagen, 2 Tage Contingency + User-Rollout).
- **Einzel-Entwickler-Risiko** — kein Bus-Factor-Fallback in 9 Tagen aufbaubar. Dokumentation in `docs/` + diesem PRD als Absicherung fuer Nachfolger.

## User Journeys

Fuenf Narrativ-Journeys decken die MVP-Capabilities ab. Personennamen sind fiktiv; bei Bedarf spaeter durch reale Rollenzuschnitte ersetzbar.

### Journey 1 — Lena, neue Mitarbeiterin, Tag 1 im Objekt (Happy Path)

**Situation.** Lena hat gestern bei DBS Home angefangen. Ihre Chefin weist ihr die Objekte HAM61 (Floegel) und BRE11 (Kulessa) zu. Alte Mitarbeiterin: "Alles Wichtige steht in SharePoint, den Rest weiss Carsten." Carsten ist heute im Urlaub. Lena ist Eigentuemerversammlung am Freitag, sie muss bis dahin sprachfaehig sein.

**Handlung.** Lena oeffnet `dashboard.dbshome.de`, klickt auf "Objekte", waehlt HAM61. Das Objekt-Detail zeigt im oberen Drittel die **Stammdaten** (Adresse, Eigentuemerliste mit Stimmrechten, WEG-Nr.), darunter einen **Pflegegrad-Badge** "Pflegegrad 72 %". Sie scrollt weiter: **Technik-Sektion** mit Fotos der Absperrpunkte, Heizungs-Karte (Viessmann, 2018, Wartungsfirma Heinemann + Hotline), strukturierte Objekt-Historie ("Dach: 2021, Leitungen: unbekannt"). **Finanzen-Sektion**: aktueller Saldo (live-pull aus Impower), Ruecklage 45.000 EUR, Wirtschaftsplan-Status "beschlossen 2026-01". **Versicherungen-Sektion**: 3 Policen mit Ablauf-Daten, zwei davon rot markiert ("< 90 Tage — Due-Radar").

**Climax.** Lena findet in 6 Min alles, was sie fuer Freitag braucht — ohne Telefonat bei Carsten. Sie bemerkt, dass der Eigentuemer Floegel einen Nebenvermerk hat ("Beirat, kritisch bei Beschluessen, Sonderumlagen genehmigt nur nach Begehung") und notiert das im Vorbereitungs-Dokument.

**Resolution.** Neue Realitaet: Lena kommt am Freitag informiert in die Versammlung. Am Montag darauf uebernimmt sie eigenstaendig BRE11 und fuegt in der Technik-Sektion zwei Fotos von Sicherungskaesten hinzu, die sie bei einer Vor-Ort-Begehung gemacht hat.

**Capabilities revealed:**
- Objekt-Listen-View + Objekt-Detail-Seite mit Cluster-Sektionen.
- Pflegegrad-Score-Badge + Live-Pull fuer Saldo.
- Foto-Upload pro Technik-Feld (SharePoint Graph-API).
- Due-Radar-Flags in Policen-Liste.
- Strukturierte Objekt-Historie (year_built, year_roof, …).
- Menschen-Notizen-Feld pro Eigentuemer (MVP-relevanter Teaser aus Cluster 3).

### Journey 2 — Markus, Bereitschaftsdienst, Samstag 22:45 Uhr (Notfall / Edge Case)

**Situation.** Samstagabend, Markus ist Bereitschaft. Anruf: Mieter in BRE11 meldet Wasserschaden im Treppenhaus — Dichtung am Steigstrang platzt. Der Mieter ist panisch, Wasser steht schon im Keller. Markus sitzt im Auto, 20 Min Fahrtzeit.

**Handlung.** Markus oeffnet auf dem Handy das Dashboard, sucht "BRE11", tippt. Objekt-Detail laedt (responsive, < 2 s). Er **swiped direkt zur Technik-Sektion**: Foto des Haupt-Wasserabsperrpunktes "Keller links neben Heizungsraum, hinter der Tuer mit gelbem Schild". Darunter: Heizungs-Stoerungsnummer Heinemann + Hotline. **Sicherungskasten-Plan pro Einheit** zeigt, welche Einheit auf welchem Stromkreis liegt.

**Climax.** Markus ruft waehrend der Fahrt den Notfall-Handwerker Thiele (Sanitaer, aus der Dienstleister-Liste sichtbar + gespeichert als "kennt BRE11 aus 2024"). Thiele erreicht das Haus 5 Min nach Markus. Markus sperrt den Haupthahn, Thiele uebernimmt. Schaden minimal, Keller trocken bis 3 Uhr.

**Resolution.** Am Montag legt Markus in der Steckbrief-Versicherungs-Sektion einen **Schadensfall** an (`Schadensfall`-Entitaet mit Policen-Verweis, Datum, Einheit, geschaetzte Summe). Die Versicherer-Detailseite aggregiert das in der Schadensquote.

**Capabilities revealed:**
- Mobile-taugliche Objekt-Suche + Detail-Seite (Tailwind responsive).
- Technik-Fotos mit **Standortbeschreibung** als Text-Feld (nicht nur Bild).
- Dienstleister-Liste pro Objekt mit "kennt-dieses-Objekt"-Flag.
- `Schadensfall`-Entitaet mit FK zur Police → Aggregations-View beim Versicherer.

### Journey 3 — Petra, Buchhalterin, Monatsabschluss April

**Situation.** Petra macht Monatsende ueber alle 50 Objekte. Heute Morgen braucht sie Saldostaende, Sonderumlage-Status und die Liste der Objekte mit offenen Rueckbuchungen. Ihre bisherige Route: 50x Impower-Kontoauszug-Ansicht oeffnen, Excel-Liste pflegen.

**Handlung.** Petra geht auf das Dashboard, oeffnet die **Objekt-Liste** (tabellarisch, sortierbar). Sie sortiert nach `reserve_current` absteigend — drei Objekte haben rote Badges "Ruecklage unter Zielwert". Sie klickt rein: Objekt-Detail zeigt **Ruecklage-Historie als Sparkline** (6 Monate), `reserve_target_monthly` aus Impower. Die Finanzen-Sektion listet **SEPA-Mandate** mit Status + letzten Einzuegen — die Rueckbuchungen sind als rote Flags sichtbar.

**Climax.** Petra erkennt an einem Objekt (GVE1), dass drei Einzuege in Serie zurueckgebucht wurden. Sie oeffnet den SEPA-Mandat-Flow (bestehendes Modul) direkt aus dem Objekt heraus und schickt dem Eigentuemer eine Mahnung.

**Resolution.** Monatsende in ~45 Min fertig statt 3 Std. Petra nimmt sich die uebrige Zeit, um Sonderumlage-Status-Fristen in die Steckbrief-`special_contributions`-Liste nachzupflegen, was sie bisher in Excel gemacht hat.

**Capabilities revealed:**
- Objekt-Liste mit **sortierbaren / filterbaren Spalten** (Saldo, Ruecklage, Mandat-Status).
- Sparkline fuer Ruecklage-Historie.
- Tiefe Integration zur bestehenden SEPA-Module (Link vom Objekt ins Mandat).
- Due-Radar-Erweiterung: Flag "Ruecklage < Zielwert" (nicht nur Zeit-basiert).

### Journey 4 — Julia, Versicherungs-Koordination, Due-Radar-Alarm (Differentiator-Journey)

**Situation.** Julia koordiniert die Versicherungen ueber alle 50 Objekte. Bisher: einmal im Quartal setzt sie sich 2 Tage hin, oeffnet jede Police in SharePoint, pflegt eine Excel-Liste. Jaehrlich gehen im Schnitt **2–3 Kuendigungsfenster** durch — Altvertraege laufen automatisch weiter, obwohl die Konditionen schlecht sind.

**Handlung.** Julia oeffnet das Dashboard. Die **Due-Radar-Seite** zeigt oben **7 Policen im 90-Tage-Fenster**, sortiert nach Kuendigungsfrist. Pro Police: Versicherer, Objekt, Summe, Laufzeit-Ende, bis wann kuendbar. Zwei davon sind rot ("< 30 Tage — dringend"). Julia klickt auf "Versicherer: Rhion" — die **Versicherer-Detailseite** zeigt: 14 Policen ueber 11 Objekte, Gesamtpraemie p.a. 89.400 EUR, Schadensquote 34 %, Ablauf-Heatmap (5 Policen in den naechsten 180 Tagen).

**Climax.** Julia faellt auf: die Rhion-Konditionen wurden seit 2023 nicht neu verhandelt, die Schadensquote rechtfertigt Preisnachlass. Sie ruft den Makler an mit einer vorbereiteten Aggregations-Liste als Verhandlungsbasis.

**Resolution.** Nach 3 Monaten Verhandlung senkt DBS die Rhion-Praemie ueber alle 14 Policen um 11 %. Erste **datengetriebene Portfolio-Entscheidung** (Business-KPI fuer 6M erreicht). Ohne Steckbrief waere das nicht entstanden — die Aggregation war in Impower und SharePoint nicht moeglich.

**Capabilities revealed:**
- Due-Radar-Global-View (Listenansicht quer ueber Portfolio, nicht pro Objekt).
- Versicherer-Detailseite mit **Aggregationen** (Policen-Anzahl, Gesamtpraemie, Schadensquote, Ablauf-Heatmap).
- `Police`-Entitaet muss `notice_period_months` + `next_main_due` als Pflichtfelder fuehren.
- `Schadensfall`-Entitaet muss in der Versicherer-Aggregation als Quote sichtbar sein.

### Journey 5 — Daniel, Admin / Platform-Owner, Review-Queue-Triage (Governance)

**Situation.** Daniel oeffnet Montags das Admin-Dashboard. Uebers Wochenende hat der nightly Impower-Mirror-Job gelaufen. Er will pruefen, ob Daten konsistent sind und ob die Review-Queue abgearbeitet wird.

**Handlung.** Admin-View zeigt: **42 Review-Queue-Eintraege gesamt, davon 7 aelter als 3 Tage**. Er filtert auf "aelter als 3 Tage" — alle gehoeren zu Julia (Versicherungs-Policen-Extraktionen aus Policen-PDFs). Er sieht, dass Julia im Urlaub war. Er filtert nach Feld-Typ: die 7 Vorschlaege sind alle IBAN-Extraktionen (aus neuen Bankdaten der Versicherer). Er approved 5 nach Stichprobe, rejected 2 mit Hinweis "falsche Police zugeordnet" — der KI-Prompt wird nachjustiert.

**Climax.** Daniel sieht in `/admin/logs` den Audit-Trail: jeder approve/reject ist protokolliert, mit User-ID und Zeitstempel. **0 KI-Direkt-Writes** ohne Queue-Eintrag — die Hart-Grenze haelt.

**Resolution.** Wochenausblick: die Median-Latenz der Queue liegt bei 0.6 Arbeitstagen, P95 bei 4 Tagen (knapp unter Ziel). Daniel baut im Laufe der Woche einen zusaetzlichen Filter ein, der Urlaubs-Abwesenheit automatisch markiert, damit Vorschlaege nicht einfach liegen bleiben.

**Capabilities revealed:**
- **Admin-Dashboard** fuer Review-Queue mit Filtern (Alter, Feld-Typ, User).
- Audit-Log-View `/admin/logs` (existiert schon) muss Steckbrief-Actions tracken.
- `field_provenance` als Query-Quelle fuer "welche Felder wurden von KI vs. Mensch befuellt".
- Rollenbasiertes Einschraenken: nur `admin`-Rolle sieht alle Queues portfolio-weit.

### Journey Requirements Summary

Die 5 Journeys decken zusammen die MVP-Capabilities ab:

| Capability | J1 | J2 | J3 | J4 | J5 |
|---|---|---|---|---|---|
| Objekt-Detailseite mit Cluster-Sektionen | ✓ | ✓ | ✓ | — | — |
| Objekt-Listen-View mit Sortierung/Filter | — | — | ✓ | ✓ | — |
| Pflegegrad-Score | ✓ | — | — | — | ✓ |
| Technik mit Foto + Standortbeschreibung | ✓ | ✓ | — | — | — |
| Heizung + Dienstleister-Liste pro Objekt | ✓ | ✓ | — | — | — |
| Finanzen: Live-Saldo + Ruecklage + SEPA-Link | ✓ | — | ✓ | — | — |
| Police + Wartungspflicht + Schadensfall | ✓ | ✓ | — | ✓ | — |
| Due-Radar global | — | — | — | ✓ | — |
| Versicherer-Registry mit Aggregationen | — | — | — | ✓ | — |
| Review-Queue + Provenance | — | — | — | — | ✓ |
| Audit-Log-Erweiterung | — | — | — | — | ✓ |
| Mobile-taugliche Ansicht | — | ✓ | — | — | — |

**Gap-Kommentar zu "klassischen" Journey-Typen aus dem Step-Template:**

- **API/Integration-Journey** — im MVP nicht relevant, weil der Context-Pack-Endpoint `/objects/{id}/context` in v2 liegt. Wenn in v1.1 erste KI-Agenten lesen (TE-Scan), folgt Journey dort.
- **Support/Troubleshooting** — kein externer User-Support, weil Tool nur intern. "Support" bei 7 Usern = Daniel selbst, das ist Journey 5.

## Domain-Specific Requirements

Domain ist `general` (Immobilien-/Hausverwaltung) mit Einstufung **medium–high** wegen Integrations-Oberflaeche und DSGVO-Pflicht. Kein regulierter Sektor, aber die Kombination aus personenbezogenen Daten, KI-Verarbeitung und Drittsystemintegration erfordert fokussierte Vorgaben. Alle Punkte bauen auf Plattform-Core auf (AuditLog, Permissions, OAuth-Gate, Hosted-Domain-Check, AVV-Klaerung fuer Anthropic).

### Compliance & Regulatorik

- **DSGVO-Verarbeitungs-Grundlage**: Verarbeitung personenbezogener Daten (Eigentuemer-, Mieter-, Beirats-Kontakte + Menschen-Notizen) im Rahmen der Verwalter-Vertraege mit den WEGs. Rechtsgrundlage: Art. 6 Abs. 1 lit. b (Vertragserfuellung). Keine neue Rechtsgrundlage noetig, aber die Datenkategorien erweitern sich gegenueber SEPA/Mietverwaltung.
- **Anthropic-Drittland-Uebermittlung**: AVV laeuft ueber die Commercial-API (Plattform-Backlog Punkt 3, geklaert). Fuer den Steckbrief muss die DSFA-Light ergaenzt werden, sobald der erste KI-Vorschlag-Flow live ist (Policen-/Vertrags-PDF-Extraktion). Information der Betroffenen: in der internen Datenschutz-Erklaerung fuer DBS-Mitarbeitende ergaenzen (nur interne Rolle).
- **Kein regulierter Sektor**: keine BaFin, keine FDA, keine HIPAA. Keine formellen Audits.
- **Aufbewahrung**: Objekt-Daten haben Vertrags-Lebenszyklus (= Dauer der Verwalter-Vertraege + gesetzliche Nachlauffrist). Konkrete Loesch-Konzepte fuer disabled Eigentuemer/Mieter sind in v1 nicht im Scope, werden mit Ausbau (v1.1+) nachgezogen.

### Technische Constraints

- **Access Control**: Bestehendes Permissions-Modell der Plattform wird wiederverwendet (flache Permissions + `resource_access` auf Workflow-Ebene). Neu fuer Steckbrief:
  - Neue Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `registries:view`, `registries:edit` in `app/permissions.py:PERMISSIONS` registrieren + in Default-Rollen seed (admin: alle, user: view+edit+approve_ki, registries:view).
  - `resource_access` um neuen `resource_type="object"` erweitern (aktuell nur `"workflow"`). Damit kann User-Zugriff pro Objekt spaeter eingeschraenkt werden. v1: alle User duerfen alle 50 Objekte sehen.
- **Encryption at Rest**: Zugangscodes (`entry_code_main_door`, `entry_code_garage` in Cluster 4) werden symmetrisch verschluesselt gespeichert. Default: `cryptography.fernet` mit Schluessel aus `SECRET_KEY` via HKDF abgeleitet. Kein KMS-Setup fuer v1. Schluessel-Rotation-Plan: kein Enforcement in v1, dokumentieren fuer v1.1 (separater Steckbrief-Key in Env `STECKBRIEF_FIELD_KEY`).
- **Encryption in Transit**: HTTPS ist durch Elestio-Reverse-Proxy + TLS auf Produktivdomain gegeben (M4-Umsetzung separat).
- **Audit-Log-Erweiterung**: Alle Schreib-Actions des Steckbrief-Moduls gehen ueber den existierenden `audit()`-Helper. Neue Action-Keys: `object_created`, `object_field_updated`, `object_photo_uploaded`, `review_queue_approved`, `review_queue_rejected`, `registry_entry_created`, `registry_entry_updated`. In `docs/architecture.md` §8 nachziehen.
- **Anonymisierung KI-Prompts**: Bei PDF-Extraktionen werden PDFs an Anthropic gesendet; das war im SEPA/Mietverwaltungs-Kontext bereits so. Keine Aenderung gegenueber bestehendem Plattform-Verhalten, jede Uebermittlung ueber `audit()` nachvollziehbar.

### Integration Requirements

Die Steckbrief-Architektur steht oder faellt mit der Qualitaet der Integrationen. v1 definiert vier Integrationen:

- **Impower Read-API** (bestehend, Client `app/services/impower.py`). Neu fuer Steckbrief:
  - Nightly-Mirror-Job fuer Cluster 1 (Stammdaten) + Cluster 6 (Finanzen). Neuer Service (vorgeschlagen `app/services/steckbrief_impower_mirror.py`), wiederverwendet den existierenden Impower-Client.
  - Live-Pull-Endpoint fuer Bank-Saldo beim Render.
  - Spring-Data-Pagination via existierendem `_get_all_paged` Helper.
  - Rate-Limit-Gate (0.12 s Mindestabstand) bleibt; Mirror-Job darf Gate nicht umgehen.
- **Facilioo Read-API** (NEU — im aktuellen Projekt nicht integriert). Risiko-Punkt fuer 9-Tage-Launch:
  - Swagger/OpenAPI-Spec besorgen, Auth-Flow klaeren.
  - Client nach Muster von `app/services/impower.py` bauen (Rate-Limit, Retry, Timeout, Pagination).
  - Entitaeten: `FaciliooTicket` (v1 MUST), `FaciliooDecision`/`Pendency`/`Request` (v1.1).
  - Polling-Intervall: 1 Min, Delta-Only via ETag/If-Modified-Since sobald Server-Support klar.
  - **Fallback**: wenn Facilioo binnen 9 Tagen nicht stabil anbindbar ist, Cluster-3.3-`open_tickets` nach v1.1 verschieben. Keiner der MVP-Journeys haengt kritisch an Facilioo-Tickets.
- **SharePoint Graph-API** (NEU):
  - Service-Account + App-Registration bei Microsoft 365. Scopes: `Files.ReadWrite.All` (oder Site-scoped), `Sites.Read.All`.
  - Upload-Pfad-Konvention: `SharePoint/DBS/Objekte/{short_code}/{kategorie}/`.
  - Steckbrief speichert **nur** `drive_item_id` + Metadaten (filename, captured_at, uploaded_by, component_ref). Keine Blobs lokal.
  - v1: Upload-Endpunkt fuer Cluster-4-Komponenten-Fotos. Browse / DMS-Link-Darstellung in v1.1.
- **Anthropic API** (bestehend, Client `app/services/claude.py`): KI-Vorschlag-Workflows fuer Steckbrief sind **v1.1** (Policen-Scan, Verwaltervertrag-Scan). In v1 wird nur die Review-Queue-Infrastruktur gebaut, damit spaetere Agenten nahtlos andocken.

### Risiken und Mitigationen

| Risiko | Impact | Mitigation |
|---|---|---|
| Facilioo-API-Integration innerhalb 9 Tagen nicht machbar (Auth, DTOs, Delta-Support unklar) | Journey 1 nicht betroffen, aber Cluster 3.3 `open_tickets` fehlt in v1 | Hart: Facilioo auf v1.1 verschieben, wenn nach Tag 3 nicht stabil. MVP bleibt launch-faehig. |
| SharePoint Graph-API Service-Account-Setup braucht M365-Admin-Ticket | Foto-Upload haengt | Parallel zum Entwicklungs-Start anstossen, nicht am Ende. Fallback: Foto-Upload in lokalen `uploads/`-Ordner verschieben auf v1.1. |
| `resource_access` auf `resource_type="object"` erweitern wird nicht getestet rechtzeitig fertig | Alle 7 User sehen alle 50 Objekte ungewollt breit | v1-Akzeptanz: alle User sehen alle Objekte. Feingranulares Object-Level-ACL = Nice-to-have, v1.1. |
| Pflegegrad-Score-Formel liefert Werte, die von Usern nicht als fair empfunden werden | Akzeptanz-Risiko: User ignorieren den Score | Score in v1 mit einfacher Formel (Completeness-Rate der Pflichtfelder in Cluster 1/4/6/8 × Aktualitaets-Decay). Transparente Dokumentation der Formel in der UI als Info-Popover. Iteration in v1.1 nach User-Feedback. |
| Due-Radar Fehlalarme bei Policen mit unklaren `next_main_due`-Daten aus Initial-Migration | User-Vertrauen verliert | v1-MVP: manuelles Seeding der ~150 aktiven Policen (50 Objekte × ~3 Policen). KI-Extract folgt in v1.1. |
| Encryption-Schluessel (Zugangscodes) haengen an `SECRET_KEY` — Rotation bricht Entschluesselung | Nachtraeglicher Wartungs-Pain | Key-Derivation via HKDF mit `SECRET_KEY` + statischem Salt. Rotations-Plan dokumentieren fuer v1.1 (separater Steckbrief-Key in Env-Variable `STECKBRIEF_FIELD_KEY`). |
| Unklare Datenschutz-Frage zu Menschen-Notizen ("Beirat kritisch bei Beschluessen") | Rechtlich: Meinung ueber Person, Speicher-Legitimitaet zu pruefen | v1: Menschen-Notizen sind nur fuer `admin`-Rolle sichtbar, nicht fuer `user`. Verschiebt Cluster-11-Problem ("Vertrauliches") nicht vollstaendig, reduziert es. Finale Feld-Level-ACL in v2. |

## Innovation & Novel Patterns

Der Steckbrief ist keine Welt-Innovation — Property-Management-Tools mit Objektdaten-Aggregation existieren. Aber drei Muster sind **DBS-intern neuartig** und werden als Plattform-Primitive ueber den Steckbrief hinauswirken. Sie verdienen eine explizite Validierungs-Strategie, sonst scheitern sie leise.

### Detected Innovation Areas

1. **KI-Review-Queue als Plattform-Primitiv.** Jede KI-Aussage (auch aus kuenftigen Agenten wie TE-Scan oder Policen-Extract) landet zwingend in der Review-Queue mit Provenance-Eintrag, bevor sie in den Steckbrief gelangt. Keine Implementation-Wahl der einzelnen Agenten, sondern durchsetzbares Muster. Neu gegenueber SEPA (direkter PDF-Extract → Chat-Korrektur) und Mietverwaltung (Auto-Merge + User-Override) — dort ist Mensch-Review in den Workflow eingebaut, hier als System-Primitive abstrahiert.
2. **Portfolio-faehiges Datenmodell ab v1** (normalisierte Seiten-Entitaeten mit FKs). Die Entscheidung, Versicherer/Dienstleister/Bank etc. **nicht** als JSONB-Anhang pro Objekt zu modellieren, sondern als eigene Tabellen mit Objekt-FKs, ist der strukturelle Unterschied zu einem klassischen "Objektsteckbrief-Formular". Ermoeglicht Aggregations-Queries (Gesamtpraemie pro Versicherer) und spaetere Detailseiten ohne Daten-Umbau.
3. **Steckbrief als Context-Source fuer kuenftige KI-Agenten.** v2-geplant (`/objects/{id}/context`). Strategisch: statt jeder Agent extrahiert seine Felder selbst, liegt eine strukturierte Ground-Truth vor, auf die alle Agenten lesen. Risiko: Lock-in gegen die Qualitaet der Steckbrief-Daten — wenn die schlecht gepflegt sind, sind auch die Agenten schlecht.

### Market Context & Competitive Landscape

Der Markt fuer kommerzielle Property-Management-Plattformen (Casavi, etg24, Facilioo selbst, ImmoMaster, Domus 5000, vdw-Tools) haelt Objektdaten meist **funktions-getrieben** (Buchhaltung, Tickets, Dokumente) in getrennten Modulen mit limitierter Cross-Modul-Aggregation. Das Portfolio-Kreuz-Select ("alle Policen im Ablauf-Fenster ueber alle Objekte") ist in diesen Produkten entweder nicht vorhanden oder nur ueber Excel-Export + Pivot realisierbar. Der DBS-interne Steckbrief **ersetzt keins dieser Produkte** — er ergaenzt Impower/Facilioo um genau die portfolio-weite Datenhoheit + KI-Governance, die die Plattformen nicht standardmaessig liefern. Das Wertversprechen ist deshalb nicht "besseres Tool als Casavi", sondern "Ergaenzungs-Layer mit eigenem Wert pro Portfolio-KPI".

### Validation Approach

Pro Innovations-Baustein ein konkreter Validierungs-Weg — kein Auto-Go-Live:

- **Review-Queue-Akzeptanz.** Validierung durch Journey 5 (Daniel) ab Tag 1: Median-Latenz < 1 Arbeitstag, Approve-Rate ≥ 70 %. Fallback, wenn nach 30 Tagen die Queue zur Halde (> 50 offene Vorschlaege > 7 Tage alt) wird: **Eskalations-Regel** in v1.1 — Vorschlaege, die 5 Tage liegen, werden einem Admin explizit notifiziert, KI-Prompt-Runde reduziert Vorschlag-Volumen.
- **Pflegegrad-Score-Fairness.** Validierung in den ersten 4 Wochen durch direktes Feedback der 7 User: nach 30 Tagen Mini-Umfrage "Fuehlt sich der Score fair an?" + Vergleich Score-Ranking vs. User-Intuition "welche Objekte sind schlecht gepflegt". Abweichung > 30 % → Formel-Nachjustierung in v1.1. Transparenz-Mechanismus in der UI (Info-Popover mit Score-Komposition).
- **Due-Radar-Nutzung.** Nach 90 Tagen messen: hat Due-Radar zu mindestens **einer dokumentierten Aktion** gefuehrt (z. B. Policen-Kuendigung rechtzeitig, Wartungstermin gebucht)? Wenn nicht, klassisches "built but not used"-Problem — dann UI-Prominenz erhoehen (Startseiten-Widget statt separate View).
- **Portfolio-faehiges Datenmodell.** Technisch validiert durch v1.1-Registry-Detailseiten (Dienstleister, Bank, Mieter, Eigentuemer): wenn diese ohne Migration auf Basis des v1-Schemas entstehen koennen, hat die Normalisierung den Designtest bestanden.
- **Context-Pack fuer KI-Agenten (v2).** Wird ueber den ersten integrierten Folge-Agenten validiert (TE-Scan oder Policen-Scan). Erfolgs-Metrik: neuer Agent braucht ≤ 50 % des Implementation-Aufwands eines aequivalenten Agenten, der eigene Datenextraktion macht.

### Risk Mitigation

| Innovations-Risiko | Fallback |
|---|---|
| Review-Queue wird als Buerokratie wahrgenommen und umgangen (User pflegen haendisch statt KI-Vorschlaege zu reviewen) | Schrittweise KI-Einfuehrung: **v1 baut nur die Queue-Infrastruktur**, keine aktiven KI-Agenten. Erste KI-Vorschlaege erst in v1.1 nach User-Gewoehnung ans UI. |
| Normalisierte Entitaeten fuehren zu Over-Engineering bei 50 Objekten (fuer das Volumen nicht lohnend) | Anti-Risiko: die Tabellen kosten fast nichts; der Wert kommt bei Portfolio-Wachstum automatisch. Messbar am v1.1-Registry-Roll-out, ob sich das Muster traegt. |
| Pflegegrad-Score ist subjektiv und wird von Usern abgelehnt | Score als Soft-Signal, nicht als Hart-Ranking. v1-UI macht klar: "Orientierungshilfe, kein Leistungs-Indikator". Formel transparent + User-Feedback-Kanal. |
| Context-Pack-Idee scheitert spaeter, weil Steckbrief-Datenqualitaet heterogen ist | Hart in v1 akzeptiert: Context-Pack ist v2, v1 etabliert nur die Daten. Wenn Datenqualitaet nach 12M schlecht ist, wird Context-Pack auf "high-confidence-only"-Felder reduziert. |

## Web-App Specific Requirements

### Project-Type Overview

Server-rendered Multi-Page-App (MPA) mit progressiv interaktiven Fragmenten via HTMX 2. Kein SPA, kein npm/node-Build-Step, keine Client-JS-Frameworks. Interne Anwendung hinter Google-Workspace-OAuth-Gate (`@dbshome.de` Hosted-Domain-Check) — weder oeffentlich zugaenglich noch SEO-relevant. Das Steckbrief-Modul folgt den etablierten Plattform-Conventions der bestehenden Module SEPA und Mietverwaltung.

### Technical Architecture Considerations

- **Rendering-Modell**: MPA mit HTMX-Swaps. Jede Seite ist vollstaendig server-rendered (Jinja2 Templates), interaktive Teile (Sortier-Wechsel, Review-Queue-Approval, Inline-Edit) sind HTMX-Fragment-Swaps. Fragment-Templates starten mit Underscore (`_object_detail_section.html`, `_review_queue_row.html`), volle Seiten ohne.
- **Layer-Disziplin**: Neue Router `app/routers/objects.py`, `app/routers/registries.py`; Services nach Domaene (`app/services/steckbrief.py`, `app/services/steckbrief_impower_mirror.py`, `app/services/pflegegrad.py`, `app/services/review_queue.py`); Models unter `app/models/` pro Entitaet (`object.py`, `police.py`, `wartungspflicht.py`, etc.). Routers machen nur HTTP-IO, Services keinen Request-Kontakt.
- **DB**: Postgres 16, JSONB fuer flexible Felder (z. B. `field_provenance.value_snapshot`, `review_queue.proposed_value`). SQLAlchemy 2.0 typed `Mapped[...]`. UUIDs ueberall.
- **BackgroundTasks** fuer langlaufende Arbeit: Impower-Mirror-Nightly-Job, Facilioo-Mirror-1-Min-Job, KI-Vorschlag-Generierung (v1.1). Jeder BackgroundTask mit eigener `SessionLocal()` + `try/finally` mit `db.close()`, analog `run_mietverwaltung_write`.

### Browser-Matrix

- **Zielgruppe**: 7 interne Mitarbeitende. Kein Consumer-Markt.
- **Evergreen-Browser (latest + N-1)**: Chrome, Edge, Firefox, Safari.
- **Mobile**: Safari iOS 17+, Chrome Android latest — wichtig wegen Journey 2 (Bereitschaftsdienst Notfall-Zugriff mobil).
- **Kein Support fuer**: IE 11, alte Edge (pre-Chromium), Browser < latest N-1.
- **HTMX 2 + Tailwind (CDN)** — beides in allen Zielbrowsern unterstuetzt.

### Responsive Design

- **Tailwind-Breakpoints** wie in bestehenden Templates (`sm` / `md` / `lg` / `xl`).
- **Mobile-zuerst-Optimierung fuer die Notfall-Journey (J2)**: Objekt-Detailseite muss auf Smartphone nutzbar sein, Technik-Sektion mit grossen Touch-Targets, Fotos swipebar.
- **Desktop-zuerst-Optimierung fuer Buchhalterin-Journey (J3)**: Objekt-Listen-View als Tabelle mit 8–12 Spalten, sortierbar — auf Mobile faellt die Listenansicht in Card-Layout zurueck.
- **Keine separaten mobilen Templates** — ein Set von Templates mit responsive Tailwind-Klassen, wie im restlichen Projekt.

### Performance Targets

- **Objekt-Detailseite**: < 2 s P95 bei 50 Objekten, inkl. Live-Pull Bank-Saldo. Headroom auf 150 Objekte (P95 < 3 s).
- **Objekt-Listen-View**: < 1.5 s P95 bei 50 Zeilen. Sortier-/Filter-Wechsel via HTMX-Fragment-Swap < 500 ms.
- **Due-Radar-Global-View**: < 2 s P95 bei typischen 20–30 im-Fenster-Eintraegen.
- **Facilioo-Ticket-Polling** darf User-Seite nicht blockieren — laeuft als BackgroundTask, UI zeigt Cached-Snapshot.
- **Impower-Mirror-Nightly** laeuft zwischen 02:00–04:00 Uhr, keine User-Interaktion zu der Zeit.

Messbar via Browser-Devtools waehrend QA und ueber die bestehenden Uvicorn-Access-Logs (ggf. Request-Timing in `audit()`-Details ergaenzen).

### SEO Strategy

Keine. Anwendung ist komplett hinter OAuth-Gate. `X-Robots-Tag: noindex, nofollow` als Default-Header setzen, damit bei Fehlkonfiguration nichts extern indiziert wird.

### Real-Time Anforderungen

Keine echten Real-Time-Anforderungen in v1. Ausreichend sind:

- **HTMX-Polling** (`hx-trigger="every 2s"`) fuer aktive Ansichten wie Review-Queue bei geoeffnetem Queue-Editor — optional, kann auch rein auf Submit aktualisieren.
- **Meta-Refresh** fuer laufende BackgroundTasks (Muster aus M5 Mietverwaltung, `<meta http-equiv="refresh" content="6">`).
- **Live-Pull** beim Render fuer Bank-Saldo — nicht Real-Time, nur "aktuell beim Seitenaufruf".

Kein WebSocket, kein SSE, kein Polling unter 1 s.

### Accessibility Level

Keine WCAG-Zertifizierung noetig (interne Anwendung, keine externen Nutzer). Dennoch als Qualitaets-Grundsatz:

- **Tastaturnavigation** funktioniert fuer alle primaeren Flows (Objekt-Liste → Detail → Sektion → Feld-Edit → Save).
- **Fokus-Rings** nicht entfernen (Tailwind-Default beibehalten).
- **Ausreichender Kontrast** gemaess Tailwind-Standard (`text-slate-700 on white` und aehnliches).
- **Semantic HTML** (`<button>`, `<nav>`, `<main>`, `<table>` wo angebracht) statt Div-Huelle.
- **`alt` fuer Technik-Fotos** — mit Standortbeschreibung aus dem zugehoerigen Textfeld befuellen, so hat der Notfall-Handwerker bei defekter Bildanzeige immer noch Text.

### Implementation Considerations

- **Wiederverwendung Plattform-Core** (keine Neu-Implementationen):
  - Google OAuth + Session ueber `app/auth.py` + `get_current_user`.
  - Permission-Dependencies `Depends(require_permission(...))` mit den neuen Steckbrief-Keys.
  - Audit-Log ueber `audit()`-Helper, Transaktion mit Business-Change.
  - Jinja-Singleton aus `app/templating.py`; neue Globals (z. B. `pflegegrad_color`, `due_radar_badge`) dort registrieren.
  - HTMX + Tailwind ueber CDN aus `base.html` (kein neuer Build-Step).
- **Migrations-Reihenfolge**: linear auf `0009` aufbauen. Vor Anlage einer neuen Migration `ls migrations/versions/` pruefen, nicht blind auf CLAUDE.md vertrauen.
- **JSONB-Felder** immer mit `flag_modified` oder Reassignment, nie Mutation am Dict ohne Tracking.
- **Testing** analog zu SEPA/Mietverwaltung (Pytest + SQLite-in-Memory, Fixtures in `tests/conftest.py`, Mocks fuer Impower/Anthropic). Neue Tests:
  - Unit-Tests fuer `pflegegrad_score`-Formel (Edge-Cases: alle Felder leer, alle Felder voll, teilweise alt).
  - Unit-Tests fuer `review_queue`-Approve/Reject-Flows inkl. Audit-Eintrag.
  - Smoke-Tests fuer `/objects`, `/objects/{id}`, `/registries/versicherer`, `/due-radar` (unauthenticated → 302/403; authenticated → 200).
  - Mocks fuer Impower-Mirror-Job + Facilioo-Mirror-Job (Delta-Logik).

### Bewusst skipped per CSV (`skip_sections`)

- `native_features` — keine Desktop-/Mobile-Native-Features, reine Web-App.
- `cli_commands` — keine CLI-Oberflaeche.

## Functional Requirements

34 Functional Requirements in 6 Capability-Areas. Jedes FR ist actor-basiert, testbar, implementation-agnostisch. Keine UI-Details, keine Performance-Zahlen (die sind in NFRs), keine Technologie-Wahl.

**Diese Liste ist der bindende Capability-Contract fuer v1.** Was nicht hier steht, wird in v1 nicht gebaut. UX-Design, Architektur und Stories orientieren sich ausschliesslich an dieser Liste.

### Objekt-Detail & Cluster-Pflege

- **FR1:** Mitarbeitende koennen eine Objekt-Detailseite aufrufen, die Stammdaten, Technik, Finanzen und Versicherungen in strukturierten Sektionen zeigt.
- **FR2:** Mitarbeitende koennen Stammdatenfelder (Cluster 1) als read-only-Spiegel aus Impower sehen (Adresse, WEG-Nr., Eigentuemerliste mit Stimmrechten).
- **FR3:** Mitarbeitende koennen technische Daten (Cluster 4) pflegen: Absperrpunkte mit Foto + Standortbeschreibung, Heizungs-Steckbrief, Zugangscodes, Objekt-Historie (year_built, year_roof, …).
- **FR4:** Mitarbeitende koennen Finanzdaten (Cluster 6) als Impower-Spiegel sehen (Ruecklage, Wirtschaftsplan-Status, SEPA-Mandate) und den Bank-Saldo als Live-Wert beim Render.
- **FR5:** Mitarbeitende koennen Versicherungs-Portfolio (Cluster 8) pflegen: Policen, Wartungspflichten mit Policen-Verweis, Schadensfaelle. (Risiko-Attribute auf Policen-/Objekt-Ebene = v1.1.)
- **FR6:** Mitarbeitende koennen einen neuen Schadensfall direkt aus der Versicherungs-Sektion des Objekts anlegen.
- **FR7:** Mitarbeitende koennen die Ruecklage-Historie als Zeitreihe (sparkline-artig) pro Objekt einsehen.
- **FR8:** Admins koennen Menschen-Notizen zu Eigentuemern pflegen; diese Notizen sind fuer Nicht-Admin-Rollen nicht sichtbar.
- **FR9:** Mitarbeitende koennen Fotos pro Technik-Komponente hochladen und anzeigen; die Fotos werden in SharePoint gespeichert, das System haelt nur Drive-Item-ID + Metadaten.
- **FR10:** Mitarbeitende koennen Zugangscodes erfassen; das System speichert sie verschluesselt und zeigt sie nur authentifizierten Usern mit `objects:view`-Permission entschluesselt an.

### Portfolio-Navigation & Due-Radar

- **FR11:** Mitarbeitende koennen alle Objekte in einer Listenansicht mit sortierbaren und filterbaren Spalten sehen (mindestens: Saldo, Ruecklage, Mandat-Status, Pflegegrad).
- **FR12:** Mitarbeitende koennen die Objekt-Listenansicht auch mobil nutzen; auf kleinen Viewports faellt die Tabelle in ein Card-Layout zurueck.
- **FR13:** Mitarbeitende koennen eine Due-Radar-Ansicht aufrufen, die portfolio-weit alle Policen und Wartungspflichten mit Ablauf-Datum innerhalb der naechsten 90 Tage listet. (Verwaltervertraege = Cluster 7, v1.1.)
- **FR14:** Mitarbeitende koennen die Due-Radar-Ansicht nach Eintrags-Typ (Police / Wartung) und nach Ablauf-Schwere (< 30 Tage / < 90 Tage) filtern.
- **FR15:** Mitarbeitende koennen von jedem Due-Radar-Eintrag direkt zur Quell-Entitaet (Objekt, Police, Wartungspflicht) oder zur Registry-Detailseite springen.

### Registries & Aggregationen

- **FR16:** Mitarbeitende koennen eine Versicherer-Listenansicht aufrufen mit Aggregationen pro Versicherer (Policen-Anzahl, Gesamtpraemie p.a., Schadensquote, Anzahl verbundener Objekte).
- **FR17:** Mitarbeitende koennen eine Versicherer-Detailseite aufrufen mit allen verbundenen Policen, Ablauf-Heatmap, Schadensfaellen und einer Aggregation der verbundenen Objekte.
- **FR18:** Das System fuehrt normalisierte Entitaeten fuer Dienstleister/Handwerker, Bank, Ablesefirma, Eigentuemer, Mieter, Mietvertrag, Zaehler sowie Facilioo-Mirror-Entitaeten als eigenstaendige Tabellen mit Objekt-FKs — auch wenn deren Detailseiten erst in v1.1 entstehen.

### Datenqualitaet & KI-Governance

- **FR19:** Das System berechnet pro Objekt einen Pflegegrad-Score auf Basis von Feld-Completeness und Aktualitaet, sichtbar als Badge auf Detail- und Listen-Seite.
- **FR20:** Mitarbeitende koennen die Komposition des Pflegegrad-Scores in einer UI-Erlaeuterung nachvollziehen (welche Felder, welche Gewichte).
- **FR21:** Das System protokolliert fuer jeden Schreibvorgang auf einem Steckbrief-Feld einen Provenance-Eintrag (Quelle, Zeitstempel, User bzw. Sync-Job, Confidence bei KI-Vorschlaegen).
- **FR22:** Das System fuehrt eine Review-Queue fuer KI-Vorschlaege mit Ziel-Entitaet, Feldname, vorgeschlagenem Wert, Confidence und Status (pending / approved / rejected / superseded).
- **FR23:** Mitarbeitende koennen Eintraege in der Review-Queue approven oder rejecten; approve schreibt den Wert mit Provenance-Eintrag `ai_suggestion`, reject verwirft den Vorschlag und markiert ihn als abgelehnt.
- **FR24:** Admins koennen die Review-Queue portfolio-weit einsehen und nach Alter, Feld-Typ und Ziel-User filtern.
- **FR25:** Das System verhindert strukturell, dass ein KI-Agent direkt in Steckbrief-Felder schreibt, ohne zuvor einen Review-Queue-Eintrag zu erzeugen.

### Externe Integrationen & Sync

- **FR26:** Das System spiegelt Impower-Stammdaten (Cluster 1) und Finanzdaten (Cluster 6) periodisch (nightly) in den Steckbrief; jedes gespiegelte Feld erhaelt einen Provenance-Eintrag `impower_mirror`.
- **FR27:** Das System laedt den Bank-Saldo aus Impower live beim Render der Objekt-Detailseite.
- **FR28:** Das System pollt Facilioo-Tickets in Ein-Minuten-Takt und spiegelt sie als `FaciliooTicket`-Entitaet; wenn der Server ETag/If-Modified-Since unterstuetzt, laedt der Job nur Deltas.
- **FR29:** Das System kann Fotos ueber die Microsoft-Graph-API in definierte SharePoint-Ordner pro Objekt hochladen und haelt lokal nur die drive_item_id + Metadaten.
- **FR30:** Das System toleriert zeitweilige Unerreichbarkeit von Impower, Facilioo oder SharePoint ohne User-Seiten-Crash (UI zeigt gecachten Snapshot mit Stale-Hinweis).

### Zugriff, Rollen & Audit

- **FR31:** Nur Mitarbeitende mit Google-Workspace-Account unter `@dbshome.de` koennen sich anmelden (bestehendes OAuth-Hosted-Domain-Gate wiederverwendet).
- **FR32:** Das System unterstuetzt die Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `registries:view`, `registries:edit`, zuweisbar ueber Rollen oder User-Overrides.
- **FR33:** Das System schreibt fuer alle Steckbrief-Schreibaktionen (Objekt-Anlage, Feld-Edit, Foto-Upload, Review-Queue-Approve/Reject, Registry-Edit) einen Audit-Log-Eintrag mit User, Zeitpunkt und IP.
- **FR34:** Admins koennen die bestehende Audit-Log-View nach Steckbrief-spezifischen Actions filtern.

### Traceability-Check

- **Vision / Differentiator** → FR13–15 (Due-Radar), FR16–17 (Versicherer-Registry), FR19–20 (Pflegegrad), FR18 (Portfolio-Datenmodell-Fundament).
- **J1 Lena** → FR1, FR2, FR3, FR4, FR5, FR8, FR19.
- **J2 Markus** → FR3, FR9, FR6, FR12, FR30.
- **J3 Petra** → FR11, FR4, FR7.
- **J4 Julia** → FR13, FR14, FR15, FR16, FR17.
- **J5 Daniel** → FR22, FR23, FR24, FR25, FR33, FR34.
- **Domain-Requirements** → FR8 (Menschen-Notizen ACL), FR10 (Zugangscodes-Encryption), FR31 (OAuth-Gate), FR32 (Permissions), FR33–34 (Audit).
- **Innovation-Patterns** → FR21, FR22, FR25 (Review-Queue als Primitive), FR18 (Portfolio-Datenmodell).

Keine MVP-Scope-Capability ohne FR. Keine User-Journey ohne FR-Abdeckung.

## Non-Functional Requirements

Nur die fuer den Steckbrief wirklich relevanten NFR-Kategorien. Explizit weggelassen: Full-WCAG-Accessibility (interner User, Qualitaetsgrundsatz bereits in Web-App-Sektion dokumentiert), massive Scalability (50 Objekte / 7 User, kein Growth-Szenario), Internationalization (DBS-intern, Deutsch).

### Performance

- **NFR-P1:** Objekt-Detailseite laedt bei 50 Objekten mit P95 < 2 s, inklusive Live-Pull des Bank-Saldos aus Impower. Bei 150 Objekten (Wachstums-Headroom) P95 < 3 s.
- **NFR-P2:** Objekt-Listenansicht mit 50 Zeilen laedt P95 < 1.5 s. Sortier- oder Filter-Wechsel ueber HTMX-Fragment-Swap P95 < 500 ms.
- **NFR-P3:** Due-Radar-Global-View laedt P95 < 2 s bei typischem Volumen (20–30 Eintraege im 90-Tage-Fenster).
- **NFR-P4:** Versicherer-Detailseite mit Aggregationen ueber alle verbundenen Policen laedt P95 < 2 s bei bis zu 20 Policen pro Versicherer.
- **NFR-P5:** Foto-Upload nach SharePoint Graph-API reagiert fuer den User innerhalb P95 < 5 s pro Foto (max. 10 MB); bei groesseren Dateien laeuft der Upload in einer BackgroundTask mit UI-Statusanzeige.

### Security

- **NFR-S1:** Jeder Zugriff auf UI oder API-Endpoints erfordert eine aktive authentifizierte Session ueber Google Workspace OAuth mit Hosted-Domain-Claim `@dbshome.de`.
- **NFR-S2:** Zugangscodes (`entry_code_main_door`, `entry_code_garage`, Cluster-4-Codes) werden symmetrisch verschluesselt at-rest gespeichert (Schluesselableitung HKDF aus `SECRET_KEY`); Klartext nie in Logs, nie im Audit-Log-Payload.
- **NFR-S3:** Alle Datenuebertragungen zwischen Client und Server laufen ueber TLS (Elestio Reverse-Proxy).
- **NFR-S4:** Schreibende Operationen (Field-Edit, Foto-Upload, Review-Queue-Approve/Reject, Registry-Edit) schreiben in einer Transaktion mit dem zugehoerigen Audit-Log-Eintrag — die beiden Writes sind atomar.
- **NFR-S5:** Menschen-Notizen (FR8) sind ausschliesslich fuer Rollen mit `admin`-Permission sichtbar; serverseitig erzwungen (nicht nur UI-gehiddet).
- **NFR-S6:** Das System enforced strukturell, dass KI-Agenten nicht direkt in Steckbrief-Felder schreiben (FR25). Ein direkter Write-Versuch ohne vorhergehenden Review-Queue-Eintrag wird abgelehnt und im Audit-Log als `policy_violation` markiert.
- **NFR-S7:** HTTP-Response-Header `X-Robots-Tag: noindex, nofollow` wird fuer alle Routen gesetzt; keine Indexierung durch Suchmaschinen moeglich, auch bei Fehlkonfiguration.

### Zuverlaessigkeit & Verfuegbarkeit

- **NFR-R1:** Die App (unabhaengig von externen APIs) hat ein Verfuegbarkeits-Ziel von 99 % ueber 30 Tage. Interner Nutzerkreis, kein 24/7-SLA noetig.
- **NFR-R2:** Bei Unerreichbarkeit eines externen Systems (Impower, Facilioo, SharePoint, Anthropic) bleibt die App bedienbar — UI zeigt gecachten Snapshot + Stale-Hinweis, keine 500er-Seiten.
- **NFR-R3:** Der Impower-Nightly-Mirror-Job toleriert einzelne Endpoint-Fehler; ein teilweise fehlgeschlagener Sync wird beim naechsten Lauf fortgesetzt, Status im Admin-Dashboard einsehbar.
- **NFR-R4:** Der Facilioo-1-Min-Mirror-Job hat ein Error-Budget von bis zu 10 % fehlgeschlagenen Polls pro 24h ohne Alert; ueberschritten → Eintrag im Admin-Dashboard.
- **NFR-R5:** BackgroundTasks nutzen je eine eigene DB-Session mit `try/finally`-Close (Plattform-Pattern). Ein Task-Crash blockiert keine User-Session.

### Integrations-Zuverlaessigkeit

- **NFR-I1:** Der Impower-Client nutzt 120 s Timeout + 5xx-Retry mit Exponential-Backoff (2/5/15/30/60 s, max 5 Versuche) — Pattern aus dem existierenden Client wiederverwendet. Rate-Limit-Gate (0.12 s Mindestabstand) greift auch fuer den Mirror-Job.
- **NFR-I2:** Der Facilioo-Client hat ein aequivalent gehaertetes Verhalten: Timeout min. 30 s, 5xx-Retry mit Backoff, Rate-Limit-Gate abhaengig vom Server-Limit (noch zu klaeren, Default 1 req/s).
- **NFR-I3:** Der SharePoint-Graph-Client nutzt OAuth-Client-Credentials (Service-Account), automatisches Token-Refresh, 429-Retry mit `Retry-After`-Header-Respektierung.
- **NFR-I4:** Bei Anthropic-Client-Fehlern in KI-Vorschlag-Flows (v1.1) wird der Vorschlag nicht erzeugt, ein Audit-Log-Eintrag `ai_suggestion_failed` geschrieben; kein User-Impact, weil KI-Workflows asynchron laufen.
- **NFR-I5:** HTML-Response-Bodies von externen Systemen (z. B. Gateway-Timeout-Pages) werden sanitisiert, bevor sie im User-facing-Errortext erscheinen.

### Observability

- **NFR-O1:** Jede schreibende Aktion im Steckbrief-Modul (Create, Edit, Delete, Approve, Reject, Mirror-Writes) erzeugt einen `AuditLog`-Eintrag mit `user_id`, `user_email`, `action`, `entity_type`, `entity_id`, `ip_address`, `details_json`, `created_at`.
- **NFR-O2:** Die bekannte Action-Liste wird um Steckbrief-Actions erweitert (siehe FR33). `docs/architecture.md` §8 ist nach Umsetzung aktualisiert.
- **NFR-O3:** Long-running BackgroundTasks (Impower-Mirror, Facilioo-Mirror, Foto-Upload) loggen Start, Ende und Fehler mit Timestamp in `stdout` (Container-Log) und schreiben einen Audit-Entry, wenn ein Lauf fehlschlaegt.
- **NFR-O4:** Der Pflegegrad-Score ist jederzeit reproduzierbar aus dem DB-Stand heraus — die Formel ist deterministisch und ohne Zufalls- oder Zeit-Abhaengigkeiten (ausser `now()` fuer den Aktualitaets-Decay).
- **NFR-O5:** Fuer Support-Debug: aus dem Admin-Log muss sich zu jedem Feld-Wert zurueckverfolgen lassen, **wann** er von **wem** (User oder Sync-Job) auf welchen Wert gesetzt wurde — das leistet die `field_provenance`-Tabelle.

### Skalierung

- **NFR-SC1:** Ziel-Dimensionierung v1: 50 Objekte, 7 gleichzeitige User, ~10k Audit-Log-Eintraege pro Monat. Keine horizontale Skalierung, keine Autoscaling-Strategie im Scope.
- **NFR-SC2:** Headroom: bei 150 Objekten und 15 Usern muessen Performance-NFRs (NFR-P1..P4) ohne Architektur-Umbau einzuhalten bleiben. Erreichbar durch konservative Indexierung der FK-Spalten und Query-Disziplin.
- **NFR-SC3:** Kein Caching-Layer (kein Redis, kein Memcached) — Postgres + Live-Pull reichen fuer das Volumen. Bei Bedarf spaeter nachziehen, v1 schliesst das strukturell nicht aus (keine Entscheidungen, die Caches unmoeglich machen).
