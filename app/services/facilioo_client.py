"""Facilioo Read-Client (Workflow: ETV-Unterschriftenliste).

Schmaler Wrapper um die Facilioo-Public-API (Bearer-JWT). Anders als der
Impower-Client (rate-limited, write-fähig) ist dieser Client read-only und
nicht rate-limited — pro PDF-Druck laden wir 6 Endpunkte; das passt locker
unter jedes vernünftige Limit.

Pattern bewusst an `app/services/impower.py` angelehnt:
- httpx.AsyncClient mit Bearer-Header.
- 5xx + Transport-Errors retried mit Exponential-Backoff.
- 4xx wirft :class:`FaciliooError`.
- Errors werden über ``_sanitize_error`` kompakt gemacht (kein HTML-Dump).
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.config import settings


_TIMEOUT = 30.0
_MAX_RETRIES_5XX = 3
_RETRY_DELAYS_5XX: tuple[int, ...] = (2, 5, 15)
_PAGE_SIZE = 100
# Safety-Cap fuer paginierte Endpunkte: bei Schema-Drift (kein totalPages,
# kein last-Flag, content immer voll) waere die Schleife sonst unbegrenzt.
# 500 Seiten * 100 Items = 50k Conferences — well above any realistic Pool.
_MAX_PAGES = 500

# Facilioo-Tenant DBS, GET /api/attributes resolved name="Miteigentumsanteile".
# Werte liegen pro Unit unter /api/units/{uid}/attribute-values als
# {"attributeId": 1438, "value": "<MEA>"}. Robuster als /voting-groups/shares,
# das in Facilioo nicht durchgaengig gepflegt wird (Wert "0").
MEA_ATTRIBUTE_ID = 1438


_logger = logging.getLogger(__name__)


class FaciliooError(Exception):
    def __init__(self, message: str, status_code: int = -1):
        super().__init__(message)
        self.status_code = status_code


def _sanitize_error(resp: httpx.Response) -> str:
    text = resp.text.strip()
    if text.startswith("<"):
        return (
            f"HTTP {resp.status_code} — Facilioo-Gateway hat HTML statt JSON "
            f"geliefert (meist Upstream-Stoerung)."
        )
    return text[:300]


def _make_client() -> httpx.AsyncClient:
    token = (settings.facilioo_bearer_token or "").strip()
    if not token:
        # Frueh raus mit klarer Meldung — sonst wuerde httpx den Header
        # `"Bearer "` als LocalProtocolError ablehnen, der Retry-Pfad zieht
        # 22 s (2+5+15 s Backoff) Wartezeit pro Aufruf. Passiert in der Praxis,
        # wenn das Prod-.env die Variable nicht gesetzt hat.
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


async def _api_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict | None = None,
    _attempt: int = 0,
) -> Any:
    try:
        resp = await client.get(path, params=params)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        if _attempt < _MAX_RETRIES_5XX:
            await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
            return await _api_get(client, path, params, _attempt + 1)
        raise FaciliooError(
            f"Verbindungsfehler zu Facilioo: {type(exc).__name__}: {exc}",
            -1,
        ) from exc

    if 500 <= resp.status_code < 600 and _attempt < _MAX_RETRIES_5XX:
        await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
        return await _api_get(client, path, params, _attempt + 1)

    if resp.status_code >= 400:
        raise FaciliooError(_sanitize_error(resp), resp.status_code)

    return resp.json()


async def _get_all_paged(
    client: httpx.AsyncClient, path: str, params: dict | None = None
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
        data = await _api_get(client, path, {**params, "pageNumber": page})

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
# ---------------------------------------------------------------------------

async def list_conferences() -> list[dict]:
    """Alle Conferences (paginated). Felder u. a. id, title, date, state,
    propertyId."""
    async with _make_client() as client:
        return await _get_all_paged(client, "/api/conferences")


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
        conferences = await _get_all_paged(client, "/api/conferences")
        prop_tasks = [
            _api_get(client, f"/api/conferences/{c['id']}/property")
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
        return await _api_get(client, f"/api/conferences/{conf_id}")


async def get_conference_property(conf_id: int | str) -> dict:
    async with _make_client() as client:
        return await _api_get(client, f"/api/conferences/{conf_id}/property")


async def list_voting_group_shares(conf_id: int | str) -> list[dict]:
    """Liste von ``{votingGroupId, shares}`` (MEA pro Stimmgruppe).

    Paginated: Facilioo liefert max. 10 Eintraege pro Seite. ``_get_all_paged``
    laeuft bis ``totalPages`` durch (wichtig bei WEGs mit > 10 Voting-Groups).
    """
    async with _make_client() as client:
        return await _get_all_paged(
            client, f"/api/conferences/{conf_id}/voting-groups/shares"
        )


async def get_voting_group(vg_id: int | str) -> dict:
    """Einzel-Voting-Group mit ``units[]`` und ``parties[]``."""
    async with _make_client() as client:
        return await _api_get(client, f"/api/voting-groups/{vg_id}")


async def list_mandates(conf_id: int | str) -> list[dict]:
    """Vollmacht-Liste: ``{propertyOwnerId, representativeId}`` (paginated)."""
    async with _make_client() as client:
        return await _get_all_paged(
            client, f"/api/conferences/{conf_id}/mandates"
        )


async def list_unit_attribute_values(unit_id: int | str) -> list[dict]:
    """Alle Attribute-Werte einer Unit (paginated).

    Eintrag-Form: ``{attributeId, value, attribute: {name, ...}, ...}``.
    Filter auf ``attributeId == MEA_ATTRIBUTE_ID`` liefert die MEA als String.
    """
    async with _make_client() as client:
        return await _get_all_paged(
            client, f"/api/units/{unit_id}/attribute-values"
        )


# ---------------------------------------------------------------------------
# Aggregator fuer einen kompletten ETV-Unterschriftenlisten-Druck
# ---------------------------------------------------------------------------

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
        conf_task = _api_get(client, f"/api/conferences/{conf_id}")
        prop_task = _api_get(client, f"/api/conferences/{conf_id}/property")
        shares_task = _get_all_paged(
            client, f"/api/conferences/{conf_id}/voting-groups/shares"
        )
        mandates_task = _get_all_paged(
            client, f"/api/conferences/{conf_id}/mandates"
        )

        conference, property_, shares, mandates = await asyncio.gather(
            conf_task, prop_task, shares_task, mandates_task
        )

        # Phase 2: alle Voting-Groups parallel
        vg_tasks = [
            _api_get(client, f"/api/voting-groups/{s['votingGroupId']}")
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
                _get_all_paged(client, f"/api/units/{uid}/attribute-values")
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
