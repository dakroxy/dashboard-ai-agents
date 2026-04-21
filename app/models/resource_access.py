from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ResourceAccess(Base):
    """Generische Zugriffstabelle: verknuepft eine Rolle ODER einen User
    mit einer Ressource (Workflow, spaeter Objekt/Task/CRM-Lead/...).

    Per CheckConstraint ist exakt eines von role_id/user_id gesetzt.
    mode='allow' oder mode='deny' — User-Overrides gewinnen ueber Role-Defaults."""

    __tablename__ = "resource_access"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    mode: Mapped[str] = mapped_column(
        String, nullable=False, default="allow"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
