"""P0-03A §2 — quelle action de facturation est SÛRE, décidée par le serveur.

Pourquoi ce champ existe
────────────────────────
`plan_code` décrit les droits ACCORDÉS. Il ne décrit pas l'existence d'un
abonnement. Un compte `past_due` porte un abonnement facturé et n'a aucun
droit : `plan_code` vaut alors `discovery`, exactement comme un compte qui n'a
jamais rien payé. Les deux situations demandent pourtant des actions opposées
— l'un doit récupérer son paiement, l'autre doit en ouvrir un.

Sans `billing_action`, le frontend n'a qu'un moyen de les distinguer : recopier
`TERMINAL_STATUSES` et la règle « défaut fermé » de `is_open_subscription()`.
Recopier une règle d'autorisation dans un navigateur, c'est se garantir qu'elle
divergera le jour où Stripe ajoutera un statut. La décision reste donc ici.

Ce que ce fichier vérifie est une MATRICE, pas une implémentation : chaque
statut Stripe connu, plus les deux formes d'inconnu — un statut que Stripe
inventerait, et un prix hors catalogue.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import FakeStripe, subscribe
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing import service
from signals.billing.schema import PAYING_STATUSES, billing_customer
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def gateway() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def app(engine, gateway: FakeStripe):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            stripe_webhook_secret="whsec_test",
        ),
        now_override=lambda: NOW,
        stripe_gateway=gateway,
    )


@pytest.fixture
def alice(app) -> TestClient:
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
    return client


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def with_customer(engine, gateway: FakeStripe, client: TestClient) -> str:
    """Donne au compte le client Stripe que le portail exige.

    Passe par le VRAI chemin : c'est `ensure_stripe_customer` qui écrit
    `billing_customer`, et c'est cette table que `open_portal` relit.
    """
    with engine.begin() as connection:
        return service.ensure_stripe_customer(
            connection,
            gateway,
            account_id=account_of(client),
            expect_livemode=False,
            now=NOW,
        )


def pay(engine, client: TestClient, **overrides) -> None:
    with engine.begin() as connection:
        subscribe(connection, account_id=account_of(client), now=NOW, **overrides)


def action(client: TestClient) -> str:
    response = client.get("/billing/status")
    assert response.status_code == 200, response.text
    return response.json()["billing_action"]


# ─── la matrice ───────────────────────────────────────────────────────────────


def test_an_account_without_any_subscription_chooses_a_plan(alice):
    assert action(alice) == "choose_plan"


def test_an_active_subscription_is_managed_in_the_portal(alice, engine, gateway):
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="active")
    assert action(alice) == "manage_subscription"


def test_a_subscription_cancelling_at_period_end_is_still_managed(alice, engine, gateway):
    """L'accès court jusqu'à la fin payée : il reste quelque chose à gérer."""
    with_customer(engine, gateway, alice)
    pay(
        engine,
        alice,
        plan="pro",
        status="active",
        cancel_at_period_end=True,
        period_end=NOW + dt.timedelta(days=12),
    )
    assert action(alice) == "manage_subscription"


@pytest.mark.parametrize("stripe_status", ["past_due", "unpaid"])
def test_an_unpaid_subscription_recovers_rather_than_buys_again(
    alice, engine, gateway, stripe_status: str
):
    """Le compte porte ENCORE un abonnement : un second Checkout le facturerait
    deux fois. L'action sûre est la récupération, pas l'achat."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status=stripe_status)
    assert action(alice) == "recover_payment"


def test_an_incomplete_subscription_asks_for_support(alice, engine, gateway):
    """Le premier paiement n'a jamais abouti. Le portail ne garantit pas de le
    finaliser, et Kivou n'a aucun contrat de reprise de cette session : mieux
    vaut ne rien promettre que promettre une réparation qu'on ne sait pas faire."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="incomplete")
    assert action(alice) == "contact_support"


def test_an_expired_incomplete_subscription_frees_the_place(alice, engine, gateway):
    """`incomplete_expired` est TERMINAL : plus rien n'est facturé, donc un
    nouveau paiement est légitime."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="incomplete_expired")
    assert action(alice) == "choose_plan"


def test_a_canceled_subscription_frees_the_place(alice, engine, gateway):
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="canceled", canceled_at=NOW)
    assert action(alice) == "choose_plan"


def test_a_paused_subscription_asks_for_support(alice, engine, gateway):
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="paused")
    assert action(alice) == "contact_support"


def test_a_trialing_subscription_asks_for_support(alice, engine, gateway):
    """Le MVP n'offre aucun essai : un `trialing` est une anomalie de
    configuration, pas un parcours client."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="trialing")
    assert action(alice) == "contact_support"


def test_a_status_stripe_invented_later_never_offers_a_second_payment(alice, engine, gateway):
    """Défaut fermé. Un statut inconnu n'est pas terminal, donc l'abonnement
    peut encore être facturé : proposer un achat serait la faute qui coûte de
    l'argent réel au client."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="something_stripe_invented_later")
    assert action(alice) == "contact_support"


