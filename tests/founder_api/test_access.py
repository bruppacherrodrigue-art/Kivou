from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from signals.founder_api.access import (
    FOUNDER_USER_HEADER,
    ORIGIN_SECRET_HEADER,
)
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FOUNDER_ALLOWED_USER_ENV, FounderApiConfig

ALLOWED_EMAIL = "rodrigue.bruppacher@gmail.com"
ALLOWED_USER = "rodrigue"
ORIGIN_SECRET = "s" * 40
NOW = dt.datetime(2026, 8, 29, 18, 30, tzinfo=dt.UTC)


def _client() -> TestClient:
    return TestClient(
        create_founder_app(
            FounderApiConfig(
                allowed_email=ALLOWED_EMAIL,
                allowed_user=ALLOWED_USER,
                origin_secret=ORIGIN_SECRET,
            ),
            now_override=lambda: NOW,
        )
    )


def _headers(
    *,
    user: str = ALLOWED_USER,
    secret: str = ORIGIN_SECRET,
) -> dict[str, str]:
    return {
        FOUNDER_USER_HEADER: user,
        ORIGIN_SECRET_HEADER: secret,
    }


def test_healthz_contains_no_internal_detail() -> None:
    with _client() as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_founder_session_fails_closed_without_origin_secret() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers={FOUNDER_USER_HEADER: ALLOWED_USER},
        )

    assert response.status_code == 403


def test_founder_session_rejects_wrong_origin_secret() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers=_headers(secret="x" * 40),
        )

    assert response.status_code == 403


def test_founder_session_requires_founder_username() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers={ORIGIN_SECRET_HEADER: ORIGIN_SECRET},
        )

    assert response.status_code == 401


def test_founder_session_rejects_every_other_username() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers=_headers(user="someoneelse"),
        )

    assert response.status_code == 403


def test_founder_session_requires_exact_username() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers=_headers(user="Rodrigue"),
        )

    assert response.status_code == 403


def test_founder_session_is_production_only_and_read_only() -> None:
    with _client() as client:
        response = client.get("/api/founder/session", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "version": "founder-session-v1",
        "service": "kivou-founder-control",
        "environment": "PRODUCTION",
        "operator_email": ALLOWED_EMAIL,
        "read_only": True,
        "generated_at": "2026-08-29T18:30:00Z",
    }


def test_founder_config_refuses_non_production_identity() -> None:
    try:
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user=ALLOWED_USER,
            origin_secret=ORIGIN_SECRET,
            environment="STAGING",  # type: ignore[arg-type]
        )
    except ValueError as error:
        assert "PRODUCTION" in str(error)
    else:
        raise AssertionError("a Founder Console non-production identity must be rejected")


def test_founder_config_normalizes_a_valid_short_username() -> None:
    config = FounderApiConfig(
        allowed_email=ALLOWED_EMAIL,
        allowed_user="  rodrigue  ",
        origin_secret=ORIGIN_SECRET,
    )

    assert config.allowed_user == ALLOWED_USER


def test_founder_config_rejects_unsafe_username() -> None:
    try:
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user="rodrigue@example.com",
            origin_secret=ORIGIN_SECRET,
        )
    except ValueError as error:
        assert FOUNDER_ALLOWED_USER_ENV in str(error)
    else:
        raise AssertionError("an unsafe Founder username must be rejected")


def test_founder_config_rejects_another_valid_username() -> None:
    try:
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user="alice",
            origin_secret=ORIGIN_SECRET,
        )
    except ValueError as error:
        assert FOUNDER_ALLOWED_USER_ENV in str(error)
        assert ALLOWED_USER in str(error)
    else:
        raise AssertionError("a different Founder username must be rejected")


def test_founder_config_requires_allowed_user_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("KIVOU_FOUNDER_ALLOWED_EMAIL", ALLOWED_EMAIL)
    monkeypatch.setenv("KIVOU_FOUNDER_ORIGIN_SECRET", ORIGIN_SECRET)
    monkeypatch.setenv("KIVOU_FOUNDER_ENVIRONMENT", "PRODUCTION")
    monkeypatch.delenv(FOUNDER_ALLOWED_USER_ENV, raising=False)

    try:
        FounderApiConfig.from_environment()
    except RuntimeError as error:
        assert FOUNDER_ALLOWED_USER_ENV in str(error)
    else:
        raise AssertionError("the Founder username environment setting must be required")
