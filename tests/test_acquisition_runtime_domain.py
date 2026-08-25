from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from signals.acquisition.contracts import AcquisitionState, Decision
from signals.acquisition_runtime.actions import KivouDomainDisposition
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeProposal,
    RuntimeQaScope,
    RuntimeStageSnapshot,
)
from signals.acquisition_runtime.domain import (
    AcquisitionDomainActions,
    AuthorizedCall,
    CampaignTruth,
    ComplianceTruth,
    DecisionTruth,
    DomainAmbiguousFailure,
    DomainApprovalRequired,
    DomainAttemptIdentity,
    DomainTransientFailure,
    OpportunityTruth,
    PersonalizationTruth,
    ProviderOperationTruth,
    ResponseTruth,
    RuntimeApprovalProvider,
    RuntimePolicyAuthorizationFactory,
    SqlAcquisitionDomainTruth,
    deterministic_attempt_identity,
)
from signals.acquisition_runtime.registry import AcquisitionActionContext
from signals.campaigns.contracts import (
    CampaignDeploymentBlocked,
    CampaignPacingExceeded,
    ProviderOperationKind,
    ProviderOperationState,
)
from signals.compliance.contracts import ComplianceDisposition
from signals.decision_engine.contracts import DecisionAuditDisposition
from signals.personalization.contracts import PersonalizationDisposition
from signals.personalization.grounding import PersonalizationDecisionNoLongerEligible
from signals.policy.contracts import BudgetUsage, PolicyStatus
from signals.supplier_discovery.contracts import SupplierSearchNotActionable
from signals.supplier_discovery.seed import AcquisitionSeedNotFound

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)
QA_TRANSPORT_IDENTITY = "9" * 64
QA_TRANSPORT_KEY_VERSION = "runtime-qa-v1"


class FakeExecutionGuard:
    def __init__(self, *times: dt.datetime) -> None:
        self._times = iter(times or (NOW,))
        self.checkpoints: list[dt.datetime] = []

    @contextmanager
    def protect(self):
        try:
            observed_at = next(self._times)
        except StopIteration:
            observed_at = self.checkpoints[-1]
        self.checkpoints.append(observed_at)
        yield observed_at


def _context(
    stage: AcquisitionRuntimeStage,
    *,
    attempt: int = 1,
    allow_provider: bool = False,
    guard: FakeExecutionGuard | None = None,
) -> AcquisitionActionContext:
    cycle = RuntimeCycleSnapshot(
        cycle_ref="cycle-qa-001",
        opportunity_key="signal-qa-001",
        status=RuntimeCycleStatus.RUNNING,
        next_stage=stage,
        spent_cost=Decimal("0"),
        started_at=NOW,
    )
    snapshot = RuntimeStageSnapshot(
        cycle_ref=cycle.cycle_ref,
        stage=stage,
        status="RUNNING",
        attempt_count=attempt,
    )
    proposal = RuntimeProposal(
        plan_ref="plan-qa-001",
        action_index=0,
        command=stage.command,
        target_ref=cycle.cycle_ref,
        argument_fingerprint="a" * 64,
        estimated_cost=Decimal("0"),
        reason_codes=("QA_TEST",),
    )
    return AcquisitionActionContext(
        stage=stage,
        cycle=cycle,
        stage_snapshot=snapshot,
        proposal=proposal,
        allow_qa_provider_mutations=allow_provider,
        guard=guard or FakeExecutionGuard(),
        at=NOW,
    )


def test_attempt_identity_is_stable_for_replay_and_fresh_for_new_attempt() -> None:
    first = deterministic_attempt_identity(
        _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY).stage_snapshot
    )
    replay = deterministic_attempt_identity(
        _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY).stage_snapshot
    )
    retry = deterministic_attempt_identity(
        _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY, attempt=2).stage_snapshot
    )

    assert first == replay
    assert first != retry
    assert all(
        len(value) == 64
        for value in (
            first.evaluation_id,
            first.request_id,
            first.run_id,
            first.correlation_id,
        )
    )


def test_domain_boundary_exports_real_sql_truth_and_injected_policy_protocols() -> None:
    assert SqlAcquisitionDomainTruth is not None
    assert RuntimePolicyAuthorizationFactory is not None
    assert RuntimeApprovalProvider is not None
    assert DomainAttemptIdentity is not None


def test_transient_failure_never_reflects_untrusted_provider_detail() -> None:
    error = DomainTransientFailure("private@example.com")

    assert error.code == "DOMAIN_RETRYABLE"
    assert "@" not in str(error)


class FakeTruth:
    def __init__(self) -> None:
        self.seed = ("source-event:qa-001", "contract-award:qa-001")
        self.current_opportunity: OpportunityTruth | None = None
        self.profile_ref: str | None = None
        self.current_decision: DecisionTruth | None = None
        self.current_personalization: PersonalizationTruth | None = None
        self.current_compliance: ComplianceTruth | None = None
        self.current_campaign: CampaignTruth | None = None
        self.operations: tuple[ProviderOperationTruth, ...] = ()
        self.current_response: ResponseTruth | None = None
        self.conversion: tuple[str, ...] = ()

    def resolve_seed(self, opportunity_key: str) -> tuple[str, ...]:
        assert opportunity_key == "signal-qa-001"
        return self.seed

    def signal_country(self, opportunity_key: str) -> str:
        assert opportunity_key == "signal-qa-001"
        return "CH"

    def opportunity(self, opportunity_key: str) -> OpportunityTruth | None:
        assert opportunity_key == "signal-qa-001"
        return self.current_opportunity

    def company_profile_ref(self, opportunity_id: str) -> str | None:
        assert opportunity_id == "opportunity-qa-001"
        return self.profile_ref

    def decision(self, opportunity_id: str) -> DecisionTruth | None:
        assert opportunity_id == "opportunity-qa-001"
        return self.current_decision

    def personalization(self, opportunity_id: str) -> PersonalizationTruth | None:
        assert opportunity_id == "opportunity-qa-001"
        return self.current_personalization

    def compliance(self, opportunity_id: str) -> ComplianceTruth | None:
        assert opportunity_id == "opportunity-qa-001"
        return self.current_compliance

    def campaign(self, opportunity_id: str) -> CampaignTruth | None:
        assert opportunity_id == "opportunity-qa-001"
        return self.current_campaign

    def provider_operations(
        self, campaign_ref: str, member_ref: str
    ) -> tuple[ProviderOperationTruth, ...]:
        assert campaign_ref == "campaign-qa-001"
        assert member_ref == "member-qa-001"
        return self.operations

    def response(
        self, opportunity_id: str, campaign: CampaignTruth
    ) -> ResponseTruth | None:
        assert opportunity_id == "opportunity-qa-001"
        assert campaign == self.current_campaign
        return self.current_response

    def conversion_refs(
        self, opportunity_id: str, campaign: CampaignTruth
    ) -> tuple[str, ...]:
        assert opportunity_id == "opportunity-qa-001"
        assert campaign == self.current_campaign
        return self.conversion


