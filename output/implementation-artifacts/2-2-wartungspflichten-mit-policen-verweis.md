# Story 2.2: Wartungspflichten mit Policen-Verweis

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter mit `objects:edit`,
ich möchte Wartungspflichten pro Police mit Dienstleister und Fälligkeits-Datum pflegen,
damit Deckungsbedingungen sichtbar werden und Due-Radar später daraus ziehen kann.

## Acceptance Criteria

**AC1 — Wartungspflicht anlegen**

**Given** eine bestehende Police in der Versicherungs-Sektion
**When** ich "Wartungspflicht hinzufügen" klicke und Felder `bezeichnung` (Pflicht), `dienstleister` (Dropdown, optional), `intervall_monate`, `letzte_wartung` (date), `next_due_date` (date) eingebe
**Then** wird ein `Wartungspflicht`-Record mit FK `policy_id` + FK `dienstleister_id` (nullable) + FK `object_id` (NOT NULL, aus `policy.object_id` abgeleitet) angelegt
**And** `next_due_date` ist indiziert (für Due-Radar Story 2.5)
**And** `object_id` ist indiziert (für Due-Radar-Filter pro Objekt)
**And** alle Feld-Writes laufen über `write_field_human` mit `entity_type="wartung"`
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` existiert

**AC2 — Wartungspflichten-Anzeige unter Police**

**Given** eine Police mit mehreren Wartungspflichten
**When** ich die Versicherungs-Sektion rendere
**Then** sehe ich Wartungspflichten expandierbar unter der zugehörigen Police (via `<details>`)
**And** jede Zeile zeigt Bezeichnung, Dienstleister-Name, Intervall (Mo.) und nächste Fälligkeit
**And** bei `next_due_date` ≤ 30 Tage: roter Badge; ≤ 90 Tage: oranger Badge; sonst: kein Badge

**AC3 — Wartungspflicht löschen**

**Given** eine bestehende Wartungspflicht
**When** ich den Löschen-Button klicke und bestätige
**Then** wird der Record entfernt
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` mit `entity_type="wartung"` und `details_json.action="delete"` existiert
**And** die betroffene Polizei-Zeile wird per HTMX-Swap aktualisiert (nicht die ganze Sektion — siehe Dev Notes "Per-Police-Fragment")

**AC4 — Neuer Dienstleister via Inline-Anlage**

**Given** ein Dienstleister existiert noch nicht in der Registry
**When** ich im Formular auf "+ Neuer Dienstleister" neben dem Dropdown klicke
**Then** öffnet sich ein Inline-Bereich mit Pflichtfeld (Name) und optionalem Feld (gewerke_tags als Freitext, komma-sep.)
**And** nach Submit ist der neue `Dienstleister`-Record persistiert
**And** ein `AuditLog`-Eintrag `action="registry_entry_created"` mit `entity_type="dienstleister"` existiert
**And** der Server antwortet mit **zwei** OOB-Fragmenten: (a) aktualisierter policy-spezifischer `#dienstleister-dropdown-{{ policy_id }}` mit neuem Dienstleister als `selected`, (b) leerer `#new-dienstleister-inline-{{ policy_id }}`-Container

**AC5 — Permission-Gate (`objects:edit` / `registries:edit`)**

**Given** ein User ohne `objects:edit`
**When** er die Versicherungs-Sektion betrachtet
**Then** sind "Wartungspflicht hinzufügen"- und Löschen-Buttons nicht sichtbar
**And** `POST /objects/{id}/policen/{policy_id}/wartungspflichten` gibt 403
**And** `DELETE /objects/{id}/wartungspflichten/{wart_id}` gibt 403
**And** `POST /registries/dienstleister` ohne `registries:edit` gibt 403

**AC6 — Security-Gate: `accessible_object_ids` auf allen Wartungspflicht-Routes**

**Given** ein User mit `objects:edit`, aber das Objekt `{id}` ist **nicht** in seiner `accessible_object_ids`
**When** er `POST /objects/{id}/policen/{policy_id}/wartungspflichten` oder `DELETE /objects/{id}/wartungspflichten/{wart_id}` aufruft
**Then** antwortet der Server mit **HTTP 404** (nicht 403 — Nicht-Existenz und Nicht-Zugriff ununterscheidbar, NFR-S7)
**And** kein DB-Read auf `wartungspflichten`, kein Write, kein Audit-Eintrag
**And** bei `DELETE`: zusätzlich Cross-Police-Guard — `wart.policy.object_id == obj.id`, sonst 404 (Enumeration durch URL-Mismatch blockieren)
**Kontext**: Retrospektive-Finding aus Epic 1 Story 1.8. `_load_accessible_object` aus Story 2.1 wiederverwenden.

**AC7 — Tests**

**Given** neue Dateien `tests/test_wartungspflichten_unit.py` + `tests/test_wartungspflichten_routes_smoke.py`
**When** `pytest -x` läuft
**Then** alle bestehenden Tests (Stand nach Story 2.1 ≥ 500) + die neuen Unit- und Route-Smoke-Tests sind grün

## Tasks / Subtasks

- [x] **Task 0 — Precheck: Story 2.1 abgeschlossen** (Voraussetzung für alle weiteren Tasks)
  - [x] 0.1 `ls app/routers/registries.py app/templates/_obj_versicherungen.html migrations/versions/0015_*.py` → alle drei müssen existieren. Wenn nicht: **STOP**, Story 2.1 ist nicht implementiert, Story 2.2 ist nicht ausführbar.
  - [x] 0.2 `grep -q "_load_accessible_object" app/routers/objects.py` → muss Match geben.
  - [x] 0.3 `grep -q "entity_type=\"police\"" app/services/steckbrief_policen.py` → bestätigt Write-Gate-Pattern aus Story 2.1 steht.
  - [x] 0.4 `grep -q "action=\"registry_entry_updated\"" app/services/steckbrief_policen.py` → bestätigt Delete-Audit-Muster aus Story 2.1.
  - [x] 0.5 Bekannte Audit-Actions prüfen: `grep -n "KNOWN_AUDIT_ACTIONS" app/services/audit.py` — sicherstellen, dass `object_field_updated` + `registry_entry_created` enthalten sind. Beides für Story 2.2 nötig.

