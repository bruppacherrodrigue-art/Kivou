"""Le ciblage courant reste la seule source des signaux servis au client.

Ces tests couvrent la révision de l'ICP et l'invalidation traçable sans jamais
supprimer une matérialisation. Ils utilisent les mêmes avis TED que le pipeline
afin de prouver un vrai changement de matching, pas un raccourci de test.
"""

from __future__ import annotations

import datetime as dt
import pathlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic import command
from billing_helpers import subscribe
from fastapi.testclient import TestClient

from signals.accounts.icp_input import TargetIcpInput
from signals.accounts.schema import target_icp
from signals.accounts.service import create_target_icp, update_target_icp
from signals.api import ApiConfig, create_app
from signals.billing.schema import discovery_signal_grant
from signals.connectors.ted import extract as extract_ted
from signals.engagement.schema import product_event, signal_feedback
from signals.feed.query import feed_page
from signals.ingestion.backfill import materialize_existing_opportunities_for_target
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence import persist_award_facts
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
    migrate_to_latest,
)
from signals.persistence.schema import materialized_signal

ORIGIN = "https://kivou.test"
PASSWORD = "un-mot-de-passe-assez-long"
NOW = dt.datetime(2026, 8, 20, 9, 0, tzinfo=dt.UTC)
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "ted"

MATERIALS_DE = {
    "offer_summary": "Composants de chantier",
    "offers": ["materials_and_components"],
    "territories": ["DE"],
    "minimum_contract_value": {"currency": "EUR", "minimum_amount": 0},
}
STAFFING_FR = {
    "offer_summary": "Personnel de chantier",
    "offers": ["staffing_and_labour"],
    "territories": ["FR"],
    "minimum_contract_value": {"currency": "EUR", "minimum_amount": 0},
}
EQUIPMENT_DE = {
    "offer_summary": "Location de matériel",
    "offers": ["equipment_rental"],
    "territories": ["DE"],
    "minimum_contract_value": {"currency": "EUR", "minimum_amount": 0},
}


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


def _persist_ted(engine: sa.Engine, fixture: str) -> None:
    extraction = extract_ted((FIXTURES / fixture).read_bytes(), retrieved_at=NOW)
    with engine.begin() as connection:
        for award in extraction.awards:
            persist_award_facts(
                connection,
                event=extraction.event,
                award=award,
                persisted_at=NOW,
            )


def _client(engine: sa.Engine, *, email: str = "customer@kivou.ch") -> TestClient:
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN),
        now_override=lambda: NOW,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Customer SA",
            "locale": "fr",
        },
    )
    assert response.status_code == 201
    return client


def test_populated_0016_upgrade_preserves_profiles_signals_grants_and_history(engine):
    _persist_ted(engine, "566039-2026.xml")
    client = _client(engine, email="migration@kivou.ch")
    created = client.post(
        "/target-icps", json={"label": "Matériaux", "customer_input": MATERIALS_DE}
    ).json()
    signal_key = client.get("/signals?freshness=all").json()["items"][0]["signal_id"]
    assert (
        client.put(f"/signals/{signal_key}/feedback", json={"relevance": "relevant"}).status_code
        == 200
    )
    assert client.post(f"/signals/{signal_key}/contacted").status_code == 200

    with engine.connect() as connection:
        before = {
            "signals": connection.execute(
                sa.select(sa.func.count()).select_from(materialized_signal)
            ).scalar_one(),
            "grants": connection.execute(
                sa.select(sa.func.count()).select_from(discovery_signal_grant)
            ).scalar_one(),
            "feedback": connection.execute(
                sa.select(sa.func.count()).select_from(signal_feedback)
            ).scalar_one(),
            "events": connection.execute(
                sa.select(sa.func.count()).select_from(product_event)
            ).scalar_one(),
        }

    config = alembic_config(engine)
    command.downgrade(config, "0016_campaign_factory")
    assert current_revision(engine) == "0016_campaign_factory"
    command.upgrade(config, "0017_target_icp_revision")

    assert current_revision(engine) == "0017_target_icp_revision"
    with engine.connect() as connection:
        stored_target = connection.execute(
            sa.select(target_icp).where(target_icp.c.target_icp_id == created["target_icp_id"])
        ).one()
        stored_signal = connection.execute(
            sa.select(materialized_signal).where(materialized_signal.c.signal_key == signal_key)
        ).one()
        after = {
            "signals": connection.execute(
                sa.select(sa.func.count()).select_from(materialized_signal)
            ).scalar_one(),
            "grants": connection.execute(
                sa.select(sa.func.count()).select_from(discovery_signal_grant)
            ).scalar_one(),
            "feedback": connection.execute(
                sa.select(sa.func.count()).select_from(signal_feedback)
            ).scalar_one(),
            "events": connection.execute(
                sa.select(sa.func.count()).select_from(product_event)
            ).scalar_one(),
        }

    assert stored_target.matching_revision == 1
    assert stored_target.plan_limit_code is None
    assert stored_signal.target_icp_revision == 1
    assert stored_signal.invalidated_at is None
    assert before == after


