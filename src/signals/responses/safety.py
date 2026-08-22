"""Pure deterministic response safety rules that always precede classification."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict

from signals.responses.contracts import ResponseClassification, ResponseReasonCode


class ResponseSafetyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    final: bool
    classification: ResponseClassification | None
    reason_codes: tuple[ResponseReasonCode, ...]
    human_response_confirmed: bool
    hot_lead: Literal[False] = False
    review_required: bool


def _catalog(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value, re.IGNORECASE) for value in values)


_UNSUBSCRIBE = {
    "en": _catalog(
        r"\bplease\s+unsubscribe\s+me\b",
        r"\bunsubscribe\s+me\b",
        r"\bremove\s+me\s+from\s+(?:your|the)\s+(?:email\s+)?list\b",
        r"\bdo\s+not\s+contact\s+me\s+again\b",
        r"\bdon['’]t\s+contact\s+me\s+again\b",
        r"\bstop\s+(?:emailing|contacting)\s+me\b",
        r"\bno\s+more\s+emails\b",
    ),
    "fr": _catalog(
        r"\bdésabonnez[ -]moi\b",
        r"\bme\s+désabonner\b",
        r"\bretirez[ -]moi\s+de\s+votre\s+liste\b",
        r"\bne\s+(?:plus|jamais)\s+me\s+contacte[rz]\b",
        r"\bcessez\s+de\s+m['’]écrire\b",
        r"\bplus\s+de\s+courriels\b",
    ),
}

_COMPLAINT = {
    "en": (
        (re.compile(r"\bthis\s+is\s+spam\b", re.IGNORECASE), ResponseReasonCode.SPAM_COMPLAINT),
        (re.compile(r"\bspam\s+(?:message|email)\b", re.IGNORECASE), ResponseReasonCode.SPAM_COMPLAINT),
        (
            re.compile(r"\bprivacy\s+(?:violation|complaint|objection)\b", re.IGNORECASE),
            ResponseReasonCode.PRIVACY_OBJECTION,
        ),
        (
            re.compile(r"\bwhy\s+did\s+you\s+(?:obtain|use)\s+my\s+data\b", re.IGNORECASE),
            ResponseReasonCode.PRIVACY_OBJECTION,
        ),
    ),
    "fr": (
        (re.compile(r"\bc['’]est\s+du\s+spam\b", re.IGNORECASE), ResponseReasonCode.SPAM_COMPLAINT),
        (
            re.compile(r"\batteinte\s+à\s+ma\s+vie\s+privée\b", re.IGNORECASE),
            ResponseReasonCode.PRIVACY_OBJECTION,
        ),
        (
            re.compile(r"\bplainte\s+(?:vie\s+privée|données\s+personnelles)\b", re.IGNORECASE),
            ResponseReasonCode.PRIVACY_OBJECTION,
        ),
    ),
}

_OUT_OF_OFFICE = {
    "en": _catalog(
        r"\bout\s+of\s+(?:the\s+)?office\b",
        r"\baway\s+until\b",
        r"\bon\s+(?:annual\s+)?leave\b",
    ),
    "fr": _catalog(
        r"\babsent(?:e)?\s+du\s+bureau\b",
        r"\babsent(?:e)?\s+jusqu['’]au\b",
        r"\ben\s+congé\b",
        r"\ben\s+vacances\b",
    ),
}


def _matches(patterns: tuple[re.Pattern[str], ...], value: str) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def evaluate_response_safety(
    *,
    event_type: str,
    language: str,
    subject: str,
    current_response: str,
    provider_auto_reply: bool | None,
) -> ResponseSafetyResult:
    """Return a conclusive safety result or defer safe human prose to classification."""

    text = unicodedata.normalize("NFC", f"{subject}\n{current_response}").strip()
    if language not in {"fr", "en"}:
        return ResponseSafetyResult(
            final=True,
            classification=ResponseClassification.AMBIGUOUS,
            reason_codes=(ResponseReasonCode.UNSUPPORTED_LANGUAGE,),
            human_response_confirmed=False,
            review_required=True,
        )
    human = event_type == "reply_received" and provider_auto_reply is not True
    # Safety phrases are bilingual regardless of the campaign language.  A
    # recipient replying in the other supported language must still be able to
    # stop contact deterministically.
    if any(_matches(patterns, text) for patterns in _UNSUBSCRIBE.values()):
        return ResponseSafetyResult(
            final=True,
            classification=ResponseClassification.UNSUBSCRIBE,
            reason_codes=(ResponseReasonCode.EXPLICIT_STOP_REQUEST,),
            human_response_confirmed=human,
            review_required=False,
        )
    for catalog in _COMPLAINT.values():
        for pattern, reason in catalog:
            if pattern.search(text):
                return ResponseSafetyResult(
                    final=True,
                    classification=ResponseClassification.COMPLAINT,
                    reason_codes=(reason,),
                    human_response_confirmed=human,
                    review_required=True,
                )
    if any(_matches(patterns, text) for patterns in _OUT_OF_OFFICE.values()):
        return ResponseSafetyResult(
            final=True,
            classification=ResponseClassification.OUT_OF_OFFICE,
            reason_codes=(ResponseReasonCode.TEMPORARY_ABSENCE,),
            human_response_confirmed=False,
            review_required=False,
        )
    if event_type == "auto_reply_received" or provider_auto_reply is True:
        return ResponseSafetyResult(
            final=True,
            classification=ResponseClassification.AUTO_REPLY,
            reason_codes=(ResponseReasonCode.AUTOMATED_RESPONSE,),
            human_response_confirmed=False,
            review_required=False,
        )
    if not current_response.strip():
        return ResponseSafetyResult(
            final=True,
            classification=ResponseClassification.AMBIGUOUS,
            reason_codes=(ResponseReasonCode.INSUFFICIENT_CONTENT,),
            human_response_confirmed=False,
            review_required=True,
        )
    return ResponseSafetyResult(
        final=False,
        classification=None,
        reason_codes=(),
        human_response_confirmed=False,
        review_required=False,
    )


__all__ = ["ResponseSafetyResult", "evaluate_response_safety"]
