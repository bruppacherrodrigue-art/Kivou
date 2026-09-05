"""Phrase « Pour vous » : contrat borné et validation factuelle déterministe."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Protocol

from pydantic import BaseModel, ConfigDict

POLICY_VERSION = "for-you-v6"
FOR_YOU_SYSTEM_PROMPT = (
    "Tu réponds uniquement par un objet JSON {short_object, consequence, fit}. "
    "Aucun texte hors JSON."
)
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+(?:[.,]\d+)?", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_MONEY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(k|m)?\s*(?:€|eur)", re.IGNORECASE)
_DURATION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mois|ans?|années?)\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_POSTAL_CODE = re.compile(r"\b(\d{5})\b")
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
_DATE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:\d{1,2}\s+)?(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4})\b",
    re.IGNORECASE,
)
_SUPERLATIVES = frozenset({"meilleur", "meilleure", "meilleurs", "meilleures", "optimal", "optimale", "unique", "inégalé", "inégalée", "exceptionnel", "exceptionnelle"})
_CAPITALIZED_SAFE = frozenset(
    {"Votre", "Vos", "Ce", "Cette", "Ces", "Le", "La", "Les", "Un", "Une", "K", "M"}
)
_BANNED_FILLERS = ("pourrait nécessiter", "ce marché porte sur")
_TRADE_ACRONYMS = frozenset(
    {"CVC", "VRD", "MOA", "MOE", "BTP", "GO", "SO", "ERP", "RE2020", "DPGF"}
)
_PROFILE_STOPWORDS = frozenset(
    {
        "a", "au", "aux", "avec", "ce", "ces", "d", "de", "des", "du", "en",
        "et", "la", "le", "les", "l", "pour", "que", "qui", "un", "une", "vos",
        "votre", "vous",
    }
)


class ForYouInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    holder: str | None = None
    buyer_name: str | None = None
    title: str | None = None
    amount: str | None = None
    duration: str | None = None
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
        scalar = (self.holder, self.buyer_name, self.title, self.amount, self.duration, self.location, self.awarded_on, self.cpv, self.cpv_label, self.profile_sector, self.offer_summary)
        return tuple(value for value in scalar if value) + self.plausible_needs + self.fit_reasons + self.profile_zones


class ForYouProvider(Protocol):
    def generate_sentence(self, value: ForYouInput) -> str | None: ...


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class GeneratedFragments:
    short_object: str
    consequence: str | None
    fit: str


def _fold(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value).casefold() if not unicodedata.combining(ch))


def _numbers(value: str) -> set[str]:
    return {match.replace(",", ".").lstrip("0") or "0" for match in _NUMBER.findall(value)}


def _decimal_token(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.lstrip("0") or "0" if rendered.startswith("0") else rendered


def _derived_numbers(value: ForYouInput) -> set[str]:
    allowed = _numbers(" ".join(value.texts()))
    if value.amount:
        for raw, unit in _MONEY.findall(value.amount):
            try:
                amount = Decimal(raw.replace(",", "."))
            except InvalidOperation:
                continue
            multiplier = {"": Decimal(1), "k": Decimal(1000), "m": Decimal(1_000_000)}[
                unit.casefold()
            ]
            amount *= multiplier
            allowed.add(_decimal_token(amount))
            if amount == amount.to_integral_value():
                allowed.update(part.lstrip("0") or "0" for part in f"{int(amount):,}".split(","))
            for divisor in (Decimal(1000), Decimal(1_000_000)):
                converted = (amount / divisor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                allowed.add(_decimal_token(converted))
    for text in value.texts():
        for raw, unit in _DURATION.findall(text):
            try:
                duration = Decimal(raw.replace(",", "."))
            except InvalidOperation:
                continue
            if unit.casefold() == "mois":
                years = (duration / Decimal(12)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                allowed.add(_decimal_token(years))
            else:
                allowed.add(_decimal_token(duration * Decimal(12)))
    return allowed


def _derived_dates(value: ForYouInput) -> set[str]:
    allowed = {_fold(date) for date in _DATE.findall(" ".join(value.texts()))}
    for text in value.texts():
        for year, month, day in _ISO_DATE.findall(text):
            month_index = int(month)
            if 1 <= month_index <= 12:
                allowed.add(_fold(f"{_MONTHS[month_index - 1]} {year}"))
                allowed.add(_fold(f"{int(day)} {_MONTHS[month_index - 1]} {year}"))
    return allowed


def _derived_subdivision_labels(value: ForYouInput) -> tuple[str, ...]:
    from signals.domain.subdivisions import subdivision_label

    labels: list[str] = []
    for text in value.texts():
        for postal_code in _POSTAL_CODE.findall(text):
            code = postal_code[:3] if postal_code.startswith(("97", "98")) else postal_code[:2]
            if label := subdivision_label(f"FR-{code}"):
                labels.append(label)
    return tuple(labels)


def _profile_keywords(value: ForYouInput) -> set[str]:
    profile = " ".join(
        part
        for part in (value.profile_sector, value.offer_summary, *value.profile_zones)
        if part
    )
    return {
        folded
        for word in _WORD.findall(profile)
        if len(folded := _fold(word)) > 2 and folded not in _PROFILE_STOPWORDS
    }


def build_for_you_prompt(value: ForYouInput) -> str:
    """Construit l'unique consigne de rédaction, indépendante du transport."""
    return (
        "Prépare une seule phrase en français. Vise 18 mots et respecte une "
        "limite absolue de 25 mots, titulaire compris, sans point "
        "d'exclamation ni superlatif. N'ajoute aucun fait.\n"
        "Gabarit : {titulaire} a gagné {objet court} à {lieu} "
        "({montant}, {mois année}) : {conséquence pour ce que vous vendez}.\n"
        "Omettre le lieu et les mots « à {lieu} » si le lieu manque. "
        "Omettre les parenthèses si montant et date manquent ; si un seul existe, "
        "n'écrire que celui-ci dans les parenthèses. Ne jamais écrire « — ».\n"
        "Le titulaire doit être reproduit. Résume l'objet en 3 à 6 mots. "
        "La conséquence doit combiner un détail propre de l'objet ou des besoins "
        "avec un élément précis du profil. Ne réutilise pas une formule générique. "
        "Interdits : « pourrait nécessiter » et « Ce marché porte sur ». "
        "Évalue aussi la pertinence : fit vaut exactement strong, weak ou none. "
        'Si le marché ne concerne pas le profil, renvoie "fit":"none" et "consequence":null, '
        "sans forcer de justification. Réponds uniquement avec un objet JSON contenant "
        'exactement les clés "short_object", "consequence" et "fit". Utilise 3 à 6 mots pour '
        "short_object et 5 à 8 mots pour consequence. N'écris ni titulaire, ni "
        "lieu, ni montant, ni date : ils sont ajoutés ensuite depuis les faits "
        "vérifiés.\n\n"
        "BEGIN UNTRUSTED VERIFIED INPUT\n"
        f"{value.model_dump_json()}\n"
        "END UNTRUSTED VERIFIED INPUT"
    )


