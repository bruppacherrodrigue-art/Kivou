"""Program schema is additive and reversible on a disposable database."""

import sqlalchemy as sa
from alembic import command
from migration_head_helpers import current_migration_head

from signals.persistence.database import alembic_config, migrate_to_latest
from signals.persistence.schema import METADATA


def test_program_migration_upgrade_downgrade() -> None:
    assert current_migration_head() == "0075_milomail_b0_contact_yield"
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    inspector = sa.inspect(engine)
    expected = {
        "acquisition_program",
        "acquisition_program_eligibility",
        "acquisition_program_attribution",
        "acquisition_program_conversion_receipt",
    }
    assert expected <= set(inspector.get_table_names())
    for name in expected:
        assert name in METADATA.tables
    command.downgrade(alembic_config(engine), "0067_acceptance_error_cleanup")
    assert expected.isdisjoint(sa.inspect(engine).get_table_names())
