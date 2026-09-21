"""Apollo census orchestration over existing Kivou research and policy services."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.census import (
    CensusBudgetExceeded,
    CensusLimits,
    CensusPartition,
    CensusRetryLater,
    CensusReviewRequired,
    CensusStore,
)
from signals.acquisition_programs.config import runtime_flags
from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.discovery import build_program_contact_profile
from signals.acquisition_programs.mail_provider import (
    DETECTOR_VERSION,
    MailProvider,
    MailProviderDetector,
    MailProviderEvidence,
    ProviderConfidence,
)
from signals.acquisition_programs.official_company import OfficialSourceRetryLater
from signals.acquisition_programs.pipeline import (
    ActiveCompanyEvidence,
    ProgramDiscoveryPipeline,
    ProgramOperationalContext,
)
from signals.acquisition_programs.qualification import (
    CapacityAssessment,
    FitSignals,
    RecipientCapacity,
    score_fit,
)
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.company_research.contracts import ApolloOrganizationObservation, CompanyResearchProfile
from signals.compliance.milomail_rules import (
    MILOMAIL_PURPOSE,
    MilomailPolicyInput,
    evaluate_milomail,
)
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.contact_discovery.contracts import (
    ApolloEnrichedPerson,
    DecisionMakerSearchProfile,
    PeopleSearchPage,
)
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate, SupplierSearchPage

_ORG_SOURCE = "https://api.apollo.io/api/v1/mixed_companies/search"


class _BudgetedOrganizations:
    def __init__(self, runner: CensusRunner) -> None:
        self._runner = runner

    def search_page(
        self, profile: CensusPartition, *, page: int, observed_at: dt.datetime
    ) -> SupplierSearchPage:
        result, _ = self._runner.store.execute_call(
            self._runner.census_id,
            kind="ORG_SEARCH",
            subject=f"{profile.partition_id}:{page}",
            partition_id=profile.partition_id,
            credits=self._runner.limits.credits_org_search_page,
            candidate_slots=profile.per_page,
            at=observed_at,
            invoke=lambda: self._runner.organizations.search_page(
                profile, page=page, observed_at=observed_at
            ),
            encode=lambda value: value.model_dump(mode="json"),
            decode=lambda value: SupplierSearchPage.model_validate(value),
        )
        return result


class _BudgetedCompanyResearch:
    def __init__(self, runner: CensusRunner) -> None:
        self._runner = runner

    def fetch_organization(self, profile: CompanyResearchProfile) -> ApolloOrganizationObservation:
        result, _ = self._runner.store.execute_call(
            self._runner.census_id,
            kind="ORG_ENRICH",
            subject=profile.provider_organization_id,
            partition_id=self._runner.current_partition_id,
            credits=self._runner.limits.credits_org_enrichment,
            candidate_slots=0,
            at=self._runner.observed_at,
            invoke=lambda: self._runner.companies.fetch_organization(profile),
            encode=lambda value: value.model_dump(mode="json"),
            decode=lambda value: ApolloOrganizationObservation.model_validate(value),
        )
        return result


class _BudgetedContacts:
    def __init__(self, runner: CensusRunner) -> None:
        self._runner = runner

    def search_people(
        self, profile: DecisionMakerSearchProfile, *, observed_at: dt.datetime
    ) -> PeopleSearchPage:
        # Opportunity/supplier refs are local bookkeeping, not Apollo filters.
        filters = profile.model_dump(mode="json", exclude={
            "acquisition_opportunity_id", "supplier_ref", "profile_fingerprint",
        })
        subject = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()
        result, _ = self._runner.store.execute_call(
            self._runner.census_id,
            kind="PEOPLE_SEARCH",
            subject=subject,
            partition_id=self._runner.current_partition_id,
            credits=self._runner.limits.credits_people_search,
            candidate_slots=0,
            at=observed_at,
            invoke=lambda: self._runner.contacts.search_people(profile, observed_at=observed_at),
            encode=lambda value: value.model_dump(mode="json"),
            decode=lambda value: PeopleSearchPage.model_validate(value),
        )
        return result

    def enrich_person(
        self, provider_person_id: str, *, observed_at: dt.datetime
    ) -> ApolloEnrichedPerson | None:
        result, _ = self._runner.store.execute_call(
            self._runner.census_id,
            kind="PERSON_ENRICH",
            subject=provider_person_id,
            partition_id=self._runner.current_partition_id,
            credits=self._runner.limits.credits_person_enrichment_max,
            candidate_slots=0,
            at=observed_at,
            invoke=lambda: self._runner.contacts.enrich_person(
                provider_person_id, observed_at=observed_at
            ),
            encode=lambda value: value.model_dump(mode="json") if value else {"none": True},
            decode=lambda value: (
                None if value == {"none": True} else ApolloEnrichedPerson.model_validate(value)
            ),
        )
        return result


class CensusRunner:
    """Processes only preparatory evidence; Instantly has no callable route here."""

    def __init__(
        self, engine: Engine, *, census_id: str, program_id: str,
        config: AcquisitionProgramConfig, limits: CensusLimits,
        organizations: ApolloOrganizationSearchClient,
        companies: ApolloCompanyResearchClient,
        contacts: ApolloContactDiscoveryClient,
        mail_provider: MailProviderDetector,
        company_activity: Callable[[ApolloOrganizationObservation], ActiveCompanyEvidence],
        company_activity_for_candidate: Callable[
            [ApolloOrganizationObservation, ApolloOrganizationCandidate], ActiveCompanyEvidence
        ] | None = None,
        acquisition: AcquisitionStore,
        shadow: MilomailShadowRuntime,
        operations: ProgramOperationalContext,
    ) -> None:
        if config.program_key != "milomail" or config.campaign_mode != "SHADOW":
            raise ValueError("census requires the SHADOW Milo Mail program")
        if config.enabled:
            raise ValueError("census program must stay disabled for outbound")
        self._engine = engine
        self.store = CensusStore(engine)
        self.census_id = census_id
        self.program_id = program_id
        self.config = config
        self.limits = limits
        self.organizations = organizations
        self.companies = companies
        self.contacts = contacts
        self.mail_provider = mail_provider
        self.current_partition_id: str | None = None
        self.allowed_partitions: frozenset[str] = frozenset()
        self.observed_at = dt.datetime.now(dt.UTC)
        self._pipeline = ProgramDiscoveryPipeline(
            engine,
            config=config,
            flags=runtime_flags({}),
            organizations=_BudgetedOrganizations(self),  # type: ignore[arg-type]
            companies=_BudgetedCompanyResearch(self),  # type: ignore[arg-type]
            contacts=_BudgetedContacts(self),  # type: ignore[arg-type]
            mail_provider=mail_provider,
            company_activity=company_activity,
            company_activity_for_candidate=company_activity_for_candidate,
            acquisition=acquisition,
            shadow=shadow,
            operations=operations,
        )

    def run(self, *, at: dt.datetime, phase: str,
            permit_id: str, configuration_hash: str, database_id: str) -> dict[str, Any]:
        """Resume from persisted cursors; never infer unlimited from missing limits."""
        self.limits.require_run_authorization()
        if phase not in {"COVERAGE", "ENRICHMENT"}:
            raise ValueError("census phase must be COVERAGE or ENRICHMENT")
        from signals.acquisition_programs.census_readiness import PermitStore

        with self._engine.connect() as connection:
            PermitStore.check_call(
                connection, permit_id=permit_id, census_id=self.census_id, phase=phase,
                kind="ORG_SEARCH" if phase == "COVERAGE" else "ORG_ENRICH",
                partition_id=None, credits=0, candidate_slots=0,
                at=dt.datetime.now(dt.UTC), configuration_hash_value=configuration_hash,
                database_id=database_id, check_capacity=False,
            )
            from signals.persistence.schema import acquisition_census_permit

            permitted = connection.execute(sa.select(
                acquisition_census_permit.c.allowed_partitions,
            ).where(acquisition_census_permit.c.permit_id == permit_id)).scalar_one()
        self.allowed_partitions = frozenset(permitted)
        self.store.bind_permit(permit_id=permit_id, phase=phase,
                               configuration_hash=configuration_hash, database_id=database_id)
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("census time must be timezone-aware")
        self.observed_at = at
        self.store.start(self.census_id, self.limits, at=at)
        if phase == "ENRICHMENT":
            if not self._process_pending():
                return self.store.status(self.census_id)
            self.store.finish(self.census_id, at=at)
            if self.store.status(self.census_id)["status"] == "COMPLETE":
                self.store.purge_contact_cache(self.census_id, at=at)
            return self.store.status(self.census_id)
        if not self._coverage_contacts():
            return self.store.status(self.census_id)
        for row in self.store.partitions(self.census_id):
            if row["status"] == "COMPLETE" or row["partition_id"] not in self.allowed_partitions:
                continue
            part = CensusPartition.from_row(row)  # type: ignore[arg-type]
            self.current_partition_id = part.partition_id
            page_number = row["cursor_page"]
            while page_number <= part.max_pages:
                def search_current_page(
                    profile: CensusPartition = part, page: int = page_number,
                ) -> SupplierSearchPage:
                    return self.organizations.search_page(profile, page=page, observed_at=at)

                try:
                    page, call_id = self.store.execute_call(
                        self.census_id,
                        kind="ORG_SEARCH",
                        subject=f"{part.partition_id}:{page_number}",
                        partition_id=part.partition_id,
                        credits=self.limits.credits_org_search_page,
                        candidate_slots=part.per_page,
                        at=at,
                        invoke=search_current_page,
                        encode=lambda value: value.model_dump(mode="json"),
                        decode=lambda value: SupplierSearchPage.model_validate(value),
                    )
                    self.store.record_page(
                        self.census_id, part.partition_id, page, call_id=call_id, at=at
                    )
                    if not self._coverage_contacts():
                        return self.store.status(self.census_id)
                except CensusBudgetExceeded:
                    self.store.pause(self.census_id, part.partition_id, "CENSUS_BUDGET_CAP", at=at)
                    return self.store.status(self.census_id)
                except CensusRetryLater:
                    self.store.pause(self.census_id, part.partition_id, "APOLLO_RATE_LIMIT", at=at)
                    return self.store.status(self.census_id)
                except CensusReviewRequired:
                    self.store.pause(
                        self.census_id, part.partition_id, "APOLLO_REVIEW_REQUIRED",
                        at=at, review=True,
                    )
                    return self.store.status(self.census_id)
                latest = next(
                    value for value in self.store.partitions(self.census_id)
                    if value["partition_id"] == part.partition_id
                )
                if latest["status"] in {"COMPLETE", "INCOMPLETE", "REVIEW_REQUIRED"}:
                    break
                page_number = latest["cursor_page"]
        return self.store.status(self.census_id)

    def _coverage_contacts(self) -> bool:
        """Persist public MX evidence and count people without email reveal."""
        for row in self.store.candidates(self.census_id, status="PENDING"):
            candidate = ApolloOrganizationCandidate.model_validate(row["snapshot"])
            if candidate.country_code != "FR" or not candidate.primary_domain:
                continue
            self.current_partition_id = self.store.permitted_partition_for_candidate(
                row["candidate_id"], self.allowed_partitions,
            )
            if self.current_partition_id is None:
                continue
            self._provider_for_candidate(row, candidate, at=self.observed_at)
            profile = build_program_contact_profile(
                self.config,
                acquisition_opportunity_id=f"census:{row['candidate_id']}",
                supplier_ref=f"census:{row['candidate_id']}",
                provider_organization_id=candidate.provider_organization_id,
                organization_domain=candidate.primary_domain,
            )
            try:
                _BudgetedContacts(self).search_people(profile, observed_at=self.observed_at)
            except CensusBudgetExceeded:
                self.store.pause(self.census_id, self.current_partition_id,
                                 "CENSUS_BUDGET_CAP", at=self.observed_at)
                return False
            except CensusRetryLater:
                self.store.pause(self.census_id, self.current_partition_id,
                                 "APOLLO_RATE_LIMIT", at=self.observed_at)
                return False
            except CensusReviewRequired:
                self.store.pause(self.census_id, self.current_partition_id,
                                 "APOLLO_REVIEW_REQUIRED", at=self.observed_at, review=True)
                return False
        return True

    def _process_pending(self) -> bool:
        for row in self.store.candidates(self.census_id, status="PENDING"):
            candidate = ApolloOrganizationCandidate.model_validate(row["snapshot"])
            self.current_partition_id = self.store.permitted_partition_for_candidate(
                row["candidate_id"], self.allowed_partitions,
            )
            if self.current_partition_id is None:
                continue
            try:
                self._assess(row, candidate)
            except CensusBudgetExceeded:
                self.store.pause(
                    self.census_id, self.current_partition_id, "CENSUS_BUDGET_CAP",
                    at=self.observed_at,
                )
                return False
            except CensusReviewRequired:
                self.store.pause(
                    self.census_id, self.current_partition_id, "APOLLO_REVIEW_REQUIRED",
                    at=self.observed_at, review=True,
                )
                return False
            except CensusRetryLater:
                self.store.pause(
                    self.census_id, self.current_partition_id, "APOLLO_RATE_LIMIT",
                    at=self.observed_at,
                )
                return False
            except OfficialSourceRetryLater:
                self.store.pause(
                    self.census_id, self.current_partition_id, "OFFICIAL_SOURCE_RETRY_LATER",
                    at=self.observed_at,
                )
                return False
        return True

    def _provider_for_candidate(
        self, row: dict[str, Any], candidate: ApolloOrganizationCandidate, *, at: dt.datetime,
    ) -> MailProviderEvidence:
        if candidate.primary_domain is None:
            raise ValueError("provider detection requires a validated domain")
        previous = row["provider_evidence"]
        if (
            isinstance(previous, dict)
            and previous.get("detector_version") == DETECTOR_VERSION
            and dt.datetime.fromisoformat(previous["observed_at"]) <= at
            < dt.datetime.fromisoformat(previous["expires_at"])
        ):
            provider = MailProviderEvidence(
                domain=candidate.primary_domain,
                provider=MailProvider(row["provider"]),
                confidence=ProviderConfidence(row["provider_confidence"]),
                mx_records=tuple(previous["mx_records"]),
                source=previous["source"],
                observed_at=dt.datetime.fromisoformat(previous["observed_at"]),
                expires_at=dt.datetime.fromisoformat(previous["expires_at"]),
            )
        else:
            provider = self.mail_provider.detect_domain(candidate.primary_domain, observed_at=at)
            self.store.record_provider(self.census_id, row["candidate_id"], provider, at=at)
        return provider

    def _assess(self, row: dict[str, Any], candidate: ApolloOrganizationCandidate) -> None:
        at = self.observed_at
        candidate_id = row["candidate_id"]
        if candidate.country_code != "FR":
            self.store.record_decision(
                self.census_id, candidate_id, provider=None, decision="NO_SEND",
                reasons=("COUNTRY_OUT_OF_SCOPE",), at=at,
            )
            return
        if not candidate.primary_domain:
            self.store.record_decision(
                self.census_id, candidate_id, provider=None, decision="HOLD",
                reasons=("DOMAIN_MISSING_OR_INVALID",), at=at,
            )
            return
        provider = self._provider_for_candidate(row, candidate, at=at)
        if provider.provider is not MailProvider.GOOGLE_WORKSPACE:
            minimal = MilomailPolicyInput(
                acquisition_purpose=MILOMAIL_PURPOSE,
                program=self.config,
                country=candidate.country_code,
                provider=provider,
                capacity=CapacityAssessment(
                    capacity=RecipientCapacity.UNKNOWN,
                    reasons=("CONTACT_NOT_ENRICHED",),
                ),
                fit=score_fit(
                    FitSignals(
                        provider=provider.provider,
                        provider_confirmed=provider.confidence is ProviderConfidence.CONFIRMED,
                    ),
                    config=self.config,
                ),
                collection_source_url=_ORG_SOURCE,
                collected_at=candidate.provider_observed_at,
                evidence_ids=(f"apollo-org:{candidate.source_fingerprint}",),
                assessed_at=at,
            )
            decision = evaluate_milomail(minimal)
            self.store.record_decision(
                self.census_id, candidate_id, provider=provider,
                decision=decision.decision, reasons=decision.reason_codes, at=at,
            )
            return
        # The existing candidate assessor owns Kivou research, contact,
        # suppression, scoring and policy. Its Apollo adapters here are all
        # budgeted/cached; its mock-only bulk `run` entrypoint is unchanged.
        self._pipeline._at = at
        result = self._pipeline._assess_candidate(self.program_id, candidate, at)
        self.store.record_decision(
            self.census_id, candidate_id, provider=provider,
            decision=result.decision.decision,
            reasons=result.decision.reason_codes,
            opportunity_id=result.opportunity_id,
            contact_ref=result.contact_ref,
            at=at,
        )


__all__ = ["CensusRunner"]
