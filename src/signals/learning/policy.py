"""Exact Kivou Policy request for one bounded future-plan proposal."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Protocol

import sqlalchemy as sa
from pydantic import Field, field_validator

from signals.learning.contracts import (
    Fingerprint,
    LearningContract,
    ShortCode,
    StableRef,
    canonical_fingerprint,
)
from signals.persistence.schema import (
    acquisition_allocation_proposal,
    acquisition_learning_snapshot,
)
from signals.policy.contracts import (
    POLICY_VERSION,
    BudgetUsage,
    ComplianceAssessment,
    ComplianceState,
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    PolicyRequest,
    Scope,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore

REALLOCATION_TARGET = "global:acquisition-allocation-v1"


@dataclass(frozen=True)
class LearningPolicyAuthorization:
    allowed: bool
    executable: bool
    policy_evaluation_id: str
    policy_action_fingerprint: str
    policy_status: str
    policy_counterfactual_status: str | None


class LearningPolicyAuthorizer(Protocol):
    def authorize(self, proposal_ref: str, *, now: dt.datetime) -> LearningPolicyAuthorization: ...


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(dt.UTC)


def _database_aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class LearningPolicyFacts(LearningContract):
    proposal_ref: Fingerprint
    snapshot_ref: Fingerprint
    snapshot_input_fingerprint: Fingerprint
    formula_version: ShortCode
    formula_fingerprint: Fingerprint
    risk_policy_version: ShortCode
    risk_policy_fingerprint: Fingerprint
    allocation_envelope_version: ShortCode
    allocation_envelope_fingerprint: Fingerprint
    current_allocation_fingerprint: Fingerprint
    proposed_allocation_fingerprint: Fingerprint
    total_daily_units: int = Field(ge=0, le=100_000)
    delta_units: int = Field(ge=0, le=1)
    candidate_version: ShortCode
    window_start: dt.datetime
    window_end: dt.datetime
    observed_at: dt.datetime
    policy_snapshot_id: StableRef
    control_revision: int = Field(ge=1)

    _times = field_validator("window_start", "window_end", "observed_at")(_aware)


def build_reallocate_policy_request(
    facts: LearningPolicyFacts,
    *,
    operational: OperationalReadiness,
    currency: str,
) -> PolicyRequest:
    arguments = {"proposal_ref": facts.proposal_ref}
    action_fingerprint = canonical_fingerprint(
        "reallocate-volume-action:v1",
        {
            "command": "reallocate_volume",
            "target_ref": REALLOCATION_TARGET,
            **facts.model_dump(mode="json"),
        },
    )
    evaluation_id = canonical_fingerprint(
        "reallocate-volume-policy-evaluation:v1",
        {
            "proposal_ref": facts.proposal_ref,
            "action_fingerprint": action_fingerprint,
            "policy_snapshot_id": facts.policy_snapshot_id,
            "control_revision": facts.control_revision,
        },
    )
    return PolicyRequest(
        evaluation_id=evaluation_id,
        request_id=evaluation_id,
        command="reallocate_volume",
        target_ref=REALLOCATION_TARGET,
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
        actor_type="HERMES",
        actor_ref="kivou-hermes-learning-selector",
        canonical_arguments=json.dumps(arguments, separators=(",", ":"), sort_keys=True),
        action_fingerprint=action_fingerprint,
        scope=Scope(),
        proposed_cost=0,
        currency=currency,
        proposed_volume=0,
        reason_codes=("BOUNDED_LEARNING_REALLOCATION",),
        evidence_refs=(
            f"learning-snapshot:{facts.snapshot_ref}",
            f"allocation-envelope:{facts.allocation_envelope_fingerprint}",
            f"allocation-proposal:{facts.proposal_ref}",
        ),
        evidence=EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=(
                "LEARNING_SNAPSHOT",
                "ALLOCATION_ENVELOPE",
                "CONVERSION_RETENTION",
            ),
            assessment_version="learning-policy-evidence-v1",
            observed_at=facts.observed_at,
        ),
        compliance=ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="learning-no-compliance-gate-v1",
            observed_at=facts.observed_at,
        ),
        operational=operational,
        expected_policy_version=POLICY_VERSION,
    )


class GatewayLearningPolicyAuthorizer:
    """Resolve one proposal and bind the exact effective control before evaluation."""

    def __init__(
        self,
        engine: sa.Engine,
        *,
        operational_provider,
        budget_usage_provider,
        currency: str,
    ) -> None:
        self.engine = engine
        self.gateway = PolicyGateway(engine)
        self.controls = PolicyStore(engine)
        self.operational_provider = operational_provider
        self.budget_usage_provider = budget_usage_provider
        self.currency = currency

    def authorize(self, proposal_ref: str, *, now: dt.datetime) -> LearningPolicyAuthorization:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(acquisition_allocation_proposal, acquisition_learning_snapshot)
                    .join(
                        acquisition_learning_snapshot,
                        acquisition_allocation_proposal.c.snapshot_ref
                        == acquisition_learning_snapshot.c.snapshot_ref,
                    )
                    .where(acquisition_allocation_proposal.c.proposal_ref == proposal_ref)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise KeyError(proposal_ref)
        control = self.controls.get_effective_control(now)
        facts = LearningPolicyFacts(
            proposal_ref=proposal_ref,
            snapshot_ref=row["snapshot_ref"],
            snapshot_input_fingerprint=row["input_fingerprint"],
            formula_version=row["formula_version"],
            formula_fingerprint=row["formula_fingerprint"],
            risk_policy_version=row["risk_policy_version"],
            risk_policy_fingerprint=row["risk_policy_fingerprint"],
            allocation_envelope_version=row["allocation_envelope_version"],
            allocation_envelope_fingerprint=row["allocation_envelope_fingerprint"],
            current_allocation_fingerprint=row["current_allocation_fingerprint"],
            proposed_allocation_fingerprint=row["proposed_allocation_fingerprint"],
            total_daily_units=sum(int(item["units"]) for item in row["current_allocation"]),
            delta_units=row["delta_units"],
            candidate_version=row["candidate_version"],
            window_start=_database_aware(row["window_start"]),
            window_end=_database_aware(row["window_end"]),
            observed_at=_database_aware(row["captured_at"]),
            policy_snapshot_id=control.policy_snapshot_id,
            control_revision=control.control_revision,
        )
        request = build_reallocate_policy_request(
            facts,
            operational=self.operational_provider(proposal_ref, now),
            currency=self.currency,
        )
        usage = self.budget_usage_provider(proposal_ref, now)
        if not isinstance(usage, BudgetUsage):
            raise TypeError("budget usage provider returned an invalid contract")
        decision = self.gateway.evaluate_and_record(
            request,
            evaluated_at=now,
            budget_usage=usage,
            policy_snapshot_id=control.policy_snapshot_id,
        )
        return LearningPolicyAuthorization(
            allowed=decision.allowed,
            executable=decision.executable,
            policy_evaluation_id=decision.evaluation_id,
            policy_action_fingerprint=decision.action_fingerprint,
            policy_status=decision.status.value,
            policy_counterfactual_status=(
                decision.counterfactual_status.value
                if decision.counterfactual_status is not None
                else None
            ),
        )


__all__ = [
    "REALLOCATION_TARGET",
    "GatewayLearningPolicyAuthorizer",
    "LearningPolicyAuthorization",
    "LearningPolicyAuthorizer",
    "LearningPolicyFacts",
    "build_reallocate_policy_request",
]
