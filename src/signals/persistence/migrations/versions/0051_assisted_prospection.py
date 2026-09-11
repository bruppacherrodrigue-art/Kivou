"""Add Founder-reviewed prospect queue and delivery audit.

Revision ID: 0051_assisted_prospection
Revises: 0050_supplier_domain_validation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_assisted_prospection"
down_revision = "0050_supplier_domain_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.add_column(sa.Column("family_review_keys", sa.JSON, nullable=False, server_default="[]"))
        batch.add_column(sa.Column("email_evidence_url", sa.Text))
        batch.add_column(sa.Column("website_failure_count", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("website_next_retry_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("website_unreachable_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("website_search_queries_completed", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("website_search_results_examined", sa.Integer, nullable=False, server_default="0"))
        batch.create_check_constraint(
            "ck_supplier_directory_website_failures",
            "website_failure_count BETWEEN 0 AND 3",
        )

    op.create_table(
        "prospect_target",
        sa.Column("target_id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("cycle_ref", sa.String(64)),
        sa.Column("opportunity_key", sa.String(256), nullable=False),
        sa.Column("procedure_award_key", sa.String(256), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(64)),
        sa.Column("siren", sa.String(9), sa.ForeignKey("supplier_directory.siren", ondelete="RESTRICT"), nullable=False),
        sa.Column("company_name", sa.Text, nullable=False),
        sa.Column("company_city", sa.Text, nullable=False),
        sa.Column("company_employees", sa.Integer, nullable=False),
        sa.Column("vertical", sa.String(100), nullable=False),
        sa.Column("family_key", sa.String(100), nullable=False),
        sa.Column("family_label", sa.Text, nullable=False),
        sa.Column("director_name", sa.Text),
        sa.Column("director_title", sa.Text),
        sa.Column("director_source", sa.String(16)),
        sa.Column("email_address", sa.String(320), nullable=False),
        sa.Column("email_source", sa.String(16), nullable=False),
        sa.Column("email_verification_status", sa.String(32), nullable=False),
        sa.Column("email_evidence_url", sa.Text),
        sa.Column("signal_holder", sa.Text, nullable=False),
        sa.Column("signal_subject", sa.Text, nullable=False),
        sa.Column("signal_amount_minor_units", sa.BigInteger, nullable=False),
        sa.Column("signal_currency", sa.String(3), nullable=False),
        sa.Column("signal_location", sa.Text, nullable=False),
        sa.Column("signal_decision_date", sa.Date, nullable=False),
        sa.Column("signal_source_url", sa.Text, nullable=False),
        sa.Column("mail_subject", sa.Text, nullable=False),
        sa.Column("mail_text", sa.Text, nullable=False),
        sa.Column("mail_html", sa.Text, nullable=False),
        sa.Column("attribution_url", sa.Text, nullable=False),
        sa.Column("attribution_member_ref", sa.String(64), nullable=False, unique=True),
        sa.Column("attribution_payload", sa.JSON, nullable=False),
        sa.Column("attribution_token_fingerprint", sa.String(64), nullable=False),
        sa.Column("unsubscribe_url", sa.Text, nullable=False),
        sa.Column("mail_word_count", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rejection_reason", sa.String(32)),
        sa.Column("rejection_comment", sa.Text),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(320)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_by", sa.String(320)),
        sa.Column("delivery_status", sa.String(16), nullable=False, server_default="not_sent"),
        sa.Column("provider_campaign_id", sa.String(128)),
        sa.Column("instantly_id", sa.String(128)),
        sa.Column("send_request_id", sa.String(36)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("clicked_at", sa.DateTime(timezone=True)),
        sa.Column("replied_at", sa.DateTime(timezone=True)),
        sa.Column("bounced_at", sa.DateTime(timezone=True)),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True)),
        sa.Column("instantly_credit_units", sa.Integer, nullable=False, server_default="0"),
        sa.Column("instantly_request_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delivery_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_prospect_target_version"),
        sa.CheckConstraint("company_employees >= 10", name="ck_prospect_target_employees"),
        sa.CheckConstraint("status IN ('pending_review', 'approved', 'rejected', 'sent')", name="ck_prospect_target_status"),
        sa.CheckConstraint("rejection_reason IS NULL OR rejection_reason IN ('wrong_company', 'wrong_address', 'off_topic', 'other')", name="ck_prospect_target_rejection_reason"),
        sa.CheckConstraint("email_source IN ('apollo', 'site', 'manual')", name="ck_prospect_target_email_source"),
        sa.CheckConstraint("email_verification_status IN ('mx_verified', 'mx_failed')", name="ck_prospect_target_email_verification"),
        sa.CheckConstraint("mail_word_count BETWEEN 1 AND 120", name="ck_prospect_target_words"),
        sa.CheckConstraint("instantly_credit_units >= 0 AND instantly_request_count >= 0", name="ck_prospect_target_delivery_cost"),
        sa.UniqueConstraint("opportunity_key", "email_address", name="uq_prospect_target_signal_email"),
    )
    op.create_index("ix_prospect_target_cycle_ref", "prospect_target", ["cycle_ref"])
    op.create_index("ix_prospect_target_opportunity_key", "prospect_target", ["opportunity_key"])
    op.create_index("ix_prospect_target_siren", "prospect_target", ["siren"])
    op.create_index("ix_prospect_target_status", "prospect_target", ["status"])
    op.create_index("ix_prospect_target_created_at", "prospect_target", ["created_at"])
    op.create_index("ix_prospect_target_daily_status", "prospect_target", ["created_at", "status"])

    op.create_table(
        "prospect_target_history",
        sa.Column("history_id", sa.String(64), primary_key=True),
        sa.Column("target_id", sa.String(36), sa.ForeignKey("prospect_target.target_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("previous_values", sa.JSON, nullable=False),
        sa.Column("new_values", sa.JSON, nullable=False),
        sa.Column("reason", sa.String(32)),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prospect_target_history_target_id", "prospect_target_history", ["target_id"])

    op.create_table(
        "prospect_send_request",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("target_ids", sa.JSON, nullable=False),
        sa.Column("request_day", sa.Date, nullable=False),
        sa.Column("reserved_count", sa.Integer, nullable=False),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('started', 'completed', 'partial', 'failed')", name="ck_prospect_send_request_status"),
        sa.CheckConstraint("reserved_count BETWEEN 1 AND 25 AND sent_count BETWEEN 0 AND reserved_count", name="ck_prospect_send_request_counts"),
    )
    op.create_index("ix_prospect_send_request_request_day", "prospect_send_request", ["request_day"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            DO $grants$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kivou_founder_rw') THEN
                GRANT USAGE ON SCHEMA public TO kivou_founder_rw;
                GRANT SELECT, INSERT, UPDATE ON prospect_target,
                  prospect_target_history, prospect_send_request TO kivou_founder_rw;
                GRANT SELECT ON supplier_directory,
                  acquisition_contact_suppression TO kivou_founder_rw;
                GRANT UPDATE (
                  legal_name, legal_name_observed_at, directors,
                  directors_observed_at, professional_email, email_source,
                  email_verification_status, email_observed_at,
                  reverification_required_at, reverification_reason,
                  family_review_keys, updated_at
                ) ON supplier_directory TO kivou_founder_rw;
                REVOKE CREATE ON SCHEMA public FROM kivou_founder_rw;
              END IF;
            END
            $grants$;
            """
        )


