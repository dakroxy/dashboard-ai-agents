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


def _client_ip(request: Request) -> str | None:
    # X-Forwarded-For vorrangig (hinter Reverse-Proxy wie Elestio-Router).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
