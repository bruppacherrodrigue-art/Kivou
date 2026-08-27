from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from test_policy_gateway import request
from test_policy_persistence import control

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_runtime.authorization import (
    AcquisitionRuntimeApprovalStore,
    RuntimeApprovalStatus,
)
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeDependencyState,
    RuntimeProposal,
    RuntimeQaScope,
    RuntimeStageDependency,
    RuntimeStageSnapshot,
)
from signals.acquisition_runtime.domain import (
    DomainApprovalRequired,
    DomainPolicyRevalidationBlocked,
    deterministic_attempt_identity,
)
from signals.acquisition_runtime.registry import AcquisitionActionContext
from signals.acquisition_runtime.runtime_policy import (
    DurableRuntimeApprovalProvider,
    LiveRuntimePolicyAuthorizationFactory,
    SqlRuntimePolicyReadinessSource,
)
from signals.company_research.contracts import CompanyResearchAuthorizationInput
from signals.contact_discovery.contracts import ContactAuthorizationInput
from signals.persistence.database import create_database_engine
from signals.persistence.schema import (
    METADATA,
    acquisition_event,
    acquisition_opportunity,
    acquisition_policy_snapshot,
    acquisition_runtime_approval,
    acquisition_runtime_cycle,
    acquisition_runtime_stage,
    policy_evaluation,
)
from signals.policy.contracts import (
    POLICY_VERSION,
    ApprovalPurpose,
    AutonomyMode,
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    PolicyDecision,
    PolicyStatus,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore, decision_values
from signals.supplier_discovery.contracts import DiscoveryAuthorizationInput

NOW = dt.datetime(2026, 8, 25, 14, tzinfo=dt.UTC)
OPPORTUNITY_ID = "opportunity-qa-001"
QA_SCOPE = RuntimeQaScope(country="CH", language="fr", wedge="construction")


class ReadyPolicyInputs:
    def evidence(self, context, *, required_claims, observed_at):
        del context
        return EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=required_claims,
            assessment_version="tested-durable-evidence-v1",
            observed_at=observed_at,
        )

    def operational(
        self,
        context,
        *,
        control,
        runtime_revision,
        observed_at,
    ):
        del context, control, observed_at
        return OperationalReadiness(runtime_revision=runtime_revision)


def _engine(
    *,
    allowed_countries: tuple[str, ...] = ("CH",),
    control_overrides: dict[str, object] | None = None,
) -> sa.Engine:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    METADATA.create_all(
        engine,
        tables=[
            acquisition_event,
            acquisition_opportunity,
            acquisition_policy_snapshot,
            policy_evaluation,
            acquisition_runtime_cycle,
            acquisition_runtime_stage,
            acquisition_runtime_approval,
        ],
    )
    overrides: dict[str, object] = {
        "autonomy_mode": AutonomyMode.ASSISTED,
        "allowed_countries": allowed_countries,
        "allowed_commands": tuple(stage.command for stage in AcquisitionRuntimeStage),
        "effective_at": NOW - dt.timedelta(hours=1),
        "qa_signal_ref": "procurement-opportunity:signal-qa-001",
    }
    overrides.update(control_overrides or {})
    PolicyStore(engine).append_control(control(1, **overrides))
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_opportunity).values(
                acquisition_opportunity_id=OPPORTUNITY_ID,
                identity_key="runtime-test-opportunity",
                state="SEND",
                stream_version=1,
                state_machine_version="acquisition-state-machine-v1",
                signal_ref="procurement-opportunity:signal-qa-001",
                supplier_ref=None,
                contact_ref=None,
                campaign_ref=None,
                decision="SEND",
                reason_codes=[],
                confidence=None,
                evidence_refs=[],
                next_action="prepare_campaign",
                next_review_at=None,
                retry_count=0,
                retry_at=None,
                last_error_category=None,
                policy_version=None,
                skill_version=None,
                supervisor_version=None,
                estimated_cost=None,
                last_event_id="event-runtime-test",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.insert(acquisition_runtime_cycle).values(
                cycle_ref="cycle-qa-001",
                opportunity_key="signal-qa-001",
                config_fingerprint="f" * 64,
                status="RUNNING",
                next_stage=AcquisitionRuntimeStage.PERSONALIZATION.value,
                spent_cost=Decimal("0"),
                last_reason_code=None,
                started_at=NOW,
                updated_at=NOW,
                completed_at=None,
            )
        )
    return engine