def downgrade() -> None:
    op.drop_index("ix_prospect_send_request_request_day", table_name="prospect_send_request")
    op.drop_table("prospect_send_request")
    op.drop_index("ix_prospect_target_history_target_id", table_name="prospect_target_history")
    op.drop_table("prospect_target_history")
    op.drop_index("ix_prospect_target_daily_status", table_name="prospect_target")
    op.drop_index("ix_prospect_target_created_at", table_name="prospect_target")
    op.drop_index("ix_prospect_target_status", table_name="prospect_target")
    op.drop_index("ix_prospect_target_siren", table_name="prospect_target")
    op.drop_index("ix_prospect_target_opportunity_key", table_name="prospect_target")
    op.drop_index("ix_prospect_target_cycle_ref", table_name="prospect_target")
    op.drop_table("prospect_target")
    with op.batch_alter_table("supplier_directory") as batch:
        batch.drop_constraint("ck_supplier_directory_website_failures", type_="check")
        batch.drop_column("website_search_results_examined")
        batch.drop_column("website_search_queries_completed")
        batch.drop_column("website_unreachable_at")
        batch.drop_column("website_next_retry_at")
        batch.drop_column("website_failure_count")
        batch.drop_column("email_evidence_url")
        batch.drop_column("family_review_keys")