- [x] **Task 1 — Migration 0016: Wartungspflicht-Felder** (AC1)
  - [x] 1.1 `ls migrations/versions/` — neueste Revision nach Story 2.1 ist `0015_policen_missing_fields.py`. `down_revision="0015"` setzen.
  - [x] 1.2 Neue Datei `migrations/versions/0016_wartungspflichten_missing_fields.py`:
    ```python
    """wartungspflichten: object_id FK (NOT NULL) + letzte_wartung"""
    from typing import Sequence, Union
    import sqlalchemy as sa
    from alembic import op
    from sqlalchemy.dialects import postgresql

    revision: str = "0016"
    down_revision: Union[str, None] = "0015"
    branch_labels: Union[str, Sequence[str], None] = None
    depends_on: Union[str, Sequence[str], None] = None

    def upgrade() -> None:
        # object_id: erst nullable anlegen, backfillen, dann NOT NULL setzen
        # (falls wartungspflichten-Rows aus Migration 0010 existieren)
        op.add_column(
            "wartungspflichten",
            sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_wartungspflichten_object_id",
            "wartungspflichten", "objects",
            ["object_id"], ["id"], ondelete="CASCADE",
        )
        op.create_index(
            "ix_wartungspflichten_object_id",
            "wartungspflichten", ["object_id"],
        )
        # Backfill aus policy.object_id
        op.execute("""
            UPDATE wartungspflichten w
            SET object_id = p.object_id
            FROM policen p
            WHERE w.policy_id = p.id AND w.object_id IS NULL
        """)
        # NOT NULL erzwingen
        op.alter_column("wartungspflichten", "object_id", nullable=False)

        op.add_column(
            "wartungspflichten",
            sa.Column("letzte_wartung", sa.Date(), nullable=True),
        )

    def downgrade() -> None:
        op.drop_column("wartungspflichten", "letzte_wartung")
        op.drop_index("ix_wartungspflichten_object_id", table_name="wartungspflichten")
        op.drop_constraint("fk_wartungspflichten_object_id", "wartungspflichten", type_="foreignkey")
        op.drop_column("wartungspflichten", "object_id")
    ```
  - [x] 1.3 `next_due_date`-Index existiert bereits aus Migration 0010 — nicht erneut anlegen.

- [x] **Task 2 — ORM: `Wartungspflicht` erweitern + Relationships beidseitig** (AC1, AC2)
  - [x] 2.1 `app/models/police.py` — `Wartungspflicht`-Klasse nach `dienstleister_id` ergänzen:
    ```python
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    letzte_wartung: Mapped[date | None] = mapped_column(Date, nullable=True)
    ```
    Imports: `date` und `Date` sind bereits im Modul.
  - [x] 2.2 Relationships auf `Wartungspflicht` (nach `notes`, vor Timestamps):
    ```python
    policy: Mapped["InsurancePolicy | None"] = relationship(
        "InsurancePolicy", back_populates="wartungspflichten", foreign_keys=[policy_id]
    )
    object: Mapped["Object"] = relationship(  # noqa: F821
        "Object", back_populates="wartungspflichten", foreign_keys=[object_id]
    )
    dienstleister: Mapped["Dienstleister | None"] = relationship(  # noqa: F821
        "Dienstleister", foreign_keys=[dienstleister_id]
    )
    ```
  - [x] 2.3 `InsurancePolicy` — Relationship ergänzen (nach `object`-Relationship):
    ```python
    wartungspflichten: Mapped[list["Wartungspflicht"]] = relationship(
        "Wartungspflicht",
        back_populates="policy",
        foreign_keys="[Wartungspflicht.policy_id]",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    ```
  - [x] 2.4 `app/models/object.py` — `Object`-Klasse: Backref für Due-Radar (Story 2.5):
    ```python
    wartungspflichten: Mapped[list["Wartungspflicht"]] = relationship(
        "Wartungspflicht",
        back_populates="object",
        foreign_keys="[Wartungspflicht.object_id]",
        cascade="all, delete-orphan",
        lazy="noload",  # nur explizit laden, keine Default-Joins
    )
    ```
    `lazy="noload"` — standardmäßig wird die Collection nicht geladen; Due-Radar holt sie per expliziter Query. Verhindert `DetachedInstanceError` in Jinja2 wenn Session geschlossen ist.

