"""#63 — prendre possession d'une clé sans se fier à `rowcount`.

Ce fichier tourne sur les DEUX moteurs
──────────────────────────────────────
C'est tout l'objet du défaut : sur SQLite, `rowcount` rend `0` ou `1` et la
garde du dépôt passait ; sur PostgreSQL avec `psycopg`, il rend `-1` et la même
garde se déclenchait **toujours**. Un test qui n'interroge qu'un moteur ne peut
pas voir ça. `KIVOU_TEST_DATABASE_URL` fait donc rejouer chaque cas contre un
vrai PostgreSQL dans une base jetable ; sans la variable, seul SQLite est
exercé et les cas PostgreSQL sont IGNORÉS — jamais silencieusement verts.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa

from signals.persistence import conflicts
from signals.persistence.conflicts import UnsupportedConflictDialect, insert_if_absent

METADATA = sa.MetaData()
probe = sa.Table(
    "conflict_probe",
    METADATA,
    sa.Column("owner_key", sa.String(64), primary_key=True),
    sa.Column("payload", sa.String(64), nullable=False),
)
upsert_probe = sa.Table(
    "upsert_probe",
    METADATA,
    sa.Column("owner_key", sa.String(64), primary_key=True),
    sa.Column("payload", sa.String(64), nullable=False),
    sa.Column("immutable_marker", sa.String(64), nullable=False),
)

PG_URL = os.environ.get("KIVOU_TEST_DATABASE_URL")


def _sqlite(tmp_path):
    return sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'conflicts.db'}")


def _postgres():
    disposable = f"kivou_conflicts_{uuid.uuid4().hex[:16]}"
    admin = sa.create_engine(PG_URL)
    with admin.connect() as connection:
        connection.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa.text(f'CREATE DATABASE "{disposable}"')
        )
    admin.dispose()
    return sa.create_engine(PG_URL.rsplit("/", 1)[0] + "/" + disposable)


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request, tmp_path):
    if request.param == "postgresql":
        if not PG_URL:
            pytest.skip("KIVOU_TEST_DATABASE_URL absent — cas PostgreSQL non exercé")
        built = _postgres()
    else:
        built = _sqlite(tmp_path)
    METADATA.create_all(built)
    yield built
    built.dispose()


def own(connection, key: str, payload: str = "first") -> bool:
    return insert_if_absent(
        connection,
        probe,
        {"owner_key": key, "payload": payload},
        index_elements=[probe.c.owner_key],
        returning=probe.c.owner_key,
    )


def stored(engine, key: str) -> str | None:
    with engine.connect() as connection:
        return connection.scalar(sa.select(probe.c.payload).where(probe.c.owner_key == key))


def upsert(connection, key: str, payload: str, immutable_marker: str):
    return conflicts.upsert_returning(
        connection,
        upsert_probe,
        {
            "owner_key": key,
            "payload": payload,
            "immutable_marker": immutable_marker,
        },
        index_elements=[upsert_probe.c.owner_key],
        update_values={"payload": payload},
        returning=(
            upsert_probe.c.owner_key,
            upsert_probe.c.payload,
            upsert_probe.c.immutable_marker,
        ),
    )


# ─── Les deux issues, et rien d'autre ────────────────────────────────────────


def test_a_successful_insert_reports_ownership(engine) -> None:
    """L'insertion réussie doit rendre True — c'est le faux conflit qu'on évite."""
    with engine.begin() as connection:
        assert own(connection, "k1") is True
    assert stored(engine, "k1") == "first"


def test_an_idempotency_conflict_reports_no_ownership(engine) -> None:
    """La seconde tentative doit rendre False — c'est le faux succès qu'on évite."""
    with engine.begin() as connection:
        assert own(connection, "k2", "first") is True
    with engine.begin() as connection:
        assert own(connection, "k2", "second") is False
    assert stored(engine, "k2") == "first", "le conflit ne doit RIEN écraser"


def test_ownership_is_claimed_exactly_once_over_many_attempts(engine) -> None:
    """Sur dix tentatives, une seule possession : ni zéro, ni deux."""
    claims = []
    for attempt in range(10):
        with engine.begin() as connection:
            claims.append(own(connection, "k3", f"payload-{attempt}"))

    assert claims.count(True) == 1, f"une seule possession attendue : {claims}"
    assert claims[0] is True, "c'est la PREMIÈRE tentative qui possède"
    assert stored(engine, "k3") == "payload-0"


def test_two_distinct_keys_are_both_owned(engine) -> None:
    """La garde ne doit pas confondre « déjà pris » et « une autre clé existe »."""
    with engine.begin() as connection:
        assert own(connection, "k4") is True
        assert own(connection, "k5") is True


def test_the_result_never_depends_on_rowcount(engine) -> None:
    """La preuve directe du défaut de #63.

    On mesure ce que `rowcount` rend réellement sur ce moteur, et on vérifie que
    la décision de possession NE lui correspond pas nécessairement. Sur
    PostgreSQL il vaut `-1` dans les deux cas : toute logique bâtie dessus est
    fausse, et c'est exactement la garde `not in {0, 1}` que portait le dépôt.
    """
    dialect = engine.dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert

    with engine.begin() as connection:
        statement = (
            insert(probe)
            .values({"owner_key": "k6", "payload": "x"})
            .on_conflict_do_nothing(index_elements=[probe.c.owner_key])
        )
        first = connection.execute(statement).rowcount
        second = connection.execute(statement).rowcount

    if dialect == "postgresql":
        assert first == -1 and second == -1, (
            f"psycopg doit rendre -1 (mesuré: {first}, {second}) — "
            "c'est ce qui faisait échouer la garde du dépôt"
        )
    # Et la possession, elle, reste correcte quel que soit ce que rend rowcount.
    with engine.begin() as connection:
        assert own(connection, "k7") is True
        assert own(connection, "k7") is False


