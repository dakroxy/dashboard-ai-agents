# Facilioo Ticket-API Spike

Datum: 2026-04-30 | Durchgeführt von: Daniel Kroll

---

## Go / No-Go Empfehlung

**Entscheidung: GO**

Begründung: Bearer-Token funktioniert, Ticket-Endpunkt erreichbar (`/api/properties/{facilioo_id}/processes`), Property-Mapping über `externalId` lösbar ohne neue Spalte (dynamischer Lookup), Pagination per `_get_all_paged` wiederverwendbar. Einzige Einschränkung: kein Delta-Support → Full-Pull-Fallback, vertretbar bei der heutigen Property-Anzahl (s. Performance-Schätzung).

**Aufwands-Audit gegen No-Go-Kriterium "API-Änderungen > 2 Tage Rework" (AC5):**

| Mehrarbeit gegenüber Story-Spec-Annahme | Aufwand |
|---|---|
| Endpunkt-Wechsel `/api/tickets` → `/api/properties/{id}/processes` | trivial (URL-Konstante) |
| Property-Mapping via `externalId`-Lookup statt direktem Ticket-DTO-Feld | ~2 h (Lookup-Helper + Cache) |
| Migration `ALTER TABLE facilioo_tickets ADD COLUMN is_archived` | ~1 h (Story 4.2) |
| Migration `ADD COLUMN facilioo_last_modified TIMESTAMPTZ` (separates Delta-Feld, s. Decisions) | ~1 h (Story 4.2) |
| Rename `facilioo_client.py → facilioo.py` inkl. Test-Mock-Pfade (s. Tabelle unten) | ~1–2 h (Story 4.2) |
| Full-Pull-Mirror statt Delta-Pull | ~2 h (Story 4.3) |
| **Gesamt** | **~7–8 h ≪ 2 Tage** |

→ GO bestätigt; alle Mehrarbeit innerhalb der geplanten Story-Scopes 4.2/4.3.

---

## Auth-Flow

- Methode: Bearer JWT aus `settings.facilioo_bearer_token`
- Status: ✓ verifiziert — ETV-Live-Test 2026-04-29, Spike-Calls 2026-04-30 alle 200 OK
- **JWT-`exp` = 2026-05-14** (≈ 14 Tage Restlaufzeit ab Spike-Datum). Verlässliche Quelle ist die `exp`-Claim im JWT-Payload — die in einer früheren Version dieses Dokuments behauptete "TTL ~12 Monate" war geschätzt und ist nicht durch das aktuell aktive Token belegt; wahrscheinlich kürzere TTL (≈ 1–3 Monate). Vor Token-Ablauf neues Token in 1Password-Vault `KI` ablegen und in Elestio-Env aktualisieren (s. Decisions → Token-Rotation).
- Konfiguration: `app/config.py:28–29` (`facilioo_base_url`, `facilioo_bearer_token`)

---

## Ticket-Endpunkt

**Befund**: Facilioo nennt Tickets intern **„Prozesse"**. Der Endpunkt heißt nicht `/api/tickets` sondern `/api/processes`.

### Endpoint-Probing (Reproduzierbarkeit)

**Schritt 1 — Swagger/Docs gesucht (alle 4 Kandidaten aus Task 1.1):**

| Kandidat | Ergebnis |
|---|---|
| `https://api.facilioo.de/swagger-ui.html` | 404 / 500 |
| `https://api.facilioo.de/v3/api-docs` | 404 / 500 |
| `https://api.facilioo.de/swagger` | 404 / 500 |
| `https://api.facilioo.de/v2/api-docs` | 404 / 500 |

→ Keine Swagger-/OpenAPI-Doku öffentlich verfügbar; Fallback auf direktes Endpoint-Probing.

**Schritt 2 — Endpoint-Kandidaten getestet:**

| Endpunkt | Ergebnis |
|---|---|
| `/api/tickets` | 404 |
| `/api/pendencies`, `/api/defects`, `/api/issues` | 404 |
| `/api/processes` | 200 — aber `propertyId`-Query-Param wird ignoriert (immer alle 262 Prozesse) |
| `/api/properties/{facilioo_id}/processes` | **✓ 200 — korrekt gefiltert** (z. B. 14 für PLS22, 16 für IKF21) |

