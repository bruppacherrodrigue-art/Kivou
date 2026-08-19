"""Ce que la passerelle Stripe ENVOIE réellement — SPEC-016.

Pourquoi ce module existe
─────────────────────────
Toute la suite double la passerelle : `FakeGateway` rend des objets propres et
n'a jamais parlé à Stripe. C'est le bon choix — une suite qui appelle un
fournisseur externe n'est ni hors ligne ni déterministe. Mais cela laissait un
angle mort exact : **personne ne vérifiait la forme des paramètres envoyés**.

Le défaut trouvé en TEST réel :

    Tax ID collection requires updating business name on the customer.
    Please set `customer_update[name]` to `auto`.

La session était refusée par Stripe. Aucun paiement n'aurait jamais abouti, ni
en staging ni en production, et rien dans la suite ne l'annonçait.

Ces tests n'appellent pas Stripe non plus. Ils substituent le CLIENT du SDK et
inspectent le dictionnaire de paramètres — ce qui teste précisément la couche
que le double masquait.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from signals.billing.gateway import StripeApiGateway

EXPIRES = dt.datetime(2026, 8, 19, 12, 0, tzinfo=dt.UTC)


class _Recorder:
    """Enregistre l'appel et rend un objet minimal ressemblant à Stripe."""

    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self.options: dict[str, Any] = {}

    def create(self, params: dict[str, Any], options: dict[str, Any] | None = None) -> Any:
        self.params = params
        self.options = options or {}
        return type("Session", (), {"id": "cs_test_1", "url": "https://checkout.test/x", "livemode": False})()


class _Sessions:
    def __init__(self, recorder: _Recorder) -> None:
        self.sessions = recorder


class _Client:
    def __init__(self, recorder: _Recorder) -> None:
        self.checkout = _Sessions(recorder)


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def gateway(recorder: _Recorder) -> StripeApiGateway:
    gateway = StripeApiGateway.__new__(StripeApiGateway)
    gateway._client = _Client(recorder)  # noqa: SLF001
    return gateway


def _create(gateway: StripeApiGateway, **overrides: Any):
    arguments: dict[str, Any] = {
        "customer_id": "cus_test_1",
        "price_id": "price_test_1",
        "account_id": "acc_test_1",
        "success_url": "https://staging.kivou.eu/checkout/success",
        "cancel_url": "https://staging.kivou.eu/checkout/cancel",
        "automatic_tax": False,
        "coupon_id": None,
        "expires_at": EXPIRES,
        "idempotency_key": "idem-1",
    }
    arguments.update(overrides)
    return gateway.create_checkout_session(**arguments)


def test_collecting_a_tax_id_authorizes_updating_the_customer_name(
    gateway: StripeApiGateway, recorder: _Recorder
):
    """Le défaut exact : Stripe refuse la session sans cette autorisation.

    Un numéro de TVA appartient à une raison sociale. Le collecter sans pouvoir
    mettre à jour le nom produirait une facture dont le numéro fiscal et le nom
    ne se correspondent pas — Stripe préfère refuser.
    """
    _create(gateway)

    assert recorder.params["tax_id_collection"] == {"enabled": True}
    assert recorder.params["customer_update"]["name"] == "auto"


def test_a_collected_address_is_also_kept(gateway: StripeApiGateway, recorder: _Recorder):
    """L'adresse est exigée à l'écran ; la saisir sans la conserver n'a pas de sens."""
    _create(gateway)

    assert recorder.params["billing_address_collection"] == "required"
    assert recorder.params["customer_update"]["address"] == "auto"


def test_the_account_travels_on_both_reconciliation_paths(
    gateway: StripeApiGateway, recorder: _Recorder
):
    """§13 — la session porte le compte, et l'abonnement qui en naîtra aussi."""
    _create(gateway, account_id="acc_reconcile")

    assert recorder.params["client_reference_id"] == "acc_reconcile"
    assert recorder.params["subscription_data"]["metadata"]["kivou_account_id"] == "acc_reconcile"


def test_the_session_expires_when_the_local_attempt_does(
    gateway: StripeApiGateway, recorder: _Recorder
):
    """Une session qui survit à la tentative locale bloquerait le compte."""
    _create(gateway)

    assert recorder.params["expires_at"] == int(EXPIRES.timestamp())


def test_the_return_urls_are_passed_through_untouched(
    gateway: StripeApiGateway, recorder: _Recorder
):
    _create(gateway)

    assert recorder.params["success_url"] == "https://staging.kivou.eu/checkout/success"
    assert recorder.params["cancel_url"] == "https://staging.kivou.eu/checkout/cancel"


def test_automatic_tax_is_sent_exactly_as_configured(
    gateway: StripeApiGateway, recorder: _Recorder
):
    """§24 — aucune décision fiscale n'est prise par défaut."""
    _create(gateway, automatic_tax=False)
    assert recorder.params["automatic_tax"] == {"enabled": False}

    _create(gateway, automatic_tax=True)
    assert recorder.params["automatic_tax"] == {"enabled": True}


def test_no_discount_is_sent_when_no_coupon_applies(
    gateway: StripeApiGateway, recorder: _Recorder
):
    """Une liste de remises vide n'est pas la même chose qu'aucune remise."""
    _create(gateway, coupon_id=None)

    assert "discounts" not in recorder.params


def test_a_coupon_is_sent_as_a_discount(gateway: StripeApiGateway, recorder: _Recorder):
    _create(gateway, coupon_id="coupon_founding")

    assert recorder.params["discounts"] == [{"coupon": "coupon_founding"}]


def test_the_idempotency_key_travels_in_the_options(
    gateway: StripeApiGateway, recorder: _Recorder
):
    """Sans elle, un double clic ouvrirait deux paiements pour un abonnement."""
    _create(gateway, idempotency_key="idem-42")

    assert recorder.options["idempotency_key"] == "idem-42"


def test_the_session_is_a_subscription_for_one_unit(
    gateway: StripeApiGateway, recorder: _Recorder
):
    _create(gateway, price_id="price_essential_eur")

    assert recorder.params["mode"] == "subscription"
    assert recorder.params["line_items"] == [{"price": "price_essential_eur", "quantity": 1}]
