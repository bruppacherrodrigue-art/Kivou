from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.responses.contracts import (
    CONTENT_FINGERPRINT_VERSION,
    RESPONSE_SAFETY_VERSION,
    RESPONSE_TAXONOMY_VERSION,
    ClassifierUsage,
    ContentFingerprintKeyring,
    ProcessingState,
    ResponseClassification,
    ResponseClassifierInput,
    ResponseClassifierOutput,
    ResponseReasonCode,
    content_fingerprint,
    response_evaluation_id,
    response_ref,
)


def test_response_taxonomy_and_processing_states_are_closed() -> None:
    assert {item.value for item in ResponseClassification} == {
        "POSITIVE",
        "NEGATIVE",
        "UNSUBSCRIBE",
        "WRONG_PERSON",
        "REFERRAL",
        "OUT_OF_OFFICE",
        "AUTO_REPLY",
        "COMPLAINT",
        "SENSITIVE",
        "AMBIGUOUS",
    }
    assert {item.value for item in ProcessingState} == {
        "PLANNED",
        "IN_FLIGHT",
        "RETRY_WAIT",
        "FINALIZED",
    }
    assert RESPONSE_TAXONOMY_VERSION == "response-taxonomy-v1"
    assert RESPONSE_SAFETY_VERSION == "response-safety-rules-v1"


def test_response_and_evaluation_identity_are_deterministic_and_versioned() -> None:
    first = response_ref(
        provider_event_ref="a" * 64,
        campaign_ref="b" * 64,
        member_ref="c" * 64,
    )
    assert first == response_ref(
        provider_event_ref="a" * 64,
        campaign_ref="b" * 64,
        member_ref="c" * 64,
    )
    assert first != response_ref(
        provider_event_ref="d" * 64,
        campaign_ref="b" * 64,
        member_ref="c" * 64,
    )
    assert response_evaluation_id(first, "response-classifier-v1") != response_evaluation_id(
        first, RESPONSE_SAFETY_VERSION
    )


def test_content_fingerprint_is_keyed_versioned_and_does_not_expose_content() -> None:
    keyring = ContentFingerprintKeyring(
        current_key_version="response-key-v1",
        keys={"response-key-v1": b"synthetic-response-content-key"},
    )

    value = content_fingerprint(
        subject="Synthetic subject",
        current_response="Synthetic reply",
        keyring=keyring,
    )

    assert value.version == CONTENT_FINGERPRINT_VERSION
    assert value.key_version == "response-key-v1"
    assert len(value.fingerprint) == 64
    assert "Synthetic" not in repr(value)
    assert value.fingerprint != content_fingerprint(
        subject="Synthetic subject",
        current_response="Different reply",
        keyring=keyring,
    ).fingerprint


def _classifier_output(**updates: object) -> ResponseClassifierOutput:
    values: dict[str, object] = {
        "classification": ResponseClassification.POSITIVE,
        "confidence": Decimal("0.90"),
        "reason_codes": (ResponseReasonCode.EXPLICIT_COMMERCIAL_INTEREST,),
        "hot_lead": True,
        "review_required": True,
        "classifier_version": "synthetic-classifier-v1",
        "language": "en",
        "human_response_confirmed": True,
        "usage": ClassifierUsage(input_tokens=20, output_tokens=10, cost=Decimal("0.001")),
    }
    values.update(updates)
    return ResponseClassifierOutput.model_validate(values)


def test_classifier_contract_is_strict_and_positive_hot_invariants_are_structural() -> None:
    assert _classifier_output().hot_lead is True
    with pytest.raises(ValidationError):
        ResponseClassifierOutput.model_validate(
            {**_classifier_output().model_dump(), "free_form_rationale": "hidden prose"}
        )
    with pytest.raises(ValidationError, match="hot lead"):
        _classifier_output(classification=ResponseClassification.NEGATIVE)
    with pytest.raises(ValidationError, match="confidence"):
        _classifier_output(confidence=Decimal("0.84"))
    with pytest.raises(ValidationError, match="approved positive reason"):
        _classifier_output(reason_codes=(ResponseReasonCode.NEGATIVE_DECLINE,))


def test_classifier_input_hides_transient_content_and_rejects_unknown_fields() -> None:
    value = ResponseClassifierInput(
        response_ref="a" * 64,
        campaign_ref="b" * 64,
        member_ref="c" * 64,
        acquisition_opportunity_id="d" * 64,
        contact_ref="e" * 64,
        language="fr",
        subject_transient="Sujet synthétique",
        current_response_transient="Oui, montrez-moi les exemples.",
    )
    assert "montrez-moi" not in repr(value)
    with pytest.raises(ValidationError):
        ResponseClassifierInput.model_validate(
            {**value.model_dump(), "provider_ai_interest": "interested"}
        )


def test_safety_classifier_identity_is_non_null_and_bounded() -> None:
    assert response_evaluation_id("a" * 64, RESPONSE_SAFETY_VERSION)
    with pytest.raises((ValidationError, ValueError)):
        response_evaluation_id("a" * 64, "")
