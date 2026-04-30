---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
status: 'complete'
completedAt: '2026-04-21'
lastStep: 8
inputDocuments:
  - output/planning-artifacts/prd.md
  - docs/architecture.md
  - docs/project-context.md
  - docs/project-overview.md
  - docs/data-models.md
  - docs/api-contracts.md
  - docs/component-inventory.md
  - docs/source-tree-analysis.md
  - docs/deployment-guide.md
  - docs/development-guide.md
  - docs/index.md
  - docs/objektsteckbrief-feld-katalog.md
  - docs/brainstorming/objektsteckbrief-2026-04-21.md
  - CLAUDE.md
workflowType: 'architecture'
project_name: 'Dashboard KI-Agenten'
user_name: 'Daniel Kroll'
date: '2026-04-21'
topic: 'Objektsteckbrief v1 — Architekturentscheidungen'
---

# Architecture Decision Document — Objektsteckbrief v1

_Brownfield-Extension der bestehenden Dashboard-KI-Agenten-Plattform. Dieses Dokument beschreibt ausschliesslich die architekturrelevanten Entscheidungen fuer das Objektsteckbrief-Modul (v1). Plattform-Regeln, Stack-Versionen und Conventions kommen aus `docs/project-context.md` und `docs/architecture.md` (Bestand) und werden hier nur referenziert, nicht dupliziert._

---

## Project Context Analysis

### Requirements Overview

**Functional Requirements (34 FRs in 6 Capability-Areas):**

- **Objekt-Detail & Cluster-Pflege (FR1–FR10):** Detailseite mit Cluster 1/4/6/8, strukturierte Sektionen, Foto-Upload nach SharePoint, Zugangscodes verschluesselt, Menschen-Notizen admin-only, Schadensfall-Anlage aus Objekt-Kontext.
- **Portfolio-Navigation & Due-Radar (FR11–FR15):** Sortier-/filterbare Liste (mobile fallback auf Cards), portfolio-weite Ablauf-Ansicht ueber Policen/Wartungspflichten/Vertraege, Filter nach Typ + Schwere, Deep-Links in Quell-Entitaeten und Registries.
- **Registries & Aggregationen (FR16–FR18):** Versicherer-Liste + Detailseite mit Aggregationen (Policen-Anzahl, Gesamtpraemie, Schadensquote, Ablauf-Heatmap); weitere Registry-Tabellen (Dienstleister, Bank, Ablesefirma, Eigentuemer, Mieter, Mietvertrag, Zaehler, FaciliooTicket) als normalisierte Entitaeten mit Objekt-FKs bereits v1 angelegt, Detailseiten v1.1.
- **Datenqualitaet & KI-Governance (FR19–FR25):** Pflegegrad-Score mit transparenter Komposition, `FieldProvenance` fuer jeden Write, `ReviewQueueEntry` fuer KI-Vorschlaege, strukturelles Enforcement gegen direkte KI-Writes.
- **Externe Integrationen & Sync (FR26–FR30):** Impower-Nightly-Mirror fuer Cluster 1/6, Live-Pull fuer Bank-Saldo, Facilioo-1-Min-Ticket-Poll mit Delta-Support, SharePoint-Graph-Foto-Upload (nur `drive_item_id` lokal), Stale-Toleranz bei externer Unerreichbarkeit.
- **Zugriff, Rollen & Audit (FR31–FR34):** Bestehendes OAuth-Hosted-Domain-Gate, neue Permissions `objects:*` + `registries:*`, Audit-Log fuer alle Steckbrief-Schreibaktionen mit Filter-Erweiterung.

**Non-Functional Requirements:**

- **Performance:** Objekt-Detail P95 < 2 s inkl. Live-Saldo (Headroom 150 Objekte), Liste < 1.5 s, HTMX-Swaps < 500 ms, Due-Radar < 2 s, Foto-Upload < 5 s.
- **Security:** OAuth `@dbshome.de`, TLS ueber Elestio, Zugangscodes HKDF-verschluesselt at-rest (nie im Log), atomare Transaktion Business-Change + AuditLog, Menschen-Notizen serverseitig admin-only, KI-Writes ohne ReviewQueueEntry strukturell blockiert + als `policy_violation` auditiert, `X-Robots-Tag: noindex, nofollow` default.
- **Reliability:** 99 % App-Verfuegbarkeit (30-Tage-Window), Stale-Snapshot bei Externe-Ausfaellen (keine 500er), Mirror-Jobs toleranz-fortsetzbar, BackgroundTasks mit eigener `SessionLocal()` + `try/finally`.
- **Integrations:** Impower 120 s Timeout + 5xx-Exponential-Backoff + 0.12 s Rate-Gate, Facilioo aequivalent gehaertet (min. 30 s Timeout, 1 req/s default), SharePoint OAuth-Client-Credentials + Token-Refresh + 429-`Retry-After`, Anthropic-Fehler = `ai_suggestion_failed` ohne User-Impact, HTML-Error-Bodies sanitisieren.
- **Observability:** 100 % Provenance-Abdeckung, bekannte Action-Liste in `docs/architecture.md` §8 nachziehen, BackgroundTask-Logging + Fehler-Audit, Pflegegrad-Score deterministisch aus DB rekonstruierbar.
- **Skalierung:** 50 Objekte / 7 User / ~10k Audit-Entries-Monat v1, Headroom 150 Objekte / 15 User ohne Architektur-Umbau, kein Caching-Layer v1 (aber auch nicht ausgeschlossen).

### Scale & Complexity

- **Primaere Domaene:** Web-App (MPA server-rendered) + Integration-Backbone + KI-Governance-Plattform-Primitiv.
- **Komplexitaetsstufe:** **medium–high** — nicht durch Volumen oder Regulierung, sondern durch vier aktive Integrationen (davon zwei NEU: Facilioo + SharePoint), normalisiertes Portfolio-Datenmodell mit ~16 neuen Entitaeten und das Review-Queue-/Provenance-Primitiv als erzwungener Gate-Layer.
- **Geschaetzte architekturelle Komponenten:** 2 neue Router (`objects`, `registries`), ~8 neue Services (`steckbrief_write_gate`, `steckbrief_impower_mirror`, `facilioo`, `facilioo_mirror`, `sharepoint_graph`, `pflegegrad`, `review_queue`, `due_radar`), ~16 neue ORM-Modelle, 2–3 neue Alembic-Migrations, ~8 neue Permission-Keys, ~12 neue Audit-Actions.

### Technical Constraints & Dependencies

**Harte Plattform-Constraints** (aus `docs/project-context.md`, nicht verhandelbar):

- Python 3.12, SQLAlchemy 2.0 typed `Mapped[...]`, Alembic handgeschrieben (kein `--autogenerate`).
- FastAPI + Jinja2 + HTMX 2 + Tailwind CDN — kein npm, kein SPA, kein neuer Build-Step.
- Postgres 16 mit JSONB + UUID-PKs; Tests gegen SQLite-in-Memory via Monkey-Patch.
- Impower-Client ausschliesslich ueber `app/services/impower.py`; Rate-Gate + Retry + Field-Stripping nicht umgehen.
- Claude: `messages.create`, nie `.parse`. IBAN-Guard (Unicode-NFKC + `isalnum` + `schwifty`) an **jedem** LLM-Output-Pfad.
- Template-Response immer `templates.TemplateResponse(request, ...)` (Request first).
- BackgroundTasks immer mit eigener `SessionLocal()` + `try/finally`; `asyncio.run(...)` nur am Task-Einstieg.
- `audit()` vor `db.commit()`, gleiche Transaktion wie Business-Change.
- JSONB-Mutation nur via Reassignment oder `flag_modified`.
- Permission-Keys **zuerst** in `PERMISSIONS` registrieren, dann an Handler binden.

**Externe Abhaengigkeiten (mit Risiko):**

