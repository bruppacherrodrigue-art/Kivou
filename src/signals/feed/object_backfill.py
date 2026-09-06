"""Backfill de l'objet affichable des signaux déjà matérialisés."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os

import sqlalchemy as sa

from signals.domain.cpv_labels import cpv_label
from signals.persistence.database import create_database_engine
from signals.persistence.schema import contract_award, materialized_signal


def _has_object(title: str | None, cpv: str | None) -> bool:
    return bool((title and title.strip()) or cpv_label(cpv, lang="fr"))


def backfill(engine: sa.Engine, *, now: dt.datetime | None = None) -> dict[str, int]:
    now = now or dt.datetime.now(dt.UTC)
    dematerialized = 0
    cpv_fallback = 0
    with engine.begin() as connection:
        rows = connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                contract_award.c.title,
                contract_award.c.cpv_main,
            )
            .select_from(
                materialized_signal.join(
                    contract_award,
                    materialized_signal.c.materialization_award_key == contract_award.c.award_key,
                )
            )
            .where(materialized_signal.c.invalidated_at.is_(None))
        )
        for row in rows:
            if row.title and row.title.strip():
                continue
            if cpv_label(row.cpv_main, lang="fr"):
                cpv_fallback += 1
                continue
            connection.execute(
                materialized_signal.update()
                .where(materialized_signal.c.signal_key == row.signal_key)
                .values(invalidated_at=now, invalidation_reason="missing_object")
            )
            dematerialized += 1
    return {"dematerialized": dematerialized, "cpv_fallback": cpv_fallback}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("KIVOU_DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("KIVOU_DATABASE_URL is required")
    print(json.dumps(backfill(create_database_engine(args.database_url)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
