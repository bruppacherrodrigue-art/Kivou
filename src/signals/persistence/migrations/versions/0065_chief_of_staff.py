"""Add append-only Chief of Staff reports, attempts, and model usage.

Revision ID: 0065_chief_of_staff
Revises: 0064_company_mail_merge
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0065_chief_of_staff"
down_revision = "0064_company_mail_merge"
branch_labels = None
depends_on = None

_USAGES = (
    "enrichment_judge",
    "enrichment_arbiter",
    "for_you",
    "hermes",
    "document_classifier",
    "chief_of_staff",
)
_USAGE_SQL = ", ".join(f"'{usage}'" for usage in _USAGES)


def _extend_model_usage_constraints() -> None:
    with op.batch_alter_table("model_daily_budget") as batch_op:
        batch_op.drop_constraint("ck_model_daily_budget_usage", type_="check")
        batch_op.create_check_constraint(
            "ck_model_daily_budget_usage", f"usage IN ({_USAGE_SQL})"
        )
    with op.batch_alter_table("model_call_journal") as batch_op:
        batch_op.drop_constraint("ck_model_call_usage", type_="check")
        batch_op.create_check_constraint("ck_model_call_usage", f"usage IN ({_USAGE_SQL})")


def upgrade() -> None:
    _extend_model_usage_constraints()
    op.create_table(
        "chief_of_staff_report",
        sa.Column("report_ref", sa.String(256), primary_key=True),
        sa.Column("report_version", sa.String(64), nullable=False),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("business_memory_version", sa.String(64), nullable=False),
        sa.Column("profile_version", sa.String(64), nullable=False),
        sa.Column("supervisor_version", sa.String(64), nullable=False),
        sa.Column("model_route", sa.String(256), nullable=False),
        sa.Column("validated_report", sa.JSON, nullable=False),
        sa.Column("evidence_facts", sa.JSON, nullable=False),
        sa.Column("usage_metadata", sa.JSON, nullable=False),
        sa.Column("estimated_cost", sa.Numeric(14, 8), nullable=False),
        sa.Column("actual_cost", sa.Numeric(14, 8)),
        sa.Column(
            "model_call_id",
            sa.String(36),
            sa.ForeignKey("model_call_journal.call_id", ondelete="SET NULL"),
        ),
        sa.CheckConstraint(
            "cadence IN ('DAILY', 'WEEKLY', 'ON_DEMAND')",
            name="ck_chief_of_staff_report_cadence",
        ),
        sa.CheckConstraint(
            "period_end > period_start", name="ck_chief_of_staff_report_period"
        ),
        sa.CheckConstraint(
            "estimated_cost >= 0", name="ck_chief_of_staff_report_estimated_cost"
        ),
        sa.CheckConstraint(
            "actual_cost IS NULL OR actual_cost >= 0",
            name="ck_chief_of_staff_report_actual_cost",
        ),
        sa.UniqueConstraint(
            "context_fingerprint",
            "report_version",
            "business_memory_version",
            "profile_version",
            "supervisor_version",
            name="uq_chief_of_staff_report_semantic",
        ),
    )
    op.create_index(
        "ix_chief_of_staff_report_cadence_captured",
        "chief_of_staff_report",
        ["cadence", "captured_at"],
    )
    op.create_index(
        "ix_chief_of_staff_report_captured",
        "chief_of_staff_report",
        ["captured_at"],
    )
    op.create_table(
        "chief_of_staff_attempt",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_route", sa.String(256), nullable=False),
        sa.Column(
            "model_call_id",
            sa.String(36),
            sa.ForeignKey("model_call_journal.call_id", ondelete="SET NULL"),
        ),
        sa.Column("reserved_usd", sa.Numeric(14, 8), nullable=False),
        sa.Column("actual_usd", sa.Numeric(14, 8)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("result_code", sa.String(100), nullable=False),
        sa.Column("profile_version", sa.String(64), nullable=False),
        sa.Column("context_version", sa.String(64), nullable=False),
        sa.Column("expected_report_version", sa.String(64), nullable=False),
        sa.Column("hermes_version", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "cadence IN ('DAILY', 'WEEKLY', 'ON_DEMAND')",
            name="ck_chief_of_staff_attempt_cadence",
        ),
        sa.CheckConstraint(
            "period_end > period_start", name="ck_chief_of_staff_attempt_period"
        ),
        sa.CheckConstraint(
            "completed_at >= started_at", name="ck_chief_of_staff_attempt_timing"
        ),
        sa.CheckConstraint(
            "status IN ('PROVIDER_FAILED', 'RESPONSE_REJECTED', "
            "'SEMANTICALLY_REJECTED', 'VALIDATED_NOT_PERSISTED', "
            "'VALIDATED_PERSISTED', 'IDEMPOTENT_EXISTING')",
            name="ck_chief_of_staff_attempt_status",
        ),
        sa.CheckConstraint(
            "stage IN ('PROVIDER_CALL', 'STRUCTURED_RESPONSE', "
            "'SEMANTIC_VALIDATION', 'PERSISTENCE', 'COMPLETE')",
            name="ck_chief_of_staff_attempt_stage",
        ),
        sa.CheckConstraint(
            "reserved_usd >= 0", name="ck_chief_of_staff_attempt_reserved"
        ),
        sa.CheckConstraint(
            "actual_usd IS NULL OR actual_usd >= 0",
            name="ck_chief_of_staff_attempt_actual",
        ),
    )
    op.create_index(
        "ix_chief_of_staff_attempt_context_started",
        "chief_of_staff_attempt",
        ["context_fingerprint", "started_at"],
    )
    op.create_index(
        "ix_chief_of_staff_attempt_status_completed",
        "chief_of_staff_attempt",
        ["status", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chief_of_staff_attempt_status_completed",
        table_name="chief_of_staff_attempt",
    )
    op.drop_index(
        "ix_chief_of_staff_attempt_context_started",
        table_name="chief_of_staff_attempt",
    )
    op.drop_table("chief_of_staff_attempt")
    op.drop_index("ix_chief_of_staff_report_captured", table_name="chief_of_staff_report")
    op.drop_index(
        "ix_chief_of_staff_report_cadence_captured", table_name="chief_of_staff_report"
    )
    op.drop_table("chief_of_staff_report")
    # The usage constraints deliberately remain additive. Reverting them could
    # require deleting durable cost-audit rows, which this migration forbids.
