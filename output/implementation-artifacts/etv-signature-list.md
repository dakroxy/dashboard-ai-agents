---
title: 'ETV-Unterschriftenliste (Modul `etv_signature_list`)'
type: 'feature'
created: '2026-04-29'
status: 'done'
baseline_commit: '4ee7d15b01d9c00d7b7183c1b8b30c5f6284bae0'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Vor jeder ETV (Eigentümerversammlung) wird heute manuell eine Unterschriftenliste mit Eigentümern, Einheiten, MEA und Vollmacht-Spalte gepflegt — die Daten leben in Facilioo, der Druck ist Handarbeit.

**Approach:** Neues Plattform-Modul `etv_signature_list` (drittes Workflow-Plug-in nach `sepa_mandate` und `mietverwaltung_setup`). User wählt eine Conference aus einem Dropdown, das Modul lädt 6 Facilioo-Endpunkte parallel und rendert ein druckfertiges A4-Querformat-PDF via WeasyPrint. Kein Claude, keine Extraktion, kein Persistieren — reiner Read-/Render-Pfad.

## Boundaries & Constraints

**Always:**
- Sidebar-/Tile-Sichtbarkeit nur für User mit `RESOURCE_TYPE_WORKFLOW`-Zugriff auf den `etv_signature_list`-Workflow (gleiches Gating wie SEPA/Mietverwaltung).
- Facilioo-Token kommt ausschließlich aus `settings.facilioo_bearer_token` (1Password → `.env`); kein Hardcoding, keine Logs mit Token.
- HTTP-Errors → user-friendly Meldung, niemals 500er bis ins Browser-Frame.
- PDF-Template ist **inline-CSS, kein Tailwind**: WeasyPrint kann Tailwind-Utility-Classes nicht zuverlässig rendern.
- Audit-Eintrag bei jedem PDF-Druck (`event="etv_signature_list_generated"`, `details={conference_id, conference_title}`).
- Für die Vollmacht-Spalte zählt ausschließlich Endpunkt 6 (`/conferences/{id}/mandates`) — Owner ist „vorgekreuzt", wenn er als `propertyOwnerId` in einem Mandat-Eintrag vorkommt.

**Ask First:**
- Wenn die Live-Smoke-Tests gegen ETV id=6944 (PLS22 Hildesheim) Anomalien zeigen (z. B. < 8 Voting-Group-Zeilen, falsche Vollmacht-Anzahl, Zellen-Mapping kaputt) → HALT vor weiteren Anpassungen.
- WeasyPrint-System-Libs (`libpango`, `libcairo`) fehlen im Dockerfile — Ergänzung erfolgt im Implement-Schritt; falls der Container-Build dadurch deutlich langsamer/größer wird, kurze Rückfrage zur Alternative (z. B. ReportLab) bevor wir das durchziehen.

**Never:**
- Keine Persistierung der gezogenen Conference-/Voting-Group-Daten in der eigenen DB. Single-Pass: laden, rendern, ausliefern.
- Kein Token-Refresh-Mechanismus (JWT ist 8 Monate gültig, Rotation manuell).
- Kein editierbarer Vor-PDF-Screen, kein Two-Phase-Flow, keine Verknüpfung mit Protokoll-Generierung.
- Kein `GET /conferences/{id}/signees` — irreführender Name, das sind Funktionsträger, nicht Eigentümer.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | User wählt Conference, klickt "PDF erzeugen" | Browser lädt PDF (Content-Disposition: attachment, Filename `etv-{date}-{property-slug}.pdf`); Audit-Eintrag geschrieben | N/A |
| Facilioo nicht erreichbar (Network/5xx nach Retries) | `httpx.TransportError` o. 5xx persistent | Auswahl-Screen mit roter Banner-Meldung "Facilioo aktuell nicht erreichbar — bitte später erneut versuchen" | HTTP 200 mit Fehler-Banner, **kein 500er** |
| Unbekannte Conference-ID (404) | User submitted ungültige ID | Auswahl-Screen mit Fehler-Banner, Dropdown bleibt befüllt | HTTP 200, kein 500er |
| Conference ohne Voting-Groups | Endpunkt 4 liefert leere Liste | PDF mit Header + leerer Tabelle + Hinweiszeile "Keine Stimmgruppen hinterlegt" | N/A |
| User ohne Workflow-Zugriff | `can_access_resource` = false | HTTP 403 (Pattern wie `contacts.py`) | N/A |
| Voting-Group hat mehrere Parties | `parties[]` mit n Einträgen | Eine Tabellenzeile, Eigentümer-Namen komma-getrennt | N/A |

