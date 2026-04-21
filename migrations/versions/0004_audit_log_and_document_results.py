"""audit_log table + documents.matching_result + documents.impower_result

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("matching_result", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("impower_result", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_log_document_id", "audit_log", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_document_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_column("documents", "impower_result")
    op.drop_column("documents", "matching_result")
