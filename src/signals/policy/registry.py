"""Callable-free Kivou policy metadata for the SPEC-017 command registry."""

from dataclasses import dataclass
from enum import StrEnum


class RiskClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    PREPARATORY = "PREPARATORY"
    COMMERCIAL_MUTATION = "COMMERCIAL_MUTATION"
    RISK_REDUCTION = "RISK_REDUCTION"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class TargetScope(StrEnum):
    OPPORTUNITY = "OPPORTUNITY"
    GLOBAL = "GLOBAL"
    EITHER = "EITHER"


@dataclass(frozen=True)
class CommandPolicy:
    risk_class: RiskClass
    target_scope: TargetScope
    required_evidence: tuple[str, ...] = ()
    uses_budget: bool = False
    uses_volume: bool = False
    uses_send_controls: bool = False
    requires_control_plane: bool = False
    requires_compliance: bool = False


COMMAND_POLICIES = {
    "discover_suppliers": CommandPolicy(
        RiskClass.PREPARATORY, TargetScope.OPPORTUNITY, ("SIGNAL", "PUBLIC_EVIDENCE"), True
    ),
    "find_decision_makers": CommandPolicy(
        RiskClass.PREPARATORY, TargetScope.OPPORTUNITY, ("SUPPLIER",), True
    ),
    "enrich_company": CommandPolicy(
        RiskClass.PREPARATORY, TargetScope.OPPORTUNITY, ("SUPPLIER",), True
    ),
    "evaluate_opportunity": CommandPolicy(
        RiskClass.PREPARATORY, TargetScope.OPPORTUNITY, ("SIGNAL", "PUBLIC_EVIDENCE")
    ),
    "prepare_campaign": CommandPolicy(
        RiskClass.COMMERCIAL_MUTATION,
        TargetScope.OPPORTUNITY,
        ("VERIFIED_CONTACT", "FIT_DECISION", "RECENT_SIGNAL"),
    ),
    "schedule_campaign": CommandPolicy(
        RiskClass.COMMERCIAL_MUTATION,
        TargetScope.OPPORTUNITY,
        ("VERIFIED_CONTACT", "FIT_DECISION", "RECENT_SIGNAL"),
        True,
        True,
        True,
        True,
        requires_compliance=True,
    ),
    "pause_campaign": CommandPolicy(
        RiskClass.RISK_REDUCTION, TargetScope.EITHER, requires_control_plane=True
    ),
    "classify_response": CommandPolicy(
        RiskClass.PREPARATORY, TargetScope.OPPORTUNITY, ("RESPONSE",)
    ),
    "reallocate_volume": CommandPolicy(
        RiskClass.COMMERCIAL_MUTATION,
        TargetScope.GLOBAL,
        uses_budget=True,
        uses_volume=True,
        uses_send_controls=True,
    ),
    "request_human_review": CommandPolicy(RiskClass.HUMAN_REVIEW, TargetScope.EITHER),
    "generate_weekly_report": CommandPolicy(RiskClass.READ_ONLY, TargetScope.GLOBAL),
}
