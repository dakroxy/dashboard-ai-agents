---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
status: 'complete'
completedAt: '2026-04-21'
inputDocuments:
  - output/planning-artifacts/prd.md
  - output/planning-artifacts/architecture.md
project_name: 'Dashboard KI-Agenten'
topic: 'Objektsteckbrief v1 — Epic- und Story-Breakdown'
date: '2026-04-21'
---

# Dashboard KI-Agenten — Epic Breakdown

_Scope dieses Dokuments: **Objektsteckbrief v1** (Modul 3 der Plattform), abgeleitet aus PRD und Architecture Decision Document vom 2026-04-21. Kein UX-Design-Dokument vorhanden — UI-Conventions ergeben sich aus `docs/project-context.md` + Bestand (Jinja2 + HTMX + Tailwind)._

## Overview

Dieses Dokument zerlegt die Anforderungen des PRD und die Entscheidungen der Architektur in implementierbare Epics und Stories fuer die Objektsteckbrief-v1-Auslieferung (Launch-Ziel Ende April 2026, 9-Tage-Window, 1 Entwickler Brownfield-Extension).

## Requirements Inventory

### Functional Requirements

**Objekt-Detail & Cluster-Pflege**

- **FR1:** Mitarbeitende koennen eine Objekt-Detailseite aufrufen, die Stammdaten, Technik, Finanzen und Versicherungen in strukturierten Sektionen zeigt.
- **FR2:** Mitarbeitende koennen Stammdatenfelder (Cluster 1) als read-only-Spiegel aus Impower sehen (Adresse, WEG-Nr., Eigentuemerliste mit Stimmrechten).
- **FR3:** Mitarbeitende koennen technische Daten (Cluster 4) pflegen: Absperrpunkte mit Foto + Standortbeschreibung, Heizungs-Steckbrief, Zugangscodes, Objekt-Historie (year_built, year_roof, …).
- **FR4:** Mitarbeitende koennen Finanzdaten (Cluster 6) als Impower-Spiegel sehen (Ruecklage, Wirtschaftsplan-Status, SEPA-Mandate) und den Bank-Saldo als Live-Wert beim Render.
- **FR5:** Mitarbeitende koennen Versicherungs-Portfolio (Cluster 8) pflegen: Policen, Wartungspflichten mit Policen-Verweis, Schadensfaelle. (Risiko-Attribute auf Policen-/Objekt-Ebene = v1.1.)
- **FR6:** Mitarbeitende koennen einen neuen Schadensfall direkt aus der Versicherungs-Sektion des Objekts anlegen.
- **FR7:** Mitarbeitende koennen die Ruecklage-Historie als Zeitreihe (sparkline-artig) pro Objekt einsehen.
- **FR8:** Admins koennen Menschen-Notizen zu Eigentuemern pflegen; diese Notizen sind fuer Nicht-Admin-Rollen nicht sichtbar.
- **FR9:** Mitarbeitende koennen Fotos pro Technik-Komponente hochladen und anzeigen; die Fotos werden in SharePoint gespeichert, das System haelt nur Drive-Item-ID + Metadaten.
- **FR10:** Mitarbeitende koennen Zugangscodes erfassen; das System speichert sie verschluesselt und zeigt sie nur authentifizierten Usern mit `objects:view`-Permission entschluesselt an.

**Portfolio-Navigation & Due-Radar**

- **FR11:** Mitarbeitende koennen alle Objekte in einer Listenansicht mit sortierbaren und filterbaren Spalten sehen (mindestens: Saldo, Ruecklage, Mandat-Status, Pflegegrad).
- **FR12:** Mitarbeitende koennen die Objekt-Listenansicht auch mobil nutzen; auf kleinen Viewports faellt die Tabelle in ein Card-Layout zurueck.
- **FR13:** Mitarbeitende koennen eine Due-Radar-Ansicht aufrufen, die portfolio-weit alle Policen und Wartungspflichten mit Ablauf-Datum innerhalb der naechsten 90 Tage listet. (Verwaltervertraege = Cluster 7, v1.1.)
- **FR14:** Mitarbeitende koennen die Due-Radar-Ansicht nach Eintrags-Typ (Police / Wartung) und nach Ablauf-Schwere (< 30 Tage / < 90 Tage) filtern.
- **FR15:** Mitarbeitende koennen von jedem Due-Radar-Eintrag direkt zur Quell-Entitaet (Objekt, Police, Wartungspflicht) oder zur Registry-Detailseite springen.

**Registries & Aggregationen**

- **FR16:** Mitarbeitende koennen eine Versicherer-Listenansicht aufrufen mit Aggregationen pro Versicherer (Policen-Anzahl, Gesamtpraemie p.a., Schadensquote, Anzahl verbundener Objekte).
- **FR17:** Mitarbeitende koennen eine Versicherer-Detailseite aufrufen mit allen verbundenen Policen, Ablauf-Heatmap, Schadensfaellen und einer Aggregation der verbundenen Objekte.
- **FR18:** Das System fuehrt normalisierte Entitaeten fuer Dienstleister/Handwerker, Bank, Ablesefirma, Eigentuemer, Mieter, Mietvertrag, Zaehler sowie Facilioo-Mirror-Entitaeten als eigenstaendige Tabellen mit Objekt-FKs — auch wenn deren Detailseiten erst in v1.1 entstehen.

**Datenqualitaet & KI-Governance**

- **FR19:** Das System berechnet pro Objekt einen Pflegegrad-Score auf Basis von Feld-Completeness und Aktualitaet, sichtbar als Badge auf Detail- und Listen-Seite.
- **FR20:** Mitarbeitende koennen die Komposition des Pflegegrad-Scores in einer UI-Erlaeuterung nachvollziehen (welche Felder, welche Gewichte).
- **FR21:** Das System protokolliert fuer jeden Schreibvorgang auf einem Steckbrief-Feld einen Provenance-Eintrag (Quelle, Zeitstempel, User bzw. Sync-Job, Confidence bei KI-Vorschlaegen).
- **FR22:** Das System fuehrt eine Review-Queue fuer KI-Vorschlaege mit Ziel-Entitaet, Feldname, vorgeschlagenem Wert, Confidence und Status (pending / approved / rejected / superseded).
- **FR23:** Mitarbeitende koennen Eintraege in der Review-Queue approven oder rejecten; approve schreibt den Wert mit Provenance-Eintrag `ai_suggestion`, reject verwirft den Vorschlag und markiert ihn als abgelehnt.
- **FR24:** Admins koennen die Review-Queue portfolio-weit einsehen und nach Alter, Feld-Typ und Ziel-User filtern.
- **FR25:** Das System verhindert strukturell, dass ein KI-Agent direkt in Steckbrief-Felder schreibt, ohne zuvor einen Review-Queue-Eintrag zu erzeugen.

**Externe Integrationen & Sync**

- **FR26:** Das System spiegelt Impower-Stammdaten (Cluster 1) und Finanzdaten (Cluster 6) periodisch (nightly) in den Steckbrief; jedes gespiegelte Feld erhaelt einen Provenance-Eintrag `impower_mirror`.
- **FR27:** Das System laedt den Bank-Saldo aus Impower live beim Render der Objekt-Detailseite.
- **FR28:** Das System pollt Facilioo-Tickets in Ein-Minuten-Takt und spiegelt sie als `FaciliooTicket`-Entitaet; wenn der Server ETag/If-Modified-Since unterstuetzt, laedt der Job nur Deltas.
- **FR29:** Das System kann Fotos ueber die Microsoft-Graph-API in definierte SharePoint-Ordner pro Objekt hochladen und haelt lokal nur die drive_item_id + Metadaten.
- **FR30:** Das System toleriert zeitweilige Unerreichbarkeit von Impower, Facilioo oder SharePoint ohne User-Seiten-Crash (UI zeigt gecachten Snapshot mit Stale-Hinweis).

**Zugriff, Rollen & Audit**

- **FR31:** Nur Mitarbeitende mit Google-Workspace-Account unter `@dbshome.de` koennen sich anmelden (bestehendes OAuth-Hosted-Domain-Gate wiederverwendet).
- **FR32:** Das System unterstuetzt die Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `registries:view`, `registries:edit`, zuweisbar ueber Rollen oder User-Overrides.
- **FR33:** Das System schreibt fuer alle Steckbrief-Schreibaktionen (Objekt-Anlage, Feld-Edit, Foto-Upload, Review-Queue-Approve/Reject, Registry-Edit) einen Audit-Log-Eintrag mit User, Zeitpunkt und IP.
- **FR34:** Admins koennen die bestehende Audit-Log-View nach Steckbrief-spezifischen Actions filtern.

### NonFunctional Requirements

**Performance**

- **NFR-P1:** Objekt-Detailseite laedt bei 50 Objekten mit P95 < 2 s, inklusive Live-Pull des Bank-Saldos aus Impower. Bei 150 Objekten (Wachstums-Headroom) P95 < 3 s.
- **NFR-P2:** Objekt-Listenansicht mit 50 Zeilen laedt P95 < 1.5 s. Sortier- oder Filter-Wechsel ueber HTMX-Fragment-Swap P95 < 500 ms.
- **NFR-P3:** Due-Radar-Global-View laedt P95 < 2 s bei typischem Volumen (20–30 Eintraege im 90-Tage-Fenster).
- **NFR-P4:** Versicherer-Detailseite mit Aggregationen ueber alle verbundenen Policen laedt P95 < 2 s bei bis zu 20 Policen pro Versicherer.
- **NFR-P5:** Foto-Upload nach SharePoint Graph-API reagiert fuer den User innerhalb P95 < 5 s pro Foto (max. 10 MB); bei groesseren Dateien laeuft der Upload in einer BackgroundTask mit UI-Statusanzeige.

**Security**

