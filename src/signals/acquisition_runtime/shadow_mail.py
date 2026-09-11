"""Compatibility adapter to the single personalization prospect-mail template."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from signals.personalization.prospect_mail import render_prospect_mail


@dataclass(frozen=True)
class ShadowMailInput:
    family_key: str
    object: str
    holder: str
    amount_minor_units: int
    currency: str
    city: str | None
    department: str
    date: dt.date
    director_name: str | None
    attribution_url: str
    source_url: str
    unsubscribe_url: str


@dataclass(frozen=True)
class ShadowMail:
    subject: str
    body: str
    status: str = "SHADOW"


def render_shadow_mail(value: ShadowMailInput) -> ShadowMail:
    rendered = render_prospect_mail(
        {
            "director_name": value.director_name,
            "family_key": value.family_key,
            "signal_holder": value.holder,
            "signal_subject": value.object,
            "signal_amount_minor_units": value.amount_minor_units,
            "signal_currency": value.currency,
            "signal_city": value.city,
            "signal_department": value.department,
            "signal_decision_date": value.date,
            "attribution_url": value.attribution_url,
            "signal_source_url": value.source_url,
            "unsubscribe_url": value.unsubscribe_url,
        }
    )
    if rendered.contract_failure is not None:
        raise ValueError(f"shadow mail contract failed: {rendered.contract_failure}")
    return ShadowMail(subject=rendered.subject, body=rendered.text)


__all__ = ["ShadowMail", "ShadowMailInput", "render_shadow_mail"]
