from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from feed_helpers import BOAMP_AGING, make_account, make_icp, materialize_boamp
from sqlalchemy.dialects import postgresql

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
    opportunity_representation,
    source_event,
)

DAY = dt.date(2026, 8, 30)
NOW = dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC)


@dataclass(frozen=True)
class BackfillCase:
    account_id: str
    target_icp_id: str
    signal_keys: tuple[str, ...]


@dataclass(frozen=True)
class SameAccountPageCase:
    account_id: str
    target_icp_ids: tuple[str, str]
    signal_keys: tuple[str, str, str, str]


@pytest.fixture
def engine(tmp_path) -> sa.Engine:
    database = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'card-intelligence-backfill.db'}"
    )
    migrate_to_latest(database)
    return database


@contextmanager
def _isolated_postgres_engine() -> Iterator[sa.Engine]:
    """Migrate a private schema and always remove it from the shared test DB."""

    dsn = os.environ.get("KIVOU_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "KIVOU_TEST_POSTGRES_DSN is required for PostgreSQL interleaving tests"
        )

    schema = f"card_backfill_{uuid.uuid4().hex}"
    admin_engine = create_database_engine(dsn, pool_pre_ping=True)
    postgres_engine: sa.Engine | None = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(schema))
        postgres_engine = create_database_engine(
            dsn,
            pool_pre_ping=True,
            connect_args={
                "options": (
                    f"-c search_path={schema} "
                    "-c statement_timeout=10000 -c lock_timeout=8000"
                )
            },
        )
        migrate_to_latest(postgres_engine)
        with postgres_engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT current_schema()")) == schema
            assert connection.scalar(sa.text("SHOW statement_timeout")) == "10s"
            assert connection.scalar(sa.text("SHOW lock_timeout")) == "8s"
        yield postgres_engine
    finally:
        if postgres_engine is not None:
            postgres_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True, if_exists=True))
            assert connection.scalar(
                sa.text("SELECT to_regnamespace(:schema)"),
                {"schema": schema},
            ) is None
        admin_engine.dispose()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _artifact_digest(artifact_ids: list[str]) -> str:
    canonical = json.dumps(sorted(artifact_ids), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _candidate_digest(engine: sa.Engine, case: BackfillCase) -> str:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.revision,
                materialized_signal.c.target_icp_revision,
            ).where(materialized_signal.c.signal_key.in_(case.signal_keys))
        ).all()
    bindings = {
        row.signal_key: (row.revision, row.target_icp_revision)
        for row in rows
    }
    return backfill_module._candidate_binding_digest(bindings)


def _active_digest(
    engine: sa.Engine,
    case: BackfillCase,
    *,
    language: str = "fr",
) -> str:
    with engine.connect() as connection:
        artifact_ids = list(
            connection.execute(
                sa.select(card_presentation_artifact.c.artifact_id).where(
                    card_presentation_artifact.c.account_id == case.account_id,
                    card_presentation_artifact.c.language == language,
                    card_presentation_artifact.c.published_at.is_not(None),
                    card_presentation_artifact.c.superseded_at.is_(None),
                )
            ).scalars()
        )
    return _artifact_digest(artifact_ids)


def _precondition(
    *,
    candidates: int,
    active: int,
    digest: str,
    engine: sa.Engine | None = None,
    case: BackfillCase | None = None,
    language: str = "fr",
    candidate_digest: str | None = None,
    active_digest: str | None = None,
    protected_language: str | None = None,
    protected_active: int | None = None,
    protected_digest: str | None = None,
    protected_active_digest: str | None = None,
):
    if candidate_digest is None:
        candidate_digest = (
            _candidate_digest(engine, case)
            if engine is not None and case is not None
            else "0" * 64
        )
    if active_digest is None:
        active_digest = (
            _active_digest(engine, case, language=language)
            if engine is not None and case is not None
            else "0" * 64
        )
    return backfill_module.BackfillPrecondition(
        expected_candidate_count=candidates,
        expected_active_publication_count=active,
        expected_current_factual_artifact_digest=digest,
        expected_candidate_binding_digest=candidate_digest,
        expected_active_artifact_digest=active_digest,
        protected_language=protected_language,
        expected_protected_active_publication_count=protected_active,
        expected_protected_current_factual_artifact_digest=protected_digest,
        expected_protected_active_artifact_digest=protected_active_digest,
    )


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


def _seed_opposed_shared_awards(
    engine: sa.Engine,
) -> tuple[BackfillCase, BackfillCase]:
    """Give two tenants the same two awards in opposite signal-key order."""

    with engine.begin() as connection:
        account_ids = (
            make_account(connection, "deadlock-a@test.invalid", "Deadlock A"),
            make_account(connection, "deadlock-b@test.invalid", "Deadlock B"),
        )
        target_ids = tuple(
            make_icp(connection, account_id, label=f"Shared authority {index}")
            for index, account_id in enumerate(account_ids)
        )
        templates = tuple(
            materialize_boamp(
                connection,
                BOAMP_AGING,
                target_icp_id=target_icp_id,
            )
            for target_icp_id in target_ids
        )
        template_signals = tuple(
            dict(
                connection.execute(
                    sa.select(materialized_signal).where(
                        materialized_signal.c.signal_key == template.signal_key
                    )
                ).mappings().one()
            )
            for template in templates
        )
        first_award_key = templates[0].materialization_award_key
        assert all(
            template.materialization_award_key == first_award_key
            for template in templates
        )
        first_award = dict(
            connection.execute(
                sa.select(contract_award).where(
                    contract_award.c.award_key == first_award_key
                )
            ).mappings().one()
        )
        first_event = dict(
            connection.execute(
                sa.select(source_event).where(
                    source_event.c.event_key == first_award["event_key"]
                )
            ).mappings().one()
        )
        first_evidence = dict(
            connection.execute(
                sa.select(evidence)
                .where(
                    evidence.c.award_key == first_award_key,
                    evidence.c.anchors_kind == "award_fact",
                )
                .order_by(evidence.c.evidence_key)
                .limit(1)
            ).mappings().one()
        )

        second_event_key = "backfill:shared-event-b"
        second_award_key = _digest("backfill:shared-award-b")
        connection.execute(
            sa.insert(source_event).values(
                **{
                    **first_event,
                    "event_key": second_event_key,
                    "source_notice_id": "backfill-shared-b",
                }
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                **{
                    **first_award,
                    "award_key": second_award_key,
                    "event_key": second_event_key,
                    "source_award_id": "backfill-shared-award-b",
                }
            )
        )
        connection.execute(
            sa.insert(evidence).values(
                **{
                    **first_evidence,
                    "evidence_key": _digest("backfill:shared-evidence-b"),
                    "award_key": second_award_key,
                    "source_notice_id": "backfill-shared-b",
                }
            )
        )
        connection.execute(
            sa.delete(materialized_signal).where(
                materialized_signal.c.signal_key.in_(
                    tuple(template.signal_key for template in templates)
                )
            )
        )

        # signal-key order is award A -> B for tenant A, but B -> A for tenant B.
        assignments = (
            (("1" * 64, first_award_key), ("4" * 64, second_award_key)),
            (("2" * 64, second_award_key), ("3" * 64, first_award_key)),
        )
        opportunity_keys = {
            first_award_key: _digest("backfill:shared-opportunity-a"),
            second_award_key: _digest("backfill:shared-opportunity-b"),
        }
        for tenant_index, tenant_assignments in enumerate(assignments):
            for signal_key, award_key in tenant_assignments:
                connection.execute(
                    sa.insert(materialized_signal).values(
                        **{
                            **template_signals[tenant_index],
                            "signal_key": signal_key,
                            "opportunity_key": opportunity_keys[award_key],
                            "materialization_award_key": award_key,
                            "content_fingerprint": _digest(
                                f"backfill:{tenant_index}:{signal_key}:content"
                            ),
                        }
                    )
                )

    first_case = BackfillCase(
        account_id=account_ids[0],
        target_icp_id=target_ids[0],
        signal_keys=tuple(signal_key for signal_key, _ in assignments[0]),
    )
    second_case = BackfillCase(
        account_id=account_ids[1],
        target_icp_id=target_ids[1],
        signal_keys=tuple(signal_key for signal_key, _ in assignments[1]),
    )
    return first_case, second_case


