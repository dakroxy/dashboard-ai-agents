# Architektur — Dashboard KI-Agenten

**Projekt-Typ**: Backend (FastAPI/Python) mit server-gerendertem UI (Jinja2 + HTMX).
**Repository-Typ**: Monolith, ein Part.
**Stand**: 2026-04-21.

## Executive Summary

Die App ist ein klassischer Python-Monolith mit folgenden Schichten:

1. **Web-Schicht** (`app/routers/*`) — FastAPI-Router pro Domain (`auth`, `documents`, `cases`, `contacts`, `workflows`, `impower`, `admin`). Haelt HTTP-I/O, Form-Validation, Permission-Checks, Template-Rendering oder JSON-Response.
2. **Service-Schicht** (`app/services/*`) — Geschaefts-Logik und externe Integrationen. Keine HTTP-Kenntnis, keine Request-Objekte.
3. **Daten-Schicht** (`app/models/*`, `app/db.py`) — SQLAlchemy-2.0-Modelle, Postgres-JSONB fuer flexible Payloads.
4. **Cross-Cutting** — `app/auth.py` (OAuth), `app/permissions.py` (Rollen + Resource-Access), `app/services/audit.py` (AuditLog), `app/templating.py` (Jinja-Globals/Filter), `app/config.py` (pydantic-settings).

Architektur-Pattern: **Layered + Service-oriented**. Kein DDD im engeren Sinne — Geschaeftslogik lebt in flachen Service-Modulen, die direkt mit ORM-Modellen arbeiten.

## 1. Permission-Modell

Zweistufig:

### Flache Permissions (strings)

Registriert in `app/permissions.py:PERMISSIONS`. Aktuell 10 Keys:

- **Dokumente**: `documents:upload`, `documents:view_all`, `documents:approve`, `documents:delete`
- **Workflows**: `workflows:view`, `workflows:edit`
- **Admin**: `users:manage`, `audit_log:view`, `audit_log:delete`, `impower:debug`

Aufloesung pro User: `Role.permissions ∪ User.permissions_extra \ User.permissions_denied`.

Dependency-Helfer:
```python
@router.get(..., user = Depends(require_permission("documents:upload")))
@router.get(..., user = Depends(require_any_permission("users:manage", "audit_log:view")))
```

### Resource-Access (UUID-basiert)

Tabelle `resource_access` verknuepft entweder `user_id` ODER `role_id` mit `(resource_type, resource_id, mode)`. `resource_type` aktuell nur `workflow` (per Konstante `RESOURCE_TYPE_WORKFLOW`), Design erlaubt spaeter `object`, `task`, `crm_lead`.

Aufloesung: **User-Overrides gewinnen ueber Role-Defaults**. `User-deny` > `User-allow` > `Role-allow` > kein Zugriff. Helfer: `can_access_resource`, `accessible_resource_ids`, `can_access_workflow`, `accessible_workflow_ids`.

Dashboard-Kacheln sind per `accessible_workflow_ids(db, user)` gefiltert — ein neuer Workflow taucht automatisch auf, wenn der User Zugriff hat.

### Bootstrap

- Lifespan-Seed in `app/main.py`: `_seed_default_roles` (admin + user mit Default-Permissions), `_seed_default_workflow_access` (beide Rollen bekommen allow fuer alle Default-Workflows).
- Erste Login-Rolle: Bei `OAuth-Callback` wird `initial_admin_emails` aus `settings` gegen die Login-E-Mail geprueft → Admin, sonst `user`. Siehe `app/routers/auth.py:google_callback`.

## 2. Workflow-Konfiguration in der DB

Tabelle `workflows` (Model `app.models.workflow.Workflow`):

- `key`: unique string (`sepa_mandate`, `mietverwaltung_setup`, `contact_create`).
- `model` / `chat_model`: Anthropic-Modell-String. Separat, weil Extraktions-Qualitaet (Opus) und Chat-Praezision (Sonnet) unterschiedlich bewertet werden — Haiku scheitert empirisch an IBAN-Reproduktion in freier JSON-Ausgabe.
- `system_prompt`: der komplette System-Prompt (editierbar per UI).
- `learning_notes`: Freitext, wird bei jedem Call ans Prompt angehaengt (`_compose_system_prompt`).
- `active`: Flag.

