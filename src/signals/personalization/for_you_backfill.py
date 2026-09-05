"""Backfill explicite et borné des phrases « Pour vous ».

Usage : ``python -m signals.personalization.for_you_backfill --limit 50 --since 2026-08-01``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections.abc import Sequence

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.documents.providers import text_generator_from_environment
from signals.persistence.database import create_database_engine
from signals.persistence.schema import for_you_sentence, materialized_signal
from signals.personalization.for_you import POLICY_VERSION, ForYouProvider
from signals.personalization.for_you_store import enqueue_stored_for_you_sentence
from signals.personalization.for_you_worker import (
    DEFAULT_CONCURRENCY,
    DEFAULT_DAILY_LIMIT,
    ForYouWorker,
    ForYouWorkerReport,
)

DATABASE_URL_ENV = "KIVOU_DATABASE_URL"
CONCURRENCY_ENV = "KIVOU_FOR_YOU_CONCURRENCY"
DAILY_LIMIT_ENV = "KIVOU_FOR_YOU_DAILY_LIMIT"


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m signals.personalization.for_you_backfill")
    parser.add_argument("--limit", required=True, type=_positive)
    parser.add_argument("--since", required=True, type=dt.date.fromisoformat)
    return parser.parse_args(arguments)


def backfill(
    engine: sa.Engine,
    provider: ForYouProvider,
    *,
    limit: int,
    since: dt.date,
    now: dt.datetime,
    concurrency: int = DEFAULT_CONCURRENCY,
    daily_limit: int = DEFAULT_DAILY_LIMIT,
) -> ForYouWorkerReport:
    if limit < 1:
        raise ValueError("limit must be positive")
    current_exists = sa.exists(
        sa.select(sa.literal(1)).where(
            for_you_sentence.c.signal_key == materialized_signal.c.signal_key,
            for_you_sentence.c.target_icp_id == materialized_signal.c.target_icp_id,
            for_you_sentence.c.signal_fingerprint == materialized_signal.c.content_fingerprint,
            for_you_sentence.c.policy_version == POLICY_VERSION,
        )
    )
    with engine.begin() as connection:
        keys = connection.scalars(
            sa.select(materialized_signal.c.signal_key)
            .select_from(
                materialized_signal.join(
                    target_icp,
                    materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
                )
            )
            .where(
                materialized_signal.c.invalidated_at.is_(None),
                materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
                materialized_signal.c.materialized_at >= since,
                ~current_exists,
            )
            .order_by(
                materialized_signal.c.materialized_at.desc(), materialized_signal.c.signal_key
            )
            .limit(limit)
        ).all()
        queued = tuple(
            result
            for key in keys
            if (result := enqueue_stored_for_you_sentence(connection, signal_key=key, now=now))
            is not None
        )
    return ForYouWorker(engine, provider, concurrency=concurrency, daily_limit=daily_limit).run(
        now=now, limit=limit, for_you_ids=queued
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = parse_args(arguments)
    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        raise SystemExit(f"{DATABASE_URL_ENV} is required")
    concurrency = _positive(os.environ.get(CONCURRENCY_ENV, str(DEFAULT_CONCURRENCY)))
    daily_limit = _positive(os.environ.get(DAILY_LIMIT_ENV, str(DEFAULT_DAILY_LIMIT)))
    provider = text_generator_from_environment()
    try:
        report = backfill(
            create_database_engine(database_url),
            provider,
            limit=parsed.limit,
            since=parsed.since,
            now=dt.datetime.now(dt.UTC),
            concurrency=concurrency,
            daily_limit=daily_limit,
        )
    finally:
        provider.close()
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
