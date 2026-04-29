# SPA-Migration — BMAD-Briefings

**Stand:** 2026-04-28
**Zweck:** Uebergabe-Bloecke fuer den BMAD-Pfad zur Migration auf SPA-Frontend
(Variante C). In jeweils einer **frischen Conversation** an den jeweiligen
BMAD-Skill geben — so weiss der Agent ab Sekunde 1, was er soll und welche
Files er lesen muss.

**Kontext der Entscheidung:** Diskussion am 2026-04-28 — nach UX-Mockup-Demo
(Objektsteckbrief + Due-Radar Kanban als React-Insel, Variante B) und
ergaenzendem Brainstorming hat der User sich fuer **Variante C** (vollstaendige
SPA-Frontend-Architektur gegen FastAPI-JSON-API) entschieden.

---

## Briefing 1 — fuer `/bmad-technical-research`

```
KONTEXT
- Projekt: Dashboard KI-Agenten, internes B2B-Tool der DBS Home GmbH
  (Hausverwaltung). Live auf https://dashboard.dbshome.de via Elestio.
- Aktueller Stack: FastAPI 0.115 + HTMX 2 + Jinja2 + Tailwind (CDN) +
  Postgres 16 + SQLAlchemy + Authlib (Google Workspace OAuth).
- Strategische Entscheidung getroffen: Wechsel auf vollstaendige SPA-Frontend-
  Architektur (Variante C). Begruendung: HTMX skaliert nicht in die
  UX-Komplexitaet kommender Module (Boards, Detail-Views mit hoher Datendichte,
  globaler Chat-Drawer, Cmd+K-Suche, Multi-Tab-Workflows).
- Backend bleibt FastAPI — kein Sprachwechsel. Domain-Logik (Impower-Connector,
  Claude-Integration, Mietverwaltungs-Pipeline) ist battle-tested und zu wertvoll
  zum Wegwerfen.

WAS BEREITS GEMACHT IST
- Zwei React-Insel-Mockups als Proof-of-concept gebaut, laufen lokal mit
  Vite + React 18 + TS + Tailwind + @dnd-kit:
  - Objektsteckbrief-Detailseite (Cluster 1-8 aus Feldkatalog)
  - Due-Radar als Kanban mit Drag-Drop ueber 8 Objekte
- Stilrichtung "Hanseatic" steht (Light + Dark Theme, Fraunces + IBM Plex
  Sans/Mono, Saffron-Akzent).
- Mockups sind portierbar — kein Wegwerf-Material.

DEIN AUFTRAG (Technical Research)
Liefere ein recherchiertes Stack- und Migrations-Pattern-Dokument als Foundation
fuer das nachfolgende Architecture-Doc. Fokus auf drei Themen:

1. STACK-WAHL FRONTEND
   Vergleiche mit echten Belegen (Bundle-Size, DX, Migration-Erfahrungen
   anderer):
   - Vite + React + TanStack Router + TanStack Query
   - Next.js (App Router)
   - Remix / React Router 7
   - TanStack Start
   - SvelteKit
   Auswahlkriterien fuer DIESES Projekt:
   - Internes B2B-Tool (kein SEO, alles hinter Login)
   - FastAPI als reine JSON-API
   - Solo-Entwickler mit Claude Code als Kollaborator
   - Static-Site-Hosting moeglich (Elestio + Caddy/Nginx)
   - Vorhandene React-18-Mockups muessen 1:1 weiternutzbar sein
   - Lock-In-Risiko (Vercel-Bindung, RSC-Magie) explizit bewerten

2. MIGRATIONS-PATTERN
   Strangler-Pattern vs. Greenfield-Pilot vs. Big-Bang.
   Speziell fuer: laufende Produktion, mehrere parallele Module
   (SEPA-Workflow, Mietverwaltung, Admin-Bereich, neue Objektsteckbrief-/
   Registry-Module), Solo-Dev. Erfahrungswerte aus aehnlichen Migrationen
   (HTMX → SPA / SSR → CSR).

3. AUTH + CO-EXISTENCE
   Wie betreibt man HTMX-Pages und SPA-Pages auf gleicher Domain mit gleichem
   Auth? Cookie-Auth weiterverwenden vs. JWT. CORS / SameSite / CSRF-Setup.
   Subpath-Mounting auf Elestio (Caddy/Nginx vor FastAPI).

EINGANGSMATERIAL ZUM LESEN
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/CLAUDE.md
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/docs/architecture.md
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/docs/source-tree-analysis.md
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/docs/deployment-guide.md
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/mockups/objektsteckbrief-react/package.json
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/mockups/objektsteckbrief-react/README.md
- Elestio-Setup steht in Memory: reference_elestio_deployment.md

OUTPUT
docs/research/spa-stack-und-migration.md mit:
- Klare Empfehlung pro Thema, mit Begruendung
- Trade-off-Tabelle pro Stack-Kandidat
- Verworfene Alternativen + Verwerfungsgrund
- Quellen / Belege (gerne WebSearch fuer aktuelle Diskussion)
- Konkrete Mengenangaben wo sinnvoll (Bundle-Budget-Empfehlung,
  CI-Build-Zeit-Erwartung, Personentage pro Modul-Migration)

USER-PRAEFERENZEN
- Sprache: Deutsch (Output-Doku auf Deutsch)
- Tempo: keine ausufernden Erklaerungen, knappe Bullets
- Pragmatismus ueber Hype — was funktioniert fuer Solo-Dev
- Kein Marketing-Geschwurbel von Framework-Anbietern uebernehmen, kritische
  Lesart

WAS DANACH KOMMT
Dieses Dokument ist Foundation fuer:
- bmad-create-ux-design (UX-Spec, parallel-zeitig)
- bmad-create-architecture (Architektur-Doc, baut auf TR + UX auf)

Bitte starte mit Lesen der Eingangsmaterialien, dann strukturierter Rechercheplan,
dann Dokumenterstellung. Bei Stack-Vergleich nicht alles abklappern — Tiefenfokus
auf 2-3 ernsthafte Kandidaten plus klare Verwerfungsbegruendung fuer den Rest.
```

