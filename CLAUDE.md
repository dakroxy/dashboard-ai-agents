# Dashboard KI-Agenten — Handover / Projekt-Kontext

Interne Plattform der DBS Home GmbH für KI-gestützte Verwaltungs-Workflows.

User: Daniel Kroll (kroll@dbshome.de).

## Projektziel

Zentrale Web-Plattform, auf der Mitarbeitende Dokumente hochladen und KI-Agenten damit Routineaufgaben erledigen — nach Human-in-the-Loop-Freigabe über einen Chat direkt auf der Website.

**Erstes Modul**: automatisiertes Pflegen von SEPA-Lastschriftmandaten aus eingescannten PDFs in die Impower-Hausverwaltungs-API. Ersetzt einen fehleranfälligen manuellen Prozess.

**Langfristig**: Multi-Modul-Plattform. Neue Workflows werden als Plug-in-Module angedockt; gemeinsame Core-Services (Auth, Queue, Audit, Files, Notifications, LLM-Zugang, Impower-Connector) sind bewusst wiederverwendbar angelegt.

## Aktueller Status

**Stand 2026-04-21**: M0–M2 fertig. M3 Code fertig, Neuanlage-Zweig noch live ungetestet. **M5 Mietverwaltungs-Anlage — Code komplett, alle 8 Pakete fertig, Live-Tests offen.** UI auf Sidebar-Layout umgestellt.

**M3 SEPA** (unverändert zu 2026-04-19): Idempotenz-Zweig live OK (Flögel HAM61 → `already_present`). Neuanlage-Zweig (Tilker GVE1 / Kulessa BRE11: PUT Contact mit neuem Bank-Account + POST Mandat + POST UCM-Array) noch nicht verifiziert. Nötig vor Produktivgang.

**M5 Mietverwaltungs-Anlage** (Session 2026-04-20 Pakete 1–4, Session 2026-04-21 Pakete 5–8): Multi-Doc-Workflow, der 1–n PDFs (Verwaltervertrag, Grundbuch, Mietverträge, Mieterliste) zu einem „Fall" bündelt, Claude extrahiert typ-spezifisch, Merge in konsolidierten Case-State, Nutzer-Maske zeigt Status pro Feld (erkannt / manuell / offen), Human-in-the-Loop-Freigabe, dann Impower-Write (Contacts → Property → PROPERTY_OWNER-Contract → PUT Property + Buildings → Units → TENANT-Contracts → Exchange-Plan → Deposit). Zusätzlich: Delta-Patch-Chat am Case, der Overrides direkt in den State mergt.
- Paket 1 ✓ Impower Write-API recherchiert (Anlage-Reihenfolge + DTOs in `memory/reference_impower_mietverwaltung_api.md`).
- Paket 2 ✓ Datenmodell + Migration `0008_cases_and_document_types.py` + Workflow-Seeding (`mietverwaltung_setup`, `contact_create`).
- Paket 3 ✓ Case-Entity + Multi-Doc-Upload-UI (`/cases/`, `cases_list.html`, `case_detail.html`).
- Paket 4 ✓ Extract-Pipeline pro PDF-Typ (Classifier + typ-spezifische Prompts + Pydantic-Schemas + Merge-Logik in `app/services/mietverwaltung.py`).
- Paket 5 ✓ Editierbare Form-UI mit Status-Indikatoren pro Feld. `merge_case_state()` um `overrides`-Parameter erweitert; `field_source()` als Jinja-Global für Feld-Provenance (`auto` / `user` / `missing` + `doc_type`); Save-Routen pro Sektion (`POST /cases/{id}/state/property` · `/management` · `/billing` · `/owner` · `/buildings/add|{idx}/delete` · `/units/add|{idx}|{idx}/delete` · `/tenant_contracts/add|{idx}|{idx}/delete`) + Reset-Routen (`/state/reset/{section}`); `case_detail.html` komplett neu als editierbare Form mit Sektionen 1–7.
- Paket 6 ✓ Contact-Create-Sub-Workflow. `impower.py`: `check_contact_duplicates()` + `create_contact()` + `_build_contact_payload()`. Neuer Router `contacts.py` (`GET/POST /contacts/new` → Duplicate-Check → `POST /contacts/confirm`). Dashboard-Kachel. Aus Case-Eigentümer-Sektion als Button mit `?prefill=<json>&return_to=/cases/{id}`.
- Paket 7 ✓ Impower-Write-Pfad. Neuer Service `app/services/mietverwaltung_write.py` mit 8-stufigem Flow (`_write_owner_contact` → `_write_tenant_contacts` → `_write_property` → `_write_property_owner_contract` → `_write_property_details` [PUT mit Buildings inline] → `_write_units` → `_write_tenant_contracts` [TENANT-Contracts] → `_write_exchange_plans` → `_write_deposits`). Idempotenz über `case.impower_result` (pro Schritt IDs festgehalten — Retry skippt bereits geschriebene). Preflight-Check. `POST /cases/{id}/write` triggert BackgroundTask; UI zeigt Live-Status mit Meta-Refresh alle 6 s.
- Paket 8 ✓ Case-Chat. Migration `0009_chat_messages_case_id.py` (`chat_messages.document_id` nullable + `case_id` hinzugefügt). `chat_about_case()` in `mietverwaltung.py` mit Delta-Patch-Prompt (nur geänderte Sektionen — entschärft den Backlog-Punkt zur Full-JSON-Ausgabe). IBAN-Guard + Unicode-NFKC wie SEPA. `POST /cases/{id}/chat` (HTMX). Chat-Drawer `_case_chat_panel.html` unten rechts.

Siehe Abschnitt „Stand M5 (Mietverwaltung)" weiter unten für Details.

**UI-Umbau** (2026-04-20): Top-Nav raus, linkes Sidebar-Menü rein (Dashboard · Workflows · Admin + User-Block unten). Dashboard zeigt Workflow-Kacheln mit Gradient-Header (SEPA Sky→Indigo · Mietverwaltung Emerald→Teal · Kontakt-Anlage Violet→Fuchsia). Einzelne Workflows sind nicht in der Sidebar — Zugang nur über Dashboard-Kacheln.

Git-Repo: **weiterhin nicht initialisiert.** Remote `git@github.com:dakroxy/dashboard-ai-agents.git` unverknüpft.

Nächster Schritt (dreigleisig):
1. **M5 Paket 7 Live-Test** — Fall mit Verwaltervertrag + Grundbuch + Mieterliste + ≥1 Mietvertrag komplett durchspielen → `POST /cases/{id}/write`. Besonders beobachten: Exchange-Plan-Step. Wenn Impower 400/422 wirft, muss der `templateExchanges[]`-Aufbau (MVP: 1 Plan mit 3 Positions-Typen COLD_RENT / OPERATING_COSTS / HEATING_COSTS) auf eine andere Granularität umgebaut werden (ggf. 1 Plan pro Position oder Summen-Eintrag mit Splits).
2. **M3-Neuanlage-Zweig** live verifizieren (Tilker GVE1 / Kulessa BRE11).
3. Danach: `git init` + Remote verknüpfen + Initial-Commit; dann M4 (Elestio).

## Architektur

```
Dashboard (Web-UI)
  └─ Platform-Core: Auth · Rollen/Permissions · Audit · Files · Notifications
        ├─ Claude-API-Client (PDF-Extraktion, Chat-Agent)   ← in M1 fertig
        └─ Impower-Connector (Read + Write)                 ← M2 (read) / M3 (write)
               │
               ├─ Modul 1: Lastschrift-Agent (M1–M3)              ← Single-Doc-Workflow
               ├─ Modul 2: Mietverwaltungs-Anlage (M5)            ← Multi-Doc-Fall (Case-Container)
               └─ Sub-Workflow: Contact-Create                    ← aus Modul 2 + spätere Module aufrufbar
```

