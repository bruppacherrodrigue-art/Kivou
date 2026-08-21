from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from test_contract_award_text_capacity import REAL_BOAMP_CONTRACT_REFERENCE

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import contract_award, source_event

PREVIOUS_REVISION = "0005_ingestion_runtime"
CAPACITY_REVISION = "0006_award_text_capacity"
ACQUISITION_REVISION = "0007_acquisition_event_store"
POLICY_REVISION = "0008_policy_gateway"
SUPPLIER_REVISION = "0009_supplier_discovery"
CONTACT_REVISION = "0010_contact_discovery"
COMPANY_REVISION = "0011_company_research"
CURRENT_HEAD = "0013_personalization"
NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


def _insert_existing_award(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(source_event).values(
                event_key="boamp:26-74073:",
                source_system="boamp",
                source_notice_id="26-74073",
                notice_version=None,
                source_country="FR",
                source_procedure_id=None,
                source_url=None,
                event_type="award_notice",
                published_at_raw="2026-08-01",
                published_on=dt.date(2026, 8, 1),
                published_precision="date",
                discovered_at=NOW,
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                award_key="existing-award",
                event_key="boamp:26-74073:",
                source_award_id="CON-0001",
                lot_identifier="LOT-0001",
                contract_reference=REAL_BOAMP_CONTRACT_REFERENCE,
                cpv_additional=[],
                winner_status="identified",
                awardee_parties=[],
                contract_signatories=[],
                created_at=NOW,
            )
        )


def test_upgrade_from_0005_preserves_existing_long_contract_reference(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'upgrade.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS_REVISION)
    _insert_existing_award(engine)

    command.upgrade(config, "head")

    with engine.connect() as connection:
        columns = {
            column["name"]: column["type"]
            for column in sa.inspect(connection).get_columns("contract_award")
        }
        stored = connection.execute(
            sa.select(contract_award.c.contract_reference).where(
                contract_award.c.award_key == "existing-award"
            )
        ).scalar_one()
    assert current_revision(engine) == CURRENT_HEAD
    assert isinstance(columns["contract_reference"], sa.Text)
    assert stored == REAL_BOAMP_CONTRACT_REFERENCE


def test_fresh_database_reaches_the_single_linear_current_head(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'fresh.db'}")
    config = alembic_config(engine)
    command.upgrade(config, "head")

    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(CAPACITY_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(ACQUISITION_REVISION).down_revision == CAPACITY_REVISION
    assert script.get_revision(POLICY_REVISION).down_revision == ACQUISITION_REVISION
    assert script.get_revision(SUPPLIER_REVISION).down_revision == POLICY_REVISION
    assert script.get_revision(CONTACT_REVISION).down_revision == SUPPLIER_REVISION
    assert script.get_revision(COMPANY_REVISION).down_revision == CONTACT_REVISION
    assert script.get_revision(CURRENT_HEAD).down_revision == COMPANY_REVISION
    assert current_revision(engine) == CURRENT_HEAD


def test_every_alembic_revision_fits_the_standard_version_table_and_resolves(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'graph.db'}")
    script = ScriptDirectory.from_config(alembic_config(engine))
    revisions = list(script.walk_revisions())

    assert revisions
    assert all(len(item.revision) <= 32 for item in revisions)
    assert len({item.revision for item in revisions}) == len(revisions)
    assert script.get_heads() == [CURRENT_HEAD]
    for item in revisions:
        parents = item.down_revision
        if parents is None:
            continue
        for parent in (parents,) if isinstance(parents, str) else parents:
            assert script.get_revision(parent) is not None


def test_capacity_revision_is_a_short_linear_child_of_ingestion(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'linear.db'}")
    script = ScriptDirectory.from_config(alembic_config(engine))

    assert len(CAPACITY_REVISION) <= 32
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(CAPACITY_REVISION).down_revision == PREVIOUS_REVISION


def test_postgresql_target_type_is_unbounded_text():
    assert contract_award.c.contract_reference.type.compile(
        dialect=postgresql.dialect()
    ) == "TEXT"


def test_postgresql_migration_widens_only_contract_reference(capsys):
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql://kivou:placeholder@localhost/kivou",
    )

    command.upgrade(config, f"{PREVIOUS_REVISION}:{CAPACITY_REVISION}", sql=True)

    sql = capsys.readouterr().out
    assert "ALTER TABLE contract_award ALTER COLUMN contract_reference TYPE TEXT;" in sql
    assert sql.count("ALTER TABLE") == 1