- [x] **Task 3 — Neuer Service `app/services/steckbrief_wartungen.py`** (AC1, AC3, AC4)
  - [x] 3.1 Datei anlegen:
    ```python
    """Service-Helfer für Wartungspflichten und Dienstleister-Registry (Story 2.2)."""
    from __future__ import annotations

    import uuid
    from datetime import date, timedelta
    from typing import Any

    from fastapi import Request
    from sqlalchemy import select
    from sqlalchemy.orm import Session, joinedload

    from app.models import InsurancePolicy, User, Wartungspflicht
    from app.models.registry import Dienstleister
    from app.services.audit import audit
    from app.services.steckbrief_write_gate import write_field_human
    ```
  - [x] 3.2 `get_all_dienstleister(db) -> list[Dienstleister]` — alphabetisch nach `name` für Dropdown.
  - [x] 3.3 `get_wartungspflichten_for_policy(db, policy_id) -> list[Wartungspflicht]` — Fallback mit `joinedload(dienstleister)`, gefiltert auf `policy_id`, sortiert `next_due_date ASC NULLS LAST`, `created_at ASC`. Für Template-Nutzung reicht `policy.wartungspflichten` (`lazy="selectin"`).
  - [x] 3.4 `get_due_severity(next_due_date: date | None) -> str | None` — Return `"critical"` wenn `<= today + 30d`, `"warning"` wenn `<= today + 90d`, sonst `None`. `None` wenn Input `None`.
    > **Dev-Note**: Diese Funktion wird in Story 2.5 nach `app/services/due_radar.py` migriert als Cross-Cutting-Helper für Due-Radar-View. In Story 2.2 bewusst lokal gehalten, damit der Scope klein bleibt.
  - [x] 3.5 `validate_wartung_dates(letzte_wartung, intervall_monate, next_due_date) -> str | None`:
    - Wenn `letzte_wartung` und `next_due_date` beide gesetzt und `next_due_date <= letzte_wartung`: `"Nächste Fälligkeit muss nach Letzter Wartung liegen."`
    - Wenn alle drei gesetzt und `abs((next_due_date - letzte_wartung).days - intervall_monate * 30) > 45`: `"Hinweis: Intervall und Datumsabstand weichen stark voneinander ab."` (Soft-Hint, nicht blockend — Render als Gelber Warnbanner)
    - Sonst `None`
  - [x] 3.6 `create_wartungspflicht(db, policy, user, request, *, bezeichnung, dienstleister_id, intervall_monate, letzte_wartung, next_due_date) -> Wartungspflicht`:
    - Row-Create minimal: `wart = Wartungspflicht(policy_id=policy.id, object_id=policy.object_id); db.add(wart); db.flush()`
    - Für jedes nicht-None Feld (`bezeichnung`, `dienstleister_id`, `intervall_monate`, `letzte_wartung`, `next_due_date`): `write_field_human(...)`
    - Entity-Type wird vom Gate via `Wartungspflicht.__tablename__ == "wartungspflichten"` → `"wartung"` abgeleitet.
    - Kein `db.commit()` — Caller committed.
  - [x] 3.7 `delete_wartungspflicht(db, wart, user, request) -> None`:
    - `audit(db, user, "object_field_updated", entity_type="wartung", entity_id=wart.id, details={"action": "delete", "bezeichnung": wart.bezeichnung, "policy_id": str(wart.policy_id)}, request=request)`
    - **Begründung**: `object_field_updated` wird genutzt, weil `"wartung"` nicht in `_REGISTRY_ENTITY_TYPES` ist. Story 2.1 nutzt `registry_entry_updated` für Police-Delete — das ist dort auch nicht ganz sauber, aber wir folgen nicht dem inkonsistenten Muster. Falls der Task-0-Precheck zeigt, dass `KNOWN_AUDIT_ACTIONS` das ablehnt: Action hinzufügen in `app/services/audit.py`.
    - `db.delete(wart)` — kein commit.
  - [x] 3.8 `create_dienstleister(db, user, request, *, name, gewerke_tags) -> Dienstleister`:
    - `d = Dienstleister(name=name, gewerke_tags=gewerke_tags); db.add(d); db.flush()`
    - `audit(db, user, "registry_entry_created", entity_type="dienstleister", entity_id=d.id, details={"name": name}, request=request)`
    - Kein commit.

- [x] **Task 4 — `registries.py` erweitern: Dienstleister-Route** (AC4, AC5)
  - [x] 4.1 `app/routers/registries.py` EXISTIERT bereits (aus Story 2.1) — NUR ERWEITERN.
  - [x] 4.2 Import: `from app.services.steckbrief_wartungen import create_dienstleister, get_all_dienstleister`
  - [x] 4.3 `POST /registries/dienstleister`:
    - Permission: `Depends(require_permission("registries:edit"))`
    - Form-Felder: `name: str = Form(...)`, `gewerke_tags_raw: str | None = Form(None)`, `policy_id: uuid.UUID | None = Form(None)` (optional, für OOB-Target-Disambig; leer bei späteren standalone-Nutzungen).
    - Validierung: `if not name.strip():` → 422 mit Fragment `_registries_dienstleister_form.html` + `error="Name ist Pflichtfeld"`.
    - `gewerke_tags = [t.strip() for t in gewerke_tags_raw.split(",") if t.strip()] if gewerke_tags_raw else []`
    - `new_d = create_dienstleister(db, user, request, name=name.strip(), gewerke_tags=gewerke_tags); db.commit()`
    - **Response-Logik:**
      - Wenn `policy_id` gesetzt: HTMLResponse mit zwei OOB-Fragmenten —
        1. `_registries_dienstleister_options.html` mit Template-Context `target_dropdown_id=f"dienstleister-dropdown-{policy_id}"`, `all_dienstleister=get_all_dienstleister(db)`, `selected_id=new_d.id` → Select mit `id="dienstleister-dropdown-{policy_id}"` und `hx-swap-oob="true"`.
        2. `<div id="new-dienstleister-inline-{{policy_id}}" hx-swap-oob="true"></div>` — räumt das Sub-Formular ab.
      - Wenn `policy_id` None: nur `_registries_dienstleister_options.html` mit `target_dropdown_id="dienstleister-dropdown"` (standalone-Fall für spätere Stories).

