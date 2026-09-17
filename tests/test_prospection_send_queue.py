from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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


def concurrent_enqueue(actions, first_command, second_command, engine):
    barrier = Barrier(2)
    competitor = competing_actions(actions, engine)

    def enqueue(candidate, action):
        barrier.wait()
        try:
            return action.enqueue_send(candidate, actor="rodrigue@kivou.eu")
        except ProspectionActionError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(enqueue, first_command, actions)
        second = executor.submit(enqueue, second_command, competitor)
    return first.result(), second.result()


def reserve_daily_capacity(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(prospect_send_request).values(
                request_id="23c6d156-4ae7-4518-8254-3b6ee32c84ba",
                payload_fingerprint="f" * 64,
                target_ids=[],
                request_day=NOW.date(),
                reserved_count=24,
                sent_count=24,
                processed_count=24,
                failed_count=0,
                status="completed",
                created_by="rodrigue@kivou.eu",
                created_at=NOW,
                updated_at=NOW,
                completed_at=NOW,
            )
        )


def daily_reserved_count(engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.scalar(
                sa.select(
                    sa.func.coalesce(
                        sa.func.sum(
                            sa.case(
                                (
                                    prospect_send_request.c.status.in_(
                                        ("started", "queued", "running", "waiting")
                                    ),
                                    prospect_send_request.c.reserved_count,
                                ),
                                else_=prospect_send_request.c.sent_count,
                            )
                        ),
                        0,
                    )
                ).where(prospect_send_request.c.request_day == NOW.date())
            )
            or 0
        )


def interleave_before_target_reservation(engine):
    interleaved = False

    def reserve_target(connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal interleaved
        if not interleaved and statement.startswith("INSERT INTO prospect_send_request"):
            interleaved = True
            connection.execute(
                sa.update(prospect_target)
                .where(prospect_target.c.target_id == TARGET_ID)
                .values(send_request_id="rival-request")
            )

    sa.event.listen(engine, "before_cursor_execute", reserve_target)
    return reserve_target


def interleave_progress_update(engine, request_id: str):
    updated = False

    def update_progress(connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal updated
        if not updated and "prospect_send_item" in statement:
            updated = True
            with engine.begin() as writer:
                writer.execute(
                    sa.update(prospect_send_request)
                    .where(prospect_send_request.c.request_id == request_id)
                    .values(status="completed", processed_count=1, sent_count=1)
                )
                writer.execute(
                    sa.update(prospect_send_item)
                    .where(prospect_send_item.c.request_id == request_id)
                    .values(status="sent")
                )

    sa.event.listen(engine, "before_cursor_execute", update_progress)
    return update_progress


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


def test_identical_concurrent_enqueue_replays(async_sending):
    actions, provider, engine = async_sending
    first, second = concurrent_enqueue(actions, command(), command(), engine)

    assert first == second
    assert first.status == "queued"
    assert row_count(engine, prospect_send_request) == 1
    assert row_count(engine, prospect_send_item) == 1
    assert provider.calls == []


def test_other_payload_concurrent_enqueue_conflicts(async_sending):
    actions, provider, engine = async_sending
    second_target_id = _seed_second_target(engine)
    other_command = SendCommand(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        targets=(SendTarget(target_id=second_target_id, expected_version=2),),
    )
    first, second = concurrent_enqueue(actions, command(), other_command, engine)

    errors = [result for result in (first, second) if isinstance(result, ProspectionActionError)]
    assert len(errors) == 1
    assert errors[0].code == "SEND_REQUEST_IDEMPOTENCY_CONFLICT"
    assert row_count(engine, prospect_send_request) == 1
    assert row_count(engine, prospect_send_item) == 1
    assert provider.calls == []


def test_concurrent_distinct_requests_cannot_exceed_daily_quota(async_sending):
    actions, provider, engine = async_sending
    second_target_id = _seed_second_target(engine)
    reserve_daily_capacity(engine)
    other_command = SendCommand(
        request_id="d5db08cf-195a-4ff1-b03e-37ac752d0d55",
        targets=(SendTarget(target_id=second_target_id, expected_version=2),),
    )
    first, second = concurrent_enqueue(actions, command(), other_command, engine)

    errors = [result for result in (first, second) if isinstance(result, ProspectionActionError)]
    assert len(errors) == 1
    assert errors[0].code == "DAILY_SEND_CAP_EXCEEDED"
    assert row_count(engine, prospect_send_request) == 2
    assert row_count(engine, prospect_send_item) == 1
    assert daily_reserved_count(engine) <= 25
    assert provider.calls == []


def test_target_reservation_conditional_update_rolls_back_the_loser(async_sending):
    actions, provider, engine = async_sending
    listener = interleave_before_target_reservation(engine)

    try:
        with pytest.raises(ProspectionActionError) as caught:
            actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    finally:
        sa.event.remove(engine, "before_cursor_execute", listener)

    assert caught.value.code == "INVALID_TARGET_STATUS"
    assert row_count(engine, prospect_send_request) == 0
    assert row_count(engine, prospect_send_item) == 0
    with engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().one()
    assert target["send_request_id"] is None
    assert provider.calls == []


def test_progress_reads_request_and_items_from_one_snapshot(async_sending):
    actions, _provider, engine = async_sending
    queued = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    listener = interleave_progress_update(engine, str(queued.request_id))

    try:
        progress = actions.send_progress(queued.request_id)
    finally:
        sa.event.remove(engine, "before_cursor_execute", listener)

    assert progress.status == "completed"
    assert progress.processed_count == progress.sent_count == 1
    assert progress.items[0].status == "sent"
