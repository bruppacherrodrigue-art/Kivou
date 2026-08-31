from __future__ import annotations

import json
from pathlib import Path

import pytest

from signals.acquisition_connectivity.config import load_connectivity_config
from signals.acquisition_connectivity.contracts import ConnectivityFailure


def _deployment() -> dict[str, object]:
    return {
        "schema_version": "acquisition-shadow-connectivity-v1",
        "instantly_workspace_ref": "workspace-production-ref",
        "mailboxes": [
            {
                "mailbox_ref": "mailbox-production-01",
                "provider_account_id": "one@example.com",
            },
            {
                "mailbox_ref": "mailbox-production-02",
                "provider_account_id": "two@example.com",
            },
            {
                "mailbox_ref": "mailbox-production-03",
                "provider_account_id": "three@example.com",
            },
        ],
    }


def _environment(tmp_path: Path, environment_name: str) -> dict[str, str]:
    config_path = tmp_path / "acquisition-shadow.json"
    config_path.write_text(json.dumps(_deployment()), encoding="utf-8")
    hermes_python = tmp_path / "hermes-python"
    hermes_python.write_text("fixture", encoding="utf-8")
    hermes_home = tmp_path / "hermes-home"
    hermes_cwd = tmp_path / "hermes-work"
    hermes_home.mkdir(exist_ok=True)
    hermes_cwd.mkdir(exist_ok=True)
    return {
        "KIVOU_ACQUISITION_ENVIRONMENT": environment_name,
        "KIVOU_ACQUISITION_SHADOW_CONFIG": str(config_path),
        "KIVOU_APOLLO_API_KEY": "synthetic-apollo-value",
        "KIVOU_INSTANTLY_API_KEY": "synthetic-instantly-value",
        "KIVOU_HERMES_PYTHON": str(hermes_python),
        "KIVOU_HERMES_HOME": str(hermes_home),
        "KIVOU_HERMES_CWD": str(hermes_cwd),
    }


@pytest.fixture
def production_connectivity_environment(tmp_path: Path) -> dict[str, str]:
    return _environment(tmp_path, "PRODUCTION")


@pytest.fixture
def staging_connectivity_environment(tmp_path: Path) -> dict[str, str]:
    return _environment(tmp_path, "STAGING")


def test_production_connectivity_configuration_loads(production_connectivity_environment) -> None:
    config = load_connectivity_config(production_connectivity_environment)
    assert config.environment == "PRODUCTION"


def test_staging_connectivity_configuration_still_loads(staging_connectivity_environment) -> None:
    config = load_connectivity_config(staging_connectivity_environment)
    assert config.environment == "STAGING"


@pytest.mark.parametrize("value", ["production", "LOCAL", "", "UNCONFIGURED"])
def test_unknown_environments_are_still_refused(
    staging_connectivity_environment, value: str
) -> None:
    values = dict(staging_connectivity_environment)
    values["KIVOU_ACQUISITION_ENVIRONMENT"] = value
    with pytest.raises(ConnectivityFailure):
        load_connectivity_config(values)
