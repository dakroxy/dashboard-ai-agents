# Test-Automatisierung — Zusammenfassung

**Datum:** 2026-04-21
**Skill:** `bmad-qa-generate-e2e-tests`
**Scope:** M3 SEPA-Write-Pfad, M5 Mietverwaltungs-Write-Pipeline, Case-Merge/Override, Permissions-Matrix

## Ergebnis

**203 Tests gruen / 0 rot** (vorher: 86 gruen / 15 rot aus bestehender Suite).

- 102 neue Tests in 4 neuen Testdateien.
- 15 pre-existing Fails in `test_upload.py` + `test_routes_smoke.py` wurden als kollateraler Fix mitgezogen (conftest + 2 Upload-Test-Updates).

## Strategie-Hinweis

Bewusst **keine Playwright-/Browser-E2E-Tests** — das Projekt ist server-rendered HTMX + Jinja, ohne npm/build-Step. Integration laeuft sauber via FastAPI-`TestClient` mit SQLite-In-Memory-DB und Mocks fuer Anthropic + Impower. Entscheidung ist in `project_testing_strategy` in der Memory abgelegt; Playwright wird neu bewertet, sobald echte Client-JS-Logik dazukommt (z. B. Drag-&-Drop-Upload).

## Neue Testdateien

### `tests/test_impower_write.py` — M3 SEPA-Write-Pfad (28 Tests)

Deckt den Schreib-Pfad zur Impower-API. Alle HTTP-Calls gemockt.

- **IBAN-Normalize:** Whitespace, Unicode-ZWSP (U+200B), Tab, NBSP, Case — Haertung gegen Sonnet-Zero-Width-Spaces.
- **`_strip_server_fields`:** Entfernung der serverseitig-verwalteten Bank-Account-Felder vor PUT (Impower wirft sonst 400).
- **`_derive_bic_from_iban`:** schwifty-BLZ-Ableitung bei valider/invalider IBAN.
- **`_build_contact_payload`:** Pflichtfeld-Normalisierung, Empty-Filter, Type-Fallback.
- **`write_sepa_mandate` Idempotenz-Zweig:** bestehendes BOOKED-Mandat → `already_present=True`, keine POSTs.
- **`write_sepa_mandate` Neuanlage-Zweig (bisher nicht live verifiziert, Backlog M3 Punkt 1):** `GET Contact → PUT Contact mit gestrippten Server-Feldern → GET Mandate → POST Mandat ohne state-Feld → POST UCM als Array` — exakte Reihenfolge + Payload-Form abgesichert.
- **BIC-Ableitung bei leerem BIC:** schwifty greift, BIC landet im PUT-Payload.
- **Fehlerpfade:** ungueltige IBAN stoppt vor jedem API-Call; unbekannte BLZ ohne User-BIC liefert klaren Fehler, ohne PUT/POST.

### `tests/test_mietverwaltung_merge.py` — Case-State-Merge (33 Tests)

- **Property/Owner/Buildings/Units/Tenant-Contracts:** typ-spezifische Merge-Regeln pro Doc-Typ.
- **Prioritaets-Reihenfolge:** Verwaltervertrag > Grundbuch > Mieterliste > Mietvertrag fuer Property-Felder; Owner nur aus Grundbuch; Buildings nur aus Mieterliste.
- **Tenant-Fallback aus Mieterliste,** wenn kein eigener Mietvertrag existiert (`_partial=True`).
- **Dict-Sektion-Override:** feldweise-Merge (User-Wert > Auto-Wert, Rest bleibt).
- **Listen-Sektion-Override:** Komplett-Ersetzen (buildings/units/tenant_contracts).
- **Owner-Override mit leerem Dict** setzt Owner auf `None` (Use-Case: User waehlt anderen Contact).
- **`field_source`:** Provenance-Layer `user` > `auto(doc_type)` > `auto` > `missing`.

### `tests/test_mietverwaltung_write.py` — M5 Write-Pipeline (19 Tests)

Volle 8-Schritt-Pipeline mit gemocktem Impower.

- **`preflight`:** Pflichtfeld-Reporting fuer property/owner/units.
- **`_ensure_impower_result`:** Initialisierung und Preserve bei Replay.
- **`_tenant_key`:** Prioritaet `unit_number` > `source_doc_id`.
- **Happy-Path `_write_all_steps`:** Sequenz `Owner-Contact → Tenants → Property → PROPERTY_OWNER-Contract → PUT Property+Buildings → Units-Array → TENANT-Contracts-Array → Exchange-Plan pro Mieter → Deposits-Array`. IDs werden korrekt in `impower_result` abgelegt.
- **Payload-Struktur:** Array-POST fuer PROPERTY_OWNER-Contract, Units, TENANT-Contracts, Deposits.
- **Exchange-Plan-Split:** Kaltmiete + Betriebskosten + Heizkosten als einzelne `templateExchanges[]`-Positionen; Fallback auf `TOTAL_RENT` wenn nur Summe gesetzt.
- **Deposit nur bei gesetztem Betrag:** Mieter ohne `deposit`-Feld wird uebersprungen.
- **Idempotenz-Replay:** zweiter Durchlauf mit bereits besetzten IDs macht **keinen einzigen** API-Call.
- **Partielles Replay:** Owner bereits angelegt → nur Tenant-Contacts werden nachgezogen.
- **Fehlerpfad:** `ImpowerError` aus einem Zwischenschritt wird sauber geworfen; bereits angelegte Entitaeten bleiben im `impower_result`.
- **Fehlende Unit-ID** blockt nicht die Pipeline — der zugehoerige TENANT-Contract wird geskippt, Rest laeuft.

