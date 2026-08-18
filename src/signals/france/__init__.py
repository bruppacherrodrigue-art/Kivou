"""France — rapprochement BOAMP × DECP."""

from signals.france.capacity import (
    IdentityBreakdown,
    LinkageAggregate,
    UniqueContractCount,
    customer_ready_breakdown,
    unique_contract_count,
)
from signals.france.link import (
    FIELD_PRIORITY,
    FRANCE_LINK_POLICY_VERSION,
    INDEPENDENT_CORROBORATORS,
    NOTIFICATION_TOLERANCE_DAYS,
    FieldConflict,
    LinkCandidate,
    MatchStrength,
    MergedFrenchAward,
    merge_award,
    resolve_candidates,
    unique_strong,
)

__all__ = [
    "FIELD_PRIORITY",
    "FRANCE_LINK_POLICY_VERSION",
    "INDEPENDENT_CORROBORATORS",
    "NOTIFICATION_TOLERANCE_DAYS",
    "FieldConflict",
    "IdentityBreakdown",
    "LinkCandidate",
    "LinkageAggregate",
    "MatchStrength",
    "MergedFrenchAward",
    "UniqueContractCount",
    "customer_ready_breakdown",
    "merge_award",
    "resolve_candidates",
    "unique_contract_count",
    "unique_strong",
]
