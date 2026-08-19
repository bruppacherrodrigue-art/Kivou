"""La remise du lien de réinitialisation — SPEC-016 §T14.

Ce que ces tests protègent
──────────────────────────
Le défaut trouvé en audit n'était pas dans la logique : `request_password_reset`
créait bien un jeton et appelait bien `delivery.deliver()`. Il était dans le
CÂBLAGE — aucun point d'entrée de production ne fournissait d'adaptateur, donc
la production tournait sur `_NullDelivery`. La route rendait 202, le jeton
existait en base, et personne ne recevait rien. Aucun journal, aucune erreur.

Un tel défaut ne se voit qu'en testant la construction elle-même, pas seulement
le service. C'est l'objet de la dernière section.

Aucun e-mail réel n'est envoyé : le transport est un double.
"""

from __future__ import annotations

import datetime as dt
import logging
import pathlib
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from signals.accounts.reset_delivery import (
    SmtpPasswordResetDelivery,
    build_reset_message,
    reset_link,
)
from signals.alerts.gateway import AlertDeliveryError, DeliveryResult, UncertainDelivery
from signals.api import ApiConfig, create_app
from signals.api.app import _NullDelivery
from signals.persistence.database import create_database_engine, migrate_to_latest

ORIGIN = "https://kivou.test"
SITE = "https://staging.kivou.eu"
TOKEN = "jeton-de-test-0123456789abcdef"
TTL = dt.timedelta(hours=1)


class RecordingTransport:
    """Un transport qui garde le message au lieu de l'envoyer."""

    def __init__(self) -> None:
        self.sent: list = []

    def send(self, message):
        self.sent.append(message)
        return DeliveryResult(provider_message_id=message.message_id)

    @property
    def last(self):
        return self.sent[-1]


class FailingTransport:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def send(self, message):
        raise self._error


# ─── le contrat d'URL ─────────────────────────────────────────────────────────


def test_the_link_targets_the_site_root_not_the_application_prefix():
    """`/reset-password` est servi à la RACINE, pas sous `/app`.

    C'est le piège de ce module : `KIVOU_PUBLIC_APP_URL` vaut `…/app` parce que
    les alertes profondes en ont besoin. Réutiliser cette base ici donnerait
    `…/app/reset-password`, que le routeur client ne connaît pas.
    """
    assert reset_link(SITE, TOKEN) == f"{SITE}/reset-password?token={TOKEN}"


def test_the_token_travels_in_the_query_parameter_the_frontend_reads():
    """Le frontend fait `useSearchParams().get('token')` — rien d'autre."""
    parts = urlsplit(reset_link(SITE, TOKEN))

    assert parts.path == "/reset-password"
    assert parse_qs(parts.query)["token"] == [TOKEN]


def test_a_token_with_url_significant_characters_survives_the_link():
    """Le jeton est encodé : un `&` non échappé tronquerait silencieusement."""
    parts = urlsplit(reset_link(SITE, "a&b=c d"))

    assert parse_qs(parts.query)["token"] == ["a&b=c d"]


def test_a_trailing_slash_on_the_base_does_not_double_up():
    assert reset_link(f"{SITE}/", TOKEN).startswith(f"{SITE}/reset-password")


@pytest.mark.parametrize(
    ("app_url", "expected"),
    [
        ("https://staging.kivou.eu/app", "https://staging.kivou.eu"),
        ("https://staging.kivou.eu/app/", "https://staging.kivou.eu"),
        ("https://kivou.eu/app", "https://kivou.eu"),
        # Une base déjà à la racine reste intacte : on retire un préfixe connu,
        # on ne devine pas.
        ("https://kivou.eu", "https://kivou.eu"),
    ],
)
def test_the_site_root_is_derived_from_the_application_url(app_url: str, expected: str):
    assert ApiConfig(public_app_url=app_url).public_site_url == expected


def test_without_a_public_url_there_is_no_site_root():
    assert ApiConfig().public_site_url is None


# ─── le message ───────────────────────────────────────────────────────────────


def test_the_message_carries_the_link_and_its_lifetime():
    message = build_reset_message(
        email="a@b.test", locale="fr", reset_token=TOKEN, site_url=SITE, ttl=TTL
    )

    assert reset_link(SITE, TOKEN) in message.text_body
    assert "1 heure" in message.text_body


def test_the_message_follows_the_account_language():
    english = build_reset_message(
        email="a@b.test", locale="en", reset_token=TOKEN, site_url=SITE, ttl=TTL
    )
    french = build_reset_message(
        email="a@b.test", locale="fr", reset_token=TOKEN, site_url=SITE, ttl=TTL
    )

    assert english.language == "en"
    assert "Reset your Kivou password" == english.subject
    assert french.language == "fr"
    assert french.subject != english.subject


