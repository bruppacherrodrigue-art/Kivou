from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from signals.acquisition_runtime.assisted import AssistedPreparationAction
from signals.acquisition_runtime.contracts import RuntimeStageStatus
from signals.prospection_actions.preparation import PreparationResult

NOW = dt.datetime(2026, 9, 11, 7, tzinfo=dt.UTC)


class Preparation:
    def __init__(self) -> None:
        self.calls = []

    def prepare(self, signal, *, cycle_ref):
        self.calls.append((signal, cycle_ref))
        return PreparationResult(
            prepared=25,
            status="pending_review",
            target_ids=tuple(f"target-{index}" for index in range(25)),
        )


def test_assisted_action_stops_cycle_at_pending_review_without_campaign_stage() -> None:
    preparation = Preparation()
    action = AssistedPreparationAction(
        preparation=preparation,
        signal_resolver=lambda _key: SimpleNamespace(opportunity_key="signal-1"),
    )
    context = SimpleNamespace(
        cycle=SimpleNamespace(cycle_ref="cycle-1", opportunity_key="signal-1")
    )

    result = action(context)

    assert result.status is RuntimeStageStatus.SUPPRESSED
    assert result.reason_codes == ("ASSISTED_PENDING_REVIEW",)
    assert len(result.result_refs) == 1
    assert preparation.calls[0][1] == "cycle-1"
