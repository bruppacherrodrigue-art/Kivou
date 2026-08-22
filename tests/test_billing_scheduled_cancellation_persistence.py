"""P0-03G — l'échéance de résiliation survit au webhook, à la base et à la lecture.

Traduire correctement ne suffit pas. L'échéance arrive dans UN webhook, et tout
ce que le client verra ensuite vient de la base. Si elle n'y est pas écrite, le
bandeau disparaît à la requête suivante — le défaut resterait entier, seulement
déplacé d'un cran.

Ce fichier vérifie donc la chaîne complète, de l'objet Stripe jusqu'au corps de
`GET /billing/status`, et surtout ce qui NE doit pas bouger : une résiliation
programmée ne retire aucun droit. Stripe reste l'autorité sur le moment où
l'accès s'arrête ; Kivou ne calcule jamais cette coupure lui-même.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import (
    BILLING_RETURN_URLS,
    TEST_WEBHOOK_SECRET,
    FakeStripe,
    event_payload,
    stripe_signature,
    subscription_state,
)
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing import service
from signals.billing.schema import billing_subscription
from signals.persistence.database import create_database_engine, migrate_to_latest

#: Franchement dans le futur, et pour une raison de fond : la vérification de
#: signature Stripe rejette un horodatage PLUS ANCIEN que la tolérance (300 s),
#: jamais un horodatage à venir. Un `NOW` proche de l'heure réelle glisse dans
#: le passé au fil de la session et fait échouer le test sans que rien n'ait
#: changé dans le code.
NOW = dt.datetime(2027, 3, 1, 9, 0, tzinfo=dt.UTC)
PERIOD_END = dt.datetime(2027, 4, 1, 9, 0, tzinfo=dt.UTC)
OTHER_DATE = dt.datetime(2027, 6, 15, 12, 0, tzinfo=dt.UTC)


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
            **BILLING_RETURN_URLS,
        ),
        now_override=lambda: NOW,
        stripe_gateway=stripe,
    )


@pytest.fixture
def client(app) -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    assert (
        client.post(
            "/auth/signup",
            json={
                "email": "alice@negoce-romand.ch",
                "password": PASSWORD,
                "company_name": "Negoce Romand SA",
                "locale": "fr",
            },
        ).status_code
        == 201
    )
    return client


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def with_customer(engine, stripe: FakeStripe, client: TestClient) -> str:
    """Le client Stripe que `billing_action` exige pour proposer le portail.

    Passe par le VRAI chemin : `ensure_stripe_customer` écrit `billing_customer`,
    et c'est cette table que la décision relit.
    """
    with engine.begin() as connection:
        return service.ensure_stripe_customer(
            connection, stripe, account_id=account_of(client), expect_livemode=False, now=NOW
        )


def sync(engine, state, *, account_id: str, event_created_at: dt.datetime | None = None):
    with engine.begin() as connection:
        return service.synchronize_subscription(
            connection,
            state,
            account_id=account_id,
            event_created_at=event_created_at or NOW,
            expect_livemode=False,
            now=NOW,
        )


def row_of(engine, account_id: str):
    with engine.connect() as connection:
        return connection.execute(
            sa.select(billing_subscription).where(billing_subscription.c.account_id == account_id)
        ).first()


def paid_state(**overrides):
    base = {
        "account_id": None,
        "period_start": NOW,
        "period_end": PERIOD_END,
    }
    base.update(overrides)
    return subscription_state(**base)


# ─── 1. la colonne existe et se remplit ──────────────────────────────────────


def test_la_migration_ajoute_la_colonne_sans_rien_detruire(engine):
    columns = {c["name"] for c in sa.inspect(engine).get_columns("billing_subscription")}

    assert "scheduled_cancellation_at" in columns
    # Les colonnes historiques survivent : la migration est purement additive.
    for historique in (
        "cancel_at_period_end",
        "canceled_at",
        "current_period_end",
        "status",
        "plan_code",
    ):
        assert historique in columns


def test_la_creation_ecrit_l_echeance(engine, client):
    account_id = account_of(client)

    sync(engine, paid_state(scheduled_cancellation_at=PERIOD_END), account_id=account_id)

    assert row_of(engine, account_id).scheduled_cancellation_at is not None


def test_la_mise_a_jour_ecrit_l_echeance_apparue_plus_tard(engine, client):
    """Le cas réel : on s'abonne, puis on résilie. Deux webhooks, un compte."""
    account_id = account_of(client)
    sync(engine, paid_state(), account_id=account_id)
    assert row_of(engine, account_id).scheduled_cancellation_at is None

    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_id,
        event_created_at=NOW + dt.timedelta(minutes=1),
    )

    with engine.connect() as connection:
        stored = service.current_subscription(connection, account_id=account_id)
    assert stored.scheduled_cancellation_at == PERIOD_END


def test_une_resiliation_annulee_efface_l_echeance(engine, client):
    """« Don't cancel subscription » existe dans le portail. Le champ doit suivre."""
    account_id = account_of(client)
    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_id,
    )

    sync(
        engine,
        paid_state(),
        account_id=account_id,
        event_created_at=NOW + dt.timedelta(minutes=2),
    )

    with engine.connect() as connection:
        stored = service.current_subscription(connection, account_id=account_id)
    assert stored.scheduled_cancellation_at is None
    assert stored.cancel_at_period_end is False


