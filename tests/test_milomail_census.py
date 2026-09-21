"""Bounded, resumable Milo Mail census with synthetic provider data only."""

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa
from test_milomail_policy import ready_config

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.census import (
    CensusBudgetExceeded,
    CensusLimits,
    CensusRetryLater,
    CensusReviewRequired,
    CensusStore,
    build_partitions,
)
from signals.acquisition_programs.census_readiness import (
    ApolloCreditPricing,
    DatabaseAuthorization,
    ExecutionPermit,
    PermitStore,
    configuration_hash,
    database_identity,
)
from signals.acquisition_programs.census_runtime import CensusRunner
from signals.acquisition_programs.mail_provider import MailProviderDetector
from signals.acquisition_programs.pipeline import ActiveCompanyEvidence, ProgramOperationalContext
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.persistence.database import migrate_to_latest
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient
from signals.supplier_discovery.contracts import (
    ApolloOrganizationCandidate,
    ApolloProviderError,
    SupplierSearchPage,
)

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def test_partitions_are_deterministic_and_employee_ranges_do_not_overlap() -> None:
    config = ready_config()
    first = build_partitions(config)
    assert first == build_partitions(config)
    assert len(first) == 9
    assert len({part.partition_id for part in first}) == 9
    for sector in config.target_sectors:
        ranges = sorted(
            (part.size_min, part.size_max) for part in first if part.sector == sector
        )
        assert ranges == [(1, 3), (4, 6), (7, 10)]
    assert all(part.organization_locations == ("France",) for part in first)


def test_absent_census_configuration_is_closed() -> None:
    limits = CensusLimits.from_environment({})
    assert not limits.enabled
    assert limits.max_partitions == limits.max_pages == limits.max_candidates == 0
    assert limits.max_enrichments == limits.max_apollo_credits == 0
    assert limits.max_cost_chf == Decimal(0)
    with pytest.raises(ValueError, match="explicit census authorization"):
        limits.require_run_authorization()


def test_plan_is_idempotent_and_zero_budget_blocks_provider_call() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_config()
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    store = CensusStore(engine, require_permit=False)
    partitions = build_partitions(config)
    run_id = store.plan(program_id=program_id, partitions=partitions, at=NOW)
    assert store.plan(program_id=program_id, partitions=partitions, at=NOW) == run_id
    assert len(store.partitions(run_id)) == len(partitions)
    with pytest.raises((ValueError, CensusBudgetExceeded)):
        store.start(run_id, CensusLimits.from_environment({}), at=NOW)
    assert store.status(run_id)["credits_reserved"] == 0


def test_actual_apollo_usage_requires_evidence_and_is_immutable() -> None:
    store, run_id = _planned_store()
    assert store.report(run_id)["cost_chf_actual"] is None
    with pytest.raises(ValueError, match="evidence"):
        store.record_actual_usage(
            run_id, credits=0, cost_chf=Decimal("0"),
            evidence_ref="", at=NOW,
        )
    store.record_actual_usage(
        run_id, credits=0, cost_chf=Decimal("0"),
        evidence_ref="synthetic-invoice-001", at=NOW,
    )
    store.record_actual_usage(
        run_id, credits=0, cost_chf=Decimal("0"),
        evidence_ref="synthetic-invoice-001", at=NOW,
    )
    report = store.report(run_id)
    assert report["apollo_credits_actual"] == 0
    assert report["cost_chf_actual"] == "0.0000"
    assert report["cost_chf_per_SEND_actual"] is None
    with pytest.raises(ValueError, match="immutable"):
        store.record_actual_usage(
            run_id, credits=1, cost_chf=Decimal("0.1"),
            evidence_ref="synthetic-invoice-002", at=NOW,
        )


def test_actual_usage_above_reserved_cap_requires_review() -> None:
    store, run_id = _planned_store()
    store.record_actual_usage(
        run_id, credits=1, cost_chf=Decimal("0.1000"),
        evidence_ref="synthetic-invoice-003", at=NOW,
    )
    report = store.report(run_id)
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["apollo_credits_reserved_upper_bound"] == 0
    assert report["apollo_credits_actual"] == 1