- **NFR-S1:** Jeder Zugriff auf UI oder API-Endpoints erfordert eine aktive authentifizierte Session ueber Google Workspace OAuth mit Hosted-Domain-Claim `@dbshome.de`.
- **NFR-S2:** Zugangscodes (`entry_code_main_door`, `entry_code_garage`, Cluster-4-Codes) werden symmetrisch verschluesselt at-rest gespeichert (Schluesselableitung HKDF aus `SECRET_KEY`); Klartext nie in Logs, nie im Audit-Log-Payload.
- **NFR-S3:** Alle Datenuebertragungen zwischen Client und Server laufen ueber TLS (Elestio Reverse-Proxy).
- **NFR-S4:** Schreibende Operationen (Field-Edit, Foto-Upload, Review-Queue-Approve/Reject, Registry-Edit) schreiben in einer Transaktion mit dem zugehoerigen Audit-Log-Eintrag — die beiden Writes sind atomar.
- **NFR-S5:** Menschen-Notizen (FR8) sind ausschliesslich fuer Rollen mit `admin`-Permission sichtbar; serverseitig erzwungen (nicht nur UI-gehiddet).
- **NFR-S6:** Das System enforced strukturell, dass KI-Agenten nicht direkt in Steckbrief-Felder schreiben (FR25). Ein direkter Write-Versuch ohne vorhergehenden Review-Queue-Eintrag wird abgelehnt und im Audit-Log als `policy_violation` markiert.
- **NFR-S7:** HTTP-Response-Header `X-Robots-Tag: noindex, nofollow` wird fuer alle Routen gesetzt; keine Indexierung durch Suchmaschinen moeglich, auch bei Fehlkonfiguration.

**Zuverlaessigkeit & Verfuegbarkeit**

- **NFR-R1:** Die App (unabhaengig von externen APIs) hat ein Verfuegbarkeits-Ziel von 99 % ueber 30 Tage.
- **NFR-R2:** Bei Unerreichbarkeit eines externen Systems (Impower, Facilioo, SharePoint, Anthropic) bleibt die App bedienbar — UI zeigt gecachten Snapshot + Stale-Hinweis, keine 500er-Seiten.
- **NFR-R3:** Der Impower-Nightly-Mirror-Job toleriert einzelne Endpoint-Fehler; ein teilweise fehlgeschlagener Sync wird beim naechsten Lauf fortgesetzt, Status im Admin-Dashboard einsehbar.
- **NFR-R4:** Der Facilioo-1-Min-Mirror-Job hat ein Error-Budget von bis zu 10 % fehlgeschlagenen Polls pro 24h ohne Alert; ueberschritten → Eintrag im Admin-Dashboard.
- **NFR-R5:** BackgroundTasks nutzen je eine eigene DB-Session mit `try/finally`-Close (Plattform-Pattern). Ein Task-Crash blockiert keine User-Session.

**Integrations-Zuverlaessigkeit**

- **NFR-I1:** Der Impower-Client nutzt 120 s Timeout + 5xx-Retry mit Exponential-Backoff (2/5/15/30/60 s, max 5 Versuche). Rate-Limit-Gate (0.12 s Mindestabstand) greift auch fuer den Mirror-Job.
- **NFR-I2:** Der Facilioo-Client hat ein aequivalent gehaertetes Verhalten: Timeout min. 30 s, 5xx-Retry mit Backoff, Rate-Limit-Gate (Default 1 req/s).
- **NFR-I3:** Der SharePoint-Graph-Client nutzt OAuth-Client-Credentials (Service-Account), automatisches Token-Refresh, 429-Retry mit `Retry-After`-Header-Respektierung.
- **NFR-I4:** Bei Anthropic-Client-Fehlern in KI-Vorschlag-Flows (v1.1) wird der Vorschlag nicht erzeugt, ein Audit-Log-Eintrag `ai_suggestion_failed` geschrieben; kein User-Impact, weil KI-Workflows asynchron laufen.
- **NFR-I5:** HTML-Response-Bodies von externen Systemen werden sanitisiert, bevor sie im User-facing-Errortext erscheinen.

**Observability**

- **NFR-O1:** Jede schreibende Aktion im Steckbrief-Modul (Create, Edit, Delete, Approve, Reject, Mirror-Writes) erzeugt einen `AuditLog`-Eintrag mit `user_id`, `user_email`, `action`, `entity_type`, `entity_id`, `ip_address`, `details_json`, `created_at`.
- **NFR-O2:** Die bekannte Action-Liste wird um Steckbrief-Actions erweitert. `docs/architecture.md` §8 ist nach Umsetzung aktualisiert.
- **NFR-O3:** Long-running BackgroundTasks (Impower-Mirror, Facilioo-Mirror, Foto-Upload) loggen Start, Ende und Fehler mit Timestamp in `stdout` (Container-Log) und schreiben einen Audit-Entry, wenn ein Lauf fehlschlaegt.
- **NFR-O4:** Der Pflegegrad-Score ist jederzeit reproduzierbar aus dem DB-Stand heraus — die Formel ist deterministisch und ohne Zufalls- oder Zeit-Abhaengigkeiten (ausser `now()` fuer den Aktualitaets-Decay).
- **NFR-O5:** Fuer Support-Debug: aus dem Admin-Log muss sich zu jedem Feld-Wert zurueckverfolgen lassen, wann er von wem (User oder Sync-Job) auf welchen Wert gesetzt wurde — das leistet die `field_provenance`-Tabelle.

**Skalierung**

- **NFR-SC1:** Ziel-Dimensionierung v1: 50 Objekte, 7 gleichzeitige User, ~10k Audit-Log-Eintraege pro Monat. Keine horizontale Skalierung, keine Autoscaling-Strategie im Scope.
- **NFR-SC2:** Headroom: bei 150 Objekten und 15 Usern muessen Performance-NFRs (NFR-P1..P4) ohne Architektur-Umbau einzuhalten bleiben. Erreichbar durch konservative Indexierung der FK-Spalten und Query-Disziplin.
- **NFR-SC3:** Kein Caching-Layer (kein Redis, kein Memcached) — Postgres + Live-Pull reichen fuer das Volumen. Bei Bedarf spaeter nachziehen, v1 schliesst das strukturell nicht aus.

### Additional Requirements

_Aus dem Architecture Decision Document (`architecture.md`) abgeleitete, implementation-formende Zusatz-Anforderungen._

**Starter-Template & Projekt-Init**

- **Kein Starter-Template** — Brownfield-Extension eines produktiven Python-Monolithen (FastAPI + Jinja2 + HTMX, Python 3.12, Postgres 16, SQLAlchemy 2.0, Alembic). Keine Projekt-Initialisierung noetig; die erste Implementierungs-Story ist stattdessen Fundament-Migration + ORM-Modelle (S1 laut Architektur).

**Neue Dependencies (nur zwei, beide etabliert)**

- `cryptography` (≥43) — `Fernet` + HKDF-Schluesselableitung fuer Field-Encryption (Zugangscodes).
- `msal` (≥1.28) — Microsoft Authentication Library fuer den SharePoint-Graph-Client-Credentials-Flow.

**Ausdrueckliche Non-Dependencies fuer v1**

- Kein Redis / Celery (BackgroundTasks reichen).
- Kein Alembic-Autogenerate (Plattform-Regel — Postgres-JSONB/UUID wird unzuverlaessig gediffed).
- Kein separates Logging-Framework (`print` + `audit()` Plattform-Pattern).
- Kein Client-JS-Framework (HTMX-only).

**Datenmodell-Fundament (CD1)**

- 2 neue Alembic-Revisionen linear auf `0009` aufbauend, handgeschrieben: `0010_steckbrief_core` (Haupt-Entitaeten + Permissions + Audit-Actions-Seed), `0011_steckbrief_governance` (`FieldProvenance` + `ReviewQueueEntry` + `resource_access(resource_type="object")`-Erweiterung).
- ~16 neue ORM-Entitaeten: `Object`, `Unit`, `InsurancePolicy` (Tabelle `policen`), `Wartungspflicht`, `Schadensfall`, `Versicherer`, `Dienstleister`, `Bank`, `Ablesefirma`, `Eigentuemer`, `Mieter`, `Mietvertrag`, `Zaehler`, `FaciliooTicket`, `SteckbriefPhoto`, `FieldProvenance`, `ReviewQueueEntry` (mit `assigned_to_user_id: UUID | None` FK auf `users` — v1 ungenutzt, v1.1-Agenten befuellen das Feld, damit FR24 "Ziel-User"-Filter ohne Migration scharfgeschaltet werden kann). UUID-PKs, `created_at`/`updated_at`, JSONB nur fuer bewusst unstrukturierte Felder.
- Index-Setup: FKs auf Object/Unit/Police; zusaetzlich `Police.next_main_due`, `Wartungspflicht.next_due_date`, `FaciliooTicket.facilioo_id` (unique), `FieldProvenance(entity_type, entity_id, field_name)`, `ReviewQueueEntry(status, created_at)`, `(target_entity_type, target_entity_id)` und `(assigned_to_user_id, status)`.

**Zentralisiertes Write-Gate (CD2 — Core-Innovation v1)**

- Alle Field-Writes auf Steckbrief-Haupt-Entitaeten laufen ueber `app/services/steckbrief_write_gate.py` (`write_field_human`, `write_field_ai_proposal`, `approve_review_entry`, `reject_review_entry`).
- Direktes `entity.field = value` ausserhalb des Gates ist fuer CD1-Haupt-Entitaeten konventionell verboten. Ausnahme: Row-Creation (`db.add(Object(...))`), `FieldProvenance`, `ReviewQueueEntry`, `AuditLog`, `SteckbriefPhoto`-Row-Creation.
- `write_field_ai_proposal` schreibt **nicht** ins Ziel-Feld — Agenten haben keine direkte Write-API, FR25 + NFR-S6 sind strukturell erzwungen.
- Unit-Test grept Sourcen auf verbotene Pattern (Konsistenz-Check).