**Korrekter URL für Story 4.2/4.3:**
```
GET https://api.facilioo.de/api/properties/{facilioo_property_id}/processes
    ?pageNumber=1&pageSize=100
```

- HTTP-Status: 200
- Pagination: **1-indexed** (`pageNumber >= 1`), `pageSize`-Parameter wird akzeptiert
- `pageNumber=0` wirft HTTP 400 (wie bei allen anderen Facilioo-Endpoints)
- Response-Header `content-range: 1-{pageSize}/{totalCount}` vorhanden

---

## DTO-Shape (Prozess = Ticket)

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `id` | int | ja | Primärschlüssel (Facilioo-intern) |
| `number` | int | ja | Laufende Nummer pro Tenant |
| `fullyQualifiedNumber` | string | ja | `"{number}/{partyId}"` — z. B. `"24/4422685"` |
| `subject` | string | ja | Betreff / Titel des Tickets |
| `report` | string (HTML) | nein | Beschreibung als HTML-String |
| `accountId` | int | nein | Zugewiesener Bearbeiter (Facilioo-Account) |
| `contactId` | int | nein | Kontakt-Referenz |
| `createdByPartyId` | int | nein | Erstellender Party |
| `typeId` | int | nein | Ticket-Typ (nur IDs, Namen nicht per API abrufbar) |
| `stageId` | int\|null | nein | Status-Stage — in Live-Daten immer `null` |
| `isFinished` | bool | ja | `true` = abgeschlossen/archiviert |
| `finishDate` | ISO-8601\|null | nein | Abschluss-Zeitstempel |
| `unitId` | int\|null | nein | Einheit-Referenz (Facilioo-Unit-ID) |
| `externalId` | string\|null | nein | Externes System (immer `null` in Live-Daten) |
| `externalIdOfPantaenius` | string\|null | nein | Pantaenius-Versicherungsreferenz |
| `created` | ISO-8601 | ja | Erstellungszeitpunkt |
| `lastModified` | ISO-8601 | ja | Letzte Änderung |
| `deleted` | ISO-8601\|null | nein | Soft-Delete-Zeitstempel |

**Nicht im DTO vorhanden** (aus Spec-AC2 erwartete optionale Felder):
- **Priorität** (`priority`/`priorityId`): kein entsprechendes Feld in der Response — Facilioo modelliert Priorität nicht auf Prozess-Ebene. Story 4.4 zeigt keine Priorität.
- **Deep-Link zur Facilioo-UI**: kein offizielles URL-Pattern in der Response. Heuristisch konstruierbar via `https://app.facilioo.de/processes/{id}` (nicht verifiziert) — bei Bedarf in Story 4.4 als externer Link prüfen oder weglassen.

**Status-Wahrheitsregel** (s. Decisions → Soft-Delete-Semantik): `deleted != null` gewinnt **vor** `isFinished` (gelöscht vor abgeschlossen). Ableitung in `services/facilioo.py` als zentraler Helper `derive_status(process) -> str` mit den Werten `"open"` / `"finished"` / `"deleted"`.

| Bedingung | `derive_status()` | Lokal `is_archived` |
|---|---|---|
| `deleted != null` | `"deleted"` | `True` |
| `deleted == null` AND `isFinished == true` | `"finished"` | `False` |
| `deleted == null` AND `isFinished == false` | `"open"` | `False` |
| Prozess nicht mehr in API-Response (Set-Diff) | (vorheriger Wert bleibt) | `True` (nur bei vollständigem Pull, s. Decisions) |

---

## Property-Mapping

**Lösung: Dynamischer Lookup über `Facilioo.property.externalId` → kein neues DB-Feld nötig**

### Befund

- Facilioo-Properties haben ein `externalId`-Feld → enthält die **Impower Property-ID** (numerischer String, z. B. `"32011"` für PLS22)
- Unser `Object.impower_property_id` = `"32011"` → direkt matchbar
- 64 Facilioo-Properties gesamt, 54 haben `externalId` gesetzt (restliche 10: Demo/Dummy-Objekte, nicht relevant)

### Mapping-Algorithmus (Story 4.2/4.3)

