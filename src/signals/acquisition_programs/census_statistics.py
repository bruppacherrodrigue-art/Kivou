"""Aggregate A1 organization sampling, without contact or address data."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.census import CensusStore
from signals.acquisition_programs.census_sampling import wilson_interval
from signals.acquisition_programs.mail_provider import normalize_domain
from signals.persistence.schema import (
    acquisition_census_call,
    acquisition_census_company_match,
    acquisition_census_sample_page,
    acquisition_census_sample_plan,
)
from signals.supplier_discovery.contracts import SupplierSearchPage


def _estimate(population: int, rate: float, low: float, high: float) -> dict[str, int]:
    return {"low": round(population * low), "central": round(population * rate),
            "high": round(population * high)}


def sample_report(engine: Engine, census_id: str, permit_id: str) -> dict[str, Any]:
    """Keep Apollo totals, page observations and weighted estimates separate."""
    store = CensusStore(engine)
    funnel = store.report(census_id, public_aggregate=True)
    partitions = {row["partition_id"]: row for row in store.partitions(census_id)}
    candidates = store.candidates(census_id)
    by_id = {row["provider_organization_id"]: row for row in candidates}
    by_domain = {normalize_domain(row["primary_domain"]): row for row in candidates
                 if row["primary_domain"]}
    with engine.connect() as connection:
        plan = connection.execute(sa.select(acquisition_census_sample_plan).where(
            acquisition_census_sample_plan.c.plan_id == permit_id,
            acquisition_census_sample_plan.c.census_id == census_id,
        )).mappings().one()
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
            if measured is None and candidate.primary_domain:
                try:
                    measured = by_domain.get(normalize_domain(candidate.primary_domain))
                except ValueError:
                    measured = None
            if measured is None:
                continue
            observation = {
                "id": measured["provider_organization_id"],
                "google": measured["provider"] == "GOOGLE_WORKSPACE" and
                measured["provider_confidence"] == "CONFIRMED",
                "valid": bool(measured["primary_domain"]),
                "active": legal.get(measured["provider_organization_id"], {}).get(
                    "legal_status") == "ACTIVE" and legal.get(
                    measured["provider_organization_id"], {}).get(
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
    accessible_google = accessible_low = accessible_high = 0.0
    accessible_active = accessible_active_low = accessible_active_high = 0.0
    sector: dict[str, Counter[str]] = defaultdict(Counter)
    size: dict[str, Counter[str]] = defaultdict(Counter)
    depth: dict[str, Counter[str]] = defaultdict(Counter)
    depth_quartile: dict[str, Counter[str]] = defaultdict(Counter)
    family_confidence = 1 - 0.05 / max(len(partitions), 1)
    for partition_id, part in partitions.items():
        values = observations[partition_id]
        n = len(values)
        gw = sum(item["google"] for item in values)
        active = sum(item["google"] and item["active"] for item in values)
        gw_low, gw_high = wilson_interval(gw, n)
        act_low, act_high = wilson_interval(active, n)
        joint_gw_low, joint_gw_high = wilson_interval(
            gw, n, confidence=family_confidence,
        )
        joint_act_low, joint_act_high = wilson_interval(
            active, n, confidence=family_confidence,
        )
        rate = gw / n if n else 0
        active_rate = active / n if n else 0
        weight = (int(part["estimated_result_count"] or 0) / declared) if declared else 0
        visible = min(int(part["estimated_result_count"] or 0),
                      500 * int(part["filters"]["per_page"]))
        accessible_weight = visible / accessible_declared if accessible_declared else 0
        weighted_google += weight * rate
        weighted_low += weight * joint_gw_low
        weighted_high += weight * joint_gw_high
        weighted_active += weight * active_rate
        weighted_active_low += weight * joint_act_low
        weighted_active_high += weight * joint_act_high
        accessible_google += accessible_weight * rate
        accessible_low += accessible_weight * joint_gw_low
        accessible_high += accessible_weight * joint_gw_high
        accessible_active += accessible_weight * active_rate
        accessible_active_low += accessible_weight * joint_act_low
        accessible_active_high += accessible_weight * joint_act_high
        label = f"{part['size_min']}-{part['size_max']}"
        for bucket in (sector[part["sector"]], size[label]):
            bucket["observed"] += n
            bucket["google"] += gw
        for item in values:
            bucket = depth["FIRST" if item["page"] == 1 else "DEEP"]
            bucket["observed"] += 1
            bucket["google"] += int(item["google"])
            accessible_pages = max(1, min(
                500, (int(part["estimated_result_count"] or 0) +
                      int(part["filters"]["per_page"]) - 1) //
                      int(part["filters"]["per_page"]),
            ))
            quartile = min(4, 1 + 4 * (item["page"] - 1) // accessible_pages)
            quarter = depth_quartile[f"Q{quartile}"]
            quarter["observed"] += 1
            quarter["google"] += int(item["google"])
        strata[partition_id] = {
            "sector": part["sector"], "size": label,
            "apollo_declared_total": part["estimated_result_count"],
            "observed": n, "google_workspace": gw,
            "google_rate": rate, "google_wilson_95": [gw_low, gw_high],
            "confirmed_active_google": active,
            "active_google_wilson_95": [act_low, act_high],
            "population_weight": weight,
            "accessible_population_weight": accessible_weight,
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
    google_unique_total = sum(
        row["provider"] == "GOOGLE_WORKSPACE" and
        row["provider_confidence"] == "CONFIRMED" for row in candidates
    )
    low_unique, high_unique = wilson_interval(max(0, observed - duplicates), observed)
    unique_rate = unique / observed if observed else 0
    unique_population = _estimate(declared, unique_rate, low_unique, high_unique)
    official_statuses = Counter(item["legal_status"] for item in legal.values())
    official_matches = Counter(item["match_confidence"] for item in legal.values())
    new_calls = [row for row in calls if row["permit_id"] == permit_id]

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
        "sample_status": (
            "COMPLETE" if selected and all(row["status"] == "COMPLETED" for row in selected)
            and len(verified_google_unique) == google_unique_total else "INCOMPLETE"
        ),
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
        "weighted_interval_method": "STRATUM_WILSON_WITH_BONFERRONI_95_FAMILY_APPROX",
        "weighted_active_google_rate": weighted_active if declared else None,
        "weighted_active_google_interval_95_approx":
            [weighted_active_low, weighted_active_high],
        "accessible_google_rate_weighted": accessible_google if accessible_declared else None,
        "accessible_google_interval_95_approx": [accessible_low, accessible_high],
        "accessible_confirmed_active_google_rate_weighted": (
            accessible_active if accessible_declared else None
        ),
        "estimated_accessible_unique_organizations": _estimate(
            accessible_declared, unique_rate, low_unique, high_unique,
        ),
        "estimated_accessible_google_workspace_organizations": _estimate(
            accessible_declared, accessible_google * unique_rate,
            accessible_low * low_unique, accessible_high * high_unique,
        ),
        "estimated_accessible_confirmed_active_google_organizations": _estimate(
            accessible_declared, accessible_active * unique_rate,
            accessible_active_low * low_unique, accessible_active_high * high_unique,
        ),
        "estimated_unique_organizations": unique_population,
        "estimated_google_workspace_organizations": _estimate(
            declared, weighted_google * unique_rate,
            weighted_low * low_unique, weighted_high * high_unique,
        ),
        "estimated_confirmed_active_google_organizations": _estimate(
            declared, weighted_active * unique_rate,
            weighted_active_low * low_unique, weighted_active_high * high_unique,
        ),
        "all_declared_estimate_status": "SCENARIO_EXTRAPOLATES_BEYOND_APOLLO_DISPLAY_LIMIT",
        "active_company_estimate_status": (
            "OBSERVED_MATCHER_YIELD_ONLY_NOT_TRUE_ACTIVITY_PREVALENCE"
            if not active_google_unique else "OBSERVED_CONFIRMED_MATCHES"
        ),
        "by_partition": strata,
        "by_sector": aggregate_rates(sector),
        "by_size": aggregate_rates(size),
        "by_depth": aggregate_rates(depth),
        "by_depth_quartile": aggregate_rates(depth_quartile),
        "by_location_unique_anonymized": funnel["by_location"],
        "by_mail_provider_unique": funnel["by_mail_provider"],
        "pages_completed": len(page_calls), "pages_a1_planned": len(selected),
        "pages_a1_completed": sum(row["status"] == "COMPLETED" for row in selected),
        "pages_a1_remaining": sum(row["status"] != "COMPLETED" for row in selected),
        "apollo_search_calls_new": sum(row["status"] == "COMPLETED" for row in new_calls),
        "apollo_search_attempts_new": len(new_calls),
        "apollo_credits_new_reserved_upper_bound": sum(row["reserved_credits"]
                                                         for row in new_calls),
        "apollo_pool_before": plan["apollo_pool_before"],
        "apollo_organization_search_day_before": plan["apollo_org_search_day_before"],
        "apollo_search_failed_or_review_new": sum(
            row["permit_id"] == permit_id and row["status"] != "COMPLETED" for row in calls
        ),
        "official_requests_cumulative": store.status(census_id)["official_requests_reserved"],
        "official_matches_without_new_request": max(
            0, len(legal) - store.status(census_id)["official_requests_reserved"]
        ),
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