Lifecycle: `_seed_default_workflow` in `main.py` laufen beim App-Start und legen die drei Default-Workflows an, falls sie fehlen. **User-Aenderungen werden nie ueberschrieben**.

Die Extract- und Chat-Services lesen den aktuellen DB-Stand bei jedem Call — kein In-Memory-Cache.

## 3. SEPA-Modul (Single-Doc-Flow)

**Router**: `app/routers/documents.py` (760 Zeilen).
**Service**: `app/services/claude.py` (Extract + Chat), `app/services/impower.py` (Match + Write).
**Modelle**: `Document`, `Extraction`, `ChatMessage`.
**Workflow**: `sepa_mandate`.

### Lifecycle `Document.status`

```
uploaded → extracting → extracted / needs_review / failed
          → matching  → matched / needs_review
          → approved (User-Freigabe)
          → writing   → written / already_present / error
```

Chat-Korrekturen (mit gueltiger IBAN-Validierung) resetten Status auf `extracted` und loeschen `matching_result`/`impower_result` damit Re-Matching sauber durchlaeuft.

### BackgroundTask-Kette

1. `upload_document` → speichert File via SHA-256-Hash → `_run_extraction(doc.id, workflow.id, user.id, user.email)`.
2. `_run_extraction` → `extract_mandate_from_pdf` → persistiert `Extraction`-Row → bei `ok` direkt `_run_matching` im selben Thread.
3. `_run_matching` → `run_full_match(extraction.extracted)` → setzt `matching_result` und Status auf `matched`/`needs_review`.
4. User klickt "Freigeben" → `approve_document` → Status `approved` → `_run_write` als BackgroundTask.
5. `_run_write` → `run_full_match` nochmal (Chat-Korrekturen beruecksichtigen) → `write_sepa_mandate`:
   a. `_ensure_bank_account` (GET+PUT Contact mit erweitertem `bankAccounts[]`).
   b. Idempotenz-Check: `GET /direct-debit-mandate?propertyId=X`, Filter auf `{bankAccountId, state: "BOOKED"}`. Treffer → `already_present=True`, kein POST.
   c. `_create_direct_debit_mandate` (ohne `state`-Feld; Impower setzt Status selbst).
   d. `_create_unit_contract_mandates` (einzelner POST mit Array statt Loop).

Alle Schritte mit 120 s Timeout + 5xx-Exponential-Backoff (2/5/15/30/60 s, max 5 Versuche) in `_api_get` / `_api_post` / `_api_put`.

### IBAN-Guard (mehrfach)

- `app/services/claude.py:chat_about_mandate` — neue IBAN aus Chat-Korrektur wird via `unicodedata.normalize("NFKC", ...)` + `isalnum()` gesaeubert (Zero-Width-Spaces u.a.) und per `schwifty.IBAN` validiert BEVOR sie als Extraction persistiert wird. Ungueltig → Korrektur verworfen, `[Hinweis]`-Block in der Chat-Antwort.
- `app/services/impower.py:_normalize_iban` / `_ensure_bank_account` — gleiche Normalisierung beim Write-Pfad.

### BIC-Derivation

`_derive_bic_from_iban(iban)` nutzt `schwifty.IBAN(iban).bic`. Moderne SEPA-Mandate drucken oft keinen BIC mehr, Impower besteht aber auf gueltigem BIC beim Contact-PUT. Wenn die BLZ im schwifty-Register unbekannt ist → ImpowerError, User muss im Chat nachreichen.

## 4. Mietverwaltungs-Modul (Multi-Doc-Case-Flow)

