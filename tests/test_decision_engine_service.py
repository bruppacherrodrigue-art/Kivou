from __future__ import annotations

import datetime as dt
import inspect
import threading
from decimal import Decimal
from enum import Enum

import pytest
import sqlalchemy as sa
from alembic import command
from feed_helpers import MATERIALIZED_AT, MATERIALIZED_ON, simap_award
from test_policy_persistence import control

import signals.policy.gateway as policy_gateway_module
from signals.acquisition.contracts import AcquisitionState, ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.company_research.contracts import ApolloOrganizationObservation
from signals.company_research.prebuild import build_acquisition_prospect_prebuild
from signals.company_research.store import CompanyResearchStore
from signals.contact_discovery.contracts import ContactObservation
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.decision_engine.contracts import (
    AcquisitionDecisionInput,
    DecisionAuditDisposition,
    DecisionAuthorizationInput,
    DecisionEvaluationIdempotencyConflict,
    DecisionEvaluationRequiresFreshAttempt,
    DecisionEvaluationWrite,
    DecisionInputChanged,
    DecisionInputVersionUnsupported,
    DecisionNotActionable,
    DecisionPublicContextNotResolvable,
)
from signals.decision_engine.service import (
    DecisionEngineService,
    _publication_date,
    policy_action_fingerprint,
)
from signals.decision_engine.store import DecisionEvaluationStore, decision_evaluation_id
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import (
    acquisition_company_profile,
    acquisition_decision_evaluation,
    acquisition_event,
    contract_award,
    policy_evaluation,
    source_event,
)
from signals.policy.contracts import (
    POLICY_VERSION,
    AutonomyMode,
    BudgetUsage,
    ComplianceAssessment,
    ComplianceState,
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    Scope,
)
from signals.policy.store import PolicyStore
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate
from signals.supplier_discovery.store import SupplierDiscoveryStore

EVALUATED_AT = dt.datetime(2026, 7, 18, 12, 30, tzinfo=dt.UTC)


class CountingClock:
    def __init__(self, value: dt.datetime = EVALUATED_AT) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> dt.datetime:
        self.calls += 1
        return self.value


@pytest.fixture
def context(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'decision-service.db'}")
    command.upgrade(alembic_config(engine), "head")
    event, awards = simap_award("33112-02")
    IngestionPipeline(engine).process(
        AcquiredPublication(event, awards),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )
    with engine.connect() as connection:
        opportunity_key = connection.scalar(
            sa.text("SELECT opportunity_key FROM opportunity_representation LIMIT 1")
        )

    supplier = SupplierDiscoveryStore(engine, clock=lambda: EVALUATED_AT).upsert_supplier(
        ApolloOrganizationCandidate(
            provider_organization_id="apollo-org-1",
            display_name="Acme SA",
            normalized_name="acme sa",
            provider_observed_at=EVALUATED_AT,
            source_fingerprint="a" * 64,
        )
    ).supplier
    contact = ContactDiscoveryStore(engine, clock=lambda: EVALUATED_AT).upsert_contact(
        ContactObservation(
            supplier_ref=supplier.supplier_ref,
            provider_person_id="person-1",
            provider_organization_id="apollo-org-1",
            title="Sales Director",
            normalized_title="sales director",
            role_tier=1,
            business_email="buyer@acme.example",
            provider_email_status="verified",
            provider_observed_at=EVALUATED_AT,
            email_observed_at=EVALUATED_AT,
            source_fingerprint="b" * 64,
        )
    ).contact
    acquisition = AcquisitionStore(engine, clock=lambda: EVALUATED_AT)
    created = acquisition.create_opportunity(
        identity_key="decision-service-opportunity",
        signal_ref=f"procurement-opportunity:{opportunity_key}",
        supplier_ref=supplier.supplier_ref,
        idempotency_key="decision-service-create",
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    with engine.begin() as connection:
        selected = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.CONTACT_SELECTED,
            expected_version=1,
            idempotency_key="decision-service-contact",
            actor_type=ActorType.SYSTEM,
            payload={"contact_ref": contact.contact_ref, "supplier_ref": supplier.supplier_ref},
        )
        enriching = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.STATE_TRANSITIONED,
            expected_version=selected.projection.stream_version,
            idempotency_key="decision-service-enriching",
            payload={"target_state": "ENRICHING"},
        )
        next_company = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=enriching.projection.stream_version,
            idempotency_key="decision-service-company",
            payload={"next_action": "enrich_company"},
        )
    observation = ApolloOrganizationObservation(
        provider_organization_id="apollo-org-1",
        provider_company_name="Acme SA",
        provider_primary_domain="acme.example",
        provider_country="CH",
        provider_industry="software",
        provider_employee_count=42,
        provider_observed_at=EVALUATED_AT,
        provider_source_fingerprint="c" * 64,
    )
    prebuild = build_acquisition_prospect_prebuild(
        acquisition_opportunity_id=opportunity_id,
        signal_ref=created.projection.signal_ref,
        supplier_ref=supplier.supplier_ref,
        contact_ref=contact.contact_ref,
        supplier_identity_status=supplier.identity_status,
        contact_role_profile_version=contact.role_profile_version,
        contact_role_tier=contact.role_tier,
        observation=observation,
    )
    CompanyResearchStore(engine, clock=lambda: EVALUATED_AT).upsert_profile(prebuild)
    with engine.begin() as connection:
        ready = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.STATE_TRANSITIONED,
            expected_version=next_company.projection.stream_version,
            idempotency_key="decision-service-ready",
            payload={"target_state": "READY_FOR_DECISION"},
        )
        acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=ready.projection.stream_version,
            idempotency_key="decision-service-evaluate",
            payload={"next_action": "evaluate_opportunity"},
        )
    PolicyStore(engine).append_control(
        control(
            1,
            allowed_commands=("evaluate_opportunity",),
            effective_at=EVALUATED_AT - dt.timedelta(days=1),
        )
    )
    return engine, acquisition, opportunity_id


