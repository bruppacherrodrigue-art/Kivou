from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from alembic import command

from signals.compliance.contracts import (
    SuppressionMatchState,
    SuppressionReasonCode,
    SuppressionSource,
)
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.contact_discovery.contracts import ContactObservation
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import acquisition_contact, acquisition_contact_suppression
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate
from signals.supplier_discovery.store import SupplierDiscoveryStore

NOW = dt.datetime(2026, 8, 21, 11, tzinfo=dt.UTC)


@pytest.fixture
def contacts(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'suppression.db'}")
    command.upgrade(alembic_config(engine), "head")
    supplier = (
        SupplierDiscoveryStore(engine, clock=lambda: NOW)
        .upsert_supplier(
            ApolloOrganizationCandidate(
                provider_organization_id="apollo-org-1",
                display_name="Acme SA",
                normalized_name="acme sa",
                country_code="FR",
                provider_observed_at=NOW,
                source_fingerprint="a" * 64,
            )
        )
        .supplier
    )
    observation = ContactObservation(
        supplier_ref=supplier.supplier_ref,
        provider_person_id="apollo-person-1",
        provider_organization_id="apollo-org-1",
        first_name="Synthetic",
        normalized_title="sales director",
        role_tier=1,
        business_email="person@example.test",
        provider_observed_at=NOW,
        email_observed_at=NOW,
        source_fingerprint="b" * 64,
    )
    first = ContactDiscoveryStore(engine, clock=lambda: NOW).upsert_contact(observation).contact
    return engine, supplier, first, observation


def keyring() -> SuppressionIdentityKeyring:
    return SuppressionIdentityKeyring(
        current_key_version="key-v2",
        keys={"key-v1": b"retained-test-key", "key-v2": b"current-test-key"},
    )


def test_record_for_contact_is_append_only_idempotent_and_stores_no_email(contacts) -> None:
    engine, supplier, contact, _ = contacts
    store = SuppressionStore(engine, keyring())

    first = store.record_for_contact(
        contact.contact_ref,
        source=SuppressionSource.RECIPIENT_OBJECTION,
        reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
        evidence_ref=suppression_evidence_ref("recipient-objection", "synthetic-1"),
        received_at=NOW,
    )
    replay = store.record_for_contact(
        contact.contact_ref,
        source=SuppressionSource.RECIPIENT_OBJECTION,
        reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
        evidence_ref=suppression_evidence_ref("recipient-objection", "synthetic-1"),
        received_at=NOW,
    )

    assert replay["suppression_id"] == first["suppression_id"]
    assert first["supplier_ref"] == supplier.supplier_ref
    assert first["minimum_retention_until"].replace(tzinfo=dt.UTC) == NOW.replace(year=2029)
    assert "person@example.test" not in repr(dict(first))
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
            )
            == 1
        )


def test_duplicate_contact_rows_with_same_email_converge_to_match(contacts) -> None:
    engine, _, first, observation = contacts
    store = SuppressionStore(engine, keyring())
    store.record_for_contact(
        first.contact_ref,
        source=SuppressionSource.UNSUBSCRIBE,
        reason_code=SuppressionReasonCode.UNSUBSCRIBED,
        evidence_ref=suppression_evidence_ref("unsubscribe", "synthetic-1"),
        received_at=NOW,
    )
    second_observation = observation.model_copy(
        update={"provider_person_id": "apollo-person-2", "source_fingerprint": "c" * 64}
    )
    second = (
        ContactDiscoveryStore(engine, clock=lambda: NOW).upsert_contact(second_observation).contact
    )

    match = store.match_contact(second.contact_ref)

    assert match.state is SuppressionMatchState.MATCHED
    assert match.suppression_refs


def test_unavailable_historical_matching_key_fails_closed(contacts) -> None:
    engine, _, contact, _ = contacts
    complete = SuppressionStore(engine, keyring())
    complete.record_for_contact(
        contact.contact_ref,
        source=SuppressionSource.SYSTEM_IMPORT,
        reason_code=SuppressionReasonCode.IMPORTED_SUPPRESSION,
        evidence_ref=suppression_evidence_ref("system-import", "synthetic-1"),
        received_at=NOW,
        key_version="key-v1",
    )
    incomplete = SuppressionStore(
        engine,
        SuppressionIdentityKeyring(
            current_key_version="key-v2", keys={"key-v2": b"current-test-key"}
        ),
    )

    result = incomplete.match_contact(contact.contact_ref)

    assert result.state is SuppressionMatchState.COVERAGE_UNSAFE
    assert result.key_versions_considered == ("key-v2",)
    with engine.connect() as connection:
        assert "business_email" not in {
            column["name"]
            for column in sa.inspect(engine).get_columns(acquisition_contact_suppression.name)
        }
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_contact)) == 1


def test_retained_old_key_matches_after_rotation_without_auto_reactivation(contacts) -> None:
    engine, _, contact, _ = contacts
    rotated = keyring()
    store = SuppressionStore(engine, rotated)
    store.record_for_contact(
        contact.contact_ref,
        source=SuppressionSource.UNSUBSCRIBE,
        reason_code=SuppressionReasonCode.UNSUBSCRIBED,
        evidence_ref=suppression_evidence_ref("unsubscribe", "old-key"),
        received_at=NOW,
        key_version="key-v1",
    )
    store.record_for_contact(
        contact.contact_ref,
        source=SuppressionSource.SYSTEM_IMPORT,
        reason_code=SuppressionReasonCode.IDENTITY_REKEY_PROOF,
        evidence_ref=suppression_evidence_ref("system-import", "new-key"),
        received_at=NOW + dt.timedelta(seconds=1),
        key_version="key-v2",
    )

    result = store.match_contact(contact.contact_ref, at=NOW.replace(year=2036))

    assert result.state is SuppressionMatchState.MATCHED
    assert result.key_versions_considered == ("key-v1", "key-v2")
    assert len(result.suppression_refs) == 2


@pytest.mark.parametrize(
    ("reason_code", "evidence_ref"),
    (
        (
            "ALICE_SMITH",
            suppression_evidence_ref("recipient-objection", "synthetic"),
        ),
        (SuppressionReasonCode.RECIPIENT_OBJECTED, "recipient:Alice-Smith"),
        (SuppressionReasonCode.RECIPIENT_OBJECTED, "https://example.com/raw-recipient"),
        (
            "RECIPIENT\nOBJECTED",
            suppression_evidence_ref("recipient-objection", "synthetic"),
        ),
    ),
)
def test_suppression_audit_values_reject_pii_and_injection(
    contacts, reason_code: object, evidence_ref: str
) -> None:
    engine, _, contact, _ = contacts

    with pytest.raises((TypeError, ValueError), match="suppression"):
        SuppressionStore(engine, keyring()).record_for_contact(
            contact.contact_ref,
            source=SuppressionSource.RECIPIENT_OBJECTION,
            reason_code=reason_code,
            evidence_ref=evidence_ref,
            received_at=NOW,
        )
