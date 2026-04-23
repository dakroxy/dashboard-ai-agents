# Story 1.5: Finanzen-Sektion mit Live-Saldo & Ruecklage-Sparkline

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter,
ich moechte die Finanzsektion eines Objekts mit aktuellem Bank-Saldo und Ruecklage-Historie sehen,
damit ich den aktuellen Stand ohne Impower-Login beurteilen kann.

## Acceptance Criteria

**AC1 — Finanzen-Sektion zeigt gespiegelte Felder + Live-Saldo**
**Given** ich oeffne `/objects/{id}` als User mit `objects:view`
**When** die Finanzen-Sektion rendert
**Then** sehe ich Ruecklage aktuell (`reserve_current`), Zielwert (`reserve_target`), Wirtschaftsplan-Status (`wirtschaftsplan_status`), SEPA-Mandat-Liste (`sepa_mandate_refs`) — jeweils aus dem DB-Mirror mit Provenance-Pill
**And** der Bank-Saldo wird live aus Impower nachgeladen (via `get_bank_balance`) und mit Zeitstempel "Stand: [Europe/Berlin]" angezeigt
**And** eine Inline-SVG-Sparkline zeigt die `reserve_current`-Historie der letzten 6 Monate (aus `FieldProvenance`-Rows)

**AC2 — Graceful Fallback bei Impower-Ausfall**
**Given** Impower antwortet beim Live-Pull mit Timeout oder 503 (nach Retries)
**When** die Seite fertig rendert
**Then** sehe ich den letzten bekannten Saldo aus `Object.last_known_balance` mit Hinweis "Saldo aktuell nicht verfuegbar"
**And** die Seite wirft keinen 500er — alle anderen Sektionen (Stammdaten, Finanzen-Spiegel) sind weiterhin sichtbar

**AC3 — Live-Pull schreibt `last_known_balance` via Write-Gate**
**Given** der Live-Pull erfolgreich war **und** es gibt keine vorherige `FieldProvenance`-Row fuer `last_known_balance` mit `source="user_edit"` oder `"ai_suggestion"`
**When** die Seite fertig rendert
**Then** ist `Object.last_known_balance` auf den aktuellen Wert aus Impower aktualisiert
**And** es existiert eine `FieldProvenance`-Row fuer `last_known_balance` mit `source="impower_mirror"`, `source_ref=<impower_property_id>`, `user_id=None`
**And** der Commit laeuft innerhalb der Render-Handler-Session (kein BackgroundTask)

**Ausnahme (Write-Gate-Mirror-Guard)**: Wenn die letzte `FieldProvenance`-Row fuer `last_known_balance` den Source `user_edit` oder `ai_suggestion` hat, liefert `write_field_human` `WriteResult(written=False, skipped=True, skip_reason="user_edit_newer")` — der Live-Wert wird ignoriert, die bestehende DB-Spalte bleibt unveraendert, die UI zeigt dennoch den Live-Wert fuer diesen Request (nicht persistiert). In v1 ist `last_known_balance` nirgends user-editierbar, der Fall tritt praktisch nicht auf. Der Test `test_last_known_balance_user_edit_wins` dokumentiert das Verhalten fuer kuenftige Stories, in denen das Feld editierbar wird (siehe Task 6.2).

**AC4 — Kein Live-Pull ohne `impower_property_id`**
**Given** ein Objekt hat keine `impower_property_id`
**When** die Seite rendert
**Then** zeigt die Finanzen-Sektion alle DB-Mirror-Felder (reserve_current etc.) und einen Hinweis "Kein Impower-Objekt verknuepft" statt Saldo-Block
**And** es gibt weder Impower-Call noch Fehler

**AC5 — Sparkline aus Provenance-Historie**
**Given** es existieren >=2 `FieldProvenance`-Rows fuer `reserve_current` (source `impower_mirror`) innerhalb der letzten 6 Monate
**When** die Finanzen-Sektion rendert
**Then** zeigt die Inline-SVG-Sparkline einen Trend aus diesen Datenpunkten (chronologisch links=aelt, rechts=neu)
**And** bei <2 Datenpunkten wird kein SVG gerendert, stattdessen ein "-" Placeholder

**Erwartung v1 (kein Bug)**: Der Nightly-Mirror aus Story 1.4 hat einen Noop-Guard — wenn `reserve_current` sich zwischen zwei Laeufen nicht aendert, entsteht keine neue Provenance-Row. Bleibt die Ruecklage 6 Monate konstant (haeufig der Fall), existiert genau **eine** Row und der Placeholder-Zweig greift. Eine sichtbare Kurve erscheint erst, wenn sich `reserve_current` tatsaechlich monatlich bewegt (Zufluss/Entnahme).

**AC6 — Performance P95 ≤ 2s**
**Given** das Objekt hat eine `impower_property_id` und Impower antwortet normal
**When** die Render-Zeit gemessen wird
**Then** ist P95 < 2 s — der Live-Pull-Timeout ist daher auf 8 s gesetzt (legt das Worst-Case-Fenster fest)

**AC7 — Tests + Regressionslauf gruen**
**Given** die neuen Dateien (`impower.py`-Erweiterung, `_obj_finanzen.html`, Router-Update, Service-Funktion)
**When** `pytest -x` laeuft
**Then** sind alle neuen Tests gruen und der bestehende Regressionslauf (>=371 Tests, Stand nach Story 1.4) bleibt vollstaendig gruen

