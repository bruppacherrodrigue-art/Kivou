"""Versioned BOAMP source archive and award facts, separate from inferences."""

import sqlalchemy as sa

from signals.persistence.schema import METADATA

notice_source_snapshot = sa.Table(
    "notice_source_snapshot",
    METADATA,
    sa.Column("snapshot_key", sa.String(64), primary_key=True),
    sa.Column("source_system", sa.String(32), nullable=False),
    sa.Column("source_notice_id", sa.String(256), nullable=False),
    # Normalize absent versions to an empty string so UNIQUE works on every dialect.
    sa.Column("notice_version", sa.String(32), nullable=False),
    sa.Column("source_url", sa.Text),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("byte_size", sa.Integer, nullable=False),
    sa.Column("payload_compressed", sa.LargeBinary),
    sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("payload_purged_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "source_system",
        "source_notice_id",
        "notice_version",
        "content_hash",
        name="uq_notice_source_snapshot_version",
    ),
    sa.CheckConstraint("source_system = 'boamp'", name="ck_notice_snapshot_source"),
    sa.CheckConstraint("byte_size > 0 AND byte_size <= 10485760", name="ck_notice_snapshot_size"),
    sa.CheckConstraint("expires_at > collected_at", name="ck_notice_snapshot_expiry"),
    sa.CheckConstraint(
        "(payload_compressed IS NOT NULL AND payload_purged_at IS NULL) OR "
        "(payload_compressed IS NULL AND payload_purged_at IS NOT NULL)",
        name="ck_notice_snapshot_payload_lifecycle",
    ),
)

notice_award_facts = sa.Table(
    "notice_award_facts",
    METADATA,
    sa.Column("facts_key", sa.String(64), primary_key=True),
    sa.Column(
        "snapshot_key",
        sa.String(64),
        sa.ForeignKey("notice_source_snapshot.snapshot_key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "event_key",
        sa.String(256),
        sa.ForeignKey("source_event.event_key", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "award_key",
        sa.String(64),
        sa.ForeignKey("contract_award.award_key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("extractor_version", sa.String(64), nullable=False),
    sa.Column("source_set_hash", sa.String(64), nullable=False),
    sa.Column("needs_related_enrichment", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("facts", sa.JSON, nullable=False),
    sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "snapshot_key",
        "award_key",
        "extractor_version",
        "source_set_hash",
        name="uq_notice_award_facts_version",
    ),
    sa.Index(
        "ix_notice_award_facts_related_coverage",
        "extractor_version",
        "needs_related_enrichment",
        "award_key",
    ),
)
