"""Cases — Multi-Doc-Fall-Container fuer die Mietverwaltungs-Anlage.

Ein Case bundelt n PDFs zu einem fachlichen Vorgang. Paket 4 verdrahtet
die Classify+Extract-Pipeline pro Doc (Claude) + den Merge in ``case.state``.
Form-UI (Paket 5), Write-Pfad (Paket 7) und Chat (Paket 8) kommen spaeter.
"""
from __future__ import annotations

import hashlib
import uuid
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
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Case, ChatMessage, Document, Extraction, User, Workflow
from app.permissions import (
    RESOURCE_TYPE_WORKFLOW,
    can_access_resource,
    has_permission,
)
from app.services.audit import audit
from app.services.mietverwaltung import (
    chat_about_case,
    classify_document,
    extract_for_doc_type,
    merge_case_state,
)
from app.services.mietverwaltung_write import preflight, run_mietverwaltung_write
from app.templating import templates

MIETVERWALTUNG_WORKFLOW_KEY = "mietverwaltung_setup"

# Benutzer-sichtbare Doc-Typen fuer die Mietverwaltungs-Anlage.
# Leerer Wert (= null) heisst "noch nicht klassifiziert".
DOC_TYPES: list[tuple[str, str]] = [
    ("verwaltervertrag", "Verwaltervertrag"),
    ("grundbuch", "Grundbuchauszug"),
    ("mietvertrag", "Mietvertrag"),
    ("mieterliste", "Mieterliste / Flaechenliste"),
    ("sonstiges", "Sonstiges"),
]
VALID_DOC_TYPES: frozenset[str] = frozenset(k for k, _ in DOC_TYPES)


router = APIRouter(prefix="/cases", tags=["cases"])

MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf"}
UPLOAD_DIR = Path(settings.uploads_dir)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _load_mietverwaltung_workflow(db: Session) -> Workflow:
    wf = (
        db.query(Workflow)
        .filter(Workflow.key == MIETVERWALTUNG_WORKFLOW_KEY)
        .first()
    )
    if wf is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow '{MIETVERWALTUNG_WORKFLOW_KEY}' nicht gefunden.",
        )
    return wf


