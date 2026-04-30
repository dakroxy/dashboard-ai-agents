"""Facilioo Read-Client — einzige Boundary fuer alle Facilioo-API-Calls.

Pattern bewusst an `app/services/impower.py` angelehnt:
- httpx.AsyncClient (Factory _make_client, kein globales Singleton).
- 5xx + Transport-Errors retried mit Exponential-Backoff (2/5/15/30/60 s).
- 429 mit Retry-After-Parsing (Cap 120 s, Floor 1 s, Fallback 30 s).
- Rate-Gate (Default: 1 req/s) deaktivierbar per rate_gate=False.
  ETV-Pfad nutzt rate_gate=False (60+ parallele Calls), Mirror-Pfad (Story 4.3)
  laesst den Default aktiv.
- ETag-Support: optionaler `etag`-Parameter + `return_response=True` fuer
  den Mirror-Pfad. Facilioo unterstuetzt aktuell kein ETag/304, aber der
  Code-Pfad ist vorbereitet (Spike 2026-04-30).
- HTML-Error-Bodies werden via _sync_common.strip_html_error bereinigt.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.config import settings
from app.services._sync_common import strip_html_error


_TIMEOUT = 30.0
_MAX_RETRIES_5XX = 5
_RETRY_DELAYS_5XX: tuple[int, ...] = (2, 5, 15, 30, 60)
_PAGE_SIZE = 100
# Safety-Cap fuer paginierte Endpunkte: bei Schema-Drift (kein totalPages,
# kein last-Flag, content immer voll) waere die Schleife sonst unbegrenzt.
# 500 Seiten * 100 Items = 50k Conferences — well above any realistic Pool.
_MAX_PAGES = 500

# Wird beim ersten Import aus settings gelesen (Prod-Override via Env).
_REQUEST_INTERVAL: float = settings.facilioo_rate_interval_seconds

# Facilioo-Tenant DBS, GET /api/attributes resolved name="Miteigentumsanteile".
# Werte liegen pro Unit unter /api/units/{uid}/attribute-values als
# {"attributeId": 1438, "value": "<MEA>"}. Robuster als /voting-groups/shares,
# das in Facilioo nicht durchgaengig gepflegt wird (Wert "0").
MEA_ATTRIBUTE_ID = 1438

_logger = logging.getLogger(__name__)

# Modul-weiter Rate-Gate-State (analog impower.py:43-44).
_rate_lock = asyncio.Lock()
_last_request_time: float = 0.0


class FaciliooError(Exception):
    def __init__(self, message: str, status_code: int = -1):
        super().__init__(message)
        self.status_code = status_code


def _parse_retry_after(value: str | None) -> int:
    """Parst Retry-After-Header (nur Integer-Sekunden). Floor 1, Cap 120, Fallback 30."""
    if value is None:
        return 30
    try:
        return max(1, min(120, int(value)))
    except (ValueError, TypeError):
        return 30


def _make_client() -> httpx.AsyncClient:
    token = (settings.facilioo_bearer_token or "").strip()
    if not token:
        # Frueh raus mit klarer Meldung — sonst wuerde httpx den Header
        # `"Bearer "` als LocalProtocolError ablehnen, der Retry-Pfad zieht
        # lange Backoff-Wartezeiten. Passiert in der Praxis, wenn das
        # Prod-.env die Variable nicht gesetzt hat.
        raise FaciliooError(
            "FACILIOO_BEARER_TOKEN ist nicht gesetzt. "
            "Bitte im Elestio-UI / .env nachtragen.",
            -1,
        )
    return httpx.AsyncClient(
        base_url=settings.facilioo_base_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout=_TIMEOUT,
    )


async def _rate_limit_gate() -> None:
    global _last_request_time
    async with _rate_lock:
        now = time.monotonic()
        wait = _REQUEST_INTERVAL - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


async def _api_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict | None = None,
    _attempt: int = 0,
    *,
    rate_gate: bool = True,
    _rate_attempt: int = 0,
    etag: str | None = None,
    return_response: bool = False,
) -> Any:
    """GET gegen Facilioo-API mit Retry-Backoff und optionalem ETag-Support.

    Mit `return_response=True` wird `(parsed_body, headers_dict, status_code)`
    zurueckgegeben statt nur `parsed_body`. Noetig fuer den Mirror-Pfad (ETag-
    Extraktion, 304-Detection). Default `False` bricht bestehende ETV-Caller nicht.

    Mit `etag` wird `If-None-Match: <etag>` als Request-Header gesetzt.
    Bei Status 304 und `return_response=True` liefert die Funktion
    `(None, headers_dict, 304)` zurueck (kein raise — 304 ist Erfolg im Mirror).
    """
    if rate_gate:
        await _rate_limit_gate()

    request_headers = {"If-None-Match": etag} if etag is not None else {}

    try:
        resp = await client.get(path, params=params, headers=request_headers or None)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        if _attempt < _MAX_RETRIES_5XX:
            await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
            return await _api_get(
                client, path, params, _attempt + 1,
                rate_gate=rate_gate, _rate_attempt=_rate_attempt,
                etag=etag, return_response=return_response,
            )
        raise FaciliooError(
            f"Verbindungsfehler zu Facilioo: {type(exc).__name__}: {exc}",
            -1,
        ) from exc

    if resp.status_code == 429:
        if _rate_attempt >= 3:
            raise FaciliooError("Rate-Limit nach 3 Retries weiterhin aktiv", 429)
        wait = _parse_retry_after(resp.headers.get("Retry-After"))
        await asyncio.sleep(wait)
        return await _api_get(
            client, path, params, _attempt,
            rate_gate=rate_gate, _rate_attempt=_rate_attempt + 1,
            etag=etag, return_response=return_response,
        )

    # 304 Not Modified — kein Fehler, Success-Pfad fuer den Mirror.
    if resp.status_code == 304:
        if return_response:
            return (None, dict(resp.headers), 304)
        return None

    if 500 <= resp.status_code < 600 and _attempt < _MAX_RETRIES_5XX:
        await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
        return await _api_get(
            client, path, params, _attempt + 1,
            rate_gate=rate_gate, _rate_attempt=_rate_attempt,
            etag=etag, return_response=return_response,
        )

    if resp.status_code >= 400:
        if resp.text.strip().startswith("<"):
            msg = strip_html_error(resp.text, limit=300) or f"HTTP {resp.status_code} (HTML-Body)"
        else:
            msg = resp.text.strip()[:300]
        raise FaciliooError(msg, resp.status_code)

    # 204 No Content oder leerer 2xx-Body — Caller bekommt None statt
    # ungewrappter JSONDecodeError. Analog impower.py:521-523.
    if resp.status_code == 204 or not resp.content:
        if return_response:
            return (None, dict(resp.headers), resp.status_code)
        return None
    try:
        body = resp.json()
    except ValueError as exc:
        # ValueError ist Superklasse von json.JSONDecodeError.
        raise FaciliooError(
            f"Non-JSON-Body von Facilioo (Status {resp.status_code})",
            resp.status_code,
        ) from exc
    if return_response:
        return (body, dict(resp.headers), resp.status_code)
    return body


async def _get_all_paged(
    client: httpx.AsyncClient,
    path: str,
    params: dict | None = None,
    *,
    rate_gate: bool = True,
) -> list[Any]:
    """Lädt alle Seiten eines paginierten Facilioo-Endpunkts.

    Facilioo paginiert **1-indexed** (`pageNumber >= 1`). Antwort-Container ist
    `{"items": [...], "totalPages": int, "pageNumber": int, ...}`.
    """
    if params is None:
        params = {}
    params = {**params, "pageSize": _PAGE_SIZE}
    all_items: list[Any] = []
    page = 1

    while True:
        data = await _api_get(
            client, path, {**params, "pageNumber": page}, rate_gate=rate_gate
        )

        if isinstance(data, list):
            all_items.extend(data)
            if len(data) < _PAGE_SIZE:
                break
        elif isinstance(data, dict):
            content = data.get("items") or data.get("content") or []
            all_items.extend(content)
            total_pages = data.get("totalPages")
            last_flag = data.get("last")
            if last_flag is True:
                break
            if total_pages is not None and page >= int(total_pages):
                break
            if not content:
                break
        else:
            break

        if page >= _MAX_PAGES:
            _logger.warning(
                "Facilioo-Pagination Safety-Cap erreicht (page=%d, path=%s) — "
                "Antwort liefert weder totalPages noch last-Flag, breche ab.",
                page,
                path,
            )
            break
        page += 1

    return all_items


# ---------------------------------------------------------------------------
# Public Read-Methoden — alle GETs auf api.facilioo.de
# ETV-Pfad: rate_gate=False (60+ parallele Calls, Performance-kritisch).
# Mirror-Pfad (Story 4.3): rate_gate=True (Default).
# ---------------------------------------------------------------------------

async def list_conferences() -> list[dict]:
    """Alle Conferences (paginated). Felder u. a. id, title, date, state,
    propertyId."""
    async with _make_client() as client:
        return await _get_all_paged(client, "/api/conferences", rate_gate=False)


async def list_conferences_with_properties() -> list[dict]:
    """Wie ``list_conferences`` plus pro Conference WEG-Kuerzel und WEG-Name.

    Hintergrund: Der Conference-Listing-Endpoint liefert nur ``title``/``date``,
    keinen WEG-Bezug. Bei generischen Titeln ("Eigentuemerversammlung 2026")
    weiss der User im Dropdown nicht, welche WEG gemeint ist. Wir laden deshalb
    pro Conference ``/conferences/{id}/property`` parallel nach und reichern
    jedes Item um ``_property_number`` (z. B. "PLS22") und ``_property_name``
    an. Bei ~30 Conferences kostet das eine Welle parallel: ~1 s.
    """
    async with _make_client() as client:
        conferences = await _get_all_paged(client, "/api/conferences", rate_gate=False)
        prop_tasks = [
            _api_get(client, f"/api/conferences/{c['id']}/property", rate_gate=False)
            for c in conferences
            if c.get("id") is not None
        ]
        properties = await asyncio.gather(*prop_tasks, return_exceptions=True)

    prop_iter = iter(properties)
    failed = 0
    for c in conferences:
        if c.get("id") is None:
            continue
        prop = next(prop_iter, None)
        if isinstance(prop, dict):
            c["_property_number"] = prop.get("number")
            c["_property_name"] = prop.get("name")
        else:
            c["_property_number"] = None
            c["_property_name"] = None
            if isinstance(prop, BaseException):
                failed += 1
    if failed:
        # Aggregiertes Warning (kein Per-Item-Log) — bei ~30 Conferences sonst
        # zu laut. User sieht im Dropdown "ohne WEG-Kuerzel"; Ops sieht hier
        # ob ein Endpunkt gerade flackert.
        _logger.warning(
            "Facilioo /conferences/{id}/property: %d von %d Lookups fehlgeschlagen.",
            failed,
            len(prop_tasks),
        )
    return conferences


async def get_conference(conf_id: int | str) -> dict:
    async with _make_client() as client:
        return await _api_get(client, f"/api/conferences/{conf_id}", rate_gate=False)


async def get_conference_property(conf_id: int | str) -> dict:
    async with _make_client() as client:
        return await _api_get(
            client, f"/api/conferences/{conf_id}/property", rate_gate=False
        )


async def list_voting_group_shares(conf_id: int | str) -> list[dict]:
    """Liste von ``{votingGroupId, shares}`` (MEA pro Stimmgruppe).

    Paginated: Facilioo liefert max. 10 Eintraege pro Seite. ``_get_all_paged``
    laeuft bis ``totalPages`` durch (wichtig bei WEGs mit > 10 Voting-Groups).
    """
    async with _make_client() as client:
        return await _get_all_paged(
            client,
            f"/api/conferences/{conf_id}/voting-groups/shares",
            rate_gate=False,
        )


async def get_voting_group(vg_id: int | str) -> dict:
    """Einzel-Voting-Group mit ``units[]`` und ``parties[]``."""
    async with _make_client() as client:
        return await _api_get(client, f"/api/voting-groups/{vg_id}", rate_gate=False)


async def list_mandates(conf_id: int | str) -> list[dict]:
    """Vollmacht-Liste: ``{propertyOwnerId, representativeId}`` (paginated)."""
    async with _make_client() as client:
        return await _get_all_paged(
            client,
            f"/api/conferences/{conf_id}/mandates",
            rate_gate=False,
        )


async def list_unit_attribute_values(unit_id: int | str) -> list[dict]:
    """Alle Attribute-Werte einer Unit (paginated).

    Eintrag-Form: ``{attributeId, value, attribute: {name, ...}, ...}``.
    Filter auf ``attributeId == MEA_ATTRIBUTE_ID`` liefert die MEA als String.
    """
    async with _make_client() as client:
        return await _get_all_paged(
            client,
            f"/api/units/{unit_id}/attribute-values",
            rate_gate=False,
        )


# ---------------------------------------------------------------------------
# Aggregator fuer einen kompletten ETV-Unterschriftenlisten-Druck
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Mirror-Helpers (Story 4.3)
# ---------------------------------------------------------------------------

def derive_status(process: dict) -> str:
    """Leitet den lokalen Status-String aus dem Facilioo-Prozess-DTO ab.

    Regelreihenfolge (Spike 2026-04-30):
      deleted != null  →  "deleted"   (gewinnt vor isFinished)
      isFinished=true  →  "finished"
      sonst            →  "open"
    """
    if process.get("deleted") is not None:
        return "deleted"
    if process.get("isFinished"):
        return "finished"
    return "open"


def parse_facilioo_datetime(value: str | None) -> datetime | None:
    """Parst einen Facilioo-ISO-8601-Zeitstempel als UTC-aware datetime.

    Facilioo liefert Zeitstempel ggf. ohne Offset (naiv). Naiver Input
    wird als UTC interpretiert. Bei Parse-Fehler: None.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Modul-level Properties-Cache (5-min TTL) fuer den Mirror-Pfad.
