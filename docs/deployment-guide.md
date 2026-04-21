# Deployment-Guide

**Flow**: GitHub Actions baut das App-Image bei jedem Push auf `main` und pusht nach GHCR. Elestio zieht das Image und faehrt den Stack via `docker-compose.prod.yml`.

**Stand**: CI eingerichtet, Elestio-Projekt noch nicht angelegt (M4).

## Infrastruktur-Ueberblick

```
Entwickler
   │ git push origin main
   ▼
GitHub (Repo: dakroxy/dashboard-ai-agents)
   │
   └─► .github/workflows/docker-build.yml
         │ docker buildx + docker/login (GITHUB_TOKEN, scope: packages:write)
         │ docker/metadata + build-push
         ▼
   GHCR: ghcr.io/dakroxy/dashboard-ai-agents
         :latest   (push auf main)
         :sha-<7>  (pro Commit)
   │
   ▼
Elestio "Custom Docker Compose"
   │ Private Registry: ghcr.io (User = GitHub-Handle, PAT mit read:packages)
   │ Compose: docker-compose.prod.yml
   │ Env-Variablen aus dem Elestio-Dashboard
   ▼
App-Container (Python 3.12)
   │ alembic upgrade head  (beim Start, aus Dockerfile CMD)
   │ uvicorn app.main:app --proxy-headers --forwarded-allow-ips=*
   │ Port 8000 → Elestio-Proxy
   ▼
Elestio Reverse-Proxy (TLS per Let's Encrypt)
   │
   ▼
dashboard.dbshome.de  (DNS A-Record bei All-Inkl auf Elestio-IP)
```

## CI-Pipeline

Datei: `.github/workflows/docker-build.yml`.

- **Trigger**: `push` auf `main` oder `workflow_dispatch` (manuell).
- **Permissions**: `contents: read`, `packages: write` (nutzt `GITHUB_TOKEN` automatisch — keine Manual-Secrets).
- **Schritte**: Checkout → Buildx → GHCR-Login → metadata-action → build-push mit Cache (`type=gha`).
- **Tags**: `latest` (bei Main-Branch) + `sha-<short>`.
- **Image-Registry**: `ghcr.io/dakroxy/dashboard-ai-agents`. Aktuell privat → Elestio braucht einen PAT fuer den Pull.

## Erst-Setup Elestio (einmalig, noch offen)

1. **GitHub-Action aktivieren**: laeuft automatisch bei Push auf `main`. Keine manuelle Secret-Konfiguration noetig.
2. **GHCR-PAT fuer Elestio**: GitHub → Settings → Developer settings → Personal access tokens (classic) → neuen Token mit Scope `read:packages`. Wenn das Package `dashboard-ai-agents` privat bleibt, braucht Elestio diesen Token fuer den Pull.
3. **Elestio-Service anlegen**:
   - Service-Typ: **Custom Docker Compose**.
   - Compose-Inhalt: `docker-compose.prod.yml` aus dem Repo.
   - **Private Docker Registry** eintragen: `ghcr.io`, Username = GitHub-Handle, Password = PAT aus Schritt 2.
4. **Env-Variablen**: siehe `.env.production.example`. Mindestens:

   | Variable | Wert |
   |---|---|
   | `APP_ENV` | `production` |
   | `BASE_URL` | `https://dashboard.dbshome.de` |
   | `SECRET_KEY` | **Frisch** generieren (32 Byte hex), nicht Dev-Wert. |
   | `POSTGRES_HOST` | `db` (Compose-Service-Name) |
   | `POSTGRES_PORT` | `5432` |
   | `POSTGRES_USER` | `dashboard` |
   | `POSTGRES_PASSWORD` | **Frisch** generieren, nicht Dev-Wert. |
   | `POSTGRES_DB` | `dashboard` |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | aus Google Cloud Console (OAuth 2.0 Client). |
   | `GOOGLE_HOSTED_DOMAIN` | `dbshome.de` |
   | `ANTHROPIC_API_KEY` | aus 1Password Vault `KI`. |
   | `IMPOWER_BASE_URL` | `https://api.app.impower.de` |
   | `IMPOWER_BEARER_TOKEN` | aus 1Password Vault `KI`. |
   | `INITIAL_ADMIN_EMAILS` | `kroll@dbshome.de` (komma-separiert fuer mehr User). |