def _load_case_for_user(db: Session, user: User, case_id: uuid.UUID) -> Case:
    """Laedt einen Case und prueft Workflow-/Eigentuemer-Zugriff."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not can_access_resource(
        db, user, RESOURCE_TYPE_WORKFLOW, case.workflow_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if (
        case.created_by_id != user.id
        and not has_permission(user, "documents:view_all")
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return case


def _load_case_document(db: Session, case: Case, doc_id: uuid.UUID) -> Document:
    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.case_id == case.id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return doc


# ---------------------------------------------------------------------------
# Extract-Pipeline (Paket 4)
# ---------------------------------------------------------------------------

def _recompute_case_state_and_status(db: Session, case: Case) -> None:
    """Baut ``case.state`` neu aus allen jeweils neuesten OK-Extractions der
    zugeordneten Dokumente und aktualisiert ``case.status`` entsprechend.

    Case-Status-Rollup:
    - irgendein Doc noch ``uploaded`` oder ``extracting``   → ``extracting``
    - mindestens ein Doc ``extracted`` und kein Doc ``extracting`` → ``ready_for_review``
    - nur ``failed`` / ``needs_review`` / keine Docs       → ``draft`` (oder ``ready_for_review``
      falls trotzdem was extrahiert wurde)
    """
    docs = (
        db.query(Document)
        .filter(Document.case_id == case.id)
        .order_by(Document.uploaded_at.asc())
        .all()
    )

    # Pro Doc die neueste usable Extraction ziehen (doc_type aus doc, damit
    # Nutzer umklassifizieren kann). Sowohl "ok" als auch "needs_review"
    # nehmen — Teilerkennungen sind besser als gar nichts im Case-State.
    extraction_entries: list[dict] = []
    for doc in docs:
        if not doc.doc_type:
            continue
        latest = (
            db.query(Extraction)
            .filter(
                Extraction.document_id == doc.id,
                Extraction.status.in_(["ok", "needs_review"]),
            )
            .order_by(Extraction.created_at.desc())
            .first()
        )
        if latest is None or not latest.extracted:
            continue
        extraction_entries.append(
            {
                "doc_id": doc.id,
                "doc_type": doc.doc_type,
                "status": latest.status,
                "data": latest.extracted,
            }
        )

    # Overrides aus bisherigem State fischen und beim Remerge weiterreichen.
    prev_overrides = (case.state or {}).get("_overrides") or {}
    case.state = merge_case_state(extraction_entries, overrides=prev_overrides)

    # Status-Rollup
    has_pending = any(d.status in {"uploaded", "extracting"} for d in docs)
    has_extracted = any(d.status == "extracted" for d in docs)
    if has_pending:
        case.status = "extracting"
    elif has_extracted:
        case.status = "ready_for_review"
    else:
        case.status = "draft" if not docs else "ready_for_review"


def _run_case_extraction(case_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    """BackgroundTask: klassifiziert (falls doc_type leer) + extrahiert +
    merged Case-State. Laeuft pro Dokument, idempotent, DB-Session eigens."""
    db: Session = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        case = db.query(Case).filter(Case.id == case_id).first()
        if doc is None or case is None:
            return

        workflow = (
            db.query(Workflow).filter(Workflow.id == case.workflow_id).first()
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
        case.status = "extracting"
        db.commit()

        pdf_bytes = pdf_path.read_bytes()

        # Classify, wenn doc_type leer
        if not doc.doc_type:
            cresult = classify_document(pdf_bytes, workflow)
            if cresult.doc_type:
                doc.doc_type = cresult.doc_type
                audit(
                    db,
                    user=None,
                    action="case_document_classified",
                    entity_type="case",
                    entity_id=case.id,
                    document_id=doc.id,
                    details={
                        "doc_type": cresult.doc_type,
                        "model": cresult.model,
                        "confidence": cresult.confidence,
                        "reason": cresult.reason,
                    },
                    user_email="system",
                )
                db.commit()
            else:
                doc.status = "needs_review"
                db.add(
                    Extraction(
                        id=uuid.uuid4(),
                        document_id=doc.id,
                        model=cresult.model,
                        prompt_version=f"{workflow.key}-classify",
                        raw_response=cresult.raw_response,
                        status="failed",
                        error=cresult.error or "Doc-Typ nicht erkannt.",
                    )
                )
                db.commit()
                _recompute_case_state_and_status(db, case)
                db.commit()
                return

        # Extract
        try:
            eresult = extract_for_doc_type(pdf_bytes, workflow, doc.doc_type)
        except Exception as exc:  # noqa: BLE001
            doc.status = "failed"
            db.add(
                Extraction(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    model=workflow.model,
                    prompt_version=f"{workflow.key}-{doc.doc_type}",
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            db.commit()
            _recompute_case_state_and_status(db, case)
            db.commit()
            return

        db.add(
            Extraction(
                id=uuid.uuid4(),
                document_id=doc.id,
                model=eresult.model,
                prompt_version=eresult.prompt_version,
                raw_response=eresult.raw_response,
                extracted=eresult.data,
                status=eresult.status,
                error=eresult.error,
            )
        )
        if eresult.status == "ok":
            doc.status = "extracted"
            action = "case_document_extracted"
        elif eresult.status == "failed":
            doc.status = "failed"
            action = "case_document_extraction_failed"
        else:
            doc.status = "needs_review"
            action = "case_document_needs_review"
        audit(
            db,
            user=None,
            action=action,
            entity_type="case",
            entity_id=case.id,
            document_id=doc.id,
            details={
                "doc_type": doc.doc_type,
                "model": eresult.model,
                "status": eresult.status,
                "error": eresult.error,
            },
            user_email="system",
        )
        db.commit()

        _recompute_case_state_and_status(db, case)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def list_cases(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workflow = _load_mietverwaltung_workflow(db)
    if not can_access_resource(
        db, user, RESOURCE_TYPE_WORKFLOW, workflow.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Keine Berechtigung fuer Workflow '{workflow.key}'.",
        )

    query = (
        db.query(Case)
        .filter(Case.workflow_id == workflow.id)
        .order_by(Case.created_at.desc())
    )
    if not has_permission(user, "documents:view_all"):
        query = query.filter(Case.created_by_id == user.id)
    cases = query.all()

    # Anzahl Dokumente pro Case sammeln (eine Query)
    case_ids = [c.id for c in cases]
    doc_counts: dict[uuid.UUID, int] = {}
    if case_ids:
        rows = (
            db.query(Document.case_id, Document.id)
            .filter(Document.case_id.in_(case_ids))
            .all()
        )
        for case_id, _ in rows:
            doc_counts[case_id] = doc_counts.get(case_id, 0) + 1

    return templates.TemplateResponse(
        request,
        "cases_list.html",
        {
            "title": "Mietverwaltung",
            "user": user,
            "workflow": workflow,
            "cases": cases,
            "doc_counts": doc_counts,
        },
    )


@router.post("/")
async def create_case(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )
    workflow = _load_mietverwaltung_workflow(db)
    if not can_access_resource(
        db, user, RESOURCE_TYPE_WORKFLOW, workflow.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Keine Berechtigung fuer Workflow '{workflow.key}'.",
        )

    case = Case(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        created_by_id=user.id,
        name=None,
        status="draft",
        state={},
    )
    db.add(case)
    db.flush()
    audit(
        db,
        user,
        "case_created",
        entity_type="case",
        entity_id=case.id,
        details={"workflow": workflow.key},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url=f"/cases/{case.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{case_id}", response_class=HTMLResponse)
async def case_detail(
    case_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case = _load_case_for_user(db, user, case_id)
    documents = (
        db.query(Document)
        .filter(Document.case_id == case.id)
        .order_by(Document.uploaded_at.asc())
        .all()
    )
    # Pro Doc die neueste Extraction mitgeben — fuer Error-/Needs-Review-Anzeige
    extractions_by_doc: dict[uuid.UUID, Extraction] = {}
    if documents:
        doc_ids = [d.id for d in documents]
        rows = (
            db.query(Extraction)
            .filter(Extraction.document_id.in_(doc_ids))
            .order_by(Extraction.created_at.desc())
            .all()
        )
        for e in rows:
            extractions_by_doc.setdefault(e.document_id, e)

    chat_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.case_id == case.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "case_detail.html",
        {
            "title": case.name or "Neuer Fall",
            "user": user,
            "case": case,
            "documents": documents,
            "doc_types": DOC_TYPES,
            "extractions_by_doc": extractions_by_doc,
            "chat_messages": chat_messages,
        },
    )


@router.post("/{case_id}/name")
async def rename_case(
    case_id: uuid.UUID,
    request: Request,
    name: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case = _load_case_for_user(db, user, case_id)
    cleaned = name.strip()
    case.name = cleaned or None
    audit(
        db,
        user,
        "case_renamed",
        entity_type="case",
        entity_id=case.id,
        details={"name": case.name},
        request=request,
    )
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/documents")
async def upload_case_document(
    case_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )
    case = _load_case_for_user(db, user, case_id)

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Nicht unterstuetzter Dateityp: "
                f"{file.content_type or 'unbekannt'} (erlaubt: PDF)."
            ),
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Datei ist leer."
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

    doc_type_clean: str | None = doc_type.strip() or None
    if doc_type_clean is not None and doc_type_clean not in VALID_DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannter doc_type: {doc_type_clean}",
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
        workflow_id=case.workflow_id,
        case_id=case.id,
        doc_type=doc_type_clean,
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
        "case_document_uploaded",
        entity_type="case",
        entity_id=case.id,
        document_id=doc.id,
        details={
            "filename": doc.original_filename,
            "size_bytes": doc.size_bytes,
            "sha256": sha256,
            "doc_type": doc_type_clean,
        },
        request=request,
    )
    db.commit()

    background.add_task(_run_case_extraction, case.id, doc.id)

    return RedirectResponse(
        url=f"/cases/{case.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/documents/{doc_id}/type")
async def set_document_type(
    case_id: uuid.UUID,
    doc_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    doc_type: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case = _load_case_for_user(db, user, case_id)
    doc = _load_case_document(db, case, doc_id)

    doc_type_clean: str | None = doc_type.strip() or None
    if doc_type_clean is not None and doc_type_clean not in VALID_DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannter doc_type: {doc_type_clean}",
        )
    previous = doc.doc_type
    doc.doc_type = doc_type_clean
    audit(
        db,
        user,
        "case_document_type_changed",
        entity_type="case",
        entity_id=case.id,
        document_id=doc.id,
        details={"previous": previous, "new": doc_type_clean},
        request=request,
    )
    # Typ-Wechsel = Re-Extract. Auch Klassifizierung von null auf einen Typ.
    if doc_type_clean and doc_type_clean != previous:
        doc.status = "uploaded"
        db.commit()
        background.add_task(_run_case_extraction, case.id, doc.id)
    else:
        db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/documents/{doc_id}/extract")
async def rerun_document_extraction(
    case_id: uuid.UUID,
    doc_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manueller Trigger: Extract-Pipeline fuer ein einzelnes Dokument neu."""
    case = _load_case_for_user(db, user, case_id)
    doc = _load_case_document(db, case, doc_id)
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )
    doc.status = "uploaded"
    audit(
        db,
        user,
        "case_document_rerun_extraction",
        entity_type="case",
        entity_id=case.id,
        document_id=doc.id,
        details={"doc_type": doc.doc_type},
        request=request,
    )
    db.commit()
    background.add_task(_run_case_extraction, case.id, doc.id)
    return RedirectResponse(
        url=f"/cases/{case.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/documents/{doc_id}/delete")