def authorization(evaluation_id: str = "decision-eval-1") -> DecisionAuthorizationInput:
    return DecisionAuthorizationInput(
        evaluation_id=evaluation_id,
        request_id=f"request-{evaluation_id}",
        actor_type="SYSTEM",
        actor_ref="kivou-decision-engine",
        scope=Scope(country="CH", language="fr", wedge="construction"),
        currency="CHF",
        evidence=EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=(
                "PUBLIC_OPPORTUNITY",
                "PUBLIC_EVIDENCE",
                "ACQUISITION_PROSPECT_PREBUILD",
                "VERIFIED_CONTACT",
                "DECISION_INPUT",
            ),
            assessment_version="decision-evidence-v1",
            observed_at=EVALUATED_AT - dt.timedelta(minutes=1),
        ),
        compliance=ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="compliance-unneeded-v1",
            observed_at=EVALUATED_AT - dt.timedelta(minutes=1),
        ),
        operational=OperationalReadiness(runtime_revision="runtime-1"),
        expected_policy_version=POLICY_VERSION,
    )


def test_service_owns_one_authoritative_clock_and_records_send(context) -> None:
    engine, acquisition, opportunity_id = context
    clock = CountingClock()
    service = DecisionEngineService(engine, clock=clock)

    result = service.evaluate(opportunity_id, authorization(), budget_usage=BudgetUsage())

    assert clock.calls == 1
    assert result.decision is not None and result.decision.evaluated_at == EVALUATED_AT
    assert result.audit.as_of_date == dt.date(2026, 7, 18)
    assert result.audit.age_days == 60
    assert result.audit.disposition is DecisionAuditDisposition.RECORDED
    assert result.audit.recorded_event_id is not None
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.SEND
    assert current.next_action == "prepare_campaign"
    assert current.confidence is None


def test_caller_cannot_supply_evaluated_at_or_as_of_date() -> None:
    parameters = inspect.signature(DecisionEngineService.evaluate).parameters
    assert "evaluated_at" not in parameters
    assert "as_of_date" not in parameters
    assert "evaluated_at" not in DecisionAuthorizationInput.model_fields
    assert "as_of_date" not in DecisionAuthorizationInput.model_fields


def test_publication_date_preserves_date_and_converts_aware_datetime_to_utc() -> None:
    source_date = dt.date(2026, 8, 20)
    aware_instant = dt.datetime(
        2026,
        8,
        20,
        0,
        30,
        tzinfo=dt.timezone(dt.timedelta(hours=2)),
    )

    assert _publication_date(source_date) == source_date
    assert _publication_date(aware_instant) == dt.date(2026, 8, 19)