- Facilioo-API (NEU) — Swagger/Auth/Delta-Support zu klaeren; **Tag-3-Go/No-Go**, Fallback: Cluster-3.3 auf v1.1.
- SharePoint Graph-API (NEU) — **M365-Admin-Ticket Tag 1**, Fallback: lokaler `uploads/`-Ordner.
- Impower Read-API (bestehend) — Spring-Data-Paging, Live-Latenzen bis 60 s, transiente 503 Gateway-Errors sind normal.
- Anthropic (v1 nur Review-Queue-Infra, erste KI-Vorschlaege v1.1) — AVV geklaert, DSFA-Light offen.

**Ressourcen-Constraints:** 1 Entwickler, 9 Tage (2026-04-22 bis 2026-04-30), parallele Wartung M3/M5 (Prod-Fix > v1-Feature).

### Cross-Cutting Concerns

1. **KI-Governance-Gate** (Review-Queue + FieldProvenance als gemeinsames Write-API).
2. **Sync-Orchestrierung** ueber drei Modi (Nightly-Mirror, 1-Min-Poll mit Delta, Live-Pull beim Render).
3. **Object-Level-ACL-Vorbereitung** (`resource_access.resource_type="object"` ab Tag 1 schreiben, Enforcement v1 "allow all").
4. **Field-Level-Encryption-Framework** (HKDF aus `SECRET_KEY` + `key_id`-Spalte, rotation-freundlich).
5. **Due-Radar als Quer-Query** ueber Police/Wartungspflicht/Vertrag (einheitliches `next_due_date` + `due_severity`-Helper).
6. **Audit-Trail-Erweiterung** (neue Actions + Filter-Hooks).
7. **Foto-Pipeline** mit zwei Implementierungen hinter `PhotoStore`-Interface (Graph / Local).
8. **Pflegegrad-Score als Service** (deterministisch, aus DB rekonstruierbar, strukturierte Komposition fuer UI-Erlaeuterung).
9. **Responsive Design fuer Notfall-Journey (J2)** — ein Template-Set, Card-Fallback auf Mobile.

---

## Starter Template Evaluation

### Entscheidung: Kein Starter

Das Projekt ist eine **Brownfield-Extension** eines produktiven Python-Monolithen (FastAPI + Jinja2 + HTMX, Python 3.12, Postgres 16, SQLAlchemy 2.0, Alembic, Anthropic + Impower + Authlib). Die Tech-Entscheidungen sind im Bestand getroffen und durch `docs/project-context.md` verbindlich festgeschrieben. Ein Starter-Template ist nicht anwendbar — es gaebe keinen, der den bestehenden Stack + Patterns + 8 laufende Alembic-Migrations + Platform-Core (Auth, Permissions, Audit, Impower-Client) ersetzen koennte ohne Regressionen.

### Bestaetigung der geerbten Plattform-Entscheidungen

| Dimension | Entscheidung (geerbt) | Quelle |
|---|---|---|
| Runtime | Python 3.12 | `pyproject.toml:requires-python` |
| Web-Framework | FastAPI ≥0.115 + Uvicorn `[standard]` | Bestand |
| Rendering | Jinja2 ≥3.1 + HTMX 2 + Tailwind (CDN) | Bestand, kein npm |
| ORM | SQLAlchemy 2.0 typed `Mapped[...]` + `psycopg[binary]` 3.2 | Bestand |
| Migrations | Alembic ≥1.14 handgeschrieben | Bestand |
| DB | Postgres 16 (JSONB + UUID) | Bestand |
| Auth | Authlib ≥1.3 + Starlette SessionMiddleware + Google OAuth `@dbshome.de` | Bestand |
| Settings | Pydantic-Settings ≥2.6 in `app/config.py` | Bestand |
| LLM | Anthropic SDK ≥0.40, `messages.create`, Opus 4.7 Extract / Sonnet 4.6 Chat | Bestand |
| IBAN | `schwifty` ≥2024.1 | Bestand |
| Deployment | Docker Compose + GHCR + Elestio Auto-Deploy | Bestand |
| Tests | Pytest ≥8.0 + pytest-asyncio, SQLite-In-Memory mit TypeCompiler-Monkey-Patch | Bestand |

### Zusaetzliche Libraries fuer v1

Nur drei neue Dependencies — alle etabliert, nicht experimentell. Versionen werden im Dependency-PR anhand `pip index` bzw. PyPI-Latest festgenagelt, da keine Web-Verifizierung erforderlich ist.

- **`cryptography` (≥43)** — fuer `Fernet` + HKDF-Schluesselableitung fuer Zugangscodes (NFR-S2). Bereits Transitive-Dep von `authlib`, wird als direkte Dep deklariert.
- **`msal` (≥1.28)** — Microsoft Authentication Library fuer SharePoint-Graph-Client-Credentials-Flow. Alternativ: manueller OAuth2-Client-Credentials-Call mit httpx — wird nur dann eingefuehrt, wenn `msal`-Footprint als zu gross empfunden wird. Default-Entscheidung: `msal` (battle-tested).
- **Keine neue Library fuer Facilioo** — der bestehende `httpx`-Stack (Impower-Client-Muster) wird wiederverwendet.

**Entscheidung:** Keine weitere Library-Einfuehrung fuer v1. Insbesondere **kein Redis/Celery** (BackgroundTasks reichen), **kein Alembic-Autogenerate** (Plattform-Regel), **kein separates Logging-Framework** (Plattform-Regel: `print` + `audit()`), **kein Client-JS-Framework** (Plattform-Regel: HTMX-only).

**Hinweis:** Projekt-Initialisierung entfaellt — die erste Implementierungs-Story ist stattdessen `docs/story-1-migration-and-models.md` (siehe Abschnitt "Naechste Schritte").

---

## Core Architectural Decisions

### Decision Priority Analysis

**Critical (blockieren Implementation):**

- CD1: Datenmodell der ~16 neuen Entitaeten
- CD2: KI-Governance-Gate-Design (Write-Pfad + Review-Queue)
- CD3: Sync-Orchestrator-Design (drei Modi)
- CD4: Permission- und Audit-Erweiterung
- CD5: Encryption-Framework fuer Zugangscodes

**Important (formen die Architektur):**

- ID1: Foto-Pipeline-Interface (SharePoint/Local)
- ID2: Due-Radar-Query-Design
- ID3: Pflegegrad-Score-Komposition
- ID4: HTMX-Fragment-Strategie fuer Objekt-Detail

**Deferred (v1.1+):**

- DD1: Object-Level-ACL-Enforcement (Tabelle ja, Check nein — in v1 "allow all")
- DD2: Write-Back pro Feld nach Impower/Facilioo (nur Read v1)
- DD3: Registry-Detailseiten ausser Versicherer
- DD4: KI-Agenten selbst (nur Infrastruktur v1)
- DD5: Event-Stream / Notification-Hub
- DD6: Redis/Cache-Layer

### CD1 — Datenarchitektur

**Entscheidung:** Normalisierte relationale Tabellen ab v1, nicht JSONB-Anhaenge pro Objekt. FKs statt Snapshots. Postgres-JSONB nur fuer bewusst unstrukturierte Felder.

**Neue Haupt-Entitaeten** (UUID-PKs, `created_at`/`updated_at`-Audit-Spalten):

| Entitaet | Zweck | JSONB-Felder |
|---|---|---|
| `Object` | Objekt-Stamm + Cluster 1/4-Felder + Sekundaer-IDs + encrypted Zugangscodes | `voting_rights`, `object_history_structured`, `equipment_flags`, `notes_owners` (admin-only) |
| `Unit` | Einheits-Zeile, FK→Object | `equipment_features`, `floorplan_drive_item_id` |
| `Police` | Versicherungs-Police, FK→Object, FK→Versicherer | `coverage`, `risk_attributes` |
| `Wartungspflicht` | FK→Police + FK→Dienstleister, `next_due_date` | `notes` |
| `Schadensfall` | FK→Police, FK→Unit, `estimated_sum` | `description` |
| `Versicherer` | Registry, v1 mit Detailseite | `contact_info` |
| `Dienstleister` | Registry (Handwerker, Sanitaer, etc.), v1 nur Tabelle | `gewerke_tags`, `notes` |
| `Bank` | Registry, v1 nur Tabelle | — |
| `Ablesefirma` | Registry, v1 nur Tabelle | — |
| `Eigentuemer` | Registry (Mirror aus Impower-Contacts), admin-only `notes` | `voting_stake_json` |
| `Mieter` | Registry (Mirror aus Impower-Contacts) | — |
| `Mietvertrag` | FK→Unit, FK→Mieter | — |
| `Zaehler` | FK→Unit | `current_reading_snapshot` |
| `FaciliooTicket` | Mirror-Entitaet, FK→Object + optional Eigentuemer/Mieter | `raw_payload` |
| `SteckbriefPhoto` | Foto-Referenz (SharePoint oder Local), FK→Object + optional Unit + component_ref | `metadata` |
| `FieldProvenance` | **Generischer Herkunfts-Nachweis fuer Einzelfelder** (siehe CD2) | `value_snapshot` |
| `ReviewQueueEntry` | **KI-Vorschlaege vor Write-Gate** (siehe CD2) | `proposed_value`, `agent_context` |