async def delete_case_document(
    case_id: uuid.UUID,
    doc_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user, "documents:delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:delete",
        )
    case = _load_case_for_user(db, user, case_id)
    doc = _load_case_document(db, case, doc_id)

    audit(
        db,
        user,
        "case_document_deleted",
        entity_type="case",
        entity_id=case.id,
        document_id=doc.id,
        details={
            "filename": doc.original_filename,
            "doc_type": doc.doc_type,
        },
        request=request,
    )
    db.delete(doc)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{case_id}/documents/{doc_id}/file")
async def case_document_file(
    case_id: uuid.UUID,
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case = _load_case_for_user(db, user, case_id)
    doc = _load_case_document(db, case, doc_id)
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
# State-Edit-Routes (Paket 5)
# ---------------------------------------------------------------------------

def _require_case_edit(user: User) -> None:
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )


def _mutate_overrides(case: Case, mutator) -> None:
    """Uebernimmt die Override-Mutation + Recompute in einer Transaktion.

    `mutator` bekommt das ``overrides``-Dict und mutiert es inplace. JSONB braucht
    eine komplette Reassignment auf ``case.state``, damit SQLAlchemy die Aenderung
    mitbekommt (kein flag_modified noetig dann).
    """
    state = dict(case.state or {})
    overrides = dict(state.get("_overrides") or {})
    mutator(overrides)
    state["_overrides"] = overrides
    case.state = state


