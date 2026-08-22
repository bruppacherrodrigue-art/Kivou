from __future__ import annotations

import pytest

from signals.responses.normalization import (
    MAX_CLASSIFIER_INPUT_BYTES,
    ResponseContentUnavailable,
    normalize_response_content,
)


def test_text_is_preferred_and_nonsemantic_whitespace_is_normalized() -> None:
    result = normalize_response_content(
        subject="  Re:  Signal\r\n",
        body_text="Bonjour,\r\n\r\n  oui,   cela m’intéresse.  ",
        body_html="<p>HTML must not win</p>",
    )

    assert result.subject == "Re: Signal"
    assert result.current_response == "Bonjour,\n\noui, cela m’intéresse."
    assert result.source == "TEXT"


def test_html_fallback_is_local_and_discards_active_or_remote_content() -> None:
    result = normalize_response_content(
        subject="Réponse",
        body_text=None,
        body_html=(
            "<p>Oui, parlons-en.</p><script>fetch('https://forbidden.invalid')</script>"
            "<img src='https://forbidden.invalid/pixel'>"
        ),
    )

    assert result.current_response == "Oui, parlons-en."
    assert "fetch" not in result.current_response
    assert "forbidden.invalid" not in result.current_response
    assert result.source == "HTML"


def test_quoted_prior_message_and_gt_lines_are_removed() -> None:
    result = normalize_response_content(
        subject="Re: Signals",
        body_text=(
            "Yes, please send examples.\n\n"
            "> Would you like to see procurement signals?\n"
            "On Fri, Aug 21, 2026 at 09:00 Kivou wrote:\n"
            "This quoted outbound copy says I am interested."
        ),
        body_html=None,
    )

    assert result.current_response == "Yes, please send examples."
    assert "Kivou wrote" not in result.current_response
    assert "outbound copy" not in result.current_response


def test_unicode_is_canonicalized() -> None:
    composed = normalize_response_content(
        subject="Réponse",
        body_text="Intéressé",
        body_html=None,
    )
    assert composed.subject == "Réponse"
    assert composed.current_response == "Intéressé"


@pytest.mark.parametrize(
    ("text", "html"),
    [(None, None), ("   ", None), (None, "<script>secret</script>")],
)
def test_missing_or_unsafe_current_response_fails_closed(text, html) -> None:
    with pytest.raises(ResponseContentUnavailable):
        normalize_response_content(subject="Re", body_text=text, body_html=html)


def test_classifier_input_has_a_hard_16_kib_boundary() -> None:
    accepted = normalize_response_content(
        subject="Re",
        body_text="x" * (MAX_CLASSIFIER_INPUT_BYTES - 2),
        body_html=None,
    )
    assert len(accepted.current_response.encode()) <= MAX_CLASSIFIER_INPUT_BYTES

    marker = "SENSITIVE-OVERSIZED-CONTENT"
    with pytest.raises(ResponseContentUnavailable) as captured:
        normalize_response_content(
            subject="Re",
            body_text=marker + ("x" * MAX_CLASSIFIER_INPUT_BYTES),
            body_html=None,
        )
    assert marker not in str(captured.value)
