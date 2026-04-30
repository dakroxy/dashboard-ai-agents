---
project_name: 'Dashboard KI-Agenten'
user_name: 'Daniel Kroll'
date: '2026-04-21'
sections_completed:
  ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'quality_rules', 'workflow_rules', 'anti_patterns']
status: 'complete'
optimized_for_llm: true
---

# Project Context for AI Agents

_Kritische Regeln und Muster, die AI-Agenten beim Implementieren in diesem Projekt einhalten muessen. Fokus auf unauffaellige Details, die sonst uebersehen werden._

---

## Technology Stack & Versions

**Runtime**
- Python **3.12** (Pflicht — `pyproject.toml:requires-python = ">=3.12"`, gleiches Base-Image im `Dockerfile`).
- Postgres **16** (Dev via Docker, Prod Elestio Managed). Nutzt Postgres-spezifische Typen (`JSONB`, `UUID`) — deshalb laufen Tests mit SQLite nur ueber einen SQLiteTypeCompiler-Monkey-Patch (`tests/conftest.py`).

**Core-Backend**
- FastAPI **>=0.115** + Uvicorn **>=0.32** (`[standard]`-Extras).
- SQLAlchemy **2.0** mit typed `Mapped[...]`-Models. Alembic **>=1.14** (Migrations **nicht** per Autogenerate — Postgres-JSONB/UUID werden unzuverlaessig gediffed; Revisionen per Hand schreiben).
- `psycopg[binary] >=3.2` (nicht psycopg2).
- Pydantic-Settings **>=2.6** (`app/config.py`).

**Auth + Session**
- Authlib **>=1.3** fuer Google OAuth.
- Starlette `SessionMiddleware` + `itsdangerous >=2.2` fuer Cookie-Signierung.

**Frontend**
- Jinja2 **>=3.1** + HTMX 2 (via CDN) + Tailwind (via CDN). **Kein** npm/node-Stack, kein Build-Step. Fragmente werden server-side gerendert.
- `python-multipart >=0.0.17` fuer Form-Uploads.

**LLM + externe APIs**
- Anthropic SDK **>=0.40**. Default-Modelle pro Workflow editierbar in DB (`workflows.model`, `workflows.chat_model`). Aktuell: Opus 4.7 (`claude-opus-4-7`) fuer Extract, Sonnet 4.6 (`claude-sonnet-4-6`) fuer Chat. Haiku **nicht** fuer Chat (IBAN-Ziffern-Verluste).
- httpx **>=0.27** fuer Impower-Client.
- schwifty **>=2024.1** fuer IBAN-Validierung + BIC-Derivation aus Bundesbank-BLZ-Register.

**Dev-Dependencies**
- pytest **>=8.0** + pytest-asyncio **>=0.24** (`asyncio_mode = "auto"`).

**Deployment**
- Docker Compose (Dev: `docker-compose.yml`; Prod: `docker-compose.prod.yml` mit `alembic upgrade head && uvicorn ...` im CMD).
- GitHub Actions → GHCR (`ghcr.io/dakroxy/dashboard-ai-agents:latest`) → Elestio Auto-Deploy.
- Prod-Proxy-Headers: `uvicorn --proxy-headers --forwarded-allow-ips=*`.

**Version-Constraints, die Agents kennen muessen**
- Python-Version **nicht unter 3.12 setzen**. Wir nutzen moderne Typing-Features (PEP 604 Unions, typed `Mapped`).
- Anthropic SDK: **`messages.create` verwenden, nicht `messages.parse`**. Grammar-Compilation-Timeout bei Optional-lastigen Pydantic-Schemas mit PDF-Input (Memory: `feedback_claude_api_pdf_extraction`).
- SQLAlchemy 2.0-Syntax Pflicht (typed Mapped, `select()` statt `query()`), keine 1.x-Legacy.
- Alembic-Migrations: immer **manuell schreiben**, nie `--autogenerate`.

## Critical Implementation Rules

### Language-Specific Rules (Python 3.12)

