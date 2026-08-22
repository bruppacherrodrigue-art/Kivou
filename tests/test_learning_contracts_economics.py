import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.learning.candidates import generate_candidates
from signals.learning.contracts import (
    AllocationCell,
    CandidateKind,
    EconomicScoreStatus,
    LearningAllocationEnvelope,
    LearningCellKey,
    LearningCellMetrics,
    LearningSelection,
    make_learning_window,
)
from signals.learning.economics import score_cell
from signals.learning.hermes import (
    UnconfiguredHermesLearningSelector,
    build_selection_context,
    validate_selection,
)
from signals.learning.service import build_learning_snapshot

NOW = dt.datetime(2026, 8, 22, 12, tzinfo=dt.UTC)


def _metrics(
    country: str,
    wedge: str,
    *,
    contacted: int = 50,
    positive: int = 2,
    bounced: int = 0,
    complaints: int = 0,
    unsubscribes: int = 0,
    paid: int = 2,
    retained_m1: int = 1,
    retained_mrr: int = 20_000,
    cost: int = 2_000,
    currency: str = "CHF",
    cost_currency: str | None = None,
    cost_complete: bool = True,
    mrr_complete: bool = True,
) -> LearningCellMetrics:
    return LearningCellMetrics(
        cell=LearningCellKey(country=country, wedge=wedge),
        contacted_count=contacted,
        bounce_count=bounced,
        positive_reply_count=positive,
        complaint_count=complaints,
        unsubscribe_count=unsubscribes,
        click_count=2,
        signup_count=2,
        activation_count=2,
        paid_count=paid,
        known_mrr_minor_units=retained_mrr,
        retained_mrr_minor_units=retained_mrr,
        currency=currency,
        mrr_complete=mrr_complete,
        m1_eligible_count=2,
        retained_m1_count=retained_m1,
        m2_eligible_count=0,
        retained_m2_count=0,
        churn_count=0,
        known_variable_cost_minor_units=cost,
        cost_currency=cost_currency or currency,
        cost_complete=cost_complete,
        missing_cost_reason_codes=() if cost_complete else ("PROVIDER_COST_UNAVAILABLE",),
        conversion_identity_ambiguous=False,
    )


def _envelope() -> LearningAllocationEnvelope:
    return LearningAllocationEnvelope(
        valid_from=NOW,
        valid_until=NOW + dt.timedelta(days=30),
        total_daily_units=5,
        cells=(
            AllocationCell(
                cell=LearningCellKey(country="CH", wedge="construction"),
                current_units=3,
                minimum_units=1,
                maximum_units=4,
            ),
            AllocationCell(
                cell=LearningCellKey(country="CH", wedge="maintenance"),
                current_units=2,
                minimum_units=1,
                maximum_units=4,
            ),
        ),
    )


def test_window_is_explicit_aware_and_exactly_sixty_days() -> None:
    window = make_learning_window(window_end=NOW, captured_at=NOW)

    assert window.window_start == NOW - dt.timedelta(days=60)
    assert window.window_end == NOW
    with pytest.raises(ValidationError):
        make_learning_window(window_end=NOW.replace(tzinfo=None), captured_at=NOW)


def test_metrics_use_decimal_delivery_proxy_and_allow_forwarded_signup_counts() -> None:
    metrics = _metrics("CH", "construction", contacted=1, positive=1, bounced=1)
    forwarded = metrics.model_copy(update={"signup_count": 2, "paid_count": 2})

    assert metrics.delivery_proxy_count == 0
    assert metrics.delivery_proxy_rate == Decimal("0")
    assert metrics.positive_reply_rate == Decimal("1")
    assert forwarded.signup_count == 2


def test_retained_mrr_beats_high_replies_without_revenue() -> None:
    retained = score_cell(_metrics("CH", "construction", positive=1))
    engagement_only = score_cell(_metrics("CH", "maintenance", positive=45, retained_mrr=0))

    assert retained.status is EconomicScoreStatus.READY
    assert retained.score > engagement_only.score


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"contacted_count": 49}, EconomicScoreStatus.INSUFFICIENT_EVIDENCE),
        ({"cost_complete": False}, EconomicScoreStatus.COST_INCOMPLETE),
        ({"mrr_complete": False}, EconomicScoreStatus.MRR_INCOMPLETE),
        ({"complaint_count": 1}, EconomicScoreStatus.RISK_BLOCKED),
        ({"bounce_count": 3}, EconomicScoreStatus.RISK_BLOCKED),
    ],
)
def test_score_statuses_fail_closed(change, status) -> None:
    metrics = _metrics("CH", "construction").model_copy(update=change)

    assert score_cell(metrics).status is status


