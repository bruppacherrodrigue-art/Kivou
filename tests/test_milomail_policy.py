"""Milo Mail policy decisions remain distinct from the frozen Kivou ruleset."""

import dataclasses
import datetime as dt
from pathlib import Path

import pytest

from signals.acquisition_programs.config import load_program_config
from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderEvidence,
    ProviderConfidence,
)
from signals.acquisition_programs.qualification import (
    CapacityAssessment,
    FitAssessment,
    RecipientCapacity,
)
from signals.compliance.contracts import ComplianceInput
from signals.compliance.milomail_rules import (
    MILOMAIL_PURPOSE,
    MilomailPolicyInput,
    evaluate_milomail,
)
from signals.compliance.rules import ComplianceRulesetMismatch, evaluate_compliance

NOW = dt.datetime(2026, 9, 21, tzinfo=dt.UTC)
EXAMPLE = Path(__file__).resolve().parents[1] / "ops/examples/milomail-acquisition.json.example"


def ready_config():
    raw = load_program_config(EXAMPLE).model_dump(mode="python")
    raw.update(
        landing_url="https://milomail.example/fr/audit",
        privacy_url="https://milomail.example/fr/confidentialite",
        opt_out_url="https://milomail.example/fr/desinscription",
        sender_configuration_ref="sender:milomail:test",
        sender_legal_name="Milo Mail SAS (synthétique)",
        sender_postal_address="1 rue du Test, 75000 Paris (synthétique)",
        sender_domains=("outbound.milomail.example",),
        instantly_workspace_ref="instantly:milomail:test",
        max_daily_contacts=10,
        max_monthly_contacts=100,
        max_cost_chf="10",
    )
    return type(load_program_config(EXAMPLE)).model_validate(raw)


def ready_input(**changes):
    config = ready_config()
    value = MilomailPolicyInput(
        acquisition_purpose=MILOMAIL_PURPOSE,
        program=config,
        country="FR",
        sector="consulting",
        employee_count=5,
        company_active=True,
        company_active_source_url="https://registre.example/entreprise",
        company_active_source_type="PUBLIC_COMPANY_REGISTRY",
        company_active_observed_at=NOW,
        company_active_evidence_id="source:company",
        business_relevance_confirmed=True,
        provider=MailProviderEvidence(
            domain="cabinet.example",
            provider=MailProvider.GOOGLE_WORKSPACE,
            confidence=ProviderConfidence.CONFIRMED,
            mx_records=("smtp.google.com",),
            source="DNS_MX",
            observed_at=NOW,
            expires_at=NOW + dt.timedelta(days=1),
        ),
        capacity=CapacityAssessment(
            capacity=RecipientCapacity.CONFIRMED_PROFESSIONAL,
            reasons=("COMPANY_DOMAIN_AND_SOURCE_VERIFIED",),
            professional_source_url="https://cabinet.example/equipe",
            professional_source_type="COMPANY_WEBSITE",
            professional_evidence_observed_at=NOW,
            evidence_expires_at=NOW + dt.timedelta(days=90),
            role="founder",
            company_id="company:test",
        ),
        fit=FitAssessment(
            total=100,
            breakdown={
                "google_workspace": 30,
                "email_dependent_sector": 25,
                "decision_maker": 20,
                "company_size": 15,
                "recent_public_activity": 10,
            },
            missing_reasons=(),
            tier="candidate_for_policy_review",
            mail_pain_score=100,
            score_version=config.score_version,
        ),
        email_verified=True,
        collection_source_url="https://cabinet.example/equipe",
        collected_at=NOW,
        suppressed=False,
        suppression_coverage_safe=True,
        sender_identity_ready=True,
        opt_out_ready=True,
        privacy_notice_ready=True,
        source_notice_ready=True,
        sender_domain="outbound.milomail.example",
        sender_healthy=True,
        spf_ready=True,
        dkim_ready=True,
        dmarc_ready=True,
        warmup_ready=True,
        landing_active=True,
        landing_french=True,
        daily_remaining=10,
        monthly_remaining=100,
        cost_remaining_chf="10",
        evidence_ids=("source:company", "mx:google", "source:email"),
        assessed_at=NOW,
    )
    return value.model_copy(update=changes)


