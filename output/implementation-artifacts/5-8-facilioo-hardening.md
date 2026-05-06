# Story 5.8: Facilioo-Hardening

Status: ready-for-dev

## Story

Als Entwickler der Plattform
möchte ich die 7 aufgelaufenen Facilioo-Hardening-Findings aus dem 4-4-Code-Review sowie Item #6 (view-only Reviewer) schliessen,
damit die Facilioo-Ticket-Sektion robust gegen Edge-Cases ist und die Review-Queue einem read-only Reviewer zugänglich gemacht werden kann.

## Hintergrund

Epic 4 brachte die Facilioo-Ticket-Integration live. Der Code-Review zu Story 4-4 hinterliess 6 Low-/Medium-Findings, die als „post-prod technische Schulden" markiert wurden. Dazu kommt Item #6 (view-only Reviewer) aus dem 3-6-Code-Review: die Review-Queue ist heute ausschliesslich über `objects:approve_ki` erreichbar — Lesen und Entscheiden sind dieselbe Permission-Schicht. Diese Story schliesst alle 7 Punkte ohne neue Features.

**Betroffene Dateien (primär):**
- `app/services/facilioo_tickets.py` — AC1–AC4 (4 Code-Fixes)
- `app/config.py` — AC5 (Schema-Validator)
- `output/implementation-artifacts/4-4-facilioo-tickets-am-objekt-detail.md` — AC6 (Spec-Wortlaut, kein App-Code)
- `app/permissions.py`, `app/routers/admin.py`, `app/templates/base.html` — AC7 (view-only Reviewer)
- `tests/test_object_facilioo_section.py` — neue Tests für AC1–AC5, AC7

**Vorbedingung:** Stories 5-1 bis 5-7 sind committed. Migrations-Stand: `0020_resource_access_unique.py` (revision `"0020"`) und `0020_perf_indexes.py` (revision `"0020_perf_indexes"`) zeigen beide auf `0019` als down_revision — das ist ein **echter Multi-Head-Zustand** in Alembic, vorbestehend aus Story 5-2/5-4. Tests laufen über `Base.metadata.create_all`, daher fällt das in der Test-Suite nicht auf; Prod-Deploys laufen aktuell ebenfalls durch (zu prüfen). **Story 5-8 berührt das nicht** — keine neue Migration nötig.

**Scope-Grenze:** Keine neuen Features. Alle App-Code-Änderungen sind gezielte Fixes in bestehenden Funktionen. AC7 fügt eine neue Permission hinzu, aber **keine Migration** — `_seed_default_roles()` in `main.py:238` macht ein additives Merge bei jedem Deploy, neue Default-Keys kommen automatisch mit.

---

## Acceptance Criteria

### AC1 — NULL-Status-Tickets im Filter einschliessen

**Deferred:** 4-4-CR „NULL-Status-Tickets fallen aus dem Filter" [`app/services/facilioo_tickets.py:48`]

**Given** ein `FaciliooTicket` mit `status=None` (nullable Spalte, erlaubt vom Model) liegt in der DB für ein Objekt

**When** `get_open_tickets_for_object(db, object_id)` aufgerufen wird

**Then**:
- Das NULL-Status-Ticket erscheint in der Rückgabeliste (wird **nicht** durch `notin_()` gefiltert)
- Tickets mit Status `"finished"`, `"deleted"`, `"closed"`, `"resolved"`, `"done"` erscheinen weiterhin **nicht**
- Der Filter lautet danach: `or_(FaciliooTicket.status.is_(None), FaciliooTicket.status.notin_(_CLOSED_STATUS_VALUES))`
- `or_` wird oben im Import aus `sqlalchemy` ergänzt

**Test:** `test_null_status_ticket_included` in `tests/test_object_facilioo_section.py`

---

### AC2 — Sort-Tiebreaker für Tickets ergänzen

**Deferred:** 4-4-CR „Sortier-Tiebreaker fehlt" [`app/services/facilioo_tickets.py:50`]

**Given** zwei `FaciliooTicket`-Einträge mit exakt gleichen `created_at`-Timestamps

**When** `get_open_tickets_for_object` mehrfach aufgerufen wird

