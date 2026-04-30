# Story 4.2: Facilioo-Client mit Retry & Rate-Gate

Status: ready-for-dev

## Story

Als Entwickler,
möchte ich einen hartgehärteten Facilioo-Client nach Impower-Muster (Modul `app/services/facilioo.py`),
damit der nachfolgende Mirror-Job (Story 4.3) und das bestehende ETV-Modul robust gegen 5xx, Timeouts, 429 und Rate-Limits laufen.

## Boundary-Klassifikation

`service-refactor` — Mittleres Risiko. Berührt Live-Pfad (ETV-Unterschriftenliste, seit 2026-04-29 produktiv).
Keine DB-Migration, keine neuen Permissions, keine neuen Audit-Actions. Output ist (a) Modul-Rename + (b) Hardening-Patch + (c) Boundary-Test.

**Vorbedingung:** Story 4.1 (Spike) muss „Go v1" empfehlen. Bei „No-Go v1.1" ist diese Story zurückzustellen — Epic 4 wird auf v1.1 verschoben (Architecture §313). Der Dev prüft vor Beginn `docs/integration/facilioo-spike.md` (Output von Story 4.1) auf die Go-Empfehlung.

**Kritische Risiken:**

1. **ETV-Regression durch Rate-Gate**: `fetch_conference_signature_payload` macht 60+ parallele Calls (Phase 1+2+3). Wenn der Default-Gate (1 req/s) ungebremst auf alle Aufrufer wirkt, geht die PDF-Generierung von ~1 s auf ~60 s — UX-Killer. **Pflicht-Lösung in dieser Story:** Per-Call-Opt-Out `rate_gate=False`, ETV-Aufrufe schalten den Gate ab; Mirror-Pfad (Story 4.3) nutzt Default `rate_gate=True`.
2. **Rename bricht ETV-Imports**: `app/routers/etv_signature_list.py:29` + `tests/test_etv_signature_list.py` (1 Import + 13 Monkey-Patch-Strings auf `app.services.facilioo_client.httpx.AsyncClient`). Werden diese nicht mit umgezogen, bricht ETV live (Import-Error im Container-Start).
3. **Backoff-Total-Time-Risiko**: Mit (2/5/15/30/60 s) summiert ein voll-erschöpfter Retry 112 s. Plus `_TIMEOUT=30 s` pro Versuch ergibt ein Worst-Case von ~262 s pro Call. Im Mirror-Job (1-Min-Loop) ist das toleriert; im ETV-Render-Pfad (User wartet) NICHT — der ETV-Pfad nutzt deshalb nicht nur `rate_gate=False`, sondern bleibt bewusst auf den **alten** 3-Versuche-Defaults via Per-Call-Override (siehe Dev Notes „Backoff-Strategien").
4. **Deferred-Work nicht auflösen**: 7 bekannte Aggregator-/Pagination-Findings (Phase-3 `return_exceptions=True`-Lücke, `_get_all_paged` Bare-List-Truncation, `vg_details[].get("units")` Schema-Drift-Crash, Phase-1-Aggregator ohne Partial-Degradation, `int(total_pages)` ohne try/except, `list_conferences_with_properties` fanout ohne Semaphore, Phase-2-gather PDF-Kill — siehe `output/implementation-artifacts/deferred-work.md` Zeilen 22–24, 37–38, 46, 48) sind **NICHT** Scope dieser Story. Werden sie hier mitgefixt, droht Scope-Creep + erhöhte Review-Last. Im PR-Body explizit als „nicht angefasst" benennen.

## Acceptance Criteria

**AC1 — Client-Modul + Hardening (Singleton, Timeout, 5xx-Backoff, Rate-Gate)**

**Given** der neue Client `app/services/facilioo.py` (Rename aus `app/services/facilioo_client.py`)
**When** ein Aufrufer `_api_get(...)` (oder `_get_all_paged(...)`) verwendet
**Then** läuft der Call durch einen async `httpx.AsyncClient` (Modul-eigener Factory `_make_client()`, analog `app/services/impower.py:_make_client`),
**And** `_TIMEOUT >= 30.0` Sekunden,
**And** 5xx + `httpx.TransportError`/`TimeoutException` lösen Retry mit Exponential-Backoff `(2, 5, 15, 30, 60)` Sekunden, max 5 Versuche, aus,
**And** ein Modul-weites Rate-Gate erlaubt im Default-Modus 1 Request/Sekunde (`_REQUEST_INTERVAL = settings.facilioo_rate_interval_seconds`, Default 1.0),
**And** der Gate ist per Aufruf deaktivierbar (`_api_get(..., rate_gate=False)`) — ETV-Pfad nutzt das, Mirror-Pfad nicht.

**AC2 — 429 mit `Retry-After`-Header**

**Given** Facilioo antwortet mit HTTP 429 und `Retry-After: <seconds>`
**When** `_api_get(...)` parsed
**Then** wartet der Client `int(Retry-After)` Sekunden (Cap 120 s, Floor 1 s) und versucht den Call genau einmal erneut,
**And** ohne `Retry-After`-Header fällt der Client auf 30 s Wait zurück (analog `app/services/impower.py:90`),
**And** der 429-Wait konsumiert keinen 5xx-Retry-Slot (separate Zähler).

**AC3 — HTML-Error-Body sanitisiert**

**Given** Facilioo liefert eine HTML-Error-Page (Status >= 400, Body beginnt mit `<`)
**When** `_api_get(...)` parsed
**Then** wird die Message via `app.services._sync_common.strip_html_error(resp.text)` gekürzt,
**And** als `FaciliooError(message, status_code=resp.status_code)` geworfen,
**And** der bestehende Inline-`_sanitize_error` ist entfernt (kein Code-Duplikat zu `_sync_common`).

**AC4 — Boundary-Test: kein Facilioo-Call außerhalb von `facilioo.py`**

**Given** der Unit-Test `tests/test_facilioo_client_boundary.py::test_no_facilioo_calls_outside_gate`
**When** er über alle `.py` unter `app/` läuft (außer Allow-List `app/services/facilioo.py` + `app/config.py` + `app/services/facilioo_mirror.py` für Story 4.3)
**Then** findet er keinen weiteren Treffer für die Tokens `facilioo_bearer_token` oder `facilioo_base_url` (Heuristik: nur das Gate-Modul + Settings dürfen den Token referenzieren),
**And** ein Self-Check (analog `tests/test_write_gate_coverage.py:test_coverage_scan_finds_seeded_violation`) verifiziert, dass die Heuristik einen synthetischen Verstoß tatsächlich findet.

## Tasks / Subtasks

- [ ] **Task 1: Rename `facilioo_client.py` → `facilioo.py`** (AC1)
  - [ ] 1.1: `git mv app/services/facilioo_client.py app/services/facilioo.py` (Git-History bleibt erhalten)
  - [ ] 1.2: `app/routers/etv_signature_list.py` — Multi-Line-Import in Zeilen 29–34 auf `from app.services.facilioo import (...)` umstellen (Modul-Pfad in Zeile 29 ändern, die 4 Symbole `FaciliooError, fetch_conference_signature_payload, list_conferences, list_conferences_with_properties` bleiben unverändert)
  - [ ] 1.3: `tests/test_etv_signature_list.py` — globaler Sed-Replace `facilioo_client` → `facilioo` (`sed -i '' 's/facilioo_client/facilioo/g' tests/test_etv_signature_list.py`). Trifft 11 Monkey-Patch-Strings (`app.services.facilioo_client.httpx.AsyncClient`), 2 Import-Zeilen (26 + 227), ~15 direkte Modul-Verwendungen (`facilioo_client.list_conferences()`, `facilioo_client.MEA_ATTRIBUTE_ID`, `facilioo_client.FaciliooError`, `facilioo_client.fetch_conference_signature_payload`, …) UND den lokalen Helper `def _patched_facilioo_client(handler):` (Zeile 211 + alle Aufrufer) → wird zu `_patched_facilioo`. Helper-Rename ist datei-lokal und harmlos, aber bewusst flag — danach manuell sichten
  - [ ] 1.4: Smoke: `pytest tests/test_etv_signature_list.py -x` muss grün bleiben (Pre-Hardening, nur Rename)

- [ ] **Task 2: Settings + Konstanten erweitern** (AC1, AC2)
  - [ ] 2.1: `app/config.py` — Feld `facilioo_rate_interval_seconds: float = 1.0` hinzufügen, Doc-Kommentar verweist auf den Gate
  - [ ] 2.2: In `app/services/facilioo.py` Konstanten anpassen: `_MAX_RETRIES_5XX = 5`, `_RETRY_DELAYS_5XX: tuple[int, ...] = (2, 5, 15, 30, 60)`, `_TIMEOUT = 30.0` (bleibt), `_REQUEST_INTERVAL = settings.facilioo_rate_interval_seconds`
  - [ ] 2.3: Modul-State: `_rate_lock = asyncio.Lock()` + `_last_request_time: float = 0.0` (analog `app/services/impower.py:43–44`)

- [ ] **Task 3: Rate-Gate implementieren** (AC1)
  - [ ] 3.1: `async def _rate_limit_gate() -> None` 1:1 nach `app/services/impower.py:59–66` portieren, aber `_REQUEST_INTERVAL` statt `_REQUEST_DELAY` benutzen
  - [ ] 3.2: `_api_get(...)`-Signatur erweitern um `*, rate_gate: bool = True`; bei `rate_gate=True` zuerst `await _rate_limit_gate()`
  - [ ] 3.3: `_get_all_paged(...)`-Signatur ebenfalls um `*, rate_gate: bool = True` erweitern, an `_api_get` durchreichen
  - [ ] 3.4: Alle ETV-Public-Funktionen (`list_conferences`, `list_conferences_with_properties`, `get_conference`, `get_conference_property`, `list_voting_group_shares`, `get_voting_group`, `list_mandates`, `list_unit_attribute_values`, `fetch_conference_signature_payload`) rufen die internen Helpers mit `rate_gate=False` auf — ETV-Performance bleibt unverändert (60+ parallele Calls erlaubt)

- [ ] **Task 4: 429-Handling mit `Retry-After`** (AC2)
  - [ ] 4.1: Im `_api_get(...)`-Body NACH dem Response-Get + VOR dem 5xx-Block: `if resp.status_code == 429:` → Header `Retry-After` parsen
  - [ ] 4.2: Parsing-Hilfsfunktion `_parse_retry_after(value: str | None) -> int` — akzeptiert nur Integer-Sekunden (kein HTTP-Date-Parsing — Facilioo dokumentiert das nicht); Floor 1, Cap 120, Fallback 30 bei `None`/Parse-Error
  - [ ] 4.3: 429-Pfad ruft `await asyncio.sleep(wait)` und retried mit unverändertem `_attempt`-Counter (verbraucht keinen 5xx-Slot); separater Counter `_rate_attempt: int = 0` mit Cap 3, sonst Endlos-Retry-Risiko
  - [ ] 4.4: Wenn `_rate_attempt > 3`: `raise FaciliooError("Rate-Limit nach 3 Retries weiterhin aktiv", 429)`

- [ ] **Task 5: HTML-Error-Sanitizer auf `_sync_common.strip_html_error` migrieren** (AC3)
  - [ ] 5.1: `from app.services._sync_common import strip_html_error` ergänzen
  - [ ] 5.2: Inline-`_sanitize_error(resp)` ersetzen durch:
    ```python
    if resp.text.strip().startswith("<"):
        msg = strip_html_error(resp.text, limit=300) or f"HTTP {resp.status_code} (HTML-Body)"
    else:
        msg = resp.text.strip()[:300]
    raise FaciliooError(msg, resp.status_code)
    ```
  - [ ] 5.3: Funktion `_sanitize_error` komplett entfernen (kein Soft-Delete, kein Re-Export)

- [ ] **Task 6: Unit-Tests `test_facilioo_unit.py`** (AC1, AC2, AC3)
  - [ ] 6.1: Neue Datei `tests/test_facilioo_unit.py` anlegen, Pattern analog `tests/test_etv_signature_list.py:_patched_facilioo_client` (httpx.MockTransport)
  - [ ] 6.2: Test `test_5xx_retry_consumes_full_backoff_sequence` — Handler liefert 5x 503, 1x 200 → `asyncio.sleep`-Mock zählt Aufrufe → erwartet exakt `[2, 5, 15, 30, 60]`
  - [ ] 6.3: Test `test_5xx_max_retries_then_raises` — Handler liefert 6x 503 → erwartet `FaciliooError(status_code >= 500)` nach 5. Retry
  - [ ] 6.4: Test `test_429_respects_retry_after_header` — Handler liefert 1x 429 mit `Retry-After: 7`, dann 200 → `asyncio.sleep`-Mock zeigt 1x `sleep(7)`
  - [ ] 6.5: Test `test_429_caps_retry_after_at_120` — Handler liefert `Retry-After: 600` → tatsächlicher Sleep ist 120
  - [ ] 6.6: Test `test_429_fallback_30s_without_header` — Handler liefert 429 ohne Retry-After → Sleep 30
  - [ ] 6.7: Test `test_429_caps_retries_at_3` — Handler liefert dauerhaft 429 mit `Retry-After: 1` → erwartet `FaciliooError(status_code=429)` mit Message-Substring "Rate-Limit nach 3 Retries". Verifiziert die `_rate_attempt > 3`-Grenze aus Task 4.4 (Endlos-Retry-Schutz)
  - [ ] 6.8: Test `test_html_error_uses_strip_html_error` — Handler liefert 502 mit Body `<html>...nginx fehler...</html>` → `FaciliooError.args[0]` enthält `nginx fehler` ohne `<html>`/`<body>`
  - [ ] 6.9: Test `test_rate_gate_spaces_calls` — 3 sequenzielle `_api_get(rate_gate=True)`-Aufrufe → `time.monotonic`-Differenzen >= `_REQUEST_INTERVAL` (Mock-bar via `monkeypatch` auf `time.monotonic`/`asyncio.sleep`)
  - [ ] 6.10: Test `test_rate_gate_skip_does_not_serialize` — 5 parallele `_api_get(rate_gate=False)`-Aufrufe → komplette Wall-Time < 0.1 s (kein Gate)
  - [ ] 6.11: Test `test_etv_paths_skip_rate_gate` — Smoke: `await list_conferences()` mit Mock-Handler, der 3 schnelle 200er liefert; Wall-Time < 0.5 s (Regression-Schutz: ETV bleibt parallel)

- [ ] **Task 7: Boundary-Test `test_facilioo_client_boundary.py`** (AC4)
  - [ ] 7.1: Neue Datei `tests/test_facilioo_client_boundary.py`, Pattern analog `tests/test_write_gate_coverage.py`
  - [ ] 7.2: Allow-List: `{app/config.py, app/services/facilioo.py, app/services/facilioo_mirror.py}` (letzteres entsteht in Story 4.3 — bereits jetzt erlauben, damit der Test stabil bleibt)
  - [ ] 7.3: Heuristik: Walk `app/**/*.py`, suche literale Strings `facilioo_bearer_token` oder `facilioo_base_url` außerhalb der Allow-List → fail
  - [ ] 7.4: Test `test_no_facilioo_calls_outside_gate` — soll auf aktueller Code-Basis grün laufen
  - [ ] 7.5: Test `test_boundary_scan_finds_seeded_violation(tmp_path, monkeypatch)` — Self-Check (analog `test_write_gate_coverage:test_coverage_scan_finds_seeded_violation`): synthetisches File `fake.py` mit `httpx.AsyncClient(... settings.facilioo_bearer_token ...)` → `pytest.raises(AssertionError)`

- [ ] **Task 8: Smoke-Run + Sprint-Status** (AC1–AC4)
  - [ ] 8.1: `pytest tests/test_facilioo_unit.py tests/test_facilioo_client_boundary.py tests/test_etv_signature_list.py -v` — alle grün
  - [ ] 8.2: `pytest` (Full-Suite) — keine neuen Failures (Soll: 851+ → 851+ + neue)
  - [ ] 8.3: Sprint-Status: Story 4.2 → `review` (Hand-Off an Code-Review)

## Dev Notes

### Was bereits existiert — NICHT neu bauen

| Artifact | Pfad | Inhalt |
|---|---|---|
| Facilioo-Read-Client (zu rename) | `app/services/facilioo_client.py` | `_make_client`, `_api_get`, `_get_all_paged`, `FaciliooError`, `MEA_ATTRIBUTE_ID`, 8 Public-Funktionen + Aggregator |
| Facilioo-Settings | `app/config.py:28–29` | `facilioo_base_url`, `facilioo_bearer_token` (existieren) |
| Impower-Client (Vorbild) | `app/services/impower.py:39–101` | Konstanten + `_rate_limit_gate` + `_api_get`-Pattern, das wir 1:1 nach `facilioo.py` übertragen (modulo `_REQUEST_INTERVAL` statt `_REQUEST_DELAY`, `FaciliooError` statt `_error`-Dict) |
| `_sync_common.strip_html_error` | `app/services/_sync_common.py:117–130` | HTML-Tag-Strip + Whitespace-Collapse + Truncate. Bereits getestet in `tests/test_sync_common_unit.py:27–39`. Wir importieren, schreiben nicht neu. |
| ETV-Importer (zu aktualisieren) | `app/routers/etv_signature_list.py:29–34` | Multi-Line-Import mit 4 Symbolen — nur Modul-Pfad in Zeile 29 umstellen, die Symbol-Liste in 30–33 bleibt |
| ETV-Test-Patches (zu aktualisieren) | `tests/test_etv_signature_list.py` | 2 Import-Zeilen (26 + 227), 11 Monkey-Patch-Strings + ~15 direkte `facilioo_client.X`-Verwendungen + lokaler Helper `_patched_facilioo_client` (Def Zeile 211, Aufrufer 264/298/327/363/473/493/526/540/555/572/604). **Globaler Sed-Replace `facilioo_client` → `facilioo`** umzusetzen, dann manuell sichten — der Helper-Rename ist datei-lokal und akzeptiert. |
| Boundary-Test-Pattern (Vorbild) | `tests/test_write_gate_coverage.py` | Vollständiges Vorbild für AC4 inkl. Self-Check-Pattern. Einfach klonen, Heuristik austauschen. |

### Architektur-Entscheidung: Naming + Singleton-Auslegung

Story 4.1 (Spike, parallel ready-for-dev) empfiehlt Option A (Rename). Diese Story zieht das durch — und übernimmt damit die in `output/planning-artifacts/architecture.md:642` festgelegte Boundary „`facilioo.py` ist einziger Facilioo-Client".

„Singleton" in der AC ist **nicht** „eine globale `httpx.AsyncClient`-Instanz" — Impower nutzt auch keine. Lesart: **„modulares Singleton" = nur ein Modul (`facilioo.py`) ist die einzige Quelle für Facilioo-Clients**, alle Aufrufer rufen dessen Public-Funktionen, niemand baut sich einen eigenen `httpx.AsyncClient` mit dem Bearer-Token. Der Boundary-Test (AC4) ist der konkrete Mechanismus, der das durchsetzt.

**Konkret:** `_make_client()` bleibt eine Factory-Funktion, die pro Call einen neuen `AsyncClient` baut (`async with _make_client() as client:` ist das Caller-Muster). Modul-Singleton-Charakter ergibt sich aus dem Pattern, nicht aus einer globalen Instanz. Genau wie Impower (`app/services/impower.py:146–153`).

### Rate-Gate-Trade-off — kritisch für ETV

ETV-Aggregator (`fetch_conference_signature_payload`) macht in 3 Phasen 60+ parallele Calls (1 Conference + 1 Property + ~8 VG-Shares + ~8 VG-Details + ~50 Unit-Attributes). Heute ohne Gate: ~1–2 s Wall-Time. Mit Default-Gate (1 req/s) seriell: 60+ s = UX-Bruch.

Lösung: **Per-Call-Opt-Out** `rate_gate=False`. Alle ETV-Public-Funktionen (`list_conferences`, …, `fetch_conference_signature_payload`) reichen `rate_gate=False` an die internen Helpers durch. Der Default `True` greift nur für Aufrufer, die das nicht tun — das ist absichtlich der Mirror-Pfad in Story 4.3.

**Code-Skeleton (Task 3.4):**
```python
async def list_conferences() -> list[dict]:
    async with _make_client() as client:
        return await _get_all_paged(client, "/api/conferences", rate_gate=False)

async def fetch_conference_signature_payload(conf_id: int | str) -> dict:
    async with _make_client() as client:
        # Phase 1
        conf_task = _api_get(client, f"/api/conferences/{conf_id}", rate_gate=False)
        prop_task = _api_get(client, f"/api/conferences/{conf_id}/property", rate_gate=False)
        # ... etc.
```

Story 4.3 ruft den (zu schaffenden) `_api_get(..., rate_gate=True)`-Pfad oder dessen Default; das serialisiert die Mirror-Calls auf 1 req/s.

### Backoff-Strategien — Total-Time im ETV-Pfad bewusst kurz halten

Das Hardening (`_MAX_RETRIES_5XX = 5`, Backoff bis 60 s) ist für den Mirror-Job dimensioniert (Worst-Case 112 s + 5× 30 s Timeout = 262 s pro Call ist im 1-Min-Loop tolerierbar, weil der nächste Tick eh wieder ansetzt).

Im **ETV-Render-Pfad** wartet aber der User. 262 s pro fehlgeschlagenem Call × 60 parallele Calls = ein hängender Browser. **Aktuell akzeptiert** — die Story-Scope ist Hardening, nicht ETV-Latenz-Optimierung. Aber bewusst hier dokumentiert, damit kein folgender Code-Reviewer das als Regression flaggt.

Falls später nötig: zusätzlicher Per-Call-Override `max_retries=3` einführen; ETV-Funktionen passen `max_retries=3` mit. Im Scope dieser Story **nicht** umsetzen.

### 429-Handling — `Retry-After`-Format-Annahme

Facilioo dokumentiert kein `Retry-After`-Format. Annahme: nur Integer-Sekunden (häufigste Variante). HTTP-Date (`Wed, 01 Jan 2025 …`) wird **nicht** geparst — Fallback 30 s. Das ist eine bewusste Vereinfachung; sollte Facilioo HTTP-Date liefern, fällt der Client gnädig auf 30 s zurück und retried trotzdem (kein Crash).

`_parse_retry_after`-Cap 120 s schützt gegen ein Server, der versehentlich „1800" oder „86400" zurückgibt — der Mirror-Loop tickt minütlich, da hat ein Sleep > 120 s eh keinen Mehrwert.

**Separater Retry-Counter:** Der 5xx-Counter (`_attempt`) ist von 429 entkoppelt. 429 hat eigenen Counter `_rate_attempt` (Cap 3). Sonst:
- 5xx + 429 + 5xx + 429 + 5xx → konsumiert nur 3 5xx-Slots, lässt aber 429er beliebig oft retry → Endlos-Loop möglich
- Mit getrenntem Counter ist der Worst-Case bounded: 5× 5xx-Backoff + 3× 429-Backoff (max 120 s) = ~470 s — OK für den Mirror, dramatisch für ETV (deshalb dort `rate_gate=False` und konsumiert keinen 429-Pfad — Facilioo-Gateway gibt im ETV-Use-Case bisher nie 429 zurück).

### HTML-Error → `strip_html_error` (Code-Duplikat-Eliminierung)

Aktuell hat `facilioo_client.py` ein eigenes `_sanitize_error`, das HTML-Bodies erkennt und einen Marker-String produziert. `_sync_common.strip_html_error` macht das gleiche und wird bereits von `app/services/steckbrief_impower_mirror.py` (indirekt über `run_sync_job`) genutzt. Konsolidierung jetzt + bei zukünftiger Veränderung wirken beide Pfade konsistent.

**Migration:** alte Marker-Message (`"HTTP {status} — Facilioo-Gateway hat HTML statt JSON geliefert (meist Upstream-Stoerung)."`) entfällt — `strip_html_error` liefert den ersten Klartext-Satz aus dem HTML; das ist informativ + ähnlich kompakt. Falls ein Test gegen den alten Marker-Text greppt, mitanpassen (im Repo: keiner — nur `tests/test_etv_signature_list.py:557` checkt `pytest.raises(facilioo_client.FaciliooError)` ohne Message-Match).

### Boundary-Test-Heuristik

`tests/test_facilioo_client_boundary.py` ist **nicht** AST-basiert; das wäre Overkill. Heuristik:

1. Walk `app/**/*.py`.
2. Skip: `app/config.py` (definiert Settings), `app/services/facilioo.py` (das Gate selbst), `app/services/facilioo_mirror.py` (Story 4.3 Konsument).
3. Suche literal `facilioo_bearer_token` oder `facilioo_base_url`.
4. Hits = Verstoß.

Begründung: Wer den Token oder die Base-URL referenziert, baut sich vermutlich einen eigenen httpx-Client und bricht die Boundary. Tests in `tests/` sind **nicht** im Scan (Tests dürfen patchen).

**Self-Check (Task 7.5):** schreibe ein synthetisches `fake.py` mit dem Pattern in `tmp_path`, monkeypatche `_SCAN_DIRS` darauf, erwarte `AssertionError`. Vorbild 1:1 in `tests/test_write_gate_coverage.py:176–198`.

### Settings-Erweiterung

```python
# app/config.py — direkt nach facilioo_bearer_token einfügen
facilioo_rate_interval_seconds: float = 1.0
"""Mindest-Abstand zwischen Facilioo-Requests (Sekunden), gilt im
Mirror-Pfad (Story 4.3). ETV-Pfad ueberspringt den Gate via
rate_gate=False, weil Aggregator 60+ parallele Calls benoetigt."""
```

Pydantic-Settings nimmt das via Env-Var `FACILIOO_RATE_INTERVAL_SECONDS` auf — Prod-Override via Elestio-UI möglich.

### Tests-Mock-Pattern für asyncio.sleep

Backoff-Sequenzen über echte `asyncio.sleep`-Wartezeiten zu testen ist absurd langsam (2+5+15+30+60 = 112 s pro Test). Pattern: `monkeypatch` auf `app.services.facilioo.asyncio.sleep`, ersetzt durch eine Liste-Aufzeichnung:

```python
sleeps: list[float] = []

async def fake_sleep(seconds):
    sleeps.append(seconds)

monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)
```

Im Test dann `assert sleeps == [2, 5, 15, 30, 60]`. Genauso für `_rate_limit_gate`-Tests: zusätzlich `time.monotonic` patchen, falls der Gate auf monotonic-Differenzen reagiert.

**Achtung:** `asyncio.sleep` wird auch innerhalb der Mock-Helpers gerne aufgerufen (z. B. in `_patched_facilioo_client` selbst). Sicherer: nur die `sleep` aus dem Modul `app.services.facilioo` patchen, nicht global `asyncio.sleep`. `monkeypatch.setattr` mit Modul-Pfad statt globalem Namespace.

### Dokumentations-Aktualisierungen (begleitend, nicht Pflicht-Scope)

`docs/project-context.md` listet unter „Critical Don't-Miss Rules":

> **Impower-Client** [...] - Timeouts **immer** 120 s + 5xx-Retry mit Exponential-Backoff; Transient-503 vom Gateway ist normal.

Analog-Eintrag für Facilioo wäre konsistent:
> **Facilioo-Client**: Timeout 30 s, 5xx-Retry (2/5/15/30/60), Rate-Gate 1 req/s im Mirror-Pfad, ETV-Pfad opt-out via `rate_gate=False`.

Im Scope dieser Story **optional** — wenn Story 4.3 (Mirror) live ist, sinnvoller im selben Update zu pflegen.

### Migrations-Schritt für Story 4.3 (Foreshadow)

`FaciliooTicket`-Modell in `app/models/facilioo.py` hat heute kein `is_archived`-Feld (siehe Story 4.1 Dev Notes). Story 4.3 wird dafür eine Alembic-Migration brauchen. **In dieser Story 4.2 NICHT antasten** — Scope ist Client-Hardening.

### Archivierte Doku-Referenzen — bewusst unverändert lassen

Die Markdown-Files unter `output/implementation-artifacts/etv-signature-list.md`, `output/implementation-artifacts/etv-signature-list-pdf-anpassungen.md` und `output/implementation-artifacts/deferred-work.md` referenzieren `app/services/facilioo_client.py:NNN` an mehreren Stellen. Diese sind **historische Story-/Review-Records** — Pfad und Zeilennummern werden mit dem Rename + Hardening obsolet, aber das ist OK: ein zukünftiger Picker re-greppt vor Bearbeitung sowieso. **Nicht in dieser Story aktualisieren** (würde 15+ Stellen-Updates ohne Geschäftsnutzen verursachen).

### Fallstricke aus Plattform-Regeln (`docs/project-context.md`)

- **Imports absolut**: `from app.services._sync_common import strip_html_error` (nicht `from .._sync_common import ...`).
- **Reihenfolge**: stdlib → 3rd-party (`httpx`) → `app.*`. Konsistent mit existierendem File.
- **Async/Sync**: Alle Helpers bleiben `async def`. Keine `asyncio.run`-Aufrufe im Modul (das ist Aufrufer-Verantwortung in BackgroundTasks).
- **Logging**: `print(...)` reicht für Ops-Visibility; bestehender `_logger = logging.getLogger(__name__)` darf weiterleben (wird von der bestehenden Pagination-Warnung genutzt). Nicht neu konfigurieren.
- **Eigene Exception**: `FaciliooError` bleibt; **nicht** auf generisches `Exception` umstellen.

## Neue Dateien

- `tests/test_facilioo_unit.py` — 5xx-Backoff + 429 (inkl. Cap-3) + HTML-Error + Rate-Gate-Spacing + ETV-Skip-Smoke (Tests 6.2–6.11)
- `tests/test_facilioo_client_boundary.py` — Boundary-Heuristik + Self-Check (Tests 7.4–7.5)

## Geänderte Dateien

- `app/services/facilioo_client.py` → `app/services/facilioo.py` (Rename via `git mv`, danach Hardening-Patch)
- `app/routers/etv_signature_list.py` — Multi-Line-Import-Block (Zeilen 29–34, nur Modul-Pfad)
- `app/config.py` — neuer Setting `facilioo_rate_interval_seconds: float = 1.0`
- `tests/test_etv_signature_list.py` — globaler `facilioo_client` → `facilioo` Sed-Replace (2 Imports + 11 Monkey-Patches + ~15 direkte Verwendungen + lokaler Helper)
- `output/implementation-artifacts/sprint-status.yaml` — Story 4.2 → `review` nach Smoke (Task 8.3)

## References

- Epic 4 Acceptance Criteria: `output/planning-artifacts/epics.md:898–920`
- Architektur Sync-Orchestrator (CD3): `output/planning-artifacts/architecture.md:284–313`
- Architektur Integrations-Patterns: `output/planning-artifacts/architecture.md:496–503`
- Architektur Facilioo-Boundary: `output/planning-artifacts/architecture.md:642`
- Architektur Tests-Sektion: `output/planning-artifacts/architecture.md:624` (`test_facilioo_unit.py` Delta-Logik + 429-Retry + Timeout)
- Vorgänger-Story (Spike): `output/implementation-artifacts/4-1-facilioo-api-spike.md` (Architektur-Entscheidung Option A: Rename)
- Impower-Client-Vorbild: `app/services/impower.py:27–101` (Konstanten + Rate-Gate + `_api_get`)
- HTML-Sanitizer: `app/services/_sync_common.py:117–130` (`strip_html_error`)
- HTML-Sanitizer-Tests: `tests/test_sync_common_unit.py:27–39`
- Zu-renamender Client: `app/services/facilioo_client.py` (komplett, 386 Zeilen)
- ETV-Importer: `app/routers/etv_signature_list.py:29–34`
- ETV-Tests (umzubauen): `tests/test_etv_signature_list.py:26, 211–219, 227, 263, 297, 326, 362, 472, 492, 525, 539, 554, 571, 603` plus alle direkten `facilioo_client.X`-Aufrufe — Sed-Replace deckt alle
- Boundary-Test-Vorbild: `tests/test_write_gate_coverage.py` (komplett)
- Bekannte Aggregator-/Pagination-Findings (NICHT Scope): `output/implementation-artifacts/deferred-work.md:22–24, 37–38, 46, 48`
- Live-Bug-Doku ETV (Pagination 1-indexed, schon gefixt): `output/implementation-artifacts/etv-signature-list.md` Sektion „Live-Bug-Fixes"
- Plattform-Regeln (Imports, Async, Logging): `docs/project-context.md` §Framework-Specific Rules + §Critical Don't-Miss Rules

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

### Completion Notes List

### File List
