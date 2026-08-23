"""Bounded H-D shadow and H-F closed-loop evidence evaluators."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from signals.operations.contracts import GateEvidence, GateStatus, SafeRef


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence time must be timezone-aware")
    return value.astimezone(dt.UTC)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ShadowEvidenceFacts(_FrozenModel):
    observed_at: dt.datetime
    shadow_decision_count: int = Field(ge=0)
    human_review_count: int = Field(ge=0)
    agreement_count: int = Field(ge=0)
    disagreement_count: int = Field(ge=0)
    outcome_refs: tuple[SafeRef, ...] = Field(max_length=100)
    _observed = field_validator("observed_at")(_aware)

    @model_validator(mode="after")
    def bounded_counts(self) -> ShadowEvidenceFacts:
        compared = self.agreement_count + self.disagreement_count
        if compared > self.shadow_decision_count or compared > self.human_review_count:
            raise ValueError("shadow comparison counts exceed source evidence")
        return self


class ClosedLoopIntegrityFacts(_FrozenModel):
    observed_at: dt.datetime
    sent_member_count: int = Field(ge=0)
    response_count: int = Field(ge=0)
    click_count: int = Field(ge=0)
    journey_count: int = Field(ge=0)
    conversion_event_count: int = Field(ge=0)
    orphan_response_count: int = Field(ge=0)
    orphan_click_count: int = Field(ge=0)
    orphan_journey_count: int = Field(ge=0)
    orphan_conversion_event_count: int = Field(ge=0)
    _observed = field_validator("observed_at")(_aware)


def evaluate_shadow_evidence(facts: ShadowEvidenceFacts) -> GateEvidence:
    if facts.shadow_decision_count == 0:
        return GateEvidence(
            status=GateStatus.INSUFFICIENT_EVIDENCE,
            reason_codes=("SHADOW_DECISIONS_UNAVAILABLE",),
        )
    if facts.human_review_count == 0:
        return GateEvidence(
            status=GateStatus.INSUFFICIENT_EVIDENCE,
            reason_codes=("HUMAN_REVIEW_TRUTH_UNAVAILABLE",),
        )
    if facts.agreement_count + facts.disagreement_count == 0:
        return GateEvidence(
            status=GateStatus.INSUFFICIENT_EVIDENCE,
            reason_codes=("SHADOW_COMPARISON_UNAVAILABLE",),
        )
    return GateEvidence(
        status=GateStatus.READY,
        reason_codes=("SHADOW_COMPARISON_AVAILABLE",),
        evidence_refs=tuple(sorted(set(facts.outcome_refs))),
    )


def evaluate_closed_loop_integrity(facts: ClosedLoopIntegrityFacts) -> GateEvidence:
    orphan_count = (
        facts.orphan_response_count
        + facts.orphan_click_count
        + facts.orphan_journey_count
        + facts.orphan_conversion_event_count
    )
    if orphan_count:
        return GateEvidence(
            status=GateStatus.NOT_READY,
            reason_codes=("CLOSED_LOOP_ORPHAN_DETECTED",),
        )
    return GateEvidence(
        status=GateStatus.READY,
        reason_codes=("CLOSED_LOOP_IDENTITIES_JOINABLE",),
        evidence_refs=("acquisition-state-v1", "conversion-event-v1"),
    )


__all__ = [
    "ClosedLoopIntegrityFacts",
    "ShadowEvidenceFacts",
    "evaluate_closed_loop_integrity",
    "evaluate_shadow_evidence",
]
