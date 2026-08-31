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
    """La plus récente opportunité du pays non retirée par un cycle terminal.

    Déterministe : à base identique, deux appels rendent la même clé. Le
    départage se fait sur la clé elle-même, pour que deux publications de même
    date ne dépendent jamais de l'ordre de lecture du moteur.

    Seul un cycle porté à un état TERMINAL (SUCCEEDED, SUPPRESSED) retire une
    opportunité du vivier. Un cycle FAILED, CANCELLED ou encore en vol la
    laisse sélectionnable, parce que `AcquisitionRuntimeStore.resume_or_create_cycle`
    reprend ce cycle plutôt que d'en créer un nouveau — l'exclure à jamais
    empêcherait cette reprise au lieu de la protéger.
    """

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("selection timestamp must be timezone-aware")
    horizon = observed_at.astimezone(dt.UTC).date()
    # Seuls les cycles TERMINAUX retirent une opportunité du vivier. Un cycle
    # FAILED, CANCELLED ou encore en vol est REPRIS par
    # `AcquisitionRuntimeStore.resume_or_create_cycle` — l'exclure à jamais
    # empêcherait la reprise au lieu de la protéger. Le filtre NOT NULL est
    # défensif : un NULL dans la sous-requête ferait taire le NOT IN entier.
    already_played = sa.select(acquisition_runtime_cycle.c.opportunity_key).where(
        acquisition_runtime_cycle.c.opportunity_key.isnot(None),
        acquisition_runtime_cycle.c.status.in_(("SUCCEEDED", "SUPPRESSED")),
    )
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
