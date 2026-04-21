# Component-Inventar

Keine komponentenbasierte Frontend-Architektur im klassischen Sinne (kein React/Vue). Stattdessen **Jinja2-Templates + HTMX-Fragmente**. Diese Datei listet beides zusammen mit den Service-/Router-Modulen.

## Jinja2-Templates

Alle in `app/templates/`. Tailwind via CDN (siehe `base.html`).

### Layout / Chrome

| Datei | Zweck |
|---|---|
| `base.html` | Sidebar-Layout (Dashboard / Workflows / Admin + User-Block unten). Active-State per `request.url.path`. Ohne Login → nur Main ohne Sidebar (Login-Page rendered in `index.html`). |
| `index.html` | Dashboard mit Workflow-Kacheln. Gradients **hardcoded** per `wf.key`: `sepa_mandate` Sky→Indigo, `mietverwaltung_setup` Emerald→Teal, `contact_create` Violet→Fuchsia. Neue Workflows brauchen aktuell eine Extension hier. |
| `_macros.html` | `status_pill(status)` — farbige Badges pro Status-String. |

### SEPA-Modul

| Datei | Zweck |
|---|---|
| `documents_list.html` | Tabelle + Upload-Form. |
| `document_detail.html` | Side-by-side: PDF-iframe links (`#view=FitH&pagemode=none` fuer Chrome PDF-Viewer), Extraktions- und Chat-Block rechts. Grid `lg:grid-cols-[1.7fr_1fr]`. |
| `_extraction_block.html` | HTMX-Polling-Fragment (`hx-trigger="every 2s"` waehrend `uploaded`/`extracting`). Zeigt Extraction + Approve-Button + Matching-Status + Impower-Result. Ziel fuer OOB-Swap aus `_chat_response.html`. |
| `_chat_block.html` | Chat-Historie + Form. Send via HTMX. |
| `_chat_response.html` | Antwort-Fragment. Enthaelt optional OOB-Swap auf `#extraction-block`, wenn Claude eine aktualisierte Extraktion geliefert hat. |

### Mietverwaltungs-Modul

| Datei | Zweck |
|---|---|
| `cases_list.html` | Fall-Liste mit „+ Neuer Fall"-Button + Doc-Counts. |
| `case_detail.html` (1019 Zeilen) | Form-UI mit 7 Sektionen: Objekt · Verwaltung · Rechnung · Eigentuemer · Gebaeude · Einheiten · Mietvertraege. Status-Pills pro Feld via `field_source(...)`-Global. Write-Button + Live-Status (Meta-Refresh alle 6 s waehrend `writing`). Chat-Drawer via `{% include "_case_chat_panel.html" %}`. Fuer den Eigentuemer-Block gibt es einen Button `/contacts/new?prefill=<json>&return_to=/cases/{id}` → ruft den Sub-Workflow mit Vorbefuellung auf. |
| `_case_chat_panel.html` | Chat-Drawer fixed unten rechts. HTMX-Target `#case-chat-panel`, wird bei `POST /cases/{id}/chat` ersetzt. |

### Kontakt-Anlage

| Datei | Zweck |
|---|---|
| `contact_create.html` | Formular + Duplicate-Check-Warnung + Bestaetigen-Flow. Success-Message bei Anlage ohne `return_to`. Error-Message bei Impower-Fehler. |

### Workflow-Konfiguration

| Datei | Zweck |
|---|---|
| `workflows_list.html` | Uebersicht der drei Workflows. |
| `workflow_edit.html` | Prompt + Modell + Lernnotizen editierbar. Dropdown aus `AVAILABLE_MODELS` in `app/services/claude.py`. |

### Admin

| Datei | Zweck |
|---|---|
| `admin/home.html` | Landing mit Counts + recent logs. |
| `admin/users_list.html` · `user_edit.html` | User-Verwaltung; `user_edit.html` hat Permission-Matrix (extras/denied) + Workflow-Override-Select (default/allow/deny). |
| `admin/roles_list.html` · `role_edit.html` | Rollen-CRUD. |
| `admin/logs.html` | Gefilterte Audit-Log-Ansicht. |

## FastAPI-Router

`app/routers/`. Zahlen in Klammern = LOC.

