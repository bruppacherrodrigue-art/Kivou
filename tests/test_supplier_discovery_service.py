from __future__ import annotations

import datetime as dt
import time
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from test_policy_persistence import control

from signals.acquisition.contracts import AcquisitionState
from signals.acquisition.store import AcquisitionStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import (
    acquisition_opportunity,
    acquisition_supplier,
    policy_evaluation,
    supplier_discovery_run,
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
from signals.policy.store import PolicyStore
from signals.supplier_discovery.contracts import (
    ApolloOrganizationCandidate,
    ApolloProviderError,
    CandidateRejection,
    DiscoveryAuthorizationInput,
    DiscoveryRunStatus,
    SupplierSearchPage,
    SupplierTargetingConfig,
)
from signals.supplier_discovery.identity import acquisition_identity_for, supplier_ref_for
from signals.supplier_discovery.profile import build_supplier_search_profile
from signals.supplier_discovery.service import SupplierDiscoveryService

NOW = dt.datetime(2026, 8, 20, 9, tzinfo=dt.UTC)


class FakeProvider:
    def __init__(self, pages, *, engine=None) -> None:
        self.pages = list(pages)
        self.calls = 0
        self.engine = engine

    def search_page(self, profile, *, page, observed_at):
        self.calls += 1
        if self.engine is not None:
            with self.engine.connect() as connection:
                assert connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(supplier_discovery_run)
                    .where(supplier_discovery_run.c.status == DiscoveryRunStatus.STARTED.value)
                ) == 1
        result = self.pages[page - 1]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'service.db'}")
    command.upgrade(alembic_config(value), "head")
    PolicyStore(value).append_control(
        control(1, allowed_commands=("discover_suppliers",))
    )
    return value


def targeting(
    *,
    max_pages: int = 1,
    threshold: int = 10_000,
    excluded_domains: tuple[str, ...] = (),
):
    return SupplierTargetingConfig(
        max_pages=max_pages,
        candidate_cap=max_pages * 100,
        search_too_broad_threshold=threshold,
        excluded_domains=excluded_domains,
    )


def profile_resolver(opportunity_key: str, config: SupplierTargetingConfig):
    return build_supplier_search_profile(
        signal_ref=f"procurement-opportunity:{opportunity_key}",
        representative_award_key="award-1",
        need_categories=("workforce_capacity",),
        targeting=config,
    )


def discovery_service(engine, provider) -> SupplierDiscoveryService:
    return SupplierDiscoveryService(
        engine, provider=provider, profile_resolver=profile_resolver
    )


def authorization(evaluation_id: str = "eval-discovery-1") -> DiscoveryAuthorizationInput:
    return DiscoveryAuthorizationInput(
        evaluation_id=evaluation_id,
        request_id=f"request-{evaluation_id}",
        actor_type="SYSTEM",
        actor_ref="kivou-supplier-discovery",
        scope=Scope(country="CH", language="fr", wedge="construction"),
        proposed_cost=Decimal("1"),
        currency="CHF",
        reason_codes=("supplier_search_requested",),
        evidence_refs=("public-evidence-1",),
        evidence=EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=("PUBLIC_OPPORTUNITY", "PUBLIC_EVIDENCE", "SUPPLIER_SEARCH_PROFILE"),
            assessment_version="supplier-search-evidence-v1",
            observed_at=NOW,
        ),
        compliance=ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="compliance-not-applicable-v1",
            observed_at=NOW,
        ),
        operational=OperationalReadiness(
            runtime_revision="apollo-runtime-v1",
            provider_quota="READY",
            provider_control_plane="AVAILABLE",
        ),
        expected_policy_version=POLICY_VERSION,
    )


def candidate(*, observed_at: dt.datetime = NOW, name: str = "Acme SA"):
    return ApolloOrganizationCandidate(
        provider_organization_id="apollo-org-1",
        display_name=name,
        normalized_name=name.casefold(),
        primary_domain="acme.example",
        provider_observed_at=observed_at,
        source_fingerprint=("b" if name == "Acme SA" else "c") * 64,
    )


def page(*candidates, total_entries: int | None = None, page_number: int = 1):
    return SupplierSearchPage(
        page=page_number,
        per_page=100,
        total_entries=total_entries if total_entries is not None else len(candidates),
        total_pages=1,
        candidates=candidates,
        rejections=(),
    )


