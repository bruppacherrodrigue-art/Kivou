from __future__ import annotations

import ast
import inspect
from pathlib import Path

from signals.supervisor.hermes import HermesSupervisorAdapter

PACKAGE = Path("src/signals/chief_of_staff")
PROFILE = Path("src/signals/supervisor/profiles/kivou-chief-of-staff/SKILL.md")
BRIDGE = Path("src/signals/supervisor/hermes_bridge.py")
FOUNDER_APP = Path("src/signals/founder_api/app.py")
CLIENT_APP = Path("src/signals/api/app.py")
SERVICE = Path("ops/systemd/kivou-chief-of-staff.service")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_hermes_boundary_has_no_database_dependency_or_executable_tool() -> None:
    imports = _imports(PACKAGE / "hermes.py") | _imports(BRIDGE)
    assert not any(name.startswith("sqlalchemy") for name in imports)
    signature = str(inspect.signature(HermesSupervisorAdapter.plan))
    assert "engine" not in signature.lower()
    assert "session" not in signature.lower()
    bridge = BRIDGE.read_text(encoding="utf-8")
    assert '"executable_tools": []' in bridge
    assert "tools != []" in bridge


def test_profile_is_secret_free_non_executing_and_injection_aware() -> None:
    body = PROFILE.read_text(encoding="utf-8")
    for required in (
        "UNTRUSTED_DATA",
        "fact_ref",
        "never execute",
        "insufficient evidence",
        "at most three",
    ):
        assert required in body
    for forbidden in ("sk-", "password=", "api_key=", "BEGIN PRIVATE KEY"):
        assert forbidden not in body


def test_chief_domain_has_no_provider_client_or_business_mutation_dependency() -> None:
    imported = set().union(*(_imports(path) for path in PACKAGE.glob("*.py")))
    forbidden = (
        "signals.acquisition.apollo",
        "signals.acquisition.instantly",
        "signals.billing.stripe",
        "stripe",
    )
    assert not any(name.startswith(forbidden) for name in imported)
    source = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py"))
    for forbidden_action in (
        "approve_target",
        "reject_target",
        "start_campaign",
        "change_price",
        "modify_policy",
    ):
        assert forbidden_action not in source


def test_chief_routes_exist_only_on_authenticated_founder_application() -> None:
    path = "/api/founder/chief-of-staff/"
    assert path in FOUNDER_APP.read_text(encoding="utf-8")
    assert path not in CLIENT_APP.read_text(encoding="utf-8")
    founder = FOUNDER_APP.read_text(encoding="utf-8")
    assert "FounderIdentityDependency" in founder
    assert "@app.post(\"/api/founder/chief-of-staff" not in founder


def test_facts_and_reports_survive_a_replaceable_hermes_adapter() -> None:
    for path in (PACKAGE / "contracts.py", PACKAGE / "store.py"):
        assert "signals.supervisor.hermes" not in path.read_text(encoding="utf-8")
    assert "signals.policy" not in (PACKAGE / "store.py").read_text(encoding="utf-8")


def test_acquisition_supervisor_public_plan_contract_is_unchanged() -> None:
    parameters = tuple(inspect.signature(HermesSupervisorAdapter.plan).parameters)
    assert parameters == ("self", "context", "required_action_count")
    assert inspect.signature(HermesSupervisorAdapter.plan).parameters[
        "required_action_count"
    ].default is None


def test_static_service_is_hardened_oneshot_and_no_timer_is_shipped() -> None:
    body = SERVICE.read_text(encoding="utf-8")
    for required in (
        "Type=oneshot",
        "User=kivou",
        "EnvironmentFile=/etc/kivou/chief-of-staff.env",
        "--persist",
        "TimeoutStartSec=",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "KIVOU_CHIEF_OF_STAFF_LOCK_FILE",
    ):
        assert required in body
    for forbidden in ("[Install]", "WantedBy=", "Restart=", "alembic", "uv sync"):
        assert forbidden not in body
    assert not Path("ops/systemd/kivou-chief-of-staff.timer").exists()
