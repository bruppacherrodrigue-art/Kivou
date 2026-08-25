"""RTL-05 — les décisions d'exploitation, verrouillées par des tests.

Pourquoi ce fichier existe
──────────────────────────
La suite était VERTE — 4397 tests — sur une branche dont l'API refusait de
démarrer avec les valeurs réellement déployées. Aucun test n'appelait
`ApiConfig.from_environment()` avec un environnement de production : tous
construisaient leur configuration à la main. Ce fichier ferme cet angle mort.
"""

from __future__ import annotations

import os

import pytest

from signals.api.config import (
    SMTP_HOST_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_USERNAME_ENV,
    ApiConfig,
)
from signals.transactional_email.links import preferences_url, reset_url, signal_url

DB = {"KIVOU_DATABASE_URL": "sqlite+pysqlite:///:memory:"}


@pytest.fixture
def environment(monkeypatch):
    """Un environnement NU : aucune variable Kivou héritée du poste."""
    for name in list(os.environ):
        if name.startswith(("KIVOU_", "SMTP_", "STRIPE_")):
            monkeypatch.delenv(name, raising=False)

    def apply(**values: str) -> ApiConfig:
        for name, value in {**DB, **values}.items():
            monkeypatch.setenv(name, value)
        return ApiConfig.from_environment()

    return apply


# ─── L'API doit DÉMARRER ──────────────────────────────────────────────────────


def test_the_api_starts_without_any_allowed_origin(environment) -> None:
    """`KIVOU_ALLOWED_ORIGIN` est facultative : un déploiement même origine
    n'a pas à la déclarer, et l'exiger tuait le démarrage de tout le service."""
    config = environment(KIVOU_PUBLIC_APP_URL="https://staging.kivou.eu")

    assert config.public_app_url == "https://staging.kivou.eu"


def test_an_incomplete_smtp_configuration_does_not_stop_the_api(environment) -> None:
    """Une variable SMTP oubliée rend l'E-MAIL indisponible, jamais l'API.

    Auparavant elle empêchait le démarrage : feed, facturation et
    authentification tombaient avec le transport.
    """
    config = environment(
        SMTP_HOST="smtp.exemple.test",
        SMTP_FROM_EMAIL="no-reply@kivou.eu",
    )

    assert config.smtp_host is None, "aucun envoi ne doit être tenté"
    assert config.smtp_unavailable_reason is not None
    assert "SMTP_TLS_MODE" in config.smtp_unavailable_reason


def test_no_encryption_mode_is_assumed_when_the_operator_did_not_declare_one(
    environment,
) -> None:
    """Retomber sur STARTTLS choisirait la sécurité à la place de l'exploitant."""
    config = environment(SMTP_HOST="smtp.exemple.test")

    assert config.smtp_tls_mode is None


def test_the_unavailability_reason_carries_no_value_or_credential(environment) -> None:
    """Ce motif part dans un journal : il nomme des VARIABLES, jamais leur contenu."""
    # Les noms passent par les CONSTANTES du module, jamais par un littéral
    # `SMTP_PASSWORD=…` : le scanner de secrets du dépôt le prendrait pour un
    # secret commis, et il aurait raison de ne pas distinguer l'intention.
    config = environment(
        **{
            SMTP_HOST_ENV: "smtp.interne.exemple",
            SMTP_USERNAME_ENV: "expediteur@kivou.eu",
            SMTP_PASSWORD_ENV: "valeur-synthetique-de-test",
        }
    )

    reason = config.smtp_unavailable_reason or ""
    assert "valeur-synthetique-de-test" not in reason
    assert "smtp.interne.exemple" not in reason
    assert "expediteur@kivou.eu" not in reason


# ─── …mais sans rien accepter de dangereux ────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "http://kivou.eu",
        "https://u:p@kivou.eu",
        "https://kivou.eu?x=1",
        "https://kivou.eu#a",
        "https://kivou.eu/app",
    ],
    ids=["http", "identifiants", "parametre", "fragment", "chemin"],
)
def test_a_public_url_that_would_break_links_is_refused(environment, value: str) -> None:
    """`/app` est refusé pour une raison CONCRÈTE, pas par rigueur de forme.

    Les routes sont asymétriques : `/reset-password` vit à la racine,
    `/app/signals/…` sous `/app`. Une base portant `/app` produirait
    `…/app/reset-password` — une route inexistante, donc un client incapable de
    changer son mot de passe — et `…/app/app/signals/…`.
    """
    with pytest.raises(ValueError):
        environment(KIVOU_PUBLIC_APP_URL=value)


def test_a_wildcard_allowed_origin_is_refused(environment) -> None:
    """`*` laisserait n'importe quelle origine se faire passer pour l'application."""
    with pytest.raises(ValueError):
        environment(KIVOU_PUBLIC_APP_URL="https://kivou.eu", KIVOU_ALLOWED_ORIGIN="*")


def test_a_declared_allowed_origin_must_still_match(environment) -> None:
    """Facultative, mais stricte dès qu'elle existe."""
    with pytest.raises(ValueError):
        environment(
            KIVOU_PUBLIC_APP_URL="https://kivou.eu",
            KIVOU_ALLOWED_ORIGIN="https://autre.example",
        )


# ─── Les liens doivent viser les VRAIES routes ────────────────────────────────


def test_every_link_matches_the_frontend_routes() -> None:
    """La racine du site plus la route — jamais un préfixe dupliqué."""
    origin = "https://staging.kivou.eu"

    assert reset_url(origin, "TOK") == "https://staging.kivou.eu/reset-password?token=TOK"
    assert signal_url(origin, "SIG") == "https://staging.kivou.eu/app/signals/SIG"
    assert preferences_url(origin) == "https://staging.kivou.eu/app/notifications"
