from __future__ import annotations

import ast
from pathlib import Path

RUNBOOKS = (
    "01-hermes-runtime-restart.md",
    "02-kill-switch-and-read-only.md",
    "03-circuit-breaker-incident.md",
    "04-provider-reconciliation.md",
    "05-dead-letter-recovery.md",
    "06-vps-database-restart.md",
    "07-staging-to-production-promotion.md",
    "08-acquisition-shadow-provider-connectivity.md",
    "09-staging-secret-rotation.md",
)
SECRET_ROTATION_RUNBOOK = Path("docs/runbooks/09-staging-secret-rotation.md")
OPERATIONS_README = Path("ops/README.md")


def test_exact_safe_runbook_set_has_no_secret_or_destructive_examples() -> None:
    root = Path("docs/runbooks")
    assert tuple(sorted(path.name for path in root.glob("*.md"))) == RUNBOOKS
    text = "\n".join((root / name).read_text(encoding="utf-8") for name in RUNBOOKS)
    for forbidden in (
        "rm -rf",
        "DROP TABLE",
        "DELETE FROM",
        "UPDATE acquisition_",
        "sk_live_",
        "whsec_",
        "Bearer ",
        "password=",
        "api_key=",
        "systemctl enable",
        "docker exec",
    ):
        assert forbidden not in text
    assert "uv run python -m signals.operations" in text
    assert "uv run python -m signals.supervisor health" in text


def test_operations_package_has_no_network_or_import_time_execution() -> None:
    package = Path("src/signals/operations")
    forbidden_import_roots = {"httpx", "requests", "openai", "stripe"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert forbidden_import_roots.isdisjoint(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".", 1)[0] not in forbidden_import_roots
        if path.name not in {"cli.py", "__main__.py"}:
            assert "datetime.now(" not in path.read_text(encoding="utf-8")


def test_no_service_manager_or_autostart_manifest_is_added() -> None:
    assert not list(Path(".").glob("**/*spec031*.service"))
    assert not list(Path(".").glob("**/*spec031*.timer"))


def test_secret_journal_audit_covers_all_fields_and_propagates_pipeline_failures() -> None:
    for path in (SECRET_ROTATION_RUNBOOK, OPERATIONS_README):
        body = path.read_text(encoding="utf-8")
        assert "/bin/bash -o pipefail -c" in body
        assert "--output=export" in body
        assert "_CMDLINE" in body
        assert "journalctl --all --no-pager -o cat |" not in body


def test_secret_rotation_inventories_then_removes_only_targeted_legacy_backups() -> None:
    body = SECRET_ROTATION_RUNBOOK.read_text(encoding="utf-8")
    target = "legacy_backups=(/etc/kivou/staging.env.bak-*)"
    removal = 'rm -- "${legacy_backups[@]}"'

    assert body.count(target) >= 2
    assert "legacy-backups.paths" in body
    assert removal in body
    assert "legacy_backup_files=0" in body
    assert "Dernier point de décision Rollback avant suppression" in body
    assert body.index("Dernier point de décision Rollback avant suppression") < body.index(
        removal
    )
    assert "rm -- /etc/kivou" not in body
