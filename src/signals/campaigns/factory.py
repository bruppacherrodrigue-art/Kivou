"""Pure deterministic CampaignFactory and two-window calendar policy."""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from signals.campaigns.contracts import (
    CampaignFactoryInput,
    CampaignPlan,
    SequenceTimingInvariantViolation,
    SequenceWindow,
)
from signals.decision_engine.policy import semantic_fingerprint

_TIMEZONES = {"CH": "Europe/Zurich", "FR": "Europe/Paris"}


def _next_weekday(value: dt.date) -> dt.date:
    while value.weekday() >= 5:
        value += dt.timedelta(days=1)
    return value


def sequence_window(jurisdiction: str, step_1_execution_date: dt.date) -> SequenceWindow:
    if jurisdiction not in _TIMEZONES:
        raise ValueError("campaign jurisdiction must be CH or FR")
    if step_1_execution_date.weekday() >= 5:
        raise ValueError("step_1_execution_date must be a weekday")
    timezone = _TIMEZONES[jurisdiction]
    zone = ZoneInfo(timezone)
    step_2_execution_date = _next_weekday(step_1_execution_date + dt.timedelta(days=4))
    return SequenceWindow(
        timezone=timezone,
        step_1_execution_date=step_1_execution_date,
        step_1_authorization_deadline=dt.datetime.combine(
            step_1_execution_date, dt.time(17), zone
        ),
        step_2_execution_date=step_2_execution_date,
        step_2_authorization_deadline=dt.datetime.combine(
            step_2_execution_date, dt.time(17), zone
        ),
    )


class CampaignFactory:
    """Callable-free factory: explicit input in, immutable plan out."""

    def build(self, value: CampaignFactoryInput, *, batch_generation: int) -> CampaignPlan:
        if batch_generation < 1:
            raise ValueError("batch_generation must be positive")
        dimensions = value.model_dump(mode="json", exclude={"step_1_execution_date"})
        campaign_group_key = semantic_fingerprint(
            {"kind": "campaign-group-key-v1", **dimensions}
        )
        campaign_ref = semantic_fingerprint(
            {
                "kind": "campaign-ref-v1",
                "campaign_group_key": campaign_group_key,
                "batch_generation": batch_generation,
            }
        )
        safe_wedge = re.sub(r"[^a-z0-9]+", "-", value.wedge.casefold()).strip("-")[:24]
        provider_name = (
            f"KIVOU-{campaign_ref[:12]}-{value.country}-{value.language}-{safe_wedge}"
        )
        window = sequence_window(value.jurisdiction, value.step_1_execution_date)
        plan_values = {
            "campaign_group_key": campaign_group_key,
            "campaign_ref": campaign_ref,
            "batch_generation": batch_generation,
            "provider_campaign_name": provider_name,
            "country": value.country,
            "jurisdiction": value.jurisdiction,
            "language": value.language,
            "wedge": value.wedge,
            "selected_need_category": value.selected_need_category,
            "sender_profile_ref": value.sender_profile_ref,
            "compliance_ruleset_fingerprint": value.compliance_ruleset_fingerprint,
            "sequence_window": window,
        }
        fingerprint = semantic_fingerprint(
            {"kind": "campaign-plan-v1", **CampaignPlan(
                **plan_values, plan_fingerprint="0" * 64
            ).model_dump(mode="json", exclude={"plan_fingerprint"})}
        )
        return CampaignPlan(**plan_values, plan_fingerprint=fingerprint)


def materialize_step_2_timing(
    window: SequenceWindow, step_1_sent_at: dt.datetime
) -> dt.datetime:
    if step_1_sent_at.tzinfo is None or step_1_sent_at.utcoffset() is None:
        raise SequenceTimingInvariantViolation("step_1_sent_at must be timezone-aware")
    zone = ZoneInfo(window.timezone)
    local_sent = step_1_sent_at.astimezone(zone)
    if local_sent.date() != window.step_1_execution_date:
        raise SequenceTimingInvariantViolation("Step 1 was not sent on its authorized date")
    local_time = local_sent.timetz().replace(tzinfo=None)
    if not dt.time(9) <= local_time < dt.time(17):
        raise SequenceTimingInvariantViolation("Step 1 was not sent inside its authorized window")
    raw_date = local_sent.date() + dt.timedelta(days=4)
    if raw_date.weekday() >= 5:
        due = dt.datetime.combine(window.step_2_execution_date, dt.time(9), zone)
    else:
        due = dt.datetime.combine(window.step_2_execution_date, local_time, zone)
    if (
        due.date() != window.step_2_execution_date
        or due >= window.step_2_authorization_deadline
    ):
        raise SequenceTimingInvariantViolation("materialized Step 2 timing escaped authorization")
    return due


def sequence_timing_fingerprint(
    *,
    sequence_authorization_fingerprint: str,
    step_1_sent_at: dt.datetime,
    step_2_due_at: dt.datetime,
    step_2_authorization_deadline: dt.datetime,
) -> str:
    return semantic_fingerprint(
        {
            "kind": "sequence-timing-v1",
            "sequence_authorization_fingerprint": sequence_authorization_fingerprint,
            "step_1_sent_at": step_1_sent_at.astimezone(dt.UTC).isoformat(),
            "step_2_due_at": step_2_due_at.astimezone(dt.UTC).isoformat(),
            "step_2_authorization_deadline": (
                step_2_authorization_deadline.astimezone(dt.UTC).isoformat()
            ),
        }
    )
