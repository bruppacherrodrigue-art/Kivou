from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from signals.campaigns.contracts import SequenceTimingInvariantViolation
from signals.campaigns.factory import (
    materialize_step_2_timing,
    sequence_timing_fingerprint,
    sequence_window,
)
from signals.campaigns.worker import SendAuthorization, classify_email_sent


def test_exact_step_two_timing_materializes_only_from_step_one_truth() -> None:
    window = sequence_window("FR", dt.date(2026, 8, 24))
    sent_at = dt.datetime(2026, 8, 24, 10, tzinfo=ZoneInfo("Europe/Paris"))

    due = materialize_step_2_timing(window, sent_at)

    assert due == dt.datetime(2026, 8, 28, 10, tzinfo=ZoneInfo("Europe/Paris"))
    assert (
        sequence_timing_fingerprint(
            sequence_authorization_fingerprint="a" * 64,
            step_1_sent_at=sent_at,
            step_2_due_at=due,
            step_2_authorization_deadline=window.step_2_authorization_deadline,
        )
        == sequence_timing_fingerprint(
            sequence_authorization_fingerprint="a" * 64,
            step_1_sent_at=sent_at,
            step_2_due_at=due,
            step_2_authorization_deadline=window.step_2_authorization_deadline,
        )
    )


@pytest.mark.parametrize(
    ("step_1_date", "sent_hour", "step_2_date", "due_hour"),
    [
        (dt.date(2026, 8, 25), 10, dt.date(2026, 8, 31), 9),
        (dt.date(2026, 8, 26), 16, dt.date(2026, 8, 31), 9),
        (dt.date(2026, 8, 27), 16, dt.date(2026, 8, 31), 16),
        (dt.date(2026, 8, 28), 16, dt.date(2026, 9, 1), 16),
    ],
)
def test_step_two_due_uses_local_calendar_and_frozen_execution_date(
    step_1_date: dt.date,
    sent_hour: int,
    step_2_date: dt.date,
    due_hour: int,
) -> None:
    zone = ZoneInfo("Europe/Paris")
    window = sequence_window("FR", step_1_date)
    sent_at = dt.datetime.combine(step_1_date, dt.time(sent_hour), zone)

    due = materialize_step_2_timing(window, sent_at)

    assert due.date() == step_2_date
    assert due.hour == due_hour
    assert due < window.step_2_authorization_deadline


def test_conflicting_step_one_date_fails_timing_invariant() -> None:
    window = sequence_window("CH", dt.date(2026, 8, 24))
    with pytest.raises(SequenceTimingInvariantViolation):
        materialize_step_2_timing(
            window,
            dt.datetime(2026, 8, 25, 10, tzinfo=ZoneInfo("Europe/Zurich")),
        )


def test_authoritative_sends_are_classified_without_discarding_late_truth() -> None:
    zone = ZoneInfo("Europe/Paris")
    due = dt.datetime(2026, 8, 28, 10, tzinfo=zone)
    deadline = dt.datetime(2026, 8, 28, 17, tzinfo=zone)

    assert classify_email_sent(step=2, occurred_at=due, due_at=due, deadline=deadline) == (
        SendAuthorization.AUTHORIZED,
        None,
    )
    assert classify_email_sent(
        step=2,
        occurred_at=due - dt.timedelta(seconds=1),
        due_at=due,
        deadline=deadline,
    ) == (SendAuthorization.UNAUTHORIZED, "STEP2_SENT_BEFORE_AUTHORIZED_WINDOW")
    assert classify_email_sent(
        step=2,
        occurred_at=deadline,
        due_at=due,
        deadline=deadline,
    ) == (SendAuthorization.UNAUTHORIZED, "STEP2_SENT_OUTSIDE_AUTHORIZED_WINDOW")
