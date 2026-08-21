"""Integrity validation for deterministic personalization artifacts."""

from __future__ import annotations

import re

from signals.personalization.catalog import (
    SUPPORTED_LANGUAGES,
    CatalogMessage,
    render_catalog_message,
)

MAX_SUBJECT_LENGTH = 90
MAX_GREETING_LENGTH = 80
MAX_BODY_LENGTH = 700

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_HEADER = re.compile(r"[,;:]\s*(?:to|cc|bcc)\s*[:<]", re.IGNORECASE)


class PersonalizationValidationError(ValueError):
    """A purported artifact falls outside the frozen v1 contract."""


def safe_first_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        return None
    if any(char in normalized for char in "\r\n\x00") or _EMAIL.search(normalized) or _URL.search(normalized):
        return None
    if any(ord(char) < 32 for char in normalized) or _HEADER.search(normalized):
        return None
    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ' -]+", normalized):
        return None
    return normalized


def require_safe_awardee(value: str) -> str:
    if not value or len(value) > 512 or any(ord(char) < 32 for char in value):
        raise PersonalizationValidationError("unsafe awardee")
    if _EMAIL.search(value) or _URL.search(value):
        raise PersonalizationValidationError("unsafe awardee")
    return value


def validate_catalog_message(
    message: CatalogMessage,
    *,
    expected: CatalogMessage | None = None,
    awardee: str | None = None,
    public_event_sentence: str | None = None,
    need_category: str | None = None,
    first_name: str | None = None,
) -> None:
    if message.language not in SUPPORTED_LANGUAGES:
        raise PersonalizationValidationError("unsupported language")
    if not message.subject or len(message.subject) > MAX_SUBJECT_LENGTH:
        raise PersonalizationValidationError("subject is empty or overlong")
    if not message.greeting or len(message.greeting) > MAX_GREETING_LENGTH:
        raise PersonalizationValidationError("greeting is empty or overlong")
    if not message.body or len(message.body) > MAX_BODY_LENGTH:
        raise PersonalizationValidationError("body is empty or overlong")
    if len(message.body.split("\n\n")) != 2:
        raise PersonalizationValidationError("v1 requires two body paragraphs")
    if "\n" in message.subject or "\r" in message.subject or "\n" in message.greeting or "\r" in message.greeting:
        raise PersonalizationValidationError("header injection")
    if not message.cta:
        raise PersonalizationValidationError("CTA is required")
    rendered = f"{message.subject}\n{message.greeting}\n{message.body}\n{message.cta}"
    if _EMAIL.search(rendered) or _URL.search(rendered):
        raise PersonalizationValidationError("rendered copy contains prohibited contact data or URL")
    if expected is None and all(
        value is not None for value in (awardee, public_event_sentence, need_category)
    ):
        expected = render_catalog_message(
            language=message.language,
            awardee=awardee,
            public_event_sentence=public_event_sentence,
            need_category=need_category,
            first_name=first_name,
        )
    if expected is not None and message != expected:
        raise PersonalizationValidationError("rendered copy differs from frozen catalog")