**Router**: `app/routers/cases.py` (1697 Zeilen — groesste Datei).
**Services**: `app/services/mietverwaltung.py` (Classify + Extract + Merge + Case-Chat, 1375 Zeilen) und `app/services/mietverwaltung_write.py` (Orchestrator, 780 Zeilen).
**Modelle**: `Case` + wiederverwendete `Document`, `Extraction`, `ChatMessage`.
**Workflow**: `mietverwaltung_setup`.

### Modell

Ein `Case` bundelt n `Document`-Zeilen (via `documents.case_id`). Jedes Dokument bekommt einen `doc_type` (`verwaltervertrag` | `grundbuch` | `mietvertrag` | `mieterliste` | `sonstiges`); SEPA-Docs lassen beide Felder null.

`case.state` (JSONB) enthaelt drei konzeptionelle Layer:

```
{
  "property":            {...}          # flache Dict-Sektion
  "management_contract": {...}
  "billing_address":     {...}
  "owner":               {...}
  "buildings":           [...]          # Listen-Sektion
  "units":               [...]
  "tenant_contracts":    [...]

  "_extractions": {                      # Provenance pro Doc
    "<doc_id>": {"doc_type": "...", "data": {...}, "status": "ok"}
  },
  "_overrides": {                        # User-Edits
    "property": {feld: wert},            # feldweise ueber Auto
    "buildings": [...]                   # komplette Liste ersetzt Auto
  }
}
```

Die sichtbare Sektion wie `state.property` wird per `merge_case_state()` aus `_extractions` gebaut, anschliessend vom `_overrides`-Layer ueberschrieben. `field_source(case_state, section, field)` liefert dem Template den Layer zurueck (`user` / `auto` / `missing` + optional `doc_type`) fuer die Status-Pills.

### Pipeline: Upload → Extract → Merge

Handler `upload_case_document` → BackgroundTask `_run_case_extraction(case_id, doc_id)`:

1. Wenn `doc.doc_type` leer → `classify_document(pdf_bytes, workflow)` (Chat-Modell, JSON-Response `{doc_type, confidence, reason}`).
2. `extract_for_doc_type(pdf_bytes, workflow, doc_type)` — typ-spezifischer Prompt (`PROMPT_VERWALTERVERTRAG` / `_GRUNDBUCH` / `_MIETVERTRAG` / `_MIETERLISTE` / `_SONSTIGES`) + Pydantic-Schema (`VerwaltervertragExtraction`, etc.). IBAN-Guard auf `contract.iban` nur fuer Mietvertrag.
3. Persistiert neue `Extraction`-Row, setzt `doc.status` (`extracted` / `needs_review` / `failed`).
4. `_recompute_case_state_and_status(db, case)` baut `case.state` neu aus allen OK/needs_review-Extractions + vorhandenen `_overrides` und rollt Case-Status auf (`extracting` / `ready_for_review` / `draft`).

Typ-Wechsel triggert Re-Extract: `POST /cases/{id}/documents/{doc_id}/type` mit anderem `doc_type` setzt `doc.status="uploaded"` und stoesst `_run_case_extraction` neu an.

### Merge-Semantik

`merge_case_state(extractions, overrides)` in `app/services/mietverwaltung.py:1131`:

- **Property-Block**: Feld-fuer-Feld per `_FIELD_PRIORITY`-Tabelle (z.B. `property.creditor_id` kommt nur aus `verwaltervertrag`, `property.street` kann aus allen vier Doc-Typen kommen, verwaltervertrag gewinnt).
- **management_contract / billing_address**: Nur aus `verwaltervertrag`, `setdefault` pro Feld (erste Quelle gewinnt).
- **owner**: Nur aus `grundbuch`.
- **buildings**: Aus `mieterliste`, eindeutige Namen.
- **units**: Primaer aus `mieterliste` (key: `number`), sekundaer: Mietvertraege mergen Felder rein (kein `None`-Overwrite).
- **tenant_contracts**: Eins pro Mietvertrag-PDF + Fallback aus Mieterliste (`_partial: True`), wenn kein eigener Mietvertrag vorhanden.

