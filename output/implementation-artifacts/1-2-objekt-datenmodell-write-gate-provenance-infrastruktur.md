# Story 1.2: Objekt-Datenmodell, Write-Gate & Provenance-Infrastruktur

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Entwickler im Steckbrief-Modul,
ich moechte ein zentralisiertes Write-Gate mit automatischer FieldProvenance-Erzeugung und struktureller KI-Blockade zur Verfuegung haben,
damit alle nachfolgenden Stories (1.3–1.8, 2.x, 3.x) saubere, nachvollziehbare Schreibvorgaenge ohne Policy-Risiko ausfuehren koennen und FR21 / FR25 / NFR-S4 / NFR-S6 strukturell erzwungen sind.

## Acceptance Criteria

**AC1 — Migration 0010 legt alle 15 Haupt-/Registry-Tabellen inkl. Indexe an**
Given eine frische Datenbank,
when `alembic upgrade head` laeuft,
then existieren die Tabellen `objects`, `units`, `policen`, `wartungspflichten`, `schadensfaelle`, `versicherer`, `dienstleister`, `banken`, `ablesefirmen`, `eigentuemer`, `mieter`, `mietvertraege`, `zaehler`, `facilioo_tickets`, `steckbrief_photos` mit UUID-PKs, `created_at`/`updated_at` + den in der Architektur definierten Indexen (`Police.next_main_due`, `Wartungspflicht.next_due_date`, `FaciliooTicket.facilioo_id` UNIQUE, alle FK-Spalten indiziert).

**AC2 — Migration 0011 legt Governance-Tabellen + `resource_type="object"` an**
Given Migration 0010 ist durchgelaufen,
when `alembic upgrade head` Revision `0011` anwendet,
then existieren die Tabellen `field_provenance` und `review_queue_entries` mit Indexen `field_provenance(entity_type, entity_id, field_name)`, `review_queue_entries(status, created_at)`, `review_queue_entries(target_entity_type, target_entity_id)` und `review_queue_entries(assigned_to_user_id, status)`,
and die Konstante `RESOURCE_TYPE_OBJECT = "object"` ist in `app/permissions.py` exportiert und `resource_access` akzeptiert Rows mit `resource_type="object"` ohne Check-Constraint-Verletzung.

**AC3 — ORM-Modelle sind importierbar + zu `Base.metadata` registriert**
Given das App-Paket wird importiert (`from app.models import Object, InsurancePolicy, FieldProvenance, ReviewQueueEntry, ...`),
when die Klassen instanziiert und per `Base.metadata.create_all()` auf SQLite (Test-DB) erzeugt werden,
then entstehen dieselben Tabellen wie in AC1/AC2,
and `tests/conftest.py::Base.metadata.create_all(_TEST_ENGINE)` laeuft ohne Fehler — alle neuen Modelle sind im zentralen `from app.models import (...)`-Import und in `app/models/__init__.py::__all__` gelistet.

**AC4 — `write_field_human` schreibt Feld + Provenance + Audit in einer Transaktion**
Given ein bestehendes `Object` und ein authentifizierter User mit `objects:edit`,
when Code
```python
write_field_human(db, entity=obj, field="year_roof", value=2021,
                  source="user_edit", user=user, request=request)
db.commit()
```
aufruft,
then ist `obj.year_roof == 2021` persistiert,
and existiert **genau eine** neue `FieldProvenance`-Zeile mit `entity_type="object"`, `entity_id=obj.id`, `field_name="year_roof"`, `source="user_edit"`, `user_id=user.id`, `value_snapshot={"old": <prev>, "new": 2021}`,
and existiert in **derselben Transaktion** ein `AuditLog`-Eintrag mit `action="object_field_updated"`, `entity_type="object"`, `entity_id=obj.id`, `user_id=user.id`.

**AC5 — `write_field_ai_proposal` schreibt NIE ins Zielfeld, nur Queue + Audit**
Given ein KI-Agent-Code ruft
```python
write_field_ai_proposal(db, target_entity_type="object", target_entity_id=obj.id,
                       field="year_roof", proposed_value=2019,
                       agent_ref="te_scan_agent", confidence=0.8,
                       source_doc_id=doc.id, agent_context={"prompt_version": "v1"})
db.commit()
```
when die Funktion ausgefuehrt ist,
then ist `obj.year_roof` **unveraendert**,
and entsteht eine `ReviewQueueEntry`-Zeile mit `status="pending"`, `target_entity_type="object"`, `target_entity_id=obj.id`, `field_name="year_roof"`, `proposed_value={"value": 2019}`, `agent_ref="te_scan_agent"`, `confidence=0.8`,
and entsteht ein `AuditLog`-Eintrag mit `action="review_queue_created"`.

**AC6 — `approve_review_entry` schreibt Feld mit `source="ai_suggestion"` + Confidence**
Given ein `ReviewQueueEntry` mit `status="pending"` und ein Admin mit `objects:approve_ki`,
when `approve_review_entry(db, entry_id=entry.id, user=admin, request=request)` aufgerufen + committed wird,
then ist `obj.<field> == entry.proposed_value["value"]`,
and die neue `FieldProvenance`-Zeile traegt `source="ai_suggestion"`, `user_id=admin.id`, `source_ref=entry.agent_ref`, `confidence=entry.confidence`,
and der `ReviewQueueEntry` hat `status="approved"`, `decided_at` gesetzt, `decided_by_user_id=admin.id`,
and ein `AuditLog`-Eintrag mit `action="review_queue_approved"` existiert.

**AC7 — `reject_review_entry` markiert Eintrag ohne Field-Write**
Given ein `ReviewQueueEntry` mit `status="pending"`,
when `reject_review_entry(db, entry_id=entry.id, user=admin, reason="falsche OCR", request=request)` aufgerufen + committed wird,
then ist `obj.<field>` **unveraendert**,
and der Eintrag hat `status="rejected"`, `decision_reason="falsche OCR"`, `decided_at` + `decided_by_user_id=admin.id`,
and **keine** neue `FieldProvenance`-Zeile entsteht,
and ein `AuditLog`-Eintrag mit `action="review_queue_rejected"` existiert.

**AC8 — Mirror-Ueberschreib-Konvention (Gap G8)**
Given ein `Object` mit `year_roof=2020` und Provenance-History `[impower_mirror (2020), user_edit (2021)]` (letzte = `user_edit`),
when ein Nightly-Mirror-Job `write_field_human(..., source="impower_mirror", user=None, ...)` mit Wert `2020` aufruft,
then bleibt `obj.year_roof == 2021` unveraendert (User-Edit gewinnt),
and es entsteht **keine** neue `FieldProvenance`-Zeile,
and **kein** `invalidate_pflegegrad`-Aufruf wird ausgefuehrt (Cache bleibt gueltig — sonst wuerde jeder Nightly-Mirror alle Pflegegrad-Caches reseten, auch ohne Value-Change),
and der Call gibt einen sichtbaren Hinweis zurueck (`WriteResult(skipped=True, reason="user_edit_newer")` oder aequivalent) — Caller kann das fuer Reporting nutzen.

Given dasselbe Object und Provenance-History `[impower_mirror (2020), impower_mirror (2021)]` (letzte = `impower_mirror`),
when ein Nightly-Mirror-Job `write_field_human(..., source="impower_mirror", ...)` mit Wert `2022` aufruft,
then wird `obj.year_roof = 2022` geschrieben + Provenance-Eintrag erstellt.

**AC9 — Konsistenz-Check: keine direkten Field-Writes auf CD1-Entitaeten**
Given der Unit-Test `test_write_gate_coverage` greept die Datei `app/routers/*.py` + `app/services/*.py` (ausser `steckbrief_write_gate.py` selbst) nach dem Pattern `entity.<field> = value`, wobei `entity` ein ORM-Object der CD1-Haupt-Entitaeten ist (`Object`, `Unit`, `InsurancePolicy`, `Wartungspflicht`, `Schadensfall`, `Versicherer`, `Dienstleister`, `Bank`, `Ablesefirma`, `Eigentuemer`, `Mieter`, `Mietvertrag`, `Zaehler`, `FaciliooTicket`),
when der Check laeuft,
then gibt es **keine** Funde ausserhalb der erlaubten Ausnahmen: (a) Row-Creation via `db.add(Entity(field=value, ...))`, (b) Pflegegrad-Cache-Felder `pflegegrad_score_cached` / `pflegegrad_score_updated_at` (werden vom Gate selbst gesetzt via `invalidate_pflegegrad`), (c) Schreibvorgaenge an `SteckbriefPhoto` (Struktur-Row), (d) Governance-Tabellen `FieldProvenance`, `ReviewQueueEntry`, `AuditLog`.

**AC10 — JSONB-Mutations-Sicherheit im Write-Gate**
Given ein `Object` mit `voting_rights={"alt": 0.5}` (JSONB-Feld),
when `write_field_human(db, entity=obj, field="voting_rights", value={"neu": 0.6}, source="user_edit", user=user)` aufgerufen + committed + Session neu geladen wird,
then ist `obj.voting_rights == {"neu": 0.6}` persistiert (das Gate macht entweder Reassignment oder `flag_modified` — nicht in-place-Mutation).

## Tasks / Subtasks

