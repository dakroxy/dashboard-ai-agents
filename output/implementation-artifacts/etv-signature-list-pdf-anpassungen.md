---
title: 'ETV-Unterschriftenliste — PDF-Anpassungen (Footer, Pagination, MEA-Quelle, Summen-Zeile, Umlaute)'
type: 'bugfix'
created: '2026-04-30'
status: 'done'
baseline_commit: '26cadc86ad31e53da4f93bfa57fdff9bea807908'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/output/implementation-artifacts/etv-signature-list.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Vier Befunde am Live-PDF (basis: PLS22, HTS1, HTS7a):
(1) Element-Footer "Erzeugt am … · Datenquelle Facilioo · …" ist ungewuenscht.
(2) `fetch_conference_signature_payload` zieht `voting-groups/shares` + `mandates` ohne Pagination — bei > 10 Voting-Groups (z. B. HTS1 mit 30) verschwinden Zeilen.
(3) MEA-Quelle `/api/conferences/{id}/voting-groups/shares` ist bei den meisten WEGs `"0"` (Pflege-Drift in Facilioo). Die zuverlaessige Quelle ist `/api/units/{id}/attribute-values` mit `attributeId=1438` ("Miteigentumsanteile") — bei PLS22 identisch mit `shares`, bei HTS7a korrekt befuellt waehrend `shares="0"`.
(4) Im PDF-Header steht "Eigentuemer" statt "Eigentümer" — User-facing-Strings im ETV-Modul nutzen ASCII-Umlaute statt echter Umlaute.
Plus User-Wunsch: Summen-Zeile fuer die MEA-Spalte unter der Tabelle.

**Approach:** Footer-Block raus (Seitenzahl bleibt). `_get_all_paged` fuer shares + mandates. Neue Aggregator-Phase 3: pro Unit `/api/units/{uid}/attribute-values` parallel laden, MEA pro Voting-Group = Summe der Unit-Werte mit `attributeId == 1438` (Decimal). PDF-Template bekommt `<tfoot>` mit Gesamt-MEA in der MEA-Spalte. Alle user-facing Strings im ETV-Scope (Templates + Banner-/Audit-Strings im Router) auf echte Umlaute umstellen + neue Regel in `CLAUDE.md` verankern + globalen Sweep als deferred Story aufnehmen.

## Boundaries & Constraints

**Always:**
- Live-Validierung gegen `conference_id=6944` (PLS22, MEA bisher korrekt → muss nach dem Fix dieselben Werte liefern) UND `conference_id=10161` (HTS7a, MEA bisher "0" → muss nach Fix MEA-Werte aus Attributen zeigen).
- MEA-Aggregation in `Decimal`, nicht `float` (Werte koennen Komma-Zahlen sein, z. B. 98.57 — Float-Drift wuerde Summen verfaelschen).
- Attribut-ID `1438` als benannte Konstante mit Code-Comment ("Facilioo-Tenant DBS, GET /api/attributes resolved → name='Miteigentumsanteile'").
- Display-Format identisch zu bestehenden MEA-Werten: ohne ueberfluessige Trailing-Zeros (`Decimal("128").normalize()` → `"128"`, `Decimal("98.57")` → `"98.57"`).
- Fehler aus den neuen `attribute-values`-Calls greifen den bestehenden Banner-Pfad (`_render_select_error`) — kein 500er ans Browser-Frame.
- `<tfoot>` direkt im selben Tabellen-Block (kein zweiter `<table>` darunter), `page-break-inside: avoid` damit die Summen-Zeile nicht alleine auf der naechsten Seite landet.
- Umlaut-Sweep nur **user-facing Strings** umstellen (Templates, Banner-Messages, Audit-Detail-Werte, Tile-Texte). **Identifier** (Variablen, Funktionen, Klassen, Konstanten, Enum-Werte, Modul-Namen, Audit-Event-`action`-Keys) bleiben ASCII. **Code-Kommentare** bleiben unangetastet.

**Ask First:**
- Wenn die Live-Smokes Diskrepanzen zwischen PLS22 (Attribute-Sum vs. alter `shares="128"`) zeigen → HALT. Das wuerde heissen, die beiden Quellen sind nicht 1:1, und wir muessen die Spec neu denken.

**Never:**
- Keine Persistierung der Attribute in der eigenen DB.
- Kein Fallback auf `units[].squareMeters` als MEA-Approximation (juristisch falsch — MEA ist Teilungserklaerung, nicht Realflaeche).
- Kein Schema-Change am Workflow-Modell.
- Kein Tailwind im PDF-Template (WeasyPrint-Limit, bestehende Spec-Boundary).
- Umlaut-Sweep nicht auf Default-System-Prompts (`app/services/claude.py`, `mietverwaltung.py`), nicht auf SEPA-/Mietverwaltung-Templates, nicht auf Admin-Views — diese gehen in die deferred Story (Re-Live-Tests fuer Extraction noetig, Scope hier zu gross).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output | Error Handling |
|---|---|---|---|
| Happy PLS22 | conf 6944, 8 VGs, MEAs gepflegt | 8 Tabellenzeilen, MEAs identisch zur bisherigen Live-Verifikation, Summen-Zeile = `Decimal`-Sum aller 8 | N/A |
| Happy HTS7a | conf 10161, 16 VGs, attribute-values gepflegt | 16 Tabellenzeilen (vorher 10), MEAs aus Attributen statt "0", Summe = Sum der 16 | N/A |
| MEA nicht gepflegt | Conference, alle Units ohne `attributeId=1438` | MEA-Spalte pro Zeile `"—"`, Summen-Zeile `"—"` | N/A |
| Voting-Group mit n Units | VG hat 2 Units mit MEA `100.5` und `99.5` | Eine Zeile, MEA-Spalte zeigt `200`, Summe addiert `200` mit | N/A |
| `attribute-values` 5xx | Persistente 5xx nach Retry | Auswahl-Screen mit roter Banner-Meldung | HTTP 200, kein 500er |
| Conference mit > 100 VGs | Pagination spannt mehrere Seiten | Alle Zeilen geladen, kein Loop, Safety-Cap aus `_get_all_paged` greift bei Schema-Drift | Warning-Log, Cap-Abbruch |

</frozen-after-approval>

## Code Map

- `app/services/facilioo_client.py` — `fetch_conference_signature_payload`: Shares + Mandates via `_get_all_paged` ziehen (Pagination-Fix). Neue Phase 3: pro Unit-ID aus den geladenen Voting-Groups parallel `_get_all_paged(client, f"/api/units/{uid}/attribute-values")`. Aggregator gibt `voting_groups[i]["mea_decimal"]` als `Decimal | None` zurueck (Sum der Unit-Werte mit `attributeId == 1438`, oder `None` wenn keine Unit MEA hatte). `MEA_ATTRIBUTE_ID = 1438` als Modul-Konstante.
- `app/routers/etv_signature_list.py` — `_build_rows` liest `mea_decimal` aus dem Payload, formatiert ueber neue Helper-Funktion `_format_mea(d: Decimal | None) -> str` (`"—"` wenn None, sonst `str(d.normalize())`). Neue Helper-Funktion `_compute_total_mea(rows) -> str`. Template-Context bekommt `mea_total`. Plus: user-facing Strings in den Banner-Messages (`_render_select_error`-Aufrufe) und Audit-`details` auf echte Umlaute umstellen.
- `app/templates/etv_signature_list_pdf.html` — `<footer>`-Block + zugehoerige CSS-Regel raus. `<tfoot>` mit einer Zeile: `colspan=2` "Summe" rechtsbuendig, MEA-Spalte = `{{ mea_total }}`, zwei leere Zellen fuer Unterschrift/Vollmacht. `page-break-inside: avoid` auf `tfoot tr`. Plus: alle deutschen ASCII-Umlaute (z. B. `Eigentuemer` → `Eigentümer`, `fuer` → `für`).
- `app/templates/etv_signature_list_select.html` — alle deutschen ASCII-Umlaute auf echte Umlaute (Auswahl-Screen + Banner-Slot).
- `app/templates/index.html` — nur den ETV-Tile-Block (Beschreibung/Label) auf echte Umlaute. Andere Tiles bleiben unberuehrt.
- `CLAUDE.md` — neue Regel unter "Design-Regeln (verbindlich, vom User vorgegeben)": *"User-facing Texte (Templates, Banner-/Flash-Messages, Audit-Beschreibungen, Tile-Labels) verwenden echte Umlaute (ä/ö/ü/ß), nicht ae/oe/ue/ss. Code-Kommentare und Identifier bleiben ASCII."*
- `output/implementation-artifacts/deferred-work.md` — neuer Eintrag *"Umlaut-Sweep ausserhalb ETV"* mit Scope-Liste (alle Templates, Banner/Flash-Strings, Default-System-Prompts in `claude.py` + `mietverwaltung.py`, Audit-Detail-Strings) und Hinweis auf Re-Live-Tests fuer SEPA-/Mietverwaltungs-Extraction.
- `tests/test_etv_signature_list.py` — Neue Cases: (a) Pagination-Mock mit 16-VG-Response (zwei Pages) → 16 Rows, (b) MEA aus attribute-values korrekt gemerged + Decimal-formatiert, (c) Multi-Unit-VG → MEA-Sum, (d) MEA-Fallback `"—"` wenn Attribut fehlt, (e) `mea_total` korrekt im Template-Context, (f) `attribute-values` 5xx → Banner. Bestehende deutsche Assert-Strings ggf. an echte Umlaute anpassen, falls sie auf Banner-Texte aus dem Router asserten.

## Tasks & Acceptance

**Execution:**
- [x] `app/services/facilioo_client.py` -- Pagination-Fix in `fetch_conference_signature_payload` (Shares + Mandates ueber `_get_all_paged`); neue Phase 3 mit asyncio.gather pro Unit-ID; `MEA_ATTRIBUTE_ID = 1438`-Konstante; pro Voting-Group `mea_decimal: Decimal | None` setzen -- Behebt Pagination-Bug + neue robuste MEA-Quelle.
- [x] `app/routers/etv_signature_list.py` -- `_format_mea`-Helper + `_compute_total_mea`-Helper; `_build_rows` setzt `row.shares` aus `mea_decimal`; `generate_pdf` uebergibt `mea_total` an Template-Context; user-facing Strings (Banner/Audit) auf echte Umlaute -- erfuellt User-Wunsch fuer Summen-Zeile + bindet neue Quelle + Umlaute.
- [x] `app/templates/etv_signature_list_pdf.html` -- Element-Footer-Block + footer-CSS entfernen; `<tfoot>` mit Summen-Zeile (Label "Summe" colspan=2 rechtsbuendig, MEA-Wert in der MEA-Spalte) ergaenzen, `page-break-inside: avoid`; ASCII-Umlaute → echte Umlaute -- Footer-Removal + Summen-Zeile + Umlaute.
- [x] `app/templates/etv_signature_list_select.html` -- ASCII-Umlaute → echte Umlaute (Auswahl-Screen, Banner-Slot, Button-Texte).
- [x] `app/templates/index.html` -- ETV-Tile-Block (Label/Beschreibung) auf echte Umlaute umstellen, andere Tiles unberuehrt lassen.
- [x] `CLAUDE.md` -- Regel "User-facing Texte: echte Umlaute" unter "Design-Regeln (verbindlich, vom User vorgegeben)" einfuegen -- macht die Convention fuer alle zukuenftigen Aenderungen verbindlich.
- [x] `output/implementation-artifacts/deferred-work.md` -- Eintrag "Umlaut-Sweep ausserhalb ETV" anlegen (Scope-Liste + Re-Live-Test-Hinweis fuer Extraction) -- macht den globalen Sweep auffindbar fuer eine separate Story.
- [x] `tests/test_etv_signature_list.py` -- Neue Cases gemaess I/O Matrix (Pagination >10 VGs, MEA aus Attributes, Multi-Unit-VG, Fallback "—", `mea_total`-Context, 5xx-Banner); bestehende Asserts auf deutsche Banner-Strings ggf. an echte Umlaute anpassen -- deckt alle Edge-Cases der Matrix ab und haelt Tests gruen.

**Acceptance Criteria:**

- Given Conference 6944 (PLS22), when das PDF erzeugt wird, then enthaelt es **8 Tabellenzeilen** mit MEAs `128, 128, 94, 128, 193, 128, 107, 94` (identisch zur bisherigen Live-Verifikation) und eine Summen-Zeile mit `1000`.
- Given Conference 10161 (HTS7a), when das PDF erzeugt wird, then enthaelt es **16 Tabellenzeilen** (vorher 10), MEAs sind nicht mehr `"0"` sondern aus `/api/units/{uid}/attribute-values` gezogen, Summen-Zeile zeigt die Decimal-Sum.
- Given irgendeine Conference, when das PDF erzeugt wird, then **enthaelt das PDF keinen "Erzeugt am …"-Block** mehr, aber die Seitenzahl unten rechts (`Seite X / Y`) **bleibt** erhalten.
- Given alle Units einer Conference haben kein `attributeId=1438`-Wert, when das PDF erzeugt wird, then zeigt jede MEA-Zelle `—` und die Summen-Zeile zeigt `—` (kein Crash, kein "0").
- Given Facilioo liefert beim `attribute-values`-Aufruf persistent 5xx, when der User submitted, then bleibt der Auswahl-Screen mit Banner sichtbar (HTTP 200, kein 500er).
- Given die Tabelle hat eine Summen-Zeile, when das PDF mehrseitig wird, then steht die Summen-Zeile auf derselben Seite wie die letzte Datenzeile (page-break-inside: avoid).
- Given das fertige PDF einer beliebigen Conference, when ich den Header/die Tabellen-Spalten/Banner inspiziere, then erscheinen alle deutschen Woerter mit echten Umlauten (z. B. "Eigentümer", "für", "Versammlung") und kein "Eigentuemer"/"fuer"/etc. mehr; ausserhalb des ETV-Scope (SEPA, Mietverwaltung, Admin, Default-Prompts) bleibt der Bestand wie vorher.
- Given `CLAUDE.md`, when ich die Datei oeffne, then steht unter "Design-Regeln (verbindlich, vom User vorgegeben)" eine Zeile, die echte Umlaute fuer user-facing Texte verbindlich macht und Identifier/Kommentare ausnimmt.
- Given `output/implementation-artifacts/deferred-work.md`, when ich die Datei oeffne, then existiert ein Eintrag "Umlaut-Sweep ausserhalb ETV" mit Scope-Liste und Hinweis auf Re-Live-Tests fuer Extraction.

## Design Notes

**Aggregator Phase 3 (Skizze):**

```python
# Phase 3: MEA pro Unit parallel ueber alle Voting-Groups
unit_ids = {u.get("id") for vg in voting_groups for u in (vg["voting_group"].get("units") or []) if u.get("id")}
attr_tasks = {uid: _get_all_paged(client, f"/api/units/{uid}/attribute-values") for uid in unit_ids}
attr_results = dict(zip(attr_tasks.keys(), await asyncio.gather(*attr_tasks.values())))
# Pro VG MEA aus den Units summieren
for entry in voting_groups:
    total = Decimal(0); seen = False
    for u in (entry["voting_group"].get("units") or []):
        for av in attr_results.get(u.get("id"), []):
            if av.get("attributeId") == MEA_ATTRIBUTE_ID and av.get("value"):
                total += Decimal(str(av["value"])); seen = True
    entry["mea_decimal"] = total if seen else None
```

**Warum Decimal nicht Float:** Im Live-Probe waren MEAs sowohl Integer (`"128"`, `"640"`) als auch Komma-Werte (`98.57` lt. Screenshot). `Decimal("0.1") + Decimal("0.2") == Decimal("0.3")`, `0.1 + 0.2 != 0.3` — bei Summen ueber 30+ Zeilen wuerde Float-Drift sichtbar.

**`<tfoot>`-Layout:**
```html
<tfoot>
  <tr>
    <td colspan="2" style="text-align:right; font-weight:600;">Summe</td>
    <td class="col-mea" style="font-weight:700;">{{ mea_total }}</td>
    <td colspan="2"></td>
  </tr>
</tfoot>
```
`tfoot tr { page-break-inside: avoid; border-top: 1pt solid #111; }` haelt Summe + letzte Datenzeile beisammen.

