"""Quel compte possède un signal matérialisé — et lequel n'appartient à personne.

    RÈGLE FAISANT AUTORITÉ (closeout §3)
    ────────────────────────────────────
    Un signal matérialisé est LIÉ À UN CLIENT si et seulement si son
    `target_icp_id` désigne une ligne réelle de `target_icp`.

    `target_icp.account_id` est la SEULE source de propriété.

    Sans ligne correspondante, le signal est NON LIÉ / RECHERCHE / PRÉ-SaaS.
    Il n'appartient à aucun compte, et ne devient jamais visible d'un client
    parce que sa chaîne d'identifiant ressemble à celle d'un ICP.

La propriété n'est JAMAIS déduite du contenu du signal, du contenu de l'ICP, de
ce que le compte a saisi, ni d'une similarité de ciblage. Une seule jointure la
détermine, et elle est écrite ici une fois pour toutes.

    Pourquoi une référence molle, et pas une clé étrangère
    ─────────────────────────────────────────────────────
    `materialized_signal.target_icp_id` n'a pas de clé étrangère vers
    `target_icp`, et c'est délibéré : les signaux produits par SPEC-010 sont
    antérieurs à l'existence des comptes et référencent des identifiants d'ICP
    de recherche. Une clé étrangère les rendrait insérables uniquement au prix
    de faux comptes ou d'une reconstruction destructive de la table — deux
    choses interdites. La frontière est donc tenue *ici*, explicitement, plutôt
    que par le schéma.

    Ce que SPEC-012 doit en faire
    ────────────────────────────
    Un feed part du COMPTE et descend : compte → `target_icp` → signal. Partir
    de `materialized_signal` puis filtrer après coup laisserait passer les
    lignes non liées, dont personne ne peut prouver le propriétaire.
"""

from __future__ import annotations

import dataclasses

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.persistence.schema import materialized_signal

__all__ = [
    "CustomerBinding",
    "account_for_materialized_signal",
    "customer_binding_for_signal",
    "customer_signal_keys",
    "signal_is_owned_by",
]


@dataclasses.dataclass(frozen=True)
class CustomerBinding:
    """Le rattachement d'un signal à un client — ou son absence, dite explicitement."""

    signal_key: str
    #: L'identifiant porté par le signal, qu'il désigne une ligne réelle ou non.
    target_icp_id: str
    #: `None` quand aucune ligne `target_icp` ne correspond : signal non lié.
    account_id: str | None

    @property
    def is_bound(self) -> bool:
        """Vrai seulement si un compte réel possède ce signal."""
        return self.account_id is not None


def customer_binding_for_signal(
    connection: sa.Connection, *, signal_key: str
) -> CustomerBinding | None:
    """Le rattachement de ce signal, ou `None` si le signal n'existe pas.

    Une jointure externe : le signal est rendu même sans `target_icp`, parce
    qu'un signal non lié est un fait à énoncer, pas une ligne à cacher.
    """
    row = connection.execute(
        sa.select(
            materialized_signal.c.signal_key,
            materialized_signal.c.target_icp_id,
            target_icp.c.account_id,
        )
        .select_from(
            materialized_signal.outerjoin(
                target_icp,
                materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
            )
        )
        .where(materialized_signal.c.signal_key == signal_key)
    ).one_or_none()
    if row is None:
        return None
    return CustomerBinding(row.signal_key, row.target_icp_id, row.account_id)


def account_for_materialized_signal(connection: sa.Connection, *, signal_key: str) -> str | None:
    """Le compte propriétaire, ou `None` — signal inconnu comme signal non lié.

    Les deux cas se confondent volontairement : dans les deux, il n'y a pas de
    client à qui montrer quoi que ce soit.
    """
    binding = customer_binding_for_signal(connection, signal_key=signal_key)
    return binding.account_id if binding is not None else None


def signal_is_owned_by(connection: sa.Connection, *, signal_key: str, account_id: str) -> bool:
    """Ce compte possède-t-il ce signal ? La question est posée à la base.

    `account_id` entre dans le `WHERE` : la propriété est une condition de la
    requête, jamais une vérification postérieure qu'un appelant peut omettre.
    """
    found = connection.execute(
        sa.select(materialized_signal.c.signal_key)
        .select_from(
            materialized_signal.join(
                target_icp,
                materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
            )
        )
        .where(
            materialized_signal.c.signal_key == signal_key,
            target_icp.c.account_id == account_id,
        )
    ).one_or_none()
    return found is not None


def customer_signal_keys(connection: sa.Connection, *, account_id: str) -> tuple[str, ...]:
    """Les signaux de ce compte, en partant du compte.

    C'est la primitive sur laquelle SPEC-012 doit bâtir : la jointure impose le
    compte, donc un signal non lié ne peut pas y entrer. Elle ne rend que des
    clés — le contenu, l'ordre et les filtres du feed appartiennent à SPEC-012.
    """
    rows = connection.execute(
        sa.select(materialized_signal.c.signal_key)
        .select_from(
            target_icp.join(
                materialized_signal,
                materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
            )
        )
        .where(target_icp.c.account_id == account_id)
        .order_by(materialized_signal.c.signal_key)
    ).all()
    return tuple(row.signal_key for row in rows)
