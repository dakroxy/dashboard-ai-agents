"""Inline-Edit fuer Extraktionsfelder eines SEPA-Lastschriftmandats.

Click-to-Edit pro Feld: Save legt eine neue Extraction-Row mit ``model="manual"``
an, resettet ``matching_result``/``impower_result`` und stellt ``doc.status``
auf ``"matching"``, sodass das HTMX-Polling sofort den Re-Match-Verlauf rendert.
``BackgroundTasks`` der aufrufenden Route triggert ``_run_matching``.

Validierung:
- IBAN: NFKC-Normalize + ``schwifty.IBAN.validate()`` (gleiches Pattern wie
  der Chat-Guard und der Impower-Schreibpfad).
- ``sepa_date``: ``date.fromisoformat()`` (ISO-Format ``YYYY-MM-DD``).
- Sonstige Text-Felder: ``strip()``, leerer String -> ``None``.

``notes``/``confidence``/``model`` und Matching-/Write-Result sind nicht
editierbar (Whitelist ``EDITABLE_FIELDS``).
"""
from __future__ import annotations

import copy
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, Request
from schwifty import IBAN as SchwiftyIBAN
from schwifty.exceptions import SchwiftyException
from sqlalchemy.orm import Session

from app.models import Document, Extraction, User
from app.services.audit import audit
from app.services.impower import _normalize_iban


# Whitelist editierbarer Felder. Reihenfolge entspricht der Anzeige im
# Extraction-Block. ``notes``/``confidence`` bleiben absichtlich draussen.
EDITABLE_FIELDS: tuple[str, ...] = (
    "weg_kuerzel",
    "weg_name",
    "weg_adresse",
    "unit_nr",
    "owner_name",
    "iban",
    "bic",
    "bank_name",
    "sepa_date",
    "creditor_id",
)

# Status, in denen Inline-Edit erlaubt ist — gleicher Set wie der Approve-Button.
EDITABLE_STATUSES: frozenset[str] = frozenset(
    {"extracted", "needs_review", "matched", "error"}
)


