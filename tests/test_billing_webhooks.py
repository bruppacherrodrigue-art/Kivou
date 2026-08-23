"""SPEC-013 §14 à §18 — la seule autorité de paiement, et ses trois pièges.

La signature est vraie, pas simulée
───────────────────────────────────
Ces tests calculent un en-tête `Stripe-Signature` authentique (HMAC-SHA256
sur « horodatage.corps ») et exercent le VRAI code de vérification. Simuler
la vérification reviendrait à ne pas la tester — et c'est la seule chose qui
sépare un événement Stripe d'un message forgé.

Les trois pièges
────────────────
Un événement peut être **rejoué** : la clé primaire l'empêche de l'être.
L'ordre n'est **pas garanti** : l'état est relu chez Stripe, et un événement
plus ancien que celui déjà appliqué est refusé. Et le navigateur n'est
**jamais** une autorité : rien ici ne part d'une redirection.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import (
    TEST_WEBHOOK_SECRET,
    FakeStripe,
    event_payload,
    signature_timestamp,
    stripe_signature,
    subscription_state,
)
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing.schema import billing_customer, billing_subscription, stripe_webhook_event
from signals.persistence.database import create_database_engine, migrate_to_latest

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


@pytest.fixture
def webhook(app) -> TestClient:
    # Aucune session, aucune origine : Stripe n'en envoie pas.
    return TestClient(app)


def deliver(
    client: TestClient,
    *,
    event_id: str,
    event_type: str,
    data_object: dict,
    created: dt.datetime = NOW,
    secret: str = TEST_WEBHOOK_SECRET,
    livemode: bool = False,
    tamper: bool = False,
):
    payload = event_payload(
        event_id=event_id,
        event_type=event_type,
        created=created,
        data_object=data_object,
        livemode=livemode,
    )
    # Deux horloges : `created` date l'événement (métier, figé à `NOW`), tandis
    # que l'en-tête est signé à l'heure que `construct_event` consulte vraiment.
    # Les confondre faisait expirer la suite au 25 août 2026 (#42).
    signature = stripe_signature(payload, secret=secret, timestamp=signature_timestamp())
    body = payload + (b" " if tamper else b"")
    return client.post(
        "/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )


def subscription_object(*, account: str, status: str = "active") -> dict:
    return {
        "id": SUBSCRIPTION_ID,
        "customer": CUSTOMER_ID,
        "status": status,
        "metadata": {"kivou_account_id": account},
    }


def put(stripe: FakeStripe, account: str, **overrides):
    return stripe.put_subscription(
        subscription_state(
            subscription_id=SUBSCRIPTION_ID,
            customer_id=CUSTOMER_ID,
            account_id=account,
            **overrides,
        )
    )


def stored(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(billing_subscription)).all()


# ─── §15 — la signature est la seule autorité ─────────────────────────────────


def test_a_valid_signature_is_accepted(webhook, stripe, account_id):
    put(stripe, account_id)
    response = deliver(
        webhook,
        event_id="evt_1",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
    )
    assert response.status_code == 200
    assert response.json()["result"] == "applied"


def test_a_missing_signature_is_rejected(webhook, stripe, account_id):
    response = webhook.post("/webhooks/stripe", content=b"{}")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_webhook_signature"


def test_a_signature_computed_with_another_secret_is_rejected(webhook, stripe, account_id):
    put(stripe, account_id)
    response = deliver(
        webhook,
        event_id="evt_2",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
        secret="whsec_" + "9" * 32,
    )
    assert response.status_code == 400
    assert stored(webhook.app.state.engine) == []


def test_a_tampered_body_invalidates_an_authentic_signature(webhook, stripe, account_id, engine):
    """Le corps BRUT est signé : un octet de plus et la signature ne vaut plus."""
    put(stripe, account_id)
    response = deliver(
        webhook,
        event_id="evt_3",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
        tamper=True,
    )
    assert response.status_code == 400
    assert stored(engine) == []


def test_the_webhook_endpoint_needs_no_session_and_no_origin(webhook, stripe, account_id):
    """Stripe n'a ni cookie ni origine : lui imposer la règle CSRF le bloquerait."""
    assert "Origin" not in webhook.headers
    response = deliver(
        webhook,
        event_id="evt_4",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
    )
    assert response.status_code == 200


