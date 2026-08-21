"""Deterministic, local acquisition-email compliance domain."""

from signals.compliance.contracts import (
    ComplianceInput,
    ComplianceJurisdiction,
    ComplianceProposal,
    SenderComplianceConfig,
)
from signals.compliance.rules import RULESET_V1, evaluate_compliance

__all__ = [
    "RULESET_V1",
    "ComplianceInput",
    "ComplianceJurisdiction",
    "ComplianceProposal",
    "SenderComplianceConfig",
    "evaluate_compliance",
]
