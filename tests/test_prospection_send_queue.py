from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from test_prospection_actions_send import Delivery, Suppressions, approve, command
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier, seed

from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.contracts import SendCommand, SendTarget
from signals.prospection_actions.service import ProspectionActionError, ProspectionActions


@pytest.fixture
def async_sending(migrated_sqlite_engine, tmp_path):
    seed(migrated_sqlite_engine)
    provider = Delivery()
    actions = ProspectionActions(
        migrated_sqlite_engine,
        email_verifier=MxVerifier(),
        link_issuer=LinkIssuer(),
        suppression_checker=Suppressions(),
        delivery_provider=provider,
        kill_switch_path=tmp_path / "acquisition.disabled",
        clock=lambda: NOW + dt.timedelta(hours=1),
    )
    approve(actions)
    return actions, provider, migrated_sqlite_engine


def row_count(engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(sa.select(sa.func.count()).select_from(table)) or 0)


def other_payload_same_request_id() -> SendCommand:
    return SendCommand(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        targets=(SendTarget(target_id=TARGET_ID, expected_version=3),),
    )


def mark_target_sent(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == TARGET_ID)
            .values(status="sent")
        )


def test_enqueue_reserves_without_calling_provider(async_sending):
    actions, provider, _engine = async_sending

    result = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")

    assert result.status == "queued"
    assert result.total_count == 1
    assert result.sent_count == result.processed_count == result.failed_count == 0
    assert actions.send_progress(result.request_id) == result
    assert provider.calls == []


def test_same_request_and_payload_replays_without_new_rows(async_sending):
    actions, provider, engine = async_sending

    first = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    replay = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")

    assert replay == first
    assert provider.calls == []
    assert row_count(engine, prospect_send_request) == 1
    assert row_count(engine, prospect_send_item) == 1


def test_same_request_with_other_payload_is_a_conflict(async_sending):
    actions, provider, _engine = async_sending
    actions.enqueue_send(command(), actor="rodrigue@kivou.eu")

    with pytest.raises(ProspectionActionError) as caught:
        actions.enqueue_send(other_payload_same_request_id(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "SEND_REQUEST_IDEMPOTENCY_CONFLICT"
    assert provider.calls == []


def test_enqueue_never_reserves_a_sent_target(async_sending):
    actions, provider, engine = async_sending
    mark_target_sent(engine)

    with pytest.raises(ProspectionActionError) as caught:
        actions.enqueue_send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "INVALID_TARGET_STATUS"
    assert provider.calls == []