</frozen-after-approval>

## Code Map

- `app/config.py` — Settings-Klasse: zwei neue Felder `facilioo_base_url` (Default `https://api.facilioo.de`) + `facilioo_bearer_token` (Default `""`).
- `app/services/facilioo_client.py` — **NEU**, schmaler Read-Client analog `services/impower.py` (httpx.AsyncClient, 30 s Timeout, 5xx-Retry mit `(2,5,15)` s Backoff, Bearer-Header, `_sanitize_error`); 6 Methoden + eine Konferenz-`fetch_conference_signature_payload(conf_id)` als asyncio.gather-Aggregator.
- `app/main.py` — `_DEFAULT_WORKFLOWS`-Tupel um `etv_signature_list` (model="", system_prompt="", chat_model=DEFAULT_CHAT_MODEL für NOT-NULL-Constraint) erweitern.
- `app/routers/etv_signature_list.py` — **NEU**, Router `prefix="/workflows/etv-signature-list"`: `GET /` (Auswahl-Screen), `POST /generate` (Aggregator + WeasyPrint + StreamingResponse).
- `app/main.py` — Router-Registrierung im `app.include_router(...)`-Block.
- `app/templates/etv_signature_list_select.html` — **NEU**, Tailwind-Auswahlscreen mit Dropdown + (optional) State-Filter + "PDF erzeugen"-Button + Fehler-Banner-Slot.
- `app/templates/etv_signature_list_pdf.html` — **NEU**, inline-CSS, `@page { size: A4 landscape; margin: 12mm; }`, Header (WEG-Name, Datum/Uhrzeit, Ort/Raum), Tabelle (Eigentümer | Einheit | MEA | Unterschrift | Vollmacht ☐/☑).
- `app/templates/index.html` — Tile-Block für `etv_signature_list` (z. B. amber→orange Gradient für visuelle Abgrenzung) ergänzen, Link `/workflows/etv-signature-list`.
- `pyproject.toml` — Dependency `weasyprint>=63`.
- `Dockerfile` — `apt-get install` um `libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-dejavu-core` ergänzen.
- `tests/test_etv_signature_list.py` — **NEU**, TestClient-Tests mit gemocktem `facilioo_client`-Module (siehe `project_testing_strategy`-Memory).

## Tasks & Acceptance

**Execution:**
- [x] `app/config.py` -- `facilioo_base_url` + `facilioo_bearer_token` Felder ergänzen -- App muss die neuen Env-Vars laden können.
- [x] `app/services/facilioo_client.py` -- Client-Modul erstellen mit den 6 in der Intent genannten Methoden + `fetch_conference_signature_payload(conf_id)` als asyncio.gather-Aggregator (lädt Endpunkte 2,3,4,6 parallel; danach pro voting-Group-Share parallel Endpunkt 5) -- Single-Source-of-Truth für alle Facilioo-GETs.
- [x] `app/main.py` -- `_DEFAULT_WORKFLOWS` um `etv_signature_list` erweitern (model="", system_prompt="", chat_model=DEFAULT_CHAT_MODEL), Router includen -- Sidebar-Tile + Resource-Access-Seed greifen.
- [x] `app/routers/etv_signature_list.py` -- Router mit `GET /` (Workflow-Gate via `can_access_resource`, Conferences laden, Template rendern) und `POST /generate` (conference_id aus Form, Aggregator-Call, WeasyPrint→PDF, Audit, StreamingResponse) -- erfüllt AC1+AC2+AC4.
- [x] `app/templates/etv_signature_list_select.html` -- Dropdown mit Conferences (sortiert nach `date` desc, Format `YYYY-MM-DD HH:MM — title`), Submit-Button, Banner-Slot -- AC2.
- [x] `app/templates/etv_signature_list_pdf.html` -- Print-CSS, Header-Block (WEG-Name aus `property.name`, Datum/Uhrzeit aus `conference.date`, Ort/Raum aus `conference.location`/`room`), Tabelle eine Zeile pro Voting-Group, Vollmacht-Symbol ☑ wenn Owner in `mandates[].propertyOwnerId` vorkommt, sonst ☐ -- AC3+AC5.
- [x] `app/templates/index.html` -- Tile für `etv_signature_list` einfügen (Gradient amber→orange, Icon Versammlung/Stimme), Link `/workflows/etv-signature-list` -- AC1.
- [x] `pyproject.toml` -- `weasyprint>=63` ergänzen -- Build-Voraussetzung.
- [x] `Dockerfile` -- WeasyPrint-System-Libs installieren -- Render läuft im Container.
- [x] `tests/test_etv_signature_list.py` -- Edge-Case-Matrix abdecken: Happy-Path (PDF-Bytes start with `%PDF-`), 5xx-after-retry → Banner, ungültige conference_id, leere voting-groups, multi-party-row, 403 ohne Workflow-Access -- TestClient + Mocks (kein Live-Call).

