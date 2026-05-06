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

import ipaddress
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
        "policy_deleted",
        "pflegegrad_cache_commit_fail",
        "wartung_deleted",
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
    user: User | None = None,
    request: Request | None = None,
) -> None:
    """Legt einen Audit-Eintrag in einer NEUEN Session an.

    Benoetigt wenn die urspruengliche Session bereits gerollt-back wurde
    (z. B. Foto-Upload-Saga nach DB-Commit-Fehler). Best-effort: Fehler
    werden nur geloggt, nicht weiter propagiert.

    `user` und `request` werden weitergereicht, damit Acting-User + IP-Address
    auch im Side-Effect-Audit erhalten bleiben (Filter pro User in /admin/logs
    sonst ohne Sicht auf diese Eintraege).
    """
    from app.db import SessionLocal
    db2 = SessionLocal()
    try:
        audit(
            db2,
            user,
            action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            request=request,
        )
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
    """Liefert die Client-IP fuer den Audit-Eintrag.

    X-Forwarded-For wird vorrangig genutzt (hinter Reverse-Proxy wie
    Elestio-Router); Fallback auf `request.client.host`.

    Validierung via `ipaddress.ip_address` schuetzt vor:
      - Garbage in XFF (gespoofte Strings, die DB-Constraint-Errors
        oder unparseable Audit-Eintraege erzeugen wuerden);
      - IPv6-Truncation-Korruption (str-Slice auf 45 chars wuerde
        Adressen mid-segment abschneiden);
      - Encoding-Surprises (Surrogate-Pairs, Multi-Byte-Codepoints).

    Liefert die normalisierte IP-Repraesentation oder `None` bei
    ungueltigen Inputs (Audit-Log darf nie an einer schlechten IP scheitern).
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        candidate = fwd.split(",")[0].strip()
    elif request.client:
        candidate = request.client.host or ""
    else:
        return None

    if not candidate:
        return None

    # IPv4 mit Port (`127.0.0.1:8080`) — manche Reverse-Proxies setzen den
    # Source-Port mit. Eine reine IPv4-Form mit genau einem Doppelpunkt ist
    # kein valides IPv6 (IPv6 hat mind. zwei `:`); split off.
    if candidate.count(":") == 1 and candidate.count(".") == 3:
        candidate = candidate.split(":", 1)[0]

    # IPv6 mit Zone-ID (`fe80::1%eth0`) — `ip_address` lehnt das ab; Zone fuer
    # Logging unwichtig, nur die numerische Adresse zaehlt.
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]

    try:
        normalized = str(ipaddress.ip_address(candidate))
    except (ValueError, TypeError):
        # Garbage in XFF (z. B. "X" * 50 oder mit Sonderzeichen) -> nichts
        # einloggen statt Truncation-Garbage. audit_log.ip_address ist nullable.
        return None

    # audit_log.ip_address ist String(45). IPv6 max 39 chars, IPv4 max 15 —
    # Truncation kann nach Validierung nicht zu malformed Werten fuehren.
    return normalized[:45]