**SQLAlchemy 2.0 Typed ORM**
- Modelle mit `Mapped[...]` + `mapped_column(...)`, nicht `Column(...)`-Legacy.
- Queries ueber `db.execute(select(Model).where(...))` + `.scalars().all()` / `.scalar_one_or_none()`. **Kein** `db.query(Model)`.
- JSONB-Spalten: **Deep-Tracking existiert nicht** — nach Mutation entweder komplett reassignen (`case.state = new_state`) oder `flag_modified(obj, "state")`. Muster in `cases.py:_mutate_overrides`.
- UUID-PKs: echte `uuid.UUID`, nie String.

**Pydantic v2**
- Schemas leben neben der Nutzung (`app/services/claude.py`, `app/services/mietverwaltung.py`). Pro Doc-Typ eigenes Schema.
- Validierung: `Model.model_validate(parsed_dict)` oder `Model(**dict)`, **nicht** `parse_obj`.
- Settings nur in `app/config.py` via `pydantic-settings` — nie via `os.getenv` an anderer Stelle.

**Typing**
- Moderne Unions: `str | None`, nicht `Optional[str]` (PEP 604).
- `list[T]`/`dict[K, V]` statt `List[T]`/`Dict[K, V]` (PEP 585).
- Return-Types an allen Service-Funktionen.

**Async/Sync**
- Router-Handler sind `async def`. BackgroundTasks duerfen sync sein (Threadpool).
- Impower-Client ist async (httpx `AsyncClient`). Im sync BackgroundTask via `asyncio.run(...)` aufrufen (siehe `run_mietverwaltung_write`).
- Anthropic-SDK-Calls sind sync — nicht mit async mischen.
- **Kein** `asyncio.run()` in einem Handler, der schon im Event-Loop laeuft — nur am BackgroundTask-Einstieg.

**Error-Handling**
- Eigene Exceptions aus Services (`ImpowerError`, `ClaudeError`), nicht generisches `Exception`.
- Router: `raise HTTPException(status_code=..., detail=...)`, nicht manuelle `JSONResponse` mit Fehlerstatus.
- BackgroundTasks: nie still ignorieren — loggen + Status + Audit.

**Imports**
- Absolute Imports (`from app.services.impower import ...`), nie relative.
- Reihenfolge stdlib → 3rd-party → `app.*`. Keine Zirkular-Imports (`app.templating` wird nicht aus Routern importiert).

**Unicode + Strings**
- LLM-Outputs vor Vergleich/Validierung normalisieren: `unicodedata.normalize("NFKC", s)` + `"".join(c for c in s if c.isalnum())`. Zero-Width-Spaces (U+200B) schlagen sonst still durch. Memory: `feedback_llm_iban_unicode_normalize`.

**Logging**
- Kein konfiguriertes `logging`-Setup; Ausgaben ueber `print(...)` ins Container-Log. Wichtige Events zusaetzlich via `audit()` ins `AuditLog`.

### Framework-Specific Rules (FastAPI + Jinja2 + HTMX)

**Schichten-Disziplin**
- `routers/` macht nur HTTP-I/O, Form-Parsing, Permission-Check, Template-Render. **Keine** Geschaefts-Logik.
- `services/` kennt **keine** HTTP-Objekte (kein `Request`, keine `Form(...)`). Input sind reine Daten/ORM-Objekte.
- `models/` ist reiner Daten-Layer (SQLAlchemy-Models).
- Cross-Cutting (`auth.py`, `permissions.py`, `templating.py`, `services/audit.py`, `config.py`) nicht in Router duplizieren.

**FastAPI-Dependencies**
- User via `Depends(get_current_user)` / `Depends(get_optional_user)`.
- Permissions via `Depends(require_permission("..."))` / `Depends(require_any_permission(...))`.
- DB-Session via `Depends(get_db)`.
- Permission-Keys muessen **zuerst** in `app/permissions.py:PERMISSIONS` registriert sein, sonst scheitert die Admin-UI.

**BackgroundTasks**
- Lange Calls (Claude ~20–60 s, Impower bis 120 s) gehoeren in `BackgroundTasks`, nicht in den Request-Handler.
- **Eigene DB-Session pro BackgroundTask** (`SessionLocal()` im Task selbst), niemals die Request-Session wiederverwenden. Nach Abschluss `db.close()`.
- Muster: `_run_extraction`, `_run_case_extraction`, `run_mietverwaltung_write`.

