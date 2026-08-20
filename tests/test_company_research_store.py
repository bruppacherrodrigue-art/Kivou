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
from signals.company_research.contracts import (
    CompanyResearchObservationConflict,
    CompanyResearchRunIdentityConflict,
    CompanyResearchRunStart,
    CompanyResearchRunStatus,
)
from signals.company_research.prebuild import build_acquisition_prospect_prebuild
from signals.company_research.profile import build_company_research_profile
from signals.company_research.store import CompanyResearchStore
from signals.contact_discovery.contracts import ContactObservation
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.policy.contracts import BudgetUsage, EvidenceReadiness, EvidenceStatus
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate
from signals.supplier_discovery.store import SupplierDiscoveryStore

NOW = dt.datetime(2026, 8, 20, 12, tzinfo=dt.UTC)


@pytest.fixture
def context(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'company.db'}")
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
        idempotency_key="create-company-opportunity",
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    contacts = ContactDiscoveryStore(engine, clock=lambda: NOW)
    contact = contacts.upsert_contact(
        ContactObservation(
            supplier_ref=supplier.supplier_ref,
            provider_person_id="person-1",
            provider_organization_id="apollo-org-1",
            title="Sales Director",
            normalized_title="sales director",
            role_tier=1,
            business_email="buyer@acme.example",
            provider_email_status="verified",
            provider_observed_at=NOW,
            email_observed_at=NOW,
            source_fingerprint="b" * 64,
        )
    ).contact
    with engine.begin() as connection:
        selected = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.CONTACT_SELECTED,
            expected_version=1,
            idempotency_key="select-contact",
            actor_type=ActorType.SYSTEM,
            payload={"contact_ref": contact.contact_ref, "supplier_ref": supplier.supplier_ref},
        )
        transitioned = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.STATE_TRANSITIONED,
            expected_version=selected.projection.stream_version,
            idempotency_key="start-enriching",
            actor_type=ActorType.SYSTEM,
            payload={"target_state": "ENRICHING"},
        )
        acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=transitioned.projection.stream_version,
            idempotency_key="next-enrich-company",
            actor_type=ActorType.SYSTEM,
            payload={"next_action": "enrich_company"},
        )
    PolicyStore(engine).append_control(control(1, allowed_commands=("enrich_company",)))
    opportunity = acquisition.get_opportunity(opportunity_id)
    evidence = EvidenceReadiness(
        status=EvidenceStatus.READY,
        claims=("SUPPLIER", "VERIFIED_CONTACT", "COMPANY_RESEARCH_PROFILE"),
        assessment_version="company-evidence-v1",
        observed_at=NOW,
    )
    decision = PolicyGateway(engine).evaluate_and_record(
        request(
            "enrich_company",
            evaluation_id="eval-1",
            target_ref=f"acquisition-opportunity:{opportunity_id}",
            acquisition_opportunity_id=opportunity_id,
            expected_opportunity_version=opportunity.stream_version,
            evidence=evidence,
            proposed_cost=Decimal("1"),
        ),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )
    assert decision.executable
    return engine, supplier, contact, acquisition.get_opportunity(opportunity_id)


def _start(opportunity, supplier_ref: str, contact_ref: str, *, run_id="run-1"):
    profile = build_company_research_profile("apollo-org-1")
    return CompanyResearchRunStart(
        company_research_run_id=run_id,
        acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
        supplier_ref=supplier_ref,
        contact_ref=contact_ref,
        policy_evaluation_id="eval-1",
        profile=profile,
        provider_request_fingerprint="c" * 64,
        expected_post_policy_version=opportunity.stream_version,
        started_at=NOW + dt.timedelta(seconds=1),
        correlation_id=run_id,
    )