**Then**:
- Die Reihenfolge der Einträge ist deterministisch (kein Flackern bei identischen Timestamps)
- `order_by` lautet: `.order_by(FaciliooTicket.created_at.desc(), FaciliooTicket.id.desc())`

**Test:** `test_sort_tiebreaker_stable` — erstellt zwei Tickets mit identischem Timestamp, ruft die Funktion zweimal auf, prüft `rows_a == rows_b` (gleiche ID-Reihenfolge).

---

### AC3 — URL-Encoding für facilioo_id im Deeplink

**Deferred:** 4-4-CR „`facilioo_id` ohne `urllib.parse.quote()` im Deeplink" [`app/services/facilioo_tickets.py:140`]

**Given** eine `facilioo_id`, die theoretisch Sonderzeichen enthalten könnte (defensives Hardening)

**When** `facilioo_ticket_url(facilioo_id)` aufgerufen wird

**Then**:
- Sonderzeichen im `facilioo_id`-Segment werden percent-encoded
- Import `from urllib.parse import quote` wird oben in `facilioo_tickets.py` ergänzt
- `return f"{base}/tickets/{quote(str(facilioo_id), safe='')}"` — `safe=""` ist zwingend, weil Pythons `quote()`-Default `safe="/"` ist und `/` sonst unkodiert bleibt
- `facilioo_ticket_url(None)` und `facilioo_ticket_url("")` geben weiterhin `"#"` zurück (bestehende Logik unverändert)

**Test:** `test_facilioo_ticket_url_encodes_special_chars` — ruft `facilioo_ticket_url("ticket/with spaces?foo=bar")` auf, prüft dass `%2F`, `%20`, `%3F` im Ergebnis vorhanden sind und kein Literal `/` im Path-Segment nach `/tickets/`.

---

### AC4 — JSONB-cast LIKE mit Key-Anchor präzisieren

**Deferred:** 4-4-CR „JSONB-cast+LIKE matcht ohne Key-Anchor" [`app/services/facilioo_tickets.py:73-75`]

**Given** ein `AuditLog`-Eintrag mit `action="sync_finished"` und `details_json={"job": "andere_job_id", "facilioo_ticket_mirror_stats": {...}}` (enthält den String `"facilioo_ticket_mirror"` in einem anderen Key)

**When** `get_last_facilioo_sync(db)` aufgerufen wird

**Then**:
- Der falsch-positive Eintrag wird **nicht** zurückgegeben (Key-Anchor verhindert den Treffer)
- Das LIKE-Pattern lautet: `'%"job": "facilioo_ticket_mirror"%'`
- **Kein Postgres-spezifischer JSONB-Operator** — das cast+LIKE bleibt für SQLite-Portabilität
- Ein Eintrag mit `details_json={"job": "facilioo_ticket_mirror", "run_id": "..."}` wird weiterhin korrekt gefunden

**Technischer Hintergrund:** Python's `json.dumps()` serialisiert Dicts in Einfüge-Reihenfolge (CPython ≥ 3.7). `AuditLog`-Einträge vom Mirror werden stets als `{"job": "facilioo_ticket_mirror", ...}` geschrieben, sodass `"job": "facilioo_ticket_mirror"` ein zuverlässiger Key-Anchor ist. Bei SQLite (Tests) wird der JSONB-Wert als Text gespeichert und ebenfalls durch `like()` gematcht.

**Test:** `test_get_last_sync_ignores_other_job` — legt einen Audit-Eintrag mit `{"job": "other_job", "note": "facilioo_ticket_mirror"}` an, prüft dass `get_last_facilioo_sync()` `None` zurückgibt.

---

### AC5 — Pydantic-Validator für facilioo_ui_base_url

**Deferred:** 4-4-CR „`facilioo_ui_base_url` ohne Schema-Validator" [`app/config.py:59`]

**Given** `facilioo_ui_base_url` ist ein freies `str`-Feld in `Settings`

**When** AC5 implementiert ist

