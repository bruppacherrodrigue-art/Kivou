"""CLOSEOUT §3 — les URL de retour Stripe n'ont plus de défaut.

Ce que ces tests protègent
──────────────────────────
Un défaut codé en dur (`https://app.kivou.ch/billing/success`) a survécu au
changement de domaine produit sans que rien ne le signale. Un mauvais domaine de
retour ne se voit qu'au premier paiement réel : le client paie, puis atterrit
sur un hôte qui n'est plus le nôtre.

La règle est donc : une facturation activée DÉCLARE ses URL de retour, ou elle
ne démarre pas. Et si la configuration passe malgré tout (application construite
à la main), l'ouverture d'un paiement échoue en 503 plutôt que d'envoyer le
client nulle part.
"""

from __future__ import annotations

import datetime as dt

import pytest
from billing_helpers import BILLING_RETURN_URLS, FakeStripe
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.api.config import (
    STRIPE_CANCEL_URL_ENV,
    STRIPE_PORTAL_RETURN_URL_ENV,
    STRIPE_SECRET_KEY_ENV,
    STRIPE_SUCCESS_URL_ENV,
)
from signals.persistence.database import create_database_engine, migrate_to_latest


@pytest.fixture
def engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


# ─── Au démarrage ────────────────────────────────────────────────────────────


def test_no_stripe_key_means_no_return_urls_are_required(monkeypatch):
    """Un déploiement sans facturation démarre : il n'encaisse rien."""
    for name in (
        STRIPE_SECRET_KEY_ENV,
        STRIPE_SUCCESS_URL_ENV,
        STRIPE_CANCEL_URL_ENV,
        STRIPE_PORTAL_RETURN_URL_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    config = ApiConfig.from_environment()

    assert config.stripe_success_url is None
    assert config.billing_return_urls_configured is False


@pytest.mark.parametrize(
    "missing",
    [STRIPE_SUCCESS_URL_ENV, STRIPE_CANCEL_URL_ENV, STRIPE_PORTAL_RETURN_URL_ENV],
)
def test_a_stripe_key_without_every_return_url_refuses_to_start(monkeypatch, missing: str):
    """L'intention d'encaisser sans savoir où revenir s'arrête au démarrage."""
    monkeypatch.setenv(STRIPE_SECRET_KEY_ENV, "sk_test_" + "0" * 24)
    monkeypatch.setenv(STRIPE_SUCCESS_URL_ENV, BILLING_RETURN_URLS["stripe_success_url"])
    monkeypatch.setenv(STRIPE_CANCEL_URL_ENV, BILLING_RETURN_URLS["stripe_cancel_url"])
    monkeypatch.setenv(
        STRIPE_PORTAL_RETURN_URL_ENV, BILLING_RETURN_URLS["stripe_portal_return_url"]
    )
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(ValueError) as error:
        ApiConfig.from_environment()

    # Le message NOMME la variable manquante : une erreur de configuration doit
    # se réparer sans lire le code source.
    assert missing in str(error.value)


def test_a_complete_billing_configuration_starts(monkeypatch):
    monkeypatch.setenv(STRIPE_SECRET_KEY_ENV, "sk_test_" + "0" * 24)
    monkeypatch.setenv(STRIPE_SUCCESS_URL_ENV, "https://kivou.eu/checkout/success")
    monkeypatch.setenv(STRIPE_CANCEL_URL_ENV, "https://kivou.eu/checkout/cancel")
    monkeypatch.setenv(STRIPE_PORTAL_RETURN_URL_ENV, "https://kivou.eu/app/billing")

    config = ApiConfig.from_environment()

    assert config.billing_return_urls_configured is True
    assert config.stripe_success_url == "https://kivou.eu/checkout/success"


def test_no_obsolete_domain_survives_anywhere_in_the_configuration(monkeypatch):
    """Aucune valeur par défaut ne peut plus désigner un domaine obsolète."""
    for name in (
        STRIPE_SECRET_KEY_ENV,
        STRIPE_SUCCESS_URL_ENV,
        STRIPE_CANCEL_URL_ENV,
        STRIPE_PORTAL_RETURN_URL_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    config = ApiConfig.from_environment()
    rendered = repr(config)

    assert "app.kivou.ch" not in rendered
    for value in (
        config.stripe_success_url,
        config.stripe_cancel_url,
        config.stripe_portal_return_url,
    ):
        assert value is None


def test_a_return_url_must_be_https(monkeypatch):
    monkeypatch.delenv(STRIPE_SECRET_KEY_ENV, raising=False)
    monkeypatch.setenv(STRIPE_SUCCESS_URL_ENV, "http://kivou.eu/checkout/success")

    with pytest.raises(ValueError):
        ApiConfig.from_environment()


# ─── À l'exécution ───────────────────────────────────────────────────────────


def _app(engine, *, urls: dict[str, str]):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            **urls,
        ),
        stripe_gateway=FakeStripe(),
    )


def _signed_up(app) -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": "claire@negoce-romand.ch",
            "password": PASSWORD,
            "company_name": "Négoce Romand",
            "locale": "fr",
        },
    )
    return client


def test_checkout_refuses_to_open_without_return_urls(engine):
    """Sans chemin de retour, le paiement ne s'ouvre pas.

    Le service se déclare INDISPONIBLE plutôt que d'abandonner un client au bout
    du parcours Stripe. C'est exact, et c'est réparable par configuration.
    """
    client = _signed_up(_app(engine, urls={}))

    response = client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "billing_unavailable"


def test_the_portal_refuses_to_open_without_return_urls(engine):
    client = _signed_up(_app(engine, urls={}))

    response = client.post("/billing/portal")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "billing_unavailable"


def test_reading_billing_state_still_works_without_return_urls(engine):
    """La lecture n'est pas une transaction : elle n'a pas besoin d'URL de retour.

    Un compte doit pouvoir consulter son offre même sur un déploiement dont la
    facturation n'est pas encore configurée.
    """
    client = _signed_up(_app(engine, urls={}))

    assert client.get("/billing/status").status_code == 200
    assert client.get("/billing/plans").status_code == 200


def test_checkout_opens_once_the_return_urls_are_configured(engine):
    client = _signed_up(_app(engine, urls=BILLING_RETURN_URLS))

    response = client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})

    assert response.status_code == 200
    assert response.json()["checkout_url"].startswith("https://")
