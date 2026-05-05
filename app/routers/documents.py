from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import AuditLog, ChatMessage, Document, Extraction, User, Workflow
from app.permissions import (
    accessible_workflow_ids,
    can_access_workflow,
    has_permission,
)
from app.services.audit import audit
from app.templating import templates
from app.services.claude import chat_about_mandate, extract_mandate_from_pdf
from app.services.document_field_edit import (
    EDITABLE_FIELDS,
    EDITABLE_STATUSES,
    FieldValidationError,
    update_extraction_field,
)
from app.services.impower import (
    MatchResult,
    run_full_match,
    write_sepa_mandate,
)

DEFAULT_WORKFLOW_KEY = "sepa_mandate"

# Statuses that allow the approve/write action
_APPROVABLE_STATUSES = {"extracted", "needs_review", "matched", "error"}

# Anzeige-Labels fuer die zehn editierbaren Extraktionsfelder.
_EXTRACTION_FIELD_LABELS: dict[str, str] = {
    "weg_kuerzel": "WEG-Kürzel",
    "weg_name": "WEG",
    "weg_adresse": "Adresse WEG",
    "unit_nr": "Einheit",
    "owner_name": "Eigentümer",
    "iban": "IBAN",
    "bic": "BIC",
    "bank_name": "Bank",
    "sepa_date": "SEPA-Datum",
    "creditor_id": "Gläubiger-ID",
}


def _load_default_workflow(db: Session) -> Workflow:
    wf = db.query(Workflow).filter(Workflow.key == DEFAULT_WORKFLOW_KEY).first()
    if wf is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow '{DEFAULT_WORKFLOW_KEY}' nicht gefunden.",
        )
    return wf


