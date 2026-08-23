from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from test_campaign_webhooks import RECEIVED, _event, _queued, _service

from signals.operations.observer import RepositoryReliabilityObserver
from signals.operations.store import OperationsStore
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_provider_event,
)
from signals.policy.contracts import AutonomyMode
from signals.policy.store import PolicyStore


def test_authoritative_post_stop_send_is_preserved_observed_and_downgrades_control(
    tmp_path,
) -> None:
    engine, _, result = _queued(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_campaign_member).values(
                execution_state="STOPPED", sequence_state="STOPPED"
            )
        )
    ingress = _service(engine)
    transport = ingress.ingest(
        _event(result, email_id="synthetic-post-stop-email"),
        received_at=RECEIVED,
    )
    assert transport.incident_code == "UNEXPECTED_EMAIL_SENT_AFTER_STOP"
    with engine.connect() as connection:
        provider_event = connection.execute(sa.select(acquisition_provider_event)).mappings().one()

    observed = RepositoryReliabilityObserver(engine).scan_campaign(
        result.campaign_ref, observed_at=RECEIVED + dt.timedelta(seconds=1)
    )

    assert len(observed.incident_refs) == 1
    incident = OperationsStore(engine).get_incident(observed.incident_refs[0])
    assert incident["incident_type"] == "UNEXPECTED_TRANSPORT_TRUTH"
    assert incident["severity"] == "CRITICAL"
    assert incident["source_state_ref"] == provider_event["provider_event_ref"]
    assert incident["policy_control_before"] is not None
    assert incident["policy_control_after"] is not None
    control = PolicyStore(engine).get_effective_control(RECEIVED + dt.timedelta(seconds=1))
    assert control.autonomy_mode is AutonomyMode.SHADOW
    assert control.kill_switch is True
    assert control.read_only is True

    # Restart/re-observation converges and never rewrites authoritative transport.
    replay = RepositoryReliabilityObserver(engine).scan_campaign(
        result.campaign_ref, observed_at=RECEIVED + dt.timedelta(minutes=1)
    )
    assert replay.incident_refs == observed.incident_refs
    with engine.connect() as connection:
        same_event = (
            connection.execute(
                sa.select(acquisition_provider_event).where(
                    acquisition_provider_event.c.provider_event_ref
                    == provider_event["provider_event_ref"]
                )
            )
            .mappings()
            .one()
        )
    assert same_event["incident_code"] == "UNEXPECTED_EMAIL_SENT_AFTER_STOP"