def test_started_run_is_durable_before_provider_and_new_opportunity_is_initialized(engine) -> None:
    provider = FakeProvider([page(candidate())], engine=engine)
    result = discovery_service(engine, provider).discover(
        "public-1", targeting(),
        authorization(),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        discovery_run_id="run-1",
        correlation_id="corr-1",
    )

    assert provider.calls == 1
    assert result.run is not None and result.run.status is DiscoveryRunStatus.SUCCESS
    assert len(result.opportunity_ids) == 1
    acquisition = AcquisitionStore(engine).get_opportunity(result.opportunity_ids[0])
    assert acquisition.signal_ref == "procurement-opportunity:public-1"
    assert acquisition.supplier_ref == supplier_ref_for("apollo", "apollo-org-1")
    assert acquisition.contact_ref is None and acquisition.campaign_ref is None
    assert acquisition.state is AcquisitionState.DISCOVERED
    assert acquisition.next_action == "find_decision_makers"
    assert acquisition.stream_version == 2


def test_same_policy_evaluation_returns_existing_run_without_second_provider_call(engine) -> None:
    provider = FakeProvider([page(candidate())])
    service = discovery_service(engine, provider)
    first = service.discover(
        "public-1", targeting(), authorization(), evaluated_at=NOW, budget_usage=BudgetUsage(),
        discovery_run_id="run-1", correlation_id="corr-1",
    )
    replay = service.discover(
        "public-1", targeting(), authorization(), evaluated_at=NOW, budget_usage=BudgetUsage(),
        discovery_run_id="run-2", correlation_id="corr-2",
    )
    assert provider.calls == 1
    assert replay.run == first.run


def test_shadow_records_policy_but_never_creates_run_or_calls_provider(engine) -> None:
    PolicyStore(engine).append_control(
        control(
            2,
            allowed_commands=("discover_suppliers",),
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.AUTONOMOUS_CAPPED,
        )
    )
    provider = FakeProvider([page(candidate())])
    result = discovery_service(engine, provider).discover(
        "public-1", targeting(), authorization(), evaluated_at=NOW, budget_usage=BudgetUsage(),
        discovery_run_id="run-shadow", correlation_id="corr-shadow",
    )
    assert result.decision.executable is False
    assert result.run is None
    assert provider.calls == 0
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(supplier_discovery_run)) == 0


def test_unknown_provider_quota_fails_before_run_and_provider_call(engine) -> None:
    provider = FakeProvider([page(candidate())])
    auth = authorization("eval-quota-unknown")
    auth = auth.model_copy(
        update={
            "operational": auth.operational.model_copy(
                update={"provider_quota": ReadinessState.UNKNOWN}
            )
        }
    )
    result = discovery_service(engine, provider).discover(
        "public-1", targeting(), auth, evaluated_at=NOW, budget_usage=BudgetUsage(),
        discovery_run_id="run-quota", correlation_id="corr-quota",
    )
    assert result.decision.executable is False
    assert "provider_quota_unavailable" in result.decision.reason_codes
    assert result.run is None
    assert provider.calls == 0


def test_rediscovery_updates_supplier_but_never_rewinds_existing_workflow(engine) -> None:
    first_provider = FakeProvider([page(candidate())])
    first = discovery_service(engine, first_provider).discover(
        "public-1", targeting(), authorization("eval-first"), evaluated_at=NOW, budget_usage=BudgetUsage(),
        discovery_run_id="run-first", correlation_id="corr-first",
    )
    opportunity_id = first.opportunity_ids[0]
    acquisition_store = AcquisitionStore(engine)
    enriched = acquisition_store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=2,
        idempotency_key="spec021-enriching",
    )
    progressed = acquisition_store.set_next_action(
        opportunity_id,
        next_action="enrich_company",
        expected_version=enriched.projection.stream_version,
        idempotency_key="spec021-next-action",
    )

    second_provider = FakeProvider(
        [page(candidate(observed_at=NOW + dt.timedelta(hours=1), name="Acme Suisse SA"))]
    )
    discovery_service(engine, second_provider).discover(
        "public-1", targeting(), authorization("eval-second"),
        evaluated_at=NOW + dt.timedelta(hours=1), budget_usage=BudgetUsage(),
        discovery_run_id="run-second", correlation_id="corr-second",
    )

    after = acquisition_store.get_opportunity(opportunity_id)
    assert after.state is AcquisitionState.ENRICHING
    assert after.next_action == "enrich_company"
    assert after.stream_version == progressed.projection.stream_version
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_opportunity)) == 1


