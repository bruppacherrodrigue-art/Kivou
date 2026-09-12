"""Persist per-usage model budgets and every provider call.

Revision ID: 0058_model_call_budget
Revises: 0057_directory_contact_keys
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0058_model_call_budget"
down_revision = "0057_directory_contact_keys"
branch_labels = None
depends_on = None

_USAGES = (
    "enrichment_judge",
    "enrichment_arbiter",
    "for_you",
    "hermes",
    "document_classifier",
)
_USAGE_SQL = ", ".join(f"'{usage}'" for usage in _USAGES)


def upgrade() -> None:
    op.create_table(
        "model_daily_budget",
        sa.Column("usage_date", sa.Date, primary_key=True),
        sa.Column("usage", sa.String(64), primary_key=True),
        sa.Column("reserved_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("actual_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"usage IN ({_USAGE_SQL})", name="ck_model_daily_budget_usage"),
        sa.CheckConstraint("reserved_usd >= 0", name="ck_model_daily_budget_reserved_cost"),
        sa.CheckConstraint("actual_usd >= 0", name="ck_model_daily_budget_actual_cost"),
    )
    op.create_table(
        "model_call_journal",
        sa.Column("call_id", sa.String(36), primary_key=True),
        sa.Column("usage", sa.String(64), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column(
            "siren",
            sa.String(9),
            sa.ForeignKey("supplier_directory.siren", ondelete="SET NULL"),
        ),
        sa.Column("batch_id", sa.String(64)),
        sa.Column("reserved_usd", sa.Numeric(14, 8), nullable=False),
        sa.Column("actual_usd", sa.Numeric(14, 8)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"usage IN ({_USAGE_SQL})", name="ck_model_call_usage"),
        sa.CheckConstraint("reserved_usd >= 0", name="ck_model_call_reserved_cost"),
        sa.CheckConstraint(
            "actual_usd IS NULL OR actual_usd >= 0", name="ck_model_call_actual_cost"
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_model_call_input_tokens"
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_model_call_output_tokens",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'succeeded', 'failed', 'rejected_budget')",
            name="ck_model_call_status",
        ),
    )
    op.create_index("ix_model_call_usage_called_at", "model_call_journal", ["usage", "called_at"])
    op.create_index("ix_model_call_siren_called_at", "model_call_journal", ["siren", "called_at"])
    op.create_index("ix_model_call_batch_id", "model_call_journal", ["batch_id"])
    with op.batch_alter_table("supplier_directory") as batch_op:
        batch_op.add_column(sa.Column("enrichment_call_id", sa.String(36)))
        batch_op.create_foreign_key(
            "fk_supplier_directory_enrichment_call",
            "model_call_journal",
            ["enrichment_call_id"],
            ["call_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch_op:
        batch_op.drop_constraint("fk_supplier_directory_enrichment_call", type_="foreignkey")
        batch_op.drop_column("enrichment_call_id")
    op.drop_index("ix_model_call_batch_id", table_name="model_call_journal")
    op.drop_index("ix_model_call_siren_called_at", table_name="model_call_journal")
    op.drop_index("ix_model_call_usage_called_at", table_name="model_call_journal")
    op.drop_table("model_call_journal")
    op.drop_table("model_daily_budget")