def _seed_same_account_opposed_icp_pages(
    engine: sa.Engine,
) -> SameAccountPageCase:
    """Create two disjoint pages that lock the same ICPs in opposite order."""

    with engine.begin() as connection:
        account_id = make_account(
            connection,
            "deadlock-same-account@test.invalid",
            "Deadlock Same Account",
        )
        target_icp_ids = (
            make_icp(connection, account_id, label="Page Lock A"),
            make_icp(connection, account_id, label="Page Lock B"),
        )
        templates = tuple(
            materialize_boamp(
                connection,
                BOAMP_AGING,
                target_icp_id=target_icp_id,
            )
            for target_icp_id in target_icp_ids
        )
        template_signals = tuple(
            dict(
                connection.execute(
                    sa.select(materialized_signal).where(
                        materialized_signal.c.signal_key == template.signal_key
                    )
                ).mappings().one()
            )
            for template in templates
        )
        template_award = dict(
            connection.execute(
                sa.select(contract_award).where(
                    contract_award.c.award_key
                    == templates[0].materialization_award_key
                )
            ).mappings().one()
        )
        template_event = dict(
            connection.execute(
                sa.select(source_event).where(
                    source_event.c.event_key == template_award["event_key"]
                )
            ).mappings().one()
        )
        template_evidence = dict(
            connection.execute(
                sa.select(evidence)
                .where(
                    evidence.c.award_key == template_award["award_key"],
                    evidence.c.anchors_kind == "award_fact",
                )
                .order_by(evidence.c.evidence_key)
                .limit(1)
            ).mappings().one()
        )
        connection.execute(
            sa.delete(materialized_signal).where(
                materialized_signal.c.signal_key.in_(
                    tuple(template.signal_key for template in templates)
                )
            )
        )

        event_keys = tuple(
            sorted(
                (f"backfill:same-account-event-{index}" for index in range(4)),
                key=_digest,
            )
        )
        # Feed pages are (1, 2) and (3, 4). Event-binding order makes their
        # target lock orders A -> B and B -> A while every source row is disjoint.
        assignments = (
            ("1" * 64, 0, event_keys[0]),
            ("2" * 64, 1, event_keys[3]),
            ("3" * 64, 1, event_keys[1]),
            ("4" * 64, 0, event_keys[2]),
        )
        common_materialized_at = template_signals[0]["materialized_at"]
        for index, (signal_key, target_index, event_key) in enumerate(assignments):
            namespace = f"backfill:same-account:{index}"
            award_key = _digest(namespace + ":award")
            connection.execute(
                sa.insert(source_event).values(
                    **{
                        **template_event,
                        "event_key": event_key,
                        "source_notice_id": f"same-account-{index}",
                    }
                )
            )
            connection.execute(
                sa.insert(contract_award).values(
                    **{
                        **template_award,
                        "award_key": award_key,
                        "event_key": event_key,
                        "source_award_id": f"same-account-award-{index}",
                    }
                )
            )
            connection.execute(
                sa.insert(evidence).values(
                    **{
                        **template_evidence,
                        "evidence_key": _digest(namespace + ":evidence"),
                        "award_key": award_key,
                        "source_notice_id": f"same-account-{index}",
                    }
                )
            )
            connection.execute(
                sa.insert(materialized_signal).values(
                    **{
                        **template_signals[target_index],
                        "signal_key": signal_key,
                        "opportunity_key": _digest(namespace + ":opportunity"),
                        "materialization_award_key": award_key,
                        "content_fingerprint": _digest(namespace + ":content"),
                        "materialized_at": common_materialized_at,
                    }
                )
            )

    return SameAccountPageCase(
        account_id=account_id,
        target_icp_ids=target_icp_ids,
        signal_keys=tuple(assignment[0] for assignment in assignments),
    )


def _run(
    engine: sa.Engine,
    case: BackfillCase,
    *,
    language: str = "fr",
    limit: int = 50,
    offset: int = 0,
    now: dt.datetime = NOW,
    precondition=None,
) -> BackfillResult:
    return backfill_factual_presentations(
        engine,
        account_id=case.account_id,
        as_of=DAY,
        language=language,
        limit=limit,
        offset=offset,
        now=now,
        precondition=precondition,
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


def test_offline_candidate_bound_is_1000_while_get_bound_and_page_stay_capped() -> None:
    assert feed_policy.CANDIDATE_SCAN_CAP == 500
    assert getattr(backfill_module, "OFFLINE_CANDIDATE_SCAN_CAP", None) == 1000
    assert MAX_BACKFILL_ITEMS == 50


def test_guarded_backfill_rejects_candidate_drift_and_incomplete_page_before_publish(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=3, prefix="guard-candidate-drift")

    with pytest.raises(RuntimeError):
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([]),
                engine=engine,
                case=case,
            ),
        )

    assert _published_rows(engine) == []


def test_backend_precondition_requires_binding_and_active_artifact_digests() -> None:
    with pytest.raises(TypeError):
        backfill_module.BackfillPrecondition(
            expected_candidate_count=2,
            expected_active_publication_count=0,
            expected_current_factual_artifact_digest=_artifact_digest([]),
        )


def test_guarded_backfill_rejects_same_count_candidate_binding_drift(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=2, prefix="guard-binding-drift")
    sealed_candidate_digest = _candidate_digest(engine, case)
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == case.signal_keys[0])
            .values(
                revision=materialized_signal.c.revision + 1,
                content_fingerprint=_digest("guard-binding-drift:replacement"),
            )
        )
    assert _candidate_digest(engine, case) != sealed_candidate_digest

    with pytest.raises(RuntimeError):
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([]),
                candidate_digest=sealed_candidate_digest,
                active_digest=_artifact_digest([]),
            ),
        )

    assert _published_rows(engine) == []


def test_guarded_backfill_rejects_same_count_active_artifact_drift(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=2, prefix="guard-active-drift")
    current_artifact_id = _publish_current(engine, case)

    with pytest.raises(RuntimeError):
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=1,
                digest=_artifact_digest([current_artifact_id]),
                candidate_digest=_candidate_digest(engine, case),
                active_digest="0" * 64,
            ),
        )

    rows = _published_rows(engine)
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == current_artifact_id


def test_guarded_backfill_rejects_moved_baseline_digest_before_publish(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=2, prefix="guard-digest-drift")
    original_artifact_id = _publish_current(engine, case)

    with pytest.raises(RuntimeError):
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=1,
                digest="0" * 64,
                engine=engine,
                case=case,
            ),
        )

    rows = _published_rows(engine)
    assert [row["artifact_id"] for row in rows] == [original_artifact_id]


def test_guarded_backfill_rejects_extra_active_publication_before_publish(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=2, prefix="guard-active-drift")
    original_artifact_id = _publish_current(engine, case)

    with pytest.raises(RuntimeError):
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([original_artifact_id]),
                engine=engine,
                case=case,
            ),
        )

    rows = _published_rows(engine)
    assert [row["artifact_id"] for row in rows] == [original_artifact_id]


def test_guarded_backfill_accepts_exact_complete_page_and_digest(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=2, prefix="guard-exact")
    original_artifact_id = _publish_current(engine, case)

    result = _run(
        engine,
        case,
        limit=2,
        precondition=_precondition(
            candidates=2,
            active=1,
            digest=_artifact_digest([original_artifact_id]),
            engine=engine,
            case=case,
        ),
    )

    assert result == BackfillResult(
        scanned=2,
        published=1,
        unchanged=1,
        failed=0,
        next_offset=None,
        scan_truncated=False,
    )
    assert len(_published_rows(engine)) == 2


