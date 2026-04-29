# Story 3.6: Review-Queue Approve/Reject

Status: ready-for-dev

## Abhängigkeiten

- **Setzt Story 3.5 voraus** (vollständig implementiert): Die Routes `GET /admin/review-queue` + `GET /admin/review-queue/rows`, die Templates `admin/review_queue.html` + `admin/_review_queue_rows.html` sowie der Admin-Nav-Link müssen vor dieser Story existieren.
- `approve_review_entry()` / `reject_review_entry()` in `app/services/steckbrief_write_gate.py` (Zeilen 400–517) sind bereits implementiert und vollständig einsatzbereit — diese Story verdrahtet sie lediglich mit HTTP-Routen und Template-Buttons.
- `ReviewQueueEntry`-Modell + Migration `0011_steckbrief_governance.py` fertig. Kein neues DB-Schema nötig: alle Felder (`decided_at`, `decided_by_user_id`, `decision_reason`, `status`) existieren bereits.
- `objects:approve_ki`-Permission ist in `app/permissions.py:55` definiert und dem `steckbrief_admin_client`-Fixture zugewiesen.

## Story

Als Admin mit `objects:approve_ki`,
möchte ich einzelne Queue-Einträge approven oder rejecten,
damit KI-Vorschläge kontrolliert in den Steckbrief einfliessen oder abgewiesen werden.

## Boundary-Klassifikation

`admin-write` + `write-gate-call` — Mittleres Risiko. Zwei neue POST-Routes + Anpassung eines bestehenden Fragments. Das Write-Gate (`steckbrief_write_gate.py`) wird aufgerufen — ein Approve persistiert einen echten Feld-Write auf einer CD1-Entität.

Risiken:
1. **WriteGateError vs. ValueError unterscheiden**: `approve_review_entry()` wirft `ValueError` wenn der Entry nicht mehr `pending` ist (Race-Condition: Doppelklick / zwei Tabs), und `WriteGateError` wenn die Ziel-Entity fehlt. Der Router muss beides als 400 behandeln und dem User eine klare Meldung geben — kein Server-Error-500.
2. **Superseding**: Das Epic-Kriterium (`status="superseded"` für ältere pending Entries auf dasselbe Feld) ist **nicht** in `approve_review_entry()` implementiert. Der Router-Code muss das nach dem Gate-Call nachführen: alle anderen `pending` Entries mit identischem `(target_entity_type, target_entity_id, field_name)` auf `superseded` setzen. Kein separater Audit-Eintrag nötig (v1); Ziel ist nur, dass die Queue-UI keine Geister-Entries mehr zeigt.
3. **Commit-Atomizität**: `approve_review_entry()` und das Superseding-Update müssen **in derselben Transaktion** committed werden. Pattern: Gate-Call → Superseding-Update → `db.commit()`.
4. **Reject-Reason-Pflicht**: `reject_review_entry()` erwartet einen nicht-leeren `reason`-String. Leerer Reason muss vor dem Gate-Call im Router abgefangen werden (400) — kein ValidationError tief im Write-Gate.
5. **HTMX-Response nach POST**: Nach einem erfolgreichen Approve/Reject soll die genehmte/abgelehnte Zeile aus der Pending-Liste verschwinden. Einfachste robuste Lösung: `HX-Redirect: /admin/review-queue` Header im Response → HTMX macht einen vollständigen Seiten-Reload. Kein fein-granulares OOB-Swap nötig (v1-Queue ist kurz und selten > 50 Einträge).
6. **Tz-awareness**: `decided_at` wird in `approve_review_entry()` / `reject_review_entry()` mit `datetime.now(tz=timezone.utc)` gesetzt — das ist korrekt. Im Router selbst kein separates Datumshandling nötig.
7. **IDOR-Schutz**: `entry_id` kommt aus dem URL-Pfad. Das `objects:approve_ki`-Permission ist portfolio-weit — jeder Admin kann jeden Entry approven. In v1 kein objekt-spezifisches Fein-Recht (kein IDOR-Risiko, da alle Admins gleiche Sicht haben).

## Acceptance Criteria

**AC1 — Approve eines pending Eintrags**

