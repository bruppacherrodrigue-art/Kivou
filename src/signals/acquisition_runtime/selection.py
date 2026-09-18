# src/signals/acquisition_runtime/selection.py
"""Sélection déterministe d'une opportunité de production par cycle."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.companies.official_cache import (
    OfficialHolder,
    official_holders_for_awards,
    official_holders_for_opportunities,
)
from signals.companies.schema import saas_company, winner_enrichment_job
from signals.persistence.schema import (
    acquisition_runtime_cycle,
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.supplier_discovery.families import families_for_signal

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
        "FR-01",
        "FR-03",
        "FR-07",
        "FR-15",
        "FR-26",
        "FR-38",
        "FR-42",
        "FR-43",
        "FR-63",
        "FR-69",
        "FR-73",
        "FR-74",
        "FRK11",
        "FRK12",
        "FRK13",
        "FRK14",
        "FRK21",
        "FRK22",
        "FRK23",
        "FRK24",
        "FRK25",
        "FRK26",
        "FRK27",
        "FRK28",
    ),
    "Centre-Val de Loire": (
        "FR-18",
        "FR-28",
        "FR-36",
        "FR-37",
        "FR-41",
        "FR-45",
        "FRB01",
        "FRB02",
        "FRB03",
        "FRB04",
        "FRB05",
        "FRB06",
    ),
}


def region_subdivision_codes(region: str) -> tuple[str, ...]:
    """Return the canonical subdivision scope shared with adjacent workers."""

    try:
        return _REGION_DEPARTMENTS[region]
    except KeyError as exc:
        raise ValueError("production selection requires a known region") from exc

MAX_DYNAMIC_HOLDER_ENRICHMENT = 45


def opportunity_family_keys(
    engine: Engine, *, opportunity_key: str, vertical: str
) -> frozenset[str]:
    with engine.connect() as connection:
        rows = tuple(
            connection.execute(
                sa.select(
                    contract_award.c.cpv_main,
                    contract_award.c.cpv_additional,
                    contract_award.c.lot_title,
                    contract_award.c.title,
                    contract_award.c.description,
                )
                .select_from(
                    opportunity_representation.join(
                        contract_award,
                        opportunity_representation.c.award_key == contract_award.c.award_key,
                    )
                )
                .where(opportunity_representation.c.opportunity_key == opportunity_key)
            )
        )
    return frozenset(
        family.key
        for row in rows
        for family in families_for_signal(
            vertical,
            cpv_codes=tuple(
                value
                for value in (row.cpv_main, *(row.cpv_additional or ()))
                if value
            ),
            object_text=" ".join(
                filter(None, (row.lot_title, row.title, row.description))
            ),
        )
    )


def award_family_keys(
    engine: Engine, *, award_key: str, vertical: str
) -> frozenset[str]:
    """Classify one exact award representation, never its opportunity peers."""

    with engine.connect() as connection:
        row = connection.execute(
            sa.select(
                contract_award.c.cpv_main,
                contract_award.c.cpv_additional,
                contract_award.c.lot_title,
                contract_award.c.title,
                contract_award.c.description,
            ).where(contract_award.c.award_key == award_key)
        ).one_or_none()
    if row is None:
        raise LookupError(award_key)
    return frozenset(
        family.key
        for family in families_for_signal(
            vertical,
            cpv_codes=tuple(
                value
                for value in (row.cpv_main, *(row.cpv_additional or ()))
                if value
            ),
            object_text=" ".join(
                filter(None, (row.lot_title, row.title, row.description))
            ),
        )
    )


def unresolved_dynamic_holder_signal_keys(
    engine: Engine,
    *,
    country: str,
    observed_at: dt.datetime,
    vertical: str,
    region: str,
    limit: int = MAX_DYNAMIC_HOLDER_ENRICHMENT,
) -> tuple[str, ...]:
    """Return a bounded set of otherwise-eligible SIRET-only signal rows."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("selection timestamp must be timezone-aware")
    region_codes = region_subdivision_codes(region)
    if not 1 <= limit <= MAX_DYNAMIC_HOLDER_ENRICHMENT:
        raise ValueError("holder enrichment limit is invalid")
    horizon = observed_at.astimezone(dt.UTC).date()
    decision_date = sa.func.coalesce(
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
    )
    latest = sa.func.max(decision_date).label("latest")
    official_holder_name = sa.func.nullif(
        sa.func.trim(sa.func.coalesce(saas_company.c.official_name, "")), ""
    )
    official_holder_is_resolved = sa.and_(
        official_holder_name.isnot(None),
        saas_company.c.official_source == "official_register",
        saas_company.c.official_name != materialized_signal.c.winner_identifier_value,
    )
    statement = (
        sa.select(materialized_signal.c.signal_key, latest)
        .select_from(
            materialized_signal.join(
                opportunity_representation,
                opportunity_representation.c.opportunity_key
                == materialized_signal.c.opportunity_key,
            )
            .join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            )
            .join(source_event, contract_award.c.event_key == source_event.c.event_key)
            .outerjoin(
                for_you_sentence,
                sa.and_(
                    for_you_sentence.c.signal_key == materialized_signal.c.signal_key,
                    for_you_sentence.c.signal_fingerprint
                    == materialized_signal.c.content_fingerprint,
                ),
            )
            .join(
                winner_enrichment_job,
                winner_enrichment_job.c.signal_key == materialized_signal.c.signal_key,
            )
            .outerjoin(
                saas_company,
                saas_company.c.identity_fingerprint
                == materialized_signal.c.company_identity_fingerprint,
            )
        )
        .where(
            source_event.c.source_country == country,
            decision_date >= horizon - dt.timedelta(days=30),
            decision_date <= horizon,
            contract_award.c.amount >= 50000,
            contract_award.c.winner_status == "identified",
            sa.func.lower(sa.func.coalesce(materialized_signal.c.winner_identifier_scheme, ""))
            == "siret",
            sa.func.length(materialized_signal.c.winner_identifier_value) == 14,
            materialized_signal.c.winner_name == materialized_signal.c.winner_identifier_value,
            sa.func.nullif(sa.func.trim(sa.func.coalesce(contract_award.c.title, "")), "").isnot(
                None
            ),
            materialized_signal.c.inferred_trade_domain == vertical,
            contract_award.c.place_of_performance["subdivision_code"]
            .as_string()
            .in_(region_codes),
            sa.or_(
                for_you_sentence.c.model_fit.is_(None),
                for_you_sentence.c.model_fit != "none",
            ),
            sa.not_(official_holder_is_resolved),
            sa.or_(
                winner_enrichment_job.c.status == "pending",
                sa.and_(
                    winner_enrichment_job.c.status == "failed",
                    winner_enrichment_job.c.attempt_count < 3,
                ),
            ),
        )
        .group_by(materialized_signal.c.signal_key)
        .order_by(latest.desc(), materialized_signal.c.signal_key)
        .limit(limit)
    )
    with engine.connect() as connection:
        return tuple(str(row.signal_key) for row in connection.execute(statement))