### `tests/test_permissions.py` — Permission-Matrix (22 Tests)

Pro Router-Gate: `unauth → 302/307`, `auth ohne Perm → 403`, `auth mit Perm → 200`.

- **Admin-Dashboard:** `users:manage` ODER `audit_log:view` (require_any_permission).
- **/admin/users, /admin/roles:** nur `users:manage`.
- **/admin/logs:** nur `audit_log:view` — `users:manage` allein reicht **nicht**.
- **/impower/health, /impower/properties, /impower/contracts:** `impower:debug`.
- **/workflows/:** `workflows:view`.
- **POST /workflows/{key}:** `workflows:edit` (view allein → 403).
- **Edge-Cases:** `permissions_denied` schlaegt `permissions_extra`; `disabled_at != None` setzt effective_permissions auf leer.

## Angepasste bestehende Dateien

### `tests/conftest.py`

- `test_user` bekommt Default-Perms der `user`-Rolle (`documents:upload`, `documents:view_all`, `documents:approve`, `workflows:view`) per `permissions_extra`. Vorher hatte er gar keine Perms — alle permission-gated Routen waren unter Tests unerreichbar.
- `auth_client`-Fixture legt ResourceAccess-Allow-Eintraege fuer alle nach Lifespan-Seed existierenden Workflows an. Vorher hatte der User keinen Resource-Zugriff → `can_access_workflow` = False → 403 beim Upload/Approve.
- `Role` + `ResourceAccess`-Model in Base.metadata importiert (sonst faehrt `create_all` die Tabellen nicht hoch).

### `tests/test_upload.py`

- `_create_doc`-Helper in `TestApproveRoute` setzt jetzt `workflow_id` aus dem geseedeten `sepa_mandate`-Workflow. Vorher NULL → IntegrityError (workflow_id ist seit M2+ NOT NULL).
- `test_other_users_document_returns_404` umgebaut: testet jetzt explizit einen User **ohne** `documents:view_all`-Recht. Der Default-`test_user` hat das Recht mittlerweile und darf fremde Docs sehen — das war vorher eine semantische Luecke in der Test-Intention.
- Audit-Action-String im `approve`-Test von `"approve"` auf `"document_approved"` korrigiert (Rename aus frueherer Runde).

## Coverage

- **M3 SEPA-Schreibpfad:** Idempotenz-Zweig **und** Neuanlage-Zweig code-seitig abgesichert. Der Live-Test von Tilker (GVE1) / Kulessa (BRE11) aus Backlog M3 bleibt weiter ausstehend — die Unit-Tests bestaetigen nur die Struktur, nicht die Impower-Akzeptanz.
- **M5 Mietverwaltungs-Write:** Alle 8 Schritte + Idempotenz + Partial-Fail abgedeckt. Der Live-Test aus Backlog M5 bleibt ausstehend — insbesondere der Exchange-Plan-Step (`templateExchanges[]`-Granularitaet), der laut Code-Kommentar unsicher ist bis zum ersten realen POST.
- **Permissions-System:** Kern-Gates durchgetestet; Role-Vererbung ueber `role.permissions` nicht separat — aber durch `require_permission` + `effective_permissions` indirekt abgedeckt.

## Naechste Schritte (empfohlen, nicht umgesetzt)

1. **Live-Tests M3 Neuanlage** (Tilker / Kulessa) und **M5 Full-Case** gegen Impower Prod-Tenant. Die Unit-Tests sichern nur die Code-Form, nicht die Server-Akzeptanz.
2. **Case-Router-Tests (`/cases/*`):** Routen-Ebene fuer Case-Anlage, Doc-Upload, State-Patches. Aktuell nur die darunterliegende Service-Logik getestet.
3. **Chat-Delta-Patch-Tests (`chat_about_case`):** IBAN-Guard und Patch-Parse separat absichern, wenn naechste Aenderung am Case-Chat ansteht.
4. **Migration-Smoke-Tests:** heute keine — falls in der naechsten Revision Postgres-spezifische Konstrukte breaken koennen, lohnt sich ein minimaler Alembic-Upgrade-Downgrade-Test gegen SQLite.

## Run-Command

```bash
docker compose exec app python -m pytest
# 203 passed, 3 warnings in ~0.6s
```
