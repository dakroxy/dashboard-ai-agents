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

## Deploy (Elestio + GHCR)

Zweigeteilter Flow: GitHub Actions baut das App-Image bei jedem Push auf
`main` und pusht es nach `ghcr.io/dakroxy/dashboard-ai-agents:latest`.
Elestio zieht das Image von dort und faehrt den Stack via
`docker-compose.prod.yml` hoch (kein Code-Build auf Elestio — zieht nur
fertige Images, daher Registry-basierter Flow).

### Erst-Setup (einmalig)

1. **GitHub Action aktivieren** — `.github/workflows/docker-build.yml`
   laeuft automatisch bei Push auf `main`. Nutzt `GITHUB_TOKEN` mit
   `packages: write` (kein manueller Secret noetig). Ergebnis:
   `ghcr.io/dakroxy/dashboard-ai-agents:latest` +
   `ghcr.io/dakroxy/dashboard-ai-agents:sha-<shortsha>`.
2. **GHCR Personal Access Token fuer Elestio** — Classic-PAT mit Scope
   `read:packages` generieren (GitHub → Settings → Developer settings →
   Tokens). Elestio braucht das fuer den Image-Pull (sofern Package
   privat bleibt — bei `dashboard-ai-agents` der Fall).
3. **Elestio-Service anlegen** — Service-Typ *Custom Docker Compose*,
   Compose-Inhalt aus `docker-compose.prod.yml` einfuegen, unter
   *Private Docker Registry* GHCR eintragen (`ghcr.io`, Username =
   GitHub-Handle, Password = PAT aus Schritt 2).
4. **Env-Variablen im Elestio-Dashboard setzen** — siehe
   `.env.production.example` fuer die vollstaendige Liste.
   `SECRET_KEY` + `POSTGRES_PASSWORD` frisch generieren, NICHT die
   Dev-Werte.
5. **Reverse-Proxy** — Elestio-Proxy auf Container-Port 8000 mappen.
6. **DNS bei All-Inkl** — `dashboard.dbshome.de` A-Record auf die
   Elestio-IP zeigen lassen. TLS uebernimmt Elestio per Let's Encrypt
   automatisch.
7. **Google OAuth Redirect-URI** — in der Google Cloud Console
   (*APIs & Services → Credentials → OAuth 2.0 Client*) zusaetzlich zur
   Dev-URL die Prod-URL `https://dashboard.dbshome.de/auth/google/callback`
   eintragen.

### Laufender Betrieb

- `git push origin main` → Action baut + pusht Image → Elestio pullt
  neues `:latest` (entweder via Redeploy-Button oder Watchtower-artiges
  Auto-Update). `alembic upgrade head` laeuft beim Container-Start.
- Health: `GET /health` — von Compose + Elestio alle 30 s geprueft.
- Logs: Elestio-UI oder `docker compose logs -f app` per SSH.
- Backup: Postgres-Volume `postgres_data` + Uploads-Volume `uploads` via
  Elestio-Backup aktivieren.

## Lizenz / intern

Intern bei DBS Home. Nicht zur Weitergabe bestimmt.
