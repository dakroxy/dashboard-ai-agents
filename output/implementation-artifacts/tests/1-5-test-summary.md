# Test-Automatisierung — Story 1.5 (Finanzen-Sektion mit Live-Saldo + Sparkline)

**Datum:** 2026-04-24
**Skill:** `bmad-qa-generate-e2e-tests`
**Scope:** Story 1.5 — Finanzen-Sektion, Live-Saldo-Pull und Ruecklage-Sparkline

## Ergebnis

**Keine neuen Tests in diesem Durchlauf** — Story 1.5 wurde waehrend der
Implementierung bereits mit 24 dedizierten Tests abgeschlossen (alle gruen).
Diese Doku zieht nur die Test-Abdeckung pro AC nach, damit die Coverage im
gleichen Muster wie `1-1-test-summary.md` / `1-4-test-summary.md`
sichtbar ist.

## Bestehende Testdateien

### `tests/test_finanzen_live_pull.py` (11 Tests)

Unit-Level fuer `impower.get_bank_balance` + Sparkline-Helpers aus
`app/services/steckbrief.py`. Mocks httpx auf dem Impower-Client, keine echten
Calls.

- Timeout-Verhalten (`_LIVE_BALANCE_TIMEOUT = 8 s`) bei haengender API.
- Graceful Fallback: `{balance_error: True}` bei 5xx, 404 und Timeout —
  keine Exception bricht die Detail-Seite (AC2).
- Parse-Happy-Path: Impower-Response → `(balance: Decimal, ts: datetime)`-Tuple.
- Fehlende Impower-Property-ID → Guard ohne Call (AC4).
- Datetime-Parse mit/ohne Timezone-Suffix.
- Sparkline-Builder: `reserve_history_for_sparkline` extrahiert bis 30
  Provenance-Zeitpunkte aus `reserve_balance`-Historie.
- `build_sparkline_svg`: korrekte Viewbox, normalisierte Y-Skala, Early-Return
  wenn <2 Datenpunkte.

### `tests/test_finanzen_routes_smoke.py` (13 Tests)

Router-Ebene `/objects/{id}` mit eingebautem Finanzen-Block. Mockt
`get_bank_balance` und verifiziert das gerenderte HTML-Fragment.

- AC1: Finanzen-Sektion rendert mit allen Mirror-Feldern (`last_known_balance`,
  `reserve_balance`, `reserve_target`, `sepa_mandate_refs`), plus Live-Saldo
  wenn Impower verfuegbar.
- AC1: Provenance-Pills pro Feld (Stichproben: `last_known_balance`,
  `reserve_balance`, `reserve_target`).
- AC1: SEPA-Mandate-Liste mit Pill (Review-Patch aus Runde-1 gefixt).
- AC2: Fallback-Banner bei `{balance_error: True}` — keine 500, Sektion
  rendert weiter.
- AC3: Live-Pull persistiert `last_known_balance` via `write_field_human` —
  FieldProvenance-Row entsteht mit `source="impower_mirror"`.
- AC4: Kein Live-Pull-Request wenn `impower_property_id` leer.
- AC5: Sparkline im HTML bei >= 2 Provenance-Punkten; ausgeblendet bei <2.
- AC5: Sparkline nutzt `reserve_balance`-History, nicht `last_known_balance`.

### Indirekt

- `tests/test_steckbrief_routes_smoke.py` — Statement-Count-Guard 8 → 9
  angepasst, Boundary-Assertion `assert "Finanzen" not in body` aus Story 1.3
  entfernt.
- `tests/test_write_gate_unit.py` — deckt die Mirror-Write-Semantik
  (`impower_mirror` vs. `user_edit`) bereits ab.

## Coverage pro AC

| AC | Anforderung | Abdeckung |
|----|-------------|-----------|
| AC1 | Finanzen-Sektion + Live-Saldo + Pills | `test_finanzen_routes_smoke` (Render + Pills + Banner) |
| AC2 | Graceful Fallback bei Impower-Ausfall | `test_finanzen_live_pull` (5xx/404/Timeout) + `test_finanzen_routes_smoke` (Fallback-Banner) |
| AC3 | Live-Pull schreibt `last_known_balance` via Write-Gate | `test_finanzen_live_pull` + `test_finanzen_routes_smoke` (Provenance-Row-Check) |
| AC4 | Kein Pull ohne `impower_property_id` | `test_finanzen_live_pull` (`test_no_call_when_pid_missing`) |
| AC5 | Sparkline aus Provenance-Historie | `test_finanzen_live_pull` (Unit) + `test_finanzen_routes_smoke` (HTML) |
| AC6 | P95 ≤ 2 s | **nicht hart automatisiert** — indirekt ueber den 8 s-Timeout und Mocks; SLO-Messung in Prod ueber Admin-Dashboard |
| AC7 | Regressionslauf gruen | Volle Suite 499/499 gruen (Stand 2026-04-24) |

## Run-Command

```bash
docker compose exec app python -m pytest \
  tests/test_finanzen_live_pull.py \
  tests/test_finanzen_routes_smoke.py -v
# 24 passed
```

## Bewusst NICHT abgedeckt

- **P95-Latenz-Assert (AC6)** — fuer einen echten Last-Test muesste der
  Impower-Endpoint in einer Prod-aehnlichen Umgebung angesprochen werden.
  Mocks koennen hoechstens "Timeout ist korrekt bei 8 s" verifizieren (ist
  im Live-Pull-Test vorhanden). Monitoring via `/admin/sync-status`-Historie
  uebernimmt das in Prod.
- **Concurrent Page-Loads mit Double-Write-Risk** auf `last_known_balance` —
  bekannter Defer aus Code-Review (siehe `deferred-work.md` Story 1.5),
  braucht Advisory-Lock oder UNIQUE-Constraint; fuer v1 akzeptiert.
- **Live-Endpoint `/v2/properties/{id}`-Balance-Feldname** — noch nicht gegen
  Prod-Tenant verifiziert; sobald der erste reale Pull laeuft, das
  Feldname-Mapping in `get_bank_balance` bestaetigen.

## Offene Luecken (nicht im Scope dieser Runde)

Keine. Abdeckung wird als ausreichend fuer den Prod-Rollout dieser Story
bewertet; Live-Verifikation des Impower-Feldnamens bleibt ein Doku-Item,
kein Test-Gap.