def _load_doc_for_user(db: Session, user: User, document_id: uuid.UUID) -> Document:
    """Laedt ein Dokument und prueft den Zugriff anhand des Workflows.

    Regel: User muss Workflow-Zugriff haben. Wer zusaetzlich nur eigene
    Dokumente sehen darf (fehlende documents:view_all), sieht fremde Docs
    nicht — auch wenn der Workflow eigentlich zugaenglich waere.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not can_access_workflow(db, user, doc.workflow):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if doc.uploaded_by_id != user.id and not has_permission(user, "documents:view_all"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return doc


router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf"}
UPLOAD_DIR = Path(settings.uploads_dir)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

def _match_result_to_dict(mr: MatchResult) -> dict:
    return {
        "property": asdict(mr.property_match) if mr.property_match else None,
        "contact": asdict(mr.contact_match) if mr.contact_match else None,
        "ambiguous": mr.ambiguous,
        "notes": mr.notes,
    }


def _run_matching(document_id: uuid.UUID) -> None:
    """Matcht Extraktion gegen Impower und speichert Ergebnis in matching_result."""
    db: Session = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            return

        extraction = (
            db.query(Extraction)
            .filter(Extraction.document_id == doc.id)
            .order_by(Extraction.created_at.desc())
            .first()
        )
        if extraction is None or extraction.status != "ok" or not extraction.extracted:
            return

        doc.status = "matching"
        db.commit()

        try:
            match_result: MatchResult = asyncio.run(run_full_match(extraction.extracted))
        except Exception as exc:  # noqa: BLE001
            doc.status = "needs_review"
            doc.matching_result = {"error": f"Matching-Fehler: {exc}"}
            db.commit()
            return

        doc.matching_result = _match_result_to_dict(match_result)

        fully_matched = (
            match_result.property_match is not None
            and match_result.contact_match is not None
            and not match_result.ambiguous
            and bool(match_result.contact_match.open_contract_ids)
        )
        doc.status = "matched" if fully_matched else "needs_review"
        db.commit()
    finally:
        db.close()


def _run_write(document_id: uuid.UUID, user_email: str, user_id: uuid.UUID) -> None:
    """Führt den Impower-Schreibpfad durch und schreibt das Ergebnis in impower_result."""
    db: Session = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            return

        extraction = (
            db.query(Extraction)
            .filter(Extraction.document_id == doc.id)
            .order_by(Extraction.created_at.desc())
            .first()
        )
        if extraction is None or not extraction.extracted:
            doc.status = "error"
            doc.impower_result = {"error": "Keine Extraktion vorhanden."}
            db.commit()
            return

        # Re-run matching — nimmt Chat-Korrekturen an der Extraktion mit
        try:
            match_result = asyncio.run(run_full_match(extraction.extracted))
        except Exception as exc:  # noqa: BLE001
            doc.status = "error"
            doc.impower_result = {"error": f"Matching fehlgeschlagen: {exc}"}
            db.commit()
            return

        doc.matching_result = _match_result_to_dict(match_result)
        ext = extraction.extracted

        missing: list[str] = []
        if not ext.get("iban"):
            missing.append("IBAN")
        if not ext.get("owner_name"):
            missing.append("Eigentümer-Name")
        if match_result.property_match is None:
            missing.append("Objekt (kein Match in Impower)")
        if match_result.contact_match is None:
            missing.append("Eigentümer-Kontakt (kein Match in Impower)")

        if missing:
            doc.status = "error"
            doc.impower_result = {
                "error": f"Pflichtfelder fehlen oder kein Match: {', '.join(missing)}"
            }
            db.add(AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                document_id=doc.id,
                entity_type="document",
                entity_id=doc.id,
                user_email=user_email,
                action="document_write_failed_validation",
                details_json={"missing": missing},
            ))
            db.commit()
            return

        doc.status = "writing"
        db.commit()

        iban = ext["iban"].replace(" ", "")
        bic = (ext.get("bic") or "").strip()
        holder_name = ext.get("owner_name", "")
        signed_date = (ext.get("sepa_date") or "").strip()
        if not signed_date:
            import datetime as dt
            signed_date = dt.date.today().isoformat()

        try:
            write_result = asyncio.run(write_sepa_mandate(
                contact_id=match_result.contact_match.contact_id,
                property_id=match_result.property_match.property_id,
                open_contract_ids=match_result.contact_match.open_contract_ids,
                iban=iban,
                bic=bic,
                holder_name=holder_name,
                signed_date=signed_date,
            ))
        except Exception as exc:  # noqa: BLE001
            doc.status = "error"
            doc.impower_result = {"error": f"Unerwarteter Fehler: {exc}"}
            db.commit()
            return

        doc.impower_result = write_result.as_dict()
        if write_result.error:
            doc.status = "error"
            action = "document_write_failed"
        elif write_result.already_present:
            doc.status = "already_present"
            action = "document_already_present"
        else:
            doc.status = "written"
            action = "document_written"

        db.add(AuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            document_id=doc.id,
            entity_type="document",
            entity_id=doc.id,
            user_email=user_email,
            action=action,
            details_json={
                "impower_result": write_result.as_dict(),
                "extraction_summary": {
                    "iban": iban,
                    "owner_name": holder_name,
                    "property": match_result.property_match.property_name,
                    "contact": match_result.contact_match.display_name,
                    "open_contracts": match_result.contact_match.open_contract_ids,
                },
            },
        ))
        db.commit()
    finally:
        db.close()


def _run_extraction(
    document_id: uuid.UUID,
    workflow_id: uuid.UUID,
    user_id: uuid.UUID,
    user_email: str,
) -> None:
    """Ruft Claude auf und speichert Extraktion. Triggert danach automatisch Matching."""
    db: Session = SessionLocal()
    should_match = False
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            return
        workflow = (
            db.query(Workflow).filter(Workflow.id == workflow_id).first()
        )
        if workflow is None:
            doc.status = "failed"
            db.add(
                Extraction(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    model="",
                    prompt_version="unknown",
                    status="failed",
                    error="Workflow-Eintrag nicht gefunden.",
                )
            )
            db.commit()
            return

        pdf_path = UPLOAD_DIR / doc.stored_path
        if not pdf_path.exists():
            doc.status = "failed"
            db.add(
                Extraction(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    model=workflow.model,
                    prompt_version=workflow.key,
                    status="failed",
                    error=f"PDF fehlt im Storage: {pdf_path}",
                )
            )
            db.commit()
            return

        doc.status = "extracting"
        db.commit()

        try:
            result = extract_mandate_from_pdf(pdf_path.read_bytes(), workflow)
        except Exception as exc:  # noqa: BLE001
            doc.status = "failed"
            db.add(
                Extraction(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    model=workflow.model,
                    prompt_version=workflow.key,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            db.add(AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                document_id=doc.id,
                entity_type="document",
                entity_id=doc.id,
                user_email=user_email,
                action="document_extraction_failed",
                details_json={"error": f"{type(exc).__name__}: {exc}"},
            ))
            db.commit()
            return

        db.add(
            Extraction(
                id=uuid.uuid4(),
                document_id=doc.id,
                model=result.model,
                prompt_version=result.prompt_version,
                raw_response=result.raw_response,
                extracted=result.data,
                status=result.status,
                error=result.error,
            )
        )
        if result.status == "ok":
            doc.status = "extracted"
            should_match = True
            db.add(AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                document_id=doc.id,
                entity_type="document",
                entity_id=doc.id,
                user_email=user_email,
                action="document_extracted",
                details_json={"model": result.model},
            ))
        elif result.status == "failed":
            doc.status = "failed"
            db.add(AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                document_id=doc.id,
                entity_type="document",
                entity_id=doc.id,
                user_email=user_email,
                action="document_extraction_failed",
                details_json={"error": result.error},
            ))
        else:
            doc.status = "needs_review"
            db.add(AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                document_id=doc.id,
                entity_type="document",
                entity_id=doc.id,
                user_email=user_email,
                action="document_needs_review",
                details_json={"reason": result.error or "Extraktion unvollständig"},
            ))
        db.commit()
    finally:
        db.close()

    # Matching startet im selben Thread nachdem DB-Session geschlossen ist
    if should_match:
        _run_matching(document_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def list_documents(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wf_ids = accessible_workflow_ids(db, user)
    if not wf_ids:
        docs: list[Document] = []
    else:
        query = (
            db.query(Document)
            .filter(Document.workflow_id.in_(wf_ids))
            .order_by(Document.uploaded_at.desc())
        )
        if not has_permission(user, "documents:view_all"):
            query = query.filter(Document.uploaded_by_id == user.id)
        docs = query.all()
    return templates.TemplateResponse(
        request,
        "documents_list.html",
        {
            "title": "Dokumente",
            "user": user,
            "documents": docs,
        },
    )


@router.post("/")
async def upload_document(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Nicht unterstuetzter Dateityp: {file.content_type or 'unbekannt'} (erlaubt: PDF).",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datei ist leer.",
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Datei ist zu gross (max {settings.max_upload_mb} MB).",
        )
    if not content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datei scheint kein PDF zu sein (Header fehlt).",
        )

    workflow = _load_default_workflow(db)
    if not can_access_workflow(db, user, workflow):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Keine Berechtigung für Workflow '{workflow.key}'.",
        )

    sha256 = hashlib.sha256(content).hexdigest()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = f"{sha256}.pdf"
    target = UPLOAD_DIR / stored_path
    if not target.exists():
        target.write_bytes(content)

    doc = Document(
        id=uuid.uuid4(),
        uploaded_by_id=user.id,
        workflow_id=workflow.id,
        original_filename=file.filename or "unbenannt.pdf",
        stored_path=stored_path,
        content_type="application/pdf",
        size_bytes=len(content),
        sha256=sha256,
        status="uploaded",
    )
    db.add(doc)
    db.flush()
    audit(
        db,
        user,
        "document_uploaded",
        entity_type="document",
        entity_id=doc.id,
        document_id=doc.id,
        details={
            "filename": doc.original_filename,
            "size_bytes": doc.size_bytes,
            "sha256": sha256,
            "workflow": workflow.key,
        },
        request=request,
    )
    db.commit()
    db.refresh(doc)

    background.add_task(
        _run_extraction, doc.id, workflow.id, user.id, user.email
    )

    return RedirectResponse(
        url=f"/documents/{doc.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{document_id}", response_class=HTMLResponse)
async def document_detail(
    document_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = _load_doc_for_user(db, user, document_id)

    extraction = (
        db.query(Extraction)
        .filter(Extraction.document_id == doc.id)
        .order_by(Extraction.created_at.desc())
        .first()
    )
    chat_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.document_id == doc.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "document_detail.html",
        {
            "title": doc.original_filename,
            "user": user,
            "document": doc,
            "extraction": extraction,
            "chat_messages": chat_messages,
        },
    )


@router.post("/{document_id}/approve")
async def approve_document(
    background: BackgroundTasks,
    document_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "documents:approve"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:approve",
        )
    doc = _load_doc_for_user(db, user, document_id)
    if doc.status not in _APPROVABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Status '{doc.status}' kann nicht freigegeben werden.",
        )

    audit(
        db,
        user,
        "document_approved",
        entity_type="document",
        entity_id=doc.id,
        document_id=doc.id,
        details={"previous_status": doc.status},
        request=request,
    )
    doc.status = "approved"
    db.commit()

    background.add_task(_run_write, doc.id, user.email, user.id)

    return RedirectResponse(
        url=f"/documents/{doc.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{document_id}/chat", response_class=HTMLResponse)
async def chat(
    document_id: uuid.UUID,
    request: Request,
    message: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = _load_doc_for_user(db, user, document_id)

    text = message.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Leere Nachricht."
        )

    pdf_path = UPLOAD_DIR / doc.stored_path
    if not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF-Datei fehlt im Storage.",
        )

    prior_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.document_id == doc.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    current_extraction = (
        db.query(Extraction)
        .filter(Extraction.document_id == doc.id)
        .order_by(Extraction.created_at.desc())
        .first()
    )

    db.add(
        ChatMessage(
            id=uuid.uuid4(),
            document_id=doc.id,
            role="user",
            content=text,
        )
    )
    audit(
        db,
        user,
        "document_chat_message",
        entity_type="document",
        entity_id=doc.id,
        document_id=doc.id,
        details={"message": text},
        request=request,
    )
    db.flush()

    workflow = _load_default_workflow(db)
    history = [{"role": m.role, "content": m.content} for m in prior_messages]
    result = chat_about_mandate(
        pdf_bytes=pdf_path.read_bytes(),
        workflow=workflow,
        current_extraction=current_extraction.extracted if current_extraction else None,
        history=history,
        new_user_message=text,
    )

    new_extraction: Extraction | None = None
    if result.updated_extraction and not result.error:
        new_extraction = Extraction(
            id=uuid.uuid4(),
            document_id=doc.id,
            model=result.model,
            prompt_version=f"{result.prompt_version}-chat",
            raw_response=result.assistant_text or "",
            extracted=result.updated_extraction,
            status="ok",
        )
        db.add(new_extraction)
        db.flush()
        # Chat-Korrekturen: Status zurück auf extracted damit Matching neu läuft,
        # und die veralteten Matching/Write-Ergebnisse raus damit die UI sauber bleibt.
        if doc.status in {"matched", "needs_review", "error", "written", "already_present"}:
            doc.status = "extracted"
        doc.matching_result = None
        doc.impower_result = None

    if result.error:
        assistant_content = f"[Fehler] {result.error}"
    elif result.assistant_text:
        assistant_content = result.assistant_text
    else:
        assistant_content = "(leere Antwort)"

    db.add(
        ChatMessage(
            id=uuid.uuid4(),
            document_id=doc.id,
            role="assistant",
            content=assistant_content,
            extraction_id=new_extraction.id if new_extraction else None,
        )
    )
    db.commit()

    all_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.document_id == doc.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "_chat_response.html",
        {
            "user": user,
            "document": doc,
            "extraction": new_extraction or current_extraction,
            "chat_messages": all_messages,
            "extraction_oob": new_extraction is not None,
        },
    )


@router.get("/{document_id}/status", response_class=HTMLResponse)
async def document_status_fragment(
    document_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HTMX-Polling-Endpoint: liefert den Status-/Extraktions-Block."""
    doc = _load_doc_for_user(db, user, document_id)

    extraction = (
        db.query(Extraction)
        .filter(Extraction.document_id == doc.id)
        .order_by(Extraction.created_at.desc())
        .first()
    )
    return templates.TemplateResponse(
        request,
        "_extraction_block.html",
        {
            "user": user,
            "document": doc,
            "extraction": extraction,
        },
    )