**Given** ich bin als Admin mit `objects:approve_ki` eingeloggt
**And** ein `ReviewQueueEntry` mit `status="pending"` existiert
**When** ich `POST /admin/review-queue/{entry_id}/approve` absende
**Then** ruft der Handler `approve_review_entry(db, entry_id=entry_id, user=user, request=request)` auf
**And** `write_field_human()` persistiert den Wert mit `source="ai_suggestion"` auf der Ziel-Entität
**And** der Queue-Eintrag hat `status="approved"`, `decided_at` gesetzt, `decided_by_user_id=current_user.id`
**And** ein `AuditLog`-Eintrag mit `action="review_queue_approved"` ist in derselben Transaktion angelegt
**And** die Response enthält `HX-Redirect: /admin/review-queue` (HTMX reload) oder ist ein 303-Redirect

**AC2 — Superseding älterer pending Einträge beim Approve**

**Given** zwei `ReviewQueueEntry`-Zeilen mit identischem `(target_entity_type, target_entity_id, field_name)`, beide `status="pending"`
**When** der neuere (höhere `created_at`) approved wird
**Then** wechselt der ältere Entry automatisch auf `status="superseded"` (ohne eigenen Audit-Eintrag)
**And** er erscheint nicht mehr in der Pending-Queue (da Pending-Filter `status="pending"` verwendet)

**AC3 — Reject eines pending Eintrags**

**Given** ein `ReviewQueueEntry` mit `status="pending"` existiert
**When** ich `POST /admin/review-queue/{entry_id}/reject` mit einem nicht-leeren `reason`-Formular-Feld absende
**Then** wechselt der Status auf `rejected`, `decision_reason` ist gesetzt
**And** das Zielfeld auf der Entität bleibt **unverändert** (kein Field-Write)
**And** ein `AuditLog`-Eintrag mit `action="review_queue_rejected"` ist angelegt
**And** die Response enthält `HX-Redirect: /admin/review-queue` oder 303-Redirect

**AC4 — Reject ohne Begründung abgelehnt**

**Given** ich sende `POST /admin/review-queue/{entry_id}/reject` mit leerem `reason`
**Then** erhalte ich 400 (kein Gate-Call)
**And** kein `status`-Wechsel im Entry

**AC5 — Doppelklick / Race-Condition**

**Given** ein Entry wurde bereits `approved` oder `rejected`
**When** ich denselben Approve/Reject erneut absende
**Then** erhalte ich 400 mit einer lesbaren Fehlermeldung (keine 500)
**And** kein zweiter Feld-Write, keine doppelte Provenance-Row

**AC6 — 403 ohne Berechtigung**

**Given** ich bin eingeloggt, aber ohne `objects:approve_ki`
**When** ich `POST /admin/review-queue/{entry_id}/approve` oder `…/reject` aufrufe
**Then** erhalte ich 403

**AC7 — Approve/Reject-Buttons in der Queue-UI**

**Given** die Queue zeigt pending Einträge (Story 3.5 Template `_review_queue_rows.html`)
**When** ich die Seite lade
**Then** hat jede Zeile einen "Approve"-Button und einen "Reject"-Button
**And** der Reject-Button expandiert ein Inline-Formular mit einem Reason-Textfeld und einem "Bestätigen"-Submit-Button

## Tasks / Subtasks

