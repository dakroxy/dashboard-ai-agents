"""Story 1.8 — Route-Smoke-Tests fuer die Foto-Endpoints auf /objects/{id}/photos.

Deckt die ACs ab, die bisher nur auf Service-Ebene getestet sind:
  * AC2: Validierter Upload (sync-Pfad) → Card-Fragment + DB-Row + Audit
  * AC3: Groesser Upload (>=3 MB) → Pending-Fragment + BackgroundTask +
         Status-Polling liefert done-Card, sobald der Task fertig ist
  * AC4: Ungueltige Content-Types/Magic-Bytes/Groessen → 400 mit Fragment,
         unbekannte component_ref → 400, kein DB-Row
  * AC5: File-Serve (local), Loeschen, Store-Delete-Fehler ist nicht-
         blockierend, SharePoint-backed → 404 (v1 liefert keine temp URL),
         Path-Traversal-Schutz → 403
  * AC6: Permission-Gates — Upload/Delete brauchen objects:edit,
         Status/File brauchen objects:view, Anon → 302 zu /login

Der Foto-Store wird per Fixture gegen einen ``LocalPhotoStore`` auf
``tmp_path`` getauscht, damit die Tests keine echten Dateien unter
``uploads/`` anlegen und auf jedem CI-Runner reproduzierbar laufen.
"""
from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import AuditLog, Object, SteckbriefPhoto, User
from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN
from app.services.photo_store import (
    LARGE_UPLOAD_THRESHOLD,
    MAGIC_BYTES,
    LocalPhotoStore,
)


# ---------------------------------------------------------------------------
# Test-Content-Helpers
# ---------------------------------------------------------------------------

_JPEG_PREFIX = MAGIC_BYTES["image/jpeg"]
_PNG_PREFIX = MAGIC_BYTES["image/png"]


def _jpeg_bytes(size: int = 256) -> bytes:
    return _JPEG_PREFIX + b"\x00" * max(0, size - len(_JPEG_PREFIX))


