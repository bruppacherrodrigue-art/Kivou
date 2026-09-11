from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from signals.acquisition_runtime.assisted import AssistedPreparationAction
from signals.acquisition_runtime.contracts import RuntimeActionResult, RuntimeStageStatus
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


def test_assisted_action_enriches_once_then_rechecks_directory() -> None:
    class SparsePreparation:
        def __init__(self) -> None:
            self.calls = 0

        def prepare(self, _signal, *, cycle_ref):
            self.calls += 1
            return PreparationResult(
                prepared=20 if self.calls == 1 else 5,
                status="pending_review",
                target_ids=(f"batch-{self.calls}",),
                enrichment_required=self.calls == 1,
            )

    preparation = SparsePreparation()
    enrich_calls = []
    action = AssistedPreparationAction(
        preparation=preparation,
        signal_resolver=lambda _key: object(),
        enrichment_handler=lambda context: (
            enrich_calls.append(context)
            or RuntimeActionResult(
                status=RuntimeStageStatus.SUCCEEDED,
                reserved_cost=1,
                observed_cost=1,
            )
        ),
    )
    context = SimpleNamespace(
        cycle=SimpleNamespace(cycle_ref="cycle-2", opportunity_key="signal-2")
    )

    result = action(context)

    assert preparation.calls == 2
    assert len(enrich_calls) == 1
    assert result.status is RuntimeStageStatus.SUPPRESSED
    assert result.observed_cost == 1
