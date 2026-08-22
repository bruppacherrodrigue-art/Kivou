from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_policy_gateway import NOW, request, snapshot

from signals.policy.contracts import (
    AvailabilityState,
    OperationalReadiness,
    PolicyStatus,
    ReadinessState,
)
from signals.policy.evaluator import evaluate_policy
from signals.policy.mapper import map_proposed_action
from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope
from signals.responses.classifier import (
    ResponseClassifierUnavailable,
    UnconfiguredResponseClassifier,
    derive_business_disposition,
)
from signals.responses.contracts import (
    ResponseClassification,
    ResponseClassifierInput,
    ResponseClassifierOutput,
    ResponseReasonCode,
)
from signals.responses.policy import build_classify_response_policy_request
from signals.responses.worker import ResponsePolicyFacts
from signals.supervisor.contracts import ProposedAction

REF = "a" * 64


def _trusted() -> dict[str, object]:
    values = request().model_dump(mode="python")
    for key in (
        "command",
        "target_ref",
        "canonical_arguments",
        "action_fingerprint",
        "reason_codes",
        "evidence_refs",
        "proposed_cost",
    ):
        values.pop(key)
    return values


def _action(*, target_ref: str = REF, arguments=None) -> ProposedAction:
    return ProposedAction(
        command="classify_response",
        target_ref=target_ref,
        arguments={} if arguments is None else arguments,
        reason_codes=("RESPONSE_TRIAGE_REQUESTED",),
        evidence_refs=(f"response:{REF}",),
        estimated_cost=Decimal("0.01"),
    )


def _input() -> ResponseClassifierInput:
    return ResponseClassifierInput(
        response_ref=REF,
        campaign_ref="campaign-ref",
        member_ref="member-ref",
        acquisition_opportunity_id="opportunity-ref",
        contact_ref="contact-ref",
        language="en",
        subject_transient="Re: hello",
        current_response_transient="Yes, please show me examples.",
    )


def _facts(**updates) -> ResponsePolicyFacts:
    values = {
        "response_ref": REF,
        "provider_event_ref": "b" * 64,
        "provider_event_fingerprint": "c" * 64,
        "provider_workspace_ref": "workspace-ref",
        "campaign_ref": "campaign-ref",
        "member_ref": "member-ref",
        "acquisition_opportunity_id": "opp-1",
        "contact_ref": "contact-ref",
        "provider_email_id": "01a028e4-5069-7b56-ae56-b7e4352c53fa",
        "source_fingerprint": "d" * 64,
        "content_fingerprint": "e" * 64,
        "content_fingerprint_version": "response-content-fingerprint-v1",
        "content_fingerprint_key_version": "content-key-v1",
        "resolver_version": "response-email-resolution-v1",
        "normalizer_version": "response-content-normalizer-v1",
        "safety_version": "response-safety-rules-v1",
        "taxonomy_version": "response-taxonomy-v1",
        "classifier_version": "synthetic-classifier-v1",
        "country": "CH",
        "wedge": "construction",
        "language": "fr",
        "human_response_confirmed": True,
        "provider_auto_reply": False,
        "observed_at": NOW,
        "max_proposed_cost": Decimal("0.01"),
    }
    values.update(updates)
    return ResponsePolicyFacts.model_validate(values)


def _response_request(**updates):
    values = {
        "expected_opportunity_version": 1,
        "operational": OperationalReadiness(runtime_revision="response-runtime-v1"),
        "currency": "CHF",
    }
    values.update(updates)
    return build_classify_response_policy_request(_facts(), **values)


def test_classify_response_policy_is_preparatory_but_metered_and_controlled() -> None:
    profile = COMMAND_POLICIES["classify_response"]

    assert profile.risk_class is RiskClass.PREPARATORY
    assert profile.target_scope is TargetScope.OPPORTUNITY
    assert profile.required_evidence == ("RESPONSE",)
    assert profile.uses_budget is True
    assert profile.uses_volume is False
    assert profile.uses_provider_quota is True
    assert profile.uses_send_controls is False
    assert profile.requires_control_plane is True
    assert profile.requires_compliance is False


def test_kivou_builds_exact_response_evidence_without_raw_content() -> None:
    built = _response_request()

    assert built.command == "classify_response"
    assert built.target_ref == REF
    assert built.evidence.claims == ("RESPONSE",)
    assert built.proposed_volume == 0
    assert built.proposed_cost == Decimal("0.01")
    assert built.compliance.state.value == "UNKNOWN"
    assert built.action_fingerprint != built.evidence_refs[0]
    assert "response-content-fingerprint-v1" in built.canonical_arguments
    for forbidden in ("subject", "body", "html", "reply_text", "lead_email"):
        assert forbidden not in built.canonical_arguments


