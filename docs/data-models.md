# Datenmodell

Postgres 16 via SQLAlchemy 2.0 (typed `Mapped[...]`). UUID als Primaerschluessel ueberall. `JSONB` fuer flexible Payloads.

Alembic-Migrations sind linear `0001 → 0009` (siehe unten). Die aktuelle ORM-Definition ist in `app/models/*.py`.

## Tabellen-Uebersicht

| Tabelle | Modell | Zweck |
|---|---|---|
| `users` | `app.models.user.User` | Google-Workspace-User + Rolle + Permission-Overrides + Disable-Flag. |
| `roles` | `app.models.role.Role` | Rolle mit Permission-Liste. System-Rollen (admin/user) vs custom. |
| `resource_access` | `app.models.resource_access.ResourceAccess` | Role- oder User-spezifischer allow/deny auf `(resource_type, resource_id)`. |
| `documents` | `app.models.document.Document` | PDF-Meta + Status + JSONB-Ergebnisse + optional Case-Zuordnung + Doc-Typ. |
| `extractions` | `app.models.extraction.Extraction` | Pro Document n Claude-Extractions (Audit-Trail + Chat-Korrekturen). |
| `chat_messages` | `app.models.chat_message.ChatMessage` | Chat-Historie; entweder `document_id` ODER `case_id` (Constraint im Code). |
| `workflows` | `app.models.workflow.Workflow` | DB-editierbare Workflow-Konfig (Prompt + Modell + Lernnotizen). |
| `cases` | `app.models.case.Case` | Multi-Doc-Container fuer Mietverwaltungs-Anlage. |
| `audit_log` | `app.models.audit_log.AuditLog` | Einheitlicher Event-Log, geschrieben ueber `app.services.audit.audit()`. |

## Beziehungen

```
users ─┬─ role_id ───────────► roles ◄──┐
       └─ documents.uploaded_by_id        │
       └─ cases.created_by_id             │ permissions (list)
                                          │
resource_access.role_id ──────────────────┤
resource_access.user_id ──► users
resource_access.resource_id ──► workflows (resource_type="workflow")

workflows ─┬─ documents.workflow_id
           └─ cases.workflow_id

cases ─► documents.case_id (nullable; SEPA lässt null)

documents ─┬─ extractions.document_id
           └─ chat_messages.document_id (SEPA-Chat)

cases ────► chat_messages.case_id (Case-Chat)

extractions ◄── chat_messages.extraction_id (Link zur durch die Chat-Antwort erzeugten Extraction)

audit_log.user_id    ──► users.id (nullable)
audit_log.document_id ──► documents.id (Legacy-FK, primaer fuer SEPA-Fälle; andere
                           Entities via entity_type/entity_id seit Migration 0007)
```

## `users`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `google_sub` | String, unique, indexed | Stabil, primaerer Lookup beim Login. |
| `email` | String, unique, indexed | |
| `name`, `picture` | String | |
| `role_id` | UUID FK `roles.id` ON DELETE SET NULL, nullable | User ohne Rolle hat keine Permissions. |
| `permissions_extra` | JSONB `list[str]` | Zusatz-Permissions zur Rollen-Basis. |
| `permissions_denied` | JSONB `list[str]` | Subtrahiert. Denied gewinnt ueber extra. |
| `disabled_at` | Timestamp tz, nullable | Disabled-User kommen weder durch Login noch durch `get_current_user`. |
| `disabled_by_id` | UUID FK `users.id` ON DELETE SET NULL, nullable | |
| `created_at`, `last_login_at` | Timestamp tz | |

## `roles`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `key` | String, unique, indexed | `admin`, `user`, …custom. |
| `name` | String | |
| `description` | Text | |
| `permissions` | JSONB `list[str]` | Permission-Keys (siehe `app/permissions.py:PERMISSIONS`). |
| `is_system_role` | Boolean | System-Rollen koennen nicht geloescht werden; Key bleibt stabil. |
| `created_at`, `updated_at` | Timestamp tz | |

