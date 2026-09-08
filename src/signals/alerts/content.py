"""Compact alert cards projected from the same rendered fields as Today.

No separate event claim or plausible-needs template: the email shows the holder,
object, amount, place, effective date, persisted fit sentence and open action.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import html
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from signals.feed import copy as feed_copy

ALERT_COPY_VERSION = "kivou-alert-pr6-v1"
SUBJECT = {
    "singular": {"fr": "1 nouveau signal pour vous", "en": "1 new signal on your markets"},
    "plural": {"fr": "{count} nouveaux signaux pour vous", "en": "{count} new signals on your markets"},
}
GREETING = {
    "fr": "Bonjour,\n\nDe nouveaux signaux correspondent à vos profils cibles.",
    "en": "Hello,\n\nNew signals match your target profiles.",
}
FOOTER = {
    "fr": "La source officielle est disponible sur chaque signal.\n"
          "Pour ne plus recevoir ces alertes, modifiez vos préférences de notification :\n{preferences}",
    "en": "Published facts and their sources are verifiable on each signal.\n"
          "To stop receiving these alerts, change your notification preferences:\n{preferences}",
}
FOR_YOU_LABEL = {"fr": "Pour vous", "en": "For you"}
OPEN_LABEL = {"fr": "Ouvrir", "en": "Open"}
_MISSING = "—"
_MONTHS = {
    "fr": ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"),
}
_DATE_LABELS = {
    "award": {"fr": "Attribué le", "en": "Awarded on"},
    "notification": {"fr": "Attribué le", "en": "Awarded on"},
    "contract_notification": {"fr": "Attribué le", "en": "Awarded on"},
    "publication": {"fr": "Publié le", "en": "Published on"},
}
_COUNTRIES = {
    "fr": {"FR": "France", "CH": "Suisse"},
    "en": {"FR": "France", "CH": "Switzerland"},
}


@dataclasses.dataclass(frozen=True)
class AlertLine:
    signal_key: str
    company: str
    contract_title: str
    amount: str
    location: str
    awarded_on: str
    date_label: str
    for_you_sentence: str
    url: str


def _amount(amount: dict | None, *, lang: str) -> str:
    """Match Today's fr-FR/en-GB Intl currency display, rounded to whole units."""
    if not amount or amount.get("value") is None or not amount.get("currency"):
        return _MISSING
    currency = amount["currency"].upper()
    try:
        value = Decimal(amount["value"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return f"{amount['value']} {currency}"
    if not value.is_finite():
        return _MISSING
    digits = f"{abs(value):,.0f}"
    sign = "-" if value < 0 else ""
    if lang == "fr":
        symbol = {"EUR": "€", "USD": "$US", "GBP": "£GB", "CAD": "$CA"}.get(currency, currency)
        return f"{sign}{digits.replace(',', chr(160))}\u00a0{symbol}"
    symbol = {"EUR": "€", "USD": "US$", "GBP": "£", "CAD": "CA$"}.get(currency, currency)
    gap = "\u00a0" if symbol.isalpha() else ""
    return f"{sign}{symbol}{gap}{digits}"


def line_from_card(card: dict[str, Any], *, url: str, lang: str) -> AlertLine:
    feed_copy.check_language(lang)
    contract = card["contract"]
    factual = card["factual_display"]
    date = factual.get("date") or {}
    try:
        parsed = dt.date.fromisoformat(date.get("value") or "")
    except ValueError:
        short_date = _MISSING
    else:
        short_date = f"{parsed.day} {_MONTHS[lang][parsed.month - 1]}"
    place = contract.get("location") or {}
    fit = card["analysis"]["fit"]
    return AlertLine(
        signal_key=card["signal_id"], company=card["company"].get("name") or _MISSING,
        contract_title=(contract.get("lot_title") or contract.get("title")
                        or factual.get("object_short") or _MISSING),
        amount=_amount(contract.get("amount"), lang=lang),
        location=(place.get("locality") or place.get("subdivision_label")
                  or _COUNTRIES[lang].get(place.get("country")) or _MISSING),
        awarded_on=short_date,
        date_label=_DATE_LABELS.get(date.get("kind"), {}).get(lang, ""),
        for_you_sentence=fit.get("for_you_sentence") or next(iter(fit.get("reasons") or ()), _MISSING),
        url=url,
    )


def subject(count: int, *, lang: str) -> str:
    feed_copy.check_language(lang)
    return SUBJECT["singular" if count == 1 else "plural"][lang].format(count=count)


def _date(line: AlertLine) -> str:
    return f"{line.date_label} {line.awarded_on}".strip()


def _offers(count: int, *, lang: str) -> str:
    return (f"{count} autres signaux dans votre zone — voir les offres :" if lang == "fr"
            else f"{count} more signals in your area — view plans:")


def render_text(lines: list[AlertLine], *, lang: str, preferences_link: str,
                remaining_count: int = 0, pricing_link: str | None = None) -> str:
    feed_copy.check_language(lang)
    blocks = [GREETING[lang], ""]
    for index, line in enumerate(lines, start=1):
        blocks.extend((f"{index}. {line.company}", f"   {line.contract_title}",
                       f"   {line.amount} · {line.location} · {_date(line)}",
                       f"   {FOR_YOU_LABEL[lang]} : {line.for_you_sentence}",
                       f"   {OPEN_LABEL[lang]} : {line.url}", ""))
    if remaining_count and pricing_link:
        blocks.extend((_offers(remaining_count, lang=lang), pricing_link, ""))
    blocks.append(FOOTER[lang].format(preferences=preferences_link))
    return "\n".join(blocks)


def render_html(lines: list[AlertLine], *, lang: str, preferences_link: str,
                remaining_count: int = 0, pricing_link: str | None = None) -> str:
    feed_copy.check_language(lang)
    cards = []
    for line in lines:
        details = (line.contract_title, f"{line.amount} · {line.location} · {_date(line)}",
                   f"{FOR_YOU_LABEL[lang]} : {line.for_you_sentence}")
        body = "".join(f"<p>{html.escape(value)}</p>" for value in details)
        cards.append('<article style="border:1px solid #d8e0dc;padding:16px;margin:12px 0">'
                     f"<h2>{html.escape(line.company)}</h2>{body}"
                     f'<p><a href="{html.escape(line.url, quote=True)}">'
                     f"{OPEN_LABEL[lang]}</a></p></article>")
    upsell = (f'<p>{html.escape(_offers(remaining_count, lang=lang))} '
              f'<a href="{html.escape(pricing_link, quote=True)}">'
              f'{"Voir les offres" if lang == "fr" else "View plans"}</a></p>'
              if remaining_count and pricing_link else "")
    unsubscribe = "Se désinscrire des alertes" if lang == "fr" else "Unsubscribe from alerts"
    greeting = "Bonjour," if lang == "fr" else "Hello,"
    return ('<!doctype html><html><body>' + f'<p>{greeting}</p>' + "".join(cards) + upsell
            + f'<p><a href="{html.escape(preferences_link, quote=True)}">'
            + unsubscribe + '</a></p></body></html>')