Overrides werden zuletzt angewandt: flache Sektionen feldweise gemerged, Listen-Sektionen komplett ersetzt (Bootstrap beim ersten Edit kopiert die Auto-Liste in `_overrides`).

### Impower-Write (8 Schritte)

`run_mietverwaltung_write(case_id)` → `_write_all_steps(state, ir)` in `app/services/mietverwaltung_write.py`:

1. `_write_owner_contact` — POST `/contacts` (Eigentuemer).
2. `_write_tenant_contacts` — POST `/contacts` pro Mieter (ueberspringt Einheiten ohne `last_name`/`company_name`).
3. `_write_property` — POST `/properties` mit Minimal-Feldern (`number`, `name`, `street`, `postalCode`, `city`, `country="DE"`, `administrationType="MV"`).
4. `_write_property_owner_contract` — POST `/contracts` als Array mit `type=PROPERTY_OWNER`.
5. `_write_property_details` — PUT `/properties` mit Detail-Feldern (`creditorId`, `supervisorName`, `accountantName`, `contractStartDate`, `dunningFeeNet`, `billingAddress`, `ownerContractId`, `buildings[]` inline). Extrahiert `building_ids` + `building_name_to_id` aus Response.
6. `_write_units` — POST `/units` Array. Units ohne `building_name` fallen auf `building_ids[0]`, wenn vorhanden.
7. `_write_tenant_contracts` — POST `/contracts` Array mit `type=TENANT` (ueberspringt Mietvertraege, fuer die kein Mieter-Contact oder keine Unit-ID existiert — diese landen in `ir.errors`).
8. `_write_exchange_plans` — POST `/exchange-plan` pro Mietvertrag mit `templateExchanges[]` fuer COLD_RENT / OPERATING_COSTS / HEATING_COSTS. Fallback: `TOTAL_RENT` als Einzel-Eintrag wenn keine Splits vorhanden.
9. `_write_deposits` — POST `/plan/manual/deposit` Array, `bankOrderState="NOT_NEEDED"`.

**Idempotenz**: Jeder Schritt prueft vor dem API-Call, ob die Ziel-ID bereits in `case.impower_result` liegt. Wenn ja → skip. Retry nach Fehler setzt an der letzten unvollstaendigen Stelle an.

**Fehlerbehandlung**:
- Preflight-Check (`preflight(case.state)`) laeuft synchron vor dem BackgroundTask: Pflichtfelder (`property.number`, `.street`, `.postal_code`, `.city`; `owner.last_name|company_name`; ≥1 Unit). Fehlend → 400, User sieht es direkt.
- `ImpowerError` im Flow → Status `partial` wenn mindestens ein Schritt durchgelaufen ist, sonst `error`. Letzte drei Errors werden im Case-Detail angezeigt.
- Unerwartete Exception → Status `error`, Audit-Log `mietverwaltung_write_crashed`.

UI zeigt Live-Status mit `<meta http-equiv="refresh" content="6">` waehrend `case.status == "writing"`.

### Case-Chat

`POST /cases/{id}/chat` → `chat_about_case(workflow, case.state, docs_summary, history, new_user_message)`.

- PDFs werden **nicht** mitgesendet (Cost/Performance) — nur der aktuelle Case-State (ohne `_extractions`, das waere zu gross) plus Doc-Liste (filename, doc_type, status).
- Claude antwortet text + optional JSON-Codeblock mit `{"overrides": {...}}` (Delta-Patch, nicht Full-State).
- Server parst via `CasePatch`-Pydantic, validiert IBAN-Guard auf `tenant_contracts[].contract.iban`, merged in `case.state._overrides` und ruft `_recompute_case_state_and_status`.

Der Chat-Drawer ist in `case_detail.html` via `{% include "_case_chat_panel.html" %}` eingebunden, HTMX ersetzt bei `POST` das `#case-chat-panel`-Fragment.

## 5. Contact-Create Sub-Workflow

**Router**: `app/routers/contacts.py` (359 Zeilen).
**Service**: `_build_contact_payload`, `check_contact_duplicates`, `create_contact` in `app/services/impower.py`.

