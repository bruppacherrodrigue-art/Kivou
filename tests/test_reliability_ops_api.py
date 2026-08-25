from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from signals.api.app import create_app
from signals.api.config import ACQUISITION_ENVIRONMENT_ENV, ApiConfig
from signals.operations.contracts import HermesRuntimeIdentity
from signals.operations.service import OperationsReadService
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.supervisor.pin import load_hermes_pin

NOW = dt.datetime(2026, 8, 23, 10, tzinfo=dt.UTC)
PASSWORD = "a-long-synthetic-password"


def _engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'ops-api.db'}")
    migrate_to_latest(engine)
    return engine


def _signup(client: TestClient, email: str) -> str:
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Synthetic Internal Operator",
            "locale": "fr",
        },
    )
    assert response.status_code == 201
    return response.json()["account_id"]


def _login(client: TestClient, email: str) -> None:
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_detailed_ops_endpoints_reuse_internal_allowlist_and_default_deny(tmp_path) -> None:
    engine = _engine(tmp_path)
    default_app = create_app(engine, ApiConfig(cookie_secure=False), now_override=lambda: NOW)
    anonymous = TestClient(default_app)
    assert anonymous.get("/internal/acquisition-ops/health").status_code == 401

    customer = TestClient(default_app)
    _signup(customer, "customer@example.com")
    assert customer.get("/internal/acquisition-ops/health").status_code == 403

    bootstrap = TestClient(default_app)
    account_id = _signup(bootstrap, "operator@example.com")
    operator_app = create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            cockpit_operator_account_ids=frozenset({account_id}),
            acquisition_environment="STAGING",
        ),
        now_override=lambda: NOW,
    )
    operator = TestClient(operator_app)
    _login(operator, "operator@example.com")

    for path in (
        "/internal/acquisition-ops/health",
        "/internal/acquisition-ops/readiness",
        "/internal/acquisition-ops/incidents",
        "/internal/acquisition-ops/dead-letters",
    ):
        response = operator.get(path)
        assert response.status_code == 200, response.text

    readiness = operator.get("/internal/acquisition-ops/readiness").json()
    assert readiness["highest_safe_mode"] == "SHADOW"
    assert operator.get("/internal/acquisition-ops/incidents?limit=101").status_code == 422


def test_process_local_runtime_injections_cannot_upgrade_durable_readiness(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    pin = load_hermes_pin()
    service = OperationsReadService(
        engine,
        observed_runtime=HermesRuntimeIdentity(
            repository=pin.repository,
            tag=pin.tag,
            commit=pin.commit,
            version=pin.version,
            python_contract=pin.python,
        ),
        supervisor_heartbeat_at=NOW - dt.timedelta(minutes=1),
        environment_identity="STAGING",
    )

    health = service.health(observed_at=NOW)
    readiness = service.readiness(evaluated_at=NOW)

    assert health.hermes_runtime == "NOT_READY"
    assert health.supervisor_loop == "NOT_READY"
    assert "RUNTIME_OBSERVATION_UNAVAILABLE" in health.reason_codes
    assert readiness.h_a_runtime.status == "NOT_READY"
    assert readiness.h_d_shadow.status == "INSUFFICIENT_EVIDENCE"
    assert readiness.h_e_capped.status == "NOT_READY"
    assert readiness.highest_safe_mode == "SHADOW"


def test_environment_identity_is_explicit_and_defaults_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv(ACQUISITION_ENVIRONMENT_ENV, raising=False)
    assert ApiConfig.from_environment().acquisition_environment == "UNCONFIGURED"
    monkeypatch.setenv(ACQUISITION_ENVIRONMENT_ENV, "STAGING")
    assert ApiConfig.from_environment().acquisition_environment == "STAGING"
    monkeypatch.setenv(ACQUISITION_ENVIRONMENT_ENV, "guessed-production")
    try:
        ApiConfig.from_environment()
    except ValueError as error:
        assert ACQUISITION_ENVIRONMENT_ENV in str(error)
    else:
        raise AssertionError("invalid environment identity must fail closed")


def test_ops_contracts_never_expose_seeded_pii_or_secrets(tmp_path) -> None:
    engine = _engine(tmp_path)
    service = OperationsReadService(engine)
    serialized = service.health(observed_at=NOW).model_dump_json() + service.readiness(
        evaluated_at=NOW
    ).model_dump_json()
    for marker in (
        "lead-marker@example.invalid",
        "customer-marker@example.invalid",
        "person marker",
        "company marker",
        "response body marker",
        "sk_live_marker",
        "webhook-secret-marker",
        "session-cookie-marker",
        "hmac-secret-marker",
    ):
        assert marker not in serialized
