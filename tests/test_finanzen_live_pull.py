"""Story 1.5 — Unit-Tests fuer get_bank_balance() + Sparkline-Service.

Mockt httpx.AsyncClient via httpx.MockTransport. Pro Test wird der
Modul-Lock im Rate-Gate nicht zurueckgesetzt — die Locks von Python-3.12
asyncio.Lock sind loop-agnostisch fuer unkontendierte acquire/release.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from app.models import FieldProvenance
from app.services.impower import get_bank_balance
from app.services.steckbrief import (
    build_sparkline_svg,
    reserve_history_for_sparkline,
)


# ---------------------------------------------------------------------------
# Helper: monkeypatch httpx.AsyncClient mit MockTransport
# ---------------------------------------------------------------------------

def _patched_async_client(handler, captured_kwargs: dict | None = None):
    """Liefert eine httpx.AsyncClient-Subklasse, die einen MockTransport
    injiziert und die Init-Kwargs (timeout, headers, base_url) optional
    in `captured_kwargs` kopiert.
    """
    transport = httpx.MockTransport(handler)

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            if captured_kwargs is not None:
                captured_kwargs.update(kwargs)
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    return _PatchedClient


# ---------------------------------------------------------------------------
# get_bank_balance — happy + error paths
# ---------------------------------------------------------------------------

async def test_get_bank_balance_returns_decimal(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"accountBalance": "12345.67"})

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    result = await get_bank_balance("12345")
    assert result is not None
    assert result["balance"] == Decimal("12345.67")
    assert result["currency"] == "EUR"
    assert result["fetched_at"].tzinfo is not None


async def test_get_bank_balance_currentBalance_field_also_supported(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"currentBalance": "9999.00"})

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    result = await get_bank_balance("12345")
    assert result is not None
    assert result["balance"] == Decimal("9999.00")


async def test_get_bank_balance_zero_balance_is_valid(monkeypatch):
    """Ein Saldo von 0 ist ein gueltiger Wert — nicht als 'fehlend'
    behandeln (sonst zerschiesst `or`-Chain den Null-Fall stumm)."""
    def handler(request):
        return httpx.Response(200, json={"accountBalance": "0"})

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    result = await get_bank_balance("12345")
    assert result is not None
    assert result["balance"] == Decimal("0")


async def test_get_bank_balance_timeout_returns_none(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    assert await get_bank_balance("12345") is None


async def test_get_bank_balance_503_returns_none(monkeypatch):
    def handler(request):
        return httpx.Response(503, text="Service Unavailable")

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    assert await get_bank_balance("12345") is None


async def test_get_bank_balance_4xx_returns_none(monkeypatch):
    def handler(request):
        return httpx.Response(404, text="Not Found")

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    assert await get_bank_balance("12345") is None


async def test_get_bank_balance_no_balance_field_returns_none(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"name": "Test Property"})

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    assert await get_bank_balance("12345") is None


async def test_get_bank_balance_non_dict_response_returns_none(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=["not", "a", "dict"])

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    assert await get_bank_balance("12345") is None


async def test_get_bank_balance_non_json_response_returns_none(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="<html>Gateway Error</html>")

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    assert await get_bank_balance("12345") is None


async def test_get_bank_balance_empty_property_id_returns_none():
    assert await get_bank_balance("") is None


async def test_get_bank_balance_8s_timeout_effective(monkeypatch):
    """Verifiziert den Bypass aus Task 1.3: get_bank_balance darf NICHT
    `_api_get` benutzen, sonst wuerde der per-call kwarg `timeout=120.0`
    den Client-Timeout ueberschreiben. Wir checken, dass der AsyncClient
    mit timeout=8.0 konstruiert wurde.
    """
    def handler(request):
        return httpx.Response(200, json={"accountBalance": "1.00"})

    captured: dict = {}
    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler, captured),
    )
    await get_bank_balance("12345")
    assert captured.get("timeout") == 8.0


async def test_get_bank_balance_uses_correct_path(monkeypatch):
    """Verifiziert, dass das URL-Path-Format /v2/properties/{id} verwendet wird."""
    seen_paths: list[str] = []

    def handler(request):
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"accountBalance": "1.00"})

    monkeypatch.setattr(
        "app.services.impower.httpx.AsyncClient",
        _patched_async_client(handler),
    )
    await get_bank_balance("HAM61")
    assert seen_paths == ["/v2/properties/HAM61"]


# ---------------------------------------------------------------------------
# reserve_history_for_sparkline (Task 6.3)
# ---------------------------------------------------------------------------

def _add_provenance(
    db,
    *,
    object_id,
    field_name,
    source,
    new_value="45000.00",
    days_ago=0,
    source_ref="ref-1",
):
    """Fuegt eine FieldProvenance-Row mit explizitem created_at hinzu.
    Manuelles created_at noetig, weil server_default=func.now() sonst
    alle Rows auf 'jetzt' setzt und Sortier-Tests nicht aussagekraeftig sind.
    """
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    row = FieldProvenance(
        id=uuid.uuid4(),
        entity_type="object",
        entity_id=object_id,
        field_name=field_name,
        source=source,
        source_ref=source_ref,
        value_snapshot={"old": None, "new": new_value},
        created_at=created,
    )
    db.add(row)
    return row


def test_reserve_history_two_points_returns_sorted_list(db, test_object):
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="40000", days_ago=20,
    )
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="45000", days_ago=5,
    )
    db.commit()

    points = reserve_history_for_sparkline(db, test_object.id)
    assert len(points) == 2
    # Chronologisch (alt -> neu)
    assert points[0][0] < points[1][0]
    assert points[0][1] == 40000.0
    assert points[1][1] == 45000.0


def test_reserve_history_empty_returns_empty_list(db, test_object):
    assert reserve_history_for_sparkline(db, test_object.id) == []


def test_reserve_history_decimal_as_string_in_snapshot(db, test_object):
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="45000.00", days_ago=10,
    )
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="50000.50", days_ago=5,
    )
    db.commit()
    points = reserve_history_for_sparkline(db, test_object.id)
    assert [v for _, v in points] == [45000.0, 50000.5]


def test_reserve_history_missing_new_key_is_skipped(db, test_object):
    bad = FieldProvenance(
        id=uuid.uuid4(),
        entity_type="object",
        entity_id=test_object.id,
        field_name="reserve_current",
        source="impower_mirror",
        source_ref="r1",
        value_snapshot={"old": "30000"},  # KEIN 'new'-Key
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.add(bad)
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="45000",
    )
    db.commit()
    points = reserve_history_for_sparkline(db, test_object.id)
    assert len(points) == 1
    assert points[0][1] == 45000.0


def test_reserve_history_only_impower_mirror_source(db, test_object):
    """User-Edits darf die Sparkline NICHT mitnehmen — sonst wuerde die Kurve
    sich bei jeder manuellen Korrektur veraendern."""
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="user_edit", new_value="999999",
    )
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="45000",
    )
    db.commit()
    points = reserve_history_for_sparkline(db, test_object.id)
    assert [v for _, v in points] == [45000.0]


def test_reserve_history_only_reserve_current_field(db, test_object):
    """last_known_balance-Provenance darf die Sparkline nicht beeinflussen."""
    _add_provenance(
        db, object_id=test_object.id, field_name="last_known_balance",
        source="impower_mirror", new_value="123",
    )
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="45000",
    )
    db.commit()
    points = reserve_history_for_sparkline(db, test_object.id)
    assert [v for _, v in points] == [45000.0]


def test_reserve_history_drops_rows_outside_window(db, test_object):
    """Werte aelter als 6 Monate (Default) duerfen nicht in der Liste landen."""
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="10000", days_ago=400,  # ~13 Monate
    )
    _add_provenance(
        db, object_id=test_object.id, field_name="reserve_current",
        source="impower_mirror", new_value="45000", days_ago=10,
    )
    db.commit()
    points = reserve_history_for_sparkline(db, test_object.id)
    assert [v for _, v in points] == [45000.0]


# ---------------------------------------------------------------------------
# build_sparkline_svg
# ---------------------------------------------------------------------------

def test_build_sparkline_svg_one_point_returns_none():
    pt = (datetime.now(timezone.utc), 42.0)
    assert build_sparkline_svg([pt]) is None


def test_build_sparkline_svg_empty_returns_none():
    assert build_sparkline_svg([]) is None


def test_build_sparkline_svg_two_points_returns_svg_string():
    now = datetime.now(timezone.utc)
    points = [(now, 100.0), (now + timedelta(days=1), 200.0)]
    svg = build_sparkline_svg(points)
    assert svg is not None
    assert svg.startswith("<svg")
    assert '<path d="M' in svg
    assert svg.endswith("</svg>")


def test_build_sparkline_svg_flat_line_for_equal_values():
    now = datetime.now(timezone.utc)
    points = [
        (now, 50.0),
        (now + timedelta(days=1), 50.0),
        (now + timedelta(days=2), 50.0),
    ]
    svg = build_sparkline_svg(points)
    assert svg is not None
    # Alle Y-Koordinaten muessen identisch sein (h/2 = 20.0).
    coords = re.findall(r"[ML](\d+\.?\d*),(\d+\.?\d*)", svg)
    assert len(coords) == 3
    ys = {c[1] for c in coords}
    assert ys == {"20.0"}
