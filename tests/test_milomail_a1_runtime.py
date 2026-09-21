"""A1 executes only selected organization pages and public MX/legal checks."""

import datetime as dt

import httpx
import pytest
from test_milomail_a0_prepaid import _pricing
from test_milomail_a1_permit import _a1_limits, _a1_permit
from test_milomail_a1_plan import _a0
from test_milomail_policy import ready_config

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.census import CensusStore
from signals.acquisition_programs.census_readiness import (
    DatabaseAuthorization,
    PermitStore,
    configuration_hash,
)
from signals.acquisition_programs.census_runtime import CensusRunner
from signals.acquisition_programs.census_sampling import SamplePlanStore
from signals.acquisition_programs.census_statistics import sample_report
from signals.acquisition_programs.mail_provider import MailProviderDetector
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialSourceConfig,
)
from signals.acquisition_programs.pipeline import ActiveCompanyEvidence, ProgramOperationalContext
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


class NoCalls:
    def __getattr__(self, name):
        raise AssertionError(f"forbidden external operation in A1: {name}")


class GoogleDNS:
    def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]:
        assert domain == "agence.fr"
        return ("smtp.google.com",)


def test_a1_one_depth_page_then_resume_uses_cache_and_never_contacts(monkeypatch) -> None:
    engine, census_id = _a0()
    store = CensusStore(engine)
    plan = SamplePlanStore(engine).plan(
        census_id, permit_id="synthetic-a1-permit", max_new_pages=1, at=NOW,
    )
    selected = plan["pages"][0]
    limits = _a1_limits(max_pages=10, max_candidates=250, max_apollo_credits=10)
    pricing = _pricing(credit_balance=2126,
                       source_reference="operator-a1-prepaid-2026-09-21")
    source = OfficialSourceConfig(enabled=True, max_requests=600, rate_limit_per_minute=60)
    auth = DatabaseAuthorization(
        database_id="postgresql:0123456789abcdef:kivou_milomail_census_a0",
        environment="staging", issued_by_reference="synthetic-operator",
        expires_at=NOW + dt.timedelta(hours=3),
    )
    monkeypatch.setattr(DatabaseAuthorization, "check", lambda *_args, **_kwargs: None)
    digest = configuration_hash(
        census_id=census_id, limits=limits, partitions=store.partitions(census_id),
        pricing=pricing, source_config=source, sample_plan_hash=plan["plan_hash"],
    )
    permit = _a1_permit(
        census_id=census_id, database_id=auth.database_id,
        allowed_partitions=tuple(row["partition_id"] for row in store.partitions(census_id)),
        max_pages=1, max_candidates=25, max_credits=1,
        sample_plan_hash=plan["plan_hash"], configuration_hash=digest,
    )
    PermitStore(engine).issue(permit, database=auth, pricing=pricing,
                              limits=limits, source_config=source, at=NOW)
    apollo_calls: list[int] = []

    def apollo_response(request):
        assert request.url.path == "/api/v1/mixed_companies/search"
        page = int(request.url.params["page"])
        assert page == selected["page"]
        apollo_calls.append(page)
        return httpx.Response(200, json={
            "organizations": [{"id": "org-a1", "name": "Agence Exemple",
                               "primary_domain": "agence.fr", "city": "Paris",
                               "postal_code": "75001", "country": "France"}],
            "pagination": {"page": page, "per_page": 25,
                           "total_entries": 750, "total_pages": 30},
        })

    official_calls: list[str] = []

    def official_response(request):
        official_calls.append(request.url.path)
        return httpx.Response(200, json={
            "results": [{"siren": "123456789", "nom_raison_sociale": "Agence Exemple",
                         "etat_administratif": "A",
                         "siege": {"siret": "12345678900001", "libelle_commune": "Paris",
                                   "code_postal": "75001", "etat_administratif": "A"}}],
            "total_results": 1,
        })

    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    runner = CensusRunner(
        engine, census_id=census_id, program_id=store.status(census_id)["program_id"],
        config=ready_config(), limits=limits,
        organizations=ApolloOrganizationSearchClient(
            api_key="synthetic", client=httpx.Client(transport=httpx.MockTransport(apollo_response))),
        companies=NoCalls(), contacts=NoCalls(), mail_provider=MailProviderDetector(GoogleDNS()),
        company_activity=lambda _: ActiveCompanyEvidence(status="UNKNOWN"),
        acquisition=acquisition,
        shadow=MilomailShadowRuntime(engine, acquisition, SuppressionIdentityKeyring(
            current_key_version="v1", keys={"v1": b"synthetic-key-material"},
        ), NoCalls()),
        operations=ProgramOperationalContext(),
        official_matcher=OfficialCompanyMatcher(
            engine, source, census_id=census_id,
            client=httpx.Client(transport=httpx.MockTransport(official_response))),
    )
    for _ in range(2):
        runner.run(at=NOW, phase="COVERAGE_A1_SAMPLE", permit_id=permit.permit_id,
                   configuration_hash=digest, database_id=auth.database_id)
    assert apollo_calls == [selected["page"]]
    assert official_calls == ["/search"]
    assert SamplePlanStore(engine).details(permit.permit_id)["pages"][0]["status"] == "COMPLETED"
    report = store.report(census_id)
    assert report["contacts_found"] == report["verified_addresses_unique"] == 0
    assert report["SEND_theoretical"] == report["HOLD"] == report["NO_SEND"] == 0
    sample = sample_report(engine, census_id, permit.permit_id)
    assert sample["apollo_declared_total_sum"] == 9 * 750
    assert sample["organizations_observed"] == sample["organizations_unique_observed"] == 1
    assert sample["google_workspace_observed"] == 1
    assert sample["pages_a1_completed"] == 1
    assert sample["contacts_verified"] == sample["email_addresses_verified"] == 0
    PermitStore(engine).revoke(permit.permit_id)
    with pytest.raises(ValueError):
        runner.run(at=NOW, phase="COVERAGE_A1_SAMPLE", permit_id=permit.permit_id,
                   configuration_hash=digest, database_id=auth.database_id)
