from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from engagement_helpers import events
from fastapi.testclient import TestClient
from feed_helpers import (
    BOAMP_AGING,
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    SIMAP_RICH,
    boamp_award,
    materialize,
    materialize_simap,
)

from signals.api import ApiConfig, create_app
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.companies.schema import saas_company
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import contract_award, materialized_signal, supplier_directory

NOW = dt.datetime(2026, 8, 25, 9, tzinfo=dt.UTC)


def _insert_directory_company(
    connection,
    *,
    siren: str,
    name: str,
    department: str = "38",
    city: str = "Grenoble",
) -> None:
    connection.execute(
        sa.insert(supplier_directory).values(
            siren=siren,
            legal_name=name,
            legal_name_observed_at=NOW,
            naf_code="23.63Z",
            naf_observed_at=NOW,
            family_keys=["ready_mix_concrete"],
            families_observed_at=NOW,
            department=department,
            department_observed_at=NOW,
            city=city,
            city_observed_at=NOW,
            employees=24,
            employees_observed_at=NOW,
            website_url="https://egli.example/",
            domain_source="registre",
            domain_observed_at=NOW,
            directors=[{"name": "Anna Egli", "title": "Présidente"}],
            directors_observed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    migrate_to_latest(value)
    return value


@pytest.fixture
def app(engine):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
        ),
        now_override=lambda: NOW,
    )


def _signup(app, *, email: str, locale: str = "fr") -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Entreprise cliente",
            "locale": locale,
        },
    )
    assert response.status_code == 201
    return client


def _icp(client: TestClient) -> str:
    response = client.post(
        "/target-icps",
        json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT},
    )
    assert response.status_code == 201
    return response.json()["target_icp_id"]


def _pay(engine, client: TestClient) -> None:
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="pro",
            subscription_id=f"sub_{account_id}",
            now=NOW,
        )


def _seed_unlocked(engine, client: TestClient) -> str:
    icp_id = _icp(client)
    _pay(engine, client)
    with engine.begin() as connection:
        signal_key = materialize_simap(
            connection, SIMAP_RICH, target_icp_id=icp_id
        ).signal_key
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="company-api-test", limit=10
        )
        return signal_key


def test_company_endpoint_requires_authentication(app) -> None:
    anonymous = TestClient(app, headers={"Origin": ORIGIN})

    response = anonymous.get("/companies/cmp_0000000000000000")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


def test_unlocked_signal_detail_links_to_the_official_company_profile(app, engine) -> None:
    client = _signup(app, email="company-api@example.com")
    signal_key = _seed_unlocked(engine, client)

    detail = client.get(f"/signals/{signal_key}")
    company_key = detail.json()["company_key"]
    response = client.get(f"/companies/{company_key}")

    assert detail.status_code == 200
    assert detail.json()["locked"] is False
    assert company_key.startswith("cmp_")
    assert response.status_code == 200
    body = response.json()
    assert body["company_key"] == company_key
    assert "city" in body
    assert body["city"] is None  # ce signal officiel ne publie aucune commune
    assert body["official_identity"]["name"] == "Egli Gartenbau AG Sursee"
    assert body["official_identity"]["source"] == "public_notice"
    assert body["related_signals"][0]["signal_id"] == signal_key
    assert "apollo" not in response.text.lower()
    assert "contact_ref" not in response.text.lower()


def test_signal_and_company_expose_the_same_holder_market_history(app, engine) -> None:
    client = _signup(app, email="company-market-history@example.com")
    signal_key = _seed_unlocked(engine, client)

    signal = client.get(f"/signals/{signal_key}").json()
    profile = client.get(f"/companies/{signal['company_key']}").json()

    assert signal["holder_history"]["resolution"] == "company_key"
    assert signal["holder_history"]["last_12_months"]["awards_count"] == 1
    assert signal["holder_history"]["source"] == "public_awards"
    assert profile["market_summary"] == {
        **signal["holder_history"]["summary"],
        "resolution": "company_key",
        "source": "public_awards",
    }


def test_company_profile_adds_matching_directory_facts_without_contact_data(app, engine) -> None:
    client = _signup(app, email="company-directory@example.com")
    signal_key = _seed_unlocked(engine, client)
    company_key = client.get(f"/signals/{signal_key}").json()["company_key"]
    with engine.begin() as connection:
        connection.execute(
            sa.update(saas_company)
            .where(saas_company.c.company_key == company_key)
            .values(
                official_identifiers=[{"scheme": "SIRET", "value": "33136472900020"}],
                official_source="official_register",
            )
        )
        _insert_directory_company(
            connection,
            siren="331364729",
            name="Egli Gartenbau AG Sursee",
        )

    profile = client.get(f"/companies/{company_key}").json()

    assert profile["directory"] == {
        "siren": "331364729",
        "name": "Egli Gartenbau AG Sursee",
        "naf_code": "23.63Z",
        "family_labels": ["Béton prêt à l'emploi"],
        "department": "38",
        "city": "Grenoble",
        "employees": 24,
        "website_url": "https://egli.example/",
        "directors": [{"name": "Anna Egli", "title": "Présidente"}],
        "source": "registre",
        "removal_path": "/contact",
    }
    assert "professional_email" not in profile