**Workflow-Konfiguration in DB**: System-Prompt + Erkennungsmodell (`model`) + Chat-Modell (`chat_model`) + Lernnotizen pro KI-Agent sind editierbar (`/workflows/{key}`). Erkennungs- und Chat-Modell sind bewusst getrennt konfigurierbar — der Chat-Flow muss exakt Ziffern reproduzieren (IBANs), da scheitert Haiku empirisch; Default Chat-Modell ist Sonnet 4.6. Jeder Agent hat einen stabilen `key`; aktuell drei Workflows geseedet: **`sepa_mandate`** (SEPA-Lastschriftmandate — M1–M3), **`mietverwaltung_setup`** (M5), **`contact_create`** (Sub-Workflow, aus Mietverwaltung aufrufbar). Extract- und Chat-Service lesen den aktuellen DB-Stand bei jedem Call. Default-Prompts / Default-Modelle stehen in `app/services/claude.py` (`DEFAULT_SYSTEM_PROMPT` / `DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT` / `DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT` / `DEFAULT_MODEL` / `DEFAULT_CHAT_MODEL`) und werden beim App-Start via FastAPI-Lifespan geseedet (`_seed_default_workflow` in `main.py` iteriert über `_DEFAULT_WORKFLOWS`-Tupel), falls der Workflow fehlt — bestehende User-Änderungen werden **nicht** überschrieben.

## Tech-Stack

- **Backend**: FastAPI 0.115 + Uvicorn, Python 3.12
- **DB**: Postgres 16 (lokal via Docker, Prod später Elestio Managed)
- **ORM / Migrations**: SQLAlchemy 2.0 (typed `Mapped[...]`), Alembic
- **Frontend**: HTMX 2 + Jinja2 + Tailwind CSS via CDN — bewusst kein npm-Stack
- **Auth**: Google Workspace OAuth über Authlib; Session via Starlette `SessionMiddleware` (itsdangerous)
- **LLM**: Anthropic SDK, Claude Opus 4.7 für Extract (`claude-opus-4-7`, pro Workflow umstellbar), Sonnet 4.6 als Default-Chat-Modell (`claude-sonnet-4-6`); multimodaler PDF-Call, Prompt-Caching auf System-Block (wirkungslos solange <4096 Tokens — greift, wenn Prompt + Lernnotizen wachsen)
- **IBAN/BIC-Handling**: `schwifty` (Bundesbank-BLZ-Register) zur BIC-Ableitung aus IBAN + IBAN-Validierung. Eingebaut weil (a) moderne SEPA-Mandate oft keinen BIC mehr drucken, (b) Impowers `PUT /contacts` besteht auf gültigem BIC.
- **Deployment**: Docker Compose; Prod auf Elestio mit Auto-Deploy bei Push auf `main` (M4)
- **Domain (geplant)**: `dashboard.dbshome.de`
- **Secret-Management**: 1Password + `op inject` → `.env` (siehe unten)

## Dateistruktur (aktuell)

```
Dashboard KI-Agenten/
├── .gitignore · .dockerignore · .env.example · .env.op
├── docker-compose.yml · Dockerfile
├── pyproject.toml · README.md
├── CLAUDE.md
├── alembic.ini
├── scripts/
│   └── env.sh                  op inject -i .env.op -o .env
├── mockups/                    Standalone-HTML-Prototypen (z. B. mietverwaltung_setup.html)
├── migrations/
│   ├── env.py · script.py.mako
│   └── versions/
│       ├── 0001_initial.py                            users · documents · extractions
│       ├── 0002_chat_messages.py                      chat_messages
│       ├── 0003_workflows.py                          workflows
│       ├── 0004_audit_log_and_document_results.py     audit_log · documents.matching_result/impower_result
│       ├── 0005_workflow_chat_model.py                workflows.chat_model
│       ├── 0006_roles_and_resource_access.py          roles · resource_access · user.role_id/permissions_extra
│       ├── 0007_audit_log_generic.py                  audit_log-Erweiterung (entity_type · entity_id · user_id)
│       ├── 0008_cases_and_document_types.py           cases · documents.case_id · documents.doc_type
│       └── 0009_chat_messages_case_id.py              chat_messages.case_id + document_id nullable (Case-Chat)
└── app/
    ├── main.py                 FastAPI-App, Lifespan seeded drei Workflows (sepa_mandate, mietverwaltung_setup, contact_create) + Rollen + Workflow-Access
    ├── config.py               Settings via pydantic-settings
    ├── db.py                   Engine · SessionLocal · Base · get_db
    ├── auth.py                 OAuth-Client · get_current_user / get_optional_user
    ├── permissions.py          Permission-Registry · has_permission · require_permission · Resource-Access-Checks
    ├── templating.py           Jinja2Templates-Singleton + Jinja-Filter (iban_format, has_permission, field_source)
    ├── models/
    │   ├── user.py · document.py · extraction.py
    │   ├── chat_message.py                      document_id + case_id beide nullable; genau einer gesetzt (SEPA-Chat vs. Case-Chat)
    │   ├── workflow.py · audit_log.py
    │   ├── role.py · resource_access.py         Rollen + Resource-basierter Zugriff (Workflows)
    │   └── case.py                              Multi-Doc-Fall (Mietverwaltung); state JSONB; documents-Relationship
    ├── routers/
    │   ├── auth.py             /auth/google/login · /callback · /logout
    │   ├── documents.py        /documents/ · Upload · Detail · Approve · Chat · File · Status (+ iban_format Jinja-Filter)
    │   ├── cases.py            /cases/ · Fall-Anlage · Multi-Doc-Upload · doc_type-Klassifikation · Rename · Löschen; /cases/{id}/state/* Save-Routen pro Sektion + Reset; /cases/{id}/write (Impower-Write-Trigger); /cases/{id}/chat (Case-Chat)
    │   ├── contacts.py         /contacts/new (GET/POST → Duplicate-Check) · /contacts/confirm (tatsaechliche Anlage)
    │   ├── impower.py          /impower/health · /properties · /contracts · /match (Debug/Read-API)
    │   ├── workflows.py        /workflows/ · /workflows/{key} (GET/POST) — editierbar für alle drei Workflows
    │   └── admin.py            /admin/* — User-/Rollen-Verwaltung, Workflow-Access, Audit-Log
    ├── services/
    │   ├── claude.py                    extract_mandate_from_pdf · chat_about_mandate (+ IBAN-Guard mit Unicode-NFKC-Normalize) · DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT · DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT
    │   ├── mietverwaltung.py            M5 Paket 4: classify_document + extract_for_doc_type + Pydantic-Schemas pro Doc-Typ. M5 Paket 5: merge_case_state(…, overrides=…) + field_source(). M5 Paket 8: chat_about_case() mit Delta-Patch + IBAN-Guard
    │   ├── mietverwaltung_write.py      M5 Paket 7: run_mietverwaltung_write() BackgroundTask; 8-stufiger Flow; preflight(); Idempotenz via case.impower_result
    │   ├── impower.py                   run_full_match (M2) · write_sepa_mandate (M3) · check_contact_duplicates + create_contact + _build_contact_payload (M5 P6) · Schwifty BIC-Derivation
    │   └── audit.py                     Zentraler Audit-Helper (audit() fügt AuditLog-Eintrag in Session)
    ├── templates/
    │   ├── base.html                  Linkes Sidebar-Menü (Dashboard/Workflows/Admin) + User-Block unten; responsive; Active-State via request.url.path
    │   ├── index.html                 Dashboard mit Workflow-Kacheln (Gradient-Header SEPA/Mietverwaltung/Kontakt-Anlage)
    │   ├── documents_list.html        Liste + Upload-Form (SEPA)
    │   ├── document_detail.html       Side-by-side Layout (SEPA)
    │   ├── cases_list.html            Liste der Mietverwaltungs-Fälle + „Neuer Fall"-Button
    │   ├── case_detail.html           Editierbare Form-UI (Paket 5): Sektionen 1–7 (Objekt · Verwaltung · Rechnung · Eigentümer · Gebäude · Einheiten · Mietverträge); Status-Pills pro Feld (erkannt/manuell/leer); Impower-Write-Button + Status-Block (Paket 7); Chat-Drawer-Include (Paket 8)
    │   ├── _case_chat_panel.html      Chat-Drawer Mietverwaltungs-Agent (Paket 8); HTMX-basiert; fixed unten rechts
    │   ├── contact_create.html        Kontakt-Anlage-Form (Paket 6); Duplicate-Check-Warnung + Bestätigen-Flow
    │   ├── _extraction_block.html     Extraktion + Approve (auch HTMX-Polling + OOB-Ziel)
    │   ├── _chat_block.html           Chat-Historie + Form (HTMX, SEPA)
    │   ├── _chat_response.html        Chat-Antwort-Fragment (+ optional OOB-Extraction, SEPA)
    │   ├── _macros.html               status_pill
    │   ├── workflows_list.html · workflow_edit.html      generisch für alle Workflows (SEPA, Mietverwaltung, Kontakt anlegen)
    │   └── admin/ …                   Admin-Views (User, Rollen, Audit-Log)
    └── static/.gitkeep
```

