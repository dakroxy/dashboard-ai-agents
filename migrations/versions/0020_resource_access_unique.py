"""resource_access: partial unique indexes + dedup

Schliesst Multi-Worker-Boot-Race in `_seed_default_workflow_access`
(Story 5-2 Code-Review F4): SELECT-then-INSERT ohne UNIQUE liess unter
Multi-Worker-Boot Duplikate (role_id, resource_type, resource_id)
entstehen. Zwei partial unique indexes — getrennt fuer role- und
user-Zweig — entsprechen dem CheckConstraint
`ck_resource_access_role_xor_user`.

Vor Index-Anlage werden vorhandene Duplikate dedupliziert (kleinste id
pro Gruppe bleibt), damit die Migration auf produktiven Stands nicht
auf einem nicht-leeren Cluster scheitert.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Vorhandene Duplikate raeumen (kleinste id pro Tripel bleibt erhalten).
    op.execute(
        """
        DELETE FROM resource_access ra
        USING resource_access ra2
        WHERE ra.role_id IS NOT NULL
          AND ra.role_id = ra2.role_id
          AND ra.resource_type = ra2.resource_type
          AND ra.resource_id = ra2.resource_id
          AND ra.id > ra2.id
        """
    )
    op.execute(
        """
        DELETE FROM resource_access ra
        USING resource_access ra2
        WHERE ra.user_id IS NOT NULL
          AND ra.user_id = ra2.user_id
          AND ra.resource_type = ra2.resource_type
          AND ra.resource_id = ra2.resource_id
          AND ra.id > ra2.id
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_resource_access_role_resource
        ON resource_access (role_id, resource_type, resource_id)
        WHERE role_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_resource_access_user_resource
        ON resource_access (user_id, resource_type, resource_id)
        WHERE user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_resource_access_user_resource")
    op.execute("DROP INDEX IF EXISTS uq_resource_access_role_resource")
