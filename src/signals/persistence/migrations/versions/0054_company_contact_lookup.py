"""Add the account-scoped company contact lookup and attempt ledger.

Revision ID: 0054_company_contact_lookup
Revises: 0053_supplier_activity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0054_company_contact_lookup"
down_revision = "0053_supplier_activity"
branch_labels = None
depends_on = None


def _create_directory_change_trigger() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_company_contact_lookup_directory_change
            AFTER UPDATE OF suppressed_at, apollo_organization_id, apollo_status
            ON supplier_directory
            WHEN NEW.suppressed_at IS NOT NULL
              OR NEW.apollo_organization_id IS NOT OLD.apollo_organization_id
              OR NEW.apollo_status IS NOT OLD.apollo_status
            BEGIN
                UPDATE company_contact_lookup_attempt
                   SET status = CASE
                                    WHEN NEW.suppressed_at IS NOT NULL
                                    THEN 'suppressed'
                                    ELSE 'expired'
                                END,
                       completed_at = COALESCE(NEW.suppressed_at, CURRENT_TIMESTAMP),
                       error_code = CASE
                                        WHEN NEW.suppressed_at IS NOT NULL
                                        THEN 'directory_suppressed'
                                        ELSE 'directory_identity_changed'
                                    END
                 WHERE directory_siren = NEW.siren
                   AND status = 'running';
                DELETE FROM company_contact_lookup
                 WHERE directory_siren = NEW.siren;
            END
            """
        )
        return
    op.execute(
        """
        CREATE FUNCTION purge_company_contact_lookup_on_directory_change()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.suppressed_at IS NOT NULL
               OR NEW.apollo_organization_id IS DISTINCT FROM OLD.apollo_organization_id
               OR NEW.apollo_status IS DISTINCT FROM OLD.apollo_status THEN
                UPDATE company_contact_lookup_attempt
                   SET status = CASE
                                    WHEN NEW.suppressed_at IS NOT NULL
                                    THEN 'suppressed'
                                    ELSE 'expired'
                                END,
                       completed_at = COALESCE(NEW.suppressed_at, CURRENT_TIMESTAMP),
                       error_code = CASE
                                        WHEN NEW.suppressed_at IS NOT NULL
                                        THEN 'directory_suppressed'
                                        ELSE 'directory_identity_changed'
                                    END
                 WHERE directory_siren = NEW.siren
                   AND status = 'running';
                DELETE FROM company_contact_lookup
                 WHERE directory_siren = NEW.siren;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_contact_lookup_directory_change
        AFTER UPDATE OF suppressed_at, apollo_organization_id, apollo_status
        ON supplier_directory
        FOR EACH ROW EXECUTE FUNCTION purge_company_contact_lookup_on_directory_change()
        """
    )


def upgrade() -> None:
    op.create_table(
        "company_contact_lookup_attempt",
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
        sa.Column(
            "organization_enrichment_requests",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column("people_search_requests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("people_match_requests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("planned_credit_units", sa.Integer, nullable=False),
        sa.Column("attempted_credit_units", sa.Integer, nullable=False, server_default="0"),
        sa.Column("observed_credit_units", sa.Integer),
        sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'no_contact', 'failed', "
            "'expired', 'suppressed')",
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
    )
    op.create_index(
        "ix_company_contact_attempt_account_requested",
        "company_contact_lookup_attempt",
        ["account_id", "requested_at"],
    )

    op.create_table(
        "company_contact_lookup",
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
        sa.Column("contacts", sa.JSON, nullable=False, server_default="[]"),
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
    )
    op.create_index(
        "ix_company_contact_lookup_account_requested",
        "company_contact_lookup",
        ["account_id", "requested_at"],
    )
    _create_directory_change_trigger()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_company_contact_lookup_directory_change "
            "ON supplier_directory"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS purge_company_contact_lookup_on_directory_change()"
        )
    else:
        op.execute("DROP TRIGGER IF EXISTS trg_company_contact_lookup_directory_change")
    op.drop_index(
        "ix_company_contact_lookup_account_requested",
        table_name="company_contact_lookup",
    )
    op.drop_table("company_contact_lookup")
    op.drop_index(
        "ix_company_contact_attempt_account_requested",
        table_name="company_contact_lookup_attempt",
    )
    op.drop_table("company_contact_lookup_attempt")