- [x] **Task 5 — Wartungspflicht-Routen in `app/routers/objects.py`** (AC1, AC3, AC5, AC6)
  - [x] 5.1 Imports:
    ```python
    from app.models import InsurancePolicy, Wartungspflicht
    from app.services.steckbrief_wartungen import (
        create_wartungspflicht, delete_wartungspflicht,
        get_all_dienstleister, get_due_severity,
        validate_wartung_dates,
    )
    ```
    **`_parse_date` NICHT neu definieren** — wurde in Story 2.1 in `objects.py` (Modul-Level) angelegt. Bei Fehlen: als Fehler markieren und Story 2.1 nachbessern, nicht duplizieren.
  - [x] 5.2 `POST /objects/{object_id}/policen/{policy_id}/wartungspflichten` — Neue Wartungspflicht (AC1, AC5, AC6):
    - Permission: `Depends(require_permission("objects:edit"))`
    - **ERSTER Aufruf**: `obj = _load_accessible_object(db, object_id, user)` — bricht mit 404 ab wenn kein Zugriff (AC6)
    - `policy = db.get(InsurancePolicy, policy_id)` + `if policy is None or policy.object_id != obj.id:` → 404 (kein 500)
    - Form-Felder parsen: `bezeichnung` (str), `dienstleister_id` (UUID oder leer → None), `intervall_monate` (int oder leer → None), `letzte_wartung` (date via `_parse_date`), `next_due_date` (date via `_parse_date`)
    - `if not bezeichnung.strip():` → 422 mit deutschem Fehlertext "Bezeichnung ist Pflichtfeld."
    - `warn = validate_wartung_dates(letzte_wartung, intervall_monate, next_due_date)` → wenn `warn` den `"muss nach"`-Text enthält: 422-Fragment (Blocker). Bei "Hinweis: Intervall ..."-Text: persistieren und Hinweis im Response-Fragment mit-rendern (Soft-Warn).
    - `create_wartungspflicht(db, policy, user, request, ...)` + `db.commit()`
    - **Rückgabe**: frisches Per-Police-Fragment `_obj_versicherungen_row.html` mit aktualisierter Police-Zeile (siehe Task 6.1 für Fragment-Granularität).
  - [x] 5.3 `DELETE /objects/{object_id}/wartungspflichten/{wart_id}` — Wartungspflicht löschen (AC3, AC5, AC6):
    - Permission: `Depends(require_permission("objects:edit"))`
    - **ERSTER Aufruf**: `obj = _load_accessible_object(db, object_id, user)` (AC6)
    - `wart = db.get(Wartungspflicht, wart_id)` + `if wart is None or wart.object_id != obj.id:` → 404
    - **Cross-Police-Guard**: `if wart.policy and wart.policy.object_id != obj.id:` → 404 (auch wenn `wart.object_id == obj.id` wäre; defense in depth)
    - `policy = wart.policy`  # vor `db.delete` merken für Response-Rendering
    - `delete_wartungspflicht(db, wart, user, request)` + `db.commit()`
    - **Rückgabe**: `_obj_versicherungen_row.html` für die betroffene `policy` — nicht die ganze Sektion.
  - [x] 5.4 `GET /objects/{object_id}/sections/versicherungen` (existiert aus Story 2.1) — Context erweitern:
    - `dienstleister_list = get_all_dienstleister(db)` hinzufügen
    - `get_due_severity` als Callable im Context übergeben (Template: `{% set sev = get_due_severity(w.next_due_date) %}`)
  - [x] 5.5 `object_detail`-Handler (bestehend): gleiche zwei Context-Keys ergänzen (`dienstleister_list`, `get_due_severity`) — konsistent mit Sektion-Route.

- [x] **Task 6 — Templates (Per-Police-Fragment-Granularität)** (AC1, AC2, AC3, AC4)
  - [x] 6.1 `app/templates/_obj_versicherungen.html` ERWEITERN — Markup-Granularität: **jede Police wird zu einem `<article data-policy-id="{{ policy.id }}">`-Block**, nicht mehr eine einzelne `<tr>`. Gesamt-Sektion-Wrapper bleibt `<section data-section="versicherungen">`. Inhalt jedes Artikels: Policen-Header (Versicherer, Nr., Fälligkeit, Prämie, Edit/Delete-Buttons) + `<details>`-Sub-Block für Wartungspflichten. Das erlaubt Per-Police-Swap statt Whole-Section-Swap.
  - [x] 6.2 Neue Datei `app/templates/_obj_versicherungen_row.html` — rendert **einen** `<article data-policy-id>`-Block:
    ```jinja
    {# Fragment für Single-Police-Swap nach Wartungspflicht-CRUD #}
    <article data-policy-id="{{ policy.id }}" class="mb-4 p-3 border rounded">
      {# Police-Header-Zeile — Struktur identisch zum Block aus _obj_versicherungen.html #}
      <div class="flex items-baseline gap-4">
        <span class="font-medium">{{ policy.versicherer.name if policy.versicherer else "—" }}</span>
        <span class="text-sm">{{ policy.police_number or "" }}</span>
        <span class="text-sm text-slate-500">Fällig: {{ policy.next_main_due.strftime("%d.%m.%Y") if policy.next_main_due else "—" }}</span>
        <span class="ml-auto text-sm">{{ policy.praemie or "—" }} €</span>
      </div>
      {# Wartungspflichten-Sub-Block #}
      <details class="mt-2 ml-4">
        <summary class="cursor-pointer text-sm text-slate-600 hover:text-slate-900">
          {% set n = policy.wartungspflichten|length %}
          {{ n }} {% if n == 1 %}Wartungspflicht{% else %}Wartungspflichten{% endif %}
        </summary>
        {% if policy.wartungspflichten %}
          <table class="mt-2 w-full text-sm">
            <thead><tr class="text-left text-slate-500">
              <th class="py-1">Bezeichnung</th><th>Dienstleister</th><th>Intervall</th>
              <th>Letzte</th><th>Nächste</th><th></th>
            </tr></thead>
            <tbody>
            {% for w in policy.wartungspflichten %}
              {% set sev = get_due_severity(w.next_due_date) %}
              <tr class="border-t">
                <td class="py-1">{{ w.bezeichnung }}</td>
                <td>{{ w.dienstleister.name if w.dienstleister else "—" }}</td>
                <td>{{ w.intervall_monate }} Mo.</td>
                <td>{{ w.letzte_wartung.strftime("%d.%m.%Y") if w.letzte_wartung else "—" }}</td>
                <td>
                  {{ w.next_due_date.strftime("%d.%m.%Y") if w.next_due_date else "—" }}
                  {% if sev == "critical" %}<span class="ml-1 px-2 py-0.5 text-xs bg-red-100 text-red-800 rounded">fällig</span>
                  {% elif sev == "warning" %}<span class="ml-1 px-2 py-0.5 text-xs bg-orange-100 text-orange-800 rounded">bald</span>
                  {% endif %}
                </td>
                <td>
                  {% if has_permission(user, "objects:edit") %}
                  <button type="button"
                          hx-delete="/objects/{{ obj.id }}/wartungspflichten/{{ w.id }}"
                          hx-target="closest article" hx-swap="outerHTML"
                          hx-confirm="Wartungspflicht '{{ w.bezeichnung }}' wirklich löschen?"
                          class="text-red-600 text-xs">Löschen</button>
                  {% endif %}
                </td>
              </tr>
            {% endfor %}
            </tbody>
          </table>
        {% endif %}
        {% if has_permission(user, "objects:edit") %}
          {# Add-Form pro Police: eigenes Dropdown-ID + eigener Inline-Container pro policy.id #}
          <form hx-post="/objects/{{ obj.id }}/policen/{{ policy.id }}/wartungspflichten"
                hx-target="closest article" hx-swap="outerHTML"
                class="mt-3 grid grid-cols-2 gap-2 text-sm">
            <input type="text" name="bezeichnung" placeholder="Bezeichnung *" required class="p-1 border rounded">
            <div class="flex gap-1">
              <select id="dienstleister-dropdown-{{ policy.id }}" name="dienstleister_id" class="flex-1 p-1 border rounded">
                <option value="">— Dienstleister wählen —</option>
                {% for d in dienstleister_list %}
                  <option value="{{ d.id }}">{{ d.name }}</option>
                {% endfor %}
              </select>
              <button type="button"
                      hx-get="/registries/dienstleister/new-form?policy_id={{ policy.id }}"
                      hx-target="#new-dienstleister-inline-{{ policy.id }}" hx-swap="innerHTML"
                      class="px-2 border rounded text-blue-600">+</button>
            </div>
            <input type="number" name="intervall_monate" placeholder="Intervall (Monate)" class="p-1 border rounded">
            <input type="date" name="letzte_wartung" class="p-1 border rounded">
            <input type="date" name="next_due_date" placeholder="Nächste Fälligkeit" class="p-1 border rounded">
            <button type="submit" class="px-3 py-1 bg-blue-600 text-white rounded">Wartungspflicht hinzufügen</button>
          </form>
          <div id="new-dienstleister-inline-{{ policy.id }}"></div>
        {% endif %}
      </details>
    </article>
    ```
    In `_obj_versicherungen.html`: statt Inline-Rendering pro Police die Iteration auf `{% include "_obj_versicherungen_row.html" %}` umstellen — Single-Source-of-Truth für Police-Markup.
  - [x] 6.3 Neue Datei `app/templates/_registries_dienstleister_form.html` (analog zu `_registries_versicherer_form.html` aus Story 2.1):
    - Pflichtfeld Name, optional gewerke_tags (Freitext, komma-sep.)
    - Hidden-Input: `<input type="hidden" name="policy_id" value="{{ policy_id }}">` — wird vom Server für OOB-Target-Disambig genutzt.
    - `hx-post="/registries/dienstleister"`, **kein `hx-target`** — Server antwortet mit OOB-Swaps auf den Dropdown und den Container.
    - Abbrechen-Button: `onclick="document.getElementById('new-dienstleister-inline-{{ policy_id }}').innerHTML=''"`
  - [x] 6.4 Neue Route `GET /registries/dienstleister/new-form` in `registries.py` — liefert `_registries_dienstleister_form.html` mit `policy_id` aus Query-Param (Permission `registries:edit`).
  - [x] 6.5 Neue Datei `app/templates/_registries_dienstleister_options.html`:
    ```jinja
    <select id="{{ target_dropdown_id }}" name="dienstleister_id" class="flex-1 p-1 border rounded" hx-swap-oob="true">
      <option value="">— Dienstleister wählen —</option>
      {% for d in all_dienstleister %}
        <option value="{{ d.id }}"{% if d.id == selected_id %} selected{% endif %}>{{ d.name }}</option>
      {% endfor %}
    </select>
    ```
    Wird vom POST `/registries/dienstleister` als erster OOB-Block gerendert, gefolgt vom Container-Reset-OOB (siehe Task 4.3).

