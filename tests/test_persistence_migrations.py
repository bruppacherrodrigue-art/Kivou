"""SPEC-010 §3, §13, §14 — une base se reconstruit depuis zéro, ou elle ne vaut rien.

Le test central part d'un fichier vide et applique les migrations. Il échouerait
si quelqu'un créait une table à la main quelque part : le schéma vivant et le
schéma migré sont comparés colonne par colonne.

Aucun service de base de données n'est requis. Les tests utilisent SQLite dans
un répertoire temporaire ; la compatibilité PostgreSQL est vérifiée par
compilation du DDL dans `test_persistence_schema.py`.
"""

from __future__ import annotations

import pathlib

import pytest
import sqlalchemy as sa

from signals.persistence.database import (
    DATABASE_URL_ENV,
    create_database_engine,
    migrate_to_latest,
    resolve_database_url,
)
from signals.persistence.schema import METADATA


@pytest.fixture
def fresh_url(tmp_path: pathlib.Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}"


# ─── §13 — base vide → schéma courant ──────────────────────────────────────────


def test_an_empty_database_reaches_the_latest_schema_through_migrations(fresh_url: str):
    engine = create_database_engine(fresh_url)
    with engine.connect() as connection:
        assert sa.inspect(connection).get_table_names() == []

    migrate_to_latest(engine)

    with engine.connect() as connection:
        tables = set(sa.inspect(connection).get_table_names())
    assert set(METADATA.tables) <= tables


def test_the_migrated_schema_matches_the_declared_schema_column_for_column(fresh_url: str):
    """Une table créée hors migration se verrait immédiatement."""
    engine = create_database_engine(fresh_url)
    migrate_to_latest(engine)

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for name, table in METADATA.tables.items():
            migrated = {column["name"] for column in inspector.get_columns(name)}
            assert migrated == {column.name for column in table.columns}, name


def test_migrating_an_already_current_database_changes_nothing(fresh_url: str):
    """§13 — la migration est rejouable : un déploiement peut la lancer à chaque démarrage."""
    engine = create_database_engine(fresh_url)
    migrate_to_latest(engine)
    with engine.connect() as connection:
        before = sorted(sa.inspect(connection).get_table_names())

    migrate_to_latest(engine)

    with engine.connect() as connection:
        assert sorted(sa.inspect(connection).get_table_names()) == before


def test_the_migration_state_is_recorded_in_the_database(fresh_url: str):
    engine = create_database_engine(fresh_url)
    migrate_to_latest(engine)
    with engine.connect() as connection:
        assert "alembic_version" in sa.inspect(connection).get_table_names()
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert revision


def test_foreign_keys_are_enforced_on_sqlite(fresh_url: str):
    """SQLite ignore les clés étrangères par défaut — ce qui masquerait des bugs."""
    engine = create_database_engine(fresh_url)
    migrate_to_latest(engine)
    with engine.connect() as connection:
        assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1


# ─── §3, §14 — configuration par l'environnement, secrets hors du code ─────────


def test_the_database_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql+psycopg://kivou@localhost/kivou")
    assert resolve_database_url() == "postgresql+psycopg://kivou@localhost/kivou"


def test_a_missing_configuration_fails_loudly_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    """Aucune base par défaut : un défaut silencieux écrirait quelque part au hasard."""
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match=DATABASE_URL_ENV):
        resolve_database_url()


def test_no_credential_is_ever_written_in_the_source():
    """§3 — secrets hors du code source."""
    source = pathlib.Path("src/signals/persistence/database.py").read_text(encoding="utf-8")
    for marker in ("password=", "PASSWORD", "postgres://user:"):
        assert marker not in source


def test_an_explicit_url_overrides_the_environment(monkeypatch: pytest.MonkeyPatch, fresh_url: str):
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql+psycopg://never@used/db")
    engine = create_database_engine(fresh_url)
    assert engine.url.get_backend_name() == "sqlite"


def test_the_engine_targets_postgresql_when_configured_for_it(monkeypatch: pytest.MonkeyPatch):
    """Vérifie le dialecte sans ouvrir de connexion : aucun serveur requis."""
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql+psycopg://kivou@localhost/kivou")
    engine = create_database_engine()
    assert engine.dialect.name == "postgresql"
