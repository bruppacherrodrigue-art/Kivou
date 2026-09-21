"""Readiness gates are checked without a paid Apollo call or send path."""

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa
from test_milomail_census import _limits
from test_milomail_policy import ready_config

from signals.acquisition_programs.apollo_account import ApolloAccountProbe, ApolloAccountState
from signals.acquisition_programs.census import (
    CensusBudgetExceeded,
    CensusLimits,
    CensusStore,
    build_partitions,
)
from signals.acquisition_programs.census_readiness import (
    ApolloCreditPricing,
    DatabaseAuthorization,
    ExecutionPermit,
    PermitStore,
    configuration_hash,
    database_identity,
    preflight,
)
from signals.acquisition_programs.official_company import OfficialSourceConfig
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.database import migrate_to_latest

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)
KEYRING = SuppressionIdentityKeyring(current_key_version="v1", keys={"v1": b"synthetic-key-material"})


def _setup():
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_config().model_copy(update={
        "max_daily_contacts": 0, "max_monthly_contacts": 0, "max_cost_chf": Decimal(0),
    })
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    store = CensusStore(engine)
    census_id = store.plan(program_id=program_id, partitions=build_partitions(config), at=NOW)
    auth = DatabaseAuthorization(database_id=database_identity(engine)[0], environment="test",
                                 issued_by_reference="synthetic-review", expires_at=NOW + dt.timedelta(days=1))
    pricing = ApolloCreditPricing(
        currency="CHF", price_per_credit=Decimal("0.10"), verified_at=NOW,
        source_type="OPERATOR_ATTESTATION", source_reference="synthetic-price-proof",
        plan_name="synthetic-plan", verified_by_reference="synthetic-review",
        org_search_credits=1, org_enrichment_credits=1, people_search_credits=0,
        person_enrichment_credits_max=9, credit_balance=100,
        credit_balance_observed_at=NOW,
        rate_limits_per_minute={"ORG_SEARCH": 10, "ORG_ENRICH": 10,
                                "PEOPLE_SEARCH": 10, "PERSON_ENRICH": 10},
        rate_limit_reference="synthetic-rate-proof",
        credit_pools_by_operation={kind: "lead_credit" for kind in (
            "ORG_SEARCH", "ORG_ENRICH", "PEOPLE_SEARCH", "PERSON_ENRICH",
        )},
    )
    return engine, store, census_id, auth, pricing


def _permit(store, census_id, auth, pricing, limits, *, phase="COVERAGE", suffix="one"):
    digest = configuration_hash(census_id=census_id, limits=limits,
                                partitions=store.partitions(census_id), pricing=pricing)
    return ExecutionPermit(
        permit_id=f"synthetic-{suffix}-{phase.lower()}", census_id=census_id, phase=phase,
        environment=auth.environment, database_id=auth.database_id,
        allowed_partitions=tuple(row["partition_id"] for row in
                                 store.partitions(census_id)[:limits.max_partitions]),
        max_pages=limits.max_pages if phase == "COVERAGE" else 0,
        max_candidates=limits.max_candidates if phase == "COVERAGE" else 0,
        max_enrichments=limits.max_enrichments if phase == "ENRICHMENT" else 0,
        max_credits=limits.max_apollo_credits, max_cost_chf=limits.max_cost_chf,
        price_chf_per_credit=pricing.price_per_credit,
        pricing_reference=pricing.source_reference, configuration_hash=digest,
        issued_by_reference="synthetic-review", issued_at=NOW,
        valid_from=NOW, expires_at=NOW + dt.timedelta(days=1),
    )


def _preflight(engine, census_id, limits, auth, pricing, *, account=None, source=True,
               keyring=KEYRING):
    return preflight(
        engine, census_id=census_id, limits=limits, database=auth, pricing=pricing,
        apollo_key_present=True, source_enabled=source, source_requests=10,
        source_available=source, suppression_keyring=keyring,
        apollo_account=account or ApolloAccountState(
            True, 100, True, True, {"lead_credit": 100},
        ), at=NOW,
    )


def test_preflight_distinguishes_technical_readiness_from_permit() -> None:
    engine, store, census_id, auth, pricing = _setup()
    limits = _limits()
    report = _preflight(engine, census_id, limits, auth, pricing)
    assert report["technically_ready"]
    assert not report["execution_authorized"]
    assert report["checks"]["execution_permit"] == "NOT_ISSUED_OR_INVALID"
    assert report["instantly_mutation_allowed"] is False
    assert report["credits_available"] == 100
    permit = _permit(store, census_id, auth, pricing, limits)
    PermitStore(engine).issue(permit, database=auth, pricing=pricing, limits=limits, at=NOW)
    report = preflight(
        engine, census_id=census_id, limits=limits, database=auth, pricing=pricing,
        apollo_key_present=True, source_enabled=True, source_requests=10,
        source_available=True, suppression_keyring=KEYRING,
        apollo_account=ApolloAccountState(True, 100, True, True,
                                         {"lead_credit": 100}), at=NOW,
        permit_id=permit.permit_id,
    )
    assert report["execution_authorized"]
    assert not report["enrichment_authorized"]
    assert report["worst_cost_chf"] == "2.00"


