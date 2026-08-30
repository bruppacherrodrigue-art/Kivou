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


def _direct_evidence(
    source: PresentationInput,
    *,
    table: str,
    column: str,
) -> str:
    direct = tuple(
        ref
        for ref in source.facts.evidence_refs
        if ref.startswith(f"source-field:v1:{table}:") and ref.endswith(f":{column}")
    )
    if len(direct) != 1:
        raise ValueError(
            f"factual fallback requires exactly one source-field proof for {table}.{column}"
        )
    return direct[0]


def _persisted_evidence(
    source: PresentationInput,
    *,
    anchors: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        ref
        for ref in source.facts.evidence_refs
        if ref.startswith("evidence:v1:") and any(ref.endswith(f":{anchor}") for anchor in anchors)
    )


def _semantic_evidence(
    source: PresentationInput,
    *,
    table: str,
    column: str,
    anchors: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Reserve the exact field pointer before optional fact-bound evidence."""

    direct = _direct_evidence(source, table=table, column=column)
    persisted = _persisted_evidence(source, anchors=anchors)
    return tuple(dict.fromkeys((direct, *persisted)))[:16]


def _award_evidence(
    source: PresentationInput,
    column: str,
    *,
    anchors: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return _semantic_evidence(
        source,
        table="contract_award",
        column=column,
        anchors=anchors,
    )


def _event_evidence(
    source: PresentationInput,
    column: str,
    *,
    anchors: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return _semantic_evidence(
        source,
        table="source_event",
        column=column,
        anchors=anchors,
    )


def _amount_evidence(source: PresentationInput) -> tuple[str, ...]:
    """Reserve both real columns of the atomic amount/currency pair."""

    amount = _direct_evidence(source, table="contract_award", column="amount")
    currency = _direct_evidence(source, table="contract_award", column="currency")
    persisted = _persisted_evidence(source, anchors=("amount",))
    return tuple(dict.fromkeys((amount, currency, *persisted)))[:16]


def _date(value: dt.date, *, language: str) -> str:
    if language == "fr":
        return f"{value.day} {_FR_MONTHS[value.month - 1]} {value.year}"
    return f"{_EN_MONTHS[value.month - 1]} {value.day}, {value.year}"


def _amount(value: Decimal, currency: str) -> str:
    return f"{value} {currency}"


def _missing_fact_labels(source: PresentationInput) -> tuple[PresentationUnknown, ...]:
    facts = source.facts
    if source.language == "fr":
        missing = (
            (
                facts.buyer_name,
                "Acheteur non publié.",
                _event_evidence(source, "procedure_buyers", anchors=("procedure_buyers",)),
            ),
            (
                facts.amount,
                "Montant non publié.",
                _amount_evidence(source),
            ),
            (
                facts.location,
                "Lieu d'exécution non publié.",
                _award_evidence(source, "place_of_performance"),
            ),
            (
                facts.award_date,
                "Date d'attribution non publiée.",
                _award_evidence(source, "award_date", anchors=("award_date",)),
            ),
            (
                facts.contract_notification_date,
                "Date de notification du contrat non publiée.",
                _award_evidence(source, "contract_notification_date"),
            ),
            (
                facts.publication_date,
                "Date de publication non publiée.",
                _event_evidence(source, "published_on"),
            ),
        )
    else:
        missing = (
            (
                facts.buyer_name,
                "The buyer is not published.",
                _event_evidence(source, "procedure_buyers", anchors=("procedure_buyers",)),
            ),
            (
                facts.amount,
                "The amount is not published.",
                _amount_evidence(source),
            ),
            (
                facts.location,
                "The place of performance is not published.",
                _award_evidence(source, "place_of_performance"),
            ),
            (
                facts.award_date,
                "The award date is not published.",
                _award_evidence(source, "award_date", anchors=("award_date",)),
            ),
            (
                facts.contract_notification_date,
                "The contract notification date is not published.",
                _award_evidence(source, "contract_notification_date"),
            ),
            (
                facts.publication_date,
                "The publication date is not published.",
                _event_evidence(source, "published_on"),
            ),
        )
    return tuple(
        PresentationUnknown(text=text, evidence_refs=evidence_refs)
        for value, text, evidence_refs in missing
        if value is None
    )


def _dated_claims(source: PresentationInput) -> tuple[PresentationClaim, ...]:
    facts = source.facts
    if source.language == "fr":
        dated = (
            (
                "FACT_AWARD_DATE",
                facts.award_date,
                "Date d'attribution publiée : {date}.",
                _award_evidence(source, "award_date", anchors=("award_date",)),
            ),
            (
                "FACT_NOTIFICATION_DATE",
                facts.contract_notification_date,
                "Date de notification du contrat publiée : {date}.",
                _award_evidence(source, "contract_notification_date"),
            ),
            (
                "FACT_PUBLICATION_DATE",
                facts.publication_date,
                "Date de publication : {date}.",
                _event_evidence(source, "published_on"),
            ),
        )
    else:
        dated = (
            (
                "FACT_AWARD_DATE",
                facts.award_date,
                "Published award date: {date}.",
                _award_evidence(source, "award_date", anchors=("award_date",)),
            ),
            (
                "FACT_NOTIFICATION_DATE",
                facts.contract_notification_date,
                "Published contract notification date: {date}.",
                _award_evidence(source, "contract_notification_date"),
            ),
            (
                "FACT_PUBLICATION_DATE",
                facts.publication_date,
                "Publication date: {date}.",
                _event_evidence(source, "published_on"),
            ),
        )
    return tuple(
        PresentationClaim(
            claim_id=claim_id,
            kind=ClaimKind.FACT,
            text=template.format(date=_date(value, language=source.language)),
            evidence_refs=claim_evidence,
        )
        for claim_id, value, template, claim_evidence in dated
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
    awardee_evidence = _award_evidence(
        source,
        "awardee_parties",
        anchors=("winner",),
    )
    buyer_evidence = _event_evidence(
        source,
        "procedure_buyers",
        anchors=("procedure_buyers",),
    )
    awardee_direct = _direct_evidence(
        source,
        table="contract_award",
        column="awardee_parties",
    )
    buyer_direct = _direct_evidence(
        source,
        table="source_event",
        column="procedure_buyers",
    )
    actor_evidence = tuple(
        dict.fromkeys(
            (
                awardee_direct,
                buyer_direct,
                *awardee_evidence,
                *buyer_evidence,
            )
        )
    )[:16]

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
            evidence_refs=awardee_evidence,
        ),
        PresentationClaim(
            claim_id="FACT_AWARD_CONTEXT",
            kind=ClaimKind.FACT,
            text=actor_sentence,
            evidence_refs=actor_evidence,
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
                evidence_refs=_amount_evidence(source),
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
                evidence_refs=_award_evidence(source, "place_of_performance"),
            )
        )
    claims.extend(_dated_claims(source))

    payload = CardPresentationPayload(
        variant=PresentationVariant.FACTUAL_FALLBACK,
        headline=headline,
        award_summary=actor_sentence,
        unknowns=_missing_fact_labels(source),
        claims=tuple(claims),
    )
    return source.ensure_evidence_refs(payload)


__all__ = ["actor_label", "bounded", "factual_fallback"]
