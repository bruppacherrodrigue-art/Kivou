"""Deterministic, non-rewriting publication gates for card presentations.

The validators in this module inspect only the immutable presentation input and
candidate payload.  They do not repair prose, infer missing facts, or contact a
provider.  Each rule returns a stable error code so publication can fail closed
without exposing validation internals to a client surface.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from itertools import combinations

from pydantic import ValidationError

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationInput,
    PresentationVariant,
)

_OFFER_TO_NEED = {
    "materials_and_components": "materials_or_components",
    "equipment_rental": "equipment_or_rental",
    "staffing_and_labour": "workforce_capacity",
    "transport_and_logistics": "logistics_and_transport",
    "specialist_subcontracting": "specialist_subcontracting",
    "safety_equipment": "safety_and_ppe",
    "waste_and_environmental_services": "waste_and_environment",
}

_NEED_TERMS = {
    "materials_or_components": (
        "materiau",
        "materiaux",
        "material",
        "materials",
        "composant",
        "composants",
        "component",
        "components",
        "fourniture",
        "fournitures",
        "intrant",
        "intrants",
    ),
    "workforce_capacity": (
        "personnel",
        "main d oeuvre",
        "effectif",
        "effectifs",
        "employe",
        "employes",
        "recrutement",
        "recruter",
        "embaucher",
        "staff",
        "staffing",
        "workforce",
        "labour",
        "labor",
        "employee",
        "employees",
        "recruitment",
        "recruit",
        "hiring",
        "hire",
    ),
    "equipment_or_rental": (
        "equipement",
        "equipements",
        "equipment",
        "location de materiel",
        "location d equipement",
        "equipment rental",
        "rental",
        "louer",
    ),
    "logistics_and_transport": (
        "logistique",
        "logistics",
        "transport",
    ),
    "specialist_subcontracting": (
        "sous traitance",
        "sous traitant",
        "subcontracting",
        "subcontractor",
        "specialiste",
        "specialist",
    ),
    "safety_and_ppe": (
        "securite",
        "protection individuelle",
        "epi",
        "safety",
        "ppe",
    ),
    "waste_and_environment": (
        "dechet",
        "dechets",
        "environnement",
        "waste",
        "environmental",
        "environment",
    ),
}

_BUYER_LABELS = (
    "acheteur",
    "acheteuse",
    "acheteurs",
    "acheteuses",
    "pouvoir adjudicateur",
    "entite adjudicatrice",
    "buyer",
    "buyers",
    "buying authority",
    "contracting authority",
    "purchaser",
)
_AWARDEE_LABELS = (
    "entreprise attributaire",
    "entreprises attributaires",
    "attributaire",
    "attributaires",
    "titulaire",
    "adjudicataire",
    "awarded company",
    "awarded companies",
    "awardee",
    "awardees",
    "successful tenderer",
    "contractor",
    "winner",
)

_MONTHS = {
    "janvier": 1,
    "january": 1,
    "fevrier": 2,
    "february": 2,
    "mars": 3,
    "march": 3,
    "avril": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "june": 6,
    "juillet": 7,
    "july": 7,
    "aout": 8,
    "august": 8,
    "septembre": 9,
    "september": 9,
    "octobre": 10,
    "october": 10,
    "novembre": 11,
    "november": 11,
    "decembre": 12,
    "december": 12,
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_PATTERNS = (
    (
        "iso",
        re.compile(r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)"),
    ),
    (
        "numeric",
        re.compile(
            r"(?<!\d)(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-]"
            r"(?P<year>\d{2}|\d{4})(?!\d)"
        ),
    ),
    (
        "day-month",
        re.compile(
            rf"(?<!\d)(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_PATTERN})\s+"
            r"(?P<year>\d{2}|\d{4})(?!\d)"
        ),
    ),
    (
        "month-day",
        re.compile(
            rf"\b(?P<month>{_MONTH_PATTERN})\s+(?P<day>\d{{1,2}})"
            r"(?:st|nd|rd|th)?\s*,?\s*(?P<year>\d{2}|\d{4})(?!\d)"
        ),
    ),
)

_DATE_KIND_PATTERNS = {
    "notification": re.compile(
        r"\b(?:date\s+de\s+notification(?:\s+du\s+contrat)?|notification\s+date|"
        r"contract\s+notification\s+date|notifie(?:e|es|s)?\s+le|notified\s+on)\b"
    ),
    "publication": re.compile(
        r"\b(?:date\s+de\s+publication|publication\s+date|published\s+on)\b"
    ),
    "award": re.compile(
        r"\b(?:date\s+d\s+attribution|date\s+attribution|attribution|"
        r"attribue(?:e|es|s)?(?:\s+le)?|award\s+date|awarded\s+on|contract\s+award)\b"
    ),
}

_URGENCY = re.compile(
    r"\b(?:urgent|urgente|urgents|urgentes|urgence|immediatement|sans\s+delai|"
    r"asap|emergency|immediately|time\s+critical)\b"
)
_CERTAINTY = re.compile(
    r"\b(?:garanti(?:e|es|s)?|garantit|achat\s+certain|besoin\s+confirme|"
    r"demande\s+certaine|sans\s+aucun\s+doute|va\s+(?:acheter|recruter|embaucher)|"
    r"guaranteed|definitely|certain\s+(?:demand|opportunity)|"
    r"will\s+(?:definitely|buy|hire|purchase|need)|must\s+(?:buy|hire|purchase))\b"
)
_HONORIFIC = re.compile(
    r"\b(?:mme|madame|monsieur|mr|mrs|ms|dr|docteur)\s+[a-z][\w'-]*\b"
)
_RAW_M_HONORIFIC = re.compile(r"\bM\.\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]*\b")
_NAMED_CONTACT = re.compile(
    r"\b(?:Contact|Contactez|Contacter|Joindre|Appelez|Call|Email|Reach(?:\s+out\s+to)?)"
    r"\s+(?:directement\s+)?(?P<name>[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]+\s+"
    r"[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]+)\b"
)
_FUNCTIONAL_CONTACT_LABELS = {
    "procurement manager",
    "site procurement manager",
    "project manager",
    "works manager",
    "supply manager",
    "responsable achats",
    "fonction achats",
}


@dataclass(frozen=True)
class ValidationResult:
    """Sorted, de-duplicated publication refusal codes."""

    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class _DateMention:
    value: dt.date | None
    start: int
    end: int


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(character for character in decomposed if not unicodedata.combining(character))
    words = re.sub(r"[^\w]+", " ", unaccented.casefold(), flags=re.UNICODE)
    return " ".join(words.split())


def _normalize_date_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(unaccented.casefold().replace("’", "'").split())


def _phrase_pattern(phrase: str) -> str:
    return rf"(?<!\w){re.escape(phrase)}(?!\w)"


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(_phrase_pattern(phrase), text) is not None


def _public_texts(payload: CardPresentationPayload) -> tuple[str, ...]:
    values = (
        payload.headline,
        payload.award_summary,
        payload.commercial_importance,
        payload.fit_reason,
        payload.timing,
        payload.recommended_action,
        *(claim.text for claim in payload.claims),
        *(role.rationale for role in payload.target_roles),
        *(unknown.text for unknown in payload.unknowns),
    )
    return tuple(dict.fromkeys(value for value in values if value))


def _validate_evidence(
    payload: CardPresentationPayload,
    source: PresentationInput,
) -> set[str]:
    errors: set[str] = set()
    references = (
        *(reference for claim in payload.claims for reference in claim.evidence_refs),
        *(reference for role in payload.target_roles for reference in role.evidence_refs),
        *(reference for unknown in payload.unknowns for reference in unknown.evidence_refs),
    )
    catalog = source.facts.evidence_catalog
    if any(reference not in catalog for reference in references):
        errors.add("evidence_ref_unknown")
    if any(not reference.startswith("source-field:v1:") for reference in references):
        errors.add("evidence_ref_not_direct")
    return errors


def _role_mentions(text: str, actor: str, labels: tuple[str, ...]) -> bool:
    labels_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    qualifiers = r"(?:\s+(?:publiee?s?|publies?|identified|identifiee?s?)){0,3}"
    before = rf"(?:{labels_pattern}){qualifiers}\s+{_phrase_pattern(actor)}"
    copula = r"(?:est|is|est\s+identifiee?\s+comme|is\s+identified\s+as)"
    after = rf"{_phrase_pattern(actor)}\s+{copula}\s+(?:{labels_pattern})\b"
    return re.search(before, text) is not None or re.search(after, text) is not None


def _acts_as_awarder(text: str, actor: str) -> bool:
    return (
        re.search(
            rf"{_phrase_pattern(actor)}\s+(?:a\s+)?(?:attribuee?s?|awarded|awards)\b",
            text,
        )
        is not None
    )


def _is_award_recipient(text: str, actor: str) -> bool:
    return (
        re.search(
            rf"\b(?:attribuee?s?|awarded)\b(?:\s+\w+){{0,6}}\s+(?:a|to)\s+"
            rf"{_phrase_pattern(actor)}",
            text,
        )
        is not None
    )


def _has_prefix_collision(text: str, actor_labels: set[str]) -> bool:
    for left, right in combinations(sorted(actor_labels), 2):
        left_words = left.split()
        right_words = right.split()
        common: list[str] = []
        for left_word, right_word in zip(left_words, right_words, strict=False):
            if left_word != right_word:
                break
            common.append(left_word)
        if len(common) < 2 or len(" ".join(common)) < 8:
            continue

        prefix = " ".join(common)
        allowed_next = {
            words[len(common)]
            for words in (left_words, right_words)
            if len(words) > len(common)
        }
        for match in re.finditer(_phrase_pattern(prefix), text):
            remainder = text[match.end() :].lstrip()
            next_word_match = re.match(r"(?P<word>\w+)", remainder)
            next_word = next_word_match.group("word") if next_word_match else None
            if next_word not in allowed_next:
                return True
    return False


def _has_truncated_actor_reference(raw_text: str, actor_labels: set[str]) -> bool:
    for ellipsis in re.finditer(r"\.\.\.|…", raw_text):
        prefix_text = _normalize(raw_text[: ellipsis.start()])
        for actor in actor_labels:
            words = actor.split()
            for length in range(2, len(words)):
                prefix = " ".join(words[:length])
                if len(prefix) >= 8 and prefix_text.endswith(prefix):
                    return True
    return False


def _validate_actor_roles(texts: tuple[str, ...], source: PresentationInput) -> set[str]:
    normalized_texts = tuple(_normalize(text) for text in texts)
    buyer_labels = {_normalize(actor.display_name) for actor in source.facts.buyers}
    awardee_labels = {_normalize(actor.display_name) for actor in source.facts.awardees}
    errors: set[str] = set()

    for label in buyer_labels & awardee_labels:
        if any(_contains_phrase(text, label) for text in normalized_texts):
            errors.add("actor_role_ambiguous")

    if any(
        _has_truncated_actor_reference(text, buyer_labels | awardee_labels)
        for text in texts
    ):
        errors.add("actor_reference_ambiguous")

    if any(
        _has_prefix_collision(text, buyer_labels | awardee_labels)
        for text in normalized_texts
    ):
        errors.add("actor_reference_ambiguous")

    for text in normalized_texts:
        for actor in buyer_labels:
            if not _contains_phrase(text, actor):
                continue
            if _role_mentions(text, actor, _AWARDEE_LABELS) or _is_award_recipient(text, actor):
                errors.add("actor_role_inversion")
        for actor in awardee_labels:
            if not _contains_phrase(text, actor):
                continue
            if _role_mentions(text, actor, _BUYER_LABELS) or _acts_as_awarder(text, actor):
                errors.add("actor_role_inversion")
    return errors


def _two_or_four_digit_year(raw: str) -> int:
    year = int(raw)
    if len(raw) == 4:
        return year
    return 2000 + year if year <= 68 else 1900 + year


def _extract_dates(text: str) -> tuple[_DateMention, ...]:
    mentions: list[_DateMention] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            occupied.append(match.span())
            month_raw = match.group("month")
            month = _MONTHS[month_raw] if kind in {"day-month", "month-day"} else int(month_raw)
            try:
                value = dt.date(
                    _two_or_four_digit_year(match.group("year")),
                    month,
                    int(match.group("day")),
                )
            except ValueError:
                value = None
            mentions.append(_DateMention(value=value, start=match.start(), end=match.end()))
    return tuple(sorted(mentions, key=lambda mention: mention.start))


def _sentence_bounds(text: str, mention: _DateMention) -> tuple[int, int]:
    previous = max((text.rfind(boundary, 0, mention.start) for boundary in ".;!?\n"), default=-1)
    following_candidates = [
        position
        for boundary in ".;!?\n"
        if (position := text.find(boundary, mention.end)) != -1
    ]
    following = min(following_candidates, default=len(text))
    return previous + 1, following


def _date_kind(text: str, mention: _DateMention) -> str | None:
    start, end = _sentence_bounds(text, mention)
    segment = text[start:end]
    kinds = {
        kind
        for kind, pattern in _DATE_KIND_PATTERNS.items()
        if pattern.search(segment) is not None
    }
    if len(kinds) == 1:
        return next(iter(kinds))
    return None


def _validate_dates(texts: tuple[str, ...], source: PresentationInput) -> set[str]:
    errors: set[str] = set()
    expected = {
        "award": source.facts.award_date,
        "notification": source.facts.contract_notification_date,
        "publication": source.facts.publication_date,
    }
    for raw_text in texts:
        text = _normalize_date_text(raw_text)
        for mention in _extract_dates(text):
            if mention.value is None:
                errors.add("date_invalid")
                continue
            kind = _date_kind(text, mention)
            if kind is None:
                errors.add("date_semantics_unbound")
                continue
            expected_date = expected[kind]
            if expected_date is None:
                errors.add(f"{kind}_date_unbound")
                continue
            if mention.value == expected_date:
                continue
            errors.add(f"{kind}_date_mismatch")
            for other_kind, other_date in expected.items():
                if other_kind != kind and mention.value == other_date:
                    errors.add(f"{other_kind}_as_{kind}_date")
    return errors


def _need_categories_in_text(text: str) -> set[str]:
    normalized = _normalize(text)
    return {
        category
        for category, terms in _NEED_TERMS.items()
        if any(_contains_phrase(normalized, term) for term in terms)
    }


def _mask_actor_labels(text: str, source: PresentationInput) -> str:
    masked = _normalize(text)
    labels = {
        _normalize(actor.display_name)
        for actor in (*source.facts.buyers, *source.facts.awardees)
    }
    for label in sorted(labels, key=len, reverse=True):
        masked = re.sub(_phrase_pattern(label), " ", masked)
    return " ".join(masked.split())


def _validate_fit(
    payload: CardPresentationPayload,
    source: PresentationInput,
    texts: tuple[str, ...],
) -> set[str]:
    errors: set[str] = set()
    fit_categories = set(payload.fit_need_categories)
    matched_categories = set(source.icp_matched_needs)
    if not fit_categories <= matched_categories:
        errors.add("fit_need_unmatched")

    captured_icp = source.target_icp_customer_input
    declared_categories = {
        _OFFER_TO_NEED[offer]
        for offer in (*captured_icp.offers, *captured_icp.secondary_offers)
    }
    if not matched_categories <= declared_categories:
        errors.add("icp_need_unbound")

    if payload.variant is PresentationVariant.FULL:
        commercial_texts = (
            payload.commercial_importance,
            payload.fit_reason,
            payload.recommended_action,
            *(role.rationale for role in payload.target_roles),
            *(
                claim.text
                for claim in payload.claims
                if claim.kind in {ClaimKind.INFERENCE, ClaimKind.RECOMMENDATION}
                and claim.text != payload.timing
            ),
        )
        for commercial_text in dict.fromkeys(commercial_texts):
            if commercial_text is None:
                continue
            mentioned = _need_categories_in_text(commercial_text)
            if not mentioned or not mentioned <= fit_categories:
                errors.add("commercial_claim_unbound_to_icp")

    if (
        "materials_or_components" in fit_categories
        and "workforce_capacity" not in fit_categories
        and any(
            _contains_phrase(_mask_actor_labels(text, source), term)
            for text in texts
            for term in _NEED_TERMS["workforce_capacity"]
        )
    ):
        errors.add("materials_staffing_mismatch")
    return errors


def _validate_certainty(
    texts: tuple[str, ...],
    source: PresentationInput,
) -> set[str]:
    errors: set[str] = set()
    actor_labels = {
        _normalize(actor.display_name)
        for actor in (*source.facts.buyers, *source.facts.awardees)
    }
    for raw_text in texts:
        normalized = _mask_actor_labels(raw_text, source)
        if _URGENCY.search(normalized):
            errors.add("unsupported_urgency")
        if _CERTAINTY.search(normalized):
            errors.add("unsupported_certainty")
        if _HONORIFIC.search(normalized):
            errors.add("invented_person")
        for match in _RAW_M_HONORIFIC.finditer(raw_text):
            if not any(_normalize(match.group()) in actor for actor in actor_labels):
                errors.add("invented_person")
        for match in _NAMED_CONTACT.finditer(raw_text):
            name = _normalize(match.group("name"))
            if name not in _FUNCTIONAL_CONTACT_LABELS and name not in actor_labels:
                errors.add("invented_person")
    return errors


def _validate_administrative_copy(
    texts: tuple[str, ...],
    source: PresentationInput,
) -> set[str]:
    if source.facts.award_title is None:
        return set()
    title = _normalize(source.facts.award_title)
    if len(title) < 5 or not any(character.isalpha() for character in title):
        return set()
    return (
        {"administrative_title_reused"}
        if any(_contains_phrase(_normalize(text), title) for text in texts)
        else set()
    )


def validate_payload(
    payload: CardPresentationPayload,
    source: PresentationInput,
) -> ValidationResult:
    """Validate a candidate against its exact source without changing either.

    Recursive Pydantic revalidation closes instances forged with ``model_copy``.
    Semantic validators run only on fully valid contracts, but both contract
    errors are collected before returning a stable, sorted result.
    """

    errors: set[str] = set()
    try:
        checked_payload = CardPresentationPayload.model_validate(payload)
    except (ValidationError, TypeError, ValueError, AttributeError):
        checked_payload = None
        errors.add("payload_contract_invalid")
    try:
        checked_source = PresentationInput.model_validate(source)
    except (ValidationError, TypeError, ValueError, AttributeError):
        checked_source = None
        errors.add("source_contract_invalid")

    if checked_payload is None or checked_source is None:
        return ValidationResult(tuple(sorted(errors)))

    texts = _public_texts(checked_payload)
    errors.update(_validate_evidence(checked_payload, checked_source))
    errors.update(_validate_actor_roles(texts, checked_source))
    errors.update(_validate_dates(texts, checked_source))
    errors.update(_validate_fit(checked_payload, checked_source, texts))
    errors.update(_validate_certainty(texts, checked_source))
    errors.update(_validate_administrative_copy(texts, checked_source))
    return ValidationResult(tuple(sorted(errors)))