**Data Validation:** Pydantic v2-Schemas pro Entitaet neben dem Service (`app/services/steckbrief.py`), Validierung an System-Boundaries (User-Input, externe API-Responses). Keine defensiven Re-Validierungen innerhalb der Service-Schicht.

**Migrations:** Zwei Alembic-Revisionen (`0010_steckbrief_core.py` fuer alle Haupt-Tabellen + Permissions + Audit-Actions-Seed, `0011_steckbrief_provenance_review_queue.py` fuer die Governance-Tabellen + `resource_type="object"`-Erweiterung). Handgeschrieben, linear auf `0009` aufbauend.

**Caching:** Keine. Live-Queries gegen Postgres sind fuer 50 Objekte × ~20 Policen kein Problem. `Cache`-Hook-Points bleiben aber moeglich (kein Singleton-State, alles Service-Funktionen).

**Indexes:** FKs auf Object/Unit/Police in jedem Kind-Modell; zusaetzliche Indexe auf `Police.next_main_due`, `Wartungspflicht.next_due_date`, `FaciliooTicket.facilioo_id` (unique), `FieldProvenance(entity_type, entity_id, field_name)`, `ReviewQueueEntry(status, created_at)` und `ReviewQueueEntry(target_entity_type, target_entity_id)`.

### CD2 — KI-Governance-Gate (Core-Innovation von v1)

**Problem:** FR21, FR22, FR25, NFR-S6 — jeder Write auf ein Steckbrief-Feld muss Provenance-Eintrag erzeugen; KI-Writes muessen strukturell an einem Review-Queue-Gate scheitern, wenn kein genehmigter Queue-Eintrag vorliegt.

**Entscheidung:** **Zentralisiertes Write-Gate** als eigener Service `app/services/steckbrief_write_gate.py`. Alle Field-Writes auf Steckbrief-Entitaeten laufen durch genau zwei Funktionen; Direktes ORM-Setzen von Feld-Werten auf den neuen Entitaeten ist konventionell verboten (enforced durch Code-Review + optional durch einen Unit-Test, der grept).

```python
# app/services/steckbrief_write_gate.py
def write_field_human(
    db: Session,
    *,
    entity,              # ORM-Instanz (Object, Police, ...)
    field: str,
    value,
    source: str,         # "user_edit" | "impower_mirror" | "facilioo_mirror" | "sharepoint_mirror"
    user: User | None,   # None fuer Sync-Jobs
    source_ref: str | None = None,   # z.B. Impower-Property-ID
    request=None,
) -> None:
    """Schreibt das Feld + FieldProvenance-Zeile + optional AuditLog in **derselben** Transaktion.
    Caller committed."""

def write_field_ai_proposal(
    db: Session,
    *,
    target_entity_type: str,
    target_entity_id: UUID,
    field: str,
    proposed_value,
    agent_ref: str,      # "te_scan_agent", "policen_extract_agent", ...
    confidence: float,
    source_doc_id: UUID | None,
    agent_context: dict,
) -> ReviewQueueEntry:
    """Legt nur einen ReviewQueueEntry an. Schreibt NIE direkt ins Ziel-Feld."""

def approve_review_entry(db, *, entry_id, user, request) -> None:
    """Approve → write_field_human mit source='ai_suggestion' + Provenance-Eintrag mit
    confidence + agent_ref. Ruft intern write_field_human() → Audit `review_queue_approved`."""

def reject_review_entry(db, *, entry_id, user, reason, request) -> None:
    """Markiert Eintrag als rejected + Audit `review_queue_rejected`. Kein Field-Write."""
```

**Strukturelle Blockade:** `write_field_ai_proposal` **schreibt nicht** ins Ziel-Feld. Der KI-Agent kann gar keinen direkten Write-Call absetzen — die Funktion existiert nicht. Policy-Violation-Pfad: wenn kuenftiger Code versucht, direkt `entity.field = value` fuer einen Agenten zu setzen, gibt es kein Provenance-Eintrag → Konsistenz-Check (`verify_provenance_coverage`-Tool, lief als nightly Assertion) faellt, `AuditLog`-Eintrag `policy_violation`.

**Rationale:** Ein vollstaendig in der DB durchgesetzter Gate (z. B. via Trigger) waere ueberengineered fuer v1. Die Kombination aus (a) nur **einer** erlaubten Write-API fuer Agenten, (b) Provenance-Pflicht fuer jeden Write und (c) nightly Konsistenz-Check (0 Felder ohne Provenance-Eintrag seit Einfuehrung) ist praktikabel und prueferbar. FR25 ist erfuellt, NFR-S6 ebenfalls.

**FieldProvenance-Schema:**

```python
class FieldProvenance(Base):
    id: Mapped[UUID]
    entity_type: Mapped[str]       # "object", "unit", "police", ...
    entity_id:   Mapped[UUID]
    field_name:  Mapped[str]
    source:      Mapped[str]       # user_edit | impower_mirror | facilioo_mirror |
                                   # sharepoint_mirror | ai_suggestion
    source_ref:  Mapped[str | None]        # Impower-ID, doc_id, agent_ref
    user_id:     Mapped[UUID | None]       # gesetzt fuer user_edit / ai_suggestion approval
    confidence:  Mapped[float | None]      # nur bei ai_suggestion
    value_snapshot: Mapped[dict]           # JSONB: {"old": ..., "new": ...}
    created_at:  Mapped[datetime]
```

**ReviewQueueEntry-Schema:**

```python
class ReviewQueueEntry(Base):
    id: Mapped[UUID]
    target_entity_type: Mapped[str]
    target_entity_id:   Mapped[UUID]
    field_name:         Mapped[str]
    proposed_value:     Mapped[dict]       # JSONB: beliebiger Typ, vereinheitlicht
    agent_ref:          Mapped[str]
    confidence:         Mapped[float]
    source_doc_id:      Mapped[UUID | None]
    agent_context:      Mapped[dict]       # JSONB: {prompt_version, extraction_id, ...}
    status:             Mapped[str]        # pending | approved | rejected | superseded
    created_at:         Mapped[datetime]
    decided_at:         Mapped[datetime | None]
    decided_by_user_id: Mapped[UUID | None]
    decision_reason:    Mapped[str | None]
```

### CD3 — Sync-Orchestrator

**Entscheidung:** Drei Sync-Modi, alle ueber denselben Grund-Layer:

- **Nightly-Mirror** (Impower Cluster 1 + 6) — triggert um 02:30 Uhr via APScheduler-ish BackgroundTask im Lifespan (einfachste Variante: `asyncio.create_task` mit `while True: sleep_until_0230` im Lifespan). **Default: keine neue Dependency** — eigener Scheduler-Baustein im Lifespan. Fallback: minuetlich `settings.next_mirror_run_at` pruefen.
- **1-Min-Poll** (Facilioo-Tickets) — Lifespan-BackgroundTask, `await asyncio.sleep(60)` im Loop. Delta via ETag/If-Modified-Since wenn Server-Support geklaert, sonst Full-Pull mit Diff auf `facilioo_id`.
- **Live-Pull** (Bank-Saldo aus Impower) — direkt im Render-Handler, async. Fehler → UI zeigt "Saldo aktuell nicht verfuegbar" + letzten bekannten Wert aus `Object.last_known_balance`.

