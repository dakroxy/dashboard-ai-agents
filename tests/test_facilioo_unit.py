"""Unit-Tests fuer den gehärteten Facilioo-Client (app/services/facilioo.py).

Story 4.2 — Tasks 6.2–6.11:
- 5xx-Backoff (2/5/15/30/60 s), Max-Retries → FaciliooError
- 429 mit Retry-After (Cap 120 s, Floor 1 s, Fallback 30 s), Rate-Attempt-Cap 3
- HTML-Error-Body via strip_html_error
- Rate-Gate seriell / Skip / ETV-Smoke
"""
from __future__ import annotations

import asyncio
import types as stdlib_types
import time as stdlib_time

import httpx
import pytest

from app.services import facilioo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(handler) -> httpx.AsyncClient:
    """AsyncClient mit Mock-Transport (kein echtes Netz, kein Token-Check)."""
    return httpx.AsyncClient(
        base_url="https://api.facilioo.de",
        transport=httpx.MockTransport(handler),
    )


def _seq_handler(*responses: httpx.Response):
    """Liefert Responses der Reihe nach; letzten wiederholen wenn erschöpft."""
    calls = [0]
    items = list(responses)

    def handler(request):
        idx = min(calls[0], len(items) - 1)
        calls[0] += 1
        return items[idx]

    return handler


def _resp(status: int, *, json=None, text: str = "", headers: dict | None = None) -> httpx.Response:
    if json is not None:
        return httpx.Response(status, json=json, headers=headers or {})
    return httpx.Response(status, text=text, headers=headers or {})


@pytest.fixture(autouse=True)
def _reset_rate_state(monkeypatch):
    """Setzt den Rate-Gate-Zustand vor jedem Test auf Null-Stand."""
    monkeypatch.setattr(facilioo, "_last_request_time", 0.0)


# ---------------------------------------------------------------------------
# Task 6.2: 5xx-Backoff-Sequenz (2/5/15/30/60 s)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_5xx_retry_consumes_full_backoff_sequence(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    call_count = [0]

    def handler(request):
        call_count[0] += 1
        if call_count[0] <= 5:
            return _resp(503)
        return _resp(200, json={"ok": True})

    async with _mock_client(handler) as client:
        result = await facilioo._api_get(client, "/test", rate_gate=False)

    assert result == {"ok": True}
    assert sleeps == [2, 5, 15, 30, 60]


# ---------------------------------------------------------------------------
# Task 6.3: 5xx Max-Retries → FaciliooError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_5xx_max_retries_then_raises(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    call_count = [0]

    def handler(request):
        call_count[0] += 1
        return _resp(503, text="Service Unavailable")

    async with _mock_client(handler) as client:
        with pytest.raises(facilioo.FaciliooError) as exc_info:
            await facilioo._api_get(client, "/test", rate_gate=False)

    assert exc_info.value.status_code == 503
    # Initial-Call + 5 Retries = 6 Calls; volle Backoff-Sequenz konsumiert.
    # Schuetzt gegen Regression auf _MAX_RETRIES_5XX = 0.
    assert call_count[0] == 6, f"Erwartet 6 Calls (Initial + 5 Retries), gesehen: {call_count[0]}"
    assert sleeps == [2, 5, 15, 30, 60]


# ---------------------------------------------------------------------------
# Task 6.4: 429 respektiert Retry-After-Header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_respects_retry_after_header(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    handler = _seq_handler(
        _resp(429, text="Too Many", headers={"Retry-After": "7"}),
        _resp(200, json={"ok": True}),
    )

    async with _mock_client(handler) as client:
        result = await facilioo._api_get(client, "/test", rate_gate=False)

    assert result == {"ok": True}
    assert 7 in sleeps


# ---------------------------------------------------------------------------
# Task 6.5: 429 Retry-After cap bei 120 s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_caps_retry_after_at_120(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    handler = _seq_handler(
        _resp(429, text="Too Many", headers={"Retry-After": "600"}),
        _resp(200, json={"ok": True}),
    )

    async with _mock_client(handler) as client:
        result = await facilioo._api_get(client, "/test", rate_gate=False)

    assert result == {"ok": True}
    assert 120 in sleeps
    assert 600 not in sleeps