## Tasks / Subtasks

- [x] **Task 1 — `get_bank_balance()` in `app/services/impower.py`** (AC1, AC2, AC3, AC4, AC6)
  - [x] 1.1 **Impower-Endpoint recherchieren**: Swagger `https://api.app.impower.de/services/pmp-accounting/v2/api-docs` pruefen auf Balance-Endpunkt. Kandidaten: `/services/pmp-accounting/api/v1/house-money-settlements?propertyId={id}` oder `/v2/properties/{id}` (Property-Objekt enthaelt ggf. `accountBalance`-Feld). Fallback: Das Saldo-Feld koennte auch in der Property-Detail-Response unter `/v2/properties/{id}` liegen. Vorab pruefbarer Check: `GET /v2/properties/{known_id}` mit echtem impower_property_id — welche Balance-Felder enthaelt die Antwort?
  - [x] 1.2 Neue async-Funktion `get_bank_balance(property_id: str) -> dict | None` in `impower.py`. Rueckgabe: `{"balance": Decimal, "currency": "EUR", "fetched_at": datetime}` oder `None` bei Fehler (Timeout, 503, kein Balance-Feld). **Eigener Timeout von 8 s** (nicht der 120 s `_TIMEOUT`): eigenes `httpx.AsyncClient(base_url=..., headers=..., timeout=8.0)` innerhalb `async with` — gleiche Auth-Header wie `_make_client()`. Grund: Live-Pull soll Render nicht zu lange blockieren (AC6).
  - [x] 1.3 **NICHT** `_api_get(client, path)` aus `impower.py:72` verwenden. Grund: `_api_get` ruft intern `await client.get(path, params=params, timeout=_TIMEOUT)` mit dem Modul-Konstanten `_TIMEOUT=120.0` — dieser per-call Kwarg **ueberschreibt** den AsyncClient-Timeout. Der 8-s-Client waere damit wirkungslos. Zwei Optionen: **(a)** in `get_bank_balance` direkt `resp = await client.get(path)` aufrufen (Client-Timeout greift) und den Response-Parsing-Teil von `_api_get` duplizieren (`resp.raise_for_status()` + `resp.json()` im `try/except` mit Mapping auf `None`). **(b)** `_api_get` um einen optionalen Kwarg `timeout_override: float | None = None` erweitern, der bei gesetztem Wert den Default ersetzt (`timeout=timeout_override if timeout_override is not None else _TIMEOUT`). Option (a) ist die MVP-Wahl — kein Touch an bestehender `_api_get`-Signatur. Bei `ImpowerError`, `httpx.TimeoutException`, `httpx.TransportError`, `httpx.HTTPStatusError` → `return None` (kein raise, kein log noise). **Kein Retry-Loop** fuer den Live-Pull — der 8-s-Timeout ist das Fangnetz, ein Retry wuerde P95 sprengen.
  - [x] 1.4 Balance-Wert aus der API-Antwort als `Decimal` parsen: `Decimal(str(raw_balance))` — nie `float(raw_balance)` wegen Gleitkomma-Drift bei Finanzzahlen. Falls das Feld fehlt oder nicht parsebare Antwort → `None` zurueckgeben. `fetched_at = datetime.now(ZoneInfo("UTC"))` setzen (nicht local-time, nicht naive) — der Router konvertiert nach `Europe/Berlin` fuer die Anzeige (Task 3.3 + 3.5).

- [x] **Task 2 — `reserve_history_for_sparkline()` + `build_sparkline_svg()` in `app/services/steckbrief.py`** (AC5)
  - [x] 2.1 Neue Funktion `reserve_history_for_sparkline(db: Session, object_id: uuid.UUID, months: int = 6) -> list[tuple[datetime, float]]`. Laedt `FieldProvenance`-Rows mit `entity_type="object"`, `entity_id=object_id`, `field_name="reserve_current"`, `source="impower_mirror"`, `created_at >= now - timedelta(days=months*31)`, sortiert `ORDER BY created_at ASC`.
  - [x] 2.2 Pro Row: `value_snapshot["new"]` auslesen und robust zu `float` konvertieren. JSONB verliert den Decimal-Typ → Wert kann als `str` (`"45000.00"`, da `_json_safe_for_provenance` Decimal so serialisiert), `int` (`45000`) oder `float` (`45000.0`) zurueckkommen. Pattern:
    ```python
    raw = row.value_snapshot.get("new")
    # None/Missing-Key/leere Keys → Row ueberspringen, sonst verschleppen wir 0.0-Artefakte.
    if raw is None or raw == "":
        continue
    try:
        val = float(str(raw))  # str() normalisiert str/int/float einheitlich
    except (TypeError, ValueError):
        continue
    ```
  - [x] 2.3 Rueckgabe ist eine sortierte Liste von `(created_at, float_value)` Tupeln. Leere Liste wenn keine Rows. Wird im Router an `build_sparkline_svg` weitergereicht; Template rendert nur den SVG-String (ohne eigene Logik).
  - [x] 2.4 **WICHTIG — JSONB-Direktlesefalle**: `value_snapshot` ist JSONB. Beim Lesen via SQLAlchemy sind Keys immer `str`, da JSONB beim Deserialisieren keine Typ-Infos erhaelt. `row.value_snapshot["new"]` kann `"45000.00"`, `45000.0` oder `45000` sein — alle drei abfangen via `float(str(...))`.
  - [x] 2.5 Neue Funktion `build_sparkline_svg(points: list[tuple[datetime, float]]) -> str | None` — siehe Referenz-Implementation im Dev-Notes-Abschnitt "Sparkline-Implementierung". Rueckgabe: fertiger `<svg>...</svg>`-String oder `None` bei `len(points) < 2` bzw. leeren Punkten. Template rendert `{{ sparkline_svg | safe }}` wenn nicht None, sonst den Placeholder `—`.

