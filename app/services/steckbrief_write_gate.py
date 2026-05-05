"""Zentrales Write-Gate fuer das Objektsteckbrief-Modul.

Alle Schreibvorgaenge auf CD1-Haupt-Entitaeten (Object, Unit, InsurancePolicy,
...) laufen ueber diese Funktionen. Das Gate:

  * erzwingt, dass KI-Code nie direkt am Zielfeld schreibt (NFR-S6 / FR25),
  * legt bei jedem menschlichen/Mirror-Write eine FieldProvenance-Row an,
  * schreibt einen Audit-Eintrag in derselben Transaktion,
  * respektiert die Mirror-vs-User-Edit-Semantik (User-Edit friert automatische
    Mirror-Updates fuers Feld ein, Story 1.2 AC8),
  * schuetzt `entry_code_*`-Ciphertext-Felder vor Klartext-Leaks in Provenance
    und Audit-Details (`{"encrypted": True}`-Marker; die eigentliche Fernet-
    Encryption kommt mit Story 1.7).

Wichtig: das Gate macht KEIN db.commit() — der Caller haelt die Transaktion,
damit Business-Change + Provenance + Audit gemeinsam committed werden (NFR-S4,
architecture.md §Implementation Patterns).
"""
from __future__ import annotations

import base64
import copy
import datetime as _dt
import decimal
import math
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import (
    Ablesefirma,
    Bank,
    Dienstleister,
    Eigentuemer,
    FaciliooTicket,
    FieldProvenance,
    InsurancePolicy,
    Mieter,
    Mietvertrag,
    Object,
    ReviewQueueEntry,
    Schadensfall,
    SteckbriefPhoto,
    Unit,
    User,
    Versicherer,
    Wartungspflicht,
    Zaehler,
)
from app.services.audit import audit


class WriteGateError(Exception):
    """Illegale Uebergabe ans Write-Gate (unbekannter Source, unbekannte
    Entitaet, fehlendes Ziel-Object)."""


_ALLOWED_SOURCES: frozenset[str] = frozenset(
    {"user_edit", "impower_mirror", "facilioo_mirror", "sharepoint_mirror", "ai_suggestion"}
)
_MIRROR_SOURCES: frozenset[str] = frozenset(
    {"impower_mirror", "facilioo_mirror", "sharepoint_mirror"}
)


# Tabellen-Name → entity_type-String. Einzige Quelle der Wahrheit — deutsche
# Plural-Tabellennamen (`policen`, `wartungspflichten`) brechen jede
# rstrip("s")-Heuristik, deshalb explizit.
_TABLE_TO_ENTITY_TYPE: dict[str, str] = {
    "objects": "object",
    "units": "unit",
    "policen": "police",
    "wartungspflichten": "wartung",
    "schadensfaelle": "schaden",
    "versicherer": "versicherer",
    "dienstleister": "dienstleister",
    "banken": "bank",
    "ablesefirmen": "ablesefirma",
    "eigentuemer": "eigentuemer",
    "mieter": "mieter",
    "mietvertraege": "mietvertrag",
    "zaehler": "zaehler",
    "facilioo_tickets": "facilioo_ticket",
    "steckbrief_photos": "steckbrief_photo",
}

_ENTITY_TYPE_TO_CLASS: dict[str, type] = {
    "object": Object,
    "unit": Unit,
    "police": InsurancePolicy,
    "wartung": Wartungspflicht,
    "schaden": Schadensfall,
    "versicherer": Versicherer,
    "dienstleister": Dienstleister,
    "bank": Bank,
    "ablesefirma": Ablesefirma,
    "eigentuemer": Eigentuemer,
    "mieter": Mieter,
    "mietvertrag": Mietvertrag,
    "zaehler": Zaehler,
    "facilioo_ticket": FaciliooTicket,
    "steckbrief_photo": SteckbriefPhoto,
}

_REGISTRY_ENTITY_TYPES: frozenset[str] = frozenset(
    {"versicherer", "dienstleister", "bank", "ablesefirma", "eigentuemer", "mieter"}
)

