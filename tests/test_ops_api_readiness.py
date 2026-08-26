from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
READINESS_HELPER = ROOT / "ops" / "bin" / "kivou-api-readiness.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _fake_environment(tmp_path: Path, systemctl_body: str) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    calls.touch()

    _write_executable(
        fake_bin / "sudo",
        "#!/bin/sh\n"
        "printf 'sudo\\n' >>\"$KIVOU_TEST_CALLS\"\n"
        "exit 99\n",
    )
    _write_executable(fake_bin / "systemctl", systemctl_body)
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\n"
        "printf 'curl\\n' >>\"$KIVOU_TEST_CALLS\"\n"
        "printf '%s' \"${KIVOU_TEST_CURL_STATUS:-503}\"\n"
        "exit \"${KIVOU_TEST_CURL_EXIT:-0}\"\n",
    )
    _write_executable(
        fake_bin / "sleep",
        "#!/bin/sh\n"
        "printf 'sleep\\n' >>\"$KIVOU_TEST_CALLS\"\n",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment["KIVOU_TEST_CALLS"] = str(calls)
    return environment, calls


def _run_helper(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert READINESS_HELPER.is_file()
    return subprocess.run(
        [str(READINESS_HELPER), "kivou-api.service", "8000"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=2,
    )


def test_api_readiness_is_bounded_and_fails_after_five_attempts(
    tmp_path: Path,
) -> None:
    environment, calls = _fake_environment(
        tmp_path,
        "#!/bin/sh\n"
        "printf 'systemctl\\n' >>\"$KIVOU_TEST_CALLS\"\n"
        "exit 0\n",
    )

    result = _run_helper(environment)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "api_readiness=timeout unit=kivou-api.service attempts=5\n"
    )
    call_log = calls.read_text(encoding="utf-8").splitlines()
    assert call_log.count("systemctl") == 5
    assert call_log.count("curl") == 5
    assert call_log.count("sleep") == 4
    assert call_log.count("sudo") == 0
    helper_source = READINESS_HELPER.read_text(encoding="utf-8")
    assert "set -euo pipefail" in helper_source
    assert "--connect-timeout 1 --max-time 1" in helper_source
    assert "while true" not in helper_source


def test_api_readiness_succeeds_as_soon_as_openapi_returns_200(
    tmp_path: Path,
) -> None:
    environment, calls = _fake_environment(
        tmp_path,
        "#!/bin/sh\n"
        "printf 'systemctl\\n' >>\"$KIVOU_TEST_CALLS\"\n"
        "exit 0\n",
    )
    environment["KIVOU_TEST_CURL_STATUS"] = "200"

    result = _run_helper(environment)

    assert result.returncode == 0
    assert result.stdout == (
        "api_readiness=ready unit=kivou-api.service port=8000 attempt=1\n"
    )
    assert result.stderr == ""
    call_log = calls.read_text(encoding="utf-8").splitlines()
    assert call_log.count("systemctl") == 1
    assert call_log.count("curl") == 1
    assert call_log.count("sleep") == 0


def test_api_readiness_never_accepts_200_from_a_failed_curl(tmp_path: Path) -> None:
    environment, calls = _fake_environment(
        tmp_path,
        "#!/bin/sh\n"
        "printf 'systemctl\\n' >>\"$KIVOU_TEST_CALLS\"\n"
        "exit 0\n",
    )
    environment["KIVOU_TEST_CURL_STATUS"] = "200"
    environment["KIVOU_TEST_CURL_EXIT"] = "28"

    result = _run_helper(environment)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "api_readiness=timeout unit=kivou-api.service attempts=5\n"
    )
    call_log = calls.read_text(encoding="utf-8").splitlines()
    assert call_log.count("curl") == 5
    assert call_log.count("sleep") == 4


def test_api_readiness_bounds_the_service_state_check(tmp_path: Path) -> None:
    environment, calls = _fake_environment(
        tmp_path,
        "#!/bin/sh\n"
        "printf 'systemctl\\n' >>\"$KIVOU_TEST_CALLS\"\n"
        "exec /bin/sleep 5\n",
    )

    try:
        result = _run_helper(environment)
    except subprocess.TimeoutExpired:
        pytest.fail("the systemctl state check exceeded its finite bound")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "api_readiness=service_inactive unit=kivou-api.service attempt=1\n"
    )
    call_log = calls.read_text(encoding="utf-8").splitlines()
    assert call_log.count("systemctl") == 1
    assert call_log.count("curl") == 0


def test_api_readiness_fails_immediately_if_service_stops(tmp_path: Path) -> None:
    environment, calls = _fake_environment(
        tmp_path,
        "#!/bin/sh\n"
        "printf 'systemctl\\n' >>\"$KIVOU_TEST_CALLS\"\n"
        "test \"$(grep -c '^systemctl$' \"$KIVOU_TEST_CALLS\")\" -lt 3\n",
    )

    result = _run_helper(environment)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "api_readiness=service_inactive unit=kivou-api.service attempt=3\n"
    )
    call_log = calls.read_text(encoding="utf-8").splitlines()
    assert call_log.count("systemctl") == 3
    assert call_log.count("curl") == 2
    assert call_log.count("sleep") == 2