def _png_bytes(size: int = 256) -> bytes:
    return _PNG_PREFIX + b"\x00" * max(0, size - len(_PNG_PREFIX))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_object(db):
    """Minimal-Objekt fuer Foto-Tests."""
    def _make(short_code: str) -> Object:
        obj = Object(
            id=uuid.uuid4(),
            short_code=short_code,
            name=f"Foto-Objekt {short_code}",
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    return _make


@pytest.fixture
def local_store(tmp_path) -> LocalPhotoStore:
    """LocalPhotoStore mit tmp_path als Root — isoliert vom echten uploads/."""
    return LocalPhotoStore(root=tmp_path)


@pytest.fixture
def editor_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-foto-editor",
        email="foto-editor@dbshome.de",
        name="Foto Editor",
        permissions_extra=["objects:view", "objects:edit"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def viewer_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-foto-viewer",
        email="foto-viewer@dbshome.de",
        name="Foto Viewer",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def nonviewer_user(db) -> User:
    """User ohne objects:view — simuliert "angemeldet, aber kein Zugriff"."""
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-foto-none",
        email="foto-none@dbshome.de",
        name="Foto None",
        permissions_extra=["documents:upload"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _client_for(db, user: User, local_store: LocalPhotoStore) -> Iterator[TestClient]:
    """Hilfs-Context-Builder: TestClient mit User-Override + injiziertem Store."""
    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user
    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        app.state.photo_store = local_store
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def editor_client(db, editor_user, local_store) -> Iterator[TestClient]:
    yield from _client_for(db, editor_user, local_store)


@pytest.fixture
def viewer_client(db, viewer_user, local_store) -> Iterator[TestClient]:
    yield from _client_for(db, viewer_user, local_store)


@pytest.fixture
def nonviewer_client(db, nonviewer_user, local_store) -> Iterator[TestClient]:
    yield from _client_for(db, nonviewer_user, local_store)


# ---------------------------------------------------------------------------
# AC2 — Upload (sync, <3 MB)
# ---------------------------------------------------------------------------

def test_upload_sync_happy_path_creates_photo_row_and_audit(
    editor_client, editor_user, make_object, db
):
    obj = make_object("UP1")
    content = _jpeg_bytes(1024)
    response = editor_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("heizung.jpg", content, "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.text
    # Card-Fragment ist zurueckgekommen — enthaelt den Dateinamen
    assert "heizung.jpg" in body
    # DB-Row angelegt
    photos = db.query(SteckbriefPhoto).filter_by(object_id=obj.id).all()
    assert len(photos) == 1
    assert photos[0].backend == "local"
    assert photos[0].component_ref == "heizung_typenschild"
    assert photos[0].uploaded_by_user_id == editor_user.id
    # Audit-Row (sync-Pfad schreibt via audit()-Helper)
    audits = (
        db.query(AuditLog)
        .filter_by(entity_id=obj.id, action="object_photo_uploaded")
        .all()
    )
    assert len(audits) == 1


def test_upload_sync_png_also_accepted(editor_client, make_object):
    obj = make_object("UP2")
    response = editor_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "absperrpunkt_wasser"},
        files={"file": ("wasser.png", _png_bytes(2048), "image/png")},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC3 — Upload (BG, >=3 MB) + Status-Polling
# ---------------------------------------------------------------------------

def test_upload_large_triggers_background_task_and_returns_pending(
    editor_client, make_object, db
):
    obj = make_object("UP3")
    # >=3 MB schickt den Request durch den BG-Pfad.
    content = _jpeg_bytes(LARGE_UPLOAD_THRESHOLD + 1024)
    response = editor_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("gross.jpg", content, "image/jpeg")},
    )
    assert response.status_code == 200
    # Pending-Fragment hat eine HTMX-Polling-Anweisung auf den Status-Endpoint
    assert "hx-get" in response.text.lower() or "polling" in response.text.lower() \
        or "uploading" in response.text.lower()
    # DB-Row ist sofort da, initial photo_metadata.status = "uploading"
    photos = db.query(SteckbriefPhoto).filter_by(object_id=obj.id).all()
    assert len(photos) == 1
    # Nach TestClient-Kontext-Exit laufen BG-Tasks — wir pruefen, dass der
    # Eintrag entweder noch "uploading" ist oder bereits auf "done".
    status = (photos[0].photo_metadata or {}).get("status")
    assert status in {"uploading", "done"}


def test_status_polling_returns_pending_fragment_while_uploading(
    editor_client, make_object, db, editor_user
):
    obj = make_object("UP4")
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        filename="gross.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
        photo_metadata={"status": "uploading"},
    )
    db.add(photo)
    db.commit()
    response = editor_client.get(f"/objects/{obj.id}/photos/{photo.id}/status")
    assert response.status_code == 200
    # Pending-Template enthaelt "uploading" als sichtbaren Status-Hint
    assert "uploading" in response.text.lower() or "hx-get" in response.text.lower()


def test_status_polling_returns_card_when_done(
    editor_client, make_object, db, editor_user
):
    obj = make_object("UP5")
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        filename="fertig.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
        photo_metadata={"status": "done"},
    )
    db.add(photo)
    db.commit()
    response = editor_client.get(f"/objects/{obj.id}/photos/{photo.id}/status")
    assert response.status_code == 200
    # Card-Fragment referenziert den Dateinamen
    assert "fertig.jpg" in response.text


def test_status_polling_unknown_photo_returns_404(
    editor_client, make_object
):
    obj = make_object("UP6")
    response = editor_client.get(
        f"/objects/{obj.id}/photos/{uuid.uuid4()}/status"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC4 — Ungueltige Uploads
# ---------------------------------------------------------------------------

def test_upload_unknown_component_ref_returns_400(editor_client, make_object, db):
    obj = make_object("UP7")
    response = editor_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "backofen_typenschild"},  # nicht in Registry
        files={"file": ("x.jpg", _jpeg_bytes(500), "image/jpeg")},
    )
    assert response.status_code == 400
    # Kein DB-Row angelegt
    assert db.query(SteckbriefPhoto).filter_by(object_id=obj.id).count() == 0


