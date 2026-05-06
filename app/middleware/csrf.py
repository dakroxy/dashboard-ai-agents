"""CSRF-Schutz fuer alle non-GET/HEAD/OPTIONS-Requests.

Token-Storage: scope["session"]["csrf_token"] (gesetzt beim Login in auth.py).
Token-Transport (in dieser Reihenfolge geprueft):
  1. X-CSRF-Token-Header (HTMX: hx-headers in base.html, fetch()-Calls)
  2. _csrf-Form-Field aus dem Body (klassische <form method="post">,
     emittiert via Jinja-Helper csrf_input(request) - siehe templating.py)

Granularitaet: einmal pro Session (keine Per-Request-Rotation), Rotation
bei Login (auth.py).

Pure-ASGI-Klasse statt BaseHTTPMiddleware - vermeidet ExceptionGroup-Issue
in Starlette 1.0+ bei Early-Return ohne call_next.
"""
from __future__ import annotations

import logging
import re
import secrets
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({b"GET", b"HEAD", b"OPTIONS"})
_FORM_CONTENT_TYPES: tuple[bytes, ...] = (
    b"application/x-www-form-urlencoded",
    b"multipart/form-data",
)
# 403-Reject-Header: kein Caching, keine Indexierung, kein Frame-Embed.
_REJECT_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Frame-Options": "DENY",
}
# Body-Cap fuer Form-Body-Fallback: 2 MB. Verhindert DoS via Multi-GB-Form-POST
# ohne X-CSRF-Token-Header. Echte Datei-Uploads laufen ueber HTMX/JS mit Header
# und treffen den schnellen Pfad; klassische <form>-Submits fuer Doc-Upload
# bleiben unter 2 MB-Cap (max 1 PDF in der Praxis).
_MAX_FORM_BODY_BYTES = 2 * 1024 * 1024


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


_MULTIPART_BOUNDARY_RE = re.compile(rb"boundary=([^;]+)", re.IGNORECASE)
# Matcht Content-Disposition, optional gefolgt von weiteren Header-Zeilen
# (z. B. Content-Type: text/plain) vor der Leerzeile zum Body. Browser
# emittieren bei file:-Inputs zusaetzliche Header; bei reinen Text-Feldern
# je nach Implementierung wechselnd.
_MULTIPART_CSRF_RE = re.compile(
    rb'Content-Disposition:\s*form-data;\s*name="_csrf"'
    rb"(?:\r\n[^\r\n]*)*"
    rb"\r\n\r\n([^\r\n]*)\r\n",
    re.IGNORECASE,
)


def _extract_csrf_from_body(body: bytes, content_type: bytes) -> str:
    """Liest das `_csrf`-Field aus einem Form-Body.

    Pure Bytes-Parsing - wir bauen bewusst KEIN Starlette-Request-Objekt,
    damit der downstream-Request-Stream unangetastet bleibt (sonst bricht
    z. B. ein nachgelagerter StreamingResponse mit 0-Byte-Body).
    """
    if content_type.startswith(b"application/x-www-form-urlencoded"):
        try:
            parsed = parse_qs(body.decode("utf-8", errors="replace"))
        except Exception:
            return ""
        values = parsed.get("_csrf") or []
        return values[0].strip() if values else ""
    if content_type.startswith(b"multipart/form-data"):
        m = _MULTIPART_CSRF_RE.search(body)
        if not m:
            return ""
        try:
            return m.group(1).decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
    return ""


class CSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").encode()
        session = scope.get("session")

        # Diagnose: SessionMiddleware fehlt komplett. Ohne sie wuerde JEDER
        # non-safe Request 403 ergeben - ohne Hinweis aufs Root-Cause.
        if session is None:
            if method not in _SAFE_METHODS:
                logger.error(
                    "CSRFMiddleware: scope['session'] missing - "
                    "SessionMiddleware not registered? path=%s method=%s",
                    scope.get("path", ""),
                    method.decode("ascii", errors="replace"),
                )
            await self.app(scope, receive, send)
            return

        # Lazy-Init des Session-Tokens NUR fuer authentifizierte Sessions
        # (user_id ist gesetzt). Damit:
        #  - Bestandssessions vor Story 5-1 bekommen beim naechsten Hit einen
        #    Token nachgesetzt, ohne Re-Login zu erzwingen.
        #  - Anonyme Visitors / Bots / Health-Probes erzeugen keine Session-
        #    Mutation -> kein Set-Cookie-Storm, keine Cookie-Inflation.
        if session.get("user_id") and not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)
        session_token: str = session.get("csrf_token", "")

        if method in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        header_token = ""
        content_type = b""
        content_length: int | None = None
        for name, value in scope.get("headers", []):
            lname = name.lower()
            if lname == b"x-csrf-token":
                # Strikte ASCII-Decodierung. Token ist secrets.token_urlsafe
                # (URL-safe Base64, ASCII-only). Non-ASCII = Tampering -> 403.
                try:
                    header_token = value.decode("ascii")
                except UnicodeDecodeError:
                    header_token = ""
            elif lname == b"content-type":
                content_type = value.lower()
            elif lname == b"content-length":
                try:
                    content_length = int(value.decode("ascii", errors="ignore"))
                except (ValueError, UnicodeDecodeError):
                    content_length = None

        # Schneller Pfad: Header passt -> durchwinken, Body nicht anfassen.
        if (
            session_token
            and header_token
            and secrets.compare_digest(session_token, header_token)
        ):
            await self.app(scope, receive, send)
            return

        # Fallback fuer klassische <form method="post">: _csrf-Form-Field aus
        # dem Body akzeptieren, wenn Content-Type ein Form-Type ist. JSON-/API-
        # Requests bleiben strikt header-only.
        is_form = any(content_type.startswith(t) for t in _FORM_CONTENT_TYPES)
        if session_token and is_form:
            # Body-Cap-Vorab-Check ueber Content-Length-Header.
            if content_length is not None and content_length > _MAX_FORM_BODY_BYTES:
                await self._reject(scope, send)
                return

            body = b""
            try:
                while True:
                    message = await receive()
                    if message["type"] != "http.request":
                        # http.disconnect mid-body -> sauberer Abbruch.
                        await self._reject(scope, send)
                        return
                    body += message.get("body", b"")
                    # Body-Cap waehrend des Lesens (kein Content-Length-Header
                    # oder gefaelschter Wert). Schliesst den DoS-Vektor auch
                    # gegen Chunked-Transfer.
                    if len(body) > _MAX_FORM_BODY_BYTES:
                        await self._reject(scope, send)
                        return
                    if not message.get("more_body", False):
                        break
            except Exception:
                # Defensives Catch: jeder Body-Read-Fehler -> 403, kein Crash.
                await self._reject(scope, send)
                return

            # Body manuell parsen - Starlette's Request.form() merkt sich
            # Parser-State auf dem Scope-Pfad und brach den nachgelagerten
            # StreamingResponse.
            form_token = _extract_csrf_from_body(body, content_type)

            if form_token and secrets.compare_digest(session_token, form_token):
                replayed = False

                async def replay() -> Message:
                    nonlocal replayed
                    if not replayed:
                        replayed = True
                        return {
                            "type": "http.request",
                            "body": body,
                            "more_body": False,
                        }
                    # Nach dem Body-Delivery auf das Original-receive
                    # durchreichen - sonst interpretiert
                    # `StreamingResponse.listen_for_disconnect` ein synthetisches
                    # http.disconnect als Client-Trennung und canceled die
                    # Streaming-Task -> 0-Byte-Body trotz Status 200.
                    return await receive()

                await self.app(scope, replay, send)
                return

        await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        response = JSONResponse(
            {"detail": "CSRF token missing or invalid"},
            status_code=403,
            headers=_REJECT_HEADERS,
        )
        await response(scope, _empty_receive, send)
