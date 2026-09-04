from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.accounts.schema import account, target_icp
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)
from signals.persistence.schema import (
    METADATA,
    contract_award,
    materialized_signal,
    source_event,
)

PREVIOUS = "0027_signal_notes"
#: La migration que CE fichier décrit. Elle n'est plus la tête depuis 0029,
#: mais reste un pas ADDITIF unique depuis son parent — ce que ce test prouve.
HEAD = "0028_card_presentation"
CURRENT_HEAD = "0038_landing_journey"
TABLE_NAME = "card_presentation_artifact"
ACTIVE_INDEX = "uq_card_presentation_active_publication"
TENANT_READ_INDEX = "ix_card_presentation_tenant_read"
NOW = dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC)

EXPECTED_COLUMNS = {
    "artifact_id",
    "account_id",
    "signal_key",
    "signal_revision",
    "target_icp_id",
    "target_icp_revision",
    "artifact_kind",
    "language",
    "version",
    "input_fingerprint",
    "payload",
    "payload_variant",
    "qa_status",
    "qa_reasons",
    "qa_policy_version",
    "generator_version",
    "prompt_version",
    "model_id",
    "provider",
    "qa_model_id",
    "qa_provider",
    "created_at",
    "published_at",
    "superseded_at",
}


def _engine(tmp_path, name: str) -> sa.Engine:
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def _table() -> sa.Table:
    return METADATA.tables[TABLE_NAME]


def _seed_bindings(connection: sa.Connection) -> None:
    connection.execute(
        sa.insert(account).values(
            account_id="account-qa",
            display_name="QA",
            locale="fr",
            onboarding_status="ready_for_signals",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    connection.execute(
        sa.insert(target_icp).values(
            target_icp_id="icp-qa",
            account_id="account-qa",
            label="QA",
            status="active",
            matching_revision=3,
            plan_limit_code=None,
            plan_limited_at=None,
            customer_input={"offers": ["materials_and_components"]},
            created_at=NOW,
            updated_at=NOW,
        )
    )
    connection.execute(
        sa.insert(source_event).values(
            event_key="decp:qa:1",
            source_system="decp",
            source_notice_id="qa",
            notice_version="1",
            source_country="FR",
            event_type="award_notice",
            procedure_buyers=[],
            created_at=NOW,
        )
    )
    connection.execute(
        sa.insert(contract_award).values(
            award_key="award-qa",
            event_key="decp:qa:1",
            cpv_additional=[],
            winner_status="identified",
            awardee_parties=[],
            contract_signatories=[],
            created_at=NOW,
        )
    )
    connection.execute(
        sa.insert(materialized_signal).values(
            signal_key="signal-qa",
            opportunity_key="opportunity-qa",
            materialization_award_key="award-qa",
            target_icp_id="icp-qa",
            target_icp_revision=3,
            revision=7,
            content_fingerprint="c" * 64,
            materialized_recency_status="recent_award",
            materialized_award_clock_status="known",
            materialized_notification_clock_status="unknown",
            materialized_publication_clock_status="known",
            materialized_as_of=NOW.date(),
            recency_policy_version="recency-v1",
            plausible_needs=[],
            icp_matched_needs=[],
            engine_versions={},
            materialized_at=NOW,
            created_at=NOW,
        )
    )


def artifact_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "artifact_id": "a" * 64,
        "account_id": "account-qa",
        "signal_key": "signal-qa",
        "signal_revision": 7,
        "target_icp_id": "icp-qa",
        "target_icp_revision": 3,
        "artifact_kind": "CARD_PRESENTATION",
        "language": "fr",
        "version": 1,
        "input_fingerprint": "b" * 64,
        "payload": {"schema_version": 1, "variant": "FACTUAL_FALLBACK"},
        "payload_variant": "FACTUAL_FALLBACK",
        "qa_status": "FALLBACK",
        "qa_reasons": ["deterministic_factual_fallback"],
        "qa_policy_version": "factual-qa-v1",
        "generator_version": "factual-fallback-v1",
        "prompt_version": None,
        "model_id": None,
        "provider": None,
        "qa_model_id": None,
        "qa_provider": None,
        "created_at": NOW,
        "published_at": NOW,
        "superseded_at": None,
    }
    values.update(overrides)
    return values


@pytest.fixture
def migrated_engine(tmp_path) -> sa.Engine:
    engine = _engine(tmp_path, "card-presentation-constraints.db")
    command.upgrade(alembic_config(engine), HEAD)
    with engine.begin() as connection:
        _seed_bindings(connection)
    return engine


def _assert_integrity_error(engine: sa.Engine, values: Mapping[str, object]) -> None:
    with engine.begin() as connection, pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.insert(_table()).values(**values))