```python
# Einmalig pro Mirror-Lauf, mit 5-min-TTL-Cache in app.state (s. Decisions → Properties-Cache):
facilioo_props = await _get_all_paged(client, "/api/properties")
impower_to_facilioo: dict[str, int] = {}
for p in facilioo_props:
    ext = (p.get("externalId") or "").strip()
    # Robustheits-Härtung (s. Decisions → Property-Mapping):
    # 1) leerer / fehlender externalId → skip (Demo-/Dummy-Properties)
    # 2) nicht-numerischer externalId → skip (Impower-Property-IDs sind alle numerisch)
    # 3) Duplicate-externalId → WARN-Log + ersten Eintrag behalten (zweiten überspringen)
    if not ext.isdigit():
        continue
    if ext in impower_to_facilioo:
        logger.warning("facilioo_duplicate_externalId", extra={"externalId": ext, "skipped_facilioo_id": p["id"]})
        continue
    impower_to_facilioo[ext] = p["id"]

# Dann pro Object mit impower_property_id:
if obj.impower_property_id is None:
    continue  # Steckbrief ohne Impower-Sync — sauber überspringen
facilioo_id = impower_to_facilioo.get(str(obj.impower_property_id))
if facilioo_id:
    processes = await _get_all_paged(client, f"/api/properties/{facilioo_id}/processes")
```

**Kein neues `facilioo_property_id`-Feld in der `objects`-Tabelle nötig** — dynamischer Lookup ist mit Properties-Cache (5-min-TTL in `app.state.facilioo_properties_cache`) billig: ~1 Properties-Call pro 5 Minuten statt pro Mirror-Lauf, also ~288 Calls/Tag statt 1440 (s. Decisions → Properties-Cache-TTL). Als zukünftige Optimierung kann die Spalte später ergänzt werden.

### Konsequenz für Story 4.2

- Migration 4.2 (`0018_facilioo_tickets_archived_and_last_modified.py`): **nicht** für `facilioo_property_id`-Spalte nötig — aber **zwei** neue Spalten auf `facilioo_tickets`:
  - `is_archived BOOLEAN NOT NULL DEFAULT FALSE` (Soft-Delete-Markierung)
  - `facilioo_last_modified TIMESTAMP WITH TIME ZONE` (separates Delta-Vergleich-Feld, **nicht** `updated_at` zweckentfremden — onupdate-ORM-Hook würde mit jedem UPSERT hochlaufen und den Delta-Vergleich kappen)
- `FaciliooTicket.object_id` FK → `objects.id` wie geplant, Mapping via Lookup

---

## Delta-Support

| Mechanismus | Status |
|---|---|
| ETag-Header in Response | ❌ nicht vorhanden |
| Last-Modified-Header in Response | ❌ nicht vorhanden |
| If-None-Match-Header (Anfrage) | ❌ ignoriert (immer 200) |
| If-Modified-Since-Header (Anfrage) | ❌ ignoriert (immer 200) |
| Query-Param `updatedSince` | ❌ ignoriert (kein Effekt auf totalCount) |
| Query-Param `modifiedSince` | ❌ ignoriert |
| Query-Param `lastModifiedFrom` | ❌ ignoriert |

**ETag-Support: nein | If-Modified-Since: nein**

### Fallback-Strategie für Stories 4.2/4.3

**Full-Pull mit lokalem Delta-Vergleich**:
1. Alle Prozesse einer Property per `_get_all_paged` laden
2. Lokale `facilioo_tickets`-Tabelle mit frischem Pull abgleichen:
   - Neu in Facilioo, nicht lokal → INSERT (`is_archived = False` initial)
   - In Facilioo und lokal vorhanden → UPDATE wenn `lastModified` neuer als gespeichertes `facilioo_last_modified`. **Re-Aktivierung:** wenn Prozess zuvor `is_archived = True` war und jetzt wieder in der API-Response auftaucht → `is_archived = False` zurücksetzen (Soft-Mark ist nie permanent).
   - Lokal vorhanden, nicht mehr in Facilioo → `is_archived = True` (soft-mark) — **nur wenn Pull vollständig erfolgreich** (Two-Phase: erst alle Properties durchpullen, dann Set-Diff in einer Transaktion; bei Fehler in Pull-Phase: kein Set-Diff, kein Archivieren).
