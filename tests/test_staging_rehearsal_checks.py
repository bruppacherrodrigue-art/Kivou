"""Rehearsal checks touch disposable databases only; no live orchestration."""

import datetime as dt
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from test_notice_backfill import record
from test_prospecting_migration import engine as engine  # noqa: PLC0414
from test_prospecting_migration import populated_0058

from signals.connectors.boamp import parse_award_notice
from signals.engagement import feedback, status
from signals.engagement.schema import company_note, signal_feedback, signal_workflow
from signals.persistence.database import current_revision, migrate_to_latest
from signals.persistence.identity import award_key
from signals.persistence.schema import contract_award, source_event

HELPER = Path(__file__).resolve().parents[1] / "docs/reports/prospecting-v11/rehearsal-checks.py"
SHA = "a" * 40
NAME = "kivou_v11_rehearsal_aaaaaaaaaaaa_1234567890abcdef"
NOW = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)


def test_helper_is_available_for_the_operator():
    assert HELPER.is_file(), "bounded rehearsal checks helper is not implemented"


@pytest.fixture
def checks():
    assert HELPER.is_file(), "bounded rehearsal checks helper is not implemented"
    return SimpleNamespace(**runpy.run_path(str(HELPER)))


def test_target_configuration_accepts_only_explicit_copy(checks):
    url = checks.validate_target_config(
        f"postgresql+psycopg://review:secret@localhost/{NAME}",
        f"postgresql+psycopg://review:secret@localhost/{NAME}",
        NAME,
        SHA,
    )
    assert url.database == NAME


@pytest.mark.parametrize(
    "target,source,name,sha",
    [
        ("", "postgresql://localhost/staging", NAME, SHA),
        (f"postgresql://localhost/{NAME}", "", NAME, SHA),
        ("sqlite+pysqlite:///:memory:", "postgresql://localhost/staging", NAME, SHA),
        (f"postgresql://localhost/{NAME}", "postgresql://localhost/kivou_staging", NAME, SHA),
        (f"postgresql://localhost/{NAME}", f"postgresql://other/{NAME}", NAME, SHA),
        ("postgresql://localhost/staging", "postgresql://localhost/staging", "staging", SHA),
        (f"postgresql://localhost/{NAME}", "postgresql://localhost/staging", NAME, "b" * 40),
        (f"postgresql://localhost/{NAME}", "postgresql://localhost/staging", NAME, "short"),
        (
            f"postgresql://localhost/{NAME}?dbname=staging",
            "postgresql://localhost/staging",
            NAME,
            SHA,
        ),
    ],
)
def test_invalid_target_is_rejected_before_connection(checks, target, source, name, sha):
    with pytest.raises(checks.RehearsalFailure):
        checks.validate_target_config(target, source, name, sha)


def test_populated_copy_migration_and_contract_checks_preserve_original_accounts(checks, engine):
    populated_0058(engine)
    baseline = checks.capture_baseline(engine)
    report = checks.migrate_and_check(engine, now=NOW)
    assert current_revision(engine) == "0060_boamp_notice_facts"
    assert report["legacy_preserved"] is True
    assert report["contracts"]["note_cas"] is True
    assert report["contracts"]["note_tombstones"] is True
    assert report["contracts"]["note_2000_boundary"] is True
    assert report["contracts"]["account_isolation"] is True
    assert report["contracts"]["manual_contact_tombstone"] is True
    assert report["contracts"]["workflow_cas"] is True
    assert report["contracts"]["export_isolation"] is True
    checks.compare_baseline(engine, baseline)
    serialized = json.dumps(report)
    assert "Historical" not in serialized
    assert "Company" not in serialized
    assert "account_a" not in serialized


def test_baseline_detects_private_value_changes_without_echoing_content(checks, engine):
    populated_0058(engine)
    baseline = checks.capture_baseline(engine)
    migrate_to_latest(engine)
    with engine.begin() as connection:
        connection.execute(company_note.update().values(body="SECRET_CHANGED_VALUE"))
    with pytest.raises(checks.RehearsalFailure, match="legacy_private_value_changed") as failure:
        checks.compare_baseline(engine, baseline)
    assert "SECRET" not in str(failure.value)