def test_guarded_protected_language_drift_aborts_before_target_publication(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=2, prefix="guard-protected-drift")
    assert _run(engine, case, language="fr", limit=2).published == 2
    fr_artifact_ids = [
        str(row["artifact_id"])
        for row in _published_rows(engine)
        if row["language"] == "fr"
    ]
    protected_digest = _artifact_digest(fr_artifact_ids)

    with engine.begin() as connection:
        connection.execute(
            sa.update(card_presentation_artifact)
            .where(
                card_presentation_artifact.c.artifact_id == fr_artifact_ids[0]
            )
            .values(superseded_at=NOW + dt.timedelta(seconds=1))
        )

    with pytest.raises(RuntimeError):
        _run(
            engine,
            case,
            language="en",
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([]),
                engine=engine,
                case=case,
                language="en",
                protected_language="fr",
                protected_active=2,
                protected_digest=protected_digest,
                protected_active_digest=protected_digest,
            ),
        )

    assert not [row for row in _published_rows(engine) if row["language"] == "en"]


@pytest.mark.parametrize(
    "protected",
    [
        {"protected_language": "fr"},
        {"protected_active": 2},
        {"protected_digest": "0" * 64},
        {"protected_active_digest": "0" * 64},
        {"protected_language": "de", "protected_active": 2, "protected_digest": "0" * 64},
        {"protected_language": "fr", "protected_active": 51, "protected_digest": "0" * 64},
    ],
)
def test_protected_precondition_is_all_or_none_and_validated(
    protected: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="invalid backfill arguments"):
        _precondition(
            candidates=2,
            active=0,
            digest=_artifact_digest([]),
            **protected,
        )


def test_protected_language_must_differ_from_published_language() -> None:
    class NoDatabaseAccess:
        def begin(self):
            raise AssertionError("invalid protected language reached database")

    with pytest.raises(ValueError, match="invalid backfill arguments"):
        backfill_factual_presentations(
            NoDatabaseAccess(),  # type: ignore[arg-type]
            account_id="qa-account",
            as_of=DAY,
            language="fr",
            limit=2,
            offset=0,
            now=NOW,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([]),
                protected_language="fr",
                protected_active=0,
                protected_digest=_artifact_digest([]),
                protected_active_digest=_artifact_digest([]),
            ),
        )


@pytest.mark.parametrize("failure_mode", ["exception", "incoherent"])
def test_guarded_publish_failure_rolls_back_every_publication_on_the_page(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    case = _seed_candidates(engine, count=2, prefix=f"guard-publish-{failure_mode}")
    original_publish = publish_factual_fallback
    calls = 0

    def fail_second_publish(connection, *, source, now):
        nonlocal calls
        calls += 1
        if calls == 2 and failure_mode == "exception":
            raise RuntimeError("PRIVATE-PUBLISH-FAILURE")
        stored = original_publish(connection, source=source, now=now)
        return {} if calls == 2 else stored

    monkeypatch.setattr(
        backfill_module,
        "publish_factual_fallback",
        fail_second_publish,
    )

    with pytest.raises(RuntimeError) as stopped:
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([]),
                engine=engine,
                case=case,
            ),
        )

    assert "PRIVATE" not in str(stopped.value)
    assert calls == 2
    assert _published_rows(engine) == []


@pytest.mark.parametrize(
    "drift",
    ["order", "count", "has_more", "scan_truncated", "same_key_field"],
)
def test_guarded_backfill_rereads_exact_page_after_authority_locks(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    case = _seed_candidates(engine, count=2, prefix=f"guard-reread-{drift}")
    calls = 0

    def drifting_feed_page(connection, **kwargs):
        nonlocal calls
        calls += 1
        page = real_feed_page(connection, **kwargs)
        if calls == 1:
            return page
        if drift == "order":
            return dataclasses.replace(page, items=tuple(reversed(page.items)))
        if drift == "count":
            return dataclasses.replace(page, items=page.items[:-1])
        if drift == "has_more":
            return dataclasses.replace(page, has_more=True)
        if drift == "scan_truncated":
            return dataclasses.replace(page, scan_truncated=True)
        changed = dataclasses.replace(
            page.items[0],
            target_icp_label="CONCURRENT-LABEL-DRIFT",
        )
        return dataclasses.replace(page, items=(changed, *page.items[1:]))

    monkeypatch.setattr(backfill_module, "feed_page", drifting_feed_page)

    with pytest.raises(RuntimeError):
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([]),
                engine=engine,
                case=case,
            ),
        )

    assert calls == 2
    assert _published_rows(engine) == []