- [x] **Task 7 — Tests** (AC1, AC3, AC6, AC7)
  - [x] 7.1 Neue Datei `tests/test_wartungspflichten_unit.py` — reine Service-Unit-Tests:
    - `test_get_due_severity_critical`: `today + 15d` → `"critical"`
    - `test_get_due_severity_warning`: `today + 60d` → `"warning"`
    - `test_get_due_severity_far_future`: `today + 365d` → `None`
    - `test_get_due_severity_none_input`: `None` → `None`
    - `test_validate_wartung_dates_ok`: `next_due_date > letzte_wartung`, Intervall passt → `None`
    - `test_validate_wartung_dates_next_before_letzte`: `next_due_date <= letzte_wartung` → Error-Text mit "muss nach"
    - `test_validate_wartung_dates_intervall_mismatch`: `intervall_monate=12`, Datumsabstand 2 Jahre → Hinweis-Text mit "weichen stark"
    - `test_create_wartungspflicht_writes_provenance_for_all_fields`: Genau 5 `FieldProvenance`-Rows (bezeichnung, dienstleister_id, intervall_monate, letzte_wartung, next_due_date), alle mit `source="user_edit"`, `entity_type="wartung"`.
    - `test_create_wartungspflicht_object_id_from_policy`: `wart.object_id == policy.object_id` (keine Route-Param-Übernahme, sondern aus Police abgeleitet).
    - `test_create_wartungspflicht_skips_none_fields`: `dienstleister_id=None` → keine Provenance für dieses Feld.
    - `test_delete_wartungspflicht_writes_audit`: `AuditLog action="object_field_updated"`, `entity_type="wartung"`, `details_json["action"] == "delete"`.
    - `test_create_dienstleister_writes_audit`: `AuditLog action="registry_entry_created"`, `entity_type="dienstleister"`.
    - `test_delete_policy_cascades_wartungspflichten`: Police mit 2 Wartungspflichten; `db.delete(policy); db.flush()` → beide Wartungspflicht-Rows weg (Cascade).
    - `test_get_policen_loads_wartungspflichten_without_n_plus_1`: mit `sqlalchemy.event.listen`-Query-Counter: 3 Policen mit je 2 Wartungspflichten → Query-Count ≤ 3 (selectin lädt alle Wartungspflichten in einem SELECT IN).
  - [x] 7.2 Neue Datei `tests/test_wartungspflichten_routes_smoke.py` — TestClient-basiert:
    - **AC1 (Create)**:
      - `test_post_wartungspflicht_creates_with_all_fields`: 200, neue Zeile im Response-Fragment, DB-Row mit allen Werten.
      - `test_post_wartungspflicht_with_empty_dienstleister`: `dienstleister_id=""` → 200, `wart.dienstleister_id IS NULL`.
      - `test_post_wartungspflicht_without_bezeichnung`: `bezeichnung=""` → 422, kein DB-Row.
      - `test_post_wartungspflicht_with_invalid_dates`: `next_due_date < letzte_wartung` → 422, kein DB-Row.
      - `test_post_wartungspflicht_with_intervall_hint`: 12 Monate vs. 24 Monate Abstand → 200, Response enthält Soft-Hint-Banner.
    - **AC2 (Anzeige)**:
      - `test_get_versicherungen_shows_wartungspflichten_expanded`: Police mit 2 Wartungspflichten → Fragment enthält `<details>` + beide Bezeichnungen.
      - `test_severity_badge_critical_for_due_within_30_days`: `next_due_date = today + 10d` → Fragment enthält CSS-Klasse `bg-red-100`.
    - **AC3 (Delete)**:
      - `test_delete_wartungspflicht_removes_row_and_audits`: AuditLog + Row weg, Per-Police-Fragment zurück.
      - `test_delete_wartungspflicht_returns_only_policy_row`: Response-Body enthält **ein** `<article data-policy-id>`, keine Section-Wrapper.
    - **AC4 (Neuer Dienstleister)**:
      - `test_post_dienstleister_creates_and_returns_two_oob_swaps`: POST mit `policy_id=X` → 200, Body enthält `id="dienstleister-dropdown-{policy_id}"` mit `hx-swap-oob="true"` UND `id="new-dienstleister-inline-{policy_id}"`-Reset.
      - `test_post_dienstleister_without_policy_id`: `policy_id=None` → 200, OOB zielt auf `dienstleister-dropdown` (ohne Suffix).
      - `test_post_dienstleister_empty_name`: 422 mit "Name ist Pflichtfeld"-Text.
      - `test_get_dienstleister_new_form_requires_policy_id`: `GET /registries/dienstleister/new-form?policy_id=X` → 200, Formular mit Hidden-Input.
    - **AC5 (Permission)**:
      - `test_wartungspflicht_post_403_for_viewer`
      - `test_wartungspflicht_delete_403_for_viewer`
      - `test_dienstleister_post_403_without_registries_edit`
      - `test_versicherungen_section_hides_wartung_buttons_for_viewer`
    - **AC6 (accessible_object_ids — Retro P2)**:
      - `test_wartungspflicht_post_404_when_object_not_accessible`
      - `test_wartungspflicht_delete_404_when_object_not_accessible`
      - `test_wartungspflicht_delete_404_when_wart_belongs_to_other_object`: Wartung gehört Objekt A, DELETE URL nutzt Objekt B → 404.
      - `test_wartungspflicht_delete_404_when_policy_belongs_to_other_object`: Wartung hat `object_id=A`, aber `policy.object_id=B` (Daten-Inkonsistenz durch Manipulation) → Cross-Police-Guard blockt mit 404.
      - `test_wartungspflicht_post_404_when_policy_belongs_to_other_object`: POST auf `/objects/A/policen/{pid}/wartungspflichten`, aber `policy.object_id=B` → 404.
    - **Regression**:
      - `test_write_gate_coverage_still_green`: `from tests.test_write_gate_coverage import test_no_direct_writes_to_cd1_entities_textscan; test_no_direct_writes_to_cd1_entities_textscan()` — muss nach neuen Services/Routern grün bleiben.

