"""Les trois signaux offerts — donnés une fois, pas prêtés chaque jour.

Pourquoi persister les déblocages
─────────────────────────────────
« Les 3 signaux les plus récents » serait un produit gratuit permanent :
chaque matin, trois nouvelles opportunités, sans jamais payer. Kivou offre
donc **trois signaux nommés**, débloqués une fois pour toutes et conservés.

Comment ils sont choisis
────────────────────────
Par la file d'attente de SPEC-012 : propriété du compte, profil actif,
identité affichable, sémantique d'événement courante, ordre déterministe.
Aucune règle de sélection nouvelle — celle du feed suffit, et en inventer
une seconde créerait deux vérités sur « ce qui vaut la peine ».

Ce qui se passe s'il y en a moins de trois
─────────────────────────────────────────
On donne ce qu'il y a. Les places restantes se remplissent plus tard, quand
des signaux éligibles apparaissent. Une fois les trois attribués, ils ne
tournent plus : un signal offert reste offert.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.accounts.service import landing_signal_keys
from signals.billing.catalogue import DISCOVERY_GRANT_LIMIT
from signals.billing.schema import discovery_signal_grant


@dataclasses.dataclass(frozen=True)
class Grant:
    account_id: str
    signal_key: str
    opportunity_key: str
    granted_at: dt.datetime


def granted_signal_keys(connection: sa.Connection, *, account_id: str) -> frozenset[str]:
    rows = connection.execute(
        sa.select(discovery_signal_grant.c.signal_key).where(
            discovery_signal_grant.c.account_id == account_id
        )
    ).all()
    return frozenset(row.signal_key for row in rows)


def grants(connection: sa.Connection, *, account_id: str) -> tuple[Grant, ...]:
    rows = connection.execute(
        sa.select(discovery_signal_grant)
        .where(discovery_signal_grant.c.account_id == account_id)
        .order_by(discovery_signal_grant.c.granted_at, discovery_signal_grant.c.signal_key)
    ).all()
    return tuple(
        Grant(row.account_id, row.signal_key, row.opportunity_key, _aware(row.granted_at))
        for row in rows
    )


def remaining_slots(connection: sa.Connection, *, account_id: str) -> int:
    used = connection.execute(
        sa.select(sa.func.count())
        .select_from(discovery_signal_grant)
        .where(discovery_signal_grant.c.account_id == account_id)
    ).scalar_one()
    return max(0, DISCOVERY_GRANT_LIMIT - used)


def grant_up_to_limit(
    connection: sa.Connection,
    *,
    account_id: str,
    candidates: list,
    now: dt.datetime,
) -> tuple[str, ...]:
    """Débloque les premiers candidats éligibles, jusqu'au plafond.

    `candidates` est la page de feed déjà ordonnée et filtrée par SPEC-012 :
    cette fonction ne rejuge rien, elle prend dans l'ordre. Les signaux déjà
    débloqués sont sautés sans consommer de place.
    """
    slots = remaining_slots(connection, account_id=account_id)
    if slots <= 0:
        return ()

    # Le signal d'atterrissage est déjà ouvert par `feed_access` : le compter
    # ici lui ferait consommer une des trois places offertes, alors qu'il a été
    # promis au prospect avant même la création du compte.
    already = granted_signal_keys(connection, account_id=account_id) | landing_signal_keys(
        connection, account_id=account_id
    )
    newly: list[str] = []
    for item in candidates:
        if slots <= 0:
            break
        key = item.signal.signal_key
        if key in already:
            continue
        connection.execute(
            sa.insert(discovery_signal_grant).values(
                account_id=account_id,
                signal_key=key,
                opportunity_key=item.signal.opportunity_key,
                granted_at=now,
                created_at=now,
            )
        )
        newly.append(key)
        already = already | {key}
        slots -= 1
    return tuple(newly)


def _aware(value) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