**Acceptance Criteria:**
- Given ein User mit Workflow-Zugriff, when er auf der Startseite ist, then sieht er die Tile "ETV-Unterschriftenliste" und einen Sidebar-Eintrag mit Link auf `/workflows/etv-signature-list`.
- Given Facilioo ist erreichbar, when der Auswahl-Screen geladen wird, then enthält das Dropdown ~29 Conferences mit Datum + Titel, sortiert neueste zuerst.
- Given der User wählt eine Conference und submitted, when der Server alle 6 Endpunkte erfolgreich lädt, then startet im Browser ein PDF-Download mit Filename `etv-{YYYY-MM-DD}-{property-slug}.pdf` innerhalb von ≤ 5 s im Happy-Path.
- Given die Live-Verifikation an `conference_id=6944` (PLS22 Hildesheim), when das PDF erzeugt wird, then enthält es den WEG-Namen aus `property.name` im Header, exakt 8 Tabellenzeilen (eine pro Voting-Group) und exakt 3 vorgekreuzte Vollmacht-Boxen.
- Given Facilioo ist nicht erreichbar oder antwortet persistent mit 5xx/Network-Error, when der User submitted, then bleibt der Auswahl-Screen sichtbar mit roter Fehler-Meldung und HTTP-Status 200, **kein 500er**.
- Given ein PDF wurde erfolgreich erzeugt, when ich das Audit-Log aufrufe, then existiert ein Eintrag `event="etv_signature_list_generated"` mit `conference_id` und `conference_title` in `details`.

### Review Findings

_Code review 2026-04-29 (3 layers: blind / edge-case / acceptance auditor) — diff `4ee7d15..f655007` narrowed to 13 ETV-Pfade._

**Decision-needed (resolved):**

- [x] [Review][Decision→Defer] Phase-2 gather killed PDF on single voting-group failure [`app/services/facilioo_client.py:279`] — **DEFER** (Spec AC4 verlangt exakte 8 Zeilen; halb-vollstaendige Unterschriftenliste ist juristisch schlechter als Re-Try). Bei UX-Feedback re-evaluieren.
- [x] [Review][Decision→Patch] Mandate-Aequivalenz `party.id == propertyOwnerId` ohne Code-Doku [`app/routers/etv_signature_list.py:139-141`] — **PATCH** als Code-Comment (Verweis auf Live-Smoke PLS22, kein Logik-Change).

**Patch (unbestaetigt):**

- [ ] [Review][Patch] WeasyPrint render exception → 500 statt Banner (verletzt "Always: niemals 500er") [`app/routers/etv_signature_list.py:280`]
- [ ] [Review][Patch] `_load_workflow_or_403` wirft 500 bei fehlendem Workflow-Row (verletzt "Always: niemals 500er") [`app/routers/etv_signature_list.py:46-50`]
- [ ] [Review][Patch] `audit(entity_id=uuid.uuid4())` schreibt Random-UUID — Conference hat keine lokale Entity, also `entity_id=None` setzen [`app/routers/etv_signature_list.py:287`]
- [ ] [Review][Patch] `_get_all_paged` Endlosschleife wenn `totalPages` None UND `last` falsy UND content immer voll — Safety-Cap `if page > 500: break` einziehen [`app/services/facilioo_client.py:109-130`]
- [ ] [Review][Patch] `list_conferences_with_properties` schluckt FaciliooError stille (`gather(return_exceptions=True)` ohne Logging) [`app/services/facilioo_client.py:163-176`]
- [ ] [Review][Patch] `_parse_conference_date` mischt naive/aware datetimes — `strftime("%H:%M")` rendert UTC vs Local inkonsistent (Spec AC4: "PLS22 18:30") [`app/routers/etv_signature_list.py:59-68`]
- [ ] [Review][Patch] `_sort_key` sortiert auf raw ISO-String — Mixed Offsets (`+02:00` vs `Z`) ergeben falsche Reihenfolge [`app/routers/etv_signature_list.py:186-188`]
- [ ] [Review][Patch] `KNOWN_AUDIT_ACTIONS` fehlt `etv_signature_list_generated` (Konvention aus `audit.py:30`) [`app/services/audit.py:30`]
- [ ] [Review][Patch] Mandate-Aequivalenz `party.id == propertyOwnerId` per Code-Comment dokumentieren [`app/routers/etv_signature_list.py:139-141`]

