from __future__ import annotations

from decimal import Decimal

import pytest

from signals.chief_of_staff.config import (
    ChiefOfStaffConfigurationState,
    chief_of_staff_config_from_environment,
)

COMPLETE = {
    "KIVOU_MODEL_CHIEF_OF_STAFF": "anthropic/claude-sonnet-4.6",
    "KIVOU_MODEL_BUDGET_CHIEF_OF_STAFF_USD": "1.25",
    "KIVOU_MODEL_RESERVE_INPUT_CHIEF_OF_STAFF_USD_PER_MILLION": "6",
    "KIVOU_MODEL_RESERVE_OUTPUT_CHIEF_OF_STAFF_USD_PER_MILLION": "30",
}


def test_absent_configuration_is_not_configured_without_defaults() -> None:
    config = chief_of_staff_config_from_environment({})
    assert config.state is ChiefOfStaffConfigurationState.NOT_CONFIGURED
    assert config.route is None


def test_complete_configuration_builds_distinct_model_route() -> None:
    config = chief_of_staff_config_from_environment(COMPLETE)
    assert config.state is ChiefOfStaffConfigurationState.CONFIGURED
    assert config.route is not None
    assert config.route.usage == "chief_of_staff"
    assert config.route.model == "anthropic/claude-sonnet-4.6"
    assert config.route.daily_budget_usd == Decimal("1.25")
    assert config.route.reserve_input_usd_per_million == Decimal("6")
    assert config.route.reserve_output_usd_per_million == Decimal("30")


def test_partial_or_invalid_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="all be configured"):
        chief_of_staff_config_from_environment(
            {"KIVOU_MODEL_CHIEF_OF_STAFF": "anthropic/claude-sonnet-4.6"}
        )
    with pytest.raises(ValueError, match="finite non-negative"):
        chief_of_staff_config_from_environment(
            {**COMPLETE, "KIVOU_MODEL_BUDGET_CHIEF_OF_STAFF_USD": "NaN"}
        )