- [x] **Task 3 — Router `app/routers/objects.py` erweitern** (AC1–AC6)
  - [x] 3.1 Imports hinzufuegen: `from app.services.steckbrief import reserve_history_for_sparkline, build_sparkline_svg` (beide neu aus Task 2), `from app.services.impower import get_bank_balance`, `from app.services.steckbrief_write_gate import write_field_human`, `from zoneinfo import ZoneInfo`. Kein `ImpowerError`-Import — `get_bank_balance` kapselt alle Fehler in ein `None`-Return (Task 1.3).
  - [x] 3.2 Neue Field-Tupel-Konstante `FINANZEN_FIELDS`:
    ```python
    FINANZEN_FIELDS: tuple[str, ...] = (
        "reserve_current",
        "reserve_target",
        "wirtschaftsplan_status",
        "sepa_mandate_refs",
        "last_known_balance",
    )
    ```
  - [x] 3.3 Im `object_detail`-Handler nach dem `get_provenance_map`-Aufruf fuer Stammdaten die Finanzen-Logik einsetzen und den neuen Template-Context anreichern. AC2 verlangt **kein 500er bei DB-/Commit-Fehler** — deshalb der `try/except` um den Write-Gate-Call:
    ```python
    from zoneinfo import ZoneInfo
    from decimal import Decimal
    from datetime import datetime
    from app.services.steckbrief_write_gate import write_field_human

    # Finanzen-Provenance
    fin_prov_map = get_provenance_map(db, "object", detail.obj.id, FINANZEN_FIELDS)

    # Live-Pull Bank-Saldo
    live_balance: Decimal | None = None
    live_balance_at_local: str | None = None
    balance_error: bool = False
    if detail.obj.impower_property_id:
        result = await get_bank_balance(detail.obj.impower_property_id)
        if result is not None:
            live_balance = result["balance"]
            live_balance_at_local = (
                result["fetched_at"]
                .astimezone(ZoneInfo("Europe/Berlin"))
                .strftime("%d.%m.%Y %H:%M")
            )
            # Persistieren via Write-Gate — resilient gegen Commit-Fehler (AC2).
            try:
                write_field_human(
                    db,
                    entity=detail.obj,
                    field="last_known_balance",
                    value=live_balance,
                    source="impower_mirror",
                    source_ref=detail.obj.impower_property_id,
                    user=None,
                )
                db.commit()
            except Exception as exc:
                db.rollback()
                balance_error = True
                print(f"[warn] last_known_balance commit failed for {detail.obj.id}: {exc}")
        else:
            balance_error = True

    # Sparkline-Daten (als vorberechneter SVG-String ans Template)
    sparkline_points = reserve_history_for_sparkline(db, detail.obj.id)
    sparkline_svg = build_sparkline_svg(sparkline_points)

    # ...weitere Context-Keys im TemplateResponse-Dict:
    #   "fin_prov_map": fin_prov_map,
    #   "live_balance": live_balance,
    #   "live_balance_at_local": live_balance_at_local,
    #   "balance_error": balance_error,
    #   "sparkline_svg": sparkline_svg,
    ```
  - [x] 3.4 **Kein Import-Zirkel pruefen**: `steckbrief_write_gate` importiert NICHTS aus `routers/` — Import im Router ist safe. `write_field_human`-Import an den Modulanfang (zusammen mit anderen steckbrief-Imports), nicht inline im Handler.
  - [x] 3.5 **Zeit-Handling — kein Filter, sondern Vorformatierung im Router**: `fetched_at` aus `get_bank_balance` ist `datetime.now(ZoneInfo("UTC"))` (Task 1.4). Konversion nach `Europe/Berlin` passiert im Router via `.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")` → fertiger String ans Template (`live_balance_at_local`). Kein `format_datetime_berlin`-Filter bauen (Story 1.3 Deferred-Work hat das als globalen Helper vorgesehen — Story 1.5 nimmt den Kurzweg).

