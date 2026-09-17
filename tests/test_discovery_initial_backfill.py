from __future__ import annotations

import datetime as dt
import pathlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import sqlalchemy as sa
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import MATERIALIZED_AT, ORIGIN, PASSWORD, pin_session_cookie

from signals.api import ApiConfig, create_app
from signals.billing import discovery
from signals.billing.schema import discovery_signal_grant
from signals.connectors.ted import extract as extract_ted
from signals.ingestion.backfill import materialize_existing_opportunities_for_target
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence import persist_award_facts
from signals.persistence.schema import (
    contract_award,
    evidence,
    for_you_sentence,
    materialized_signal,
)

ACTIVE_INPUT = {
    "offers": [
        "materials_and_components",
        "equipment_rental",
        "staffing_and_labour",
        "transport_and_logistics",
        "specialist_subcontracting",
        "safety_equipment",
        "waste_and_environmental_services",
    ],
    "buyer_trades": [],
    "territories": ["FR"],
    "minimum_contract_value": {"currency": "EUR", "minimum_amount": 0},
}


def _candidate(index: int):
    fixture = pathlib.Path(__file__).parent / "fixtures" / "ted" / "550374-2026.xml"
    extraction = extract_ted(fixture.read_bytes(), retrieved_at=MATERIALIZED_AT)
    event = extraction.event.model_copy(
        update={
            "provenance": extraction.event.provenance.model_copy(
                update={
                    "source_notice_id": f"discovery-backfill-notice-{index}",
                    "source_procedure_id": f"discovery-backfill-procedure-{index}",
                }
            )
        }
    )
    award = extraction.awards[0].model_copy(
        update={
            "event_ref": event.ref(),
            "source_award_id": f"discovery-backfill-award-{index}",
        }
    )
    return event, award


def _persist_candidates(engine: sa.Engine, *, count: int, start: int = 0) -> None:
    with engine.begin() as connection:
        for index in range(start, start + count):
            event, award = _candidate(index)
            persist_award_facts(
                connection,
                event=event,
                award=award,
                persisted_at=MATERIALIZED_AT,
            )


def _new_discovery_client(engine: sa.Engine, *, email: str = "discovery@kivou.ch"):
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN),
        now_override=lambda: MATERIALIZED_AT,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Discovery Customer SAS",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(client, response)
    return client