- [x] **Task 1:** Migration `0010_steckbrief_core.py` — Haupt-/Registry-Tabellen (AC1, AC3)
  - [x] **Vorab-Check:** `ls migrations/versions/` ausfuehren und die neueste Revision als `down_revision` eintragen. Erwartet: `down_revision = "0009"` (Memory `feedback_migrations_check_existing`). Nicht CLAUDE.md-Listen vertrauen.
  - [x] Neue Datei `migrations/versions/0010_steckbrief_core.py` (manuell, **nicht** autogenerate — `docs/project-context.md` §Migrations).
  - [x] `upgrade()`: 15 `op.create_table(...)`-Calls in FK-Reihenfolge: zuerst ohne FK (`Versicherer`, `Dienstleister`, `Bank`, `Ablesefirma`, `Object`), dann abhaengig (`Unit` → Object; `InsurancePolicy` → Object + Versicherer; `Wartungspflicht` → InsurancePolicy + Dienstleister; `Schadensfall` → InsurancePolicy + Unit; `Eigentuemer`, `Mieter` → Object; `Mietvertrag` → Unit + Mieter; `Zaehler` → Unit; `FaciliooTicket` → Object; `SteckbriefPhoto` → Object + optional Unit). Plural-Tabellennamen siehe AC1.
  - [x] Pflicht-Spalten pro Tabelle: `id UUID PK DEFAULT`, `created_at TIMESTAMPTZ DEFAULT NOW()`, `updated_at TIMESTAMPTZ DEFAULT NOW() ON UPDATE NOW()`. `uuid.uuid4` als Python-Default in Modellen; Migration nutzt `postgresql.UUID(as_uuid=True)` + `server_default` fuer Timestamps (Muster wie `migrations/versions/0008_cases_and_document_types.py`).
  - [x] JSONB-Felder aus Architektur-Tabelle (CD1): `Object.voting_rights`, `Object.object_history_structured`, `Object.equipment_flags`, `Object.notes_owners`, `Unit.equipment_features`, `Unit.floorplan_drive_item_id` (String, kein JSONB), `InsurancePolicy.coverage`, `InsurancePolicy.risk_attributes`, `Wartungspflicht.notes`, `Schadensfall.description` (Text, kein JSONB), `Versicherer.contact_info`, `Dienstleister.gewerke_tags`, `Dienstleister.notes`, `Eigentuemer.voting_stake_json`, `Zaehler.current_reading_snapshot`, `FaciliooTicket.raw_payload`, `SteckbriefPhoto.photo_metadata` (DB-Spalte `photo_metadata`; **nicht** `metadata` — der Name ist auf `DeclarativeBase` reserviert (`Base.metadata` = SQLAlchemy-MetaData-Singleton) und wirft `InvalidRequestError: Attribute name 'metadata' is reserved` beim Klassen-Build). JSONB `nullable=False, server_default=sa.text("'{}'::jsonb")` bzw. `'[]'::jsonb` je nach Typ (Muster aus `cases`-Tabelle).
  - [x] `Object`-Spezial-Spalten (aus PRD/Architektur abgeleitet): `short_code String UNIQUE`, `name String`, `full_address String`, `weg_nr String`, `impower_property_id String INDEX`, `year_built Integer`, `year_roof Integer`, `entry_code_main_door String` (Ciphertext, Encryption erst Story 1.7), `entry_code_garage String`, `entry_code_technical_room String`, `last_known_balance Numeric(12,2)`, `pflegegrad_score_cached Integer NULL`, `pflegegrad_score_updated_at TIMESTAMPTZ NULL`.
  - [x] **Vor Migration-Schreibung:** `docs/objektsteckbrief-feld-katalog.md` gegenchecken — alle Felder mit `Pflicht v1 = ✓` in Cluster 1/4/6/8 muessen hier als Spalten landen, sonst zwingt Story 1.5/1.6 eine spaetere Migration 0012. Insbesondere Cluster-2-Felder auf `InsurancePolicy` pruefen.
  - [x] `InsurancePolicy`-Spezial-Spalten: `police_number String`, `main_due_date Date NULL`, `next_main_due Date NULL INDEX`, `praemie Numeric(12,2)`, `risk_attributes JSONB` (v1.1-Felder duerfen leer bleiben). Feldkatalog-Check-Ergebnis hier ergaenzen, falls weitere v1-Pflichtfelder auftauchen.
  - [x] `Wartungspflicht.next_due_date Date NULL INDEX`.
  - [x] `FaciliooTicket.facilioo_id String UNIQUE INDEX`.
  - [x] FK-Spalten konsequent indizieren (`op.create_index(f"ix_{table}_{col}", table, [col])`).
  - [x] `downgrade()`: `op.drop_table(...)` in umgekehrter FK-Reihenfolge, davor die zugehoerigen `drop_index`.
  - [x] Keine Audit-Actions-Seed mehr — sind **bereits** in Story 1.1 als `KNOWN_AUDIT_ACTIONS`-Konstante registriert (`app/services/audit.py:73-87`). Story 1.2 nutzt sie nur.
  - [x] Keine Permissions-Seed in Migration — Permissions stehen in `app/permissions.py:PERMISSIONS` und werden nicht in die DB persistiert.

- [x] **Task 2:** Migration `0011_steckbrief_governance.py` — FieldProvenance + ReviewQueueEntry (AC2, AC3)
  - [x] Neue Datei `migrations/versions/0011_steckbrief_governance.py`, `down_revision = "0010"`.
  - [x] `op.create_table("field_provenance", ...)` mit Spalten:
    - `id UUID PK`, `entity_type String NOT NULL`, `entity_id UUID NOT NULL`, `field_name String NOT NULL`
    - `source String NOT NULL` (Werte: `user_edit | impower_mirror | facilioo_mirror | sharepoint_mirror | ai_suggestion` — als String, **kein** SQL-Enum, damit neue Quellen ohne Migration moeglich sind)
    - `source_ref String NULL`, `user_id UUID NULL FK→users(id) ON DELETE SET NULL`, `confidence Float NULL`
    - `value_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb` (enthaelt `{"old": ..., "new": ...}` — JSON-kompatible Werte; Date/UUID werden vor Einfuegen in Strings konvertiert)
    - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
  - [x] Indexe: `ix_field_provenance_entity_field` auf `(entity_type, entity_id, field_name)`, `ix_field_provenance_user_id`, `ix_field_provenance_created_at`.
  - [x] `op.create_table("review_queue_entries", ...)` mit Spalten:
    - `id UUID PK`, `target_entity_type String NOT NULL`, `target_entity_id UUID NOT NULL`, `field_name String NOT NULL`
    - `proposed_value JSONB NOT NULL` (wrap: `{"value": <typisierter Wert>}` — vereinheitlicht Typ-Unterschiede int/str/dict)
    - `agent_ref String NOT NULL`, `confidence Float NOT NULL`, `source_doc_id UUID NULL FK→documents(id) ON DELETE SET NULL`, `agent_context JSONB NOT NULL DEFAULT '{}'::jsonb`
    - `status String NOT NULL DEFAULT 'pending'` (Werte `pending | approved | rejected | superseded` — String, kein Enum)
    - `assigned_to_user_id UUID NULL FK→users(id) ON DELETE SET NULL` (v1 ungenutzt, v1.1-Filter FR24 ohne Migration scharfschaltbar — im `epics.md` explizit gefordert)
    - `decided_at TIMESTAMPTZ NULL`, `decided_by_user_id UUID NULL FK→users(id) ON DELETE SET NULL`, `decision_reason Text NULL`
    - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
  - [x] Indexe: `ix_review_queue_status_created` auf `(status, created_at)`, `ix_review_queue_target` auf `(target_entity_type, target_entity_id)`, `ix_review_queue_assigned` auf `(assigned_to_user_id, status)`, `ix_review_queue_source_doc`.
  - [x] **Keine DDL-Aenderung auf `resource_access`** — die Tabelle (`migrations/versions/0006_roles_and_resource_access.py:67-114`) hat `resource_type String NOT NULL` ohne Check-Constraint auf erlaubte Werte. `"object"` wird automatisch akzeptiert. Migration 0011 fuegt trotzdem einen **No-Op-Block** mit einem Inline-Kommentar ein (fuer Grep-Findability bei v1.1-Enforcement-Arbeit). Konkret am Ende von `upgrade()`:
    ```python
    # Seit Migration 0011 akzeptiert resource_access.resource_type den Wert "object"
    # (kein Check-Constraint, kein Enum — die Tabelle validiert nicht). v1 nutzt
    # die Zeilen als Soft-Record; Enforcement via accessible_object_ids() schaltet
    # v1.1 scharf. Falls v1.1 auf ein Enum migriert, hier CHECK-Constraint ergaenzen.
    ```
  - [x] `RESOURCE_TYPE_OBJECT = "object"`-Konstante in `app/permissions.py` neben `RESOURCE_TYPE_WORKFLOW` hinzufuegen (Story 1.1 hat diese Konstante explizit auf 1.2 verschoben, siehe `1-1-steckbrief-permissions-audit-actions-default-header.md:50`).
  - [x] `downgrade()`: drop Indexe + `review_queue_entries` + `field_provenance` in dieser Reihenfolge.

- [x] **Task 3:** ORM-Modelle in `app/models/` (AC3)
  - [x] **Vorab:** bestehendes Pattern anschauen: `app/models/case.py` (JSONB, UUID, FK + `relationship`, `default=dict` + `server_default="{}"`) — als Schablone fuer alle neuen Modelle verwenden.
  - [x] Neue Dateien gemaess Architektur-File-Plan (`output/planning-artifacts/architecture.md:558-564`):
    - `app/models/object.py` → `Object`, `Unit`, `SteckbriefPhoto`
    - `app/models/police.py` → `InsurancePolicy` (Tabelle `policen`), `Wartungspflicht` (Tabelle `wartungspflichten`), `Schadensfall` (Tabelle `schadensfaelle`)
    - `app/models/registry.py` → `Versicherer`, `Dienstleister`, `Bank` (Tabelle `banken`), `Ablesefirma` (Tabelle `ablesefirmen`)
    - `app/models/person.py` → `Eigentuemer`, `Mieter`
    - `app/models/rental.py` → `Mietvertrag` (Tabelle `mietvertraege`), `Zaehler`
    - `app/models/facilioo.py` → `FaciliooTicket` (Tabelle `facilioo_tickets`)
    - `app/models/governance.py` → `FieldProvenance` (Tabelle `field_provenance`), `ReviewQueueEntry` (Tabelle `review_queue_entries`)
  - [x] Jede Klasse: SQLAlchemy 2.0 typed `Mapped[...]` + `mapped_column(...)` (project-context §SQLAlchemy 2.0), UUID-PK mit `default=uuid.uuid4`, `created_at`/`updated_at` wie in `Case`-Modell.
  - [x] `InsurancePolicy` als Python-Klassenname (Tabellenname `policen`, `__tablename__ = "policen"`), **nicht** `Policy` — Namenskollision mit "Permissions-Policy" laut Architektur (`architecture.md:471`).
  - [x] `relationship(...)`-Rueckbezug nur wo fuer spaetere Stories noetig (z.B. `Object.units`, `Object.policen`) — **keine spekulativen Relations** (project-context §Keine spekulative Abstraktion).
  - [x] JSONB-Dict-Mutation-Warnung im Klassen-Docstring: *"JSONB-Mutation nie in-place — immer Reassignment oder `flag_modified()`"* (Memory `docs/project-context.md:63`).
  - [x] **Reservierte-Attributnamen-Falle:** In `SteckbriefPhoto` NICHT `metadata: Mapped[dict]` definieren — `metadata` ist auf SQLAlchemy-`DeclarativeBase` reserviert (Kollision mit `Base.metadata`, Klassen-Build wirft `InvalidRequestError`). Attributname und DB-Spalte beide `photo_metadata` nennen (konsistent im Model, in der Migration 0010 und in allen Tests).
  - [x] Alle neuen Modelle in `app/models/__init__.py`-Import + `__all__` aufnehmen — das importiert die Submodule transitiv, SQLAlchemy registriert alle Tabellen automatisch auf `Base.metadata`, und SQLite legt sie beim `create_all` in der Test-DB an. Die explizite Liste in `conftest.py` ist damit **nicht** der Enforcement-Punkt (siehe Task 7).

