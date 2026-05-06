"""Impower API Client — Read- und Write-Pfad (M2/M3).

Implementiert paginiertes Laden von Properties, OWNER-Vertraegen, Kontakten
und unit-contract-mandates sowie Property- und Contact-Matching (M2).
Schreibpfad: Bank-Account sichern, Direct-Debit-Mandat und Unit-Contract-Mandate
anlegen (M3).

Rate-Limit: 500 req/min → 0.12 s Mindestabstand zwischen Requests.
"""
from __future__ import annotations

import asyncio
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from schwifty import IBAN as SchwiftyIBAN

from app.config import settings

_PAGE_SIZE = 100
_REQUEST_DELAY = 0.12
# Impower-Gateway antwortet auf /v2/properties empirisch mit ~60 s Latenz —
# Timeout muss deutlich darueber liegen, sonst faengt der Nginx davor an,
# 502 zu liefern und unser eigener Timeout reisst parallel die Verbindung ab.
_TIMEOUT = 120.0
# Eigener kurzer Timeout fuer den Live-Pull-Saldo (Story 1.5). Render-Pfad
# darf nicht 120 s blockieren — 8 s ist das Worst-Case-Fenster aus AC6
# (P95 < 2 s, einzelner Ausreisser bis 8 s ist akzeptabel).
_LIVE_BALANCE_TIMEOUT = 8.0
# Impower-Gateway drosselt sporadisch mit 503 (Instant-Response, Backend
# kriegt nichts davon). Mehrere Versuche mit Exponential-Backoff.
_MAX_RETRIES_5XX = 5
_RETRY_DELAYS_5XX: tuple[int, ...] = (2, 5, 15, 30, 60)

# Module-level rate-limiting state
_rate_lock = asyncio.Lock()
_last_request_time: float = 0.0


def _sanitize_error(resp: httpx.Response) -> str:
    """Extrahiert kompakte Info aus einer Fehler-Response, ohne rohe HTML-Seiten
    durchzureichen."""
    text = resp.text.strip()
    if text.startswith("<"):
        return (
            f"HTTP {resp.status_code} — Impower-Gateway hat HTML statt JSON "
            f"geliefert (meist Upstream-Timeout oder Gateway-Stoerung)."
        )
    return text[:300]


async def _rate_limit_gate() -> None:
    global _last_request_time
    async with _rate_lock:
        now = time.monotonic()
        wait = _REQUEST_DELAY - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(min(wait, 7.5))
        _last_request_time = time.monotonic()


async def _api_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict | None = None,
    _attempt: int = 0,
) -> Any:
    """GET mit Rate-Limiting, Retry bei 429 und 5xx."""
    await _rate_limit_gate()

    try:
        resp = await client.get(path, params=params, timeout=_TIMEOUT)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        if _attempt < _MAX_RETRIES_5XX:
            await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
            return await _api_get(client, path, params, _attempt + 1)
        return {
            "_error": -1,
            "_msg": f"Verbindungsfehler zu Impower: {type(exc).__name__}: {exc}",
        }

    if resp.status_code == 429:
        await asyncio.sleep(30)
        return await _api_get(client, path, params, _attempt)

    if 500 <= resp.status_code < 600 and _attempt < _MAX_RETRIES_5XX:
        await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
        return await _api_get(client, path, params, _attempt + 1)

    if resp.status_code >= 400:
        return {"_error": resp.status_code, "_msg": _sanitize_error(resp)}

    return resp.json()


def _is_error(data: Any) -> bool:
    return isinstance(data, dict) and "_error" in data


async def _get_all_paged(client: httpx.AsyncClient, path: str, params: dict | None = None) -> list[Any]:
    """Lädt alle Seiten eines Spring-Data-paginierten Endpunkts."""
    if params is None:
        params = {}
    params = {**params, "size": _PAGE_SIZE}
    all_items: list[Any] = []
    page = 0

    while True:
        data = await _api_get(client, path, {**params, "page": page})

        if _is_error(data):
            if page == 0:
                raise ImpowerError(data.get("_msg", "API-Fehler"), data.get("_error", -1))
            break

        if isinstance(data, list):
            all_items.extend(data)
            if len(data) < _PAGE_SIZE:
                break
        elif isinstance(data, dict):
            content = data.get("content", [])
            all_items.extend(content)
            if data.get("last", True) or not content:
                break
        else:
            break

        page += 1

    return all_items


