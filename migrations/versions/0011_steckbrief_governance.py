"""Steckbrief-Governance: field_provenance + review_queue_entries

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-21

Zentrales Write-Gate braucht zwei Governance-Tabellen:
  * field_provenance — ein Eintrag pro erfolgreichem Feld-Write mit Herkunft
    (user_edit, impower_mirror, facilioo_mirror, sharepoint_mirror, ai_suggestion)
    und einem JSON-Snapshot (old/new). Ciphertext-Felder landen als
    `{"encrypted": True}`-Marker, nie Klartext.
  * review_queue_entries — jede KI-Write-Absicht wird NICHT am Zielfeld
    geschrieben, sondern als pending-Entry angelegt. approve_review_entry
    macht daraus einen echten Write mit source=ai_suggestion.

source/status bewusst als String (kein SQL-Enum) — neue Quellen und
Status-Uebergaenge kommen mit spaeteren Stories, Schema-Change vermeiden.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "field_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "value_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_field_provenance_entity_field",
        "field_provenance",
        ["entity_type", "entity_id", "field_name"],
    )
    op.create_index(
        "ix_field_provenance_user_id", "field_provenance", ["user_id"]
    )
    op.create_index(
        "ix_field_provenance_created_at",
        "field_provenance",
        ["created_at"],
    )

    op.create_table(
        "review_queue_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_entity_type", sa.String(), nullable=False),
        sa.Column(
            "target_entity_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("proposed_value", postgresql.JSONB(), nullable=False),
        sa.Column("agent_ref", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "source_doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "agent_context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "assigned_to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_review_queue_status_created",
        "review_queue_entries",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_review_queue_target",
        "review_queue_entries",
        ["target_entity_type", "target_entity_id"],
    )
    op.create_index(
        "ix_review_queue_assigned",
        "review_queue_entries",
        ["assigned_to_user_id", "status"],
    )
    op.create_index(
        "ix_review_queue_source_doc",
        "review_queue_entries",
        ["source_doc_id"],
    )

    # Seit Migration 0011 akzeptiert resource_access.resource_type den Wert "object"
    # (kein Check-Constraint, kein Enum — die Tabelle validiert nicht). v1 nutzt
    # die Zeilen als Soft-Record; Enforcement via accessible_object_ids() schaltet
    # v1.1 scharf. Falls v1.1 auf ein Enum migriert, hier CHECK-Constraint ergaenzen.


def downgrade() -> None:
    op.drop_index(
        "ix_review_queue_source_doc", table_name="review_queue_entries"
    )
    op.drop_index("ix_review_queue_assigned", table_name="review_queue_entries")
    op.drop_index("ix_review_queue_target", table_name="review_queue_entries")
    op.drop_index(
        "ix_review_queue_status_created", table_name="review_queue_entries"
    )
    op.drop_table("review_queue_entries")

    op.drop_index(
        "ix_field_provenance_created_at", table_name="field_provenance"
    )
    op.drop_index("ix_field_provenance_user_id", table_name="field_provenance")
    op.drop_index(
        "ix_field_provenance_entity_field", table_name="field_provenance"
    )
    op.drop_table("field_provenance")