def test_the_webhook_secret_never_appears_in_a_response(webhook, stripe, account_id):
    put(stripe, account_id)
    body = deliver(
        webhook,
        event_id="evt_5",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
    ).text
    assert TEST_WEBHOOK_SECRET not in body
    assert "whsec" not in body


# ─── §18 — idempotence ────────────────────────────────────────────────────────


def test_the_same_event_delivered_twice_is_a_no_operation_the_second_time(
    webhook, stripe, account_id, engine
):
    put(stripe, account_id)
    first = deliver(
        webhook,
        event_id="evt_same",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
    )
    second = deliver(
        webhook,
        event_id="evt_same",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
    )
    assert first.json()["result"] == "applied"
    assert second.json()["result"] == "duplicate"
    assert len(stored(engine)) == 1
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(stripe_webhook_event)
            ).scalar()
            == 1
        )


def test_a_retried_checkout_completion_creates_no_second_subscription(
    webhook, stripe, account_id, engine
):
    put(stripe, account_id)
    completion = {
        "id": "cs_test_0001",
        "subscription": SUBSCRIPTION_ID,
        "client_reference_id": account_id,
    }
    for event_id in ("evt_co_1", "evt_co_1", "evt_co_1"):
        deliver(
            webhook,
            event_id=event_id,
            event_type="checkout.session.completed",
            data_object=completion,
        )
    assert len(stored(engine)) == 1


def test_a_retried_invoice_paid_does_not_transition_twice(webhook, stripe, account_id, engine):
    put(stripe, account_id)
    invoice = {"id": "in_test_0001", "subscription": SUBSCRIPTION_ID}
    first = deliver(webhook, event_id="evt_inv", event_type="invoice.paid", data_object=invoice)
    second = deliver(webhook, event_id="evt_inv", event_type="invoice.paid", data_object=invoice)
    assert first.json()["result"] == "applied"
    assert second.json()["result"] == "duplicate"
    assert len(stored(engine)) == 1


def test_two_distinct_events_about_the_same_subscription_are_both_recorded(
    webhook, stripe, account_id, engine
):
    put(stripe, account_id)
    deliver(
        webhook,
        event_id="evt_a",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
    )
    deliver(
        webhook,
        event_id="evt_b",
        event_type="customer.subscription.updated",
        data_object=subscription_object(account=account_id),
        created=NOW + dt.timedelta(minutes=1),
    )
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(stripe_webhook_event)
            ).scalar()
            == 2
        )
    assert len(stored(engine)) == 1


# ─── §17 — l'ordre ne doit rien changer ───────────────────────────────────────


def test_subscription_updated_arriving_before_checkout_completed_still_ends_correct(
    webhook, stripe, account_id, engine
):
    put(stripe, account_id, plan="pro", status="active")
    deliver(
        webhook,
        event_id="evt_upd",
        event_type="customer.subscription.updated",
        data_object=subscription_object(account=account_id),
        created=NOW + dt.timedelta(minutes=2),
    )
    deliver(
        webhook,
        event_id="evt_chk",
        event_type="checkout.session.completed",
        data_object={
            "id": "cs_1",
            "subscription": SUBSCRIPTION_ID,
            "client_reference_id": account_id,
        },
        created=NOW,
    )
    rows = stored(engine)
    assert len(rows) == 1
    assert rows[0].plan_code == "pro"
    assert rows[0].status == "active"


def test_invoice_paid_arriving_before_the_subscription_event_still_ends_correct(
    webhook, stripe, account_id, engine
):
    put(stripe, account_id, plan="scale", currency="eur", status="active")
    deliver(
        webhook,
        event_id="evt_i",
        event_type="invoice.paid",
        data_object={"id": "in_1", "subscription": SUBSCRIPTION_ID},
        created=NOW + dt.timedelta(minutes=5),
    )
    deliver(
        webhook,
        event_id="evt_s",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
        created=NOW,
    )
    rows = stored(engine)
    assert rows[0].plan_code == "scale"
    assert rows[0].currency == "eur"


