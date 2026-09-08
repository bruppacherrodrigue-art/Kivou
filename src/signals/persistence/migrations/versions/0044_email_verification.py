"""Separate email possession from attribution and session authentication."""
import sqlalchemy as sa
from alembic import op

revision = "0044_email_verification"
down_revision = "0043_qa_landing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_identity",
        sa.Column("user_id", sa.String(64), sa.ForeignKey("auth_user.user_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("verified_email", sa.String(320)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("pending_email", sa.String(320)),
        sa.Column("token_hash", sa.String(64), unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "attribution_recipient",
        sa.Column("nonce", sa.String(64), primary_key=True),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("attribution_recipient")
    op.drop_table("email_identity")
