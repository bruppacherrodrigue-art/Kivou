from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_conversion_attribution import NOW, prepared

from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.persistence.schema import (
    acquisition_conversion_event,
    acquisition_conversion_journey,
)


def client_for(engine, service, *, now: dt.datetime) -> TestClient:
    return TestClient(
        create_app(
            engine,
            ApiConfig(cookie_secure=True),
            now_override=lambda: now,
            conversion_attribution_service=service,
        ),
        base_url="https://testserver",
    )


def test_click_sets_bounded_http_only_context_and_redirects_cleanly(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=NOW + dt.timedelta(hours=1))

    response = client.get(
        f"/a/{token.raw_token}?redirect=https://evil.example.invalid/steal",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/signup"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    cookie = response.headers["set-cookie"]
    assert "kivou_attribution=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/auth/signup" in cookie
    assert "evil.example" not in response.text


def test_bad_token_sets_no_cookie_and_token_grants_no_session(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=NOW + dt.timedelta(hours=1))

    invalid = client.get(f"/a/{token.raw_token}x", follow_redirects=False)
    assert invalid.status_code == 404
    assert "set-cookie" not in invalid.headers

    accepted = client.get(f"/a/{token.raw_token}", follow_redirects=False)
    assert accepted.status_code == 303
    assert client.get("/me").status_code == 401


def test_successful_signup_consumes_attribution_in_same_account_transaction(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    clicked_at = NOW + dt.timedelta(hours=1)
    client = client_for(engine, service, now=clicked_at)
    assert client.get(f"/a/{token.raw_token}", follow_redirects=False).status_code == 303

    response = client.post(
        "/auth/signup",
        json={
            "email": "new-account@example.com",
            "password": "a-long-synthetic-account-password",
            "company_name": "Synthetic Signup",
            "locale": "fr",
        },
    )

    assert response.status_code == 201
    with engine.connect() as connection:
        journey = connection.execute(sa.select(acquisition_conversion_journey)).mappings().one()
    assert journey["account_id"] == response.json()["account_id"]
    assert "new-account@example.com" not in repr(journey)
    assert "kivou_attribution=\"\"" in response.headers["set-cookie"]


def test_last_pre_signup_click_cookie_freezes_the_selected_source(tmp_path) -> None:
    engine, service, first_token, _ = prepared(tmp_path)
    second_token = service.keyring.issue(
        first_token.payload.model_copy(update={"issued_at": NOW + dt.timedelta(minutes=30)})
    )
    client = client_for(engine, service, now=NOW + dt.timedelta(hours=1))

    assert client.get(f"/a/{first_token.raw_token}", follow_redirects=False).status_code == 303
    assert client.get(f"/a/{second_token.raw_token}", follow_redirects=False).status_code == 303
    response = client.post(
        "/auth/signup",
        json={
            "email": "last-click-account@example.com",
            "password": "a-long-synthetic-account-password",
            "company_name": "Synthetic Last Click",
            "locale": "fr",
        },
    )

    assert response.status_code == 201
    with engine.connect() as connection:
        journey = connection.execute(sa.select(acquisition_conversion_journey)).mappings().one()
    assert journey["token_fingerprint"] == second_token.token_fingerprint
    assert journey["token_fingerprint"] != first_token.token_fingerprint


def test_real_target_icp_activation_route_records_one_activation(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=NOW + dt.timedelta(days=2))
    assert client.get(f"/a/{token.raw_token}", follow_redirects=False).status_code == 303
    signup = client.post(
        "/auth/signup",
        json={
            "email": "activated-account@example.com",
            "password": "a-long-synthetic-account-password",
            "company_name": "Synthetic Activated Signup",
            "locale": "fr",
        },
    )
    assert signup.status_code == 201

    created = client.post(
        "/target-icps",
        json={
            "label": "Synthetic ICP",
            "customer_input": {
                "offers": ["materials_and_components"],
                "territories": ["CH"],
                "minimum_contract_value": {
                    "currency": "CHF",
                    "minimum_amount": 1000,
                },
            },
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "active"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_conversion_event)
            .where(acquisition_conversion_event.c.milestone == "ACTIVATED")
        ) == 1