def _account_id(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def _grant_keys(engine: sa.Engine, account_id: str) -> tuple[str, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.execute(
                sa.select(discovery_signal_grant.c.signal_key)
                .where(discovery_signal_grant.c.account_id == account_id)
                .order_by(discovery_signal_grant.c.signal_key)
            ).scalars()
        )


def _activate(client: TestClient, *, label: str = "Fournitures France") -> str:
    response = client.post(
        "/target-icps",
        json={"label": label, "customer_input": ACTIVE_INPUT},
    )
    assert response.status_code == 201, response.text
    return response.json()["target_icp_id"]


def test_first_active_profile_grants_three_existing_signals_before_any_feed_read(
    migrated_sqlite_engine,
):
    _persist_candidates(migrated_sqlite_engine, count=4)
    client = _new_discovery_client(migrated_sqlite_engine)

    _activate(client)

    account_id = _account_id(client)
    grants = _grant_keys(migrated_sqlite_engine, account_id)
    assert len(grants) == 3


def test_initial_backfill_ignores_the_zero_day_plan_window_without_opening_history(
    migrated_sqlite_engine,
):
    with migrated_sqlite_engine.begin() as connection:
        for index in range(3):
            event, award = _candidate(index)
            persist_award_facts(
                connection,
                event=event,
                award=award.model_copy(
                    update={
                        "award_date": MATERIALIZED_AT.date() - dt.timedelta(days=45),
                        "contract_notification_date": None,
                    }
                ),
                persisted_at=MATERIALIZED_AT,
            )
    client = _new_discovery_client(migrated_sqlite_engine, email="history-window@kivou.ch")

    _activate(client)

    assert client.get("/billing/status").json()["entitlements"]["history_days"] == 0
    assert len(_grant_keys(migrated_sqlite_engine, _account_id(client))) == 3
    assert client.get("/signals").json()["items"] == []
    history = client.get("/signals", params={"view": "history", "limit": 50}).json()[
        "items"
    ]
    assert len(history) == 3
    assert all(item["locked"] is False for item in history)
    assert len(client.get("/dashboard").json()["top3"]) == 3


def test_dashboard_reload_feed_detail_evidence_and_fourth_lock_are_coherent(
    migrated_sqlite_engine,
):
    _persist_candidates(migrated_sqlite_engine, count=4)
    client = _new_discovery_client(migrated_sqlite_engine, email="journey@kivou.ch")
    _activate(client)
    grants = set(_grant_keys(migrated_sqlite_engine, _account_id(client)))
    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.signal_key == next(iter(grants)))
            .values(model_fit="none")
        )

    first = client.get("/dashboard")
    second = client.get("/dashboard")
    assert first.status_code == second.status_code == 200
    first_keys = {item["signal_id"] for item in first.json()["top3"]}
    second_keys = {item["signal_id"] for item in second.json()["top3"]}
    assert first_keys == second_keys == grants

    feed = client.get("/signals", params={"view": "history", "limit": 50})
    assert feed.status_code == 200, feed.text
    items = feed.json()["items"]
    assert len(items) == 4
    assert {item["signal_id"] for item in items if not item["locked"]} == grants
    locked = [item for item in items if item["locked"]]
    assert len(locked) == 1

    for signal_key in grants:
        detail = client.get(f"/signals/{signal_key}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["locked"] is False
        assert detail.json()["evidence"]["public_facts"]
    locked_detail = client.get(f"/signals/{locked[0]['signal_id']}").json()
    assert locked_detail["locked"] is True
    assert "evidence" not in locked_detail


def test_replaying_backfill_keeps_the_same_three_without_duplicates(migrated_sqlite_engine):
    _persist_candidates(migrated_sqlite_engine, count=5)
    client = _new_discovery_client(migrated_sqlite_engine, email="retry@kivou.ch")
    _activate(client)
    account_id = _account_id(client)
    before = _grant_keys(migrated_sqlite_engine, account_id)

    with migrated_sqlite_engine.begin() as connection:
        assert discovery.reconcile_initial_backfill(
            connection,
            account_id=account_id,
            as_of=MATERIALIZED_AT.date(),
            now=MATERIALIZED_AT + dt.timedelta(minutes=1),
        ) == ()

    assert _grant_keys(migrated_sqlite_engine, account_id) == before
    assert len(before) == len(set(before)) == 3


def test_two_candidates_are_granted_and_one_lifetime_slot_remains(migrated_sqlite_engine):
    _persist_candidates(migrated_sqlite_engine, count=2)
    client = _new_discovery_client(migrated_sqlite_engine, email="partial@kivou.ch")
    _activate(client)

    assert len(_grant_keys(migrated_sqlite_engine, _account_id(client))) == 2
    status = client.get("/billing/status").json()["discovery"]
    assert status == {"granted_signal_count": 2, "remaining_slots": 1, "limit": 3}
    dashboard = client.get("/dashboard").json()
    assert dashboard["plan"]["assigned"] == 2
    assert dashboard["plan"]["remaining"] == 1
    assert dashboard["plan"]["availability"] == "partial"
    assert len(dashboard["top3"]) == 2


def test_zero_candidates_is_explicitly_underfilled_not_complete(migrated_sqlite_engine):
    client = _new_discovery_client(migrated_sqlite_engine, email="waiting@kivou.ch")
    _activate(client)

    status = client.get("/billing/status").json()["discovery"]
    dashboard = client.get("/dashboard").json()
    assert status == {"granted_signal_count": 0, "remaining_slots": 3, "limit": 3}
    assert dashboard["top3"] == []
    assert dashboard["plan"] == {
        "code": "discovery",
        "name": "Découverte",
        "assigned": 0,
        "opened_this_month": None,
        "quota": 3,
        "remaining": 3,
        "availability": "preparing",
        "period_end": None,
    }


def test_a_later_ingestion_fills_only_the_remaining_slot(migrated_sqlite_engine):
    _persist_candidates(migrated_sqlite_engine, count=2)
    client = _new_discovery_client(migrated_sqlite_engine, email="later@kivou.ch")
    _activate(client)
    account_id = _account_id(client)
    before = set(_grant_keys(migrated_sqlite_engine, account_id))
    assert len(before) == 2

    event, award = _candidate(20)
    result = IngestionPipeline(migrated_sqlite_engine).process(
        AcquiredPublication(event, (award,)),
        as_of=MATERIALIZED_AT.date(),
        persisted_at=MATERIALIZED_AT + dt.timedelta(minutes=2),
    )

    after = set(_grant_keys(migrated_sqlite_engine, account_id))
    assert result.signals_materialized == 1
    assert before < after
    assert len(after) == 3


def test_profile_modification_never_creates_a_new_quota(migrated_sqlite_engine):
    _persist_candidates(migrated_sqlite_engine, count=2)
    client = _new_discovery_client(migrated_sqlite_engine, email="retarget@kivou.ch")
    target_id = _activate(client)
    account_id = _account_id(client)
    before = _grant_keys(migrated_sqlite_engine, account_id)
    assert len(before) == 2

    # These facts already exist when the customer edits the active profile.
    # Rematerialization may match them, but an edit is not a second historical
    # backfill; only a subsequent acquisition may fill the remaining slot.
    _persist_candidates(migrated_sqlite_engine, count=3, start=10)

    changed = client.patch(
        f"/target-icps/{target_id}",
        json={
            "customer_input": {
                **ACTIVE_INPUT,
                "minimum_contract_value": {"currency": "EUR", "minimum_amount": 1},
            }
        },
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()["matching_revision"] == 2
    assert _grant_keys(migrated_sqlite_engine, account_id) == before


def test_repeated_profile_confirmation_keeps_the_same_lifetime_allocation(
    migrated_sqlite_engine,
):
    _persist_candidates(migrated_sqlite_engine, count=5)
    client = _new_discovery_client(migrated_sqlite_engine, email="double-confirm@kivou.ch")
    target_id = _activate(client)
    account_id = _account_id(client)
    before = _grant_keys(migrated_sqlite_engine, account_id)

    first = client.patch(
        f"/target-icps/{target_id}", json={"customer_input": ACTIVE_INPUT}
    )
    second = client.patch(
        f"/target-icps/{target_id}", json={"customer_input": ACTIVE_INPUT}
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["matching_revision"] == second.json()["matching_revision"] == 1
    assert _grant_keys(migrated_sqlite_engine, account_id) == before
    assert len(before) == 3


def test_discovery_grants_are_strictly_isolated_between_accounts(migrated_sqlite_engine):
    _persist_candidates(migrated_sqlite_engine, count=4)
    alice = _new_discovery_client(migrated_sqlite_engine, email="alice@kivou.ch")
    bob = _new_discovery_client(migrated_sqlite_engine, email="bob@kivou.ch")
    _activate(alice, label="Alice France")
    _activate(bob, label="Bob France")

    alice_grants = set(_grant_keys(migrated_sqlite_engine, _account_id(alice)))
    bob_grants = set(_grant_keys(migrated_sqlite_engine, _account_id(bob)))
    assert len(alice_grants) == len(bob_grants) == 3
    assert alice_grants.isdisjoint(bob_grants)


def test_concurrent_backfills_never_allocate_more_than_three(migrated_sqlite_engine):
    client = _new_discovery_client(migrated_sqlite_engine, email="race@kivou.ch")
    target_id = _activate(client)
    account_id = _account_id(client)
    _persist_candidates(migrated_sqlite_engine, count=5)
    materialize_existing_opportunities_for_target(
        migrated_sqlite_engine,
        target_icp_id=target_id,
        as_of=MATERIALIZED_AT.date(),
        materialized_at=MATERIALIZED_AT + dt.timedelta(minutes=1),
    )
    barrier = Barrier(2)

    def run_backfill() -> tuple[str, ...]:
        barrier.wait()
        with migrated_sqlite_engine.begin() as connection:
            return discovery.reconcile_initial_backfill(
                connection,
                account_id=account_id,
                as_of=MATERIALIZED_AT.date(),
                now=MATERIALIZED_AT + dt.timedelta(minutes=2),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _index: run_backfill(), range(2)))

    assert sum(len(result) for result in results) == 3
    assert len(_grant_keys(migrated_sqlite_engine, account_id)) == 3


def test_paid_account_access_is_unchanged_and_creates_no_discovery_grants(
    migrated_sqlite_engine,
):
    _persist_candidates(migrated_sqlite_engine, count=4)
    client = _new_discovery_client(migrated_sqlite_engine, email="paid@kivou.ch")
    account_id = _account_id(client)
    with migrated_sqlite_engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="pro",
            subscription_id="sub_discovery_backfill_paid",
            now=MATERIALIZED_AT,
        )

    _activate(client)

    assert _grant_keys(migrated_sqlite_engine, account_id) == ()
    items = client.get("/signals", params={"view": "history", "limit": 50}).json()["items"]
    assert len(items) == 4
    assert all(item["locked"] is False for item in items)


def test_backfill_accepts_displayable_official_signals_without_attached_evidence(
    migrated_sqlite_engine,
):
    _persist_candidates(migrated_sqlite_engine, count=7)
    client = _new_discovery_client(migrated_sqlite_engine, email="quality@kivou.ch")
    target_id = _activate(client)
    account_id = _account_id(client)

    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.delete(discovery_signal_grant).where(
                discovery_signal_grant.c.account_id == account_id
            )
        )
        rows = connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.materialization_award_key,
            )
            .where(materialized_signal.c.target_icp_id == target_id)
            .order_by(materialized_signal.c.signal_key)
        ).all()
        assert len(rows) == 7
        no_title, no_proof, no_holder, invalid_date, hidden_decision, *valid = rows

        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == no_title.materialization_award_key)
            .values(title="   ")
        )
        connection.execute(
            sa.delete(evidence).where(
                evidence.c.award_key == no_proof.materialization_award_key
            )
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == hidden_decision.signal_key)
            .values(icp_match_decision="hide")
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == no_holder.signal_key)
            .values(winner_name="", winner_identifier_value=None)
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == no_holder.materialization_award_key)
            .values(awardee_parties=[])
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == invalid_date.materialization_award_key)
            .values(award_date=MATERIALIZED_AT.date() + dt.timedelta(days=30))
        )

        preview = discovery.preview_initial_backfill(
            connection,
            account_id=account_id,
            as_of=MATERIALIZED_AT.date(),
        )
        excluded = {
            no_title.signal_key,
            no_holder.signal_key,
            invalid_date.signal_key,
        }
        assert excluded.isdisjoint(preview.eligible_signal_keys)
        assert no_proof.signal_key in preview.eligible_signal_keys
        assert hidden_decision.signal_key in preview.eligible_signal_keys
        assert set(preview.proposed_signal_keys).issubset(
            {no_proof.signal_key, hidden_decision.signal_key, *(row.signal_key for row in valid)}
        )

        discovery.reconcile_initial_backfill(
            connection,
            account_id=account_id,
            as_of=MATERIALIZED_AT.date(),
            now=MATERIALIZED_AT + dt.timedelta(minutes=1),
        )

    assert len(_grant_keys(migrated_sqlite_engine, account_id)) == 3


