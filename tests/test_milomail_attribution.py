"""Minimal signed Milo Mail conversion events bind to opaque Kivou tokens."""

import datetime as dt
import hashlib
import hmac
import json

import pytest
import sqlalchemy as sa
from test_milomail_policy import NOW, ready_input

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.attribution import (
    MilomailConversionIngress,
    ProgramAttributionKeyring,
    ProgramAttributionService,
)
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.persistence.database import migrate_to_latest
from signals.persistence.schema import (
    acquisition_contact,
    acquisition_program_conversion_receipt,
    acquisition_supplier,
)


class ForbiddenProvider:
    def __getattr__(self, name):
        raise AssertionError(f"Instantly provider called: {name}")


def synthetic_contact(engine, email: str, suffix: str, at: dt.datetime) -> tuple[str, str]:
    supplier_ref = hashlib.sha256(f"supplier:{suffix}".encode()).hexdigest()
    contact_ref = hashlib.sha256(f"contact:{suffix}".encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_supplier).values(
            supplier_ref=supplier_ref, provider="apollo", provider_organization_id=suffix,
            display_name="Cabinet Exemple", normalized_name="cabinet exemple",
            primary_domain="cabinet.example", country_code="FR",
            identity_status="PROVIDER_IDENTIFIED", provider_observed_at=at,
            source_fingerprint="a" * 64, created_at=at, updated_at=at,
        ))
        connection.execute(sa.insert(acquisition_contact).values(
            contact_ref=contact_ref, supplier_ref=supplier_ref, provider="apollo",
            provider_person_id=suffix, provider_organization_id=suffix,
            title="Founder", normalized_title="founder", role_profile_version="synthetic-v1",
            role_tier=4, business_email=email, provider_email_status="verified",
            verification_state="PROVIDER_VERIFIED", verification_provider="apollo",
            provider_observed_at=at, email_observed_at=at, source_fingerprint="b" * 64,
            created_at=at, updated_at=at,
        ))
    return supplier_ref, contact_ref


def prepared():
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    supplier_ref, contact_ref = synthetic_contact(engine, "founder@cabinet.example", "conversion-test", NOW)
    created = acquisition.create_opportunity(
        identity_key="acquisition-program:milomail:conversion-test",
        signal_ref="acquisition-program:milomail:conversion-test",
        idempotency_key="milomail:conversion-test",
        supplier_ref=supplier_ref,
        contact_ref=contact_ref,
        occurred_at=NOW,
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    policy_input = ready_input()
    program_id = AcquisitionProgramStore(engine).register(policy_input.program, at=NOW)
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1",
        keys={"v1": b"suppression-test-secret"},
    )
    runtime = MilomailShadowRuntime(engine, acquisition, suppression_keys, ForbiddenProvider())
    assert (
        runtime.evaluate(
            program_id=program_id,
            opportunity_id=opportunity_id,
            email="founder@cabinet.example",
            policy_input=policy_input,
        ).decision
        == "SEND"
    )
    return engine, acquisition, program_id, opportunity_id


def test_token_issuance_requires_selected_contact_and_current_suppression() -> None:
    engine, _, program_id, opportunity_id = prepared()
    keys = ProgramAttributionKeyring(
        current_key_version="v1", keys={"v1": b"token-test-secret-0123456789"}
    )
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1", keys={"v1": b"suppression-test-secret"}
    )
    service = ProgramAttributionService(
        engine, keys, suppression_keys, clock=lambda: NOW + dt.timedelta(minutes=2)
    )
    kwargs = {
        "program_id": program_id,
        "opportunity_id": opportunity_id,
        "campaign_ref": "milomail:wrong-recipient",
        "issued_at": NOW,
        "expires_at": NOW + dt.timedelta(days=30),
    }
    with pytest.raises(ValueError, match="selected contact"):
        service.issue(**kwargs, recipient_email="stranger@cabinet.example")
    suppression = SuppressionStore(engine, suppression_keys, scope=MILOMAIL_SUPPRESSION_SCOPE)
    with engine.begin() as connection:
        suppression.record_for_email_in_transaction(
            connection, "founder@cabinet.example", source=SuppressionSource.UNSUBSCRIBE,
            reason_code=SuppressionReasonCode.UNSUBSCRIBED,
            evidence_ref=suppression_evidence_ref("UNSUBSCRIBE", "late-opt-out"),
            received_at=NOW + dt.timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="suppressed"):
        service.issue(**kwargs, recipient_email="founder@cabinet.example")