Lokal starten:

```bash
./scripts/env.sh                  # .env aus 1Password bauen (einmalig)
docker compose up --build
```

## Datenmodell

- **User** — `google_sub`, `email`, `name`, `picture`, `last_login_at`.
- **Document** — `uploaded_by_id` (FK user), `workflow_id` (FK workflow), `original_filename`, `stored_path` (`{sha256}.pdf` unter `uploads/`), `content_type`, `size_bytes`, `sha256` (indexed), `status`-Lifecycle: `uploaded` → `extracting` → `extracted` / `needs_review` / `failed`; → `matching` → `matched` oder `needs_review`; → Mitarbeiter-Freigabe → `approved` → `writing` → `written` / `already_present` / `error`. Plus `matching_result` (JSONB), `impower_result` (JSONB), `uploaded_at`. **Seit Migration 0008**: `case_id` (nullable FK `cases`) — SEPA lässt null, Mietverwaltung setzt den Container-Case; `doc_type` (nullable, z. B. `verwaltervertrag`/`grundbuch`/`mietvertrag`/`mieterliste`/`sonstiges`).
- **Extraction** — `document_id`, `model`, `prompt_version` (`{workflow.key}-{sha256(prompt+notes)[:8]}`), `raw_response`, `extracted` (JSONB), `status` (`ok` / `needs_review` / `failed`), `error`, `created_at`. Mehrere Extraktionen pro Dokument möglich (neue Row bei jedem Chat-Update).
- **ChatMessage** — entweder `document_id` (SEPA-Chat an einem Mandat) ODER `case_id` (Mietverwaltungs-Case-Chat, Migration 0009); beide nullable, Constraint im Code. Plus `role` (`user`/`assistant`), `content`, `extraction_id` (nullable FK — setzt Verbindung zu der durch diese Chat-Antwort entstandenen Extraction), `created_at`.
- **Workflow** — `key` (unique, z. B. `sepa_mandate`), `name`, `description`, `model` (Erkennungsmodell), `chat_model` (Chat-/Rückfrage-Flow), `system_prompt`, `learning_notes`, `active`, `created_at`, `updated_at`.
- **AuditLog** — `user_id` (FK user, nullable), `user_email`, `action`, `entity_type` (z. B. `document`/`case`/`workflow`), `entity_id` (UUID der betroffenen Entity), `document_id` (Legacy-FK für SEPA-Fälle), `ip_address`, `details_json` (JSONB), `created_at`. Wird überall über den zentralen `audit()`-Helper geschrieben; seit Migration 0007 generisch (entity_type/entity_id), sodass auch Cases/Workflows/User-Events geloggt werden.
- **Role** — `key` (`admin` / `user` / ...), `name`, `description`, `permissions` (JSON-Array von Permission-Keys wie `documents:upload`, `workflows:edit`), `is_system_role`. Systemrollen werden beim App-Start geseedet (überschreibt Permissions **nicht** bei späterem Restart).
- **ResourceAccess** — `user_id` oder `role_id` (eines von beiden), `resource_type` (aktuell `workflow`), `resource_id`, `mode` (`allow`/`deny`). User-Overrides gewinnen über Role-Defaults. Steuert z. B. welcher Workflow einem User sichtbar ist.
- **Case** (Migration 0008) — `workflow_id` (FK workflow, aktuell nur `mietverwaltung_setup`), `created_by_id` (FK user), `name` (nullable), `status` (`draft` → `extracting` → `ready_for_review` → `writing` → `written` / `partial` / `error`), `state` (JSONB — gemergter Stand aus Extractions + `_overrides` mit User-Edits + `_extractions` als Provenance), `impower_result` (JSONB, nach Write-Pfad: `contacts.{owner_id, tenants.{key}}`, `property_id`, `property_owner_contract_id`, `property_update_ok`, `building_ids`, `building_name_to_id`, `unit_ids.{num}`, `tenant_contract_ids.{key}`, `exchange_plan_ids.{key}`, `deposit_ids.{key}`, `steps_completed[]`, `errors[]`), `created_at`, `updated_at`. Relationship zu `documents` via `documents.case_id`.

## Routen-Überblick

| Route | Zweck |
|---|---|
| `GET /` | Dashboard (Login oder Workflow-Übersicht) |
| `GET /auth/google/login` · `/callback` · `/logout` | OAuth-Flow |
| `GET /documents/` | Liste aller Dokumente des Users |
| `POST /documents/` | Upload → legt Document an, scheduled BackgroundTask, redirectet auf Detail |
| `GET /documents/{id}` | Detail-Seite (PDF links, Extraktion + Chat rechts) |
| `GET /documents/{id}/file` | PDF inline (`Content-Disposition: inline`) |
| `GET /documents/{id}/status` | HTMX-Polling für Extraktions-Block während `uploaded`/`extracting` |
| `POST /documents/{id}/approve` | Status `extracted`/`needs_review` → `approved` |
| `POST /documents/{id}/chat` | User-Message + Claude-Call (synchron, hx-indicator); Response ist neues Chat-Panel + optional OOB-Extraction |
| `GET /cases/` | Liste der Mietverwaltungs-Fälle (filtered per Workflow-Access + ggf. eigene) |
| `POST /cases/` | Neuer Fall (leer) → Redirect auf Detail |
| `GET /cases/{id}` | Fall-Detail mit Dokumenten-Liste + Multi-Doc-Upload-Form |
| `POST /cases/{id}/name` | Fall umbenennen |
| `POST /cases/{id}/documents` | PDF-Upload an Fall (optional doc_type mitsetzen); triggert Classify+Extract via BackgroundTask |
| `POST /cases/{id}/documents/{doc_id}/type` | doc_type nachträglich setzen/ändern; triggert Re-Extract bei Typ-Wechsel |
| `POST /cases/{id}/documents/{doc_id}/extract` | Extract-Pipeline für ein einzelnes Dokument manuell neu anstoßen |
| `POST /cases/{id}/documents/{doc_id}/delete` | PDF aus Fall entfernen |
| `GET /cases/{id}/documents/{doc_id}/file` | PDF inline (Content-Disposition: inline) |
| `POST /cases/{id}/state/property` · `/management` · `/billing` · `/owner` | Sektion-Save für flache Dict-Sektionen (Paket 5) — speichert als `_overrides.{section}` + Recompute |
| `POST /cases/{id}/state/buildings/add` · `/buildings/{idx}/delete` | Gebäude-Liste editieren (Paket 5) |
| `POST /cases/{id}/state/units/add` · `/units/{idx}` · `/units/{idx}/delete` | Einheiten-Tabelle editieren |
| `POST /cases/{id}/state/tenant_contracts/add` · `/tenant_contracts/{idx}` · `/tenant_contracts/{idx}/delete` | Mietverträge editieren |
| `POST /cases/{id}/state/reset/{section}` | Override einer Sektion verwerfen → zurück auf Auto-Erkennung |
| `POST /cases/{id}/write` | Impower-Write-Pfad triggern (Preflight + BackgroundTask, Paket 7) |
| `POST /cases/{id}/chat` | Case-Chat mit Delta-Patch-Support (Paket 8); rendert `_case_chat_panel.html`-Fragment |
| `GET /contacts/new` · `POST /contacts/new` | Kontakt-Anlage-Form + Duplicate-Check (Paket 6); optional `?prefill=<json>&return_to=...` aus Case-Kontext |
| `POST /contacts/confirm` | Tatsächliche Impower-Contact-Anlage nach Duplicate-Bestätigung |
| `GET /workflows/` · `GET /workflows/{key}` · `POST /workflows/{key}` | Einstellungen pro Workflow (für alle drei Workflows identisch editierbar) |
| `GET /admin/*` | User-/Rollen-Verwaltung, Workflow-Access, Audit-Log-Ansicht |

