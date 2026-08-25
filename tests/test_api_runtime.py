"""P0-03E — le point d'entrée que la production importe réellement.

Pourquoi ces tests existent
───────────────────────────
Le gate staging de P0-03 a échoué sur `ModuleNotFoundError: No module named
'signals.api.asgi'`. `main` n'avait aucun point d'entrée ASGI : le serveur
démarrait depuis un fichier qui ne vivait que sur une branche jamais
intégrée. Un déploiement reproductible depuis un SHA était donc impossible.

Ces tests décrivent ce qu'un point d'entrée de production doit garantir, et
chacun correspond à un défaut réel ou évité :

  — l'import ne doit ouvrir aucune base. Un module dont le simple import exige
    une base ne peut être ni collecté par pytest, ni inspecté par un outil ;
  — aucune migration ne doit courir au démarrage. Plusieurs workers uvicorn se
    disputeraient `alembic_version` ;
  — la passerelle Stripe doit être CÂBLÉE quand une clé existe. La fabrique
    l'accepte depuis SPEC-013, mais aucun point d'entrée ne la fournissait ;
  — la remise du lien de réinitialisation doit l'être aussi. Même défaut,
    découvert de la même façon : le jeton était créé, la route rendait 202, et
    personne ne recevait rien.
"""

from __future__ import annotations

import datetime as dt
import importlib
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import BILLING_RETURN_URLS

from signals.api.config import ApiConfig

MODULE = "signals.api.asgi"


@pytest.fixture
def sqlite_url(tmp_path: pathlib.Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'runtime.db'}"