Zwei-Phasen-Flow:

1. **Phase 1** `POST /contacts/new` → `_build_payload_from_fields` (ContactLegacyDto) → `check_contact_duplicates(payload)` (Impower POST `/contacts/duplicate`). Rendert Formular mit Warnungen + hidden `payload_json`.
2. **Phase 2** `POST /contacts/confirm` mit `payload_json` aus Phase 1 → `create_contact(payload)` → bei Erfolg Redirect an `return_to` mit Query-Params `contact_created_id` + `contact_created_name`.

Aus dem Case-Detail (Eigentuemer-Sektion) wird der Flow mit `?prefill=<json>&return_to=/cases/{id}` aufgerufen.

**Im Mietverwaltungs-Write-Flow wird der Sub-Workflow nicht aufgerufen** — Mieter-Contacts werden in `_write_tenant_contacts` automatisch ohne User-Intervention angelegt.

## 6. Claude-Integration

### Extract (`app/services/claude.py:extract_mandate_from_pdf`)

- PDF als base64-Document-Block + Text-Instruction via `messages.create` (NICHT `messages.parse` — Grammar-Compilation-Timeout bei Optional-lastigen Pydantic-Schemas, siehe `feedback_claude_api_pdf_extraction`-Memory).
- System-Block mit `cache_control: {type: "ephemeral"}` (greift aktuell nicht — Opus 4.7 hat 4096-Token-Mindestlaenge, aktueller Prompt ~1000 Tokens; greift, sobald Prompt + Lernnotizen wachsen).
- Response: Text, gestripped von Codefence, `json.loads`, per Pydantic `MandateExtraction` validiert.
- Status-Heuristik: `owner_name`+`iban`+`weg_kuerzel|weg_name` vorhanden + `confidence != low` → `ok`, sonst `needs_review`.

### Chat (`app/services/claude.py:chat_about_mandate`)

- Multi-Turn: System-Prompt mit `CHAT_PROMPT_APPENDIX` (Regeln fuer Rueckfragen) + ein initiales User-Assistant-Paar mit dem PDF + aktuelle Extraktion + komplette Chat-Historie + neue Message.
- Response enthaelt optional Codefence-JSON-Block mit komplettem neuen Extract (Full-JSON statt Delta — siehe Backlog-Punkt 5). Regex extrahiert, Pydantic validiert, IBAN-Guard, neue `Extraction`-Row persistiert.

### Case-Chat (`app/services/mietverwaltung.py:chat_about_case`)

- Response ist Delta-Patch (`{"overrides": {...}}`) statt Full-JSON. Entschaerft den Prompt-Groessen-Bloat und das Ziffern-Reproduktions-Risiko.

### Prompt-Komposition (`_compose_system_prompt` / `_compose_extract_system_prompt`)

```
workflow.system_prompt
  + (optional) "LERN-NOTIZEN:\n{workflow.learning_notes}"
  + (optional) CHAT_PROMPT_APPENDIX
```

Version-Hash `prompt_version_for(workflow)` = `"{key}-{sha256(prompt+notes)[:8]}"` — landet in `Extraction.prompt_version` fuer Nachvollziehbarkeit.

## 7. Impower-Client-Haertungen

`app/services/impower.py` kapselt:

- **Rate-Limit-Gate** (`_rate_limit_gate`, module-level `asyncio.Lock`): 500 req/min → 0.12 s Mindestabstand zwischen Requests.
- **Timeout + Retry**: 120 s Timeout (Impower-Gateway antwortet empirisch bis 60 s); 5xx + Transport-Errors werden mit Exponential-Backoff (2/5/15/30/60 s) bis max 5 Versuche retriet. 429 → 30 s pause + Retry ohne Counter.
- **Sanitize Error**: HTML-Responses (Upstream-Timeout → Gateway liefert Error-Page) werden auf `"HTTP <code> — Impower-Gateway hat HTML statt JSON geliefert"` gekuerzt, damit Frontend-Errors lesbar bleiben.
- **Spring-Data-Pagination** (`_get_all_paged`): paged durch `{content: [...], last: bool}` oder flache Arrays.
- **Server-managed Fields strippen**: Vor dem PUT `/contacts/{id}` werden `created`, `createdBy`, `updated`, `updatedBy`, `domainId`, `casaviSyncData` aus bestehenden `bankAccounts[]`-Items entfernt (wuerden sonst 400 werfen).

