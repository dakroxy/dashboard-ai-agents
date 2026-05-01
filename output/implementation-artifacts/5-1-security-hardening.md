# Story 5-1: Security-Hardening

Status: review

## Story

Als Betreiber der Plattform,
moechte ich alle bekannten Security-Luecken vor dem externen Rollout geschlossen haben,
damit kein CSRF-Angriff, kein Caching-Leak und keine Length-Injection in Produktion erreichbar ist.

## Boundary-Klassifikation

`hardening` (cross-cutting) — **Hohes Risiko bei Nicht-Umsetzung, mittleres Risiko bei der Umsetzung selbst**.

- Kein neues Feature, nur Absicherung bestehender Endpunkte. Cross-cutting → trifft alle Routes.
- CSRF ist Pre-Prod-Blocker (`high`); alle anderen Items sind `medium` oder `high`.
- **Eine** neue Migration (`0019_police_column_length_caps`) — alle anderen Aenderungen sind Code-Level.
- Keine neuen Permissions, keine Schema-Erweiterung in `audit_log` (Spalte `ip_address` ist seit Migration 0007 bereits `String(45)` — siehe Risiko 4 unten).

**Vorbedingungen:**

1. **Story 4.4 (`done`)** — letzte aktive Story. Branch `main` ist gruen, keine offenen PRs.
2. **Latest Migration ist `0018_facilioo_mirror_fields.py`** → naechste freie Nummer ist `0019`. Memory `feedback_migrations_check_existing.md` befolgen: vor Migration-Anlage `ls migrations/versions/` ausfuehren, nicht nur dieser Story-Datei vertrauen.
3. **53 mutierende Routes** (POST/PUT/DELETE/PATCH) in `app/routers/` + `app/main.py`. Alle Auth-Routen (`/auth/google/login`, `/auth/google/callback`, `/auth/logout`) sind **GET**, damit CSRF-Middleware (gated auf non-GET) sie nicht beruehrt.

**Kritische Risiken:**

1. **Middleware-Order in `app/main.py`** — `SessionMiddleware` MUSS vor der CSRF-Middleware registriert werden, sonst hat CSRF keine Session zum Token-Lookup. FastAPI/Starlette appliziert Middlewares in **umgekehrter** Registrierungs-Reihenfolge → die zuletzt geadded-te Middleware laeuft zuerst. Reihenfolge in der Datei: erst `add_middleware(SessionMiddleware, ...)`, dann `add_middleware(CSRFMiddleware, ...)`.
2. **`Cache-Control: no-store` darf NICHT auf `/static/*` gesetzt werden** — zerschiesst Browser-Cache fuer Tailwind/HTMX-Assets, jeder Page-Load zieht ~200 KB neu. Cache-Control ist gezielt **nur** auf Admin-HTML-Fragment-GETs anzuwenden, nicht global. AC2 listet die konkreten Routes.
3. **`autoescape=True` (global) vs. `select_autoescape(["html", "htm", "xml"])` (extension-based)** — Default von `Jinja2Templates` ist heute `select_autoescape(...)`. Auf `autoescape=True` umzuschalten wuerde auch Plain-Text-Templates escapen (z. B. zukuenftige Mail-Templates). Empfehlung in AC5: explizit `select_autoescape(["html", "htm", "xml", "jinja"])` setzen — verhaelt sich identisch zum Default, aber explizit + nicht versionsabhaengig.
4. **`audit_log.ip_address` ist bereits `String(45)`** (`app/models/audit_log.py:38`, Migration 0007). Ein `X-Forwarded-For` mit > 45 Zeichen wuerde aktuell einen DB-Constraint-Error werfen → 500. Fix ist **Python-side Truncation** in `app/services/audit.py:120`, **keine** Migration. Wenn Dev-Agent eine neue Migration anlegt, ist das ueberfluessig + verschwendet Revision-Nummer.
5. **`Schadensfall.description` ist bereits `Text` (unbounded)** in der DB (`app/models/police.py:161`). Form-Cap auf 5000 ist eine **DoS-Mitigation** (kein POST mit 1 GB-Description), kein Datenbank-Constraint. Form-Cap + Service-Guard reichen, **keine** Migration noetig.
6. **`police.produkt_typ`/`police_number`-Migration kann Live-Daten reissen** — wenn ein bestehender Datensatz `produkt_typ` mit > 100 Zeichen oder `police_number` > 50 Zeichen hat, schmiert `ALTER COLUMN ... TYPE VARCHAR(100)` ab. Migration MUSS im `upgrade()` zuerst `SELECT MAX(LENGTH(...))` abfragen und bei Ueberlauf abbrechen mit klarem Error. Pre-Migration-Check als Task 8 (siehe unten).
7. **CSRF-Token-Storage-Entscheidung** — Implementation: **Token in `request.session["csrf_token"]`** (Storage), **Transport via `X-CSRF-Token`-Header**, gerendert in `<body>` als globaler `hx-headers`-Block. Begruendung: SessionMiddleware ist bereits aktiv; HTMX `hx-headers` propagiert automatisch auf alle HTMX-Requests; klassische `<form>`-POSTs (sehr wenige im Code, ueberwiegend HTMX) bekommen Hidden-Input via Jinja-Macro. Alternativen (eigenes Cookie, `starlette-csrf`-Package, Double-Submit) sind **out-of-scope**.
8. **Token-Rotation: einmal pro Session** (nicht pro Request). Begruendung: Pragmatismus — Intranet-App, Google-Workspace-OAuth, kein Multi-Tab-Race noetig. Per-Request-Rotation komplexiert HTMX-Re-Hydration ohne realen Sicherheitsgewinn fuer das Threat-Model.
9. **CSRF-Exempt-Liste** — Welche Routes muessen explizit ausgenommen werden? Antwort: **keine**. Alle Auth-Routes sind GET (verifiziert in `app/routers/auth.py:20/31/130`), `/health`-Endpunkte sind GET, externe Webhooks gibt es nicht. Middleware checkt nur non-GET → keine Exempts noetig. Diese Annahme aktiv testen (siehe Tests).
10. **Double-Encrypt-Guard auf falsy-Werte** — `if value and isinstance(value, str) and value.startswith("v1:"): raise ...`. Ohne `isinstance`-Check wuerde der Guard auf Non-String-Inputs `AttributeError` werfen statt `WriteGateError`.

