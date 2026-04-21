# Development-Guide

## Prerequisites

- macOS (User arbeitet auf Darwin 25.3.0) — Linux sollte analog funktionieren.
- **Python 3.12** (Zielversion, siehe `pyproject.toml:requires-python = ">=3.12"` und `Dockerfile`).
- **Docker + Docker Compose** (Dev-Stack laeuft containerisiert).
- **1Password-CLI (`op`)** + Service-Account-Token in macOS-Keychain unter `op-service-account-ki` — optional, alternativ Klartext-`.env`.

## Setup

### Option A: via 1Password (bevorzugt)

```bash
# .env aus 1Password bauen (einmalig, oder wenn .env.op sich aendert)
./scripts/env.sh

# Docker-Stack starten
docker compose up --build
```

`scripts/env.sh` macht `op inject -i .env.op -o .env`. Referenziert Vault `KI` in "DBS Home GmbH". Benoetigte Items:
- `Google OAuth - HV Dashboard AI Agents` (`username` = Client-ID, `credential` = Secret)
- `Claude API Key - Lastschrift` (`credential`)
- `Impower API Token PowerAutomate` (`credential`)

Dev-Werte (`SECRET_KEY`, `POSTGRES_PASSWORD`) stehen als Klartext in `.env.op` — das ist fuer Dev OK; Prod nutzt Elestio-Env-Variablen.

### Option B: ohne 1Password

```bash
cp .env.example .env
# Werte von Hand eintragen (Google Client ID/Secret, Anthropic-Key, Impower-Bearer)
docker compose up --build
```

### Laufende App

- Dashboard: http://localhost:8000
- Health: http://localhost:8000/health (liefert `{"status": "ok", "env": "development"}`)
- Postgres: localhost:5432 (aus dem Host erreichbar, siehe `docker-compose.yml`)

### Google-OAuth lokal

In der Google Cloud Console (APIs & Services → Credentials → OAuth 2.0 Client) als Redirect-URI eintragen:

```
http://localhost:8000/auth/google/callback
```

Hosted-Domain muss `dbshome.de` sein (Settings `google_hosted_domain`).

### Erster Login → Admin-Rolle

Trage deine E-Mail in `INITIAL_ADMIN_EMAILS` (komma-separiert) ein, dann beim ersten Login wird automatisch die Admin-Rolle vergeben. Spaetere Rollen-Wechsel laufen ueber `/admin/users/{id}`. Bestehende Admin-Zuweisungen werden nicht ueberschrieben.

## Projekt-Struktur

Siehe [`source-tree-analysis.md`](./source-tree-analysis.md).

## Wichtige Commands

### App

- **Container neu bauen**: `docker compose up --build`
- **Logs live**: `docker compose logs -f app`
- **In den Container**: `docker compose exec app bash`
- **DB-Shell**: `docker compose exec db psql -U dashboard -d dashboard`

### Migrations (Alembic)

Alembic ist in den App-Container eingebaut. Migrations werden **automatisch beim Container-Start** ausgefuehrt (`alembic upgrade head && uvicorn ...` in `Dockerfile` CMD).

Neue Migration generieren:

```bash
docker compose exec app alembic revision -m "kurzbeschreibung"
# → legt migrations/versions/<hash>_kurzbeschreibung.py an
```

**Wichtig**: Revisionen werden **nicht** autogeneriert aus dem ORM (kein `--autogenerate`). Schema-Aenderungen per Hand in den Migrations-Files formulieren, weil das ORM mit Postgres-spezifischen Typen (`JSONB`, `UUID`) arbeitet und Alembic-Autogenerate hier unzuverlaessig diffed.

Vor Anlage einer neuen Migration **immer `ls migrations/versions/`** laufen lassen und die neueste Revision als `down_revision` eintragen. Laut `feedback_migrations_check_existing`-Memory fuehrte das Blindvertrauen auf die CLAUDE.md-Liste einmal zu einem Alembic-Restart-Loop.

Upgrade manuell: `docker compose exec app alembic upgrade head`
Downgrade: `docker compose exec app alembic downgrade -1`

### Python-Deps

```bash
# Lokal ohne Docker (zB fuer Tests)
pip install -e ".[dev]"
```

### Tests

```bash
pip install -e ".[dev]"
pytest
```