- [x] **Task 8 — Regression + manueller Test** (AC7)
  - [x] 8.1 `pytest -x` im Container — alle Tests grün.
  - [x] 8.2 `test_write_gate_coverage` prüfen — kein direktes `wart.<attr> = value` außerhalb Row-Creation.
  - [x] 8.3 Manueller Test (Edge-Cases):
    - Wartungspflicht anlegen **ohne** `dienstleister_id` (optional) → persistiert, Dropdown zeigt "—".
    - Wartungspflicht anlegen **ohne** `next_due_date` → kein Badge, Spalte zeigt "—".
    - Wartungspflicht mit Datum 15 Tage in Zukunft → roter Badge "fällig".
    - Wartungspflicht mit Datum 60 Tage in Zukunft → oranger Badge "bald".
    - Drei Policen öffnen alle `<details>`, **eine** Wartungspflicht an Police B hinzufügen → Police A und C bleiben expandiert (Per-Police-Swap verifiziert).
    - Neuer Dienstleister über Inline-Form → Dropdown in Formular aktualisiert, Inline-Container geleert.
    - Police löschen (Story 2.1-Funktion) mit 2 Wartungspflichten daran → Wartungspflichten sind weg (Cascade verifiziert).

## Dev Notes

### Abhängigkeit von Story 2.1 (KRITISCH)

Story 2.2 baut auf Story 2.1-Code auf. Task 0 enthält die `ls`/`grep`-Prechecks. Bei fehlenden Artefakten Story 2.1 zuerst fertigstellen — Story 2.2 ist nicht parallelisierbar.

### Kritische Implementation-Details (kompakt)

- **`entity_type="wartung"`** (nicht `"wartungspflicht"`) — Mapping in `_TABLE_TO_ENTITY_TYPE["wartungspflichten"]`.
- **Delete-Action `object_field_updated`** mit `details_json.action="delete"` — weil `"wartung"` nicht in `_REGISTRY_ENTITY_TYPES`. Test 7.1 `test_delete_wartungspflicht_writes_audit` pinnt das. Vor Implementation: `KNOWN_AUDIT_ACTIONS` in `app/services/audit.py` erweitern falls nötig.
- **`object_id` ist NOT NULL** (Migration 0016) — immer aus `policy.object_id` abgeleitet, nie vom Router gesetzt. Due-Radar (Story 2.5) verlässt sich darauf.
- **Cross-Police-Guard im DELETE** (AC6): doppelter Check (`wart.object_id == obj.id` UND `wart.policy.object_id == obj.id`) — defense in depth gegen manipulierte Daten.
- **`policy_id` vs. `police_id`**: DB-Spalte ist `policy_id` (englisch). Epic-Text "police_id" ist Domain-Sprache; Code immer `policy_id`.
- **`_parse_date` aus Story 2.1 wiederverwenden** — Modul-Level-Helper in `objects.py`. Nicht duplizieren.
- **Per-Police-Fragment (`_obj_versicherungen_row.html`)** statt Whole-Section-Swap: erhalten die `<details>`-Zustände anderer Policen nach CRUD. Response-Target: `closest article` mit `outerHTML`.
- **Pro-Police-Dropdown-ID**: `id="dienstleister-dropdown-{{ policy.id }}"` + Hidden-`policy_id`-Input im Inline-Formular. Server rendert den OOB-Swap mit korrektem `target_dropdown_id`.
- **`lazy="selectin"` auf `InsurancePolicy.wartungspflichten`**: Template iteriert `policy.wartungspflichten` direkt — SQLAlchemy lädt per SELECT IN, kein N+1. Aber: nur innerhalb der DB-Session gültig. In Jinja2 nach Session-Close → `DetachedInstanceError`. In `objects.py` sicherstellen, dass der TemplateResponse **innerhalb** des `get_db()`-Kontexts gerendert wird (Standard-Pattern, aber bewusst markiert).
- **`lazy="noload"` auf `Object.wartungspflichten`**: bewusst gewählt — nur Due-Radar (Story 2.5) lädt die Collection per expliziter Query.

