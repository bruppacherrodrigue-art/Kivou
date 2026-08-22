"""Add sealed campaign batches, members, provider operations, and transport events."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_campaign_factory"
down_revision = "0015_scheduled_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_campaign",
        sa.Column("campaign_ref", sa.String(64), primary_key=True),
        sa.Column("campaign_group_key", sa.String(64), nullable=False),
        sa.Column("batch_generation", sa.Integer(), nullable=False),
        sa.Column("factory_version", sa.String(64), nullable=False),
        sa.Column("plan_fingerprint", sa.String(64), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("wedge", sa.String(100), nullable=False),
        sa.Column("wedge_version", sa.String(64), nullable=False),
        sa.Column("selected_need_category", sa.String(100), nullable=False),
        sa.Column("selected_need_version", sa.String(64), nullable=False),
        sa.Column("personalization_catalog_version", sa.String(64), nullable=False),
        sa.Column("personalization_template_version", sa.String(64), nullable=False),
        sa.Column("language_policy_version", sa.String(64), nullable=False),
        sa.Column("envelope_catalog_version", sa.String(64), nullable=False),
        sa.Column("sender_profile_ref", sa.String(256), nullable=False),
        sa.Column("mailbox_pool_version", sa.String(64), nullable=False),
        sa.Column("compliance_ruleset_fingerprint", sa.String(64), nullable=False),
        sa.Column("sequence_policy_version", sa.String(64), nullable=False),
        sa.Column("tracking_policy_version", sa.String(64), nullable=False),
        sa.Column("send_window_policy_version", sa.String(64), nullable=False),
        sa.Column("sequence_window_policy_version", sa.String(64), nullable=False),
        sa.Column("batch_policy_version", sa.String(64), nullable=False),
        sa.Column("pacing_policy_version", sa.String(64), nullable=False),
        sa.Column("provider_workspace_ref", sa.String(128), nullable=False),
        sa.Column("provider_campaign_name", sa.String(100), nullable=False),
        sa.Column("provider_campaign_id", sa.String(128)),
        sa.Column("desired_provider_config_fingerprint", sa.String(64), nullable=False),
        sa.Column("current_provider_config_fingerprint", sa.String(64)),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("step_1_execution_date", sa.Date(), nullable=False),
        sa.Column("step_1_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_2_execution_date", sa.Date(), nullable=False),
        sa.Column("step_2_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("reserved_member_count", sa.Integer(), nullable=False),
        sa.Column("member_capacity", sa.Integer(), nullable=False),
        sa.Column("first_member_reserved_at", sa.DateTime(timezone=True)),
        sa.Column("membership_close_at", sa.DateTime(timezone=True)),
        sa.Column("membership_closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "campaign_group_key", "batch_generation", name="uq_campaign_group_generation"
        ),
        sa.UniqueConstraint("provider_campaign_id", name="uq_campaign_provider_id"),
        sa.CheckConstraint("batch_generation >= 1", name="ck_campaign_batch_generation"),
        sa.CheckConstraint(
            "country IN ('CH', 'FR') AND jurisdiction IN ('CH', 'FR')",
            name="ck_campaign_country",
        ),
        sa.CheckConstraint("language IN ('fr', 'en')", name="ck_campaign_language"),
        sa.CheckConstraint(
            "lifecycle IN ('BUILDING', 'SEALED', 'ACTIVE', 'PAUSED', 'COMPLETED', 'FAILED')",
            name="ck_campaign_lifecycle",
        ),
        sa.CheckConstraint(
            "member_capacity = 10 AND reserved_member_count >= 0 "
            "AND reserved_member_count <= member_capacity",
            name="ck_campaign_capacity",
        ),
        sa.CheckConstraint(
            "(first_member_reserved_at IS NULL AND membership_close_at IS NULL "
            "AND reserved_member_count = 0) OR "
            "(first_member_reserved_at IS NOT NULL AND membership_close_at IS NOT NULL "
            "AND reserved_member_count >= 1)",
            name="ck_campaign_membership_clock",
        ),
        sa.CheckConstraint(
            "membership_closed_at IS NULL OR membership_close_at IS NOT NULL",
            name="ck_campaign_membership_closed",
        ),
    )
    op.create_index(
        "ix_campaign_group_lifecycle",
        "acquisition_campaign",
        ["campaign_group_key", "lifecycle"],
    )

    op.create_table(
        "acquisition_campaign_member",
        sa.Column("member_ref", sa.String(64), primary_key=True),
        sa.Column("campaign_ref", sa.String(64), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("supplier_ref", sa.String(64), nullable=False),
        sa.Column("contact_ref", sa.String(64), nullable=False),
        sa.Column("personalization_artifact_id", sa.String(64), nullable=False),
        sa.Column("personalization_artifact_fingerprint", sa.String(64), nullable=False),
        sa.Column("compliance_assessment_id", sa.String(64), nullable=False),
        sa.Column("compliance_assessment_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64), nullable=False),
        sa.Column("policy_provenance", sa.JSON(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("contact_provider_identity_binding", sa.String(64), nullable=False),
        sa.Column("plan_fingerprint", sa.String(64), nullable=False),
        sa.Column("envelope_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_action_fingerprint", sa.String(64), nullable=False),
        sa.Column("ruleset_fingerprint", sa.String(64), nullable=False),
        sa.Column("sender_config_fingerprint", sa.String(64), nullable=False),
        sa.Column("mailbox_ref", sa.String(256), nullable=False),
        sa.Column("mailbox_readiness_fingerprint", sa.String(64), nullable=False),
        sa.Column("provider_lead_id", sa.String(128)),
        sa.Column("provider_binding_fingerprint", sa.String(64)),
        sa.Column("step_1_execution_date", sa.Date(), nullable=False),
        sa.Column("step_1_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_2_execution_date", sa.Date(), nullable=False),
        sa.Column("step_2_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence_authorization_fingerprint", sa.String(64), nullable=False),
        sa.Column("step_1_sent_at", sa.DateTime(timezone=True)),
        sa.Column("step_2_due_at", sa.DateTime(timezone=True)),
        sa.Column("sequence_timing_fingerprint", sa.String(64)),
        sa.Column("execution_state", sa.String(16), nullable=False),
        sa.Column("sequence_state", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(100)),
        sa.Column("incident_code", sa.String(100)),
        sa.Column("queue_event_id", sa.String(64)),
        sa.Column("action_clear_event_id", sa.String(64)),
        sa.Column("sent_event_id", sa.String(64)),
        sa.Column("step_1_provider_event_ref", sa.String(64)),
        sa.Column("step_2_provider_event_ref", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_ref"], ["acquisition_campaign.campaign_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_ref"], ["acquisition_supplier.supplier_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_ref"], ["acquisition_contact.contact_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["personalization_artifact_id"],
            ["acquisition_personalization_artifact.personalization_artifact_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["compliance_assessment_id"],
            ["acquisition_compliance_assessment.compliance_assessment_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"],
            ["policy_evaluation.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["queue_event_id"], ["acquisition_event.event_id"]),
        sa.ForeignKeyConstraint(["action_clear_event_id"], ["acquisition_event.event_id"]),
        sa.ForeignKeyConstraint(["sent_event_id"], ["acquisition_event.event_id"]),
        sa.UniqueConstraint(
            "acquisition_opportunity_id", name="uq_campaign_member_opportunity"
        ),
        sa.UniqueConstraint("provider_lead_id", name="uq_campaign_member_provider_lead"),
        sa.UniqueConstraint("policy_evaluation_id", name="uq_campaign_member_policy"),
        sa.CheckConstraint(
            "execution_state IN ('RESERVED', 'ENROLLED', 'QUEUED', 'STOPPED', 'SENT', 'FAILED')",
            name="ck_campaign_member_execution_state",
        ),
        sa.CheckConstraint(
            "sequence_state IN ('PENDING_STEP1', 'WAITING_STEP2', 'COMPLETED', 'STOPPED', 'FAILED')",
            name="ck_campaign_member_sequence_state",
        ),
        sa.CheckConstraint(
            "(sequence_timing_fingerprint IS NULL AND step_1_sent_at IS NULL "
            "AND step_2_due_at IS NULL) OR "
            "(sequence_timing_fingerprint IS NOT NULL AND step_1_sent_at IS NOT NULL "
            "AND step_2_due_at IS NOT NULL)",
            name="ck_campaign_member_timing_write",
        ),
    )
    op.create_index(
        "ix_campaign_member_campaign_state",
        "acquisition_campaign_member",
        ["campaign_ref", "execution_state"],
    )

    op.create_table(
        "acquisition_provider_operation",
        sa.Column("operation_ref", sa.String(64), primary_key=True),
        sa.Column("operation_key", sa.String(64), nullable=False, unique=True),
        sa.Column("operation_version", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("campaign_ref", sa.String(64), nullable=False),
        sa.Column("member_ref", sa.String(64)),
        sa.Column("desired_request_fingerprint", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("provider_identity", sa.String(128)),
        sa.Column("provider_result_fingerprint", sa.String(64)),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_ref"], ["acquisition_campaign.campaign_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["member_ref"], ["acquisition_campaign_member.member_ref"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "kind IN ('CREATE_CAMPAIGN', 'CONFIGURE_CAMPAIGN', 'ADD_LEAD', "
            "'ACTIVATE_CAMPAIGN', 'PAUSE_CAMPAIGN', 'PAUSE_LEAD')",
            name="ck_provider_operation_kind",
        ),
        sa.CheckConstraint(
            "state IN ('PLANNED', 'IN_FLIGHT', 'CONFIRMED', 'RECONCILE_REQUIRED', "
            "'RETRYABLE_FAILED', 'TERMINAL_FAILED')",
            name="ck_provider_operation_state",
        ),
        sa.CheckConstraint(
            "(kind IN ('ADD_LEAD', 'PAUSE_LEAD') AND member_ref IS NOT NULL) OR "
            "(kind NOT IN ('ADD_LEAD', 'PAUSE_LEAD') AND member_ref IS NULL)",
            name="ck_provider_operation_member_scope",
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_provider_operation_attempt"),
    )
    op.create_index(
        "ix_provider_operation_claim",
        "acquisition_provider_operation",
        ["state", "retry_after", "lease_expires_at"],
    )

    op.create_table(
        "acquisition_provider_event",
        sa.Column("provider_event_ref", sa.String(64), primary_key=True),
        sa.Column("canonical_event_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("fingerprint_version", sa.String(64), nullable=False),
        sa.Column("fingerprint_key_version", sa.String(64), nullable=False),
        sa.Column("provider_event_type", sa.String(64), nullable=False),
        sa.Column("provider_workspace_ref", sa.String(128), nullable=False),
        sa.Column("provider_campaign_id", sa.String(128), nullable=False),
        sa.Column("provider_lead_id", sa.String(128)),
        sa.Column("provider_email_event_id", sa.String(128)),
        sa.Column("campaign_ref", sa.String(64), nullable=False),
        sa.Column("member_ref", sa.String(64)),
        sa.Column("acquisition_opportunity_id", sa.String(64)),
        sa.Column("contact_ref", sa.String(64)),
        sa.Column("step", sa.Integer()),
        sa.Column("variant", sa.String(32)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mailbox_ref", sa.String(256)),
        sa.Column("transport_status", sa.String(64)),
        sa.Column("resolution_state", sa.String(32), nullable=False),
        sa.Column("incident_code", sa.String(100)),
        sa.Column("recorded_acquisition_event_id", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["campaign_ref"], ["acquisition_campaign.campaign_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["member_ref"], ["acquisition_campaign_member.member_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("step IS NULL OR step IN (1, 2)", name="ck_provider_event_step"),
        sa.CheckConstraint(
            "resolution_state IN ('ACCEPTED', 'PROCESSED', 'QUARANTINED', 'FAILED')",
            name="ck_provider_event_resolution",
        ),
    )
    op.create_index(
        "ix_provider_event_member_time",
        "acquisition_provider_event",
        ["member_ref", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("acquisition_provider_event")
    op.drop_table("acquisition_provider_operation")
    op.drop_table("acquisition_campaign_member")
    op.drop_table("acquisition_campaign")