- [ ] **Task 1**: Route `POST /admin/review-queue/{entry_id}/approve` in `app/routers/admin.py` (AC1, AC2, AC5, AC6)
  - [ ] 1.1: Imports ergänzen: `from sqlalchemy import update` (falls noch nicht vorhanden) + `from app.services.steckbrief_write_gate import approve_review_entry, reject_review_entry, WriteGateError`
  - [ ] 1.2: `ReviewQueueEntry` in `admin.py` bereits importiert (aus Story 3.5 Task 6.1) — Existenz prüfen, falls nicht: `from app.models.governance import ReviewQueueEntry` ergänzen
  - [ ] 1.3: Handler-Signatur: `async def approve_entry(entry_id: uuid.UUID, request: Request, user: User = Depends(require_permission("objects:approve_ki")), db: Session = Depends(get_db))`
  - [ ] 1.4: Entry vorab laden: `entry = db.get(ReviewQueueEntry, entry_id)` — `None`-Guard: falls nicht gefunden → 404
  - [ ] 1.5: `try: approve_review_entry(db, entry_id=entry_id, user=user, request=request)` — `except (WriteGateError, ValueError) as e: raise HTTPException(400, detail=str(e))`
  - [ ] 1.6: Superseding-Update nach erfolgreichem Gate-Call (vor Commit): `db.execute(update(ReviewQueueEntry).where(ReviewQueueEntry.status == "pending", ReviewQueueEntry.target_entity_type == entry.target_entity_type, ReviewQueueEntry.target_entity_id == entry.target_entity_id, ReviewQueueEntry.field_name == entry.field_name, ReviewQueueEntry.id != entry_id).values(status="superseded", decided_at=datetime.now(timezone.utc), decided_by_user_id=user.id))`
  - [ ] 1.7: `db.commit()`
  - [ ] 1.8: HTMX-Response: `from fastapi.responses import HTMLResponse as _HTML; resp = Response(status_code=204); resp.headers["HX-Redirect"] = "/admin/review-queue"; return resp` — bei nicht-HTMX-Request als Fallback `RedirectResponse("/admin/review-queue", status_code=303)`

- [ ] **Task 2**: Route `POST /admin/review-queue/{entry_id}/reject` in `app/routers/admin.py` (AC3, AC4, AC5, AC6)
  - [ ] 2.1: Handler-Signatur: `async def reject_entry(entry_id: uuid.UUID, request: Request, reason: str = Form(""), user: User = Depends(require_permission("objects:approve_ki")), db: Session = Depends(get_db))`
  - [ ] 2.2: Reason-Guard: `if not reason.strip(): raise HTTPException(400, detail="Begründung ist erforderlich")`
  - [ ] 2.3: `try: reject_review_entry(db, entry_id=entry_id, user=user, reason=reason.strip(), request=request)` — `except (WriteGateError, ValueError) as e: raise HTTPException(400, detail=str(e))`
  - [ ] 2.4: `db.commit()`
  - [ ] 2.5: Gleiche HTMX-Response wie Task 1.8

- [ ] **Task 3**: Fragment-Template `app/templates/admin/_reject_form.html` erstellen (AC7)
  - [ ] 3.1: Kein `{% extends %}` — reines Fragment
  - [ ] 3.2: Ein `<form>` mit `hx-post="/admin/review-queue/{{ entry_id }}/reject"` + `hx-include="[name]"` + `hx-push-url="false"`
  - [ ] 3.3: `<textarea name="reason" rows="2" placeholder="Begründung..." required class="w-full rounded border border-slate-300 px-2 py-1 text-sm"></textarea>`
  - [ ] 3.4: Submit-Button "Reject bestätigen" + Cancel-Link

- [ ] **Task 4**: Route `GET /admin/review-queue/{entry_id}/reject-form` in `app/routers/admin.py` (AC7)
  - [ ] 4.1: Liefert Fragment `admin/_reject_form.html` mit `{"entry_id": entry_id}` — kein DB-Call nötig, nur Template-Render
  - [ ] 4.2: `require_permission("objects:approve_ki")` als Dependency

- [ ] **Task 5**: Template `app/templates/admin/_review_queue_rows.html` anpassen (AC7)
  - [ ] 5.1: Datei aus Story 3.5 lesen bevor editieren
  - [ ] 5.2: Pro `<tr>` in der Zeile eine Aktionszelle `<td>` hinzufügen (letzte Spalte "Aktion")
  - [ ] 5.3: Approve-Button: `<button hx-post="/admin/review-queue/{{ item.entry.id }}/approve" hx-confirm="Vorschlag für Feld '{{ item.entry.field_name }}' freigeben?" hx-push-url="false" class="px-2 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-sm">Approve</button>`
  - [ ] 5.4: Reject-Button (öffnet Inline-Form via HTMX-GET): `<button hx-get="/admin/review-queue/{{ item.entry.id }}/reject-form" hx-target="#reject-area-{{ item.entry.id | string | replace('-', '') }}" hx-swap="innerHTML" class="ml-2 px-2 py-1 bg-red-600 hover:bg-red-700 text-white rounded text-sm">Reject</button>`
  - [ ] 5.5: Inline-Expand-Area pro Zeile: `<div id="reject-area-{{ item.entry.id | string | replace('-', '') }}" class="mt-1"></div>`
  - [ ] 5.6: Tabellenkopf in `review_queue.html` um Spalte "Aktion" erweitern (aus Story 3.5 Datei lesen + editieren)

