"""Global replay index for minimal program conversion events."""

import sqlalchemy as sa
from alembic import op

revision = "0070_program_conversion_receipt"
down_revision = "0069_milomail_suppression_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_program_conversion_receipt",
        sa.Column("receipt_id", sa.String(64), primary_key=True),
        sa.Column("program_id", sa.String(64), sa.ForeignKey("acquisition_program.program_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attribution_id", sa.String(64), sa.ForeignKey("acquisition_program_attribution.attribution_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id_hash", sa.String(64), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("recorded_event_id", sa.String(64), sa.ForeignKey("acquisition_event.event_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("program_id", "event_id_hash", name="uq_program_conversion_event_identity"),
    )
    op.create_index(
        "ix_program_conversion_attribution", "acquisition_program_conversion_receipt",
        ["attribution_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_program_conversion_attribution", table_name="acquisition_program_conversion_receipt")
    op.drop_table("acquisition_program_conversion_receipt")
