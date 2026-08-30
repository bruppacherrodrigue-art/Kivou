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
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import cast

from pydantic import ValidationError

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationInput,
    PresentationVariant,
    SourceTable,
    source_field_ref,
)
from signals.card_intelligence.fallback import factual_fallback

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

_IDENTIFIER_DATE_CONTEXT = re.compile(
    r"\b(?:(?:reference|ref|identifier|id|numero|number)"
    r"(?:\s+(?:projet|project|cpv|lot))?|"
    r"cpv|lot|code\s+postal|postcode)\b"
)

_BUYER_ASSERTION = re.compile(
    r"\b(?:(?:acheteur(?:s)?|acheteuse(?:s)?)(?:\s+publie(?:e|es|s)?)?|"
    r"(?:published\s+)?buyers?|buying\s+authority|contracting\s+authority|purchaser)"
    r"\s*[:\-]"
)
_AWARDEE_ASSERTION = re.compile(
    r"\b(?:entreprise(?:s)?\s+attributaire(?:s)?(?:\s+publie(?:e|es|s)?)?|"
    r"attributaire(?:s)?(?:\s+publie(?:e|es|s)?)?|titulaire|adjudicataire|"
    r"(?:published\s+)?awardees?|awarded\s+compan(?:y|ies)|"
    r"successful\s+tenderer|contractor|winner)\s*[:\-]"
)

_AMOUNT_AFTER = re.compile(
    r"(?<![\w-])(?P<amount>\d[\d\s\u00a0'’]*(?:[.,]\d+)?)\s*"
    r"(?P<currency>[A-Z]{3})(?![A-Z])",
    re.IGNORECASE,
)
_AMOUNT_BEFORE = re.compile(
    r"(?<![A-Z])(?P<currency>[A-Z]{3})\s*"
    r"(?P<amount>\d[\d\s\u00a0'’]*(?:[.,]\d+)?)(?![\w-])",
    re.IGNORECASE,
)
_AMOUNT_CONTEXT = re.compile(r"\b(?:montant|amount|valeur|value|prix|price)\b", re.IGNORECASE)
_LABELED_AMOUNT_WITHOUT_CURRENCY = re.compile(
    r"\b(?:montant|amount|valeur|value|prix|price)(?:\s+publie(?:e|es|s)?|\s+published)?"
    r"\s*[:\-]\s*(?P<amount>\d(?:[\d\s\u00a0'’]*\d)?(?:[.,]\d+)?)"
    r"(?!\d)(?!\s*[a-z]{3}\b)"
)
_LOCATION_ASSERTION = re.compile(
    r"\b(?:(?:lieu\s+d[' ]execution|location)(?:\s+publie(?:e|es|s)?)?|"
    r"(?:published\s+)?place\s+of\s+performance)\s*[:\-]"
)

