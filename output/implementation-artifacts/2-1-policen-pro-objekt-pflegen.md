# Story 2.1: Policen pro Objekt pflegen

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter mit `objects:edit`,
ich möchte Versicherungspolicen mit Versicherer, Laufzeit und Kündigungsfrist pro Objekt anlegen und bearbeiten,
damit das Portfolio der Policen an jedem Objekt sichtbar und aktuell ist.

## Acceptance Criteria

**AC1 — Neue Police anlegen**

**Given** ich öffne `/objects/{id}` und die Versicherungs-Sektion
**When** ich auf "Neue Police" klicke und die Form ausfülle (Versicherer aus Dropdown, Policen-Nr., Produkt-Typ, `start_date`, `end_date`, `next_main_due`, `notice_period_months`, Prämie p.a.)
**Then** wird nach Submit die Police als `InsurancePolicy` mit FK `versicherer_id` + FK `object_id` angelegt
**And** alle Feld-Writes laufen über `write_field_human`
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` mit `entity_type="police"` existiert

**AC2 — Policen-Liste anzeigen + Edit/Löschen**

**Given** eine angelegte Police
**When** ich die Versicherungs-Sektion neu lade
**Then** sehe ich die Police in einer Zeile mit Versicherer, Produkt-Typ, Ablauf-Datum (`next_main_due`), Kündigungsfrist und Prämie
**And** jede Zeile hat Edit- und Löschen-Buttons (nur wenn `objects:edit`)
**And** Löschen entfernt den Record und schreibt `AuditLog action="registry_entry_updated"` mit `details_json.action="delete"`

**AC3 — Neuer Versicherer via Inline-Sub-Formular**

**Given** ein Versicherer existiert noch nicht in der Registry
**When** ich im Police-Formular auf den Button "+ Neuer Versicherer" (direkt neben dem Versicherer-Dropdown) klicke
**Then** laedt HTMX via `GET /registries/versicherer/new-form` ein Sub-Formular in den Container `#new-versicherer-inline` — mit Pflichtfeld Name und optionalen Feldern Adresse, Kontakt-Email, Kontakt-Tel
**And** nach Submit ist der neue `Versicherer`-Record persistiert
**And** ein `AuditLog`-Eintrag `action="registry_entry_created"` mit `entity_type="versicherer"` existiert
**And** der Server antwortet mit zwei OOB-Fragmenten: (a) neues Dropdown `#versicherer-dropdown` mit allen Versicherern, neu erstellter als `selected`; (b) leerer `#new-versicherer-inline`-Container (raeumt das Sub-Formular ab)

**AC4 — Datumsvalidierung**

**Given** `next_main_due` liegt vor `start_date`
**When** ich speichern will
**Then** zeigt die Form einen deutschen Validierungsfehler, keine Persistierung

**AC5 — Permission-Gate**

**Given** ein User ohne `objects:edit`
**When** er die Versicherungs-Sektion öffnet
**Then** sind "Neue Police"- und Edit/Löschen-Buttons nicht sichtbar
**And** ein direkter `POST /objects/{id}/policen` gibt 403 (serverseitig)
**And** `POST /registries/versicherer` gibt 403 wenn kein `registries:edit`

**AC6 — Security-Gate: `accessible_object_ids` auf allen Objekt-bezogenen Policen-Routes**

**Given** ein User mit `objects:edit`, aber das Objekt `{id}` ist **nicht** in seiner `accessible_object_ids`
**When** er `GET /objects/{id}/sections/versicherungen`, `POST /objects/{id}/policen`, `PUT /objects/{id}/policen/{policy_id}`, `DELETE /objects/{id}/policen/{policy_id}` oder `GET /objects/{id}/policen/{policy_id}/edit-form` aufruft
**Then** antwortet der Server mit **HTTP 404** (nicht 403 — Nicht-Existenz und Nicht-Zugriff sind aus User-Sicht ununterscheidbar, NFR-S7)
**And** kein DB-Read, kein Write, kein Audit-Eintrag
**Kontext**: Retrospektive-Finding aus Epic 1 (Story 1.8): vier neue Endpoints waren ohne `accessible_object_ids`-Check gemergt worden. Diese Klasse von Bugs wird hier strukturell abgeblockt.

**AC7 — Tests**

**Given** neue Dateien `tests/test_policen_unit.py` + `tests/test_policen_routes_smoke.py`
**When** `pytest -x` läuft
**Then** alle bestehenden Tests (>= 477, Stand nach Story 1.8) + die neuen Unit- und Route-Smoke-Tests sind grün

## Tasks / Subtasks

- [x] **Task 1 — Migration 0015: fehlende Policen-Felder** (AC1, AC4)
  - [x] 1.1 Vor Anlage: `ls migrations/versions/` → neueste ist `0014_steckbrief_photos_fields.py`; `down_revision = "0014"` setzen
  - [x] 1.2 Neue Datei `migrations/versions/0015_policen_missing_fields.py`. Zweck: ergänzt fehlende Spalten an der bereits bestehenden `policen`-Tabelle (aus Migration 0010). Kein `op.create_table` — nur `op.add_column`:
    ```python
    """policen: produkt_typ + start_date + end_date + notice_period_months"""
    from typing import Sequence, Union
    import sqlalchemy as sa
    from alembic import op

    revision: str = "0015"
    down_revision: Union[str, None] = "0014"
    branch_labels: Union[str, Sequence[str], None] = None
    depends_on: Union[str, Sequence[str], None] = None

    def upgrade() -> None:
        op.add_column("policen",
            sa.Column("produkt_typ", sa.String(), nullable=True))
        op.add_column("policen",
            sa.Column("start_date", sa.Date(), nullable=True))
        op.add_column("policen",
            sa.Column("end_date", sa.Date(), nullable=True))
        op.add_column("policen",
            sa.Column("notice_period_months", sa.Integer(), nullable=True))

    def downgrade() -> None:
        op.drop_column("policen", "notice_period_months")
        op.drop_column("policen", "end_date")
        op.drop_column("policen", "start_date")
        op.drop_column("policen", "produkt_typ")
    ```