**Jinja2-Templating**
- Genau eine Singleton-Instanz in `app/templating.py`. Neue Globals/Filter **dort** registrieren, nicht im Router (`iban_format`, `has_permission`, `field_source`).
- Template-Response mit **Request first**: `templates.TemplateResponse(request, "name.html", {...})`. Alte Signatur (`"name.html", {"request": request, ...}`) wirft `TypeError: unhashable type dict` tief in Jinja2. Memory: `feedback_starlette_templateresponse`.
- Fragment-Templates (HTMX-Swaps) starten mit Underscore: `_extraction_block.html`, `_chat_block.html`, `_case_chat_panel.html`. Volle Seiten ohne.

**HTMX-Patterns**
- Server liefert HTML-Fragmente, nicht JSON. Bei OOB-Updates (`hx-swap-oob`) beide Fragmente im gleichen Response.
- Long-Running-Status: HTMX-Polling (`hx-trigger="every 2s"`) fuer Doc-Extract, `<meta http-equiv="refresh" content="6">` fuer Case-Write.
- Form-Submits: normale `POST`-Handler, die bei HTMX-Request nur das Fragment rendern, bei Full-Navigation die ganze Seite oder `RedirectResponse`.

**Auditing**
- Nicht-trivialer Handler ruft `audit(db, user, "action_name", entity_type=..., entity_id=..., details={...}, request=request)` **vor** dem `db.commit()`. Der Helper fuegt in die Session ein — Commit macht der Caller, damit Log + Geschaefts-Change in einer Transaktion landen.
- Neue Actions in die bekannte Liste aufnehmen (siehe `docs/architecture.md` §8).

**Impower-Client-Regeln**
- Alle externen Calls durch `_api_get` / `_api_post` / `_api_put` in `app/services/impower.py`. Nicht direkt `httpx.AsyncClient` an anderen Stellen verwenden.
- Vor `PUT /contacts/{id}` die Server-managed Fields aus vorhandenen `bankAccounts[]`-Items **strippen** (`created`, `createdBy`, `updated`, `updatedBy`, `domainId`, `casaviSyncData`) — sonst 400.
- Rate-Limit-Gate (`_rate_limit_gate`) nicht umgehen: 0.12 s Mindestabstand.

**Claude-Client-Regeln**
- `messages.create` — nie `messages.parse` (Grammar-Compilation-Timeout). Memory: `feedback_claude_api_pdf_extraction`.
- System-Prompt immer via `_compose_system_prompt(workflow, chat_mode=...)` bauen (Base-Prompt + `LERN-NOTIZEN:` + optional `CHAT_PROMPT_APPENDIX`). Prompts **nie** hardcoden.
- Erkennungsmodell = `workflow.model`, Chat-Modell = `workflow.chat_model`. Beide bei jedem Call frisch aus DB lesen.
- IBAN-Guard: Jede aus LLM-Output gelesene IBAN via Unicode-NFKC normalisieren + `schwifty.IBAN(...)` validieren **bevor** sie als Extraction persistiert wird. Bei ungueltig: Korrektur verwerfen, `[Hinweis]`-Block im Chat-Antwort-Text.

### Testing Rules

**Setup**
- Pytest mit `asyncio_mode = "auto"` (aus `pyproject.toml`). Keine `@pytest.mark.asyncio`-Dekoration pro Test noetig.
- `tests/conftest.py` liefert zentrale Fixtures: User, Workflow, DB-Session — pro Test frisch.
- DB in Tests ist **SQLite in-memory** mit StaticPool; `SQLiteTypeCompiler` gemonkey-patched fuer JSONB→TEXT und UUID→CHAR(32). Keinen echten Postgres starten.

**Mocks**
- Anthropic-Client **immer** mocken (`tests/test_claude_unit.py`). Kein echter API-Call in Tests.
- Impower httpx-Client **immer** mocken (`tests/test_impower_unit.py`). Es gibt **keinen Sandbox-Tenant** — echte Calls waeren Prod-Writes.
- OAuth-Flow wird im Smoke-Test nicht durchlaufen — unauthenticated Requests muessen 302 (Redirect) oder 403 zurueckgeben.

