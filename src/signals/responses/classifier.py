"""Provider-neutral structured response-classifier boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from signals.responses.contracts import (
    ResponseClassification,
    ResponseClassifierInput,
    ResponseClassifierOutput,
)


class ResponseClassifierUnavailable(RuntimeError):
    """No bounded classifier execution is currently available."""


class ResponseClassifier(Protocol):
    @property
    def classifier_version(self) -> str: ...

    def classify(self, value: ResponseClassifierInput) -> ResponseClassifierOutput: ...


class UnconfiguredResponseClassifier:
    """Fail-closed repository default; it has no model or network dependency."""

    classifier_version = "response-classifier-unconfigured-v1"

    def classify(self, value: ResponseClassifierInput) -> ResponseClassifierOutput:
        del value
        raise ResponseClassifierUnavailable("response classifier is not configured")


@dataclass(frozen=True)
class ResponseBusinessDisposition:
    hot_lead: bool
    review_required: bool
    record_replied: bool
    next_action: str | None


def derive_business_disposition(
    result: ResponseClassifierOutput,
) -> ResponseBusinessDisposition:
    """Derive workflow effects from taxonomy; the model cannot choose them."""

    classification = result.classification
    if classification is ResponseClassification.POSITIVE:
        return ResponseBusinessDisposition(True, True, True, "request_human_review")
    if classification is ResponseClassification.NEGATIVE:
        return ResponseBusinessDisposition(False, False, True, None)
    if classification in {
        ResponseClassification.WRONG_PERSON,
        ResponseClassification.REFERRAL,
    }:
        return ResponseBusinessDisposition(False, True, True, "request_human_review")
    if classification is ResponseClassification.SENSITIVE:
        return ResponseBusinessDisposition(
            False,
            True,
            result.human_response_confirmed,
            "request_human_review",
        )
    if classification is ResponseClassification.AMBIGUOUS:
        return ResponseBusinessDisposition(
            False,
            True,
            result.human_response_confirmed,
            "request_human_review",
        )
    if classification in {
        ResponseClassification.AUTO_REPLY,
        ResponseClassification.OUT_OF_OFFICE,
    }:
        return ResponseBusinessDisposition(False, False, False, None)
    if classification is ResponseClassification.UNSUBSCRIBE:
        return ResponseBusinessDisposition(
            False, False, result.human_response_confirmed, None
        )
    if classification is ResponseClassification.COMPLAINT:
        return ResponseBusinessDisposition(
            False,
            True,
            result.human_response_confirmed,
            "request_human_review",
        )
    raise AssertionError(f"unhandled response classification: {classification.value}")


__all__ = [
    "ResponseBusinessDisposition",
    "ResponseClassifier",
    "ResponseClassifierUnavailable",
    "UnconfiguredResponseClassifier",
    "derive_business_disposition",
]
