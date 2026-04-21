"""Impower-Router — Connectivity-Test und Matching-API (Read-Pfad).

Endpunkte sind hinter `impower:debug` geschuetzt (Admin-Only).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.models import User
from app.permissions import require_permission
from app.services import impower as svc
from app.services.impower import ImpowerError

router = APIRouter(prefix="/impower", tags=["impower"])


class MatchRequest(BaseModel):
    weg_kuerzel: str | None = None
    weg_name: str | None = None
    weg_adresse: str | None = None
    owner_name: str | None = None


# ---------------------------------------------------------------------------
# Health / Connectivity
# ---------------------------------------------------------------------------

@router.get("/health")
async def impower_health(
    _user: User = Depends(require_permission("impower:debug")),
):
    """Prüft ob die Impower-API erreichbar ist."""
    result = await svc.health_check()
    if not result["ok"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error", "Impower nicht erreichbar"),
        )
    return result


# ---------------------------------------------------------------------------
# Rohdaten-Endpunkte (für Debugging / Tests)
# ---------------------------------------------------------------------------

@router.get("/properties")
async def list_properties(
    _user: User = Depends(require_permission("impower:debug")),
):
    """Alle Properties aus Impower abrufen."""
    try:
        props = await svc.load_properties()
    except ImpowerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return {
        "count": len(props),
        "properties": [
            {
                "id": p.get("id"),
                "hr_id": p.get("propertyHrId"),
                "name": p.get("name"),
                "address": p.get("address") or p.get("street"),
            }
            for p in props
        ],
    }


@router.get("/contracts")
async def list_owner_contracts(
    _user: User = Depends(require_permission("impower:debug")),
):
    """Alle OWNER-Verträge abrufen (kompakte Ansicht)."""
    try:
        contracts = await svc.load_owner_contracts()
    except ImpowerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return {"count": len(contracts)}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

@router.post("/match")
async def match_extraction(
    body: MatchRequest,
    _user: User = Depends(require_permission("impower:debug")),
):
    """Matched eine Extraktion gegen Impower (Property + Contact)."""
    extraction = body.model_dump()
    try:
        result = await svc.run_full_match(extraction)
    except ImpowerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    response: dict = {
        "property_match": None,
        "contact_match": None,
        "ambiguous": result.ambiguous,
        "notes": result.notes,
    }

    if result.property_match:
        pm = result.property_match
        response["property_match"] = {
            "property_id": pm.property_id,
            "hr_id": pm.property_hr_id,
            "name": pm.property_name,
            "score": round(pm.score, 3),
        }

    if result.contact_match:
        cm = result.contact_match
        response["contact_match"] = {
            "contact_id": cm.contact_id,
            "display_name": cm.display_name,
            "score": round(cm.score, 3),
            "open_contract_ids": cm.open_contract_ids,
            "has_bank_account": cm.has_bank_account,
        }

    return response
