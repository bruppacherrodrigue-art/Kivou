"""Le point d'entrée ASGI de production — la seule chose qu'un serveur importe.

    uvicorn signals.api.asgi:app

Pourquoi ce module existe
─────────────────────────
`create_app()` est une fabrique : elle reçoit un moteur et une configuration.
C'est exactement ce qu'il faut pour les tests, qui construisent une application
par cas avec une base jetable et une horloge figée. Mais un serveur ASGI importe
un OBJET, pas une fabrique. Sans ce module, chaque déploiement inventerait son
propre bout de code de démarrage — et c'est là que les configurations divergent.

Ce module fait donc le strict minimum : lire l'environnement, ouvrir un moteur,
construire l'application. Rien d'autre.

Ce qu'il ne fait PAS
────────────────────
Il ne migre pas la base. La migration est une opération ponctuelle du
déploiement, jouée UNE fois avant le redémarrage (§12) ; la déclencher ici la
ferait courir dans chaque worker au démarrage, et plusieurs workers se
disputeraient la table `alembic_version`.

Il n'accepte aucun défaut de configuration : `ApiConfig.from_environment()` et
`resolve_database_url()` refusent tous deux de deviner. Un démarrage sans
configuration s'arrête avec un message clair plutôt que d'écrire au mauvais
endroit.
"""

from __future__ import annotations

from fastapi import FastAPI

from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.billing.gateway import StripeApiGateway
from signals.persistence.database import create_database_engine


def build_application() -> FastAPI:
    """L'application telle que la production la sert.

    Le moteur reçoit `pool_pre_ping` : une connexion PostgreSQL peut être coupée
    par un redémarrage de base ou un pare-feu sans que le pool le sache. Sans
    cette vérification, la première requête après la coupure échoue chez un
    client plutôt que d'être remplacée en silence.
    """
    config = ApiConfig.from_environment()
    engine = create_database_engine(pool_pre_ping=True)
    return create_app(engine, config, stripe_gateway=_stripe_gateway(config))


def _stripe_gateway(config: ApiConfig) -> StripeApiGateway | None:
    """La passerelle Stripe, ou `None` quand aucune clé n'est configurée.

    `None` n'est pas une panne : c'est l'état normal d'un déploiement qui
    n'encaisse pas. Les routes de facturation répondent alors 503
    `billing_unavailable`, ce qui est exact et lisible.

    Sans cette fabrique, l'application construite ici n'aurait JAMAIS de
    passerelle — la facturation serait indisponible en permanence, y compris
    sur un déploiement parfaitement configuré, et rien ne l'expliquerait.
    """
    if config.stripe_secret_key is None:
        return None
    return StripeApiGateway(config.stripe_secret_key)


def __getattr__(name: str) -> FastAPI:
    """Construit l'application au PREMIER accès à `app`, pas à l'import.

    `uvicorn signals.api.asgi:app` importe le module puis lit l'attribut : la
    construction a donc bien lieu, au bon moment. Mais un simple `import
    signals.api.asgi` — celui que fait la collecte de tests, ou n'importe quel
    outil qui parcourt le paquet — n'ouvre plus de moteur et n'exige plus de
    configuration. Un module dont le seul import réclame une base de données
    est un module qu'on ne peut ni tester ni inspecter.
    """
    if name == "app":
        return build_application()
    raise AttributeError(f"module {__name__!r} n'a pas d'attribut {name!r}")