def _apply_flat_section(
    overrides: dict, section: str, fields: dict[str, str | None]
) -> None:
    """Setzt Override-Felder fuer eine flache Sektion (property, management, ...).

    Leerer String/None = Override entfernen (auf Auto zurueckfallen).
    """
    existing = dict(overrides.get(section) or {})
    for key, value in fields.items():
        if value is None or value == "":
            existing.pop(key, None)
        else:
            existing[key] = value
    if existing:
        overrides[section] = existing
    else:
        overrides.pop(section, None)


def _to_float(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _to_int(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.post("/{case_id}/state/property")
async def save_state_property(
    case_id: uuid.UUID,
    request: Request,
    number: str = Form(""),
    name: str = Form(""),
    street: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    creditor_id: str = Form(""),
    land_registry_district: str = Form(""),
    folio_number: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)

    fields = {
        "number": number.strip() or None,
        "name": name.strip() or None,
        "street": street.strip() or None,
        "postal_code": postal_code.strip() or None,
        "city": city.strip() or None,
        "country": (country.strip() or None),
        "creditor_id": creditor_id.strip() or None,
        "land_registry_district": land_registry_district.strip() or None,
        "folio_number": folio_number.strip() or None,
    }
    _mutate_overrides(case, lambda o: _apply_flat_section(o, "property", fields))
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "property"}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-property",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/management")
async def save_state_management(
    case_id: uuid.UUID,
    request: Request,
    management_company_name: str = Form(""),
    supervisor_name: str = Form(""),
    accountant_name: str = Form(""),
    contract_start_date: str = Form(""),
    contract_end_date: str = Form(""),
    dunning_fee_net: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)

    fields: dict[str, str | float | None] = {
        "management_company_name": management_company_name.strip() or None,
        "supervisor_name": supervisor_name.strip() or None,
        "accountant_name": accountant_name.strip() or None,
        "contract_start_date": contract_start_date.strip() or None,
        "contract_end_date": contract_end_date.strip() or None,
        "dunning_fee_net": _to_float(dunning_fee_net),
    }
    _mutate_overrides(
        case, lambda o: _apply_flat_section(o, "management_contract", fields)
    )
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "management_contract"}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-management",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/billing")
async def save_state_billing(
    case_id: uuid.UUID,
    request: Request,
    is_same_as_owner: str = Form(""),
    street: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)

    same = is_same_as_owner.strip().lower() in {"1", "true", "on", "yes"}
    # Checkbox aktiv: abweichende Adress-Felder verwerfen
    fields: dict[str, str | bool | None] = {
        "is_same_as_owner": same,
        "street": None if same else (street.strip() or None),
        "postal_code": None if same else (postal_code.strip() or None),
        "city": None if same else (city.strip() or None),
    }
    _mutate_overrides(
        case, lambda o: _apply_flat_section(o, "billing_address", fields)
    )
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "billing_address"}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-billing",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/owner")
async def save_state_owner(
    case_id: uuid.UUID,
    request: Request,
    type: str = Form("PERSON"),
    salutation: str = Form(""),
    title: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    company_name: str = Form(""),
    trade_register_number: str = Form(""),
    street: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)

    owner_type = (type or "PERSON").strip().upper()
    if owner_type not in {"PERSON", "COMPANY", "MANAGEMENT_COMPANY"}:
        owner_type = "PERSON"

    fields: dict[str, str | None] = {
        "type": owner_type,
        "salutation": salutation.strip() or None,
        "title": title.strip() or None,
        "first_name": first_name.strip() or None,
        "last_name": last_name.strip() or None,
        "company_name": company_name.strip() or None,
        "trade_register_number": trade_register_number.strip() or None,
        "street": street.strip() or None,
        "postal_code": postal_code.strip() or None,
        "city": city.strip() or None,
        "country": country.strip() or None,
    }
    _mutate_overrides(case, lambda o: _apply_flat_section(o, "owner", fields))
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "owner"}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-owner",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# -- Gebaeude: Add / Rename / Delete ----------------------------------------