**Defer (pre-existing oder nicht akut, in deferred-work.md):**

- [x] [Review][Defer] Phase-1 gather ohne Partial-Degradation [`app/services/facilioo_client.py:251`] — deferred, Header-Endpunkte sind alle essential, Fail-Loud verteidigbar
- [x] [Review][Defer] `int(total_pages)` ohne try/except [`app/services/facilioo_client.py:123`] — deferred, low likelihood (Facilioo liefert immer numerisch)
- [x] [Review][Defer] Audit committed vor StreamingResponse zugestellt [`app/routers/etv_signature_list.py:296`] — deferred, semantisch ist "Daten geladen" der Audit-Anker, nicht "Bytes empfangen"
- [x] [Review][Defer] Content-Disposition filename nicht RFC-5987 [`app/routers/etv_signature_list.py:304`] — deferred, `_slug` strippt zu ASCII, Injection praktisch unmoeglich
- [x] [Review][Defer] `sidebar_workflows` oeffnet eigenes `SessionLocal()` pro Render [`app/templating.py:53`] — deferred, architektonische Entscheidung mit Code-Begruendung
- [x] [Review][Defer] Sidebar-Active prefix-startswith collision-prone [`app/templates/base.html:696-703`] — deferred, aktuell keine kollidierenden Pfade (`/contacts/new` vs nichts)
- [x] [Review][Defer] Test `test_generate_returns_403_without_workflow_access` koennte 401/422 statt 403 schlucken [`tests/test_etv_signature_list.py:1729`] — deferred, Test-Robustheit
- [x] [Review][Defer] WeasyPrint-Monkeypatch fragil bei Modul-Import-Refactor [`tests/test_etv_signature_list.py:1685-1696`] — deferred, Test-Robustheit
- [x] [Review][Defer] Non-ASCII-WEG-Namen kollidieren auf Filename-Fallback [`app/routers/etv_signature_list.py:90-96`] — deferred, alle DBS-WEGs sind deutsch ASCII-fold-bar
- [x] [Review][Defer] `list_conferences_with_properties` fanout ohne Semaphore [`app/services/facilioo_client.py:158-163`] — deferred, ~30 Conferences im Pool
- [x] [Review][Defer] Test-Coverage 5xx vs 404 zusammengelegt — deferred, gleicher Codepfad
- [x] [Review][Defer] Phase-2 gather killed PDF on single VG failure [`app/services/facilioo_client.py:279`] — deferred, Spec AC4 verlangt exakte 8 Zeilen → Fail-loud ist Spec-konform; bei UX-Feedback re-evaluieren

**Spec-Hygiene-Notiz:** `baseline_commit: 4ee7d15` zeigt auf "Story 3.1: Objekt-Liste mit Sortierung & Filter". Zwischen baseline und HEAD liegen 5 unrelated Commits (Pflegegrad 3.2/3.3, Redeploy, Sidebar-Wording-Refactor). Bei naechstem Spec-Update den baseline auf den letzten Commit vor `35492a5 ETV-Unterschriftenliste: neues Workflow-Modul` setzen.

## Spec Change Log

