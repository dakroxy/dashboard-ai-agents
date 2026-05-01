"""CSRF-Schutz fuer alle non-GET/HEAD/OPTIONS-Requests.

Token-Storage: scope["session"]["csrf_token"] (gesetzt beim Login in auth.py).
Token-Transport: X-CSRF-Token-Header (HTMX: hx-headers in base.html).
Granularitaet: einmal pro Session (keine Per-Request-Rotation).

Pure-ASGI-Klasse statt BaseHTTPMiddleware — vermeidet ExceptionGroup-Issue
in Starlette 1.0+ bei Early-Return ohne call_next.
"""
from __future__ import annotations

import secrets
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_SAFE_METHODS = frozenset({b"GET", b"HEAD", b"OPTIONS"})


class CSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            method = scope.get("method", "GET").encode()
            if method not in _SAFE_METHODS:
                session: dict[str, Any] = scope.get("session", {})
                session_token: str = session.get("csrf_token", "")
                headers_list = scope.get("headers", [])
                header_token: str = ""
                for name, value in headers_list:
                    if name.lower() == b"x-csrf-token":
                        header_token = value.decode("latin-1", errors="replace")
                        break

                if (
                    not session_token
                    or not header_token
                    or not secrets.compare_digest(session_token, header_token)
                ):
                    response = JSONResponse(
                        {"detail": "CSRF token missing or invalid"},
                        status_code=403,
                    )
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)
