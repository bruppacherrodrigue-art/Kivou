from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from signals.company_research.contracts import CompanySizeBand, ResearchCompleteness
from signals.decision_engine.contracts import RecencyBasis
from signals.decision_engine.input import (
    build_acquisition_decision_input,
    build_public_decision_context,
)
from signals.decision_engine.policy import DECISION_POLICY_V1
from signals.supplier_discovery.contracts import SupplierIdentityStatus

AS_OF = dt.date(2026, 8, 20)


def _context(**updates):
    values = {
        "opportunity_key": "public-opp-1",
        "representative_award_key": "award-1",
        "source_event_key": "simap:notice-1:",
        "award_date": dt.date(2026, 8, 1),
        "contract_notification_date": dt.date(2026, 8, 5),
        "publication_date": dt.date(2026, 8, 6),
        "public_evidence_refs": (
            "source-event:simap:notice-1:",
            "contract-award:award-1",
        ),
    }
    values.update(updates)
    return build_public_decision_context(**values)


def _decision_input(context=None, **updates):
    values = {
        "acquisition_opportunity_id": "acq-1",
        "signal_ref": "procurement-opportunity:public-opp-1",
        "supplier_ref": "supplier-1",
        "contact_ref": "contact-1",
        "company_prebuild_version": "acquisition-prospect-prebuild-v1",
        "company_prebuild_fingerprint": "a" * 64,
        "size_band_version": "company-size-v1",
        "profile_supplier_identity_status": SupplierIdentityStatus.PROVIDER_IDENTIFIED,
        "current_supplier_identity_status": SupplierIdentityStatus.PROVIDER_IDENTIFIED,
        "profile_contact_role_profile_version": "decision-maker-search-v1",
        "profile_contact_role_tier": 1,
        "current_contact_role_profile_version": "decision-maker-search-v1",
        "current_contact_role_tier": 1,
        "current_contact_verification_state": "PROVIDER_VERIFIED",
        "current_contact_verification_provider": "apollo",
        "current_contact_provider_email_status": "verified",
        "research_completeness": ResearchCompleteness.COMPLETE,
        "research_gaps": (),
        "size_band": CompanySizeBand.SMB,
        "public_context": context or _context(),
        "as_of_date": AS_OF,
        "policy_config": DECISION_POLICY_V1,
    }
    values.update(updates)
    return build_acquisition_decision_input(**values)


@pytest.mark.parametrize(
    ("dates", "basis", "date"),
    (
        (
            {
                "award_date": dt.date(2026, 8, 1),
                "contract_notification_date": dt.date(2026, 8, 5),
                "publication_date": dt.date(2026, 8, 6),
            },
            RecencyBasis.AWARD_DATE,
            dt.date(2026, 8, 1),
        ),
        (
            {
                "award_date": None,
                "contract_notification_date": dt.date(2026, 8, 5),
                "publication_date": dt.date(2026, 8, 6),
            },
            RecencyBasis.CONTRACT_NOTIFICATION_DATE,
            dt.date(2026, 8, 5),
        ),
        (
            {
                "award_date": None,
                "contract_notification_date": None,
                "publication_date": dt.date(2026, 8, 6),
            },
            RecencyBasis.PUBLICATION_DATE,
            dt.date(2026, 8, 6),
        ),
        (
            {
                "award_date": None,
                "contract_notification_date": None,
                "publication_date": None,
            },
            RecencyBasis.UNRESOLVED,
            None,
        ),
    ),
)
def test_recency_precedence_is_explicit(dates, basis, date) -> None:
    decision_input = _decision_input(_context(**dates))

    assert decision_input.recency_basis is basis
    assert decision_input.recency_date == date
    assert decision_input.age_days == ((AS_OF - date).days if date else None)


def test_present_invalid_award_date_does_not_fall_back() -> None:
    decision_input = _decision_input(
        _context(
            award_date=dt.date(2026, 8, 25),
            contract_notification_date=dt.date(2026, 8, 10),
            publication_date=dt.date(2026, 8, 12),
        )
    )

    assert decision_input.recency_basis is RecencyBasis.AWARD_DATE
    assert decision_input.recency_date == dt.date(2026, 8, 25)
    assert decision_input.age_days == -5
    assert decision_input.public_timing_inconsistent is True


def test_award_one_day_after_publication_is_tolerated_but_two_days_is_not() -> None:
    tolerated = _decision_input(
        _context(
            award_date=dt.date(2026, 8, 11),
            publication_date=dt.date(2026, 8, 10),
        )
    )
    inconsistent = _decision_input(
        _context(
            award_date=dt.date(2026, 8, 12),
            publication_date=dt.date(2026, 8, 10),
        )
    )

    assert tolerated.public_timing_inconsistent is False
    assert inconsistent.public_timing_inconsistent is True


def test_public_context_and_input_fingerprints_are_deterministic_and_exclude_discovery_time() -> None:
    first_context = _context()
    second_context = _context()
    first = _decision_input(first_context)
    second = _decision_input(second_context)

    assert first_context.public_context_fingerprint == second_context.public_context_fingerprint
    assert first.decision_input_fingerprint == second.decision_input_fingerprint
    assert "discovered" not in first.model_dump(mode="json")


def test_as_of_date_changes_the_decision_input_fingerprint() -> None:
    first = _decision_input(as_of_date=dt.date(2026, 8, 20))
    second = _decision_input(as_of_date=dt.date(2026, 8, 21))

    assert first.age_days + 1 == second.age_days
    assert first.decision_input_fingerprint != second.decision_input_fingerprint


@pytest.mark.parametrize(
    "updates",
    (
        {
            "recency_basis": RecencyBasis.UNRESOLVED,
            "recency_date": dt.date(2026, 8, 1),
            "age_days": 19,
        },
        {
            "recency_basis": RecencyBasis.AWARD_DATE,
            "recency_date": None,
            "age_days": None,
        },
        {
            "recency_basis": RecencyBasis.AWARD_DATE,
            "recency_date": dt.date(2026, 8, 1),
            "age_days": 18,
        },
    ),
)
def test_decision_input_contract_rejects_inconsistent_recency(updates) -> None:
    values = _decision_input().model_dump(mode="python")
    values.update(updates)

    with pytest.raises(ValidationError):
        type(_decision_input()).model_validate(values)