@router.get("/{document_id}/file")
async def document_file(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = _load_doc_for_user(db, user, document_id)
    path = UPLOAD_DIR / doc.stored_path
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    filename_encoded = quote(doc.original_filename)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{filename_encoded}",
        },
    )


# ---------------------------------------------------------------------------
# Inline-Edit fuer Extraktionsfelder
# ---------------------------------------------------------------------------


def _check_field_edit_permission(user: User, field: str) -> None:
    if not has_permission(user, "documents:approve"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:approve",
        )
    if field not in EDITABLE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Feld '{field}' ist nicht editierbar.",
        )


def _latest_extraction(db: Session, doc: Document) -> Extraction | None:
    return (
        db.query(Extraction)
        .filter(Extraction.document_id == doc.id)
        .order_by(Extraction.created_at.desc())
        .first()
    )


@router.get("/{document_id}/extraction/edit", response_class=HTMLResponse)
async def extraction_field_edit_form(
    document_id: uuid.UUID,
    request: Request,
    field: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Liefert das Inline-Edit-Form-Fragment fuer ein einzelnes Feld."""
    doc = _load_doc_for_user(db, user, document_id)
    _check_field_edit_permission(user, field)
    if doc.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Status '{doc.status}' kann nicht editiert werden.",
        )
    extraction = _latest_extraction(db, doc)
    if extraction is None or not extraction.extracted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine Extraktion vorhanden — Edit nicht möglich.",
        )
    current_value = extraction.extracted.get(field)
    return templates.TemplateResponse(
        request,
        "_extraction_field_edit.html",
        {
            "doc_id": doc.id,
            "key": field,
            "label": _EXTRACTION_FIELD_LABELS.get(field, field),
            "value": current_value,
            "form_error": None,
        },
    )


# v2-TODO: documents:approve-Check ergaenzen (siehe deferred-work.md #81). Information-Disclosure-Risiko aktuell minimal — der Wert ist auf der Detail-Page ohnehin sichtbar.
@router.get("/{document_id}/extraction/view", response_class=HTMLResponse)
async def extraction_field_view_fragment(
    document_id: uuid.UUID,
    request: Request,
    field: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Liefert das Read-Only-View-Fragment fuer ein einzelnes Feld (Cancel-Pfad)."""
    doc = _load_doc_for_user(db, user, document_id)
    if field not in EDITABLE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Feld '{field}' ist nicht editierbar.",
        )
    extraction = _latest_extraction(db, doc)
    current_value = (
        extraction.extracted.get(field) if extraction and extraction.extracted else None
    )
    editable = (
        doc.status in EDITABLE_STATUSES
        and has_permission(user, "documents:approve")
    )
    return templates.TemplateResponse(
        request,
        "_extraction_field_view.html",
        {
            "doc_id": doc.id,
            "key": field,
            "label": _EXTRACTION_FIELD_LABELS.get(field, field),
            "value": current_value,
            "editable": editable,
        },
    )


