# Story 4.1: Facilioo-API-Spike

Status: review

## Story

Als Entwickler,
möchte ich die Facilioo-Ticket-API auf Auth, DTO-Struktur und Delta-Support prüfen,
damit wir eine belastbare Go/No-Go-Entscheidung für die Ticket-Integration in v1 haben.

## Boundary-Klassifikation

`research-spike` — Geringes Risiko. Keine Produktions-Writes. Kein neues ORM-Modell, keine Migration,
kein neuer Router. Output ist eine Dokumentationsdatei + optionale Erweiterung des bestehenden Clients.

**Kritische Risiken:**
1. **Falscher Ticket-Endpoint**: Endpunkt `/api/tickets` ist ungetestet — könnte `/api/properties/{id}/tickets` oder ähnlich sein. Falsche Annahme bricht Story 4.3.
2. **Property-ID-Mapping fehlt**: Die Brücke zwischen unserem `Object.impower_property_id` und der Facilioo-`propertyId` ist ungeklärt. Ohne dieses Mapping kann Story 4.3 keine Tickets dem richtigen Objekt zuordnen.
3. **`facilioo_client.py` vs. architekturelles `facilioo.py`**: Die Architektur plant `services/facilioo.py`, vorhanden ist aber `services/facilioo_client.py` (aus ETV). Story 4.1 entscheidet, ob `facilioo_client.py` umbenannt/erweitert oder der Ticket-Pfad als eigenes Modul gebaut wird. Diese Entscheidung blockt Stories 4.2–4.4.
4. **Spike ist No-Go-fähig**: Bei fehlendem Token, unzugänglichem Ticket-Endpoint oder nicht-lösbarem Property-Mapping ist das Ergebnis "No-Go für v1" — kein Fehler, sondern das Ziel dieses Spikes.

**Sprint-Reihenfolge:** Story 4.0 (Code-Hygiene) blockiert Story 4.2 (erste Code-Story in Epic 4), aber **nicht** diese Story. Story 4.1 ist dokumentations-only und kann parallel zu 4.0 laufen. Empfehlung: 4.1 zuerst starten — Go/No-Go-Entscheidung entkoppelt den ganzen Epic, 4.0 läuft daneben weiter.

## Acceptance Criteria

**AC1 — Ticket-Endpoint erreichbar (Basis-Call)**

**Given** der bestehende `settings.facilioo_bearer_token` ist gesetzt (Bezugsquelle: 1Password-Vault `KI`, siehe Memory `secrets_1password.md`)
**When** ich einen GET auf den Facilioo-Ticket-Endpunkt mache (zu ermitteln: `/api/tickets`, `/api/properties/{id}/tickets` o.ä.)
**Then** erhalte ich eine erfolgreiche Antwort (2xx) mit einer Ticket-Liste **oder** einen klaren 4xx/5xx, der den No-Go-Pfad in AC5 auslöst
**And** auch der Response-Container (Top-Level-List vs. `{items}` vs. `{content}` vs. anderes Wrapper-Schema) wird notiert — relevant für Reuse von `_get_all_paged` in Story 4.2

**AC2 — DTO-Shape & Property-Mapping-Klärung**

**Given** ein erfolgreicher Ticket-Listen-Call (AC1)
**When** ich die Response auswerte
**Then** identifiziere ich die relevanten Felder:
  - Pflichtfelder: Ticket-ID, Titel, Status, Datum
  - Optionale Felder: Eigentuemer-/Mieter-Bezug, Kategorie, Priorität, Verlinkung
  - Property-Referenz-Feld: Wie verweist ein Ticket auf ein Objekt (Facilioo-Property-ID, externer Key)?
**And** ich kläre: Gibt es ein Mapping-Feld, das `Object.impower_property_id` entspricht, oder brauchen wir ein neues `Object.facilioo_property_id`-Feld?

**AC3 — Delta-Support (ETag / If-Modified-Since)**

**Given** der Ticket-Endpunkt antwortet auf AC1
**When** ich einen zweiten GET auf denselben Endpunkt mache, diesmal mit `If-None-Match: <etag>` oder `If-Modified-Since: <datum>` Header
**Then** stelle ich fest, ob der Server mit 304 antwortet (Delta unterstützt) oder 200 zurückgibt (kein Delta)
**And** halte explizit fest: "ETag-Support: ja/nein, If-Modified-Since: ja/nein"

**AC4 — Rate-Limits beobachtet**

