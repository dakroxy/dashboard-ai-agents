"""Audit-Logger — einheitlicher Helper fuer alle Event-Typen.

Benutzung:
    from app.services.audit import audit
    audit(db, user, "document_approved", entity_type="document", entity_id=doc.id,
          document_id=doc.id, details={"previous_status": doc.status}, request=request)
    db.commit()

Der Helper fuegt den Eintrag nur zur Session hinzu — das Commit muss
der Caller machen, damit der Log-Eintrag in derselben Transaktion
wie der fachliche Vorgang landet.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


# Known Audit-Actions — fuer das Filter-Dropdown in /admin/logs.
#
# Das Dropdown zeigt die Union aus dieser Konstante und den distinct-Actions,
# die tatsaechlich in der DB liegen. Damit tauchen neue Actions nach Deploy
# sofort im Filter auf, auch wenn noch kein Log-Eintrag existiert.
# Neue Actions beim Hinzufuegen des audit()-Calls hier miterweitern.
KNOWN_AUDIT_ACTIONS: list[str] = sorted(
    [
        # Auth + User
        "login",
        "login_new_user",
        "login_denied_disabled",
        "logout",
        "user_updated",
        "user_disabled",
        "user_enabled",
        # Rollen
        "role_created",
        "role_updated",
        "role_deleted",
        # Workflows
        "workflow_edited",
        # ETV-Unterschriftenliste
        "etv_signature_list_generated",
        # Dokumente (SEPA-Workflow)
        "document_uploaded",
        "document_extracted",
        "document_approved",
        "document_written",
        "document_already_present",
        "document_write_failed",
        "document_chat_message",
        "extraction_field_updated",
        # Cases (Mietverwaltung)
        "case_created",
        "case_renamed",
        "case_document_uploaded",
        "case_document_classified",
        "case_document_extracted",
        "case_state_saved",
        "case_state_reset",
        "case_chat_message",
        "mietverwaltung_write_triggered",
        "mietverwaltung_write_complete",
        "mietverwaltung_write_error",
        "mietverwaltung_write_crashed",
        "mietverwaltung_write_preflight_failed",
        # Kontakte
        "contact_created",
        # Audit selbst
        "audit_entry_deleted",
        # Objektsteckbrief (Epic 1) — Emit folgt in spaeteren Stories.
        "object_created",
        "object_field_updated",
        "object_photo_uploaded",
        "object_photo_deleted",
        "sharepoint_init_failed",
        "registry_entry_created",
        "registry_entry_updated",
        "review_queue_created",
        "review_queue_approved",
        "review_queue_rejected",
        "sync_started",
        "sync_finished",
        "sync_failed",
        "policy_violation",
        "encryption_key_missing",
        "photo_upload_orphan",
    ]
)


def audit(
    db: Session,
    user: User | None,
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
    user_email: str | None = None,
) -> AuditLog:
    """Legt einen Audit-Log-Eintrag an.

    user_email wird aus user genommen, falls vorhanden. Fuer Login-Fehler
    (noch kein User) oder Systemevents kann user_email explizit gesetzt werden.
    """
    entry = AuditLog(
        id=uuid.uuid4(),
        user_id=user.id if user is not None else None,
        user_email=(user.email if user is not None else user_email) or "",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        document_id=document_id,
        ip_address=_client_ip(request) if request is not None else None,
        details_json=details,
    )
    db.add(entry)
    return entry


def _audit_in_new_session(
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Legt einen Audit-Eintrag in einer NEUEN Session an.

    Benoetigt wenn die urspruengliche Session bereits gerollt-back wurde
    (z. B. Foto-Upload-Saga nach DB-Commit-Fehler). Best-effort: Fehler
    werden nur geloggt, nicht weiter propagiert.
    """
    from app.db import SessionLocal
    db2 = SessionLocal()
    try:
        audit(db2, None, action, entity_type=entity_type, entity_id=entity_id, details=details)
        db2.commit()
    except Exception:
        db2.rollback()
    finally:
        db2.close()


def _update_stub_status_in_new_session(
    photo_id: uuid.UUID,
    status: str,
    *,
    error: str | None = None,
) -> None:
    """Aktualisiert den Status einer Stub-Photo-Row in einer NEUEN Session.

    Wird im Foto-Upload-Saga-Pfad benoetigt, wenn die Haupt-Session
    nach einem Upload-Commit-Fehler rollbacked ist. Best-effort.
    """
    from app.db import SessionLocal
    from app.models.object import SteckbriefPhoto
    db2 = SessionLocal()
    try:
        photo = db2.get(SteckbriefPhoto, photo_id)
        if photo is not None:
            meta: dict = dict(photo.photo_metadata or {})
            meta["status"] = status
            if error:
                meta["error"] = error[:500]
            photo.photo_metadata = meta
            db2.commit()
    except Exception:
        db2.rollback()
    finally:
        db2.close()


def _client_ip(request: Request) -> str | None:
    # X-Forwarded-For vorrangig (hinter Reverse-Proxy wie Elestio-Router).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        ip = fwd.split(",")[0].strip()
    elif request.client:
        ip = request.client.host
    else:
        return None
    # audit_log.ip_address ist String(45) — Truncation verhindert DB-Constraint-Error
    # bei gespoofen X-Forwarded-For-Chains (kein ALTER COLUMN noetig, Spalte korrekt seit 0007).
    return ip[:45] if ip else None