# Reduziert API-Calls von ~1440/Tag auf ~288/Tag.
_properties_cache: list[dict] | None = None
_properties_cache_ts: float = 0.0
_PROPERTIES_CACHE_TTL: float = 5 * 60.0


async def _get_properties_cached(client: httpx.AsyncClient) -> list[dict]:
    """Gibt gecachte Facilioo-Property-Liste zurueck (TTL 5 min)."""
    global _properties_cache, _properties_cache_ts
    now = time.monotonic()
    if _properties_cache is not None and (now - _properties_cache_ts) < _PROPERTIES_CACHE_TTL:
        return _properties_cache
    props = await _get_all_paged(client, "/api/properties")
    _properties_cache = props
    _properties_cache_ts = time.monotonic()
    return props


def _reset_properties_cache_for_tests() -> None:
    """Test-Hook: Properties-Cache leeren."""
    global _properties_cache, _properties_cache_ts
    _properties_cache = None
    _properties_cache_ts = 0.0


async def list_properties() -> list[dict]:
    """Alle Facilioo-Properties (gecacht, Rate-Gate aktiv)."""
    async with _make_client() as client:
        return await _get_properties_cached(client)


async def list_processes(facilioo_property_id: int | str) -> list[dict]:
    """Alle Prozesse (= Tickets) einer Facilioo-Property (Rate-Gate aktiv)."""
    async with _make_client() as client:
        return await _get_all_paged(
            client, f"/api/properties/{facilioo_property_id}/processes"
        )