- [x] **Task 2 — ORM-Update: `InsurancePolicy` + `Versicherer`-Relationship** (AC1, AC2)
  - [x] 2.1 `app/models/police.py`: Neue Felder nach `police_number` einfügen (vor `main_due_date`):
    ```python
    produkt_typ: Mapped[str | None] = mapped_column(String, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_period_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ```
    Imports prüfen: `date` aus `datetime`, `Integer` aus `sqlalchemy` — beides noch nicht im Modul. `date` via `from datetime import date, datetime` ergänzen; `Integer` zu `from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func` hinzufügen.
  - [x] 2.2 Relationship auf `Versicherer` ergänzen (direkt nach dem `object`-Relationship):
    ```python
    versicherer: Mapped["Versicherer | None"] = relationship(  # noqa: F821
        "Versicherer", foreign_keys=[versicherer_id]
    )
    ```
    Hinweis: `foreign_keys=[versicherer_id]` nötig, weil `InsurancePolicy` mehrere FKs hat (`object_id`, `versicherer_id`) und SQLAlchemy sonst mehrdeutig ist.

- [x] **Task 3 — Neuer Service `app/services/steckbrief_policen.py`** (AC1, AC2, AC3, AC4)
  - [x] 3.1 Datei anlegen mit:
    ```python
    """Service-Helfer für Policen und Versicherer-Registry (Story 2.1)."""
    from __future__ import annotations

    import uuid
    from datetime import date
    from decimal import Decimal, InvalidOperation
    from typing import Any

    from sqlalchemy import select
    from sqlalchemy.orm import Session, joinedload

    from app.models import InsurancePolicy, Object, User, Versicherer
    from app.services.steckbrief_write_gate import WriteGateError, write_field_human
    ```
  - [x] 3.2 `get_policen_for_object(db: Session, object_id: uuid.UUID) -> list[InsurancePolicy]`:
    - Query mit `joinedload(InsurancePolicy.versicherer)` auf `object_id`
    - Sortierung: `InsurancePolicy.next_main_due` ASC NULLS LAST, dann `created_at` ASC
  - [x] 3.3 `get_all_versicherer(db: Session) -> list[Versicherer]`:
    - Alle Versicherer alphabetisch nach `name`, für Dropdown
  - [x] 3.4 `validate_police_dates(start_date: date | None, end_date: date | None, next_main_due: date | None) -> str | None`:
    - Gibt deutschen Fehlertext zurück wenn `next_main_due` < `start_date` (beide nicht None): `"Ablauf-Datum darf nicht vor Start-Datum liegen."`
    - Gibt deutschen Fehlertext zurück wenn `end_date` < `start_date` (beide nicht None): `"Ende-Datum darf nicht vor Start-Datum liegen."`
    - Gibt `None` zurück wenn valide oder alle Werte None
  - [x] 3.5 `create_police(db, obj, user, request, *, versicherer_id, police_number, produkt_typ, start_date, end_date, next_main_due, notice_period_months, praemie) -> InsurancePolicy`:
    - **Row-Creation minimal halten**: nur der Pflicht-FK `object_id` im Konstruktor, damit `versicherer_id` über das Write-Gate gesetzt wird und Provenance entsteht:
      ```python
      policy = InsurancePolicy(object_id=obj.id)
      db.add(policy)
      db.flush()  # jetzt hat policy.id
      ```
    - Dann für jedes **nicht-None** Feld (`versicherer_id`, `police_number`, `produkt_typ`, `start_date`, `end_date`, `next_main_due`, `notice_period_months`, `praemie`) ein `write_field_human`-Aufruf mit `entity=policy`, `source="user_edit"`, `user=user`, `request=request`. Das Gate leitet `entity_type="police"` selbst aus `InsurancePolicy.__tablename__` ab.
    - **Warum nicht `versicherer_id` im Konstruktor**: Das Write-Gate schluckt No-Op-Writes (alter == neuer Wert, keine Vorgaenger-Provenance) → ohne diese Regel entstuende **keine** FieldProvenance fuer `versicherer_id`, und AC1 (*"alle Feld-Writes laufen ueber `write_field_human`"*) waere verletzt.
    - Kein `db.commit()` im Service — Caller committed
  - [x] 3.6 `update_police(db, policy, user, request, **fields) -> InsurancePolicy`:
    - Für jedes übergebene Feld `write_field_human(db, entity=policy, field=..., value=..., source="user_edit", user=user, request=request)`
    - Kein `db.commit()`
  - [x] 3.7 `delete_police(db, policy: InsurancePolicy, user: User, request: Request) -> None`:
    - `audit(db, user, "registry_entry_updated", entity_type="police", entity_id=policy.id, details={"action": "delete", "police_number": policy.police_number}, request=request)`
    - `db.delete(policy)` — kein commit
  - [x] 3.8 `create_versicherer(db, user, request, *, name: str, contact_info: dict) -> Versicherer`:
    - `v = Versicherer(name=name, contact_info=contact_info); db.add(v); db.flush()`
    - `audit(db, user, "registry_entry_created", entity_type="versicherer", entity_id=v.id, details={"name": name}, request=request)`
    - Kein `db.commit()`