**Given** AC1 hat den Endpoint erreicht
**When** ich N (≥ 5) sequentielle GETs absetze (z. B. dieselbe Liste fünfmal hintereinander, ohne Throttle)
**Then** halte ich das beobachtete Verhalten fest:
  - 429-Response gesehen: ja/nein, ggf. mit `Retry-After`-Wert + Header-Felder (`X-RateLimit-Remaining`, `X-RateLimit-Reset`, ...)
  - Falls keine Limits aufgetreten: explizite Aussage "Mit N Calls keine 429 beobachtet — Default 1 req/s für Mirror-Job konservativ angemessen"
**And** ich gebe eine Empfehlung für den Throttle-Wert in `facilioo_mirror.py` (Default 1 req/s, oder schärfer wenn 429 beobachtet)

**AC5 — Spike-Dokument vollständig**

**Given** AC1–AC4 durchgeführt
**When** `docs/integration/facilioo-spike.md` eingereicht wird
**Then** enthält es alle Pflicht-Sektionen (s. Dev Notes: Dokumentstruktur) — mindestens: Auth-Flow, Ticket-Endpoint, DTO-Shape, Property-Mapping, Delta-Support, Rate-Limits, Architektur-Entscheidung Client-Naming, Abhängigkeiten 4.2–4.4
**And** enthält eine explizite **Go/No-Go-Empfehlung**:
  - **Go** wenn: Token vorhanden + Ticket-Endpoint erreichbar + Property-Mapping lösbar (neue Spalte oder bestehender Key)
  - **No-Go v1** wenn: Endpoint nicht erreichbar, Property-Mapping unklar, oder API-Änderungen > 2 Tage Rework bedeuten
**And** im Go-Fall: Liste der Abhängigkeiten für Stories 4.2–4.4 (z. B. "Delta fehlt → Full-Pull-Fallback in 4.3", "neues `facilioo_property_id`-Feld + Migration nötig für 4.2", "Response-Container ist `{tickets, pagination}` → eigene Pager-Variante in 4.2")

## Tasks / Subtasks

- [x] Task 1: Facilioo-Ticket-Endpoint ermitteln und auswerten (AC1, AC2)
  - [x] 1.1: Facilioo-Swagger/Docs aufrufen — Kandidaten-URLs (Spring-Boot-Konvention, weil bestehende API REST-typisch ist):
    1. `https://api.facilioo.de/swagger-ui.html`
    2. `https://api.facilioo.de/v3/api-docs`
    3. `https://api.facilioo.de/swagger`
    4. `https://api.facilioo.de/v2/api-docs`

    Bei Sackgasse: existierende Endpunkt-Liste aus `app/services/facilioo_client.py` (`/api/conferences`, `/api/voting-groups`, `/api/units/{id}/attribute-values`, `/api/conferences/{id}/mandates`) als Hinweis nutzen — Tickets liegen wahrscheinlich unter `/api/tickets` oder `/api/properties/{id}/tickets`. Letzte Eskalationsstufe: Facilioo-Support kontaktieren (Kontakt im 1Password-Vault `KI`).
  - [x] 1.2: GET Ticket-Liste testen — bestehenden `facilioo_client.py`-Client verwenden (Token bereits in `settings.facilioo_bearer_token`); alternativ direkter `httpx`-Call mit `_make_client()` im Python-REPL
  - [x] 1.3: DTO-Shape auswerten: relevante Felder + **Container-Wrapper** notieren (Top-Level-List vs. `{items}` vs. `{content}` vs. anderes — relevant für `_get_all_paged`-Reuse in 4.2)
  - [x] 1.4: Property-Mapping klären: Gibt es ein `impower_property_id`-äquivalentes Feld oder brauchen wir neues `Object.facilioo_property_id`?

- [x] Task 2: Delta-Support prüfen (AC3)
  - [x] 2.1: Zweiter GET mit `If-None-Match` und/oder `If-Modified-Since` Header → Response-Code + Header auswerten
  - [x] 2.2: Falls kein Delta: Full-Pull-Fallback als Architektur-Note im Spike-Doc

- [x] Task 3: Rate-Limits proben (AC4)
  - [x] 3.1: 5 sequentielle GETs auf Ticket-Liste in schneller Folge (kein Sleep) — Status-Codes + Header `Retry-After`, `X-RateLimit-*` notieren
  - [x] 3.2: Empfehlung für `facilioo_mirror.py` Default-Throttle ableiten (1 req/s konservativ, oder schärfer falls 429 schon bei < 5 Calls)

