from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from test_policy_persistence import control

from signals.acquisition_runtime.authorization import (
    AcquisitionRuntimeApprovalStore,
    RuntimeApprovalStatus,
)
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeProposal,
    RuntimeStageSnapshot,
)
from signals.acquisition_runtime.domain import (
    DomainApprovalRequired,
    deterministic_attempt_identity,
)
from signals.acquisition_runtime.registry import AcquisitionActionContext
from signals.acquisition_runtime.runtime_policy import (
    DurableRuntimeApprovalProvider,
    LiveRuntimePolicyAuthorizationFactory,
)
from signals.company_research.contracts import CompanyResearchAuthorizationInput
from signals.contact_discovery.contracts import ContactAuthorizationInput
from signals.persistence.database import create_database_engine
from signals.persistence.schema import (
    METADATA,
    acquisition_opportunity,
    acquisition_policy_snapshot,
    acquisition_runtime_approval,
    acquisition_runtime_cycle,
    policy_evaluation,
)
from signals.policy.contracts import (
    POLICY_VERSION,
    ApprovalPurpose,
    AutonomyMode,
    PolicyDecision,
    PolicyStatus,
)
from signals.policy.store import PolicyStore, decision_values
from signals.supplier_discovery.contracts import DiscoveryAuthorizationInput

NOW = dt.datetime(2026, 8, 25, 14, tzinfo=dt.UTC)
OPPORTUNITY_ID = "opportunity-qa-001"


def _engine(*, allowed_countries: tuple[str, ...] = ("CH",)) -> sa.Engine:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    METADATA.create_all(
        engine,
        tables=[
            acquisition_opportunity,
            acquisition_policy_snapshot,
            policy_evaluation,
            acquisition_runtime_cycle,
            acquisition_runtime_approval,
        ],
    )
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=AutonomyMode.ASSISTED,
            allowed_countries=allowed_countries,
            allowed_commands=tuple(stage.command for stage in AcquisitionRuntimeStage),
            effective_at=NOW - dt.timedelta(hours=1),
        )
    )
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


def test_live_factory_fails_closed_when_policy_scope_is_ambiguous() -> None:
    engine = _engine(allowed_countries=("CH", "FR"))
    context = _context(AcquisitionRuntimeStage.SUPPLIER_DISCOVERY)

    with pytest.raises(RuntimeError, match="POLICY_SCOPE_NOT_EXACT"):
        LiveRuntimePolicyAuthorizationFactory(
            engine, runtime_revision="runtime-config:001"
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

    with pytest.raises(DomainApprovalRequired, match="HUMAN_APPROVAL_REQUIRED"):
        provider.consume_for(context, opportunity_id=OPPORTUNITY_ID)

    pending = AcquisitionRuntimeApprovalStore(engine).list_approvals()
    assert len(pending) == 1
    assert pending[0].binding.command == "execute_provider_operations"
    assert pending[0].binding.action_fingerprint == context.proposal.argument_fingerprint
    assert pending[0].binding.target_ref == (
        f"acquisition-opportunity:{OPPORTUNITY_ID}"
    )
    engine.dispose()
