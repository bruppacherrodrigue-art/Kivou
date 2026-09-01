"""Customer-facing copy assembled exclusively from published award facts.

This module deliberately does not import Card Intelligence, the Need Graph or
any provider integration.  It is a deterministic view over the source facts
already attached to a :class:`FeedSignal`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from signals.feed import policy
from signals.feed.query import FeedSignal

_MAX_OBJECT_LENGTH = 180


def _clean(value: object, *, limit: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    if limit is not None and len(cleaned) > limit:
        return f"{cleaned[: limit - 1].rstrip()}…"
    return cleaned


def _amount(value: Decimal | None, currency: str | None, *, lang: str) -> str | None:
    if value is None or currency is None:
        return None
    quantized = value.quantize(Decimal("0.01"))
    integral = quantized == quantized.to_integral()
    rendered = f"{quantized:,.0f}" if integral else f"{quantized:,.2f}"
    if lang == "fr":
        rendered = rendered.replace(",", "\u202f").replace(".", ",")
    currency_label = "€" if currency.upper() == "EUR" else currency.upper()
    return f"{rendered} {currency_label}"


def _location(place: dict[str, Any] | None) -> str | None:
    if not place:
        return None
    return (
        _clean(place.get("locality"))
        or _clean(place.get("subdivision_code"))
        or _clean(place.get("country"))
    )


def _buyer(item: FeedSignal) -> str | None:
    for organization in item.signal.event.procedure_buyers or []:
        name = _clean(organization.get("legal_name"))
        if name:
            return name
    return None


def _headline(
    *,
    company: str,
    market_object: str | None,
    amount: str | None,
    location: str | None,
    buyer: str | None,
    lang: str,
) -> str:
    if lang == "en":
        if amount and location:
            return f"{company} wins a {amount} contract in {location}"
        if market_object:
            return f"{company} wins “{market_object}”"
        if amount:
            return f"{company} wins a {amount} contract"
        if buyer:
            return f"{company} wins a contract from {buyer}"
        return f"Contract awarded to {company}"

    if amount and location:
        return f"{company} remporte un marché de {amount} à {location}"
    if market_object:
        return f"{company} remporte « {market_object} »"
    if amount:
        return f"{company} remporte un marché de {amount}"
    if buyer:
        return f"{company} remporte un marché de {buyer}"
    return f"Marché attribué à {company}"


def factual_display(item: FeedSignal, *, lang: str) -> dict[str, Any]:
    """Return deterministic display copy and its data-completeness state.

    ``missing_fields`` is also the authority for the compact status rendered by
    the frontend: the browser does not guess whether a signal is complete.
    """

    company = item.display.name if item.display is not None else ""
    market_object = _clean(item.signal.award.title, limit=_MAX_OBJECT_LENGTH)
    amount = _amount(item.signal.award.amount, item.signal.award.currency, lang=lang)
    location = _location(item.signal.award.place_of_performance)
    buyer = _buyer(item)
    clock = policy.STATUS_CLOCK.get(item.status)
    event_date = item.event_date

    values = {
        "market_object": market_object,
        "amount": amount,
        "location": location,
        "buyer": buyer,
        "event_date": event_date,
    }
    missing = [name for name, value in values.items() if value is None]
    known_count = len(values) - len(missing)
    completeness = (
        "verified" if not missing else "partial" if known_count else "to_verify"
    )

    return {
        "headline": _headline(
            company=company,
            market_object=market_object,
            amount=amount,
            location=location,
            buyer=buyer,
            lang=lang,
        ),
        "market_summary": market_object,
        "object_short": market_object,
        "date": {
            "value": event_date.isoformat() if event_date is not None else None,
            "kind": clock or "unknown",
        },
        "completeness": completeness,
        "missing_fields": missing,
    }


__all__ = ["factual_display"]
