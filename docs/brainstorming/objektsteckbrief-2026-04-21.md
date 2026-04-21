---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Objektsteckbrief — zentrale Objektsicht der DBS-Plattform, die Impower + Facilioo ergaenzt und Ground-Truth fuer KI-Agenten bildet'
session_goals: 'Breite Ideen-Landkarte (welche Daten, Felder, Entitaeten, Bilder, Dokumente), Rahmen fuer Pflegegrad-Tracking, Klaerung Sync-Richtung mit Impower/Facilioo.'
selected_approach: 'progressive-flow'
techniques_used: ['Role Playing', 'Mind Mapping', 'Morphological Analysis', 'Decision Tree Mapping']
ideas_generated: 92
session_active: false
workflow_completed: true
---

# Brainstorming Session Results — Objektsteckbrief

**Facilitator / Owner:** Daniel Kroll
**Datum:** 2026-04-21
**Dauer:** ~60 min

---

## Session Overview

**Topic:** *Objektsteckbrief* — eine zentrale Objektsicht in der DBS-Plattform, die Impower + Facilioo ueberlagert und ergaenzt. Eine einzige Stelle, an der alle Daten zu einer Immobilie zusammenlaufen. Mit Pflegegrad-Tracking und (perspektivisch) bidirektionalem Sync zu Impower. Zusaetzlich als Wissensquelle/Ground-Truth fuer KI-Agenten.

**Goals:**
- Breite Ideen-Landkarte: welche Entitaeten, Attribute, Medien, Dokumente, Beziehungen sollen erfasst werden?
- Rahmen fuer Pflegegrad-Tracking (Completeness-Score pro Objekt).
- Grobe Klaerung: Was gehoert ins interne System, was wird von Impower/Facilioo gespiegelt, welche Sync-Richtung?
- Kein operatives Cockpit — Aktionen laufen weiter ueber Facilioo.

### Grundsatz-Entscheidungen aus der Session

- **Steckbrief = Single Source of Truth**, aber **v1 = read-only Sync** aus Impower/Facilioo. Write-Back schrittweise ab v1.1 je Feld, nachdem sich die Pflege-Praxis eingespielt hat.
- **KI schreibt niemals direkt** in den Steckbrief — jeder KI-Vorschlag landet in einer Review-Queue und wird vom Menschen approved.
- **SharePoint bleibt DMS** — der Steckbrief haelt Links + Metadaten, keine Blobs.
- **Dateinamen von Scans sind keine Info-Quelle** (durchgaengiges Design-Prinzip der Plattform).

---

## Technique Selection

**Approach:** Progressive Technique Flow — systematisch von breiter Ideation zu priorisiertem Scope.

**Progressive Techniques:**

- **Phase 1 — Expansive Exploration:** Role Playing (multi-stakeholder perspective, 10 Rollen + 1 Shadow-Wildcard)
- **Phase 2 — Pattern Recognition:** Mind Mapping (Cluster-Bildung)
- **Phase 3 — Idea Development:** Morphological Analysis → durch Default-Regel ersetzt (Tempo)
- **Phase 4 — Action Planning:** MoSCoW-Cluster-Cut + Architektur-Entscheidungen

**Journey Rationale:** Bei "was alles erfassen?"-Feature ist der groesste Fehler, frueh auf das Naheliegende zu spitzen. Role Playing erzwang Stakeholder-Wechsel und damit Domain-Shifts alle 2–3 Minuten (Anti-Bias). Morphological Analysis wurde — auf Wunsch des Owners — durch eine **Default-Regel fuer System-of-Record** ersetzt, damit die Session nicht in Feld-Level-Detailarbeit versandet. Das detaillierte Feld-Katalog-Dokument entsteht als Architektur-Artefakt nach der Session.

---

## Phase 1 · Role Playing — Pool der Rohideen

Gespielte Rollen und die daraus abgeleiteten Attributbereiche (Annahme-Status nach User-Review):

### 🧑‍🔧 Rolle 1 — Notfall-Handwerker, Samstag 2 Uhr nachts