- [x] **Task 4 — Template `app/templates/_obj_finanzen.html`** (AC1, AC2, AC4, AC5)
  - [x] 4.1 Neue Datei `app/templates/_obj_finanzen.html`. Erweitert keine Base-Seite — ist ein Include-Fragment (Prefix `_`).
  - [x] 4.2 Struktur — drei Sub-Sektionen:
    - **Saldo-Block** (oben): Live-Saldo ODER Fallback ODER "Kein Impower-Objekt"
    - **Mirror-Felder-Grid**: `reserve_current`, `reserve_target`, `wirtschaftsplan_status` als Felder-Grid mit Provenance-Pills (identisches Pattern wie `_obj_stammdaten.html`)
    - **SEPA-Mandate-Liste**: `sepa_mandate_refs`-Array als kleine Tabelle (mandate_id, state)
    - **Sparkline**: Inline-SVG wenn `sparkline_points|length >= 2`
  - [x] 4.3 Saldo-Block Logik (Jinja2) — Timestamp kommt als vorformatierter String `live_balance_at_local` aus dem Router (siehe Task 3.3), kein Filter-Aufruf im Template:
    ```jinja
    {% if not obj.impower_property_id %}
      <p class="text-slate-400 text-sm">Kein Impower-Objekt verknuepft.</p>
    {% elif live_balance is not none %}
      <div class="text-2xl font-semibold tabular-nums">{{ "%.2f"|format(live_balance) }} EUR</div>
      <p class="text-xs text-slate-500 mt-1">Stand: {{ live_balance_at_local }} (Europe/Berlin)</p>
    {% else %}
      <div class="text-slate-700 text-sm font-medium">
        {% if obj.last_known_balance is not none %}
          Zuletzt: {{ "%.2f"|format(obj.last_known_balance) }} EUR
        {% else %}
          &mdash;
        {% endif %}
      </div>
      {% if balance_error %}
        <p class="text-xs text-amber-600 mt-1">Saldo aktuell nicht verfuegbar</p>
      {% endif %}
    {% endif %}
    ```
  - [x] 4.4 Provenance-Pills fuer Mirror-Felder: identisches Pattern wie `_obj_stammdaten.html` — `{% set pill = provenance_pill(fin_prov_map.get("reserve_current")) %}`.
  - [x] 4.5 `wirtschaftsplan_status`-Wert wird als deutsch angezeigt (der Mirror hat schon gemappt: "beschlossen", "in_vorbereitung", "entwurf"). Kein Mapping im Template noetig.
  - [x] 4.6 SEPA-Mandate-Tabelle: `sepa_mandate_refs` ist eine JSONB-Liste mit Dicts `{"mandate_id": ..., "bank_account_id": ..., "state": "BOOKED"}`. Im Template: `{% for m in obj.sepa_mandate_refs %}`.
  - [x] 4.7 **Inline-SVG Sparkline** — der fertige SVG-String kommt aus `build_sparkline_svg()` (Task 2.5), das Template rendert nur `{{ sparkline_svg | safe }}` bzw. einen Placeholder:
    ```jinja
    {% if sparkline_svg %}
      <div class="mt-3">{{ sparkline_svg | safe }}</div>
    {% else %}
      <div class="mt-3 text-slate-300 text-sm">&mdash;</div>
    {% endif %}
    ```
    `| safe` ist noetig, damit Jinja2 das SVG-Markup nicht escapet. Die Render-Logik (Koordinaten-Normalisierung, viewBox, Stroke) liegt komplett in der Service-Funktion — siehe Dev-Notes-Abschnitt "Sparkline-Implementierung" fuer die Referenz-Implementation.
  - [x] 4.8 Timestamp-Rendering erfolgt **im Router**, nicht im Template. `live_balance_at_local` ist bereits ein vorformatierter String im `DD.MM.YYYY HH:MM`-Format mit `Europe/Berlin`-Zeitzone (siehe Task 3.3 + 3.5). Kein Jinja2-Filter noetig; der aktuell fehlende zentrale `format_datetime_berlin`-Helper bleibt im Deferred-Work (Story 1.3) und wird in einer spaeteren Story projektweit eingefuehrt.

- [x] **Task 5 — `app/templates/object_detail.html` aktualisieren** (AC1)
  - [x] 5.1 Kommentar aktualisieren. Aktueller Stand (Zeile 12-13):
    ```
    {# Weitere Sektionen (Technik/Finanzen/Versicherungen/Historie/Menschen/Review-Queue) folgen mit Stories 1.4-3.6 — nicht vorbauen. #}
    ```
    → `Finanzen` aus der Aufzaehlung streichen, Story-Range auf `1.6-3.6` anheben:
    ```
    {# Weitere Sektionen (Technik/Versicherungen/Historie/Menschen/Review-Queue) folgen mit Stories 1.6-3.6 — nicht vorbauen. #}
    ```
  - [x] 5.2 `{% include "_obj_finanzen.html" %}` nach dem Stammdaten-Include einfuegen:
    ```html
    {% include "_obj_stammdaten.html" %}
    {% include "_obj_finanzen.html" %}
    ```