def test_broad_search_and_provider_failure_never_create_false_complete_state(engine) -> None:
    broad_provider = FakeProvider([page(total_entries=10_001)])
    broad = discovery_service(engine, broad_provider).discover(
        "public-1", targeting(threshold=10_000), authorization("eval-broad"), evaluated_at=NOW,
        budget_usage=BudgetUsage(), discovery_run_id="run-broad", correlation_id="corr-broad",
    )
    assert broad.run is not None
    assert broad.run.status is DiscoveryRunStatus.SEARCH_TOO_BROAD

    failed_provider = FakeProvider([ApolloProviderError("rate_limited")])
    failed = discovery_service(engine, failed_provider).discover(
        "public-1", targeting(), authorization("eval-failed"), evaluated_at=NOW, budget_usage=BudgetUsage(),
        discovery_run_id="run-failed", correlation_id="corr-failed",
    )
    assert failed.run is not None
    assert failed.run.status is DiscoveryRunStatus.FAILED
    assert failed.run.error_category == "rate_limited"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_supplier)) == 0


def test_provider_partial_results_marker_is_recorded_as_provider_limit(engine) -> None:
    limited_page = SupplierSearchPage(
        page=1,
        per_page=100,
        total_entries=100,
        total_pages=1,
        partial_results_only=True,
        candidates=(),
        rejections=(),
    )

    result = discovery_service(engine, FakeProvider([limited_page])).discover(
        "public-1",
        targeting(),
        authorization("eval-provider-limit"),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        discovery_run_id="run-provider-limit",
        correlation_id="corr-provider-limit",
    )

    assert result.run is not None
    assert result.run.status is DiscoveryRunStatus.SEARCH_TOO_BROAD
    assert result.run.error_category == "provider_limit"


def test_second_page_failure_keeps_first_page_facts_and_marks_partial(engine) -> None:
    first_page = SupplierSearchPage(
        page=1,
        per_page=100,
        total_entries=101,
        total_pages=2,
        candidates=(candidate(),),
        rejections=(),
    )
    provider = FakeProvider([first_page, ApolloProviderError("server_error")])
    result = discovery_service(engine, provider).discover(
        "public-1", targeting(max_pages=2), authorization("eval-partial"), evaluated_at=NOW,
        budget_usage=BudgetUsage(), discovery_run_id="run-partial", correlation_id="corr-partial",
    )
    assert result.run is not None
    assert result.run.status is DiscoveryRunStatus.PARTIAL
    assert result.run.pages_requested == 2
    assert result.run.records_accepted == 1
    assert len(result.opportunity_ids) == 1


def test_changed_provider_pagination_after_first_page_fails_partial_not_broad(
    engine,
) -> None:
    first_page = SupplierSearchPage(
        page=1,
        per_page=100,
        total_entries=101,
        total_pages=2,
        candidates=(candidate(),),
        rejections=(),
    )
    changed_page = SupplierSearchPage(
        page=2,
        per_page=100,
        total_entries=10_001,
        total_pages=101,
        partial_results_only=True,
        candidates=(),
        rejections=(),
    )
    result = discovery_service(
        engine, FakeProvider([first_page, changed_page])
    ).discover(
        "public-1",
        targeting(max_pages=2),
        authorization("eval-pagination-drift"),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        discovery_run_id="run-pagination-drift",
        correlation_id="corr-pagination-drift",
    )

    assert result.run is not None
    assert result.run.status is DiscoveryRunStatus.PARTIAL
    assert result.run.error_category == "malformed_response"
    assert result.run.records_accepted == 1
    assert len(result.opportunity_ids) == 1


def test_empty_provider_page_stops_without_consuming_remaining_page_budget(engine) -> None:
    empty = SupplierSearchPage(
        page=1,
        per_page=100,
        total_entries=300,
        total_pages=3,
        candidates=(),
        rejections=(),
    )
    provider = FakeProvider([empty])

    result = discovery_service(engine, provider).discover(
        "public-1", targeting(max_pages=3),
        authorization("eval-empty-page"),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        discovery_run_id="run-empty-page",
        correlation_id="corr-empty-page",
    )

    assert provider.calls == 1
    assert result.run is not None
    assert result.run.status is DiscoveryRunStatus.SUCCESS
    assert result.run.pages_requested == 1


