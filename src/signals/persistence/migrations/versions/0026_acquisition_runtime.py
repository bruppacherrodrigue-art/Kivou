"""Add the bounded acquisition runtime and QA transport identity binding.

Revision ID: 0026_acquisition_runtime
Revises: 0024_scheduled_plan_change

The temporary parent is the current branch head. Before publication this
migration is rebased logically onto the transactional-delivery migration so
the deployed Alembic history remains strictly linear.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_acquisition_runtime"
down_revision = "0024_scheduled_plan_change"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name, constraint_name in (
        (
            "supplier_discovery_run",
            "ck_supplier_discovery_run_recovery_calls",
        ),
        ("contact_discovery_run", "ck_contact_run_recovery_calls"),
        ("company_research_run", "ck_company_run_recovery_calls"),
    ):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(
                sa.Column(
                    "recovery_provider_calls",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
            batch.create_check_constraint(
                constraint_name,
                "recovery_provider_calls >= 0 AND recovery_provider_calls <= 1",
            )
    op.add_column(
        "acquisition_policy_snapshot",
        sa.Column("qa_signal_ref", sa.String(256), nullable=True),
    )
    op.create_table(
        "acquisition_runtime_lease",
        sa.Column("lease_name", sa.String(64), primary_key=True),
        sa.Column("owner_ref", sa.String(256)),
        sa.Column("acquired_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.CheckConstraint(
            "generation >= 0",
            name="ck_acquisition_runtime_lease_generation",
        ),
        sa.CheckConstraint(
            "(owner_ref IS NULL AND acquired_at IS NULL AND heartbeat_at IS NULL "
            "AND expires_at IS NULL) OR "
            "(owner_ref IS NOT NULL AND acquired_at IS NOT NULL "
            "AND heartbeat_at IS NOT NULL AND expires_at IS NOT NULL "
            "AND acquired_at <= heartbeat_at AND heartbeat_at < expires_at)",
            name="ck_acquisition_runtime_lease_lifecycle",
        ),
    )
    op.create_table(
        "acquisition_runtime_cycle",
        sa.Column("cycle_ref", sa.String(64), primary_key=True),
        sa.Column("opportunity_key", sa.String(256), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("next_stage", sa.String(32)),
        sa.Column("spent_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("last_reason_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "opportunity_key",
            "config_fingerprint",
            name="uq_acquisition_runtime_cycle_config_opportunity",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING', 'SUCCEEDED', "
            "'BLOCKED', 'FAILED', 'SUPPRESSED', 'CANCELLED')",
            name="ck_acquisition_runtime_cycle_status",
        ),
        sa.CheckConstraint(
            "next_stage IS NULL OR next_stage IN "
            "('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
            "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
            "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
            "'ATTRIBUTION_CONVERSION')",
            name="ck_acquisition_runtime_cycle_next_stage",
        ),
        sa.CheckConstraint(
            "spent_cost >= 0",
            name="ck_acquisition_runtime_cycle_cost",
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCEEDED', 'SUPPRESSED') AND completed_at IS NOT NULL "
            "AND next_stage IS NULL) OR "
            "(status NOT IN ('SUCCEEDED', 'SUPPRESSED') AND completed_at IS NULL)",
            name="ck_acquisition_runtime_cycle_lifecycle",
        ),
    )
    op.create_index(
        "ix_acquisition_runtime_cycle_status",
        "acquisition_runtime_cycle",
        ["status", "updated_at"],
    )
    op.create_table(
        "acquisition_runtime_observation",
        sa.Column("runtime_name", sa.String(64), primary_key=True),
        sa.Column("capability_fingerprint", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("qa_only", sa.Boolean(), nullable=False),
        sa.Column("hermes_repository", sa.String(256), nullable=False),
        sa.Column("hermes_tag", sa.String(256), nullable=False),
        sa.Column("hermes_commit", sa.String(40), nullable=False),
        sa.Column("hermes_version", sa.String(256), nullable=False),
        sa.Column("hermes_python_contract", sa.String(256), nullable=False),
        sa.Column("registry_identity", sa.String(64), nullable=False),
        sa.Column("native_tools", sa.Integer(), nullable=False),
        sa.Column("commands", sa.JSON(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_cycle_ref",
            sa.String(64),
            sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="RESTRICT"),
        ),
        sa.Column("last_cycle_status", sa.String(16)),
        sa.Column("last_cycle_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "runtime_name = 'acquisition-run-once'",
            name="ck_acquisition_runtime_observation_name",
        ),
        sa.CheckConstraint(
            "environment = 'STAGING' AND mode = 'SHADOW' "
            "AND qa_only IS TRUE AND native_tools = 0",
            name="ck_acquisition_runtime_observation_boundary",
        ),
        sa.CheckConstraint(
            "observed_at <= heartbeat_at AND heartbeat_at <= updated_at",
            name="ck_acquisition_runtime_observation_timeline",
        ),
        sa.CheckConstraint(
            "(last_cycle_ref IS NULL AND last_cycle_status IS NULL "
            "AND last_cycle_at IS NULL) OR "
            "(last_cycle_ref IS NOT NULL AND last_cycle_status IS NOT NULL "
            "AND last_cycle_at IS NOT NULL AND last_cycle_at <= heartbeat_at)",
            name="ck_acquisition_runtime_observation_cycle",
        ),
        sa.CheckConstraint(
            "last_cycle_status IS NULL OR last_cycle_status IN "
            "('PENDING', 'RUNNING', 'WAITING', 'SUCCEEDED', 'BLOCKED', "
            "'FAILED', 'SUPPRESSED', 'CANCELLED')",
            name="ck_acquisition_runtime_observation_cycle_status",
        ),
    )
    op.create_index(
        "ix_acquisition_runtime_observation_heartbeat",
        "acquisition_runtime_observation",
        ["heartbeat_at"],
    )
    op.create_table(
        "acquisition_runtime_approval",
        sa.Column("approval_id", sa.String(64), primary_key=True),
        sa.Column("request_ref", sa.String(256), nullable=False, unique=True),
        sa.Column(
            "cycle_ref",
            sa.String(64),
            sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("command", sa.String(64), nullable=False),
        sa.Column("target_ref", sa.String(256), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(256), nullable=False),
        sa.Column("action_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(256), nullable=False),
        sa.Column("policy_snapshot_id", sa.String(256), nullable=False),
        sa.Column("control_revision", sa.Integer, nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("binding_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_actor_ref", sa.String(256)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_by_ref", sa.String(256)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stage IN ('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
            "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
            "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
            "'ATTRIBUTION_CONVERSION')",
            name="ck_acquisition_runtime_approval_stage",
        ),
        sa.CheckConstraint(
            "purpose IN ('ACTION', 'COMPLIANCE_REVIEW')",
            name="ck_acquisition_runtime_approval_purpose",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'APPROVED', 'CONSUMED')",
            name="ck_acquisition_runtime_approval_state",
        ),
        sa.CheckConstraint(
            "control_revision >= 1",
            name="ck_acquisition_runtime_approval_revision",
        ),
        sa.CheckConstraint(
            "requested_at < expires_at AND updated_at >= requested_at",
            name="ck_acquisition_runtime_approval_window",
        ),
        sa.CheckConstraint(
            "(state = 'PENDING' AND approved_by_actor_ref IS NULL "
            "AND approved_at IS NULL AND consumed_by_ref IS NULL "
            "AND consumed_at IS NULL) OR "
            "(state = 'APPROVED' AND approved_by_actor_ref IS NOT NULL "
            "AND approved_at IS NOT NULL AND requested_at <= approved_at "
            "AND approved_at < expires_at AND consumed_by_ref IS NULL "
            "AND consumed_at IS NULL) OR "
            "(state = 'CONSUMED' AND approved_by_actor_ref IS NOT NULL "
            "AND approved_at IS NOT NULL AND consumed_by_ref IS NOT NULL "
            "AND consumed_at IS NOT NULL AND requested_at <= approved_at "
            "AND approved_at <= consumed_at AND consumed_at < expires_at)",
            name="ck_acquisition_runtime_approval_lifecycle",
        ),
    )
    op.create_index(
        "ix_acquisition_runtime_approval_state_expiry",
        "acquisition_runtime_approval",
        ["state", "expires_at"],
    )
    op.create_table(
        "acquisition_runtime_stage",
        sa.Column(
            "cycle_ref",
            sa.String(64),
            sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("stage", sa.String(32), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("plan_ref", sa.String(256)),
        sa.Column("command", sa.String(64)),
        sa.Column("argument_fingerprint", sa.String(64)),
        sa.Column("result_refs", sa.JSON, nullable=False),
        sa.Column("reserved_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("observed_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("reason_codes", sa.JSON, nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("replay_same_attempt", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stage IN ('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
            "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
            "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
            "'ATTRIBUTION_CONVERSION')",
            name="ck_acquisition_runtime_stage_name",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING', 'SUCCEEDED', "
            "'BLOCKED', 'FAILED', 'SUPPRESSED', 'CANCELLED')",
            name="ck_acquisition_runtime_stage_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_acquisition_runtime_stage_attempts",
        ),
        sa.CheckConstraint(
            "reserved_cost >= 0 AND observed_cost >= 0",
            name="ck_acquisition_runtime_stage_cost",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND attempt_count = 0 AND started_at IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'RUNNING' AND attempt_count >= 1 AND started_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status NOT IN ('PENDING', 'RUNNING') AND attempt_count >= 1 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_acquisition_runtime_stage_lifecycle",
        ),
        sa.CheckConstraint(
            "retry_at IS NULL OR status = 'WAITING'",
            name="ck_acquisition_runtime_stage_retry",
        ),
        sa.CheckConstraint(
            "replay_same_attempt IS FALSE OR "
            "(status = 'WAITING' AND retry_at IS NOT NULL)",
            name="ck_acquisition_runtime_stage_replay",
        ),
    )
    op.create_index(
        "ix_acquisition_runtime_stage_status",
        "acquisition_runtime_stage",
        ["status", "updated_at"],
    )
    op.create_table(
        "acquisition_runtime_stage_attempt",
        sa.Column(
            "cycle_ref",
            sa.String(64),
            sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("stage", sa.String(32), primary_key=True),
        sa.Column("attempt_count", sa.Integer, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reserved_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("observed_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("proposal", sa.JSON()),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("replay_same_attempt", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "stage IN ('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
            "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
            "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
            "'ATTRIBUTION_CONVERSION')",
            name="ck_acquisition_runtime_attempt_stage",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'WAITING', 'SUCCEEDED', 'BLOCKED', 'FAILED', "
            "'SUPPRESSED', 'CANCELLED')",
            name="ck_acquisition_runtime_attempt_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 1",
            name="ck_acquisition_runtime_attempt_count",
        ),
        sa.CheckConstraint(
            "reserved_cost >= 0 AND observed_cost >= 0",
            name="ck_acquisition_runtime_attempt_cost",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL) OR "
            "(status <> 'RUNNING' AND completed_at IS NOT NULL)",
            name="ck_acquisition_runtime_attempt_lifecycle",
        ),
        sa.CheckConstraint(
            "retry_at IS NULL OR status = 'WAITING'",
            name="ck_acquisition_runtime_attempt_retry",
        ),
        sa.CheckConstraint(
            "replay_same_attempt IS FALSE OR "
            "(status = 'WAITING' AND retry_at IS NOT NULL)",
            name="ck_acquisition_runtime_attempt_replay",
        ),
    )
    op.create_index(
        "ix_acquisition_runtime_attempt_cycle",
        "acquisition_runtime_stage_attempt",
        ["cycle_ref", "completed_at"],
    )
    with op.batch_alter_table("acquisition_campaign_member") as batch:
        batch.add_column(sa.Column("transport_recipient_identity", sa.String(64)))
        batch.add_column(sa.Column("transport_recipient_key_version", sa.String(64)))
        batch.create_check_constraint(
            "ck_campaign_member_transport_identity",
            "(transport_recipient_identity IS NULL AND "
            "transport_recipient_key_version IS NULL) OR "
            "(transport_recipient_identity IS NOT NULL AND "
            "transport_recipient_key_version IS NOT NULL)",
        )
    op.create_index(
        "ix_campaign_member_transport_identity",
        "acquisition_campaign_member",
        [
            "campaign_ref",
            "transport_recipient_key_version",
            "transport_recipient_identity",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_member_transport_identity",
        table_name="acquisition_campaign_member",
    )
    with op.batch_alter_table("acquisition_campaign_member") as batch:
        batch.drop_constraint(
            "ck_campaign_member_transport_identity",
            type_="check",
        )
        batch.drop_column("transport_recipient_key_version")
        batch.drop_column("transport_recipient_identity")
    op.drop_index(
        "ix_acquisition_runtime_attempt_cycle",
        table_name="acquisition_runtime_stage_attempt",
    )
    op.drop_table("acquisition_runtime_stage_attempt")
    op.drop_index(
        "ix_acquisition_runtime_stage_status",
        table_name="acquisition_runtime_stage",
    )
    op.drop_table("acquisition_runtime_stage")
    op.drop_index(
        "ix_acquisition_runtime_approval_state_expiry",
        table_name="acquisition_runtime_approval",
    )
    op.drop_table("acquisition_runtime_approval")
    op.drop_index(
        "ix_acquisition_runtime_observation_heartbeat",
        table_name="acquisition_runtime_observation",
    )
    op.drop_table("acquisition_runtime_observation")
    op.drop_index(
        "ix_acquisition_runtime_cycle_status",
        table_name="acquisition_runtime_cycle",
    )
    op.drop_table("acquisition_runtime_cycle")
    op.drop_table("acquisition_runtime_lease")
    op.drop_column("acquisition_policy_snapshot", "qa_signal_ref")
    for table_name, constraint_name in (
        ("company_research_run", "ck_company_run_recovery_calls"),
        ("contact_discovery_run", "ck_contact_run_recovery_calls"),
        (
            "supplier_discovery_run",
            "ck_supplier_discovery_run_recovery_calls",
        ),
    ):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(constraint_name, type_="check")
            batch.drop_column("recovery_provider_calls")
