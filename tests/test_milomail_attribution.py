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
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.database import migrate_to_latest
from signals.persistence.schema import acquisition_program_conversion_receipt


class ForbiddenProvider:
    def __getattr__(self, name):
        raise AssertionError(f"Instantly provider called: {name}")


def prepared():
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    created = acquisition.create_opportunity(
        identity_key="acquisition-program:milomail:conversion-test",
        signal_ref="acquisition-program:milomail:conversion-test",
        idempotency_key="milomail:conversion-test",
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
