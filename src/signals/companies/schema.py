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
    sa.Column("official_observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