async def fetch_conference_signature_payload(conf_id: int | str) -> dict:
    """Lädt alles, was die ETV-Unterschriftenliste pro Conference braucht.

    Phase 1: Conference, Property, Voting-Group-Shares, Mandates parallel.
        ``shares`` und ``mandates`` werden paginiert geladen — Facilioo liefert
        nur 10 Eintraege pro Seite, frueher gingen Zeilen bei >10 VGs verloren.
    Phase 2: Voting-Group-Details parallel (eine Welle pro vg_share).
    Phase 3: MEA pro Unit aus ``/api/units/{uid}/attribute-values`` parallel.
        Robuster als ``/voting-groups/shares`` — wird in Facilioo manchmal nicht
        gepflegt (Wert "0"), die Unit-Eigenschaften aber schon.

    Rückgabe-Form::

        {
          "conference": {...},
          "property": {...},
          "voting_groups": [
            {"voting_group": {...units, parties}, "shares": "...",
             "mea_decimal": Decimal | None},
            ...
          ],
          "mandates": [...],
        }
    """
    async with _make_client() as client:
        conf_task = _api_get(client, f"/api/conferences/{conf_id}", rate_gate=False)
        prop_task = _api_get(
            client, f"/api/conferences/{conf_id}/property", rate_gate=False
        )
        shares_task = _get_all_paged(
            client,
            f"/api/conferences/{conf_id}/voting-groups/shares",
            rate_gate=False,
        )
        mandates_task = _get_all_paged(
            client,
            f"/api/conferences/{conf_id}/mandates",
            rate_gate=False,
        )

        conference, property_, shares, mandates = await asyncio.gather(
            conf_task, prop_task, shares_task, mandates_task
        )

        # Phase 2: alle Voting-Groups parallel
        vg_tasks = [
            _api_get(client, f"/api/voting-groups/{s['votingGroupId']}", rate_gate=False)
            for s in shares
            if s.get("votingGroupId") is not None
        ]
        vg_details = await asyncio.gather(*vg_tasks) if vg_tasks else []

        voting_groups: list[dict] = []
        vg_index = 0
        for s in shares:
            if s.get("votingGroupId") is None:
                continue
            voting_groups.append({
                "voting_group": vg_details[vg_index],
                "shares": s.get("shares", ""),
            })
            vg_index += 1

        # Phase 3: MEA pro Unit (parallel, einmal pro unique Unit-ID).
        unit_ids = list({
            u.get("id")
            for vg in voting_groups
            for u in (vg["voting_group"].get("units") or [])
            if u.get("id") is not None
        })
        if unit_ids:
            attr_tasks = [
                _get_all_paged(
                    client,
                    f"/api/units/{uid}/attribute-values",
                    rate_gate=False,
                )
                for uid in unit_ids
            ]
            attr_lists = await asyncio.gather(*attr_tasks)
        else:
            attr_lists = []

    attr_by_unit: dict = dict(zip(unit_ids, attr_lists))
    for entry in voting_groups:
        total = Decimal("0")
        seen = False
        for u in (entry["voting_group"].get("units") or []):
            uid = u.get("id")
            if uid is None:
                continue
            for av in attr_by_unit.get(uid, []):
                if av.get("attributeId") != MEA_ATTRIBUTE_ID:
                    continue
                raw = av.get("value")
                if raw in (None, ""):
                    continue
                try:
                    parsed = Decimal(str(raw))
                except (InvalidOperation, ValueError):
                    _logger.warning(
                        "MEA-Wert nicht parsbar (unitId=%s, value=%r) — ignoriert.",
                        uid,
                        raw,
                    )
                    continue
                # Decimal akzeptiert "NaN"/"Infinity"/"-Infinity"/"sNaN" als valide
                # Konstruktoren — ohne is_finite()-Guard wuerde NaN-Vergiftung in
                # die Summe propagieren und das PDF "NaN" / "Infinity" zeigen.
                if not parsed.is_finite():
                    _logger.warning(
                        "MEA-Wert nicht endlich (unitId=%s, value=%r) — ignoriert.",
                        uid,
                        raw,
                    )
                    continue
                total += parsed
                seen = True
                # Nur die erste valide MEA-Row pro Unit zaehlt — schuetzt vor
                # Doppel-Aufaddieren bei (hypothetisch) mehreren attributeId-1438-
                # Eintraegen pro Unit.
                break
        entry["mea_decimal"] = total if seen else None

    return {
        "conference": conference,
        "property": property_,
        "voting_groups": voting_groups,
        "mandates": mandates,
    }
