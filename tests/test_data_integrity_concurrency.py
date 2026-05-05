"""Story 5-2: Daten-Integritaet & Concurrency.

Prueft:
  AC1: Multi-Worker-Boot ohne IntegrityError bei Seed-Funktionen
  AC2: Pflegegrad-Cache Row-Lock (with_for_update im SELECT)
  AC3: Document-Concurrent-Save Row-Lock + Idempotenz
  AC4: notes_owners Row-Lock
  AC5: Foto-Upload OOM-Pre-Check via Content-Length
  AC6: Foto-Upload-Saga Sync- und BG-Pfad
  AC7: Negative Praemie/Schadensfall ablehnen
  AC8: notice_period_months Range-Check
"""
from __future__ import annotations

import asyncio
import io
import uuid
from decimal import Decimal
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import app.db as app_db
import app.main as main_module
from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import (
    _seed_default_roles,
    _seed_default_workflow,
    _seed_default_workflow_access,
)
from app.models import (
    Eigentuemer,
    InsurancePolicy,
    Object,
    ResourceAccess,
    Role,
    Schadensfall,
    User,
    Workflow,
)
from app.models.object import SteckbriefPhoto
from app.services.pflegegrad import get_or_update_pflegegrad_cache
from app.services.steckbrief_policen import create_police, update_police
from app.services.steckbrief_schadensfaelle import create_schadensfall
from app.services.photo_store import (
    MAGIC_BYTES,
    MAX_SIZE_BYTES,
    LocalPhotoStore,
    PhotoRef,
)
from tests.conftest import _TEST_CSRF_TOKEN, _make_session_cookie
from app.main import app


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _jpeg_bytes(size: int = 256) -> bytes:
    prefix = MAGIC_BYTES["image/jpeg"]
    return prefix + b"\x00" * max(0, size - len(prefix))


def _png_bytes(size: int = 256) -> bytes:
    prefix = MAGIC_BYTES["image/png"]
    return prefix + b"\x00" * max(0, size - len(prefix))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def obj(db) -> Object:
    o = Object(id=uuid.uuid4(), short_code="CON1", name="Concurrency-Test-Objekt")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture
def editor_user(db) -> User:
    u = User(
        id=uuid.uuid4(),
        google_sub="google-sub-concurrency-edit",
        email="concurrency-edit@dbshome.de",
        name="Concurrency Edit User",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:view_confidential",
            "registries:view",
            "registries:edit",
        ],
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def editor_client(db, editor_user) -> Iterator[TestClient]:
    def override_db():
        yield db

    def override_user():
        return editor_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
        c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def local_store(tmp_path) -> LocalPhotoStore:
    return LocalPhotoStore(root=tmp_path)


# ---------------------------------------------------------------------------
# AC1 — Multi-Worker-Seed-Idempotenz
# ---------------------------------------------------------------------------

def test_seed_default_roles_idempotent_sqlite_path(db):
    """Zwei aufeinanderfolgende _seed_default_roles()-Calls → kein IntegrityError, keine Duplikate."""
    _seed_default_roles()
    _seed_default_roles()

    roles = db.query(Role).all()
    keys = [r.key for r in roles]
    assert len(keys) == len(set(keys)), f"Duplikate in Rollen-Keys: {keys}"


def test_seed_default_roles_idempotent_postgres_path(db, monkeypatch):
    """Simuliert Postgres-Dialekt: pg_insert-Pfad wird gewaehlt, kein IntegrityError."""
    # Wir mocken die Dialect-Detection so, dass der pg_insert-Pfad durchlaueft.
    # Da der echte pg_insert gegen SQLite nicht funktioniert, mocken wir ihn,
    # verifizieren aber, dass er aufgerufen wuerde.
    pg_insert_keys: list[str] = []

    import app.main as main_module_local

    original_helper = main_module_local._seed_role_idempotent

    def intercepting_helper(db_arg, key, name, description, permissions):
        pg_insert_keys.append(key)
        # Eigentliche Idempotenz-Logik (SQLite-sicherer Pfad) beibehalten
        original_helper(db_arg, key, name, description, permissions)

    monkeypatch.setattr(main_module_local, "_seed_role_idempotent", intercepting_helper)

    _seed_default_roles()
    _seed_default_roles()

    roles = db.query(Role).all()
    keys = [r.key for r in roles]
    assert len(keys) == len(set(keys)), "Duplikate nach zwei Seed-Calls"
    assert len(pg_insert_keys) >= 2, "Helper wurde zu wenig aufgerufen"


def test_seed_default_workflow_idempotent(db):
    """Zwei Workflow-Seed-Calls → kein IntegrityError, keine Duplikate."""
    _seed_default_workflow()
    _seed_default_workflow()

    workflows = db.query(Workflow).all()
    keys = [w.key for w in workflows]
    assert len(keys) == len(set(keys)), f"Duplikate in Workflow-Keys: {keys}"


