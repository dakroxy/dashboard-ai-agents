---
status: Entwurf
date: 2026-05-05
author: Daniel Kroll
quellen:
  - mockups/objektsteckbrief-react/ (Hanseatic Terminal, beide Themes, Komponenten + zwei Pages)
  - docs/brainstorming/objektsteckbrief-2026-04-21.md (10 Stakeholder-Rollen, 92 Roh-Ideen)
  - docs/objektsteckbrief-feld-katalog.md (Feldbasis, Provenance-Modell, Registry-FKs)
  - docs/architecture.md (Modul-Inventar, Permission-Modell)
  - CLAUDE.md (Modul-Status, Plattform-Prinzipien, Backlog 1-7)
geltungsbereich: SPA-Frontend (Variante C) der DBS-KI-Plattform — Foundation fuer alle Module
nicht_im_scope: Brand-Design, User-Research, Marketing-Pages, Pixel-Mockups
---

# UX-Design — SPA-Frontend Dashboard KI-Agenten

> **Foundation, kein Mockup-Inferno.** Diese Spec definiert wiederverwendbare Schablonen
> (Templates, Patterns, States), die alle Module nach dem SPA-Wechsel teilen. Pro Modul
> wird spaeter nur konkretisiert, nicht neu erfunden.

---

## 0. Plattform-Prinzipien (nicht verhandelbar)

Diese fuenf Saetze gelten fuer **jedes** Modul und sind die Pruefkriterien fuer jedes neue
Mockup oder jede neue Komponente.

| # | Prinzip | Konsequenz fuer UX |
|---|---|---|
| **P1** | **Provenance pro Datenfeld.** Jedes angezeigte Datenfeld traegt einen Quellen-Glyph (manual / mirror / ai / derived / missing). | `Field`-Komponente ist Pflicht. „Nackter" Wert ohne Provenance ist Bug, nicht Feature. |
| **P2** | **KI schreibt nie direkt.** Alle KI-Vorschlaege landen in der Review-Queue. Annahme = Feld bekommt Provenance `manual` + Audit-Eintrag. | Review-Queue-Drawer ist globale Komponente, nicht modul-spezifisch. |
| **P3** | **Datendichte > Whitespace.** Vorbild Bloomberg-Terminal / Linear / Airtable. Kein Material-Design-Pastell, kein Generic-SaaS-Look. | Schriftgroessen 10–13 px Dominanz, tabular nums, Hairlines statt fette Borders, Corner-Ticks an Cards. |
| **P4** | **Desktop-First.** Verwalter-Arbeitsplatz mit ≥1440 px Breite. | Layouts auf 1440 entwickeln, dann nach unten degradieren. Mobile = Edge-Case (Notfall-Handwerker). |
| **P5** | **SoR ist eindeutig.** Impower (Stammdaten/Finanzen), Facilioo (Vorgaenge/Beschluesse), SharePoint (DMS), Steckbrief (alles andere). | Felder zeigen ihre Herkunft; Read-only-Felder sind nicht editierbar; Live-Pull-Felder zeigen Zeitstempel. |

---

## 1. Information Architecture

### 1.1 Sitemap

Die Plattform besteht aus **Modulen**, **Registries** (Listen-/Portfolio-Sichten ueber
normalisierte Entitaeten) und **Querschnitts-Sichten**. Module sind die Workflows, Registries
sind die Aggregat-Views, Querschnitts-Sichten sind objekt-uebergreifend.

```
DBS-KI-Plattform
│
├── 🏠 Dashboard (Home)
│   ├── Persoenliche Inbox (Review-Queue, Notifications, offene Cases)
│   ├── Modul-Tiles (nur sichtbar bei Permission)
│   └── KPI-Strip (Pflegegrad-Avg, Faellig-Counter, Annahmequote)
│
├── 📋 Objektregister (Cluster: "Datenbasis")
│   ├── Liste / Karte / Karten-Map  ← View-Switcher
│   └── Objekt-Detail (Steckbrief, 10 Sektionen)
│       ├── Cluster 1 Stammdaten
│       ├── Cluster 2 Einheiten
│       ├── Cluster 3 Personen + Vorgaenge (Facilioo-Tickets)
│       ├── Cluster 4 Technik & Substanz
│       ├── Cluster 5 Medien (SharePoint-Links)
│       ├── Cluster 6 Finanzen (Impower-Mirror + Saldo-Live)
│       ├── Cluster 7 Verwaltervertrag
│       ├── Cluster 8 Versicherungen + Wartungspflichten
│       ├── Cluster 9 Recht & Governance (Facilioo-Beschluesse)
│       └── Cluster 10 Baurecht / DD
│
├── 🔁 Workflows (Cluster: "KI-Aktionen")
│   ├── SEPA-Mandat (Single-Doc)
│   ├── Mietverwaltungs-Anlage (Multi-Doc → Case)
│   ├── Contact-Create (Sub-Workflow)
│   └── (kuenftig: TE-Scan, Energieausweis-Scan, Police-Scan, …)
│
├── 🗂️ Registries (Cluster: "Portfolio-Sichten")
│   ├── Versicherer-Registry      ← v1
│   ├── Dienstleister-Registry    ← v1
│   ├── Eigentuemer-Registry      ← v1.1
│   ├── Mieter-Registry           ← v1.1
│   ├── Bank-Registry             ← v1.1
│   └── Ablesefirma-Registry      ← v1.1
│
├── 🚨 Querschnitts-Sichten
│   ├── Due-Radar global (Wartungen / Policen / Vertraege / Beschluesse)
│   ├── Maengel-/Instandhaltungsstau global         ← v1.1
│   └── Pflegegrad-Heatmap Portfolio                ← v1.1
│
└── ⚙ Admin
    ├── Users + Rollen
    ├── Workflows (Prompts, Modelle, Lernnotizen)
    ├── Audit-Log
    ├── Sync-Status (Impower-Mirror, Facilioo-Mirror)
    └── Permissions / Resource-Access
```

**Hierarchie-Regel:** maximal **3 Klick-Tiefen** vom Dashboard bis zum Detail-Feld.
Tiefer wird ueber Tabs / Drawer aufgeloest, nicht ueber neue Pages.

### 1.2 Navigation — global vs. modul

Es gibt genau **zwei** Navigations-Ebenen. Jede UI-Komponente weiss, in welche sie gehoert.

| Ebene | Komponente | Inhalt | Verhalten |
|---|---|---|---|
| **Global** | `AppShell.TopBar` (37 px hoch) | Brand · Modul-Tabs · Cmd+K · Theme-Switch · User-Chip | Sticky. Immer sichtbar. Kein Re-Mount beim Modul-Wechsel. |
| **Modul** | `PageHeader` (variabel, 80–180 px) | Eyebrow · Titel · KPI-Tiles · Filter / Tabs · Such-Input · Aktions-Buttons | Sticky unter TopBar. Pro Page eigener Inhalt. |

**Modul-Tabs in der TopBar** (Reihenfolge nach Nutzungsfrequenz):

```
[ Dashboard ]  [ Objektregister ]  [ Workflows ▾ ]  [ Registries ▾ ]  [ Due-Radar ]  [ Admin ▾ ]
```

`▾` = Dropdown mit Untermodulen. Der Modul-Tab wird nur eingeblendet, wenn der User
mindestens **eine** Permission im Sub-Modul hat.

**Sidebar gibt es nur innerhalb einer Page** als **Sprungmarken-Nav** (siehe
Steckbrief-Detail). Sie ist **nicht** die globale Navigation.

### 1.3 Querschnittsfunktionen — wo leben sie?

Diese vier Funktionen sind cross-modul und brauchen einen festen Anker.

| Funktion | Anker | Aktivierung | Persistent? |
|---|---|---|---|
| **Cmd+K-Suche** | Such-Pill in der TopBar (`⌘K`) | Tastatur global · Klick auf Pill | Modal-Dialog uebersteuert alles |
| **Notification-Hub** | Glocken-Icon in der TopBar mit Badge | Klick → Drawer rechts | Drawer kann geoeffnet bleiben (380 px) |
| **Review-Queue** | Sparkle-Icon in der TopBar mit Badge | Klick → Drawer rechts (gleicher Slot wie Notifications) | Drawer kann geoeffnet bleiben |
| **User-Chat (Backlog 4)** | Bottom-Right-Drawer (Floating-Action) | Klick → kleiner Chat-Drawer (440 px breit) | Persistent ueber Pages, blendet sich nicht aus |

**Drawer-Slot-Regel:** Es gibt **zwei** Drawer-Slots: rechts oben (Notifications/Review/
modul-spezifischer Drawer wie KI-Vorschlaege im Steckbrief) und rechts unten (User-Chat).
Beide koennen gleichzeitig offen sein. Mehr nicht.

---

## 2. Personae & Critical Flows

Aus dem Brainstorming uebernommene 10 Rollen, jeweils mit Job-to-be-done, kritischem Flow
und Modul-Touchpoints. Reihenfolge nach **Frequenz x Frust**: oben die Personae, deren
Schmerzen heute am groessten sind.

### P1 · Buchhalterin am Monatsende

| | |
|---|---|
| **JTBD** | „Ich muss am 28. wissen, welche WEG-Konten in Schieflage sind und welche Sonderumlagen offen stehen." |
| **Kritischer Flow** | (1) Dashboard → KPI „Konten unter Soll-Ruecklage" → (2) Klick auf Counter → Listen-View aller Objekte mit Pflegegrad + Saldo-Trend → (3) Filter „Saldo-Trend negativ 30d" → (4) Drilldown ins Objekt → Cluster 6 Finanzen → (5) Sonderumlagen-Tabelle → (6) Export PDF fuer Mail an Beirat |
| **Touchpoints** | Dashboard, Objektregister-Liste, Steckbrief Cluster 6, Export-Aktion |
| **UX-Anforderungen** | Tabular nums, schnelle Sortierung, Snapshot-/Stichtag-Funktion, Saldo-Sparkline 12 Monate |

### P2 · WEG-Beirat vor ETV