def _context(
    stage: AcquisitionRuntimeStage,
    *,
    attempt: int = 1,
    at: dt.datetime = NOW,
) -> AcquisitionActionContext:
    cycle = RuntimeCycleSnapshot(
        cycle_ref="cycle-qa-001",
        opportunity_key="signal-qa-001",
        status=RuntimeCycleStatus.RUNNING,
        next_stage=stage,
        spent_cost=Decimal("0"),
        started_at=NOW,
    )
    return AcquisitionActionContext(
        stage=stage,
        proposal=RuntimeProposal(
            plan_ref=f"plan-{stage.value.lower()}",
            action_index=0,
            command=stage.command,
            target_ref=cycle.cycle_ref,
            argument_fingerprint="a" * 64,
            estimated_cost=Decimal("0"),
            reason_codes=("QA_TEST",),
        ),
        cycle=cycle,
        stage_snapshot=RuntimeStageSnapshot(
            cycle_ref=cycle.cycle_ref,
            stage=stage,
            status="RUNNING",
            attempt_count=attempt,
        ),
        allow_qa_provider_mutations=True,
        guard=object(),
        at=at,
    )


def _record_approval_required(
    engine: sa.Engine,
    *,
    stage: AcquisitionRuntimeStage,
    action_fingerprint: str = "c" * 64,
) -> None:
    decision = PolicyDecision(
        evaluation_id="previous-policy-evaluation",
        request_id="previous-policy-request",
        status=PolicyStatus.APPROVAL_REQUIRED,
        executable=False,
        command=stage.command,
        target_ref=f"acquisition-opportunity:{OPPORTUNITY_ID}",
        acquisition_opportunity_id=OPPORTUNITY_ID,
        action_fingerprint=action_fingerprint,
        reason_codes=("action_approval_required",),
        policy_version=POLICY_VERSION,
        policy_snapshot_id="snapshot-1",
        control_revision=1,
        runtime_revision="acquisition-runtime-v1",
        evaluated_at=NOW,
        requires_revalidation=True,
        currency="CHF",
        estimated_cost=Decimal("0"),
        proposed_volume=0,
        cost_remaining=Decimal("100"),
        volume_remaining=100,
    )
    with engine.begin() as connection:
        connection.execute(
            sa.insert(policy_evaluation).values(
                decision_values(decision, semantic_fingerprint="d" * 64)
            )
        )


def test_live_factory_builds_native_authorizations_from_current_policy() -> None:
    engine = _engine()
    factory = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision="runtime-config:001",
        qa_signal_ref="procurement-opportunity:signal-qa-001",
        qa_scope=QA_SCOPE,
        readiness=ReadyPolicyInputs(),
    )
    supplier_context = _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY)
    supplier_identity = deterministic_attempt_identity(
        supplier_context.stage_snapshot
    )

    supplier = factory.supplier(supplier_context, supplier_identity, ())
    contact_context = _context(AcquisitionRuntimeStage.CONTACT_DISCOVERY)
    contact = factory.contact(
        contact_context,
        deterministic_attempt_identity(contact_context.stage_snapshot),
        (),
        opportunity_id=OPPORTUNITY_ID,
    )
    company_context = _context(AcquisitionRuntimeStage.COMPANY_RESEARCH)
    company = factory.company(
        company_context,
        deterministic_attempt_identity(company_context.stage_snapshot),
        (),
        opportunity_id=OPPORTUNITY_ID,
    )

    assert isinstance(supplier.authorization, DiscoveryAuthorizationInput)
    assert isinstance(contact.authorization, ContactAuthorizationInput)
    assert isinstance(company.authorization, CompanyResearchAuthorizationInput)
    assert supplier.authorization.evaluation_id == supplier_identity.evaluation_id
    assert supplier.authorization.scope.model_dump() == {
        "country": "CH",
        "language": "fr",
        "wedge": "construction",
    }
    assert supplier.authorization.actor_type == "HERMES"
    assert supplier.authorization.qa_signal_ref == (
        "procurement-opportunity:signal-qa-001"
    )
    assert supplier.authorization.supervisor_plan_id == supplier_context.proposal.plan_ref
    assert supplier.authorization.expected_policy_version == POLICY_VERSION
    assert supplier.authorization.operational.runtime_revision == "runtime-config:001"
    assert supplier.authorization.evidence.status.value == "READY"
    assert set(supplier.authorization.evidence.claims) == {
        "PUBLIC_OPPORTUNITY",
        "PUBLIC_EVIDENCE",
        "SUPPLIER_SEARCH_PROFILE",
    }
    assert supplier.budget_usage.cost_used == Decimal("0")
    engine.dispose()


