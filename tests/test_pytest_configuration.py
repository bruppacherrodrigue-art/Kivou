from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BENCHMARK_MODULES = (
    "tests/test_winner100_benchmark.py",
    "tests/test_contract100_benchmark.py",
    "tests/test_document100_benchmark.py",
)
ARCHIVE_TREES = (
    "archive/research",
    "archive/verification",
    "archive/phase_a_btp",
    "archive/learning",
)
MIXED_MODULE_MIGRATION_TESTS = (
    "tests/test_accounts_signal_binding.py::test_a_pre_account_signal_survives_the_migration",
    "tests/test_accounts_signal_binding.py::test_a_pre_account_signal_is_unbound",
    "tests/test_accounts_signal_binding.py::test_a_pre_account_signal_resolves_to_no_account",
    "tests/test_accounts_signal_binding.py::test_no_account_can_claim_a_pre_account_signal",
    "tests/test_accounts_signal_binding.py::test_creating_an_icp_whose_label_matches_the_research_profile_binds_nothing",
    "tests/test_billing_entitlements.py::test_an_empty_database_reaches_the_billing_schema_through_every_migration",
    "tests/test_billing_entitlements.py::test_a_populated_spec012_database_upgrades_without_losing_anything",
    "tests/test_policy_persistence.py::test_migration_is_linear_and_adds_exactly_two_tables",
    "tests/test_policy_persistence.py::test_postgresql_offline_migration_contains_only_policy_tables",
    "tests/test_sirene_apollo_binding.py::test_migration_marks_apollo_first_suppliers_legacy_without_binding",
    "tests/test_target_icp_revision.py::test_populated_0016_upgrade_preserves_profiles_signals_grants_and_history",
)


def _collect(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_local_pytest_defaults_to_parallel_fast_suite() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = configuration["dependency-groups"]["dev"]
    pytest_options = configuration["tool"]["pytest"]["ini_options"]

    assert any(dependency.startswith("pytest-xdist") for dependency in dependencies)
    assert shlex.split(pytest_options["addopts"]) == ["-n", "auto", "-m", "not slow"]
    assert any(marker.startswith("slow:") for marker in pytest_options["markers"])
    assert "archive" in pytest_options["norecursedirs"]


def test_local_pytest_uses_available_memory_backed_temp_root(tmp_path: pathlib.Path) -> None:
    from conftest import configure_local_pytest_temproot

    environment: dict[str, str] = {}

    assert configure_local_pytest_temproot(environment, candidate=tmp_path)
    assert environment["PYTEST_DEBUG_TEMPROOT"] == str(tmp_path)


def test_ci_and_explicit_temp_roots_are_not_overridden(tmp_path: pathlib.Path) -> None:
    from conftest import configure_local_pytest_temproot

    ci_environment = {"CI": "true"}
    explicit_environment = {"PYTEST_DEBUG_TEMPROOT": "/operator-choice"}

    assert not configure_local_pytest_temproot(ci_environment, candidate=tmp_path)
    assert not configure_local_pytest_temproot(explicit_environment, candidate=tmp_path)
    assert "PYTEST_DEBUG_TEMPROOT" not in ci_environment
    assert explicit_environment["PYTEST_DEBUG_TEMPROOT"] == "/operator-choice"


def test_real_default_collection_excludes_slow_and_all_archive_trees() -> None:
    result = _collect()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "tests/test_benchmark_smoke.py::test_winner" in result.stdout
    assert not any(module in result.stdout for module in BENCHMARK_MODULES)
    assert not any(tree in result.stdout for tree in ARCHIVE_TREES)


def test_real_ci_style_collection_includes_every_full_benchmark() -> None:
    result = _collect("-o", "addopts=", *BENCHMARK_MODULES)

    assert result.returncode == 0, result.stdout + result.stderr
    assert all(module in result.stdout for module in BENCHMARK_MODULES)


def test_migration_transitions_in_mixed_modules_are_local_slow_but_collected_in_ci() -> None:
    local = _collect(*MIXED_MODULE_MIGRATION_TESTS)
    ci = _collect("-o", "addopts=", *MIXED_MODULE_MIGRATION_TESTS)

    assert local.returncode == 5, local.stdout + local.stderr
    assert not any(node in local.stdout for node in MIXED_MODULE_MIGRATION_TESTS)
    assert ci.returncode == 0, ci.stdout + ci.stderr
    assert all(node in ci.stdout for node in MIXED_MODULE_MIGRATION_TESTS)


def test_exhaustive_migration_routing_is_an_explicit_complete_allowlist() -> None:
    from conftest import EXHAUSTIVE_MIGRATION_SUITES, is_slow_suite_path

    migration_modules = {
        path.name for path in (ROOT / "tests").glob("test_*migration*.py")
    }

    assert set(EXHAUSTIVE_MIGRATION_SUITES) == migration_modules
    assert all(is_slow_suite_path(pathlib.Path("tests") / name) for name in migration_modules)
    assert not is_slow_suite_path(pathlib.Path("tests/test_migration_copy_helper.py"))
    assert not is_slow_suite_path(pathlib.Path("tests/test_benchmark_smoke.py"))
    assert not is_slow_suite_path(pathlib.Path("tests/test_dashboard.py"))


def test_shard_helper_selects_each_node_once_and_clears_addopts(tmp_path: pathlib.Path) -> None:
    nodes = [f"tests/test_example.py::test_{index}" for index in range(11)]
    collection = tmp_path / "collection.txt"
    collection.write_text("\n".join(nodes) + "\n", encoding="utf-8")
    runner = tmp_path / "runner"
    runner.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[[ \"$1\" == -o && \"$2\" == addopts= && \"$3\" == -q ]]\n"
        "printf '%s\\n' \"${@:4}\" >> \"$KIVOU_CAPTURE\"\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    capture = tmp_path / "selected.txt"
    environment = {
        **os.environ,
        "KIVOU_PYTEST_COLLECTION_FILE": str(collection),
        "KIVOU_PYTEST_RUNNER": str(runner),
        "KIVOU_CAPTURE": str(capture),
    }

    for shard in range(4):
        result = subprocess.run(
            [str(ROOT / "ops/bin/kivou-pytest-shard.sh"), str(shard), "4"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    selected = capture.read_text(encoding="utf-8").splitlines()
    expected = [node for shard in range(4) for index, node in enumerate(nodes) if index % 4 == shard]
    assert selected == expected
    assert sorted(selected) == sorted(nodes)


def test_shard_collection_command_clears_addopts(tmp_path: pathlib.Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[[ \"$1\" == run && \"$2\" == pytest && \"$3\" == -o ]]\n"
        "[[ \"$4\" == addopts= && \"$5\" == --collect-only && \"$6\" == -q ]]\n"
        "printf '%s\\n' 'tests/test_example.py::test_one'\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    runner = tmp_path / "runner"
    runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "KIVOU_PYTEST_RUNNER": str(runner),
    }

    result = subprocess.run(
        [str(ROOT / "ops/bin/kivou-pytest-shard.sh"), "0", "1"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
