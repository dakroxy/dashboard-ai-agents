# Story 1.8: Foto-Upload mit SharePoint + Local-Fallback

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter mit `objects:edit`,
ich möchte Fotos pro technischer Komponente (z.B. Absperrpunkt Wasser) hochladen und in der Technik-Sektion sehen,
damit im Notfall Standort und Zustand klar sind, auch ohne Vor-Ort-Kenntnis.

## Acceptance Criteria

**AC1 — SharePoint-Init: Fallback auf LocalPhotoStore bei MSAL-Fehler**

**Given** die App startet mit `settings.photo_backend="sharepoint"` und valider MSAL-Konfiguration
**When** die Lifespan-Init den SharePoint-Graph-Client testet
**Then** ist der SharePointPhotoStore aktiv und `/objects/{id}/photos` akzeptiert Uploads

**Given** die App startet mit `settings.photo_backend="sharepoint"` aber der MSAL-Client-Credentials-Flow scheitert
**When** die Lifespan-Init scheitert
**Then** fallback-t das System automatisch auf `LocalPhotoStore`
**And** ein `AuditLog`-Eintrag `action="sharepoint_init_failed"` existiert
**And** die Admin-Dashboard-Startseite (`/admin`) zeigt einen WARN-Hinweis

**AC2 — Validierter Upload: Content-Type + Magic-Bytes + Größe + Persistenz**

**Given** ich lade ein JPEG (< 3 MB) für `component_ref="absperrpunkt_wasser"` hoch
**When** der Upload-Handler es verarbeitet
**Then** wird Content-Type + Magic-Bytes + Size (<= 10 MB) validiert
**And** die Datei landet lokal unter `uploads/objects/{short_code}/technik/{sha256}.jpg`
  oder bei SharePoint unter `SharePoint/DBS/Objekte/{short_code}/technik/`
**And** ein `SteckbriefPhoto`-Record existiert mit `backend`, `drive_item_id` oder `local_path`,
  `filename`, `component_ref`, `captured_at`, `uploaded_by_user_id`
**And** ein `AuditLog`-Eintrag `action="object_photo_uploaded"` existiert

**AC3 — Großer Upload (>= 3 MB): BackgroundTask + HTMX-Polling**

**Given** ich lade eine Datei >= 3 MB hoch
**When** der Upload startet
**Then** läuft der eigentliche Store-Upload in einem BackgroundTask (eigene `SessionLocal()` + `try/finally`)
**And** die UI zeigt sofort "Upload läuft..." mit HTMX-Polling auf den Status-Endpoint alle 3 s
**And** nach Abschluss aktualisiert das Polling-Fragment das `<img>`-Card in der Technik-Sektion

**AC4 — Ungültige Dateitypen: 400**

**Given** ich lade eine PDF- oder EXE-Datei hoch
**When** der Handler die Datei validiert
**Then** antwortet er mit 400 und einer deutschen Fehlermeldung, es wird nichts persistiert

**AC5 — Foto-Anzeige + Löschen**

**Given** ein Objekt hat gespeicherte Fotos
**When** ich die Objekt-Detailseite lade
**Then** sehe ich die Fotos in der Technik-Sektion, gruppiert nach Komponente
**And** als User mit `objects:edit` gibt es einen Lösch-Button pro Foto
**And** nach Löschen entsteht ein `AuditLog`-Eintrag `action="object_photo_deleted"`
**And** das Foto-Element verschwindet per HTMX-Swap ohne Page-Reload

**AC6 — Permission-Gate**

**Given** ein User ohne `objects:edit`
**When** er `POST /objects/{id}/photos` aufruft
**Then** gibt es 403 (serverseitig, nicht nur UI)

**AC7 — Tests + Regression**

**Given** neue Datei `tests/test_photo_store_unit.py`
**When** `pytest -x` läuft
**Then** alle bestehenden Tests (>= 446, Stand nach Story 1.7) + die ~12 neuen Unit-Tests aus `test_photo_store_unit.py` sind grün

**AC8 — Scope-Erweiterung gegenüber Epic 1.8: Impower-Object-Discover im Nightly-Mirror** (siehe Task 12 für Kontext + Rationale)

**Given** der Nightly-Mirror lädt den Impower-Properties-Snapshot via `_fetch_impower_snapshot()`
**When** der Snapshot eine `propertyId` enthält, für die kein `Object` mit passender `impower_property_id` existiert
**Then** legt der Mirror **vor** dem Reconcile-Loop ein neues `Object` per `db.add(Object(...))` an (Row-Creation — Ausnahme vom Write-Gate, vgl. CD2)
**And** `impower_property_id` ist gesetzt
**And** `full_address` wird via vorhandenem `_build_full_address(prop)`-Helper berechnet (konsistent mit dem `_reconcile_object`-Pfad, damit der nachfolgende Reconcile nicht sofort dieselben Felder überschreibt und doppelte `FieldProvenance`-Rows erzeugt)
**And** `short_code` + `name` werden aus den gleichen Impower-Property-Keys gemappt, die `_reconcile_object` verwendet (falls dort noch nicht gespiegelt: vorerst `NULL` lassen und allein den `_reconcile_object`-Pfad gewinnen lassen — nicht im Discover raten)
**And** das neu angelegte Object läuft in derselben Lauf-Iteration durch den bestehenden `_reconcile_object`-Pfad

**Given** ein Impower-Property wurde in einem früheren Lauf bereits gediscovert
**When** der Discover-Loop dieselbe `propertyId` erneut sieht
**Then** wird kein neues Object erzeugt (idempotent via Lookup-Set aus `select(Object.impower_property_id)`)

**Given** ein Discover-Lauf hat n neue Objekte angelegt
**When** `/admin/sync-status` gerendert wird
**Then** zeigt die „Letzter Lauf"-Karte einen neuen Counter `Neu entdeckt: n`
**And** dieselbe Spalte erscheint in der Historien-Tabelle (Header + Body)

## Tasks / Subtasks

- [x] **Task 1 — Migration 0014: `steckbrief_photos` Schema-Erweiterung + ORM-Update** (AC2, AC5)
  - [x] 1.1 Vor Anlage: `ls migrations/versions/` ausführen → neueste ist `0013_steckbrief_cluster4_fields.py`; `down_revision = "0013"` setzen.
  - [x] 1.2 Neue Datei `migrations/versions/0014_steckbrief_photos_fields.py`. Zweck: ergänzt fehlende Spalten an der bereits bestehenden `steckbrief_photos`-Tabelle (aus Migration 0010). Kein `op.create_table` — nur `op.add_column` für jede fehlende Spalte:
    ```python
    """steckbrief_photos: backend + filename + component_ref + captured_at + uploaded_by_user_id"""
    from typing import Sequence, Union
    import sqlalchemy as sa
    from alembic import op
    from sqlalchemy.dialects import postgresql

    revision: str = "0014"
    down_revision: Union[str, None] = "0013"
    branch_labels: Union[str, Sequence[str], None] = None
    depends_on: Union[str, Sequence[str], None] = None

    def upgrade() -> None:
        op.add_column("steckbrief_photos",
            sa.Column("backend", sa.String(), nullable=False, server_default="local"))
        op.add_column("steckbrief_photos",
            sa.Column("filename", sa.String(), nullable=False, server_default=""))
        op.add_column("steckbrief_photos",
            sa.Column("component_ref", sa.String(), nullable=True))
        op.add_column("steckbrief_photos",
            sa.Column("captured_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False))
        op.add_column("steckbrief_photos",
            sa.Column("uploaded_by_user_id",
                      postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"),
                      nullable=True))
        op.create_index("ix_steckbrief_photos_component_ref",
                        "steckbrief_photos", ["component_ref"])

    def downgrade() -> None:
        op.drop_index("ix_steckbrief_photos_component_ref",
                      table_name="steckbrief_photos")
        op.drop_column("steckbrief_photos", "uploaded_by_user_id")
        op.drop_column("steckbrief_photos", "captured_at")
        op.drop_column("steckbrief_photos", "component_ref")
        op.drop_column("steckbrief_photos", "filename")
        op.drop_column("steckbrief_photos", "backend")
    ```
  - [x] 1.3 `app/models/object.py`: `SteckbriefPhoto`-Klasse um neue Felder erweitern. Die neuen Felder kommen **nach** `unit_id` und **vor** `drive_item_id` (logische Gruppierung). Das bestehende `label`-Feld bleibt erhalten:
    ```python
    backend: Mapped[str] = mapped_column(String, nullable=False, default="local")
    filename: Mapped[str] = mapped_column(String, nullable=False, default="")
    component_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    ```
    Benötigte Imports prüfen: `ForeignKey` aus `sqlalchemy`, `datetime` aus `datetime` — beide bereits im Modul vorhanden (für `FieldProvenance`-ähnliche Muster).
  - [x] 1.4 `app/models/__init__.py` — kein Änderungsbedarf; `SteckbriefPhoto` ist bereits re-exportiert (Zeile 8 + 31).

