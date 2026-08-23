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