- [x] Task 4: Spike-Dokument erstellen (AC5)
  - [x] 4.1: `docs/integration/facilioo-spike.md` anlegen (Template s. Dev Notes: Dokumentstruktur)
  - [x] 4.2: Go/No-Go-Empfehlung + Abhängigkeitsliste formulieren
  - [x] 4.3: Architektur-Entscheidung `facilioo_client.py` vs. Umbenennung dokumentieren
  - [x] 4.4: Sprint-Status manuell aktualisieren: Story 4.1 → `done`; Epic-4-Status auf `in-progress`

## Dev Notes

### Was bereits existiert — NICHT neu bauen

| Artifact | Pfad | Inhalt |
|---|---|---|
| Facilioo-HTTP-Client | `app/services/facilioo_client.py` | Bearer-Auth, Retry (2/5/15 s, max 3), `_api_get`, `_get_all_paged` mit 1-indexed-Fix, `_sanitize_error` |
| Facilioo-Konfiguration | `app/config.py:28–29` | `facilioo_base_url = "https://api.facilioo.de"`, `facilioo_bearer_token = ""` |
| FaciliooTicket-ORM | `app/models/facilioo.py` | Felder: `id` (UUID PK), `object_id` (FK→objects), `facilioo_id` (unique), `status`, `title`, `raw_payload` (JSONB), `created_at`, `updated_at` |
| `facilioo_tickets` Tabelle | Migration `0010_steckbrief_core.py:402–430` | Tabelle existiert auf DB, inkl. `uq_facilioo_tickets_facilioo_id`-Constraint und Indexes |
| FaciliooTicket-Import | `app/models/__init__.py:6` | `from app.models.facilioo import FaciliooTicket` — bereits registriert |

### Auth-Status: bereits verifiziert

Der Bearer-Token aus `settings.facilioo_bearer_token` funktioniert — ETV-Unterschriftenliste ist live und ruft dieselbe API seit 2026-04-29 erfolgreich ab. Kein separater Auth-Spike nötig. Spike fokussiert auf Ticket-spezifische Endpunkte.

### Pagination-Pattern: bereits implementiert und gefixt

`facilioo_client.py::_get_all_paged` ist korrekt implementiert (1-indexed, `page <= totalPages`-Check). Wichtig: `pageNumber=0` wirft HTTP 400. Dieser Bug wurde bei ETV-Implementierung entdeckt und gefixt. Der neue Ticket-Pull-Code muss `_get_all_paged` wiederverwenden, nicht eigenes Paging schreiben.

### Response-Shape-Probe für `_get_all_paged`

`_get_all_paged` (`app/services/facilioo_client.py:110-155`) ist robust gegen drei Container-Formen:

1. List-Top-Level (`[item, item, ...]`)
2. `{items: [...], totalPages, last, pageNumber}`
3. `{content: [...]}`

Falls der Ticket-Endpoint eine **andere** Form liefert (z. B. `{tickets: [...], pagination: {...}}` oder `{data: [...], hasMore: bool}`), ist `_get_all_paged` **nicht** 1:1 wiederverwendbar — Story 4.2 müsste eine `_get_all_paged_tickets`-Variante bauen oder den generischen Pager um Wrapper-Aliase erweitern. **Im Spike-Doc den exakten Container-Wrapper notieren** (AC1) — das entscheidet, ob 4.2 reuse machen kann oder eigenen Pager braucht.

### Spike-Testen via Python REPL

```python
# Im Container oder lokal (mit .env geladen):
import asyncio
from app.config import settings
from app.services.facilioo_client import _make_client, _api_get, _get_all_paged

async def spike():
    async with _make_client() as client:
        # 1. Ticket-Liste testen
        result = await _api_get(client, "/api/tickets", {"pageNumber": 1, "pageSize": 5})
        print("Ticket-Liste:", result)

        # 2. ETag-Check — erstes Ergebnis liefert ggf. ETag-Header
        # (httpx Response-Header direkt auswerten)

asyncio.run(spike())
```

Alternativ: `docker compose exec app python -c "..."` verwenden.

### Architektur-Naming-Konflikt klären

Die Architektur (`output/planning-artifacts/architecture.md:582`) plant:
```
services/facilioo.py          # [new] Facilioo-Client
services/facilioo_mirror.py   # [new] 1-Min-Poll-Job
```

Vorhanden ist aber:
```
services/facilioo_client.py   # [exists] Konferenz-/ETV-Client
```

**Konsumenten von `facilioo_client.py` heute:**

```bash
$ grep -rn "from app.services.facilioo_client" app/
app/routers/etv_signature_list.py:29
```

