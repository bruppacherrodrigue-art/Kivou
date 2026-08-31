from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Callable

import pytest

from signals.acquisition_runtime import cli
from signals.acquisition_runtime.cli import main
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeDependencyState,
    RuntimeRunResult,
    RuntimeRunStatus,
    RuntimeStageDependency,
)


def _execute(result: RuntimeRunResult) -> tuple[Callable[[bool], RuntimeRunResult], list[bool]]:
    calls: list[bool] = []

    def run(allow_qa_provider_mutations: bool) -> RuntimeRunResult:
        calls.append(allow_qa_provider_mutations)
        return result

    return run, calls


def _ready_dependencies() -> tuple[RuntimeStageDependency, ...]:
    return tuple(
        RuntimeStageDependency(
            stage=stage,
            status=RuntimeDependencyState.READY,
        )
        for stage in AcquisitionRuntimeStage
    )


def test_check_dependencies_reports_exact_ready_and_does_not_run_cycle(capsys) -> None:
    execute, run_calls = _execute(
        RuntimeRunResult(status=RuntimeRunStatus.ALREADY_RUNNING)
    )
    check_calls: list[bool] = []

    def check_dependencies() -> tuple[RuntimeStageDependency, ...]:
        check_calls.append(True)
        return _ready_dependencies()

    exit_code = main(
        ["check-dependencies"],
        execute=execute,
        check_dependencies=check_dependencies,
    )

    assert exit_code == 0
    assert run_calls == []
    assert check_calls == [True]
    streams = capsys.readouterr()
    assert streams.out == "status=READY dependency_count=11\n"
    assert streams.err == ""


@pytest.mark.parametrize(
    "dependencies",
    (
        _ready_dependencies()[:-1],
        tuple(
            RuntimeStageDependency(
                stage=stage,
                status=(
                    RuntimeDependencyState.NOT_READY
                    if stage is AcquisitionRuntimeStage.CAMPAIGN
                    else RuntimeDependencyState.READY
                ),
                reason_codes=(
                    ("MAILBOX_DEPENDENCY_NOT_READY",)
                    if stage is AcquisitionRuntimeStage.CAMPAIGN
                    else ()
                ),
            )
            for stage in AcquisitionRuntimeStage
        ),
    ),
)
def test_check_dependencies_rejects_incomplete_or_not_ready_coverage(
    dependencies: tuple[RuntimeStageDependency, ...],
    capsys,
) -> None:
    exit_code = main(
        ["check-dependencies"],
        check_dependencies=lambda: dependencies,
    )

    assert exit_code == 1
    streams = capsys.readouterr()
    assert streams.out == "status=NOT_READY\n"
    assert streams.err == ""


@pytest.mark.parametrize(
    "error",
    (
        ImportError("private-import-marker"),
        OSError("private-provider-marker"),
        RuntimeError("private-config-marker"),
    ),
)
def test_check_dependencies_sanitizes_every_failure(error, capsys) -> None:
    def check_dependencies() -> tuple[RuntimeStageDependency, ...]:
        raise error

    assert (
        main(
            ["check-dependencies"],
            check_dependencies=check_dependencies,
        )
        == 1
    )
    streams = capsys.readouterr()
    assert streams.out == "status=NOT_READY\n"
    assert streams.err == ""
    assert "private-" not in streams.out
    assert "private-" not in streams.err


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


def test_sigterm_interrupts_the_cycle_and_restores_the_process_handler() -> None:
    script = textwrap.dedent(
        """
        import os
        import signal

        from signals.acquisition_runtime.cli import main
        from signals.acquisition_runtime.contracts import RuntimeRunResult, RuntimeRunStatus

        previous_handler = signal.getsignal(signal.SIGTERM)

        def execute(_allow: bool) -> RuntimeRunResult:
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            except InterruptedError:
                return RuntimeRunResult(
                    status=RuntimeRunStatus.CANCELLED,
                    cycle_ref="cycle-001",
                    reason_code="PROCESS_TERMINATED",
                )
            raise AssertionError("SIGTERM must interrupt the active runtime call")

        exit_code = main(["run-once"], execute=execute)
        assert signal.getsignal(signal.SIGTERM) is previous_handler
        raise SystemExit(exit_code)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stdout == (
        "status=CANCELLED cycle_ref=cycle-001 reason=PROCESS_TERMINATED\n"
    )
    assert completed.stderr == ""


def test_production_refuses_the_qa_mutation_gate(monkeypatch, capsys) -> None:
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "PRODUCTION")
    called = False

    def execute(_allow: bool):
        nonlocal called
        called = True
        raise AssertionError("the runtime must not be reached")

    from signals.acquisition_runtime.cli import main

    code = main(["run-once", "--allow-qa-provider-mutations"], execute=execute)
    assert code == 2
    assert called is False
    assert "status=INVALID_ARGUMENTS" in capsys.readouterr().err


def test_staging_still_accepts_the_qa_mutation_gate(monkeypatch) -> None:
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    seen: list[bool] = []

    from signals.acquisition_runtime.cli import main
    from signals.acquisition_runtime.contracts import RuntimeRunResult, RuntimeRunStatus

    def execute(allow: bool) -> RuntimeRunResult:
        seen.append(allow)
        return RuntimeRunResult(status=RuntimeRunStatus.COMPLETED)

    assert main(["run-once", "--allow-qa-provider-mutations"], execute=execute) == 0
    assert seen == [True]