# ---------------------------------------------------------------------------
# Task 6.6: 429 ohne Retry-After → Fallback 30 s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_fallback_30s_without_header(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    handler = _seq_handler(
        _resp(429, text="Too Many"),
        _resp(200, json={"ok": True}),
    )

    async with _mock_client(handler) as client:
        result = await facilioo._api_get(client, "/test", rate_gate=False)

    assert result == {"ok": True}
    assert 30 in sleeps


# ---------------------------------------------------------------------------
# Task 6.7: 429 Rate-Attempt-Cap bei 3 Retries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_caps_retries_at_3(monkeypatch):
    async def fake_sleep(s):
        pass

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    call_count = [0]

    def handler(request):
        call_count[0] += 1
        return _resp(429, text="Too Many", headers={"Retry-After": "1"})

    async with _mock_client(handler) as client:
        with pytest.raises(facilioo.FaciliooError) as exc_info:
            await facilioo._api_get(client, "/test", rate_gate=False)

    assert exc_info.value.status_code == 429
    assert "Rate-Limit nach 3 Retries" in str(exc_info.value)
    # Initial-Call + 3 Retries = 4 Calls; beim 4. Aufruf greift Cap (>= 3).
    # Schuetzt gegen Off-by-one-Regression beim >=-Vergleich.
    assert call_count[0] == 4, f"Erwartet 4 Calls (Initial + 3 Retries), gesehen: {call_count[0]}"


# ---------------------------------------------------------------------------
# Combined 5xx + 429-Storm: Counter laufen unabhaengig
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_combined_5xx_429_storm_keeps_counters_independent(monkeypatch):
    """5xx und 429 abwechselnd: beide Counter laufen unabhaengig hoch.

    Sequenz: 5xx, 429, 5xx, 429, 200 → 5 Calls, 4 Sleeps.
    Erwartete Sleeps:
      - 2x 5xx-Backoff (Indices 0, 1 → [2, 5])
      - 2x 429-Wait (Retry-After=1 → [1, 1])
    Reihenfolge: [2, 1, 5, 1] (5xx-Backoff → 429-Wait → 5xx-Backoff → 429-Wait).
    """
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    handler = _seq_handler(
        _resp(503),
        _resp(429, headers={"Retry-After": "1"}),
        _resp(503),
        _resp(429, headers={"Retry-After": "1"}),
        _resp(200, json={"ok": True}),
    )

    async with _mock_client(handler) as client:
        result = await facilioo._api_get(client, "/test", rate_gate=False)

    assert result == {"ok": True}
    assert sleeps == [2, 1, 5, 1]


# ---------------------------------------------------------------------------
# 204 No Content + leerer Body + Non-JSON-Body
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_204_no_content_returns_none():
    def handler(request):
        return httpx.Response(204)

    async with _mock_client(handler) as client:
        result = await facilioo._api_get(client, "/test", rate_gate=False)

    assert result is None


@pytest.mark.asyncio
async def test_empty_2xx_body_returns_none():
    def handler(request):
        return httpx.Response(200, content=b"")

    async with _mock_client(handler) as client:
        result = await facilioo._api_get(client, "/test", rate_gate=False)

    assert result is None


@pytest.mark.asyncio
async def test_non_json_2xx_body_raises_facilioo_error():
    """200er Status + Non-JSON-Body (z. B. Cloudflare-Maintenance-Seite mit 200)
    muss einen FaciliooError werfen, nicht ungewrappten JSONDecodeError."""
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    async with _mock_client(handler) as client:
        with pytest.raises(facilioo.FaciliooError) as exc_info:
            await facilioo._api_get(client, "/test", rate_gate=False)

    assert exc_info.value.status_code == 200
    assert "Non-JSON-Body" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Task 6.8: HTML-Error-Body via strip_html_error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_html_error_uses_strip_html_error(monkeypatch):
    async def fake_sleep(s):
        pass

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    def handler(request):
        return _resp(
            502,
            text="<html><body><p>nginx fehler upstream</p></body></html>",
        )

    async with _mock_client(handler) as client:
        with pytest.raises(facilioo.FaciliooError) as exc_info:
            await facilioo._api_get(client, "/test", rate_gate=False)

    msg = str(exc_info.value)
    assert "nginx fehler upstream" in msg
    assert "<html>" not in msg
    assert "<body>" not in msg


