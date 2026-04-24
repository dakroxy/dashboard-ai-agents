# Story 2.3: Schadensfall direkt aus Objekt anlegen

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter mit `objects:edit`,
ich möchte einen Schadensfall direkt aus der Versicherungs-Sektion eines Objekts anlegen,
damit die Versicherer-Schadensquote automatisch aggregiert wird und Dokumentation nicht in Excel landet.

## Acceptance Criteria

**AC1 — Schadensfall anlegen**

**Given** ich öffne die Versicherungs-Sektion und klicke "Schadensfall melden"
**When** ich Police (Dropdown aus allen Policen des Objekts), optional Unit, Datum, geschätzte Summe und Beschreibung eingebe
**Then** wird ein `Schadensfall`-Record mit `policy_id` + optional `unit_id` + `amount` (`estimated_sum`) angelegt
**And** alle Feld-Writes laufen über `write_field_human` mit `entity_type="schaden"`
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` existiert

**AC2 — Schadensfall-Liste anzeigen**

**Given** ein Objekt mit mehreren Schadensfällen
**When** ich die Versicherungs-Sektion rendere
**Then** sehe ich eine Schadensfall-Liste (global für das Objekt) mit Datum, Police-Nummer/Versicherer, Unit (falls vorhanden), Summe, Status

**AC3 — Summen-Validierung**

**Given** der geschätzte Summen-Wert ist 0 oder negativ
**When** ich speichern will
**Then** blockt die Form mit einem deutschen Validierungsfehler, keine Persistierung

**AC4 — Permission-Gate**

**Given** ein User ohne `objects:edit`
**When** er die Versicherungs-Sektion betrachtet
**Then** ist der "Schadensfall melden"-Button nicht sichtbar
**And** ein direkter `POST /objects/{id}/schadensfaelle` gibt 403 (serverseitig)

**AC5 — Security-Gate: `accessible_object_ids` auf allen Objekt-bezogenen Schadensfall-Routes**

**Given** ein User mit `objects:edit`, aber das Objekt `{id}` ist **nicht** in seiner `accessible_object_ids`
**When** er `POST /objects/{id}/schadensfaelle` aufruft
**Then** antwortet der Server mit **HTTP 404** (nicht 403 — Nicht-Existenz und Nicht-Zugriff sind aus User-Sicht ununterscheidbar, NFR-S7, konsistent mit 2.1 AC6 / 2.2 AC6)
**And** kein DB-Read, kein Write, kein Audit-Eintrag
**Kontext**: Retrospektive-Finding aus Epic 1 (Story 1.8) wird auch auf die neue Schadensfall-Route angewandt — die `GET`-Routes (`/objects/{id}` + `/objects/{id}/sections/versicherungen`) sind bereits in 2.1 abgesichert.

**AC6 — Tests**

**Given** neue Datei `tests/test_schadensfaelle_unit.py`
**When** `pytest -x` läuft
**Then** alle bestehenden Tests (Stand nach Story 2.2 — exakte Floor-Zahl nach 2.2-Merge festnageln, analog 2.1 mit `>= 477` nach Story 1.8) + neue Unit-Tests sind grün

## Tasks / Subtasks

- [ ] **Task 0 — Precheck: Stories 2.1 + 2.2 abgeschlossen** (Voraussetzung für alle weiteren Tasks)

  Vor dem Start der Implementation bestätigen, dass die Upstream-Stories gemergt sind. 2.3 baut direkt
  auf ihrem Code auf — Migration, Services, Template und Helper müssen live sein.

  - [ ] 0.1 Migration 0016 applied: `docker compose exec app alembic current` zeigt `0016` (oder neuer).
  - [ ] 0.2 Dateien existieren:
    ```bash
    ls app/services/steckbrief_policen.py \
       app/services/steckbrief_wartungen.py \
       app/templates/_obj_versicherungen.html \
       app/routers/registries.py
    ```
  - [ ] 0.3 Helper `_load_accessible_object` existiert in `app/routers/objects.py` (von 2.1 eingeführt) —
    dieselbe Signatur wie in 2.2 Tasks 5.2/5.3 verwendet.
  - [ ] 0.4 Wenn einer der Checks fehlschlägt: Story 2.1/2.2 zuerst abschließen, nicht umbauen.

- [ ] **Task 1 — ORM: Relationships hinzufügen** (AC1, AC2)

  > KEIN neue Migration nötig — die Tabelle `schadensfaelle` existiert vollständig seit `0010_steckbrief_core.py`
  > mit allen benötigten Spalten: `policy_id`, `unit_id`, `amount`, `occurred_at`, `description`, `status`.
  > Neueste Migration nach Story 2.2 ist `0016`. Vor Task 1 prüfen: `ls migrations/versions/` — wenn
  > `0016_wartungspflichten_missing_fields.py` nicht vorhanden (weil 2.2 noch nicht gemergt), entsprechend
  > anpassen.

  - [ ] 1.1 `app/models/police.py` — `Schadensfall`-Klasse: Relationships nach den Spalten-Definitionen einfügen:
    ```python
    policy: Mapped["InsurancePolicy | None"] = relationship(
        "InsurancePolicy", back_populates="schadensfaelle", foreign_keys=[policy_id]
    )
    unit: Mapped["Unit | None"] = relationship(  # noqa: F821
        "Unit", foreign_keys=[unit_id]
    )
    ```
    Import prüfen: `Unit` ist in `app/models/object.py` definiert — kein direkter Import nötig, SQLAlchemy
    löst den String-Ref (`"Unit"`) über die Mapper-Registry auf. `InsurancePolicy` ist im selben File.

  - [ ] 1.2 `InsurancePolicy`-Klasse (gleiche Datei `app/models/police.py`): `schadensfaelle`-Relationship
    nach dem `wartungspflichten`-Relationship (aus Story 2.2) einfügen:
    ```python
    schadensfaelle: Mapped[list["Schadensfall"]] = relationship(
        "Schadensfall",
        back_populates="policy",
        foreign_keys="[Schadensfall.policy_id]",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    ```
    `lazy="selectin"`: Beim Laden von Policen über `get_policen_for_object()` werden die Schadensfälle
    automatisch mitgeladen — kein N+1, kein extra joinedload im Service nötig.
    `cascade="all, delete-orphan"`: Löschen der Police löscht zugehörige Schadensfälle (CASCADE ist bereits
    auf DB-Ebene via FK definiert, hier ORM-Konsistenz).

- [ ] **Task 2 — Neuer Service `app/services/steckbrief_schadensfaelle.py`** (AC1, AC2, AC3)
  - [ ] 2.1 Neue Datei anlegen:
    ```python
    """Service-Helfer für Schadensfälle (Story 2.3)."""
    from __future__ import annotations

    import uuid
    from datetime import date
    from decimal import Decimal, InvalidOperation
    from typing import Any

    from sqlalchemy import select
    from sqlalchemy.orm import Session, joinedload

    from app.models import Schadensfall, User
    from app.models.police import InsurancePolicy
    from app.models.object import Unit
    from app.services.steckbrief_write_gate import write_field_human
    ```

  - [ ] 2.2 `get_schadensfaelle_for_object(db: Session, object_id: uuid.UUID) -> list[Schadensfall]`:
    ```python
    def get_schadensfaelle_for_object(db: Session, object_id: uuid.UUID) -> list[Schadensfall]:
        return (
            db.execute(
                select(Schadensfall)
                .join(InsurancePolicy, Schadensfall.policy_id == InsurancePolicy.id)
                .where(InsurancePolicy.object_id == object_id)
                .options(
                    joinedload(Schadensfall.policy).joinedload(InsurancePolicy.versicherer),
                    joinedload(Schadensfall.unit),
                )
                .order_by(Schadensfall.occurred_at.desc().nullslast(), Schadensfall.created_at.desc())
            )
            .scalars()
            .all()
        )
    ```
    Hinweis: Das Join über `InsurancePolicy` filtert auf `object_id` — ein `Schadensfall` gehört immer
    transitiv zum Objekt über seine `policy_id`. Der joinedload auf `policy.versicherer` verhindert N+1
    beim Rendern des Versicherer-Namens in der Liste.

  - [ ] 2.3 `create_schadensfall(db, policy, user, request, *, occurred_at, amount, description, unit_id) -> Schadensfall`:
    ```python
    def create_schadensfall(
        db: Session,
        policy: InsurancePolicy,
        user: User,
        request: Any,
        *,
        occurred_at: date | None,
        amount: Decimal,
        description: str | None,
        unit_id: uuid.UUID | None,
    ) -> Schadensfall:
        schaden = Schadensfall(policy_id=policy.id)
        db.add(schaden)
        db.flush()  # ID generieren

        for field, value in [
            ("amount", amount),
            ("occurred_at", occurred_at),
            ("description", description),
            ("unit_id", unit_id),
        ]:
            if value is not None:
                write_field_human(
                    db, entity=schaden, field=field, value=value,
                    source="user_edit", user=user, request=request,
                )
        return schaden
    ```
    Kein `db.commit()` im Service — Caller committed.
    `policy_id` wird im Konstruktor gesetzt (Row-Creation-Pattern), nicht über `write_field_human` —
    FK-Felder beim Create sind zulässige Ausnahme vom Write-Gate (konsistent mit Stories 2.1/2.2).

- [ ] **Task 3 — Route `POST /objects/{object_id}/schadensfaelle`** in `app/routers/objects.py`** (AC1, AC3, AC4, AC5)

  - [ ] 3.1 Imports ergänzen:
    ```python
    from decimal import Decimal, InvalidOperation
    from app.models import Schadensfall
    from app.models.police import InsurancePolicy
    from app.services.steckbrief_schadensfaelle import (
        create_schadensfall,
        get_schadensfaelle_for_object,
    )
    ```
    `Unit` ist bereits über `app/models/object.py` importiert (prüfen ob `Unit` in `app/models/__init__.py`
    re-exportiert wird — falls nein: `from app.models.object import Unit` hinzufügen).

  - [ ] 3.2 Neue Route `POST /objects/{object_id}/schadensfaelle`:
    ```python
    @router.post("/{object_id}/schadensfaelle")
    async def create_schadensfall_route(
        request: Request,
        object_id: uuid.UUID,
        policy_id: uuid.UUID = Form(...),
        unit_id: str | None = Form(None),
        occurred_at: str | None = Form(None),
        estimated_sum: str = Form(...),
        description: str | None = Form(None),
        db: Session = Depends(get_db),
        user: User = Depends(require_permission("objects:edit")),
    ):
        # AC5: accessible_object_ids-Gate als ERSTER Aufruf — bricht mit 404 ab wenn kein Zugriff,
        # kein DB-Read auf Policy/Units/Schaden, kein Audit. Helper stammt aus Story 2.1.
        obj = _load_accessible_object(db, object_id, user)

        # Policy laden + Objekt-Zugehörigkeit prüfen
        policy = db.get(InsurancePolicy, policy_id)
        if not policy or policy.object_id != obj.id:
            raise HTTPException(404, detail="Police nicht gefunden")

        # Unit-ID validieren (optional)
        unit_uuid: uuid.UUID | None = None
        if unit_id and unit_id.strip():
            try:
                unit_uuid = uuid.UUID(unit_id.strip())
            except ValueError:
                raise HTTPException(422, detail="Ungültige Unit-ID")

        # Summen-Validierung (AC3)
        try:
            amount = Decimal(estimated_sum.replace(",", ".").strip())
        except InvalidOperation:
            raise HTTPException(422, detail="Summe muss eine Zahl sein")
        if amount <= 0:
            raise HTTPException(422, detail="Geschätzte Summe muss größer als 0 sein")

        # Datum parsen
        occ_date = _parse_date(occurred_at)

        create_schadensfall(
            db, policy, user, request,
            occurred_at=occ_date,
            amount=amount,
            description=description.strip() if description else None,
            unit_id=unit_uuid,
        )
        db.commit()

        # Sektion neu rendern
        policen = get_policen_for_object(db, obj.id)
        versicherer_list = get_all_versicherer(db)
        dienstleister_list = get_all_dienstleister(db)
        schadensfaelle = get_schadensfaelle_for_object(db, obj.id)
        units = obj.units  # via Object.units relationship (selectin oder lazy load)
        return templates.TemplateResponse(
            request, "_obj_versicherungen.html",
            {
                "obj": obj,
                "policen": policen,
                "versicherer_list": versicherer_list,
                "dienstleister_list": dienstleister_list,
                "schadensfaelle": schadensfaelle,
                "units": units,
                "get_due_severity": get_due_severity,
                "user": user,
            },
        )
    ```
    Hinweis: `get_policen_for_object`, `get_all_versicherer`, `get_all_dienstleister`, `get_due_severity`
    kommen aus Stories 2.1/2.2 (`steckbrief_policen.py`, `steckbrief_wartungen.py`). Imports anpassen.

  - [ ] 3.3 Bestehende `GET /objects/{object_id}/sections/versicherungen`-Route (erstellt in Story 2.1):
    Context um `schadensfaelle` + `units` erweitern:
    ```python
    schadensfaelle = get_schadensfaelle_for_object(db, obj.id)
    units = obj.units
    # Dann in context dict ergänzen:
    "schadensfaelle": schadensfaelle,
    "units": units,
    ```

  - [ ] 3.4 Ebenso den `object_detail`-Handler (`GET /objects/{object_id}`) — Context um `schadensfaelle`
    + `units` ergänzen, damit die Seite beim ersten Laden vollständig ist.

    > Hinweis: `obj.units` lädt die Units über die `Object.units`-Relationship (definiert in
    > `app/models/object.py:102`, `cascade="all, delete-orphan"`). Wenn die Relationship lazy ist,
    > sicherstellen dass der DB-Scope noch offen ist. Alternativ:
    > `units = db.scalars(select(Unit).where(Unit.object_id == obj.id).order_by(Unit.name)).all()`

- [ ] **Task 4 — Template `app/templates/_obj_versicherungen.html` erweitern** (AC1, AC2, AC4)

  > Dieses Template wird von Story 2.1 angelegt und von Story 2.2 erweitert — **NICHT neu anlegen, nur erweitern**.

  - [ ] 4.1 **Schadensfall-Meldeformular** (globaler Button für die gesamte Versicherungs-Sektion):
    Nach der Policen-Tabelle (und den Wartungspflichten unter jeder Police) einen Block hinzufügen:
    ```html
    {% if has_permission(user, "objects:edit") %}
    <div class="mt-6">
      <details id="schadensfall-form-toggle">
        <summary class="cursor-pointer inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium
                        bg-red-50 text-red-700 border border-red-200 rounded hover:bg-red-100">
          Schadensfall melden
        </summary>
        <div class="mt-3 p-4 border border-red-200 rounded-lg bg-red-50/50">
          <form hx-post="/objects/{{ obj.id }}/schadensfaelle"
                hx-target="[data-section='versicherungen']"
                hx-swap="outerHTML">
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <!-- Police (Pflicht) -->
              <div>
                <label class="block text-sm font-medium text-slate-700">Police *</label>
                <select name="policy_id" required
                        class="mt-1 w-full rounded border-slate-300 text-sm">
                  <option value="">— bitte wählen —</option>
                  {% for p in policen %}
                  <option value="{{ p.id }}">
                    {{ p.versicherer.name if p.versicherer else "Unbekannt" }}
                    {% if p.police_number %} · {{ p.police_number }}{% endif %}
                  </option>
                  {% endfor %}
                </select>
              </div>
              <!-- Unit (optional) -->
              <div>
                <label class="block text-sm font-medium text-slate-700">Einheit (optional)</label>
                <select name="unit_id"
                        class="mt-1 w-full rounded border-slate-300 text-sm">
                  <option value="">— keine —</option>
                  {% for u in units %}
                  <option value="{{ u.id }}">{{ u.name or u.impower_unit_id or u.id }}</option>
                  {% endfor %}
                </select>
              </div>
              <!-- Datum -->
              <div>
                <label class="block text-sm font-medium text-slate-700">Schadensdatum</label>
                <input type="date" name="occurred_at"
                       class="mt-1 w-full rounded border-slate-300 text-sm">
              </div>
              <!-- Geschätzte Summe (Pflicht) -->
              <div>
                <label class="block text-sm font-medium text-slate-700">Geschätzte Summe (€) *</label>
                <input type="number" name="estimated_sum" step="0.01" min="0.01" required
                       placeholder="0.00"
                       class="mt-1 w-full rounded border-slate-300 text-sm">
              </div>
              <!-- Beschreibung -->
              <div class="sm:col-span-2">
                <label class="block text-sm font-medium text-slate-700">Beschreibung</label>
                <textarea name="description" rows="2"
                          class="mt-1 w-full rounded border-slate-300 text-sm"></textarea>
              </div>
            </div>
            <div class="mt-3 flex gap-2">
              <button type="submit"
                      class="px-4 py-1.5 bg-red-600 text-white text-sm font-medium rounded hover:bg-red-700">
                Speichern
              </button>
              <button type="button" onclick="this.closest('details').removeAttribute('open')"
                      class="px-4 py-1.5 bg-white text-slate-600 text-sm border rounded hover:bg-slate-50">
                Abbrechen
              </button>
            </div>
          </form>
        </div>
      </details>
    </div>
    {% endif %}
    ```

  - [ ] 4.2 **Schadensfall-Liste** (global für das Objekt) nach dem Meldeformular einfügen:
    ```html
    {% if schadensfaelle %}
    <div class="mt-6">
      <h4 class="text-sm font-semibold text-slate-700 mb-2">Schadensfälle ({{ schadensfaelle|length }})</h4>
      <table class="w-full text-sm text-left border-collapse">
        <thead class="bg-slate-100 text-xs text-slate-600 uppercase">
          <tr>
            <th class="px-3 py-2">Datum</th>
            <th class="px-3 py-2">Police / Versicherer</th>
            <th class="px-3 py-2">Einheit</th>
            <th class="px-3 py-2 text-right">Summe (€)</th>
            <th class="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-200">
          {% for s in schadensfaelle %}
          <tr class="hover:bg-slate-50">
            <td class="px-3 py-2">
              {{ s.occurred_at.strftime("%d.%m.%Y") if s.occurred_at else "—" }}
            </td>
            <td class="px-3 py-2">
              {{ s.policy.versicherer.name if s.policy and s.policy.versicherer else "—" }}
              {% if s.policy and s.policy.police_number %}
                <span class="text-slate-400">· {{ s.policy.police_number }}</span>
              {% endif %}
            </td>
            <td class="px-3 py-2">
              {{ s.unit.name if s.unit and s.unit.name else (s.unit.impower_unit_id if s.unit else "—") }}
            </td>
            <td class="px-3 py-2 text-right tabular-nums">
              {{ "%.2f"|format(s.amount|float) if s.amount else "—" }}
            </td>
            <td class="px-3 py-2">
              <span class="text-xs px-2 py-0.5 rounded-full
                           {{ 'bg-slate-100 text-slate-600' if not s.status else 'bg-blue-100 text-blue-700' }}">
                {{ s.status or "offen" }}
              </span>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <p class="mt-6 text-sm text-slate-500 italic">Noch keine Schadensfälle erfasst.</p>
    {% endif %}
    ```

- [ ] **Task 5 — Tests `tests/test_schadensfaelle_unit.py` + `tests/test_schadensfaelle_routes_smoke.py`** (AC1, AC3, AC4, AC5, AC6)
  - [ ] 5.1 Neue Datei `tests/test_schadensfaelle_unit.py` anlegen
  - [ ] 5.2 `test_create_schadensfall_writes_provenance`:
    Mock-DB + User + Policy; `create_schadensfall(...)` mit `amount=Decimal("500")` aufrufen;
    prüfen dass `FieldProvenance`-Rows mit `source="user_edit"`, `entity_type="schaden"` für
    `amount` + `occurred_at` entstehen (analog zu Story 2.2 Tests)
  - [ ] 5.3 `test_create_schadensfall_no_unit`:
    `create_schadensfall(...)` mit `unit_id=None` aufrufen; prüfen dass kein `FieldProvenance`-Row
    für `unit_id` entsteht (None-Felder werden nicht geschrieben)
  - [ ] 5.4 `test_amount_validation_zero`:
    Route-Test (TestClient): `POST /objects/{id}/schadensfaelle` mit `estimated_sum=0` → 422
  - [ ] 5.5 `test_amount_validation_negative`:
    `POST /objects/{id}/schadensfaelle` mit `estimated_sum=-10` → 422
  - [ ] 5.6 `test_amount_validation_comma_decimal`:
    `estimated_sum="1.500,50"` (deutsche Notation) → 422 (der Server erwartet Punkt als Dezimaltrenner;
    Eingabe-Validierung liegt im Browser via `type="number"`, Server akzeptiert nur Punkt-Notation oder
    einfach `Decimal("1500,50")` ist InvalidOperation → korrekt 422)
  - [ ] 5.7 `test_policy_object_mismatch_gives_404`:
    Policy aus anderem Objekt übergeben → 404
  - [ ] 5.8 `test_permission_gate_returns_403` (AC4 — Server-Seite):
    `POST /objects/{id}/schadensfaelle` ohne `objects:edit` → 403
  - [ ] 5.9 `test_button_hidden_without_edit_permission` (AC4 — UI-Seite, neue Route-Smoke-Datei
    `tests/test_schadensfaelle_routes_smoke.py`): Viewer-User (read-only, ohne `objects:edit`) ruft
    `GET /objects/{id}` auf → Response-HTML enthält **nicht** `"Schadensfall melden"`
    (Analog-Pattern zu 2.1/2.2-Route-Smokes).
  - [ ] 5.10 `test_accessible_object_ids_gate_returns_404` (AC5):
    User mit `objects:edit`, aber ohne Zugriff auf Objekt `{id}` (nicht in `accessible_object_ids`)
    ruft `POST /objects/{id}/schadensfaelle` auf → 404. Prüfen, dass weder Policy-/Unit-Lookup
    noch Schadensfall-Insert noch Audit-Row entstehen.

- [ ] **Task 6 — Regression + Smoke** (AC6)
  - [ ] 6.1 `pytest -x` — alle Tests grün
  - [ ] 6.2 Manuelle Verifikation: Schadensfall anlegen, in Liste sehen, Validierungsfehler bei 0 testen

## Dev Notes

### Abhängigkeit von Stories 2.1 und 2.2 (KRITISCH)

Story 2.3 baut direkt auf dem Code aus 2.1 und 2.2 auf (Checkliste vor Start: siehe Task 0):
- `app/routers/registries.py` — muss existieren (2.1)
- `app/templates/_obj_versicherungen.html` — muss existieren (2.1), erweitern (2.2 fügt Wartungspflichten ein, 2.3 fügt Schadensfall-Form + Liste ein)
- `app/services/steckbrief_policen.py` mit `get_policen_for_object()`, `get_all_versicherer()` — muss existieren (2.1)
- `app/services/steckbrief_wartungen.py` mit `get_all_dienstleister()`, `get_due_severity()` — muss existieren (2.2)
- `GET /objects/{id}/sections/versicherungen`-Route — muss existieren (2.1), wird erweitert (2.3)
- Helper `_load_accessible_object(db, object_id, user)` in `app/routers/objects.py` — in 2.1 eingeführt,
  von 2.2 Tasks 5.2/5.3 verwendet. Story 2.3 nutzt **denselben Namen** — KEIN `_load_object`.
- Migrationstand: `0016` (nach 2.1 `0015` + 2.2 `0016`) muss applied sein.

### Keine eigene Migration in Story 2.3

Story 2.3 legt **selbst keine Migration an**. Voraussetzung aus Task 0: `alembic current` zeigt
mindestens `0016` (= Migrationen 0015 aus Story 2.1 + 0016 aus Story 2.2 sind applied).

Die Tabelle `schadensfaelle` mit allen benötigten Spalten existiert bereits seit Migration
`0010_steckbrief_core.py` — Story 2.3 ergänzt nur ORM-Relationships, keine DB-Schema-Änderungen.

Spalten in `schadensfaelle` (seit 0010):
- `id` (UUID PK), `policy_id` (FK → policen), `unit_id` (FK → units, nullable)
- `description` (Text), `amount` (Numeric 12,2), `occurred_at` (Date), `status` (String)
- `created_at`, `updated_at` (Timestamps)

### Feldname-Mapping (Epic vs. ORM)

Das Epic verwendet zwei abweichende Feldbezeichnungen — der Developer muss immer den ORM-Namen nutzen:

| Epic-Begriff | ORM-Feldname | Tabelle |
|---|---|---|
| `police_id` | `policy_id` | schadensfaelle |
| `estimated_sum` | `amount` | schadensfaelle |

Das HTML-Formular-Feld heißt `estimated_sum` (User-facing), der Server mapped es auf `Decimal`
und übergibt es als `amount` an `create_schadensfall`. Kein Rename in der DB nötig.

### Unit-Modell-Standort

`Unit` ist in `app/models/object.py`, NICHT in einer eigenen Datei. Importpfad:
```python
from app.models.object import Unit
```
Das `Object`-Model hat eine `units`-Relationship (line 102, `cascade="all, delete-orphan"`).
Im Route-Handler kann `obj.units` direkt genutzt werden wenn der ORM-Context aktiv ist.

### Write-Gate Entity-Type für Schadensfall

Mapping `"schadensfaelle"` → `"schaden"` ist bereits im Write-Gate verdrahtet
(`app/services/steckbrief_write_gate.py` — `_TABLE_TO_ENTITY_TYPE` + `_ENTITY_TYPE_TO_CLASS`).
Keine Code-Anpassung am Write-Gate nötig.

### TemplateResponse-Signatur (Starlette ≥ 0.21)

IMMER: `templates.TemplateResponse(request, "template.html", {...})` — Request als ERSTES Argument.
NICHT: `templates.TemplateResponse("template.html", {"request": request, ...})` → TypeError.

### HTMX-Target-Konvention

Der Route-Handler gibt das Fragment `_obj_versicherungen.html` mit dem Wrapper-Div zurück.
Das HTMX-Target in allen Formularen dieser Sektion ist `[data-section='versicherungen']` mit
`hx-swap="outerHTML"` (konsistent mit Stories 2.1/2.2).

### Schadensfall-Status beim Erstellen

Das Modell hat ein `status`-Feld (String, nullable). Beim Erstellen via Story 2.3 wird kein
expliziter Status gesetzt — `status=None` ist der initiale Zustand, das Template zeigt `"offen"` als
Fallback. Ein Status-Workflow (Abschluss, Zahlung, etc.) ist für spätere Stories vorgesehen.

### `_parse_date`-Helper

Wenn Story 2.1 diesen Helper bereits in `objects.py` definiert hat, einfach wiederverwenden.
Falls nicht (oder wegen Namenskonflikt), direkt im neuen Service nutzen:
```python
from datetime import date

def _parse_date(val: str | None) -> date | None:
    if not val or not val.strip():
        return None
    try:
        return date.fromisoformat(val.strip())
    except ValueError:
        raise HTTPException(422, detail=f"Ungültiges Datum: {val!r}")
```

### Schadensquote (Story 2.7)

Story 2.7 (Versicherer-Listenansicht) aggregiert `Schadensfall.amount` als `estimated_sum` in der
Formel `Schadensquote = Summe(amount) / Gesamtpräemie`. Das ist der Downstream-Use-Case für diese Story.
Die Datenbasis muss stimmen — kein `status`-Filter auf "offen" in Story 2.7 spezifiziert, alle
`amount`-Werte werden summiert. Sicherstellen, dass negative Werte via AC3 korrekt geblockt werden.

### Aus Stories 2.1/2.2 gelernt (verhindert Wiederholung)

- **`db.commit()` im Router**, nicht im Service.
- **`registries.py` und `_obj_versicherungen.html` nicht neu anlegen** — nur erweitern.
- **Write-Gate Coverage**: Kein direktes `schaden.field = value` außerhalb Row-Creation.
- **`policy.object_id != obj.id`-Check**: Verhindert Cross-Object-Manipulation beim Policy-Lookup.
- **Pro-Policy ID-Namespacing** (aus 2.2): Nicht nötig in 2.3, da das Schadensfall-Formular global ist
  (eine Form für das gesamte Objekt, nicht eine pro Police).
- **`accessible_object_ids`-Gate als ERSTER Aufruf** (Retro-Finding Epic 1 / Story 1.8, AC5):
  `_load_accessible_object(db, object_id, user)` bevor irgendein Policy-/Unit-Lookup passiert,
  sonst leaken wir 404-vs-403-Signal über transitive FK-Joins.

### Nicht in Story 2.3 (Deferred)

- **Schadensfall löschen / bearbeiten** — kein AC für Edit/Delete; kein `DELETE`-Route nötig.
- **Status-Workflow** (offen → abgeschlossen / ausgezahlt) — kommt in späteren Stories.
- **SEPA-Mandat für Schadenszahlung** — nicht im Scope.
- **Schadensquoten-Aggregation** — ist Aufgabe von Story 2.7, nicht 2.3.

## Dev Agent Record

_Wird vom Dev-Agenten nach Implementierung ausgefüllt._

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
