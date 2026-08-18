"""SPEC-012 §19, §28 — un identifiant stable n'est pas une identité client.

DECP 2022 publie le SIRET du titulaire sans sa dénomination sociale : c'est le
constat mesuré de SPEC-009E, et la raison pour laquelle 379 des 428 événements
français hebdomadaires ne sont pas exploitables tels quels. Un feed qui
afficherait « Entreprise : 44284979000013 » aurait l'air complet et ne servirait
à rien.

L'autre moitié porte sur l'unicité. Un même marché vu par deux portails reste UN
signal : la déduplication est structurelle depuis SPEC-010, et l'ajout d'une
seconde représentation ne doit pas dédoubler la carte.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    LINKED_BOAMP,
    LINKED_DECP,
    ORIGIN,
    PASSWORD,
    RETRIEVED_AT,
    SIMAP_RICH,
    materialize,
    materialize_simap,
)

from signals.api import ApiConfig, create_app
from signals.feed.query import is_customer_ready
from signals.persistence.database import create_database_engine, migrate_to_latest


class Clock:
    def __init__(self, day: dt.date = dt.date(2026, 8, 25)) -> None:
        self.now = dt.datetime.combine(day, dt.time(9, 0), tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


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
        now_override=Clock(),
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": "alice@negoce-romand.ch",
            "password": PASSWORD,
            "company_name": "Negoce Romand SA",
            "locale": "fr",
        },
    )
    subscribe_to_scale(engine, client)
    return client


def subscribe_to_scale(engine, client) -> None:
    """Abonne le compte à Scale — historique complet, filtres avancés.

    SPEC-013 : ces tests portent sur la FRAÎCHEUR et l'IDENTITÉ d'un signal
    débloqué. Depuis l'arrivée de la facturation, un compte Discovery ne voit
    que trois signaux offerts et verrouille le reste ; l'abonnement garde donc
    ces assertions sur leur objet. Le mur payant a ses propres tests.
    """
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id=f"sub_test_{account_id[-8:]}",
            now=RETRIEVED_AT,
        )


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps", json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]


def feed(client: TestClient, **params) -> dict:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    return client.get(f"/signals?{query}" if query else "/signals").json()


# ─── §28.1, §28.2, §28.3 — un nom, ou rien ────────────────────────────────────


def test_a_named_company_is_eligible_for_the_feed(client, icp, engine):
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)

    body = feed(client, freshness="all")
    assert [item["signal_id"] for item in body["items"]] == [signal.signal_key]
    assert body["items"][0]["company"]["name"] == "Egli Gartenbau AG Sursee"
    assert body["excluded"]["without_display_name"] == 0


def test_a_winner_known_only_by_its_identifier_stays_out_of_the_feed(client, icp, engine):
    """Le cas DECP 2022 : un SIRET, pas de dénomination sociale."""
    from feed_helpers import simap_award

    event, awards = simap_award(SIMAP_RICH)
    anonymous = _strip_legal_names(awards[0])
    with engine.begin() as connection:
        materialize(connection, event, anonymous, target_icp_id=icp)

    body = feed(client, freshness="all")
    assert body["items"] == []
    assert body["excluded"]["without_display_name"] == 1


def test_no_company_name_is_ever_fabricated_from_an_identifier(client, icp, engine):
    from feed_helpers import simap_award

    event, awards = simap_award(SIMAP_RICH)
    anonymous = _strip_legal_names(awards[0])
    with engine.begin() as connection:
        signal = materialize(connection, event, anonymous, target_icp_id=icp)

    body = client.get(f"/signals/{signal.signal_key}").json()
    assert body["company"]["name"] is None
    assert body["customer_ready"] is False
    identifier = body["company"]["identifier"]
    assert identifier is None or identifier["value"] != body["company"]["name"]


def test_an_identifier_copied_into_the_name_field_is_not_a_display_name(engine):
    """Un nom qui n'est que l'identifiant recopié ne rend pas le signal montrable."""
    from signals.persistence.repository import StoredSignal

    for name, identifier, ready in (
        ("Egli Gartenbau AG", "CHE-123", True),
        ("44284979000013", "44284979000013", False),
        ("442 849 790 00013", "44284979000013", False),
        ("   ", None, False),
        (None, "44284979000013", False),
    ):
        stub = _stub_signal(name, identifier)
        assert is_customer_ready(stub) is ready, (name, identifier)
        assert isinstance(stub, StoredSignal)


# ─── §28.4, §28.5 — un marché, un signal ──────────────────────────────────────


def test_a_strongly_linked_opportunity_remains_a_single_customer_signal(client, icp, engine):
    from signals.connectors.boamp import parse_award_notice
    from signals.connectors.decp import parse_contract

    boamp_event, boamp_awards = parse_award_notice(LINKED_BOAMP, retrieved_at=RETRIEVED_AT)
    decp_event, decp_award = parse_contract(LINKED_DECP, retrieved_at=RETRIEVED_AT)
    with engine.begin() as connection:
        first = materialize(connection, boamp_event, boamp_awards[0], target_icp_id=icp)
        second = materialize(
            connection,
            decp_event,
            decp_award,
            target_icp_id=icp,
            linked_to=[boamp_awards[0]],
            link_strength="strong",
        )

    assert first.opportunity_key == second.opportunity_key, "un seul marché derrière"
    items = feed(client, freshness="all")["items"]
    assert len(items) == 1
    assert items[0]["signal_id"] == first.signal_key
    assert items[0]["company"]["name"], "la représentation nommée l'emporte"


def test_adding_a_second_source_representation_does_not_duplicate_the_feed_item(
    client, icp, engine
):
    from signals.connectors.boamp import parse_award_notice
    from signals.connectors.decp import parse_contract

    boamp_event, boamp_awards = parse_award_notice(LINKED_BOAMP, retrieved_at=RETRIEVED_AT)
    with engine.begin() as connection:
        first = materialize(connection, boamp_event, boamp_awards[0], target_icp_id=icp)
    before = len(feed(client, freshness="all")["items"])
    assert before == 1

    decp_event, decp_award = parse_contract(LINKED_DECP, retrieved_at=RETRIEVED_AT)
    with engine.begin() as connection:
        second = materialize(
            connection,
            decp_event,
            decp_award,
            target_icp_id=icp,
            linked_to=[boamp_awards[0]],
            link_strength="strong",
        )

    assert second.signal_key == first.signal_key, "même opportunité, même client"
    assert len(feed(client, freshness="all")["items"]) == before


def test_the_customer_never_learns_which_source_quirk_produced_the_signal(client, icp, engine):
    """§20 — le vécu client tient à l'événement, au fait et à la preuve."""
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)

    body = str(client.get(f"/signals/{signal.signal_key}").json())
    for quirk in ("cdl", "sentinel", "1970-01-01", "2000-01-01", "eforms", "bt-1451"):
        assert quirk not in body.lower(), quirk