def test_an_open_subscription_on_an_unknown_price_asks_for_support(alice, engine, gateway):
    """Le prix ne correspond à aucun plan Kivou : personne ne sait ce que ce
    compte paie. Ni achat, ni gestion — une revue humaine."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", lookup_key="kivou_unknown_monthly_chf", status="active")
    assert action(alice) == "contact_support"


def test_a_terminal_subscription_on_an_unknown_price_still_frees_the_place(
    alice, engine, gateway
):
    """L'ordre compte : la terminaison prime sur le prix inconnu, parce qu'un
    abonnement résilié ne facture plus rien."""
    with_customer(engine, gateway, alice)
    pay(
        engine,
        alice,
        plan="pro",
        lookup_key="kivou_unknown_monthly_chf",
        status="canceled",
        canceled_at=NOW,
    )
    assert action(alice) == "choose_plan"


# ─── incohérence de données ───────────────────────────────────────────────────


@pytest.mark.parametrize("stripe_status", ["active", "past_due", "unpaid"])
def test_an_action_needing_the_portal_falls_back_when_the_customer_is_missing(
    alice, engine, stripe_status: str
):
    """Un abonnement sans `billing_customer` — ce que produit un abonnement créé
    hors du parcours Kivou. `POST /billing/portal` répondrait 409 : annoncer
    « gérez votre abonnement » enverrait le client sur une porte fermée."""
    pay(engine, alice, plan="pro", status=stripe_status)
    with engine.connect() as connection:
        assert service.stripe_customer_id(connection, account_id=account_of(alice)) is None
    assert action(alice) == "contact_support"


def test_a_missing_customer_does_not_block_a_first_purchase(alice, engine):
    """Sans abonnement, aucun portail n'est nécessaire : l'absence de client
    Stripe est l'état NORMAL d'un compte qui n'a jamais payé."""
    assert action(alice) == "choose_plan"


def test_a_terminal_subscription_without_customer_still_frees_the_place(alice, engine):
    pay(engine, alice, plan="pro", status="canceled", canceled_at=NOW)
    assert action(alice) == "choose_plan"


# ─── ce que ce champ ne change pas ────────────────────────────────────────────


def test_the_paying_statuses_are_not_widened(alice):
    """Le champ décrit une ACTION, jamais un droit. Élargir `PAYING_STATUSES`
    ouvrirait l'accès payant à un abonnement impayé."""
    assert PAYING_STATUSES == ("active",)


@pytest.mark.parametrize(
    "stripe_status",
    ["past_due", "unpaid", "incomplete", "incomplete_expired", "canceled", "paused", "trialing"],
)
def test_no_action_grants_any_entitlement(alice, engine, gateway, stripe_status: str):
    """Quelle que soit l'action proposée, les droits restent ceux de Discovery."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="scale", status=stripe_status)
    body = alice.get("/billing/status").json()
    assert body["plan_code"] == "discovery"
    assert body["entitlements"]["max_active_icps"] == 1


def test_the_action_never_leaks_a_stripe_identifier(alice, engine, gateway):
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="past_due")
    body = alice.get("/billing/status").json()
    assert body["billing_action"] == "recover_payment"
    for forbidden in ("cus_", "sub_", "price_", "sk_test", "whsec"):
        assert forbidden not in str(body)


def test_the_action_is_one_of_the_four_declared_values(alice, engine, gateway):
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="active")
    assert action(alice) in service.BILLING_ACTIONS


# ─── l'abonnement en conflit ──────────────────────────────────────────────────


def test_a_conflicting_second_subscription_never_offers_a_second_payment(
    alice, engine, gateway
):
    """R1 §5 — un second abonnement arrive, Kivou refuse de trancher et CONSERVE
    le premier. L'action reste donc celle du premier abonnement, qui est ouvert :
    le compte ne se voit jamais proposer un troisième paiement.

    Le conflit lui-même n'est pas exposé — voir BILLING ATTENTION GAP.
    """
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="active")
    with engine.begin() as connection, pytest.raises(service.BillingSubscriptionConflict):
        subscribe(
            connection,
            account_id=account_of(alice),
            plan="scale",
            status="active",
            subscription_id="sub_test_9999",
            now=NOW,
        )
    assert action(alice) == "manage_subscription"


def test_the_status_never_claims_a_missing_billing_customer_row(alice, engine, gateway):
    """Garde-fou de cohérence : si `manage_subscription` est rendu, la ligne que
    `open_portal` relira existe réellement."""
    with_customer(engine, gateway, alice)
    pay(engine, alice, plan="pro", status="active")
    assert action(alice) == "manage_subscription"
    with engine.connect() as connection:
        stored = connection.execute(
            sa.select(billing_customer.c.stripe_customer_id).where(
                billing_customer.c.account_id == account_of(alice)
            )
        ).scalar_one_or_none()
    assert stored is not None
