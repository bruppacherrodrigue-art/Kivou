"""Contexte Alembic — piloté par un moteur fourni, jamais par un fichier `.ini`.

`alembic.ini` n'existe pas dans ce dépôt, et c'est délibéré : il porterait une
URL de base, donc un secret, dans un fichier versionné. L'appelant fournit un
moteur déjà configuré via `config.attributes`.
"""

from __future__ import annotations

from alembic import context

# L'import enregistre les tables de SPEC-011 dans le même `METADATA`.
import signals.accounts.schema
import signals.billing.schema
import signals.engagement.schema  # noqa: F401
from signals.persistence.schema import METADATA

target_metadata = METADATA


def run_migrations_offline() -> None:
    """Génère le SQL sans connexion — utile pour relire un déploiement avant de l'appliquer."""
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = context.config.attributes.get("connection_engine")
    if engine is None:  # pragma: no cover - garde-fou de configuration
        raise RuntimeError("aucun moteur fourni : `alembic_config(engine)` est obligatoire")
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():  # pragma: no cover
    run_migrations_offline()
else:
    run_migrations_online()
