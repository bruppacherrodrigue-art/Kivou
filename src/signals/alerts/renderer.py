"""Le texte du digest — le même vocabulaire sûr que le feed, jamais un second.

La formulation vient de `recency.claim`, comme partout ailleurs (§21)
────────────────────────────────────────────────────────────────────
Écrire ici une seconde phrase d'événement recréerait exactement l'écart que
SPEC-009D a mesuré : un feed qui dit une chose, un e-mail qui en dit une
autre, et aucun test qui compare les deux. L'e-mail réutilise donc la carte
de feed déjà construite.

Ce que l'e-mail ne contient jamais
──────────────────────────────────
Aucune preuve (elle reste dans le détail du signal), aucun score, aucune
règle, aucun vocabulaire moteur. Un e-mail est un rappel, pas une archive :
ce qui mérite vérification mérite d'être ouvert dans Kivou.
"""

from __future__ import annotations

import dataclasses
import html
from decimal import Decimal, InvalidOperation
from typing import Any

from signals.feed import copy as feed_copy

ALERT_COPY_VERSION = "kivou-alert-copy-v0.1"

SUBJECT: dict[str, dict[str, str]] = {
    "singular": {
        "fr": "1 nouveau signal pour vous",
        "en": "1 new signal on your markets",
    },
    "plural": {
        "fr": "{count} nouveaux signaux pour vous",
        "en": "{count} new signals on your markets",
    },
}

GREETING: dict[str, str] = {
    "fr": "Bonjour,\n\nDe nouveaux signaux correspondent à vos profils cibles.",
    "en": "Hello,\n\nNew signals match your target profiles.",
}

FOOTER: dict[str, str] = {
    "fr": (
        "La source officielle est disponible sur chaque signal.\n"
        "Pour ne plus recevoir ces alertes, modifiez vos préférences de notification :\n"
        "{preferences}"
    ),
    "en": (
        "Published facts and their sources are verifiable on each signal.\n"
        "To stop receiving these alerts, change your notification preferences:\n"
        "{preferences}"
    ),
}

NEEDS_LABEL: dict[str, str] = {"fr": "À prévoir", "en": "To plan for"}
BUYER_LABEL: dict[str, str] = {"fr": "Acheteur", "en": "Buyer"}
FOR_YOU_LABEL: dict[str, str] = {"fr": "Pour vous", "en": "For you"}

#: §21 — au plus trois familles de besoin par signal. Au-delà, on recopie
#: l'analyse dans l'e-mail au lieu d'inviter à l'ouvrir.
MAXIMUM_NEEDS_SHOWN = 3


@dataclasses.dataclass(frozen=True)
class AlertLine:
    """Un signal, réduit à ce qui donne envie de l'ouvrir."""

    signal_key: str
    company: str
    headline: str
    why_now: str
    contract_title: str | None
    amount: str | None
    location: str | None
    awarded_on: str | None
    buyer: str | None
    needs: tuple[str, ...]
    for_you_sentence: str | None
    url: str


def line_from_card(card: dict[str, Any], *, url: str, lang: str) -> AlertLine:
    """Construit une ligne depuis la carte de feed DÉJÀ rendue.

    Repartir de la carte garantit que l'e-mail et l'application disent la même
    chose du même signal — y compris le jour où la formulation change.
    """
    feed_copy.check_language(lang)
    needs = [
        need["label"] for need in card["analysis"]["plausible_needs"]["items"] if need.get("label")
    ][:MAXIMUM_NEEDS_SHOWN]
    buyer = (card["contract"].get("buyer") or {}).get("name")
    amount = card["contract"].get("amount") or {}
    amount_label = _format_amount(amount.get("value"), amount.get("currency"), lang=lang)
    location = card["contract"].get("location") or {}
    return AlertLine(
        signal_key=card["signal_id"],
        company=card["company"]["name"] or "",
        headline=card["event"]["headline"],
        why_now=card["event"]["why_now"],
        contract_title=card["contract"].get("title"),
        amount=amount_label,
        location=location.get("locality") or location.get("subdivision_label"),
        awarded_on=card["contract"].get("dates", {}).get("award"),
        buyer=buyer,
        needs=tuple(needs),
        for_you_sentence=card["analysis"]["fit"].get("for_you_sentence"),
        url=url,
    )


