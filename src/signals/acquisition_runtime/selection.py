# src/signals/acquisition_runtime/selection.py
"""Sélection déterministe d'une opportunité de production par cycle."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import (
    acquisition_runtime_cycle,
    contract_award,
    opportunity_representation,
    source_event,
)


def select_production_opportunity_key(
    engine: Engine, *, country: str, observed_at: dt.datetime
) -> str | None:
    """La plus récente opportunité du pays jamais retenue par un cycle.

    Déterministe : à base identique, deux appels rendent la même clé. Le
    départage se fait sur la clé elle-même, pour que deux publications de même
    date ne dépendent jamais de l'ordre de lecture du moteur.

    La preuve qu'une opportunité a déjà servi est l'enregistrement durable des
    cycles, jamais un fichier ni une mémoire de processus.
    """

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("selection timestamp must be timezone-aware")
    horizon = observed_at.astimezone(dt.UTC).date()
    already_played = sa.select(acquisition_runtime_cycle.c.opportunity_key)
    latest = sa.func.max(source_event.c.published_on).label("latest")
    statement = (
        sa.select(opportunity_representation.c.opportunity_key, latest)
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            ).join(
                source_event,
                contract_award.c.event_key == source_event.c.event_key,
            )
        )
        .where(
            source_event.c.source_country == country,
            source_event.c.published_on.isnot(None),
            source_event.c.published_on <= horizon,
            opportunity_representation.c.opportunity_key.notin_(already_played),
        )
        .group_by(opportunity_representation.c.opportunity_key)
        .order_by(latest.desc(), opportunity_representation.c.opportunity_key.asc())
        .limit(1)
    )
    with engine.connect() as connection:
        row = connection.execute(statement).first()
    return None if row is None else str(row.opportunity_key)


__all__ = ["select_production_opportunity_key"]
