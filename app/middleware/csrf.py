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

import secrets
from typing import Any

from starlette.requests import Request
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


class CSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").encode()
        if method in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        session: dict[str, Any] = scope.get("session", {})
        session_token: str = session.get("csrf_token", "")

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

            async def cached_receive() -> Message:
                return {"type": "http.request", "body": body, "more_body": False}

            form_token = ""
            try:
                req = Request(scope, cached_receive)
                form = await req.form()
                raw = form.get("_csrf")
                if isinstance(raw, str):
                    form_token = raw.strip()
            except Exception:
                form_token = ""

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
                    return {"type": "http.disconnect"}

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