| Router | Prefix | Groesse | Key-Routen |
|---|---|---|---|
| `auth.py` | `/auth` | 144 | `/google/login`, `/google/callback`, `/logout` |
| `documents.py` | `/documents` | 760 | Upload + Detail + Approve + Chat + Status-Fragment + File-Inline |
| `cases.py` | `/cases` | 1697 | Case-CRUD + 12 `state/*`-Routen + Write-Trigger + Case-Chat |
| `contacts.py` | `/contacts` | 359 | Contact-Create 2-Phasen-Flow |
| `workflows.py` | `/workflows` | 114 | Workflow-Edit |
| `impower.py` | `/impower` | 124 | Debug: health, properties, contracts, match (JSON) |
| `admin.py` | `/admin` | 698 | User/Roles CRUD + Audit-Log |

## Services

`app/services/`. Ohne Router-Abhaengigkeit, mit eigenen DB-Sessions fuer BackgroundTasks.

| Datei | Groesse | Oeffentliche API |
|---|---|---|
| `audit.py` | 63 | `audit(db, user, action, *, entity_type, entity_id, document_id, details, request, user_email)` |
| `claude.py` | 533 | `extract_mandate_from_pdf`, `chat_about_mandate`, Konstanten `DEFAULT_MODEL`/`DEFAULT_CHAT_MODEL`/`AVAILABLE_MODELS`/`DEFAULT_SYSTEM_PROMPT`/`DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT`/`DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT`, Helper `prompt_version_for` |
| `mietverwaltung.py` | 1375 | `classify_document`, `extract_for_doc_type`, `merge_case_state(extractions, overrides)`, `field_source(case_state, section, field)`, `chat_about_case` |
| `mietverwaltung_write.py` | 780 | `preflight(case_state) -> WritePreflight`, `run_mietverwaltung_write(case_id)` (BackgroundTask-Entry) |
| `impower.py` | 928 | Read: `load_properties`, `load_owner_contracts`, `load_all_contacts`, `load_unit_contract_mandates`, `health_check`; Matching: `match_property`, `match_contact_in_property`, `run_full_match`; Write: `write_sepa_mandate` + internals `_api_get/_api_post/_api_put`, `_ensure_bank_account`, `_normalize_iban`, `_derive_bic_from_iban`; Contact: `_build_contact_payload`, `check_contact_duplicates`, `create_contact` |

## Cross-Cutting-Module

| Datei | Zweck |
|---|---|
| `app/config.py` | `settings` Singleton (pydantic-settings). |
| `app/db.py` | `engine`, `SessionLocal`, `Base`, `get_db()` FastAPI-Dependency. |
| `app/auth.py` | OAuth-Client + `get_current_user` / `get_optional_user`. |
| `app/permissions.py` | Permission-Registry, `has_permission`, `effective_permissions`, `require_permission(key)` / `require_any_permission(*keys)`, `can_access_workflow`, `accessible_workflow_ids`. |
| `app/templating.py` | `templates` Singleton. Globals: `has_permission`, `field_source`. Filter: `iban_format` (gruppiert IBAN in 4er-Blocks fuer Anzeige). |

## Erweiterungs-Leitfaden

### Neuen Workflow hinzufuegen

1. System-Prompt-Konstante in `app/services/claude.py` (oder eigener Service, wenn multi-step).
2. Workflow-Eintrag in `main.py:_DEFAULT_WORKFLOWS`.
3. Optional: neuer Router + Template.
4. Dashboard-Kachel in `app/templates/index.html` ergaenzen (`if wf.key == "..."`-Block).
5. Migration fuer neue Tabellen, falls noetig.

### Neue Permission

1. `Permission(...)` in `app/permissions.py:PERMISSIONS` anhaengen.
2. Default-Rollen-Permissions in `DEFAULT_ROLE_PERMISSIONS` ergaenzen, wenn initial vergeben.
3. `require_permission("...")` in Router-Handler einsetzen.

### Neuer Resource-Type

1. Konstante `RESOURCE_TYPE_XYZ = "xyz"` in `app/permissions.py`.
2. `can_access_resource(db, user, RESOURCE_TYPE_XYZ, resource_id)` in Handler nutzen.
3. Admin-UI (`user_edit.html` / `role_edit.html`) ggf. um neuen Ressourcen-Typ erweitern.
