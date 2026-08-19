"""Le point d'entrée ASGI de production.

Ce que ces tests protègent
──────────────────────────
Un point d'entrée qui devine une base par défaut écrirait un jour dans le
mauvais endroit sans que personne ne s'en aperçoive. Et un point d'entrée qui
migre au démarrage ferait courir plusieurs workers sur `alembic_version`.
"""

from __future__ import annotations

import pytest

from signals.api import asgi
from signals.persistence.database import DATABASE_URL_ENV, current_revision


def test_importing_the_module_needs_no_configuration(monkeypatch):
    """L'import seul n'ouvre aucun moteur : sinon rien ne pourrait l'inspecter."""
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    import importlib

    importlib.reload(asgi)  # ne lève pas


def test_accessing_app_without_a_configured_database_fails_clearly(monkeypatch):
    """`uvicorn …:app` lit l'attribut — c'est là que la configuration est exigée."""
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(RuntimeError) as error:
        _ = asgi.app

    assert DATABASE_URL_ENV in str(error.value)


def test_it_refuses_to_start_without_a_configured_database(monkeypatch):
    """Aucune base supposée : mieux vaut ne pas démarrer qu'écrire ailleurs."""
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(RuntimeError) as error:
        asgi.build_application()

    assert DATABASE_URL_ENV in str(error.value)


def test_it_builds_an_application_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    application = asgi.build_application()

    assert application.title == "Kivou"
    # La sonde de vivacité RÉPOND — c'est ce que le proxy interrogera, et c'est
    # une affirmation plus forte que d'inspecter la table de routage.
    from fastapi.testclient import TestClient

    assert TestClient(application).get("/health/live").status_code == 200


def test_it_does_not_migrate_at_startup(monkeypatch, tmp_path):
    """La migration est une étape de déploiement, jouée UNE fois (§12).

    La déclencher ici la ferait courir dans chaque worker, et plusieurs workers
    se disputeraient la table de version.
    """
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'neuve.db'}")

    application = asgi.build_application()

    assert current_revision(application.state.engine) is None
