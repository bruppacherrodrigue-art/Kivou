"""Kivou-owned monotonic autonomy downgrade through Policy controls."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.operations.contracts import canonical_fingerprint
from signals.policy.contracts import AutonomyMode, PolicyControlSnapshot
from signals.policy.store import PolicyStore

SAFETY_CONTROLLER_REF = "kivou-safety-controller"

_NEXT_SAFER = {
    AutonomyMode.ADAPTIVE_SCALE: AutonomyMode.AUTONOMOUS_CAPPED,
    AutonomyMode.AUTONOMOUS_CAPPED: AutonomyMode.ASSISTED,
    AutonomyMode.ASSISTED: AutonomyMode.SHADOW,
    AutonomyMode.SHADOW: AutonomyMode.SHADOW,
}


class SafetyController:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._policy = PolicyStore(engine)

    def downgrade(
        self, *, at: dt.datetime, reason_codes: tuple[str, ...]
    ) -> PolicyControlSnapshot:
        current = self._policy.get_effective_control(at)
        if (
            current.created_by_actor_ref == SAFETY_CONTROLLER_REF
            and current.reason_codes == reason_codes
        ):
            return current
        target = _NEXT_SAFER[current.autonomy_mode]
        if target is current.autonomy_mode:
            return current
        return self._append_safer(
            current,
            at=at,
            target=target,
            kill_switch=current.kill_switch,
            read_only=current.read_only,
            reason_codes=reason_codes,
        )

    def critical_stop(
        self, *, at: dt.datetime, reason_codes: tuple[str, ...]
    ) -> PolicyControlSnapshot:
        current = self._policy.get_effective_control(at)
        if (
            current.autonomy_mode is AutonomyMode.SHADOW
            and current.kill_switch
            and current.read_only
        ):
            return current
        return self._append_safer(
            current,
            at=at,
            target=AutonomyMode.SHADOW,
            kill_switch=True,
            read_only=True,
            reason_codes=reason_codes,
        )

    def _append_safer(
        self,
        current: PolicyControlSnapshot,
        *,
        at: dt.datetime,
        target: AutonomyMode,
        kill_switch: bool,
        read_only: bool,
        reason_codes: tuple[str, ...],
    ) -> PolicyControlSnapshot:
        payload = {
            "previous": current.policy_snapshot_id,
            "target": target.value,
            "kill_switch": kill_switch,
            "read_only": read_only,
            "reason_codes": reason_codes,
        }
        fingerprint = canonical_fingerprint("policy-safety-control:v1", payload)
        replacement = current.model_copy(
            update={
                "policy_snapshot_id": fingerprint,
                "control_revision": current.control_revision + 1,
                "autonomy_mode": target,
                "shadow_target_mode": (
                    AutonomyMode.ASSISTED if target is AutonomyMode.SHADOW else None
                ),
                "kill_switch": kill_switch,
                "read_only": read_only,
                "effective_at": at,
                "expires_at": None,
                "snapshot_fingerprint": fingerprint,
                "created_at": at,
                "created_by_actor_type": "SYSTEM",
                "created_by_actor_ref": SAFETY_CONTROLLER_REF,
                "reason_codes": reason_codes,
            }
        )
        try:
            replacement = PolicyControlSnapshot.model_validate(replacement)
            self._policy.append_control(replacement)
            return replacement
        except (ValueError, ValidationError, sa.exc.IntegrityError):
            # A concurrent safety controller may have appended the same or a safer
            # authority. Re-read current truth and never overwrite its winner.
            winner = self._policy.get_effective_control(at)
            if self._at_or_below(winner.autonomy_mode, target):
                return winner
            raise

    @staticmethod
    def _at_or_below(current: AutonomyMode, target: AutonomyMode) -> bool:
        order = {
            AutonomyMode.SHADOW: 0,
            AutonomyMode.ASSISTED: 1,
            AutonomyMode.AUTONOMOUS_CAPPED: 2,
            AutonomyMode.ADAPTIVE_SCALE: 3,
        }
        return order[current] <= order[target]
