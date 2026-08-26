from __future__ import annotations

import json
from pathlib import Path

import pytest

from signals.acquisition_connectivity.config import (
    REQUIRED_ENVIRONMENT_VARIABLES,
    load_connectivity_config,
)
from signals.acquisition_connectivity.contracts import ConnectivityErrorCode, ConnectivityFailure


def _deployment(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "acquisition-shadow-connectivity-v1",
        "instantly_workspace_ref": "workspace-staging-ref",
        "mailboxes": [
            {
                "mailbox_ref": "mailbox-staging-01",
                "provider_account_id": "one@example.com",
            },
            {
                "mailbox_ref": "mailbox-staging-02",
                "provider_account_id": "two@example.com",
            },
            {
                "mailbox_ref": "mailbox-staging-03",
                "provider_account_id": "three@example.com",
            },
        ],
    }
    value.update(updates)
    return value


def _environment(tmp_path: Path, document: dict[str, object] | None = None) -> dict[str, str]:
    config_path = tmp_path / "acquisition-shadow.json"
    config_path.write_text(json.dumps(document or _deployment()), encoding="utf-8")
    hermes_python = tmp_path / "hermes-python"
    hermes_python.write_text("fixture", encoding="utf-8")
    hermes_home = tmp_path / "hermes-home"
    hermes_cwd = tmp_path / "hermes-work"
    hermes_home.mkdir(exist_ok=True)
    hermes_cwd.mkdir(exist_ok=True)
    return {
        "KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
        "KIVOU_ACQUISITION_SHADOW_CONFIG": str(config_path),
        "KIVOU_APOLLO_API_KEY": "synthetic-apollo-value",
        "KIVOU_INSTANTLY_API_KEY": "synthetic-instantly-value",
        "KIVOU_HERMES_PYTHON": str(hermes_python),
        "KIVOU_HERMES_HOME": str(hermes_home),
        "KIVOU_HERMES_CWD": str(hermes_cwd),
    }


def test_complete_configuration_is_strict_and_keeps_secrets_opaque(tmp_path: Path) -> None:
    environment = _environment(tmp_path)

    config = load_connectivity_config(environment)

    assert config.environment == "STAGING"
    assert config.deployment.schema_version == "acquisition-shadow-connectivity-v1"
    assert len(config.deployment.mailboxes) == 3
    assert config.apollo_api_key.get_secret_value() == "synthetic-apollo-value"
    assert "synthetic-apollo-value" not in repr(config)
    assert "one@example.com" not in repr(config)


@pytest.mark.parametrize("gap_minutes", [1, 10, 1_440])
def test_managed_airmail_sending_gap_minutes_accepts_strict_bounded_integers(
    tmp_path: Path, gap_minutes: int
) -> None:
    mailboxes = _deployment()["mailboxes"]
    mailboxes[0] = {
        **mailboxes[0],
        "managed_airmail_sending_gap_minutes": gap_minutes,
    }

    config = load_connectivity_config(
        _environment(tmp_path, _deployment(mailboxes=mailboxes))
    )

    assert (
        config.deployment.mailboxes[0].managed_airmail_sending_gap_minutes
        == gap_minutes
    )


@pytest.mark.parametrize("gap_minutes", [0, -1, 1_441, True, "10", 10.0])
def test_managed_airmail_sending_gap_minutes_rejects_invalid_values_without_identity_leakage(
    tmp_path: Path, gap_minutes: object
) -> None:
    mailboxes = _deployment()["mailboxes"]
    mailboxes[0] = {
        **mailboxes[0],
        "managed_airmail_sending_gap_minutes": gap_minutes,
    }

    with pytest.raises(ConnectivityFailure) as caught:
        load_connectivity_config(
            _environment(tmp_path, _deployment(mailboxes=mailboxes))
        )

    assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED
    assert "mailbox-staging-01" not in str(caught.value)
    assert "@" not in str(caught.value)


def test_old_v1_document_loads_with_managed_airmail_sending_gap_minutes_unset(
    tmp_path: Path,
) -> None:
    config = load_connectivity_config(_environment(tmp_path))

    assert all(
        mailbox.managed_airmail_sending_gap_minutes is None
        for mailbox in config.deployment.mailboxes
    )


