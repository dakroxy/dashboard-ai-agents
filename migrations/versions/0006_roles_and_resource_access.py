"""roles, resource_access, user-extras, documents.workflow_id

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------
    # roles — eigenstaendige Entitaet, damit Admins neue Rollen anlegen koennen.
    # Permissions sind als JSONB-Array gespeichert, weil sich das Set
    # schnell aendert und die Query-Performance hier unkritisch ist.
    # -------------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "permissions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_system_role",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
        sa.UniqueConstraint("key", name="uq_roles_key"),
    )
    op.create_index("ix_roles_key", "roles", ["key"])

    # -------------------------------------------------------------------
    # resource_access — generische N:M-Zugriffstabelle. Ein Eintrag
    # ist entweder rollen- ODER userbezogen (CheckConstraint XOR).
    # Damit koennen spaetere Module (Objekte, Tasks, CRM) dieselbe
    # Tabelle wiederverwenden, indem sie einen neuen resource_type
    # registrieren — kein Schema-Redesign pro Feature.
    # -------------------------------------------------------------------
    op.create_table(
        "resource_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="allow"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(role_id IS NOT NULL)::int + (user_id IS NOT NULL)::int = 1",
            name="ck_resource_access_role_xor_user",
        ),
        sa.CheckConstraint(
            "mode IN ('allow','deny')",
            name="ck_resource_access_mode",
        ),
    )
    op.create_index(
        "ix_resource_access_role",
        "resource_access",
        ["role_id", "resource_type"],
    )
    op.create_index(
        "ix_resource_access_user",
        "resource_access",
        ["user_id", "resource_type"],
    )
    op.create_index(
        "ix_resource_access_resource",
        "resource_access",
        ["resource_type", "resource_id"],
    )

    # -------------------------------------------------------------------
    # users: Rolle + Per-User-Permission-Overrides + Soft-Disable
    # -------------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "permissions_extra",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "permissions_denied",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "disabled_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # -------------------------------------------------------------------
    # documents.workflow_id — explizite Zuordnung ab jetzt, damit der
    # Zugriff pro Workflow steuerbar ist. Backfill auf sepa_mandate,
    # dann NOT NULL.
    # -------------------------------------------------------------------
    op.add_column(
        "documents",
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE documents
        SET workflow_id = (
            SELECT id FROM workflows WHERE key = 'sepa_mandate' LIMIT 1
        )
        WHERE workflow_id IS NULL
        """
    )
    op.alter_column("documents", "workflow_id", nullable=False)
    op.create_index("ix_documents_workflow_id", "documents", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_workflow_id", table_name="documents")
    op.drop_column("documents", "workflow_id")
    op.drop_column("users", "disabled_by_id")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "permissions_denied")
    op.drop_column("users", "permissions_extra")
    op.drop_column("users", "role_id")
    op.drop_index("ix_resource_access_resource", table_name="resource_access")
    op.drop_index("ix_resource_access_user", table_name="resource_access")
    op.drop_index("ix_resource_access_role", table_name="resource_access")
    op.drop_table("resource_access")
    op.drop_index("ix_roles_key", table_name="roles")
    op.drop_table("roles")