- [ ] **Task 6**: Tests `tests/test_review_queue_approve_reject.py` (AC1–AC7)
  - [ ] 6.1: `_make_pending_entry(db, field_name, target_entity_type, target_entity_id)` — Hilfsfunktion analog zu `_make_entry` aus Story 3.5, erzeugt `pending` Entry + `Object` als Ziel-Entity
  - [ ] 6.2: `test_approve_sets_status(steckbrief_admin_client, db)` — Approve → Entry `status="approved"`, `decided_by_user_id` gesetzt
  - [ ] 6.3: `test_approve_writes_field(steckbrief_admin_client, db)` — Approve → Ziel-Object-Feld hat den neuen Wert aus `proposed_value["value"]`
  - [ ] 6.4: `test_approve_creates_audit_log(steckbrief_admin_client, db)` — `AuditLog` mit `action="review_queue_approved"` vorhanden
  - [ ] 6.5: `test_approve_supersedes_other_pending(steckbrief_admin_client, db)` — 2 Entries gleiche Entity+Feld → approve 1 → 2. Entry auf `superseded`
  - [ ] 6.6: `test_reject_sets_status(steckbrief_admin_client, db)` — Reject → `status="rejected"`, `decision_reason` gesetzt
  - [ ] 6.7: `test_reject_no_field_write(steckbrief_admin_client, db)` — Reject → Ziel-Object-Feld unverändert
  - [ ] 6.8: `test_reject_missing_reason_returns_400(steckbrief_admin_client, db)` — leerer reason → 400
  - [ ] 6.9: `test_approve_already_approved_returns_400(steckbrief_admin_client, db)` — doppelter Approve → 400
  - [ ] 6.10: `test_approve_no_permission_returns_403(auth_client, db)` — ohne `objects:approve_ki` → 403

## Dev Notes

### Task 1+2: Route-Skelett in `app/routers/admin.py`

```python
# ---- Imports ergänzen (am Anfang von admin.py, nach bestehenden Importen) ----
from sqlalchemy import update
from app.models.governance import ReviewQueueEntry  # falls nicht aus Story 3.5 vorhanden
from app.services.steckbrief_write_gate import (
    approve_review_entry,
    reject_review_entry,
    WriteGateError,
)

# ---- Approve-Route ----
@router.post("/review-queue/{entry_id}/approve")
async def approve_entry(
    entry_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:approve_ki")),
    db: Session = Depends(get_db),
):
    entry = db.get(ReviewQueueEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    try:
        approve_review_entry(db, entry_id=entry_id, user=user, request=request)
    except (WriteGateError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Superseding: weitere pending Entries auf dasselbe Feld derselben Entity
    db.execute(
        update(ReviewQueueEntry)
        .where(
            ReviewQueueEntry.status == "pending",
            ReviewQueueEntry.target_entity_type == entry.target_entity_type,
            ReviewQueueEntry.target_entity_id == entry.target_entity_id,
            ReviewQueueEntry.field_name == entry.field_name,
            ReviewQueueEntry.id != entry_id,
        )
        .values(
            status="superseded",
            decided_at=datetime.now(timezone.utc),
            decided_by_user_id=user.id,
        )
    )
    db.commit()
    return _htmx_redirect(request, "/admin/review-queue")


# ---- Reject-Route ----
@router.post("/review-queue/{entry_id}/reject")
async def reject_entry(
    entry_id: uuid.UUID,
    request: Request,
    reason: str = Form(""),
    user: User = Depends(require_permission("objects:approve_ki")),
    db: Session = Depends(get_db),
):
    if not reason.strip():
        raise HTTPException(status_code=400, detail="Begründung ist erforderlich")
    entry = db.get(ReviewQueueEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    try:
        reject_review_entry(db, entry_id=entry_id, user=user, reason=reason.strip(), request=request)
    except (WriteGateError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return _htmx_redirect(request, "/admin/review-queue")


# ---- GET-Fragment für Reject-Formular ----
@router.get("/review-queue/{entry_id}/reject-form", response_class=HTMLResponse)
async def reject_form_fragment(
    entry_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("objects:approve_ki")),
    db: Session = Depends(get_db),
):
    return TemplateResponse(request, "admin/_reject_form.html", {"entry_id": entry_id})


# ---- Hilfsfunktion (einmalig in admin.py definieren) ----
from fastapi.responses import Response as _Response
from fastapi.responses import RedirectResponse as _Redirect

def _htmx_redirect(request: Request, url: str):
    """HTMX-Response: setzt HX-Redirect-Header (HTMX-Seitennavigation) oder
    gibt 303-Redirect für normalen Browser zurück."""
    if request.headers.get("HX-Request"):
        resp = _Response(status_code=204)
        resp.headers["HX-Redirect"] = url
        return resp
    return _Redirect(url=url, status_code=303)
```

