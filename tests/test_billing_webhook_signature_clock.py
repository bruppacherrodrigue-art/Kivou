"""RTL-02 / #42 — la vérification de signature et l'horloge murale.

Deux horloges, et le piège qui naît à les confondre
───────────────────────────────────────────────────
Les tests de facturation figent une horloge MÉTIER (`now_override`) à une date
d'écriture : c'est ce qui les rend reproductibles. Mais `construct_event` ne
consulte pas cette horloge-là. Il interroge `time.time()` et refuse tout
horodatage de signature antérieur de plus de 300 secondes.

Signer avec la date métier revenait donc à poser une bombe à retardement : tant
que cette date restait dans le futur, Stripe l'acceptait ; le jour où l'horloge
réelle la dépassait, la suite virait au rouge sans qu'une ligne de code ait
bougé. Ces tests verrouillent la séparation des deux horloges, et exercent la
tolérance à ses frontières EXACTES — ce qui n'est possible qu'en figeant
l'horloge que la vérification consulte vraiment.

Rien ici n'assouplit la sécurité : la tolérance de production reste celle du
SDK, et un horodatage hors zone reste refusé.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import (
    STRIPE_SIGNATURE_TOLERANCE_SECONDS,
    TEST_WEBHOOK_SECRET,
    FakeStripe,
    event_payload,
    signature_timestamp,
    stripe_signature,
    subscription_state,
    verifier_clock_at,
)
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing.schema import billing_customer, billing_subscription
from signals.persistence.database import create_database_engine, migrate_to_latest

#: L'horloge MÉTIER, figée. Aucun rapport avec la date réelle d'exécution.
NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)
SUBSCRIPTION_ID = "sub_test_0001"
CUSTOMER_ID = "cus_test_0001"


class Clock:
    def __call__(self) -> dt.datetime:
        return NOW


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def stripe() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def app(engine, stripe: FakeStripe):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            stripe_webhook_secret=TEST_WEBHOOK_SECRET,
        ),
        now_override=Clock(),
        stripe_gateway=stripe,
    )


@pytest.fixture
def account_id(app, engine) -> str:
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
    identifier = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        connection.execute(
            sa.insert(billing_customer).values(
                account_id=identifier,
                stripe_customer_id=CUSTOMER_ID,
                livemode=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return identifier


def subscribed(stripe: FakeStripe, account: str) -> None:
    stripe.put_subscription(
        subscription_state(
            subscription_id=SUBSCRIPTION_ID, customer_id=CUSTOMER_ID, account_id=account
        )
    )


def deliver(
    client: TestClient,
    *,
    account: str,
    event_id: str,
    signed_at: int | None = None,
):
    """Livre un événement métier daté de `NOW`, signé à l'instant demandé."""
    payload = event_payload(
        event_id=event_id,
        event_type="customer.subscription.created",
        created=NOW,
        data_object={
            "id": SUBSCRIPTION_ID,
            "customer": CUSTOMER_ID,
            "status": "active",
            "metadata": {"kivou_account_id": account},
        },
    )
    timestamp = signature_timestamp() if signed_at is None else signed_at
    return client.post(
        "/webhooks/stripe",
        content=payload,
        headers={
            "Stripe-Signature": stripe_signature(
                payload, secret=TEST_WEBHOOK_SECRET, timestamp=timestamp
            ),
            "Content-Type": "application/json",
        },
    )


def stored(engine) -> list:
    with engine.connect() as connection:
        return connection.execute(sa.select(billing_subscription)).all()


# ─── #42 — la date réelle d'exécution ne décide de rien ───────────────────────


@pytest.mark.parametrize(
    "real_date",
    [
        dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 8, 24, 23, 59, tzinfo=dt.UTC),
        dt.datetime(2026, 8, 25, 9, 5, 1, tzinfo=dt.UTC),
        dt.datetime(2030, 6, 1, tzinfo=dt.UTC),
    ],
    ids=["long-before", "the-day-before", "just-past-the-fixed-date", "years-after"],
)
def test_a_valid_delivery_is_accepted_whatever_the_real_date(
    app, stripe, account_id, engine, real_date
):
    """Le cœur de #42 : la suite ne doit pas virer au rouge en passant minuit.

    `2026-08-25 09:05:01` est l'instant précis où l'ancien code cassait : la
    date métier figée venait de sortir de la zone de tolérance.
    """
    subscribed(stripe, account_id)
    with verifier_clock_at(real_date):
        response = deliver(TestClient(app), account=account_id, event_id="evt_clock")

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "applied"
    assert len(stored(engine)) == 1


