"""CSRF-Schutz fuer alle non-GET/HEAD/OPTIONS-Requests.

Token-Storage: scope["session"]["csrf_token"] (gesetzt beim Login in auth.py).
Token-Transport (in dieser Reihenfolge geprueft):
  1. X-CSRF-Token-Header (HTMX: hx-headers in base.html, fetch()-Calls)
  2. _csrf-Form-Field aus dem Body (klassische <form method="post">,
     emittiert via Jinja-Helper csrf_input(request) — siehe templating.py)

Granularitaet: einmal pro Session (keine Per-Request-Rotation).

Pure-ASGI-Klasse statt BaseHTTPMiddleware — vermeidet ExceptionGroup-Issue
in Starlette 1.0+ bei Early-Return ohne call_next.
"""
from __future__ import annotations

import re
import secrets
from typing import Any
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SAFE_METHODS = frozenset({b"GET", b"HEAD", b"OPTIONS"})
_FORM_CONTENT_TYPES: tuple[bytes, ...] = (
    b"application/x-www-form-urlencoded",
    b"multipart/form-data",
)
_REJECT_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "X-Frame-Options": "DENY",
}


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


_MULTIPART_BOUNDARY_RE = re.compile(rb"boundary=([^;]+)", re.IGNORECASE)
# Matched: <CRLF>Content-Disposition: form-data; name="_csrf"<CRLF><CRLF><value><CRLF>--
_MULTIPART_CSRF_RE = re.compile(
    rb'Content-Disposition:\s*form-data;\s*name="_csrf"\s*\r\n\r\n([^\r]*)\r\n',
    re.IGNORECASE,
)


def _extract_csrf_from_body(body: bytes, content_type: bytes) -> str:
    """Liest das `_csrf`-Field aus einem Form-Body.

    Pure Bytes-Parsing — wir bauen bewusst KEIN Starlette-Request-Objekt,
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

        # Lazy-Init des Session-Tokens — muss VOR dem Safe-Method-Bypass
        # laufen, damit der GET, der die Form rendert, das Token bereits
        # in der Session hat. Bestandssessions vor Story 5-1 haben keinen
        # `csrf_token`-Key (Token wird sonst nur im OAuth-Callback gesetzt).
        # Mutation auf scope["session"] propagiert via SessionMiddleware
        # automatisch in den Response-Cookie.
        session = scope.get("session")
        if session is not None and not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)
        session_token: str = (session or {}).get("csrf_token", "")

        method = scope.get("method", "GET").encode()
        if method in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        header_token = ""
        content_type = b""
        for name, value in scope.get("headers", []):
            lname = name.lower()
            if lname == b"x-csrf-token":
                header_token = value.decode("ascii", errors="replace")
            elif lname == b"content-type":
                content_type = value.lower()

        # Schneller Pfad: Header passt → durchwinken, Body nicht anfassen.
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
            body = b""
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    await self._reject(scope, send)
                    return
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break

            # Body manuell parsen — wir haben den downstream-Stream sonst
            # angefasst (Starlette's Request.form() merkt sich Parser-State
            # auf dem Scope-Pfad und brach den nachgelagerten StreamingResponse).
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
                    # durchreichen — sonst interpretiert
                    # `StreamingResponse.listen_for_disconnect` ein synthetisches
                    # http.disconnect als Client-Trennung und canceled die
                    # Streaming-Task → 0-Byte-Body trotz Status 200.
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
