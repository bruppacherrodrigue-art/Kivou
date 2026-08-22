from __future__ import annotations

import datetime as dt
import threading

import sqlalchemy as sa
from test_campaign_store import _factory_input, _prepared, _reservation

from signals.accounts import service as account_service
from signals.campaigns.store import CampaignStore
from signals.conversion.contracts import AttributionTokenPayload
from signals.conversion.service import ConversionAttributionService
from signals.conversion.token import AttributionTokenKeyring
from signals.persistence.schema import (
    acquisition_conversion_event,
    acquisition_conversion_journey,
)

NOW = dt.datetime(2026, 8, 24, 9, tzinfo=dt.UTC)


def prepared(tmp_path):
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    reservation = CampaignStore(engine).reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )
    keyring = AttributionTokenKeyring(
        current_key_version="attribution-test-v1",
        keys={"attribution-test-v1": b"synthetic-attribution-secret"},
    )
    token = keyring.issue(
        AttributionTokenPayload(
            campaign_ref=reservation.campaign_ref,
            member_ref=reservation.member_ref,
            acquisition_opportunity_id=opportunity_id,
            wedge="construction",
            wedge_version="wedge-v1",
            country="FR",
            sector_ref="sector-public-works-v1",
            need_ref="GROWTH",
            need_version="need-v1",
            issued_at=NOW,
            expires_at=NOW + dt.timedelta(days=34),
        )
    )
    return engine, ConversionAttributionService(engine, keyring), token, opportunity_id


def create_account(connection, *, suffix: str, now: dt.datetime) -> str:
    session = account_service.sign_up(
        connection,
        email=f"conversion-{suffix}@example.invalid",
        password="a-very-long-synthetic-password",
        company_name="Synthetic Account",
        locale="fr",
        now=now,
        session_ttl=dt.timedelta(days=1),
    )
    return session.account_id


def test_valid_click_and_duplicate_converge(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)

    first = service.record_click(token.raw_token, at=NOW + dt.timedelta(hours=1))
    second = service.record_click(token.raw_token, at=NOW + dt.timedelta(hours=2))

    assert first.conversion_event_ref == second.conversion_event_ref
    assert second.replayed is True
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_conversion_event)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["milestone"] == "CLICK"
    assert rows[0]["occurred_at"].replace(tzinfo=dt.UTC) == NOW + dt.timedelta(hours=1)
    assert token.raw_token not in repr(rows[0])


def test_signup_freezes_source_without_matching_signup_email(tmp_path) -> None:
    engine, service, token, opportunity_id = prepared(tmp_path)
    click = service.record_click(token.raw_token, at=NOW + dt.timedelta(hours=1))
    with engine.begin() as connection:
        account_id = create_account(connection, suffix="forwarded", now=NOW + dt.timedelta(days=2))
        first = service.bind_signup_in_transaction(
            connection,
            account_id=account_id,
            raw_token=token.raw_token,
            at=NOW + dt.timedelta(days=2),
        )
        second = service.bind_signup_in_transaction(
            connection,
            account_id=account_id,
            raw_token=token.raw_token,
            at=NOW + dt.timedelta(days=2),
        )

    assert first.journey_ref == second.journey_ref
    assert first.source_click_event_ref == click.conversion_event_ref
    with engine.connect() as connection:
        journey = connection.execute(sa.select(acquisition_conversion_journey)).mappings().one()
        events = connection.execute(
            sa.select(acquisition_conversion_event).order_by(
                acquisition_conversion_event.c.occurred_at
            )
        ).mappings().all()
    assert journey["account_id"] == account_id
    assert journey["acquisition_opportunity_id"] == opportunity_id
    assert [row["milestone"] for row in events] == ["CLICK", "SIGNUP"]
    assert "conversion-forwarded@example.invalid" not in repr(journey)


def test_signup_after_30_days_is_unattributed(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    service.record_click(token.raw_token, at=NOW + dt.timedelta(hours=1))
    with engine.begin() as connection:
        account_id = create_account(connection, suffix="late", now=NOW + dt.timedelta(days=32))
        assert (
            service.bind_signup_in_transaction(
                connection,
                account_id=account_id,
                raw_token=token.raw_token,
                at=NOW + dt.timedelta(days=32),
            )
            is None
        )
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_conversion_journey)
        ) == 0


def test_later_click_cannot_rewrite_existing_account_attribution(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    service.record_click(token.raw_token, at=NOW + dt.timedelta(hours=1))
    with engine.begin() as connection:
        account_id = create_account(connection, suffix="immutable", now=NOW + dt.timedelta(days=1))
        frozen = service.bind_signup_in_transaction(
            connection,
            account_id=account_id,
            raw_token=token.raw_token,
            at=NOW + dt.timedelta(days=1),
        )
    later_token = service.keyring.issue(
        token.payload.model_copy(
            update={"member_ref": "f" * 64, "campaign_ref": "e" * 64}
        )
    )
    with engine.begin() as connection:
        replay = service.bind_signup_in_transaction(
            connection,
            account_id=account_id,
            raw_token=later_token.raw_token,
            at=NOW + dt.timedelta(days=2),
        )
    assert replay == frozen


def test_concurrent_duplicate_click_has_one_durable_identity(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def click() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(
                service.record_click(token.raw_token, at=NOW + dt.timedelta(hours=1))
            )
        except (
            RuntimeError,
            ValueError,
            sa.exc.SQLAlchemyError,
            threading.BrokenBarrierError,
        ) as error:  # pragma: no cover - asserted below
            errors.append(error)

    threads = [threading.Thread(target=click) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(results) == 2
    assert len({result.conversion_event_ref for result in results}) == 1
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_conversion_event)
        ) == 1