def test_card_presentation_migration_is_one_additive_table(tmp_path) -> None:
    engine = _engine(tmp_path, "card-presentation.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    scripts = ScriptDirectory.from_config(config)
    assert set(sa.inspect(engine).get_table_names()) - before == {TABLE_NAME}
    assert current_revision(engine) == HEAD
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS


def test_declared_and_migrated_table_have_the_exact_closed_shape(tmp_path) -> None:
    engine = _engine(tmp_path, "card-presentation-shape.db")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)
    migrated = {column["name"]: column for column in inspector.get_columns(TABLE_NAME)}

    assert set(migrated) == EXPECTED_COLUMNS
    assert {column.name for column in _table().columns} == EXPECTED_COLUMNS
    assert inspector.get_pk_constraint(TABLE_NAME)["constrained_columns"] == [
        "artifact_id"
    ]
    assert {
        "payload",
        "payload_variant",
        "prompt_version",
        "model_id",
        "provider",
        "qa_model_id",
        "qa_provider",
        "published_at",
        "superseded_at",
    } == {name for name, column in migrated.items() if column["nullable"]}
    for name in ("prompt_version", "model_id", "provider", "qa_model_id", "qa_provider"):
        assert migrated[name]["default"] is None
    assert migrated["qa_policy_version"]["type"].length == 128
    assert migrated["generator_version"]["type"].length == 128
    assert {
        constraint.name
        for constraint in _table().constraints
        if isinstance(constraint, sa.CheckConstraint)
    } == {
        item["name"] for item in inspector.get_check_constraints(TABLE_NAME)
    }


def test_foreign_keys_versions_checks_and_read_indexes_are_durable(tmp_path) -> None:
    engine = _engine(tmp_path, "card-presentation-schema.db")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)

    foreign_keys = {
        tuple(item["constrained_columns"]): (
            item["referred_table"],
            tuple(item["referred_columns"]),
            item["options"].get("ondelete"),
        )
        for item in inspector.get_foreign_keys(TABLE_NAME)
    }
    assert foreign_keys == {
        ("account_id",): ("account", ("account_id",), "CASCADE"),
        ("signal_key",): ("materialized_signal", ("signal_key",), "RESTRICT"),
        ("target_icp_id",): ("target_icp", ("target_icp_id",), "RESTRICT"),
    }
    assert {
        (item["name"], tuple(item["column_names"]))
        for item in inspector.get_unique_constraints(TABLE_NAME)
    } == {
        (
            "uq_card_presentation_version",
            (
                "account_id",
                "signal_key",
                "target_icp_id",
                "artifact_kind",
                "language",
                "version",
            ),
        )
    }
    indexes = {item["name"]: item for item in inspector.get_indexes(TABLE_NAME)}
    assert indexes[TENANT_READ_INDEX]["column_names"] == [
        "account_id",
        "language",
        "artifact_kind",
        "signal_key",
        "signal_revision",
        "target_icp_revision",
    ]
    assert indexes[ACTIVE_INDEX]["column_names"] == [
        "account_id",
        "signal_key",
        "target_icp_id",
        "artifact_kind",
        "language",
    ]
    assert indexes[ACTIVE_INDEX]["unique"] == 1
    assert "published_at is not null" in str(
        indexes[ACTIVE_INDEX]["dialect_options"]["sqlite_where"]
    ).casefold()
    assert "superseded_at is null" in str(
        indexes[ACTIVE_INDEX]["dialect_options"]["sqlite_where"]
    ).casefold()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_id", "a" * 63),
        ("artifact_id", "g" * 64),
        ("artifact_id", "A" * 64),
        ("input_fingerprint", "b" * 63),
        ("input_fingerprint", "z" * 64),
        ("input_fingerprint", "B" * 64),
        ("signal_revision", 0),
        ("target_icp_revision", 0),
        ("version", 0),
        ("language", "de"),
        ("artifact_kind", "OTHER"),
    ],
)
def test_closed_identity_revision_language_and_kind_checks(
    migrated_engine: sa.Engine, field: str, value: object
) -> None:
    _assert_integrity_error(migrated_engine, artifact_values(**{field: value}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"account_id": "missing-account"},
        {"signal_key": "missing-signal"},
        {"target_icp_id": "missing-icp"},
    ],
)
def test_every_binding_is_protected_by_a_foreign_key(
    migrated_engine: sa.Engine, overrides: dict[str, object]
) -> None:
    _assert_integrity_error(migrated_engine, artifact_values(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"published_at": NOW - dt.timedelta(seconds=1)},
        {"superseded_at": NOW - dt.timedelta(seconds=1)},
        {"published_at": None, "superseded_at": NOW + dt.timedelta(seconds=1)},
    ],
)
def test_artifact_timestamps_are_ordered(
    migrated_engine: sa.Engine, overrides: dict[str, object]
) -> None:
    _assert_integrity_error(migrated_engine, artifact_values(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"qa_status": "UNKNOWN"},
        {"payload_variant": "UNKNOWN"},
        {"qa_status": "PASS", "payload_variant": "FACTUAL_FALLBACK"},
        {"qa_status": "FALLBACK", "payload_variant": "FULL"},
        {"qa_status": "REVIEW", "payload_variant": "FULL"},
        {"qa_status": "REGENERATE", "payload_variant": "FULL"},
        {"payload": None, "payload_variant": None},
        {"published_at": None, "payload": None, "payload_variant": "FULL"},
    ],
)
def test_invalid_status_variant_or_payload_fails_closed(
    migrated_engine: sa.Engine, overrides: dict[str, object]
) -> None:
    _assert_integrity_error(migrated_engine, artifact_values(**overrides))