def test_an_unsupported_dialect_is_refused_rather_than_guessed() -> None:
    """Défaut fermé : ailleurs, `ON CONFLICT` et `RETURNING` ne se comportent pas pareil."""

    class _Fake:
        class dialect:
            name = "mysql"

    with pytest.raises(UnsupportedConflictDialect):
        insert_if_absent(
            _Fake(),
            probe,
            {"owner_key": "k8", "payload": "x"},
            index_elements=[probe.c.owner_key],
            returning=probe.c.owner_key,
        )


def test_a_bare_conflict_target_behaves_identically(engine) -> None:
    """Sans `index_elements`, la sémantique doit rester « inséré ou conflit ».

    Plusieurs appelants du dépôt utilisent la forme sans argument. La traduire
    en une liste explicite changerait la contrainte visée : le helper doit donc
    la relayer telle quelle.
    """

    def own_bare(connection, key: str, payload: str) -> bool:
        return insert_if_absent(
            connection,
            probe,
            {"owner_key": key, "payload": payload},
            returning=probe.c.owner_key,
        )

    with engine.begin() as connection:
        assert own_bare(connection, "bare1", "first") is True
    with engine.begin() as connection:
        assert own_bare(connection, "bare1", "second") is False
    assert stored(engine, "bare1") == "first"


def test_the_default_projection_needs_no_column_from_the_caller(engine) -> None:
    """`RETURNING 1` répond à la seule question posée : « ai-je écrit ? ».

    Exiger une colonne de chaque appelant multiplierait les occasions de se
    tromper de table sans rien apporter — on ne lit jamais la ligne rendue.
    """
    with engine.begin() as connection:
        assert (
            insert_if_absent(
                connection,
                probe,
                {"owner_key": "d1", "payload": "x"},
                index_elements=[probe.c.owner_key],
            )
            is True
        )
    with engine.begin() as connection:
        assert (
            insert_if_absent(
                connection,
                probe,
                {"owner_key": "d1", "payload": "y"},
                index_elements=[probe.c.owner_key],
            )
            is False
        )
    assert stored(engine, "d1") == "x"


# ─── Écrire ou remplacer en une seule instruction ───────────────────────────


def test_upsert_returning_inserts_and_returns_the_written_row(engine) -> None:
    with engine.begin() as connection:
        row = upsert(connection, "u1", "first", "created-once")

    assert tuple(row) == ("u1", "first", "created-once")


def test_upsert_returning_updates_only_requested_values_and_returns_the_row(engine) -> None:
    with engine.begin() as connection:
        upsert(connection, "u2", "first", "created-once")
    with engine.begin() as connection:
        row = upsert(connection, "u2", "second", "must-not-replace")

    assert tuple(row) == ("u2", "second", "created-once")
    with engine.connect() as connection:
        stored_row = connection.execute(
            sa.select(upsert_probe).where(upsert_probe.c.owner_key == "u2")
        ).one()
    assert tuple(stored_row) == ("u2", "second", "created-once")


def test_upsert_returning_refuses_an_unsupported_dialect() -> None:
    class _Fake:
        class dialect:
            name = "mysql"

    with pytest.raises(UnsupportedConflictDialect):
        upsert(_Fake(), "u3", "payload", "immutable")


# ─── L'URL de la base jetable ─────────────────────────────────────────────────


def test_a_disposable_url_keeps_its_password_and_its_options() -> None:
    """`str(url)` MASQUE le mot de passe : la base jetable ne s'authentifierait pas.

    Deux pièges se rejoignent ici, et j'ai fait les deux :

    - découper l'URL à la main (`rsplit`) perd les paramètres — `?sslmode=require`
      disparaît, et la base jetable se connecte autrement que l'admin qui vient
      de réussir ;
    - `str(URL)` remplace le mot de passe par `***`, ce qui produit une URL
      d'apparence correcte et une authentification refusée.

    `render_as_string(hide_password=False)` est la seule forme qui rende une URL
    utilisable.
    """
    from conftest import disposable_database_url

    admin = "postgresql+psycopg://kivou:s3cr3t@db.example:5432/postgres?sslmode=require"
    rendered = disposable_database_url(admin, "kivou_test_abc")

    assert "s3cr3t" in rendered, "sans mot de passe, la connexion échoue"
    assert "sslmode=require" in rendered, "les options doivent survivre"
    assert "/kivou_test_abc" in rendered
    assert "***" not in rendered


def test_the_masked_form_is_what_belongs_in_a_log() -> None:
    """Le corollaire : ce qui va dans un journal doit rester masqué.

    Rendre l'URL en clair est nécessaire pour SE CONNECTER, et interdit pour
    JOURNALISER. Les deux formes coexistent, et les confondre ferait fuiter un
    mot de passe dans une sortie de test ou de CI.
    """
    from sqlalchemy.engine import make_url

    url = make_url("postgresql+psycopg://kivou:s3cr3t@db.example:5432/postgres")

    assert "s3cr3t" not in str(url), "la forme par défaut doit masquer"
    assert "s3cr3t" not in repr(url)
    assert "***" in str(url)