@pytest.fixture
def base_environment(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> None:
    """Un environnement minimal et VALIDE, sans Stripe ni SMTP."""
    for name in (
        "STRIPE_SECRET_KEY",
        "STRIPE_SUCCESS_URL",
        "STRIPE_CANCEL_URL",
        "STRIPE_PORTAL_RETURN_URL",
        "SMTP_HOST",
        "SMTP_FROM_EMAIL",
        "KIVOU_PUBLIC_APP_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KIVOU_DATABASE_URL", sqlite_url)
    monkeypatch.setenv("KIVOU_ALLOWED_ORIGIN", "https://staging.kivou.test")
    monkeypatch.setenv("KIVOU_STRIPE_MODE", "test")


# ─── l'import reste inerte ────────────────────────────────────────────────────


def test_importing_the_entry_point_opens_no_database(monkeypatch: pytest.MonkeyPatch):
    """L'import ne doit RIEN construire — pas même exiger une configuration.

    Le module est retiré de `sys.modules` avant ET après : l'importer à neuf
    est le seul moyen d'observer ce que l'import lui-même déclenche, et le
    retirer ensuite évite de laisser aux tests suivants un module dont les noms
    ont été liés pendant le patch.
    """
    import sys

    for name in ("KIVOU_DATABASE_URL", "KIVOU_ALLOWED_ORIGIN"):
        monkeypatch.delenv(name, raising=False)

    opened: list[str] = []

    def _forbidden(*args: object, **kwargs: object) -> None:
        opened.append("engine")
        raise AssertionError("moteur ouvert à l'import")

    from signals.persistence import database

    monkeypatch.setattr(database, "create_database_engine", _forbidden)
    sys.modules.pop(MODULE, None)
    try:
        importlib.import_module(MODULE)
        assert opened == []
    finally:
        sys.modules.pop(MODULE, None)


def test_the_module_exposes_build_application(base_environment):
    module = importlib.import_module(MODULE)
    assert callable(module.build_application)


def test_an_unknown_attribute_still_raises(base_environment):
    """`__getattr__` ne doit pas transformer chaque faute de frappe en application."""
    module = importlib.import_module(MODULE)
    with pytest.raises(AttributeError):
        # L'affectation n'est pas décorative : sans elle l'accès passe pour une
        # expression sans effet, alors que c'est lui qu'on met à l'épreuve.
        _ = module.something_that_does_not_exist


# ─── ce que `build_application()` construit ───────────────────────────────────


def test_the_application_uses_the_configured_database(base_environment, sqlite_url: str):
    module = importlib.import_module(MODULE)
    app = module.build_application()
    assert str(app.state.engine.url) == sqlite_url


def test_the_engine_checks_connections_before_handing_them_out(base_environment):
    """`pool_pre_ping` : une connexion coupée par la base est remplacée en
    silence plutôt que de faire échouer la requête d'un client."""
    module = importlib.import_module(MODULE)
    app = module.build_application()
    assert app.state.engine.pool._pre_ping is True


def test_starting_the_application_runs_no_migration(base_environment, sqlite_url: str):
    """Plusieurs workers uvicorn se disputeraient `alembic_version`.

    La migration est une étape de déploiement, jouée UNE fois avant le
    redémarrage — jamais à l'import d'un worker.
    """
    module = importlib.import_module(MODULE)
    module.build_application()

    engine = sa.create_engine(sqlite_url, future=True)
    with engine.connect() as connection:
        tables = sa.inspect(connection).get_table_names()
    assert tables == [], "le démarrage a créé des tables : une migration a couru"


# ─── passerelle Stripe ────────────────────────────────────────────────────────


def test_without_a_stripe_key_no_gateway_is_wired(base_environment):
    """Absence de clé n'est pas une panne : c'est un déploiement qui n'encaisse
    pas. Les routes de facturation répondent alors 503."""
    module = importlib.import_module(MODULE)
    app = module.build_application()
    assert app.state.stripe_gateway is None


def test_a_configured_test_key_produces_a_gateway(
    base_environment, monkeypatch: pytest.MonkeyPatch
):
    """Le défaut historique : la fabrique acceptait une passerelle, aucun point
    d'entrée n'en fournissait. La facturation était donc indisponible en
    permanence, y compris sur un déploiement parfaitement configuré."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_" + "0" * 24)
    for name, value in BILLING_RETURN_URLS.items():
        monkeypatch.setenv(name.upper(), value)

    module = importlib.import_module(MODULE)
    app = module.build_application()
    assert app.state.stripe_gateway is not None


def test_billing_is_unavailable_rather_than_broken_without_stripe(base_environment):
    """Sans passerelle, `/billing/checkout` doit se déclarer indisponible —
    et non échouer d'une façon qu'aucun client ne peut interpréter."""
    from fastapi.testclient import TestClient

    module = importlib.import_module(MODULE)
    app = module.build_application()
    client = TestClient(app, headers={"Origin": "https://staging.kivou.test"})
    response = client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    assert response.status_code in {401, 503}


# ─── remise du lien de réinitialisation ───────────────────────────────────────


def test_without_smtp_no_delivery_is_wired(base_environment):
    from signals.accounts.reset_delivery import SmtpPasswordResetDelivery

    module = importlib.import_module(MODULE)
    app = module.build_application()
    assert not isinstance(app.state.password_reset_delivery, SmtpPasswordResetDelivery)


def test_a_configured_smtp_actually_delivers_the_reset_link(
    base_environment, monkeypatch: pytest.MonkeyPatch
):
    """Ajouter des identifiants SMTP à l'environnement NE SUFFISAIT PAS : sans
    ce câblage la production retombait sur `_NullDelivery`, et rien dans les
    journaux ne le disait — l'absence d'e-mail ne produit aucune erreur."""
    from signals.accounts.reset_delivery import SmtpPasswordResetDelivery

    monkeypatch.setenv("SMTP_HOST", "smtp.kivou.test")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@kivou.eu")
    monkeypatch.setenv("SMTP_TLS_MODE", "starttls")
    monkeypatch.setenv("KIVOU_PUBLIC_APP_URL", "https://staging.kivou.test")

    module = importlib.import_module(MODULE)
    app = module.build_application()
    assert isinstance(app.state.password_reset_delivery, SmtpPasswordResetDelivery)


def test_the_reset_link_points_at_the_site_root_not_the_app_prefix():
    """L'origine publique n'inclut aucun chemin et `/reset-password` reste à
    la racine servie par le routeur navigateur."""
    from signals.accounts.reset_delivery import reset_link

    config = ApiConfig(
        allowed_origin="https://staging.kivou.test",
        public_app_url="https://staging.kivou.test",
    )
    assert config.public_site_url == "https://staging.kivou.test"
    link = reset_link(config.public_site_url or "", "jeton-abc")
    assert link == "https://staging.kivou.test/reset-password?token=jeton-abc"
    assert "/app/" not in link


def test_the_reset_message_never_carries_a_tracker():
    from signals.accounts.reset_delivery import build_reset_message

    message = build_reset_message(
        email="claire@negoce-romand.ch",
        locale="fr",
        reset_token="jeton-abc",
        site_url="https://staging.kivou.test",
        ttl=dt.timedelta(hours=1),
    )
    assert "jeton-abc" in message.text_body
    assert "<img" not in message.text_body
    assert "désinscri" not in message.text_body.lower(), "un e-mail de sécurité ne se désinscrit pas"


@pytest.mark.parametrize(
    ("locale", "subject", "greeting", "validity"),
    [
        (
            "fr",
            "Réinitialisation de votre mot de passe Kivou",
            "Bonjour,",
            "Ce lien est valable 1 heure(s) et ne fonctionne qu'une seule fois.",
        ),
        (
            "en",
            "Reset your Kivou password",
            "Hello,",
            "The link is valid for 1 hour(s) and works only once.",
        ),
    ],
)
def test_reset_templates_preserve_the_same_certainty_in_french_and_english(
    locale: str, subject: str, greeting: str, validity: str
) -> None:
    from signals.accounts.reset_delivery import build_reset_message

    message = build_reset_message(
        email="synthetic-user@kivou.eu",
        locale=locale,
        reset_token="synthetic-reset-value",
        site_url="https://staging.kivou.test",
        ttl=dt.timedelta(hours=1),
        message_id=f"<reset-{locale}@kivou.eu>",
    )

    assert message.subject == subject
    assert message.text_body.startswith(greeting)
    assert validity in message.text_body
    assert (
        "https://staging.kivou.test/reset-password?token=synthetic-reset-value"
        in message.text_body
    )


@pytest.mark.parametrize(
    "origin",
    ["https://staging.kivou.test", "https://kivou.eu"],
)
def test_reset_links_are_rooted_at_the_configured_public_origin(origin: str) -> None:
    from signals.accounts.reset_delivery import build_reset_message

    message = build_reset_message(
        email="synthetic-user@kivou.eu",
        locale="fr",
        reset_token="synthetic-reset-value",
        site_url=origin,
        ttl=dt.timedelta(minutes=30),
    )

    assert f"{origin}/reset-password?token=synthetic-reset-value" in message.text_body
    assert f"{origin}/app/" not in message.text_body


@pytest.mark.parametrize(
    "error_code",
    ["unknown_delivery_state", "smtp_authentication_failed"],
)
def test_reset_delivery_failure_logs_only_a_safe_code(caplog, error_code: str) -> None:
    from signals.accounts.reset_delivery import SmtpPasswordResetDelivery
    from signals.alerts.gateway import AlertDeliveryError, UncertainDelivery

    reset_value = "reset-" + "private-value"
    address = "synthetic-private-user" + "@kivou.eu"
    smtp_secret = "smtp-" + "private-value"

    class FailingGateway:
        def send(self, message):
            if error_code == "unknown_delivery_state":
                raise UncertainDelivery()
            raise AlertDeliveryError(error_code, retryable=False)

    delivery = SmtpPasswordResetDelivery(
        FailingGateway(),
        site_url="https://staging.kivou.test",
        ttl=dt.timedelta(hours=1),
    )
    delivery.deliver(email=address, locale="fr", reset_token=reset_value)

    payload = caplog.records[-1].runtime_event
    assert payload == {
        "event": "delivery",
        "channel": "password_reset",
        "status": "failed",
        "code": error_code,
        "retryable": False,
        "attempt": 1,
    }
    rendered = str(payload)
    for forbidden in (reset_value, address, smtp_secret, "Traceback"):
        assert forbidden not in rendered


def test_a_delivery_failure_never_reaches_the_caller():
    """`deliver()` ne lève jamais : une erreur SMTP remontée à la route
    distinguerait une adresse connue d'une inconnue."""
    from signals.accounts.reset_delivery import SmtpPasswordResetDelivery
    from signals.alerts.gateway import AlertDeliveryError

    class Failing:
        def send(self, message):
            raise AlertDeliveryError("smtp_unavailable")

    delivery = SmtpPasswordResetDelivery(
        Failing(), site_url="https://staging.kivou.test", ttl=dt.timedelta(hours=1)
    )
    delivery.deliver(email="claire@negoce-romand.ch", locale="fr", reset_token="jeton-abc")


def test_the_deferred_delivery_sends_nothing_before_it_is_flushed():
    """Le canal temporel : l'aller-retour SMTP n'a lieu que pour un compte
    existant. Mesuré sur staging — 2178 ms pour une adresse connue contre 98 ms
    pour une inconnue, avec la MÊME réponse. La remise quitte donc le temps de
    réponse."""
    from signals.accounts.reset_delivery import DeferredDelivery

    sent: list[dict[str, str]] = []

    class Recording:
        def deliver(self, **kwargs):
            sent.append(kwargs)

    deferred = DeferredDelivery(Recording())
    deferred.deliver(email="claire@negoce-romand.ch", locale="fr", reset_token="jeton-abc")
    assert sent == [], "la remise a eu lieu pendant la requête"

    deferred.flush()
    assert len(sent) == 1

    deferred.flush()
    assert len(sent) == 1, "une seconde vidange rejouerait l'envoi"


# ─── la route ne doit pas trahir l'existence d'un compte ─────────────────────


def test_the_reset_route_defers_the_delivery_out_of_the_request(
    base_environment, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """Câbler SMTP en synchrone ROUVRIRAIT l'oracle temporel.

    Tant que la remise ne faisait rien, les deux chemins coûtaient le même
    temps. Dès qu'un vrai transport est branché, l'aller-retour SMTP n'a lieu
    que pour un compte existant, et la durée redevient observable.

    Ce test regarde ce que la route passe RÉELLEMENT au service : une enveloppe
    différée, et non la remise elle-même. Au moment où le service est appelé —
    donc à l'intérieur de la transaction — rien n'a encore été envoyé.
    """
    from fastapi.testclient import TestClient

    from signals.accounts.reset_delivery import DeferredDelivery
    from signals.api import routes_auth
    from signals.api.app import create_app
    from signals.persistence.database import create_database_engine, migrate_to_latest

    url = f"sqlite+pysqlite:///{tmp_path / 'reset.db'}"
    monkeypatch.setenv("KIVOU_DATABASE_URL", url)
    engine = create_database_engine(url)
    migrate_to_latest(engine)

    sent: list[str] = []
    observed: dict[str, object] = {}

    class Recording:
        def deliver(self, *, email: str, locale: str, reset_token: str) -> None:
            sent.append(email)

    original = routes_auth.service.request_password_reset

    def spy(connection, **kwargs):
        observed["delivery"] = kwargs.get("delivery")
        observed["sent_at_call_time"] = list(sent)
        return original(connection, **kwargs)

    monkeypatch.setattr(routes_auth.service, "request_password_reset", spy)

    app = create_app(engine, password_reset_delivery=Recording())
    client = TestClient(app, headers={"Origin": app.state.config.allowed_origin})
    client.post(
        "/auth/signup",
        json={
            "email": "claire@negoce-romand.ch",
            "password": "motdepassesolide",
            "company_name": "Acme",
            "locale": "fr",
        },
    )

    response = client.post(
        "/auth/password-reset/request", json={"email": "claire@negoce-romand.ch"}
    )
    assert response.status_code == 202

    assert isinstance(observed["delivery"], DeferredDelivery), (
        "la route passe la remise directe : l'envoi a lieu dans la transaction"
    )
    assert observed["sent_at_call_time"] == [], "un envoi a eu lieu pendant la requête"
    # La tâche de fond a bien tourné : le lien part réellement.
    assert sent == ["claire@negoce-romand.ch"]


def test_an_unknown_address_schedules_the_same_work(
    base_environment, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """La route programme `flush()` sans condition : vider zéro remise coûte le
    même prix que d'en vider une, et rien ne distingue les deux chemins."""
    from fastapi.testclient import TestClient

    from signals.api.app import create_app
    from signals.persistence.database import create_database_engine, migrate_to_latest

    url = f"sqlite+pysqlite:///{tmp_path / 'unknown.db'}"
    monkeypatch.setenv("KIVOU_DATABASE_URL", url)
    engine = create_database_engine(url)
    migrate_to_latest(engine)

    sent: list[str] = []

    class Recording:
        def deliver(self, *, email: str, locale: str, reset_token: str) -> None:
            sent.append(email)

    app = create_app(engine, password_reset_delivery=Recording())
    client = TestClient(app, headers={"Origin": app.state.config.allowed_origin})

    response = client.post(
        "/auth/password-reset/request", json={"email": "inconnu@negoce-romand.ch"}
    )
    assert response.status_code == 202
    assert sent == [], "aucun compte, donc aucune remise — mais la même réponse"