@pytest.mark.parametrize(
    "provider_metadata",
    [
        {"provider": "forbidden"},
        {"model_id": "forbidden"},
        {"prompt_version": "forbidden"},
        {"qa_provider": "forbidden"},
        {"qa_model_id": "forbidden"},
    ],
)
def test_fallback_metadata_cannot_claim_a_provider(
    migrated_engine: sa.Engine, provider_metadata: dict[str, object]
) -> None:
    _assert_integrity_error(migrated_engine, artifact_values(**provider_metadata))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qa_policy_version", None),
        ("qa_policy_version", ""),
        ("qa_policy_version", "   "),
        ("qa_policy_version", "\t"),
        ("qa_policy_version", "\n"),
        ("qa_policy_version", "-_.:"),
        ("qa_policy_version", "q" * 129),
        ("generator_version", ""),
        ("generator_version", "   "),
        ("generator_version", "\t"),
        ("generator_version", "\n"),
        ("generator_version", "-_.:"),
        ("generator_version", "g" * 129),
        ("qa_reasons", None),
    ],
)
def test_required_provenance_is_non_null_non_empty_and_bounded(
    migrated_engine: sa.Engine, field: str, value: object
) -> None:
    _assert_integrity_error(migrated_engine, artifact_values(**{field: value}))


