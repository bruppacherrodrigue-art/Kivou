from __future__ import annotations

import datetime as dt
import json

import sqlalchemy as sa
from feed_helpers import MATERIALIZED_AT
from test_discovery_initial_backfill import (
    _account_id,
    _activate,
    _grant_keys,
    _new_discovery_client,
    _persist_candidates,
)

from signals.billing.discovery_backfill import catch_up, main
from signals.billing.schema import discovery_signal_grant


def _legacy_zero_of_three(engine, *, email: str) -> str:
    _persist_candidates(engine, count=4)
    client = _new_discovery_client(engine, email=email)
    _activate(client)
    account_id = _account_id(client)
    with engine.begin() as connection:
        connection.execute(
            sa.delete(discovery_signal_grant).where(
                discovery_signal_grant.c.account_id == account_id
            )
        )
    assert _grant_keys(engine, account_id) == ()
    return account_id


def test_dry_run_reports_legacy_zero_of_three_without_mutating(migrated_sqlite_engine):
    account_id = _legacy_zero_of_three(
        migrated_sqlite_engine, email="legacy-dry-run@kivou.ch"
    )

    report = catch_up(
        migrated_sqlite_engine,
        as_of=MATERIALIZED_AT.date(),
        now=MATERIALIZED_AT + dt.timedelta(minutes=1),
        limit=50,
    )

    assert report.mode == "dry_run"
    assert report.accounts_reported == 1
    assert report.proposed_grants == 3
    assert report.applied_grants == 0
    assert report.accounts[0].account_id == account_id
    assert report.accounts[0].granted_before == 0
    assert report.accounts[0].scan_truncated is False
    assert len(report.accounts[0].proposed_signal_ids) == 3
    assert _grant_keys(migrated_sqlite_engine, account_id) == ()


def test_explicit_apply_is_rerunnable_and_never_exceeds_three(migrated_sqlite_engine):
    account_id = _legacy_zero_of_three(
        migrated_sqlite_engine, email="legacy-apply@kivou.ch"
    )

    first = catch_up(
        migrated_sqlite_engine,
        as_of=MATERIALIZED_AT.date(),
        now=MATERIALIZED_AT + dt.timedelta(minutes=1),
        limit=50,
        apply=True,
    )
    second = catch_up(
        migrated_sqlite_engine,
        as_of=MATERIALIZED_AT.date(),
        now=MATERIALIZED_AT + dt.timedelta(minutes=2),
        limit=50,
        apply=True,
    )

    assert first.applied_grants == 3
    assert second.applied_grants == 0
    assert second.accounts_reported == 0
    assert len(_grant_keys(migrated_sqlite_engine, account_id)) == 3


def test_command_defaults_to_json_dry_run_without_mutation(
    migrated_sqlite_engine, capsys
):
    account_id = _legacy_zero_of_three(
        migrated_sqlite_engine, email="legacy-command@kivou.ch"
    )

    exit_code = main(
        ["--limit", "50", "--as-of", MATERIALIZED_AT.date().isoformat()],
        engine_factory=lambda: migrated_sqlite_engine,
        clock=lambda: MATERIALIZED_AT + dt.timedelta(minutes=1),
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["mode"] == "dry_run"
    assert payload["proposed_grants"] == 3
    assert _grant_keys(migrated_sqlite_engine, account_id) == ()
