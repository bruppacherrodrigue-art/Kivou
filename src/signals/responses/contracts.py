"""Immutable, bounded, PII-minimized Response Intelligence contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

RESPONSE_INTELLIGENCE_VERSION = "response-intelligence-v1"
RESPONSE_TAXONOMY_VERSION = "response-taxonomy-v1"
RESPONSE_SAFETY_VERSION = "response-safety-rules-v1"
RESPONSE_EMAIL_RESOLUTION_VERSION = "response-email-resolution-v1"
RESPONSE_CONTENT_NORMALIZER_VERSION = "response-content-normalizer-v1"
RESPONSE_CLASSIFIER_VERSION = "response-classifier-v1"
RESPONSE_CLASSIFIER_OUTPUT_VERSION = "response-classifier-output-v1"
RESPONSE_EVIDENCE_VERSION = "response-evidence-v1"
RESPONSE_EVALUATION_STORE_VERSION = "response-evaluation-store-v1"
CONTENT_FINGERPRINT_VERSION = "response-content-fingerprint-v1"
UNCONFIGURED_CLASSIFIER_VERSION = "response-classifier-unconfigured-v1"

Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
StableRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
ShortCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class ResponseContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ResponseClassification(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    WRONG_PERSON = "WRONG_PERSON"
    REFERRAL = "REFERRAL"
    OUT_OF_OFFICE = "OUT_OF_OFFICE"
    AUTO_REPLY = "AUTO_REPLY"
    COMPLAINT = "COMPLAINT"
    SENSITIVE = "SENSITIVE"
    AMBIGUOUS = "AMBIGUOUS"


class ProcessingState(StrEnum):
    PLANNED = "PLANNED"
    IN_FLIGHT = "IN_FLIGHT"
    RETRY_WAIT = "RETRY_WAIT"
    FINALIZED = "FINALIZED"


class ResponseInputSource(StrEnum):
    WEBHOOK_V2 = "WEBHOOK_V2"
    INSTANTLY_EMAIL_V2 = "INSTANTLY_EMAIL_V2"


class ResponseReasonCode(StrEnum):
    EXPLICIT_COMMERCIAL_INTEREST = "EXPLICIT_COMMERCIAL_INTEREST"
    EXPLICIT_NEXT_STEP = "EXPLICIT_NEXT_STEP"
    NEGATIVE_DECLINE = "NEGATIVE_DECLINE"
    NOT_RELEVANT = "NOT_RELEVANT"
    EXPLICIT_STOP_REQUEST = "EXPLICIT_STOP_REQUEST"
    SPAM_COMPLAINT = "SPAM_COMPLAINT"
    PRIVACY_OBJECTION = "PRIVACY_OBJECTION"
    WRONG_RECIPIENT = "WRONG_RECIPIENT"
    REFERRAL_PROVIDED = "REFERRAL_PROVIDED"
    TEMPORARY_ABSENCE = "TEMPORARY_ABSENCE"
    AUTOMATED_RESPONSE = "AUTOMATED_RESPONSE"
    SENSITIVE_CONTEXT = "SENSITIVE_CONTEXT"
    INSUFFICIENT_CONTENT = "INSUFFICIENT_CONTENT"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    RESPONSE_IDENTITY_AMBIGUOUS = "RESPONSE_IDENTITY_AMBIGUOUS"
    RESPONSE_CONTENT_UNAVAILABLE = "RESPONSE_CONTENT_UNAVAILABLE"
    CLASSIFIER_UNAVAILABLE = "CLASSIFIER_UNAVAILABLE"
    CLASSIFIER_MALFORMED = "CLASSIFIER_MALFORMED"
    POLICY_NOT_EXECUTABLE = "POLICY_NOT_EXECUTABLE"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    NORMALIZATION_UNSAFE = "NORMALIZATION_UNSAFE"


_APPROVED_POSITIVE_REASONS = frozenset(
    {
        ResponseReasonCode.EXPLICIT_COMMERCIAL_INTEREST,
        ResponseReasonCode.EXPLICIT_NEXT_STEP,
    }
)

_CATEGORY_REASONS = {
    ResponseClassification.POSITIVE: _APPROVED_POSITIVE_REASONS,
    ResponseClassification.NEGATIVE: frozenset(
        {ResponseReasonCode.NEGATIVE_DECLINE, ResponseReasonCode.NOT_RELEVANT}
    ),
    ResponseClassification.UNSUBSCRIBE: frozenset(
        {ResponseReasonCode.EXPLICIT_STOP_REQUEST}
    ),
    ResponseClassification.WRONG_PERSON: frozenset(
        {ResponseReasonCode.WRONG_RECIPIENT}
    ),
    ResponseClassification.REFERRAL: frozenset(
        {ResponseReasonCode.REFERRAL_PROVIDED}
    ),
    ResponseClassification.OUT_OF_OFFICE: frozenset(
        {ResponseReasonCode.TEMPORARY_ABSENCE}
    ),
    ResponseClassification.AUTO_REPLY: frozenset(
        {ResponseReasonCode.AUTOMATED_RESPONSE}
    ),
    ResponseClassification.COMPLAINT: frozenset(
        {ResponseReasonCode.SPAM_COMPLAINT, ResponseReasonCode.PRIVACY_OBJECTION}
    ),
    ResponseClassification.SENSITIVE: frozenset(
        {ResponseReasonCode.SENSITIVE_CONTEXT}
    ),
    ResponseClassification.AMBIGUOUS: frozenset(
        {
            ResponseReasonCode.INSUFFICIENT_CONTENT,
            ResponseReasonCode.UNSUPPORTED_LANGUAGE,
            ResponseReasonCode.RESPONSE_IDENTITY_AMBIGUOUS,
            ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE,
            ResponseReasonCode.CLASSIFIER_UNAVAILABLE,
            ResponseReasonCode.CLASSIFIER_MALFORMED,
            ResponseReasonCode.POLICY_NOT_EXECUTABLE,
            ResponseReasonCode.PROVIDER_RATE_LIMITED,
            ResponseReasonCode.NORMALIZATION_UNSAFE,
        }
    ),
}


class ClassifierUsage(ResponseContract):
    input_tokens: int = Field(ge=0, le=1_000_000)
    output_tokens: int = Field(ge=0, le=1_000_000)
    cost: Decimal = Field(ge=0, le=Decimal("1000"))


class ResponseClassifierInput(ResponseContract):
    response_ref: Fingerprint
    campaign_ref: StableRef
    member_ref: StableRef
    acquisition_opportunity_id: StableRef
    contact_ref: StableRef
    language: Literal["fr", "en"]
    subject_transient: str = Field(max_length=998, repr=False)
    current_response_transient: str = Field(min_length=1, max_length=16_384, repr=False)
    taxonomy_version: Literal["response-taxonomy-v1"] = RESPONSE_TAXONOMY_VERSION
    safety_version: Literal["response-safety-rules-v1"] = RESPONSE_SAFETY_VERSION
    classifier_contract_version: Literal["response-classifier-v1"] = (
        RESPONSE_CLASSIFIER_VERSION
    )

    @field_validator("current_response_transient")
    @classmethod
    def bounded_utf8(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 16_384:
            raise ValueError("classifier content exceeds byte boundary")
        return value


class ResponseClassifierOutput(ResponseContract):
    classification: ResponseClassification
    confidence: Decimal = Field(ge=0, le=1)
    reason_codes: tuple[ResponseReasonCode, ...] = Field(min_length=1, max_length=8)
    hot_lead: bool
    review_required: bool
    classifier_version: ShortCode
    language: Literal["fr", "en"]
    human_response_confirmed: bool
    usage: ClassifierUsage | None = None

    @field_validator("confidence")
    @classmethod
    def finite_confidence(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or not math.isfinite(float(value)):
            raise ValueError("confidence must be finite")
        return value

    @model_validator(mode="after")
    def hot_lead_invariants(self) -> ResponseClassifierOutput:
        if self.hot_lead:
            if self.classification is not ResponseClassification.POSITIVE:
                raise ValueError("hot lead requires POSITIVE classification")
            if self.confidence < Decimal("0.85"):
                raise ValueError("hot lead confidence must be at least 0.85")
            if not self.human_response_confirmed or not self.review_required:
                raise ValueError("hot lead requires confirmed human review")
            if not set(self.reason_codes).intersection(_APPROVED_POSITIVE_REASONS):
                raise ValueError("hot lead requires an approved positive reason")
        if self.classification is ResponseClassification.POSITIVE and not self.hot_lead:
            raise ValueError("POSITIVE classification must derive a hot lead")
        if not set(self.reason_codes).intersection(_CATEGORY_REASONS[self.classification]):
            raise ValueError("reason codes do not match response classification")
        return self


class ContentFingerprint(ResponseContract):
    fingerprint: Fingerprint
    version: Literal["response-content-fingerprint-v1"] = CONTENT_FINGERPRINT_VERSION
    key_version: ShortCode


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


class ResponseReservation(ResponseContract):
    response_evaluation_id: Fingerprint
    response_ref: Fingerprint
    provider_event_ref: Fingerprint
    campaign_ref: StableRef
    member_ref: StableRef
    acquisition_opportunity_id: StableRef
    contact_ref: StableRef
    input_source: ResponseInputSource
    source_fingerprint: Fingerprint
    resolver_version: Literal["response-email-resolution-v1"] = (
        RESPONSE_EMAIL_RESOLUTION_VERSION
    )
    normalizer_version: Literal["response-content-normalizer-v1"] = (
        RESPONSE_CONTENT_NORMALIZER_VERSION
    )
    safety_version: Literal["response-safety-rules-v1"] = RESPONSE_SAFETY_VERSION
    taxonomy_version: Literal["response-taxonomy-v1"] = RESPONSE_TAXONOMY_VERSION
    classifier_version: ShortCode
    estimated_cost: Decimal = Field(ge=0, le=Decimal("1000"))
    supersedes_response_evaluation_id: Fingerprint | None = None
    reclassification_reason: ShortCode | None = None
    received_at: dt.datetime
    created_at: dt.datetime

    _received = field_validator("received_at", "created_at")(_aware)

    @model_validator(mode="after")
    def identity_and_reclassification(self) -> ResponseReservation:
        if self.response_evaluation_id != response_evaluation_id(
            self.response_ref, self.classifier_version
        ):
            raise ValueError("response evaluation identity mismatch")
        if (self.supersedes_response_evaluation_id is None) != (
            self.reclassification_reason is None
        ):
            raise ValueError("reclassification reference and reason must be paired")
        return self


class ResponseFinalization(ResponseContract):
    input_source: ResponseInputSource
    source_fingerprint: Fingerprint
    provider_email_id: StableRef | None = None
    provider_thread_id: StableRef | None = None
    content_fingerprint: Fingerprint | None = None
    content_fingerprint_version: Literal["response-content-fingerprint-v1"] | None = None
    content_fingerprint_key_version: ShortCode | None = None
    prompt_version: ShortCode | None = None
    model_version: ShortCode | None = None
    classification: ResponseClassification
    confidence: Decimal = Field(ge=0, le=1)
    reason_codes: tuple[ResponseReasonCode, ...] = Field(min_length=1, max_length=8)
    human_response_confirmed: bool
    hot_lead: bool
    review_required: bool
    next_action: Literal["request_human_review"] | None
    policy_evaluation_id: StableRef | None = None
    policy_action_fingerprint: Fingerprint | None = None
    policy_status: ShortCode | None = None
    actual_cost: Decimal | None = Field(default=None, ge=0, le=Decimal("1000"))
    input_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    disposition: ShortCode
    outcome_event_ref: StableRef | None = None
    next_action_event_ref: StableRef | None = None
    suppression_ref: StableRef | None = None
    evaluated_at: dt.datetime
    finalized_at: dt.datetime

    _times = field_validator("evaluated_at", "finalized_at")(_aware)

    @field_validator("confidence")
    @classmethod
    def finite_result_confidence(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("confidence must be finite")
        return value

    @model_validator(mode="after")
    def coherent_final_result(self) -> ResponseFinalization:
        content = (
            self.content_fingerprint,
            self.content_fingerprint_version,
            self.content_fingerprint_key_version,
        )
        if any(item is None for item in content) and any(item is not None for item in content):
            raise ValueError("content fingerprint fields must be all present or all absent")
        policy = (
            self.policy_evaluation_id,
            self.policy_action_fingerprint,
            self.policy_status,
        )
        if any(item is None for item in policy) and any(item is not None for item in policy):
            raise ValueError("policy provenance fields must be all present or all absent")
        if self.hot_lead:
            if (
                self.classification is not ResponseClassification.POSITIVE
                or self.confidence < Decimal("0.85")
                or not self.human_response_confirmed
                or not self.review_required
                or self.next_action != "request_human_review"
                or not set(self.reason_codes).intersection(_APPROVED_POSITIVE_REASONS)
            ):
                raise ValueError("hot lead finalization invariant violated")
        elif self.classification is ResponseClassification.POSITIVE:
            raise ValueError("POSITIVE finalization must be hot")
        if self.classification in {
            ResponseClassification.AUTO_REPLY,
            ResponseClassification.OUT_OF_OFFICE,
        } and (self.human_response_confirmed or self.outcome_event_ref is not None):
            raise ValueError("machine response cannot be a human outcome")
        return self


@dataclass(frozen=True)
class ContentFingerprintKeyring:
    current_key_version: str
    keys: dict[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        if self.current_key_version not in self.keys or not self.keys[self.current_key_version]:
            raise ValueError("current response content fingerprint key must be available")
        if len(self.keys) > 8:
            raise ValueError("response content fingerprint keyring is too large")
        if any(not version or len(version) > 100 for version in self.keys):
            raise ValueError("invalid response content fingerprint key version")


def _fingerprint(domain: bytes, value: dict[str, object]) -> str:
    encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(domain + b"\0" + encoded.encode("utf-8")).hexdigest()


def response_ref(*, provider_event_ref: str, campaign_ref: str, member_ref: str) -> str:
    return _fingerprint(
        b"kivou:response-ref:v1",
        {
            "provider_event_ref": provider_event_ref,
            "campaign_ref": campaign_ref,
            "member_ref": member_ref,
        },
    )


def response_evaluation_id(response_ref_value: str, classifier_version: str) -> str:
    if not classifier_version or len(classifier_version) > 100:
        raise ValueError("classifier_version is required for evaluation identity")
    return _fingerprint(
        b"kivou:response-evaluation:v1",
        {"response_ref": response_ref_value, "classifier_version": classifier_version},
    )


def content_fingerprint(
    *,
    subject: str,
    current_response: str,
    keyring: ContentFingerprintKeyring,
) -> ContentFingerprint:
    canonical = json.dumps(
        {
            "version": CONTENT_FINGERPRINT_VERSION,
            "subject": subject,
            "current_response": current_response,
        },
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    value = hmac.new(
        keyring.keys[keyring.current_key_version],
        b"kivou:response-content-fingerprint:v1\0" + canonical,
        hashlib.sha256,
    ).hexdigest()
    return ContentFingerprint(
        fingerprint=value,
        key_version=keyring.current_key_version,
    )


__all__ = [
    "CONTENT_FINGERPRINT_VERSION",
    "RESPONSE_CLASSIFIER_VERSION",
    "RESPONSE_CONTENT_NORMALIZER_VERSION",
    "RESPONSE_EMAIL_RESOLUTION_VERSION",
    "RESPONSE_EVALUATION_STORE_VERSION",
    "RESPONSE_EVIDENCE_VERSION",
    "RESPONSE_INTELLIGENCE_VERSION",
    "RESPONSE_SAFETY_VERSION",
    "RESPONSE_TAXONOMY_VERSION",
    "UNCONFIGURED_CLASSIFIER_VERSION",
    "ClassifierUsage",
    "ContentFingerprint",
    "ContentFingerprintKeyring",
    "ProcessingState",
    "ResponseClassification",
    "ResponseClassifierInput",
    "ResponseClassifierOutput",
    "ResponseFinalization",
    "ResponseInputSource",
    "ResponseReasonCode",
    "ResponseReservation",
    "content_fingerprint",
    "response_evaluation_id",
    "response_ref",
]