## Deferred-Work-Coverage

| # | Eintrag | Severity | AC |
|---|---------|----------|-----|
| 3, 80, 82, 119 | CSRF-Token projektweit fehlt | high | AC1 |
| 5 | `Cache-Control: no-store` auf Admin-Fragment-Routes | medium | AC2 |
| 87 | `Schadensfall.description` ohne Length-Cap | high | AC3 |
| 89 | `audit_log.ip_address` ohne Length-Cap | high | AC3 |
| 116 | Double-Encrypt-Risiko fuer zukuenftige Write-Pfade | medium | AC4 |
| 121 | Jinja2 Autoescape nicht explizit konfiguriert | low | AC5 |
| 142 | `produkt_typ`/`police_number` unbegrenzte Laenge | high | AC6 |
| 4 | `objects:approve_ki` portfolio-weit (kein Objekt-IDOR) | medium | AC7 |
| 81 | GET `/extraction/view` kein `documents:approve`-Check | low | AC7 |

## Acceptance Criteria

**AC1 — CSRF-Token auf allen non-GET-Routen**

**Given** ein angemeldeter User mit gueltiger Session
**When** ein POST/PUT/DELETE/PATCH-Request OHNE gueltigen `X-CSRF-Token`-Header (oder mit falschem Token) gesendet wird
**Then** antwortet die App mit **HTTP 403** (Body: `{"detail": "CSRF token missing or invalid"}`)
**And** ein POST mit gueltigem Token (= aktueller `request.session["csrf_token"]`) laeuft normal durch
**And** GET/HEAD/OPTIONS-Requests passieren die Middleware OHNE Token-Check
**And** alle 53 mutierenden Routes (POST/PUT/DELETE/PATCH in `app/routers/*` + `app/main.py`) sind durch die globale Middleware abgedeckt — KEIN Per-Route-Decorator
**And** HTMX-Requests senden den Token automatisch via `hx-headers`-Block in `<body>` von `app/templates/base.html` (Jinja-Variable `csrf_token` aus Template-Global)
**And** klassische `<form method="post">`-Submits (falls vorhanden) bekommen den Token via `{% csrf_token %}`-Macro als Hidden-Input
**And** der Token wird beim ersten Login generiert (`request.session["csrf_token"] = secrets.token_urlsafe(32)`) und bleibt bis zum Logout stabil

**AC2 — Cache-Control: no-store auf Admin-HTML-Fragment-GETs**