class FakeApprovals:
    def __init__(self) -> None:
        self.calls: list[tuple[AcquisitionRuntimeStage, str | None]] = []
        self.action_fingerprints: list[str | None] = []

    def consume_for(
        self,
        context,
        *,
        opportunity_id,
        action_fingerprint=None,
    ):
        self.calls.append((context.stage, opportunity_id))
        self.action_fingerprints.append(action_fingerprint)
        return ()


class FakeAuthorizations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, DomainAttemptIdentity, tuple[object, ...]]] = []

    def _call(self, name, identity, approvals, *, language=None):
        self.calls.append((name, identity, approvals))
        return AuthorizedCall(
            authorization=SimpleNamespace(evaluation_id=identity.evaluation_id),
            budget_usage=BudgetUsage(),
            language=language,
        )

    def revalidate_provider_recovery(self, context, *, opportunity_id):
        del context, opportunity_id

    def supplier(self, context, identity, approvals):
        return self._call("supplier", identity, approvals)

    def contact(self, context, identity, approvals, *, opportunity_id):
        return self._call("contact", identity, approvals)

    def company(self, context, identity, approvals, *, opportunity_id):
        return self._call("company", identity, approvals)

    def decision(self, context, identity, approvals, *, opportunity_id):
        return self._call("decision", identity, approvals)

    def personalization(self, context, identity, approvals, *, opportunity_id):
        return self._call("personalization", identity, approvals, language="fr")

    def compliance(self, context, identity, approvals, *, opportunity_id):
        return self._call("compliance", identity, approvals)

    def campaign(self, context, identity, approvals, *, opportunity_id):
        return self._call("campaign", identity, approvals)


class FakeSupplierService:
    def __init__(self, truth: FakeTruth) -> None:
        self.truth = truth
        self.calls = 0

    def resume_started(self, discovery_run_id, *, authorize_recovery):
        del discovery_run_id
        del authorize_recovery

    def discover(self, opportunity_key, targeting, authorization, **kwargs):
        self.calls += 1
        assert targeting.max_pages == 1
        assert targeting.per_page == 1
        assert targeting.candidate_cap == 1
        self.truth.current_opportunity = OpportunityTruth(
            opportunity_id="opportunity-qa-001",
            state=AcquisitionState.ENRICHING,
            supplier_ref="supplier-qa-001",
        )
        return SimpleNamespace(
            decision=SimpleNamespace(executable=True, status=PolicyStatus.APPROVED),
            run=SimpleNamespace(status="SUCCESS", retry_after=None, error_category=None),
            opportunity_ids=("opportunity-qa-001",),
        )


class FakeContactService:
    def __init__(self, truth: FakeTruth) -> None:
        self.truth = truth

    def resume_started(self, run_id, *, authorize_recovery):
        del run_id
        del authorize_recovery

    def find(self, opportunity_id, authorization, **kwargs):
        self.truth.current_opportunity = replace(
            self.truth.current_opportunity,
            contact_ref="contact-qa-001",
        )
        return SimpleNamespace(
            decision=SimpleNamespace(executable=True, status=PolicyStatus.APPROVED),
            run=SimpleNamespace(status="SUCCESS", retry_after=None, error_category=None),
            contact=SimpleNamespace(contact_ref="contact-qa-001"),
        )


class FakeCompanyService:
    def __init__(self, truth: FakeTruth) -> None:
        self.truth = truth

    def resume_started(self, run_id, *, authorize_recovery):
        del run_id
        del authorize_recovery

    def research(self, opportunity_id, authorization, **kwargs):
        self.truth.profile_ref = "profile-qa-001"
        self.truth.current_opportunity = replace(
            self.truth.current_opportunity,
            state=AcquisitionState.READY_FOR_DECISION,
        )
        return SimpleNamespace(
            decision=SimpleNamespace(executable=True, status=PolicyStatus.APPROVED),
            run=SimpleNamespace(status="SUCCESS", retry_after=None, error_category=None),
            profile=SimpleNamespace(prebuild_fingerprint="profile-qa-001"),
        )


class FakeDecisionService:
    def __init__(self, truth: FakeTruth, decision: Decision = Decision.SEND) -> None:
        self.truth = truth
        self.proposed_decision = decision

    def evaluate(self, opportunity_id, authorization, **kwargs):
        self.truth.current_decision = DecisionTruth(
            evaluation_ref="decision-qa-001", decision=self.proposed_decision
        )
        self.truth.current_opportunity = replace(
            self.truth.current_opportunity,
            state=AcquisitionState(self.proposed_decision.value),
            decision=self.proposed_decision,
        )
        return SimpleNamespace(
            decision=SimpleNamespace(executable=True, status=PolicyStatus.APPROVED),
            audit=SimpleNamespace(decision_evaluation_id="decision-qa-001"),
            proposal=SimpleNamespace(proposed_decision=self.proposed_decision),
        )


