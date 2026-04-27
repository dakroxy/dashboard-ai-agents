from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class InsurancePolicy(Base):
    """Versicherungs-Police an einem Objekt. Klassennamen bewusst englisch
    (`InsurancePolicy`) statt `Policy`, weil `Policy` mit dem Permissions-
    Policy-Begriff kollidiert (architecture.md §Naming)."""

    __tablename__ = "policen"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    versicherer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versicherer.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    police_number: Mapped[str | None] = mapped_column(String, nullable=True)
    produkt_typ: Mapped[str | None] = mapped_column(String, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_period_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_main_due: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    praemie: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    coverage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    risk_attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    object: Mapped["Object"] = relationship(  # noqa: F821
        "Object", back_populates="policen"
    )
    versicherer: Mapped["Versicherer | None"] = relationship(  # noqa: F821
        "Versicherer", foreign_keys=[versicherer_id]
    )
    wartungspflichten: Mapped[list["Wartungspflicht"]] = relationship(
        "Wartungspflicht",
        back_populates="policy",
        foreign_keys="[Wartungspflicht.policy_id]",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    schadensfaelle: Mapped[list["Schadensfall"]] = relationship(
        "Schadensfall",
        back_populates="policy",
        foreign_keys="[Schadensfall.policy_id]",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Wartungspflicht(Base):
    """Wartungspflicht — meist aus einer Police abgeleitet (z.B. Haftpflicht
    verlangt jaehrliche Kaminkehrer-Wartung), mit optionalem Dienstleister."""

    __tablename__ = "wartungspflichten"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policen.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dienstleister_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dienstleister.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bezeichnung: Mapped[str] = mapped_column(String, nullable=False)
    intervall_monate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    letzte_wartung: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    policy: Mapped["InsurancePolicy | None"] = relationship(
        "InsurancePolicy", back_populates="wartungspflichten", foreign_keys=[policy_id]
    )
    object: Mapped["Object"] = relationship(  # noqa: F821
        "Object", back_populates="wartungspflichten", foreign_keys=[object_id]
    )
    dienstleister: Mapped["Dienstleister | None"] = relationship(  # noqa: F821
        "Dienstleister", foreign_keys=[dienstleister_id]
    )


class Schadensfall(Base):
    """Schadensfall unter einer Police; optional auf Einheit bezogen."""

    __tablename__ = "schadensfaelle"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policen.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    occurred_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    policy: Mapped["InsurancePolicy | None"] = relationship(
        "InsurancePolicy", back_populates="schadensfaelle", foreign_keys=[policy_id]
    )
    unit: Mapped["Unit | None"] = relationship(  # noqa: F821
        "Unit", foreign_keys=[unit_id]
    )
