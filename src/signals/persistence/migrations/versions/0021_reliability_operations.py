"""Add acquisition operational incidents and dead letters.

Revision ID: 0021_reliability_operations
Revises: 0020_hermes_learning_loop
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_reliability_operations"
down_revision = "0020_hermes_learning_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_operational_incident",
        sa.Column("incident_ref", sa.String(64), primary_key=True),
        sa.Column("trigger_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("incident_version", sa.String(64), nullable=False),
        sa.Column("incident_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_ref", sa.String(256), nullable=False),
        sa.Column("source_state_ref", sa.String(256), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_value", sa.Numeric(24, 8)),
        sa.Column("threshold_value", sa.Numeric(24, 8)),
        sa.Column("metric_version", sa.String(64)),
        sa.Column("reason_codes", sa.JSON, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("human_review_required", sa.Boolean, nullable=False),
        sa.Column("pause_required", sa.Boolean, nullable=False),
        sa.Column("policy_control_before", sa.String(64)),
        sa.Column("policy_control_after", sa.String(64)),
        sa.Column("campaign_ref", sa.String(64)),
        sa.Column("mailbox_ref", sa.String(100)),
        sa.Column("wedge", sa.String(100)),
        sa.Column("country", sa.String(2)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_ref"], ["acquisition_campaign.campaign_ref"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "incident_type IN ('BOUNCE_RATE', 'COMPLAINT', 'COMPLIANCE_FAILURE', "
            "'PROVIDER_FAILURE', 'UNEXPECTED_TRANSPORT_TRUTH', 'BUDGET_BREACH', "
            "'COST_DRIFT', 'CONVERSION_DEGRADATION', 'RETENTION_DEGRADATION', "
            "'MAILBOX_UNAVAILABLE')",
            name="ck_operational_incident_type",
        ),
        sa.CheckConstraint(
            "severity IN ('WARNING', 'HIGH', 'CRITICAL')",
            name="ck_operational_incident_severity",
        ),
        sa.CheckConstraint(
            "scope_type IN ('GLOBAL', 'COUNTRY', 'WEDGE', 'CAMPAIGN', 'MAILBOX')",
            name="ck_operational_incident_scope",
        ),
        sa.CheckConstraint(
            "state IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')",
            name="ck_operational_incident_state",
        ),
        sa.CheckConstraint(
            "(state = 'OPEN' AND acknowledged_at IS NULL AND resolved_at IS NULL) OR "
            "(state = 'ACKNOWLEDGED' AND acknowledged_at IS NOT NULL AND resolved_at IS NULL) OR "
            "(state = 'RESOLVED' AND resolved_at IS NOT NULL)",
            name="ck_operational_incident_lifecycle",
        ),
        sa.CheckConstraint(
            "country IS NULL OR country IN ('CH', 'FR')",
            name="ck_operational_incident_country",
        ),
    )
    op.create_index(
        "ix_operational_incident_open_scope",
        "acquisition_operational_incident",
        ["scope_type", "scope_ref", "severity"],
        sqlite_where=sa.text("state <> 'RESOLVED'"),
        postgresql_where=sa.text("state <> 'RESOLVED'"),
    )
    op.create_index(
        "ix_operational_incident_campaign",
        "acquisition_operational_incident",
        ["campaign_ref", "triggered_at"],
    )

    op.create_table(
        "acquisition_dead_letter",
        sa.Column("dead_letter_ref", sa.String(64), primary_key=True),
        sa.Column("exhaustion_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("work_type", sa.String(64), nullable=False),
        sa.Column("work_ref", sa.String(256), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_ref", sa.String(256), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_code", sa.String(100), nullable=False),
        sa.Column("retry_policy_version", sa.String(64), nullable=False),
        sa.Column("source_component", sa.String(64), nullable=False),
        sa.Column("source_state_ref", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requeued_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "work_type IN ('SUPERVISOR_CYCLE', 'SUPPLIER_DISCOVERY', "
            "'CONTACT_DISCOVERY', 'COMPANY_RESEARCH', 'CAMPAIGN_PROVIDER_OPERATION', "
            "'RESPONSE_RESOLUTION', 'CONVERSION_RECONCILIATION', 'LEARNING_CYCLE')",
            name="ck_dead_letter_work_type",
        ),
        sa.CheckConstraint(
            "scope_type IN ('GLOBAL', 'COUNTRY', 'WEDGE', 'CAMPAIGN', 'MAILBOX')",
            name="ck_dead_letter_scope",
        ),
        sa.CheckConstraint("attempt_count >= 1", name="ck_dead_letter_attempt_count"),
        sa.CheckConstraint(
            "first_failed_at <= last_failed_at", name="ck_dead_letter_failure_window"
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'REQUEUED', 'RESOLVED')", name="ck_dead_letter_status"
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND requeued_at IS NULL AND resolved_at IS NULL) OR "
            "(status = 'REQUEUED' AND requeued_at IS NOT NULL AND resolved_at IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL)",
            name="ck_dead_letter_lifecycle",
        ),
    )
    op.create_index(
        "ix_dead_letter_status_created",
        "acquisition_dead_letter",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_dead_letter_work",
        "acquisition_dead_letter",
        ["work_type", "work_ref"],
    )


def downgrade() -> None:
    op.drop_table("acquisition_dead_letter")
    op.drop_table("acquisition_operational_incident")