def test_item_rejection_reason_is_counted_while_valid_candidate_persists(engine) -> None:
    mixed_page = SupplierSearchPage(
        page=1,
        per_page=100,
        total_entries=2,
        total_pages=1,
        candidates=(candidate(),),
        rejections=(
            CandidateRejection(
                item_index=1,
                provider_organization_id="apollo-bad-2",
                reason_code="missing_organization_name",
            ),
        ),
    )
    result = discovery_service(engine, FakeProvider([mixed_page])).discover(
        "public-1", targeting(), authorization("eval-item-reject"), evaluated_at=NOW,
        budget_usage=BudgetUsage(), discovery_run_id="run-item", correlation_id="corr-item",
    )
    assert result.run is not None
    assert result.run.status is DiscoveryRunStatus.SUCCESS
    assert result.run.records_accepted == 1
    assert result.run.records_rejected == 1
    assert result.run.rejection_reason_counts == {"missing_organization_name": 1}


def test_kivou_excluded_domain_is_rejected_without_supplier_or_opportunity(
    engine,
) -> None:
    result = discovery_service(engine, FakeProvider([page(candidate())])).discover(
        "public-1", targeting(excluded_domains=("ACME.EXAMPLE",)),
        authorization("eval-excluded-domain"),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        discovery_run_id="run-excluded-domain",
        correlation_id="corr-excluded-domain",
    )

    assert result.run is not None
    assert result.run.status is DiscoveryRunStatus.SUCCESS
    assert result.run.records_accepted == 0
    assert result.run.records_rejected == 1
    assert result.run.rejection_reason_counts == {"excluded_supplier_domain": 1}
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_supplier)
        ) == 0
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_opportunity)
        ) == 0


def test_rate_limit_preserves_retry_after_without_automatic_retry(engine) -> None:
    retry_after = NOW + dt.timedelta(minutes=5)
    provider = FakeProvider(
        [ApolloProviderError("rate_limited", retry_after=retry_after)]
    )
    result = discovery_service(engine, provider).discover(
        "public-1", targeting(), authorization("eval-429"), evaluated_at=NOW, budget_usage=BudgetUsage(),
        discovery_run_id="run-429", correlation_id="corr-429",
    )
    assert provider.calls == 1
    assert result.run is not None
    assert result.run.status is DiscoveryRunStatus.FAILED
    assert result.run.retry_after == retry_after
    assert result.run.provider_credit_units_observed is None


def test_candidate_transaction_rolls_back_supplier_and_opportunity_together(
    engine, monkeypatch
) -> None:
    service = discovery_service(engine, FakeProvider([page(candidate())]))

    def fail_append(*args, **kwargs):
        raise sa.exc.IntegrityError("NEXT_ACTION_SET", {}, RuntimeError("write failed"))

    monkeypatch.setattr(service._acquisition, "append_in_transaction", fail_append)
    result = service.discover(
        "public-1", targeting(), authorization("eval-rollback"), evaluated_at=NOW,
        budget_usage=BudgetUsage(), discovery_run_id="run-rollback",
        correlation_id="corr-rollback",
    )
    assert result.run is not None and result.run.status is DiscoveryRunStatus.FAILED
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_supplier)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_opportunity)) == 0


def test_opportunity_identity_is_seed_times_supplier_only() -> None:
    supplier_ref = supplier_ref_for("apollo", "apollo-org-1")
    assert acquisition_identity_for(
        "procurement-opportunity:public-1", supplier_ref
    ) == acquisition_identity_for("procurement-opportunity:public-1", supplier_ref)
    assert acquisition_identity_for(
        "procurement-opportunity:public-2", supplier_ref
    ) != acquisition_identity_for("procurement-opportunity:public-1", supplier_ref)


def test_one_hundred_company_fixture_processing_is_measured_without_sla(engine) -> None:
    candidates = tuple(
        ApolloOrganizationCandidate(
            provider_organization_id=f"apollo-org-{index:03d}",
            display_name=f"Supplier {index:03d} SA",
            normalized_name=f"supplier {index:03d} sa",
            primary_domain=f"supplier-{index:03d}.example",
            provider_observed_at=NOW,
            source_fingerprint=f"{index:064x}",
        )
        for index in range(100)
    )
    provider = FakeProvider([page(*candidates, total_entries=100)])
    started = time.perf_counter()

    result = discovery_service(engine, provider).discover(
        "public-1", targeting(),
        authorization("eval-performance-100"),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
        discovery_run_id="run-performance-100",
        correlation_id="corr-performance-100",
    )

    elapsed = time.perf_counter() - started
    assert result.run is not None
    assert result.run.records_accepted == 100
    assert result.run.opportunities_created == 100
    assert len(result.opportunity_ids) == 100
    print(f"supplier_discovery_100_elapsed_seconds={elapsed:.6f}")
