import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_archived_signal_packages_are_not_in_active_source_or_test_discovery():
    for package in ("research", "verification", "phase_a_btp", "learning"):
        assert not (ROOT / "src" / "signals" / package).exists()
    for test_path in (
        ROOT / "tests" / "test_phase_a_btp.py",
        ROOT / "tests" / "test_learning_worker.py",
        ROOT / "tests" / "test_verifier_contract.py",
    ):
        assert not test_path.exists()


def test_removed_filters_route_is_not_declared():
    routes = (ROOT / "src" / "signals" / "api" / "routes_signals.py").read_text()
    assert '"/signals/filters"' not in routes


def test_active_billing_catalogue_has_no_retired_plan():
    catalogue = (ROOT / "src" / "signals" / "billing" / "catalogue.py").read_text().lower()
    retired = "sc" + "ale"
    assert not re.search(rf"\b{retired}\b", catalogue)


def test_declared_api_routes_have_a_frontend_or_runtime_caller():
    """A new private API route must have an explicit consumer or exemption."""
    route_paths = set()
    for route_file in (ROOT / "src" / "signals" / "api").glob("routes_*.py"):
        text = route_file.read_text()
        route_paths.update(re.findall(r'@router\.\w+\("(/[^"{]+)', text))

    frontend = "\n".join(
        path.read_text()
        for path in (ROOT / "frontend" / "src").rglob("*.ts")
        if path.name != "cleanupArchitecture.test.ts"
    )
    runtime = "\n".join(
        path.read_text()
        for path in (ROOT / "src" / "signals").rglob("*.py")
        if path.parent.name != "api"
    )
    allowlisted = ("/internal/", "/founder", "/operations", "/webhooks/", "/a/")
    missing = []
    for route_path in sorted(route_paths):
        if route_path.startswith(allowlisted):
            continue
        family = "/" + route_path.strip("/").split("/", 1)[0]
        if family not in frontend and family not in runtime:
            missing.append(route_path)
    assert not missing, f"API routes without a frontend/runtime caller: {missing}"


def test_active_source_never_imports_archive():
    for path in (ROOT / "src" / "signals").rglob("*.py"):
        assert "import archive" not in path.read_text()