def test_coverage_accepts_bounded_credits_with_zero_enrichment() -> None:
    engine, _store, census_id, auth, pricing = _setup()
    limits = _limits(max_partitions=9, max_pages=9, max_candidates=225,
                     max_enrichments=0, max_apollo_credits=9,
                     max_cost_chf="0.90")
    limits.require_run_authorization(phase="COVERAGE")
    with pytest.raises(ValueError, match="explicit census authorization"):
        limits.require_run_authorization(phase="ENRICHMENT")
    report = preflight(
        engine, census_id=census_id, limits=limits, database=auth, pricing=pricing,
        apollo_key_present=True, source_enabled=True, source_requests=10,
        source_available=True, suppression_keyring=KEYRING,
        apollo_account=ApolloAccountState(True, 100, True, True,
                                         {"lead_credit": 100}), at=NOW,
        phase="COVERAGE", source_rate_limit_per_minute=60,
    )
    assert report["checks"]["limits"] == "READY"
    assert report["checks"]["no_enrichment"] == "READY"
    assert report["checks"]["operation_cost"] == "READY"
    assert report["checks"]["postgresql"] == "NON_POSTGRESQL_DATABASE"
    assert not report["execution_authorized"]


def test_coverage_zero_credit_cap_still_blocks_org_search() -> None:
    engine, _store, census_id, auth, pricing = _setup()
    limits = _limits(max_enrichments=0, max_apollo_credits=0,
                     max_cost_chf="0")
    report = preflight(
        engine, census_id=census_id, limits=limits, database=auth, pricing=pricing,
        apollo_key_present=True, source_enabled=True, source_requests=10,
        source_available=True, suppression_keyring=KEYRING,
        apollo_account=ApolloAccountState(True, 100, True, True,
                                         {"lead_credit": 100}), at=NOW,
        phase="COVERAGE", source_rate_limit_per_minute=60,
    )
    assert report["checks"]["operation_cost"] == "ORG_SEARCH_REQUIRES_CREDIT"
    assert not report["execution_authorized"]


def test_preflight_requires_balance_in_each_attested_credit_pool() -> None:
    engine, _store, census_id, auth, pricing = _setup()
    pools = {**pricing.credit_pools_by_operation, "ORG_SEARCH": "export_credit"}
    split_pricing = pricing.model_copy(update={"credit_pools_by_operation": pools})
    missing_pool = _preflight(engine, census_id, _limits(), auth, split_pricing)
    assert missing_pool["checks"]["apollo_account"] == "NOT_PROBED_OR_CAPACITY_UNKNOWN"
    verified = _preflight(
        engine, census_id, _limits(), auth, split_pricing,
        account=ApolloAccountState(True, 100, True, True,
                                   {"lead_credit": 100, "export_credit": 100}),
    )
    assert verified["checks"]["apollo_account"] == "READY"
    assert verified["credit_balances_by_pool"] == {
        "export_credit": 100, "lead_credit": 100,
    }


@pytest.mark.parametrize("change,expected", [
    ({"apollo_key_present": False}, "apollo_key"),
    ({"source_enabled": False}, "official_source"),
    ({"suppression_keyring": None}, "suppression"),
    ({"pricing": None}, "pricing"),
    ({"database": None}, "database"),
])
def test_preflight_missing_prerequisite_is_explicit(change, expected) -> None:
    engine, _store, census_id, auth, pricing = _setup()
    inputs = {"engine": engine, "census_id": census_id, "limits": _limits(), "database": auth,
              "pricing": pricing, "apollo_key_present": True, "source_enabled": True,
              "source_requests": 10, "source_available": True,
              "suppression_keyring": KEYRING,
              "apollo_account": ApolloAccountState(True, 100, True, True,
                                                    {"lead_credit": 100}), "at": NOW}
    inputs.update(change)
    result = preflight(**inputs)
    assert expected in result["blockers"]
    assert not result["technically_ready"]


def test_zero_caps_stale_price_and_wrong_database_fail() -> None:
    engine, _store, census_id, auth, pricing = _setup()
    assert "limits" in _preflight(engine, census_id, CensusLimits(), auth, pricing)["blockers"]
    stale = pricing.model_copy(update={"verified_at": NOW - dt.timedelta(days=31)})
    assert "pricing" in _preflight(engine, census_id, _limits(), auth, stale)["blockers"]
    incoherent = _limits(max_cost_chf="0.10")
    assert "pricing" in _preflight(engine, census_id, incoherent, auth, pricing)["blockers"]
    wrong = auth.model_copy(update={"database_id": "sqlite:wrong:other"})
    assert "database" in _preflight(engine, census_id, _limits(), wrong, pricing)["blockers"]