def test_an_unknown_locale_falls_back_to_french():
    message = build_reset_message(
        email="a@b.test", locale="de", reset_token=TOKEN, site_url=SITE, ttl=TTL
    )

    assert message.language == "fr"


def test_the_security_email_never_borrows_the_alert_vocabulary():
    """Une réinitialisation n'annonce ni opportunité, ni acheteur, ni désinscription.

    Le même gabarit pour les deux ferait qu'un changement de formulation
    commerciale modifierait un e-mail de sécurité.
    """
    message = build_reset_message(
        email="a@b.test", locale="fr", reset_token=TOKEN, site_url=SITE, ttl=TTL
    )
    body = message.text_body.lower()

    for forbidden in ("opportunité", "acheteur", "désinscri", "préférences de notification"):
        assert forbidden not in body


def test_two_requests_do_not_share_a_message_identifier():
    """Un identifiant déterministe ferait écarter le second e-mail comme doublon.

    C'est exactement l'inverse du besoin des alertes, qui dédupliquent un lot.
    Ici, le second message porte le jeton encore valable : le perdre bloquerait
    la personne qui a redemandé un lien.
    """
    first = build_reset_message(
        email="a@b.test", locale="fr", reset_token="jeton-un", site_url=SITE, ttl=TTL
    )
    second = build_reset_message(
        email="a@b.test", locale="fr", reset_token="jeton-deux", site_url=SITE, ttl=TTL
    )

    assert first.message_id != second.message_id


def test_the_message_identifier_never_derives_from_the_token():
    message = build_reset_message(
        email="a@b.test", locale="fr", reset_token=TOKEN, site_url=SITE, ttl=TTL
    )

    assert TOKEN not in message.message_id


# ─── l'échec d'envoi ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error",
    [
        AlertDeliveryError("smtp_authentication_failed", retryable=False),
        UncertainDelivery(),
        RuntimeError("panne inattendue"),
    ],
)
def test_a_delivery_failure_never_reaches_the_caller(error: Exception):
    """Sinon la route rendrait 500 pour une adresse connue et 202 sinon.

    La page de demande deviendrait un oracle d'existence de compte — précisément
    ce que la réponse générique empêche. Et l'exception annulerait la
    transaction qui vient d'insérer le jeton.
    """
    delivery = SmtpPasswordResetDelivery(FailingTransport(error), site_url=SITE, ttl=TTL)

    delivery.deliver(email="a@b.test", locale="fr", reset_token=TOKEN)  # ne lève pas


def test_a_delivery_failure_logs_a_code_and_never_the_token(caplog):
    delivery = SmtpPasswordResetDelivery(
        FailingTransport(AlertDeliveryError("smtp_authentication_failed")),
        site_url=SITE,
        ttl=TTL,
    )

    with caplog.at_level(logging.WARNING):
        delivery.deliver(email="a@b.test", locale="fr", reset_token=TOKEN)

    written = caplog.text
    assert "smtp_authentication_failed" in written
    assert TOKEN not in written
    assert "a@b.test" not in written


def test_an_unexpected_failure_logs_without_leaking_its_message(caplog):
    delivery = SmtpPasswordResetDelivery(
        FailingTransport(RuntimeError(f"échec pour {TOKEN}")), site_url=SITE, ttl=TTL
    )

    with caplog.at_level(logging.WARNING):
        delivery.deliver(email="a@b.test", locale="fr", reset_token=TOKEN)

    assert TOKEN not in caplog.text


def test_it_refuses_to_build_without_a_public_url():
    """Mieux vaut ne pas construire que d'envoyer un lien relatif inutilisable."""
    with pytest.raises(ValueError):
        SmtpPasswordResetDelivery(RecordingTransport(), site_url="", ttl=TTL)


# ─── le parcours complet ──────────────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def transport() -> RecordingTransport:
    return RecordingTransport()


@pytest.fixture
def client(engine, transport: RecordingTransport) -> TestClient:
    app = create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            password_reset_ttl=TTL,
            public_app_url=f"{SITE}/app",
        ),
        password_reset_delivery=SmtpPasswordResetDelivery(transport, site_url=SITE, ttl=TTL),
    )
    return TestClient(app, headers={"Origin": ORIGIN})


def _token_from(message) -> str:
    line = next(part for part in message.text_body.split() if part.startswith(SITE))
    return parse_qs(urlsplit(line).query)["token"][0]


