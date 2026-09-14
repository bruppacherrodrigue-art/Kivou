"""The company release checker mutates only a pre-created, explicitly fenced copy."""

import contextlib
import datetime as dt
import hashlib
import json
import runpy
import zlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from migration_head_helpers import CURRENT_HEAD

from signals.persistence.database import alembic_config, create_database_engine, current_revision

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "docs/reports/prospecting-v11/company-live-rehearsal.py"
SHA = "a" * 40
SOURCE_SHA = "b" * 40
NAME = f"kivou_v11_rehearsal_{SHA[:12]}_1234567890abcdef"
URL = f"postgresql+psycopg://review:secret@localhost/{NAME}"
NOW = dt.datetime(2026, 9, 14, 10, tzinfo=dt.UTC)
HEADS = {"STAGING": "0060_boamp_notice_facts", "PRODUCTION": "0058_model_call_budget"}


def load_checker():
    assert HELPER.is_file(), "company release copy checker is not implemented"
    return SimpleNamespace(**runpy.run_path(str(HELPER)))


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'copy.db'}")
    yield value
    value.dispose()


def seeded(engine, head):
    command.upgrade(alembic_config(engine), head)
    metadata = sa.MetaData()
    table = lambda name: sa.Table(name, metadata, autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            table("account").insert(),
            {
                "account_id": "old-owner",
                "display_name": "PRIVATE_NAME",
                "locale": "fr",
                "onboarding_status": "account_created",
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
        note = table("signal_note")
        connection.execute(
            note.insert(),
            {
                "account_id": "old-owner",
                "signal_key": "old-signal",
                "note": "  PRIVATE_NOTE\n exact whitespace  ",
                "created_at": NOW,
                "updated_at": NOW,
                **({"revision": 9} if "revision" in note.c else {}),
            },
        )
        connection.execute(
            table("supplier_directory").insert(),
            {
                "siren": "481153435",
                "legal_name": "Public company",
                "legal_name_observed_at": NOW,
                "family_keys": ["public-family"],
                "family_confidence": Decimal(".950"),
                "families_observed_at": NOW,
                "directors": [],
                "phone": "+33412345678",
                "enrichment_evidence": {"second": [2, 1], "first": "RAW_NOT_FOR_REPORT"},
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
        if head == HEADS["PRODUCTION"]:
            connection.execute(
                table("model_daily_budget").insert(),
                {
                    "usage_date": NOW.date(),
                    "usage": "enrichment_judge",
                    "reserved_usd": Decimal(".123456"),
                    "actual_usd": Decimal(".0625"),
                    "updated_at": NOW,
                },
            )
            connection.execute(
                table("model_call_journal").insert(),
                {
                    "call_id": "existing-call",
                    "usage": "enrichment_judge",
                    "model": "old-model",
                    "reserved_usd": Decimal(".125"),
                    "actual_usd": Decimal(".0625"),
                    "status": "succeeded",
                    "called_at": NOW,
                    "completed_at": NOW,
                },
            )
        else:
            connection.execute(
                table("source_event").insert(),
                {
                    "event_key": "boamp:fixture",
                    "source_system": "boamp",
                    "source_country": "FR",
                    "source_notice_id": "fixture",
                    "event_type": "award_notice",
                    "procedure_buyers": [],
                    "created_at": NOW,
                },
            )
            connection.execute(
                table("contract_award").insert(),
                {
                    "award_key": "fixture-award",
                    "event_key": "boamp:fixture",
                    "source_award_id": "1",
                    "awardee_parties": [],
                    "cpv_additional": [],
                    "contract_signatories": [],
                    "winner_status": "unresolved",
                    "created_at": NOW,
                },
            )
            raw = b'{"public":"sanitized fixture"}'
            connection.execute(
                table("notice_source_snapshot").insert(),
                {
                    "snapshot_key": "fixture-snapshot",
                    "source_system": "boamp",
                    "source_notice_id": "fixture",
                    "notice_version": "1",
                    "content_hash": hashlib.sha256(raw).hexdigest(),
                    "byte_size": len(raw),
                    "payload_compressed": zlib.compress(raw),
                    "collected_at": NOW,
                    "expires_at": NOW + dt.timedelta(days=30),
                    "created_at": NOW,
                },
            )
            connection.execute(
                table("notice_award_facts").insert(),
                {
                    "facts_key": "fixture-facts",
                    "snapshot_key": "fixture-snapshot",
                    "event_key": "boamp:fixture",
                    "award_key": "fixture-award",
                    "extractor_version": "fixture",
                    "source_set_hash": "c" * 64,
                    "facts": {"public": {"amount": "12.50", "nested": [1, 2]}},
                    "collected_at": NOW,
                    "created_at": NOW,
                },
            )


@pytest.mark.parametrize("environment,head", HEADS.items())
def test_both_deployed_parents_preserve_private_shared_and_replayed_contracts(
    engine, tmp_path, environment, head
):
    checker = load_checker()
    seeded(engine, head)
    report = checker.run_checks(
        engine,
        source_environment=environment,
        expected_deployed_head=head,
        now=NOW,
        temp_dir=tmp_path,
    )
    assert current_revision(engine) == CURRENT_HEAD
    assert report["legacy_preserved"] and report["replay_preserved"]
    assert report["contracts"]["note_2000_boundary"]
    assert report["contracts"]["workflow_contact_history"]
    expected = (
        {"supplier_directory", "model_daily_budget", "model_call_journal"}
        if environment == "PRODUCTION"
        else {"supplier_directory", "notice_source_snapshot", "notice_award_facts"}
    )
    assert set(report["shared_baseline_rows"]) == expected
    assert all(report["shared_baseline_rows"][name] == 1 for name in expected)
    assert not list(tmp_path.glob("kivou-v11-baseline-*"))
    assert not any(
        secret in json.dumps(report)
        for secret in ("PRIVATE_", "RAW_NOT", "old-owner", "existing-call")
    )


@pytest.mark.parametrize("name", ["kivou", "kivou_staging", "postgres", "other_copy"])
def test_live_database_names_are_rejected_before_connection(name):
    checker = load_checker()
    url = f"postgresql://review:secret@localhost/{name}"
    with pytest.raises(checker.checks.RehearsalFailure):
        checker.validate_configuration(
            url, url, name, SHA, "PRODUCTION", HEADS["PRODUCTION"], SOURCE_SHA
        )


@pytest.mark.parametrize(
    "environment,head",
    [
        ("", HEADS["STAGING"]),
        ("PRODUCTION", HEADS["STAGING"]),
        ("STAGING", HEADS["PRODUCTION"]),
        ("STAGING", "head"),
    ],
)
def test_source_environment_requires_its_exact_verified_branch(environment, head):
    checker = load_checker()
    with pytest.raises(checker.checks.RehearsalFailure):
        checker.validate_configuration(URL, URL, NAME, SHA, environment, head, SOURCE_SHA)


def test_configuration_keeps_source_artifact_explicit_and_default_database_on_copy():
    checker = load_checker()
    assert (
        checker.validate_configuration(
            URL, URL, NAME, SHA, "PRODUCTION", HEADS["PRODUCTION"], SOURCE_SHA
        ).database
        == NAME
    )
    with pytest.raises(checker.checks.RehearsalFailure):
        checker.validate_configuration(
            URL,
            URL.replace(NAME, "kivou"),
            NAME,
            SHA,
            "PRODUCTION",
            HEADS["PRODUCTION"],
            SOURCE_SHA,
        )
    with pytest.raises(checker.checks.RehearsalFailure):
        checker.validate_configuration(
            URL, URL, NAME, SHA, "PRODUCTION", HEADS["PRODUCTION"], "short"
        )


def test_wrong_or_multiple_restored_heads_fail_before_migration(engine, tmp_path):
    checker = load_checker()
    seeded(engine, HEADS["STAGING"])
    with pytest.raises(checker.checks.RehearsalFailure, match="restored_head_mismatch"):
        checker.run_checks(
            engine,
            source_environment="PRODUCTION",
            expected_deployed_head=HEADS["PRODUCTION"],
            now=NOW,
            temp_dir=tmp_path,
        )
    assert current_revision(engine) == HEADS["STAGING"]
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO alembic_version VALUES ('0058_model_call_budget')"))
    with pytest.raises(checker.checks.RehearsalFailure, match="restored_head_mismatch"):
        checker.run_checks(
            engine,
            source_environment="STAGING",
            expected_deployed_head=HEADS["STAGING"],
            now=NOW,
            temp_dir=tmp_path,
        )
    assert not list(tmp_path.glob("kivou-v11-baseline-*"))


@pytest.mark.parametrize(
    "head,table,column,value",
    [
        (HEADS["STAGING"], "supplier_directory", "phone", "CHANGED"),
        (HEADS["STAGING"], "notice_source_snapshot", "payload_compressed", b"changed"),
        (HEADS["STAGING"], "notice_award_facts", "facts", {"changed": True}),
        (HEADS["PRODUCTION"], "model_daily_budget", "actual_usd", Decimal("1")),
        (HEADS["PRODUCTION"], "model_call_journal", "model", "changed"),
    ],
)
def test_shared_baseline_detects_every_protected_table_change(engine, head, table, column, value):
    checker = load_checker()
    seeded(engine, head)
    with checker.checks.capture_baseline(engine, extra_tables=checker.SHARED_TABLES) as baseline:
        changed = sa.Table(table, sa.MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(changed.update().values({column: value}))
        with pytest.raises(checker.checks.RehearsalFailure, match="legacy_private_value_changed"):
            checker.checks.compare_baseline(engine, baseline)


def test_candidate_checkout_sha_must_match_before_database_use():
    checker = load_checker()
    with pytest.raises(checker.checks.RehearsalFailure, match="candidate_checkout_sha_mismatch"):
        checker.verify_checkout(SHA)


def test_candidate_checker_and_reused_helper_must_be_tracked_in_candidate(monkeypatch):
    checker = load_checker()
    monkeypatch.setattr(checker.subprocess, "check_output", lambda *_args, **_kwargs: SHA)
    monkeypatch.setattr(
        checker.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=1)
    )
    with pytest.raises(checker.checks.RehearsalFailure, match="candidate_checker_untracked"):
        checker.verify_checkout(SHA)


def test_actual_database_mismatch_is_closed_before_migration_and_engine_is_disposed(
    monkeypatch, capsys
):
    checker = load_checker()
    for name, value in {
        "KIVOU_V11_REHEARSAL_DATABASE_NAME": NAME,
        "KIVOU_V11_REHEARSAL_DATABASE_URL": URL,
        "KIVOU_DATABASE_URL": URL,
        "KIVOU_V11_CANDIDATE_SHA": SHA,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(checker.subprocess, "check_output", lambda *_args, **_kwargs: SHA)
    monkeypatch.setattr(
        checker.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0)
    )

    class WrongDatabase:
        dialect = SimpleNamespace(name="postgresql")
        disposed = False

        @contextlib.contextmanager
        def connect(self):
            yield SimpleNamespace(scalar=lambda _query: "kivou")

        def dispose(self):
            self.disposed = True

    wrong = WrongDatabase()
    monkeypatch.setattr(checker.sa, "create_engine", lambda *_args, **_kwargs: wrong)
    monkeypatch.setitem(
        checker.main.__globals__,
        "run_checks",
        lambda *_args, **_kwargs: pytest.fail("wrong database reached migrations"),
    )
    assert (
        checker.main(
            [
                "--source-environment",
                "PRODUCTION",
                "--expected-deployed-head",
                HEADS["PRODUCTION"],
                "--source-sha",
                SOURCE_SHA,
            ]
        )
        == 2
    )
    result = capsys.readouterr()
    assert json.loads(result.out) == {"status": "failed", "code": "connected_database_mismatch"}
    assert result.err == "" and wrong.disposed


def test_baseline_temporary_files_close_if_migration_checks_fail(engine, tmp_path, monkeypatch):
    checker = load_checker()
    seeded(engine, HEADS["STAGING"])

    def failed(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_DATABASE_DETAIL")

    monkeypatch.setattr(checker.checks, "migrate_and_check", failed)
    with pytest.raises(RuntimeError):
        checker.run_checks(
            engine,
            source_environment="STAGING",
            expected_deployed_head=HEADS["STAGING"],
            now=NOW,
            temp_dir=tmp_path,
        )
    assert not list(tmp_path.glob("kivou-v11-baseline-*"))


def test_replay_compares_shared_rows_and_removes_both_private_baselines(
    engine, tmp_path, monkeypatch
):
    checker = load_checker()
    seeded(engine, HEADS["STAGING"])
    migrate = checker.checks.migrate_to_latest

    def corrupt_replay(target):
        migrate(target)
        table = sa.Table("supplier_directory", sa.MetaData(), autoload_with=target)
        with target.begin() as connection:
            connection.execute(table.update().values(phone="CHANGED_ON_REPLAY"))

    monkeypatch.setattr(checker.checks, "migrate_to_latest", corrupt_replay)
    with pytest.raises(checker.checks.RehearsalFailure, match="legacy_private_value_changed"):
        checker.run_checks(
            engine,
            source_environment="STAGING",
            expected_deployed_head=HEADS["STAGING"],
            now=NOW,
            temp_dir=tmp_path,
        )
    assert not list(tmp_path.glob("kivou-v11-baseline-*"))


def test_extra_tables_never_filter_private_rows_and_missing_historical_tables_are_allowed(engine):
    checker = load_checker()
    seeded(engine, HEADS["STAGING"])
    with checker.checks.capture_baseline(engine, extra_tables=checker.SHARED_TABLES) as baseline:
        assert "signal_note" in baseline and "account" in baseline
        assert "model_daily_budget" not in baseline
        assert baseline["supplier_directory"]["row_count"] == 1
    with pytest.raises(checker.checks.RehearsalFailure, match="baseline_extra_tables_invalid"):
        checker.checks.capture_baseline(engine, extra_tables="supplier_directory")


def test_main_configuration_failure_is_closed_and_never_constructs_engine(monkeypatch, capsys):
    checker = load_checker()
    monkeypatch.setenv("KIVOU_V11_REHEARSAL_DATABASE_NAME", "kivou")
    monkeypatch.setenv(
        "KIVOU_V11_REHEARSAL_DATABASE_URL", "postgresql://secret:PRIVATE_PASSWORD@localhost/kivou"
    )
    monkeypatch.setattr(
        checker.sa,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail("invalid config opened a database"),
    )
    assert (
        checker.main(
            [
                "--source-environment",
                "PRODUCTION",
                "--expected-deployed-head",
                HEADS["PRODUCTION"],
                "--source-sha",
                SOURCE_SHA,
            ]
        )
        == 2
    )
    result = capsys.readouterr()
    assert json.loads(result.out)["status"] == "failed"
    assert "PRIVATE_PASSWORD" not in result.out + result.err
