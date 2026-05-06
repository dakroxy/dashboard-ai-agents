"""Length-Caps fuer policen.produkt_typ (VARCHAR->VARCHAR(100)) und
policen.police_number (VARCHAR->VARCHAR(50)).

Pre-Migration-Check bricht ab, wenn Bestandsdaten die neue Cap reissen.

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Defensive: bei frischer DB / Test-Re-Run kann die Tabelle fehlen.
    # Ohne diesen Check wuerde der naechste Step mit einem unklaren
    # `ProgrammingError` (PG) bzw. `OperationalError` (SQLite) crashen.
    inspector = sa.inspect(conn)
    if not inspector.has_table("policen"):
        # Nichts zu cappen — die Spalten kommen aus Migration 0009 ohnehin
        # bereits mit den neuen Caps in einer frischen Initial-Migration.
        return

    row = conn.execute(
        sa.text(
            "SELECT MAX(LENGTH(produkt_typ)), MAX(LENGTH(police_number)) FROM policen"
        )
    ).fetchone()

    if row is not None:
        max_produkt_typ = row[0] or 0
        max_police_number = row[1] or 0
        if max_produkt_typ > 100 or max_police_number > 50:
            raise RuntimeError(
                f"Daten-Cleanup vor Migration 0019 noetig: "
                f"MAX(LENGTH(produkt_typ))={max_produkt_typ} (cap=100), "
                f"MAX(LENGTH(police_number))={max_police_number} (cap=50). "
                f"Betroffene Zeilen bereinigen und dann erneut migrieren."
            )

    op.alter_column(
        "policen",
        "produkt_typ",
        type_=sa.String(100),
        existing_type=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "policen",
        "police_number",
        type_=sa.String(50),
        existing_type=sa.String(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "policen",
        "produkt_typ",
        type_=sa.String(),
        existing_type=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "policen",
        "police_number",
        type_=sa.String(),
        existing_type=sa.String(50),
        existing_nullable=True,
    )
