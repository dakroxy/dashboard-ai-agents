---
title: 'SEPA-Lastschrift: Inline-Edit für Extraktionsfelder'
type: 'feature'
created: '2026-04-27'
status: 'done'
baseline_commit: '6c8258026953314babc85c917f21678d47812494'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Korrekturen an der KI-Extraktion eines SEPA-Lastschriftmandats laufen heute nur über den Chat, der das gesamte JSON zurückwirft. Für Tipp-Korrekturen schwergewichtig, und Sonnet verstümmelt gelegentlich Ziffernfolgen (Backlog 5+7).

**Approach:** Click-to-Edit pro Extraktionsfeld auf der Document-Detail-Seite, analog zum Technik-/Mietverwaltungs-Pattern. Pen-Icon → Inline-Form → Save → ganze Extraktion-Box re-rendert, automatisches Re-Match wie nach Chat-Korrektur.

## Boundaries & Constraints

**Always:**
- Save legt neue `Extraction`-Row an (`model="manual"`, `prompt_version=f"{prev}-manual"`, `status="ok"`). Schema identisch zur LLM-Row.
- IBAN: `_normalize_iban()` + `schwifty.IBAN(v).validate()`. Ungültig → 422 mit Inline-Fehler.
- `sepa_date`: `date.fromisoformat()`. Ungültig → 422.
- Status-Reset analog Chat (`documents.py:675-678`): aus `{matched, needs_review, error, written, already_present}` → `extracted`, `matching_result`/`impower_result` cleared. Re-Match per `BackgroundTasks`.
- Audit `action="extraction_field_updated"`, `details={field, old, new}`. In `KNOWN_AUDIT_ACTIONS` registrieren.
- Edit nur in Status `{extracted, needs_review, matched, error}`. Permission `documents:approve` (gleich wie Approve).

**Never:**
- Keine Bulk-/Multi-Field-Form. `notes`/`confidence`/`model`/Matching-/Write-Result nicht editierbar. Kein neuer Permission-Key, keine Schema-Migration.

## I/O & Edge-Case Matrix

| Szenario | Input / State | Verhalten | Fehlerpfad |
|----------|---------------|-----------|------------|
| IBAN happy | gültig, Status `needs_review` | neue Row, Status → `extracted`, BG-Re-Match, Block-Swap | — |
| IBAN mit ZWSP | `"DE25​1933..."` (U+200B) | NFKC normalisiert, schwifty OK | — |
| IBAN ungültig | `"DE25XYZ"` | — | 422, `form_error="Ungültige IBAN"` |
| `sepa_date` kaputt | `"04.05.26"` | — | 422, `form_error="Datum YYYY-MM-DD"` |
| Text-Feld leer | `weg_name=""` | JSON-Wert → `null` | — |
| Status `writing` | beliebig | — | 400 |
| Field nicht in Whitelist | `field=confidence` | — | 400 |

</frozen-after-approval>

## Code Map

- `app/services/claude.py:195` — `MandateExtraction` (Field-Keys-Whitelist)
- `app/services/impower.py:526` — `_normalize_iban()` (wiederverwenden)
- `app/routers/documents.py:95,519,553,660-678` — `_run_matching`, `_load_doc_for_user`, `approve_document` (Permission-Pattern), Chat-Status-Reset (1:1 wiederverwenden)
- `app/templates/_extraction_block.html` — Felder-Loop Z. 53-80 ersetzen
- `app/templates/_obj_technik_field_view.html` / `_edit.html` — UX-Vorbild
- `app/services/audit.py` — `audit()`, `KNOWN_AUDIT_ACTIONS`

## Tasks & Acceptance

**Execution:**