class ImpowerError(Exception):
    def __init__(self, message: str, status_code: int = -1):
        super().__init__(message)
        self.status_code = status_code


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.impower_base_url,
        headers={
            "Authorization": f"Bearer {settings.impower_bearer_token}",
            "Accept": "application/json",
        },
    )


# ---------------------------------------------------------------------------
# Daten laden
# ---------------------------------------------------------------------------

async def load_properties() -> list[dict]:
    """Alle Properties laden. Gibt Liste von Property-Objekten zurück."""
    async with _make_client() as client:
        return await _get_all_paged(client, "/v2/properties")


async def load_owner_contracts() -> list[dict]:
    """Alle OWNER-Verträge laden."""
    async with _make_client() as client:
        return await _get_all_paged(client, "/v2/contracts", {"type": "OWNER"})


async def load_all_contacts() -> list[dict]:
    """Alle Kontakte laden (inkl. bankAccounts)."""
    async with _make_client() as client:
        contacts = await _get_all_paged(client, "/v2/contacts")
        if not contacts:
            return contacts
        # bankAccounts kommen nicht immer im Listen-Response mit
        if contacts and "bankAccounts" not in contacts[0]:
            enriched = []
            for c in contacts:
                detail = await _api_get(client, f"/v2/contacts/{c['id']}")
                enriched.append(detail if not _is_error(detail) else c)
            return enriched
        return contacts


async def load_unit_contract_mandates(property_id: int | str) -> list[dict]:
    """unit-contract-mandate für eine Property laden."""
    async with _make_client() as client:
        data = await _api_get(
            client,
            "/services/pmp-accounting/api/v1/unit-contract-mandate",
            {"propertyId": property_id},
        )
    if _is_error(data):
        raise ImpowerError(data.get("_msg", "API-Fehler"), data.get("_error", -1))
    return data if isinstance(data, list) else []


async def health_check() -> dict:
    """Kurze Connectivity-Prüfung: Lädt erste Seite Properties."""
    async with _make_client() as client:
        data = await _api_get(client, "/v2/properties", {"size": 1, "page": 0})
    if _is_error(data):
        return {"ok": False, "error": data.get("_msg"), "status_code": data.get("_error")}
    return {"ok": True}


# ---------------------------------------------------------------------------
# Matching-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _contact_display_name(contact: dict) -> str:
    company = contact.get("companyName", "")
    first = contact.get("firstName", "")
    last = contact.get("lastName", "")
    if company:
        person = f"{first} {last}".strip()
        return f"{company} ({person})" if person else company
    if first or last:
        return f"{first} {last}".strip()
    return contact.get("recipientName", "") or contact.get("name", "") or f"#{contact.get('id', '?')}"


@dataclass
class PropertyMatch:
    property_id: Any
    property_hr_id: str
    property_name: str
    score: float  # 1.0 = exact, <1 = fuzzy


@dataclass
class ContactMatch:
    contact_id: Any
    display_name: str
    score: float
    open_contract_ids: list[Any] = field(default_factory=list)
    has_bank_account: bool = False


@dataclass
class MatchResult:
    property_match: PropertyMatch | None
    contact_match: ContactMatch | None
    ambiguous: bool
    notes: list[str] = field(default_factory=list)