_URGENCY = re.compile(
    r"\b(?:urgent|urgente|urgents|urgentes|urgence|immediat(?:e|es|s|ement)|"
    r"sans\s+delai|en\s+priorite|prioritaire|priorite|au\s+plus\s+vite|"
    r"des\s+que\s+possible|asap|emergency|immediate(?:ly)?|time\s+critical|"
    r"high\s+priority|priority|right\s+away)\b"
)
_CERTAINTY = re.compile(
    r"\b(?:garanti(?:e|es|s)?|garantit|achat\s+certain|besoin\s+confirme|"
    r"demande\s+certaine|vente\s+certaine|succes\s+assure|conversion\s+assuree?|"
    r"est\s+assuree?|is\s+assured|sans\s+aucun\s+doute|inevitable|"
    r"va\s+(?:acheter|recruter|embaucher)|"
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
_NORMALIZED_NAMED_CONTACT = re.compile(
    r"\b(?:contact|contactez|contacter|joindre|appelez|appeler|call|email|reach)"
    r"\s+(?:out\s+to\s+|directement\s+)?(?P<name>[a-z][\w'-]+\s+[a-z][\w'-]+)\b"
)
_CONTACT_VERBS = r"(?:contact|contactez|contacter|joindre|appelez|appeler|call|email|reach)"
_TITLE_CASE_NAME = re.compile(
    r"\b(?P<name>[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ][\wÀ-ÖØ-öø-ÿ'-]*\s+"
    r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ][\wÀ-ÖØ-öø-ÿ'-]*)\b"
)
_FUNCTIONAL_LABELS_BY_ROLE = {
    "PROCUREMENT_MANAGER": {
        "procurement manager",
        "responsable achats",
        "responsable des achats",
        "directeur des achats",
        "fonction achats",
    },
    "SITE_PROCUREMENT_MANAGER": {
        "site procurement manager",
        "responsable achats site",
    },
    "PROJECT_MANAGER": {"project manager", "chef de projet"},
    "WORKS_MANAGER": {"works manager", "conducteur de travaux"},
    "SUPPLY_MANAGER": {"supply manager", "responsable approvisionnements"},
}
_FUNCTIONAL_CONTACT_LABELS = frozenset(
    label for labels in _FUNCTIONAL_LABELS_BY_ROLE.values() for label in labels
)


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


def _source_ref(
    source: PresentationInput,
    *,
    table: str,
    column: str,
) -> str:
    binding = (
        source.facts.source_award_binding
        if table == "contract_award"
        else source.facts.source_event_binding
    )
    return source_field_ref(
        table=cast(SourceTable, table),
        binding=binding,
        column=column,
    )


def _decimal_amount(raw: str) -> Decimal | None:
    compact = re.sub(r"[\s\u00a0'’]", "", raw)
    if not compact:
        return None
    if "," in compact and "." in compact:
        decimal_separator = "," if compact.rfind(",") > compact.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        compact = compact.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in compact or "." in compact:
        separator = "," if "," in compact else "."
        groups = compact.split(separator)
        grouped_thousands = (
            len(groups) > 2 and all(len(group) == 3 for group in groups[1:])
        ) or (len(groups) == 2 and len(groups[1]) == 3 and len(groups[0]) <= 3)
        if grouped_thousands:
            compact = "".join(groups)
        else:
            compact = compact.replace(separator, ".")
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def _amount_mentions(
    text: str,
    *,
    source_currency: str | None,
) -> tuple[tuple[Decimal | None, str], ...]:
    def is_amount_context(match: re.Match[str]) -> bool:
        currency = match.group("currency").upper()
        return currency == source_currency or bool(
            _AMOUNT_CONTEXT.search(text[max(0, match.start() - 48) : match.start()])
        )

    after = tuple(match for match in _AMOUNT_AFTER.finditer(text) if is_amount_context(match))
    before = tuple(
        match
        for match in _AMOUNT_BEFORE.finditer(text)
        if is_amount_context(match)
    )
    matches = (*after, *before)
    return tuple(
        (_decimal_amount(match.group("amount")), match.group("currency").upper())
        for match in matches
    )


def _claim_evidence_errors(
    payload: CardPresentationPayload,
    source: PresentationInput,
) -> set[str]:
    errors: set[str] = set()
    typed_refs = {
        "awardee": _source_ref(
            source,
            table="contract_award",
            column="awardee_parties",
        ),
        "buyer": _source_ref(
            source,
            table="source_event",
            column="procedure_buyers",
        ),
        "amount": _source_ref(source, table="contract_award", column="amount"),
        "currency": _source_ref(source, table="contract_award", column="currency"),
        "location": _source_ref(
            source,
            table="contract_award",
            column="place_of_performance",
        ),
        "award": _source_ref(source, table="contract_award", column="award_date"),
        "notification": _source_ref(
            source,
            table="contract_award",
            column="contract_notification_date",
        ),
        "publication": _source_ref(source, table="source_event", column="published_on"),
    }
    buyer_labels = tuple(_normalize(actor.display_name) for actor in source.facts.buyers)
    awardee_labels = tuple(_normalize(actor.display_name) for actor in source.facts.awardees)
    location = _normalize(source.facts.location) if source.facts.location else None

    for claim in payload.claims:
        normalized = _normalize(claim.text)
        required: set[str] = set()
        if any(_contains_phrase(normalized, actor) for actor in buyer_labels):
            required.add(typed_refs["buyer"])
        if any(_contains_phrase(normalized, actor) for actor in awardee_labels):
            required.add(typed_refs["awardee"])
        if location and _contains_phrase(normalized, location):
            required.add(typed_refs["location"])

        amount_mentions = _amount_mentions(
            claim.text,
            source_currency=source.facts.currency,
        )
        if amount_mentions:
            required.update((typed_refs["amount"], typed_refs["currency"]))
            if source.facts.amount is None or source.facts.currency is None:
                errors.add("amount_value_unbound")
            elif any(
                amount is None
                or amount != source.facts.amount
                or currency != source.facts.currency
                for amount, currency in amount_mentions
            ):
                errors.add("amount_value_mismatch")

        folded_claim = _normalize_date_text(claim.text)
        amount_without_currency = (
            ()
            if amount_mentions
            else tuple(_LABELED_AMOUNT_WITHOUT_CURRENCY.finditer(folded_claim))
        )
        if amount_without_currency:
            required.update((typed_refs["amount"], typed_refs["currency"]))
            errors.add("amount_currency_unbound")
            if source.facts.amount is None or any(
                _decimal_amount(match.group("amount")) != source.facts.amount
                for match in amount_without_currency
            ):
                errors.add("amount_value_mismatch")

        for assertion in _LOCATION_ASSERTION.finditer(folded_claim):
            required.add(typed_refs["location"])
            if location is None:
                errors.add("location_value_unbound")
            elif re.match(
                _phrase_pattern(location),
                _normalize(folded_claim[assertion.end() :]),
            ) is None:
                errors.add("location_value_mismatch")

        date_text = folded_claim
        for mention in _extract_dates(date_text):
            if _is_identifier_date(date_text, mention):
                continue
            kind = _date_kind(date_text, mention)
            if kind is not None:
                required.add(typed_refs[kind])

        if not required <= set(claim.evidence_refs):
            errors.add("claim_evidence_mismatch")
    return errors


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
    errors.update(_claim_evidence_errors(payload, source))
    return errors


def _role_mentions(text: str, actor: str, labels: tuple[str, ...]) -> bool:
    labels_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    article = r"(?:l|le|la|les|un|une|the|a|an)"
    qualifiers = r"(?:\s+(?:publiee?s?|publies?|identified|identifiee?s?)){0,3}"
    label = rf"(?<!\w)(?:{labels_pattern})(?!\w)"
    copula = r"(?:est\s+identifiee?\s+comme|is\s+identified\s+as|est|is)"
    role_first = (
        rf"(?:{article}\s+)?{label}{qualifiers}(?:\s+{copula})?\s+"
        rf"{_phrase_pattern(actor)}"
    )
    actor_first = (
        rf"{_phrase_pattern(actor)}\s+{copula}\s+(?:{article}\s+)?{label}"
    )
    return re.search(role_first, text) is not None or re.search(actor_first, text) is not None


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


def _has_prefix_collision(raw_text: str, actor_labels: set[str]) -> bool:
    decomposed = unicodedata.normalize("NFKD", raw_text)
    folded = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).casefold()
    token_matches = tuple(re.finditer(r"\w+", folded, flags=re.UNICODE))
    token_values = tuple(match.group() for match in token_matches)
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
        common_words = tuple(common)
        for index in range(len(token_values) - len(common_words) + 1):
            if token_values[index : index + len(common_words)] != common_words:
                continue
            next_index = index + len(common_words)
            next_word = (
                token_values[next_index]
                if next_index < len(token_values)
                else None
            )
            if next_word in allowed_next:
                continue
            if prefix in actor_labels:
                if next_word is None:
                    continue
                separator = folded[
                    token_matches[next_index - 1].end() : token_matches[next_index].start()
                ]
                if next_word in {"and", "et"} or any(
                    marker in separator for marker in (";", ",", ".", "!", "?", "/", "&")
                ):
                    continue
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


