from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from test_policy_persistence import control

from signals.acquisition.contracts import AcquisitionState, ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.contact_discovery.contracts import (
    ApolloEnrichedPerson,
    ContactAuthorizationInput,
    ContactDiscoveryEvaluationRequiresFreshAttempt,
    ContactDiscoveryNotActionable,
    ContactRunIdentityConflict,
    ContactRunStatus,
    PeopleSearchCandidate,
    PeopleSearchPage,
)
from signals.contact_discovery.service import ContactDiscoveryService
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import acquisition_contact
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
    def __init__(self, page: PeopleSearchPage, enriched=(), *, hook=None) -> None:
        self.page = page
        self.enriched = list(enriched)
        self.hook = hook
        self.search_calls = 0
        self.enrich_calls = 0

    def search_people(self, profile, *, observed_at):
        self.search_calls += 1
        if self.hook is not None:
            self.hook()
            self.hook = None
        return self.page.model_copy(update={"observed_at": observed_at})

    def enrich_person(self, provider_person_id, *, observed_at):
        self.enrich_calls += 1
        value = self.enriched.pop(0)
        if value is None:
            return None
        return value.model_copy(update={"provider_observed_at": observed_at})


def _candidate(person_id="person-1", *, title="Sales Director", name="ACME S.A.", position=0):
    return PeopleSearchCandidate(
        provider_person_id=person_id,
        first_name="Alice",
        last_name_obfuscated="D.",
        title=title,
        provider_position=position,
        organization_name=name,
        has_email=True,
    )


def _page(*candidates, total=None):
    return PeopleSearchPage(
        total_entries=len(candidates) if total is None else total,
        candidates=tuple(candidates),
        rejections=(),
        observed_at=NOW,
    )


def _enriched(
    person_id="person-1",
    *,
    organization_id="apollo-org-1",
    email="alice@acme.example",
    status="verified",
    title="Sales Director",
):
    return ApolloEnrichedPerson(
        provider_person_id=person_id,
        provider_organization_id=organization_id,
        first_name="Alice",
        last_name="Dupont",
        display_name="Alice Dupont",
        title=title,
        business_email=email,
        provider_email_status=status,
        provider_observed_at=NOW,
        source_fingerprint="e" * 64,
    )


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
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    created = acquisition.create_opportunity(
        identity_key="contact-service-opportunity",
        signal_ref="procurement-opportunity:opp-1",
        supplier_ref=supplier.supplier_ref,
        idempotency_key="contact-service-create",
    )
    with engine.begin() as connection:
        acquisition.append_in_transaction(
            connection,
            created.projection.acquisition_opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=1,
            idempotency_key="contact-service-next",
            actor_type=ActorType.SYSTEM,
            payload={"next_action": "find_decision_makers"},
        )
    PolicyStore(engine).append_control(control(1, allowed_commands=("find_decision_makers",)))
    return engine, acquisition, supplier, created.projection.acquisition_opportunity_id


def _authorization(evaluation_id="contact-eval-1"):
    return ContactAuthorizationInput(
        evaluation_id=evaluation_id,
        request_id=f"request-{evaluation_id}",
        actor_type="SYSTEM",
        actor_ref="contact-discovery",
        scope=Scope(country="CH", language="fr", wedge="construction"),
        proposed_cost=Decimal("3"),
        currency="CHF",
        evidence_refs=("public-evidence:1",),
        evidence=EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=("SUPPLIER", "CONTACT_SEARCH_PROFILE"),
            assessment_version="contact-evidence-v1",
            observed_at=NOW,
        ),
        compliance=ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="compliance-unneeded-v1",
            observed_at=NOW,
        ),
        operational=OperationalReadiness(runtime_revision="runtime-1"),
        expected_policy_version=POLICY_VERSION,
    )


def _service(engine, provider, *, clock=None):
    ticking = clock or TickClock()
    return ContactDiscoveryService(engine, provider=provider, clock=ticking)


def _find(service, opportunity_id, authorization=None, run_id="contact-run-1"):
    return service.find(
        opportunity_id,
        authorization or _authorization(),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        contact_discovery_run_id=run_id,
        correlation_id=run_id,
    )