Genau **eine** Import-Stelle. Rename ist faktisch trivial: 1 Zeile in `etv_signature_list.py` updaten + Datei umbenennen (`git mv`).

**Optionen für das Spike-Dokument:**

| Option | Vorteil | Nachteil |
|---|---|---|
| A: `facilioo_client.py` → `facilioo.py` (umbenennen) | Passt zur Architektur, ein zentraler Client; Rename betrifft nur `etv_signature_list.py:29` | Minimaler Aufwand, kein echter Nachteil |
| B: Ticket-Funktionen in `facilioo_client.py` ergänzen, `facilioo_mirror.py` neu anlegen | Kein Rename | Naming-Drift gegenüber Architektur bleibt dauerhaft im Repo |

**Empfehlung Spike-Doc: Option A** — Aufwand-Nutzen klar pro Rename (1 Import-Update + 1 `git mv` gegen permanenten Naming-Drift gegenüber Architektur).

### FaciliooTicket — fehlendes `archived`-Feld

Das aktuelle `FaciliooTicket`-Modell (`app/models/facilioo.py`) hat kein `is_archived`-Feld. Story 4.3 sieht vor, nicht mehr vorhandene Tickets als `archived` zu markieren. Für Story 4.3 wird eine neue Migration nötig (`ALTER TABLE facilioo_tickets ADD COLUMN is_archived BOOLEAN DEFAULT FALSE`). Im Spike-Doc vermerken, falls der Full-Pull-Fallback gewählt wird — dann ist `is_archived` für Story 4.3 obligatorisch.

### Property-Mapping — kritische offene Frage

Die `FaciliooTicket`-Tabelle hat einen FK → `objects.id`. Aber: Wie ordnen wir ein Facilioo-Ticket einem unserer `Object`-Rows zu?

Szenarien:
1. **Facilioo liefert `impower_property_id` im Ticket-DTO** → direktes Matching auf `Object.impower_property_id` möglich, keine Migration nötig.
2. **Facilioo hat eigene `propertyId`** → neues Feld `Object.facilioo_property_id` + Migration + Admin-Pflege-UI oder automatisches Matching über Property-Name/Adresse.
3. **Kein eindeutiger Key** → No-Go oder manuelles Mapping-Konzept nötig.

Diese Frage **muss** das Spike-Dokument beantworten — sonst können Stories 4.2–4.4 nicht implementiert werden.

### Dokumentstruktur `docs/integration/facilioo-spike.md`

Das Spike-Dokument muss folgende Sektionen enthalten:

```markdown
# Facilioo Ticket-API Spike

Datum: YYYY-MM-DD | Durchgeführt von: Daniel Kroll

## Go / No-Go Empfehlung

**Entscheidung: GO / NO-GO (v1.1)**
Begründung: ...

## Auth-Flow

- Methode: Bearer JWT aus `settings.facilioo_bearer_token`
- Status: ✓ verifiziert (ETV-Live-Test 2026-04-29)
- Kein Token-Refresh nötig / Token TTL: ...

## Ticket-Endpoint

- URL: `GET https://api.facilioo.de/api/...`
- HTTP-Status bei Aufruf: 200 / ...
- Pagination: 1-indexed (pageNumber=1), pageSize-Parameter: ...

## DTO-Shape (Ticket)

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| ... | ... | ... | ... |

## Property-Mapping

- Lösung: impower_property_id direkt im DTO vorhanden / neues facilioo_property_id Feld nötig / unklar
- Konsequenz für Stories: ...

## Delta-Support

- ETag: ja / nein
- If-Modified-Since: ja / nein
- Fallback-Strategie für Stories 4.2/4.3: ...

## Rate-Limits

- Beobachtet bei N sequentiellen Calls (AC4): keine 429 / 429 nach Call X mit `Retry-After=N s`
- Header-Felder vorhanden (`X-RateLimit-Remaining`, `X-RateLimit-Reset`, ...): ja/nein
- Empfehlung Default-Throttle für `facilioo_mirror.py`: 1 req/s / schärfer / lockerer — Begründung: ...

## Architektur-Entscheidung: Client-Naming

Option A/B (s. Story 4.1 Dev Notes) — Begründung: ...

## Abhängigkeiten für Stories 4.2–4.4

