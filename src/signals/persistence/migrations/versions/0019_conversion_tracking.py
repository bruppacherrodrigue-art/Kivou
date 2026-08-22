"""Add first-party conversion journeys and append-only milestones.

Revision ID: 0019_conversion_tracking
Revises: 0018_response_intelligence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_conversion_tracking"
down_revision = "0018_response_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_conversion_journey",
        sa.Column("journey_ref", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False, unique=True),
        sa.Column("source_click_event_ref", sa.String(64), nullable=False),
        sa.Column("campaign_ref", sa.String(64), nullable=False),
        sa.Column("member_ref", sa.String(64), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("token_fingerprint", sa.String(64), nullable=False),
        sa.Column("token_version", sa.String(64), nullable=False),
        sa.Column("token_key_version", sa.String(100), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("sector_ref", sa.String(256), nullable=False),
        sa.Column("sector_version", sa.String(100), nullable=False),
        sa.Column("need_ref", sa.String(256), nullable=False),
        sa.Column("need_version", sa.String(100), nullable=False),
        sa.Column("wedge", sa.String(100), nullable=False),
        sa.Column("wedge_version", sa.String(100), nullable=False),
        sa.Column("attribution_policy_version", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attribution_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signed_up_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.account_id"], ondelete="RESTRICT"),
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
        sa.CheckConstraint("country IN ('CH', 'FR')", name="ck_conversion_journey_country"),
        sa.CheckConstraint(
            "clicked_at <= signed_up_at AND signed_up_at <= attribution_expires_at",
            name="ck_conversion_journey_window",
        ),
    )
    op.create_index(
        "ix_conversion_journey_campaign",
        "acquisition_conversion_journey",
        ["campaign_ref", "signed_up_at"],
    )
    op.create_index(
        "ix_acquisition_conversion_journey_source_click_event_ref",
        "acquisition_conversion_journey",
        ["source_click_event_ref"],
    )

    op.create_table(
        "acquisition_conversion_event",
        sa.Column("conversion_event_ref", sa.String(64), primary_key=True),
        sa.Column("journey_ref", sa.String(64)),
        sa.Column("milestone", sa.String(32), nullable=False),
        sa.Column("event_version", sa.String(64), nullable=False),
        sa.Column("event_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("token_fingerprint", sa.String(64)),
        sa.Column("trigger_ref_type", sa.String(64)),
        sa.Column("trigger_ref", sa.String(256)),
        sa.Column("account_id", sa.String(64)),
        sa.Column("campaign_ref", sa.String(64)),
        sa.Column("member_ref", sa.String(64)),
        sa.Column("acquisition_opportunity_id", sa.String(64)),
        sa.Column("activation_fingerprint", sa.String(64)),
        sa.Column("billing_subscription_ref", sa.String(64)),
        sa.Column("catalogue_version", sa.String(64)),
        sa.Column("mrr_known", sa.Boolean),
        sa.Column("mrr_minor_units", sa.BigInteger),
        sa.Column("currency", sa.String(3)),
        sa.Column("reason_code", sa.String(100)),
        sa.Column("outcome_event_ref", sa.String(64)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_ref"], ["acquisition_conversion_journey.journey_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.account_id"]),
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
        sa.ForeignKeyConstraint(
            ["outcome_event_ref"], ["acquisition_event.event_id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "milestone IN ('CLICK', 'SIGNUP', 'ACTIVATED', 'PAID', 'MRR_CHANGED', "
            "'RETAINED_M1', 'RETAINED_M2', 'CHURNED')",
            name="ck_conversion_event_milestone",
        ),
        sa.CheckConstraint(
            "(milestone = 'CLICK' AND journey_ref IS NULL AND token_fingerprint IS NOT NULL "
            "AND account_id IS NULL) OR "
            "(milestone <> 'CLICK' AND journey_ref IS NOT NULL AND account_id IS NOT NULL)",
            name="ck_conversion_event_phase",
        ),
        sa.CheckConstraint(
            "(milestone = 'MRR_CHANGED' AND mrr_known IS NOT NULL) OR "
            "(milestone <> 'MRR_CHANGED' AND mrr_known IS NULL AND mrr_minor_units IS NULL "
            "AND currency IS NULL)",
            name="ck_conversion_event_mrr_scope",
        ),
        sa.CheckConstraint(
            "mrr_known IS NULL OR "
            "(mrr_known IS TRUE AND mrr_minor_units >= 0 AND currency IN ('chf', 'eur') "
            "AND reason_code IS NULL) OR "
            "(mrr_known IS FALSE AND mrr_minor_units IS NULL AND currency IS NULL "
            "AND reason_code IS NOT NULL)",
            name="ck_conversion_event_money",
        ),
        sa.CheckConstraint(
            "occurred_at <= observed_at AND observed_at <= recorded_at",
            name="ck_conversion_event_times",
        ),
    )
    op.create_index(
        "ix_acquisition_conversion_event_token_fingerprint",
        "acquisition_conversion_event",
        ["token_fingerprint"],
    )
    op.create_index(
        "ix_conversion_event_journey_time",
        "acquisition_conversion_event",
        ["journey_ref", "occurred_at"],
    )
    op.create_index(
        "ix_conversion_event_milestone_time",
        "acquisition_conversion_event",
        ["milestone", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("acquisition_conversion_event")
    op.drop_table("acquisition_conversion_journey")