### Severity-Helper wandert in Story 2.5

`get_due_severity()` lebt in Story 2.2 in `app/services/steckbrief_wartungen.py`. Story 2.5 (Due-Radar) wird die Funktion nach `app/services/due_radar.py` verschieben als Cross-Cutting-Helper für Schadensfälle, Pendenzen und Wartungen. Jetzt bewusst nicht vorziehen, damit Story 2.2-Scope klein bleibt. Beim Refactor in 2.5: Import-Pfad in `objects.py` + `steckbrief_wartungen.py` mitziehen, alten Helper entfernen.

### Aus Story 2.1 gelernt — verhindert Wiederholung

- `TemplateResponse(request, "name.html", {...})` — Request zuerst (Starlette ≥ 0.21).
- Write-Gate-Coverage-Test: kein direktes `entity.field = value` außerhalb Row-Creation.
- `registries.py` und `_obj_versicherungen.html` nicht neu anlegen — nur erweitern (Task 0 prüft).
- `db.commit()` im Router, nicht im Service.
- Fragment-Template-Underscore-Prefix.
- Retro P2 (Security-Gate): `_load_accessible_object` ist Pflicht auf jeder neuen Objekt-Route.

### Nicht in Story 2.2 (Deferred)

- **Edit-Formular für bestehende Wartungspflicht**: Epic hat nur Add + Delete. Kein `PUT /wartungspflichten/{id}` — bei Änderungen: Löschen + Neu-Anlegen.
- **Dienstleister-Registry-Detailseite**: kommt in Story 2.7/2.8 analog Versicherer.
- **SEPA-Mandate pro Dienstleister**: aus SEPA-Workflow ableiten, nicht in 2.2.

### Deferred-Work-Bezüge

Keine neuen Deferred-Items aus Story 2.2. Bestehende Items in `deferred-work.md` sind für 2.2 nicht relevant.

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (1M context)

### Debug Log References

- `write_field_human` erfordert alle Parameter nach `db` als Keyword-Argumente (Signatur `def write_field_human(db, *, entity, field, ...)`).
- `Wartungspflicht.bezeichnung` ist NOT NULL → Row-Create mit Placeholder `""` damit `write_field_human` anschließend den echten Wert schreibt (Write-Gate No-Op greift sonst bei old==new && last is None).
- SQLAlchemy Identity-Map: Wartungspflichten via `policy_id` direkt angelegt (nicht via `policy.wartungspflichten.append()`) → `policy.wartungspflichten` ist "unloaded" bis `db.expire(policy)` + Access. Tests brauchen `db.expire_all()` vor HTTP-Request wenn Relationship-Content geprüft wird.
- ORM-Cascade `delete-orphan` auf `InsurancePolicy.wartungspflichten` benötigt geladene Collection — Test nutzt `db.expire(policy); _ = policy.wartungspflichten` vor `db.delete(policy)`.
- Bestehendes `test_get_versicherungen_section_shows_existing_policies` prüfte `data-police-id` (altes Attribut) — nach Template-Umbau auf `data-policy-id` (Story-Spec) angepasst.

### Completion Notes List

- **Migration 0016** (`migrations/versions/0016_wartungspflichten_missing_fields.py`): `object_id` UUID NOT NULL mit FK auf `objects.id` (CASCADE) + Index + Backfill-Script; `letzte_wartung` Date nullable.
- **ORM** (`app/models/police.py`): `Wartungspflicht` um `object_id` + `letzte_wartung` + Relationships `policy`/`object`/`dienstleister` erweitert. `InsurancePolicy` um `wartungspflichten` mit `cascade="all, delete-orphan"` + `lazy="selectin"`. `app/models/object.py`: `Object` um `wartungspflichten` mit `lazy="noload"` für Due-Radar (Story 2.5).
- **Service** (`app/services/steckbrief_wartungen.py`): `get_all_dienstleister`, `get_wartungspflichten_for_policy`, `get_due_severity`, `validate_wartung_dates`, `create_wartungspflicht`, `delete_wartungspflicht`, `create_dienstleister` — alle mit Write-Gate-Provenance und Audit.
- **Router Registries** (`app/routers/registries.py`): `GET /registries/dienstleister/new-form` + `POST /registries/dienstleister` mit OOB-Response-Logik (policy-spezifischer Dropdown + Container-Reset).
- **Router Objects** (`app/routers/objects.py`): `POST /{object_id}/policen/{policy_id}/wartungspflichten` + `DELETE /{object_id}/wartungspflichten/{wart_id}` mit `_load_accessible_object` + Cross-Police-Guard. `_render_versicherungen` + `object_detail` um `dienstleister_list` + `get_due_severity` erweitert.
- **Templates**: `_obj_versicherungen.html` auf `<article data-policy-id>`-Struktur umgebaut; neues `_obj_versicherungen_row.html` (Per-Police-Fragment); `_registries_dienstleister_form.html` + `_registries_dienstleister_options.html` für Inline-Anlage.
- **Tests**: 21 Unit-Tests + 23 Route-Smoke-Tests; alle 581 Tests grün (keine Regressionen).

### File List

