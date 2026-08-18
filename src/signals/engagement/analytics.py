"""L'analytique produit — ce que Kivou observe de lui-même, et rien de plus.

Elle est SERVEUR, jamais cliente (§11)
──────────────────────────────────────
Il n'existe aucun `POST /analytics/event`. Un point d'entrée où le
navigateur choisirait le nom et le contenu de l'événement produirait des
chiffres qu'un client peut fabriquer — et une activation qu'on ne pourrait
plus croire. Les événements naissent d'actions serveur déjà authentifiées.

Elle est APPEND-ONLY
────────────────────
Une ligne écrite n'est jamais modifiée. C'est ce qui permet de recompter un
mois plus tard sans dépendre de l'état courant, et de distinguer un client
qui a changé d'avis d'un client qui n'en a jamais eu.

Observation répétable ≠ action métier idempotente (§12)
──────────────────────────────────────────────────────
Ouvrir deux fois un signal, ce sont deux consultations : la répétition est
l'information. Marquer deux fois « contacté », c'est UNE action commerciale :
la répétition est un artefact de clic. Les deux ne s'enregistrent donc pas
de la même façon, et c'est l'appelant qui tranche — le contact n'est
enregistré qu'au passage de `NULL` à une date.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import secrets
from typing import Any

import sqlalchemy as sa

from signals.engagement.schema import (
    ACTIVATION_EVENT_TYPES,
    COMMERCIAL_ACTION_EVENT,
    PRODUCT_EVENT_TYPES,
    product_event,
)

ANALYTICS_VERSION = "kivou-analytics-v0.1"

#: §13 — la fenêtre de l'étoile polaire. Trente jours, parce que c'est
#: l'horizon d'un cycle commercial B2B court et celui de la facturation.
NORTH_STAR_WINDOW_DAYS = 30

#: §9 — ce qu'aucune propriété d'événement n'a le droit de contenir. Le contrôle
#: porte sur les NOMS : une propriété nommée `ip` ou `token` est refusée à
#: l'écriture, plutôt que découverte six mois plus tard dans un export.
FORBIDDEN_PROPERTY_MARKERS: tuple[str, ...] = (
    "password",
    "token",
    "secret",
    "session",
    "api_key",
    "ip_address",
    "user_agent",
    "evidence",
    "excerpt",
    "raw_",
    "payload",
    "email",
    "card",
)


class UnknownEventType(ValueError):
    """§10 — un nom d'événement hors vocabulaire. Refusé, jamais inventé."""


class ForbiddenEventProperty(ValueError):
    """Une propriété que l'analytique n'a pas le droit de conserver (§9)."""


def _identifier() -> str:
    return f"evt_{base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip('=')}"


