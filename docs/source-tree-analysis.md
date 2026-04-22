# Source-Tree-Analyse

**Stand**: 2026-04-21 · Exhaustive Scan

Monolith, Python-3.12-Backend mit Jinja2-Templates und HTMX. Single cohesive Part, `project_type_id = backend` aber mit server-gerendertem Frontend. Git-Repo initialisiert (`main`-Branch), GHCR-Deploy-Pipeline live.

## Top-Level

```
Dashboard KI-Agenten/
├── .env.example               # Template fuer lokale Entwicklung (keine echten Secrets)
├── .env.op                    # 1Password-Refs, committed — wird durch scripts/env.sh in .env aufgeloest
├── .env.production.example    # Vollstaendige Liste der Elestio-Env-Variablen
├── .github/
│   └── workflows/
│       └── docker-build.yml   # GHCR-Build auf push:main -> ghcr.io/dakroxy/dashboard-ai-agents
├── .gitignore · .dockerignore
├── CLAUDE.md                  # Projekt-Handover (Kontext fuer Claude Code; 1200+ Zeilen)
├── Dockerfile                 # python:3.12-slim, alembic upgrade head, uvicorn --proxy-headers
├── README.md                  # Setup + Deploy-Flow
├── alembic.ini                # script_location=migrations; DB-URL kommt aus app.config
├── docker-compose.yml         # Dev-Stack (app + postgres:16-alpine, Volumes uploads+postgres_data)
├── docker-compose.prod.yml    # Elestio-Stack (pull aus GHCR, keine lokalen Volumes ausser persistent)
├── pyproject.toml             # FastAPI 0.115 / SQLAlchemy 2.0 / Anthropic / Authlib / schwifty / httpx
├── app/                       # Applikations-Code (siehe unten)
├── migrations/                # Alembic-Migrations (0001..0009)
├── mockups/                   # Standalone-HTML-Prototypen (z.B. mietverwaltung_setup.html)
├── scripts/
│   └── env.sh                 # op inject -i .env.op -o .env (1Password -> .env)
├── tests/                     # Pytest (SQLite-in-Memory; 62 Tests)
├── docs/                      # (diese Doku)
├── _bmad/                     # BMad-Skills/Config (nicht Teil der App)
└── .claude/                   # Claude-Code-Skills (nicht Teil der App)
```

## `app/` — FastAPI-Applikation