- ✅ **Absperrpunkte** (Wasser/Gas/Strom) mit Foto + Standortbeschreibung
- ✅ **Bereitschaftsliste + Handwerker pro Gewerk** (Handy, Stundensatz), erweitert: *welche Handwerker kennen dieses Objekt bereits / Gewerke-Historie*
- ✅ **Gebaeude-Zugangscodes** (Haustuer / TG / Aufzug-Notrufvertrag)
- ✅ **Heizungs-Steckbrief** (Typ, Hersteller, Baujahr, Wartungsfirma, Stoerungsnummer)
- 🟡 **Stromkreis-/Sicherungsplan** (optional)
- ❌ Schluessel-Logistik-Details · individuelle Einheits-Zugangshinweise · automatischer Nachbar-Alarm

### 👩‍💼 Rolle 2 — Buchhalterin am Monatsende

- ✅ **Bankkonten mit aktuellem Saldo** (Impower, live-pull)
- ✅ **Instandhaltungsruecklage** mit historischem Verlauf
- ✅ **Wirtschaftsplan- / Jahresabrechnungs-Status**
- ✅ **SEPA-Mandat-Uebersicht pro Person** (Status, letzte Einzuege, Rueckbuchungen)
- ✅ **Sonderumlagen** (historisch + geplant, Zahlungsstatus je Eigentuemer)
- ❌ Hausgeld-Sollstellungen-Uebersicht (in Impower) · Verteilungsschluessel-Klartext · laufende Zahlungsverpflichtungen (Dienstleister-Rechnungen) — wird aus verknuepften Entitaeten ersichtlich

### 👶 Rolle 3 — Neue Mitarbeiterin, Tag 1

- ✅ **Objekt-Historie strukturiert** (nicht Freitext): Baujahr, letzte Gesamtsanierung, Dach: Jahr, Heizung: Jahr, Leitungen (Wasser/Elektro/Gas): Jahr, Fenster: Jahr, Fassade: Jahr, Daemmung: Jahr
- ✅ **Menschen-Notizen zu Eigentuemern/Beiraeten** (Kuemmerer, kritisch bei Beschluessen, Lieblingsthemen)
- ✅ **Nebenabsprachen / Uraltvereinbarungen** (Kellerraum-Zuordnung, informelle Sondernutzung)
- ✅ **ET-Protokolle der letzten 3 Versammlungen** via SharePoint-Link (Zukunftsmusik: KI schlaegt passendes Dokument vor)
- ✅ **Unser Verwaltervertrag** als eigene Entitaet: Paket-Typ (Full-Service/Miet/WEG), Preis/Einheit, Sonderleistungen (was, Umfang), Stundensatz Extra, Kuendigungsfristen, Laufzeit, naechste Preisanpassung
- ❌ Kommunikations-Gewohnheiten pro Eigentuemer · Anti-Wissen ("was wuerdest du NIE tun")

### 🗣️ Rolle 4 — WEG-Beirat vor ETV

- ✅ **Beschluss-Historie** (SoR: **Facilioo**)
- ✅ **Offene Pendenzen aus Versammlungen**
- ✅ **Bevorstehende Entscheidungen + Wuensche Eigentuemer fuer naechste ETV** (Facilioo)
- ✅ **Eigentuemerliste mit Stimmrechten** (Impower)
- ✅ **Teilungserklaerung + Gemeinschaftsordnung** strukturiert pflegbar: Stimmverteilung (Kopf/MEA/Objekt), Sondernutzungsrechte — KI-Agent scannt TE und schlaegt Feldwerte vor (Backlog, analog SEPA-Agent)
- ✅ **Rechtsstreitigkeiten** (Aktenzeichen, Gegner, Streitwert, Anwalt, naechster Termin)
- ✅ **Wirtschaftliche Kennzahlen** (Ruecklage pro MEA, Hausgeld-Quote, Instandhaltungsstau-Schaetzung, Versicherungsschaeden 5 Jahre)
- ❌ Lieferanten-Transparenz als Beirat-Feature (wird durch Dienstleister-Registry abgedeckt)

### 🧯 Rolle 5 — Versicherungsmakler bei Schadensmeldung

