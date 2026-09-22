"""The A1 shared-key exception authorizes only bounded organization pages."""

import datetime as dt
from decimal import Decimal

import pytest
from test_milomail_a0_prepaid import _pricing
from test_milomail_a1_plan import _a0

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import CensusLimits, CensusStore
from signals.acquisition_programs.census_cli import resolve_apollo_key
from signals.acquisition_programs.census_readiness import (
    DatabaseAuthorization,
    ExecutionPermit,
    PermitStore,
    configuration_hash,
    preflight,
)
from signals.acquisition_programs.census_sampling import SamplePlanStore
from signals.acquisition_programs.official_company import OfficialSourceConfig
from signals.compliance.suppression import SuppressionIdentityKeyring

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _a1_limits(**changes):
    fields = {
        "enabled": True, "authorization_ref": "operator-a1-81-credits",
        "max_partitions": 9, "max_pages": 90, "max_candidates": 2250,
        "max_enrichments": 0, "max_apollo_credits": 90,
        "max_cost_chf": Decimal(0), "chf_per_credit_ceiling": Decimal(0),
    }
    fields.update(changes)
    return CensusLimits(**fields)


def _a1_permit(**changes):
    fields = {
        "permit_id": "synthetic-a1-permit", "census_id": "synthetic-census",
        "phase": "COVERAGE_A1_SAMPLE", "environment": "staging",
        "database_id": "postgresql:0123456789abcdef:kivou_milomail_census_a0",
        "allowed_partitions": tuple(f"p{i}" for i in range(9)),
        "max_pages": 81, "max_candidates": 2025, "max_enrichments": 0,
        "max_credits": 81, "max_cost_chf": Decimal(0),
        "price_chf_per_credit": None, "billing_basis": "PREPAID_SHARED_POOL",
        "apollo_secret_ref": "KIVOU_APOLLO_API_KEY",
        "sample_plan_hash": "a" * 64,
        "pricing_reference": "operator-a1-prepaid-2026-09-21",
        "configuration_hash": "b" * 64,
        "issued_by_reference": "operator-prompt", "issued_at": NOW,
        "valid_from": NOW, "expires_at": NOW + dt.timedelta(hours=2),
    }
    fields.update(changes)
    return ExecutionPermit(**fields)


def test_a1_prepaid_caps_keep_defaults_closed_and_reject_contact_ops() -> None:
    _a1_limits().require_run_authorization(phase="COVERAGE_A1_SAMPLE")
    _pricing(credit_balance=2126).check(_a1_limits(), at=NOW,
                                        phase="COVERAGE_A1_SAMPLE")
    assert CensusLimits.from_environment({}).max_apollo_credits == 0
    for changed in ({"max_pages": 91}, {"max_apollo_credits": 91},
                    {"max_enrichments": 1}, {"max_cost_chf": Decimal("1")}):
        with pytest.raises(ValueError):
            _a1_limits(**changed).require_run_authorization(phase="COVERAGE_A1_SAMPLE")
    with pytest.raises(ValueError):
        _pricing(auto_top_up_allowed=True).check(_a1_limits(), at=NOW,
                                                phase="COVERAGE_A1_SAMPLE")


def test_a1_shared_key_is_staging_only_and_enrichment_is_forbidden() -> None:
    source = {"KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
              "MILOMAIL_CENSUS_APOLLO_SECRET_REF": "KIVOU_APOLLO_API_KEY",
              "KIVOU_APOLLO_API_KEY": "synthetic-secret-do-not-print"}
    assert resolve_apollo_key(source, phase="COVERAGE_A1_SAMPLE",
                              expected_ref="KIVOU_APOLLO_API_KEY") == source["KIVOU_APOLLO_API_KEY"]
    for phase in ("COVERAGE", "ENRICHMENT"):
        with pytest.raises(ValueError) as error:
            resolve_apollo_key(source, phase=phase, expected_ref="KIVOU_APOLLO_API_KEY")
        assert source["KIVOU_APOLLO_API_KEY"] not in str(error.value)
    with pytest.raises(ValueError):
        resolve_apollo_key(source | {"KIVOU_ACQUISITION_ENVIRONMENT": "PRODUCTION"},
                           phase="COVERAGE_A1_SAMPLE", expected_ref="KIVOU_APOLLO_API_KEY")


def test_a1_permit_needs_a_frozen_plan_and_exact_database() -> None:
    _a1_permit()
    for changed in ({"sample_plan_hash": None}, {"max_credits": 82},
                    {"max_pages": 82}, {"max_enrichments": 1},
                    {"database_id": "postgresql:0123456789abcdef:kivou_staging"},
                    {"expires_at": NOW + dt.timedelta(hours=5)}):
        with pytest.raises(ValueError):
            _a1_permit(**changed)