**Then**:
- `app/config.py` importiert `field_validator` von `pydantic` (Pydantic v2)
- Ein `@field_validator("facilioo_ui_base_url")` prüft: `v.startswith("http://") or v.startswith("https://")`
- Bei ungültigem Wert (z.B. `""`, `"app.facilioo.de"`) raised der Validator `ValueError` mit klarer Meldung
- Der Default-Wert `"https://app.facilioo.de"` passiert den Validator (kein Startup-Fehler)
- `@field_validator` ist `mode="after"` (Default) — wird nach Typ-Parsing aufgerufen

**Pydantic-v2-Pattern (Projekt-Standard aus `project-context.md`):**
```python
from pydantic import field_validator

@field_validator("facilioo_ui_base_url")
@classmethod
def _validate_facilioo_ui_base_url(cls, v: str) -> str:
    if not v.startswith(("http://", "https://")):
        raise ValueError("facilioo_ui_base_url muss mit http:// oder https:// beginnen")
    return v
```

**Test:** `test_facilioo_ui_base_url_validator` — nicht via `Settings()`-Konstruktor (braucht `.env`), sondern direkt: ruft die Classmethod `Settings._validate_facilioo_ui_base_url("no-schema")` auf und prüft `pytest.raises(ValueError)`. Hinweis: dieses Pattern ist bisher noch nicht in der Codebase etabliert — `field_validator` wird hier zum ersten Mal genutzt. Falls der direkte Aufruf an Pydantic-v2-Internals scheitert, alternativ via `Settings.model_validate({...})` mit `pytest.raises(pydantic.ValidationError)` testen.

---

### AC6 — AC1-Spec-Wortlaut in 4-4-Story-Datei korrigieren

**Deferred:** 4-4-CR „AC1-Spec-Wortlaut driftet von Implementation" [`output/implementation-artifacts/4-4-facilioo-tickets-am-objekt-detail.md:47`]

**Given** Story-Datei `4-4-facilioo-tickets-am-objekt-detail.md` enthält in AC1 den Wortlaut „und mind. {{ extra_count }} weiteres in Facilioo", die Implementation rendert aber „Weitere offene Vorgänge in Facilioo." ohne Zahl

**When** AC6 abgehakt ist

**Then**:
- In `output/implementation-artifacts/4-4-facilioo-tickets-am-objekt-detail.md`, AC1 wird um eine Klarstellung ergänzt: die Zahl wird **nicht** angezeigt (Limit-Cap-Pattern: `LIMIT cap+1` kennt die echte Anzahl nicht), der Wortlaut „Weitere offene Vorgänge in Facilioo." ist die korrekte Implementation
- **Kein App-Code-Change** — nur die Story-Datei wird angepasst
- **Kein Test nötig**

---

### AC7 — view-only Reviewer (Permission-Splitting)

**Deferred:** Code-Review 3-6 Item #6 „Single-Permission-Tier (kein view-only Reviewer)"

**Given** heute sind Lesen der Review-Queue und Entscheiden (Approve/Reject) hinter derselben Permission `objects:approve_ki` versteckt

**When** AC7 implementiert ist

**Then**:

**permissions.py:**
- Neue Permission `objects:view_review_queue` mit Beschreibung `"Review-Queue ansehen (read-only)"`, Gruppe `"Objekte"`, eingefügt **vor** `objects:approve_ki` (logische Reihenfolge: erst sehen, dann entscheiden)
- `DEFAULT_ROLE_PERMISSIONS["admin"]` und `DEFAULT_ROLE_PERMISSIONS["user"]` enthalten `"objects:view_review_queue"`
- `_seed_default_roles()` addiert die neue Permission automatisch bei nächstem Start — **keine Migration nötig**

**Wichtig — Design-Entscheidung Default-Rollen:**
- Die Default-`user`-Rolle behält `objects:approve_ki` (kein Downgrade bestehender User auf read-only)
- Die Default-`admin`-Rolle hat ohnehin alle Keys via `sorted(PERMISSION_KEYS)`
- Ein **echter view-only Reviewer** entsteht durch eine **separate Custom-Rolle** (z.B. `reviewer_readonly`), die der Admin manuell über `/admin/roles` anlegt mit nur `objects:view` + `objects:view_review_queue`
- AC7 macht den view-only-Fall **technisch möglich** (Permission existiert + Routes/Sidebar respektieren sie), erzwingt ihn aber nicht über die System-Defaults