def _bootstrap_list_override(case: Case, section: str) -> list[dict]:
    """Holt die aktuelle Liste (Auto oder bereits Override) und stellt sicher,
    dass sie ab jetzt als Override persistiert wird."""
    current = list(case.state.get(section) or []) if case.state else []
    return [dict(item) for item in current]


@router.post("/{case_id}/state/buildings/add")
async def add_building(
    case_id: uuid.UUID,
    request: Request,
    name: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)
    clean = name.strip()
    if not clean:
        return RedirectResponse(
            url=f"/cases/{case.id}#sec-buildings",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    def mutator(o: dict) -> None:
        items = o.get("buildings")
        if items is None:
            items = _bootstrap_list_override(case, "buildings")
        if not any((b or {}).get("name") == clean for b in items):
            items.append({"name": clean})
        o["buildings"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "buildings", "op": "add", "name": clean}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-buildings",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/buildings/{idx}/delete")
async def delete_building(
    case_id: uuid.UUID,
    idx: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)

    def mutator(o: dict) -> None:
        items = o.get("buildings")
        if items is None:
            items = _bootstrap_list_override(case, "buildings")
        if 0 <= idx < len(items):
            items.pop(idx)
        o["buildings"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "buildings", "op": "delete", "idx": idx}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-buildings",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# -- Einheiten: Add / Edit / Delete -----------------------------------------

_UNIT_TYPES = ("APARTMENT", "COMMERCIAL", "PARKING", "OTHER")


def _parse_unit_form(
    number: str, unit_type: str, building_name: str,
    floor: str, position: str, living_area: str,
    heating_area: str, persons: str, tenant_name: str,
    cold_rent: str, operating_costs: str, heating_costs: str,
) -> dict:
    ut = (unit_type or "").strip().upper() or None
    if ut and ut not in _UNIT_TYPES:
        ut = None
    return {
        "number": number.strip() or None,
        "unit_type": ut,
        "building_name": building_name.strip() or None,
        "floor": floor.strip() or None,
        "position": position.strip() or None,
        "living_area": _to_float(living_area),
        "heating_area": _to_float(heating_area),
        "persons": _to_int(persons),
        "tenant_name": tenant_name.strip() or None,
        "cold_rent": _to_float(cold_rent),
        "operating_costs": _to_float(operating_costs),
        "heating_costs": _to_float(heating_costs),
    }


@router.post("/{case_id}/state/units/add")
async def add_unit(
    case_id: uuid.UUID,
    request: Request,
    number: str = Form(""),
    unit_type: str = Form(""),
    building_name: str = Form(""),
    floor: str = Form(""),
    position: str = Form(""),
    living_area: str = Form(""),
    heating_area: str = Form(""),
    persons: str = Form(""),
    tenant_name: str = Form(""),
    cold_rent: str = Form(""),
    operating_costs: str = Form(""),
    heating_costs: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)
    payload = _parse_unit_form(
        number, unit_type, building_name, floor, position,
        living_area, heating_area, persons, tenant_name,
        cold_rent, operating_costs, heating_costs,
    )
    if not payload["number"]:
        return RedirectResponse(
            url=f"/cases/{case.id}#sec-units",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    def mutator(o: dict) -> None:
        items = o.get("units")
        if items is None:
            items = _bootstrap_list_override(case, "units")
        items.append({k: v for k, v in payload.items() if v is not None})
        o["units"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "units", "op": "add", "number": payload["number"]},
        request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-units",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/units/{idx}")
