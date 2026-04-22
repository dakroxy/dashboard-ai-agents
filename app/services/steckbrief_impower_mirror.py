"""Impower-Nightly-Mirror fuer Cluster 1 + 6 (Story 1.4).

Spiegelt pro Objekt (Object mit impower_property_id):
  - Cluster 1: full_address, weg_nr, Eigentuemer-Reconcile (OWNER-Contracts).
  - Cluster 6: reserve_current, reserve_target, wirtschaftsplan_status,
               sepa_mandate_refs (BOOKED-Direct-Debit-Mandate).

Alle Feld-Writes laufen durch `write_field_human(source="impower_mirror")`.
Damit greifen automatisch:
  - Mirror-Guard: User-Edits werden nicht ueberschrieben.
  - No-Op-Short-Circuit: identische Werte erzeugen keine Provenance-Rows.
  - Audit-Chain: pro Feld ein audit_log-Eintrag.

Orphan-Owner (Eigentuemer-Row ohne Match im aktuellen Impower-Set) werden
v1 NICHT auto-geloescht — Datenverlust-Risiko bei zeitweisen Impower-
Ausfaellen ist zu hoch. Orphans landen nur im sync_started-Audit.

Lock-Semantik: pro Process ein `asyncio.Lock`. Zweiter Trigger, waehrend ein
Lauf laeuft → `SyncRunResult(skipped=True, skip_reason="already_running")`.
Fuer horizontale Skalierung waere ein advisory PG lock noetig (v1.1-Scope).
"""
from __future__ import annotations

import asyncio
import logging
import unicodedata
import uuid
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Eigentuemer, Object
from app.services._sync_common import (
    ReconcileStats,
    SyncItemFailure,
    SyncRunResult,
    run_sync_job,
)
from app.services.impower import (
    _api_get,
    _contact_display_name,
    _get_all_paged,
    _make_client,
)
from app.services.steckbrief_write_gate import write_field_human


_logger = logging.getLogger(__name__)


def _is_impower_error(payload: Any) -> bool:
    """`_api_get` gibt bei 4xx/5xx/Timeout `{"_error": -1, "_msg": ...}`
    zurueck (kein Wurf). Dieser Sentinel muss explizit gecheckt werden,
    sonst wird ein leerer `[]`-Fallback als "keine Mandate" interpretiert
    und ueberschreibt bestehende Daten.
    """
    return isinstance(payload, dict) and "_error" in payload


# Wirtschaftsplan-Status-Mapping: Impower-Rohwert → deutschsprachiger
# lowercase-String fuer die UI (Story 1.5 rendert den String im Template).
_WIRTSCHAFTSPLAN_STATUS_MAP: dict[str, str] = {
    "RESOLVED": "beschlossen",
    "IN_PREPARATION": "in_vorbereitung",
    "DRAFT": "entwurf",
}


# Lazy-konstruiert im richtigen Event-Loop. pytest-asyncio dreht pro Test
# einen eigenen Loop — ein Modul-global angelegter Lock wuerde
# RuntimeError: bound to a different event loop werfen.
_mirror_lock: asyncio.Lock | None = None


def _get_mirror_lock() -> asyncio.Lock:
    global _mirror_lock
    if _mirror_lock is None:
        _mirror_lock = asyncio.Lock()
    return _mirror_lock


def _reset_mirror_lock_for_tests() -> None:
    """Test-Hook: zwischen Tests den Lock droppen, damit der Lazy-Getter im
    naechsten Lauf frisch baut."""
    global _mirror_lock
    _mirror_lock = None


# ---------------------------------------------------------------------------
# Mapping-Helpers
# ---------------------------------------------------------------------------

def _build_full_address(property_dict: dict[str, Any]) -> str | None:
    """Baut `"{street}, {zip} {city}"`. Ohne Street → None (write-gate No-Op)."""
    street = (property_dict.get("addressStreet") or "").strip()
    zip_ = (property_dict.get("addressZip") or "").strip()
    city = (property_dict.get("addressCity") or "").strip()
    if not street:
        return None
    tail = " ".join(p for p in (zip_, city) if p)
    return f"{street}, {tail}" if tail else street


