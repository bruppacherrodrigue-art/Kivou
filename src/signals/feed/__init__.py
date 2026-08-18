"""Feed client — SPEC-012.

La lecture part du compte (`query`), la fraîcheur se réévalue au jour de la
lecture, et la mise en forme sépare les faits publiés des inférences (`view`).
"""

from signals.feed.policy import (
    DEFAULT_FRESHNESS,
    DEFAULT_PAGE_SIZE,
    FEED_POLICY_VERSION,
    FRESHNESS_MODES,
    MAXIMUM_PAGE_SIZE,
    NEW_OPPORTUNITY_STATUSES,
)
from signals.feed.query import (
    FeedPage,
    FeedSignal,
    ForeignTargetIcp,
    feed_page,
    is_customer_ready,
    owned_signal,
    owned_target_icps,
)
from signals.feed.view import feed_item, signal_detail

__all__ = [
    "DEFAULT_FRESHNESS",
    "DEFAULT_PAGE_SIZE",
    "FEED_POLICY_VERSION",
    "FRESHNESS_MODES",
    "MAXIMUM_PAGE_SIZE",
    "NEW_OPPORTUNITY_STATUSES",
    "FeedPage",
    "FeedSignal",
    "ForeignTargetIcp",
    "feed_item",
    "feed_page",
    "is_customer_ready",
    "owned_signal",
    "owned_target_icps",
    "signal_detail",
]