Seed beim App-Start (`_seed_default_roles` in `main.py`): `admin` = alle Permissions, `user` = `[documents:upload, documents:view_all, documents:approve, workflows:view]`. Existierende Rollen werden **nicht** mit neuen Permissions ueberschrieben (Admin-UI-Aenderungen bleiben erhalten).

## `resource_access`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `role_id` | UUID FK `roles.id` ON DELETE CASCADE, nullable | **Genau eines** von `role_id`/`user_id` gesetzt (Constraint im Code). |
| `user_id` | UUID FK `users.id` ON DELETE CASCADE, nullable | |
| `resource_type` | String | Aktuell nur `workflow`. |
| `resource_id` | UUID | Verweist auf `workflows.id` (kein FK wegen Polymorphismus). |
| `mode` | String | `allow` oder `deny`. |
| `created_at` | Timestamp tz | |

Seed: `_seed_default_workflow_access` gibt admin + user `allow` fuer alle Default-Workflows.

## `workflows`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `key` | String, unique, indexed | `sepa_mandate`, `mietverwaltung_setup`, `contact_create`. |
| `name`, `description` | String/Text | |
| `model` | String | Erkennungs-/Extraktions-Modell (Anthropic). Default `claude-opus-4-7`. |
| `chat_model` | String, server_default `claude-sonnet-4-6` | Chat-Modell separat wegen Praezisions-Anforderung. |
| `system_prompt` | Text | |
| `learning_notes` | Text | Wird bei jedem Call ans Prompt angehaengt. |
| `active` | Boolean | |
| `created_at`, `updated_at` | Timestamp tz | |

## `documents`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `uploaded_by_id` | UUID FK `users.id` ON DELETE RESTRICT, indexed | |
| `workflow_id` | UUID FK `workflows.id` ON DELETE RESTRICT, indexed | |
| `original_filename` | String | |
| `stored_path` | String | `{sha256}.pdf` unter `settings.uploads_dir`. Deduplication. |
| `content_type`, `size_bytes` | String/Integer | |
| `sha256` | String(64), indexed | |
| `status` | String, default `uploaded` | Lifecycle siehe unten. |
| `matching_result` | JSONB, nullable | Dict `{property, contact, ambiguous, notes}`. |
| `impower_result` | JSONB, nullable | `WriteResult.as_dict()` — IDs + Flags + Error. |
| `case_id` | UUID FK `cases.id` ON DELETE CASCADE, indexed, nullable | Mietverwaltung setzt den Container; SEPA laesst null. |
| `doc_type` | String, nullable | `verwaltervertrag` / `grundbuch` / `mietvertrag` / `mieterliste` / `sonstiges`; null fuer SEPA. |
| `uploaded_at` | Timestamp tz | |

### Status-Lifecycle (`Document.status`)

**SEPA-Flow**:
```
uploaded (Upload-Handler)
  → extracting (BackgroundTask start)
    → extracted | needs_review | failed  (Claude-Result)
      → matching (automatisch bei extracted)
        → matched | needs_review
          → approved (User-Click)
            → writing
              → written | already_present | error
```

**Mietverwaltung-Flow** (Doc-Level):
```
uploaded → extracting → extracted | needs_review | failed
```
Case-Level-Status rollup in `_recompute_case_state_and_status`:
- irgendein Doc `uploaded`/`extracting` → Case `extracting`
- mindestens ein Doc `extracted` → Case `ready_for_review`
- User triggert Write → Case `writing`
- Write-Ende → Case `written` | `partial` | `error`

Chat-Korrekturen resetten SEPA-Doc-Status: `matched`/`needs_review`/`error`/`written`/`already_present` → `extracted` und loeschen `matching_result`+`impower_result`, damit Re-Matching sauber durchlaeuft.