def test_guarded_authority_table_locks_are_static_and_dialect_scoped() -> None:
    expected = (
        "LOCK TABLE target_icp IN SHARE MODE NOWAIT",
        "LOCK TABLE materialized_signal IN SHARE MODE NOWAIT",
        "LOCK TABLE contract_award IN SHARE MODE NOWAIT",
        "LOCK TABLE source_event IN SHARE MODE NOWAIT",
        "LOCK TABLE opportunity_representation IN SHARE MODE NOWAIT",
        "LOCK TABLE evidence IN SHARE MODE NOWAIT",
    )
    assert backfill_module._GUARDED_AUTHORITY_LOCK_SQL == expected
    assert backfill_module._GUARDED_ARTIFACT_LOCK_SQL == (
        "LOCK TABLE card_presentation_artifact IN SHARE ROW EXCLUSIVE MODE NOWAIT"
    )
    assert backfill_module._GUARDED_READ_COMMITTED_SQL == (
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
    )
    assert backfill_module._GUARDED_LOCK_TIMEOUT_SQL == (
        "SET LOCAL lock_timeout = '8s'"
    )
    assert all("{" not in statement and "%" not in statement for statement in expected)

    class RecordingConnection:
        def __init__(self, dialect_name: str) -> None:
            self.dialect = type("Dialect", (), {"name": dialect_name})()
            self.statements: list[str] = []

        def exec_driver_sql(self, statement: str) -> None:
            self.statements.append(statement)

    postgres = RecordingConnection("postgresql")
    sqlite = RecordingConnection("sqlite")
    backfill_module._prepare_guarded_transaction(postgres)
    backfill_module._lock_guarded_authorities(postgres)
    backfill_module._lock_guarded_artifact_table(postgres)
    backfill_module._prepare_guarded_transaction(sqlite)
    backfill_module._lock_guarded_authorities(sqlite)
    backfill_module._lock_guarded_artifact_table(sqlite)

    assert postgres.statements == [
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "SET LOCAL lock_timeout = '8s'",
        *expected,
        "LOCK TABLE card_presentation_artifact IN SHARE ROW EXCLUSIVE MODE NOWAIT",
    ]
    assert sqlite.statements == ["BEGIN"]

    guarded_account = backfill_module._owned_account_statement(
        "qa-account",
        guarded=True,
    )
    compiled = str(
        guarded_account.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "FOR KEY SHARE" in compiled


def test_guarded_table_lock_failure_is_opaque() -> None:
    class FailingConnection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def exec_driver_sql(self, _statement: str) -> None:
            raise RuntimeError("PRIVATE-LOCK-TIMEOUT-DETAIL")

    with pytest.raises(RuntimeError) as stopped:
        backfill_module._lock_guarded_authorities(FailingConnection())

    assert "PRIVATE" not in str(stopped.value)


@pytest.mark.parametrize("failure_stage", ["build", "lock"])
def test_guarded_build_or_lock_failure_aborts_without_any_publication(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    case = _seed_candidates(engine, count=2, prefix=f"guard-{failure_stage}")
    secret = f"PRIVATE-{failure_stage}-FAILURE"

    if failure_stage == "build":
        original = build_presentation_input
        calls = 0

        def fail_second_build(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError(secret)
            return original(*args, **kwargs)

        monkeypatch.setattr(
            backfill_module,
            "build_presentation_input",
            fail_second_build,
        )
    else:
        original = lock_publication_source
        calls = 0

        def fail_second_lock(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError(secret)
            return original(*args, **kwargs)

        monkeypatch.setattr(
            backfill_module,
            "lock_publication_source",
            fail_second_lock,
        )

    with pytest.raises(RuntimeError) as stopped:
        _run(
            engine,
            case,
            limit=2,
            precondition=_precondition(
                candidates=2,
                active=0,
                digest=_artifact_digest([]),
                engine=engine,
                case=case,
            ),
        )

    assert secret not in str(stopped.value)
    assert _published_rows(engine) == []


@pytest.mark.parametrize(
    "expectation_arguments",
    [
        ["--expect-candidate-count", "2"],
        ["--expect-active-publication-count", "0"],
        ["--expect-current-factual-artifact-digest", "0" * 64],
        ["--expect-candidate-binding-digest", "0" * 64],
        ["--expect-active-artifact-digest", "0" * 64],
        [
            "--expect-candidate-count",
            "2",
            "--expect-active-publication-count",
            "0",
        ],
        [
            "--expect-candidate-count",
            "2",
            "--expect-current-factual-artifact-digest",
            "0" * 64,
        ],
    ],
)
def test_cli_guard_expectations_are_all_or_none_and_opaque(
    expectation_arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = [
        "backfill-fallbacks",
        "--account-id",
        "qa-account",
        "--as-of",
        DAY.isoformat(),
        "--language",
        "fr",
        "--limit",
        "2",
        "--offset",
        "0",
    ]
    with pytest.raises(SystemExit) as stopped:
        main(
            [*base, *expectation_arguments],
            engine_factory=lambda: (_ for _ in ()).throw(
                AssertionError("partial guard reached engine creation")
            ),
            clock=lambda: NOW,
        )

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )
    assert "0" * 64 not in captured.err


def test_cli_complete_guard_is_parsed_and_runtime_failure_is_opaque(
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine_calls = 0

    def unavailable_engine() -> sa.Engine:
        nonlocal engine_calls
        engine_calls += 1
        raise RuntimeError("PRIVATE-GUARD-RUNTIME")

    exit_code = main(
        [
            "backfill-fallbacks",
            "--account-id",
            "qa-account",
            "--as-of",
            DAY.isoformat(),
            "--language",
            "fr",
            "--limit",
            "2",
            "--offset",
            "0",
            "--expect-candidate-count",
            "2",
            "--expect-active-publication-count",
            "0",
            "--expect-current-factual-artifact-digest",
            _artifact_digest([]),
            "--expect-candidate-binding-digest",
            "0" * 64,
            "--expect-active-artifact-digest",
            _artifact_digest([]),
        ],
        engine_factory=unavailable_engine,
        clock=lambda: NOW,
    )

    assert exit_code == 1
    assert engine_calls == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )
    assert "PRIVATE" not in captured.err


@pytest.mark.parametrize(
    "protected_arguments",
    [
        ["--expect-protected-language", "fr"],
        ["--expect-protected-active-publication-count", "2"],
        ["--expect-protected-current-factual-artifact-digest", "0" * 64],
        ["--expect-protected-active-artifact-digest", "0" * 64],
        [
            "--expect-protected-language",
            "fr",
            "--expect-protected-active-publication-count",
            "2",
        ],
    ],
)
def test_cli_protected_expectations_are_all_or_none_and_opaque(
    protected_arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "backfill-fallbacks",
                "--account-id",
                "qa-account",
                "--as-of",
                DAY.isoformat(),
                "--language",
                "en",
                "--limit",
                "2",
                "--offset",
                "0",
                "--expect-candidate-count",
                "2",
                "--expect-active-publication-count",
                "0",
                "--expect-current-factual-artifact-digest",
                _artifact_digest([]),
                "--expect-candidate-binding-digest",
                "0" * 64,
                "--expect-active-artifact-digest",
                _artifact_digest([]),
                *protected_arguments,
            ],
            engine_factory=lambda: (_ for _ in ()).throw(
                AssertionError("partial protected guard reached engine creation")
            ),
            clock=lambda: NOW,
        )

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )
    assert "0" * 64 not in captured.err


@pytest.mark.parametrize("protected_language", ["en", "de"])
def test_cli_protected_language_is_valid_and_different_before_engine_creation(
    protected_language: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "backfill-fallbacks",
                "--account-id",
                "qa-account",
                "--as-of",
                DAY.isoformat(),
                "--language",
                "en",
                "--limit",
                "2",
                "--offset",
                "0",
                "--expect-candidate-count",
                "2",
                "--expect-active-publication-count",
                "0",
                "--expect-current-factual-artifact-digest",
                _artifact_digest([]),
                "--expect-candidate-binding-digest",
                "0" * 64,
                "--expect-active-artifact-digest",
                _artifact_digest([]),
                "--expect-protected-language",
                protected_language,
                "--expect-protected-active-publication-count",
                "2",
                "--expect-protected-current-factual-artifact-digest",
                "0" * 64,
                "--expect-protected-active-artifact-digest",
                "0" * 64,
            ],
            engine_factory=lambda: (_ for _ in ()).throw(
                AssertionError("invalid protected guard reached engine creation")
            ),
            clock=lambda: NOW,
        )

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )


def test_cli_complete_protected_guard_reaches_runtime_opaquely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine_calls = 0

    def unavailable_engine() -> sa.Engine:
        nonlocal engine_calls
        engine_calls += 1
        raise RuntimeError("PRIVATE-PROTECTED-RUNTIME")

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
            "2",
            "--offset",
            "0",
            "--expect-candidate-count",
            "2",
            "--expect-active-publication-count",
            "0",
            "--expect-current-factual-artifact-digest",
            _artifact_digest([]),
            "--expect-candidate-binding-digest",
            "0" * 64,
            "--expect-active-artifact-digest",
            _artifact_digest([]),
            "--expect-protected-language",
            "fr",
            "--expect-protected-active-publication-count",
            "2",
            "--expect-protected-current-factual-artifact-digest",
            "0" * 64,
            "--expect-protected-active-artifact-digest",
            "0" * 64,
        ],
        engine_factory=unavailable_engine,
        clock=lambda: NOW,
    )

    assert exit_code == 1
    assert engine_calls == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )
    assert "PRIVATE" not in captured.err


@pytest.mark.parametrize(
    ("extra_arguments", "private_failure"),
    [
        (
            [
                "--expect-candidate-count",
                "3",
                "--expect-active-publication-count",
                "0",
                "--expect-current-factual-artifact-digest",
                "0" * 64,
            ],
            "candidate expectation exceeded limit",
        ),
        (
            [
                "--expect-candidate-count",
                "2",
                "--expect-active-publication-count",
                "51",
                "--expect-current-factual-artifact-digest",
                "0" * 64,
            ],
            "active expectation exceeded maximum",
        ),
    ],
)
def test_cli_guard_counts_are_bounded_before_engine_creation(
    extra_arguments: list[str],
    private_failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "backfill-fallbacks",
                "--account-id",
                "qa-account",
                "--as-of",
                DAY.isoformat(),
                "--language",
                "fr",
                "--limit",
                "2",
                "--offset",
                "0",
                *extra_arguments,
            ],
            engine_factory=lambda: (_ for _ in ()).throw(
                AssertionError(private_failure)
            ),
            clock=lambda: NOW,
        )

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )
    assert private_failure not in captured.err


