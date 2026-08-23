"""One deterministic attribution-source contract for issuance and verification."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa

from signals.conversion.contracts import AttributionTokenPayload
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_opportunity,
)
from signals.supplier_discovery.seed import AcquisitionSeedNotFound, resolve_acquisition_seed


class AttributionSourceUnavailable(ValueError):
    code = "invalid_attribution_binding"


@dataclass(frozen=True)
class AttributionSourceFacts:
    campaign_ref: str
    member_ref: str
    acquisition_opportunity_id: str
    signal_ref: str
    country: str
    wedge: str
    wedge_version: str
    need_ref: str
    need_version: str
    timezone: str
    step_1_execution_date: dt.date
    step_2_authorization_deadline: dt.datetime


class AttributionSourceResolver:
    """Reconstruct the complete hidden HMAC payload from Kivou-owned facts."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def from_facts(self, facts: AttributionSourceFacts) -> AttributionTokenPayload:
        try:
            issued_at = dt.datetime.combine(
                facts.step_1_execution_date,
                dt.time(9),
                tzinfo=ZoneInfo(facts.timezone),
            ).astimezone(dt.UTC)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise AttributionSourceUnavailable("invalid attribution sequence window") from error
        deadline = facts.step_2_authorization_deadline
        deadline = (
            deadline.replace(tzinfo=dt.UTC)
            if deadline.tzinfo is None
            else deadline.astimezone(dt.UTC)
        )
        return AttributionTokenPayload(
            campaign_ref=facts.campaign_ref,
            member_ref=facts.member_ref,
            acquisition_opportunity_id=facts.acquisition_opportunity_id,
            wedge=facts.wedge,
            wedge_version=facts.wedge_version,
            country=facts.country,
            sector_ref=self.sector_ref_for_signal(facts.signal_ref),
            need_ref=facts.need_ref,
            need_version=facts.need_version,
            issued_at=issued_at,
            expires_at=deadline + dt.timedelta(days=30),
        )

    def for_member(
        self, connection: sa.Connection, member_ref: str
    ) -> AttributionTokenPayload:
        row = connection.execute(
            sa.select(
                acquisition_campaign.c.campaign_ref,
                acquisition_campaign.c.country,
                acquisition_campaign.c.wedge,
                acquisition_campaign.c.wedge_version,
                acquisition_campaign.c.selected_need_category,
                acquisition_campaign.c.selected_need_version,
                acquisition_campaign.c.timezone,
                acquisition_campaign.c.step_1_execution_date,
                acquisition_campaign.c.step_2_authorization_deadline,
                acquisition_campaign_member.c.member_ref,
                acquisition_campaign_member.c.acquisition_opportunity_id,
                acquisition_opportunity.c.signal_ref,
            )
            .select_from(
                acquisition_campaign_member.join(
                    acquisition_campaign,
                    acquisition_campaign.c.campaign_ref
                    == acquisition_campaign_member.c.campaign_ref,
                ).join(
                    acquisition_opportunity,
                    acquisition_opportunity.c.acquisition_opportunity_id
                    == acquisition_campaign_member.c.acquisition_opportunity_id,
                )
            )
            .where(acquisition_campaign_member.c.member_ref == member_ref)
        ).mappings().one_or_none()
        if row is None:
            raise AttributionSourceUnavailable("attribution member is unavailable")
        step_1_date = row["step_1_execution_date"]
        deadline = row["step_2_authorization_deadline"]
        if not isinstance(step_1_date, dt.date) or not isinstance(deadline, dt.datetime):
            raise AttributionSourceUnavailable("attribution sequence window is unavailable")
        return self.from_facts(
            AttributionSourceFacts(
                campaign_ref=row["campaign_ref"],
                member_ref=row["member_ref"],
                acquisition_opportunity_id=row["acquisition_opportunity_id"],
                signal_ref=row["signal_ref"],
                country=row["country"],
                wedge=row["wedge"],
                wedge_version=row["wedge_version"],
                need_ref=row["selected_need_category"],
                need_version=row["selected_need_version"],
                timezone=row["timezone"],
                step_1_execution_date=step_1_date,
                step_2_authorization_deadline=deadline,
            )
        )

    def sector_ref_for_signal(self, signal_ref: str) -> str:
        """Return the shared deterministic sector identity used by attribution readers."""
        prefix = "procurement-opportunity:"
        if not signal_ref.startswith(prefix):
            return "sector-unknown-v1"
        try:
            seed = resolve_acquisition_seed(self._engine, signal_ref.removeprefix(prefix))
        except AcquisitionSeedNotFound:
            return "sector-unknown-v1"
        return semantic_fingerprint(
            {
                "kind": "conversion-sector-ref-v1",
                "sector_code": seed.understanding.sector.value,
                "inference_version": seed.understanding.engine_version,
            }
        )


__all__ = [
    "AttributionSourceFacts",
    "AttributionSourceResolver",
    "AttributionSourceUnavailable",
]