**admin.py:**
- `list_review_queue` (GET `/review-queue`) → `require_permission("objects:view_review_queue")`
- `list_review_queue_rows` (GET `/review-queue/rows`) → `require_permission("objects:view_review_queue")`
- `approve_entry` (POST `/review-queue/{id}/approve`) → bleibt `require_permission("objects:approve_ki")`
- `reject_entry` (POST `/review-queue/{id}/reject`) → bleibt `require_permission("objects:approve_ki")`
- `reject_form_fragment` (GET `/review-queue/{id}/reject-form`) → bleibt `require_permission("objects:approve_ki")`

**base.html:**
- Sidebar-Link `/admin/review-queue` wird angezeigt wenn `has_permission(user, "objects:view_review_queue")` (statt bisher `objects:approve_ki`)

**Tests** in neuem `tests/test_review_queue_permission_split.py`:
- `test_view_review_queue_without_approve_ki` — User hat nur `objects:view_review_queue`, kein `approve_ki`: `GET /admin/review-queue` → 200 (oder Redirect zu Login ist falsch — 200 erwartet)
- `test_approve_blocked_without_approve_ki` — gleicher User: `POST /admin/review-queue/{id}/approve` → 403
- `test_reject_blocked_without_approve_ki` — gleicher User: `POST /admin/review-queue/{id}/reject` → 403
- bestehende Tests in `test_review_queue_routes_smoke.py` bleiben grün

---

## Dev Notes

### Datei-Übersicht: was wo geändert wird

| Datei | AC | Art |
|-------|-----|-----|
| `app/services/facilioo_tickets.py` | AC1–AC4 | Code-Fixes |
| `app/config.py` | AC5 | `field_validator` ergänzen |
| `output/implementation-artifacts/4-4-facilioo-tickets-am-objekt-detail.md` | AC6 | Wortlaut-Fix (kein App-Code) |
| `app/permissions.py` | AC7 | neue Permission + Default-Roles |
| `app/routers/admin.py` | AC7 | 2× Permission-String ändern |
| `app/templates/base.html` | AC7 | Sidebar-Condition ändern |
| `tests/test_object_facilioo_section.py` | AC1–AC5 | neue Tests |
| `tests/test_review_queue_permission_split.py` | AC7 | neue Test-Datei |

### AC1 — Fix-Snippet facilioo_tickets.py

```python
# Vorher (Zeile 12):
from sqlalchemy import cast, String, literal, select

# Nachher:
from sqlalchemy import cast, or_, String, literal, select

# Vorher (Zeile 44–55, get_open_tickets_for_object):
.where(
    FaciliooTicket.object_id == object_id,
    FaciliooTicket.is_archived.is_(False),
    FaciliooTicket.status.notin_(_CLOSED_STATUS_VALUES),
)
.order_by(FaciliooTicket.created_at.desc())

# Nachher:
.where(
    FaciliooTicket.object_id == object_id,
    FaciliooTicket.is_archived.is_(False),
    or_(FaciliooTicket.status.is_(None), FaciliooTicket.status.notin_(_CLOSED_STATUS_VALUES)),
)
.order_by(FaciliooTicket.created_at.desc(), FaciliooTicket.id.desc())
```

(AC1 = `or_()`, AC2 = `.id.desc()` — beide in einem `where`/`order_by`-Block, ein Commit reicht.)

### AC3 — Fix-Snippet facilioo_tickets.py

```python
# Import oben ergänzen:
from urllib.parse import quote

# facilioo_ticket_url():
# Vorher:
return f"{base}/tickets/{facilioo_id}"
# Nachher (safe="" ist Pflicht — Default-safe="/" würde `/` unkodiert lassen):
return f"{base}/tickets/{quote(str(facilioo_id), safe='')}"
```

### AC4 — Fix-Snippet facilioo_tickets.py

```python
# Vorher (Zeile 75):
cast(AuditLog.details_json, String).like('%"facilioo_ticket_mirror"%'),

# Nachher:
cast(AuditLog.details_json, String).like('%"job": "facilioo_ticket_mirror"%'),
```

