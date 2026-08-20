from __future__ import annotations

import datetime as dt
import threading
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command

from signals.persistence.database import alembic_config, create_database_engine
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate, SupplierIdentityStatus
from signals.supplier_discovery.identity import supplier_ref_for
from signals.supplier_discovery.store import SupplierDiscoveryStore

NOW = dt.datetime(2026, 8, 20, 9, tzinfo=dt.UTC)


@pytest.fixture
def store(tmp_path) -> SupplierDiscoveryStore:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'suppliers.db'}")
    command.upgrade(alembic_config(engine), "head")
    return SupplierDiscoveryStore(engine)


def candidate(
    provider_id: str,
    *,
    name: str = "Acme SA",
    domain: str | None = "acme.example",
    observed_at: dt.datetime = NOW,
    website: str | None = "https://acme.example",
    fingerprint: str = "a" * 64,
) -> ApolloOrganizationCandidate:
    return ApolloOrganizationCandidate(
        provider_organization_id=provider_id,
        display_name=name,
        normalized_name=name.casefold(),
        primary_domain=domain,
        website_url=website,
        provider_observed_at=observed_at,
        source_fingerprint=fingerprint,
    )


def test_supplier_ref_is_kivou_owned_stable_and_provider_scoped() -> None:
    value = supplier_ref_for("apollo", "apollo-org-1")
    assert value == supplier_ref_for("apollo", "apollo-org-1")
    assert value != supplier_ref_for("apollo", "apollo-org-2")
    assert value.startswith("sup_")
    assert len(value) == 64


def test_replay_updates_only_with_equal_or_newer_provider_observation(store) -> None:
    first = store.upsert_supplier(candidate("apollo-org-1"))
    newer = store.upsert_supplier(
        candidate(
            "apollo-org-1",
            name="Acme Suisse SA",
            observed_at=NOW + dt.timedelta(hours=1),
            website="https://new.acme.example",
            fingerprint="b" * 64,
        )
    )
    stale = store.upsert_supplier(
        candidate(
            "apollo-org-1",
            name="Old Acme",
            observed_at=NOW - dt.timedelta(hours=1),
            website="https://old.acme.example",
            fingerprint="c" * 64,
        )
    )

    assert first.created is True
    assert newer.created is False and newer.metadata_updated is True
    assert stale.metadata_updated is False
    stored = store.get_supplier(first.supplier.supplier_ref)
    assert stored.display_name == "Acme Suisse SA"
    assert stored.website_url == "https://new.acme.example"
    assert stored.source_fingerprint == "b" * 64


def test_domain_conflict_marks_all_existing_and_new_suppliers_symmetrically(store) -> None:
    first = store.upsert_supplier(candidate("apollo-org-1"))
    second = store.upsert_supplier(candidate("apollo-org-2", name="Acme Group"))

    reloaded_first = store.get_supplier(first.supplier.supplier_ref)
    reloaded_second = store.get_supplier(second.supplier.supplier_ref)
    assert reloaded_first.supplier_ref != reloaded_second.supplier_ref
    assert reloaded_first.identity_status is SupplierIdentityStatus.DOMAIN_CONFLICT
    assert reloaded_second.identity_status is SupplierIdentityStatus.DOMAIN_CONFLICT
    assert reloaded_first.identity_conflict_fingerprint == (
        reloaded_second.identity_conflict_fingerprint
    )
    assert len(reloaded_first.identity_conflict_fingerprint or "") == 64


def test_newer_observation_removing_domain_clears_conflict_for_both_suppliers(
    store,
) -> None:
    first = store.upsert_supplier(candidate("apollo-org-1"))
    second = store.upsert_supplier(candidate("apollo-org-2", name="Acme Group"))

    store.upsert_supplier(
        candidate(
            "apollo-org-1",
            domain=None,
            observed_at=NOW + dt.timedelta(minutes=1),
        )
    )

    reloaded_first = store.get_supplier(first.supplier.supplier_ref)
    reloaded_second = store.get_supplier(second.supplier.supplier_ref)
    assert reloaded_first.primary_domain is None
    assert reloaded_first.identity_status is SupplierIdentityStatus.PROVIDER_IDENTIFIED
    assert reloaded_first.identity_conflict_fingerprint is None
    assert reloaded_second.identity_status is SupplierIdentityStatus.PROVIDER_IDENTIFIED
    assert reloaded_second.identity_conflict_fingerprint is None