def test_required_environment_vocabulary_is_exact() -> None:
    assert REQUIRED_ENVIRONMENT_VARIABLES == (
        "KIVOU_ACQUISITION_ENVIRONMENT",
        "KIVOU_ACQUISITION_SHADOW_CONFIG",
        "KIVOU_APOLLO_API_KEY",
        "KIVOU_INSTANTLY_API_KEY",
        "KIVOU_HERMES_PYTHON",
        "KIVOU_HERMES_HOME",
        "KIVOU_HERMES_CWD",
    )


@pytest.mark.parametrize("name", REQUIRED_ENVIRONMENT_VARIABLES)
@pytest.mark.parametrize("replacement", [None, "", "   "])
def test_every_missing_or_empty_variable_fails_closed(
    tmp_path: Path, name: str, replacement: str | None
) -> None:
    environment = _environment(tmp_path)
    if replacement is None:
        environment.pop(name)
    else:
        environment[name] = replacement

    with pytest.raises(ConnectivityFailure) as caught:
        load_connectivity_config(environment)

    assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED
    assert "synthetic-" not in str(caught.value)
    assert "@" not in str(caught.value)


def test_environment_must_be_exactly_staging(tmp_path: Path) -> None:
    for value in ("PRODUCTION", "SHADOW", "staging", "UNCONFIGURED"):
        environment = _environment(tmp_path)
        environment["KIVOU_ACQUISITION_ENVIRONMENT"] = value

        with pytest.raises(ConnectivityFailure) as caught:
            load_connectivity_config(environment)

        assert caught.value.code is ConnectivityErrorCode.WRONG_ENVIRONMENT


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": "other"},
        {"unknown": True},
        {"instantly_workspace_ref": ""},
        {"instantly_workspace_ref": "x" * 257},
        {"mailboxes": _deployment()["mailboxes"][:2]},
        {
            "mailboxes": [
                *_deployment()["mailboxes"],
                {
                    "mailbox_ref": "mailbox-staging-04",
                    "provider_account_id": "four@example.com",
                },
            ]
        },
        {
            "mailboxes": [
                _deployment()["mailboxes"][0],
                _deployment()["mailboxes"][0],
                _deployment()["mailboxes"][2],
            ]
        },
        {
            "mailboxes": [
                _deployment()["mailboxes"][0],
                {
                    "mailbox_ref": "mailbox-staging-02",
                    "provider_account_id": "one@example.com",
                },
                _deployment()["mailboxes"][2],
            ]
        },
        {
            "mailboxes": [
                {
                    **_deployment()["mailboxes"][0],
                    "unexpected": "value",
                },
                *_deployment()["mailboxes"][1:],
            ]
        },
        {
            "mailboxes": [
                {
                    "mailbox_ref": "mailbox-staging-01",
                    "provider_account_id": "not-an-email",
                },
                *_deployment()["mailboxes"][1:],
            ]
        },
    ],
)
def test_deployment_document_is_closed_and_fail_closed(
    tmp_path: Path, update: dict[str, object]
) -> None:
    environment = _environment(tmp_path, _deployment(**update))

    with pytest.raises(ConnectivityFailure) as caught:
        load_connectivity_config(environment)

    assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED
    assert "@" not in str(caught.value)


@pytest.mark.parametrize("content", ["{", "[]", "null", "x" * 65_537])
def test_malformed_or_oversized_configuration_fails_closed(
    tmp_path: Path, content: str
) -> None:
    environment = _environment(tmp_path)
    Path(environment["KIVOU_ACQUISITION_SHADOW_CONFIG"]).write_text(
        content, encoding="utf-8"
    )

    with pytest.raises(ConnectivityFailure) as caught:
        load_connectivity_config(environment)

    assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED


def test_configuration_paths_must_be_absolute_and_document_must_exist(
    tmp_path: Path,
) -> None:
    for name in (
        "KIVOU_ACQUISITION_SHADOW_CONFIG",
        "KIVOU_HERMES_PYTHON",
        "KIVOU_HERMES_HOME",
        "KIVOU_HERMES_CWD",
    ):
        environment = _environment(tmp_path)
        environment[name] = "relative/path"
        with pytest.raises(ConnectivityFailure) as caught:
            load_connectivity_config(environment)
        assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED

    environment = _environment(tmp_path)
    environment["KIVOU_ACQUISITION_SHADOW_CONFIG"] = str(tmp_path / "missing.json")
    with pytest.raises(ConnectivityFailure) as caught:
        load_connectivity_config(environment)
    assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED
