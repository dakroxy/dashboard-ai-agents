---
title: 'Umlaut-Sweep ausserhalb ETV'
type: 'chore'
created: '2026-04-30'
status: 'done'
baseline_commit: 'ea0090795da0598ab189c548bb4b0a36ab6d6cde'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Ausserhalb des ETV-Moduls stehen user-facing deutsche Texte noch in ASCII-Umlaut-Schreibweise (`ae/oe/ue/ss`). Die CLAUDE.md-Regel verlangt echte Umlaute (`ä/ö/ü/ß`); aktuell sieht der User „Mietvertraege", „Gebaeude", „verfuegbar". Der Sweep ist als Backlog-Punkt in `deferred-work.md` Zeile 21–27 vorgesehen.

**Approach:** Alle user-facing Strings in Templates, Router-Banner/Flash/HTTP-Details, Audit-`details`-Texten, System-Prompts und betroffenen Test-Asserts auf echte Umlaute umstellen. Identifier (Variablennamen, Funktionsnamen, JSON-Field-Keys, URL-Slugs, Audit-`action`-Keys, Permission-Strings, Logger-Event-Namen, Pydantic-Field-Aliases) und Code-Kommentare bleiben ASCII. System-Prompts werden im selben Schritt umgestellt — Re-Live-Tests fuer SEPA / Mietverwaltung / Contact-Create erfolgen anschliessend manuell durch den User.

## Boundaries & Constraints

**Always:**
- Echte Umlaute in: HTML-Text-Knoten, `placeholder=`/`title=`/`aria-label=`/`alt=`-Werten, Jinja-`{{ "..." }}`-Strings, Audit-`details`-Werten, HTTPException-`detail`-Strings, Flash-/Toast-Texten, System-Prompts (Description-/Anweisungs-Text), Test-Asserts auf gerenderte Strings.
- ASCII unveraendert in: Python/JS-Identifiern, JSON-Field-Keys (`weg_kuerzel` bleibt), Pydantic-Field-Namen + `alias=`-Werten, Audit-`action`-Keys (`object_updated` bleibt), Permission-Strings (`objects:approve_ki` bleibt), URL-Pfaden, CSS-Klassen, `data-*`-Attributen, Logger-Event-Strings (`logger.info("user_created")` bleibt), Datenbank-Spalten/Enum-Werten, Code-Kommentaren.
- Pro Datei nacharbeiten; kein blindes `sed`. False-Positive-Filter beachten: englische Worte (`use`, `user`, `success`, `request`, `response`, `update`, `queue`, `password`), Eigennamen, ASCII-Identifier.
- Tests parallel zur Source-Aenderung anpassen; nach jedem Block `pytest -x` lokal gruen.

**Ask First:**
- Wenn ein Pydantic-Schema einen `alias="WEG-Kuerzel"` o. ae. nutzt, der ueber das LLM-JSON in den Code wandert: stoppen und fragen, ob Alias mitgezogen wird (Risiko: laufende Extraktionen mit altem Alias brechen).
- Wenn ein User-facing String aus einer DB-Tabelle stammt (z. B. seed-data fuer Workflows, Roles): stoppen und fragen, ob Migration noetig ist oder Wert nur in `_seed_*()`-Funktion ueberschrieben wird.