def test_success_is_bounded_truncated_and_updates_workflow_atomically(context) -> None:
    engine, acquisition, _, opportunity_id = context
    provider = FakeProvider(_page(_candidate(name="Acme Legal SA"), total=80), [_enriched()])
    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.SUCCESS
    assert result.run.provider_total_entries == 80
    assert result.run.search_results_returned == 1
    assert result.run.search_results_truncated is True
    assert provider.search_calls == provider.enrich_calls == 1
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.ENRICHING
    assert current.next_action == "enrich_company"
    assert current.contact_ref == result.contact.contact_ref
    assert current.campaign_ref is None
    assert current.stream_version == 6
    assert result.decision.evaluated_at < result.run.started_at
    assert result.run.started_at <= result.contact.provider_observed_at
    assert result.contact.provider_observed_at <= result.run.completed_at


def test_existing_run_replay_precedes_actionability_and_calls_no_provider(context) -> None:
    engine, _, _, opportunity_id = context
    first_provider = FakeProvider(_page(_candidate()), [_enriched()])
    first = _find(_service(engine, first_provider), opportunity_id)
    replay_provider = FakeProvider(_page(_candidate()), [_enriched()])
    replay = _find(_service(engine, replay_provider), opportunity_id)

    assert replay.run.contact_discovery_run_id == first.run.contact_discovery_run_id
    assert replay_provider.search_calls == replay_provider.enrich_calls == 0


@pytest.mark.parametrize(
    ("opportunity_id", "authorization"),
    [
        ("other-opportunity", _authorization("contact-eval-1")),
        (
            None,
            _authorization("contact-eval-1").model_copy(update={"request_id": "different-request"}),
        ),
    ],
)
def test_existing_run_replay_is_bound_to_policy_target_and_request(
    context, opportunity_id, authorization
) -> None:
    engine, _, _, actual_opportunity_id = context
    first = FakeProvider(_page(_candidate()), [_enriched()])
    _find(_service(engine, first), actual_opportunity_id)
    replay_provider = FakeProvider(_page(_candidate()), [_enriched()])

    with pytest.raises(ContactRunIdentityConflict):
        _find(
            _service(engine, replay_provider),
            opportunity_id or actual_opportunity_id,
            authorization,
        )
    assert replay_provider.search_calls == replay_provider.enrich_calls == 0


def test_policy_audit_without_run_requires_fresh_evaluation_id(context) -> None:
    engine, acquisition, _, opportunity_id = context
    opportunity = acquisition.get_opportunity(opportunity_id)
    authorization = _authorization("interrupted-eval")
    profile_json = "{}"
    from signals.policy.contracts import PolicyRequest

    PolicyGateway(engine).evaluate_and_record(
        PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="find_decision_makers",
            target_ref=f"acquisition-opportunity:{opportunity_id}",
            acquisition_opportunity_id=opportunity_id,
            expected_opportunity_version=opportunity.stream_version,
            actor_type="SYSTEM",
            canonical_arguments=profile_json,
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
    provider = FakeProvider(_page())
    with pytest.raises(ContactDiscoveryEvaluationRequiresFreshAttempt):
        _find(_service(engine, provider), opportunity_id, authorization)
    assert provider.search_calls == 0
    assert ContactDiscoveryStore(engine).get_run_by_policy("interrupted-eval") is None


def test_not_actionable_is_rejected_before_policy_run_or_provider(context) -> None:
    engine, acquisition, _, opportunity_id = context
    with engine.begin() as connection:
        acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.STATE_TRANSITIONED,
            expected_version=2,
            idempotency_key="already-enriching",
            payload={"target_state": "ENRICHING"},
        )
    provider = FakeProvider(_page())
    with pytest.raises(ContactDiscoveryNotActionable):
        _find(_service(engine, provider), opportunity_id)
    assert provider.search_calls == 0
    with engine.connect() as connection:
        assert PolicyStore(engine).evaluation_row(connection, "contact-eval-1") is None