def test_a1_permit_is_bound_to_frozen_pages_and_rejects_non_org_calls(monkeypatch) -> None:
    engine, census_id = _a0()
    store = CensusStore(engine)
    plan = SamplePlanStore(engine).plan(
        census_id, permit_id="synthetic-a1-permit", at=NOW,
    )
    limits = _a1_limits()
    pricing = _pricing(credit_balance=2126,
                       source_reference="operator-a1-prepaid-2026-09-21")
    source = OfficialSourceConfig(enabled=True, max_requests=600,
                                  rate_limit_per_minute=60)
    auth = DatabaseAuthorization(
        database_id="postgresql:0123456789abcdef:kivou_milomail_census_a0",
        environment="staging", issued_by_reference="synthetic-operator",
        expires_at=NOW + dt.timedelta(hours=3),
    )
    # The production-only PostgreSQL identity check is covered separately.
    monkeypatch.setattr(DatabaseAuthorization, "check", lambda *_args, **_kwargs: None)
    digest = configuration_hash(
        census_id=census_id, limits=limits, partitions=store.partitions(census_id),
        pricing=pricing, source_config=source,
        sample_plan_hash=plan["plan_hash"],
    )
    permit = _a1_permit(
        census_id=census_id, database_id=auth.database_id,
        allowed_partitions=tuple(row["partition_id"] for row in store.partitions(census_id)),
        sample_plan_hash=plan["plan_hash"], configuration_hash=digest,
    )
    PermitStore(engine).issue(permit, database=auth, pricing=pricing,
                              limits=limits, source_config=source, at=NOW)
    selected = plan["pages"][0]
    with engine.connect() as connection:
        PermitStore.check_call(
            connection, permit_id=permit.permit_id, census_id=census_id,
            phase="COVERAGE_A1_SAMPLE", kind="ORG_SEARCH",
            partition_id=selected["partition_id"],
            subject=f"{selected['partition_id']}:{selected['page']}",
            credits=1, candidate_slots=25, at=NOW,
            configuration_hash_value=digest, database_id=auth.database_id,
        )
        for kind, page in (("PEOPLE_SEARCH", selected["page"]),
                           ("ORG_ENRICH", selected["page"]),
                           ("ORG_SEARCH", 501)):
            with pytest.raises(ValueError):
                PermitStore.check_call(
                    connection, permit_id=permit.permit_id, census_id=census_id,
                    phase="COVERAGE_A1_SAMPLE", kind=kind,
                    partition_id=selected["partition_id"],
                    subject=f"{selected['partition_id']}:{page}",
                    credits=1, candidate_slots=25, at=NOW,
                    configuration_hash_value=digest, database_id=auth.database_id,
                )
    with pytest.raises(ValueError):
        PermitStore(engine).issue(permit.model_copy(update={
            "sample_plan_hash": "f" * 64,
        }), database=auth, pricing=pricing, limits=limits,
            source_config=source, at=NOW)


def test_a1_preflight_reports_frozen_plan_and_refuses_non_postgres(monkeypatch) -> None:
    engine, census_id = _a0()
    plan = SamplePlanStore(engine).plan(census_id, permit_id="synthetic-a1-permit", at=NOW)
    limits = _a1_limits()
    pricing = _pricing(credit_balance=2126,
                       source_reference="operator-a1-prepaid-2026-09-21")
    source = OfficialSourceConfig(enabled=True, max_requests=600,
                                  rate_limit_per_minute=60)
    auth = DatabaseAuthorization(
        database_id="postgresql:0123456789abcdef:kivou_milomail_census_a0",
        environment="staging", issued_by_reference="synthetic-operator",
        expires_at=NOW + dt.timedelta(hours=3),
    )
    monkeypatch.setattr(DatabaseAuthorization, "check", lambda *_args, **_kwargs: None)
    digest = configuration_hash(
        census_id=census_id, limits=limits,
        partitions=CensusStore(engine).partitions(census_id), pricing=pricing,
        source_config=source, sample_plan_hash=plan["plan_hash"],
    )
    PermitStore(engine).issue(_a1_permit(
        census_id=census_id, database_id=auth.database_id,
        allowed_partitions=tuple(row["partition_id"] for row in
                                 CensusStore(engine).partitions(census_id)),
        sample_plan_hash=plan["plan_hash"], configuration_hash=digest,
    ), database=auth, pricing=pricing, limits=limits, source_config=source, at=NOW)
    state = ApolloAccountState(
        True, 2126, True, True, {"lead_credit": 2126}, 9, 50_000,
    )
    result = preflight(
        engine, census_id=census_id, limits=limits, database=auth, pricing=pricing,
        apollo_key_present=True, source_enabled=True, source_requests=600,
        source_available=True, suppression_keyring=SuppressionIdentityKeyring(
            current_key_version="v1", keys={"v1": b"synthetic-key-material"},
        ), apollo_account=state, at=NOW, permit_id="synthetic-a1-permit",
        source_rate_limit_per_minute=60, source_config=source,
        phase="COVERAGE_A1_SAMPLE",
    )
    assert result["checks"]["sample_plan"] == "READY"
    assert result["checks"]["a0_cache"] == "READY"
    assert result["checks"]["organization_search_counter"] == "READY"
    assert result["checks"]["organizations_only"] == "READY"
    assert result["checks"]["postgresql"] == "NON_POSTGRESQL_DATABASE"
    assert not result["execution_authorized"]
