# Facilioo Ticket-API Spike

Datum: 2026-04-30 | Durchgeführt von: Daniel Kroll

---

## Go / No-Go Empfehlung

**Entscheidung: GO**

Begründung: Bearer-Token funktioniert, Ticket-Endpunkt erreichbar (`/api/properties/{facilioo_id}/processes`), Property-Mapping über `externalId` lösbar ohne neue Spalte (dynamischer Lookup), Pagination per `_get_all_paged` wiederverwendbar. Einzige Einschränkung: kein Delta-Support → Full-Pull-Fallback, unproblematisch bei ~54 Objekten.

---

## Auth-Flow

- Methode: Bearer JWT aus `settings.facilioo_bearer_token`
- Status: ✓ verifiziert — ETV-Live-Test 2026-04-29, Spike-Calls 2026-04-30 alle 200 OK
- Kein Token-Refresh nötig; JWT-`exp` = 2026-05-14 (TTL ~12 Monate ab Ausstellung)
- Konfiguration: `app/config.py:28–29` (`facilioo_base_url`, `facilioo_bearer_token`)

---

## Ticket-Endpunkt

**Befund**: Facilioo nennt Tickets intern **„Prozesse"**. Der Endpunkt heißt nicht `/api/tickets` sondern `/api/processes`.

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

**Aktives Ticket**: `isFinished == false` AND `deleted == null`  
**Abgeschlossen**: `isFinished == true`  
**Gelöscht (soft)**: `deleted != null`

---

## Property-Mapping

**Lösung: Dynamischer Lookup über `Facilioo.property.externalId` → kein neues DB-Feld nötig**

### Befund

- Facilioo-Properties haben ein `externalId`-Feld → enthält die **Impower Property-ID** (numerischer String, z. B. `"32011"` für PLS22)
- Unser `Object.impower_property_id` = `"32011"` → direkt matchbar
- 64 Facilioo-Properties gesamt, 54 haben `externalId` gesetzt (restliche 10: Demo/Dummy-Objekte, nicht relevant)

### Mapping-Algorithmus (Story 4.2/4.3)

```python
# Einmalig pro Mirror-Lauf (nicht pro Property):
facilioo_props = await _get_all_paged(client, "/api/properties")
impower_to_facilioo = {
    p["externalId"]: p["id"]
    for p in facilioo_props
    if p.get("externalId") and not p["externalId"].startswith("DEMO")
}
# Dann pro Object mit impower_property_id:
facilioo_id = impower_to_facilioo.get(str(obj.impower_property_id))
if facilioo_id:
    processes = await _get_all_paged(client, f"/api/properties/{facilioo_id}/processes")
```

**Kein neues `facilioo_property_id`-Feld in der `objects`-Tabelle nötig** — dynamischer Lookup ist bei ~54 Objekten billig (1 Properties-Seite, ~2 KB). Als zukünftige Optimierung kann die Spalte später ergänzt werden.

### Konsequenz für Story 4.2

- Migration 4.2: **nicht** für `facilioo_property_id`-Spalte nötig — nur für `is_archived` auf `facilioo_tickets`
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
   - Neu in Facilioo, nicht lokal → INSERT
   - In Facilioo und lokal vorhanden → UPDATE wenn `lastModified` neuer
   - Lokal vorhanden, nicht mehr in Facilioo → `is_archived = True` (soft-mark)
3. `lastModified`-Vergleich über `facilioo_tickets.updated_at` vs. Facilioo `lastModified`-Feld

Performance-Schätzung: 54 Objekte × ø 8 Prozesse = ~430 Prozesse pro Pull, alle auf 1 Seite (pageSize=100 reicht meist). Gesamtlaufzeit ca. 54 + 1 API-Calls pro Run, bei 45–160 ms/Call ≈ 10–15 s pro Mirror-Lauf.

---

## Rate-Limits

- **Beobachtet bei 10 sequentiellen Calls (AC4): keine 429**
- **`X-RateLimit-*`-Header vorhanden: nein** — keine Rate-Limit-Header in Responses
- **`Retry-After`-Header: nein**
- Antwortzeiten: 44–161 ms (erste Anfrage ≈ 160 ms, warm ≈ 45 ms)