def test_actual_chf_above_reserved_ceiling_requires_review() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(), at=NOW)
    partition = store.partitions(run_id)[0]
    store.reserve_call(
        run_id, kind="ORG_SEARCH", subject="priced-page", attempt=1,
        partition_id=partition["partition_id"], credits=1, candidate_slots=25, at=NOW,
    )
    assert store.status(run_id)["cost_reserved_chf"] == "0.10"
    with pytest.raises(ValueError, match="terminal"):
        store.record_actual_usage(
            run_id, credits=1, cost_chf=Decimal("0.1500"),
            evidence_ref="synthetic-invoice-005", at=NOW,
        )
    store.pause(run_id, None, "USAGE_REVIEW", at=NOW, review=True)
    store.record_actual_usage(
        run_id, credits=1, cost_chf=Decimal("0.1500"),
        evidence_ref="synthetic-invoice-005", at=NOW,
    )
    assert store.report(run_id)["status"] == "REVIEW_REQUIRED"


def _limits(**changes) -> CensusLimits:
    values = {
        "enabled": True,
        "max_partitions": 9,
        "max_pages": 4,
        "max_candidates": 100,
        "max_enrichments": 8,
        "max_apollo_credits": 20,
        "max_cost_chf": "2",
        "chf_per_credit_ceiling": "0.10",
        "authorization_ref": "synthetic-test-approval",
    }
    values.update(changes)
    return CensusLimits.model_validate(values)


def _planned_store():
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    program_id = AcquisitionProgramStore(engine).register(ready_config(), at=NOW)
    store = CensusStore(engine, require_permit=False)
    run_id = store.plan(program_id=program_id, partitions=build_partitions(ready_config()), at=NOW)
    return store, run_id


def _test_permits(engine, store, run_id, limits):
    database_id = database_identity(engine)[0]
    auth = DatabaseAuthorization(database_id=database_id, environment="test",
                                 issued_by_reference="synthetic-test", expires_at=NOW + dt.timedelta(days=1))
    pricing = ApolloCreditPricing(
        currency="CHF", price_per_credit="0.10", verified_at=NOW,
        source_type="OPERATOR_ATTESTATION", source_reference="synthetic-test-pricing",
        plan_name="synthetic", verified_by_reference="synthetic-test",
        org_search_credits=1, org_enrichment_credits=1,
        people_search_credits=0, person_enrichment_credits_max=9,
        credit_balance=100, credit_balance_observed_at=NOW,
        rate_limits_per_minute={"ORG_SEARCH": 10, "ORG_ENRICH": 10,
                                "PEOPLE_SEARCH": 10, "PERSON_ENRICH": 10},
        rate_limit_reference="synthetic-test-rate-limits",
        credit_pools_by_operation={kind: "lead_credit" for kind in (
            "ORG_SEARCH", "ORG_ENRICH", "PEOPLE_SEARCH", "PERSON_ENRICH",
        )},
    )
    digest = configuration_hash(census_id=run_id, limits=limits,
                                partitions=store.partitions(run_id), pricing=pricing)
    values = {}
    for phase in ("COVERAGE", "ENRICHMENT"):
        permit_id = f"synthetic-{phase.lower()}-{run_id[:12]}"
        permit = ExecutionPermit(
            permit_id=permit_id, census_id=run_id, phase=phase,
            environment="test", database_id=database_id,
            allowed_partitions=tuple(row["partition_id"] for row in
                                     store.partitions(run_id)[:limits.max_partitions]),
            max_pages=limits.max_pages if phase == "COVERAGE" else 0,
            max_candidates=limits.max_candidates if phase == "COVERAGE" else 0,
            max_enrichments=limits.max_enrichments if phase == "ENRICHMENT" else 0,
            max_credits=limits.max_apollo_credits,
            max_cost_chf=limits.max_cost_chf,
            price_chf_per_credit="0.10", pricing_reference="synthetic-test-pricing",
            configuration_hash=digest, issued_by_reference="synthetic-test",
            issued_at=NOW, valid_from=NOW, expires_at=NOW + dt.timedelta(days=1),
        )
        PermitStore(engine).issue(permit, database=auth, pricing=pricing, limits=limits,
                                  at=NOW)
        values[phase] = permit_id
    return values, digest, database_id