- [x] **Task 2 — `pyproject.toml` + `app/config.py` + `.env.op` erweitern** (AC1)
  - [x] 2.1 `pyproject.toml` unter `[project] dependencies`: `"msal>=1.28",` nach `"cryptography>=43"` ergänzen.
  - [x] 2.2 `app/config.py` in der `Settings`-Klasse nach `steckbrief_field_key` ergänzen:
    ```python
    # Foto-Backend (ID1 — Photo-Pipeline)
    # Bewusste Abweichung von architecture.md §ID1 (Default "sharepoint"):
    # Default "local" vermeidet M365-Admin-Ticket fuer lokale Entwicklung.
    # Prod setzt PHOTO_BACKEND=sharepoint via Env-Override (Elestio).
    photo_backend: str = "local"  # "sharepoint" | "local"
    sharepoint_tenant_id: str = ""
    sharepoint_client_id: str = ""
    sharepoint_client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_drive_id: str = ""
    ```
  - [x] 2.3 `.env.op` nach der `STECKBRIEF_FIELD_KEY`-Sektion ergänzen:
    ```
    # Foto-Backend (ID1 — Photo-Pipeline)
    # "local" = uploads/objects/ (Default Dev, kein M365-Admin-Ticket erforderlich)
    # "sharepoint" = SharePoint-Graph-API (Prod, erfordert M365-Admin-Ticket)
    PHOTO_BACKEND=local
    SHAREPOINT_TENANT_ID=
    SHAREPOINT_CLIENT_ID=
    SHAREPOINT_CLIENT_SECRET=
    SHAREPOINT_SITE_ID=
    SHAREPOINT_DRIVE_ID=
    ```

- [x] **Task 3 — `app/services/photo_store.py` (NEU)** (AC1–AC4)
  - [x] 3.1 Neue Datei. Vollständige Implementierung:
    - **Konstanten + Typen:**
      ```python
      ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png"})
      MAGIC_BYTES: dict[str, bytes] = {
          "image/jpeg": b"\xff\xd8\xff",
          "image/png": b"\x89PNG\r\n\x1a\n",
      }
      MAX_SIZE_BYTES: int = 10 * 1024 * 1024   # 10 MB
      LARGE_UPLOAD_THRESHOLD: int = 3 * 1024 * 1024  # >= 3 MB → BackgroundTask

      class PhotoValidationError(Exception):
          pass

      class PhotoRef(BaseModel):
          backend: Literal["sharepoint", "local"]
          drive_item_id: str | None
          local_path: str | None
          filename: str
      ```
    - **`validate_photo(content: bytes, content_type: str) -> None`:** prüft in Reihenfolge: (1) `content_type in ALLOWED_CONTENT_TYPES` → sonst `PhotoValidationError("Nur JPEG und PNG erlaubt.")`, (2) Magic-Bytes der ersten Bytes passen zu `content_type` → sonst `PhotoValidationError("Dateiinhalt passt nicht zum Typ.")`, (3) `len(content) <= MAX_SIZE_BYTES` → sonst `PhotoValidationError("Datei zu groß. Maximum: 10 MB.")`. PNG braucht 8 Bytes für Magic-Check; JPEG 3 Bytes.
    - **`PhotoStore` Protocol (`runtime_checkable`):**
      ```python
      @runtime_checkable
      class PhotoStore(Protocol):
          backend_name: str  # "sharepoint" oder "local"
          async def upload(self, *, object_short_code: str, category: str,
                           filename: str, content: bytes, content_type: str) -> PhotoRef: ...
          async def delete(self, ref: PhotoRef) -> None: ...
      ```
      **Bewusst nicht im v1-Protocol**: `async def url(self, ref) -> str` (temporaerer Download-Link) — architecture.md §ID1 listet die Methode auf, sie ist aber auf v1.1 verschoben (siehe Dev Notes §7 + deferred-work.md). `SharePointPhotoStore`-Fotos zeigen in v1 nur den Dateinamen, nicht das Thumbnail.
    - **`LocalPhotoStore`:**
      - `backend_name = "local"`
      - `upload()`: `sha256 = hashlib.sha256(content).hexdigest()`, Extension aus `filename` oder aus content_type (`jpeg`/`png`), Pfad = `Path(f"uploads/objects/{object_short_code}/{category}/{sha256}.{ext}")`, `path.parent.mkdir(parents=True, exist_ok=True)`, `path.write_bytes(content)`, return `PhotoRef(backend="local", local_path=str(path), drive_item_id=None, filename=filename)`
      - `delete(ref)`: `if ref.local_path: Path(ref.local_path).unlink(missing_ok=True)`
    - **`SharePointPhotoStore`:**
      - `backend_name = "sharepoint"`
      - `__init__(tenant_id, client_id, client_secret, site_id, drive_id)`: legt `msal.ConfidentialClientApplication(...)` + `httpx.AsyncClient(timeout=30.0)` an
      - `_get_token() -> str`: `app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])["access_token"]`. MSAL cached Tokens automatisch (TTL ~1h).
      - `upload()`: `PUT https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{object_short_code}/{category}/{filename}:/content` mit Authorization-Header + Content-Type-Header + `content` als Body. Response enthält `id` → `drive_item_id`. Return `PhotoRef(backend="sharepoint", drive_item_id=item_id, filename=filename, local_path=None)`.
      
        **Pfad-Annahme**: `drive_id` zeigt auf die SharePoint-Library `DBS/Objekte` (durch M365-Admin bei Setup konfiguriert). Damit ist der vollstaendige Speicherort `SharePoint/DBS/Objekte/{object_short_code}/{category}/{filename}` — matched AC2 + architecture.md §ID1. Zeigt `drive_id` stattdessen auf die Site-Root, muss der Praefix `DBS/Objekte/` explizit in die URL (`root:/DBS/Objekte/{object_short_code}/...`). Entscheidung beim M365-Ticket klären und in `.env.op` kommentieren.
      - `delete(ref)`: `DELETE https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{ref.drive_item_id}` — bei 404 kein Fehler werfen (idempotent).
      - **Fehlerbehandlung**: `httpx.HTTPStatusError` (nach `response.raise_for_status()`) wird in `upload()` / `delete()` gefangen und als `PhotoStoreError(f"SharePoint-{op}: {status} {body}")` re-raised. Der Router-Code im BackgroundTask fängt jede `Exception` ab (Task 7.5 — Status `error` in `photo_metadata`); der synchrone Upload-Pfad laesst die Exception propagieren und FastAPI mappt auf 500.
    - **`async def create_photo_store(settings) -> PhotoStore`:** Wenn `settings.photo_backend == "sharepoint"` UND alle Credentials non-empty: `SharePointPhotoStore(...)` instanziieren, einen Test-Token holen (`_get_token()`); wenn das scheitert → `LocalPhotoStore()` zurückgeben. Wenn `photo_backend != "sharepoint"` oder Credentials fehlen: direkt `LocalPhotoStore()`.
  - [x] 3.2 `PhotoStoreError(Exception)` ebenfalls in dieser Datei — für interne Fehler des SharePoint-Clients.
  - [x] 3.3 **Kein Import auf Modul-Ebene von `app.config`** — `create_photo_store` nimmt `settings` als Parameter.

- [x] **Task 4 — `app/services/audit.py`: `sharepoint_init_failed` ergänzen** (AC1)
  - [x] 4.1 In `KNOWN_AUDIT_ACTIONS` nach `"object_photo_deleted"` einfügen:
    ```python
    "sharepoint_init_failed",
    ```

- [x] **Task 5 — `app/main.py`: Lifespan-PhotoStore-Init + `app.state`** (AC1)
  - [x] 5.1 Import ergänzen:
    ```python
    from app.services.photo_store import create_photo_store, LocalPhotoStore
    ```
  - [x] 5.2 Im Lifespan-Context-Manager (`@asynccontextmanager async def lifespan(app)`), nach dem Mirror-Scheduler-Init-Block:
    ```python
    # --- PhotoStore-Init (ID1) ---
    _photo_store = await create_photo_store(settings)
    if isinstance(_photo_store, LocalPhotoStore) and settings.photo_backend == "sharepoint":
        print("WARNING: SharePoint-Init fehlgeschlagen — LocalPhotoStore aktiv")
        _ls_db = SessionLocal()
        try:
            from app.services.audit import audit as _audit
            _audit(_ls_db, None, "sharepoint_init_failed",
                   details={"reason": "MSAL-Client-Credentials-Flow fehlgeschlagen"})
            _ls_db.commit()
        finally:
            _ls_db.close()
        app.state.photo_backend_warning = (
            "SharePoint-Init fehlgeschlagen — Fotos werden lokal gespeichert."
        )
    else:
        app.state.photo_backend_warning = None
    app.state.photo_store = _photo_store
    ```
  - [x] 5.3 `SessionLocal` ist bereits in `main.py` importiert (für Mirror-Scheduler-Jobs) — vor Edit prüfen, nicht doppelt importieren.
  - [x] 5.4 Kein Cleanup im Exit-Teil des Lifespans nötig (kein Connection-Pool, kein BackgroundTask).

