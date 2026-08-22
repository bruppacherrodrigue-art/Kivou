from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from feed_helpers import (
    LINKED_BOAMP,
    LINKED_DECP,
    MATERIALIZED_AT,
    MATERIALIZED_ON,
    RETRIEVED_AT,
    make_account,
    simap_award,
)

from signals.accounts.icp_input import TargetIcpInput
from signals.accounts.service import create_target_icp
from signals.api import ApiConfig, create_app
from signals.connectors.boamp import parse_award_notice
from signals.connectors.decp import parse_contract
from signals.connectors.ted import extract as extract_ted
from signals.feed.query import feed_page
from signals.ingestion.france import FranceLinker
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence import persist_award_facts
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.identity import award_key
from signals.persistence.schema import contract_award, materialized_signal, source_event

ORIGIN = "https://kivou.test"
PASSWORD = "un-mot-de-passe-assez-long"
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


def _engine(tmp_path, name="backfill.db"):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    migrate_to_latest(engine)
    return engine


def _persist_matching_awards(engine, count=1):
    fixture = pathlib.Path(__file__).parent / "fixtures" / "ted" / "550374-2026.xml"
    extraction = extract_ted(fixture.read_bytes(), retrieved_at=RETRIEVED_AT)
    event, awards = extraction.event, extraction.awards
    with engine.begin() as connection:
        for index in range(count):
            item_event = event.model_copy(
                update={
                    "provenance": event.provenance.model_copy(
                        update={
                            "source_notice_id": f"backfill-notice-{index}",
                            "source_procedure_id": f"backfill-procedure-{index}",
                        }
                    )
                }
            )
            item_award = awards[0].model_copy(
                update={
                    "event_ref": item_event.ref(),
                    "source_award_id": f"backfill-award-{index}",
                }
            )
            persist_award_facts(
                connection,
                event=item_event,
                award=item_award,
                persisted_at=MATERIALIZED_AT,
            )


def _signed_client(engine):
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN),
        now_override=lambda: MATERIALIZED_AT,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": "new-customer@kivou.ch",
            "password": PASSWORD,
            "company_name": "New Customer SA",
            "locale": "fr",
        },
    )
    assert response.status_code == 201
    return client


def _active_target(connection, account_id):
    return create_target_icp(
        connection,
        account_id=account_id,
        label="Toutes fournitures",
        customer_input=TargetIcpInput.model_validate(ACTIVE_INPUT),
        now=MATERIALIZED_AT,
    )


def test_persisted_reader_reconstructs_the_approved_canonical_models(tmp_path):
    from signals.ingestion.persisted import canonical_award, canonical_event

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'persisted.db'}")
    migrate_to_latest(engine)
    event, awards = simap_award("33112-02")
    with engine.begin() as connection:
        persist_award_facts(
            connection,
            event=event,
            award=awards[0],
            persisted_at=MATERIALIZED_AT,
        )
    with engine.connect() as connection:
        row = connection.execute(
            sa.select(source_event, contract_award).select_from(
                contract_award.join(
                    source_event, contract_award.c.event_key == source_event.c.event_key
                )
            )
        ).one()

    restored_event = canonical_event(row)
    restored_award = canonical_award(row, restored_event)

    assert restored_event.ref() == event.ref()
    assert restored_event.published_at == event.published_at
    assert restored_event.provenance.retrieved_at.date() == event.provenance.retrieved_at.date()
    assert restored_event.procedure_buyers == event.procedure_buyers
    assert restored_award == awards[0]


def test_active_target_creation_backfills_existing_facts_into_the_customer_feed(tmp_path):
    engine = _engine(tmp_path)
    _persist_matching_awards(engine)
    client = _signed_client(engine)

    response = client.post(
        "/target-icps",
        json={"label": "Toutes fournitures", "customer_input": ACTIVE_INPUT},
    )
    assert response.status_code == 201
    target_id = response.json()["target_icp_id"]
    account_id = client.get("/me").json()["account_id"]

    with engine.connect() as connection:
        signals = connection.execute(sa.select(materialized_signal)).all()
        page = feed_page(
            connection,
            account_id=account_id,
            target_icp_id=target_id,
            as_of=MATERIALIZED_ON,
            freshness="all",
        )

    assert len(signals) == 1
    assert len(page.items) == 1
    assert page.items[0].signal.icp_match_decision == "show"


def test_draft_target_does_not_backfill_existing_facts(tmp_path):
    engine = _engine(tmp_path)
    _persist_matching_awards(engine)
    client = _signed_client(engine)

    response = client.post(
        "/target-icps",
        json={"label": "Incomplet", "customer_input": {}},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(sa.func.count()).select_from(materialized_signal)
        ).scalar_one() == 0