## Claude-Integration (`app/services/claude.py`)

- **Modelle**: Erkennungsmodell Default `claude-opus-4-7`, Chat-Modell Default `claude-sonnet-4-6` — beide pro Workflow editierbar (`workflow.model` / `workflow.chat_model`). Verfügbare Werte: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`. **Haiku für Chat empirisch nicht tragfähig** — scheitert an präziser Ziffern-Reproduktion über 20+ Zeichen in freier JSON-Ausgabe (IBAN-Drop: verliert z. B. die letzte `0`). Sonnet ist der sichere Default, Opus Overkill für die Chat-Länge.
- **Extract-Flow**: `extract_mandate_from_pdf(pdf_bytes, workflow)` → PDF als base64-Document-Block + Text-Instruction, `messages.create` (NICHT `messages.parse` — siehe Memory), Ergebnis wird lokal gestripped, `json.loads`'t, per `MandateExtraction`-Pydantic validiert. Nutzt `workflow.model`.
- **Chat-Flow**: `chat_about_mandate(pdf_bytes, workflow, current_extraction, history, new_message)` baut Multi-Turn-Messages (Initial-Prompt mit aktueller Extraktion + komplette Chat-Historie + neue Message). Nutzt `workflow.chat_model`. Antwort enthält optional einen Markdown-JSON-Codeblock mit aktualisierter Extraktion — per Regex extrahiert, Pydantic-validiert, als neue Extraction-Row persistiert; via HTMX-OOB-Swap erscheint sie sofort im UI.
- **IBAN-Guard im Chat-Flow**: bevor eine Chat-Korrektur als neue Extraktion übernommen wird, wird die IBAN **Unicode-NFKC-normalisiert** + auf reine Alphanumerik reduziert + per `schwifty` validiert. Hintergrund: Sonnet streut gelegentlich unsichtbare Zero-Width-Spaces in Ausgaben ein, die `replace(" ", "")` NICHT entfernt — ohne den Guard fallen Chat-Korrekturen mit „Invalid IBAN length" durch, obwohl visuell alles stimmt. Zweitens schützt der Guard vor Ziffern-Dropout-Bugs (Haiku). Bei ungültiger IBAN wird die Korrektur verworfen, der User bekommt im Chat-Antwort-Text einen `[Hinweis]`-Block.
- **Prompt-Komposition**: `_compose_system_prompt(workflow, chat_mode)` = `workflow.system_prompt` + (optional `LERN-NOTIZEN:\n{workflow.learning_notes}`) + (optional `CHAT_PROMPT_APPENDIX` mit Rückfragen-Regeln).
- **Prompt-Caching**: `cache_control: {type: "ephemeral"}` auf dem System-Block. Opus 4.7 hat 4096-Token-Mindestlänge — mit aktuellem Prompt (~1000 Tokens) greift der Cache noch nicht; wirkt erst bei größeren Prompts oder Lernnotizen.

## Secret-Management (1Password)

- Vault `KI` in "DBS Home GmbH".
- Items: `Google OAuth - HV Dashboard AI Agents` (`username` = Client-ID, `credential` = Secret), `Claude API Key - Lastschrift` (`credential`), `Impower API Token PowerAutomate` (`credential`).
- Service-Account-Token in macOS-Keychain als `op-service-account-ki`.
- Workflow: `.env.op` (committed, nur Refs) → `./scripts/env.sh` → `.env` (gitignored). `docker compose` liest `.env` physisch, deshalb inject-basiert statt `op run`.
- Dev-only Werte (`SECRET_KEY`, `POSTGRES_PASSWORD`) sind Klartext in `.env.op`; Prod bekommt echte Werte über Elestio-Env-Variablen.

## Meilensteine

| ID | Inhalt | Schätzung | Status |
|----|--------|-----------|--------|
| M0 | Grundgerüst (FastAPI + Postgres + Docker) | 1–2d | fertig |
| M1 | OAuth + Upload + Extraktion + Chat + Workflow-Einstellungen | 2–3d | fertig |
| M2 | Impower-Matching (Property + Contact, Read-Pfad) | 2–3d | fertig, live verifiziert (HAM61 Score 100 %) |
| M3 | Freigabe → Impower-Schreibpfad (Bank-Account, Mandat, Haken) | 2d | **Code fertig, Idempotenz-Zweig live OK — Neuanlage-Zweig noch live zu verifizieren** |
| M4 | Elestio-Deployment + DNS + TLS | 1d | offen |
| M5 | Mietverwaltungs-Anlage (Multi-Doc → Impower, neuer Workflow) | 7–10d | **Code komplett (Pakete 1–8 fertig), Live-Tests offen** — insbesondere der Impower-Write (Paket 7) mit echtem Case; Exchange-Plan-Schema muss ggf. nach erstem POST angepasst werden |

## Stand M3 (2026-04-19, Abend)

### Was gebaut / gefixt wurde

Alle vier Code-Bugs aus dem Vormittag sind behoben, Idempotenz + Härtungen oben drauf:

1. **`_ensure_bank_account` neu** — Bank-Account-Anlage läuft via `GET /services/pmp-accounting/api/v1/contacts/{id}` → Duplicate-Check im `bankAccounts[]`-Array (normalisierter IBAN-Vergleich) → falls neu: Item anhängen, Server-Felder (`id`, `created`, `createdBy`, `updated`, `updatedBy`, `domainId`, `casaviSyncData`) aus bestehenden Items strippen → `PUT /services/pmp-accounting/api/v1/contacts/{id}` → neue `bankAccountId` aus der PUT-Response via IBAN-Match extrahieren. Der ursprünglich vermutete `POST /v2/contacts/{id}/bank-accounts`-Endpunkt existiert nicht.
2. **`_create_direct_debit_mandate`** — `state`-Feld aus dem Payload raus; Impower setzt den Status selbst via UCM.
3. **`_create_unit_contract_mandates`** — ein einziger POST mit Array aller Einträge statt Loop mit Einzelobjekten. Response ist ebenfalls ein Array mit IDs.
4. **Timeouts + Retries** — 120 s Timeout, 5xx-Retry mit Exponential-Backoff (2/5/15/30/60 s, max 5 Versuche), identisch für GET/POST/PUT. Neuer `_api_put`-Helper analog zu `_api_post`.
5. **Idempotenz-Check** — nach `_ensure_bank_account` wird `GET /api/v1/direct-debit-mandate?propertyId=X` geladen und gegen `{bankAccountId, state: "BOOKED"}` gefiltert. Treffer → Early-Return mit `WriteResult.already_present=True`, kein POST. `Document.status = "already_present"`, UI zeigt grüne Meldung „Mandat bereits mit dieser IBAN eingetragen — nichts geändert".

### Was zusätzlich dazukam (aus der Session)

- **BIC-Auto-Ableitung via `schwifty`** — neue Dependency, leitet BIC aus der IBAN ab, weil moderne SEPA-Mandate oft keinen BIC mehr drucken und Impower (scheinbar) auf einem gültigen BIC besteht. Fällt durch auf klaren Fehler, wenn die BLZ im schwifty-Register nicht bekannt ist. Extract-seitig bleibt BIC optional (Claude liefert ihn, wenn er auf dem Formular steht); der Write-Pfad zieht bei leerem BIC das Register.
- **IBAN-Validierung + Unicode-Normalize (Chat-Guard)** — Sonnet schmuggelt gelegentlich Zero-Width-Spaces (U+200B) in IBAN-Ausgaben. Naive `replace(" ", "")` fängt das nicht, Schwifty meldet dann „Invalid IBAN length" bei sichtbar korrekter IBAN. Fix an zwei Stellen: `_normalize_iban` in `impower.py` nutzt `unicodedata.normalize("NFKC", …)` + `.isalnum()`-Filter; Chat-Guard in `claude.py` normalisiert die Chat-Korrektur-IBAN und validiert mit Schwifty BEVOR sie als Extraktion persistiert wird. Ungültige Korrektur → Extraktion NICHT übernommen, `[Hinweis]`-Block in der Chat-Antwort.
- **Chat-Modell separat konfigurierbar** — `workflows.chat_model` (Migration 0005), Default `claude-sonnet-4-6`. Grund: Haiku 4.5 verliert in freier JSON-Ausgabe präzise Ziffern (IBAN 22→21), Sonnet ist der sichere Default für den Chat-Flow. Erkennungsmodell bleibt unabhängig konfigurierbar (Kostenabwägung).
- **IBAN-Format-Filter** — Jinja-Filter `iban_format` (in `documents.py` registriert) gruppiert die IBAN im UI in 4er-Blocks (`DE05 2598 0027 0611 2183 00`). Nur Anzeige, Speicherung bleibt kompakt.
- **WriteResult.already_present** und neue Doc-Status `already_present` + passende Status-Pill und End-Block im `_extraction_block.html`. Chat-Korrekturen resetten auch den `already_present`-Status zurück auf `extracted`, damit das Re-Matching durchläuft.

### Live-Teststand (HAM61 Flögel)

- Matching läuft 100% (Property + Contact Score 100%).
- Schreibpfad: Idempotenz-Zweig durchgelaufen — Flögel hat bereits ein BOOKED-Mandat auf dieser IBAN (Mandat-ID 283929, Bank-Account-ID 700509). UI zeigt „bereits eingetragen", keine ungewollten Writes. Das bestätigt: Idempotenz-Check funktioniert, Modell/Chat-Flow inkl. Unicode-Härtung funktioniert.
- **Noch nicht verifiziert:** der Neuanlage-Zweig (PUT Contact mit neuem Bank-Account, POST Mandat, POST UCM-Array). Erst ein Dokument nötig, das noch nicht in Impower als BOOKED-Mandat existiert — Kandidaten: Tilker (GVE1) oder Kulessa (BRE11).

### Sekundärer Befund: IBAN-Wechsel ist der Normalfall

Flögel hatte keine `open_contract_ids` — alle Unit-Contracts waren bereits mit einem älteren Mandat verknüpft. Das ist der **häufigste Case**: Eigentümer wechselt Bankverbindung. Für diesen Fall braucht es einen erweiterten Flow: altes Mandat via `PUT /api/v1/direct-debit-mandate/deactivate` deaktivieren, neues Mandat anlegen, Unit-Contract-Verknüpfungen umhängen. **Nicht im MVP implementiert**, vor Produktiv-Rollout nötig.

### Impower API — wichtige Pfade für M3

- `GET /services/pmp-accounting/api/v1/contacts/{id}` — voller Contact inkl. `bankAccounts[]` (für GET-vor-PUT)
- `PUT /services/pmp-accounting/api/v1/contacts/{id}` — Contact updaten, Body `ContactLegacyDto` (kompletter Contact)
- `POST /services/pmp-accounting/api/v1/direct-debit-mandate` — Mandat anlegen, Body `{bankAccountId, propertyId, directDebitSignedOnDate, directDebitValidFromDate}` (KEIN `state`!)
- `POST /services/pmp-accounting/api/v1/unit-contract-mandate` — Array `[{unitContractId, directDebitMandateId, state}]`
- `GET /services/pmp-accounting/api/v1/direct-debit-mandate?propertyId=X` — existierende Mandate listen (Idempotenz-Check)
- `PUT /services/pmp-accounting/api/v1/direct-debit-mandate/deactivate` — altes Mandat deaktivieren (IBAN-Wechsel-Szenario, noch nicht verdrahtet)

Swagger-Specs: `https://api.app.impower.de/v2/api-docs` (Main Read, 57 Pfade) und `https://api.app.impower.de/services/pmp-accounting/v2/api-docs` (Write, 358 Pfade, Swagger 2.0). Alle anderen pmp-Service-Präfixe wurden getestet und existieren nicht (alle 404).