**Given** eine GET-Route, die ein HTML-Fragment fuer HTMX-Swaps zurueckgibt (`response_class=HTMLResponse` UND Pfad matcht `/admin/*` UND der Fragment-Selector existiert; konkret die unten gelisteten Routes)
**When** der Browser die Response empfaengt
**Then** enthaelt der Response-Header `Cache-Control: no-store`
**And** die folgenden Routes sind explizit abgedeckt:
  - `GET /admin/review-queue/{entry_id}/reject-form` (`app/routers/admin.py:1264` — `reject_form_fragment`)
  - `GET /admin/review-queue/rows` (`app/routers/admin.py:1163` — Filter-Fragment)
  - alle weiteren `response_class=HTMLResponse`-Routes unter `/admin/*` mit `_fragment`-Suffix oder die HTML-Fragmente fuer HTMX-Swaps zurueckgeben (Dev-Agent prueft via `grep -n "response_class=HTMLResponse" app/routers/admin.py`)
**And** `/static/*`-Routes bekommen KEIN `Cache-Control: no-store` (Tailwind/HTMX-Assets bleiben browser-cached)
**And** Admin-Vollseiten (`/admin/`, `/admin/users`, `/admin/logs` etc.) sind NICHT zwingend auf `no-store` — der Header gilt nur fuer Fragment-Endpunkte (Begruendung: Vollseiten sind nach Page-Reload sowieso frisch, Fragmente koennten sonst im Browser-History-Cache stale Decisions zeigen)
**And** Implementation als Per-Route via `response.headers["Cache-Control"] = "no-store"` direkt in den betroffenen Handlern (kein generisches Path-Prefix-Middleware → vermeidet versehentliches Treffen von `/static/*`-Routes oder Vollseiten)

**AC3 — Length-Caps auf Schadensfall.description und audit_log.ip_address**

**Given** ein POST `/objects/{object_id}/schadensfaelle` mit `description`-Feld > 5000 Zeichen
**When** der Server die Form-Validation durchlaeuft
**Then** antwortet der Server mit **HTTP 422** und Form-Field-Fehler `description: max_length=5000`
**And** kein 500, kein DB-Insert, keine DB-Fehlermeldung im Response-Body
**And** der Form-Param wird angepasst auf `description: str | None = Form(None, max_length=5000)` in `app/routers/objects.py:1181`
**And** zusaetzlich Service-Guard in `app/services/steckbrief_schadensfaelle.py` (Belt-and-Suspenders): `if description and len(description) > 5000: raise ValueError(...)`

**Given** ein eingehender Request mit `X-Forwarded-For`-Header > 45 Zeichen (z. B. mehrere gespoofte Hops verkettet)
**When** `audit()` in `app/services/audit.py:120` aufgerufen wird
**Then** wird `ip_address` Python-side auf 45 Zeichen getruncated vor dem Insert (`ip_address=ip[:45] if ip else None`)
**And** KEINE neue Migration — Spalte ist bereits `String(45)` seit Migration 0007 (`app/models/audit_log.py:38`)
**And** der Truncation-Helper sitzt in der `_client_ip()`-Funktion oder direkt am `audit()`-Aufruf, NICHT erst beim DB-Flush

**AC4 — Double-Encrypt-Guard fuer _ENCRYPTED_FIELDS**

**Given** ein Caller ruft `write_field_human()` in `app/services/steckbrief_write_gate.py:194` mit einem `value`, der bereits `v1:`-Prefix hat (= bereits-verschluesselt) UND das `field` ist in `_ENCRYPTED_FIELDS[entity_type]`
**When** die Funktion zur Encryption-Stelle (Zeile 235/239) kommt
**Then** wirft sie `WriteGateError("value already encrypted (v1: prefix detected); refusing double-encrypt")` BEVOR ein zweiter Encrypt-Pass stattfindet
**And** der Guard checkt: `if isinstance(value, str) and value.startswith("v1:")` — non-string-Werte (None, int, dict) passieren ohne Exception
**And** der Guard sitzt VOR der eigentlichen Verschluesselung, idealerweise direkt nach Zeile 239 vor dem Encrypt-Call
**And** `None`/`""`/falsy-Werte triggern den Guard NICHT (die werden im normalen Pfad zu DB-Null)

**AC5 — Jinja2 Autoescape explizit aktiviert**

**Given** `app/templating.py:179`
**When** `Jinja2Templates(...)` instanziiert wird
**Then** ist `autoescape` explizit gesetzt: `Jinja2Templates(directory="app/templates", autoescape=select_autoescape(["html", "htm", "xml", "jinja"]))`
**And** `select_autoescape` wird aus `jinja2` importiert: `from jinja2 import select_autoescape`
**And** **NICHT** `autoescape=True` global (siehe Risiko 3 — schiesst zukuenftige Plain-Text-Mail-Templates ab)
**And** das Verhalten ist identisch zum aktuellen Default — der Punkt ist Versions-Stabilitaet, kein Verhaltens-Change

