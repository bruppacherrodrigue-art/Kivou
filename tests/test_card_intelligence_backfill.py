from __future__ import annotations

import datetime as dt
import hashlib
import os
import threading
import uuid
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from feed_helpers import BOAMP_AGING, make_account, make_icp, materialize_boamp

from signals.accounts.schema import account
from signals.card_intelligence import backfill as backfill_module
from signals.card_intelligence.backfill import (
    MAX_BACKFILL_ITEMS,
    BackfillResult,
    backfill_factual_presentations,
)
from signals.card_intelligence.cli import main
from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.service import publish_factual_fallback
from signals.card_intelligence.store import (
    lock_publication_source,
    published_for_signals,
)
from signals.feed import policy as feed_policy
from signals.feed.query import feed_page as real_feed_page
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    card_presentation_artifact,
    contract_award,
    evidence,
    materialized_signal,
    source_event,
)

DAY = dt.date(2026, 8, 30)
NOW = dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC)


@dataclass(frozen=True)
class BackfillCase:
    account_id: str
    target_icp_id: str
    signal_keys: tuple[str, ...]


@pytest.fixture
def engine(tmp_path) -> sa.Engine:
    database = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'card-intelligence-backfill.db'}"
    )
    migrate_to_latest(database)
    return database


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_candidates(
    engine: sa.Engine,
    *,
    count: int,
    prefix: str,
) -> BackfillCase:
    """Clone persisted source rows so pagination is exercised by real SQL."""

    with engine.begin() as connection:
        account_id = make_account(
            connection,
            f"backfill-{prefix}@test.invalid",
            f"QA account metadata {prefix}",
        )
        target_icp_id = make_icp(connection, account_id, label=f"QA ICP {prefix}")
        template = materialize_boamp(
            connection,
            BOAMP_AGING,
            target_icp_id=target_icp_id,
        )
        signal_row = dict(
            connection.execute(
                sa.select(materialized_signal).where(
                    materialized_signal.c.signal_key == template.signal_key
                )
            ).mappings().one()
        )
        award_row = dict(
            connection.execute(
                sa.select(contract_award).where(
                    contract_award.c.award_key
                    == template.materialization_award_key
                )
            ).mappings().one()
        )
        event_row = dict(
            connection.execute(
                sa.select(source_event).where(
                    source_event.c.event_key == award_row["event_key"]
                )
            ).mappings().one()
        )
        evidence_row = dict(
            connection.execute(
                sa.select(evidence)
                .where(
                    evidence.c.award_key == award_row["award_key"],
                    evidence.c.anchors_kind == "award_fact",
                )
                .order_by(evidence.c.evidence_key)
                .limit(1)
            ).mappings().one()
        )
        connection.execute(
            sa.delete(materialized_signal).where(
                materialized_signal.c.signal_key == template.signal_key
            )
        )

        signal_keys: list[str] = []
        for index in range(count):
            namespace = f"{prefix}:{account_id}:{index:04d}"
            event_key = f"backfill:{_digest(namespace + ':event')[:48]}"
            award_key = _digest(namespace + ":award")
            evidence_key = _digest(namespace + ":evidence")
            signal_key = _digest(namespace + ":signal")
            opportunity_key = _digest(namespace + ":opportunity")
            signal_keys.append(signal_key)

            connection.execute(
                sa.insert(source_event).values(
                    **{
                        **event_row,
                        "event_key": event_key,
                        "source_notice_id": f"backfill-{prefix}-{index:04d}",
                    }
                )
            )
            connection.execute(
                sa.insert(contract_award).values(
                    **{
                        **award_row,
                        "award_key": award_key,
                        "event_key": event_key,
                        "source_award_id": f"backfill-award-{prefix}-{index:04d}",
                    }
                )
            )
            connection.execute(
                sa.insert(evidence).values(
                    **{
                        **evidence_row,
                        "evidence_key": evidence_key,
                        "award_key": award_key,
                        "source_notice_id": f"backfill-{prefix}-{index:04d}",
                    }
                )
            )
            connection.execute(
                sa.insert(materialized_signal).values(
                    **{
                        **signal_row,
                        "signal_key": signal_key,
                        "opportunity_key": opportunity_key,
                        "materialization_award_key": award_key,
                        "content_fingerprint": _digest(namespace + ":content"),
                    }
                )
            )

    return BackfillCase(
        account_id=account_id,
        target_icp_id=target_icp_id,
        signal_keys=tuple(sorted(signal_keys)),
    )