def test_draft_to_active_update_backfills_existing_facts(tmp_path):
    engine = _engine(tmp_path)
    _persist_matching_awards(engine)
    client = _signed_client(engine)
    draft = client.post(
        "/target-icps", json={"label": "Incomplet", "customer_input": {}}
    ).json()

    response = client.patch(
        f"/target-icps/{draft['target_icp_id']}",
        json={"customer_input": ACTIVE_INPUT},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(sa.func.count()).select_from(materialized_signal)
        ).scalar_one() == 1


def test_repeated_backfill_keeps_signal_identity_and_revision_stable(tmp_path):
    from signals.ingestion.backfill import materialize_existing_opportunities_for_target

    engine = _engine(tmp_path)
    _persist_matching_awards(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "repeat@example.test", "Repeat SA")
        target = _active_target(connection, account_id)

    first = materialize_existing_opportunities_for_target(
        engine,
        target_icp_id=target.target_icp_id,
        as_of=MATERIALIZED_ON,
        materialized_at=MATERIALIZED_AT,
    )
    with engine.connect() as connection:
        before = connection.execute(
            sa.select(materialized_signal.c.signal_key, materialized_signal.c.revision)
        ).one()
    second = materialize_existing_opportunities_for_target(
        engine,
        target_icp_id=target.target_icp_id,
        as_of=MATERIALIZED_ON,
        materialized_at=MATERIALIZED_AT + dt.timedelta(minutes=1),
    )
    with engine.connect() as connection:
        after = connection.execute(
            sa.select(materialized_signal.c.signal_key, materialized_signal.c.revision)
        ).one()

    assert first.signals_materialized == 1
    assert second.signals_materialized == 0
    assert before == after


def test_backfill_caps_eligible_window_and_reports_truncation(tmp_path, caplog):
    from signals.ingestion.backfill import materialize_existing_opportunities_for_target

    engine = _engine(tmp_path, "bounded.db")
    _persist_matching_awards(engine, count=501)
    with engine.begin() as connection:
        account_id = make_account(connection, "bounded@example.test", "Bounded SA")
        target = _active_target(connection, account_id)

    result = materialize_existing_opportunities_for_target(
        engine,
        target_icp_id=target.target_icp_id,
        as_of=MATERIALIZED_ON,
        materialized_at=MATERIALIZED_AT,
    )

    assert result.candidates_available == 501
    assert result.candidates_evaluated == 500
    assert result.truncated is True
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(sa.func.count()).select_from(materialized_signal)
        ).scalar_one() == result.signals_materialized
    assert any("truncated" in record.getMessage() for record in caplog.records)


def test_backfill_limit_cannot_exceed_the_approved_mvp_ceiling(tmp_path):
    from signals.ingestion.backfill import materialize_existing_opportunities_for_target

    engine = _engine(tmp_path, "hard-cap.db")

    with pytest.raises(ValueError, match="500"):
        materialize_existing_opportunities_for_target(
            engine,
            target_icp_id="any-target",
            as_of=MATERIALIZED_ON,
            materialized_at=MATERIALIZED_AT,
            max_candidates=501,
        )


def test_linked_opportunity_uses_one_deterministic_named_representation(tmp_path):
    from signals.ingestion.backfill import materialize_existing_opportunities_for_target

    engine = _engine(tmp_path, "representative.db")
    boamp_event, boamp_awards = parse_award_notice(LINKED_BOAMP, retrieved_at=RETRIEVED_AT)
    decp_event, decp_award = parse_contract(LINKED_DECP, retrieved_at=RETRIEVED_AT)
    pipeline = IngestionPipeline(engine, linker=FranceLinker())
    pipeline.process(
        AcquiredPublication(boamp_event, boamp_awards),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )
    pipeline.process(
        AcquiredPublication(decp_event, (decp_award,)),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT + dt.timedelta(minutes=1),
    )
    with engine.begin() as connection:
        account_id = make_account(connection, "linked@example.test", "Linked SA")
        target = _active_target(connection, account_id)

    materialize_existing_opportunities_for_target(
        engine,
        target_icp_id=target.target_icp_id,
        as_of=MATERIALIZED_ON,
        materialized_at=MATERIALIZED_AT + dt.timedelta(minutes=2),
    )
    with engine.connect() as connection:
        first = connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.revision,
                materialized_signal.c.materialization_award_key,
            )
        ).one()
    materialize_existing_opportunities_for_target(
        engine,
        target_icp_id=target.target_icp_id,
        as_of=MATERIALIZED_ON,
        materialized_at=MATERIALIZED_AT + dt.timedelta(minutes=3),
    )
    with engine.connect() as connection:
        second = connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.revision,
                materialized_signal.c.materialization_award_key,
            )
        ).one()

    assert first.materialization_award_key == award_key(boamp_awards[0])
    assert second == first