def test_envelope_conserves_total_and_bounds_cells() -> None:
    assert sum(cell.current_units for cell in _envelope().cells) == 5
    with pytest.raises(ValidationError):
        _envelope().model_copy(update={"total_daily_units": 6}, deep=True).model_validate(
            _envelope().model_dump() | {"total_daily_units": 6}
        )


def test_candidates_are_bounded_one_unit_conserved_and_same_currency() -> None:
    envelope = _envelope()
    candidates = generate_candidates(
        snapshot_ref="a" * 64,
        envelope=envelope,
        scores=(
            score_cell(_metrics("CH", "construction", retained_mrr=10_000)),
            score_cell(_metrics("CH", "maintenance", retained_mrr=30_000)),
        ),
        baseline_authority_ref="INITIAL:" + "b" * 64,
    )

    assert len(candidates) <= 5
    assert candidates[0].kind is CandidateKind.NO_CHANGE
    shift = next(item for item in candidates if item.kind is CandidateKind.SHIFT_ONE_UNIT)
    assert shift.delta_units == 1
    assert sum(item.units for item in shift.proposed_allocation) == 5
    assert shift.from_cell == LearningCellKey(country="CH", wedge="construction")
    assert shift.to_cell == LearningCellKey(country="CH", wedge="maintenance")

    incompatible = generate_candidates(
        snapshot_ref="a" * 64,
        envelope=envelope,
        scores=(
            score_cell(_metrics("CH", "construction", currency="CHF")),
            score_cell(_metrics("CH", "maintenance", currency="EUR")),
        ),
        baseline_authority_ref="INITIAL:" + "b" * 64,
    )
    assert [item.kind for item in incompatible] == [CandidateKind.NO_CHANGE]


def test_cost_currency_mismatch_is_not_ready_for_economic_comparison() -> None:
    score = score_cell(
        _metrics("CH", "construction", currency="CHF", cost_currency="EUR")
    )

    assert score.status is EconomicScoreStatus.COST_INCOMPLETE
    assert "COST_CURRENCY_MISMATCH" in score.reason_codes


def test_hermes_can_only_select_a_supplied_proposal_ref() -> None:
    candidates = generate_candidates(
        snapshot_ref="a" * 64,
        envelope=_envelope(),
        scores=(
            score_cell(_metrics("CH", "construction", retained_mrr=10_000)),
            score_cell(_metrics("CH", "maintenance", retained_mrr=30_000)),
        ),
        baseline_authority_ref="INITIAL:" + "b" * 64,
    )
    context = build_selection_context(
        snapshot_ref="a" * 64,
        scores=(
            score_cell(_metrics("CH", "construction", retained_mrr=10_000)),
            score_cell(_metrics("CH", "maintenance", retained_mrr=30_000)),
        ),
        candidates=candidates,
    )
    default = UnconfiguredHermesLearningSelector().select(context)

    assert default.proposal_ref == candidates[0].proposal_ref
    assert candidates[0].kind is CandidateKind.NO_CHANGE
    assert "current_allocation" not in context.model_dump_json()
    assert "proposed_allocation" not in context.model_dump_json()
    with pytest.raises(ValueError, match="supplied candidate"):
        validate_selection(
            LearningSelection(
                snapshot_ref="a" * 64,
                proposal_ref="f" * 64,
                reason_codes=("SYNTHETIC",),
                confidence=Decimal("0.5"),
            ),
            snapshot_ref="a" * 64,
            candidates=candidates,
        )


def test_same_window_inputs_have_same_snapshot_ref_across_capture_retry() -> None:
    envelope = _envelope()
    metrics = (_metrics("CH", "construction"), _metrics("CH", "maintenance"))
    first = build_learning_snapshot(
        window=make_learning_window(window_end=NOW, captured_at=NOW),
        metrics=metrics,
        envelope=envelope,
        previous_applied_proposal_ref=None,
    )
    retried = build_learning_snapshot(
        window=make_learning_window(window_end=NOW, captured_at=NOW + dt.timedelta(minutes=1)),
        metrics=metrics,
        envelope=envelope,
        previous_applied_proposal_ref=None,
    )

    assert first.snapshot_ref == retried.snapshot_ref
    assert first.input_fingerprint == retried.input_fingerprint
