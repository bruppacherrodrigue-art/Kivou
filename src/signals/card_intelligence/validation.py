"""Deterministic publication checks; QA Signals cannot override these gates."""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
import unicodedata

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationInput,
    PresentationVariant,
)
from signals.card_intelligence.fallback import actor_binding, actor_label

# These certainty patterns retain a useful invariant learned in the isolated
# SPEC-009A experiment. The experimental verifier itself is intentionally not
# imported or activated: its model/policy failed development gates.
_CERTAINTY_PATTERNS = (
    "will buy",
    "will hire",
    "confirmed need",
    "confirmed demand",
    "must purchase",
    "va acheter",
    "va recruter",
    "besoin confirmé",
    "demande certaine",
    "achat certain",
    "opportunité certaine",
)

_STAFFING_TERMS = (
    "personnel",
    "main d'oeuvre",
    "main-d'oeuvre",
    "recrut",
    "embauch",
    "intérim",
    "interim",
    "staffing",
    "workforce",
    "hire",
)
_MATERIAL_TERMS = (
    "matériau",
    "materiau",
    "fourniture",
    "composant",
    "materials_and_components",
    "material",
)
_VOLATILE_URGENCY = (
    "urgent",
    "immédiatement",
    "immediatement",
    "agir maintenant",
    "vient de",
    "tout juste",
    "récent",
    "recent",
)

_MONTHS = {
    "jan": 1,
    "janv": 1,
    "janvier": 1,
    "january": 1,
    "feb": 2,
    "fevr": 2,
    "fevrier": 2,
    "february": 2,
    "mar": 3,
    "mars": 3,
    "march": 3,
    "apr": 4,
    "avr": 4,
    "avril": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "jun": 6,
    "juin": 6,
    "june": 6,
    "jul": 7,
    "juil": 7,
    "juillet": 7,
    "july": 7,
    "aout": 8,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "septembre": 9,
    "september": 9,
    "oct": 10,
    "octobre": 10,
    "october": 10,
    "nov": 11,
    "novembre": 11,
    "november": 11,
    "dec": 12,
    "decembre": 12,
    "december": 12,
}
_MONTH_PATTERN = "|".join(sorted(map(re.escape, _MONTHS), key=len, reverse=True))
_DATE_LITERAL = re.compile(
    rf"\b(?:"
    rf"(?P<iso_year>20\d{{2}})-(?P<iso_month>\d{{2}})-(?P<iso_day>\d{{2}})"
    rf"|(?P<num_day>\d{{1,2}})[-/.](?P<num_month>\d{{1,2}})[-/.](?P<num_year>20\d{{2}}|\d{{2}})"
    rf"|(?P<word_day>\d{{1,2}})(?:er)?\s+(?P<word_month>{_MONTH_PATTERN})[.]?\s+"
    rf"(?P<word_year>20\d{{2}}|\d{{2}})"
    rf"|(?P<en_month>{_MONTH_PATTERN})[.]?\s+(?P<en_day>\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+"
    rf"(?P<en_year>20\d{{2}}|\d{{2}})"
    rf")\b"
)
_DATE_ROLE_BEFORE = {
    "award": re.compile(
        r"(?:"
        r"date\s+d[' ]?attribution(?:\s+publiee?)?"
        r"|date\s+attribution"
        r"|attribuee?\s+(?:le|en|on)"
        r"|attribution\s+(?:le|en|on)"
        r"|award(?:ed)?\s+(?:on|in)"
        r"|(?:published\s+)?award\s+date"
        r")\s*[:;,]?\s*$"
    ),
    "notification": re.compile(
        r"(?:date\s+de\s+notification(?:\s+publiee?)?"
        r"|notifiee?\s+(?:le|en|on)|notified\s+(?:on|in)"
        r"|notification\s+date)\s*[:;,]?\s*$"
    ),
    "publication": re.compile(
        r"(?:date\s+de\s+publication(?:\s+publiee?)?"
        r"|publiee?\s+(?:le|en|on)|published\s+(?:on|in)"
        r"|publication\s+date|avis\s+public\s+enregistre\s+(?:le|on))"
        r"\s*[:;,]?\s*$"
    ),
}
_DATE_ROLE_AFTER = {
    "award": re.compile(r"^\s*[,;:]?\s*(?:date d'attribution|award date|awarded)\b"),
    "notification": re.compile(r"^\s*[,;:]?\s*(?:date de notification|notification date)\b"),
    "publication": re.compile(r"^\s*[,;:]?\s*(?:date de publication|publication date|published)\b"),
}
_AWARD_EVENT = re.compile(
    r"\b(?:attribue(?:e)?s?|attributions?|remporte(?:e)?s?|gagne(?:e)?s?|"
    r"awards?|awarded|wins?|won)\b"
)
_MONTH_LITERAL = re.compile(rf"\b(?:{_MONTH_PATTERN})\b[.]?")
_INCOMPLETE_NUMERIC_DATE = re.compile(r"\b\d{1,2}[-/.]\d{1,2}\b")
_RELATIVE_DATE = re.compile(
    r"\b(?:hier|aujourd'hui|demain|yesterday|today|tomorrow|"
    r"la\s+semaine\s+derniere|last\s+week|ce\s+mois|this\s+month)\b"
)
_WORD = re.compile(r"[a-z0-9]+")
_VERBATIM_WORD_RUN = 12


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _text_fields(payload: CardPresentationPayload) -> tuple[str, ...]:
    return (
        payload.headline,
        payload.award_summary,
        payload.commercial_importance or "",
        payload.fit_reason or "",
        payload.timing or "",
        payload.recommended_action or "",
        *payload.target_roles,
        *payload.fit_need_categories,
        *payload.unknowns,
        *(claim.text for claim in payload.claims),
    )


