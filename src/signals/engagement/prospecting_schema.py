"""Public identity aliases and account-private prospecting records."""

import sqlalchemy as sa

import signals.accounts.schema  # noqa: F401
from signals.persistence.schema import METADATA


def _account():
    return sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    )


def _dates():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


company_subject_alias = sa.Table(
    "company_subject_alias",
    METADATA,
    sa.Column("alias_company_key", sa.String(64), primary_key=True),
    sa.Column("canonical_company_key", sa.String(64), nullable=False, index=True),
    sa.Column("identifier_type", sa.String(16), nullable=False),
    sa.Column("identifier_value", sa.String(64), nullable=False),
    sa.Column("provenance", sa.String(64), nullable=False),
    sa.Column("resolution_status", sa.String(16), nullable=False),
    *_dates(),
    sa.CheckConstraint(
        "resolution_status IN ('exact', 'unresolved')", name="ck_company_alias_resolution"
    ),
)

account_company_alias_override = sa.Table(
    "account_company_alias_override",
    METADATA,
    _account(),
    sa.Column("alias_company_key", sa.String(64), primary_key=True),
    sa.Column("private_subject_key", sa.String(64), nullable=False, index=True),
    sa.Column("mode", sa.String(16), nullable=False),
    sa.Column("reason", sa.String(128), nullable=False),
    *_dates(),
    sa.CheckConstraint("mode IN ('isolated', 'resolved')", name="ck_account_company_alias_mode"),
)

account_company_membership = sa.Table(
    "account_company_membership",
    METADATA,
    _account(),
    sa.Column("company_key", sa.String(64), primary_key=True),
    sa.Column("origin", sa.String(32), nullable=False),
    sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
    *_dates(),
    sa.CheckConstraint("revision >= 1", name="ck_company_membership_revision"),
)

company_manual_contact = sa.Table(
    "company_manual_contact",
    METADATA,
    _account(),
    sa.Column("company_key", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(120)),
    sa.Column("role", sa.String(120)),
    sa.Column("email", sa.String(254)),
    sa.Column("phone", sa.String(40)),
    sa.Column("source", sa.String(16), nullable=False, server_default="user"),
    sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
    sa.Column("deleted_at", sa.DateTime(timezone=True)),
    *_dates(),
    sa.CheckConstraint("source = 'user'", name="ck_manual_contact_source"),
    sa.CheckConstraint("revision >= 1", name="ck_manual_contact_revision"),
    sa.CheckConstraint(
        "deleted_at IS NOT NULL OR (name IS NOT NULL AND (email IS NOT NULL OR phone IS NOT NULL))",
        name="ck_manual_contact_reachable",
    ),
)
