from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from test_prospection_actions_send import (
    Delivery,
    Suppressions,
    _seed_second_target,
    approve,
    command,
)
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


def competing_actions(actions: ProspectionActions, engine) -> ProspectionActions:
    return ProspectionActions(
        engine,
        email_verifier=MxVerifier(),
        link_issuer=LinkIssuer(),
        suppression_checker=Suppressions(),
        delivery_provider=Delivery(),
        kill_switch_path=actions._kill_switch_path,
        clock=actions._clock,
    )


def interleave_before_target_lock(actions, competitor_command, engine) -> None:
    original_locked_rows = actions._locked_rows
    interleaved = False

    def lock_rows(connection, statement, *, target_ids):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            competing_actions(actions, engine).enqueue_send(
                competitor_command, actor="rodrigue@kivou.eu"
            )
        return original_locked_rows(connection, statement, target_ids=target_ids)

    actions._locked_rows = lock_rows


def interleave_before_request_insert(actions, competitor_command, engine) -> None:
    interleaved = False

    def insert_request(connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal interleaved
        if not interleaved and statement.startswith("INSERT INTO prospect_send_request"):
            interleaved = True
            competing_actions(actions, engine).enqueue_send(
                competitor_command, actor="rodrigue@kivou.eu"
            )

    sa.event.listen(engine, "before_cursor_execute", insert_request)
    return insert_request


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


def test_identical_interleaved_enqueue_replays_after_target_lock(async_sending):
    actions, provider, engine = async_sending
    interleave_before_target_lock(actions, command(), engine)

    result = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")

    assert result.status == "queued"
    assert row_count(engine, prospect_send_request) == 1
    assert row_count(engine, prospect_send_item) == 1
    assert provider.calls == []


def test_other_payload_interleaved_enqueue_conflicts_after_target_lock(async_sending):
    actions, provider, engine = async_sending
    second_target_id = _seed_second_target(engine)
    other_command = SendCommand(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        targets=(SendTarget(target_id=second_target_id, expected_version=2),),
    )
    interleave_before_target_lock(actions, other_command, engine)

    with pytest.raises(ProspectionActionError) as caught:
        actions.enqueue_send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "SEND_REQUEST_IDEMPOTENCY_CONFLICT"
    assert row_count(engine, prospect_send_request) == 1
    assert row_count(engine, prospect_send_item) == 1
    assert provider.calls == []


def test_other_payload_request_insert_race_becomes_a_conflict(async_sending):
    actions, provider, engine = async_sending
    second_target_id = _seed_second_target(engine)
    other_command = SendCommand(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        targets=(SendTarget(target_id=second_target_id, expected_version=2),),
    )
    listener = interleave_before_request_insert(actions, other_command, engine)

    try:
        with pytest.raises(ProspectionActionError) as caught:
            actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    finally:
        sa.event.remove(engine, "before_cursor_execute", listener)

    assert caught.value.code == "SEND_REQUEST_IDEMPOTENCY_CONFLICT"
    assert row_count(engine, prospect_send_request) == 1
    assert row_count(engine, prospect_send_item) == 1
    assert provider.calls == []
