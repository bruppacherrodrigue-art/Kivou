"""Phrase « Pour vous » : contrat borné et validation factuelle déterministe."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict

POLICY_VERSION = "for-you-v1"
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+(?:[.,]\d+)?", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_DATE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4})\b",
    re.IGNORECASE,
)
_SUPERLATIVES = frozenset({"meilleur", "meilleure", "meilleurs", "meilleures", "optimal", "optimale", "unique", "inégalé", "inégalée", "exceptionnel", "exceptionnelle"})
_CAPITALIZED_SAFE = frozenset({"Votre", "Vos", "Ce", "Cette", "Ces", "Le", "La", "Les", "Un", "Une"})


class ForYouInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    holder: str | None = None
    title: str | None = None
    amount: str | None = None
    location: str | None = None
    awarded_on: str | None = None
    cpv: str | None = None
    cpv_label: str | None = None
    plausible_needs: tuple[str, ...] = ()
    fit_reasons: tuple[str, ...] = ()
    profile_sector: str | None = None
    profile_zones: tuple[str, ...] = ()
    offer_summary: str = ""

    def texts(self) -> tuple[str, ...]:
        scalar = (self.holder, self.title, self.amount, self.location, self.awarded_on, self.cpv, self.cpv_label, self.profile_sector, self.offer_summary)
        return tuple(value for value in scalar if value) + self.plausible_needs + self.fit_reasons + self.profile_zones


class ForYouProvider(Protocol):
    def generate_sentence(self, value: ForYouInput) -> str | None: ...


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str | None = None
    detail: str | None = None


def _fold(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value).casefold() if not unicodedata.combining(ch))


def _numbers(value: str) -> set[str]:
    return {match.replace(",", ".").lstrip("0") or "0" for match in _NUMBER.findall(value)}


def validate_sentence(sentence: str | None, value: ForYouInput) -> ValidationResult:
    if sentence and "!" in sentence:
        return ValidationResult(False, "exclamation")
    if not sentence or "\n" in sentence or not sentence.strip().endswith((".", "?")):
        return ValidationResult(False, "invalid_shape")
    sentence = " ".join(sentence.split())
    words = _WORD.findall(sentence)
    if len(words) > 25:
        return ValidationResult(False, "too_many_words")
    folded_words = {_fold(word) for word in words}
    if folded_words & {_fold(word) for word in _SUPERLATIVES}:
        return ValidationResult(False, "superlative")
    source = " ".join(value.texts())
    dates = _DATE.findall(sentence)
    if any(_fold(date) not in _fold(source) for date in dates):
        return ValidationResult(False, "invented_date")
    if not _numbers(sentence) <= _numbers(source):
        return ValidationResult(False, "invented_number")
    allowed = {_fold(word) for word in _WORD.findall(source)}
    for index, word in enumerate(words):
        if index == 0 or word in _CAPITALIZED_SAFE or not word[:1].isupper():
            continue
        if _fold(word) not in allowed:
            return ValidationResult(False, "invented_name_or_place", word)
    return ValidationResult(True)


def fallback_sentence(value: ForYouInput) -> str:
    return value.fit_reasons[0] if value.fit_reasons else "Ce signal correspond à votre profil cible."


__all__ = [
    "POLICY_VERSION",
    "ForYouInput",
    "ForYouProvider",
    "ValidationResult",
    "fallback_sentence",
    "validate_sentence",
]
