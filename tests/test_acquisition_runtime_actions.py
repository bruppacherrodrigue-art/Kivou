from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.acquisition_runtime.actions import (
    KivouDomainDisposition,
    KivouDomainOutcome,
    build_kivou_stage_handlers,
)
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeProposal,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.registry import AcquisitionActionContext

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)


class FakeDomainActions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, AcquisitionActionContext]] = []

    def _result(self, name: str, context: AcquisitionActionContext):
        self.calls.append((name, context))
        return KivouDomainOutcome(
            disposition=KivouDomainDisposition.COMPLETE,
            result_refs=(f"{name}:result-001",),
            observed_cost=Decimal("0.10"),
            reason_codes=("DOMAIN_STAGE_COMPLETE",),
        )

    def resolve_signal_seed(self, context):
        return self._result("signal-seed", context)

    def discover_supplier(self, context):
        return self._result("supplier", context)

    def discover_contact(self, context):
        return self._result("contact", context)

    def research_company(self, context):
        return self._result("company", context)

    def decide(self, context):
        return self._result("decision", context)

    def personalize(self, context):
        return self._result("personalization", context)

    def assess_compliance(self, context):
        return self._result("compliance", context)

    def plan_campaign(self, context):
        return self._result("campaign", context)

    def handoff_provider(self, context):
        return self._result("provider", context)

    def observe_response(self, context):
        return self._result("response", context)

    def reconcile_conversion(self, context):
        return self._result("conversion", context)


EXPECTED_METHOD = {
    AcquisitionRuntimeStage.SIGNAL_SEED: "signal-seed",
    AcquisitionRuntimeStage.SUPPLIER_DISCOVERY: "supplier",
    AcquisitionRuntimeStage.CONTACT_DISCOVERY: "contact",
    AcquisitionRuntimeStage.COMPANY_RESEARCH: "company",
    AcquisitionRuntimeStage.DECISION: "decision",
    AcquisitionRuntimeStage.PERSONALIZATION: "personalization",
    AcquisitionRuntimeStage.COMPLIANCE: "compliance",
    AcquisitionRuntimeStage.CAMPAIGN: "campaign",
    AcquisitionRuntimeStage.PROVIDER_HANDOFF: "provider",
    AcquisitionRuntimeStage.RESPONSE: "response",
    AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION: "conversion",
}


def _context(stage: AcquisitionRuntimeStage) -> AcquisitionActionContext:
    cycle = RuntimeCycleSnapshot(
        cycle_ref="cycle-001",
        opportunity_key="signal-001",
        status=RuntimeCycleStatus.RUNNING,
        next_stage=stage,
        spent_cost=Decimal("0"),
        started_at=NOW,
    )
    return AcquisitionActionContext(
        stage=stage,
        proposal=RuntimeProposal(
            plan_ref="plan-001",
            action_index=0,
            command=stage.command,
            target_ref=cycle.cycle_ref,
            argument_fingerprint="a" * 64,
            estimated_cost=Decimal("0.25"),
            reason_codes=("QA_RUNTIME_STEP",),
        ),
        cycle=cycle,
        stage_snapshot=RuntimeStageSnapshot(
            cycle_ref=cycle.cycle_ref,
            stage=stage,
            status=RuntimeStageStatus.RUNNING,
            attempt_count=2,
            result_refs=("prior:checkpoint-001",),
        ),
        allow_qa_provider_mutations=(
            stage is AcquisitionRuntimeStage.PROVIDER_HANDOFF
        ),
        at=NOW,
    )


def test_every_runtime_stage_is_bound_to_one_explicit_domain_method() -> None:
    domain = FakeDomainActions()
    handlers = build_kivou_stage_handlers(domain)

    assert set(handlers) == set(AcquisitionRuntimeStage)
    for stage in AcquisitionRuntimeStage:
        context = _context(stage)
        result = handlers[stage](context)

        assert result.status is RuntimeStageStatus.SUCCEEDED
        assert result.result_refs == (f"{EXPECTED_METHOD[stage]}:result-001",)
        assert domain.calls[-1] == (EXPECTED_METHOD[stage], context)
        assert domain.calls[-1][1].stage_snapshot.attempt_ref


@pytest.mark.parametrize(
    ("disposition", "expected"),
    (
        (KivouDomainDisposition.COMPLETE, RuntimeStageStatus.SUCCEEDED),
        (KivouDomainDisposition.WAITING, RuntimeStageStatus.WAITING),
        (KivouDomainDisposition.BLOCKED, RuntimeStageStatus.BLOCKED),
        (KivouDomainDisposition.SUPPRESSED, RuntimeStageStatus.SUPPRESSED),
        (KivouDomainDisposition.FAILED, RuntimeStageStatus.FAILED),
    ),
)
def test_domain_dispositions_map_to_closed_runtime_states(disposition, expected) -> None:
    outcome = KivouDomainOutcome(
        disposition=disposition,
        reason_codes=("BOUNDED_DOMAIN_RESULT",),
    )

    assert outcome.to_runtime_result().status is expected


@pytest.mark.parametrize(
    "unsafe_ref",
    (
        "person@example.test",
        "https://provider.invalid/raw",
        "raw payload",
    ),
)
def test_domain_outcome_rejects_pii_urls_and_raw_payload_refs(unsafe_ref) -> None:
    with pytest.raises(ValidationError):
        KivouDomainOutcome(
            disposition=KivouDomainDisposition.COMPLETE,
            result_refs=(unsafe_ref,),
        )


def test_non_complete_domain_outcome_requires_a_machine_reason() -> None:
    with pytest.raises(ValidationError, match="machine reason"):
        KivouDomainOutcome(disposition=KivouDomainDisposition.WAITING)