**Never:**
- ETV-Modul anfassen (`app/templates/_etv_*`, `app/routers/etv_signature_list.py`, `app/services/etv_*`, `app/services/facilioo_*` PDF-Generator, `tests/test_etv_*`) — dort bereits gemacht.
- Code-Kommentare umschreiben (`# Eigentuemer-Check` bleibt).
- Identifier in JSON-Antworten an Impower oder andere externe APIs aendern.
- `git mv` oder Datei-Renames — reine Inhalts-Aenderung.
- Logger-Strings, die als grep-Anker fuer Ops dienen, anfassen.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Template mit ASCII-Umlaut im sichtbaren Text | `case_detail.html:201 "5 Gebaeude"` | Nach Sweep: `"5 Gebäude"` | N/A |
| Pydantic-Field-Description in System-Prompt | `claude.py:53 "WEG-Kuerzel wie HAM61"` | Prompt-Text auf `"WEG-Kürzel wie HAM61"`; JSON-Key `weg_kuerzel` unveraendert | Re-Live-Test SEPA muss extrahieren wie vorher |
| Audit-Detail-String im Router | `objects.py: audit(... details="Objekt geaendert")` | `details="Objekt geändert"`; `action="object_updated"` unveraendert | N/A |
| Test-Assert auf gerenderten String | `tests/test_finanzen_routes_smoke.py:174 assert "Saldo aktuell nicht verfuegbar"` | Assert auf `"Saldo aktuell nicht verfügbar"` | Wenn Source-Datei nicht angepasst: Test schlaegt fehl — Fix in selbem Patch |
| Englisches Wort als False-Positive | `use_cache=True`, `password_hash`, `request.url` | Bleibt unangetastet | N/A |
| HTML-Entity bereits encoded | `_extraction_block.html:216 "ge&auml;ndert"` | Auf direktes `"geändert"` umstellen (UTF-8-Output ist Standard) | N/A |

</frozen-after-approval>

## Code Map

- `app/services/claude.py`, `app/services/mietverwaltung.py` — System-Prompts + Extraction-Prompts. Re-Live-Tests SEPA / Mietverwaltung / Contact-Create danach.
- `app/routers/{objects,cases,documents,contacts,admin,registries,auth}.py` — HTTPException-Details, Banner/Flash, Audit-`details`-Strings.
- `app/templates/index.html` — Tile-Beschreibungen + „Oeffnen"-Buttons.
- `app/templates/case_detail.html` — groesste Template-Datei (~20 Treffer).
- `app/templates/{cases_list,contact_create,_obj_*,_due_radar_rows,_extraction_*,_macros,_chat_*,_registries_*,_versicherer_rows,registries_versicherer_detail}.html` — Steckbrief-Sektionen + Partials.
- `app/templates/admin/*.html` — Admin-Views (Roles, Sync-Status, Review-Queue).
- `tests/test_{zugangscodes,finanzen,technik,wartungspflichten}_routes_smoke.py` — Asserts auf deutsche Strings, synchron mit jedem Source-Patch.
- `output/implementation-artifacts/deferred-work.md` — nach Abschluss den Eintrag entfernen.

## Tasks & Acceptance