def test_upload_wrong_content_type_returns_400(editor_client, make_object, db):
    obj = make_object("UP8")
    response = editor_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("doc.pdf", b"%PDF-1.4\n...", "application/pdf")},
    )
    assert response.status_code == 400
    assert db.query(SteckbriefPhoto).filter_by(object_id=obj.id).count() == 0


def test_upload_mismatched_magic_bytes_returns_400(editor_client, make_object, db):
    obj = make_object("UP9")
    # Content-Type sagt JPEG, Bytes sind PNG
    response = editor_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("lie.jpg", _png_bytes(500), "image/jpeg")},
    )
    assert response.status_code == 400
    assert db.query(SteckbriefPhoto).filter_by(object_id=obj.id).count() == 0


def test_upload_for_unknown_object_returns_404(editor_client):
    response = editor_client.post(
        f"/objects/{uuid.uuid4()}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("x.jpg", _jpeg_bytes(500), "image/jpeg")},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC5 — File-Serve + Delete
# ---------------------------------------------------------------------------

def test_file_serve_local_returns_file_bytes(
    editor_client, make_object, db, editor_user
):
    """file_serve verifiziert ``is_relative_to(pathlib.Path("uploads").resolve())``
    als Path-Traversal-Schutz — die zu servierende Datei muss wirklich unter
    ``uploads/`` liegen. Deshalb tauschen wir fuer diesen Test den tmp_path-
    Store gegen einen Store, der in den echten Upload-Ordner schreibt, und
    raeumen die Test-Datei am Ende wieder auf."""
    import pathlib
    import shutil

    obj = make_object("FS1")
    content = _jpeg_bytes(400)
    app.state.photo_store = LocalPhotoStore(root="uploads")
    try:
        upload = editor_client.post(
            f"/objects/{obj.id}/photos",
            data={"component_ref": "heizung_typenschild"},
            files={"file": ("served.jpg", content, "image/jpeg")},
        )
        assert upload.status_code == 200
        photo = db.query(SteckbriefPhoto).filter_by(object_id=obj.id).first()
        response = editor_client.get(
            f"/objects/{obj.id}/photos/{photo.id}/file"
        )
        assert response.status_code == 200
        # Bytes matchen den Upload (SHA256-dedup)
        assert response.content == content
    finally:
        test_dir = pathlib.Path("uploads/objects/FS1")
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)


def test_file_serve_sharepoint_backed_returns_404_in_v1(
    editor_client, make_object, db, editor_user
):
    obj = make_object("FS2")
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="sharepoint",
        drive_item_id="some-drive-id",
        filename="remote.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
    )
    db.add(photo)
    db.commit()
    response = editor_client.get(
        f"/objects/{obj.id}/photos/{photo.id}/file"
    )
    # v1 liefert keine temporaeren Graph-Download-URLs (defer → v1.1).
    assert response.status_code == 404


def test_file_serve_path_traversal_rejected(
    editor_client, make_object, db, editor_user
):
    obj = make_object("FS3")
    # Manipulierte local_path-Row, die auf /etc/passwd zeigt — soll 403 liefern.
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        local_path="/etc/passwd",
        filename="passwd",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
    )
    db.add(photo)
    db.commit()
    response = editor_client.get(
        f"/objects/{obj.id}/photos/{photo.id}/file"
    )
    assert response.status_code == 403