**Wichtig:** `datetime` und `timezone` sind in `admin.py` (Zeile 11) bereits importiert. `Form` aus `fastapi` ist bereits importiert (Upload-Routes). `uuid` ist aus Story 3.5 bereits importiert. Existenz aller Imports prüfen, bevor ergänzt wird.

**SQLAlchemy-`update()`**: Erfordert `from sqlalchemy import update` — das Statement wird als Bulk-Update ausgeführt (kein ORM-Select nötig). Sicher mit SQLite (Tests) und Postgres (Prod).

### Task 3: `admin/_reject_form.html`

```html
{# Reines Fragment — kein extends, kein block. Eingebettet via hx-get-Swap. #}
<form hx-post="/admin/review-queue/{{ entry_id }}/reject"
      hx-push-url="false"
      class="mt-2 space-y-2">
  <textarea name="reason"
            rows="2"
            required
            placeholder="Begründung (Pflicht)"
            class="w-full rounded border border-slate-300 px-2 py-1 text-sm focus:ring-1 focus:ring-red-400 focus:outline-none"></textarea>
  <div class="flex gap-2">
    <button type="submit"
            class="px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded text-sm">
      Reject bestätigen
    </button>
    <button type="button"
            onclick="this.closest('div[id]').innerHTML=''"
            class="px-3 py-1 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded text-sm">
      Abbrechen
    </button>
  </div>
</form>
```

Das Fragment hat kein eigenes `hx-target` — der Submit-Button erbt die HTMX-Attribute vom Form-Element. Der Form-POST an `…/reject` löst nach Erfolg einen `HX-Redirect`-Header aus, HTMX navigiert die Vollseite zur Queue. Das Inline-JS im Abbrechen-Button (`onclick`) ist das einzige JS in dieser Story — bewusst minimal, kein Framework-Overhead.

### Task 5: `_review_queue_rows.html` anpassen

**Vor Editieren lesen**: `app/templates/admin/_review_queue_rows.html` vollständig lesen (Story 3.5 hat sie angelegt).

Spalte "Aktion" pro `<tr>`:
```html
<td class="px-3 py-2 whitespace-nowrap">
  <button hx-post="/admin/review-queue/{{ item.entry.id }}/approve"
          hx-confirm="Vorschlag für '{{ item.entry.field_name }}' freigeben?"
          hx-push-url="false"
          class="px-2 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-xs font-medium">
    Approve
  </button>
  <button hx-get="/admin/review-queue/{{ item.entry.id }}/reject-form"
          hx-target="#reject-area-{{ item.entry.id | replace('-', '') }}"
          hx-swap="innerHTML"
          class="ml-2 px-2 py-1 bg-red-600 hover:bg-red-700 text-white rounded text-xs font-medium">
    Reject
  </button>
  <div id="reject-area-{{ item.entry.id | replace('-', '') }}" class="mt-1"></div>
</td>
```

**Jinja2-Filter `replace`**: `item.entry.id | string | replace('-', '')` produziert eine gültige HTML-ID ohne Bindestriche.

**Tabellenkopf** in `review_queue.html` (ebenfalls aus Story 3.5): `<th>` für die neue "Aktion"-Spalte anhängen. Stelle via `grep -n "Alter" app/templates/admin/review_queue.html` finden.

### Task 6: Tests `tests/test_review_queue_approve_reject.py`

