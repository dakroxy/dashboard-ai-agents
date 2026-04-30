# Story 3.5: Review-Queue-Admin-UI mit Filtern

Status: done

## Abhängigkeiten

- **Keine Abhängigkeit auf Stories 3.1–3.4.** Das `ReviewQueueEntry`-Modell, die Migration `0011_steckbrief_governance.py` (Tabelle `review_queue_entries`) und die Permission `objects:approve_ki` sind bereits deployed und einsatzbereit.
- `approve_review_entry()` / `reject_review_entry()` in `app/services/steckbrief_write_gate.py` sind bereits implementiert — sie werden in Story 3.6 verdrahtet. Story 3.5 ruft sie **nicht** auf (rein lesende View).
- Story 3.6 (Approve/Reject) setzt diese Story voraus — sie baut auf der Queue-Seite mit ihren POST-Routes auf.

## Story

Als Admin mit `objects:approve_ki`,
möchte ich eine portfolio-weite Review-Queue mit Filter-Optionen sehen,
damit ich KI-Vorschläge gezielt abarbeiten und Queue-Halden verhindern kann.

## Boundary-Klassifikation

`admin-ui` + `read-only` — Mittleres Risiko. Neue Route + neues Template, aber nur lesender DB-Zugriff. Das Write-Gate wird in dieser Story **nicht** aufgerufen.

Risiken:
1. **Timezone-Awareness**: `created_at` ist `DateTime(timezone=True)` (Migration 0011 + Modell `governance.py:95-96`) — also **timezone-aware** in Postgres. Projekt-Konvention (`admin.py` Z. 11, 299, 651, 784, 912): durchgaengig `datetime.now(timezone.utc)`. **Niemals** `datetime.utcnow()` (naive) — Subtraktion von tz-aware `created_at` wirft `TypeError: can't subtract offset-naive and offset-aware datetimes`. **SQLite-Caveat fuer Tests**: SQLite strippt tzinfo beim Roundtrip → `e.created_at` kann beim Read aus der Test-DB naive sein. `_prepare_entries` muss daher per `_aware()`-Helper coercen (Muster aus `admin.py:786-790`).
2. **proposed_value-Format**: JSONB mit Struktur `{"value": <typed_value>}`. Wert via `proposed_value.get("value", "")` extrahieren und zu `str()` casten; truncaten bei > 100 Zeichen (Pflicht: Listenwerte erzeugen sonst lange Repr).
3. **Entity-Links**: Für `target_entity_type="object"` existiert `/objects/{id}`. Für alle anderen Typen (unit, police, wartung, …) gibt es in v1 noch keine Detail-Views → nur UUID-String anzeigen, kein `<a>`-Tag.
4. **422 bei ungueltigen Query-Params**: Sowohl `/admin/review-queue` (Vollseite) als auch `/admin/review-queue/rows` (HTMX-Fragment) muessen bei ungueltiger UUID in `assigned_to_user_id` mit 200 antworten und den Filter stillschweigend ignorieren — niemals 422 (HTMX rendert eine 422-JSON-Fehlermeldung sonst direkt ins DOM, und der Vollseiten-Render duerfte dem User die Seite ueberhaupt nicht entreissen). Numerische Felder (`min_age_days`) sind via FastAPI `Query(..., ge=0)` validiert; bei negativen Werten kommt 422, was OK ist (Browser-Number-Input mit `min=0` verhindert das).

## Acceptance Criteria

**AC1 — Queue-Listing für Admin (Vollseite)**

**Given** ich bin als Admin mit `objects:approve_ki` eingeloggt
**When** ich `GET /admin/review-queue` aufrufe
**Then** erhalte ich HTTP 200
**And** sehe eine Liste aller `ReviewQueueEntry`-Zeilen mit `status="pending"`, sortiert nach `created_at` aufsteigend (älteste zuerst)
**And** pro Zeile sind enthalten: Ziel-Entität (verlinkt wenn `target_entity_type="object"`), Feldname, vorgeschlagener Wert (truncated bei > 100 Zeichen), Agent-Ref, Confidence (Prozent), Alter in Tagen

**AC2 — Empty State**

**Given** die Queue hat keine `status="pending"`-Einträge (v1-Normalzustand: keine aktiven KI-Agenten)
**When** die Seite rendert
**Then** sehe ich den Text "Keine Vorschläge offen"
**And** kein Fehler, kein leeres `<tbody>` ohne Hinweis

**AC3 — Alter-Filter via HTMX**

**Given** ich gebe im Filter "Alter > 3 Tage" ein
**When** der Filter-Input geändert wird
**Then** wird per HTMX (`hx-get="/admin/review-queue/rows"`) nur das entsprechende Subset als `<tbody>`-Fragment in die Tabelle geswapt
**And** Einträge mit `created_at > now - 3 Tage` sind ausgeblendet

**AC4 — Feldname-Filter und Ziel-User-Filter**

**Given** ich filtere nach `field_name="heating_type"`
**When** der Filter greift (HTMX-Swap)
**Then** werden nur Einträge mit `field_name="heating_type"` angezeigt