def test_second_alembic_revision_is_reported_as_divergence() -> None:
    engine, _store, census_id, auth, pricing = _setup()
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('unexpected')"))
    report = _preflight(engine, census_id, _limits(), auth, pricing)
    assert report["checks"]["migration"] == "MISSING_OR_DIVERGED"
    assert len(report["database"]["all_revisions"]) == 2


def test_production_environment_is_rejected_even_with_matching_database_id(monkeypatch) -> None:
    engine, _store, census_id, auth, pricing = _setup()
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "PRODUCTION")
    report = _preflight(engine, census_id, _limits(), auth, pricing)
    assert report["checks"]["database"] == "UNAUTHORIZED_EXPIRED_OR_DIVERGED"
    assert not report["technically_ready"]


def test_short_prod_environment_and_prod_host_are_rejected(monkeypatch) -> None:
    engine, _store, _census_id, auth, _pricing = _setup()
    monkeypatch.setenv("KIVOU_ENVIRONMENT", "prod")
    with pytest.raises(ValueError, match="production"):
        auth.check_identity(engine, at=NOW)
    monkeypatch.delenv("KIVOU_ENVIRONMENT")
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    hosted = sa.create_engine("postgresql+psycopg://host:secret@prod-db.example/approved")
    hosted_auth = auth.model_copy(update={
        "database_id": database_identity(hosted)[0], "environment": "staging",
    })
    with pytest.raises(ValueError, match="production"):
        hosted_auth.check_identity(hosted, at=NOW)


def test_preflight_does_not_create_missing_sqlite_database(tmp_path) -> None:
    path = tmp_path / "missing.sqlite"
    engine = sa.create_engine(f"sqlite:///{path}")
    with pytest.raises(ValueError, match="cannot create"):
        database_identity(engine)
    assert not path.exists()


def test_permit_required_caps_idempotence_and_revoke() -> None:
    engine, store, census_id, auth, pricing = _setup()
    limits = _limits(max_partitions=1, max_pages=1, max_candidates=25,
                     max_apollo_credits=1, max_cost_chf="0.10")
    store.start(census_id, limits, at=NOW)
    partition = store.partitions(census_id)[0]["partition_id"]
    with pytest.raises(ValueError, match="permit"):
        store.reserve_call(census_id, kind="ORG_SEARCH", subject="one", attempt=1,
                           partition_id=partition, credits=1, candidate_slots=25, at=NOW)
    permit = _permit(store, census_id, auth, pricing, limits)
    permits = PermitStore(engine)
    permits.issue(permit, database=auth, pricing=pricing, limits=limits, at=NOW)
    permits.issue(permit, database=auth, pricing=pricing, limits=limits, at=NOW)
    store.bind_permit(permit_id=permit.permit_id, phase="COVERAGE",
                      configuration_hash=permit.configuration_hash, database_id=auth.database_id)
    call = store.reserve_call(census_id, kind="ORG_SEARCH", subject="one", attempt=1,
                              partition_id=partition, credits=1, candidate_slots=25, at=NOW)
    assert call["permit_id"] == permit.permit_id
    assert store.reserve_call(census_id, kind="ORG_SEARCH", subject="one", attempt=1,
                              partition_id=partition, credits=1, candidate_slots=25,
                              at=NOW)["call_id"] == call["call_id"]
    with pytest.raises(CensusBudgetExceeded):
        store.reserve_call(census_id, kind="ORG_SEARCH", subject="two", attempt=1,
                           partition_id=partition, credits=1, candidate_slots=25, at=NOW)
    permits.revoke(permit.permit_id)
    with pytest.raises(ValueError, match="permit"):
        store.reserve_call(census_id, kind="ORG_SEARCH", subject="three", attempt=1,
                           partition_id=partition, credits=1, candidate_slots=25, at=NOW)