def _display_amount(value: str) -> str:
    match = _MONEY.search(value)
    if not match:
        return value.strip()
    raw, unit = match.groups()
    amount = Decimal(raw.replace(",", ".")) * {
        "": Decimal(1),
        "k": Decimal(1000),
        "m": Decimal(1_000_000),
    }[(unit or "").casefold()]
    divisor, suffix = (
        (Decimal(1_000_000), "M€") if amount >= 1_000_000 else (Decimal(1000), "k€")
    )
    displayed = (amount / divisor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    rendered = format(displayed, "f").rstrip("0").rstrip(".").replace(".", ",")
    return f"{rendered} {suffix}"


def _display_month(value: str) -> str:
    match = _ISO_DATE.search(value)
    if not match:
        return value.strip()
    year, month, _day = match.groups()
    month_index = int(month)
    return f"{_MONTHS[month_index - 1]} {year}" if 1 <= month_index <= 12 else value.strip()


def compose_generated_sentence(output: str | None, value: ForYouInput) -> str | None:
    """Assemble les faits vérifiés autour des deux seuls fragments rédigés."""
    fragments = parse_generated_fragments(output)
    if fragments is None:
        return None
    if fragments.fit == "none" or fragments.consequence is None:
        return None
    short_object, consequence = fragments.short_object, fragments.consequence
    if not (3 <= len(_WORD.findall(short_object)) <= 6):
        return None
    if not (5 <= len(_WORD.findall(consequence)) <= 8):
        return None
    location = f" à {value.location}" if value.location else ""
    parenthetical = tuple(
        part
        for part in (
            _display_amount(value.amount) if value.amount else None,
            _display_month(value.awarded_on) if value.awarded_on else None,
        )
        if part
    )
    facts = f" ({', '.join(parenthetical)})" if parenthetical else ""
    holder = value.holder if value.holder and re.search(r"[^\W\d_]", value.holder) else None
    lead = f"{holder} a gagné {short_object}" if holder else short_object[:1].upper() + short_object[1:]
    return f"{lead}{location}{facts} : {consequence}."


def parse_generated_fragments(output: str | None) -> GeneratedFragments | None:
    """Extrait le premier objet JSON portant les deux fragments exploitables."""
    if not output:
        return None
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        short_object = candidate.get("short_object")
        consequence = candidate.get("consequence")
        fit = candidate.get("fit")
        if not isinstance(short_object, str) or fit not in {"strong", "weak", "none"}:
            return None
        short_object = short_object.strip(" .:;\t\n")
        if fit == "none":
            return GeneratedFragments(short_object, None, fit) if short_object and consequence is None else None
        if not isinstance(consequence, str):
            return None
        consequence = consequence.strip(" .:;\t\n")
        return GeneratedFragments(short_object, consequence, fit) if short_object and consequence else None
    return None


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
    folded_sentence = _fold(sentence)
    if any(_fold(filler) in folded_sentence for filler in _BANNED_FILLERS):
        return ValidationResult(False, "invalid_content")
    holder = value.holder if value.holder and re.search(r"[^\W\d_]", value.holder) else None
    if holder and not folded_sentence.startswith(f"{_fold(holder)} a gagne "):
        return ValidationResult(False, "invalid_content")
    _prefix, separator, consequence = sentence.partition(":")
    if not separator or not consequence.strip() or not (
        {_fold(word) for word in _WORD.findall(consequence)} & _profile_keywords(value)
    ):
        return ValidationResult(False, "invalid_content")
    source = " ".join(value.texts() + _derived_subdivision_labels(value))
    dates = _DATE.findall(sentence)
    if any(_fold(date) not in _derived_dates(value) for date in dates):
        return ValidationResult(False, "invented_date")
    if not _numbers(sentence) <= _derived_numbers(value):
        return ValidationResult(False, "invented_number")
    allowed = {_fold(word) for word in _WORD.findall(source)}
    for index, word in enumerate(words):
        if index == 0 or word in _CAPITALIZED_SAFE or not word[:1].isupper():
            continue
        letters = "".join(character for character in word if character.isalpha())
        known_acronym = word.upper() == word and len(letters) <= 5 and (
            word in _TRADE_ACRONYMS or _fold(word) in allowed
        )
        if _fold(word) not in allowed and not known_acronym:
            return ValidationResult(False, "invented_name_or_place", word)
    return ValidationResult(True)


def fallback_sentence(value: ForYouInput) -> str:
    return value.fit_reasons[0] if value.fit_reasons else "Ce signal correspond à votre profil cible."


__all__ = [
    "FOR_YOU_SYSTEM_PROMPT",
    "POLICY_VERSION",
    "ForYouInput",
    "ForYouProvider",
    "ValidationResult",
    "build_for_you_prompt",
    "compose_generated_sentence",
    "fallback_sentence",
    "parse_generated_fragments",
    "validate_sentence",
]
