from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import sqlalchemy as sa
from alembic import command

from signals.learning.candidates import generate_candidates
from signals.learning.contracts import (
    AllocationCell,
    LearningAllocationEnvelope,
    LearningCellKey,
    LearningCellMetrics,
    make_learning_window,
)
from signals.learning.economics import score_cell
from signals.learning.service import build_learning_snapshot
from signals.learning.store import LearningStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import acquisition_allocation_proposal

NOW = dt.datetime(2026, 8, 22, 12, tzinfo=dt.UTC)


def _metrics(wedge: str, retained_mrr: int) -> LearningCellMetrics:
    return LearningCellMetrics(
        cell=LearningCellKey(country="CH", wedge=wedge),
        contacted_count=50,
        bounce_count=0,
        positive_reply_count=2,
        complaint_count=0,
        unsubscribe_count=0,
        click_count=2,
        signup_count=2,
        activation_count=2,
        paid_count=2,
        known_mrr_minor_units=retained_mrr,
        retained_mrr_minor_units=retained_mrr,
        currency="CHF",
        mrr_complete=True,
        m1_eligible_count=2,
        retained_m1_count=1,
        m2_eligible_count=0,
        retained_m2_count=0,
        churn_count=0,
        known_variable_cost_minor_units=1_000,
        cost_currency="CHF",
        cost_complete=True,
        missing_cost_reason_codes=(),
    )


def _envelope() -> LearningAllocationEnvelope:
    return LearningAllocationEnvelope(
        valid_from=NOW,
        valid_until=NOW + dt.timedelta(days=30),
        total_daily_units=5,
        cells=(
            AllocationCell(
                cell=LearningCellKey(country="CH", wedge="weaker"),
                current_units=3,
                minimum_units=1,
                maximum_units=4,
            ),
            AllocationCell(
                cell=LearningCellKey(country="CH", wedge="stronger"),
                current_units=2,
                minimum_units=1,
                maximum_units=4,
            ),
        ),
    )


def _context(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'learning-store.db'}")
    command.upgrade(alembic_config(engine), "head")
    envelope = _envelope()
    metrics = (_metrics("weaker", 10_000), _metrics("stronger", 30_000))
    snapshot = build_learning_snapshot(
        window=make_learning_window(window_end=NOW, captured_at=NOW),
        metrics=metrics,
        envelope=envelope,
        previous_applied_proposal_ref=None,
    )
    candidates = generate_candidates(
        snapshot_ref=snapshot.snapshot_ref,
        envelope=envelope,
        scores=tuple(score_cell(item) for item in metrics),
        baseline_authority_ref="INITIAL:" + envelope.fingerprint,
    )
    return engine, snapshot, envelope, candidates


def test_snapshot_and_candidates_are_exact_replays(tmp_path) -> None:
    engine, snapshot, envelope, candidates = _context(tmp_path)
    store = LearningStore(engine)

    assert store.save_snapshot(snapshot).replayed is False
    assert store.save_snapshot(snapshot).replayed is True
    first = store.save_candidates(
        candidates, envelope_fingerprint=envelope.fingerprint, created_at=NOW
    )
    replay = store.save_candidates(
        candidates, envelope_fingerprint=envelope.fingerprint, created_at=NOW
    )

    assert all(not item.replayed for item in first)
    assert all(item.replayed for item in replay)
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_allocation_proposal)
        ) == len(candidates)


def test_snapshot_retry_keeps_original_capture_timestamp(tmp_path) -> None:
    engine, snapshot, _, _ = _context(tmp_path)
    store = LearningStore(engine)
    store.save_snapshot(snapshot)
    retry_window = snapshot.window.model_copy(
        update={"captured_at": NOW + dt.timedelta(minutes=1)}
    )
    retry = snapshot.model_copy(
        update={"window": retry_window, "created_at": retry_window.captured_at}
    )

    result = store.save_snapshot(retry)

    assert result.replayed is True
    assert result.row["captured_at"].replace(tzinfo=dt.UTC) == NOW


def test_duplicate_application_moves_volume_once_and_stale_candidate_is_rejected(tmp_path) -> None:
    engine, snapshot, envelope, candidates = _context(tmp_path)
    store = LearningStore(engine)
    store.save_snapshot(snapshot)
    store.save_candidates(candidates, envelope_fingerprint=envelope.fingerprint, created_at=NOW)
    shift = next(item for item in candidates if item.delta_units == 1)
    store.record_selection(
        shift.proposal_ref,
        source="HERMES",
        confidence=Decimal("0.9"),
        decided_at=NOW,
    )
    store.record_policy(
        shift.proposal_ref,
        evaluation_id="evaluation-1",
        action_fingerprint="f" * 64,
        status="APPROVED",
        counterfactual_status=None,
        state="PROPOSED",
        decided_at=NOW,
    )

    first = store.apply(shift.proposal_ref, applied_at=NOW)
    replay = store.apply(shift.proposal_ref, applied_at=NOW)

    assert first.applied is True
    assert replay.replayed is True
    assert store.current_allocation(envelope.fingerprint).authority_ref == shift.proposal_ref
    assert sum(store.current_allocation(envelope.fingerprint).allocation.values()) == 5