def _candidate(org_id: str = "org-1", domain: str = "agence.fr"):
    return ApolloOrganizationCandidate(
        provider_organization_id=org_id,
        display_name="Agence Exemple",
        normalized_name="agence exemple",
        primary_domain=domain,
        website_url=f"https://{domain}",
        country_code="FR",
        location="Paris, France",
        industry="Marketing",
        provider_observed_at=NOW,
        source_fingerprint="a" * 64,
    )


def _page(page: int, *, candidates, total_pages: int = 1, total_entries: int = 1):
    return SupplierSearchPage(
        page=page, per_page=25, total_entries=total_entries, total_pages=total_pages,
        candidates=tuple(candidates), rejections=(),
    )


def test_page_checkpoint_deduplicates_between_partitions_and_resumes() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(), at=NOW)
    first, second = store.partitions(run_id)[:2]
    for part in (first, second):
        call = store.reserve_call(
            run_id, kind="ORG_SEARCH", subject=f"{part['partition_id']}:1", attempt=1,
            partition_id=part["partition_id"], credits=1, candidate_slots=25, at=NOW,
        )
        page = _page(1, candidates=[_candidate()])
        store.complete_call(call["call_id"], page.model_dump(mode="json"), at=NOW)
        store.record_page(run_id, part["partition_id"], page, call_id=call["call_id"], at=NOW)
        store.record_page(run_id, part["partition_id"], page, call_id=call["call_id"], at=NOW)
    assert len(store.candidates(run_id)) == 1
    parts = store.partitions(run_id)
    assert sum(part["unique_count"] for part in parts) == 1
    assert sum(part["duplicate_count"] for part in parts) == 1
    assert store.status(run_id)["credits_reserved"] == 2
    assert store.status(run_id)["candidate_slots_reserved"] == 2
    assert parts[0]["cursor_page"] == parts[1]["cursor_page"] == 2


def test_apollo_ip_domain_is_retained_as_unknown_without_stopping_page() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(), at=NOW)
    partition = store.partitions(run_id)[0]
    call = store.reserve_call(
        run_id, kind="ORG_SEARCH", subject="invalid-domain-page", attempt=1,
        partition_id=partition["partition_id"], credits=1, candidate_slots=25, at=NOW,
    )
    page = _page(1, candidates=[_candidate(domain="127.0.0.1")])
    store.complete_call(call["call_id"], page.model_dump(mode="json"), at=NOW)
    store.record_page(run_id, partition["partition_id"], page, call_id=call["call_id"], at=NOW)
    candidate = store.candidates(run_id)[0]
    assert candidate["primary_domain"] is None
    assert candidate["snapshot"]["primary_domain"] is None
    assert store.report(run_id)["valid_domains"] == 0


def test_reservation_stops_at_page_credit_and_chf_caps() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(max_pages=1, max_apollo_credits=1, max_cost_chf="0.10"), at=NOW)
    first = store.partitions(run_id)[0]
    store.reserve_call(
        run_id, kind="ORG_SEARCH", subject="page-one", attempt=1,
        partition_id=first["partition_id"], credits=1, candidate_slots=25, at=NOW,
    )
    with pytest.raises(CensusBudgetExceeded):
        store.reserve_call(
            run_id, kind="ORG_SEARCH", subject="page-two", attempt=1,
            partition_id=first["partition_id"], credits=1, candidate_slots=25, at=NOW,
        )
    assert store.status(run_id)["cost_reserved_chf"] == "0.10"


def test_candidate_slots_are_reserved_before_apollo_call() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(max_candidates=5), at=NOW)
    partition = store.partitions(run_id)[0]
    with pytest.raises(CensusBudgetExceeded):
        store.reserve_call(
            run_id, kind="ORG_SEARCH", subject="too-wide-page", attempt=1,
            partition_id=partition["partition_id"], credits=1,
            candidate_slots=25, at=NOW,
        )
    assert store.status(run_id)["credits_reserved"] == 0