**Sync-Orchestrator (CD3)**

- Drei Modi mit gemeinsamem Muster (`app/services/_sync_common.py::run_sync_job`): **Nightly-Mirror** (Impower Cluster 1+6 um 02:30), **1-Min-Poll** (Facilioo-Tickets, Delta via ETag/If-Modified-Since), **Live-Pull** (Bank-Saldo im Render-Handler).
- Scheduler-Baustein im FastAPI-Lifespan (kein APScheduler / kein Redis) — `asyncio.create_task` mit Sleep-Loop.
- Status-Persistenz ueber `AuditLog` (`sync_started`/`sync_finished`/`sync_failed`); kein eigenes `SyncRun`-Model.
- Einzel-Item-Fehler brechen den Job nicht ab (NFR-R3). HTML-Error-Bodies werden sanitisiert (`strip_html_error`).

**Permissions-Erweiterung (CD4)**

- 8 neue Permission-Keys: `objects:view`, `objects:edit`, `objects:approve_ki`, `objects:view_confidential`, `registries:view`, `registries:edit`, `due_radar:view`, `sync:admin`.
- Reihenfolge **zwingend**: (1) Key in `app/permissions.py:PERMISSIONS` registrieren → (2) Default-Rollen-Seed in `app/main.py::_seed_default_roles` ergaenzen → (3) Handler per `Depends(require_permission(...))` schuetzen. Sonst scheitert die Admin-UI mit "unknown Permission".
- Default-Rollen: Admin = alle; `user` = `objects:view/edit/approve_ki`, `registries:view/edit`, `due_radar:view`. `objects:view_confidential` + `sync:admin` nur Admin.
- `RESOURCE_TYPE_OBJECT = "object"` als neue Konstante. Tabelle ab Tag 1 befuellbar; Enforcement bleibt v1 "allow all" (v1.1-Scharfschaltung ohne Migration moeglich).

**Audit-Trail-Erweiterung (CD4)**

- ~14 neue Audit-Actions: `object_created`, `object_field_updated`, `object_photo_uploaded`, `object_photo_deleted`, `registry_entry_created`, `registry_entry_updated`, `review_queue_created`, `review_queue_approved`, `review_queue_rejected`, `sync_started`, `sync_finished`, `sync_failed`, `policy_violation`, `encryption_key_missing`.
- Alle ueber `audit()`-Helper in derselben Transaktion wie der Business-Change (NFR-S4). `docs/architecture.md` §8 nach Umsetzung ergaenzen (NFR-O2).

**Field-Level-Encryption (CD5)**

- `cryptography.fernet.Fernet` mit per-Feld-Schluessel aus HKDF: `HKDF(SECRET_KEY, salt=b"steckbrief-v1", info=f"{entity_type}:{field_name}")`.
- Ciphertext-Format `v1:<base64>` mit `key_id`-Praefix → Rotations-faehig (Rotation-Job erst v1.1).
- Schluessel-Quelle `settings.STECKBRIEF_FIELD_KEY` → Fallback `settings.SECRET_KEY`; Dokumentation in `.env.op`.
- Anwendungsfelder v1: `Object.entry_code_main_door`, `Object.entry_code_garage`, `Object.entry_code_technical_room`.
- Klartext-Zugangscodes **nicht** in `AuditLog.details_json` oder Provenance-`value_snapshot`; Marker `{"encrypted": true}`.

**Foto-Pipeline mit Backend-Auto-Fallback (ID1)**

- `PhotoStore`-Protocol mit zwei Implementierungen: `SharePointPhotoStore` (MSAL + Graph) und `LocalPhotoStore` (`uploads/objects/{short_code}/{kategorie}/{sha256}.{ext}`).
- Auswahl via `settings.photo_backend = "sharepoint" | "local"` (Default `"sharepoint"`); Lifespan-Check beim Start — wenn Graph-Auth scheitert, automatisch auf `"local"` fallen + `AuditLog` `sharepoint_init_failed` + WARN-Log.
- Upload-Validierung analog `test_upload.py` (Content-Type-Whitelist jpeg/png, Size-Limit 10 MB, Magic-Bytes-Check). Uploads > 3 MB laufen in BackgroundTask (NFR-P5).

**Pflegegrad-Score (ID3)**

- Deterministische Formel in `app/services/pflegegrad.py`, kein KI-Anteil.
- Gewichtung initial: C1=20 %, C4=30 %, C6=20 %, C8=30 %.
- Aktualitaets-Decay: Feld > 365 Tage alt zaehlt halb, > 1095 Tage zaehlt zu 10 %.
- Listen-Cache-Spalten `Object.pflegegrad_score_cached: int | None` + `pflegegrad_score_updated_at` fuer schnelle Sort-View. Detail-Seite rechnet neu bei Cache > 5 Min; Cache invalidiert automatisch bei jedem `write_field_human`.

**Due-Radar-Query (ID2)**

- `app/services/due_radar.py::list_due_within` als UNION-ALL-Query ueber `policen`, `wartungspflichten`, `management_contract`. Keine Materialized View, keine separate Tabelle.
- Ausgabe: `DueRadarEntry` (Dataclass) mit `kind`, `entity_id`, `object_id`, `object_short_code`, `due_date`, `days_remaining`, `severity`, `title`, `link_url`.
- Enforcement via `accessible_object_ids(db, user)` (v1: alle Objekte fuer alle User).

**HTMX-Fragment-Strategie (ID4)**

- `object_detail.html` unterteilt in 7 Sektions-Fragmente: `_obj_stammdaten.html`, `_obj_technik.html`, `_obj_finanzen.html`, `_obj_versicherungen.html`, `_obj_menschen.html`, `_obj_historie.html`, `_obj_review_queue.html`. Edit-Forms posten an `POST /objects/{id}/sections/{section_key}` → Response = frisches Sektion-Fragment.
- Liste (`objects_list.html`) mit HTMX-Swap des `_obj_table_body.html` bei Sort/Filter.
- BackgroundTask-Status: Meta-Refresh-Pattern aus M5 wiederverwenden.

**Middleware & Header**

- `X-Robots-Tag: noindex, nofollow` als Default-Response-Header (neuer Middleware-Hook in `main.py`, NFR-S7) — trivial, in Fundament-Story mitnehmen.

**Konvention: Mirror vs. User-Edit (Gap G8 — Klaerung)**

- Default-Regel: User-Edit (Provenance `user_edit`) gewinnt ueber `impower_mirror`. Der Mirror ueberschreibt nur, wenn die letzte Provenance ebenfalls `impower_mirror` war. Regel in Fundament-/Mirror-Story testen.

**Externe Abhaengigkeiten (Spike-/Ticket-Anforderungen Tag 1)**

- **Facilioo-API-Spike Tag 1**, Go/No-Go Tag 3 — Swagger + Auth + Delta-Support verifizieren. Fallback: Cluster 3.3 (`open_tickets`) auf v1.1 verschieben; UI zeigt "Ticket-Integration in Vorbereitung".
- **SharePoint M365-Admin-Ticket Tag 1** — Service-Account + App-Registration (`Files.ReadWrite.All`, `Sites.Read.All`). Fallback: `LocalPhotoStore` bleibt aktiv, Migration zu SharePoint nachtraeglich via `drive_item_id`-Update.

**Testing-Delta (zusaetzlich zur Plattform-Testing-Strategie)**

- Neue Unit-Tests: `test_write_gate_unit.py` (Provenance-Pflicht, Audit-Transaktion, Agent-Gate, Coverage-Grep), `test_pflegegrad_unit.py` (Formel-Edge-Cases), `test_field_encryption_unit.py` (Roundtrip + Key-ID + Log-Sanity), `test_due_radar_unit.py` (Zeit-Fenster + Severity + ACL-Filter), `test_photo_store_unit.py` (Backend-Switch + Validierung), `test_facilioo_unit.py` (Delta + 429 + Timeout), `test_sync_common_unit.py` (Einzel-Item-Fehler bricht Job nicht ab).
- Smoke-Tests: `test_steckbrief_routes_smoke.py` fuer `/objects`, `/objects/{id}`, `/registries/versicherer`, `/due-radar` (unauthenticated → 302/303/403; authenticated → 200).
- `conftest.py` um Fixtures fuer `Object`, `InsurancePolicy`, `Versicherer` erweitern.

**Doku-Nachzuege nach Umsetzung**

- `docs/architecture.md` §8: neue Audit-Actions ergaenzen (NFR-O2).
- `docs/api-contracts.md`: neue Routen `/objects`, `/registries/*`, `/due-radar`, `/admin/review-queue`, `/admin/sync-status`.
- `docs/data-models.md`: 16 neue Entitaeten dokumentieren.
- `.env.op`: neue Settings-Refs (`STECKBRIEF_FIELD_KEY`, `PHOTO_BACKEND`, `FACILIOO_*`, `SHAREPOINT_*`).

### UX Design Requirements

_Kein formelles UX-Design-Dokument im Scope vorhanden. UI-Conventions ergeben sich aus `docs/project-context.md` und dem Bestand der Plattform (Sidebar-Layout, Jinja2 + HTMX + Tailwind, Fragment-Templates mit Underscore-Prefix, Status-Pills analog zu M5 `field_source`). Responsive-Anforderung fuer die Notfall-Journey (J2) ist als FR12 erfasst; darueber hinausgehende Design-Token-/Component-Arbeiten werden im v1-MVP nicht als separate Epics gefuehrt._

### FR Coverage Map

