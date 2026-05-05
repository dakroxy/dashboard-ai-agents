"""Foto-Speicher-Backends fuer die Technik-Sektion (Story 1.8 / ID1).

Zwei Backends:
  * ``LocalPhotoStore``      — schreibt nach ``uploads/objects/{short_code}/{category}/``
  * ``SharePointPhotoStore`` — Graph-API-Simple-Upload bis 4 MB (unser Limit: 3 MB)

``create_photo_store(settings)`` waehlt anhand der Settings + verfuegbarer Credentials
das aktive Backend. SharePoint-Init testet einen MSAL-Client-Credentials-Flow;
schlaegt der fehl, fallt das System still auf ``LocalPhotoStore`` zurueck (der Caller
emittiert dann den ``sharepoint_init_failed``-Audit-Eintrag).

Die ``url()``-Methode aus architecture.md §ID1 ist bewusst NICHT im v1-Protocol
enthalten — temporaere Graph-API-Download-URLs werden in v1.1 nachgezogen
(Defer; siehe ``deferred-work.md``).
"""
from __future__ import annotations

import asyncio
import hashlib
import pathlib
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import quote

import httpx
import msal
from pydantic import BaseModel


ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png"})

MAGIC_BYTES: dict[str, bytes] = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}

MAX_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB Hard-Limit
LARGE_UPLOAD_THRESHOLD: int = 3 * 1024 * 1024  # >= 3 MB → BackgroundTask


class PhotoValidationError(Exception):
    """Validierung des Upload-Contents fehlgeschlagen (Typ/Magic/Groesse)."""


class PhotoStoreError(Exception):
    """Backend-seitiger Fehler (z.B. SharePoint-API liefert non-2xx)."""


class PhotoRef(BaseModel):
    """Referenz auf ein gespeichertes Foto.

    Genau eines von ``drive_item_id`` (SharePoint) oder ``local_path`` (Local)
    ist je Backend gesetzt — die Router-Logik nutzt ``backend`` zum Dispatch.
    """

    backend: Literal["sharepoint", "local"]
    drive_item_id: str | None
    local_path: str | None
    filename: str


def validate_photo(content: bytes, content_type: str) -> None:
    """Prueft Content-Type, Magic-Bytes und Groesse — wirft ``PhotoValidationError``.

    Reihenfolge ist relevant: Content-Type zuerst (billig), Magic-Bytes danach
    (verhindert PDF-mit-image/jpeg-Header), Groesse zuletzt (kostet nichts mehr).
    """
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise PhotoValidationError("Nur JPEG und PNG erlaubt.")

    expected_magic = MAGIC_BYTES[content_type]
    if not content.startswith(expected_magic):
        raise PhotoValidationError("Dateiinhalt passt nicht zum Typ.")

    if len(content) > MAX_SIZE_BYTES:
        raise PhotoValidationError("Datei zu groß. Maximum: 10 MB.")