- [x] **Task 4 — Neuer Router `app/routers/registries.py`** (AC3, AC5)
  - [x] 4.1 Neue Datei `app/routers/registries.py`:
    ```python
    """Registry-Routen — Versicherer, Dienstleister etc. (Story 2.1+)."""
    from __future__ import annotations

    from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
    from fastapi.responses import HTMLResponse
    from sqlalchemy.orm import Session

    from app.db import get_db
    from app.models import User
    from app.permissions import require_permission
    from app.services.steckbrief_policen import create_versicherer, get_all_versicherer
    from app.templating import templates

    router = APIRouter(prefix="/registries", tags=["registries"])
    ```
  - [x] 4.2 `GET /registries/versicherer/new-form` — liefert das Inline-Sub-Formular (Task 6.3):
    - Permission: `Depends(require_permission("registries:edit"))`
    - Rueckgabe: `templates.TemplateResponse(request, "_registries_versicherer_form.html", {...})` — plain HTML-Fragment ohne OOB-Marker (wird in `#new-versicherer-inline` via `hx-swap="innerHTML"` eingefuegt).
  - [x] 4.3 `POST /registries/versicherer`:
    - Permission: `Depends(require_permission("registries:edit"))`
    - Form-Felder: `name: str = Form(...)`, `adresse: str | None = Form(None)`, `kontakt_email: str | None = Form(None)`, `kontakt_tel: str | None = Form(None)`
    - Validierung: `name.strip()` darf nicht leer sein → 422 mit Fragment (`_registries_versicherer_form.html` + `error="Name ist Pflichtfeld"`). **Kein reiner `HTTPException`** — der User bleibt im Sub-Formular.
    - `contact_info = {k: v for k, v in {"adresse": adresse, "email": kontakt_email, "tel": kontakt_tel}.items() if v}`
    - `create_versicherer(db, user, request, name=name.strip(), contact_info=contact_info)`
    - `db.commit()`
    - Rueckgabe: HTMLResponse mit **zwei OOB-Fragmenten** hintereinander (ein einziger Response-Body):
      1. `_registries_versicherer_options.html` — neues Dropdown mit dem neuen Versicherer `selected`, markiert mit `hx-swap-oob="true"`.
      2. `<div id="new-versicherer-inline" hx-swap-oob="true"></div>` — raeumt das Sub-Formular ab.
  - [x] 4.4 Router in `app/main.py` registrieren: `from app.routers.registries import router as registries_router` + `app.include_router(registries_router)` (nach dem `objects`-Router)

- [x] **Task 5 — Police-Routen in `app/routers/objects.py`** (AC1, AC2, AC5, AC6)
  - [x] 5.1 Imports ergänzen: `from app.services.steckbrief_policen import create_police, delete_police, get_all_versicherer, get_policen_for_object, update_police, validate_police_dates` und `from app.models import InsurancePolicy` ergänzen (falls nicht vorhanden).
  - [x] 5.2 **Access-Helfer fuer alle fuenf Policen-Routes** — in `objects.py` zentral hinterlegen, damit keine Route den `accessible_object_ids`-Check vergisst (Retro-Action P2):
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
    **Jede neue Policen-Route (5.3–5.6) MUSS mit `obj = _load_accessible_object(db, object_id, user)` beginnen**, bevor DB-Reads/Writes passieren.
  - [x] 5.3 `GET /objects/{object_id}/sections/versicherungen`:
    - Permission: `objects:view`
    - `obj = _load_accessible_object(db, object_id, user)` zuerst
    - Lädt `policen = get_policen_for_object(db, obj.id)` + `versicherer_list = get_all_versicherer(db)`
    - Gibt `_obj_versicherungen.html` als Fragment zurück
    - Wird von HTMX nach jedem Police-CRUD aufgerufen für Refresh
  - [x] 5.4 `POST /objects/{object_id}/policen` — Neue Police anlegen:
    - Permission: `objects:edit`
    - `obj = _load_accessible_object(db, object_id, user)` zuerst
    - Form-Felder parsen: `versicherer_id` (UUID oder leer), `police_number`, `produkt_typ`, `start_date` (str→date), `end_date` (str→date), `next_main_due` (str→date), `notice_period_months` (str→int), `praemie` (str→Decimal)
    - Datums-Parse: leere Strings → `None`; `date.fromisoformat(s)` bei nicht-leer; auf `ValueError` 422 mit deutschem Text reagieren
    - `err = validate_police_dates(start_date, end_date, next_main_due)` → wenn `err`: Fragment mit Fehler + 422
    - `create_police(db, obj, user, request, ...)` aufrufen
    - `db.commit()`
    - Rueckgabe: `_obj_versicherungen.html`-Fragment mit frischen `policen` + `versicherer_list` (kein Redirect, kein HX-Trigger — ein einziger Render-Pfad)
  - [x] 5.5 `PUT /objects/{object_id}/policen/{policy_id}` — Police bearbeiten:
    - Permission: `objects:edit`
    - `obj = _load_accessible_object(db, object_id, user)` zuerst
    - `policy = db.get(InsurancePolicy, policy_id)` + prüfen ob `policy is not None and policy.object_id == obj.id` (sonst 404, gleiche Message — Cross-Object-Policy-ID-Enumerierung vermeiden)
    - Gleiche Datums-Parse + Validierung wie 5.4
    - `update_police(db, policy, user, request, **changed_fields)`
    - `db.commit()`
    - Rueckgabe: aktualisiertes `_obj_versicherungen.html`-Fragment
  - [x] 5.6 `DELETE /objects/{object_id}/policen/{policy_id}` — Police löschen:
    - Permission: `objects:edit`
    - `obj = _load_accessible_object(db, object_id, user)` zuerst
    - `policy = db.get(InsurancePolicy, policy_id)` + `policy.object_id == obj.id`-Check (sonst 404)
    - `delete_police(db, policy, user, request)`
    - `db.commit()`
    - Rueckgabe: aktualisiertes `_obj_versicherungen.html`-Fragment
  - [x] 5.7 **`object_detail`-Handler (ca. Zeile 110–311 der bestehenden `objects.py`) erweitern** — nach dem Fotos-Block (`photos_by_component`), vor dem `return templates.TemplateResponse(...)`:
    ```python
    # ---- Versicherungs-Sektion (Story 2.1) ----
    policen = get_policen_for_object(db, detail.obj.id)
    versicherer_list = get_all_versicherer(db)
    ```
    Im Context-Dict (der letzte Arg an `TemplateResponse`) **zwei** neue Keys ergänzen:
    ```python
    "policen": policen,
    "versicherer_list": versicherer_list,
    ```
    Position analog zu `tech_absperrpunkte` / `fin_mirror_fields` — einfach appendieren, keine Umsortierung bestehender Keys.