async def edit_unit(
    case_id: uuid.UUID,
    idx: int,
    request: Request,
    number: str = Form(""),
    unit_type: str = Form(""),
    building_name: str = Form(""),
    floor: str = Form(""),
    position: str = Form(""),
    living_area: str = Form(""),
    heating_area: str = Form(""),
    persons: str = Form(""),
    tenant_name: str = Form(""),
    cold_rent: str = Form(""),
    operating_costs: str = Form(""),
    heating_costs: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)
    payload = _parse_unit_form(
        number, unit_type, building_name, floor, position,
        living_area, heating_area, persons, tenant_name,
        cold_rent, operating_costs, heating_costs,
    )

    def mutator(o: dict) -> None:
        items = o.get("units")
        if items is None:
            items = _bootstrap_list_override(case, "units")
        if 0 <= idx < len(items):
            items[idx] = {k: v for k, v in payload.items() if v is not None}
        o["units"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "units", "op": "edit", "idx": idx}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-units",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/units/{idx}/delete")
async def delete_unit(
    case_id: uuid.UUID,
    idx: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)

    def mutator(o: dict) -> None:
        items = o.get("units")
        if items is None:
            items = _bootstrap_list_override(case, "units")
        if 0 <= idx < len(items):
            items.pop(idx)
        o["units"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "units", "op": "delete", "idx": idx}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-units",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# -- Mietvertraege: Add / Edit / Delete -------------------------------------

_DEPOSIT_TYPES = ("CASH", "GUARANTEE", "DEPOSIT_ACCOUNT")
_PAYMENT_METHODS = ("SELF_PAYER", "DIRECT_DEBIT")


def _parse_tenant_contract_form(
    unit_number: str,
    tenant_type: str,
    tenant_salutation: str,
    tenant_first_name: str,
    tenant_last_name: str,
    tenant_company_name: str,
    tenant_email: str,
    tenant_phone: str,
    signed_date: str,
    start_date: str,
    end_date: str,
    vat_relevant: str,
    cold_rent: str,
    operating_costs: str,
    heating_costs: str,
    total_rent: str,
    deposit: str,
    deposit_type: str,
    deposit_due_date: str,
    payment_method: str,
    iban: str,
    bic: str,
) -> dict:
    ttype = (tenant_type or "PERSON").strip().upper()
    if ttype not in {"PERSON", "COMPANY"}:
        ttype = "PERSON"
    dt = (deposit_type or "").strip().upper() or None
    if dt and dt not in _DEPOSIT_TYPES:
        dt = None
    pm = (payment_method or "").strip().upper() or None
    if pm and pm not in _PAYMENT_METHODS:
        pm = None
    vat = vat_relevant.strip().lower() in {"1", "true", "on", "yes"}

    tenant = {
        "type": ttype,
        "salutation": tenant_salutation.strip() or None,
        "first_name": tenant_first_name.strip() or None,
        "last_name": tenant_last_name.strip() or None,
        "company_name": tenant_company_name.strip() or None,
        "email": tenant_email.strip() or None,
        "phone": tenant_phone.strip() or None,
    }
    contract = {
        "signed_date": signed_date.strip() or None,
        "start_date": start_date.strip() or None,
        "end_date": end_date.strip() or None,
        "vat_relevant": vat,
        "cold_rent": _to_float(cold_rent),
        "operating_costs": _to_float(operating_costs),
        "heating_costs": _to_float(heating_costs),
        "total_rent": _to_float(total_rent),
        "deposit": _to_float(deposit),
        "deposit_type": dt,
        "deposit_due_date": deposit_due_date.strip() or None,
        "payment_method": pm,
        "iban": iban.strip() or None,
        "bic": bic.strip() or None,
    }
    return {
        "unit_number": unit_number.strip() or None,
        "tenant": {k: v for k, v in tenant.items() if v is not None},
        "contract": {k: v for k, v in contract.items() if v is not None},
    }


