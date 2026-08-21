"""Deterministic construction of PII-free decision inputs."""

from __future__ import annotations

import datetime as dt

from signals.company_research.contracts import CompanySizeBand, ResearchCompleteness
from signals.decision_engine.contracts import (
    INPUT_VERSION,
    AcquisitionDecisionInput,
    DecisionPolicyConfig,
    PublicDecisionContext,
    RecencyBasis,
)
from signals.decision_engine.policy import semantic_fingerprint
from signals.supplier_discovery.contracts import SupplierIdentityStatus


def build_public_decision_context(
    *,
    opportunity_key: str,
    representative_award_key: str,
    source_event_key: str,
    award_date: dt.date | None,
    contract_notification_date: dt.date | None,
    publication_date: dt.date | None,
    public_evidence_refs: tuple[str, ...],
) -> PublicDecisionContext:
    values = {
        "opportunity_key": opportunity_key,
        "representative_award_key": representative_award_key,
        "source_event_key": source_event_key,
        "award_date": award_date,
        "contract_notification_date": contract_notification_date,
        "publication_date": publication_date,
        "public_evidence_refs": public_evidence_refs,
    }
    return PublicDecisionContext(
        **values,
        public_context_fingerprint=semantic_fingerprint(values),
    )


def _resolve_recency(
    context: PublicDecisionContext,
    *,
    as_of_date: dt.date,
    policy_config: DecisionPolicyConfig,
) -> tuple[RecencyBasis, dt.date | None, int | None, bool]:
    if context.award_date is not None:
        basis = RecencyBasis.AWARD_DATE
        selected = context.award_date
    elif context.contract_notification_date is not None:
        basis = RecencyBasis.CONTRACT_NOTIFICATION_DATE
        selected = context.contract_notification_date
    elif context.publication_date is not None:
        basis = RecencyBasis.PUBLICATION_DATE
        selected = context.publication_date
    else:
        return RecencyBasis.UNRESOLVED, None, None, False

    age_days = (as_of_date - selected).days
    inconsistent = (
        age_days < -policy_config.future_date_tolerance_days
        or age_days > policy_config.max_plausible_public_age_days
    )
    if (
        context.award_date is not None
        and context.publication_date is not None
        and (context.award_date - context.publication_date).days
        > policy_config.award_publication_tolerance_days
    ):
        inconsistent = True
    return basis, selected, age_days, inconsistent


def build_acquisition_decision_input(
    *,
    acquisition_opportunity_id: str,
    signal_ref: str,
    supplier_ref: str,
    contact_ref: str,
    company_prebuild_version: str,
    company_prebuild_fingerprint: str,
    size_band_version: str,
    profile_supplier_identity_status: SupplierIdentityStatus,
    current_supplier_identity_status: SupplierIdentityStatus,
    profile_contact_role_profile_version: str,
    profile_contact_role_tier: int,
    current_contact_role_profile_version: str,
    current_contact_role_tier: int,
    current_contact_verification_state: str,
    current_contact_verification_provider: str,
    current_contact_provider_email_status: str,
    research_completeness: ResearchCompleteness,
    research_gaps: tuple[str, ...],
    size_band: CompanySizeBand,
    public_context: PublicDecisionContext,
    as_of_date: dt.date,
    policy_config: DecisionPolicyConfig,
) -> AcquisitionDecisionInput:
    basis, recency_date, age_days, inconsistent = _resolve_recency(
        public_context,
        as_of_date=as_of_date,
        policy_config=policy_config,
    )
    values = {
        "input_version": INPUT_VERSION,
        "acquisition_opportunity_id": acquisition_opportunity_id,
        "signal_ref": signal_ref,
        "supplier_ref": supplier_ref,
        "contact_ref": contact_ref,
        "company_prebuild_version": company_prebuild_version,
        "company_prebuild_fingerprint": company_prebuild_fingerprint,
        "size_band_version": size_band_version,
        "profile_supplier_identity_status": profile_supplier_identity_status,
        "current_supplier_identity_status": current_supplier_identity_status,
        "profile_contact_role_profile_version": profile_contact_role_profile_version,
        "profile_contact_role_tier": profile_contact_role_tier,
        "current_contact_role_profile_version": current_contact_role_profile_version,
        "current_contact_role_tier": current_contact_role_tier,
        "current_contact_verification_state": current_contact_verification_state,
        "current_contact_verification_provider": current_contact_verification_provider,
        "current_contact_provider_email_status": current_contact_provider_email_status,
        "representative_award_key": public_context.representative_award_key,
        "source_event_key": public_context.source_event_key,
        "public_evidence_refs": public_context.public_evidence_refs,
        "public_context_fingerprint": public_context.public_context_fingerprint,
        "award_date": public_context.award_date,
        "contract_notification_date": public_context.contract_notification_date,
        "publication_date": public_context.publication_date,
        "recency_basis": basis,
        "recency_date": recency_date,
        "as_of_date": as_of_date,
        "age_days": age_days,
        "public_timing_inconsistent": inconsistent,
        "research_completeness": research_completeness,
        "research_gaps": tuple(sorted(set(research_gaps))),
        "size_band": size_band,
        "decision_policy_version": policy_config.policy_version,
        "decision_policy_config_fingerprint": policy_config.config_fingerprint,
    }
    return AcquisitionDecisionInput(
        **values,
        decision_input_fingerprint=semantic_fingerprint(values),
    )