```python
import uuid
from datetime import datetime, timezone

from app.models.governance import ReviewQueueEntry, FieldProvenance
from app.models import AuditLog, Object
from sqlalchemy import select


def _make_object(db, short_code="TST1"):
    """Minimales Ziel-Object für Write-Gate."""
    obj = Object(id=uuid.uuid4(), short_code=short_code, name="Test-Objekt")
    db.add(obj)
    db.flush()
    return obj


def _make_pending_entry(db, obj: Object, field_name="heating_type", proposed="Fernwärme"):
    """pending ReviewQueueEntry mit Ziel-Object."""
    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=obj.id,
        field_name=field_name,
        proposed_value={"value": proposed},
        agent_ref="test-agent-v1",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
    )
    db.add(entry)
    db.commit()
    return entry


def test_approve_sets_status(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    # Expect 204 (HTMX-Redirect) or 303 (Full-Nav) — beide sind OK
    assert resp.status_code in (204, 303)
    db.expire_all()
    updated = db.get(ReviewQueueEntry, entry.id)
    assert updated.status == "approved"
    assert updated.decided_by_user_id is not None
    assert updated.decided_at is not None


def test_approve_writes_field(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj, field_name="heating_type", proposed="Fernwärme")
    steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    db.expire_all()
    obj_updated = db.get(Object, obj.id)
    assert obj_updated.heating_type == "Fernwärme"


def test_approve_creates_audit_log(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj)
    steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    logs = db.execute(
        select(AuditLog).where(AuditLog.action == "review_queue_approved")
    ).scalars().all()
    assert len(logs) == 1


def test_approve_supersedes_other_pending(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry_a = _make_pending_entry(db, obj, field_name="heating_type", proposed="Gas")
    entry_b = _make_pending_entry(db, obj, field_name="heating_type", proposed="Fernwärme")
    # Approve entry_b → entry_a soll auf superseded wechseln
    steckbrief_admin_client.post(f"/admin/review-queue/{entry_b.id}/approve")
    db.expire_all()
    assert db.get(ReviewQueueEntry, entry_a.id).status == "superseded"
    assert db.get(ReviewQueueEntry, entry_b.id).status == "approved"


def test_reject_sets_status(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "Falsches Feld"},
    )
    assert resp.status_code in (204, 303)
    db.expire_all()
    updated = db.get(ReviewQueueEntry, entry.id)
    assert updated.status == "rejected"
    assert updated.decision_reason == "Falsches Feld"


def test_reject_no_field_write(steckbrief_admin_client, db):
    obj = _make_object(db)
    original_heating = obj.heating_type
    entry = _make_pending_entry(db, obj, field_name="heating_type", proposed="Solar")
    steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "Korrekturfehler"},
    )
    db.expire_all()
    assert db.get(Object, obj.id).heating_type == original_heating


def test_reject_missing_reason_returns_400(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": ""},
    )
    assert resp.status_code == 400


def test_approve_already_approved_returns_400(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj)
    steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    resp = steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    assert resp.status_code == 400


def test_approve_no_permission_returns_403(auth_client, db):
    # auth_client = test_user ohne objects:approve_ki
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj)
    resp = auth_client.post(f"/admin/review-queue/{entry.id}/approve")
    assert resp.status_code == 403
```

**Hinweis zu `_make_object`**: Die `Object`-Klasse hat Pflichtfelder — `short_code` und `name` sind ausreichend für v1 (alle anderen Felder nullable). Kein `db.commit()` vor `flush()` nötig (SQLite statische Session in Tests).

**`db.expire_all()`**: Nach einem POST über den TestClient ist die DB-Session des Tests nicht automatisch aktualisiert. `expire_all()` zwingt das ORM, beim nächsten `db.get()` frische Daten zu laden.

**`Object.heating_type`**: Dieses Feld existiert in `app/models/Object` als String-Spalte (aus Story 1.2 / `0010_steckbrief_core.py`). Wenn es nicht nullable ist, muss in `_make_object` ein Default gesetzt werden (z.B. `heating_type=None` falls nullable, oder `heating_type="Gas"` als Initial-Wert).

### Keine neue Migration nötig