- [x] **Task 6 — `app/services/steckbrief.py`: PHOTO_COMPONENT_REFS** (AC2, AC5)
  - [x] 6.1 Nach `ZUGANGSCODE_FIELD_KEYS` ergänzen:
    ```python
    # ---------------------------------------------------------------------------
    # Foto-Komponenten-Registry (Story 1.8)
    # ---------------------------------------------------------------------------
    PHOTO_COMPONENT_REFS: dict[str, str] = {
        "absperrpunkt_wasser":  "Absperrpunkt Wasser",
        "absperrpunkt_strom":   "Absperrpunkt Strom",
        "absperrpunkt_gas":     "Absperrpunkt Gas",
        "heizung_typenschild":  "Heizung / Typenschild",
    }
    ```
  - [x] 6.2 Router nutzt diese Konstante zur Validierung eingehender `component_ref`-Werte.
    Template nutzt sie für Labels + Iteration der Fotos-Sektion.

- [x] **Task 7 — `app/routers/objects.py`: Imports + `object_detail`-Erweiterung + 4 neue Endpoints** (AC2–AC6)
  - [x] 7.1 Imports ergänzen (am Modulanfang):
    ```python
    import hashlib
    import pathlib
    from collections import defaultdict

    from fastapi import (
        APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
        Request, UploadFile, status,
    )
    from fastapi.responses import FileResponse, HTMLResponse

    from app.models.object import SteckbriefPhoto
    from app.services.photo_store import (
        LARGE_UPLOAD_THRESHOLD, PhotoRef, PhotoValidationError, validate_photo,
    )
    from app.services.steckbrief import PHOTO_COMPONENT_REFS
    ```
    **Hinweis**: `audit` ist seit Story 1.7 bereits importiert. `Form`, `HTTPException`, `Request`, `HTMLResponse` ebenfalls — nur fehlende ergänzen, nicht doppelt importieren.
  - [x] 7.2 Im `object_detail`-Handler, nach dem `tech_zugangscodes`-Block:
    ```python
    # --- Fotos pro Komponente (Story 1.8) ---
    photos_raw = (
        db.execute(
            select(SteckbriefPhoto)
            .where(SteckbriefPhoto.object_id == detail.obj.id)
            .order_by(SteckbriefPhoto.captured_at.desc())
        )
        .scalars()
        .all()
    )
    photos_by_component: dict[str, list] = defaultdict(list)
    for _p in photos_raw:
        photos_by_component[_p.component_ref or "sonstige"].append(_p)
    ```
  - [x] 7.3 Template-Context des `object_detail`-Handlers ergänzen:
    ```python
    "photos_by_component": dict(photos_by_component),
    "photo_component_refs": PHOTO_COMPONENT_REFS,
    ```
  - [x] 7.4 **`POST /{object_id}/photos`** — Upload-Endpoint: Signatur + Preflight (Permission, Component-Check, Object-Lookup, Validierung) + Split in Sync/BG nach `len(content)`.
    ```python
    @router.post("/{object_id}/photos", response_class=HTMLResponse)
    async def photo_upload(
        object_id: uuid.UUID,
        request: Request,
        background_tasks: BackgroundTasks,
        component_ref: str = Form(...),
        file: UploadFile = File(...),
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        # Preflight (fuer beide Pfade identisch)
        if component_ref not in PHOTO_COMPONENT_REFS:
            raise HTTPException(400, f"Unbekannte Komponente: {component_ref!r}")
        accessible = accessible_object_ids(db, user)
        detail = get_object_detail(db, object_id, accessible_ids=accessible)
        if detail is None:
            raise HTTPException(404, "Objekt nicht gefunden")

        content = await file.read()
        try:
            validate_photo(content, file.content_type or "")
        except PhotoValidationError as exc:
            return templates.TemplateResponse(
                request, "_obj_photo_upload_result.html",
                {"obj": detail.obj, "component_ref": component_ref,
                 "error": str(exc), "user": user},
                status_code=400,
            )

        photo_store = request.app.state.photo_store
        short_code = detail.obj.short_code

        if len(content) >= LARGE_UPLOAD_THRESHOLD:
            return await _photo_upload_bg_path(
                db, request, background_tasks, detail, component_ref,
                file, content, photo_store, short_code, object_id, user,
            )
        return await _photo_upload_sync_path(
            db, request, detail, component_ref, file, content, photo_store,
            short_code, object_id, user,
        )
    ```
  - [x] 7.4a **Sync-Pfad (<3 MB)** — `_photo_upload_sync_path` Helper, inline in `objects.py`:
    ```python
    async def _photo_upload_sync_path(db, request, detail, component_ref, file,
                                      content, photo_store, short_code, object_id, user):
        ref = await photo_store.upload(
            object_short_code=short_code, category="technik",
            filename=file.filename or "foto.jpg", content=content,
            content_type=file.content_type or "image/jpeg",
        )
        photo = SteckbriefPhoto(
            object_id=object_id,
            backend=ref.backend,
            drive_item_id=ref.drive_item_id,
            local_path=ref.local_path,
            filename=ref.filename,
            component_ref=component_ref,
            uploaded_by_user_id=user.id,
        )
        db.add(photo)
        audit(db, user, "object_photo_uploaded",
              entity_type="object", entity_id=object_id,
              details={"component_ref": component_ref, "filename": ref.filename,
                       "backend": ref.backend},
              request=request)
        db.commit()
        db.refresh(photo)
        return templates.TemplateResponse(
            request, "_obj_photo_card.html",
            {"photo": photo, "obj": detail.obj, "user": user},
        )
    ```
  - [x] 7.4b **BG-Pfad (>= 3 MB)** — `_photo_upload_bg_path` Helper: legt sofort eine `status=uploading`-Row an, triggert `_run_photo_upload_bg`, rendert `_obj_photo_pending.html`.
    ```python
    async def _photo_upload_bg_path(db, request, background_tasks, detail, component_ref,
                                    file, content, photo_store, short_code, object_id, user):
        photo = SteckbriefPhoto(
            object_id=object_id,
            backend=photo_store.backend_name,
            filename=file.filename or "foto.jpg",
            component_ref=component_ref,
            uploaded_by_user_id=user.id,
            photo_metadata={"status": "uploading"},
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        background_tasks.add_task(
            _run_photo_upload_bg,
            photo_id=photo.id,
            content=content,
            content_type=file.content_type or "image/jpeg",
            filename=file.filename or "foto.jpg",
            short_code=short_code,
            category="technik",
            photo_store=photo_store,
            user_id=user.id,
            object_id=object_id,
        )
        return templates.TemplateResponse(
            request, "_obj_photo_pending.html",
            {"photo": photo, "obj": detail.obj, "user": user},
        )
    ```
  - [x] 7.5 **`_run_photo_upload_bg` BackgroundTask-Funktion** (synchron, NICHT `async def`):
    ```python
    def _run_photo_upload_bg(
        *, photo_id: uuid.UUID, content: bytes, content_type: str,
        filename: str, short_code: str, category: str, photo_store,
        user_id: uuid.UUID, object_id: uuid.UUID,
    ) -> None:
        import asyncio
        from app.db import SessionLocal as _SL
        from app.models import AuditLog
        db = _SL()
        try:
            ref = asyncio.run(photo_store.upload(
                object_short_code=short_code, category=category,
                filename=filename, content=content, content_type=content_type,
            ))
            photo = db.get(SteckbriefPhoto, photo_id)
            if photo is not None:
                photo.backend = ref.backend
                photo.drive_item_id = ref.drive_item_id
                photo.local_path = ref.local_path
                photo.filename = ref.filename
                photo.photo_metadata = {"status": "done"}
                db.add(AuditLog(
                    action="object_photo_uploaded",
                    user_id=user_id,
                    entity_type="object",
                    entity_id=object_id,
                    details_json={"component_ref": photo.component_ref,
                                  "filename": ref.filename, "backend": ref.backend},
                ))
                db.commit()
        except Exception as exc:
            print(f"_run_photo_upload_bg: Upload fehlgeschlagen: {exc}")
            _db2 = _SL()
            try:
                p = _db2.get(SteckbriefPhoto, photo_id)
                if p:
                    p.photo_metadata = {"status": "error"}
                    _db2.commit()
            finally:
                _db2.close()
        finally:
            db.close()
    ```
    **Wichtig**: `asyncio.run()` ist nur im sync-BackgroundTask erlaubt (Plattform-Regel). `AuditLog` direkt via `db.add(AuditLog(...))` statt `audit()`-Helper — kein `Request` im BackgroundTask verfügbar (Muster aus `mietverwaltung_write.py`).
  - [x] 7.6 **`GET /{object_id}/photos/{photo_id}/status`** — Polling-Endpoint:
    ```python
    @router.get("/{object_id}/photos/{photo_id}/status", response_class=HTMLResponse)
    async def photo_status(
        object_id: uuid.UUID, photo_id: uuid.UUID, request: Request,
        user: User = Depends(require_permission("objects:view")),
        db: Session = Depends(get_db),
    ):
        photo = db.get(SteckbriefPhoto, photo_id)
        if photo is None or photo.object_id != object_id:
            raise HTTPException(404)
        status = (photo.photo_metadata or {}).get("status", "done")
        if status == "uploading":
            return templates.TemplateResponse(
                request, "_obj_photo_pending.html",
                {"photo": photo, "obj": None, "user": user},
            )
        return templates.TemplateResponse(
            request, "_obj_photo_card.html",
            {"photo": photo, "obj": None, "user": user},
        )
    ```
  - [x] 7.7 **`DELETE /{object_id}/photos/{photo_id}`**:
    ```python
    @router.delete("/{object_id}/photos/{photo_id}", response_class=HTMLResponse)
    async def photo_delete(
        object_id: uuid.UUID, photo_id: uuid.UUID, request: Request,
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        photo = db.get(SteckbriefPhoto, photo_id)
        if photo is None or photo.object_id != object_id:
            raise HTTPException(404)
        photo_store = request.app.state.photo_store
        ref = PhotoRef(
            backend=photo.backend, drive_item_id=photo.drive_item_id,
            local_path=photo.local_path, filename=photo.filename or "",
        )
        try:
            await photo_store.delete(ref)
        except Exception as exc:
            print(f"photo_delete: store.delete fehlgeschlagen (nicht blockierend): {exc}")
        audit(db, user, "object_photo_deleted",
              entity_type="object", entity_id=object_id,
              details={"component_ref": photo.component_ref, "filename": photo.filename},
              request=request)
        db.delete(photo)
        db.commit()
        return HTMLResponse("")
    ```
    `HTMLResponse("")` bei HTMX `hx-swap="outerHTML"` entfernt das Ziel-Element.
  - [x] 7.8 **`GET /{object_id}/photos/{photo_id}/file`** — lokale Fotos ausliefern:
    ```python
    @router.get("/{object_id}/photos/{photo_id}/file")
    async def photo_file_serve(
        object_id: uuid.UUID, photo_id: uuid.UUID,
        user: User = Depends(require_permission("objects:view")),
        db: Session = Depends(get_db),
    ):
        """Liefert lokal gespeicherte Foto-Dateien (backend='local') aus."""
        photo = db.get(SteckbriefPhoto, photo_id)
        if photo is None or photo.object_id != object_id:
            raise HTTPException(404)
        if photo.backend != "local" or not photo.local_path:
            raise HTTPException(404)
        safe = pathlib.Path(photo.local_path).resolve()
        root = pathlib.Path("uploads").resolve()
        if not str(safe).startswith(str(root)):
            raise HTTPException(403, "Pfad außerhalb des Upload-Verzeichnisses")
        if not safe.exists():
            raise HTTPException(404)
        return FileResponse(safe)
    ```
    Path-Traversal-Schutz: `local_path` kommt aus DB (nicht direkt vom User), aber `.resolve()` + Prefix-Check ist trotzdem Pflicht als Defense-in-Depth.