## `extractions`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK `documents.id` ON DELETE CASCADE, indexed | |
| `model` | String | Claude-Modell aus dem Response. |
| `prompt_version` | String | `{workflow.key}-{sha256(prompt+notes)[:8]}`; bei Chat mit `-chat`-Suffix, bei Mietverwaltung mit `-{doc_type}`-Suffix. |
| `raw_response` | Text, nullable | Kompletter Text-Response. |
| `extracted` | JSONB, nullable | Gemaess Pydantic-Schema (SEPA: `MandateExtraction`; Mietverwaltung: 5 Doc-Typ-Schemas). |
| `status` | String | `ok` / `needs_review` / `failed`. |
| `error` | Text, nullable | |
| `created_at` | Timestamp tz | |

Neue Row bei **jedem** erfolgreichen Chat-Update. Der Case-Merge liest pro Doc die neueste Row mit `status in {"ok", "needs_review"}`.

## `chat_messages`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK `documents.id` ON DELETE CASCADE, indexed, nullable | SEPA-Chat. |
| `case_id` | UUID FK `cases.id` ON DELETE CASCADE, indexed, nullable | Case-Chat (seit Migration 0009). |
| `role` | String | `user` oder `assistant`. |
| `content` | Text | |
| `extraction_id` | UUID FK `extractions.id` ON DELETE SET NULL, nullable | Link zur durch diese Chat-Antwort erzeugten Extraction (nur SEPA). |
| `created_at` | Timestamp tz | |

Constraint **im Code, nicht in der DB**: genau eines von `document_id`/`case_id` gesetzt. Der Router validiert implizit (`/documents/{id}/chat` setzt `document_id`, `/cases/{id}/chat` setzt `case_id`).

## `cases`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `workflow_id` | UUID FK `workflows.id` ON DELETE RESTRICT, indexed | Aktuell nur `mietverwaltung_setup`. |
| `created_by_id` | UUID FK `users.id` ON DELETE RESTRICT, indexed | |
| `name` | String, nullable | User-gesetzt oder null. |
| `status` | String, default `draft` | `draft` → `extracting` → `ready_for_review` → `writing` → `written` / `partial` / `error`. |
| `state` | JSONB, default `{}` | siehe Struktur unten. |
| `impower_result` | JSONB, nullable | Pro Schritt IDs + Logs. |
| `created_at`, `updated_at` | Timestamp tz | |

### `case.state`-Struktur

```jsonc
{
  // Dict-Sektionen (feldweise Override):
  "property": {
    "number": "SBA9", "name": null, "street": "...",
    "postal_code": "...", "city": "...", "country": "DE",
    "creditor_id": "DE71ZZZ00002822264",
    "land_registry_district": "...", "folio_number": "..."
  },
  "management_contract": {
    "management_company_name": "DBS Home GmbH",
    "supervisor_name": "...", "accountant_name": "...",
    "contract_start_date": "2024-01-01", "contract_end_date": null,
    "dunning_fee_net": 5.00
  },
  "billing_address": {
    "is_same_as_owner": true, "street": null, "postal_code": null, "city": null
  },
  "owner": {
    "type": "PERSON"|"COMPANY"|"MANAGEMENT_COMPANY",
    "salutation": "...", "title": "...",
    "first_name": "...", "last_name": "...",
    "company_name": "...", "trade_register_number": "...",
    "street": "...", "postal_code": "...", "city": "...", "country": "DE"
  },

  // Listen-Sektionen (Override ersetzt komplett):
  "buildings": [{"name": "Block F"}],
  "units": [{
    "number": "1", "unit_type": "APARTMENT"|"COMMERCIAL"|"PARKING"|"OTHER",
    "building_name": "Block F", "floor": "EG", "position": "links",
    "living_area": 78.5, "heating_area": 78.5, "persons": 2,
    "tenant_name": "...", "cold_rent": 900.0,
    "operating_costs": 150.0, "heating_costs": 80.0
  }],
  "tenant_contracts": [{
    "source_doc_id": "<uuid>",
    "unit_number": "1",
    "tenant": { /* _TenantBlock */ },
    "contract": { /* _ContractBlock inkl. iban/bic + deposit */ },
    "_partial": true  // wenn nur aus Mieterliste abgeleitet
  }],

  // Meta-Layer:
  "_extractions": {
    "<doc_id>": {"doc_type": "verwaltervertrag", "data": {...}, "status": "ok"}
  },
  "_overrides": {
    "property":            {feld: wert},
    "management_contract": {feld: wert},
    "billing_address":     {feld: wert},
    "owner":               {feld: wert},
    "buildings":           [...],
    "units":               [...],
    "tenant_contracts":    [...]
  }
}
```