- [x] **Task 4:** Write-Gate-Service `app/services/steckbrief_write_gate.py` (AC4–AC8, AC10)
  - [x] Neue Datei `app/services/steckbrief_write_gate.py` — Public API laut Architektur (`architecture.md:205-241`), erweitert um `confidence` auf `write_field_human`:
    - `write_field_human(db, *, entity, field, value, source, user, source_ref=None, confidence=None, request=None) -> WriteResult`
    - `write_field_ai_proposal(db, *, target_entity_type, target_entity_id, field, proposed_value, agent_ref, confidence, source_doc_id, agent_context) -> ReviewQueueEntry`
    - `approve_review_entry(db, *, entry_id, user, request) -> None`
    - `reject_review_entry(db, *, entry_id, user, reason, request) -> None`
  - [x] `WriteResult`-Dataclass: `written: bool`, `skipped: bool = False`, `skip_reason: str | None = None`. Ermoeglicht Callern (Mirror-Jobs) Reporting ohne weitere DB-Queries.
  - [x] **Entity-Type-Mapping** (Modul-Level-Konstante, einzige Quelle der Wahrheit):
    ```python
    _TABLE_TO_ENTITY_TYPE: dict[str, str] = {
        "objects": "object",
        "units": "unit",
        "policen": "police",
        "wartungspflichten": "wartung",
        "schadensfaelle": "schaden",
        "versicherer": "versicherer",
        "dienstleister": "dienstleister",
        "banken": "bank",
        "ablesefirmen": "ablesefirma",
        "eigentuemer": "eigentuemer",
        "mieter": "mieter",
        "mietvertraege": "mietvertrag",
        "zaehler": "zaehler",
        "facilioo_tickets": "facilioo_ticket",
        "steckbrief_photos": "steckbrief_photo",
    }
    _REGISTRY_ENTITY_TYPES = {"versicherer", "dienstleister", "bank", "ablesefirma", "eigentuemer", "mieter"}
    _ENCRYPTED_FIELDS: dict[str, set[str]] = {
        "object": {"entry_code_main_door", "entry_code_garage", "entry_code_technical_room"},
    }
    ```
    Keine `rstrip("s")`-Heuristik — deutsche Plurale (`policen`, `wartungspflichten`, `eigentuemer` = Singular=Plural) brechen die Ableitung. Unbekannter `__tablename__` → `WriteGateError`.
  - [x] **`_json_safe(value)` Helper** (Dev Notes §JSONB-Snapshot-Safety):
    - `None`, `bool`, `int`, `float`, `str` → unveraendert zurueck.
    - `uuid.UUID` → `str(value)`.
    - `datetime.date` / `datetime.datetime` → `value.isoformat()`.
    - `decimal.Decimal` → `str(value)` (Kommastellen erhalten).
    - `bytes` → `base64.b64encode(value).decode()`.
    - `list` / `tuple` → rekursiv `[_json_safe(x) for x in value]`.
    - `dict` → rekursiv `{k: _json_safe(v) for k, v in value.items()}`.
    - Alles andere → `str(value)` als Fallback (nie crashen; lieber lesbar als throw).
    - Zweiter Helper `_json_safe_for_provenance(entity_type, field, value)`: ersetzt den Rueckgabewert durch `{"encrypted": True}`, wenn `field in _ENCRYPTED_FIELDS.get(entity_type, set())` — blockiert Klartext in `value_snapshot` + Audit-Details.
  - [x] **Implementierungs-Schritte `write_field_human`:**
    1. Entity-Type ueber `_TABLE_TO_ENTITY_TYPE[entity.__tablename__]` ableiten; `KeyError` → `WriteGateError`.
    2. Source-Whitelist pruefen: `source in {"user_edit", "impower_mirror", "facilioo_mirror", "sharepoint_mirror", "ai_suggestion"}`, sonst `WriteGateError`.
    3. Mirror-Guard (AC8): wenn `source` einer der Mirror-Quellen ist (`impower_mirror`, `facilioo_mirror`, `sharepoint_mirror`), zuerst `FieldProvenance`-History des Feldes laden (letzter Eintrag nach `created_at DESC`). Wenn dessen `source` `user_edit` oder `ai_suggestion` ist → return `WriteResult(written=False, skipped=True, skip_reason="user_edit_newer")` **ohne** Field-Write, **ohne** Provenance-Eintrag, **ohne** Audit, **ohne** `invalidate_pflegegrad`. Ausnahme: Erster Mirror-Call (keine History) schreibt.
    4. Old-Value lesen: `old = getattr(entity, field)`. Wenn `old == value` und letzte Provenance denselben Source haelt → return `WriteResult(written=False, skipped=True, skip_reason="noop_unchanged")`, **kein** Provenance-Eintrag, **kein** `invalidate_pflegegrad`. Sonst weiter.
    5. Feld setzen: bei JSONB-Feldern vollstaendiges Reassignment (`setattr(entity, field, copy.deepcopy(value))`) oder plain `setattr` + `flag_modified(entity, field)` (Muster project-context §JSONB-Fallen).
    6. `FieldProvenance`-Row anlegen. `value_snapshot={"old": _json_safe_for_provenance(entity_type, field, old), "new": _json_safe_for_provenance(entity_type, field, value)}`. Felder auf der Row: `source`, `source_ref` (durchgereicht), `user_id=user.id if user else None`, `confidence` (durchgereicht — `None` fuer user_edit/mirror, float fuer ai_suggestion).
    7. `audit()`-Call:
        - `entity_type in _REGISTRY_ENTITY_TYPES` → `action="registry_entry_updated"`.
        - sonst → `action="object_field_updated"` (bewusst generisch fuer alle CD1-Entitaeten — siehe Dev Notes §Audit-Actions-Strategie; semantisch akzeptiert, auch fuer `InsurancePolicy`/`Wartungspflicht`/... Entity-Type unterscheidet das Event).
        - Details: `{"entity_type": entity_type, "field": field, "source": source, "old": _json_safe_for_provenance(...), "new": _json_safe_for_provenance(...)}`. Bei Zugangscodes landet der Marker `{"encrypted": True}` — Klartext-Schutz auch im Audit-Log (NFR-S2).
    8. `invalidate_pflegegrad(entity)` aufrufen — **nur bei `written=True`**: wenn `entity` ein `Object` ist, setze `entity.pflegegrad_score_cached = None` + `entity.pflegegrad_score_updated_at = None`. Diese zwei Cache-Writes sind explizite Ausnahme vom Write-Gate-Boundary (AC9), im Docstring der Funktion dokumentieren.
    9. **Kein `db.commit()`** — Caller entscheidet. (project-context §Auditing, `architecture.md:491`).
    10. Return `WriteResult(written=True)`.
  - [x] **Implementierungs-Schritte `write_field_ai_proposal`:**
    1. Validierung: `confidence` in `[0.0, 1.0]`, sonst `ValueError`. `target_entity_type in _TABLE_TO_ENTITY_TYPE.values()`, sonst `WriteGateError`.
    2. `ReviewQueueEntry` anlegen, `proposed_value={"value": _json_safe(proposed_value)}`.
    3. `audit(... action="review_queue_created", entity_type=target_entity_type, entity_id=target_entity_id, details={"field": field, "agent_ref": agent_ref, "confidence": confidence})`.
    4. Return Entry. Caller committed.
  - [x] **Implementierungs-Schritte `approve_review_entry`:**
    1. Entry laden (`db.get(ReviewQueueEntry, entry_id)`), pruefen `status == "pending"` sonst `ValueError("bereits entschieden")`.
    2. Ziel-Entity laden ueber Mapping `{"object": Object, "police": InsurancePolicy, ...}` + `db.get(Cls, entry.target_entity_id)`. Gleiche Source-of-Truth wie `_TABLE_TO_ENTITY_TYPE` (Klassenliste als inverses Mapping neben der Konstante fuehren).
    3. `db.flush()` aufrufen, falls der Entry noch keinen persistierten Zustand hat (edge-case: approve direkt nach Create ohne intermittenten Commit) — danach hat `entry.id` + `entry.agent_ref` sichere Werte, die wir unten referenzieren.
    4. `write_field_human(db, entity=target, field=entry.field_name, value=entry.proposed_value["value"], source="ai_suggestion", user=user, source_ref=entry.agent_ref, confidence=entry.confidence, request=request)` aufrufen. Der `confidence`-Param durchreichen ist die kanonische Variante — Helfer legt die Provenance-Row inkl. `confidence` + `source_ref` in einem Atomic-Call an. Kein nachtraegliches Row-Patching.
    5. `entry.status = "approved"`, `entry.decided_at = func.now()` (bzw. `datetime.now(tz=...)`), `entry.decided_by_user_id = user.id`.
    6. `audit(... action="review_queue_approved", entity_type="review_queue_entry", entity_id=entry.id, details={"target_entity_type": ..., "field": ..., "value": ...})`.
  - [x] **Implementierungs-Schritte `reject_review_entry`:**
    1. Entry laden + status-Check wie oben.
    2. `entry.status = "rejected"`, `entry.decision_reason = reason`, `entry.decided_at`, `entry.decided_by_user_id`.
    3. `audit(... action="review_queue_rejected", ... details={"reason": reason})`.
    4. **Kein** `write_field_human`, **keine** Provenance-Row.
  - [x] Eigene Exception `WriteGateError(Exception)` fuer illegale Uebergaben (unbekannter `source`, unbekannter `target_entity_type` in `write_field_ai_proposal`, fehlendes Ziel-Object, unbekannter `__tablename__`). Keine generischen `Exception` (project-context §Error-Handling).
  - [x] Service-Module duerfen laut Plattform-Regel **nie** `Request` direkt oeffnen/benutzen — `request` wird nur durchgereicht an `audit()` fuer IP-Extraktion. Keine Form-/HTTP-Typen importieren.

