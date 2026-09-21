"""The census schema is additive and reversible on disposable databases."""

import datetime as dt
import os
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from test_milomail_policy import ready_config

from signals.acquisition_programs.census import CensusLimits, CensusStore, build_partitions
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    migrate_to_latest,
)
from signals.persistence.schema import METADATA
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate, SupplierSearchPage

TABLES = {
    "acquisition_census_run",
    "acquisition_census_partition",
    "acquisition_census_candidate",
    "acquisition_census_identity",
    "acquisition_census_occurrence",
    "acquisition_census_call",
}
READINESS_TABLES = {
    "acquisition_census_permit", "acquisition_census_official_cache",
    "acquisition_census_company_match",
}


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request):
    if request.param == "sqlite":
        database = sa.create_engine("sqlite:///:memory:")
        yield database
        database.dispose()
        return
    url = os.getenv("KIVOU_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("disposable PostgreSQL URL not configured")
    schema = f"milomail_census_test_{uuid.uuid4().hex}"
    admin = create_database_engine(url)
    with admin.begin() as connection:
        connection.execute(sa.schema.CreateSchema(schema))
    database = create_database_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield database
    finally:
        database.dispose()
        with admin.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True))
        admin.dispose()


def test_census_upgrade_downgrade(engine) -> None:
    command.upgrade(alembic_config(engine), "0070_program_conversion_receipt")
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    migrate_to_latest(engine)
    assert TABLES <= set(sa.inspect(engine).get_table_names())
    assert TABLES <= set(METADATA.tables)
    assert READINESS_TABLES <= set(sa.inspect(engine).get_table_names())
    assert READINESS_TABLES <= set(METADATA.tables)
    assert "permit_id" in {column["name"] for column in
                           sa.inspect(engine).get_columns("acquisition_census_call")}
    assert "official_requests_reserved" in {column["name"] for column in
                                            sa.inspect(engine).get_columns("acquisition_census_run")}
    command.downgrade(alembic_config(engine), "0071_milomail_shadow_census")
    assert READINESS_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    assert "permit_id" not in {column["name"] for column in
                               sa.inspect(engine).get_columns("acquisition_census_call")}
    assert "official_requests_reserved" not in {column["name"] for column in
                                                sa.inspect(engine).get_columns("acquisition_census_run")}
    command.downgrade(alembic_config(engine), "0070_program_conversion_receipt")
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())


def test_checkpoint_and_domain_dedup_on_both_dialects(engine) -> None:
    migrate_to_latest(engine)
    at = dt.datetime(2026, 9, 21, tzinfo=dt.UTC)
    config = ready_config()
    program_id = AcquisitionProgramStore(engine).register(config, at=at)
    store = CensusStore(engine, require_permit=False)
    run_id = store.plan(program_id=program_id, partitions=build_partitions(config), at=at)
    store.start(run_id, CensusLimits(
        enabled=True, max_partitions=2, max_pages=2, max_candidates=50,
        max_enrichments=1, max_apollo_credits=2, max_cost_chf="0.20",
        chf_per_credit_ceiling="0.10", authorization_ref="synthetic-test",
    ), at=at)
    first, second = store.partitions(run_id)[:2]
    for index, part in enumerate((first, second)):
        candidate = ApolloOrganizationCandidate(
            provider_organization_id=f"org-{index}", display_name="Cabinet Exemple",
            normalized_name="cabinet exemple", primary_domain="cabinet.fr",
            country_code="FR", provider_observed_at=at, source_fingerprint="a" * 64,
        )
        page = SupplierSearchPage(
            page=1, per_page=25, total_entries=1, total_pages=1,
            candidates=(candidate,), rejections=(),
        )
        call = store.reserve_call(
            run_id, kind="ORG_SEARCH", subject=f"{part['partition_id']}:1", attempt=1,
            partition_id=part["partition_id"], credits=1, candidate_slots=25, at=at,
        )
        store.complete_call(call["call_id"], page.model_dump(mode="json"), at=at)
        store.record_page(run_id, part["partition_id"], page, call_id=call["call_id"], at=at)
    assert len(store.candidates(run_id)) == 1
    assert sum(part["duplicate_count"] for part in store.partitions(run_id)) == 1
    assert store.status(run_id)["credits_reserved"] == 2
    store.pause(run_id, None, "USAGE_REVIEW", at=at, review=True)
    store.record_actual_usage(
        run_id, credits=2, cost_chf=Decimal("0.2000"),
        evidence_ref="synthetic-invoice-004", at=at,
    )
    assert store.report(run_id)["cost_chf_actual"] == "0.2000"