| FR | Epic | Bemerkung |
|----|------|-----------|
| FR1 | E1 | Objekt-Detailseite (Stammdaten-Sektion in E1; weitere Cluster-Sektionen erweitert innerhalb von E1) |
| FR2 | E1 | Stammdaten als read-only Impower-Spiegel |
| FR3 | E1 | Technik-Pflege (Absperrpunkte, Heizung, Objekt-Historie) inkl. Foto + Standortbeschreibung |
| FR4 | E1 | Finanzen-Spiegel + Live-Saldo |
| FR5 | E2 | Policen / Wartungspflichten / Schadensfaelle pflegen |
| FR6 | E2 | Schadensfall-Anlage aus Versicherungs-Sektion |
| FR7 | E1 | Ruecklage-Historie Sparkline |
| FR8 | E2 | Menschen-Notizen admin-only |
| FR9 | E1 | Foto-Upload SharePoint mit Local-Fallback |
| FR10 | E1 | Zugangscodes Field-Level-Encryption |
| FR11 | E1 + E3 | E1 = simple Tabelle; E3 = Sortier/Filter-Spalten + Pflegegrad-Spalte |
| FR12 | E3 | Mobile Card-Layout |
| FR13 | E2 | Due-Radar-Global-View (90-Tage-Fenster) |
| FR14 | E2 | Filter Typ + Schwere |
| FR15 | E2 | Deep-Links aus Due-Radar in Quell-Entitaeten / Registries |
| FR16 | E2 | Versicherer-Liste mit Aggregationen |
| FR17 | E2 | Versicherer-Detailseite |
| FR18 | E1 | Normalisierte Registry-Tabellen (Dienstleister/Bank/Mieter/...) angelegt; Detailseiten v1.1 |
| FR19 | E3 | Pflegegrad-Score-Badge |
| FR20 | E3 | Score-Komposition via Info-Popover |
| FR21 | E1 | FieldProvenance-Pflicht via Write-Gate |
| FR22 | E3 | Review-Queue-UI mit Listing / Filtern |
| FR23 | E3 | Approve / Reject-Flow inkl. Provenance-Eintrag |
| FR24 | E3 | Admin-Filter Alter / Feld-Typ / Ziel-User |
| FR25 | E1 | Strukturelle Hart-Grenze (kein direkter KI-Write) via Write-Gate; User-Sichtbarkeit der Policy-Violation in E3 |
| FR26 | E1 | Nightly-Mirror Cluster 1 + 6 |
| FR27 | E1 | Live-Pull Bank-Saldo beim Render |
| FR28 | E4 | Facilioo-1-Min-Polling mit Delta-Support |
| FR29 | E1 | SharePoint-Graph-Upload |
| FR30 | E1 (primary) + E4 (Facilioo-Leg) | Stale-Toleranz je Integration |
| FR31 | E1 | OAuth Hosted-Domain `@dbshome.de` |
| FR32 | E1 | 8 Steckbrief-Permissions + Default-Rollen-Seed |
| FR33 | E1 | Audit-Log-Eintraege fuer alle Steckbrief-Schreibaktionen |
| FR34 | E1 | Audit-Log-View-Filter nach Steckbrief-Actions |

**Alle 34 FRs abgedeckt.**

## Epic List

### Epic 1: Objekt-Zugriff & Pflege

Mitarbeitende koennen sich ueber Google Workspace einloggen, die Objekt-Liste oeffnen und pro Objekt eine komplette Detailseite mit Stammdaten (Impower-Mirror), Technik (Absperrpunkte, Heizung, Objekt-Historie mit Fotos + Standortbeschreibung, verschluesselte Zugangscodes) und Finanzen (Impower-Mirror mit Live-Saldo, Ruecklage-Sparkline, SEPA-Mandate) pflegen. Plattform-Governance (Write-Gate, FieldProvenance, Audit-Log, Steckbrief-Permissions) ist live; das System blockiert strukturell jeden direkten KI-Write. Alle normalisierten Registry-Tabellen (Dienstleister/Bank/Eigentuemer/Mieter/Zaehler/...) stehen als Schema. SharePoint-Graph-Upload mit automatischem Fallback auf Local bei Init-Fehler; Stale-Snapshots bei Impower-/SharePoint-Ausfall statt 500er-Seiten.

**Deckt Journeys:** J1 Lena (Onboarding, Tag 1 im Objekt) komplett, J2 Markus (Bereitschaftsdienst mobil) zum Pflichtteil — Notfall-Fotos + Standortbeschreibung + Heizungs-Hotline.

**FRs covered:** FR1, FR2, FR3, FR4, FR7, FR9, FR10, FR11 (Basic), FR18, FR21, FR25, FR26, FR27, FR29, FR30 (Impower/SharePoint-Leg), FR31, FR32, FR33, FR34

### Epic 2: Versicherungen & Due-Radar

Mitarbeitende pflegen Versicherungs-Portfolio (Policen, Wartungspflichten mit Policen-Verweis, Schadensfaelle inkl. Anlage direkt aus der Versicherungs-Sektion) und vertrauliche Menschen-Notizen zu Eigentuemern (serverseitig admin-only erzwungen). Der Due-Radar zeigt portfolio-weit alle Policen/Wartungspflichten/Vertraege mit Ablauf innerhalb 90 Tagen, filterbar nach Typ und Ablauf-Schwere, mit Deep-Links in Quell-Entitaet oder Registry. Versicherer-Registry liefert Listen- und Detailansicht mit Aggregationen (Policen-Anzahl, Gesamtpraemie p.a., Schadensquote, Ablauf-Heatmap, verbundene Objekte).

**Deckt Journeys:** J4 Julia (Versicherungs-Koordination, Differentiator-Use-Case) komplett. Ergaenzt J2 Markus (Schadensfall-Nachtrag nach Notfall).

**FRs covered:** FR5, FR6, FR8, FR13, FR14, FR15, FR16, FR17

### Epic 3: Portfolio-UX & KI-Governance-Oberflaeche

Petra oeffnet die Objekt-Liste mit sortier- und filterbaren Spalten (Saldo, Ruecklage, Mandat-Status, Pflegegrad) und sieht bei mobiler Nutzung automatisch ein Card-Layout. Ein Pflegegrad-Score-Badge auf Liste und Detail macht Datenqualitaet pro Objekt sichtbar; ein Info-Popover legt die Score-Komposition (Cluster-Gewichte, Aktualitaets-Decay) offen. Daniel oeffnet die Admin-Review-Queue, filtert nach Alter / Feld-Typ / Ziel-User und approved oder rejected KI-Vorschlaege; Approve schreibt den Wert ueber das Write-Gate mit Provenance `ai_suggestion`, Reject markiert den Eintrag und protokolliert eine Entscheidungsbegruendung. Die Queue laeuft v1 ohne aktive KI-Agenten (leer), aber UI und Flow sind durchlauffaehig — v1.1-Agenten docken ohne UI-Umbau an.

**Deckt Journeys:** J3 Petra (Buchhalterin, Monatsabschluss) + J5 Daniel (Admin / Review-Queue-Triage) komplett.

**FRs covered:** FR11 (Enhanced), FR12, FR19, FR20, FR22, FR23, FR24

### Epic 4: Facilioo-Ticket-Integration (Launch-Optional)

Facilioo-Tickets werden ueber ein 1-Minuten-Polling in die `FaciliooTicket`-Tabelle gespiegelt (Delta via ETag/If-Modified-Since, falls Server-Support vorhanden) und am Objekt-Detail sichtbar. Bei Facilioo-Ausfall zeigt das System einen gecachten Snapshot mit Stale-Hinweis, keine 500er. Der Epic ist an die **Tag-3-Go/No-Go-Entscheidung** gekoppelt — bei No-Go wird er auf v1.1 verschoben, die anderen Epics bleiben launch-faehig.

**Deckt Journey:** Ergaenzt J1/J2/J4 um Ticket-Sichtbarkeit; keine Journey haengt kritisch an diesem Epic.

**FRs covered:** FR28, FR30 (Facilioo-Leg)

### Abhaengigkeiten zwischen den Epics

- **E1 ist die Plattform-Basis** (Migration 0010/0011, Write-Gate, ORM-Modelle, Permissions, Audit, alle Registry-Tabellen). Ohne E1 sind E2–E4 nicht sinnvoll umsetzbar.
- **E2 baut auf E1** (Policen-Tabelle existiert via Migration 0010), ist aber inhaltlich eigenstaendig.
- **E3 baut auf E1** und profitiert von E2-Daten (volleres Pflegegrad-Feedback), funktioniert aber auch ohne E2 (Score laeuft auf jedem Daten-Stand deterministisch).
- **E4 ist komplett optional** — Tag-3-Go/No-Go. Kein anderes Epic haengt davon ab.

### Empfohlene Implementations-Reihenfolge

E1 → E2 → E3 → E4. Entspricht dem Journey-Narrativ (Basiszugriff + Pflege → Versicherungs-Pflege + Differentiator → Portfolio-UX + Governance-UI → Integrations-Ausbau) und dem 9-Tage-Puffer-Gedanken (E4 kann spaet entschieden werden).

---

## Epic 1: Objekt-Zugriff & Pflege

Mitarbeitende koennen sich einloggen, die Objekt-Liste oeffnen und pro Objekt eine komplette Detailseite mit Stammdaten (Impower-Mirror), Technik, Finanzen und Fotos pflegen. Plattform-Governance (Write-Gate, FieldProvenance, Audit-Log, Steckbrief-Permissions) ist live; direkte KI-Writes sind strukturell blockiert. SharePoint mit Local-Fallback. Stale-Snapshots statt 500er-Seiten.

### Story 1.1: Steckbrief-Permissions, Audit-Actions & Default-Header

Als Admin der Plattform,
ich moechte die neuen Steckbrief-Permissions in der Admin-UI zuweisen koennen und die neuen Audit-Actions im Audit-Log-Filter sehen,
damit ich Rollen fuer das kommende Steckbrief-Modul vorbereiten und Nachvollziehbarkeit sicherstellen kann.

**Acceptance Criteria:**