- 4.2: ...
- 4.3: ...
- 4.4: ...
```

### Kein Unit-Test für Spike

Story 4.1 ist ein Spike — keine automatisierten Tests. Tests kommen in Story 4.2 (`test_facilioo_client_boundary`) und Story 4.3 (`test_facilioo_unit.py` für Delta-Logik + Retry). Im Spike nur manuelle Calls oder `python -c "..."` im Container.

### No-Go-Verhalten

Falls No-Go empfohlen:
1. `docs/integration/facilioo-spike.md` trotzdem vollständig einreichen
2. Sprint-Status: Stories 4.2–4.4 bleiben auf `backlog`, Epic-4 → `backlog` zurücksetzen
3. `FaciliooTicket`-Modell + Migration bleiben im Code (kein Remove nötig) — Tabelle bleibt leer
4. Story 4.4 AC3 greift: UI-Sektion zeigt "Ticket-Integration in Vorbereitung" (bereits im Epic definiert)

## Neue Dateien

- `docs/integration/facilioo-spike.md` (Haupt-Output) — der Ordner `docs/integration/` existiert noch nicht und wird durch das Anlegen der Datei mit erstellt (nichts manuell zu tun)

## Geänderte Dateien

- Optional: `app/services/facilioo_client.py` → Ticket-spezifische `list_tickets()`-Funktion ergänzen (wenn Endpoint bekannt und Go empfohlen, als Vorbereitung für 4.2) — **nur wenn explizit entschieden**
- `output/implementation-artifacts/sprint-status.yaml` — Story 4.1 → `done`

## References

- Epic 4 Acceptance Criteria: `output/planning-artifacts/epics.md` §Story 4.1 (Zeile ~860–890)
- Architektur Sync-Orchestrator (CD3): `output/planning-artifacts/architecture.md` §CD3 (Zeile ~289)
- Architektur Facilioo-Client-Planung: `output/planning-artifacts/architecture.md:582–583`
- Bestehender Facilioo-Client: `app/services/facilioo_client.py` (komplett)
- Facilioo-Konfiguration: `app/config.py:28–29`
- FaciliooTicket-ORM: `app/models/facilioo.py` (komplett)
- FaciliooTicket-Migration: `migrations/versions/0010_steckbrief_core.py:402–430`
- FaciliooTicket-Model-Import: `app/models/__init__.py:6`
- Auth-Beweis (ETV-Workflow): `output/implementation-artifacts/etv-signature-list.md`
- Pagination-Fix-Memory: Memory `reference_facilioo_pagination.md`
- Facilioo-Datenhoheit (was Tickets sind): Memory `reference_facilioo_scope.md`
- Secrets-Bezugsquelle (Bearer-Token): Memory `secrets_1password.md`
- No-Go-Kriterien: `output/planning-artifacts/architecture.md:313`
- Story 4.0 (Sprint-Reihenfolge — parallel zu dieser Story möglich): `output/implementation-artifacts/4-0-code-hygiene-helpers-und-triage.md`
- Einziger Konsument von `facilioo_client.py`: `app/routers/etv_signature_list.py:29`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

2026-04-30: Alle Swagger-Kandidaten 404/500. Direktes Endpoint-Probing ergab: `/api/tickets` 404, `/api/processes` 200 aber propertyId-Filter wirkungslos. `/api/properties/{id}/processes` korrekt gefiltert. Property-Mapping via `externalId`-Feld gelöst. Delta-Support vollständig abwesend (kein ETag, kein Last-Modified, alle „Since"-Params ignoriert). 10 sequentielle GETs ohne 429.

### Completion Notes List

- **GO-Empfehlung** — Token OK, Endpoint gefunden, Property-Mapping lösbar, kein Blocker
- **Ticket-Endpunkt**: `/api/properties/{facilioo_id}/processes` (nicht `/api/tickets`)
- **Container**: `{items, pageNumber, pageSize, totalPages, totalCount, hasPreviousPage, hasNextPage}` → `_get_all_paged` direkt wiederverwendbar
- **Property-Mapping**: `Facilioo.property.externalId` = Impower property_id → dynamischer Lookup, kein neues DB-Feld nötig
- **Delta**: kein ETag/Last-Modified → Full-Pull + lokaler lastModified-Vergleich
- **Rate-Limits**: keine 429 bei 10 Calls, keine Header → 1 req/s als konservativer Default
- **Architektur**: Option A — Rename `facilioo_client.py` → `facilioo.py` (1 Import-Stelle)
- **Fehlendes `is_archived`**: Migration in Story 4.2 erforderlich
- **Token-Ablauf**: JWT exp 2026-05-14, rechtzeitig rotieren

### File List

- `docs/integration/facilioo-spike.md` (neu)
- `output/implementation-artifacts/sprint-status.yaml` (aktualisiert)
- `output/implementation-artifacts/4-1-facilioo-api-spike.md` (Tasks + Status aktualisiert)
