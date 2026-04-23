# Story 1.6: Technik-Sektion mit Inline-Edit

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter mit `objects:edit`,
ich moechte die technischen Daten eines Objekts (Absperrpunkte, Heizungs-Steckbrief, Objekt-Historie) direkt auf der Detailseite bearbeiten,
damit ich Wissen aus Begehungen sofort dokumentieren kann.

## Acceptance Criteria

**AC1 — Technik-Sektion rendert mit drei Sub-Bloecken + Edit-Buttons (fuer `objects:edit`)**
**Given** ich oeffne `/objects/{id}` als User mit `objects:edit`
**When** die Technik-Sektion rendert
**Then** sehe ich drei Sub-Bloecke: (a) **Absperrpunkte** mit je einem Standort-Textfeld fuer Wasser / Strom / Gas (`shutoff_water_location`, `shutoff_electricity_location`, `shutoff_gas_location`), (b) **Heizung** mit Typ / Baujahr / Wartungsfirma / Hotline (`heating_type`, `year_heating`, `heating_company`, `heating_hotline`), (c) **Objekt-Historie** mit Baujahr / Dach / Elektrik (`year_built`, `year_roof`, `year_electrics`)
**And** jedes Feld zeigt seinen aktuellen Wert oder einen `—`-Placeholder, eine Provenance-Pill (`provenance_pill` Global, gleiche Pill-Farben wie Stammdaten/Finanzen) und — nur fuer User mit `objects:edit` — einen **Edit-Button**
**And** Zugangscodes (`entry_code_*`) sind in dieser Story **NICHT** sichtbar oder editierbar (Scope Story 1.7 — dort kommen UI + Fernet-Encryption gemeinsam)

**AC2 — Edit → Save schreibt via Write-Gate + Provenance-Pill + Audit-Eintrag**
**Given** ich klicke auf "Edit" fuer `year_roof`, gebe `2021` ein und poste "Speichern"
**When** der HTMX-Request durchlaeuft
**Then** laeuft der Write ausschliesslich durch `write_field_human(entity=obj, field="year_roof", value=2021, source="user_edit", user=current_user)` (kein direktes `obj.year_roof = ...`)
**And** das Fragment-Response tauscht den Feld-Card mit dem neuen Wert + Pill `Manuell` (`data-source="user_edit"`) aus
**And** es existiert genau **ein** neuer `FieldProvenance`-Eintrag mit `entity_type="object"`, `field_name="year_roof"`, `source="user_edit"`, `user_id=<aktueller User>`, `value_snapshot={"old": <prev>, "new": 2021}`
**And** es existiert ein neuer `AuditLog`-Eintrag mit `action="object_field_updated"`, `entity_type="object"`, `entity_id=<obj.id>`, und `details_json.field == "year_roof"` (die Action ist in `KNOWN_AUDIT_ACTIONS` bereits registriert — kein Audit-Katalog-Touch noetig)

**AC3 — Ohne `objects:edit` sind Edit-Buttons unsichtbar UND der Server blockt den POST mit 403**
**Given** ich bin eingeloggt mit `objects:view`, aber **ohne** `objects:edit`
**When** ich die Technik-Sektion sehe
**Then** ist die Sektion sichtbar, aber **kein** Edit-Button wird gerendert (Template-Gate via `has_permission(user, "objects:edit")`)
**And** ein direkter `POST /objects/{id}/technik/field` mit `field_name=year_roof` bekommt **HTTP 403** (serverseitig via `Depends(require_permission("objects:edit"))`), kein DB-Write, kein Audit-Eintrag

**AC4 — Validierungsfehler → Fragment zeigt Fehler, kein Write**
**Given** ich klicke auf "Edit" fuer `year_roof` und poste einen invaliden Wert (`value="abc"` oder Jahr ausserhalb `[1800, current_year+1]`; leer = bewusste Loeschung → NULL, s. AC6)
**When** die Form submitted
**Then** liefert der Server das Edit-Fragment mit einer sichtbaren Fehlermeldung (`data-error="true"` + deutsche Meldung unter dem Input) zurueck
**And** kein `FieldProvenance`- und kein `AuditLog`-Eintrag wurde angelegt
**And** die DB-Spalte bleibt unveraendert

**AC5 — Pflegegrad-Cache invalidiert bei erfolgreichem Write**
**Given** ein Objekt mit `pflegegrad_score_cached=72` und `pflegegrad_score_updated_at=2026-04-20T10:00Z`
**When** ein erfolgreicher Technik-Edit via Write-Gate laeuft (z.B. `year_roof=2021`)
**Then** ist `pflegegrad_score_cached=None` und `pflegegrad_score_updated_at=None` — der Cache-Reset passiert **automatisch** im Write-Gate via `_invalidate_pflegegrad(entity)` fuer alle Object-Entities; keine Zusatz-Logik im Router

**AC6 — Empty-String setzt Feld auf NULL (bewusste Loeschung)**
**Given** ein Objekt mit `year_roof=2021` und `FieldProvenance(source="user_edit")`
**When** ich Edit auf `year_roof` klicke, den Input leere und "Speichern" poste
**Then** schreibt `write_field_human(..., value=None, source="user_edit", user=...)` das Feld zurueck auf `NULL`
**And** die neue Provenance-Row hat `value_snapshot={"old": 2021, "new": None}` und `source="user_edit"`
**And** das Fragment zeigt den `—`-Placeholder + Pill `Manuell`
**Kontext**: In v1 gibt es keine echten Pflichtfelder in Cluster 4 — alle Technik-Felder sind optional (siehe Feld-Katalog). Das "Pflichtfeld-Check" aus AC4 greift deshalb **nur** bei Type-Validierungsfehlern (ungueltige Jahreszahl, Text ueber `MAX_LEN`), nicht bei leerem Input.

**AC7 — Tests + Regressionslauf gruen**
**Given** die neuen Dateien (Migration 0013, Object-Model-Erweiterung, Router-Endpoints, Templates, Service-Validator)
**When** `pytest -x` laeuft
**Then** sind alle neuen Tests gruen und der bestehende Regressionslauf (>=405 Tests, Stand nach Story 1.5) bleibt vollstaendig gruen

## Tasks / Subtasks

- [x] **Task 1 — Migration 0013 `steckbrief_cluster4_fields`** (AC1, AC5)
  - [x] 1.1 `ls migrations/versions/` zur Bestaetigung, dass `0012_steckbrief_finance_mirror_fields.py` die neueste Revision ist (Memory: `feedback_migrations_check_existing` — NICHT auf CLAUDE.md vertrauen). `down_revision = "0012"`, `revision = "0013"`.
  - [x] 1.2 Neue Datei `migrations/versions/0013_steckbrief_cluster4_fields.py`. **Per Hand schreiben**, NIE `alembic revision --autogenerate` (project-context.md: Postgres-JSONB/UUID unzuverlaessig gediffed).
  - [x] 1.3 In `upgrade()` 8 neue Spalten auf Tabelle `objects` anlegen (alle nullable, keine Defaults):
    ```python
    # Absperrpunkte (Standortbeschreibung als Freitext)
    op.add_column("objects", sa.Column("shutoff_water_location", sa.String(), nullable=True))
    op.add_column("objects", sa.Column("shutoff_electricity_location", sa.String(), nullable=True))
    op.add_column("objects", sa.Column("shutoff_gas_location", sa.String(), nullable=True))
    # Heizungs-Steckbrief
    op.add_column("objects", sa.Column("heating_type", sa.String(), nullable=True))
    op.add_column("objects", sa.Column("year_heating", sa.Integer(), nullable=True))
    op.add_column("objects", sa.Column("heating_company", sa.String(), nullable=True))
    op.add_column("objects", sa.Column("heating_hotline", sa.String(), nullable=True))
    # Objekt-Historie (year_built + year_roof existieren schon aus 0010)
    op.add_column("objects", sa.Column("year_electrics", sa.Integer(), nullable=True))
    # Fassade bleibt v1.1 (nicht im PRD-Kern)
    ```
  - [x] 1.4 `downgrade()` spiegelt mit `op.drop_column` in umgekehrter Reihenfolge.
  - [x] 1.5 **KEINE neuen Indexes** — alle neuen Felder sind optional und werden nicht fuer Portfolio-Sortierung genutzt. Pro unnoetigem Index Speicher sparen, zusaetzlich haelt das die 0013 klein (ein Zweck pro Migration).

