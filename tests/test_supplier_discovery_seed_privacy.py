from __future__ import annotations

import inspect

import sqlalchemy as sa
from feed_helpers import MATERIALIZED_AT, MATERIALIZED_ON, simap_award

import signals.supplier_discovery.profile as profile_module
import signals.supplier_discovery.seed as seed_module
import signals.supplier_discovery.service as service_module
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import opportunity_representation
from signals.supplier_discovery.contracts import SupplierTargetingConfig
from signals.supplier_discovery.seed import (
    build_profile_from_seed,
    resolve_acquisition_seed,
)


def test_public_opportunity_resolves_to_customer_independent_acquisition_seed(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'public-seed.db'}")
    migrate_to_latest(engine)
    event, awards = simap_award("33112-02")
    IngestionPipeline(engine).process(
        AcquiredPublication(event, awards),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )
    with engine.connect() as connection:
        opportunity_key = connection.scalar(
            sa.select(opportunity_representation.c.opportunity_key).limit(1)
        )

    seed = resolve_acquisition_seed(engine, opportunity_key)
    profile = build_profile_from_seed(seed, targeting=SupplierTargetingConfig())
    service = service_module.SupplierDiscoveryService(engine, provider=object())
    production_profile = service._resolve_persisted_profile(
        opportunity_key, SupplierTargetingConfig()
    )

    assert seed.signal_ref == f"procurement-opportunity:{opportunity_key}"
    assert seed.opportunity_key == opportunity_key
    assert seed.understanding.award_ref == seed.award.event_ref
    assert seed.needs.award_ref == seed.award.event_ref
    assert profile.signal_ref == seed.signal_ref
    assert profile.representative_award_key == seed.representative_award_key
    assert profile.need_categories == tuple(
        sorted(need.category for need in seed.needs.needs)
    )
    assert production_profile == profile


def test_public_service_boundary_accepts_seed_key_not_prebuilt_provider_profile() -> None:
    parameters = inspect.signature(
        service_module.SupplierDiscoveryService.discover
    ).parameters
    assert "opportunity_key" in parameters
    assert "targeting" in parameters
    assert "profile" not in parameters


def test_supplier_discovery_modules_have_no_customer_private_dependencies() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (seed_module, profile_module, service_module)
    )
    for forbidden in (
        "signals.accounts",
        "signals.billing",
        "signals.matching",
        "TargetICP",
        "materialized_signal",
        "customer feedback",
    ):
        assert forbidden not in source
