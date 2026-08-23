"""Explicit no-autostart learning worker; repository defaults are a safe no-op."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from signals.learning.candidates import generate_candidates
from signals.learning.contracts import (
    CandidateKind,
    LearningAllocationEnvelope,
    make_learning_window,
)
from signals.learning.hermes import (
    HermesLearningSelector,
    build_selection_context,
    validate_selection,
)
from signals.learning.metrics import RepositoryLearningMetricsSource
from signals.learning.policy import LearningPolicyAuthorizer
from signals.learning.service import build_learning_snapshot
from signals.learning.store import LearningStore


class LearningWorkerStatus(StrEnum):
    UNCONFIGURED = "UNCONFIGURED"
    NO_CHANGE = "NO_CHANGE"
    SHADOW_ONLY = "SHADOW_ONLY"
    POLICY_DENIED = "POLICY_DENIED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


@dataclass(frozen=True)
class LearningWorkerResult:
    status: LearningWorkerStatus
    snapshot_ref: str | None = None
    proposal_ref: str | None = None


class LearningMetricsSource(Protocol):
    def capture(self, *, window): ...


class UnconfiguredLearningAllocationEnvelopeProvider:
    def __call__(self, at: dt.datetime) -> None:
        del at


class LearningLoopWorker:
    def __init__(
        self,
        *,
        store: LearningStore,
        metrics_source: LearningMetricsSource | RepositoryLearningMetricsSource,
        envelope_provider: Callable[[dt.datetime], LearningAllocationEnvelope | None],
        selector: HermesLearningSelector,
        policy_authorizer: LearningPolicyAuthorizer,
    ) -> None:
        self.store = store
        self.metrics_source = metrics_source
        self.envelope_provider = envelope_provider
        self.selector = selector
        self.policy_authorizer = policy_authorizer

    def run(self, *, window_end: dt.datetime, captured_at: dt.datetime) -> LearningWorkerResult:
        window = make_learning_window(window_end=window_end, captured_at=captured_at)
        envelope = self.envelope_provider(captured_at)
        if envelope is None:
            return LearningWorkerResult(LearningWorkerStatus.UNCONFIGURED)
        if not envelope.valid_from <= captured_at < envelope.valid_until:
            return LearningWorkerResult(LearningWorkerStatus.UNCONFIGURED)
        existing = self.store.existing_cycle(
            window_end=window.window_end,
            envelope_fingerprint=envelope.fingerprint,
        )
        if existing is not None and existing[1] is not None:
            selected = existing[1]
            statuses = {
                "APPLIED": LearningWorkerStatus.APPLIED,
                "SHADOW_ONLY": LearningWorkerStatus.SHADOW_ONLY,
                "POLICY_DENIED": LearningWorkerStatus.POLICY_DENIED,
                "REJECTED": LearningWorkerStatus.REJECTED,
            }
            if selected["state"] in statuses:
                return LearningWorkerResult(
                    statuses[selected["state"]],
                    snapshot_ref=existing[0]["snapshot_ref"],
                    proposal_ref=selected["proposal_ref"],
                )
            return self._finish_selected(
                snapshot_ref=existing[0]["snapshot_ref"],
                proposal_ref=selected["proposal_ref"],
                delta_units=selected["delta_units"],
                policy_status=selected["policy_status"],
                now=captured_at,
            )
        current = self.store.resolve_current_allocation(envelope)
        metrics = self.metrics_source.capture(window=window)
        snapshot = build_learning_snapshot(
            window=window,
            metrics=tuple(metrics),
            envelope=envelope,
            previous_applied_proposal_ref=(
                current.authority_ref if not current.authority_ref.startswith("INITIAL:") else None
            ),
            current_allocation=current.allocation,
        )
        self.store.save_snapshot(snapshot)
        candidates = generate_candidates(
            snapshot_ref=snapshot.snapshot_ref,
            envelope=envelope,
            scores=snapshot.economic_scores,
            baseline_authority_ref=current.authority_ref,
            current_allocation=current.allocation,
        )
        self.store.save_candidates(
            candidates,
            envelope_fingerprint=envelope.fingerprint,
            created_at=captured_at,
        )
        selection = self.selector.select(
            build_selection_context(
                snapshot_ref=snapshot.snapshot_ref,
                scores=snapshot.economic_scores,
                candidates=candidates,
            )
        )
        candidate = validate_selection(
            selection, snapshot_ref=snapshot.snapshot_ref, candidates=candidates
        )
        source = "KIVOU_NO_CHANGE" if candidate.kind is CandidateKind.NO_CHANGE else "HERMES"
        selected = self.store.record_selection(
            candidate.proposal_ref,
            source=source,
            confidence=selection.confidence,
            reason_codes=selection.reason_codes,
            decided_at=captured_at,
        )
        return self._finish_selected(
            snapshot_ref=selected["snapshot_ref"],
            proposal_ref=selected["proposal_ref"],
            delta_units=selected["delta_units"],
            policy_status=selected["policy_status"],
            now=captured_at,
        )

    def _finish_selected(
        self,
        *,
        snapshot_ref: str,
        proposal_ref: str,
        delta_units: int,
        policy_status: str | None,
        now: dt.datetime,
    ) -> LearningWorkerResult:
        if delta_units == 0:
            return LearningWorkerResult(
                LearningWorkerStatus.NO_CHANGE,
                snapshot_ref=snapshot_ref,
                proposal_ref=proposal_ref,
            )
        if policy_status == "APPROVED":
            applied = self.store.apply(proposal_ref, applied_at=now)
            return LearningWorkerResult(
                LearningWorkerStatus.APPLIED
                if applied.applied or applied.replayed
                else LearningWorkerStatus.REJECTED,
                snapshot_ref=snapshot_ref,
                proposal_ref=proposal_ref,
            )
        try:
            authorization = self.policy_authorizer.authorize(proposal_ref, now=now)
        except Exception:  # noqa: BLE001 - injected Policy boundary fails closed
            return LearningWorkerResult(
                LearningWorkerStatus.POLICY_UNAVAILABLE,
                snapshot_ref=snapshot_ref,
                proposal_ref=proposal_ref,
            )
        if not authorization.executable or not authorization.allowed:
            shadow = authorization.policy_counterfactual_status == "APPROVED"
            state = "SHADOW_ONLY" if shadow else "POLICY_DENIED"
            self.store.record_policy(
                proposal_ref,
                evaluation_id=authorization.policy_evaluation_id,
                action_fingerprint=authorization.policy_action_fingerprint,
                status=authorization.policy_status,
                counterfactual_status=authorization.policy_counterfactual_status,
                state=state,
                decided_at=now,
            )
            return LearningWorkerResult(
                LearningWorkerStatus.SHADOW_ONLY if shadow else LearningWorkerStatus.POLICY_DENIED,
                snapshot_ref=snapshot_ref,
                proposal_ref=proposal_ref,
            )
        self.store.record_policy(
            proposal_ref,
            evaluation_id=authorization.policy_evaluation_id,
            action_fingerprint=authorization.policy_action_fingerprint,
            status=authorization.policy_status,
            counterfactual_status=authorization.policy_counterfactual_status,
            state="PROPOSED",
            decided_at=now,
        )
        applied = self.store.apply(proposal_ref, applied_at=now)
        return LearningWorkerResult(
            LearningWorkerStatus.APPLIED
            if applied.applied or applied.replayed
            else LearningWorkerStatus.REJECTED,
            snapshot_ref=snapshot_ref,
            proposal_ref=proposal_ref,
        )


__all__ = [
    "LearningLoopWorker",
    "LearningWorkerResult",
    "LearningWorkerStatus",
    "UnconfiguredLearningAllocationEnvelopeProvider",
]
