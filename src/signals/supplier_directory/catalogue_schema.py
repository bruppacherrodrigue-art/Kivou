"""Ownership and checkpoints for the isolated public catalogue mirror."""

import sqlalchemy as sa

from signals.persistence.schema import METADATA

catalogue_mirror_entry = sa.Table(
    "catalogue_mirror_entry",
    METADATA,
    sa.Column("siren", sa.String(9), primary_key=True),
    sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source_fact_hashes", sa.JSON(), nullable=False),
    sa.Column("mirrored_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
)

catalogue_mirror_state = sa.Table(
    "catalogue_mirror_state",
    METADATA,
    sa.Column("source", sa.String(16), primary_key=True),
    sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("mirrored_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source = 'production'", name="ck_catalogue_mirror_source"),
)