def _labeled_actor_errors(
    raw_text: str,
    *,
    buyers: set[str],
    awardees: set[str],
) -> set[str]:
    folded = _normalize_date_text(raw_text)
    assertions = [
        *(("buyer", match) for match in _BUYER_ASSERTION.finditer(folded)),
        *(("awardee", match) for match in _AWARDEE_ASSERTION.finditer(folded)),
    ]
    assertions.sort(key=lambda item: item[1].start())
    errors: set[str] = set()
    for index, (role, match) in enumerate(assertions):
        end = assertions[index + 1][1].start() if index + 1 < len(assertions) else len(folded)
        expected = buyers if role == "buyer" else awardees
        raw_segment = folded[match.end() : end]
        segment = _normalize(raw_segment)
        for boundary in re.finditer(r"[.!?](?:\s+|$)", raw_segment):
            candidate = _normalize(raw_segment[: boundary.start()])
            if any(_contains_phrase(candidate, actor) for actor in expected):
                segment = candidate
                break
        matched = False
        remainder = segment
        for actor in sorted(expected, key=len, reverse=True):
            if _contains_phrase(remainder, actor):
                matched = True
                remainder = re.sub(_phrase_pattern(actor), " ", remainder)
        remainder_words = tuple(
            word
            for word in remainder.split()
            if word not in {"and", "et"}
        )
        if not matched or remainder_words:
            errors.add("actor_reference_unbound")
    return errors