## Review Findings

_Code review 2026-04-30 (3 layers: blind / edge-case / acceptance auditor) — diff filtered to ETV-Anpassungen-Scope, 894 Lines._

**Patch (angewandt):**

- [x] [Review][Patch] **NaN/Infinity-Decimal-Vergiftung** [`app/services/facilioo_client.py:355`] — `Decimal("NaN")` / `Decimal("Infinity")` / `Decimal("-Infinity")` / `Decimal("sNaN")` sind valide Konstruktoren, die den `(InvalidOperation, ValueError)`-Catch passieren. `parsed.is_finite()`-Guard greift jetzt; Logging als Warning. Test `test_aggregator_skips_nan_and_infinity_values` (4 Parametrize-Faelle).
- [x] [Review][Patch] **`break` nach erstem MEA-Match pro Unit** [`app/services/facilioo_client.py:362`] — schuetzt vor Doppel-Aufaddieren, falls Facilioo (hypothetisch) mehrere `attributeId=1438`-Rows pro Unit liefert. Test `test_aggregator_uses_first_attribute_value_when_multiple_present`.

**Defer (in `deferred-work.md`):**

- [x] [Review][Defer] Phase-3 Aggregator ohne `return_exceptions=True` — N-Unit-Multiplikation des bereits-deferred Phase-1-Risikos.
- [x] [Review][Defer] `_get_all_paged` Bare-List-Truncation — drei neue Aufrufstellen, aber Live-Probe zeigt nur dict-Wrapped-Responses; nicht aktiv triggerbar.
- [x] [Review][Defer] `vg_details[]` Non-Dict-Guard — pre-existing Schema-Drift-Risiko in Phase 2.
- [x] [Review][Defer] Tfoot near-empty page (WeasyPrint-Layout-Edge-Case).

**Reject (Begruendung kompakt):**

- [x] [Review][Reject] Tfoot Column-Count "5 vs 4" (Blind Hunter) — False alarm, Header hat 5 Spalten (`col-vk` uebersehen).
- [x] [Review][Reject] Duplicate unit-ids across VGs (Edge Case Hunter) — Facilioo-Domain-Modell erlaubt eine Unit nur in einer Stimmgruppe.
- [x] [Review][Reject] Negative-Zero / Arabic-Indic Digits (Edge Case Hunter) — extrem hypothetische Datenstaende.
- [x] [Review][Reject] `_format_decimal`-`or "0"` "unreachable" (Blind Hunter) — defensiv-ok, kein Behavior-Change.
- [x] [Review][Reject] CLAUDE.md "Self-Contradiction" (Blind Hunter) — keine Kommentar-Umlautisierung im Diff.
- [x] [Review][Reject] `_format_mea` Type-Fragility bei legacy strings (Blind Hunter) — kein realer Caller, interne Helper.
- [x] [Review][Reject] Diverse Test-Mock-Quality nits (alle drei Reviewer).

## Verification

**Commands:**
- `docker compose exec app pytest tests/test_etv_signature_list.py -v` — alle Cases gruen, inkl. der neuen Pagination/MEA/Summen-Tests.

**Manual checks (Live-Smoke):**
- PLS22 (id=6944): 8 Zeilen, MEAs identisch zur Spec-`done`-Verifikation, Summe = 1000.
- HTS7a (id=10161): 16 Zeilen (vorher 10), MEAs aus Attribut-Values, Summe = Decimal-Sum.
- HTS1 (id=9245 oder 10155): 30 Zeilen (falls Attribute gepflegt) oder 30 Zeilen mit `—`-MEA.
- PDF-Optik: kein "Erzeugt am …"-Footer mehr, Seitenzahl unten rechts steht, Summen-Zeile direkt unter der letzten Datenzeile mit Trennlinie.

## Suggested Review Order

**Aggregator: neue MEA-Quelle + Pagination-Fix**