def test_live_factory_recovers_one_cycle_after_eighteen_chf_durable_cost(
) -> None:
    engine = _engine(
        control_overrides={
            "daily_cost_cap": Decimal("30"),
            "daily_volume_cap": 1,
        }
    )
    factory = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision="runtime-config:001",
        qa_signal_ref="procurement-opportunity:signal-qa-001",
        qa_scope=QA_SCOPE,
        readiness=ReadyPolicyInputs(),
    )
    gateway = PolicyGateway(engine)
    acquisition = AcquisitionStore(engine)

    def evaluate(
        active_factory: LiveRuntimePolicyAuthorizationFactory,
        stage: AcquisitionRuntimeStage,
        *,
        attempt: int,
    ):
        context = _context(stage, attempt=attempt)
        identity = deterministic_attempt_identity(context.stage_snapshot)
        if stage is AcquisitionRuntimeStage.SUPPLIER_DISCOVERY:
            call = active_factory.supplier(context, identity, ())
            target_ref = "procurement-opportunity:signal-qa-001"
            opportunity_id = None
            expected_version = None
        elif stage is AcquisitionRuntimeStage.CONTACT_DISCOVERY:
            call = active_factory.contact(
                context,
                identity,
                (),
                opportunity_id=OPPORTUNITY_ID,
            )
            target_ref = f"acquisition-opportunity:{OPPORTUNITY_ID}"
            opportunity_id = OPPORTUNITY_ID
            expected_version = acquisition.get_opportunity(
                OPPORTUNITY_ID
            ).stream_version
        else:
            assert stage is AcquisitionRuntimeStage.COMPANY_RESEARCH
            call = active_factory.company(
                context,
                identity,
                (),
                opportunity_id=OPPORTUNITY_ID,
            )
            target_ref = f"acquisition-opportunity:{OPPORTUNITY_ID}"
            opportunity_id = OPPORTUNITY_ID
            expected_version = acquisition.get_opportunity(
                OPPORTUNITY_ID
            ).stream_version
        policy_request = request(
            stage.command,
            **call.authorization.model_dump(mode="python"),
            target_ref=target_ref,
            acquisition_opportunity_id=opportunity_id,
            expected_opportunity_version=expected_version,
            action_fingerprint=context.proposal.argument_fingerprint,
            proposed_volume=0,
        )
        return call.budget_usage, gateway.evaluate_and_record(
            policy_request,
            evaluated_at=NOW,
            budget_usage=call.budget_usage,
        )

    prior_decisions = [
        evaluate(factory, AcquisitionRuntimeStage.SUPPLIER_DISCOVERY, attempt=1)[1],
        evaluate(factory, AcquisitionRuntimeStage.SUPPLIER_DISCOVERY, attempt=2)[1],
        evaluate(factory, AcquisitionRuntimeStage.CONTACT_DISCOVERY, attempt=1)[1],
        evaluate(factory, AcquisitionRuntimeStage.CONTACT_DISCOVERY, attempt=2)[1],
        evaluate(factory, AcquisitionRuntimeStage.COMPANY_RESEARCH, attempt=1)[1],
    ]

    def executable_cost() -> Decimal:
        with engine.connect() as connection:
            value = connection.scalar(
                sa.select(sa.func.sum(policy_evaluation.c.estimated_cost)).where(
                    policy_evaluation.c.executable.is_(True)
                )
            )
        return Decimal(value)

    assert all(decision.executable for decision in prior_decisions)
    assert executable_cost() == Decimal("18")

    recovered_factory = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision="runtime-config:001",
        qa_signal_ref="procurement-opportunity:signal-qa-001",
        qa_scope=QA_SCOPE,
        readiness=ReadyPolicyInputs(),
    )
    supplier_usage, supplier = evaluate(
        recovered_factory,
        AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
        attempt=3,
    )
    contact_usage, contact = evaluate(
        recovered_factory,
        AcquisitionRuntimeStage.CONTACT_DISCOVERY,
        attempt=3,
    )
    company_usage, company = evaluate(
        recovered_factory,
        AcquisitionRuntimeStage.COMPANY_RESEARCH,
        attempt=2,
    )
    over_cap_usage, over_cap = evaluate(
        recovered_factory,
        AcquisitionRuntimeStage.CONTACT_DISCOVERY,
        attempt=4,
    )

    assert [
        supplier.estimated_cost,
        contact.estimated_cost,
        company.estimated_cost,
    ] == [Decimal("2"), Decimal("6"), Decimal("2")]
    assert [
        supplier_usage.cost_used,
        contact_usage.cost_used,
        company_usage.cost_used,
    ] == [Decimal("18"), Decimal("20"), Decimal("26")]
    assert all(decision.executable for decision in (supplier, contact, company))
    assert [
        supplier.cost_remaining,
        contact.cost_remaining,
        company.cost_remaining,
    ] == [Decimal("12"), Decimal("10"), Decimal("4")]
    assert [
        supplier.volume_remaining,
        contact.volume_remaining,
        company.volume_remaining,
    ] == [1, 1, 1]
    assert over_cap_usage.cost_used == Decimal("28")
    assert over_cap.status is PolicyStatus.BUDGET_EXCEEDED
    assert over_cap.executable is False
    assert over_cap.cost_remaining == Decimal("2")
    assert over_cap.volume_remaining == 1
    assert "daily_cost_cap_exceeded" in over_cap.reason_codes
    assert executable_cost() == Decimal("28")
    engine.dispose()