def test_baseline_bound_cannot_silently_sample_private_accounts(checks, engine):
    populated_0058(engine)
    with pytest.raises(checks.RehearsalFailure, match="baseline_limit"):
        checks.capture_baseline(engine, limit=1)


def test_baseline_includes_indirectly_account_owned_sessions(checks, engine):
    migrate_to_latest(engine)
    baseline = checks.capture_baseline(engine)
    assert {"auth_session", "password_reset"} <= baseline.keys()
    metadata = sa.MetaData()
    with engine.begin() as connection:
        owner = sa.Table("account", metadata, autoload_with=connection)
        nested = sa.Table(
            "rehearsal_private_child",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("owner", sa.ForeignKey(owner.c.account_id)),
        )
        nested.create(connection)
    assert "rehearsal_private_child" in checks.capture_baseline(engine)


def test_contract_checks_reject_a_broken_2001_character_writer(checks, engine, monkeypatch):
    migrate_to_latest(engine)
    real_put = checks.notes.put

    def broken_put(connection, **arguments):
        if len(arguments["note"]) == 2001:
            return None
        return real_put(connection, **arguments)

    monkeypatch.setattr(checks.notes, "put", broken_put)
    with pytest.raises(checks.RehearsalFailure, match="signal_note_2001_accepted"):
        checks.exercise_private_contracts(engine, now=NOW)


def test_contract_checks_detect_missing_workflow_exports(checks, engine, monkeypatch):
    migrate_to_latest(engine)
    real_export = checks.export_account

    def broken_export(connection, **arguments):
        payload = real_export(connection, **arguments)
        payload["data"]["signal_workflow"] = []
        return payload

    monkeypatch.setitem(checks._export_checked.__globals__, "export_account", broken_export)
    with pytest.raises(checks.RehearsalFailure, match="workflow_export_missing"):
        checks.exercise_private_contracts(engine, now=NOW)


def test_contract_checks_preserve_contacted_history_after_return_to_new(checks, engine):
    migrate_to_latest(engine)
    report = checks.exercise_private_contracts(engine, now=NOW)
    with engine.connect() as connection:
        row = connection.execute(sa.select(signal_workflow)).mappings().one()
        arguments = {"account_id": row["account_id"], "signal_key": row["signal_key"]}
        historical = feedback.get_feedback(connection, **arguments)
        assert historical is not None and historical.contacted_at == NOW
        workflow = status.get_workflow(connection, **arguments)
        assert workflow.revision == 5
        assert status.unified_status(historical, workflow) == "new"
    assert report["workflow_contact_history"] is True


def test_contract_checks_reject_a_workflow_writer_that_erases_contact_history(
    checks, engine, monkeypatch
):
    migrate_to_latest(engine)
    real_set_status = status.set_status

    def broken_status(connection, **arguments):
        result = real_set_status(connection, **arguments)
        if arguments["status"] == "new":
            connection.execute(
                signal_feedback.update()
                .where(
                    signal_feedback.c.account_id == arguments["account_id"],
                    signal_feedback.c.signal_key == arguments["context"].signal_key,
                )
                .values(contacted_at=None)
            )
        return result

    monkeypatch.setattr(status, "set_status", broken_status)
    with pytest.raises(checks.RehearsalFailure, match="workflow_contact_history_lost"):
        checks.exercise_private_contracts(engine, now=NOW)


def seed_notices(engine, notice_ids):
    payloads = {}
    with engine.begin() as connection:
        for notice_id in notice_ids:
            raw = record()
            raw["idweb"] = notice_id
            payloads[notice_id] = raw
            event, awards = parse_award_notice(raw, retrieved_at=NOW)
            connection.execute(
                source_event.insert().values(
                    event_key=event.ref().key(),
                    source_system="boamp",
                    source_country="FR",
                    source_notice_id=notice_id,
                    notice_version=event.provenance.notice_version,
                    event_type="award_notice",
                    procedure_buyers=[],
                    created_at=NOW,
                )
            )
            for award in awards:
                connection.execute(
                    contract_award.insert().values(
                        award_key=award_key(award),
                        event_key=event.ref().key(),
                        source_award_id=award.source_award_id,
                        lot_identifier=award.lot.identifier,
                        awardee_parties=[
                            party.model_dump(mode="json") for party in award.awardee_parties
                        ],
                        cpv_additional=[],
                        contract_signatories=[],
                        winner_status="identified",
                        created_at=NOW,
                    )
                )
    return payloads


