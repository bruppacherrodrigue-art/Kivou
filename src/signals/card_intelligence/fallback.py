"""Deterministic factual Card Intelligence renderer for offline publication."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationUnknown,
    PresentationVariant,
)

_FR_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _clean(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("factual fallback text cannot be empty")
    return cleaned


def actor_label(value: str) -> str:
    """Normalize whitespace without shortening or resolving a published actor."""

    return _clean(value)


def bounded(text: str, limit: int, *, fallback: str) -> str:
    """Keep a whole fact or use a whole generic fact; never cut a legal name."""

    candidate = _clean(text)
    replacement = _clean(fallback)
    if limit < 1 or len(replacement) > limit:
        raise ValueError("bounded fallback exceeds its contract")
    return candidate if len(candidate) <= limit else replacement


def _evidence(source: PresentationInput) -> tuple[str, ...]:
    refs = tuple(dict.fromkeys(source.facts.evidence_refs))[:16]
    if not refs:
        raise ValueError("factual fallback requires persisted evidence")
    return refs


def _date(value: dt.date, *, language: str) -> str:
    if language == "fr":
        return f"{value.day} {_FR_MONTHS[value.month - 1]} {value.year}"
    return f"{_EN_MONTHS[value.month - 1]} {value.day}, {value.year}"


def _amount(value: Decimal, currency: str) -> str:
    return f"{value} {currency}"


def _missing_fact_labels(
    source: PresentationInput, evidence_refs: tuple[str, ...]
) -> tuple[PresentationUnknown, ...]:
    facts = source.facts
    if source.language == "fr":
        missing = (
            (facts.buyer_name, "Acheteur non publié."),
            (facts.amount, "Montant non publié."),
            (facts.location, "Lieu d'exécution non publié."),
            (facts.award_date, "Date d'attribution non publiée."),
            (
                facts.contract_notification_date,
                "Date de notification du contrat non publiée.",
            ),
            (facts.publication_date, "Date de publication non publiée."),
        )
    else:
        missing = (
            (facts.buyer_name, "The buyer is not published."),
            (facts.amount, "The amount is not published."),
            (facts.location, "The place of performance is not published."),
            (facts.award_date, "The award date is not published."),
            (
                facts.contract_notification_date,
                "The contract notification date is not published.",
            ),
            (facts.publication_date, "The publication date is not published."),
        )
    return tuple(
        PresentationUnknown(text=text, evidence_refs=evidence_refs)
        for value, text in missing
        if value is None
    )


def _dated_claims(
    source: PresentationInput, evidence_refs: tuple[str, ...]
) -> tuple[PresentationClaim, ...]:
    facts = source.facts
    if source.language == "fr":
        dated = (
            (
                "FACT_AWARD_DATE",
                facts.award_date,
                "Date d'attribution publiée : {date}.",
            ),
            (
                "FACT_NOTIFICATION_DATE",
                facts.contract_notification_date,
                "Date de notification du contrat publiée : {date}.",
            ),
            (
                "FACT_PUBLICATION_DATE",
                facts.publication_date,
                "Date de publication : {date}.",
            ),
        )
    else:
        dated = (
            ("FACT_AWARD_DATE", facts.award_date, "Published award date: {date}."),
            (
                "FACT_NOTIFICATION_DATE",
                facts.contract_notification_date,
                "Published contract notification date: {date}.",
            ),
            ("FACT_PUBLICATION_DATE", facts.publication_date, "Publication date: {date}."),
        )
    return tuple(
        PresentationClaim(
            claim_id=claim_id,
            kind=ClaimKind.FACT,
            text=template.format(date=_date(value, language=source.language)),
            evidence_refs=evidence_refs,
        )
        for claim_id, value, template in dated
        if value is not None
    )


def factual_fallback(source: PresentationInput) -> CardPresentationPayload:
    """Render one evidence-bound fallback with no commercial conclusion.

    The renderer deliberately ignores administrative prose.  It uses only
    structured actor roles, atomic money, structured location, and separately
    typed dates copied into :class:`PresentationInput`.
    """

    facts = source.facts
    winner = actor_label(facts.winner_name)
    buyer = actor_label(facts.buyer_name) if facts.buyer_name is not None else None
    evidence_refs = _evidence(source)

    if source.language == "fr":
        headline = bounded(
            f"Attribution publiée pour {winner}",
            160,
            fallback="Attribution publiée",
        )
        if buyer is None:
            actor_sentence = bounded(
                f"Attributaire publié : {winner}. Acheteur non publié.",
                420,
                fallback="La source publie un attributaire. Acheteur non publié.",
            )
        else:
            actor_sentence = bounded(
                f"Acheteur publié : {buyer}. Attributaire publié : {winner}.",
                420,
                fallback="La source publie un acheteur et un attributaire.",
            )
    else:
        headline = bounded(
            f"Published award for {winner}",
            160,
            fallback="Published award",
        )
        if buyer is None:
            actor_sentence = bounded(
                f"Published awardee: {winner}. The buyer is not published.",
                420,
                fallback="The source publishes an awardee. The buyer is not published.",
            )
        else:
            actor_sentence = bounded(
                f"Published buyer: {buyer}. Published awardee: {winner}.",
                420,
                fallback="The source publishes a buyer and an awardee.",
            )

    claims: list[PresentationClaim] = [
        PresentationClaim(
            claim_id="FACT_HEADLINE",
            kind=ClaimKind.FACT,
            text=headline,
            evidence_refs=evidence_refs,
        ),
        PresentationClaim(
            claim_id="FACT_AWARD_CONTEXT",
            kind=ClaimKind.FACT,
            text=actor_sentence,
            evidence_refs=evidence_refs,
        ),
    ]
    if facts.amount is not None:
        assert facts.currency is not None
        amount_text = bounded(
            f"Montant publié : {_amount(facts.amount, facts.currency)}."
            if source.language == "fr"
            else f"Published amount: {_amount(facts.amount, facts.currency)}.",
            420,
            fallback=(
                "La source publie un montant."
                if source.language == "fr"
                else "The source publishes an amount."
            ),
        )
        claims.append(
            PresentationClaim(
                claim_id="FACT_AMOUNT",
                kind=ClaimKind.FACT,
                text=amount_text,
                evidence_refs=evidence_refs,
            )
        )
    if facts.location is not None:
        location_text = bounded(
            f"Lieu d'exécution publié : {facts.location}."
            if source.language == "fr"
            else f"Published place of performance: {facts.location}.",
            420,
            fallback=(
                "La source publie un lieu d'exécution."
                if source.language == "fr"
                else "The source publishes a place of performance."
            ),
        )
        claims.append(
            PresentationClaim(
                claim_id="FACT_LOCATION",
                kind=ClaimKind.FACT,
                text=location_text,
                evidence_refs=evidence_refs,
            )
        )
    claims.extend(_dated_claims(source, evidence_refs))

    return CardPresentationPayload(
        variant=PresentationVariant.FACTUAL_FALLBACK,
        headline=headline,
        award_summary=actor_sentence,
        unknowns=_missing_fact_labels(source, evidence_refs),
        claims=tuple(claims),
    )


__all__ = ["actor_label", "bounded", "factual_fallback"]
