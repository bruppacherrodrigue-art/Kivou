"""Five-firm B0 micro-pilot with synthetic Apollo and no sending adapter."""

import datetime as dt
from decimal import Decimal

import sqlalchemy as sa
from test_milomail_a1_plan import _a0
from test_milomail_policy import ready_config

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import CensusLimits
from signals.acquisition_programs.census_b0 import B0PlanStore, B0Runner
from signals.acquisition_programs.census_readiness import ExecutionPermit
from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderEvidence,
    ProviderConfidence,
)
from signals.acquisition_programs.official_company import OfficialMatch
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.contracts import (
    ApolloEnrichedPerson,
    PeopleSearchCandidate,
    PeopleSearchPage,
)
from signals.persistence.schema import (
    acquisition_census_candidate,
    acquisition_census_occurrence,
    acquisition_census_partition,
    acquisition_census_permit,
    acquisition_census_run,
)
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


class SyntheticApollo:
    def __init__(self) -> None:
        self.balance = 600
        self.searches = 0
        self.matches = 0
        self.probes = 0

    def account(self) -> ApolloAccountState:
        self.probes += 1
        return ApolloAccountState(True, self.balance, True, True,
                                  {"lead_credit": self.balance}, None, None,
                                  self.searches, self.matches)

    def search_people(self, profile, *, observed_at):
        self.searches += 1
        return PeopleSearchPage(total_entries=1,
                                candidates=(PeopleSearchCandidate(
                                    provider_person_id=profile.provider_organization_id,
                                    title="Founder", provider_position=0, has_email=True,
                                ),), rejections=(), observed_at=observed_at)

    def enrich_person(self, provider_person_id, *, observed_at):
        self.matches += 1
        self.balance -= 1
        suffix = provider_person_id.rsplit("-", 1)[1]
        return ApolloEnrichedPerson(
            provider_person_id=provider_person_id,
            provider_organization_id=provider_person_id,
            title="Founder", business_email=f"alice@synthetic-{suffix}.fr",
            provider_email_status="verified", provider_observed_at=observed_at,
            source_fingerprint="b" * 64,
        )


class SyntheticMX:
    def detect_domain(self, domain, *, observed_at):
        return MailProviderEvidence(domain, MailProvider.GOOGLE_WORKSPACE,
                                    ProviderConfidence.CONFIRMED,
                                    ("smtp.google.com",), "DNS_MX", observed_at,
                                    observed_at + dt.timedelta(days=1))


class UnprovenOfficial:
    def assess_with_legal_page(self, candidate, *, resolver, at):
        return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                             observed_at=at, match_reasons=("NO_CORROBORATED_MATCH",))


def test_micro_pilot_and_resume_use_only_cached_contact_calls() -> None:
    engine, census_id = _a0()
    with engine.begin() as connection:
        connection.execute(sa.update(acquisition_census_run).where(
            acquisition_census_run.c.census_id == census_id,
        ).values(pages_reserved=90, credits_reserved=90,
                 candidate_slots_reserved=2250, active_sample_plan_id="synthetic-a1"))
        parts = connection.execute(sa.select(acquisition_census_partition).where(
            acquisition_census_partition.c.census_id == census_id,
        ).order_by(acquisition_census_partition.c.partition_id)).mappings().all()
        for index in range(6):
            part = parts[index]
            organization = ApolloOrganizationCandidate(
                provider_organization_id=f"synthetic-org-{index}",
                display_name=f"Synthetic firm {index}", normalized_name=f"synthetic firm {index}",
                primary_domain=f"synthetic-{index}.fr", country_code="FR",
                provider_observed_at=NOW, source_fingerprint="a" * 64,
            )
            candidate_id = f"{index:064x}"
            connection.execute(sa.insert(acquisition_census_candidate).values(
                candidate_id=candidate_id, census_id=census_id,
                provider_organization_id=organization.provider_organization_id,
                primary_domain=organization.primary_domain,
                snapshot=organization.model_dump(mode="json"), sector=part["sector"],
                location=None, company_size=None, role=None, provider="GOOGLE_WORKSPACE",
                provider_confidence="CONFIRMED", provider_evidence={"mx": "google"},
                recipient_provider=None, recipient_provider_confidence=None,
                contact_found=False, leader_identified=False, email_verified=False,
                opportunity_id=None, contact_ref=None, status="PENDING", decision=None,
                reason_codes=[], created_at=NOW, updated_at=NOW,
            ))
            connection.execute(sa.insert(acquisition_census_occurrence).values(
                partition_id=part["partition_id"], candidate_id=candidate_id,
                first_page=1, observed_at=NOW,
            ))
    plan = B0PlanStore(engine).plan(census_id, permit_id="synthetic-b0-run",
                                    pool_balance=600, max_companies=6,
                                    max_credits=100, at=NOW)
    permit = ExecutionPermit(
        permit_id="synthetic-b0-run", census_id=census_id,
        phase="CONTACT_YIELD_B0", environment="staging",
        database_id="postgresql:0123456789abcdef:kivou_milomail_census_a0",
        allowed_partitions=tuple(part["partition_id"] for part in parts),
        max_pages=0, max_candidates=6, max_enrichments=10, max_credits=100,
        max_cost_chf=Decimal(0), price_chf_per_credit=None,
        billing_basis="PREPAID_SHARED_POOL", apollo_secret_ref="KIVOU_APOLLO_API_KEY",
        pricing_reference="synthetic-pricing", configuration_hash="c" * 64,
        sample_plan_hash=plan["plan_hash"], issued_by_reference="synthetic-test",
        issued_at=NOW, valid_from=NOW, expires_at=NOW + dt.timedelta(hours=2),
    )
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_permit).values(
            **permit.model_dump(mode="python")))
    apollo = SyntheticApollo()
    runner = B0Runner(
        engine, census_id=census_id, permit_id=permit.permit_id,
        config=ready_config(),
        limits=CensusLimits(enabled=True, authorization_ref="synthetic-b0",
                            max_partitions=9, max_pages=90, max_candidates=2450,
                            max_enrichments=10, max_apollo_credits=190,
                            max_cost_chf=Decimal(0), chf_per_credit_ceiling=Decimal(0)),
        database_id=permit.database_id, configuration_hash=permit.configuration_hash,
        contacts=apollo, account_probe=apollo.account, detector=SyntheticMX(),
        official=UnprovenOfficial(), legal_pages=object(),
        suppression_keys=SuppressionIdentityKeyring("v1", {"v1": b"synthetic-key"}),
    )
    first = runner.run(at=NOW, micro_only=True)
    assert first["completed"] == 5
    assert first["google_workspace_emails"] == 5
    assert first["by_decision"] == {"HOLD": 5}
    assert first["credits_reserved_upper_bound"] == 45
    assert first["observed_credit_delta_by_operation"]["PERSON_ENRICH"]["sum"] == 5
    assert apollo.balance == 595 and apollo.searches == apollo.matches == 5
    second = runner.run(at=NOW, micro_only=True)
    assert second == first
    assert apollo.searches == apollo.matches == 5
    assert second["instantly_mutations"] == second["emails_sent"] == 0
    probes_before_continuation = apollo.probes
    final = runner.run(at=NOW, micro_only=False)
    assert final["completed"] == 6
    assert final["second_candidates_attempted"] == 0
    assert final["free_searches_documented_unprobed"] == 1
    assert apollo.searches == apollo.matches == 6
    assert apollo.probes - probes_before_continuation == 3  # paid match before/after + final
