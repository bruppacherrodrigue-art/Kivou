from __future__ import annotations

import datetime as dt
import threading
import time

import sqlalchemy as sa
from test_attribution_landing import CLICKED_AT, client_for, land, prepared

from signals.persistence.schema import for_you_sentence
from signals.personalization.for_you_worker import ForYouWorker


class FakeProvider:
    def __init__(self, sentence: str | None) -> None:
        self.sentence = sentence
        self.calls = 0

    def generate_sentence(self, _value) -> str | None:
        self.calls += 1
        return self.sentence


def _seed(tmp_path, *, count: int = 1):
    engine, attribution, token, _ = prepared(tmp_path)
    assert land(client_for(engine, attribution, now=CLICKED_AT), token.raw_token).status_code == 303
    with engine.begin() as connection:
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


def test_worker_accepts_and_persists_generated_sentence(tmp_path) -> None:
    engine = _seed(tmp_path)
    provider = FakeProvider("Votre offre répond aux besoins de travaux du titulaire.")

    report = ForYouWorker(engine, provider, concurrency=4, daily_limit=20).run(now=CLICKED_AT)

    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert report.accepted == 1
    assert report.generated_today == 1
    assert row["sentence"] == provider.sentence
    assert row["provenance"] == "generated"
    assert row["state"] == "completed"


def test_worker_rejects_an_invented_number_and_keeps_fallback(tmp_path) -> None:
    engine = _seed(tmp_path)
    provider = FakeProvider("Ce marché représente 987654 euros pour votre offre.")

    report = ForYouWorker(engine, provider, concurrency=1, daily_limit=20).run(now=CLICKED_AT)

    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert report.rejected == 1
    assert row["sentence"] == row["fallback_sentence"]
    assert row["validation_reason"] == "invented_number"
    assert row["state"] == "completed"


def test_worker_daily_cap_leaves_excess_pairs_pending(tmp_path) -> None:
    engine = _seed(tmp_path, count=5)
    provider = FakeProvider("Votre offre répond aux besoins de travaux du titulaire.")

    report = ForYouWorker(engine, provider, concurrency=4, daily_limit=2).run(now=CLICKED_AT)

    with engine.connect() as connection:
        states = connection.execute(
            sa.select(for_you_sentence.c.state, sa.func.count()).group_by(for_you_sentence.c.state)
        ).all()
    assert report.attempted == 2
    assert report.daily_limit == 2
    assert dict(states) == {"completed": 2, "pending": 3}
    assert provider.calls == 2


class ConcurrencyProbe(FakeProvider):
    def __init__(self) -> None:
        super().__init__("Votre offre répond aux besoins de travaux du titulaire.")
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

    ForYouWorker(engine, provider, concurrency=2, daily_limit=20).run(now=CLICKED_AT)

    assert provider.maximum == 2
    assert provider.calls == 6


def test_worker_failure_completes_with_visible_fallback(tmp_path) -> None:
    engine = _seed(tmp_path)
    provider = FakeProvider(None)

    report = ForYouWorker(engine, provider, concurrency=1, daily_limit=20).run(
        now=CLICKED_AT + dt.timedelta(minutes=1)
    )

    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert report.fallback == 1
    assert row["provenance"] == "fallback"
    assert row["validation_reason"] == "provider_unavailable"
    assert row["state"] == "completed"
