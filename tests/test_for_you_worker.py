from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable
from decimal import Decimal

import sqlalchemy as sa
from test_attribution_landing import CLICKED_AT, client_for, land, prepared

from signals.accounts.schema import target_icp
from signals.model_runtime.budget import DailyModelBudgetExhausted
from signals.persistence.schema import (
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
)
from signals.personalization.for_you import ForYouInput, compose_generated_sentence
from signals.personalization.for_you_queue import (
    ForYouProspectionScope,
    audit_and_purge_queue,
    prioritized_claim_query,
)
from signals.personalization.for_you_worker import ForYouWorker, limits_from_environment


class FakeProvider:
    def __init__(self, sentence: str | None | Callable) -> None:
        self.sentence = sentence
        self.calls = 0

    def generate_sentence(self, value) -> str | None:
        self.calls += 1
        return self.sentence(value) if callable(self.sentence) else self.sentence


def valid_sentence(value) -> str:
    return '{"short_object":"travaux de bâtiment","consequence":"vos matériaux répondent aux travaux","fit":"strong"}'


def _seed(tmp_path, *, count: int = 1):
    engine, attribution, token, _ = prepared(tmp_path)
    assert land(client_for(engine, attribution, now=CLICKED_AT), token.raw_token).status_code == 303
    with engine.begin() as connection:
        connection.execute(
            sa.update(contract_award).values(
                award_date=CLICKED_AT.date() - dt.timedelta(days=1),
                contract_notification_date=None,
            )
        )
        connection.execute(
            sa.update(for_you_sentence).values(state="pending", completed_at=None, attempt_day=None)
        )
        if count > 1:
            original = connection.execute(sa.select(for_you_sentence)).mappings().one()
            for index in range(1, count):
                values = dict(original)
                values.update(
                    for_you_id=f"{index:064x}",
                    signal_fingerprint=f"{index:064x}",
                )
                connection.execute(sa.insert(for_you_sentence).values(**values))
    return engine


def _clone_signal(connection, *, suffix: str, award_date: dt.date, vertical: str, subdivision: str):
    award = dict(connection.execute(sa.select(contract_award)).mappings().first())
    award.update(
        award_key=f"award-{suffix}",
        award_date=award_date,
        contract_notification_date=None,
        place_of_performance={"country": "FR", "subdivision_code": subdivision},
    )
    connection.execute(sa.insert(contract_award).values(**award))
    signal = dict(connection.execute(sa.select(materialized_signal)).mappings().first())
    signal.update(
        signal_key=f"signal-{suffix}",
        opportunity_key=f"opportunity-{suffix}",
        materialization_award_key=award["award_key"],
        content_fingerprint=f"fingerprint-{suffix}",
        inferred_trade_domain=vertical,
    )
    connection.execute(sa.insert(materialized_signal).values(**signal))
    representation = dict(
        connection.execute(sa.select(opportunity_representation)).mappings().first()
    )
    representation.update(
        award_key=award["award_key"],
        opportunity_key=signal["opportunity_key"],
    )
    connection.execute(sa.insert(opportunity_representation).values(**representation))
    queued = dict(connection.execute(sa.select(for_you_sentence)).mappings().first())
    queued.update(
        for_you_id=f"for-you-{suffix}",
        signal_key=signal["signal_key"],
        signal_fingerprint=signal["content_fingerprint"],
        state="pending",
        completed_at=None,
        attempt_day=None,
        created_at=CLICKED_AT + dt.timedelta(seconds=len(suffix)),
    )
    connection.execute(sa.insert(for_you_sentence).values(**queued))
    return queued["for_you_id"]


def test_queue_prioritizes_active_pair_then_other_active_recent_then_rest(tmp_path) -> None:
    engine = _seed(tmp_path)
    with engine.begin() as connection:
        original = connection.scalar(sa.select(for_you_sentence.c.for_you_id))
        connection.execute(sa.update(materialized_signal).values(inferred_trade_domain="other"))
        pair = _clone_signal(
            connection,
            suffix="pair",
            award_date=CLICKED_AT.date() - dt.timedelta(days=1),
            vertical="general_building",
            subdivision="FR-38",
        )
        rest = _clone_signal(
            connection,
            suffix="rest",
            award_date=CLICKED_AT.date() - dt.timedelta(days=40),
            vertical="other",
            subdivision="FR-75",
        )
        rows = connection.scalars(
            prioritized_claim_query(
                now=CLICKED_AT,
                limit=10,
                scope=ForYouProspectionScope("general_building", ("FR-38",)),
                for_you_ids=None,
            )
        ).all()
    assert rows == [pair, original, rest]


