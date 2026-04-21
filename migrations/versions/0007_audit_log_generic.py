"""audit_log generisch: document_id nullable + user_id + entity + ip

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # document_id muss optional werden, damit z. B. Login/Workflow-Edit
    # ohne Dokumentbezug geloggt werden koennen.
    op.alter_column("audit_log", "document_id", nullable=True)

    op.add_column(
        "audit_log",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])

    # Generisches Entity-Pair fuer alle zukuenftigen Module (Workflow,
    # Task, Objekt, Brief, CRM-Lead usw.). document_id bleibt zusaetzlich
    # erhalten, weil Dokumente der Haupt-Use-Case sind und die FK
    # Integritaet erzwingt.
    op.add_column(
        "audit_log", sa.Column("entity_type", sa.String(), nullable=True)
    )
    op.add_column(
        "audit_log",
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_audit_log_entity",
        "audit_log",
        ["entity_type", "entity_id"],
    )

    op.add_column(
        "audit_log",
        sa.Column("ip_address", sa.String(length=45), nullable=True),
    )

    # Haeufige Filter im Admin-UI: nach Action und nach Zeitraum.
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index(
        "ix_audit_log_created_at", "audit_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_column("audit_log", "ip_address")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_column("audit_log", "entity_id")
    op.drop_column("audit_log", "entity_type")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_column("audit_log", "user_id")
    op.alter_column("audit_log", "document_id", nullable=False)