### Paperclip-Migration (2026-04-19)

Der parallele `paperclip-dashboard-ki-agenten`-Ordner wurde komplett nach `Dashboard KI-Agenten` migriert und danach gelöscht. Git-History wurde bewusst verworfen — frisches `git init` steht noch aus. Remote `git@github.com:dakroxy/dashboard-ai-agents.git` muss neu verknüpft werden. Migration 0004 wurde neu angelegt, weil Paperclip `AuditLog` + `documents.matching_result/impower_result` ohne Migration hatte. Migration 0005 fügt `workflows.chat_model` hinzu. Tests (62 in `tests/`) sind da.

## Was in M1 zusätzlich dazukam, das ursprünglich nicht im Plan war

- **Workflow-Konfiguration in DB** (Prompt + Modell + Lernnotizen editierbar). Kam spät dazu, war Wunsch des Users. Hintergrund: langfristiger "lernender Agent" — für jetzt pragmatisch als Freitext-Lernnotizen umgesetzt, die bei jedem Call an den Prompt angehängt werden. Phase 2 kann daraus Few-Shot-Examples oder automatische Notizen-Ableitung aus Chat-Korrekturen werden.
- **Side-by-side Detail-Layout** mit PDF-Iframe (`#view=FitH&pagemode=none` blendet Thumbnails im Chrome-PDF-Viewer aus). Grid `lg:grid-cols-[1.7fr_1fr]`.
- **Approve-Button** setzt Status auf `approved` — Impower-Write noch nicht verdrahtet (kommt in M3, aber die Vorstufe ist da).

## Offene Punkte für M3 (nächste Session)

Code ist fertig, es geht um Verifikation und die IBAN-Wechsel-Erweiterung:

1. **Neuanlage-Zweig live verifizieren** — Tilker (GVE1) oder Kulessa (BRE11) hochladen, extrahieren, approven. Erwartung: PUT Contact mit neu angehängtem Bank-Account, POST Mandat, POST UCM-Array → Status `written`, grüner Haken. Damit ist auch die schwifty-BIC-Ableitung live getestet (Flögel ging über den Idempotenz-Shortcut, da lief der PUT gar nicht).
2. **IBAN-Wechsel-Szenario (pre-prod, vor Produktiv-Rollout)**: wenn alle Unit-Contracts der Person schon BOOKED sind und das gesuchte IBAN-Mandat NICHT darunter ist, muss erst `PUT /direct-debit-mandate/deactivate` auf das alte Mandat laufen, dann das neue angelegt und die Verknüpfungen umgehängt werden. Noch nicht implementiert. Logik-Skizze: aus `matching_result.contact.open_contract_ids == []` + `impower_result.already_present == False` folgt Wechsel-Case → separate Handler-Funktion, evtl. zusätzlicher Status `iban_wechsel_pending` mit User-Bestätigung im Chat bevor deactivate/re-create ausgeführt wird.
3. **Saubere Fehlermeldungen** — `_sanitize_error` kürzt HTML-Responses; aktuelle Error-Darstellung im UI (`_extraction_block.html`, `ir.error`-Block) ist lesbar. Kein offener Punkt mehr, aber vor dem Produktiv-Rollout nochmal gegen echte Error-Cases gegencheken.

Wenn 1+2 durch sind: frisches `git init`, Remote verknüpfen, Initial-Commit pushen, dann M4 (Elestio) in Angriff.

## Stand M5 (Mietverwaltung) — 2026-04-21

Multi-Doc-Workflow für die Neuanlage einer Mietverwaltung in Impower. Session 2026-04-20 hat die Pakete 1–4 (Fundament + Extraktion) abgeschlossen, Session 2026-04-21 die Pakete 5–8 (Form-UI + Contact-Create + Impower-Write + Chat). Code-seitig komplett; offen sind nur Live-Tests gegen die echte Impower-API.

### Gesamt-Flow (implementiert)

