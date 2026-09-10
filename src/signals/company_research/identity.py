"""Shared deterministic normalization for SIRENE-to-web/Apollo identity matching."""

from __future__ import annotations

import re
import unicodedata

_LEGAL_FORMS = frozenset({"sa", "sarl", "sas", "sasu", "eurl", "snc", "sca", "scs"})
_NAME_STOP_WORDS = frozenset(
    {"a", "au", "aux", "d", "de", "des", "du", "et", "l", "la", "le", "les"}
)


def ascii_text(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def significant_name_words(value: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9]+", ascii_text(value).casefold())
    return tuple(
        word for word in words if word not in _LEGAL_FORMS and word not in _NAME_STOP_WORDS
    )


def normalized_organization_name(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", ascii_text(value))
    without_legal_form = [word for word in words if word.casefold() not in _LEGAL_FORMS]
    return " ".join(without_legal_form).title()


def normalized_city(value: str) -> str:
    candidate = ascii_text(value).strip()
    candidate = re.sub(r"(?i)^ste(?=[\s-])", "Sainte", candidate)
    candidate = re.sub(r"(?i)^st(?=[\s-])", "Saint", candidate)
    candidate = re.sub(r"[^A-Za-z0-9'-]+", " ", candidate)
    return " ".join(candidate.split()).title()


__all__ = [
    "ascii_text",
    "normalized_city",
    "normalized_organization_name",
    "significant_name_words",
]
