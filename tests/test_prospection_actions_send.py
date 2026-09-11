from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier, seed

from signals.persistence.schema import prospect_send_request, prospect_target, supplier_directory
from signals.prospection_actions.contracts import ApproveCommand, SendCommand, SendTarget
from signals.prospection_actions.service import (
    DeliveryAttempt,
    ProspectionActionError,
    ProspectionActions,
)
from signals.supplier_directory.domain_audit import audit_confirmed_domains


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


def _seed_second_target(engine) -> str:
    target_id = "11111111-1111-4111-8111-111111111111"
    with engine.begin() as connection:
        directory = dict(
            connection.execute(sa.select(supplier_directory)).mappings().one()
        )
        directory.update(
            siren="100000001",
            legal_name="Alpha Béton",
            domain="alpha-beton.fr",
            website_url="https://alpha-beton.fr",
            professional_email="contact@alpha-beton.fr",
        )
        connection.execute(sa.insert(supplier_directory).values(**directory))

        target = dict(connection.execute(sa.select(prospect_target)).mappings().one())
        target.update(
            target_id=target_id,
            siren="100000001",
            opportunity_key="boamp-2026-41",
            procedure_award_key="notice-1:lot-2",
            acquisition_opportunity_id="b" * 64,
            company_name="Alpha Béton",
            email_address="contact@alpha-beton.fr",
            attribution_member_ref="e" * 64,
            attribution_payload={"member_ref": "e" * 64},
            attribution_token_fingerprint="f" * 64,
        )
        connection.execute(sa.insert(prospect_target).values(**target))
    return target_id


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


def test_send_refuses_approved_mail_that_failed_the_render_contract(sending) -> None:
    actions, provider, engine, _tmp = sending
    approve(actions)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == TARGET_ID)
            .values(
                mail_contract_status="failed",
                mail_contract_failure="signature_invalid",
            )
        )

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "MAIL_CONTRACT_FAILED"
    assert provider.calls == []


def test_send_refuses_an_approved_target_quarantined_by_domain_audit(sending) -> None:
    actions, provider, engine, _tmp = sending
    approve(actions)
    with engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == "123456789")
            .values(domain="beton-bourbonnais.localbiz.fr")
        )
    audit = audit_confirmed_domains(
        engine,
        observed_at=NOW + dt.timedelta(minutes=30),
        apply=True,
    )
    assert audit.modified_count == 1

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "DIRECTORY_REVERIFICATION_REQUIRED"
    assert caught.value.status_code == 422
    assert caught.value.target_ids == (TARGET_ID,)
    assert provider.calls == []
    with engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().one()
        request_count = connection.scalar(
            sa.select(sa.func.count()).select_from(prospect_send_request)
        )
    assert target["status"] == "approved"
    assert target["send_request_id"] is None
    assert request_count == 0


def test_send_refuses_kill_switch_before_provider(sending) -> None:
    actions, provider, _engine, tmp_path = sending
    approve(actions)
    (tmp_path / "acquisition.disabled").touch()

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "KILL_SWITCH_ACTIVE"
    assert provider.calls == []


def test_send_rechecks_kill_switch_after_reservation(sending) -> None:
    actions, provider, engine, _tmp = sending
    approve(actions)

    class DelayedKillSwitch:
        def __init__(self) -> None:
            self.calls = 0

        def exists(self) -> bool:
            self.calls += 1
            return self.calls >= 2

    actions._kill_switch_path = DelayedKillSwitch()

    with pytest.raises(ProspectionActionError) as caught:
        actions.send(command(), actor="rodrigue@kivou.eu")

    assert caught.value.code == "KILL_SWITCH_ACTIVE"
    assert provider.calls == []
    with engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().one()
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
    assert target["send_request_id"] is None
    assert request["status"] == "failed"


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


def test_send_locks_batch_targets_then_directories_in_sorted_order_and_keeps_payload_order(
    sending,
) -> None:
    actions, provider, engine, _tmp = sending
    second_target_id = _seed_second_target(engine)
    approve(actions)
    actions.approve(
        ApproveCommand(target_id=second_target_id, expected_version=1),
        actor="rodrigue@kivou.eu",
    )
    batch = SendCommand(
        request_id="984be03d-fbe4-46b1-9900-b99b4068fcbd",
        targets=(
            SendTarget(target_id=TARGET_ID, expected_version=2),
            SendTarget(target_id=second_target_id, expected_version=2),
        ),
    )
    statements: list[sa.sql.ClauseElement] = []

    def capture_statement(
        _connection,
        clauseelement,
        _multiparams,
        _params,
        _execution_options,
    ) -> None:
        statements.append(clauseelement)

    sa.event.listen(engine, "before_execute", capture_statement)
    try:
        result = actions.send(batch, actor="rodrigue@kivou.eu")
    finally:
        sa.event.remove(engine, "before_execute", capture_statement)

    lock_sql = [
        " ".join(
            str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ).split()
        )
        for statement in statements
        if isinstance(statement, sa.sql.Select)
        and statement._for_update_arg is not None
    ]
    assert len(lock_sql) == 2
    assert "FROM prospect_target" in lock_sql[0]
    assert "ORDER BY prospect_target.target_id FOR UPDATE NOWAIT" in lock_sql[0]
    assert "FROM supplier_directory" in lock_sql[1]
    assert "ORDER BY supplier_directory.siren FOR UPDATE NOWAIT" in lock_sql[1]
    assert [str(item.target_id) for item in provider.calls[0]] == [
        TARGET_ID,
        second_target_id,
    ]
    assert [item.target_id for item in result.results] == [TARGET_ID, second_target_id]


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
