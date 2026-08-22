from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import acquisition_response_evaluation

CAMPAIGN_FACTORY = "0016_campaign_factory"
PREVIOUS = "0017_target_icp_revision"
HEAD = "0018_response_intelligence"


def test_response_migration_is_linear_and_adds_exactly_one_table(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'responses.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {
        "acquisition_response_evaluation"
    }
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert scripts.get_revision(PREVIOUS).down_revision == CAMPAIGN_FACTORY
    versions = pathlib.Path(scripts.versions)
    assert (versions / "0017_target_icp_revision.py").is_file()
    assert (versions / "0018_response_intelligence.py").is_file()
    assert not (versions / "0017_response_intelligence.py").exists()
    assert not any(path.name.startswith("0018_merge") for path in versions.glob("*.py"))
    assert not any(path.name.startswith("0019") for path in versions.glob("*.py"))


def test_fresh_upgrade_downgrade_and_reupgrade_preserve_prior_heads(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'roundtrip.db'}")
    config = alembic_config(engine)

    command.upgrade(config, HEAD)

    assert current_revision(engine) == HEAD
    assert sa.inspect(engine).has_table(acquisition_response_evaluation.name)
    assert sa.inspect(engine).has_table("acquisition_provider_event")
    assert "matching_revision" in {
        column["name"] for column in sa.inspect(engine).get_columns("target_icp")
    }

    command.downgrade(config, PREVIOUS)

    assert current_revision(engine) == PREVIOUS
    assert not sa.inspect(engine).has_table(acquisition_response_evaluation.name)
    assert sa.inspect(engine).has_table("acquisition_provider_event")
    assert "matching_revision" in {
        column["name"] for column in sa.inspect(engine).get_columns("target_icp")
    }

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD


def test_response_schema_matches_core_and_excludes_raw_content() -> None:
    columns = {column.name for column in acquisition_response_evaluation.columns}
    assert {
        "response_evaluation_id",
        "response_ref",
        "provider_event_ref",
        "campaign_ref",
        "member_ref",
        "acquisition_opportunity_id",
        "contact_ref",
        "content_fingerprint",
        "content_fingerprint_version",
        "content_fingerprint_key_version",
        "classifier_version",
        "classification",
        "human_response_confirmed",
        "hot_lead",
        "review_required",
        "processing_state",
        "supersedes_response_evaluation_id",
    } <= columns
    forbidden = {
        "email",
        "lead_email",
        "sending_account",
        "subject",
        "reply_text",
        "reply_html",
        "body",
        "html",
        "content_preview",
        "message_id",
        "unibox_url",
        "attachment",
        "raw_prompt",
        "raw_model_response",
        "raw_provider_json",
    }
    assert forbidden.isdisjoint(columns)


def test_response_database_schema_has_constraints_and_core_parity(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'parity.db'}")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)

    assert {item["name"] for item in inspector.get_unique_constraints(
        acquisition_response_evaluation.name
    )} >= {
        "uq_response_event_classifier",
        "uq_response_ref_classifier",
    }
    assert {column["name"] for column in inspector.get_columns(
        acquisition_response_evaluation.name
    )} == {column.name for column in acquisition_response_evaluation.columns}
    checks = {item["name"] for item in inspector.get_check_constraints(
        acquisition_response_evaluation.name
    )}
    assert {
        "ck_response_processing_state",
        "ck_response_classification",
        "ck_response_hot_invariant",
        "ck_response_machine_invariant",
        "ck_response_next_action",
        "ck_response_content_fingerprint",
        "ck_response_finalization",
    } <= checks


def test_response_postgresql_offline_sql_creates_one_table(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out

    assert sql.count("CREATE TABLE acquisition_response_evaluation (") == 1
    assert sql.count("CREATE TABLE acquisition_") == 1
    for forbidden in ("reply_text", "reply_html", "raw_model_response", "raw_provider_json"):
        assert forbidden not in sql