def test_the_source_system_is_stated_without_driving_the_interpretation(client, icp, engine):
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)

    body = client.get(f"/signals/{signal.signal_key}").json()
    assert body["source"]["system"] == "simap"
    # L'événement et la phrase viennent du STATUT, jamais du portail.
    assert body["event"]["status"] == "stale_award"
    assert "simap" not in body["event"]["headline"].lower()


# ─── outils ───────────────────────────────────────────────────────────────────


def _strip_legal_names(award):
    """Retire la dénomination sociale des attributaires, en gardant l'identifiant."""
    parties = []
    for party in award.awardee_parties:
        members = [
            member.model_copy(
                update={
                    "organization": member.organization.model_copy(
                        update={"legal_name": member.organization.identifiers[0].value}
                    )
                }
            )
            for member in party.members
        ]
        parties.append(party.model_copy(update={"members": tuple(members)}))
    return award.model_copy(update={"awardee_parties": tuple(parties)})


def _stub_signal(name: str | None, identifier: str | None):
    """Un signal minimal : seule l'identité de l'attributaire est en jeu ici."""
    from signals.persistence.repository import StoredAward, StoredEvent, StoredSignal

    event = StoredEvent(
        event_key="e",
        source_system="simap",
        source_notice_id="n",
        notice_version=None,
        source_country="CH",
        source_url=None,
        published_at=None,
        published_on=None,
        published_precision=None,
        discovered_at=None,
    )
    award = StoredAward(
        award_key="a",
        source_award_id=None,
        lot_identifier=None,
        title=None,
        cpv_main=None,
        amount=None,
        currency=None,
        place_country=None,
        award_date=None,
        contract_signature_date=None,
        contract_notification_date=None,
        contract_start_date=None,
        contract_end_date=None,
        awardee_parties=[],
    )
    return StoredSignal(
        signal_key="s",
        opportunity_key="o",
        materialization_award_key="a",
        target_icp_id="icp",
        revision=1,
        content_fingerprint="f",
        event=event,
        award=award,
        evidence=(),
        materialized_recency_status="stale_award",
        materialized_primary_event=None,
        materialized_award_clock_status="unknown",
        materialized_notification_clock_status="unknown",
        materialized_publication_clock_status="unknown",
        materialized_award_age_days=None,
        materialized_notification_age_days=None,
        materialized_publication_age_days=None,
        materialized_as_of=dt.date(2026, 8, 18),
        recency_policy_version="award-recency-v0.3",
        winner_name=name,
        winner_country="FR",
        winner_identifier_scheme="SIRET",
        winner_identifier_value=identifier,
        inferred_contract_type=None,
        inferred_sector=None,
        inferred_trade_domain=None,
        inferred_contract_summary=None,
        plausible_needs=[],
        icp_match_decision=None,
        icp_match_band=None,
        icp_match_confidence=None,
        icp_match_normalized_score=None,
        icp_matched_needs=[],
        engine_versions={},
        materialized_at=dt.datetime(2026, 8, 18, tzinfo=dt.UTC),
    )
