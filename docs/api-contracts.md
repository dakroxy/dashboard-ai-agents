# API-Contracts

Vollstaendige Liste aller HTTP-Routen. Permissions sind soweit moeglich als FastAPI-Dependency dokumentiert; wo dort `get_current_user` steht, wird ein angemeldeter User verlangt und zusaetzliche Permissions werden im Handler selbst geprueft.

Alle UI-Routes geben `text/html` zurueck (Jinja2-Template oder HTMX-Fragment). Debug-JSON-Endpoints sind markiert.

## Auth (`/auth`)

| Methode | Pfad | Handler | Zweck |
|---|---|---|---|
| GET  | `/auth/google/login` | `auth.google_login` | OAuth-Redirect an Google, forciert `hd=dbshome.de` + `prompt=select_account`. |
| GET  | `/auth/google/callback` | `auth.google_callback` | Token-Tausch, User anlegen/aktualisieren, `@dbshome.de`-Gate, Default-Rolle (admin wenn in `INITIAL_ADMIN_EMAILS`, sonst `user`), Session-Cookie setzen. |
| GET  | `/auth/logout` | `auth.logout` | Session clear + Audit-Log. |

## Dashboard / Health

| Methode | Pfad | Handler | Permission | Zweck |
|---|---|---|---|---|
| GET  | `/` | `main.index` | optional User | Workflow-Kachel-Dashboard (gefiltert per `accessible_workflow_ids`). |
| GET  | `/health` | `main.health` | — | `{"status": "ok", "env": "..."}` fuer Docker-/Elestio-Healthcheck. |

## Documents — SEPA Single-Doc-Flow (`/documents`)

| Methode | Pfad | Handler | Permission (Zusatz-Check im Handler) | Zweck |
|---|---|---|---|---|
| GET  | `/documents/` | `list_documents` | `get_current_user` + Workflow-Access; Non-`documents:view_all`-User sieht nur eigene | Listen aller Docs fuer zugaengliche Workflows. |
| POST | `/documents/` | `upload_document` | `documents:upload` + Workflow-Access | PDF-Upload (content-type + size + `%PDF`-Header validiert), `sha256`-basierter Speicherpfad (`{sha}.pdf`), `Document`-Row, BackgroundTask `_run_extraction`. |
| GET  | `/documents/{id}` | `document_detail` | Owner oder `documents:view_all` | Detail-Seite: PDF-iframe links, Extraktion + Chat rechts. |
| POST | `/documents/{id}/approve` | `approve_document` | `documents:approve` | Nur aus `_APPROVABLE_STATUSES` (`extracted` / `needs_review` / `matched` / `error`). Status `approved`, BackgroundTask `_run_write`. |
| POST | `/documents/{id}/chat` | `chat` | Owner oder `documents:view_all` | Chat-Message + Claude-Call. Response = `_chat_response.html`-Fragment + optional OOB-Swap der Extraktion. Chat-Korrekturen resetten Matching/Write-Status. |
| GET  | `/documents/{id}/status` | `document_status_fragment` | Owner oder `documents:view_all` | HTMX-Polling waehrend `uploaded`/`extracting`. |
| GET  | `/documents/{id}/file` | `document_file` | Owner oder `documents:view_all` | PDF inline (`Content-Disposition: inline; filename*=UTF-8''...`). |

## Cases — Mietverwaltung (`/cases`)

### Fall-Lifecycle

| Methode | Pfad | Handler | Zweck |
|---|---|---|---|
| GET  | `/cases/` | `list_cases` | Workflow-gated. Fall-Liste mit Doc-Counts. |
| POST | `/cases/` | `create_case` | `documents:upload`. Legt leeren Case an (state `{}`, status `draft`) → Redirect auf Detail. |
| GET  | `/cases/{id}` | `case_detail` | Editierbare Form-UI mit 7 Sektionen + Chat-Drawer + Write-Button. |
| POST | `/cases/{id}/name` | `rename_case` | Umbenennen. |

### Dokumente im Fall

