"""Deterministic capability availability owned by Kivou, never by Hermes."""

from __future__ import annotations

from dataclasses import dataclass

from signals.chief_of_staff.contracts import (
    CAPABILITY_ORDER,
    Capability,
    CapabilityAvailability,
    ChiefOfStaffFact,
    Domain,
)


@dataclass(frozen=True)
class CapabilityRequirement:
    capability: Capability
    domain: Domain | None
    source_contract: str | None


CAPABILITY_REQUIREMENTS: tuple[CapabilityRequirement, ...] = (
    CapabilityRequirement("BUSINESS_REVIEW", "BUSINESS", "WeeklyCommercialCockpit"),
    CapabilityRequirement("PRODUCT_JOURNEY_REVIEW", None, None),
    CapabilityRequirement("DATA_HEALTH_REVIEW", "DATA", "CockpitDataQuality"),
    CapabilityRequirement(
        "OPERATIONS_REVIEW", "OPERATIONS", "AcquisitionOperationalHealth"
    ),
    CapabilityRequirement(
        "ACQUISITION_REVIEW", "ACQUISITION", "FounderAcquisitionStatus"
    ),
    CapabilityRequirement("ROADMAP_RELEASE_REVIEW", None, None),
    CapabilityRequirement("STRATEGIC_SYNTHESIS", None, None),
)

_SYNTHESIS_INPUTS = (
    "BUSINESS_REVIEW",
    "DATA_HEALTH_REVIEW",
    "OPERATIONS_REVIEW",
    "ACQUISITION_REVIEW",
)


def evaluate_capabilities(
    facts: tuple[ChiefOfStaffFact, ...],
) -> tuple[CapabilityAvailability, ...]:
    """Evaluate the fixed V1 matrix from structured source evidence only."""

    statuses: list[CapabilityAvailability] = []
    by_capability: dict[Capability, CapabilityAvailability] = {}
    for requirement in CAPABILITY_REQUIREMENTS:
        if requirement.capability == "STRATEGIC_SYNTHESIS":
            inputs = tuple(by_capability[name] for name in _SYNTHESIS_INPUTS)
            available = all(item.status == "AVAILABLE" for item in inputs)
            value = CapabilityAvailability(
                capability=requirement.capability,
                status="AVAILABLE" if available else "INSUFFICIENT_EVIDENCE",
                reason_codes=(
                    "REQUIRED_SOURCES_PRESENT"
                    if available
                    else "REQUIRED_CAPABILITY_UNAVAILABLE",
                ),
                fact_refs=(
                    tuple(sorted({ref for item in inputs for ref in item.fact_refs}))
                    if available
                    else ()
                ),
            )
        elif requirement.domain is None or requirement.source_contract is None:
            value = CapabilityAvailability(
                capability=requirement.capability,
                status="UNAVAILABLE",
                reason_codes=("READ_MODEL_UNAVAILABLE",),
                fact_refs=(),
            )
        else:
            matching = tuple(
                sorted(
                    (
                        fact
                        for fact in facts
                        if fact.domain == requirement.domain
                        and fact.source_contract == requirement.source_contract
                    ),
                    key=lambda item: item.fact_ref,
                )
            )
            evidenced = tuple(
                fact for fact in matching if fact.data_status in {"KNOWN", "STALE"}
            )
            if evidenced:
                value = CapabilityAvailability(
                    capability=requirement.capability,
                    status="AVAILABLE",
                    reason_codes=("REQUIRED_SOURCES_PRESENT",),
                    fact_refs=tuple(fact.fact_ref for fact in evidenced),
                )
            else:
                value = CapabilityAvailability(
                    capability=requirement.capability,
                    status="INSUFFICIENT_EVIDENCE",
                    reason_codes=(
                        "REQUIRED_EVIDENCE_NOT_KNOWN"
                        if matching
                        else "REQUIRED_SOURCE_MISSING",
                    ),
                    fact_refs=tuple(fact.fact_ref for fact in matching),
                )
        statuses.append(value)
        by_capability[requirement.capability] = value
    result = tuple(statuses)
    if tuple(item.capability for item in result) != CAPABILITY_ORDER:
        raise RuntimeError("capability matrix is not in canonical order")
    return result


__all__ = [
    "CAPABILITY_REQUIREMENTS",
    "CapabilityRequirement",
    "evaluate_capabilities",
]
