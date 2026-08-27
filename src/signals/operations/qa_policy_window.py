"""Bounded operator-only Policy window for one controlled staging QA cycle."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.engine import Engine

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeStage,
    MachineCode,
    OpaqueRef,
    require_aware,
)
from signals.api.config import resolve_acquisition_environment
from signals.operations.contracts import canonical_fingerprint
from signals.operations.safety_controller import SAFETY_CONTROLLER_REF
from signals.persistence.schema import (
    contract_award,
    opportunity_representation,
    source_event,
)
from signals.policy.contracts import (
    AutonomyMode,
    PolicyControlSnapshot,
    PolicyControlUnavailable,
)
from signals.policy.store import PolicyStore

MAXIMUM_QA_WINDOW = dt.timedelta(minutes=30)
MAXIMUM_QA_COST = Decimal("30")
QA_DAILY_VOLUME = 1
MAX_CONTROL_APPEND_ATTEMPTS = 3
QA_WINDOW_OPENED = "ACQUISITION_RUNTIME_QA_WINDOW_OPEN"
QA_WINDOW_CLOSED = "ACQUISITION_RUNTIME_QA_WINDOW_CLOSED"
RECOVERABLE_STOP_REASON = "OPERATOR_QA_STOP"
LEGACY_RECOVERABLE_STOP_REASON = "AUDIT_80_PRE_QA_STOP"
_RECOVERABLE_STOP_REASON_SETS = frozenset(
    {
        (RECOVERABLE_STOP_REASON,),
        (LEGACY_RECOVERABLE_STOP_REASON,),
    }
)
RUNTIME_COMMANDS = tuple(stage.command for stage in AcquisitionRuntimeStage)

_OPAQUE_REF = TypeAdapter(OpaqueRef)
_MACHINE_CODE = TypeAdapter(MachineCode)


class RuntimeQaPolicyWindowError(RuntimeError):
    """A safe, non-reflective refusal to change staging Policy authority."""


@dataclass(frozen=True)
class _QaAuthority:
    opportunity_key: str
    signal_ref: str
    country: str
    language: str
    wedge: str
    cost_cap: Decimal


class RuntimeQaPolicyWindowController:
    """Open ASSISTED briefly, then restore non-executable SHADOW authority.

    Both transitions require the explicit STAGING identity, one exact runtime
    opportunity and its operator-owned QA scope. The close transition may
    disarm a tested staging kill switch, but it always keeps SHADOW + READ ONLY;
    this controller has no path to an autonomous mode.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._policy = PolicyStore(engine)

    def open(
        self,
        *,
        at: dt.datetime,
        expires_at: dt.datetime,
        actor_ref: str,
        reason_code: str,
        runtime_config: AcquisitionRuntimeConfig,
    ) -> PolicyControlSnapshot:
        self._require_staging()
        authority = self._authority(runtime_config)
        self._verify_public_authority(authority)
        at = self._instant(at)
        expires_at = self._instant(expires_at)
        actor = self._actor(actor_ref)
        reason = self._reason(reason_code)
        if not at < expires_at <= at + MAXIMUM_QA_WINDOW:
            raise RuntimeQaPolicyWindowError("runtime QA policy expiry is invalid")

        for _attempt in range(MAX_CONTROL_APPEND_ATTEMPTS):
            head = self._latest()
            current = self._current(at)
            if current.control_revision > head.control_revision:
                continue
            if current.control_revision != head.control_revision and not (
                self._is_expected_expired_window(
                    head,
                    authority=authority,
                    at=at,
                )
            ):
                raise RuntimeQaPolicyWindowError("runtime QA policy durable head is unrelated")
            self._require_chf(current)
            if self._same_open_window(
                current,
                authority=authority,
                at=at,
                expires_at=expires_at,
                actor_ref=actor,
                reason_code=reason,
            ):
                return current
            if current.autonomy_mode is not AutonomyMode.SHADOW or not current.read_only:
                raise RuntimeQaPolicyWindowError("runtime QA policy cannot be opened")
            if current.kill_switch and current.created_by_actor_ref == SAFETY_CONTROLLER_REF:
                raise RuntimeQaPolicyWindowError(
                    "runtime QA policy critical stop must not be cleared"
                )
            replacement = self._append(
                current,
                head=head,
                authority=authority,
                at=at,
                expires_at=expires_at,
                actor_ref=actor,
                reason_codes=(QA_WINDOW_OPENED, reason),
                autonomy_mode=AutonomyMode.ASSISTED,
                shadow_target_mode=None,
                read_only=False,
            )
            if replacement is not None:
                return replacement
        raise RuntimeQaPolicyWindowError("runtime QA policy authority changed concurrently")

    def close(
        self,
        *,
        at: dt.datetime,
        actor_ref: str,
        reason_code: str,
        runtime_config: AcquisitionRuntimeConfig,
    ) -> PolicyControlSnapshot:
        self._require_staging()
        authority = self._authority(runtime_config)
        at = self._instant(at)
        actor = self._actor(actor_ref)
        reason = self._reason(reason_code)
        for _attempt in range(MAX_CONTROL_APPEND_ATTEMPTS):
            head = self._latest()
            current = self._current(at)
            if current.control_revision > head.control_revision:
                continue
            if current.control_revision != head.control_revision:
                raise RuntimeQaPolicyWindowError("runtime QA policy durable head is not effective")
            self._require_chf(current)
            if self._same_closed_window(current, authority=authority):
                return current
            if current.autonomy_mode is AutonomyMode.ASSISTED:
                if not self._same_qa_authority(current, authority=authority) or (
                    QA_WINDOW_OPENED not in current.reason_codes
                ):
                    raise RuntimeQaPolicyWindowError("runtime QA policy authority is unrelated")
            elif not self._recoverable_qa_stop(current, authority=authority):
                raise RuntimeQaPolicyWindowError("runtime QA policy authority is unsafe")
            replacement = self._append(
                current,
                head=head,
                authority=authority,
                at=at,
                expires_at=None,
                actor_ref=actor,
                reason_codes=(QA_WINDOW_CLOSED, reason),
                autonomy_mode=AutonomyMode.SHADOW,
                shadow_target_mode=AutonomyMode.ASSISTED,
                read_only=True,
            )
            if replacement is not None:
                return replacement
        raise RuntimeQaPolicyWindowError("runtime QA policy authority changed concurrently")

    def _append(
        self,
        current: PolicyControlSnapshot,
        *,
        head: PolicyControlSnapshot,
        authority: _QaAuthority,
        at: dt.datetime,
        expires_at: dt.datetime | None,
        actor_ref: str,
        reason_codes: tuple[str, ...],
        autonomy_mode: AutonomyMode,
        shadow_target_mode: AutonomyMode | None,
        read_only: bool,
    ) -> PolicyControlSnapshot | None:
        revision = head.control_revision + 1
        fingerprint = canonical_fingerprint(
            "acquisition-runtime-qa-policy-window:v3",
            {
                "previous": current.policy_snapshot_id,
                "durable_head": head.policy_snapshot_id,
                "control_revision": revision,
                "qa_signal_ref": authority.signal_ref,
                "autonomy_mode": autonomy_mode.value,
                "shadow_target_mode": (shadow_target_mode.value if shadow_target_mode else None),
                "read_only": read_only,
                "allowed_commands": RUNTIME_COMMANDS,
                "country": authority.country,
                "language": authority.language,
                "wedge": authority.wedge,
                "currency": "CHF",
                "daily_cost_cap": authority.cost_cap,
                "daily_volume_cap": QA_DAILY_VOLUME,
                "effective_at": at.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "actor_ref": actor_ref,
                "reason_codes": reason_codes,
            },
        )
        values = current.model_dump(mode="python")
        values.update(
            {
                "policy_snapshot_id": fingerprint,
                "control_revision": revision,
                "autonomy_mode": autonomy_mode,
                "shadow_target_mode": shadow_target_mode,
                "read_only": read_only,
                "kill_switch": False,
                "qa_signal_ref": authority.signal_ref,
                "allowed_commands": RUNTIME_COMMANDS,
                "allowed_countries": (authority.country,),
                "allowed_languages": (authority.language,),
                "allowed_wedges": (authority.wedge,),
                "currency": "CHF",
                "daily_cost_cap": authority.cost_cap,
                "daily_volume_cap": QA_DAILY_VOLUME,
                "effective_at": at,
                "expires_at": expires_at,
                "snapshot_fingerprint": fingerprint,
                "created_at": at,
                "created_by_actor_type": "HUMAN",
                "created_by_actor_ref": actor_ref,
                "reason_codes": reason_codes,
            }
        )
        try:
            replacement = PolicyControlSnapshot.model_validate(values)
        except (ValidationError, ValueError):
            raise RuntimeQaPolicyWindowError("runtime QA policy authority is invalid") from None
        try:
            if self._policy.append_control_if_latest(
                replacement,
                expected_latest_revision=head.control_revision,
            ):
                return replacement
        except sa.exc.SQLAlchemyError:
            raise RuntimeQaPolicyWindowError("runtime QA policy authority is unavailable") from None
        return None

    def _authority(self, runtime_config: AcquisitionRuntimeConfig) -> _QaAuthority:
        deployment = runtime_config.deployment
        if runtime_config.environment != "STAGING" or len(deployment.allowed_opportunity_keys) != 1:
            raise RuntimeQaPolicyWindowError("runtime QA policy requires one exact opportunity")
        scope = deployment.qa_scope
        opportunity_key = deployment.allowed_opportunity_keys[0]
        return _QaAuthority(
            opportunity_key=opportunity_key,
            signal_ref=f"procurement-opportunity:{opportunity_key}",
            country=scope.country,
            language=scope.language,
            wedge=scope.wedge,
            cost_cap=min(deployment.limits.maximum_cycle_cost, MAXIMUM_QA_COST),
        )

    def _verify_public_authority(self, authority: _QaAuthority) -> None:
        query = (
            sa.select(source_event.c.source_country)
            .select_from(
                opportunity_representation.join(
                    contract_award,
                    opportunity_representation.c.award_key == contract_award.c.award_key,
                ).join(
                    source_event,
                    contract_award.c.event_key == source_event.c.event_key,
                )
            )
            .where(opportunity_representation.c.opportunity_key == authority.opportunity_key)
            .distinct()
            .order_by(source_event.c.source_country)
        )
        try:
            with self._engine.connect() as connection:
                countries = tuple(connection.scalars(query).all())
        except sa.exc.SQLAlchemyError:
            raise RuntimeQaPolicyWindowError(
                "runtime QA public opportunity is unavailable"
            ) from None
        if countries != (authority.country,):
            raise RuntimeQaPolicyWindowError(
                "runtime QA public opportunity does not match its exact scope"
            )

    def _current(self, at: dt.datetime) -> PolicyControlSnapshot:
        try:
            return self._policy.get_effective_control(at)
        except (PolicyControlUnavailable, sa.exc.SQLAlchemyError, ValueError):
            raise RuntimeQaPolicyWindowError("runtime QA policy authority is unavailable") from None

    def _latest(self) -> PolicyControlSnapshot:
        try:
            return self._policy.get_latest_control()
        except (PolicyControlUnavailable, sa.exc.SQLAlchemyError, ValueError):
            raise RuntimeQaPolicyWindowError("runtime QA policy authority is unavailable") from None

    def _recoverable_qa_stop(
        self,
        control: PolicyControlSnapshot,
        *,
        authority: _QaAuthority,
    ) -> bool:
        if not (
            control.autonomy_mode is AutonomyMode.SHADOW
            and control.shadow_target_mode is AutonomyMode.ASSISTED
            and control.read_only
            and control.kill_switch
            and control.expires_at is None
            and control.created_by_actor_type == "SYSTEM"
            and control.created_by_actor_ref == SAFETY_CONTROLLER_REF
            and control.reason_codes in _RECOVERABLE_STOP_REASON_SETS
            and self._same_qa_authority(control, authority=authority)
        ):
            return False
        try:
            previous = self._policy.get_previous_control(control.control_revision)
        except (PolicyControlUnavailable, sa.exc.SQLAlchemyError, ValueError):
            return False
        return self._same_closed_window(previous, authority=authority)

    @staticmethod
    def _require_chf(control: PolicyControlSnapshot) -> None:
        if control.currency != "CHF":
            raise RuntimeQaPolicyWindowError("runtime QA policy requires CHF authority")

    @staticmethod
    def _require_staging() -> None:
        try:
            environment = resolve_acquisition_environment()
        except ValueError:
            raise RuntimeQaPolicyWindowError("runtime QA policy environment is invalid") from None
        if environment != "STAGING":
            raise RuntimeQaPolicyWindowError("runtime QA policy is restricted to staging")

    @staticmethod
    def _instant(value: dt.datetime) -> dt.datetime:
        try:
            return require_aware(value)
        except ValueError:
            raise RuntimeQaPolicyWindowError("runtime QA policy timestamp is invalid") from None

    @staticmethod
    def _actor(value: str) -> str:
        try:
            return _OPAQUE_REF.validate_python(value)
        except ValidationError:
            raise RuntimeQaPolicyWindowError("runtime QA policy actor is invalid") from None

    @staticmethod
    def _reason(value: str) -> str:
        try:
            return _MACHINE_CODE.validate_python(value)
        except ValidationError:
            raise RuntimeQaPolicyWindowError("runtime QA policy reason is invalid") from None

    @staticmethod
    def _same_qa_authority(
        control: PolicyControlSnapshot,
        *,
        authority: _QaAuthority,
    ) -> bool:
        return (
            control.allowed_commands == RUNTIME_COMMANDS
            and control.qa_signal_ref == authority.signal_ref
            and control.allowed_countries == (authority.country,)
            and control.allowed_languages == (authority.language,)
            and control.allowed_wedges == (authority.wedge,)
            and control.currency == "CHF"
            and control.daily_cost_cap == authority.cost_cap
            and control.daily_volume_cap == QA_DAILY_VOLUME
        )

    @classmethod
    def _same_open_window(
        cls,
        control: PolicyControlSnapshot,
        *,
        authority: _QaAuthority,
        at: dt.datetime,
        expires_at: dt.datetime,
        actor_ref: str,
        reason_code: str,
    ) -> bool:
        return (
            control.autonomy_mode is AutonomyMode.ASSISTED
            and control.shadow_target_mode is None
            and not control.read_only
            and not control.kill_switch
            and cls._same_qa_authority(control, authority=authority)
            and control.effective_at <= at
            and control.expires_at == expires_at
            and control.created_by_actor_ref == actor_ref
            and control.reason_codes == (QA_WINDOW_OPENED, reason_code)
        )

    @classmethod
    def _is_expected_expired_window(
        cls,
        control: PolicyControlSnapshot,
        *,
        authority: _QaAuthority,
        at: dt.datetime,
    ) -> bool:
        return (
            control.autonomy_mode is AutonomyMode.ASSISTED
            and control.shadow_target_mode is None
            and not control.read_only
            and not control.kill_switch
            and cls._same_qa_authority(control, authority=authority)
            and control.effective_at <= at
            and control.expires_at is not None
            and control.expires_at <= at
            and control.created_by_actor_type == "HUMAN"
            and len(control.reason_codes) == 2
            and control.reason_codes[0] == QA_WINDOW_OPENED
        )

    @classmethod
    def _same_closed_window(
        cls,
        control: PolicyControlSnapshot,
        *,
        authority: _QaAuthority,
    ) -> bool:
        return (
            control.autonomy_mode is AutonomyMode.SHADOW
            and control.shadow_target_mode is AutonomyMode.ASSISTED
            and control.read_only
            and not control.kill_switch
            and cls._same_qa_authority(control, authority=authority)
            and control.expires_at is None
            and control.created_by_actor_type == "HUMAN"
            and QA_WINDOW_CLOSED in control.reason_codes
        )


__all__ = [
    "MAXIMUM_QA_WINDOW",
    "RuntimeQaPolicyWindowController",
    "RuntimeQaPolicyWindowError",
]
