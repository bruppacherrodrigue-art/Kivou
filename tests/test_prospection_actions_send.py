from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier, seed

from signals.persistence.schema import prospect_send_request, prospect_target
from signals.prospection_actions.contracts import ApproveCommand, SendCommand, SendTarget
from signals.prospection_actions.service import (
    DeliveryAttempt,
    ProspectionActionError,
    ProspectionActions,
)


class Suppressions:
    def __init__(self, suppressed: set[str] | None = None) -> None:
        self.suppressed = suppressed or set()

    def is_suppressed(self, connection, *, email: str, at: dt.datetime) -> bool:
        return email in self.suppressed


class Delivery:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def deliver(self, *, permit, targets, at: dt.datetime):
        self.calls.append(tuple(targets))
        assert permit.target_ids == frozenset(item.target_id for item in targets)
        return tuple(
            DeliveryAttempt(
                target_id=item.target_id,
                status="sent",
                instantly_id=f"lead-{item.target_id}",
                provider_campaign_id="campaign-2026-09-11",
                instantly_credit_units=1,
                instantly_request_count=2,
            )
            for item in targets
        )


@pytest.fixture
def sending(migrated_sqlite_engine, tmp_path):
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
    return actions, provider, migrated_sqlite_engine, tmp_path


def approve(actions: ProspectionActions) -> None:
    actions.approve(
        ApproveCommand(target_id=TARGET_ID, expected_version=1),
        actor="rodrigue@kivou.eu",
    )


def command(version: int = 2) -> SendCommand:
    return SendCommand(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        targets=(SendTarget(target_id=TARGET_ID, expected_version=version),),
    )


def test_send_refuses_unapproved_without_calling_provider(sending) -> None:
    actions, provider, _engine, _tmp = sending

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(version=1), actor="rodrigue@kivou.eu")

    assert caught.value.code == "INVALID_TARGET_STATUS"
    assert provider.calls == []


def test_send_refuses_non_mx_verified_even_when_approved(sending) -> None:
    actions, provider, engine, _tmp = sending
    approve(actions)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == TARGET_ID)
            .values(email_verification_status="mx_failed")
        )

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "EMAIL_NOT_MX_VERIFIED"
    assert provider.calls == []


def test_send_refuses_kill_switch_before_provider(sending) -> None:
    actions, provider, _engine, tmp_path = sending
    approve(actions)
    (tmp_path / "acquisition.disabled").touch()

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "KILL_SWITCH_ACTIVE"
    assert provider.calls == []


def test_send_is_idempotent_and_persists_delivery_cost(sending) -> None:
    actions, provider, engine, _tmp = sending
    approve(actions)

    first = actions.send(command(), actor="rodrigue@kivou.eu")
    replay = actions.send(command(), actor="rodrigue@kivou.eu")

    assert first == replay
    assert first.results[0].status == "sent"
    assert first.daily_sent_count == 1
    assert first.daily_remaining == 24
    assert len(provider.calls) == 1
    with engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().one()
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
    assert target["instantly_credit_units"] == 1
    assert target["instantly_request_count"] == 2
    assert request["sent_count"] == 1


def test_send_hard_cap_counts_completed_and_reserved_batches(sending) -> None:
    actions, provider, engine, _tmp = sending
    approve(actions)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(prospect_send_request).values(
                request_id="65bc7eec-f756-4929-ab8a-2b17d168a40e",
                payload_fingerprint="f" * 64,
                target_ids=["old"],
                request_day=NOW.date(),
                reserved_count=25,
                sent_count=25,
                status="completed",
                result={},
                created_by="rodrigue@kivou.eu",
                created_at=NOW,
                completed_at=NOW,
            )
        )

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "DAILY_SEND_CAP_EXCEEDED"
    assert provider.calls == []
