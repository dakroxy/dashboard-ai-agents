"""cases + documents.case_id/doc_type fuer Multi-Doc-Workflows

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-20

Neue Tabelle `cases` als Container fuer Workflows, bei denen mehrere Dokumente
zu einem Fall gehoeren (Mietverwaltungs-Anlage). Die bestehende `documents`-
Tabelle bekommt einen optionalen `case_id` (gehoert zu welchem Fall) und
`doc_type` (Typ-Klassifizierung: verwaltervertrag, grundbuch, mietvertrag,
mieterliste, sonstiges). Single-Doc-Workflows (SEPA) lassen beide Felder null.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("impower_result", postgresql.JSONB(), nullable=True),
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
    )
    op.create_index("ix_cases_workflow_id", "cases", ["workflow_id"])
    op.create_index("ix_cases_created_by_id", "cases", ["created_by_id"])

    op.add_column(
        "documents",
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_case_id", "documents", ["case_id"])
    op.add_column(
        "documents",
        sa.Column("doc_type", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "doc_type")
    op.drop_index("ix_documents_case_id", table_name="documents")
    op.drop_column("documents", "case_id")
    op.drop_index("ix_cases_created_by_id", table_name="cases")
    op.drop_index("ix_cases_workflow_id", table_name="cases")
    op.drop_table("cases")