class FieldValidationError(HTTPException):
    """422 mit deutscher Fehlermeldung — die Route rendert die Edit-Form neu."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=422, detail=detail)


def _strip_control_chars(value: str) -> str:
    """Entfernt NUL und sonstige C0-Steuerzeichen — Postgres weist NULs in
    JSONB-Strings zurueck (DataError). Drucksbar lassen wir durch, weil
    `_normalize_iban` (NFKC + isalnum) den IBAN-Spezialfall ohnehin abdeckt.
    """
    return "".join(c for c in value if c >= " " or c in ("\t",))


def _validate_iban(raw_input: str) -> str | None:
    """Validiert eine IBAN. raw_input ist bereits trim-bereinigt.

    Wenn raw_input leer ist, wird das Feld geleert (None).
    Wenn raw_input nicht leer ist, aber nach NFKC-Normalize keine
    alphanumerischen Zeichen mehr uebrig bleiben (z. B. nur Whitespace
    / Sonderzeichen), wird das als Fehleingabe behandelt — sonst wuerde
    der User eine IBAN unbeabsichtigt loeschen.
    """
    if not raw_input:
        return None
    normalized = _normalize_iban(raw_input)
    if not normalized:
        raise FieldValidationError("Ungültige IBAN")
    try:
        SchwiftyIBAN(normalized).validate()
    except (SchwiftyException, ValueError, TypeError) as exc:
        raise FieldValidationError("Ungültige IBAN") from exc
    return normalized


def _validate_sepa_date(value: str) -> str | None:
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise FieldValidationError("Datum YYYY-MM-DD") from exc
    return value


def _coerce_value(field: str, value_raw: str | None) -> Any:
    raw = _strip_control_chars((value_raw or "").strip())
    if field == "iban":
        return _validate_iban(raw)
    if field == "sepa_date":
        return _validate_sepa_date(raw)
    return raw or None


def update_extraction_field(
    db: Session,
    doc: Document,
    field: str,
    value_raw: str | None,
    user: User,
    request: Request,
) -> Extraction | None:
    """Persistiert einen Feld-Edit als neue Extraction-Row.

    Returnt die neue Extraction-Row bei tatsaechlichem Save.
    Returnt ``None`` bei No-Op (Wert unveraendert) — Caller sollte dann
    den Re-Match-BG-Task NICHT triggern und den Block einfach neu rendern.
    Wirft 400 fuer ungueltige Felder/Status, 422 (FieldValidationError)
    fuer Validierungsfehler.
    """
    if field not in EDITABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Feld '{field}' ist nicht editierbar.",
        )
    if doc.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status '{doc.status}' kann nicht editiert werden.",
        )

    # Inline-Edit ist auf SEPA-Lastschrift-Workflow beschraenkt. Mietverwaltungs-
    # Cases haben eigene Edit-Pfade in /cases/{id} — wenn ein Case-Document
    # versehentlich hier landet, wuerden SEPA-Field-Keys ins Mietverwaltungs-
    # Extraction-JSON geschrieben (Cross-Workflow-Kontamination).
    if doc.workflow is None or doc.workflow.key != "sepa_mandate":
        raise HTTPException(
            status_code=400,
            detail="Inline-Edit nur für SEPA-Lastschrift-Dokumente.",
        )

    latest = (
        db.query(Extraction)
        .filter(Extraction.document_id == doc.id)
        .order_by(Extraction.created_at.desc())
        .first()
    )
    if latest is None or not latest.extracted:
        raise HTTPException(
            status_code=400,
            detail="Keine Extraktion vorhanden — Edit nicht möglich.",
        )

    new_value = _coerce_value(field, value_raw)

    old_value = latest.extracted.get(field)
    if old_value == new_value:
        # No-Op — kein neuer State, kein Audit, kein Re-Match-Trigger.
        return None

    # Deepcopy, weil ``extracted`` ein nested JSONB-Dict werden kann (heutige
    # MandateExtraction ist flach, aber ``dict(...)`` waere bei zukuenftigen
    # nested Strukturen ein Shallow-Copy und wuerde die LLM-Original-Row
    # versehentlich mutieren).
    new_extracted = copy.deepcopy(latest.extracted)
    new_extracted[field] = new_value

    # ``-manual`` einmalig — wiederholte Saves sollten nicht
    # ``sepa-v1-manual-manual-manual...`` produzieren.
    new_prompt_version = (
        latest.prompt_version
        if latest.prompt_version.endswith("-manual")
        else f"{latest.prompt_version}-manual"
    )

    new_extraction = Extraction(
        id=uuid.uuid4(),
        document_id=doc.id,
        model="manual",
        prompt_version=new_prompt_version,
        raw_response="",
        extracted=new_extracted,
        status="ok",
        # Explizit setzen: server_default=func.now() ist in SQLite sekunden-
        # granular; bei mehreren Saves innerhalb einer Sekunde wuerden
        # ORDER BY created_at DESC nicht-deterministisch sortieren.
        created_at=datetime.now(timezone.utc),
    )
    db.add(new_extraction)

    # Status-Reset analog Chat-Korrektur (`documents.py:660-678`): alle
    # Matching-/Write-Ergebnisse sind nach einem Edit ungueltig. Wir setzen
    # status="matching" direkt, damit die Save-Response sofort den Spinner
    # rendert und das HTMX-Polling laeuft — der _run_matching-BG-Task setzt
    # den Status anschliessend auf "matched"/"needs_review".
    doc.status = "matching"
    doc.matching_result = None
    doc.impower_result = None

    audit(
        db,
        user,
        "extraction_field_updated",
        entity_type="document",
        entity_id=doc.id,
        document_id=doc.id,
        details={"field": field, "old": old_value, "new": new_value},
        request=request,
    )

    db.flush()
    return new_extraction
