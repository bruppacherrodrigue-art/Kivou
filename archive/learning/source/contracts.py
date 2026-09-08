"""Strict v1 country-by-wedge learning contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

HERMES_LEARNING_LOOP_VERSION = "hermes-learning-loop-v1"
LEARNING_WINDOW_VERSION = "learning-window-v1"
LEARNING_SNAPSHOT_VERSION = "learning-snapshot-v1"
LEARNING_CELL_METRICS_VERSION = "learning-cell-metrics-v1"
LEARNING_ALLOCATION_ENVELOPE_VERSION = "learning-allocation-envelope-v1"
LEARNING_RISK_POLICY_VERSION = "learning-risk-policy-v1"
LEARNING_COST_POLICY_VERSION = "learning-cost-policy-v1"
ECONOMIC_FORMULA_VERSION = "wedge-economic-value-v1"
CANDIDATE_GENERATION_VERSION = "learning-candidate-generation-v1"
LEARNING_SELECTION_VERSION = "learning-selection-v1"
LEARNING_PROPOSAL_VERSION = "learning-proposal-v1"

Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ShortCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class LearningContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(dt.UTC)


def canonical_fingerprint(domain: str, value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value,
        allow_nan=False,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(f"kivou:{domain}\0".encode() + encoded).hexdigest()


class LearningCellKey(LearningContract):
    country: Literal["CH", "FR"]
    wedge: ShortCode

    @property
    def key(self) -> str:
        return f"{self.country}:{self.wedge}"


class LearningWindow(LearningContract):
    version: Literal["learning-window-v1"] = LEARNING_WINDOW_VERSION
    window_start: dt.datetime
    window_end: dt.datetime
    captured_at: dt.datetime

    _times = field_validator("window_start", "window_end", "captured_at")(_aware)

    @model_validator(mode="after")
    def exact_window(self) -> LearningWindow:
        if self.window_end - self.window_start != dt.timedelta(days=60):
            raise ValueError("learning window must be exactly 60 days")
        if self.captured_at < self.window_end:
            raise ValueError("snapshot cannot be captured before window end")
        return self


def make_learning_window(*, window_end: dt.datetime, captured_at: dt.datetime) -> LearningWindow:
    return LearningWindow(
        window_start=window_end - dt.timedelta(days=60),
        window_end=window_end,
        captured_at=captured_at,
    )


class LearningCellMetrics(LearningContract):
    version: Literal["learning-cell-metrics-v1"] = LEARNING_CELL_METRICS_VERSION
    cell: LearningCellKey
    contacted_count: int = Field(ge=0)
    bounce_count: int = Field(ge=0)
    positive_reply_count: int = Field(ge=0)
    complaint_count: int = Field(ge=0)
    unsubscribe_count: int = Field(ge=0)
    click_count: int = Field(ge=0)
    signup_count: int = Field(ge=0)
    activation_count: int = Field(ge=0)
    paid_count: int = Field(ge=0)
    known_mrr_minor_units: int = Field(ge=0)
    retained_mrr_minor_units: int = Field(ge=0)
    currency: Literal["CHF", "EUR"] | None
    mrr_complete: bool
    m1_eligible_count: int = Field(ge=0)
    retained_m1_count: int = Field(ge=0)
    m2_eligible_count: int = Field(ge=0)
    retained_m2_count: int = Field(ge=0)
    churn_count: int = Field(ge=0)
    known_variable_cost_minor_units: int = Field(ge=0)
    cost_currency: Literal["CHF", "EUR"] | None
    cost_complete: bool
    missing_cost_reason_codes: tuple[ShortCode, ...] = Field(max_length=8)
    conversion_identity_ambiguous: bool = False

    @model_validator(mode="after")
    def coherent_counts_and_money(self) -> LearningCellMetrics:
        if self.bounce_count > self.contacted_count:
            raise ValueError("bounce count cannot exceed contacted members")
        if self.positive_reply_count > self.contacted_count:
            raise ValueError("positive replies are unique contacted members")
        if self.complaint_count > self.contacted_count:
            raise ValueError("complaints are unique contacted members")
        if self.unsubscribe_count > self.contacted_count:
            raise ValueError("unsubscribes are unique contacted members")
        if self.retained_m1_count > self.m1_eligible_count:
            raise ValueError("M1 retained count exceeds eligibility")
        if self.retained_m2_count > self.m2_eligible_count:
            raise ValueError("M2 retained count exceeds eligibility")
        if self.churn_count > self.paid_count:
            raise ValueError("churn count exceeds paid journeys")
        if self.cost_complete and self.missing_cost_reason_codes:
            raise ValueError("complete cost cannot have missing components")
        if self.mrr_complete and self.paid_count and self.currency is None:
            raise ValueError("complete paid MRR requires a currency")
        if self.cost_complete and self.cost_currency is None:
            raise ValueError("complete cost requires a currency")
        return self

    @computed_field
    @property
    def delivery_proxy_count(self) -> int:
        return max(self.contacted_count - self.bounce_count, 0)

    def _ratio(self, numerator: int, denominator: int) -> Decimal | None:
        return Decimal(numerator) / Decimal(denominator) if denominator else None

    @computed_field
    @property
    def delivery_proxy_rate(self) -> Decimal | None:
        return self._ratio(self.delivery_proxy_count, self.contacted_count)

    @computed_field
    @property
    def positive_reply_rate(self) -> Decimal | None:
        return self._ratio(self.positive_reply_count, self.contacted_count)

    @computed_field
    @property
    def retention_m1_rate(self) -> Decimal | None:
        return self._ratio(self.retained_m1_count, self.m1_eligible_count)

    @computed_field
    @property
    def retention_m2_rate(self) -> Decimal | None:
        return self._ratio(self.retained_m2_count, self.m2_eligible_count)

    @computed_field
    @property
    def churn_rate(self) -> Decimal | None:
        return self._ratio(self.churn_count, self.paid_count)


class EconomicScoreStatus(StrEnum):
    READY = "READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    COST_INCOMPLETE = "COST_INCOMPLETE"
    MRR_INCOMPLETE = "MRR_INCOMPLETE"
    RISK_BLOCKED = "RISK_BLOCKED"


class EconomicScore(LearningContract):
    formula_version: Literal["wedge-economic-value-v1"] = ECONOMIC_FORMULA_VERSION
    cell: LearningCellKey
    status: EconomicScoreStatus
    currency: Literal["CHF", "EUR"] | None
    score: Decimal
    retained_mrr_per_contact: Decimal
    cost_per_contact: Decimal
    risk_penalty_per_contact: Decimal
    reason_codes: tuple[ShortCode, ...] = Field(max_length=12)


class AllocationCell(LearningContract):
    cell: LearningCellKey
    current_units: int = Field(ge=0)
    minimum_units: int = Field(ge=0)
    maximum_units: int = Field(ge=0)

    @model_validator(mode="after")
    def bounds(self) -> AllocationCell:
        if not self.minimum_units <= self.current_units <= self.maximum_units:
            raise ValueError("allocation cell is outside its bounds")
        return self


class LearningAllocationEnvelope(LearningContract):
    version: Literal["learning-allocation-envelope-v1"] = LEARNING_ALLOCATION_ENVELOPE_VERSION
    valid_from: dt.datetime
    valid_until: dt.datetime
    total_daily_units: int = Field(ge=0)
    cells: tuple[AllocationCell, ...] = Field(min_length=1, max_length=64)

    _times = field_validator("valid_from", "valid_until")(_aware)

    @model_validator(mode="after")
    def valid_envelope(self) -> LearningAllocationEnvelope:
        if self.valid_until <= self.valid_from:
            raise ValueError("allocation envelope validity is empty")
        keys = [cell.cell.key for cell in self.cells]
        if len(keys) != len(set(keys)):
            raise ValueError("allocation cells must be unique")
        if sum(cell.current_units for cell in self.cells) != self.total_daily_units:
            raise ValueError("current allocation must conserve total daily units")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_fingerprint(
            "learning-allocation-envelope:v1",
            self.model_dump(mode="json", exclude={"fingerprint"}),
        )


class AllocationUnit(LearningContract):
    cell: LearningCellKey
    units: int = Field(ge=0)


class CandidateKind(StrEnum):
    NO_CHANGE = "NO_CHANGE"
    SHIFT_ONE_UNIT = "SHIFT_ONE_UNIT"


class LearningCandidate(LearningContract):
    candidate_version: Literal["learning-candidate-generation-v1"] = CANDIDATE_GENERATION_VERSION
    proposal_ref: Fingerprint
    snapshot_ref: Fingerprint
    kind: CandidateKind
    current_allocation: tuple[AllocationUnit, ...]
    proposed_allocation: tuple[AllocationUnit, ...]
    baseline_authority_ref: StableRef
    from_cell: LearningCellKey | None = None
    to_cell: LearningCellKey | None = None
    delta_units: Literal[0, 1]
    expected_score_delta: Decimal
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def valid_move(self) -> LearningCandidate:
        current = {item.cell.key: item.units for item in self.current_allocation}
        proposed = {item.cell.key: item.units for item in self.proposed_allocation}
        if current.keys() != proposed.keys() or sum(current.values()) != sum(proposed.values()):
            raise ValueError("candidate must preserve its allocation envelope")
        if self.kind is CandidateKind.NO_CHANGE:
            if current != proposed or self.delta_units or self.from_cell or self.to_cell:
                raise ValueError("NO_CHANGE candidate cannot mutate allocation")
        else:
            if self.delta_units != 1 or self.from_cell is None or self.to_cell is None:
                raise ValueError("shift candidate must move exactly one unit")
            if current[self.from_cell.key] - proposed[self.from_cell.key] != 1:
                raise ValueError("shift donor delta is invalid")
            if proposed[self.to_cell.key] - current[self.to_cell.key] != 1:
                raise ValueError("shift receiver delta is invalid")
        return self


class LearningSelection(LearningContract):
    version: Literal["learning-selection-v1"] = LEARNING_SELECTION_VERSION
    snapshot_ref: Fingerprint
    proposal_ref: Fingerprint
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=8)
    confidence: Decimal = Field(ge=0, le=1)

    @field_validator("confidence")
    @classmethod
    def finite_confidence(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("confidence must be finite")
        return value


class LearningCellSummary(LearningContract):
    cell: LearningCellKey
    economic_status: EconomicScoreStatus
    currency: Literal["CHF", "EUR"] | None
    economic_score: Decimal
    reason_codes: tuple[ShortCode, ...] = Field(max_length=12)


class LearningCandidateSummary(LearningContract):
    proposal_ref: Fingerprint
    kind: CandidateKind
    from_cell: LearningCellKey | None
    to_cell: LearningCellKey | None
    delta_units: Literal[0, 1]
    expected_score_delta: Decimal
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=8)


class LearningSelectionContext(LearningContract):
    version: Literal["learning-selection-v1"] = LEARNING_SELECTION_VERSION
    snapshot_ref: Fingerprint
    formula_version: Literal["wedge-economic-value-v1"] = ECONOMIC_FORMULA_VERSION
    risk_policy_version: Literal["learning-risk-policy-v1"] = LEARNING_RISK_POLICY_VERSION
    cells: tuple[LearningCellSummary, ...] = Field(max_length=64)
    candidates: tuple[LearningCandidateSummary, ...] = Field(min_length=1, max_length=5)


class LearningSnapshot(LearningContract):
    snapshot_ref: Fingerprint
    learning_version: Literal["hermes-learning-loop-v1"] = HERMES_LEARNING_LOOP_VERSION
    window: LearningWindow
    formula_version: Literal["wedge-economic-value-v1"] = ECONOMIC_FORMULA_VERSION
    formula_fingerprint: Fingerprint
    risk_policy_version: Literal["learning-risk-policy-v1"] = LEARNING_RISK_POLICY_VERSION
    risk_policy_fingerprint: Fingerprint
    cost_policy_version: Literal["learning-cost-policy-v1"] = LEARNING_COST_POLICY_VERSION
    cost_policy_fingerprint: Fingerprint
    input_fingerprint: Fingerprint
    cell_metrics: tuple[LearningCellMetrics, ...] = Field(max_length=64)
    economic_scores: tuple[EconomicScore, ...] = Field(max_length=64)
    allocation_envelope_version: Literal["learning-allocation-envelope-v1"] = (
        LEARNING_ALLOCATION_ENVELOPE_VERSION
    )
    allocation_envelope_fingerprint: Fingerprint
    current_allocation: tuple[AllocationUnit, ...]
    current_allocation_fingerprint: Fingerprint
    previous_applied_proposal_ref: Fingerprint | None = None
    created_at: dt.datetime

    _created = field_validator("created_at")(_aware)

    @model_validator(mode="after")
    def coherent_snapshot(self) -> LearningSnapshot:
        if self.created_at != self.window.captured_at:
            raise ValueError("snapshot creation must equal explicit capture time")
        if tuple(item.cell.key for item in self.cell_metrics) != tuple(
            item.cell.key for item in self.economic_scores
        ):
            raise ValueError("metrics and economic scores must share ordered cells")
        return self


__all__ = [
    "CANDIDATE_GENERATION_VERSION",
    "ECONOMIC_FORMULA_VERSION",
    "HERMES_LEARNING_LOOP_VERSION",
    "LEARNING_ALLOCATION_ENVELOPE_VERSION",
    "LEARNING_CELL_METRICS_VERSION",
    "LEARNING_COST_POLICY_VERSION",
    "LEARNING_PROPOSAL_VERSION",
    "LEARNING_RISK_POLICY_VERSION",
    "LEARNING_SELECTION_VERSION",
    "LEARNING_SNAPSHOT_VERSION",
    "LEARNING_WINDOW_VERSION",
    "AllocationCell",
    "AllocationUnit",
    "CandidateKind",
    "EconomicScore",
    "EconomicScoreStatus",
    "LearningAllocationEnvelope",
    "LearningCandidate",
    "LearningCandidateSummary",
    "LearningCellKey",
    "LearningCellMetrics",
    "LearningCellSummary",
    "LearningSelection",
    "LearningSelectionContext",
    "LearningSnapshot",
    "LearningWindow",
    "canonical_fingerprint",
    "make_learning_window",
]
