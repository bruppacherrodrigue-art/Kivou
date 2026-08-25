from __future__ import annotations

import pathlib

from signals.acquisition_runtime.contracts import AcquisitionRuntimeDeployment

ROOT = pathlib.Path(__file__).parents[1]
SERVICE = ROOT / "ops/systemd/kivou-acquisition.service"
TIMER = ROOT / "ops/systemd/kivou-acquisition.timer"
RUNBOOK = ROOT / "docs/runbooks/10-acquisition-runtime.md"
RUNTIME_ENV = ROOT / "ops/examples/acquisition-runtime.env.example"
RUNTIME_CONFIG = ROOT / "ops/examples/acquisition-runtime.json.example"
ENV_EXAMPLE = ROOT / ".env.example"


def test_acquisition_service_is_one_bounded_shadow_orchestrator() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "User=kivou" in service
    assert "Group=kivou" in service
    assert "WorkingDirectory=/srv/kivou/app" in service
    assert "EnvironmentFile=/etc/kivou/staging.env" in service
    assert "EnvironmentFile=/etc/kivou/acquisition-shadow.env" in service
    assert "EnvironmentFile=/etc/kivou/acquisition-runtime.env" in service
    assert service.count("ExecStart=") == 1
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
        "/run/kivou/acquisition.lock /srv/kivou/app/.venv/bin/python -m "
        "signals.acquisition_runtime run-once"
    ) in service
    assert "RuntimeDirectory=kivou" in service
    assert "TimeoutStartSec=25min" in service
    assert "TimeoutStopSec=90s" in service
    assert "UMask=0077" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=true" in service
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in service
    assert "ReadWritePaths=/run/kivou /var/lib/kivou/hermes-shadow" in service
    assert "--allow-qa-provider-mutations" not in service


def test_acquisition_timer_is_persistent_and_non_overlapping() -> None:
    timer = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=300" in timer
    assert "AccuracySec=60" in timer
    assert "Unit=kivou-acquisition.service" in timer
    assert "WantedBy=timers.target" in timer


def test_runtime_examples_are_redacted_closed_and_schema_valid() -> None:
    environment = RUNTIME_ENV.read_text(encoding="utf-8")
    document = RUNTIME_CONFIG.read_text(encoding="utf-8")
    repository_environment = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "KIVOU_ACQUISITION_RUNTIME_CONFIG=/etc/kivou/acquisition-runtime.json" in environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT=" in environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT_KEY=" in environment
    assert "KIVOU_ACQUISITION_RUNTIME_CONFIG=" in repository_environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT=" in repository_environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT_KEY=" in repository_environment
    assert "@" not in environment
    deployment = AcquisitionRuntimeDeployment.model_validate_json(document)
    assert deployment.qa_only is True
    assert deployment.mode.value == "SHADOW"
    assert deployment.limits.maximum_suppliers == 1
    assert deployment.limits.maximum_contacts == 1
    assert deployment.limits.maximum_provider_operations <= 3


def test_runbook_keeps_timer_non_mutating_and_manual_provider_gate_explicit() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "python -m signals.acquisition_runtime run-once" in runbook
    assert "--allow-qa-provider-mutations" in runbook
    assert "list-runtime-approvals" in runbook
    assert "approve-runtime-approval" in runbook
    assert "open-runtime-qa-policy-window" in runbook
    assert "close-runtime-qa-policy-window" in runbook
    assert "--duration-seconds 1800" in runbook
    assert "--expires-at" not in runbook
    assert "--database-url` et `--now" in runbook
    assert "python -m signals.operations health" in runbook
    assert "python -m signals.operations readiness" in runbook
    assert "activate-kill-switch" in runbook
    assert runbook.count("--property=RuntimeMaxSec=20min") >= 2
    assert runbook.count("/usr/bin/flock --verbose --nonblock") >= 2
    assert "journalctl -u kivou-acquisition.service" in runbook
    assert "alembic downgrade 0025_alert_recipient_context" in runbook
    assert runbook.count("--property=EnvironmentFile=/etc/kivou/acquisition-shadow.env") >= 2
    assert "systemctl disable --now kivou-acquisition.timer" in runbook
    assert "0026_acquisition_runtime" in runbook
    assert "client" not in runbook.casefold()
    assert "prospect" in runbook.casefold()
