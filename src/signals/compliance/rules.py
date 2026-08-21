"""Pure ordered SPEC-025 compliance rule matrix."""

from __future__ import annotations

import datetime as dt

from signals.compliance.contracts import (
    BusinessContextState,
    CHLegalBasis,
    ComplianceInput,
    ComplianceJurisdiction,
    ComplianceProposal,
    ComplianceRulesetConfig,
    EmailProvenance,
    SuppressionMatchState,
)
from signals.decision_engine.policy import semantic_fingerprint
from signals.policy.contracts import ComplianceState

RULESET_V1 = ComplianceRulesetConfig()


class ComplianceRulesetMismatch(ValueError):
    """The input was constructed for a different immutable legal ruleset."""


def _dedupe(values: tuple[str, ...], limit: int) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))[:limit]


def _proposal(
    value: ComplianceInput,
    config: ComplianceRulesetConfig,
    *,
    state: ComplianceState,
    reasons: tuple[str, ...],
    next_action: str | None,
) -> ComplianceProposal:
    validity = None
    if state is ComplianceState.ALLOWED:
        validity = value.assessed_at + dt.timedelta(hours=config.allowed_ttl_hours)
        if value.sender_config.valid_until is not None:
            validity = min(validity, value.sender_config.valid_until)
        if config.valid_until is not None:
            validity = min(validity, config.valid_until)
    evidence = _dedupe((*value.evidence_refs, *value.jurisdiction.evidence_refs), 16)
    assert config.config_fingerprint is not None
    payload = {
        "kind": "acquisition-compliance-proposal-v1",
        "input_fingerprint": value.compliance_input_fingerprint,
        "state": state.value,
        "reason_codes": reasons,
        "evidence_refs": evidence,
        "next_action": next_action,
        "valid_until": validity.isoformat() if validity else None,
        "ruleset_version": config.ruleset_version,
        "ruleset_config_fingerprint": config.config_fingerprint,
    }
    return ComplianceProposal(
        state=state,
        reason_codes=reasons,
        evidence_refs=evidence,
        next_action=next_action,
        valid_until=validity,
        input_fingerprint=value.compliance_input_fingerprint,
        ruleset_config_fingerprint=config.config_fingerprint,
        proposal_fingerprint=semantic_fingerprint(payload),
    )


def evaluate_compliance(
    value: ComplianceInput, config: ComplianceRulesetConfig = RULESET_V1
) -> ComplianceProposal:
    """Apply the frozen rule ordering without database, clock, or network access."""
    if (
        value.ruleset_version != config.ruleset_version
        or value.ruleset_config_fingerprint != config.config_fingerprint
        or value.ruleset_legal_review_ref != config.legal_review_ref
        or value.ruleset_effective_from != config.effective_from
        or value.ruleset_valid_until != config.valid_until
    ):
        raise ComplianceRulesetMismatch("compliance input ruleset binding mismatch")

    if value.suppression_match_state is SuppressionMatchState.MATCHED:
        return _proposal(
            value,
            config,
            state=ComplianceState.BLOCKED,
            reasons=("SUPPRESSION_MATCH",),
            next_action=None,
        )
    if value.suppression_match_state is SuppressionMatchState.COVERAGE_UNSAFE:
        return _proposal(
            value,
            config,
            state=ComplianceState.UNKNOWN,
            reasons=("SUPPRESSION_KEY_COVERAGE_UNSAFE",),
            next_action=None,
        )

    if value.assessed_at < config.effective_from or (
        config.valid_until is not None and value.assessed_at >= config.valid_until
    ):
        return _proposal(
            value,
            config,
            state=ComplianceState.REVIEW_REQUIRED,
            reasons=("RULESET_NOT_EFFECTIVE",),
            next_action="request_human_review",
        )

    jurisdiction = value.jurisdiction.jurisdiction
    if jurisdiction is ComplianceJurisdiction.UNRESOLVED:
        return _proposal(
            value,
            config,
            state=ComplianceState.UNKNOWN,
            reasons=("JURISDICTION_UNRESOLVED",),
            next_action="request_human_review" if value.jurisdiction.resolvable else None,
        )
    if jurisdiction is ComplianceJurisdiction.OUT_OF_SCOPE:
        return _proposal(
            value,
            config,
            state=ComplianceState.BLOCKED,
            reasons=("JURISDICTION_OUT_OF_SCOPE",),
            next_action=None,
        )
    if jurisdiction is ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED:
        return _proposal(
            value,
            config,
            state=ComplianceState.REVIEW_REQUIRED,
            reasons=("COUNTRY_RULESET_UNCONFIGURED",),
            next_action="request_human_review",
        )
    if jurisdiction.value not in config.configured_country_rulesets:
        return _proposal(
            value,
            config,
            state=ComplianceState.REVIEW_REQUIRED,
            reasons=("COUNTRY_RULESET_UNCONFIGURED",),
            next_action="request_human_review",
        )

    reasons: list[str] = []
    if jurisdiction is ComplianceJurisdiction.CH:
        if value.ch_legal_basis is CHLegalBasis.UNPROVEN:
            reasons.append("LEGAL_BASIS_UNRESOLVED")
        if (
            value.sender_config.valid_until is not None
            and value.sender_config.valid_until <= value.assessed_at
        ):
            reasons.append("SENDER_CONFIG_EXPIRED")
        if not value.sender_config.sender_identity_ready:
            reasons.append("REQUIRED_SENDER_IDENTITY_MISSING")
        if not value.sender_config.opt_out_ready:
            reasons.append("REQUIRED_OPT_OUT_MECHANISM_MISSING")
    else:
        if (
            value.sender_config.valid_until is not None
            and value.sender_config.valid_until <= value.assessed_at
        ):
            reasons.append("SENDER_CONFIG_EXPIRED")
        if not value.sender_config.sender_identity_ready:
            reasons.append("REQUIRED_SENDER_IDENTITY_MISSING")
        if not value.sender_config.opt_out_ready:
            reasons.append("REQUIRED_OPT_OUT_MECHANISM_MISSING")
        if not value.sender_config.privacy_notice_ready:
            reasons.append("REQUIRED_PRIVACY_NOTICE_MISSING")
        if not value.sender_config.source_notice_ready:
            reasons.append("REQUIRED_SOURCE_NOTICE_MISSING")
        if value.business_context_state is not BusinessContextState.PROFESSIONAL_CONTEXT_VERIFIED:
            reasons.append("BUSINESS_CONTEXT_INSUFFICIENT")
        if value.email_provenance is not EmailProvenance.PROVIDER_VERIFIED_BUSINESS_CONTACT:
            reasons.append("EMAIL_PROVENANCE_UNRESOLVED")

    if reasons:
        return _proposal(
            value,
            config,
            state=ComplianceState.REVIEW_REQUIRED,
            reasons=_dedupe(tuple(reasons), 8),
            next_action="request_human_review",
        )
    allowed_reasons = (
        (
            "CH_LEGAL_PREDICATE_VERIFIED",
            "SENDER_AND_OBJECTION_MECHANISM_VERIFIED",
        )
        if jurisdiction is ComplianceJurisdiction.CH
        else (
            "JURISDICTION_RULESET_SATISFIED",
            "BUSINESS_CONTEXT_VERIFIED",
            "SENDER_AND_OBJECTION_MECHANISM_VERIFIED",
        )
    )
    return _proposal(
        value,
        config,
        state=ComplianceState.ALLOWED,
        reasons=allowed_reasons,
        next_action="schedule_campaign",
    )


__all__ = ["RULESET_V1", "ComplianceRulesetMismatch", "evaluate_compliance"]
