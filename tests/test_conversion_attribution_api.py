from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_conversion_attribution import NOW, prepared

from signals.api.app import create_app
from signals.api.config import ATTRIBUTION_COOKIE_NAME, ApiConfig
from signals.conversion.token import AttributionTokenKeyring
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


def seed_click(client, service, token, *, at: dt.datetime) -> None:
    """Le clic d'attribution, SANS l'atterrissage — le parcours d'inscription.

    PR2b tâche 5 a fait de `/a/{jeton}` un atterrissage : il crée lui-même un
    compte Découverte. Les tests ci-dessous portent sur l'AUTRE parcours, resté
    intact : le prospect qui s'inscrit ensuite avec sa vraie adresse et son
    propre mot de passe, et dont l'inscription doit rester attribuée.
    """
    service.record_click(token.raw_token, at=at)
    # Pas de `domain="testserver"` : httpx (`http.cookiejar` dessous) refuse de
    # réémettre un cookie dont le domaine posé n'a pas de point — un domaine à
    # un seul label est traité comme un TLD public et jamais renvoyé, même vers
    # le même hôte. Sans `domain`, httpx l'associe à l'hôte de la requête ayant
    # servi à le poser, ce qui matche `base_url="https://testserver"`.
    client.cookies.set(ATTRIBUTION_COOKIE_NAME, token.raw_token, path="/")


def test_click_lands_on_the_product_and_never_on_a_caller_supplied_redirect(
    tmp_path,
) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=NOW + dt.timedelta(hours=1))

    response = client.get(
        f"/a/{token.raw_token}?redirect=https://evil.example.invalid/steal",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/signals/")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    cookie = next(
        item
        for item in response.headers.get_list("set-cookie")
        if item.startswith("kivou_attribution=")
    )
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/auth/signup" in cookie
    assert "evil.example" not in response.text


def test_bad_token_sets_no_cookie_and_grants_no_session(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=NOW + dt.timedelta(hours=1))

    invalid = client.get(f"/a/{token.raw_token}x", follow_redirects=False)
    assert invalid.status_code == 303
    assert invalid.headers["location"] == "/signup?attribution=expired"
    assert "set-cookie" not in invalid.headers
    assert "<!doctype html>" not in invalid.text.lower()
    assert client.get("/me").status_code == 401


def test_successful_signup_consumes_attribution_in_same_account_transaction(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    clicked_at = NOW + dt.timedelta(hours=1)
    client = client_for(engine, service, now=clicked_at)
    seed_click(client, service, token, at=clicked_at)

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


def test_one_forwarded_click_can_source_two_distinct_account_signups(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    first = client_for(engine, service, now=NOW + dt.timedelta(days=1))
    second = client_for(engine, service, now=NOW + dt.timedelta(days=2))
    seed_click(first, service, token, at=NOW + dt.timedelta(days=1))
    seed_click(second, service, token, at=NOW + dt.timedelta(days=2))

    first_signup = first.post(
        "/auth/signup",
        json={
            "email": "forwarded-first@example.com",
            "password": "a-long-synthetic-account-password",
            "company_name": "Synthetic Forwarded One",
            "locale": "fr",
        },
    )
    second_signup = second.post(
        "/auth/signup",
        json={
            "email": "forwarded-second@example.com",
            "password": "a-long-synthetic-account-password",
            "company_name": "Synthetic Forwarded Two",
            "locale": "fr",
        },
    )

    assert first_signup.status_code == second_signup.status_code == 201
    assert first_signup.json()["account_id"] != second_signup.json()["account_id"]
    with engine.connect() as connection:
        journeys = connection.execute(
            sa.select(acquisition_conversion_journey).order_by(
                acquisition_conversion_journey.c.account_id
            )
        ).mappings().all()
        click_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_conversion_event)
            .where(acquisition_conversion_event.c.milestone == "CLICK")
        )
    assert len(journeys) == 2
    assert len({row["account_id"] for row in journeys}) == 2
    assert len({row["source_click_event_ref"] for row in journeys}) == 1
    assert len({row["campaign_ref"] for row in journeys}) == 1
    assert len({row["member_ref"] for row in journeys}) == 1
    assert len({row["acquisition_opportunity_id"] for row in journeys}) == 1
    assert click_count == 1
    assert "forwarded-first@example.com" not in repr(journeys)
    assert "forwarded-second@example.com" not in repr(journeys)


def test_last_pre_signup_click_cookie_freezes_the_selected_source(tmp_path) -> None:
    engine, service, first_token, _ = prepared(tmp_path)
    second_token = AttributionTokenKeyring(
        current_key_version="attribution-test-old",
        keys={"attribution-test-old": b"old-synthetic-attribution-secret"},
    ).issue(first_token.payload.model_copy(update={"key_version": None}))
    client = client_for(engine, service, now=NOW + dt.timedelta(hours=1))

    seed_click(client, service, first_token, at=NOW + dt.timedelta(hours=1))
    seed_click(client, service, second_token, at=NOW + dt.timedelta(hours=1))
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
    seed_click(client, service, token, at=NOW + dt.timedelta(days=2))
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