def test_delete_removes_row_and_writes_audit(
    editor_client, make_object, db, editor_user
):
    obj = make_object("DEL1")
    upload = editor_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("bye.jpg", _jpeg_bytes(400), "image/jpeg")},
    )
    assert upload.status_code == 200
    photo = db.query(SteckbriefPhoto).filter_by(object_id=obj.id).first()
    response = editor_client.delete(
        f"/objects/{obj.id}/photos/{photo.id}"
    )
    assert response.status_code == 200
    assert db.query(SteckbriefPhoto).filter_by(id=photo.id).first() is None
    audits = (
        db.query(AuditLog)
        .filter_by(entity_id=obj.id, action="object_photo_deleted")
        .all()
    )
    assert len(audits) == 1


def test_delete_store_error_does_not_block_db_delete(
    editor_client, make_object, db, editor_user, local_store, monkeypatch
):
    """Store-Backend wirft bei Delete → DB-Row muss trotzdem verschwinden
    (Saga-Regel aus Story 1.8: lieber Datei-Leiche als DB-Zombie)."""
    obj = make_object("DEL2")
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        local_path=str(obj.id) + ".jpg",  # existiert nicht, aber egal
        filename="ghost.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
    )
    db.add(photo)
    db.commit()

    async def _raise(_ref):
        raise RuntimeError("SharePoint ist kaputt")

    monkeypatch.setattr(local_store, "delete", _raise)
    response = editor_client.delete(
        f"/objects/{obj.id}/photos/{photo.id}"
    )
    assert response.status_code == 200
    assert db.query(SteckbriefPhoto).filter_by(id=photo.id).first() is None


def test_delete_unknown_photo_returns_404(editor_client, make_object):
    obj = make_object("DEL3")
    response = editor_client.delete(
        f"/objects/{obj.id}/photos/{uuid.uuid4()}"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC6 — Permission-Gates
# ---------------------------------------------------------------------------

def test_upload_forbidden_for_viewer(viewer_client, make_object, db):
    obj = make_object("PERM1")
    response = viewer_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("x.jpg", _jpeg_bytes(400), "image/jpeg")},
    )
    assert response.status_code == 403
    assert db.query(SteckbriefPhoto).filter_by(object_id=obj.id).count() == 0


def test_delete_forbidden_for_viewer(
    viewer_client, make_object, db, viewer_user
):
    obj = make_object("PERM2")
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        local_path="x",
        filename="pin.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=viewer_user.id,
    )
    db.add(photo)
    db.commit()
    response = viewer_client.delete(
        f"/objects/{obj.id}/photos/{photo.id}"
    )
    assert response.status_code == 403
    assert db.query(SteckbriefPhoto).filter_by(id=photo.id).first() is not None


def test_status_polling_requires_objects_view(
    nonviewer_client, make_object, db, nonviewer_user
):
    obj = make_object("PERM3")
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        local_path="x",
        filename="pin.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=nonviewer_user.id,
    )
    db.add(photo)
    db.commit()
    response = nonviewer_client.get(
        f"/objects/{obj.id}/photos/{photo.id}/status"
    )
    assert response.status_code == 403


def test_file_serve_requires_objects_view(
    nonviewer_client, make_object, db, nonviewer_user
):
    obj = make_object("PERM4")
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        local_path="x",
        filename="pin.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=nonviewer_user.id,
    )
    db.add(photo)
    db.commit()
    response = nonviewer_client.get(
        f"/objects/{obj.id}/photos/{photo.id}/file"
    )
    assert response.status_code == 403


def test_upload_anonymous_blocked(anon_client, make_object):
    obj = make_object("PERM5")
    response = anon_client.post(
        f"/objects/{obj.id}/photos",
        data={"component_ref": "heizung_typenschild"},
        files={"file": ("x.jpg", _jpeg_bytes(400), "image/jpeg")},
    )
    # Production: CSRFMiddleware blockt mit 403, bevor Auth-Layer redirected.
    # Falls die Middleware-Order kuenftig anders liegt, ist 302/307/401 auch ok.
    assert response.status_code in (302, 307, 401, 403)