def _validate_actor_roles(texts: tuple[str, ...], source: PresentationInput) -> set[str]:
    normalized_texts = tuple(_normalize(text) for text in texts)
    buyer_labels = {_normalize(actor.display_name) for actor in source.facts.buyers}
    awardee_labels = {_normalize(actor.display_name) for actor in source.facts.awardees}
    errors: set[str] = set()

    for text in texts:
        errors.update(
            _labeled_actor_errors(
                text,
                buyers=buyer_labels,
                awardees=awardee_labels,
            )
        )

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
        for text in texts
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
    markers = [
        (kind, match)
        for kind, pattern in _DATE_KIND_PATTERNS.items()
        for match in pattern.finditer(segment)
    ]
    if not markers:
        return None

    local_start = mention.start - start
    local_end = mention.end - start

    def distance(match: re.Match[str]) -> int:
        return _span_distance(local_start, local_end, match)

    closest_distance = min(distance(match) for _, match in markers)
    if closest_distance > 80:
        return None
    closest_kinds = {
        kind for kind, match in markers if distance(match) == closest_distance
    }
    return next(iter(closest_kinds)) if len(closest_kinds) == 1 else None


def _span_distance(start: int, end: int, match: re.Match[str]) -> int:
    if match.end() <= start:
        return start - match.end()
    if end <= match.start():
        return match.start() - end
    return 0


def _is_identifier_date(text: str, mention: _DateMention) -> bool:
    start, end = _sentence_bounds(text, mention)
    segment = text[start:end]
    local_start = mention.start - start
    local_end = mention.end - start
    identifier_matches = tuple(
        match
        for match in _IDENTIFIER_DATE_CONTEXT.finditer(segment)
        if match.end() <= local_start
    )
    if not identifier_matches:
        return False
    closest_identifier = min(
        identifier_matches,
        key=lambda match: _span_distance(local_start, local_end, match),
    )
    if _span_distance(local_start, local_end, closest_identifier) > 48:
        return False
    date_mentions = _extract_dates(segment)
    semantic_markers = tuple(
        match
        for pattern in _DATE_KIND_PATTERNS.values()
        for match in pattern.finditer(segment)
        if _span_distance(local_start, local_end, match) <= 80
    )
    for marker in semantic_markers:
        if marker.end() <= local_start:
            return False
        if marker.start() < local_end:
            continue
        if not any(date.start >= marker.end() for date in date_mentions):
            return False
    return True


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
            kind = _date_kind(text, mention)
            if _is_identifier_date(text, mention):
                continue
            if mention.value is None:
                errors.add("date_invalid")
                continue
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
    payload: CardPresentationPayload,
    texts: tuple[str, ...],
    source: PresentationInput,
) -> set[str]:
    errors: set[str] = set()
    actor_labels = {
        _normalize(actor.display_name)
        for actor in (*source.facts.buyers, *source.facts.awardees)
    }
    allowed_functional = {
        label
        for role in payload.target_roles
        for label in _FUNCTIONAL_LABELS_BY_ROLE[role.role.value]
    }
    for raw_text in texts:
        normalized = _mask_actor_labels(raw_text, source)
        contact_scan = _normalize(raw_text)
        for label in _FUNCTIONAL_CONTACT_LABELS - allowed_functional:
            if _contains_phrase(contact_scan, label):
                errors.add("target_role_unbound")
        allowed_contacts = actor_labels | allowed_functional
        for allowed in sorted(allowed_contacts, key=len, reverse=True):
            contact_scan = re.sub(
                rf"\b{_CONTACT_VERBS}\s+(?:(?:le|la|les|un|une|the|a)\s+)?"
                rf"{_phrase_pattern(allowed)}",
                " functional_contact ",
                contact_scan,
            )
        for actor in sorted(actor_labels, key=len, reverse=True):
            contact_scan = re.sub(_phrase_pattern(actor), " ", contact_scan)
        contact_scan = " ".join(contact_scan.split())
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
            if name not in allowed_functional and name not in actor_labels:
                errors.add("invented_person")
        for match in _NORMALIZED_NAMED_CONTACT.finditer(contact_scan):
            name = match.group("name")
            if name not in _FUNCTIONAL_CONTACT_LABELS:
                errors.add("invented_person")
        for match in _TITLE_CASE_NAME.finditer(raw_text):
            name = _normalize(match.group("name"))
            if name in allowed_functional:
                continue
            if any(_contains_phrase(actor, name) for actor in actor_labels):
                continue
            errors.add("invented_person")
    return errors