def test_an_old_duplicate_event_never_rolls_the_state_backward(webhook, stripe, account_id, engine):
    """Le cas qui compte : la résiliation est connue, un vieil événement arrive."""
    put(stripe, account_id, status="active")
    deliver(
        webhook,
        event_id="evt_old",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
        created=NOW,
    )
    put(stripe, account_id, status="canceled")
    deliver(
        webhook,
        event_id="evt_new",
        event_type="customer.subscription.deleted",
        data_object=subscription_object(account=account_id, status="canceled"),
        created=NOW + dt.timedelta(hours=1),
    )
    assert stored(engine)[0].status == "canceled"

    # Stripe relivre un événement ANTÉRIEUR, décrivant un abonnement encore actif.
    put(stripe, account_id, status="active")
    late = deliver(
        webhook,
        event_id="evt_late",
        event_type="customer.subscription.updated",
        data_object=subscription_object(account=account_id),
        created=NOW + dt.timedelta(minutes=1),
    )
    assert late.json()["result"] == "ignored"
    assert stored(engine)[0].status == "canceled", "un passé ne réécrit pas le présent"


def test_the_state_always_comes_from_the_current_stripe_object(webhook, stripe, account_id, engine):
    """La charge de l'événement dit `active` ; l'objet courant dit `past_due`."""
    put(stripe, account_id, status="past_due")
    deliver(
        webhook,
        event_id="evt_current",
        event_type="customer.subscription.updated",
        data_object=subscription_object(account=account_id, status="active"),
    )
    assert stored(engine)[0].status == "past_due"


# ─── §16 — le jeu d'événements ────────────────────────────────────────────────


def test_an_unhandled_event_type_is_recorded_without_effect(webhook, stripe, account_id, engine):
    response = deliver(
        webhook,
        event_id="evt_other",
        event_type="customer.created",
        data_object={"id": CUSTOMER_ID},
    )
    assert response.json()["result"] == "unhandled"
    assert stored(engine) == []


def test_a_payment_action_required_event_never_invents_paid_access(
    webhook, stripe, account_id, engine
):
    put(stripe, account_id)
    response = deliver(
        webhook,
        event_id="evt_action",
        event_type="invoice.payment_action_required",
        data_object={"id": "in_2", "subscription": SUBSCRIPTION_ID},
    )
    assert response.json()["result"] == "ignored"
    assert stored(engine) == []


def test_a_payment_failure_synchronizes_the_failing_state(webhook, stripe, account_id, engine):
    put(stripe, account_id, status="past_due")
    deliver(
        webhook,
        event_id="evt_fail",
        event_type="invoice.payment_failed",
        data_object={"id": "in_3", "subscription": SUBSCRIPTION_ID},
    )
    assert stored(engine)[0].status == "past_due"


# ─── §30 — le mode Stripe ─────────────────────────────────────────────────────


def test_a_live_event_is_rejected_by_an_application_configured_for_test(
    webhook, stripe, account_id, engine
):
    put(stripe, account_id)
    response = deliver(
        webhook,
        event_id="evt_live",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
        livemode=True,
    )
    assert response.status_code == 400
    assert stored(engine) == []


# ─── §9 — un prix inconnu n'accorde rien ──────────────────────────────────────


def test_an_unknown_stripe_price_grants_no_paid_plan(webhook, stripe, account_id, engine):
    put(stripe, account_id, lookup_key="kivou_mystery_monthly_chf")
    deliver(
        webhook,
        event_id="evt_unknown",
        event_type="customer.subscription.created",
        data_object=subscription_object(account=account_id),
    )
    row = stored(engine)[0]
    assert row.status == "active"
    assert row.plan_code is None, "aucun repli sur Pro"


def test_a_subscription_without_any_reconcilable_account_is_ignored(webhook, stripe, engine):
    stripe.put_subscription(
        subscription_state(subscription_id="sub_orphan", customer_id="cus_unknown", account_id=None)
    )
    response = deliver(
        webhook,
        event_id="evt_orphan",
        event_type="customer.subscription.created",
        data_object={"id": "sub_orphan", "customer": "cus_unknown", "metadata": {}},
    )
    assert response.json()["result"] == "ignored"
    assert stored(engine) == []
