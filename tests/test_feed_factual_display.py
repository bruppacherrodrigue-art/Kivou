"""Phase 1 — la hiérarchie client est construite uniquement avec des faits."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    materialize,
    pin_session_cookie,
    simap_award,
)

from signals.api import ApiConfig, create_app
from signals.feed.factual_display import _headline
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import materialized_signal

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def client(engine) -> TestClient:
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=lambda: NOW,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": "factual-display@kivou.eu",
            "password": PASSWORD,
            "company_name": "Factual Display",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(client, response)
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id="sub_factual_display",
            now=NOW,
        )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps",
        json={"label": "Faits", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]


def _feed_item(client: TestClient, signal_key: str) -> dict:
    response = client.get("/signals", params={"view": "history", "limit": 50})
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["signal_id"] == signal_key)


def test_rich_title_starts_with_the_winner_and_never_with_an_identifier(
    client, engine, icp
) -> None:
    event, awards = simap_award("33112-02")
    with engine.begin() as connection:
        signal_key = materialize(
            connection, event, awards[0], target_icp_id=icp
        ).signal_key

    item = _feed_item(client, signal_key)
    display = item["factual_display"]

    assert display["headline"].startswith(item["company"]["name"])
    assert "remporte" in display["headline"]
    assert display["market_summary"] == item["contract"]["title"]
    assert display["date"] == {
        "value": item["event"]["date"],
        "kind": item["event"]["clock"],
    }
    identifier = item["company"]["identifier"]
    if identifier is not None:
        assert identifier["value"] not in display["headline"]


def test_missing_object_amount_and_place_use_the_published_buyer_fallback(
    client, engine, icp
) -> None:
    event, awards = simap_award("29997-02")
    award = awards[0].model_copy(
        update={"title": None, "value": None, "place_of_performance": None}
    )
    with engine.begin() as connection:
        signal_key = materialize(connection, event, award, target_icp_id=icp).signal_key

    item = _feed_item(client, signal_key)
    display = item["factual_display"]
    buyer = item["contract"]["buyer"]["name"]

    assert display["headline"] == (
        f"{item['company']['name']} remporte un marché attribué par {buyer}"
    )
    assert display["market_summary"] is None
    assert set(display["missing_fields"]) >= {"market_object", "amount", "location"}
    assert display["completeness"] == "partial"


def test_fallback_never_reads_analysis_or_adds_a_person_or_urgency(client, engine, icp) -> None:
    event, awards = simap_award("33885-03")
    event = event.model_copy(update={"procedure_buyers": ()})
    award = awards[0].model_copy(
        update={"title": None, "value": None, "place_of_performance": None}
    )
    with engine.begin() as connection:
        signal_key = materialize(connection, event, award, target_icp_id=icp).signal_key
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal_key)
            .values(
                inferred_contract_summary="URGENT : contacter Jean Dupont",
                plausible_needs=[
                    {
                        "category": "workforce_capacity",
                        "statement": "Recruter immédiatement une équipe",
                    }
                ],
            )
        )

    item = _feed_item(client, signal_key)
    display_text = str(item["factual_display"])

    assert item["factual_display"]["headline"] == (
        f"Marché attribué à {item['company']['name']}"
    )
    assert "Jean Dupont" not in display_text
    assert "URGENT" not in display_text
    assert "Recruter" not in display_text


def test_notification_date_is_never_presented_as_an_award_date(client, engine, icp) -> None:
    event, awards = simap_award("34794-02")
    award = awards[0].model_copy(
        update={
            "award_date": None,
            "contract_notification_date": dt.date(2026, 8, 12),
        }
    )
    with engine.begin() as connection:
        signal_key = materialize(connection, event, award, target_icp_id=icp).signal_key

    display = _feed_item(client, signal_key)["factual_display"]

    assert display["date"] == {"value": "2026-08-12", "kind": "notification"}


def test_fact_copy_uses_the_account_language_without_changing_facts(client, engine, icp) -> None:
    event, awards = simap_award("38918-02")
    with engine.begin() as connection:
        signal_key = materialize(
            connection, event, awards[0], target_icp_id=icp
        ).signal_key

    french = _feed_item(client, signal_key)
    response = client.patch("/me", json={"locale": "en"})
    assert response.status_code == 200, response.text
    english = _feed_item(client, signal_key)

    assert "remporte" in french["factual_display"]["headline"]
    assert "wins" in english["factual_display"]["headline"]
    assert french["company"] == english["company"]
    # `cpv_label` est le libellé officiel CPV 2008 traduit dans la langue du
    # compte, pas une lecture Kivou : on compare le reste du contrat à
    # l'identique, puis on vérifie que le code (`cpv`) est inchangé et que
    # les deux libellés traduits sont ceux attendus.
    assert {k: v for k, v in french["contract"].items() if k != "cpv_label"} == {
        k: v for k, v in english["contract"].items() if k != "cpv_label"
    }
    assert french["contract"]["cpv"] == english["contract"]["cpv"]


def test_history_api_applies_winner_and_current_event_filters(client, engine, icp) -> None:
    recent_event, recent_awards = simap_award("29997-02")
    recent_award = recent_awards[0].model_copy(
        update={"award_date": dt.date(2026, 8, 13)}
    )
    stale_event, stale_awards = simap_award("33112-02")
    stale_award = stale_awards[0].model_copy(
        update={"award_date": dt.date(2024, 1, 3)}
    )
    with engine.begin() as connection:
        recent_key = materialize(
            connection, recent_event, recent_award, target_icp_id=icp
        ).signal_key
        materialize(connection, stale_event, stale_award, target_icp_id=icp)

    winner = recent_award.awardee_organizations()[0].legal_name
    winner_response = client.get(
        "/signals",
        params={"view": "history", "winner": winner, "limit": 50},
    )
    event_response = client.get(
        "/signals",
        params={"view": "history", "primary_event": "recent_award", "limit": 50},
    )

    assert winner_response.status_code == 200, winner_response.text
    assert event_response.status_code == 200, event_response.text
    assert [item["signal_id"] for item in winner_response.json()["items"]] == [recent_key]
    assert [item["signal_id"] for item in event_response.json()["items"]] == [recent_key]


def test_headline_is_bounded_after_composing_published_facts() -> None:
    headline = _headline(
        company="Entreprise " + "très longue " * 80,
        market_object="Objet " + "documenté " * 80,
        amount=None,
        location=None,
        buyer=None,
        lang="fr",
    )

    assert len(headline) <= 220
    assert headline.endswith("…")


# ─── Un identifiant n'est pas un nom, un pays n'est pas un lieu ───────────────


def _decp_like(event, award):
    """Le contrat tel que DECP 2022 le publie : SIRET d'acheteur, code postal seul."""
    from signals.domain.values import Location, OrganizationIdentifier, OrganizationRef

    siret = "27920022400012"
    buyer = OrganizationRef(
        legal_name=siret,
        identifiers=(OrganizationIdentifier(scheme="SIRET", value=siret),),
        country="FR",
    )
    return (
        event.model_copy(update={"procedure_buyers": (buyer,)}),
        award.model_copy(
            update={"place_of_performance": Location(country="FR", postal_code="92350")}
        ),
    )