@router.post("/{case_id}/state/tenant_contracts/add")
async def add_tenant_contract(
    case_id: uuid.UUID,
    request: Request,
    unit_number: str = Form(""),
    tenant_type: str = Form("PERSON"),
    tenant_salutation: str = Form(""),
    tenant_first_name: str = Form(""),
    tenant_last_name: str = Form(""),
    tenant_company_name: str = Form(""),
    tenant_email: str = Form(""),
    tenant_phone: str = Form(""),
    signed_date: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    vat_relevant: str = Form(""),
    cold_rent: str = Form(""),
    operating_costs: str = Form(""),
    heating_costs: str = Form(""),
    total_rent: str = Form(""),
    deposit: str = Form(""),
    deposit_type: str = Form(""),
    deposit_due_date: str = Form(""),
    payment_method: str = Form(""),
    iban: str = Form(""),
    bic: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)
    payload = _parse_tenant_contract_form(
        unit_number, tenant_type, tenant_salutation, tenant_first_name,
        tenant_last_name, tenant_company_name, tenant_email, tenant_phone,
        signed_date, start_date, end_date, vat_relevant,
        cold_rent, operating_costs, heating_costs, total_rent,
        deposit, deposit_type, deposit_due_date, payment_method, iban, bic,
    )

    def mutator(o: dict) -> None:
        items = o.get("tenant_contracts")
        if items is None:
            items = _bootstrap_list_override(case, "tenant_contracts")
        items.append(payload)
        o["tenant_contracts"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "tenant_contracts", "op": "add"}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-contracts",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/tenant_contracts/{idx}")
async def edit_tenant_contract(
    case_id: uuid.UUID,
    idx: int,
    request: Request,
    unit_number: str = Form(""),
    tenant_type: str = Form("PERSON"),
    tenant_salutation: str = Form(""),
    tenant_first_name: str = Form(""),
    tenant_last_name: str = Form(""),
    tenant_company_name: str = Form(""),
    tenant_email: str = Form(""),
    tenant_phone: str = Form(""),
    signed_date: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    vat_relevant: str = Form(""),
    cold_rent: str = Form(""),
    operating_costs: str = Form(""),
    heating_costs: str = Form(""),
    total_rent: str = Form(""),
    deposit: str = Form(""),
    deposit_type: str = Form(""),
    deposit_due_date: str = Form(""),
    payment_method: str = Form(""),
    iban: str = Form(""),
    bic: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)
    payload = _parse_tenant_contract_form(
        unit_number, tenant_type, tenant_salutation, tenant_first_name,
        tenant_last_name, tenant_company_name, tenant_email, tenant_phone,
        signed_date, start_date, end_date, vat_relevant,
        cold_rent, operating_costs, heating_costs, total_rent,
        deposit, deposit_type, deposit_due_date, payment_method, iban, bic,
    )

    def mutator(o: dict) -> None:
        items = o.get("tenant_contracts")
        if items is None:
            items = _bootstrap_list_override(case, "tenant_contracts")
        if 0 <= idx < len(items):
            # source_doc_id/_partial-Marker erhalten, falls vorhanden
            prev = items[idx] or {}
            payload["source_doc_id"] = prev.get("source_doc_id")
            items[idx] = payload
        o["tenant_contracts"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "tenant_contracts", "op": "edit", "idx": idx},
        request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-contracts",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/state/tenant_contracts/{idx}/delete")
