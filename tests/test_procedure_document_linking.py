from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.documents.early_capture import (
    ProcedureDocumentRecord,
    confirm_document_join,
    resolve_award_documents,
    store_procedure_document,
)
from signals.documents.extract import TextBlock
from signals.domain import ContractAward, CpvCode, Provenance, PublicEvent
from signals.persistence.schema import procedure_documents

NOW = dt.datetime(2026, 9, 4, tzinfo=dt.UTC)


def event(
    *, procedure: str | None, related: tuple[str, ...] = (), buyer_name: str = "Ville Exemple"
) -> PublicEvent:
    from signals.domain import OrganizationRef

    return PublicEvent(
        provenance=Provenance(
            source_system="boamp",
            source_country="FR",
            source_notice_id="award-notice",
            source_procedure_id=procedure,
        ),
        event_type="award_notice",
        source_notice_links=related,
        procedure_buyers=(OrganizationRef(legal_name=buyer_name, country="FR"),),
    )


def award(title: str = "Transport scolaire") -> ContractAward:
    return ContractAward(
        event_ref=event(procedure="procedure-1").ref(),
        title=title,
        cpv_main=CpvCode(code="60112000"),
        winner_status="undisclosed",
    )


def insert_document(connection, *, notice="tender-1", procedure="procedure-1") -> None:
    store_procedure_document(
        connection,
        ProcedureDocumentRecord(
            source_system="boamp",
            source_notice_id=notice,
            source_procedure_id=procedure,
            buyer_fingerprint=None,
            object_normalized="transport scolaire",
            cpv_main="60112000",
            submission_deadline=None,
            source_url=f"https://example.test/{notice}.txt",
            access_status="available",
            content=b"Le titulaire doit assurer une permanence.",
            content_hash=notice,
            media_type="text/plain",
            blocks=(TextBlock(locator="ligne 1", text="obligation", method="plain_text"),),
            captured_at=NOW,
        ),
        quota_bytes=10_000,
    )


def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    procedure_documents.create(engine)
    return engine


def test_explicit_notice_reference_wins_over_other_modes() -> None:
    engine = connection()
    with engine.begin() as opened:
        insert_document(opened, notice="explicit", procedure="other")
        resolution = resolve_award_documents(
            opened, event=event(procedure="procedure-1", related=("explicit",)), award=award()
        )

    assert resolution.status == "linked"
    assert resolution.match_mode == "explicit_notice"
    assert resolution.blocks


def test_procedure_identifier_is_a_strong_join() -> None:
    engine = connection()
    with engine.begin() as opened:
        insert_document(opened)
        resolution = resolve_award_documents(
            opened, event=event(procedure="procedure-1"), award=award()
        )

    assert resolution.status == "linked"
    assert resolution.match_mode == "procedure_id"
    assert resolution.blocks
    assert len(resolution.analysis.requirements) == 1
    with engine.connect() as opened:
        assert opened.execute(
            sa.select(procedure_documents.c.classified_requirements_count)
        ).scalar_one() == 1


def test_fingerprint_match_is_quarantined_and_never_calls_classifier() -> None:
    engine = connection()
    calls = []
    with engine.begin() as opened:
        insert_document(opened, procedure="different")
        opened.execute(
            sa.update(procedure_documents).values(
                buyer_fingerprint="forced-match"
            )
        )
        resolution = resolve_award_documents(
            opened,
            event=event(procedure=None),
            award=award(),
            buyer_identity="forced-match",
            classify=lambda blocks: calls.append(blocks),
        )

    assert resolution.status == "review_required"
    assert resolution.match_mode == "fingerprint"
    assert resolution.blocks == ()
    assert resolution.analysis is None
    assert calls == []

    with engine.begin() as opened:
        assert confirm_document_join(opened, linked_award_key=resolution.linked_award_key) == 1
        assert opened.execute(
            sa.select(procedure_documents.c.join_status)
        ).scalar_one() == "linked"