| Methode | Pfad | Handler | Zweck |
|---|---|---|---|
| POST | `/cases/{id}/documents` | `upload_case_document` | PDF hochladen, optional `doc_type` setzen. Triggert BackgroundTask `_run_case_extraction`. |
| POST | `/cases/{id}/documents/{doc_id}/type` | `set_document_type` | `doc_type` nachtraeglich setzen/aendern. Wechsel triggert Re-Extract. |
| POST | `/cases/{id}/documents/{doc_id}/extract` | `rerun_document_extraction` | `documents:upload`. Extract-Pipeline fuer ein einzelnes Dokument manuell neu. |
| POST | `/cases/{id}/documents/{doc_id}/delete` | `delete_case_document` | `documents:delete`. Entfernt Dokument (und kaskadiert Extractions). |
| GET  | `/cases/{id}/documents/{doc_id}/file` | `case_document_file` | PDF inline. |

### State-Editor (Paket 5)

Alle `state/*`-Routen pruefen `_require_case_edit` (`documents:upload`) und rufen am Ende `_recompute_case_state_and_status(db, case)`. Redirect an `/cases/{id}#sec-<anchor>`.

| Methode | Pfad | Sektion | Semantik |
|---|---|---|---|
| POST | `/cases/{id}/state/property` | `property` | Feldweise Override. Leere Felder → Override entfernen (fallback auf Auto). |
| POST | `/cases/{id}/state/management` | `management_contract` | Feldweise. `dunning_fee_net` wird als float geparst (Komma oder Punkt). |
| POST | `/cases/{id}/state/billing` | `billing_address` | Bei `is_same_as_owner=true` werden abweichende Adress-Felder verworfen. |
| POST | `/cases/{id}/state/owner` | `owner` | `type` zwangsnormalisiert auf `PERSON` / `COMPANY` / `MANAGEMENT_COMPANY`. |
| POST | `/cases/{id}/state/buildings/add` | `buildings` | Append Eintrag (Bootstrap aus Auto-Liste beim ersten Edit). Duplikat-Namen werden nicht doppelt eingefuegt. |
| POST | `/cases/{id}/state/buildings/{idx}/delete` | `buildings` | Loescht Eintrag an Index. |
| POST | `/cases/{id}/state/units/add` | `units` | Append. Leere `number` → Redirect ohne Aenderung. |
| POST | `/cases/{id}/state/units/{idx}` | `units` | Edit an Index. `unit_type` zwangsnormalisiert. |
| POST | `/cases/{id}/state/units/{idx}/delete` | `units` | Loescht Eintrag. |
| POST | `/cases/{id}/state/tenant_contracts/add` | `tenant_contracts` | Append. |
| POST | `/cases/{id}/state/tenant_contracts/{idx}` | `tenant_contracts` | Edit. `source_doc_id` aus vorherigem Eintrag wird erhalten. |
| POST | `/cases/{id}/state/tenant_contracts/{idx}/delete` | `tenant_contracts` | Loescht Eintrag. |
| POST | `/cases/{id}/state/reset/{section}` | alle | Verwirft die Override einer Sektion → zurueck auf Auto-Erkennung. |

### Write + Chat

| Methode | Pfad | Handler | Zweck |
|---|---|---|---|
| POST | `/cases/{id}/write` | `trigger_mietverwaltung_write` | `documents:upload`. Preflight-Check (Pflichtfelder) → BackgroundTask `run_mietverwaltung_write`. |
| POST | `/cases/{id}/chat` | `case_chat` | `documents:upload`. HTMX. User-Message persistieren → `chat_about_case` → optional Delta-Patch anwenden → Assistant-Message persistieren → Recompute → `_case_chat_panel.html`-Fragment zurueck. |

## Contacts — Sub-Workflow (`/contacts`)

| Methode | Pfad | Handler | Zweck |
|---|---|---|---|
| GET  | `/contacts/new` | `new_contact_form` | `documents:upload` + Workflow-Access `contact_create`. Leeres Formular oder mit `?prefill=<json>&return_to=...` vorbefuellt. |
| POST | `/contacts/new` | `check_and_confirm_contact` | Phase 1: minimale Validierung (entweder `last_name` oder `company_name`), `_build_contact_payload` → `check_contact_duplicates` → Formular mit Duplicate-Warnungen + hidden `payload_json`. |
| POST | `/contacts/confirm` | `confirm_create_contact` | Phase 2: `payload_json` direkt aus Hidden-Field → `create_contact`. Redirect an `return_to` mit `?contact_created_id=...&contact_created_name=...`. |

## Workflows (`/workflows`)