```
app/
├── __init__.py
├── main.py                    # FastAPI-App-Factory + Lifespan-Seeding (3 Workflows, 2 Rollen, Workflow-Access)
├── config.py                  # pydantic-settings Settings — liest .env, exposed global `settings`
├── db.py                      # SQLAlchemy-Engine + SessionLocal + Base + get_db()-Dependency
├── auth.py                    # Authlib-OAuth-Client (Google) + get_current_user / get_optional_user
├── permissions.py             # Permission-Registry, Role/ResourceAccess-Resolver, FastAPI-Dependencies
├── templating.py              # Jinja2Templates-Singleton + Globals (has_permission, field_source, provenance_pill) + iban_format-Filter
│
├── models/                    # SQLAlchemy-ORM-Modelle
│   ├── __init__.py            # Re-exports: User, Role, ResourceAccess, Document, Extraction,
│   │                          #             ChatMessage, Workflow, AuditLog, Case
│   ├── user.py                # google_sub, email, role_id FK, permissions_extra/denied, disabled_at
│   ├── role.py                # key, name, permissions[], is_system_role
│   ├── resource_access.py     # Rolle ODER User -> (resource_type, resource_id, allow|deny)
│   ├── document.py            # PDF-Meta, status-Lifecycle, matching_result/impower_result JSONB, case_id FK
│   ├── extraction.py          # Pro Document n Extractions (Claude-Output)
│   ├── chat_message.py        # document_id ODER case_id (Constraint im Code, genau eines)
│   ├── workflow.py            # key, name, model, chat_model, system_prompt, learning_notes, active
│   ├── audit_log.py           # user/action/entity_type/entity_id/details_json/ip_address
│   └── case.py                # Multi-Doc-Fall (Mietverwaltung): state JSONB + impower_result JSONB
│
├── routers/                   # FastAPI-Router, per Kompetenz-Domain gesplittet
│   ├── auth.py                # /auth/google/login, /callback, /logout (Google Workspace OAuth, @dbshome.de-Gate)
│   ├── documents.py           # SEPA-Single-Doc-Flow: Upload -> Extract -> Match -> Approve -> Write -> Chat
│   ├── cases.py               # Mietverwaltungs-Case: Multi-Doc-Upload, State-Edit-Routes, Write, Case-Chat
│   ├── contacts.py            # Kontakt-Anlage-Sub-Workflow (2-Phasen: Duplicate-Check + Confirm)
│   ├── objects.py             # Steckbrief: GET /objects (Liste) + GET /objects/{id} (Detail Cluster 1, read-only)
│   ├── workflows.py           # GET/POST /workflows/{key} — Prompt/Modell/Notes editierbar
│   ├── impower.py             # Debug-Endpoints (/impower/health, /properties, /contracts, /match)
│   └── admin.py               # /admin/* — User, Rollen, Workflow-Access, Audit-Log
│
├── services/                  # Geschaefts-Logik und externe Integrationen
│   ├── audit.py               # audit(db, user, action, ...) — zentraler Helper fuer AuditLog-Eintraege
│   ├── claude.py              # SEPA-Extract + SEPA-Chat (Claude-API, IBAN-Guard + schwifty, Prompt-Caching)
│   ├── mietverwaltung.py      # Classify + Extract per Doc-Typ, merge_case_state, Case-Chat mit Delta-Patch
│   ├── mietverwaltung_write.py# 8-Schritte-Write-Flow (Contacts -> Property -> Contract -> Units -> ...)
│   ├── steckbrief.py          # Read-only-Queries fuer Objekt-Liste + Detail (LEFT-JOIN unit_counts, get_provenance_map)
│   ├── steckbrief_write_gate.py # Zentrales Write-Gate fuer CD1-Entitaeten (Provenance + Audit + Mirror-Guard)
│   ├── steckbrief_impower_mirror.py # Nightly-Mirror Cluster 1+6 aus Impower (Story 1.4)
│   ├── _sync_common.py        # Generischer Sync-Job-Wrapper (Lock, Audit, per-Item-Session, Fehler-Isolation)
│   └── impower.py             # Impower-Client (httpx): Read-Pfad Matching, Write-Pfad SEPA-Mandat,
│                              # Rate-Limiting, 5xx-Retry, Schwifty-BIC-Derivation, _build_contact_payload
│
├── static/                    # (.gitkeep)
│
└── templates/                 # Jinja2 + HTMX (Tailwind via CDN)
    ├── base.html              # Sidebar-Layout (Dashboard/Workflows/Admin + User-Block unten)
    ├── index.html             # Dashboard mit Workflow-Kacheln (hardcoded Gradients pro wf.key)
    ├── documents_list.html    # SEPA-Doc-Liste + Upload
    ├── document_detail.html   # SEPA-Detail: PDF-iframe links, Extraktion + Chat rechts
    ├── _extraction_block.html # HTMX-Polling-Fragment fuer SEPA-Extract-Status
    ├── _chat_block.html       # SEPA-Chat-Historie + Form
    ├── _chat_response.html    # SEPA-Chat-Antwort-Fragment (+ OOB-Swap der Extraktion)
    ├── cases_list.html        # Mietverwaltungs-Faelle-Liste + „Neuer Fall"
    ├── case_detail.html       # Mietverwaltungs-Case: Form-UI (7 Sektionen), Status-Pills, Write-Button
    ├── _case_chat_panel.html  # Case-Chat-Drawer (fixed unten rechts)
    ├── contact_create.html    # Kontakt-Anlage-Form + Duplicate-Check-Warnung
    ├── workflows_list.html    # Workflow-Uebersicht (3 Eintraege: sepa_mandate, mietverwaltung_setup, contact_create)
    ├── workflow_edit.html     # Workflow-Konfig-Formular (Prompt + Modell + Lernnotizen)
    ├── objects_list.html      # Steckbrief-Liste: Tabelle mit short_code/name/Adresse/Anzahl-Einheiten (Story 1.3)
    ├── object_detail.html     # Steckbrief-Detail: Container-Template, include `_obj_stammdaten.html` (Story 1.3)
    ├── _obj_stammdaten.html   # Stammdaten-Sektion + Eigentuemerliste + Stale-Banner + Provenance-Pills
    ├── _obj_table_body.html   # Tabellenkoerper der Objekt-Liste (eigenes Fragment fuer spaetere HTMX-Swaps)
    ├── _macros.html           # status_pill() Jinja-Macro
    └── admin/
        ├── home.html
        ├── users_list.html · user_edit.html
        ├── roles_list.html · role_edit.html
        ├── logs.html
        └── sync_status.html   # Sync-Status-Dashboard + Manual-Trigger (Story 1.4)
```