class FakePersonalizationService:
    def __init__(self, truth: FakeTruth) -> None:
        self.truth = truth

    def personalize(self, opportunity_id, language, authorization, **kwargs):
        assert language == "fr"
        self.truth.current_personalization = PersonalizationTruth(
            artifact_ref="personalization-qa-001",
            disposition=PersonalizationDisposition.READY,
        )
        return SimpleNamespace(
            personalization_artifact_id="personalization-qa-001",
            disposition=PersonalizationDisposition.READY,
        )


class FakeComplianceService:
    def __init__(self, truth: FakeTruth) -> None:
        self.truth = truth

    def assess(self, opportunity_id, authorization, **kwargs):
        self.truth.current_compliance = ComplianceTruth(
            assessment_ref="compliance-qa-001",
            disposition=ComplianceDisposition.RECORDED,
            state="ALLOWED",
        )
        return SimpleNamespace(
            compliance_assessment_id="compliance-qa-001",
            disposition=ComplianceDisposition.RECORDED,
            state="ALLOWED",
        )


class FakeCampaignService:
    def __init__(self, truth: FakeTruth) -> None:
        self.truth = truth

    def schedule(self, opportunity_id, authorization, **kwargs):
        self.truth.current_campaign = CampaignTruth(
            campaign_ref="campaign-qa-001", member_ref="member-qa-001"
        )
        self.truth.current_opportunity = replace(
            self.truth.current_opportunity,
            campaign_ref="campaign-qa-001",
        )
        self.truth.operations = tuple(
            ProviderOperationTruth(
                operation_ref=f"operation-{kind.value.lower()}",
                kind=kind,
                state=ProviderOperationState.PLANNED,
            )
            for kind in (
                ProviderOperationKind.CREATE_CAMPAIGN,
                ProviderOperationKind.CONFIGURE_CAMPAIGN,
                ProviderOperationKind.ADD_LEAD,
            )
        )
        return SimpleNamespace(
            disposition="PLANNED",
            policy_status=PolicyStatus.APPROVED.value,
            campaign_ref="campaign-qa-001",
            member_ref="member-qa-001",
        )


class FakeCampaignWorker:
    def __init__(self, truth: FakeTruth) -> None:
        self.truth = truth
        self.calls: list[ProviderOperationKind] = []

    def process(self, operation_ref: str, now: dt.datetime) -> ProviderOperationState:
        operations = list(self.truth.operations)
        index = next(
            index
            for index, operation in enumerate(operations)
            if operation.operation_ref == operation_ref
        )
        self.calls.append(operations[index].kind)
        operations[index] = replace(operations[index], state=ProviderOperationState.CONFIRMED)
        self.truth.operations = tuple(operations)
        if operations[index].kind is ProviderOperationKind.ADD_LEAD:
            self.truth.current_campaign = replace(
                self.truth.current_campaign,
                transport_recipient_identity=QA_TRANSPORT_IDENTITY,
                transport_recipient_key_version=QA_TRANSPORT_KEY_VERSION,
            )
        return ProviderOperationState.CONFIRMED


def _actions(
    truth: FakeTruth,
    *,
    decision: Decision = Decision.SEND,
    worker: FakeCampaignWorker | None = None,
) -> tuple[AcquisitionDomainActions, FakeCampaignWorker, FakeApprovals]:
    campaign_worker = worker or FakeCampaignWorker(truth)
    approvals = FakeApprovals()
    actions = AcquisitionDomainActions(
        truth=truth,
        supplier_service=FakeSupplierService(truth),
        contact_service=FakeContactService(truth),
        company_service=FakeCompanyService(truth),
        decision_service=FakeDecisionService(truth, decision),
        personalization_service=FakePersonalizationService(truth),
        compliance_service=FakeComplianceService(truth),
        campaign_service=FakeCampaignService(truth),
        campaign_worker=campaign_worker,
        authorization_factory=FakeAuthorizations(),
        approval_provider=approvals,
        maximum_provider_operations=3,
        qa_transport_recipient_identity=QA_TRANSPORT_IDENTITY,
        qa_transport_recipient_key_version=QA_TRANSPORT_KEY_VERSION,
        qa_scope=RuntimeQaScope(
            country="CH", language="fr", wedge="construction"
        ),
    )
    return actions, campaign_worker, approvals


def test_full_domain_cycle_composes_each_existing_stage_without_network() -> None:
    truth = FakeTruth()
    actions, worker, approvals = _actions(truth)
    outcomes = []
    calls = (
        (AcquisitionRuntimeStage.SIGNAL_SEED, actions.resolve_signal_seed),
        (AcquisitionRuntimeStage.SUPPLIER_DISCOVERY, actions.discover_supplier),
        (AcquisitionRuntimeStage.CONTACT_DISCOVERY, actions.discover_contact),
        (AcquisitionRuntimeStage.COMPANY_RESEARCH, actions.research_company),
        (AcquisitionRuntimeStage.DECISION, actions.decide),
        (AcquisitionRuntimeStage.PERSONALIZATION, actions.personalize),
        (AcquisitionRuntimeStage.COMPLIANCE, actions.assess_compliance),
        (AcquisitionRuntimeStage.CAMPAIGN, actions.plan_campaign),
        (AcquisitionRuntimeStage.PROVIDER_HANDOFF, actions.handoff_provider),
    )

    for stage, execute in calls:
        outcome = execute(
            _context(
                stage,
                allow_provider=stage is AcquisitionRuntimeStage.PROVIDER_HANDOFF,
            )
        )
        outcomes.append(outcome)
        assert outcome.disposition is KivouDomainDisposition.COMPLETE
        assert outcome.result_refs

    assert worker.calls == [
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ]
    assert ProviderOperationKind.ACTIVATE_CAMPAIGN not in worker.calls
    assert [stage for stage, _ in approvals.calls] == [
        *list(AcquisitionRuntimeStage)[1:8],
        *([AcquisitionRuntimeStage.PROVIDER_HANDOFF] * 4),
    ]
    rendered = repr(tuple(outcome.result_refs for outcome in outcomes))
    assert "@" not in rendered
    assert "payload" not in rendered.casefold()
    assert not any(
        value in rendered
        for value in (
            "supplier-qa-001",
            "contact-qa-001",
            "profile-qa-001",
            "campaign-qa-001",
            "member-qa-001",
        )
    )


