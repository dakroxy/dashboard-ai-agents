"""0020 perf indexes: Composite-Index auf field_provenance fuer get_provenance_map_bulk.

Revision ID: 0020_perf_indexes
Revises: 0020
Create Date: 2026-05-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_perf_indexes"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Covering-Index fuer get_provenance_map_bulk:
    # WHERE entity_type=... AND entity_id=... ORDER BY field_name, created_at DESC, id DESC
    # Postgres kann diesen Query als reinen Index-Scan ohne extra Sort ausfuehren.
    # SQLite ignoriert DESC-Hinweise im Index, verhält sich aber semantisch korrekt.
    op.create_index(
        "ix_field_provenance_entity_field_created",
        "field_provenance",
        [
            "entity_type",
            "entity_id",
            "field_name",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_field_provenance_entity_field_created",
        table_name="field_provenance",
    )