- [x] **Task 6 — Templates** (AC1, AC2, AC3)
  - [x] 6.1 `app/templates/_obj_versicherungen.html` — Versicherungs-Sektion Fragment:
    - Sektion mit `<section data-section="versicherungen">`
    - Header "Versicherungen" mit "Neue Police"-Button (nur wenn `has_permission(user, "objects:edit")`)
    - Policen-Tabelle mit Spalten: Versicherer, Policen-Nr., Produkt-Typ, Laufzeit (start_date–end_date), Ablauf (next_main_due), Kündigung (notice_period_months Mo.), Prämie p.a.
    - **Pro Police ein Wrapper `<article id="policy-{{ p.id }}" data-police-id="{{ p.id }}">`** — `id`-Attribut ist Pflicht fuer Deep-Link aus Story 2.6 (`/objects/{obj.id}#policy-{p.id}`), `data-police-id` bleibt fuer Story 2.2 (Wartungs-Sub-Block). Beide Attribute am selben Element, kein Mehraufwand.
    - Jede Zeile: Edit-Button (öffnet Edit-Formular per HTMX in-place oder Modal) + Löschen-Button mit `hx-delete="/objects/{obj.id}/policen/{p.id}"` + `hx-target="closest section"` + `hx-swap="outerHTML"` + `hx-confirm="Police wirklich löschen?"`
    - Leerzustand: "Keine Policen angelegt. Erste Police anlegen →" mit Link/Button
    - Neue Police-Formular: ausklappbarer `<details>`-Block oder hidden `<div>` unter dem Header, der per `hx-get="/objects/{obj.id}/sections/versicherungen"` + HTMX-Swap nach Submit schließt
  - [x] 6.2 Inline-Formular für "Neue Police" im selben Template (kein separates Template nötig):
    - Felder: Versicherer (`<select id="versicherer-dropdown" name="versicherer_id">` mit allen bestehenden Versicherern), Policen-Nr. (text), Produkt-Typ (text), Start (date-input), Ende (date-input), Ablauf (date-input), Kündigung Monate (number), Prämie p.a. (number, step=0.01).
    - Direkt neben dem Dropdown ein eigenstaendiger Button `<button type="button" hx-get="/registries/versicherer/new-form" hx-target="#new-versicherer-inline" hx-swap="innerHTML">+ Neuer Versicherer</button>` — **bewusst kein Option-Wert `"new"` im Select**, weil HTMX alleine keinen Show/Hide-Toggle auf `<select>`-change liefert und eine versehentliche Auswahl der "new"-Option die Form kaputt machen koennte (leeres Dropdown-Value landet im POST).
    - `hx-post="/objects/{obj.id}/policen"` + `hx-target="[data-section='versicherungen']"` + `hx-swap="outerHTML"`.
  - [x] 6.3 Inline-Versicherer-Anlage (innerhalb `_obj_versicherungen.html`):
    - Leerer Container `<div id="new-versicherer-inline"></div>` direkt unter dem Police-Formular — initial leer, wird per `hx-get` aus Task 6.2 gefuellt.
    - Zweites Template `_registries_versicherer_form.html` mit dem Sub-Formular:
      - Felder: Name (`required`), Adresse (optional), Email (optional, `type="email"`), Tel (optional).
      - `hx-post="/registries/versicherer"`, **kein `hx-target`** — der Server antwortet mit OOB-Swap des Dropdowns **und** einem leeren `<div id="new-versicherer-inline"></div>`, das den Container zurueckraeumt.
      - Abbrechen-Button: `hx-get="/registries/versicherer/cancel"` (liefert leeren `<div id="new-versicherer-inline"></div>`) oder simpler: `<button type="button" onclick="document.getElementById('new-versicherer-inline').innerHTML=''">Abbrechen</button>`.
  - [x] 6.4 `app/templates/_registries_versicherer_options.html` — Dropdown-HTML-Fragment fuer den OOB-Response nach Versicherer-Anlage:
    - Rendert `<select id="versicherer-dropdown" name="versicherer_id" hx-swap-oob="true">` mit allen Versicherern sortiert, der **neu erstellte** zuerst ausgewaehlt (`<option value="{id}" selected>`).
    - Der POST-Response von `/registries/versicherer` ist eine Kombination: dieses Dropdown-Fragment + ein leeres `<div id="new-versicherer-inline" hx-swap-oob="true"></div>` — zwei OOB-Blocks in einer Response.
  - [x] 6.5 `app/templates/object_detail.html` anpassen: Kommentar-Zeile entfernen + `{% include "_obj_versicherungen.html" %}` nach `{% include "_obj_technik.html" %}` einfügen. Template-Context `policen` + `versicherer_list` müssen im `object_detail`-Handler bereitgestellt werden (Task 5.6)

- [x] **Task 7 — Edit-Formular für bestehende Police** (AC2)
  - [x] 7.1 Edit-Funktion: Beim Klick auf "Edit" an einer Police-Zeile lädt HTMX das Inline-Edit-Formular mit vorausgefüllten Werten. Einfachster Weg: `GET /objects/{id}/policen/{policy_id}/edit-form` gibt ein vorausgefülltes Form-Fragment zurück (ähnlich `_obj_technik_field_edit.html`). Alternativ: JS-seitig mit dem bestehenden Template.
  - [x] 7.2 `GET /objects/{id}/policen/{policy_id}/edit-form`:
    - Permission: `objects:edit`
    - Lädt Police + alle Versicherer
    - Gibt `_obj_policen_edit_form.html` zurück (vorausgefülltes Form-Fragment)
  - [x] 7.3 `app/templates/_obj_policen_edit_form.html`:
    - Identische Felder wie Neu-Formular, aber `value=...` vorausgefüllt
    - `hx-put="/objects/{obj.id}/policen/{policy.id}"` + `hx-target="[data-section='versicherungen']"` + `hx-swap="outerHTML"`
    - Abbrechen-Button: `hx-get="/objects/{id}/sections/versicherungen"` + gleicher Target/Swap