_ENCRYPTED_FIELDS: dict[str, frozenset[str]] = {
    "object": frozenset(
        {"entry_code_main_door", "entry_code_garage", "entry_code_technical_room"}
    ),
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WriteResult:
    """Rueckgabewert von `write_field_human`. Erlaubt Caller (v.a. Mirror-Jobs)
    Reporting ohne zusaetzliche DB-Queries — `written=False, skipped=True,
    skip_reason=...` zeigt, warum nichts passiert ist."""

    written: bool
    skipped: bool = False
    skip_reason: str | None = None


# ---------------------------------------------------------------------------
# JSON-Safe-Helper
# ---------------------------------------------------------------------------

def _json_safe(value: Any, _seen: set[int] | None = None) -> Any:
    """Konvertiert beliebige Python-Werte in JSON-kompatible Formen.

    Nutzung fuer `value_snapshot` der FieldProvenance-Row: Postgres-JSONB
    akzeptiert nur JSON-Primitives, sonst wirft der Insert. CD1-Modelle
    enthalten `UUID`, `date`, `datetime`, `Decimal` und `bytes` — die werden
    hier auf lesbare Strings reduziert.

    `_seen` faengt zyklische Container ab — `proposed_value` in
    `write_field_ai_proposal` stammt aus LLM-Output und ist potenziell
    verschachtelt/zyklisch; ohne Cycle-Guard wuerde RecursionError fliegen."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (_dt.date, _dt.datetime, _dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, (list, tuple, dict)):
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return {"__cycle": True}
        _seen.add(marker)
        try:
            if isinstance(value, dict):
                return {str(k): _json_safe(v, _seen) for k, v in value.items()}
            return [_json_safe(v, _seen) for v in value]
        finally:
            _seen.discard(marker)
    return str(value)


def _json_safe_for_provenance(
    entity_type: str, field: str, value: Any
) -> Any:
    """Wie `_json_safe`, aber ersetzt Klartext-Werte sensibler Felder durch
    einen `{"encrypted": True}`-Marker (auch schon in Story 1.2 — die
    Fernet-Encryption selbst kommt mit 1.7, der Klartext-Leak-Schutz im
    Audit-/Provenance-Pfad muss aber ab 1.2 aktiv sein, sonst hat der
    Migrationspfad 1.2→1.7 ein Sicherheits-Gap)."""
    if field in _ENCRYPTED_FIELDS.get(entity_type, frozenset()):
        return {"encrypted": True}
    return _json_safe(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_field_human(
    db: Session,
    *,
    entity: Any,
    field: str,
    value: Any,
    source: str,
    user: User | None,
    source_ref: str | None = None,
    confidence: float | None = None,
    request: Request | None = None,
) -> WriteResult:
    """Schreibt ein Feld auf einer CD1-Entitaet mit voller Nachvollziehbarkeit.

    Ablauf:
      1. Validierung (entity_type bekannt, source whitelisted).
      2. Mirror-Guard (AC8): wenn source ein Mirror ist und der letzte
         Provenance-Eintrag ein user_edit/ai_suggestion war, return
         `skipped=True, skip_reason="user_edit_newer"` — kein Write, kein
         Invalidate, kein Audit.
      3. No-Op-Short-Circuit: unveraenderter Wert + gleicher Source → return
         `skipped=True, skip_reason="noop_unchanged"`.
      4. Feld setzen, Provenance-Row anlegen, Audit-Eintrag schreiben.
      5. Bei Object-Entity: `pflegegrad_score_cached` + `_updated_at`
         reseten (`invalidate_pflegegrad`).
    """
    table = getattr(entity, "__tablename__", None)
    entity_type = _TABLE_TO_ENTITY_TYPE.get(table) if table else None
    if entity_type is None:
        raise WriteGateError(
            f"Unbekannte Entitaet (__tablename__={table!r}) im Write-Gate"
        )
    if source not in _ALLOWED_SOURCES:
        raise WriteGateError(f"Unbekannte source: {source!r}")
    if source == "ai_suggestion" and user is None:
        raise WriteGateError(
            "source='ai_suggestion' erfordert einen Reviewer-User — der "
            "kanonische Pfad laeuft ueber approve_review_entry, das immer "
            "einen User traegt."
        )

    # --- Feld-Encryption (entry_code_* und andere _ENCRYPTED_FIELDS) ---
    # Fernet hat Random-IV → jedes Encrypt ergibt ein neues Token; der
    # No-Op-Vergleich unten vergleicht darum alten Ciphertext gegen neuen
    # Ciphertext und schlaegt immer durch. Absicht fuer v1.
    if field in _ENCRYPTED_FIELDS.get(entity_type, frozenset()):
        # Guard gegen Double-Encrypt: bereits-verschluesselter Wert (v1:-Prefix)
        # wuerde erneut verschluesselt → WriteGateError statt stiller Korruption.
        if isinstance(value, str) and value.startswith("v1:"):
            raise WriteGateError(
                f"value already encrypted (v1: prefix detected); "
                f"refusing double-encrypt for field={field!r} entity={entity_type!r}"
            )
        if value is not None and isinstance(value, str) and value.strip():
            from app.services.field_encryption import encrypt_field as _enc
            value = _enc(value, entity_type=entity_type, field=field)
        else:
            value = None

    entity_id = entity.id
    if entity_id is None:
        raise WriteGateError(
            f"Entity {type(entity).__name__} hat keine id — db.flush() oder "
            "explizites id=uuid.uuid4() vor dem Write-Gate aufrufen."
        )

    # --- Mirror-Guard (AC8) ---
    if source in _MIRROR_SOURCES:
        last = _latest_provenance(db, entity_type, entity_id, field)
        if last is not None and last.source in {"user_edit", "ai_suggestion"}:
            return WriteResult(
                written=False, skipped=True, skip_reason="user_edit_newer"
            )

    # --- No-Op-Short-Circuit ---
    # Bei JSONB-Feldern gibt `getattr` eine Referenz auf das Dict/List in der
    # ORM-Instance zurueck — wenn der Caller `value=obj.voting_rights` uebergibt
    # (aliased), greift die Gleichheit trivial und wir wuerden den Write
    # stumm uebergehen. Deep-Copy vor Vergleich schliesst das Loch.
    raw_old = getattr(entity, field)
    old_value = copy.deepcopy(raw_old) if isinstance(raw_old, (dict, list)) else raw_old
    if old_value == value:
        last = _latest_provenance(db, entity_type, entity_id, field)
        # Unchanged + selbe Source → skip. Auch beim Erstwrite mit
        # identischem Wert (last is None, z.B. Mirror importiert NULL auf
        # leeres Feld) macht eine Provenance-Row keinen Sinn — sonst
        # verrauschen wir die History mit {"old": X, "new": X}-Eintraegen.
        if last is None or last.source == source:
            return WriteResult(
                written=False, skipped=True, skip_reason="noop_unchanged"
            )

    # --- Feld setzen (JSONB-sicher via Deep-Copy + flag_modified) ---
    if isinstance(value, (dict, list)):
        setattr(entity, field, copy.deepcopy(value))
        flag_modified(entity, field)
    else:
        setattr(entity, field, value)

    # --- Provenance-Row ---
    safe_old = _json_safe_for_provenance(entity_type, field, old_value)
    safe_new = _json_safe_for_provenance(entity_type, field, value)
    prov = FieldProvenance(
        id=uuid.uuid4(),
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field,
        source=source,
        source_ref=source_ref,
        user_id=user.id if user is not None else None,
        confidence=confidence,
        value_snapshot={"old": safe_old, "new": safe_new},
    )
    db.add(prov)

    # --- Audit ---
    action = (
        "registry_entry_updated"
        if entity_type in _REGISTRY_ENTITY_TYPES
        else "object_field_updated"
    )
    audit(
        db,
        user,
        action,
        entity_type=entity_type,
        entity_id=entity_id,
        details={
            "entity_type": entity_type,
            "field": field,
            "source": source,
            "old": safe_old,
            "new": safe_new,
        },
        request=request,
    )

    # --- Pflegegrad-Cache invalidieren (nur Object, nur bei written=True) ---
    if isinstance(entity, Object):
        _invalidate_pflegegrad(entity)

    return WriteResult(written=True)


def write_field_ai_proposal(
    db: Session,
    *,
    target_entity_type: str,
    target_entity_id: uuid.UUID,
    field: str,
    proposed_value: Any,
    agent_ref: str,
    confidence: float,
    source_doc_id: uuid.UUID | None,
    agent_context: dict[str, Any] | None = None,
    request: Request | None = None,
    user: User | None = None,
) -> ReviewQueueEntry:
    """Legt einen KI-Vorschlag als ReviewQueueEntry an. SCHREIBT NICHT ans
    Zielfeld — das ist die strukturelle Blockade (NFR-S6). Erst eine
    explizite Freigabe via `approve_review_entry` macht daraus einen echten
    Feld-Write.
    """
    if target_entity_type not in _ENTITY_TYPE_TO_CLASS:
        raise WriteGateError(
            f"Unbekannter target_entity_type: {target_entity_type!r}"
        )
    # Ciphertext-Felder duerfen keine KI-Proposals bekommen — sonst landet
    # der Klartext-Vorschlag in `review_queue_entries.proposed_value` und
    # verstoesst gegen NFR-S2 (Story 1.7 schaltet Encryption scharf, aber
    # der Leak-Schutz muss ab 1.2 greifen).
    if field in _ENCRYPTED_FIELDS.get(target_entity_type, frozenset()):
        raise WriteGateError(
            f"KI-Proposals fuer Ciphertext-Feld {target_entity_type}.{field} "
            "sind nicht erlaubt (Klartext-Leak-Schutz, Story 1.7 folgt)."
        )
    if isinstance(confidence, bool) or not math.isfinite(float(confidence)) or not (
        0.0 <= float(confidence) <= 1.0
    ):
        raise ValueError(
            f"confidence muss endlicher float in [0.0, 1.0] sein, nicht {confidence!r}"
        )

    entry = ReviewQueueEntry(
        id=uuid.uuid4(),
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
        field_name=field,
        proposed_value={"value": _json_safe(proposed_value)},
        agent_ref=agent_ref,
        confidence=float(confidence),
        source_doc_id=source_doc_id,
        agent_context=agent_context or {},
        status="pending",
    )
    db.add(entry)

    audit(
        db,
        user,
        "review_queue_created",
        entity_type=target_entity_type,
        entity_id=target_entity_id,
        details={
            "field": field,
            "agent_ref": agent_ref,
            "confidence": float(confidence),
        },
        request=request,
    )
    return entry


def approve_review_entry(
    db: Session,
    *,
    entry_id: uuid.UUID,
    user: User,
    request: Request | None = None,
) -> None:
    """Freigabe eines KI-Vorschlags: schreibt das Zielfeld mit
    `source="ai_suggestion"` + Confidence + agent_ref und markiert den Entry
    als approved. Fuer den eigentlichen Write wird `write_field_human`
    wiederverwendet — so landen Feld, Provenance und Audit in einer
    atomaren Transaktion.
    """
    entry = db.execute(
        select(ReviewQueueEntry)
        .where(ReviewQueueEntry.id == entry_id)
        .with_for_update()
    ).scalar_one_or_none()
    if entry is None:
        raise WriteGateError(f"ReviewQueueEntry {entry_id} nicht gefunden")
    if entry.status != "pending":
        raise ValueError(
            f"ReviewQueueEntry {entry_id} bereits entschieden (status={entry.status})"
        )

    cls = _ENTITY_TYPE_TO_CLASS.get(entry.target_entity_type)
    if cls is None:
        raise WriteGateError(
            f"Unbekannter target_entity_type in Entry: {entry.target_entity_type!r}"
        )
    target = db.get(cls, entry.target_entity_id)
    if target is None:
        raise WriteGateError(
            f"Ziel-Entity {entry.target_entity_type}/{entry.target_entity_id} fehlt"
        )

    # Sicherstellen, dass der Entry persistiert ist — approve direkt nach
    # create ohne Zwischen-Commit braucht einen Flush, damit id + agent_ref
    # stabil referenzierbar sind.
    db.flush()

    write_result = write_field_human(
        db,
        entity=target,
        field=entry.field_name,
        value=entry.proposed_value["value"],
        source="ai_suggestion",
        user=user,
        source_ref=entry.agent_ref,
        confidence=entry.confidence,
        request=request,
    )
    # Wenn der Write still uebersprungen wurde (z.B. weil dasselbe Feld schon
    # mit identischem Wert + Source="ai_suggestion" in der Provenance steht —
    # Duplicate-Approve-Edge-Case), wuerden wir sonst einen approved-Entry
    # ohne Provenance/Audit-Chain erzeugen. Lieber laut abbrechen.
    if write_result.skipped:
        raise ValueError(
            f"Approve fuer Entry {entry_id} wurde vom Write-Gate uebersprungen "
            f"(skip_reason={write_result.skip_reason!r}) — Zielfeld hat bereits "
            "denselben Wert mit ai_suggestion-Provenance. Entry nicht als "
            "approved markiert."
        )

    entry.status = "approved"
    entry.decided_at = _dt.datetime.now(tz=_dt.timezone.utc)
    entry.decided_by_user_id = user.id

    audit(
        db,
        user,
        "review_queue_approved",
        entity_type="review_queue_entry",
        entity_id=entry.id,
        details={
            "target_entity_type": entry.target_entity_type,
            "target_entity_id": str(entry.target_entity_id),
            "field": entry.field_name,
            "value": _json_safe_for_provenance(
                entry.target_entity_type, entry.field_name, entry.proposed_value["value"]
            ),
        },
        request=request,
    )


def reject_review_entry(
    db: Session,
    *,
    entry_id: uuid.UUID,
    user: User,
    reason: str,
    request: Request | None = None,
) -> None:
    """Lehnt einen KI-Vorschlag ab. Kein Field-Write, keine Provenance-Row."""
    entry = db.execute(
        select(ReviewQueueEntry)
        .where(ReviewQueueEntry.id == entry_id)
        .with_for_update()
    ).scalar_one_or_none()
    if entry is None:
        raise WriteGateError(f"ReviewQueueEntry {entry_id} nicht gefunden")
    if entry.status != "pending":
        raise ValueError(
            f"ReviewQueueEntry {entry_id} bereits entschieden (status={entry.status})"
        )

    entry.status = "rejected"
    entry.decision_reason = reason
    entry.decided_at = _dt.datetime.now(tz=_dt.timezone.utc)
    entry.decided_by_user_id = user.id

    audit(
        db,
        user,
        "review_queue_rejected",
        entity_type="review_queue_entry",
        entity_id=entry.id,
        details={
            "target_entity_type": entry.target_entity_type,
            "target_entity_id": str(entry.target_entity_id),
            "field": entry.field_name,
            "reason": reason,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _latest_provenance(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
) -> FieldProvenance | None:
    # Wichtig: die Session laeuft mit autoflush=False. Ohne expliziten flush
    # wuerde der Mirror-Guard/No-Op-Check pending Provenance-Rows derselben
    # Transaktion nicht sehen und falsch positiv durchlassen.
    db.flush()
    stmt = (
        select(FieldProvenance)
        .where(
            FieldProvenance.entity_type == entity_type,
            FieldProvenance.entity_id == entity_id,
            FieldProvenance.field_name == field_name,
        )
        .order_by(FieldProvenance.created_at.desc(), FieldProvenance.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _invalidate_pflegegrad(obj: Object) -> None:
    """Direkter Cache-Write auf `pflegegrad_score_*` — explizite Ausnahme
    vom Write-Gate-Boundary (AC9 Allow-List). Die Invalidation passiert
    als Seiteneffekt eines echten Feld-Writes; der Pflegegrad selbst wird
    in Story 3.3 berechnet, hier nur der Hook."""
    obj.pflegegrad_score_cached = None
    obj.pflegegrad_score_updated_at = None