def test_concurrent_same_provider_identity_replays_without_raw_integrity_error(
    store
) -> None:
    engine = store._engine
    barrier = threading.Barrier(2)
    seen: set[int] = set()
    lock = threading.Lock()

    @sa.event.listens_for(engine, "before_cursor_execute")
    def synchronize_identity_insert(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        if not statement.lstrip().upper().startswith("INSERT"):
            return
        if "acquisition_supplier" not in statement:
            return
        thread_id = threading.get_ident()
        with lock:
            if thread_id in seen:
                return
            seen.add(thread_id)
        barrier.wait(timeout=5)

    results = []
    errors = []

    def persist() -> None:
        try:
            results.append(store.upsert_supplier(candidate("apollo-org-race")))
        except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=persist) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    sa.event.remove(engine, "before_cursor_execute", synchronize_identity_insert)

    assert not errors
    assert len(results) == 2
    assert len({result.supplier.supplier_ref for result in results}) == 1


def test_metadata_update_uses_database_timestamp_compare_and_set(store) -> None:
    store.upsert_supplier(candidate("apollo-org-cas", observed_at=NOW))
    statements: list[str] = []

    @sa.event.listens_for(store._engine, "before_cursor_execute")
    def capture_update(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        if statement.lstrip().upper().startswith("UPDATE ACQUISITION_SUPPLIER"):
            statements.append(statement)

    store.upsert_supplier(
        candidate("apollo-org-cas", observed_at=NOW + dt.timedelta(minutes=1))
    )
    sa.event.remove(store._engine, "before_cursor_execute", capture_update)

    metadata_updates = [
        statement for statement in statements if "provider_observed_at" in statement
    ]
    assert metadata_updates
    assert any("provider_observed_at <=" in statement for statement in metadata_updates)


def test_postgresql_domain_conflicts_take_sorted_transaction_advisory_locks() -> None:
    statements = []

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, statement):
            statements.append(statement)

    SupplierDiscoveryStore._lock_domains(
        FakeConnection(), ("alpha.example", "beta.example")
    )

    assert len(statements) == 2
    assert all("pg_advisory_xact_lock" in str(statement) for statement in statements)
    assert str(statements[0]) != str(statements[1]) or (
        statements[0].compile().params != statements[1].compile().params
    )


def test_concurrent_distinct_provider_ids_mark_domain_conflict_symmetrically(
    store,
) -> None:
    engine = store._engine
    barrier = threading.Barrier(2)
    seen: set[int] = set()
    lock = threading.Lock()

    @sa.event.listens_for(engine, "before_cursor_execute")
    def synchronize_insert(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        if not statement.lstrip().upper().startswith("INSERT"):
            return
        if "acquisition_supplier" not in statement:
            return
        thread_id = threading.get_ident()
        with lock:
            if thread_id in seen:
                return
            seen.add(thread_id)
        barrier.wait(timeout=5)

    results = []
    errors = []

    def persist(provider_id: str) -> None:
        try:
            results.append(store.upsert_supplier(candidate(provider_id)))
        except (RuntimeError, sa.exc.SQLAlchemyError) as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=persist, args=(f"apollo-domain-race-{index}",))
        for index in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    sa.event.remove(engine, "before_cursor_execute", synchronize_insert)

    assert not errors
    assert len(results) == 2
    stored = [store.get_supplier(result.supplier.supplier_ref) for result in results]
    assert all(
        supplier.identity_status is SupplierIdentityStatus.DOMAIN_CONFLICT
        for supplier in stored
    )
    assert len({supplier.identity_conflict_fingerprint for supplier in stored}) == 1