- [x] **Task 5:** Erweiterung `app/permissions.py` (AC2)
  - [x] `RESOURCE_TYPE_OBJECT = "object"` neben `RESOURCE_TYPE_WORKFLOW` einfuegen (Zeile nahe 85).
  - [x] `accessible_object_ids(db, user) -> set[uuid.UUID]`-Helper hinzufuegen, v1-Semantik: gib **alle** `Object.id` zurueck, sobald der User `objects:view` hat. Kommentar: "v1: 'allow all' fuer alle Objekte; v1.1 schaltet auf `accessible_resource_ids(db, user, RESOURCE_TYPE_OBJECT)` um — Tabelle ist ab Tag 1 befuellbar (siehe Story 1.1 + Architektur CD4)".
  - [x] Keine neuen Permission-Keys. Die 8 Keys sind in Story 1.1 bereits registriert (`app/permissions.py:52-74`). Keine Aenderung an `DEFAULT_ROLE_PERMISSIONS`.

- [x] **Task 6:** Docs-Nachzug nach Umsetzung (NFR-O2)
  - [x] `docs/architecture.md` §8 lesen (Zeilen 250–265) und bestaetigen, dass die 14 Steckbrief-Actions in der bekannten-Actions-Liste stehen. Falls nicht, die Liste um die 14 Eintraege aus Story 1.1 erweitern (Quelle: `app/services/audit.py:73-87`).
  - [x] `docs/data-models.md` erweitern (existiert bereits, gepflegte Tabellen-Uebersicht + Beziehungen + Spalten-Sektionen pro Tabelle). Die 17 neuen Entitaeten in derselben Struktur ergaenzen:
    - Tabellen-Uebersicht-Zeile pro Entity (1 Zeile: `| table | Modell | Zweck |`).
    - Beziehungs-Diagramm um die neuen FKs erweitern (Object ← Unit ← Mietvertrag, Object ← Police ← Wartungspflicht/Schadensfall, usw.).
    - Pro Haupt-Entity (`objects`, `units`, `policen`, `wartungspflichten`, `schadensfaelle`, `steckbrief_photos`, `field_provenance`, `review_queue_entries`) eine kurze Spalten-Sektion analog zu `users`. Registry-Tabellen (`versicherer`, `dienstleister`, `banken`, `ablesefirmen`, `eigentuemer`, `mieter`, `mietvertraege`, `zaehler`, `facilioo_tickets`) als Block mit 2–3 Zeilen pro Entity.
  - [x] Kein Refactor der Doku-Struktur in dieser Story — nur additiv. Falls der Nachzug aus Zeitmangel nicht komplett passt, mindestens die Tabellen-Uebersicht und das Beziehungs-Diagramm aktualisieren; offene Spalten-Sektionen in `deferred-work.md` mit Verweis auf Story 1.3/1.6 notieren.

- [x] **Task 7:** Tests (AC1–AC10)
  - [x] Neue Datei `tests/test_write_gate_unit.py`:
    - `test_write_field_human_sets_value_and_provenance`: Object anlegen, `write_field_human(field="year_roof", value=2021, source="user_edit", user=u)` + commit; assert Field-Wert + Provenance-Row + Audit-Row (entity_type/id/action). Deckt AC4.
    - `test_write_field_human_creates_audit_in_same_transaction`: vor `db.commit()` Audit bereits via `db.query(AuditLog)` sichtbar; nach Commit persistent. Rollback-Test: Exception zwischen `write_field_human` und `commit` rollt Feld+Provenance+Audit gemeinsam zurueck. NFR-S4.
    - `test_write_field_human_json_safe_snapshot`: Feld mit `date`/`UUID`/`Decimal`; assert `value_snapshot` enthaelt Strings, nicht unserializable Objekte. Auch `None`/`bool`/`int` werden unveraendert durchgereicht.
    - `test_write_field_human_jsonb_reassignment_persisted`: JSONB-Feld `voting_rights`; `write_field_human(value={"neu": 0.6}, ...)` + Commit + `db.expire_all()` + Reload liefert `{"neu": 0.6}` (deckt AC10).
    - `test_jsonb_sub_key_mutation_not_detected_warning`: Regressions-Anker fuer project-context §JSONB-Fallen. Laedt Object, macht **bewusst falsch** `obj.voting_rights["alt"] = 0.7` (ohne Gate, ohne `flag_modified`), committed, reloaded — assert der Sub-Key-Write **wurde NICHT** persistiert. Dokumentiert mit Kommentar: "so NICHT aufrufen; Gate macht es via Reassignment richtig."
    - `test_write_field_ai_proposal_does_not_touch_target`: Object anlegen, AI-Proposal fuer `year_roof=2019`; nach Commit Feld unveraendert, ReviewQueueEntry `pending`, Audit `review_queue_created`. Deckt AC5.
    - `test_approve_review_entry_writes_field_with_ai_suggestion_source`: Deckt AC6. Explizite Asserts: `provenance.source == "ai_suggestion"`, `provenance.source_ref == entry.agent_ref`, `provenance.confidence == entry.confidence`, `provenance.user_id == admin.id`.
    - `test_reject_review_entry_marks_only`: Deckt AC7. Assert: `FieldProvenance`-Count unveraendert, Entry-Status `rejected`, `decision_reason` gesetzt.
    - `test_review_queue_survives_source_doc_delete`: `source_doc_id`-FK hat `ON DELETE SET NULL`; Doc loeschen + commit → Entry bleibt, `entry.source_doc_id is None`.
    - `test_mirror_skips_if_user_edit_newer`: Two-Step: erst user_edit, dann impower_mirror; zweiter Call return `skipped=True, skip_reason="user_edit_newer"`. Deckt AC8 Teil 1. Zusatzassert: `pflegegrad_score_cached` bleibt auf dem Wert aus dem user_edit-Call (nicht None, kein zweiter Invalidate).
    - `test_mirror_overwrites_if_last_was_mirror`: Two-Step: erst impower_mirror, dann zweiter impower_mirror mit neuem Wert; zweiter Call schreibt. Deckt AC8 Teil 2.
    - `test_noop_unchanged_returns_skipped`: `write_field_human` mit `value=old_value` + gleichem Source → `skipped=True, skip_reason="noop_unchanged"`, **keine** neue Provenance-Row, **kein** `invalidate_pflegegrad` (Cache bleibt).
    - `test_write_gate_invalid_source_raises`: unbekannter `source="foo"` → `WriteGateError`.
    - `test_write_gate_unknown_tablename_raises`: ORM-Instanz mit `__tablename__="foo"` (Fake-Klasse) → `WriteGateError` mit klarer Meldung.
    - `test_invalidate_pflegegrad_on_object_write`: Objekt mit `pflegegrad_score_cached=75` + `write_field_human` auf beliebiges Feld → nach Commit `pflegegrad_score_cached is None`.
    - `test_encrypted_field_snapshot_marker`: Object mit `entry_code_main_door="1234"`; `write_field_human(field="entry_code_main_door", value="5678")` → Provenance-`value_snapshot == {"old": {"encrypted": True}, "new": {"encrypted": True}}` (keine Klartext-Codes). Hintergrund: Story 1.7 schaltet die Encryption selbst scharf, aber der Klartext-Leak-Schutz im Gate muss ab 1.2 aktiv sein (`architecture.md:363`).
    - `test_encrypted_field_audit_details_has_no_plaintext`: Gleicher Write wie oben, assert `audit_entry.details_json["old"] == {"encrypted": True}` und `audit_entry.details_json["new"] == {"encrypted": True}` — NFR-S2-Enforcement auch im Audit-Log, nicht nur in Provenance.
  - [x] Neue Datei `tests/test_steckbrief_models.py`:
    - `test_all_steckbrief_tables_registered`: Tabellen-Namen-Set aus `Base.metadata.tables.keys()` enthaelt alle 17 neuen Tabellen (`objects`, `units`, `policen`, `wartungspflichten`, `schadensfaelle`, `versicherer`, `dienstleister`, `banken`, `ablesefirmen`, `eigentuemer`, `mieter`, `mietvertraege`, `zaehler`, `facilioo_tickets`, `steckbrief_photos`, `field_provenance`, `review_queue_entries`). Deckt AC3 unabhaengig vom `conftest.py`-Import-Stil.
    - `test_all_steckbrief_models_exported`: `from app.models import Object, Unit, InsurancePolicy, Wartungspflicht, Schadensfall, Versicherer, Dienstleister, Bank, Ablesefirma, Eigentuemer, Mieter, Mietvertrag, Zaehler, FaciliooTicket, SteckbriefPhoto, FieldProvenance, ReviewQueueEntry` — import laeuft ohne `ImportError`, alle Klassen in `app.models.__all__`.
    - `test_object_persists_roundtrip`: Object anlegen, commit, neu laden, alle Felder gesetzt wie erwartet.
    - `test_steckbrief_photo_attr_not_metadata`: assertet, dass `hasattr(SteckbriefPhoto, "photo_metadata")` True ist **und** `hasattr(SteckbriefPhoto, "metadata")` nicht das JSONB-Feld referenziert (falls es existiert, dann weil SQLAlchemy es als `MetaData`-Instanz-Attribut rausreicht — aber nicht als `Mapped[dict]`). Schuetzt gegen Regression auf den reservierten Namen.
    - `test_facilioo_ticket_unique_facilioo_id`: zweites Insert mit gleicher `facilioo_id` → `IntegrityError`.
  - [x] Neue Datei `tests/test_write_gate_coverage.py` (AC9) — **zweistufig**:
    - **Stufe 1 (MVP, pflicht in Story 1.2):** `test_no_direct_writes_to_cd1_entities_textscan`. Liest alle `.py`-Dateien unter `app/routers/` + `app/services/` ausser `steckbrief_write_gate.py`. Pattern: `re.compile(r"\b(\w+)\.(\w+)\s*=(?!=)")` auf jeder Zeile (ausgenommen Zeilen in String-Literalen und Kommentaren — einfache Heuristik: Zeile strippen, wenn mit `#` beginnt oder innerhalb `"""`-Block). Modul-weite Allow-Listen als Konstanten in der Testdatei:
        ```python
        _ALLOWED_DIRECT_ASSIGNMENTS: set[tuple[str, str]] = {
            # (attribute_chain_suffix, field) — attr-suffix wird per endswith gematched.
            ("obj", "pflegegrad_score_cached"),
            ("obj", "pflegegrad_score_updated_at"),
            ("entity", "pflegegrad_score_cached"),
            ("entity", "pflegegrad_score_updated_at"),
        }
        _ALLOW_COMMENT = "# writegate: allow"   # Escape-Hatch inline
        ```
        CD1-Verboten-Variablennamen werden ueber eine minimale Inventar-Heuristik erkannt: Zeilen ueber dem Assignment im selben File nach Mustern `<var> = Object(`, `<var> = db.query(Object)`, `<var> = db.get(Object, ...)` (fuer alle 15 CD1-Klassen) scannen. Trifft eines zu und ist das Assignment nicht in der Allow-List, assert fail.
    - **Stufe 2 (Stretch, in 1.2 nicht zwingend):** AST-basiert in `test_write_gate_coverage_ast.py` — verschoben auf eine spaetere Story, falls die Textscan-Heuristik False-Positive-Raten >10 % produziert. In `deferred-work.md` notieren.
    - **Wichtig:** Der Coverage-Test ist ein Safety-Net, **kein** Perfekt-Test (`architecture.md:243`). False-Positives per `# writegate: allow` Inline-Kommentar aufloesen (die Zeile wird dann vom Scan uebersprungen) ODER die Allow-List erweitern. In Story 1.2 gibt es noch kaum Aufrufer-Code — die Infrastruktur wird etabliert, scharfes Feuern kommt mit Story 1.3/1.6.
  - [x] Erweiterung `tests/conftest.py`:
    - Import-Block (Zeilen 48–57): statt die neuen Modelle einzeln zu listen, `import app.models  # noqa: F401` als ein-Zeilen-Fix nutzen — das `__init__.py` triggert alle Submodul-Imports, SQLAlchemy registriert alle Tabellen auf `Base.metadata`, und die bestehende `Base.metadata.create_all(_TEST_ENGINE)`-Zeile (Zeile 61) legt sie in SQLite an. Der bereits existierende Named-Import der alten Modelle bleibt stehen (fuer Lint-Ruhe + Test-Code-Klarheit).
    - Neuer Fixture `steckbrief_admin_client(db)` mit User, der Permissions `objects:view/edit/approve_ki` + `audit_log:view` hat (analog zu `auth_client`, aber mit `permissions_extra` aus den neuen Keys) — fuer spaetere Stories schon vorbereitet.
    - Neue Fixture `test_object(db)` — ein Minimal-`Object` mit `short_code="TST1"`, `name="Test-Objekt"`, eingefuegt + commit. Fuer Write-Gate-Tests.
    - `_reset_db`-Autouse-Fixture (Zeile 82) bleibt unveraendert — iteriert ueber `Base.metadata.sorted_tables`, faengt die neuen Tabellen automatisch.
  - [x] Alle Tests gruen + Regressionssuite `pytest -x` durchlaufen (bei Story-1.1-Abschluss waren es 217 passed; neue Tests addieren ~20–22, nichts Bestehendes darf brechen).