def test_candidate_ranking_is_relevance_first_and_deterministic(migrated_sqlite_engine):
    _persist_candidates(migrated_sqlite_engine, count=4)
    client = _new_discovery_client(migrated_sqlite_engine, email="ranking@kivou.ch")
    target_id = _activate(client)
    account_id = _account_id(client)

    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.delete(discovery_signal_grant).where(
                discovery_signal_grant.c.account_id == account_id
            )
        )
        keys = tuple(
            connection.scalars(
                sa.select(materialized_signal.c.signal_key)
                .where(materialized_signal.c.target_icp_id == target_id)
                .order_by(materialized_signal.c.signal_key)
            )
        )
        promising, strong_low, strong_high, weak = keys
        rankings = {
            promising: ("promising", 100),
            strong_low: ("strong", 10),
            strong_high: ("strong", 90),
            weak: ("weak", 100),
        }
        for signal_key, (band, score) in rankings.items():
            connection.execute(
                sa.update(materialized_signal)
                .where(materialized_signal.c.signal_key == signal_key)
                .values(icp_match_band=band, icp_match_normalized_score=score)
            )

        first = discovery.preview_initial_backfill(
            connection,
            account_id=account_id,
            as_of=MATERIALIZED_AT.date(),
        )
        second = discovery.preview_initial_backfill(
            connection,
            account_id=account_id,
            as_of=MATERIALIZED_AT.date(),
        )

    assert first.proposed_signal_keys == second.proposed_signal_keys
    assert first.proposed_signal_keys == (strong_high, strong_low, promising)
    assert weak not in first.proposed_signal_keys