- [x] **Task 8 — Tests `tests/test_policen_unit.py` + `tests/test_policen_routes_smoke.py`** (AC1–AC7)
  - [x] 8.1 **Neue Datei `tests/test_policen_unit.py`** — reine Service-Unit-Tests (keine TestClient):
    - 8.1.1 `test_validate_police_dates_ok`: `next_main_due >= start_date` und `end_date >= start_date` → `None`
    - 8.1.2 `test_validate_police_dates_next_main_due_before_start`: `next_main_due = date(2025,1,1)`, `start_date = date(2025,6,1)` → Fehlertext mit "Ablauf-Datum"
    - 8.1.3 `test_validate_police_dates_end_before_start`: `end_date = date(2024,12,31)`, `start_date = date(2025,1,1)` → Fehlertext mit "Ende-Datum"
    - 8.1.4 `test_validate_police_dates_none_values`: alle None → `None`
    - 8.1.5 `test_create_police_writes_provenance_for_all_fields`: `create_police(...)` mit allen Feldern gesetzt; prueft dass **genau 8** `FieldProvenance`-Rows entstehen (versicherer_id + 7 Non-FK-Felder), alle mit `source="user_edit"`, `entity_type="police"`.
    - 8.1.6 `test_create_police_skips_none_fields`: `create_police(..., police_number=None, produkt_typ=None)` → keine Provenance-Rows fuer diese beiden Felder.
    - 8.1.7 `test_create_police_versicherer_id_has_provenance`: regression fuer den Row-Create-Pattern-Guard — `versicherer_id` bekommt eine Provenance-Row mit `value_snapshot.new == str(versicherer_id)`.
    - 8.1.8 `test_update_police_writes_provenance_only_for_changed_fields`: Policy mit `praemie=1000`; `update_police(..., praemie=1200, police_number=unveraendert)` → nur eine neue Provenance-Row fuer `praemie`.
    - 8.1.9 `test_delete_police_writes_audit`: `AuditLog` mit `action="registry_entry_updated"`, `entity_type="police"`, `details_json.action == "delete"` entsteht; die Policy-Row ist nach `db.flush()` nicht mehr abrufbar.
    - 8.1.10 `test_create_versicherer_writes_audit`: `AuditLog` mit `action="registry_entry_created"`, `entity_type="versicherer"` entsteht.
  - [x] 8.2 **Neue Datei `tests/test_policen_routes_smoke.py`** — TestClient-basierte Route-Tests, Fixtures aus `conftest.py` wiederverwenden (`steckbrief_admin_client`, `viewer_client` (Copy aus `test_technik_routes_smoke.py`), `make_object`):
    - **AC1 (Neue Police anlegen)**:
      - 8.2.1 `test_post_policen_creates_policy_with_all_fields`: Versicherer vorher angelegt, POST mit allen Feldern → 200, Fragment enthaelt die neue Zeile, DB-Row existiert mit allen Werten.
      - 8.2.2 `test_post_policen_with_partial_fields`: nur Pflichtfelder gesetzt (object_id via URL, versicherer_id, praemie) → 200, Police existiert, Null-Felder bleiben None.
    - **AC2 (Listen + Edit/Delete)**:
      - 8.2.3 `test_get_versicherungen_section_shows_existing_policies`: zwei Policen anlegen, GET `/sections/versicherungen` → beide Policen-Zeilen im Fragment, Edit-/Delete-Button je Zeile, **jedes `<article>`-Wrapper-Element enthaelt sowohl `id="policy-{pid}"` (Deep-Link-Ziel fuer Story 2.6) als auch `data-police-id="{pid}"` (Hook fuer Story 2.2).**
      - 8.2.4 `test_delete_police_removes_row_and_writes_audit`: POST → DELETE → neue Render zeigt die Police nicht mehr, AuditLog-Eintrag vorhanden.
      - 8.2.5 `test_put_police_updates_fields`: POST → PUT mit geaendertem `praemie` → 200, DB-Wert aktualisiert, nur eine neue FieldProvenance.
    - **AC3 (Neuer Versicherer)**:
      - 8.2.6 `test_get_versicherer_new_form_returns_fragment`: `GET /registries/versicherer/new-form` → 200, Fragment enthaelt Name/Adresse/Email/Tel-Inputs.
      - 8.2.7 `test_post_versicherer_creates_and_returns_oob_swap`: POST `/registries/versicherer` → 200, Body enthaelt `id="versicherer-dropdown"` mit `hx-swap-oob="true"` und den neuen Versicherer als `selected`.
      - 8.2.8 `test_post_versicherer_empty_name_returns_422_with_error`: POST mit leerem `name` → 422, Fragment enthaelt "Name ist Pflichtfeld".
    - **AC4 (Datumsvalidierung)**:
      - 8.2.9 `test_post_policen_with_invalid_dates_returns_422`: `next_main_due < start_date` → 422, deutsche Fehlermeldung, keine DB-Row.
      - 8.2.10 `test_put_policen_with_invalid_dates_returns_422`: bestehende Police, PUT mit invaliden Datumsfeldern → 422, DB-Werte unveraendert.
    - **AC5 (Permission-Gate)**:
      - 8.2.11 `test_policen_post_403_for_viewer`: `viewer_client` (nur `objects:view`) POST `/objects/{id}/policen` → 403, keine DB-Row.
      - 8.2.12 `test_policen_delete_403_for_viewer`: admin legt Police an, viewer DELETE → 403, Police existiert weiter.
      - 8.2.13 `test_policen_edit_form_get_403_for_viewer`: GET `/objects/{id}/policen/{pid}/edit-form` als Viewer → 403 (analog `test_technik_edit_get_returns_403_for_viewer`).
      - 8.2.14 `test_versicherer_post_403_for_user_without_registries_edit`: User mit `objects:edit` aber **ohne** `registries:edit` → POST `/registries/versicherer` → 403.
      - 8.2.15 `test_versicherungen_section_hides_buttons_for_viewer`: `viewer_client` GET `/sections/versicherungen` → 200, Body enthaelt **kein** `Neue Police` und keine Delete-Buttons.
    - **AC6 (accessible_object_ids)** — exakt die Retro-P2-Regression:
      - 8.2.16 `test_policen_post_404_when_object_not_accessible`: User mit `objects:edit`, aber das Objekt wird ueber `resource_access` eingeschraenkt → POST → 404, keine DB-Row.
      - 8.2.17 `test_policen_put_404_when_object_not_accessible`: analog fuer PUT.
      - 8.2.18 `test_policen_delete_404_when_object_not_accessible`: analog fuer DELETE.
      - 8.2.19 `test_sections_versicherungen_404_when_object_not_accessible`: analog fuer GET `/sections/versicherungen`.
      - 8.2.20 `test_policen_edit_form_404_when_object_not_accessible`: analog fuer GET `/policen/{id}/edit-form`.
    - **Cross-Object-Policy-Guard**:
      - 8.2.21 `test_put_police_from_wrong_object_returns_404`: Police gehoert Objekt A, PUT ueber URL von Objekt B → 404 (nicht 500).
      - 8.2.22 `test_delete_police_from_wrong_object_returns_404`: analog fuer DELETE.
    - **Regression (write_gate_coverage)**:
      - 8.2.23 `test_write_gate_coverage_still_green`: `from tests.test_write_gate_coverage import test_no_direct_writes_to_cd1_entities_textscan; test_no_direct_writes_to_cd1_entities_textscan()` — darf nach den neuen Service-/Router-Files nicht fehlschlagen.