| Methode | Pfad | Handler | Permission | Zweck |
|---|---|---|---|---|
| GET  | `/workflows/` | `list_workflows` | `workflows:view` | Uebersicht aller Workflows. |
| GET  | `/workflows/{key}` | `edit_workflow` | `workflows:view` | Formular. |
| POST | `/workflows/{key}` | `update_workflow` | `workflows:edit` | Update `name`/`description`/`model`/`chat_model`/`system_prompt`/`learning_notes`. Validiert `model` gegen `AVAILABLE_MODELS`. |

## Impower — Debug-/Read-API (`/impower`) — JSON

Alle hinter `impower:debug` (Admin).

| Methode | Pfad | Handler | Zweck |
|---|---|---|---|
| GET  | `/impower/health` | `impower_health` | Connectivity-Test gegen Impower. |
| GET  | `/impower/properties` | `list_properties` | Kompakte Property-Liste. |
| GET  | `/impower/contracts` | `list_owner_contracts` | Anzahl OWNER-Vertraege. |
| POST | `/impower/match` | `match_extraction` | Body: `{weg_kuerzel?, weg_name?, weg_adresse?, owner_name?}` → Property-Match + Contact-Match + ambiguous-Flag. |

## Admin (`/admin`)

| Methode | Pfad | Handler | Permission | Zweck |
|---|---|---|---|---|
| GET  | `/admin` | `admin_home` | `users:manage` ODER `audit_log:view` | Landing mit Counts + recent logs. |
| GET  | `/admin/users` | `list_users` | `users:manage` | User-Liste. |
| GET  | `/admin/users/{id}` | `edit_user` | `users:manage` | User-Formular: Rolle, extra/denied Permissions, Workflow-Overrides (default/allow/deny pro Workflow). |
| POST | `/admin/users/{id}` | `update_user` | `users:manage` | Update. Wenn derselbe Key in extra UND denied → denied gewinnt. |
| POST | `/admin/users/{id}/disable` | `disable_user` | `users:manage` | `disabled_at` + `disabled_by_id` setzen. Self-disable blockiert. |
| POST | `/admin/users/{id}/enable` | `enable_user` | `users:manage` | `disabled_at=None`. |
| GET  | `/admin/roles` | `list_roles` | `users:manage` | |
| GET  | `/admin/roles/new` | `new_role_form` | `users:manage` | |
| POST | `/admin/roles` | `create_role` | `users:manage` | Key-Regex `^[a-z][a-z0-9_]{1,63}$`. Permissions + Workflow-Zuweisungen. |
| GET  | `/admin/roles/{id}` | `edit_role` | `users:manage` | |
| POST | `/admin/roles/{id}` | `update_role` | `users:manage` | Sync von Permissions + Workflow-Assignments (diff added/removed). |
| POST | `/admin/roles/{id}/delete` | `delete_role` | `users:manage` | System-Rollen nicht loeschbar; Rolle mit aktiven Usern nicht loeschbar. |
| GET  | `/admin/logs` | `list_logs` | `audit_log:view` | Filter `user_email`, `action`, `from`, `to` (ISO). Limit 500. |
| POST | `/admin/logs/{id}/delete` | `delete_log` | `audit_log:delete` | Einzel-Log loeschen; schreibt `audit_entry_deleted`-Eintrag. |

## Static

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/static/*` | FastAPI `StaticFiles(directory="app/static")`. Aktuell leer ausser `.gitkeep`. |

## Konventionen

- **Redirects** nach POST: `HTTP_303_SEE_OTHER` (Post-Redirect-Get-Pattern).
- **HTMX-Fragments**: `_chat_response.html`, `_extraction_block.html`, `_case_chat_panel.html` — eigenstaendige HTML-Snippets, die HTMX per `hx-target`/`hx-swap` einbettet.
- **Permission-Failure**: 403 mit `detail="Keine Berechtigung: {key}"`. Uncaught → kein Redirect an Login; fuer fehlende Session wirft `get_current_user` einen 302 an `/auth/google/login`.
- **Upload-Gates** (wiederverwendet in `/documents/` und `/cases/{id}/documents`):
  - `content_type ∈ {"application/pdf"}` (400 sonst).
  - `size > 0` (400 sonst).
  - `size ≤ MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024` (413 sonst).
  - `content.startswith(b"%PDF")` (400 sonst).