**Given** ich bin als Admin eingeloggt
**When** ich `/admin/users/{id}` oeffne
**Then** sehe ich die neuen Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `objects:view_confidential`, `registries:view`, `registries:edit`, `due_radar:view`, `sync:admin` als zuweisbare Eintraege
**And** neue User haben per Default-Rolle `user` die Permissions `objects:view`, `objects:edit`, `objects:approve_ki`, `registries:view`, `registries:edit`, `due_radar:view` (ohne `view_confidential` / `sync:admin`)

**Given** ich bin als Admin eingeloggt
**When** ich `/admin/audit-log` oeffne und den Action-Filter aufklappe
**Then** erscheinen die neuen Actions `object_created`, `object_field_updated`, `object_photo_uploaded`, `object_photo_deleted`, `registry_entry_created`, `registry_entry_updated`, `review_queue_created`, `review_queue_approved`, `review_queue_rejected`, `sync_started`, `sync_finished`, `sync_failed`, `policy_violation`, `encryption_key_missing` in der Auswahl

**Given** eine beliebige HTTP-Response der App
**When** der Browser die Antwort-Header inspiziert
**Then** ist der Header `X-Robots-Tag: noindex, nofollow` gesetzt

**Given** die Plattform-Regel "Permissions zuerst in PERMISSIONS registrieren"
**When** die Lifespan-Seed-Routine laeuft
**Then** bricht keine der neuen Permission-Keys mit "unknown Permission" ab und die Default-Rollen-Tabelle enthaelt die korrekten Zuweisungen

### Story 1.2: Objekt-Datenmodell, Write-Gate & Provenance-Infrastruktur

Als Entwickler im Steckbrief-Modul,
ich moechte ein zentralisiertes Write-Gate mit automatischer FieldProvenance-Erzeugung und struktureller KI-Blockade zur Verfuegung haben,
damit alle nachfolgenden Stories saubere, nachvollziehbare Schreibvorgaenge ohne Policy-Risiko ausfuehren koennen.

**Acceptance Criteria:**

**Given** eine frische Datenbank
**When** `alembic upgrade head` laeuft
**Then** existieren die Tabellen `objects`, `units`, `policen`, `wartungspflichten`, `schadensfaelle`, `versicherer`, `dienstleister`, `banken`, `ablesefirmen`, `eigentuemer`, `mieter`, `mietvertraege`, `zaehler`, `facilioo_tickets`, `steckbrief_photos`, `field_provenance`, `review_queue_entries` mit UUID-PKs, `created_at`/`updated_at` und den in der Architektur definierten Indexen
**And** `resource_access.resource_type` akzeptiert den neuen Wert `"object"`

**Given** ein bestehendes `Object` und ein authentifizierter User mit `objects:edit`
**When** Code `write_field_human(db, entity=obj, field="year_roof", value=2021, source="user_edit", user=user)` aufruft und die Transaktion committed
**Then** ist `obj.year_roof == 2021` persistiert
**And** existiert genau eine neue `FieldProvenance`-Zeile mit `entity_type="object"`, `entity_id=obj.id`, `field_name="year_roof"`, `source="user_edit"`, `user_id=user.id`, `value_snapshot={"old": <prev>, "new": 2021}`
**And** existiert in derselben Transaktion ein `AuditLog`-Eintrag mit `action="object_field_updated"`

**Given** ein KI-Agent ruft `write_field_ai_proposal(target_entity_type="object", target_entity_id=..., field="roof_year", proposed_value=2021, agent_ref="te_scan_agent", confidence=0.8, ...)`
**When** die Funktion ausgefuehrt wird
**Then** wird **nicht** `Object.roof_year` geschrieben
**And** entsteht eine `ReviewQueueEntry`-Zeile mit `status="pending"`
**And** entsteht ein `AuditLog`-Eintrag mit `action="review_queue_created"`

**Given** ein Konsistenz-Check greept die Sourcen nach direktem `entity.field = value` fuer die CD1-Haupt-Entitaeten ausserhalb der erlaubten Ausnahmen (Row-Creation, Governance-Tabellen)
**When** der Check im Unit-Test `test_write_gate_coverage` laeuft
**Then** gibt es keine Funde — alle Field-Writes gehen ueber das Write-Gate

### Story 1.3: Objekt-Liste & Stammdaten-Detailseite

Als Mitarbeiter mit `objects:view`,
ich moechte die Liste aller Objekte oeffnen und pro Objekt eine Detailseite mit Stammdaten sehen,
damit ich einen ersten Ueberblick ueber Adresse, WEG-Nummer und Eigentuemerliste bekomme.

**Acceptance Criteria:**

**Given** ich bin als User mit `objects:view` eingeloggt und es existieren 50 Objekte in der DB
**When** ich `/objects` aufrufe
**Then** sehe ich eine Tabelle mit einer Zeile pro Objekt, Spalten `short_code`, `name`, `Adresse`, `Anzahl Einheiten`
**And** jede Zeile verlinkt auf `/objects/{id}`
**And** die Seite laedt unter 1.5 s P95 bei 50 Zeilen

**Given** ich klicke auf ein Objekt in der Liste
**When** `/objects/{id}` rendert
**Then** sehe ich die Sektion "Stammdaten" mit `short_code`, `name`, `full_address`, `weg_nr`, `impower_property_id`, Eigentuemerliste mit Name + Stimmrecht
**And** jedes Feld zeigt die Provenance-Pill (`impower_mirror` / `user_edit` / `missing`) mit Tooltip (Zeitpunkt + Quelle)

**Given** ich bin **nicht** als User mit `objects:view` eingeloggt (z. B. nur Gast)
**When** ich `/objects` oder `/objects/{id}` aufrufe
**Then** bekomme ich eine 302-Redirect-Response zum Login oder 403

**Given** ein Objekt `obj` ohne Stammdaten aus Impower-Mirror
**When** die Detailseite rendert
**Then** sehe ich ein "noch nicht gesynced"-Hinweisbanner in der Stammdaten-Sektion, keine 500er-Seite

### Story 1.4: Impower-Nightly-Mirror fuer Cluster 1 + 6

Als Mitarbeiter,
ich moechte, dass Stammdaten und Finanzdaten der Objekte nachts automatisch aus Impower gespiegelt werden,
damit ich am Morgen aktuelle Daten auf der Objekt-Detailseite vorfinde, ohne manuellen Aufwand.

**Acceptance Criteria:**

**Given** die App startet
**When** die FastAPI-Lifespan initialisiert wird
**Then** startet ein BackgroundTask, der um 02:30 Uhr lokaler Zeit den Impower-Mirror-Job ausloest
**And** der Job laeuft idempotent (doppelter Start erzeugt keine Duplikate)

**Given** der Mirror-Job laeuft und Impower ist erreichbar
**When** der Job durchlaeuft
**Then** sind alle 50 Objekte mit Cluster-1-Feldern (Adresse, WEG-Nr., Eigentuemerliste) und Cluster-6-Feldern (Ruecklage, Wirtschaftsplan-Status, SEPA-Mandat-Refs) aktualisiert
**And** jedes gespiegelte Feld hat eine neue oder aktualisierte `FieldProvenance`-Zeile mit `source="impower_mirror"` und `source_ref=<Impower-Property-ID>`
**And** ein `AuditLog`-Eintrag `action="sync_started"` und `action="sync_finished"` ist geschrieben

**Given** ein User hat manuell ein Feld per UI geaendert (letzte Provenance = `user_edit`)
**When** der Mirror-Job denselben Feld-Pfad ueberschreiben will
**Then** wird das Feld **nicht** ueberschrieben (User-Edit gewinnt)

**Given** Impower wirft bei einem der 50 Objekte einen 503-Fehler
**When** der Mirror-Job fortsetzt
**Then** wird der Fehler geloggt, die anderen 49 Objekte werden erfolgreich gesynced
**And** ein `AuditLog`-Eintrag `action="sync_failed"` fuer das Einzel-Objekt existiert mit `details_json` inkl. Objekt-ID + Fehlertext (HTML sanitisiert)

**Given** ich oeffne `/admin/sync-status` als Admin
**When** die Seite rendert
**Then** sehe ich Datum und Ergebnis des letzten Mirror-Laufs und eine Liste fehlgeschlagener Objekte

### Story 1.5: Finanzen-Sektion mit Live-Saldo & Ruecklage-Sparkline

Als Mitarbeiter,
ich moechte die Finanzsektion eines Objekts mit aktuellem Bank-Saldo und Ruecklage-Historie sehen,
damit ich den aktuellen Stand ohne Impower-Login beurteilen kann.

**Acceptance Criteria:**

**Given** ich oeffne `/objects/{id}` als User mit `objects:view`
**When** die Finanzen-Sektion rendert
**Then** sehe ich Ruecklage aktuell, Zielwert, Wirtschaftsplan-Status, SEPA-Mandat-Liste (jeweils aus DB-Mirror)
**And** der Bank-Saldo wird live aus Impower nachgeladen und mit Zeitstempel angezeigt
**And** eine Inline-SVG-Sparkline zeigt die Ruecklage-Historie der letzten 6 Monate

**Given** Impower antwortet beim Live-Pull mit Timeout oder 503
**When** die Seite fertig rendert
**Then** sehe ich den letzten bekannten Saldo aus `Object.last_known_balance` mit Hinweis "Saldo aktuell nicht verfuegbar"
**And** die Seite wirft keinen 500er

**Given** die Detailseite mit geladener Finanzsektion
**When** der Seiten-Load gemessen wird
**Then** ist die P95-Render-Zeit inkl. Live-Pull unter 2 s bei 50 Objekten

### Story 1.6: Technik-Sektion mit Inline-Edit

Als Mitarbeiter mit `objects:edit`,
ich moechte die technischen Daten eines Objekts (Absperrpunkte, Heizungs-Steckbrief, Objekt-Historie) direkt auf der Detailseite bearbeiten,
damit ich Wissen aus Begehungen sofort dokumentieren kann.

