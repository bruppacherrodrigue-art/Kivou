"""Allow a separate Milo Mail brand scope in the existing suppression ledger."""

from alembic import op

revision = "0069_milomail_suppression_scope"
down_revision = "0068_acquisition_program"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("acquisition_contact_suppression") as batch:
        batch.drop_constraint("ck_suppression_scope", type_="check")
        batch.create_check_constraint(
            "ck_suppression_scope",
            "scope IN ('KIVOU_ACQUISITION_EMAIL', 'MILOMAIL_ACQUISITION_EMAIL')",
        )


def downgrade() -> None:
    # Downgrade is safe only after Milo Mail suppressions have been removed from
    # this disposable/test database. Production downgrade requires data review.
    with op.batch_alter_table("acquisition_contact_suppression") as batch:
        batch.drop_constraint("ck_suppression_scope", type_="check")
        batch.create_check_constraint(
            "ck_suppression_scope", "scope = 'KIVOU_ACQUISITION_EMAIL'"
        )