`ReviewQueueEntry` in `app/models/governance.py` hat alle benötigten Felder bereits (`decided_at`, `decided_by_user_id`, `decision_reason`, `status`). Neueste Migration: `0016_wartungspflichten_missing_fields.py`. Falls neue Spalten nötig wären, wäre `down_revision = "0016"` zu setzen — hier entfällt das.

### Write-Gate-Verhalten bei Superseding

`approve_review_entry()` wirft `ValueError` wenn `write_result.skipped == True` (z.B. Feld hat schon denselben Wert mit `source="ai_suggestion"`). Das ist ein korrektes Verhalten und der Router behandelt das als 400. Das Superseding-Update wird dann **nicht** ausgeführt (da der `try`-Block abbricht). In v1 ist das akzeptabel — Doppel-Approve auf identischen Wert ist ein Edge-Case.

### Muster für HTMX-Redirect aus anderen Routen

Pattern aus `admin.py` (Write-Routes wie `POST /admin/users/{id}`) prüfen — möglicherweise ist `_htmx_redirect` dort schon definiert oder ähnlich gelöst. Bestehende Pattern nicht duplizieren.

## Test-Checkliste (Epic-2-Retro P1)

- [ ] **Permission-Matrix**: Unauthenticated → 302, kein `approve_ki` → 403, `approve_ki` → Approve/Reject (Tests 6.9, 6.10)
- [ ] **IDOR**: URL-Pfad-FK `entry_id` — portfolio-weite Permission, kein objekt-spezifisches Gate nötig in v1
- [ ] **Race-Condition (Doppelklick)**: bereits approved/rejected → 400 (Test 6.9)
- [ ] **Pflichtfeld-Validation**: Leerer Reject-Reason → 400 (Test 6.8)
- [ ] **Atomic Commit**: approve_review_entry + Superseding-Update + db.commit() in einer Transaktion (kein Zwischen-Commit)
- [ ] **Superseding**: 2 Entries gleiches Feld+Entity → Approve 1 → Anderer auf `superseded` (Test 6.5)
- [ ] **Kein Field-Write beim Reject**: Zielfeld bleibt unverändert (Test 6.7)
- [ ] **Empty-State nicht gebrochen**: Nach Approve einer Queue mit 1 Entry zeigt `/admin/review-queue` "Keine Vorschläge offen" (via redirect + reload)
- [ ] **Date-Bounds**: `created_at` in Tests mit `datetime(2025, 1, 15, tzinfo=timezone.utc)` (mid-month per `feedback_date_tests_pick_mid_month.md`)

## Neue Dateien

- `app/templates/admin/_reject_form.html`
- `tests/test_review_queue_approve_reject.py`

## Geänderte Dateien

- `app/routers/admin.py` — `approve_entry()`, `reject_entry()`, `reject_form_fragment()`, `_htmx_redirect()` hinzufügen; Imports ergänzen
- `app/templates/admin/_review_queue_rows.html` — Aktionsspalte mit Approve/Reject-Buttons + Inline-Reject-Area
- `app/templates/admin/review_queue.html` — `<th>`-Spalte "Aktion" ergänzen

## References

- `approve_review_entry()` / `reject_review_entry()`: `app/services/steckbrief_write_gate.py:400–517`
- `WriteGateError`: `app/services/steckbrief_write_gate.py:56`
- `ReviewQueueEntry`-Modell: `app/models/governance.py:49–98`
- `objects:approve_ki` Permission: `app/permissions.py:55`
- `steckbrief_admin_client` Fixture (inkl. User-Perms): `tests/conftest.py:190–225`
- Superseding-AC: `output/planning-artifacts/epics.md` — Story 3.6 AC3
- Migration (neueste): `migrations/versions/0016_wartungspflichten_missing_fields.py`
- Write-Gate-Test-Muster: `tests/test_write_gate_unit.py` (falls vorhanden)
- HTMX-Fragment-Pattern: `output/implementation-artifacts/3-5-review-queue-admin-ui-mit-filtern.md`
- Audit-Log-Actions: `app/services/audit.py`
- Date-Bounds Memory: `memory/feedback_date_tests_pick_mid_month.md`
- SQLAlchemy-`update()`: SQLAlchemy 2.0-Bulk-Update Pattern (analog zu `admin.py` — vorhandene Patterns prüfen)

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

### Completion Notes List

### File List