def test_provider_recovery_revalidates_current_exact_qa_policy_authority() -> None:
    engine = _engine()
    factory = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision="runtime-config:001",
        qa_signal_ref="procurement-opportunity:signal-qa-001",
        qa_scope=QA_SCOPE,
    )

    factory.revalidate_provider_recovery(
        _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY),
        opportunity_id=None,
    )

    engine.dispose()


@pytest.mark.parametrize(
    "control_overrides",
    [
        {"kill_switch": True},
        {"read_only": True},
        {
            "autonomy_mode": AutonomyMode.SHADOW,
            "shadow_target_mode": AutonomyMode.ASSISTED,
        },
        {"qa_signal_ref": "procurement-opportunity:another-signal"},
        {"allowed_commands": ("enrich_company",)},
        {"allowed_countries": ("FR",)},
        {"allowed_languages": ("en",)},
        {"allowed_wedges": ("software",)},
        {"expires_at": NOW - dt.timedelta(seconds=1)},
    ],
)
def test_provider_recovery_fails_closed_when_current_qa_policy_is_not_exact(
    control_overrides: dict[str, object],
) -> None:
    engine = _engine(control_overrides=control_overrides)
    factory = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision="runtime-config:001",
        qa_signal_ref="procurement-opportunity:signal-qa-001",
        qa_scope=QA_SCOPE,
    )

    with pytest.raises(DomainPolicyRevalidationBlocked):
        factory.revalidate_provider_recovery(
            _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY),
            opportunity_id=None,
        )

    engine.dispose()