### Entry-Points

- **HTTP-App-Start**: `app/main.py:app` (FastAPI-Instanz). Uvicorn in `Dockerfile` CMD:
  `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*`.
- **Lifespan-Seeding**: `app/main.py:lifespan` ruft beim App-Start nacheinander `_seed_default_workflow` (3 Workflows), `_seed_default_roles` (admin/user), `_seed_default_workflow_access` (Role-Defaults allow fuer alle Default-Workflows).
- **Health**: `GET /health` — liest `settings.app_env`, gibt `{"status": "ok", "env": "..."}` zurueck.
- **Root**: `GET /` — gerendertes Dashboard. Ohne Login Landing-Page, sonst Workflow-Kacheln (gefiltert per `accessible_workflow_ids`).

### Integration Points (extern)

- **Anthropic API** (`app/services/claude.py`, `app/services/mietverwaltung.py`): Multimodal PDF + JSON-Response. Default Opus 4.7 fuer Extract, Sonnet 4.6 fuer Chat. Prompt-Caching auf System-Block. Modell + Prompt pro Workflow in der DB editierbar.
- **Impower API** (`app/services/impower.py`, `app/services/mietverwaltung_write.py`): 2 Swagger-Spec-Bereiche — `/v2/api-docs` (Read) und `/services/pmp-accounting/v2/api-docs` (Write). Rate-Limit 500/min → 120ms Abstand. 120s Timeout + 5xx-Exponential-Backoff bis 60s.
- **Google Workspace OAuth** (`app/auth.py`): `@dbshome.de` hard-gated via `hd`-Claim im ID-Token.
- **1Password** (`scripts/env.sh`): Dev-Secrets via `op inject -i .env.op -o .env`. Prod-Secrets via Elestio-UI.
- **GHCR + Elestio** (CI `.github/workflows/docker-build.yml`): Push auf `main` → Image-Build → GHCR → Elestio zieht `:latest`.

### Kritische Verzeichnisse

| Pfad | Zweck |
|---|---|
| `app/routers/cases.py` (1700 Zeilen) | Groesste Datei — komplette Mietverwaltungs-State-Edit-API (13 Save-Routen, Chat, Write-Trigger). |
| `app/services/mietverwaltung.py` (1375 Zeilen) | Classify + 5 typ-spezifische Prompts/Schemas, `merge_case_state` + `field_source`, Case-Chat mit Delta-Patch. |
| `app/services/impower.py` (928 Zeilen) | Read + Write + Fuzzy-Matching + BIC-Derivation + Contact-Anlage. |
| `app/services/mietverwaltung_write.py` (780 Zeilen) | 8-Schritte-Orchestrator, Idempotenz via `case.impower_result`. |
| `app/templates/case_detail.html` (1019 Zeilen) | Form-UI mit 7 Sektionen, Status-Pills pro Feld, Write-Status-Block. |
| `migrations/versions/` | 9 Revisions, linear (0001 → 0009). |