def test_signal_seed_fails_closed_when_public_country_differs_from_qa_scope() -> None:
    truth = FakeTruth()
    truth.signal_country = lambda _key: "FR"
    actions, _, _ = _actions(truth)

    outcome = actions.resolve_signal_seed(
        _context(AcquisitionRuntimeStage.SIGNAL_SEED)
    )

    assert outcome.disposition is KivouDomainDisposition.BLOCKED
    assert outcome.reason_codes == ("QA_SCOPE_SIGNAL_MISMATCH",)


def test_response_and_conversion_wait_then_converge_from_durable_truth() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001",
        member_ref="member-qa-001",
        transport_recipient_identity=QA_TRANSPORT_IDENTITY,
        transport_recipient_key_version=QA_TRANSPORT_KEY_VERSION,
    )
    actions, _, _ = _actions(truth)

    waiting_response = actions.observe_response(_context(AcquisitionRuntimeStage.RESPONSE))
    waiting_conversion = actions.reconcile_conversion(
        _context(AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION)
    )
    assert waiting_response.disposition is KivouDomainDisposition.WAITING
    assert waiting_conversion.disposition is KivouDomainDisposition.WAITING

    truth.current_response = ResponseTruth(
        response_ref="response-qa-001", classification="POSITIVE"
    )
    truth.conversion = ("journey-qa-001", "conversion-qa-001")

    complete_response = actions.observe_response(
        _context(AcquisitionRuntimeStage.RESPONSE, attempt=2)
    )
    complete_conversion = actions.reconcile_conversion(
        _context(AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION, attempt=2)
    )
    assert complete_response.disposition is KivouDomainDisposition.COMPLETE
    assert complete_conversion.disposition is KivouDomainDisposition.COMPLETE


@pytest.mark.parametrize(
    ("decision", "expected", "reason"),
    (
        (
            Decision.NO_SEND,
            KivouDomainDisposition.SUPPRESSED,
            "DECISION_NO_SEND",
        ),
        (
            Decision.REVIEW,
            KivouDomainDisposition.BLOCKED,
            "DECISION_REVIEW_REQUIRED",
        ),
    ),
)
def test_decision_no_send_is_suppressed_and_review_is_blocked(
    decision: Decision,
    expected: KivouDomainDisposition,
    reason: str,
) -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.READY_FOR_DECISION,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
    )
    actions, _, _ = _actions(truth, decision=decision)

    outcome = actions.decide(_context(AcquisitionRuntimeStage.DECISION))

    assert outcome.disposition is expected
    assert outcome.reason_codes == (reason,)


def test_durable_approval_required_decision_waits_and_never_converges_as_send() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.READY_FOR_DECISION,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
    )
    truth.current_decision = DecisionTruth(
        evaluation_ref="decision-qa-001",
        decision=Decision.SEND,
        disposition=DecisionAuditDisposition.POLICY_BLOCKED,
        policy_status=PolicyStatus.APPROVAL_REQUIRED,
    )
    actions, _, _ = _actions(truth)

    outcome = actions.decide(_context(AcquisitionRuntimeStage.DECISION, attempt=2))

    assert outcome.disposition is KivouDomainDisposition.WAITING
    assert outcome.reason_codes == ("POLICY_APPROVAL_REQUIRED",)


def test_approval_blocked_personalization_reenters_exact_durable_review() -> None:
    class PendingApproval(FakeApprovals):
        def consume_for(self, context, *, opportunity_id):
            super().consume_for(context, opportunity_id=opportunity_id)
            raise DomainApprovalRequired

    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        decision=Decision.SEND,
    )
    truth.current_personalization = PersonalizationTruth(
        artifact_ref="personalization-blocked-qa-001",
        disposition=PersonalizationDisposition.POLICY_BLOCKED,
        policy_status=PolicyStatus.APPROVAL_REQUIRED,
    )
    actions, _, _ = _actions(truth)
    approvals = PendingApproval()
    actions._approvals = approvals

    outcome = actions.personalize(
        _context(AcquisitionRuntimeStage.PERSONALIZATION, attempt=2)
    )

    assert outcome.disposition is KivouDomainDisposition.WAITING
    assert outcome.reason_codes == ("HUMAN_APPROVAL_REQUIRED",)
    assert approvals.calls == [
        (AcquisitionRuntimeStage.PERSONALIZATION, "opportunity-qa-001")
    ]


@pytest.mark.parametrize("state", ("REVIEW_REQUIRED", "BLOCKED"))
def test_compliance_review_and_refusal_are_blocked(state: str) -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        decision=Decision.SEND,
    )
    truth.current_compliance = ComplianceTruth(
        assessment_ref="compliance-qa-001",
        disposition=ComplianceDisposition.RECORDED,
        state=state,
    )
    actions, _, _ = _actions(truth)

    outcome = actions.assess_compliance(_context(AcquisitionRuntimeStage.COMPLIANCE))

    assert outcome.disposition is KivouDomainDisposition.BLOCKED
    assert outcome.reason_codes == (
        "COMPLIANCE_REVIEW_REQUIRED" if state == "REVIEW_REQUIRED" else "COMPLIANCE_BLOCKED",
    )


class CrashAfterSupplierCommit(FakeSupplierService):
    def discover(self, *args, **kwargs):
        super().discover(*args, **kwargs)
        raise InterruptedError