def test_completed_response_before_checkpoint_is_reused_without_second_call() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(), at=NOW)
    partition = store.partitions(run_id)[0]
    page = _page(1, candidates=[_candidate()])
    call = store.reserve_call(
        run_id, kind="ORG_SEARCH", subject="interrupted-page", attempt=1,
        partition_id=partition["partition_id"], credits=1, candidate_slots=25, at=NOW,
    )
    store.complete_call(call["call_id"], page.model_dump(mode="json"), at=NOW)

    def forbidden():
        raise AssertionError("completed Apollo response was requested twice")

    cached, cached_id = store.execute_call(
        run_id, kind="ORG_SEARCH", subject="interrupted-page",
        partition_id=partition["partition_id"], credits=1, candidate_slots=25,
        at=NOW, invoke=forbidden, encode=lambda value: value.model_dump(mode="json"),
        decode=SupplierSearchPage.model_validate,
    )
    store.record_page(run_id, partition["partition_id"], cached, call_id=cached_id, at=NOW)
    assert len(store.candidates(run_id)) == 1
    assert store.status(run_id)["credits_reserved"] == 1
    assert store.partitions(run_id)[0]["cursor_page"] == 2


def test_rate_limit_retry_is_bounded_and_charged_conservatively() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(max_pages=2), at=NOW)
    partition = store.partitions(run_id)[0]
    calls = 0

    def rate_limited_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ApolloProviderError("rate_limited", retry_after=NOW)
        return _page(1, candidates=[_candidate()])

    page, call_id = store.execute_call(
        run_id, kind="ORG_SEARCH", subject="retry-page",
        partition_id=partition["partition_id"], credits=1, candidate_slots=25,
        at=NOW, invoke=rate_limited_once,
        encode=lambda value: value.model_dump(mode="json"),
        decode=SupplierSearchPage.model_validate,
    )
    store.record_page(run_id, partition["partition_id"], page, call_id=call_id, at=NOW)
    assert calls == 2
    assert store.status(run_id)["credits_reserved"] == 2
    assert store.report(run_id)["api_calls"] == {
        "ORG_SEARCH:COMPLETED": 1, "ORG_SEARCH:RATE_LIMITED": 1,
    }


def test_future_retry_after_never_bypasses_rate_limit() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(), at=NOW)
    partition = store.partitions(run_id)[0]
    calls = 0

    def rate_limited():
        nonlocal calls
        calls += 1
        raise ApolloProviderError("rate_limited", retry_after=NOW + dt.timedelta(minutes=2))

    with pytest.raises(CensusRetryLater):
        store.execute_call(
            run_id, kind="ORG_SEARCH", subject="future-limit",
            partition_id=partition["partition_id"], credits=1, candidate_slots=25,
            at=NOW, invoke=rate_limited,
            encode=lambda value: value.model_dump(mode="json"),
            decode=SupplierSearchPage.model_validate,
        )
    assert calls == 1
    assert store.status(run_id)["credits_reserved"] == 1


def test_ambiguous_provider_failure_keeps_reservation_and_requires_review() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(), at=NOW)
    partition = store.partitions(run_id)[0]

    def broken():
        raise ApolloProviderError("timeout", detail="founder@example.fr secret-value")

    with pytest.raises(CensusReviewRequired, match="Apollo timeout"):
        store.execute_call(
            run_id, kind="ORG_SEARCH", subject="uncertain-page",
            partition_id=partition["partition_id"], credits=1, candidate_slots=25,
            at=NOW, invoke=broken,
            encode=lambda value: value.model_dump(mode="json"),
            decode=SupplierSearchPage.model_validate,
        )
    assert store.status(run_id)["status"] == "REVIEW_REQUIRED"
    assert store.status(run_id)["credits_reserved"] == 1
    with pytest.raises(CensusReviewRequired):
        store.execute_call(
            run_id, kind="ORG_SEARCH", subject="uncertain-page",
            partition_id=partition["partition_id"], credits=1, candidate_slots=25,
            at=NOW, invoke=broken,
            encode=lambda value: value.model_dump(mode="json"),
            decode=SupplierSearchPage.model_validate,
        )