**Acceptance Criteria:**

**Given** ich oeffne `/objects/{id}` als User mit `objects:edit`
**When** die Technik-Sektion rendert
**Then** sehe ich Felder fuer Absperrpunkte (Wasser / Strom / Gas mit Standortbeschreibung), Heizungs-Typ / Baujahr / Wartungsfirma / Hotline, Objekt-Historie (`year_built`, `year_roof`, `year_heating`, `year_electrics`, ...) mit jeweils einem Edit-Button

**Given** ich klicke auf "Edit" fuer `year_roof` und gebe 2021 ein, dann "Speichern"
**When** die Form submitted
**Then** laeuft der Write durch `write_field_human` mit `source="user_edit"`
**And** die Sektion wird per HTMX-Fragment mit dem neuen Wert und Provenance-Pill `user_edit` geswapped
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` mit `details_json.field == "year_roof"` existiert

**Given** ich bin eingeloggt, aber **ohne** `objects:edit`
**When** ich auf die Technik-Sektion klicke
**Then** sind die Edit-Buttons nicht sichtbar und ein direkter `POST` auf die Edit-Route gibt 403

**Given** der Inline-Edit auf ein Pflichtfeld mit leerem Wert
**When** die Form submitted
**Then** zeigt die Fragment-Response eine Validierungs-Meldung, keine Persistierung

### Story 1.7: Zugangscodes mit Field-Level-Encryption

Als Mitarbeiter mit `objects:edit`,
ich moechte Zugangscodes (Haustuer, Garage, Technikraum) zu einem Objekt hinterlegen und abrufen koennen,
damit ich im Notfall oder bei Begehungen den Code ohne Rueckfrage habe — und die Codes sicher at-rest gespeichert werden.

**Acceptance Criteria:**

**Given** ein Objekt ohne Zugangscodes
**When** ich `entry_code_main_door="1234-5678"` in der Technik-Sektion eingebe und speichere
**Then** wird der Wert vor dem DB-Write ueber `encrypt_field(..., entity_type="object", field="entry_code_main_door", key_id="v1")` in das Format `v1:<base64>` gepackt
**And** die DB-Spalte enthaelt keinen Klartext
**And** die FieldProvenance-`value_snapshot` enthaelt `{"encrypted": true}` statt des Klartexts
**And** der `AuditLog.details_json` enthaelt keinen Klartext

**Given** ich bin als User mit `objects:view` eingeloggt
**When** ich die Technik-Sektion oeffne
**Then** wird der Code on-the-fly entschluesselt angezeigt (ueber `decrypt_field(...)`)
**And** die Entschluesselung nutzt den Schluessel aus `settings.STECKBRIEF_FIELD_KEY` oder Fallback `settings.SECRET_KEY`

**Given** der Schluessel ist nicht gesetzt oder passt nicht zum Ciphertext-Praefix
**When** die Entschluesselung scheitert
**Then** zeigt die UI "Code nicht verfuegbar — Schluessel-Konfiguration pruefen"
**And** ein `AuditLog`-Eintrag `action="encryption_key_missing"` ist geschrieben

### Story 1.8: Foto-Upload mit SharePoint + Local-Fallback

Als Mitarbeiter mit `objects:edit`,
ich moechte Fotos pro technischer Komponente (z.B. Absperrpunkt Wasser) hochladen und in der Technik-Sektion sehen,
damit im Notfall Standort und Zustand klar sind, auch ohne Vor-Ort-Kenntnis.

**Acceptance Criteria:**

**Given** die App startet mit `settings.photo_backend="sharepoint"` und valider MSAL-Konfiguration
**When** die Lifespan-Init den SharePoint-Graph-Client testet
**Then** ist der SharePointPhotoStore aktiv und `/objects/{id}/photos` akzeptiert Uploads

**Given** die App startet mit `settings.photo_backend="sharepoint"` aber der MSAL-Client-Credentials-Flow scheitert
**When** die Lifespan-Init scheitert
**Then** fallback-t das System automatisch auf `LocalPhotoStore`
**And** ein `AuditLog`-Eintrag `action="sharepoint_init_failed"` ist geschrieben
**And** die UI zeigt im Admin-Dashboard einen WARN-Hinweis

**Given** ich lade ein JPEG < 3 MB fuer `component_ref="absperrpunkt_wasser"` hoch
**When** der Upload-Handler es verarbeitet
**Then** wird Content-Type + Magic-Bytes + Size (<= 10 MB) validiert
**And** die Datei landet bei SharePoint unter `SharePoint/DBS/Objekte/{short_code}/technik/` bzw. lokal unter `uploads/objects/{short_code}/technik/{sha256}.jpg`
**And** ein `SteckbriefPhoto`-Record existiert mit `backend`, `drive_item_id` oder `local_path`, `filename`, `component_ref`, `captured_at`, `uploaded_by_user_id`
**And** ein `AuditLog`-Eintrag `action="object_photo_uploaded"` existiert

**Given** ich lade eine Datei > 3 MB hoch
**When** der Upload startet
**Then** laeuft der Upload in einem BackgroundTask (eigene `SessionLocal()` + `try/finally`)
**And** die UI zeigt "Upload laeuft..." mit HTMX-Polling auf den Status-Endpoint

**Given** ich lade eine PDF- oder EXE-Datei hoch
**When** der Handler validiert
**Then** antwortet er mit 400 und einer Fehlermeldung, es wird nichts persistiert

---

## Epic 2: Versicherungen & Due-Radar

Mitarbeitende pflegen Policen, Wartungspflichten und Schadensfaelle am Objekt, sehen vertrauliche Menschen-Notizen admin-only, arbeiten mit einem portfolio-weiten Due-Radar ueber Ablauf-Fristen und nutzen eine Versicherer-Registry mit Aggregationen.

### Story 2.1: Policen pro Objekt pflegen

Als Mitarbeiter mit `objects:edit`,
ich moechte Versicherungspolicen mit Versicherer, Laufzeit und Kuendigungsfrist pro Objekt anlegen und bearbeiten,
damit das Portfolio der Policen an jedem Objekt sichtbar und aktuell ist.

**Acceptance Criteria:**

**Given** ich oeffne `/objects/{id}` und die Versicherungs-Sektion
**When** ich auf "Neue Police" klicke und die Form ausfuelle (Versicherer aus Dropdown, Policen-Nr., Produkt-Typ, `start_date`, `end_date`, `next_main_due`, `notice_period_months`, Praemie p.a.)
**Then** wird nach Submit die Police als `InsurancePolicy` mit FK `versicherer_id` + FK `object_id` angelegt
**And** alle Feld-Writes laufen ueber `write_field_human`
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` mit `entity_type="insurance_policy"` existiert

**Given** eine angelegte Police
**When** ich die Versicherungs-Sektion neu lade
**Then** sehe ich die Police in einer Zeile mit Versicherer, Produkt-Typ, Ablauf-Datum, Kuendigungsfrist und Praemie
**And** jede Zeile hat Edit- und Loeschen-Buttons

**Given** ein Versicherer existiert noch nicht in der Registry
**When** ich "Neuer Versicherer" im Dropdown waehle
**Then** oeffnet sich ein Inline-Modal mit Pflichtfeldern (Name, Adresse, Kontakt) und nach Submit ist der neue `Versicherer`-Record persistiert und ausgewaehlt

**Given** `next_main_due` liegt vor dem `start_date`
**When** ich speichern will
**Then** zeigt die Form einen Validierungsfehler, keine Persistierung

### Story 2.2: Wartungspflichten mit Policen-Verweis

Als Mitarbeiter mit `objects:edit`,
ich moechte Wartungspflichten pro Police mit Dienstleister und Faelligkeits-Datum pflegen,
damit Deckungsbedingungen sichtbar werden und Due-Radar spaeter daraus ziehen kann.

**Acceptance Criteria:**

**Given** eine bestehende Police
**When** ich "Wartungspflicht hinzufuegen" klicke und `Dienstleister`, `intervall_monate`, `letzte_wartung`, `next_due_date` eingebe
**Then** wird ein `Wartungspflicht`-Record mit FK `police_id` + FK `dienstleister_id` + FK `object_id` angelegt
**And** das `next_due_date`-Feld ist fuer Due-Radar indiziert

**Given** eine Police mit mehreren Wartungspflichten
**When** ich die Versicherungs-Sektion rendere
**Then** sehe ich Wartungspflichten expandierbar unter der zugehoerigen Police mit Dienstleister + naechste Faelligkeit

**Given** ich loesche eine Wartungspflicht
**When** der Loesch-Handler ausgefuehrt wird
**Then** wird der Record entfernt, ein `AuditLog`-Eintrag geschrieben und die Sektion per HTMX-Swap aktualisiert

### Story 2.3: Schadensfall direkt aus Objekt anlegen

Als Mitarbeiter mit `objects:edit`,
ich moechte einen Schadensfall direkt aus der Versicherungs-Sektion eines Objekts anlegen,
damit die Versicherer-Schadensquote automatisch aggregiert wird und Dokumentation nicht in Excel landet.

**Acceptance Criteria:**

**Given** ich oeffne die Versicherungs-Sektion und klicke "Schadensfall melden"
**When** ich Police (Dropdown), optional Unit, Datum, geschaetzte Summe und Beschreibung eingebe
**Then** wird ein `Schadensfall`-Record mit FK `police_id` + optional `unit_id` + `estimated_sum` angelegt
**And** ein `AuditLog`-Eintrag existiert

**Given** ein Objekt mit mehreren Schadensfaellen
**When** ich die Versicherungs-Sektion rendere
**Then** sehe ich eine Schadensfall-Liste mit Datum, Police, Unit, Summe, Status