def match_property(
    properties: list[dict],
    weg_kuerzel: str | None,
    weg_name: str | None,
    weg_adresse: str | None,
    threshold: float = 0.72,
) -> tuple[PropertyMatch | None, bool]:
    """Findet die beste Property anhand WEG-Kürzel oder Name/Adresse.

    Gibt (match, ambiguous) zurück. ambiguous=True wenn mehrere ähnlich gute Treffer.
    """
    candidates: list[PropertyMatch] = []

    for p in properties:
        hr_id: str = p.get("propertyHrId", "") or ""
        name: str = p.get("name", "") or ""
        address: str = p.get("address", "") or p.get("street", "") or ""

        # Exact match auf Kürzel hat Vorrang
        if weg_kuerzel and hr_id.strip().lower() == weg_kuerzel.strip().lower():
            return PropertyMatch(
                property_id=p["id"],
                property_hr_id=hr_id,
                property_name=name,
                score=1.0,
            ), False

        # Fuzzy: Name und Adresse kombiniert
        score = 0.0
        if weg_name:
            score = max(score, _similarity(name, weg_name))
        if weg_adresse and address:
            score = max(score, _similarity(address, weg_adresse))
        if weg_name and weg_adresse:
            combined_p = f"{name} {address}"
            combined_q = f"{weg_name} {weg_adresse}"
            score = max(score, _similarity(combined_p, combined_q))

        if score >= threshold:
            candidates.append(PropertyMatch(
                property_id=p["id"],
                property_hr_id=hr_id,
                property_name=name,
                score=score,
            ))

    if not candidates:
        return None, False

    candidates.sort(key=lambda c: c.score, reverse=True)
    best = candidates[0]
    # Ambig wenn zweiter Treffer innerhalb 5% des besten
    ambiguous = len(candidates) > 1 and (best.score - candidates[1].score) < 0.05
    return best, ambiguous


def match_contact_in_property(
    contracts: list[dict],
    contacts_by_id: dict[Any, dict],
    property_id: Any,
    owner_name: str,
    booked_contract_ids: set[Any],
    threshold: float = 0.72,
) -> tuple[ContactMatch | None, bool]:
    """Findet Kontakt innerhalb einer Property per Namens-Fuzzy.

    Sucht nur in OWNER-Verträgen der gewählten Property.
    Gibt alle offenen (nicht BOOKED) OWNER-Vertraege des Kontakts zurück.
    """
    # Contracts dieser Property
    prop_contracts = [c for c in contracts if c.get("propertyId") == property_id]

    # Kontakte mit Score
    contact_scores: dict[Any, tuple[float, dict]] = {}
    for contract in prop_contracts:
        for ref in contract.get("contacts", []):
            cid = ref.get("id")
            if cid is None or cid in contact_scores:
                continue
            contact = contacts_by_id.get(cid)
            if contact is None:
                continue
            display = _contact_display_name(contact)
            score = _similarity(display, owner_name)
            if score >= threshold:
                contact_scores[cid] = (score, contact)

    if not contact_scores:
        return None, False

    sorted_contacts = sorted(contact_scores.items(), key=lambda x: x[1][0], reverse=True)
    best_id, (best_score, best_contact) = sorted_contacts[0]
    ambiguous = len(sorted_contacts) > 1 and (best_score - sorted_contacts[1][1][0]) < 0.05

    # Offene OWNER-Verträge dieses Kontakts in dieser Property
    open_contracts = [
        c["id"]
        for c in prop_contracts
        if c["id"] not in booked_contract_ids
        and any(ref.get("id") == best_id for ref in c.get("contacts", []))
    ]

    has_bank = bool(best_contact.get("bankAccounts"))

    return ContactMatch(
        contact_id=best_id,
        display_name=_contact_display_name(best_contact),
        score=best_score,
        open_contract_ids=open_contracts,
        has_bank_account=has_bank,
    ), ambiguous


