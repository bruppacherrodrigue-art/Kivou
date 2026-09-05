from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)
from signals.persistence.schema import (
    METADATA,
    acquisition_campaign_member,
    acquisition_runtime_approval,
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_observation,
    acquisition_runtime_stage,
    acquisition_runtime_stage_attempt,
)

PREVIOUS = "0025_alert_recipient_context"
HEAD = "0026_acquisition_runtime"
CURRENT_HEAD = "0042_account_deletion"
RUNTIME_TABLES = {
    acquisition_runtime_approval.name,
    acquisition_runtime_lease.name,
    acquisition_runtime_observation.name,
    acquisition_runtime_cycle.name,
    acquisition_runtime_stage.name,
    acquisition_runtime_stage_attempt.name,
}


NOW = dt.datetime(2026, 9, 1, 9, tzinfo=dt.UTC)


def _engine(tmp_path: pathlib.Path, name: str) -> sa.Engine:
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def _observation_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "runtime_name": "acquisition-run-once",
        "capability_fingerprint": "f" * 64,
        "environment": "STAGING",
        "mode": "SHADOW",
        "qa_only": True,
        "hermes_repository": "kivou/hermes",
        "hermes_tag": "v1.0.0",
        "hermes_commit": "a" * 40,
        "hermes_version": "1.0.0",
        "hermes_python_contract": ">=3.11,<3.13",
        "registry_identity": "b" * 64,
        "native_tools": 0,
        "commands": ["signal_seed"],
        "dependencies": [],
        "observed_at": NOW,
        "heartbeat_at": NOW,
        "last_cycle_ref": None,
        "last_cycle_status": None,
        "last_cycle_at": None,
        "updated_at": NOW,
    }
    values.update(overrides)
    return values


def _insert_observation(engine: sa.Engine, values: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_runtime_observation).values(**values)
        )


def test_acquisition_runtime_migration_is_one_additive_revision(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-revision.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    scripts = ScriptDirectory.from_config(config)
    assert set(sa.inspect(engine).get_table_names()) - before == RUNTIME_TABLES
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert (pathlib.Path(scripts.versions) / "0026_acquisition_runtime.py").is_file()


def test_acquisition_runtime_migration_matches_declared_schema(tmp_path) -> None:
    migrated = _engine(tmp_path, "runtime-migrated.db")
    declared = _engine(tmp_path, "runtime-declared.db")
    command.upgrade(alembic_config(migrated), HEAD)
    METADATA.create_all(declared)

    for table_name in (*sorted(RUNTIME_TABLES), acquisition_campaign_member.name):
        migrated_columns = {
            column["name"]
            for column in sa.inspect(migrated).get_columns(table_name)
        }
        declared_columns = {
            column["name"]
            for column in sa.inspect(declared).get_columns(table_name)
        }
        assert migrated_columns == declared_columns

    checks = {
        check["name"]
        for check in sa.inspect(migrated).get_check_constraints(
            acquisition_campaign_member.name
        )
    }
    assert "ck_campaign_member_transport_identity" in checks


def test_acquisition_runtime_migration_roundtrip(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)

    command.downgrade(config, PREVIOUS)

    assert current_revision(engine) == PREVIOUS
    assert not RUNTIME_TABLES & set(sa.inspect(engine).get_table_names())
    member_columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns(acquisition_campaign_member.name)
    }
    assert "transport_recipient_identity" not in member_columns
    assert "transport_recipient_key_version" not in member_columns

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
    assert RUNTIME_TABLES <= set(sa.inspect(engine).get_table_names())


def test_acquisition_runtime_postgresql_sql_is_bounded_and_secret_free(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql://kivou:placeholder@localhost/kivou",
    )

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    upgrade_sql = capsys.readouterr().out.lower()
    command.downgrade(config, f"{HEAD}:{PREVIOUS}", sql=True)
    downgrade_sql = capsys.readouterr().out.lower()

    for table_name in RUNTIME_TABLES:
        assert upgrade_sql.count(f"create table {table_name} (") == 1
        assert f"drop table {table_name}" in downgrade_sql
    assert "add column transport_recipient_identity" in upgrade_sql
    assert "add column transport_recipient_key_version" in upgrade_sql
    assert "create index ix_campaign_member_transport_identity" in upgrade_sql
    assert "drop index ix_campaign_member_transport_identity" in downgrade_sql
    assert "drop column transport_recipient_identity" in downgrade_sql
    for forbidden in (
        "raw_payload",
        "provider_payload",
        "message_content",
        "business_email",
        "api_key",
        "secret_key",
        "phone",
    ):
        assert forbidden not in upgrade_sql


def test_observation_boundary_accepts_staging_qa_only(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-boundary-staging-qa-only.db")
    command.upgrade(alembic_config(engine), "head")

    _insert_observation(engine, _observation_values())


def test_observation_boundary_rejects_staging_non_qa_only(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-boundary-staging-non-qa-only.db")
    command.upgrade(alembic_config(engine), "head")

    with pytest.raises(sa.exc.IntegrityError):
        _insert_observation(engine, _observation_values(qa_only=False))


def test_observation_boundary_accepts_production_non_qa_only(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-boundary-production-non-qa-only.db")
    command.upgrade(alembic_config(engine), "head")

    _insert_observation(
        engine,
        _observation_values(environment="PRODUCTION", qa_only=False),
    )


def test_observation_boundary_rejects_production_qa_only(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-boundary-production-qa-only.db")
    command.upgrade(alembic_config(engine), "head")

    with pytest.raises(sa.exc.IntegrityError):
        _insert_observation(
            engine,
            _observation_values(environment="PRODUCTION", qa_only=True),
        )


@pytest.mark.parametrize(
    ("environment", "environment_overrides"),
    (
        pytest.param("STAGING", {}, id="staging"),
        pytest.param("PRODUCTION", {"qa_only": False}, id="production"),
    ),
)
@pytest.mark.parametrize(
    ("field", "value"),
    (
        pytest.param("mode", "LIVE", id="mode-not-shadow"),
        pytest.param("native_tools", 1, id="native-tools-not-zero"),
    ),
)
def test_observation_boundary_rejects_the_unconditional_prefix(
    tmp_path, environment, environment_overrides, field, value
) -> None:
    """`ck_acquisition_runtime_observation_boundary`'s `mode = 'SHADOW' AND
    native_tools = 0` prefix is unconditional — it must hold for a STAGING
    row exactly as much as a PRODUCTION one. Every other boundary test above
    only ever varies `environment`/`qa_only`, so a regression that folded
    this prefix into only the STAGING branch (e.g. moving it inside the
    first `OR` arm) would still pass every one of them. These four cases —
    both environments, crossed with a non-SHADOW `mode` and a non-zero
    `native_tools` — pin the prefix to both branches directly.
    """
    engine = _engine(tmp_path, "runtime-boundary-prefix.db")
    command.upgrade(alembic_config(engine), "head")

    overrides = {"environment": environment, **environment_overrides, field: value}
    with pytest.raises(sa.exc.IntegrityError):
        _insert_observation(engine, _observation_values(**overrides))