def test_existing_audit_replays_without_clock_policy_or_event(context) -> None:
    engine, acquisition, opportunity_id = context
    first_clock = CountingClock()
    first = DecisionEngineService(engine, clock=first_clock).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    version = acquisition.get_opportunity(opportunity_id).stream_version
    replay_clock = CountingClock(EVALUATED_AT + dt.timedelta(days=5))

    replay = DecisionEngineService(engine, clock=replay_clock).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )

    assert replay.audit == first.audit
    assert replay_clock.calls == 0
    assert acquisition.get_opportunity(opportunity_id).stream_version == version


def test_existing_audit_replay_uses_historical_not_current_budget_usage(context) -> None:
    engine, acquisition, opportunity_id = context
    first = DecisionEngineService(engine, clock=CountingClock()).evaluate(
        opportunity_id,
        authorization(),
        budget_usage=BudgetUsage(cost_used=Decimal("7.50"), volume_used=12),
    )
    version = acquisition.get_opportunity(opportunity_id).stream_version
    replay_clock = CountingClock(EVALUATED_AT + dt.timedelta(days=5))

    replay = DecisionEngineService(engine, clock=replay_clock).evaluate(
        opportunity_id,
        authorization(),
        budget_usage=BudgetUsage(cost_used=Decimal("61.25"), volume_used=73),
    )

    assert replay.audit == first.audit
    assert replay_clock.calls == 0
    assert acquisition.get_opportunity(opportunity_id).stream_version == version
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(policy_evaluation)
        ) == 1
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_event).where(
                acquisition_event.c.event_type == "DECISION_RECORDED"
            )
        ) == 1


def test_completed_audit_with_legacy_decimal_hash_replays_after_r1(
    context, monkeypatch
) -> None:
    engine, acquisition, opportunity_id = context

    def legacy_canonical(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dt.datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {
                str(key): legacy_canonical(nested)
                for key, nested in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [legacy_canonical(nested) for nested in value]
        return value

    with monkeypatch.context() as legacy_runtime:
        legacy_runtime.setattr(policy_gateway_module, "_canonical", legacy_canonical)
        first = DecisionEngineService(engine, clock=CountingClock()).evaluate(
            opportunity_id,
            authorization(),
            budget_usage=BudgetUsage(cost_used=Decimal("7.50"), volume_used=12),
        )

    version = acquisition.get_opportunity(opportunity_id).stream_version
    replay_clock = CountingClock(EVALUATED_AT + dt.timedelta(days=5))
    replay = DecisionEngineService(engine, clock=replay_clock).evaluate(
        opportunity_id,
        authorization(),
        budget_usage=BudgetUsage(cost_used=Decimal("61.25"), volume_used=73),
    )

    assert replay.audit == first.audit
    assert replay_clock.calls == 0
    assert acquisition.get_opportunity(opportunity_id).stream_version == version


def test_naive_publication_datetime_fails_before_policy_or_decision_audit(context) -> None:
    engine, _, opportunity_id = context
    with engine.begin() as connection:
        published = connection.scalar(sa.select(source_event.c.published_at_raw).limit(1))
        assert published is not None
        connection.execute(
            sa.update(source_event).values(
                published_at_raw=f"{published[:10]}T12:00:00",
                published_precision="datetime",
            )
        )

    with pytest.raises(DecisionPublicContextNotResolvable):
        DecisionEngineService(engine, clock=CountingClock()).evaluate(
            opportunity_id,
            authorization(),
            budget_usage=BudgetUsage(),
        )

    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(policy_evaluation)
        ) == 0
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_decision_evaluation)
        ) == 0
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_event).where(
                acquisition_event.c.event_type == "DECISION_RECORDED"
            )
        ) == 0


def test_naive_publication_datetime_after_policy_is_input_changed(context) -> None:
    engine, acquisition, opportunity_id = context
    service = DecisionEngineService(engine, clock=CountingClock())

    def make_publication_naive() -> None:
        with engine.begin() as connection:
            published = connection.scalar(
                sa.select(source_event.c.published_at_raw).limit(1)
            )
            assert published is not None
            connection.execute(
                sa.update(source_event).values(
                    published_at_raw=f"{published[:10]}T12:00:00",
                    published_precision="datetime",
                )
            )

    service._after_policy_hook = make_publication_naive
    with pytest.raises(DecisionInputChanged):
        service.evaluate(
            opportunity_id,
            authorization(),
            budget_usage=BudgetUsage(),
        )

    assert acquisition.get_opportunity(opportunity_id).state is AcquisitionState.READY_FOR_DECISION
    assert DecisionEvaluationStore(engine).get_by_policy("decision-eval-1") is None