def test_offline_backfill_can_reach_the_first_displayable_candidate_after_get_cap(
    engine: sa.Engine,
) -> None:
    case = _seed_candidates(engine, count=501, prefix="display-after-get-cap")
    identifier_only = "99999999999999"
    identifier_only_parties = [
        {
            "members": [
                {
                    "organization": {
                        "legal_name": identifier_only,
                        "identifiers": [
                            {"scheme": "SIRET", "value": identifier_only}
                        ],
                    }
                }
            ]
        }
    ]

    with engine.begin() as connection:
        ordered = connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.materialization_award_key,
            )
            .where(materialized_signal.c.target_icp_id == case.target_icp_id)
            .order_by(
                materialized_signal.c.materialized_at.desc(),
                materialized_signal.c.signal_key,
            )
        ).all()
        assert len(ordered) == 501
        assert tuple(row.signal_key for row in ordered) == case.signal_keys

        hidden = ordered[: feed_policy.CANDIDATE_SCAN_CAP]
        connection.execute(
            sa.update(materialized_signal)
            .where(
                materialized_signal.c.signal_key.in_(
                    [row.signal_key for row in hidden]
                )
            )
            .values(
                winner_name=identifier_only,
                winner_identifier_scheme="SIRET",
                winner_identifier_value=identifier_only,
            )
        )
        connection.execute(
            sa.update(contract_award)
            .where(
                contract_award.c.award_key.in_(
                    [row.materialization_award_key for row in hidden]
                )
            )
            .values(awardee_parties=identifier_only_parties)
        )

        get_page = real_feed_page(
            connection,
            account_id=case.account_id,
            as_of=DAY,
            freshness="all",
            limit=MAX_BACKFILL_ITEMS,
            offset=0,
        )

    assert feed_policy.CANDIDATE_SCAN_CAP == 500
    assert get_page.items == ()
    assert get_page.excluded_without_display_name == 500
    assert get_page.scan_truncated is True

    result = _run(engine, case, limit=MAX_BACKFILL_ITEMS, offset=0)

    assert result == BackfillResult(
        scanned=1,
        published=1,
        unchanged=0,
        failed=0,
        next_offset=None,
        scan_truncated=False,
    )
    published = _published_rows(engine)
    assert len(published) == 1
    assert published[0]["signal_key"] == ordered[500].signal_key
    assert result.published <= MAX_BACKFILL_ITEMS


def test_cli_offset_uses_the_offline_candidate_bound(
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine_calls = 0

    def unavailable_engine() -> sa.Engine:
        nonlocal engine_calls
        engine_calls += 1
        raise RuntimeError("opaque")

    accepted = main(
        [
            "backfill-fallbacks",
            "--account-id",
            "qa-account",
            "--as-of",
            DAY.isoformat(),
            "--language",
            "fr",
            "--limit",
            "50",
            "--offset",
            "1000",
        ],
        engine_factory=unavailable_engine,
        clock=lambda: NOW,
    )

    assert accepted == 1
    assert engine_calls == 1
    accepted_output = capsys.readouterr()
    assert accepted_output.out == ""
    assert accepted_output.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )

    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "backfill-fallbacks",
                "--account-id",
                "qa-account",
                "--as-of",
                DAY.isoformat(),
                "--language",
                "fr",
                "--limit",
                "50",
                "--offset",
                "1001",
            ],
            engine_factory=lambda: (_ for _ in ()).throw(
                AssertionError("invalid offset reached engine creation")
            ),
            clock=lambda: NOW,
        )
    assert stopped.value.code == 2
    rejected_output = capsys.readouterr()
    assert rejected_output.out == ""
    assert rejected_output.err == (
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )


def test_scan_cap_stops_without_silently_advancing_past_it(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _seed_candidates(engine, count=4, prefix="scan-cap")
    monkeypatch.setattr(backfill_module, "OFFLINE_CANDIDATE_SCAN_CAP", 3)

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


def test_cli_truncated_nonempty_page_stops_before_build_and_publication(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert feed_policy.CANDIDATE_SCAN_CAP == 500
    assert getattr(backfill_module, "OFFLINE_CANDIDATE_SCAN_CAP", None) == 1000
    offline_cap = backfill_module.OFFLINE_CANDIDATE_SCAN_CAP
    case = _seed_candidates(
        engine,
        count=offline_cap + 1,
        prefix="cli-real-scan-cap",
    )
    build_calls = 0
    original_build = build_presentation_input

    def recorded_build(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return original_build(*args, **kwargs)

    monkeypatch.setattr(backfill_module, "build_presentation_input", recorded_build)
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
            "50",
            "--offset",
            "0",
        ],
        clock=lambda: NOW,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    assert captured.out == (
        "scanned=50 published=0 unchanged=0 failed=0 next_offset=none "
        "scan_truncated=1\n"
    )
    assert build_calls == 0
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


def test_incoherent_service_result_rolls_back_the_written_artifact(
    engine: sa.Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _seed_candidates(engine, count=1, prefix="incoherent-result")

    def publish_then_hide_result(connection, *, source, now):
        publish_factual_fallback(connection, source=source, now=now)
        return {}

    monkeypatch.setattr(
        backfill_module,
        "publish_factual_fallback",
        publish_then_hide_result,
    )

    result = _run(engine, case, limit=1)

    assert result == BackfillResult(
        scanned=1,
        published=0,
        unchanged=0,
        failed=1,
        next_offset=None,
        scan_truncated=False,
    )
    assert _published_rows(engine) == []


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
    account_transaction_lock = backfill_module._lock_account_backfill_transaction

    def recorded_feed_page(connection, **kwargs):
        events.append(("page", kwargs["account_id"]))
        page_calls.append((kwargs["offset"], kwargs["limit"], kwargs["scan_cap"]))
        return real_feed_page(connection, **kwargs)

    def recorded_account_lock(connection, *, account_id):
        events.append(("account_lock", account_id))
        return account_transaction_lock(connection, account_id=account_id)

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
        "_lock_account_backfill_transaction",
        recorded_account_lock,
    )
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
    assert page_calls == [(1, 2, 1000)]
    assert presentation_calls == [set(case.signal_keys[1:3])]
    assert [event for event, _ in events] == [
        "account_lock",
        "page",
        "lock",
        "lock",
        "batch",
    ]
    assert events[:2] == [
        ("account_lock", case.account_id),
        ("page", case.account_id),
    ]
    assert {value for event, value in events if event == "lock"} == set(
        case.signal_keys[1:3]
    )
    assert events[-1] == ("batch", set(case.signal_keys[1:3]))
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
        {"offset": backfill_module.OFFLINE_CANDIDATE_SCAN_CAP + 1},
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
        "scanned=2 published=1 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
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
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
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
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
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
        "scanned=0 published=0 unchanged=0 failed=1 next_offset=none "
        "scan_truncated=0\n"
    )
    assert secret not in captured.err
    assert "DISPOSE-SECRET" not in captured.err


def test_postgresql_recovery_reconciles_49_with_8_active_and_2_revision_stale(
) -> None:
    with _isolated_postgres_engine() as postgres_engine:
        case = _seed_candidates(
            postgres_engine,
            count=49,
            prefix="recovery-49-8-6",
        )
        original_by_key: dict[str, str] = {}
        with postgres_engine.begin() as connection:
            for signal_key in case.signal_keys[:8]:
                source = build_presentation_input(
                    connection,
                    account_id=case.account_id,
                    signal_key=signal_key,
                    language="fr",
                )
                stored = publish_factual_fallback(
                    connection,
                    source=source,
                    now=NOW,
                )
                original_by_key[signal_key] = str(stored["artifact_id"])

        stale_keys = case.signal_keys[:2]
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.update(materialized_signal)
                .where(materialized_signal.c.signal_key.in_(stale_keys))
                .values(
                    revision=materialized_signal.c.revision + 1,
                    content_fingerprint=_digest("recovery-49-8-6:revised"),
                )
            )

        with postgres_engine.connect() as connection:
            binding_rows = connection.execute(
                sa.select(
                    materialized_signal.c.signal_key,
                    materialized_signal.c.revision,
                    materialized_signal.c.target_icp_revision,
                ).where(materialized_signal.c.signal_key.in_(case.signal_keys))
            ).all()
            bindings = {
                row.signal_key: (row.revision, row.target_icp_revision)
                for row in binding_rows
            }
            current_before = published_for_signals(
                connection,
                account_id=case.account_id,
                bindings=bindings,
                language="fr",
            )
        current_before_ids = [
            presentation.artifact_id for presentation in current_before.values()
        ]
        original_ids = list(original_by_key.values())
        assert len(bindings) == 49
        assert len(current_before_ids) == 6

        result = _run(
            postgres_engine,
            case,
            limit=49,
            now=NOW + dt.timedelta(minutes=1),
            precondition=_precondition(
                candidates=49,
                active=8,
                digest=_artifact_digest(current_before_ids),
                candidate_digest=backfill_module._candidate_binding_digest(bindings),
                active_digest=_artifact_digest(original_ids),
            ),
        )

        assert result == BackfillResult(
            scanned=49,
            published=43,
            unchanged=6,
            failed=0,
            next_offset=None,
            scan_truncated=False,
        )
        rows = [
            row
            for row in _published_rows(postgres_engine)
            if row["account_id"] == case.account_id and row["language"] == "fr"
        ]
        active_rows = [row for row in rows if row["superseded_at"] is None]
        row_by_artifact = {str(row["artifact_id"]): row for row in rows}
        assert len(rows) == 51
        assert len(active_rows) == 49
        assert all(row["qa_status"] == "FALLBACK" for row in rows)
        assert all(row["payload_variant"] == "FACTUAL_FALLBACK" for row in rows)
        assert all(
            row[field] is None
            for row in rows
            for field in (
                "provider",
                "model_id",
                "prompt_version",
                "qa_provider",
                "qa_model_id",
            )
        )
        assert all(
            row_by_artifact[original_by_key[signal_key]]["superseded_at"]
            is not None
            for signal_key in stale_keys
        )
        assert all(
            row_by_artifact[original_by_key[signal_key]]["superseded_at"] is None
            for signal_key in case.signal_keys[2:8]
        )


