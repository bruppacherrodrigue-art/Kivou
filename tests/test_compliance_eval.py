from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from signals.compliance.contracts import (
    BusinessContextState,
    CHLegalBasis,
    ComplianceInput,
    ComplianceJurisdiction,
    EmailProvenance,
    JurisdictionResolution,
    SenderComplianceConfig,
    SuppressionMatchState,
)
from signals.compliance.rules import RULESET_V1, evaluate_compliance

FIXTURE = Path(__file__).parent / "fixtures" / "compliance_eval_v1.json"
NOW = dt.datetime(2026, 8, 21, 12, tzinfo=dt.UTC)


def _evaluate(case: dict[str, object]) -> str:
    jurisdiction = ComplianceJurisdiction(case["jurisdiction"])
    config = SenderComplianceConfig(
        sender_profile_ref="sender-profile:synthetic",
        sender_identity_ready=case.get("sender_identity_ready", True),
        opt_out_ready=case.get("opt_out_ready", True),
        privacy_notice_ready=case.get("privacy_notice_ready", True),
        source_notice_ready=case.get("source_notice_ready", True),
    )
    values = {
        "acquisition_opportunity_id": "synthetic-opportunity",
        "supplier_ref": "synthetic-supplier",
        "contact_ref": "synthetic-contact",
        "personalization_artifact_id": "synthetic-artifact",
        "personalization_artifact_fingerprint": "1" * 64,
        "personalization_input_fingerprint": "2" * 64,
        "personalization_proposal_fingerprint": "3" * 64,
        "personalization_policy_action_fingerprint": "4" * 64,
        "language": "fr",
        "supplier_identity_status": "PROVIDER_IDENTIFIED",
        "contact_verification_state": "PROVIDER_VERIFIED",
        "contact_verification_provider": "apollo",
        "contact_provider_email_status": "verified",
        "contact_source_fingerprint": "5" * 64,
        "contact_role_profile_version": "decision-maker-role-v1",
        "contact_role_tier": case.get("role_tier", 1),
        "jurisdiction": JurisdictionResolution(
            jurisdiction=jurisdiction,
            country_code=case.get("country_code"),
            resolvable=case.get("resolvable", True),
            evidence_refs=("synthetic-country:evidence",),
        ),
        "business_context_state": (
            BusinessContextState.PROFESSIONAL_CONTEXT_VERIFIED
            if int(case.get("role_tier", 1)) <= 3
            else BusinessContextState.BUSINESS_CONTEXT_INSUFFICIENT
        ),
        "email_provenance": EmailProvenance.PROVIDER_VERIFIED_BUSINESS_CONTACT,
        "sender_config": config,
        "acquisition_purpose": "KIVOU_ACQUISITION_SIGNAL_RELEVANCE",
        "ch_legal_basis": CHLegalBasis(case.get("ch_legal_basis", "UNPROVEN")),
        "suppression_match_state": SuppressionMatchState(case.get("suppression", "CLEAR")),
        "suppression_key_versions_considered": ("synthetic-key-v1",),
        "evidence_refs": ("synthetic-public:evidence",),
        "ruleset_config_fingerprint": RULESET_V1.config_fingerprint,
        "ruleset_legal_review_ref": RULESET_V1.legal_review_ref,
        "ruleset_effective_from": RULESET_V1.effective_from,
        "ruleset_valid_until": RULESET_V1.valid_until,
        "assessed_at": NOW,
        "as_of_date": NOW.date(),
        "compliance_input_fingerprint": "6" * 64,
    }
    return evaluate_compliance(ComplianceInput.model_validate(values), RULESET_V1).state.value


def test_offline_eval_corpus_has_all_twenty_frozen_synthetic_cases() -> None:
    cases = json.loads(FIXTURE.read_text())

    assert len(cases) == 20
    assert {case["id"] for case in cases} == {
        "ch_explicit_consent",
        "ch_existing_customer",
        "ch_cold_apollo",
        "fr_tier1",
        "fr_tier2",
        "fr_tier3",
        "fr_tier4",
        "fr_missing_source_notice",
        "fr_missing_opt_out",
        "fr_suppression",
        "de_unconfigured",
        "be_unconfigured",
        "lu_unconfigured",
        "us_out_of_scope",
        "missing_country",
        "conflicting_country",
        "suppression_keyring_incomplete",
        "shadow",
        "changed_artifact",
        "concurrent_suppression",
    }
    assert all(case["synthetic"] is True for case in cases)


def test_offline_eval_rule_cases_match_frozen_invariants() -> None:
    cases = json.loads(FIXTURE.read_text())

    evaluated = [case for case in cases if case["kind"] == "RULE"]

    assert len(evaluated) == 17
    assert {_evaluate(case) for case in evaluated} <= {
        "ALLOWED",
        "BLOCKED",
        "REVIEW_REQUIRED",
        "UNKNOWN",
    }
    for case in evaluated:
        assert _evaluate(case) == case["expected_state"]
