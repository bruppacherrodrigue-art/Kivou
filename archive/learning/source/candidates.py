"""Deterministic bounded allocation candidate generation."""

from __future__ import annotations

from decimal import Decimal

from signals.learning.contracts import (
    CANDIDATE_GENERATION_VERSION,
    AllocationUnit,
    CandidateKind,
    EconomicScore,
    EconomicScoreStatus,
    LearningAllocationEnvelope,
    LearningCandidate,
    LearningCellKey,
    canonical_fingerprint,
)


def _vector(
    values: dict[str, int], cells: dict[str, LearningCellKey]
) -> tuple[AllocationUnit, ...]:
    return tuple(AllocationUnit(cell=cells[key], units=values[key]) for key in sorted(values))


def _candidate_ref(payload: dict[str, object]) -> str:
    return canonical_fingerprint("learning-proposal:v1", payload)


def generate_candidates(
    *,
    snapshot_ref: str,
    envelope: LearningAllocationEnvelope,
    scores: tuple[EconomicScore, ...],
    baseline_authority_ref: str,
    current_allocation: dict[str, int] | None = None,
) -> tuple[LearningCandidate, ...]:
    cells = {item.cell.key: item.cell for item in envelope.cells}
    bounds = {item.cell.key: item for item in envelope.cells}
    current = (
        {item.cell.key: item.current_units for item in envelope.cells}
        if current_allocation is None
        else dict(current_allocation)
    )
    if current.keys() != cells.keys() or sum(current.values()) != envelope.total_daily_units:
        raise ValueError("current allocation is incompatible with the envelope")
    current_vector = _vector(current, cells)
    no_change_payload = {
        "candidate_version": CANDIDATE_GENERATION_VERSION,
        "snapshot_ref": snapshot_ref,
        "kind": CandidateKind.NO_CHANGE.value,
        "allocation": [item.model_dump(mode="json") for item in current_vector],
        "baseline_authority_ref": baseline_authority_ref,
    }
    no_change = LearningCandidate(
        proposal_ref=_candidate_ref(no_change_payload),
        snapshot_ref=snapshot_ref,
        kind=CandidateKind.NO_CHANGE,
        current_allocation=current_vector,
        proposed_allocation=current_vector,
        baseline_authority_ref=baseline_authority_ref,
        delta_units=0,
        expected_score_delta=Decimal(0),
        reason_codes=("NO_SAFE_REALLOCATION_REQUIRED",),
    )
    ready = [
        score
        for score in scores
        if score.status is EconomicScoreStatus.READY and score.cell.key in current
    ]
    moves: list[tuple[Decimal, str, str, LearningCandidate]] = []
    for donor in ready:
        for receiver in ready:
            if donor.cell == receiver.cell or donor.currency != receiver.currency:
                continue
            if receiver.score <= donor.score:
                continue
            if current[donor.cell.key] <= bounds[donor.cell.key].minimum_units:
                continue
            if current[receiver.cell.key] >= bounds[receiver.cell.key].maximum_units:
                continue
            proposed = dict(current)
            proposed[donor.cell.key] -= 1
            proposed[receiver.cell.key] += 1
            proposed_vector = _vector(proposed, cells)
            score_delta = receiver.score - donor.score
            payload = {
                "candidate_version": CANDIDATE_GENERATION_VERSION,
                "snapshot_ref": snapshot_ref,
                "kind": CandidateKind.SHIFT_ONE_UNIT.value,
                "from": donor.cell.model_dump(mode="json"),
                "to": receiver.cell.model_dump(mode="json"),
                "delta": 1,
                "current": [item.model_dump(mode="json") for item in current_vector],
                "proposed": [item.model_dump(mode="json") for item in proposed_vector],
                "baseline_authority_ref": baseline_authority_ref,
            }
            candidate = LearningCandidate(
                proposal_ref=_candidate_ref(payload),
                snapshot_ref=snapshot_ref,
                kind=CandidateKind.SHIFT_ONE_UNIT,
                current_allocation=current_vector,
                proposed_allocation=proposed_vector,
                baseline_authority_ref=baseline_authority_ref,
                from_cell=donor.cell,
                to_cell=receiver.cell,
                delta_units=1,
                expected_score_delta=score_delta,
                reason_codes=("SHIFT_TO_HIGHER_RETAINED_VALUE",),
            )
            moves.append((score_delta, donor.cell.key, receiver.cell.key, candidate))
    moves.sort(key=lambda item: (-item[0], item[1], item[2]))
    return (no_change, *(item[3] for item in moves[:4]))


__all__ = ["generate_candidates"]