3. `lastModified`-Vergleich über separate Spalte `facilioo_tickets.facilioo_last_modified` (nicht `updated_at`!) vs. Facilioo `lastModified`-Feld. Annahme: Facilioo liefert ISO-8601 mit Offset; Pydantic-Schema erwartet `datetime` mit TZ. Bei abweichendem Format (naiv) → in `services/facilioo.py` Helper auf UTC normalisieren.

Performance-Schätzung (Stand 2026-04-30): 54 gemappte Objekte, im Spike-Sample 14 + 16 Prozesse pro Property gesehen — Gesamt-Volumen aus `/api/processes` ungefiltert: 262 Prozesse über alle Properties (Mittelwert ≈ 5 Prozesse pro gemapptem Objekt). Bei pageSize=100 reicht eine Seite pro Property in nahezu allen Fällen. Gesamtlaufzeit ca. 54 + 1 API-Calls pro Run, bei 45–160 ms/Call **ohne Throttle** ≈ 10–15 s; **mit 1 req/s Throttle** ≈ 55 s pro Mirror-Lauf (s. Sicherheitspuffer in Rate-Limits-Sektion).

---

## Rate-Limits

- **Beobachtet bei 10 sequentiellen Calls (AC4): keine 429**
- **`X-RateLimit-*`-Header vorhanden: nein** — keine Rate-Limit-Header in Responses
- **`Retry-After`-Header: nein**
- Antwortzeiten: 44–161 ms (erste Anfrage ≈ 160 ms, warm ≈ 45 ms)

**Empfehlung Default-Throttle für `facilioo_mirror.py`**: **1 req/s** — konservativ angemessen. Keine 429 beobachtet, aber ohne dokumentiertes Limit lieber vorsichtig. Bei 54 Objekten + 1 Properties-Call (mit 5-min-Cache also nicht jedes Mal) = bis zu 55 Calls × 1 s = ~55 s pro Run, knapp unter dem 1-Minuten-Polling-Intervall aus Story 4.3.

**Implementation** (s. Decisions → Throttle + Concurrency): `asyncio.Semaphore(1)` + `asyncio.sleep(1.0)` zwischen Calls in `services/facilioo.py`-Wrapper — **nicht** `asyncio.gather()` für die Property-Schleife (würde alle Calls parallel feuern und das Throttle ignorieren).

**Sicherheitspuffer:**
- Watchdog: WARN-Log wenn ein Lauf > 50 s dauert.
- Single-flight: Mirror nutzt PostgreSQL `pg_advisory_lock(hashtext('facilioo_mirror'))` — gleichzeitiger zweiter Lauf (parallel-Scheduler-Tick oder manuelles Re-Sync via Admin-Button) wartet nicht, sondern überspringt ("Mirror läuft bereits"-Toast im Admin-UI).
- Verschärfung: bei zukünftiger 429-Beobachtung auf 0,5 req/s **verlangsamen** (1 Call alle 2 s — also längeres Throttle, nicht aggressiveres).

---

## Architektur-Entscheidung: Client-Naming

**Entscheidung: Option A — `facilioo_client.py` umbenennen zu `facilioo.py`**

Begründung:
- Passt zur geplanten Architektur (`services/facilioo.py` laut `architecture.md:582`)
- Vermeidet dauerhaften Naming-Drift (`facilioo_client.py` vs. `facilioo_mirror.py` im gleichen Ordner)

**Rename-Scope (vollständig, korrigiert nach Code-Review 2026-04-30):**

| Konsument | Stellen | Aufwand |
|---|---|---|
| `app/routers/etv_signature_list.py:29` | 1 Import (`from app.services.facilioo_client import ...`) | trivial |
| `tests/test_etv_signature_list.py` | 1 Import (`from app.services import facilioo_client`) + ca. 25 Mock-String-Pfade in `monkeypatch.setattr("app.services.facilioo_client.httpx.AsyncClient", ...)` und Calls über `facilioo_client.list_conferences()` etc. | ~30 min: ein `sed -i 's/facilioo_client/facilioo/g'` über `tests/test_etv_signature_list.py` + Test-Lauf zur Verifikation |
| `CLAUDE.md` Mention von `facilioo_client.py` | 1 Stelle | trivial |
| Memory-Files (`reference_facilioo_pagination.md` etc.) | mehrere Mentions, nicht hart import-relevant | als Defer-Item dokumentiert |
| Dynamische Imports / `importlib.import_module` | keine gefunden (`grep -rn "importlib" app/ tests/` leer) | n/a |