@pytest.mark.parametrize(
    "changed_authorization",
    (
        lambda value: value.model_copy(
            update={"scope": Scope(country="FR", language="fr", wedge="construction")}
        ),
        lambda value: value.model_copy(update={"actor_ref": "different-actor"}),
        lambda value: value.model_copy(
            update={
                "evidence": value.evidence.model_copy(
                    update={"assessment_version": "different-evidence-v2"}
                )
            }
        ),
    ),
)
def test_existing_audit_replay_rejects_changed_authorization_semantics(
    context, changed_authorization
) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=CountingClock()).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )

    with pytest.raises(DecisionEvaluationIdempotencyConflict):
        DecisionEngineService(engine, clock=CountingClock()).evaluate(
            opportunity_id,
            changed_authorization(authorization()),
            budget_usage=BudgetUsage(),
        )


def test_shadow_persists_blocked_proposal_without_commercial_mutation(context) -> None:
    engine, acquisition, opportunity_id = context
    PolicyStore(engine).append_control(
        control(
            2,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.AUTONOMOUS_CAPPED,
            allowed_commands=("evaluate_opportunity",),
            effective_at=EVALUATED_AT - dt.timedelta(hours=1),
        )
    )
    before = acquisition.get_opportunity(opportunity_id)

    result = DecisionEngineService(engine, clock=CountingClock()).evaluate(
        opportunity_id, authorization("shadow-eval"), budget_usage=BudgetUsage()
    )

    after = acquisition.get_opportunity(opportunity_id)
    assert result.audit.disposition is DecisionAuditDisposition.POLICY_BLOCKED
    assert result.audit.recorded_event_id is None
    assert after.state == before.state
    assert after.next_action == before.next_action
    assert after.stream_version == before.stream_version + 1  # POLICY_EVALUATED only
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_event).where(
                acquisition_event.c.event_type == "DECISION_RECORDED"
            )
        ) == 0


def test_policy_blocked_audit_revalidates_exact_policy_action_binding(context) -> None:
    engine, acquisition, opportunity_id = context
    PolicyStore(engine).append_control(
        control(
            2,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.AUTONOMOUS_CAPPED,
            allowed_commands=("evaluate_opportunity",),
            effective_at=EVALUATED_AT - dt.timedelta(hours=1),
        )
    )
    service = DecisionEngineService(engine, clock=CountingClock())

    def corrupt_binding() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.update(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == "shadow-binding-eval")
                .values(action_fingerprint="f" * 64)
            )

    service._after_policy_hook = corrupt_binding
    with pytest.raises(DecisionEvaluationIdempotencyConflict):
        service.evaluate(
            opportunity_id,
            authorization("shadow-binding-eval"),
            budget_usage=BudgetUsage(),
        )

    assert acquisition.get_opportunity(opportunity_id).state is AcquisitionState.READY_FOR_DECISION
    assert DecisionEvaluationStore(engine).get_by_policy("shadow-binding-eval") is None


def test_policy_audit_without_decision_audit_requires_fresh_evaluation(context) -> None:
    engine, acquisition, opportunity_id = context
    service = DecisionEngineService(engine, clock=CountingClock())
    service._after_policy_hook = lambda: (_ for _ in ()).throw(RuntimeError("crash"))
    with pytest.raises(RuntimeError, match="crash"):
        service.evaluate(opportunity_id, authorization("crash-eval"), budget_usage=BudgetUsage())

    clock = CountingClock()
    with pytest.raises(DecisionEvaluationRequiresFreshAttempt):
        DecisionEngineService(engine, clock=clock).evaluate(
            opportunity_id, authorization("crash-eval"), budget_usage=BudgetUsage()
        )
    assert clock.calls == 0
    assert acquisition.get_opportunity(opportunity_id).state is AcquisitionState.READY_FOR_DECISION


