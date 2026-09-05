from __future__ import annotations

import logging

import pytest
import sqlalchemy as sa
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from signals.api import ApiConfig, create_app
from signals.api.errors import api_error
from signals.persistence.database import create_database_engine, migrate_to_latest


@pytest.fixture
def client(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    app = create_app(engine, ApiConfig(cookie_secure=False, allowed_origin="https://kivou.test"))

    @app.get("/__test/value-error")
    def value_error() -> None:
        raise ValueError("internal boundary failed")

    @app.get("/__test/converted-error")
    def converted_error(request: Request) -> None:
        try:
            request.app.state.engine.connect().execute(sa.text("SELECT missing_column"))
        except SQLAlchemyError as error:
            raise api_error(422, "invalid_input", "invalid") from error

    return TestClient(app)


def test_value_error_converted_to_422_keeps_its_trace_in_server_logs(client, caplog):
    with caplog.at_level(logging.ERROR, logger="signals.api.app"):
        response = client.get("/__test/value-error")

    assert response.status_code == 422
    record = next(record for record in caplog.records if record.exc_info)
    assert record.request_method == "GET"
    assert record.request_path == "/__test/value-error"
    assert record.response_status == 422
    assert record.exc_info[0] is ValueError


def test_http_4xx_chained_from_server_error_keeps_cause_trace(client, caplog):
    with caplog.at_level(logging.ERROR, logger="signals.api.app"):
        response = client.get("/__test/converted-error")

    assert response.status_code == 422
    record = next(record for record in caplog.records if record.exc_info)
    assert record.request_path == "/__test/converted-error"
    assert issubclass(record.exc_info[0], SQLAlchemyError)


def test_expected_client_4xx_without_server_cause_is_not_logged(client, caplog):
    with caplog.at_level(logging.ERROR, logger="signals.api.app"):
        response = client.get("/me")

    assert response.status_code == 401
    assert not caplog.records
