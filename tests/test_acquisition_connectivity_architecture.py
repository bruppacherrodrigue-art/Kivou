from __future__ import annotations

import ast
import json
from pathlib import Path

from signals.acquisition_connectivity.config import HERMES_SHADOW_MODEL_CONFIG
from signals.acquisition_connectivity.contracts import ShadowConnectivityDocument

PACKAGE = Path("src/signals/acquisition_connectivity")
UNIT = Path("ops/systemd/kivou-acquisition-shadow-smoke.service")
OPS_ENV = Path("ops/examples/acquisition-shadow.env.example")
OPS_JSON = Path("ops/examples/acquisition-shadow.json.example")
HERMES_CONFIG = Path("ops/examples/hermes-shadow-config.yaml")
RUNBOOK = Path("docs/runbooks/08-acquisition-shadow-provider-connectivity.md")
HERMES_BRIDGE = Path("src/signals/supervisor/hermes_bridge.py")


def _assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value
    return values


def test_connectivity_package_adds_no_second_business_worker_policy_store_or_client() -> None:
    forbidden_modules = {
        "signals.campaigns.worker",
        "signals.campaigns.webhooks",
        "signals.campaigns.service",
        "signals.responses.worker",
        "signals.responses.webhooks",
        "signals.supplier_discovery.service",
        "signals.contact_discovery.service",
        "signals.company_research.service",
        "signals.operations.safety_controller",
    }
    forbidden_class_names = {
        "CampaignWorker",
        "CampaignService",
        "PolicyStore",
        "OperationsStore",
        "HermesSupervisorAdapter",
        "SupervisorPlan",
        "HttpInstantlyProvider",
    }
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        }.intersection(forbidden_class_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden_modules


def test_connectivity_package_contains_no_mutating_http_method_or_paid_apollo_path() -> None:
    forbidden_methods = {"POST", "PATCH", "DELETE"}
    forbidden_paths = {
        "/api/v1/mixed_companies/search",
        "/api/v1/mixed_people/api_search",
        "/api/v1/people/match",
        "/api/v1/organizations/",
    }
    constants: set[str] = set()
    source = ""
    for path in PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        source += text
        tree = ast.parse(text)
        constants.update(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    assert forbidden_methods.isdisjoint(constants)
    assert not any(path in source for path in forbidden_paths)
    assert "time.sleep" not in source
    assert "CampaignWorker" not in source


def test_optional_gap_profile_is_owned_only_by_manual_connectivity_composition() -> None:
    opt_out_callers = [
        path
        for path in Path("src/signals").rglob("*.py")
        if "require_sending_gap=False" in path.read_text(encoding="utf-8")
    ]

    assert opt_out_callers == [Path("src/signals/acquisition_connectivity/cli.py")]


def test_existing_hermes_bridge_has_one_exact_route_without_retry_or_fallback() -> None:
    source = HERMES_BRIDGE.read_text(encoding="utf-8")
    assert "from agent.oneshot import run_oneshot" not in source
    assert "max_retries=0" in source
    assert '"allow_fallbacks": False' in source
    assert 'OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"' in source


def test_main_env_example_has_only_blank_values_for_the_seven_new_settings() -> None:
    values = _assignments(Path(".env.example"))
    names = {
        "KIVOU_ACQUISITION_ENVIRONMENT",
        "KIVOU_ACQUISITION_SHADOW_CONFIG",
        "KIVOU_APOLLO_API_KEY",
        "KIVOU_INSTANTLY_API_KEY",
        "KIVOU_HERMES_PYTHON",
        "KIVOU_HERMES_HOME",
        "KIVOU_HERMES_CWD",
    }
    assert {name: values[name] for name in names} == {name: "" for name in names}


def test_redacted_deployment_examples_are_strict_and_secret_free() -> None:
    environment = _assignments(OPS_ENV)
    assert environment["KIVOU_ACQUISITION_ENVIRONMENT"] == "STAGING"
    assert environment["KIVOU_APOLLO_API_KEY"] == ""
    assert environment["KIVOU_INSTANTLY_API_KEY"] == ""
    assert set(environment) == {
        "KIVOU_ACQUISITION_ENVIRONMENT",
        "KIVOU_ACQUISITION_SHADOW_CONFIG",
        "KIVOU_APOLLO_API_KEY",
        "KIVOU_INSTANTLY_API_KEY",
        "KIVOU_HERMES_PYTHON",
        "KIVOU_HERMES_HOME",
        "KIVOU_HERMES_CWD",
    }
    deployment = ShadowConnectivityDocument.model_validate_json(
        OPS_JSON.read_text(encoding="utf-8")
    )
    assert len(deployment.mailboxes) == 3
    assert [
        mailbox.managed_airmail_sending_gap_minutes
        for mailbox in deployment.mailboxes
    ] == [10, 10, 10]
    assert json.loads(HERMES_CONFIG.read_text(encoding="utf-8")) == (
        HERMES_SHADOW_MODEL_CONFIG
    )
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (OPS_ENV, OPS_JSON, HERMES_CONFIG)
    )
    for forbidden in (
        "Bearer ",
        "x-api-key",
        "OPENROUTER_API_KEY=",
        "sk-or-",
        "api_key=",
        "password=",
    ):
        assert forbidden not in text


def test_systemd_unit_is_manual_static_oneshot_without_listener_or_restart() -> None:
    text = UNIT.read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    assert "User=kivou" in text
    assert "Group=kivou" in text
    assert "WorkingDirectory=/srv/kivou/app" in text
    assert "EnvironmentFile=/etc/kivou/staging.env" in text
    assert "EnvironmentFile=/etc/kivou/acquisition-shadow.env" in text
    assert (
        "ExecStart=/srv/kivou/app/.venv/bin/python "
        "-m signals.acquisition_connectivity check"
    ) in text
    for forbidden in (
        "[Install]",
        "WantedBy=",
        "Restart=",
        "ListenStream=",
        "ListenDatagram=",
        "uvicorn",
        "gateway",
    ):
        assert forbidden not in text
    assert not Path("ops/systemd/kivou-acquisition-shadow-smoke.timer").exists()


def test_runbook_contains_pin_provisioning_permissions_smoke_and_rollback() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "e624e9fde561e1add9388384012b295fde669ade",
        "v2026.8.18",
        "0.20.4",
        "https://docs.apollo.io/reference/authentication",
        "https://developer.instantly.ai/api-reference/workspace/get-workspace",
        "https://developer.instantly.ai/api-reference/account/get-account",
        "https://openrouter.ai/docs/guides/routing/provider-selection",
        "allow_fallbacks=false",
        "SDK retries to zero",
        "sudoedit /etc/kivou/acquisition-shadow.env",
        "namei -l",
        "systemctl start kivou-acquisition-shadow-smoke.service",
        "python -m signals.acquisition_connectivity check",
        "Rollback",
    ):
        assert required in text
    for forbidden in (
        "systemctl enable",
        "curl |",
        "rm -rf",
        "OPENROUTER_API_KEY=",
        "KIVOU_APOLLO_API_KEY=",
        "KIVOU_INSTANTLY_API_KEY=",
    ):
        assert forbidden not in text