- [x] **Task 8 — Templates** (AC2–AC5)
  - [x] 8.1 `app/templates/_obj_technik.html` — Fotos-Sub-Block nach dem Zugangscodes-Block ergänzen:
    ```jinja
    <div class="mt-6 pt-6 border-t border-slate-100">
      <h3 class="text-sm font-semibold text-slate-800 mb-4">Fotos</h3>
      {% for component_ref, label in photo_component_refs.items() %}
        <div class="mb-5">
          <div class="text-xs uppercase tracking-wider text-slate-500 mb-2">{{ label }}</div>
          <div class="flex flex-wrap gap-3 items-start">
            {% for photo in photos_by_component.get(component_ref, []) %}
              {% include "_obj_photo_card.html" %}
            {% endfor %}
            {% if has_permission(user, "objects:edit") %}
              {% include "_obj_photo_upload_form.html" %}
            {% endif %}
          </div>
        </div>
      {% endfor %}
    </div>
    ```
    `{% include %}` erbt den aktuellen Jinja2-Scope — `component_ref`, `label`, `obj`, `user` sind im Sub-Template automatisch verfügbar (kein `with context` nötig).
  - [x] 8.2 Neue Datei `app/templates/_obj_photo_card.html` — rendert AUSSCHLIESSLICH Done-Zustand (Upload fertig oder Fehler). Uploading-Zustand lebt vollstaendig in `_obj_photo_pending.html` (Task 8.4); der Polling-Endpoint (Task 7.6) entscheidet welches Template greift. Damit ist jede Template-Datei nur fuer einen Zustand zustaendig.
    ```jinja
    {# Einzelnes Foto-Card (Done-State). Erwartet: photo (SteckbriefPhoto), obj (Object oder None), user.
       Wird vom Polling-Endpoint (Task 7.6) gerendert, wenn status != "uploading". #}
    {% set _status = (photo.photo_metadata or {}).get("status", "done") %}
    {% set _obj_id = obj.id if obj else photo.object_id %}
    <div id="photo-{{ photo.id }}"
         class="relative group w-24 h-24 rounded border border-slate-200 overflow-hidden bg-slate-50 flex items-center justify-center text-xs">
      {% if _status == "error" %}
        <div class="text-rose-500 text-center px-1">Fehler beim<br>Upload</div>
      {% else %}
        {% if photo.backend == "local" and photo.local_path %}
          <img src="/objects/{{ _obj_id }}/photos/{{ photo.id }}/file"
               alt="{{ photo.filename }}"
               class="w-full h-full object-cover">
        {% else %}
          <div class="text-slate-400 text-center px-1">{{ photo.filename }}</div>
        {% endif %}
        {% if has_permission(user, "objects:edit") %}
          <button type="button"
                  hx-delete="/objects/{{ _obj_id }}/photos/{{ photo.id }}"
                  hx-target="#photo-{{ photo.id }}"
                  hx-swap="outerHTML"
                  hx-confirm="Foto löschen?"
                  class="absolute top-1 right-1 hidden group-hover:flex items-center justify-center w-5 h-5 rounded-full bg-rose-600 text-white leading-none">
            &times;
          </button>
        {% endif %}
      {% endif %}
    </div>
    ```
  - [x] 8.3 Neue Datei `app/templates/_obj_photo_upload_form.html`:
    ```jinja
    {# Upload-Formular für eine Foto-Komponente. Erwartet: component_ref, obj, user.
       hx-encoding="multipart/form-data" MUSS gesetzt sein (HTMX-Pflicht für File-Uploads). #}
    <div>
      <form hx-post="/objects/{{ obj.id }}/photos"
            hx-encoding="multipart/form-data"
            hx-target="#photo-upload-result-{{ component_ref }}"
            hx-swap="innerHTML">
        <input type="hidden" name="component_ref" value="{{ component_ref }}">
        <label class="cursor-pointer w-24 h-24 rounded border-2 border-dashed
                       border-slate-300 hover:border-sky-400 flex flex-col items-center
                       justify-center text-slate-400 hover:text-sky-500 transition">
          <svg class="w-6 h-6 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M12 4v16m8-8H4"/>
          </svg>
          <span class="text-xs">Foto</span>
          <input type="file" accept="image/jpeg,image/png" name="file" class="hidden"
                 onchange="this.closest('form').requestSubmit()">
        </label>
      </form>
      <div id="photo-upload-result-{{ component_ref }}"></div>
    </div>
    ```
    `onchange="this.closest('form').requestSubmit()"` löst HTMX-Submit aus sobald eine Datei gewählt wird — kein separater Submit-Button nötig.
  - [x] 8.4 Neue Datei `app/templates/_obj_photo_pending.html`:
    ```jinja
    {# "Upload läuft..." Card mit HTMX-Polling. Erwartet: photo (SteckbriefPhoto).
       Polling-Endpoint liefert dieses oder _obj_photo_card.html zurück je nach Status. #}
    <div id="photo-{{ photo.id }}"
         hx-get="/objects/{{ photo.object_id }}/photos/{{ photo.id }}/status"
         hx-trigger="every 3s"
         hx-swap="outerHTML"
         class="w-24 h-24 rounded border border-slate-200 bg-slate-50
                flex items-center justify-center text-xs text-slate-400 text-center px-1">
      Upload<br>läuft...
    </div>
    ```
  - [x] 8.5 Neue Datei `app/templates/_obj_photo_upload_result.html` (Validierungsfehler):
    ```jinja
    {# Fehlermeldung bei Upload-Validierungsfehler.
       Wird in hx-target="#photo-upload-result-{component_ref}" eingesetzt. #}
    <p class="text-xs text-rose-600 mt-1">{{ error }}</p>
    ```
  - [x] 8.6 `app/templates/admin/home.html` — WARN-Banner vor dem ersten `<div class="mb-6">`:
    ```jinja
    {% if photo_backend_warning %}
    <div class="mb-4 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
      <strong>Foto-Backend:</strong> {{ photo_backend_warning }}
    </div>
    {% endif %}
    ```
    Im Admin-Home-Handler (`app/routers/admin.py` oder äquivalent) `photo_backend_warning` aus `request.app.state.photo_backend_warning` in den Template-Context übergeben.