def _prebuild(opportunity, supplier, contact, *, observed_at=NOW, source="d" * 64):
    from signals.company_research.contracts import ApolloOrganizationObservation

    observation = ApolloOrganizationObservation(
        provider_organization_id="apollo-org-1",
        provider_company_name="Acme SA",
        provider_primary_domain="acme.example",
        provider_country="CH",
        provider_industry="software",
        provider_employee_count=42,
        provider_observed_at=observed_at,
        provider_source_fingerprint=source,
    )
    return build_acquisition_prospect_prebuild(
        acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
        signal_ref=opportunity.signal_ref,
        supplier_ref=supplier.supplier_ref,
        contact_ref=contact.contact_ref,
        supplier_identity_status=supplier.identity_status,
        contact_role_profile_version=contact.role_profile_version,
        contact_role_tier=contact.role_tier,
        observation=observation,
    )


def test_one_policy_evaluation_owns_at_most_one_company_run(context) -> None:
    engine, supplier, contact, opportunity = context
    store = CompanyResearchStore(engine)

    first = store.start_run(_start(opportunity, supplier.supplier_ref, contact.contact_ref))
    replay = store.start_run(
        _start(opportunity, supplier.supplier_ref, contact.contact_ref, run_id="run-2")
    )

    assert first.owned is True
    assert first.run.status is CompanyResearchRunStatus.STARTED
    assert replay.owned is False
    assert replay.run.company_research_run_id == "run-1"


def test_concurrent_company_run_start_has_exactly_one_owner(context, monkeypatch) -> None:
    engine, supplier, contact, opportunity = context
    store = CompanyResearchStore(engine)
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
                store.start_run(
                    _start(
                        opportunity,
                        supplier.supplier_ref,
                        contact.contact_ref,
                        run_id=run_id,
                    )
                )
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
    assert len({result.run.company_research_run_id for result in results}) == 1


def test_run_id_collision_with_different_policy_is_typed(context) -> None:
    engine, supplier, contact, opportunity = context
    store = CompanyResearchStore(engine)
    store.start_run(_start(opportunity, supplier.supplier_ref, contact.contact_ref))

    conflicting = _start(
        opportunity,
        supplier.supplier_ref,
        contact.contact_ref,
    ).model_copy(update={"policy_evaluation_id": "different-evaluation"})
    with pytest.raises(CompanyResearchRunIdentityConflict):
        store.start_run(conflicting)


def test_company_profile_compare_and_set_is_deterministic(context) -> None:
    engine, supplier, contact, opportunity = context
    store = CompanyResearchStore(engine, clock=lambda: NOW)
    original = _prebuild(opportunity, supplier, contact)

    created = store.upsert_profile(original)
    replay = store.upsert_profile(original)
    stale = store.upsert_profile(
        _prebuild(
            opportunity,
            supplier,
            contact,
            observed_at=NOW - dt.timedelta(seconds=1),
            source="e" * 64,
        )
    )

    assert created.created is True
    assert replay.metadata_updated is False
    assert stale.metadata_updated is False
    assert stale.profile.provider_source_fingerprint == "d" * 64


def test_equal_timestamp_different_semantics_conflicts(context) -> None:
    engine, supplier, contact, opportunity = context
    store = CompanyResearchStore(engine, clock=lambda: NOW)
    store.upsert_profile(_prebuild(opportunity, supplier, contact))

    with pytest.raises(CompanyResearchObservationConflict):
        store.upsert_profile(_prebuild(opportunity, supplier, contact, source="f" * 64))


def test_immutable_profile_bindings_cannot_change(context) -> None:
    engine, supplier, contact, opportunity = context
    store = CompanyResearchStore(engine, clock=lambda: NOW)
    original = _prebuild(opportunity, supplier, contact)
    store.upsert_profile(original)

    with pytest.raises(CompanyResearchObservationConflict):
        store.upsert_profile(
            original.model_copy(
                update={
                    "signal_ref": "procurement-opportunity:different",
                    "provider_observed_at": NOW + dt.timedelta(seconds=1),
                }
            )
        )