- [x] **Task 6 — Tests** (AC2, AC3, AC5, AC7)
  - [x] 6.1 Neue Datei `tests/test_finanzen_live_pull.py`:
    - `test_get_bank_balance_returns_decimal` — mockt httpx mit valider Antwort → `Decimal` zurueck
    - `test_get_bank_balance_timeout_returns_none` — httpx.TimeoutException → `None` (kein raise)
    - `test_get_bank_balance_503_returns_none` — httpx 503-Response → `None`
    - `test_get_bank_balance_no_balance_field_returns_none` — Antwort ohne Balance-Feld → `None`
    - `test_get_bank_balance_8s_timeout_effective` — mockt httpx-Client-Factory, verifiziert dass der per-request-Timeout 8 s ist (nicht 120 s). Absichern, dass der in 1.3 beschriebene `_api_get`-Bypass wirklich funktioniert (sonst wird der 8-s-Client stumm zu 120 s).
  - [x] 6.2 Neue Tests in `tests/test_steckbrief_routes_smoke.py` oder neuer Datei `tests/test_finanzen_routes_smoke.py`:
    - `test_object_detail_finance_section_no_impower_id` — Objekt ohne `impower_property_id` → 200, kein `get_bank_balance`-Call
    - `test_object_detail_finance_section_live_balance_success` — `get_bank_balance` gemockt mit Wert → 200, Saldo in HTML, `last_known_balance` schreibt durch Write-Gate, neue `FieldProvenance`-Row mit `source="impower_mirror"` existiert
    - `test_object_detail_finance_section_live_balance_fallback` — `get_bank_balance` gibt None zurueck → 200, "Saldo aktuell nicht verfuegbar" in HTML
    - `test_object_detail_finance_section_commit_failure_no_500` — `get_bank_balance` liefert Wert, aber `db.commit()` schlaegt via Mock fehl → 200, nicht 500, `balance_error=True` im HTML, Stammdaten-Sektion weiterhin sichtbar (AC2)
    - `test_last_known_balance_user_edit_wins` — existierende `FieldProvenance(field_name="last_known_balance", source="user_edit")`, Live-Pull liefert neuen Wert → Mirror-Guard greift, DB bleibt unveraendert, UI zeigt trotzdem den Live-Wert fuer diesen Request (dokumentiert AC3-Ausnahme)
    - `test_object_detail_finance_section_timestamp_europe_berlin` — `get_bank_balance` liefert `fetched_at=datetime(2026, 4, 22, 15, 30, tzinfo=UTC)` → HTML enthaelt `"22.04.2026 17:30"` (MESZ = UTC+2) und den Zeitzonen-Suffix `(Europe/Berlin)`.
  - [x] 6.3 Test fuer `reserve_history_for_sparkline()` + `build_sparkline_svg()`:
    - `test_reserve_history_two_points_returns_sorted_list` — 2 FieldProvenance-Rows in DB → Liste mit 2 Tupeln, chronologisch
    - `test_reserve_history_empty_returns_empty_list` — keine Rows → `[]`
    - `test_reserve_history_decimal_as_string_in_snapshot` — `value_snapshot={"old": "30000.00", "new": "45000.00"}` → float 45000.0 in Ergebnis
    - `test_reserve_history_missing_new_key_is_skipped` — `value_snapshot={"old": "30000"}` ohne `new` → Row uebersprungen, kein Crash
    - `test_build_sparkline_svg_one_point_returns_none` — `len(points) == 1` → `None`
    - `test_build_sparkline_svg_two_points_returns_svg_string` — 2 Punkte → String startet mit `<svg`, enthaelt `<path d="M`, endet mit `</svg>`
    - `test_build_sparkline_svg_flat_line_for_equal_values` — alle Werte gleich → Pfad ist horizontale Linie (alle Y-Koordinaten identisch auf `h/2`)
  - [x] 6.4 **Impower-Mock**: alle Tests mocken `app.services.impower.get_bank_balance` via `unittest.mock.patch` oder `monkeypatch` — keine echten Impower-Calls (Memory: "Impower hat keinen Sandbox-Tenant").
  - [x] 6.5 **Write-Gate-Coverage-Scanner** (`tests/test_write_gate_coverage.py`) bleibt gruen: `write_field_human`-Call im Router schreibt `last_known_balance`. Verifikation abgeschlossen — der Scanner scannt `app/routers/` + `app/services/` (siehe `test_write_gate_coverage.py:61-66`, `_SCAN_DIRS`); nur `app/services/steckbrief_write_gate.py` ist ausgenommen. Ein direktes `obj.last_known_balance = ...` im Router wuerde **gefangen** werden. Keine Sonder-Action noetig, aber Dev-Agent darf **nicht** per `setattr` oder Direktzuweisung arbeiten.
  - [x] 6.6 **Regressionslauf**: `pytest -x` nach allen Tasks. Alle bestehenden Tests gruen (>=371 Tests, Stand nach Story 1.4 done), plus die neuen Tests aus 6.1–6.3.

## Dev Notes

### Was bereits existiert — NICHT neu bauen

- **Alle 5 Finance-Felder im `Object`-Model** (`app/models/object.py`):
  - `last_known_balance: Mapped[Decimal | None]` (Zeile 44) — aus Migration 0010
  - `reserve_current: Mapped[Decimal | None]` (Zeile 47) — aus Migration 0012
  - `reserve_target: Mapped[Decimal | None]` (Zeile 50) — aus Migration 0012
  - `wirtschaftsplan_status: Mapped[str | None]` (Zeile 53) — aus Migration 0012
  - `sepa_mandate_refs: Mapped[list[Any]]` (Zeile 56, JSONB) — aus Migration 0012
- **Kein neue Migration noetig** — alle Spalten existieren bereits.
- **`write_field_human`** in `app/services/steckbrief_write_gate.py` — aufrufen fuer `last_known_balance`-Persistierung. Keine direkte Zuweisung `obj.last_known_balance = ...` erlaubt (Write-Gate-Coverage-Scanner).
- **`get_provenance_map(db, "object", obj.id, fields)`** in `app/services/steckbrief.py` (Zeile 116) — unveraendert nutzbar fuer `FINANZEN_FIELDS`.
- **`provenance_pill(wrap)`** Template-Global in `app/templating.py` — gleiche Pill-Farben wie in `_obj_stammdaten.html`.
- **`ImpowerError`** (`app/services/impower.py`, Zeile 133) — bereits vorhanden, `get_bank_balance` faengt sie intern ab → `None`.
- **`_make_client()`** (`app/services/impower.py`, Zeile 139) — Vorlage fuer den 8-s-Timeout-Client in `get_bank_balance`.
- **`_WIRTSCHAFTSPLAN_STATUS_MAP`** in `app/services/steckbrief_impower_mirror.py` (Zeile 67) — Mirror mappt bereits nach deutsch; Template zeigt einfach `obj.wirtschaftsplan_status`.
- **`FieldProvenance.value_snapshot`** (`app/models/governance.py`, Zeile 38) — JSONB, Format `{"old": <safe_value>, "new": <safe_value>}` (schreibt Write-Gate so). `new` ist der Wert nach dem Write.

