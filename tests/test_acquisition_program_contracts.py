"""Versioned acquisition programs remain disabled until explicitly activated."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from signals.acquisition_programs.config import load_program_config, runtime_flags
from signals.acquisition_programs.contracts import AcquisitionProgramConfig

EXAMPLE = Path(__file__).resolve().parents[1] / "ops/examples/milomail-acquisition.json.example"


def test_milomail_example_is_a_closed_shadow_program() -> None:
    config = load_program_config(EXAMPLE)
    assert config.program_key == "milomail"
    assert config.product_name == "Milo Mail"
    assert config.offer_key == "gmail_free_audit"
    assert config.available_plan == "milo_clean"
    assert config.coming_soon_plans == ("milo_pro", "milo_agent")
    assert config.target_country == "FR"
    assert config.target_locale == "fr-FR"
    assert config.target_company_size_min == 1
    assert config.target_company_size_max == 10
    assert config.allowed_mail_providers == ("GOOGLE_WORKSPACE",)
    assert config.campaign_mode == "SHADOW"
    assert config.enabled is False
    assert config.max_daily_contacts == 0
    assert config.max_monthly_contacts == 0
    assert config.max_cost_chf == 0
    assert config.bounce_alert_threshold == Decimal("0.02")
    assert config.complaint_alert_threshold == Decimal("0.001")
    assert config.unknown_provider_alert_threshold == Decimal("0.25")
    assert config.landing_url is None
    assert config.sender_domains == ()


def test_runtime_flags_default_closed_and_reject_partial_activation() -> None:
    flags = runtime_flags({})
    assert flags.enabled is False
    assert flags.mode == "SHADOW"
    assert flags.max_daily_contacts == 0
    assert flags.max_monthly_contacts == 0
    assert flags.max_cost_chf == 0
    with pytest.raises(ValueError, match="SHADOW"):
        runtime_flags({"MILOMAIL_ACQUISITION_ENABLED": "true"})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MILOMAIL_ALLOWED_COUNTRIES", "FR,DE"),
        ("MILOMAIL_ALLOWED_PROVIDERS", "GOOGLE_WORKSPACE,MICROSOFT_365"),
    ],
)
def test_runtime_flags_reject_unreviewed_country_or_provider(name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        runtime_flags({name: value})


def test_program_rejects_non_https_landing_and_sender_on_main_domain() -> None:
    raw = load_program_config(EXAMPLE).model_dump(mode="python")
    with pytest.raises(ValidationError):
        AcquisitionProgramConfig.model_validate({**raw, "landing_url": "http://example.fr/audit"})
    with pytest.raises(ValidationError):
        AcquisitionProgramConfig.model_validate(
            {**raw, "sender_domains": ("mail.example.fr",), "transactional_domain": "example.fr"}
        )