| | |
|---|---|
| **JTBD** | „Ich brauche in 5 Minuten den Stand der WEG fuer das Briefing — Beschluss-Historie, offene Pendenzen, Hausgeld-Quote, anstehende Versicherungs-Erneuerungen." |
| **Kritischer Flow** | (1) Steckbrief direkt aufrufen (URL aus Mail) → (2) View-Switch „Risiko-Fokus" — alles dimmt ausser Versicherungen, Maengel-Stau, Rechtsstreit → (3) Cluster 9 Recht expand → (4) PDF-Export mit Stichtag-Snapshot |
| **Touchpoints** | Direkter Steckbrief-Deep-Link, Risiko-Fokus-View, PDF-Export, Snapshot |
| **UX-Anforderungen** | Risiko-Fokus muss in 1 Klick erreichbar sein. Snapshot mit Datum unten im Footer-Strip. |

### P3 · Notfall-Handwerker, Sa 2 Uhr

| | |
|---|---|
| **JTBD** | „Wo ist der Wasser-Absperrhahn? Wo der Heizungsraum? Welcher Code geht?" |
| **Kritischer Flow** | (1) Mobile (Smartphone) → (2) Cmd+K oder Such-URL `/?q=Eppendorfer 47` → (3) Treffer → (4) Cluster 4 Technik → (5) Foto-Lightbox auf Absperr-Foto → (6) Code-Copy-Button (Click-to-Reveal, audit-pflichtig) |
| **Touchpoints** | Cmd+K, Steckbrief Cluster 4, Foto-Viewer, Click-to-Reveal Codes |
| **UX-Anforderungen** | **Einzige Persona mit Mobile-Pflicht.** Cluster 4 muss auf 360 px lesbar sein. Codes muessen verschluesselt sein und nur per Click-to-Reveal mit Audit. |

### P4 · Versicherungsmakler bei Schaden

| | |
|---|---|
| **JTBD** | „Welche Police greift, was sind die Risikomerkmale, sind die Wartungsnachweise aktuell?" |
| **Kritischer Flow** | (1) Steckbrief → (2) Cluster 8 Versicherungen → (3) Police-Tabelle mit Due-Highlighting → (4) Wartungspflichten daneben (Deckungs-Bedingung) → (5) Schadens-Historie 5 Jahre direkt darunter → (6) PDF-Export der Sektion fuer Mail an Versicherer |
| **Touchpoints** | Steckbrief Cluster 8, Versicherer-Registry (Sprungziel via Insurer-Chip), Schaden-Detail-Drawer |
| **UX-Anforderungen** | Wartungspflichten + Policen visuell verknuepfen (Hover auf Police highlightet relevante Wartungen). |

### P5 · Neue Mitarbeiterin, Tag 1

| | |
|---|---|
| **JTBD** | „Ich uebernehme 30 Objekte — wo finde ich Onboarding-Wissen pro Objekt ohne Vorgaenger?" |
| **Kritischer Flow** | (1) Dashboard → (2) Tile „Mein Portfolio (30)" → (3) Karten-Liste der Objekte mit Pflegegrad-Ring → (4) Pro Objekt: Steckbrief Cluster 1+3 Stammdaten + Menschen-Notizen → (5) Cluster 7 Verwaltervertrag-Konditionen → (6) Cluster 4 Objekt-Historie strukturiert |
| **Touchpoints** | Dashboard, Mein-Portfolio-View, Steckbrief 4 Cluster, Menschen-Notizen-Editor |
| **UX-Anforderungen** | „Mein Portfolio" als persoenlicher Filter im Objektregister. Menschen-Notizen prominent + Provenance `manual` mit Autor-Initialen. |

### P6 · KI-Agent (Data-Perspektive, kein UI)

| | |
|---|---|
| **JTBD** | „Liefere mir ein Objekt-Briefing fuer den naechsten Prompt-Call." |
| **Kritischer Flow** | (rein API) — `GET /objects/{id}/context` liefert kompaktes Briefing. UI-Effekt: jede UI-Aktion, die KI nutzt (Chat, Vorschlag), zeigt im Drawer die **Quellen-Snippets** (Provenance-Trace) an, damit der Mensch nachverfolgen kann, *worauf* die KI ihre Aussage stuetzt. |
| **Touchpoints** | Review-Queue-Drawer (Quellen-Snippet-Anzeige), Case-Chat, Steckbrief-„An KI-Chat ▸"-Button |
| **UX-Anforderungen** | Kein direktes UI, aber jede KI-getriebene UI-Komponente zeigt **Source-Snippet** + Confidence-Bar + 80%-Schwellen-Marker. |

### P7 · Mieter mit Reklamation (durchgereicht via Verwalter)

| | |
|---|---|
| **JTBD** | (Verwalter-Sicht) „Welche Einheit, welcher Vertrag, gab es Vorbeschwerden, sind Steigleitungen-Probleme dokumentiert?" |
| **Kritischer Flow** | (1) Steckbrief → (2) Cluster 2 Einheiten → Klick auf Einheit → (3) Einheits-Drawer mit Mieter-Stammblatt + offene Tickets aus Facilioo + Nachbar-Relation → (4) Klick auf Ticket → Facilioo-Deep-Link |
| **Touchpoints** | Steckbrief Cluster 2 + 3, Einheits-Drawer, Facilioo-Deep-Link |
| **UX-Anforderungen** | Einheits-Drawer muss neben dem Steckbrief geoeffnet werden, ohne den Steckbrief zu verlassen. |

### P8 · Due-Diligence-Pruefer (extern, aber durchgereicht)

| | |
|---|---|
| **JTBD** | „Komplettes DD-Paket eines Objekts — Grundbuch, Energieausweis, Maengel-Stau, Schadens-Historie, Gutachten." |
| **Kritischer Flow** | (1) Steckbrief → (2) PDF-Export „DD-Paket" generiert konsolidiertes PDF aus Cluster 1, 6, 8, 10, 4 → (3) Snapshot mit Datum + Hash signiert |
| **Touchpoints** | Steckbrief, Export-Aktion mit Profil „DD-Paket", Snapshot-Funktion |
| **UX-Anforderungen** | Export-Aktion mit waehlbaren Profilen (Voll / DD / Beirat / Versicherer). Snapshot-Hash unten im Footer. |

### P9 · ESG-/Energieberater

| | |
|---|---|
| **JTBD** | „Heizungs-Status, GEG-Konformitaet, iSFP-Stand, CO2-Verteilung." |
| **Kritischer Flow** | (1) Steckbrief → (2) Cluster 4 Technik (Heizung) + Cluster 10 Baurecht/ESG (Energieausweis, GEG, iSFP, PV) — beide bewusst gemeinsam scrollbar |
| **Touchpoints** | Steckbrief Cluster 4 + 10 |
| **UX-Anforderungen** | Diese Persona ist **v1.1+** — Cluster 10 ist im v1 nur „Grundbuch + Energieausweis + Maengel-Stau". Vollumfang spaeter. |

### P10 · Vermarktung / Mietersuche

| | |
|---|---|
| **JTBD** | „Bilder pro Einheit, Lagebeschreibung, Vermietungs-Policy des Eigentuemers." |
| **Kritischer Flow** | (1) Einheits-Detail (aus Steckbrief Cluster 2) → (2) Bild-Galerie + Grundriss → (3) Vermietungs-Policy aus Cluster 3 Notes-on-Owner |
| **Touchpoints** | Steckbrief Cluster 2 + 3 |
| **UX-Anforderungen** | Bild-Galerie mit Aufnahmedatum, Grundriss als PDF-Viewer inline. **v1.1+**. |

### Personae-Matrix

| Persona | Dashboard | Steckbrief | Workflow | Registry | Due-Radar | Admin |
|---|---|---|---|---|---|---|
| P1 Buchhalterin | ✓ Start | C6 | — | Bank, Eigentuemer | ✓ (Mahnungen) | — |
| P2 Beirat | — | **Hauptsicht** | — | — | — | — |
| P3 Handwerker | — | C4 (mobil) | — | Dienstleister | — | — |
| P4 Versicherer | — | C8 | — | **Versicherer** | ✓ (Policen-Lauf) | — |
| P5 Neue MA | ✓ Start | C1+C3+C7 | — | Eigentuemer | — | — |
| P6 KI-Agent | — | (Source-Trace) | (Chat) | — | — | — |
| P7 Mieter (via Verw.) | — | C2+C3 | — | Mieter | — | — |
| P8 DD-Pruefer | — | **Export DD** | — | — | — | — |
| P9 ESG | — | C4+C10 | — | — | — | — |
| P10 Vermarktung | — | C2+C3 | — | — | — | — |

---

## 3. Design-System-Inventar

Komplette Extraktion aus den vorhandenen Mockups (`mockups/objektsteckbrief-react/`).
Wenn ein Wert hier verbindlich notiert ist, gilt er; wenn ein Modul abweichen will,
braucht es eine begruendete Aenderung in dieser Spec, nicht im Modul.

### 3.1 Design-Tokens

#### Farben — Light-Theme „Hanseatic Paper"

| Token | Hex | Verwendung |
|---|---|---|
| `--bg` | `#f4f0e3` | Seite (warm-creme Papier) |
| `--surface-1` | `#fbf8ed` | Card-Body (lifted) |
| `--surface-2` | `#ebe5d1` | Tabellen-Header, Nested |
| `--surface-3` | `#ddd5b8` | Hover-Backgrounds |
| `--surface-hi` | `#c8bd97` | Hervorgehobene Surface |
| `--border` | `#c2b89c` | Standard-Border |
| `--border-2` | `#948969` | Border bei Hover/Aktiv |
| `--hairline` | `#ddd6c0` | Trennlinien innerhalb Card |
| `--text-1` | `#19170f` | Primaer-Text |
| `--text-2` | `#3a352a` | Sekundaer-Text |
| `--text-3` | `#6a6451` | Tertiaer-Text (Eyebrows, Labels) |
| `--text-4` | `#968d74` | Disabled / Placeholder |
| `--accent` | `#aa6e1d` | Saffron — Aktiv-Tabs, Buttons-Primary, Highlights |
| `--accent-2` | `#8d5810` | Accent-Hover |
| `--accent-bg` | `rgba(170,110,29,0.10)` | Accent-Background-Tints |
| `--accent-line` | `rgba(170,110,29,0.45)` | Accent-Border |
| `--ok` | `#2f7d3c` | Status OK |
| `--warn` | `#a06d12` | Status Warnung |
| `--danger` | `#ad3a23` | Status Fehler/Ueberfaellig |
| `--live` | `#1c7367` | Live-Indicator (Sync-Dot) |
| `--info` | `#344a76` | Mirror-Quelle, Info-States |