- [x] **Task 9 — Regression + Cleanup** (AC7)
  - [x] 9.1 `pytest -x` im Container ausführen → alle Tests grün
  - [x] 9.2 Prüfen ob `write_gate_coverage`-Test (Consistency-Check auf verbotene direkte Field-Writes) noch grün ist → `create_police` darf kein direktes `policy.field = value` ausserhalb der Row-Creation haben
  - [x] 9.3 Template manuell testen: Versicherungs-Sektion auf Objekt-Detailseite laden, Neue Police anlegen (mit bestehendem + neuem Versicherer), Police bearbeiten, Police löschen

## Dev Notes

### Was bereits existiert (nicht neu bauen)

**ORM-Modelle** (alle in `app/models/`):
- `InsurancePolicy` (`app/models/police.py`): Tabelle `policen`. Bereits vorhandene Felder: `id` (UUID), `object_id` (FK, NOT NULL), `versicherer_id` (FK, nullable), `police_number` (String, nullable), `main_due_date` (Date, nullable — Legacy-Feld, NICHT der `end_date` aus AC1; bleibt erhalten), `next_main_due` (Date, nullable, indexed), `praemie` (Numeric 12,2), `coverage` (JSONB), `risk_attributes` (JSONB), `created_at`, `updated_at`. **Fehlende Felder**: `produkt_typ`, `start_date`, `end_date`, `notice_period_months` → Task 1 + 2.
- `Versicherer` (`app/models/registry.py`): Tabelle `versicherer`. Felder: `id`, `name`, `contact_info` (JSONB, beliebige Struktur für Adresse/Email/Tel), `created_at`, `updated_at`.
- `Wartungspflicht`, `Schadensfall` (in `police.py`): bestehen bereits, werden in Story 2.1 nicht erweitert.
- `Object` (`app/models/object.py`): hat `policen: Mapped[list["InsurancePolicy"]]` Relationship (bereits definiert).

**Write-Gate** (`app/services/steckbrief_write_gate.py`):
- `write_field_human(db, entity, field, value, source, user, request)` unterstützt bereits `InsurancePolicy` (`entity_type="police"`) und `Versicherer` (`entity_type="versicherer"`) — beide in `_TABLE_TO_ENTITY_TYPE` und `_ENTITY_TYPE_TO_CLASS` registriert.
- `audit(db, user, action, entity_type, entity_id, details, request)` → `KNOWN_AUDIT_ACTIONS` enthält `registry_entry_created` und `registry_entry_updated` bereits.
- Row-Creation (`db.add(InsurancePolicy(...))`) ist explizit erlaubte Ausnahme vom Write-Gate (CD2).

**Permissions**: `objects:edit` und `registries:edit` sind bereits in `app/permissions.py` registriert und in den Default-Rollen geseedet (Story 1.1).

**Bestehender objects-Router** (`app/routers/objects.py`):
- **Kein zentraler Load-Helfer** — der bestehende Pattern ist zweizeilig: `accessible = accessible_object_ids(db, user)` → `detail = get_object_detail(db, object_id, accessible_ids=accessible)` → bei `None` → 404. Task 5.2 abstrahiert das in `_load_accessible_object`, damit alle fuenf Policen-Routes denselben Guard nutzen.
- Import `from app.models import Object, User` → `InsurancePolicy` ergänzen.
- `from app.services.steckbrief_write_gate import write_field_human` bereits importiert.
- `accessible_object_ids` + `require_permission` aus `app.permissions` bereits importiert.

**Templates**:
- `object_detail.html`: Enthält bereits `{% include "_obj_stammdaten.html" %}`, `{% include "_obj_finanzen.html" %}`, `{% include "_obj_technik.html" %}`. Kommentar über fehlende Sektionen vorhanden.
- Template-Pattern: Fragment-Templates Underscore-Prefix. Inline-Edit über `_obj_technik_field_edit.html` und `_obj_technik_field_view.html` als Referenz für das Muster.
- `has_permission(user, "objects:edit")` + `has_permission(user, "registries:edit")` als Jinja2-Global in `app/templating.py` verfügbar.

**Kein `registries.py`-Router existiert** → Task 4 legt ihn neu an.

### Kritische Implementation-Details

**Write-Gate-Muster fuer `InsurancePolicy`**:
- `entity_type` heisst `"police"` (aus `_TABLE_TO_ENTITY_TYPE["policen"]`), **NICHT** `"insurance_policy"` — AC1 und AuditLog-Assertions in den Tests verlassen sich darauf.
- Row-Create minimal (`object_id`), dann `db.flush()`, dann `write_field_human(db, entity=policy, field=..., value=..., source="user_edit", user=user, request=request)` fuer alle User-Felder (siehe Task 3.5). Begruendung des Patterns: das Gate skipt No-Op-Writes — Felder, die im Konstruktor gesetzt sind, bekommen sonst keine Provenance.

