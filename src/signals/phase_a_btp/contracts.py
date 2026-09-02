"""Closed contracts for the provider-free Phase A BTP demonstration."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CommercialState(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    VISIBLE_DASHBOARD = "VISIBLE_DASHBOARD"
    OUTBOUND_READY = "OUTBOUND_READY"


class EnrichmentLevel(StrEnum):
    OFFICIAL_SOURCE = "OFFICIAL_SOURCE"
    DCE_ANALYZED = "DCE_ANALYZED"


class FreshnessBucket(StrEnum):
    DAYS_0_90 = "0_90_days"
    DAYS_91_180 = "91_180_days"
    DAYS_181_365 = "181_365_days"
    OVER_ONE_YEAR = "over_one_year"


class Location(Contract):
    country: NonEmpty | None = None
    locality: NonEmpty | None = None
    postal_code: NonEmpty | None = None
    subdivision_code: NonEmpty | None = None

    @property
    def precise(self) -> bool:
        return any((self.locality, self.postal_code, self.subdivision_code))


class AwardSnapshot(Contract):
    opportunity_key: NonEmpty
    signal_key: NonEmpty
    award_key: NonEmpty
    awardee_name: NonEmpty | None = None
    awardee_siret: NonEmpty | None = None
    buyer_name: NonEmpty | None = None
    title: NonEmpty | None = None
    lot_title: NonEmpty | None = None
    description: NonEmpty | None = None
    cpv_main: Annotated[str, StringConstraints(pattern=r"^\d{8}$")] | None = None
    cpv_additional: tuple[Annotated[str, StringConstraints(pattern=r"^\d{8}$")], ...] = ()
    amount: NonEmpty | None = None
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    location: Location | None = None
    event_date: dt.date | None = None
    award_date: dt.date | None = None
    notification_date: dt.date | None = None
    publication_date: dt.date | None = None
    contract_start_date: dt.date | None = None
    contract_end_date: dt.date | None = None
    duration_value: int | None = Field(default=None, ge=1)
    duration_unit: NonEmpty | None = None
    source_system: NonEmpty
    source_notice_id: NonEmpty
    source_url: NonEmpty | None = None
    dce_document_ids: tuple[NonEmpty, ...] = ()
    target_profile_label: NonEmpty | None = None
    target_offer_summary: str = ""
    target_offers: tuple[NonEmpty, ...] = ()
    trade_domain: NonEmpty | None = None


class EligibilityResult(Contract):
    visible_dashboard: bool
    outbound_ready: bool
    commercial_state: CommercialState
    enrichment_level: EnrichmentLevel
    freshness_bucket: FreshnessBucket
    age_days: int
    execution_probably_ongoing: bool
    outbound_reason: NonEmpty
    concrete_information: tuple[NonEmpty, ...]
    operational_elements: tuple[NonEmpty, ...]
    reasons: tuple[NonEmpty, ...]
    recoverable_siret: bool


class OfficialFacts(Contract):
    awardee: NonEmpty
    buyer: NonEmpty | None = None
    object: NonEmpty
    lot: NonEmpty | None = None
    amount: NonEmpty | None = None
    date: dt.date
    location: NonEmpty
    cpv: NonEmpty
    source_system: NonEmpty
    source_notice_id: NonEmpty
    source_url: NonEmpty


class PotentialNeed(Contract):
    statement: NonEmpty
    based_on: NonEmpty


class ShowcaseSignal(Contract):
    opportunity_key: NonEmpty
    signal_key: NonEmpty
    award_key: NonEmpty
    specialty: NonEmpty
    specificity_score: int = Field(ge=0)
    official_facts: OfficialFacts
    operational_elements: tuple[NonEmpty, ...] = Field(min_length=1)
    potential_needs_title: str = "Besoins potentiels à qualifier"
    potential_needs: tuple[PotentialNeed, ...] = Field(min_length=1, max_length=3)
    fit_reason: NonEmpty
    recommended_action: NonEmpty
    contact_roles: tuple[NonEmpty, ...] = Field(min_length=1, max_length=3)
    to_qualify: tuple[NonEmpty, ...] = Field(max_length=3)
    visible_dashboard: bool
    outbound_ready: bool
    outbound_reason: NonEmpty
    freshness_bucket: FreshnessBucket
    age_days: int = Field(ge=0)
    enrichment_level: EnrichmentLevel


class FreshnessDistribution(Contract):
    days_0_90: int = Field(ge=0)
    days_91_180: int = Field(ge=0)
    days_181_365: int = Field(ge=0)
    over_one_year: int = Field(ge=0)


class PhaseABtpReport(Contract):
    schema_version: str = "phase-a-btp-report-v1"
    evaluated_on: dt.date
    corpus_total: int = Field(ge=0)
    btp_total: int = Field(ge=0)
    exploitable_total: int = Field(ge=0)
    insufficient_total: int = Field(ge=0)
    siret_recovery_candidates: int = Field(ge=0)
    dce_available: int = Field(ge=0)
    outbound_ready_total: int = Field(ge=0)
    freshness: FreshnessDistribution
    showcase: tuple[ShowcaseSignal, ...] = Field(max_length=10)