def test_postgresql_concurrent_identical_backfills_publish_one_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_postgres_engine() as postgres_engine:
        case = _seed_candidates(
            postgres_engine,
            count=1,
            prefix="concurrent-identical",
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
                after_batch_read.wait(timeout=2)
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
                start.wait(timeout=3)
                results.append(_run(postgres_engine, case, limit=1))
            except BaseException as error:  # noqa: BLE001 - asserted by test thread
                errors.append(error)

        first = threading.Thread(target=run_backfill, daemon=True)
        second = threading.Thread(target=run_backfill, daemon=True)
        try:
            first.start()
            second.start()
            start.wait(timeout=3)
            first.join(timeout=15)
            second.join(timeout=15)

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


def test_postgresql_guarded_share_locks_allow_same_transaction_publication() -> None:
    with _isolated_postgres_engine() as postgres_engine:
        case = _seed_candidates(
            postgres_engine,
            count=1,
            prefix="guarded-share-write",
        )

        result = _run(
            postgres_engine,
            case,
            limit=1,
            precondition=_precondition(
                candidates=1,
                active=0,
                digest=_artifact_digest([]),
                engine=postgres_engine,
                case=case,
            ),
        )

        assert result == BackfillResult(
            scanned=1,
            published=1,
            unchanged=0,
            failed=0,
            next_offset=None,
            scan_truncated=False,
        )
        assert len(_published_rows(postgres_engine)) == 1


def test_postgresql_guarded_reread_rejects_candidate_committed_after_first_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_postgres_engine() as postgres_engine:
        case = _seed_candidates(
            postgres_engine,
            count=2,
            prefix="guarded-candidate-race",
        )
        hidden_signal_key = case.signal_keys[1]
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.update(materialized_signal)
                .where(materialized_signal.c.signal_key == hidden_signal_key)
                .values(invalidated_at=NOW)
            )
        visible_case = dataclasses.replace(
            case,
            signal_keys=(case.signal_keys[0],),
        )

        first_read_done = threading.Event()
        candidate_committed = threading.Event()
        feed_calls = 0
        errors: list[BaseException] = []

        def synchronized_feed_page(connection, **kwargs):
            nonlocal feed_calls
            feed_calls += 1
            page = real_feed_page(connection, **kwargs)
            if feed_calls == 1:
                first_read_done.set()
                assert candidate_committed.wait(timeout=10)
            return page

        monkeypatch.setattr(backfill_module, "feed_page", synchronized_feed_page)

        def reveal_candidate() -> None:
            try:
                assert first_read_done.wait(timeout=10)
                with postgres_engine.begin() as connection:
                    connection.execute(
                        sa.update(materialized_signal)
                        .where(materialized_signal.c.signal_key == hidden_signal_key)
                        .values(invalidated_at=None)
                    )
            except BaseException as error:  # noqa: BLE001 - asserted below
                errors.append(error)
            finally:
                candidate_committed.set()

        writer = threading.Thread(target=reveal_candidate, daemon=True)
        writer.start()
        try:
            with pytest.raises(RuntimeError):
                _run(
                    postgres_engine,
                    case,
                    limit=1,
                    precondition=_precondition(
                        candidates=1,
                        active=0,
                        digest=_artifact_digest([]),
                        engine=postgres_engine,
                        case=visible_case,
                    ),
                )
            writer.join(timeout=15)

            assert not writer.is_alive()
            assert errors == []
            assert feed_calls == 2
            assert _published_rows(postgres_engine) == []
        finally:
            writer.join(timeout=1)