- ✅ **Policen-Portfolio** (Versicherer, Policen-Nr., Typ, Summe, Deckung, SB, Beitrag, Hauptfaelligkeit)
- ✅ **Laufzeit + Kuendigungsfenster** (→ Due-Radar 90 Tage)
- ✅ **Risiko-Merkmale** (Bauartklasse, Heizungsart, Dachdeckung, ZUERS-Zone, Denkmalschutz, PV, Ladepunkte)
- ✅ **Schadens-Historie** (Datum, Art, Einheit, gemeldete/regulierte Summe, Status)
- ✅ **Wartungsnachweise als Deckungs-Bedingung** (Heizung, E-Check, Blitz, Rueckstau, Schornsteinfeger, Trinkwasser, Aufzug-TUeV, Spielplatz — jeweils letzte Pruefung, Faelligkeit, PDF, Policen-Verweis)
- ✅ **Spezialrisiken + Ausschluesse** (KI extrahiert aus Policen-PDF)
- ✅ **Versicherungsnehmer** (WEG vs. Einzeleigentuemer, wichtig fuer Mietverwaltung)

### 🤖 Rolle 6 — KI-Agent (Data-Perspektive)

- ✅ **Maschinenlesbare ID-Kette**: Impower-Property-ID, Facilioo-ID, WEG-Nr., interne Kurzform (HAM61), Flurstueck/Grundbuch
- ✅ **Feld-Provenance** pro Feld: Wert + Quelle (manuell / Impower-Spiegel / PDF-Extraktion / KI-Vorschlag) + Zeitstempel + Confidence
- ✅ **Pflegegrad-Score live** (Completeness-Rate, aeltestes "Letzte Aktualisierung"-Datum, unterpflegte Bereiche)
- ✅ **Context-Pack fuer LLM** — `/objects/{id}/context`-Endpoint liefert kompaktes Briefing fuer Agenten
- ✅ **Write-Back-Protokoll / Review-Queue**: KI-Vorschlaege landen zur Freigabe, nicht direkt im Datenmodell
- ✅ **Event-Stream** (Ablaufmeldungen, neue Entitaeten, Ruecklagen-Unterschreitung) — Basis fuer spaeteren Notification-Hub
- ❌ Semantische Suche ueber Freitexte (v1) · Agent-Kill-Switches pro Objekt (nicht noetig, solange KI ohnehin nur ueber Review-Queue schreibt)

### 🏠 Rolle 7 — Mieter mit Reklamation

- ✅ **Mieter-Stammblatt** (Kontakt, bevorzugte Sprache, Einzug, Vertragslaufzeit, Kaution, Wohnparteien)
- ✅ **Mietvertrags-Felder + Mietvertrag-PDF** verlinkt
- ✅ **Offene Vorgaenge pro Mieter UND pro Eigentuemer** (aus Facilioo gespiegelt)
- ✅ **Mieter-Historie** (Vormieter, Leerstandszeiten, Kuendigungsgruende)
- ✅ **Einheits-Steckbrief** (Flaeche + Messungsmethodik, Zimmer, Etage, Balkon, Keller, Stellplatz, Grundriss-PDF, Ausstattungsmerkmale)
- ✅ **Zaehler pro Einheit** (Strom/Gas/Wasser/Heizung — aus Facilioo)
- ✅ **Sonderrechte / Lasten** (Gartenanteil, Umbau-Genehmigung, E-Ladung, Internet-Kopplung)
- ✅ **Reklamations-Einstiegspunkt** als UI-Sicht (Nachbar-Relation, vorherige Wasserschaeden, Steigleitungen)

### 🔍 Rolle 8 — Due-Diligence-Pruefer

- ✅ **Grundbuch-Paket** (Blatt-Nr., Amtsgericht, Flur/Flurstueck, Abt. II/III-Lasten, letzter Auszug)
- ✅ **Baurechtliche Unterlagen** (Baugenehmigung, Abnahme, Nutzungsaenderung, Denkmalschutz, Erhaltungssatzung, Milieuschutz, Baulasten)
- ✅ **Energieausweis** (Typ, Endenergie, Klasse, Ausstellungsdatum, Gueltig-bis)
- ✅ **Altlasten / Umweltrisiken** (Altlastenkataster, Kampfmittel, Radon, Starkregen/Hochwasser-Zone)
- ✅ **Maengel + Instandhaltungsrueckstau** (Liste mit Behebungssumme, Dringlichkeit, Foto, Ursprung)
- ✅ **Externe Gutachten** (Wert, Dach, Statik, Schadstoff, Thermografie)
- ✅ **Steuer + Foerder-Status** (Grundsteuer, KfW, BAFA, §7h/7i-AfA, Denkmal-AfA)
- ✅ **Stichtags-Snapshot** fuer Uebergaben