**Given** ich wähle im Assigned-to-Dropdown einen User
**When** der Filter greift
**Then** werden nur Einträge mit passendem `assigned_to_user_id` angezeigt
**And** Einträge ohne Zuweisung (`assigned_to_user_id IS NULL`) sind dann ausgeblendet

**AC5 — 403 ohne Berechtigung**

**Given** ich bin eingeloggt, aber ohne `objects:approve_ki`
**When** ich `GET /admin/review-queue` aufrufe
**Then** erhalte ich HTTP 403

**Given** ich bin nicht eingeloggt
**When** ich `GET /admin/review-queue` aufrufe
**Then** erhalte ich HTTP 302 (Redirect auf Login)

**AC6 — Admin-Navigation-Link**

**Given** ich bin Admin mit `objects:approve_ki`
**When** ich eine beliebige Seite im Admin-Bereich lade
**Then** ist in der Admin-Navigation ein Link "Review Queue" → `/admin/review-queue` sichtbar

## Tasks / Subtasks

- [x] **Task 1**: Route `GET /admin/review-queue` in `app/routers/admin.py` (AC1, AC2, AC5)
  - [x] 1.1: Funktion `list_review_queue(request, min_age_days, field_name, assigned_to_user_id, user, db)` nach dem letzten bestehenden Route-Handler anhängen
  - [x] 1.2: `require_permission("objects:approve_ki")` als Dependency
  - [x] 1.3: Query: `select(ReviewQueueEntry).where(ReviewQueueEntry.status == "pending").order_by(ReviewQueueEntry.created_at.asc())`
  - [x] 1.4: Filter `min_age_days`: `.where(ReviewQueueEntry.created_at < datetime.now(timezone.utc) - timedelta(days=min_age_days))` (nur wenn `min_age_days` gesetzt; **timezone-aware** — siehe Risk #1)
  - [x] 1.5: Filter `field_name`: `.where(ReviewQueueEntry.field_name == field_name)` (exact match, nur wenn gesetzt)
  - [x] 1.6: Filter `assigned_to_user_id`: `.where(ReviewQueueEntry.assigned_to_user_id == uuid.UUID(assigned_to_user_id))` (nur wenn gesetzt, in try/except für invalid UUID — gilt fuer **beide** Routen, Vollseite + Fragment, jeweils 200 + Filter ignoriert, kein 422)
  - [x] 1.7: `users_for_filter` laden: `db.execute(select(User).order_by(User.email)).scalars().all()` — für Assigned-to-Dropdown
  - [x] 1.8: `entries` + altersberechneten Kontext aufbereiten (Alter in Tagen als List[dict])
  - [x] 1.9: `TemplateResponse(request, "admin/review_queue.html", {...})` — alle Filter-Werte als `filter_*` zurückgeben

- [x] **Task 2**: HTMX-Fragment-Route `GET /admin/review-queue/rows` in `app/routers/admin.py` (AC3, AC4)
  - [x] 2.1: Gleiche Query-Parameter und Logik wie Task 1 (Hilfsfunktion `_build_queue_query(db, min_age_days, field_name, assigned_to_user_id)` extrahieren, von beiden Routen aufrufen)
  - [x] 2.2: `TemplateResponse(request, "admin/_review_queue_rows.html", {"entries": entries})` zurückgeben
  - [x] 2.3: Im Fehlerfall (z.B. ungültige UUID): leere Liste zurückgeben (kein 422)

- [x] **Task 3**: Template `app/templates/admin/review_queue.html` erstellen (AC1, AC2, AC3, AC4, AC6)
  - [x] 3.1: `{% extends "base.html" %}`, `{% block title %}Review Queue{% endblock %}`
  - [x] 3.2: Filter-Formular mit `id="filter-form"`, `hx-get="/admin/review-queue/rows"`, `hx-trigger="change"`, `hx-target="#queue-tbody"`, `hx-include="[name]"`
  - [x] 3.3: Filter-Inputs: `name="min_age_days"` (number, min=0), `name="field_name"` (text), `name="assigned_to_user_id"` (`<select>` mit `<option value="">— alle —</option>` + Loop über `users_for_filter`)
  - [x] 3.4: Tabellen-Kopf: Spalten "Ziel-Entität", "Feld", "Vorgeschlagener Wert", "Agent", "Confidence", "Alter"
  - [x] 3.5: `<tbody id="queue-tbody">{% include "admin/_review_queue_rows.html" %}</tbody>`
  - [x] 3.6: Auf dem `<form>`-Element `hx-trigger="change, submit"` setzen, damit ein einfacher `<button type="submit">Filtern</button>` ohne eigene `hx-*`-Attribute den Filter-Swap ausloest (vermeidet doppelte HTMX-Requests bei Klick auf den Button)

- [x] **Task 4**: Fragment-Template `app/templates/admin/_review_queue_rows.html` erstellen (AC1, AC2)
  - [x] 4.1: `{% for item in entries %}` Loop mit je einer `<tr>`
  - [x] 4.2: Ziel-Entität-Zelle: `{% if item.entry.target_entity_type == "object" %}<a href="/objects/{{ item.entry.target_entity_id }}" class="text-sky-600 hover:underline">object/{{ item.entry.target_entity_id | string | truncate(8, True, '') }}</a>{% else %}{{ item.entry.target_entity_type }}/{{ item.entry.target_entity_id }}{% endif %}`
  - [x] 4.3: Vorgeschlagener-Wert-Zelle: `{{ item.value_str }}` (aufbereitet im Router — max 100 Zeichen + "…" falls abgeschnitten)
  - [x] 4.4: Confidence-Zelle: `{{ (item.entry.confidence * 100) | round | int }} %`
  - [x] 4.5: Alter-Zelle: `{{ item.age_days }} Tage`
  - [x] 4.6: Empty-State: `{% else %}<tr><td colspan="6" class="text-center text-slate-400 italic py-8">Keine Vorschläge offen</td></tr>{% endfor %}`

- [x] **Task 5**: Admin-Navigation-Link hinzufügen (AC6)
  - [x] 5.1: Datei `app/templates/base.html` lesen — Stelle finden, wo Admin-Nav-Links stehen (z.B. Sidebar-Block mit `/admin/logs`, `/admin/sync-status`)
  - [x] 5.2: Link `<a href="/admin/review-queue">Review Queue</a>` mit Permission-Guard `{% if has_permission(user, "objects:approve_ki") %}` an geeigneter Stelle einfügen (nach "Audit-Log" oder in eigenem "KI-Governance"-Abschnitt)

- [x] **Task 6**: Imports + Hilfsfunktion in `admin.py` sicherstellen (AC1–AC4)
  - [x] 6.1: `from app.models.governance import ReviewQueueEntry` importieren (in `admin.py` aktuell noch nicht vorhanden — ergaenzen)
  - [x] 6.2: `datetime`, `timezone`, `timedelta` sind in `admin.py` Z. 11 bereits importiert (`from datetime import datetime, timedelta, timezone`) — keine Aenderung noetig
  - [x] 6.3: `User` ist bereits via `from app.models import ..., User, ...` importiert

- [x] **Task 7**: Tests `tests/test_review_queue_routes_smoke.py` (AC1–AC6 + Risk #4)
  - [x] 7.1: `test_review_queue_unauthenticated(anon_client)` — 302
  - [x] 7.2: `test_review_queue_no_permission(auth_client)` — `test_user` ohne `objects:approve_ki` → 403
  - [x] 7.3: `test_review_queue_empty_state(steckbrief_admin_client)` — keine Entries → 200, "Keine Vorschläge offen" im Text
  - [x] 7.4: `test_review_queue_entry_visible(steckbrief_admin_client, db)` — 1 Entry → 200, `field_name` im Text
  - [x] 7.5: `test_review_queue_rows_fragment_200(steckbrief_admin_client)` — GET `/admin/review-queue/rows` → 200
  - [x] 7.6: `test_review_queue_filter_field_name(steckbrief_admin_client, db)` — 2 Entries (1 passend) → nur passender Entry im Text
  - [x] 7.7: `test_review_queue_filter_min_age_excludes_fresh(steckbrief_admin_client, db)` — min_age_days=1, frischer Entry → Empty-State
  - [x] 7.8: `test_review_queue_filter_invalid_uuid_no_422(steckbrief_admin_client, db)` — `assigned_to_user_id=not-a-uuid` → 200, Filter ignoriert (Risk #4)

## Dev Notes

### Task 1+2: Route-Skeleton in `app/routers/admin.py`

```python
# ---- Imports (oben in admin.py ergaenzen — datetime/timedelta/timezone bereits Z. 11) ----
import uuid
from app.models.governance import ReviewQueueEntry

# ---- Hilfsfunktionen ----
def _aware(dt: datetime | None) -> datetime | None:
    """SQLite-Roundtrip strippt tzinfo. Coercen auf UTC, damit Subtraktion mit
    tz-aware `now` keinen TypeError wirft. Muster aus admin.py:786-790."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _build_queue_query(
    db: Session,
    min_age_days: int | None,
    field_name: str | None,
    assigned_to_user_id: str | None,
):
    q = select(ReviewQueueEntry).where(ReviewQueueEntry.status == "pending")
    if min_age_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
        q = q.where(ReviewQueueEntry.created_at <= cutoff)
    if field_name:
        q = q.where(ReviewQueueEntry.field_name == field_name)
    if assigned_to_user_id:
        try:
            uid = uuid.UUID(assigned_to_user_id)
            q = q.where(ReviewQueueEntry.assigned_to_user_id == uid)
        except ValueError:
            pass  # ungueltige UUID → Filter ignorieren (200 + leerer/ungefilterter State)
    return q.order_by(ReviewQueueEntry.created_at.asc())


def _prepare_entries(entries):
    """Konvertiert ORM-Objekte in Template-freundliche Dicts."""
    now = datetime.now(timezone.utc)
    result = []
    for e in entries:
        raw_value = e.proposed_value.get("value", "") if e.proposed_value else ""
        value_str = str(raw_value)
        if len(value_str) > 100:
            value_str = value_str[:100] + "…"
        result.append({
            "entry": e,
            "value_str": value_str,
            "age_days": (now - _aware(e.created_at)).days,
        })
    return result


# ---- Vollseite ----
@router.get("/review-queue", response_class=HTMLResponse)
async def list_review_queue(
    request: Request,
    min_age_days: int | None = Query(None, ge=0),
    field_name: str | None = Query(None),
    assigned_to_user_id: str | None = Query(None),
    user: User = Depends(require_permission("objects:approve_ki")),
    db: Session = Depends(get_db),
):
    q = _build_queue_query(db, min_age_days, field_name, assigned_to_user_id)
    entries = _prepare_entries(db.execute(q).scalars().all())
    users_for_filter = db.execute(select(User).order_by(User.email)).scalars().all()
    return TemplateResponse(request, "admin/review_queue.html", {
        "entries": entries,
        "users_for_filter": users_for_filter,
        "filter_min_age_days": min_age_days or "",
        "filter_field_name": field_name or "",
        "filter_assigned_to_user_id": assigned_to_user_id or "",
        "user": user,
    })


# ---- HTMX-Fragment ----
@router.get("/review-queue/rows", response_class=HTMLResponse)
async def list_review_queue_rows(
    request: Request,
    min_age_days: int | None = Query(None, ge=0),
    field_name: str | None = Query(None),
    assigned_to_user_id: str | None = Query(None),
    user: User = Depends(require_permission("objects:approve_ki")),
    db: Session = Depends(get_db),
):
    q = _build_queue_query(db, min_age_days, field_name, assigned_to_user_id)
    entries = _prepare_entries(db.execute(q).scalars().all())
    return TemplateResponse(request, "admin/_review_queue_rows.html", {
        "entries": entries,
        "user": user,
    })
```

**Wichtig**: `require_permission("objects:approve_ki")` ist der korrekte Permission-Key (existiert bereits in `app/permissions.py:55`). Die `require_permission`-Funktion prüft via `effective_permissions(user)` — User ohne dieses Recht bekommen 403, Nicht-Eingeloggte 302.

**SQLAlchemy-Style**: Das bestehende Audit-Log-Query (`admin.py:644`) nutzt noch das 1.x-`db.query(...)`-API. Wir wechseln in dieser Story bewusst auf das 2.0-`db.execute(select(...)).scalars().all()`-Pattern — neue Routen sollen darauf konvergieren. Funktional aequivalent, kein Refactor des Audit-Log-Codes noetig.

### Task 3+4: Template-Struktur

**`admin/review_queue.html`** (Vollseite) — Muster analog zu `admin/logs.html`:
- `{% extends "base.html" %}`
- Page-Header mit Titel "Review Queue"
- Filter-Formular (GET, kein POST) mit HTMX-Attributen auf dem `<form>`-Element
- Tabelle mit `<tbody id="queue-tbody">{% include "admin/_review_queue_rows.html" %}</tbody>`

**`admin/_review_queue_rows.html`** (reines Fragment — kein extends, kein block):
- Nur der Loop `{% for item in entries %}...{% else %}...{% endfor %}`
- Wird sowohl vom include im Vollseiten-Template genutzt, als auch direkt vom HTMX-Endpunkt zurückgegeben

**Entity-Link-Logik** (für spätere Erweiterung auf andere Typen vorbereiten):
```html
{% if item.entry.target_entity_type == "object" %}
  <a href="/objects/{{ item.entry.target_entity_id }}"
     class="text-sky-600 hover:underline text-sm font-mono">
    {{ item.entry.target_entity_id | string | truncate(8, True, '') }}
  </a>
{% else %}
  <span class="text-sm text-slate-500 font-mono">
    {{ item.entry.target_entity_type }}/{{ item.entry.target_entity_id | string | truncate(8, True, '') }}
  </span>
{% endif %}
```

**Confidence-Farbkodierung** (optional, gute UX):
```html
<span class="{% if item.entry.confidence >= 0.8 %}text-green-700{% elif item.entry.confidence >= 0.5 %}text-yellow-700{% else %}text-red-700{% endif %} tabular-nums">
  {{ (item.entry.confidence * 100) | round | int }} %
</span>
```

**Filter-Formular** (Form-Element mit HTMX):
```html
<form id="filter-form"
      hx-get="/admin/review-queue/rows"
      hx-trigger="change, submit"
      hx-target="#queue-tbody"
      hx-include="[name]"
      class="flex gap-4 flex-wrap items-end mb-6">
  <!-- min_age_days -->
  <div>
    <label class="block text-xs text-slate-500 mb-1">Alter > (Tage)</label>
    <input type="number" name="min_age_days" min="0" placeholder="—"
           value="{{ filter_min_age_days }}"
           class="w-24 rounded border border-slate-300 px-2 py-1 text-sm">
  </div>
  <!-- field_name -->
  <div>
    <label class="block text-xs text-slate-500 mb-1">Feld</label>
    <input type="text" name="field_name" placeholder="z.B. heating_type"
           value="{{ filter_field_name }}"
           class="rounded border border-slate-300 px-2 py-1 text-sm w-44">
  </div>
  <!-- assigned_to_user_id -->
  <div>
    <label class="block text-xs text-slate-500 mb-1">Zugewiesen an</label>
    <select name="assigned_to_user_id"
            class="rounded border border-slate-300 px-2 py-1 text-sm">
      <option value="">— alle —</option>
      {% for u in users_for_filter %}
      <option value="{{ u.id }}" {% if filter_assigned_to_user_id == u.id | string %}selected{% endif %}>
        {{ u.email }}
      </option>
      {% endfor %}
    </select>
  </div>
  <button type="submit"
          class="px-3 py-1 bg-slate-800 text-white rounded text-sm">
    Filtern
  </button>
</form>
```

`hx-trigger="change, submit"` sorgt dafuer, dass die Filter sowohl bei Live-Aenderung der Eingabefelder als auch bei explizitem Klick auf "Filtern" einen Swap ausloesen — der Button braucht keine eigenen `hx-*`-Attribute (die haetten sonst die Form-HTMX-Konfiguration doppelt ausgefuehrt).

### Task 5: Admin-Navigationslink

**Datei lesen bevor editieren**: `app/templates/base.html` vollständig lesen, um die genaue Stelle zu finden. In früheren Stories wurden Admin-Links in einem Sidebar-Block untergebracht. Suche nach `/admin/logs` oder `/admin/sync-status` — dort in der Nähe den neuen Link einfügen.

Pattern aus `base.html` (vermutlich ähnlich):
```html
{% if has_permission(user, "objects:approve_ki") %}
<a href="/admin/review-queue"
   class="...{% if request.url.path.startswith('/admin/review-queue') %} active-class {% endif %}">
  Review Queue
</a>
{% endif %}
```

Die `has_permission`-Funktion ist in `base.html` als Jinja2-Global verfügbar (analog zu `provenance_pill` in `templating.py`).

### Task 7: Tests `tests/test_review_queue_routes_smoke.py`

**Fixtures aus `tests/conftest.py`** (bereits vorhanden — Namen pruefen!):
- `db` — SQLite in-memory Session (Z. ~50)
- `steckbrief_admin_client` — TestClient mit allen Steckbrief-Admin-Perms inkl. `objects:approve_ki` (Z. 200)
- `auth_client` — TestClient mit eingeloggtem `test_user` **ohne** `objects:approve_ki` → fuer 403-Test (Z. 141)
- `anon_client` — TestClient ohne Authentifizierung → 302 (Z. 240)

Die in alten Stories teilweise referenzierten `client` / `steckbrief_user_client` existieren **nicht**. Verwende oben genannte Namen.

```python
import uuid
from datetime import datetime, timezone
from app.models.governance import ReviewQueueEntry


def _make_entry(db, field_name="heating_type"):
    """Hilfsfunktion: legt einen pending ReviewQueueEntry an.

    Datum-Konvention: Fixdatum 15. Januar (mid-month per
    `memory/feedback_date_tests_pick_mid_month.md`), tz-aware da Spalte
    `DateTime(timezone=True)` ist."""
    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=uuid.uuid4(),
        field_name=field_name,
        proposed_value={"value": "Fernwärme"},
        agent_ref="test-agent-v1",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
    )
    db.add(entry)
    db.commit()
    return entry


def test_review_queue_unauthenticated(anon_client):
    resp = anon_client.get("/admin/review-queue", follow_redirects=False)
    assert resp.status_code == 302


def test_review_queue_no_permission(auth_client):
    # auth_client = test_user ohne objects:approve_ki → 403
    resp = auth_client.get("/admin/review-queue")
    assert resp.status_code == 403


def test_review_queue_empty_state(steckbrief_admin_client):
    resp = steckbrief_admin_client.get("/admin/review-queue")
    assert resp.status_code == 200
    assert "Keine Vorschläge offen" in resp.text


def test_review_queue_entry_visible(steckbrief_admin_client, db):
    _make_entry(db, field_name="heating_type")
    resp = steckbrief_admin_client.get("/admin/review-queue")
    assert resp.status_code == 200
    assert "heating_type" in resp.text


def test_review_queue_rows_fragment_200(steckbrief_admin_client):
    resp = steckbrief_admin_client.get("/admin/review-queue/rows")
    assert resp.status_code == 200
    assert "Keine Vorschläge offen" in resp.text


def test_review_queue_filter_field_name(steckbrief_admin_client, db):
    _make_entry(db, field_name="heating_type")
    _make_entry(db, field_name="year_built")
    resp = steckbrief_admin_client.get("/admin/review-queue/rows?field_name=heating_type")
    assert resp.status_code == 200
    assert "heating_type" in resp.text
    assert "year_built" not in resp.text


def test_review_queue_filter_min_age_excludes_fresh(steckbrief_admin_client, db):
    # Frischer Entry (created_at = jetzt, tz-aware) soll bei min_age_days=1
    # nicht erscheinen — Entry ist < 1 Tag alt → ausgeblendet
    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=uuid.uuid4(),
        field_name="heating_type",
        proposed_value={"value": "Gas"},
        agent_ref="agent",
        confidence=0.8,
        status="pending",
        agent_context={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    resp = steckbrief_admin_client.get("/admin/review-queue/rows?min_age_days=1")
    assert resp.status_code == 200
    assert "Keine Vorschläge offen" in resp.text


def test_review_queue_filter_invalid_uuid_no_422(steckbrief_admin_client, db):
    # Risk #4: ungueltige UUID in assigned_to_user_id → 200 + Filter ignoriert
    _make_entry(db, field_name="heating_type")
    resp = steckbrief_admin_client.get(
        "/admin/review-queue/rows?assigned_to_user_id=not-a-uuid"
    )
    assert resp.status_code == 200
    assert "heating_type" in resp.text  # Filter wurde ignoriert, Entry sichtbar
```

**Hinweis zu Datums-Konventionen**:
- Fixdatum `datetime(2025, 1, 15, tzinfo=timezone.utc)` (15. Januar — mid-month per `feedback_date_tests_pick_mid_month.md`) vermeidet Flackern am 1.–5. eines Monats.
- **Tz-aware Pflicht**: Spalte ist `DateTime(timezone=True)` — naive `datetime.utcnow()` / `datetime(2025, 1, 15)` wuerden auf SQLite roundtrippen, in Postgres-Prod aber zu Vergleichs-Crashes fuehren.
- Im `min_age_excludes_fresh`-Test wird `datetime.now(timezone.utc)` direkt gesetzt, da genau die "frisch" Eigenschaft getestet wird.

### Kein Konflikt mit Write-Gate

Story 3.5 ruft `write_field_human()`, `approve_review_entry()` oder `reject_review_entry()` **nicht** auf. Das Write-Gate bleibt unberührt. Kein FieldProvenance-Eintrag wird erstellt.

### `ReviewQueueEntry`-Import in `admin.py`

`admin.py` importiert aktuell bereits `AuditLog` und andere Modelle. Prüfen ob `from app.models.governance import ReviewQueueEntry` bereits vorhanden ist — falls nicht, am Anfang des Modells-Import-Blocks ergänzen. Die Governance-Modelle liegen in `app/models/governance.py`.

### Bestehende `_obj_list_query`-Pattern nicht verwenden

Die Review-Queue-Query hat nichts mit Objekt-Abfragen zu tun. Den `_build_queue_query`-Helper direkt in `admin.py` definieren (nicht in ein separates Service-Modul auslagern — zu klein für eigene Datei).

## Test-Checkliste (Epic-2-Retro P1)

- [x] **Permission-Matrix**: Unauthenticated → 302, kein `approve_ki` → 403, `approve_ki` → 200 (Tests 7.1, 7.2, 7.3)
- [x] **IDOR**: nicht anwendbar — keine FK aus Form-Body (Story 3.5 ist read-only)
- [x] **Numerische Boundaries**: `min_age_days=0` → zeigt alle Entries (Grenzwert 0 inklusive) — Test `test_review_queue_filter_min_age_zero_includes_all` (Code-Review-Patch)
- [x] **NULLs**: `assigned_to_user_id IS NULL` bei unzugewiesenen Entries kein Crash + bei gesetztem Filter ausgeblendet — Test `test_review_queue_filter_assigned_excludes_null` (Code-Review-Patch)
- [x] **Tel-Link**: nicht anwendbar
- [x] **Date-Bounds**: Fixdatum `date(2025, 1, 15)` in `_make_entry` (mid-month)
- [x] **HTMX-422-Render**: `/rows`-Endpunkt gibt bei ungültiger UUID für `assigned_to_user_id` 200 + Filter ignoriert zurück (kein 422) — abgedeckt durch Test 7.8
- [x] **Timezone-Roundtrip**: alle Tests inserten `created_at` tz-aware (`datetime(..., tzinfo=timezone.utc)`); `_aware()`-Helper im Router fängt SQLite-tzinfo-Stripping ab
- [x] **Empty-State**: "Keine Vorschläge offen" (Test 7.3, 7.7)

## Neue Dateien

- `app/templates/admin/review_queue.html`
- `app/templates/admin/_review_queue_rows.html`
- `tests/test_review_queue_routes_smoke.py`

## Geänderte Dateien

- `app/routers/admin.py` — `_build_queue_query()`, `_prepare_entries()`, `list_review_queue()`, `list_review_queue_rows()` hinzufügen; `ReviewQueueEntry`-Import ergänzen
- `app/templates/base.html` — Admin-Nav-Link "Review Queue" mit `objects:approve_ki`-Guard

## References

- `ReviewQueueEntry`-Modell: `app/models/governance.py:49–98`
- `objects:approve_ki` Permission: `app/permissions.py:55`
- `_build_queue_query` Pattern (analog Audit-Log): `app/routers/admin.py:634–685`
- `approve_review_entry()` / `reject_review_entry()` (Story 3.6): `app/services/steckbrief_write_gate.py:400–518`
- Migration Governance-Tabellen: `migrations/versions/0011_steckbrief_governance.py`
- HTMX-Fragment-Pattern (analog Story 3.1): `output/implementation-artifacts/3-1-objekt-liste-mit-sortierung-filter.md`
- `_prepare_entries` timezone-Hinweis: `created_at` ist `DateTime(timezone=True)` → `datetime.now(timezone.utc)` + `_aware()`-Helper (Muster `admin.py:786-790`) gegen SQLite-tzinfo-Stripping
- Date-Bounds Memory: `memory/feedback_date_tests_pick_mid_month.md`
- Smoke-Test Muster: `tests/test_registries_routes_smoke.py`
- Admin-Template Muster: `app/templates/admin/logs.html`
- Epic-2-Retro Test-Checkliste P1: `output/implementation-artifacts/epic-2-retro-2026-04-28.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

Kein Debug-Log nötig. Implementation lief ohne Probleme durch.

### Completion Notes List

- Alle 7 Tasks implementiert, 8/8 neue Tests grün, 804 Gesamt-Tests grün (kein Regression).
- `select` musste zu sqlalchemy-Import ergänzt werden (war noch nicht in admin.py).
- `_aware()` + `_build_queue_query()` + `_prepare_entries()` als Hilfsfunktionen vor den neuen Routes platziert.
- Filter-Formular mit `hx-trigger="change, submit"` — Live-Update bei Eingabe + expliziter Filtern-Button ohne doppelte HTMX-Requests.
- Nav-Link unter eigenem "KI-Governance"-Block mit `objects:approve_ki`-Guard, aktive-Klasse für `/admin/review-queue`-Pfade.
- Bestehender Test `test_detail_renders_stammdaten_and_eigentuemer` prüfte `"Review" not in body` — angepasst auf Main-Content-Scope, da Nav jetzt "Review Queue" enthält.
- Confidence-Farbkodierung (grün ≥0.8 / gelb ≥0.5 / rot <0.5) als UX-Verbesserung eingebaut.

### File List

- `app/routers/admin.py` — `select`-Import, `ReviewQueueEntry`-Import, `_aware()`, `_build_queue_query()`, `_prepare_entries()`, `list_review_queue()`, `list_review_queue_rows()` hinzugefügt
- `app/templates/admin/review_queue.html` — neu erstellt
- `app/templates/admin/_review_queue_rows.html` — neu erstellt
- `app/templates/base.html` — KI-Governance-Nav-Block mit Review-Queue-Link
- `tests/test_review_queue_routes_smoke.py` — neu erstellt (8 Tests)
- `tests/test_steckbrief_routes_smoke.py` — Assertion auf Main-Content-Scope eingeschränkt

### Review Findings

Code-Review 2026-04-30 (3 parallele Reviewer: Blind Hunter, Edge Case Hunter, Acceptance Auditor). Triage: 7 Patches, 11 Defers, 19 Dismissed.

**Patches (Must-Fix / Should-Fix):**

- [x] [Review][Patch] **Test 7.4 false-positive durch Filter-Placeholder** [`tests/test_review_queue_routes_smoke.py:40-44`] — `test_review_queue_entry_visible` asserted `"heating_type" in resp.text` gegen Vollseite, aber `review_queue.html:24` hat `placeholder="z.B. heating_type"`. Test passt immer, auch bei leerer DB / 500 / falschem Template. Fix: gegen aussagekräftigen String asserten (`agent_ref="test-agent-v1"`, `Fernwärme`, oder UUID-Truncate). Quelle: Auditor.
- [x] [Review][Patch] **Boundary-Test `min_age_days=0` fehlt** [`tests/test_review_queue_routes_smoke.py`] — Test-Checkliste verlangt explizit "Grenzwert 0 inklusive". Code: `created_at <= now - 0d` ⇒ alle Entries; ohne Test nicht verifiziert. Quelle: Auditor.
- [x] [Review][Patch] **AC4-NULL-Exclusion nicht getestet** [`tests/test_review_queue_routes_smoke.py`] — AC4 zweite Klausel: "Einträge ohne Zuweisung (`assigned_to_user_id IS NULL`) sind dann ausgeblendet". Code stützt sich auf SQL-3VL (`NULL == uid` → false), aber kein Test mit zwei Entries (eine NULL, eine zugewiesen) + User-Filter. Quelle: Auditor.
- [x] [Review][Patch] **`field_name` whitespace-only fasst leere Filter als gesetzt auf** [`app/routers/admin.py:_build_queue_query`] — `if field_name:` ist truthy für `" "`, danach `==` matcht null Rows. User glaubt nichts gefiltert zu haben, sieht aber Empty-State. Fix: `if field_name and field_name.strip():` + Wert getrimmt einsetzen. Quelle: Edge Case Hunter.
- [x] [Review][Patch] **`min_age_days` ohne Obergrenze ⇒ OverflowError** [`app/routers/admin.py:list_review_queue`] — `Query(None, ge=0)` akzeptiert auch `1e15`; `timedelta(days=...)` overflowt bei > 999_999_999. 500. Fix: `Query(None, ge=0, le=36500)` (100 Jahre als Sanity-Cap). Quelle: Edge Case Hunter.
- [x] [Review][Patch] **`proposed_value`-Shape-Defense fehlt** [`app/routers/admin.py:_prepare_entries`] — Konvention ist `{"value": ...}`, JSONB nullable=False. Wenn Agent versehentlich Liste/Skalar einliefert, crasht `e.proposed_value.get(...)` mit `AttributeError` ⇒ 500 für die ganze Queue. Fix: `raw_value = e.proposed_value.get("value", "") if isinstance(e.proposed_value, dict) else str(e.proposed_value or "")`. Quelle: Blind+Edge.
- [x] [Review][Patch] **Test-Checkliste-Boxen abhaken nach Patches** [`output/implementation-artifacts/3-5-...md:452-460`] — Boxen "Numerische Boundaries", "NULLs" sind ungekreuzt; nach Patch 2+3 gibt es Test-Evidence. Quelle: Auditor.

**Defers (real, aber nicht jetzt):**

- [x] [Review][Defer] **Pagination / Unbounded Result Set** [`app/routers/admin.py:_build_queue_query`] — deferred, v1 hat Queue mit 0 Entries (keine aktiven KI-Agenten). Bei wachsender Queue (>200 Entries) auf `LIMIT/OFFSET` umstellen. Quelle: Blind+Edge.
- [x] [Review][Defer] **HTMX `hx-include="[name]"` zu greedy** [`app/templates/admin/review_queue.html:11`] — deferred, aktuell keine anderen `[name]`-Inputs auf der Page (Sidebar hat keine Inputs). Bei Erweiterung der Page (z.B. Suchleiste, CSRF-Token) auf `hx-include="closest form"` umstellen. Quelle: Blind.
- [x] [Review][Defer] **HTMX double-fire on Enter** [`app/templates/admin/review_queue.html:14`] — deferred, `change, submit` kann bei Tab+Enter zwei Requests feuern; mit `delay:100ms` zu härten. Niedriges Risiko. Quelle: Edge.
- [x] [Review][Defer] **`agent_ref` ohne Truncation/`max-w`** [`app/templates/admin/_review_queue_rows.html:18`] — deferred, lange Agent-IDs sprengen Layout. UX-Fit-and-Finish. Quelle: Blind.
- [x] [Review][Defer] **`age_days` Negativ-Werte bei Clock-Skew** [`app/routers/admin.py:_prepare_entries`] — deferred, `(now - created_at).days` kann -1 werden bei Server-Clock-Drift / future-dated test data. Defensiv: `max(0, days)`. Niedriges Risiko in Prod (NTP). Quelle: Blind+Edge.
- [x] [Review][Defer] **Confidence ausserhalb [0,1]** [`app/templates/admin/_review_queue_rows.html:18-21`] — deferred, falsch kalibrierte Agents könnten "150%" oder "-30%" rendern. Defensive Clamp: `(min(1, max(0, conf)) * 100)`. Quelle: Edge.
- [x] [Review][Defer] **Anchor-Text ohne `object/`-Prefix** [`app/templates/admin/_review_queue_rows.html:7`] — deferred, Spec ist intern inkonsistent (Task 4.2 inkl. Prefix, Dev Notes ohne); Dev folgte Dev Notes. Cosmetic. Quelle: Auditor.
- [x] [Review][Defer] **Doppel-Highlight: Review Queue + Admin auf `/admin/review-queue`** [`app/templates/base.html:124+138`] — deferred, pre-existing Pattern (alle `/admin/*`-Subpages haben den Effekt). Globaler Sidebar-Refactor wäre eigene Story. Quelle: Auditor.
- [x] [Review][Defer] **`test_steckbrief_routes_smoke.py:241-243` `<main>`-Split fragil** [`tests/test_steckbrief_routes_smoke.py:241-243`] — deferred, `body.split("<main")[1].split("</main>")[0]` fällt bei Layout-Refactor stillschweigend auf Full-Body zurück (else-Branch maskiert Regression). Pragmatisch akzeptabel; bei Layout-Änderung neu prüfen. Quelle: Blind.
- [x] [Review][Defer] **Permission-Magic-String dupliziert (Template + Router)** [`app/templates/base.html:124`, `app/routers/admin.py:1003+1031`] — deferred, projektweites Pattern. Konstanten-Refactor wäre eigene Story. Quelle: Blind.
- [x] [Review][Defer] **`test_review_queue_unauthenticated` asserted Redirect-Status, nicht Target** [`tests/test_review_queue_routes_smoke.py:24-26`] — deferred, pre-existing Test-Pattern; offen-Redirect via `next=`-Param wäre eigene Story. Quelle: Blind.

**Dismissed (handled / by design / impossible):**

IDOR/Portfolio-wide-Visibility (Spec-Design "portfolio-weite Queue"), Silent-UUID-Ignore (Risk #4 Contract + Test 7.8), `<=` vs `<` (matched Dev Notes + AC3-Wording), `created_at`/`confidence`-NULL-Crash (`nullable=False`), Confidence-NaN (Postgres rejects NaN), Object-Link-404 bei gelöschtem Objekt (by Design — Admin sieht die Lücke), Non-Object-Drill-down (Risk #3 explizit), Routes-Drift (`_build_queue_query` ist shared), Uppercase-UUID-Select-Preselection (Postgres outputs lowercase), `field_name` case-sensitive (Konvention), Users-Email-Liste Info-Leak (Admin sieht Emails ohnehin), Read-Audit-Log (Projekt-Pattern: nur Writes), Confidence-Color-Coding "Scope-Creep" (steht in Dev Notes), `filter_min_age_days`-Falsy-Fix (positive Abweichung), Tests-fixtures-decken-tz-Roundtrip-nicht (Test 7.7 mit `now` deckt es ab), `test_review_queue_filter_field_name`-Substring (Fragment hat keinen Placeholder), `change`-pro-Keystroke (Browser feuert `change` erst on Blur), XSS-via-Unicode-Truncation (Jinja-Autoescape + Codepoint-Slicing).
