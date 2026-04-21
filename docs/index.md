# Dashboard KI-Agenten — Dokumentation

**Projekt**: DBS Home Dashboard KI-Agenten — interne Plattform fuer KI-gestuetzte Verwaltungs-Workflows.
**Stand**: 2026-04-21 · Exhaustive Scan
**Generiert von**: `bmad-document-project`-Workflow.

## Projekt-Uebersicht

- **Typ**: Monolith · Backend (FastAPI + Python 3.12) mit server-gerenderten Templates (Jinja2 + HTMX)
- **Primaere Sprache**: Python 3.12
- **Architektur-Pattern**: Layered + Service-oriented
- **Repository**: `git@github.com:dakroxy/dashboard-ai-agents.git`
- **Ziel-URL (Prod)**: `https://dashboard.dbshome.de` (Elestio, DNS noch offen)

## Quick Reference

| | |
|---|---|
| **Tech-Stack** | FastAPI 0.115 · SQLAlchemy 2.0 · Postgres 16 · Jinja2 + HTMX · Tailwind (CDN) · Anthropic SDK · Authlib · schwifty |
| **Entry-Point** | `app/main.py:app` (uvicorn), gestartet via `Dockerfile` CMD: `alembic upgrade head && uvicorn app.main:app ...` |
| **Auth** | Google Workspace OAuth (`@dbshome.de`-Gate) via Authlib + Starlette SessionMiddleware |
| **Permissions** | Flache Permission-Keys (`documents:upload`, `workflows:edit`, …) + ResourceAccess (Workflow-Sichtbarkeit) |
| **Dependencies** | `pyproject.toml` · Python 3.12-only |
| **Migrations** | Alembic `migrations/versions/0001..0009` (linear) |
| **Tests** | `pytest` · SQLite-in-Memory · 62 Tests |
| **Deploy** | GitHub Action → GHCR → Elestio (Custom Compose) |

## Generierte Dokumentation

- [Projekt-Uebersicht](./project-overview.md) — Management-Summary, Workflows, Tech-Stack, offene Punkte
- [Architektur](./architecture.md) — Layer, Module, Flows (SEPA + Mietverwaltung + Contact-Create), Claude-Integration, Impower-Client-Haertungen
- [Source-Tree](./source-tree-analysis.md) — annotierter Verzeichnis-Baum, Entry-Points, Integration-Points
- [API-Contracts](./api-contracts.md) — alle HTTP-Routen (Auth, Documents, Cases, Contacts, Workflows, Impower, Admin)
- [Data-Models](./data-models.md) — Postgres-Schema, Beziehungen, Status-Lifecycle, `case.state`-Struktur, Migrations-Historie
- [Component-Inventar](./component-inventory.md) — Templates (+ HTMX-Fragmente), Router, Services, Erweiterungs-Leitfaden
- [Development-Guide](./development-guide.md) — Setup, Commands, Tests, Konventionen, Debugging
- [Deployment-Guide](./deployment-guide.md) — GHCR + Elestio, Env-Variablen, Rollback, Backups

## Bestehende Quellen (nicht durch diesen Scan generiert)

- [`CLAUDE.md`](../CLAUDE.md) — komplettes Projekt-Handover, ~1200 Zeilen. **Pflicht-Lektuere fuer AI-Assistenten**. Enthaelt historischen Kontext, Session-Logs, Meilenstein-Status, offene Architektur-Entscheidungen.
- [`README.md`](../README.md) — Kurzanleitung Setup + Deploy.
- [`.env.example`](../.env.example) — Dev-Env-Template.
- [`.env.production.example`](../.env.production.example) — Prod-Env-Template fuer Elestio.
- `mockups/mietverwaltung_setup.html` — standalone HTML-Prototyp der Mietverwaltungs-Eingabemaske.
- `~/.claude/projects/-Users-daniel-Desktop-Vibe-Coding-Dashboard-KI-Agenten/memory/` — persistente Memory-Notizen (inkl. Impower-API-Referenzen, Claude-API-Quirks, Secret-Management, Feedback-Rules).

## Getting Started

Fuer neue Mitwirkende:

1. [`development-guide.md`](./development-guide.md) durchlesen → `scripts/env.sh` oder `.env.example` → `docker compose up --build`
2. [`project-overview.md`](./project-overview.md) fuer das fachliche Big-Picture
3. [`architecture.md`](./architecture.md) fuer die Modul-Flows (SEPA, Mietverwaltung, Contact-Create)

Fuer Brownfield-PRD oder Stories (BMad-Flow):

- Diese `docs/`-Sammlung als Kontext-Quelle verwenden.
- [`CLAUDE.md`](../CLAUDE.md) zusaetzlich als Baseline reingeben — die historischen Entscheidungen und Live-Teststand-Notizen stehen dort.

## Offene Punkte (Stand 2026-04-21)

1. **M5 Paket 7 Live-Test** — Fall mit Verwaltervertrag + Grundbuch + Mieterliste + ≥1 Mietvertrag komplett durchspielen. Beobachten: Exchange-Plan-Granularitaet.
2. **M3 Neuanlage-Zweig** live verifizieren (Tilker GVE1 oder Kulessa BRE11).
3. **M4 Elestio-Deployment** — Projekt anlegen, DNS + TLS schalten, Google-OAuth-Redirect-URI fuer Prod registrieren.
4. **IBAN-Wechsel-Szenario** — haeufigster Real-Case (Eigentuemer wechselt Bank). Noch nicht implementiert: deactivate altes Mandat → neues Mandat → Unit-Contract-Mandate umhaengen.

Vollstaendige Liste in [`../CLAUDE.md`](../CLAUDE.md) unter „Backlog" und „Offene Punkte".