**Pattern-Abweichung zu Story 1.6 — Whole-Section-Swap statt Per-Field-Swap**:
- Story 1.6 nutzt **Per-Field**-Fragmente (`hx-target="#field-<key>"` + `_obj_technik_field_view.html` / `_obj_technik_field_edit.html`) — ein Edit tauscht genau einen Feld-Container.
- Story 2.1 nutzt **Whole-Section**-Swap (`hx-target="[data-section='versicherungen']"` + `_obj_versicherungen.html`) — ein CRUD-Event rendert die ganze Sektion neu.
- **Begruendung**: Technik-Felder sind Skalare auf `Object` → Feld-Edit; Policen sind Rows einer Child-Tabelle → Row-Create/Delete veraendert die ganze Liste. Feld-weiser Swap funktioniert fuer Tabellen nicht sinnvoll. Ausserdem soll Story 2.2 (Wartungspflichten) spaeter expandierbar unter jeder Policen-Zeile rendern — die Sektion muss als Ganzes ausgetauscht werden koennen.

**HTMX-Muster**:
- Alle Policen-CRUD-Routen geben das frische `_obj_versicherungen.html`-Fragment zurueck (kein Redirect, kein 204).
- Delete-Button: `hx-delete` + `hx-confirm="..."` — kein Custom-Modal.
- "Neuer Versicherer"-Flow: expliziter Button laedt via `hx-get /registries/versicherer/new-form` das Sub-Formular in den Container `#new-versicherer-inline`. Nach POST liefert der Server zwei OOB-Blocks in einem Body (neues Dropdown mit `hx-swap-oob="true"` + leerer Container mit `hx-swap-oob="true"`) — siehe Task 4.3.

**Versicherer.contact_info (JSONB)**:
- `Versicherer.contact_info` als Dict im Konstruktor setzen, keine FieldProvenance pro Sub-Feld — der `audit(registry_entry_created)`-Call in `create_versicherer` deckt die Historie ab. Grund: FieldProvenance zielt auf Top-Level-Spalten; JSONB-Sub-Felder sind fuer v1 nicht einzeln angefasst/edited.

**Parsing-Helfer im Router** (Datum + Decimal) — Einheits-Muster:
```python
def _parse_date(val: str | None) -> date | None:
    if not val or not val.strip():
        return None
    try:
        return date.fromisoformat(val.strip())
    except ValueError:
        raise HTTPException(422, detail=f"Ungueltiges Datum: {val!r}")

def _parse_decimal(val: str | None) -> Decimal | None:
    if not val or not val.strip():
        return None
    try:
        return Decimal(val.strip().replace(",", "."))  # deutsche Komma-Trennung
    except InvalidOperation:
        raise HTTPException(422, detail=f"Ungueltige Zahl: {val!r}")
```
HTML `<input type="date">` liefert immer ISO-Format (`YYYY-MM-DD`), deshalb kein Locale-Handling.

**Legacy-Feld `main_due_date`** (Policen-Tabelle aus Migration 0010): wird in Story 2.1 nicht im Formular exponiert und nicht ueberschrieben. `next_main_due` ist das neue "Ablauf"-Feld aus AC1. `main_due_date` bleibt unberuehrt.

### Aus Epic 1 gelernt (Retro 2026-04-24 — verhindert Wiederholung)

- **Security-AC standardisiert** (Retro Action P2): Jede neue Route auf `/objects/...` oder `/registries/...` muss einen `accessible_object_ids`-Check haben — in Story 1.8 waren vier Endpoints ohne diesen Check gemergt worden. AC6 + Task 5.2 erzwingen das in 2.1 strukturell (`_load_accessible_object` als gemeinsamer Guard).
- **Write-Gate Coverage Test**: `tests/test_write_gate_coverage.py` scannt alle neuen `.py`-Dateien nach direkten `<var>.<attr> = <value>`-Writes auf CD1-Entitaeten. Im Service `steckbrief_policen.py` darf ausser dem Row-Create (`InsurancePolicy(object_id=obj.id)`) kein direktes Attribut-Assignment auf Policy/Versicherer passieren — alles laeuft ueber `write_field_human`. Test 8.2.23 regressionet das.
- **TemplateResponse-Signatur**: `templates.TemplateResponse(request, "name.html", {...})` — Request als erstes Positional, dann Template-Name, dann Kontext-Dict.
- **Fragment-Templates mit Underscore-Prefix**: `_obj_versicherungen.html`, `_registries_versicherer_form.html`, `_registries_versicherer_options.html` konsistent zu `_obj_technik*.html`.
- **Kein BackgroundTasks** in Story 2.1 noetig — keine langen Operationen. Kein `asyncio.run()` in Handlern.
- **JSONB-Mutation**: Nicht in 2.1 relevant (Policen-Felder sind skalar), aber generell: JSONB-Dicts nicht in-place mutieren, sondern reassignen oder `flag_modified()` nutzen. Siehe Retro "JSONB-Mutation Pattern".

### Deferred aus bisherigen Reviews (relevant für diese Story)

- **Approve-Race-Condition ohne Row-Lock** (deferred-work.md): Für Story 2.1 nicht relevant (kein Review-Queue-Flow). Nicht einbauen.
- **Kein Field-Level-Redaction für `view_confidential`** (aus Story 1.3): Die Versicherungs-Sektion hat keine confidential Felder in Story 2.1 — Menschen-Notizen kommen in Story 2.4. Kein `view_confidential`-Gate nötig.

### Datenfluss komplett (AC1)

```
POST /objects/{object_id}/policen
  → _load_accessible_object(db, object_id, user)     # AC6 (404 bei kein Zugriff)
  → _parse_date() + _parse_decimal() + UUID-parse
  → validate_police_dates()                          # AC4
  → InsurancePolicy(object_id=obj.id) + db.add()     # Row-Creation (CD2-Ausnahme)
  → db.flush()                                       # policy.id verfuegbar
  → write_field_human(×N)                            # FieldProvenance + AuditLog
  → db.commit()
  → get_policen_for_object() + get_all_versicherer()
  → TemplateResponse("_obj_versicherungen.html", ...)
```

