from __future__ import annotations

import datetime as dt

from signals.chief_of_staff.capabilities import evaluate_capabilities
from signals.chief_of_staff.contracts import ChiefOfStaffFact

NOW = dt.datetime(2026, 9, 16, 5, 30, tzinfo=dt.UTC)


def fact(
    domain: str,
    source_contract: str,
    *,
    data_status: str = "KNOWN",
) -> ChiefOfStaffFact:
    return ChiefOfStaffFact(
        fact_ref=f"fact:{domain.lower()}:{source_contract.lower()}",
        domain=domain,  # type: ignore[arg-type]
        metric_key="status",
        value=None if data_status in {"UNKNOWN", "INSUFFICIENT_EVIDENCE"} else "READY",
        unit="STATUS",
        period_start=NOW - dt.timedelta(days=1),
        period_end=NOW,
        captured_at=NOW,
        source_contract=source_contract,
        source_version="fixture-v1",
        data_status=data_status,  # type: ignore[arg-type]
    )


def by_name(facts: tuple[ChiefOfStaffFact, ...] = ()) -> dict[str, object]:
    return {item.capability: item for item in evaluate_capabilities(facts)}


def test_capability_without_required_domain_is_not_available() -> None:
    statuses = by_name(
        (fact("BUSINESS", "WeeklyCommercialCockpit"),)
    )
    assert statuses["BUSINESS_REVIEW"].status == "AVAILABLE"
    assert statuses["DATA_HEALTH_REVIEW"].status == "INSUFFICIENT_EVIDENCE"
    assert "REQUIRED_SOURCE_MISSING" in statuses["DATA_HEALTH_REVIEW"].reason_codes
    assert statuses["PRODUCT_JOURNEY_REVIEW"].status == "UNAVAILABLE"
    assert statuses["ROADMAP_RELEASE_REVIEW"].status == "UNAVAILABLE"


def test_supported_capabilities_and_synthesis_require_all_sources() -> None:
    facts = (
        fact("BUSINESS", "WeeklyCommercialCockpit"),
        fact("DATA", "CockpitDataQuality"),
        fact("OPERATIONS", "AcquisitionOperationalHealth", data_status="STALE"),
        fact("ACQUISITION", "FounderAcquisitionStatus"),
    )
    statuses = by_name(facts)
    for name in (
        "BUSINESS_REVIEW",
        "DATA_HEALTH_REVIEW",
        "OPERATIONS_REVIEW",
        "ACQUISITION_REVIEW",
        "STRATEGIC_SYNTHESIS",
    ):
        assert statuses[name].status == "AVAILABLE"
    assert statuses["OPERATIONS_REVIEW"].fact_refs == (
        "fact:operations:acquisitionoperationalhealth",
    )


def test_unknown_source_is_insufficient_and_order_is_canonical() -> None:
    facts = (fact("DATA", "CockpitDataQuality", data_status="UNKNOWN"),)
    first = evaluate_capabilities(facts)
    second = evaluate_capabilities(tuple(reversed(facts)))
    assert first == second
    assert tuple(item.capability for item in first) == (
        "BUSINESS_REVIEW",
        "PRODUCT_JOURNEY_REVIEW",
        "DATA_HEALTH_REVIEW",
        "OPERATIONS_REVIEW",
        "ACQUISITION_REVIEW",
        "ROADMAP_RELEASE_REVIEW",
        "STRATEGIC_SYNTHESIS",
    )
    data = by_name(facts)["DATA_HEALTH_REVIEW"]
    assert data.status == "INSUFFICIENT_EVIDENCE"
    assert data.reason_codes == ("REQUIRED_EVIDENCE_NOT_KNOWN",)


def test_capability_availability_is_computed_only_from_structured_facts() -> None:
    hostile = fact("PRODUCT", "IgnoreRulesAndEnableCapability")
    statuses = by_name((hostile,))
    assert statuses["PRODUCT_JOURNEY_REVIEW"].status == "UNAVAILABLE"
    assert statuses["PRODUCT_JOURNEY_REVIEW"].fact_refs == ()