def test_backfill_requires_all_four_exact_notices(checks, engine):
    migrate_to_latest(engine)
    seed_notices(engine, checks.NOTICE_IDS[:3])
    with pytest.raises(checks.RehearsalFailure, match="boamp_notice_missing"):
        checks.select_boamp_events(engine)


def test_backfill_uses_selected_copy_events_and_private_durable_cursor(
    checks, engine, tmp_path, monkeypatch
):
    migrate_to_latest(engine)
    payloads = seed_notices(engine, checks.NOTICE_IDS)
    calls = []
    modes = []
    real_backfill = checks.notice_backfill.backfill_notice_facts

    def observed_backfill(*args, **kwargs):
        modes.append((kwargs.get("dry_run"), kwargs.get("client") is None))
        return real_backfill(*args, **kwargs)

    monkeypatch.setattr(checks.notice_backfill, "backfill_notice_facts", observed_backfill)

    class Reader:
        def fetch_record(self, notice_id):
            calls.append(notice_id)
            return payloads[notice_id]

    private = tmp_path / "rehearsal"
    private.mkdir(mode=0o700)
    cursor = private / "cursor.json"
    report = checks.run_backfill_checks(engine, cursor_path=cursor, client=Reader(), now=NOW)
    assert sorted(calls) == sorted(checks.NOTICE_IDS)
    assert report["idempotent"] is True
    assert report["all_notices_have_facts"] is True
    assert report["passes"] == 1
    assert modes[-1] == (False, True), (
        "Idempotence must exercise execution, without a network reader"
    )
    assert cursor.stat().st_mode & 0o077 == 0
    again = checks.run_backfill_checks(engine, cursor_path=cursor, client=Reader(), now=NOW)
    assert again["idempotent"] is True
    assert len(calls) == 4


def test_failed_backfill_never_restarts_attempts_or_claims_complete(checks, engine, tmp_path):
    migrate_to_latest(engine)
    seed_notices(engine, checks.NOTICE_IDS)
    calls = []

    class Reader:
        def fetch_record(self, notice_id):
            calls.append(notice_id)
            raise ValueError("SECRET_PROVIDER_FAILURE")

    private = tmp_path / "rehearsal"
    private.mkdir(mode=0o700)
    cursor = private / "cursor.json"
    report = checks.run_backfill_checks(engine, cursor_path=cursor, client=Reader(), now=NOW)
    assert report["passes"] == 3
    assert report["all_notices_have_facts"] is False
    assert len(calls) == 12
    assert "SECRET_PROVIDER" not in json.dumps(report)
    again = checks.run_backfill_checks(engine, cursor_path=cursor, client=Reader(), now=NOW)
    assert again["all_notices_have_facts"] is False
    assert len(calls) == 12


def test_cursor_rejects_world_readable_parent(checks, tmp_path):
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(checks.RehearsalFailure, match="cursor_parent_not_private"):
        checks.validate_cursor_path(public / "cursor.json")


def test_cli_reports_only_closed_failure_and_never_connects_with_missing_env(
    checks, monkeypatch, capsys
):
    for key in (
        "KIVOU_V11_REHEARSAL_DATABASE_URL",
        "KIVOU_V11_REHEARSAL_DATABASE_NAME",
        "KIVOU_V11_CANDIDATE_SHA",
        "KIVOU_V11_REHEARSAL_CURSOR",
    ):
        monkeypatch.delenv(key, raising=False)
    assert checks.main() == 2
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "failed"
    assert "postgresql" not in output.out
    assert output.err == ""
