from __future__ import annotations

import datetime as dt

import pytest

from signals.compliance.contracts import (
    BusinessContextState,
    CHLegalBasis,
    ComplianceInput,
    ComplianceJurisdiction,
    ComplianceRulesetConfig,
    EmailProvenance,
    JurisdictionResolution,
    SenderComplianceConfig,
    SuppressionMatchState,
)
from signals.compliance.rules import (
    RULESET_V1,
    ComplianceRulesetMismatch,
    evaluate_compliance,
)
from signals.policy.contracts import ComplianceState

NOW = dt.datetime(2026, 8, 21, 10, tzinfo=dt.UTC)
FP = "a" * 64


def sender(**overrides: object) -> SenderComplianceConfig:
    values: dict[str, object] = {
        "config_version": "sender-compliance-v1",
        "sender_profile_ref": "sender-profile:acquisition-primary",
        "sender_identity_ready": True,
        "opt_out_ready": True,
        "privacy_notice_ready": True,
        "source_notice_ready": True,
    }
    values.update(overrides)
    return SenderComplianceConfig.model_validate(values)


def compliance_input(**overrides: object) -> ComplianceInput:
    resolution = JurisdictionResolution(
        jurisdiction=ComplianceJurisdiction.FR,
        country_code="FR",
        resolvable=True,
        evidence_refs=("acquisition-supplier:supplier-1",),
    )
    values: dict[str, object] = {
        "acquisition_opportunity_id": "opp-1",
        "supplier_ref": "supplier-1",
        "contact_ref": "contact-1",
        "personalization_artifact_id": "artifact-1",
        "personalization_artifact_fingerprint": FP,
        "personalization_input_fingerprint": "b" * 64,
        "personalization_proposal_fingerprint": "c" * 64,
        "personalization_policy_action_fingerprint": "d" * 64,
        "language": "fr",
        "supplier_identity_status": "PROVIDER_IDENTIFIED",
        "contact_verification_state": "PROVIDER_VERIFIED",
        "contact_verification_provider": "apollo",
        "contact_provider_email_status": "verified",
        "contact_source_fingerprint": "e" * 64,
        "contact_role_profile_version": "decision-maker-role-v1",
        "contact_role_tier": 1,
        "jurisdiction": resolution,
        "business_context_state": BusinessContextState.PROFESSIONAL_CONTEXT_VERIFIED,
        "email_provenance": EmailProvenance.PROVIDER_VERIFIED_BUSINESS_CONTACT,
        "sender_config": sender(),
        "acquisition_purpose": "KIVOU_ACQUISITION_SIGNAL_RELEVANCE",
        "ch_legal_basis": CHLegalBasis.UNPROVEN,
        "suppression_match_state": SuppressionMatchState.CLEAR,
        "suppression_key_versions_considered": ("key-v1",),
        "evidence_refs": (
            "acquisition-personalization:artifact-1",
            "acquisition-contact:contact-1",
        ),
        "ruleset_config_fingerprint": RULESET_V1.config_fingerprint,
        "ruleset_legal_review_ref": RULESET_V1.legal_review_ref,
        "ruleset_effective_from": RULESET_V1.effective_from,
        "ruleset_valid_until": RULESET_V1.valid_until,
        "assessed_at": NOW,
        "as_of_date": NOW.date(),
        "compliance_input_fingerprint": "f" * 64,
    }
    values.update(overrides)
    return ComplianceInput.model_validate(values)


def ruleset(**overrides: object) -> ComplianceRulesetConfig:
    values = RULESET_V1.model_dump(mode="python", exclude={"config_fingerprint"})
    values.update(overrides)
    return ComplianceRulesetConfig.model_validate(values)


def ruleset_input(
    config: ComplianceRulesetConfig, **overrides: object
) -> ComplianceInput:
    values: dict[str, object] = {
        "ruleset_config_fingerprint": config.config_fingerprint,
        "ruleset_legal_review_ref": config.legal_review_ref,
        "ruleset_effective_from": config.effective_from,
        "ruleset_valid_until": config.valid_until,
    }
    values.update(overrides)
    return compliance_input(**values)


@pytest.mark.parametrize(
    ("basis", "expected"),
    (
        (CHLegalBasis.CONSENT_PROVEN, ComplianceState.ALLOWED),
        (CHLegalBasis.EXISTING_CUSTOMER_SIMILAR_PROVEN, ComplianceState.ALLOWED),
        (CHLegalBasis.UNPROVEN, ComplianceState.REVIEW_REQUIRED),
    ),
)
def test_ch_frozen_legal_predicate(basis, expected) -> None:
    resolution = JurisdictionResolution(
        jurisdiction=ComplianceJurisdiction.CH,
        country_code="CH",
        resolvable=True,
        evidence_refs=("acquisition-supplier:supplier-1",),
    )

    proposal = evaluate_compliance(
        compliance_input(jurisdiction=resolution, ch_legal_basis=basis), RULESET_V1
    )

    assert proposal.state is expected
    assert proposal.next_action == (
        "schedule_campaign" if expected is ComplianceState.ALLOWED else "request_human_review"
    )


