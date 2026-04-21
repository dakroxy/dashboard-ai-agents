from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Case(Base):
    """Container fuer komplexe Workflows, bei denen mehrere Dokumente zu einem
    Fall gehoeren (z.B. Mietverwaltungs-Anlage: Verwaltervertrag + Grundbuch +
    n Mietvertraege). Der gemergte Extraktions-Stand + die manuell gepflegten
    Felder liegen in `state` (JSONB). Einzel-Dokument-Extractions bleiben wie
    bisher an `documents.extractions` haengen."""

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="draft", server_default="draft"
    )
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    impower_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workflow: Mapped["Workflow"] = relationship("Workflow")  # noqa: F821
    creator: Mapped["User"] = relationship("User")  # noqa: F821
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        "Document", back_populates="case", cascade="all"
    )
