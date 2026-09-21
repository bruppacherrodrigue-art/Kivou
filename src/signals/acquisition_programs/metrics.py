"""Program, wedge, and campaign counters over existing immutable Kivou records."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Engine, RowMapping

from signals.persistence.schema import (
    acquisition_event,
    acquisition_program,
    acquisition_program_attribution,
    acquisition_program_conversion_receipt,
    acquisition_program_eligibility,
)


@dataclass(frozen=True)
class ProgramMetrics:
    program_id: str
    wedge_key: str | None
    campaign_ref: str | None
    prospects_studied: int
    decision_counts: dict[str, int]
    reason_counts: dict[str, int]
    provider_counts: dict[str, int]
    wedge_counts: dict[str, int]
    conversion_counts: dict[str, int]
    provider_event_counts: dict[str, int]
    paid_count: int
    mrr_chf: Decimal | None
    mrr_known: bool
    unknown_provider_rate: Decimal | None
    bounce_rate: Decimal | None
    reply_rate: Decimal | None
    cost_per_studied_chf: Decimal | None
    cost_per_contacted_chf: Decimal | None


def read_program_metrics(
    engine: Engine,
    *,
    program_id: str,
    wedge_key: str | None = None,
    campaign_ref: str | None = None,
) -> ProgramMetrics:
    with engine.connect() as connection:
        program = connection.execute(
            sa.select(acquisition_program.c.program_id).where(
                acquisition_program.c.program_id == program_id
            )
        ).scalar_one_or_none()
        if program is None:
            raise ValueError("unknown acquisition program")
        eligibility = sa.select(acquisition_program_eligibility).where(
            acquisition_program_eligibility.c.program_id == program_id
        )
        rows = connection.execute(eligibility).mappings().all()
        latest: dict[str, RowMapping] = {}
        for row in rows:
            opportunity_id = row["acquisition_opportunity_id"]
            prior = latest.get(opportunity_id)
            if prior is None or (row["evaluated_at"], row["eligibility_id"]) > (
                prior["evaluated_at"],
                prior["eligibility_id"],
            ):
                latest[opportunity_id] = row
        if wedge_key is not None:
            latest = {
                key: value for key, value in latest.items() if value["wedge_key"] == wedge_key
            }
        if campaign_ref is not None:
            campaign_opportunities = set(
                connection.execute(
                    sa.select(acquisition_program_attribution.c.acquisition_opportunity_id).where(
                        acquisition_program_attribution.c.program_id == program_id,
                        acquisition_program_attribution.c.campaign_ref == campaign_ref,
                    )
                ).scalars()
            )
            latest = {key: value for key, value in latest.items() if key in campaign_opportunities}
        opportunity_ids = tuple(latest)
        decisions: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        providers: Counter[str] = Counter()
        wedges: Counter[str] = Counter()
        for row in latest.values():
            decisions[row["decision"]] += 1
            reasons.update(row["reason_codes"])
            providers[row["mail_provider"]] += 1
            if row["wedge_key"] is not None:
                wedges[row["wedge_key"]] += 1

        conversions: Counter[str] = Counter()
        provider_events: Counter[str] = Counter()
        paid_mrr: list[Decimal | None] = []
        if opportunity_ids:
            conversion_rows = connection.execute(
                sa.select(
                    acquisition_program_conversion_receipt.c.event_type,
                    acquisition_event.c.payload,
                )
                .join(
                    acquisition_program_attribution,
                    acquisition_program_conversion_receipt.c.attribution_id
                    == acquisition_program_attribution.c.attribution_id,
                )
                .join(
                    acquisition_event,
                    acquisition_program_conversion_receipt.c.recorded_event_id
                    == acquisition_event.c.event_id,
                )
                .where(
                    acquisition_program_conversion_receipt.c.program_id == program_id,
                    acquisition_program_attribution.c.acquisition_opportunity_id.in_(
                        opportunity_ids
                    ),
                    *(
                        (acquisition_program_attribution.c.campaign_ref == campaign_ref,)
                        if campaign_ref is not None
                        else ()
                    ),
                )
            ).all()
            for event_type, payload in conversion_rows:
                conversions[event_type] += 1
                if event_type == "milo_clean_paid":
                    paid_mrr.append(
                        Decimal(payload["mrr_chf"]) if payload.get("mrr_chf") is not None else None
                    )
            provider_rows = connection.execute(
                sa.select(acquisition_event.c.payload).where(
                    acquisition_event.c.acquisition_opportunity_id.in_(opportunity_ids),
                    acquisition_event.c.policy_version == "milomail-provider-event-v1",
                )
            ).scalars()
            for payload in provider_rows:
                if payload.get("program_id") == program_id and (
                    campaign_ref is None or payload.get("campaign_ref") == campaign_ref
                ):
                    provider_events[payload["event_type"]] += 1
        studied = len(latest)
        sent = provider_events["email_sent"]
        mrr_known = bool(paid_mrr) and all(value is not None for value in paid_mrr)
        return ProgramMetrics(
            program_id=program_id,
            wedge_key=wedge_key,
            campaign_ref=campaign_ref,
            prospects_studied=studied,
            decision_counts=dict(sorted(decisions.items())),
            reason_counts=dict(sorted(reasons.items())),
            provider_counts=dict(sorted(providers.items())),
            wedge_counts=dict(sorted(wedges.items())),
            conversion_counts=dict(sorted(conversions.items())),
            provider_event_counts=dict(sorted(provider_events.items())),
            paid_count=conversions["milo_clean_paid"],
            mrr_chf=sum((value for value in paid_mrr if value is not None), Decimal(0))
            if mrr_known
            else None,
            mrr_known=mrr_known,
            unknown_provider_rate=Decimal(providers["UNKNOWN"]) / Decimal(studied)
            if studied
            else None,
            bounce_rate=Decimal(provider_events["email_bounced"]) / Decimal(sent) if sent else None,
            reply_rate=Decimal(provider_events["reply_received"]) / Decimal(sent) if sent else None,
            # No real provider calls or sends exist in SHADOW. Missing cost
            # observations remain unknown rather than an invented zero.
            cost_per_studied_chf=None,
            cost_per_contacted_chf=None,
        )


__all__ = ["ProgramMetrics", "read_program_metrics"]