Ein „Fall" (Case) sammelt die Dokumente zu einer Mietverwaltungs-Anlage: Verwaltervertrag, Grundbuch, Mieterliste, n Mietverträge. Pro Dokument-Typ erkennt Claude die relevanten Felder (typ-spezifischer Prompt); ein Merge-Service baut daraus einen konsolidierten Case-State mit Provenance pro Feld. Der Nutzer sieht eine strukturierte Eingabemaske mit Status-Pills (erkannt / manuell / leer) pro Feld, editierbar in allen 7 Sektionen (Objekt · Verwaltung · Rechnung · Eigentümer · Gebäude · Einheiten · Mietverträge). User-Edits landen als `_overrides` im Case-State und haben Vorrang vor den Auto-Merge-Werten. Fehlt ein Eigentümer- oder Mieter-Kontakt in Impower, wird der wiederverwendbare `contact_create`-Sub-Workflow aufgerufen (Button in der Eigentümer-Sektion, mit Prefill aus dem Case). Parallel steht ein Chat-Drawer bereit, der Delta-Patches zum State vorschlägt. Nach Freigabe läuft der Write-Pfad als BackgroundTask: Contacts (Eigentümer + Mieter) → Property-Minimalanlage → PROPERTY_OWNER-Contract → PUT Property mit Detail-Feldern (inkl. Buildings inline) → Units (Array-POST) → TENANT-Contracts (Array-POST) → Exchange-Plan (Miet-Positionen) → Deposit (Kaution). Idempotenz via `case.impower_result`.

### Paket-Status

| # | Paket | Status | Artefakte |
|---|---|---|---|
| 1 | Impower Write-API recherchiert | ✓ | `memory/reference_impower_mietverwaltung_api.md` — Anlage-Reihenfolge + DTOs + Pflichtfelder |
| 2 | Datenmodell + Migration + Workflow-Seeding | ✓ | Migration `0008_cases_and_document_types.py`, Model `case.py`, Default-Prompts `DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT` + `DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT` in `claude.py`, Lifespan-Seed in `main.py` (`_DEFAULT_WORKFLOWS`-Tupel) |
| 3 | Case-Entity + Multi-Doc-Upload-UI | ✓ | Router `cases.py` (7 Routen), Templates `cases_list.html` + `case_detail.html`, Nav-Link + Dashboard-Kachel |
| 4 | Extract-Pipeline pro PDF-Typ | ✓ | `app/services/mietverwaltung.py` mit `classify_document` + `extract_for_doc_type` + 5 typ-spezifischen Pydantic-Schemas + `merge_case_state`; BackgroundTask `_run_case_extraction` in `cases.py` haengt beim Upload/Typ-Wechsel/Rerun an; IBAN-Guard auch hier (Unicode-NFKC + schwifty) fuer `mietvertrag.contract.iban` |
| 5 | Form-UI mit Status-Indikatoren | ✓ | `merge_case_state(…, overrides=…)` (einzelne Dict-Sektionen werden feldweise, Listen komplett ueberschrieben). `field_source()` als Jinja-Global liefert pro Feld `state` (`user`/`auto`/`missing`) + optional `doc_type`. 13 Save-Routen in `cases.py` (`/state/property`, `/state/management`, `/state/billing`, `/state/owner`, `/state/buildings/add`, `/state/buildings/{idx}/delete`, `/state/units/add`, `/state/units/{idx}`, `/state/units/{idx}/delete`, `/state/tenant_contracts/add`, `/state/tenant_contracts/{idx}`, `/state/tenant_contracts/{idx}/delete`, `/state/reset/{section}`). `case_detail.html` komplett neu als editierbare Form; 7 Sektionen (Objekt · Verwaltung · Rechnung · Eigentümer · Gebäude · Einheiten · Mietverträge), Status-Pills pro Feld, Pflicht-Counter in der Section-Nav, Override-Reset pro Sektion. |
| 6 | Contact-Create-Workflow | ✓ | `impower.py`: `_build_contact_payload()` (baut ContactLegacyDto) + `check_contact_duplicates()` (`POST /contacts/duplicate`) + `create_contact()` (`POST /contacts`). Neuer Router `contacts.py` mit zwei-Phasen-Flow: (a) `POST /contacts/new` → Duplicate-Check, rendert Warnungen mit bestehenden Treffern + hidden `payload_json`; (b) `POST /contacts/confirm` → tatsächliche Anlage mit dem gespeicherten Payload. `contact_create.html` als Template. Dashboard-Kachel (Violet→Fuchsia-Gradient). Aus Case-Eigentümer-Sektion `<a href="/contacts/new?prefill=<json>&return_to=/cases/{id}">`; nach erfolgreicher Anlage Redirect zurück mit `?contact_created_id=…&contact_created_name=…`. |
| 7 | Impower-Write-Pfad | ✓ | Neuer Service `app/services/mietverwaltung_write.py`. Orchestrator `run_mietverwaltung_write(case_id)` laeuft als BackgroundTask (eigene DB-Session, `asyncio.run` fuer den httpx-Flow). 8 Schritte, jeder idempotent: `_write_owner_contact` → `_write_tenant_contacts` → `_write_property` (POST minimal) → `_write_property_owner_contract` (POST /contracts als Array mit `type=PROPERTY_OWNER`) → `_write_property_details` (PUT /properties mit `creditorId`, `supervisorName`, `accountantName`, `contractStartDate`, `dunningFeeNet`, `billingAddress`, `ownerContractId`, `buildings[]` inline) → `_write_units` (POST-Array, pro Einheit `unitType`, `floor`, `position`, `livingArea`, `heatingArea`, `persons`) → `_write_tenant_contracts` (TENANT-Contracts, POST-Array) → `_write_exchange_plans` (1 Plan pro Vertrag mit `templateExchanges[]` für COLD_RENT / OPERATING_COSTS / HEATING_COSTS, sonst TOTAL_RENT-Fallback) → `_write_deposits` (POST /plan/manual/deposit, `bankOrderState=NOT_NEEDED`). Idempotenz pro Schritt via `case.impower_result` — vorhandene IDs werden ueberprungen; Retry nach Fehler setzt an der letzten unvollstaendigen Stelle an. `preflight()` prueft Pflichtfelder (property.number/street/postal_code/city, owner.last_name|company_name, ≥1 unit) vor dem Start. `POST /cases/{id}/write` im Router. UI zeigt Live-Status mit Meta-Refresh alle 6 s, Success-Block (Property-ID, Contact-ID, Counts), Fehler-Block mit letzten 3 Errors + „Erneut ausfuehren"-Button. |
| 8 | Chat-Unterstützung im Formular | ✓ | Migration `0009_chat_messages_case_id.py` (document_id nullable + case_id FK). `chat_about_case()` in `mietverwaltung.py` bekommt Workflow + Case-State (ohne `_extractions`, um Prompt-Groesse zu begrenzen) + Docs-Summary (`filename`/`doc_type`/`status`) + Historie + neue User-Message. Prompt (konstant `CASE_CHAT_PROMPT`) fordert Delta-Patch: nur geänderte Sektionen im `overrides`-Block. `_extract_case_patch()` parst Codefence-JSON, validiert via `CasePatch`-Pydantic, schneidet Patch aus der Text-Antwort. IBAN-Guard fuer `tenant_contracts[].contract.iban`. `POST /cases/{id}/chat` im Router (HTMX): persistiert User+Assistant-Message, appliziert Patch (Dict-Sektionen feldweise merge, Listen-Sektionen ersetzen), ruft `_recompute_case_state_and_status`. Rendert `_case_chat_panel.html`-Fragment zurueck (HTMX ersetzt `#case-chat-panel`). Chat-Drawer ist fixed unten rechts, im `case_detail.html` per `{% include %}`. |

### Was schon live ist (nach Paket 8)

