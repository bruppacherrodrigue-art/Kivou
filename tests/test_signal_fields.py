"""PR2b tâche 2 — bande de correspondance, groupement, libellé CPV.

Trois faits que la carte annonçait déjà par leurs voisins (`icp_match_band` en
base, `awardee_parties` de l'attribution, `cpv_main` du contrat) mais que le
client ne recevait pas encore sous une forme exploitable. Ce fichier prouve
qu'ils arrivent sur `feed_item` ET `signal_detail`, avec le MÊME vocabulaire
que `companies.listing` pour la bande, et qu'ils ne fuient pas dans le teaser
verrouillé au-delà du seul fait public (`is_consortium`).
"""

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
    SIMAP_RICH,
    materialize,
    materialize_simap,
    simap_award,
)

from signals.api import ApiConfig, create_app
from signals.domain.awards import Awardee, AwardeeParty
from signals.domain.cpv_labels import cpv_label
from signals.feed.policy import FIT_BANDS
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import for_you_sentence, materialized_signal


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


def app_for(engine, locale: str = "fr") -> TestClient:
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=Clock(),
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    assert (
        client.post(
            "/auth/signup",
            json={
                "email": f"alice-{locale}@negoce-romand.ch",
                "password": PASSWORD,
                "company_name": "Negoce Romand SA",
                "locale": locale,
            },
        ).status_code
        == 201
    )
    subscribe_to_scale(engine, client)
    return client


def subscribe_to_scale(engine, client: TestClient) -> None:
    """Abonne le compte à Scale : ces tests portent sur le contenu d'un signal
    débloqué, pas sur le mur payant (qui a son propre test)."""
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id=f"sub_test_{account_id[-8:]}",
            now=Clock()(),
        )


@pytest.fixture
def client(engine) -> TestClient:
    return app_for(engine)


def icp_of(client: TestClient) -> str:
    return client.post(
        "/target-icps", json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]


def detail(client: TestClient, signal_key: str) -> dict:
    response = client.get(f"/signals/{signal_key}")
    assert response.status_code == 200, response.text
    return response.json()


def feed_items(client: TestClient) -> list[dict]:
    response = client.get("/signals?freshness=all&limit=50")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _consortium_award(award):
    """Transforme le premier attributaire en groupement à deux membres.

    Même construction que `_strip_legal_names` dans `tests/test_feed_identity.py` :
    on part d'une attribution réelle et on ne touche qu'au champ étudié.
    """
    party = award.awardee_parties[0]
    lead = party.members[0].model_copy(update={"role": "consortium_lead"})
    partner_org = lead.organization.model_copy(
        update={"legal_name": f"{lead.organization.legal_name} — partenaire"}
    )
    partner = Awardee(organization=partner_org, role="consortium_member")
    group = AwardeeParty(members=(lead, partner), name=party.name)
    return award.model_copy(update={"awardee_parties": (group, *award.awardee_parties[1:])})


# ─── is_consortium ─────────────────────────────────────────────────────────


def test_a_single_bidder_award_is_not_a_consortium(client, engine):
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)

    item = next(i for i in feed_items(client) if i["signal_id"] == signal.signal_key)
    assert item["is_consortium"] is False
    assert detail(client, signal.signal_key)["is_consortium"] is False


def test_a_grouped_award_is_a_consortium(client, engine):
    icp = icp_of(client)
    event, awards = simap_award(SIMAP_RICH)
    grouped = _consortium_award(awards[0])
    with engine.begin() as connection:
        signal = materialize(connection, event, grouped, target_icp_id=icp)

    item = next(i for i in feed_items(client) if i["signal_id"] == signal.signal_key)
    assert item["is_consortium"] is True
    assert detail(client, signal.signal_key)["is_consortium"] is True


# ─── analysis.fit.band ──────────────────────────────────────────────────────


def _set_band(engine, signal_key: str, band: str | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal_key)
            .values(icp_match_band=band)
        )


@pytest.mark.parametrize("band", ["strong", "promising", "weak", "unknown", None])
def test_the_fit_band_reflects_the_stored_icp_match_band(client, engine, band):
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
    _set_band(engine, signal.signal_key, band)

    expected = band if band in ("strong", "promising", "weak") else "unknown"
    assert expected in FIT_BANDS
    body = detail(client, signal.signal_key)
    assert body["analysis"]["fit"]["band"] == expected
    item = next(i for i in feed_items(client) if i["signal_id"] == signal.signal_key)
    assert item["analysis"]["fit"]["band"] == expected


def test_an_unrecognised_stored_band_still_renders_as_unknown(client, engine):
    """Une bande inconnue en base ne doit jamais fuir telle quelle vers le client."""
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
    _set_band(engine, signal.signal_key, "some-future-internal-label")

    body = detail(client, signal.signal_key)
    assert body["analysis"]["fit"]["band"] == "unknown"


def test_model_fit_none_reduces_match_to_weak_in_detail_and_history(client, engine):
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal.signal_key)
            .values(icp_match_band="strong")
        )
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.signal_key == signal.signal_key)
            .values(model_fit="none")
        )

    assert detail(client, signal.signal_key)["analysis"]["fit"]["band"] == "weak"
    item = next(i for i in feed_items(client) if i["signal_id"] == signal.signal_key)
    assert item["analysis"]["fit"]["band"] == "weak"


# ─── contract.cpv_label ─────────────────────────────────────────────────────


def test_the_cpv_label_is_the_official_label_of_the_published_code(client, engine):
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)

    body = detail(client, signal.signal_key)
    assert body["contract"]["cpv"] == "45214200"
    assert body["contract"]["cpv_label"] == cpv_label("45214200", lang="fr")
    assert body["contract"]["cpv_label"] == "Travaux de construction de bâtiments scolaires"


def test_the_cpv_label_is_none_when_no_cpv_is_published(client, engine):
    icp = icp_of(client)
    event, awards = simap_award(SIMAP_RICH)
    uncoded = awards[0].model_copy(update={"cpv_main": None})
    with engine.begin() as connection:
        signal = materialize(connection, event, uncoded, target_icp_id=icp)

    body = detail(client, signal.signal_key)
    assert body["contract"]["cpv"] is None
    assert body["contract"]["cpv_label"] is None
