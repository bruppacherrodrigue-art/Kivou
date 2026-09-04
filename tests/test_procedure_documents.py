from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from signals.documents.early_capture import (
    ProcedureDocumentRecord,
    StorageQuotaReached,
    purge_expired_unlinked,
    store_procedure_document,
    stored_bytes,
)
from signals.documents.extract import TextBlock
from signals.persistence.schema import procedure_documents

NOW = dt.datetime(2026, 9, 4, tzinfo=dt.UTC)


@pytest.fixture
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    procedure_documents.create(engine)
    with engine.begin() as opened:
        yield opened


def record(**changes) -> ProcedureDocumentRecord:
    values = {
        "source_system": "boamp",
        "source_notice_id": "26-85090",
        "source_procedure_id": "procedure-1",
        "buyer_fingerprint": "buyer-1",
        "object_normalized": "transport personnes autocar chauffeur",
        "cpv_main": "60112000",
        "submission_deadline": dt.datetime(2026, 10, 2, 10, tzinfo=dt.UTC),
        "source_url": "https://example.test/dce.zip",
        "access_status": "available",
        "content": b"archive",
        "content_hash": "hash-1",
        "media_type": "application/zip",
        "blocks": (TextBlock(locator="a.pdf — page 1", text="Exigence", method="pdf_text"),),
        "captured_at": NOW,
    }
    values.update(changes)
    return ProcedureDocumentRecord(**values)


def test_store_is_idempotent_and_accounts_actual_archived_bytes(connection) -> None:
    first = store_procedure_document(connection, record(), quota_bytes=100)
    second = store_procedure_document(connection, record(), quota_bytes=100)

    assert first.created is True
    assert second.created is False
    assert stored_bytes(connection) == len(b"archive")
    row = connection.execute(sa.select(procedure_documents)).one()
    assert row.host == "example.test"
    assert row.blocks[0]["locator"] == "a.pdf — page 1"
    assert row.expires_at.replace(tzinfo=dt.UTC) == dt.datetime(
        2027, 10, 2, 10, tzinfo=dt.UTC
    )


def test_quota_stops_before_writing_the_document(connection) -> None:
    store_procedure_document(connection, record(), quota_bytes=len(b"archive"))

    with pytest.raises(StorageQuotaReached):
        store_procedure_document(
            connection,
            record(source_url="https://example.test/other.zip", content_hash="hash-2"),
            quota_bytes=len(b"archive"),
        )

    assert connection.execute(sa.select(sa.func.count()).select_from(procedure_documents)).scalar() == 1


def test_retention_only_purges_expired_procedures_without_an_award_link(connection) -> None:
    old_deadline = dt.datetime(2025, 8, 1, tzinfo=dt.UTC)
    store_procedure_document(connection, record(submission_deadline=old_deadline), quota_bytes=100)
    store_procedure_document(
        connection,
        record(
            source_url="https://example.test/linked.zip",
            content_hash="hash-linked",
            submission_deadline=old_deadline,
            join_status="linked",
            linked_award_key="award-1",
        ),
        quota_bytes=100,
    )
    store_procedure_document(
        connection,
        record(
            source_url="https://example.test/no-deadline.zip",
            content_hash="hash-none",
            submission_deadline=None,
        ),
        quota_bytes=100,
    )

    assert purge_expired_unlinked(connection, now=NOW) == 1
    statuses = connection.execute(
        sa.select(procedure_documents.c.join_status).order_by(procedure_documents.c.source_url)
    ).scalars().all()
    assert statuses == ["linked", "unlinked"]