- [x] **Task 2 — ORM `Object`-Model erweitern** (AC1)
  - [x] 2.1 In `app/models/object.py` nach dem `year_roof`-Feld (Zeile 37) die neuen Spalten als typed `Mapped[...]` ergaenzen. Einhalten der PEP-604-Union-Syntax (`str | None` statt `Optional[str]`) und SQLAlchemy-2.0-Typed-ORM (project-context.md §Language-Specific Rules).
    ```python
    # Absperrpunkte
    shutoff_water_location: Mapped[str | None] = mapped_column(String, nullable=True)
    shutoff_electricity_location: Mapped[str | None] = mapped_column(String, nullable=True)
    shutoff_gas_location: Mapped[str | None] = mapped_column(String, nullable=True)
    # Heizung
    heating_type: Mapped[str | None] = mapped_column(String, nullable=True)
    year_heating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heating_company: Mapped[str | None] = mapped_column(String, nullable=True)
    heating_hotline: Mapped[str | None] = mapped_column(String, nullable=True)
    # Objekt-Historie
    year_electrics: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ```
  - [x] 2.2 Plazierung: neue Felder **oberhalb** der `entry_code_*`-Felder — Gruppierung nach Domaene (Bau/Technik vor Zugangscodes vor Finanzen). Nur Append + Umsortierung, keine Mutation bestehender Spalten.

- [x] **Task 3 — Validator + Feld-Registry in `app/services/steckbrief.py`** (AC1, AC4, AC6)
  - [x] 3.1 Neue Konstante `TECHNIK_FIELDS` als sortierte Tupel-Registry pro Sub-Block. Wird sowohl im Router als auch im Template konsumiert — Single Source of Truth:
    ```python
    # In app/services/steckbrief.py — ganz am Ende der Datei ergaenzen.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class TechnikField:
        key: str          # Spalten-Name auf Object
        label: str        # UI-Label (Deutsch)
        kind: str         # "int_year" | "text"
        max_len: int = 500

    TECHNIK_ABSPERRPUNKTE: tuple[TechnikField, ...] = (
        TechnikField("shutoff_water_location", "Wasser-Absperrung", "text"),
        TechnikField("shutoff_electricity_location", "Strom-Absperrung", "text"),
        TechnikField("shutoff_gas_location", "Gas-Absperrung", "text"),
    )
    TECHNIK_HEIZUNG: tuple[TechnikField, ...] = (
        TechnikField("heating_type", "Heizungs-Typ", "text"),
        TechnikField("year_heating", "Baujahr Heizung", "int_year"),
        TechnikField("heating_company", "Wartungsfirma", "text"),
        TechnikField("heating_hotline", "Stoerungs-Hotline", "text"),
    )
    TECHNIK_HISTORIE: tuple[TechnikField, ...] = (
        TechnikField("year_built", "Baujahr Gebaeude", "int_year"),
        TechnikField("year_roof", "Jahr letzte Dach-Sanierung", "int_year"),
        TechnikField("year_electrics", "Jahr Elektrik-Check", "int_year"),
    )
    TECHNIK_FIELDS: tuple[TechnikField, ...] = (
        *TECHNIK_ABSPERRPUNKTE,
        *TECHNIK_HEIZUNG,
        *TECHNIK_HISTORIE,
    )
    TECHNIK_FIELD_KEYS: frozenset[str] = frozenset(f.key for f in TECHNIK_FIELDS)
    ```
    **Nicht aufnehmen**: `entry_code_main_door`, `entry_code_garage`, `entry_code_technical_room` (Encrypted-Scope Story 1.7 — UI wird dort gemeinsam mit Fernet ausgerollt).
  - [x] 3.2 Neue Funktion `parse_technik_value(field_key: str, raw: str) -> tuple[Any | None, str | None]`. Rueckgabe: `(parsed_value, error_msg)` — genau einer von beiden ist `None`.
    ```python
    from datetime import datetime

    _TECHNIK_LOOKUP: dict[str, TechnikField] = {f.key: f for f in TECHNIK_FIELDS}

    def parse_technik_value(field_key: str, raw: str) -> tuple[Any | None, str | None]:
        """Validiert und parst User-Input fuer Technik-Felder.

        - Leerer Input → (None, None): bewusste Loeschung (AC6).
        - `int_year`: Integer zwischen 1800 und (aktuelles Jahr + 1). Alles andere → Fehler.
        - `text`: Laenge <= MAX_LEN. Nur leading/trailing whitespace strippen.

        Unbekannter field_key → ValueError (reiner Programmier-Guard, nie User-sichtbar).
        """
        field = _TECHNIK_LOOKUP.get(field_key)
        if field is None:
            raise ValueError(f"Unbekanntes Technik-Feld: {field_key!r}")
        stripped = (raw or "").strip()
        if stripped == "":
            return None, None  # Loeschung erlaubt
        if field.kind == "int_year":
            try:
                year = int(stripped)
            except ValueError:
                return None, "Bitte eine ganze Zahl (Jahr) eingeben."
            current_year = datetime.now().year
            if not (1800 <= year <= current_year + 1):
                return None, f"Jahr muss zwischen 1800 und {current_year + 1} liegen."
            return year, None
        if field.kind == "text":
            if len(stripped) > field.max_len:
                return None, f"Maximal {field.max_len} Zeichen erlaubt."
            return stripped, None
        raise ValueError(f"Unbekannter Feld-Typ: {field.kind!r}")
    ```
  - [x] 3.3 **Warum ein eigener Service statt Pydantic-Model?** Jedes Feld hat eigene Validierungsregeln (Jahr-Range vs. Text-Length), und ein Pydantic-Schema pro Feld waere Overkill. Die `parse_technik_value`-Funktion bleibt kompakt, ist trivial testbar, und der Router delegiert komplett an sie — damit ist die Validierung nicht im Router dupliziert. Muster konsistent zur existierenden `build_sparkline_svg` in derselben Datei (Business-Logik im Service, nicht im Router).

