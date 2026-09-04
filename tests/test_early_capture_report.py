from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.documents.early_capture import capture_report
from signals.persistence.schema import procedure_documents, source_event


def test_report_groups_hosts_from_persisted_rows_and_estimates_coverage() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    source_event.create(engine)
    procedure_documents.create(engine)
    # A replay captures today notices published inside an older window.
    created = dt.datetime(2026, 9, 10, tzinfo=dt.UTC)
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
                    created_at=created,
                )
            )
        rows = [
            ("PLACE", "tender-0", "www.marches-publics.gouv.fr", "available", None, 100, 2),
            (
                "achat",
                "tender-1",
                "www.achatpublic.com",
                "portal_blocked",
                "robots_disallowed",
                0,
                0,
            ),
            ("max", "tender-2", "marches.maximilien.fr", "available", None, 300, 4),
        ]
        for key, notice, host, status, detail, size, requirements in rows:
            connection.execute(
                sa.insert(procedure_documents).values(
                    procedure_document_key=key,
                    source_system="boamp",
                    source_notice_id=notice,
                    source_url=f"https://{host}/dce",
                    host=host,
                    access_status=status,
                    access_detail=detail,
                    byte_size=size,
                    classified_requirements_count=requirements,
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
    assert report.hosts[0].portal_url == "https://www.marches-publics.gouv.fr"
    assert report.hosts[0].average_folder_bytes == 100
    assert report.hosts[0].classified_requirements_per_folder == 2.0
    assert report.hosts[1].blocked == 1
    assert report.hosts[1].block_reasons == ("robots_disallowed",)
    assert report.average_folder_bytes == 200
    assert report.estimated_award_coverage_at_three_months == 2 / 3
