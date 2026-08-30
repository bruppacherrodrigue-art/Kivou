"""Build the bounded model input from already-owned, structured Kivou data."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from signals.accounts.schema import target_icp
from signals.card_intelligence.contracts import PresentationInput, SourceFacts
from signals.feed.query import FeedSignal


class PresentationInputUnavailable(ValueError):
    pass


def _buyer_name(item: FeedSignal) -> str | None:
    for buyer in item.signal.event.procedure_buyers or []:
        name = (buyer.get("legal_name") or "").strip()
        if name and not name.replace(" ", "").isdigit():
            return name
    return None


def _location(item: FeedSignal) -> str | None:
    place = item.signal.award.place_of_performance or {}
    values = (
        place.get("locality"),
        place.get("postal_code"),
        place.get("subdivision_code"),
        place.get("country"),
    )
    rendered = " · ".join(str(value).strip() for value in values if value)
    return rendered or None


def build_presentation_input(
    connection: Connection,
    *,
    item: FeedSignal,
    account_id: str,
    language: str,
) -> PresentationInput:
    """Build an input only through the account-owned target ICP relationship."""
    profile = connection.execute(
        sa.select(
            target_icp.c.target_icp_id,
            target_icp.c.label,
            target_icp.c.matching_revision,
            target_icp.c.customer_input,
        ).where(
            target_icp.c.account_id == account_id,
            target_icp.c.target_icp_id == item.signal.target_icp_id,
            target_icp.c.status == "active",
        )
    ).mappings().one_or_none()
    if profile is None or profile["matching_revision"] != item.signal.target_icp_revision:
        raise PresentationInputUnavailable(item.signal.signal_key)
    if item.display is None:
        raise PresentationInputUnavailable("winner display name is unavailable")

    event = item.signal.event
    award = item.signal.award
    source_ref = f"source:{event.source_system}:{event.source_notice_id}"
    refs = {source_ref}
    for evidence in item.signal.evidence:
        refs.add(evidence.evidence_key)
    amount: Decimal | None = award.amount if award.currency else None
    currency = award.currency if award.amount is not None else None

    return PresentationInput(
        account_id=account_id,
        signal_key=item.signal.signal_key,
        signal_revision=item.signal.revision,
        target_icp_id=item.signal.target_icp_id,
        target_icp_revision=item.signal.target_icp_revision,
        language=language,
        target_icp_label=profile["label"],
        target_icp_customer_input=profile["customer_input"],
        icp_matched_needs=tuple(item.signal.icp_matched_needs or ()),
        facts=SourceFacts(
            winner_name=item.display.name,
            buyer_name=_buyer_name(item),
            award_title=award.title or award.lot_title,
            amount=amount,
            currency=currency,
            location=_location(item),
            award_date=award.award_date,
            contract_notification_date=award.contract_notification_date,
            publication_date=event.published_on,
            source_system=event.source_system,
            source_notice_id=event.source_notice_id,
            evidence_refs=tuple(sorted(refs)),
        ),
    )