**Given** der geschaetzte Summen-Wert ist 0 oder negativ
**When** ich speichern will
**Then** blockt die Form mit Validierungs-Fehler

### Story 2.4: Menschen-Notizen admin-only

Als Admin mit `objects:view_confidential`,
ich moechte Notizen zu Eigentuemern (z. B. "Beirat, kritisch bei Beschluessen") pflegen, die fuer normale User unsichtbar bleiben,
damit heikle Kontext-Informationen nicht jedem zugaenglich sind, aber fuer Admin-Vorbereitung verfuegbar bleiben.

**Acceptance Criteria:**

**Given** ich bin als Admin mit `objects:view_confidential` eingeloggt
**When** ich `/objects/{id}` oeffne
**Then** sehe ich pro Eigentuemer in der Menschen-Sektion ein freies Notes-Feld (`notes_owners[eigentuemer_id]`), editierbar

**Given** ich bin als normaler User **ohne** `objects:view_confidential`
**When** ich dieselbe Detailseite oeffne
**Then** sehe ich keine Menschen-Notizen (nicht einmal leere Felder)
**And** ein direkter POST auf die Edit-Route des Notes-Feldes gibt 403 — serverseitig, nicht nur UI

**Given** ich bearbeite und speichere eine Notiz als Admin
**When** der Write laeuft
**Then** geht er durch `write_field_human` mit JSONB-Reassignment (nicht Dict-Mutation)
**And** ein `AuditLog`-Eintrag `action="object_field_updated"` existiert

### Story 2.5: Due-Radar Global-View

Als Mitarbeiter mit `due_radar:view`,
ich moechte eine portfolio-weite Liste aller Policen, Wartungspflichten und Verwaltervertraege mit Ablauf innerhalb der naechsten 90 Tage sehen,
damit keine Kuendigungsfenster unbemerkt verstreichen.

**Acceptance Criteria:**

**Given** ich bin als User mit `due_radar:view` eingeloggt
**When** ich `/due-radar` aufrufe
**Then** sehe ich eine Liste aus UNION-ALL-Abfrage ueber `policen` (Feld `next_main_due`) und `wartungspflichten` (Feld `next_due_date`), gefiltert auf <= 90 Tage
**And** jede Zeile zeigt Typ, Objekt-`short_code`, Titel, Faelligkeits-Datum, verbleibende Tage, Severity-Badge (`< 30 Tage` rot / `< 90 Tage` orange)
**And** die Seite laedt unter 2 s P95 bei 20–30 Eintraegen

**Given** keine Eintraege im Fenster
**When** die Seite rendert
**Then** sehe ich einen leeren State "Keine ablaufenden Eintraege in den naechsten 90 Tagen"

### Story 2.6: Due-Radar-Filter & Deep-Links

Als Mitarbeiter mit `due_radar:view`,
ich moechte die Due-Radar-Liste nach Typ und Schwere filtern und pro Eintrag direkt in die Quell-Entitaet springen,
damit ich gezielt priorisieren und Massnahmen ergreifen kann.

**Acceptance Criteria:**

**Given** ich bin auf `/due-radar`
**When** ich den Typ-Filter auf "Police" setze
**Then** wird per HTMX-Fragment-Swap (`_due_radar_rows.html`) nur Policen gezeigt, in <= 500 ms

**Given** ich setze den Severity-Filter auf "< 30 Tage"
**When** die Liste rendert
**Then** sehe ich nur Eintraege mit `days_remaining < 30`
**And** kombiniere ich beide Filter, gelten sie additiv

**Given** ich klicke auf eine Zeile mit `kind="police"`
**When** der Link ausloest
**Then** lande ich auf `/objects/{object_id}` mit Anker `#versicherungen` und Scroll/Highlight zur entsprechenden Police
**And** klicke ich stattdessen auf den Versicherer-Namen, lande ich auf `/registries/versicherer/{id}`

### Story 2.7: Versicherer-Listenansicht mit Aggregationen

Als Mitarbeiter mit `registries:view`,
ich moechte eine Liste aller Versicherer mit aggregierten Kennzahlen sehen,
damit ich Portfolio-Entscheidungen (z. B. Konsolidierung eines Anbieters) datengetrieben vorbereiten kann.

**Acceptance Criteria:**

**Given** ich bin als User mit `registries:view` eingeloggt
**When** ich `/registries/versicherer` aufrufe
**Then** sehe ich eine Tabelle mit einer Zeile pro Versicherer und den Spalten: Name, Policen-Anzahl, Gesamtpraemie p.a. (Summe ueber alle aktiven Policen), Schadensquote (Summe `Schadensfall.estimated_sum` / Gesamtpraemie), verbundene Objekte
**And** die Liste ist sortierbar nach allen numerischen Spalten via HTMX

**Given** ein Versicherer ohne Policen
**When** die Liste rendert
**Then** zeigt die Zeile "0" fuer alle numerischen Spalten und einen dezenten "ungenutzt"-Hinweis

**Given** die Aggregations-Query
**When** sie bei 50 Objekten und typisch ~150 Policen laeuft
**Then** rendert die Seite P95 unter 2 s

### Story 2.8: Versicherer-Detailseite mit Heatmap & Schadensfaellen

Als Mitarbeiter mit `registries:view`,
ich moechte pro Versicherer eine Detailseite mit allen verbundenen Policen, einer Ablauf-Heatmap und der Schadensfall-Historie sehen,
damit ich Kuendigungs- und Neuverhandlungs-Entscheidungen vorbereiten kann.

**Acceptance Criteria:**

**Given** ich bin als User mit `registries:view` eingeloggt
**When** ich `/registries/versicherer/{id}` aufrufe
**Then** sehe ich im Kopf: Name + Adresse + Kontakt des Versicherers, Anzahl Policen, Gesamtpraemie, Schadensquote
**And** darunter eine Ablauf-Heatmap (zeitlicher Balken ueber 12 Monate, rote Markierungen bei ablaufenden Policen < 90 Tage)
**And** eine Tabelle aller verbundenen Policen mit Deep-Link zum jeweiligen Objekt
**And** eine Liste der Schadensfaelle (Datum, Objekt, Unit, Summe)
**And** eine Aggregation "verbundene Objekte" mit Liste und Objekt-Links

**Given** die Detailseite mit bis zu 20 Policen
**When** sie rendert
**Then** ist P95 unter 2 s

---

## Epic 3: Portfolio-UX & KI-Governance-Oberflaeche

Petra findet ueber die erweiterte Objekt-Liste und den Pflegegrad-Score schnell die priorisierten Objekte; Daniel triagiert die Review-Queue als Governance-Plattform-Primitive.

### Story 3.1: Objekt-Liste mit Sortierung & Filter

Als Mitarbeiter mit `objects:view`,
ich moechte die Objekt-Liste nach Saldo, Ruecklage, Mandat-Status und Pflegegrad sortieren und filtern,
damit ich beim Monatsabschluss die Objekte mit Handlungsbedarf zuerst sehe.

**Acceptance Criteria:**

**Given** ich bin auf `/objects` als User mit `objects:view`
**When** die Liste rendert
**Then** sehe ich Spalten `short_code`, `name`, `saldo`, `reserve_current`, `mandat_status`, `pflegegrad`
**And** Header-Klick sortiert ab-/aufsteigend, HTMX-Fragment-Swap unter 500 ms

**Given** ich waehle im Filter "Ruecklage < Zielwert"
**When** der Filter greift
**Then** wird per HTMX nur ein Subset der Zeilen gezeigt, kombinierbar mit Sort

**Given** ein Objekt hat `reserve_current < reserve_target_monthly × 6`
**When** die Zeile rendert
**Then** zeigt die Ruecklage-Spalte einen roten Badge "unter Zielwert"

**Given** der Pflegegrad-Score-Cache auf `Object.pflegegrad_score_cached` ist gesetzt
**When** die Liste sortiert
**Then** nutzt sie den Cache-Wert (kein On-the-fly-Compute pro Zeile)

### Story 3.2: Mobile Card-Layout

Als Mitarbeiter im Bereitschaftsdienst (J2 Markus),
ich moechte die Objekt-Liste auch auf dem Smartphone nutzbar sehen,
damit ich unterwegs Objekte finden und oeffnen kann.

**Acceptance Criteria:**

**Given** ich rufe `/objects` auf einem Viewport < 640 px auf
**When** die Seite rendert
**Then** faellt die Tabelle in ein Card-Layout zurueck (eine Karte pro Objekt, Touch-Targets >= 44 px)
**And** jede Karte zeigt `short_code`, `name`, `saldo`, `pflegegrad` und ist vollflaechig klickbar

**Given** ich rufe `/objects/{id}` mobil auf
**When** die Seite rendert
**Then** sind die Sektionen vertikal gestapelt, Fotos swipebar, die Heizungs-Hotline ist prominent (Tap-to-call-Link)

### Story 3.3: Pflegegrad-Score-Service

Als Entwickler,
ich moechte einen deterministischen Service, der pro Objekt einen Pflegegrad-Score aus Completeness + Aktualitaet berechnet,
damit Badge und Portfolio-Sort konsistent und reproduzierbar arbeiten.

**Acceptance Criteria:**

**Given** ein Objekt mit allen Cluster-1/4/6/8-Pflichtfeldern befuellt und keiner `FieldProvenance` aelter als 365 Tage
**When** `pflegegrad_score(obj)` aufgerufen wird
**Then** liefert er Score 100 und eine `per_cluster`-Map mit jeweils 100 %
**And** `weakest_fields` ist leer

**Given** ein Objekt mit nur Cluster-1 vollstaendig und Cluster 4/6/8 leer
**When** der Score berechnet wird
**Then** liegt der Score bei ~20 (C1 20 % Gewichtung × 100) ± Rundung
**And** `weakest_fields` listet die fehlenden Cluster 4/6/8-Pflichtfelder

