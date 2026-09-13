"""Bounded selection for model enrichment of newly materialized winners."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa

from signals.companies.active_scope import active_account_signal_exists
from signals.companies.schema import winner_enrichment_job
from signals.persistence.schema import contract_award, materialized_signal, source_event

MAX_WINNER_MODEL_BATCH = 100
RECENT_SIGNAL_WINDOW = dt.timedelta(days=30)


@dataclass(frozen=True)
class WinnerEnrichmentCandidate:
    signal_key: str
    holder_key: str


def _holder_key() -> sa.ColumnElement[str]:
    identifier = materialized_signal.c.winner_identifier_value
    return sa.case(
        (sa.func.length(identifier) == 14, sa.func.substr(identifier, 1, 9)),
        (sa.func.length(identifier) == 9, identifier),
        else_=sa.func.coalesce(
            materialized_signal.c.company_identity_fingerprint,
            winner_enrichment_job.c.identity_fingerprint,
            winner_enrichment_job.c.signal_key,
        ),
    )


def select_winner_enrichment_candidates(
    connection: sa.Connection,
    *,
    now: dt.datetime,
    activated_at: dt.datetime,
    limit: int = 25,
) -> tuple[WinnerEnrichmentCandidate, ...]:
    """Return one pending job per recent active holder after activation."""

    if now.tzinfo is None or activated_at.tzinfo is None:
        raise ValueError("winner enrichment clocks must be timezone-aware")
    if not 1 <= limit <= MAX_WINNER_MODEL_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_WINNER_MODEL_BATCH}")
    effective_date = sa.func.coalesce(
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
        source_event.c.published_on,
    )
    holder_key = _holder_key()
    ranked = (
        sa.select(
            winner_enrichment_job.c.signal_key.label("signal_key"),
            holder_key.label("holder_key"),
            sa.func.row_number()
            .over(
                partition_by=holder_key,
                order_by=(
                    winner_enrichment_job.c.queued_at,
                    winner_enrichment_job.c.signal_key,
                ),
            )
            .label("holder_rank"),
            winner_enrichment_job.c.queued_at.label("queued_at"),
        )
        .select_from(
            winner_enrichment_job.join(
                materialized_signal,
                winner_enrichment_job.c.signal_key == materialized_signal.c.signal_key,
            )
            .join(
                contract_award,
                materialized_signal.c.materialization_award_key == contract_award.c.award_key,
            )
            .join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(
            winner_enrichment_job.c.status == "pending",
            winner_enrichment_job.c.queued_at >= activated_at,
            active_account_signal_exists(winner_enrichment_job.c.signal_key),
            effective_date >= now.date() - RECENT_SIGNAL_WINDOW,
            effective_date <= now.date(),
        )
        .subquery("ranked_winner_enrichment")
    )
    rows = connection.execute(
        sa.select(ranked.c.signal_key, ranked.c.holder_key)
        .where(ranked.c.holder_rank == 1)
        .order_by(ranked.c.queued_at, ranked.c.signal_key)
        .limit(limit)
    )
    return tuple(
        WinnerEnrichmentCandidate(signal_key=row.signal_key, holder_key=row.holder_key)
        for row in rows
    )


__all__ = [
    "MAX_WINNER_MODEL_BATCH",
    "RECENT_SIGNAL_WINDOW",
    "WinnerEnrichmentCandidate",
    "select_winner_enrichment_candidates",
]
