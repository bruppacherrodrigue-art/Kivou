"""Add durable Kivou policy controls and evaluation audit."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_policy_gateway"
down_revision = "0007_acquisition_event_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_policy_snapshot",
        sa.Column("policy_snapshot_id", sa.String(64), primary_key=True),
        sa.Column("control_revision", sa.Integer(), nullable=False, unique=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("autonomy_mode", sa.String(32), nullable=False),
        sa.Column("shadow_target_mode", sa.String(32)),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("kill_switch", sa.Boolean(), nullable=False),
        sa.Column("allowed_commands", sa.JSON(), nullable=False),
        sa.Column("allowed_countries", sa.JSON(), nullable=False),
        sa.Column("allowed_languages", sa.JSON(), nullable=False),
        sa.Column("allowed_wedges", sa.JSON(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("daily_cost_cap", sa.Numeric(18, 6), nullable=False),
        sa.Column("daily_volume_cap", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("snapshot_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_actor_type", sa.String(16), nullable=False),
        sa.Column("created_by_actor_ref", sa.String(256), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.CheckConstraint("control_revision >= 1", name="ck_policy_snapshot_revision"),
        sa.CheckConstraint("daily_cost_cap >= 0", name="ck_policy_snapshot_cost"),
        sa.CheckConstraint("daily_volume_cap >= 0", name="ck_policy_snapshot_volume"),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at", name="ck_policy_snapshot_interval"
        ),
    )
    op.create_index(
        "ix_acquisition_policy_snapshot_effective_at",
        "acquisition_policy_snapshot",
        ["effective_at"],
    )
    op.create_table(
        "policy_evaluation",
        sa.Column("evaluation_id", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(64)),
        sa.Column("command", sa.String(64), nullable=False),
        sa.Column("target_ref", sa.String(256), nullable=False),
        sa.Column("action_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("counterfactual_status", sa.String(32)),
        sa.Column("executable", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_snapshot_id", sa.String(64), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("runtime_revision", sa.String(100), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("proposed_volume", sa.Integer(), nullable=False),
        sa.Column("cost_remaining", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume_remaining", sa.Integer(), nullable=False),
        sa.Column("approval_refs", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("requires_revalidation", sa.Boolean(), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id"],
            ["acquisition_policy_snapshot.policy_snapshot_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("estimated_cost >= 0", name="ck_policy_evaluation_cost"),
        sa.CheckConstraint("proposed_volume >= 0", name="ck_policy_evaluation_volume"),
    )
    op.create_index("ix_policy_evaluation_status", "policy_evaluation", ["status"])
    op.create_index("ix_policy_evaluation_evaluated_at", "policy_evaluation", ["evaluated_at"])
    op.create_index(
        "ix_policy_evaluation_opportunity_time",
        "policy_evaluation",
        ["acquisition_opportunity_id", "evaluated_at"],
    )
    op.create_index(
        "ix_policy_evaluation_command_time", "policy_evaluation", ["command", "evaluated_at"]
    )


def downgrade() -> None:
    op.drop_table("policy_evaluation")
    op.drop_table("acquisition_policy_snapshot")
