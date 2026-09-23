"""Durable, content-free ledger for legal-page and DNS attempts in B1."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.http_accounting import LegalHttpAttempt
from signals.persistence.schema import acquisition_census_legal_http_attempt


class LegalHttpAttemptStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(self, event: LegalHttpAttempt) -> None:
        if not event.run_id:
            raise ValueError("B1 HTTP accounting requires a census run ID")
        table = acquisition_census_legal_http_attempt
        with self.engine.begin() as connection:
            previous = connection.execute(sa.select(table).where(
                table.c.attempt_id == event.attempt_id,
            ).with_for_update()).mappings().one_or_none()
            if event.outcome == "STARTED":
                if previous is None:
                    connection.execute(sa.insert(table).values(
                        attempt_id=event.attempt_id, census_id=event.run_id,
                        candidate_id=event.company_id, domain=event.domain,
                        request_type=event.request_type, proof_type=(
                            "OFFICIAL_STATUS" if event.request_type == "OFFICIAL_API"
                            else "LEGAL_IDENTITY"),
                        started_at=event.occurred_at, completed_at=None,
                        outcome="STARTED", http_status=None, cache_hit=False,
                    ))
                elif (previous["census_id"] != event.run_id or
                      previous["candidate_id"] != event.company_id or
                      previous["domain"] != event.domain or
                      previous["request_type"] != event.request_type):
                    raise ValueError("HTTP attempt identity conflict")
                return
            if previous is None:
                if event.request_type not in {"CACHE", "ROBOTS_POLICY"} and not (
                    event.request_type == "OFFICIAL_API" and event.outcome == "CACHE_HIT"
                ):
                    raise ValueError("HTTP terminal event missing STARTED")
                connection.execute(sa.insert(table).values(
                    attempt_id=event.attempt_id, census_id=event.run_id,
                    candidate_id=event.company_id, domain=event.domain,
                    request_type=event.request_type, proof_type=(
                        "OFFICIAL_STATUS" if event.request_type == "OFFICIAL_API"
                        else "LEGAL_IDENTITY"),
                    started_at=event.occurred_at, completed_at=event.occurred_at,
                    outcome=event.outcome, http_status=event.http_status,
                    cache_hit=event.outcome == "CACHE_HIT",
                ))
                return
            if (previous["census_id"] != event.run_id or
                  previous["candidate_id"] != event.company_id or
                  previous["domain"] != event.domain or
                  previous["request_type"] != event.request_type):
                raise ValueError("HTTP attempt identity conflict")
            if previous["outcome"] == event.outcome and previous["http_status"] == event.http_status:
                return
            if previous["outcome"] != "STARTED":
                raise ValueError("HTTP attempt already finalized")
            connection.execute(sa.update(table).where(
                table.c.attempt_id == event.attempt_id,
            ).values(outcome=event.outcome, http_status=event.http_status,
                     completed_at=event.occurred_at,
                     cache_hit=event.outcome == "CACHE_HIT"))

    def summary(self, census_id: str) -> dict[str, int]:
        table = acquisition_census_legal_http_attempt
        with self.engine.connect() as connection:
            rows = connection.execute(sa.select(table.c.request_type, table.c.outcome,
                                                sa.func.count()).where(
                table.c.census_id == census_id,
            ).group_by(table.c.request_type, table.c.outcome)).all()
        return {f"{kind}:{outcome}": count for kind, outcome, count in rows}