def test_crash_after_domain_commit_replays_from_truth_without_duplicate_call() -> None:
    truth = FakeTruth()
    supplier = CrashAfterSupplierCommit(truth)
    actions, _, _ = _actions(truth)
    actions._supplier = supplier

    with pytest.raises(InterruptedError):
        actions.discover_supplier(_context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY))

    replay = actions.discover_supplier(_context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY))
    assert replay.disposition is KivouDomainDisposition.COMPLETE
    assert supplier.calls == 1


class RetryableSupplier(FakeSupplierService):
    def discover(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            decision=SimpleNamespace(executable=True, status=PolicyStatus.APPROVED),
            run=SimpleNamespace(
                status="FAILED",
                retry_after=NOW + dt.timedelta(minutes=1),
                error_category="rate_limited",
            ),
            opportunity_ids=(),
        )


def test_retryable_provider_uses_fresh_deterministic_attempt_on_retry() -> None:
    truth = FakeTruth()
    supplier = RetryableSupplier(truth)
    authorizations = FakeAuthorizations()
    actions, _, _ = _actions(truth)
    actions._supplier = supplier
    actions._authorizations = authorizations

    first = actions.discover_supplier(_context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY))
    retry = actions.discover_supplier(
        _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY, attempt=2)
    )

    assert first.disposition is KivouDomainDisposition.WAITING
    assert retry.disposition is KivouDomainDisposition.WAITING
    assert first.retry_at == NOW + dt.timedelta(minutes=1)
    assert retry.retry_at == NOW + dt.timedelta(minutes=1)
    assert authorizations.calls[0][1] != authorizations.calls[1][1]


class StartedSupplier(FakeSupplierService):
    def discover(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            decision=SimpleNamespace(
                executable=True,
                status=PolicyStatus.APPROVED,
            ),
            run=SimpleNamespace(
                status="STARTED",
                started_at=NOW,
                retry_after=None,
                error_category=None,
            ),
            opportunity_ids=(),
        )


def test_started_apollo_run_remains_same_attempt_after_bounded_recovery() -> None:
    truth = FakeTruth()
    supplier = StartedSupplier(truth)
    authorizations = FakeAuthorizations()
    actions, _, _ = _actions(truth)
    actions._supplier = supplier
    actions._authorizations = authorizations
    context = _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY)

    first = actions.discover_supplier(context)
    replay = actions.discover_supplier(context)

    assert first.disposition is KivouDomainDisposition.WAITING
    assert first.replay_same_attempt is True
    assert first.retry_at == NOW + dt.timedelta(minutes=1)
    assert replay == first
    assert authorizations.calls[0][1] == authorizations.calls[1][1]

    exhausted = actions.discover_supplier(
        _context(
            AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
            guard=FakeExecutionGuard(NOW + dt.timedelta(minutes=11)),
        )
    )
    assert exhausted.disposition is KivouDomainDisposition.WAITING
    assert exhausted.reason_codes == ("APOLLO_PROVIDER_OUTCOME_AMBIGUOUS",)
    assert exhausted.replay_same_attempt is True
    assert exhausted.retry_at == NOW + dt.timedelta(hours=1, minutes=11)


class WaitingCampaignWorker(FakeCampaignWorker):
    def __init__(self, truth: FakeTruth, state: ProviderOperationState) -> None:
        super().__init__(truth)
        self.state = state

    def process(self, operation_ref: str, now: dt.datetime) -> ProviderOperationState:
        operation = next(
            item for item in self.truth.operations if item.operation_ref == operation_ref
        )
        self.calls.append(operation.kind)
        return self.state


@pytest.mark.parametrize(
    "state",
    (
        ProviderOperationState.RETRYABLE_FAILED,
        ProviderOperationState.RECONCILE_REQUIRED,
    ),
)
def test_provider_429_or_timeout_state_waits_without_activation(
    state: ProviderOperationState,
) -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001", member_ref="member-qa-001"
    )
    truth.operations = tuple(
        ProviderOperationTruth(
            operation_ref=f"operation-{kind.value.lower()}",
            kind=kind,
            state=ProviderOperationState.PLANNED,
        )
        for kind in (
            ProviderOperationKind.CREATE_CAMPAIGN,
            ProviderOperationKind.CONFIGURE_CAMPAIGN,
            ProviderOperationKind.ADD_LEAD,
        )
    )
    worker = WaitingCampaignWorker(truth, state)
    actions, _, _ = _actions(truth, worker=worker)

    outcome = actions.handoff_provider(
        _context(AcquisitionRuntimeStage.PROVIDER_HANDOFF, allow_provider=True)
    )

    assert outcome.disposition is KivouDomainDisposition.WAITING
    assert worker.calls == [ProviderOperationKind.CREATE_CAMPAIGN]
    assert ProviderOperationKind.ACTIVATE_CAMPAIGN not in worker.calls


def test_provider_retry_after_waits_before_approval_or_worker_dispatch() -> None:
    retry_at = NOW + dt.timedelta(minutes=5)
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001", member_ref="member-qa-001"
    )
    truth.operations = tuple(
        ProviderOperationTruth(
            operation_ref=f"operation-{kind.value.lower()}",
            kind=kind,
            state=(
                ProviderOperationState.RETRYABLE_FAILED
                if kind is ProviderOperationKind.CREATE_CAMPAIGN
                else ProviderOperationState.PLANNED
            ),
            retry_at=(
                retry_at
                if kind is ProviderOperationKind.CREATE_CAMPAIGN
                else None
            ),
        )
        for kind in (
            ProviderOperationKind.CREATE_CAMPAIGN,
            ProviderOperationKind.CONFIGURE_CAMPAIGN,
            ProviderOperationKind.ADD_LEAD,
        )
    )
    actions, worker, approvals = _actions(truth)

    outcome = actions.handoff_provider(
        _context(AcquisitionRuntimeStage.PROVIDER_HANDOFF, allow_provider=True)
    )

    assert outcome.disposition is KivouDomainDisposition.WAITING
    assert outcome.retry_at == retry_at
    assert worker.calls == []
    assert approvals.calls == []