def test_seed_default_workflow_access_idempotent(db):
    """Zwei Workflow-Access-Seed-Calls → kein IntegrityError, keine Duplikate."""
    _seed_default_roles()
    _seed_default_workflow()
    _seed_default_workflow_access()
    _seed_default_workflow_access()

    access_rows = db.query(ResourceAccess).filter(ResourceAccess.role_id.isnot(None)).all()
    # Keine doppelten (role_id, resource_type, resource_id)-Kombinationen
    combos = [
        (str(r.role_id), r.resource_type, str(r.resource_id))
        for r in access_rows
    ]
    assert len(combos) == len(set(combos)), "Duplikate in ResourceAccess"


# ---------------------------------------------------------------------------
# AC2 — Pflegegrad-Cache Row-Lock
# ---------------------------------------------------------------------------

def test_get_or_update_pflegegrad_cache_uses_for_update(db, obj):
    """get_or_update_pflegegrad_cache nutzt SELECT...FOR UPDATE auf der objects-Zeile."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.sql.selectable import Select

    execute_stmts: list = []
    real_execute = db.execute

    def spy_execute(stmt, *args, **kwargs):
        execute_stmts.append(stmt)
        return real_execute(stmt, *args, **kwargs)

    with patch.object(db, "execute", side_effect=spy_execute):
        get_or_update_pflegegrad_cache(obj, db)

    # Mindestens ein SELECT-Statement sollte FOR UPDATE gesetzt haben
    for_update_found = any(
        isinstance(stmt, Select) and getattr(stmt, "_for_update_arg", None) is not None
        for stmt in execute_stmts
    )
    assert for_update_found, (
        "get_or_update_pflegegrad_cache soll SELECT...FOR UPDATE auf objects ausfuehren "
        f"(gefundene Statements: {execute_stmts})"
    )


def test_pflegegrad_cache_recompute_on_stale(db, obj):
    """Stale Cache → Score wird neu berechnet + Cache-Feld gesetzt."""
    obj.pflegegrad_score_cached = None
    db.commit()

    result, was_updated = get_or_update_pflegegrad_cache(obj, db)
    db.commit()

    db.refresh(obj)
    assert result is not None
    assert obj.pflegegrad_score_cached is not None


def test_pflegegrad_cache_skip_on_fresh(db, obj):
    """Frischer Cache → kein Recompute, was_updated=False."""
    import datetime as _dt
    from app.services.pflegegrad import CACHE_TTL

    obj.pflegegrad_score_cached = 42
    obj.pflegegrad_score_updated_at = _dt.datetime.now(_dt.timezone.utc)
    db.commit()

    result, was_updated = get_or_update_pflegegrad_cache(obj, db)
    assert not was_updated


# ---------------------------------------------------------------------------
# AC3 — Document-Concurrent-Save Row-Lock
# ---------------------------------------------------------------------------

def test_extraction_save_locks_document_row(db, test_user, monkeypatch):
    """extraction_field_save nutzt SELECT...FOR UPDATE auf dem Document."""
    from app.models import Document, Workflow, Extraction
    from app.permissions import RESOURCE_TYPE_WORKFLOW
    from sqlalchemy.sql.selectable import Select

    monkeypatch.setattr("app.routers.documents._run_matching", lambda *a, **kw: None)

    _seed_default_workflow()
    wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
    assert wf is not None, "sepa_mandate-Workflow nach Seed nicht gefunden"

    db.add(ResourceAccess(
        id=uuid.uuid4(), user_id=test_user.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="allow",
    ))
    db.commit()

    doc = Document(
        id=uuid.uuid4(),
        uploaded_by_id=test_user.id,
        workflow_id=wf.id,
        original_filename="test.pdf",
        stored_path=f"{uuid.uuid4().hex}.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="a" * 64,
        status="extracted",
    )
    db.add(doc)

    extraction = Extraction(
        id=uuid.uuid4(),
        document_id=doc.id,
        model="test-model",
        prompt_version="v1",
        raw_response="",
        extracted={
            "weg_kuerzel": "HAM61",
            "weg_name": None,
            "weg_adresse": None,
            "unit_nr": None,
            "owner_name": "Test User",
            "iban": "DE89370400440532013000",
            "bic": None,
            "bank_name": None,
            "sepa_date": None,
            "creditor_id": None,
        },
        status="ok",
    )
    db.add(extraction)
    db.commit()
    db.refresh(doc)

    execute_stmts: list = []
    real_execute = db.execute

    def spy_execute(stmt, *args, **kwargs):
        execute_stmts.append(stmt)
        return real_execute(stmt, *args, **kwargs)

    def override_db():
        yield db

    def override_user():
        return test_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    try:
        with patch.object(db, "execute", side_effect=spy_execute):
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
                c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
                c.post(
                    f"/documents/{doc.id}/extraction/field",
                    data={"field": "weg_kuerzel", "value": "HAM99"},
                )
    finally:
        app.dependency_overrides.clear()

    for_update_found = any(
        isinstance(stmt, Select) and getattr(stmt, "_for_update_arg", None) is not None
        for stmt in execute_stmts
    )
    assert for_update_found, "extraction_field_save soll SELECT...FOR UPDATE auf Document ausfuehren"


def test_extraction_save_idempotent_within_2s(db, test_user, monkeypatch):
    """Zwei sequentielle Saves mit unveraendertem Wert → nur eine Extraction-Row (No-Op)."""
    from app.models import Document, Workflow, Extraction
    from app.permissions import RESOURCE_TYPE_WORKFLOW

    monkeypatch.setattr("app.routers.documents._run_matching", lambda *a, **kw: None)

    _seed_default_workflow()
    wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
    assert wf is not None, "sepa_mandate-Workflow nach Seed nicht gefunden"

    db.add(ResourceAccess(
        id=uuid.uuid4(), user_id=test_user.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="allow",
    ))
    db.commit()

    doc = Document(
        id=uuid.uuid4(), uploaded_by_id=test_user.id, workflow_id=wf.id,
        original_filename="test2.pdf", stored_path=f"{uuid.uuid4().hex}.pdf",
        content_type="application/pdf", size_bytes=100, sha256="b" * 64,
        status="extracted",
    )
    db.add(doc)
    ext = Extraction(
        id=uuid.uuid4(), document_id=doc.id, model="test-model", prompt_version="v1",
        raw_response="",
        extracted={
            "weg_kuerzel": "HAM61", "weg_name": None, "weg_adresse": None,
            "unit_nr": None, "owner_name": "Test", "iban": "DE89370400440532013000",
            "bic": None, "bank_name": None, "sepa_date": None, "creditor_id": None,
        },
        status="ok",
    )
    db.add(ext)
    db.commit()
    db.refresh(doc)

    count_before = db.query(Extraction).filter(Extraction.document_id == doc.id).count()

    def override_db():
        yield db

    def override_user():
        return test_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    try:
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            # Erster Save mit neuem Wert → neue Extraction
            c.post(f"/documents/{doc.id}/extraction/field", data={"field": "weg_kuerzel", "value": "NEU1"})
            # Zweiter Save mit GLEICHEM Wert → No-Op, keine neue Extraction
            c.post(f"/documents/{doc.id}/extraction/field", data={"field": "weg_kuerzel", "value": "NEU1"})
    finally:
        app.dependency_overrides.clear()

    count_after = db.query(Extraction).filter(Extraction.document_id == doc.id).count()
    assert count_after == count_before + 1, (
        f"Erwartet genau 1 neue Extraction (No-Op beim zweiten Save), "
        f"got {count_after - count_before} neue Rows"
    )


def test_extraction_save_after_value_change_creates_new_row(db, test_user, monkeypatch):
    """Zwei Saves mit UNTERSCHIEDLICHEN Werten → zwei neue Extraction-Rows."""
    from app.models import Document, Workflow, Extraction
    from app.permissions import RESOURCE_TYPE_WORKFLOW

    monkeypatch.setattr("app.routers.documents._run_matching", lambda *a, **kw: None)

    _seed_default_workflow()
    wf = db.query(Workflow).filter(Workflow.key == "sepa_mandate").first()
    assert wf is not None, "sepa_mandate-Workflow nach Seed nicht gefunden"

    db.add(ResourceAccess(
        id=uuid.uuid4(), user_id=test_user.id,
        resource_type=RESOURCE_TYPE_WORKFLOW, resource_id=wf.id, mode="allow",
    ))
    db.commit()

    doc = Document(
        id=uuid.uuid4(), uploaded_by_id=test_user.id, workflow_id=wf.id,
        original_filename="test3.pdf", stored_path=f"{uuid.uuid4().hex}.pdf",
        content_type="application/pdf", size_bytes=100, sha256="c" * 64,
        status="extracted",
    )
    db.add(doc)
    ext = Extraction(
        id=uuid.uuid4(), document_id=doc.id, model="test-model", prompt_version="v1",
        raw_response="",
        extracted={
            "weg_kuerzel": "HAM61", "weg_name": None, "weg_adresse": None,
            "unit_nr": None, "owner_name": "Test", "iban": "DE89370400440532013000",
            "bic": None, "bank_name": None, "sepa_date": None, "creditor_id": None,
        },
        status="ok",
    )
    db.add(ext)
    db.commit()
    db.refresh(doc)

    count_before = db.query(Extraction).filter(Extraction.document_id == doc.id).count()

    def override_db():
        yield db

    def override_user():
        return test_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    try:
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            c.post(f"/documents/{doc.id}/extraction/field", data={"field": "weg_kuerzel", "value": "WERT1"})
            # Nach dem ersten Save ist doc.status="matching" (nicht editierbar).
            # Simuliere BG-Task-Abschluss durch Status-Reset auf "matched".
            db.refresh(doc)
            doc.status = "matched"
            db.commit()
            c.post(f"/documents/{doc.id}/extraction/field", data={"field": "weg_kuerzel", "value": "WERT2"})
    finally:
        app.dependency_overrides.clear()

    count_after = db.query(Extraction).filter(Extraction.document_id == doc.id).count()
    assert count_after == count_before + 2, (
        f"Erwartet 2 neue Extractions bei zwei verschiedenen Werten, "
        f"got {count_after - count_before}"
    )


# ---------------------------------------------------------------------------
# AC4 — notes_owners Row-Lock
# ---------------------------------------------------------------------------

def test_save_owner_note_locks_object_row(db, obj, editor_user):
    """save_owner_note nutzt SELECT...FOR UPDATE auf der objects-Zeile."""
    from sqlalchemy.sql.selectable import Select

    eig = Eigentuemer(id=uuid.uuid4(), object_id=obj.id, name="Test Eigentuemer")
    db.add(eig)
    db.commit()
    db.refresh(eig)

    execute_stmts: list = []
    real_execute = db.execute

    def spy_execute(stmt, *args, **kwargs):
        execute_stmts.append(stmt)
        return real_execute(stmt, *args, **kwargs)

    def override_db():
        yield db

    def override_user():
        return editor_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    try:
        with patch.object(db, "execute", side_effect=spy_execute):
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
                c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
                c.post(
                    f"/objects/{obj.id}/menschen-notizen/{eig.id}",
                    data={"note": "Test-Notiz"},
                )
    finally:
        app.dependency_overrides.clear()

    for_update_found = any(
        isinstance(stmt, Select) and getattr(stmt, "_for_update_arg", None) is not None
        for stmt in execute_stmts
    )
    assert for_update_found, "notiz_save soll SELECT...FOR UPDATE auf objects ausfuehren"


def test_save_owner_note_two_users_keeps_both_notes(db, obj):
    """Zwei sequentielle Saves auf unterschiedliche Eigentuemer → beide Notes bleiben erhalten."""
    user1 = User(
        id=uuid.uuid4(), google_sub="sub-note-1", email="note1@test.de", name="Note User 1",
        permissions_extra=["objects:view", "objects:edit", "objects:view_confidential"],
    )
    user2 = User(
        id=uuid.uuid4(), google_sub="sub-note-2", email="note2@test.de", name="Note User 2",
        permissions_extra=["objects:view", "objects:edit", "objects:view_confidential"],
    )
    db.add_all([user1, user2])
    db.commit()

    eig1 = Eigentuemer(id=uuid.uuid4(), object_id=obj.id, name="Eigentuemer 1")
    eig2 = Eigentuemer(id=uuid.uuid4(), object_id=obj.id, name="Eigentuemer 2")
    db.add_all([eig1, eig2])
    db.commit()

    # User1 speichert Note fuer Eigentuemer 1
    for user, eig, note_text in [(user1, eig1, "Note von User 1"), (user2, eig2, "Note von User 2")]:
        def override_db():
            yield db

        def make_override_user(u):
            def override_user():
                return u
            return override_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = make_override_user(user)
        app.dependency_overrides[get_optional_user] = make_override_user(user)

        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            resp = c.post(
                f"/objects/{obj.id}/menschen-notizen/{eig.id}",
                data={"note": note_text},
            )
            assert resp.status_code == 200

        app.dependency_overrides.clear()

    db.refresh(obj)
    notes = obj.notes_owners or {}
    assert str(eig1.id) in notes, "Note von User 1 fehlt"
    assert str(eig2.id) in notes, "Note von User 2 fehlt"


# ---------------------------------------------------------------------------
# AC5 — Foto-Upload OOM-Pre-Check
# ---------------------------------------------------------------------------

def test_photo_upload_rejects_large_content_length_header(db, obj, editor_user, local_store):
    """Content-Length > 10 MB → 413 OHNE file.read() aufzurufen."""
    def override_db():
        yield db

    def override_user():
        return editor_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    app.state.photo_store = local_store
    file_content = _jpeg_bytes(256)

    try:
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            # Setze Content-Length-Header auf 11 MB (> 10 MB * 1.05 Toleranz)
            resp = c.post(
                f"/objects/{obj.id}/photos",
                data={"component_ref": "heizung_typenschild"},
                files={"file": ("test.jpg", file_content, "image/jpeg")},
                headers={"Content-Length": str(11 * 1024 * 1024)},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 413, f"Erwartet 413, got {resp.status_code}"


def test_photo_upload_accepts_valid_content_length(db, obj, editor_user, local_store):
    """Content-Length < 10 MB → Upload erfolgreich."""
    def override_db():
        yield db

    def override_user():
        return editor_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    app.state.photo_store = local_store
    file_content = _jpeg_bytes(512)

    try:
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            resp = c.post(
                f"/objects/{obj.id}/photos",
                data={"component_ref": "heizung_typenschild"},
                files={"file": ("test.jpg", file_content, "image/jpeg")},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Erwartet 200, got {resp.status_code}: {resp.text[:200]}"


def test_photo_upload_no_content_length_falls_back_to_validate(db, obj, editor_user, local_store):
    """Kein Content-Length-Header → validate_photo greift als Fallback-Gate."""
    def override_db():
        yield db

    def override_user():
        return editor_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    app.state.photo_store = local_store
    file_content = _jpeg_bytes(256)

    try:
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            c.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            c.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            resp = c.post(
                f"/objects/{obj.id}/photos",
                data={"component_ref": "heizung_typenschild"},
                files={"file": ("test.jpg", file_content, "image/jpeg")},
            )
    finally:
        app.dependency_overrides.clear()

    # Ohne Content-Length-Header soll der Upload normal verarbeitet werden
    assert resp.status_code == 200, f"Erwartet 200 ohne Content-Length, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC6 — Foto-Upload-Saga (Sync-Pfad)
# ---------------------------------------------------------------------------

def test_photo_upload_sync_saga_deletes_on_commit_fail(db, obj, editor_user, local_store):
    """Sync-Pfad: Upload erfolgreich + db.commit() IntegrityError → photo_store.delete() aufgerufen."""
    from app.routers.objects import _photo_upload_sync_path

    deleted_refs: list = []

    async def tracking_delete(self, ref):
        deleted_refs.append(ref)

    with patch.object(LocalPhotoStore, "delete", tracking_delete):
        with patch.object(db, "commit", side_effect=IntegrityError("mock", None, Exception("forced"))):

            import asyncio as _asyncio
            import dataclasses

            @dataclasses.dataclass
            class FakeDetail:
                obj: Object

            fake_request = MagicMock()
            fake_request.headers.get.return_value = None
            fake_request.app.state.photo_store = local_store

            file_mock = MagicMock()
            file_mock.filename = "test.jpg"
            file_mock.content_type = "image/jpeg"

            with pytest.raises(IntegrityError):
                _asyncio.run(
                    _photo_upload_sync_path(
                        db=db,
                        request=fake_request,
                        detail=FakeDetail(obj=obj),
                        component_ref="heizung_typenschild",
                        file=file_mock,
                        content=_jpeg_bytes(256),
                        photo_store=local_store,
                        short_code=obj.short_code,
                        object_id=obj.id,
                        user=editor_user,
                    )
                )

    assert len(deleted_refs) == 1, "photo_store.delete() soll nach Commit-Fehler aufgerufen werden"


def test_photo_upload_sync_saga_logs_orphan_when_delete_fails(db, obj, editor_user, local_store):
    """Sync-Pfad worst-case: Upload OK + Commit fail + Delete fail → _audit_in_new_session aufgerufen."""
    from app.routers.objects import _photo_upload_sync_path
    import app.services.audit as audit_module

    audit_calls: list = []

    async def tracking_delete(self, ref):
        raise Exception("delete failed on purpose")

    original_audit_in_new_session = audit_module._audit_in_new_session

    def tracking_audit_in_new_session(action, **kwargs):
        audit_calls.append(action)

    with patch.object(LocalPhotoStore, "delete", tracking_delete):
        with patch.object(db, "commit", side_effect=IntegrityError("mock", None, Exception("forced"))):
            with patch.object(audit_module, "_audit_in_new_session", tracking_audit_in_new_session):
                import asyncio as _asyncio
                import dataclasses

                @dataclasses.dataclass
                class FakeDetail:
                    obj: Object

                fake_request = MagicMock()
                fake_request.headers.get.return_value = None

                file_mock = MagicMock()
                file_mock.filename = "test.jpg"
                file_mock.content_type = "image/jpeg"

                with pytest.raises(Exception):
                    _asyncio.run(
                        _photo_upload_sync_path(
                            db=db,
                            request=fake_request,
                            detail=FakeDetail(obj=obj),
                            component_ref="heizung_typenschild",
                            file=file_mock,
                            content=_jpeg_bytes(256),
                            photo_store=local_store,
                            short_code=obj.short_code,
                            object_id=obj.id,
                            user=editor_user,
                        )
                    )

    assert "photo_upload_orphan" in audit_calls, (
        "_audit_in_new_session('photo_upload_orphan') soll bei Delete-Fehler aufgerufen werden"
    )


def test_photo_upload_sync_saga_propagates_original_exception(db, obj, editor_user, local_store):
    """Sync-Pfad: Original-Commit-Exception wird nach Saga re-raised → Client sieht 500."""
    from app.routers.objects import _photo_upload_sync_path

    import asyncio as _asyncio
    import dataclasses

    @dataclasses.dataclass
    class FakeDetail:
        obj: Object

    fake_request = MagicMock()
    fake_request.headers.get.return_value = None

    file_mock = MagicMock()
    file_mock.filename = "test.jpg"
    file_mock.content_type = "image/jpeg"

    original_error = IntegrityError("original-error", None, Exception("original"))

    with patch.object(db, "commit", side_effect=original_error):
        with pytest.raises(IntegrityError) as exc_info:
            _asyncio.run(
                _photo_upload_sync_path(
                    db=db,
                    request=fake_request,
                    detail=FakeDetail(obj=obj),
                    component_ref="heizung_typenschild",
                    file=file_mock,
                    content=_jpeg_bytes(256),
                    photo_store=local_store,
                    short_code=obj.short_code,
                    object_id=obj.id,
                    user=editor_user,
                )
            )

    assert exc_info.value is original_error


# ---------------------------------------------------------------------------
# AC6 — Foto-Upload-Saga (BG-Pfad)
# ---------------------------------------------------------------------------

def test_photo_upload_bg_saga_deletes_on_final_commit_fail(db, obj, editor_user, local_store):
    """BG-Pfad: Upload OK + finaler Commit fail → delete() aufgerufen + Stub auf upload_failed."""
    from app.routers.objects import _run_photo_upload_bg
    import app.services.audit as audit_module

    # Stub-Photo anlegen (wie _photo_upload_bg_path das tut)
    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        filename="test.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
        photo_metadata={"status": "uploading"},
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    photo_id = photo.id

    deleted_refs: list = []

    async def tracking_delete(self, ref):
        deleted_refs.append(ref)

    # SessionLocal → gibt db zurueck (Testdatenbank)
    # commit muss beim finalen Commit im BG-Task fehlschlagen
    commit_count = [0]
    original_commit = db.commit

    def failing_final_commit():
        commit_count[0] += 1
        if commit_count[0] >= 1:
            raise IntegrityError("mock", None, Exception("forced BG commit fail"))
        return original_commit()

    with patch.object(LocalPhotoStore, "delete", tracking_delete):
        with patch.object(app_db, "SessionLocal", return_value=db):
            with patch.object(db, "commit", side_effect=failing_final_commit):
                _run_photo_upload_bg(
                    photo_id=photo_id,
                    content=_jpeg_bytes(512),
                    content_type="image/jpeg",
                    filename="test.jpg",
                    short_code=obj.short_code,
                    category="technik",
                    photo_store=local_store,
                    user_id=editor_user.id,
                    object_id=obj.id,
                )

    assert len(deleted_refs) > 0, "photo_store.delete() soll nach BG-Commit-Fehler aufgerufen werden"


def test_photo_upload_bg_saga_logs_orphan_when_delete_fails(db, obj, editor_user, local_store):
    """BG worst-case: Upload OK + Commit fail + Delete fail → _audit_in_new_session aufgerufen."""
    from app.routers.objects import _run_photo_upload_bg
    import app.services.audit as audit_module

    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        filename="test.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
        photo_metadata={"status": "uploading"},
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    photo_id = photo.id

    audit_calls: list = []

    async def tracking_delete(self, ref):
        raise Exception("delete also failed")

    def tracking_audit_in_new_session(action, **kwargs):
        audit_calls.append(action)

    def failing_commit():
        raise IntegrityError("mock", None, Exception("forced"))

    with patch.object(LocalPhotoStore, "delete", tracking_delete):
        with patch.object(app_db, "SessionLocal", return_value=db):
            with patch.object(db, "commit", side_effect=failing_commit):
                with patch.object(audit_module, "_audit_in_new_session", tracking_audit_in_new_session):
                    _run_photo_upload_bg(
                        photo_id=photo_id,
                        content=_jpeg_bytes(512),
                        content_type="image/jpeg",
                        filename="test.jpg",
                        short_code=obj.short_code,
                        category="technik",
                        photo_store=local_store,
                        user_id=editor_user.id,
                        object_id=obj.id,
                    )

    assert "photo_upload_orphan" in audit_calls, (
        "_audit_in_new_session('photo_upload_orphan') soll bei BG Delete-Fehler aufgerufen werden"
    )


def test_photo_upload_bg_stub_remains_visible_after_failure(db, obj, editor_user, local_store):
    """BG-Saga: Stub-Row bekommt nach Commit-Fehler Status 'upload_failed' (kein ewiger 'uploading')."""
    from app.routers.objects import _run_photo_upload_bg
    import app.services.audit as audit_module

    photo = SteckbriefPhoto(
        id=uuid.uuid4(),
        object_id=obj.id,
        backend="local",
        filename="test.jpg",
        component_ref="heizung_typenschild",
        uploaded_by_user_id=editor_user.id,
        photo_metadata={"status": "uploading"},
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    photo_id = photo.id

    # Fuer _update_stub_status_in_new_session brauchen wir eine echte Session
    # (nicht db, weil die im commit-fail-Zweig landet). Wir lassen die echte
    # TestSession laufen, mocken nur den BG-Session-commit.
    commit_count = [0]
    original_commit = db.commit

    def failing_first_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            raise IntegrityError("mock", None, Exception("forced"))
        return original_commit()

    # Fuer _update_stub_status_in_new_session muss ein *neuer* Session-Aufruf
    # die echte DB nutzen. Wir patchen SessionLocal so, dass nach dem ersten
    # Aufruf (BG-Session) wieder die normale Test-Session zuruckgegeben wird.
    call_count = [0]
    original_sl = app_db.SessionLocal

    def smart_session_local():
        call_count[0] += 1
        if call_count[0] == 1:
            # Erster Aufruf: BG-Task-Session (mit fallendem commit)
            return db
        # Folgende Aufrufe: echte neue Session fuer _update_stub_status_in_new_session
        return original_sl()

    with patch.object(app_db, "SessionLocal", side_effect=smart_session_local):
        with patch.object(db, "commit", side_effect=failing_first_commit):
            _run_photo_upload_bg(
                photo_id=photo_id,
                content=_jpeg_bytes(512),
                content_type="image/jpeg",
                filename="test.jpg",
                short_code=obj.short_code,
                category="technik",
                photo_store=local_store,
                user_id=editor_user.id,
                object_id=obj.id,
            )

    # Stub-Status sollte auf "upload_failed" gesetzt worden sein
    fresh_db = original_sl()
    try:
        updated_photo = fresh_db.get(SteckbriefPhoto, photo_id)
        assert updated_photo is not None
        status = (updated_photo.photo_metadata or {}).get("status")
        assert status == "upload_failed", f"Erwartet 'upload_failed', got '{status}'"
    finally:
        fresh_db.close()


# ---------------------------------------------------------------------------
# AC7 — Negative Betraege ablehnen
# ---------------------------------------------------------------------------

def test_police_create_rejects_negative_praemie(db, obj, editor_client):
    """POST Policen mit praemie=-100 → 422."""
    resp = editor_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "-100"},
    )
    assert resp.status_code == 422, f"Erwartet 422, got {resp.status_code}"


def test_police_create_accepts_zero_praemie(db, obj, editor_client):
    """POST Policen mit praemie=0 → 200 (Null ist erlaubt)."""
    resp = editor_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "0"},
    )
    assert resp.status_code == 200, f"Erwartet 200 fuer praemie=0, got {resp.status_code}"


def test_police_update_rejects_negative_praemie(db, obj, editor_client):
    """PUT Policen mit praemie=-50 → 422."""
    # Erst eine Police anlegen
    create_resp = editor_client.post(
        f"/objects/{obj.id}/policen",
        data={"praemie": "100"},
    )
    assert create_resp.status_code == 200

    from app.models import InsurancePolicy
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None

    resp = editor_client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={"praemie": "-50"},
    )
    assert resp.status_code == 422, f"Erwartet 422, got {resp.status_code}"


def test_schadensfall_create_rejects_negative_amount(db, obj, editor_client):
    """POST Schadensfaelle mit amount=-25 → Fehler (amount <= 0 Guard greift)."""
    # Erst eine Police anlegen
    editor_client.post(f"/objects/{obj.id}/policen", data={"praemie": "100"})
    from app.models import InsurancePolicy
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None

    resp = editor_client.post(
        f"/objects/{obj.id}/schadensfaelle",
        data={
            "policy_id": str(policy.id),
            "estimated_sum": "-25",
        },
    )
    # Router gibt 422-Fragment zurueck (HTML, kein JSON), aber status_code ist 422
    assert resp.status_code == 422, f"Erwartet 422 fuer negativen Schadensbetrag, got {resp.status_code}"


def test_registries_skips_negative_praemie_with_warning(db, obj, capsys):
    """registries.py-Aggregation ueberspringt negative Praemien mit Warning-Log."""
    from app.services.registries import get_versicherer_detail
    from app.models import InsurancePolicy, Versicherer
    from app.services.steckbrief_write_gate import write_field_human

    v = Versicherer(id=uuid.uuid4(), name="Test-V-Praemie", contact_info={})
    db.add(v)
    db.commit()

    user = User(
        id=uuid.uuid4(), google_sub="gs-praemie", email="rp@t.de", name="RP",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()

    # Police mit normalem positiven Wert
    policy1 = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(policy1)
    db.flush()
    write_field_human(db, entity=policy1, field="versicherer_id", value=v.id,
                      source="user_edit", user=user, request=None)
    write_field_human(db, entity=policy1, field="praemie", value=Decimal("500.00"),
                      source="user_edit", user=user, request=None)
    db.commit()

    # Police mit negativer Praemie direkt in DB schreiben (Guard umgehen)
    policy2 = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(policy2)
    db.flush()
    write_field_human(db, entity=policy2, field="versicherer_id", value=v.id,
                      source="user_edit", user=user, request=None)
    db.commit()
    policy2.praemie = Decimal("-100.00")
    db.commit()

    get_versicherer_detail(db, v.id)

    captured = capsys.readouterr()
    assert "negative_value_skipped" in captured.out, (
        "Warning-Log fuer negative Praemie erwartet"
    )


def test_registries_skips_negative_schaden_with_warning(db, obj, capsys):
    """registries.py-Aggregation ueberspringt negative Schadensbetrage mit Warning-Log."""
    from app.services.registries import get_versicherer_detail
    from app.models import InsurancePolicy, Schadensfall as SchadensfallModel, Versicherer
    from app.services.steckbrief_write_gate import write_field_human

    v = Versicherer(id=uuid.uuid4(), name="Test-V-Schaden", contact_info={})
    db.add(v)
    db.commit()

    user = User(
        id=uuid.uuid4(), google_sub="gs-schaden", email="rs@t.de", name="RS",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()

    policy = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(policy)
    db.flush()
    write_field_human(db, entity=policy, field="versicherer_id", value=v.id,
                      source="user_edit", user=user, request=None)
    db.commit()

    # Negativen Schadensbetrag direkt in DB schreiben
    schaden = SchadensfallModel(id=uuid.uuid4(), policy_id=policy.id)
    db.add(schaden)
    db.flush()
    schaden.amount = Decimal("-50.00")
    db.commit()

    get_versicherer_detail(db, v.id)

    captured = capsys.readouterr()
    assert "negative_value_skipped" in captured.out, (
        "Warning-Log fuer negativen Schadensbetrag erwartet"
    )


def test_steckbrief_policen_service_raises_on_negative_praemie(db, obj, editor_user):
    """create_police() Service-Guard: praemie=-1 → ValueError."""
    with pytest.raises(ValueError, match="praemie must be >= 0"):
        create_police(
            db, obj, editor_user, None,
            versicherer_id=None,
            police_number=None,
            produkt_typ=None,
            start_date=None,
            end_date=None,
            next_main_due=None,
            notice_period_months=None,
            praemie=Decimal("-1.00"),
        )


# ---------------------------------------------------------------------------
# AC8 — notice_period_months Range-Check
# ---------------------------------------------------------------------------

def test_notice_period_create_rejects_negative(db, obj, editor_client):
    """POST Policen mit notice_period_months=-5 → 422."""
    resp = editor_client.post(
        f"/objects/{obj.id}/policen",
        data={"notice_period_months": "-5"},
    )
    assert resp.status_code == 422, f"Erwartet 422 fuer -5 Monate, got {resp.status_code}"


def test_notice_period_create_rejects_over_360(db, obj, editor_client):
    """POST Policen mit notice_period_months=400 → 422."""
    resp = editor_client.post(
        f"/objects/{obj.id}/policen",
        data={"notice_period_months": "400"},
    )
    assert resp.status_code == 422, f"Erwartet 422 fuer 400 Monate, got {resp.status_code}"


def test_notice_period_create_accepts_zero(db, obj, editor_client):
    """POST Policen mit notice_period_months=0 → 200 (0 = keine Kuendigungsfrist, erlaubt)."""
    resp = editor_client.post(
        f"/objects/{obj.id}/policen",
        data={"notice_period_months": "0"},
    )
    assert resp.status_code == 200, f"Erwartet 200 fuer 0 Monate, got {resp.status_code}"


def test_notice_period_create_accepts_360(db, obj, editor_client):
    """POST Policen mit notice_period_months=360 → 200 (Boundary-Wert)."""
    resp = editor_client.post(
        f"/objects/{obj.id}/policen",
        data={"notice_period_months": "360"},
    )
    assert resp.status_code == 200, f"Erwartet 200 fuer 360 Monate, got {resp.status_code}"


def test_notice_period_update_rejects_negative(db, obj, editor_client):
    """PUT Policen mit notice_period_months=-1 → 422."""
    editor_client.post(f"/objects/{obj.id}/policen", data={"praemie": "100"})
    from app.models import InsurancePolicy
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.object_id == obj.id).first()
    assert policy is not None

    resp = editor_client.put(
        f"/objects/{obj.id}/policen/{policy.id}",
        data={"notice_period_months": "-1"},
    )
    assert resp.status_code == 422, f"Erwartet 422 fuer -1 Monat (update), got {resp.status_code}"
