from __future__ import annotations

import sqlalchemy as sa

from signals.documents.model import access_family
from signals.persistence.schema import portal_capture_runtime, procedure_documents


def test_portal_statuses_are_valid_access_facts() -> None:
    assert access_family("portal_blocked") == "external_portal"
    assert access_family("cgu_restricted") == "external_portal"


def test_portal_runtime_and_access_detail_are_portable_to_sqlite() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    procedure_documents.create(engine)
    portal_capture_runtime.create(engine)

    assert "access_detail" in procedure_documents.c
    assert set(portal_capture_runtime.c.keys()) == {
        "host",
        "consecutive_errors",
        "last_request_at",
        "blocked_until",
        "created_at",
        "updated_at",
    }