def _run(
    engine: sa.Engine,
    case: BackfillCase,
    *,
    language: str = "fr",
    limit: int = 50,
    offset: int = 0,
    now: dt.datetime = NOW,
) -> BackfillResult:
    return backfill_factual_presentations(
        engine,
        account_id=case.account_id,
        as_of=DAY,
        language=language,
        limit=limit,
        offset=offset,
        now=now,
    )


def _published_rows(engine: sa.Engine) -> list[sa.RowMapping]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                sa.select(card_presentation_artifact).where(
                    card_presentation_artifact.c.published_at.is_not(None)
                )
            ).mappings()
        )


def _publish_current(
    engine: sa.Engine,
    case: BackfillCase,
    *,
    language: str = "fr",
    now: dt.datetime = NOW,
) -> str:
    signal_key = case.signal_keys[0]
    with engine.begin() as connection:
        source = build_presentation_input(
            connection,
            account_id=case.account_id,
            signal_key=signal_key,
            language=language,
        )
        stored = publish_factual_fallback(connection, source=source, now=now)
    return str(stored["artifact_id"])


def test_backfill_processes_at_most_fifty_and_requires_explicit_offset_for_51st(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=51, prefix="page")

    first = _run(engine, case, limit=MAX_BACKFILL_ITEMS, offset=0)

    assert first == BackfillResult(
        scanned=50,
        published=50,
        unchanged=0,
        failed=0,
        next_offset=50,
        scan_truncated=False,
    )
    first_keys = {row["signal_key"] for row in _published_rows(engine)}
    assert first_keys == set(case.signal_keys[:50])
    assert case.signal_keys[50] not in first_keys

    second = _run(
        engine,
        case,
        limit=1,
        offset=50,
        now=NOW + dt.timedelta(minutes=1),
    )

    assert second.scanned == 1
    assert second.published == 1
    assert second.failed == 0
    assert second.next_offset is None
    assert {row["signal_key"] for row in _published_rows(engine)} == set(
        case.signal_keys
    )