- [x] **Task 4 — Router `app/routers/objects.py` — Read-Context erweitern** (AC1)
  - [x] 4.1 Imports ergaenzen am Modulanfang:
    ```python
    from app.services.steckbrief import (
        ...,  # bestehende Imports
        TECHNIK_FIELDS,
        TECHNIK_ABSPERRPUNKTE,
        TECHNIK_HEIZUNG,
        TECHNIK_HISTORIE,
        TECHNIK_FIELD_KEYS,
        parse_technik_value,
    )
    ```
  - [x] 4.2 Im `object_detail`-Handler nach dem Finanzen-Block einen Technik-Block ergaenzen. Der gleiche Provenance-Map-Aufruf wie fuer Stammdaten + Finanzen:
    ```python
    tech_prov_map = get_provenance_map(
        db, "object", detail.obj.id,
        tuple(f.key for f in TECHNIK_FIELDS),
    )

    def _build_section(fields: tuple[TechnikField, ...]) -> list[dict]:
        return [
            {
                "key": f.key,
                "label": f.label,
                "kind": f.kind,
                "value": getattr(detail.obj, f.key),
                "prov": tech_prov_map.get(f.key),
            }
            for f in fields
        ]

    tech_absperrpunkte = _build_section(TECHNIK_ABSPERRPUNKTE)
    tech_heizung = _build_section(TECHNIK_HEIZUNG)
    tech_historie = _build_section(TECHNIK_HISTORIE)
    ```
  - [x] 4.3 Diese drei Listen zusaetzlich ans Template uebergeben (nach `sparkline_svg`):
    ```python
    "tech_absperrpunkte": tech_absperrpunkte,
    "tech_heizung": tech_heizung,
    "tech_historie": tech_historie,
    ```