@pytest.mark.parametrize("tier", (1, 2, 3))
def test_fr_tiers_one_to_three_with_complete_config_are_allowed(tier: int) -> None:
    proposal = evaluate_compliance(compliance_input(contact_role_tier=tier), RULESET_V1)

    assert proposal.state is ComplianceState.ALLOWED
    assert proposal.next_action == "schedule_campaign"
    assert proposal.valid_until == NOW + dt.timedelta(hours=24)


def test_fr_tier_four_and_missing_capabilities_require_review() -> None:
    tier_four = evaluate_compliance(
        compliance_input(
            contact_role_tier=4,
            business_context_state=BusinessContextState.BUSINESS_CONTEXT_INSUFFICIENT,
        ),
        RULESET_V1,
    )
    missing_notice = evaluate_compliance(
        compliance_input(sender_config=sender(source_notice_ready=False)), RULESET_V1
    )

    assert tier_four.state is ComplianceState.REVIEW_REQUIRED
    assert "BUSINESS_CONTEXT_INSUFFICIENT" in tier_four.reason_codes
    assert missing_notice.state is ComplianceState.REVIEW_REQUIRED
    assert "REQUIRED_SOURCE_NOTICE_MISSING" in missing_notice.reason_codes


def test_fr_reason_order_puts_sender_capabilities_before_business_provenance() -> None:
    proposal = evaluate_compliance(
        compliance_input(
            contact_role_tier=4,
            business_context_state=BusinessContextState.BUSINESS_CONTEXT_INSUFFICIENT,
            email_provenance=EmailProvenance.UNKNOWN,
            sender_config=sender(
                sender_identity_ready=False,
                opt_out_ready=False,
                privacy_notice_ready=False,
                source_notice_ready=False,
            ),
        ),
        RULESET_V1,
    )

    assert proposal.reason_codes == (
        "REQUIRED_SENDER_IDENTITY_MISSING",
        "REQUIRED_OPT_OUT_MECHANISM_MISSING",
        "REQUIRED_PRIVACY_NOTICE_MISSING",
        "REQUIRED_SOURCE_NOTICE_MISSING",
        "BUSINESS_CONTEXT_INSUFFICIENT",
        "EMAIL_PROVENANCE_UNRESOLVED",
    )


def test_expired_sender_configuration_cannot_create_allowed_result() -> None:
    proposal = evaluate_compliance(
        compliance_input(sender_config=sender(valid_until=NOW - dt.timedelta(seconds=1))),
        RULESET_V1,
    )

    assert proposal.state is ComplianceState.REVIEW_REQUIRED
    assert proposal.reason_codes[0] == "SENDER_CONFIG_EXPIRED"


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("sender_identity_ready", "REQUIRED_SENDER_IDENTITY_MISSING"),
        ("opt_out_ready", "REQUIRED_OPT_OUT_MECHANISM_MISSING"),
        ("privacy_notice_ready", "REQUIRED_PRIVACY_NOTICE_MISSING"),
        ("source_notice_ready", "REQUIRED_SOURCE_NOTICE_MISSING"),
    ),
)
def test_each_fr_sender_capability_is_independently_required(field: str, reason: str) -> None:
    proposal = evaluate_compliance(
        compliance_input(sender_config=sender(**{field: False})), RULESET_V1
    )

    assert proposal.state is ComplianceState.REVIEW_REQUIRED
    assert reason in proposal.reason_codes


def test_suppression_is_highest_precedence_and_non_overridable() -> None:
    result = evaluate_compliance(
        compliance_input(
            suppression_match_state=SuppressionMatchState.MATCHED,
            jurisdiction=JurisdictionResolution(
                jurisdiction=ComplianceJurisdiction.UNRESOLVED,
                resolvable=True,
                evidence_refs=("jurisdiction:unresolved",),
            ),
        ),
        RULESET_V1,
    )

    assert result.state is ComplianceState.BLOCKED
    assert result.next_action is None
    assert result.reason_codes[0] == "SUPPRESSION_MATCH"


