"""Opaque proposal-only Hermes selection boundary."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from signals.learning.contracts import (
    CandidateKind,
    EconomicScore,
    LearningCandidate,
    LearningCandidateSummary,
    LearningCellSummary,
    LearningSelection,
    LearningSelectionContext,
)


class HermesLearningSelector(Protocol):
    def select(self, context: LearningSelectionContext) -> LearningSelection: ...


class UnconfiguredHermesLearningSelector:
    """Safe repository default: choose the Kivou-generated NO_CHANGE candidate."""

    def select(self, context: LearningSelectionContext) -> LearningSelection:
        candidate = next(
            item for item in context.candidates if item.kind is CandidateKind.NO_CHANGE
        )
        return LearningSelection(
            snapshot_ref=context.snapshot_ref,
            proposal_ref=candidate.proposal_ref,
            reason_codes=("HERMES_SELECTOR_UNCONFIGURED",),
            confidence=Decimal(1),
        )


def build_selection_context(
    *,
    snapshot_ref: str,
    scores: tuple[EconomicScore, ...],
    candidates: tuple[LearningCandidate, ...],
) -> LearningSelectionContext:
    return LearningSelectionContext(
        snapshot_ref=snapshot_ref,
        cells=tuple(
            LearningCellSummary(
                cell=item.cell,
                economic_status=item.status,
                currency=item.currency,
                economic_score=item.score,
                reason_codes=item.reason_codes,
            )
            for item in scores
        ),
        candidates=tuple(
            LearningCandidateSummary(
                proposal_ref=item.proposal_ref,
                kind=item.kind,
                from_cell=item.from_cell,
                to_cell=item.to_cell,
                delta_units=item.delta_units,
                expected_score_delta=item.expected_score_delta,
                reason_codes=item.reason_codes,
            )
            for item in candidates
        ),
    )


def validate_selection(
    selection: LearningSelection,
    *,
    snapshot_ref: str,
    candidates: tuple[LearningCandidate, ...],
) -> LearningCandidate:
    if selection.snapshot_ref != snapshot_ref:
        raise ValueError("Hermes selection snapshot mismatch")
    selected = next(
        (item for item in candidates if item.proposal_ref == selection.proposal_ref), None
    )
    if selected is None:
        raise ValueError("Hermes may select only a supplied candidate")
    return selected


__all__ = [
    "HermesLearningSelector",
    "UnconfiguredHermesLearningSelector",
    "build_selection_context",
    "validate_selection",
]