async def run_full_match(extraction: dict) -> MatchResult:
    """Vollständiges Matching einer Extraktion gegen Impower.

    Lädt Properties, Contracts, Contacts und Mandate parallel (wo möglich),
    liefert PropertyMatch + ContactMatch + ambiguous-Flag zurück.
    """
    notes: list[str] = []

    # Parallele Ladung von Properties und Contracts
    properties_task = asyncio.create_task(load_properties())
    contracts_task = asyncio.create_task(load_owner_contracts())
    properties, contracts = await asyncio.gather(properties_task, contracts_task)

    weg_kuerzel = extraction.get("weg_kuerzel")
    weg_name = extraction.get("weg_name")
    weg_adresse = extraction.get("weg_adresse")
    owner_name = extraction.get("owner_name") or ""

    prop_match, prop_ambiguous = match_property(properties, weg_kuerzel, weg_name, weg_adresse)

    if prop_ambiguous:
        notes.append("Mehrere Properties ähnlich gut — Property-Match mehrdeutig.")

    if prop_match is None:
        return MatchResult(
            property_match=None,
            contact_match=None,
            ambiguous=False,
            notes=["Keine passende Property gefunden."],
        )

    # Mandate und Kontakte für diese Property laden
    mandates_task = asyncio.create_task(
        load_unit_contract_mandates(prop_match.property_id)
    )
    contacts_task = asyncio.create_task(load_all_contacts())
    mandates, all_contacts = await asyncio.gather(mandates_task, contacts_task)

    booked_ids: set[Any] = {
        m["unitContractId"] for m in mandates if m.get("state") == "BOOKED"
    }
    contacts_by_id = {c["id"]: c for c in all_contacts}

    if not owner_name:
        notes.append("Kein Eigentümer-Name — Contact-Matching übersprungen.")
        return MatchResult(
            property_match=prop_match,
            contact_match=None,
            ambiguous=prop_ambiguous,
            notes=notes,
        )

    contact_match, contact_ambiguous = match_contact_in_property(
        contracts, contacts_by_id, prop_match.property_id, owner_name, booked_ids
    )

    if contact_ambiguous:
        notes.append("Mehrere Kontakte ähnlich gut — Contact-Match mehrdeutig.")

    ambiguous = prop_ambiguous or contact_ambiguous

    if contact_match is None:
        notes.append("Kein passender Kontakt in dieser Property gefunden.")

    return MatchResult(
        property_match=prop_match,
        contact_match=contact_match,
        ambiguous=ambiguous,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Write-Pfad (M3)
# ---------------------------------------------------------------------------

async def _api_post(
    client: httpx.AsyncClient,
    path: str,
    payload: dict,
    _attempt: int = 0,
) -> Any:
    """POST mit Rate-Limiting, Retry bei 429 und 5xx.

    Achtung: POST ist nicht zwingend idempotent — wir retrien 5xx trotzdem,
    weil Impower 5xx-Responses teilweise zurueckgibt, OBWOHL das Backend
    garnicht erreicht wurde (Gateway-Timeout vor Upstream). In dem Fall ist
    Retry sicher. Falls sich zeigt, dass Doppel-Inserts entstehen, muss das
    5xx-Retry hier deaktiviert werden.
    """
    await _rate_limit_gate()

    try:
        resp = await client.post(path, json=payload, timeout=_TIMEOUT)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        if _attempt < _MAX_RETRIES_5XX:
            await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
            return await _api_post(client, path, payload, _attempt + 1)
        return {
            "_error": -1,
            "_msg": f"Verbindungsfehler zu Impower: {type(exc).__name__}: {exc}",
        }

    if resp.status_code == 429:
        await asyncio.sleep(30)
        return await _api_post(client, path, payload, _attempt)

    if 500 <= resp.status_code < 600 and _attempt < _MAX_RETRIES_5XX:
        await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
        return await _api_post(client, path, payload, _attempt + 1)

    if resp.status_code >= 400:
        return {"_error": resp.status_code, "_msg": _sanitize_error(resp)}

    return resp.json()


async def _api_put(
    client: httpx.AsyncClient,
    path: str,
    payload: Any,
    _attempt: int = 0,
) -> Any:
    """PUT mit Rate-Limiting, Retry bei 429 und 5xx.

    Payload ist meistens Dict, bei manchen Endpunkten (z. B. deactivate) ein List-Array —
    daher Typ `Any`.
    """
    await _rate_limit_gate()

    try:
        resp = await client.put(path, json=payload, timeout=_TIMEOUT)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        if _attempt < _MAX_RETRIES_5XX:
            await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
            return await _api_put(client, path, payload, _attempt + 1)
        return {
            "_error": -1,
            "_msg": f"Verbindungsfehler zu Impower: {type(exc).__name__}: {exc}",
        }

    if resp.status_code == 429:
        await asyncio.sleep(30)
        return await _api_put(client, path, payload, _attempt)

    if 500 <= resp.status_code < 600 and _attempt < _MAX_RETRIES_5XX:
        await asyncio.sleep(_RETRY_DELAYS_5XX[_attempt])
        return await _api_put(client, path, payload, _attempt + 1)

    if resp.status_code >= 400:
        return {"_error": resp.status_code, "_msg": _sanitize_error(resp)}

    # 204 No Content moeglich
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def _normalize_iban(iban: str) -> str:
    """Normalisiert eine IBAN auf reine ASCII-Alphanumerik (uppercase).

    Robust gegen Unicode-Whitespace und unsichtbare Zeichen (Zero-Width-Space u. a.),
    die Sonnet gelegentlich in Ausgaben einstreut und die schlichtes
    `.replace(" ", "")` NICHT entfernen wuerde. Das wuerde sonst zu "Invalid IBAN
    length"-Fehlern fuehren, obwohl sichtbar alles korrekt aussieht.
    """
    if not iban:
        return ""
    normalized = unicodedata.normalize("NFKC", iban)
    return "".join(c for c in normalized if c.isalnum()).upper()


def _derive_bic_from_iban(iban: str) -> str | None:
    """Leitet den BIC aus einer deutschen IBAN via Bundesbank-BLZ-Register ab.

    Gibt None zurueck, wenn die BLZ in der schwifty-Registry nicht bekannt ist
    (seltene Sub-BLZ oder falsch extrahierte IBAN). Der Aufrufer muss dann einen
    fachlichen Fehler werfen, damit der User im Chat korrigieren kann.
    """
    try:
        return SchwiftyIBAN(iban).bic
    except Exception:
        return None


# Server-generierte Felder, die beim PUT nicht mitgesendet werden sollten —
# Impower generiert/verwaltet sie selbst. Wenn wir sie mitsenden, riskieren wir
# Validation-Fehler oder Ueberschreiben von Meta-Daten.
_SERVER_MANAGED_FIELDS = (
    "created", "createdBy", "updated", "updatedBy", "domainId", "casaviSyncData",
)


def _strip_server_fields(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in _SERVER_MANAGED_FIELDS}


async def _get_contact_full(client: httpx.AsyncClient, contact_id: Any) -> dict:
    """Laedt den vollstaendigen Contact via Private-API (enthaelt bankAccounts[])."""
    data = await _api_get(
        client, f"/services/pmp-accounting/api/v1/contacts/{contact_id}"
    )
    if _is_error(data):
        raise ImpowerError(
            f"Contact laden fehlgeschlagen: {data.get('_msg')}",
            data.get("_error", -1),
        )
    return data


async def _load_property_mandates(client: httpx.AsyncClient, property_id: Any) -> list[dict]:
    """Listet Direct-Debit-Mandate einer Property (fuer Idempotenz-Check)."""
    data = await _api_get(
        client,
        "/services/pmp-accounting/api/v1/direct-debit-mandate",
        {"propertyId": property_id},
    )
    if _is_error(data):
        raise ImpowerError(
            f"Mandate laden fehlgeschlagen: {data.get('_msg')}",
            data.get("_error", -1),
        )
    return data if isinstance(data, list) else []


async def _ensure_bank_account(
    client: httpx.AsyncClient,
    contact_id: Any,
    iban: str,
    bic: str,
    holder_name: str,
) -> tuple[int, bool]:
    """Gibt (bankAccountId, created) zurueck.

    Es existiert kein dedizierter POST fuer Bank-Accounts — wir muessen den
    kompletten Contact via `PUT /services/pmp-accounting/api/v1/contacts/{id}`
    updaten, mit erweitertem `bankAccounts[]`-Array (Replace-Semantik).

    1. GET Contact → bestehende bankAccounts lesen.
    2. Wenn IBAN bereits vorhanden → existierende bankAccountId zurueck.
    3. Sonst: neues Item anhaengen, Server-Felder aus bestehenden Items strippen,
       PUT Contact → neue bankAccountId aus Response ziehen.
    """
    clean_iban = _normalize_iban(iban)
    try:
        SchwiftyIBAN(clean_iban)
    except Exception as exc:
        raise ImpowerError(
            f"IBAN '{clean_iban}' ist ungültig ({exc}). Bitte im Chat prüfen.",
            -1,
        ) from exc
    contact = await _get_contact_full(client, contact_id)

    existing_accounts = contact.get("bankAccounts") or []
    for ba in existing_accounts:
        if _normalize_iban(ba.get("iban", "")) == clean_iban:
            return ba["id"], False

    # Impower besteht auf einen gueltigen BIC — SEPA-Mandate enthalten ihn heute
    # aber oft nicht mehr, d. h. Claude extrahiert meist keinen. Wir leiten den
    # BIC aus der IBAN via Bundesbank-BLZ-Register ab; wenn auch das nichts liefert,
    # muss der User im Chat den BIC nachreichen.
    clean_bic = bic.upper().strip() if bic else ""
    if not clean_bic:
        derived = _derive_bic_from_iban(clean_iban)
        if derived:
            clean_bic = str(derived)
    if not clean_bic:
        raise ImpowerError(
            f"BIC fehlt und konnte aus der IBAN {clean_iban} nicht abgeleitet werden "
            "(BLZ unbekannt). Bitte BIC im Chat ergänzen oder IBAN prüfen.",
            -1,
        )
    new_account: dict[str, Any] = {
        "iban": clean_iban,
        "bic": clean_bic,
        "accountHolderName": holder_name,
    }
    updated_accounts = [_strip_server_fields(ba) for ba in existing_accounts]
    updated_accounts.append(new_account)

    updated_contact = _strip_server_fields(dict(contact))
    updated_contact["bankAccounts"] = updated_accounts

    result = await _api_put(
        client,
        f"/services/pmp-accounting/api/v1/contacts/{contact_id}",
        updated_contact,
    )
    if _is_error(result):
        raise ImpowerError(
            f"Bank-Account anlegen fehlgeschlagen: {result.get('_msg')}",
            result.get("_error", -1),
        )

    # Neue bankAccountId aus Response: IBAN-Match im zurueckgelieferten Array.
    returned_accounts = result.get("bankAccounts") or []
    for ba in returned_accounts:
        if _normalize_iban(ba.get("iban", "")) == clean_iban:
            return ba["id"], True

    raise ImpowerError(
        "Bank-Account angelegt, aber neue ID wurde in der PUT-Response nicht gefunden.",
        -1,
    )


async def _create_direct_debit_mandate(
    client: httpx.AsyncClient,
    property_id: Any,
    bank_account_id: int,
    signed_date: str,
    valid_from_date: str | None = None,
) -> int:
    """Legt ein Direct-Debit-Mandat an und gibt die Mandat-ID zurueck.

    `DirectDebitMandateCreationDto` hat kein `state`-Feld — Impower setzt den Status
    selbst (neu angelegte Mandate landen im BOOKED-Flow via unit-contract-mandate).
    """
    payload = {
        "propertyId": property_id,
        "bankAccountId": bank_account_id,
        "directDebitSignedOnDate": signed_date,
        "directDebitValidFromDate": valid_from_date or signed_date,
    }
    result = await _api_post(
        client,
        "/services/pmp-accounting/api/v1/direct-debit-mandate",
        payload,
    )
    if _is_error(result):
        raise ImpowerError(
            f"Direct-Debit-Mandat anlegen fehlgeschlagen: {result.get('_msg')}",
            result.get("_error", -1),
        )
    return result["id"]


async def _create_unit_contract_mandates(
    client: httpx.AsyncClient,
    unit_contract_ids: list[Any],
    direct_debit_mandate_id: int,
) -> list[int]:
    """Verknuepft mehrere OWNER-Vertraege mit einem Mandat.

    Der Endpunkt nimmt ein Array — kein Einzelobjekt in Schleife. Response ist
    ebenfalls ein Array mit IDs in der gleichen Reihenfolge.
    """
    if not unit_contract_ids:
        return []

    payload = [
        {
            "unitContractId": cid,
            "directDebitMandateId": direct_debit_mandate_id,
            "state": "BOOKED",
        }
        for cid in unit_contract_ids
    ]
    result = await _api_post(
        client,
        "/services/pmp-accounting/api/v1/unit-contract-mandate",
        payload,
    )
    if _is_error(result):
        raise ImpowerError(
            f"Unit-Contract-Mandate anlegen fehlgeschlagen: {result.get('_msg')}",
            result.get("_error", -1),
        )
    if not isinstance(result, list):
        raise ImpowerError(
            "Unit-Contract-Mandate-Response hat unerwartetes Format (kein Array).",
            -1,
        )
    return [item["id"] for item in result if isinstance(item, dict) and "id" in item]


@dataclass
class WriteResult:
    bank_account_id: int | None = None
    bank_account_created: bool = False
    direct_debit_mandate_id: int | None = None
    unit_contract_mandate_ids: list[int] = field(default_factory=list)
    already_present: bool = False
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "bank_account_id": self.bank_account_id,
            "bank_account_created": self.bank_account_created,
            "direct_debit_mandate_id": self.direct_debit_mandate_id,
            "unit_contract_mandate_ids": self.unit_contract_mandate_ids,
            "already_present": self.already_present,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Contact-Anlage (Paket 6)
# ---------------------------------------------------------------------------

def _build_contact_payload(
    type_: str,
    *,
    salutation: str | None = None,
    title: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    company_name: str | None = None,
    trade_register_number: str | None = None,
    vat_id: str | None = None,
    email: str | None = None,
    phone_business: str | None = None,
    phone_mobile: str | None = None,
    phone_private: str | None = None,
    addresses: list[dict] | None = None,
    notes: str | None = None,
) -> dict:
    """Baut einen ContactLegacyDto-konformen Payload fuer Impower.

    Felder, die leer sind, werden weggelassen — Impower verlangt ``type`` als
    einziges hartes Pflichtfeld. Addresses sind optional und werden nur
    mitgesendet, wenn mindestens eine gefuellt ist.
    """
    t = (type_ or "PERSON").strip().upper()
    if t not in {"PERSON", "COMPANY", "MANAGEMENT_COMPANY"}:
        t = "PERSON"

    payload: dict[str, Any] = {"type": t}

    def _set(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        payload[key] = value.strip() if isinstance(value, str) else value

    _set("salutation", salutation)
    _set("title", title)
    _set("firstName", first_name)
    _set("lastName", last_name)
    _set("companyName", company_name)
    _set("tradeRegisterNumber", trade_register_number)
    _set("vatId", vat_id)
    _set("email", email)
    _set("phoneBusiness", phone_business)
    _set("phoneMobile", phone_mobile)
    _set("phonePrivate", phone_private)

    clean_addresses = []
    for a in (addresses or []):
        if not a:
            continue
        has_content = any(
            (a.get(k) or "").strip()
            for k in ("street", "postalCode", "city")
        )
        if not has_content:
            continue
        clean_addresses.append(
            {k: v for k, v in a.items() if v not in (None, "")}
        )
    if clean_addresses:
        payload["addresses"] = clean_addresses

    if notes and notes.strip():
        payload["notes"] = notes.strip()

    return payload


async def check_contact_duplicates(payload: dict) -> list[dict]:
    """POST /contacts/duplicate — Duplikate finden bevor angelegt wird.

    Response ist eine Liste von Contact-Duplicate-Matches (meist mit
    ``contact`` + ``score`` oder aehnlich). Bei 404/Empty-Response leere Liste
    zurueckgeben.
    """
    async with _make_client() as client:
        result = await _api_post(
            client,
            "/services/pmp-accounting/api/v1/contacts/duplicate",
            payload,
        )
    if _is_error(result):
        raise ImpowerError(
            f"Duplicate-Check fehlgeschlagen: {result.get('_msg')}",
            result.get("_error", -1),
        )
    if isinstance(result, list):
        return result
    return []


async def create_contact(payload: dict) -> dict:
    """POST /contacts — legt einen Kontakt an.

    Gibt den neu angelegten Contact (inkl. ``id``) zurueck.
    """
    async with _make_client() as client:
        result = await _api_post(
            client,
            "/services/pmp-accounting/api/v1/contacts",
            payload,
        )
    if _is_error(result):
        raise ImpowerError(
            f"Contact-Anlage fehlgeschlagen: {result.get('_msg')}",
            result.get("_error", -1),
        )
    if not isinstance(result, dict) or "id" not in result:
        raise ImpowerError(
            "Contact-Anlage: unerwartete Response (keine ID zurueck).",
            -1,
        )
    return result


async def write_sepa_mandate(
    contact_id: Any,
    property_id: Any,
    open_contract_ids: list[Any],
    iban: str,
    bic: str,
    holder_name: str,
    signed_date: str,
) -> WriteResult:
    """Vollstaendiger Schreibpfad: Bank-Account sichern → Idempotenz-Check →
    Mandat anlegen → Verknuepfungen.

    Reihenfolge:
    1. `_ensure_bank_account` (GET+PUT Contact mit erweitertem bankAccounts-Array)
    2. Idempotenz-Check: Wenn fuer diese bankAccountId in dieser Property bereits
       ein BOOKED-Mandat existiert → Early-Return mit `already_present=True`.
    3. `_create_direct_debit_mandate` (ohne state-Feld).
    4. `_create_unit_contract_mandates` (Batch-Array, ein POST).
    """
    result = WriteResult()
    try:
        async with _make_client() as client:
            bank_account_id, created = await _ensure_bank_account(
                client, contact_id, iban, bic, holder_name
            )
            result.bank_account_id = bank_account_id
            result.bank_account_created = created

            existing_mandates = await _load_property_mandates(client, property_id)
            for m in existing_mandates:
                if (
                    m.get("bankAccountId") == bank_account_id
                    and m.get("state") == "BOOKED"
                ):
                    result.already_present = True
                    result.direct_debit_mandate_id = m.get("id")
                    return result

            result.direct_debit_mandate_id = await _create_direct_debit_mandate(
                client, property_id, bank_account_id, signed_date
            )

            result.unit_contract_mandate_ids = await _create_unit_contract_mandates(
                client, open_contract_ids, result.direct_debit_mandate_id
            )

    except ImpowerError as exc:
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# Live-Pull Bank-Saldo (Story 1.5)
# ---------------------------------------------------------------------------

async def get_bank_balance(property_id: str) -> dict | None:
    """Holt den aktuellen Bank-Saldo einer Impower-Property fuer den Live-Pull
    in der Finanzen-Sektion (Story 1.5).

    Eigener `httpx.AsyncClient(timeout=8.0)` statt `_make_client()` —
    `_api_get()` setzt auf jedem Call `timeout=_TIMEOUT (120 s)` per Kwarg
    und wuerde den Client-Default ueberschreiben. Render-Handler darf nicht
    2+ Minuten an einem Impower-Slowdown haengen (AC6: P95 < 2 s).

    Rueckgabe:
      * Erfolg: ``{"balance": Decimal, "currency": "EUR", "fetched_at": datetime}``
        — `fetched_at` ist UTC-aware, der Router konvertiert nach Europe/Berlin.
      * Fehler (Timeout, 4xx/5xx, kein Balance-Feld, parse-Fehler): ``None``.

    Kein Retry — der 8-s-Timeout ist das einzige Fangnetz, sonst sprengt der
    Live-Pull AC6.
    """
    if not property_id:
        return None

    try:
        async with httpx.AsyncClient(
            base_url=settings.impower_base_url,
            headers={
                "Authorization": f"Bearer {settings.impower_bearer_token}",
                "Accept": "application/json",
            },
            timeout=_LIVE_BALANCE_TIMEOUT,
        ) as client:
            await _rate_limit_gate()
            resp = await client.get(f"/v2/properties/{property_id}")
            resp.raise_for_status()
            data = resp.json()
    except (
        httpx.TimeoutException,
        httpx.TransportError,
        httpx.HTTPStatusError,
        ImpowerError,
        ValueError,  # json.JSONDecodeError extends ValueError — z. B. HTML-Antwort vom Gateway
    ):
        return None

    if not isinstance(data, dict):
        return None

    raw = data.get("accountBalance")
    if raw is None:
        raw = data.get("currentBalance")
    if raw is None:
        raw = data.get("bankBalance")
    if raw is None:
        return None

    try:
        balance = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None

    return {
        "balance": balance,
        "currency": "EUR",
        "fetched_at": datetime.now(ZoneInfo("UTC")),
    }