### AC5 — Pydantic-v2-Validator in config.py

Imports in `app/config.py` sind aktuell `from pydantic_settings import BaseSettings, SettingsConfigDict` — kein `pydantic`-Import. Ergänzen:

```python
from pydantic import field_validator
```

Validator-Methode **innerhalb** der `Settings`-Klasse, nach dem letzten Feld-Eintrag, vor dem Klassenende:

```python
@field_validator("facilioo_ui_base_url")
@classmethod
def _validate_facilioo_ui_base_url(cls, v: str) -> str:
    if not v.startswith(("http://", "https://")):
        raise ValueError("facilioo_ui_base_url muss mit http:// oder https:// beginnen")
    return v
```

### AC5 — Test-Ansatz

Direkter Methodenaufruf ist am einfachsten (kein dotenv-Overhead):

```python
import pytest
from app.config import Settings

def test_facilioo_ui_base_url_validator_rejects_no_schema():
    with pytest.raises(Exception):  # ValidationError oder ValueError
        Settings._validate_facilioo_ui_base_url("app.facilioo.de")

def test_facilioo_ui_base_url_validator_accepts_https():
    result = Settings._validate_facilioo_ui_base_url("https://app.facilioo.de")
    assert result == "https://app.facilioo.de"
```

Falls der direkte Aufruf wegen Pydantic-v2-Internals nicht funktioniert: `Settings.model_validate({..., "facilioo_ui_base_url": "bad"})` mit `pytest.raises(pydantic.ValidationError)` — aber Achtung: `model_validate` löst alle `env_file`-Reads aus, daher lieber `Settings.__validators__`-Lookup oder Mock von `settings.facilioo_ui_base_url` post-instantiation prüfen.

**Empfehlung**: Classmethod direkt testen — kein dotenv-Overhead, kein Pflichtfeld-Setup nötig. Dies wird das erste Validator-Unit-Test-Pattern in der Codebase und kann als Vorbild für künftige Settings-Validatoren dienen.

### AC7 — permissions.py Änderung

```python
# Nach Permission("objects:edit", ...):
Permission("objects:view_review_queue", "Review-Queue ansehen (read-only)", "Objekte"),
Permission("objects:approve_ki", "KI-Vorschläge freigeben", "Objekte"),

# DEFAULT_ROLE_PERMISSIONS["user"] — "objects:view_review_queue" ergänzen:
"user": sorted([
    ...,
    "objects:view_review_queue",
    "objects:approve_ki",
    ...
])
# admin bekommt alle Keys automatisch via sorted(PERMISSION_KEYS)
```

### AC7 — admin.py Änderung

Nur zwei Zeilen ändern (list_review_queue und list_review_queue_rows):
```python
# Vorher:
user: User = Depends(require_permission("objects:approve_ki")),
# Nachher (in list_review_queue und list_review_queue_rows):
user: User = Depends(require_permission("objects:view_review_queue")),
```

`approve_entry`, `reject_entry`, `reject_form_fragment` bleiben unverändert auf `objects:approve_ki`.

### AC7 — base.html Änderung

```html
<!-- Vorher (Zeile ~124): -->
{% if has_permission(user, "objects:approve_ki") %}
{% set active = path.startswith("/admin/review-queue") %}
<a href="/admin/review-queue" ...>

<!-- Nachher: -->
{% if has_permission(user, "objects:view_review_queue") %}
{% set active = path.startswith("/admin/review-queue") %}
<a href="/admin/review-queue" ...>
```

### AC7 — Test-Hilfsmittel

Vorbild für Permission-Override-Client ist `tests/test_object_facilioo_section.py::view_only_client`. Für AC7 einen `view_review_queue_client` bauen:

```python
@pytest.fixture
def view_review_queue_client(db):
    """Client mit objects:view_review_queue aber OHNE objects:approve_ki."""
    from fastapi.testclient import TestClient
    from app.auth import get_current_user, get_optional_user
    from app.db import get_db
    from app.main import app
    from app.models import User

    user = User(
        id=uuid.uuid4(),
        email="viewer@test.de",
        permissions_extra=["objects:view_review_queue"],
        permissions_denied=["objects:approve_ki"],
    )
    db.add(user)
    db.commit()

    def _get_user():
        return user

    def _get_db():
        yield db

    app.dependency_overrides[get_current_user] = _get_user
    app.dependency_overrides[get_optional_user] = _get_user
    app.dependency_overrides[get_db] = _get_db
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()
```

