"""Steckbrief-Finance + Mirror-Fields: Cluster-6-Finanzen + impower_contact_id

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-22

Erweitert das Steckbrief-Datenmodell um die Felder, die der Impower-Nightly-
Mirror (Story 1.4) aus Cluster 1 + 6 spiegelt:

  * objects.reserve_current       — Ruecklage-Saldo (NUMERIC 12,2)
  * objects.reserve_target        — Ruecklage-Zielwert monatlich (NUMERIC 12,2)
  * objects.wirtschaftsplan_status — RESOLVED/IN_PREPARATION/... als lowercase-String
  * objects.sepa_mandate_refs     — JSONB-Liste {mandate_id, bank_account_id, state}
  * eigentuemer.impower_contact_id — Fuer Reconcile-Match pro Objekt, composite Index

`last_known_balance` bleibt wie in 0010 — der Live-Saldo-Pull kommt mit Story 1.5
und haengt nicht am Mirror.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "objects",
        sa.Column("reserve_current", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("reserve_target", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("wirtschaftsplan_status", sa.String(), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column(
            "sepa_mandate_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.add_column(
        "eigentuemer",
        sa.Column("impower_contact_id", sa.String(), nullable=True),
    )
    # Composite-Index fuer Reconcile-Match per Objekt. Nicht unique — Impower
    # koennte theoretisch denselben Contact zweimal als Owner fuehren, das
    # soll keinen Insert abbrechen lassen.
    op.create_index(
        "ix_eigentuemer_impower_contact",  # ix_<table>_<col> ohne _id-Suffix — bewusst kuerzer; kein Rename (DB-Op ohne fachlichen Mehrwert)
        "eigentuemer",
        ["object_id", "impower_contact_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eigentuemer_impower_contact", table_name="eigentuemer"
    )
    op.drop_column("eigentuemer", "impower_contact_id")

    op.drop_column("objects", "sepa_mandate_refs")
    op.drop_column("objects", "wirtschaftsplan_status")
    op.drop_column("objects", "reserve_target")
    op.drop_column("objects", "reserve_current")
