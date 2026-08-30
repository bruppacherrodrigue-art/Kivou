"""Prendre possession d'une clé sans se fier à `rowcount`.

    `rowcount` ne peut PAS répondre à « ai-je inséré, ou était-ce déjà là ? »

Sur PostgreSQL avec `psycopg`, un `INSERT ... ON CONFLICT DO NOTHING` rend
`rowcount = -1` — « inconnu » — que l'insertion ait eu lieu ou non. Toute garde
de la forme `if rowcount not in {0, 1}: raise` se déclenche donc
systématiquement, y compris sur le chemin heureux. Sur SQLite le même code rend
`0` ou `1` : la suite reste verte et le défaut demeure invisible jusqu'au jour
où l'on parle à la base de production.

`RETURNING` répond, lui, de façon déterministe et identique sur les deux
moteurs : une ligne rendue signifie « c'est moi qui ai inséré », aucune ligne
signifie « quelqu'un d'autre l'avait déjà ». Il n'y a pas de troisième cas, donc
plus de garde « indéterminé » à écrire — ni de faux succès, ni de faux conflit.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Row


class UnsupportedConflictDialect(RuntimeError):
    """Le contrat de persistance se limite volontairement à SQLite et PostgreSQL.

    Un autre moteur n'est pas refusé par prudence rituelle : `ON CONFLICT` et
    `RETURNING` ont des sémantiques trop différentes ailleurs pour qu'une
    possession de clé y reste démontrable.
    """


def _conflict_insert(connection: Connection, table: sa.Table):
    dialect = connection.dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise UnsupportedConflictDialect(f"conflict-safe insert unsupported for dialect {dialect}")
    return insert(table)


def insert_if_absent(
    connection: Connection,
    table: sa.Table,
    values: dict[str, Any],
    *,
    index_elements: list[Any] | None = None,
    returning: Any = None,
) -> bool:
    """Insère, et dit si **cette** requête est celle qui a inséré.

    Rend `True` quand la ligne vient d'être créée par cet appel, `False` quand
    une transaction concurrente — ou antérieure — la possédait déjà. Aucune
    troisième issue : c'est ce qui permet à l'appelant de traiter le conflit
    comme un fait, et non comme une incertitude à retenter.

    `index_elements` omis reprend la forme sans argument (`ON CONFLICT DO
    NOTHING` sur n'importe quelle contrainte) : plusieurs appelants s'appuient
    dessus, et la traduire en une liste explicite changerait leur sémantique.
    """
    # `RETURNING 1` suffit : on ne veut pas la ligne, seulement savoir si elle a
    # été écrite. Cela évite d'imposer à chaque appelant de nommer une colonne,
    # et se comporte identiquement sur les deux moteurs.
    projection = sa.literal_column("1") if returning is None else returning
    statement = _conflict_insert(connection, table).values(values)
    statement = (
        statement.on_conflict_do_nothing()
        if index_elements is None
        else statement.on_conflict_do_nothing(index_elements=index_elements)
    )
    return connection.execute(statement.returning(projection)).first() is not None


def upsert_returning(
    connection: Connection,
    table: sa.Table,
    values: dict[str, Any],
    *,
    index_elements: list[Any],
    update_values: dict[str, Any],
    returning: Sequence[Any],
) -> Row[Any]:
    """Insère ou met à jour atomiquement, puis rend l'unique ligne écrite."""
    statement = (
        _conflict_insert(connection, table)
        .values(values)
        .on_conflict_do_update(
            index_elements=index_elements,
            set_=update_values,
        )
        .returning(*returning)
    )
    return connection.execute(statement).one()


__all__ = ["UnsupportedConflictDialect", "insert_if_absent", "upsert_returning"]
