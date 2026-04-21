"""Steckbrief-Core: 15 Haupt-/Registry-Tabellen fuer Objektsteckbrief (Epic 1)

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-21

Legt das Datenmodell fuer das Objektsteckbrief-Modul an:
  * Registries (ohne FK): versicherer, dienstleister, banken, ablesefirmen
  * Haupt-Entitaeten: objects, units, policen, wartungspflichten, schadensfaelle,
    eigentuemer, mieter, mietvertraege, zaehler, facilioo_tickets, steckbrief_photos

Governance-Tabellen (field_provenance + review_queue_entries) folgen in 0011,
damit Datenmodell und Write-Gate-Verkabelung getrennt nachvollziehbar sind
(architecture.md §CD1).

JSONB-Defaults als '{}'::jsonb bzw. '[]'::jsonb (je nach Typ); Ciphertext-Felder
(entry_code_*) stehen in 1.2 als plain String — Fernet-Encryption kommt mit
Story 1.7, bis dahin dokumentiert das Write-Gate die Felder als "sensibel".
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Registries (keine FK-Abhaengigkeiten)
    # ------------------------------------------------------------------
    op.create_table(
        "versicherer",
        _uuid_pk(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "contact_info",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_versicherer_name", "versicherer", ["name"])

    op.create_table(
        "dienstleister",
        _uuid_pk(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "gewerke_tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "notes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_dienstleister_name", "dienstleister", ["name"])

    op.create_table(
        "banken",
        _uuid_pk(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("bic", sa.String(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_banken_bic", "banken", ["bic"])

    op.create_table(
        "ablesefirmen",
        _uuid_pk(),
        sa.Column("name", sa.String(), nullable=False),
        *_timestamps(),
    )

    # ------------------------------------------------------------------
    # objects (Haupt-Entitaet, keine FK-Abhaengigkeiten)
    # ------------------------------------------------------------------
    op.create_table(
        "objects",
        _uuid_pk(),
        sa.Column("short_code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("full_address", sa.String(), nullable=True),
        sa.Column("weg_nr", sa.String(), nullable=True),
        sa.Column("impower_property_id", sa.String(), nullable=True),
        sa.Column("year_built", sa.Integer(), nullable=True),
        sa.Column("year_roof", sa.Integer(), nullable=True),
        # Ciphertext-Placeholder — Encryption-Wrapper kommt mit Story 1.7.
        sa.Column("entry_code_main_door", sa.String(), nullable=True),
        sa.Column("entry_code_garage", sa.String(), nullable=True),
        sa.Column("entry_code_technical_room", sa.String(), nullable=True),
        sa.Column("last_known_balance", sa.Numeric(12, 2), nullable=True),
        sa.Column("pflegegrad_score_cached", sa.Integer(), nullable=True),
        sa.Column(
            "pflegegrad_score_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "voting_rights",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "object_history_structured",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "equipment_flags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "notes_owners",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.UniqueConstraint("short_code", name="uq_objects_short_code"),
    )
    op.create_index("ix_objects_short_code", "objects", ["short_code"])
    op.create_index(
        "ix_objects_impower_property_id", "objects", ["impower_property_id"]
    )

    # ------------------------------------------------------------------
    # units (FK → objects)
    # ------------------------------------------------------------------
    op.create_table(
        "units",
        _uuid_pk(),
        sa.Column(
            "object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unit_number", sa.String(), nullable=False),
        sa.Column("impower_unit_id", sa.String(), nullable=True),
        sa.Column("usage_type", sa.String(), nullable=True),
        sa.Column("floor_area_sqm", sa.Numeric(10, 2), nullable=True),
        sa.Column("floor_level", sa.Integer(), nullable=True),
        sa.Column("floorplan_drive_item_id", sa.String(), nullable=True),
        sa.Column(
            "equipment_features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_units_object_id", "units", ["object_id"])
    op.create_index("ix_units_impower_unit_id", "units", ["impower_unit_id"])

    # ------------------------------------------------------------------
    # policen (FK → objects + versicherer)
    # ------------------------------------------------------------------
    op.create_table(
        "policen",
        _uuid_pk(),
        sa.Column(
            "object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "versicherer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("versicherer.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("police_number", sa.String(), nullable=True),
        sa.Column("main_due_date", sa.Date(), nullable=True),
        sa.Column("next_main_due", sa.Date(), nullable=True),
        sa.Column("praemie", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "coverage",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "risk_attributes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_policen_object_id", "policen", ["object_id"])
    op.create_index("ix_policen_versicherer_id", "policen", ["versicherer_id"])
    op.create_index("ix_policen_next_main_due", "policen", ["next_main_due"])

    # ------------------------------------------------------------------
    # wartungspflichten (FK → policen + dienstleister)
    # ------------------------------------------------------------------
    op.create_table(
        "wartungspflichten",
        _uuid_pk(),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policen.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dienstleister_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dienstleister.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("bezeichnung", sa.String(), nullable=False),
        sa.Column("intervall_monate", sa.Integer(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column(
            "notes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_wartungspflichten_policy_id", "wartungspflichten", ["policy_id"]
    )
    op.create_index(
        "ix_wartungspflichten_dienstleister_id",
        "wartungspflichten",
        ["dienstleister_id"],
    )
    op.create_index(
        "ix_wartungspflichten_next_due_date",
        "wartungspflichten",
        ["next_due_date"],
    )

    # ------------------------------------------------------------------
    # schadensfaelle (FK → policen + units)
    # ------------------------------------------------------------------
    op.create_table(
        "schadensfaelle",
        _uuid_pk(),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policen.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("occurred_at", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_schadensfaelle_policy_id", "schadensfaelle", ["policy_id"]
    )
    op.create_index("ix_schadensfaelle_unit_id", "schadensfaelle", ["unit_id"])

    # ------------------------------------------------------------------
    # eigentuemer (FK → objects) — Personen-Registry pro Objekt
    # ------------------------------------------------------------------
    op.create_table(
        "eigentuemer",
        _uuid_pk(),
        sa.Column(
            "object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column(
            "voting_stake_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_eigentuemer_object_id", "eigentuemer", ["object_id"])

    # ------------------------------------------------------------------
    # mieter (FK → objects)
    # ------------------------------------------------------------------
    op.create_table(
        "mieter",
        _uuid_pk(),
        sa.Column(
            "object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_mieter_object_id", "mieter", ["object_id"])

    # ------------------------------------------------------------------
    # mietvertraege (FK → units + mieter)
    # ------------------------------------------------------------------
    op.create_table(
        "mietvertraege",
        _uuid_pk(),
        sa.Column(
            "unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mieter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mieter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("cold_rent", sa.Numeric(12, 2), nullable=True),
        sa.Column("deposit", sa.Numeric(12, 2), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_mietvertraege_unit_id", "mietvertraege", ["unit_id"])
    op.create_index(
        "ix_mietvertraege_mieter_id", "mietvertraege", ["mieter_id"]
    )

    # ------------------------------------------------------------------
    # zaehler (FK → units)
    # ------------------------------------------------------------------
    op.create_table(
        "zaehler",
        _uuid_pk(),
        sa.Column(
            "unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("meter_number", sa.String(), nullable=False),
        sa.Column("meter_type", sa.String(), nullable=True),
        sa.Column(
            "current_reading_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_zaehler_unit_id", "zaehler", ["unit_id"])

    # ------------------------------------------------------------------
    # facilioo_tickets (FK → objects)
    # ------------------------------------------------------------------
    op.create_table(
        "facilioo_tickets",
        _uuid_pk(),
        sa.Column(
            "object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("facilioo_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.UniqueConstraint("facilioo_id", name="uq_facilioo_tickets_facilioo_id"),
    )
    op.create_index(
        "ix_facilioo_tickets_object_id", "facilioo_tickets", ["object_id"]
    )
    op.create_index(
        "ix_facilioo_tickets_facilioo_id",
        "facilioo_tickets",
        ["facilioo_id"],
    )

    # ------------------------------------------------------------------
    # steckbrief_photos (FK → objects + optional units)
    #
    # DB-Spalte bewusst `photo_metadata`. `metadata` ist auf SQLAlchemy-
    # DeclarativeBase reserviert (Base.metadata) und wuerde den Klassen-Build
    # mit InvalidRequestError scheitern lassen.
    # ------------------------------------------------------------------
    op.create_table(
        "steckbrief_photos",
        _uuid_pk(),
        sa.Column(
            "object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("drive_item_id", sa.String(), nullable=True),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column(
            "photo_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_steckbrief_photos_object_id", "steckbrief_photos", ["object_id"]
    )
    op.create_index(
        "ix_steckbrief_photos_unit_id", "steckbrief_photos", ["unit_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_steckbrief_photos_unit_id", table_name="steckbrief_photos")
    op.drop_index(
        "ix_steckbrief_photos_object_id", table_name="steckbrief_photos"
    )
    op.drop_table("steckbrief_photos")

    op.drop_index(
        "ix_facilioo_tickets_facilioo_id", table_name="facilioo_tickets"
    )
    op.drop_index(
        "ix_facilioo_tickets_object_id", table_name="facilioo_tickets"
    )
    op.drop_table("facilioo_tickets")

    op.drop_index("ix_zaehler_unit_id", table_name="zaehler")
    op.drop_table("zaehler")

    op.drop_index("ix_mietvertraege_mieter_id", table_name="mietvertraege")
    op.drop_index("ix_mietvertraege_unit_id", table_name="mietvertraege")
    op.drop_table("mietvertraege")

    op.drop_index("ix_mieter_object_id", table_name="mieter")
    op.drop_table("mieter")

    op.drop_index("ix_eigentuemer_object_id", table_name="eigentuemer")
    op.drop_table("eigentuemer")

    op.drop_index("ix_schadensfaelle_unit_id", table_name="schadensfaelle")
    op.drop_index("ix_schadensfaelle_policy_id", table_name="schadensfaelle")
    op.drop_table("schadensfaelle")

    op.drop_index(
        "ix_wartungspflichten_next_due_date", table_name="wartungspflichten"
    )
    op.drop_index(
        "ix_wartungspflichten_dienstleister_id",
        table_name="wartungspflichten",
    )
    op.drop_index(
        "ix_wartungspflichten_policy_id", table_name="wartungspflichten"
    )
    op.drop_table("wartungspflichten")

    op.drop_index("ix_policen_next_main_due", table_name="policen")
    op.drop_index("ix_policen_versicherer_id", table_name="policen")
    op.drop_index("ix_policen_object_id", table_name="policen")
    op.drop_table("policen")

    op.drop_index("ix_units_impower_unit_id", table_name="units")
    op.drop_index("ix_units_object_id", table_name="units")
    op.drop_table("units")

    op.drop_index(
        "ix_objects_impower_property_id", table_name="objects"
    )
    op.drop_index("ix_objects_short_code", table_name="objects")
    op.drop_table("objects")

    op.drop_table("ablesefirmen")

    op.drop_index("ix_banken_bic", table_name="banken")
    op.drop_table("banken")

    op.drop_index("ix_dienstleister_name", table_name="dienstleister")
    op.drop_table("dienstleister")

    op.drop_index("ix_versicherer_name", table_name="versicherer")
    op.drop_table("versicherer")