def test_person_response_cache_expires_without_erasing_credit_or_funnel_counts() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(retention_days=1), at=NOW)
    partition = store.partitions(run_id)[0]
    call = store.reserve_call(
        run_id, kind="PEOPLE_SEARCH", subject="synthetic-person-search", attempt=1,
        partition_id=partition["partition_id"], credits=0, candidate_slots=0, at=NOW,
    )
    store.complete_call(call["call_id"], {"candidates": [{"id": "synthetic"}]}, at=NOW)
    assert store.purge_contact_cache(run_id, at=NOW + dt.timedelta(days=2)) == 1
    assert store.status(run_id)["status"] == "REVIEW_REQUIRED"
    assert store.report(run_id)["contacts_found"] == 1
    with pytest.raises(CensusReviewRequired, match="purged Apollo response"):
        store.execute_call(
            run_id, kind="PEOPLE_SEARCH", subject="synthetic-person-search",
            partition_id=partition["partition_id"], credits=0, candidate_slots=0,
            at=NOW + dt.timedelta(days=2), invoke=lambda: None,
            encode=lambda value: value, decode=lambda value: value,
        )


def test_apollo_display_limit_is_reported_as_coverage_hole() -> None:
    store, run_id = _planned_store()
    store.start(run_id, _limits(), at=NOW)
    partition = store.partitions(run_id)[0]
    page = _page(1, candidates=[_candidate()], total_pages=500, total_entries=50_000)
    call = store.reserve_call(
        run_id, kind="ORG_SEARCH", subject="wide-search", attempt=1,
        partition_id=partition["partition_id"], credits=1, candidate_slots=25, at=NOW,
    )
    store.complete_call(call["call_id"], page.model_dump(mode="json"), at=NOW)
    store.record_page(run_id, partition["partition_id"], page, call_id=call["call_id"], at=NOW)
    assert store.partitions(run_id)[0]["last_error"] == "APOLLO_COVERAGE_LIMIT"
    assert any(
        gap["reason"] == "APOLLO_COVERAGE_LIMIT"
        for gap in store.report(run_id)["coverage_holes"]
    )