def resolved_holder_for_opportunity(
    engine: Engine,
    opportunity_key: str,
    *,
    source_award_key: str | None = None,
) -> OfficialHolder | None:
    """Read the official holder cache without altering the public source fact."""
    with engine.connect() as connection:
        if source_award_key is not None:
            return official_holders_for_awards(
                connection,
                ((opportunity_key, source_award_key),),
            ).get((opportunity_key, source_award_key))
        return official_holders_for_opportunities(
            connection, (opportunity_key,)
        ).get(opportunity_key)


def resolved_holder_name_for_opportunity(engine: Engine, opportunity_key: str) -> str | None:
    """Backward-compatible holder name accessor."""
    holder = resolved_holder_for_opportunity(engine, opportunity_key)
    return None if holder is None else holder.name


def select_production_opportunity_key(
    engine: Engine,
    *,
    country: str,
    observed_at: dt.datetime,
    vertical: str | None = None,
    region: str | None = None,
    family_key: str | None = None,
    pinned_opportunity_key: str | None = None,
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
    decision_date = sa.func.coalesce(
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
    )
    latest = sa.func.max(decision_date).label("latest")
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
        played_procedures = (
            sa.select(opportunity_representation.c.award_key)
            .select_from(
                opportunity_representation.join(
                    acquisition_runtime_cycle,
                    acquisition_runtime_cycle.c.opportunity_key
                    == opportunity_representation.c.opportunity_key,
                )
            )
            .where(sa.func.date(acquisition_runtime_cycle.c.started_at) == horizon)
        )
        region_codes = _REGION_DEPARTMENTS[region]
        cycle_filters = (
            (
                opportunity_representation.c.opportunity_key.notin_(already_played),
                opportunity_representation.c.award_key.notin_(played_procedures),
            )
            if pinned_opportunity_key is None
            else (
                opportunity_representation.c.opportunity_key == pinned_opportunity_key,
            )
        )
        published_holder_name = sa.func.nullif(
            sa.func.trim(sa.func.coalesce(materialized_signal.c.winner_name, "")),
            "",
        )
        official_holder_name = sa.func.nullif(
            sa.func.trim(sa.func.coalesce(saas_company.c.official_name, "")),
            "",
        )
        official_holder_is_resolved = sa.and_(
            official_holder_name.isnot(None),
            saas_company.c.official_source == "official_register",
            saas_company.c.official_name != materialized_signal.c.winner_identifier_value,
        )
        published_holder_is_named = sa.and_(
            published_holder_name.isnot(None),
            sa.or_(
                sa.func.lower(sa.func.coalesce(materialized_signal.c.winner_identifier_scheme, ""))
                != "siret",
                materialized_signal.c.winner_name != materialized_signal.c.winner_identifier_value,
            ),
        )
        statement = (
            sa.select(opportunity_representation.c.opportunity_key, latest)
            .select_from(
                opportunity_representation.join(
                    materialized_signal,
                    materialized_signal.c.opportunity_key
                    == opportunity_representation.c.opportunity_key,
                )
                .join(
                    contract_award,
                    opportunity_representation.c.award_key == contract_award.c.award_key,
                )
                .join(
                    source_event,
                    contract_award.c.event_key == source_event.c.event_key,
                )
                .outerjoin(
                    for_you_sentence,
                    sa.and_(
                        for_you_sentence.c.signal_key == materialized_signal.c.signal_key,
                        for_you_sentence.c.signal_fingerprint
                        == materialized_signal.c.content_fingerprint,
                    ),
                )
                .outerjoin(
                    saas_company,
                    saas_company.c.identity_fingerprint
                    == materialized_signal.c.company_identity_fingerprint,
                )
            )
            .where(
                source_event.c.source_country == country,
                decision_date >= horizon - dt.timedelta(days=30),
                decision_date <= horizon,
                contract_award.c.amount >= 50000,
                contract_award.c.winner_status == "identified",
                sa.or_(published_holder_is_named, official_holder_is_resolved),
                sa.func.nullif(
                    sa.func.trim(sa.func.coalesce(contract_award.c.title, "")), ""
                ).isnot(None),
                materialized_signal.c.inferred_trade_domain == vertical,
                contract_award.c.place_of_performance["subdivision_code"]
                .as_string()
                .in_(region_codes),
                sa.or_(
                    for_you_sentence.c.model_fit.is_(None),
                    for_you_sentence.c.model_fit != "none",
                ),
                *cycle_filters,
            )
            .group_by(opportunity_representation.c.opportunity_key)
            .order_by(latest.desc(), opportunity_representation.c.opportunity_key.asc())
            .limit(1 if pinned_opportunity_key else (100 if family_key else 1))
        )
        with engine.connect() as connection:
            rows = tuple(connection.execute(statement))
        if family_key is None:
            return None if not rows else str(rows[0].opportunity_key)
        for row in rows:
            opportunity_key = str(row.opportunity_key)
            matched_families = opportunity_family_keys(
                engine,
                opportunity_key=opportunity_key,
                vertical=vertical,
            )
            if (
                matched_families == {family_key}
                or (
                    pinned_opportunity_key == opportunity_key
                    and family_key in matched_families
                )
            ):
                return opportunity_key
        return None
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


__all__ = [
    "MAX_DYNAMIC_HOLDER_ENRICHMENT",
    "opportunity_family_keys",
    "resolved_holder_for_opportunity",
    "resolved_holder_name_for_opportunity",
    "select_production_opportunity_key",
    "unresolved_dynamic_holder_signal_keys",
]