def test_permit_expiry_environment_and_config_change_block_before_call() -> None:
    engine, store, census_id, auth, pricing = _setup()
    limits = _limits()
    permit = _permit(store, census_id, auth, pricing, limits)
    with pytest.raises(ValueError, match="environment"):
        PermitStore(engine).issue(permit.model_copy(update={"environment": "staging"}),
                                  database=auth, pricing=pricing, limits=limits, at=NOW)
    PermitStore(engine).issue(permit, database=auth, pricing=pricing, limits=limits, at=NOW)
    partition = store.partitions(census_id)[0]["partition_id"]
    with engine.connect() as connection:
        base = {"connection": connection, "permit_id": permit.permit_id,
                "census_id": census_id, "phase": "COVERAGE", "kind": "ORG_SEARCH",
                "partition_id": partition, "credits": 1, "candidate_slots": 25,
                "configuration_hash_value": permit.configuration_hash,
                "database_id": auth.database_id}
        with pytest.raises(ValueError, match="permit"):
            PermitStore.check_call(**{**base, "at": NOW + dt.timedelta(days=2)})
        with pytest.raises(ValueError, match="permit"):
            PermitStore.check_call(**{**base, "at": NOW,
                                      "configuration_hash_value": "f" * 64})
        with pytest.raises(ValueError, match="permit"):
            PermitStore.check_call(**{**base, "at": NOW, "database_id": "other-db"})
        with pytest.raises(ValueError, match="phase"):
            PermitStore.check_call(**{**base, "at": NOW, "kind": "PERSON_ENRICH"})


def test_permit_cannot_understate_verified_price_or_exceed_limits() -> None:
    engine, store, census_id, auth, pricing = _setup()
    limits = _limits()
    permit = _permit(store, census_id, auth, pricing, limits)
    underpriced = permit.model_copy(update={"price_chf_per_credit": Decimal("0.01")})
    with pytest.raises(ValueError, match="price"):
        PermitStore(engine).issue(underpriced, database=auth, pricing=pricing,
                                  limits=limits, at=NOW)
    too_many_pages = permit.model_copy(update={"max_pages": limits.max_pages + 1})
    with pytest.raises(ValueError, match="limits"):
        PermitStore(engine).issue(too_many_pages, database=auth, pricing=pricing,
                                  limits=limits, at=NOW)


def test_official_request_cap_change_invalidates_permit_configuration() -> None:
    engine, store, census_id, auth, pricing = _setup()
    limits = _limits()
    permit = _permit(store, census_id, auth, pricing, limits)
    source = OfficialSourceConfig(enabled=True, max_requests=10)
    with pytest.raises(ValueError, match="configuration hash"):
        PermitStore(engine).issue(permit, database=auth, pricing=pricing,
                                  limits=limits, at=NOW, source_config=source)


def test_preflight_rejects_exhausted_permit_and_uncovered_suppression_key() -> None:
    engine, store, census_id, auth, pricing = _setup()
    limits = _limits(max_partitions=1, max_pages=1, max_candidates=25,
                     max_apollo_credits=1, max_cost_chf="0.10")
    permit = _permit(store, census_id, auth, pricing, limits)
    PermitStore(engine).issue(permit, database=auth, pricing=pricing, limits=limits, at=NOW)
    store.start(census_id, limits, at=NOW)
    store.bind_permit(permit_id=permit.permit_id, phase="COVERAGE",
                      configuration_hash=permit.configuration_hash, database_id=auth.database_id)
    store.reserve_call(census_id, kind="ORG_SEARCH", subject="one", attempt=1,
                       partition_id=permit.allowed_partitions[0], credits=1,
                       candidate_slots=25, at=NOW)
    report = preflight(
        engine, census_id=census_id, limits=limits, database=auth, pricing=pricing,
        apollo_key_present=True, source_enabled=True, source_requests=10,
        source_available=True, suppression_keyring=KEYRING,
        apollo_account=ApolloAccountState(True, 100, True, True,
                                         {"lead_credit": 100}), at=NOW,
        permit_id=permit.permit_id,
    )
    assert report["checks"]["execution_permit"] == "NOT_ISSUED_OR_INVALID"
    assert report["permit_remaining"]["credits"] == 0


def test_free_apollo_probe_only_calls_documented_zero_credit_endpoints() -> None:
    paths = []

    def handle(request):
        paths.append((request.method, request.url.path))
        if request.url.path.endswith("auth/health"):
            return httpx.Response(200, json={"healthy": True, "is_logged_in": True})
        if request.url.path.endswith("credit_usage_stats"):
            return httpx.Response(200, json={"credit_usage_stats": {
                "lead_credit": {"left_over": 25}, "export_credit": {"left_over": 11}}})
        return httpx.Response(200, json={"api_usage_stats": {}})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    result = ApolloAccountProbe(api_key="synthetic-secret", client=client).inspect_free()
    assert result.credit_balance == 25
    assert result.credit_balances == {"lead_credit": 25, "export_credit": 11}
    assert paths == [
        ("GET", "/api/v1/auth/health"),
        ("POST", "/api/v1/usage_stats/credit_usage_stats"),
        ("POST", "/api/v1/usage_stats/api_usage_stats"),
    ]


def test_apollo_health_requires_both_official_success_flags() -> None:
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"healthy": True, "is_logged_in": False}),
    ))
    state = ApolloAccountProbe(api_key="synthetic-secret", client=client).inspect_free()
    assert not state.credential_valid
    assert state.credit_balance is None
