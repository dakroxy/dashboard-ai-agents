"""Add is_archived + facilioo_last_modified to facilioo_tickets (Story 4.3).

Spike-Befund: Variante A (kein objects.facilioo_property_id noetig —
Mapping erfolgt dynamisch ueber Facilioo-Property.externalId = impower_property_id).

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "facilioo_tickets",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Separate Spalte fuer lastModified-Vergleich (nicht updated_at zweckentfremden
    # — onupdate-Hook wuerde bei jedem UPSERT hochlaufen und den Delta-Vergleich
    # kappen). Nullable: historische Rows ohne Mirror-Lauf haben keinen Wert.
    op.add_column(
        "facilioo_tickets",
        sa.Column(
            "facilioo_last_modified",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("facilioo_tickets", "facilioo_last_modified")
    op.drop_column("facilioo_tickets", "is_archived")
