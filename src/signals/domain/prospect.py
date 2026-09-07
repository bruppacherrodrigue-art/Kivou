"""Public-fact eligibility for prospect bait, independent of accounts and delivery."""
from __future__ import annotations

import datetime as dt
import re

from signals.domain.cpv_labels import cpv_label

PROSPECT_POLICY_VERSION = "prospect-bait-v1"
MAX_PROSPECT_AGE_DAYS = 30


def prospect_refusal_codes(award, event, *, as_of: dt.date) -> tuple[str, ...]:
    reasons = []
    named = False
    for organization in award.awardee_organizations():
        name = (organization.legal_name or "").strip()
        comparable = re.sub(r"[\s.\-/·]", "", name).casefold()
        identifiers = {
            re.sub(r"[\s.\-/·]", "", item.value).casefold()
            for item in organization.identifiers
        }
        if (any(character.isalpha() for character in name)
                and comparable not in identifiers
                and name.casefold() not in {"inconnu", "non renseigné", "titulaire inconnu"}):
            named = True
            break
    if not named:
        reasons.append("WINNER_NAME_UNRESOLVED")
    title = (award.lot.title if award.lot else None) or award.title
    if not title or not title.strip(" \t\n—-"):
        title = cpv_label(award.cpv_main.code, lang="fr") if award.cpv_main else None
    if not title or not title.strip():
        reasons.append("SIGNAL_OBJECT_UNRESOLVED")
    published = event.published_at
    if isinstance(published, dt.datetime):
        published = published.date()
    date = award.award_date or award.contract_notification_date or published
    if date is None:
        reasons.append("RECENCY_UNRESOLVED")
    elif not 0 <= (as_of - date).days <= MAX_PROSPECT_AGE_DAYS:
        reasons.append("SIGNAL_OUTSIDE_ACQUISITION_WINDOW")
    return tuple(reasons)


def require_prospect_eligible(award, event, *, as_of: dt.date) -> None:
    reasons = prospect_refusal_codes(award, event, as_of=as_of)
    if reasons:
        raise ValueError("prospect_ineligible: " + ", ".join(reasons))
