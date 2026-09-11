"""Additive SaaS storage for opaque, official-source company identities."""

from __future__ import annotations

import sqlalchemy as sa

from signals.persistence.schema import METADATA

saas_company = sa.Table(
    "saas_company",
    METADATA,
    sa.Column("company_key", sa.String(64), primary_key=True),
    sa.Column("identity_fingerprint", sa.String(64), nullable=False, unique=True),
    sa.Column("identity_method", sa.String(32), nullable=False),
    sa.Column("identity_validation", sa.JSON, nullable=False),
    sa.Column(
        "source_award_key",
        sa.String(64),
        sa.ForeignKey("contract_award.award_key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "origin_signal_key",
        sa.String(64),
        sa.ForeignKey("materialized_signal.signal_key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    sa.Column("official_name", sa.Text, nullable=False),
    sa.Column("official_country", sa.String(2)),
    sa.Column("official_address", sa.Text),
    sa.Column("official_identifiers", sa.JSON, nullable=False),
    sa.Column("official_website_url", sa.Text),
    sa.Column(
        "official_source",
        sa.String(32),
        nullable=False,
        server_default="public_notice",
    ),
    sa.Column("official_observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


# PR6b — account-scoped decision-maker cache plus an append-only provider
# attempt ledger. Person data remains only in the cache; the ledger has costs.
company_contact_lookup = sa.Table(
    "company_contact_lookup",
    METADATA,
    sa.Column("lookup_id", sa.String(64), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "company_key",
        sa.String(64),
        sa.ForeignKey("saas_company.company_key", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "directory_siren",
        sa.String(9),
        sa.ForeignKey("supplier_directory.siren", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("provider_organization_id", sa.String(128), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("organization", sa.JSON),
    sa.Column("contacts", sa.JSON, nullable=False),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("researched_at", sa.DateTime(timezone=True)),
    sa.Column("refresh_after", sa.DateTime(timezone=True)),
    sa.Column("lease_id", sa.String(64)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column("error_code", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "account_id", "company_key", name="uq_company_contact_lookup_account_company"
    ),
    sa.CheckConstraint(
        "status IN ('running', 'ready', 'no_contact', 'failed')",
        name="ck_company_contact_lookup_status",
    ),
    sa.Index(
        "ix_company_contact_lookup_account_requested",
        "account_id",
        "requested_at",
    ),
)


company_contact_lookup_attempt = sa.Table(
    "company_contact_lookup_attempt",
    METADATA,
    sa.Column("attempt_id", sa.String(64), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "company_key",
        sa.String(64),
        sa.ForeignKey("saas_company.company_key", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "directory_siren",
        sa.String(9),
        sa.ForeignKey("supplier_directory.siren", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("provider_organization_id", sa.String(128), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("organization_enrichment_requests", sa.Integer, nullable=False),
    sa.Column("people_search_requests", sa.Integer, nullable=False),
    sa.Column("people_match_requests", sa.Integer, nullable=False),
    sa.Column("planned_credit_units", sa.Integer, nullable=False),
    sa.Column("attempted_credit_units", sa.Integer, nullable=False),
    # Apollo's merged contracts do not report billed credits. Keep this null
    # rather than presenting locally estimated units as observed provider cost.
    sa.Column("observed_credit_units", sa.Integer),
    sa.Column("error_code", sa.String(64)),
    sa.CheckConstraint(
        "status IN ('running', 'success', 'no_contact', 'failed', 'expired', 'suppressed')",
        name="ck_company_contact_attempt_status",
    ),
    sa.CheckConstraint(
        "organization_enrichment_requests >= 0 "
        "AND organization_enrichment_requests <= 1 "
        "AND people_search_requests >= 0 "
        "AND people_search_requests <= 1 "
        "AND people_match_requests >= 0 "
        "AND people_match_requests <= 3 "
        "AND planned_credit_units >= 0 "
        "AND attempted_credit_units >= 0 "
        "AND attempted_credit_units <= planned_credit_units "
        "AND (observed_credit_units IS NULL OR observed_credit_units >= 0)",
        name="ck_company_contact_attempt_costs",
    ),
    sa.Index(
        "ix_company_contact_attempt_account_requested",
        "account_id",
        "requested_at",
    ),
)


winner_enrichment_job = sa.Table(
    "winner_enrichment_job",
    METADATA,
    sa.Column(
        "signal_key",
        sa.String(64),
        sa.ForeignKey("materialized_signal.signal_key", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("identity_fingerprint", sa.String(64)),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("error_code", sa.String(64)),
    sa.Column("claimed_by", sa.String(64)),
    sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('pending', 'in_progress', 'completed', 'partial', 'failed')",
        name="ck_winner_enrichment_status",
    ),
    sa.CheckConstraint(
        "attempt_count >= 0 AND attempt_count <= 3",
        name="ck_winner_enrichment_attempt_count",
    ),
    sa.CheckConstraint(
        "(status = 'pending' AND attempt_count = 0 AND started_at IS NULL "
        "AND finished_at IS NULL) OR "
        "(status = 'in_progress' AND attempt_count >= 1 AND started_at IS NOT NULL "
        "AND finished_at IS NULL) OR "
        "(status IN ('completed', 'partial', 'failed') AND attempt_count >= 1 "
        "AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
        name="ck_winner_enrichment_lifecycle",
    ),
    sa.CheckConstraint(
        "(status = 'pending' AND claimed_by IS NULL) OR "
        "(status <> 'pending' AND claimed_by IS NOT NULL)",
        name="ck_winner_enrichment_claim",
    ),
    sa.CheckConstraint(
        "(status = 'failed' AND error_code IS NOT NULL) OR "
        "(status <> 'failed' AND error_code IS NULL)",
        name="ck_winner_enrichment_error",
    ),
    sa.Index("ix_winner_enrichment_status_queued", "status", "queued_at", "signal_key"),
    sa.Index("ix_winner_enrichment_identity", "identity_fingerprint"),
)