- Konstante `MEA_ATTRIBUTE_ID = 1438` mit Begruendungs-Comment (Facilioo-DBS-Tenant).
  [`facilioo_client.py:39`](../../app/services/facilioo_client.py#L39)

- Aggregator-Docstring: drei Phasen, MEA aus `/api/units/{uid}/attribute-values` als robustere Quelle.
  [`facilioo_client.py:266`](../../app/services/facilioo_client.py#L266)

- Phase 1 nutzt jetzt `_get_all_paged` fuer shares + mandates (Pagination-Bug-Fix).
  [`facilioo_client.py:296`](../../app/services/facilioo_client.py#L296)

- Phase 3: pro Unit parallel `attribute-values`, MEA = Decimal-Sum, `mea_decimal` pro Voting-Group.
  [`facilioo_client.py:323`](../../app/services/facilioo_client.py#L323)

- Defensive Haertung (Review-Patches): `is_finite()`-Guard gegen NaN/Infinity + `break` nach erstem Match pro Unit.
  [`facilioo_client.py:362`](../../app/services/facilioo_client.py#L362)

- Neue Public-Methode `list_unit_attribute_values` (paginated).
  [`facilioo_client.py:250`](../../app/services/facilioo_client.py#L250)

**Router: Decimal-Format + Summen-Zeile**

- `_format_decimal` mit `format(d, "f")` + rstrip — `Decimal.normalize()` rutscht in Exponential.
  [`etv_signature_list.py:69`](../../app/routers/etv_signature_list.py#L69)

- `_format_mea` mappt `Decimal | None` auf String / `"—"`.
  [`etv_signature_list.py:82`](../../app/routers/etv_signature_list.py#L82)

- `_compute_total_mea` summiert pro Voting-Group; alle `None` → `"—"`.
  [`etv_signature_list.py:89`](../../app/routers/etv_signature_list.py#L89)

- `_build_rows` liest `mea_decimal` aus dem Payload (Quelle gewechselt).
  [`etv_signature_list.py:205`](../../app/routers/etv_signature_list.py#L205)

- `mea_total` im Render-Context (loest die `<tfoot>`-Zelle).
  [`etv_signature_list.py:379`](../../app/routers/etv_signature_list.py#L379)

**PDF-Template: Footer raus, tfoot rein, Umlaute**

- `<th>Eigentümer` (echter Umlaut).
  [`etv_signature_list_pdf.html:127`](../../app/templates/etv_signature_list_pdf.html#L127)

- `<tfoot>` mit Summen-Zeile, `page-break-inside: avoid`, Trennlinie zur letzten Datenzeile.
  [`etv_signature_list_pdf.html:158`](../../app/templates/etv_signature_list_pdf.html#L158)

**Umlaut-Sweep (ETV-Scope)**

- Auswahl-Screen: Eigentümerversammlung / wählen / verfügbar.
  [`etv_signature_list_select.html:6`](../../app/templates/etv_signature_list_select.html#L6)

- ETV-Tile: für eine ETV — Eigentümer, Einheiten, MEA … (andere Tiles unberuehrt).
  [`index.html:95`](../../app/templates/index.html#L95)

**Convention + Backlog**

- Neue Design-Regel "User-facing Texte: echte Umlaute" mit Identifier/Kommentar-Carve-out.
  [`CLAUDE.md:168`](../../CLAUDE.md#L168)

- Deferred-Work-Block fuer den globalen Umlaut-Sweep + 4 Code-Review-Defer-Findings.
  [`deferred-work.md:5`](deferred-work.md#L5)

**Tests**

- Aggregator: Pagination >10 VGs, MEA-Quelle, Multi-Unit-Sum, NaN/Infinity-Filter, Multi-Row-Break, 5xx-Banner.
  [`test_etv_signature_list.py:296`](../../tests/test_etv_signature_list.py#L296)

- Helper: `_format_decimal` Trailing-Zeros-Edge-Cases, `_compute_total_mea`-Pfade.
  [`test_etv_signature_list.py:104`](../../tests/test_etv_signature_list.py#L104)

- Template-Render: tfoot da, Footer raus, echte Umlaute.
  [`test_etv_signature_list.py:519`](../../tests/test_etv_signature_list.py#L519)