5. **Reverse-Proxy**: Elestio-Proxy auf Container-Port 8000 mappen.
6. **DNS bei All-Inkl**: `dashboard.dbshome.de` A-Record auf die Elestio-IP. TLS uebernimmt Elestio (Let's Encrypt).
7. **Google-OAuth-Redirect-URI**: In Google Cloud Console als zusaetzliche Redirect-URI eintragen:

   ```
   https://dashboard.dbshome.de/auth/google/callback
   ```

## Laufender Betrieb

- **Deploy**: `git push origin main` → CI baut + pusht → Elestio pullt neues `:latest`. `alembic upgrade head` laeuft beim Container-Start. Auto-Deploy vs. manueller Redeploy-Button haengt von der Elestio-Konfiguration ab (Watchtower-artiges Polling moeglich).
- **Health-Monitoring**: Compose-Healthcheck `GET /health` alle 30 s. Elestio zeigt unhealthy Container im Dashboard an.
- **Logs**: Elestio-UI oder `docker compose logs -f app` per SSH.
- **Audit-Log**: in der App selbst unter `/admin/logs` einsehbar; wird bei Bedarf ueber `/admin/logs/{id}/delete` geloescht.
- **Backups**:
  - `postgres_data`-Volume (DB) → Elestio-Backup aktivieren.
  - `uploads`-Volume (PDFs) → Elestio-Backup.
  - **Wichtig**: PDFs werden als `{sha256}.pdf` abgelegt (`settings.uploads_dir`). Dedup auf Hash-Basis — derselbe Upload zweimal verursacht keine zusaetzlichen Writes, aber das Doc-Entry wird neu angelegt.

## Rollbacks

- Per GHCR-Tag: Elestio auf `ghcr.io/dakroxy/dashboard-ai-agents:sha-<previous>` umstellen (statt `:latest`).
- DB-Downgrade: `docker compose exec app alembic downgrade -1` — **NUR** wenn die Downgrade-Funktion in der Migration sauber ist; bei destructiven Aenderungen (DROP COLUMN) riskant.
- Volume-Restore: Elestio-Backup einspielen.

## Security-Notes

- `https_only=settings.app_env != "development"` — Session-Cookie nur ueber HTTPS gesendet in Prod.
- `X-Forwarded-For` wird im Audit-Log beachtet (`_client_ip` in `audit.py`).
- OAuth-Gate auf `hd=dbshome.de` + `email_verified=True` — Non-`@dbshome.de` kriegt 403.
- `SessionMiddleware` nutzt `itsdangerous` mit `settings.secret_key`. Rotation → alle Sessions invalid, User muessen neu einloggen.
- Impower-Bearer-Token und Anthropic-Key sind Langzeit-Secrets. Regelmaessig rotieren (manuell; keine automatische Rotation eingerichtet).

## Bekannte Grenzen

- **Impower-Sandbox**: existiert nicht. Write-Pfad testet gegen den Live-Tenant. Deshalb gibt es Idempotenz + Preflight + State-Machine mit Partial-Success.
- **GDPR / DSGVO**: PDFs enthalten Klarnamen + IBANs. AVV mit Anthropic ist laut Memory-Note geklaert (`project_anthropic_avv_cleared`). Vor Produktiv-Rollout trotzdem im Auge behalten — siehe Backlog-Punkt 3 in `CLAUDE.md`.
- **Monitoring**: kein Sentry, kein APM. Fuer M4+ ggf. Sentry oder den Elestio-eigenen Monitoring-Stack aktivieren.