**Gemeinsames Muster** (`app/services/_sync_common.py`):

```python
async def run_sync_job(
    *,
    job_name: str,
    fetch_items: Callable,
    reconcile_item: Callable,
    db_factory: Callable = SessionLocal,
) -> SyncRunResult:
    """Fetched Items via fetch_items(), reconciles pro Item in eigener Session,
    sammelt Fehler, schreibt Start/Ende/Fehler in AuditLog + stdout.
    Einzel-Item-Fehler brechen den Job nicht ab (NFR-R3)."""
```

**Status-Persistenz:** `SyncRun` ist kein eigener Model — Laufzeit-Info wird im Audit-Log gespeichert (`sync_started` / `sync_finished` / `sync_failed` mit `details`). Admin-Dashboard liest das zurueck (FR30, NFR-R3, NFR-O3).

**Rate-Limit-Respektierung:** Impower-Mirror nutzt den bestehenden `_rate_limit_gate` des Clients. Facilioo-Client bringt eigenes Gate mit (Default 1 req/s). SharePoint-Graph respektiert `Retry-After` aus 429.

**Fallback-Pfade:**

- Facilioo nicht in 9 Tagen anbindbar → `Cluster 3.3` auf v1.1, `FaciliooTicket`-Tabelle bleibt leer, UI zeigt "Ticket-Integration in Vorbereitung".
- SharePoint-Setup verzoegert → `PhotoStore.Local` aktiv, Uploads landen unter `uploads/objects/{short_code}/{kategorie}/{sha256}.jpg`, Migration zu SharePoint schreibt `drive_item_id` nachtraeglich in `SteckbriefPhoto`-Row.

### CD4 — Authentication, Authorization, Audit

**Authentication:** Unveraendert — bestehendes Google-OAuth-Gate mit `@dbshome.de` Hosted-Domain-Check, Session via Starlette + itsdangerous.

**Authorization (neue Permissions):**

- `objects:view` — Objekt-Liste + Detailseite.
- `objects:edit` — Steckbrief-spezifische Felder (Cluster 4/6/8) schreiben.
- `objects:approve_ki` — Review-Queue approve/reject.
- `objects:view_confidential` — Vertrauliche Felder lesen — Zugangscodes (Story 1.7 + 2.0) und Menschen-Notizen (Story 2.4), admin-only default, NFR-S5, FR8.
- `registries:view` — Versicherer/Dienstleister/...-Liste.
- `registries:edit` — Registry-Entitaeten schreiben.
- `due_radar:view` — Due-Radar-View.
- `sync:admin` — Sync-Status-Admin-View + Manual-Trigger.

**Default-Rollen:** Admin bekommt alle; `user` bekommt `objects:view/edit/approve_ki`, `registries:view/edit`, `due_radar:view`. `objects:view_confidential` + `sync:admin` nur Admin.

**Resource-Access-Erweiterung:** `RESOURCE_TYPE_OBJECT = "object"` als neue Konstante. Ab Tag 1 **nicht enforced** (v1: alle duerfen alle 50 Objekte) — aber `accessible_object_ids(db, user)`-Helper existiert, Handler nutzen ihn. Scharfschaltung erfolgt in v1.1, ohne weitere Tabellen-Migration.

**Audit-Actions (neue Keys):**

```
object_created, object_field_updated, object_photo_uploaded, object_photo_deleted,
registry_entry_created, registry_entry_updated,
review_queue_created, review_queue_approved, review_queue_rejected,
sync_started, sync_finished, sync_failed,
policy_violation,
encryption_key_missing  (operativer Fallback)
```

Alle ueber `audit()`-Helper (`app/services/audit.py`), in derselben Transaktion wie der Business-Change (NFR-S4). `docs/architecture.md` §8 wird nach Umsetzung ergaenzt.

### CD5 — Field-Level-Encryption

**Entscheidung:** `cryptography.fernet.Fernet` mit per-Feld-Schluessel, abgeleitet via `HKDF(SECRET_KEY, salt=b"steckbrief-v1", info=f"{entity_type}:{field_name}")`. Neue Helper `app/services/field_encryption.py`.

```python
def encrypt_field(plaintext: str, *, entity_type: str, field: str, key_id: str = "v1") -> str: ...
def decrypt_field(ciphertext: str, *, entity_type: str, field: str) -> str: ...
# Hinweis: decrypt_field hat keinen key_id-Parameter — die key_id wird aus dem
# Ciphertext-Praefix gelesen (ciphertext.partition(":")), aber v1 nutzt immer
# denselben abgeleiteten Schluessel. Rotation (v1.1) erfordert einen Key-Ring-Lookup.
```

**Rotations-Vorbereitung:** Jede verschluesselte Zelle speichert das Ciphertext-Format `v1:<base64>` — Praefix ist die `key_id`. Rotation bedeutet: neue `key_id="v2"` aktiv machen, Re-Encrypt-Job schreibt alle Felder neu (Admin-Tool). In v1 kein Job implementiert, aber Format vorbereitet.

**Schluessel-Quelle:** `settings.STECKBRIEF_FIELD_KEY` (optional) → Fallback `settings.SECRET_KEY`. Dokumentiert im `.env.op`.

**Anwendungsfelder v1:** `Object.entry_code_main_door`, `Object.entry_code_garage`, `Object.entry_code_technical_room` (alle String-Spalten mit Ciphertext). Kein transparentes `TypeDecorator` — das machen explizite Service-Calls `get_entry_codes(obj, user)`, damit Audit-Eintrag sauber entsteht, falls der Zugriff loggingpflichtig wird.

**Nie im Log / Audit-Payload:** Klartext-Zugangscodes werden **nicht** in `AuditLog.details_json` oder Provenance-`value_snapshot` geschrieben — dort landet nur ein Marker `{"encrypted": true}`. Explizit im Code-Review checken.

### ID1 — Foto-Pipeline

**Interface** `app/services/photo_store.py`:

```python
class PhotoStore(Protocol):
    async def upload(self, *, object_short_code: str, category: str,
                     filename: str, content: bytes, content_type: str) -> PhotoRef: ...
    async def url(self, ref: PhotoRef) -> str: ...   # Temporary download link
    async def delete(self, ref: PhotoRef) -> None: ...

class PhotoRef(BaseModel):
    backend: Literal["sharepoint", "local"]
    drive_item_id: str | None
    local_path: str | None
    filename: str
```

**Zwei Implementierungen:** `SharePointPhotoStore` (MSAL + Graph-API, Upload nach `SharePoint/DBS/Objekte/{short_code}/{kategorie}/`) und `LocalPhotoStore` (Pfad `uploads/objects/{short_code}/{kategorie}/{sha256}.{ext}`). Auswahl via `settings.photo_backend = "sharepoint" | "local"`, Default `"sharepoint"`. Lifespan prueft beim Start, ob der SharePoint-Graph-Client authentifiziert werden kann; wenn nicht → automatisch `"local"` + WARN-Log + AuditLog `sharepoint_init_failed`.

**Upload-Handler:** Foto als `UploadFile` aus dem Browser, Validierung (`content_type` Whitelist jpeg/png, Size-Limit 10 MB, Magic-Bytes-Check wie in `test_upload.py`). Upload ueber den selektierten `PhotoStore`. Das entstehende `SteckbriefPhoto`-ORM-Object haelt `backend`, `drive_item_id`, `local_path`, `filename`, `component_ref` (z. B. `"absperrpunkt_wasser"` oder `"heizung_typenschild"`), `captured_at`, `uploaded_by_user_id`.

**BackgroundTask fuer grosse Uploads:** Wenn `content_length > 3 MB`, geht der Upload nach SharePoint in einen BackgroundTask; UI zeigt "Upload laeuft..." und pollt `GET /objects/{id}/photos/{photo_id}/status` jede 3 s. Kleine Fotos synchron. (NFR-P5.)

### ID2 — Due-Radar-Query

**Entscheidung:** **Keine** Materialized View, keine separate `due_radar_entries`-Tabelle. Statt dessen ein Service `app/services/due_radar.py` mit UNION-ALL-Query ueber drei Quell-Tabellen:

