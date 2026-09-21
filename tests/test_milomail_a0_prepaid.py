"""The shared staging pool is a narrow, auditable A0 exception."""

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from test_milomail_census_readiness import _setup

from signals.acquisition_programs.census import CensusBudgetExceeded, CensusLimits
from signals.acquisition_programs.census_cli import resolve_apollo_key
from signals.acquisition_programs.census_readiness import (
    ApolloCreditPricing,
    ExecutionPermit,
    configuration_hash,
)
from signals.persistence.schema import acquisition_census_permit

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _pricing(**changes):
    fields = {
        "currency": "CHF", "price_per_credit": None, "billing_basis": "PREPAID_SHARED_POOL",
        "max_incremental_charge_chf": Decimal("0"), "auto_top_up_allowed": False,
        "overage_allowed": False, "verified_at": NOW, "source_type": "OPERATOR_ATTESTATION",
        "source_reference": "operator-a0-2026-09-21", "plan_name": "staging-shared",
        "verified_by_reference": "operator-prompt", "org_search_credits": 1,
        "org_enrichment_credits": 1, "people_search_credits": 0,
        "person_enrichment_credits_max": 9, "credit_balance": 2135,
        "credit_balance_observed_at": NOW,
        "rate_limits_per_minute": {k: 10 for k in (
            "ORG_SEARCH", "ORG_ENRICH", "PEOPLE_SEARCH", "PERSON_ENRICH")},
        "rate_limit_reference": "apollo-free-usage-probe",
        "credit_pools_by_operation": {k: "lead_credit" for k in (
            "ORG_SEARCH", "ORG_ENRICH", "PEOPLE_SEARCH", "PERSON_ENRICH")},
    }
    fields.update(changes)
    return ApolloCreditPricing(**fields)


def _limits(**changes):
    fields = {"enabled": True, "authorization_ref": "a0-operator-prompt",
                  "max_partitions": 9, "max_pages": 9, "max_candidates": 225,
                  "max_enrichments": 0, "max_apollo_credits": 9, "max_cost_chf": Decimal(0),
                  "chf_per_credit_ceiling": Decimal(0)}
    fields.update(changes)
    return CensusLimits(**fields)


def test_prepaid_pricing_requires_firm_zero_incremental_cost() -> None:
    _pricing().check(_limits(), at=NOW, phase="COVERAGE_A0")
    for change in ({"auto_top_up_allowed": True}, {"overage_allowed": True},
                   {"max_incremental_charge_chf": Decimal("1")}):
        with pytest.raises(ValueError):
            _pricing(**change).check(_limits(), at=NOW, phase="COVERAGE_A0")
    with pytest.raises(ValueError):
        _pricing().check(_limits(), at=NOW, phase="COVERAGE")
    with pytest.raises(ValueError):
        _limits(max_apollo_credits=10).require_run_authorization(phase="COVERAGE_A0")


def test_shared_key_only_resolves_for_a0_and_never_appears_in_error() -> None:
    source = {"KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
              "MILOMAIL_CENSUS_APOLLO_SECRET_REF": "KIVOU_APOLLO_API_KEY",
              "KIVOU_APOLLO_API_KEY": "synthetic-secret-do-not-print"}
    assert resolve_apollo_key(source, phase="COVERAGE_A0", expected_ref="KIVOU_APOLLO_API_KEY") == source["KIVOU_APOLLO_API_KEY"]
    for phase in ("COVERAGE", "ENRICHMENT"):
        with pytest.raises(ValueError) as error:
            resolve_apollo_key(source, phase=phase, expected_ref="KIVOU_APOLLO_API_KEY")
        assert source["KIVOU_APOLLO_API_KEY"] not in str(error.value)
    with pytest.raises(ValueError):
        resolve_apollo_key(source, phase="COVERAGE_A0", expected_ref="OTHER_KEY")