### 🌱 Rolle 9 — ESG-/Energieberater

- ✅ **Heizung Ausserbetriebnahme-Plan** (GEG §72, Bestandsschutz, Ersatzpfad, Foerderkulisse)
- ✅ **CO2-Kostenverteilung** (Stufenmodell, Vermieter-Anteil pro Gebaeude-Effizienz)
- ✅ **Sanierungs-Fahrplan (iSFP)** wenn vorhanden
- ✅ **Hydraulischer Abgleich** (Datum, Bericht, Fristen)
- ✅ **Ladeinfra E-Mobilitaet** (Defaultzuteilung durch Facilitator; Zustimmung implizit)
- ✅ **PV / Balkonkraftwerke** (Anlagen-Inventar, MaStR, EEG-Ende, Mieterstrom)
- ✅ **Wasser / Kreislauf** (Regenwasser, Versiegelung, Haerte, Legionellen)
- ✅ **Barriere- / Zukunftsfreiheit** (barrierefrei erschlossene WEs, Aufzug-Reichweite, Fahrrad/Lastenrad, DIN 18040)

### 📣 Rolle 10 — Vermarktung / Mietersuche

- ✅ **Bild-Sets** pro Einheit + Objekt (mit Aufnahmedatum)
- ✅ **Lagebeschreibung + POI** (ideal AI-gezogen)
- ✅ **Vermietungs-Policy der Eigentuemer**
- ❌ Expose-Ready-Ampel · Zielgruppen-Hinweise

### 👹 Shadow-Wildcard

- ✅ **Stille Risiken** (vertrauliche Notizen, rollen-gesichert — "Dach 2023 nur kosmetisch", "Drittmieter WE 2 toleriert")
- ✅ **Verbrannte-Erde-Liste Dienstleister** (NIE WIEDER arbeiten mit …)
- ❌ Problem-Personen-Flag · Krisenplan · GWG-/PEP-Flags

### Querschnitts-Ideen (kein Cluster, aber strukturell relevant)

- ✅ **Custom-Module-Baukasten** — UI-Menue fuer neue Pflegebloecke ohne Programmierung (v2)
- ✅ **Registries / Portfolio-Ansichten** — jede wichtige Entitaet (Versicherer, Dienstleister, Bank, Handwerker, Eigentuemer, Mieter, Ablesefirma) bekommt Detailseite + Aggregationen. Besonderer Wert: **Due-Radar global** und **Gesamtpraemie pro Versicherer**.

---

## Phase 2 · Cluster (Mind Mapping)

12 Cluster — 10 inhaltliche + 2 Querschnitts-Cluster.

| # | Cluster | Hauptfelder | ~Ideen |
|---|---|---|---:|
| 1 | Stammdaten & Einheiten-Struktur | ID-Kette, MEA, Eigentuemerliste mit Stimmrechten, WE-Uebersicht | 4 |
| 2 | Einheits-Steckbrief | pro WE: Flaeche, Zimmer, Etage, Balkon, Keller, Stellplatz, Grundriss, Ausstattung, Zaehler | 7 |
| 3 | Personen & laufende Vorgaenge | Mieter-Stammblatt, Mietvertrag, Menschen-Notizen, offene Vorgaenge pro Person | 9 |
| 4 | Technik & Gebaeudesubstanz | Absperrpunkte, Heizung, Zugangscodes, Objekt-Historie strukturiert | 9 |
| 5 | Medien / DMS | Bilder Objekt/WE/Technik, SharePoint-Links, POI | 5 |
| 6 | Finanzen | Bankkonten (Saldo live), Ruecklage, Wirtschaftsplan, SEPA, Sonderumlagen, Kennzahlen | 10 |
| 7 | Verwaltervertrag & Dienstleister | unser Vertrag, Dienstleister-Registry, Handwerker + Historie, Ablesefirmen | 6 |
| 8 | Versicherungen & Wartungspflichten | Portfolio, Laufzeit, Risikomerkmale, Schadenshistorie, Wartungsnachweise, Ausschluesse | 8 |
| 9 | Recht & Governance | Beschluss-Historie, Pendenzen, bevorstehende Entscheidungen (**Facilioo**), TE strukturiert, Rechtsstreit | 7 |
| 10 | Baurecht / DD / ESG | Grundbuch, Baurecht, Energieausweis, Altlasten, Maengel, Gutachten, Steuer, GEG/CO2/iSFP/Ladeinfra/PV/Wasser/Barriere | 13 |
| 11 | ⚠ Vertrauliches (rollengesichert) | Stille Risiken, Verbrannte-Erde-Liste | 2 |
| 12 | ⚙ Meta-Features | Pflegegrad, Custom-Module-Baukasten, Feld-Provenance, Review-Queue, Event-Stream, Context-Pack, Due-Radar, Snapshot, Sync-Richtung, Rollen-Zugriff | 12 |

