"""workflows.chat_model — separates Modell fuer Chat-/Rueckfrage-Flow

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "chat_model",
            sa.String(),
            nullable=False,
            server_default="claude-sonnet-4-6",
        ),
    )


def downgrade() -> None:
    op.drop_column("workflows", "chat_model")
