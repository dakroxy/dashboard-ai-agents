"""chat_messages.case_id + document_id nullable fuer Case-Chat (Paket 8)

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-21

Chat-Historie haengt bisher an Documents. Fuer Multi-Doc-Cases kommt ein
zweiter Chat-Kanal, der an Case haengt. Zwei aenderungen:
- chat_messages.document_id wird nullable (Case-Chat hat keinen Doc)
- chat_messages.case_id neu (nullable FK, entweder document_id oder case_id
  muss gesetzt sein — der Constraint bleibt im Code, nicht in der DB)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "chat_messages", "document_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_chat_messages_case_id", "chat_messages", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_case_id", table_name="chat_messages")
    op.drop_column("chat_messages", "case_id")
    # document_id wieder not-null setzen: NUR moeglich wenn keine Case-Messages
    # (case_id nicht mehr da). Annahme: wenn downgrade laeuft, gibt's keine.
    op.alter_column(
        "chat_messages", "document_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