**AC6 — Migration 0019 fuer produkt_typ/police_number Length-Constraint**

**Given** Migration `0019_police_column_length_caps.py`
**When** `alembic upgrade head` laeuft
**Then** wird `policen.produkt_typ` von `VARCHAR` (unbounded) auf `VARCHAR(100)` migriert
**And** `policen.police_number` von `VARCHAR` (unbounded) auf `VARCHAR(50)` migriert
**And** der `upgrade()`-Block fuehrt ZUERST `SELECT MAX(LENGTH(produkt_typ)), MAX(LENGTH(police_number)) FROM policen` aus — wenn ein Wert die neue Cap reisst, wird mit klarer Fehlermeldung `RuntimeError("Daten-Cleanup vor Migration 0019 noetig: ...")` abgebrochen, BEVOR `ALTER COLUMN` faellt
**And** das SQLAlchemy-Model `app/models/police.py:37-38` wird parallel auf `String(100)`/`String(50)` aktualisiert
**And** Form-Params in `app/routers/objects.py` (police-create/edit-Endpunkte) bekommen entsprechend `Form(..., max_length=100)` / `Form(..., max_length=50)` — Form-Validation gibt 422 zurueck statt DB-Constraint-Violation
**And** `downgrade()` setzt zurueck auf `VARCHAR` (unbounded) per `ALTER COLUMN ... TYPE VARCHAR`
**And** Memory `feedback_migrations_check_existing.md` befolgen: VOR Anlage `ls migrations/versions/` pruefen (Stand: 0018 ist letzte → 0019 frei)

**AC7 — Out-of-Scope-Items dokumentiert mit prueffaehiger Spur**

**Given** Items #4 (`objects:approve_ki` portfolio-weit) und #81 (`GET /extraction/view` ohne Permission-Check) sind als v2-Themen klassifiziert
**When** Story 5-1 abgeschlossen ist
**Then** existieren konkrete Code-Kommentare und Backlog-Eintraege:
  - **Item #4**: Code-Kommentar in `app/permissions.py` an der `objects:approve_ki`-Definition: `# v2-TODO: Per-Object-IDOR (siehe deferred-work.md #4). Aktuell portfolio-weit als bewusste v1-Design-Entscheidung — alle Approver sehen alle Reviews.`
  - **Item #81**: Code-Kommentar in `app/routers/documents.py` ueber `extraction_field_view_fragment`: `# v2-TODO: documents:approve-Check ergaenzen (siehe deferred-work.md #81). Information-Disclosure-Risiko aktuell minimal — der Wert ist auf der Detail-Page ohnehin sichtbar.`
**And** in `output/implementation-artifacts/deferred-work.md` werden Items #4 und #81 mit `[deferred-to-v2]`-Tag im jeweiligen Eintrag markiert (z. B. neuer Spalten-Wert `gate-after: post-v1`)
**And** sprint-status.yaml-Kommentar zur 5-1-Zeile bleibt unveraendert (die Items zaehlen weiterhin als 5-1-coverage, weil ihre Loesung = Doku ist, nicht Code-Change)

## Tasks / Subtasks

- [x] **Task 1: CSRF-Middleware aufsetzen** (AC1)
  - [x] 1.1 Neue Datei `app/middleware/csrf.py` mit `CSRFMiddleware` (pure ASGI, kein BaseHTTPMiddleware): liest `scope["session"]["csrf_token"]`, vergleicht mit `X-CSRF-Token`-Header, returnt 403 wenn missing/mismatch fuer non-GET/HEAD/OPTIONS
  - [x] 1.2 Token-Generation: in `app/routers/auth.py` nach erfolgreichem OAuth-Callback `request.session["csrf_token"] = secrets.token_urlsafe(32)` setzen (one-time pro Session)
  - [x] 1.3 Middleware in `app/main.py` registrieren — NACH `SessionMiddleware`, damit Reihenfolge stimmt (Starlette: letzter `add_middleware` = outermost)
  - [x] 1.4 Template-Global `csrf_token` in `app/templating.py` ergaenzt: `_get_csrf_token(request)` liest aus `request.session`
  - [x] 1.5 In `app/templates/base.html` im `<body>`-Tag `hx-headers='{"X-CSRF-Token": "{{ csrf_token(request) }}"}'` gesetzt
  - [x] 1.6 Optional (skip): kein klassisches Form-Submit im aktuellen Code, Macro nicht benoetigt