- **2026-04-29 — Code-Review-Patches**: 9 Findings aus dem Multi-Layer-Review (blind / edge-case / acceptance auditor) gefixt. Highlights: WeasyPrint-Render-Exception greift jetzt den Banner-Pfad (Spec-Boundary "kein 500er"), `_load_workflow_or_403` ebenso, `audit(entity_id=...)` nicht mehr garbage-UUID, `_get_all_paged` hat Safety-Cap gegen Endlosschleife, `_parse_conference_date` gibt jetzt deterministisch Europe/Berlin (AC4 18:30 stabil), `_sort_key` sortiert auf parsed datetime, `KNOWN_AUDIT_ACTIONS` registriert `etv_signature_list_generated`, Mandate-Aequivalenz-Annahme dokumentiert. Phase-2-gather-Fail-Loud bewusst deferred (Spec AC4 verlangt 8 Zeilen). Alle 795 Tests gruen. Status: `done`.
- **2026-04-29 — Live-Bug-Fixes (Post-Implement)**:
  - Facilioo paginiert **1-indexed**: `_get_all_paged` startete bei `pageNumber=0`, was Facilioo mit HTTP 400 quittiert. Folge: Auswahl-Screen zeigte „Facilioo nicht erreichbar"-Banner trotz funktionierendem Token. Fix in `app/services/facilioo_client.py` (Loop ab `page=1`, Abbruch bei `page >= totalPages`). Regression-Tests `test_list_conferences_starts_at_page_one` + `test_list_conferences_walks_multiple_pages`.
  - Sidebar-Eintrag: KI-Workflows tauchen jetzt als eigene Sidebar-Sektion auf (alle aktiven Workflows mit Resource-Access). Implementiert via Jinja-Global `sidebar_workflows(user)` in `app/templating.py` + neuer Sidebar-Block in `app/templates/base.html`. Damit greift AC1 vollstaendig (Tile + Sidebar).
  - `Workflows`-Konfig-Sidebar wird nicht mehr faelschlich aktiv gehighlightet, wenn der User auf einer KI-Workflow-Seite ist (Active-Match entkoppelt via `ns.in_wf_path`).

## Design Notes

**Aggregator-Strategie** (`fetch_conference_signature_payload`):

```python
# Phase 1: Header-Endpunkte parallel (Endpunkte 2,3,4,6).
conf, prop, vg_shares, mandates = await asyncio.gather(
    get_conference(conf_id),
    get_conference_property(conf_id),
    list_voting_group_shares(conf_id),
    list_mandates(conf_id),
)
# Phase 2: pro voting-Group-Share parallel Endpunkt 5.
voting_groups = await asyncio.gather(*[
    get_voting_group(s["votingGroupId"]) for s in vg_shares
])
return {"conference": conf, "property": prop, "voting_groups": [...zip mit shares...], "mandates": mandates}
```

Phase-2 ist als zweite Welle nötig, weil die `votingGroupId`-Liste erst aus Phase 1 kommt — kein Single-Shot-gather möglich.

**Workflow-Tabelle:** Bestehendes Schema (`model`, `system_prompt`, `chat_model` sind `NOT NULL`) bleibt unangetastet. Wir setzen `model=""`, `system_prompt=""`, `chat_model=DEFAULT_CHAT_MODEL` als no-op-Werte. Der ETV-Workflow erscheint dadurch zwar in `/workflows/{key}`-Edit-Views als „leerer Prompt", aber ohne Konsequenz — der Router benutzt diese Felder nicht. Vollwertiger Schema-Change wäre Overkill für ein No-Claude-Modul.

**Permission-Gate:** Nur `can_access_resource(db, user, RESOURCE_TYPE_WORKFLOW, wf.id)` — kein zusätzlicher Permission-Key wie `documents:upload` (das war in `contacts.py` Resterampe; wäre für ETV semantisch falsch).

## Verification

**Commands:**
- `docker compose up --build` -- erwartet: Container startet, App läuft, neue Tile auf `/` sichtbar, `/workflows/etv-signature-list` rendert Dropdown.
- `pytest tests/test_etv_signature_list.py -v` -- erwartet: alle Cases grün.
- `python -c "import weasyprint; print(weasyprint.__version__)"` (im Container) -- erwartet: Versionsnummer ohne ImportError.

**Manual checks (CHECKPOINT vor Live-Smoke):**
- WeasyPrint-Image-Größe + Build-Dauer prüfen — wenn Build > 5 min oder Image > 1.5 GB, kurz Rücksprache.
- Live-Smoke an `conference_id=6944`: Header zeigt "WEG PLS22 Plötzenstr. 22, 31139 Hildesheim", 8 Zeilen, 3 ☑.