**Gesamt: ~92 Rohideen.**

---

## Phase 3 · Default-Regel fuer System-of-Record & Sync

Statt Feld-fuer-Feld-Matrix (zu zeitintensiv) wurde eine **Default-Regel** gesetzt. Der Feld-Katalog entsteht als Architektur-Artefakt nach der Session.

### Default-Regel

| Quelle | Rolle | Defaults |
|---|---|---|
| **Impower** | SoR Stammdaten/Finanzen/Vertraege | Stammdaten, Eigentuemer, SEPA, Hausgeld, Wirtschaftsplan, Kontoinventar |
| **Facilioo** | SoR operative Vorgaenge + Beschluesse | Tickets, Reklamationen, Dienstleister-CRM, Zaehlerablesungen, **Beschluss-Historie**, Pendenzen, Wuensche ETV |
| **SharePoint** | DMS | alle PDFs; Steckbrief haelt Links + Metadaten |
| **Steckbrief (intern)** | SoR fuer den Rest | Technik + Fotos, Objekt-Historie, Versicherungen & Wartungsnachweise, Baurecht, ESG, Verwaltervertrag, Menschen-Notizen, Vertrauliches |

**v1-Schreibrichtung:** Read-only Sync aus Impower/Facilioo. Write-Back schrittweise ab v1.1 je Feld.

### Markierte Ausnahmen

1. **Konto-Saldo** — Impower SoR, aber Live-Pull statt Mirror.
2. **Teilungserklaerung-Strukturfelder** — PDF in SharePoint, *extrahierte Felder* (Stimmrechts-Schluessel, Sondernutzungsrechte) sind Steckbrief-Truth, per KI-Vorschlag befuellt.
3. **Dienstleister** — Grunddaten aus Facilioo, *steckbrief-eigene Meta-Felder* (kennt dieses Objekt, Gewerke-Historie, verbrannte-Erde-Flag) sind Steckbrief-Truth.
4. **Offene Vorgaenge pro Eigentuemer/Mieter** — Facilioo SoR, Steckbrief aggregiert + zeigt.
5. **Zaehler** — wenn Facilioo unvollstaendig, faellt Rest in Steckbrief zurueck.

---

## Phase 4 · MoSCoW + Architektur-Entscheidungen (v1-Scope)

### MoSCoW auf Cluster-Ebene

| Cluster | v1 | Kommentar |
|---|---|---|
| 1 Stammdaten | **MUST** | Read-only Spiegel Impower. Foundation. |
| 2 Einheits-Steckbrief | **MUST** | Impower-Spiegel + intern Fotos/Grundriss |
| 3 Personen & Vorgaenge | **MUST** | Impower (Personen) + Facilioo (Tickets) aggregiert |
| 4 Technik & Gebaeudesubstanz | **MUST** | Hauptdiff-Nutzen, intern, Foto-zentriert |
| 5 Medien / DMS | **SHOULD** | Upload + SharePoint-Link. Wachsen lassen. |
| 6 Finanzen | **MUST** | Impower-Spiegel; Saldo live |
| 7 Verwaltervertrag + Dienstleister | **MUST** (upgegradet) | Dienstleister normalisiert → Voraussetzung fuer Registries |
| 8 Versicherungen & Wartungspflichten | **MUST** | Grosser Schmerzpunkt, hoher Pflegegrad-Impact |
| 9 Recht & Governance | **SHOULD** | Facilioo-Spiegel; TE-Scan-Agent spaeter |
| 10 Baurecht / DD / ESG | **SPLIT** | v1-MUST: Grundbuch + Energieausweis + Maengel-Stau. Rest (ESG, Gutachten, Foerder) COULD. |
| 11 ⚠ Vertrauliches | **WON'T v1** | Braucht Feld-Level-ACL, blockiert durch Permissions-Modell |
| 12 ⚙ Meta-Features | **SPLIT** | v1-MUST: Pflegegrad-Score, Feld-Provenance, Review-Queue, **Normalisierte Entitaeten + Registries (Versicherer, Dienstleister, Due-Radar global)**. v1-COULD: Event-Stream-Fundament. v2: Custom-Module-Baukasten, Context-Pack, Snapshot. |