def test_queue_purge_audits_old_and_inactive_without_deleting_history(tmp_path) -> None:
    engine = _seed(tmp_path)
    with engine.begin() as connection:
        old = _clone_signal(
            connection,
            suffix="old",
            award_date=CLICKED_AT.date() - dt.timedelta(days=31),
            vertical="other",
            subdivision="FR-75",
        )
        inactive = _clone_signal(
            connection,
            suffix="inactive",
            award_date=CLICKED_AT.date() - dt.timedelta(days=1),
            vertical="other",
            subdivision="FR-75",
        )
        connection.execute(sa.update(target_icp).values(status="inactive"))
        # Preserve one completed row as historical evidence even for an inactive profile.
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.for_you_id == inactive)
            .values(state="completed", completed_at=CLICKED_AT)
        )
        dry = audit_and_purge_queue(connection, now=CLICKED_AT, apply=False)
        applied = audit_and_purge_queue(connection, now=CLICKED_AT, apply=True)
        remaining = set(connection.scalars(sa.select(for_you_sentence.c.for_you_id)))
    assert dry.deleted == 0
    assert dry.before == 2
    assert dry.older_than_30_days == 1
    assert dry.inactive_profile == 2
    assert dry.overlap == 1
    assert applied.deleted == 2
    assert inactive in remaining
    assert old not in remaining


def test_worker_accepts_and_persists_generated_sentence(tmp_path) -> None:
    engine = _seed(tmp_path)
    provider = FakeProvider(valid_sentence)

    report = ForYouWorker(engine, provider, concurrency=4, batch_limit=20).run(now=CLICKED_AT)

    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert report.accepted == 1
    assert report.attempted == 1
    value = ForYouInput.model_validate(row["input_snapshot"])
    assert row["sentence"] == compose_generated_sentence(valid_sentence(value), value)
    assert row["provenance"] == "generated"
    assert row["state"] == "completed"
    assert row["model_fit"] == "strong"


def test_worker_persists_none_fit_as_non_rejected_fallback(tmp_path) -> None:
    engine = _seed(tmp_path)
    raw = '{"short_object":"maintenance médicale","consequence":null,"fit":"none"}'
    report = ForYouWorker(engine, FakeProvider(raw), concurrency=1, batch_limit=20).run(
        now=CLICKED_AT
    )
    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert report.rejected == 0
    assert report.fallback == 1
    assert row["model_fit"] == "none"
    assert row["sentence"] == row["fallback_sentence"]
    assert row["validation_reason"] is None


def test_worker_rejects_an_invented_number_and_keeps_fallback(tmp_path) -> None:
    engine = _seed(tmp_path)
    provider = FakeProvider(
        '{"short_object":"travaux de bâtiment","consequence":"vos matériaux couvrent 987654 travaux","fit":"strong"}'
    )

    report = ForYouWorker(engine, provider, concurrency=1, batch_limit=20).run(now=CLICKED_AT)

    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert report.rejected == 1
    assert report.as_dict()["rejection_rate"] == 1.0
    assert row["sentence"] == row["fallback_sentence"]
    assert row["validation_reason"] == "invented_number"
    assert row["raw_provider_response"] == provider.sentence
    assert row["raw_response_expires_at"] == (CLICKED_AT + dt.timedelta(days=30)).replace(
        tzinfo=None
    )
    assert row["state"] == "completed"


def test_worker_truncates_rejected_raw_output_and_purges_it_after_30_days(tmp_path) -> None:
    engine = _seed(tmp_path)
    raw = "x" * 2_500
    worker = ForYouWorker(engine, FakeProvider(raw), concurrency=1, batch_limit=20)

    worker.run(now=CLICKED_AT)
    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert row["raw_provider_response"] == "x" * 2_000

    worker.run(now=CLICKED_AT + dt.timedelta(days=30))
    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert row["raw_provider_response"] is None
    assert row["raw_response_expires_at"] is None


def test_invalid_shape_is_reserved_for_missing_json_fragments(tmp_path) -> None:
    engine = _seed(tmp_path)
    ForYouWorker(
        engine, FakeProvider("réponse sans objet JSON"), concurrency=1, batch_limit=20
    ).run(now=CLICKED_AT)
    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert row["validation_reason"] == "invalid_shape"


