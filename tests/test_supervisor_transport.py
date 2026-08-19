from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from signals.supervisor.contracts import SupervisorLimits
from signals.supervisor.runtime import (
    HealthState,
    SupervisorNotConfigured,
    SupervisorProtocolError,
    SupervisorSettings,
    SupervisorTimeout,
    SupervisorUnavailable,
)
from signals.supervisor.transport import SubprocessHermesTransport


def script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "bridge_fixture.py"
    path.write_text(body, encoding="utf-8")
    return path


def settings(tmp_path: Path, **limit_overrides) -> SupervisorSettings:
    home = tmp_path / "hermes-home"
    cwd = tmp_path / "hermes-cwd"
    home.mkdir(exist_ok=True)
    cwd.mkdir(exist_ok=True)
    return SupervisorSettings(
        hermes_python=Path(sys.executable),
        hermes_home=home,
        working_directory=cwd,
        limits=SupervisorLimits(**limit_overrides),
    )


def test_settings_require_explicit_kivou_paths_and_ignore_developer_hermes_home(tmp_path):
    developer_home = tmp_path / "developer-hermes"
    configured_home = tmp_path / "kivou-hermes"
    configured_cwd = tmp_path / "kivou-cwd"
    configured_home.mkdir()
    configured_cwd.mkdir()
    env = {
        "HERMES_HOME": str(developer_home),
        "KIVOU_HERMES_PYTHON": sys.executable,
        "KIVOU_HERMES_HOME": str(configured_home),
        "KIVOU_HERMES_CWD": str(configured_cwd),
        "KIVOU_HERMES_TIMEOUT_SECONDS": "7.5",
    }
    value = SupervisorSettings.from_environ(env)
    assert value.hermes_home == configured_home
    assert value.working_directory == configured_cwd
    assert value.limits.invocation_timeout_seconds == 7.5
    assert value.configuration_state() is HealthState.CONFIGURED


def test_missing_or_relative_runtime_paths_are_not_configured(tmp_path):
    value = SupervisorSettings.from_environ({})
    assert value.configuration_state() is HealthState.NOT_CONFIGURED
    with pytest.raises(SupervisorNotConfigured):
        value.require_configured()

    with pytest.raises(ValueError, match="absolute"):
        SupervisorSettings.from_environ(
            {
                "KIVOU_HERMES_PYTHON": "python",
                "KIVOU_HERMES_HOME": str(tmp_path),
                "KIVOU_HERMES_CWD": str(tmp_path),
            }
        )


def test_subprocess_receives_only_allowlisted_environment_and_dedicated_cwd(
    tmp_path, monkeypatch
):
    fixture = script(
        tmp_path,
        """
import json
import os
import sys

request = json.loads(sys.stdin.read())
print(json.dumps({
    "request": request,
    "environment": dict(os.environ),
    "cwd": os.getcwd(),
}))
""",
    )
    for name, value in {
        "DATABASE_URL": "postgresql://secret",
        "STRIPE_SECRET_KEY": "sk_live_secret",
        "GH_TOKEN": "github-secret",
        "SMTP_PASSWORD": "smtp-secret",
        "MCP_CONFIG": "/developer/mcp.json",
        "HERMES_HOME": "/developer/.hermes",
        "OPENAI_API_KEY": "developer-provider-secret",
    }.items():
        monkeypatch.setenv(name, value)

    configured = settings(tmp_path)
    result = SubprocessHermesTransport(configured, bridge_path=fixture).invoke(
        {"operation": "health"}
    )
    assert result["request"] == {"operation": "health"}
    assert result["cwd"] == str(configured.working_directory)
    assert result["environment"] == {
        "HOME": str(configured.hermes_home),
        "HERMES_HOME": str(configured.hermes_home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    }


def test_timeout_kills_the_bridge_and_returns_no_result(tmp_path):
    fixture = script(
        tmp_path,
        """
import time
time.sleep(10)
print('{}')
""",
    )
    configured = settings(tmp_path, invocation_timeout_seconds=0.05)
    started = time.monotonic()
    with pytest.raises(SupervisorTimeout, match="timed out"):
        SubprocessHermesTransport(configured, bridge_path=fixture).invoke({"operation": "plan"})
    assert time.monotonic() - started < 2


def test_oversized_or_malformed_bridge_output_fails_closed(tmp_path):
    oversized = script(tmp_path, "print('x' * 2048)")
    configured = settings(tmp_path, max_output_bytes=1024)
    with pytest.raises(SupervisorProtocolError, match="maximum"):
        SubprocessHermesTransport(configured, bridge_path=oversized).invoke(
            {"operation": "health"}
        )

    malformed = script(tmp_path, "print('not-json')")
    with pytest.raises(SupervisorProtocolError, match="valid JSON"):
        SubprocessHermesTransport(configured, bridge_path=malformed).invoke(
            {"operation": "health"}
        )


def test_bridge_failure_never_reflects_stderr_or_secret(tmp_path):
    fixture = script(
        tmp_path,
        """
import sys
sys.stderr.write('sk_live_must_not_escape')
raise SystemExit(7)
""",
    )
    with pytest.raises(SupervisorUnavailable) as caught:
        SubprocessHermesTransport(settings(tmp_path), bridge_path=fixture).invoke(
            {"operation": "health"}
        )
    assert "sk_live_must_not_escape" not in str(caught.value)
    assert caught.value.category == "unavailable"


def test_bridge_must_return_one_json_object(tmp_path):
    array = script(tmp_path, "print(json.dumps([]))\n")
    array.write_text("import json\nprint(json.dumps([]))\n", encoding="utf-8")
    with pytest.raises(SupervisorProtocolError, match="JSON object"):
        SubprocessHermesTransport(settings(tmp_path), bridge_path=array).invoke(
            {"operation": "health"}
        )
