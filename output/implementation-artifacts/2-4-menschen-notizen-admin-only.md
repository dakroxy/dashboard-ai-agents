# Story 2.4: Menschen-Notizen admin-only

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Admin mit `objects:view_confidential`,
ich möchte Notizen zu Eigentümern (z. B. "Beirat, kritisch bei Beschlüssen") pflegen, die für normale User unsichtbar bleiben,
damit heikle Kontext-Informationen nicht jedem zugänglich sind, aber für Admin-Vorbereitung verfügbar bleiben.

## Abhängigkeiten

**Story 2.0 und Story 2.1 müssen implementiert sein**, bevor Story 2.4 beginnt.

- **Story 2.0** etabliert den `objects:view_confidential`-Enforcement-Pattern (Zugangscodes), den Story 2.4 für Menschen-Notizen 1:1 übernimmt. Canonical Pattern steht in den Dev Notes von Story 2.0.
- **Story 2.1** führt den `_load_accessible_object(db, object_id, user)`-Helper in `app/routers/objects.py` ein (Story 2.1 Task 5.2) — Story 2.4 nutzt ihn in allen drei Routes (Task 3.1–3.3). Außerdem fügt 2.1 `{% include "_obj_versicherungen.html" %}` in `object_detail.html` als Insertion-Anchor für Task 2.4 hinzu.

## Acceptance Criteria

**AC1 — Admin sieht Menschen-Notizen-Sektion**

**Given** ich bin als Admin mit `objects:view_confidential` eingeloggt
**When** ich `/objects/{id}` öffne
**Then** sehe ich eine "Menschen"-Sektion mit einer Tabelle aller Eigentümer
**And** jeder Eigentümer zeigt Name + Note-Feld (leer oder gespeicherten Text) + Edit-Button

**AC2 — Normaler User sieht keine Menschen-Notizen**

**Given** ich bin als normaler User **ohne** `objects:view_confidential`
**When** ich dieselbe Detailseite öffne
**Then** ist die gesamte "Menschen"-Sektion nicht gerendert (nicht einmal leere Felder oder Überschrift)
**And** ein direkter `POST /objects/{id}/menschen-notizen/{eid}` gibt 403 — serverseitig, nicht nur UI

**AC3 — Notiz speichern via Write-Gate**

