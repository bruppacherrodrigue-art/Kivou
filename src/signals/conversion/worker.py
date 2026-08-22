"""Explicit conversion workers. Importing this module starts nothing."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.conversion.milestones import ConversionMilestoneService, MilestoneResult
from signals.persistence.schema import acquisition_conversion_journey


class ConversionRetentionWorker:
    def __init__(self, engine: sa.Engine, service: ConversionMilestoneService) -> None:
        self.engine = engine
        self.service = service

    def run(self, *, at: dt.datetime) -> tuple[MilestoneResult, ...]:
        with self.engine.begin() as connection:
            account_ids = tuple(
                connection.scalars(
                    sa.select(acquisition_conversion_journey.c.account_id).order_by(
                        acquisition_conversion_journey.c.account_id
                    )
                )
            )
            results: list[MilestoneResult] = []
            for account_id in account_ids:
                results.extend(
                    self.service.record_retention_in_transaction(
                        connection, account_id=account_id, at=at
                    )
                )
            return tuple(results)


__all__ = ["ConversionRetentionWorker"]