```python
def list_due_within(db, *, days: int, severity: str | None, types: list[str] | None,
                    accessible_object_ids: list[UUID]) -> list[DueRadarEntry]:
    """
    UNION ALL:
      SELECT 'police' AS kind, id, object_id, next_main_due AS due_date, ...
      SELECT 'wartung', id, object_id, next_due_date, ... FROM wartungspflicht
      SELECT 'contract', id, object_id, next_main_due, ... FROM management_contract
    WHERE due_date <= now() + INTERVAL ':days days'
      AND object_id = ANY(:accessible_object_ids)
    """
```

`DueRadarEntry` ist ein schlanker Dataclass mit `kind`, `entity_id`, `object_id`, `object_short_code`, `due_date`, `days_remaining`, `severity` ("< 30 Tage" / "< 90 Tage"), `title`, `link_url`. Volumen bei 50 Objekten × 3 Policen + 3 Wartungen = ~300 Zeilen, gefiltert auf 90-Tage-Fenster = typisch 20–30 — P95 < 2 s trivial erreichbar (NFR-P3).

### ID3 — Pflegegrad-Score

**Entscheidung:** Deterministische Formel im Service `app/services/pflegegrad.py`, keine KI, keine Zufallskomponente. Komposition pro Objekt:

- **Completeness-Rate** pro Cluster: Anteil befuellter Pflichtfelder (Feldkatalog-Legende `Pflicht v1 = ✓`) in Cluster 1/4/6/8. Gewichtung initial: C1=20 %, C4=30 %, C6=20 %, C8=30 %.
- **Aktualitaets-Decay:** Feld-Werte aelter als 365 Tage (per neuestem `FieldProvenance.created_at`) zaehlen zur Haelfte. Aelter als 1095 Tage → zaehlen zu 10 %.
- **Score** = gewichtete Summe × 100, gerundet auf Integer.

**Ausgabe:** `PflegegradResult(score: int, per_cluster: dict[str, float], weakest_fields: list[str])` — UI rendert Badge + Info-Popover mit Komposition (FR20). Jeder Feld-Liste-Eintrag linkt direkt zum Anker in der Objekt-Detail-Seite.

**Persistierung:** `Object.pflegegrad_score_cached: int | None` + `pflegegrad_score_updated_at: datetime | None` fuer schnelle Listen-View-Sortierung. Cache invalidiert automatisch on-write (im `write_field_human` → `invalidate_pflegegrad(entity)`). Listen-View nutzt Cache; Detail-Seite rechnet neu, wenn Cache aelter als 5 Min.

### ID4 — HTMX-Fragment-Strategie

**Objekt-Detailseite:** Eine Haupt-Seite `object_detail.html`, unterteilt in 7 Sektionen als `include`-Fragmente (`_obj_stammdaten.html`, `_obj_technik.html`, `_obj_finanzen.html`, `_obj_versicherungen.html`, `_obj_menschen.html`, `_obj_historie.html`, `_obj_review_queue.html`). Inline-Edits via HTMX-Swap der jeweiligen Sektion; Edit-Forms posten an `POST /objects/{id}/sections/{section_key}` → Response ist das frische Sektion-Fragment.

**Liste:** `objects_list.html` mit HTMX-Swap des `_obj_table_body.html`-Fragments bei Sort/Filter.

**Review-Queue (Admin):** `/admin/review-queue` mit Filter-Form, HTMX-Swap der Zeilen-Liste.

**Due-Radar:** `/due-radar` eine Seite, Filter-Controls HTMX-swappen `_due_radar_rows.html`.

**Case-like Live-Status fuer BackgroundTasks (grosse Foto-Uploads, Nightly-Mirror manual trigger):** Meta-Refresh-Pattern aus M5 wiederverwenden.

### Cross-Cutting Decisions

- **Data Format:** JSONB-Feldnamen **snake_case** (konsistent mit bestehendem Code). Boolean als `true`/`false`. Datums-Felder als ISO-8601. Geld-Betraege als `Numeric(12, 2)`.
- **Error-Handling:** Eigene Exceptions (`SteckbriefError`, `SyncError`, `PhotoStoreError`) aus Services; Router mappen zu `HTTPException`. Externe Fehler (httpx) kommen als `ImpowerError`/`FaciliooError`/`SharePointError` hoch.
- **Logging:** `print(...)` + `audit()` (Plattform-Regel, kein zusaetzliches Logging-Framework).
- **Communication:** Keine eigenen Events/Messages — direkter Service-Call. Event-Stream-Fundament ist v1.1-Kandidat (Backlog-Punkt 4).
- **Loading States:** HTMX `hx-indicator` auf allen nicht-trivialen Swaps; BackgroundTask-Views nutzen `<meta http-equiv="refresh">`.

### Decision Impact Analysis

**Implementation-Reihenfolge:**

1. Alembic-Migration `0010` (Haupt-Entitaeten + Permissions + Audit-Actions).
2. `write_field_human` + Provenance + Tests (ohne Review-Queue).
3. Alembic-Migration `0011` (`ReviewQueueEntry` + `resource_type="object"`-Seed).
4. Objekt-Detail + Liste (manuelle Daten-Eingabe).
5. Impower-Mirror (Nightly).
6. SharePoint-Upload + Foto-Pipeline.
7. Due-Radar + Versicherer-Registry.
8. Facilioo-Integration (ab Tag 3 Go/No-Go).
9. Pflegegrad + Admin-Dashboards.

**Cross-Component Dependencies:**

- CD2 `write_field_human` ist Voraussetzung fuer **alle** Sync-Jobs und UI-Edits — muss vor Schritt 4 fertig sein.
- CD5 Encryption ist Voraussetzung fuer Cluster-4-Edit-Forms — muss vor Technik-Sektion fertig sein.
- ID1 Foto-Pipeline kann als `LocalPhotoStore`-Only in v1 parallel zum SharePoint-Setup laufen.
- CD3 Sync-Orchestrator verfeinern, sobald Facilioo-Auth geklaert.

---

## Implementation Patterns & Consistency Rules

_Zusaetzlich zu `docs/project-context.md` (Plattform-weite Regeln). Hier nur Muster, die fuer den Steckbrief neu oder schaerfer sind._

### Naming

**ORM-Tabellen:** `steckbrief_` praefixieren ist **nicht** noetig (zu sperrig). Direkt sprechende Namen: `objects`, `units`, `policen`, `wartungspflichten`, `schadensfaelle`, `versicherer`, `dienstleister`, `banken`, `ablesefirmen`, `eigentuemer`, `mieter`, `mietvertraege`, `zaehler`, `facilioo_tickets`, `steckbrief_photos`, `field_provenance`, `review_queue_entries`. Deutsche Pluralformen sind akzeptabel, wo etabliert (konsistent zu den Domain-Begriffen). Fremdschluessel: `<entity>_id`.

**Python-Modelle:** PascalCase, Englisch wo klar (`Object`, `Unit`, `Policy` — **Ausnahme:** `Policy` kollidiert semantisch mit Permissions-Policy, deshalb `Police` beibehalten. Oder `InsurancePolicy`. Entscheidung: `InsurancePolicy` als Python-Klasse, Tabellenname `policen`. Das halbiert das Mismatch-Risiko.)

**Router-Pfade:** deutsche Nouns, aber URL-safe (`/objects`, `/objects/{id}`, `/registries/versicherer`, `/registries/dienstleister`, `/due-radar`, `/admin/review-queue`).

**Permission-Keys:** `<resource>:<action>` in snake_case (siehe CD4).

**Audit-Actions:** `<entity>_<verb>` in snake_case (siehe CD4).

### Code Organization

- Router unter `app/routers/` — eine Datei pro Top-Level-Ressource.
- Services unter `app/services/` — eine Datei pro Fach-Konzept.
- Models unter `app/models/` — eine Datei pro Aggregat (ein File kann mehrere kleine FK-Relationen halten, z. B. `police.py` enthaelt `InsurancePolicy`, `Schadensfall`, `Wartungspflicht`).
- Schemas (Pydantic) **neben** dem Service (`app/services/steckbrief.py` enthaelt `ObjectCreate`, `ObjectUpdate`, `PoliceCreate`, ...). Keine separaten `schemas/`-Verzeichnisse.
- Templates: vollstaendige Seiten (`object_detail.html`, `objects_list.html`) und Fragmente (`_obj_technik.html`, `_due_radar_rows.html`, `_review_queue_row.html`).