def test_postgresql_guarded_authority_nowait_never_sacrifices_materializer() -> None:
    with _isolated_postgres_engine() as postgres_engine:
        case = _seed_candidates(
            postgres_engine,
            count=1,
            prefix="guarded-nowait-materializer",
        )
        with postgres_engine.connect() as connection:
            signal_row = dict(
                connection.execute(
                    sa.select(materialized_signal).where(
                        materialized_signal.c.signal_key == case.signal_keys[0]
                    )
                ).mappings().one()
            )
            award_row = dict(
                connection.execute(
                    sa.select(contract_award).where(
                        contract_award.c.award_key
                        == signal_row["materialization_award_key"]
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
                    .where(evidence.c.award_key == award_row["award_key"])
                    .order_by(evidence.c.evidence_key)
                    .limit(1)
                ).mappings().one()
            )

        namespace = "guarded-nowait-materializer:new"
        event_key = f"backfill:{_digest(namespace + ':event')[:48]}"
        award_key = _digest(namespace + ":award")
        opportunity_key = _digest(namespace + ":opportunity")
        signal_key = _digest(namespace + ":signal")
        writer_holds_award = threading.Event()
        backfill_holds_materialized = threading.Event()
        writer_committed = threading.Event()
        writer_errors: list[BaseException] = []
        writer_sqlstates: list[str | None] = []
        backfill_errors: list[BaseException] = []

        def observe_table_lock(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if statement in (
                "LOCK TABLE materialized_signal IN SHARE MODE",
                "LOCK TABLE materialized_signal IN SHARE MODE NOWAIT",
            ):
                backfill_holds_materialized.set()

        sa.event.listen(
            postgres_engine,
            "after_cursor_execute",
            observe_table_lock,
        )

        def materialize_candidate() -> None:
            try:
                with postgres_engine.begin() as connection:
                    connection.execute(
                        sa.insert(source_event).values(
                            **{
                                **event_row,
                                "event_key": event_key,
                                "source_notice_id": "guarded-nowait-materializer",
                            }
                        )
                    )
                    connection.execute(
                        sa.insert(contract_award).values(
                            **{
                                **award_row,
                                "award_key": award_key,
                                "event_key": event_key,
                                "source_award_id": "guarded-nowait-materializer",
                            }
                        )
                    )
                    writer_holds_award.set()
                    assert backfill_holds_materialized.wait(timeout=10)
                    connection.execute(
                        sa.insert(opportunity_representation).values(
                            award_key=award_key,
                            opportunity_key=opportunity_key,
                            created_at=signal_row["created_at"],
                        )
                    )
                    connection.execute(
                        sa.insert(evidence).values(
                            **{
                                **evidence_row,
                                "evidence_key": _digest(namespace + ":evidence"),
                                "award_key": award_key,
                                "source_notice_id": "guarded-nowait-materializer",
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
                                "content_fingerprint": _digest(
                                    namespace + ":content"
                                ),
                            }
                        )
                    )
                writer_committed.set()
            except BaseException as error:  # noqa: BLE001 - asserted below
                writer_errors.append(error)
                if isinstance(error, sa.exc.DBAPIError):
                    writer_sqlstates.append(getattr(error.orig, "sqlstate", None))

        def run_guarded() -> None:
            try:
                assert writer_holds_award.wait(timeout=10)
                _run(
                    postgres_engine,
                    case,
                    limit=1,
                    precondition=_precondition(
                        candidates=1,
                        active=0,
                        digest=_artifact_digest([]),
                        engine=postgres_engine,
                        case=case,
                    ),
                )
            except BaseException as error:  # noqa: BLE001 - asserted below
                backfill_errors.append(error)

        writer = threading.Thread(target=materialize_candidate, daemon=True)
        guarded = threading.Thread(target=run_guarded, daemon=True)
        try:
            writer.start()
            guarded.start()
            writer.join(timeout=15)
            guarded.join(timeout=15)

            assert not writer.is_alive()
            assert not guarded.is_alive()
            assert writer_committed.is_set(), (
                writer_errors,
                writer_sqlstates,
                backfill_errors,
            )
            assert writer_errors == []
            assert "40P01" not in writer_sqlstates
            assert len(backfill_errors) == 1
            assert isinstance(backfill_errors[0], RuntimeError)
            assert str(backfill_errors[0]) == ""
            assert _published_rows(postgres_engine) == []
            with postgres_engine.connect() as connection:
                assert connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(materialized_signal)
                    .where(materialized_signal.c.signal_key == signal_key)
                ) == 1
        finally:
            sa.event.remove(
                postgres_engine,
                "after_cursor_execute",
                observe_table_lock,
            )
            writer.join(timeout=1)
            guarded.join(timeout=1)


def test_postgresql_two_guarded_accounts_nowait_without_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_postgres_engine() as postgres_engine:
        first_case = _seed_candidates(
            postgres_engine,
            count=1,
            prefix="guarded-distinct-first",
        )
        second_case = _seed_candidates(
            postgres_engine,
            count=1,
            prefix="guarded-distinct-second",
        )
        start = threading.Barrier(3)
        at_artifact_lock = threading.Barrier(2)
        results: list[BackfillResult] = []
        errors: list[BaseException] = []
        original_artifact_lock = backfill_module._lock_guarded_artifact_table

        def synchronized_artifact_lock(connection) -> None:
            at_artifact_lock.wait(timeout=10)
            original_artifact_lock(connection)

        monkeypatch.setattr(
            backfill_module,
            "_lock_guarded_artifact_table",
            synchronized_artifact_lock,
        )

        def run_guarded(case: BackfillCase) -> None:
            try:
                start.wait(timeout=5)
                results.append(
                    _run(
                        postgres_engine,
                        case,
                        limit=1,
                        precondition=_precondition(
                            candidates=1,
                            active=0,
                            digest=_artifact_digest([]),
                            engine=postgres_engine,
                            case=case,
                        ),
                    )
                )
            except BaseException as error:  # noqa: BLE001 - asserted below
                errors.append(error)

        first = threading.Thread(target=run_guarded, args=(first_case,), daemon=True)
        second = threading.Thread(target=run_guarded, args=(second_case,), daemon=True)
        try:
            first.start()
            second.start()
            start.wait(timeout=5)
            first.join(timeout=20)
            second.join(timeout=20)

            assert not first.is_alive()
            assert not second.is_alive()
            assert len(errors) == 1
            assert isinstance(errors[0], RuntimeError)
            assert str(errors[0]) == ""
            assert results == [BackfillResult(1, 1, 0, 0, None, False)]
            assert len(_published_rows(postgres_engine)) == 1
        finally:
            first.join(timeout=1)
            second.join(timeout=1)


def test_postgresql_guarded_backfill_sees_ordinary_publication_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_postgres_engine() as postgres_engine:
        case = _seed_candidates(
            postgres_engine,
            count=1,
            prefix="ordinary-versus-guarded",
        )
        ordinary_written = threading.Event()
        allow_ordinary_commit = threading.Event()
        ordinary_committed = threading.Event()
        guarded_reached_source_lock = threading.Event()
        allow_guarded_source_lock = threading.Event()
        ordinary_errors: list[BaseException] = []
        guarded_errors: list[BaseException] = []
        original_lock = lock_publication_source

        def publish_ordinary() -> None:
            try:
                with postgres_engine.begin() as connection:
                    source = build_presentation_input(
                        connection,
                        account_id=case.account_id,
                        signal_key=case.signal_keys[0],
                        language="fr",
                    )
                    publish_factual_fallback(connection, source=source, now=NOW)
                    ordinary_written.set()
                    assert allow_ordinary_commit.wait(timeout=10)
                ordinary_committed.set()
            except BaseException as error:  # noqa: BLE001 - asserted below
                ordinary_errors.append(error)

        def synchronized_guarded_lock(connection, *, source):
            guarded_reached_source_lock.set()
            assert allow_guarded_source_lock.wait(timeout=10)
            return original_lock(connection, source=source)

        monkeypatch.setattr(
            backfill_module,
            "lock_publication_source",
            synchronized_guarded_lock,
        )

        def run_guarded() -> None:
            try:
                _run(
                    postgres_engine,
                    case,
                    limit=1,
                    precondition=_precondition(
                        candidates=1,
                        active=0,
                        digest=_artifact_digest([]),
                        engine=postgres_engine,
                        case=case,
                    ),
                )
            except BaseException as error:  # noqa: BLE001 - asserted below
                guarded_errors.append(error)

        ordinary = threading.Thread(target=publish_ordinary, daemon=True)
        guarded = threading.Thread(target=run_guarded, daemon=True)
        try:
            ordinary.start()
            assert ordinary_written.wait(timeout=10)
            guarded.start()
            assert guarded_reached_source_lock.wait(timeout=10)
            allow_ordinary_commit.set()
            assert ordinary_committed.wait(timeout=10)
            allow_guarded_source_lock.set()
            ordinary.join(timeout=15)
            guarded.join(timeout=15)

            assert not ordinary.is_alive()
            assert not guarded.is_alive()
            assert ordinary_errors == []
            assert len(guarded_errors) == 1
            assert isinstance(guarded_errors[0], RuntimeError)
            assert str(guarded_errors[0]) == ""
            rows = _published_rows(postgres_engine)
            assert len(rows) == 1
            assert rows[0]["signal_key"] == case.signal_keys[0]
        finally:
            allow_ordinary_commit.set()
            allow_guarded_source_lock.set()
            ordinary.join(timeout=1)
            guarded.join(timeout=1)


def test_postgresql_shared_authorities_use_one_global_lock_order_without_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_postgres_engine() as postgres_engine:
        first_case, second_case = _seed_opposed_shared_awards(postgres_engine)
        start = threading.Barrier(3)
        after_first_lock = threading.Barrier(2)
        thread_state = threading.local()
        batch_calls: list[set[str]] = []
        lock_sqlstates: list[str | None] = []
        results: dict[str, BackfillResult] = {}
        errors: list[BaseException] = []

        def synchronized_lock(connection, *, source):
            try:
                locked = lock_publication_source(connection, source=source)
            except sa.exc.DBAPIError as error:
                lock_sqlstates.append(getattr(error.orig, "sqlstate", None))
                raise
            if not getattr(thread_state, "first_authority_locked", False):
                thread_state.first_authority_locked = True
                try:
                    after_first_lock.wait(timeout=2)
                except threading.BrokenBarrierError:
                    pass
            return locked

        def recorded_presentations(connection, **kwargs):
            batch_calls.append(set(kwargs["bindings"]))
            return published_for_signals(connection, **kwargs)

        monkeypatch.setattr(
            backfill_module,
            "lock_publication_source",
            synchronized_lock,
        )
        monkeypatch.setattr(
            backfill_module,
            "published_for_signals",
            recorded_presentations,
        )

        def run_backfill(case: BackfillCase) -> None:
            try:
                start.wait(timeout=3)
                results[case.account_id] = _run(postgres_engine, case, limit=2)
            except BaseException as error:  # noqa: BLE001 - asserted by test thread
                errors.append(error)

        first = threading.Thread(target=run_backfill, args=(first_case,), daemon=True)
        second = threading.Thread(target=run_backfill, args=(second_case,), daemon=True)
        try:
            first.start()
            second.start()
            start.wait(timeout=3)
            first.join(timeout=15)
            second.join(timeout=15)

            assert not first.is_alive()
            assert not second.is_alive()
            assert errors == []
            assert "40P01" not in lock_sqlstates
            assert results == {
                first_case.account_id: BackfillResult(
                    scanned=2,
                    published=2,
                    unchanged=0,
                    failed=0,
                    next_offset=None,
                    scan_truncated=False,
                ),
                second_case.account_id: BackfillResult(
                    scanned=2,
                    published=2,
                    unchanged=0,
                    failed=0,
                    next_offset=None,
                    scan_truncated=False,
                ),
            }
            assert len(batch_calls) == 2
            assert {frozenset(call) for call in batch_calls} == {
                frozenset(first_case.signal_keys),
                frozenset(second_case.signal_keys),
            }
            with postgres_engine.connect() as connection:
                rows = list(
                    connection.execute(
                        sa.select(
                            card_presentation_artifact.c.account_id,
                            card_presentation_artifact.c.signal_key,
                            card_presentation_artifact.c.version,
                            card_presentation_artifact.c.superseded_at,
                        )
                    ).mappings()
                )
            assert len(rows) == 4
            assert all(row["version"] == 1 for row in rows)
            assert all(row["superseded_at"] is None for row in rows)
        finally:
            first.join(timeout=1)
            second.join(timeout=1)


def test_postgresql_same_account_pages_are_serialized_before_icp_row_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_postgres_engine() as postgres_engine:
        case = _seed_same_account_opposed_icp_pages(postgres_engine)
        with postgres_engine.connect() as connection:
            page_sources = tuple(
                tuple(
                    build_presentation_input(
                        connection,
                        account_id=case.account_id,
                        signal_key=signal_key,
                        language="fr",
                    )
                    for signal_key in page
                )
                for page in (case.signal_keys[:2], case.signal_keys[2:])
            )
        first_authorities = {
            (
                source.facts.source_event_binding,
                source.facts.source_award_binding,
            )
            for source in page_sources[0]
        }
        second_authorities = {
            (
                source.facts.source_event_binding,
                source.facts.source_award_binding,
            )
            for source in page_sources[1]
        }
        assert first_authorities.isdisjoint(second_authorities)
        assert {event for event, _ in first_authorities}.isdisjoint(
            {event for event, _ in second_authorities}
        )
        assert {award for _, award in first_authorities}.isdisjoint(
            {award for _, award in second_authorities}
        )
        assert [
            source.target_icp_id
            for source in sorted(
                page_sources[0],
                key=backfill_module._publication_lock_order,
            )
        ] == list(case.target_icp_ids)
        assert [
            source.target_icp_id
            for source in sorted(
                page_sources[1],
                key=backfill_module._publication_lock_order,
            )
        ] == list(reversed(case.target_icp_ids))

        start = threading.Barrier(3)
        after_first_authority = threading.Barrier(2)
        thread_state = threading.local()
        batch_calls: list[set[str]] = []
        lock_sqlstates: list[str | None] = []
        results: dict[int, BackfillResult] = {}
        errors: list[BaseException] = []

        def synchronized_lock(connection, *, source):
            try:
                locked = lock_publication_source(connection, source=source)
            except sa.exc.DBAPIError as error:
                lock_sqlstates.append(getattr(error.orig, "sqlstate", None))
                raise
            if not getattr(thread_state, "first_authority_locked", False):
                thread_state.first_authority_locked = True
                try:
                    after_first_authority.wait(timeout=2)
                except threading.BrokenBarrierError:
                    pass
            return locked

        def recorded_presentations(connection, **kwargs):
            batch_calls.append(set(kwargs["bindings"]))
            return published_for_signals(connection, **kwargs)

        monkeypatch.setattr(
            backfill_module,
            "lock_publication_source",
            synchronized_lock,
        )
        monkeypatch.setattr(
            backfill_module,
            "published_for_signals",
            recorded_presentations,
        )

        def run_page(offset: int) -> None:
            try:
                start.wait(timeout=3)
                results[offset] = backfill_factual_presentations(
                    postgres_engine,
                    account_id=case.account_id,
                    as_of=DAY,
                    language="fr",
                    limit=2,
                    offset=offset,
                    now=NOW + dt.timedelta(minutes=offset),
                )
            except BaseException as error:  # noqa: BLE001 - asserted by test thread
                errors.append(error)

        first = threading.Thread(target=run_page, args=(0,), daemon=True)
        second = threading.Thread(target=run_page, args=(2,), daemon=True)
        try:
            first.start()
            second.start()
            start.wait(timeout=3)
            first.join(timeout=15)
            second.join(timeout=15)

            assert not first.is_alive()
            assert not second.is_alive()
            assert errors == []
            assert "40P01" not in lock_sqlstates
            assert results == {
                0: BackfillResult(
                    scanned=2,
                    published=2,
                    unchanged=0,
                    failed=0,
                    next_offset=2,
                    scan_truncated=False,
                ),
                2: BackfillResult(
                    scanned=2,
                    published=2,
                    unchanged=0,
                    failed=0,
                    next_offset=None,
                    scan_truncated=False,
                ),
            }
            assert len(batch_calls) == 2
            assert {frozenset(call) for call in batch_calls} == {
                frozenset(case.signal_keys[:2]),
                frozenset(case.signal_keys[2:]),
            }
            with postgres_engine.connect() as connection:
                rows = list(
                    connection.execute(
                        sa.select(
                            card_presentation_artifact.c.signal_key,
                            card_presentation_artifact.c.version,
                            card_presentation_artifact.c.superseded_at,
                        ).where(
                            card_presentation_artifact.c.account_id == case.account_id
                        )
                    ).mappings()
                )
            assert {row["signal_key"] for row in rows} == set(case.signal_keys)
            assert all(row["version"] == 1 for row in rows)
            assert all(row["superseded_at"] is None for row in rows)
        finally:
            first.join(timeout=1)
            second.join(timeout=1)


def test_postgresql_account_backfill_lock_ends_with_its_transaction() -> None:
    with _isolated_postgres_engine() as postgres_engine:
        lock_count = sa.text(
            "SELECT count(*) FROM pg_locks "
            "WHERE pid = :pid AND locktype = 'advisory' AND granted"
        )
        for finish in ("commit", "rollback"):
            connection = postgres_engine.connect()
            transaction = connection.begin()
            try:
                backend_pid = int(connection.scalar(sa.text("SELECT pg_backend_pid()")))
                backfill_module._lock_account_backfill_transaction(
                    connection,
                    account_id="transaction-scope-test",
                )
                with postgres_engine.connect() as observer:
                    held = observer.scalar(lock_count, {"pid": backend_pid})
                assert held == 1

                getattr(transaction, finish)()

                with postgres_engine.connect() as observer:
                    remaining = observer.scalar(lock_count, {"pid": backend_pid})
                assert remaining == 0
            finally:
                if transaction.is_active:
                    transaction.rollback()
                connection.close()