**Execution:**
- [x] `app/services/claude.py` -- `DEFAULT_SYSTEM_PROMPT` + `DEFAULT_CHAT_SYSTEM_PROMPT` Description-Text auf echte Umlaute (JSON-Keys / Pydantic-Aliases unveraendert) -- Schritt 1, hoechstes Risiko zuerst, vor Templates fertig haben damit Re-Live-Test fokussiert laufen kann
- [x] `app/services/mietverwaltung.py` -- `CLASSIFY_PROMPT`, `DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT`, `DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT`, Extraction-Prompts (Verwaltervertrag/Grundbuch/Mietvertrag/Mieterliste) auf echte Umlaute -- analog claude.py
- [x] `app/routers/objects.py` -- HTTPException-`detail`-Strings + Audit-`details`-Werte auf echte Umlaute -- Router-Sweep zuerst, klarer Diff vor Templates
- [x] `app/routers/documents.py` -- HTTPException-`detail` + Audit-Strings -- analog
- [x] `app/routers/cases.py` -- DOC_TYPES-Display-Labels (`"Mieterliste / Flaechenliste"` → `"Mieterliste / Flächenliste"`) + Banner/Flash + Audit -- DOC_TYPES sind user-facing Display-Werte, JSON-Keys (`mieterliste`) bleiben
- [x] `app/routers/contacts.py` -- Banner/Flash + Audit-Strings -- analog
- [x] `app/routers/admin.py` -- Banner/Flash + Audit-Strings -- inkl. Review-Queue-Filter-Labels
- [x] `app/routers/registries.py`, `app/routers/auth.py` -- Banner/Flash falls vorhanden -- analog
- [x] `app/templates/index.html` -- Tile-Beschreibungen + „Oeffnen"-Buttons -- Tile-Labels sind besonders sichtbar
- [x] `app/templates/case_detail.html` -- 20+ Treffer (Mietvertraege/Gebaeude/Faelle/hinzufuegen/ausfuehren/uebertragen/waehlen/ausgewaehlte) -- groesste Single-Datei, sorgfaeltig
- [x] `app/templates/cases_list.html`, `app/templates/contact_create.html` -- Mietverwaltungs-/Contact-UI -- analog
- [x] `app/templates/_obj_*.html`, `app/templates/_due_radar_rows.html`, `app/templates/_extraction_*.html`, `app/templates/_chat_*.html`, `app/templates/_macros.html`, `app/templates/_registries_*.html`, `app/templates/_versicherer_rows.html`, `app/templates/registries_versicherer_detail.html` -- Partials/Sektionen -- HTML-Entity `ge&auml;ndert` in `_extraction_block.html` auf direktes `geändert`
- [x] `app/templates/admin/role_edit.html`, `app/templates/admin/sync_status.html`, `app/templates/admin/*` -- Admin-Views -- inkl. „Jetzt ausfuehren"-Button
- [x] `tests/test_zugangscodes_routes_smoke.py`, `tests/test_finanzen_routes_smoke.py`, `tests/test_technik_routes_smoke.py`, `tests/test_wartungspflichten_routes_smoke.py` -- 5+ Asserts auf gerenderte Strings synchron halten -- mit jedem Source-Patch im selben Edit-Schwung
- [x] `output/implementation-artifacts/deferred-work.md` -- „Umlaut-Sweep ausserhalb ETV"-Eintrag (Zeilen 21–27) entfernen -- nach komplettem Sweep
- [x] Re-Run `pytest -x tests/` -- ganze Suite gruen, keine Reststellen mit ASCII-Umlauten in user-facing Asserts

**Acceptance Criteria:**
- Given ein Mietverwaltungs-Fall im UI, when der User die Detail-Seite oeffnet, then sieht er „Mietverträge", „Gebäude", „Fälle", „hinzufügen", „ausführen", „übertragen" — keine ASCII-Umlaute mehr.
- Given ein SEPA-Mandat-Upload, when die Extraktion laeuft, then liefert das LLM dieselben Felder wie vorher (`weg_kuerzel`, `creditor_id`, `iban`, ...) und das Ergebnis-JSON ist strukturell unveraendert.
- Given ein Aufruf von `/admin/audit-log`, when ein neuer Audit-Eintrag entsteht, then enthaelt der `details`-Text echte Umlaute; `action`-Keys bleiben ASCII.
- Given die volle Test-Suite, when `pytest -x` laeuft, then alle Tests gruen.
- Given `grep -rE '(verfuegbar|Mietvertraege|Gebaeude|Faelle|hinzufuegen|ausfuehren|uebertragen|waehlen|ausgewaehlte|moeglich|gebraeuchlich|Eigentuemer|Glaeubiger|erklaerend|Flaechenliste|Uebersicht|zusammenfuegen|Saetze|aenderung|Anderung)' app/ tests/ --include='*.py' --include='*.html'` (ohne ETV-Pfad), when ausgefuehrt, then keine Treffer in user-facing Strings.

## Spec Change Log

