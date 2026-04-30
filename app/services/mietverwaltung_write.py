"""Impower-Write-Pfad fuer die Mietverwaltungs-Anlage (M5 Paket 7).

Nimmt einen Case mit gemergtem + ueberschriebenem State und legt alle
Entitaeten in Impower in der richtigen Reihenfolge an:

    1. Contacts (Eigentuemer + n Mieter)         # POST /contacts
    2. Property (Minimal)                        # POST /properties
    3. PROPERTY_OWNER-Vertrag                    # POST /contracts (Array)
    4. Property-Detail-Update mit Buildings      # PUT  /properties
    5. Units                                     # POST /units (Array)
    6. TENANT-Vertraege                          # POST /contracts (Array)
    7. Exchange-Plan (Miet-Positionen)           # POST /exchange-plan
    8. Deposits (Kautionen)                      # POST /plan/manual/deposit

Kernprinzip ist Idempotenz: Alle bereits erfolgreich angelegten IDs werden
in ``case.impower_result`` festgehalten. Retrys ueberspringen jeden Schritt,
dessen Output-ID bereits vorhanden ist. So kann der User bei einem
Teil-Fehler einfach "Erneut ausfuehren" klicken, ohne dass bereits
geschriebene Daten dupliziert werden.

Der Flow laeuft als BackgroundTask mit eigener DB-Session — darum eine
eigene Funktion ``run_mietverwaltung_write(case_id)``, die den Case laedt,
schrittweise writet und Status + impower_result zurueckschreibt.

Fuer Fehlercase: der fehlschlagende Schritt wird in
``impower_result.errors`` vermerkt, der Case-Status wird auf ``partial``
(wenn mindestens ein Schritt durchgelaufen ist) oder ``error`` gesetzt.
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal
from app.models import Case
from app.services._time import today_local
from app.services.audit import audit
from app.services.impower import (
    ImpowerError,
    _api_post,
    _api_put,
    _build_contact_payload,
    _is_error,
    _make_client,
)

# ---------------------------------------------------------------------------
# Validierung vor dem Write
# ---------------------------------------------------------------------------

REQUIRED_PROPERTY_FIELDS = ("number", "street", "postal_code", "city")


@dataclass
class WritePreflight:
    ok: bool
    missing: list[str]


def preflight(case_state: dict[str, Any]) -> WritePreflight:
    """Prueft, ob ein Case die Mindestanforderungen fuer den Write erfuellt."""
    missing: list[str] = []
    prop = (case_state or {}).get("property") or {}
    for f in REQUIRED_PROPERTY_FIELDS:
        if not prop.get(f):
            missing.append(f"property.{f}")

    owner = (case_state or {}).get("owner") or {}
    if not (owner.get("last_name") or owner.get("company_name")):
        missing.append("owner.last_name|company_name")

    units = (case_state or {}).get("units") or []
    if not units:
        missing.append("units[] leer")

    return WritePreflight(ok=not missing, missing=missing)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _ensure_impower_result(case: Case) -> dict:
    """Liest oder initialisiert den ``impower_result``-Struct."""
    ir = dict(case.impower_result or {})
    ir.setdefault("contacts", {})
    ir["contacts"].setdefault("tenants", {})
    ir.setdefault("building_ids", [])
    ir.setdefault("unit_ids", {})
    ir.setdefault("tenant_contract_ids", {})
    ir.setdefault("exchange_plan_ids", {})
    ir.setdefault("deposit_ids", {})
    ir.setdefault("steps_completed", [])
    ir.setdefault("errors", [])
    return ir


def _log_step(ir: dict, step: str) -> None:
    if step not in ir["steps_completed"]:
        ir["steps_completed"].append(step)


def _log_error(ir: dict, step: str, message: str) -> None:
    ir["errors"].append(
        {
            "step": step,
            "message": message,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        }
    )


def _commit_state(case: Case, ir: dict) -> None:
    """Persistiert impower_result.

    Reassign allein reicht NICHT: `_ensure_impower_result` baut `ir` als flachen
    Shallow-Copy von `case.impower_result` (shared nested refs). Spaetere
    In-Place-Mutationen an `ir["contacts"]` etc. mutieren damit auch das
    bestehende `case.impower_result`-Dict. Beim zweiten Commit vergleicht
    SQLAlchemy das alte Attribut gegen `dict(ir)` und sieht sie als gleich an
    (Value-Equality ueber shared refs) → kein UPDATE. `flag_modified` erzwingt
    den dirty-Flag.
    """
    case.impower_result = dict(ir)
    flag_modified(case, "impower_result")


def _address_payload(
    street: str | None,
    postal_code: str | None,
    city: str | None,
    country: str | None = "DE",
    *,
    for_invoice: bool = True,
    for_mail: bool = True,
) -> dict | None:
    if not (street or postal_code or city):
        return None
    return {
        k: v
        for k, v in {
            "street": street,
            "postalCode": postal_code,
            "city": city,
            "country": country or "DE",
            "forInvoice": for_invoice,
            "forMail": for_mail,
        }.items()
        if v is not None
    }


def _display_name(block: dict | None) -> str:
    if not block:
        return "(Unbekannt)"
    if block.get("company_name"):
        return str(block["company_name"])
    fn = block.get("first_name") or ""
    ln = block.get("last_name") or ""
    return f"{fn} {ln}".strip() or "(Unbekannt)"


def _tenant_key(tc: dict) -> str:
    """Stabile Referenz-Key pro Mietvertrag (fuer Idempotenz-Map)."""
    return str(tc.get("unit_number") or tc.get("source_doc_id") or id(tc))


# ---------------------------------------------------------------------------
# Einzel-Schritte
# ---------------------------------------------------------------------------

async def _write_owner_contact(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> int | None:
    """Schritt 1a: Eigentuemer-Contact anlegen, falls noch nicht vorhanden."""
    if ir["contacts"].get("owner_id"):
        return ir["contacts"]["owner_id"]
    owner = state.get("owner") or {}
    if not (owner.get("last_name") or owner.get("company_name")):
        raise ImpowerError("Kein Eigentümer im Case-State.", -1)

    addresses = []
    addr = _address_payload(
        owner.get("street"), owner.get("postal_code"), owner.get("city"),
        owner.get("country"),
    )
    if addr:
        addresses.append(addr)

    payload = _build_contact_payload(
        owner.get("type") or "PERSON",
        salutation=owner.get("salutation"),
        title=owner.get("title"),
        first_name=owner.get("first_name"),
        last_name=owner.get("last_name"),
        company_name=owner.get("company_name"),
        trade_register_number=owner.get("trade_register_number"),
        addresses=addresses or None,
    )
    result = await _api_post(
        client, "/services/pmp-accounting/api/v1/contacts", payload,
    )
    if _is_error(result) or not isinstance(result, dict) or "id" not in result:
        raise ImpowerError(
            f"Eigentümer-Contact anlegen fehlgeschlagen: "
            f"{result.get('_msg') if isinstance(result, dict) else 'unbekannt'}",
            (result.get("_error", -1) if isinstance(result, dict) else -1),
        )
    ir["contacts"]["owner_id"] = result["id"]
    return result["id"]


async def _write_tenant_contacts(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> dict[str, int]:
    """Schritt 1b: Alle Mieter-Contacts anlegen."""
    tenants_ids: dict[str, int] = dict(ir["contacts"].get("tenants") or {})
    for tc in state.get("tenant_contracts") or []:
        key = _tenant_key(tc)
        if key in tenants_ids:
            continue
        tenant = tc.get("tenant") or {}
        if not (tenant.get("last_name") or tenant.get("company_name")):
            # Mieter ohne Name (z. B. "nur aus Mieterliste") -> skip
            continue
        payload = _build_contact_payload(
            tenant.get("type") or "PERSON",
            salutation=tenant.get("salutation"),
            first_name=tenant.get("first_name"),
            last_name=tenant.get("last_name"),
            company_name=tenant.get("company_name"),
            email=tenant.get("email"),
            phone_business=tenant.get("phone"),
            addresses=None,
        )
        result = await _api_post(
            client, "/services/pmp-accounting/api/v1/contacts", payload,
        )
        if _is_error(result) or not isinstance(result, dict) or "id" not in result:
            raise ImpowerError(
                f"Mieter-Contact anlegen fehlgeschlagen "
                f"({_display_name(tenant)}): "
                f"{result.get('_msg') if isinstance(result, dict) else 'unbekannt'}",
                (result.get("_error", -1) if isinstance(result, dict) else -1),
            )
        tenants_ids[key] = result["id"]
        ir["contacts"]["tenants"] = dict(tenants_ids)
    return tenants_ids


async def _write_property(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> int | None:
    """Schritt 2: Property minimal anlegen."""
    if ir.get("property_id"):
        return ir["property_id"]
    prop = state.get("property") or {}
    payload = {
        "number": prop.get("number"),
        "name": prop.get("name") or prop.get("number"),
        "street": prop.get("street"),
        "postalCode": prop.get("postal_code"),
        "city": prop.get("city"),
        "country": prop.get("country") or "DE",
        "administrationType": "MV",
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    result = await _api_post(
        client, "/services/pmp-accounting/api/v1/properties", payload,
    )
    if _is_error(result) or not isinstance(result, dict) or "id" not in result:
        raise ImpowerError(
            f"Property anlegen fehlgeschlagen: "
            f"{result.get('_msg') if isinstance(result, dict) else 'unbekannt'}",
            (result.get("_error", -1) if isinstance(result, dict) else -1),
        )
    ir["property_id"] = result["id"]
    return result["id"]


async def _write_property_owner_contract(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> int | None:
    """Schritt 3: PROPERTY_OWNER-Vertrag anlegen."""
    if ir.get("property_owner_contract_id"):
        return ir["property_owner_contract_id"]
    if not ir.get("property_id") or not ir["contacts"].get("owner_id"):
        raise ImpowerError(
            "property_id oder owner_id fehlt beim PROPERTY_OWNER-Contract.", -1,
        )
    mc = state.get("management_contract") or {}
    today = today_local().isoformat()
    payload = [
        {
            "propertyId": ir["property_id"],
            "signedDate": mc.get("contract_start_date") or today,
            "startDate": mc.get("contract_start_date") or today,
            "endDate": mc.get("contract_end_date"),
            "type": "PROPERTY_OWNER",
            "contacts": [
                {
                    "contactId": ir["contacts"]["owner_id"],
                    "role": ["OWNER"],
                }
            ],
        }
    ]
    payload = [{k: v for k, v in p.items() if v is not None} for p in payload]
    result = await _api_post(
        client, "/services/pmp-accounting/api/v1/contracts", payload,
    )
    if _is_error(result) or not isinstance(result, list) or not result:
        raise ImpowerError(
            f"PROPERTY_OWNER-Contract anlegen fehlgeschlagen: "
            f"{result.get('_msg') if isinstance(result, dict) else 'unbekannt'}",
            (result.get("_error", -1) if isinstance(result, dict) else -1),
        )
    first = result[0] if isinstance(result[0], dict) else {}
    contract_id = first.get("id")
    if not contract_id:
        raise ImpowerError(
            "PROPERTY_OWNER-Contract angelegt, aber keine ID in Response.", -1,
        )
    ir["property_owner_contract_id"] = contract_id
    return contract_id


async def _write_property_details(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> dict:
    """Schritt 4: PUT /properties mit Detail-Feldern + Buildings inline.

    Gibt die aktualisierte Property zurueck, u. a. mit ``buildings[].id``.
    """
    if ir.get("property_update_ok") and ir.get("building_ids"):
        return {}
    prop = state.get("property") or {}
    mc = state.get("management_contract") or {}
    billing = state.get("billing_address") or {}
    buildings_in = state.get("buildings") or []

    # Buildings inline: wenn leer, einen Default-Block ohne Namen haengen wir
    # nicht an — Impower BuildingEpo verlangt eine name-Feld.
    building_payload: list[dict] = []
    for b in buildings_in:
        name = (b or {}).get("name")
        if not name:
            continue
        building_payload.append(
            {
                "name": name,
                "address": _address_payload(
                    prop.get("street"), prop.get("postal_code"), prop.get("city"),
                    prop.get("country"),
                ),
            }
        )

    billing_dto = None
    if billing and not billing.get("is_same_as_owner"):
        billing_dto = _address_payload(
            billing.get("street"), billing.get("postal_code"), billing.get("city"),
            for_invoice=True, for_mail=False,
        )

    payload = {
        "id": ir["property_id"],
        "number": prop.get("number"),
        "name": prop.get("name") or prop.get("number"),
        "street": prop.get("street"),
        "postalCode": prop.get("postal_code"),
        "city": prop.get("city"),
        "country": prop.get("country") or "DE",
        "administrationType": "MV",
        "creditorId": prop.get("creditor_id"),
        "supervisorName": mc.get("supervisor_name"),
        "accountantName": mc.get("accountant_name"),
        "contractStartDate": mc.get("contract_start_date"),
        "contractEndDate": mc.get("contract_end_date"),
        "dunningFeeNet": mc.get("dunning_fee_net"),
        "billingAddress": billing_dto,
        "ownerContractId": ir.get("property_owner_contract_id"),
        "buildings": building_payload or None,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    result = await _api_put(
        client, "/services/pmp-accounting/api/v1/properties", payload,
    )
    if _is_error(result):
        raise ImpowerError(
            f"Property-Detail-Update fehlgeschlagen: {result.get('_msg')}",
            result.get("_error", -1),
        )
    ir["property_update_ok"] = True

    # Building-IDs aus Response extrahieren
    if isinstance(result, dict):
        b_ids = []
        name_map: dict[str, int] = {}
        for b in result.get("buildings") or []:
            bid = b.get("id") if isinstance(b, dict) else None
            bname = b.get("name") if isinstance(b, dict) else None
            if bid:
                b_ids.append(bid)
            if bid and bname:
                name_map[bname] = bid
        if b_ids:
            ir["building_ids"] = b_ids
        if name_map:
            ir["building_name_to_id"] = name_map
    return result if isinstance(result, dict) else {}


_UNIT_TYPE_DEFAULTS = {
    "APARTMENT": "APARTMENT",
    "COMMERCIAL": "COMMERCIAL",
    "PARKING": "PARKING",
    "OTHER": "OTHER",
}


async def _write_units(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> dict[str, int]:
    """Schritt 5: Units anlegen (Array-POST)."""
    existing_ids = dict(ir.get("unit_ids") or {})
    units_in = state.get("units") or []
    to_create: list[tuple[str, dict]] = []
    building_map = ir.get("building_name_to_id") or {}
    # Fallback: nur ein Building → alle Units da anhaengen
    fallback_building_id = ir["building_ids"][0] if ir.get("building_ids") else None

    for u in units_in:
        num = str((u or {}).get("number") or "").strip()
        if not num or num in existing_ids:
            continue
        utype = _UNIT_TYPE_DEFAULTS.get((u.get("unit_type") or "").upper(), "OTHER")
        bid = building_map.get(u.get("building_name")) if u.get("building_name") else fallback_building_id
        payload = {
            "propertyId": ir["property_id"],
            "buildingId": bid,
            "unitNrSharingDeclaration": num,
            "unitType": utype,
            "floor": u.get("floor"),
            "position": u.get("position"),
            "livingArea": u.get("living_area"),
            "heatingArea": u.get("heating_area"),
            "persons": u.get("persons"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        to_create.append((num, payload))

    if not to_create:
        return existing_ids

    result = await _api_post(
        client,
        "/services/pmp-accounting/api/v1/units",
        [p for _, p in to_create],
    )
    if _is_error(result) or not isinstance(result, list):
        raise ImpowerError(
            f"Units anlegen fehlgeschlagen: "
            f"{result.get('_msg') if isinstance(result, dict) else 'unbekannt'}",
            (result.get("_error", -1) if isinstance(result, dict) else -1),
        )
    for (num, _), item in zip(to_create, result, strict=False):
        if isinstance(item, dict) and "id" in item:
            existing_ids[num] = item["id"]
    ir["unit_ids"] = dict(existing_ids)
    return existing_ids


async def _write_tenant_contracts(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> dict[str, int]:
    """Schritt 6: TENANT-Vertraege anlegen (Array-POST), einer pro Mietvertrag."""
    existing_ids = dict(ir.get("tenant_contract_ids") or {})
    tenants_by_key = ir["contacts"].get("tenants") or {}
    unit_ids = ir.get("unit_ids") or {}

    to_create: list[tuple[str, dict]] = []
    for tc in state.get("tenant_contracts") or []:
        key = _tenant_key(tc)
        if key in existing_ids:
            continue
        contact_id = tenants_by_key.get(key)
        unit_number = str(tc.get("unit_number") or "").strip()
        unit_id = unit_ids.get(unit_number)
        contract = tc.get("contract") or {}
        if not contact_id or not unit_id:
            # Mieter-Contact oder Unit-ID fehlt -> skip, im Fehler-Log vermerken
            continue
        payload = {
            "propertyId": ir["property_id"],
            "unitId": unit_id,
            "type": "TENANT",
            "signedDate": contract.get("signed_date") or contract.get("start_date"),
            "startDate": contract.get("start_date"),
            "endDate": contract.get("end_date"),
            "vatRelevance": bool(contract.get("vat_relevant")),
            "contacts": [
                {
                    "contactId": contact_id,
                    "role": ["TENANT"],
                }
            ],
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        to_create.append((key, payload))

    if not to_create:
        return existing_ids

    result = await _api_post(
        client,
        "/services/pmp-accounting/api/v1/contracts",
        [p for _, p in to_create],
    )
    if _is_error(result) or not isinstance(result, list):
        raise ImpowerError(
            f"TENANT-Vertraege anlegen fehlgeschlagen: "
            f"{result.get('_msg') if isinstance(result, dict) else 'unbekannt'}",
            (result.get("_error", -1) if isinstance(result, dict) else -1),
        )
    for (key, _), item in zip(to_create, result, strict=False):
        if isinstance(item, dict) and "id" in item:
            existing_ids[key] = item["id"]
    ir["tenant_contract_ids"] = dict(existing_ids)
    return existing_ids


async def _write_exchange_plans(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> dict[str, int]:
    """Schritt 7: Miet-Positionen als Exchange-Plan pro Mietvertrag.

    MVP: Ein Exchange-Plan pro Mietvertrag, das `templateExchanges[]` enthaelt
    ein Item je Positionstyp (Kaltmiete / Betriebskosten / Heizkosten). Die
    genaue Granularitaet ist laut reference_impower_mietverwaltung_api.md
    schema-seitig nicht final geklaert — wenn Impower Split-Positionen statt
    Summen erwartet, muessen wir das hier anpassen.
    """
    existing_ids = dict(ir.get("exchange_plan_ids") or {})
    tenant_contracts = ir.get("tenant_contract_ids") or {}

    for tc in state.get("tenant_contracts") or []:
        key = _tenant_key(tc)
        if key in existing_ids:
            continue
        unit_contract_id = tenant_contracts.get(key)
        if not unit_contract_id:
            continue
        contract = tc.get("contract") or {}
        start = contract.get("start_date")
        if not start:
            continue

        positions = []
        for pos_type, amount_key in (
            ("COLD_RENT", "cold_rent"),
            ("OPERATING_COSTS", "operating_costs"),
            ("HEATING_COSTS", "heating_costs"),
        ):
            amount = contract.get(amount_key)
            if amount is None or amount == 0:
                continue
            positions.append(
                {
                    "propertyId": ir["property_id"],
                    "unitContractId": unit_contract_id,
                    "amount": amount,
                    "type": pos_type,
                    "recurrencePattern": "MONTHLY",
                }
            )
        # Fallback: nur Gesamtmiete gesetzt -> ein einziger Eintrag
        if not positions and contract.get("total_rent"):
            positions.append(
                {
                    "propertyId": ir["property_id"],
                    "unitContractId": unit_contract_id,
                    "amount": contract["total_rent"],
                    "type": "TOTAL_RENT",
                    "recurrencePattern": "MONTHLY",
                }
            )
        if not positions:
            continue

        payload = {
            "propertyId": ir["property_id"],
            "unitContractId": unit_contract_id,
            "startDate": start,
            "templateExchanges": positions,
        }
        result = await _api_post(
            client,
            "/services/pmp-accounting/api/v1/exchange-plan",
            payload,
        )
        if _is_error(result):
            raise ImpowerError(
                f"Exchange-Plan fuer {key} fehlgeschlagen: {result.get('_msg')}",
                result.get("_error", -1),
            )
        plan_id = result.get("id") if isinstance(result, dict) else None
        if plan_id:
            existing_ids[key] = plan_id
            ir["exchange_plan_ids"] = dict(existing_ids)
    return existing_ids


async def _write_deposits(
    client: httpx.AsyncClient, state: dict, ir: dict
) -> dict[str, int]:
    """Schritt 8: Kautionen (ein Deposit pro Mietvertrag mit deposit-Feld)."""
    existing_ids = dict(ir.get("deposit_ids") or {})
    tenant_contracts = ir.get("tenant_contract_ids") or {}

    to_create: list[tuple[str, dict]] = []
    for tc in state.get("tenant_contracts") or []:
        key = _tenant_key(tc)
        if key in existing_ids:
            continue
        unit_contract_id = tenant_contracts.get(key)
        if not unit_contract_id:
            continue
        contract = tc.get("contract") or {}
        amount = contract.get("deposit")
        if not amount:
            continue
        due = contract.get("deposit_due_date") or contract.get("start_date")
        if not due:
            continue
        payload = {
            "amount": amount,
            "bankOrderState": "NOT_NEEDED",
            "debtDate": due,
            "propertyId": ir["property_id"],
            "unitContractId": unit_contract_id,
        }
        to_create.append((key, payload))

    if not to_create:
        return existing_ids

    result = await _api_post(
        client,
        "/services/pmp-accounting/api/v1/plan/manual/deposit",
        [p for _, p in to_create],
    )
    if _is_error(result) or not isinstance(result, list):
        raise ImpowerError(
            f"Deposits anlegen fehlgeschlagen: "
            f"{result.get('_msg') if isinstance(result, dict) else 'unbekannt'}",
            (result.get("_error", -1) if isinstance(result, dict) else -1),
        )
    for (key, _), item in zip(to_create, result, strict=False):
        if isinstance(item, dict) and "id" in item:
            existing_ids[key] = item["id"]
    ir["deposit_ids"] = dict(existing_ids)
    return existing_ids


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def _write_all_steps(state: dict, ir: dict) -> None:
    """Durchlaeuft alle 8 Schritte mit Idempotenz."""
    async with _make_client() as client:
        await _write_owner_contact(client, state, ir)
        _log_step(ir, "owner_contact")

        await _write_tenant_contacts(client, state, ir)
        _log_step(ir, "tenant_contacts")

        await _write_property(client, state, ir)
        _log_step(ir, "property_create")

        await _write_property_owner_contract(client, state, ir)
        _log_step(ir, "property_owner_contract")

        await _write_property_details(client, state, ir)
        _log_step(ir, "property_details")

        await _write_units(client, state, ir)
        _log_step(ir, "units")

        await _write_tenant_contracts(client, state, ir)
        _log_step(ir, "tenant_contracts_create")

        await _write_exchange_plans(client, state, ir)
        _log_step(ir, "exchange_plans")

        await _write_deposits(client, state, ir)
        _log_step(ir, "deposits")


def run_mietverwaltung_write(case_id: uuid.UUID) -> None:
    """BackgroundTask-Einstieg. Eigene DB-Session, asyncio.run fuer den
    Write-Flow, damit der httpx.AsyncClient aus impower.py nativ laeuft."""
    import asyncio

    db = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == case_id).first()
        if case is None:
            return

        preflight_res = preflight(case.state or {})
        if not preflight_res.ok:
            ir = _ensure_impower_result(case)
            _log_error(
                ir,
                "preflight",
                "Pflichtfelder fehlen: " + ", ".join(preflight_res.missing),
            )
            case.status = "error"
            _commit_state(case, ir)
            audit(
                db, user=None, user_email="system",
                action="mietverwaltung_write_preflight_failed",
                entity_type="case", entity_id=case.id,
                details={"missing": preflight_res.missing},
            )
            db.commit()
            return

        case.status = "writing"
        ir = _ensure_impower_result(case)
        _commit_state(case, ir)
        db.commit()

        state = dict(case.state or {})

        try:
            asyncio.run(_write_all_steps(state, ir))
        except ImpowerError as exc:
            # Partial-Success: wenn mindestens eine Contact-ID oder property_id
            # schon gesetzt wurde, koennen wir teilweise schreiben und beim
            # naechsten Trigger fortsetzen.
            _log_error(ir, ir["steps_completed"][-1] if ir["steps_completed"] else "unknown", str(exc))
            case.status = "partial" if ir["steps_completed"] else "error"
            _commit_state(case, ir)
            audit(
                db, user=None, user_email="system",
                action="mietverwaltung_write_error",
                entity_type="case", entity_id=case.id,
                details={
                    "error": str(exc),
                    "steps_completed": list(ir["steps_completed"]),
                },
            )
            db.commit()
            return
        except Exception as exc:  # noqa: BLE001
            _log_error(ir, "orchestrator", f"{type(exc).__name__}: {exc}")
            case.status = "error"
            _commit_state(case, ir)
            audit(
                db, user=None, user_email="system",
                action="mietverwaltung_write_crashed",
                entity_type="case", entity_id=case.id,
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
            db.commit()
            return

        # Erfolg
        case.status = "written"
        _commit_state(case, ir)
        audit(
            db, user=None, user_email="system",
            action="mietverwaltung_write_complete",
            entity_type="case", entity_id=case.id,
            details={
                "property_id": ir.get("property_id"),
                "units": len(ir.get("unit_ids") or {}),
                "tenant_contracts": len(ir.get("tenant_contract_ids") or {}),
            },
        )
        db.commit()
    finally:
        db.close()