@pytest.mark.parametrize(
    ("jurisdiction", "resolvable", "state", "next_action", "reason"),
    (
        (
            ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED,
            True,
            ComplianceState.REVIEW_REQUIRED,
            "request_human_review",
            "COUNTRY_RULESET_UNCONFIGURED",
        ),
        (
            ComplianceJurisdiction.OUT_OF_SCOPE,
            False,
            ComplianceState.BLOCKED,
            None,
            "JURISDICTION_OUT_OF_SCOPE",
        ),
        (
            ComplianceJurisdiction.UNRESOLVED,
            True,
            ComplianceState.UNKNOWN,
            "request_human_review",
            "JURISDICTION_UNRESOLVED",
        ),
    ),
)
def test_fail_closed_jurisdiction_matrix(
    jurisdiction, resolvable, state, next_action, reason
) -> None:
    proposal = evaluate_compliance(
        compliance_input(
            jurisdiction=JurisdictionResolution(
                jurisdiction=jurisdiction,
                country_code="DE"
                if jurisdiction is ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED
                else None,
                resolvable=resolvable,
                evidence_refs=("jurisdiction:evidence",),
            )
        ),
        RULESET_V1,
    )

    assert proposal.state is state
    assert proposal.next_action == next_action
    assert proposal.reason_codes[0] == reason


def test_incomplete_suppression_key_coverage_is_non_resolvable_unknown() -> None:
    proposal = evaluate_compliance(
        compliance_input(suppression_match_state=SuppressionMatchState.COVERAGE_UNSAFE),
        RULESET_V1,
    )

    assert proposal.state is ComplianceState.UNKNOWN
    assert proposal.next_action is None
    assert proposal.reason_codes == ("SUPPRESSION_KEY_COVERAGE_UNSAFE",)
    assert proposal.valid_until is None
    assert len(proposal.reason_codes) <= 8
    assert len(proposal.evidence_refs) <= 16


@pytest.mark.parametrize("country", ("FR", "CH"))
def test_automatic_country_rule_requires_explicit_ruleset_configuration(country: str) -> None:
    jurisdiction = JurisdictionResolution(
        jurisdiction=ComplianceJurisdiction(country),
        country_code=country,
        resolvable=True,
        evidence_refs=("jurisdiction:evidence",),
    )
    config = ruleset(
        configured_country_rulesets=tuple(
            configured
            for configured in RULESET_V1.configured_country_rulesets
            if configured != country
        )
    )
    value = ruleset_input(
        config,
        jurisdiction=jurisdiction,
        ch_legal_basis=(
            CHLegalBasis.CONSENT_PROVEN if country == "CH" else CHLegalBasis.UNPROVEN
        ),
    )

    proposal = evaluate_compliance(value, config)

    assert proposal.state is ComplianceState.REVIEW_REQUIRED
    assert proposal.reason_codes == ("COUNTRY_RULESET_UNCONFIGURED",)
    assert proposal.next_action == "request_human_review"


def test_ruleset_outside_effective_interval_requires_review() -> None:
    config = ruleset(
        effective_from=NOW + dt.timedelta(hours=1),
        valid_until=NOW + dt.timedelta(hours=2),
    )
    before = ruleset_input(config)
    expiring = ruleset(
        effective_from=NOW - dt.timedelta(hours=1),
        valid_until=NOW,
    )
    at_expiry = ruleset_input(expiring)

    for value, selected in ((before, config), (at_expiry, expiring)):
        proposal = evaluate_compliance(value, selected)
        assert proposal.state is ComplianceState.REVIEW_REQUIRED
        assert proposal.reason_codes == ("RULESET_NOT_EFFECTIVE",)
        assert proposal.next_action == "request_human_review"


def test_ruleset_inside_effective_interval_runs_normal_country_rules() -> None:
    config = ruleset(
        effective_from=NOW - dt.timedelta(hours=1),
        valid_until=NOW + dt.timedelta(hours=1),
    )
    value = ruleset_input(config)

    proposal = evaluate_compliance(value, config)

    assert proposal.state is ComplianceState.ALLOWED


def test_allowed_validity_is_clipped_by_ruleset_expiry() -> None:
    expiry = NOW + dt.timedelta(hours=3)
    config = ruleset(
        effective_from=NOW - dt.timedelta(hours=1),
        valid_until=expiry,
    )
    value = ruleset_input(config)

    proposal = evaluate_compliance(value, config)

    assert proposal.state is ComplianceState.ALLOWED
    assert proposal.valid_until == expiry


def test_input_must_bind_the_exact_ruleset_config() -> None:
    other = ruleset(configured_country_rulesets=("CH",))

    with pytest.raises(ComplianceRulesetMismatch, match="ruleset"):
        evaluate_compliance(compliance_input(), other)


def test_legal_review_identity_and_interval_affect_config_fingerprint() -> None:
    base = RULESET_V1
    changed_review = ruleset(legal_review_ref="legal-review:spec025-r1:replacement")
    changed_start = ruleset(effective_from=base.effective_from + dt.timedelta(seconds=1))
    changed_end = ruleset(valid_until=NOW + dt.timedelta(days=30))

    assert base.legal_review_ref == (
        "legal-review:spec025-r1:ff6a070c3d7a8ad95c002fc0ffc97b3b4f93c594"
    )
    assert base.config_fingerprint != changed_review.config_fingerprint
    assert base.config_fingerprint != changed_start.config_fingerprint
    assert base.config_fingerprint != changed_end.config_fingerprint
