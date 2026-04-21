# Dashboard KI-Agenten — Projekt-Uebersicht

**Projekt**: Dashboard KI-Agenten — interne Plattform der DBS Home GmbH fuer KI-gestuetzte Verwaltungs-Workflows.
**Ziel-URL**: `https://dashboard.dbshome.de` (Elestio; DNS + TLS noch nicht geschaltet, M4).
**Stand**: 2026-04-21.
**Owner**: Daniel Kroll · `kroll@dbshome.de`.

## Was die Plattform tut

Zentrale Web-App, auf der Mitarbeitende PDFs hochladen. KI-Agenten extrahieren strukturierte Daten, matchen sie gegen die Impower-Hausverwaltungs-API und schreiben nach Human-in-the-Loop-Freigabe zurueck. Chat pro Dokument/Fall erlaubt Korrekturen in natuerlicher Sprache.

Zwei produktive Workflows + ein Sub-Workflow:

| Workflow | Zweck | Stand |
|---|---|---|
| `sepa_mandate` | Single-PDF: SEPA-Lastschriftmandat → Bank-Account sichern → Mandat anlegen → Unit-Contract-Mandate verknuepfen. Ersetzt manuelles Abtippen und Freigabe-Mails. | M3 Code fertig. Idempotenz-Zweig live OK (Floegel HAM61 → `already_present`). Neuanlage-Zweig noch live zu verifizieren. |
| `mietverwaltung_setup` | Multi-PDF-„Fall": Verwaltervertrag + Grundbuch + Mieterliste + n Mietvertraege → konsolidierter State → 8-stufiger Impower-Write (Contacts → Property → Contracts → Units → Exchange-Plan → Deposit). | M5 Code komplett (Pakete 1–8). Live-Tests offen. |
| `contact_create` | Sub-Workflow: Impower-Contact anlegen mit Duplicate-Check. Aus Mietverwaltungs-Fall (Eigentuemer) oder standalone aufrufbar. | Fertig, in Produktion einsetzbar. |

## Tech-Stack (Top-Level)

| Schicht | Wahl | Begruendung |
|---|---|---|
| Backend | FastAPI 0.115 + Uvicorn, Python 3.12 | Typed, asynchron, kompakt. Gute BackgroundTask-Integration fuer lange Impower-Calls. |
| DB | Postgres 16 (Docker lokal; Elestio Managed geplant) | JSONB fuer `documents.matching_result`, `documents.impower_result`, `cases.state`, `cases.impower_result`, `audit_log.details_json`. |
| ORM | SQLAlchemy 2.0 (typed `Mapped[...]`) + Alembic | Vollstaendig getyped; Migrations per Datei. |
| Frontend | Jinja2 + HTMX 2 + Tailwind via CDN | Kein npm-Stack, alle Interaktionen server-side (HTMX-Swap/OOB). Dev-Velocity ueber SPA-Komfort. |
| Auth | Google Workspace OAuth (Authlib + Starlette SessionMiddleware) | `@dbshome.de`-Gate via `hd`-Claim. Session-Cookie itsdangerous-signiert. |
| LLM | Anthropic SDK, Claude Opus 4.7 (Extract) + Sonnet 4.6 (Chat), Modell pro Workflow in DB umschaltbar. | Multimodal PDF-Call, Prompt-Caching auf System-Block. Chat-Flow bewusst separat konfigurierbar (Haiku scheitert empirisch an IBAN-Ziffern-Reproduktion). |
| IBAN/BIC | `schwifty` (Bundesbank-BLZ-Register) | BIC aus IBAN ableiten weil moderne SEPA-Mandate oft keinen BIC mehr drucken; plus IBAN-Validierung mit Unicode-NFKC-Normalize (LLMs schmuggeln Zero-Width-Spaces). |
| Deployment | Docker Compose; Prod via GHCR + Elestio Auto-Deploy bei `push:main`. | CI-Flow siehe `.github/workflows/docker-build.yml` + `docker-compose.prod.yml`. |
| Secret-Management | 1Password (Dev) + Elestio-Env (Prod) | `.env.op`-Refs committed, Klartext-`.env` gitignored. |

## Architektur-Prinzip

```
Dashboard (Jinja2 + HTMX)
  └─ Platform-Core: Auth · Rollen/Permissions · Audit · Files · Workflows (DB-editierbar)
        ├─ Claude-Client         (PDF-Extraktion, Chat-Agent — service.claude + service.mietverwaltung)
        └─ Impower-Connector     (Read + Write, Rate-Limit, Retry — service.impower + service.mietverwaltung_write)
               │
               ├─ Modul 1: SEPA-Lastschrift-Agent            (Single-Doc-Workflow, M1–M3)
               ├─ Modul 2: Mietverwaltungs-Anlage            (Multi-Doc-„Case", M5)
               └─ Sub-Workflow: Contact-Create               (zwei-Phasen: Duplicate-Check + Confirm)
```

Module teilen sich den Core. Neue Workflows docken via neuem `Workflow`-Eintrag (Seed in `main.py:_DEFAULT_WORKFLOWS`) + Router + optional neuem Service an.

## Ausfuehrungs-Modell

- **Short-Request**: HTTP-Handler → DB-Lookup → Template-Render. Alle UI-Routen sind so.
- **Long-Running**: PDF-Extraktion (Claude 20–60 s), Impower-Write (30–120 s) laufen als FastAPI-`BackgroundTask`. UI pollt Status via HTMX (`hx-trigger="every 2s"` oder Meta-Refresh alle 6 s fuer Case-Write).
- **Eigene DB-Session pro BackgroundTask**: keine Session-Wiederverwendung aus dem Request-Scope (siehe `_run_extraction`, `_run_case_extraction`, `run_mietverwaltung_write`).

## Pfade, die jeder AI-Assistent zuerst lesen sollte

- [`architecture.md`](./architecture.md) — ausfuehrliche Komponenten + Flows.
- [`api-contracts.md`](./api-contracts.md) — alle HTTP-Routen in Tabellenform.
- [`data-models.md`](./data-models.md) — Schema + Status-Lifecycle + JSONB-Payload-Struktur.
- [`development-guide.md`](./development-guide.md) — lokales Setup, Tests, Migrations.
- [`deployment-guide.md`](./deployment-guide.md) — GHCR + Elestio.
- [`../CLAUDE.md`](../CLAUDE.md) — komplettes Handover inkl. historischem Kontext und offenen Punkten (~1200 Zeilen).

## Offene Punkte (Stand 2026-04-21)

1. **M5 Paket 7 Live-Test** (Mietverwaltung-Impower-Write). Besonders beobachten: Exchange-Plan-Granularitaet (`templateExchanges[]` mit COLD_RENT/OPERATING_COSTS/HEATING_COSTS).
2. **M3 Neuanlage-Zweig** live verifizieren (Tilker GVE1 oder Kulessa BRE11).
3. M4: Elestio-Projekt anlegen, DNS bei All-Inkl auf Elestio-IP, Google-OAuth-Redirect fuer Prod-Domain registrieren.
4. IBAN-Wechsel-Szenario (deactivate altes Mandat → neues Mandat → Unit-Contract-Mandate umhaengen) — noch nicht implementiert, aber haeufigster Real-Case.

Vollstaendige Liste: siehe [`../CLAUDE.md`](../CLAUDE.md).