async def delete_tenant_contract(
    case_id: uuid.UUID,
    idx: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_case_edit(user)
    case = _load_case_for_user(db, user, case_id)

    def mutator(o: dict) -> None:
        items = o.get("tenant_contracts")
        if items is None:
            items = _bootstrap_list_override(case, "tenant_contracts")
        if 0 <= idx < len(items):
            items.pop(idx)
        o["tenant_contracts"] = items

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_saved",
        entity_type="case", entity_id=case.id,
        details={"section": "tenant_contracts", "op": "delete", "idx": idx},
        request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    return RedirectResponse(
        url=f"/cases/{case.id}#sec-contracts",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/write")
async def trigger_mietverwaltung_write(
    case_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Startet den Impower-Write als BackgroundTask. UI pollt via Meta-Refresh,
    bis case.status != writing.

    Preflight-Check laeuft synchron, damit der User Fehler direkt sieht.
    """
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )
    case = _load_case_for_user(db, user, case_id)

    if case.status in {"writing"}:
        # Doppelt drauf klicken soll nichts kaputtmachen.
        return RedirectResponse(
            url=f"/cases/{case.id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    pre = preflight(case.state or {})
    if not pre.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pflichtfelder fehlen: " + ", ".join(pre.missing),
        )

    audit(
        db, user, "mietverwaltung_write_triggered",
        entity_type="case", entity_id=case.id,
        details={
            "property_number": (case.state or {}).get("property", {}).get("number"),
            "units": len((case.state or {}).get("units") or []),
            "tenant_contracts": len((case.state or {}).get("tenant_contracts") or []),
        },
        request=request,
    )
    db.commit()

    background.add_task(run_mietverwaltung_write, case.id)

    return RedirectResponse(
        url=f"/cases/{case.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{case_id}/chat", response_class=HTMLResponse)
async def case_chat(
    case_id: uuid.UUID,
    request: Request,
    message: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Case-Chat: Nachricht an den Agenten + optional Override-Patch anwenden.

    Rendert das Chat-Panel-Fragment zurueck (HTMX-OOB fuer das Form, damit
    Input geleert wird). Wenn Claude einen Patch vorschlaegt, wird er in
    ``case.state['_overrides']`` gemerged und der Case-State neu berechnet.
    """
    case = _load_case_for_user(db, user, case_id)
    if not has_permission(user, "documents:upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: documents:upload",
        )

    msg = (message or "").strip()
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Leere Nachricht.",
        )

    # User-Message persistieren
    db.add(
        ChatMessage(
            id=uuid.uuid4(),
            case_id=case.id,
            role="user",
            content=msg,
        )
    )
    db.flush()

    workflow = (
        db.query(Workflow).filter(Workflow.id == case.workflow_id).first()
    )

    # Historie aus DB laden (inkl. der gerade persistierten User-Message)
    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.case_id == case.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    # Letzte User-Message ist das, was wir gerade an Claude senden — nicht mit
    # in die Historie aufnehmen.
    history = [
        {"role": m.role, "content": m.content}
        for m in history_rows[:-1]
    ]

    documents = (
        db.query(Document)
        .filter(Document.case_id == case.id)
        .order_by(Document.uploaded_at.asc())
        .all()
    )
    docs_summary = [
        {
            "filename": d.original_filename,
            "doc_type": d.doc_type,
            "status": d.status,
        }
        for d in documents
    ]

    result = chat_about_case(
        workflow=workflow,
        case_state=case.state or {},
        documents_summary=docs_summary,
        history=history,
        new_user_message=msg,
    )

    response_text = result.assistant_text
    if result.error:
        response_text = f"[Fehler] {result.error}"

    # Assistant-Message persistieren
    db.add(
        ChatMessage(
            id=uuid.uuid4(),
            case_id=case.id,
            role="assistant",
            content=response_text,
        )
    )
    audit(
        db, user, "case_chat_message",
        entity_type="case", entity_id=case.id,
        details={
            "model": result.model,
            "patch_applied": bool(result.patch),
            "error": result.error,
        },
        request=request,
    )

    # Patch anwenden: Overrides mergen + Recompute
    if result.patch:
        def mutator(o: dict) -> None:
            for key, value in result.patch.items():
                if value is None:
                    continue
                if key in {"property", "management_contract", "billing_address", "owner"}:
                    base = dict(o.get(key) or {})
                    if isinstance(value, dict):
                        base.update(
                            {k: v for k, v in value.items() if v is not None}
                        )
                    o[key] = base
                elif key in {"buildings", "units", "tenant_contracts"}:
                    if isinstance(value, list):
                        o[key] = value

        _mutate_overrides(case, mutator)
        _recompute_case_state_and_status(db, case)

    db.commit()

    chat_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.case_id == case.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "_case_chat_panel.html",
        {
            "case": case,
            "chat_messages": chat_messages,
            "patch_applied": bool(result.patch),
        },
    )


@router.post("/{case_id}/state/reset/{section}")
async def reset_section_override(
    case_id: uuid.UUID,
    section: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verwirft die Override einer Sektion -> zurueck auf Auto-Erkennung."""
    _require_case_edit(user)
    if section not in {
        "property", "management_contract", "billing_address", "owner",
        "buildings", "units", "tenant_contracts",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannte Sektion: {section}",
        )
    case = _load_case_for_user(db, user, case_id)

    def mutator(o: dict) -> None:
        o.pop(section, None)

    _mutate_overrides(case, mutator)
    audit(
        db, user, "case_state_reset",
        entity_type="case", entity_id=case.id,
        details={"section": section}, request=request,
    )
    _recompute_case_state_and_status(db, case)
    db.commit()
    anchor = {
        "property": "sec-property", "management_contract": "sec-management",
        "billing_address": "sec-billing", "owner": "sec-owner",
        "buildings": "sec-buildings", "units": "sec-units",
        "tenant_contracts": "sec-contracts",
    }[section]
    return RedirectResponse(
        url=f"/cases/{case.id}#{anchor}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
