"""Les deux sondes de santé — et ce qu'elles refusent de dire.

Ce que ces tests protègent
──────────────────────────
`/health/live` ne doit JAMAIS toucher la base. Si un jour quelqu'un y ajoute une
requête « pour être sûr », une base injoignable ferait échouer la vivacité, le
superviseur redémarrerait l'application en boucle, et le redémarrage ne
réparerait rien puisque la panne est ailleurs. C'est une panne classique, et
elle se prévient par un test.

`/health/ready` doit distinguer « base injoignable » de « migrations non
jouées » : les deux se réparent différemment.

Et aucune des deux ne doit publier d'infrastructure : ce sont des points
d'entrée NON authentifiés.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest


@pytest.fixture
def engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def unmigrated_engine(tmp_path):
    """Une base joignable, mais sans schéma : le cas « déploiement à moitié fait »."""
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'vide.db'}")


def build(engine):
    return create_app(engine, ApiConfig(cookie_secure=False, session_ttl=dt.timedelta(days=1)))


# ─── Vivacité ────────────────────────────────────────────────────────────────


def test_live_answers_without_any_database(unmigrated_engine):
    client = TestClient(build(unmigrated_engine))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_live_answers_even_when_the_database_is_unreachable(tmp_path):
    """Une base morte ne rend pas le PROCESSUS mort.

    Le moteur pointe vers un pilote qui échouera à la connexion. La vivacité
    doit rester verte : redémarrer l'application ne réparerait pas la base.
    """
    engine = sa.create_engine("postgresql+psycopg://kivou:x@127.0.0.1:1/absente")
    client = TestClient(build(engine))

    response = client.get("/health/live")

    assert response.status_code == 200


# ─── Disponibilité ───────────────────────────────────────────────────────────


def test_ready_is_green_on_a_migrated_database(engine):
    client = TestClient(build(engine))

    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # La révision est une information d'exploitation utile : elle dit d'un coup
    # d'œil quelle migration tourne réellement.
    assert body["revision"]


def test_ready_refuses_traffic_when_migrations_were_never_applied(unmigrated_engine):
    client = TestClient(build(unmigrated_engine))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "migrations_not_applied"


def test_ready_refuses_traffic_when_the_database_is_unreachable():
    engine = sa.create_engine("postgresql+psycopg://kivou:x@127.0.0.1:1/absente")
    client = TestClient(build(engine))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "database_unreachable"


def test_ready_detects_a_schema_older_than_the_code(engine):
    """Une base migrée vers une AUTRE tête ne doit pas recevoir de trafic.

    C'est le déploiement qui a redémarré l'application sans jouer la migration :
    les colonnes attendues manquent, et le premier client verrait une erreur SQL.
    """
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE alembic_version SET version_num = '0001_initial'"))

    client = TestClient(build(engine))
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["reason"] == "schema_revision_mismatch"
    assert body["applied_revision"] == "0001_initial"
    assert body["expected_revision"] != "0001_initial"


# ─── Ce que les sondes ne publient pas ───────────────────────────────────────


def test_no_probe_ever_leaks_infrastructure():
    """Ces routes ne sont pas authentifiées : tout ce qu'elles rendent est public."""
    engine = sa.create_engine(
        "postgresql+psycopg://kivou_user:un-mot-de-passe@db.interne.test:5432/kivou_staging"
    )
    client = TestClient(build(engine))

    bodies = [client.get("/health/live").text, client.get("/health/ready").text]

    for body in bodies:
        for leak in (
            "un-mot-de-passe",
            "kivou_user",
            "db.interne.test",
            "postgresql",
            "psycopg",
            "5432",
            "Traceback",
        ):
            assert leak not in body, leak


def test_readiness_does_not_depend_on_stripe_smtp_or_public_sources(engine):
    """Aucune passerelle n'est injectée : la disponibilité doit rester verte.

    Kivou sert parfaitement un feed et une session quand Stripe est lent ou
    qu'une source publique est en panne. Lier la disponibilité à un tiers
    reviendrait à lui laisser décider de la nôtre.
    """
    app = create_app(engine, ApiConfig(cookie_secure=False))
    assert getattr(app.state, "stripe_gateway", None) is None

    assert TestClient(app).get("/health/ready").status_code == 200


# ─── Surface d'API (§19) ─────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_api_publishes_no_interactive_documentation(engine, path: str):
    """Un dépôt privé qui sert son propre schéma en clair annule sa discrétion."""
    assert TestClient(build(engine)).get(path).status_code == 404