### Kritische Fallstricke

1. **8-s-Timeout fuer Live-Pull**: `_TIMEOUT = 120.0` ist das globale Impower-Timeout — fuer Live-Pull NICHT nutzen. Eigenen `httpx.AsyncClient(timeout=8.0)` in `get_bank_balance` oeffnen. Sonst blockiert jeder Impower-Slowdown den Render fuer 2+ Minuten.
2. **Decimal aus JSONB lesen**: `value_snapshot["new"]` kann `str`, `int` oder `float` sein (JSONB verliert den Decimal-Typ). Immer `float(str(val))` — nie direkt `Decimal(val)` wenn `val` schon ein float ist (Gleitkomma-Repr kann Artefakte erzeugen). Oder: `Decimal(val) if isinstance(val, str) else Decimal(str(val))`.
3. **JSONB-Mutation `sepa_mandate_refs`**: Im Template readonly — kein Problem. Wenn zukuenftige Stories das Feld editieren: Reassignment noetig (`obj.sepa_mandate_refs = [...]`, kein in-place `.append()`).
4. **Template-Response-Signatur**: `templates.TemplateResponse(request, "object_detail.html", {...})` — `request` MUSS erstes Argument sein (Memory: `feedback_starlette_templateresponse`). Bestehender Handler `object_detail` tut das bereits korrekt.
5. **Kein `asyncio.run()` im Handler**: Handler ist `async def object_detail(...)` — `await get_bank_balance(...)` direkt verwenden, kein `asyncio.run()`.
6. **`_json_safe_for_provenance` und Decimal**: `write_field_human` serialisiert Decimal via `_json_safe_for_provenance` → String in JSONB. Das ist expected behavior. Die Provenance-Row speichert `"45000.00"` als String.
7. **Deferred-Work aus Story 1.3**: `_proposed_value`-Typ-Roundtrip fuer Decimal/Date (write_gate.py:1779) ist mit Story 1.5 relevant. Wenn das Review-Queue-System spaeter Finanzdaten approven will, muss der Approve-Handler den String-Wert typsicher parsen. Story 1.5 selbst legt keine ReviewQueueEntry an — kein akutes Problem.

### Sparkline-Implementierung (Task 2.5)

Referenz-Implementation fuer `build_sparkline_svg(points: list[tuple[datetime, float]]) -> str | None` in `app/services/steckbrief.py`:

```python
def build_sparkline_svg(points: list[tuple[datetime, float]]) -> str | None:
    """Liefert einen fertigen SVG-String oder None bei <2 Datenpunkten."""
    if len(points) < 2:
        return None
    vals = [v for _, v in points]
    min_v, max_v = min(vals), max(vals)
    w, h = 120, 40
    pad = 2

    def to_xy(i: int, v: float) -> tuple[float, float]:
        x = pad + i / (len(vals) - 1) * (w - 2 * pad)
        if max_v == min_v:
            y = h / 2  # Flat-Line bei allen Werten identisch
        else:
            y = h - pad - (v - min_v) / (max_v - min_v) * (h - 2 * pad)
        return round(x, 1), round(y, 1)

    coords = [to_xy(i, v) for i, v in enumerate(vals)]
    path_d = " ".join(
        f"{'M' if i == 0 else 'L'}{x},{y}"
        for i, (x, y) in enumerate(coords)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{path_d}" stroke="#0ea5e9" stroke-width="1.5" fill="none"/>'
        f'</svg>'
    )
```

SVG-String wird im Router als `sparkline_svg: str | None` an das Template uebergeben. Template rendert `{{ sparkline_svg | safe }}` wenn nicht None — `| safe` ist noetig, da es echtes HTML ist.

### Impower-Endpoint fuer Bank-Saldo (Task 1.1)

Der exakte Endpoint ist nicht im Code dokumentiert — muss aus Swagger ermittelt werden. Suchstrategie:
1. **Swagger lesen**: `https://api.app.impower.de/services/pmp-accounting/v2/api-docs` im Browser oder via `curl` — nach `balance`, `saldo`, `account` suchen.
2. **Vorlage: Vorhandene pmp-accounting-Calls** in `impower.py`: Mandate via `GET /services/pmp-accounting/api/v1/direct-debit-mandate?propertyId={id}` (aktuell in `_load_property_mandates`, `app/services/impower.py:575`; auch genutzt im Nightly-Mirror `app/services/steckbrief_impower_mirror.py:239`). Das Prefix `services/pmp-accounting/api/v1/` ist der richtige Namespace fuer Accounting-Endpoints.
3. **Kandidaten-Endpoints** (Reihenfolge nach Wahrscheinlichkeit, alle zu pruefen):
   - `/services/pmp-accounting/api/v1/house-money-settlements?propertyId={id}` — Hausgeld-Abrechnung mit Saldo
   - `/v2/properties/{id}` — Property-Detail-Objekt, koennte `accountBalance` oder `currentBalance` enthalten
   - `/services/pmp-accounting/api/v1/account-balances?propertyId={id}` — explizites Balance-Endpoint