def test_target_revision_changes_only_with_matching_criteria(engine):
    from feed_helpers import make_account

    with engine.begin() as connection:
        account_id = make_account(connection, "revision@example.test", "Revision SA")
        created = create_target_icp(
            connection,
            account_id=account_id,
            label="Matériaux",
            customer_input=TargetIcpInput.model_validate(MATERIALS_DE),
            now=NOW,
        )
        assert created.matching_revision == 1

        relabelled = update_target_icp(
            connection,
            account_id=account_id,
            target_icp_id=created.target_icp_id,
            label="Composants",
            customer_input=None,
            now=NOW + dt.timedelta(minutes=1),
        )
        assert relabelled.matching_revision == 1

        described = update_target_icp(
            connection,
            account_id=account_id,
            target_icp_id=created.target_icp_id,
            label=None,
            customer_input=TargetIcpInput.model_validate(
                {**MATERIALS_DE, "offer_summary": "Nouvelle description inerte"}
            ),
            now=NOW + dt.timedelta(minutes=2),
        )
        assert described.matching_revision == 1

        retargeted = update_target_icp(
            connection,
            account_id=account_id,
            target_icp_id=created.target_icp_id,
            label=None,
            customer_input=TargetIcpInput.model_validate(STAFFING_FR),
            now=NOW + dt.timedelta(minutes=3),
        )
        assert retargeted.matching_revision == 2


def test_materialization_records_the_target_revision_and_invalidates_old_matches(engine):
    from feed_helpers import make_account

    _persist_ted(engine, "566039-2026.xml")
    _persist_ted(engine, "550374-2026.xml")
    with engine.begin() as connection:
        account_id = make_account(connection, "matching@example.test", "Matching SA")
        target = create_target_icp(
            connection,
            account_id=account_id,
            label="Matériaux Allemagne",
            customer_input=TargetIcpInput.model_validate(MATERIALS_DE),
            now=NOW,
        )

    materialize_existing_opportunities_for_target(
        engine,
        target_icp_id=target.target_icp_id,
        as_of=NOW.date(),
        materialized_at=NOW,
    )
    with engine.connect() as connection:
        first = connection.execute(sa.select(materialized_signal)).one()
    assert first.target_icp_revision == 1
    assert first.invalidated_at is None

    with engine.begin() as connection:
        changed = update_target_icp(
            connection,
            account_id=account_id,
            target_icp_id=target.target_icp_id,
            label=None,
            customer_input=TargetIcpInput.model_validate(STAFFING_FR),
            now=NOW + dt.timedelta(minutes=1),
        )
    materialize_existing_opportunities_for_target(
        engine,
        target_icp_id=target.target_icp_id,
        as_of=NOW.date(),
        materialized_at=NOW + dt.timedelta(minutes=1),
    )

    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(materialized_signal).order_by(materialized_signal.c.signal_key)
        ).all()
    assert changed.matching_revision == 2
    assert len(rows) == 2
    assert len([row for row in rows if row.invalidated_at is None]) == 1
    current = next(row for row in rows if row.invalidated_at is None)
    invalid = next(row for row in rows if row.invalidated_at is not None)
    assert current.target_icp_revision == 2
    assert invalid.target_icp_revision == 1
    assert invalid.invalidation_reason == "target_icp_criteria_changed"