def test_the_business_clock_stays_fixed_and_dates_the_event(app, stripe, account_id, engine):
    """Découpler les horloges ne doit pas rendre la date métier réelle.

    Sans cette garde, « signer à l'heure réelle » pourrait dériver en « dater
    l'événement à l'heure réelle », et la reproductibilité des tests métier
    disparaîtrait sans bruit.
    """
    subscribed(stripe, account_id)
    with verifier_clock_at(dt.datetime(2030, 6, 1, tzinfo=dt.UTC)):
        assert deliver(TestClient(app), account=account_id, event_id="evt_dates").status_code == 200

    with engine.connect() as connection:
        row = connection.execute(sa.select(billing_subscription)).one()
    assert row.updated_at.replace(tzinfo=dt.UTC) == NOW


# ─── Les frontières EXACTES de la tolérance ───────────────────────────────────


def test_a_signature_at_the_exact_tolerance_edge_is_accepted(app, stripe, account_id, engine):
    """300 s pile : Stripe rejette « antérieur à », pas « égal à »."""
    subscribed(stripe, account_id)
    real_now = dt.datetime(2029, 1, 1, 12, 0, tzinfo=dt.UTC)
    signed_at = int(real_now.timestamp()) - STRIPE_SIGNATURE_TOLERANCE_SECONDS

    with verifier_clock_at(real_now):
        response = deliver(
            TestClient(app), account=account_id, event_id="evt_edge", signed_at=signed_at
        )

    assert response.status_code == 200, response.text
    assert len(stored(engine)) == 1


def test_a_signature_one_second_past_the_tolerance_is_rejected(app, stripe, account_id, engine):
    """301 s : la première seconde hors zone, et rien n'est appliqué."""
    subscribed(stripe, account_id)
    real_now = dt.datetime(2029, 1, 1, 12, 0, tzinfo=dt.UTC)
    signed_at = int(real_now.timestamp()) - STRIPE_SIGNATURE_TOLERANCE_SECONDS - 1

    with verifier_clock_at(real_now):
        response = deliver(
            TestClient(app), account=account_id, event_id="evt_stale", signed_at=signed_at
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_webhook_signature"
    assert stored(engine) == []


def test_a_long_expired_signature_is_rejected(app, stripe, account_id, engine):
    """Le rejet d'un horodatage franchement ancien reste explicitement testé.

    C'est la garantie anti-rejeu que #42 demande de CONSERVER : la corriger
    en l'assouplissant reviendrait à ouvrir la porte qu'elle ferme.
    """
    subscribed(stripe, account_id)
    real_now = dt.datetime(2029, 1, 1, 12, 0, tzinfo=dt.UTC)
    signed_at = int((real_now - dt.timedelta(days=30)).timestamp())

    with verifier_clock_at(real_now):
        response = deliver(
            TestClient(app), account=account_id, event_id="evt_ancient", signed_at=signed_at
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_webhook_signature"
    assert stored(engine) == []


def test_a_signature_from_the_future_is_still_accepted(app, stripe, account_id, engine):
    """Stripe ne borne QUE l'ancienneté. Le documenter évite de croire l'inverse.

    Ce test n'élargit rien : il constate la tolérance réelle du SDK, celle-là
    même qui masquait le défaut de #42 jusqu'au 25 août 2026.
    """
    subscribed(stripe, account_id)
    real_now = dt.datetime(2029, 1, 1, 12, 0, tzinfo=dt.UTC)
    signed_at = int((real_now + dt.timedelta(hours=1)).timestamp())

    with verifier_clock_at(real_now):
        response = deliver(
            TestClient(app), account=account_id, event_id="evt_future", signed_at=signed_at
        )

    assert response.status_code == 200, response.text
    assert len(stored(engine)) == 1