def test_signal_detail_exposes_the_local_circuit_for_the_target_profile(app, engine) -> None:
    client = _signup(app, email="signal-local-circuit@example.com")
    signal_key = _seed_unlocked(engine, client)
    with engine.begin() as connection:
        award_key = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == signal_key
            )
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == award_key)
            .values(
                place_country="FR",
                place_of_performance={
                    "country": "FR",
                    "subdivision_code": "FR-38",
                    "locality": "Grenoble",
                },
            )
        )
        _insert_directory_company(
            connection,
            siren="331364729",
            name="Fournisseur local",
        )

    detail = client.get(f"/signals/{signal_key}").json()

    assert detail["local_circuit"] == [
        {
            "siren": "331364729",
            "name": "Fournisseur local",
            "trade": "Béton prêt à l'emploi",
            "city": "Grenoble",
            "employees": 24,
            "href": "/app/companies/directory/331364729",
            "source": "registre",
        }
    ]


def test_authenticated_directory_profile_has_a_closed_not_found_shape(app, engine) -> None:
    client = _signup(app, email="directory-route@example.com")
    icp_id = _icp(client)
    with engine.begin() as connection:
        event, awards = boamp_award(BOAMP_AGING)
        materialize(connection, event, awards[0], target_icp_id=icp_id)
        _insert_directory_company(
            connection,
            siren="331364729",
            name="SARL ALCIS TRANSPORTS",
            department="31",
            city="Toulouse",
        )

    profile = client.get("/companies/directory/331364729")
    missing = client.get("/companies/directory/000000000")

    assert profile.status_code == 200
    assert profile.json()["directory"]["name"] == "SARL ALCIS TRANSPORTS"
    assert profile.json()["markets"][0]["title"]
    assert profile.json()["markets"][0]["source"] == "public_awards"
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "company_not_found"


def test_company_list_projects_a_named_holder_even_before_enrichment(app, engine) -> None:
    client = _signup(app, email="company-unresolved-list@example.com")
    icp_id = _icp(client)
    _pay(engine, client)
    with engine.begin() as connection:
        materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)

    response = client.get("/companies")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["Egli Gartenbau AG Sursee"]
    assert response.json()["items"][0]["company_key"].startswith("cmp_")


def test_company_profile_exposes_dated_contact_note_and_signal_history(app, engine) -> None:
    client = _signup(app, email="company-history@example.com")
    signal_key = _seed_unlocked(engine, client)
    company_key = client.get(f"/signals/{signal_key}").json()["company_key"]
    assert client.post(
        f"/companies/{company_key}/contact", json={"status": "contacted"}
    ).status_code == 200
    assert client.put(
        f"/companies/{company_key}/note", json={"body": "Relancer mardi"}
    ).status_code == 200
    assert client.put(
        f"/signals/{signal_key}/feedback", json={"relevance": "relevant"}
    ).status_code == 200

    history = client.get(f"/companies/{company_key}").json()["history"]

    assert {event["type"] for event in history} >= {"contacted", "note", "signal_saved"}
    assert all(event["occurred_at"] for event in history)


def test_unlocked_feed_links_to_company_without_opening_every_signal_detail(app, engine) -> None:
    client = _signup(app, email="company-feed-api@example.com")
    signal_key = _seed_unlocked(engine, client)

    feed = client.get("/signals?freshness=all&limit=50")

    assert feed.status_code == 200
    card = next(item for item in feed.json()["items"] if item["signal_id"] == signal_key)
    assert card["locked"] is False
    assert card["company_key"].startswith("cmp_")
    profile = client.get(f"/companies/{card['company_key']}")
    assert profile.status_code == 200
    assert profile.json()["company_key"] == card["company_key"]
    assert events(engine, event_type="signal_detail_viewed") == []


def test_known_company_key_is_not_an_inter_account_oracle(app, engine) -> None:
    alice = _signup(app, email="alice-company-api@example.com")
    signal_key = _seed_unlocked(engine, alice)
    company_key = alice.get(f"/signals/{signal_key}").json()["company_key"]
    bob = _signup(app, email="bob-company-api@example.com")
    _icp(bob)
    _pay(engine, bob)

    response = bob.get(f"/companies/{company_key}")

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "company_not_found", "message": "entreprise introuvable"}
    }
    assert "egli" not in response.text.lower()


def test_locked_signal_detail_never_reveals_a_company_key(app, engine) -> None:
    client = _signup(app, email="locked-company-api@example.com")
    icp_id = _icp(client)
    with engine.begin() as connection:
        keys = [
            materialize_simap(connection, name, target_icp_id=icp_id).signal_key
            for name in ("29997-02", "33112-02", "33885-03", "34794-02")
        ]
    cards = client.get("/signals?freshness=all&limit=50").json()["items"]
    locked_key = next(card["signal_id"] for card in cards if card["locked"])

    response = client.get(f"/signals/{locked_key}")

    assert locked_key in keys
    locked_card = next(card for card in cards if card["signal_id"] == locked_key)
    assert "company_key" not in locked_card
    assert response.status_code == 200
    assert response.json()["locked"] is True
    assert "company_key" not in response.json()
    assert "holder_history" not in response.json()


def test_missing_and_malformed_company_keys_share_the_same_not_found_shape(app, engine) -> None:
    client = _signup(app, email="missing-company-api@example.com")
    _icp(client)
    _pay(engine, client)

    missing = client.get("/companies/cmp_0000000000000000")
    malformed = client.get("/companies/not-a-company-key")

    assert missing.status_code == malformed.status_code == 404
    assert missing.json() == malformed.json() == {
        "detail": {"code": "company_not_found", "message": "entreprise introuvable"}
    }