def test_not_actionable_fails_before_policy_and_audit(context) -> None:
    engine, acquisition, opportunity_id = context
    current = acquisition.get_opportunity(opportunity_id)
    with engine.begin() as connection:
        acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=current.stream_version,
            idempotency_key="decision-not-actionable",
            payload={"next_action": "request_human_review"},
        )
    clock = CountingClock()

    with pytest.raises(DecisionNotActionable):
        DecisionEngineService(engine, clock=clock).evaluate(
            opportunity_id, authorization(), budget_usage=BudgetUsage()
        )

    assert clock.calls == 1
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_decision_evaluation)
        ) == 0


def test_profile_change_after_policy_prevents_stale_decision(context) -> None:
    engine, acquisition, opportunity_id = context
    service = DecisionEngineService(engine, clock=CountingClock())

    def mutate_profile() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_company_profile)
                .where(
                    acquisition_company_profile.c.acquisition_opportunity_id == opportunity_id
                )
                .values(prebuild_fingerprint="f" * 64)
            )

    service._after_policy_hook = mutate_profile
    with pytest.raises(DecisionInputChanged):
        service.evaluate(opportunity_id, authorization(), budget_usage=BudgetUsage())

    assert acquisition.get_opportunity(opportunity_id).state is AcquisitionState.READY_FOR_DECISION
    assert DecisionEvaluationStore(engine).get_by_policy("decision-eval-1") is None


@pytest.mark.parametrize("mutation", ("unsupported_profile", "supplier_identity", "contact_role"))
def test_material_post_policy_binding_changes_are_typed_as_input_changed(
    context, mutation
) -> None:
    engine, acquisition, opportunity_id = context
    service = DecisionEngineService(engine, clock=CountingClock())

    def mutate_binding() -> None:
        with engine.begin() as connection:
            if mutation == "unsupported_profile":
                connection.execute(
                    sa.update(acquisition_company_profile)
                    .where(
                        acquisition_company_profile.c.acquisition_opportunity_id
                        == opportunity_id
                    )
                    .values(prebuild_version="future-prebuild-v2")
                )
            elif mutation == "supplier_identity":
                connection.execute(
                    sa.text(
                        "UPDATE acquisition_supplier SET identity_status = "
                        "'DOMAIN_CONFLICT', identity_conflict_fingerprint = :fingerprint"
                    ),
                    {"fingerprint": "d" * 64},
                )
            else:
                connection.execute(
                    sa.text("UPDATE acquisition_contact SET role_tier = 2")
                )

    service._after_policy_hook = mutate_binding
    with pytest.raises(DecisionInputChanged):
        service.evaluate(opportunity_id, authorization(), budget_usage=BudgetUsage())

    assert acquisition.get_opportunity(opportunity_id).state is AcquisitionState.READY_FOR_DECISION
    assert DecisionEvaluationStore(engine).get_by_policy("decision-eval-1") is None


def test_action_fingerprint_binds_opportunity_and_exact_proposal() -> None:
    first = policy_action_fingerprint(
        acquisition_opportunity_id="opp-1",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        proposal_fingerprint="a" * 64,
    )
    same = policy_action_fingerprint(
        acquisition_opportunity_id="opp-1",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        proposal_fingerprint="a" * 64,
    )
    changed = policy_action_fingerprint(
        acquisition_opportunity_id="opp-2",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        proposal_fingerprint="a" * 64,
    )

    assert first == same
    assert first != changed


def test_decision_audit_is_pii_free(context) -> None:
    engine, _, opportunity_id = context
    result = DecisionEngineService(engine, clock=CountingClock()).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    serialized = str(result.audit.model_dump(mode="json")).lower()

    assert "buyer@" not in serialized
    assert "sales director" not in serialized
    assert "first_name" not in serialized
    assert "business_email" not in serialized


def test_unsupported_prebuild_version_fails_before_policy(context) -> None:
    engine, _, opportunity_id = context
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_company_profile)
            .where(acquisition_company_profile.c.acquisition_opportunity_id == opportunity_id)
            .values(prebuild_version="future-prebuild-v2")
        )
    clock = CountingClock()

    with pytest.raises(DecisionInputVersionUnsupported):
        DecisionEngineService(engine, clock=clock).evaluate(
            opportunity_id, authorization(), budget_usage=BudgetUsage()
        )

    assert clock.calls == 1
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 0