- `migrations/versions/0016_wartungspflichten_missing_fields.py` (neu)
- `app/models/police.py` (geändert — `Wartungspflicht` + `InsurancePolicy`)
- `app/models/object.py` (geändert — `Object.wartungspflichten`)
- `app/services/steckbrief_wartungen.py` (neu)
- `app/routers/registries.py` (geändert — Dienstleister-Routen)
- `app/routers/objects.py` (geändert — Wartungspflicht-Routen + Context-Keys)
- `app/templates/_obj_versicherungen.html` (geändert — article-Struktur + include)
- `app/templates/_obj_versicherungen_row.html` (neu)
- `app/templates/_registries_dienstleister_form.html` (neu)
- `app/templates/_registries_dienstleister_options.html` (neu)
- `tests/test_wartungspflichten_unit.py` (neu)
- `tests/test_wartungspflichten_routes_smoke.py` (neu)
- `tests/test_policen_routes_smoke.py` (geändert — `data-police-id` → `data-policy-id`)

### Review Findings

Code-Review 2026-04-26 (3-Layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance Auditor).

- [x] [Review][Patch] Migration 0016: orphan-rows blockieren `alter_column NOT NULL` [`migrations/versions/0016_wartungspflichten_missing_fields.py:25-42`] — Backfill `WHERE w.policy_id = p.id` skipt rows mit `policy_id IS NULL` (Migration 0010 hat `ondelete="SET NULL"`). `alter_column` crashed dann mit `NotNullViolation`. Fix: orphan rows + rows mit nicht-backfillbarer policy.object_id vor dem ALTER löschen.
- [x] [Review][Patch] `police_create`/`police_update` 422-Renderer fehlen `dienstleister_list` + `get_due_severity` [`app/routers/objects.py:1086-1097, 1177-1188`] — `_obj_versicherungen.html:107` includiert `_obj_versicherungen_row.html`; rendert dort `get_due_severity(...)` wenn Wartungen existieren → `TypeError: 'Undefined' object is not callable` bei Police-Datums-Validierungs-Fehler auf Objekten mit Wartungspflichten.
- [x] [Review][Patch] Nicht-existente `dienstleister_id` → IntegrityError → 500 [`app/routers/objects.py:1254-1259`] — UUID wird syntaktisch geparst, Existenz nicht. FK-Violation bei `db.commit()` → unhandled 500. Fix: `db.get(Dienstleister, ...)`-Check vor `create_wartungspflicht`, sonst 422.
- [x] [Review][Patch] `_registries_dienstleister_form.html` rendert `value="None"` als policy_id [`app/templates/_registries_dienstleister_form.html:10,29`] — Wenn `policy_id` None (Standalone-Pfad), rendert Jinja `value="None"`; FastAPI `uuid.UUID | None = Form(None)` parst das als 422. cancel-onclick crasht analog (`getElementById('new-dienstleister-inline-None')` → null). Fix: Hidden-Input + cancel-onclick nur wenn `policy_id` gesetzt.
- [x] [Review][Patch] Cross-Police-Guard-Test fehlt für Daten-Manipulations-Variante [`tests/test_wartungspflichten_routes_smoke.py`] — Spec Task 7.2 verlangt explizit `test_wartungspflicht_delete_404_when_policy_belongs_to_other_object` (wart.object_id=A, policy.object_id=B). Vorhandener Test prüft nur ersten Guard. Fix: Test ergänzen, der den zweiten Guard via Daten-Manipulation auslöst.
- [x] [Review][Patch] Permission-Test deckt Wartung-Lösch-Button-Sichtbarkeit nicht ab [`tests/test_wartungspflichten_routes_smoke.py`] — AC5 verlangt "Lösch-Buttons nicht sichtbar" für Viewer; Test prüft nur "+ Wartungspflicht". Fix: Wartung anlegen, dann Section als Viewer abrufen → Lösch-Button-Markup nicht im Body.
- [x] [Review][Patch] `intervall_monate < 1` server-seitig nicht abgelehnt [`app/routers/objects.py:1261-1266`] — HTML `min="1"` ist client-side only; `parsed_intervall = -12` oder `0` persistiert. Fix: nach `int()`-Cast `if parsed_intervall is not None and parsed_intervall < 1: raise HTTPException(422, ...)`.
- [x] [Review][Defer] DELETE retourniert full section bei `wart.policy is None` [`app/routers/objects.py:1330-1331`] — deferred, edge-case nicht über regulären Pfad reachable (orphan-wart entsteht nur via raw SQL).
- [x] [Review][Defer] Audit `delete` action nutzt `object_field_updated` semantisch verwirrend [`app/services/steckbrief_wartungen.py:90-103`] — deferred, in Story-Spec Task 3.7 bewusst entschieden (`"wartung"` nicht in `_REGISTRY_ENTITY_TYPES`).
- [x] [Review][Defer] ORM cascade `delete-orphan` mit unloaded `lazy="selectin"`-Collection in Story-2.1-`delete_police`-Pfad [`app/services/steckbrief_policen.py`] — deferred, Story 2.2 nicht im Scope; Tests grün.
- [x] [Review][Defer] `letzte_wartung` in Zukunft / `next_due_date` in Past nicht geflaggt [`app/services/steckbrief_wartungen.py:33-49`] — deferred, Use-case-Frage (z.B. "verspätet eingetragene Wartung mit erfasstem next_due in Vergangenheit").
- [x] [Review][Defer] `intervall_monate` int32-Overflow → 500 [`app/routers/objects.py:1261-1266`] — deferred, exotischer Edge-Case; P7 deckt negative/0 ab.
- [x] [Review][Defer] NBSP-only-bezeichnung umgeht `strip()`-Check via Zero-Width-Space [`app/routers/objects.py:1248-1252`] — deferred, Echte User tippen kein ZWSP; Patch wäre Unicode-Whitespace-Awareness.
- [x] [Review][Defer] Stale Dropdown bei multiplen Policies nach Dienstleister-Add [`app/routers/registries.py:118-127`] — deferred, OOB-Swap zielt nur auf eine Police; UX-Verbesserung Future-Story.

## Change Log

- 2026-04-24: Story 2.2 implementiert — Wartungspflichten mit Policen-Verweis (Migration 0016, Service, Routen, Templates, Tests). 581 Tests grün.
- 2026-04-26: Code-Review (3 Layer). 7 Patches, 7 Defer, ~22 Dismiss.
