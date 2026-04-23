"""steckbrief_photos: backend + filename + component_ref + captured_at + uploaded_by_user_id

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-23

Erweitert die bereits in 0010 angelegte ``steckbrief_photos``-Tabelle um die
Story-1.8-Felder. Kein ``op.create_table`` — nur ``op.add_column``:

  * backend             — "sharepoint" oder "local" (Quelle der gespeicherten Datei)
  * filename            — Originalname (User-sichtbar im UI)
  * component_ref       — Logischer Gruppenkey (z.B. "absperrpunkt_wasser")
  * captured_at         — Aufnahme-/Upload-Zeitpunkt (default now())
  * uploaded_by_user_id — FK -> users.id (SET NULL beim User-Loeschen)

Der Index auf ``component_ref`` beschleunigt das Gruppieren in der
Technik-Sektion (``photos_by_component``).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "steckbrief_photos",
        sa.Column("backend", sa.String(), nullable=False, server_default="local"),
    )
    op.add_column(
        "steckbrief_photos",
        sa.Column("filename", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "steckbrief_photos",
        sa.Column("component_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "steckbrief_photos",
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "steckbrief_photos",
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_steckbrief_photos_component_ref",
        "steckbrief_photos",
        ["component_ref"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_steckbrief_photos_component_ref",
        table_name="steckbrief_photos",
    )
    op.drop_column("steckbrief_photos", "uploaded_by_user_id")
    op.drop_column("steckbrief_photos", "captured_at")
    op.drop_column("steckbrief_photos", "component_ref")
    op.drop_column("steckbrief_photos", "filename")
    op.drop_column("steckbrief_photos", "backend")
