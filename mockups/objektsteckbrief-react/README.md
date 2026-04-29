# Objektsteckbrief — UX-Mockup (Variante B)

Self-contained React-Mockup der Objektsteckbrief-Detailseite (Beispielobjekt **HAM61** —
WEG Eppendorfer Landstraße 47–49, Hamburg). Konzipiert als **React-Insel** im FastAPI/Jinja-Backend.

## Designentscheidung

**Hanseatic Terminal** — bewusste Anti-SaaS-Aesthetik. Dunkles Bloomberg-Terminal-Gefuehl
mit hanseatischer Editorial-Typografie. Keine Pastell-Kacheln, keine generischen
Material-/SaaS-Patterns. Hoher Datendichte, scharfe Ecken, Tabular-Numerals,
Provenance-Glyphen pro Feld.

- **Display**: Fraunces (variable serif) — Hanseatic gravitas
- **UI**: IBM Plex Sans — technische Autoritaet
- **Daten**: IBM Plex Mono — Tabular-numerals fuer Geld, IDs, Datumsfelder
- **Akzent**: Saffron-Amber `#e3a860` — ruhig, signalisiert Aufmerksamkeit ohne aggressiv zu sein
- **Status**: gedaempfter Moos-Gruen / Dusty-Yellow / Terrakotta-Rot statt Knallfarben

## Was zu sehen ist

- Sticky-Header mit ID-Chips, Pflegegrad-Ring, Review-Queue-Counter, Vollansicht/Kompakt/Risiko-Fokus-Tabs
- Due-Radar-Banner direkt unter dem Header
- Sektions-Sidebar mit Sprungmarken + Provenance-Verteilungs-Bars
- Stammdaten · Einheiten · Personen · Technik · Finanzen · Versicherungen
- **Killer-Visual:** horizontale Bauakten-Timeline 1924–2026 (Cluster 4)
- **Killer-Visual:** Police-Tabelle mit Due-Highlighting + Wartungspflichten-Status (Cluster 8)
- Right-Drawer mit Review-Queue (KI-Vorschlaegen, Confidence-Bars, Annehmen/Ablehnen)

Alle Daten sind Mock-Daten in `src/data/mock.ts`.

## Lokal starten

```bash
cd mockups/objektsteckbrief-react
npm install
npm run dev
```

Default-Port: `http://localhost:5174`

Empfohlene Browser-Breite: **1440px+** (Desktop-First, der Use-Case ist Verwalter-Arbeitsplatz).

## Spaeter als Insel im Bestand

Wenn die Designrichtung gefaellt, lassen sich die Sub-Komponenten 1:1 als React-Insel
in eine bestehende FastAPI/Jinja-Page mounten:

```python
# in der Jinja-Template:
<div id="objektsteckbrief-island" data-object-id="{{ object.id }}"></div>
<script type="module" src="/static/js/objektsteckbrief.js"></script>
```

Daten kommen dann ueber FastAPI-JSON-Endpoints (statt Mock-Konstanten) — Pydantic-Schemas
bleiben unveraendert, lassen sich via `openapi-typescript` als TS-Types generieren.

## Struktur

```
src/
├── App.tsx                          Komposition + View-State
├── main.tsx                         React-Mount
├── index.css                        Design-Tokens + Grain-Overlay + Animationen
├── data/mock.ts                     HAM61-Realistische Mock-Daten
└── components/
    ├── ui.tsx                       Primitive: ProvenanceIcon, Pill, IdChip, Sparkline, Donut, ...
    ├── Header.tsx                   Sticky-Top mit Identitaet, Pflegegrad, Tabs
    ├── Sidebar.tsx                  Sprungmarken-Nav mit Provenance-Bars
    ├── DueRadarBanner.tsx           Querschnitts-Warnungen unter Header
    ├── StammdatenSection.tsx        Cluster 1
    ├── EinheitenPersonenSection.tsx Cluster 2 + 3 (kompakt)
    ├── FinanzenSection.tsx          Cluster 6
    ├── TechnikSection.tsx           Cluster 4 (mit Bauakten-Timeline)
    ├── HistorieTimeline.tsx         Killer-Visual: 1924-2026
    ├── VersicherungenSection.tsx    Cluster 8
    └── ReviewQueueDrawer.tsx        KI-Vorschlaege mit Confidence
```
