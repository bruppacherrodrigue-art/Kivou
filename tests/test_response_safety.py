from __future__ import annotations

import pytest

from signals.responses.contracts import ResponseClassification, ResponseReasonCode
from signals.responses.safety import evaluate_response_safety


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "Please unsubscribe me and do not contact me again."),
        ("fr", "Merci de me désabonner et de ne plus me contacter."),
    ],
)
def test_explicit_unsubscribe_is_the_highest_precedence(language, text) -> None:
    result = evaluate_response_safety(
        event_type="reply_received",
        language=language,
        subject="Re",
        current_response=text + " I would otherwise like a demo.",
        provider_auto_reply=False,
    )

    assert result.classification is ResponseClassification.UNSUBSCRIBE
    assert result.reason_codes == (ResponseReasonCode.EXPLICIT_STOP_REQUEST,)
    assert result.human_response_confirmed is True
    assert result.final is True


@pytest.mark.parametrize(
    ("language", "text", "reason"),
    [
        ("en", "This is spam. Why did you contact me?", ResponseReasonCode.SPAM_COMPLAINT),
        (
            "fr",
            "C'est une atteinte à ma vie privée. Pourquoi me contactez-vous ?",
            ResponseReasonCode.PRIVACY_OBJECTION,
        ),
    ],
)
def test_complaint_beats_positive_language(language, text, reason) -> None:
    result = evaluate_response_safety(
        event_type="reply_received",
        language=language,
        subject="Re",
        current_response=text + " Montrez-moi aussi une démo.",
        provider_auto_reply=False,
    )

    assert result.classification is ResponseClassification.COMPLAINT
    assert result.reason_codes == (reason,)
    assert result.human_response_confirmed is True
    assert result.review_required is True
    assert result.hot_lead is False


def test_provider_auto_reply_is_machine_safety_without_human_outcome() -> None:
    result = evaluate_response_safety(
        event_type="auto_reply_received",
        language="en",
        subject="Automatic reply",
        current_response="Thank you. This inbox is automated.",
        provider_auto_reply=True,
    )

    assert result.classification is ResponseClassification.AUTO_REPLY
    assert result.reason_codes == (ResponseReasonCode.AUTOMATED_RESPONSE,)
    assert result.human_response_confirmed is False
    assert result.review_required is False


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "I am out of office until 2 September."),
        ("fr", "Je suis absent du bureau jusqu'au 2 septembre."),
    ],
)
def test_out_of_office_is_not_a_human_reply(language, text) -> None:
    result = evaluate_response_safety(
        event_type="reply_received",
        language=language,
        subject="Automatic reply",
        current_response=text,
        provider_auto_reply=True,
    )

    assert result.classification is ResponseClassification.OUT_OF_OFFICE
    assert result.reason_codes == (ResponseReasonCode.TEMPORARY_ABSENCE,)
    assert result.human_response_confirmed is False


def test_unsubscribe_still_beats_provider_auto_reply_flag() -> None:
    result = evaluate_response_safety(
        event_type="auto_reply_received",
        language="en",
        subject="Auto",
        current_response="Please unsubscribe me.",
        provider_auto_reply=True,
    )
    assert result.classification is ResponseClassification.UNSUBSCRIBE


@pytest.mark.parametrize("language", ["de", "it", "es"])
def test_unsupported_language_fails_closed_to_ambiguous_review(language) -> None:
    result = evaluate_response_safety(
        event_type="reply_received",
        language=language,
        subject="Re",
        current_response="Bitte senden Sie Beispiele.",
        provider_auto_reply=False,
    )

    assert result.classification is ResponseClassification.AMBIGUOUS
    assert result.reason_codes == (ResponseReasonCode.UNSUPPORTED_LANGUAGE,)
    assert result.review_required is True
    assert result.hot_lead is False


def test_missing_content_fails_closed_without_positive_inference() -> None:
    result = evaluate_response_safety(
        event_type="reply_received",
        language="en",
        subject="",
        current_response="",
        provider_auto_reply=False,
    )
    assert result.classification is ResponseClassification.AMBIGUOUS
    assert result.reason_codes == (ResponseReasonCode.INSUFFICIENT_CONTENT,)


def test_non_safety_human_content_is_deferred_to_semantic_classifier() -> None:
    result = evaluate_response_safety(
        event_type="reply_received",
        language="en",
        subject="Re",
        current_response="Yes, show me a few examples.",
        provider_auto_reply=False,
    )
    assert result.final is False
    assert result.classification is None
    assert result.reason_codes == ()
