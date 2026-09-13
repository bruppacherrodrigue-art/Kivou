"""V11 lossless prospecting: CAS notes, workflow and account-private company work."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0059_prospecting_state"
down_revision = "0058_client_location"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    for name in ("signal_note", "company_note"):
        # Neither note table has dependent rows, so SQLite batch replacement
        # cannot cascade-delete private children as an account table rewrite could.
        with op.batch_alter_table(name) as batch:
            if name == "signal_note":
                batch.alter_column(
                    "note",
                    existing_type=sa.String(500),
                    type_=sa.String(2000),
                    existing_nullable=False,
                )
            batch.add_column(sa.Column("revision", sa.Integer, nullable=False, server_default="1"))
            batch.create_check_constraint(f"ck_{name}_revision", "revision >= 1")
    op.create_table(
        "signal_workflow",
        _account(),
        sa.Column("signal_key", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        *_dates(),
        sa.CheckConstraint(
            "status IN ('new', 'saved', 'contacted', 'ignored')", name="ck_signal_workflow_status"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_signal_workflow_revision"),
    )
    op.create_index(
        "ix_signal_workflow_account_status", "signal_workflow", ["account_id", "status"]
    )
    op.execute(
        sa.text("""
        INSERT INTO signal_workflow(account_id, signal_key, status, revision, created_at, updated_at)
        SELECT account_id, signal_key,
          CASE WHEN contacted_at IS NOT NULL THEN 'contacted'
               WHEN relevance = 'relevant' THEN 'saved'
               WHEN relevance = 'not_relevant' THEN 'ignored' ELSE 'new' END,
          1, created_at, updated_at FROM signal_feedback
    """)
    )
    op.create_table(
        "company_subject_alias",
        sa.Column("alias_company_key", sa.String(64), primary_key=True),
        sa.Column("canonical_company_key", sa.String(64), nullable=False),
        sa.Column("identifier_type", sa.String(16), nullable=False),
        sa.Column("identifier_value", sa.String(64), nullable=False),
        sa.Column("provenance", sa.String(64), nullable=False),
        sa.Column("resolution_status", sa.String(16), nullable=False),
        *_dates(),
        sa.CheckConstraint(
            "resolution_status IN ('exact', 'unresolved')", name="ck_company_alias_resolution"
        ),
    )
    op.create_index(
        "ix_company_subject_alias_canonical_company_key",
        "company_subject_alias",
        ["canonical_company_key"],
    )
    op.create_table(
        "account_company_alias_override",
        _account(),
        sa.Column("alias_company_key", sa.String(64), primary_key=True),
        sa.Column("private_subject_key", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        *_dates(),
        sa.CheckConstraint(
            "mode IN ('isolated', 'resolved')", name="ck_account_company_alias_mode"
        ),
    )
    op.create_index(
        "ix_account_company_alias_override_private_subject_key",
        "account_company_alias_override",
        ["private_subject_key"],
    )
    op.create_table(
        "account_company_membership",
        _account(),
        sa.Column("company_key", sa.String(64), primary_key=True),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        *_dates(),
        sa.CheckConstraint("revision >= 1", name="ck_company_membership_revision"),
    )
    op.create_table(
        "company_manual_contact",
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


def downgrade() -> None:
    raise RuntimeError(
        "V11 prospecting downgrade would discard private work; use a compatible application rollback without database downgrade"
    )