@pytest.mark.parametrize(
    ("request_updates", "snapshot_updates", "status"),
    [
        ({}, {"budget": snapshot().budget.model_copy(update={"cost_cap": Decimal("0")})}, PolicyStatus.BUDGET_EXCEEDED),
        ({"operational": OperationalReadiness(runtime_revision="v1", provider_quota=ReadinessState.UNKNOWN)}, {}, PolicyStatus.RATE_LIMITED),
        ({"operational": OperationalReadiness(runtime_revision="v1", provider_control_plane=AvailabilityState.UNAVAILABLE)}, {}, PolicyStatus.RATE_LIMITED),
    ],
)
def test_policy_budget_quota_and_control_denial_prevent_classification(
    request_updates, snapshot_updates, status
) -> None:
    decision = evaluate_policy(
        _response_request(**request_updates),
        snapshot(**snapshot_updates),
        NOW,
    )

    assert decision.status is status
    assert decision.executable is False


def test_hermes_classify_response_accepts_only_opaque_ref_and_no_arguments() -> None:
    mapped = map_proposed_action(_action(), **_trusted())

    assert mapped.target_ref == REF
    assert mapped.canonical_arguments == "{}"


@pytest.mark.parametrize(
    ("target_ref", "arguments"),
    [
        ("not-an-opaque-response-ref", {}),
        (REF, {"text": "prospect content"}),
        (REF, {"classification": "POSITIVE"}),
        (REF, {"retry": 5}),
    ],
)
def test_hermes_cannot_supply_response_content_or_semantics(target_ref, arguments) -> None:
    with pytest.raises(ValueError, match="classify_response"):
        map_proposed_action(
            _action(target_ref=target_ref, arguments=arguments), **_trusted()
        )


def test_default_classifier_is_explicitly_unconfigured_and_does_not_fallback() -> None:
    classifier = UnconfiguredResponseClassifier()

    with pytest.raises(ResponseClassifierUnavailable):
        classifier.classify(_input())


def test_classifier_output_is_strict_and_has_no_free_form_rationale() -> None:
    with pytest.raises(ValidationError, match="extra"):
        ResponseClassifierOutput.model_validate(
            {
                "classification": "NEGATIVE",
                "confidence": "0.95",
                "reason_codes": ["NEGATIVE_DECLINE"],
                "hot_lead": False,
                "review_required": False,
                "classifier_version": "synthetic-classifier-v1",
                "language": "en",
                "human_response_confirmed": True,
                "rationale": "hidden reasoning must not cross the boundary",
            }
        )


def test_positive_requires_approved_reason_confidence_human_and_review() -> None:
    result = ResponseClassifierOutput(
        classification=ResponseClassification.POSITIVE,
        confidence=Decimal("0.85"),
        reason_codes=(ResponseReasonCode.EXPLICIT_COMMERCIAL_INTEREST,),
        hot_lead=True,
        review_required=True,
        classifier_version="synthetic-classifier-v1",
        language="fr",
        human_response_confirmed=True,
    )

    disposition = derive_business_disposition(result)
    assert disposition.hot_lead is True
    assert disposition.record_replied is True
    assert disposition.next_action == "request_human_review"


@pytest.mark.parametrize(
    ("classification", "human", "record_replied", "next_action"),
    [
        (ResponseClassification.NEGATIVE, True, True, None),
        (ResponseClassification.WRONG_PERSON, True, True, "request_human_review"),
        (ResponseClassification.REFERRAL, True, True, "request_human_review"),
        (ResponseClassification.SENSITIVE, True, True, "request_human_review"),
        (ResponseClassification.AMBIGUOUS, False, False, "request_human_review"),
        (ResponseClassification.AUTO_REPLY, False, False, None),
        (ResponseClassification.OUT_OF_OFFICE, False, False, None),
    ],
)
def test_kivou_derives_business_effects_not_the_model(
    classification, human, record_replied, next_action
) -> None:
    reason = {
        ResponseClassification.NEGATIVE: ResponseReasonCode.NEGATIVE_DECLINE,
        ResponseClassification.WRONG_PERSON: ResponseReasonCode.WRONG_RECIPIENT,
        ResponseClassification.REFERRAL: ResponseReasonCode.REFERRAL_PROVIDED,
        ResponseClassification.SENSITIVE: ResponseReasonCode.SENSITIVE_CONTEXT,
        ResponseClassification.AMBIGUOUS: ResponseReasonCode.INSUFFICIENT_CONTENT,
        ResponseClassification.AUTO_REPLY: ResponseReasonCode.AUTOMATED_RESPONSE,
        ResponseClassification.OUT_OF_OFFICE: ResponseReasonCode.TEMPORARY_ABSENCE,
    }[classification]
    output = ResponseClassifierOutput(
        classification=classification,
        confidence=Decimal("0.75"),
        reason_codes=(reason,),
        hot_lead=False,
        review_required=next_action is not None,
        classifier_version="synthetic-classifier-v1",
        language="en",
        human_response_confirmed=human,
    )

    disposition = derive_business_disposition(output)
    assert disposition.record_replied is record_replied
    assert disposition.next_action == next_action
    assert disposition.hot_lead is False
