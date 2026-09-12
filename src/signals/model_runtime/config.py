"""Batch-scoped model routes and daily safety caps."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

ModelUsage = Literal[
    "enrichment_judge",
    "enrichment_arbiter",
    "for_you",
    "hermes",
    "document_classifier",
]

MODEL_USAGES: tuple[ModelUsage, ...] = (
    "enrichment_judge",
    "enrichment_arbiter",
    "for_you",
    "hermes",
    "document_classifier",
)
MODEL_TIMEZONE = "Europe/Zurich"

_DEFAULT_MODELS: dict[ModelUsage, str] = {
    "enrichment_judge": "mistralai/mistral-small",
    "enrichment_arbiter": "anthropic/claude-sonnet-4.6",
    "for_you": "anthropic/claude-sonnet-4.6",
    "hermes": "anthropic/claude-sonnet-4.6",
    "document_classifier": "anthropic/claude-sonnet-4.6",
}
_DEFAULT_BUDGETS: dict[ModelUsage, Decimal] = {
    "enrichment_judge": Decimal("2"),
    "enrichment_arbiter": Decimal("1"),
    "for_you": Decimal("1"),
    "hermes": Decimal("1"),
    "document_classifier": Decimal("1"),
}
_DEFAULT_RESERVATION_RATES: dict[ModelUsage, tuple[Decimal, Decimal]] = {
    "enrichment_judge": (Decimal("0.20"), Decimal("0.60")),
    "enrichment_arbiter": (Decimal("6"), Decimal("30")),
    "for_you": (Decimal("6"), Decimal("30")),
    "hermes": (Decimal("6"), Decimal("30")),
    "document_classifier": (Decimal("6"), Decimal("30")),
}


def model_environment_name(usage: ModelUsage) -> str:
    return f"KIVOU_MODEL_{usage.upper()}"


def budget_environment_name(usage: ModelUsage) -> str:
    return f"KIVOU_MODEL_BUDGET_{usage.upper()}_USD"


def reservation_environment_name(usage: ModelUsage, direction: str) -> str:
    if direction not in {"INPUT", "OUTPUT"}:
        raise ValueError("reservation direction must be INPUT or OUTPUT")
    return f"KIVOU_MODEL_RESERVE_{direction}_{usage.upper()}_USD_PER_MILLION"


@dataclass(frozen=True)
class ModelRoute:
    usage: ModelUsage
    model: str
    daily_budget_usd: Decimal
    reserve_input_usd_per_million: Decimal = Decimal("6")
    reserve_output_usd_per_million: Decimal = Decimal("30")


@dataclass(frozen=True)
class ModelRouteSnapshot:
    batch_id: str
    routes: tuple[ModelRoute, ...]
    timezone: str = MODEL_TIMEZONE

    def route(self, usage: ModelUsage) -> ModelRoute:
        for route in self.routes:
            if route.usage == usage:
                return route
        raise ValueError(f"unknown model usage: {usage}")


def _budget(value: str | None, *, usage: ModelUsage) -> Decimal:
    name = budget_environment_name(usage)
    if value is None:
        return _DEFAULT_BUDGETS[usage]
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a finite non-negative decimal") from error
    if not parsed.is_finite() or parsed < 0 or not value.strip():
        raise ValueError(f"{name} must be a finite non-negative decimal")
    return parsed


def _reservation_rate(
    value: str | None, *, usage: ModelUsage, direction: str
) -> Decimal:
    name = reservation_environment_name(usage, direction)
    default_index = 0 if direction == "INPUT" else 1
    if value is None:
        return _DEFAULT_RESERVATION_RATES[usage][default_index]
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a finite non-negative decimal") from error
    if not parsed.is_finite() or parsed < 0 or not value.strip():
        raise ValueError(f"{name} must be a finite non-negative decimal")
    return parsed


def routes_from_environment(
    *,
    batch_id: str,
    environment: Mapping[str, str] | None = None,
) -> ModelRouteSnapshot:
    """Read routes once; callers retain the returned snapshot for the whole lot."""

    normalized_batch_id = batch_id.strip()
    if not normalized_batch_id or len(normalized_batch_id) > 64:
        raise ValueError("batch_id must contain between 1 and 64 characters")
    values = os.environ if environment is None else environment
    routes: list[ModelRoute] = []
    for usage in MODEL_USAGES:
        model_name = model_environment_name(usage)
        model = values.get(model_name, _DEFAULT_MODELS[usage]).strip()
        if not model or len(model) > 160:
            raise ValueError(f"{model_name} must contain between 1 and 160 characters")
        routes.append(
            ModelRoute(
                usage=cast(ModelUsage, usage),
                model=model,
                daily_budget_usd=_budget(
                    values.get(budget_environment_name(usage)), usage=usage
                ),
                reserve_input_usd_per_million=_reservation_rate(
                    values.get(reservation_environment_name(usage, "INPUT")),
                    usage=usage,
                    direction="INPUT",
                ),
                reserve_output_usd_per_million=_reservation_rate(
                    values.get(reservation_environment_name(usage, "OUTPUT")),
                    usage=usage,
                    direction="OUTPUT",
                ),
            )
        )
    return ModelRouteSnapshot(batch_id=normalized_batch_id, routes=tuple(routes))


__all__ = [
    "MODEL_TIMEZONE",
    "MODEL_USAGES",
    "ModelRoute",
    "ModelRouteSnapshot",
    "ModelUsage",
    "budget_environment_name",
    "model_environment_name",
    "reservation_environment_name",
    "routes_from_environment",
]