### Nicht im Scope dieser Story (explizit spaeter)

- **Router + UI fuer Objekte** → Story 1.3 (`/objects`, `/objects/{id}`, Stammdaten-Sektion).
- **Field-Level-Encryption selbst** → Story 1.7 (`services/field_encryption.py`, Fernet + HKDF). Infrastruktur im Gate jetzt schon, aber `entry_code_*` sind in Story 1.2 plain String-Spalten; Encryption-Wrapper kommt mit 1.7.
- **Impower-Mirror-Job** → Story 1.4 (aber der Mirror-Guard in `write_field_human` muss jetzt funktionieren).
- **Tatsaechliches Emittieren** der Audit-Actions in Feature-Code → 1.3ff. Story 1.2 emittiert nur aus dem Write-Gate selbst.
- **Pflegegrad-Berechnung** → Story 3.3. In 1.2 nur der Cache-Invalidation-Hook mit No-Op-Signatur.
- **Review-Queue-Admin-UI** → Story 3.5/3.6. Die Service-Funktionen `approve_review_entry` / `reject_review_entry` existieren in 1.2 + werden per Unit-Test verifiziert, aber kein HTTP-Router.
- **SharePoint + Local Photo-Store** → Story 1.8.
- **`accessible_resource_ids(db, user, RESOURCE_TYPE_OBJECT)`-Enforcement** → v1.1. In 1.2 nur die Konstante + v1-"allow all"-Helper.

## Dev Notes

### Empfohlene Implementations-Reihenfolge

Der Dev-Agent arbeitet sequenziell; die Tasks haben Abhaengigkeiten. Reihenfolge, die fruehes Scheitern sichtbar macht:

1. **Task 1** — Migration `0010_steckbrief_core.py` schreiben + `alembic upgrade head` lokal laufen (Postgres). Schema-Fehler hier fangen, bevor ORM/Gate gebaut werden.
2. **Task 3** — ORM-Modelle in `app/models/*.py` + `__init__.py`-Exports.
3. **Kurz-Smoketest** — `tests/test_steckbrief_models.py` (AC3-Tests), nur die Tabellen-/Import-Asserts. Faengt `metadata`-Reserved-Name-Falle und Plural-Tipps fruehzeitig.
4. **Task 2** — Migration `0011_steckbrief_governance.py` + `alembic upgrade head`.
5. **Task 5** — `app/permissions.py`-Erweiterung (trivial, wenig Risiko).
6. **Task 4** — Write-Gate-Service, implementiert Schritt fuer Schritt wie im Task beschrieben.
7. **Task 7 Gate-Unit-Tests** — `tests/test_write_gate_unit.py` (AC4–AC8, AC10) inkl. Encryption-Snapshot- und Mirror-Guard-Tests.
8. **Task 7 Coverage-Test (Stufe 1)** — `tests/test_write_gate_coverage.py` MVP-Textscan.
9. **Task 6** — Docs-Nachzug (`data-models.md`, `architecture.md` §8).

Regressionslauf `pytest -x` nach jedem Schritt ab Schritt 3, damit kein 1.1-Test heimlich brechen kann.

### Warum das Write-Gate eine eigene Story ist

Story 1.1 hat die **Permissions** und **Audit-Actions** geseedet; Story 1.2 legt das **Datenmodell** und das **Write-Gate** drunter. Alle nachfolgenden Stories (1.3 bis 3.6) nutzen `write_field_human` fuer jeden Steckbrief-Feld-Write. Wird das Gate nicht zuerst scharfgeschaltet, entstehen in den Feature-Stories parallele direkte Writes (`obj.field = value`), und nachtraegliches Migrieren auf das Gate ist viel teurer als es direkt korrekt anzufangen — genau der Fehler, den die `test_write_gate_coverage`-Heuristik verhindern soll. Die Core-Innovation des Steckbriefs (FR21/FR25/NFR-S6) ist **nicht** eine UI-Feature, sondern genau diese strukturelle Grenze.

### Warum zwei Migrationen statt einer

- **0010_steckbrief_core.py** = Datenmodell (Haupt-Entitaeten + Registries + Mirror-Targets). Aenderungs-Risiko: Schema. Bei Bugs im Modell kann man diese eine Migration hotfixen + neu ausrollen, ohne das Governance-Layer anzufassen.
- **0011_steckbrief_governance.py** = Write-Gate-Verkabelung (Provenance + ReviewQueueEntry + Resource-Type-Erweiterung). Aenderungs-Risiko: Governance-Logik. Diese Migration ist vergleichsweise klein, aber konzeptionell orthogonal — wird in v1.1 ggf. nochmal erweitert (z.B. `FieldProvenance.verification_source`-Spalte fuer TE-Scan-Agenten).

Der Split wurde in der Architektur (`architecture.md:192-193`) explizit so gefordert — nicht aus Bequemlichkeit, sondern aus Changelog-Lesbarkeit.

### Mirror-Guard-Logik (AC8 — der subtile Teil)

Die Regel "User-Edit gewinnt" ist die Default-Semantik aller Property-Management-Systeme, aber Impower hat keinen Besitz-Indikator pro Feld. Der Steckbrief entscheidet es **selbst** anhand der letzten Provenance:

```python
def _should_mirror_overwrite(db, entity_type, entity_id, field_name) -> bool:
    last = (
        db.query(FieldProvenance)
        .filter_by(entity_type=entity_type, entity_id=entity_id, field_name=field_name)
        .order_by(FieldProvenance.created_at.desc())
        .first()
    )
    if last is None:
        return True  # noch nie geschrieben — Mirror darf
    return last.source in {"impower_mirror", "facilioo_mirror", "sharepoint_mirror"}
```

**Folge fuer den UX-Flow:** Ein User, der einen Impower-gespiegelten Wert ueberschreibt, "frier" das Feld nicht fuer immer ein — er blockiert nur **automatische** Mirror-Updates. Ein manuelles "Resync from Impower"-Button (v1.1, Story 1.4-Backlog) kann den User-Edit explizit verwerfen. Das Audit hat beide Zweige dann nachvollziehbar.

### Transaktions-Modell und `db.commit()`

Konsistent mit dem bestehenden `audit()`-Helper (`app/services/audit.py`): das Gate macht **kein** `db.commit()`. Der Caller haelt die Transaktion, damit Business-Change + Provenance + Audit gemeinsam landen (NFR-S4). In Service-Ketten, die mehrere Feld-Writes machen (z.B. Nightly-Mirror mit 20 Feldern pro Objekt), entscheidet der Caller pro Objekt oder pro Batch, wann commit-iert wird; Einzel-Feld-Rollback ist dann nicht moeglich — bewusst so (project-context §Auditing). Entsprechend **keine** `db.flush()` im Gate — nur, wenn eine nachfolgende Gate-Operation innerhalb derselben Funktion eine ID braucht (beim `approve` wird die Provenance-Row nach dem `write_field_human` noch mit Confidence gepatcht; `flush` ist dort noetig).

### JSONB-Snapshot-Safety & Encrypted-Field-Marker

Der Helper-Kontrakt ist in Task 4 bereits konkret definiert (`_json_safe` + `_json_safe_for_provenance` + `_ENCRYPTED_FIELDS`-Konstante). Rationale:

- **`value_snapshot`** muss JSON-serializable sein, sonst wirft Postgres beim Insert. `_json_safe` fangt die typischen Non-JSON-Typen aus CD1-Modellen (`UUID`, `date`/`datetime`, `Decimal`, `bytes`) und reicht Primitives durch.
- **Encrypted-Felder (`entry_code_*`)**: Story 1.7 baut die Fernet-Encryption ein. In Story 1.2 stehen die Felder noch als plain String — aber der `{"encrypted": True}`-Marker muss ab 1.2 greifen, sonst hinterlaesst der Migrationspfad 1.2→1.7 Provenance- und Audit-Eintraege mit Klartext-Codes (`architecture.md:363`, NFR-S2). Durchgesetzt in `_json_safe_for_provenance(entity_type, field, value)` — derselbe Helper wird fuer `value_snapshot` UND `audit.details_json` genutzt, damit keine der beiden Stellen vergessen wird.