def _map_wirtschaftsplan_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    mapped = _WIRTSCHAFTSPLAN_STATUS_MAP.get(raw)
    if mapped is not None:
        return mapped
    return str(raw).lower()


def _normalize_mandate_refs(mandates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter auf BOOKED, Projektion mit stabiler Key-Reihenfolge, Sort nach mandate_id.

    Ohne Stable-Sort fliegen bei jedem Lauf Provenance-Rows wegen Reordering.
    Listen-Gleichheit in Python ist ordnungs-sensitiv. Sort erfolgt ueber
    den String-Key, weil Impower mandate_id als int **oder** string liefern
    kann — gemischte Listen wuerden beim Tuple-Sort `TypeError` werfen.
    """
    booked: list[dict[str, Any]] = []
    for m in mandates:
        if m.get("state") != "BOOKED":
            continue
        mid = m.get("id")
        if mid is None:
            continue
        booked.append(
            {
                "mandate_id": str(mid),
                "bank_account_id": m.get("bankAccountId"),
                "state": "BOOKED",
            }
        )
    booked.sort(key=lambda item: item["mandate_id"])
    return booked


def _normalize_voting_stake(raw: Any) -> dict[str, Any]:
    """Bringt votingShare in ein stabiles Dict-Format.

    - float/int zwischen 0 und 1 → `{"percent": raw*100}` (Impower liefert
      Bruchanteile: 0.5 = 50 %).
    - float/int > 1 → `{"percent": raw}` (Annahme: bereits Prozent).
    - None → `{}` (leer; write-gate macht No-Op, kein Rauschen).

    Heuristik ist bis zur Live-Validierung empirisch. Grenzwerte (exakt 0,
    exakt 1) loggen wir als WARNING, damit wir beim ersten realen Lauf
    nachvollziehen koennen, was Impower tatsaechlich schickt.
    """
    if raw is None:
        return {}
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return {}
    if val == 0 or val == 1:
        _logger.warning(
            "voting_stake boundary value raw=%r — heuristic ambiguous, "
            "verify Impower semantics on next live run",
            raw,
        )
    if 0 <= val <= 1:
        return {"percent": val * 100}
    return {"percent": val}


def _nfkc(value: Any) -> str:
    """NFKC-normalisiert + trimmt. Gegen Unicode-Drift (Mueller/Müller) +
    Zero-Width-Spaces in LLM-/Impower-Ausgaben."""
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Impower-Ladefunktionen
# ---------------------------------------------------------------------------

async def _fetch_impower_snapshot(
    client: httpx.AsyncClient,
) -> dict[str, dict[str, Any]]:
    """Laedt alle Properties + pro Property die Direct-Debit-Mandate seriell.

    Rueckgabe: `{property_id_str: {"property": dict, "mandates": list}}`.

    Mandate-Fehler: `_api_get` gibt den `_error`-Sentinel zurueck statt zu
    werfen. Wir differenzieren:
      - Liste → normale BOOKED-Projektion.
      - Error-Sentinel → Property wird als "mandates_unavailable" geflagged,
        damit der Reconcile-Schritt `sepa_mandate_refs` NICHT auf []
        ueberschreibt.
      - Alles andere (unerwartet) → ebenfalls unavailable, eher vorsichtig
        als falsch.
    """
    properties = await _get_all_paged(client, "/v2/properties")
    out: dict[str, dict[str, Any]] = {}
    for prop in properties:
        pid = prop.get("id")
        if pid is None:
            continue
        pid_str = str(pid)
        mandates_raw = await _api_get(
            client,
            "/services/pmp-accounting/api/v1/direct-debit-mandate",
            {"propertyId": pid},
        )
        if _is_impower_error(mandates_raw):
            _logger.warning(
                "mandate fetch failed for property=%s: %s",
                pid_str,
                (mandates_raw or {}).get("_msg"),
            )
            out[pid_str] = {
                "property": prop,
                "mandates": [],
                "mandates_unavailable": True,
            }
            continue
        if isinstance(mandates_raw, list):
            out[pid_str] = {
                "property": prop,
                "mandates": mandates_raw,
                "mandates_unavailable": False,
            }
        else:
            out[pid_str] = {
                "property": prop,
                "mandates": [],
                "mandates_unavailable": True,
            }
    return out


async def _fetch_owner_contracts_by_property(
    client: httpx.AsyncClient,
) -> dict[str, list[dict[str, Any]]]:
    """Laedt alle OWNER-Vertraege + deren Contacts und gruppiert nach Property.

    Ein Vertrag kann mehrere Contacts im `contacts[]`-Array fuehren — jeder
    dieser Contacts wird zu einem Owner-Eintrag.
    """
    contracts = await _get_all_paged(
        client, "/v2/contracts", {"type": "OWNER"}
    )
    contacts = await _get_all_paged(client, "/v2/contacts")
    contacts_by_id: dict[str, dict[str, Any]] = {
        str(c["id"]): c for c in contacts if c.get("id") is not None
    }

    grouped: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        pid = contract.get("propertyId")
        if pid is None:
            continue
        pid_str = str(pid)
        voting_share = (
            contract.get("votingShare")
            if contract.get("votingShare") is not None
            else contract.get("sharePercent")
            if contract.get("sharePercent") is not None
            else contract.get("voteFraction")
        )
        for contact_ref in contract.get("contacts", []) or []:
            cid = contact_ref.get("id")
            if cid is None:
                continue
            cid_str = str(cid)
            contact = contacts_by_id.get(cid_str)
            # Wenn der Contact im Snapshot fehlt (Paging-Trunkation,
            # Impower-Teilausfall), liefern wir display_name=None — der
            # Reconcile-Schritt darf dann NICHT die numerische Contact-ID
            # in `name` schreiben.
            display_name = (
                _contact_display_name(contact) if contact else None
            )
            grouped.setdefault(pid_str, []).append(
                {
                    "contactId": cid_str,
                    "displayName": display_name,
                    "votingShare": voting_share,
                }
            )
    return grouped


# ---------------------------------------------------------------------------
# Reconcile-Logik
# ---------------------------------------------------------------------------

async def _reconcile_object(
    obj_id: uuid.UUID,
    impower_data: dict[str, Any] | None,
    owner_data: list[dict[str, Any]],
    db: Session,
) -> ReconcileStats:
    """Mirrort ein einzelnes Object. Wird aus run_sync_job aufgerufen (eigene
    DB-Session pro Item).

    Wirft `SyncItemFailure` mit phase + external_id + entity_id, damit der
    Sync-Wrapper den Fehler-Audit strukturiert ablegen kann.
    """
    stats = ReconcileStats()

    obj = db.get(Object, obj_id)
    if obj is None:
        stats.skipped_no_external_data = True
        return stats

    if obj.impower_property_id is None:
        stats.skipped_no_external_id = True
        return stats

    pid = obj.impower_property_id

    if impower_data is None:
        stats.skipped_no_external_data = True
        return stats

    prop = impower_data.get("property") or {}
    mandates_unavailable = bool(impower_data.get("mandates_unavailable"))
    mandates_raw = impower_data.get("mandates") or []

    try:
        # --- Cluster 1: full_address, weg_nr ---
        full_addr = _build_full_address(prop)
        # Wichtig: None NICHT schreiben — sonst wuerde eine bestehende
        # User-gepflegte Adresse auf NULL gesetzt, weil das Write-Gate
        # nur bei `old == new` No-Op macht, nicht bei new=None.
        if full_addr is not None:
            _apply_field(db, obj, "full_address", full_addr, pid, stats)

        weg = (
            prop.get("wegNumber")
            or prop.get("propertyHrId")
            or prop.get("name")
        )
        if weg is not None:
            _apply_field(db, obj, "weg_nr", weg, pid, stats)

        # --- Cluster 6: reserve_current, reserve_target,
        # wirtschaftsplan_status, sepa_mandate_refs ---
        finance = prop.get("financeSummary") or {}
        reserve_current = _to_decimal(
            prop.get("reserveCurrent") or finance.get("reserveCurrent")
        )
        reserve_target = _to_decimal(
            prop.get("reserveTargetMonthly") or finance.get("reserveTarget")
        )
        plan_status = _map_wirtschaftsplan_status(
            prop.get("economicPlanStatus")
            or prop.get("wirtschaftsplanStatus")
        )

        if reserve_current is not None:
            _apply_field(
                db, obj, "reserve_current", reserve_current, pid, stats
            )
        if reserve_target is not None:
            _apply_field(
                db, obj, "reserve_target", reserve_target, pid, stats
            )
        if plan_status is not None:
            _apply_field(
                db, obj, "wirtschaftsplan_status", plan_status, pid, stats
            )

        # Mandate nur schreiben, wenn der Fetch erfolgreich war — sonst
        # wuerden wir eine bestehende Liste still auf [] ueberschreiben.
        if not mandates_unavailable:
            mandate_refs = _normalize_mandate_refs(mandates_raw)
            _apply_field(
                db, obj, "sepa_mandate_refs", mandate_refs, pid, stats
            )

        # --- Eigentuemer-Reconcile ---
        _reconcile_eigentuemer(db, obj_id, pid, owner_data, stats)
    except SyncItemFailure:
        raise
    except Exception as exc:
        raise SyncItemFailure(
            phase="reconcile",
            external_id=pid,
            entity_id=obj_id,
            cause=exc,
        ) from exc

    return stats


def _apply_field(
    db: Session,
    entity: Any,
    field: str,
    value: Any,
    source_ref: str,
    stats: ReconcileStats,
) -> None:
    result = write_field_human(
        db,
        entity=entity,
        field=field,
        value=value,
        source="impower_mirror",
        user=None,
        source_ref=source_ref,
    )
    if result.written:
        stats.fields_updated += 1
    elif result.skip_reason == "user_edit_newer":
        stats.skipped_user_edit_newer += 1


def _reconcile_eigentuemer(
    db: Session,
    obj_id: uuid.UUID,
    impower_property_id: str,
    owners: list[dict[str, Any]],
    stats: ReconcileStats,
) -> None:
    existing = (
        db.execute(select(Eigentuemer).where(Eigentuemer.object_id == obj_id))
        .scalars()
        .all()
    )
    by_contact_id = {
        str(e.impower_contact_id): e
        for e in existing
        if e.impower_contact_id
    }

    impower_contact_ids: set[str] = set()

    for owner in owners:
        cid = str(owner.get("contactId"))
        impower_contact_ids.add(cid)
        # NFKC-Normalize + Trim. Ohne Normalize triggern Unicode-Drifts
        # ("Mueller" vs "Müller") oder Zero-Width-Spaces staendige
        # Provenance-Rewrites ohne Semantik-Change.
        display_name = _nfkc(owner.get("displayName"))
        voting_stake = _normalize_voting_stake(owner.get("votingShare"))

        # Wenn kein belastbarer Name aus Impower kam, NICHT schreiben —
        # sonst wuerde der numerische Contact-ID-Fallback ins `name`-Feld
        # laufen und bestehende echte Namen ueberschreiben.
        has_real_name = bool(display_name)

        existing_eig = by_contact_id.get(cid)
        if existing_eig is not None:
            name_written = False
            if has_real_name:
                name_result = write_field_human(
                    db,
                    entity=existing_eig,
                    field="name",
                    value=display_name,
                    source="impower_mirror",
                    user=None,
                    source_ref=cid,
                )
                name_written = name_result.written
                if name_result.skip_reason == "user_edit_newer":
                    stats.skipped_user_edit_newer += 1
            stake_result = write_field_human(
                db,
                entity=existing_eig,
                field="voting_stake_json",
                value=voting_stake,
                source="impower_mirror",
                user=None,
                source_ref=cid,
            )
            stake_written = stake_result.written
            written_count = int(name_written) + int(stake_written)
            if written_count:
                stats.eigentuemer_updated += 1
                stats.fields_updated += written_count
            if stake_result.skip_reason == "user_edit_newer":
                stats.skipped_user_edit_newer += 1
        else:
            # Wenn kein Name vorhanden ist, legen wir den Eigentuemer v1
            # NICHT blind an — ein leerer Name-Eintrag bringt in der UI
            # keinen Mehrwert und verschleiert das Problem.
            if not has_real_name:
                _logger.warning(
                    "eigentuemer insert skipped — kein displayName aus "
                    "Impower (property=%s, contact=%s)",
                    impower_property_id,
                    cid,
                )
                continue
            # Platzhalter-Bootstrap: name="" sorgt fuer old != new, damit der
            # No-Op-Guard beim ersten write_field_human NICHT zuschlaegt.
            # Constructor-kwargs sind vom Write-Gate-Coverage-Scanner bewusst
            # ausgenommen (siehe test_write_gate_coverage.py).
            new_eig = Eigentuemer(
                id=uuid.uuid4(),
                object_id=obj_id,
                name="",
                impower_contact_id=cid,
            )
            db.add(new_eig)
            db.flush()

            name_res = write_field_human(
                db,
                entity=new_eig,
                field="name",
                value=display_name,
                source="impower_mirror",
                user=None,
                source_ref=cid,
            )
            stake_res = write_field_human(
                db,
                entity=new_eig,
                field="voting_stake_json",
                value=voting_stake,
                source="impower_mirror",
                user=None,
                source_ref=cid,
            )
            # Nur zaehlen, wenn der Erst-Name wirklich persistiert wurde.
            if name_res.written:
                stats.eigentuemer_inserted += 1
                stats.fields_updated += 1
            if stake_res.written:
                stats.fields_updated += 1

    # Orphan-Erkennung (keine Loeschung — v1-Scope ist Datenerhalt).
    # Orphan-Entries tragen Objekt-Kontext (object_id, impower_contact_id,
    # display_name) — so bleibt ein Contact, der in mehreren Objekten als
    # Orphan auftaucht, pro Objekt nachvollziehbar.
    for e in existing:
        cid = e.impower_contact_id
        if cid and cid not in impower_contact_ids:
            stats.eigentuemer_orphans.append(
                {
                    "object_id": str(obj_id),
                    "impower_contact_id": str(cid),
                    "display_name": e.name or None,
                }
            )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_impower_mirror(
    db_factory: Any = SessionLocal,
    http_client_factory: Any = _make_client,
) -> SyncRunResult:
    """Fuehrt einen kompletten Impower-Nightly-Mirror-Lauf aus.

    Ablauf:
      1. Lock-Check (zweiter Trigger → skipped=already_running).
      2. Impower-Snapshot (Properties + Mandate) + Owner-Contracts laden.
      3. Alle Objects mit impower_property_id holen.
      4. Pro Object `_reconcile_object` durch run_sync_job wrappen.
    """
    lock = _get_mirror_lock()

    snapshot: dict[str, dict[str, Any]] = {}
    owners_by_property: dict[str, list[dict[str, Any]]] = {}

    async def fetch_items() -> list[uuid.UUID]:
        nonlocal snapshot, owners_by_property
        async with http_client_factory() as client:
            snapshot = await _fetch_impower_snapshot(client)
            owners_by_property = await _fetch_owner_contracts_by_property(client)
        db = db_factory()
        try:
            stmt = select(Object.id).where(
                Object.impower_property_id.is_not(None)
            )
            return list(db.execute(stmt).scalars().all())
        finally:
            db.close()

    async def reconcile(obj_id: uuid.UUID, db: Session) -> ReconcileStats:
        db_obj = db.get(Object, obj_id)
        pid = db_obj.impower_property_id if db_obj is not None else None
        impower_data = snapshot.get(str(pid)) if pid else None
        owners = owners_by_property.get(str(pid), []) if pid else []
        return await _reconcile_object(obj_id, impower_data, owners, db)

    return await run_sync_job(
        job_name="steckbrief_impower_mirror",
        fetch_items=fetch_items,
        reconcile_item=reconcile,
        db_factory=db_factory,
        lock=lock,
        item_identity=lambda oid: str(oid),
    )