- Sidebar-Layout: **Dashboard · Workflows · Admin** + User-Block unten, Active-State mit emerald-Border, single-workflow-Bereiche (SEPA, Mietverwaltung, Kontakt-Anlage) **nicht** in der Sidebar.
- Dashboard-Kacheln mit Gradient-Icon-Header: SEPA (Sky→Indigo) + Mietverwaltung (Emerald→Teal) + Kontakt-Anlage (Violet→Fuchsia).
- `/cases/` listet Mietverwaltungs-Fälle, „+ Neuer Fall"-Button.
- `/cases/{id}`: Multi-Doc-Upload, editierbare Form-UI mit Status-Pills pro Feld, Gebäude/Einheiten/Mietverträge-Listen editierbar, „Nach Impower übertragen"-Button (BackgroundTask mit Live-Status), Chat-Drawer mit Delta-Patch-Agent.
- `/contacts/new`: Kontakt-Anlage-Form mit Duplicate-Check-Flow; aus Case-Eigentümer mit Prefill aufrufbar.
- `/workflows/` zeigt drei Workflows (SEPA, Mietverwaltung, Kontakt anlegen) mit identischer Edit-Maske.

### Architektur-Entscheidungen

- **Ein Fall = n Dokumente**: Neue Tabelle `cases` als Container. `documents.case_id` ist **nullable**, damit SEPA-Workflow unverändert bleibt. `documents.doc_type` ebenfalls nullable.
- **`case.state` als JSONB** enthält drei konzeptionelle Layer: (a) `_extractions` = Rohdaten pro Doc (Provenance), (b) Auto-Merge-Werte aus `merge_case_state()`, (c) `_overrides` = User-Edits. Beim Rendern gewinnt `_overrides` > Auto-Merge. `field_source()` liefert für jedes Feld im Template den Layer zurueck (Pill erkannt/manuell/leer). Pro Document bleiben die `extractions`-Rows pro Claude-Call bestehen; der Merge-Service baut aus ihnen + den Overrides den konsolidierten State neu auf.
- **Dict-Sektionen vs. List-Sektionen bei Overrides**: flache Sektionen (`property`, `management_contract`, `billing_address`, `owner`) werden **feldweise** gemerged — User kann einzelne Felder überschreiben, der Rest kommt weiterhin aus der Auto-Merge. Listen (`buildings`, `units`, `tenant_contracts`) werden **komplett** ersetzt, sobald der User sie bearbeitet (Bootstrap beim ersten Edit kopiert die aktuelle Auto-Liste in `_overrides`).
- **`contact_create` als eigener Workflow**: Wird aus Mietverwaltung heraus als Sub-Flow aufgerufen (für Eigentümer-Neuanlage) und ist auch standalone nutzbar (eigene Dashboard-Kachel). Eigener `key` + Seed + editierbarer Prompt.
- **Mieter-Contacts im Write-Flow automatisch**: Paket 7 legt Mieter-Contacts ohne User-Intervention an. Der Contact-Create-Sub-Workflow (Paket 6) ist explizit **nicht** in die Write-Pipeline eingebunden — er bleibt dem Eigentümer-Fall + manuellen Ad-hoc-Anlagen vorbehalten.
- **Prompts pro Doc-Typ im Code, nicht als separate Workflows**: `mietverwaltung_setup.system_prompt` ist ein Koordinator-/Meta-Prompt; die typ-spezifischen Extract-Prompts (verwaltervertrag, grundbuch, mietvertrag, mieterliste, sonstiges) sind Code-Konstanten in `app/services/mietverwaltung.py`. Wenn der User später pro Typ im UI tunen will, erweitern wir das Workflow-Model um `extraction_prompts: JSONB` (Dict `{doc_type: prompt}`).
- **Case-Chat liefert Delta-Patches, kein Full-JSON**: anders als der SEPA-Chat (Backlog-Punkt 5) gibt der Case-Chat nur geänderte Sektionen zurück; der Server merged sie in `_overrides`. Damit ist die Fehleroberfläche bei langen Ziffernfolgen viel kleiner, und der Prompt bleibt unter Token-Budget.
- **Default-Modelle**: `claude-opus-4-7` für Extract, `claude-sonnet-4-6` für Chat (beides via `DEFAULT_MODEL` / `DEFAULT_CHAT_MODEL` bei Seed). Pro Workflow in der DB editierbar.

### Offene fachliche Fragen

