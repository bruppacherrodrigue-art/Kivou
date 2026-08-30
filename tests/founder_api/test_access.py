from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from signals.founder_api.access import (
    ACCESS_ASSERTION_HEADER,
    ACCESS_EMAIL_HEADER,
    ORIGIN_SECRET_HEADER,
)
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig

ALLOWED_EMAIL = "rodrigue.bruppacher@gmail.com"
ORIGIN_SECRET = "s" * 40
NOW = dt.datetime(2026, 8, 29, 18, 30, tzinfo=dt.UTC)


def _client() -> TestClient:
    return TestClient(
        create_founder_app(
            FounderApiConfig(
                allowed_email=ALLOWED_EMAIL,
                origin_secret=ORIGIN_SECRET,
            ),
            now_override=lambda: NOW,
        )
    )


def _headers(
    *,
    email: str = ALLOWED_EMAIL,
    secret: str = ORIGIN_SECRET,
    assertion: str = "signed-by-cloudflare-access",
) -> dict[str, str]:
    return {
        ACCESS_EMAIL_HEADER: email,
        ACCESS_ASSERTION_HEADER: assertion,
        ORIGIN_SECRET_HEADER: secret,
    }


def test_healthz_contains_no_internal_detail() -> None:
    with _client() as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_founder_session_fails_closed_without_trusted_proxy_secret() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers={
                ACCESS_EMAIL_HEADER: ALLOWED_EMAIL,
                ACCESS_ASSERTION_HEADER: "signed-by-cloudflare-access",
            },
        )

    assert response.status_code == 403


def test_founder_session_requires_cloudflare_access_identity() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers={ORIGIN_SECRET_HEADER: ORIGIN_SECRET},
        )

    assert response.status_code == 401


def test_founder_session_rejects_every_other_email() -> None:
    with _client() as client:
        response = client.get(
            "/api/founder/session",
            headers=_headers(email="someone.else@example.com"),
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
            origin_secret=ORIGIN_SECRET,
            environment="STAGING",  # type: ignore[arg-type]
        )
    except ValueError as error:
        assert "PRODUCTION" in str(error)
    else:
        raise AssertionError("a Founder Console non-production identity must be rejected")