---

## Briefing 2 — fuer `/bmad-create-ux-design`

```
KONTEXT
- Projekt: Dashboard KI-Agenten, internes B2B-Tool der DBS Home GmbH
  (Hausverwaltung). 5+ Plattform-Module: SEPA-Lastschrift, Mietverwaltung,
  Contact-Create-Sub-Workflow, Admin/Audit, kommend: Objektsteckbrief +
  Versicherer-Registry + Dienstleister-Registry + Due-Radar global.
- Strategische Entscheidung: Wechsel auf SPA-Frontend (Variante C).
- Stack-Recherche laeuft parallel via bmad-technical-research.

WAS BEREITS AN UX MATERIAL EXISTIERT
- Zwei produktionsnahe React-Mockups (mockups/objektsteckbrief-react/):
  - Objektsteckbrief-Detailseite — Detail-View mit 5 Sektionen, Sidebar-Nav,
    Pflegegrad-Score, Provenance-Indikatoren pro Feld, KI-Review-Queue-Drawer
  - Due-Radar — Kanban mit Drag-Drop, Filter-Bar, Detail-Drawer, KPI-Tiles
- Stilrichtung "Hanseatic" mit zwei Themes:
  - Hell: warmes Papyrus + deep Saffron + Fraunces/IBM Plex
  - Dunkel: Bloomberg-Terminal-Stil
- Brainstorming-Session fuer Objektsteckbrief mit 10 Stakeholder-Personae
  durchgespielt — die sind direkt als UX-Personae uebernehmbar
- Feldkatalog mit ~92 Feldern in 12 Clustern als Datenbasis
- Backlog Punkt 4: zentraler User-Chat / Notification-Hub als
  Querschnitts-Feature geplant

DEIN AUFTRAG (Create UX Design)
Liefere eine UX-Spezifikation, die als Foundation fuer alle folgenden
Module dient — KEIN Mockup-Inferno, sondern wiederverwendbare Schablonen.

1. INFORMATION ARCHITECTURE
   Sitemap aller geplanten Module + Verlinkungen + Hierarchien.
   Globale Navigation (App-Bar) vs. Modul-Navigation (Page-Header) sauber
   trennen. Querschnittsfunktionen (Cmd+K, Notifications, Chat) verorten.

2. PERSONAE-FLOWS
   Aus den 10 Brainstorming-Rollen UX-Personae machen, jeweils mit:
   - Job-to-be-done
   - Kritischer Flow (3-5 Schritte) durch das System
   - Welche Module/Pages der Persona begegnen
   Personae aus Brainstorming-Doc:
   - Notfall-Handwerker (Sa 2 Uhr nachts)
   - Buchhalterin (Monatsende)
   - Neue Mitarbeiterin (Tag 1)
   - WEG-Beirat vor ETV
   - Versicherungsmakler bei Schaden
   - KI-Agent (Data-Perspektive — keine UI, aber API-Anforderungen)
   - Mieter mit Reklamation
   - Due-Diligence-Pruefer
   - ESG-/Energieberater
   - Vermarktung / Mietersuche

3. DESIGN-SYSTEM-INVENTAR
   Aus den Mockups extrahieren und systematisch dokumentieren:
   - Design-Tokens (siehe mockups/objektsteckbrief-react/src/index.css —
     bereits sauber strukturiert, beide Themes)
   - Components: ProvenanceIcon, Pill, IdChip, Avatar, PflegegradRing,
     Sparkline, Donut, ProvenanceBar, FieldDisplay, SectionCard
   - Patterns: Sticky-Header-Stack, Sidebar-Sprungmarken, Drawer rechts,
     Drag-Drop-Karte, Filter-Dropdown, View-Switcher, KPI-Tile, Status-Pills
   - Status-System: ok/warn/danger/info/neutral mit Hex-Werten

4. PAGE-TEMPLATES
   Definiere ~6-8 wiederverwendbare Templates, je mit Skizze + Slot-Spec:
   - Detail-View (vorhanden)
   - Board-View (vorhanden)
   - Listen-/Tabellen-View (Linear/Airtable-Style — kommt fuer Registries)
   - Form-View / Edit-Modus (kritisch fuer Steckbrief-Pflege)
   - Wizard / Multi-Step (Mietverwaltungs-Anlage)
   - Dashboard-Home (Eingangsseite)
   - Search-/Filter-Result-View
   - Empty-Module-Placeholder (Modul vorbereitet, aber leer)

5. CRITICAL-INTERACTIONS-SPEC
   Pro Pattern: Trigger, Flow, States, Persistence, Audit:
   - Inline-Edit auf Steckbrief-Feldern (mit Provenance-Setzung)
   - KI-Vorschlag-Approval-Flow (Annehmen/Ablehnen/Anpassen)
   - Drag-Drop mit Audit-Begruendung (Kanban)
   - Cmd+K-Suche ueber Module hinweg
   - Notifications/Chat-Drawer
   - Datei-Upload (PDF, Foto) mit SharePoint-Integration
   - Bulk-Aktionen auf Listen/Boards

6. STATE-COVERAGE
   Fuer jedes Pattern: empty / loading / error / partial / no-permission.
   Hier wird's haeufig vergessen — pflicht.

7. RESPONSIVE-STRATEGIE
   Desktop-First (Verwalter-Arbeitsplatz, 1440px+).
   Was passiert bei 1024px (kleinerer Laptop)? Was unter 800px?
   Mobile ist Edge-Case (Notfall-Handwerker mit Smartphone) — kein
   Vollumfang noetig, aber kritische Pages duerfen nicht broken sein.

8. A11Y-ANFORDERUNGEN
   WCAG AA als Mindest. Tastatur-Navigation, Fokus-Ringe, ARIA-Landmarks,
   Kontrast-Werte (in Mockup-Themes bereits durchgerechnet).

EINGANGSMATERIAL ZUM LESEN
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/CLAUDE.md
  (Module-Status, Backlog-Punkte 1-7)
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/docs/brainstorming/objektsteckbrief-2026-04-21.md
  (10 Personae, 92 Ideen, Cluster-Cuts)
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/docs/objektsteckbrief-feld-katalog.md
  (Datenbasis fuer Detail-View)
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/docs/architecture.md
  (Module-Uebersicht)
- /Users/daniel/Desktop/Vibe Coding/Dashboard KI-Agenten/mockups/objektsteckbrief-react/
  alle Files in src/components/ + src/pages/ + src/index.css + README.md
  (Stilrichtung + Component-Inventar als Vorlage)

OUTPUT
docs/ux-design-spa-frontend.md mit den 8 oben genannten Abschnitten.
Lieber wenige scharfe Templates als viele wackelige Mockups.
ASCII/Markdown-Sketches sind OK fuer Templates — keine Pixel-Perfect-Pflicht.

CONSTRAINTS / NICHT-VERHANDELBAR
- Sprache: Deutsch (Output auf Deutsch)
- Hanseatic-Stilrichtung (siehe Mockups) — keine generische SaaS-Aesthetik
- Provenance-System ist Pflicht-Bestandteil ALLER Datenpraesentationen
- KI-Vorschlaege laufen IMMER ueber Review-Queue, nie direkter Schreibvorgang
  (Plattform-Prinzip)
- Desktop-First (Verwalter-Arbeitsplatz, breite Bildschirme)
- Datendichte ueber Whitespace — Bloomberg/Linear/Notion-Vorbild, kein
  Material-Design-Pastell

WAS DU NICHT MACHEN SOLLST
- Keine 15 Page-Mockups malen — Templates definieren reicht
- Kein User-Research / Interviews durchspielen — Personae stehen schon
- Kein Brand-/Logo-Design — interner Tool ohne Marke-Anspruch
- Keine Marketing-Pages — alles hinter Login

WAS DANACH KOMMT
Dein Output ist Input fuer:
- bmad-create-architecture (das Architektur-Doc reagiert auf deine
  UX-Anforderungen — globaler Drawer beeinflusst Layout-Shell, Cmd+K
  beeinflusst Such-API-Design im Backend, Inline-Edit beeinflusst
  PATCH-Endpoint-Granularitaet)
```

---

## BMAD-Reihenfolge fuer die SPA-Migration

Siehe naechste Sektion in dieser Datei oder die Antwort in der urspruenglichen
Conversation.