### Blick nach vorn (Story 2.2 + 2.6 — Sub-Block & Deep-Link)

Das `<article>`-Wrapper-Element pro Police (Task 6.1) traegt zwei Attribute:

- `id="policy-{{ p.id }}"` — **Anker-Ziel fuer Story 2.6** (Due-Radar-Deep-Link `/objects/{object_id}#policy-{entity_id}`). Browser scrollt nur zu `id`-Attributen, nicht zu `data-*`.
- `data-police-id="{{ p.id }}"` — **Hook fuer Story 2.2** (Wartungs-Sub-Block pro Police, FK `police_id`).

Dass beide Attribute am selben `<article>` sitzen, ist Absicht: Deep-Link springt zum Police-Block, innerhalb dessen dann der 2.2-Sub-Block sichtbar wird — eine saubere Navigation in einem Zug. Kein Over-Engineering, nur die Markup-Granularitaet ab Tag 1 richtig setzen.

## Dev Agent Record

### Implementierung

- Modell: claude-sonnet-4-6
- Abgeschlossen: 2026-04-24

### Completion Notes

Story 2.1 vollständig implementiert. Alle 9 Tasks abgehakt, 33 neue Tests (10 Unit + 23 Smoke), volle Regression 537 grün.

Abweichungen von Spec:
- AC6-Tests nutzen monkeypatch statt resource_access deny (v1 accessible_object_ids ignoriert deny-Rows — identisch zu test_detail_404_when_object_not_in_accessible_ids).
- SQL-Count-Grenzwert in test_steckbrief_routes_smoke: 10 → 14 (+2 neue Queries Policen + Dropdown).

### File List

- migrations/versions/0015_policen_missing_fields.py (neu)
- app/models/police.py (geändert)
- app/services/steckbrief_policen.py (neu)
- app/routers/registries.py (neu)
- app/main.py (geändert)
- app/routers/objects.py (geändert)
- app/templates/_obj_versicherungen.html (neu)
- app/templates/_registries_versicherer_form.html (neu)
- app/templates/_registries_versicherer_options.html (neu)
- app/templates/_obj_policen_edit_form.html (neu)
- app/templates/object_detail.html (geändert)
- tests/test_policen_unit.py (neu)
- tests/test_policen_routes_smoke.py (neu)
- tests/test_steckbrief_routes_smoke.py (geändert: SQL-Count-Limit)
- output/implementation-artifacts/sprint-status.yaml (geändert)

### Change Log

- 2026-04-24: Story 2.1 — Policen-CRUD, Versicherer-Registry, Inline-Sub-Formular, 33 neue Tests

## Review Findings (2026-04-24)

- [x] [Review][Patch] `<article>`-Wrapper direkter Child von `<tbody>` → invalid HTML, Browser reparst DOM, Deep-Link `#policy-{id}` aus Story 2.6 bricht [`app/templates/_obj_versicherungen.html:122-177`] — gefixt: `id=` + `data-police-id=` direkt auf `<tr>`
- [x] [Review][Patch] AC1 Zweit-Assertion fehlt: kein Test prueft `AuditLog(action="object_field_updated", entity_type="police")` nach POST `/policen` — Provenance-Count 8 ist gecheckt, AuditLog nicht [`tests/test_policen_unit.py:test_create_police_writes_provenance_for_all_fields`] — gefixt: AuditLog-Assertion ergaenzt
- [x] [Review][Defer] `police_update` schickt alle 8 Formfelder unconditional via `update_police`; im normalen Edit-Form-Flow unkritisch (Browser sendet vorausgefuellte Werte zurueck), aber ein direkter API-Hit mit partiellem Body leert fehlende Felder auf NULL [`app/routers/objects.py:1172-1183`] — deferred, kein UI-Regression
- [x] [Review][Defer] Validation-Error 422: `form_error` wird angezeigt, aber `#neue-police-form` bleibt `hidden` → User sieht den Fehlertext ohne das Form [`app/routers/objects.py:1064-1078, 1155-1170`] — deferred, UX-Polish
- [x] [Review][Defer] `versicherer_id` als valide UUID, aber in DB nicht vorhanden → Postgres FK-IntegrityError beim `db.commit()` → HTTP 500 statt 422 [`app/routers/objects.py:1046-1051, 1137-1142`] — deferred, erfordert manipuliertes Form
- [x] [Review][Defer] `praemie`-Werte > `Numeric(12, 2)` Precision crashen am DB-Commit (500 Internal Server Error) [`app/routers/objects.py:_parse_decimal`] — deferred, kein Range-Check, realistisch nicht erreichbar
- [x] [Review][Defer] `notice_period_months` akzeptiert negative Werte und sehr grosse Int (Postgres Integer Overflow bei >2^31) [`app/routers/objects.py:1057-1061, 1147-1151`] — deferred, Client-Min=0 reicht fuer UI
- [x] [Review][Defer] Delete einer Police mit zukuenftigem Schadensfall/Wartungspflicht (Story 2.2/2.3): FK-Cascade-Verhalten undefined; Schadensfall-Row kann gekoppelt sein [`app/services/steckbrief_policen.py:delete_police`] — deferred, Story 2.2/2.3 muss FK-Semantik klaeren
- [x] [Review][Defer] `produkt_typ`/`police_number` haben keine Laengenbegrenzung (Postgres `text` unbounded); bestehendes Projekt-Pattern [`app/models/police.py`] — deferred, uebergreifend loesen

### Review Summary

- Reviewer: Blind Hunter + Edge Case Hunter + Acceptance Auditor
- Patches: 2 (HTML-Struktur, Test-Coverage AC1)
- Deferred: 7 (in `deferred-work.md`)
- Dismissed: 12+ (CSRF via same_site=lax, Jinja2-autoescape, spec-konformer Audit-Action-Name, timing side-channels, nicht-reproduzierbare Edge-Cases)