def subject(count: int, *, lang: str) -> str:
    feed_copy.check_language(lang)
    if count == 1:
        return SUBJECT["singular"][lang]
    return SUBJECT["plural"][lang].format(count=count)


def _truncate(text: str, limit: int = 120) -> str:
    """Un titre de marché peut faire trois lignes ; l'e-mail n'en a pas besoin."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _format_amount(value: str | None, currency: str | None, *, lang: str) -> str | None:
    if not value or not currency:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return f"{value} {currency}"
    rendered = f"{number:,.0f}" if lang == "en" else f"{number:,.0f}".replace(",", "\u00a0")
    symbol = {"EUR": "€", "CHF": "CHF", "GBP": "£", "USD": "$"}.get(currency.upper(), currency.upper())
    return f"{rendered} {symbol}"


def _format_date(value: str | None, *, lang: str) -> str | None:
    if not value:
        return None
    try:
        year, month, day = (int(part) for part in value[:10].split("-"))
    except (ValueError, TypeError):
        return value
    if lang == "en":
        return f"{month:02d}/{day:02d}/{year}"
    months = (
        "janv.", "févr.", "mars", "avr.", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc.",
    )
    return f"{day} {months[month - 1]} {year}"


def render_text(
    lines: list[AlertLine], *, lang: str, preferences_link: str,
) -> str:
    """Le corps en texte simple. Pas de HTML, pas de pixel, pas de traqueur.

    Le lien de préférences est OBLIGATOIRE : annoncer « modifiez vos préférences »
    sans dire où revient à ne rien proposer, et un envoi automatisé sans porte de
    sortie visible se fait classer indésirable.
    """
    feed_copy.check_language(lang)
    blocks: list[str] = []
    for line in lines:
        blocks.append(f"Titulaire : {line.company}")
        if line.contract_title:
            blocks.append(f"Objet : {_truncate(line.contract_title)}")
        if line.amount:
            blocks.append(f"Montant : {line.amount}")
        if line.location:
            blocks.append(f"Lieu : {line.location}")
        if line.awarded_on:
            blocks.append(f"Date : {_format_date(line.awarded_on, lang=lang)}")
        if line.for_you_sentence:
            blocks.append(f"{FOR_YOU_LABEL[lang]} : {line.for_you_sentence}")
        blocks.append(f"Ouvrir : {line.url}")
        blocks.append("")
    blocks.append(FOOTER[lang].format(preferences=preferences_link))
    return "\n".join(blocks)


def render_html(
    lines: list[AlertLine], *, lang: str, preferences_link: str,
) -> str:
    """Version HTML sobre construite depuis exactement les mêmes lignes."""
    feed_copy.check_language(lang)
    cards = []
    for line in lines:
        details = [
            ("Titulaire", line.company),
            ("Objet", _truncate(line.contract_title) if line.contract_title else None),
            ("Montant", line.amount),
            ("Lieu", line.location),
            ("Date", _format_date(line.awarded_on, lang=lang)),
        ]
        if line.for_you_sentence:
            details.append((FOR_YOU_LABEL[lang], line.for_you_sentence))
        body = "".join(
            f"<p><strong>{html.escape(label)} :</strong> {html.escape(value)}</p>"
            for label, value in details if value
        )
        cards.append(
            '<article style="border:1px solid #d8e0dc;padding:16px;margin:12px 0">'
            f"{body}"
            f'<p><a href="{html.escape(line.url, quote=True)}">Ouvrir</a></p></article>'
        )
    return (
        '<!doctype html><html><body>'
        + "".join(cards)
        + f'<p><a href="{html.escape(preferences_link, quote=True)}">'
        "Se désinscrire des alertes</a></p></body></html>"
    )