def _all_text(payload: CardPresentationPayload) -> str:
    return "\n".join(_text_fields(payload))


def _commercial_text(payload: CardPresentationPayload) -> str:
    """Only model-authored commercial assertions, never factual names or copy."""
    values = (
        payload.commercial_importance or "",
        payload.fit_reason or "",
        payload.timing or "",
        payload.recommended_action or "",
        *payload.target_roles,
        *payload.fit_need_categories,
        *payload.unknowns,
        *(
            claim.text
            for claim in payload.claims
            if claim.kind in (ClaimKind.INFERENCE, ClaimKind.RECOMMENDATION)
        ),
    )
    return "\n".join(values)


def _mostly_uppercase(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    if len(letters) < 12:
        return False
    return sum(character.isupper() for character in letters) / len(letters) > 0.72


def _mentions_actor(summary: str, actor: str) -> bool:
    full = _fold(" ".join(actor.split()))
    clipped = _fold(actor_label(actor)).rstrip("…")
    return full in summary or clipped in summary


def _actor_roles_are_canonical(summary: str, source: PresentationInput) -> bool:
    """Critical actor roles are rendered deterministically, not inferred by QA."""
    expected = _fold(actor_binding(source))
    if not summary.startswith(expected):
        return False
    remainder = summary[len(expected) :]
    actors = (source.facts.winner_name, source.facts.buyer_name)
    return not any(
        _fold(actor_label(actor)).rstrip("…") in remainder
        for actor in actors
        if actor is not None
    )


@dataclasses.dataclass(frozen=True)
class _DateMention:
    value: dt.date | None
    rendered: str
    start: int
    end: int


def _date_mentions(folded: str) -> tuple[_DateMention, ...]:
    mentions: list[_DateMention] = []
    for match in _DATE_LITERAL.finditer(folded):
        groups = match.groupdict()
        if groups["iso_year"]:
            year, month, day = (
                int(groups["iso_year"]),
                int(groups["iso_month"]),
                int(groups["iso_day"]),
            )
        elif groups["num_year"]:
            year = int(groups["num_year"])
            if year < 100:
                year += 2000
            month, day = int(groups["num_month"]), int(groups["num_day"])
        elif groups["word_year"]:
            year = int(groups["word_year"])
            if year < 100:
                year += 2000
            month, day = _MONTHS[groups["word_month"]], int(groups["word_day"])
        else:
            year = int(groups["en_year"])
            if year < 100:
                year += 2000
            month, day = _MONTHS[groups["en_month"]], int(groups["en_day"])
        try:
            value = dt.date(year, month, day)
        except ValueError:
            value = None
        mentions.append(
            _DateMention(
                value=value,
                rendered=match.group(0),
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(mentions)


def _date_role(folded: str, mention: _DateMention) -> str | None:
    before = folded[max(0, mention.start - 100) : mention.start]
    after = folded[mention.end : mention.end + 80]
    for role in ("award", "notification", "publication"):
        if _DATE_ROLE_BEFORE[role].search(before) or _DATE_ROLE_AFTER[role].search(after):
            return role
    return None


def _award_event_in_statement(folded: str, position: int) -> bool:
    statement = folded[max(0, position - 180) : position]
    # A dot belonging to an abbreviated month is not a sentence boundary.
    statement = re.sub(rf"\b({_MONTH_PATTERN})[.]\s*$", r"\1 ", statement)
    for boundary in ("! ", "? ", ". "):
        statement = statement.rsplit(boundary, 1)[-1]
    return _AWARD_EVENT.search(statement) is not None


def _year_is_non_temporal_identifier(folded: str, mention: _DateMention) -> bool:
    before = folded[max(0, mention.start - 32) : mention.start]
    after = folded[mention.end : mention.end + 32]
    if re.search(r"\b(?:lot|projet|project)\s*$", before):
        return True
    return re.match(
        r"\s*(?:eur|chf|usd|gbp|cad|aud|unites?|units?|articles?|pieces?|"
        r"m2|m²|kg|tonnes?|·)",
        after,
    ) is not None


def _unparsed_year_has_temporal_context(folded: str, mention: _DateMention) -> bool:
    if _date_role(folded, mention) is not None:
        return True
    before = folded[max(0, mention.start - 40) : mention.start]
    month = re.search(rf"\b(?:{_MONTH_PATTERN})[.]?\s*$", before)
    if month is None:
        month_role = None
    else:
        month_mention = _DateMention(
            value=None,
            rendered=month.group(0),
            start=max(0, mention.start - 40) + month.start(),
            end=max(0, mention.start - 40) + month.end(),
        )
        month_role = _date_role(folded, month_mention)
    if month_role is not None:
        return True
    return _award_event_in_statement(folded, mention.start)


def _without_actor_names_preserving_case(
    value: str, source: PresentationInput
) -> str:
    cleaned = value
    rendered_actors: list[str] = []
    for actor in (source.facts.winner_name, source.facts.buyer_name):
        if actor is None:
            continue
        for rendered in (" ".join(actor.split()), actor_label(actor).rstrip("…")):
            if rendered:
                rendered_actors.append(rendered)
    for rendered in sorted(set(rendered_actors), key=len, reverse=True):
        cleaned = re.sub(re.escape(rendered), " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def _without_actor_names(value: str, source: PresentationInput) -> str:
    return _fold(_without_actor_names_preserving_case(value, source))


def _contains_long_verbatim_run(
    candidate: str,
    raw_title: str,
    source: PresentationInput,
) -> bool:
    candidate_words = _WORD.findall(_without_actor_names(candidate, source))
    raw_words = _WORD.findall(_without_actor_names(raw_title, source))
    if len(candidate_words) < _VERBATIM_WORD_RUN or len(raw_words) < _VERBATIM_WORD_RUN:
        return False
    raw_runs = {
        tuple(raw_words[index : index + _VERBATIM_WORD_RUN])
        for index in range(len(raw_words) - _VERBATIM_WORD_RUN + 1)
    }
    return any(
        tuple(candidate_words[index : index + _VERBATIM_WORD_RUN]) in raw_runs
        for index in range(len(candidate_words) - _VERBATIM_WORD_RUN + 1)
    )


@dataclasses.dataclass(frozen=True)
class ValidationOutcome:
    valid: bool
    errors: tuple[str, ...] = ()


def validate_payload(
    payload: CardPresentationPayload, source: PresentationInput
) -> ValidationOutcome:
    """Validate generated copy against facts, ICP and durable-display rules."""
    errors: list[str] = []
    facts = source.facts
    text = _all_text(payload)
    summary_folded = _fold(payload.award_summary)

    if not _actor_roles_are_canonical(summary_folded, source):
        errors.append("actor_role_mismatch")
    if not _mentions_actor(summary_folded, facts.winner_name):
        errors.append("award_summary_missing_winner")
    if facts.buyer_name:
        if not _mentions_actor(summary_folded, facts.buyer_name):
            errors.append("award_summary_missing_buyer")
        if _fold(facts.buyer_name) == _fold(facts.winner_name) or _fold(
            actor_label(facts.buyer_name)
        ) == _fold(actor_label(facts.winner_name)):
            errors.append("actor_role_collision")
    elif not any(
        phrase in summary_folded
        for phrase in ("acheteur non publie", "buyer not published")
    ):
        errors.append("missing_buyer_not_disclosed")

    known_evidence = set(facts.evidence_refs)
    claim_ids: set[str] = set()
    for claim in payload.claims:
        if claim.claim_id in claim_ids:
            errors.append(f"duplicate_claim_id:{claim.claim_id}")
        claim_ids.add(claim.claim_id)
        unknown = set(claim.evidence_refs) - known_evidence
        if unknown:
            errors.append(f"unknown_evidence_ref:{claim.claim_id}:{','.join(sorted(unknown))}")
        if claim.kind is ClaimKind.RECOMMENDATION and not claim.evidence_refs:
            errors.append(f"recommendation_without_basis:{claim.claim_id}")

    dates_by_role = {
        "award": facts.award_date,
        "notification": facts.contract_notification_date,
        "publication": facts.publication_date,
    }
    known_dates = {value for value in dates_by_role.values() if value is not None}
    for value in _text_fields(payload):
        # Fields are checked independently: an event word in one card field
        # cannot turn an unrelated number in another field into a date. A
        # newline inside a field remains part of the same statement.
        date_text = _without_actor_names(value, source)
        mentions = _date_mentions(date_text)
        for mention in mentions:
            rendered = (
                mention.value.isoformat()
                if mention.value is not None
                else mention.rendered
            )
            if mention.value is None:
                errors.append(f"invalid_date_literal:{rendered}")
                continue
            if mention.value not in known_dates:
                errors.append(f"unknown_date:{rendered}")
            role = _date_role(date_text, mention)
            if role is None:
                errors.append(f"unqualified_date:{rendered}")
            elif dates_by_role[role] != mention.value:
                if role == "award":
                    errors.append("publication_or_notification_presented_as_award_date")
                else:
                    errors.append(f"date_role_mismatch:{role}:{rendered}")
        covered_positions = {
            position
            for mention in mentions
            for position in range(mention.start, mention.end)
        }
        for year in re.finditer(r"\b20\d{2}\b", date_text):
            mention = _DateMention(
                value=None,
                rendered=year.group(0),
                start=year.start(),
                end=year.end(),
            )
            if (
                year.start() not in covered_positions
                and not _year_is_non_temporal_identifier(date_text, mention)
                and _unparsed_year_has_temporal_context(date_text, mention)
            ):
                errors.append(f"unparsed_date_literal:{year.group(0)}")
        for pattern in (_MONTH_LITERAL, _INCOMPLETE_NUMERIC_DATE, _RELATIVE_DATE):
            for literal in pattern.finditer(date_text):
                if (
                    literal.start() not in covered_positions
                    and _award_event_in_statement(date_text, literal.start())
                ):
                    errors.append(f"unparsed_date_literal:{literal.group(0)}")

    if _mostly_uppercase(_without_actor_names_preserving_case(payload.headline, source)):
        errors.append("headline_mostly_uppercase")
    if payload.headline.count("\n") > 2 or payload.award_summary.count("\n") > 2:
        errors.append("copy_exceeds_three_lines")
    if _fold(payload.headline) == _fold(payload.award_summary):
        errors.append("headline_repeats_summary")
    if facts.award_title:
        raw = _fold(facts.award_title)
        if len(raw) > 80 and (raw == _fold(payload.headline) or raw == summary_folded):
            errors.append("raw_administrative_title_reused")
        if any(
            _contains_long_verbatim_run(candidate, facts.award_title, source)
            for candidate in (payload.headline, payload.award_summary)
        ):
            errors.append("raw_administrative_title_partially_reused")

    assertions_without_actors = _without_actor_names(text, source)
    for pattern in _CERTAINTY_PATTERNS:
        if _fold(pattern) in assertions_without_actors:
            errors.append(f"unsupported_certainty:{pattern}")

    profile = _fold(
        source.target_icp_label
        + " "
        + repr(source.target_icp_customer_input)
    )
    commercial = _fold(_commercial_text(payload))
    unbound_fit = set(payload.fit_need_categories) - set(source.icp_matched_needs)
    if unbound_fit:
        errors.append(f"fit_need_not_matched:{','.join(sorted(unbound_fit))}")
    if any(_fold(term) in profile for term in _MATERIAL_TERMS) and any(
        _fold(term) in commercial for term in _STAFFING_TERMS
    ):
        errors.append("icp_category_mismatch:materials_vs_staffing")

    if payload.variant is PresentationVariant.FULL and any(
        _fold(term) in _fold(payload.timing or "") for term in _VOLATILE_URGENCY
    ):
        errors.append("volatile_urgency_copy_not_publishable")

    # Contract validation already excludes commercial fields; this explicit
    # check protects callers that construct objects without Pydantic later.
    if payload.variant is PresentationVariant.FACTUAL_FALLBACK and any(
        claim.kind is not ClaimKind.FACT for claim in payload.claims
    ):
        errors.append("fallback_contains_non_fact_claim")

    return ValidationOutcome(valid=not errors, errors=tuple(errors))