### Daten- und Write-Patterns

- **Ein einziger Write-Pfad** fuer Steckbrief-Felder: `steckbrief_write_gate.write_field_human(...)`. Direkte `entity.field = value` gefolgt von `db.commit()` ist fuer die CD1-Entitaeten konventionell verboten, **ausgenommen** die Tabellen `FieldProvenance`, `ReviewQueueEntry`, `AuditLog` und `SteckbriefPhoto`-Row-Creation (Photo-Referenz ist ein Struktur-Write, kein Cluster-Feld-Write). Code-Review kontrolliert; Unit-Test `test_write_gate_coverage.py` grept die Sources auf verbotene Pattern.
- **JSONB-Mutation nur via Reassign / `flag_modified`** — Plattform-Regel, gilt fuer `object.voting_rights`, `review_queue_entry.agent_context`, etc.
- **`write_field_human` committed nicht selbst** — Caller haelt die Transaktion. Damit landet der Business-Write, der Provenance-Eintrag und der Audit-Eintrag in **einer** Transaktion (NFR-S4).

### Integrations-Patterns

- **Neue externe Clients** (Facilioo, SharePoint) folgen dem Impower-Client-Muster:
  - `async` httpx-Client als Modul-Singleton, gleiche Timeout/Retry-Semantik, Rate-Gate.
  - Keine direkten `httpx.AsyncClient`-Calls ausserhalb des Client-Moduls.
  - Antworten via Pydantic-Schema validieren.
  - HTML-Body sanitisieren (`strip_html_error` in `_sync_common`).
- **Keine Legacy-"ImpowerClient-Klasse"** — Plattform-Muster nutzt Modul-Level-Funktionen mit `async_client`-Singleton. Wird fuer Facilioo/SharePoint uebernommen.

### BackgroundTask-Pattern

Unveraendert gegenueber M5:

```python
def some_handler(background_tasks: BackgroundTasks, ...):
    background_tasks.add_task(_run_something, arg1, arg2)

def _run_something(arg1, arg2):
    db = SessionLocal()
    try:
        asyncio.run(_do_async_work(db, arg1, arg2))
    except Exception:
        # log + audit
        ...
    finally:
        db.close()
```

### Form + HTMX

- Edit-Forms posten an Sektion-Endpoints. Response: Sektion-Fragment mit frischem State.
- Bei HTMX-Request (`HX-Request` Header) nur Fragment; bei Full-Navigation Fragment mit `hx-preserve` auf dem Shell. Oder einfacher: Full-Navigation auf Edit-Success → `RedirectResponse` (303) zur Detailseite.
- `hx-indicator` fuer alle Swaps > 200 ms.

### Fehlerbehandlung

- User-facing: `HTTPException(detail=...)`-Text nie Stacktraces enthalten.
- Service-intern: eigene Exceptions (`SteckbriefError`, `SyncError`, `PhotoStoreError`) mit klaren Messages.
- Sync-Jobs: einzelne Item-Fehler sammeln, nicht aborten, Audit `sync_failed` mit Fehler-Array.
- BackgroundTasks: unerwartete Exception → `audit("task_crashed", ...)`, nie stumm schlucken.

### Status-Indikatoren (Provenance-Pills im UI)

Analog zu `field_source` aus M5: Jinja-Filter `provenance_pill(entity, field)` liefert eines von `user_edit` / `impower_mirror` / `facilioo_mirror` / `ai_suggestion` / `missing` — rendert mit Farbe + Tooltip (Zeitpunkt + Quelle + ggf. Confidence). Der Filter lebt in `app/templating.py`.

---

## Project Structure & Boundaries

### Geplante Erweiterung des Repos (Delta gegen `docs/source-tree-analysis.md`)

```
app/
├── main.py                              # [edit] Lifespan: Scheduler-Tasks registrieren,
│                                        #        neue Permissions seeden, Admin-Email-Check
├── permissions.py                       # [edit] PERMISSIONS um objects/registries/sync erweitern,
│                                        #        RESOURCE_TYPE_OBJECT konstante
├── templating.py                        # [edit] neue Globals: provenance_pill, pflegegrad_color,
│                                        #        due_severity_badge
├── config.py                            # [edit] STECKBRIEF_FIELD_KEY, PHOTO_BACKEND,
│                                        #        FACILIOO_BASE_URL, FACILIOO_API_KEY,
│                                        #        SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID,
│                                        #        SHAREPOINT_CLIENT_SECRET, SHAREPOINT_DRIVE_ID
│
├── models/
│   ├── object.py                        # [new] Object, Unit, SteckbriefPhoto
│   ├── police.py                        # [new] InsurancePolicy, Wartungspflicht, Schadensfall
│   ├── registry.py                      # [new] Versicherer, Dienstleister, Bank, Ablesefirma
│   ├── person.py                        # [new] Eigentuemer, Mieter
│   ├── rental.py                        # [new] Mietvertrag, Zaehler
│   ├── facilioo.py                      # [new] FaciliooTicket
│   └── governance.py                    # [new] FieldProvenance, ReviewQueueEntry
│
├── routers/
│   ├── objects.py                       # [new] /objects, /objects/{id}, Sektion-POSTs,
│   │                                    #       /objects/{id}/photos, /objects/{id}/review-queue
│   ├── registries.py                    # [new] /registries/versicherer, /registries/dienstleister,
│   │                                    #       /registries/banken, /registries/ablesefirmen
│   ├── due_radar.py                     # [new] /due-radar
│   └── admin.py                         # [edit] /admin/review-queue, /admin/sync-status
│
├── services/
│   ├── steckbrief_write_gate.py         # [new] write_field_human, write_field_ai_proposal,
│   │                                    #       approve/reject_review_entry
│   ├── steckbrief.py                    # [new] CRUD-Services + Pydantic-Schemas fuer Object/Unit
│   ├── steckbrief_impower_mirror.py     # [new] Nightly-Mirror fuer Cluster 1 + 6
│   ├── facilioo.py                      # [new] Facilioo-Client (httpx, rate-gate, retry)
│   ├── facilioo_mirror.py               # [new] 1-Min-Poll-Job
│   ├── sharepoint_graph.py              # [new] MSAL-basiert, Graph-Upload/Download/List
│   ├── photo_store.py                   # [new] PhotoStore-Interface + SharePoint/Local-Impl
│   ├── pflegegrad.py                    # [new] deterministische Score-Berechnung
│   ├── review_queue.py                  # [new] list/filter/decide-Helfer
│   ├── due_radar.py                     # [new] list_due_within
│   ├── field_encryption.py              # [new] Fernet + HKDF, encrypt_field/decrypt_field
│   └── _sync_common.py                  # [new] run_sync_job, strip_html_error, backoff
│
├── templates/
│   ├── objects_list.html                # [new]
│   ├── object_detail.html               # [new]
│   ├── _obj_stammdaten.html             # [new]
│   ├── _obj_technik.html                # [new]
│   ├── _obj_finanzen.html               # [new]
│   ├── _obj_versicherungen.html         # [new]
│   ├── _obj_menschen.html               # [new]
│   ├── _obj_historie.html               # [new]
│   ├── _obj_review_queue.html           # [new]
│   ├── _obj_table_body.html             # [new]
│   ├── registries_versicherer_list.html # [new]
│   ├── registry_versicherer_detail.html # [new]
│   ├── _registry_row.html               # [new] (generisch fuer Dienstleister/Bank/...)
│   ├── due_radar.html                   # [new]
│   ├── _due_radar_rows.html             # [new]
│   ├── admin_review_queue.html          # [new]
│   ├── _review_queue_row.html           # [new]
│   ├── admin_sync_status.html           # [new]
│   └── base.html                        # [edit] Navigations-Eintrag Objekte + Due-Radar
│
migrations/versions/
├── 0010_steckbrief_core.py              # [new] alle Haupt-Tabellen + Permissions + Audit-Seed
├── 0011_steckbrief_governance.py        # [new] FieldProvenance + ReviewQueueEntry +
│                                        #       resource_access(resource_type="object")
│
tests/
├── test_write_gate_unit.py              # [new] Provenance-Pflicht, Audit-Transaktion, Agent-Gate
├── test_pflegegrad_unit.py              # [new] Formel-Edge-Cases (alle leer, alle voll, aged)
├── test_field_encryption_unit.py        # [new] Roundtrip + Key-ID-Format + nicht-im-log
├── test_due_radar_unit.py               # [new] Zeit-Fenster + Severity + ACL-Filter
├── test_photo_store_unit.py             # [new] Backend-Switch + Validierung
├── test_facilioo_unit.py                # [new] Delta-Logik + 429-Retry + Timeout
├── test_sync_common_unit.py             # [new] Einzel-Item-Fehler bricht Job nicht ab
├── test_steckbrief_routes_smoke.py      # [new] /objects, /due-radar, /registries/* (302/403/200)
└── conftest.py                          # [edit] Fixtures fuer Object/InsurancePolicy/...
```