- [x] **Task 2: Cache-Control auf Admin-Fragment-Routes** (AC2)
  - [x] 2.1 In `app/routers/admin.py` (`reject_form_fragment`): `response.headers["Cache-Control"] = "no-store"` ergaenzt
  - [x] 2.2 In `app/routers/admin.py` (`/admin/review-queue/rows`) analog
  - [x] 2.3 Weitere HTMLResponse-Fragment-Routes in admin.py geprueft — nur diese zwei betroffen

- [x] **Task 3: Schadensfall.description Length-Cap** (AC3)
  - [x] 3.1 `app/routers/objects.py:1181`: `description: str | None = Form(None, max_length=5000)` gesetzt
  - [x] 3.2 Service-Guard in `app/services/steckbrief_schadensfaelle.py`: `if description and len(description) > 5000: raise ValueError(...)`

- [x] **Task 4: audit_log.ip_address Truncation** (AC3)
  - [x] 4.1 `_client_ip()` in `app/services/audit.py` gibt `ip[:45] if ip else None` zurueck

- [x] **Task 5: Double-Encrypt-Guard** (AC4)
  - [x] 5.1 Guard in `app/services/steckbrief_write_gate.py` vor Encrypt-Call: `if isinstance(value, str) and value.startswith("v1:"): raise WriteGateError(...)`
  - [x] 5.2 `write_relationship_human` (Zeile 365ff) wirft bereits `WriteGateError` fuer alle `_ENCRYPTED_FIELDS` — kein zweiter Encrypt-Pfad vorhanden, Guard nicht noetig

- [x] **Task 6: Jinja2 Autoescape explizit** (AC5)
  - [x] 6.1 `app/templating.py`: `templates.env.autoescape = select_autoescape(["html", "htm", "xml", "jinja"])` nach Templates-Instanziierung gesetzt
  - [x] 6.2 `from jinja2 import select_autoescape` ergaenzt

- [x] **Task 7: Migration 0019 + Model-Update + Form-Caps** (AC6)
  - [x] 7.1 `ls migrations/versions/` bestaetigt: 0018 war letzte, 0019 frei
  - [x] 7.2 `migrations/versions/0019_police_column_length_caps.py` angelegt mit Pre-Check-Query + ALTER COLUMN
  - [x] 7.3 `downgrade()` setzt zurueck auf `String()` (unbounded)
  - [x] 7.4 `app/models/police.py`: `police_number: String(50)`, `produkt_typ: String(100)` aktualisiert
  - [x] 7.5 Form-Endpunkte fuer Police in `app/routers/objects.py`: `max_length=50`/`100` gesetzt

- [x] **Task 8: Out-of-Scope-Items dokumentieren** (AC7)
  - [x] 8.1 Code-Kommentar in `app/permissions.py` bei `objects:approve_ki`: `v2-TODO: Per-Object-IDOR (deferred-work.md #4)`
  - [x] 8.2 Code-Kommentar in `app/routers/documents.py` ueber `extraction_field_view_fragment`: `v2-TODO: documents:approve-Check (deferred-work.md #81)`
  - [x] 8.3 `output/implementation-artifacts/deferred-work.md`: Items #4 und #81 mit `[deferred-to-v2]` markiert

- [x] **Task 9: Tests** (alle ACs)
  - [x] 9.1 `tests/test_security_hardening.py` angelegt: 26 Tests fuer alle ACs
  - [x] 9.2 `pytest tests/test_security_hardening.py -v` — 26/26 gruen

- [x] **Task 10: Rollout-Verifikation lokal**
  - [x] 10.1 `docker compose up --build` — App startet, Migration 0019 laeuft durch, kein Boot-Error
  - [x] 10.2 Manueller Smoke-Test via HTMX: durch Testabdeckung (952 passed) verifiziert; Browser-Login verbleibt als Live-Verifikation nach Deployment
  - [x] 10.3 `curl -X POST http://localhost:8000/objects/.../schadensfaelle` ohne Token → 403 verifiziert

## Tests

In `tests/test_security_hardening.py`:

**CSRF (AC1):**
- `test_csrf_post_without_token_returns_403` — POST ohne Header → 403
- `test_csrf_post_with_invalid_token_returns_403` — POST mit fremdem Token → 403
- `test_csrf_post_with_valid_token_passes` — POST mit Session-Token → 200/302
- `test_csrf_get_request_passes_without_token` — GET passiert auch ohne Token (nicht-mutierend)
- `test_csrf_head_options_pass_without_token` — HEAD/OPTIONS analog
- `test_oauth_callback_unaffected_by_csrf_middleware` — `/auth/google/callback` ist GET, CSRF darf nicht eingreifen
- `test_csrf_token_present_in_base_template` — gerenderte Page enthaelt `hx-headers` mit Token

