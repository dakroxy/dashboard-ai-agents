from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Object(Base):
    """Stammdaten eines verwalteten Immobilien-Objekts (WEG / Mietobjekt).

    JSONB-Felder duerfen NICHT in-place mutiert werden — immer Reassignment
    oder flag_modified(). Das zentrale Write-Gate nutzt Reassignment.
    """

    __tablename__ = "objects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    short_code: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    full_address: Mapped[str | None] = mapped_column(String, nullable=True)
    weg_nr: Mapped[str | None] = mapped_column(String, nullable=True)
    impower_property_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_roof: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Ciphertext-Placeholder — Fernet-Encryption folgt mit Story 1.7.
    entry_code_main_door: Mapped[str | None] = mapped_column(String, nullable=True)
    entry_code_garage: Mapped[str | None] = mapped_column(String, nullable=True)
    entry_code_technical_room: Mapped[str | None] = mapped_column(String, nullable=True)

    last_known_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    reserve_current: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    reserve_target: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    wirtschaftsplan_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    sepa_mandate_refs: Mapped[list[Any]] = mapped_column(
        # `text("'[]'")` statt String-Default "[]": das laeuft unter Postgres
        # (impliziter Cast auf JSONB) UND SQLite (TEXT-Literal in Tests). Der
        # alte String-Default erzeugte bei Alembic-Autogenerate-Diffs einen
        # Rauch-Drift gegen die Migration (die sa.text("'[]'::jsonb") nutzt).
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    pflegegrad_score_cached: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pflegegrad_score_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    voting_rights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    object_history_structured: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    equipment_flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    notes_owners: Mapped[dict[str, Any]] = mapped_column(
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

    units: Mapped[list["Unit"]] = relationship(
        "Unit", back_populates="object", cascade="all, delete-orphan"
    )
    policen: Mapped[list["InsurancePolicy"]] = relationship(  # noqa: F821
        "InsurancePolicy", back_populates="object", cascade="all, delete-orphan"
    )


class Unit(Base):
    """Einzelne Nutzungseinheit (Wohnung, Gewerbe, TG-Stellplatz, ...) eines
    Objekts. Verknuepft Mietvertraege, Zaehler, Schadensfaelle."""

    __tablename__ = "units"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_number: Mapped[str] = mapped_column(String, nullable=False)
    impower_unit_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    usage_type: Mapped[str | None] = mapped_column(String, nullable=True)
    floor_area_sqm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    floor_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    floorplan_drive_item_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    equipment_features: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
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

    object: Mapped[Object] = relationship("Object", back_populates="units")


class SteckbriefPhoto(Base):
    """Foto-Metadaten (SharePoint-Link oder Local-Fallback) zu einem Objekt
    oder einer Einheit.

    Attribut/Spalte heisst bewusst `photo_metadata` — `metadata` ist auf
    SQLAlchemy-DeclarativeBase (Base.metadata) reserviert und bricht den
    Klassen-Build (InvalidRequestError).
    """

    __tablename__ = "steckbrief_photos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    drive_item_id: Mapped[str | None] = mapped_column(String, nullable=True)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    photo_metadata: Mapped[dict[str, Any]] = mapped_column(
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