### `case.impower_result`-Struktur (nach Write-Pfad)

```jsonc
{
  "contacts": {
    "owner_id": 12345,
    "tenants": { "<tenant_key>": 12346 }  // key = unit_number oder source_doc_id
  },
  "property_id": 9876,
  "property_owner_contract_id": 555,
  "property_update_ok": true,
  "building_ids": [101, 102],
  "building_name_to_id": { "Block F": 101, "Block B": 102 },
  "unit_ids": { "1": 5001, "2": 5002 },
  "tenant_contract_ids": { "1": 601 },
  "exchange_plan_ids": { "1": 701 },
  "deposit_ids": { "1": 801 },
  "steps_completed": ["owner_contact", "tenant_contacts", "property_create", …],
  "errors": [
    {"step": "units", "message": "...", "timestamp": "2026-04-21T12:34:56Z"}
  ]
}
```

## `audit_log`

| Feld | Typ | Hinweis |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK `users.id` ON DELETE SET NULL, indexed, nullable | Null bei System-Events (z.B. BackgroundTask-Logs). |
| `user_email` | String | Kopie, damit Einträge lesbar bleiben wenn der User gelöscht wird. |
| `action` | String, indexed | z.B. `document_approved`, `case_state_saved`, `login`. |
| `entity_type` | String, nullable | `document`, `case`, `user`, `workflow`, `role`, `contact`, `audit_log` (seit 0007). |
| `entity_id` | UUID, nullable | UUID der betroffenen Entity. |
| `document_id` | UUID FK `documents.id` ON DELETE CASCADE, indexed, nullable | Legacy-FK primär für SEPA-Aktionen. |
| `ip_address` | String(45), nullable | X-Forwarded-For vorrangig (Reverse-Proxy). |
| `details_json` | JSONB, nullable | Event-spezifischer Payload. |
| `created_at` | Timestamp tz, indexed | |

Alle Writes laufen ueber `app.services.audit.audit(db, user, action, ...)`. Commit durch den Caller, damit Audit-Eintrag + Geschäfts-Change in einer Transaktion sind.

## Migrations-Historie

Linear, in `migrations/versions/`:

| Revision | Datei | Inhalt |
|---|---|---|
| `0001` | `0001_initial.py` | `users` + `documents` + `extractions`. |
| `0002` | `0002_chat_messages.py` | `chat_messages` (nur `document_id`). |
| `0003` | `0003_workflows.py` | `workflows`. |
| `0004` | `0004_audit_log_and_document_results.py` | `audit_log` + `documents.matching_result` + `documents.impower_result`. |
| `0005` | `0005_workflow_chat_model.py` | `workflows.chat_model`. |
| `0006` | `0006_roles_and_resource_access.py` | `roles` + `resource_access` + `users.role_id`/`permissions_extra`/`permissions_denied`/`disabled_at`/`disabled_by_id`. |
| `0007` | `0007_audit_log_generic.py` | `audit_log.entity_type` + `audit_log.entity_id` (+ `user_id` wurde generalisiert). |
| `0008` | `0008_cases_and_document_types.py` | `cases` + `documents.case_id` + `documents.doc_type`. |
| `0009` | `0009_chat_messages_case_id.py` | `chat_messages.case_id` + `document_id` nullable. |

`alembic upgrade head` laeuft als erstes Kommando beim Container-Start (`Dockerfile` CMD).
