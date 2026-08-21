from __future__ import annotations

import datetime as dt

import pytest

from signals.company_research.contracts import CompanySizeBand, ResearchCompleteness
from signals.decision_engine.input import (
    build_acquisition_decision_input,
    build_public_decision_context,
)
from signals.decision_engine.policy import DECISION_POLICY_V1
from signals.personalization.grounding import (
    PersonalizationDecisionNoLongerEligible,
    require_current_send,
)
from signals.supplier_discovery.contracts import SupplierIdentityStatus


def _input(as_of_date: dt.date):
    context = build_public_decision_context(
        opportunity_key="public-opp-1",
        representative_award_key="award-1",
        source_event_key="simap:notice-1:",
        award_date=dt.date(2026, 6, 21),
        contract_notification_date=None,
        publication_date=dt.date(2026, 6, 21),
        public_evidence_refs=("source-event:simap:notice-1:", "contract-award:award-1"),
    )
    return build_acquisition_decision_input(
        acquisition_opportunity_id="acq-1",
        signal_ref="procurement-opportunity:public-opp-1",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        company_prebuild_version="acquisition-prospect-prebuild-v1",
        company_prebuild_fingerprint="a" * 64,
        size_band_version="company-size-v1",
        profile_supplier_identity_status=SupplierIdentityStatus.PROVIDER_IDENTIFIED,
        current_supplier_identity_status=SupplierIdentityStatus.PROVIDER_IDENTIFIED,
        profile_contact_role_profile_version="decision-maker-search-v1",
        profile_contact_role_tier=1,
        current_contact_role_profile_version="decision-maker-search-v1",
        current_contact_role_tier=1,
        current_contact_verification_state="PROVIDER_VERIFIED",
        current_contact_verification_provider="apollo",
        current_contact_provider_email_status="verified",
        research_completeness=ResearchCompleteness.COMPLETE,
        research_gaps=(),
        size_band=CompanySizeBand.SMB,
        public_context=context,
        as_of_date=as_of_date,
        policy_config=DECISION_POLICY_V1,
    )


def test_current_day_sixty_send_is_eligible() -> None:
    proposal = require_current_send(_input(dt.date(2026, 8, 20)))

    assert proposal.proposed_decision.value == "SEND"


def test_day_sixty_one_is_not_eligible_even_if_historical_decision_was_send() -> None:
    with pytest.raises(PersonalizationDecisionNoLongerEligible):
        require_current_send(_input(dt.date(2026, 8, 21)))