### Architektur-Entscheidungen (v1-Default)

| # | Entscheidung | v1-Default | Konsequenz |
|---|---|---|---|
| **A** | Sync-Strategie | Read-only Impower + Facilioo; Write-Back pro Feld schrittweise ab v1.1 | 1 Schreibrichtung → stabil, keine Konfliktbehandlung |
| **B** | Foto-/Medien-Pipeline | SharePoint via Graph-API (Service-Account), Metadaten im Steckbrief | Konsistent mit DMS; kein lokaler Blob-Store |
| **C** | Custom-Module-Baukasten | **v2** (in v1 Cluster 1–10 hartkodiert), Datenmodell so bauen, dass JSONB-Extension spaeter einfach nachruestbar | v1 deutlich einfacher |
| **D** | Permissions-Modell | Objekt-Level-ACL wie heute; Cluster 11 ausgeklammert | Kein Feld-Level-ACL in v1 noetig |
| **E** | Registries / Portfolio-Perspektive | **Normalisierte Entitaeten ab v1** (Versicherer, Dienstleister, Bank, Handwerker, Eigentuemer, Mieter, Ablesefirma als eigene Tabellen mit IDs). v1-Detailseiten: Versicherer + Dienstleister + Due-Radar global. Rest v1.1. | Voraussetzung fuer Cross-Views; macht FK-Disziplin im Feld-Katalog zur Pflicht |

### v1-Scope (zusammengefasst)

**Steckbrief v1 liefert:**

- Objekt-Detailseite mit Clustern 1, 2, 3, 4, 6, 8 komplett + 5/7/9 leicht + Teile von 10 (Grundbuch, Energieausweis, Maengel)
- **Registries** fuer Versicherer + Dienstleister/Handwerker mit Detail- und Listenansichten
- **Due-Radar global** ueber alle Objekte (Versicherungen, Wartungen, Vertraege mit Ablauf < 90 Tage)
- **Pflegegrad-Score** pro Objekt
- **Feld-Provenance** pro Feld (Mensch/Sync/KI-Vorschlag + Zeitstempel)
- **Review-Queue** fuer KI-Vorschlaege (KI schreibt nie direkt)
- Read-only Impower/Facilioo-Sync (Mirror + Live-Pull fuer Saldo)
- SharePoint-Link-Integration fuer Dokumente

**v1.1+ nachziehen:**

- Write-Back pro Feld schrittweise nach Praxis-Bedarf
- Registries fuer Bank · Eigentuemer · Mieter · Ablesefirma
- ESG-Cluster (GEG, iSFP, CO2, Ladeinfra, PV)
- Gutachten, Foerderungen, Altlasten
- Event-Stream-Fundament

**v2:**

- Custom-Module-Baukasten (UI fuer eigene Pflegebloecke)
- Feld-Level-ACL → Cluster 11 Vertrauliches aktivieren
- TE-Scan-Agent als eigener KI-Workflow (analog SEPA, Mietverwaltung)
- Context-Pack-Endpoint fuer LLM
- Stichtags-Snapshot-Funktion
- Semantische Suche ueber Freitexte

---

## Action Plan — Naechste Schritte