def check_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Refuse une propriété dont le NOM annonce une donnée interdite."""
    for name in properties:
        lowered = name.lower()
        for marker in FORBIDDEN_PROPERTY_MARKERS:
            if marker in lowered:
                raise ForbiddenEventProperty(
                    f"propriété d'événement interdite : {name!r} (motif {marker!r})"
                )
    return properties


def record(
    connection: sa.Connection,
    *,
    account_id: str,
    event_type: str,
    occurred_at: dt.datetime,
    user_id: str | None = None,
    target_icp_id: str | None = None,
    signal_key: str | None = None,
    properties: dict[str, Any] | None = None,
) -> str:
    """Écrit un événement produit. Rend son identifiant.

    `occurred_at` est explicite : aucune horloge n'est lue ici, sinon une
    reprise de traitement déplacerait des événements dans le temps.
    """
    if event_type not in PRODUCT_EVENT_TYPES:
        raise UnknownEventType(f"type d'événement inconnu : {event_type!r}")
    payload = check_properties(dict(properties or {}))
    event_id = _identifier()
    connection.execute(
        sa.insert(product_event).values(
            event_id=event_id,
            account_id=account_id,
            user_id=user_id,
            target_icp_id=target_icp_id,
            signal_key=signal_key,
            event_type=event_type,
            occurred_at=occurred_at,
            properties=payload,
            created_at=occurred_at,
        )
    )
    return event_id


# ─── §14 — les quelques questions auxquelles il faut savoir répondre ───────────


def _window(start: dt.datetime, end: dt.datetime) -> sa.ColumnElement[bool]:
    return sa.and_(product_event.c.occurred_at >= start, product_event.c.occurred_at < end)


def _distinct_accounts(
    connection: sa.Connection, *, event_types: tuple[str, ...], start: dt.datetime, end: dt.datetime
) -> int:
    return connection.execute(
        sa.select(sa.func.count(sa.distinct(product_event.c.account_id))).where(
            product_event.c.event_type.in_(event_types), _window(start, end)
        )
    ).scalar_one()


def activated_accounts(connection: sa.Connection, *, start: dt.datetime, end: dt.datetime) -> int:
    """§13 — les comptes ACTIVÉS produit sur la période.

    Une inscription n'est pas une activation. Un compte l'est quand il a jugé au
    moins un signal pertinent, ou contacté au moins une entreprise : c'est le
    moment où le produit a servi à quelque chose.
    """
    return _distinct_accounts(connection, event_types=ACTIVATION_EVENT_TYPES, start=start, end=end)


def accounts_with_commercial_action(
    connection: sa.Connection, *, start: dt.datetime, end: dt.datetime
) -> int:
    """Les comptes ayant réellement contacté une entreprise sur la période."""
    return _distinct_accounts(
        connection, event_types=(COMMERCIAL_ACTION_EVENT,), start=start, end=end
    )


def north_star(connection: sa.Connection, *, as_of: dt.datetime) -> int:
    """§13 — l'étoile polaire : comptes distincts ayant contacté sur 30 jours.

    Ni connexions, ni pages vues, ni inscriptions, ni e-mails envoyés. Ces
    chiffres montent tout seuls et ne disent rien ; celui-ci ne monte que si le
    produit a provoqué une démarche commerciale réelle.
    """
    return accounts_with_commercial_action(
        connection, start=as_of - dt.timedelta(days=NORTH_STAR_WINDOW_DAYS), end=as_of
    )


def feedback_breakdown(
    connection: sa.Connection, *, start: dt.datetime, end: dt.datetime
) -> dict[str, int]:
    """Combien de jugements positifs, combien de négatifs."""
    rows = connection.execute(
        sa.select(product_event.c.event_type, sa.func.count())
        .where(
            product_event.c.event_type.in_(
                ("signal_feedback_relevant", "signal_feedback_not_relevant")
            ),
            _window(start, end),
        )
        .group_by(product_event.c.event_type)
    ).all()
    # La comparaison porte sur le type COMPLET : `signal_feedback_not_relevant`
    # se termine lui aussi par `_relevant`, et un test de suffixe ferait
    # silencieusement compter les refus comme des accords.
    counts = {"relevant": 0, "not_relevant": 0}
    by_type = {
        "signal_feedback_relevant": "relevant",
        "signal_feedback_not_relevant": "not_relevant",
    }
    for event_type, count in rows:
        counts[by_type[event_type]] = count
    return counts


def negative_reason_breakdown(
    connection: sa.Connection, *, start: dt.datetime, end: dt.datetime
) -> dict[str, int]:
    """La répartition des six raisons de refus — la matière première de la R&D.

    Lue depuis les ÉVÉNEMENTS et non depuis l'état courant : un client qui
    change d'avis ne doit pas effacer la raison qu'il avait donnée.
    """
    rows = connection.execute(
        sa.select(product_event.c.properties).where(
            product_event.c.event_type == "signal_feedback_not_relevant", _window(start, end)
        )
    ).scalars()
    counts: dict[str, int] = {}
    for properties in rows:
        reason = (properties or {}).get("reason_code")
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def event_count(
    connection: sa.Connection, *, event_type: str, start: dt.datetime, end: dt.datetime
) -> int:
    return connection.execute(
        sa.select(sa.func.count())
        .select_from(product_event)
        .where(product_event.c.event_type == event_type, _window(start, end))
    ).scalar_one()


def signals_contacted_count(
    connection: sa.Connection, *, start: dt.datetime, end: dt.datetime
) -> int:
    return connection.execute(
        sa.select(sa.func.count(sa.distinct(product_event.c.signal_key))).where(
            product_event.c.event_type == COMMERCIAL_ACTION_EVENT, _window(start, end)
        )
    ).scalar_one()


def relevant_signal_count(
    connection: sa.Connection, *, start: dt.datetime, end: dt.datetime
) -> int:
    return connection.execute(
        sa.select(sa.func.count(sa.distinct(product_event.c.signal_key))).where(
            product_event.c.event_type == "signal_feedback_relevant", _window(start, end)
        )
    ).scalar_one()


@dataclasses.dataclass(frozen=True)
class ProductSnapshot:
    """Les quelques chiffres qui disent si le produit sert à quelque chose."""

    start: dt.datetime
    end: dt.datetime
    activated_accounts: int
    accounts_with_commercial_action: int
    feedback: dict[str, int]
    negative_reasons: dict[str, int]
    signals_contacted: int
    relevant_signals: int


def snapshot(connection: sa.Connection, *, start: dt.datetime, end: dt.datetime) -> ProductSnapshot:
    return ProductSnapshot(
        start=start,
        end=end,
        activated_accounts=activated_accounts(connection, start=start, end=end),
        accounts_with_commercial_action=accounts_with_commercial_action(
            connection, start=start, end=end
        ),
        feedback=feedback_breakdown(connection, start=start, end=end),
        negative_reasons=negative_reason_breakdown(connection, start=start, end=end),
        signals_contacted=signals_contacted_count(connection, start=start, end=end),
        relevant_signals=relevant_signal_count(connection, start=start, end=end),
    )