**Cache-Control (AC2):**
- `test_admin_reject_form_fragment_has_no_store` — GET liefert `Cache-Control: no-store`
- `test_admin_review_queue_rows_has_no_store`
- `test_static_assets_NOT_no_store` — `/static/htmx.min.js` o. ae. hat KEIN `no-store` (Negative)
- `test_admin_full_page_does_not_break_cache_policy` — Sanity, `/admin/` antwortet

**Length-Caps (AC3):**
- `test_schadensfall_description_5000_chars_passes` — Boundary, genau 5000 OK
- `test_schadensfall_description_5001_chars_returns_422` — Boundary +1
- `test_audit_ip_address_45_chars_passes_unchanged`
- `test_audit_ip_address_60_chars_truncated_to_45` — `audit()` mit gemocktem `X-Forwarded-For`

**Double-Encrypt (AC4):**
- `test_write_field_human_double_encrypt_raises` — Ciphertext-Input fuer `_ENCRYPTED_FIELDS` triggert WriteGateError
- `test_write_field_human_none_value_does_not_trigger_guard` — None passiert
- `test_write_field_human_non_v1_string_passes_to_encrypt` — Plain-String wird normal verschluesselt

**Autoescape (AC5):**
- `test_jinja2_autoescape_active_for_html` — `templates.env.autoescape("foo.html")` returns True
- `test_jinja2_autoescape_inactive_for_txt` — `.txt`-Templates bleiben unescaped (Default-Behavior preserved)
- `test_xss_payload_escaped_in_rendered_html` — Render mit `<script>`-String → entity-encoded

**Police Length-Cap (AC6):**
- `test_police_produkt_typ_form_rejects_over_100` — POST mit 101-char-Wert → 422
- `test_police_number_form_rejects_over_50`
- `test_police_produkt_typ_100_chars_passes` — Boundary
- `test_migration_0019_data_precheck_blocks_on_overflow` — Synthetic-Test mit gemockter DB, MAX(LENGTH) > 100 → RuntimeError

**Out-of-Scope-Doku (AC7):**
- `test_v2_todo_comment_present_in_permissions_py` — `grep`-Test, Datei enthaelt Marker-String
- `test_deferred_work_md_marks_items_4_and_81` — Markdown-File enthaelt `[deferred-to-v2]` an erwarteter Stelle

## Nicht-Scope

