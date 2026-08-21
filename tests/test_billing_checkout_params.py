"""P0-03F — ce que Kivou envoie RÉELLEMENT à Stripe, et ce qu'il fait de son refus.

Le défaut que ce fichier ferme
──────────────────────────────
Le premier paiement TEST réel a échoué en 500 sur staging, alors que 2712
tests étaient verts. Stripe refusait la requête :

    Tax ID collection requires updating business name on the customer.
    To enable tax ID collection for an existing customer, please set
    `customer_update[name]` to `auto`.

Aucun test ne pouvait le voir : tous passent par un faux `StripeGateway` qui
accepte `**kwargs` sans jamais construire le dictionnaire de paramètres que
Stripe reçoit. Le faux prouvait la forme des arguments Kivou, jamais leur
validité Stripe.

D'où ces tests : ils interrogent la VRAIE `StripeApiGateway` et inspectent le
dictionnaire exact remis au SDK. Le client HTTP du SDK est remplacé par un
enregistreur — aucun appel réseau, donc la suite reste hors-ligne — mais la
construction des paramètres, elle, est celle de la production.

La seconde moitié du fichier porte sur la classification des erreurs. Elle est
volontairement asymétrique : libérer la place d'une tentative est l'acte
DANGEREUX (il autorise une seconde session de paiement), donc seule une preuve
qu'aucune session n'existe l'autorise. Tout le reste garde la place.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import stripe

from signals.billing.gateway import (
    CheckoutSessionRejected,
    CheckoutSessionUncertain,
    StripeApiGateway,
)

EXPIRES_AT = dt.datetime(2026, 8, 25, 9, 30, tzinfo=dt.UTC)


class _Session:
    """Ce que le SDK rend : un objet dynamique, lu par attribut."""

    id = "cs_test_recorded"
    url = "https://checkout.stripe.com/c/pay/cs_test_recorded"
    livemode = False


class _RecordingSessions:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, params: dict[str, Any], options: dict[str, Any]) -> _Session:
        self.calls.append({"params": params, "options": options})
        if self.error is not None:
            raise self.error
        return _Session()


class _RecordingClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.checkout = type("_Checkout", (), {"sessions": _RecordingSessions(error)})()


def gateway_recording(
    error: Exception | None = None,
) -> tuple[StripeApiGateway, _RecordingSessions]:
    """La passerelle de production, dont seul le transport est remplacé."""
    gateway = StripeApiGateway("sk_test_offline_double")
    client = _RecordingClient(error)
    gateway._client = client
    return gateway, client.checkout.sessions


def open_session(gateway: StripeApiGateway, *, automatic_tax: bool = False):
    return gateway.create_checkout_session(
        customer_id="cus_existing_1",
        price_id="price_pro_chf",
        account_id="acc_1",
        success_url="https://staging.kivou.eu/checkout/success",
        cancel_url="https://staging.kivou.eu/checkout/cancel",
        automatic_tax=automatic_tax,
        coupon_id=None,
        expires_at=EXPIRES_AT,
        idempotency_key="kivou-checkout:cka_1",
    )


# ─── 1. les paramètres exacts ────────────────────────────────────────────────


def test_un_customer_existant_autorise_stripe_a_completer_nom_et_adresse():
    """Le paramètre qui manquait. Sans lui, Stripe refuse TOUTE session."""
    gateway, sessions = gateway_recording()

    open_session(gateway)

    params = sessions.calls[0]["params"]
    assert params["customer_update"] == {"name": "auto", "address": "auto"}


def test_la_collecte_du_numero_de_tva_est_conservee():
    """§29 — la contourner échangerait un blocage contre une perte de donnée."""
    gateway, sessions = gateway_recording()

    open_session(gateway)

    params = sessions.calls[0]["params"]
    assert params["tax_id_collection"] == {"enabled": True}
    assert params["billing_address_collection"] == "required"


def test_le_client_stripe_reste_celui_que_kivou_a_resolu():
    gateway, sessions = gateway_recording()

    open_session(gateway)

    params = sessions.calls[0]["params"]
    assert params["customer"] == "cus_existing_1"
    assert params["mode"] == "subscription"
    assert params["line_items"] == [{"price": "price_pro_chf", "quantity": 1}]


@pytest.mark.parametrize("enabled", [False, True])
def test_la_fiscalite_automatique_reste_pilotee_par_la_configuration(enabled: bool):
    """`customer_update` ne doit RIEN changer à `automatic_tax` (hors périmètre)."""
    gateway, sessions = gateway_recording()

    open_session(gateway, automatic_tax=enabled)

    assert sessions.calls[0]["params"]["automatic_tax"] == {"enabled": enabled}


def test_la_cle_d_idempotence_reste_celle_de_la_tentative():
    gateway, sessions = gateway_recording()

    open_session(gateway)

    assert sessions.calls[0]["options"]["idempotency_key"] == "kivou-checkout:cka_1"


# ─── 2. refus DÉFINITIF — aucune session ne peut exister ─────────────────────


def test_un_refus_de_parametres_est_definitif():
    """`InvalidRequestError` est un 400 sur la requête : rien n'a été créé.

    C'est exactement l'erreur qu'a produite le défaut `customer_update`.
    """
    gateway, _ = gateway_recording(stripe.InvalidRequestError("Tax ID collection requires…", None))

    with pytest.raises(CheckoutSessionRejected):
        open_session(gateway)


@pytest.mark.parametrize(
    "error",
    [
        stripe.AuthenticationError("clé invalide"),
        stripe.PermissionError("accès refusé"),
    ],
)
def test_une_cle_refusee_est_definitive(error: Exception):
    gateway, _ = gateway_recording(error)

    with pytest.raises(CheckoutSessionRejected):
        open_session(gateway)


def test_le_message_stripe_ne_fuit_pas_dans_l_erreur_kivou():
    """Le message brut reste au journal, jamais dans ce que voit un client."""
    secret_ish = "Request req_b2NukkUugQhoVY: Tax ID collection requires updating business name"
    gateway, _ = gateway_recording(stripe.InvalidRequestError(secret_ish, None))

    with pytest.raises(CheckoutSessionRejected) as raised:
        open_session(gateway)

    assert secret_ish not in str(raised.value)
    assert "req_" not in str(raised.value)


# ─── 3. échec AMBIGU — Stripe a peut-être exécuté la requête ─────────────────


@pytest.mark.parametrize(
    "error",
    [
        stripe.APIConnectionError("connexion interrompue"),
        stripe.APIError("erreur interne Stripe"),
        stripe.RateLimitError("trop de requêtes"),
        stripe.IdempotencyError("clé déjà utilisée avec d'autres paramètres"),
        TimeoutError("délai dépassé"),
    ],
)
def test_une_reponse_perdue_n_est_jamais_traitee_comme_un_refus(error: Exception):
    """Le défaut fermé ici : conclure « échec » d'une réponse jamais reçue.

    `IdempotencyError` en particulier PROUVE qu'une requête portant cette clé a
    déjà été traitée — la traiter en refus libérerait la place alors qu'une
    session existe peut-être déjà.
    """
    gateway, _ = gateway_recording(error)

    with pytest.raises(CheckoutSessionUncertain):
        open_session(gateway)


def test_un_echec_ambigu_n_est_pas_un_refus_definitif():
    """Les deux familles ne doivent jamais se confondre par héritage."""
    gateway, _ = gateway_recording(stripe.APIConnectionError("coupure"))

    with pytest.raises(CheckoutSessionUncertain) as raised:
        open_session(gateway)

    assert not isinstance(raised.value, CheckoutSessionRejected)
