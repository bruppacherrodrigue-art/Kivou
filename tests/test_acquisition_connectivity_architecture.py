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