- **Exchange-Plan-Schema** (Miet-Positionen, Paket 7): MVP legt einen Exchange-Plan pro Mietvertrag mit einem `templateExchanges[]`-Array an, das je einen Eintrag für COLD_RENT / OPERATING_COSTS / HEATING_COSTS enthält (Fallback: TOTAL_RENT als Einzel-Eintrag). Schema-seitig nicht bestätigt — wenn Impower 400/422 wirft, muss die Granularität umgebaut werden (Alternativen: 1 Plan pro Position, oder 1 Plan mit Summen-Eintrag plus Splits über `counterpartInstruction`). Entscheidung fällt beim ersten realen Write.
- **IBAN-Wechsel-Szenario** (aus M3 SEPA) ist auch für Mietverwaltungs-Lastschriften relevant, falls ein Mieter mit aktivem Mandat die Bank wechselt. Handler noch nicht implementiert (siehe ebenfalls „Offene Punkte für M3").
- **Mieter-SEPA-Mandate im Write-Flow**: Wenn im Mietvertrag eine IBAN erkannt wird (`tenant_contracts[].contract.iban`), legt der Write-Pfad aktuell **kein** Mandat an — der User muss Mieter-Lastschriften manuell in Impower nachziehen. Für den Produktiv-Rollout nachträglich aufnehmen (Muster vorhanden via SEPA-Schreibpfad).

### UI-Umbau: Sidebar statt Top-Nav (2026-04-20)

- `base.html`: dunkles Sidebar-Panel links (`bg-slate-900`, `w-60`) mit Logo oben, Nav-Einträgen (**Dashboard · Workflows (bei Permission) · Admin (bei Permission)**), User-Block unten (Avatar, Name, Email, Logout-Link). Active-State über `request.url.path`-Prüfung mit emerald-Border links (`border-l-2 border-emerald-400`).
- Einzelne Workflows (SEPA `/documents/`, Mietverwaltung `/cases/`) stehen **nicht** in der Sidebar — Zugang nur über Dashboard-Kacheln. Hintergrund: User-Wunsch „Verknüpfung auf das Dashboard, nicht oben in die Menüleiste". Neue Workflows tauchen automatisch als Kachel auf, sobald sie geseedet sind **und** der User die passende Workflow-Resource-Access-Permission hat.
- `index.html`: Kacheln-Grid (`md:grid-cols-2 lg:grid-cols-3`) mit Gradient-Header pro Workflow, Icon, Titel, Beschreibung, „Öffnen →"-Pfeil. „aktiv"-Badge oben rechts. Generische Fallback-Kachel für weitere Workflow-Keys fehlt noch — derzeit hardcoded `if wf.key == "sepa_mandate" … elif "mietverwaltung_setup"`; bei weiteren Workflows muss `index.html` erweitert oder auf generische Kachel umgestellt werden.

## Backlog — übergreifende Themen (meilensteinunabhängig)

Sammelstelle für Anforderungen, die quer zu den Modulen liegen. Werden beizeiten zu eigenen Meilensteinen hochgezogen.

1. **Rollen & Rechte für Logins.** Aktuell darf jeder eingeloggte `@dbshome.de`-User alles (Upload, Extraktion, Approve, Workflow-Prompt editieren). Ziel: mindestens zwei Stufen — Standard-User (Upload + Chat + Approve auf eigene Docs) und Admin (alles, inkl. Workflow-Konfiguration, fremde Docs, Log-Einsicht). Umsetzung: `role`-Spalte am `User`-Model (`user` / `admin`), FastAPI-Dependency `require_admin`, Navigation blendet Admin-Bereiche nur bei Berechtigung ein. Offen: feinere Rechte pro Workflow nötig oder reicht Zwei-Stufen-Modell?
2. **Admin-Log / Audit-Trail sichtbar machen.** Heute: implizites Audit nur über `uploaded_by_id`, `created_at`, `last_login_at`. Fehlt: expliziter Event-Log (Login, Upload, Extract-Start/-Ende, Chat-Message, Approve, Workflow-Edit) mit `user_id`, `event_type`, `target_type`, `target_id`, `payload` (JSONB), `created_at`. UI: `/admin/logs` mit Filter nach User / Event / Zeitraum. Nutzen: Nachvollziehbarkeit bei Reklamationen + Grundlage für Pflicht-Doku gegenüber Datenschutz.
3. **Datenschutz-Prüfung Anthropic-Upload.** PDFs enthalten Klarnamen, Adressen, IBANs — personenbezogene Daten + Bankdaten im Sinne DSGVO Art. 4. Werden derzeit an Anthropic API (US-Unternehmen) geschickt. Zu klären: (a) AVV mit Anthropic vorhanden und unterschrieben? (b) Zero-Data-Retention / kein Training auf unseren Daten vertraglich bestätigt? (c) EU-Datenresidenz möglich (Anthropic EU-Endpoint oder via AWS Bedrock eu-central-1)? (d) DSFA erforderlich? (e) Information der Betroffenen über Drittland-Übermittlung geregelt? Fallback-Optionen falls rechtlich nicht tragfähig: Anonymisierung vor Upload (IBAN + Name maskieren, nur zur Feld-Extraktion), lokales Modell (Ollama / vLLM auf eigener Hardware), On-Premise-Deployment. Entscheidung vor Produktiv-Rollout auf `dashboard.dbshome.de` zwingend.
4. **Zentraler User-Chat + Notification-Hub (Idee).** Statt pro Dokument einen isolierten Chat und pro Workflow eigene UIs: ein persistenter Chat-Kanal pro angemeldetem User als zentrale Anlaufstelle. Dort landen (a) System-Events aller Workflows ("Lastschrift von Tilker erkannt", "Mandat in Impower eingetragen", "Matching uneindeutig — bitte prüfen"), (b) proaktive Rückfragen der Agenten, (c) freie User-Nachrichten an den Bot. Jede Nachricht referenziert ihr Quelldokument / Workflow via Chip mit Deep-Link. Datenmodell: `chat_messages` um `user_id` (Owner-Kanal) und `kind` (`user` / `assistant` / `system_notification`) erweitern, `document_id` bleibt nullable FK für Referenz. UI: Sidebar oder Bottom-Drawer, global in `base.html`, Realtime via SSE oder HTMX-Polling. Offene Fragen: (i) ersetzt der zentrale Chat den Doc-Chat oder laufen beide parallel (Doc-Chat für tiefe Korrekturen, zentral als Feed)? (ii) wie routet der Bot Kontext — letzte erwähnte Doc-ID als "aktiver Fokus", oder explizites `@doc-123`-Tagging? (iii) Notification-Retention / Markieren-als-gelesen nötig?
5. **Chat-Korrekturen als Delta statt Full-JSON.** **Für den Case-Chat (M5 Paket 8) bereits umgesetzt** — `chat_about_case()` in `services/mietverwaltung.py` fordert nur geänderte Sektionen im `overrides`-Block und mergt sie server-seitig. Offen: der SEPA-Chat (`chat_about_mandate()` in `services/claude.py`) schickt weiterhin das komplette Extraction-JSON zurück. Bei nächster größerer SEPA-Runde analog umbauen.
6. **IBAN-/BIC-Registry-Aktualität.** `schwifty` liefert die BLZ→BIC-Zuordnung aus einem gebundelten Datenfile, das je nach Version mehrere Monate alt sein kann. Bundesbank aktualisiert die offizielle BLZ-Datei quartalsweise. Risiko: neue Banken / Fusionen → BIC-Derivation fällt bei seltenen BLZ durch (Fallback ist dann „BIC im Chat ergänzen"). Mögliche Maßnahmen: (a) regelmäßiges `pip install -U schwifty` im CI, (b) eigener BLZ-Import-Job gegen Bundesbank-Feed, (c) Fallback-Chain User-Feedback → Service-Desk. Aktuell low prio, aber dokumentieren vor Produktiv-Rollout.
7. **OCR-/LLM-Robustheit bei Ziffernfolgen.** Claude hat in der Session IBANs beim Extract und beim Chat-Rewrite verkantet (einmal komplett andere BLZ, einmal Ziffern-Drop am Ende, einmal Zero-Width-Space). Heute abgedeckt: Schwifty-Validierung + Unicode-Normalize + Chat-Guard. Offen: proaktive Plausibilitätsprüfung beim Initial-Extract (IBAN gültige Prüfziffer + bekannte BLZ → `high`, sonst Confidence runter). Ferner: bei mehrfach hintereinander abgelehnten Chat-Korrekturen automatisch auf das nächstgrößere Modell eskalieren (Sonnet → Opus), falls Sonnet die Korrektur wiederholt verkantet.

## Externe Blocker

- **GitHub-Push**: User macht manuell. Remote: `git@github.com:dakroxy/dashboard-ai-agents.git`.
- **Elestio-Projekt**: noch nicht angelegt (M4).
- **DNS bei All-Inkl**: `dashboard.dbshome.de` noch nicht angelegt (M4).

## Design-Regeln (verbindlich, vom User vorgegeben)

- **Dateinamen von Scans sind NICHT als Info-Quelle nutzen.** Auch wenn das aktuelle Benennungsschema strukturiert wirkt, ist es nicht verlässlich. Nur der PDF-Inhalt zählt. (Im Prompt verankert.)
- **Pflichtfelder**: Objekt (WEG-Kürzel oder WEG-Name+Adresse), Eigentümer-Name, IBAN. Fehlt eines → `needs_review`, nicht blocken, nicht still ablehnen.
- **Einheit ist optional** (`unit_nr` darf null sein).
- **Bei Problemen fragt der Bot im Chat nach**, statt automatisch zu entscheiden.
- **Zwei Formular-Varianten**: neues Impower-Template mit "Objekt-Nr." und "Einheits-Nr.", und älteres DBS-Formular ohne diese Felder. Prompt liest beide robust.

## Vorgehen und Defaults

- User will Tempo, keine überlangen Erklärungen.
- Prototyp wurde bewusst übersprungen — direkt Produktivcode.
- Bei offensichtlichen Defaults nicht zurückfragen, direkt machen und transparent melden.
- Risiko-Actions (Force-Push, destruktiv, shared state) weiterhin nur mit Rückfrage.
- Sprache im Chat: Deutsch; Code-Kommentare und Commit-Messages: Deutsch oder Englisch egal, aber konsistent pro Datei.

## Referenzen

- **Vorgängerprojekt (Nightly-Check-Skript)**: `/Users/daniel/Desktop/Vibe Coding/Impower Lastschrift/` — komplette Impower-API-Doku in dessen `CLAUDE.md`, funktionierende Calls in `impower_lastschrift_check.py`, Ausgabe-CSV zur Referenz.
- **Beispiel-Mandate** (zum Testen): `/Users/daniel/Downloads/OneDrive_1_18.4.2026/` (3 PDFs: Flögel HAM61, Tilker GVE1, Kulessa BRE11). Flögel wurde bereits erfolgreich extrahiert.
- **Gläubiger-IDs** (aus den Beispielen): HAM61 → `DE71ZZZ00002822264`, BRE11 → `DE37ZZZ00000481199`.
- **Mockup Mietverwaltungs-Eingabemaske**: `mockups/mietverwaltung_setup.html` — standalone HTML-Prototyp des Formulars mit Status-Indikatoren, Multi-Doc-Tabs, Kontakt-Sub-Workflow-Hinweis; wird in Paket 5 als `case_detail.html` umgesetzt.
- **UI-Vorbild Sidebar-Layout**: `/Users/daniel/Desktop/KI Workshop Screenshots/Dashboard - KI Mitarbeiter.png` (vom User vorgegeben).
- **Impower-Swagger-Specs**: `GET https://api.app.impower.de/services/pmp-accounting/v2/api-docs` (Write, 358 Pfade, Swagger 2.0) und `GET https://api.app.impower.de/v2/api-docs` (Read). Beide **ohne Auth abrufbar**, JSON als Quelle der Wahrheit für DTOs + Pflichtfelder.
- **GitHub-Repo**: `git@github.com:dakroxy/dashboard-ai-agents.git`.
- **Produktiv-URL (geplant)**: `https://dashboard.dbshome.de`.