def test_provider_operations_receive_fresh_fenced_time_between_mutations() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001", member_ref="member-qa-001"
    )
    truth.operations = tuple(
        ProviderOperationTruth(
            operation_ref=f"operation-{kind.value.lower()}",
            kind=kind,
            state=ProviderOperationState.PLANNED,
        )
        for kind in (
            ProviderOperationKind.CREATE_CAMPAIGN,
            ProviderOperationKind.CONFIGURE_CAMPAIGN,
            ProviderOperationKind.ADD_LEAD,
        )
    )

    class TimedWorker(FakeCampaignWorker):
        def __init__(self, current_truth: FakeTruth) -> None:
            super().__init__(current_truth)
            self.times: list[dt.datetime] = []

        def process(self, operation_ref: str, now: dt.datetime):
            self.times.append(now)
            return super().process(operation_ref, now)

    times = tuple(NOW + dt.timedelta(seconds=index) for index in range(1, 5))
    guard = FakeExecutionGuard(*times)
    worker = TimedWorker(truth)
    actions, _, _ = _actions(truth, worker=worker)

    outcome = actions.handoff_provider(
        _context(
            AcquisitionRuntimeStage.PROVIDER_HANDOFF,
            allow_provider=True,
            guard=guard,
        )
    )

    assert outcome.disposition is KivouDomainDisposition.COMPLETE
    assert worker.times == list(times[-3:])
    assert len(guard.checkpoints) == 4


def test_provider_binding_drift_requires_a_new_approval_before_mutation() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001", member_ref="member-qa-001"
    )
    truth.operations = tuple(
        ProviderOperationTruth(
            operation_ref=f"operation-{kind.value.lower()}",
            kind=kind,
            state=ProviderOperationState.PLANNED,
            desired_request_fingerprint=f"{index}" * 64,
        )
        for index, kind in enumerate(
            (
                ProviderOperationKind.CREATE_CAMPAIGN,
                ProviderOperationKind.CONFIGURE_CAMPAIGN,
                ProviderOperationKind.ADD_LEAD,
            ),
            start=1,
        )
    )

    class DriftApproval(FakeApprovals):
        def consume_for(
            self,
            context,
            *,
            opportunity_id,
            action_fingerprint=None,
        ):
            result = super().consume_for(
                context,
                opportunity_id=opportunity_id,
                action_fingerprint=action_fingerprint,
            )
            if len(self.calls) == 1:
                operations = list(truth.operations)
                operations[0] = replace(
                    operations[0],
                    desired_request_fingerprint="9" * 64,
                )
                truth.operations = tuple(operations)
                return result
            raise DomainApprovalRequired

    actions, worker, _ = _actions(truth)
    approvals = DriftApproval()
    actions._approvals = approvals

    outcome = actions.handoff_provider(
        _context(AcquisitionRuntimeStage.PROVIDER_HANDOFF, allow_provider=True)
    )

    assert outcome.disposition is KivouDomainDisposition.WAITING
    assert outcome.reason_codes == ("HUMAN_APPROVAL_REQUIRED",)
    assert len(approvals.action_fingerprints) == 2
    assert approvals.action_fingerprints[0] != approvals.action_fingerprints[1]
    assert worker.calls == []


def test_provider_handoff_refuses_any_activation_operation() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001", member_ref="member-qa-001"
    )
    truth.operations = (
        ProviderOperationTruth(
            operation_ref="operation-activate",
            kind=ProviderOperationKind.ACTIVATE_CAMPAIGN,
            state=ProviderOperationState.PLANNED,
        ),
    )
    worker = FakeCampaignWorker(truth)
    actions, _, _ = _actions(truth, worker=worker)

    outcome = actions.handoff_provider(
        _context(AcquisitionRuntimeStage.PROVIDER_HANDOFF, allow_provider=True)
    )

    assert outcome.disposition is KivouDomainDisposition.BLOCKED
    assert worker.calls == []


def test_provider_handoff_refuses_duplicate_required_operations() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001", member_ref="member-qa-001"
    )
    truth.operations = tuple(
        ProviderOperationTruth(
            operation_ref=f"operation-{index}",
            kind=kind,
            state=ProviderOperationState.CONFIRMED,
        )
        for index, kind in enumerate(
            (
                ProviderOperationKind.CREATE_CAMPAIGN,
                ProviderOperationKind.CONFIGURE_CAMPAIGN,
                ProviderOperationKind.ADD_LEAD,
                ProviderOperationKind.ADD_LEAD,
            )
        )
    )
    actions, worker, _ = _actions(truth)

    outcome = actions.handoff_provider(
        _context(AcquisitionRuntimeStage.PROVIDER_HANDOFF, allow_provider=True)
    )

    assert outcome.disposition is KivouDomainDisposition.BLOCKED
    assert outcome.reason_codes == ("PROVIDER_OPERATION_SET_UNSAFE",)
    assert worker.calls == []


def test_confirmed_provider_operations_require_the_exact_qa_transport_binding() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        campaign_ref="campaign-qa-001",
        decision=Decision.SEND,
    )
    truth.current_campaign = CampaignTruth(
        campaign_ref="campaign-qa-001",
        member_ref="member-qa-001",
        transport_recipient_identity="8" * 64,
        transport_recipient_key_version="stale-key-v1",
    )
    truth.operations = tuple(
        ProviderOperationTruth(
            operation_ref=f"operation-{kind.value.lower()}",
            kind=kind,
            state=ProviderOperationState.CONFIRMED,
        )
        for kind in (
            ProviderOperationKind.CREATE_CAMPAIGN,
            ProviderOperationKind.CONFIGURE_CAMPAIGN,
            ProviderOperationKind.ADD_LEAD,
        )
    )
    actions, worker, _ = _actions(truth)

    outcome = actions.handoff_provider(
        _context(AcquisitionRuntimeStage.PROVIDER_HANDOFF, allow_provider=True)
    )

    assert outcome.disposition is KivouDomainDisposition.BLOCKED
    assert outcome.reason_codes == ("QA_TRANSPORT_BINDING_MISMATCH",)
    assert worker.calls == []


