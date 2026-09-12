"""Join the company-enrichment and company-contact migration branches.

Revision ID: 0056_company_contact_merge
Revises: 0055_company_enrichment, 0054_company_contact_lookup
"""

from __future__ import annotations

from alembic import op

revision = "0056_company_contact_merge"
down_revision = ("0055_company_enrichment", "0054_company_contact_lookup")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The company-enrichment SQLite batch migration rebuilds supplier_directory and
    # drops triggers attached to the old table. PostgreSQL ALTER TABLE keeps
    # the trigger created by the contact branch, so only SQLite needs repair.
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_company_contact_lookup_directory_change")
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


def downgrade() -> None:
    pass