- [x] **Task 9 — Tests `tests/test_photo_store_unit.py` (NEU)** (AC1–AC4, AC7)
  - [x] 9.1 Neue Datei. Reine Unit-Tests ohne TestClient. Imports analog zu `test_field_encryption_unit.py`:
    ```python
    import os
    os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use")
    os.environ.setdefault("POSTGRES_PASSWORD", "")
    os.environ.setdefault("ANTHROPIC_API_KEY", "")
    os.environ.setdefault("IMPOWER_BEARER_TOKEN", "")

    from app.services.photo_store import (
        validate_photo, PhotoValidationError, LocalPhotoStore,
        LARGE_UPLOAD_THRESHOLD, MAX_SIZE_BYTES, MAGIC_BYTES,
        create_photo_store,
    )
    ```
  - [x] 9.2 Tests:
    - `test_validate_photo_accepts_jpeg` — JPEG-Magic + `image/jpeg` + 100 Bytes → kein Fehler
    - `test_validate_photo_accepts_png` — PNG-Magic + `image/png` + 100 Bytes → kein Fehler
    - `test_validate_photo_rejects_pdf_content_type` — `content_type="application/pdf"` → `PhotoValidationError`
    - `test_validate_photo_rejects_mismatched_magic_bytes` — JPEG-Content-Type aber PNG-Magic → `PhotoValidationError`
    - `test_validate_photo_rejects_oversized` — JPEG-Magic + `image/jpeg` + `MAX_SIZE_BYTES + 1` Bytes → `PhotoValidationError`
    - `test_large_upload_threshold_value` — `LARGE_UPLOAD_THRESHOLD == 3 * 1024 * 1024`
    - `test_local_store_upload_creates_file(tmp_path)` — Instanz mit `tmp_path` als Upload-Root (patchen oder direkt instanziieren mit Pfad-Parameter), `await store.upload(...)` → Datei existiert, `ref.backend == "local"`, `ref.local_path` nicht None
    - `test_local_store_sha256_deduplication(tmp_path)` — gleicher Content zweimal → gleicher `local_path`
    - `test_local_store_delete_removes_file(tmp_path)` — Upload + Delete → Datei weg
    - `test_local_store_delete_missing_file_no_error(tmp_path)` — `delete(ref)` mit nicht-existierendem Pfad → kein Fehler
    - `test_create_photo_store_returns_local_for_local_backend` — Settings-Mock mit `photo_backend="local"` → `isinstance(store, LocalPhotoStore)`
    - `test_create_photo_store_returns_local_when_sharepoint_credentials_missing` — Settings-Mock mit `photo_backend="sharepoint"` aber leeren Credentials → `isinstance(store, LocalPhotoStore)`
    **Hinweis**: `LocalPhotoStore` muss den Upload-Root als Parameter nehmen ODER im Test via `monkeypatch` angepasst werden, damit Tests in `tmp_path` schreiben statt in echtes `uploads/`.

- [x] **Task 10 — Admin-Router: `photo_backend_warning` in Template-Context** (AC1)
  - [x] 10.1 Prüfe `app/routers/admin.py` (oder wie der Admin-Home-Handler heißt): den Handler für `GET /admin` oder `/admin/home` finden und `photo_backend_warning=request.app.state.photo_backend_warning` in den Template-Context einfügen. Attribut kann `None` sein (kein SharePoint-Fehler) — Template prüft auf Truthiness.

- [x] **Task 11 — Regression + Deferred-Work** (AC7)
  - [x] 11.1 `pytest -x` vollständig ausführen. Erwartung: >= 463 bestehende Tests + neue Tests aus `test_photo_store_unit.py` — alle grün.
  - [x] 11.2 `tests/test_write_gate_coverage.py` — **kein Eingriff noetig.** Verifiziert: `_CD1_CLASSES` (Zeile 27-44) enthaelt `SteckbriefPhoto` NICHT (nur `Object, Unit, InsurancePolicy, Wartungspflicht, Schadensfall, Versicherer, Dienstleister, Bank, Ablesefirma, Eigentuemer, Mieter, Mietvertrag, Zaehler, FaciliooTicket`). Der Scanner wird weder `db.add(SteckbriefPhoto(...))` noch `photo.backend = ref.backend` flaggen. AC8 dagegen fuegt `db.add(Object(...))` im Mirror ein — das ist Row-Creation, die der Scanner ebenfalls nicht flaggt (nur `<var>.<field> = value`). Falls `_reconcile_object` anschliessend `new_obj.full_address = ...` als Direktzuweisung setzt, waere das ein Hit; der Discover-Pfad in Task 12.4 setzt Felder aber ausschliesslich im `Object(...)`-Konstruktor, nicht per nachtraeglichem Assign. Also: keine Allowlist-Aenderung noetig.
  - [x] 11.3 `output/implementation-artifacts/deferred-work.md` ergänzen:
    - **SharePoint-Foto-Anzeige via temporärer Download-Link** — v1 zeigt für `backend="sharepoint"` nur Dateinamen (kein `<img>`); temporäre Graph-API-URLs (Ablauf: 1h) als Defer auf v1.1. Fix: `url()`-Methode im Router aufrufen + URL cachen.
    - **Concurrent Page-Loads erzeugen doppelte `SteckbriefPhoto`-Rows** — kein UNIQUE-Constraint auf `(object_id, component_ref, filename, captured_at)`. Kein praktisches Problem bei manuellem Upload, aber Notiz für zukünftige Bulk-Uploads.

