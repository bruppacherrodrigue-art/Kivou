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
DECISION_REVISION = "0012_decision_engine"
PERSONALIZATION_REVISION = "0013_personalization"
COMPLIANCE_REVISION = "0014_compliance"
BILLING_REVISION = "0015_scheduled_cancellation"
CAMPAIGN_REVISION = "0016_campaign_factory"
TARGET_ICP_REVISION = "0017_target_icp_revision"
RESPONSE_REVISION = "0018_response_intelligence"
CONVERSION_REVISION = "0019_conversion_tracking"
LEARNING_REVISION = "0020_hermes_learning_loop"
RELIABILITY_REVISION = "0021_reliability_operations"
SAAS_COMPANY_REVISION = "0022_saas_company_profile"
#: Le maillon inséré entre la migration SaaS et la tête courante.
EMAIL_REVISION = "0023_transactional_email_runtime"
SCHEDULED_PLAN_REVISION = "0024_scheduled_plan_change"
ALERT_RECIPIENT_CONTEXT_REVISION = "0025_alert_recipient_context"
ACQUISITION_RUNTIME_REVISION = "0026_acquisition_runtime"
SIGNAL_NOTES_REVISION = "0027_signal_notes"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de SIGNAL_NOTES_REVISION, et écraser ce lien ferait passer un test faux.
CARD_PRESENTATION_REVISION = "0028_card_presentation"
PRODUCTION_OBSERVATION_REVISION = "0029_production_observation"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de PRODUCTION_OBSERVATION_REVISION, et écraser ce lien ferait passer un test faux.
WINNER_ENRICHMENT_REVISION = "0030_winner_enrichment"
FRENCH_OFFICIAL_COMPANY_REVISION = "0031_french_official_company"
REQUEUE_SIRET_PLACEHOLDERS_REVISION = "0032_requeue_siret_placeholders"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de REQUEUE_SIRET_PLACEHOLDERS_REVISION, et écraser ce lien ferait passer un test faux.
REQUEUE_UNRESOLVED_SIRET_REVISION = "0033_requeue_unresolved_siret"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de REQUEUE_UNRESOLVED_SIRET_REVISION, et écraser ce lien ferait passer un test faux.
COMPANY_ENGAGEMENT_REVISION = "0034_company_engagement"
CURRENT_HEAD = "0035_landing_signal"
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
    assert script.get_revision(DECISION_REVISION).down_revision == COMPANY_REVISION
    assert script.get_revision(PERSONALIZATION_REVISION).down_revision == DECISION_REVISION
    assert script.get_revision(COMPLIANCE_REVISION).down_revision == PERSONALIZATION_REVISION
    assert script.get_revision(BILLING_REVISION).down_revision == COMPLIANCE_REVISION
    assert script.get_revision(CAMPAIGN_REVISION).down_revision == BILLING_REVISION
    assert script.get_revision(TARGET_ICP_REVISION).down_revision == CAMPAIGN_REVISION
    assert script.get_revision(RESPONSE_REVISION).down_revision == TARGET_ICP_REVISION
    assert script.get_revision(CONVERSION_REVISION).down_revision == RESPONSE_REVISION
    assert script.get_revision(LEARNING_REVISION).down_revision == CONVERSION_REVISION
    assert (
        script.get_revision(COMPANY_ENGAGEMENT_REVISION).down_revision
        == REQUEUE_UNRESOLVED_SIRET_REVISION
    )
    assert (
        script.get_revision(CURRENT_HEAD).down_revision
        == COMPANY_ENGAGEMENT_REVISION
    )
    assert (
        script.get_revision(REQUEUE_UNRESOLVED_SIRET_REVISION).down_revision
        == REQUEUE_SIRET_PLACEHOLDERS_REVISION
    )
    assert (
        script.get_revision(REQUEUE_SIRET_PLACEHOLDERS_REVISION).down_revision
        == FRENCH_OFFICIAL_COMPANY_REVISION
    )
    assert (
        script.get_revision(FRENCH_OFFICIAL_COMPANY_REVISION).down_revision
        == WINNER_ENRICHMENT_REVISION
    )
    assert (
        script.get_revision(WINNER_ENRICHMENT_REVISION).down_revision
        == PRODUCTION_OBSERVATION_REVISION
    )
    assert (
        script.get_revision(PRODUCTION_OBSERVATION_REVISION).down_revision
        == CARD_PRESENTATION_REVISION
    )
    assert (
        script.get_revision(CARD_PRESENTATION_REVISION).down_revision
        == SIGNAL_NOTES_REVISION
    )
    assert (
        script.get_revision(SIGNAL_NOTES_REVISION).down_revision
        == ACQUISITION_RUNTIME_REVISION
    )
    assert (
        script.get_revision(ACQUISITION_RUNTIME_REVISION).down_revision
        == ALERT_RECIPIENT_CONTEXT_REVISION
    )
    assert (
        script.get_revision(ALERT_RECIPIENT_CONTEXT_REVISION).down_revision
        == SCHEDULED_PLAN_REVISION
    )
    assert (
        script.get_revision(SCHEDULED_PLAN_REVISION).down_revision
        == EMAIL_REVISION
    )
    assert script.get_revision(EMAIL_REVISION).down_revision == SAAS_COMPANY_REVISION
    assert script.get_revision(SAAS_COMPANY_REVISION).down_revision == RELIABILITY_REVISION
    assert script.get_revision(RELIABILITY_REVISION).down_revision == LEARNING_REVISION
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
