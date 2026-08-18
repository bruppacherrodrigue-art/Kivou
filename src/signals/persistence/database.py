"""La connexion et les migrations — configurées par l'environnement, jamais par le code.

    KIVOU_DATABASE_URL   l'unique point de configuration

Aucune valeur par défaut n'est fournie. Une base par défaut écrirait quelque
part au hasard le jour où la variable manque, et c'est précisément le genre
d'incident qu'on ne détecte qu'après avoir perdu des données.

    Portabilité (§14)
    ─────────────────
    Un déploiement a besoin de trois choses et pas d'une de plus :
    l'application, un PostgreSQL, un volume persistant. Les migrations voyagent
    dans le paquet — `signals/persistence/migrations` — donc une installation
    par wheel sait se migrer elle-même. Aucun service géré, aucun conteneur,
    aucun orchestrateur n'est requis.
"""

from __future__ import annotations

import os
import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

DATABASE_URL_ENV = "KIVOU_DATABASE_URL"

MIGRATIONS_PATH = pathlib.Path(__file__).resolve().parent / "migrations"


def resolve_database_url(url: str | None = None) -> str:
    """L'URL explicite, sinon celle de l'environnement, sinon une erreur claire."""
    if url:
        return url
    configured = os.environ.get(DATABASE_URL_ENV)
    if not configured:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} n'est pas défini : aucune base par défaut n'est "
            "supposée, pour ne pas écrire silencieusement au mauvais endroit"
        )
    return configured


def create_database_engine(url: str | None = None, **options: object) -> sa.Engine:
    """Un moteur SQLAlchemy Core. Aucune connexion n'est ouverte ici."""
    engine = sa.create_engine(resolve_database_url(url), future=True, **options)
    if engine.dialect.name == "sqlite":
        _enforce_sqlite_foreign_keys(engine)
    return engine


def _enforce_sqlite_foreign_keys(engine: sa.Engine) -> None:
    """SQLite ignore les clés étrangères par défaut.

    Les laisser inactives ferait passer en test des écritures que PostgreSQL
    refuserait en production — l'exact inverse de ce qu'un test doit garantir.
    """

    @sa.event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection: object, _record: object) -> None:  # pragma: no cover
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def alembic_config(engine: sa.Engine) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    # L'URL passe par l'objet de configuration plutôt que par le fichier : rien
    # de sensible n'a donc à exister sur disque.
    config.attributes["connection_engine"] = engine
    return config


def migrate_to_latest(engine: sa.Engine) -> None:
    """Amène la base au schéma courant. Rejouable sans effet sur une base à jour."""
    command.upgrade(alembic_config(engine), "head")


def current_revision(engine: sa.Engine) -> str | None:
    with engine.connect() as connection:
        if not sa.inspect(connection).has_table("alembic_version"):
            return None
        return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
