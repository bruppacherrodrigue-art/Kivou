"""Politique de fraîcheur d'attribution — SPEC-009E."""

from signals.recency.policy import (
    AGING_AWARD_DAYS,
    CLAIMABLE_JUST_WON,
    CLOCKS,
    IMPLAUSIBLE_AWARD_AGE_DAYS,
    PUBLICATION_TOLERANCE_DAYS,
    RECENCY_POLICY_VERSION,
    RECENT_AWARD_DAYS,
    RECENT_NOTIFICATION_DAYS,
    RECENT_PUBLICATION_DAYS,
    AwardRecency,
    AwardRecencyStatus,
    ClockAssessment,
    ClockStatus,
    assess_recency,
)

__all__ = [
    "AGING_AWARD_DAYS",
    "CLAIMABLE_JUST_WON",
    "CLOCKS",
    "IMPLAUSIBLE_AWARD_AGE_DAYS",
    "PUBLICATION_TOLERANCE_DAYS",
    "RECENCY_POLICY_VERSION",
    "RECENT_AWARD_DAYS",
    "RECENT_NOTIFICATION_DAYS",
    "RECENT_PUBLICATION_DAYS",
    "AwardRecency",
    "AwardRecencyStatus",
    "ClockAssessment",
    "ClockStatus",
    "assess_recency",
]