**Given** ich bearbeite und speichere eine Notiz als Admin
**When** der Write läuft
**Then** geht er durch `write_field_human` mit `field="notes_owners"`, vollständigem JSONB-Dict-Replacement (nicht Dict-Mutation), `source="user_edit"`
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` existiert

**AC4 — Inline-Edit**

**Given** ich klicke "Edit" bei einem Eigentümer
**When** das HTMX-Fragment geladen wird
**Then** erscheint ein Textarea mit dem aktuellen Note-Text
**And** Speichern ersetzt das Fragment zurück auf View-Modus
**And** Abbrechen kehrt ohne Save zum View-Modus zurück

**AC5 — Tests**

**Given** neue Datei `tests/test_menschen_notizen_unit.py`
**When** `pytest -x` läuft
**Then** alle bestehenden Tests + neue Unit-Tests sind grün

## Tasks / Subtasks

- [x] **Task 1 — Keine Migration** (Vorab-Check)

  > `notes_owners` ist bereits als JSONB-Spalte auf `Object` definiert:
  > `app/models/object.py` Zeile 88–90:
  > ```python
  > notes_owners: Mapped[dict[str, Any]] = mapped_column(
  >     JSONB, nullable=False, default=dict, server_default="{}"
  > )
  > ```
  > Neueste Migration: `0014_steckbrief_photos_fields.py`. Vor Task 2 prüfen:
  > `ls migrations/versions/` — wenn nach Story 2.0–2.3 neue Migrationen existieren,
  > keinen Down-Revision-Fehler einbauen (diese Story braucht keine Migration).

  - [x] 1.1 Bestätigen: `notes_owners` auf `Object` vorhanden (kein neues Feld, keine Migration nötig)

- [x] **Task 2 — `object_detail`-Handler erweitern** (AC1, AC2)

  In `app/routers/objects.py`, Funktion `object_detail`:

  - [x] 2.1 Imports prüfen (am Datei-Anfang):
    ```python
    from app.permissions import has_permission  # ggf. bereits vorhanden nach Story 2.0
    ```

  - [x] 2.2 Vor dem `return templates.TemplateResponse(...)` einen neuen Block einfügen:
    ```python
    # --- Menschen-Notizen (Story 2.4, nur für view_confidential) ---
    notes_owners: dict | None = None
    if has_permission(user, "objects:view_confidential"):
        notes_owners = dict(detail.obj.notes_owners or {})
    ```

  - [x] 2.3 Im `context`-Dict des `TemplateResponse`-Aufrufs ergänzen:
    ```python
    "notes_owners": notes_owners,
    ```
    Hinweis: Der Wert ist `None` für User ohne `view_confidential` und ein Dict (ggf. leer)
    für Admins. Das Template prüft `has_permission(user, "objects:view_confidential")`.

  - [x] 2.4 Im Template `object_detail.html` den Include nach den
    bestehenden Sektion-Includes hinzufügen (nach Story 2.1 liegt
    `_obj_versicherungen.html` zwischen `_obj_technik.html` und dem
    Menschen-Block — Menschen gehört ans Ende):
    ```html
    {% include "_obj_menschen.html" %}
    ```

- [x] **Task 3 — Drei Inline-Edit-Routen in `objects.py`** (AC2, AC3, AC4)

  Alle Routen unter `@router` in `app/routers/objects.py`. Imports, die ggf. ergänzt werden müssen:
  ```python
  from sqlalchemy import select
  from app.models.person import Eigentuemer
  ```
  `Eigentuemer` ist in `app/models/person.py`. Prüfen ob `from app.models import Eigentuemer`
  bereits (via `__init__.py`) verfügbar — falls nicht: expliziter Import.

  - [x] 3.1 **GET view-Fragment** `GET /{object_id}/menschen-notizen/{eigentuemer_id}/view`:
    ```python
    @router.get("/{object_id}/menschen-notizen/{eigentuemer_id}/view", response_class=HTMLResponse)
    async def notiz_view(
        object_id: uuid.UUID,
        eigentuemer_id: uuid.UUID,
        request: Request,
        user: User = Depends(require_permission("objects:view_confidential")),
        db: Session = Depends(get_db),
    ):
        obj = _load_accessible_object(db, object_id, user)
        eig = db.get(Eigentuemer, eigentuemer_id)
        if not eig or eig.object_id != obj.id:
            raise HTTPException(404, detail="Eigentümer nicht gefunden")
        note_text = (obj.notes_owners or {}).get(str(eigentuemer_id)) or ""
        return templates.TemplateResponse(
            request, "_obj_notiz_view.html",
            {"obj": obj, "eig": eig, "note_text": note_text, "user": user},
        )
    ```

  - [x] 3.2 **GET edit-Fragment** `GET /{object_id}/menschen-notizen/{eigentuemer_id}/edit`:
    ```python
    @router.get("/{object_id}/menschen-notizen/{eigentuemer_id}/edit", response_class=HTMLResponse)
    async def notiz_edit(
        object_id: uuid.UUID,
        eigentuemer_id: uuid.UUID,
        request: Request,
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        if not has_permission(user, "objects:view_confidential"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Keine Berechtigung für vertrauliche Felder")
        obj = _load_accessible_object(db, object_id, user)
        eig = db.get(Eigentuemer, eigentuemer_id)
        if not eig or eig.object_id != obj.id:
            raise HTTPException(404, detail="Eigentümer nicht gefunden")
        note_text = (obj.notes_owners or {}).get(str(eigentuemer_id)) or ""
        return templates.TemplateResponse(
            request, "_obj_notiz_edit.html",
            {"obj": obj, "eig": eig, "note_text": note_text, "user": user},
        )
    ```

  - [x] 3.3 **POST save** `POST /{object_id}/menschen-notizen/{eigentuemer_id}`:
    ```python
    @router.post("/{object_id}/menschen-notizen/{eigentuemer_id}", response_class=HTMLResponse)
    async def notiz_save(
        object_id: uuid.UUID,
        eigentuemer_id: uuid.UUID,
        request: Request,
        note: str | None = Form(None),
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        if not has_permission(user, "objects:view_confidential"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Keine Berechtigung für vertrauliche Felder")
        obj = _load_accessible_object(db, object_id, user)
        eig = db.get(Eigentuemer, eigentuemer_id)
        if not eig or eig.object_id != obj.id:
            raise HTTPException(404, detail="Eigentümer nicht gefunden")

        # JSONB-sicherer Write: KEIN direktes Dict-Mutieren, Full-Replace via Write-Gate
        new_notes = dict(obj.notes_owners or {})
        note_clean = (note or "").strip()
        if note_clean:
            new_notes[str(eigentuemer_id)] = note_clean
        else:
            new_notes.pop(str(eigentuemer_id), None)

        write_field_human(
            db, entity=obj, field="notes_owners", value=new_notes,
            source="user_edit", user=user, request=request,
        )
        db.commit()

        note_text = new_notes.get(str(eigentuemer_id)) or ""
        return templates.TemplateResponse(
            request, "_obj_notiz_view.html",
            {"obj": obj, "eig": eig, "note_text": note_text, "user": user},
        )
    ```
    Import `write_field_human` prüfen: kommt aus `app.services.steckbrief_write_gate`
    (wurde in Story 1.6 in `objects.py` hinzugefügt, ist also bereits verfügbar).

- [x] **Task 4 — Template `app/templates/_obj_menschen.html`** (neu) (AC1, AC2)

  Neue Datei. Vollständiger Inhalt:
  ```html
  {# Menschen-Sektion: Eigentümer-Liste + Admin-only Notes. Sektion nur für
     view_confidential sichtbar. #}
  {% if has_permission(user, "objects:view_confidential") %}
  <section class="rounded-lg bg-white border border-slate-200 p-6 mb-6" data-section="menschen">
      <h2 class="text-lg font-semibold text-slate-900 mb-4">Menschen</h2>

      {% if eigentuemer %}
      <table class="w-full text-sm">
          <thead class="text-xs uppercase tracking-wide text-slate-500 bg-slate-50 border-b border-slate-200">
              <tr>
                  <th class="text-left px-3 py-2 font-semibold w-1/3">Name</th>
                  <th class="text-left px-3 py-2 font-semibold">Notiz (nur Admin)</th>
              </tr>
          </thead>
          <tbody>
              {% for eig in eigentuemer %}
              <tr class="border-t border-slate-100">
                  <td class="px-3 py-2 text-slate-800 font-medium align-top">{{ eig.name }}</td>
                  <td class="px-3 py-2 align-top">
                      {% set note_text = (notes_owners or {}).get(eig.id | string) or "" %}
                      {% include "_obj_notiz_view.html" %}
                  </td>
              </tr>
              {% endfor %}
          </tbody>
      </table>
      {% else %}
      <p class="text-sm text-slate-500 italic">Noch kein Eigentümer erfasst.</p>
      {% endif %}
  </section>
  {% endif %}
  ```
  Hinweis: `eig.id | string` ist Jinja2-Filter für `str(uuid)`. `notes_owners` kommt aus
  dem context dict (via Task 2.2) — ist Dict für Admins, None für normale User.
  Das äußere `{% if has_permission(...) %}` ist redundant zum Router-Gate, aber
  verhindert leckende leere Sektionen falls `notes_owners=None` durch `object_detail`
  durchrutscht.

- [x] **Task 5 — Template `app/templates/_obj_notiz_view.html`** (neu) (AC1, AC4)

  Neue Datei. Enthält das per-Eigentümer View-Fragment (Container-ID für HTMX-Swap):
  ```html
  {# View-Fragment für eine einzelne Eigentümer-Notiz.
     Container-ID = `notiz-{eig.id}`, damit HTMX outerHTML-Swap trifft. #}
  <div id="notiz-{{ eig.id }}">
      {% if note_text %}
      <p class="text-sm text-slate-800 whitespace-pre-wrap">{{ note_text }}</p>
      {% else %}
      <span class="text-slate-400 text-sm">—</span>
      {% endif %}
      {% if has_permission(user, "objects:edit") and has_permission(user, "objects:view_confidential") %}
      <button type="button"
              hx-get="/objects/{{ obj.id }}/menschen-notizen/{{ eig.id }}/edit"
              hx-target="#notiz-{{ eig.id }}"
              hx-swap="outerHTML"
              class="mt-1 text-xs text-sky-600 hover:text-sky-900">
          Bearbeiten
      </button>
      {% endif %}
  </div>
  ```

- [x] **Task 6 — Template `app/templates/_obj_notiz_edit.html`** (neu) (AC4)

  Neue Datei. Enthält das per-Eigentümer Edit-Fragment (Container-ID muss identisch mit View sein):
  ```html
  {# Edit-Fragment für eine einzelne Eigentümer-Notiz.
     Selbe Container-ID wie View-Fragment damit Cancel/Save-Swap korrekt trifft. #}
  <div id="notiz-{{ eig.id }}">
      <form hx-post="/objects/{{ obj.id }}/menschen-notizen/{{ eig.id }}"
            hx-target="#notiz-{{ eig.id }}"
            hx-swap="outerHTML">
          <textarea name="note"
                    rows="3"
                    placeholder="Notiz zu {{ eig.name }} …"
                    class="block w-full rounded border border-slate-300 px-2 py-1 text-sm resize-y">{{ note_text }}</textarea>
          <div class="flex items-center gap-2 mt-1.5">
              <button type="submit"
                      class="text-xs px-2 py-0.5 rounded bg-sky-600 text-white hover:bg-sky-700">
                  Speichern
              </button>
              <button type="button"
                      hx-get="/objects/{{ obj.id }}/menschen-notizen/{{ eig.id }}/view"
                      hx-target="#notiz-{{ eig.id }}"
                      hx-swap="outerHTML"
                      class="text-xs text-slate-500 hover:text-slate-900">
                  Abbrechen
              </button>
          </div>
      </form>
  </div>
  ```

- [x] **Task 7 — Tests `tests/test_menschen_notizen_unit.py`** (AC2, AC3, AC5)

  Neue Datei anlegen. Muster aus `tests/test_zugangscodes_routes_smoke.py` (Story 2.0) übernehmen:

  - [x] 7.1 Fixtures:
    - `admin_user` mit `permissions_extra=["objects:view", "objects:edit", "objects:view_confidential"]`
    - `normal_user` mit `permissions_extra=["objects:view", "objects:edit"]` — OHNE `view_confidential`
    - `admin_client` (TestClient mit `admin_user`)
    - `normal_client` (TestClient mit `normal_user`)
    - `test_obj` — ein `Object`-Eintrag mit `notes_owners={}` in der Test-DB
    - `test_eig` — ein `Eigentuemer`-Eintrag mit `object_id=test_obj.id`

  - [x] 7.2 `test_notiz_save_writes_via_write_gate`:
    - `admin_client.post(f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}", data={"note": "Beirat"})` → Status 200
    - DB: `FieldProvenance` mit `entity_type="object"`, `field_name="notes_owners"`, `source="user_edit"` existiert
    - DB: `AuditLog`-Eintrag mit `action="object_field_updated"`, `entity_id=test_obj.id` existiert (AC3 — Pattern aus `tests/test_zugangscodes_routes_smoke.py:181-184`):
      ```python
      audit = (
          db.query(AuditLog)
          .filter(AuditLog.action == "object_field_updated",
                  AuditLog.entity_id == test_obj.id)
          .order_by(AuditLog.created_at.desc())
          .first()
      )
      assert audit is not None
      assert audit.details["field"] == "notes_owners"
      ```
      Import ergänzen: `from app.models import AuditLog`.
    - DB: `db.refresh(test_obj)` dann `test_obj.notes_owners[str(test_eig.id)] == "Beirat"`
      (Refresh nötig, da `write_field_human` via `flag_modified` persistiert und der
      Request-Handler mit einer anderen Session-View arbeiten kann als die Test-DB-Fixture).

  - [x] 7.3 `test_notiz_delete_on_empty_string`:
    - `test_obj.notes_owners` vorbelegen: `{str(test_eig.id): "Alt"}` (danach `db.commit()`)
    - `admin_client.post(..., data={"note": ""})` → Status 200
    - `db.refresh(test_obj)` dann `test_obj.notes_owners.get(str(test_eig.id))` ist `None`

  - [x] 7.4 `test_notiz_save_blocked_without_view_confidential`:
    - `normal_client.post(f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}", data={"note": "X"})` → Status 403

  - [x] 7.5 `test_notiz_edit_get_blocked_without_view_confidential`:
    - `normal_client.get(f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}/edit")` → Status 403

  - [x] 7.6 `test_notiz_view_get_blocked_without_view_confidential`:
    - `normal_client.get(f"/objects/{test_obj.id}/menschen-notizen/{test_eig.id}/view")` → Status 403

- [x] **Task 8 — Regression + Smoke** (AC5)
  - [x] 8.1 `pytest -x` — alle Tests grün (612/612, inkl. 5 neue)
  - [ ] 8.2 Manuelle Verifikation: Admin → Menschen-Sektion sichtbar, Notiz speichern, Edit/Cancel. Normal User → Sektion komplett weg.

## Dev Notes

### Was bereits existiert (NICHT neu anlegen)

- **`notes_owners`-Feld**: `Object.notes_owners` (JSONB, nullable=False, default `{}`) — existiert seit
  `app/models/object.py` Zeile 88. **Keine Migration nötig.**
- **Permission `objects:view_confidential`**: bereits in `app/permissions.py` Zeile 57–60 registriert.
  Label nach Story 2.0: `"Vertrauliche Felder lesen"`. Kein neuer Key nötig.
- **`has_permission`**: Python-Funktion in `app/permissions.py:127` + Jinja2-Global in `app/templating.py`.
- **`require_permission`**: FastAPI-Dependency-Factory in `app/permissions.py:133`.
- **`write_field_human`**: in `app/services/steckbrief_write_gate.py`. Importiert in `objects.py`
  bereits ab Story 1.2+. Falls nicht vorhanden: `from app.services.steckbrief_write_gate import write_field_human`.
- **`Eigentuemer`-Model**: `app/models/person.py`, `__tablename__ = "eigentuemer"`,
  Felder: `id (UUID)`, `object_id`, `name`, `email`, `phone`, `impower_contact_id`, `voting_stake_json`.
- **`_load_accessible_object`-Helper**: in `app/routers/objects.py` — lädt Object + prüft
  `accessible_object_ids`, wirft 404 bei kein Zugriff. Signatur: `(db, object_id, user) → Object`.
  Eingeführt in Story 2.1 Task 5.2. **Nicht mit einem vermeintlichen `_load_object` verwechseln**
  — den gibt es nicht (Story 2.3 Task 0 warnt explizit davor).

### JSONB-Write-Muster (KRITISCH: nicht Dict mutieren)

`notes_owners` ist JSONB. SQLAlchemy trackt keine tiefe Mutation — direktes
`obj.notes_owners[key] = value` wird **nicht persistiert** ohne `flag_modified`.
Das Write-Gate (`write_field_human`) erledigt `flag_modified` intern (via `copy.deepcopy` + `setattr`).

**Korrektes Muster** (wie in Task 3.3 implementiert):
```python
new_notes = dict(obj.notes_owners or {})   # shallow copy des top-level Dict
new_notes[str(eigentuemer_id)] = note_text  # Mutation auf der Kopie
write_field_human(db, entity=obj, field="notes_owners", value=new_notes, ...)
```

**FALSCH** (darf nicht verwendet werden):
```python
obj.notes_owners[str(eigentuemer_id)] = note_text  # Direkte Mutation → kein Persist
```

### Canonical Pattern aus Story 2.0

Story 2.0 etablierte den `view_confidential`-Enforcement für Zugangscodes. Story 2.4 übernimmt
exakt dasselbe Muster:

| Route-Typ | Dependency | In-Handler-Check |
|---|---|---|
| GET view-Fragment | `require_permission("objects:view_confidential")` | — |
| GET edit-Fragment | `require_permission("objects:edit")` | `has_permission(user, "objects:view_confidential")` |
| POST save | `require_permission("objects:edit")` | `has_permission(user, "objects:view_confidential")` |

Dieses Muster verhindert, dass ein "read-only-admin" (hat `view_confidential`, aber nicht `objects:edit`)
Notizen schreiben kann, aber trotzdem lesen kann.

### Template-Variable für `notes_owners`

Im `object_detail`-Handler wird `notes_owners` als `dict | None` übergeben:
- `None` für User ohne `view_confidential` — Template-Sektion komplett kein Render
- `{}` oder befülltes Dict für Admins

In `_obj_menschen.html` der Zugriff:
```html
{% set note_text = (notes_owners or {}).get(eig.id | string) or "" %}
```
`eig.id | string` ist der Jinja2-Filter für `str(uuid.UUID)` — gibt z.B.
`"3f4a1b2c-..."` zurück. Entspricht dem Dict-Key `str(eigentuemer_id)` aus dem Router.

### HTMX-Container-ID Konvention

Container-ID für HTMX-Swap: `notiz-{eig.id}` (UUID ohne Stripping).
Konsistent über View- und Edit-Fragment: beide HTML-Containers müssen die gleiche
`id="notiz-{{ eig.id }}"` tragen, sonst läuft `hx-swap="outerHTML"` ins Leere.

`_obj_notiz_view.html` wird auch aus `_obj_menschen.html` via `{% include %}` gerendert
(Zeile mit `{% include "_obj_notiz_view.html" %}` im `<td>`). Dort muss `eig` + `note_text`
im Jinja2-Context verfügbar sein — beides wird via `{% set %}` vor dem Include gesetzt.

### `_load_accessible_object`-Helper (aus Story 2.1)

Story 2.1 legt in `app/routers/objects.py` diesen zentralen Access-Guard an:
```python
def _load_accessible_object(
    db: Session, object_id: uuid.UUID, user: User
) -> Object:
    """Laedt Object oder wirft 404 — prueft accessible_object_ids."""
    accessible = accessible_object_ids(db, user)
    detail = get_object_detail(db, object_id, accessible_ids=accessible)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden",
        )
    return detail.obj
```
**Nutzung in allen drei Menschen-Notizen-Routes identisch**: `obj = _load_accessible_object(db, object_id, user)`.
Der Helper berechnet `accessible_object_ids` selbst — das Set NICHT extern ermitteln
und übergeben.

### db.commit() im Router, nicht im Service

Kein `db.commit()` in `write_field_human` oder anderen Service-Helpern — der Router committed.
Muster aus Story 2.3: `write_field_human(...)` → `db.commit()` im Route-Handler. Genau so in Task 3.3.

### TemplateResponse-Signatur (Starlette ≥ 0.21)

IMMER: `templates.TemplateResponse(request, "template.html", {...})` — Request als ERSTES Argument.
NICHT: `templates.TemplateResponse("template.html", {"request": request, ...})` → TypeError.

### Nicht in Story 2.4 (Deferred)

- **Eigentümer-Kontaktdaten editieren** — nur Notes; Name/Email/Phone-Edit ist separater Scope.
- **Notizen für Mieter** — nur Eigentümer-Notizen im Scope dieser Story.
- **Notiz-History / Provenance-Anzeige im Template** — Provenance wird geschrieben, aber
  kein UI-Display geplant. Eine Inline-Pill wie bei Technik-Feldern wäre nett, ist aber deferred.
- **Freitextsuche über Notes** — kein Such-Index nötig in v1.

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

Keine besonderen Debug-Schritte nötig — alle Tasks liefen auf Anhieb durch. uv als Package-Manager identifiziert und `.venv` via `uv add --dev pytest pytest-asyncio` angelegt.

### Completion Notes List

- `notes_owners` war bereits als JSONB-Spalte auf `Object` vorhanden (Zeile 88–90) — keine Migration nötig.
- `Eigentuemer` zu den Imports in `objects.py` hinzugefügt (war bereits in `app.models.__init__` exportiert).
- `notes_owners`-Block im `object_detail`-Handler nach dem Zugangscode-Block eingefügt (AC2: `None` für normale User, `dict` für Admins).
- `notes_owners` zum Context-Dict des TemplateResponse hinzugefügt.
- `{% include "_obj_menschen.html" %}` am Ende von `object_detail.html` (nach `_obj_versicherungen.html`) ergänzt.
- Drei neue Routen (GET view, GET edit, POST save) am Ende von `objects.py` unter "Menschen-Notizen"-Kommentarblock — exakt nach dem in der Story definierten Canonical-Permission-Pattern (view: `require_permission("objects:view_confidential")`, edit/save: `require_permission("objects:edit")` + In-Handler-Check auf `view_confidential`).
- JSONB-Write-Muster korrekt: `dict(obj.notes_owners or {})` kopiert, dann `write_field_human` mit dem neuen Dict — kein direktes Dict-Mutieren.
- 5 neue Unit-Tests in `tests/test_menschen_notizen_unit.py` — alle grün.
- Vollständige Regression-Suite: 612/612 Tests grün, keine Regressions.

### File List

- `app/routers/objects.py` (geändert — Eigentuemer-Import, notes_owners-Block, 3 neue Routen)
- `app/templates/object_detail.html` (geändert — Include _obj_menschen.html)
- `app/templates/_obj_menschen.html` (neu)
- `app/templates/_obj_notiz_view.html` (neu)
- `app/templates/_obj_notiz_edit.html` (neu)
- `tests/test_menschen_notizen_unit.py` (neu)
- `pyproject.toml` (geändert — pytest/pytest-asyncio als dev-Abhängigkeiten via uv hinzugefügt)
- `uv.lock` (geändert — von uv automatisch aktualisiert)