**Testaufteilung**
- `test_claude_unit.py` — Extract-/Chat-Logik, IBAN-Guard, Pydantic-Schemas.
- `test_impower_unit.py` — Matching + Write-Client-Helpers (Idempotenz, Field-Stripping).
- `test_routes_smoke.py` — Router-Smoke: Gates (302/403), `/health` liefert 200.
- `test_upload.py` — Upload-Validierung (Size-Limit, Content-Type, PDF-Header).

**Konventionen**
- Eine Test-Funktion pro verifizierter Regel. Aussagekraeftige Namen (`test_iban_guard_rejects_zero_width_space`).
- Nie Tests gegen echte Impower-API/Anthropic-API in CI oder lokal ohne Absicht.
- Coverage-Ziel: Service-Logik + IBAN-/Permissions-/Merge-Kern. Keine Coverage-Huerde enforced.
- Kein End-to-End gegen laufenden Uvicorn — nur TestClient.

### Code Quality & Style Rules

**Naming + Struktur**
- Dateien: snake_case. Klassen: PascalCase. Funktionen/Variablen: snake_case.
- Router-Files nach Domain (`documents.py`, `cases.py`, `contacts.py`), keine `api.py`-Sammel-Files.
- Template-Fragmente: `_name.html` (Underscore-Prefix), vollstaendige Seiten ohne.
- Services: `app/services/<domain>.py` oder `app/services/<domain>_<aspect>.py` (z.B. `mietverwaltung_write.py`).

**Kommentare**
- Default: **keine** Kommentare. Nur schreiben, wenn das *Warum* nicht offensichtlich ist (Hidden Constraint, Workaround fuer Bug, ueberraschende Invariante).
- Nie Task-/PR-Referenzen im Code (`# fuer Ticket X`, `# added for Y flow`).
- Pro Datei Kommentar-Sprache konsistent: Deutsch oder Englisch, nicht mischen.

**Style**
- Keine Emojis im Code (ausser auf ausdruecklichen Wunsch).
- Keine Feature-Flags / Backwards-Compat-Shims. Bei Breaking Change direkt migrieren.
- Keine spekulative Abstraktion. Drei aehnliche Zeilen sind besser als eine praemature Helper-Funktion.
- Keine defensiven `try/except` an internen Grenzen. Validierung nur an Boundaries (User-Input, externe APIs).
- Keine `# removed`-/`# unused`-Kommentare fuer entfernten Code — einfach loeschen.

**Datenbank**
- JSONB-Dicts nie mutieren ohne `flag_modified` oder Reassignment.
- Migrations: pro Migration **ein** Zweck, kein Multi-Change-Sammelbrief.
- Spalten-Typen konsistent halten (`String(128)` mit gleicher Laenge wie existierende Referenz-Spalten).

**Frontend**
- Tailwind-Klassen statt Custom-CSS. Keine neuen `<style>`-Bloecke ohne Grund.
- Keine Client-JS-Frameworks. Wenn JS noetig: inline `<script>`, bevorzugt HTMX-Attribute.

### Development Workflow Rules

**Migrations**
- Revisionen per Hand schreiben (nie `alembic revision --autogenerate`). ORM nutzt Postgres-spezifische Typen.
- **Vor** Anlage einer neuen Migration `ls migrations/versions/` ausfuehren und die existierende neueste Revision als `down_revision` eintragen. Memory: `feedback_migrations_check_existing` (blindvertrauen auf CLAUDE.md-Liste fuehrte zu Alembic-Restart-Loop).
- Migrations laufen **automatisch beim Container-Start** (`alembic upgrade head && uvicorn ...` im Dockerfile CMD). Lokal manuell: `docker compose exec app alembic upgrade head`.

**Permissions-Erweiterung**
- Reihenfolge: (1) Key in `app/permissions.py:PERMISSIONS` registrieren → (2) Default-Rollen-Seed in `app/main.py` ergaenzen → (3) Handler per `Depends(require_permission(...))` schuetzen. Sonst scheitert die Admin-UI mit "unknown Permission".