def test_runbook_has_collision_safe_backup_and_executable_airmail_rollback() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    unique_backup = (
        'kivou_airmail_backup="$(sudo mktemp '
        '/etc/kivou/acquisition-shadow.json.rollback.XXXXXXXX)"'
    )
    root_only_copy = (
        "sudo install -m 0600 -o root -g root \\\n"
        '  /etc/kivou/acquisition-shadow.json "$kivou_airmail_backup"'
    )
    backup_stat = (
        "sudo stat -c '%a %U %G %n' \"$kivou_airmail_backup\""
    )
    backup_verify = (
        "test \"$(sudo stat -c '%a %U %G' \"$kivou_airmail_backup\")\" "
        "= '600 root root'"
    )
    failed_copy_cleanup = 'sudo rm -f -- "$kivou_airmail_backup"'
    backup_record = "Record the exact printed backup path"
    rollback_candidate = (
        "sudo install -m 0640 -o root -g kivou \\\n"
        '  "$kivou_airmail_backup" \\\n'
        "  /etc/kivou/acquisition-shadow.json.rollback.next"
    )
    rollback_validation_target = (
        'Path("/etc/kivou/acquisition-shadow.json.rollback.next").read_text('
        'encoding="utf-8")'
    )
    forward_validation_target = (
        'Path("/etc/kivou/acquisition-shadow.json.next").read_text('
        'encoding="utf-8")'
    )
    forward_candidate_verify = (
        "test \"$(sudo stat -c '%a %U %G' "
        "/etc/kivou/acquisition-shadow.json.next)\" = '640 root kivou'"
    )
    rollback_candidate_verify = (
        "test \"$(sudo stat -c '%a %U %G' "
        "/etc/kivou/acquisition-shadow.json.rollback.next)\" "
        "= '640 root kivou'"
    )
    forward_move = (
        "sudo mv -T /etc/kivou/acquisition-shadow.json.next \\\n"
        "  /etc/kivou/acquisition-shadow.json"
    )
    rollback_move = (
        "sudo mv -T /etc/kivou/acquisition-shadow.json.rollback.next \\\n"
        "  /etc/kivou/acquisition-shadow.json"
    )
    live_verify = (
        "test \"$(sudo stat -c '%a %U %G' "
        "/etc/kivou/acquisition-shadow.json)\" = '640 root kivou'"
    )
    older_code = (
        "Only after that live-file verification may code that predates the "
        "optional field be deployed."
    )

    required_in_order = (
        unique_backup,
        root_only_copy,
        backup_stat,
        backup_verify,
        failed_copy_cleanup,
        backup_record,
        rollback_candidate,
        rollback_move,
        older_code,
    )
    positions = [text.index(required) for required in required_in_order]
    assert positions == sorted(positions)
    assert 'test -n "$kivou_airmail_backup"' in text
    rollback_validation = text[
        text.index(rollback_candidate) : text.index(rollback_move)
    ]
    assert "sudo -u kivou" in rollback_validation
    assert (
        "ShadowConnectivityDocument.model_validate_json" in rollback_validation
    )
    assert rollback_validation_target in rollback_validation
    assert (
        "sudo install -m 0640 -o root -g kivou \\\n"
        "  /etc/kivou/acquisition-shadow.json \\\n"
        "  /etc/kivou/acquisition-shadow.json.rollback"
    ) not in text

    forward_marker = "# Fail closed: prepare and switch the forward candidate."
    rollback_marker = "# Fail closed: restore the recorded protected backup."
    backup_marker = "# Fail closed: create and verify the root-only backup."
    backup_start = text.index(backup_marker)
    backup_handler = text.index("} || {", backup_start)
    backup_end = text.index("}\n", backup_handler) + 2
    backup_block = text[backup_start:backup_handler]
    backup_failure = text[backup_handler:backup_end]
    assert "set -euo pipefail" in backup_block
    backup_positions = [
        backup_block.index(required)
        for required in (
            unique_backup,
            root_only_copy,
            backup_stat,
            backup_verify,
        )
    ]
    assert backup_positions == sorted(backup_positions)
    assert backup_block.count("&&") >= 3
    assert failed_copy_cleanup in backup_failure
    assert "Protected JSON backup creation or verification failed" in backup_failure
    assert "exit 1" in backup_failure
    assert backup_end < text.index(backup_record) < text.index(forward_marker)

    forward_start = text.index(forward_marker)
    forward_handler = text.index(") || {", forward_start)
    forward_end = text.index("}\n", forward_handler) + 2
    forward_block = text[forward_start:forward_handler]
    forward_failure = text[forward_handler:forward_end]
    assert "set -euo pipefail" in forward_block
    assert "ShadowConnectivityDocument.model_validate_json" in forward_block
    forward_positions = [
        forward_block.index(required)
        for required in (
            forward_validation_target,
            forward_candidate_verify,
            forward_move,
            live_verify,
        )
    ]
    assert forward_positions == sorted(forward_positions)
    assert forward_block.count("&&") >= 8
    assert "Forward AirMail JSON switch failed" in forward_failure
    assert "exit 1" in forward_failure

    rollback_start = text.index(rollback_marker, forward_end)
    rollback_handler = text.index(") || {", rollback_start)
    rollback_end = text.index("}\n", rollback_handler) + 2
    rollback_block = text[rollback_start:rollback_handler]
    rollback_failure = text[rollback_handler:rollback_end]
    assert "set -euo pipefail" in rollback_block
    assert "ShadowConnectivityDocument.model_validate_json" in rollback_block
    rollback_positions = [
        rollback_block.index(required)
        for required in (
            backup_verify,
            rollback_validation_target,
            rollback_candidate_verify,
            rollback_move,
            live_verify,
        )
    ]
    assert rollback_positions == sorted(rollback_positions)
    assert rollback_block.count("&&") >= 7
    assert "AirMail JSON rollback failed" in rollback_failure
    assert "exit 1" in rollback_failure
    assert text.index(older_code) > rollback_end


