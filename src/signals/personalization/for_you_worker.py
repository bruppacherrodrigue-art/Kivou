"""Worker borné des phrases « Pour vous » mises en file à la matérialisation."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from signals.persistence.schema import for_you_sentence
from signals.personalization.for_you import ForYouInput, ForYouProvider, validate_sentence

DEFAULT_CONCURRENCY = 4
DEFAULT_DAILY_LIMIT = 500
LEASE_TTL = dt.timedelta(minutes=15)


@dataclass(frozen=True)
class ForYouWorkerReport:
    attempted: int
    accepted: int
    rejected: int
    fallback: int
    generated_today: int
    daily_limit: int
    pending: int

    @property
    def rejection_rate(self) -> float:
        return self.rejected / self.attempted if self.attempted else 0.0


@dataclass(frozen=True)
class _Outcome:
    for_you_id: str
    sentence: str | None
    reason: str | None
    detail: str | None


class ForYouWorker:
    def __init__(
        self,
        engine: sa.Engine,
        provider: ForYouProvider,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        if daily_limit < 0:
            raise ValueError("daily_limit must not be negative")
        self.engine = engine
        self.provider = provider
        self.concurrency = concurrency
        self.daily_limit = daily_limit

    def _claim(
        self,
        *,
        now: dt.datetime,
        limit: int | None,
        for_you_ids: tuple[str, ...] | None,
    ) -> list[dict]:
        worker = uuid.uuid4().hex
        with self.engine.begin() as connection:
            used = (
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(for_you_sentence)
                    .where(for_you_sentence.c.attempt_day == now.date())
                )
                or 0
            )
            remaining = max(0, self.daily_limit - used)
            if limit is not None:
                remaining = min(remaining, limit)
            if remaining == 0:
                return []
            reclaimable = sa.or_(
                for_you_sentence.c.state == "pending",
                sa.and_(
                    for_you_sentence.c.state == "running",
                    for_you_sentence.c.lease_expires_at <= now,
                ),
            )
            query = (
                sa.select(for_you_sentence.c.for_you_id, for_you_sentence.c.input_snapshot)
                .where(reclaimable)
                .order_by(for_you_sentence.c.created_at, for_you_sentence.c.for_you_id)
                .limit(remaining)
            )
            if for_you_ids is not None:
                query = query.where(for_you_sentence.c.for_you_id.in_(for_you_ids))
            if connection.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
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
            sentence = self.provider.generate_sentence(value)
        # Le fournisseur est une frontière externe : toute panne conserve le
        # repli déjà visible, sans faire échouer le lot ni la matérialisation.
        except Exception:  # noqa: BLE001
            return _Outcome(row["for_you_id"], None, "provider_unavailable", None)
        if sentence is None:
            return _Outcome(row["for_you_id"], None, "provider_unavailable", None)
        validation = validate_sentence(sentence, value)
        if not validation.accepted:
            return _Outcome(row["for_you_id"], None, validation.reason, validation.detail)
        return _Outcome(row["for_you_id"], " ".join(sentence.split()), None, None)

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
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.concurrency,
            thread_name_prefix="for-you",
        ) as pool:
            outcomes = list(pool.map(self._generate, rows))

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
                }
                if generated:
                    values["sentence"] = outcome.sentence
                connection.execute(
                    sa.update(for_you_sentence)
                    .where(for_you_sentence.c.for_you_id == outcome.for_you_id)
                    .values(**values)
                )
            generated_today = (
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(for_you_sentence)
                    .where(for_you_sentence.c.attempt_day == now.date())
                )
                or 0
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
            generated_today=generated_today,
            daily_limit=self.daily_limit,
            pending=pending,
        )


__all__ = ["ForYouWorker", "ForYouWorkerReport"]