def test_exploitable_json_with_invalid_content_has_a_distinct_reason(tmp_path) -> None:
    engine = _seed(tmp_path)
    raw = '{"short_object":"travaux","consequence":"trop court","fit":"strong"}'
    ForYouWorker(engine, FakeProvider(raw), concurrency=1, batch_limit=20).run(now=CLICKED_AT)
    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert row["validation_reason"] == "invalid_content"


def test_worker_batch_limit_leaves_excess_pairs_pending(tmp_path) -> None:
    engine = _seed(tmp_path, count=5)
    provider = FakeProvider(valid_sentence)

    report = ForYouWorker(engine, provider, concurrency=4, batch_limit=2).run(now=CLICKED_AT)

    with engine.connect() as connection:
        states = connection.execute(
            sa.select(for_you_sentence.c.state, sa.func.count()).group_by(for_you_sentence.c.state)
        ).all()
    assert report.attempted == 2
    assert report.batch_limit == 2
    assert dict(states) == {"completed": 2, "pending": 3}
    assert provider.calls == 2


class ConcurrencyProbe(FakeProvider):
    def __init__(self) -> None:
        super().__init__(valid_sentence)
        self.active = 0
        self.maximum = 0
        self.lock = threading.Lock()

    def generate_sentence(self, value) -> str | None:
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        time.sleep(0.02)
        with self.lock:
            self.active -= 1
        return super().generate_sentence(value)


def test_worker_bounds_provider_concurrency(tmp_path) -> None:
    engine = _seed(tmp_path, count=6)
    provider = ConcurrencyProbe()

    ForYouWorker(engine, provider, concurrency=2, batch_limit=20).run(now=CLICKED_AT)

    assert provider.maximum == 2
    assert provider.calls == 6


def test_worker_failure_completes_with_visible_fallback(tmp_path) -> None:
    engine = _seed(tmp_path)
    provider = FakeProvider(None)

    report = ForYouWorker(engine, provider, concurrency=1, batch_limit=20).run(
        now=CLICKED_AT + dt.timedelta(minutes=1)
    )

    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert report.fallback == 1
    assert row["provenance"] == "fallback"
    assert row["validation_reason"] == "provider_unavailable"
    assert row["state"] == "completed"


def test_worker_stops_cleanly_and_requeues_when_model_budget_is_exhausted(tmp_path) -> None:
    engine = _seed(tmp_path, count=3)

    def exhausted(_value):
        raise DailyModelBudgetExhausted(
            usage="for_you",
            cap_usd=Decimal("1"),
            actual_usd=Decimal("1"),
            reserved_usd=Decimal("0"),
            requested_usd=Decimal("0.001"),
        )

    report = ForYouWorker(engine, FakeProvider(exhausted), concurrency=1, batch_limit=20).run(
        now=CLICKED_AT
    )

    with engine.connect() as connection:
        states = connection.execute(
            sa.select(for_you_sentence.c.state, sa.func.count()).group_by(for_you_sentence.c.state)
        ).all()
    assert report.budget_exhausted is True
    assert report.attempted == 0
    assert report.pending == 3
    assert dict(states) == {"pending": 3}


def test_worker_reclaims_only_an_expired_lease(tmp_path) -> None:
    engine = _seed(tmp_path, count=2)
    with engine.begin() as connection:
        ids = connection.scalars(
            sa.select(for_you_sentence.c.for_you_id).order_by(for_you_sentence.c.for_you_id)
        ).all()
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.for_you_id == ids[0])
            .values(state="running", lease_expires_at=CLICKED_AT - dt.timedelta(seconds=1))
        )
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.for_you_id == ids[1])
            .values(state="running", lease_expires_at=CLICKED_AT + dt.timedelta(minutes=1))
        )

    report = ForYouWorker(engine, FakeProvider(valid_sentence), concurrency=1, batch_limit=20).run(
        now=CLICKED_AT
    )

    assert report.attempted == 1


def test_batch_limit_does_not_block_a_second_run_the_same_day(tmp_path) -> None:
    engine = _seed(tmp_path, count=2)
    provider = FakeProvider(valid_sentence)
    worker = ForYouWorker(engine, provider, concurrency=1, batch_limit=1)

    assert worker.run(now=CLICKED_AT).attempted == 1
    assert worker.run(now=CLICKED_AT + dt.timedelta(hours=1)).attempted == 1
    assert worker.run(now=CLICKED_AT + dt.timedelta(days=1)).attempted == 0


def test_worker_limits_are_configurable_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("KIVOU_FOR_YOU_CONCURRENCY", "3")
    monkeypatch.setenv("KIVOU_FOR_YOU_BATCH_LIMIT", "42")

    assert limits_from_environment() == (3, 42)