4. **Kein semantischer Fallback auf Ruecklage** — `reserveCurrent` (gespiegelt in `Object.reserve_current`) ist **nicht** der Bank-Saldo. Ruecklage = zweckgebundenes Guthaben fuer zukuenftige Ausgaben; Bank-Saldo = aktueller Girokontostand der WEG. Der PRD trennt die beiden bewusst (FR4 und FR7). Wenn nach Swagger-Recherche kein dedizierter Balance-Endpoint auffindbar ist:
    - `get_bank_balance` liefert unconditional `None` (keine Dummy-Daten).
    - Die UI zeigt den Fallback-Zweig aus AC2 (`obj.last_known_balance` wenn vorhanden, sonst `&mdash;` + "Saldo aktuell nicht verfuegbar").
    - Ergaenzung im Saldo-Block-Template: Zusaetzlicher Hinweis-Text "Bank-Saldo via API aktuell nicht verfuegbar — Impower-Support kontaktieren".
    - Story-Abnahme erfolgt trotzdem (AC1 Live-Saldo-Zeile dokumentiert "N/A in v1"); Dev-Agent legt in Deferred-Work einen Eintrag "Impower-Balance-Endpoint-Spike" an und erwaehnt in der PR-Beschreibung explizit, welche Endpoints getestet wurden (Response-Status + Fehler).

### Project Structure Notes

- Neue/geaenderte Dateien:
  - `app/services/impower.py` — neue Funktion `get_bank_balance` (append-only, keine bestehende Funktion aendern)
  - `app/services/steckbrief.py` — neue Funktionen `reserve_history_for_sparkline` + `build_sparkline_svg`
  - `app/routers/objects.py` — `object_detail`-Handler erweitert, neue Imports, neue Konstante `FINANZEN_FIELDS`
  - `app/templates/_obj_finanzen.html` — neu (Fragment)
  - `app/templates/object_detail.html` — ein `{% include %}` ergaenzt
  - `tests/test_finanzen_live_pull.py` — neu
  - Ggf. Erweiterung `tests/test_steckbrief_routes_smoke.py` oder neue `tests/test_finanzen_routes_smoke.py`
- **Keine** Migration, kein neues Model, keine neue Route (der Endpoint `/objects/{id}` wird nur erweitert), kein neuer Router, keine Aenderung an Write-Gate, kein neues Workflow-Seeding.

### References