- [x] **Task 12 — Impower-Object-Discover im Nightly-Mirror** (AC8 — Scope-Erweiterung gegenueber Epic 1.8)
  
  **Kontext:** `app/services/steckbrief_impower_mirror.py:643-645` filtert `Object.impower_property_id.is_not(None)` — der Mirror reconcilet nur bestehende Object-Rows. Bei leerer `objects`-Tabelle ist der Sync ein No-Op (Counter `objects_ok = 0`), und es gibt keinen Anlege-Pfad fuer Objekte — weder UI noch Seed noch Bootstrap (verifiziert: `db.add(Object(` findet kein Ergebnis im Repo). Discover-Phase fuellt diese Luecke.
  
  **Rationale fuer Bundle mit 1.8:** Gleiche Touch-Datei `steckbrief_impower_mirror.py` (fetch_items-Erweiterung). Alternative: eigenes Ticket `1.4.1 Discover-Pass` — Entscheidung liegt beim User. Wenn Zeit knapp ist, ist Herauslösen sauberer.
  
  **Governance-Hinweis:** Der Discover-Pfad fuehrt `db.add(Object(...))` direkt aus. architecture.md §CD2 listet `Object`-Row-Creation NICHT explizit als Write-Gate-Ausnahme (nur `FieldProvenance`, `ReviewQueueEntry`, `AuditLog`, `SteckbriefPhoto`-Row-Creation). Row-Creation ist dem Geist nach aber keine Feld-Mutation → passt zur Gate-Logik. Scanner flaggt es nicht (siehe Task 11.2). Trotzdem: Architektur-Ausnahme fuer `Object`-Row-Creation durch Mirror nachtraeglich in `architecture.md §CD2` + §Daten- und Write-Patterns dokumentieren.

  - [x] 12.1 `app/services/_sync_common.py`: in `@dataclass class SyncRunResult` (Zeile 90-110, verifiziert) neues Feld `items_discovered: int = 0` nach `items_skipped_no_external_data` ergänzen.
  - [x] 12.2 `app/services/_sync_common.py`: in der Counter-Mapping-Sektion von `run_sync_job` (Zeile 420-435, verifiziert — `"objects_ok": result.items_ok` steht auf Zeile 427) neuen Eintrag `"objects_discovered": result.items_discovered,` ergänzen.
  - [x] 12.3 `app/services/_sync_common.run_sync_job`: Signatur von `fetch_items` erweitern auf `Callable[[], Awaitable[list[T] | tuple[list[T], int]]]`. `run_sync_job` prüft `isinstance(result, tuple)` und setzt `result.items_discovered` entsprechend, sonst default 0. Abwärtskompatibel — die anderen Mirror-Jobs liefern weiterhin nur die Liste.
  - [x] 12.4 `app/services/steckbrief_impower_mirror.py`: in `fetch_items()` (aktuell Zeile ~636) vor dem `select(Object.id).where(Object.impower_property_id.is_not(None))`-Query eine Discover-Phase einziehen:
    ```python
    # Discover: neue Impower-Properties als Object anlegen (AC8)
    existing_pids: set[str] = set(
        str(p) for p in db.execute(
            select(Object.impower_property_id).where(
                Object.impower_property_id.is_not(None)
            )
        ).scalars().all()
    )
    discovered = 0
    for pid_str, data in snapshot.items():
        if pid_str in existing_pids:
            continue
        prop = data.get("property") or {}
        new_obj = Object(
            impower_property_id=pid_str,
            full_address=_build_full_address(prop),
            # short_code + name: nur befüllen, wenn konsistent mit dem
            # Mapping in _reconcile_object; sonst NULL lassen und den
            # Reconcile-Pfad in derselben Lauf-Iteration gewinnen lassen.
        )
        db.add(new_obj)
        discovered += 1
    if discovered > 0:
        db.commit()
    stmt = select(Object.id).where(
        Object.impower_property_id.is_not(None)
    )
    return (list(db.execute(stmt).scalars().all()), discovered)
    ```
    Die `return (list, discovered)`-Variante setzt die in Task 12.3 festgelegte Signatur-Erweiterung voraus (Union-Rueckgabetyp). Keine Alternative implementieren — Ein-Weg-Entscheidung.
  - [x] 12.5 **Mapping-Konsistenz prüfen**: bevor 12.4 committed wird, in `_reconcile_object` (`app/services/steckbrief_impower_mirror.py:362+`) nachschauen, welche Impower-Property-Keys für `short_code` + `name` gelesen werden. Discover darf **nur** Felder schreiben, die der Reconcile-Pfad später identisch wieder schreibt — sonst: (a) Doppel-Writes mit unterschiedlichen Werten → doppelte `FieldProvenance`-Rows, (b) Mirror-Guard überspringt zweiten Write, falls Discover bereits einen User-Edit-fremden Stand gesetzt hat und der Reconcile-Wert formal abweicht. Wenn `_reconcile_object` aktuell `short_code`/`name` nicht spiegelt → im Discover ebenfalls weglassen, nur `impower_property_id` + `full_address` setzen.
  - [x] 12.6 `app/templates/admin/sync_status.html`: in der „Letzter Lauf"-Metriken-Tabelle (aktuell Zeile ~44-69) nach dem `objects_skipped_no_impower_data`-Block ergänzen:
    ```jinja
    <dt class="text-slate-500">Neu entdeckt</dt>
    <dd class="font-mono">{{ last_run.counters.get("objects_discovered", 0) }}</dd>
    ```
    In der Historien-Tabelle (aktuell Zeile ~127-168) einen neuen `<th>Neu</th>`-Header + passenden `<td>`-Block mit `{{ run.counters.get("objects_discovered", 0) }}` ergänzen.
  - [x] 12.7 Test in `tests/test_steckbrief_impower_mirror_unit.py` ergänzen: gemockter Snapshot mit 3 PIDs + leere `objects`-Tabelle → nach einem Lauf existieren 3 Objects mit gesetzter `impower_property_id`; `SyncRunResult.items_discovered == 3`; zweiter Lauf mit gleichem Snapshot legt keine neuen Objects an und hat `items_discovered == 0` (Idempotenz).
  - [x] 12.8 Project Structure Notes (weiter unten in diesem File) ergänzen: `app/services/steckbrief_impower_mirror.py`, `app/services/_sync_common.py`, `app/templates/admin/sync_status.html` im „Modifizieren"-Block anhängen.

## Dev Notes

### Was bereits existiert — NICHT neu bauen

- **`SteckbriefPhoto`-ORM-Modell** in `app/models/object.py:154` — existiert mit Spalten `id`, `object_id`, `unit_id`, `drive_item_id`, `local_path`, `label`, `photo_metadata`, `created_at`, `updated_at`. Migration 0014 fügt fehlende Spalten hinzu, ORM-Modell wird entsprechend erweitert.
- **`steckbrief_photos`-Tabelle** in Migration 0010 angelegt (FK→objects + FK→units, Index auf object_id/unit_id).
- **`object_photo_uploaded` + `object_photo_deleted`** in `KNOWN_AUDIT_ACTIONS` (`app/services/audit.py:75-76`).
- **`UploadFile`, `File`, `BackgroundTasks`** in `app/routers/cases.py:16-22` — Muster-Datei für Imports.
- **BackgroundTask-Muster** aus `app/routers/cases.py` (`_run_case_extraction`): sync Funktion, eigene `SessionLocal()`, `try/finally`, `asyncio.run()` am Einstieg — exakt dieses Muster wiederverwenden.
- **Upload-Validierungsmuster** aus `app/routers/documents.py` oder `test_upload.py` — Magic-Bytes + Content-Type-Check, analog anwenden.
- **`get_object_detail` + `accessible_object_ids`** bereits in `app/routers/objects.py` — nutzen, nicht neu schreiben.
- **`audit()`-Import** in `objects.py` seit Story 1.7 — prüfen ob schon da.
- **`has_permission`** als Jinja2-Global in `app/templating.py` — kein neuer Import im Template.

### Kritische Implementation-Details

**1. `SteckbriefPhoto`-Row-Creation ist Ausnahme vom Write-Gate**

`architecture.md §Daten- und Write-Patterns` (Zeile 492) sagt woertlich: _"Direkte `entity.field = value` gefolgt von `db.commit()` ist fuer die CD1-Entitaeten konventionell verboten, **ausgenommen** die Tabellen `FieldProvenance`, `ReviewQueueEntry`, `AuditLog` und `SteckbriefPhoto`-Row-Creation (Photo-Referenz ist ein Struktur-Write, kein Cluster-Feld-Write)."_ Direktes `db.add(SteckbriefPhoto(...))` + `db.commit()` ist **korrekt** — kein `write_field_human`-Aufruf.

In der `_run_photo_upload_bg`-BackgroundTask macht der Update-Pfad `photo.backend = ref.backend` etc. strenggenommen Feld-Writes, aber auf `SteckbriefPhoto` — und `SteckbriefPhoto` ist nicht in `_CD1_CLASSES` (Task 11.2 bestaetigt). Der Scanner flaggt nicht; Governance-konform, da die Felder strukturelle Foto-Metadaten sind, keine Cluster-Felder.

**2. BackgroundTask: `asyncio.run()` nur am Task-Einstieg**

`_run_photo_upload_bg` ist `def` (nicht `async def`) — läuft im FastAPI-Thread-Pool. `asyncio.run(photo_store.upload(...))` ist der einzige Einstieg in async Code. Plattform-Regel: `asyncio.run()` nur am Einstieg eines sync BackgroundTask, nie aus einem async Handler.

**3. AuditLog im BackgroundTask ohne `audit()`-Helper**

`audit()` braucht `Request` (fuer IP-Extraktion). Kein Request im BackgroundTask → direktes `db.add(AuditLog(action=..., user_id=..., entity_type=..., entity_id=..., details_json=...))`. **Wichtig**: Der `audit()`-Helper nimmt `details=` als Parameter (wird intern auf `details_json` gemappt), aber der direkte `AuditLog(...)`-Konstruktor nimmt das Spaltenname-Feld `details_json=` — nicht verwechseln, sonst TypeError. `AuditLog`-Import: `from app.models import AuditLog`.

**4. HTMX `hx-encoding="multipart/form-data"` ist Pflicht**

Standard HTMX-Form sendet `application/x-www-form-urlencoded`. Für `UploadFile` in FastAPI MUSS `hx-encoding="multipart/form-data"` auf dem `<form>`-Tag gesetzt sein. Fehlt das → FastAPI erhält keinen Datei-Content, `file.read()` gibt `b""`.

**5. HTMX DELETE-Methode**

HTMX unterstützt `hx-delete` nativ. FastAPI: `@router.delete(...)`. Response `HTMLResponse("")` + `hx-swap="outerHTML"` entfernt das Ziel-Element ohne Page-Reload.

**6. `photo_store.backend_name`-Attribut**

Beide Store-Implementierungen MÜSSEN `backend_name: str = "local"` bzw. `backend_name: str = "sharepoint"` als Klassen-Attribut haben. Der Upload-Handler und der BackgroundTask nutzen das, um `SteckbriefPhoto.backend` zu setzen — kein `isinstance()`-Check in Router-Code.

**7. SharePoint-Foto-Anzeige: v1 zeigt NUR Dateinamen, keine Thumbnails — sichtbare User-Limitation**

