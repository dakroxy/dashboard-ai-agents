# Dashboard KI-Agenten

Interne Plattform der DBS Home GmbH für KI-gestützte Verwaltungs-Workflows.

Erster Workflow: automatisierte Pflege von SEPA-Lastschriftmandaten aus eingescannten Dokumenten in die Impower-API.

## Lokales Setup

Secrets kommen aus 1Password (Vault `KI`). Ein Skript loest die Refs aus `.env.op`
in eine lokale `.env` auf:

```bash
# .env aus 1Password generieren (einmalig bzw. wenn .env.op sich aendert)
./scripts/env.sh

# Container bauen + starten
docker compose up --build
```

Voraussetzung: `op`-CLI installiert und der Service-Account-Token liegt in der
macOS-Keychain unter `op-service-account-ki`.

Ohne 1Password geht auch: `cp .env.example .env` und Werte von Hand eintragen.

Dashboard läuft dann unter http://localhost:8000
Health-Check: http://localhost:8000/health

## Status

**Phase: M3 — Code fertig, Impower-Schreibpfad noch nicht gegen Live-API verifiziert.**

- **M0** — Grundgeruest ✓
- **M1** — Google OAuth + PDF-Upload + Claude-Extraktion + Chat + Workflow-Einstellungen ✓
- **M2** — Impower-Matching (Property + Contact, Read-Pfad) ✓
- **M3** — Freigabe-Flow + Impower-Schreibpfad (Bank-Account, Mandat, Vertragsverknuepfung) — Code fertig, Live-Verifikation offen
- **M4** — Elestio-Deployment unter https://dashboard.dbshome.de — offen

## Tests

Tests laufen mit einer SQLite-In-Memory-DB — kein echtes Postgres notwendig:

```bash
pip install -e ".[dev]"
pytest
```

## Deploy (Elestio)

Produktiv-Deployment laeuft via Git-Push auf `main` gegen Elestio.
Compose-Datei fuer Prod: `docker-compose.prod.yml` (kein Code-Mount,
Postgres nur intern, Healthchecks, Uvicorn mit `--proxy-headers`).

### Erst-Setup (einmalig)

1. **Elestio-Projekt anlegen** — Service-Typ: *Docker Compose*, Compose-File
   `docker-compose.prod.yml` auswaehlen, Git-Repo
   `git@github.com:dakroxy/dashboard-ai-agents.git` einhaengen, Branch `main`,
   Auto-Deploy aktivieren.
2. **Env-Variablen im Elestio-Dashboard setzen** — siehe
   `.env.production.example` fuer die vollstaendige Liste.
   `SECRET_KEY` + `POSTGRES_PASSWORD` frisch generieren, NICHT die Dev-Werte.
3. **DNS bei All-Inkl** — `dashboard.dbshome.de` A-Record auf die Elestio-IP
   zeigen lassen. TLS uebernimmt Elestio per Let's Encrypt automatisch.
4. **Google OAuth Redirect-URI** — in der Google Cloud Console
   (*APIs & Services → Credentials → OAuth 2.0 Client*) zusaetzlich zur
   Dev-URL die Prod-URL `https://dashboard.dbshome.de/auth/google/callback`
   eintragen.

### Laufender Betrieb

- `git push origin main` → Elestio baut das Image neu + macht `alembic upgrade head` beim Start.
- Health: `GET /health` — von Compose + Elestio alle 30 s geprueft.
- Logs: Elestio-UI oder `docker compose logs -f app` per SSH.
- Backup: Postgres-Volume `postgres_data` + Uploads-Volume `uploads` via
  Elestio-Backup aktivieren.

## Lizenz / intern

Intern bei DBS Home. Nicht zur Weitergabe bestimmt.
