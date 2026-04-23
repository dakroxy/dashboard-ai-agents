"""Story 1.8 — Unit-Tests fuer app/services/photo_store.py.

Reine Logik-Tests ohne TestClient oder DB. Tests fuer validate_photo,
LocalPhotoStore (ueber tmp_path-konfigurierbaren Root) und
create_photo_store-Backend-Auswahl.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use")
os.environ.setdefault("POSTGRES_PASSWORD", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("IMPOWER_BEARER_TOKEN", "")

from app.services.photo_store import (  # noqa: E402
    LARGE_UPLOAD_THRESHOLD,
    MAGIC_BYTES,
    MAX_SIZE_BYTES,
    LocalPhotoStore,
    PhotoValidationError,
    create_photo_store,
    validate_photo,
)


# ---------------------------------------------------------------------------
# Test-Fixtures — Magic-Bytes-Prefixes als konstantes Content
# ---------------------------------------------------------------------------

_JPEG_PREFIX = MAGIC_BYTES["image/jpeg"]
_PNG_PREFIX = MAGIC_BYTES["image/png"]


def _jpeg_bytes(size: int = 100) -> bytes:
    return _JPEG_PREFIX + b"\x00" * max(0, size - len(_JPEG_PREFIX))


def _png_bytes(size: int = 100) -> bytes:
    return _PNG_PREFIX + b"\x00" * max(0, size - len(_PNG_PREFIX))


# ---------------------------------------------------------------------------
# validate_photo
# ---------------------------------------------------------------------------

def test_validate_photo_accepts_jpeg():
    validate_photo(_jpeg_bytes(100), "image/jpeg")


def test_validate_photo_accepts_png():
    validate_photo(_png_bytes(100), "image/png")


def test_validate_photo_rejects_pdf_content_type():
    with pytest.raises(PhotoValidationError):
        validate_photo(b"%PDF-1.4\n...", "application/pdf")


def test_validate_photo_rejects_mismatched_magic_bytes():
    # Content-Type behauptet JPEG, aber die Bytes sind PNG
    with pytest.raises(PhotoValidationError):
        validate_photo(_png_bytes(100), "image/jpeg")


def test_validate_photo_rejects_oversized():
    oversized = _JPEG_PREFIX + b"\x00" * (MAX_SIZE_BYTES + 1 - len(_JPEG_PREFIX))
    with pytest.raises(PhotoValidationError):
        validate_photo(oversized, "image/jpeg")


def test_large_upload_threshold_value():
    assert LARGE_UPLOAD_THRESHOLD == 3 * 1024 * 1024


# ---------------------------------------------------------------------------
# LocalPhotoStore
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_local_store_upload_creates_file(tmp_path):
    store = LocalPhotoStore(root=tmp_path)
    ref = await store.upload(
        object_short_code="HAM61",
        category="technik",
        filename="heizung.jpg",
        content=_jpeg_bytes(200),
        content_type="image/jpeg",
    )
    assert ref.backend == "local"
    assert ref.local_path is not None
    assert os.path.exists(ref.local_path)
    assert ref.filename == "heizung.jpg"


@pytest.mark.asyncio
async def test_local_store_sha256_deduplication(tmp_path):
    store = LocalPhotoStore(root=tmp_path)
    content = _jpeg_bytes(500)
    ref1 = await store.upload(
        object_short_code="HAM61",
        category="technik",
        filename="a.jpg",
        content=content,
        content_type="image/jpeg",
    )
    ref2 = await store.upload(
        object_short_code="HAM61",
        category="technik",
        filename="b.jpg",  # anderer Dateiname, gleicher Content
        content=content,
        content_type="image/jpeg",
    )
    assert ref1.local_path == ref2.local_path


@pytest.mark.asyncio
async def test_local_store_delete_removes_file(tmp_path):
    store = LocalPhotoStore(root=tmp_path)
    ref = await store.upload(
        object_short_code="HAM61",
        category="technik",
        filename="heizung.jpg",
        content=_jpeg_bytes(200),
        content_type="image/jpeg",
    )
    assert os.path.exists(ref.local_path)
    await store.delete(ref)
    assert not os.path.exists(ref.local_path)


@pytest.mark.asyncio
async def test_local_store_delete_missing_file_no_error(tmp_path):
    store = LocalPhotoStore(root=tmp_path)
    from app.services.photo_store import PhotoRef
    ref = PhotoRef(
        backend="local",
        drive_item_id=None,
        local_path=str(tmp_path / "does-not-exist.jpg"),
        filename="gone.jpg",
    )
    # missing_ok=True → kein Fehler
    await store.delete(ref)


# ---------------------------------------------------------------------------
# create_photo_store — Backend-Auswahl
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_photo_store_returns_local_for_local_backend():
    fake_settings = SimpleNamespace(
        photo_backend="local",
        sharepoint_tenant_id="",
        sharepoint_client_id="",
        sharepoint_client_secret="",
        sharepoint_site_id="",
        sharepoint_drive_id="",
    )
    store = await create_photo_store(fake_settings)
    assert isinstance(store, LocalPhotoStore)


@pytest.mark.asyncio
async def test_create_photo_store_returns_local_when_sharepoint_credentials_missing():
    fake_settings = SimpleNamespace(
        photo_backend="sharepoint",
        sharepoint_tenant_id="",  # leer → Fallback
        sharepoint_client_id="",
        sharepoint_client_secret="",
        sharepoint_site_id="",
        sharepoint_drive_id="",
    )
    store = await create_photo_store(fake_settings)
    assert isinstance(store, LocalPhotoStore)


@pytest.mark.asyncio
async def test_create_photo_store_returns_local_when_msal_token_fails():
    from unittest.mock import MagicMock, patch

    fake_settings = SimpleNamespace(
        photo_backend="sharepoint",
        sharepoint_tenant_id="tenant-id",
        sharepoint_client_id="client-id",
        sharepoint_client_secret="secret",
        sharepoint_site_id="site-id",
        sharepoint_drive_id="drive-id",
    )
    with patch("app.services.photo_store.msal.ConfidentialClientApplication") as mock_cls:
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "Client authentication failed.",
        }
        mock_cls.return_value = mock_app
        store = await create_photo_store(fake_settings)
    assert isinstance(store, LocalPhotoStore)