def test_two_candidates_on_same_baseline_have_at_most_one_applied_successor(tmp_path) -> None:
    engine, snapshot, envelope, candidates = _context(tmp_path)
    store = LearningStore(engine)
    store.save_snapshot(snapshot)
    shift = next(item for item in candidates if item.delta_units == 1)
    alternative = shift.model_copy(
        update={
            "proposal_ref": "9" * 64,
            "reason_codes": ("SYNTHETIC_COMPETING_MOVE",),
        }
    )
    store.save_candidates(
        (shift, alternative), envelope_fingerprint=envelope.fingerprint, created_at=NOW
    )
    for index, proposal in enumerate((shift, alternative), 1):
        store.record_selection(
            proposal.proposal_ref,
            source="HERMES",
            confidence=Decimal("0.9"),
            decided_at=NOW,
        )
        store.record_policy(
            proposal.proposal_ref,
            evaluation_id=f"evaluation-{index}",
            action_fingerprint=str(index) * 64,
            status="APPROVED",
            counterfactual_status=None,
            state="PROPOSED",
            decided_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda ref: LearningStore(engine).apply(ref, applied_at=NOW),
                (shift.proposal_ref, alternative.proposal_ref),
            )
        )

    assert sum(result.applied for result in results) == 1
    with engine.connect() as connection:
        states = (
            connection.execute(sa.select(acquisition_allocation_proposal.c.state)).scalars().all()
        )
    assert sorted(states) == ["APPLIED", "REJECTED"]


def test_current_allocation_follows_authority_chain_not_timestamp_order(tmp_path) -> None:
    engine, snapshot, envelope, candidates = _context(tmp_path)
    store = LearningStore(engine)
    store.save_snapshot(snapshot)
    store.save_candidates(candidates, envelope_fingerprint=envelope.fingerprint, created_at=NOW)
    first = next(item for item in candidates if item.delta_units == 1)
    store.record_selection(
        first.proposal_ref, source="HERMES", confidence=Decimal("0.9"), decided_at=NOW
    )
    store.record_policy(
        first.proposal_ref,
        evaluation_id="evaluation-chain-1",
        action_fingerprint="1" * 64,
        status="APPROVED",
        counterfactual_status=None,
        state="PROPOSED",
        decided_at=NOW,
    )
    store.apply(first.proposal_ref, applied_at=NOW)

    current = store.current_allocation(envelope.fingerprint)
    second_snapshot = build_learning_snapshot(
        window=make_learning_window(
            window_end=NOW + dt.timedelta(days=1),
            captured_at=NOW + dt.timedelta(days=1),
        ),
        metrics=(_metrics("weaker", 10_000), _metrics("stronger", 30_000)),
        envelope=envelope,
        previous_applied_proposal_ref=first.proposal_ref,
        current_allocation=current.allocation,
    )
    store.save_snapshot(second_snapshot)
    second_candidates = generate_candidates(
        snapshot_ref=second_snapshot.snapshot_ref,
        envelope=envelope,
        scores=tuple(score_cell(item) for item in second_snapshot.cell_metrics),
        baseline_authority_ref=first.proposal_ref,
        current_allocation=current.allocation,
    )
    second = next(item for item in second_candidates if item.delta_units == 1).model_copy(
        update={"proposal_ref": "0" * 64}
    )
    store.save_candidates(
        (second,),
        envelope_fingerprint=envelope.fingerprint,
        created_at=NOW + dt.timedelta(days=1),
    )
    store.record_selection(
        second.proposal_ref,
        source="HERMES",
        confidence=Decimal("0.9"),
        decided_at=NOW + dt.timedelta(days=1),
    )
    store.record_policy(
        second.proposal_ref,
        evaluation_id="evaluation-chain-2",
        action_fingerprint="2" * 64,
        status="APPROVED",
        counterfactual_status=None,
        state="PROPOSED",
        decided_at=NOW + dt.timedelta(days=1),
    )
    store.apply(second.proposal_ref, applied_at=NOW)

    assert store.current_allocation(envelope.fingerprint).authority_ref == second.proposal_ref
