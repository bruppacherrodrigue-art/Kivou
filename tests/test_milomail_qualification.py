"""Professional capacity and fit are explicit public-evidence calculations."""

import datetime as dt
from pathlib import Path

import pytest

from signals.acquisition_programs.config import load_program_config
from signals.acquisition_programs.mail_provider import MailProvider
from signals.acquisition_programs.qualification import (
    FitSignals,
    ProfessionalEvidenceInput,
    RecipientCapacity,
    classify_recipient,
    score_fit,
)

NOW = dt.datetime(2026, 9, 21, tzinfo=dt.UTC)
CONFIG = load_program_config(
    Path(__file__).resolve().parents[1] / "ops/examples/milomail-acquisition.json.example"
)


def test_company_domain_with_professional_source_is_confirmed() -> None:
    result = classify_recipient(
        ProfessionalEvidenceInput(
            email="owner@agency.fr", company_domain="agency.fr", company_id="company-1",
            company_active=True, role="founder", email_verified=True,
            professional_source_url="https://agency.fr/equipe", professional_source_type="COMPANY_SITE",
            professional_evidence_observed_at=NOW,
        ),
        config=CONFIG, at=NOW,
    )
    assert result.capacity is RecipientCapacity.CONFIRMED_PROFESSIONAL
    assert result.classifier_version


def test_gmail_requires_explicit_professional_publication() -> None:
    base = {"email": "owner@gmail.com", "company_domain": "agency.fr", "company_id": "company-1", "company_active": True, "role": "founder", "email_verified": True}
    without = classify_recipient(ProfessionalEvidenceInput(**base), config=CONFIG, at=NOW)
    assert without.capacity is RecipientCapacity.PERSONAL
    with_source = classify_recipient(
        ProfessionalEvidenceInput(**base, professional_source_url="https://agency.fr/contact", professional_source_type="COMPANY_SITE", professional_evidence_observed_at=NOW, email_explicitly_published=True),
        config=CONFIG, at=NOW,
    )
    assert with_source.capacity is RecipientCapacity.CONFIRMED_PROFESSIONAL
    assert "GMAIL_PROFESSIONALLY_PUBLISHED" in with_source.reasons


def test_minor_and_private_individual_are_personal() -> None:
    for flag in ("is_minor", "is_private_individual"):
        result = classify_recipient(
            ProfessionalEvidenceInput(email="owner@agency.fr", company_domain="agency.fr", company_id="company-1", company_active=True, role="founder", email_verified=True, **{flag: True}),
            config=CONFIG, at=NOW,
        )
        assert result.capacity is RecipientCapacity.PERSONAL


def test_score_breakdown_and_configurable_thresholds() -> None:
    signals = FitSignals(
        provider=MailProvider.GOOGLE_WORKSPACE, provider_confirmed=True,
        sector="digital_or_creative_agency",
        role="founder", employee_count=5,
        recent_public_activity_source="https://agency.fr/actualites",
        public_contact_channel_sources=("https://agency.fr/contact",),
        operational_decision_maker=True,
    )
    result = score_fit(signals, config=CONFIG)
    assert result.total == 100
    assert result.breakdown == CONFIG.score_weights
    assert result.tier == "candidate_for_policy_review"
    assert result.mail_pain_score > 0
    stricter = CONFIG.model_copy(update={"send_review_threshold": 101})
    # Pydantic copies do not validate: the scorer must still enforce configured thresholds.
    assert score_fit(signals, config=stricter).tier == "HOLD"


def test_missing_public_activity_never_creates_an_invented_fact() -> None:
    result = score_fit(
        FitSignals(provider=MailProvider.GOOGLE_WORKSPACE, provider_confirmed=True, sector="consulting", role="ceo", employee_count=5),
        config=CONFIG,
    )
    assert result.total == 90
    assert result.breakdown["recent_public_activity"] == 0
    assert "RECENT_PUBLIC_ACTIVITY_MISSING" in result.missing_reasons


def test_unconfirmed_google_provider_receives_no_workspace_points() -> None:
    result = score_fit(
        FitSignals(
            provider=MailProvider.GOOGLE_WORKSPACE,
            provider_confirmed=False,
            sector="consulting",
            role="ceo",
            employee_count=5,
        ),
        config=CONFIG,
    )
    assert result.breakdown["google_workspace"] == 0
    assert "GOOGLE_WORKSPACE_MISSING" in result.missing_reasons


def test_invalid_email_and_expired_professional_source_never_confirm() -> None:
    with pytest.raises(ValueError):
        classify_recipient(
            ProfessionalEvidenceInput(email="owner.agency.fr", company_domain="agency.fr", company_id="company-1", company_active=True, role="founder", email_verified=True, professional_source_url="https://agency.fr/equipe", professional_source_type="COMPANY_SITE", professional_evidence_observed_at=NOW),
            config=CONFIG, at=NOW,
        )
    stale = classify_recipient(
        ProfessionalEvidenceInput(email="owner@agency.fr", company_domain="agency.fr", company_id="company-1", company_active=True, role="founder", email_verified=True, professional_source_url="https://agency.fr/equipe", professional_source_type="COMPANY_SITE", professional_evidence_observed_at=NOW),
        config=CONFIG, at=NOW + dt.timedelta(days=CONFIG.professional_evidence_ttl_days + 1),
    )
    assert stale.capacity is RecipientCapacity.LIKELY_PROFESSIONAL
    assert "PROFESSIONAL_SOURCE_EXPIRED" in stale.reasons
