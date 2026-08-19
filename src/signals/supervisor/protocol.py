"""Replaceable Kivou supervisor interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from signals.supervisor.contracts import ProposedAction, SupervisorContext, SupervisorPlan
from signals.supervisor.runtime import SupervisorHealth


@runtime_checkable
class KivouSupervisor(Protocol):
    def plan(self, context: SupervisorContext) -> SupervisorPlan: ...

    def propose_actions(self, context: SupervisorContext) -> tuple[ProposedAction, ...]: ...

    def health(self) -> SupervisorHealth: ...