def _longest_common_token_run(
    title_tokens: tuple[str, ...],
    surface_tokens: tuple[str, ...],
) -> tuple[int, int, int]:
    previous = [(0, 0, 0)] * (len(surface_tokens) + 1)
    best = (0, 0, 0)
    for title_token in title_tokens:
        current = [(0, 0, 0)] * (len(surface_tokens) + 1)
        for index, surface_token in enumerate(surface_tokens, start=1):
            if title_token != surface_token:
                continue
            prior_count, prior_chars, prior_alpha = previous[index - 1]
            candidate = (
                prior_count + 1,
                prior_chars + len(title_token) + (1 if prior_count else 0),
                prior_alpha + int(title_token.isalpha() and len(title_token) >= 3),
            )
            current[index] = candidate
            if (candidate[1], candidate[0]) > (best[1], best[0]):
                best = candidate
        previous = current
    return best


def _is_substantial_title_copy(title: str, surface: str) -> bool:
    if _contains_phrase(surface, title):
        return True
    title_tokens = tuple(title.split())
    surface_tokens = tuple(surface.split())
    if not surface_tokens:
        return False
    token_count, character_count, alphabetic_count = _longest_common_token_run(
        title_tokens,
        surface_tokens,
    )
    return (
        token_count >= 10
        and alphabetic_count >= 8
        and character_count >= 80
        and character_count >= int(len(surface) * 0.55)
    )


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
        if any(_is_substantial_title_copy(title, _normalize(text)) for text in texts)
        else set()
    )


def validate_payload(
    payload: CardPresentationPayload,
    source: PresentationInput,
) -> ValidationResult:
    """Validate a candidate against its exact source without changing either.

    Recursive Pydantic revalidation closes instances forged with ``model_copy``.
    The exact deterministic fallback is authoritative and bypasses prose
    heuristics.  Semantic validators remain diagnostics for every FULL or
    non-canonical fallback candidate.
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

    canonical_fallback = factual_fallback(checked_source)
    if (
        checked_payload.variant is PresentationVariant.FACTUAL_FALLBACK
        and checked_payload == canonical_fallback
    ):
        return ValidationResult(())
    if checked_payload.variant is PresentationVariant.FULL:
        errors.add("full_variant_not_authorized")
    else:
        errors.add("factual_fallback_not_canonical")

    texts = _public_texts(checked_payload)
    errors.update(_validate_evidence(checked_payload, checked_source))
    errors.update(_validate_actor_roles(texts, checked_source))
    errors.update(_validate_dates(texts, checked_source))
    errors.update(_validate_fit(checked_payload, checked_source, texts))
    errors.update(_validate_certainty(checked_payload, texts, checked_source))
    errors.update(_validate_administrative_copy(texts, checked_source))
    return ValidationResult(tuple(sorted(errors)))