@pytest.mark.parametrize(
    "suppressed,recipient_email,expected",
    [
        (False, "founder@cabinet.fr", "SEND"),
        (True, "founder@cabinet.fr", "NO_SEND"),
        (False, "founder@gmail.com", "NO_SEND"),
    ],
)
def test_mocked_apollo_census_policy_never_mutates_instantly(
    suppressed, recipient_email, expected
) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_config()
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    store = CensusStore(engine, require_permit=False)
    run_id = store.plan(program_id=program_id, partitions=build_partitions(config), at=NOW)
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        path = request.url.path
        if path == "/api/v1/mixed_companies/search":
            return httpx.Response(200, json={
                "organizations": [{
                    "id": "org-1", "name": "Cabinet Exemple", "primary_domain": "cabinet.fr",
                    "website_url": "https://cabinet.fr", "country": "France",
                    "industry": "Consulting",
                }],
                "pagination": {"page": 1, "per_page": 25, "total_entries": 1, "total_pages": 1},
            })
        if path == "/api/v1/organizations/org-1":
            return httpx.Response(200, json={"organization": {
                "id": "org-1", "name": "Cabinet Exemple", "primary_domain": "cabinet.fr",
                "website_url": "https://cabinet.fr", "country": "France",
                "industry": "Consulting", "estimated_num_employees": 5,
                "keywords": ["consulting"],
            }})
        if path == "/api/v1/mixed_people/api_search":
            return httpx.Response(200, json={"total_entries": 1, "people": [
                {"id": "person-1", "title": "Founder", "has_email": True}
            ]})
        if path == "/api/v1/people/match":
            return httpx.Response(200, json={"person": {
                "id": "person-1", "organization_id": "org-1", "title": "Founder",
                "email": recipient_email, "email_status": "verified",
            }})
        raise AssertionError("unexpected Apollo endpoint")

    class DNS:
        def __init__(self):
            self.calls = 0

        def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]:
            assert domain == "cabinet.fr"
            self.calls += 1
            return ("smtp.google.com",)

    class ForbiddenInstantly:
        def __getattr__(self, name):
            raise AssertionError(f"Instantly called in SHADOW: {name}")

    client = httpx.Client(transport=httpx.MockTransport(handle))
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    dns = DNS()
    keyring = SuppressionIdentityKeyring(
        current_key_version="v1", keys={"v1": b"test-secret-key"}
    )
    if suppressed:
        suppression = SuppressionStore(engine, keyring, scope=MILOMAIL_SUPPRESSION_SCOPE)
        with engine.begin() as connection:
            suppression.record_for_email_in_transaction(
                connection, recipient_email,
                source=SuppressionSource.UNSUBSCRIBE,
                reason_code=SuppressionReasonCode.UNSUBSCRIBED,
                evidence_ref=suppression_evidence_ref("UNSUBSCRIBE", "synthetic-event"),
                received_at=NOW - dt.timedelta(minutes=1),
            )
    limits = _limits(max_partitions=1, max_pages=1, max_candidates=25,
                     max_enrichments=2, max_apollo_credits=11, max_cost_chf="1.10")
    permits, config_hash, database_id = _test_permits(engine, store, run_id, limits)
    runner = CensusRunner(
        engine,
        census_id=run_id,
        program_id=program_id,
        config=config,
        limits=limits,
        organizations=ApolloOrganizationSearchClient(api_key="synthetic", client=client),
        companies=ApolloCompanyResearchClient(api_key="synthetic", client=client, clock=lambda: NOW),
        contacts=ApolloContactDiscoveryClient(api_key="synthetic", client=client),
        mail_provider=MailProviderDetector(dns),
        company_activity=lambda _: ActiveCompanyEvidence(
            status="ACTIVE", source_url="https://registre.example/org-1",
            source_type="PUBLIC_COMPANY_REGISTRY", observed_at=NOW,
            evidence_id="registry:org-1",
        ),
        acquisition=acquisition,
        shadow=MilomailShadowRuntime(
            engine, acquisition, keyring, ForbiddenInstantly(),
        ),
        operations=ProgramOperationalContext(
            sender_identity_ready=True, opt_out_ready=True, privacy_notice_ready=True,
            source_notice_ready=True, sender_domain="outbound.milomail.example",
            sender_healthy=True, spf_ready=True, dkim_ready=True, dmarc_ready=True,
            warmup_ready=True, landing_active=True, landing_french=True,
            daily_remaining=10, monthly_remaining=100, cost_remaining_chf="10",
        ),
    )
    runner.run(at=NOW, phase="COVERAGE", permit_id=permits["COVERAGE"],
               configuration_hash=config_hash, database_id=database_id)
    runner.run(at=NOW, phase="ENRICHMENT", permit_id=permits["ENRICHMENT"],
               configuration_hash=config_hash, database_id=database_id)
    first = store.candidates(run_id)
    assert len(first) == 1
    assert first[0]["decision"] == expected
    assert first[0]["email_verified"]
    assert dns.calls == 1  # the existing detector cache serves the policy path
    assert seen == [
        "/api/v1/mixed_companies/search", "/api/v1/mixed_people/api_search",
        "/api/v1/organizations/org-1", "/api/v1/people/match",
    ]
    runner.run(at=NOW, phase="ENRICHMENT", permit_id=permits["ENRICHMENT"],
               configuration_hash=config_hash, database_id=database_id)
    assert len(store.candidates(run_id)) == 1
    assert len(seen) == 4
    assert store.status(run_id)["credits_reserved"] == 11
    report = store.report(run_id)
    assert report["organizations_found"] == report["organizations_unique"] == 1
    assert report["contacts_found"] == report["leaders_identified"] == 1
    assert report["google_workspace_confirmed"] == 1
    assert report["recipient_gmail_consumer"] == int(recipient_email.endswith("gmail.com"))
    assert report["verified_addresses_unique"] == 1
    assert report["SEND_theoretical"] == int(expected == "SEND")
    assert report["HOLD"] == 0
    assert report["NO_SEND"] == int(expected == "NO_SEND")
    assert report["suppressions"] == int(suppressed)
    assert report["by_company_size"]["5"][expected] == 1
    assert report["apollo_credits_reserved_upper_bound"] == 11
    assert report["cost_chf_actual"] is None
    assert report["population_estimate_15000_50000"] == "UNMEASURED_HYPOTHESIS"