def test_live_factory_defaults_to_unknown_evidence_and_operational_readiness() -> None:
    engine = _engine()
    context = _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY)

    authorization = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision="runtime-config:001",
        qa_signal_ref="procurement-opportunity:signal-qa-001",
        qa_scope=QA_SCOPE,
    ).supplier(context, deterministic_attempt_identity(context.stage_snapshot), ())

    assert authorization.authorization.evidence.status is EvidenceStatus.UNKNOWN
    assert authorization.authorization.evidence.claims == ()
    assert authorization.authorization.operational.provider_quota.value == "UNKNOWN"
    assert authorization.authorization.operational.mailbox_quota.value == "UNKNOWN"
    assert authorization.authorization.operational.send_window.value == "UNKNOWN"
    assert (
        authorization.authorization.operational.provider_control_plane.value
        == "UNKNOWN"
    )
    engine.dispose()


def test_sql_readiness_requires_durable_stage_truth_and_live_dependency_probes() -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_runtime_stage).values(
                cycle_ref="cycle-qa-001",
                stage=AcquisitionRuntimeStage.SIGNAL_SEED.value,
                status="SUCCEEDED",
                attempt_count=1,
                plan_ref="plan-signal-seed",
                command=AcquisitionRuntimeStage.SIGNAL_SEED.command,
                argument_fingerprint="a" * 64,
                result_refs=["public-evidence-001"],
                reserved_cost=Decimal("0"),
                observed_cost=Decimal("0"),
                reason_codes=[],
                retry_at=None,
                replay_same_attempt=False,
                started_at=NOW,
                completed_at=NOW,
                updated_at=NOW,
            )
        )
    dependencies = tuple(
        RuntimeStageDependency(
            stage=stage,
            status=RuntimeDependencyState.READY,
        )
        for stage in AcquisitionRuntimeStage
    )
    source = SqlRuntimePolicyReadinessSource(
        engine,
        dependencies=dependencies,
    )
    context = _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY)

    evidence = source.evidence(
        context,
        required_claims=("PUBLIC_OPPORTUNITY",),
        observed_at=NOW,
    )
    operational = source.operational(
        context,
        control=PolicyStore(engine).get_effective_control(NOW),
        runtime_revision="runtime-config:001",
        observed_at=NOW,
    )

    assert evidence.status is EvidenceStatus.READY
    assert evidence.claims == ("PUBLIC_OPPORTUNITY",)
    assert operational.provider_quota.value == "READY"
    assert operational.mailbox_quota.value == "UNKNOWN"
    engine.dispose()


def test_sql_readiness_keeps_mailbox_quota_and_kill_switch_fail_closed() -> None:
    engine = _engine()
    dependencies = tuple(
        RuntimeStageDependency(
            stage=stage,
            status=(
                RuntimeDependencyState.NOT_READY
                if stage is AcquisitionRuntimeStage.CAMPAIGN
                else RuntimeDependencyState.READY
            ),
            reason_codes=(
                ("MAILBOX_DEPENDENCY_NOT_READY",)
                if stage is AcquisitionRuntimeStage.CAMPAIGN
                else ()
            ),
        )
        for stage in AcquisitionRuntimeStage
    )
    source = SqlRuntimePolicyReadinessSource(
        engine,
        dependencies=dependencies,
    )
    control_snapshot = PolicyStore(engine).get_effective_control(NOW)

    mailbox = source.operational(
        _context(AcquisitionRuntimeStage.CAMPAIGN),
        control=control_snapshot,
        runtime_revision="runtime-config:001",
        observed_at=NOW,
    )
    killed = source.operational(
        _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY),
        control=control_snapshot.model_copy(update={"kill_switch": True}),
        runtime_revision="runtime-config:001",
        observed_at=NOW,
    )

    assert mailbox.provider_quota.value == "UNKNOWN"
    assert mailbox.mailbox_quota.value == "UNKNOWN"
    assert mailbox.send_window.value == "UNKNOWN"
    assert killed.provider_quota.value == "UNKNOWN"
    assert killed.provider_control_plane.value == "UNKNOWN"
    engine.dispose()


def test_live_factory_fails_closed_when_policy_scope_is_ambiguous() -> None:
    engine = _engine(allowed_countries=("CH", "FR"))
    context = _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY)

    with pytest.raises(RuntimeError, match="POLICY_SCOPE_NOT_EXACT"):
        LiveRuntimePolicyAuthorizationFactory(
            engine,
            runtime_revision="runtime-config:001",
            qa_signal_ref="procurement-opportunity:signal-qa-001",
            qa_scope=QA_SCOPE,
        ).supplier(context, deterministic_attempt_identity(context.stage_snapshot), ())
    engine.dispose()