def test_a_still_valid_match_is_updated_to_the_new_revision_without_duplicate(engine):
    _persist_ted(engine, "566039-2026.xml")
    client = _client(engine, email="still-valid@kivou.ch")
    created = client.post(
        "/target-icps", json={"label": "Matériaux", "customer_input": MATERIALS_DE}
    ).json()
    signal_key = client.get("/signals?freshness=all").json()["items"][0]["signal_id"]

    expanded = {
        **MATERIALS_DE,
        "secondary_offers": ["equipment_rental"],
    }
    changed = client.patch(
        f"/target-icps/{created['target_icp_id']}",
        json={"customer_input": expanded},
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()["matching_revision"] == 2
    assert [
        item["signal_id"]
        for item in client.get("/signals?freshness=all").json()["items"]
    ] == [signal_key]
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(materialized_signal).where(
                materialized_signal.c.target_icp_id == created["target_icp_id"]
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].target_icp_revision == 2
    assert rows[0].invalidated_at is None


def test_retargeting_hides_old_detail_and_reactivates_history_without_duplicate(engine):
    _persist_ted(engine, "566039-2026.xml")
    _persist_ted(engine, "550374-2026.xml")
    client = _client(engine)

    created = client.post(
        "/target-icps",
        json={"label": "Matériaux Allemagne", "customer_input": MATERIALS_DE},
    )
    assert created.status_code == 201, created.text
    target_id = created.json()["target_icp_id"]
    first_feed = client.get("/signals?freshness=all").json()["items"]
    assert len(first_feed) == 1
    signal_a = first_feed[0]["signal_id"]
    assert (
        client.put(f"/signals/{signal_a}/feedback", json={"relevance": "relevant"}).status_code
        == 200
    )
    assert client.post(f"/signals/{signal_a}/contacted").status_code == 200

    changed = client.patch(
        f"/target-icps/{target_id}",
        json={"label": "Personnel France", "customer_input": STAFFING_FR},
    )
    assert changed.status_code == 200, changed.text
    second_feed = client.get("/signals?freshness=all").json()["items"]
    assert len(second_feed) == 1
    signal_b = second_feed[0]["signal_id"]
    assert signal_b != signal_a
    assert client.get(f"/signals/{signal_a}").status_code == 404
    assert client.get(f"/signals/{signal_a}/feedback").status_code == 404

    restored = client.patch(
        f"/target-icps/{target_id}",
        json={"label": "Matériaux Allemagne", "customer_input": MATERIALS_DE},
    )
    assert restored.status_code == 200, restored.text
    final_feed = client.get("/signals?freshness=all").json()["items"]
    assert [item["signal_id"] for item in final_feed] == [signal_a]
    interaction = client.get(f"/signals/{signal_a}/feedback").json()["interaction"]
    assert interaction["relevance"] == "relevant"
    assert interaction["contacted"] is True

    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(materialized_signal).where(materialized_signal.c.target_icp_id == target_id)
        ).all()
        grants = (
            connection.execute(
                sa.select(discovery_signal_grant.c.signal_key).order_by(
                    discovery_signal_grant.c.signal_key
                )
            )
            .scalars()
            .all()
        )
        feedback_rows = connection.execute(sa.select(signal_feedback)).all()
    assert len(rows) == 2
    assert len([row for row in rows if row.signal_key == signal_a]) == 1
    assert next(row for row in rows if row.signal_key == signal_a).target_icp_revision == 3
    assert grants == [signal_a], "le déblocage consommé n'est ni rendu ni recréé"
    assert len(feedback_rows) == 1


