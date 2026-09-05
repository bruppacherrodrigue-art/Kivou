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

NEEDS_LABEL: dict[str, str] = {"fr": "Besoins plausibles", "en": "Plausible needs"}
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
    amount_label = (
        f"{amount['value']} {amount['currency']}"
        if amount.get("value") and amount.get("currency")
        else None
    )
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


def render_text(lines: list[AlertLine], *, lang: str, preferences_link: str) -> str:
    """Le corps en texte simple. Pas de HTML, pas de pixel, pas de traqueur.

    Le lien de préférences est OBLIGATOIRE : annoncer « modifiez vos préférences »
    sans dire où revient à ne rien proposer, et un envoi automatisé sans porte de
    sortie visible se fait classer indésirable.
    """
    feed_copy.check_language(lang)
    blocks = [GREETING[lang], ""]
    for index, line in enumerate(lines, start=1):
        blocks.append(f"{index}. {line.company}")
        blocks.append(f"   {line.headline}")
        blocks.append(f"   {line.why_now}")
        if line.contract_title:
            blocks.append(f"   {_truncate(line.contract_title)}")
        facts = tuple(value for value in (line.amount, line.location, line.awarded_on) if value)
        if facts:
            blocks.append(f"   {' · '.join(facts)}")
        if line.buyer:
            blocks.append(f"   {BUYER_LABEL[lang]} : {line.buyer}")
        if line.needs:
            blocks.append(f"   {NEEDS_LABEL[lang]} : {', '.join(line.needs)}")
        if line.for_you_sentence:
            blocks.append(f"   {FOR_YOU_LABEL[lang]} : {line.for_you_sentence}")
        blocks.append(f"   {line.url}")
        blocks.append("")
    blocks.append(FOOTER[lang].format(preferences=preferences_link))
    return "\n".join(blocks)


def render_html(lines: list[AlertLine], *, lang: str, preferences_link: str) -> str:
    """Version HTML sobre construite depuis exactement les mêmes lignes."""
    feed_copy.check_language(lang)
    cards = []
    for line in lines:
        details = [line.headline, line.why_now, line.contract_title]
        facts = tuple(value for value in (line.amount, line.location, line.awarded_on) if value)
        if facts:
            details.append(" · ".join(facts))
        if line.for_you_sentence:
            details.append(f"{FOR_YOU_LABEL[lang]} : {line.for_you_sentence}")
        body = "".join(
            f"<p>{html.escape(value)}</p>" for value in details if value
        )
        cards.append(
            '<article style="border:1px solid #d8e0dc;padding:16px;margin:12px 0">'
            f"<h2>{html.escape(line.company)}</h2>{body}"
            f'<p><a href="{html.escape(line.url, quote=True)}">Ouvrir</a></p></article>'
        )
    return (
        '<!doctype html><html><body><p>Bonjour,</p>'
        + "".join(cards)
        + f'<p><a href="{html.escape(preferences_link, quote=True)}">'
        "Se désinscrire des alertes</a></p></body></html>"
    )