**Achtung:** `permissions_denied` überschreibt Rolle-Defaults. Der User braucht zusätzlich `objects:view` damit Admin-Bereich zugänglich ist (oder die Tests prüfen nur den direkten Endpoint-Status ohne Sidebar-Check).

### Keine Migration nötig

`_seed_default_roles()` in `main.py:238` macht `set(existing.permissions) | set(new_defaults)` — sobald `objects:view_review_queue` in `DEFAULT_ROLE_PERMISSIONS` steht, wird es beim nächsten App-Start automatisch zu allen bestehenden `admin`- und `user`-Rollen hinzugefügt.

### Migration-Präfix für diese Story

Falls doch eine Migration entsteht (z.B. für einen Hotfix): Präfix `0021_` verwenden und **explizit** down_revision auf den gewünschten Vorgänger setzen. Achtung — Alembic-History ist aktuell in einem Multi-Head-Zustand: `0020_resource_access_unique` (revision `"0020"`) und `0020_perf_indexes` (revision `"0020_perf_indexes"`) zeigen beide auf `0019`. Eine neue 0021-Migration müsste entweder via `alembic merge` beide Heads zusammenführen oder den Multi-Head bewusst auf einen Branch fixieren. Für Story 5-8 nicht relevant (keine Migration), aber bei nächster Migration zu lösen.

### Commit-Strategie (empfohlen)

1. AC1+AC2+AC3+AC4 (alle `facilioo_tickets.py`-Fixes in einem Commit)
2. AC5 (config.py Validator)
3. AC6 (Story-Datei-Fix)
4. AC7 (Permission-Split + Tests)

Tests können zusammen mit dem jeweiligen Fix committed werden.

---

## Aus 5-7 (Test-Coverage) gelernt

- **Validator direkt testen** ist sauberer als Settings-Instantiation mit `model_validate` (Env-Overhead vermeiden)
- **`_make_ticket`-Helper** in `test_object_facilioo_section.py` ist schon vorhanden — für AC1-Tests erweitern, nicht neu erfinden. `status=None` muss als explizites kwarg übergeben werden (Default ist `"open"`)
- **`_make_audit_finished`-Helper** ist ebenfalls in der Datei — für AC4-Tests nutzen, `job`-Parameter steuert den Job-Wert
- **`view_only_client`-Fixture** in derselben Datei zeigt das exakte Pattern für Permission-Override-Clients (AC7-Tests folgen demselben Muster)

## Aus 5-4 (Performance) gelernt

- `or_()` mit `is_(None)` ist der korrekte SQLAlchemy-2.0-Ansatz für nullable Spalten (kein `== None`)
- Tests für Sortier-Stabilität funktionieren zuverlässig wenn Timestamps explizit gesetzt werden (vgl. `date_tests_pick_mid_month`-Feedback im Memory)

## Projektkontext-Referenz

- **Tech-Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2.0, Pydantic v2, HTMX 2, Jinja2, SQLite (Tests), PostgreSQL 16 (Prod)
- **Testing:** pytest + TestClient + Mocks; Playwright erst wenn echter Client-JS nötig
- **User-facing Texte:** echte Umlaute (ä/ö/ü/ß), Identifier ASCII
- **Template-Response-Signatur:** `templates.TemplateResponse(request, template_name, context)` — `request` als erstes Positional-Arg (neue Starlette-API)
- **Permissions-System:** `has_permission(user, key)` im Template, `require_permission(key)` als FastAPI-Dependency

---

## Completion Notes

_[Wird nach der Implementierung vom Dev-Agent befüllt]_

- AC1 implementiert: ✗
- AC2 implementiert: ✗
- AC3 implementiert: ✗
- AC4 implementiert: ✗
- AC5 implementiert: ✗
- AC6 implementiert: ✗
- AC7 implementiert: ✗
- Tests grün: ✗
- Anmerkungen: —