def _truth_database():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    statements = (
        (
            "CREATE TABLE acquisition_opportunity ("
            "acquisition_opportunity_id TEXT PRIMARY KEY, signal_ref TEXT, state TEXT, "
            "supplier_ref TEXT, contact_ref TEXT, campaign_ref TEXT, decision TEXT)"
        ),
        (
            "CREATE TABLE acquisition_company_profile ("
            "acquisition_opportunity_id TEXT PRIMARY KEY, prebuild_fingerprint TEXT)"
        ),
        (
            "CREATE TABLE acquisition_decision_evaluation ("
            "decision_evaluation_id TEXT PRIMARY KEY, acquisition_opportunity_id TEXT, "
            "proposed_decision TEXT, disposition TEXT, policy_status TEXT, "
            "created_at DATETIME)"
        ),
        (
            "CREATE TABLE acquisition_personalization_artifact ("
            "personalization_artifact_id TEXT PRIMARY KEY, "
            "acquisition_opportunity_id TEXT, disposition TEXT, policy_status TEXT, "
            "created_at DATETIME)"
        ),
        (
            "CREATE TABLE acquisition_compliance_assessment ("
            "compliance_assessment_id TEXT PRIMARY KEY, acquisition_opportunity_id TEXT, "
            "disposition TEXT, state TEXT, created_at DATETIME)"
        ),
        (
            "CREATE TABLE acquisition_campaign_member ("
            "member_ref TEXT PRIMARY KEY, campaign_ref TEXT, "
            "acquisition_opportunity_id TEXT, transport_recipient_identity TEXT, "
            "transport_recipient_key_version TEXT, created_at DATETIME)"
        ),
        (
            "CREATE TABLE acquisition_provider_operation ("
            "operation_ref TEXT PRIMARY KEY, kind TEXT, state TEXT, campaign_ref TEXT, "
            "member_ref TEXT, desired_request_fingerprint TEXT, retry_after DATETIME, "
            "created_at DATETIME)"
        ),
        (
            "CREATE TABLE acquisition_response_evaluation ("
            "response_evaluation_id TEXT PRIMARY KEY, acquisition_opportunity_id TEXT, "
            "campaign_ref TEXT, member_ref TEXT, classification TEXT, "
            "processing_state TEXT, finalized_at DATETIME)"
        ),
        (
            "CREATE TABLE acquisition_conversion_journey ("
            "journey_ref TEXT PRIMARY KEY, acquisition_opportunity_id TEXT, "
            "campaign_ref TEXT, member_ref TEXT, created_at DATETIME)"
        ),
        (
            "CREATE TABLE acquisition_conversion_event ("
            "conversion_event_ref TEXT PRIMARY KEY, journey_ref TEXT, "
            "acquisition_opportunity_id TEXT, campaign_ref TEXT, member_ref TEXT, "
            "recorded_at DATETIME)"
        ),
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(sa.text(statement))
    return engine


def test_sql_truth_reads_only_current_durable_domain_refs() -> None:
    engine = _truth_database()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_opportunity VALUES "
                "('opp-1', 'procurement-opportunity:signal-qa-001', 'SEND', "
                "'supplier-1', 'contact-1', 'campaign-1', 'SEND')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_company_profile VALUES ('opp-1', 'p' || hex(randomblob(32)))"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_decision_evaluation VALUES "
                "('decision-1', 'opp-1', 'SEND', 'RECORDED', 'APPROVED', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_personalization_artifact VALUES "
                "('personalization-1', 'opp-1', 'READY', 'APPROVED', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_compliance_assessment VALUES "
                "('compliance-1', 'opp-1', 'RECORDED', 'ALLOWED', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_campaign_member VALUES "
                "('member-1', 'campaign-1', 'opp-1', :identity, :version, :now)"
            ),
            {
                "identity": QA_TRANSPORT_IDENTITY,
                "version": QA_TRANSPORT_KEY_VERSION,
                "now": NOW,
            },
        )
        for index, kind in enumerate(
            (
                ProviderOperationKind.CREATE_CAMPAIGN,
                ProviderOperationKind.CONFIGURE_CAMPAIGN,
                ProviderOperationKind.ADD_LEAD,
            )
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO acquisition_provider_operation VALUES "
                    "(:ref, :kind, 'CONFIRMED', 'campaign-1', :member, :fingerprint, "
                    "NULL, :now)"
                ),
                {
                    "ref": f"operation-{index}",
                    "kind": kind.value,
                    "member": "member-1" if kind is ProviderOperationKind.ADD_LEAD else None,
                    "fingerprint": f"{index}" * 64,
                    "now": NOW,
                },
            )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_response_evaluation VALUES "
                "('response-1', 'opp-1', 'campaign-1', 'member-1', "
                "'POSITIVE', 'FINALIZED', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_response_evaluation VALUES "
                "('response-stale', 'opp-1', 'campaign-stale', 'member-stale', "
                "'POSITIVE', 'FINALIZED', :later)"
            ),
            {"later": NOW + dt.timedelta(minutes=1)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_conversion_journey VALUES "
                "('journey-1', 'opp-1', 'campaign-1', 'member-1', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_conversion_journey VALUES "
                "('journey-stale', 'opp-1', 'campaign-stale', 'member-stale', :later)"
            ),
            {"later": NOW + dt.timedelta(minutes=1)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_conversion_event VALUES "
                "('conversion-1', 'journey-1', 'opp-1', 'campaign-1', "
                "'member-1', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_conversion_event VALUES "
                "('conversion-stale-binding', 'journey-1', 'opp-1', "
                "'campaign-stale', 'member-stale', :later)"
            ),
            {"later": NOW + dt.timedelta(minutes=1)},
        )
    truth = SqlAcquisitionDomainTruth(
        engine,
        seed_resolver=lambda _engine, _key: SimpleNamespace(
            public_evidence_refs=("event-1", "award-1")
        ),
    )

    opportunity = truth.opportunity("signal-qa-001")

    assert opportunity == OpportunityTruth(
        opportunity_id="opp-1",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        campaign_ref="campaign-1",
        decision=Decision.SEND,
    )
    assert truth.resolve_seed("signal-qa-001") == ("event-1", "award-1")
    assert truth.company_profile_ref("opp-1") is not None
    assert truth.decision("opp-1") == DecisionTruth("decision-1", Decision.SEND)
    assert truth.personalization("opp-1") == PersonalizationTruth(
        "personalization-1", PersonalizationDisposition.READY
    )
    assert truth.compliance("opp-1") == ComplianceTruth(
        "compliance-1", ComplianceDisposition.RECORDED, "ALLOWED"
    )
    campaign = CampaignTruth(
        "campaign-1",
        "member-1",
        QA_TRANSPORT_IDENTITY,
        QA_TRANSPORT_KEY_VERSION,
    )
    assert truth.campaign("opp-1") == campaign
    assert [item.kind for item in truth.provider_operations("campaign-1", "member-1")] == [
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ]
    assert truth.response("opp-1", campaign) == ResponseTruth("response-1", "POSITIVE")
    assert truth.conversion_refs("opp-1", campaign) == (
        "journey-1",
        "conversion-1",
    )