**Empfehlung Default-Throttle für `facilioo_mirror.py`**: **1 req/s** — konservativ angemessen. Keine 429 beobachtet, aber ohne dokumentiertes Limit lieber vorsichtig. Bei 54 Objekten + 1 Properties-Call = 55 Calls × 1 s = ~55 s pro Run, deutlich unter dem 1-Minuten-Polling-Intervall aus Story 4.3. Falls Performance-Probleme auftreten, auf 0,5 req/s (500 ms) erhöhen.

---

## Architektur-Entscheidung: Client-Naming

**Entscheidung: Option A — `facilioo_client.py` umbenennen zu `facilioo.py`**

Begründung:
- Nur **1 Import-Stelle** betroffen: `app/routers/etv_signature_list.py:29`
- Rename = 1 `git mv` + 1 Zeile in `etv_signature_list.py` updaten
- Passt zur geplanten Architektur (`services/facilioo.py` laut `architecture.md:582`)
- Vermeidet dauerhaften Naming-Drift (`facilioo_client.py` vs. `facilioo_mirror.py` im gleichen Ordner)

**Aktion in Story 4.2**: `git mv app/services/facilioo_client.py app/services/facilioo.py` + Import-Update in `etv_signature_list.py`

---

## Response-Container für `_get_all_paged`-Reuse

`/api/properties/{id}/processes` liefert:
```json
{
  "items": [...],
  "pageNumber": 1,
  "pageSize": 100,
  "totalPages": 2,
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

- Rename `facilioo_client.py` → `facilioo.py` (1 Import-Update)
- Neue Funktion `list_processes(facilioo_property_id)` in `facilioo.py` (nutzt `_get_all_paged`)
- Neue Funktion `list_properties()` in `facilioo.py` (für Property-Lookup)
- Migration: `ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE` auf `facilioo_tickets`
- Rate-Gate: 1 req/s als Default (keine API-seitigen Hinweise, konservativer Wert)
- `test_facilioo_client_boundary` Tests: Mock-basiert, kein echter API-Call

### Story 4.3 — 1-Min-Poll-Job mit Delta-Support

- **Kein ETag / kein If-Modified-Since** → Full-Pull-Strategie + lokaler `lastModified`-Vergleich
- Mapping-Algorithmus: `_get_all_paged("/api/properties")` → `externalId → facilioo_id` dict → pro Object
- Delta-Logik: INSERT/UPDATE/is_archived via `lastModified`-Vergleich
- Soft-Delete-Markierung: `is_archived = True` wenn Prozess nicht mehr in API-Response
- Kein neues `facilioo_property_id`-Feld in `objects` nötig

### Story 4.4 — Facilioo-Tickets am Objekt-Detail

- UI liest aus lokaler `facilioo_tickets`-Tabelle (kein Live-Call)
- Filter: `is_archived = False` für aktive Tickets
- Property-Zuordnung bereits via `object_id` FK vorhanden
- Go-Fall: Ticket-Sektion zeigt echte Daten
- No-Go-Fallback (AC3) war vorbereitet — entfällt, da GO

---

## Anmerkungen

- **Token-Ablauf**: JWT `exp` = 2026-05-14. Rechtzeitig vor Ablauf neues Token in 1Password-Vault `KI` ablegen und Elestio-Env-Var aktualisieren.
- **10 Objekte ohne Impower-Link**: Demo/Dummy-Properties in Facilioo (z. B. "Musterhaus facilioo Workshop", "Anfragen Dummy") haben kein `externalId`. Mirror-Job überspringt diese sauber via `if facilioo_id:`.
- **`typeId`-Namen nicht per API abrufbar**: `/api/process-types` liefert nur IDs ohne Namen. Für das UI in Story 4.4 keine Typ-Beschriftung nötig — `subject` reicht.
- **`stageId` immer null**: In Live-Daten keine Stage-Zuweisung. `isFinished` ist das einzige Status-Signal.
