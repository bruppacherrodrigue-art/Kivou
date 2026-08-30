"""Compact, deterministic factual fallback; never source prose copied verbatim."""

from __future__ import annotations

from decimal import Decimal

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationVariant,
)


def actor_label(value: str, *, limit: int = 88) -> str:
    """Keep long consortium names factual while preserving a card-safe shape."""
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    prefix = compact[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{prefix or compact[: limit - 1]}…"


def _amount(value: Decimal, currency: str) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return f"{rendered or '0'} {currency}"


def _bounded_sentences(sentences: list[str], *, limit: int = 420) -> str:
    selected: list[str] = []
    for sentence in sentences:
        candidate = " ".join((*selected, sentence))
        if len(candidate) <= limit:
            selected.append(sentence)
    return " ".join(selected)


def factual_fallback(source: PresentationInput) -> CardPresentationPayload:
    facts = source.facts
    winner = actor_label(facts.winner_name)
    buyer = actor_label(facts.buyer_name) if facts.buyer_name else None
    if source.language == "en":
        if buyer:
            sentences = [
                f"{buyer} is identified as the buyer and {winner} as the awarded company."
            ]
        else:
            sentences = [
                (
                    f"{winner} is identified as the awarded company. Buyer not published "
                    "in the available data."
                )
            ]
        sentences.append(
            "Object not provided by the source."
            if facts.award_title is None
            else "An object is published in the official notice; no validated summary is available."
        )
        if facts.amount is not None and facts.currency is not None:
            sentences.append(f"Published contract amount: {_amount(facts.amount, facts.currency)}.")
        if facts.award_date is not None:
            sentences.append(f"Published award date: {facts.award_date.isoformat()}.")
        if facts.location is not None:
            sentences.append(f"Published location: {actor_label(facts.location)}.")
        unknowns = [
            label
            for missing, label in (
                (facts.buyer_name is None, "Buyer not published"),
                (facts.award_date is None, "Award date not published"),
                (facts.award_title is None, "Object not provided by the source"),
                (facts.location is None, "Place of performance not published"),
            )
            if missing
        ]
        headline = f"Documented public award — {actor_label(facts.winner_name, limit=120)}"
    else:
        if buyer:
            sentences = [
                f"{buyer} est indiqué comme acheteur et {winner} comme entreprise attributaire."
            ]
        else:
            sentences = [
                (
                    f"{winner} est indiqué comme entreprise attributaire. Acheteur non publié "
                    "dans les données disponibles."
                )
            ]
        sentences.append(
            "Objet non renseigné dans la source."
            if facts.award_title is None
            else "Objet publié dans l'avis officiel ; résumé validé indisponible."
        )
        if facts.amount is not None and facts.currency is not None:
            sentences.append(f"Montant du marché publié : {_amount(facts.amount, facts.currency)}.")
        if facts.award_date is not None:
            sentences.append(f"Date d'attribution publiée : {facts.award_date.isoformat()}.")
        if facts.location is not None:
            sentences.append(f"Territoire publié : {actor_label(facts.location)}.")
        unknowns = [
            label
            for missing, label in (
                (facts.buyer_name is None, "Acheteur non publié"),
                (facts.award_date is None, "Date d'attribution non publiée"),
                (facts.award_title is None, "Objet non renseigné dans la source"),
                (facts.location is None, "Territoire d'exécution non publié"),
            )
            if missing
        ]
        headline = f"Attribution publique documentée — {actor_label(facts.winner_name, limit=120)}"

    return CardPresentationPayload(
        variant=PresentationVariant.FACTUAL_FALLBACK,
        headline=headline,
        award_summary=_bounded_sentences(sentences),
        unknowns=tuple(unknowns),
        claims=(
            PresentationClaim(
                claim_id="FACT_AWARDEE",
                kind=ClaimKind.FACT,
                text=(
                    f"Awarded company: {winner}"
                    if source.language == "en"
                    else f"Entreprise attributaire : {winner}"
                ),
                evidence_refs=facts.evidence_refs,
            ),
        ),
    )