**Aktion in Story 4.2** (~1–2 h gesamt):
1. `git mv app/services/facilioo_client.py app/services/facilioo.py`
2. `sed` über `app/routers/etv_signature_list.py` und `tests/test_etv_signature_list.py` (Strings UND Imports)
3. `pytest tests/test_etv_signature_list.py` muss grün bleiben
4. CLAUDE.md-Mention updaten

---

## Response-Container für `_get_all_paged`-Reuse

`/api/properties/{id}/processes` liefert (Beispiel PLS22, totalCount=14, pageSize=100):
```json
{
  "items": [...],
  "pageNumber": 1,
  "pageSize": 100,
  "totalPages": 1,
  "totalCount": 14,
  "hasPreviousPage": false,
  "hasNextPage": false
}
```

`_get_all_paged` unterstützt bereits `items`-Container + `totalPages`-Check → **direkte Wiederverwendung möglich, keine Variante nötig**.

---

## Fehlende `is_archived`-Spalte in `facilioo_tickets`

Das aktuelle Modell (`app/models/facilioo.py`) hat kein `is_archived`-Feld. Story 4.3 (Full-Pull-Fallback) braucht es für Soft-Delete-Markierung.

**Migration in Story 4.2**:
```sql
ALTER TABLE facilioo_tickets ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE;
```

---

## Abhängigkeiten für Stories 4.2–4.4

### Story 4.2 — Facilioo-Client mit Retry + Rate-Gate

- Rename `facilioo_client.py` → `facilioo.py` inkl. Test-Mock-Pfade (s. Architektur-Entscheidung Tabelle)
- Neue Funktion `list_processes(facilioo_property_id)` in `facilioo.py` (nutzt `_get_all_paged`)
- Neue Funktion `list_properties()` in `facilioo.py` (für Property-Lookup; mit 5-min-TTL-Cache in `app.state.facilioo_properties_cache`)
- Helper `derive_status(process) -> str` mit Werten `"open"`/`"finished"`/`"deleted"`
- Helper `parse_facilioo_datetime(value) -> datetime` (UTC-aware) für `lastModified`-Normalisierung
- Migration `0018_facilioo_tickets_archived_and_last_modified.py`:
  - `ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE`
  - `ADD COLUMN facilioo_last_modified TIMESTAMP WITH TIME ZONE`
- Rate-Gate: `asyncio.Semaphore(1) + asyncio.sleep(1.0)` zwischen Calls (Default 1 req/s)
- Pydantic-Schema mit `populate_by_name=True` und `Field(..., alias="lastModified")` für Defensive-Drift
- `test_facilioo_client_boundary` Tests: Mock-basiert, kein echter API-Call; zusätzlich Test für Property-Mapping-Edge-Cases (NULL externalId, nicht-numerischer externalId, Duplicate)

### Story 4.3 — 1-Min-Poll-Job mit Delta-Support

- **Kein ETag / kein If-Modified-Since** → Full-Pull-Strategie + lokaler `facilioo_last_modified`-Vergleich (separate Spalte, **nicht** `updated_at`!)
- Mapping-Algorithmus: gecachtes `_get_all_paged("/api/properties")` → `externalId → facilioo_id` dict → pro Object (mit Härtung gegen NULL/Duplicate/Non-numeric, s. Mapping-Sektion)
- Delta-Logik: INSERT (mit `is_archived = False` initial) / UPDATE wenn `lastModified` neuer / Re-Aktivierung wenn lokal `is_archived = True` aber wieder in API-Response
- Soft-Delete-Markierung: `is_archived = True` wenn Prozess nicht mehr in API-Response — **nur bei vollständigem Pull** (Two-Phase-Commit, kein Set-Diff bei Pull-Fehler)
- Single-flight via PostgreSQL `pg_advisory_lock(hashtext('facilioo_mirror'))` — verhindert parallele Mirror-Läufe und Race mit manuellem Re-Sync
- Watchdog: WARN-Log bei Lauf-Dauer > 50 s; Skip nächste Iteration falls vorheriger Lauf noch läuft
- Token-Health-Check beim App-Boot: JWT-`exp` decodieren; bei < 7 Tagen Restlaufzeit → ERROR-Log + Audit-Event `facilioo_token_expiring` + `/admin/sync-status` zeigt DEGRADED. Bei 401-Response zur Laufzeit → Audit-Event `facilioo_token_invalid` + Sync-Status DEGRADED.
- Kein neues `facilioo_property_id`-Feld in `objects` nötig

