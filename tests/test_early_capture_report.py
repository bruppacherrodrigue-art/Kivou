from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.documents.early_capture import capture_report
from signals.persistence.schema import procedure_documents, source_event


def test_report_groups_hosts_from_persisted_rows_and_estimates_coverage() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    source_event.create(engine)
    procedure_documents.create(engine)
    created = dt.datetime(2026, 9, 3, tzinfo=dt.UTC)
    with engine.begin() as connection:
        for index in range(3):
            connection.execute(
                sa.insert(source_event).values(
                    event_key=f"boamp:tender-{index}:",
                    source_system="boamp",
                    source_notice_id=f"tender-{index}",
                    source_country="FR",
                    event_type="tender_notice",
                    published_on=dt.date(2026, 9, 3),
                    procedure_buyers=[],
                    related_notice_ids=[],
                    created_at=created,
                )
            )
        rows = [
            ("PLACE", "PLACE", "www.marches-publics.gouv.fr", "available", 100),
            ("achat", "achatpublic", "www.achatpublic.com", "external", 0),
            ("max", "Maximilien", "marches.maximilien.fr", "available", 300),
        ]
        for key, notice, host, status, size in rows:
            connection.execute(
                sa.insert(procedure_documents).values(
                    procedure_document_key=key,
                    source_system="boamp",
                    source_notice_id=notice,
                    source_url=f"https://{host}/dce",
                    host=host,
                    access_status=status,
                    byte_size=size,
                    blocks=[],
                    join_status="unlinked",
                    captured_at=created,
                    created_at=created,
                )
            )

        report = capture_report(
            connection,
            source="boamp",
            since=dt.date(2026, 9, 1),
            until=dt.date(2026, 9, 7),
        )

    assert report.notices_ingested == 3
    assert [(row.host_group, row.downloaded, row.total) for row in report.hosts] == [
        ("PLACE", 1, 1),
        ("achatpublic", 0, 1),
        ("Maximilien", 1, 1),
    ]
    assert report.average_folder_bytes == 200
    assert report.estimated_award_coverage_at_three_months == 2 / 3