- [x] `app/services/document_field_edit.py` -- `update_extraction_field(db, doc, field, value_raw, user, request) -> Extraction`. Whitelist `EDITABLE_FIELDS` (10 Keys). IBAN/Date-Validierung. Kopiert `latest.extracted`, mutiert ein Feld (leerer String → `None`), legt neue Row an, Status auf `matching` (siehe Spec Change Log), Audit-Row. `FieldValidationError(422)` bei Validierung. Explizites `created_at=datetime.now(timezone.utc)` für deterministisches `ORDER BY` in SQLite-Tests.
- [x] `app/services/audit.py` -- `KNOWN_AUDIT_ACTIONS` += `"extraction_field_updated"`.
- [x] `app/routers/documents.py` -- Drei Routen `extraction_field_edit_form` (GET edit), `extraction_field_view_fragment` (GET view), `extraction_field_save` (POST). POST ruft Service, kickt `BackgroundTasks(_run_matching)`, returnt `_extraction_block.html`. Bei 422: Edit-Partial mit `form_error`. Gates: `documents:approve` (403), Status-Whitelist (400). `_chat_response.html` und `document_status_fragment` nehmen jetzt `user` in den Kontext (für `editable`-Logik).
- [x] `app/templates/_extraction_field_view.html` -- Cell `<dd id="extraction-cell-{key}">` als Grid-Row, Wert + Pen-Icon (`hx-get=".../edit?field=..."`) wenn `editable`. IBAN via `iban_format`. (Per-Feld-„manuell"-Pill: bewusst entfallen — globale Anzeige bleibt im Block-Footer via `extraction.model`.)
- [x] `app/templates/_extraction_field_edit.html` -- Form, Input (`type="date"` für `sepa_date`, sonst `text`), Save (Target `#extraction-block`) + Abbrechen (Target `#extraction-cell-{key}`). `form_error` rot unter Input.
- [x] `app/templates/_extraction_block.html` -- Felder-Loop Z. 53-80 durch View-Partial-Include ersetzt. `editable = doc.status in {extracted,needs_review,matched,error} and has_permission(user, "documents:approve")`. Hinweistext bei `needs_review` ergänzt um „Stift-Symbol".
- [x] `tests/test_documents_extraction_edit.py` -- 18 Tests in 4 Klassen (Happy / Validation / Gates / EditFormGet). Auto-Fixture mockt `_run_matching`. Coverage: Happy Text + IBAN + IBAN-ZWSP + Empty-Value + Audit + No-Op + Triple-Save + Invalid-IBAN-422 + Invalid-Date-422 + Status-Writing-400 + Field-Whitelist-400 + Permission-403 + GET-edit-form (value/text/date/invalid-field) + GET-view-fragment.

**Acceptance Criteria:**

- Given Status `needs_review`, when Pen-Icon → Wert ändern → Save, then existiert eine neue `Extraction`-Row mit `model="manual"`, `doc.status="matching"` (BG-Re-Match-Task läuft), und ein Audit `action="extraction_field_updated"` mit `details={field, old, new}`.
- Given ungültige IBAN, when Save, then HTTP 200 mit Edit-Form-Re-Render und Inline-Fehler (HTMX 2.x default-config swappt 4xx nicht), keine neue Row, kein Audit.
- Given Status `writing`/`approved`, when `POST /extraction/field`, then 400; UI rendert keinen Pen-Icon.
- Given User ohne `documents:approve`, when Save, then 403.
- Given drei Saves, then drei Extraction-Rows + drei Audit-Einträge (keine Coalescenz), `prompt_version` enthält `-manual` genau einmal.
- Given Save mit unverändertem Wert (No-Op), then keine neue Row, kein Audit, kein Re-Match-Trigger.

## Spec Change Log

- **2026-04-27 — Status-Reset auf `matching` statt `extracted`** — Spec-Always-Boundary sah analog zum Chat ein Reset auf `extracted` vor; in der Save-Route würde damit aber kein HTMX-Polling triggern (Polling-Statuses umfassen `matching`, nicht `extracted`), und der User würde 0–2s lang die Approve-UI ohne Re-Match-Spinner sehen. Service setzt jetzt `doc.status="matching"` direkt; der `_run_matching`-BG-Task setzt das anschließend auf `matched`/`needs_review`. Funktional identisch, UX deutlich klarer.
- **2026-04-27 — Per-Feld-„manuell"-Pill entfallen** — Spec-Task sah Pill via `manual = (extraction.model == "manual")` vor; das wäre semantisch irreführend, weil eine `manual`-Row 9 Felder unverändert von der vorherigen Row erbt und nur eines tatsächlich manuell editiert wurde. Korrektes Per-Feld-Tracking bräuchte einen Audit-Log-Query pro Render (N+1-Risiko) oder ein neues Schema-Feld. Stattdessen rendert der bestehende Block-Footer das Modell (`extraction.model = "manual"`), was den Status zumindest grob anzeigt. Per-Feld-Pill bleibt für eine spätere Iteration offen.
- **2026-04-27 — Validierungsfehler returnen HTTP 200 statt 422** (Code-Review-Befund von „Edge Case Hunter"). HTMX 2.x default `responseHandling` swappt **keine** 4xx-Antworten in den DOM; ein 422 mit Edit-Form-Re-Render würde silently verschluckt und der User sähe keinen Inline-Fehler. Server returnt jetzt 200 mit dem Edit-Form-Partial inkl. `form_error`. Service-Schicht wirft weiterhin `FieldValidationError(422)` (semantisch korrekt); die Route wandelt das in 200 um. AC entsprechend umformuliert.
- **2026-04-27 — Patch-Pass nach Code-Review (3 Subagents)**:
  - `_validate_iban`: spezifische Exception-Klassen statt `bare except`; non-empty Input mit nur Sonderzeichen → 422 statt silent-clear; raw schwifty-Detail wird nicht mehr in die User-Meldung übernommen (Wording „Ungültige IBAN").
  - `_validate_sepa_date`: Wording auf „Datum YYYY-MM-DD" gekürzt (Spec-konform).
  - Service: Workflow-Key-Check (`workflow.key == "sepa_mandate"`) gegen Cross-Workflow-Kontamination. Reihenfolge umgestellt: Latest-Extraction-Check VOR Wert-Validierung. `prompt_version` einmaliges `-manual`-Suffix (statt compounding). `copy.deepcopy` statt Shallow-Copy. Service returnt `None` bei No-Op; Route triggert dann KEINEN BG-Re-Match. NUL/Control-Chars werden gestrippt vor Persistierung.
  - GET `/extraction/edit?field=`: 400 wenn keine Extraction vorhanden (statt leerer Form mit Späterem-Save-Crash).
  - View-Partial: Pen-Icon vom Unicode-Glyph `✏` auf inline SVG umgestellt (CLAUDE.md: keine Emojis), `aria-label` ergänzt.
  - Tests: try/finally-Cleanup für `dependency_overrides` im 403-Test; Triple-Save-Loop simuliert den BG-Re-Match-Effekt explizit; neuer Test für GET-edit-form ohne Extraktion; neuer Test für IBAN-only-Garbage-Chars.

## Design Notes

- **Neue Row pro Save** (statt In-Place): symmetrisch zum Chat-Pfad (`documents.py:660-678`), Geschichte trivial nachvollziehbar, kein Display-Sonderfall.
- **Whole-Block-Swap auf Save** (Cell-Swap nur auf Cancel): Status-Pill und Matching-Bereich müssen mitziehen sobald matching-relevant editiert; HTMX-Polling zeigt den Re-Match-Verlauf automatisch.

## Verification

- `docker compose exec app pytest -x tests/test_documents_extraction_edit.py` — alle grün
- `docker compose exec app pytest -x` — keine Regression (Chat, Approve, Polling, Doc-Liste)
- Manuell: `needs_review`-Doc öffnen, je 1 Edit für Text/IBAN/Datum (gültig + ungültig). Erwartet: Block-Swap, Polling-Animation, „manuell"-Pill, neuer Matching-Status. Auf `written`: keine Pen-Icons.

## Suggested Review Order

**Service-Logik (Validation + State-Mutation)**

- Entry-Point: zentrale Logik des Inline-Edits, alle Validierungen + Status-Transition kommen hier zusammen.
  [`document_field_edit.py:84`](../../app/services/document_field_edit.py#L84)

- IBAN-Validierungs-Edge-Cases: NFKC-Normalize + schwifty + non-empty-but-empty-after-strip Edge-Case.
  [`document_field_edit.py:60`](../../app/services/document_field_edit.py#L60)

- Cross-Workflow-Schutz: nur `sepa_mandate`-Workflow darf hier rein, sonst kontaminiert der SEPA-Edit ein Mietverwaltungs-JSON.
  [`document_field_edit.py:113`](../../app/services/document_field_edit.py#L113)

**Routing + HTMX-Quirk**

- POST Save: HTMX 2.x default swappt 4xx nicht — daher 200 mit Edit-Form-Re-Render bei `FieldValidationError`.
  [`documents.py:903`](../../app/routers/documents.py#L903)

- Re-Match-Trigger nur bei tatsächlicher Änderung (No-Op skippt BG-Task).
  [`documents.py:935`](../../app/routers/documents.py#L935)

- GET edit-form blockt früh wenn keine Extraction da ist (statt späterer Save-Crash).
  [`documents.py:826`](../../app/routers/documents.py#L826)

**UI-Templates**

- View-Cell mit Pen-Icon (SVG, kein Emoji); Edit-Mode nur sichtbar wenn `editable`.
  [`_extraction_field_view.html:23`](../../app/templates/_extraction_field_view.html#L23)

- Inline-Edit-Form: Save targets ganzen Block (Status-Pill muss mit), Cancel targets nur die Cell.
  [`_extraction_field_edit.html:11`](../../app/templates/_extraction_field_edit.html#L11)

- Block-Update: Felder-Loop ruft jetzt das View-Partial; `editable` einmal pro Render berechnet.
  [`_extraction_block.html:55`](../../app/templates/_extraction_block.html#L55)

**Audit + Tests**

- Audit-Action registriert.
  [`audit.py:55`](../../app/services/audit.py#L55)

- 20 Tests in 4 Klassen — Happy/Validation/Gates/EditFormGet, mit gemocktem `_run_matching` für Determinismus.
  [`test_documents_extraction_edit.py:1`](../../tests/test_documents_extraction_edit.py#L1)