- [x] **Task 5 — Router `app/routers/objects.py` — Edit-/View-/Save-Endpoints** (AC2, AC3, AC4, AC6)
  - [x] 5.1 Drei neue Endpoints am Ende des Routers ergaenzen. **Alle drei** haengen an `Depends(require_permission("objects:edit"))` — AC3 verlangt, dass auch das **Laden** des Edit-Formulars (nicht nur das Speichern) fuer Viewer 403 wirft. Andernfalls koennte ein Viewer mit direktem `curl` das Form-Fragment sehen.
    ```python
    from fastapi import Form

    @router.get(
        "/{object_id}/technik/edit",
        response_class=HTMLResponse,
    )
    async def technik_field_edit(
        object_id: uuid.UUID,
        request: Request,
        field: str,
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        if field not in TECHNIK_FIELD_KEYS:
            raise HTTPException(400, "Unbekanntes Technik-Feld")
        accessible = accessible_object_ids(db, user)
        detail = get_object_detail(db, object_id, accessible_ids=accessible)
        if detail is None:
            raise HTTPException(404, "Objekt nicht gefunden")
        return templates.TemplateResponse(
            request,
            "_obj_technik_field_edit.html",
            {
                "obj": detail.obj,
                "field": _technik_field_ctx(detail.obj, field, db),
                "user": user,
                "error": None,
            },
        )

    @router.get(
        "/{object_id}/technik/view",
        response_class=HTMLResponse,
    )
    async def technik_field_view(
        object_id: uuid.UUID,
        request: Request,
        field: str,
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        """Cancel-Button rendert den View-Zustand wieder — gleicher Permission-
        Check wie Edit: Viewer haben ueberhaupt keinen Edit-/Cancel-Loop."""
        if field not in TECHNIK_FIELD_KEYS:
            raise HTTPException(400, "Unbekanntes Technik-Feld")
        accessible = accessible_object_ids(db, user)
        detail = get_object_detail(db, object_id, accessible_ids=accessible)
        if detail is None:
            raise HTTPException(404, "Objekt nicht gefunden")
        return templates.TemplateResponse(
            request,
            "_obj_technik_field_view.html",
            {
                "obj": detail.obj,
                "field": _technik_field_ctx(detail.obj, field, db),
                "user": user,
            },
        )

    @router.post(
        "/{object_id}/technik/field",
        response_class=HTMLResponse,
    )
    async def technik_field_save(
        object_id: uuid.UUID,
        request: Request,
        field_name: str = Form(...),
        value: str = Form(""),
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        if field_name not in TECHNIK_FIELD_KEYS:
            raise HTTPException(400, "Unbekanntes Technik-Feld")
        accessible = accessible_object_ids(db, user)
        detail = get_object_detail(db, object_id, accessible_ids=accessible)
        if detail is None:
            raise HTTPException(404, "Objekt nicht gefunden")

        parsed, error = parse_technik_value(field_name, value)
        if error is not None:
            # Form mit Fehler rendern — kein Write, kein Audit.
            return templates.TemplateResponse(
                request,
                "_obj_technik_field_edit.html",
                {
                    "obj": detail.obj,
                    "field": _technik_field_ctx(detail.obj, field_name, db),
                    "user": user,
                    "error": error,
                    "submitted_value": value,
                },
                status_code=422,
            )

        write_field_human(
            db,
            entity=detail.obj,
            field=field_name,
            value=parsed,
            source="user_edit",
            user=user,
            request=request,
        )
        db.commit()

        # Provenance neu laden — die Write-Gate-Row ist jetzt da, wir brauchen
        # den frischen Pill-State fuer das Render-Fragment.
        return templates.TemplateResponse(
            request,
            "_obj_technik_field_view.html",
            {
                "obj": detail.obj,
                "field": _technik_field_ctx(detail.obj, field_name, db),
                "user": user,
            },
        )


    def _technik_field_ctx(obj: Object, field_key: str, db: Session) -> dict:
        """Baut das Render-Dict fuer ein einzelnes Technik-Feld-Fragment.

        Eigener Helper, damit GET edit / GET view / POST save alle dasselbe
        Shape nutzen. Die Provenance-Row muss frisch aus der DB kommen (nach
        Save), deshalb wird sie hier on-demand geladen.
        """
        lookup = {f.key: f for f in TECHNIK_FIELDS}
        tf = lookup[field_key]
        prov = get_provenance_map(db, "object", obj.id, (field_key,))
        return {
            "key": tf.key,
            "label": tf.label,
            "kind": tf.kind,
            "value": getattr(obj, field_key),
            "prov": prov.get(field_key),
        }
    ```
  - [x] 5.2 **Kein `HX-Request`-Branch noetig** — die Endpoints liefern **nur** Fragmente aus. Wer das POST direkt via Form-Submit aufruft (kein HTMX), bekommt trotzdem ein Fragment zurueck; das ist im Plattform-Kontext OK, weil ausserhalb von HTMX kein realer User das Endpoint trifft (Reine API-Nutzung ist nicht v1-Scope). Vgl. `app/templates/_extraction_block.html`, das exakt demselben Muster folgt.
  - [x] 5.3 **Write-Gate nicht umgehen**: `write_field_human` macht intern `setattr` + `flag_modified` + Provenance-Row + Audit-Eintrag + `_invalidate_pflegegrad` — alles atomar in einer Transaktion (AC5). Der Router macht **nur** `db.commit()`. Kein `obj.<field> = ...` im Router — sonst schlaegt `tests/test_write_gate_coverage.py` an (Memory `feedback_migrations_check_existing` + project-context §Critical Don't-Miss Rules).
  - [x] 5.4 **Kein Flash/Redirect**: HTMX-Swap passiert direkt auf das Fragment. Der Erfolgszustand ist das frisch gerenderte View-Fragment mit neuer Pill — kein Toast, kein Inline-"Gespeichert"-Message (UX-Konsistenz zu M5/Case-Detail, wo Saves ebenfalls stumm per Fragment-Swap bestaetigt werden).

- [x] **Task 6 — Template `app/templates/_obj_technik.html` (neu)** (AC1, AC3)
  - [x] 6.1 Neue Datei im gleichen Stil wie `_obj_stammdaten.html` + `_obj_finanzen.html`. Drei Sub-Karten in einer `<section>`:
    ```jinja
    {# Technik-Sektion (Story 1.6):
       - Absperrpunkte (3 Text-Felder): Wasser / Strom / Gas mit Standortbeschreibung
       - Heizung (4 Felder): Typ / Baujahr / Wartungsfirma / Hotline
       - Objekt-Historie (3 Jahr-Felder): Baujahr / Dach / Elektrik
       Alle Felder via Inline-Edit — Edit-Button nur wenn objects:edit.
       Zugangscodes bleiben Story 1.7 (UI + Fernet gemeinsam). #}

    <section class="rounded-lg bg-white border border-slate-200 p-6 mb-6"
             data-section="technik">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-slate-900">Technik</h2>
      </div>

      <div class="mb-6">
        <h3 class="text-sm font-semibold text-slate-800 mb-3">Absperrpunkte</h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-4">
          {% for field in tech_absperrpunkte %}
            {% include "_obj_technik_field_view.html" %}
          {% endfor %}
        </div>
      </div>

      <div class="mb-6">
        <h3 class="text-sm font-semibold text-slate-800 mb-3">Heizung</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
          {% for field in tech_heizung %}
            {% include "_obj_technik_field_view.html" %}
          {% endfor %}
        </div>
      </div>

      <div>
        <h3 class="text-sm font-semibold text-slate-800 mb-3">Objekt-Historie</h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-4">
          {% for field in tech_historie %}
            {% include "_obj_technik_field_view.html" %}
          {% endfor %}
        </div>
      </div>
    </section>
    ```

- [x] **Task 7 — Template `app/templates/_obj_technik_field_view.html` (neu)** (AC1, AC2, AC3)
  - [x] 7.1 Einzelfeld-Fragment im View-Zustand. Container-ID ist **das** HTMX-Target fuer Edit/Save-Swaps:
    ```jinja
    {# View-Fragment fuer ein einzelnes Technik-Feld.
       Container-ID = `field-<key>`, sodass Edit-Fragments via hx-swap="outerHTML"
       genau diesen Block ersetzen. #}
    {% set pill = provenance_pill(field.prov) %}
    <div id="field-{{ field.key }}" class="min-w-0">
      <div class="text-xs uppercase tracking-wider text-slate-500 mb-1">{{ field.label }}</div>
      <div class="flex items-center justify-between gap-3">
        <div class="text-sm text-slate-900 truncate">
          {% if field.value is not none and field.value != "" %}
            {{ field.value }}
          {% else %}
            <span class="text-slate-400">&mdash;</span>
          {% endif %}
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <span data-source="{{ pill.source }}"
                data-field="{{ field.key }}"
                title="{{ pill.tooltip }}"
                class="inline-flex items-center text-[11px] px-2 py-0.5 rounded {{ pill.color_class }}">
            {{ pill.label }}
          </span>
          {% if has_permission(user, "objects:edit") %}
            <button type="button"
                    data-edit-field="{{ field.key }}"
                    hx-get="/objects/{{ obj.id }}/technik/edit?field={{ field.key }}"
                    hx-target="#field-{{ field.key }}"
                    hx-swap="outerHTML"
                    class="text-xs text-sky-600 hover:text-sky-900">Edit</button>
          {% endif %}
        </div>
      </div>
    </div>
    ```

- [x] **Task 8 — Template `app/templates/_obj_technik_field_edit.html` (neu)** (AC2, AC4, AC6)
  - [x] 8.1 Inline-Edit-Form-Fragment. Rendert auch den Fehler-Zweig (Context-Variable `error`):
    ```jinja
    {# Edit-Fragment fuer ein einzelnes Technik-Feld.
       Behaelt die Container-ID bei (damit der Cancel-/Save-Swap wieder auf
       denselben Ziel-Knoten trifft). `submitted_value` kommt nur beim
       Validierungsfehler zurueck — sonst faellt die Form auf den
       DB-Wert zurueck. #}
    <div id="field-{{ field.key }}" class="min-w-0"
         data-edit-field="{{ field.key }}"
         data-error="{{ 'true' if error else 'false' }}">
      <form hx-post="/objects/{{ obj.id }}/technik/field"
            hx-target="#field-{{ field.key }}"
            hx-swap="outerHTML"
            class="flex flex-col gap-1">
        <label class="text-xs uppercase tracking-wider text-slate-500"
               for="input-{{ field.key }}">{{ field.label }}</label>
        <input type="hidden" name="field_name" value="{{ field.key }}">
        {% set current_value =
           submitted_value if submitted_value is defined and submitted_value is not none
           else (field.value if field.value is not none else "") %}
        <input id="input-{{ field.key }}"
               name="value"
               type="{{ 'number' if field.kind == 'int_year' else 'text' }}"
               value="{{ current_value }}"
               {% if field.kind == 'int_year' %}min="1800" max="{{ 3000 }}"{% endif %}
               class="block w-full rounded border {{ 'border-rose-300' if error else 'border-slate-300' }} px-2 py-1 text-sm">
        {% if error %}
          <p class="text-xs text-rose-600 mt-0.5">{{ error }}</p>
        {% endif %}
        <div class="flex items-center gap-2 mt-1">
          <button type="submit"
                  class="text-xs px-2 py-0.5 rounded bg-sky-600 text-white hover:bg-sky-700">
            Speichern
          </button>
          <button type="button"
                  hx-get="/objects/{{ obj.id }}/technik/view?field={{ field.key }}"
                  hx-target="#field-{{ field.key }}"
                  hx-swap="outerHTML"
                  class="text-xs text-slate-500 hover:text-slate-900">
            Abbrechen
          </button>
        </div>
      </form>
    </div>
    ```
  - [x] 8.2 **`max="3000"` ist bewusst**: der HTML5-`max`-Browser-Check ist reine UX-Hilfe — die harte Regel (`<= current_year + 1`) sitzt im Server-Validator (`parse_technik_value`). Ohne HTML5-`max` waere das Feld frei; mit einem dynamisch gesetzten `current_year+1` wuerde das Template jedes Jahr neue Pseudo-Edge-Cases erzeugen. "3000" ist eine sichere Obergrenze fuer Browser-Widgets und dokumentiert die serverseitige Begrenzung klar.

- [x] **Task 9 — `app/templates/object_detail.html` aktualisieren** (AC1)
  - [x] 9.1 Kommentar aktualisieren. Aktuell:
    ```
    {# Weitere Sektionen (Technik/Versicherungen/Historie/Menschen/Review-Queue)
       folgen mit Stories 1.6-3.6 — nicht vorbauen. #}
    ```
    → `Technik` aus der Aufzaehlung streichen, Story-Range auf `1.7-3.6`:
    ```
    {# Weitere Sektionen (Versicherungen/Historie/Menschen/Review-Queue)
       folgen mit Stories 1.7-3.6 — nicht vorbauen. #}
    ```
  - [x] 9.2 `{% include "_obj_technik.html" %}` nach dem Finanzen-Include einfuegen:
    ```html
    {% include "_obj_stammdaten.html" %}
    {% include "_obj_finanzen.html" %}
    {% include "_obj_technik.html" %}
    ```

- [x] **Task 10 — Unit-Tests** (AC4, AC5, AC6, AC7)
  - [x] 10.1 Neue Datei `tests/test_technik_parser_unit.py` — reine Validator-Tests, kein TestClient:
    - `test_parse_empty_returns_none_no_error` — `parse_technik_value("year_roof", "")` → `(None, None)` (bewusste Loeschung, AC6).
    - `test_parse_year_valid` — `parse_technik_value("year_roof", "2021")` → `(2021, None)`.
    - `test_parse_year_too_low` — `parse_technik_value("year_built", "1700")` → `(None, "Jahr muss zwischen 1800 und ...")` (Substring-Match).
    - `test_parse_year_too_high` — `parse_technik_value("year_heating", "3000")` → `(None, "Jahr muss zwischen 1800 und ...")`.
    - `test_parse_year_non_numeric` — `parse_technik_value("year_built", "abc")` → `(None, "Bitte eine ganze Zahl (Jahr) eingeben.")`.
    - `test_parse_year_whitespace_trimmed` — `parse_technik_value("year_built", "  2020  ")` → `(2020, None)`.
    - `test_parse_text_valid` — `parse_technik_value("heating_type", "Viessmann")` → `("Viessmann", None)`.
    - `test_parse_text_too_long` — `parse_technik_value("shutoff_water_location", "x" * 501)` → `(None, "Maximal 500 Zeichen erlaubt.")`.
    - `test_parse_text_whitespace_trimmed` — `"  Keller  "` → `("Keller", None)`.
    - `test_parse_unknown_field_raises` — `parse_technik_value("entry_code_main_door", "1234")` raises `ValueError` (nicht in TECHNIK_FIELD_KEYS → gar nicht editierbar ueber diese API; Encrypted-Felder bleiben Story 1.7).

- [x] **Task 11 — Route-Smoke-Tests** (AC1, AC2, AC3, AC4, AC5, AC6)
  - [x] 11.1 Neue Datei `tests/test_technik_routes_smoke.py`. Wiederverwendung der `make_finanzen_object`-Fixture nicht sinnvoll (die haengt in `test_finanzen_routes_smoke.py`); eigene `make_object`-Fixture im File oder inline-Helper.
  - [x] 11.2 Fixture `viewer_client` fuer AC3: User mit `objects:view`, aber ohne `objects:edit`:
    ```python
    @pytest.fixture
    def viewer_client(db):
        user = User(
            id=uuid.uuid4(),
            google_sub="google-sub-viewer-technik",
            email="viewer-technik@dbshome.de",
            name="Viewer",
            permissions_extra=["objects:view"],  # KEIN objects:edit
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        def override_db(): yield db
        def override_user(): return user
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            yield c
        app.dependency_overrides.clear()
    ```
    (Exakt das gleiche Muster wie `steckbrief_admin_client` in `conftest.py:200`, aber mit reduziertem Permission-Set.)
  - [x] 11.3 Tests:
    - **AC1** `test_technik_section_rendered_with_all_fields_and_edit_buttons_for_editor` — Objekt anlegen, `GET /objects/{id}` als `steckbrief_admin_client` → 200, Response enthaelt `data-section="technik"`, alle 10 `data-field="..."`-Attribute, 10 `data-edit-field="..."`-Buttons, **keine** `entry_code_*`-Referenzen im HTML (Scope-Boundary zu Story 1.7).
    - **AC1** `test_technik_section_labels_in_german` — Pruefe deutsche Labels "Absperrpunkte", "Heizung", "Objekt-Historie", "Wartungsfirma" etc.
    - **AC2 + AC5** `test_technik_field_save_writes_via_gate_and_invalidates_pflegegrad` —
        ```python
        obj.pflegegrad_score_cached = 72  # writegate: allow
        obj.pflegegrad_score_updated_at = datetime.now(timezone.utc)  # writegate: allow
        db.commit()
        resp = client.post(f"/objects/{obj.id}/technik/field",
                           data={"field_name": "year_roof", "value": "2021"})
        assert resp.status_code == 200
        assert 'data-source="user_edit"' in resp.text
        assert 'id="field-year_roof"' in resp.text
        assert "2021" in resp.text
        db.expire_all()
        refreshed = db.get(Object, obj.id)
        assert refreshed.year_roof == 2021
        assert refreshed.pflegegrad_score_cached is None  # AC5 Invalidate
        assert refreshed.pflegegrad_score_updated_at is None
        # Genau eine FieldProvenance-Row, source user_edit
        prov = db.query(FieldProvenance).filter_by(
            entity_type="object", entity_id=obj.id, field_name="year_roof"
        ).all()
        assert len(prov) == 1 and prov[0].source == "user_edit"
        # Audit-Eintrag
        audit_rows = db.query(AuditLog).filter_by(
            action="object_field_updated", entity_id=obj.id
        ).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].details_json["field"] == "year_roof"
        ```
    - **AC2** `test_technik_field_save_text_field` — `heating_type="Viessmann"` Happy-Path.
    - **AC3** `test_technik_edit_button_not_rendered_for_viewer` — `viewer_client.get("/objects/{id}")` → 200, Response enthaelt `data-section="technik"`, aber **keine** `data-edit-field`-Buttons.
    - **AC3** `test_technik_post_returns_403_for_viewer` — `viewer_client.post("/objects/{id}/technik/field", data={"field_name": "year_roof", "value": "2021"})` → 403, DB bleibt unveraendert, kein FieldProvenance, kein AuditLog.
    - **AC3** `test_technik_edit_get_returns_403_for_viewer` — `viewer_client.get("/objects/{id}/technik/edit?field=year_roof")` → 403. Belegt AC3-Zweig 2 (Viewer sollen auch nicht das Form-Fragment ueber Umwege sehen koennen).
    - **AC4** `test_technik_save_invalid_year_returns_form_with_error` — POST mit `value="abc"` auf `year_roof` → HTTP 422 **und** Response enthaelt `"Bitte eine ganze Zahl (Jahr) eingeben."`, keine FieldProvenance-Row entstanden, `refreshed.year_roof` unveraendert.
    - **AC4** `test_technik_save_year_out_of_range_returns_422` — POST `value="1700"` → 422 + Fehlermeldung "Jahr muss zwischen 1800" (Substring). Value bleibt im Form erhalten (`submitted_value`).
    - **AC4** `test_technik_save_text_over_max_len_returns_422` — POST `value="x"*501` auf `heating_type` → 422.
    - **AC4** `test_technik_save_unknown_field_returns_400` — POST `field_name="does_not_exist"` → 400. (Guard in Router + Schutz vor Ghost-Schreiben auf entry_code_* via API.)
    - **AC4** `test_technik_save_rejects_entry_code_field` — POST `field_name="entry_code_main_door", value="1234"` → 400. Kritische Scope-Boundary: AC1 sagt explizit Zugangscodes sind NICHT editierbar ueber diese Endpoints. Fernet-Encryption kommt erst mit Story 1.7.
    - **AC6** `test_technik_save_empty_string_sets_null` — Objekt mit `year_roof=2021` → POST `value=""` → 200, `refreshed.year_roof is None`, FieldProvenance-Row mit `value_snapshot={"old": 2021, "new": None}` und `source="user_edit"`.
    - **AC2** `test_technik_edit_get_returns_form_fragment` — `GET /objects/{id}/technik/edit?field=year_roof` als admin → 200, Response enthaelt `hx-post`, `name="field_name" value="year_roof"`, Input mit aktuellem Wert.
    - **AC2** `test_technik_view_cancel_returns_view_fragment` — `GET /objects/{id}/technik/view?field=year_roof` → 200, kein `<form>`, Edit-Button sichtbar (weil admin).
    - **AC7** Bereits bestehend: `tests/test_write_gate_coverage.py` laeuft nach den Router-Erweiterungen weiterhin gruen — die neuen Route-Handler rufen ausschliesslich `write_field_human(...)`, kein direktes `obj.<field> = ...`. Kein neuer Test noetig, aber **manueller Check**: im neuen Router-Code kein `setattr` und keine Direktzuweisungen auf `detail.obj`.

- [x] **Task 12 — Regression + Deferred-Work-Update** (AC7)
  - [x] 12.1 `pytest -x` komplett durchlaufen lassen. Erwartung: >=405 bestehende + neue Tests, alle gruen.
  - [x] 12.2 **Nicht erwartete Noop-Fallen**: `write_field_human` hat einen No-Op-Shortcut, wenn `old == new` UND die letzte Provenance-Row dieselbe Source hat (`_latest_provenance` → source-Match). Bei wiederholtem Save desselben Werts (z.B. Admin klickt aus Versehen 2× "Speichern") landet der zweite Save im `skipped=True, skip_reason="noop_unchanged"`-Branch — kein neuer Provenance-Eintrag, kein Audit. Das ist **korrekt**, aber dokumentieren, damit der Dev-Agent nicht nachbaut "zwei Saves = zwei Provenance-Rows".
  - [x] 12.3 Findings aus dem Code-Review (falls welche entstehen, siehe `checklist.md` der Skill): nach Code-Review in `output/implementation-artifacts/deferred-work.md` unter Abschnitt `## Deferred from: code review of story-1.6 (YYYY-MM-DD)` ergaenzen.

## Dev Notes

### Was bereits existiert — NICHT neu bauen

- **`write_field_human(...)`** in `app/services/steckbrief_write_gate.py` (Zeile 194). Schreibt das Feld, flag_modified-t JSONB, legt Provenance-Row an, ruft `audit(...)`, invalidiert Pflegegrad-Cache (AC5). **Einziger** erlaubter Schreibpfad fuer Cluster-1/4/6/8-Felder — Coverage-Scanner greift sonst.
- **`get_provenance_map(db, entity_type, entity_id, fields)`** in `app/services/steckbrief.py` (Zeile 117). Liefert pro Feld die neueste `FieldProvenance`-Row mit User-Email-Resolution. Identisches Interface wie in Finanzen-Sektion — einfach ein weiteres Feld-Tupel reingeben.
- **`provenance_pill(wrap)`** Template-Global in `app/templating.py` (Zeile 78). Muss **nicht** registriert werden — ist bereits als `templates.env.globals["provenance_pill"]` verdrahtet. Einfach im neuen Template aufrufen.
- **`has_permission(user, key)`** Template-Global (`app/templating.py:114`). Benutzen fuer `{% if has_permission(user, "objects:edit") %}` im View-Fragment.
- **`require_permission("objects:edit")`** existiert als FastAPI-Dependency (`app/permissions.py:133`). `objects:edit` ist in `PERMISSIONS` registriert (`app/permissions.py:54`) und in `DEFAULT_ROLE_PERMISSIONS["user"]` — jeder normale User hat es by default.
- **Audit-Action `object_field_updated`** ist bereits in `KNOWN_AUDIT_ACTIONS` (`app/services/audit.py:74`) registriert — das Write-Gate emittiert sie automatisch. Kein Registry-Touch noetig.
- **`test_write_gate_coverage.py`** scannt `app/routers/*` + `app/services/*` auf verbotene Direktzuweisungen an CD1-Felder. Der neue Router muss strikt `write_field_human` nutzen; `# writegate: allow`-Kommentar **nur** in Tests, nie in Production-Code.
- **`accessible_object_ids(db, user)`** in `app/permissions.py:257` — in v1 liefert das schlicht alle Object.id-s zurueck, solange der User `objects:view` hat. Nutzen wie der bestehende `object_detail`-Handler.
- **`_invalidate_pflegegrad(obj)`** wird **vom Write-Gate** selbst aufgerufen (`steckbrief_write_gate.py:313-315`). Router muss nichts tun, AC5 ist "geschenkt". Test laden wir trotzdem, damit die Regression nicht stumm kippt.
- **Feld-Labels statt raw snake_case**: die `_obj_stammdaten.html`-Deferred-Work-Note ("Feld-Labels rendern raw snake_case") ist fuer Cluster 1 offen, aber Cluster 4 holt hier den Rueckstand ein: `TechnikField.label` ist **Pflicht** in der Registry. Kein "year_roof" im HTML — durchgehend deutsch.

### Scope-Boundary zu Story 1.7 (wichtig)

- **Zugangscodes (`entry_code_main_door`, `entry_code_garage`, `entry_code_technical_room`) bleiben Story 1.7.** Weder UI-Anzeige noch Edit in dieser Story.
- `TECHNIK_FIELD_KEYS` enthaelt **nicht** `entry_code_*`. Der Router-Guard `if field not in TECHNIK_FIELD_KEYS: raise 400` blockiert strukturell jeden Versuch, via `/objects/{id}/technik/field` einen Zugangscode zu schreiben — auch wenn das Write-Gate selbst (`_ENCRYPTED_FIELDS`) einen Klartext-Value mit `{"encrypted": True}`-Marker maskieren wuerde. AC1 + AC4 verlangen explizit diese Scope-Grenze.
- Grund: Story 1.7 schaltet Fernet-Encryption + UI zusammen scharf. Wuerden wir hier schon eine Plain-Text-UI bauen, haetten wir im Migrationspfad 1.6→1.7 einen Klartext-in-Plain-String-Spalten-Fenster, der per GET `/objects/{id}` potenziell im Response-Body steht. Memory-Referenz: `architecture.md:350` (CD5) + `architecture.md:361` (Ciphertext-Format `v1:<base64>`).

### Kritische Fallstricke

1. **Migration-Reihenfolge**: `ls migrations/versions/` vor Anlage der 0013 — nicht auf CLAUDE.md-Liste vertrauen (Memory: `feedback_migrations_check_existing`). Stand heute ist `0012_steckbrief_finance_mirror_fields.py` die Spitze.
2. **Kein Autogenerate**: Migration 0013 per Hand schreiben. Postgres-JSONB/UUID werden von Alembic-Autogenerate unzuverlaessig gediffed — eine autogenerierte Migration kann stumm Spalten duplizieren oder Typen downcasten.
3. **Write-Gate-Coverage-Scanner** (`tests/test_write_gate_coverage.py`): direkte `detail.obj.year_roof = 2021` im Router wird **gefangen**. Ausschliesslich `write_field_human(...)` aufrufen, der Scanner ist Text-basiert + ignoriert nur `steckbrief_write_gate.py` + Pflegegrad-Cache-Felder.
4. **HTMX + `objects:edit`-Gate**: AC3 fordert 403 auf **allen drei** Endpoints (GET edit, GET view, POST save). Auch der Cancel-Knopf (der das View-Fragment laedt) muss die Permission haben — sonst koennte ein Viewer via HTML-Inspektor das Form-Fragment vorspielen und per `curl` den POST aufrufen (der Server wirft dann 403, aber die UI-Illusion waere unsauber). Konsistente Permission-Boundary = eine Regel pro Router-Gruppe.
5. **Provenance-Pill beim ersten Edit**: Nach Save muss das View-Fragment die **frische** Provenance-Row zeigen. `_technik_field_ctx(obj, field_key, db)` laedt die Provenance on-demand per `get_provenance_map`, nicht aus dem ersten Request-Render-Dict. Sonst zeigt die Pill nach Save weiterhin "Leer".
6. **Leerer String = NULL, nicht `""`**: `parse_technik_value` mappt `""` → `None` (AC6). Wenn der Dev-Agent versehentlich `""` in die DB schreibt, bleibt die DB-Spalte ein leerer String statt NULL, und `field.value is not none` im Template rendert einen leeren Span statt des `—`-Placeholders.
7. **`write_field_human` No-Op**: Bei unveraendertem Wert + gleicher Source liefert das Gate `skipped=True, skip_reason="noop_unchanged"`. Der Router committet trotzdem (leer), das Fragment rendert mit dem alten Pill. Das ist gewollt, aber: ein Regression-Test darf nicht annehmen "nach zweitem POST existieren zwei Provenance-Rows" — es bleibt bei einer.
8. **Template-Response-Signatur**: `templates.TemplateResponse(request, "...", {...})` — `request` MUSS erstes Argument sein (Memory: `feedback_starlette_templateresponse`). Bei den drei neuen Endpoints nicht versehentlich die alte Form nutzen (`templates.TemplateResponse("...", {"request": request, ...})` → `TypeError: unhashable type dict` tief in Jinja2).
9. **Kein globaler Exception-Handler noetig**: ein `HTTPException(400)` oder `422` aus dem Router landet bei FastAPI in einer JSON-Antwort (Default-Error-Handler). Das ist fuer HTMX-Swaps irrelevant — HTMX zeigt bei 422 trotzdem den `outerHTML`-Swap, wenn der Server den Fragment-Body liefert. Dafuer gibt der POST-Handler bewusst `status_code=422` **mit** dem Fragment (`templates.TemplateResponse(..., status_code=422)`) zurueck. Den FastAPI-Default-422-Error-Body (`{"detail": ...}`) umgehen wir, indem wir den Fragment-Render **vor** dem raise platzieren.
10. **Kein `write_field_human(...)` mit `source="user_edit"` ohne User**: `_ALLOWED_SOURCES` akzeptiert `user_edit` auch mit `user=None`, aber der Sinn der Audit-Trails geht verloren. Der `Depends(require_permission("objects:edit"))` liefert immer einen User; kein Fallback noetig.

### Project Structure Notes

- **Neu angelegt:**
  - `migrations/versions/0013_steckbrief_cluster4_fields.py`
  - `app/templates/_obj_technik.html`
  - `app/templates/_obj_technik_field_view.html`
  - `app/templates/_obj_technik_field_edit.html`
  - `tests/test_technik_parser_unit.py`
  - `tests/test_technik_routes_smoke.py`
- **Modifiziert:**
  - `app/models/object.py` (8 neue typed `Mapped[...]`-Spalten — Absperrpunkte, Heizung, `year_electrics`)
  - `app/services/steckbrief.py` (TechnikField-Dataclass, TECHNIK_*-Tuple-Registries, `parse_technik_value`)
  - `app/routers/objects.py` (Imports, Technik-Context im `object_detail`, 3 neue Endpoints: `technik_field_edit`, `technik_field_view`, `technik_field_save`, Helper `_technik_field_ctx`)
  - `app/templates/object_detail.html` (`{% include "_obj_technik.html" %}` + Kommentar-Update)
- **Nicht betroffen / KEIN Touch:**
  - Keine neue Permission in `app/permissions.py` (`objects:edit` existiert).
  - Keine neue Audit-Action (`object_field_updated` existiert).
  - Kein Service `steckbrief_write_gate.py` anfassen.
  - Kein neues Workflow-Seeding in `app/main.py`.
  - Keine Aenderung am Lifespan-Scheduler.
  - Keine Aenderung an der Impower-Integration — Cluster 4 ist **nicht** Teil des Nightly-Mirrors (Story 1.4 hat bewusst nur Cluster 1+6 gespiegelt).

### References

- [Epic 1 Story 1.6 Akzeptanzkriterien](output/planning-artifacts/epics.md#story-16-technik-sektion-mit-inline-edit) — Quelle der ACs.
- [Architektur CD2 Write-Gate](output/planning-artifacts/architecture.md) — zentrale Policy, dass alle CD1-Feld-Writes durch das Gate laufen.
- [Architektur ID4 HTMX-Fragment-Strategie](output/planning-artifacts/architecture.md#id4--htmx-fragment-strategie) — `_obj_technik.html` ist eines der 7 Section-Fragments; Edit-Forms posten an Sektion-Endpoint und bekommen das Fragment zurueck.
- [Architektur CD5 Field-Level-Encryption](output/planning-artifacts/architecture.md#cd5--field-level-encryption) — dokumentiert, warum Zugangscodes nicht in 1.6 landen.
- [Story 1.5 Finanzen-Sektion](output/implementation-artifacts/1-5-finanzen-sektion-mit-live-saldo-ruecklage-sparkline.md) — Referenz-Pattern fuer Section-Fragment + Provenance-Pills.
- [Story 1.2 Write-Gate + Provenance-Infrastruktur](output/implementation-artifacts/1-2-objekt-datenmodell-write-gate-provenance-infrastruktur.md) — Mirror-Guard, No-Op-Shortcut, JSON-Safe-Provenance-Marker.
- [Object-Model](app/models/object.py:15) — bestehende Cluster-1-/6-Felder; neue Felder werden hier ergaenzt.
- [Migration 0010 Steckbrief-Core](migrations/versions/0010_steckbrief_core.py:110) — Ur-Migration der Object-Tabelle; Stil-Vorlage fuer 0013.
- [Migration 0012 Finance-Mirror-Felder](migrations/versions/0012_steckbrief_finance_mirror_fields.py) — juengste Migration, Referenz fuer `down_revision`-Kette und Add-Column-Pattern.
- [Router-Pattern Finanzen](app/routers/objects.py:77) — `object_detail`-Handler mit Provenance-Map + Template-Context-Aufbau. Neue Technik-Endpoints haengen an denselben Router.
- [Template-Pattern Stammdaten](app/templates/_obj_stammdaten.html:16) — Grid + `provenance_pill`-Aufruf als Vorbild.
- [Template-Pattern Finanzen](app/templates/_obj_finanzen.html) — Section-Wrapper mit `data-section`-Attribut + Sub-Bloecke.
- [Write-Gate-Coverage-Scanner](tests/test_write_gate_coverage.py:40) — Pattern-Liste, Escape-Hatches, Scan-Dirs.
- [Deferred-Work-Datei](output/implementation-artifacts/deferred-work.md) — dort neue Findings dokumentieren (z.B. AST-Stufe-2-Scanner, falls 1.6 weitere False-Positives ausloest).

### Latest Technical Information

- **FastAPI 0.115 + Form**: `field_name: str = Form(...)` ist der idiomatische Weg fuer HTMX-Form-Posts; `python-multipart >=0.0.17` ist bereits gelockt (project-context §Core-Backend). Kein `Body(...)`-Workaround noetig.
- **HTMX 2 via CDN** (project-context §Frontend): `hx-get`, `hx-post`, `hx-target`, `hx-swap="outerHTML"` sind die Standard-Attribute. Kein `HX-Trigger`-Polling noetig (Edit ist synchron, <100 ms).
- **SQLAlchemy 2.0 typed ORM** — alle neuen `Mapped[...]`-Felder folgen dem existierenden Stil in `app/models/object.py:24-89`. **Kein** `Column(...)`-Legacy verwenden.
- **Alembic 1.14** — Migration per Hand, `op.add_column(...)` pro Spalte. `server_default` weglassen fuer nullable optional Fields (sonst erzwingt die Migration einen DB-Wert bei bestehenden Rows, was fuer Jahr-Felder unsinnig ist).
- **pytest 8.x + asyncio_mode="auto"** (project-context §Testing): Tests sind sync, der TestClient macht die async-Sync-Bruecke selbst. Fuer die neuen Tests kein `@pytest.mark.asyncio` noetig.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7

### Debug Log References

- Erste Regression zeigte 3 rote Tests: `test_technik_save_empty_string_sets_null` (Ordering-Problem: `created_at.desc()` plus `id.desc()` ist unter SQLite mit `CURRENT_TIMESTAMP`-Sekundenaufloesung nicht deterministisch), und in `test_steckbrief_routes_smoke.py` die Tests `test_detail_renders_stammdaten_and_eigentuemer` (assert `"Technik" not in body` ist mit gebauter Sektion hinfaellig) und `test_detail_sql_statement_count` (Grenze `<=7` war fuer Pre-1.6-Query-Count, die zusaetzliche Technik-Provenance-Map erhoeht ihn auf max 8). Alle drei gefixt — mein Empty-String-Test filtert jetzt inhaltlich auf die Loesch-Row statt per Sort-Order.

### Completion Notes List

- **Migration 0013** `steckbrief_cluster4_fields.py` anglegt, `down_revision="0012"` (bestaetigt per `ls migrations/versions/` — 0012 ist tatsaechlich die Spitze, CLAUDE.md-Aufstellung war aktuell). Per Hand geschrieben, kein Autogenerate.
- **ORM** in `app/models/object.py` um 8 typed `Mapped[...]`-Spalten erweitert (zwischen `year_roof` und `entry_code_*`-Feldern eingefuegt, Gruppierung nach Domaene wie Story verlangt).
- **Service** in `app/services/steckbrief.py` erweitert um `TechnikField`-Dataclass, die drei Sub-Block-Tuple-Registries + Gesamt-Tuple + `frozenset`-Key-Set, und die `parse_technik_value`-Funktion. Single-Source-of-Truth fuer Router + Templates, Validierungsfehler sind lokalisierte deutsche Strings.
- **Router** in `app/routers/objects.py`: Imports ergaenzt, Technik-Block im `object_detail`-Handler (mit innerer `_build_section`-Helper-Funktion), plus drei neue Endpoints (`technik_field_edit` GET, `technik_field_view` GET, `technik_field_save` POST) + `_technik_field_ctx`-Helper. Alle drei Endpoints an `require_permission("objects:edit")` — deckt AC3 auch fuer das Cancel-/Edit-Fragment-Load.
- **Templates**: `_obj_technik.html` als Section-Wrapper mit 3 Sub-Bloecken; `_obj_technik_field_view.html` als Single-Field-Fragment mit Pill + Edit-Button; `_obj_technik_field_edit.html` als Inline-Form mit Save/Cancel + Fehler-Rendering. `object_detail.html` um `{% include "_obj_technik.html" %}` erweitert und den Kommentar angepasst.
- **Tests** (neu):
  - `tests/test_technik_parser_unit.py` (12 Tests): Empty-String-Semantik (AC6), Jahr-Range inkl. dynamische Obergrenze (`current_year + 1`), Text-Length-Limit, Whitespace-Trim, Unbekannte-Felder-Guard (inkl. `entry_code_main_door` → ValueError als Scope-Boundary zu Story 1.7).
  - `tests/test_technik_routes_smoke.py` (15 Tests): AC1 (Sektion + 10 Felder + 10 Edit-Buttons + deutsche Labels, keine `entry_code_*`), AC2+AC5 (Save → DB + Provenance + Audit + Pflegegrad-Cache-Invalidate), AC3 (Viewer: keine Edit-Buttons + POST 403 + GET-Edit 403), AC4 (invalid year 422, out-of-range 422, text-over-max 422, unknown-field 400, `entry_code_main_door` via POST 400), AC6 (Empty-String → NULL mit Provenance-Delta).
- **Regression**: volle Suite laeuft mit **432 Tests, alle gruen** (>=405 Baseline + 27 neue). Zwei bestehende Tests in `test_steckbrief_routes_smoke.py` angepasst (Technik-Negative-Assertion entfernt, SQL-Statement-Count von `<=7` auf `<=8` gehoben mit Kommentar-Update — die zusaetzliche Provenance-Map-Query fuer Technik ist strukturell unvermeidbar und konsistent zum bestehenden Stammdaten/Finanzen-Pattern).
- **Scope-Boundary zu Story 1.7**: Zugangscodes (`entry_code_*`) sind strukturell nicht schreibbar via `/objects/{id}/technik/field` — weder Router-Whitelist noch Parser lassen sie durch. AC-Tests fangen das explizit ab (`test_technik_save_rejects_entry_code_field`).

### File List

- **Neu**:
  - `migrations/versions/0013_steckbrief_cluster4_fields.py`
  - `app/templates/_obj_technik.html`
  - `app/templates/_obj_technik_field_view.html`
  - `app/templates/_obj_technik_field_edit.html`
  - `tests/test_technik_parser_unit.py`
  - `tests/test_technik_routes_smoke.py`
- **Modifiziert**:
  - `app/models/object.py` (8 neue typed `Mapped[...]`-Spalten)
  - `app/services/steckbrief.py` (TechnikField + TECHNIK_*-Registries + `parse_technik_value`)
  - `app/routers/objects.py` (Imports + Technik-Block im `object_detail` + 3 neue Endpoints + Helper)
  - `app/templates/object_detail.html` (Technik-Include + Kommentar)
  - `tests/test_steckbrief_routes_smoke.py` (Technik-Assert entfernt, SQL-Count-Grenze `<=8`)
  - `output/implementation-artifacts/sprint-status.yaml` (Story 1.6: ready-for-dev → review)

### Change Log

- 2026-04-23: Story 1.6 implementiert — Technik-Sektion mit 3 Sub-Bloecken (Absperrpunkte, Heizung, Objekt-Historie), 10 inline-editierbare Felder ueber HTMX-Fragments, durchgaengig via Write-Gate. Neue Migration 0013, neue Validator-Logik, 27 neue Tests. Zwei bestehende Steckbrief-Route-Smoke-Tests an die neue Sektion angepasst. Regression 432 Tests gruen.

### Review Findings

- [x] [Review][Decision] GET /technik/view hinter objects:edit — bei objects:edit belassen, Test ergaenzt (test_technik_view_get_returns_403_for_viewer).

- [x] [Review][Patch] _technik_field_ctx baut inline dict statt Modul-Konstante _TECHNIK_LOOKUP [app/routers/objects.py] — gefixt: next() statt inline dict
- [x] [Review][Patch] parse_technik_value: int("2021.0") schlaegt fehl — Browser sendet bei type=number ggf. Dezimalzahl [app/services/steckbrief.py + app/templates/_obj_technik_field_edit.html] — gefixt: float() + ganzzahl-check + step="1"
- [x] [Review][Patch] Fixture steckbrief_admin_user Email-Kollision mit conftest.py-User [tests/test_technik_routes_smoke.py:47] — gefixt: eigene unique Email
- [x] [Review][Patch] AC4-Tests ohne data-error="true"-Assertion [tests/test_technik_routes_smoke.py] — gefixt: Assertion ergaenzt
- [x] [Review][Patch] Kein try/except + db.rollback() um db.commit() in technik_field_save [app/routers/objects.py] — gefixt: try/except + rollback

- [x] [Review][Defer] Template max="3000" divergiert bewusst von Server-Limit current_year+1 (Task 8.2 dokumentiert) [app/templates/_obj_technik_field_edit.html] — deferred, bewusste Design-Entscheidung
- [x] [Review][Defer] year_built/year_roof gleichzeitig in Stammdaten-Herkunft und Technik-Registry [app/services/steckbrief.py] — deferred, pre-existing design concern
- [x] [Review][Defer] CSRF-Schutz fehlt auf POST-Endpunkten — deferred, platform-weites pre-existing Issue
- [x] [Review][Defer] get_provenance_map dreifach als separater SQL-Hit in object_detail [app/routers/objects.py] — deferred, pre-existing Pattern aus Story 1.4/1.5
- [x] [Review][Defer] Jinja2 Autoescape nicht explizit konfiguriert [app/templating.py] — deferred, pre-existing