#### Farben — Dark-Theme „Hanseatic Terminal"

| Token | Hex | Verwendung |
|---|---|---|
| `--bg` | `#0a0d14` | Seite (Bloomberg-tief) |
| `--surface-1` | `#141a26` | Card-Body |
| `--surface-2` | `#1e2533` | Tabellen-Header |
| `--surface-3` | `#2a3344` | Hover |
| `--border` | `#3a4356` | Standard-Border |
| `--text-1` | `#f7f5ed` | Primaer-Text |
| `--text-2` | `#d7cfbb` | Sekundaer |
| `--accent` | `#f0b76c` | Saffron-Amber |
| `--ok` | `#8ed694` | gedaempftes Moos-Gruen |
| `--warn` | `#f5c668` | Dusty-Yellow |
| `--danger` | `#ee8268` | Terrakotta-Rot |
| `--live` | `#8fd0c8` | Tealgruen |
| `--info` | `#aabddd` | gedaempftes Blau |

(Vollstaendige Token-Liste in `mockups/objektsteckbrief-react/src/index.css`. Diese
Datei ist **die Quelle der Wahrheit**, nicht diese Tabelle.)

**Theme-Wechsel:** per `data-theme="dark"` am Root. Persistierung in `localStorage`,
Default = Light. Toggle in der TopBar.

#### Typografie

| Rolle | Font-Family | Beispiel |
|---|---|---|
| **Display** | `Fraunces` (variable serif) — Hanseatic gravitas | Page-Titel, Section-Titel, Drawer-Titel |
| **UI** | `IBM Plex Sans` | Body-Text, Buttons (in mono), Labels |
| **Daten** | `IBM Plex Mono` mit `tabular-nums`, `lining-nums`, `ss01` | Geld, IDs, Datumsfelder, Counts |

| Stil | Spec |
|---|---|
| `section-eyebrow` | 10 px / Mono / `letter-spacing: 0.22em` / Uppercase / `text-3` |
| `kbd` | 10 px / Mono / 1 px Border / 2×5 px Padding |
| `btn` | 11 px / Mono / Uppercase / `letter-spacing: 0.06em` / 7×12 px Padding |
| `Field`-Label | 10 px / Mono / Uppercase / `letter-spacing: 0.16em` / `text-3` |
| `Field`-Value | 14 px / Sans (oder Mono bei Daten) / `text-1` |
| Section-Title | 22 px / Display (Fraunces) / Light / `opsz 80` |
| Page-Title | 26–28 px / Display / Light / italic-Anteile fuer Untertitel-Phrasen |

**Schriftgroessen-Skala:** 9 / 10 / 11 / 12 / 13 / 14 / 18 / 22 / 26 / 28 / 44 px.
Andere Groessen sind Bug.

#### Spacing & Density

- Tailwind-Default-Spacing-Skala (4 px-Raster).
- **Komponenten-Padding** typisch `px-3 py-2` (Cards), `px-6 pt-5 pb-3` (Section-Header),
  `px-7 py-7` (Page-Main).
- **Card-Innenabstand** zwischen Feldern: `gap-y-5` (20 px), zwischen Spalten `gap-x-6/8`.
- Listen-Reihen: 32–40 px hoch (kompakt).
- **Hairline-Border** (1 px, `--hairline`) zwischen Reihen statt Whitespace — gibt Bloomberg-Gefuehl.

### 3.2 Status-System

Genau **5 States**, jede UI-Komponente bildet darauf ab. Mehr States sind Bug.

| State | Token | Wann | Beispiel |
|---|---|---|---|
| `ok` | `--ok` | Im Soll, Wartung aktuell, Mandat aktiv | Wartung BLITZ OK |
| `warn` | `--warn` | Bald faellig, < 60 d, schwacher Pflegegrad | Police laeuft in 45 d ab |
| `danger` | `--danger` | Ueberfaellig, kritisch, Fehler | Wartung HEIZUNG +12 d ueber |
| `info` | `--info` | Mirror-Quelle, Hinweis, Live-Dot | Letzter Sync, Snapshot |
| `neutral` | `--text-3` | Default, kein State | Ausstattungsmerkmal, Notiz |

Pille-Komponente (`Pill`) ist die Standard-Visualisierung. Frame-Color-Bar links
(3 px breit) ist die Listen-Variante (siehe `ObligationRow`).

### 3.3 Komponenten-Inventar

**Primitives** (in `mockups/objektsteckbrief-react/src/components/ui.tsx`):

| Komponente | Zweck | Wo benutzt |
|---|---|---|
| `ProvenanceIcon` | 9 px-Glyph fuer manual / mirror / ai / derived / missing | Pflicht auf jedem `Field`, in `Sidebar`-Provenance-Bars, in `ProvenanceBar` |
| `Field` | Label + Value + Provenance-Glyph, vertikal | Form- und Detail-Sektionen |
| `IdChip` | Mono-ID mit Label-Eyebrow, 1 px Border | Header-Identitaets-Strip (Impower, Facilioo, WEG-Nr) |
| `Pill` | Status-Indikator klein, 10 px Mono Uppercase | Status-Spalten in Tabellen |
| `Avatar` | Initialen-Chip 26 px, person-Variante (rund) und firm-Variante (eckig + accent-bg) | Listen, Drawer |
| `PflegegradRing` | Score-Ring mit Tick-Frame, Mono-Score in Mitte, Trend-Pille unten | Page-Header, Dashboard-Tiles |
| `Sparkline` | 12-Monats-Linie mit Area-Fill, letzter Punkt markiert | Saldo-Verlauf, KPI-Tiles |
| `Donut` | Single-Percent-Ring mit Mono-Zahl in Mitte | KPI-Tile, Quoten |
| `SectionCard` | Frame mit Eyebrow + Display-Titel + optional Subtitle + Meta-Slot rechts; Bloomberg-Corner-Ticks | Jede Sektion in Detail-/Form-Pages |
| `ProvenanceBar` | Stacked-Bar (manual / mirror / ai / missing), 1 px hoch | Sidebar-Sprungmarken, Section-Header |
| `fmtEUR` / `fmtNum` | Helper de-DE-Formatierung | Ueberall, wo Geld oder Zahlen |

**Composites** (gehen ueber `ui.tsx` hinaus, leben in eigenen Files):

| Komponente | Zweck |
|---|---|
| `KPI-Tile` | 3-Zeilen-Tile: Eyebrow / grosse Zahl / Hint. 4 Tones (danger/warn/info/neutral/ok). |
| `FilterDropdown` | Click-to-open-Dropdown mit aktiv-Highlight-Variante (`accent-bg`). Rendert `label · selected · ▾`. |
| `ViewSwitch` | Inline-Tab-Group mit aktiv-Variante (`accent` als Background). Beispiel: Kanban / Liste / Kalender / Heatmap. |
| `KanbanColumn` + `KanbanCard` | Drag-/Drop-Spalten mit Sortable-Cards (dnd-kit). 300 px breit, Sticky-Column-Header, Tone-Bar links. |
| `DetailDrawer` | 360 px breit, Sticky-Top, Footer-Aktionen-Grid 3-Spalten. Geoeffnet via `selected`-State, geschlossen per `×` rechts. |
| `ReviewQueueDrawer` | 380 px breit, Suggestion-Cards mit Source-Glyph (PDF/Chat/Mirror), Diff-Block (Vorschlag vs. Aktuell), Confidence-Bar mit 80%-Schwellen-Marker, 3-Button-Footer (Anpassen / Ablehnen / Annehmen). |
| `Sidebar (sectional)` | Sprungmarken-Liste mit Provenance-Bar je Sektion + Provenance-Legende unten |

### 3.4 Pattern-Inventar

| Pattern | Zweck / Anwendung |
|---|---|
| **Sticky-Header-Stack** | TopBar (37 px) + PageHeader (variabel) + optional Sub-Header (Filter-Strip). Alle drei sticky, `scroll-margin-top` Anker bei 240 px. |
| **Sidebar-Sprungmarken** | Nur in Detail-Pages mit ≥ 6 Sektionen. Links 220 px, Sticky bei ~230 px Top-Offset. |
| **Drawer rechts** | Kontextueller Detail oder Queue-Inhalt. 360–380 px. Nicht modal — Page bleibt scrollbar. |
| **Drag-Drop-Karte** | Kanban-Pattern. Drop-Targets: Spalten (Bucket-Wechsel) oder andere Karten (Reorder im Spalten-Kontext). Drop-Animation: card rotiert leicht (1.2 deg) waehrend Drag. |
| **Filter-Dropdown** | Inline neben dem Titel. Aktive Filter visuell als `accent-bg`-Pill. Reset-Link zur Rechten erscheint, wenn ≥ 1 Filter aktiv. |
| **View-Switcher** | Inline-Toggle fuer Repraesentations-Wechsel (Kanban/Liste/Kalender/Heatmap). Default zeigt erste Option als aktiv. |
| **KPI-Tile-Strip** | 2–4 Tiles oben rechts neben dem Titel. Min-Breite 120 px. Mit Tone fuer kritische Werte. |
| **Inline-Edit** | Klick auf `Field`-Value öffnet Editor in-place. Provenance wechselt nach Save auf `manual`. (Detail in §5.1) |
| **Live-Sync-Dot** | Pulsierender 1.5 px Dot neben „Letzter Sync"-Zeitstempel. Tealgruen `--live`. |
| **Bloomberg-Corner-Tick** | An jeder `frame-card` 8×8 px Border-Ecken oben-links + unten-rechts in `accent-line`. Pure CSS via `::before`/`::after`. |
| **Section-Eyebrow** | „CLUSTER 06 · FINANZEN"-Stil. Mono, Uppercase, weit gesperrt, Tertiaer-Farbe. Pflicht ueber jedem Section-Titel. |
| **Frame-Card** | Rechteck 1 px Border, `surface-1`. Keine `border-radius`. Corner-Ticks Pflicht. |
| **Hairline-Divider** | 1 px Lineal in `--hairline`. Trennt Content-Zonen innerhalb einer Card. Keine schweren Borders. |