def test_other_providers_unknown_and_foreign_country_need_no_enrichment() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_config()
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    store = CensusStore(engine, require_permit=False)
    run_id = store.plan(program_id=program_id, partitions=build_partitions(config), at=NOW)
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/mixed_people/api_search":
            return httpx.Response(200, json={"total_entries": 0, "people": []})
        assert request.url.path == "/api/v1/mixed_companies/search"
        organizations = [
            {"id": "org-gmail", "name": "Freelance", "primary_domain": "gmail.com",
             "country": "France", "industry": "Consulting"},
            {"id": "org-ms", "name": "Cabinet Microsoft", "primary_domain": "ms.fr",
             "country": "France", "industry": "Consulting"},
            {"id": "org-unknown", "name": "Cabinet Inconnu", "primary_domain": "unknown.fr",
             "country": "France", "industry": "Consulting"},
            {"id": "org-de", "name": "Firma", "primary_domain": "firma.de",
             "country": "Germany", "industry": "Consulting"},
        ]
        return httpx.Response(200, json={
            "organizations": organizations,
            "pagination": {"page": 1, "per_page": 25, "total_entries": 4, "total_pages": 1},
        })

    class DNS:
        def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]:
            if domain == "ms.fr":
                return ("ms-fr.mail.protection.outlook.com",)
            assert domain == "unknown.fr"
            raise TimeoutError

    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError(f"forbidden call: {name}")

    client = httpx.Client(transport=httpx.MockTransport(handle))
    limits = _limits(max_partitions=1, max_pages=1, max_candidates=25,
                     max_apollo_credits=1, max_cost_chf="0.10")
    permits, config_hash, database_id = _test_permits(engine, store, run_id, limits)
    runner = CensusRunner(
        engine, census_id=run_id, program_id=program_id, config=config,
        limits=limits,
        organizations=ApolloOrganizationSearchClient(api_key="synthetic", client=client),
        companies=NoCalls(), contacts=ApolloContactDiscoveryClient(api_key="synthetic", client=client),
        mail_provider=MailProviderDetector(DNS()), company_activity=NoCalls(),
        acquisition=NoCalls(), shadow=NoCalls(), operations=ProgramOperationalContext(),
    )
    runner.run(at=NOW, phase="COVERAGE", permit_id=permits["COVERAGE"],
               configuration_hash=config_hash, database_id=database_id)
    runner.run(at=NOW, phase="ENRICHMENT", permit_id=permits["ENRICHMENT"],
               configuration_hash=config_hash, database_id=database_id)
    decisions = {row["provider_organization_id"]: row["decision"] for row in store.candidates(run_id)}
    assert decisions == {
        "org-gmail": "NO_SEND", "org-ms": "NO_SEND",
        "org-unknown": "HOLD", "org-de": "NO_SEND",
    }
    report = store.report(run_id)
    assert report["gmail_consumer"] == report["microsoft_365"] == 1
    assert report["provider_unknown"] == 2  # DNS timeout and out-of-country short-circuit
    assert report["HOLD"] == 1
    assert report["NO_SEND"] == 3
    assert report["verified_addresses_unique"] == 0
    assert seen == ["/api/v1/mixed_companies/search"] + [
        "/api/v1/mixed_people/api_search"
    ] * 3
