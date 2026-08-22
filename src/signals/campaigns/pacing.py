"""Pure Kivou-owned pacing calculations."""

from signals.campaigns.contracts import PacingPolicy


def effective_capacity(policy: PacingPolicy, *, provider_daily_limit: int) -> int:
    if provider_daily_limit < 0:
        raise ValueError("provider_daily_limit cannot be negative")
    return min(
        policy.global_daily_cap,
        policy.country_daily_cap,
        policy.wedge_daily_cap,
        policy.mailbox_daily_cap,
        provider_daily_limit,
    )