def test_missing_review_creates_exact_pending_then_consumes_only_approved_grant() -> None:
    engine = _engine()
    stage = AcquisitionRuntimeStage.PERSONALIZATION
    _record_approval_required(engine, stage=stage)
    store = AcquisitionRuntimeApprovalStore(engine)
    provider = DurableRuntimeApprovalProvider(engine, approval_ttl_seconds=1800)

    with pytest.raises(DomainApprovalRequired, match="HUMAN_APPROVAL_REQUIRED"):
        provider.consume_for(_context(stage), opportunity_id=OPPORTUNITY_ID)

    pending = store.list_approvals()
    assert len(pending) == 1
    assert pending[0].status is RuntimeApprovalStatus.PENDING
    assert pending[0].binding.purpose is ApprovalPurpose.ACTION
    assert pending[0].binding.command == stage.command
    assert pending[0].binding.target_ref == (
        f"acquisition-opportunity:{OPPORTUNITY_ID}"
    )
    assert pending[0].binding.action_fingerprint == "c" * 64
    assert pending[0].binding.scope_fingerprint != "a" * 64
    assert pending[0].approved_by_actor_ref is None

    store.approve(
        pending[0].approval_id,
        approved_by_actor_ref="operator-qa-001",
        at=NOW + dt.timedelta(minutes=1),
    )
    approved_context = _context(
        stage,
        attempt=2,
        at=NOW + dt.timedelta(minutes=2),
    )
    grants = provider.consume_for(
        approved_context,
        opportunity_id=OPPORTUNITY_ID,
    )
    replay = provider.consume_for(
        approved_context,
        opportunity_id=OPPORTUNITY_ID,
    )

    assert len(grants) == 1
    assert replay == grants
    assert grants[0].approval_id == pending[0].approval_id
    assert grants[0].one_shot is True
    assert grants[0].consumed_at is None
    assert grants[0].approved_by_actor_ref == "operator-qa-001"
    assert store.list_approvals()[0].status is RuntimeApprovalStatus.CONSUMED

    with pytest.raises(DomainApprovalRequired, match="HUMAN_APPROVAL_REQUIRED"):
        provider.consume_for(
            _context(stage, attempt=3, at=NOW + dt.timedelta(minutes=3)),
            opportunity_id=OPPORTUNITY_ID,
        )
    assert len(store.list_approvals()) == 2
    engine.dispose()


def test_first_native_review_attempt_does_not_forge_a_grant() -> None:
    engine = _engine()
    provider = DurableRuntimeApprovalProvider(engine, approval_ttl_seconds=1800)

    assert (
        provider.consume_for(
            _context(AcquisitionRuntimeStage.PERSONALIZATION),
            opportunity_id=OPPORTUNITY_ID,
        )
        == ()
    )
    assert AcquisitionRuntimeApprovalStore(engine).list_approvals() == ()
    engine.dispose()


def test_provider_handoff_requires_its_own_durable_one_shot_approval() -> None:
    engine = _engine()
    provider = DurableRuntimeApprovalProvider(engine, approval_ttl_seconds=1800)
    context = _context(AcquisitionRuntimeStage.PROVIDER_HANDOFF)
    provider_binding = "b" * 64

    with pytest.raises(DomainApprovalRequired, match="HUMAN_APPROVAL_REQUIRED"):
        provider.consume_for(
            context,
            opportunity_id=OPPORTUNITY_ID,
            action_fingerprint=provider_binding,
        )

    pending = AcquisitionRuntimeApprovalStore(engine).list_approvals()
    assert len(pending) == 1
    assert pending[0].binding.command == "execute_provider_operations"
    assert pending[0].binding.action_fingerprint == provider_binding
    assert pending[0].binding.action_fingerprint != context.proposal.argument_fingerprint
    assert pending[0].binding.target_ref == (
        f"acquisition-opportunity:{OPPORTUNITY_ID}"
    )
    engine.dispose()