def test_no_candidate_sets_human_review_without_changing_state(context) -> None:
    engine, acquisition, _, opportunity_id = context
    provider = FakeProvider(_page())
    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.NO_CANDIDATE
    assert result.contact is None
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.DISCOVERED
    assert current.contact_ref is None
    assert current.next_action == "request_human_review"
    assert current.stream_version == 4


@pytest.mark.parametrize("total", [10, 80])
def test_positive_total_empty_search_fails_without_human_review(context, total) -> None:
    engine, acquisition, _, opportunity_id = context
    provider = FakeProvider(_page(total=total))

    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.FAILED
    assert result.run.error_category == "malformed_response"
    assert result.run.error_detail == "unexpected_empty_search_page"
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.DISCOVERED
    assert current.contact_ref is None
    assert current.next_action == "find_decision_makers"
    assert current.stream_version == 3


def test_too_broad_performs_zero_enrichment_and_records_coverage(context) -> None:
    engine, acquisition, _, opportunity_id = context
    provider = FakeProvider(_page(_candidate(), total=251), [_enriched()])
    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.CONTACT_SEARCH_TOO_BROAD
    assert result.run.provider_total_entries == 251
    assert result.run.search_results_truncated is True
    assert provider.enrich_calls == 0
    assert acquisition.get_opportunity(opportunity_id).next_action == "request_human_review"


def test_enrichment_employer_mismatch_is_rejected(context) -> None:
    engine, acquisition, _, opportunity_id = context
    provider = FakeProvider(_page(_candidate()), [_enriched(organization_id="different-org")])
    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.NO_VERIFIED_CONTACT
    assert result.run.selected_contact_ref is None
    assert acquisition.get_opportunity(opportunity_id).contact_ref is None


def test_enrichment_is_sequential_bounded_and_stops_on_first_verified(context) -> None:
    engine, _, _, opportunity_id = context
    candidates = tuple(_candidate(f"person-{index}", position=index - 1) for index in range(1, 5))
    provider = FakeProvider(
        _page(*candidates),
        [
            _enriched("person-1", status="unverified"),
            _enriched("person-2", email=None, status="unavailable"),
            _enriched("person-3"),
            _enriched("person-4"),
        ],
    )
    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.SUCCESS
    assert result.run.enrichment_attempts == 3
    assert provider.enrich_calls == 3
    assert result.contact.provider_person_id == "person-3"


def test_enrichment_no_match_continues_to_next_candidate(context) -> None:
    engine, _, _, opportunity_id = context
    provider = FakeProvider(
        _page(
            _candidate("person-1", position=0),
            _candidate("person-2", position=1),
        ),
        [None, _enriched("person-2")],
    )

    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.SUCCESS
    assert result.run.enrichment_attempts == 2
    assert result.run.candidates_rejected == 1
    assert result.contact.provider_person_id == "person-2"


def test_three_enrichment_no_matches_end_without_verified_contact(context) -> None:
    engine, acquisition, _, opportunity_id = context
    provider = FakeProvider(
        _page(
            _candidate("person-1", position=0),
            _candidate("person-2", position=1),
            _candidate("person-3", position=2),
        ),
        [None, None, None],
    )

    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.NO_VERIFIED_CONTACT
    assert result.run.enrichment_attempts == 3
    assert result.run.candidates_rejected == 3
    assert acquisition.get_opportunity(opportunity_id).contact_ref is None


def test_enriched_non_commercial_title_is_rejected_and_next_candidate_tried(context) -> None:
    engine, _, _, opportunity_id = context
    provider = FakeProvider(
        _page(
            _candidate("person-1", title="Sales Director", position=0),
            _candidate("person-2", title="Sales Director", position=1),
        ),
        [
            _enriched("person-1", title="CTO"),
            _enriched("person-2", title="Commercial Director"),
        ],
    )

    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.SUCCESS
    assert result.run.enrichment_attempts == 2
    assert result.contact.provider_person_id == "person-2"
    assert result.contact.title == "Commercial Director"
    assert result.contact.normalized_title == "commercial director"
    assert result.contact.role_tier == 1