def test_runbook_requires_strict_runtime_dependencies_ready_before_qa() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    marker = "# Strict read-only runtime dependency READY gate."
    gate_start = text.index(marker)
    gate_handler = text.index(") || {", gate_start)
    gate_end = text.index("}\n", gate_handler) + 2
    gate_block = text[gate_start:gate_handler]
    gate_failure = text[gate_handler:gate_end]

    required = (
        "set -euo pipefail",
        "--property=EnvironmentFile=/etc/kivou/staging.env",
        "--property=EnvironmentFile=/etc/kivou/acquisition-shadow.env",
        "--property=EnvironmentFile=/etc/kivou/acquisition-runtime.env",
        (
            "/srv/kivou/app/.venv/bin/python "
            "-m signals.acquisition_runtime check-dependencies"
        ),
    )
    positions = [gate_block.index(value) for value in required]
    assert positions == sorted(positions)
    assert "Strict runtime dependency readiness failed" in gate_failure
    assert "exit 1" in gate_failure
    assert "run-once" not in gate_block
    assert "--allow-qa-provider-mutations" not in gate_block
    assert "python -m signals.acquisition_connectivity check" not in gate_block
    assert "ProductionRuntimeDependencyProbe" not in gate_block
    assert "_default_hermes_runtime" not in gate_block
    assert "get_secret_value" not in gate_block
    assert "/srv/kivou/app/.venv/bin/python -c" not in gate_block
    assert (
        "A connectivity-smoke PASS does not satisfy this strict gate" in text
    )
    assert gate_end < text.index("## 7. Manual smoke")
