"""Bounded SHADOW account discovery using Kivou's Apollo and evidence stores."""

from __future__ import annotations

import datetime as dt
import hashlib
import unicodedata
from collections.abc import Callable
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import EventType
from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.contracts import AcquisitionProgramConfig, ProgramRuntimeFlags
from signals.acquisition_programs.discovery import (
    build_program_contact_profile,
    build_program_search_profile,
)
from signals.acquisition_programs.mail_provider import (
    MailProviderDetector,
    ProviderConfidence,
    normalize_domain,
)
from signals.acquisition_programs.qualification import (
    CapacityAssessment,
    FitSignals,
    ProfessionalEvidenceInput,
    RecipientCapacity,
    classify_recipient,
    score_fit,
)
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.company_research.contracts import ApolloOrganizationObservation
from signals.company_research.profile import build_company_research_profile
from signals.compliance.milomail_rules import (
    MILOMAIL_PURPOSE,
    MilomailPolicyDecision,
    MilomailPolicyInput,
)
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.contact_discovery.contracts import ContactObservation
from signals.contact_discovery.ranking import rank_candidates
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient
from signals.supplier_discovery.identity import acquisition_identity_for
from signals.supplier_discovery.store import SupplierDiscoveryStore

_APOLLO_ORGANIZATION_SOURCE = "https://api.apollo.io/api/v1/mixed_companies/search"
_APOLLO_PERSON_SOURCE = "https://api.apollo.io/api/v1/people/match"


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ActiveCompanyEvidence(_ClosedModel):
    status: Literal["ACTIVE", "INACTIVE", "UNKNOWN"]
    source_url: str | None = None
    source_type: str | None = None
    observed_at: dt.datetime | None = None
    evidence_id: str | None = None

    @model_validator(mode="after")
    def proof_for_status(self) -> ActiveCompanyEvidence:
        if self.status != "UNKNOWN" and not all(
            (
                self.source_url,
                self.source_type,
                self.observed_at,
                self.evidence_id,
            )
        ):
            raise ValueError("known company activity requires dated public evidence")
        if self.source_url:
            parsed = urlsplit(self.source_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("company activity source must be HTTPS")
            normalize_domain(parsed.hostname)
        if self.observed_at and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("company activity observation must be timezone-aware")
        return self


class ProgramOperationalContext(_ClosedModel):
    sender_identity_ready: bool = False
    opt_out_ready: bool = False
    privacy_notice_ready: bool = False
    source_notice_ready: bool = False
    sender_domain: str | None = None
    sender_healthy: bool = False
    spf_ready: bool = False
    dkim_ready: bool = False
    dmarc_ready: bool = False
    warmup_ready: bool = False
    landing_active: bool = False
    landing_french: bool = False
    daily_remaining: int = Field(default=0, ge=0)
    monthly_remaining: int = Field(default=0, ge=0)
    cost_remaining_chf: Decimal = Field(default=Decimal(0), ge=0)


class PipelineResult(_ClosedModel):
    program_id: str
    opportunity_id: str
    supplier_ref: str
    contact_ref: str | None
    decision: MilomailPolicyDecision


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _match_one(texts: tuple[str, ...], terms: dict[str, tuple[str, ...]]) -> str | None:
    haystack = " ".join(_fold(text) for text in texts)
    matches = [
        key
        for key, phrases in terms.items()
        if any(_fold(phrase) in haystack for phrase in phrases)
    ]
    return matches[0] if len(matches) == 1 else None


class ProgramDiscoveryPipeline:
    def __init__(
        self,
        engine: Engine,
        *,
        config: AcquisitionProgramConfig,
        flags: ProgramRuntimeFlags,
        organizations: ApolloOrganizationSearchClient,
        companies: ApolloCompanyResearchClient,
        contacts: ApolloContactDiscoveryClient,
        mail_provider: MailProviderDetector,
        company_activity: Callable[[ApolloOrganizationObservation], ActiveCompanyEvidence],
        acquisition: AcquisitionStore,
        shadow: MilomailShadowRuntime,
        operations: ProgramOperationalContext,
    ) -> None:
        self._engine = engine
        self._config = config
        self._flags = flags
        self._organizations = organizations
        self._companies = companies
        self._contacts = contacts
        self._mail_provider = mail_provider
        self._company_activity = company_activity
        self._acquisition = acquisition
        self._shadow = shadow
        self._operations = operations
        self._suppliers = SupplierDiscoveryStore(engine, clock=lambda: self._at)
        self._contact_store = ContactDiscoveryStore(engine, clock=lambda: self._at)
        self._at = dt.datetime.now(dt.UTC)

    def run(self, *, program_id: str, observed_at: dt.datetime) -> tuple[PipelineResult, ...]:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("discovery time must be timezone-aware")
        if not self._config.enabled or not self._flags.enabled:
            return ()
        if self._config.program_key != "milomail" or self._config.campaign_mode != "SHADOW":
            raise ValueError("Milo Mail discovery is locked to SHADOW")
        if (
            "FR" not in self._flags.allowed_countries
            or "GOOGLE_WORKSPACE" not in self._flags.allowed_providers
        ):
            return ()
        # SPEC-019 currently denies every executable command in SHADOW and its
        # supplier command is procurement-seeded. Until a reviewed generic
        # preparatory command is added, only in-process Apollo mocks may run.
        if not all(
            isinstance(getattr(adapter._client, "_transport", None), httpx.MockTransport)
            for adapter in (self._organizations, self._companies, self._contacts)
        ):
            raise RuntimeError("SHADOW discovery requires mocked Apollo transports")
        self._at = observed_at
        profile = build_program_search_profile(self._config)
        results: list[PipelineResult] = []
        seen: set[str] = set()
        for page_number in range(1, profile.max_pages + 1):
            page = self._organizations.search_page(
                profile,
                page=page_number,
                observed_at=observed_at,
            )
            for candidate in page.candidates:
                if candidate.provider_organization_id in seen:
                    continue
                seen.add(candidate.provider_organization_id)
                if candidate.country_code != "FR" or not candidate.primary_domain:
                    continue
                results.append(self._assess_candidate(program_id, candidate, observed_at))
            if page_number >= page.total_pages:
                break
        return tuple(results)

    def _assess_candidate(self, program_id, candidate, at: dt.datetime) -> PipelineResult:
        supplier = self._suppliers.upsert_supplier(candidate).supplier
        signal_ref = f"acquisition-program:{self._config.program_key}"
        identity_key = acquisition_identity_for(signal_ref, supplier.supplier_ref)
        created = self._acquisition.create_opportunity(
            identity_key=identity_key,
            signal_ref=signal_ref,
            supplier_ref=supplier.supplier_ref,
            idempotency_key=identity_key,
            reason_codes=("PROGRAM_DISCOVERED",),
            evidence_refs=(f"apollo-org:{candidate.source_fingerprint}",),
            policy_version=self._config.policy_version,
            occurred_at=candidate.provider_observed_at,
        )
        opportunity_id = created.projection.acquisition_opportunity_id
        company = self._companies.fetch_organization(
            build_company_research_profile(candidate.provider_organization_id)
        )
        activity = self._company_activity(company)
        if activity.observed_at and activity.observed_at > at:
            raise ValueError("company activity evidence is in the future")
        company_domain = company.provider_primary_domain or candidate.primary_domain
        if company_domain != candidate.primary_domain:
            company_domain = None
        sector = _match_one(
            (company.provider_industry or "", *company.provider_keywords),
            self._config.sector_terms,
        )
        role = None
        person = None
        contact_ref = None
        if company_domain:
            contact_profile = build_program_contact_profile(
                self._config,
                acquisition_opportunity_id=opportunity_id,
                supplier_ref=supplier.supplier_ref,
                provider_organization_id=candidate.provider_organization_id,
                organization_domain=company_domain,
            )
            people = self._contacts.search_people(contact_profile, observed_at=at)
            for ranked in rank_candidates(people.candidates)[
                : contact_profile.max_enrichment_attempts
            ]:
                selected_role = _match_one((ranked.candidate.title,), self._config.role_terms)
                if selected_role not in self._config.target_roles or not ranked.candidate.has_email:
                    continue
                enriched = self._contacts.enrich_person(
                    ranked.candidate.provider_person_id,
                    observed_at=at,
                )
                if (
                    enriched is None
                    or enriched.provider_organization_id != candidate.provider_organization_id
                    or enriched.provider_email_status != "verified"
                    or not enriched.business_email
                ):
                    continue
                observation = ContactObservation(
                    supplier_ref=supplier.supplier_ref,
                    provider_person_id=enriched.provider_person_id,
                    provider_organization_id=candidate.provider_organization_id,
                    first_name=enriched.first_name,
                    last_name=enriched.last_name,
                    display_name=enriched.display_name,
                    title=enriched.title,
                    normalized_title=ranked.normalized_title,
                    role_profile_version=contact_profile.profile_version,
                    role_tier=ranked.role_tier,
                    business_email=enriched.business_email,
                    provider_observed_at=enriched.provider_observed_at,
                    email_observed_at=enriched.provider_observed_at,
                    source_fingerprint=enriched.source_fingerprint,
                )
                contact_ref = self._contact_store.upsert_contact(observation).contact.contact_ref
                person, role = enriched, selected_role
                break
        if contact_ref:
            with self._engine.begin() as connection:
                current = self._acquisition.get_opportunity_in_transaction(
                    connection,
                    opportunity_id,
                    for_update=True,
                )
                if current.contact_ref is None:
                    self._acquisition.append_in_transaction(
                        connection,
                        opportunity_id,
                        event_type=EventType.CONTACT_SELECTED,
                        expected_version=current.stream_version,
                        idempotency_key=f"program-contact:{contact_ref}",
                        payload={"contact_ref": contact_ref, "supplier_ref": supplier.supplier_ref},
                        occurred_at=at,
                    )
                elif current.contact_ref != contact_ref:
                    raise ValueError("program opportunity has a different selected contact")
        provider = (
            self._mail_provider.detect_email(person.business_email, observed_at=at)
            if person and person.business_email
            else self._mail_provider.detect_domain(
                company_domain or candidate.primary_domain, observed_at=at
            )
        )
        capacity = (
            classify_recipient(
                ProfessionalEvidenceInput(
                    email=person.business_email,
                    company_domain=company_domain,
                    company_id=supplier.supplier_ref,
                    company_active=activity.status == "ACTIVE",
                    role=role,
                    email_verified=True,
                    professional_source_url=_APOLLO_PERSON_SOURCE,
                    professional_source_type="APOLLO_VERIFIED_BUSINESS_CONTACT",
                    professional_evidence_observed_at=person.provider_observed_at,
                    email_explicitly_published=False,
                ),
                config=self._config,
                at=at,
            )
            if person and person.business_email
            else CapacityAssessment(
                capacity=RecipientCapacity.UNKNOWN,
                reasons=("DECISION_MAKER_OR_VERIFIED_EMAIL_MISSING",),
                company_id=supplier.supplier_ref,
            )
        )
        fit = score_fit(
            FitSignals(
                provider=provider.provider,
                provider_confirmed=provider.confidence is ProviderConfidence.CONFIRMED,
                sector=sector,
                role=role,
                employee_count=company.provider_employee_count,
                public_contact_channel_sources=(company.provider_website_url,)
                if company.provider_website_url
                else (),
                operational_decision_maker=role is not None,
            ),
            config=self._config,
        )
        evidence_ids = [
            f"apollo-org:{candidate.source_fingerprint}",
            f"apollo-company:{company.provider_source_fingerprint}",
            f"mx:{hashlib.sha256('|'.join(provider.mx_records).encode()).hexdigest()}",
        ]
        if person:
            evidence_ids.append(f"apollo-contact:{person.source_fingerprint}")
        if activity.evidence_id:
            evidence_ids.append(activity.evidence_id)
        policy = MilomailPolicyInput(
            acquisition_purpose=MILOMAIL_PURPOSE,
            program=self._config,
            country=candidate.country_code,
            sector=sector,
            employee_count=company.provider_employee_count,
            company_active=(
                True
                if activity.status == "ACTIVE"
                else False
                if activity.status == "INACTIVE"
                else None
            ),
            company_active_source_url=activity.source_url,
            company_active_source_type=activity.source_type,
            company_active_observed_at=activity.observed_at,
            company_active_evidence_id=activity.evidence_id,
            business_relevance_confirmed=sector is not None,
            provider=provider,
            capacity=capacity,
            fit=fit,
            email_verified=person is not None,
            collection_source_url=_APOLLO_PERSON_SOURCE if person else _APOLLO_ORGANIZATION_SOURCE,
            collected_at=at,
            suppression_coverage_safe=person is not None,
            evidence_ids=tuple(evidence_ids),
            assessed_at=at,
            **self._operations.model_dump(mode="python"),
        )
        decision = self._shadow.evaluate(
            program_id=program_id,
            opportunity_id=opportunity_id,
            email=person.business_email if person else None,
            policy_input=policy,
        )
        return PipelineResult(
            program_id=program_id,
            opportunity_id=opportunity_id,
            supplier_ref=supplier.supplier_ref,
            contact_ref=contact_ref,
            decision=decision,
        )


__all__ = [
    "ActiveCompanyEvidence",
    "PipelineResult",
    "ProgramDiscoveryPipeline",
    "ProgramOperationalContext",
]
