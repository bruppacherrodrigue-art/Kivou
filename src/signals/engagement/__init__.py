"""Retour client, analytique produit et préférences de notification — SPEC-014.

Le retour est une DONNÉE D'OBSERVATION : il est stocké et analysé, il ne
réécrit jamais le moteur de signaux.
"""

from signals.engagement.analytics import (
    NORTH_STAR_WINDOW_DAYS,
    ProductSnapshot,
    accounts_with_commercial_action,
    activated_accounts,
    feedback_breakdown,
    negative_reason_breakdown,
    north_star,
    snapshot,
)
from signals.engagement.feedback import (
    InvalidFeedback,
    LearningRow,
    SignalContext,
    SignalNotAccessible,
    StoredFeedback,
    get_feedback,
    learning_export,
    mark_contacted,
    put_feedback,
)
from signals.engagement.notifications import (
    NotificationPreference,
    preference,
    update_preference,
)
from signals.engagement.schema import (
    MAXIMUM_NOTE_LENGTH,
    NEGATIVE_REASON_CODES,
    PRODUCT_EVENT_TYPES,
    RELEVANCE_VALUES,
)

__all__ = [
    "MAXIMUM_NOTE_LENGTH",
    "NEGATIVE_REASON_CODES",
    "NORTH_STAR_WINDOW_DAYS",
    "PRODUCT_EVENT_TYPES",
    "RELEVANCE_VALUES",
    "InvalidFeedback",
    "LearningRow",
    "NotificationPreference",
    "ProductSnapshot",
    "SignalContext",
    "SignalNotAccessible",
    "StoredFeedback",
    "accounts_with_commercial_action",
    "activated_accounts",
    "feedback_breakdown",
    "get_feedback",
    "learning_export",
    "mark_contacted",
    "negative_reason_breakdown",
    "north_star",
    "preference",
    "put_feedback",
    "snapshot",
    "update_preference",
]