Tests laufen mit **SQLite in-memory** (siehe `tests/conftest.py`): `SQLiteTypeCompiler` wird gemonkey-patched, damit JSONB als TEXT und UUID als CHAR(32) DDL-generiert werden. Kein echter Postgres noetig. Zentrale Fixtures legen User + Workflow + Session fuer jeden Test frisch an.

Anthropic- und Impower-HTTP-Clients werden in den Unit-Tests gemockt (`tests/test_claude_unit.py`, `tests/test_impower_unit.py`). Keine echten API-Calls.

Test-Verzeichnis:

- `test_claude_unit.py` — Extract/Chat-Logik, IBAN-Guard, Pydantic-Schemas.
- `test_impower_unit.py` — Matching + Write-Client-Helper.
- `test_routes_smoke.py` — Router-Smoke (302/403-Gates, Health 200).
- `test_upload.py` — Upload-Validierung (size, content-type, PDF-Header).

## Dev-Flow

- **BackgroundTasks**: Lange Calls (Claude, Impower) laufen als FastAPI-BackgroundTask mit eigener DB-Session (`_run_extraction`, `_run_case_extraction`, `run_mietverwaltung_write`). Nicht die Request-Session wiederverwenden.
- **Transaktions-Handling**: Audit-Logs werden ueber `audit()` in die Session geschrieben, Commit macht der Caller — damit Log + Geschaefts-Change in einer Transaktion landen.
- **HTMX**: UI-Updates werden server-side gerendert. Fragment-Templates beginnen mit Underscore (`_extraction_block.html`, `_case_chat_panel.html`). Siehe [`component-inventory.md`](./component-inventory.md).
- **JSONB-Writes**: SQLAlchemy erkennt JSONB-Mutations NICHT automatisch (kein deep-tracking). Nach einer Aenderung am JSONB-Dict entweder komplett reassigen (`case.state = new_state`) oder `flag_modified(case, "state")` nutzen. Siehe `cases.py:_mutate_overrides` — vollstaendige Reassignment-Variante.

## Konventionen

- **Sprache**: Deutsch im Chat mit dem User, im Code Kommentare deutsch/englisch konsistent pro Datei.
- **Emojis im Code**: keine, ausser auf Anfrage.
- **Feature-Flags / Backwards-Compat-Shims**: vermeiden. Lieber den Code direkt aendern.
- **Tests pro Feature**: wo sinnvoll, mindestens ein Unit-Test. Integrationstests gegen echte Impower-API existieren nicht (kein Sandbox-Tenant).
- **Prototypen-First**: bewusst uebersprungen. Direkt Produktivcode, Iteration ueber Chat.

## Debugging

- **OAuth-Fehler**: `GET /auth/google/login` → Redirect-URI in Google Cloud Console stimmen muss; Hosted-Domain muss `dbshome.de` sein.
- **Anthropic-Fehler**: `ANTHROPIC_API_KEY` nicht gesetzt → Extract/Chat geben sofort `failed`/`error` zurueck mit passender Message.
- **Impower-Timeout**: `_api_get/_post/_put` haben 120s Timeout + 5xx-Exponential-Backoff. 503 vom Gateway ist bekannt und transient; Retry laeuft automatisch bis 5× mit Delays 2/5/15/30/60s. HTML-Error-Pages werden im Response sanitized (siehe `_sanitize_error`).
- **Sentry / APM**: nicht verdrahtet. Logs stehen im Container-Log (`docker compose logs app`) und im Audit-Log (`/admin/logs`).

## Hinweise fuer Code-Aenderungen

1. Bei Aenderungen an `app/templating.py`-Globals muessen die Template-Caller neu gestartet werden (Dev-Server pickt es automatisch wenn Volume gemountet — `./app:/app/app` in `docker-compose.yml`).
2. Neue Jinja-Filter/Globals werden zentral in `app/templating.py` registriert, nicht im Router.
3. Neue Permission: zuerst in `app/permissions.py:PERMISSIONS` registrieren, dann in Default-Rollen ergaenzen, dann im Handler pruefen. Ohne Registrierung schlaegt die Admin-UI fehl (unknown Permission).
4. `messages.parse` vs `messages.create`: immer `messages.create` + manuelles Pydantic — `messages.parse` hat Grammar-Compilation-Timeouts bei Optional-lastigen Schemas mit PDF-Input (siehe `feedback_claude_api_pdf_extraction`-Memory).