### Architectural Boundaries

**Router → Service → Model** (Plattform-Pattern, keine Abweichung).

- Router sehen **nie** `httpx`-Clients direkt, **nie** `cryptography`, **nie** Alembic.
- Services sehen **nie** `Request`, **nie** `Form(...)`, **nie** Template-Globals.
- Models halten **nur** Daten-Struktur + Beziehungen, keine Geschaefts-Methoden jenseits einfacher `@property`-Derivate.

**Write-Gate-Boundary:** Die CD1-Haupt-Entitaeten werden **ausserhalb** von `steckbrief_write_gate.py` nicht feld-beschrieben. Ausnahme: Row-Creation selbst (z. B. `db.add(Object(short_code=..., name=...))`) ist erlaubt; nachtraegliches `obj.field = value` nicht.

**Integrations-Boundary:**

- `impower.py` bleibt einziger Impower-Client.
- `facilioo.py` ist einziger Facilioo-Client.
- `sharepoint_graph.py` ist einziger Graph-Client.
- `photo_store.py` wird ueber `get_photo_store()` (Factory, liest `settings.photo_backend`) in Handlern eingezogen.

**Auth-Boundary:** Jeder neue Router nutzt `Depends(get_current_user)` + `Depends(require_permission(...))`. Keine eigenen Auth-Implementierungen.

### Requirements to Structure Mapping

| FR | Haupt-Locations |
|---|---|
| FR1 Objekt-Detail | `routers/objects.py`, `object_detail.html`, alle `_obj_*.html` |
| FR2 Stammdaten Read-only | `services/steckbrief_impower_mirror.py`, `_obj_stammdaten.html` |
| FR3 Technik-Pflege | `_obj_technik.html`, `services/steckbrief.py`, `field_encryption.py` |
| FR4 Finanzen + Live-Saldo | `_obj_finanzen.html`, `steckbrief_impower_mirror.py`, `impower.py::get_bank_balance` |
| FR5/FR6 Versicherungen + Schadensfall | `_obj_versicherungen.html`, `services/steckbrief.py::create_schadensfall` |
| FR7 Ruecklage-Sparkline | `_obj_finanzen.html` (SVG inline), `services/steckbrief_impower_mirror.py` (Historie) |
| FR8 Menschen-Notizen admin-only | `_obj_menschen.html`, `permissions.py::objects:view_confidential` |
| FR9 Foto-Upload | `routers/objects.py::upload_photo`, `services/photo_store.py` |
| FR10 Zugangscodes verschluesselt | `services/field_encryption.py`, `Object`-Model mit encrypted Strings |
| FR11/FR12 Objekt-Liste | `objects_list.html`, `_obj_table_body.html` |
| FR13–FR15 Due-Radar | `routers/due_radar.py`, `services/due_radar.py` |
| FR16/FR17 Versicherer-Registry | `routers/registries.py`, `registries_versicherer_list.html`, `registry_versicherer_detail.html` |
| FR18 normalisierte Registries | `models/registry.py`, `models/person.py`, `models/rental.py` |
| FR19/FR20 Pflegegrad | `services/pflegegrad.py`, Popover-Partial in `_obj_stammdaten.html` |
| FR21 Provenance | `models/governance.py::FieldProvenance`, write-gate |
| FR22–FR25 Review-Queue + Gate | `models/governance.py::ReviewQueueEntry`, `services/steckbrief_write_gate.py`, `routers/admin.py::review_queue` |
| FR26 Impower-Mirror | `services/steckbrief_impower_mirror.py` (Lifespan-Trigger) |
| FR27 Bank-Saldo Live-Pull | `services/impower.py` + Render in `_obj_finanzen.html` |
| FR28 Facilioo-Mirror | `services/facilioo.py` + `services/facilioo_mirror.py` |
| FR29 SharePoint-Upload | `services/sharepoint_graph.py` + `services/photo_store.py` |
| FR30 Stale-Toleranz | Alle Render-Paths catchen externe Fehler und zeigen Snapshot |
| FR31–FR34 Auth + Permissions + Audit | bestehende Platform-Core + CD4 |

### Cross-Cutting Touchpoints

- **Audit-Log:** `audit()`-Helper in jedem Router-Handler, der schreibt. Neue Actions in `docs/architecture.md` §8 nachziehen.
- **Permissions-Seed:** `main.py::_seed_default_roles` um neue Keys ergaenzen. Deploy laedt automatisch in die Default-Rollen; bestehende User-spezifische Overrides bleiben.
- **Lifespan-Tasks:** `main.py`-Lifespan startet `steckbrief_impower_mirror.start_scheduler()` (Nightly-Tick) und `facilioo_mirror.start_poller()` (1-Min-Poll). Shutdown-Hook ruft `cancel()` sauber. Beide Tasks sind idempotent gegen doppelten Start.

---

## Architecture Validation Results

### Coherence Validation

**Decision Compatibility:** Alle CDs/IDs bauen auf demselben Plattform-Core (Auth, Permissions, Audit, Impower-Client, Jinja-Singleton, BackgroundTask-Pattern). Keine widerspruechlichen Tech-Entscheidungen — insbesondere bleibt das Monolith-/MPA-Modell durchgaengig.

**Pattern Consistency:** Write-Gate-Pattern (CD2) ist mit Audit-Pattern (CD4) und Transaktions-Pattern (NFR-S4) verzahnt; alle drei werden in **derselben** DB-Transaktion geschrieben. Sync-Pattern (CD3) nutzt das bekannte BackgroundTask-Muster aus M5 unveraendert.

**Structure Alignment:** Die Datei-Struktur-Delta bleibt additiv — keine Refactorings an bestehenden Modulen, bis auf `main.py`, `permissions.py`, `templating.py`, `config.py` und `admin.py` (Registry-Eintraege + Lifespan-Starts).

### Requirements Coverage

**FR-Coverage:** 34 / 34 FRs sind einer oder mehreren architektonischen Komponenten zugeordnet (siehe Mapping oben). Kein FR ohne Home.

**NFR-Coverage:**

| NFR-Bereich | Adressiert durch |
|---|---|
| NFR-P1..P5 (Performance) | Kein Caching noetig bei 50 Objekten; FK-Indexe; async Live-Pull; BackgroundTask fuer grosse Uploads |
| NFR-S1 OAuth | Bestehender Auth-Pfad |
| NFR-S2 Encryption | CD5 + `field_encryption.py` |
| NFR-S3 TLS | Elestio-Proxy (unveraendert) |
| NFR-S4 Atomarer Audit | Write-Gate + `audit()` in gleicher Transaktion |
| NFR-S5 admin-only Notes | Permission `objects:view_confidential` + serverseitig im Service-Lookup gefiltert |
| NFR-S6 KI-Write-Gate | CD2 strukturell erzwungen |
| NFR-S7 noindex-Header | Neuer Middleware-Hook in `main.py` (Default-Header) — Umsetzung ist trivial, wird in Story 1 mitgenommen |
| NFR-R1..R5 (Reliability) | Stale-Snapshot im Render; Mirror-Jobs fortsetzbar; BackgroundTask-Session-Pattern |
| NFR-I1..I5 (Integrations) | Bestehender Impower-Pattern + gleiche Haertung fuer Facilioo/SharePoint |
| NFR-O1..O5 (Observability) | AuditLog + Provenance + deterministischer Score |
| NFR-SC1..SC3 (Skalierung) | Postgres-only, keine Skalierungs-Architektur — Headroom durch Indexe |

