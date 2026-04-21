from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    stored_path: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="uploaded", server_default="uploaded"
    )
    matching_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    impower_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    doc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    uploader: Mapped["User"] = relationship("User")  # noqa: F821
    workflow: Mapped["Workflow"] = relationship("Workflow")  # noqa: F821
    case: Mapped["Case | None"] = relationship(  # noqa: F821
        "Case", back_populates="documents"
    )