@router.post("/{document_id}/extraction/field", response_class=HTMLResponse)
async def extraction_field_save(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    field: str = Form(...),
    value: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persistiert einen einzelnen Feld-Edit. Triggert anschliessend Re-Match.

    Bei Validierungsfehler: rendert die Edit-Form mit Inline-Fehler neu
    (HTTP 200, weil HTMX 2.x Default-Config 4xx-Responses NICHT swappt;
    der semantische 422-Fehler wird nur ueber den Edit-Form-Re-Render an
    den User kommuniziert — siehe Spec Change Log).
    Bei No-Op (Wert unveraendert): kein Re-Match-Trigger, Block re-rendert
    aber sauber, damit die Cell von Edit-Form zurueck auf View springt.
    Bei Erfolg: rendert den ganzen `_extraction_block.html` neu (Whole-Block-Swap)
    und triggert `_run_matching` als BackgroundTask.
    """
    doc = _load_doc_for_user(db, user, document_id)
    _check_field_edit_permission(user, field)

    # Row-Lock serialisiert parallele Field-Saves auf demselben Dokument
    # (Concurrent-Save-Race, Defer #77). Lock haelt bis db.commit().
    db.execute(select(Document).where(Document.id == document_id).with_for_update())
    # Nach Lock-Erwerb doc-State neu laden (status/workflow lesen) — sonst
    # entscheidet update_extraction_field auf einem Pre-Lock-Snapshot.
    db.refresh(doc)

    try:
        new_extraction = update_extraction_field(db, doc, field, value, user, request)
        db.commit()
    except FieldValidationError as exc:
        # Edit-Form mit Inline-Fehler neu rendern (Cell-Swap). HTTP 200, damit
        # HTMX die Antwort tatsaechlich in den DOM swappt.
        db.rollback()
        return templates.TemplateResponse(
            request,
            "_extraction_field_edit.html",
            {
                "doc_id": doc.id,
                "key": field,
                "label": _EXTRACTION_FIELD_LABELS.get(field, field),
                "value": value,
                "submitted_value": value,
                "form_error": exc.detail,
            },
        )

    # Re-Match nur bei tatsaechlicher Aenderung — bei No-Op spart das einen
    # ungewollten Impower-Roundtrip + verhindert eine Race auf doc.matching_result.
    if new_extraction is not None:
        background.add_task(_run_matching, doc.id)

    # Whole-Block-Swap: Status-Pill, Pen-Icons, Matching-Bereich werden
    # konsistent neu gerendert.
    db.refresh(doc)
    extraction = _latest_extraction(db, doc)
    return templates.TemplateResponse(
        request,
        "_extraction_block.html",
        {
            "user": user,
            "document": doc,
            "extraction": extraction,
        },
    )