def test_scan_cap_stops_without_silently_advancing_past_it(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _seed_candidates(engine, count=4, prefix="scan-cap")
    monkeypatch.setattr(feed_policy, "CANDIDATE_SCAN_CAP", 3)

    result = _run(engine, case, limit=1, offset=3)

    assert result == BackfillResult(
        scanned=0,
        published=0,
        unchanged=0,
        failed=0,
        next_offset=None,
        scan_truncated=True,
    )
    assert _published_rows(engine) == []


def test_each_failed_item_rolls_back_its_partial_work_and_preserves_the_page(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _seed_candidates(engine, count=3, prefix="savepoint")
    failed_key = case.signal_keys[0]
    original_publish = publish_factual_fallback

    def partially_write_then_fail(connection, *, source, now):
        if source.signal_key == failed_key:
            connection.execute(
                sa.update(materialized_signal)
                .where(materialized_signal.c.signal_key == failed_key)
                .values(winner_name="MUST ROLL BACK")
            )
            raise RuntimeError("injected per-item failure")
        return original_publish(connection, source=source, now=now)

    monkeypatch.setattr(
        backfill_module,
        "publish_factual_fallback",
        partially_write_then_fail,
    )

    result = _run(engine, case, limit=2)

    assert result.scanned == 2
    assert result.published == 1
    assert result.unchanged == 0
    assert result.failed == 1
    assert result.next_offset is None
    with engine.connect() as connection:
        failed_name = connection.scalar(
            sa.select(materialized_signal.c.winner_name).where(
                materialized_signal.c.signal_key == failed_key
            )
        )
    assert failed_name != "MUST ROLL BACK"
    assert {row["signal_key"] for row in _published_rows(engine)} == {
        case.signal_keys[1]
    }


def test_malformed_current_artifact_is_repaired_not_marked_unchanged(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=1, prefix="corrupt")
    old_artifact_id = _publish_current(engine, case)
    with engine.begin() as connection:
        connection.execute(
            sa.update(card_presentation_artifact)
            .where(card_presentation_artifact.c.artifact_id == old_artifact_id)
            .values(payload={"schema_version": "card-presentation-v1"})
        )

    result = _run(engine, case, limit=1, now=NOW + dt.timedelta(minutes=1))

    assert result.published == 1
    assert result.unchanged == 0
    assert result.failed == 0
    with engine.connect() as connection:
        rows = list(
            connection.execute(
                sa.select(card_presentation_artifact).where(
                    card_presentation_artifact.c.signal_key == case.signal_keys[0],
                    card_presentation_artifact.c.language == "fr",
                )
            ).mappings()
        )
        source = build_presentation_input(
            connection,
            account_id=case.account_id,
            signal_key=case.signal_keys[0],
            language="fr",
        )
        current = published_for_signals(
            connection,
            account_id=case.account_id,
            bindings={
                source.signal_key: (
                    source.signal_revision,
                    source.target_icp_revision,
                )
            },
            language="fr",
        ).get(source.signal_key)
    assert len(rows) == 2
    assert sum(row["superseded_at"] is None for row in rows) == 1
    assert current is not None
    assert current.artifact_id != old_artifact_id
    assert current.status == "FALLBACK"
    assert current.content.variant.value == "FACTUAL_FALLBACK"


def test_only_a_valid_current_factual_envelope_with_current_fingerprint_is_unchanged(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=1, prefix="unchanged")
    artifact_id = _publish_current(engine, case)

    result = _run(engine, case, limit=1, now=NOW + dt.timedelta(minutes=1))

    assert result.published == 0
    assert result.unchanged == 1
    assert result.failed == 0
    rows = _published_rows(engine)
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == artifact_id


def test_valid_old_envelope_with_stale_fingerprint_is_republished(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=1, prefix="stale-fingerprint")
    old_artifact_id = _publish_current(engine, case)
    with engine.begin() as connection:
        event_key = connection.scalar(
            sa.select(contract_award.c.event_key)
            .select_from(
                materialized_signal.join(
                    contract_award,
                    materialized_signal.c.materialization_award_key
                    == contract_award.c.award_key,
                )
            )
            .where(materialized_signal.c.signal_key == case.signal_keys[0])
        )
        buyers = connection.scalar(
            sa.select(source_event.c.procedure_buyers).where(
                source_event.c.event_key == event_key
            )
        )
        assert isinstance(buyers, list)
        connection.execute(
            sa.update(source_event)
            .where(source_event.c.event_key == event_key)
            .values(
                procedure_buyers=[
                    *buyers,
                    {"legal_name": "Acheteur public nouvellement publié"},
                ]
            )
        )

    result = _run(engine, case, limit=1, now=NOW + dt.timedelta(minutes=1))

    assert result.published == 1
    assert result.unchanged == 0
    assert result.failed == 0
    rows = _published_rows(engine)
    assert len(rows) == 2
    assert sum(row["superseded_at"] is None for row in rows) == 1
    assert next(row for row in rows if row["superseded_at"] is None)[
        "artifact_id"
    ] != old_artifact_id


def test_backfill_is_tenant_and_language_isolated(engine: sa.Engine) -> None:
    alice = _seed_candidates(engine, count=1, prefix="alice")
    bob = _seed_candidates(engine, count=1, prefix="bob")

    fr = _run(engine, alice, language="fr", limit=1)
    en = _run(
        engine,
        alice,
        language="en",
        limit=1,
        now=NOW + dt.timedelta(minutes=1),
    )

    assert fr.published == 1
    assert en.published == 1
    assert en.unchanged == 0
    rows = _published_rows(engine)
    assert {(row["account_id"], row["signal_key"], row["language"]) for row in rows} == {
        (alice.account_id, alice.signal_keys[0], "fr"),
        (alice.account_id, alice.signal_keys[0], "en"),
    }
    assert all(row["account_id"] != bob.account_id for row in rows)


def test_one_invocation_executes_exactly_one_explicit_page(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _seed_candidates(engine, count=4, prefix="one-page")
    page_calls: list[tuple[int, int, int]] = []
    events: list[tuple[str, object]] = []
    presentation_calls: list[set[str]] = []

    def recorded_feed_page(connection, **kwargs):
        page_calls.append((kwargs["offset"], kwargs["limit"], kwargs["scan_cap"]))
        return real_feed_page(connection, **kwargs)

    def recorded_lock(connection, *, source):
        events.append(("lock", source.signal_key))
        return lock_publication_source(connection, source=source)

    def recorded_presentations(connection, **kwargs):
        presentation_calls.append(set(kwargs["bindings"]))
        events.append(("batch", set(kwargs["bindings"])))
        return published_for_signals(connection, **kwargs)

    monkeypatch.setattr(backfill_module, "feed_page", recorded_feed_page)
    monkeypatch.setattr(
        backfill_module,
        "lock_publication_source",
        recorded_lock,
    )
    monkeypatch.setattr(
        backfill_module,
        "published_for_signals",
        recorded_presentations,
    )

    result = _run(engine, case, limit=2, offset=1)

    assert result.scanned == 2
    assert result.next_offset == 3
    assert page_calls == [(1, 2, feed_policy.CANDIDATE_SCAN_CAP)]
    assert presentation_calls == [set(case.signal_keys[1:3])]
    assert events == [
        *(("lock", signal_key) for signal_key in case.signal_keys[1:3]),
        ("batch", set(case.signal_keys[1:3])),
    ]
    assert len(_published_rows(engine)) == 2


def test_authority_lock_failure_is_item_scoped_and_stops_next_offset(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _seed_candidates(engine, count=3, prefix="lock-failure")
    failed_key = case.signal_keys[0]

    def partially_lock_then_fail(connection, *, source):
        if source.signal_key == failed_key:
            connection.execute(
                sa.update(materialized_signal)
                .where(materialized_signal.c.signal_key == failed_key)
                .values(winner_name="LOCK FAILURE MUST ROLL BACK")
            )
            event_key = connection.scalar(
                sa.select(contract_award.c.event_key)
                .select_from(
                    materialized_signal.join(
                        contract_award,
                        materialized_signal.c.materialization_award_key
                        == contract_award.c.award_key,
                    )
                )
                .where(materialized_signal.c.signal_key == failed_key)
            )
            buyers = connection.scalar(
                sa.select(source_event.c.procedure_buyers).where(
                    source_event.c.event_key == event_key
                )
            )
            assert isinstance(buyers, list)
            connection.execute(
                sa.update(source_event)
                .where(source_event.c.event_key == event_key)
                .values(
                    procedure_buyers=[
                        *buyers,
                        {"legal_name": "Concurrent source mutation"},
                    ]
                )
            )
        return lock_publication_source(connection, source=source)

    monkeypatch.setattr(
        backfill_module,
        "lock_publication_source",
        partially_lock_then_fail,
    )

    result = _run(engine, case, limit=2)

    assert result.scanned == 2
    assert result.published == 1
    assert result.unchanged == 0
    assert result.failed == 1
    assert result.next_offset is None
    with engine.connect() as connection:
        failed_name = connection.scalar(
            sa.select(materialized_signal.c.winner_name).where(
                materialized_signal.c.signal_key == failed_key
            )
        )
    assert failed_name != "LOCK FAILURE MUST ROLL BACK"
    assert {row["signal_key"] for row in _published_rows(engine)} == {
        case.signal_keys[1]
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"account_id": ""},
        {"account_id": " surrounded "},
        {"account_id": "qa/account"},
        {"as_of": "2026-08-30"},
        {"as_of": dt.datetime(2026, 8, 30, tzinfo=dt.UTC)},
        {"language": "de"},
        {"limit": 0},
        {"limit": 51},
        {"limit": True},
        {"offset": -1},
        {"offset": feed_policy.CANDIDATE_SCAN_CAP + 1},
        {"offset": False},
        {"now": NOW.replace(tzinfo=None)},
        {"now": "2026-08-30T10:00:00Z"},
    ],
)
def test_invalid_arguments_fail_before_any_database_access(overrides: dict) -> None:
    class NoDatabaseAccess:
        def begin(self):
            raise AssertionError("invalid input reached the database")

    arguments = {
        "account_id": "qa-account",
        "as_of": DAY,
        "language": "fr",
        "limit": 50,
        "offset": 0,
        "now": NOW,
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match="invalid backfill arguments"):
        backfill_factual_presentations(NoDatabaseAccess(), **arguments)


def test_cli_returns_nonzero_for_any_item_failure_and_prints_only_opaque_counts(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _seed_candidates(engine, count=2, prefix="cli-private-marker")
    failed_key = case.signal_keys[0]
    with engine.begin() as connection:
        event_key = connection.scalar(
            sa.select(contract_award.c.event_key)
            .select_from(
                materialized_signal.join(
                    contract_award,
                    materialized_signal.c.materialization_award_key
                    == contract_award.c.award_key,
                )
            )
            .where(materialized_signal.c.signal_key == failed_key)
        )
        connection.execute(
            sa.update(source_event)
            .where(source_event.c.event_key == event_key)
            .values(procedure_buyers={"private-source-fact": "must-not-print"})
        )
        connection.execute(
            sa.update(account)
            .where(account.c.account_id == case.account_id)
            .values(display_name="PRIVATE ACCOUNT METADATA")
        )
    monkeypatch.setenv(
        "KIVOU_DATABASE_URL",
        engine.url.render_as_string(hide_password=False),
    )

    exit_code = main(
        [
            "backfill-fallbacks",
            "--account-id",
            case.account_id,
            "--as-of",
            DAY.isoformat(),
            "--language",
            "fr",
            "--limit",
            "2",
            "--offset",
            "0",
        ],
        clock=lambda: NOW,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    assert captured.out == (
        "scanned=2 published=1 unchanged=0 failed=1 next_offset=none\n"
    )
    rendered = captured.out + captured.err
    for forbidden in (
        case.account_id,
        failed_key,
        "PRIVATE ACCOUNT METADATA",
        "private-source-fact",
        "KIVOU_DATABASE_URL",
        "provider",
        "model",
        "prompt",
        "Hermes",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "argv",
    [
        ["backfill-fallbacks", "--account-id", "qa-account"],
        [
            "backfill-fallbacks",
            "--account-id",
            "PRIVATE-ARGUMENT-" + "x" * 80,
            "--as-of",
            DAY.isoformat(),
            "--language",
            "fr",
            "--limit",
            "50",
            "--offset",
            "0",
        ],
        [
            "backfill-fallbacks",
            "--account-id",
            "qa-account",
            "--as-of",
            DAY.isoformat(),
            "--language",
            "de",
            "--limit",
            "50",
            "--offset",
            "0",
        ],
        [
            "backfill-fallbacks",
            "--account-id",
            "qa-account",
            "--as-of",
            DAY.isoformat(),
            "--language",
            "fr",
            "--limit",
            "51",
            "--offset",
            "0",
        ],
    ],
)
def test_cli_rejects_invalid_arguments_without_echoing_them(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(
            argv,
            engine_factory=lambda: (_ for _ in ()).throw(
                AssertionError("invalid CLI input reached engine creation")
            ),
            clock=lambda: NOW,
        )

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none\n"
    )
    assert "PRIVATE-ARGUMENT" not in captured.err


def test_cli_sanitizes_runtime_failure_and_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "postgresql://user:SECRET@db.invalid/kivou"

    exit_code = main(
        [
            "backfill-fallbacks",
            "--account-id",
            "qa-account",
            "--as-of",
            DAY.isoformat(),
            "--language",
            "en",
            "--limit",
            "1",
            "--offset",
            "0",
        ],
        engine_factory=lambda: (_ for _ in ()).throw(RuntimeError(secret)),
        clock=lambda: NOW,
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none\n"
    )
    assert secret not in captured.err
    assert "SECRET" not in captured.err


def test_cli_sanitizes_engine_disposal_failure_and_returns_nonzero(
    engine: sa.Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _seed_candidates(engine, count=1, prefix="dispose")
    secret = "postgresql://user:DISPOSE-SECRET@db.invalid/kivou"

    class FailingDisposeEngine:
        def begin(self):
            return engine.begin()

        def dispose(self) -> None:
            raise RuntimeError(secret)

    exit_code = main(
        [
            "backfill-fallbacks",
            "--account-id",
            case.account_id,
            "--as-of",
            DAY.isoformat(),
            "--language",
            "fr",
            "--limit",
            "1",
            "--offset",
            "0",
        ],
        engine_factory=FailingDisposeEngine,
        clock=lambda: NOW,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none\n"
    )
    assert secret not in captured.err
    assert "DISPOSE-SECRET" not in captured.err


def test_postgresql_concurrent_identical_backfills_publish_one_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = os.environ.get("KIVOU_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "KIVOU_TEST_POSTGRES_DSN is required for the backfill interleaving test"
        )

    postgres_engine = create_database_engine(dsn, pool_pre_ping=True)
    migrate_to_latest(postgres_engine)
    case = _seed_candidates(
        postgres_engine,
        count=1,
        prefix=f"concurrent-{uuid.uuid4().hex}",
    )
    start = threading.Barrier(3)
    after_batch_read = threading.Barrier(2)
    batch_calls: list[set[str]] = []
    results: list[BackfillResult] = []
    errors: list[BaseException] = []

    def synchronized_batch_reader(connection, **kwargs):
        current = published_for_signals(connection, **kwargs)
        batch_calls.append(set(kwargs["bindings"]))
        try:
            after_batch_read.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        return current

    monkeypatch.setattr(
        backfill_module,
        "published_for_signals",
        synchronized_batch_reader,
    )

    def run_backfill() -> None:
        try:
            start.wait(timeout=5)
            results.append(_run(postgres_engine, case, limit=1))
        except BaseException as error:  # noqa: BLE001 - asserted by the test thread
            errors.append(error)

    first = threading.Thread(target=run_backfill, daemon=True)
    second = threading.Thread(target=run_backfill, daemon=True)
    try:
        first.start()
        second.start()
        start.wait(timeout=5)
        first.join(timeout=20)
        second.join(timeout=20)

        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []
        assert len(results) == 2
        assert sorted(
            (result.published, result.unchanged, result.failed)
            for result in results
        ) == [(0, 1, 0), (1, 0, 0)]
        assert batch_calls == [
            {case.signal_keys[0]},
            {case.signal_keys[0]},
        ]
        with postgres_engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(
                        card_presentation_artifact.c.version,
                        card_presentation_artifact.c.superseded_at,
                    ).where(
                        card_presentation_artifact.c.account_id == case.account_id,
                        card_presentation_artifact.c.signal_key
                        == case.signal_keys[0],
                        card_presentation_artifact.c.language == "fr",
                    )
                ).mappings()
            )
        assert rows == [{"version": 1, "superseded_at": None}]
    finally:
        first.join(timeout=1)
        second.join(timeout=1)
        postgres_engine.dispose()
