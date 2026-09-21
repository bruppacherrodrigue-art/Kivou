"""A1 plan persists before payment and reuses the nine A0 response snapshots."""

import datetime as dt

import pytest
import sqlalchemy as sa
from test_milomail_policy import ready_config

from signals.acquisition_programs.census import CensusLimits, CensusStore, build_partitions
from signals.acquisition_programs.census_sampling import SamplePlanStore
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.persistence.database import migrate_to_latest
from signals.supplier_discovery.contracts import SupplierSearchPage

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _a0():
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_config()
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    store = CensusStore(engine, require_permit=False)
    census_id = store.plan(program_id=program_id, partitions=build_partitions(config), at=NOW)
    limits = CensusLimits(
        enabled=True, authorization_ref="synthetic-a0", max_partitions=9,
        max_pages=9, max_candidates=225, max_enrichments=0,
        max_apollo_credits=9, max_cost_chf=0, chf_per_credit_ceiling=0,
    )
    store.start(census_id, limits, at=NOW, phase="COVERAGE_A0")
    for partition in store.partitions(census_id):
        page = SupplierSearchPage(
            page=1, per_page=25, total_entries=750, total_pages=30,
            candidates=(), rejections=(),
        )
        saved, call_id = store.execute_call(
            census_id, kind="ORG_SEARCH", subject=f"{partition['partition_id']}:1",
            partition_id=partition["partition_id"], credits=1, candidate_slots=25,
            at=NOW, invoke=lambda response=page: response,
            encode=lambda value: value.model_dump(mode="json"),
            decode=SupplierSearchPage.model_validate,
        )
        store.record_page(census_id, partition["partition_id"], saved, call_id=call_id,
                          at=NOW)
    return engine, census_id


def test_plan_is_immutable_and_recovers_the_nine_cached_a0_pages() -> None:
    engine, census_id = _a0()
    planning = SamplePlanStore(engine)
    permit_id = "synthetic-a1-permit"
    first = planning.plan(census_id, permit_id=permit_id, max_new_pages=81, at=NOW)
    assert first["a0_cached_pages"] == 9
    assert first["new_pages_planned"] == 81
    assert len(first["pages"]) == 81
    assert len({(row["partition_id"], row["page"]) for row in first["pages"]}) == 81
    assert all(row["page"] > 1 for row in first["pages"])
    assert planning.plan(census_id, permit_id=permit_id, max_new_pages=81, at=NOW) == first
    with pytest.raises(ValueError, match="immutable"):
        planning.plan(census_id, permit_id=permit_id, max_new_pages=72, at=NOW)


def test_missing_a0_cache_blocks_sample_plan_without_provider_call() -> None:
    engine, census_id = _a0()
    with engine.begin() as connection:
        connection.execute(sa.text(
            "UPDATE acquisition_census_call SET result_snapshot = NULL "
            "WHERE call_id = (SELECT call_id FROM acquisition_census_call LIMIT 1)"
        ))
    with pytest.raises(ValueError, match="A0 cache"):
        SamplePlanStore(engine).plan(census_id, permit_id="synthetic-a1", at=NOW)
