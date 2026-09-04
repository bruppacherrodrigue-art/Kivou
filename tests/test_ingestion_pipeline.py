from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from feed_helpers import (
    LINKED_BOAMP,
    LINKED_DECP,
    MATERIALIZED_AT,
    MATERIALIZED_ON,
    RETRIEVED_AT,
    make_account,
    make_icp,
    simap_award,
)

from signals.accounts.icp_input import TargetIcpInput
from signals.accounts.schema import target_icp
from signals.accounts.service import create_target_icp
from signals.connectors.boamp import parse_award_notice
from signals.connectors.decp import parse_contract
from signals.connectors.ted import extract as extract_ted
from signals.documents.early_capture import ProcedureDocumentRecord, store_procedure_document
from signals.documents.extract import TextBlock
from signals.feed.query import feed_page
from signals.ingestion.france import FranceLinker
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    contract_award,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.understanding import ContractUnderstandingEngine


def test_pipeline_persists_facts_and_materializes_only_for_active_matching_icps(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "active@example.test", "Active SA")
        active_id = make_icp(
            connection,
            account_id,
            offers=["staffing_and_labour", "equipment_rental", "materials_and_components"],
            buyer_trades=[],
            territories=["FR"],
            minimum_contract_value={"currency": "EUR", "minimum_amount": 0},
        )
        draft = create_target_icp(
            connection,
            account_id=account_id,
            label="Incomplete",
            customer_input=TargetIcpInput(),
            now=MATERIALIZED_AT,
        )
        assert draft.status == "draft"

    fixture = pathlib.Path(__file__).parent / "fixtures" / "ted" / "550374-2026.xml"
    extraction = extract_ted(fixture.read_bytes(), retrieved_at=RETRIEVED_AT)
    event, awards = extraction.event, extraction.awards
    outcome = IngestionPipeline(engine).process(
        AcquiredPublication(event, awards),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )

    with engine.connect() as connection:
        signal_targets = connection.execute(
            sa.select(materialized_signal.c.target_icp_id)
        ).scalars().all()
        statuses = dict(
            connection.execute(sa.select(target_icp.c.target_icp_id, target_icp.c.status)).all()
        )

    assert outcome.records_persisted == len(awards)
    assert outcome.signals_materialized >= 1
    assert set(signal_targets) == {active_id}
    assert statuses[draft.target_icp_id] == "draft"


def test_facts_remain_durable_when_no_customer_match_exists(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'facts-only.db'}")
    migrate_to_latest(engine)
    event, awards = simap_award("33112-02")

    outcome = IngestionPipeline(engine).process(
        AcquiredPublication(event, awards),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )

    with engine.connect() as connection:
        event_count = connection.execute(sa.select(sa.func.count()).select_from(source_event)).scalar()
        award_count = connection.execute(
            sa.select(sa.func.count()).select_from(contract_award)
        ).scalar()
        signal_count = connection.execute(
            sa.select(sa.func.count()).select_from(materialized_signal)
        ).scalar()

    assert outcome.records_persisted == len(awards)
    assert event_count == 1
    assert award_count == len(awards)
    assert signal_count == 0


def test_strong_early_document_join_classifies_only_when_award_arrives(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'deferred.db'}")
    migrate_to_latest(engine)
    event, awards = parse_award_notice(LINKED_BOAMP, retrieved_at=RETRIEVED_AT)
    content = b"Le titulaire doit assurer une permanence quotidienne."
    with engine.begin() as connection:
        store_procedure_document(
            connection,
            ProcedureDocumentRecord(
                source_system="boamp",
                source_notice_id=event.source_notice_links[0],
                source_procedure_id="other-procedure",
                buyer_fingerprint=None,
                object_normalized="unrelated",
                cpv_main="60112000",
                submission_deadline=None,
                source_url="https://example.test/dce.txt",
                access_status="available",
                content=content,
                content_hash="deferred",
                media_type="text/plain",
                blocks=(
                    TextBlock(
                        locator="ligne 1",
                        text=content.decode(),
                        method="plain_text",
                    ),
                ),
                captured_at=RETRIEVED_AT,
            ),
            quota_bytes=10_000,
        )

    recorded = []
    delegate = ContractUnderstandingEngine()

    class RecordingUnderstanding:
        def understand(self, award, event, *, document_requirements=()):
            recorded.extend(document_requirements)
            return delegate.understand(
                award, event, document_requirements=document_requirements
            )

    pipeline = IngestionPipeline(engine)
    pipeline.understanding = RecordingUnderstanding()
    pipeline.process(
        AcquiredPublication(event, (awards[0],)),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )

    assert [requirement.statement for requirement in recorded] == [
        "Le titulaire doit assurer une permanence quotidienne."
    ]