def test_opportunity_change_after_policy_is_not_overwritten(context) -> None:
    engine, acquisition, opportunity_id = context
    service = DecisionEngineService(engine, clock=CountingClock())

    def mutate_opportunity() -> None:
        current = acquisition.get_opportunity(opportunity_id)
        with engine.begin() as connection:
            acquisition.append_in_transaction(
                connection,
                opportunity_id,
                event_type=EventType.NEXT_ACTION_SET,
                expected_version=current.stream_version,
                idempotency_key="concurrent-human-review",
                payload={"next_action": "request_human_review"},
            )

    service._after_policy_hook = mutate_opportunity
    with pytest.raises(DecisionInputChanged):
        service.evaluate(opportunity_id, authorization(), budget_usage=BudgetUsage())

    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.READY_FOR_DECISION
    assert current.next_action == "request_human_review"
    assert DecisionEvaluationStore(engine).get_by_policy("decision-eval-1") is None


def test_public_context_change_after_policy_prevents_stale_decision(context) -> None:
    engine, acquisition, opportunity_id = context
    service = DecisionEngineService(engine, clock=CountingClock())

    def mutate_public_fact() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.update(contract_award).values(award_date=dt.date(2026, 5, 18))
            )

    service._after_policy_hook = mutate_public_fact
    with pytest.raises(DecisionInputChanged):
        service.evaluate(opportunity_id, authorization(), budget_usage=BudgetUsage())

    assert acquisition.get_opportunity(opportunity_id).state is AcquisitionState.READY_FOR_DECISION
    assert DecisionEvaluationStore(engine).get_by_policy("decision-eval-1") is None


def test_terminal_audit_failure_rolls_back_decision_event_and_projection(context) -> None:
    engine, acquisition, opportunity_id = context
    store = DecisionEvaluationStore(engine)

    def fail(_connection, _write):
        raise RuntimeError("synthetic audit failure")

    store.append_in_transaction = fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        DecisionEngineService(engine, clock=CountingClock(), decision_store=store).evaluate(
            opportunity_id, authorization(), budget_usage=BudgetUsage()
        )

    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.READY_FOR_DECISION
    assert current.next_action == "evaluate_opportunity"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_event).where(
                acquisition_event.c.event_type == "DECISION_RECORDED"
            )
        ) == 0


def _write_from_result(result) -> DecisionEvaluationWrite:
    audit = result.audit
    return DecisionEvaluationWrite(
        decision_evaluation_id=audit.decision_evaluation_id,
        acquisition_opportunity_id=audit.acquisition_opportunity_id,
        policy_evaluation_id=audit.policy_evaluation_id,
        decision_input=AcquisitionDecisionInput.model_validate(audit.decision_input),
        proposal=result.proposal,
        policy_status=audit.policy_status,
        policy_counterfactual_status=audit.policy_counterfactual_status,
        expected_post_policy_version=audit.expected_post_policy_version,
        disposition=audit.disposition,
        recorded_event_id=audit.recorded_event_id,
        created_at=audit.created_at,
    )


def test_decision_audit_exact_replay_is_noop_and_semantic_change_conflicts(context) -> None:
    engine, _, opportunity_id = context
    result = DecisionEngineService(engine, clock=CountingClock()).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    store = DecisionEvaluationStore(engine)
    write = _write_from_result(result)

    replay = store.append(write)
    assert replay == result.audit

    changed = write.model_copy(
        update={
            "proposal": write.proposal.model_copy(
                update={"proposal_fingerprint": "f" * 64}
            )
        }
    )
    with pytest.raises(DecisionEvaluationIdempotencyConflict):
        store.append(changed)


def test_same_decision_evaluation_race_leaves_one_row_and_one_event(context) -> None:
    engine, _, opportunity_id = context
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def run() -> None:
        try:
            barrier.wait()
            results.append(
                DecisionEngineService(engine, clock=CountingClock()).evaluate(
                    opportunity_id, authorization(), budget_usage=BudgetUsage()
                )
            )
        except (RuntimeError, sa.exc.SQLAlchemyError, ValueError) as error:
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(results) == 2
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_decision_evaluation)
        ) == 1
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_event).where(
                acquisition_event.c.event_type == "DECISION_RECORDED"
            )
        ) == 1


def test_decision_evaluation_identity_is_versioned_and_deterministic() -> None:
    assert decision_evaluation_id("policy-1") == decision_evaluation_id("policy-1")
    assert decision_evaluation_id("policy-1") != decision_evaluation_id("policy-2")
    assert len(decision_evaluation_id("policy-1")) == 64