### Implementation Readiness

- **Decision Completeness:** Alle kritischen + wichtigen Decisions dokumentiert; Versionen aus Bestand geerbt, keine offenen Tech-Wahlen ausser PyPI-Versions-Pinning fuer `cryptography` und `msal`.
- **Structure Completeness:** File-Liste vollstaendig; kein unklarer Ort fuer FR-Umsetzung.
- **Pattern Completeness:** Write-Gate, Sync-Orchestrator, Photo-Store-Interface, Foto-Upload-Flow, Pflegegrad-Formel, Due-Radar-Query, Encryption-Helper — alle mit Signatur oder Skelett dokumentiert.

### Gap Analysis & offene Punkte

| # | Gap | Prioritaet | Mitigation |
|---|---|---|---|
| G1 | Facilioo-Auth und Delta-Support unbekannt | Hoch | **Tag 1 Spike:** API-Doku + Auth-Call-Probing; Go/No-Go Tag 3 |
| G2 | SharePoint Service-Account (M365-Admin-Ticket) | Hoch | **Tag 1 anstossen**, LocalPhotoStore als Fallback startbereit |
| G3 | DSFA-Light nicht dokumentiert | Mittel | Vor erstem KI-Vorschlag-Flow in v1.1 — **nicht blockierend fuer v1** |
| G4 | Pflegegrad-Formel-Gewichte empirisch unvalidiert | Niedrig | Start mit dokumentierten Defaults; Iteration nach 30-Tage-Umfrage |
| G5 | Registry-Detailseiten ausser Versicherer fehlen | Niedrig | Bewusst v1.1, Tabellen-Schema traegt die spaeteren Seiten |
| G6 | `resource_type="object"`-Enforcement nicht live | Niedrig | Tabelle geschrieben, Check kommt v1.1 |
| G7 | Rotation-Job fuer Encryption-Keys nicht implementiert | Niedrig | Format traegt `key_id`, Admin-Job v1.1 |
| G8 | Re-Extract beim Austausch von Feld-Quelle (Mirror ueberschreibt User-Edit?) | **Hoch, Klaerung** | **Default:** User-Edit (Provenance `user_edit`) gewinnt ueber `impower_mirror` — Mirror ueberschreibt nur, wenn letzte Provenance ebenfalls `impower_mirror` war. In Story 1 testen. |

### Risks revisited (aus PRD uebernommen + architekturelle Sicht)

| Risiko | Architektonische Mitigation |
|---|---|
| 9-Tage-Window zu knapp | Additive Struktur, kein Refactoring am Bestand; Fallback-Pfade fuer Facilioo + SharePoint explizit |
| Bus-Factor 1 | `docs/architecture.md` und dieses Dokument als vollstaendige Doku; Write-Gate macht Governance aus dem Kopf in den Code |
| Review-Queue wird zur Halde | KI-Workflows bewusst erst v1.1 — v1 zeigt nur leere Queue, Usability wird bei Launch nicht getestet |
| Pflegegrad-Score-Akzeptanz | Formel im Popover sichtbar; Formel-Iteration kostet keine Daten-Migration |

### Architecture Completeness Checklist

- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified (geerbte Plattform-Regeln)
- [x] Cross-cutting concerns mapped (9 Items)
- [x] Critical decisions documented (CD1–CD5)
- [x] Tech-Stack vollstaendig spezifiziert (Bestand + 2 neue Libraries)
- [x] Integration patterns defined (Impower bestehend + Facilioo + SharePoint neu, gleiches Muster)
- [x] Performance considerations addressed
- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Process patterns documented (BackgroundTask, Write-Gate, Sync-Orchestrator)
- [x] Complete directory structure defined (Delta gegen Bestand)
- [x] Component boundaries established (Router/Service/Model + Write-Gate-Boundary)
- [x] Integration points mapped
- [x] Requirements to structure mapping complete (FR1–FR34)

### Readiness Assessment

**Status:** READY FOR IMPLEMENTATION

**Confidence:** Hoch fuer den plattform-internen Teil (Datenmodell, Gate, Encryption, Pflegegrad, Due-Radar, SharePoint `Local`-Fallback). Mittel fuer Facilioo, solange Auth/Delta nicht verifiziert sind — mit klarem Fallback-Pfad.

**Key Strengths:**

- Keine neuen Build-Tools, keine neue Sprache, keine neue DB — maximales Tempo fuer 9-Tage-Fenster.
- KI-Governance als Plattform-Primitiv, nicht Steckbrief-lokal — macht spaetere Agenten (TE-Scan, Policen-Scan) andockfertig.
- Normalisiertes Datenmodell ab Tag 1, ohne JSONB-Schulden; Registry-Detailseiten in v1.1 ohne Migration moeglich.
- Klare Fallbacks fuer beide neuen Integrationen (Facilioo/SharePoint).

**Areas for Future Enhancement (v1.1+):**

- Object-Level-ACL scharfschalten.
- Registry-Detailseiten fuer Dienstleister/Bank/Ablesefirma/Eigentuemer/Mieter.
- Write-Back Impower pro Feld.
- Event-Stream + Notification-Hub (Backlog-Punkt 4).
- Encryption-Key-Rotation-Admin-Job.
- Pflegegrad-Formel-Tuning nach empirischem Feedback.

---

## Naechste Schritte — Implementation-Handoff

**Story-Vorschlag fuer die Umsetzung** (reine Reihenfolge-Empfehlung, keine Zeitangaben):

1. **S1 — Fundament.** Migration `0010`, alle ORM-Modelle, Permissions-Seed, Audit-Actions-Liste erweitert, `main.py`-Lifespan-Hook skeleton, `X-Robots-Tag`-Middleware.
2. **S2 — Write-Gate + Provenance.** `steckbrief_write_gate.py`, Migration `0011`, `test_write_gate_unit.py`.
3. **S3 — Object + Unit UI, manuelle Eingabe.** `routers/objects.py` Grundgeruest, `object_detail.html` + `_obj_stammdaten.html` + `_obj_technik.html` (ohne Foto), Field-Encryption fuer Zugangscodes.
4. **S4 — Foto-Pipeline.** `photo_store.py` + `LocalPhotoStore` zuerst, Upload-Handler, UI-Einbettung.
5. **S5 — Impower-Mirror.** `steckbrief_impower_mirror.py`, Nightly-Scheduler im Lifespan, Admin-Sync-Status-View.
6. **S6 — SharePoint-Graph.** Sobald App-Registration fertig — `sharepoint_graph.py`, `SharePointPhotoStore`, Backend-Switch via Settings.
7. **S7 — Versicherungen + Schadensfall.** `_obj_versicherungen.html`, CRUD fuer Police/Wartung/Schadensfall.
8. **S8 — Due-Radar + Versicherer-Registry.** `due_radar.py`, `registries/versicherer`.
9. **S9 — Pflegegrad-Score.** Formel-Service + Popover + Listen-Sort.
10. **S10 — Facilioo-Mirror.** Nach Tag-3-Go — `facilioo.py`, `facilioo_mirror.py`, Tickets in `_obj_vorgaenge.html` (eigene Sektion, gated auf `objects:view` — NICHT in `_obj_menschen.html`, weil die Confidential-gated ist; Story 4.4).
11. **S11 — Admin-Review-Queue-UI.** Queue leer in v1, UI vorhanden, Story-Loop fuer Approve/Reject.
12. **S12 — Launch-Polishing.** Mobile-Check J2, Accessibility-Pass, E2E-Klickpfad aller 5 Journeys.

**Empfohlen:** `bmad-create-story` fuer Story 1 laufen lassen, die restlichen als `bmad-create-epics-and-stories` oder direkt als Backlog-Einzelstorys fuehren.
