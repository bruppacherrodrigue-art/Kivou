"""Écriture explicite du tout premier contrôle Policy d'un environnement."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.operations.contracts import canonical_fingerprint
from signals.operations.qa_policy_window import RUNTIME_COMMANDS
from signals.policy.contracts import (
    AutonomyMode,
    PolicyControlSnapshot,
    PolicyControlUnavailable,
)
from signals.policy.store import PolicyStore


class PolicyBootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(f"policy bootstrap error: {code}")
        self.code = code


def bootstrap_policy_control(
    engine: Engine,
    *,
    at: dt.datetime,
    actor_ref: str,
    reason_code: str,
    daily_cost_cap: Decimal,
    country: str,
    language: str,
    wedge: str,
) -> PolicyControlSnapshot:
    """Pose une autorité NON exécutable. Ce n'est pas un levier d'activation.

    Le mode reste SHADOW, la lecture seule et le coupe-circuit sont armés, et le
    plafond de volume vaut zéro. Le coupe-circuit n'entrave pas le cycle
    d'observation : il laisse passer les classes READ_ONLY, PREPARATORY,
    RISK_REDUCTION et HUMAN_REVIEW, et tout le cycle est PREPARATORY.
    """

    if at.tzinfo is None or at.utcoffset() is None:
        raise PolicyBootstrapError("TIMESTAMP_NOT_AWARE")
    if country not in {"CH", "FR"} or language not in {"fr", "en"} or not wedge:
        raise PolicyBootstrapError("SCOPE_INVALID")
    if not daily_cost_cap.is_finite() or daily_cost_cap <= 0:
        raise PolicyBootstrapError("COST_CAP_INVALID")
    store = PolicyStore(engine)
    try:
        store.get_latest_control()
    except PolicyControlUnavailable:
        pass
    else:
        raise PolicyBootstrapError("CONTROL_ALREADY_EXISTS")
    observed_at = at.astimezone(dt.UTC)
    fingerprint = canonical_fingerprint(
        "acquisition-policy-bootstrap:v1",
        {
            "control_revision": 1,
            "autonomy_mode": AutonomyMode.SHADOW.value,
            "shadow_target_mode": AutonomyMode.ASSISTED.value,
            "country": country,
            "language": language,
            "wedge": wedge,
            "currency": "CHF",
            "daily_cost_cap": str(daily_cost_cap),
            "effective_at": observed_at.isoformat(),
            "actor_ref": actor_ref,
            "reason_codes": (reason_code,),
        },
    )
    try:
        control = PolicyControlSnapshot(
            policy_snapshot_id=fingerprint,
            control_revision=1,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.ASSISTED,
            read_only=True,
            kill_switch=True,
            allowed_commands=RUNTIME_COMMANDS,
            allowed_countries=(country,),
            allowed_languages=(language,),
            allowed_wedges=(wedge,),
            currency="CHF",
            daily_cost_cap=daily_cost_cap,
            daily_volume_cap=0,
            effective_at=observed_at,
            snapshot_fingerprint=fingerprint,
            created_at=observed_at,
            created_by_actor_type="HUMAN",
            created_by_actor_ref=actor_ref,
            reason_codes=(reason_code,),
        )
    except (ValidationError, ValueError):
        raise PolicyBootstrapError("CONTROL_INVALID") from None
    store.append_control(control)
    return control


__all__ = ["PolicyBootstrapError", "bootstrap_policy_control"]