**2026-04-30 — Review-Patches (Blind Hunter, Edge Case Hunter, Acceptance Auditor):**
- Patch: 4 in step-04 vom Blind Hunter gefundene Reststellen (`Bloecke auf dem Grundstueck`, `Flaeche`/`Flaeche m²`-Placeholder, `naechsten` in `admin/sync_status.html`).
- Patch: 9 weitere Reststellen vom Edge Case Hunter und Acceptance Auditor gefunden (Wort-Pattern, die das Spec-grep nicht abdeckte): `Laeufe`/`Laeuft`/`Uebersprungen`/`Naechster`/`fuer Cluster` in `admin/sync_status.html`, `Uebertragung`/`laeuft` in `case_detail.html`, `Spaeter nicht mehr aenderbar` in `admin/role_edit.html`, `laeuft`/`Vorschlaege`/`koennen` in `contact_create.html`, `Berechtigungs-Bundles fuer User` in `admin/roles_list.html`, `Eintraege` in `admin/logs.html`, `_EXTRACTION_FIELD_LABELS` HTML-Entities in `documents.py`, `beruecksichtige diese` Lernnotizen-Header in `claude.py`/`mietverwaltung.py`, `KI-Vorschlaege freigeben` in `permissions.py`, `Inline-Edit nur fuer …` in `document_field_edit.py`, `Bitte BIC im Chat ergaenzen oder IBAN pruefen` in `impower.py`. Alle als trivial fixable eingestuft.
- Defer: Workflow-Description-Strings in der Live-DB (Migration), `onsubmit`-JS-Escape-Pattern, Audit-`details_json` Ops-Doku — siehe `deferred-work.md`.
- Reject: `test_invalid_iban_captured_in_error` (Test ist tolerant gebaut, schwifty liefert „Invalid"; läuft grün).
- KEEP: Reihenfolge Services → Router → Templates → Tests funktioniert, Pydantic/LLM-Schema-Sync-Regel hat Bestand (keine Field-Keys angefasst), Audit-Backward-Compat akzeptiert.

## Design Notes

**Reihenfolge der Patches matters:**
1. Services (System-Prompts) zuerst → Re-Live-Test-Block unmittelbar verifizierbar.
2. Router danach → klarer Diff fuer Banner/Flash, einfach review-bar.
3. Templates ganz am Ende → grosse Volumen-Aenderung, aber rein visuell.
4. Tests jeweils im selben Patch wie das Source-File → keine roten Builds zwischen den Schritten.

**False-Positive-Discipline:** Vor jedem Edit pruefen: ist das Wort wirklich Deutsch und user-facing? `use_cache`, `password`, `success`, `failure` (Status-Enum), `update_payload`, `request_id`, `response_data` — bleiben.

**Pydantic / LLM-Schema-Sync (kritisch):** Pydantic-Field-Namen sind Identifier (z. B. `weg_kuerzel`, `creditor_id`) und bleiben ASCII. Im Prompt darf der Description-Text — also `"WEG-Kuerzel wie HAM61"` — auf echte Umlaute gehen, weil das LLM den Description-Text als Anweisungs-Hint liest, nicht als Schema-Anker. Der Schema-Anker ist der Field-Key (z. B. `"weg_kuerzel"` im JSON-Output). Wenn ein Pydantic-Feld einen `alias="WEG-Kuerzel"` hat, der ueber das LLM-JSON wandert — STOPP, fragen.

**Audit-Backward-Compat:** Bestehende DB-Audit-Eintraege mit ASCII-Umlauten in `details` bleiben unangetastet — nur neue Eintraege bekommen echte Umlaute. Mischbestand ist akzeptiert.

**Verifizierung per grep:** Ein finaler `grep -rE`-Anker (siehe Acceptance Criteria) faengt Reststellen. Pattern-Liste deckt die haeufigsten Wortstaemme ab; bei seltenen Begriffen Stichprobe per Auge.

## Verification

**Commands:**
- `pytest -x` -- expected: alle Tests gruen
- `grep -rEn '(verfuegbar|Mietvertraege|Gebaeude|Faelle|hinzufuegen|ausfuehren|uebertragen|waehlen|ausgewaehlte|moeglich|gebraeuchlich|Eigentuemer|Glaeubiger|erklaerend|Flaechenliste|Uebersicht|zusammenfuegen|Saetze)' app/ tests/ --include='*.py' --include='*.html' | grep -v '_etv_' | grep -v 'etv_signature_list' | grep -v 'facilioo_'` -- expected: leer (alle False-Positives bereits ausgefiltert)
- `docker compose up --build` + manueller Smoke-Klick `/cases/`, `/objects/`, `/admin/audit-log`, `/workflows/sepa_mandate` -- expected: keine ASCII-Umlaute im sichtbaren UI

**Manual checks:**
- Re-Live-Test SEPA: ein Mandat (Floegel HAM61 oder Tilker GVE1) hochladen → Extraktion liefert Felder strukturell unveraendert.
- Re-Live-Test Mietverwaltung: einen bestehenden Fall oeffnen → Felder weiterhin korrekt zugeordnet, keine 500er.
- Re-Live-Test Contact-Create: Sub-Workflow aufrufen, Dummy-Kontakt anlegen → Two-Phase-Flow unveraendert.

## Suggested Review Order

**System-Prompts (höchstes Risiko — beeinflusst LLM-Output)**

- Default-Prompt + RÜCKFRAGEN-MODUS-Appendix: Description-Text auf Umlaute, JSON-Field-Keys (`weg_kuerzel`, `creditor_id`) bleiben ASCII.
  [`claude.py:37`](../../app/services/claude.py#L37)

- 5 Doc-Typ-Prompts + CLASSIFY_PROMPT für Mietverwaltung: gleiches Muster, Pydantic-Schemas unangetastet.
  [`mietverwaltung.py:276`](../../app/services/mietverwaltung.py#L276)

- Lernnotizen-Header (an LLM angehängt): „berücksichtige diese" — Edge-Case-Hunter-Patch.
  [`claude.py:247`](../../app/services/claude.py#L247)

**Field-Labels & Audit-Strings (User-facing Strings im Backend)**

- `_EXTRACTION_FIELD_LABELS` von HTML-Entities (`&uuml;`) auf direkte Umlaute — sichtbar im Inline-Edit-Pfad.
  [`documents.py:54`](../../app/routers/documents.py#L54)

- Audit-`details_json` mit echtem Umlaut, `action`-Key bleibt ASCII.
  [`documents.py:403`](../../app/routers/documents.py#L403)

- Permission-Labels für `/admin/users` (Rolle-Edit-Dialog).
  [`permissions.py:47`](../../app/permissions.py#L47)

- Default-Workflow-Beschreibungen (Migration für existierende DB-Rows steht in `deferred-work.md`).
  [`main.py:67`](../../app/main.py#L67)

**Router-Sweep (HTTPException-Detail + Banner)**

- IBAN-Validierungs-Fehler an User: schwifty's „Invalid" wird vom Test-Pattern gefangen.
  [`impower.py:616`](../../app/services/impower.py#L616)

- Encryption-Key-Fallback-Message + Audit-Detail.
  [`objects.py:342`](../../app/routers/objects.py#L342)

- DOC_TYPES Display-Label „Mieterliste / Flächenliste" (URL-Slug `mieterliste` bleibt ASCII).
  [`cases.py:55`](../../app/routers/cases.py#L55)

**Templates (Sichtbares UI)**

- Größte Datei mit ~25 Treffern: Mietverträge, Gebäude, Fälle, hinzufügen, ausführen, übertragen.
  [`case_detail.html:531`](../../app/templates/case_detail.html#L531)

- Tile-Beschreibungen + Öffnen-Buttons auf Dashboard.
  [`index.html:47`](../../app/templates/index.html#L47)

- HTML-Entities (`Eigent&uuml;mer`, `Vertr&auml;ge`) auf direkte Umlaute.
  [`_extraction_block.html:31`](../../app/templates/_extraction_block.html#L31)

- Sync-Status-Übersicht mit vielen Status-Badges (Läuft/Übersprungen/Läufe).
  [`admin/sync_status.html:6`](../../app/templates/admin/sync_status.html#L6)

**Tests (parallel zu Source-Patches)**

- Re-Asserts auf gerenderte Strings.
  [`test_finanzen_routes_smoke.py:174`](../../tests/test_finanzen_routes_smoke.py#L174)

- RÜCKFRAGEN-MODUS und Empty-State.
  [`test_claude_unit.py:258`](../../tests/test_claude_unit.py#L258)

- Sync-Status Empty-State.
  [`test_admin_sync_status_routes.py:99`](../../tests/test_admin_sync_status_routes.py#L99)
