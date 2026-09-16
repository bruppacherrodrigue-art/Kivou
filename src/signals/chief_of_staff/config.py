"""Explicit fail-closed configuration for Chief of Staff model use."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from signals.model_runtime.config import ModelRoute

MODEL_ENV = "KIVOU_MODEL_CHIEF_OF_STAFF"
BUDGET_ENV = "KIVOU_MODEL_BUDGET_CHIEF_OF_STAFF_USD"
INPUT_RESERVE_ENV = "KIVOU_MODEL_RESERVE_INPUT_CHIEF_OF_STAFF_USD_PER_MILLION"
OUTPUT_RESERVE_ENV = "KIVOU_MODEL_RESERVE_OUTPUT_CHIEF_OF_STAFF_USD_PER_MILLION"
_VARIABLES = (MODEL_ENV, BUDGET_ENV, INPUT_RESERVE_ENV, OUTPUT_RESERVE_ENV)


class ChiefOfStaffConfigurationState(StrEnum):
    CONFIGURED = "CONFIGURED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass(frozen=True)
class ChiefOfStaffModelConfiguration:
    state: ChiefOfStaffConfigurationState
    route: ModelRoute | None


def _amount(value: str, *, name: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a finite non-negative decimal") from exc
    if not value.strip() or not result.is_finite() or result < 0:
        raise ValueError(f"{name} must be a finite non-negative decimal")
    return result


def chief_of_staff_config_from_environment(
    environment: Mapping[str, str] | None = None,
) -> ChiefOfStaffModelConfiguration:
    values = os.environ if environment is None else environment
    present = tuple(name for name in _VARIABLES if values.get(name, "").strip())
    if not present:
        return ChiefOfStaffModelConfiguration(
            state=ChiefOfStaffConfigurationState.NOT_CONFIGURED,
            route=None,
        )
    if len(present) != len(_VARIABLES):
        raise ValueError("Chief of Staff model variables must all be configured")
    model = values[MODEL_ENV].strip()
    if len(model) > 160:
        raise ValueError(f"{MODEL_ENV} must contain at most 160 characters")
    return ChiefOfStaffModelConfiguration(
        state=ChiefOfStaffConfigurationState.CONFIGURED,
        route=ModelRoute(
            usage="chief_of_staff",
            model=model,
            daily_budget_usd=_amount(values[BUDGET_ENV], name=BUDGET_ENV),
            reserve_input_usd_per_million=_amount(
                values[INPUT_RESERVE_ENV], name=INPUT_RESERVE_ENV
            ),
            reserve_output_usd_per_million=_amount(
                values[OUTPUT_RESERVE_ENV], name=OUTPUT_RESERVE_ENV
            ),
        ),
    )


__all__ = [
    "BUDGET_ENV",
    "INPUT_RESERVE_ENV",
    "MODEL_ENV",
    "OUTPUT_RESERVE_ENV",
    "ChiefOfStaffConfigurationState",
    "ChiefOfStaffModelConfiguration",
    "chief_of_staff_config_from_environment",
]