# ---------------------------------------------------------------------------
# Task 6.9: Rate-Gate seriell — Calls werden um _REQUEST_INTERVAL gebremst
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_gate_spaces_calls(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    # time.monotonic immer auf 1000.0 einfrieren → Gate berechnet deterministisch.
    fake_time = stdlib_types.SimpleNamespace(monotonic=lambda: 1000.0)
    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(facilioo, "time", fake_time)
    # _last_request_time = 0.0 bereits durch autouse-Fixture gesetzt.

    def handler(request):
        return _resp(200, json={})

    async with _mock_client(handler) as client:
        await facilioo._api_get(client, "/a", rate_gate=True)
        await facilioo._api_get(client, "/b", rate_gate=True)
        await facilioo._api_get(client, "/c", rate_gate=True)

    # Call 1: _last=0, now=1000 → wait = 1.0 - 1000 < 0 → kein Sleep.
    # Call 2: _last=1000, now=1000 → wait = 1.0 - 0 = 1.0 → sleep(1.0).
    # Call 3: _last=1000, now=1000 → wait = 1.0 - 0 = 1.0 → sleep(1.0).
    assert len(sleeps) == 2
    assert all(s >= facilioo._REQUEST_INTERVAL for s in sleeps)


# ---------------------------------------------------------------------------
# Task 6.10: rate_gate=False serialisiert nicht
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_gate_skip_does_not_serialize(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.services.facilioo.asyncio.sleep", fake_sleep)

    def handler(request):
        return _resp(200, json={})

    t0 = stdlib_time.monotonic()
    async with _mock_client(handler) as client:
        await asyncio.gather(*[
            facilioo._api_get(client, "/test", rate_gate=False)
            for _ in range(5)
        ])
    wall = stdlib_time.monotonic() - t0

    assert wall < 0.1
    assert not sleeps


# ---------------------------------------------------------------------------
# Task 6.11: ETV-Pfad ueberspringt Rate-Gate (Smoke)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_etv_paths_skip_rate_gate(monkeypatch):
    def _handler(request):
        return _resp(200, json={"items": [], "totalPages": 1})

    class _MockClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(_handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("app.services.facilioo.httpx.AsyncClient", _MockClient)
    monkeypatch.setattr(facilioo.settings, "facilioo_bearer_token", "fake-token")

    t0 = stdlib_time.monotonic()
    result = await facilioo.list_conferences()
    wall = stdlib_time.monotonic() - t0

    assert wall < 0.5
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Task 3.5: ETag-Support (_api_get)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_get_etag_header_added():
    """ETag-Parameter → If-None-Match-Header wird an den Server geschickt."""
    captured: dict = {}

    def handler(request):
        captured["if-none-match"] = request.headers.get("if-none-match")
        return _resp(200, json=[])

    client = _mock_client(handler)
    async with client:
        await facilioo._api_get(client, "/api/test", etag="tag-abc", rate_gate=False)

    assert captured.get("if-none-match") == "tag-abc"


@pytest.mark.asyncio
async def test_api_get_304_returns_none():
    """Status 304 ohne return_response → None (kein raise)."""
    def handler(request):
        return httpx.Response(304)

    client = _mock_client(handler)
    async with client:
        result = await facilioo._api_get(client, "/api/test", rate_gate=False)

    assert result is None


@pytest.mark.asyncio
async def test_api_get_return_response_includes_headers():
    """return_response=True → (body, headers_dict, status_code)-Tuple."""
    def handler(request):
        return _resp(200, json={"items": []}, headers={"ETag": "tag-xyz"})

    client = _mock_client(handler)
    async with client:
        result = await facilioo._api_get(
            client, "/api/test", return_response=True, rate_gate=False
        )

    body, hdrs, status = result
    assert status == 200
    assert body == {"items": []}
    assert hdrs.get("etag") or hdrs.get("ETag")