def test_complete_fr_b2b_prospect_is_theoretical_send_in_shadow() -> None:
    result = evaluate_milomail(ready_input())
    assert result.decision == "SEND"
    assert result.policy_country == "FR"
    assert result.policy_version == "milomail-fr-b2b-v1"
    assert result.score_version == "milomail-fit-v1"
    assert result.evidence_ids == ("source:company", "mx:google", "source:email")
    assert result.reason_codes == ("FR_B2B_GMAIL_AUDIT_ELIGIBLE",)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"country": "DE"}, "COUNTRY_OUT_OF_SCOPE"),
        ({"sector": "retail"}, "SECTOR_OUT_OF_SCOPE"),
        ({"employee_count": 25}, "COMPANY_SIZE_OUT_OF_SCOPE"),
        ({"company_active": False}, "COMPANY_INACTIVE"),
        ({"suppressed": True}, "SUPPRESSION_MATCH"),
        ({"is_minor": True}, "PERSONAL_OR_MINOR"),
        ({"is_private_individual": True}, "PERSONAL_OR_MINOR"),
        ({"fit": ready_input().fit.model_copy(update={"total": 40})}, "FIT_BELOW_MINIMUM"),
        (
            {
                "provider": dataclasses.replace(
                    ready_input().provider, provider=MailProvider.MICROSOFT_365
                )
            },
            "MAIL_PROVIDER_OUT_OF_SCOPE",
        ),
        (
            {
                "provider": dataclasses.replace(
                    ready_input().provider, provider=MailProvider.GMAIL_CONSUMER
                )
            },
            "MAIL_PROVIDER_OUT_OF_SCOPE",
        ),
        (
            {
                "capacity": ready_input().capacity.model_copy(
                    update={"capacity": RecipientCapacity.PERSONAL}
                )
            },
            "PERSONAL_RECIPIENT",
        ),
    ],
)
def test_real_exclusions_are_no_send(changes, reason) -> None:
    result = evaluate_milomail(ready_input(**changes))
    assert result.decision == "NO_SEND"
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"country": None}, "COUNTRY_UNRESOLVED"),
        ({"company_active": None}, "COMPANY_ACTIVE_STATUS_UNRESOLVED"),
        ({"company_active_source_url": None}, "COMPANY_ACTIVE_EVIDENCE_INSUFFICIENT"),
        ({"email_verified": False}, "EMAIL_NOT_VERIFIED"),
        (
            {
                "provider": dataclasses.replace(
                    ready_input().provider,
                    provider=MailProvider.UNKNOWN,
                    confidence=ProviderConfidence.UNKNOWN,
                )
            },
            "MAIL_PROVIDER_UNKNOWN",
        ),
        (
            {
                "capacity": ready_input().capacity.model_copy(
                    update={"capacity": RecipientCapacity.UNKNOWN}
                )
            },
            "RECIPIENT_CAPACITY_UNCONFIRMED",
        ),
        (
            {
                "capacity": ready_input().capacity.model_copy(
                    update={"capacity": RecipientCapacity.LIKELY_PROFESSIONAL}
                )
            },
            "RECIPIENT_CAPACITY_UNCONFIRMED",
        ),
        ({"suppression_coverage_safe": False}, "SUPPRESSION_COVERAGE_UNSAFE"),
        ({"landing_french": False}, "FRENCH_LANDING_UNAVAILABLE"),
        ({"sender_healthy": False}, "SENDER_NOT_READY"),
        ({"daily_remaining": 0}, "BUDGET_EXHAUSTED"),
        ({"fit": ready_input().fit.model_copy(update={"total": 70})}, "FIT_BELOW_REVIEW_THRESHOLD"),
        ({"evidence_ids": ()}, "EVIDENCE_MISSING"),
        (
            {
                "capacity": ready_input().capacity.model_copy(
                    update={"professional_source_url": None}
                )
            },
            "PROFESSIONAL_EVIDENCE_INCOMPLETE",
        ),
        (
            {"provider": dataclasses.replace(ready_input().provider, mx_records=("fake.example",))},
            "GOOGLE_WORKSPACE_EVIDENCE_INSUFFICIENT",
        ),
    ],
)
def test_remediable_gaps_are_hold(changes, reason) -> None:
    result = evaluate_milomail(ready_input(**changes))
    assert result.decision == "HOLD"
    assert reason in result.reason_codes


def test_expired_public_evidence_is_hold() -> None:
    provider = dataclasses.replace(ready_input().provider, expires_at=NOW)
    assert (
        "PROVIDER_EVIDENCE_EXPIRED"
        in evaluate_milomail(ready_input(provider=provider)).reason_codes
    )
    capacity = ready_input().capacity.model_copy(update={"evidence_expires_at": NOW})
    assert (
        "PROFESSIONAL_EVIDENCE_EXPIRED"
        in evaluate_milomail(ready_input(capacity=capacity)).reason_codes
    )


def test_future_mx_observation_is_not_eligible() -> None:
    provider = dataclasses.replace(
        ready_input().provider,
        observed_at=NOW + dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(days=1, minutes=1),
    )
    decision = evaluate_milomail(ready_input(provider=provider))
    assert decision.decision == "HOLD"
    assert "PROVIDER_EVIDENCE_FROM_FUTURE" in decision.reason_codes


def test_kivou_ruleset_rejects_milomail_purpose() -> None:
    assert (
        "MILOMAIL_GMAIL_AUDIT_B2B"
        in ComplianceInput.model_fields["acquisition_purpose"].annotation.__args__
    )
    # The frozen Kivou evaluator must reject this purpose before legal predicates.
    with pytest.raises(ComplianceRulesetMismatch):
        evaluate_compliance(ready_input())  # type: ignore[arg-type]
