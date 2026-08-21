"""Integrity validation for deterministic personalization artifacts."""

from __future__ import annotations

import re

from signals.personalization.catalog import SUPPORTED_LANGUAGES, CatalogMessage

MAX_SUBJECT_LENGTH = 90
MAX_GREETING_LENGTH = 80
MAX_BODY_LENGTH = 700

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


class PersonalizationValidationError(ValueError):
    """A purported artifact falls outside the frozen v1 contract."""


def safe_first_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        return None
    if any(char in normalized for char in "\r\n\x00"):
        return None
    if any(ord(char) < 32 for char in normalized):
        return None
    return normalized


def validate_catalog_message(message: CatalogMessage) -> None:
    if message.language not in SUPPORTED_LANGUAGES:
        raise PersonalizationValidationError("unsupported language")
    if not message.subject or len(message.subject) > MAX_SUBJECT_LENGTH:
        raise PersonalizationValidationError("subject is empty or overlong")
    if not message.greeting or len(message.greeting) > MAX_GREETING_LENGTH:
        raise PersonalizationValidationError("greeting is empty or overlong")
    if not message.body or len(message.body) > MAX_BODY_LENGTH:
        raise PersonalizationValidationError("body is empty or overlong")
    if len(message.body.split("\n\n")) > 2:
        raise PersonalizationValidationError("too many body paragraphs")
    if not message.cta:
        raise PersonalizationValidationError("CTA is required")
    rendered = f"{message.subject}\n{message.greeting}\n{message.body}\n{message.cta}"
    if _EMAIL.search(rendered) or _URL.search(rendered):
        raise PersonalizationValidationError("rendered copy contains prohibited contact data or URL")
