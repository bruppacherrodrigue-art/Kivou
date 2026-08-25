"""Kivou-owned monotonic autonomy downgrade through Policy controls."""

from __future__ import annotations

import datetime as dt

from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.operations.contracts import canonical_fingerprint
from signals.policy.contracts import AutonomyMode, PolicyControlSnapshot
from signals.policy.store import PolicyStore

SAFETY_CONTROLLER_REF = "kivou-safety-controller"
MAX_CONTROL_APPEND_ATTEMPTS = 3

_NEXT_SAFER = {
    AutonomyMode.ADAPTIVE_SCALE: AutonomyMode.AUTONOMOUS_CAPPED,
    AutonomyMode.AUTONOMOUS_CAPPED: AutonomyMode.ASSISTED,
    AutonomyMode.ASSISTED: AutonomyMode.SHADOW,
    AutonomyMode.SHADOW: AutonomyMode.SHADOW,
}


class SafetyControlConflict(RuntimeError):
    """The bounded append-only safety transition lost every durable CAS."""


class SafetyController:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._policy = PolicyStore(engine)

    def downgrade(self, *, at: dt.datetime, reason_codes: tuple[str, ...]) -> PolicyControlSnapshot:
        for _attempt in range(MAX_CONTROL_APPEND_ATTEMPTS):
            head = self._policy.get_latest_control()
            current = self._policy.get_effective_control(at)
            if current.control_revision > head.control_revision:
                continue
            if current.control_revision != head.control_revision and not (
                head.expires_at is not None and head.expires_at <= at
            ):
                raise SafetyControlConflict("policy safety durable head is not effective")
            if (
                current.created_by_actor_ref == SAFETY_CONTROLLER_REF
                and current.reason_codes == reason_codes
            ):
                return current
            target = _NEXT_SAFER[current.autonomy_mode]
            if target is current.autonomy_mode:
                return current
            replacement = self._append_safer(
                current,
                head=head,
                at=at,
                target=target,
                kill_switch=current.kill_switch,
                read_only=current.read_only,
                reason_codes=reason_codes,
            )
            if replacement is not None:
                return replacement
        raise SafetyControlConflict("policy safety control changed concurrently")

    def critical_stop(
        self, *, at: dt.datetime, reason_codes: tuple[str, ...]
    ) -> PolicyControlSnapshot:
        for _attempt in range(MAX_CONTROL_APPEND_ATTEMPTS):
            head = self._policy.get_latest_control()
            current = self._policy.get_effective_control(at)
            if current.control_revision > head.control_revision:
                continue
            if self._is_exact_critical_stop(current):
                return current
            replacement = self._append_safer(
                current,
                head=head,
                at=at,
                target=AutonomyMode.SHADOW,
                kill_switch=True,
                read_only=True,
                reason_codes=reason_codes,
            )
            if replacement is not None:
                return replacement
            winner = self._policy.get_effective_control(at)
            if self._is_exact_critical_stop(winner):
                return winner
        raise SafetyControlConflict("policy critical stop changed concurrently")

    def _append_safer(
        self,
        current: PolicyControlSnapshot,
        *,
        head: PolicyControlSnapshot,
        at: dt.datetime,
        target: AutonomyMode,
        kill_switch: bool,
        read_only: bool,
        reason_codes: tuple[str, ...],
    ) -> PolicyControlSnapshot | None:
        revision = head.control_revision + 1
        payload = {
            "previous": current.policy_snapshot_id,
            "durable_head": head.policy_snapshot_id,
            "control_revision": revision,
            "target": target.value,
            "kill_switch": kill_switch,
            "read_only": read_only,
            "reason_codes": reason_codes,
            "effective_at": at.isoformat(),
        }
        fingerprint = canonical_fingerprint("policy-safety-control:v2", payload)
        values = current.model_dump(mode="python")
        values.update(
            {
                "policy_snapshot_id": fingerprint,
                "control_revision": revision,
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
            replacement = PolicyControlSnapshot.model_validate(values)
        except (ValueError, ValidationError):
            raise SafetyControlConflict("policy safety control is invalid") from None
        if self._policy.append_control_if_latest(
            replacement,
            expected_latest_revision=head.control_revision,
        ):
            return replacement
        return None

    @staticmethod
    def _is_exact_critical_stop(control: PolicyControlSnapshot) -> bool:
        return (
            control.autonomy_mode is AutonomyMode.SHADOW
            and control.shadow_target_mode is AutonomyMode.ASSISTED
            and control.kill_switch
            and control.read_only
            and control.expires_at is None
        )