def test_contact_email_change_needs_a_new_send_assessment() -> None:
    engine, _, program_id, opportunity_id = prepared()
    keys = ProgramAttributionKeyring(
        current_key_version="v1", keys={"v1": b"token-test-secret-0123456789"}
    )
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1", keys={"v1": b"suppression-test-secret"}
    )
    with engine.begin() as connection:
        connection.execute(sa.update(acquisition_contact).values(business_email="new@cabinet.example"))
    service = ProgramAttributionService(engine, keys, suppression_keys, clock=lambda: NOW)
    with pytest.raises(ValueError, match="assessed recipient"):
        service.issue(
            program_id=program_id, opportunity_id=opportunity_id,
            campaign_ref="milomail:changed-contact", recipient_email="new@cabinet.example",
            issued_at=NOW, expires_at=NOW + dt.timedelta(days=30),
        )


def signed(body: dict[str, object], secret: bytes, at: dt.datetime):
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    stamp = str(int(at.timestamp()))
    signature = hmac.new(
        secret,
        b"milomail-conversion-v1\0" + stamp.encode() + b"\0" + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, {"X-MiloMail-Timestamp": stamp, "X-MiloMail-Signature": signature}


def test_opaque_token_signed_conversion_and_replay_are_idempotent() -> None:
    engine, acquisition, program_id, opportunity_id = prepared()
    keyring = ProgramAttributionKeyring(
        current_key_version="v1",
        keys={"v1": b"token-test-secret-0123456789"},
    )
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1", keys={"v1": b"suppression-test-secret"}
    )
    service = ProgramAttributionService(engine, keyring, suppression_keys)
    issued = service.issue(
        program_id=program_id,
        opportunity_id=opportunity_id,
        campaign_ref="milomail:synthetic-campaign",
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=30),
        recipient_email="founder@cabinet.example",
    )
    assert issued == service.issue(
        program_id=program_id,
        opportunity_id=opportunity_id,
        campaign_ref="milomail:synthetic-campaign",
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=30),
        recipient_email="founder@cabinet.example",
    )
    assert len(issued) == 43 and "@" not in issued
    secret = b"webhook-test-secret-0123456789"
    ingress = MilomailConversionIngress(
        engine,
        acquisition,
        program_id=program_id,
        webhook_secret=secret,
    )
    body = {
        "event_id": "evt-opaque-1",
        "event_type": "audit_started",
        "attribution_token": issued,
        "occurred_at": (NOW + dt.timedelta(minutes=1)).isoformat(),
    }
    raw, headers = signed(body, secret, NOW + dt.timedelta(minutes=2))
    first = ingress.ingest(raw, headers=headers, received_at=NOW + dt.timedelta(minutes=2))
    second = ingress.ingest(raw, headers=headers, received_at=NOW + dt.timedelta(minutes=2))
    assert first == second
    assert acquisition.get_opportunity(opportunity_id).policy_version == "milomail-fr-b2b-v1"
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_program_conversion_receipt)
            )
            == 1
        )


def test_conversion_rejects_private_payload_bad_signature_and_replay_window() -> None:
    engine, acquisition, program_id, opportunity_id = prepared()
    keyring = ProgramAttributionKeyring(
        current_key_version="v1",
        keys={"v1": b"token-test-secret-0123456789"},
    )
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1", keys={"v1": b"suppression-test-secret"}
    )
    token = ProgramAttributionService(engine, keyring, suppression_keys).issue(
        program_id=program_id,
        opportunity_id=opportunity_id,
        campaign_ref="milomail:synthetic-campaign",
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=30),
        recipient_email="founder@cabinet.example",
    )
    secret = b"webhook-test-secret-0123456789"
    ingress = MilomailConversionIngress(
        engine, acquisition, program_id=program_id, webhook_secret=secret
    )
    body = {
        "event_id": "evt-opaque-2",
        "event_type": "audit_completed",
        "attribution_token": token,
        "occurred_at": NOW.isoformat(),
    }
    raw, headers = signed(body, secret, NOW)
    with pytest.raises(ValueError, match="signature"):
        ingress.ingest(raw, headers={**headers, "X-MiloMail-Signature": "0" * 64}, received_at=NOW)
    with pytest.raises(ValueError, match="timestamp"):
        ingress.ingest(raw, headers=headers, received_at=NOW + dt.timedelta(minutes=10))
    private, private_headers = signed({**body, "gmail_content": "forbidden"}, secret, NOW)
    with pytest.raises(ValueError):
        ingress.ingest(private, headers=private_headers, received_at=NOW)