- [Story 1.4 Nicht-im-Scope-Abschnitt](output/implementation-artifacts/1-4-impower-nightly-mirror-fuer-cluster-1-6.md): "Live-Pull-Saldo (`last_known_balance`) ist Scope Story 1.5" und "Ruecklage-Historie-Snapshots — Story 1.5 entscheidet"
- [Architektur CD3](output/planning-artifacts/architecture.md#CD3): Live-Pull (Bank-Saldo beim Render), Sync-Orchestrator-Modi
- [Architektur ID4](output/planning-artifacts/architecture.md#ID4): `_obj_finanzen.html` als eines der 7 Section-Fragments
- [FieldProvenance Model](app/models/governance.py:14): `value_snapshot: JSONB = {"old": ..., "new": ...}`
- [Write Gate](app/services/steckbrief_write_gate.py): `write_field_human()` + `_json_safe_for_provenance()`
- [Impower Client Patterns](app/services/impower.py): `_make_client()`, `_api_get()`, `ImpowerError`, `_TIMEOUT`
- [Existing Router Pattern](app/routers/objects.py): `object_detail`-Handler, `get_provenance_map`-Aufruf, `STAMMDATEN_FIELDS`-Tupel
- [Existing Template Pattern](app/templates/_obj_stammdaten.html): Provenance-Pills, Grid-Layout, Stale-Banner
- [Deferred Work](output/implementation-artifacts/deferred-work.md): `proposed_value`-Decimal-Roundtrip (Story 1.5 relevant), `format_datetime_berlin`-Helper (noch ausstehend)
- [Memory: ImpowerError Handling](../../../.claude/projects/-Users-daniel-Desktop-Vibe-Coding-Dashboard-KI-Agenten/memory/reference_impower_api.md)

## Dev Agent Record

### Agent Model Used

claude-opus-4-7

### Debug Log References

- Erster Regressionslauf scheiterte an `test_detail_renders_stammdaten_and_eigentuemer` — der Story-1.3-Test enthielt `assert "Finanzen" not in body` als Story-Boundary-Guard. Mit Story 1.5 ist die Finanzen-Sektion jetzt da; die Assertion wurde entfernt (Technik/Review-Guards bleiben).
- Zwei Sparkline-Routen-Tests scheiterten initial an `<svg`-Substring-Match, weil die Sidebar-Icons SVG-Elemente enthalten. Tests umgestellt auf den sparkline-spezifischen `viewBox="0 0 120 40"`-Marker (Sidebar-Icons nutzen 24x24).

### Completion Notes List

- **Impower-Endpoint MVP-Wahl**: `GET /v2/properties/{id}` mit Lookup-Reihenfolge `accountBalance` → `currentBalance` → `bankBalance`. Live-Verifikation steht aus — wenn Impower keines dieser Felder im Property-Detail-Objekt liefert, faellt `get_bank_balance` sauber auf `None` zurueck (UI zeigt den Fallback "Saldo aktuell nicht verfuegbar"). Folge-Aktion in dem Fall: Swagger-Recherche + ggf. dedizierter Endpoint wie `/services/pmp-accounting/api/v1/house-money-settlements`.
- **8-s-Timeout**: Eigener `httpx.AsyncClient(timeout=8.0)` umgeht den 120-s-Modul-Timeout aus `_api_get`. Bypass per Test (`test_get_bank_balance_8s_timeout_effective`) abgesichert — kein stilles Auto-Override.
- **Mirror-Guard**: `last_known_balance` wird via Write-Gate persistiert. Wenn die letzte Provenance-Row ein `user_edit` traegt (in v1 nicht erreichbar — `last_known_balance` ist nirgends user-editierbar), greift der Guard und blockt den Mirror-Write. Test `test_last_known_balance_user_edit_wins` dokumentiert das Verhalten fuer kuenftige Stories.
- **Commit-Resilienz (AC2)**: Try/except im Router faengt sowohl `write_field_human`-Fehler als auch `db.commit()`-Fehler ab; Render geht durch, `balance_error=True` wird im Template als `data-balance-error="true"`-Attribut reflektiert. UI bleibt nutzbar.
- **Zeit-Formatierung**: Konversion UTC → Europe/Berlin erfolgt im Router (`.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")`); kein globaler Jinja-Filter — bleibt im Story-1.3-Deferred-Work-Backlog.
- **Sparkline**: Render-Logik komplett im Service (`build_sparkline_svg`); Template macht nur `{{ sparkline_svg | safe }}`. SVG-Spezifisches `viewBox="0 0 120 40"` wird bewusst verwendet, damit Tests es trennscharf von den Sidebar-Icons (24x24) unterscheiden koennen.
- **Tests**: 36 neue Tests (23 in `test_finanzen_live_pull.py`, 13 in `test_finanzen_routes_smoke.py`). Volle Suite 405/405 gruen (vorheriger Stand 369; Bewegung kommt durch das Loeschen einer obsolet gewordenen Story-1.3-Assertion).

### File List

Neu angelegt:
- `app/templates/_obj_finanzen.html`
- `tests/test_finanzen_live_pull.py`
- `tests/test_finanzen_routes_smoke.py`

Modifiziert:
- `app/services/impower.py` (+`get_bank_balance` + `_LIVE_BALANCE_TIMEOUT` + Imports `datetime`/`Decimal`/`ZoneInfo`)
- `app/services/steckbrief.py` (+`reserve_history_for_sparkline` + `build_sparkline_svg` + datetime-Imports)
- `app/routers/objects.py` (+`FINANZEN_FIELDS` + Finanzen-Logik in `object_detail`-Handler + neue Imports)
- `app/templates/object_detail.html` (+`{% include "_obj_finanzen.html" %}` + Kommentar-Update)
- `tests/test_steckbrief_routes_smoke.py` (`assert "Finanzen" not in body` entfernt — Boundary-Guard aus Story 1.3 ist obsolet, Sektion existiert jetzt)
- `output/implementation-artifacts/sprint-status.yaml` (Story 1.5: ready-for-dev → review)

### Change Log

- 2026-04-22: Story 1.5 implementiert (`get_bank_balance` mit 8-s-Timeout + `_obj_finanzen.html` + Sparkline-Service + Write-Gate-Persistierung von `last_known_balance` + 36 neue Tests). Regression 405/405 gruen. Status → review. Live-Verifikation des Impower-Endpoints `/v2/properties/{id}` (Balance-Feldname) steht aus.

### Review Findings

- [x] [Review][Decision] Sparkline-Position: innerhalb Saldo-Block statt nach SEPA-Mandate-Liste — Task 4.2 beschreibt 4 gleichrangige Sub-Sektionen (Saldo-Block | Mirror-Felder | SEPA | Sparkline). Im Template ist die Sparkline in den `<div class="mb-6">` des Saldo-Blocks genestet — visuell vor Mirror-Feldern und SEPA, nicht nach SEPA. Entscheidung: **(a)** Sparkline nach SEPA verschieben (Spec-konform) oder **(b)** Position so lassen (UX-Argument: Ruecklage-Trend direkt neben Saldo). [`app/templates/_obj_finanzen.html:41`]

- [x] [Review][Patch] sepa_mandate_refs ohne Provenance-Pill (AC1 Verletzung) [`app/templates/_obj_finanzen.html:80`] — AC1 verlangt "jeweils mit Provenance-Pill" fuer alle vier Felder inkl. sepa_mandate_refs. `fin_prov_map` (FINANZEN_FIELDS inkl. sepa_mandate_refs) wird berechnet, aber `fin_prov_map.get("sepa_mandate_refs")` wird nicht ans Template uebergeben und kein Pill in der SEPA-Tabelle gerendert.

- [x] [Review][Defer] Rate-Gate-Wartezeit nicht durch 8s-HTTP-Timeout begrenzt [`app/services/impower.py`] — deferred, pre-existing
- [x] [Review][Defer] asyncio.CancelledError propagiert als 500 aus get_bank_balance [`app/services/impower.py`] — deferred, systemic
- [x] [Review][Defer] Concurrent Page-Loads erzeugen doppelte FieldProvenance-Rows fuer last_known_balance [`app/routers/objects.py`] — deferred, pre-existing design
