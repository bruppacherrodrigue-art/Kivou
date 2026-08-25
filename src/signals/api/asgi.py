"""Le point d'entrée ASGI de production — la seule chose qu'un serveur importe.

    uvicorn signals.api.asgi:app

Pourquoi ce module existe
─────────────────────────
`create_app()` est une fabrique : elle reçoit un moteur et une configuration.
C'est exactement ce qu'il faut pour les tests, qui construisent une application
par cas avec une base jetable et une horloge figée. Mais un serveur ASGI importe
un OBJET, pas une fabrique.

Sans ce module, chaque déploiement invente son propre bout de code de démarrage
— et c'est précisément ce qui s'est produit : le staging Kivou a tourné pendant
des semaines sur un `asgi.py` qui ne vivait que sur une branche jamais
intégrée. Déployer un SHA de `main` échouait donc sur `ModuleNotFoundError`, et
personne ne pouvait reproduire le serveur depuis le dépôt. Un point d'entrée
non versionné n'est pas un détail d'exploitation : c'est une dépendance de
production que la revue de code ne voit jamais.

Ce module fait donc le strict minimum : lire l'environnement, ouvrir un moteur,
construire l'application, câbler les deux adaptateurs qui ont besoin de secrets.
Rien d'autre.

Ce qu'il ne fait PAS
────────────────────
Il ne migre pas la base. La migration est une opération ponctuelle du
déploiement, jouée UNE fois avant le redémarrage ; la déclencher ici la ferait
courir dans chaque worker au démarrage, et plusieurs workers se disputeraient la
table `alembic_version`.

Il n'accepte aucun défaut de configuration : `ApiConfig.from_environment()` et
`resolve_database_url()` refusent tous deux de deviner. Un démarrage sans
configuration s'arrête avec un message clair plutôt que d'écrire au mauvais
endroit.
"""

from __future__ import annotations

from fastapi import FastAPI

from signals.accounts.reset_delivery import SmtpPasswordResetDelivery
from signals.alerts.gateway import SmtpAlertGateway, SmtpConfiguration
from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.billing.gateway import StripeApiGateway
from signals.campaigns.runtime_webhook import (
    build_instantly_webhook_service,
    load_instantly_webhook_runtime_config,
)
from signals.persistence.database import create_database_engine
from signals.runtime_events import configure_runtime_event_logging


def build_application() -> FastAPI:
    """L'application telle que la production la sert.

    Le moteur reçoit `pool_pre_ping` : une connexion PostgreSQL peut être coupée
    par un redémarrage de base ou un pare-feu sans que le pool le sache. Sans
    cette vérification, la première requête après la coupure échoue chez un
    client plutôt que d'être remplacée en silence.
    """
    configure_runtime_event_logging()
    config = ApiConfig.from_environment()
    webhook_configuration = load_instantly_webhook_runtime_config(required=False)
    engine = create_database_engine(pool_pre_ping=True)
    return create_app(
        engine,
        config,
        stripe_gateway=_stripe_gateway(config),
        password_reset_delivery=_password_reset_delivery(config),
        instantly_webhook_service=(
            build_instantly_webhook_service(engine, webhook_configuration)
            if webhook_configuration is not None
            else None
        ),
    )


def _stripe_gateway(config: ApiConfig) -> StripeApiGateway | None:
    """La passerelle Stripe, ou `None` quand aucune clé n'est configurée.

    `None` n'est pas une panne : c'est l'état normal d'un déploiement qui
    n'encaisse pas. Les routes de facturation répondent alors 503
    `billing_unavailable`, ce qui est exact et lisible.

    Sans cette fabrique, l'application construite ici n'aurait JAMAIS de
    passerelle — la facturation serait indisponible en permanence, y compris sur
    un déploiement parfaitement configuré, et rien ne l'expliquerait.
    """
    if config.stripe_secret_key is None:
        return None
    return StripeApiGateway(config.stripe_secret_key)


def _password_reset_delivery(config: ApiConfig) -> SmtpPasswordResetDelivery | None:
    """La remise du lien de réinitialisation, ou `None` sans SMTP.

    Même défaut que la passerelle Stripe, et découvert de la même façon : la
    fabrique acceptait `password_reset_delivery` depuis SPEC-011, mais aucun
    point d'entrée de production ne la fournissait. La production retombait donc
    sur `_NullDelivery` — le jeton était créé en base, la route rendait 202, et
    personne ne recevait jamais rien. Rien dans les journaux ne le disait :
    l'absence d'e-mail ne produit aucune erreur.

    Ajouter des identifiants SMTP à l'environnement N'AURAIT PAS suffi. Il
    fallait ce câblage.

    `None` reste l'état normal d'un déploiement sans SMTP : la demande est alors
    acceptée et le jeton reste inutilisé jusqu'à expiration, ce qui vaut mieux
    qu'un démarrage refusé.
    """
    if not config.password_reset_email_configured:
        return None
    gateway = SmtpAlertGateway(
        SmtpConfiguration(
            host=config.smtp_host or "",
            port=config.smtp_port,
            username=config.smtp_username,
            password=config.smtp_password,
            from_email=config.smtp_from_email or "",
            from_name=config.smtp_from_name,
            tls_mode=config.smtp_tls_mode,
            timeout_seconds=config.smtp_timeout_seconds,
            reply_to_email=config.smtp_reply_to_email,
        )
    )
    return SmtpPasswordResetDelivery(
        gateway,
        site_url=config.public_site_url or "",
        ttl=config.password_reset_ttl,
    )


def __getattr__(name: str) -> FastAPI:
    """Construit l'application au PREMIER accès à `app`, pas à l'import.

    `uvicorn signals.api.asgi:app` importe le module puis lit l'attribut : la
    construction a donc bien lieu, au bon moment. Mais un simple
    `import signals.api.asgi` — celui que fait la collecte de tests, ou
    n'importe quel outil qui parcourt le paquet — n'ouvre plus de moteur et
    n'exige plus de configuration. Un module dont le seul import réclame une
    base de données est un module qu'on ne peut ni tester ni inspecter.
    """
    if name == "app":
        return build_application()
    raise AttributeError(f"module {__name__!r} n'a pas d'attribut {name!r}")