def test_fact_persistence_is_not_rolled_back_by_customer_matching_failure(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'facts-first.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "facts-first@example.test", "Facts First SA")
        make_icp(
            connection,
            account_id,
            offers=["materials_and_components"],
            buyer_trades=[],
            territories=["CH"],
            minimum_contract_value={"currency": "CHF", "minimum_amount": 0},
        )
    event, awards = simap_award("33112-02")
    pipeline = IngestionPipeline(engine)

    class FailingMatching:
        def match(self, *_args, **_kwargs):
            raise RuntimeError("matching unavailable")

    pipeline.matching = FailingMatching()

    with pytest.raises(RuntimeError, match="matching unavailable"):
        pipeline.process(
            AcquiredPublication(event, awards),
            as_of=MATERIALIZED_ON,
            persisted_at=MATERIALIZED_AT,
        )

    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(source_event)).scalar_one() == 1
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(contract_award)).scalar_one()
            == len(awards)
        )
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(materialized_signal)).scalar_one()
            == 0
        )


def test_late_decp_representation_joins_the_existing_boamp_opportunity(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'late-link.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "france-link@example.test", "France Link SA")
        target_id = make_icp(
            connection,
            account_id,
            offers=[
                "materials_and_components",
                "equipment_rental",
                "staffing_and_labour",
                "transport_and_logistics",
                "specialist_subcontracting",
                "safety_equipment",
                "waste_and_environmental_services",
            ],
            buyer_trades=[],
            territories=["FR"],
            minimum_contract_value={"currency": "EUR", "minimum_amount": 0},
        )
    boamp_event, boamp_awards = parse_award_notice(LINKED_BOAMP, retrieved_at=RETRIEVED_AT)
    decp_event, decp_award = parse_contract(LINKED_DECP, retrieved_at=RETRIEVED_AT)
    pipeline = IngestionPipeline(engine, linker=FranceLinker())

    pipeline.process(
        AcquiredPublication(boamp_event, boamp_awards),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )
    with engine.connect() as connection:
        original = connection.execute(
            sa.select(opportunity_representation.c.opportunity_key)
        ).scalar_one()
        original_signal = connection.execute(
            sa.select(materialized_signal.c.signal_key)
        ).scalar_one()

    outcome = pipeline.process(
        AcquiredPublication(decp_event, (decp_award,)),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT + dt.timedelta(hours=1),
    )
    with engine.connect() as connection:
        opportunities = connection.execute(
            sa.select(opportunity_representation.c.opportunity_key).order_by(
                opportunity_representation.c.award_key
            )
        ).scalars().all()
        signals = connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.target_icp_id,
            )
        ).all()
        page = feed_page(
            connection,
            account_id=account_id,
            as_of=MATERIALIZED_ON,
            freshness="all",
        )

    assert outcome.representations_linked == 1
    assert opportunities == [original, original]
    assert signals == [(original_signal, target_id)]
    assert len(page.items) == 1
    assert page.items[0].display is not None
    assert page.items[0].display.name != LINKED_DECP["titulaire_id_1"]


def test_two_existing_opportunities_are_not_silently_merged_by_a_late_link(
    tmp_path, caplog
):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'conflict.db'}")
    migrate_to_latest(engine)
    event, awards = parse_award_notice(LINKED_BOAMP, retrieved_at=RETRIEVED_AT)
    duplicate_event = event.model_copy(
        update={
            "provenance": event.provenance.model_copy(
                update={"source_notice_id": "intentional-conflict-copy"}
            )
        }
    )
    duplicate_award = awards[0].model_copy(
        update={
            "event_ref": duplicate_event.ref(),
            "source_award_id": "intentional-conflict-copy",
        }
    )
    no_link = IngestionPipeline(engine)
    no_link.process(
        AcquiredPublication(event, awards),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )
    no_link.process(
        AcquiredPublication(duplicate_event, (duplicate_award,)),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT,
    )
    decp_event, decp_award = parse_contract(LINKED_DECP, retrieved_at=RETRIEVED_AT)

    outcome = IngestionPipeline(engine, linker=FranceLinker()).process(
        AcquiredPublication(decp_event, (decp_award,)),
        as_of=MATERIALIZED_ON,
        persisted_at=MATERIALIZED_AT + dt.timedelta(hours=1),
    )

    with engine.connect() as connection:
        opportunities = connection.execute(
            sa.select(opportunity_representation.c.opportunity_key)
        ).scalars().all()
    assert outcome.opportunity_conflicts == 1
    assert outcome.representations_linked == 0
    assert len(set(opportunities)) == 3
    conflict = next(
        record for record in caplog.records if record.getMessage().startswith("opportunity conflict")
    )
    assert "réconciliation requise" in conflict.getMessage()
    assert conflict.source_system == "decp"
    assert conflict.source_notice_id == decp_event.provenance.source_notice_id
