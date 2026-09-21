"""Authenticated Instantly simulation never reaches Kivou campaign bindings."""

import datetime as dt

import pytest
import sqlalchemy as sa
from test_milomail_attribution import prepared
from test_milomail_policy import NOW

from signals.acquisition_programs.attribution import (
    ProgramAttributionKeyring,
    ProgramAttributionService,
)
from signals.acquisition_programs.provider_events import MilomailInstantlyEventSimulation
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
)
from signals.persistence.schema import acquisition_contact_suppression


def event(kind: str, event_id: str) -> dict[str, object]:
    return {
        "event_type": kind,
        "timestamp": NOW.isoformat(),
        "workspace": "instantly:milomail:test",
        "campaign_id": "milomail:synthetic-campaign",
        "campaign_name": "milomail:synthetic-campaign",
        "lead_email": "founder@cabinet.example",
        "email_id": event_id,
        "reply_text": "Private reply text must never persist",
    }


def test_simulated_reply_bounce_and_optout_are_program_scoped_and_idempotent() -> None:
    engine, acquisition, program_id, opportunity_id = prepared()
    keys = ProgramAttributionKeyring(
        current_key_version="v1",
        keys={"v1": b"token-test-secret-0123456789"},
    )
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1", keys={"v1": b"suppression-test-secret"}
    )
    ProgramAttributionService(engine, keys, suppression_keys).issue(
        program_id=program_id,
        opportunity_id=opportunity_id,
        campaign_ref="milomail:synthetic-campaign",
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=30),
        recipient_email="founder@cabinet.example",
    )
    service = MilomailInstantlyEventSimulation(
        engine,
        acquisition,
        program_id=program_id,
        workspace_ref="instantly:milomail:test",
        webhook_secret="synthetic-milomail-secret",
        suppression_keyring=suppression_keys,
    )
    reply = service.ingest(
        event("reply_received", "provider-reply-1"),
        supplied_secret="synthetic-milomail-secret",
        received_at=NOW,
    )
    assert (
        service.ingest(
            event("reply_received", "provider-reply-1"),
            supplied_secret="synthetic-milomail-secret",
            received_at=NOW,
        )
        == reply
    )
    assert service.ingest(
        event("email_bounced", "provider-bounce-1"),
        supplied_secret="synthetic-milomail-secret",
        received_at=NOW,
    )
    assert service.ingest(
        event("lead_unsubscribed", "provider-optout-1"),
        supplied_secret="synthetic-milomail-secret",
        received_at=NOW,
    )
    assert acquisition.get_opportunity(opportunity_id).policy_version == "milomail-fr-b2b-v1"
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_contact_suppression)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["scope"] == MILOMAIL_SUPPRESSION_SCOPE
    assert not service.follow_up_allowed("founder@cabinet.example", at=NOW)
    assert "Private reply text" not in repr(acquisition.list_events(opportunity_id))
    with pytest.raises(ValueError, match="lead identity mismatch"):
        service.ingest(
            {
                **event("reply_received", "provider-wrong-lead"),
                "lead_email": "stranger@cabinet.example",
            },
            supplied_secret="synthetic-milomail-secret",
            received_at=NOW,
        )


def test_simulated_provider_event_rejects_wrong_secret_or_workspace() -> None:
    engine, acquisition, program_id, _ = prepared()
    service = MilomailInstantlyEventSimulation(
        engine,
        acquisition,
        program_id=program_id,
        workspace_ref="instantly:milomail:test",
        webhook_secret="synthetic-milomail-secret",
        suppression_keyring=SuppressionIdentityKeyring(
            current_key_version="v1",
            keys={"v1": b"suppression-test-secret"},
        ),
    )
    with pytest.raises(ValueError, match="authentication"):
        service.ingest(event("reply_received", "id"), supplied_secret="wrong", received_at=NOW)
    with pytest.raises(ValueError, match="workspace"):
        service.ingest(
            {**event("reply_received", "id"), "workspace": "kivou-workspace"},
            supplied_secret="synthetic-milomail-secret",
            received_at=NOW,
        )
