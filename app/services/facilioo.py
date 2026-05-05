"""Facilioo Read-Client — einzige Boundary fuer alle Facilioo-API-Calls.

Pattern bewusst an `app/services/impower.py` angelehnt:
- httpx.AsyncClient (Factory _make_client, kein globales Singleton).
- 5xx + Transport-Errors retried mit Exponential-Backoff (2/5/15/30/60 s).
- 429 mit Retry-After-Parsing (Cap 120 s, Floor 1 s, Fallback 30 s).
- Rate-Gate (Default: 1 req/s) deaktivierbar per rate_gate=False.
  ETV-Pfad nutzt rate_gate=False (60+ parallele Calls), Mirror-Pfad (Story 4.3)
  laesst den Default aktiv.
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
# Maximale parallele Property-Lookups bei list_conferences_with_properties.
# 10 ist heuristisch: bei ~30 Conferences kein Unterschied; bei 200+ wird
# der Facilioo-Connection-Pool nicht geflutet. Wiederverwendbar fuer kuenftige Fanouts.
_PROPERTY_LOOKUP_CONCURRENCY = 10

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
) -> Any:
    """GET gegen Facilioo-API mit Retry-Backoff."""
    if rate_gate:
        await _rate_limit_gate()

    try:
        resp = await client.get(path, params=params)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        if _attempt < _MAX_RETRIES_5XX:
            await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
            return await _api_get(
                client, path, params, _attempt + 1,
                rate_gate=rate_gate, _rate_attempt=_rate_attempt,
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
        )

    if 500 <= resp.status_code < 600 and _attempt < _MAX_RETRIES_5XX:
        await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
        return await _api_get(
            client, path, params, _attempt + 1,
            rate_gate=rate_gate, _rate_attempt=_rate_attempt,
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
        return None
    try:
        return resp.json()
    except ValueError as exc:
        # ValueError ist Superklasse von json.JSONDecodeError.
        raise FaciliooError(
            f"Non-JSON-Body von Facilioo (Status {resp.status_code})",
            resp.status_code,
        ) from exc


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
            if not data:
                break
            if len(data) < _PAGE_SIZE:
                break
        elif isinstance(data, dict):
            content = data.get("items") or data.get("content") or []
            all_items.extend(content)
            total_pages = data.get("totalPages")
            last_flag = data.get("last")
            if last_flag is True:
                break
            try:
                total_pages_int = int(total_pages) if total_pages is not None else None
            except (TypeError, ValueError):
                total_pages_int = None
            if total_pages_int is not None and page >= total_pages_int:
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
        sem = asyncio.Semaphore(_PROPERTY_LOOKUP_CONCURRENCY)

        async def _bounded_get(c_id: int | str) -> dict | Exception:
            async with sem:
                return await _api_get(client, f"/api/conferences/{c_id}/property", rate_gate=False)

        prop_tasks = [
            _bounded_get(c["id"])
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

    Defensive: `isFinished` wird als String "true"/"True" akzeptiert
    (Facilioo-DTO-Drift). Andere truthy Strings (z. B. "false") gelten
    bewusst NICHT als finished.
    """
    if process.get("deleted") is not None:
        return "deleted"
    raw = process.get("isFinished")
    if raw is True or (isinstance(raw, str) and raw.strip().lower() == "true"):
        return "finished"
    return "open"


def parse_facilioo_datetime(value: str | None) -> datetime | None:
    """Parst einen Facilioo-ISO-8601-Zeitstempel als UTC-aware datetime.

    Facilioo liefert Zeitstempel ggf. ohne Offset (naiv). Naiver Input
    wird als UTC interpretiert. Bei Parse-Fehler: None.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    # 'Z' (Zulu) NUR am Ende zu '+00:00' machen — sonst ersetzt der naive
    # `.replace("Z", "+00:00")` ein 'Z' mitten im String und produziert
    # Garbage, das `fromisoformat` als ValueError ablehnt.
    cleaned = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(cleaned)
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
            vg = vg_details[vg_index]
            if not isinstance(vg, dict):
                print(f"[facilioo] phase2_vg_non_dict vg={vg!r}")
                vg_index += 1
                continue
            voting_groups.append({
                "voting_group": vg,
                "shares": s.get("shares", ""),
            })
            vg_index += 1

        # Phase 3: MEA pro Unit (parallel, einmal pro unique Unit-ID).
        unit_ids: list = []
        seen_ids: set = set()
        for vg in voting_groups:
            vg_inner = vg["voting_group"]
            if not isinstance(vg_inner, dict):
                continue
            for u in (vg_inner.get("units") or []):
                if u.get("id") is not None and u["id"] not in seen_ids:
                    unit_ids.append(u["id"])
                    seen_ids.add(u["id"])
        if unit_ids:
            attr_tasks = [
                _get_all_paged(
                    client,
                    f"/api/units/{uid}/attribute-values",
                    rate_gate=False,
                )
                for uid in unit_ids
            ]
            attr_lists = await asyncio.gather(*attr_tasks, return_exceptions=True)
        else:
            attr_lists = []

    attr_by_unit: dict = {}
    for uid, result in zip(unit_ids, attr_lists):
        if isinstance(result, Exception):
            print(f"[facilioo] phase3_unit_attr_failed unit_id={uid} error={result}")
            attr_by_unit[uid] = []
        else:
            attr_by_unit[uid] = result
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
