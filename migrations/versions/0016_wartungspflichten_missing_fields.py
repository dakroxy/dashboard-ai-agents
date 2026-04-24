"""wartungspflichten: object_id FK (NOT NULL) + letzte_wartung"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # object_id: erst nullable anlegen, backfillen, dann NOT NULL setzen
    # (falls wartungspflichten-Rows aus Migration 0010 existieren)
    op.add_column(
        "wartungspflichten",
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_wartungspflichten_object_id",
        "wartungspflichten",
        "objects",
        ["object_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_wartungspflichten_object_id",
        "wartungspflichten",
        ["object_id"],
    )
    # Backfill aus policy.object_id
    op.execute("""
        UPDATE wartungspflichten w
        SET object_id = p.object_id
        FROM policen p
        WHERE w.policy_id = p.id AND w.object_id IS NULL
    """)
    # NOT NULL erzwingen
    op.alter_column("wartungspflichten", "object_id", nullable=False)

    op.add_column(
        "wartungspflichten",
        sa.Column("letzte_wartung", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wartungspflichten", "letzte_wartung")
    op.drop_index("ix_wartungspflichten_object_id", table_name="wartungspflichten")
    op.drop_constraint(
        "fk_wartungspflichten_object_id", "wartungspflichten", type_="foreignkey"
    )
    op.drop_column("wartungspflichten", "object_id")
