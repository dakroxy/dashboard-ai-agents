"""Steckbrief-Cluster-4: Technik-Felder (Absperrpunkte, Heizung, Historie)

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-23

Erweitert die Objekt-Tabelle um die Inline-Edit-Felder aus Story 1.6:

  * objects.shutoff_water_location        — Wasser-Absperrung (Freitext)
  * objects.shutoff_electricity_location  — Strom-Absperrung (Freitext)
  * objects.shutoff_gas_location          — Gas-Absperrung (Freitext)
  * objects.heating_type                  — Heizungs-Typ (Freitext)
  * objects.year_heating                  — Baujahr Heizung (Integer)
  * objects.heating_company               — Wartungsfirma (Freitext)
  * objects.heating_hotline               — Stoerungs-Hotline (Freitext)
  * objects.year_electrics                — Jahr Elektrik-Check (Integer)

Alle Spalten sind nullable und ohne Default — bestehende Rows bleiben
unveraendert, die Felder werden vom User per Inline-Edit gepflegt.

Keine neuen Indexes: Technik-Felder werden nicht fuer Portfolio-Sortierung
oder Filter verwendet. Speicher sparen + Migration fokussiert halten.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Absperrpunkte (Standortbeschreibung als Freitext)
    op.add_column(
        "objects",
        sa.Column("shutoff_water_location", sa.String(), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("shutoff_electricity_location", sa.String(), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("shutoff_gas_location", sa.String(), nullable=True),
    )

    # Heizungs-Steckbrief
    op.add_column(
        "objects",
        sa.Column("heating_type", sa.String(), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("year_heating", sa.Integer(), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("heating_company", sa.String(), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("heating_hotline", sa.String(), nullable=True),
    )

    # Objekt-Historie (year_built + year_roof existieren schon aus 0010)
    op.add_column(
        "objects",
        sa.Column("year_electrics", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("objects", "year_electrics")
    op.drop_column("objects", "heating_hotline")
    op.drop_column("objects", "heating_company")
    op.drop_column("objects", "year_heating")
    op.drop_column("objects", "heating_type")
    op.drop_column("objects", "shutoff_gas_location")
    op.drop_column("objects", "shutoff_electricity_location")
    op.drop_column("objects", "shutoff_water_location")