**Secrets**
- Dev: `.env` wird aus `.env.op` via `./scripts/env.sh` (`op inject`) gebaut. `.env` ist gitignored, `.env.op` ist committed (nur Refs).
- Prod: Elestio-Env-Variablen. `SECRET_KEY` + `POSTGRES_PASSWORD` in Prod **frisch generieren**, nie Dev-Werte uebernehmen.
- Google-OAuth-Redirect-URI muss pro Env (Dev + Prod) in Google Cloud Console whitelistet sein.

**Git**
- Default-Branch `main`. Push auf `main` triggert GHCR-Build + Elestio-Auto-Deploy.
- Commit-Messages Deutsch **oder** Englisch, konsistent pro Commit.
- Keine `--no-verify`, keine Force-Pushes auf `main` (auch nicht vom User-Wunsch aus ohne Rueckfrage).
- `.env`, `.env.local`, `uploads/`-Inhalte, `postgres_data/` sind gitignored.

**Workflow-Seeds**
- Neuer Workflow: (1) Default-Prompt + `DEFAULT_MODEL`/`DEFAULT_CHAT_MODEL` in `app/services/claude.py` ergaenzen, (2) in `app/main.py:_DEFAULT_WORKFLOWS`-Tupel aufnehmen (Lifespan-Seed), (3) optional Default-Workflow-Access in `_seed_default_workflow_access`, (4) Router + optional Service. **User-Aenderungen in `workflows`-Tabelle werden beim Seed nicht ueberschrieben.**

**Rollen-Vergabe**
- Neue User bekommen Default-Rolle `user`. Admin nur via `INITIAL_ADMIN_EMAILS` (Env, komma-separiert) beim ersten Login oder manuelles Upgrade in `/admin/users/{id}`. Memory: `feedback_default_user_role`.

**Deployment**
- Prod nutzt `docker-compose.prod.yml` mit Image aus GHCR. Build laeuft in GitHub Actions, nicht auf Elestio.
- Uvicorn in Prod mit `--proxy-headers --forwarded-allow-ips=*` (Elestio-Reverse-Proxy). `X-Forwarded-For` wird im `audit()` prioritaer gelesen.

### Critical Don't-Miss Rules

**LLM-Output-Haertung**
- **IBAN/BIC aus LLM-Ausgaben immer** durch Unicode-NFKC-Normalize + `isalnum()`-Filter + `schwifty`-Validierung. Sonst schleichen sich Zero-Width-Spaces (U+200B) durch, die `replace(" ", "")` nicht faengt. Memory: `feedback_llm_iban_unicode_normalize`.
- **Haiku nicht fuer Chat/Praezision** — verliert einzelne Ziffern in freier JSON-Ausgabe (IBAN 22→21). Chat-Flows setzen Sonnet 4.6 als Default. Memory: `feedback_haiku_unreliable_for_long_digits`.
- Scan-**Dateinamen sind KEINE Info-Quelle**. Nur der PDF-Inhalt zaehlt. Ist im Extract-Prompt verankert; in neuen Prompts nicht weglassen.

**JSONB-Fallen**
- Direkte Mutation eines JSONB-Dict (`case.state["foo"] = "bar"`) ohne `flag_modified(case, "state")` oder ohne Reassignment wird **nicht persistiert**. SQLAlchemy macht keinen Deep-Diff.
- Bei Override-Listen: bei erstem Edit die aktuelle Auto-Liste in `_overrides` kopieren, sonst verliert der User bestehende Eintraege.

**BackgroundTask-Fallen**
- Request-Session NIE im BackgroundTask verwenden — ist zu dem Zeitpunkt geschlossen. Immer `SessionLocal()` frisch + `try/finally` mit `db.close()`.
- `asyncio.run(...)` nur am Einstieg eines sync BackgroundTask — nicht aus einem async Handler.

