from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from test_policy_gateway import request
from test_policy_persistence import control

from signals.acquisition.contracts import ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.contact_discovery.contracts import (
    ContactObservation,
    ContactObservationConflict,
    ContactRunIdentityConflict,
    ContactRunStart,
    ContactRunStatus,
)
from signals.contact_discovery.identity import contact_ref_for
from signals.contact_discovery.profile import build_decision_maker_profile
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.policy.contracts import (
    BudgetUsage,
    EvidenceReadiness,
    EvidenceStatus,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate
from signals.supplier_discovery.store import SupplierDiscoveryStore

NOW = dt.datetime(2026, 8, 20, 12, tzinfo=dt.UTC)


@pytest.fixture
def context(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'contacts.db'}")
    command.upgrade(alembic_config(engine), "head")
    supplier = (
        SupplierDiscoveryStore(engine, clock=lambda: NOW)
        .upsert_supplier(
            ApolloOrganizationCandidate(
                provider_organization_id="apollo-org-1",
                display_name="Acme SA",
                normalized_name="acme sa",
                provider_observed_at=NOW,
                source_fingerprint="a" * 64,
            )
        )
        .supplier
    )
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    created = acquisition.create_opportunity(
        identity_key="seed:supplier-1",
        signal_ref="procurement-opportunity:opp-1",
        supplier_ref=supplier.supplier_ref,
        idempotency_key="create-contact-opportunity",
    )
    initialized = acquisition.append_in_transaction
    with engine.begin() as connection:
        initialized(
            connection,
            created.projection.acquisition_opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=1,
            idempotency_key="next-find-contacts",
            actor_type=ActorType.SYSTEM,
            payload={"next_action": "find_decision_makers"},
        )
    PolicyStore(engine).append_control(control(1, allowed_commands=("find_decision_makers",)))
    return (
        engine,
        supplier,
        acquisition.get_opportunity(created.projection.acquisition_opportunity_id),
    )


def _evaluate(engine, opportunity, evaluation_id: str):
    evidence = EvidenceReadiness(
        status=EvidenceStatus.READY,
        claims=("SUPPLIER", "CONTACT_SEARCH_PROFILE"),
        assessment_version="contact-evidence-v1",
        observed_at=NOW,
    )
    req = request(
        "find_decision_makers",
        evaluation_id=evaluation_id,
        request_id=f"request-{evaluation_id}",
        target_ref=f"acquisition-opportunity:{opportunity.acquisition_opportunity_id}",
        acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
        expected_opportunity_version=opportunity.stream_version,
        evidence=evidence,
        proposed_cost=Decimal("3"),
    )
    return PolicyGateway(engine).evaluate_and_record(
        req, evaluated_at=NOW, budget_usage=BudgetUsage()
    )


def _start(opportunity, supplier_ref: str, evaluation_id: str, run_id: str):
    profile = build_decision_maker_profile(
        acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
        supplier_ref=supplier_ref,
        provider_organization_id="apollo-org-1",
    )
    return ContactRunStart(
        contact_discovery_run_id=run_id,
        acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
        supplier_ref=supplier_ref,
        policy_evaluation_id=evaluation_id,
        profile=profile,
        provider_request_fingerprint="b" * 64,
        expected_post_policy_version=opportunity.stream_version + 1,
        started_at=NOW + dt.timedelta(seconds=1),
        correlation_id=run_id,
    )


def _observation(supplier_ref: str, *, observed_at=NOW, fingerprint="c" * 64):
    return ContactObservation(
        supplier_ref=supplier_ref,
        provider_person_id="apollo-person-1",
        provider_organization_id="apollo-org-1",
        first_name="Alice",
        last_name="Dupont",
        display_name="Alice Dupont",
        title="Sales Director",
        normalized_title="sales director",
        role_profile_version="decision-maker-search-v1",
        role_tier=1,
        business_email="alice@acme.example",
        provider_email_status="verified",
        verification_state="PROVIDER_VERIFIED",
        verification_provider="apollo",
        provider_observed_at=observed_at,
        email_observed_at=observed_at,
        source_fingerprint=fingerprint,
    )


def test_one_policy_evaluation_owns_at_most_one_contact_run(context) -> None:
    engine, supplier, opportunity = context
    _evaluate(engine, opportunity, "eval-1")
    store = ContactDiscoveryStore(engine)
    first = store.start_run(_start(opportunity, supplier.supplier_ref, "eval-1", "run-1"))
    replay = store.start_run(_start(opportunity, supplier.supplier_ref, "eval-1", "run-2"))

    assert first.owned is True
    assert first.run.status is ContactRunStatus.STARTED
    assert replay.owned is False
    assert replay.run.contact_discovery_run_id == "run-1"


def test_concurrent_contact_run_start_has_exactly_one_owner(context, monkeypatch) -> None:
    engine, supplier, opportunity = context
    _evaluate(engine, opportunity, "eval-1")
    store = ContactDiscoveryStore(engine)
    original = store._insert_run_if_absent
    barrier = threading.Barrier(2)

    def synchronized_insert(connection, values):
        barrier.wait(timeout=5)
        return original(connection, values)

    monkeypatch.setattr(store, "_insert_run_if_absent", synchronized_insert)
    results = []
    errors = []

    def claim(run_id):
        try:
            results.append(
                store.start_run(_start(opportunity, supplier.supplier_ref, "eval-1", run_id))
            )
        except (RuntimeError, sa.exc.SQLAlchemyError) as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=claim, args=(f"run-{index}",)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert sorted(result.owned for result in results) == [False, True]
    assert len({result.run.contact_discovery_run_id for result in results}) == 1


def test_run_id_collision_with_different_policy_is_typed(context) -> None:
    engine, supplier, opportunity = context
    _evaluate(engine, opportunity, "eval-1")
    opportunity = AcquisitionStore(engine).get_opportunity(opportunity.acquisition_opportunity_id)
    _evaluate(engine, opportunity, "eval-2")
    store = ContactDiscoveryStore(engine)
    store.start_run(
        _start(
            opportunity.model_copy(update={"stream_version": 2}),
            supplier.supplier_ref,
            "eval-1",
            "run-shared",
        )
    )

    with pytest.raises(ContactRunIdentityConflict):
        store.start_run(_start(opportunity, supplier.supplier_ref, "eval-2", "run-shared"))


def test_contact_observation_compare_and_set_is_deterministic(context) -> None:
    engine, supplier, _ = context
    store = ContactDiscoveryStore(engine, clock=lambda: NOW)
    original = _observation(supplier.supplier_ref)

    created = store.upsert_contact(original)
    exact_replay = store.upsert_contact(original)
    stale = store.upsert_contact(
        _observation(
            supplier.supplier_ref,
            observed_at=NOW - dt.timedelta(seconds=1),
            fingerprint="d" * 64,
        )
    )

    assert created.created is True
    assert exact_replay.metadata_updated is False
    assert stale.metadata_updated is False
    assert stale.contact.business_email == "alice@acme.example"


def test_equal_timestamp_different_fingerprint_conflicts(context) -> None:
    engine, supplier, _ = context
    store = ContactDiscoveryStore(engine, clock=lambda: NOW)
    store.upsert_contact(_observation(supplier.supplier_ref))

    with pytest.raises(ContactObservationConflict):
        store.upsert_contact(
            _observation(supplier.supplier_ref, fingerprint="e" * 64).model_copy(
                update={"business_email": "changed@acme.example"}
            )
        )

    assert (
        store.get_contact(
            contact_ref_for("apollo", "apollo-person-1", supplier.supplier_ref)
        ).business_email
        == "alice@acme.example"
    )


def test_newer_observation_updates_mutable_email_without_changing_identity(context) -> None:
    engine, supplier, _ = context
    store = ContactDiscoveryStore(engine, clock=lambda: NOW)
    original = store.upsert_contact(_observation(supplier.supplier_ref))
    newer = store.upsert_contact(
        _observation(
            supplier.supplier_ref,
            observed_at=NOW + dt.timedelta(seconds=1),
            fingerprint="f" * 64,
        ).model_copy(update={"business_email": "new@acme.example"})
    )

    assert newer.contact.contact_ref == original.contact.contact_ref
    assert newer.metadata_updated is True
    assert newer.contact.business_email == "new@acme.example"
