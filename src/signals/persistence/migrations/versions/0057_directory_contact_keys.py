"""Allow account-scoped contact lookups for directory-only companies.

Revision ID: 0057_directory_contact_keys
Revises: 0056_company_contact_merge
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0057_directory_contact_keys"
down_revision = "0056_company_contact_merge"
branch_labels = None
depends_on = None

_TABLES = ("company_contact_lookup_attempt", "company_contact_lookup")
_SQLITE_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}


def _create_sqlite_directory_trigger() -> None:
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


def _constraint_name(table_name: str) -> str:
    if op.get_bind().dialect.name == "sqlite":
        return f"fk_{table_name}_company_key_saas_company"
    return f"{table_name}_company_key_fkey"


def upgrade() -> None:
    # A directory profile has a stable ``cmp_directory_<siren>`` key but does
    # not necessarily originate from a materialized signal. Account ownership
    # and directory identity remain protected by their own foreign keys.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in _TABLES:
            op.execute(
                f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS "
                f"{table_name}_company_key_fkey"
            )
        return

    inspector = sa.inspect(bind)
    tables_with_legacy_fk = [
        table_name
        for table_name in _TABLES
        if any(
            foreign_key["referred_table"] == "saas_company"
            and foreign_key["constrained_columns"] == ["company_key"]
            for foreign_key in inspector.get_foreign_keys(table_name)
        )
    ]
    if tables_with_legacy_fk:
        # SQLite rebuilds each table to remove a foreign key. Its trigger is
        # parsed during every rename, so detach it for the bounded rebuild.
        op.execute("DROP TRIGGER IF EXISTS trg_company_contact_lookup_directory_change")
    for table_name in tables_with_legacy_fk:
        with op.batch_alter_table(
            table_name,
            naming_convention=_SQLITE_NAMING_CONVENTION,
        ) as batch:
            batch.drop_constraint(_constraint_name(table_name), type_="foreignkey")
    if tables_with_legacy_fk:
        _create_sqlite_directory_trigger()


def downgrade() -> None:
    # Keep the relaxed key contract when stepping back one application
    # revision. Recreating the former FK would either fail on legitimate
    # ``cmp_directory_*`` audit rows or require deleting that append-only
    # history. The older application remains compatible with the relaxed
    # schema; downgrading farther through 0054 still removes both feature
    # tables as originally defined.
    pass
