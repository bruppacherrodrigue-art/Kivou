"""Kivou-owned command declarations; deliberately no executable callables."""

from __future__ import annotations

ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "discover_suppliers",
        "find_decision_makers",
        "enrich_company",
        "evaluate_opportunity",
        "prepare_campaign",
        "assess_campaign_compliance",
        "schedule_campaign",
        "pause_campaign",
        "classify_response",
        "reallocate_volume",
        "request_human_review",
        "generate_weekly_report",
    }
)

ALLOWED_NEXT_ACTIONS: frozenset[str] = ALLOWED_COMMANDS

DECISION_VOCABULARY: frozenset[str] = frozenset(
    {"SEND", "HOLD", "ENRICH", "NO_SEND", "REVIEW"}
)