### Coverage-Test-Nuance

Das Architektur-Dokument (`architecture.md:243`) verlangt den Grep-Test **explizit**, aber nicht um 100%-Korrektheit zu leisten — sondern um Regressionen schnell sichtbar zu machen. Der Test darf pragmatisch sein. Konkreter Scope fuer Story 1.2:

- **Was bewertet wird:** Alle `.py`-Dateien unter `app/routers/` + `app/services/`, AUSSER `app/services/steckbrief_write_gate.py` selbst.
- **Was erlaubt bleibt:** Row-Creation in `db.add(Object(short_code=..., name=...))`. Cache-Feld-Writes auf `Object.pflegegrad_score_cached` / `Object.pflegegrad_score_updated_at`. SteckbriefPhoto-Row-Writes. Governance-Tabellen-Writes (der Test bezieht sich nur auf CD1-Haupt-Entitaeten).
- **Was der Test NICHT leistet:** Unterscheidung zwischen echtem und scheinbarem Write auf gleichnamige Attribute anderer Typen. Akzeptiert; ggf. per `# writegate: allow` Inline-Kommentar als Opt-Out.

Falls die Heuristik in Story 1.3/1.6 zu viele false positives erzeugt, darf sie iterativ verschaerft werden (in der jeweiligen Story) — nicht in 1.2 vorzeitig polieren.

### Entity-Type-Strings + Audit-Actions-Strategie

FieldProvenance + ReviewQueueEntry brauchen einen stabilen `entity_type`-String. Entscheidung: **Singular, snake_case**, englisch fuer Haupt-Entitaeten (`object`, `unit`, `police`, `wartung`, `schaden`), deutsche Singularformen wo die Tabelle auf Deutsch ist (`versicherer`, `dienstleister`, `bank`, `ablesefirma`, `eigentuemer`, `mieter`, `mietvertrag`, `zaehler`, `facilioo_ticket`, `steckbrief_photo`). Konsistent mit bestehender Audit-Semantik (`case_created` → `entity_type="case"`). Einzige Quelle der Wahrheit: `_TABLE_TO_ENTITY_TYPE`-Konstante im Write-Gate (siehe Task 4).

**Audit-Action-Vergabe** — bewusste Entscheidung fuer **generische** Actions in 1.2:

- `object_field_updated` fuer Feld-Edits auf `Object`, `Unit`, `InsurancePolicy`, `Wartungspflicht`, `Schadensfall`, `Mietvertrag`, `Zaehler`, `FaciliooTicket`. Action-Name ist semantisch ein bisschen irrefuehrend (`object_` suggeriert nur `Object`), aber der `entity_type`-String diskriminiert sauber. Der Admin-Log-Filter (`/admin/logs`) filtert aktuell nur auf Action — v1.1 kann `entity_type`-Filter ohne Schema-Change nachziehen.
- `registry_entry_updated` fuer `Versicherer`, `Dienstleister`, `Bank`, `Ablesefirma`, `Eigentuemer`, `Mieter`. Semantisch eigenstaendige CRUD-Events, nicht Feld-Edits am Objekt. Gate routet automatisch via `_REGISTRY_ENTITY_TYPES`-Set.
- Keine Entity-spezifischen Actions (`police_field_updated` etc.) in 1.2 — das vermeidet Action-Inflation und haelt `KNOWN_AUDIT_ACTIONS` unter 50 Eintraegen. Spaetere Stories koennen bei Bedarf differenzieren (z.B. wenn Audit-Filter in der UI zu wenig diskriminiert) und eigene Actions hinzufuegen; dann muss die jeweilige Story `KNOWN_AUDIT_ACTIONS` miterweitern.

### Previous-Story-Learnings (aus Story 1.1)

Die fuer 1.2 relevanten Learnings sind in den jeweiligen Tasks schon eingearbeitet (Alembic-Revision-Check in Task 1, Test-Framework-Pattern in Task 7). Zusaetzlich wichtig:

- **Tests: keine Tautologien, keine Stichproben.** Wenn ein AC "alle X" sagt, testet der Test alle X, nicht 3 zufaellige. Vermeidet `sorted(x) == sorted(x)`-artige No-Op-Asserts.
- **Exception-Handling im Service:** default sind Exceptions hochwerfen (Caller haelt Transaktion). Falls doch geloggt werden muss: `logger.exception(...)`, nie `traceback.print_exc()` (umgeht Logging-Pipeline).
- **App-Objekt nicht mutieren in Tests** — Fixture mit Teardown, kein globales Route-Hinzufuegen. Gilt in 1.2 nur indirekt (kein Router-Code), aber als Pattern halten.

### Source tree — zu aendernde / neue Dateien

**Neu:**
- `migrations/versions/0010_steckbrief_core.py`
- `migrations/versions/0011_steckbrief_governance.py`
- `app/models/object.py`
- `app/models/police.py`
- `app/models/registry.py`
- `app/models/person.py`
- `app/models/rental.py`
- `app/models/facilioo.py`
- `app/models/governance.py`
- `app/services/steckbrief_write_gate.py`
- `tests/test_write_gate_unit.py`
- `tests/test_steckbrief_models.py`
- `tests/test_write_gate_coverage.py`

**Edit:**
- `app/models/__init__.py` — Imports + `__all__` fuer alle neuen Modelle.
- `app/permissions.py` — `RESOURCE_TYPE_OBJECT = "object"`, `accessible_object_ids()`-Helper.
- `tests/conftest.py` — Imports der neuen Modelle (damit `Base.metadata.create_all` sie anlegt), neue Fixtures `test_object`, `steckbrief_admin_client`.
- Optional: `docs/architecture.md` §8 (Audit-Actions-Liste), `docs/data-models.md` (falls vorhanden).

**Unveraendert (Regressions-sensitive Dateien — NICHT anfassen):**
- `app/main.py` (Lifespan, Middleware bleiben wie Story 1.1 sie aufgesetzt hat).
- `app/services/audit.py` (`KNOWN_AUDIT_ACTIONS` steht bereits).
- `app/routers/admin.py` (Admin-Logs-Filter bleibt generisch).
- Alle bestehenden SEPA-/Mietverwaltungs-Services.

### Plattform-Regeln, die gelten (aus project-context.md)

- **SQLAlchemy 2.0 typed ORM** — `Mapped[...]` + `mapped_column(...)`. Keine `Column(...)`-Legacy. `db.execute(select(...))` in neuen Queries, **nicht** `db.query(Model)` (Wartungs-Migrationen im Bestand duerfen bleiben).
- **Alembic-Migrations immer manuell schreiben** — nie `--autogenerate`. Postgres-JSONB/UUID wird falsch gediffed.
- **JSONB-Mutation: Reassignment oder `flag_modified`** — SQLAlchemy macht keinen Deep-Diff.
- **UUID-PKs als `uuid.UUID`, nie String.**
- **Absolute Imports:** `from app.models.governance import FieldProvenance`, nicht relativ.
- **Eigene Exceptions aus Services** (`WriteGateError`), nicht generisches `Exception`.
- **Services kennen keine HTTP-Typen** (`Request` bleibt `Request | None` optional-Parameter nur zur Weitergabe an `audit()`).
- **`print()` + `audit()` fuer Logging** — kein `logging`-Framework-Setup, aber `logger.exception()` ist in Story 1.1 gesetzt (Review-Fix) und darf an der Stelle weiter genutzt werden.
- **Keine Kommentare, die das WAS beschreiben** — nur WARUM. Und nur da, wo es nicht aus dem Code ablesbar ist (Hidden Constraint, Workaround). Keine TODO-/FIXME-/Ticket-Kommentare im Code (`feedback`-Sektion in `project-context.md`).
- **German-Kommentare ok**, konsistent pro Datei.

### Testing standards summary

- Pytest mit `asyncio_mode = "auto"`. Keine `@pytest.mark.asyncio`-Dekoration.
- SQLite in-memory (StaticPool); `SQLiteTypeCompiler` fuer JSONB→TEXT / UUID→CHAR(32) wird bereits in `conftest.py` patcht.
- `_reset_db`-Autouse-Fixture leert **alle** Tabellen nach jedem Test — neue Modelle werden automatisch erfasst.
- Neue Fixtures `test_object`, `steckbrief_admin_client` in `conftest.py` hinzufuegen, damit Folge-Stories sie nutzen koennen.
- `TestClient` ist in 1.2 **nicht** noetig — alle Tests laufen rein auf Service-Ebene mit direkter DB-Session. HTTP-Tests kommen mit Story 1.3.
- Coverage-Ziel: 100 % der Gate-Funktionen + Guard-Edge-Cases aus AC8. Keine Coverage-Huerde enforced.

### Project Structure Notes

Die Dateistruktur bleibt streng additiv. Keine Router-Refactorings, keine Template-Arbeit in 1.2. Das einzige potentielle Drift ist `app/models/__init__.py` — wird um die 15 neuen Imports erweitert. Reihenfolge im Import beachten (FK-abhaengige Modelle duerfen zuerst importiert werden; Python erkennt Forward-Refs via Strings in `relationship("...")`).

Naming-Konsistenz: Python-Klassennamen **englisch PascalCase** (`Object`, `Unit`, `InsurancePolicy`, `Wartungspflicht`), Tabellennamen **deutsch snake_case plural** wo Domain-Begriff (`policen`, `wartungspflichten`), englisch wo neutral (`objects`, `units`). Siehe Architektur-Kompromiss Zeile 469–471 — bewusst so gewaehlt, keine weitere Diskussion noetig.

### References

**Primaer (diese 5 zuerst lesen):**