### 3.5 Animationen — sparsam und funktional

| Name | Wann | Spec |
|---|---|---|
| `live-dot` | Neben Sync-Zeitstempel und „live"-States | `pulseDot` 2.4 s loop |
| `fade-up` | Erstes Erscheinen einer Card / Drawer | 550 ms `cubic-bezier(0.16,1,0.3,1)`, 60 ms-Stagger pro Card |
| `drawSweep` | Pflegegrad-Ring beim Initial-Render | 1.2 s `cubic-bezier(0.16,1,0.3,1)` |
| `scanLine` | (Reserviert fuer Live-Sync-Visualisierung in v1.1) | — |

Keine Bouncing-Effekte, keine Spring-Animationen. Bewegung dient Information, nicht Drama.

---

## 4. Page-Templates

Sieben wiederverwendbare Templates. Jedes Template ist ein Gerust mit benannten Slots —
Module fuellen die Slots, erfinden aber nicht das Gerust neu.

### T1 · Detail-View (Steckbrief-Stil)

**Wann:** Komplexe Single-Entity-Sicht mit ≥ 6 Sektionen, gemischten Datenquellen,
Inline-Edit und Sprungmarken. Vorbild: Objektsteckbrief.

```
┌────────────────────────────────────────────────────────────────────────┐
│ TopBar (37 px) · Brand · Modul-Tabs · Cmd+K · Theme · User           │
├────────────────────────────────────────────────────────────────────────┤
│ PageHeader (sticky, ~180 px)                                          │
│ ┌─[breadcrumb] DBS / Objektregister / Hamburg / HAM61 ──[live-dot]─┐ │
│ │ HAM61  Wohnpark Eppendorfer Landstr. 47–49     ┌─────────────┐  │ │
│ │ [Impower 12345] [Facilioo 67] [WEG 142]        │ ⚡ Vorschlag│  │ │
│ │ 14 WE · 3 Häuser · Bj 1924                     │   12 offen │  │ │
│ │                                                 ├─────────────┤  │ │
│ │                                                 │ ◯ Pflegegrad│  │ │
│ │                                                 │     76      │  │ │
│ │                                                 └─────────────┘  │ │
│ │ ─────────────────────────────────────────────────────────────────│ │
│ │ [🔍 Such-Input  ⌘K] [Vollansicht|Kompakt|Risiko]  [PDF][Snap]  │ │
│ └─────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────┤
│ DueRadarBanner (optional, sticky unter PageHeader)                    │
│ "1 Wartung überfällig · 2 Policen in 60 d · Beirat-Pendenz offen"    │
├──────────┬───────────────────────────────────────────────┬────────────┤
│          │                                                │            │
│ Sidebar  │  Main-Content                                  │  Drawer    │
│ (220 px) │  (flex, min-w-0)                               │  (380 px,  │
│ Sprung-  │                                                │   optional)│
│ marken + │  ┌────────────────────────────────────────┐   │            │
│ Provenance│  │ SectionCard (Cluster 1 Stammdaten)     │   │  Review-   │
│-Bar je   │  └────────────────────────────────────────┘   │  Queue     │
│ Sektion  │  ┌────────────────────────────────────────┐   │  oder      │
│          │  │ SectionCard (Cluster 2 Einheiten)      │   │  modul-    │
│          │  └────────────────────────────────────────┘   │  spez.     │
│          │  …                                             │  Drawer    │
│          │  ┌────────────────────────────────────────┐   │            │
│          │  │ Footer: Datenherkunft · Build · Render │   │            │
│          │  └────────────────────────────────────────┘   │            │
└──────────┴───────────────────────────────────────────────┴────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `breadcrumb` | ✓ | Mono-Pfad, max. 3 Tiefen |
| `identity` | ✓ | Kurz-ID (40+ px Mono Accent) + Display-Titel + ID-Chips + Meta-Zeile |
| `kpi-tiles` | optional | 1–3 Tiles (z.B. Pflegegrad-Ring, Vorschlags-Counter, KPI) |
| `toolbar` | ✓ | Such-Input + View-Tabs + Aktions-Buttons |
| `due-banner` | optional | Wenn ≥ 1 querschnittliche Faelligkeit |
| `sidebar` | ✓ ab 6 Sektionen | Sprungmarken mit Sektion-Provenance-Bar |
| `drawer` | optional | Review-Queue oder modul-spezifischer Detail-Drawer |
| `footer` | ✓ | Datenherkunft + Pflegegrad-Berechnung + Render-Versionsstrip |

**View-Modi:** `voll` / `kompakt` (versteckt Cluster 4 Technik) / `risiko` (dimmt
nicht-Risiko-Sektionen auf 30 % Opacity, Pointer-Events off).

### T2 · Board-View (Due-Radar / Kanban-Stil)

**Wann:** Items mit Workflow-Status, die per Drag-Drop in Buckets kippen.
Vorbild: Due-Radar.

```
┌────────────────────────────────────────────────────────────────────────┐
│ TopBar                                                                 │
├────────────────────────────────────────────────────────────────────────┤
│ PageHeader                                                             │
│ Eyebrow: "QUERSCHNITT · CLUSTER 12 · ALLE OBJEKTE"                    │
│ Titel:   Due-Radar — was kippt diese Woche / Monat / Quartal           │
│ Beschreibung 1–2 Zeilen                              [KPI][KPI][KPI]   │
│ ─────────────────────────────────────────────────────────────────────│
│ FILTER  [Objekt ▾] [Typ ▾] [Verantw. ▾] [×Reset]   [Kanban|Liste|...] │
│                                                     [Snooze] [+Neu]    │
├────────────────────────────────────────────────────────────────────────┤
│ Main: 6 Spalten Kanban, horizontal scroll                              │
│ ┌─────┬─────┬─────┬─────┬─────┬─────┐  ┌─DetailDrawer (optional)─┐  │
│ │über-│30 d │60 d │90 d │180 d│ ok  │  │ Item-Detail              │  │
│ │fällig│     │     │     │     │     │  │ Status, Anbieter, Audit  │  │
│ │ ▣▣▣ │ ▣▣  │ ▣   │ ▣▣  │ ▣   │ ▣▣▣ │  │ [Snooze][Steckbrief][OK] │  │
│ │ ▣▣  │     │     │     │     │ ▣▣  │  └──────────────────────────┘  │
│ └─────┴─────┴─────┴─────┴─────┴─────┘                                 │
└────────────────────────────────────────────────────────────────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `eyebrow + title + lead` | ✓ | Beschreibt Querschnitt (welche Objekte, welche Items) |
| `kpi-strip` | ✓ | 2–4 Tiles: Ueberfaellig-Counter, Objekte-betroffen, Volumen-offen |
| `filter-row` | ✓ | 2–4 FilterDropdowns + ggf. Reset-Link |
| `view-switcher` | ✓ | Kanban / Liste / Kalender / Heatmap (View-Wechsel ohne Page-Reload) |
| `secondary-actions` | ✓ | Snooze, +Neu, Bulk-Aktionen |
| `columns` | ✓ | 4–7 Buckets, horizontal scroll bei Bedarf |
| `cards` | ✓ | Mit Object-Code (Accent-Mono), Titel, Detail-Zeile, Footer (Avatar + Volumen + Tage-Delta) |
| `detail-drawer` | optional | 360 px, geoeffnet bei `selectedId`, Footer mit 3-Aktionen-Grid |

### T3 · Listen-/Tabellen-View (Linear/Airtable-Stil)

**Wann:** Registries (Versicherer, Dienstleister, Eigentuemer, …) und das Objektregister.
Hohe Datendichte, viele Spalten, Sortierung, Inline-Filter.