**Given** ein Objekt mit Cluster-4-Werten, deren Provenance > 1095 Tage alt ist
**When** der Score berechnet wird
**Then** zaehlen diese Werte zu 10 % (Aktualitaets-Decay)

**Given** jeder erfolgreiche `write_field_human(entity=obj, ...)`
**When** der Write committed wird
**Then** wird `Object.pflegegrad_score_cached` invalidiert (auf `NULL` gesetzt, Recompute lazy)

### Story 3.4: Pflegegrad-Badge & Komposition-Popover

Als Mitarbeiter,
ich moechte den Pflegegrad-Score als Badge auf Liste und Detail sehen und bei Bedarf die Komposition nachvollziehen koennen,
damit ich verstehe, warum ein Objekt schlecht bewertet ist und welche Felder ich pflegen kann.

**Acceptance Criteria:**

**Given** ein Objekt mit Score 72
**When** ich die Detail- oder Listen-Seite rendere
**Then** sehe ich einen farbkodierten Badge "Pflegegrad 72 %" (Gruen ≥ 70, Gelb 40–69, Rot < 40)

**Given** ich klicke auf den Badge
**When** das Popover oeffnet
**Then** sehe ich pro Cluster die Completeness (z. B. "Cluster 4: 60 %") mit Gewicht (`C4 = 30 %`)
**And** die `weakest_fields`-Liste mit Deep-Links zum Anker in der Detailseite (z. B. `#year_roof`)

### Story 3.5: Review-Queue-Admin-UI mit Filtern

Als Admin mit `objects:approve_ki`,
ich moechte eine portfolio-weite Review-Queue mit Filter-Optionen sehen,
damit ich KI-Vorschlaege gezielt abarbeiten und Queue-Halden verhindern kann.

**Acceptance Criteria:**

**Given** ich bin als Admin eingeloggt
**When** ich `/admin/review-queue` aufrufe
**Then** sehe ich eine Liste aller `ReviewQueueEntry`-Zeilen mit `status="pending"` (sortiert nach `created_at` aufsteigend)
**And** pro Zeile: Ziel-Entitaet (`target_entity_type/id`, klickbar), Feldname, vorgeschlagener Wert (truncated bei > 100 Zeichen), Agent-Ref, Confidence, Alter in Tagen

**Given** ich setze den Filter "Alter > 3 Tage"
**When** der Filter greift
**Then** wird per HTMX nur das entsprechende Subset angezeigt
**And** Filter nach `field_name` und `assigned_to_user_id` (Ziel-User, FR24) funktionieren analog

**Given** die Queue ist v1 leer (keine aktiven KI-Agenten)
**When** die Seite rendert
**Then** sehe ich einen leeren State "Keine Vorschlaege offen"
**And** die UI ist ohne Fehler durchklickbar

**Given** ich bin **nicht** Admin (ohne `objects:approve_ki`)
**When** ich `/admin/review-queue` aufrufe
**Then** bekomme ich 403

### Story 3.6: Review-Queue Approve/Reject

Als Admin mit `objects:approve_ki`,
ich moechte einzelne Queue-Eintraege approven oder rejecten,
damit KI-Vorschlaege kontrolliert in den Steckbrief einfliessen oder abgewiesen werden.

**Acceptance Criteria:**

**Given** ein `ReviewQueueEntry` im Status `pending`
**When** ich "Approve" klicke
**Then** ruft der Handler `approve_review_entry()` im Write-Gate
**And** ein `write_field_human(..., source="ai_suggestion", user=<current_user>, confidence=<entry.confidence>, source_ref=<entry.agent_ref>)` persistiert den Wert auf der Ziel-Entitaet
**And** der Queue-Eintrag wechselt auf `status="approved"` mit `decided_at`, `decided_by_user_id=current_user.id`
**And** ein `AuditLog`-Eintrag `action="review_queue_approved"` ist geschrieben (atomar in derselben Transaktion)

**Given** ein `ReviewQueueEntry` im Status `pending`
**When** ich "Reject" klicke und einen Grund eingebe
**Then** wechselt der Status auf `rejected`, `decision_reason` ist gesetzt, kein Feld-Write auf der Ziel-Entitaet
**And** ein `AuditLog`-Eintrag `action="review_queue_rejected"` ist geschrieben

**Given** zwei Queue-Eintraege auf dasselbe Feld derselben Entitaet
**When** der erste approved wird
**Then** wechselt der zweite automatisch auf `status="superseded"` (aelterer Vorschlag verliert)

---

## Epic 4: Facilioo-Ticket-Integration (Launch-Optional)

Facilioo-Tickets werden minuetlich gespiegelt und am Objekt-Detail sichtbar. Der Epic ist an die Tag-3-Go/No-Go-Entscheidung gekoppelt.

### Story 4.1: Facilioo-API-Spike

Als Entwickler,
ich moechte an Tag 1 die Facilioo-API auf Auth, DTO-Struktur und Delta-Support pruefen,
damit wir an Tag 3 eine belastbare Go/No-Go-Entscheidung fuer v1 haben.

**Acceptance Criteria:**

**Given** ich habe API-Zugang zum Facilioo-Tenant
**When** ich die Swagger-/OpenAPI-Doku sichte und drei Test-Calls (Auth-Exchange, Ticket-Liste, Ticket-Delta) ausfuehre
**Then** dokumentiere ich in `docs/integration/facilioo-spike.md`: Auth-Flow, Pagination-Muster, verfuegbare Rate-Limits, ETag/If-Modified-Since-Support, DTO-Shape fuer Ticket-Liste

**Given** das Spike-Dokument
**When** es eingereicht wird
**Then** enthaelt es eine explizite Go/No-Go-Empfehlung + Liste der Abhaengigkeiten fuer v1 (z. B. "Delta-Support fehlt — Full-Pull-Fallback noetig")
**And** das Dokument verweist auf die relevanten Stories 4.2/4.3/4.4

### Story 4.2: Facilioo-Client mit Retry & Rate-Gate

Als Entwickler,
ich moechte einen hartgeharteten Facilioo-Client nach Impower-Muster,
damit der nachfolgende Mirror-Job robust gegen 5xx, Timeouts und Rate-Limits laeuft.

**Acceptance Criteria:**

**Given** der neue Client `app/services/facilioo.py`
**When** er instanziiert wird
**Then** nutzt er einen httpx-`AsyncClient`-Singleton mit Timeout >= 30 s, 5xx-Retry mit Exponential-Backoff (2/5/15/30/60 s, max 5 Versuche), Rate-Limit-Gate (Default 1 req/s)

**Given** ein 429-Response mit `Retry-After`-Header
**When** der Client den Retry plant
**Then** respektiert er den `Retry-After`-Wert

**Given** eine HTML-Error-Page-Response statt JSON
**When** der Client parsed
**Then** wird die HTML-Message via `strip_html_error` sanitisiert und als `FaciliooError` geworfen

**Given** keine Datei ausserhalb von `facilioo.py` nutzt `httpx.AsyncClient` fuer Facilioo-Calls
**When** der Unit-Test `test_facilioo_client_boundary` greept
**Then** gibt es keine Funde

### Story 4.3: 1-Min-Poll-Job mit Delta-Support

Als Mitarbeiter,
ich moechte, dass Facilioo-Tickets automatisch und minuetlich in die Steckbrief-DB gespiegelt werden,
damit ich offene Tickets am Objekt-Detail sehen kann, ohne Facilioo separat zu oeffnen.

**Acceptance Criteria:**

**Given** die App startet
**When** die Lifespan-Init laeuft
**Then** startet `facilioo_mirror.start_poller()` eine asyncio-Loop mit `await asyncio.sleep(60)`
**And** der Loop ist idempotent gegen doppelten Start

**Given** Facilioo unterstuetzt ETag
**When** der Poll laeuft
**Then** sendet der Job den letzten `ETag` mit und liest nur Deltas
**And** `FaciliooTicket`-Zeilen werden via Upsert aktualisiert

**Given** Facilioo unterstuetzt keinen Delta-Mechanismus
**When** der Poll laeuft
**Then** macht der Job einen Full-Pull und diff-t auf `facilioo_id` (unique) — neue Tickets insert, geaenderte update, fehlende mark als `archived`

**Given** das Error-Budget von 10 % fehlgeschlagenen Polls in 24h ist ueberschritten
**When** der naechste Poll-Fehler auftritt
**Then** existiert ein `AuditLog`-Eintrag `action="sync_failed"` und das Admin-Dashboard zeigt einen Alert

### Story 4.4: Facilioo-Tickets am Objekt-Detail

Als Mitarbeiter mit `objects:view`,
ich moechte offene Facilioo-Tickets am Objekt-Detail sehen,
damit ich bei Anruf oder Anfrage weiss, welche Themen schon im System laufen.

**Acceptance Criteria:**

**Given** ein Objekt mit N offenen Facilioo-Tickets
**When** ich `/objects/{id}` oeffne
**Then** sehe ich in der Menschen-/Vorgang-Sektion eine Liste der Tickets (Titel, Datum, Status, optional Eigentuemer/Mieter-Bezug)
**And** jedes Ticket verlinkt auf Facilioo direkt

**Given** die Facilioo-Synchronisation ist gerade nicht erreichbar (letzter erfolgreicher Poll > 10 Min her)
**When** die Seite rendert
**Then** sehe ich den letzten bekannten Snapshot mit Stale-Hinweis "Letzte Aktualisierung: vor X Minuten"
**And** die Seite wirft keinen 500er

**Given** der Facilioo-Epic wurde bei Tag-3-No-Go auf v1.1 verschoben
**When** Facilioo-Mirror nicht laeuft und `FaciliooTicket` leer ist
**Then** zeigt die Sektion einen Platzhalter "Ticket-Integration in Vorbereitung" ohne Fehlermeldung
