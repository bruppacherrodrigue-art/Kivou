from __future__ import annotations

from collections.abc import Callable

import pytest

from signals.acquisition_runtime import cli
from signals.acquisition_runtime.cli import main
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeRunResult,
    RuntimeRunStatus,
)


def _execute(result: RuntimeRunResult) -> tuple[Callable[[bool], RuntimeRunResult], list[bool]]:
    calls: list[bool] = []

    def run(allow_qa_provider_mutations: bool) -> RuntimeRunResult:
        calls.append(allow_qa_provider_mutations)
        return result

    return run, calls


def test_run_once_defaults_to_non_mutating_shadow_mode(capsys) -> None:
    execute, calls = _execute(
        RuntimeRunResult(
            status=RuntimeRunStatus.WAITING,
            cycle_ref="cycle-001",
            stage=AcquisitionRuntimeStage.PROVIDER_HANDOFF,
            reason_code="QA_PROVIDER_MUTATION_NOT_AUTHORIZED",
        )
    )

    exit_code = main(["run-once"], execute=execute)

    assert exit_code == 0
    assert calls == [False]
    assert capsys.readouterr().out == (
        "status=WAITING cycle_ref=cycle-001 stage=PROVIDER_HANDOFF "
        "reason=QA_PROVIDER_MUTATION_NOT_AUTHORIZED\n"
    )


def test_process_boundary_configures_closed_runtime_logging(monkeypatch) -> None:
    configured: list[bool] = []
    monkeypatch.setattr(
        cli,
        "configure_acquisition_runtime_logging",
        lambda: configured.append(True),
    )
    execute, _calls = _execute(
        RuntimeRunResult(status=RuntimeRunStatus.ALREADY_RUNNING)
    )

    assert main(["run-once"], execute=execute) == 0
    assert configured == [True]


def test_manual_provider_flag_is_explicit_and_current(capsys) -> None:
    execute, calls = _execute(
        RuntimeRunResult(
            status=RuntimeRunStatus.COMPLETED,
            cycle_ref="cycle-001",
        )
    )

    exit_code = main(
        ["run-once", "--allow-qa-provider-mutations"],
        execute=execute,
    )

    assert exit_code == 0
    assert calls == [True]
    assert capsys.readouterr().out == "status=COMPLETED cycle_ref=cycle-001\n"


def test_normal_concurrency_is_not_a_timer_failure(capsys) -> None:
    execute, _ = _execute(RuntimeRunResult(status=RuntimeRunStatus.ALREADY_RUNNING))

    assert main(["run-once"], execute=execute) == 0
    assert capsys.readouterr().out == "status=ALREADY_RUNNING\n"


def test_current_technical_failure_returns_nonzero(capsys) -> None:
    execute, _ = _execute(
        RuntimeRunResult(
            status=RuntimeRunStatus.FAILED,
            cycle_ref="cycle-001",
            stage=AcquisitionRuntimeStage.CONTACT_DISCOVERY,
            reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
        )
    )

    assert main(["run-once"], execute=execute) == 1
    assert "status=FAILED" in capsys.readouterr().out


@pytest.mark.parametrize("error", (RuntimeError("secret-marker"), ValueError("secret-marker")))
def test_configuration_failure_is_explicit_and_expurgated(error, capsys) -> None:
    def execute(_allow):
        raise error

    assert main(["run-once"], execute=execute) == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "status=CONFIGURATION_INVALID\n"
    assert "secret-marker" not in streams.err


def test_unexpected_runtime_failure_is_expurgated(capsys) -> None:
    def execute(_allow):
        raise OSError("provider-secret-marker")

    assert main(["run-once"], execute=execute) == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "status=RUNTIME_FAILED\n"
    assert "provider-secret-marker" not in streams.err


def test_invalid_arguments_never_reflect_their_value(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--provider-secret-marker"])

    assert raised.value.code == 2
    streams = capsys.readouterr()
    assert streams.err == "status=INVALID_ARGUMENTS\n"
    assert "provider-secret-marker" not in streams.err