## 8. Audit-Trail

Alle nicht-trivialen Handler schreiben `AuditLog` ueber den zentralen `audit()`-Helper in `app/services/audit.py`:

```python
audit(db, user, "action_name",
      entity_type="case", entity_id=case.id,
      details={...}, request=request)
db.commit()
```

Der Helper setzt `user_id`/`user_email`/`ip_address` (X-Forwarded-For vorrangig, fuer Elestio-Proxy) + fuegt den Eintrag in die Session ein — Commit erfolgt durch den Caller, damit Log + Geschaefts-Change in einer Transaktion landen.

Vollständige Liste: `app/services/audit.py:KNOWN_AUDIT_ACTIONS` — dort autoritativ gepflegt. Das zentrale Write-Gate (`app/services/steckbrief_write_gate.py`, Story 1.2) emittiert drei Actions pro Feld-Write-Pfad: `object_field_updated` (CD1-Haupt-Entitaeten), `registry_entry_updated` (Versicherer, Dienstleister, Bank, Ablesefirma, Eigentuemer, Mieter), und fuer die KI-Freigabe-Pipeline `review_queue_created` / `review_queue_approved` / `review_queue_rejected`.

**Write-Gate-Ausnahmen (CD2):** Object-Row-Creation via Discover-Mirror (`steckbrief_impower_mirror.py:discover_new_objects`) ist eine erlaubte Ausnahme — `db.add(Object(...))` mit NOT-NULL-Pflichtfeldern ist kein Field-Write i.S.d. CD2-Konvention. Row-Creation mit Pflichtfeldern geht direkt in den ORM-Konstruktor; nur nachgelagerte Feld-Updates laufen durch `write_field_human`.

Admin-UI `/admin/logs` filtert nach `user_email`, `action`, Zeitraum.

## 9. Testing

`tests/` mit Pytest + SQLite-In-Memory (StaticPool, in `conftest.py`). `SQLiteTypeCompiler` wird gemonkey-patched, damit JSONB als TEXT und UUID als CHAR(32) DDL-generiert werden. DML nutzt normale JSON/UUID-Typen.

62 Tests verteilt auf:
- `test_claude_unit.py` — Extract/Chat-Unit-Tests (mock Anthropic).
- `test_impower_unit.py` — Matching + Write-Client (mock httpx).
- `test_routes_smoke.py` — Router-Smoke-Tests (unauthenticated → 302/403, health 200).
- `test_upload.py` — Upload-Flow (size, content-type, PDF-Header-Check).

Keine Integrationstests gegen echte Impower-API — die laeuft ausschliesslich gegen den Live-Tenant, ohne Sandbox.

## 10. Deployment-Architektur (aktueller Stand)

```
push origin main
      │
      ▼
GitHub Action docker-build.yml
      │  build + push
      ▼
GHCR: ghcr.io/dakroxy/dashboard-ai-agents:latest
      │  pull
      ▼
Elestio Custom Docker Compose
      │  docker compose up -d (docker-compose.prod.yml)
      ▼
App-Container:
  alembic upgrade head  (beim Start)
  uvicorn app.main:app  --proxy-headers --forwarded-allow-ips=*
      │
      ▼
Elestio Reverse-Proxy → dashboard.dbshome.de (DNS + TLS noch offen — M4)
```

Secrets: Elestio-Env-Variablen. `SECRET_KEY` + `POSTGRES_PASSWORD` muessen frisch generiert sein (nicht Dev-Werte). Google-OAuth-Redirect muss die Prod-URL explizit gewhitelistet haben.

Backup-Volumes: `postgres_data` + `uploads` via Elestio-Backup.