def test_the_emitted_link_is_actually_usable(client: TestClient, transport: RecordingTransport):
    """Le test qui compte : le jeton EXTRAIT DE L'E-MAIL réinitialise vraiment.

    Vérifier séparément que le service émet un jeton et que le gabarit contient
    un lien laisserait passer une troncature, un mauvais paramètre ou une base
    erronée. Ici le jeton fait l'aller-retour complet.
    """
    client.post(
        "/auth/signup",
        json={
            "email": "fondateur@negoce-romand.ch",
            "password": "un-mot-de-passe-assez-long",
            "company_name": "Negoce Romand SA",
            "locale": "fr",
        },
    )

    accepted = client.post(
        "/auth/password-reset/request", json={"email": "fondateur@negoce-romand.ch"}
    )
    assert accepted.status_code == 202
    assert len(transport.sent) == 1

    confirmed = client.post(
        "/auth/password-reset/confirm",
        json={
            "reset_token": _token_from(transport.last),
            "new_password": "un-tout-autre-mot-de-passe",
        },
    )

    assert confirmed.status_code == 200
    assert (
        client.post(
            "/auth/login",
            json={"email": "fondateur@negoce-romand.ch", "password": "un-tout-autre-mot-de-passe"},
        ).status_code
        == 200
    )


def test_an_unknown_address_sends_nothing_and_answers_the_same(
    client: TestClient, transport: RecordingTransport
):
    response = client.post(
        "/auth/password-reset/request", json={"email": "inconnu@negoce-romand.ch"}
    )

    assert response.status_code == 202
    assert transport.sent == []


def test_a_broken_transport_does_not_change_the_public_answer(engine):
    """Une panne SMTP ne doit pas distinguer un compte connu d'un compte inconnu."""
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, public_app_url=f"{SITE}/app"),
        password_reset_delivery=SmtpPasswordResetDelivery(
            FailingTransport(UncertainDelivery()), site_url=SITE, ttl=TTL
        ),
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": "fondateur@negoce-romand.ch",
            "password": "un-mot-de-passe-assez-long",
            "company_name": "Negoce Romand SA",
            "locale": "fr",
        },
    )

    known = client.post(
        "/auth/password-reset/request", json={"email": "fondateur@negoce-romand.ch"}
    )
    unknown = client.post(
        "/auth/password-reset/request", json={"email": "inconnu@negoce-romand.ch"}
    )

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


# ─── le câblage de production ─────────────────────────────────────────────────


SMTP_ENVIRONMENT = {
    "KIVOU_PUBLIC_APP_URL": f"{SITE}/app",
    "SMTP_HOST": "mail.infomaniak.com",
    "SMTP_FROM_EMAIL": "no-reply@kivou.eu",
    "SMTP_USERNAME": "no-reply@kivou.eu",
    "SMTP_PASSWORD": "sans-importance-ici",
}


def test_without_smtp_the_production_entry_point_builds_no_delivery(monkeypatch):
    from signals.api import asgi

    for name in SMTP_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    assert asgi._password_reset_delivery(ApiConfig.from_environment()) is None


def test_with_smtp_the_production_entry_point_builds_a_real_delivery(monkeypatch):
    """Le test qui aurait attrapé le défaut d'origine.

    Il ne vérifie pas qu'un e-mail part — il vérifie que la production CONSTRUIT
    autre chose que la remise nulle.
    """
    from signals.api import asgi

    for name, value in SMTP_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    delivery = asgi._password_reset_delivery(ApiConfig.from_environment())

    assert isinstance(delivery, SmtpPasswordResetDelivery)
    assert not isinstance(delivery, _NullDelivery)


def test_the_production_link_base_drops_the_application_prefix(monkeypatch):
    for name, value in SMTP_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    assert ApiConfig.from_environment().public_site_url == SITE


def test_smtp_without_a_public_url_builds_no_delivery(monkeypatch):
    """Un e-mail dont le lien est cassé est pire qu'un e-mail absent."""
    from signals.api import asgi

    for name, value in SMTP_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("KIVOU_PUBLIC_APP_URL")

    assert asgi._password_reset_delivery(ApiConfig.from_environment()) is None


def test_both_email_senders_share_one_transport_factory(monkeypatch):
    """Deux mappings de configuration finiraient par diverger."""
    from signals.alerts import cli
    from signals.api.mail import smtp_transport

    for name, value in SMTP_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    config = ApiConfig.from_environment()

    assert cli._gateway(config)._configuration == smtp_transport(config)._configuration