### Story 4.4 — Facilioo-Tickets am Objekt-Detail

- UI liest aus lokaler `facilioo_tickets`-Tabelle (kein Live-Call)
- Filter: `is_archived = False` für aktive Tickets
- Anzeige: nur `subject` + `derive_status()`-Pille (`open`/`finished`); **kein** Typ-Name (`/api/process-types` liefert nur IDs ohne Namen — Lookup-Cache wäre Wartungsaufwand für Marginal-Mehrwert)
- **Keine Priorität** anzeigen (existiert nicht im Process-DTO)
- Deep-Link zur Facilioo-UI: optional via `https://app.facilioo.de/processes/{id}` (nicht verifiziert) — bei Bedarf prüfen oder weglassen
- Wording im UI bleibt **„Tickets"** (etabliertes Vokabular in DB-Tabelle, Story-Spec, Codebase) — Mapping auf Facilioo-„Prozesse" nur in `services/facilioo.py` als Code-Kommentar
- Property-Zuordnung bereits via `object_id` FK vorhanden
- Go-Fall: Ticket-Sektion zeigt echte Daten
- AC3 (UI-Fallback "Ticket-Integration nicht verfügbar"): **bleibt erhalten** als Code-Resilienz — Template zeigt den Fallback wenn keine `FaciliooTicket`-Rows für das Objekt existieren ODER ein Service-Down-Flag (`sync_status.facilioo_state == "DEGRADED"`) gesetzt ist. Damit bleibt die UI robust auch bei Token-Ablauf oder Facilioo-Downtime.

---

## Anmerkungen

- **Token-Ablauf**: JWT `exp` = 2026-05-14. Rechtzeitig vor Ablauf neues Token in 1Password-Vault `KI` ablegen und Elestio-Env-Var aktualisieren. Story 4.3 baut Pre-expiry-Health-Check ein (s. Story-4.3-Abhängigkeiten).
- **10 Objekte ohne Impower-Link**: Properties in Facilioo, deren `externalId` leer oder nicht-numerisch ist (z. B. "Musterhaus facilioo Workshop", "Anfragen Dummy"). Mirror-Job überspringt diese sauber via `if not ext.isdigit(): continue` (statt fragilem Prefix-Check). Counter `facilioo_unmapped_properties` wird in `/admin/sync-status` ausgegeben (Story 4.3) — wenn neue Production-Property versehentlich ohne externalId angelegt wird, fällt das auf.
- **`typeId`-Namen nicht per API abrufbar**: `/api/process-types` liefert nur IDs ohne Namen. Für das UI in Story 4.4 keine Typ-Beschriftung — `subject` reicht. Bei späterem Bedarf: statisches Mapping in `app/data/facilioo_type_names.json` pflegen.
- **`stageId` immer null in Live-Daten** (Stichprobe über 14 + 16 + 262 Prozesse aller Properties): Facilioo-Mandant für DBS Home nutzt keine Stages. `isFinished` (kombiniert mit `deleted`) ist das einzige Status-Signal. Falls zukünftig Stages eingeführt werden: `raw_payload`-JSONB sichert die Original-Response → `derive_status()` kann erweitert werden ohne Migration.
- **`partyId` in `fullyQualifiedNumber`** (Format `"{number}/{partyId}"`, z. B. `"24/4422685"`): Multi-Tenancy-Schlüssel auf Facilioo-Seite. Token ist DBS-Home-spezifisch ausgestellt — wir sehen nur unsere 64 Properties. Falls Token in Zukunft an einen breiteren Scope gekoppelt wird, könnte das Mapping doppelte `externalId`s liefern (gleiche Impower-Property-ID bei zwei Mandanten) — dann greift der Duplicate-Check im Mapping-Algorithmus.
- **Spike-Sample-Größe**: Endpunkt-Verhalten verifiziert über 2 Properties (PLS22, IKF21) + 10 sequentielle Calls für Rate-Limit. Repräsentativ, aber nicht exhaustiv — Story 4.2 Boundary-Tests erweitern die Coverage.
