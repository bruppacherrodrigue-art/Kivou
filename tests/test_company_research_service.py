from __future__ import annotations

import datetime as dt
import json
import time
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from test_policy_persistence import control

from signals.acquisition.contracts import AcquisitionState, ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.company_research.contracts import (
    ApolloOrganizationObservation,
    CompanyResearchAuthorizationInput,
    CompanyResearchEvaluationRequiresFreshAttempt,
    CompanyResearchNotActionable,
    CompanyResearchProviderError,
    CompanyResearchRunIdentityConflict,
    CompanyResearchRunStatus,
    ResearchCompleteness,
)
from signals.company_research.prebuild import build_acquisition_prospect_prebuild
from signals.company_research.profile import build_company_research_profile
from signals.company_research.service import CompanyResearchService
from signals.company_research.store import CompanyResearchStore
from signals.contact_discovery.contracts import ContactObservation
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import (
    acquisition_company_profile,
    acquisition_contact,
    acquisition_supplier,
    policy_evaluation,
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
    ReadinessState,
    Scope,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate
from signals.supplier_discovery.store import SupplierDiscoveryStore

NOW = dt.datetime(2026, 8, 20, 12, tzinfo=dt.UTC)


class TickClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> dt.datetime:
        self.value += dt.timedelta(seconds=1)
        return self.value


class FakeProvider:
    def __init__(self, observation=None, *, error=None, hook=None) -> None:
        self.observation = observation or _observation()
        self.error = error
        self.hook = hook
        self.calls = 0
        self.seen_started = None

    def fetch_organization(self, profile):
        self.calls += 1
        if self.hook is not None:
            self.hook()
        if self.error is not None:
            raise self.error
        return self.observation


class CrashAfterStartedCompanyStore(CompanyResearchStore):
    """Expose the durable pre-provider crash boundary exercised by the runtime."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._interrupt_once = True

    def start_run(self, start):
        ownership = super().start_run(start)
        if self._interrupt_once and ownership.owned:
            self._interrupt_once = False
            raise InterruptedError
        return ownership


def _observation(**updates):
    values = {
        "provider_organization_id": "apollo-org-1",
        "provider_company_name": "Acme SA",
        "provider_primary_domain": "acme.example",
        "provider_country": "CH",
        "provider_industry": "software",
        "provider_employee_count": 42,
        "provider_observed_at": NOW + dt.timedelta(seconds=2),
        "provider_source_fingerprint": "d" * 64,
    }
    values.update(updates)
    return ApolloOrganizationObservation(**values)


@pytest.fixture
def context(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'service.db'}")
    command.upgrade(alembic_config(engine), "head")
    supplier = (
        SupplierDiscoveryStore(engine, clock=lambda: NOW)
        .upsert_supplier(
            ApolloOrganizationCandidate(
                provider_organization_id="apollo-org-1",
                display_name="Acme SA",
                normalized_name="acme sa",
                provider_observed_at=NOW,
                source_fingerprint="a" * 64,
            )
        )
        .supplier
    )
    contact = (
        ContactDiscoveryStore(engine, clock=lambda: NOW)
        .upsert_contact(
            ContactObservation(
                supplier_ref=supplier.supplier_ref,
                provider_person_id="person-1",
                provider_organization_id="apollo-org-1",
                title="Sales Director",
                normalized_title="sales director",
                role_tier=1,
                business_email="buyer@acme.example",
                provider_email_status="verified",
                provider_observed_at=NOW,
                email_observed_at=NOW,
                source_fingerprint="b" * 64,
            )
        )
        .contact
    )
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    created = acquisition.create_opportunity(
        identity_key="company-service-opportunity",
        signal_ref="procurement-opportunity:opp-1",
        supplier_ref=supplier.supplier_ref,
        idempotency_key="company-service-create",
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    with engine.begin() as connection:
        selected = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.CONTACT_SELECTED,
            expected_version=1,
            idempotency_key="company-service-contact",
            actor_type=ActorType.SYSTEM,
            payload={"contact_ref": contact.contact_ref, "supplier_ref": supplier.supplier_ref},
        )
        transitioned = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.STATE_TRANSITIONED,
            expected_version=selected.projection.stream_version,
            idempotency_key="company-service-enriching",
            actor_type=ActorType.SYSTEM,
            payload={"target_state": "ENRICHING"},
        )
        acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=transitioned.projection.stream_version,
            idempotency_key="company-service-next",
            actor_type=ActorType.SYSTEM,
            payload={"next_action": "enrich_company"},
        )
    PolicyStore(engine).append_control(control(1, allowed_commands=("enrich_company",)))
    return engine, acquisition, supplier, contact, opportunity_id


def _authorization(evaluation_id="company-eval-1", *, quota=ReadinessState.READY):
    return CompanyResearchAuthorizationInput(
        evaluation_id=evaluation_id,
        request_id=f"request-{evaluation_id}",
        actor_type="SYSTEM",
        actor_ref="company-research",
        scope=Scope(country="CH", language="fr", wedge="construction"),
        proposed_cost=Decimal("1"),
        currency="CHF",
        evidence_refs=("public-evidence:1",),
        evidence=EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=("SUPPLIER", "VERIFIED_CONTACT", "COMPANY_RESEARCH_PROFILE"),
            assessment_version="company-evidence-v1",
            observed_at=NOW,
        ),
        compliance=ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="compliance-unneeded-v1",
            observed_at=NOW,
        ),
        operational=OperationalReadiness(runtime_revision="runtime-1", provider_quota=quota),
        expected_policy_version=POLICY_VERSION,
    )


def _research(service, opportunity_id, authorization=None, run_id="company-run-1"):
    return service.research(
        opportunity_id,
        authorization or _authorization(),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        company_research_run_id=run_id,
        correlation_id=run_id,
    )


def _service(engine, provider, *, store=None):
    return CompanyResearchService(
        engine,
        provider=provider,
        company_store=store,
        clock=TickClock(),
    )


def test_success_persists_profile_and_advances_workflow_atomically(context) -> None:
    engine, acquisition, _, _, opportunity_id = context
    provider = FakeProvider()
    result = _research(
        _service(engine, provider),
        opportunity_id,
    )

    assert provider.calls == 1
    assert result.run.status is CompanyResearchRunStatus.SUCCESS
    assert result.profile.research_completeness is ResearchCompleteness.COMPLETE
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.READY_FOR_DECISION
    assert current.next_action == "evaluate_opportunity"
    assert current.stream_version == 7
    assert result.decision.evaluated_at <= result.run.started_at
    assert result.run.started_at <= result.profile.provider_observed_at
    assert result.profile.provider_observed_at <= result.run.completed_at


def test_started_run_recovery_reuses_policy_run_and_calls_apollo_once(context) -> None:
    engine, _, _, _, opportunity_id = context
    store = CrashAfterStartedCompanyStore(engine, clock=TickClock())
    provider = FakeProvider()
    service = CompanyResearchService(
        engine,
        provider=provider,
        company_store=store,
        clock=TickClock(),
    )

    with pytest.raises(InterruptedError):
        _research(service, opportunity_id)

    started = store.get_run("company-run-1")
    assert started.status is CompanyResearchRunStatus.STARTED
    assert started.recovery_provider_calls == 0
    assert provider.calls == 0
    revalidations: list[str] = []

    recovered = service.resume_started(
        started.company_research_run_id,
        authorize_recovery=lambda: revalidations.append("current-policy"),
    )

    assert recovered is not None
    assert recovered.run.status is CompanyResearchRunStatus.SUCCESS
    assert recovered.run.company_research_run_id == started.company_research_run_id
    assert recovered.run.policy_evaluation_id == started.policy_evaluation_id
    assert recovered.run.recovery_provider_calls == 1
    assert provider.calls == 1
    assert revalidations == ["current-policy"]
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == started.policy_evaluation_id)
        ) == 1


def test_limited_optional_fields_still_advance_with_explicit_gaps(context) -> None:
    engine, acquisition, _, _, opportunity_id = context
    provider = FakeProvider(
        _observation(
            provider_primary_domain=None,
            provider_country=None,
            provider_employee_count=None,
            research_gaps=(
                "MISSING_DOMAIN_OR_WEBSITE",
                "MISSING_COUNTRY",
                "MISSING_EMPLOYEE_COUNT",
            ),
        )
    )
    result = _research(_service(engine, provider), opportunity_id)

    assert result.run.status is CompanyResearchRunStatus.LIMITED
    assert result.profile.research_completeness is ResearchCompleteness.LIMITED
    assert acquisition.get_opportunity(opportunity_id).state is AcquisitionState.READY_FOR_DECISION


def test_started_run_exists_before_provider_call(context) -> None:
    engine, _, _, _, opportunity_id = context
    store = CompanyResearchStore(engine)
    provider = FakeProvider()

    def assert_started():
        assert store.get_run_by_policy("company-eval-1").status is CompanyResearchRunStatus.STARTED

    provider.hook = assert_started
    _research(
        _service(engine, provider, store=store),
        opportunity_id,
    )


def test_existing_run_replay_calls_neither_policy_nor_provider(context) -> None:
    engine, _, _, _, opportunity_id = context
    first = _research(_service(engine, FakeProvider()), opportunity_id)
    replay_provider = FakeProvider()
    replay = _research(_service(engine, replay_provider), opportunity_id)

    assert replay.run.company_research_run_id == first.run.company_research_run_id
    assert replay_provider.calls == 0


def test_policy_audit_without_run_requires_fresh_evaluation(context) -> None:
    engine, acquisition, _, _, opportunity_id = context
    opportunity = acquisition.get_opportunity(opportunity_id)
    authorization = _authorization("interrupted-eval")
    from signals.policy.contracts import PolicyRequest

    PolicyGateway(engine).evaluate_and_record(
        PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="enrich_company",
            target_ref=f"acquisition-opportunity:{opportunity_id}",
            acquisition_opportunity_id=opportunity_id,
            expected_opportunity_version=opportunity.stream_version,
            actor_type="SYSTEM",
            canonical_arguments="{}",
            action_fingerprint="f" * 64,
            scope=authorization.scope,
            proposed_cost=authorization.proposed_cost,
            currency=authorization.currency,
            evidence=authorization.evidence,
            compliance=authorization.compliance,
            operational=authorization.operational,
            expected_policy_version=authorization.expected_policy_version,
        ),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )

    provider = FakeProvider()
    with pytest.raises(CompanyResearchEvaluationRequiresFreshAttempt):
        _research(
            _service(engine, provider),
            opportunity_id,
            authorization,
        )
    assert provider.calls == 0


def test_not_actionable_is_rejected_before_policy_run_or_provider(context) -> None:
    engine, acquisition, _, _, opportunity_id = context
    with engine.begin() as connection:
        current = acquisition.get_opportunity_in_transaction(connection, opportunity_id)
        acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=current.stream_version,
            idempotency_key="not-actionable",
            payload={"next_action": "request_human_review"},
        )
    provider = FakeProvider()
    with pytest.raises(CompanyResearchNotActionable):
        _research(_service(engine, provider), opportunity_id)
    assert provider.calls == 0
    with engine.connect() as connection:
        assert PolicyStore(engine).evaluation_row(connection, "company-eval-1") is None


@pytest.mark.parametrize(
    "category",
    [
        "unauthorized",
        "forbidden",
        "not_found",
        "unprocessable_entity",
        "client_error",
        "rate_limited",
        "timeout",
        "network_error",
        "server_error",
        "malformed_response",
        "response_too_large",
        "provider_identity_mismatch",
    ],
)
def test_provider_failures_fail_run_without_profile_or_workflow(context, category) -> None:
    engine, acquisition, _, _, opportunity_id = context
    provider = FakeProvider(error=CompanyResearchProviderError(category))
    result = _research(_service(engine, provider), opportunity_id)

    assert result.run.status is CompanyResearchRunStatus.FAILED
    assert result.run.error_category == category
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.ENRICHING
    assert current.next_action == "enrich_company"
    with engine.connect() as connection:
        assert (
            connection.scalar(sa.select(sa.func.count()).select_from(acquisition_company_profile))
            == 0
        )


def test_shadow_and_unknown_quota_call_no_provider(context) -> None:
    engine, _, _, _, opportunity_id = context
    PolicyStore(engine).append_control(
        control(
            2,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.AUTONOMOUS_CAPPED,
            allowed_commands=("enrich_company",),
        )
    )
    shadow_provider = FakeProvider()
    shadow = _research(_service(engine, shadow_provider), opportunity_id)
    assert shadow.decision.executable is False
    assert shadow_provider.calls == 0


def test_quota_unknown_calls_no_provider(context) -> None:
    engine, _, _, _, opportunity_id = context
    provider = FakeProvider()
    result = _research(
        _service(engine, provider),
        opportunity_id,
        _authorization(quota=ReadinessState.UNKNOWN),
    )
    assert result.decision.executable is False
    assert provider.calls == 0


def test_run_id_collision_is_typed_before_provider(context) -> None:
    engine, _, _, _, opportunity_id = context
    first = _research(
        _service(
            engine,
            FakeProvider(error=CompanyResearchProviderError("timeout")),
        ),
        opportunity_id,
    )
    provider = FakeProvider()
    with pytest.raises(CompanyResearchRunIdentityConflict):
        _research(
            _service(engine, provider),
            opportunity_id,
            _authorization("different-evaluation"),
            run_id=first.run.company_research_run_id,
        )
    assert provider.calls == 0


def test_concurrent_opportunity_change_after_policy_is_not_overwritten(context) -> None:
    engine, acquisition, _, _, opportunity_id = context

    def concurrent_change():
        current = acquisition.get_opportunity(opportunity_id)
        with engine.begin() as connection:
            acquisition.append_in_transaction(
                connection,
                opportunity_id,
                event_type=EventType.NEXT_ACTION_SET,
                expected_version=current.stream_version,
                idempotency_key="concurrent-review",
                payload={"next_action": "request_human_review"},
            )

    provider = FakeProvider(hook=concurrent_change)
    result = _research(_service(engine, provider), opportunity_id)

    assert result.run.status is CompanyResearchRunStatus.FAILED
    assert result.run.error_category == "opportunity_concurrency_conflict"
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.ENRICHING
    assert current.next_action == "request_human_review"


def test_concurrent_supplier_identity_refresh_is_used_in_prebuild(context) -> None:
    engine, _, _, _, opportunity_id = context

    def refresh_supplier():
        with engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_supplier).values(
                    identity_status="DOMAIN_CONFLICT",
                    identity_conflict_fingerprint="9" * 64,
                )
            )

    result = _research(_service(engine, FakeProvider(hook=refresh_supplier)), opportunity_id)

    assert result.run.status is CompanyResearchRunStatus.SUCCESS
    assert result.profile.supplier_identity_status == "DOMAIN_CONFLICT"


def test_concurrent_contact_role_refresh_is_used_in_prebuild(context) -> None:
    engine, _, _, _, opportunity_id = context

    def refresh_contact():
        with engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_contact).values(
                    role_profile_version="decision-maker-search-v2",
                    role_tier=2,
                )
            )

    result = _research(_service(engine, FakeProvider(hook=refresh_contact)), opportunity_id)

    assert result.run.status is CompanyResearchRunStatus.SUCCESS
    assert result.profile.contact_role_profile_version == "decision-maker-search-v2"
    assert result.profile.contact_role_tier == 2


def test_terminal_write_failure_rolls_back_profile_and_workflow(context) -> None:
    engine, acquisition, _, _, opportunity_id = context
    store = CompanyResearchStore(engine, clock=TickClock())
    original = store.finish_run_in_transaction
    failed_once = False

    def fail_once(connection, run_id, **values):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("synthetic terminal failure")
        return original(connection, run_id, **values)

    store.finish_run_in_transaction = fail_once  # type: ignore[method-assign]
    result = _research(
        _service(engine, FakeProvider(), store=store),
        opportunity_id,
    )

    assert result.run.status is CompanyResearchRunStatus.FAILED
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.ENRICHING
    assert current.next_action == "enrich_company"
    with engine.connect() as connection:
        assert (
            connection.scalar(sa.select(sa.func.count()).select_from(acquisition_company_profile))
            == 0
        )


def test_one_hundred_organization_observations_are_measured_without_sla(context) -> None:
    engine, acquisition, supplier, contact, opportunity_id = context
    opportunity = acquisition.get_opportunity(opportunity_id)
    ticks = iter(NOW + dt.timedelta(seconds=index + 1) for index in range(100))
    payload = json.dumps(
        {
            "organization": {
                "id": "apollo-org-1",
                "name": "Acme SA",
                "primary_domain": "acme.example",
                "country": "CH",
                "industry": "software",
                "estimated_num_employees": 42,
            }
        }
    ).encode()
    client = ApolloCompanyResearchClient(
        api_key="fake-test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
        ),
        clock=lambda: next(ticks),
    )
    profile = build_company_research_profile("apollo-org-1")
    store = CompanyResearchStore(engine, clock=lambda: NOW)
    started = time.perf_counter()

    for _index in range(100):
        observation = client.fetch_organization(profile)
        prebuild = build_acquisition_prospect_prebuild(
            acquisition_opportunity_id=opportunity_id,
            signal_ref=opportunity.signal_ref,
            supplier_ref=supplier.supplier_ref,
            contact_ref=contact.contact_ref,
            supplier_identity_status=supplier.identity_status,
            contact_role_profile_version=contact.role_profile_version,
            contact_role_tier=contact.role_tier,
            observation=observation,
        )
        store.upsert_profile(prebuild)

    elapsed = time.perf_counter() - started
    persisted = store.get_profile(opportunity_id)
    assert persisted.provider_observed_at == NOW + dt.timedelta(seconds=100)
    print(f"company_research_100_elapsed_seconds={elapsed:.6f}")
