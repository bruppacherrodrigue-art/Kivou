# src/signals/acquisition_runtime/selection.py
"""Sélection déterministe d'une opportunité de production par cycle."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import (
    acquisition_runtime_cycle,
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
    source_event,
)

# Amorçage de production (2026-09-01) : le contrôle Policy est maintenant
# ASSISTED, exécutable — un cycle peut donc s'arrêter WAITING (accord humain
# requis) au lieu d'être forcé DENIED comme sous l'ancien amorçage SHADOW.
# `runner.py:726`/`:413` : un stage WAITING donne un cycle de statut WAITING,
# ni SUCCEEDED ni SUPPRESSED, donc jamais retiré par l'exclusion terminale
# ci-dessous. Sans un refroidissement séparé, un cycle parqué en attente
# d'approbation humaine — ou simplement interrompu en vol — serait resélectionné
# à chaque tir horaire du timer et monopoliserait le vivier au lieu de le
# libérer pour la prochaine opportunité.
SELECTION_COOLDOWN = dt.timedelta(hours=20)

_REGION_DEPARTMENTS: dict[str, tuple[str, ...]] = {
    "Auvergne-Rhône-Alpes": (
        "FR-01", "FR-03", "FR-07", "FR-15", "FR-26", "FR-38",
        "FR-42", "FR-43", "FR-63", "FR-69", "FR-73", "FR-74",
        "FRK11", "FRK12", "FRK13", "FRK14", "FRK21", "FRK22",
        "FRK23", "FRK24", "FRK25", "FRK26", "FRK27", "FRK28",
    ),
}


def select_production_opportunity_key(
    engine: Engine,
    *,
    country: str,
    observed_at: dt.datetime,
    vertical: str | None = None,
    region: str | None = None,
) -> str | None:
    """La plus récente opportunité du pays ni retirée ni en refroidissement.

    Déterministe : à base identique, deux appels rendent la même clé. Le
    départage se fait sur la clé elle-même, pour que deux publications de même
    date ne dépendent jamais de l'ordre de lecture du moteur.

    Deux règles retirent une opportunité du vivier :

    1. Un cycle porté à un état TERMINAL (SUCCEEDED, SUPPRESSED) l'exclut
       pour toujours.
    2. Un cycle dont `updated_at` a moins de `SELECTION_COOLDOWN` (20 heures)
       l'exclut temporairement, quel que soit son statut — y compris WAITING,
       FAILED, CANCELLED ou encore en vol. Un cycle parqué en attente d'un
       accord humain (ASSISTED, cf. `policy_bootstrap.py`) ne doit pas
       monopoliser le vivier à chaque tir horaire ; passé le refroidissement,
       il redevient sélectionnable et
       `AcquisitionRuntimeStore.resume_or_create_cycle` le reprend plutôt que
       d'en créer un nouveau — l'exclure à jamais empêcherait cette reprise
       au lieu de la protéger. Le refroidissement est volontairement grossier
       (il ne distingue pas *pourquoi* un cycle attend) : un cycle en échec
       revient dès le lendemain, rien n'est jamais exclu de façon permanente
       par cette règle, et 20 heures reste sous la cadence quotidienne visée
       tout en tolérant le timer horaire.
    """

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("selection timestamp must be timezone-aware")
    observed_at = observed_at.astimezone(dt.UTC)
    horizon = observed_at.date()
    cooldown_floor = observed_at - SELECTION_COOLDOWN
    # Le filtre NOT NULL est défensif : un NULL dans la sous-requête ferait
    # taire le NOT IN entier. Un cycle est retiré du vivier s'il est
    # TERMINAL (pour toujours), ou si sa dernière mise à jour tombe dans la
    # fenêtre de refroidissement (temporairement, quel que soit son statut) —
    # sinon un cycle parqué en attente d'approbation monopoliserait le vivier
    # à chaque tir horaire au lieu de le libérer.
    already_played = sa.select(acquisition_runtime_cycle.c.opportunity_key).where(
        acquisition_runtime_cycle.c.opportunity_key.isnot(None),
        sa.or_(
            acquisition_runtime_cycle.c.status.in_(("SUCCEEDED", "SUPPRESSED")),
            acquisition_runtime_cycle.c.updated_at > cooldown_floor,
        ),
    )
    latest = sa.func.max(source_event.c.published_on).label("latest")
    if vertical is not None or region is not None:
        if not (
            sa.inspect(engine).has_table(materialized_signal.name)
            and sa.inspect(engine).has_table(for_you_sentence.name)
        ):
            # Legacy isolated test databases predate the signal projection;
            # production databases always carry both tables.
            return select_production_opportunity_key(
                engine, country=country, observed_at=observed_at
            )
        if not vertical or not region or region not in _REGION_DEPARTMENTS:
            raise ValueError("production selection requires a known vertical and region")
        played_procedures = sa.select(opportunity_representation.c.award_key).select_from(
            opportunity_representation.join(
                acquisition_runtime_cycle,
                acquisition_runtime_cycle.c.opportunity_key
                == opportunity_representation.c.opportunity_key,
            )
        ).where(sa.func.date(acquisition_runtime_cycle.c.started_at) == horizon)
        region_codes = _REGION_DEPARTMENTS[region]
        statement = (
            sa.select(opportunity_representation.c.opportunity_key, latest)
            .select_from(
                opportunity_representation.join(
                    materialized_signal,
                    materialized_signal.c.opportunity_key
                    == opportunity_representation.c.opportunity_key,
                ).join(
                    contract_award,
                    opportunity_representation.c.award_key == contract_award.c.award_key,
                ).join(
                    source_event,
                    contract_award.c.event_key == source_event.c.event_key,
                ).join(
                    for_you_sentence,
                    sa.and_(
                        for_you_sentence.c.signal_key == materialized_signal.c.signal_key,
                        for_you_sentence.c.signal_fingerprint
                        == materialized_signal.c.content_fingerprint,
                    ),
                )
            )
            .where(
                source_event.c.source_country == country,
                source_event.c.published_on >= horizon - dt.timedelta(days=30),
                source_event.c.published_on <= horizon,
                contract_award.c.amount >= 50000,
                contract_award.c.winner_status == "identified",
                sa.func.nullif(sa.func.trim(sa.func.coalesce(materialized_signal.c.winner_name, "")), "").isnot(None),
                sa.or_(
                    sa.func.lower(sa.func.coalesce(materialized_signal.c.winner_identifier_scheme, "")) != "siret",
                    materialized_signal.c.winner_name != materialized_signal.c.winner_identifier_value,
                ),
                sa.func.nullif(sa.func.trim(sa.func.coalesce(contract_award.c.title, "")), "").isnot(None),
                materialized_signal.c.inferred_trade_domain == vertical,
                contract_award.c.place_of_performance["subdivision_code"].as_string().in_(region_codes),
                for_you_sentence.c.model_fit.isnot(None),
                for_you_sentence.c.model_fit != "none",
                opportunity_representation.c.opportunity_key.notin_(already_played),
                opportunity_representation.c.award_key.notin_(played_procedures),
            )
            .group_by(opportunity_representation.c.opportunity_key)
            .order_by(latest.desc(), opportunity_representation.c.opportunity_key.asc())
            .limit(1)
        )
        with engine.connect() as connection:
            row = connection.execute(statement).first()
        return None if row is None else str(row.opportunity_key)
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