def test_published_fallback_persists_qa_reasons_as_a_json_list(
    migrated_engine: sa.Engine,
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(sa.insert(_table()).values(**artifact_values()))
    with migrated_engine.connect() as connection:
        row = connection.execute(
            sa.select(
                _table().c.qa_reasons,
                _table().c.qa_policy_version,
                _table().c.generator_version,
            ).where(
                _table().c.artifact_id == "a" * 64
            )
        ).one()
    assert row.qa_reasons == ["deterministic_factual_fallback"]
    assert row.qa_policy_version == "factual-qa-v1"
    assert row.generator_version == "factual-fallback-v1"


def test_pass_full_and_unpublished_review_are_the_only_respective_valid_shapes(
    migrated_engine: sa.Engine,
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            sa.insert(_table()).values(
                **artifact_values(
                    artifact_id="d" * 64,
                    input_fingerprint="e" * 64,
                    language="en",
                    qa_status="PASS",
                    payload={"schema_version": 1, "variant": "FULL"},
                    payload_variant="FULL",
                    generator_version="generator-v1",
                    provider="approved-provider",
                    model_id="approved-model",
                    prompt_version="prompt-v1",
                    qa_provider="approved-qa-provider",
                    qa_model_id="approved-qa-model",
                )
            )
        )
        connection.execute(
            sa.insert(_table()).values(
                **artifact_values(
                    artifact_id="e" * 64,
                    version=2,
                    published_at=None,
                    payload=None,
                    payload_variant=None,
                    qa_status="REVIEW",
                    qa_reasons=["human_review_required"],
                )
            )
        )


def test_partial_unique_index_allows_attempts_but_only_one_active_publication(
    migrated_engine: sa.Engine,
) -> None:
    table = _table()
    with migrated_engine.begin() as connection:
        connection.execute(sa.insert(table).values(**artifact_values()))
        connection.execute(
            sa.insert(table).values(
                **artifact_values(
                    artifact_id="d" * 64,
                    input_fingerprint="d" * 64,
                    version=2,
                    published_at=None,
                    payload=None,
                    payload_variant=None,
                    qa_status="REVIEW",
                )
            )
        )
        connection.execute(
            sa.insert(table).values(
                **artifact_values(
                    artifact_id="e" * 64,
                    input_fingerprint="e" * 64,
                    version=3,
                    published_at=None,
                    payload=None,
                    payload_variant=None,
                    qa_status="REGENERATE",
                )
            )
        )

    _assert_integrity_error(
        migrated_engine,
        artifact_values(
            artifact_id="f" * 64,
            input_fingerprint="f" * 64,
            version=4,
        ),
    )

    with migrated_engine.begin() as connection:
        connection.execute(
            sa.update(table)
            .where(table.c.artifact_id == "a" * 64)
            .values(superseded_at=NOW + dt.timedelta(seconds=1))
        )
        connection.execute(
            sa.insert(table).values(
                **artifact_values(
                    artifact_id="f" * 64,
                    input_fingerprint="f" * 64,
                    version=4,
                    created_at=NOW + dt.timedelta(seconds=1),
                    published_at=NOW + dt.timedelta(seconds=1),
                )
            )
        )


def test_version_number_is_unique_inside_the_presentation_stream(
    migrated_engine: sa.Engine,
) -> None:
    table = _table()
    with migrated_engine.begin() as connection:
        connection.execute(
            sa.insert(table).values(
                **artifact_values(published_at=None, payload=None, payload_variant=None)
            )
        )
    _assert_integrity_error(
        migrated_engine,
        artifact_values(
            artifact_id="d" * 64,
            input_fingerprint="d" * 64,
            published_at=None,
            payload=None,
            payload_variant=None,
        ),
    )


def test_targeted_downgrade_and_reupgrade_leave_0027_intact(tmp_path) -> None:
    engine = _engine(tmp_path, "card-presentation-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    assert "signal_note" in sa.inspect(engine).get_table_names()

    command.downgrade(config, PREVIOUS)

    tables = set(sa.inspect(engine).get_table_names())
    assert TABLE_NAME not in tables
    assert "signal_note" in tables
    assert current_revision(engine) == PREVIOUS

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
    assert TABLE_NAME in sa.inspect(engine).get_table_names()


def test_postgresql_offline_sql_is_additive_partial_and_provider_neutral(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou"
    )

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)

    raw_sql = capsys.readouterr().out
    sql = raw_sql.lower()
    assert sql.count(f"create table {TABLE_NAME} (") == 1
    assert "foreign key(account_id) references account" in sql
    assert "foreign key(signal_key) references materialized_signal" in sql
    assert "foreign key(target_icp_id) references target_icp" in sql
    assert f"create unique index {ACTIVE_INDEX}" in sql
    assert "where published_at is not null and superseded_at is null" in sql
    assert f"create index {TENANT_READ_INDEX}" in sql
    assert "ck_card_presentation_publishable_pair" in sql
    assert "ck_card_presentation_fallback_offline" in sql
    assert "qa_policy_version varchar(128) not null" in sql
    assert "ck_card_presentation_qa_policy_version" in sql
    assert "ck_card_presentation_generator_version" in sql
    assert "qa_policy_version ~ '[0-9A-Za-z]'" in raw_sql
    assert "generator_version ~ '[0-9A-Za-z]'" in raw_sql
    assert "alter table" not in sql
    assert "drop table" not in sql
    assert "hermes" not in sql
    assert " default " not in sql