def test_un_evenement_plus_ancien_ne_ressuscite_pas_une_echeance_perimee(engine, client):
    """§17 — l'ordre de livraison n'est pas garanti, et un retardataire ne gagne pas."""
    account_id = account_of(client)
    sync(
        engine,
        paid_state(),
        account_id=account_id,
        event_created_at=NOW + dt.timedelta(minutes=5),
    )

    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_id,
        event_created_at=NOW,
    )

    with engine.connect() as connection:
        stored = service.current_subscription(connection, account_id=account_id)
    assert stored.scheduled_cancellation_at is None


# ─── 2. l'état de facturation et l'API ───────────────────────────────────────


def test_billing_state_porte_l_echeance(engine, client):
    account_id = account_of(client)
    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_id,
    )

    with engine.connect() as connection:
        state = service.billing_state(connection, account_id=account_id)

    assert state.scheduled_cancellation_at == PERIOD_END
    assert state.cancel_at_period_end is True


def test_l_api_rend_l_echeance_en_iso(engine, client):
    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_of(client),
    )

    body = client.get("/billing/status").json()

    assert body["scheduled_cancellation_at"] == PERIOD_END.isoformat()
    assert body["cancel_at_period_end"] is True


def test_l_api_rend_null_sans_resiliation(engine, client):
    sync(engine, paid_state(), account_id=account_of(client))

    body = client.get("/billing/status").json()

    assert body["scheduled_cancellation_at"] is None
    assert body["cancel_at_period_end"] is False


def test_un_compte_sans_abonnement_n_a_aucune_echeance(client):
    body = client.get("/billing/status").json()

    assert body["scheduled_cancellation_at"] is None
    assert body["plan_code"] == "discovery"


def test_une_date_distincte_n_est_pas_annoncee_comme_fin_de_periode(engine, client):
    """Le client doit lire la VRAIE date, pas « fin de période »."""
    sync(
        engine,
        paid_state(scheduled_cancellation_at=OTHER_DATE, cancel_at_period_end=False),
        account_id=account_of(client),
    )

    body = client.get("/billing/status").json()

    assert body["scheduled_cancellation_at"] == OTHER_DATE.isoformat()
    assert body["cancel_at_period_end"] is False
    assert body["current_period_end"] == PERIOD_END.isoformat()


# ─── 3. ce qui NE doit pas changer ───────────────────────────────────────────


def test_une_resiliation_programmee_ne_retire_aucun_droit(engine, client, stripe: FakeStripe):
    """L'accès reste PAYANT jusqu'à ce que Stripe change réellement le statut.

    Kivou ne calcule jamais localement la date de coupure des droits : il lit
    `status`. Une échéance annoncée n'est pas une échéance atteinte.
    """
    with_customer(engine, stripe, client)
    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_of(client),
    )

    body = client.get("/billing/status").json()

    assert body["plan_code"] == "pro"
    assert body["subscription_status"] == "active"
    assert body["billing_action"] == "manage_subscription"
    assert body["entitlements"]["history_days"] == 365


def test_l_echeance_ne_change_aucun_droit(engine, client):
    """Les droits d'un abonnement résilié en fin de période sont ceux de son plan."""
    account_id = account_of(client)
    sync(engine, paid_state(), account_id=account_id)
    avant = client.get("/billing/status").json()["entitlements"]

    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_id,
        event_created_at=NOW + dt.timedelta(minutes=1),
    )
    apres = client.get("/billing/status").json()["entitlements"]

    assert avant == apres


def test_billing_action_reste_manage_subscription(engine, client, stripe: FakeStripe):
    """§5 — l'action sûre ne change pas : le portail reste le bon endroit."""
    with_customer(engine, stripe, client)
    sync(
        engine,
        paid_state(scheduled_cancellation_at=PERIOD_END, cancel_at_period_end=True),
        account_id=account_of(client),
    )

    assert client.get("/billing/status").json()["billing_action"] == "manage_subscription"


# ─── 4. le chemin réel : par le webhook ──────────────────────────────────────


def test_le_webhook_de_resiliation_rend_l_echeance_visible(engine, client, stripe: FakeStripe):
    """Le parcours EXACT observé sur staging, de bout en bout.

    Un `customer.subscription.updated` arrive après la demande de résiliation ;
    l'objet relu chez Stripe porte l'échéance. C'est ce webhook qui, jusqu'ici,
    était appliqué sans rien rendre visible.
    """
    account_id = account_of(client)
    sync(engine, paid_state(), account_id=account_id)
    assert client.get("/billing/status").json()["scheduled_cancellation_at"] is None

    stripe.put_subscription(
        paid_state(
            account_id=account_id,
            scheduled_cancellation_at=PERIOD_END,
            cancel_at_period_end=True,
            canceled_at=NOW,
        )
    )
    created = NOW + dt.timedelta(minutes=1)
    payload = event_payload(
        event_id="evt_p0_03g_1",
        event_type="customer.subscription.updated",
        created=created,
        data_object={"id": "sub_test_0001", "metadata": {"kivou_account_id": account_id}},
    )
    response = client.post(
        "/webhooks/stripe",
        content=payload,
        headers={
            "Stripe-Signature": stripe_signature(
                payload, secret=TEST_WEBHOOK_SECRET, timestamp=int(created.timestamp())
            ),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200, response.text
    body = client.get("/billing/status").json()
    assert body["scheduled_cancellation_at"] == PERIOD_END.isoformat()
    assert body["cancel_at_period_end"] is True
    assert body["plan_code"] == "pro"
