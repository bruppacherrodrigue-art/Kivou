"""Worker borné des phrases « Pour vous » mises en file à la matérialisation."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from signals.model_runtime.budget import DailyModelBudgetExhausted
from signals.persistence.schema import for_you_sentence
from signals.personalization.for_you import (
    ForYouInput,
    ForYouProvider,
    compose_generated_sentence,
    parse_generated_fragments,
    validate_sentence,
)
from signals.personalization.for_you_queue import (
    ForYouProspectionScope,
    audit_and_purge_queue,
    prioritized_claim_query,
)

DEFAULT_CONCURRENCY = 4
DEFAULT_BATCH_LIMIT = 500
LEASE_TTL = dt.timedelta(minutes=15)
RAW_RESPONSE_RETENTION = dt.timedelta(days=30)
RAW_RESPONSE_MAX_CHARS = 2_000
CONCURRENCY_ENV = "KIVOU_FOR_YOU_CONCURRENCY"
BATCH_LIMIT_ENV = "KIVOU_FOR_YOU_BATCH_LIMIT"
DATABASE_URL_ENV = "KIVOU_DATABASE_URL"


def limits_from_environment() -> tuple[int, int]:
    concurrency = int(os.environ.get(CONCURRENCY_ENV, str(DEFAULT_CONCURRENCY)))
    batch_limit = int(os.environ.get(BATCH_LIMIT_ENV, str(DEFAULT_BATCH_LIMIT)))
    if concurrency < 1:
        raise ValueError(f"{CONCURRENCY_ENV} must be positive")
    if batch_limit < 1:
        raise ValueError(f"{BATCH_LIMIT_ENV} must be positive")
    return concurrency, batch_limit


@dataclass(frozen=True)
class ForYouWorkerReport:
    attempted: int
    accepted: int
    rejected: int
    fallback: int
    batch_limit: int
    pending: int
    purged: int = 0
    budget_exhausted: bool = False

    @property
    def rejection_rate(self) -> float:
        return self.rejected / self.attempted if self.attempted else 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {**self.__dict__, "rejection_rate": self.rejection_rate}


@dataclass(frozen=True)
class _Outcome:
    for_you_id: str
    sentence: str | None
    reason: str | None
    detail: str | None
    raw_response: str | None
    model_fit: str | None


class ForYouWorker:
    def __init__(
        self,
        engine: sa.Engine,
        provider: ForYouProvider,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        prospection_scope: ForYouProspectionScope | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        if batch_limit < 1:
            raise ValueError("batch_limit must be positive")
        self.engine = engine
        self.provider = provider
        self.concurrency = concurrency
        self.batch_limit = batch_limit
        self.prospection_scope = prospection_scope
        self._last_purged = 0

    def _claim(
        self,
        *,
        now: dt.datetime,
        limit: int | None,
        for_you_ids: tuple[str, ...] | None,
    ) -> list[dict]:
        worker = uuid.uuid4().hex
        with self.engine.begin() as connection:
            connection.execute(
                sa.update(for_you_sentence)
                .where(for_you_sentence.c.raw_response_expires_at <= now)
                .values(raw_provider_response=None, raw_response_expires_at=None)
            )
            if connection.dialect.name == "postgresql":
                # Sérialise la purge et la réclamation entre plusieurs hôtes.
                connection.execute(
                    sa.text("LOCK TABLE for_you_sentence IN SHARE ROW EXCLUSIVE MODE")
                )
            audit = audit_and_purge_queue(connection, now=now, apply=True)
            self._last_purged = audit.deleted
            remaining = self.batch_limit
            if limit is not None:
                remaining = min(remaining, limit)
            if remaining == 0:
                return []
            query = prioritized_claim_query(
                now=now,
                limit=remaining,
                scope=self.prospection_scope,
                for_you_ids=for_you_ids,
            )
            if connection.dialect.name == "postgresql":
                # The priority query uses outer joins; PostgreSQL must lock only
                # the queue rows, never the nullable joined relations.
                query = query.with_for_update(skip_locked=True, of=for_you_sentence)
            rows = [dict(row) for row in connection.execute(query).mappings()]
            if rows:
                connection.execute(
                    sa.update(for_you_sentence)
                    .where(for_you_sentence.c.for_you_id.in_([row["for_you_id"] for row in rows]))
                    .values(
                        state="running",
                        attempt_day=now.date(),
                        lease_owner=worker,
                        lease_expires_at=now + LEASE_TTL,
                        updated_at=now,
                    )
                )
            return rows

    def _generate(self, row: dict) -> _Outcome:
        value = ForYouInput.model_validate(row["input_snapshot"])
        try:
            output = self.provider.generate_sentence(value)
        except DailyModelBudgetExhausted:
            raise
        # Le fournisseur est une frontière externe : toute panne conserve le
        # repli déjà visible, sans faire échouer le lot ni la matérialisation.
        except Exception:  # noqa: BLE001
            return _Outcome(row["for_you_id"], None, "provider_unavailable", None, None, None)
        if output is None:
            return _Outcome(row["for_you_id"], None, "provider_unavailable", None, None, None)
        fragments = parse_generated_fragments(output)
        if fragments is not None and fragments.fit == "none":
            return _Outcome(row["for_you_id"], None, None, None, None, "none")
        sentence = compose_generated_sentence(output, value)
        if sentence is None:
            reason = (
                "invalid_shape" if parse_generated_fragments(output) is None else "invalid_content"
            )
            return _Outcome(
                row["for_you_id"],
                None,
                reason,
                None,
                output[:RAW_RESPONSE_MAX_CHARS],
                fragments.fit if fragments is not None else None,
            )
        validation = validate_sentence(sentence, value)
        if not validation.accepted:
            return _Outcome(
                row["for_you_id"],
                None,
                validation.reason,
                validation.detail,
                output[:RAW_RESPONSE_MAX_CHARS],
                fragments.fit if fragments is not None else None,
            )
        return _Outcome(
            row["for_you_id"], " ".join(sentence.split()), None, None, None, fragments.fit
        )

    def run(
        self,
        *,
        now: dt.datetime,
        limit: int | None = None,
        for_you_ids: tuple[str, ...] | None = None,
    ) -> ForYouWorkerReport:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        rows = self._claim(now=now, limit=limit, for_you_ids=for_you_ids)
        outcomes: list[_Outcome] = []
        requeue_ids: list[str] = []
        budget_exhausted = False
        next_row = 0
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.concurrency,
            thread_name_prefix="for-you",
        ) as pool:
            pending: dict[concurrent.futures.Future[_Outcome], dict] = {}

            def submit_next() -> bool:
                nonlocal next_row
                if next_row >= len(rows):
                    return False
                row = rows[next_row]
                next_row += 1
                pending[pool.submit(self._generate, row)] = row
                return True

            for _ in range(min(self.concurrency, len(rows))):
                submit_next()
            while pending:
                completed, _ = concurrent.futures.wait(
                    tuple(pending),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in completed:
                    row = pending.pop(future)
                    try:
                        outcomes.append(future.result())
                    except DailyModelBudgetExhausted:
                        budget_exhausted = True
                        requeue_ids.append(row["for_you_id"])
                    if not budget_exhausted:
                        submit_next()
            if budget_exhausted:
                requeue_ids.extend(row["for_you_id"] for row in rows[next_row:])

        accepted = rejected = fallback = 0
        with self.engine.begin() as connection:
            for outcome in outcomes:
                generated = outcome.sentence is not None
                accepted += int(generated)
                rejected += int(outcome.reason not in (None, "provider_unavailable"))
                fallback += int(not generated)
                values = {
                    "state": "completed",
                    "provenance": "generated" if generated else "fallback",
                    "validation_reason": outcome.reason,
                    "validation_detail": outcome.detail,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                    "completed_at": now,
                    "raw_provider_response": outcome.raw_response,
                    "model_fit": outcome.model_fit,
                    "raw_response_expires_at": (
                        now + RAW_RESPONSE_RETENTION if outcome.raw_response is not None else None
                    ),
                }
                if generated:
                    values["sentence"] = outcome.sentence
                connection.execute(
                    sa.update(for_you_sentence)
                    .where(for_you_sentence.c.for_you_id == outcome.for_you_id)
                    .values(**values)
                )
            if requeue_ids:
                connection.execute(
                    sa.update(for_you_sentence)
                    .where(for_you_sentence.c.for_you_id.in_(requeue_ids))
                    .values(
                        state="pending",
                        attempt_day=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
            pending = (
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(for_you_sentence)
                    .where(for_you_sentence.c.state == "pending")
                )
                or 0
            )
        return ForYouWorkerReport(
            attempted=len(outcomes),
            accepted=accepted,
            rejected=rejected,
            fallback=fallback,
            batch_limit=self.batch_limit,
            pending=pending,
            purged=self._last_purged,
            budget_exhausted=budget_exhausted,
        )


def main() -> int:
    from signals.documents.providers import text_generator_from_environment
    from signals.persistence.database import create_database_engine

    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        raise SystemExit(f"{DATABASE_URL_ENV} is required")
    from signals.acquisition_runtime.config import load_runtime_config
    from signals.acquisition_runtime.selection import region_subdivision_codes

    concurrency, batch_limit = limits_from_environment()
    scope = None
    if os.environ.get("KIVOU_ACQUISITION_RUNTIME_CONFIG"):
        runtime = load_runtime_config()
        selection = runtime.deployment.selection
        if selection is not None and selection.vertical and selection.region:
            scope = ForYouProspectionScope(
                vertical=selection.vertical,
                subdivision_codes=region_subdivision_codes(selection.region),
            )
    engine = create_database_engine(database_url)
    provider = text_generator_from_environment(engine=engine, batch_id=f"for-you-{uuid.uuid4()}")
    try:
        report = ForYouWorker(
            engine,
            provider,
            concurrency=concurrency,
            batch_limit=batch_limit,
            prospection_scope=scope,
        ).run(now=dt.datetime.now(dt.UTC))
    finally:
        provider.close()
        engine.dispose()
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0


__all__ = ["ForYouWorker", "ForYouWorkerReport", "limits_from_environment"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
