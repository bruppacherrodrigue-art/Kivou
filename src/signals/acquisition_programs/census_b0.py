"""Frozen, private B0 contact-yield sample over observed Google Workspace firms."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable
from functools import partial
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import CensusBudgetExceeded, CensusLimits, CensusStore
from signals.acquisition_programs.census_readiness import PermitStore
from signals.acquisition_programs.census_sampling import wilson_interval
from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.discovery import build_program_contact_profile
from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderDetector,
    normalize_domain,
)
from signals.acquisition_programs.official_company import OfficialCompanyMatcher
from signals.acquisition_programs.qualification import (
    FitSignals,
    ProfessionalEvidenceInput,
    classify_recipient,
    score_fit,
)
from signals.compliance.milomail_rules import (
    MILOMAIL_PURPOSE,
    MilomailPolicyInput,
    evaluate_milomail,
)
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    normalize_business_email,
)
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.contact_discovery.contracts import (
    ApolloEnrichedPerson,
    PeopleSearchPage,
)
from signals.persistence.schema import (
    acquisition_census_b0_entry,
    acquisition_census_b0_plan,
    acquisition_census_call,
    acquisition_census_candidate,
    acquisition_census_company_match,
    acquisition_census_occurrence,
    acquisition_census_partition,
    acquisition_census_permit,
    acquisition_census_run,
    acquisition_contact_suppression,
    acquisition_supplier,
)
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate

PLAN_VERSION = "milomail-b0-stratified-v1"
_LEADER_TERMS = (
    ("cofondateur", 0), ("co-fondateur", 0), ("cofounder", 0),
    ("fondateur", 0), ("founder", 0), ("propriétaire", 1), ("owner", 1),
    ("gérant", 2), ("gerant", 2), ("président", 3), ("president", 3),
    ("chief executive", 4), ("ceo", 4), ("managing director", 5),
    ("directeur général", 5), ("directrice générale", 5),
    ("fondatrice", 0), ("gérante", 2), ("présidente", 3),
    ("dirigeant", 6), ("dirigeante", 6),
)
_PERSONAL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "hotmail.fr",
    "yahoo.com", "yahoo.fr", "icloud.com", "live.com", "aol.com",
})
_GENERIC_LOCAL = frozenset({"info", "contact", "hello", "support", "admin", "office", "bonjour"})


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def leader_rank(title: str | None) -> int | None:
    if not title:
        return None
    lower = title.casefold()
    if any(token in lower for token in ("former", "ancien", "ex-", "external", "consultant")):
        return None
    return min((rank for term, rank in _LEADER_TERMS if term in lower), default=None)


def program_role(title: str | None, config: AcquisitionProgramConfig) -> str | None:
    lower = (title or "").casefold()
    for role in ("founder", "owner", "ceo", "managing_director"):
        if any(term.casefold() in lower for term in config.role_terms.get(role, ())):
            return role
    return None


def classify_email(person: ApolloEnrichedPerson | None, *, company_domain: str,
                   provider: MailProvider) -> str:
    if person is None or not person.business_email:
        return "NO_EMAIL"
    try:
        email = normalize_business_email(person.business_email)
        local, domain = email.rsplit("@", 1)
        domain = normalize_domain(domain)
    except (ValueError, TypeError):
        return "NO_EMAIL"
    if domain in _PERSONAL_DOMAINS:
        return "PERSONAL_EMAIL_REJECTED"
    if local.split("+", 1)[0] in _GENERIC_LOCAL:
        return "GENERIC_EMAIL_REJECTED"
    if domain != company_domain:
        return "DOMAIN_MISMATCH"
    if person.provider_email_status != "verified":
        return "PRO_EMAIL_FOUND"
    if provider != MailProvider.GOOGLE_WORKSPACE:
        return "PROVIDER_MISMATCH"
    return "GOOGLE_WORKSPACE_EMAIL"


def reconcile_counter_window(kind: str, before: int | None, after: int | None,
                             pool_delta: int | None) -> bool:
    """Return whether a one-call counter advanced across its minute reset."""
    if kind == "PEOPLE_SEARCH" and pool_delta == 0:
        # This endpoint is documented as free. Its response and zero pool
        # movement are recorded even when the shared daily counter lags.
        return False
    if before is not None and after is not None and after - before == 1:
        return False
    if (kind == "PERSON_ENRICH" and before is not None and after == 1 and
            before > after and pool_delta == 1):
        return True
    raise CensusBudgetExceeded("Apollo operation counter is ambiguous")


class B0PlanStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def plan(self, census_id: str, *, permit_id: str, pool_balance: int,
             max_companies: int, max_credits: int, at: dt.datetime) -> dict:
        if (not 5 <= max_companies <= 200 or not 1 <= max_credits <= 1500 or
                pool_balance - max_credits < 500 or not 8 <= len(permit_id) <= 64):
            raise ValueError("B0 requires a frozen sample and 500-credit reserve")
        with self.engine.begin() as connection:
            run = connection.execute(sa.select(acquisition_census_run).where(
                acquisition_census_run.c.census_id == census_id,
            ).with_for_update()).mappings().one()
            if (run["pages_reserved"] != 90 or run["active_sample_plan_id"] is None or
                    run["status"] not in {"ACTIVE", "PAUSED"}):
                raise ValueError("B0 requires completed A1 pages")
            rows = connection.execute(sa.select(acquisition_census_candidate).where(
                acquisition_census_candidate.c.census_id == census_id,
                acquisition_census_candidate.c.provider == "GOOGLE_WORKSPACE",
                acquisition_census_candidate.c.provider_confidence == "CONFIRMED",
                acquisition_census_candidate.c.primary_domain.is_not(None),
            ).order_by(acquisition_census_candidate.c.candidate_id)).mappings().all()
            occurrences = defaultdict(list)
            for row in connection.execute(sa.select(acquisition_census_occurrence).join(
                acquisition_census_partition).where(
                acquisition_census_partition.c.census_id == census_id,
            )).mappings():
                occurrences[row["candidate_id"]].append(row)
            partitions = {row["partition_id"]: row for row in connection.execute(
                sa.select(acquisition_census_partition).where(
                    acquisition_census_partition.c.census_id == census_id,
                )).mappings()}
            official = {row["provider_organization_id"]: row["match_evidence"]
                        for row in connection.execute(sa.select(acquisition_census_company_match).where(
                            acquisition_census_company_match.c.census_id == census_id,
                        )).mappings()}
            already = {row[0] for row in connection.execute(sa.select(
                acquisition_census_b0_entry.c.candidate_id,
            ).join(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.census_id == census_id,
                acquisition_census_b0_entry.c.status == "COMPLETE",
            ))}
            prior_searches = set(connection.execute(sa.select(
                acquisition_census_call.c.subject_hash,
            ).where(
                acquisition_census_call.c.census_id == census_id,
                acquisition_census_call.c.kind == "PEOPLE_SEARCH",
                acquisition_census_call.c.status == "COMPLETED",
            )).scalars())
            suppressed_companies = {row[0] for row in connection.execute(sa.select(
                acquisition_supplier.c.provider_organization_id,
            ).join(acquisition_contact_suppression,
                   acquisition_contact_suppression.c.supplier_ref == acquisition_supplier.c.supplier_ref)
             .where(acquisition_supplier.c.provider == "apollo",
                    acquisition_contact_suppression.c.scope == MILOMAIL_SUPPRESSION_SCOPE,
                    acquisition_contact_suppression.c.effective_at <= at))}
            groups: dict[tuple, list[tuple[dict, dict]]] = defaultdict(list)
            for row in rows:
                if (row["candidate_id"] in already or
                        hashlib.sha256(f'{row["candidate_id"]}:people-search'.encode()).hexdigest()
                        in prior_searches or row["contact_found"] or
                        row["email_verified"] or
                        row["provider_organization_id"] in suppressed_companies):
                    continue
                try:
                    normalized = normalize_domain(row["primary_domain"])
                except (ValueError, TypeError):
                    continue
                if normalized != row["primary_domain"]:
                    continue
                evidence = official.get(row["provider_organization_id"], {})
                if evidence.get("match_confidence") == "CONFIRMED_MATCH" and evidence.get("legal_status") == "CEASED":
                    continue
                seen = sorted(occurrences[row["candidate_id"]],
                              key=lambda item: (item["partition_id"], item["first_page"]))
                if not seen:
                    continue
                part = partitions[seen[0]["partition_id"]]
                snapshot = row["snapshot"]
                quality = "complete" if snapshot.get("display_name") and snapshot.get("location") else "sparse"
                proof = "official" if evidence.get("match_confidence") == "CONFIRMED_MATCH" else "unproved"
                depth = "first" if seen[0]["first_page"] == 1 else "deep"
                stratum = {"sector": part["sector"], "size_band": f"{part['size_min']}-{part['size_max']}",
                           "partition_id": part["partition_id"], "depth": depth,
                           "official_proof": proof, "data_quality": quality}
                group = (part["sector"], stratum["size_band"], stratum["partition_id"],
                         depth, proof, quality)
                groups[group].append((dict(row), stratum))
            baseline = _digest([(r["candidate_id"], r["provider_evidence"],
                                 official.get(r["provider_organization_id"])) for r in rows])
            seed = _digest((PLAN_VERSION, permit_id, baseline))
            for values in groups.values():
                values.sort(key=lambda item: _digest((seed, item[0]["candidate_id"])))
            selected: list[tuple[dict, dict]] = []
            ordered = sorted(groups, key=lambda group: _digest((seed, group)))
            cursor = 0
            while len(selected) < max_companies:
                progressed = False
                for group in ordered:
                    if cursor < len(groups[group]):
                        selected.append(groups[group][cursor])
                        progressed = True
                        if len(selected) == max_companies:
                            break
                if not progressed:
                    break
                cursor += 1
            if len(selected) < 5:
                raise ValueError("B0 has fewer than five eligible organizations")
            plan_hash = _digest((PLAN_VERSION, census_id, seed, baseline, max_credits,
                                 [(item[0]["candidate_id"], item[1]) for item in selected]))
            existing = connection.execute(sa.select(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.plan_id == permit_id,
            )).mappings().one_or_none()
            if existing:
                if (existing["plan_hash"] != plan_hash or existing["baseline_hash"] != baseline or
                        existing["pool_before"] != pool_balance):
                    raise ValueError("B0 plan is immutable")
            else:
                connection.execute(sa.insert(acquisition_census_b0_plan).values(
                    plan_id=permit_id, census_id=census_id, plan_hash=plan_hash,
                    baseline_hash=baseline, seed=seed, pool_before=pool_balance,
                    pool_after=None, credit_cap=max_credits, minimum_pool_balance=500,
                    status="PLANNED", created_at=at, updated_at=at,
                ))
                connection.execute(sa.insert(acquisition_census_b0_entry), [
                    {"plan_id": permit_id, "candidate_id": row["candidate_id"],
                     "selection_rank": index, "stratum": stratum,
                     "status": "PLANNED", "result": None, "completed_at": None}
                    for index, (row, stratum) in enumerate(selected, 1)
                ])
        return self.details(permit_id)

    def details(self, permit_id: str) -> dict:
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.plan_id == permit_id,
            )).mappings().one()
            entries = connection.execute(sa.select(acquisition_census_b0_entry).where(
                acquisition_census_b0_entry.c.plan_id == permit_id,
            ).order_by(acquisition_census_b0_entry.c.selection_rank)).mappings().all()
        return {"plan_id": permit_id, "census_id": plan["census_id"],
                "plan_hash": plan["plan_hash"], "status": plan["status"],
                "companies_planned": len(entries), "companies_complete": sum(
                    row["status"] == "COMPLETE" for row in entries),
                "credit_cap": plan["credit_cap"], "pool_before": plan["pool_before"],
                "pool_after": plan["pool_after"]}

    def report(self, permit_id: str) -> dict:
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.plan_id == permit_id,
            )).mappings().one()
            rows = connection.execute(sa.select(acquisition_census_b0_entry).where(
                acquisition_census_b0_entry.c.plan_id == permit_id,
            )).mappings().all()
            calls = connection.execute(sa.select(acquisition_census_call).where(
                acquisition_census_call.c.permit_id == permit_id,
            )).mappings().all()
        counts = Counter(row["result"].get("classification") for row in rows if row["result"])
        decisions = Counter(row["result"].get("decision") for row in rows if row["result"])
        official = Counter(
            (row["result"]["official"].get("match_confidence"),
             row["result"]["official"].get("legal_status"))
            for row in rows if row["result"] and isinstance(row["result"].get("official"), dict)
        )
        observed_costs: dict[str, list[int]] = defaultdict(list)
        checkpointed_calls: set[str] = set()
        for row in rows:
            if isinstance(row["result"], dict):
                for receipt in row["result"].get("calls", []):
                    checkpointed_calls.add(receipt["call_id"])
                    if receipt.get("observed_pool_delta") is not None:
                        observed_costs[receipt["kind"]].append(receipt["observed_pool_delta"])
        return {"phase": "CONTACT_YIELD_B0", "plan_status": plan["status"],
                "sample_size": len(rows),
                "completed": sum(row["status"] == "COMPLETE" for row in rows),
                "review_required": sum(row["status"] == "REVIEW_REQUIRED" for row in rows),
                "completed_calls_without_company_checkpoint": sum(
                    row["status"] == "COMPLETED" and row["call_id"] not in checkpointed_calls
                    for row in calls),
                "free_search_counters_unconfirmed": sum(bool(
                    receipt.get("counter_unconfirmed")) for row in rows
                    if isinstance(row["result"], dict)
                    for receipt in row["result"].get("calls", [])),
                "free_searches_documented_unprobed": sum(bool(
                    receipt.get("documented_zero_credit")) for row in rows
                    if isinstance(row["result"], dict)
                    for receipt in row["result"].get("calls", [])),
                "by_classification": dict(sorted(counts.items())),
                "by_decision": dict(sorted(decisions.items())),
                "official_status": {f"{match}:{status}": count
                                    for (match, status), count in sorted(official.items())},
                "legal_identifiers_from_website": sum(bool(
                    row["result"] and (row["result"].get("legal_identifier_from_website") or
                    (isinstance(row["result"].get("official"), dict) and
                     row["result"]["official"].get("legal_page_source_url")))) for row in rows),
                "leaders_found": sum(bool(row["result"] and row["result"].get("leader_found")) for row in rows),
                "professional_emails_found": sum(bool(row["result"] and row["result"].get("professional_email_found")) for row in rows),
                "verified_emails": sum(bool(row["result"] and row["result"].get("verified_email")) for row in rows),
                "second_candidates_attempted": sum(
                    sum(receipt.get("kind") == "PERSON_ENRICH" for receipt in
                        row["result"].get("calls", [])) == 2
                    for row in rows if isinstance(row["result"], dict)),
                "google_workspace_emails": counts.get("GOOGLE_WORKSPACE_EMAIL", 0),
                "apollo_calls_by_kind": dict(sorted(Counter(row["kind"] for row in calls).items())),
                "credits_reserved_upper_bound": sum(row["reserved_credits"] for row in calls),
                "observed_credit_delta_by_operation": {
                    kind: {"calls": len(values), "sum": sum(values), "max": max(values)}
                    for kind, values in sorted(observed_costs.items())
                },
                "pool_before": plan["pool_before"], "pool_after": plan["pool_after"],
                "pool_delta_ambiguous_shared": (None if plan["pool_after"] is None else
                                                 plan["pool_before"] - plan["pool_after"]),
                "incremental_charge_chf": "0.00", "allocation_cost_chf": None,
                "instantly_mutations": 0, "emails_sent": 0}

    def refresh_official(self, permit_id: str, *, matcher: OfficialCompanyMatcher,
                         resolver: LegalPageResolver, max_companies: int,
                         at: dt.datetime) -> dict:
        """Public-only recheck after a revoked permit; never touches Apollo contacts."""
        if not 1 <= max_companies <= 200:
            raise ValueError("official recheck must be bounded")
        with self.engine.connect() as connection:
            permit = connection.execute(sa.select(acquisition_census_permit).where(
                acquisition_census_permit.c.permit_id == permit_id,
            )).mappings().one()
            if permit["status"] != "REVOKED" or permit["phase"] != "CONTACT_YIELD_B0":
                raise ValueError("official-only recheck requires revoked B0 permit")
            entries = connection.execute(sa.select(acquisition_census_b0_entry).where(
                acquisition_census_b0_entry.c.plan_id == permit_id,
                acquisition_census_b0_entry.c.status == "COMPLETE",
            ).order_by(acquisition_census_b0_entry.c.selection_rank)).mappings().all()
        checked = 0
        for entry in entries:
            result = entry["result"]
            if (not isinstance(result, dict) or
                    result.get("classification") != "GOOGLE_WORKSPACE_EMAIL"):
                continue
            prior = result.get("official")
            if (isinstance(prior, dict) and
                    prior.get("match_confidence") == "CONFIRMED_MATCH" and
                    prior.get("legal_status") in {"ACTIVE", "CEASED"}):
                continue
            if checked >= max_companies:
                break
            with self.engine.connect() as connection:
                candidate = connection.execute(sa.select(acquisition_census_candidate).where(
                    acquisition_census_candidate.c.candidate_id == entry["candidate_id"],
                )).mappings().one()
            company = ApolloOrganizationCandidate.model_validate(candidate["snapshot"])
            official_match = matcher.assess_with_legal_page(company, resolver=resolver, at=at)
            revised = dict(result)
            revised["official"] = official_match.model_dump(mode="json")
            if (official_match.match_confidence == "CONFIRMED_MATCH" and
                    official_match.legal_status == "CEASED"):
                revised["decision"] = "NO_SEND"
                revised["reason_codes"] = ["COMPANY_INACTIVE"]
            else:
                # Sender and landing remain closed. Never upgrade to SEND here.
                revised["decision"] = "HOLD"
                revised["reason_codes"] = ["POLICY_GATEWAY_REVIEW_REQUIRED" if (
                    official_match.match_confidence == "CONFIRMED_MATCH" and
                    official_match.legal_status == "ACTIVE") else
                    "COMPANY_ACTIVE_STATUS_UNRESOLVED"]
            with self.engine.begin() as connection:
                connection.execute(sa.update(acquisition_census_b0_entry).where(
                    acquisition_census_b0_entry.c.plan_id == permit_id,
                    acquisition_census_b0_entry.c.candidate_id == entry["candidate_id"],
                    acquisition_census_b0_entry.c.status == "COMPLETE",
                ).values(result=revised))
            checked += 1
        return {"official_rechecked": checked,
                "official_api_calls": matcher.requests_made,
                "website_http_calls": resolver.requests_made,
                "instantly_mutations": 0, "emails_sent": 0,
                "report": self.report(permit_id)}

    def census_report(self, census_id: str) -> dict:
        """Aggregate completed B0 permits without emitting contact fields."""
        with self.engine.connect() as connection:
            plans = connection.execute(sa.select(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.census_id == census_id,
            ).order_by(acquisition_census_b0_plan.c.created_at)).mappings().all()
            entries = connection.execute(sa.select(acquisition_census_b0_entry).join(
                acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.census_id == census_id,
                acquisition_census_b0_entry.c.status == "COMPLETE",
            ).order_by(acquisition_census_b0_entry.c.completed_at,
                       acquisition_census_b0_entry.c.plan_id)).mappings().all()
            calls = connection.execute(sa.select(acquisition_census_call).join(
                acquisition_census_permit,
                acquisition_census_call.c.permit_id == acquisition_census_permit.c.permit_id,
            ).where(
                acquisition_census_permit.c.census_id == census_id,
                acquisition_census_permit.c.phase == "CONTACT_YIELD_B0",
            )).mappings().all()
        by_candidate: dict[str, Any] = {}
        for entry in entries:
            by_candidate.setdefault(entry["candidate_id"], entry["result"])
        results = [item for item in by_candidate.values() if isinstance(item, dict)]
        classification = Counter(item.get("classification") for item in results)
        decision = Counter(item.get("decision") for item in results)
        reasons = Counter(code for item in results for code in item.get("reason_codes", []))
        receipt_ids = {receipt["call_id"] for item in results
                       for receipt in item.get("calls", []) if "call_id" in receipt}
        observed_costs: dict[str, list[int]] = defaultdict(list)
        for item in results:
            for receipt in item.get("calls", []):
                delta = receipt.get("observed_pool_delta")
                if type(delta) is int:
                    observed_costs[receipt["kind"]].append(delta)
        before = plans[0]["pool_before"] if plans else None
        after = next((plan["pool_after"] for plan in reversed(plans)
                      if plan["pool_after"] is not None), None)
        return {"phase": "CONTACT_YIELD_B0", "companies_completed": len(results),
                "leaders_found": sum(bool(item.get("leader_found")) for item in results),
                "professional_emails_found": sum(bool(item.get("professional_email_found"))
                                                 for item in results),
                "verified_emails": sum(bool(item.get("verified_email")) for item in results),
                "second_candidates_attempted": sum(
                    sum(receipt.get("kind") == "PERSON_ENRICH" for receipt in
                        item.get("calls", [])) == 2 for item in results),
                "google_workspace_emails": classification["GOOGLE_WORKSPACE_EMAIL"],
                "legal_identifiers_from_website": sum(bool(
                    item.get("legal_identifier_from_website") or
                    (isinstance(item.get("official"), dict) and
                     item["official"].get("legal_page_source_url"))) for item in results),
                "official_active_confirmed": sum(bool(
                    isinstance(item.get("official"), dict) and
                    item["official"].get("match_confidence") == "CONFIRMED_MATCH" and
                    item["official"].get("legal_status") == "ACTIVE") for item in results),
                "by_classification": dict(sorted(classification.items())),
                "by_decision": dict(sorted(decision.items())),
                "by_reason_code": dict(sorted(reasons.items())),
                "free_search_counters_unconfirmed": sum(bool(
                    receipt.get("counter_unconfirmed")) for item in results
                    for receipt in item.get("calls", [])),
                "free_searches_documented_unprobed": sum(bool(
                    receipt.get("documented_zero_credit")) for item in results
                    for receipt in item.get("calls", [])),
                "apollo_calls_by_kind": dict(sorted(Counter(call["kind"] for call in calls).items())),
                "completed_calls_without_company_checkpoint": sum(
                    call["status"] == "COMPLETED" and call["call_id"] not in receipt_ids
                    for call in calls),
                "credits_reserved_upper_bound": sum(call["reserved_credits"] for call in calls),
                "observed_credit_delta_by_operation": {
                    kind: {"calls": len(values), "sum": sum(values), "max": max(values)}
                    for kind, values in sorted(observed_costs.items())
                },
                "pool_before": before, "pool_after": after,
                "pool_delta_ambiguous_shared": before - after if before is not None and
                after is not None else None,
                "permits_total": len(plans),
                "incremental_charge_chf": "0.00", "allocation_cost_chf": None,
                "instantly_mutations": 0, "emails_sent": 0}

    def projection(self, permit_id: str, *, a1_report: dict,
                   all_b0_permits: bool = False) -> dict:
        """Population-weighted, model-based interval; no addresses are inferred as facts."""
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.plan_id == permit_id,
            )).mappings().one()
            if all_b0_permits:
                sample = connection.execute(sa.select(acquisition_census_b0_entry).join(
                    acquisition_census_b0_plan).where(
                    acquisition_census_b0_plan.c.census_id == plan["census_id"],
                    acquisition_census_b0_entry.c.status == "COMPLETE",
                ).order_by(acquisition_census_b0_entry.c.completed_at,
                           acquisition_census_b0_entry.c.plan_id)).mappings().all()
                unique_sample: dict[str, Any] = {}
                for item in sample:
                    unique_sample.setdefault(item["candidate_id"], item)
                sample = list(unique_sample.values())
            else:
                sample = connection.execute(sa.select(acquisition_census_b0_entry).where(
                    acquisition_census_b0_entry.c.plan_id == permit_id,
                )).mappings().all()
            candidates = connection.execute(sa.select(acquisition_census_candidate).where(
                acquisition_census_candidate.c.census_id == plan["census_id"],
                acquisition_census_candidate.c.provider == "GOOGLE_WORKSPACE",
                acquisition_census_candidate.c.provider_confidence == "CONFIRMED",
            )).mappings().all()
            occurrences = defaultdict(list)
            for row in connection.execute(sa.select(acquisition_census_occurrence).join(
                acquisition_census_partition).where(
                acquisition_census_partition.c.census_id == plan["census_id"],
            )).mappings():
                occurrences[row["candidate_id"]].append(row)
        population: Counter[tuple[str, str]] = Counter()
        for candidate in candidates:
            seen = sorted(occurrences[candidate["candidate_id"]],
                          key=lambda row: (row["partition_id"], row["first_page"]))
            if seen:
                population[(seen[0]["partition_id"],
                            "first" if seen[0]["first_page"] == 1 else "deep")] += 1
        completed = defaultdict(list)
        for item in sample:
            if item["status"] == "COMPLETE" and isinstance(item["result"], dict):
                key = (item["stratum"]["partition_id"], item["stratum"]["depth"])
                completed[key].append(item["result"])
        if not population or any(not completed[group] for group in population):
            return {"status": "INSUFFICIENT_STRATA", "completed": sum(map(len, completed.values())),
                    "population_strata": len(population),
                    "sampled_strata": sum(bool(completed[group]) for group in population)}
        outcomes = {
            "leaders_identifiable": lambda result: bool(result.get("leader_found")),
            "professional_emails_found": lambda result: bool(result.get("professional_email_found")),
            "verified_emails": lambda result: bool(result.get("verified_email")),
            "google_workspace_emails": lambda result: result.get("classification") == "GOOGLE_WORKSPACE_EMAIL",
            "technical_hold": lambda result: (result.get("classification") == "GOOGLE_WORKSPACE_EMAIL"
                                              and result.get("decision") == "HOLD"),
        }
        total_population = sum(population.values())
        rates = {}
        for label, predicate in outcomes.items():
            low = middle = high = 0.0
            for group, size in population.items():
                observations = completed[group]
                success = sum(bool(predicate(item)) for item in observations)
                weight = size / total_population
                lower, upper = wilson_interval(success, len(observations),
                                                 confidence=1 - 0.05 / len(population))
                low += weight * lower
                middle += weight * success / len(observations)
                high += weight * upper
            rates[label] = {"low": low, "central": middle, "high": high}
        base_keys = {
            "apollo_displayable": "estimated_accessible_google_workspace_organizations",
            "all_declared_uncertain": "estimated_google_workspace_organizations",
        }
        projections = {}
        for category, forecast_key in base_keys.items():
            base = a1_report.get(forecast_key)
            if not isinstance(base, dict) or not all(type(base.get(level)) is int and
                                                     base[level] >= 0 for level in
                                                     ("low", "central", "high")):
                raise ValueError("A1 aggregate forecast is missing or invalid")
            projections[category] = {
                label: {"low": math.floor(base["low"] * interval["low"]),
                        "central": round(base["central"] * interval["central"]),
                        "high": math.ceil(base["high"] * interval["high"])}
                for label, interval in rates.items()
            }
        deltas = [0 if (receipt.get("documented_zero_credit") and
                        receipt.get("kind") == "PEOPLE_SEARCH") else
                  receipt.get("observed_pool_delta")
                  for outcomes_group in completed.values() for item in outcomes_group
                  for receipt in item.get("calls", [])]
        if any(type(value) is not int for value in deltas):
            return {"status": "CREDIT_ATTRIBUTION_AMBIGUOUS", "rates": rates,
                    "sample_size": sum(map(len, completed.values()))}
        credits_observed = sum(deltas)
        attribution_complete = (not all_b0_permits and
                                self.report(permit_id)["completed_calls_without_company_checkpoint"] == 0)
        per_company = (credits_observed / sum(map(len, completed.values()))
                       if attribution_complete else None)
        return {"status": "MODEL_BASED_ESTIMATE", "sample_size": sum(map(len, completed.values())),
                "a1_google_workspace_organizations_observed": total_population,
                "strata": len(population), "rates": rates, "projections": projections,
                "observed_credits_per_company": per_company,
                "estimated_credits_for_displayable_central": (
                    round(a1_report[base_keys["apollo_displayable"]]["central"] * per_company)
                    if per_company is not None else None),
                "credit_estimate_status": "ATTRIBUTED" if attribution_complete else "AMBIGUOUS_SHARED_POOL",
                "allocation_cost_chf": None,
                "send_theoretical_observed": sum(
                    item.get("decision") == "SEND_THEORETICAL"
                    for outcomes_group in completed.values() for item in outcomes_group),
                "send_theoretical_future_projection": "NOT_ESTIMABLE_WITH_CLOSED_SENDER_AND_LANDING",
                "interval_method": "population-weighted Wilson with Bonferroni simultaneous 95% bounds",
                "limitations": ["deterministic sample requires exchangeability within strata",
                                "Apollo display cap and cross-partition overlap remain uncertain",
                                "organizations are not verified contact addresses"]}


class B0Runner:
    """Apollo People only. No supplier export, campaign factory or Instantly adapter."""

    def __init__(self, engine: Engine, *, census_id: str, permit_id: str,
                 config: AcquisitionProgramConfig, limits: CensusLimits,
                 database_id: str, configuration_hash: str,
                 contacts: ApolloContactDiscoveryClient,
                 account_probe: Callable[[], ApolloAccountState],
                 detector: MailProviderDetector,
                 official: OfficialCompanyMatcher,
                 legal_pages: LegalPageResolver,
                 suppression_keys: SuppressionIdentityKeyring) -> None:
        if config.program_key != "milomail" or config.enabled or config.campaign_mode != "SHADOW":
            raise ValueError("B0 requires disabled SHADOW Milo Mail")
        self.engine = engine
        self.census_id = census_id
        self.permit_id = permit_id
        self.config = config
        self.limits = limits
        self.database_id = database_id
        self.configuration_hash = configuration_hash
        self.contacts = contacts
        self.account_probe = account_probe
        self.detector = detector
        self.official = official
        self.legal_pages = legal_pages
        self.suppression_keys = suppression_keys
        self.store = CensusStore(engine)
        self._free_search_calibrated = False

    def _account(self, *, min_required: int) -> ApolloAccountState:
        state = self.account_probe()
        balance = state.credit_balances.get("lead_credit")
        if not state.credential_valid or balance is None or balance < min_required:
            raise CensusBudgetExceeded("Apollo prepaid balance or reserve is unavailable")
        return state

    def _call(self, *, candidate_id: str, partition_id: str, kind: str, subject: str,
              credits: int, at: dt.datetime, invoke: Callable[[], Any],
              model: type[PeopleSearchPage | ApolloEnrichedPerson]) -> tuple[Any, dict]:
        with self.engine.connect() as connection:
            prior = connection.execute(sa.select(acquisition_census_call.c.status).where(
                acquisition_census_call.c.census_id == self.census_id,
                acquisition_census_call.c.kind == kind,
                acquisition_census_call.c.subject_hash == hashlib.sha256(subject.encode()).hexdigest(),
                acquisition_census_call.c.attempt == 1,
            )).scalar_one_or_none()
            reserved = connection.scalar(sa.select(sa.func.coalesce(sa.func.sum(
                acquisition_census_call.c.reserved_credits), 0)).where(
                acquisition_census_call.c.permit_id == self.permit_id,
            )) or 0
            plan = connection.execute(sa.select(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.plan_id == self.permit_id,
            )).mappings().one()
        before: ApolloAccountState | None
        current: int | None
        documented_free = bool(kind == "PEOPLE_SEARCH" and self._free_search_calibrated and
                               prior is None)
        if prior is None and not documented_free:
            # A current free account probe protects the shared pool from concurrent
            # drawdown. Reserved worst-case credits are never reclaimed on guesses.
            before = self._account(min_required=500 + credits)
            current = before.credit_balances["lead_credit"]
            if current > plan["pool_before"]:
                raise CensusBudgetExceeded("Apollo pool increased; top-up status requires review")
            if reserved + credits > plan["credit_cap"]:
                raise CensusBudgetExceeded("B0 credit cap exhausted before call")
        else:
            current = None
            before = None
        def decode(value: object) -> Any:
            if value == {"none": True}:
                return None
            return model.model_validate(value)
        result, call_id = self.store.execute_call(
            self.census_id, kind=kind, subject=subject, partition_id=partition_id,
            credits=credits, candidate_slots=1 if kind == "PEOPLE_SEARCH" else 0,
            at=at, invoke=invoke,
            encode=lambda value: value.model_dump(mode="json") if value is not None else {"none": True},
            decode=decode,
        )
        after = self._account(min_required=500) if before is not None else None
        delta = (None if current is None or after is None else
                 current - after.credit_balances["lead_credit"])
        if delta is not None and (delta < 0 or delta > credits):
            raise CensusBudgetExceeded("Apollo pool delta is ambiguous or exceeds reservation")
        counter_window_rolled = False
        counter_unconfirmed = False
        if before is not None and after is not None:
            previous_count = (before.people_search_day_consumed if kind == "PEOPLE_SEARCH"
                              else before.people_match_minute_consumed)
            later_count = (after.people_search_day_consumed if kind == "PEOPLE_SEARCH"
                           else after.people_match_minute_consumed)
            counter_unconfirmed = bool(kind == "PEOPLE_SEARCH" and
                                       (previous_count is None or later_count is None or
                                        later_count - previous_count != 1))
            counter_window_rolled = reconcile_counter_window(
                kind, previous_count, later_count, delta)
        return result, {"call_id": call_id, "kind": kind, "reserved": credits,
                        "observed_pool_delta": delta, "cache_hit": prior == "COMPLETED",
                        "documented_zero_credit": documented_free,
                        "counter_window_rolled": counter_window_rolled,
                        "counter_unconfirmed": counter_unconfirmed}

    def _suppressed(self, email: str, *, at: dt.datetime) -> bool:
        hashes = self.suppression_keys.identities_for_email(
            email, scope=MILOMAIL_SUPPRESSION_SCOPE,
        )
        with self.engine.connect() as connection:
            retained = tuple(connection.execute(sa.select(
                acquisition_contact_suppression.c.identity_key_version,
            ).where(acquisition_contact_suppression.c.scope == MILOMAIL_SUPPRESSION_SCOPE)
             .distinct()).scalars())
            self.suppression_keys.require_versions_covered(retained)
            return bool(connection.scalar(sa.select(sa.func.count()).select_from(
                acquisition_contact_suppression).where(
                acquisition_contact_suppression.c.scope == MILOMAIL_SUPPRESSION_SCOPE,
                acquisition_contact_suppression.c.identity_hmac.in_(tuple(hashes.values())),
                acquisition_contact_suppression.c.effective_at <= at,
            )))

    def _process(self, row: dict, stratum: dict, *, at: dt.datetime) -> dict:
        candidate = ApolloOrganizationCandidate.model_validate(row["snapshot"])
        candidate_id = row["candidate_id"]
        domain = normalize_domain(candidate.primary_domain or "")
        provider = self.detector.detect_domain(domain, observed_at=at)
        if provider.provider != MailProvider.GOOGLE_WORKSPACE:
            return {"classification": "PROVIDER_UNKNOWN" if provider.provider == MailProvider.UNKNOWN
                    else "PROVIDER_MISMATCH",
                    "decision": "HOLD" if provider.provider == MailProvider.UNKNOWN else "NO_SEND",
                    "leader_found": False, "professional_email_found": False,
                    "verified_email": False, "calls": []}
        with self.engine.connect() as connection:
            occurrence = connection.execute(sa.select(acquisition_census_occurrence).where(
                acquisition_census_occurrence.c.candidate_id == candidate_id,
            ).order_by(acquisition_census_occurrence.c.partition_id).limit(1)).mappings().one()
        partition_id = occurrence["partition_id"]
        profile = build_program_contact_profile(
            self.config, acquisition_opportunity_id=f"b0:{candidate_id}",
            supplier_ref=f"b0:{candidate_id}",
            provider_organization_id=candidate.provider_organization_id,
            organization_domain=domain,
        )
        search, receipt = self._call(
            candidate_id=candidate_id, partition_id=partition_id, kind="PEOPLE_SEARCH",
            subject=f"{candidate_id}:people-search", credits=0, at=at,
            invoke=lambda: self.contacts.search_people(profile, observed_at=at),
            model=PeopleSearchPage,
        )
        calls = [receipt]
        assert isinstance(search, PeopleSearchPage)
        leaders = [person for person in search.candidates if leader_rank(person.title) is not None]
        ranked = sorted((person for person in leaders if person.has_email and
                         leader_rank(person.title) is not None),
                        key=lambda person: (leader_rank(person.title), person.provider_position))
        if not ranked:
            return {"classification": "NO_EMAIL" if leaders else "NO_CONTACT",
                    "decision": "HOLD" if leaders else "NO_SEND",
                    "leader_found": bool(leaders), "professional_email_found": False,
                    "verified_email": False, "calls": calls}
        classification = "NO_EMAIL"
        found_business_email: str | None = None
        selected: ApolloEnrichedPerson | None = None
        for person in ranked[:2]:
            if person.provider_person_id in {item.get("provider_person_id") for item in calls}:
                continue
            person_id = person.provider_person_id
            enriched, receipt = self._call(
                candidate_id=candidate_id, partition_id=partition_id, kind="PERSON_ENRICH",
                subject=f"{candidate_id}:person:{person.provider_person_id}",
                credits=self.limits.credits_person_enrichment_max, at=at,
                invoke=partial(self.contacts.enrich_person, person_id, observed_at=at),
                model=ApolloEnrichedPerson,
            )
            calls.append({**receipt, "provider_person_id": person.provider_person_id})
            if enriched is None:
                classification = "NO_EMAIL"
                continue
            assert isinstance(enriched, ApolloEnrichedPerson)
            if (enriched.provider_organization_id != candidate.provider_organization_id or
                    leader_rank(enriched.title) is None):
                classification = "ROLE_REJECTED"
                continue
            classification = classify_email(enriched, company_domain=domain,
                                            provider=provider.provider)
            if classification in {"PRO_EMAIL_FOUND", "GOOGLE_WORKSPACE_EMAIL"}:
                found_business_email = enriched.business_email
            if classification != "GOOGLE_WORKSPACE_EMAIL":
                continue
            selected = enriched
            break
        email = selected.business_email if selected else None
        if email:
            with self.engine.connect() as connection:
                existing = connection.execute(sa.select(acquisition_census_b0_entry.c.result).where(
                    acquisition_census_b0_entry.c.plan_id == self.permit_id,
                    acquisition_census_b0_entry.c.status == "COMPLETE",
                )).scalars().all()
            if any(isinstance(item, dict) and item.get("email") == email for item in existing):
                classification = "DUPLICATE_EMAIL"
        suppressed = bool(email and self._suppressed(email, at=at))
        if suppressed:
            classification = "SUPPRESSED"
        official = (self.official.assess_with_legal_page(candidate,
                    resolver=self.legal_pages, at=at) if email and not suppressed else None)
        if classification == "GOOGLE_WORKSPACE_EMAIL" and selected:
            active_evidence = official.activity() if official else None
            role = program_role(selected.title, self.config)
            size_low, size_high = (int(part) for part in stratum["size_band"].split("-", 1))
            size_range = (size_low, size_high)
            capacity = classify_recipient(ProfessionalEvidenceInput(
                email=email or "", company_domain=domain,
                company_id=candidate.provider_organization_id,
                company_active=bool(active_evidence and active_evidence.status == "ACTIVE"),
                role=role, email_verified=True,
                professional_source_url="https://api.apollo.io/api/v1/people/match",
                professional_source_type="APOLLO_PEOPLE_ENRICHMENT",
                professional_evidence_observed_at=selected.provider_observed_at,
            ), config=self.config, at=at)
            fit = score_fit(FitSignals(
                provider=provider.provider, provider_confirmed=True,
                sector=stratum["sector"], role=role,
                employee_count_range=size_range,
                operational_decision_maker=True,
            ), config=self.config)
            evidence_ids = [f"apollo-person:{selected.source_fingerprint}"]
            if active_evidence and active_evidence.evidence_id:
                evidence_ids.append(active_evidence.evidence_id)
            policy = evaluate_milomail(MilomailPolicyInput(
                acquisition_purpose=MILOMAIL_PURPOSE, program=self.config,
                country=candidate.country_code, sector=stratum["sector"],
                employee_count_range=size_range,
                company_active=(None if not active_evidence or active_evidence.status == "UNKNOWN"
                                else active_evidence.status == "ACTIVE"),
                company_active_source_url=active_evidence.source_url if active_evidence else None,
                company_active_source_type=active_evidence.source_type if active_evidence else None,
                company_active_observed_at=active_evidence.observed_at if active_evidence else None,
                company_active_evidence_id=active_evidence.evidence_id if active_evidence else None,
                business_relevance_confirmed=stratum["sector"] in self.config.target_sectors,
                provider=provider, capacity=capacity, fit=fit, email_verified=True,
                collection_source_url="https://api.apollo.io/api/v1/people/match",
                collected_at=selected.provider_observed_at,
                suppressed=False, suppression_coverage_safe=True,
                evidence_ids=tuple(evidence_ids), assessed_at=at,
            ))
            decision = "SEND_THEORETICAL" if policy.decision == "SEND" else policy.decision
            reasons = list(policy.reason_codes)
        else:
            decision = "NO_SEND"
            reasons = [classification]
        return {"classification": classification, "decision": decision,
                "reason_codes": reasons, "leader_found": True,
                "professional_email_found": bool(found_business_email),
                "verified_email": bool(email),
                "email": email, "person": selected.model_dump(mode="json") if selected else None,
                "official": official.model_dump(mode="json") if official else None,
                "calls": calls}

    def run(self, *, at: dt.datetime, micro_only: bool = True) -> dict:
        with self.engine.connect() as connection:
            permit = connection.execute(sa.select(acquisition_census_permit).where(
                acquisition_census_permit.c.permit_id == self.permit_id,
            )).mappings().one()
        if permit["phase"] != "CONTACT_YIELD_B0" or permit["status"] != "ACTIVE":
            raise ValueError("active B0 permit required")
        if B0PlanStore(self.engine).details(self.permit_id)["status"] == "COMPLETE":
            return B0PlanStore(self.engine).report(self.permit_id)
        self.store.bind_permit(permit_id=self.permit_id, phase="CONTACT_YIELD_B0",
                               configuration_hash=self.configuration_hash,
                               database_id=self.database_id)
        with self.engine.connect() as connection:
            PermitStore.check_call(
                connection, permit_id=self.permit_id, census_id=self.census_id,
                phase="CONTACT_YIELD_B0", kind="PEOPLE_SEARCH", partition_id=None,
                credits=0, candidate_slots=0, at=at,
                configuration_hash_value=self.configuration_hash,
                database_id=self.database_id, check_capacity=False,
            )
        self.store.start(self.census_id, self.limits, at=at, phase="CONTACT_YIELD_B0",
                         sample_plan_id=self.permit_id)
        with self.engine.connect() as connection:
            entries = connection.execute(sa.select(acquisition_census_b0_entry).where(
                acquisition_census_b0_entry.c.plan_id == self.permit_id,
            ).order_by(acquisition_census_b0_entry.c.selection_rank)).mappings().all()
        if not micro_only:
            baseline = entries[:5]
            if (len(baseline) != 5 or any(item["status"] != "COMPLETE" for item in baseline) or
                    not any(any(call["kind"] == "PERSON_ENRICH" for call in item["result"]["calls"])
                            for item in baseline) or
                    any(any(call["observed_pool_delta"] is None for call in item["result"]["calls"])
                        for item in baseline)):
                raise ValueError("five-company calibration is incomplete or unattributable")
            self._free_search_calibrated = True
        for entry in entries[:5] if micro_only else entries:
            if entry["status"] == "COMPLETE":
                continue
            if entry["status"] == "REVIEW_REQUIRED":
                break
            with self.engine.connect() as connection:
                candidate = connection.execute(sa.select(acquisition_census_candidate).where(
                    acquisition_census_candidate.c.candidate_id == entry["candidate_id"],
                )).mappings().one()
            try:
                result = self._process(dict(candidate), entry["stratum"],
                                       at=dt.datetime.now(dt.UTC))
            except CensusBudgetExceeded:
                with self.engine.begin() as connection:
                    connection.execute(sa.update(acquisition_census_b0_plan).where(
                        acquisition_census_b0_plan.c.plan_id == self.permit_id,
                    ).values(status="PAUSED", updated_at=dt.datetime.now(dt.UTC)))
                break
            except Exception:
                with self.engine.begin() as connection:
                    connection.execute(sa.update(acquisition_census_b0_entry).where(
                        acquisition_census_b0_entry.c.plan_id == self.permit_id,
                        acquisition_census_b0_entry.c.candidate_id == entry["candidate_id"],
                    ).values(status="REVIEW_REQUIRED", completed_at=dt.datetime.now(dt.UTC)))
                raise
            with self.engine.begin() as connection:
                connection.execute(sa.update(acquisition_census_b0_entry).where(
                    acquisition_census_b0_entry.c.plan_id == self.permit_id,
                    acquisition_census_b0_entry.c.candidate_id == entry["candidate_id"],
                    acquisition_census_b0_entry.c.status == "PLANNED",
                ).values(status="COMPLETE", result=result, completed_at=dt.datetime.now(dt.UTC)))
        final_balance = self._account(min_required=500).credit_balances["lead_credit"]
        with self.engine.begin() as connection:
            remaining = connection.scalar(sa.select(sa.func.count()).select_from(
                acquisition_census_b0_entry).where(
                acquisition_census_b0_entry.c.plan_id == self.permit_id,
                acquisition_census_b0_entry.c.status != "COMPLETE",
            )) or 0
            connection.execute(sa.update(acquisition_census_b0_plan).where(
                acquisition_census_b0_plan.c.plan_id == self.permit_id,
            ).values(pool_after=final_balance,
                     status="COMPLETE" if remaining == 0 else "PAUSED",
                     updated_at=dt.datetime.now(dt.UTC)))
        return B0PlanStore(self.engine).report(self.permit_id)