**Impower-Client**
- Vor PUT `/contacts/{id}` Server-managed Felder strippen (`created`, `createdBy`, `updated`, `updatedBy`, `domainId`, `casaviSyncData`) in allen `bankAccounts[]`-Items. Memory: `project_impower_bank_account_flow`.
- Keinen dedizierten POST-Endpoint fuer Bank-Accounts suchen — es gibt keinen. Anlage ueber GET-Contact → Array erweitern → PUT-Contact.
- Timeouts **immer** 120 s + 5xx-Retry mit Exponential-Backoff; Transient-503 vom Gateway ist normal. Memory: `project_impower_performance`.
- SEPA-Mandat-POST: **kein** `state`-Feld mitsenden. Impower setzt Status via UCM-Array selbst.
- Unit-Contract-Mandate: **ein** POST mit Array, kein Loop mit Einzelobjekten.

**Case-Write-Idempotenz**
- Jeder Schritt in `mietverwaltung_write.py` prueft vor API-Call, ob die Ziel-ID bereits in `case.impower_result` liegt. Neue Schritte **muessen** dieses Muster uebernehmen, sonst werden Retries zu Duplikaten.
- Bei Fehler: Status `partial` wenn mindestens ein Schritt durchlief, sonst `error`. Letzte 3 Errors in `impower_result.errors[]` behalten.

**Facilioo-Mirror (Epic 4)**
- Tickets werden aus der lokalen `facilioo_tickets`-Tabelle gelesen (kein Live-Call im Render-Handler; CD3 Read/Write-Trennung, FR30).
- Anzeige am Objekt-Detail in `_obj_vorgaenge.html` (eigene Sektion, `data-section="vorgaenge"`); Stale-Banner > 10 Min via `format_stale_hint()` in `app/services/facilioo_tickets.py`.
- Permission: `objects:view` reicht — Tickets sind operativ, nicht confidential. `_obj_menschen.html` ist weiterhin `objects:view_confidential` gated.
- `_OPEN_STATUS_FILTER = ("finished", "deleted", "closed", "resolved", "done")` — filtert abgeschlossene Tickets; echte Facilioo-Werte (Spike 4.1) sind `"open"/"finished"/"deleted"`.
- `get_last_facilioo_sync` nutzt `cast(JSONB, String).like(...)` fuer portablen JSONB-Zugriff auf SQLite (Tests) und PostgreSQL (Prod).

**Template-Response-Signatur**
- Starlette/FastAPI: **Request first** — `templates.TemplateResponse(request, "name.html", {...})`. Alte Form wirft `TypeError: unhashable type dict` tief in Jinja2-Internals. Memory: `feedback_starlette_templateresponse`.

**Sicherheit**
- Uploads nur via `UploadFile`; `content_type` + PDF-Header + Size pruefen (Muster in `test_upload.py`).
- PDFs landen unter `uploads/{sha256}.pdf`, Zugriff nur authentifiziert ueber `/documents/{id}/file` bzw. `/cases/{id}/documents/{doc_id}/file`.
- Audit-Log fuer alle privileged Actions (siehe bekannte Actions in `docs/architecture.md` §8).
- Kein Datenschutz-Shortcut: `@dbshome.de`-Hosted-Domain-Check bleibt Pflicht im OAuth-Callback.

**Sprache**
- Chat mit User + Artefakt-Dokumente: **Deutsch** (laut `_bmad/bmm/config.yaml`).
- Code-Kommentare: deutsch oder englisch konsistent pro Datei.
- UI-Texte und Fehlermeldungen fuer User: Deutsch.

---

## Usage Guidelines

**Fuer AI-Agenten**
- Diese Datei **vor** jeder Implementierung lesen.
- Alle Regeln exakt befolgen; im Zweifel die strengere Variante waehlen.
- Ergaenzende Referenz: `docs/architecture.md`, `docs/data-models.md`, `docs/api-contracts.md`, `CLAUDE.md`.
- Wenn ein neues Muster wiederkehrt, diese Datei erweitern — aber keine obvious Regeln aufnehmen.

**Fuer Menschen**
- Lean halten. Eine Regel darf raus, sobald sie offensichtlich aus dem Code ablesbar ist.
- Bei Stack-Aenderungen (Python-Version, SQLAlchemy-Major, Anthropic-SDK-Major): Versions-Block aktualisieren.
- Quartalsweise gegenlesen und veraltete Regeln entfernen.

Last Updated: 2026-04-21
