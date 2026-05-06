# Story 5.6: Code-Qualität & Refactoring

Status: done

## Story

Als Entwickler der Plattform
möchte ich alle 47 aufgelaufenen Code-Qualitäts- und Refactoring-Findings aus früheren Code-Reviews bereinigt haben,
damit die Codebasis konsistenter, wartbarer und weniger fehleranfällig ist.

## Hintergrund

Diese Story schließt 47 Deferred-Work-Einträge (#2, #20, #24, #25, #29, #30, #36, #38, #44, #45, #46, #62, #65, #66, #70, #73, #74, #85, #88, #90, #92, #93, #98, #100, #101, #102, #103, #105, #107, #108, #109, #110, #113, #114, #117, #118, #122, #123, #126, #130, #131, #132, #134, #135, #136, #144, #146) aus `output/implementation-artifacts/deferred-work.md`. Severity-Mix: 6× medium (#20, #88, #101, #108, #131, #136), Rest low. Keine Pre-Prod-Blocker. Die Story tastet 5-1/5-2/5-3/5-4/5-5 nicht an.

## Acceptance Criteria

---

### AC1 — Permission-Konstanten-Refactoring (#20, #93, #102)

**Given** Permission-Magic-Strings (`"objects:approve_ki"`, `"objects:edit"` etc.) sind in `app/routers/admin.py`, `app/templates/base.html` und weiteren Dateien hardkodiert; Waisen-Keys in `Role.permissions` werden nie bereinigt; `_ENCRYPTED_FIELDS` enthält nur `"object"`

**When** AC1 implementiert ist

**Then**:
- **#20** — `app/permissions.py` erhält ein `PermKey`-Literal-Dict oder Konstanten-Block am Dateianfang. Alle vorhandenen `PERMISSIONS`-Keys als Python-Konstanten:
  ```python
  # in app/permissions.py, direkt nach den Imports
  PERM_OBJECTS_VIEW = "objects:view"
  PERM_OBJECTS_EDIT = "objects:edit"
  PERM_OBJECTS_APPROVE_KI = "objects:approve_ki"
  PERM_OBJECTS_VIEW_CONFIDENTIAL = "objects:view_confidential"
  PERM_REGISTRIES_VIEW = "registries:view"
  PERM_REGISTRIES_EDIT = "registries:edit"
  PERM_DUE_RADAR_VIEW = "due_radar:view"
  PERM_SYNC_ADMIN = "sync:admin"
  ```
  Pattern-Suche: `grep -rn '"objects:\|"registries:\|"due_radar:\|"sync:' app/routers/ app/templates/ app/services/` — alle Funde auf die Konstanten umstellen. Templates nutzen Jinja2-Globals (bereits eingesetzt in anderen Templates), falls möglich; sonst bleibt der String-Wert im Template und nur der Router-Code nutzt die Konstanten.
- **#93** — In `app/main.py:_seed_default_roles` wird beim Merge `role.permissions = role.permissions | new_perm_set` nur hinzugefügt, nie entfernt. Nach dem Seed-Schritt: `role.permissions = {k for k in role.permissions if k in set(PERMISSIONS.keys())}` — Waisen-Keys werden beim nächsten App-Start stumm bereinigt.
- **#102** — `app/services/steckbrief_write_gate.py:_ENCRYPTED_FIELDS` erhält einen Kommentar: `# v1: nur "object"; Erweiterung auf Unit/Mieter in v1.1 wenn deren Entry-Codes verschlüsselt werden`. Kein Code-Change nötig, nur Kommentar.
- **And** Test: `test_no_permission_magic_strings` — greept `app/routers/` und `app/services/` auf hardkodierte Permission-Strings, die nicht über PERM_*-Konstanten definiert sind; analog zum Write-Gate-Boundary-Test. Template-Strings bleiben in Template-Dateien (aus Test-Scope heraus).

---

### AC2 — Score-Service Algorithmus-Qualität (#36, #38, #45, #46, #98)

**Given** `app/services/pflegegrad.py` hat instabile Provenance-Tie-Breaks, redundantes Naming und ungesicherte Semantik für `0`-Werte

**When** AC2 implementiert ist

**Then**:
- **#46** — `_ALL_SCALAR` in `pflegegrad.py` auf `_ALL_SCALAR_FIELDS` umbenennen (Konstante + alle 3–4 Verwendungen im gleichen File). `replace_all`-Edit, keine Logikänderung.
- **#38** — `_latest_provenance(...)` in `pflegegrad.py` (`order_by(FieldProvenance.created_at.desc())`): zweiten Tiebreaker ergänzen: `order_by(FieldProvenance.created_at.desc(), FieldProvenance.id.desc())`. Identischer Fix in `app/services/steckbrief_write_gate.py:_latest_provenance` (beide Vorkommen suchen via `grep -n "_latest_provenance\|order_by.*created_at.desc" app/services/`).
- **#98** — Kommentar in `steckbrief_write_gate.py` beim Tie-Break-Block: `# Tiebreaker via created_at+id statt uuid4, da uuid4-DESC nicht monoton ist`. (Falls #38 denselben Ort adressiert, sind beide zusammen in einem Fix erledigt.)
- **#36** — `pflegegrad_score()` → `weakest_fields`-Sammlung nach Score-Beitrag sortieren (höchster Verlust zuerst) und deduplizieren. Typische Dedup-Zeile: `seen = set(); weakest_fields = [f for f in weakest_fields if not (f in seen or seen.add(f))]`. Sortierung: `sorted(set(weakest_fields), key=lambda f: field_weight(f), reverse=True)`. Falls kein `field_weight()`-Helper existiert, reicht `sorted(set(...))` alphabetisch als First-Pass.
- **#45** — `pflegegrad.py::_scalar_effective` (oder Äquivalent für `last_known_balance`): Kommentar ergänzen: `# 0€-Saldo ist fachlich "befuellt" (kein Impower-Saldo ist None, nicht 0). is_none-Check ist korrekt.` — kein Logik-Change, nur Klarstellung im Code.
- **And** bestehende Tests in `tests/test_pflegegrad_unit.py` bleiben grün. Kein neuer Test erforderlich (Rename + Tiebreaker haben keine eigenständige Testvariante).

---

### AC3 — JSONB-Feld-Qualität: Mandate, Notizen, ReviewQueue (#44, #85, #101)

**Given** `sepa_mandate_refs`, `notes_owners`-Orphans und `proposed_value`-Roundtrip haben Qualitätslücken

**When** AC3 implementiert ist

**Then**:
- **#44** — `app/services/pflegegrad.py`: Im Block, der `sepa_mandate_refs` als "befuellt" wertet, Filter auf Falsy-Items ergänzen: `mandates = [m for m in (obj.sepa_mandate_refs or []) if m]`. Grep-Pattern: `grep -n "sepa_mandate_refs" app/services/pflegegrad.py`.
- **#85** — `app/services/steckbrief.py` oder `steckbrief_impower_mirror.py` — im Pfad, der `notes_owners` schreibt oder Eigentuemer-Listen synchronisiert: nach dem Mirror-Update ein Cleanup-Step: `orphan_keys = set(obj.notes_owners.keys()) - {str(e.id) for e in obj.eigentuemer_list}; if orphan_keys: new_owners = {k: v for k, v in obj.notes_owners.items() if k not in orphan_keys}; write_field_human(db, obj, "notes_owners", new_owners, ...)`. Alternativ: beim User-initierten Eigentuemer-Delete in `app/routers/objects.py` nach dem Delete-Commit den Cleanup ausführen. Dev-Agent wählt die einfachere Variante und dokumentiert die Entscheidung in Completion Notes.
- **#101** — `app/services/steckbrief_write_gate.py::_json_safe` und `approve_review_entry`: Typisiertes Envelope `{"__type__": "decimal", "value": str(v)}` für `Decimal`-Werte; `{"__type__": "date", "value": v.isoformat()}` für `date`. In `approve_review_entry` vor dem Write: Envelope erkennen und in nativen Python-Typ konvertieren. Kein Schema-Change nötig (JSONB speichert das Envelope als dict).
- **And** Test: `test_proposed_value_decimal_roundtrip` — schreibt `write_field_ai_proposal(..., proposed_value=Decimal("1234.56"))`, approved es via `approve_review_entry`, prüft, dass der Zielwert kein String sondern `Numeric`-kompatibel ist (kein `db.commit()`-Fehler).

---

### AC4 — Due-Radar & Registry-Qualität (#62, #65, #70, #73, #74)

**Given** Due-Radar, Versicherer-Registry und Wartungs-Spec haben kleinere Qualitätslücken

**When** AC4 implementiert ist

**Then**:
- **#73** — `app/services/due_radar.py::list_due_within`: `order_by` erhält zweiten Tiebreaker: `order_by(DueRadarEntry.due_date.asc(), DueRadarEntry.entity_id.asc())` (oder entsprechender ORM-Ausdruck). Verhindert Page-Flackern bei gleichen `due_date`-Werten.
- **#65** — `app/services/steckbrief_policen.py` oder `app/routers/registries.py`: `policen_anzahl` in der Versicherer-Aggregation zählt nur Police-Rows, Heatmap-Slot-Berechnung filtert ggf. nach `next_main_due is not None`. Kommentar ergänzen, warum die Zählungen legitim divergieren dürfen (oder angleichen).
- **#70** — `app/templates/_registries_versicherer_detail.html` oder Aggregations-Service: Schadensquote bei `gesamtpraemie == 0` explizit behandeln: `schadens_quote = sum_schaden / gesamtpraemie if gesamtpraemie > 0 else None`. Template rendert `"–"` statt `"∞"` oder Division-by-Zero-Fehler.
- **#62** — Kommentar in `app/routers/objects.py` oder `app/services/steckbrief.py` beim Default-Sort: `# Default sort: short_code asc — bewusst kein numerischer Default (Spec-interner Widerspruch; Story-3.1-Entscheidung: alpha-sort ist explizit nutzbar)`.
- **#74** — `app/services/steckbrief_wartungen.py` oder Migrations-Doku: Kommentar bei `object_id`-FK auf Wartung: `# object_id = Spec-Wording, kodiert dasselbe wie police.object_id (gleiche Entität); kein eigenes JOIN nötig`.
- **And** alle bestehenden Tests bleiben grün. Schadensquote-Fix durch `test_versicherer_schadensquote_zero_praemie` (prüft Response-Rendering wenn Prämie 0).

---

### AC5 — Police-Form & PhotoStore Robustheit (#88, #101→in AC3, #131, #136, #146)

**Given** `update_police` überschreibt alle Felder unconditional, PhotoStore hat keine Guard bei fehlendem `drive_item_id`, und Wartungs-Datumseingaben werden nicht validiert

**When** AC5 implementiert ist

**Then**:
- **#136** — `app/routers/objects.py:update_police` (ca. L1160–1185): Statt 8 Form-Params direkt weiterzureichen, `request.form()` aufrufen und nur explizit gesendete Felder übernehmen. Pattern:
  ```python
  form_data = await request.form()
  changed_fields = {}
  if "police_number" in form_data:
      changed_fields["police_number"] = form_data["police_number"] or None
  # ... je Feld
  for field, value in changed_fields.items():
      write_field_human(db, policy, field, value, ...)
  ```
  Damit löst ein partieller API-Hit keine Null-Overwrites mehr aus. Backward-compat: Browser sendet immer alle Felder → kein Regressions-Risiko.
- **#88** — `app/routers/objects.py:delete_police` (oder `app/services/steckbrief_policen.py:delete_police`): Vor dem `db.delete(policy)` ein `db.get(InsurancePolicy, policy_id, with_for_update=True)` statt nur `db.get(...)`. Verhindert den Race bei concurrent Delete auf dasselbe Parent.
- **#131** — `app/services/photo_store.py:SharePointPhotoStore.upload`: Nach dem Upload-Call `item_id = response_json.get("id")`. Guard ergänzen: `if not item_id: raise PhotoStoreError("Graph-API lieferte kein 'id' in der Upload-Response")`. Aktuell: `drive_item_id = None` wird still in die DB geschrieben, dann ist Delete unmöglich.
- **#146** — `app/services/steckbrief_wartungen.py:create_wartung` und `update_wartung`: Keine Hard-Reject, aber Hinweis-Logic: wenn `letzte_wartung > date.today()` oder `next_due_date < date.today() - timedelta(days=30)`, Warnung im Audit-Log-`details_json` ergänzen: `{"warning": "Datum möglicherweise fehlerhaft: ..."}`. Due-Radar warnt dann implizit via Severity-Badge; kein `HTTPException` — User kann echte Retro-Einträge machen.
- **And** Test: `test_update_police_partial_body` — sendet Form-Body mit nur 3 von 8 Feldern, prüft, dass die anderen 5 Felder unverändert bleiben (nicht auf NULL gesetzt).

---

### AC6 — Permission-Enforcement: Zugangscodes & Vertraulich (#108, #109, #122, #123, #126)

**Given** Zugangscode-Endpoints fehlen `objects:view`-Check, Edit-Button rendert ohne Permission-Gate, view_confidential-Enforcement hat Lücken

**When** AC6 implementiert ist

**Then**:
- **#123** — `app/routers/objects.py`: alle Zugangscode-Write-Endpoints (Save für `entry_code_main_door`, `entry_code_garage`, `entry_code_technical_room`) erhalten zusätzlich `Depends(require_permission("objects:view"))` neben dem bereits vorhandenen `objects:edit`-Check. Grep: `grep -n "entry_code\|view_confidential" app/routers/objects.py`.
- **#122** — `app/templates/_obj_zugangscode_view.html:26`: Edit-Button erhält inneren Guard: `{% if current_user | has_permission("objects:edit") and current_user | has_permission("objects:view_confidential") %}`. Template-Pattern analog `_obj_technik.html` (wo der Edit-Button auch gated ist).
- **#108** — `app/routers/objects.py`: Im Objekt-Detail-Handler (ca. L79) prüfen, ob `user` die `view_confidential`-Permission hat. Falls nein: `context["notes_owners"] = {}` vor dem Template-Render setzen (Server-seitig leeren statt nur Template-hiding). Schließt den "direkter-POST"-Angriffsvektor zu Teilen (der volle IDOR-Fix ist v2). Memo: Die Zugangscode-Sektion wurde in Story 2.0 bereits vollständig hinter `view_confidential` gegated — `notes_owners`-Felder ggf. noch offen.
- **#109** — `app/templating.py::_prov_tooltip` (ca. L64): Der Fallback `"Manuell gepflegt am {ts}"` ist bereits korrekt. Ergänzen: wenn `provenance.user_id is None` aber `provenance.source == "user_edit"`: Text `"von [gelöschter Nutzer] am {ts}"`. Falls eine `user_email`-Spalte existiert (Audit-Pattern): Wert aus der Spalte nutzen.
- **#126** — `app/routers/objects.py`: Im Decrypt-Fehler-Pfad (Zugangscode-Entschlüsselung schlägt fehl): `try: audit(db, ...action="encryption_key_missing"...); db.commit(); except: pass` → umstellen auf explizites `db.flush()` vor dem äußeren `db.commit()`, sodass der Audit-Row auch bei Commit-Fail persistiert wird. Alternative: eigene Audit-Session öffnen (analog `_audit_sync`-Pattern in `_sync_common.py`).
- **And** Test: `test_entry_code_write_requires_view_permission` — User mit `objects:edit + view_confidential` aber ohne `objects:view` kann keinen Zugangscode schreiben (erwartet 403).

---

### AC7 — Audit-Trail Konsistenz (#92, #144)

**Given** Wartungs-Lösch-Audit nutzt falsche Action; X-Robots-Tag fehlt bei Streaming-Fehlern

**When** AC7 implementiert ist

**Then**:
- **#144** — `app/services/audit.py` (oder `app/config.py:KNOWN_AUDIT_ACTIONS`): `"wartung_deleted"` zu `KNOWN_AUDIT_ACTIONS` hinzufügen. In `app/services/steckbrief_wartungen.py:delete_wartung` den Audit-Aufruf von `action="object_field_updated"` auf `action="wartung_deleted"` umstellen.
- **#92** — `app/main.py`: Der `X-Robots-Tag`-Middleware-Hook setzt den Header bereits in `http.response.start`. Bei `StreamingResponse`/`FileResponse`, die den Body-Generator in einen Fehler laufen, ist der Header-Block schon raus → kein Fix möglich ohne ASGI-Wrapping. Kommentar im Middleware-Code ergänzen: `# Bei StreamingResponse mid-stream-Fehler ist X-Robots-Tag bereits gesendet — kein Nachträg möglich`. Kein Code-Change.
- **And** Test: `test_wartung_deleted_audit_action` — löscht Wartung, prüft `AuditLog.action == "wartung_deleted"`.

---

### AC8 — Template & UI-Details (#100, #105, #107, #110, #113)

**Given** Feld-Labels rendern als snake_case, Timestamps haben keinen Timezone-Marker, Sort-Tiebreaker und Rate-Gate-Limit fehlen

**When** AC8 implementiert ist

**Then**:
- **#107** — `app/services/steckbrief.py` oder `app/templating.py`: Neues Mapping-Dict `FIELD_LABEL_MAP: dict[str, str]` mit human-readable Labels für die wichtigsten Steckbrief-Felder (z.B. `"year_built": "Baujahr"`, `"weg_nr": "WEG-Nr.", `"impower_property_id": "Impower-ID"`, `"full_address": "Adresse"`, `"reserve_current": "Rücklage"`, etc.). In `app/templating.py` als Jinja2-Filter `field_label` registrieren: `lambda k: FIELD_LABEL_MAP.get(k, k.replace("_", " ").title())`. Verwendung in `_obj_stammdaten.html` und anderen betroffenen Templates via `{{ field_name | field_label }}`.
- **#105** — `app/templating.py::format_datetime_local` (oder `_prov_tooltip`): Timestamps werden als UTC gespeichert. Anzeige: `strftime("%d.%m.%Y %H:%M Uhr")` und Kommentar `# Timestamps in DB = UTC; für CET/CEST korrekte Darstellung ggf. pytz ergänzen`. Aktuell: Python-Default ist naiv-UTC. Als schnelles Low-Risk-Fix: Suffix `" UTC"` anhängen statt tZ-Konvertierung.
- **#110** — `app/services/impower.py::_rate_limit_gate`: `asyncio.sleep(sleep_s)` — `sleep_s` ist aktuell nicht nach oben begrenzt. Ergänzen: `sleep_s = min(sleep_s, 7.5)` (etwas unter dem 8s HTTP-Timeout). Verhindert, dass Gate-Wartezeit den Render-Request blockiert.
- **#113** — Migration `0012_steckbrief_finance_mirror_fields.py:~L62-66` und `app/services/steckbrief.py`: Kommentar ergänzen: `# ix_eigentuemer_impower_contact (ohne _id-Suffix) — Spec-AC8 vs Task-1.3 sind intern inkonsistent; der tatsächliche Index-Name ist der hier`. Kein Rename (Datenbankoperation ohne fachlichen Mehrwert).
- **#100** — `tests/conftest.py` oder `tests/test_write_gate_unit.py`: Bei FK `ON DELETE SET NULL`-Tests eine Warnung als Kommentar ergänzen: `# HINWEIS: SQLite ohne PRAGMA foreign_keys=ON ignoriert FK-Constraints. Dieser Test prüft nur ORM-Metadata. Für echte FK-Enforcement ist Postgres-Fixture nötig (project_testing_strategy.md).` Kein Infrastruktur-Change (kein Testcontainer).
- **And** Test: `test_field_label_filter` — prüft `field_label("year_built") == "Baujahr"` und `field_label("unknown_field") == "Unknown Field"` (Fallback-Titlecase).

---

### AC9 — HTTP-Compliance & Test-Qualität (#24, #25, #29, #30, #66)

**Given** WeasyPrint-Monkeypatch ist fragil, redundante Test-Mocks, Content-Disposition nicht RFC-5987

**When** AC9 implementiert ist

**Then**:
- **#25** — `app/routers/etv_signature_list.py:~L304`: `Content-Disposition: attachment; filename="..."` → RFC-5987-konform: `filename*=UTF-8''${slug}.pdf` ergänzen, damit nicht-ASCII-Zeichen im Dateinamen korrekt übertragen werden. `_slug` ist ohnehin `[a-z0-9-]`, also rein ASCII → der Fix ist harmlos und macht den Header formal konform.
- **#29** — `tests/test_etv_signature_list.py:~L1685-1696`: Kommentar bei WeasyPrint-Monkeypatch ergänzen: `# FRAGIL: Funktioniert nur weil der echte Import lazily im Handler passiert. Wird der Import auf Modul-Ebene gezogen, greift dieser Patch nicht mehr.` Kein Code-Change.
- **#30** — `app/routers/etv_signature_list.py:~L90-96`: Kommentar beim `_slug`-Fallback: `# Non-ASCII-WEG-Namen werden zu leerem _slug → Fallback "unterschriften" aktiviert. Bei mehreren solchen WEGs am gleichen Tag entsteht identischer Dateiname. Acceptable for DBS-German-ASCII portfolio.`
- **#66** — `tests/test_registries_*.py` (oder ähnlich): `monkeypatch.setitem(sys.modules, "reg_mod", ...)` auf `reg_mod.date` wird laut Review als redundant angesehen, da `date` nicht direkt im Testpfad mock-nötig ist. Dev-Agent prüft via `grep -n "reg_mod.date\|monkeypatch.*date" tests/` und entfernt Mocks, die tatsächlich redundant sind; behält nur die, die von einem Test aktiv verwendet werden.
- **#24** — `app/routers/etv_signature_list.py:~L296`: Kommentar beim `db.commit()`-Audit-Aufruf vor `StreamingResponse`: `# Audit "PDF generated" committed vor Streaming-Start. Semantisch: "PDF gerendert+bereit", nicht "Delivered". Bei Client-Disconnect mid-stream bleibt der Audit-Eintrag korrekt.`
- **And** alle existierenden Tests bleiben grün nach diesen Änderungen.

---

### AC10 — Dokumentation & Kommentare (#2, #90, #103, #114, #117, #118, #130, #132, #134, #135)

**Given** mehrere Codestellen und Dokumente haben fehlende Kommentare oder inkonsistente Beschreibungen

**When** AC10 implementiert ist

**Then**:
- **#2** — `app/services/audit.py`: Kommentar beim `details_json`-Parameter: `# details_json enthaelt echte Umlaute (seit Umlaut-Sweep 2026-04-30). Log-Aggregatoren und grep-Patterns muessen UTF-8-aware sein.`
- **#90** — `app/services/steckbrief_schadensfaelle.py` oder zugehöriger Service: Kommentar beim FK-Field-Write: `# FK-Felder (unit_id, police_id) werden durch write_field_human geleitet (Provenance), auch beim Row-Create. Spec-AC1 sagt "alle Feld-Writes"; Dev-Notes-Task-2.3 erlaubt FK-Ausnahme beim Create. Aktuell: beide durch Gate → Provenance-Konsistenz gewährt.`
- **#103** — `docs/architecture.md §8` (Audit-Actions-Tabelle): Deduplizierte Version sicherstellen — falls die Tabelle in §8 und an anderer Stelle vorhanden ist, eine entfernen und durch einen Verweis ersetzen: `Vollständige Liste: app/services/audit.py:KNOWN_AUDIT_ACTIONS`.
- **#114** — `app/services/_sync_common.py:run_sync_job`: Docstring ergänzen: `# Diese Funktion öffnet ihre eigene DB-Session via db_factory() und committet eigenständig. Nicht in transaktionalen Test-Scopes mischen (kein Savepoint-Support).`
- **#117** — `app/templates/_obj_technik_field_edit.html`: Kommentar beim `max="3000"`: `{# bewusst statischer Wert statt {{ max_year }} — kein jährlicher Template-Change nötig; Server-Validator ist die harte Grenze. #}`
- **#118** — `app/services/steckbrief.py` oder Migration `0010`: Kommentar bei `year_built`/`year_roof`: `# Konzeptuell: Stammdaten-Cluster-1 (Impower-Mirror) UND Technik-Cluster-4 (User-Edit). Write-Gate-Mirror-Guard greift wenn Impower diese Felder künftig spiegelt.`
- **#130** — `app/services/photo_store.py:SharePointPhotoStore.upload`: Kommentar: `# Zielpfad "DBS/Objekte/{short_code}/..." setzt voraus, dass drive_id auf die "DBS/Objekte"-Library zeigt. Klärung beim M365-Admin-Ticket (SHAREPOINT_DRIVE_ID-Setting).`
- **#132** — `app/services/photo_store.py:SharePointPhotoStore.url` (oder äquivalenter Kommentar): `# v1: Foto-Anzeige nicht implementiert (temp Download-URLs Ablauf ~1h). v1.1: url()-Methode + URL-Cache + Template-<img>-Branch.`
- **#134** — `app/services/steckbrief_impower_mirror.py:discover_new_objects` (oder äquivalent): Kommentar: `# Bootstrap-short_code/name = "impw-{pid}" als deterministischer Platzhalter (NOT-NULL ORM-Constraint). User muss via Steckbrief-UI umbenennen. v1.1: Mapping aus Impower-Property-Keys ergänzen.`
- **#135** — `docs/architecture.md §CD2 (Write-Gate-Ausnahmen)`: Ergänzen: `Object-Row-Creation via Discover-Mirror ist erlaubte Ausnahme (db.add(Object(...))). Row-Creation mit Pflicht-Feldern ist kein Field-Write i.S.d. CD2-Konvention.`
- **And** keine neuen Tests nötig für reine Kommentar/Doku-Änderungen.

---

### AC11 — Deferred-Work.md aktualisieren (#2–#146 der abgearbeiteten Items)

**Given** alle 47 Items in `deferred-work.md` haben Sprint-Target `post-prod`

**When** AC1–AC10 implementiert sind

**Then** werden die entsprechenden Items in der Triage-Tabelle mit `[done-5-6]`-Tag in der Sprint-Target-Spalte markiert (z.B. `post-prod [done-5-6]`), damit die Triage-Tabelle korrekt bleibt.

---

## Tasks / Subtasks

- [x] **Task 1: AC1 — Permission-Konstanten** (#20 #93 #102)
  - [x] 1.1 `PERM_*`-Konstanten in `permissions.py` einführen
  - [x] 1.2 Magic-Strings in `app/routers/` und `app/services/` ersetzen (grep-basiert)
  - [x] 1.3 Waisen-Key-Cleanup in `_seed_default_roles`
  - [x] 1.4 Kommentar `_ENCRYPTED_FIELDS` in `steckbrief_write_gate.py`
  - [x] 1.5 Test: `test_no_permission_magic_strings`

- [x] **Task 2: AC2 — Score-Service Algorithmus** (#46 #38 #98 #36 #45)
  - [x] 2.1 `_ALL_SCALAR` → `_ALL_SCALAR_FIELDS` umbenennen in `pflegegrad.py`
  - [x] 2.2 Stable Tie-Break `created_at.desc(), id.desc()` in `pflegegrad.py` + `steckbrief_write_gate.py`
  - [x] 2.3 `weakest_fields` dedup+sort in `pflegegrad.py`
  - [x] 2.4 Kommentar `last_known_balance == 0` in `pflegegrad.py`

- [x] **Task 3: AC3 — JSONB-Feld-Qualität** (#44 #85 #101)
  - [x] 3.1 `sepa_mandate_refs` Falsy-Filter in `pflegegrad.py`
  - [x] 3.2 Orphan `notes_owners` Cleanup-Step bei Eigentuemer-Delete
  - [x] 3.3 `proposed_value` Decimal/Date typisiertes Envelope in `steckbrief_write_gate.py`
  - [x] 3.4 Test: `test_proposed_value_decimal_roundtrip`

- [x] **Task 4: AC4 — Due-Radar & Registry** (#73 #65 #70 #62 #74)
  - [x] 4.1 `due_date + entity_id` Tiebreaker in `due_radar.py`
  - [x] 4.2 `policen_anzahl` vs Heatmap Kommentar/Angleichung
  - [x] 4.3 Schadensquote Division-by-Zero Guard in Service/Template
  - [x] 4.4 Sort-Default-Kommentar in `objects.py`
  - [x] 4.5 `object_id`-Kommentar in `steckbrief_wartungen.py`
  - [x] 4.6 Test: `test_versicherer_schadensquote_zero_praemie`

- [x] **Task 5: AC5 — Police-Form & PhotoStore** (#136 #88 #131 #146)
  - [x] 5.1 `update_police` auf `request.form()`-basierten partiellen Update umstellen
  - [x] 5.2 `delete_police` mit `with_for_update=True` absichern
  - [x] 5.3 PhotoStore `drive_item_id = None` Guard in `photo_store.py`
  - [x] 5.4 `letzte_wartung`/`next_due_date` Warning im Audit-Log
  - [x] 5.5 Test: `test_update_police_partial_body`

- [x] **Task 6: AC6 — Permission-Enforcement** (#123 #122 #108 #109 #126)
  - [x] 6.1 `objects:view`-Dep auf Zugangscode-Write-Endpoints
  - [x] 6.2 Edit-Button `_obj_zugangscode_view.html` innerer Permission-Check
  - [x] 6.3 `notes_owners` serverseitig für non-confidential User leeren
  - [x] 6.4 `_prov_tooltip` "von [gelöschter Nutzer]" Fallback
  - [x] 6.5 Audit-Row bei `DecryptionError` abgesichert
  - [x] 6.6 Test: `test_entry_code_write_requires_view_permission`

- [x] **Task 7: AC7 — Audit-Action Konsistenz** (#144 #92)
  - [x] 7.1 `"wartung_deleted"` in `KNOWN_AUDIT_ACTIONS` + `steckbrief_wartungen.py`
  - [x] 7.2 Kommentar X-Robots-Tag Streaming in `main.py`
  - [x] 7.3 Test: `test_wartung_deleted_audit_action`

- [x] **Task 8: AC8 — Template & UI-Details** (#107 #105 #110 #113 #100)
  - [x] 8.1 `FIELD_LABEL_MAP` + `field_label`-Filter in `templating.py`/`steckbrief.py`
  - [x] 8.2 Timestamp-Tooltips mit `" UTC"`-Suffix in `templating.py`
  - [x] 8.3 Rate-Gate `min(sleep_s, 7.5)` in `impower.py`
  - [x] 8.4 Index-Name-Kommentar in Migration 0012
  - [x] 8.5 FK-Test-Kommentar in `conftest.py` / Write-Gate-Test
  - [x] 8.6 Test: `test_field_label_filter`

- [x] **Task 9: AC9 — HTTP-Compliance & Test-Qualität** (#25 #29 #30 #66 #24)
  - [x] 9.1 `Content-Disposition` RFC-5987 in `etv_signature_list.py`
  - [x] 9.2 WeasyPrint-Monkeypatch Fragilitäts-Kommentar
  - [x] 9.3 Non-ASCII Filename-Fallback Kommentar
  - [x] 9.4 Redundante `reg_mod.date`-Mocks entfernen
  - [x] 9.5 Audit-Commit-vor-Streaming Kommentar

- [x] **Task 10: AC10 — Dokumentation & Kommentare** (#2 #90 #103 #114 #117 #118 #130 #132 #134 #135)
  - [x] 10.1 Umlaut-Kommentar in `audit.py`
  - [x] 10.2 FK-Spec-Selbstwiderspruch-Kommentar in Schadensfälle-Service
  - [x] 10.3 `docs/architecture.md §8` Audit-Actions deduplizieren
  - [x] 10.4 `_sync_common.py:run_sync_job` Docstring
  - [x] 10.5 Template `max="3000"` Kommentar
  - [x] 10.6 `year_built`/`year_roof` Domänen-Kommentar
  - [x] 10.7 SharePoint-Zielpfad Kommentar in `photo_store.py`
  - [x] 10.8 SharePoint-Foto-URL v1.1-TODO
  - [x] 10.9 Object-Bootstrap Platzhalter Kommentar
  - [x] 10.10 CD2-Ausnahme in `docs/architecture.md`

- [x] **Task 11: AC11 — Deferred-Work.md aktualisieren**
  - [x] 11.1 Alle 47 Items mit `[done-5-6]` markieren

## Dev Notes

### Projektstruktur-Ankerpunkte

- **Permissions-Constanten**: Neue Konstanten in `app/permissions.py` oben als Modul-Variablen, da `PERMISSIONS`-Dict bereits dort definiert ist. Importe in Routern: `from app.permissions import PERM_OBJECTS_APPROVE_KI` etc.
- **Jinja2-Filter**: Neue Filter **ausschließlich** in `app/templating.py` registrieren (`templates.env.filters["field_label"] = ...`). Pattern: analog `iban_format`-Filter Z. 243.
- **Template-Response-Signatur**: `templates.TemplateResponse(request, "name.html", {...})` — `request` zuerst. Alte Signatur wirft `TypeError: unhashable type dict` (Memory: `feedback_starlette_templateresponse`).
- **JSONB-Mutation-Falle**: Nie `obj.jsonb_field["key"] = value` (SQLAlchemy trackt Deep-Mutations nicht). Immer `obj.jsonb_field = {**obj.jsonb_field, "key": value}` oder `flag_modified(obj, "field_name")`. Pattern aus `mietverwaltung.py::_mutate_overrides`.
- **Write-Gate**: `write_field_human(db, entity, field_name, value, source, user)` ist der korrekte Aufruf. Direkte `entity.field = value`-Writes sind nur für Row-Creation, FieldProvenance, ReviewQueueEntry, AuditLog erlaubt.
- **`_audit_sync`**: öffnet eigene Session — nicht in Request-Handler verwenden, nur in BackgroundTasks/Sync-Jobs. Für Audit in Routern: `audit(db, ...)` + am Ende des Handlers `db.commit()`.
- **Keine neuen Migrationen** für diese Story — alle Änderungen sind Service/Router/Template/Doku-seitig oder nutzen bestehende JSONB-Felder.
- **Kein neues Python-Paket** erforderlich.

### Kritische Detailhinweise pro AC

**AC1 Permission-Konstanten — Grep-Scope**:
`grep -rn '"objects:\|"registries:\|"due_radar:\|"sync:' app/routers/ app/services/ app/templates/`
Templates nutzen String-Literale direkt im `has_permission`-Filter-Aufruf — diese bleiben als Strings (kein Python-Import in Jinja2). Nur Router + Services auf Konstanten umstellen.

**AC3 #85 Orphan notes_owners — Vorsicht JSONB-Mutation**:
`obj.notes_owners = {k: v for k, v in obj.notes_owners.items() if k not in orphan_keys}` ist ein komplettes Reassign → kein `flag_modified` nötig, weil die Variable selbst neu zugewiesen wird. Sicherstellen, dass `obj.notes_owners` nie `None` ist (`obj.notes_owners or {}`).

**AC3 #101 proposed_value Envelope — Backward-Compat**:
Alte `proposed_value`-Rows (vor diesem Fix) enthalten entweder einen String oder eine Zahl. Im `approve_review_entry`: zuerst auf Envelope-Shape prüfen (`isinstance(val, dict) and "__type__" in val`); sonst Wert direkt verwenden (Backward-Compat). Neues `write_field_ai_proposal` schreibt Envelope.

**AC5 #136 update_police — request.form() in FastAPI**:
`await request.form()` gibt ein `ImmutableMultiDict` zurück. Check mit `"police_number" in form_data` ist korrekt. Leerer String `""` vs. nicht gesendetes Feld: beide werden nicht in `form_data` unterschieden — aber Browser sendet immer alle Felder aus dem Formular, daher ist das kein praktischer Unterschied.

**AC6 #108 notes_owners serverseitig**:
Der Handler in `app/routers/objects.py` baut den Template-Context. Vor dem Context-Build:
```python
if not has_permission(user, "objects:view_confidential"):
    notes_owners = {}
else:
    notes_owners = obj.notes_owners or {}
```
Damit kann ein nicht-autorisierter User auch bei direktem API-Zugriff keine Notizen extrahieren (er würde leere notes_owners bekommen).

**AC8 #107 FIELD_LABEL_MAP — Scope**:
Nur die gebräuchlichsten Felder einpflegen (15–20 Einträge), nicht alle 50+ ORM-Felder. Fallback `k.replace("_", " ").title()` reicht für unbekannte Felder. Keine i18n-Infrastruktur nötig.

### Testing-Strategie

- Test-DB: SQLite in-memory mit `StaticPool` (bestehend in `tests/conftest.py`). Keine neue Infrastruktur.
- Template-Tests: `client.get(url)` → `response.text` durchsuchen.
- Neue Tests bevorzugt in neuer Datei `tests/test_code_quality.py`.
- `asyncio_mode = "auto"` — kein `@pytest.mark.asyncio` pro Test nötig.
- Anthropic/Impower immer mocken. Kein Netzwerk-Call in Tests.

### Dateien die geändert werden

**Python Services:**
- `app/permissions.py` (AC1: #20 Konstanten)
- `app/main.py` (AC1: #93 Waisen-Cleanup)
- `app/services/pflegegrad.py` (AC2: #46 #38 #36 #44 #45)
- `app/services/steckbrief_write_gate.py` (AC2: #98; AC3: #101; AC1: #102-Kommentar)
- `app/services/steckbrief.py` oder `steckbrief_impower_mirror.py` (AC3: #85)
- `app/services/due_radar.py` (AC4: #73)
- `app/services/steckbrief_policen.py` (AC4: #65; AC5: #88)
- `app/services/steckbrief_wartungen.py` (AC4: #74; AC5: #146; AC7: #144)
- `app/services/photo_store.py` (AC5: #131; AC10: #130 #132)
- `app/services/audit.py` (AC10: #2; AC7: #144-KNOWN_AUDIT_ACTIONS)
- `app/services/impower.py` (AC8: #110)
- `app/services/_sync_common.py` (AC10: #114)

**Python Routers:**
- `app/routers/objects.py` (AC1: #20-Magic-Strings; AC4: #62; AC5: #136 #88; AC6: #123 #108 #126)
- `app/routers/registries.py` (AC1: #20-Magic-Strings; AC4: #65 #70)
- `app/routers/etv_signature_list.py` (AC9: #25 #30 #24)

**Templating:**
- `app/templating.py` (AC8: #107 `field_label`-Filter; #105 Timestamp-Format)

**Templates:**
- `app/templates/_obj_zugangscode_view.html` (AC6: #122 Edit-Button Guard)
- `app/templates/_obj_stammdaten.html` (AC8: #107 field_label-Verwendung)
- Ggf. weitere Templates mit `{{ field_name }}` → `{{ field_name | field_label }}`

**Tests:**
- `tests/test_code_quality.py` (neu: ACs 1–8)
- `tests/conftest.py` (AC8: #100 FK-Kommentar)
- `tests/test_etv_signature_list.py` (AC9: #29 #66 Kommentare/Cleanup)

**Dokumentation:**
- `docs/architecture.md` (AC10: #103 #135)
- `output/implementation-artifacts/deferred-work.md` (AC11)

### Abgrenzung / Out-of-Scope

Diese Story bearbeitet **nicht**:
- #4 `approve_ki` IDOR (deferred-to-v2)
- #6 Single-Permission-Tier (größere Änderung)
- #55 `/objects`-Pagination (eigene Story)
- #57 `accessible_object_ids` per-Request-Cache (Story 5-4)
- #115 Key-Ring-Rotation (deferred-to-v2)
- #94/#95 AST-Write-Gate-Coverage (eigene Test-Infrastruktur-Story)
- Alle Items aus 5-7 (Test-Coverage), 5-8 (Facilioo-Hardening)
- #33 Phase-2-gather fail-loud (by-design, deferred-until-UX-feedback)

### Lernnotizen aus Story 5-5

- `accessible_object_ids_for_request(request, db, user)` ist der korrekte Call (nicht `accessible_object_ids(db, user)` — die alte Signatur, 5-4 hat das migriert).
- `_load_accessible_object` erhält `request: Request` als erstes Argument — nicht verändern.
- In `app/templating.py` wurde in 5-4 ein Stale-Hint-Filter ergänzt — dieses Muster als Vorlage für `field_label`-Filter.
- AC6 Notes: 5-5 AC7 hat Pen-Icon-A11y in `_extraction_field_view.html` + `_obj_technik_field_view.html` geprüft — Zugangscode-Edit-Button in `_obj_zugangscode_view.html` war damals noch nicht adressiert (kein Überschneidungsrisiko).

### Referenzen

- Deferred-Work-Details: `output/implementation-artifacts/deferred-work.md`
- Permission-System: `app/permissions.py` + `app/main.py:_seed_default_roles`
- Write-Gate + `_ENCRYPTED_FIELDS`: `app/services/steckbrief_write_gate.py`
- Score-Formel: `app/services/pflegegrad.py`
- Due-Radar-Query: `app/services/due_radar.py`
- Templating-Singleton + Filter-Pattern: `app/templating.py:243` (`iban_format` als Vorlage)
- `_audit_sync`-Session-Convention: `app/services/_sync_common.py:127-144`
- Provenance-Tooltip: `app/templating.py:~60`
- Zugangscode-Permission-Enforcement: `app/routers/objects.py` + `app/templates/_obj_zugangscode_view.html`

### Review Findings

- [x] [Review][Patch] notes_owners Cleanup: Mirror-Guard blockiert Cleanup + Massen-Lösch-Risiko [app/services/steckbrief_impower_mirror.py:614]
- [x] [Review][Patch] delete_police: with_for_update via db.get() trifft Identity Map — kein echter Row-Lock [app/services/steckbrief_policen.py:134]
- [x] [Review][Patch] dependency_overrides.clear() ohne try/finally in zwei Tests [tests/test_code_quality.py:138,231]
- [x] [Review][Patch] _unwrap_proposal_value: KeyError wenn proposed_value kein "value"-Key hat [app/services/steckbrief_write_gate.py:482]
- [x] [Review][Patch] _json_safe_as_proposal: datetime-Werte nicht als Envelope kodiert [app/services/steckbrief_write_gate.py:188]
- [x] [Review][Patch] _unwrap_proposal_value: InvalidOperation bei korruptem Decimal-String [app/services/steckbrief_write_gate.py:201]
- [x] [Review][Patch] zugangscode_field_view + edit: db.flush() fehlt vor db.commit() im DecryptionError-Pfad [app/routers/objects.py:766]
- [x] [Review][Patch] field_label-Filter nicht in Templates verwendet — _obj_stammdaten.html zeigt snake_case [app/templates/_obj_stammdaten.html:20]
- [x] [Review][Patch] _prov_tooltip: "von [gelöschter Nutzer]" fehlt Prefix "Manuell gepflegt am" [app/templating.py:181]
- [x] [Review][Patch] sepa_mandate_refs: `if m` filtert leere Dicts fälschlich — sollte `if m is not None` sein [app/services/pflegegrad.py:230]
- [x] [Review][Patch] test_no_permission_magic_strings: Docstring beschreibt breiteren Scope als tatsächlich geprüft [tests/test_code_quality.py:20]
- [x] [Review][Patch] test_proposed_value_decimal_roundtrip prüft Envelope-Shape nicht (nur dict+value-Key) [tests/test_code_quality.py:89]
- [x] [Review][Defer] approve_review_entry: Double-Approve löst ValueError statt HTTP 409 — pre-existing [app/services/steckbrief_write_gate.py:493] — deferred, pre-existing
- [x] [Review][Defer] _rate_limit_gate: min(wait, 7.5) ist Dead Code (wait ≤ 0.12s) — spec-beauftragt, harmlos [app/services/impower.py:714] — deferred, pre-existing
- [x] [Review][Defer] _build_date_warning: bei zwei gleichzeitig ungültigen Daten nur erstes Warning — by-design [app/services/steckbrief_wartungen.py:131] — deferred, pre-existing
- [x] [Review][Defer] police_update: Double-Consume request.form() — technisch sicher (Starlette-Cache), fehlt Erklärungskommentar [app/routers/objects.py:1607] — deferred, pre-existing
- [x] [Review][Defer] RFC-5987 percent-encoding in Content-Disposition fehlt — harmlos da _slug ASCII-only [app/routers/etv_signature_list.py:434] — deferred, pre-existing

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- AC3 #85 Orphan-notes_owners: Simpler Variant gewählt (cleanup im Mirror-Update statt im Eigentuemer-Delete, da kein Delete-Endpoint in v1 existiert).
- AC4 #70 Schadensquote: Typ `float | None` statt `float`; alle drei Stellen (VersichererAggRow, VersichererDetailData, _build_heatmap-Kommentar) angepasst; Templates rendern `"–"` bei None. Bestehende Tests auf `None` umgestellt.
- AC1 #93 Waisen-Keys: Vorhandene Tests spiegeln altes Verhalten (Keys bleiben) — Charakterisierungstest umbenannt + Assertion invertiert auf neues Cleanup-Verhalten.
- AC7 #144 `wartung_deleted`: Route-Test + Unit-Test beide auf neuen Action-Key umgestellt.
- AC8 #105 UTC-Suffix: In `_prov_tooltip` ergänzt; kein neues Paket (pytz) nötig, Low-Risk-Fix.
- AC9 #66 reg_mod.date: Die `.today`-Einträge in den 4 Mocks sind redundant (registries.py nutzt `today_local()` aus `_time.py`). Entfernt. `.max`/`.min` bleiben als Sort-Sentinel.
- Umbenennung `_ALL_SCALAR` → `_ALL_SCALAR_FIELDS`: Drei Import-Stellen nachgezogen (objects.py, test_performance_query_optimization.py).
- test_update_police_partial_body: Route ist PUT (HTMX), nicht POST. Test auf `steckbrief_admin_client.put(...)` umgestellt (CSRF-Token inkludiert).
- 1112 Tests grün, 2 xfailed, 3 xpassed.

### File List

**Python Services:**
- `app/permissions.py`
- `app/main.py`
- `app/services/pflegegrad.py`
- `app/services/steckbrief_write_gate.py`
- `app/services/steckbrief_impower_mirror.py`
- `app/services/due_radar.py`
- `app/services/steckbrief_policen.py`
- `app/services/steckbrief_wartungen.py`
- `app/services/steckbrief_schadensfaelle.py`
- `app/services/photo_store.py`
- `app/services/audit.py`
- `app/services/impower.py`
- `app/services/_sync_common.py`
- `app/services/registries.py`
- `app/services/steckbrief.py`

**Python Routers:**
- `app/routers/objects.py`
- `app/routers/registries.py`
- `app/routers/due_radar.py`
- `app/routers/admin.py`
- `app/routers/etv_signature_list.py`

**Templating:**
- `app/templating.py`

**Templates:**
- `app/templates/_obj_zugangscode_view.html`
- `app/templates/_obj_technik_field_edit.html`
- `app/templates/_versicherer_rows.html`
- `app/templates/registries_versicherer_detail.html`

**Migrations:**
- `migrations/versions/0012_steckbrief_finance_mirror_fields.py`

**Tests:**
- `tests/test_code_quality.py` (neu)
- `tests/test_write_gate_unit.py`
- `tests/test_registries_unit.py`
- `tests/test_steckbrief_bootstrap.py`
- `tests/test_wartungspflichten_routes_smoke.py`
- `tests/test_wartungspflichten_unit.py`
- `tests/test_etv_signature_list.py`
- `tests/test_performance_query_optimization.py`

**Dokumentation:**
- `docs/architecture.md`
- `output/implementation-artifacts/deferred-work.md`
- `output/implementation-artifacts/5-6-code-qualitaet-refactoring.md`
