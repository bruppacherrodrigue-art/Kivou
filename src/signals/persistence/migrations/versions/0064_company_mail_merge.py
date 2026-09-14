"""Join V11 company data and the upstream mail contract without altering either."""

revision = "0064_company_mail_merge"
down_revision = ("0063_catalogue_mirror", "0059_prospect_mail_word_limit_v2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