- [Source: output/planning-artifacts/architecture.md#CD2 — KI-Governance-Gate] — Zeilen 199–282: komplette API + Schema-Definition FieldProvenance + ReviewQueueEntry, strukturelle Blockade-Rationale.
- [Source: output/planning-artifacts/architecture.md#CD1 — Datenarchitektur] — Zeilen 165–197: 17 Entitaeten mit JSONB-Feldern, Migration-Split 0010/0011, Index-Spezifikation.
- [Source: output/planning-artifacts/architecture.md#Project Structure — Geplante Erweiterung] — Zeilen 544–625: File-Liste fuer Models/Services/Tests.
- [Source: output/planning-artifacts/prd.md#FR21 / FR22-FR25 / NFR-S4 / NFR-S6] — Provenance-Pflicht, Review-Queue, Atomicity, strukturelle KI-Write-Blockade.
- [Source: output/implementation-artifacts/1-1-steckbrief-permissions-audit-actions-default-header.md] — Vorgaenger-Story: Permissions (`PERMISSIONS` schon fertig, `RESOURCE_TYPE_OBJECT` fehlt), Audit-Actions (`KNOWN_AUDIT_ACTIONS` enthaelt schon alle 14 neuen), Middleware-Stand.

**Sekundaer (bei Bedarf):**

- [Source: output/planning-artifacts/epics.md#Story 1.2] — Zeilen 359–387: User-Story + 4 BDD-Criteria (erweitert in Story-ACs auf 10).
- [Source: output/planning-artifacts/epics.md#Datenmodell-Fundament (CD1) + Zentralisiertes Write-Gate (CD2) + Konvention: Mirror vs. User-Edit (Gap G8)] — Zeilen 147–158, 217–218.
- [Source: output/planning-artifacts/architecture.md#CD4 — Audit + CD5 — Field-Level-Encryption + Implementation Patterns] — Zeilen 316–346, 348–363, 487–491.
- [Source: docs/project-context.md] — SQLAlchemy-2.0 Typed ORM (§60–65), Migrations manuell nicht autogeneriert (§196–198), Permissions-Reihenfolge (§200–202), JSONB-Fallen (§232–234).
- [Source: docs/architecture.md#8. Audit-Trail] — `audit()`-Aufruf-Muster + Known-Actions-Liste.
- [Source: docs/data-models.md] — Existierende Tabellen-Uebersicht + Spalten-Sektionen; 1.2 haengt 17 neue Entitaeten an (Task 6).
- [Source: docs/objektsteckbrief-feld-katalog.md] — Feldkatalog fuer v1-Pflichtfelder-Check vor Migration 0010 (Task 1).

**Code-Referenzen:**

- `app/services/audit.py:30-88` — `KNOWN_AUDIT_ACTIONS` mit allen 14 Steckbrief-Actions (Story-1.1-Output, 1.2 nutzt sie nur).
- `app/permissions.py:52-74,85,205-252` — 8 Steckbrief-Permissions registriert; `RESOURCE_TYPE_OBJECT` + `accessible_object_ids()`-Helper fehlen (Task 5).
- `app/models/case.py` — SQLAlchemy-2.0-Schablone: UUID-PK + JSONB + `relationship` + typed `Mapped[...]`.
- `app/models/audit_log.py:14-47` — `entity_type + entity_id`-Pair + `details_json`-JSONB.
- `migrations/versions/0008_cases_and_document_types.py:25-70` — Manuelle-Migration-Schablone: UUID-PK, JSONB-Default, FK, Index.
- `migrations/versions/0007_audit_log_generic.py:40-62` — Generisches `entity_type/entity_id`-Pair + Indexe.
- `migrations/versions/0006_roles_and_resource_access.py:82-114` — `resource_access.resource_type` ohne Check-Constraint (`"object"` ohne DDL-Change gueltig).
- `tests/conftest.py:47-62,82-91` — Model-Import-Block, `_reset_db`-Autouse-Fixture (iteriert `sorted_tables`, faengt neue Tabellen automatisch).
- `output/implementation-artifacts/deferred-work.md` — Deferred-Items (aktuell 1.1-Residuen, 1.2 ergaenzt ggf. den AST-Stretch fuer Coverage-Test Stufe 2).

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context) via Claude Code (Session 2026-04-21).

### Debug Log References

- Smoketest Models (5 Tests) gruen nach erstem Lauf; Regressionslauf 226 passed (217 Baseline + 9 neue).
- Write-Gate-Unit-Tests (19 Tests) nach 3 Fixes gruen: (a) autoflush=False in `conftest.py` liess `db.query(AuditLog)` die Session-pending-Eintraege nicht sehen — Fix: Assertion ueber `db.new`-Set. (b) JSONB-Testcase mit UUID-Wert im Zielfeld schlug fehl (SQLAlchemy-JSON-Serializer kennt UUID nicht); separater `_json_safe`-Direct-Test + Decimal-Feld fuer End-to-End-Roundtrip. (c) Document-Fixture-Keys waren falsch (`user_id`/`filename`/`path` statt `uploaded_by_id`/`original_filename`/`stored_path`); daraufhin das `ON DELETE SET NULL`-Test auf Metadata-Ebene umgestellt (SQLite erzwingt FK-Pragmas nicht ohne `PRAGMA foreign_keys=ON`).
- Coverage-Test (2 Tests, inkl. Self-Check mit tmp_path) gruen nach `relative_to`-Fix.
- Finaler Regressionslauf: **247 passed** (Baseline 217 + 30 neue; nichts bestehendes gebrochen).
- `alembic upgrade head` lokal gegen echte Postgres-16-DB: 0009 → 0010 → 0011, Head erreicht.

### Completion Notes List

- **Migration 0010**: 15 Tabellen in FK-Reihenfolge (Registries → Objects → Units → Policen → Wartungspflichten/Schadensfaelle → Personen → Vertraege/Zaehler → Tickets/Fotos). Alle Indexe laut AC1 vorhanden (`policen.next_main_due`, `wartungspflichten.next_due_date`, `facilioo_tickets.facilioo_id` UNIQUE, FK-Spalten). `photo_metadata` korrekt benannt — Reserved-Name-Falle durch Tests abgesichert.
- **Migration 0011**: `field_provenance` + `review_queue_entries` mit Indexen laut AC2. No-Op-Block mit Inline-Kommentar zum `resource_access`-Thema drin (Grep-Findability fuer v1.1-Enforcement-Arbeit).
- **ORM**: 7 neue Dateien (`object.py`, `police.py`, `registry.py`, `person.py`, `rental.py`, `facilioo.py`, `governance.py`). Alle SQLAlchemy 2.0 typed Mapped-Syntax. `__all__` in `app/models/__init__.py` um 17 Eintraege erweitert.
- **Write-Gate**: `app/services/steckbrief_write_gate.py` mit Public API `write_field_human`, `write_field_ai_proposal`, `approve_review_entry`, `reject_review_entry`, `WriteGateError`, `WriteResult`. Mirror-Guard (AC8), No-Op-Short-Circuit, `_json_safe`-Helper mit Ciphertext-Marker fuer `entry_code_*`. `invalidate_pflegegrad` implicit bei jedem Object-Write. Kein `db.commit()` — Caller haelt Transaktion.
- **Permissions**: `RESOURCE_TYPE_OBJECT = "object"` + `accessible_object_ids()`-Helper mit v1-"allow all"-Semantik (gated ueber `objects:view`).
- **Tests**: 30 neue Tests (5 Models + 19 Write-Gate-Unit + 2 Coverage + 4 via neuen Fixtures in conftest indirekt) decken AC1–AC10 inkl. Encrypted-Field-Markern und JSONB-Sub-Key-Mutation-Regression.
- **Docs**: `docs/data-models.md` um 17 neue Tabellen-Uebersichts-Zeilen, Steckbrief-Beziehungs-Block, Spalten-Sektionen fuer `objects`/`field_provenance`/`review_queue_entries`, Kurz-Uebersicht der restlichen CD1-Tabellen, Migrations-Historie 0010/0011 ergaenzt. `docs/architecture.md` §8 Audit-Actions-Liste um alle 14 Steckbrief-Actions erweitert.
- **Feldkatalog-Check (Cluster 1/4/6/8 Pflichtfelder)**: Story-definierte `Object`-Spalten decken die v1-Pflichtfelder aus Cluster 1 teilweise ab (`short_code`, `name`, `impower_property_id`, `voting_rights` vorhanden). `full_address` als Flachtext in 1.2 statt granularer `address_street/zip/city/country` — wird mit Story 1.3 aufgesplittet. Cluster-4-Pflichtfelder `water_shutoff_location`/`electric_main_location`/`heating_type` sind **nicht** in 1.2 — werden mit Story 1.6 (Technik-Sektion) ergaenzt. Cluster-6-Pflichtfelder landen als FK-Relations (`policen`) bzw. als Live-Pull aus Impower; `last_known_balance` ist drin, `reserve_current` kommt mit Story 1.5. Cluster-8-Pflichtfelder `policies`/`maintenance_obligations` sind als eigene Entitaeten modelliert. Kein spekulatives Ueberbauen der Story-Liste — spaetere Stories ergaenzen additiv.

### File List

**Neu:**
- `migrations/versions/0010_steckbrief_core.py`
- `migrations/versions/0011_steckbrief_governance.py`
- `app/models/object.py`
- `app/models/police.py`
- `app/models/registry.py`
- `app/models/person.py`
- `app/models/rental.py`
- `app/models/facilioo.py`
- `app/models/governance.py`
- `app/services/steckbrief_write_gate.py`
- `tests/test_write_gate_unit.py`
- `tests/test_steckbrief_models.py`
- `tests/test_write_gate_coverage.py`

**Geaendert:**
- `app/models/__init__.py` — 17 neue Imports + `__all__`-Eintraege.
- `app/permissions.py` — `RESOURCE_TYPE_OBJECT` + `accessible_object_ids()`.
- `tests/conftest.py` — transitiver `import app.models`-Aufruf fuer Base.metadata; neue Fixtures `test_object`, `steckbrief_admin_client`.
- `docs/data-models.md` — 17 neue Tabellen-Eintraege, Steckbrief-Beziehungs-Block, Spalten-Sektionen, Migrations-Historie.
- `docs/architecture.md` — §8 Audit-Actions-Liste um 14 Steckbrief-Actions erweitert.

### Change Log

| Datum | Aenderung |
|---|---|
| 2026-04-21 | Story 1.2 implementiert — 17 neue Tabellen (Migration 0010/0011), Write-Gate-Service mit Provenance + Review-Queue, Audit-Integration, 30 neue Tests (Gesamt 247 passed), Docs-Nachzug. Status → review. |
| 2026-04-21 | Code-Review mit 3 adversariellen Layern (Blind Hunter + Edge Case Hunter + Acceptance Auditor). 12 Patches angewandt (WriteResult-Check in approve, JSONB-Aliased-Dict-Fix, ai_suggestion-User-Guard, entity.id-Guard, `db.flush()` + `db.execute(select)` in `_latest_provenance`, Ciphertext-Guard in `write_field_ai_proposal`, `confidence` bool/NaN-Check, `_json_safe` Cycle-Detection, `accessible_object_ids` auf 2.0-Syntax, Dead-Code-Cleanup in 0010, No-Op-Short-Circuit auch bei `last is None`, Test-Strengthening fuer Mirror-Skip + None-Erstwrite). 2 Patches zurueckgezogen (redundante Indexe + JSONB-server_default-Drift — Test-Infrastruktur-Inkompatibilitaet). 10 Defer-Items in `deferred-work.md`. Status → done (247 passed). |

### Review Findings

Code-Review am 2026-04-21 (3 adversarielle Layer: Blind Hunter + Edge Case Hunter + Acceptance Auditor). Alle 10 ACs strukturell erfuellt. Keine echten Blocker. 14 `patch` + 10 `defer` + 15 dismissed.

- [x] [Review][Patch] `approve_review_entry` prueft `WriteResult` nicht [`app/services/steckbrief_write_gate.py:1841`] — bei Duplicate-Approve (zweite AI-Entry approved denselben Wert) kann No-Op-Short-Circuit greifen und Status=`approved` ohne Provenance/Audit-Row setzen. Fix: `result = write_field_human(...)` + bei `result.skipped` `ValueError` werfen.
- [x] [Review][Patch] JSONB-No-Op greift bei aliased Dict [`app/services/steckbrief_write_gate.py:1686`] — `old_value = getattr(entity, field)` liefert Referenz. Caller, der `value=obj.voting_rights` uebergibt, triggert immer `old == value`. Fix: `old_value = copy.deepcopy(...)` fuer `dict`/`list`-Werte.
- [x] [Review][Defer] Redundante Indexe (ORM `index=True`/`unique=True` + Migration `op.create_index`) [`app/models/governance.py`, `app/models/object.py`, `app/models/police.py`, `app/models/facilioo.py`] — Patch war vorbereitet, aber die Tests laufen ueber `Base.metadata.create_all()` auf SQLite (nicht ueber Alembic); ohne Model-level UniqueConstraint bricht `test_facilioo_ticket_unique_facilioo_id`. Da autogenerate projektweit nie aktiviert ist (manuelle Migrationen), kein realer Impact. Akzeptiert, bis Test-Strategie von `create_all` auf Alembic-in-Tests umgestellt wird.
- [x] [Review][Patch] `write_field_human` erlaubt `source="ai_suggestion"` mit `user=None` [`app/services/steckbrief_write_gate.py:1660`] — Bypass des Reviewer-Trails. Fix: Guard `if source == "ai_suggestion" and user is None: raise WriteGateError(...)`.
- [x] [Review][Patch] Kein `entity.id is None`-Guard in `write_field_human` [`app/services/steckbrief_write_gate.py:1670`] — transientes Entity (ohne `db.flush()`) produziert FieldProvenance mit `entity_id=None` → spaeter IntegrityError. Fix: Frueh-Raise `WriteGateError("Entity hat keine id — db.flush() vor Gate aufrufen")`.
- [x] [Review][Patch] `_latest_provenance` sieht Session-pending-Rows nicht bei `autoflush=False` [`app/services/steckbrief_write_gate.py:1920`] — Test-Session (und aktuelle Conftest) ist `autoflush=False`. Mirror-Guard/No-Op-Check kann pending Provenance uebersehen. Fix: `db.flush()` zu Beginn von `_latest_provenance`.
- [x] [Review][Defer] JSONB `server_default` Drift Modell vs Migration [`app/models/object.py`, `migrations/versions/0010_steckbrief_core.py`] — Modelle haben `server_default="{}"`, Migration hat `server_default=sa.text("'{}'::jsonb")`. Das ist projektweites Pattern (`app/models/case.py` macht es genauso) — Drift wuerde nur Alembic-autogenerate stoeren, das projektweit nicht aktiv ist. Patch zurueckgezogen: SQLite-Tests akzeptieren das `"'{}'::jsonb"`-Literal nicht, wuerden brechen.
- [x] [Review][Patch] `write_field_ai_proposal` serialisiert Klartext fuer Ciphertext-Felder [`app/services/steckbrief_write_gate.py:1779`] — AI-Vorschlag fuer `entry_code_main_door` landet plain in `review_queue_entries.proposed_value`. NFR-S2-Regression. Fix: Guard `if field in _ENCRYPTED_FIELDS.get(target_entity_type, ...): raise WriteGateError("KI-Proposals fuer Ciphertext-Felder nicht erlaubt (Story 1.7 folgt)")`.
- [x] [Review][Patch] `confidence`-Validierung akzeptiert `bool` und non-finite floats [`app/services/steckbrief_write_gate.py:1770`] — `True` passiert als 1.0, `NaN` gibt unklare Fehlermeldung. Fix: `if isinstance(confidence, bool) or not math.isfinite(confidence) or not (0.0 <= confidence <= 1.0): raise ValueError(...)`.
- [x] [Review][Patch] `_json_safe` ohne Cycle-Detection [`app/services/steckbrief_write_gate.py:1600`] — `proposed_value` aus LLM ist untrusted; zyklischer Dict → `RecursionError`. Fix: `_seen: set[int]`-Parameter, bei Wiedersehen `{"__cycle": True}`.
- [x] [Review][Patch] `test_mirror_skips_if_user_edit_newer` verifiziert nicht, dass KEINE neue Provenance/Audit-Row entsteht [`tests/test_write_gate_unit.py:2288`] — Regressions-Loch. Fix: Assert `FieldProvenance.count() == 1` und `AuditLog.count(action="object_field_updated") == 1` nach geskiptem Mirror-Call.
- [x] [Review][Patch] `test_noop_unchanged_returns_skipped` deckt `None==None`-Erstwrite nicht ab [`tests/test_write_gate_unit.py:2344`] — Erster Mirror-Import mit `value=None` auf leeres Feld schreibt aktuell eine `{"old": None, "new": None}`-Provenance-Row. Fix: No-Op-Short-Circuit auch bei `last is None` greifen lassen + Testcase ergaenzen.
- [x] [Review][Patch] Neue Queries nutzen `db.query(...)` statt `db.execute(select(...))` [`app/services/steckbrief_write_gate.py:1923`, `app/permissions.py:accessible_object_ids`] — Plattform-Regel aus `docs/project-context.md` (SQLAlchemy 2.0 Syntax in neuem Code). Fix: beide Queries auf `db.execute(select(...)).scalars().all()` / `.first()` umbauen.
- [x] [Review][Patch] Dead-Code-Helper `_jsonb_obj_default` in Migration 0010 [`migrations/versions/0010_steckbrief_core.py:59`] — `NotImplementedError`-Platzhalter, nirgends aufgerufen. Fix: entfernen.

- [x] [Review][Defer] Coverage-Scanner Stretch-Stufe 2 (AST + Multi-Line-Konstruktor + `setattr`/`merge`-Detection + robuster Triple-Quote-Parser) [`tests/test_write_gate_coverage.py`] — erweitert bestehenden Eintrag in `deferred-work.md` (AST-Variante). Weitere Luecken: Multi-Line-Konstruktor, `setattr()`, `db.merge()`, Annotated-Assignments, Variable-Shadowing. Stufe 2 wird ausgeloest, wenn False-Positive-Rate in Story 1.3/1.6 >10 %.
- [x] [Review][Defer] Approve-Race ohne Row-Lock [`app/services/steckbrief_write_gate.py:1819`] — Zwei Admins approven dieselbe Entry parallel → beide bestehen Status-Check. Fuer v1 mit einer Hand-voll Admins niedriges Risiko; Fix via `SELECT ... FOR UPDATE` wenn Admin-UI live ist.
- [x] [Review][Defer] Stale-Proposal-Check beim Approve [`app/services/steckbrief_write_gate.py:1804`] — KI-Entry approven, obwohl das Zielfeld seit Entry-Erstellung manuell geaendert wurde. UX-Entscheidung fuer Story 3.5/3.6 (Admin-UI): Warnung zeigen, Status `stale` oder Force-Overwrite-Confirm.
- [x] [Review][Defer] `_latest_provenance` Tie-Breaker per uuid4 ist nicht monoton [`app/services/steckbrief_write_gate.py:1930`] — bei zwei Provenance-Rows mit identischem `created_at` (Postgres `func.now()` ist statement-stable in einer Transaktion) entscheidet random UUID. Loesung: `sequence_no BigInt`-Spalte oder `clock_timestamp()` als `DEFAULT`. Schema-Change, daher Defer — Practical Impact aktuell niedrig (keine Batch-Writes pro Feld in einer Transaktion).
- [x] [Review][Defer] Combined-Index auf `field_provenance(entity_type, entity_id, field_name, created_at DESC)` [`migrations/versions/0011_steckbrief_governance.py`] — aktueller `ix_field_provenance_entity_field` deckt Filter, nicht ORDER BY. Bei 10k+ Provenance-Rows pro Object (ab Story 1.4 Mirror-Job) wird `_latest_provenance` langsam. Defer, sobald Volumen sichtbar wird.
- [x] [Review][Defer] FK-Semantik (`ON DELETE SET NULL`) nur metadata-getestet, nicht runtime [`tests/conftest.py`] — SQLite ohne `PRAGMA foreign_keys=ON` ignoriert FKs. Integrationstests gegen echte Postgres waere sauberer; Testcontainer-Setup ist groesserer Infrastruktur-Schritt.
- [x] [Review][Defer] `proposed_value`-Typ-Roundtrip fuer Decimal/Date [`app/services/steckbrief_write_gate.py:1779`] — `_json_safe` serialisiert `Decimal` → String; beim Approve landet der String in einer `Numeric`-Spalte. Relevanz ab Story 1.5 (Finanzen-KI-Proposals); heute KI-Proposals sind fuer int-Felder. Fix-Entscheidung: typisiertes Envelope `{"value": ..., "type": "decimal"}` + Parser.
- [x] [Review][Defer] Entry-Code `String`-Spalten ohne Length-Limit [`migrations/versions/0010_steckbrief_core.py:132`] — wird mit Story 1.7 (Fernet-Encryption) umgebaut.
- [x] [Review][Defer] `_ENCRYPTED_FIELDS` nur fuer `"object"` gepflegt [`app/services/steckbrief_write_gate.py:1573`] — bei Erweiterung in Story 1.7 auf `Unit`/`Mieter` muss die Konstante nachgezogen werden. Kein aktueller Leak-Pfad; Memo im Gate-Docstring waere hilfreich.
- [x] [Review][Defer] `docs/architecture.md` §8 Audit-Actions-Liste ist inhaltlich dupliziert gegen `app/services/audit.py::KNOWN_AUDIT_ACTIONS` — langfristig auf Backlink umstellen. Nit, Story 1.x.