`SharePointPhotoStore.url()` braucht einen asynchronen Graph-API-Call (temporaere Download-URLs laufen nach 1h ab). Fuer v1 ausgelassen — im Template zeigt `photo.backend == "sharepoint"` nur `photo.filename` als Text-Kachel, kein `<img>`-Tag. **User sieht Bild nicht, solange SharePoint aktiv ist.** Daher laeuft Dev-Setup mit `photo_backend="local"` (Task 2.2) und Prod faehrt mit `"sharepoint"`; Thumbnail-Anzeige via Graph-API-URL ist Defer v1.1 (siehe Task 11.3 + `deferred-work.md`). Stakeholder im UAT darauf vorbereiten.

**8. Path-Traversal-Schutz im `photo_file_serve`-Endpoint**

`photo.local_path` kommt aus DB (nicht direkt vom User-Input), aber `pathlib.Path(photo.local_path).resolve()` + Prefix-Check gegen `Path("uploads").resolve()` ist trotzdem Pflicht (Defense-in-Depth, falls ein kompromittierter DB-Wert oder fehlerhafte Datenbankbeschreibung entsteht).

**Edge-Case**: `LocalPhotoStore.upload()` schreibt Pfade immer **relativ** zum CWD (`uploads/objects/...`). Der `str(path)`-Roundtrip in `PhotoRef.local_path` gibt den relativen Pfad in die DB. `Path(...).resolve()` macht beim Serve-Request daraus einen absoluten Pfad relativ zum **aktuellen** CWD — wenn der FastAPI-Prozess mit unveraendertem CWD laeuft, passt der Prefix-Check. Wenn zukuenftig ein Sync-Job aus anderem CWD startet und absolute Pfade schreibt, dann Prefix-Check ueberdenken (oder `LocalPhotoStore` konfigurierbare Absolute-Root erzwingen).

**9. Admin-Home-Handler: `photo_backend_warning` einfügen**

`request.app.state` ist in FastAPI-Handlern via `request.app.state.attr` zugänglich. Den Wert als `photo_backend_warning=request.app.state.photo_backend_warning` in den Template-Context des Admin-Home-Handlers einfügen (Template prüft auf Truthiness — `None` → kein Banner).

**10. Template-Response-Signatur**

`templates.TemplateResponse(request, "name.html", {...})` — Request MUSS erstes Argument sein. Memory: `feedback_starlette_templateresponse`.

**11. `LocalPhotoStore` im Test: Upload-Root-Pfad**

`LocalPhotoStore.upload()` schreibt nach `uploads/objects/{short_code}/...` — relativer Pfad, also relativ zum CWD. In Tests mit `tmp_path`-Fixture: entweder `monkeypatch.chdir(tmp_path)` (dann landen Uploads unter `tmp_path/uploads/...`) oder `LocalPhotoStore` bekommt einen konfigurierbaren Root-Pfad als `__init__`-Parameter. Letzteres ist sauberer (kein CWD-Seiteneffekt in parallelen Tests).

**12. Scope-Erweiterung gegenueber Epic 1.8 transparent machen**

Epic 1.8 hat 4 ACs (Init-Fallback, Validated-Upload, Large-Upload-BG, 400-Reject-Invalid). Diese Story ergaenzt bewusst:

- **AC5 Foto-Anzeige + Loeschen** — logische Gegenrichtung zum Upload; ohne Delete bleibt jeder Fehl-Upload permanent sichtbar. Standard-Erwartung.
- **AC6 Permission-Gate serverseitig** — Security-Hygiene; UI-Only-Check ist Pentest-Finding wartend-zu-passieren.
- **AC7 Test-Requirement** — Plattform-Standard fuer alle Stories.
- **AC8 Impower-Object-Discover** — unabhaengige Scope-Entscheidung (siehe Task 12 Kontext + Rationale). User-Entscheidung, ob gebundelt oder als eigenes Ticket.

### Bekannte Grenzfälle

- **Validierung vor BackgroundTask**: `validate_photo()` läuft synchron BEVOR die Größe geprüft wird, ob BackgroundTask nötig ist. Jede Datei — auch große — wird zuerst vollständig validiert.
- **Gleichzeitige Uploads**: SHA256-basierter Dateiname macht lokale Uploads idempotent (gleicher Content → gleicher Dateiname, kein Überschreiben nötig).
- **SharePoint nicht erreichbar nach Init**: Upload-Fehler im BackgroundTask → `photo_metadata = {"status": "error"}`. UI zeigt "Fehler beim Upload"-Platzhalter. Kein automatischer Retry in v1.
- **`component_ref = None` für ältere Rows**: `photos_by_component.get(None, [])` → nicht in `photo_component_refs.items()` — diese Fotos tauchen nicht in der Technik-Sektion auf (akzeptabel, da alte Rows `label` haben; v1.1 Migration nötig falls gewünscht).
- **Sehr kleiner Content bei Magic-Bytes-Check**: Content kürzer als 8 Bytes → JPEG-Check mit 3 Bytes (`content[:3]`) und PNG-Check mit 8 Bytes (`content[:8]`) → kurzer Content hat keine PNG-Magic-Bytes → `PhotoValidationError`. Edge-Case, kein reales Problem.

### Project Structure Notes

**Neu anlegen:**
- `migrations/versions/0014_steckbrief_photos_fields.py`
- `app/services/photo_store.py`
- `app/templates/_obj_photo_card.html`
- `app/templates/_obj_photo_upload_form.html`
- `app/templates/_obj_photo_pending.html`
- `app/templates/_obj_photo_upload_result.html`
- `tests/test_photo_store_unit.py`

**Modifizieren:**
- `pyproject.toml` (`msal>=1.28`)
- `app/config.py` (`photo_backend` + `sharepoint_*`)
- `.env.op` (PHOTO_BACKEND + SHAREPOINT_* Refs)
- `app/services/audit.py` (`sharepoint_init_failed`)
- `app/services/steckbrief.py` (`PHOTO_COMPONENT_REFS`)
- `app/models/object.py` (`SteckbriefPhoto` neue Felder)
- `app/main.py` (Lifespan PhotoStore-Init + `app.state`)
- `app/routers/objects.py` (Imports + `object_detail` + 4 neue Endpoints + BackgroundTask-Funktion)
- `app/templates/_obj_technik.html` (Fotos-Sub-Block)
- `app/templates/admin/home.html` (WARN-Banner)
- `app/routers/admin.py` (oder äquivalent: `photo_backend_warning` in Admin-Home-Context)
- `app/services/_sync_common.py` (SyncRunResult.items_discovered + Counter-Mapping + fetch_items-Signatur)
- `app/services/steckbrief_impower_mirror.py` (Discover-Phase in fetch_items)
- `app/templates/admin/sync_status.html` (Counter "Neu entdeckt" + Historien-Spalte)
- `output/implementation-artifacts/deferred-work.md`

**Nicht berühren:**
- `app/models/__init__.py` — `SteckbriefPhoto` bereits re-exportiert
- `migrations/versions/0010_steckbrief_core.py` — nicht modifizieren; Änderungen ausschließlich via 0014
- `app/services/field_encryption.py` — kein Bezug zu Fotos

### References