def test_sql_truth_refuses_ambiguous_opportunities_or_campaign_members() -> None:
    engine = _truth_database()
    with engine.begin() as connection:
        for identifier in ("opp-1", "opp-2"):
            connection.execute(
                sa.text(
                    "INSERT INTO acquisition_opportunity VALUES "
                    "(:identifier, 'procurement-opportunity:signal-qa-001', "
                    "'ENRICHING', 'supplier-1', NULL, NULL, NULL)"
                ),
                {"identifier": identifier},
            )
    truth = SqlAcquisitionDomainTruth(
        engine,
        seed_resolver=lambda _engine, _key: SimpleNamespace(public_evidence_refs=()),
    )

    with pytest.raises(DomainAmbiguousFailure):
        truth.opportunity("signal-qa-001")


def test_domain_actions_translate_ambiguous_durable_truth_to_blocked() -> None:
    truth = FakeTruth()

    def ambiguous(_key: str):
        raise DomainAmbiguousFailure("private persistence detail")

    truth.opportunity = ambiguous
    actions, _, _ = _actions(truth)

    outcome = actions.discover_contact(_context(AcquisitionRuntimeStage.CONTACT_DISCOVERY))

    assert outcome.disposition is KivouDomainDisposition.BLOCKED
    assert outcome.reason_codes == ("DOMAIN_TRUTH_AMBIGUOUS",)
    assert "private" not in repr(outcome)


def test_missing_public_seed_is_a_bounded_blocked_disposition() -> None:
    engine = _truth_database()

    def missing(_engine, key: str):
        raise AcquisitionSeedNotFound(key)

    truth = SqlAcquisitionDomainTruth(engine, seed_resolver=missing)
    actions, _, _ = _actions(FakeTruth())
    actions._truth = truth

    outcome = actions.resolve_signal_seed(_context(AcquisitionRuntimeStage.SIGNAL_SEED))

    assert outcome.disposition is KivouDomainDisposition.BLOCKED
    assert outcome.reason_codes == ("SIGNAL_SEED_NOT_FOUND",)


def test_supplier_need_becoming_non_actionable_is_suppressed() -> None:
    truth = FakeTruth()
    actions, _, _ = _actions(truth)

    def not_actionable(*args, **kwargs):
        raise SupplierSearchNotActionable

    actions._supplier = SimpleNamespace(
        resume_started=lambda *args, **kwargs: None,
        discover=not_actionable,
    )

    outcome = actions.discover_supplier(_context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY))

    assert outcome.disposition is KivouDomainDisposition.SUPPRESSED
    assert outcome.reason_codes == ("SUPPLIER_NEED_NOT_ACTIONABLE",)


def test_personalization_eligibility_loss_is_suppressed() -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        decision=Decision.SEND,
    )
    actions, _, _ = _actions(truth)

    def not_eligible(*args, **kwargs):
        raise PersonalizationDecisionNoLongerEligible

    actions._personalization = SimpleNamespace(personalize=not_eligible)

    outcome = actions.personalize(_context(AcquisitionRuntimeStage.PERSONALIZATION))

    assert outcome.disposition is KivouDomainDisposition.SUPPRESSED
    assert outcome.reason_codes == ("PERSONALIZATION_NO_LONGER_ELIGIBLE",)


@pytest.mark.parametrize(
    ("error", "expected", "reason"),
    (
        (
            CampaignPacingExceeded("qa cap"),
            KivouDomainDisposition.WAITING,
            "CAMPAIGN_PACING_LIMIT_REACHED",
        ),
        (
            CampaignDeploymentBlocked("qa safety"),
            KivouDomainDisposition.BLOCKED,
            "CAMPAIGN_DEPLOYMENT_BLOCKED",
        ),
    ),
)
def test_campaign_control_conditions_have_bounded_dispositions(
    error: RuntimeError,
    expected: KivouDomainDisposition,
    reason: str,
) -> None:
    truth = FakeTruth()
    truth.current_opportunity = OpportunityTruth(
        opportunity_id="opportunity-qa-001",
        state=AcquisitionState.SEND,
        supplier_ref="supplier-qa-001",
        contact_ref="contact-qa-001",
        decision=Decision.SEND,
    )
    actions, _, _ = _actions(truth)

    def reject(*args, **kwargs):
        raise error

    actions._campaign = SimpleNamespace(schedule=reject)

    outcome = actions.plan_campaign(_context(AcquisitionRuntimeStage.CAMPAIGN))

    assert outcome.disposition is expected
    assert outcome.reason_codes == (reason,)
