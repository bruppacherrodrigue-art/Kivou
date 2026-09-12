"""Bounded backfill for the customer-facing award location projection."""

from __future__ import annotations

import argparse

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.ingestion.client_location import resolve_client_location
from signals.persistence.database import create_database_engine
from signals.persistence.schema import contract_award, materialized_signal, source_event


def backfill_client_locations(
    connection: sa.Connection,
    *,
    account_ids: tuple[str, ...],
    limit: int,
) -> int:
    if not account_ids:
        raise ValueError("at least one account id is required")
    if not 1 <= limit <= 1_000:
        raise ValueError("limit must be between 1 and 1000")
    rows = connection.execute(
        sa.select(
            contract_award.c.award_key,
            contract_award.c.place_of_performance,
            source_event.c.procedure_buyers,
        )
        .select_from(
            target_icp.join(
                materialized_signal,
                target_icp.c.target_icp_id == materialized_signal.c.target_icp_id,
            )
            .join(
                contract_award,
                materialized_signal.c.materialization_award_key
                == contract_award.c.award_key,
            )
            .join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(target_icp.c.account_id.in_(tuple(sorted(set(account_ids)))))
        .distinct()
        .order_by(contract_award.c.award_key)
        .limit(limit)
    ).mappings()
    updated = 0
    for row in rows:
        resolved = resolve_client_location(
            execution=row["place_of_performance"],
            buyers=row["procedure_buyers"] or (),
        )
        result = connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == row["award_key"])
            .values(
                client_location=resolved.location if resolved is not None else None,
                client_location_basis=resolved.basis if resolved is not None else None,
            )
        )
        updated += int(result.rowcount or 0)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m signals.ingestion.client_location_backfill")
    parser.add_argument("--account-id", action="append", required=True)
    parser.add_argument("--limit", type=int, required=True)
    arguments = parser.parse_args()
    engine = create_database_engine()
    try:
        with engine.begin() as connection:
            updated = backfill_client_locations(
                connection,
                account_ids=tuple(arguments.account_id),
                limit=arguments.limit,
            )
    finally:
        engine.dispose()
    print(f"client_location_backfill updated={updated}")


if __name__ == "__main__":
    main()