- [Epic 1 Story 1.8](output/planning-artifacts/epics.md#story-18-foto-upload-mit-sharepoint--local-fallback)
- [Architecture ID1 Foto-Pipeline](output/planning-artifacts/architecture.md#id1--foto-pipeline) — PhotoStore-Protocol, PhotoRef, Backend-Auswahl, BackgroundTask-Threshold
- [Architecture CD2 Write-Gate Ausnahmen](output/planning-artifacts/architecture.md#cd2--ki-governance-gate) — SteckbriefPhoto-Row-Creation explizit erlaubt
- [Architecture CD4 Neue Permissions + Audit-Actions](output/planning-artifacts/architecture.md#cd4--authentication-authorization-audit) — `object_photo_uploaded`, `object_photo_deleted`, `sharepoint_init_failed`
- [Story 1.7 Dev Notes §BackgroundTask](output/implementation-artifacts/1-7-zugangscodes-mit-field-level-encryption.md#kritische-implementation-details) — asyncio.run() Regel, Audit ohne Request
- [Story 1.6 _obj_technik.html](app/templates/_obj_technik.html) — bestehende Technik-Sektions-Struktur
- [SteckbriefPhoto-Modell](app/models/object.py:154) — bestehende Spalten
- [Migration 0010](migrations/versions/0010_steckbrief_core.py:435) — steckbrief_photos bestehende Tabellenstruktur
- [audit.py KNOWN_AUDIT_ACTIONS](app/services/audit.py:30) — Registrierungsliste
- [cases.py BackgroundTask-Muster](app/routers/cases.py:180) — `_run_case_extraction` + `SessionLocal()`
- [project-context.md](docs/project-context.md) — asyncio.run(), BackgroundTask-Session, Template-Response-Signatur, TemplateResponse(request, ...)

### Latest Technical Information

- **`msal>=1.28`** (Microsoft Authentication Library): `msal.ConfidentialClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant_id}", client_credential=client_secret)` + `.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])` → `result["access_token"]`. MSAL cached Tokens intern (TTL ~1h), kein manuelles Refresh nötig. Wenn `"error"` im Result → Auth fehlgeschlagen.
- **Graph API Simple-Upload**: `PUT https://graph.microsoft.com/v1.0/drives/{driveId}/root:/{path}/{filename}:/content` mit `Authorization: Bearer {token}` + `Content-Type: image/jpeg` + Body = bytes. Funktioniert für Dateien bis 4 MB (Microsoft-Limit für Simple-Upload) — unser Threshold von 3 MB liegt sicher darunter.
- **`FileResponse`** aus `fastapi.responses` — im Projekt prüfen ob bereits importiert. Falls nicht: `from fastapi.responses import FileResponse, HTMLResponse`.
- **HTMX `hx-encoding="multipart/form-data"`**: MUSS auf dem `<form>`-Element stehen (nicht auf dem `<input type="file">`). Ohne das sendet HTMX kein multipart-Body, UploadFile-Parameter in FastAPI ist leer.
- **`pathlib.Path.unlink(missing_ok=True)`**: Python 3.8+ — gibt keinen Fehler wenn Datei nicht existiert. In Python 3.12 vorhanden (Plattform-Constraint).
- **Magic-Bytes**: JPEG: `b"\xff\xd8\xff"` (3 Bytes genug), PNG: `b"\x89PNG\r\n\x1a\n"` (8 Bytes, erster Byte `\x89`, dann ASCII `PNG`).

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (Claude Code, /bmad-dev-story Workflow, 2026-04-23)

### Debug Log References

- `pytest -x` (in Container): 477 passed, 0 failed, 11 warnings (Deprecation-Noise aus Bestandscode).
- `tests/test_photo_store_unit.py`: 12 passed.
- `tests/test_steckbrief_impower_mirror_unit.py::test_mirror_discover_*`: 2 passed.
- `alembic upgrade head` (Postgres im Container): Migration 0013 → 0014 ohne Fehler.
- `docker compose restart app`: Lifespan-Init logged kein `sharepoint_init_failed` (PHOTO_BACKEND=local Default), `app.state.photo_store` ist `LocalPhotoStore`.

### Completion Notes List

- Migration 0014 verlängert die bestehende `steckbrief_photos`-Tabelle um Story-1.8-Felder. `op.add_column` mit `server_default` für `backend`/`filename`/`captured_at`, damit bestehende Rows (aus 0010) nicht NOT-NULL-violieren.
- ORM-Modell um die neuen Felder erweitert; Reihenfolge: nach `unit_id`, vor `drive_item_id` (Story-Vorgabe).
- `app/services/photo_store.py` neu: `validate_photo`, `LocalPhotoStore` (mit konfigurierbarem Root für Tests), `SharePointPhotoStore` (MSAL-Client-Credentials + Graph-API-Simple-Upload bis 4 MB), `create_photo_store(settings)` mit Auth-Probe-basierter Backend-Auswahl.
- `_run_photo_upload_bg` nutzt sync `def`-Pattern aus `mietverwaltung_write.py` (eigene `SessionLocal()` + `try/finally` + `asyncio.run`). AuditLog im BG direkt via `db.add(AuditLog(...))`, weil kein `Request` für den `audit()`-Helper verfuegbar ist.
- Foto-Card-Template rendert SharePoint-Fotos in v1 nur mit Dateinamen (Defer in `deferred-work.md`).
- HTMX-Pflicht `hx-encoding="multipart/form-data"` auf dem Upload-Form gesetzt; ohne das schickt HTMX kein multipart-Body und FastAPI's `UploadFile` ist leer.
- AC8 Discover: `Object.short_code` und `Object.name` sind im ORM `nullable=False`. Da `_reconcile_object` weder `short_code` noch `name` spiegelt, wird beim Discover ein deterministischer Platzhalter `f"impw-{pid}"` für beide Felder gesetzt — User benennt via Steckbrief-UI um. Defer-Eintrag dokumentiert diese Abweichung von der Story-Spec ("vorerst NULL lassen").
- Sync-Status-Tabelle (last_run + Historie) zeigt jetzt einen `Neu entdeckt`-Counter.
- `tests/test_steckbrief_routes_smoke.py::test_detail_sql_statement_count`-Budget von 9 → 10 erhöht: die Foto-Sektion fügt einen weiteren `SELECT FROM steckbrief_photos`-Hit hinzu (in Comment dokumentiert).
- `msal>=1.28` als Dependency aufgenommen; im laufenden Container nachinstalliert (`pip install msal>=1.28`); nach Image-Rebuild kommt sie via `pyproject.toml` automatisch mit.

### File List

**Neu:**
- `migrations/versions/0014_steckbrief_photos_fields.py`
- `app/services/photo_store.py`
- `app/templates/_obj_photo_card.html`
- `app/templates/_obj_photo_upload_form.html`
- `app/templates/_obj_photo_pending.html`
- `app/templates/_obj_photo_upload_result.html`
- `tests/test_photo_store_unit.py`

**Modifiziert:**
- `pyproject.toml`
- `app/config.py`
- `.env.op`
- `app/services/audit.py`
- `app/services/steckbrief.py`
- `app/services/photo_store.py` (s.o. — Neu)
- `app/services/_sync_common.py`
- `app/services/steckbrief_impower_mirror.py`
- `app/models/object.py`
- `app/main.py`
- `app/routers/objects.py`
- `app/routers/admin.py`
- `app/templates/_obj_technik.html`
- `app/templates/admin/home.html`
- `app/templates/admin/sync_status.html`
- `tests/test_steckbrief_impower_mirror_unit.py`
- `tests/test_steckbrief_routes_smoke.py`
- `output/implementation-artifacts/deferred-work.md`
- `output/implementation-artifacts/sprint-status.yaml`

### Review Findings (2026-04-23)

- [x] [Review][Patch] P1: `SharePointPhotoStore._http` — event-loop-Konflikt + Resource-Leak [app/services/photo_store.py:177] — **gefixt**: per-Request `async with httpx.AsyncClient()` statt persistentem Client
- [x] [Review][Patch] P2: `photo_file_serve` path-traversal via `str.startswith` [app/routers/objects.py:927] — **gefixt**: `safe.is_relative_to(root)`
- [x] [Review][Patch] P3: Filename-Injection in SharePoint-URL [app/services/photo_store.py:199] — **gefixt**: `urllib.parse.quote(filename, safe="")`
- [x] [Review][Patch] P4: `photo_status`/`photo_delete`/`photo_file_serve` ohne `accessible_object_ids`-Check [app/routers/objects.py] — **gefixt**: Access-Check vor DB-Lookup in allen drei Endpoints
- [x] [Review][Patch] P5: MSAL-Token-Fehler-Fallback nicht im Unit-Test abgedeckt [tests/test_photo_store_unit.py] — **gefixt**: `test_create_photo_store_returns_local_when_msal_token_fails` ergänzt
- [x] [Review][Defer] D1: `_get_token()` blockiert Event-Loop (MSAL cached, nur 1x/h) [app/services/photo_store.py:179] — deferred, pre-existing
- [x] [Review][Defer] D2: Orphan-Datei wenn DB-Commit nach Store-Upload scheitert [app/routers/objects.py] — deferred, pre-existing
- [x] [Review][Defer] D3: OOM durch `file.read()` vor Size-Check bei > 10 MB Uploads — deferred, Server-Config-Scope
- [x] [Review][Defer] D4: SharePoint-Zielpfad `DBS/Objekte/` nur via M365-Admin-Config, nicht code-seitig erzwungen — deferred, deployment-time decision
- [x] [Review][Defer] D5: `drive_item_id = None` wenn Graph-API `id`-Feld fehlt — deferred, benötigt live SharePoint zum Testen

## Change Log

- 2026-04-23 — Code-Review Story 1.8: 5 Patches (httpx event-loop fix, path-traversal, URL-encoding, access-gate, MSAL-Test), 5 Defer-Einträge.
- 2026-04-23 — Story 1.8 implementiert: Foto-Upload-Pipeline (LocalPhotoStore + SharePointPhotoStore), Lifespan-Init mit Fallback-Audit, 4 neue Endpoints (Upload sync/BG, Status-Polling, Delete, File-Serve), Technik-Sektions-Foto-Block + 4 neue Templates, Migration 0014, 12 Unit-Tests. AC8 Bonus: Impower-Object-Discover im Nightly-Mirror (neuer `Neu entdeckt`-Counter in /admin/sync-status, 2 Idempotenz-Tests). Volle Regression: 477 passed.
