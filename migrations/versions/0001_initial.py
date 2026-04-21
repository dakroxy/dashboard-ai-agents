"""initial: users, documents, extractions

Revision ID: 0001
Revises:
Create Date: 2026-04-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("google_sub", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("picture", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "uploaded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("stored_path", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="uploaded",
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_documents_uploaded_by_id", "documents", ["uploaded_by_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("extracted", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_extractions_document_id", "extractions", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_extractions_document_id", table_name="extractions")
    op.drop_table("extractions")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_uploaded_by_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_table("users")