```
┌────────────────────────────────────────────────────────────────────────┐
│ TopBar                                                                 │
├────────────────────────────────────────────────────────────────────────┤
│ PageHeader                                                             │
│ Eyebrow · Display-Titel · 1-Zeilen-Lead · KPI-Strip rechts            │
│ ─────────────────────────────────────────────────────────────────────│
│ TOOLBAR  [🔍 Suche ⌘K] [Filter ▾][Filter ▾]  [Tabelle|Karten|Karte]  │
│                                              [Spalten ▾][Export][+Neu]│
├────────────────────────────────────────────────────────────────────────┤
│ Main: Tabelle (sticky-header)                                          │
│ ┌────┬─────────────┬──────────────┬────────┬────────┬────────┬──────┐│
│ │ ▢  │ Name ▼      │ Typ          │ Volumen│ Ablauf │ Verantw│ Status││
│ ├────┼─────────────┼──────────────┼────────┼────────┼────────┼──────┤│
│ │ ▢  │ Allianz     │ Haftpflicht  │ 5.4 M €│ 31.12  │   DK   │ [OK] ││
│ │ ▢  │ HUK Coburg  │ Wohngebaeude │ 12 M € │ +45d   │   ML   │[WARN]││
│ │ …  │             │              │        │        │        │      ││
│ └────┴─────────────┴──────────────┴────────┴────────┴────────┴──────┘│
│ Footer: 24 / 124 Eintraege · [‹][1][2][3][›]                          │
└────────────────────────────────────────────────────────────────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `bulk-checkbox` | ✓ ab 10 Reihen | Erste Spalte, Header-Checkbox toggelt alle |
| `sortable-headers` | ✓ | Klick-to-sort, Pfeil-Indikator. Multi-Sort via Shift+Click. |
| `inline-filters` | ✓ | FilterDropdown im Toolbar, NICHT in der Header-Zeile |
| `column-toggle` | optional | Spalten-Picker rechts (Mono-Liste mit Checkboxes) |
| `view-switcher` | optional | Tabelle / Karten / Karte (Map) — wenn mehr als eine Repraesentation Sinn ergibt |
| `pagination` | ✓ ab 50 Eintraegen | Numeriert, max. 5 Seiten + Sprung |
| `bulk-action-bar` | ✓ ab gewaehlten Reihen | Erscheint sticky am Bottom: „N gewaehlt · [Aktion 1] [Aktion 2] [Loeschen]" |

### T4 · Form-View / Edit-Modus

**Wann:** Datenpflege (Steckbrief-Edit, Workflow-Konfiguration, User-Edit).
Multi-Sektion, Inline-Save oder Save-All.

```
┌────────────────────────────────────────────────────────────────────────┐
│ PageHeader                                                             │
│ Eyebrow · Titel · Edit-Modus-Pille (`bearbeiten`)  [Verwerfen][Save] │
├────────────────────────────────────────────────────────────────────────┤
│ Sidebar (Sektions-Anker mit „geaendert"-Pill)                         │
│ │ Main                                                                 │
│ │ ┌──────────────────────────────────────────────────────────────┐    │
│ │ │ SectionCard "Stammdaten"                          [Reset Sektion]│
│ │ │  ┌─Field──────────────────┐ ┌─Field──────────────────┐       │    │
│ │ │  │ ◼ STRASSE              │ │ ◼ PLZ / ORT            │       │    │
│ │ │  │ [Eppendorfer Landstr.] │ │ [20249  Hamburg]       │       │    │
│ │ │  └────────────────────────┘ └────────────────────────┘       │    │
│ │ │  ⚡ KI-Vorschlag: „Hausmeister Hr. Meier" → [Annehmen][Ablehnen]│
│ │ └──────────────────────────────────────────────────────────────┘    │
│ │ …                                                                    │
└────────────────────────────────────────────────────────────────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `edit-mode-pill` | ✓ | Im PageHeader sichtbar, dass Page editierbar ist |
| `dirty-indicator` | ✓ | Pro Sektion (Sidebar) + global im PageHeader: „2 Aenderungen" |
| `section-reset` | ✓ | Pro Sektion „Reset Sektion" — verwirft Overrides, faellt auf Auto-Merge zurueck |
| `field-editor` | ✓ | Inline. Save-on-Blur + Save-on-Enter. Provenance-Glyph wechselt sofort. |
| `inline-suggestion` | optional | KI-Vorschlag direkt am Feld, mit Annehmen/Ablehnen-Inline-Buttons |
| `save-all` / `discard-all` | ✓ | Im PageHeader rechts |

### T5 · Wizard / Multi-Step

**Wann:** Mehrstufige Anlage-Workflows (Mietverwaltungs-Anlage, Contact-Create-Sub-Workflow).

```
┌────────────────────────────────────────────────────────────────────────┐
│ PageHeader                                                             │
│ Eyebrow „NEUER FALL · MIETVERWALTUNG"                                 │
│ Titel "Anlage Wohnpark Eppendorfer Landstr."                          │
│                                                                        │
│ Step-Strip (sticky)                                                    │
│ [✓ 1 Dokumente]──[● 2 Extraktion]──[○ 3 Pruefen]──[○ 4 Schreiben]    │
├────────────────────────────────────────────────────────────────────────┤
│ Main (per Step variabel)                                               │
│   Step 1: Drag-Drop-Upload-Zone, hochgeladene Liste                   │
│   Step 2: Extraktions-Status pro PDF, KI-Vorschlaege                  │
│   Step 3: Editierbare Form-View mit allen Feldern, Provenance         │
│   Step 4: Live-Status-Strip "1/8 Contacts angelegt …"                 │
│                                                                        │
│ Footer-Bar (sticky bottom)                                             │
│ [‹ Zurueck]  Step 2 von 4              [Speichern & Weiter ›]         │
└────────────────────────────────────────────────────────────────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `step-strip` | ✓ | Status-Glyphen (✓ done, ● aktiv, ○ kommend); Klick auf done-Step → springt zurueck |
| `step-content` | ✓ | Pro Step eigener Slot |
| `progress-indicator` | ✓ | „Step N von M" |
| `back/forward-buttons` | ✓ | Sticky Bottom; „Weiter" deaktiviert, wenn Pflichtfelder fehlen |
| `cancel-link` | ✓ | Oben rechts, klein, „Abbrechen" — fuehrt zur Bestaetigung „Aenderungen verwerfen?" |
| `auto-save-indicator` | optional | „Letzter Auto-Save vor 12 s" |

### T6 · Dashboard-Home

**Wann:** Eingangsseite nach Login. **Persoenliches** Dashboard, nicht
Plattform-Status.

```
┌────────────────────────────────────────────────────────────────────────┐
│ TopBar                                                                 │
├────────────────────────────────────────────────────────────────────────┤
│ PageHeader (kompakt, ~100 px)                                         │
│ Eyebrow „GUTEN MORGEN, DANIEL · 2026-05-05 · KW 19"                   │
│ Display "Was heute Aufmerksamkeit braucht."                           │
├────────────────────────────────────────────────────────────────────────┤
│ ┌─Inbox──────────────────────────┐ ┌─KPI-Strip────────────────────┐  │
│ │ 12 KI-Vorschlaege offen        │ │ Pflegegrad ∅ 73 / 100        │  │
│ │ 3 Cases in „needs_review"      │ │ Faellig 30 d: 18              │  │
│ │ 2 Notifications                │ │ Annahmequote 87 %             │  │
│ └────────────────────────────────┘ └──────────────────────────────┘  │
│                                                                        │
│ ┌─Modul-Tiles────────────────────────────────────────────────────┐   │
│ │  ┌─Objekt-       ┐ ┌─Workflow-     ┐ ┌─Due-Radar     ┐         │   │
│ │  │ register      │ │ SEPA          │ │ ⚠ 3 ueberf.   │         │   │
│ │  │ 124 Objekte   │ │ Run starten ▸ │ │ ⓘ 18 in 30 d  │         │   │
│ │  └───────────────┘ └───────────────┘ └───────────────┘         │   │
│ │  ┌─Versicherer-  ┐ ┌─Dienstleister-┐ ┌─Mein Portfolio┐         │   │
│ │  │ Registry      │ │ Registry      │ │ 30 Objekte    │         │   │
│ │  └───────────────┘ └───────────────┘ └───────────────┘         │   │
│ └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│ ┌─Aktivitaet-Feed (letzte 24h, gefiltert auf eigene Domain)─────┐    │
│ │ 14:08 ⚡ KI-Vorschlag fuer HAM61 / Heizung-Wartungsfirma       │    │
│ │ 13:55 ◼ Manuelle Pflege HAM61 / Cluster 8 Police HUK          │    │
│ │ 12:31 ↻ Mirror-Run Impower OK · 0 Fehler                       │    │
│ └────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `greeting + date` | ✓ | Personalisiert |
| `inbox` | ✓ | Counter fuer Vorschlaege / Cases / Notifications |
| `kpi-strip` | ✓ | 3–5 Werte ueber Plattform-Aggregate |
| `module-tiles` | ✓ | Nur Module mit Permission. Mit Status-Hint im Tile. |
| `activity-feed` | optional | Letzte 24 h, Filter „nur eigene Aktionen" |

### T7 · Search-/Filter-Result-View

**Wann:** Cmd+K-Modal-Ergebnisse, gespeicherte Suchen, Globalsuche.

```
┌────Cmd+K-Modal────────────────────────────────────────┐
│ [🔍  ____________________________________________] [×]│
│  Suche in Objekte · Personen · Vorgaenge · Workflows  │
├───────────────────────────────────────────────────────┤
│ OBJEKTE (3)                                            │
│   HAM61 · Eppendorfer Landstr. 47–49 · Hamburg ▸     │
│   GVE1  · Tilker · Glemse Verbund                  ▸ │
│   BRE11 · Kulessa · Bremen                          ▸ │
│                                                        │
│ PERSONEN (2)                                           │
│   Heinrich Floegel · Eigentuemer HAM61 WE 7         ▸ │
│   Hr. Meier · Hausmeister 4 Objekte                  ▸ │
│                                                        │
│ FELDER (5)                                             │
│   HAM61 · Cluster 4 · Wasser-Absperrhahn             ▸ │
│   …                                                    │
└───────────────────────────────────────────────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `search-input` | ✓ | Auto-fokussiert. Esc schliesst. |
| `result-groups` | ✓ | Gruppiert nach Entity-Typ. Counts in Klammern. |
| `result-row` | ✓ | Code (Accent-Mono) + Beschreibung + Sub-Info + Pfeil |
| `keyboard-hints` | ✓ | Footer mit `↑↓` navigieren · `↵` oeffnen · `esc` schliessen |
| `recent-searches` | optional | Bei leerer Query: zuletzt gesuchte Items |

### T8 · Empty-Module-Placeholder

**Wann:** Modul ist im Code vorhanden aber nicht aktiviert / nicht konfiguriert.
Vorbild: Versicherer-Registry, Mietverwaltung im Pre-Bootstrap.

```
┌────────────────────────────────────────────────────────────────────────┐
│ PageHeader (regulaer)                                                  │
│ Eyebrow · Titel · 1-Zeilen-Lead                                       │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│       ┌────────────────────────────────────────┐                      │
│       │ ICON / SVG-Glyph (gross, gedaempft)    │                      │
│       │                                        │                      │
│       │ "Noch keine Eintraege."                │                      │
│       │                                        │                      │
│       │ Erklaerungs-Satz, was hier landet,     │                      │
│       │ und wann das Modul Daten zeigt.        │                      │
│       │                                        │                      │
│       │ [PRIMAERE-AKTION ›]  [Doku ›]          │                      │
│       └────────────────────────────────────────┘                      │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**Slot-Spec:**

| Slot | Pflicht | Inhalt |
|---|---|---|
| `glyph` | ✓ | Mono-/Line-SVG, kein Foto/Illustration |
| `headline` | ✓ | „Noch keine X" — kein „Oh!" oder Smileys |
| `explanation` | ✓ | 1–2 Saetze fachlich („Hier landen …") |
| `primary-action` | ✓ | Eindeutiger naechster Schritt |
| `link-to-docs` | optional | Bei komplexen Modulen |

---

## 5. Critical-Interactions-Spec

Sieben Interaktionen, die quer durch die Plattform laufen. Pro Interaktion: Trigger,
Flow, States, Persistence, Audit.

### 5.1 Inline-Edit auf Steckbrief-Feldern

| | |
|---|---|
| **Trigger** | Klick auf Field-Value (Cursor wird zu Text-Cursor on Hover, sichtbarer Hover-Border) |
| **Flow** | (1) Click → Field expandiert in Editor (Input/Select/Textarea je nach Typ) → (2) User editiert → (3) Save-on-Blur ODER Save-on-Enter ODER Esc abbrechen → (4) Optimistic Update der UI → (5) Server-Roundtrip → (6) Provenance-Glyph wechselt auf `manual` → (7) Toast „Gespeichert · vor 2 s" rechts unten |
| **States** | `idle` → `editing` → `saving` (Spinner im Glyph-Slot) → `saved` (Glyph wechselt) ODER `error` (rotes Border, Tooltip mit Fehler) |
| **Persistence** | PATCH `/objects/{id}/fields/{field_key}` mit `{value, override: true}`. Server merged in `_overrides`. |
| **Audit** | `audit("object.field.edit", entity_id=object_id, details={field_key, old_value, new_value})` vor Commit. |
| **Edge-Cases** | (a) Konflikt durch parallele Mirror-Aktualisierung: Server gibt 409 → Toast „Inzwischen wurde dieses Feld vom Mirror aktualisiert. [Werte vergleichen]". (b) Validierungsfehler (z.B. IBAN ungueltig): Server gibt 422 → roter Border + Tooltip mit Fehlertext. |
| **A11y** | Focus bleibt nach Save im Field, damit Tab-Navigation weitergeht. Esc verwirft, ARIA-Live-Region kuendigt „Gespeichert" an. |

### 5.2 KI-Vorschlag-Approval-Flow

| | |
|---|---|
| **Trigger** | (a) Klick auf Suggestion-Card im Review-Queue-Drawer · (b) Inline-Suggestion direkt am Field im Edit-Modus |
| **Flow** | Variante A (Drawer): Card zeigt Vorschlag-vs-Aktuell-Diff, Confidence-Bar, Source-Snippet-Link → 3 Buttons [Anpassen ‖ Ablehnen ‖ Annehmen]. Variante B (Inline): Vorschlags-Pille direkt unter Field-Value, gleiche 3 Buttons inline-mini. |
| **„Annehmen"** | Wert wandert ins Field, Provenance wechselt von `ai` auf `manual` (Annahme = bewusste menschliche Entscheidung), Card faded out im Drawer, Inbox-Counter dekrementiert. |
| **„Ablehnen"** | Vorschlag wandert in Trash-Tab des Drawers (revertierbar 24 h), Field bleibt unveraendert, Audit-Log haelt `rejected_by + rejected_at`. |
| **„Anpassen"** | Inline-Editor oeffnet, Vorschlagswert ist Pre-Fill, User editiert frei, Save → wird wie eigenstaendige manuelle Edit behandelt + KI-Suggestion bekommt `superseded`-Marker. |
| **Bulk-Approve** | Footer-Button im Drawer: Wenn ≥ 1 Card ausgewaehlt → „N annehmen". Bei Confidence < 80 % wird ein Confirm-Dialog vorgeschaltet („Vorschlaege mit Confidence < 80 % einbezogen — sicher?"). |
| **States** | `proposed` → `accepted` / `rejected` / `superseded`. UI-spezifisch: `pending-approval` (gerade aktiv im Drawer), `applying` (Spinner im Card), `applied` (Card faded out 0.6 s). |
| **Persistence** | POST `/review-queue/{id}/accept` / `/reject` / `/supersede`. |
| **Audit** | `audit("review_queue.accept", entity_id=suggestion_id, details={field_key, value, confidence, source})`. |

### 5.3 Drag-Drop mit Audit-Begruendung (Kanban)

| | |
|---|---|
| **Trigger** | Maus drueckt auf Card, bewegt > 6 px (Activation-Constraint dnd-kit). |
| **Flow** | (1) Pointer-Down → Card wird zur DragOverlay-Replik (rotiert 1.2 deg, shadow-2xl) → (2) Spalten zeigen Drop-Target-Border (`border-accent`) bei Hover → (3) Pointer-Up auf Spalte → (4) Wenn Bucket-Wechsel → Begruendungs-Dialog erscheint („Warum schiebst du das aus `ueberfaellig` in `30 d`?") → (5) Begruendung Pflichtfeld bei Bucket-Wechsel, optional bei Reorder → (6) Save → Card wandert mit `fade-up` |
| **States** | `idle` → `dragging` (rotation, opacity 0.4 auf Original) → `drop-pending` (Begruendungs-Dialog) → `applying` → `done` |
| **Edge-Cases** | (a) Drop auf gleiche Spalte: silent Reorder, kein Dialog. (b) Drop ausserhalb Spalte: Card schnappt zurueck. (c) Drop auf nicht-zugaengliche Spalte (z.B. „erledigt" ohne Permission): Card schnappt zurueck + Toast „Keine Berechtigung". |
| **Persistence** | PATCH `/due-radar/{item_id}` mit `{bucket, reason}`. |
| **Audit** | `audit("due_radar.bucket_change", entity_id=item_id, details={from, to, reason, user_id})`. |
| **A11y** | Tastatur-Aequivalent: `Shift+↑/↓` reordert in Spalte, `Shift+←/→` wechselt Bucket (mit Begruendungs-Dialog). |

### 5.4 Cmd+K-Suche ueber Module hinweg

| | |
|---|---|
| **Trigger** | `Cmd+K` (Mac) / `Ctrl+K` (Win) global · Klick auf Such-Pill in TopBar |
| **Flow** | (1) Modal oeffnet zentriert, 600 px breit, dunkler Backdrop (Light-Theme: 60 % opacity bg, Dark: 80 %) → (2) Input auto-fokussiert → (3) Live-Search (Debounce 200 ms) → (4) Ergebnis-Gruppen (Objekte / Personen / Vorgaenge / Felder / Workflows) → (5) `↑↓` navigiert, `Enter` oeffnet, `Esc` schliesst |
| **Such-Scope** | Backend-Endpoint `/search?q=...&types=...`. Default alle Typen. Tab-Filter: `o` Objekte, `p` Personen, `v` Vorgaenge, `f` Felder, `w` Workflows. (Beispiel: `o:HAM` filtert nur Objekte beginnend mit „HAM".) |
| **Treffer-Format** | `[Code Mono Accent] Beschreibung · Sub-Info · ▸`. Bei Field-Treffern zusaetzlich Pfad „Objekt > Cluster > Feld". |
| **States** | `closed` → `open-empty` (zeigt zuletzt-gesucht) → `searching` (Spinner) → `results` / `no-results` / `error` |
| **Persistence** | `recent_searches` lokal pro User in `localStorage` (max. 20). Server-seitig `audit("global_search", details={q, n_results})` nur wenn `q.length >= 3` (kein Spam-Audit pro Tastendruck). |
| **A11y** | ARIA-Combobox-Pattern, `role="listbox"` fuer Ergebnisse, `aria-activedescendant` fuer aktiven Treffer. |

### 5.5 Notifications / Chat-Drawer

(Drei Kanaele teilen sich ein Drawer-Pattern, wechselbar per Tab im Drawer-Header.)

| | |
|---|---|
| **Trigger** | Klick auf Glocken-Icon in TopBar (oeffnet `Notifications`-Tab default) ODER Klick auf Chat-FAB unten rechts (oeffnet `Chat`-Tab) |
| **Tabs im Drawer** | `[Inbox] [Notifications] [Chat]` — Inbox = persistente System-Events, Notifications = ephemere (Toast-faehig), Chat = User-zu-Bot |
| **Flow Notification** | (1) Server pusht Event via SSE → (2) Toast erscheint kurz unten rechts (4 s) → (3) Falls verpasst, Counter im Glocken-Icon bleibt → (4) Klick auf Toast / Glocke oeffnet Drawer im richtigen Tab |
| **Flow Chat** | (1) FAB-Klick → Drawer oeffnet im Chat-Tab → (2) User schreibt, Bot antwortet, Bot kann Kontext-Chips einfuegen (`@HAM61/Cluster-8` deep-linkable) → (3) Chip-Klick scrollt im Hauptcontent zu der referenzierten Stelle |
| **States Notification** | `unread` (fett) → `read` (klick) → `archived` (manuell). Toast-Dauer 4 s, hoverbar (pausiert Auto-Dismiss). |
| **Persistence** | `notifications`-Tabelle: `{user_id, kind, payload, created_at, read_at, archived_at}`. SSE-Stream `/notifications/stream`. Chat-Messages in `chat_messages` mit `kind='user'/'assistant'/'system_notification'` (siehe Backlog 4). |
| **Audit** | Nur fuer User-Aktionen (Mark-as-read, Archivieren, Chat-Send). Nicht fuer Empfangen. |

### 5.6 Datei-Upload (PDF, Foto) mit SharePoint-Integration

| | |
|---|---|
| **Trigger** | (a) Drag-Drop auf Drop-Zone im Wizard / Field · (b) Klick auf „+ Foto/PDF"-Button am Field |
| **Flow** | (1) File ausgewaehlt → (2) Client-Side: Type-Check + Size-Check (PDF max 25 MB, Bild max 10 MB) → (3) Upload mit Progress-Bar → (4) Server speichert in `uploads/{sha256}.{ext}` → (5) Backend-Job: Push nach SharePoint via Graph-API → (6) SharePoint-URL kommt zurueck → (7) Field bekommt Link-Chip mit Datei-Name + Mini-Vorschau |
| **States** | `idle` → `selected` → `uploading` (Progress-Bar) → `uploaded-local` (lokal OK, SharePoint pending) → `synced` (SharePoint OK) ODER `failed` (Retry-Button) |
| **Sichtbarer Sync-Status** | Neben Datei-Chip: `↻ Sync` (pulse) waehrend SharePoint-Push, `✓ SharePoint` nach Erfolg, `⚠ lokal nur` bei SharePoint-Fehler (mit Retry-Button) |
| **Persistence** | `media_assets`-Tabelle mit `{local_path, sharepoint_url, sha256, uploaded_at, sharepoint_synced_at}`. Field-Reference per FK. |
| **Audit** | `audit("media.upload", entity_id=asset_id, details={filename, size, sha256, target_field})`. |
| **Edge-Cases** | (a) PDF ohne Inhalt (0 Bytes): Reject vor Upload. (b) Doppel-Hash erkannt: Server gibt bestehende Asset-ID zurueck, kein zweiter Upload. (c) SharePoint nicht erreichbar: lokal gespeichert + Retry-Job in 30 s. |

### 5.7 Bulk-Aktionen auf Listen / Boards

| | |
|---|---|
| **Trigger** | Checkbox in Tabellen-Header ODER Klick auf einzelne Reihen-Checkboxen |
| **Flow** | (1) ≥ 1 Reihe gewaehlt → Bulk-Action-Bar erscheint sticky am unteren Rand → (2) „N gewaehlt · [Aktion 1] [Aktion 2] [Loeschen]" → (3) Klick auf Aktion → bei destruktiven Aktionen Confirm-Dialog mit Anzahl |
| **States** | `none-selected` (Bar nicht sichtbar) → `selecting` (Bar slides up) → `applying` (Spinner an Aktion-Button) → `done` (Toast „N geaendert", Selection cleared) |
| **Erlaubte Aktionen je Modul** | `Versicherer-Registry`: Export · Tag setzen · Faelligkeits-Snooze · Loeschen. `Due-Radar`: Bucket-Wechsel · Verantwortlich neu zuweisen · Snooze. `Review-Queue`: Bulk-Approve (siehe 5.2) · Bulk-Reject. |
| **Persistence** | POST `/{module}/bulk` mit `{ids: [...], action, params}`. Server fuehrt atomic in einer Transaktion aus, gibt Per-Item-Status zurueck. |
| **Audit** | Ein Audit-Eintrag mit `count` + `ids` (gekuerzt > 100), nicht ein Eintrag pro ID. |
| **A11y** | Header-Checkbox als „indeterminate" wenn 1 ≤ N < total. Shift+Click selektiert Range. |

---

## 6. State-Coverage-Matrix

Pflichtuebung pro Pattern. Wenn ein Pattern hier keinen State hat, ist die Zelle als
„nicht anwendbar" zu interpretieren — nicht als „vergessen".

| Pattern | empty | loading | error | partial | no-permission |
|---|---|---|---|---|---|
| **Liste/Tabelle (T3)** | „Noch keine Eintraege. [Primaeraktion]" — gleiches Empty-Template wie T8, aber kompakter | Skeleton-Reihen 5 Zeilen, Mono-Pulse-Animation | Banner oben „Konnte nicht geladen werden. [Erneut versuchen]" + leere Tabelle | Banner „N von M geladen, Rest folgt …" + sichtbare Reihen + Loader unten | Liste nicht gerendert, stattdessen Empty-Template mit Hint „Du hast keine Berechtigung fuer N Modul" |
| **Detail-View (T1)** | n/a (Detail ohne Daten = Bug) | Skeleton: PageHeader-Skeleton + Section-Skeletons (3 Cards leer) | Volle Page-Error: „Objekt {id} konnte nicht geladen werden. [Erneut versuchen][Zurueck zur Liste]" | Sektionen einzeln laden, jede Section-Card hat eigenen Loading-State | 403-Page mit Erklaerung + Link zum Admin |
| **Board (T2)** | „Keine Items in den Filtern. [Filter zuruecksetzen]" pro Spalte | Spalten zeigen je 2 Card-Skeletons | Spalten leer + Banner oben | Manche Spalten geladen, andere noch nicht: pro Spalte Mini-Loader im Header | wie Liste |
| **Form (T4)** | n/a | Form leer + Loader-Overlay | Roter Banner oben mit Server-Fehler-Detail; Form bleibt editierbar (lokale Aenderungen nicht verloren) | n/a (Form ist atomar) | Felder als read-only gerendert |
| **Wizard (T5)** | n/a | Step-Content zeigt Loader; Step-Strip bleibt navigierbar | Banner im Step + „Speichern" deaktiviert | Step zeigt „X von Y verarbeitet" + Live-Refresh | Wizard nicht startbar, Tile auf Dashboard mit Hint |
| **Dashboard (T6)** | „Keine Aktivitaet heute" pro Aktivitaet-Feed; KPIs zeigen `—` | Tiles als Skeleton, KPIs als Mono-Pulse | KPI zeigt `—` mit Tooltip „Wert konnte nicht geladen werden" | Manche Tiles laden, andere noch nicht; Mini-Loader pro Tile | Tile nicht gerendert, kein Hint („nicht da" = nicht da) |
| **Search-Result (T7)** | „Tippe ≥ 2 Zeichen" + zuletzt gesucht | Spinner-Inline waehrend Debounce + Fetch | Banner „Suche fehlgeschlagen, Server unreachable" | Gruppen erscheinen progressiv, sobald Backend liefert | Treffer in nicht-zugaenglichen Modulen werden ausgegraut + Tooltip „Keine Berechtigung" |
| **ReviewQueueDrawer** | „Keine offenen Vorschlaege. [Filter ▾]" + Annahmequote unten | 3 Card-Skeletons mit Pulse | Banner oben + Footer „Erneut versuchen" | Live-Stream: neue Cards faden ein per `fade-up` | Drawer nicht oeffenbar, Sparkle-Icon ausgegraut |
| **DetailDrawer (Board/Liste)** | n/a | Spinner-Center | „Item konnte nicht geladen werden, [Schliessen]" | n/a | Drawer nicht oeffnen, Toast-Fehler stattdessen |
| **Inline-Edit-Field** | n/a | Glyph wird Spinner | Roter Field-Border + Tooltip mit Fehlertext | n/a | Field nicht klickbar, kein Hover-Border |
| **File-Upload-Dropzone** | „Datei hierher ziehen oder [waehlen]" | Progress-Bar pro Datei | Pro Datei rote Pille + [Erneut] | Mehrere Files: Progress-Liste pro File | Drop-Zone deaktiviert, Hint „Keine Upload-Berechtigung" |
| **KPI-Tile** | Wert `—` mit Tooltip „Keine Daten" | Mono-Pulse `··· /100` | `—` mit Tooltip „Fehler beim Berechnen" + Retry-Icon | Wert mit Live-Dot in Eyebrow | Tile nicht gerendert |
| **Notification-Toast** | n/a | n/a | Toast-Variante mit `danger`-Tone | n/a | n/a |

**Meta-Regel:** Jeder neue Komponenten-Entwurf muss diese Matrix ergaenzen, sonst ist
er nicht review-ready.

---

## 7. Responsive-Strategie

**Definition:** Desktop-First Web-App fuer Verwalter-Arbeitsplaetze.

### 7.1 Breakpoints

| Breakpoint | Zielgeraet | Verhalten |
|---|---|---|
| **≥ 1440 px** | Verwalter-Standard, externe Monitore | Voller Layout, Drawer offen, Sidebar offen, alle 3 Spalten der Tabellen sichtbar. **Default-Entwicklungs-Breite.** |
| **1280–1439 px** | Kleinerer Desktop, 13–14" Laptop angedockt | Drawer collapsen Sidebar standardmaessig auf 0 px (kann manuell aufgeklappt werden), Tabelle behaelt alle Spalten |
| **1024–1279 px** | Laptop ohne Monitor | Sidebar nicht mehr sticky, wandert ueber Burger-Menu links. Drawer rechts wird modal (overlay). Tabellen koennen weniger wichtige Spalten ausblenden (Spalten-Picker) |
| **800–1023 px** | Tablet quer / kleines Laptop | Detail-View verliert Sidebar komplett (Sprungmarken werden zu Sticky-Tab-Bar oben), KPI-Strip wird vertikal, Tabellen werden zu Card-Listen |
| **< 800 px** | Smartphone | **Edge-Case** — nur 4 Pages funktionieren voll: Dashboard-Inbox, Steckbrief Cluster 4 (Notfall), Cmd+K-Suche, Auth/Login. Alles andere zeigt Banner: „Diese Ansicht ist fuer Desktop optimiert. [Trotzdem fortfahren]" |

### 7.2 Mobile-Pflicht-Pages

Diese Pages **muessen** auf 360 px lesbar funktionieren:

1. **Steckbrief Cluster 4 Technik** — Notfall-Handwerker (P3). Mono-Layout, Foto-Lightbox-Vollbild, Click-to-Reveal-Codes mit grossem Touch-Target.
2. **Cmd+K-Suche** — Suche-Modal in Vollbild auf Mobile, Treffer scrollbar.
3. **Dashboard-Inbox** — Eine Spalte, Counter + Liste.
4. **Auth/Login** — OAuth-Redirect, einfache Klick-Pages.

Alle anderen Pages dürfen auf < 800 px im Best-Effort-Modus laufen (kein Bug, aber kein Gold-Standard).

### 7.3 Adaptive Komponenten

| Komponente | ≥ 1440 | 1024–1439 | < 1024 |
|---|---|---|---|
| `AppShell.TopBar` | voll, mit Modul-Tabs | voll | Logo + Burger + Cmd+K-Pill + User-Chip |
| `Sidebar` (Sektion-Sprungmarken) | 220 px sticky | 220 px sticky | Sticky-Tab-Bar oben, horizontal scrollbar |
| `ReviewQueueDrawer` | 380 px sticky open | sticky togglebar | Modal Overlay |
| `KPI-Strip` | horizontal | horizontal | vertikal (1 Spalte) |
| `Tabelle` | alle Spalten | Spalten-Picker | Card-Liste mit Hauptfeldern + Detail-Drawer |
| `Kanban-Board` | horizontal scroll, 6 Spalten | wie 1440 | Spalten gestapelt vertikal, kollabierbar |

### 7.4 Touch-Targets

Bei < 1024 px: Touch-Targets minimum **40 px Hoehe**. Click-to-Reveal-Codes,
Drag-Handles, FilterDropdowns muessen vergroessert werden — nicht durch
groesseren Font, sondern durch zusaetzliches Padding.

---

## 8. A11y-Anforderungen

**Mindeststandard:** WCAG 2.1 AA. Wenn ein Pattern hier nicht abgedeckt ist, gilt die
WCAG-Default-Empfehlung.

### 8.1 Kontrast

Beide Themes wurden ausgelegt mit ≥ 4.5:1 fuer Body-Text, ≥ 3:1 fuer UI-Komponenten.
Spot-Check bei Light-Theme:

| Foreground / Background | Ratio | OK? |
|---|---|---|
| `text-1 #19170f` auf `bg #f4f0e3` | ~ 14:1 | ✓ |
| `text-2 #3a352a` auf `surface-1 #fbf8ed` | ~ 9:1 | ✓ |
| `text-3 #6a6451` auf `bg #f4f0e3` | ~ 4.6:1 | ✓ (knapp) |
| `accent #aa6e1d` auf `bg #f4f0e3` | ~ 4.7:1 | ✓ (knapp; nicht fuer Body, nur fuer Akzent OK) |
| `ok #2f7d3c` / `warn #a06d12` / `danger #ad3a23` auf `bg` | ~ 4.5–5.5:1 | ✓ |

**Regel:** `text-4` ist **nicht** body-zulaessig — nur Disabled / Placeholder.

Dark-Theme analog mit hellen Werten gegen dunkle Surfaces ≥ 4.5:1.

### 8.2 Tastatur-Navigation

| Action | Shortcut | Wo |
|---|---|---|
| Cmd+K-Suche | `⌘K` / `Ctrl+K` | global |
| Theme wechseln | `⌘⇧L` | global (Vorschlag) |
| Modul-Tab N | `⌘1..9` | global |
| In Sidebar springen | `g s` | Detail-View (Vim-Style) |
| Naechste/Vorherige Sektion | `j` / `k` | Detail-View |
| Drawer toggeln | `⌘.` | Detail-View / Board |
| Karte verschieben | `Shift+←/→` (Bucket), `Shift+↑/↓` (Reorder) | Board |
| Speichern | `⌘S` | Form / Wizard |
| Esc | schliesst Modal/Drawer | global |

**Fokus-Ringe:** `outline: 1px solid var(--accent); outline-offset: 2px` global per `:focus-visible`. Nicht uebermalen.

**Tab-Order:** Linear durchs DOM, `tabindex` nicht setzen (ausser fuer Skip-Links).

### 8.3 ARIA-Landmarks

Pflicht-Landmarks pro Page:

```html
<header role="banner">                    <!-- AppShell.TopBar -->
<nav role="navigation" aria-label="Modul">  <!-- TopBar Modul-Tabs -->
<main role="main">                         <!-- Page-Main-Content -->
<aside role="complementary" aria-label="Review-Queue"> <!-- Drawer -->
<nav role="navigation" aria-label="Sektionen"> <!-- Page-Sidebar -->
<footer role="contentinfo">                <!-- Page-Footer -->
```

Skip-Link „Zum Hauptinhalt" als erstes Element hinter `<body>` (nur bei `:focus` sichtbar).

### 8.4 Screen-Reader-Patterns

| Pattern | ARIA-Pattern |
|---|---|
| Cmd+K-Modal | `role="dialog"` + `aria-modal="true"` + Focus-Trap |
| Drawer | `role="region"` + `aria-label="..."` + ESC schliesst |
| FilterDropdown | `role="combobox"` + `aria-expanded` + `aria-controls` + `aria-activedescendant` |
| Tab-Group (View-Switcher, Modul-Tabs) | `role="tablist"` mit `role="tab"`-Children, `aria-selected` |
| Status-Pille | `role="status"` mit `aria-label="Status: faellig in 12 Tagen"` |
| Toast-Notification | `role="status"` + `aria-live="polite"` (oder `assertive` bei Error) |
| Inline-Edit Save | ARIA-Live-Region announces „Gespeichert" oder Fehlermeldung |
| Provenance-Glyph | `aria-label="Quelle: KI-Vorschlag offen"` (gleiche Texte wie `title`) |
| Kanban-Card Drag | `role="button"` + `aria-grabbed` + Tastatur-Aequivalent (siehe 5.3) |
| Pflegegrad-Ring | `role="meter"` + `aria-valuenow="76"` + `aria-valuemin="0"` + `aria-valuemax="100"` |

### 8.5 Datentabellen

- Pflicht `<thead>` mit `<th scope="col">` pro Spalte.
- Bei Spalten-Sort: `aria-sort="ascending|descending|none"` am `<th>`.
- Bei Bulk-Selection: Header-Checkbox mit `aria-label="Alle waehlen"`, jede Reihen-Checkbox mit `aria-label="{Name} waehlen"`.
- Tabular-Numerals → `font-variant-numeric: tabular-nums`.

### 8.6 Reduced Motion

User-Setting respektieren:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
  .live-dot { animation: none; opacity: 1; }
}
```

Live-Dot wird zum statischen Punkt, `fade-up` und `drawSweep` werden Instant.

### 8.7 Sprachen + Lokalisierung

- HTML-Lang: `<html lang="de">`.
- Datumsformat: `de-DE` (TT.MM.JJJJ), Geld via `Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' })`.
- Mono-IDs (HAM61, IBANs, Police-Nrs) sind nicht uebersetzbar — bleiben als `<code>` getagged.
- Falls spaeter mehrsprachig: alle UI-Strings in `i18n`-Keys, kein hartkodierter Text in TSX.

---

## 9. Konventionen fuer modul-spezifische Konkretisierungen

Wenn ein Modul-Team eine neue Page entwirft:

1. **Welches Template?** Aus §4 (T1–T8) waehlen. Wenn keines passt, eine neue T9 in dieser Spec begruenden — kein „freier" Layout pro Modul.
2. **Welche Slots fuelle ich?** Pflicht-Slots immer. Optionale nur, wenn fachlicher Bedarf.
3. **Welche Komponenten verwende ich?** Aus §3.3 / 3.4. Wenn fehlend, neue Komponente in dieser Spec hinzufuegen + in `mockups/objektsteckbrief-react/src/components/ui.tsx` implementieren.
4. **Welche Interactions?** Aus §5. Bei neuer Interaction-Klasse: §5 erweitern + State-Coverage-Matrix in §6 ergaenzen.
5. **Welche States deckt mein Pattern?** Alle aus der Matrix in §6 — kein „loading" vergessen.
6. **A11y-Selbstcheck?** §8.4-Patterns durchgehen. Tastatur-Pfad funktioniert ohne Maus.

Dieses Dokument ist das **Vetorecht** der UX-Spec — wenn ein Modul abweichen will, muss
diese Spec erweitert werden, nicht das Modul „kreativ" sein.

---

## 10. Glossar

| Begriff | Definition |
|---|---|
| **Provenance** | Herkunft eines Datenfelds. 5 Kategorien: `manual` (Mensch hat eingetragen), `mirror` (aus Impower/Facilioo gespiegelt), `ai` (KI-Vorschlag, noch nicht angenommen), `derived` (berechnet aus anderen Feldern), `missing` (leer). |
| **SoR** | System of Record — die autoritative Quelle fuer ein Feld. Defaults siehe Brainstorming §3. |
| **Pflegegrad** | Vollstaendigkeits-/Qualitaets-Score 0–100 pro Objekt, cluster-gewichtet. |
| **Review-Queue** | Liste aller offenen KI-Vorschlaege, die ein Mensch annehmen / ablehnen / anpassen muss. |
| **Due-Radar** | Querschnitts-View ueber Wartungspflichten, Policen, Vertraege, Beschluesse mit Faelligkeit. |
| **Mirror** | Periodische Kopie von Impower/Facilioo-Daten in die lokale Datenbank (Nightly). Vs. Live-Pull (jeder Render-Request fragt frisch). |
| **Cluster** | Logische Feldgruppe im Steckbrief (1–10 inhaltlich, 11–12 Querschnitt). |
| **Hanseatic** | Stilrichtung dieser Plattform — warmes Papyrus/dunkles Bloomberg, hanseatische Editorial-Typografie, kein generisches SaaS-Pastell. |

---

## Anhang A — Hanseatic-Stil-Cheatsheet

Was diese Plattform optisch vom Generic-SaaS-Look trennt:

| Generic-SaaS | Hanseatic-Plattform |
|---|---|
| Pastell-Hintergrund, weisser Header | Warm-creme Papier (`bg #f4f0e3`) ohne harte Header-Trennung |
| Material-Design-Cards mit `border-radius: 8` und Drop-Shadow | `frame-card`: 1 px Border, **0 px Border-Radius**, Bloomberg-Corner-Ticks |
| Friendly Sans-Serif (Inter, Poppins) | Display: Fraunces (variable serif) · UI: IBM Plex Sans · Daten: IBM Plex Mono |
| Knallige Status-Farben (Tailwind-Default) | Gedaempft (Moos-Gruen, Dusty-Yellow, Terrakotta) |
| Emoji-Reactions, Smileys, Confetti | **Keine Emojis im UI.** Mono-Glyphen (`▣ ◐ ↻ ⚡`) statt. |
| Bouncing-Animations | Lineare Transitions, `cubic-bezier(0.16,1,0.3,1)`, sparsam |
| Whitespace-fokussiert | **Datendichte** — Hairlines (1 px), kompakte Reihen, tabular-nums |
| Friendly Empty-States mit Illustration | Mono-Line-SVG + 1-Satz-Erklaerung + 1 Aktion |
| „Kreativer" Brand-Ton | Sachlich, hanseatisch-trocken (siehe Display-Titel-Beispiele) |

---

## Anhang B — Was diese Spec NICHT regelt

- **Brand / Logo / Marketing-Pages** — interne Plattform, keine Marke.
- **User-Research / Interview-Transkripte** — Personae stehen aus dem Brainstorming.
- **Frontend-Stack-Wahl** (React vs. Vue vs. Solid) — laeuft parallel via `bmad-technical-research`.
- **Backend-Endpoint-Schemas** — gehoeren in `docs/api-contracts.md`.
- **Datenbank-Migrationen** — gehoeren in `migrations/`.
- **Pixel-perfekte High-Fidelity-Mockups** — die zwei vorhandenen Mockups sind Stilrichtungs-Referenzen, nicht Pflicht-Vorlagen pro Page.

---

**Letzte Aenderung:** 2026-05-05 · Daniel Kroll