def test_enriched_title_reclassifies_current_role(context) -> None:
    engine, _, _, opportunity_id = context
    provider = FakeProvider(
        _page(_candidate(title="Sales Director")),
        [_enriched(title="Business Development Director")],
    )

    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.SUCCESS
    assert result.contact.title == "Business Development Director"
    assert result.contact.normalized_title == "business development director"
    assert result.contact.role_tier == 2


def test_absent_enriched_title_uses_search_title_fallback(context) -> None:
    engine, _, _, opportunity_id = context
    provider = FakeProvider(
        _page(_candidate(title="Sales Director")),
        [_enriched(title=None)],
    )

    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.SUCCESS
    assert result.contact.title == "Sales Director"
    assert result.contact.normalized_title == "sales director"
    assert result.contact.role_tier == 1


def test_concurrent_opportunity_change_after_policy_never_gets_overwritten(context) -> None:
    engine, acquisition, _, opportunity_id = context

    def concurrent_change():
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

    provider = FakeProvider(_page(_candidate()), [_enriched()], hook=concurrent_change)
    result = _find(_service(engine, provider), opportunity_id)

    assert result.run.status is ContactRunStatus.FAILED
    assert result.run.error_category == "opportunity_concurrency_conflict"
    current = acquisition.get_opportunity(opportunity_id)
    assert current.next_action == "request_human_review"
    assert current.contact_ref is None
    assert current.state is AcquisitionState.DISCOVERED


def test_success_transaction_rolls_back_contact_and_events_when_run_finish_fails(
    context,
) -> None:
    engine, acquisition, _, opportunity_id = context
    provider = FakeProvider(_page(_candidate()), [_enriched()])
    store = ContactDiscoveryStore(engine, clock=TickClock())
    original = store.finish_run_in_transaction
    failed_once = False

    def fail_once(connection, run_id, **values):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("synthetic terminal-write failure")
        return original(connection, run_id, **values)

    store.finish_run_in_transaction = fail_once  # type: ignore[method-assign]
    service = ContactDiscoveryService(
        engine, provider=provider, contact_store=store, clock=TickClock()
    )
    result = _find(service, opportunity_id)

    assert result.run.status is ContactRunStatus.FAILED
    current = acquisition.get_opportunity(opportunity_id)
    assert current.stream_version == 3
    assert current.contact_ref is None
    with engine.connect() as connection:
        count = connection.scalar(sa.select(sa.func.count()).select_from(acquisition_contact))
    assert count == 0


def test_no_contact_transaction_rolls_back_next_action_when_run_finish_fails(
    context,
) -> None:
    engine, acquisition, _, opportunity_id = context
    store = ContactDiscoveryStore(engine, clock=TickClock())
    original = store.finish_run_in_transaction
    failed_once = False

    def fail_once(connection, run_id, **values):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("synthetic terminal-write failure")
        return original(connection, run_id, **values)

    store.finish_run_in_transaction = fail_once  # type: ignore[method-assign]
    result = _find(
        ContactDiscoveryService(
            engine,
            provider=FakeProvider(_page()),
            contact_store=store,
            clock=TickClock(),
        ),
        opportunity_id,
    )

    assert result.run.status is ContactRunStatus.FAILED
    current = acquisition.get_opportunity(opportunity_id)
    assert current.stream_version == 3
    assert current.next_action == "find_decision_makers"


def test_shadow_policy_audits_but_calls_no_provider(context) -> None:
    engine, acquisition, _, opportunity_id = context
    PolicyStore(engine).append_control(
        control(
            2,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.AUTONOMOUS_CAPPED,
            allowed_commands=("find_decision_makers",),
        )
    )
    provider = FakeProvider(_page(_candidate()), [_enriched()])
    result = _find(_service(engine, provider), opportunity_id)

    assert result.decision.executable is False
    assert result.run is None
    assert provider.search_calls == provider.enrich_calls == 0
    assert acquisition.get_opportunity(opportunity_id).stream_version == 3