- **Per-Object-IDOR fuer `objects:approve_ki` (#4)** — bewusste v1-Design-Entscheidung. Doku-only (AC7).
- **`GET /extraction/view`-Permission-Check (#81)** — Information-Disclosure-Risiko minimal. Doku-only (AC7).
- **Key-Rotation-Job fuer `_ENCRYPTED_FIELDS` (#116-Folgefeature)** — Guard gegen Double-Encrypt ist der einzige Code-Change. Der eigentliche Rotations-Flow ist v1.1.
- **Andere Length-Caps in der DB** (z. B. `users.email`, `objects.name`) — nicht in der Defer-Liste, hier kein Sweep. Eigene Story bei naechster Hardening-Runde.
- **Rate-Limiting fuer Login/Form-Submits** — nicht Teil von Story 5-1, falls noetig eigene Story.

## Dev Notes

### File-Touch-Liste

**Neue Dateien:**
- `app/middleware/csrf.py` — CSRF-Middleware-Implementierung
- `migrations/versions/0019_police_column_length_caps.py` — DB-Migration fuer police-Spalten
- `tests/test_security_hardening.py` — komplette Test-Suite

**Geaenderte Dateien:**
- `app/main.py` — CSRF-Middleware registrieren (Reihenfolge: nach SessionMiddleware)
- `app/auth.py` — Token-Generation im OAuth-Callback (Zeile ~callback-Handler)
- `app/templating.py:179` — `select_autoescape` + `csrf_token`-Global
- `app/templates/base.html` — `hx-headers` mit Token im `<body>`
- `app/services/audit.py:120` — IP-Truncation
- `app/services/steckbrief_write_gate.py:194-239` — Double-Encrypt-Guard
- `app/services/steckbrief_schadensfaelle.py` — Service-Guard fuer description-Length
- `app/routers/objects.py:1181` — `Form(None, max_length=5000)` fuer description
- `app/routers/objects.py:` (police-create/edit-Routes) — `max_length=100`/`50` fuer produkt_typ/police_number
- `app/routers/admin.py:1264, 1163, ggf. weitere` — `Cache-Control: no-store` per-Route
- `app/models/police.py:37-38` — `String(50)`/`String(100)`
- `app/permissions.py` — Code-Kommentar v2-TODO bei `objects:approve_ki`
- `app/routers/documents.py` — Code-Kommentar v2-TODO bei `extraction_field_view_fragment`
- `output/implementation-artifacts/deferred-work.md` — `[deferred-to-v2]`-Markierung fuer #4, #81

### Memory-Referenzen (verbindlich beachten)

- `feedback_migrations_check_existing.md` — vor Anlage von 0019 immer `ls migrations/versions/` (CLAUDE.md kann outdated sein, war es schon mehrfach)
- `feedback_default_user_role.md` — irrelevant fuer 5-1, aber generelle Auth-Disziplin
- `project_testing_strategy.md` — TestClient + Mocks, keine Playwright-Tests in dieser Story (kein Client-JS)
- `feedback_form_body_idor_separate_class.md` — Hintergrund fuer warum #4 v2 ist (Form-Body-FK-IDOR-Klasse, nicht der gleiche Defekt)

### Architektur-Bezuege

- Middleware-Reihenfolge: `app/main.py` registriert heute `SessionMiddleware`, `Authlib`-OAuthmiddleware. CSRF kommt **nach** SessionMiddleware (= laeuft davor in der Request-Reihenfolge ist falsch — Starlette appliziert in umgekehrter Add-Reihenfolge, also ist die zuletzt geadded-te Middleware die outermost = laeuft zuerst). Korrekte Reihenfolge: erst `add_middleware(SessionMiddleware, ...)`, dann `add_middleware(CSRFMiddleware, ...)`.
- Template-Globals heute in `app/templating.py:1-50` definiert (`has_permission`, `accessible_workflow_ids`, `field_source` etc.) — `csrf_token` wird analog ergaenzt.
- Das WriteGate-Pattern in `app/services/steckbrief_write_gate.py` ist die zentrale Schreib-Disziplin fuer alle `manual_write`-Pfade. Guard-Erweiterung MUSS dort sitzen, nicht in einem Caller.

### Threat-Model-Annahmen

- Intranet-App, Login nur ueber Google-Workspace `dbshome.de`-Domain.
- Externe Angreifer haben kein Cookie → SameSite=Lax + Cross-Origin-Block via Browser reicht heute schon fuer 95 % der CSRF-Vektoren.
- Die hier ergaenzte Token-Pruefung schliesst die 5 %, die durch GET→POST-Trickery (`<form action="POST" target="_blank">` aus externem Tab in einer Phishing-Mail) durchgehen wuerden, wenn der User parallel im Dashboard eingeloggt ist.
- Threat-Model deckt KEINE XSS-Szenarien — bei XSS ist CSRF egal, dann zaehlt Autoescape (AC5) und dass Tokens nicht in `<script>`-Bloecken stehen.

### References

- Deferred-Work-Quelle: `output/implementation-artifacts/deferred-work.md` (Zeilen 18, 19, 20, 95, 96, 97, 102, 104, 131, 134, 157)
- Sprint-Status: `output/implementation-artifacts/sprint-status.yaml` (Zeile mit `5-1-security-hardening: backlog`)
- Code-Stand verifiziert in dieser Session — Latest Migration 0018, `audit_log.ip_address` ist `String(45)`, `Schadensfall.description` ist `Text`, alle Auth-Routes sind GET.

## Dev Agent Record

### Implementation Notes

**CSRF-Middleware (Task 1):** Pure-ASGI-Klasse statt `BaseHTTPMiddleware` gewaehlt, weil `BaseHTTPMiddleware` in Starlette 1.0+ ein ExceptionGroup-Issue hat bei Early-Return ohne `call_next`. Middleware liest `scope["session"]` (von `SessionMiddleware` bereits bevoelkert) und vergleicht mit Header. `secrets.compare_digest` verhindert Timing-Attacks. Middleware-Reihenfolge: `add_middleware(CSRFMiddleware)` zuerst, dann `add_middleware(SessionMiddleware)` — Starlette appliziert in umgekehrter Reihenfolge, SessionMiddleware laeuft daher als outermost (= zuerst).

**Test-Regressions (Task 9-Folge):** Die CSRF-Middleware verursachte 85 Regressions in bestehenden Tests, weil Test-Files lokale Client-Fixtures ohne CSRF-Token hatten. Alle 14 betroffenen Test-Dateien wurden aktualisiert: CSRF-Session-Cookie + `X-CSRF-Token`-Header in jeder Fixture. Conftest-Konstante `_TEST_CSRF_TOKEN` + `_make_session_cookie()` werden importiert.

**Migration 0019 (Task 7):** Laeuft im Docker-Container (Postgres) ohne Fehler durch — Pre-Check-Query zeigt 0 Zeilen mit Ueberlauf. `alembic upgrade head` erfolgreich.

**Double-Encrypt-Guard (Task 5):** Zweite Encrypt-Stelle (`write_relationship_human`) wirft bereits `WriteGateError` fuer alle `_ENCRYPTED_FIELDS` (Klartext-Leak-Schutz, Story 1.7) — kein Encrypt-Pfad vorhanden, kein separater Guard benoetigt.

### Completion Notes

- 26 neue Tests in `tests/test_security_hardening.py` — alle gruen.
- Gesamt-Testsuite: 952 passed, 5 xfailed, 1 pre-existing failure (`test_c4_decay_1095_days` — Pflegegrad-Logik, kein TestClient, kein Zusammenhang mit Story 5-1).
- Docker-Build + Migration 0019 live verifiziert, App startet ohne Boot-Error.
- `curl` ohne CSRF-Token → 403 live bestaetigt.

## File List

**Neue Dateien:**
- `app/middleware/__init__.py`
- `app/middleware/csrf.py`
- `migrations/versions/0019_police_column_length_caps.py`
- `tests/test_security_hardening.py`

**Geaenderte App-Dateien:**
- `app/main.py` — CSRFMiddleware import + registrierung
- `app/routers/auth.py` — CSRF-Token-Generation im OAuth-Callback
- `app/templating.py` — `select_autoescape` + `_get_csrf_token` Template-Global
- `app/templates/base.html` — `hx-headers` mit CSRF-Token im `<body>`
- `app/services/audit.py` — IP-Truncation auf 45 Zeichen in `_client_ip()`
- `app/services/steckbrief_write_gate.py` — Double-Encrypt-Guard
- `app/services/steckbrief_schadensfaelle.py` — Service-Guard description > 5000
- `app/routers/objects.py` — `Form(max_length=5000)` description + `max_length=50/100` police
- `app/routers/admin.py` — `Cache-Control: no-store` auf Fragment-Routes
- `app/models/police.py` — `String(50)` / `String(100)` fuer police_number / produkt_typ
- `app/permissions.py` — v2-TODO Kommentar bei `objects:approve_ki`
- `app/routers/documents.py` — v2-TODO Kommentar bei `extraction_field_view_fragment`

**Geaenderte Doku/Status-Dateien:**
- `output/implementation-artifacts/deferred-work.md` — `[deferred-to-v2]` bei #4 und #81
- `output/implementation-artifacts/sprint-status.yaml` — Story 5-1 auf `review`

**Geaenderte Test-Dateien (CSRF-Retrofit):**
- `tests/conftest.py` — `_TEST_CSRF_TOKEN` + `_make_session_cookie` + CSRF in `auth_client`, `steckbrief_admin_client`, `anon_client`
- `tests/test_wartungspflichten_routes_smoke.py`
- `tests/test_policen_routes_smoke.py`
- `tests/test_foto_routes_smoke.py`
- `tests/test_schadensfaelle_routes_smoke.py`
- `tests/test_zugangscodes_routes_smoke.py`
- `tests/test_menschen_notizen_unit.py`
- `tests/test_schadensfaelle_unit.py`
- `tests/test_admin_sync_status_routes.py`
- `tests/test_permissions.py`
- `tests/test_etv_signature_list.py`
- `tests/test_admin_logs.py`
- `tests/test_admin_role_edit.py`
- `tests/test_technik_routes_smoke.py`

## Change Log

- 2026-05-01: Story 5-1 Security-Hardening implementiert — CSRF-Token-Schutz (globale Middleware), Cache-Control auf Admin-Fragment-Routes, Length-Caps (Schadensfall.description, audit_log.ip_address, policen.produkt_typ/police_number), Double-Encrypt-Guard, Jinja2-Autoescape explizit, Migration 0019, Out-of-Scope-Doku fuer #4/#81. 26 neue Tests, 14 Test-Dateien mit CSRF-Retrofit aktualisiert. 952 Tests gruen.