def test_failed_rematerialization_rolls_back_the_profile_and_all_signal_changes(
    engine, monkeypatch: pytest.MonkeyPatch
):
    from signals.api import routes_icp

    _persist_ted(engine, "566039-2026.xml")
    _persist_ted(engine, "550374-2026.xml")
    client = _client(engine, email="rollback@kivou.ch")
    created = client.post(
        "/target-icps", json={"label": "Matériaux", "customer_input": MATERIALS_DE}
    ).json()
    target_id = created["target_icp_id"]
    signal_a = client.get("/signals?freshness=all").json()["items"][0]["signal_id"]

    real = routes_icp.rematerialize_target_in_transaction

    def fail_after_writes(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("injected rematerialization failure")

    monkeypatch.setattr(routes_icp, "rematerialize_target_in_transaction", fail_after_writes)
    with TestClient(
        client.app, headers={"Origin": ORIGIN}, raise_server_exceptions=False
    ) as failing:
        failing.cookies.update(client.cookies)
        response = failing.patch(
            f"/target-icps/{target_id}",
            json={"label": "Personnel", "customer_input": STAFFING_FR},
        )
    assert response.status_code == 500

    stored = client.get(f"/target-icps/{target_id}").json()
    assert stored["label"] == "Matériaux"
    assert stored["matching_revision"] == 1
    assert [item["signal_id"] for item in client.get("/signals?freshness=all").json()["items"]] == [
        signal_a
    ]


def test_new_ingestion_materializes_against_the_current_target_revision(engine):
    from feed_helpers import make_account

    extraction = extract_ted((FIXTURES / "566039-2026.xml").read_bytes(), retrieved_at=NOW)
    with engine.begin() as connection:
        account_id = make_account(connection, "pipeline@kivou.ch", "Pipeline SA")
        target = create_target_icp(
            connection,
            account_id=account_id,
            label="Personnel France",
            customer_input=TargetIcpInput.model_validate(STAFFING_FR),
            now=NOW,
        )
        changed = update_target_icp(
            connection,
            account_id=account_id,
            target_icp_id=target.target_icp_id,
            label="Matériaux Allemagne",
            customer_input=TargetIcpInput.model_validate(MATERIALS_DE),
            now=NOW + dt.timedelta(minutes=1),
        )
    assert changed.matching_revision == 2

    IngestionPipeline(engine).process(
        AcquiredPublication(extraction.event, extraction.awards),
        as_of=NOW.date(),
        persisted_at=NOW + dt.timedelta(minutes=2),
    )

    with engine.connect() as connection:
        row = connection.execute(sa.select(materialized_signal)).one()
        page = feed_page(
            connection,
            account_id=account_id,
            as_of=NOW.date(),
            freshness="all",
        )
    assert row.target_icp_revision == 2
    assert len(page.items) == 1


def test_discovery_refuses_a_new_profile_above_its_territory_limit(engine):
    client = _client(engine, email="territory-create@kivou.ch")
    response = client.post(
        "/target-icps",
        json={
            "label": "Deux pays",
            "customer_input": {**MATERIALS_DE, "territories": ["DE", "FR"]},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "territory_limit_exceeded",
        "message": "ce profil dépasse la limite territoriale de l’offre",
        "limit": 1,
        "territory_count": 2,
        "plan_code": "discovery",
    }
    assert client.get("/target-icps").json() == []


def test_discovery_refuses_an_over_limit_update_without_changing_the_profile(engine):
    client = _client(engine, email="territory-update@kivou.ch")
    created = client.post(
        "/target-icps", json={"label": "Un pays", "customer_input": MATERIALS_DE}
    ).json()

    response = client.patch(
        f"/target-icps/{created['target_icp_id']}",
        json={"customer_input": {**MATERIALS_DE, "territories": ["DE", "FR"]}},
    )

    assert response.status_code == 422
    stored = client.get(f"/target-icps/{created['target_icp_id']}").json()
    assert stored["customer_input"]["territories"] == ["DE"]
    assert stored["matching_revision"] == 1


def test_downgrade_keeps_all_territories_but_marks_profile_unusable_until_resolved(engine):
    _persist_ted(engine, "566039-2026.xml")
    client = _client(engine, email="territory-downgrade@kivou.ch")
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="pro",
            subscription_id="sub_territory_downgrade",
            now=NOW,
        )
    created = client.post(
        "/target-icps",
        json={
            "label": "Allemagne et France",
            "customer_input": {**MATERIALS_DE, "territories": ["DE", "FR"]},
        },
    )
    assert created.status_code == 201, created.text
    target_id = created.json()["target_icp_id"]
    signal_key = client.get("/signals?freshness=all").json()["items"][0]["signal_id"]

    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="essential",
            subscription_id="sub_territory_downgrade",
            now=NOW + dt.timedelta(minutes=1),
        )

    limited = client.get(f"/target-icps/{target_id}").json()
    assert limited["customer_input"]["territories"] == ["DE", "FR"]
    assert limited["plan_limit"] == {
        "code": "territory_limit_exceeded",
        "limit": 1,
        "territory_count": 2,
    }
    assert client.get("/signals?freshness=all").json()["items"] == []
    assert client.get(f"/signals/{signal_key}").status_code == 404

    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="pro",
            subscription_id="sub_territory_downgrade",
            now=NOW + dt.timedelta(minutes=2),
        )
    restored = client.get(f"/target-icps/{target_id}").json()
    assert restored["plan_limit"] is None
    assert [item["signal_id"] for item in client.get("/signals?freshness=all").json()["items"]] == [
        signal_key
    ]


def test_two_concurrent_updates_are_serialized_into_distinct_revisions(engine):
    _persist_ted(engine, "566039-2026.xml")
    _persist_ted(engine, "550374-2026.xml")
    client = _client(engine, email="concurrent@kivou.ch")
    created = client.post(
        "/target-icps", json={"label": "Initial", "customer_input": MATERIALS_DE}
    ).json()
    target_id = created["target_icp_id"]
    barrier = Barrier(2)

    def update(label: str, customer_input: dict) -> int:
        with TestClient(
            client.app,
            headers={"Origin": ORIGIN},
            raise_server_exceptions=False,
        ) as concurrent:
            concurrent.cookies.update(client.cookies)
            barrier.wait()
            return concurrent.patch(
                f"/target-icps/{target_id}",
                json={"label": label, "customer_input": customer_input},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = tuple(
            pool.map(
                lambda arguments: update(*arguments),
                (("Personnel", STAFFING_FR), ("Équipement", EQUIPMENT_DE)),
            )
        )

    assert statuses == (200, 200)
    stored = client.get(f"/target-icps/{target_id}").json()
    assert stored["matching_revision"] == 3
    assert (
        stored["customer_input"]["offers"],
        stored["customer_input"]["territories"],
    ) in ((["staffing_and_labour"], ["FR"]), (["equipment_rental"], ["DE"]))
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(materialized_signal).where(
                materialized_signal.c.target_icp_id == target_id
            )
        ).all()
    current = [row for row in rows if row.invalidated_at is None]
    assert len(current) == 1
    assert current[0].target_icp_revision == 3
