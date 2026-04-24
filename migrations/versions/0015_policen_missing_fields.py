"""policen: produkt_typ + start_date + end_date + notice_period_months"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("policen",
        sa.Column("produkt_typ", sa.String(), nullable=True))
    op.add_column("policen",
        sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("policen",
        sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("policen",
        sa.Column("notice_period_months", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("policen", "notice_period_months")
    op.drop_column("policen", "end_date")
    op.drop_column("policen", "start_date")
    op.drop_column("policen", "produkt_typ")
