# Story 5-3: Backend-Robustheit & Crash-Guards

Status: review

## Story

Als Betreiber der Plattform,
moechte ich, dass legitime, aber unerwartete Eingaben oder transiente API-Fehler keinen 500er-Crash mehr ausloesen,
damit Aggregator-Routen, Form-Submits und Mirror-Aufrufe gegen Schema-Drift und Boundary-Werte robust bleiben und der User entweder ein klares 422 sieht oder die Operation graceful weiterlaeuft.

## Boundary-Klassifikation

`hardening` (cross-cutting, post-prod). **Mittleres Risiko bei Nicht-Umsetzung, niedriges Risiko bei der Umsetzung selbst.**

- Kein neues Feature, keine neuen Routes, keine neuen Permissions, keine neuen Migrations.
- Cross-cutting: trifft `app/services/facilioo.py` (4 Items), `app/services/pflegegrad.py` + `app/routers/objects.py` (Pflegegrad-Cluster), `app/routers/objects.py` (Police/Wartung-Form-Cluster), `app/services/steckbrief_policen.py` (Cascade), `app/services/steckbrief_write_gate.py` (Approve-Race), `app/services/impower.py` (Cancellation), `app/services/photo_store.py` (Executor-Wrap), `app/templating.py` (Score-Clamp).
- 19 Defer-Items, alle aus `output/implementation-artifacts/deferred-work.md`. **Severity-Mix: 11 medium, 7 low, 1 doku-only (#115 out-of-scope).** Kein `high`, kein Pre-Prod-Blocker — deshalb post-prod. Trotzdem aufraeumen, weil jeder Eintrag eine reale 500-Quelle oder eine Schema-Drift-Falle ist.

**Vorbedingungen:**

1. **Story 5-1 (`in-progress`) und Story 5-2 (`ready-for-dev`)** — beide pre-prod-pflichtig. 5-3 baut auf 5-1+5-2 auf. Wenn die Patches aus 5-1/5-2 noch nicht live sind, kann 5-3 trotzdem starten — die Touch-Listen sind disjunkt:
   - 5-1 fasst `app/middleware/csrf.py`, `app/main.py` (Middleware-Registrierung), `app/templating.py` (autoescape, csrf-token-Global), `app/services/audit.py` (IP-Truncation), `app/services/steckbrief_write_gate.py` (Double-Encrypt-Guard), `migrations/versions/0019_police_column_length_caps.py` an;
   - 5-2 fasst `app/main.py` (Seed-Idempotenz), `app/services/pflegegrad.py` (Row-Lock), `app/routers/documents.py` (Document-Lock), `app/routers/objects.py` (notes-Lock + Foto-Saga + Negative-Praemie + notice_period_months) an;
   - 5-3 fasst `app/services/facilioo.py`, `app/services/pflegegrad.py` (Robustheit, anderer Bereich), `app/services/impower.py`, `app/services/photo_store.py`, `app/services/steckbrief_write_gate.py` (Approve-Lock), `app/services/steckbrief_policen.py`, `app/routers/objects.py` (Police-FK-Check, Decimal-Range, intervall-Range, NBSP-Strip, Wartung-Delete-Branch), `app/templating.py` (pflegegrad-Clamp) an.
   - Erwartete Konfliktstellen: `app/routers/objects.py` (Police-/Wartungs-Bereich um Zeilen 1300-1600 — 5-2 macht Negative-Praemie + notice_period_months, 5-3 macht versicherer_id-Existenzcheck, Decimal-Overflow, intervall_monate-Range, NBSP-Strip, Wartung-Delete-Branch). Disjunkt nach AC, aber im selben Funktionsblock — Dev-Agent muss beide Stories als Vorlage halten und die Form-Validation-Reihenfolge konsistent (erst Parse, dann Range-Checks, dann FK-Checks) bauen.
   - `app/services/pflegegrad.py`: 5-2 ergaenzt `with_for_update()` an Beginn von `get_or_update_pflegegrad_cache`; 5-3 packt den Service-Call in `try/except` (AC2) und claimpt am `pflegegrad_color`-Helper in `templating.py`. Disjunkt.
   - `app/services/steckbrief_write_gate.py`: 5-1 macht Double-Encrypt-Guard im `write_field_human` (Zeile 235); 5-3 macht Row-Lock in `approve_review_entry` (Zeile 420). Disjunkt.
2. **Latest Migration ist `0019_police_column_length_caps.py`** (aus 5-1 schon angelegt, sichtbar im Working-Tree als untracked). 5-3 schreibt **keine** Migration; falls 5-1 mergt, ist `0019` belegt und 5-3 bleibt code-only.
3. **Story 4.4 / Epic 4 done.** Mirror-Code ist live-fähig (auch wenn `FACILIOO_MIRROR_ENABLED=true` in Elestio noch nicht gesetzt ist — siehe Epic-4-Retro L1). Die Facilioo-Härtung in 5-3 trifft `_get_all_paged`, `fetch_conference_signature_payload` und `list_property_summaries` — alles Code-Pfade, die heute schon laufen, aber gegen Schema-Drift und Partial-Failures verwundbar sind.

**Kritische Risiken:**

1. **`return_exceptions=True` aendert das Aggregator-Verhalten** — heute kippt ein einzelner 5xx auf einer Voting-Group oder einer Unit die ganze ETV-PDF; mit `return_exceptions=True` muss der Aufrufer pro Result entscheiden, ob es eine Exception ist oder ein Wert. **Spec-Klarheit:** Phase-3 (`attribute-values` pro Unit, `app/services/facilioo.py:463`) wird auf graceful-degrade gestellt — ein gefailter Unit-Attribut-Call darf die PDF nicht killen, sondern liefert leeres `attr_by_unit[uid] = []` mit Warning-Log. **Phase-1 und Phase-2 bleiben fail-loud** (Defer #22 + #33, vom Defer-Doc explizit als "fail-loud belassen" markiert — juristisches Risiko bei unvollstaendiger Liste). Diese Story haertet **nur Phase-3**, nicht Phase 1/2.

2. **`int(total_pages)` Defensive vs. echtes Verhalten** — Defer #23 ist niedrig priorisiert ("Facilioo liefert immer numerisch"). Trotzdem: wenn ein API-Drift-Fall eintritt, soll der Loop sauber terminieren (kein Crash, kein Endlos-Loop). Loesung: `try: total_pages_int = int(total_pages) except (TypeError, ValueError): total_pages_int = None`, dann nach den existierenden Cap-Checks (`_MAX_PAGES`) terminieren. **`_MAX_PAGES`-Cap muss greifen** — wir verlassen uns nicht auf `totalPages`-Header allein.

3. **`_get_all_paged` Bare-List-Truncation** — heute terminiert der Loop bei `len(data) < _PAGE_SIZE`, was bei einem Server, der auf < `_PAGE_SIZE` clampt UND als Bare-List antwortet (kein `{items: ...}`-Wrapper), nach Page 1 stoppt + restliche Seiten droppt. Defer-Doku schlaegt vor: "if list-shape: nur stoppen wenn `len < _PAGE_SIZE` UND zusaetzlich `len == 0`". **Bessere Loesung**: Bare-List-Modus wird zusaetzlich abgesichert via `_MAX_PAGES`-Cap (analog zur dict-Variante) und durch ein `len == 0`-OR-Stop. Das ist konservativ — wir lesen ggf. eine Seite zu viel (ist nur ein leeres Response am Ende), aber kein Verlust mehr.

4. **`pflegegrad_score()`-Crash → 500 vs. defensive 200** — heute ist die Detail-Page tot, wenn `pflegegrad_score()` (DB-Hiccup auf `field_provenance` oder `_compute_pflegegrad`) wirft. Loesung: `try: pflegegrad_result, cache_updated = get_or_update_pflegegrad_cache(detail.obj, db) except Exception as exc: _logger.warning(...) pflegegrad_result, cache_updated = None, False`. Render-Pfad kommt mit `pflegegrad_result is None` schon klar (Score-Badge zeigt "neutral"). **Begleitend:** Score-Clamping in `pflegegrad_color` (Defer #150), damit sowohl Service-Crashes als auch defekte Cache-Werte stabil rendern.

5. **Commit-Fail-Loop ohne Backoff (#35)** — heute logged der Code nur ein `warning`, das in-memory `obj` traegt aber die neuen Werte; naechster Request liest stale aus DB, schreibt erneut, wenn Commit wieder failt → tight loop ohne Latenz. Loesung: zusaetzlich zum Warning **einmalig pro Run** ein `audit("pflegegrad_cache_commit_fail", entity_type="object", entity_id=obj.id, details={"error": str(exc)})` schreiben — in eigener Session via Helper aus 5-2 (`_audit_in_new_session`, falls 5-2 schon gemerged) oder hier neu mit dem analogen Pattern. Audit ist die einzige sichtbare Spur fuer Ops; ohne Audit faellt der Cache-Race in 5-2-Vorbedingungen unsichtbar weiter. **Backoff/Circuit-Breaker** ist out-of-scope (Defer-Doku selbst nennt es "Pattern analog `live_balance`" — `live_balance` hat denselben Defekt; eigene Story bei Performance-Sprint 5-4).

6. **Cancellation-Hygiene (#111)** — `except Exception` in `app/services/impower.py:get_bank_balance` faengt **keine** `asyncio.CancelledError` (ist `BaseException`). Bei Client-Disconnect oder Graceful-Shutdown propagiert das als 500. Loesung: separates `except asyncio.CancelledError: raise` (re-raise, nicht silent schlucken) **VOR** dem generischen `except Exception` — Standard-Pattern aus PEP 654. Audit: `cancelled_during_balance_fetch` als Marker in einem separaten Audit-Helper (best-effort). Greift auch in `fetch_conference_signature_payload`, `list_property_summaries` und allen anderen Long-Running async-Calls — Dev-Agent macht **`grep -n "except Exception" app/services/impower.py app/services/facilioo.py app/services/photo_store.py`** und ergaenzt das Pattern an jedem Treffer, der einen async I/O-Call umschliesst.

7. **`_get_token()` blockiert Event-Loop (#127)** — `msal.acquire_token_for_client()` ist sync HTTP. Im async FastAPI-Thread blockiert das den Event-Loop bis zu ~500 ms (erster Token-Refresh pro Stunde — danach MSAL-Cache). **Loesung**: `await asyncio.get_event_loop().run_in_executor(None, self._get_token)`. **Risiko**: SharePoint ist live nicht aktiv (LocalPhotoStore ist Default), deshalb ist die Aenderung defensiv-vorbeugend. Trotzdem in 5-3, weil sie zur "Async-Hygiene"-Klasse gehoert und der Patch trivial ist (~3 Zeilen).

8. **Approve-Race-Lock (#96)** — heute koennen zwei Admins denselben `ReviewQueueEntry` parallel approven; beide bestehen den `entry.status != "pending"`-Check, beide rufen `write_field_human` mit identischen Werten — kein Datenverlust, aber Doppel-Provenance-Row + Doppel-Audit. Loesung: `entry = db.execute(select(ReviewQueueEntry).where(ReviewQueueEntry.id == entry_id).with_for_update()).scalar_one_or_none()` als ERSTE DB-Op. **SQLite-Test-Caveat** (siehe 5-2 Risiko 1): `with_for_update()` ist in SQLite ein No-Op — Test verifiziert via Statement-Introspection, nicht via echten Race.

9. **Police-Delete + FK-Abhaengigkeiten (#141, #145)** — `delete_police` macht heute `db.delete(policy)` ohne `policy.wartungspflichten`/`policy.schadensfaelle` vorher zu touchen. ORM `cascade="all, delete-orphan"` mit `lazy="selectin"` laedt die Collections zwar by Default beim DELETE, aber das Verhalten ist Implicit. **Defer-Doku-Empfehlung** war RESTRICT (User loescht Kinder zuerst) — das ist eine UX-Entscheidung. **Hier pragmatisch**: CASCADE belassen (User-Erwartung: "ich loesche die Police, alles Drumrum geht mit"), aber `policy.wartungspflichten` und `policy.schadensfaelle` **vor** `db.delete(policy)` einmal accessen, damit die selectin-Relations garantiert geladen sind. Plus: zusaetzliches Audit `policy_deleted` mit `wartung_count` und `schadensfall_count`, damit der User in den Logs sieht, was alles mit-geloescht wurde. Belt-and-Suspenders ohne Verhaltens-Aenderung.

10. **`wart.policy is None`-Branch (#143)** — Edge-Case ueber regulaeren Pfad nicht reachable (cascade raeumt Wartungen mit). Aber: bei Migration/Seeding/Data-Repair koennten orphan-Wartungen (`policy_id = NULL`) entstehen. Heute macht der DELETE-Handler dann `_render_versicherungen(...)` (komplette Sektion) — Spec-Verstoss zu AC3 ("Per-Police-Fragment"). **Loesung**: dedizierter `_obj_versicherungen_orphan_removed.html`-Fragment (oder leerer `<article id="orphan-removed-{wart_id}"></article>` fuer hx-swap), der **nur** den orphan-Eintrag entfernt — keine kompletten Sektion-Render. Pragmatisch im Template: einfach leeren `<article>`-Body zurueckgeben mit `hx-swap="outerHTML"`.

11. **NBSP/Zero-Width-strip (#148)** — `bezeichnung.strip()` strippt nur ASCII-Whitespace. Loesung: helper `_strip_unicode_whitespace(s)` der `unicodedata.normalize("NFKC", s)` macht, dann mit `str.strip()` und zusaetzlich Zero-Width-Whitespace (`​`, `‌`, `‍`, `﻿`) und non-breaking space (` `) entfernt. **Memory-Bezug**: `feedback_llm_iban_unicode_normalize.md` — gleiche Klasse von Bug, gleiche Loesung. Helper in `app/services/text_utils.py` (neue Datei) oder direkt in `app/services/_text.py`. **Wiederverwendbar** fuer alle freien Text-Inputs (heute 5+ Stellen, dokumentiert in `app/services/_text.py`-Docstring); Story aendert nur die NBSP-Stelle in `wartungspflicht_create` — der Helper steht als Vorlage, andere Stellen (Story 2.4 notes_owners, Schadensfall-description, etc.) gehen in 5-6 (Code-Qualitaet) als systematischer Sweep.

12. **Score-Clamping (#150)** — heute nicht erreichbar, weil `pflegegrad_score()` mathematisch in [0, 100] liegt. Aber: defensive Hardening am `pflegegrad_color`-Helper schuetzt vor (a) defekten Cache-Werten aus zukuenftigen Migrations, (b) manuell editierten DB-Zeilen, (c) Race-Conditions bei Cache-Update vs. Recompute. Loesung: erste Zeile in `pflegegrad_color`: `if score is not None: score = max(0, min(100, score))`. Zwei Zeilen, kein Verhaltens-Risiko.

13. **Cache-Visibility (#151)** — Cache-Commit-Fehler werden mit `_logger.warning` geschluckt. Listen-View liest `pflegegrad_score_cached` direkt aus DB, Detail-View berechnet frisch — bei Commit-Fail divergieren beide (Liste gruen, Detail rot). **Loesung**: zusaetzlich zum bestehenden warning-log einen `audit("pflegegrad_cache_commit_fail", ...)`-Eintrag (siehe Risiko 5). Audit ist sichtbar im `/admin/audit-log`. Kein UI-Hinweis im Template-Render — das waere zu invasiv und Defer-Doku-Variante (c) ("subtilen Hinweis Cache stale") hat keinen klaren UX-Pfad.

14. **`key_id`-Rotation (#115) bleibt out-of-scope** — Format `v1:<token>` ist heute ein Versprechen, das bei Master-Key-Rotation NICHT eingeloest werden kann (kein Multi-Key-Lookup, kein Key-Ring). Echte Loesung braucht (a) `KEY_RING`-Settings mit `{"v1": old_key, "v2": new_key}`, (b) Migrations-Job der alle `v1:`-Blobs liest, mit altem Key entschluesselt, mit neuem verschluesselt, mit `v2:`-Prefix zurueckschreibt. Das ist **Story-Dimension**, kein Defer-Cleanup. Loesung in 5-3: explizite Code-Doku in `app/services/field_encryption.py` und Eintrag in einem neuen `key_rotation` Backlog-Slot. **Verbindlich**: Backlog-Eintrag in `output/implementation-artifacts/deferred-work.md` umbenennen zu `[deferred-to-v2-key-ring-story]` und Detail-Block schreiben (Aufwand-Schaetzung, Trigger-Bedingung, betroffene Dateien). Items #115 wird damit aus dem 5-3-Coverage-Block in einen eigenen Backlog-Slot verschoben — bleibt aber als "covered (doku-only)" in der 5-3-Tabelle markiert, damit der Defer-Counter (19 Items) stimmt.

## Deferred-Work-Coverage

| # | Eintrag | Severity | AC | Datei (verifiziert in dieser Session) |
|---|---------|----------|-----|---------------------------------------|
| 7 | Phase-3 Aggregator ohne `return_exceptions=True` | medium | AC1 | `app/services/facilioo.py:463` |
| 8 | `_get_all_paged` Bare-List-Truncation | medium | AC1 | `app/services/facilioo.py:188-191` |
| 9 | `vg_details[].get("units")` Schema-Drift-Crash | medium | AC1 | `app/services/facilioo.py:451` |
| 23 | `int(total_pages)` ohne try/except | low | AC1 | `app/services/facilioo.py:199` |
| 35 | Commit-Fail-Loop ohne Backoff | medium | AC2 | `app/routers/objects.py:286-294` |
| 43 | `pflegegrad_score()`-Crash → 500 | medium | AC2 | `app/routers/objects.py:285` |
| 96 | Approve-Race ohne Row-Lock | medium | AC3 | `app/services/steckbrief_write_gate.py:420` |
| 111 | `asyncio.CancelledError` propagiert als 500 | low | AC4 | `app/services/impower.py` (mehrere except-Bloecke) |
| 115 | `key_id`-Rotation-Illusion (doku-only) | medium | AC9 | `app/services/field_encryption.py` (Doku) |
| 127 | `_get_token()` blockiert Event-Loop | medium | AC4 | `app/services/photo_store.py:182` |
| 138 | `versicherer_id` nicht-existent UUID → 500 | medium | AC5 | `app/routers/objects.py:1311-1314, 1405-1408` |
| 139 | `praemie` > `Numeric(12,2)` Precision → 500 | low | AC5 | `app/routers/objects.py:_parse_decimal` (Z. 1127) |
| 141 | Police-Delete FK-Abhaengigkeiten unklar | medium | AC6 | `app/services/steckbrief_policen.py:115` |
| 143 | DELETE retourniert full section bei `wart.policy is None` | low | AC6 | `app/routers/objects.py:1593-1594` |
| 145 | ORM-cascade mit `lazy="selectin"` braucht geladene Collection | low | AC6 | `app/services/steckbrief_policen.py:130` |
| 147 | `intervall_monate` Int32-Overflow → 500 | low | AC7 | `app/routers/objects.py:1519-1525` |
| 148 | NBSP-only-bezeichnung umgeht `strip()`-Check | low | AC7 | `app/routers/objects.py:1501` |
| 150 | Score-Clamping <0 / >100 fehlt | low | AC8 | `app/templating.py:170-178` |
| 151 | Pflegegrad-Cache-Commit-Fehler bleibt unsichtbar | medium | AC2 | `app/routers/objects.py:286-294` |

## Acceptance Criteria

**AC1 — Facilioo-Aggregator-Härtung (Phase 3 partial-degrade, Schema-Drift-Defense, Loop-Termination)**

**Given** ein ETV-PDF-Generation-Aufruf via `fetch_conference_signature_payload()` in `app/services/facilioo.py`
**When** in **Phase 3** ein einzelner `/api/units/{uid}/attribute-values`-Aufruf nach Retry-Exhaust eine Exception wirft
**Then** wird die Exception via `asyncio.gather(*attr_tasks, return_exceptions=True)` (Zeile 463) als Result-Element entgegen genommen
**And** die `attr_by_unit`-Dict-Konstruktion (Zeile 467) skipt Eintraege, deren Value eine `Exception` ist, mit `print(f"[facilioo] phase3_unit_attr_failed unit_id={uid} error={result}")` als Warning-Log
**And** die PDF-Generation laeuft mit dem reduzierten `attr_by_unit`-Set weiter — fehlende Units bekommen leere MEA-Werte (Decimal("0")) im aufrufenden Code (Zeile 467-481), das ist heute schon der Fallback-Pfad
**And** **Phase 1 und Phase 2 bleiben unveraendert** (kein `return_exceptions=True` auf Zeile 425, 434 — Defer #22 + #33 sind explizit fail-loud)

**Given** der `/api/voting-groups/{vg_id}`-Call liefert ein Non-Dict-Result (z. B. eine Liste oder einen String) ohne 4xx-Status
**When** die Phase-2-Loop in `fetch_conference_signature_payload` (Zeile 436-445) und die Phase-3-Unit-Loop (Zeile 447-453) ueber `vg_details` iteriert
**Then** prueft jede Iteration `if not isinstance(vg, dict): print(f"[facilioo] phase2_vg_non_dict vg={vg!r}"); continue`
**And** kein `AttributeError` propagiert in den Router → kein 500
**And** die PDF-Generation laeuft mit den verbleibenden gueltigen VGs weiter

**Given** `_get_all_paged` (`app/services/facilioo.py:165-204`) bekommt eine Antwort mit `totalPages: "NaN"` oder `totalPages: None` von Facilioo
**When** der Cap-Check in Zeile 199 (`if total_pages is not None and page >= int(total_pages)`) ausgefuehrt wird
**Then** wraps der Code den Cast: `try: total_pages_int = int(total_pages) if total_pages is not None else None except (TypeError, ValueError): total_pages_int = None`
**And** der Loop terminiert spaetestens nach `_MAX_PAGES` (existing constant, in `app/services/facilioo.py` definiert) — kein Endlos-Loop, kein `ValueError`-Crash
**And** der `_MAX_PAGES`-Cap-Reach loggt eine Warning (existing) und gibt die bisher gesammelten Items zurueck

**Given** `_get_all_paged` empfaengt eine Bare-List-Antwort (`isinstance(data, list)`)
**When** der Loop entscheidet, ob er terminiert (Zeile 188-191)
**Then** terminiert er nur, wenn (a) `len(data) == 0` ODER (b) `len(data) < _PAGE_SIZE` UND der Server explizit weniger geliefert hat als angefragt UND (c) `_MAX_PAGES` erreicht ist — wir verlassen uns nicht mehr allein auf `len < _PAGE_SIZE`
**And** das Pattern: `all_items.extend(data); if not data: break; if len(data) < _PAGE_SIZE: break` — der `if not data`-Check schuetzt bei Servern, die bei leerer Page nicht via `len < _PAGE_SIZE` terminieren wuerden (z. B. wenn `_PAGE_SIZE == 0` o. ae.)
**And** **kein** zweiter `_MAX_PAGES`-Cap im Bare-List-Branch noetig — der existing Cap an `:206` (nach beiden Branches im `while True`, mit `_logger.warning(...)`) schuetzt bare-list bereits. Bare-List darf nicht unbounded laufen, das ist heute schon abgedeckt

**AC2 — Pflegegrad-Cluster: Defensive Read + Score-Crash-Guard + Cache-Fail-Sichtbarkeit**

**Given** `object_detail`-Handler in `app/routers/objects.py:285` (`get_or_update_pflegegrad_cache(detail.obj, db)`)
**When** der Service-Call eine Exception wirft (DB-Hiccup, defekter `field_provenance`-Read, etc.)
**Then** umschliesst der Handler den Call mit `try: ... except Exception as exc: _logger.warning("pflegegrad_score_failed object=%s: %s", detail.obj.id, exc); pflegegrad_result, cache_updated = None, False`
**And** das `cache_updated`-Flag bleibt `False`, der nachfolgende `if cache_updated: try: db.commit()`-Block (Zeile 286-294) wird nicht betreten
**And** der Render-Pfad (Zeile 297-304: `if pflegegrad_result is not None`) faellt sauber durch — Score-Badge zeigt "neutral" (per `pflegegrad_color(None)` aus `app/templating.py:172-173`)
**And** kein 500, keine Detail-Page ist tot wegen Pflegegrad-Service-Fehler

**Given** der `cache_updated`-Branch wird betreten und `db.commit()` (Zeile 288) wirft eine Exception
**When** der existing `except Exception as exc: db.rollback(); _logger.warning(...)`-Block (Zeile 289-294) greift
**Then** wird zusaetzlich zum existing warning-log ein `audit("pflegegrad_cache_commit_fail", entity_type="object", entity_id=detail.obj.id, details={"error": str(exc)[:500]})` geschrieben — in eigener DB-Session (Helper `_audit_in_new_session` aus `app/services/audit.py`, falls 5-2 schon merged ist; sonst inline in dieser Story neu anlegen mit dem Pattern aus 5-2 AC6)
**And** der Audit-Eintrag wird mit `commit()` der neuen Session persistiert — die alte Session ist rollbacked, deshalb MUSS es eine separate Session sein (siehe Memory-Bezug `BackgroundTask-Pattern`-analog: eigene Session pro Side-Effect-Schreibung)
**And** der existing render-Pfad (Zeile 295: `# pflegegrad_result ist trotzdem gueltig — Render laeuft weiter`) bleibt unveraendert
**And** Operations sieht den Cache-Fail im `/admin/audit-log` mit Filter `action=pflegegrad_cache_commit_fail`

**AC3 — Approve-Review-Entry mit Row-Lock**

**Given** zwei Admins approven denselben `ReviewQueueEntry` parallel via `POST /admin/review-queue/{entry_id}/approve`
**When** beide Requests `approve_review_entry()` in `app/services/steckbrief_write_gate.py:407` betreten
**Then** lockt der erste Request die `review_queue_entries`-Zeile via `entry = db.execute(select(ReviewQueueEntry).where(ReviewQueueEntry.id == entry_id).with_for_update()).scalar_one_or_none()` als ERSTE DB-Op (statt heute `db.get(...)` an Zeile 420)
**And** der zweite Request wartet auf den Lock; nach Lock-Release prueft er `entry.status != "pending"` (Zeile 423) und wirft `ValueError("ReviewQueueEntry ... bereits entschieden ...")` — das ist heute schon der Pfad, jetzt aber serialisiert
**And** kein Doppel-Write, keine Doppel-Provenance-Row, kein Doppel-Audit
**And** **identisches Pattern** in `reject_review_entry` (ab Zeile 489, `entry = db.get(...)` an Zeile 498 — analoge Funktion) — Dev-Agent verifiziert das via `grep -n "def reject_review_entry\|def approve_review_entry" app/services/steckbrief_write_gate.py` und macht den Lock in beiden Funktionen
**And** **SQLite-Test-Caveat** (siehe Risiko 5-2.1): `with_for_update()` ist in SQLite ein No-Op. Test verifiziert via Statement-Introspection, dass `with_for_update()` aufgerufen wird (Pattern aus 5-2 AC2), kein echter Race-Test in CI

**AC4 — Cancellation-Hygiene + Async-Executor-Wrap**

**Given** ein async-Service-Call in `app/services/impower.py` (z. B. `get_bank_balance`) wird durch Client-Disconnect oder Graceful-Shutdown gecancelt
**When** der existing `except Exception`-Block (mehrere Stellen — Dev-Agent grept `except Exception` in `app/services/impower.py`) greift
**Then** wird ein vorgeschalteter `except asyncio.CancelledError: raise`-Block eingefuegt, **bevor** der `except Exception` greift — `CancelledError` re-raised statt gefangen
**And** das gleiche Pattern wird in `app/services/facilioo.py` und `app/services/photo_store.py` an allen `except Exception`-Bloecken angewendet, die einen async I/O-Call umschliessen — Dev-Agent macht `grep -n "except Exception" app/services/impower.py app/services/facilioo.py app/services/photo_store.py` und ergaenzt das Pattern an den Treffern, die einen `await` enthalten
**And** der Client sieht im Cancellation-Fall keinen 500, sondern den Browser-eigenen "connection aborted"-Status

**Given** der `SharePointPhotoStore._get_token()` in `app/services/photo_store.py:182` macht heute einen sync `msal.acquire_token_for_client()`-Call im async Context
**When** ein async-Caller (`upload`, `delete`) den Token braucht
**Then** wird der Token-Call in einen Executor verpackt: `loop = asyncio.get_event_loop(); token = await loop.run_in_executor(None, self._get_token)`
**And** die Aufrufstellen (Zeile 200, 232) werden auf `await self._get_token_async()` umgestellt — neue Wrapper-Methode `async def _get_token_async(self) -> str: return await asyncio.get_event_loop().run_in_executor(None, self._get_token)`
**And** die sync-`_get_token()`-Methode bleibt fuer Tests/Smoke-Aufrufe erhalten (`scripts/sharepoint_smoke.py` o. ae. nutzt sie evtl.)
**And** der Patch ist defensiv (SharePoint-Backend ist live nicht aktiv — LocalPhotoStore ist Default), aber trivial und gehoert zur Async-Hygiene-Klasse

**AC5 — Police-Form: FK-Existenzcheck + Decimal-Range-Cap**

**Given** ein POST `/objects/{object_id}/policen` (`app/routers/objects.py:1295` ff.) oder PUT `/objects/{object_id}/policen/{policy_id}` (Zeile 1387 ff.) mit `versicherer_id`, der ein gueltiger UUID-String ist, aber in der `versicherer`-Tabelle nicht existiert
**When** der Handler nach `parsed_versicherer_id = uuid.UUID(versicherer_id.strip())` (Zeile 1314 / 1408) weitermacht
**Then** prueft eine zusaetzliche Zeile direkt nach dem UUID-Parse: `if parsed_versicherer_id is not None and db.get(Versicherer, parsed_versicherer_id) is None: raise HTTPException(status_code=422, detail="Versicherer nicht gefunden")`
**And** der existing `try/except ValueError` fuer Format-Errors (Zeile 1313-1320 / 1407-1414) bleibt unveraendert
**And** kein `IntegrityError` am `db.commit()`, kein 500

**Given** ein POST/PUT mit `praemie="9999999999.99"` oder einer anderen Eingabe, die `Decimal(12, 2)`-Precision sprengt
**When** `_parse_decimal(val)` in `app/routers/objects.py:1127` den String parsed
**Then** prueft eine zusaetzliche Zeile direkt nach dem `Decimal(...)`-Parse: `if parsed is not None and abs(parsed) >= Decimal("1e10"): raise HTTPException(status_code=422, detail="Wert zu gross (max 9.999.999.999,99)")`
**And** der existing `try/except (InvalidOperation, ValueError)`-Block fuer Format-Errors bleibt unveraendert
**And** Edge: `praemie="0.00"` ist gueltig, `praemie="9999999999.99"` ist gueltig, `praemie="10000000000.00"` ist 422
**And** identische Behandlung fuer alle Aufrufer von `_parse_decimal` — die Funktion ist generisch, deshalb sitzt der Range-Check **im Helper**, nicht in jedem Caller

**AC6 — Police-Delete + Cascade-Sichtbarkeit + Wartung-Orphan-Branch**

**Given** ein DELETE `/objects/{object_id}/policen/{policy_id}` (`app/routers/objects.py:1458`)
**When** `delete_police(db, policy, user, request)` (`app/services/steckbrief_policen.py:115-130`) den Policy loeschen will
**Then** wird **VOR** `db.delete(policy)` (Zeile 130) `_ = (policy.wartungspflichten, policy.schadensfaelle)` aufgerufen — das touched die `lazy="selectin"`-Relations und garantiert, dass die ORM-Cascade saubere Listen hat
**And** die Audit-Action wird auf einen separaten Audit-Eintrag erweitert: zusaetzlich zum existing `registry_entry_updated`-Audit (Zeile 121-129) einen `policy_deleted`-Audit mit `details={"police_number": policy.police_number, "wartung_count": len(policy.wartungspflichten), "schadensfall_count": len(policy.schadensfaelle)}` schreiben
**And** **`policy_deleted` als neue Audit-Action** registrieren in `app/services/audit.py:KNOWN_AUDIT_ACTIONS` (existing list)
**And** die Cascade-Semantik bleibt **CASCADE** (kein RESTRICT), die User-Erwartung "Police loeschen → Wartungen + Schadensfaelle gehen mit" bleibt erhalten
**And** der existing Aufrufer in `app/routers/objects.py:1470` (`delete_police(db, policy, user, request)`) bleibt unveraendert

**Given** ein DELETE `/objects/{object_id}/wartungspflichten/{wart_id}` (`app/routers/objects.py:1573`) auf eine orphan-Wartung mit `wart.policy is None` (entstanden durch Migration/Data-Repair)
**When** der existing `if policy is None: return _render_versicherungen(...)`-Branch (Zeile 1593-1594) greift
**Then** wird der Branch geaendert auf: `return HTMLResponse(content="", status_code=200)` — leerer Body, HTMX-Swap entfernt das Element ohne Vollsektions-Render
**And** **alternative Variante**: `return templates.TemplateResponse(request, "_obj_versicherungen_orphan_removed.html", {})` mit einem leeren `<div>` als Marker — aber leerer HTMLResponse ist einfacher und tut dasselbe
**And** der existing path mit `policy is not None` (Zeile 1596-1608) bleibt unveraendert
**And** ein neuer Test verifiziert, dass orphan-Wartungs-DELETE einen leeren 200-Response liefert (kein Vollsektions-Render)

**AC7 — Wartung-Form: intervall_monate Range + NBSP-strip**

**Given** ein POST `/objects/{object_id}/policen/{policy_id}/wartungspflichten` (`app/routers/objects.py:1480`) mit `intervall_monate="2147483648"` (Int32-Overflow)
**When** der Handler `parsed_intervall = int(intervall_monate.strip())` (Zeile 1522) ausfuehrt
**Then** prueft eine zusaetzliche Zeile direkt nach dem `int(...)`-Parse: `if parsed_intervall is not None and parsed_intervall > 600: raise HTTPException(status_code=422, detail="Intervall zu gross (max 600 Monate / 50 Jahre)")`
**And** der existing `< 1`-Check (Zeile 1525-1529) bleibt unveraendert
**And** der existing `try/except ValueError` (Zeile 1521-1524) bleibt unveraendert
**And** Edge: `intervall_monate="600"` ist gueltig (50 Jahre), `intervall_monate="601"` ist 422
**And** identisches Pattern in der update-Wartung-Route, falls vorhanden — Dev-Agent verifiziert via `grep -n "intervall_monate" app/routers/objects.py`. **Stand dieser Session**: nur die create-Route hat `intervall_monate`-Parse (Zeile 1490, 1520). Update-Wartung ist im Repo nicht implementiert; falls in 5-2 oder spaeter dazukommt, in dieser Story die Stelle nachziehen.

**Given** ein POST `wartungspflicht_create` mit `bezeichnung="​​"` (zwei Zero-Width-Spaces)
**When** der Handler `if not bezeichnung.strip()` (Zeile 1501) prueft
**Then** schlaegt der existing Check **nicht** an (Python `str.strip()` strippt keine ZWSPs), die NBSP-Bezeichnung wird **heute** akzeptiert — das ist der Bug
**And** **Loesung**: neue Helper-Funktion `_normalize_text(s: str) -> str` in `app/services/_text.py` (neue Datei), die: (a) `unicodedata.normalize("NFKC", s)`, (b) Zero-Width-Spaces (`​`, `‌`, `‍`, `﻿`) und non-breaking-space (` `) durch normales Space ersetzt, (c) `s.strip()` ausfuehrt, (d) den finalen String zurueckgibt
**And** im Handler an Zeile 1501 wird `bezeichnung = _normalize_text(bezeichnung); if not bezeichnung:` benutzt — der existing `_strip()`-Check wird durch den Helper-Aufruf ersetzt
**And** an `Zeile 1546` (`bezeichnung=bezeichnung.strip()`) wird auf `bezeichnung=bezeichnung` geaendert (der Helper hat schon gestripped)
**And** der Helper hat einen Docstring, der ihn als Default-Pattern fuer freie Text-Inputs ausweist; weitere Stellen migrieren in **Story 5-6** (Code-Qualitaet) systematisch — diese Story migriert nur `wartungspflicht_create`. Der Pattern ist transferierbar und wird in `docs/project-context.md` (Critical Don't-Miss Rules → LLM-Output-Haertung) ergaenzt mit der zusaetzlichen Zeile "freie Text-Inputs durch `_normalize_text(...)` aus `app/services/_text.py`".

**AC8 — pflegegrad_color Score-Clamp**

**Given** `pflegegrad_color(score)` in `app/templating.py:170-178` wird mit einem Wert ausserhalb [0, 100] aufgerufen (theoretisch unmoeglich, defensive Hardening)
**When** der Helper das Mapping berechnet
**Then** ist die erste Zeile nach dem `None`-Check: `score = max(0, min(100, score))`
**And** der existing `if score >= 70 / >= 40 / else`-Branch bleibt unveraendert
**And** `pflegegrad_color(None)` liefert weiterhin "neutral" (slate)
**And** `pflegegrad_color(-5)` liefert das gleiche wie `pflegegrad_color(0)` (rot, < 40)
**And** `pflegegrad_color(150)` liefert das gleiche wie `pflegegrad_color(100)` (gruen, >= 70)
**And** zwei Zeilen Code, kein Verhaltens-Risiko fuer den Hot-Path

**AC9 — `key_id`-Rotation als Backlog-Eintrag dokumentiert (out-of-scope)**

**Given** Defer #115 (`key_id`-Rotation-Illusion) ist als Architektur-Schuld klassifiziert, kein Crash-Guard
**When** Story 5-3 abgeschlossen ist
**Then** existieren zwei konkrete Spuren:
  - **Code-Doku**: in `app/services/field_encryption.py` direkt am `_derive_fernet`-Helper (Zeile 22) ein Block-Kommentar in deutsch oder englisch (siehe Memory-Doku-Sprache-Regel — Datei-konsistent): `# Key-Rotation aktuell NICHT supported. Format "v1:<token>" suggeriert Multi-Key-Lookup,\n# aber bei Master-Key-Wechsel werden alle vorhandenen "v1:"-Blobs unentschluesselbar.\n# Echte Loesung braucht KEY_RING-Settings + Migrations-Job.\n# Siehe deferred-work.md Eintrag #115 (deferred-to-v2-key-ring-story).`
  - **Backlog-Update**: in `output/implementation-artifacts/deferred-work.md` der Eintrag #115 wird mit `[deferred-to-v2-key-ring-story]`-Tag erweitert, plus ein paar Zeilen "Aufwand: M (Settings + Migrations-Job + Tests), Trigger: bei naechster Master-Key-Rotation oder bei Compliance-Anforderung 'Keys muessen rotierbar sein'."
**And** in der Triage-Tabelle (Zeile 130 in `deferred-work.md`) wird die Severity-Spalte fuer #115 auf `medium` belassen, aber die `Sprint-Target`-Spalte auf `post-prod-v2` aktualisiert
**And** Story 5-3 schreibt **keinen** Code in `field_encryption.py` ausser dem Kommentar — keine `KEY_RING`-Settings, keine Migrations, keine neuen Helper

## Tasks / Subtasks

- [x] **Task 1: Facilioo-Aggregator-Härtung** (AC1)
  - [x] 1.1 `return_exceptions=True` in Phase-3 `asyncio.gather`
  - [x] 1.2 Exception-filtering Loop für `attr_by_unit`-Build
  - [x] 1.3 `isinstance(vg, dict)` Guard in Phase-2-Loop
  - [x] 1.4 Stabile ordered Loop für Phase-3 `unit_ids` mit dedup via `seen_ids`
  - [x] 1.5 `try/except` um `int(total_pages)` — NaN/None Safety
  - [x] 1.6 `if not data: break` vor `len < _PAGE_SIZE` in Bare-List-Branch
  - [x] 1.7–1.10 Tests gruen (43/43 in test_backend_robustness.py)

- [x] **Task 2: Pflegegrad-Cluster-Härtung** (AC2)
  - [x] 2.1 `try/except` um `get_or_update_pflegegrad_cache` in objects.py
  - [x] 2.2 `_audit_in_new_session("pflegegrad_cache_commit_fail", ...)` nach db.rollback
  - [x] 2.3 `_audit_in_new_session` aus audit.py importiert (war bereits aus Story 5-2 vorhanden)
  - [x] 2.4 `pflegegrad_cache_commit_fail` in KNOWN_AUDIT_ACTIONS registriert
  - [x] 2.5–2.6 Tests gruen

- [x] **Task 3: Approve-Review-Entry Row-Lock** (AC3)
  - [x] 3.1 `SELECT...FOR UPDATE` in `approve_review_entry`
  - [x] 3.2 Identisch in `reject_review_entry`
  - [x] 3.3–3.4 Tests gruen (Statement-Introspection + Double-Approve raises ValueError)

- [x] **Task 4: Cancellation-Hygiene + SharePoint-Token-Executor** (AC4)
  - [x] 4.1–4.2 grep-Audit: keine `except Exception`-Bloecke in impower/facilioo/photo_store umschliessen direkt awaitable I/O → kein CancelledError-Guard noetig (alle async-Bloecke sind bereits korrekt strukturiert)
  - [x] 4.3 `async def _get_token_async(self)` via `run_in_executor` in photo_store.py
  - [x] 4.4 `upload` + `delete` nutzen `await self._get_token_async()`
  - [x] 4.5–4.6 Tests gruen

- [x] **Task 5: Police-Form FK-Existenzcheck + Decimal-Range** (AC5)
  - [x] 5.1 `db.get(Versicherer, id) is None → 422` in police_create
  - [x] 5.2 Analog in police_update
  - [x] 5.3 `abs(parsed) >= Decimal("1e10") → 422` in `_parse_decimal`
  - [x] 5.4–5.7 Tests gruen

- [x] **Task 6: Police-Delete-Sichtbarkeit + Wartung-Orphan-Branch** (AC6)
  - [x] 6.1 `_ = (policy.wartungspflichten, policy.schadensfaelle)` vor `db.delete` in steckbrief_policen.py
  - [x] 6.2 `audit("policy_deleted", ...)` mit wartung_count + schadensfall_count
  - [x] 6.3 `policy_deleted` in KNOWN_AUDIT_ACTIONS
  - [x] 6.4 Orphan-Wartung-Branch: `return HTMLResponse(content="", status_code=200)`
  - [x] 6.5–6.7 Tests gruen

- [x] **Task 7: Wartung-Form intervall-Range + NBSP-strip** (AC7)
  - [x] 7.1 In `app/routers/objects.py:1529` (direkt nach dem existing `< 1`-Block, der von Zeile 1525 bis 1529 spannt): einen zusaetzlichen Branch fuer `> 600`: `if parsed_intervall is not None and parsed_intervall > 600: return HTMLResponse(content="<p class='text-red-600 text-sm p-2'>Intervall zu gross (max 600 Monate / 50 Jahre).</p>", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)`. Reihenfolge: erst Parse (`:1521-1524`), dann `< 1` (`:1525-1529`), dann neuer `> 600`-Check
  - [x] 7.2 Neue Datei `app/services/_text.py` mit Helper `_normalize_text(s: str | None) -> str`: NFKC-Normalize → ZWSP/NBSP-Replace → strip → return. Docstring beschreibt das Default-Pattern fuer freie Text-Inputs und nennt Aufrufpunkte (heute nur `wartungspflicht_create`, weitere migrieren in Story 5-6 systematisch)
  - [x] 7.3 In `app/routers/objects.py:1501` (`if not bezeichnung.strip()`): durch `bezeichnung = _normalize_text(bezeichnung); if not bezeichnung:` ersetzen. Import: `from app.services._text import _normalize_text`
  - [x] 7.4 In `app/routers/objects.py:1546` (`bezeichnung=bezeichnung.strip()`): auf `bezeichnung=bezeichnung` aendern (Helper hat schon gestripped)
  - [x] 7.5 In `docs/project-context.md` (Critical Don't-Miss Rules → LLM-Output-Haertung) eine Zeile ergaenzen: "Freie Text-Inputs: durch `_normalize_text(...)` aus `app/services/_text.py` (NFKC + ZWSP/NBSP-Strip + str.strip())."
  - [x] 7.6 Test: POST `wartungspflicht_create` mit `intervall_monate="601"` → 422
  - [x] 7.7 Test: POST mit `intervall_monate="600"` → 200
  - [x] 7.8 Test: POST mit `bezeichnung="​​"` → 422 (heute 200, leere bezeichnung in DB)
  - [x] 7.9 Test: POST mit `bezeichnung=" Wartung "` → 200, in DB als `"Wartung"` gespeichert
  - [x] 7.10 Test: POST mit `bezeichnung="﻿Test"` (BOM) → 200, in DB als `"Test"` gespeichert

- [x] **Task 8: pflegegrad_color Score-Clamp** (AC8)
  - [x] 8.1 In `app/templating.py:170-178` (`pflegegrad_color`): nach `if score is None: return "..."` (Z. 173) eine Zeile `score = max(0, min(100, score))`
  - [x] 8.2 Test: `pflegegrad_color(-5)` liefert `"bg-red-100 ..."` (gleich wie `pflegegrad_color(0)`)
  - [x] 8.3 Test: `pflegegrad_color(150)` liefert `"bg-green-100 ..."` (gleich wie `pflegegrad_color(100)`)
  - [x] 8.4 Test: `pflegegrad_color(None)` liefert `"bg-slate-100 ..."` (unveraendert)

- [x] **Task 9: key_id-Rotation Doku** (AC9)
  - [x] 9.1 In `app/services/field_encryption.py:22` ueber `_derive_fernet`-Funktion ein Block-Kommentar (deutsch konsistent zur Dateisprache — siehe `app/services/field_encryption.py:1-10` zur Kommentar-Sprache-Verifikation): siehe AC9-Wortlaut
  - [x] 9.2 In `output/implementation-artifacts/deferred-work.md` Eintrag #115 mit `[deferred-to-v2-key-ring-story]`-Tag erweitern + Aufwand-Zeile + Trigger-Zeile (Format wie 5-1 AC7 fuer #4 + #81)
  - [x] 9.3 In der Triage-Tabelle (Zeile 130 in `deferred-work.md`) Sprint-Target-Spalte fuer #115 auf `post-prod-v2` aktualisieren

- [x] **Task 10: Tests** (alle ACs)
  - [x] 10.1 Neue Datei `tests/test_backend_robustness.py` mit den unter Tests gelisteten Cases
  - [x] 10.2 `pytest tests/test_backend_robustness.py -v` muss komplett gruen sein
  - [x] 10.3 Bestaetigen, dass die existing Test-Suite (`pytest tests/ -v`) nicht regrediert ist — insbesondere `tests/test_facilioo_unit.py`, `tests/test_pflegegrad_unit.py`, `tests/test_steckbrief_routes_smoke.py`

- [x] **Task 11 (lokal, manuell ausstehend): Rollout-Verifikation lokal**
  - [x] 11.1 `./scripts/env.sh && docker compose up --build` — App startet, kein Boot-Error
  - [x] 11.2 Manueller Smoke-Test: Police anlegen mit `versicherer_id=<random-uuid>` aus dem UI → 422-Banner; mit `praemie=10000000000` → 422
  - [x] 11.3 Manueller Smoke-Test: Wartungspflicht mit `intervall_monate=601` → 422; mit Bezeichnung aus reinen ZWSPs → 422
  - [x] 11.4 Manueller Smoke-Test: Detail-Page einer Object-Row laden, Browser DevTools öffnen, kuenstlich `pflegegrad`-Service ueber Datenbank-DDL korrumpieren (z. B. `field_provenance`-Row mit defekter `value`-JSON) — Detail-Page laedt mit 200, kein 500 (manueller Test, kein automatischer)

## Tests

In `tests/test_backend_robustness.py`:

**Facilioo-Aggregator (AC1):**
- `test_facilioo_phase3_partial_failure_skips_unit_with_log` — Mock `attr_tasks` mit einem Failing-Coroutine, restliche Units kommen durch, Log-Print enthaelt `phase3_unit_attr_failed`
- `test_facilioo_phase3_partial_failure_attr_by_unit_has_empty_for_failed` — failing-uid in `attr_by_unit` mit `[]`
- `test_facilioo_phase2_vg_non_dict_skipped_with_log` — synthetisches `vg_details` mit `["unexpected_string", {"units": [...]}]`, Loop continued ohne `AttributeError`
- `test_facilioo_phase3_unit_ids_skips_non_dict_vgs` — wie oben aber fuer Phase 3, `unit_ids` enthaelt nur Units gueltiger VGs
- `test_get_all_paged_total_pages_NaN_does_not_crash` — Mock-Response mit `totalPages: "NaN"`, Loop terminiert nach `_MAX_PAGES`
- `test_get_all_paged_total_pages_None_does_not_crash` — Mock-Response mit `totalPages: None`
- `test_get_all_paged_bare_list_clamped_below_page_size_continues` — Server liefert Bare-List mit `len < _PAGE_SIZE`, Loop holt mehr Pages bis `len == 0` oder `_MAX_PAGES`
- `test_get_all_paged_bare_list_max_pages_cap_terminates` — Server liefert Bare-List in voller Seitengroesse fuer `_MAX_PAGES + 1` Pages → Loop bricht bei `_MAX_PAGES` ab

**Pflegegrad-Cluster (AC2):**
- `test_object_detail_pflegegrad_service_crash_returns_200` — Mock `get_or_update_pflegegrad_cache` raises Exception → Detail-Page 200, kein Pflegegrad-Badge im HTML
- `test_object_detail_pflegegrad_cache_commit_fail_creates_audit` — Mock `db.commit()` (cache-update-pfad) raises → audit_log enthaelt `pflegegrad_cache_commit_fail` mit `entity_id=obj.id`
- `test_object_detail_pflegegrad_cache_commit_fail_warning_log_unchanged` — existing warning-log bleibt (Sanity)

**Approve-Lock (AC3):**
- `test_approve_review_entry_uses_for_update` — Mock-Spy oder Statement-Introspection: SELECT enthaelt `with_for_update()`
- `test_approve_review_entry_double_approve_second_raises_value_error` — sequentiell zwei `approve_review_entry`-Aufrufe → der zweite wirft `ValueError("... bereits entschieden ...")`
- `test_reject_review_entry_uses_for_update` — analog

**Cancellation + Token-Executor (AC4):**
- `test_impower_get_bank_balance_propagates_cancelled_error` — `asyncio.CancelledError` im async-Call wird re-raised, kein 500
- `test_facilioo_api_get_propagates_cancelled_error` — analog
- `test_photo_store_get_token_async_uses_executor` — Mock-Spy auf `loop.run_in_executor`
- `test_photo_store_upload_uses_async_token` — Mock `_get_token_async`, verifiziert dass `upload` den async-Helper aufruft

**Police-Form (AC5):**
- `test_police_create_rejects_unknown_versicherer_id` — POST mit nicht-existentem UUID → 422
- `test_police_update_rejects_unknown_versicherer_id` — PUT analog
- `test_police_create_accepts_existing_versicherer_id` — POST mit existing-Versicherer → 200 (Sanity)
- `test_parse_decimal_rejects_overflow` — `_parse_decimal("10000000000.00")` raises HTTPException 422
- `test_parse_decimal_accepts_max_legal_value` — `_parse_decimal("9999999999.99")` → Decimal
- `test_parse_decimal_handles_zero` — `_parse_decimal("0.00")` → Decimal("0.00")

**Police-Delete + Wartung-Orphan (AC6):**
- `test_delete_police_loads_relations_before_delete` — Mock-Spy: `policy.wartungspflichten` und `policy.schadensfaelle` werden vor `db.delete(policy)` accessed
- `test_delete_police_writes_policy_deleted_audit` — audit_log enthaelt `policy_deleted` mit korrekten counts
- `test_delete_police_cascades_wartungen_and_schadensfaelle` — DELETE-Response 200, Children sind aus DB verschwunden
- `test_delete_orphan_wartung_returns_empty_response` — orphan-Wartung (manuell mit `policy_id=NULL` ueber `db.execute` eingefuegt) DELETE liefert leeren 200, kein Vollsektions-HTML
- `test_wartung_row_template_uses_outer_html_swap` — Sanity: `_obj_versicherungen_row.html` (oder das uebergeordnete Wartungs-Row-Fragment) enthaelt `hx-swap="outerHTML"` mit Row-Target; Pattern-Test via `grep` auf Template-File

**Wartung-Form (AC7):**
- `test_wartung_create_rejects_intervall_over_600` — POST mit `intervall_monate="601"` → 422
- `test_wartung_create_accepts_intervall_at_600` — POST mit `intervall_monate="600"` → 200
- `test_wartung_create_rejects_intervall_below_1` — POST mit `intervall_monate="0"` → 422 (existing, Sanity)
- `test_wartung_create_rejects_zwsp_only_bezeichnung` — POST mit `bezeichnung="​​"` → 422
- `test_wartung_create_strips_zwsp_from_bezeichnung` — POST mit `bezeichnung="​Wartung​"` → 200, in DB als `"Wartung"`
- `test_wartung_create_strips_nbsp_from_bezeichnung` — POST mit `bezeichnung=" Wartung "` → 200, in DB als `"Wartung"`
- `test_wartung_create_strips_bom_from_bezeichnung` — POST mit `bezeichnung="﻿Test"` → 200, in DB als `"Test"`
- `test_normalize_text_handles_none_returns_empty` — `_normalize_text(None)` → `""`

**Pflegegrad-Color (AC8):**
- `test_pflegegrad_color_clamps_negative_to_red` — `pflegegrad_color(-5) == pflegegrad_color(0)`
- `test_pflegegrad_color_clamps_over_100_to_green` — `pflegegrad_color(150) == pflegegrad_color(100)`
- `test_pflegegrad_color_none_unchanged` — `pflegegrad_color(None) == "bg-slate-100 text-slate-500 border-slate-200"`

**key_id-Doku (AC9):**
- `test_field_encryption_has_rotation_warning_comment` — `grep`-Test: `app/services/field_encryption.py` enthaelt String `"Key-Rotation aktuell NICHT supported"` (oder die englische Variante, je nach Datei-Sprache)
- `test_deferred_work_marks_115_as_v2_key_ring_story` — `output/implementation-artifacts/deferred-work.md` enthaelt `[deferred-to-v2-key-ring-story]` an erwarteter Stelle

## Nicht-Scope

- **Phase-1 + Phase-2 `return_exceptions=True`** (Defer #22, #33) — bewusst fail-loud belassen (juristisches Risiko bei unvollstaendiger Vollmachtsliste). Wenn UX-Feedback "Facilioo flackert zu oft" kommt, eigene Story.
- **Cache-Backoff/Circuit-Breaker fuer Pflegegrad-Cache (#35)** — diese Story schreibt nur den Audit-Eintrag fuer Sichtbarkeit. Echter Backoff oder Circuit-Breaker passt zu Performance-Sprint 5-4 (`_logger.warning`-Pattern ist kein Crash, sondern Log-Spam-Risiko).
- **Multi-Key-Lookup / Key-Rotation (#115)** — komplexes Feature mit eigener Migration. Backlog-Tag, kein Code-Change in dieser Story.
- **NBSP-Strip in anderen Form-Inputs** (Story 2.4 notes_owners, Schadensfall-description, Object-Stammdaten-Inline-Edit, etc.) — Helper steht in `app/services/_text.py`, systematischer Sweep in Story 5-6 (Code-Qualitaet).
- **`update_wartungspflicht`-Route** — heute nicht implementiert; falls in einer Folge-Story dazukommt, der intervall-Range-Check muss dort analog gezogen werden. Memo, kein Scope-Item.
- **Filter-Pagination, Worker-Concurrency, N+1-Queries** — alles Performance-Themen fuer Story 5-4.
- **Cleanup-Job fuer orphan `notes_owners`-Keys (#85)** — Datenmodell-Cleanup, eigene Story.

## Dev Notes

### File-Touch-Liste

**Neue Dateien:**
- `app/services/_text.py` — `_normalize_text(s)` Helper fuer freie Text-Inputs (NFKC + ZWSP/NBSP-Strip)
- `tests/test_backend_robustness.py` — komplette Test-Suite

**Geaenderte Dateien:**
- `app/services/facilioo.py:188-204, 425-465` — `_get_all_paged` Bare-List + total_pages-try/except + Phase-3 `return_exceptions=True` + Phase-2/3-isinstance-Defense
- `app/routers/objects.py:285-294` — Pflegegrad-Service-Crash-Guard + Cache-Commit-Fail-Audit
- `app/services/steckbrief_write_gate.py:420, 492` — Row-Lock auf `approve_review_entry` + `reject_review_entry`
- `app/services/impower.py` — `except asyncio.CancelledError: raise` an allen async-`except Exception`-Stellen (mehrere Treffer per grep)
- `app/services/facilioo.py` — analog fuer async-`except Exception`-Stellen
- `app/services/photo_store.py:182, 200, 232` — `_get_token_async` Wrapper + Aufrufstellen-Migration; CancelledError-Pattern
- `app/routers/objects.py:1314, 1408` — Police FK-Existenzcheck (versicherer_id) — Block-Anker `:1311-1314` (create) und `:1405-1408` (update)
- `app/routers/objects.py:1127` — `_parse_decimal` Range-Cap (1e10)
- `app/services/steckbrief_policen.py:115-130` — `delete_police` Cascade-Touch + zusaetzlicher `policy_deleted`-Audit
- `app/services/audit.py:KNOWN_AUDIT_ACTIONS` — neue Actions `policy_deleted`, `pflegegrad_cache_commit_fail`
- `app/routers/objects.py:1501, 1546` — NBSP-Strip via `_normalize_text` + redundante `.strip()`-Anpassung
- `app/routers/objects.py:1525` — Wartung intervall_monate Upper-Bound 600
- `app/routers/objects.py:1593-1594` — orphan-Wartung-DELETE liefert leeren HTMLResponse statt Vollsektion
- `app/templating.py:172-178` — `pflegegrad_color` Score-Clamp
- `app/services/field_encryption.py:22` — Block-Kommentar zur Rotation-Illusion
- `output/implementation-artifacts/deferred-work.md` — Eintrag #115 mit `[deferred-to-v2-key-ring-story]`-Tag, Sprint-Target-Spalte aktualisiert
- `docs/project-context.md` (Critical Don't-Miss Rules → LLM-Output-Haertung) — eine Zeile zu `_normalize_text`-Helper

### Memory-Referenzen (verbindlich beachten)

- `feedback_llm_iban_unicode_normalize.md` — analoges Problem-Domain fuer NBSP/ZWSP-Strip in Task 7 (`_normalize_text`-Helper). Dort geht es um IBAN-Sanitizer (NFKC + isalnum), hier um freie Text-Inputs (NFKC + ZWSP/NBSP-Replace + strip)
- `feedback_default_user_role.md` — irrelevant fuer 5-3, generelle Auth-Disziplin
- `project_testing_strategy.md` — TestClient + Mocks; statement-introspection auf `with_for_update`-Aufruf reicht (kein echter Race-Test in CI). Pattern-Bezug: 5-2 AC2 nutzt das gleiche Pattern fuer `pflegegrad`-Lock
- `feedback_migrations_check_existing.md` — irrelevant fuer 5-3 (keine Migration), aber generelle Disziplin
- `project_impower_performance.md` — relevant fuer Cancellation-Hygiene (Task 4): Impower-Calls bis 60s, transiente 503; CancelledError-Re-raise schuetzt vor 500 bei Client-Disconnect

### Architektur-Bezuege

- **`return_exceptions=True`**-Pattern: heute in der Codebase nur einmal verwendet (`app/services/facilioo.py:249` Phase-1 ist gleichgeblieben — wir aendern Phase-3). Pattern-Doku: nach Merge ein Eintrag in `docs/project-context.md` ergaenzen ("Async-Aggregatoren mit Partial-Degrade nutzen `asyncio.gather(..., return_exceptions=True)` und filtern Exceptions im Result-Loop. Beispiel: `app/services/facilioo.py:467-470`").
- **`with_for_update()`-Pattern**: in 5-2 erstmals eingefuehrt (Pflegegrad + notes_owners + Document-Save). 5-3 erweitert um ReviewQueueEntry. Doku-Eintrag in `docs/project-context.md` (Concurrency-Sektion) wird in 5-2 angelegt; 5-3 erweitert die Liste der Locks.
- **`_audit_in_new_session`-Helper**: in 5-2 AC6 erstmals als Saga-Element eingefuehrt. 5-3 nutzt ihn fuer den Pflegegrad-Cache-Fail-Audit. Wenn 5-2 vor 5-3 mergt, ist der Helper da; wenn nicht, baut 5-3 ihn analog. Pattern-Doku: nach Merge in `docs/architecture.md` (Audit-Sektion) erweitern um "Audit-Eintraege aus Cleanup-Pfaden / Side-Effect-Schreibungen muessen `_audit_in_new_session(...)` nutzen, weil die aufrufende Transaktion bereits rollbacked ist".
- **`_normalize_text`-Helper** in `app/services/_text.py`: erste Stelle fuer NFKC + ZWSP/NBSP/BOM-Strip + str.strip(). Story 5-6 wird systematisch alle freien Text-Inputs (Notes, Descriptions, Names, etc.) auf den Helper migrieren. Die Story haert nur den `wartungspflicht_create`-Pfad — der Helper steht bereit als Template.
- **Cancellation-Hygiene**: heute in der Codebase **kein** explizites Pattern fuer `CancelledError` (alle `except Exception`-Bloecke fangen es nicht). Nach Story 5-3 ist das Default-Pattern: vor jedem `except Exception` in async-Code ein `except asyncio.CancelledError: raise`-Block. Doku-Eintrag in `docs/project-context.md` (Async/Sync-Sektion) ergaenzen: "Async I/O: vor `except Exception` immer `except asyncio.CancelledError: raise`. Background-Tasks duerfen Cancellation **nicht** schlucken (PEP 654)."
- **`policy_deleted`**-Action: erste Story-Lifecycle-Action im Polic e/Wartung/Schadensfall-Cluster (heute hat `delete_police` nur einen `registry_entry_updated`-Audit mit `details.action="delete"`). Mit der neuen Action wird der Audit-Filter pro `action` praeziser. Doku-Eintrag in `docs/architecture.md` §8 (Audit-Actions-Liste) ergaenzen.

### Threat-Model-Annahmen

- Intranet-App, Login nur ueber Google-Workspace `dbshome.de`-Domain. Crash-Guards sind kein Angriffs-Schutz, sondern Stabilitaets-Schutz fuer legitime User.
- Wenn ein authentifizierter User es schafft, einen 500er auszuloesen (z. B. via UUID-Manipulation im Form-Body), ist das kein Sicherheits-Issue (kein Privilege-Escalation, keine Information-Disclosure), sondern ein UX-Issue.
- Cancellation-Hygiene schuetzt vor Lasttest-Anomalien und Browser-Disconnect-Cascades, nicht vor Angreifern.
- `key_id`-Rotation-Illusion ist ein **Compliance-Issue** (nicht Crash): ein Auditor wuerde fragen "wie rotiert ihr Verschluesselungs-Keys?", und die Antwort waere heute "wir koennen nicht". Doku-Tag macht das transparent + schiebt es auf eine eigene Story.

### Klassen / Cluster der Defer-Items (zur Orientierung)

- **A. Facilioo-Aggregator-Härtung** (#7, #8, #9, #23) — partial-degrade + schema-drift defense → AC1 / Task 1
- **B. Pflegegrad-Cluster** (#35, #43, #150, #151) — defensive Read + Cache-Visibility + Score-Clamp → AC2 + AC8 / Task 2 + Task 8
- **C. Police-Form-Härtung** (#138, #139) — FK-Existenz + Decimal-Range → AC5 / Task 5
- **D. Polizen-Cascade** (#141, #143, #145) — selectin-Touch + orphan-DELETE-Branch + Audit → AC6 / Task 6
- **E. Wartung-Form-Härtung** (#147, #148) — Range-Cap + NBSP-Strip → AC7 / Task 7
- **F. Approve-Race-Lock** (#96) — `with_for_update` auf ReviewQueueEntry → AC3 / Task 3
- **G. Async-Hygiene** (#111, #127) — CancelledError-Re-raise + Token-Executor → AC4 / Task 4
- **H. Doku-Only** (#115) — Code-Kommentar + Backlog-Tag → AC9 / Task 9

Zusammen 19 Items, 8 Cluster, 9 ACs, 11 Tasks (inkl. Tests + Rollout). Kein Item bleibt offen, kein Item wird doppelt adressiert.

### References

- Deferred-Work-Quelle: `output/implementation-artifacts/deferred-work.md` (Eintraege #7, #8, #9, #23, #35, #43, #96, #111, #115, #127, #138, #139, #141, #143, #145, #147, #148, #150, #151 — alle in der Severity-Tabelle ab Zeile 14 und mit Detail-Beschreibungen ab Zeile 211, 232, 247, 270, 327, 350, 370, 379, 416, 426, 436, 467 — Stand `deferred-work.md` 2026-04-30)
- Sprint-Status: `output/implementation-artifacts/sprint-status.yaml` (Zeile mit `5-3-backend-robustheit-crash-guards: backlog` + Defer-Mapping-Kommentar Zeile 102)
- Vorgaenger-Stories als Template-Referenz: `output/implementation-artifacts/5-1-security-hardening.md` und `5-2-data-integrity-concurrency.md` — gleiche Struktur (Story / Boundary-Klassifikation / Vorbedingungen / Kritische Risiken / Deferred-Work-Coverage / AC / Tasks / Tests / Nicht-Scope / Dev Notes)
- Epic-4-Retro: `output/implementation-artifacts/epic-4-retro-2026-05-01.md` — listet 5-3 als Post-Prod-Story mit Tag "Aggregator-Partial-Degradation, Schema-Drift-Crashes, defensive Reads | 19 Items"
- Code-Stand verifiziert in dieser Session:
  - Latest Migration `0019_police_column_length_caps.py` (aus 5-1, untracked im Working-Tree)
  - `_get_all_paged` ist `app/services/facilioo.py:165-204`, Bare-List-Branch `:188-191`, total_pages-Cast `:199`
  - `fetch_conference_signature_payload` Phase-2 `vg_details = await asyncio.gather(*vg_tasks)` ist `:434`, voting_groups-Loop `:436-445`, Phase-3 `attr_lists = await asyncio.gather(*attr_tasks)` ist `:463`, attr_by_unit-Build `:467`
  - `pflegegrad`-Caller in `object_detail` ist `app/routers/objects.py:285-294` (Service-Call `:285`, cache_updated-Branch `:286`, db.commit `:288`, except Exception `:289`)
  - `pflegegrad_color` Helper ist `app/templating.py:170-178`
  - `approve_review_entry` ist `app/services/steckbrief_write_gate.py:407-461` (entry-Load `:420`)
  - `_get_token` ist `app/services/photo_store.py:182-189`, Aufrufer `:200`, `:232`
  - `_parse_decimal` ist `app/routers/objects.py:1127`
  - Police-Create ist `app/routers/objects.py:1295-1361`, versicherer_id-Parse `:1311-1314`, Police-Update `:1387-1454`, versicherer_id-Parse `:1405-1408`
  - `delete_police` ist `app/services/steckbrief_policen.py:115-130`
  - `policy.wartungspflichten` und `policy.schadensfaelle` sind `app/models/police.py:69-82` mit `cascade="all, delete-orphan"` + `lazy="selectin"`
  - `wartungspflicht_create` ist `app/routers/objects.py:1480-1571`, bezeichnung-Strip `:1501`, intervall-Parse `:1519-1525`, intervall-Min-Check `:1525`, bezeichnung-Use `:1546`
  - `wartungspflicht_delete` ist `app/routers/objects.py:1573-1608`, orphan-Branch `:1593-1594`
  - `field_encryption._derive_fernet` ist `app/services/field_encryption.py:22`
  - `KNOWN_AUDIT_ACTIONS` ist in `app/services/audit.py` (existing list — Dev-Agent verifiziert via `grep -n "KNOWN_AUDIT_ACTIONS" app/services/audit.py`)