1. **Feld-Katalog erstellen** — neues Dokument `docs/objektsteckbrief-feld-katalog.md`: alle ~92 Attribute mit Typ / Pflicht / SoR nach Default-Regel / zugeordnete Rolle + Registry-Flag (normalisierte Entitaet ja/nein). Grundlage fuer Migration + Formular-Rendering + Registry-Routen.
2. **Architektur-Dokument** — `docs/architecture-objektsteckbrief.md`: Datenmodell-Skizze (Objekt-Kern, normalisierte Seiten-Entitaeten, Feld-Provenance-Tabelle, Review-Queue), Sync-Strategie (Mirror vs. Live-Pull pro Feld), SharePoint-Integration via Graph-API, Registry-Query-Muster.
3. **Impower + Facilioo Read-Spiegel-Spec** — welche Endpunkte liefern welche Felder, in welchem Intervall wird gemirrort, was ist live-pull. Pro-Cluster tabellarisch.
4. **Story-Schnitt fuer BMAD** — Epic "Objektsteckbrief v1" mit Stories pro Cluster-Bereich. Reihenfolge (Vorschlag):
   1. Story 1: Datenmodell-Fundament + Feld-Provenance + Pflegegrad-Score
   2. Story 2: Impower-Read-Spiegel (Cluster 1 + 6)
   3. Story 3: Facilioo-Read-Spiegel (Cluster 3 + 9 Teile)
   4. Story 4: Technik + Foto-Pipeline (Cluster 4 + 5) inkl. SharePoint-Graph-API
   5. Story 5: Versicherungen + Wartungsnachweise + Due-Radar (Cluster 8 + Teil von 12)
   6. Story 6: Verwaltervertrag + Dienstleister-Registry (Cluster 7)
   7. Story 7: Einheits-Steckbrief + Mieter (Cluster 2 + Teil 3)
   8. Story 8: Baurecht-Grundlagen (Cluster 10-Teil)
5. **Entscheidung deferred (naechste Session):** genaue Auswahl der Registry-Detailseiten fuer v1.1 (Bank/Eigentuemer/Mieter/Ablesefirma-Prio).

---

## Session Summary

**Key Achievements:**

- 92 Rohideen ueber 10 Stakeholder-Rollen + 1 Shadow-Runde generiert.
- 12 Cluster (10 inhaltlich + 2 Querschnitt) identifiziert; Schwerpunkte sichtbar (Baurecht/DD/ESG groesste Cluster, Vertrauliches rechtlich heikel).
- Default-Regel fuer System-of-Record + 5 Ausnahmen geklaert.
- v1-Scope als MoSCoW-Cut festgelegt; v2-Roadmap skizziert.
- 5 Architektur-Entscheidungen dokumentiert (Sync, Medien-Pipeline, Baukasten, Permissions, Registries).
- Kritischer Design-Pivot: **Registries/Portfolio-Perspektive** als strukturelle Eigenschaft des Datenmodells aufgenommen (nicht als UI-Feature), inkl. Due-Radar global als Killer-Use-Case.
- Grundsatz "KI schreibt nie direkt" als plattformweites Prinzip bestaetigt.

**Creative Breakthroughs:**

- **Due-Radar global** ueber alle Objekte hinweg — Killer-Anwendungsfall, in Impower/Facilioo heute nicht moeglich.
- **Wartungsnachweise als Deckungs-Bedingung** als eigene Entitaets-Beziehung (Wartung ↔ Policen-Verweis) statt loser Liste.
- **Feld-Provenance + Review-Queue** als architektonische Basis fuer "KI schlaegt vor, Mensch entscheidet".
- **Normalisierung aller Seiten-Entitaeten in v1** als Preis fuer spaetere Portfolio-Ansichten.

**Was gut lief:**

- Role-Playing hat systematisch Domain-Shifts erzwungen; der Notfall-Handwerker, der ESG-Berater und die Onboarding-Rolle haben Felder geliefert, die rein "feature-getriebenes" Ideen-Sammeln nicht erreicht haette.
- Der Abbruch des Feld-Level-Matrix-Schrittes zugunsten einer Default-Regel war tempomaessig richtig.
- Die nachgelieferte Registries-Frage am Ende war ein wichtiger Korrektiv-Moment und wurde direkt ins Scope eingearbeitet.

**Offene Fragen fuer Folge-Session:**

- Genaue v1.1-Prio fuer Registry-Detailseiten (Bank vs. Eigentuemer vs. Mieter vs. Ablesefirma).
- Technische Abklaerung SharePoint Graph-API (Service-Account-Setup, bestehende Ordnerstruktur).
- Facilioo-Lese-API: verfuegbare Endpunkte fuer Beschluesse, Tickets, Dienstleister-CRM, Zaehler.
- TE-Scan-Agent als eigener Meilenstein nach M5 — Prompt-Draft + Pydantic-Schema.