@pytest.fixture
def decp_like_signal(client: TestClient, icp: str, engine):
    event, awards = simap_award("33112-02")
    event, award = _decp_like(event, awards[0])
    with engine.begin() as connection:
        return materialize(connection, event, award, target_icp_id=icp)


def test_a_buyer_known_only_by_its_siret_has_no_name(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    buyer = body["contract"]["buyer"]
    assert buyer["name"] is None
    assert buyer["identifier"] == {"scheme": "SIRET", "value": "27920022400012"}


def test_a_named_buyer_further_down_the_list_is_not_hidden_by_a_siret_only_first(
    client, icp, engine
):
    """§19 — un second acheteur nommé compte, même quand le premier n'a qu'un
    SIREN. Le premier acheteur n'a pas de statut privilégié sur le nom."""
    from signals.domain.values import OrganizationIdentifier, OrganizationRef

    unnamed_siren = "552032534"
    unnamed = OrganizationRef(
        legal_name=unnamed_siren,
        identifiers=(OrganizationIdentifier(scheme="SIREN", value=unnamed_siren),),
        country="FR",
    )
    named = OrganizationRef(
        legal_name="Métropole de Lyon",
        identifiers=(OrganizationIdentifier(scheme="SIREN", value="200046977"),),
        country="FR",
    )
    event, awards = simap_award("33112-02")
    event = event.model_copy(update={"procedure_buyers": (unnamed, named)})
    with engine.begin() as connection:
        signal = materialize(connection, event, awards[0], target_icp_id=icp)

    body = client.get(f"/signals/{signal.signal_key}").json()
    buyer = body["contract"]["buyer"]
    assert buyer["name"] == "Métropole de Lyon"
    assert buyer["identifier"] == {"scheme": "SIREN", "value": "200046977"}


def test_a_postal_code_yields_a_department_and_its_label(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    location = body["contract"]["location"]
    assert location["locality"] is None
    assert location["postal_code"] == "92350"
    assert location["subdivision_code"] == "FR-92"
    assert location["subdivision_label"] == "Hauts-de-Seine"


def test_completeness_does_not_count_a_siret_as_a_buyer_name(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    display = body["factual_display"]
    assert "buyer" in display["missing_fields"]
    assert "location" not in display["missing_fields"], "un département est un lieu"
    assert display["completeness"] == "partial"


def test_the_headline_names_the_department_rather_than_the_country(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    headline = body["factual_display"]["headline"]
    assert "dans le département 92 (Hauts-de-Seine)" in headline
    assert " à FR" not in headline


def test_a_country_alone_is_not_a_location(client, icp, engine):
    from signals.domain.values import Location

    event, awards = simap_award("33112-02")
    award = awards[0].model_copy(update={"place_of_performance": Location(country="FR")})
    with engine.begin() as connection:
        signal = materialize(connection, event, award, target_icp_id=icp)

    display = client.get(f"/signals/{signal.signal_key}").json()["factual_display"]
    assert "location" in display["missing_fields"]
    assert " à FR" not in display["headline"]
