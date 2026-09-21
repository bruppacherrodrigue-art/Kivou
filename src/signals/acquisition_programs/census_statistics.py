"""Aggregate A1 organization sampling, without contact or address data."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.census import CensusStore
from signals.acquisition_programs.census_sampling import wilson_interval
from signals.persistence.schema import (
    acquisition_census_call,
    acquisition_census_company_match,
    acquisition_census_sample_page,
)
from signals.supplier_discovery.contracts import SupplierSearchPage


def _estimate(population: int, rate: float, low: float, high: float) -> dict[str, int]:
    return {"low": round(population * low), "central": round(population * rate),
            "high": round(population * high)}


def sample_report(engine: Engine, census_id: str, permit_id: str) -> dict[str, Any]:
    """Keep Apollo totals, page observations and weighted estimates separate."""
    store = CensusStore(engine)
    funnel = store.report(census_id)
    partitions = {row["partition_id"]: row for row in store.partitions(census_id)}
    candidates = store.candidates(census_id)
    by_id = {row["provider_organization_id"]: row for row in candidates}
    with engine.connect() as connection:
        selected = connection.execute(sa.select(acquisition_census_sample_page).where(
            acquisition_census_sample_page.c.plan_id == permit_id,
        )).mappings().all()
        calls = connection.execute(sa.select(acquisition_census_call).where(
            acquisition_census_call.c.census_id == census_id,
            acquisition_census_call.c.kind == "ORG_SEARCH",
        )).mappings().all()
        legal = {row["provider_organization_id"]: row["match_evidence"] for row in
                 connection.execute(sa.select(acquisition_census_company_match).where(
                     acquisition_census_company_match.c.census_id == census_id,
                 )).mappings()}
    page_calls = [row for row in calls if row["status"] == "COMPLETED" and
                  row["result_snapshot"]]
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    page_depth: Counter[str] = Counter()
    for call in page_calls:
        partition_id = call["partition_id"]
        if partition_id not in partitions:
            continue
        page = SupplierSearchPage.model_validate(call["result_snapshot"])
        page_depth["FIRST" if page.page == 1 else "DEEP"] += 1
        for candidate in page.candidates:
            measured = by_id.get(candidate.provider_organization_id)
            if measured is None:
                continue
            observation = {
                "id": candidate.provider_organization_id,
                "google": measured["provider"] == "GOOGLE_WORKSPACE" and
                measured["provider_confidence"] == "CONFIRMED",
                "valid": bool(measured["primary_domain"]),
                "active": legal.get(candidate.provider_organization_id, {}).get(
                    "legal_status") == "ACTIVE" and legal.get(
                    candidate.provider_organization_id, {}).get(
                    "match_confidence") == "CONFIRMED_MATCH",
                "page": page.page,
            }
            observations[partition_id].append(observation)
    declared = sum(int(row["estimated_result_count"] or 0) for row in partitions.values())
    accessible_declared = sum(min(int(row["estimated_result_count"] or 0),
                                  500 * int(row["filters"]["per_page"]))
                              for row in partitions.values())
    strata: dict[str, dict[str, Any]] = {}
    weighted_google = weighted_low = weighted_high = 0.0
    weighted_active = weighted_active_low = weighted_active_high = 0.0
    sector: dict[str, Counter[str]] = defaultdict(Counter)
    size: dict[str, Counter[str]] = defaultdict(Counter)
    depth: dict[str, Counter[str]] = defaultdict(Counter)
    for partition_id, part in partitions.items():
        values = observations[partition_id]
        n = len(values)
        gw = sum(item["google"] for item in values)
        active = sum(item["google"] and item["active"] for item in values)
        gw_low, gw_high = wilson_interval(gw, n)
        act_low, act_high = wilson_interval(active, n)
        rate = gw / n if n else 0
        active_rate = active / n if n else 0
        weight = (int(part["estimated_result_count"] or 0) / declared) if declared else 0
        weighted_google += weight * rate
        weighted_low += weight * gw_low
        weighted_high += weight * gw_high
        weighted_active += weight * active_rate
        weighted_active_low += weight * act_low
        weighted_active_high += weight * act_high
        label = f"{part['size_min']}-{part['size_max']}"
        for bucket in (sector[part["sector"]], size[label]):
            bucket["observed"] += n
            bucket["google"] += gw
        for item in values:
            bucket = depth["FIRST" if item["page"] == 1 else "DEEP"]
            bucket["observed"] += 1
            bucket["google"] += int(item["google"])
        strata[partition_id] = {
            "sector": part["sector"], "size": label,
            "apollo_declared_total": part["estimated_result_count"],
            "observed": n, "google_workspace": gw,
            "google_rate": rate, "google_wilson_95": [gw_low, gw_high],
            "confirmed_active_google": active,
            "active_google_wilson_95": [act_low, act_high],
            "population_weight": weight,
            "accessible_pages": min(500, (int(part["estimated_result_count"] or 0) + 24) // 25),
        }
    observed = sum(len(values) for values in observations.values())
    unique = len({row["candidate_id"] for row in candidates})
    duplicates = max(0, observed - unique)
    valid = sum(item["valid"] for values in observations.values() for item in values)
    google = sum(item["google"] for values in observations.values() for item in values)
    active_google = sum(item["google"] and item["active"]
                        for values in observations.values() for item in values)
    verified_google_unique = [row for row in candidates if
                              row["provider"] == "GOOGLE_WORKSPACE" and
                              row["provider_confidence"] == "CONFIRMED" and
                              row["provider_organization_id"] in legal]
    active_google_unique = sum(
        legal[row["provider_organization_id"]]["legal_status"] == "ACTIVE" and
        legal[row["provider_organization_id"]]["match_confidence"] == "CONFIRMED_MATCH"
        for row in verified_google_unique
    )
    low_unique, high_unique = wilson_interval(max(0, observed - duplicates), observed)
    unique_rate = unique / observed if observed else 0
    unique_population = _estimate(declared, unique_rate, low_unique, high_unique)
    official_statuses = Counter(item["legal_status"] for item in legal.values())
    official_matches = Counter(item["match_confidence"] for item in legal.values())

    def aggregate_rates(buckets: dict[str, Counter[str]]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for key, bucket in sorted(buckets.items()):
            n, k = bucket["observed"], bucket["google"]
            output[key] = {"observed": n, "google_workspace": k,
                           "rate": k / n if n else None,
                           "wilson_95": wilson_interval(k, n)}
        return output

    return {
        "census_id": census_id, "permit_id": permit_id,
        "phase": "COVERAGE_A1_SAMPLE", "apollo_declared_total_sum": declared,
        "apollo_accessible_declared_max": accessible_declared,
        "apollo_inaccessible_declared_min": max(0, declared - accessible_declared),
        "organizations_observed": observed, "organizations_unique_observed": unique,
        "cross_partition_duplicate_occurrences": duplicates,
        "valid_domains_observed": valid,
        "valid_domain_rate": valid / observed if observed else None,
        "valid_domain_wilson_95": wilson_interval(valid, observed),
        "duplicate_rate": duplicates / observed if observed else None,
        "duplicate_wilson_95": wilson_interval(duplicates, observed),
        "google_workspace_observed": google,
        "google_workspace_observed_rate": google / observed if observed else None,
        "confirmed_active_google_observed": active_google,
        "confirmed_active_google_unique": active_google_unique,
        "official_legal_status": dict(sorted(official_statuses.items())),
        "official_match_confidence": dict(sorted(official_matches.items())),
        "confirmed_active_given_google_verified": (
            active_google_unique / len(verified_google_unique)
            if verified_google_unique else None
        ),
        "weighted_google_rate": weighted_google if declared else None,
        "weighted_google_interval_95_approx": [weighted_low, weighted_high],
        "weighted_active_google_rate": weighted_active if declared else None,
        "weighted_active_google_interval_95_approx":
            [weighted_active_low, weighted_active_high],
        "estimated_unique_organizations": unique_population,
        "estimated_google_workspace_organizations": _estimate(
            declared, weighted_google * unique_rate,
            weighted_low * low_unique, weighted_high * high_unique,
        ),
        "estimated_confirmed_active_google_organizations": _estimate(
            declared, weighted_active * unique_rate,
            weighted_active_low * low_unique, weighted_active_high * high_unique,
        ),
        "by_partition": strata,
        "by_sector": aggregate_rates(sector),
        "by_size": aggregate_rates(size),
        "by_depth": aggregate_rates(depth),
        "pages_completed": len(page_calls), "pages_a1_planned": len(selected),
        "pages_a1_completed": sum(row["status"] == "COMPLETED" for row in selected),
        "pages_a1_remaining": sum(row["status"] != "COMPLETED" for row in selected),
        "apollo_search_calls_new": sum(row["permit_id"] == permit_id for row in page_calls),
        "apollo_search_attempts_new": sum(row["permit_id"] == permit_id for row in calls),
        "apollo_search_failed_or_review_new": sum(
            row["permit_id"] == permit_id and row["status"] != "COMPLETED" for row in calls
        ),
        "official_requests_cumulative": store.status(census_id)["official_requests_reserved"],
        "contacts_found": funnel["contacts_found"],
        "leaders_identified": funnel["leaders_identified"],
        "email_addresses_verified": funnel["verified_addresses_unique"],
        "instantly_mutations": 0, "emails_sent": 0,
        "estimate_method": "DECLARED_PARTITION_TOTALS_TIMES_STRATIFIED_PAGE_RATES_AND_OBSERVED_DEDUP_RATIO",
        "limits": [
            ("Wilson intervals treat sampled organization observations as independent; "
             "Apollo ranking and overlap may violate this assumption"),
            "Declared partition totals overlap and each search exposes at most 500 pages",
            "No contact or address availability can be inferred from organization counts",
        ],
    }