@runtime_checkable
class PhotoStore(Protocol):
    """Backend-Protocol — beide Stores muessen ``backend_name`` als Klassen-/
    Instance-Attribut tragen, der Router nutzt das fuer ``SteckbriefPhoto.backend``."""

    backend_name: str

    async def upload(
        self,
        *,
        object_short_code: str,
        category: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> PhotoRef: ...

    async def delete(self, ref: PhotoRef) -> None: ...


class LocalPhotoStore:
    """Schreibt nach ``{root}/objects/{short_code}/{category}/{sha256}.{ext}``.

    SHA256-basierter Dateiname macht Uploads idempotent — gleicher Content
    landet im gleichen Pfad, keine Kollision. ``root`` ist parametriert, damit
    Tests mit ``tmp_path`` arbeiten koennen, ohne Seiteneffekte ins echte
    ``uploads/``-Verzeichnis.
    """

    backend_name: str = "local"

    def __init__(self, root: str | pathlib.Path = "uploads") -> None:
        self.root = pathlib.Path(root)

    async def upload(
        self,
        *,
        object_short_code: str,
        category: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> PhotoRef:
        sha256 = hashlib.sha256(content).hexdigest()
        ext = self._infer_extension(filename, content_type)
        path = self.root / "objects" / object_short_code / category / f"{sha256}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return PhotoRef(
            backend="local",
            drive_item_id=None,
            local_path=str(path),
            filename=filename,
        )

    async def delete(self, ref: PhotoRef) -> None:
        if ref.local_path:
            pathlib.Path(ref.local_path).unlink(missing_ok=True)

    @staticmethod
    def _infer_extension(filename: str, content_type: str) -> str:
        suffix = pathlib.Path(filename).suffix.lstrip(".").lower()
        if suffix in {"jpg", "jpeg", "png"}:
            return suffix
        if content_type == "image/png":
            return "png"
        return "jpg"


class SharePointPhotoStore:
    """Graph-API-Simple-Upload-Backend.

    Pfad-Annahme: ``drive_id`` zeigt auf die SharePoint-Library
    ``DBS/Objekte`` (per M365-Admin konfiguriert). Der vollstaendige
    Speicherort wird damit ``SharePoint/DBS/Objekte/{short_code}/{category}/{filename}``.
    Zeigt ``drive_id`` stattdessen auf die Site-Root, muss der Praefix
    ``DBS/Objekte/`` explizit in die URL — Entscheidung beim M365-Ticket
    klaeren und in ``.env.op`` kommentieren.
    """

    backend_name: str = "sharepoint"

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_id: str,
        drive_id: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.site_id = site_id
        self.drive_id = drive_id
        self._msal_app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        # Kein persistenter httpx.AsyncClient — wird per-Request erstellt,
        # damit BackgroundTask-asyncio.run() einen eigenen Event-Loop aufmachen
        # kann ohne Loop-Binding-Konflikt.

    def _get_token(self) -> str:
        result = self._msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            err = result.get("error_description") or result.get("error") or str(result)
            raise PhotoStoreError(f"SharePoint-Auth fehlgeschlagen: {err}")
        return result["access_token"]

    async def _get_token_async(self) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_token)

    async def upload(
        self,
        *,
        object_short_code: str,
        category: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> PhotoRef:
        token = await self._get_token_async()
        encoded = quote(filename, safe="")
        url = (
            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:"
            f"/{object_short_code}/{category}/{encoded}:/content"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.put(
                    url,
                    content=content,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": content_type,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise PhotoStoreError(
                    f"SharePoint-Upload: {exc.response.status_code} {exc.response.text}"
                ) from exc
            item = response.json()
        return PhotoRef(
            backend="sharepoint",
            drive_item_id=item.get("id"),
            local_path=None,
            filename=filename,
        )

    async def delete(self, ref: PhotoRef) -> None:
        if not ref.drive_item_id:
            return
        token = await self._get_token_async()
        url = (
            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}"
            f"/items/{ref.drive_item_id}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.delete(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 404:
                    return
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise PhotoStoreError(
                    f"SharePoint-Delete: {exc.response.status_code} {exc.response.text}"
                ) from exc


async def create_photo_store(settings) -> PhotoStore:
    """Backend-Auswahl: SharePoint wenn konfiguriert + Auth-Test gruen, sonst Local."""
    if settings.photo_backend != "sharepoint":
        return LocalPhotoStore()

    creds = (
        settings.sharepoint_tenant_id,
        settings.sharepoint_client_id,
        settings.sharepoint_client_secret,
        settings.sharepoint_site_id,
        settings.sharepoint_drive_id,
    )
    if not all(creds):
        return LocalPhotoStore()

    store = SharePointPhotoStore(
        tenant_id=settings.sharepoint_tenant_id,
        client_id=settings.sharepoint_client_id,
        client_secret=settings.sharepoint_client_secret,
        site_id=settings.sharepoint_site_id,
        drive_id=settings.sharepoint_drive_id,
    )
    try:
        store._get_token()
    except Exception:
        return LocalPhotoStore()
    return store
