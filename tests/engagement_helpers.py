"""Fabriques partagées des tests SPEC-014 — comptes, signaux, plans, passerelle d'e-mail."""

from __future__ import annotations

import dataclasses
import datetime as dt
import pathlib

import sqlalchemy as sa
from billing_helpers import FakeStripe, subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    boamp_award,
    materialize,
    simap_award,
)

from signals.alerts.gateway import AlertDeliveryError, AlertMessage, DeliveryResult
from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest

READ_ON = dt.date(2026, 8, 25)
NOW = dt.datetime.combine(READ_ON, dt.time(9, 0), tzinfo=dt.UTC)
#: Antérieure à la parution des avis SIMAP : une décision publiée après sa
#: propre parution est refusée par la politique de fraîcheur.
AWARDED_FROM = dt.date(2026, 8, 13)

#: Les avis réellement exploitables des fixtures, tous porteurs d'un
#: attributaire nommé : douze signaux DISTINCTS.
#:
#: Les lots multiples de `33885-03` et `34794-02` partagent leur identifiant de
#: lot, donc leur `award_key` : trois « lots » n'y produisent qu'un signal. Les
#: réutiliser gonflerait un décompte de test sans rien créer. Les trois lots
#: BOAMP complètent le compte jusqu'à douze.
SIGNAL_SOURCES: tuple[tuple[str, str, int], ...] = (
    ("simap", "28066-04", 0),
    ("simap", "29997-02", 0),
    ("simap", "33112-02", 0),
    ("simap", "33885-03", 0),
    ("simap", "34794-02", 0),
    ("simap", "38147-02", 0),
    ("simap", "38918-02", 0),
    ("simap", "41098-01", 0),
    ("simap", "42486-01", 0),
    ("boamp", "26-80978", 0),
    ("boamp", "26-80978", 1),
    ("boamp", "26-80922", 0),
)

#: L'avis SIMAP riche en besoins plausibles — celui qui rend un digest complet.
RICH_SOURCE_INDEX = 2

#: CLOSEOUT §3 — la base des liens profonds inclut le préfixe `/app` du routeur
#: navigateur : le job d'alerte construit `{base}/signals/{clé}`, et la route
#: cliente est `/app/signals/{clé}`. Une base sans `/app` produirait un lien qui
#: tombe sur la route publique et non sur le signal. Domaine synthétique.
PUBLIC_APP_URL = "https://kivou.test/app"


class Clock:
    def __init__(self, start: dt.datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, delta: dt.timedelta) -> None:
        self.now += delta

    def move_to(self, day: dt.date) -> None:
        self.now = dt.datetime.combine(day, dt.time(9, 0), tzinfo=dt.UTC)


@dataclasses.dataclass
class FakeMailer:
    """Une passerelle d'e-mail déterministe : elle garde ce qu'on lui donne."""

    sent: list[AlertMessage] = dataclasses.field(default_factory=list)
    #: Erreur à lever au prochain envoi, pour éprouver les chemins d'échec.
    fail_with: Exception | None = None

    def send(self, message: AlertMessage) -> DeliveryResult:
        if self.fail_with is not None:
            error, self.fail_with = self.fail_with, None
            raise error
        self.sent.append(message)
        return DeliveryResult(provider_message_id=message.message_id)

    @property
    def last(self) -> AlertMessage:
        return self.sent[-1]


def failure(code: str = "smtp_451", *, retryable: bool = True) -> AlertDeliveryError:
    return AlertDeliveryError(code, retryable=retryable)


def make_engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


def make_app(engine, clock: Clock, **overrides):
    config = ApiConfig(
        cookie_secure=False,
        allowed_origin=ORIGIN,
        session_ttl=dt.timedelta(days=365),
        stripe_mode="test",
        stripe_webhook_secret="whsec_test",
        public_app_url=PUBLIC_APP_URL,
        **overrides,
    )
    return create_app(engine, config, now_override=clock, stripe_gateway=FakeStripe())


def signed_up(app, email: str = "alice@negoce-romand.ch", locale: str = "fr") -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Negoce Romand SA",
            "locale": locale,
        },
    )
    assert response.status_code == 201, response.text
    return client


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def icp_of(client: TestClient, label: str = "Intrants") -> str:
    response = client.post(
        "/target-icps", json={"label": label, "customer_input": COMPLETE_ICP_INPUT}
    )
    assert response.status_code == 201, response.text
    return response.json()["target_icp_id"]


def pay(engine, client: TestClient, *, plan: str = "pro", now: dt.datetime = NOW, **overrides):
    account_id = account_of(client)
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan=plan,
            subscription_id=f"sub_{account_id[-10:]}",
            now=now,
            **overrides,
        )


def seed(engine, icp: str, *, count: int = 1, offset: int = 0) -> list[str]:
    """`count` signaux réels et DISTINCTS, tous `recent_award` à la date de lecture.

    `offset` permet d'en ajouter d'autres plus tard sans retomber sur les mêmes
    couples (avis, lot) — ce qui ne créerait aucun signal nouveau.
    """
    assert offset + count <= len(SIGNAL_SOURCES), "pas assez d'avis distincts en fixtures"
    keys = []
    with engine.begin() as connection:
        for index in range(count):
            keys.append(_materialize_source(connection, index + offset, icp))
    return keys


def seed_rich(engine, icp: str) -> str:
    """Le signal SIMAP porteur de trois besoins plausibles."""
    with engine.begin() as connection:
        return _materialize_source(connection, RICH_SOURCE_INDEX, icp)


def _materialize_source(connection, index: int, icp: str) -> str:
    system, name, lot = SIGNAL_SOURCES[index]
    event, awards = (simap_award if system == "simap" else boamp_award)(name)
    award = awards[lot].model_copy(update={"award_date": AWARDED_FROM - dt.timedelta(days=index)})
    return materialize(connection, event, award, target_icp_id=icp).signal_key


def events(engine, *, event_type: str | None = None) -> list[sa.Row]:
    from signals.engagement.schema import product_event

    query = sa.select(product_event).order_by(product_event.c.occurred_at)
    if event_type is not None:
        query = query.where(product_event.c.event_type == event_type)
    with engine.connect() as connection:
        return connection.execute(query).all()