def test_a0_permit_requires_exact_staging_scope() -> None:
    fields = {"permit_id": "synthetic-a0", "census_id": "synthetic-census",
                  "phase": "COVERAGE_A0", "environment": "staging",
                  "database_id": "postgresql:0123456789abcdef:kivou_milomail_census_a0",
                  "allowed_partitions": tuple(f"p{i}" for i in range(9)),
                  "max_pages": 9, "max_candidates": 225, "max_enrichments": 0,
                  "max_credits": 9, "max_cost_chf": Decimal(0), "price_chf_per_credit": None,
                  "billing_basis": "PREPAID_SHARED_POOL",
                  "apollo_secret_ref": "KIVOU_APOLLO_API_KEY",
                  "pricing_reference": "operator-a0-2026-09-21",
                  "configuration_hash": "a" * 64,
                  "issued_by_reference": "operator-prompt", "issued_at": NOW,
                  "valid_from": NOW, "expires_at": NOW + dt.timedelta(hours=2)}
    ExecutionPermit(**fields)
    for change in ({"phase": "COVERAGE"}, {"max_credits": 10},
                   {"database_id": "postgresql:0123456789abcdef:kivou_staging"},
                   {"expires_at": NOW + dt.timedelta(days=1)}):
        with pytest.raises(ValueError):
            ExecutionPermit(**(fields | change))


def test_a0_nine_call_hard_stop_and_completed_cache() -> None:
    engine, store, census_id, _auth, _old_pricing = _setup()
    limits = _limits()
    pricing = _pricing()
    partitions = store.partitions(census_id)
    database_id = "postgresql:0123456789abcdef:kivou_milomail_census_a0"
    permit = ExecutionPermit(
        permit_id="synthetic-nine-call-a0", census_id=census_id,
        phase="COVERAGE_A0", environment="staging", database_id=database_id,
        allowed_partitions=tuple(row["partition_id"] for row in partitions),
        max_pages=9, max_candidates=225, max_enrichments=0, max_credits=9,
        max_cost_chf=Decimal(0), price_chf_per_credit=None,
        billing_basis="PREPAID_SHARED_POOL", apollo_secret_ref="KIVOU_APOLLO_API_KEY",
        pricing_reference=pricing.source_reference,
        configuration_hash=configuration_hash(
            census_id=census_id, limits=limits, partitions=partitions, pricing=pricing),
        issued_by_reference="operator-prompt", issued_at=NOW,
        valid_from=NOW, expires_at=NOW + dt.timedelta(hours=2),
    )
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_permit).values(
            **permit.model_dump(mode="python")))
    store.start(census_id, limits, at=NOW, phase="COVERAGE_A0")
    store.bind_permit(permit_id=permit.permit_id, phase="COVERAGE_A0",
                      configuration_hash=permit.configuration_hash,
                      database_id=database_id)
    for index, row in enumerate(partitions):
        call = store.reserve_call(
            census_id, kind="ORG_SEARCH", subject=f"page-{index}", attempt=1,
            partition_id=row["partition_id"], credits=1, candidate_slots=25, at=NOW)
        store.complete_call(call["call_id"], {"page": index}, at=NOW)
    cached, _ = store.execute_call(
        census_id, kind="ORG_SEARCH", subject="page-0",
        partition_id=partitions[0]["partition_id"], credits=1,
        candidate_slots=25, at=NOW,
        invoke=lambda: pytest.fail("completed page was replayed"),
        encode=lambda value: value, decode=lambda value: value,
    )
    assert cached == {"page": 0}
    with pytest.raises(CensusBudgetExceeded):
        store.reserve_call(census_id, kind="ORG_SEARCH", subject="page-10",
                           attempt=1, partition_id=partitions[0]["partition_id"],
                           credits=1, candidate_slots=25, at=NOW)
    with pytest.raises(ValueError, match="phase"):
        store.reserve_call(census_id, kind="PEOPLE_SEARCH", subject="contact",
                           attempt=1, partition_id=partitions[0]["partition_id"],
                           credits=0, candidate_slots=0, at=NOW)
    report = store.report(census_id)
    assert report["billing_basis"] == "PREPAID_SHARED_POOL"
    assert report["incremental_charge_chf_upper_bound"] == "0.00"
    assert report["allocation_cost_chf"] is None
    assert report["apollo_credits_reserved_upper_bound"] == 9
    assert report["contacts_found"] == report["verified_addresses_unique"] == 0
