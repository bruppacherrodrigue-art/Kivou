from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import stat
import subprocess
import sys

import pytest

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "ops/bin/kivou_secret_hygiene.py"
RUNBOOK = REPOSITORY / "docs/runbooks/09-staging-secret-rotation.md"
OPERATIONS = REPOSITORY / "ops/README.md"

SECRET_NAMES = (
    "KIVOU_DATABASE_URL",
    "SMTP_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)
FAKE_OLD_SECRETS = {
    "KIVOU_DATABASE_URL": (
        "postgresql+psycopg://kivou:FAKE-old-db-81@db.invalid:5432/kivou_staging"
    ),
    "SMTP_PASSWORD": "FAKE-old-smtp-81!",
    "STRIPE_SECRET_KEY": "sk_test_FAKE_old_81",
    "STRIPE_WEBHOOK_SECRET": "whsec_FAKE_old_81",
}
FAKE_NEW_SECRETS = {
    "KIVOU_DATABASE_URL": (
        "postgresql+psycopg://kivou:FAKE-new-db-81@db.invalid:5432/kivou_staging"
    ),
    "SMTP_PASSWORD": "FAKE-new-smtp-81!",
    "STRIPE_SECRET_KEY": "sk_test_FAKE_new_81",
    "STRIPE_WEBHOOK_SECRET": "whsec_FAKE_new_81",
}
ALL_FAKE_VALUES = (*FAKE_OLD_SECRETS.values(), *FAKE_NEW_SECRETS.values())


def _write_values(
    path: pathlib.Path,
    values: dict[str, str] = FAKE_NEW_SECRETS,
    *,
    content: str | None = None,
) -> pathlib.Path:
    if content is None:
        content = "".join(f"{name}={values[name]}\n" for name in SECRET_NAMES)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def _run_cli(
    *arguments: str | pathlib.Path,
    stdin: str = "",
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _assert_no_fake_value(result: subprocess.CompletedProcess[str]) -> None:
    combined = result.stdout + result.stderr
    for value in ALL_FAKE_VALUES:
        assert value not in combined


def test_audit_journal_emits_only_numeric_counters_and_fails_on_matches(
    tmp_path: pathlib.Path,
) -> None:
    values_file = _write_values(tmp_path / "old.values", FAKE_OLD_SECRETS)
    journal = "\n".join(
        (
            f"connection detail={FAKE_OLD_SECRETS['KIVOU_DATABASE_URL']}",
            "clean operational line",
            (
                f"smtp={FAKE_OLD_SECRETS['SMTP_PASSWORD']} "
                f"stripe={FAKE_OLD_SECRETS['STRIPE_SECRET_KEY']}"
            ),
            (
                f"hook={FAKE_OLD_SECRETS['STRIPE_WEBHOOK_SECRET']} "
                f"again={FAKE_OLD_SECRETS['STRIPE_WEBHOOK_SECRET']}"
            ),
        )
    )

    result = _run_cli("audit-journal", values_file, stdin=journal)

    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload == {
        "secret_values_checked": 4,
        "matching_lines": 3,
        "matching_occurrences": 5,
    }
    assert all(type(value) is int for value in payload.values())
    _assert_no_fake_value(result)


def test_audit_journal_accepts_multiple_value_files_and_succeeds_when_clean(
    tmp_path: pathlib.Path,
) -> None:
    old_file = _write_values(tmp_path / "old.values", FAKE_OLD_SECRETS)
    new_file = _write_values(tmp_path / "new.values", FAKE_NEW_SECRETS)

    result = _run_cli("audit-journal", old_file, new_file, stdin="counters only\n")

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "secret_values_checked": 8,
        "matching_lines": 0,
        "matching_occurrences": 0,
    }
    _assert_no_fake_value(result)


def test_replace_env_replaces_all_secrets_atomically_and_preserves_metadata(
    tmp_path: pathlib.Path,
) -> None:
    values_file = _write_values(tmp_path / "new.values", FAKE_NEW_SECRETS)
    target = tmp_path / "staging.env"
    target.write_text(
        "".join(
            (
                "# this comment and every unrelated value must survive\n",
                f"KIVOU_DATABASE_URL={FAKE_OLD_SECRETS['KIVOU_DATABASE_URL']}\n",
                "KIVOU_PUBLIC_ORIGIN=https://staging.invalid\n",
                f"SMTP_PASSWORD={FAKE_OLD_SECRETS['SMTP_PASSWORD']}\n",
                f"STRIPE_SECRET_KEY={FAKE_OLD_SECRETS['STRIPE_SECRET_KEY']}\n",
                "UNRELATED=value=with=equals\n",
                f"STRIPE_WEBHOOK_SECRET={FAKE_OLD_SECRETS['STRIPE_WEBHOOK_SECRET']}\n",
                "\n",
            )
        ),
        encoding="utf-8",
    )
    target.chmod(0o600)
    before = target.stat()

    result = _run_cli("replace-env", "--values-file", values_file, "--target", target)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert set(payload) == {"secret_values_replaced", "target_lines_written"}
    assert payload["secret_values_replaced"] == 4
    assert all(type(value) is int for value in payload.values())
    _assert_no_fake_value(result)

    after = target.stat()
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode) == 0o600
    assert (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
    assert not list(tmp_path.glob(f".{target.name}.*"))

    body = target.read_text(encoding="utf-8")
    for name, value in FAKE_NEW_SECRETS.items():
        assert body.count(f"{name}={value}") == 1
    for value in FAKE_OLD_SECRETS.values():
        assert value not in body
    assert "# this comment and every unrelated value must survive\n" in body
    assert "KIVOU_PUBLIC_ORIGIN=https://staging.invalid\n" in body
    assert "UNRELATED=value=with=equals\n" in body
    assert body.endswith("\n\n")


@pytest.mark.parametrize(
    "content",
    (
        pytest.param(
            "".join(
                f"{name}={FAKE_NEW_SECRETS[name]}\n" for name in SECRET_NAMES
            )
            + f"SMTP_PASSWORD={FAKE_OLD_SECRETS['SMTP_PASSWORD']}\n",
            id="duplicate-name",
        ),
        pytest.param(
            "".join(
                f"{name}={FAKE_NEW_SECRETS[name]}\n" for name in SECRET_NAMES
            )
            + "UNAPPROVED_SECRET=FAKE-unapproved-81\n",
            id="unapproved-name",
        ),
        pytest.param(
            "".join(
                f"{name}={' ' if name != 'SMTP_PASSWORD' else ''}\n"
                for name in SECRET_NAMES
            ),
            id="empty-value",
        ),
        pytest.param(
            "KIVOU_DATABASE_URL=FAKE-db-81\n"
            "SMTP_PASSWORD=FAKE-line-one-81\nFAKE-line-two-81\n"
            "STRIPE_SECRET_KEY=sk_test_FAKE_new_81\n"
            "STRIPE_WEBHOOK_SECRET=whsec_FAKE_new_81\n",
            id="newline-in-value",
        ),
    ),
)
def test_values_files_reject_duplicates_unknown_names_empty_or_multiline_values(
    tmp_path: pathlib.Path,
    content: str,
) -> None:
    values_file = _write_values(tmp_path / "invalid.values", content=content)

    result = _run_cli("audit-journal", values_file, stdin="clean\n")

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error=invalid_input\n"
    _assert_no_fake_value(result)


def test_replace_env_requires_all_four_values(tmp_path: pathlib.Path) -> None:
    values_file = _write_values(
        tmp_path / "incomplete.values",
        content="".join(
            f"{name}={FAKE_NEW_SECRETS[name]}\n" for name in SECRET_NAMES[:-1]
        ),
    )
    target = _write_values(tmp_path / "staging.env", FAKE_OLD_SECRETS)

    result = _run_cli("replace-env", "--values-file", values_file, "--target", target)

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error=invalid_input\n"
    assert target.read_text(encoding="utf-8").endswith(
        f"STRIPE_WEBHOOK_SECRET={FAKE_OLD_SECRETS['STRIPE_WEBHOOK_SECRET']}\n"
    )
    _assert_no_fake_value(result)


def test_values_file_must_be_a_regular_non_symlink_with_exact_mode_0600(
    tmp_path: pathlib.Path,
) -> None:
    protected = _write_values(tmp_path / "protected.values", FAKE_NEW_SECRETS)
    bad_mode = _write_values(tmp_path / "bad-mode.values", FAKE_NEW_SECRETS)
    bad_mode.chmod(0o640)
    symlink = tmp_path / "linked.values"
    symlink.symlink_to(protected)
    directory = tmp_path / "directory.values"
    directory.mkdir(mode=0o700)
    directory.chmod(0o600)

    try:
        for invalid in (bad_mode, symlink, directory):
            result = _run_cli("audit-journal", invalid, stdin="clean\n")
            assert result.returncode != 0
            assert result.stdout == ""
            assert result.stderr == "error=invalid_input\n"
            _assert_no_fake_value(result)
    finally:
        directory.chmod(0o700)


def test_values_file_rejects_a_fifo_without_waiting_for_a_writer(
    tmp_path: pathlib.Path,
) -> None:
    fifo = tmp_path / "fifo.values"
    os.mkfifo(fifo, mode=0o600)

    result = _run_cli("audit-journal", fifo, stdin="clean\n", timeout=1)

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error=invalid_input\n"


@pytest.mark.parametrize("target_kind", ("bad-mode", "symlink", "directory"))
def test_replace_env_refuses_unprotected_or_non_regular_targets(
    tmp_path: pathlib.Path,
    target_kind: str,
) -> None:
    values_file = _write_values(tmp_path / "new.values", FAKE_NEW_SECRETS)
    protected_target = _write_values(tmp_path / "protected.env", FAKE_OLD_SECRETS)
    target = tmp_path / "target.env"
    directory: pathlib.Path | None = None
    if target_kind == "bad-mode":
        target = protected_target
        target.chmod(0o644)
    elif target_kind == "symlink":
        target.symlink_to(protected_target)
    else:
        directory = target
        directory.mkdir(mode=0o700)
        directory.chmod(0o600)

    try:
        result = _run_cli("replace-env", "--values-file", values_file, "--target", target)
        assert result.returncode != 0
        assert result.stdout == ""
        assert result.stderr == "error=invalid_input\n"
        _assert_no_fake_value(result)
    finally:
        if directory is not None:
            directory.chmod(0o700)


def test_cli_is_stdlib_only_streaming_and_durable_atomic_replace() -> None:
    body = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(body)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots <= sys.stdlib_module_names | {"__future__"}
    assert "for line in sys.stdin:" in body
    assert "sys.stdin.read(" not in body
    assert "tempfile.mkstemp(" in body
    assert "os.replace(" in body
    assert body.count("os.fsync(") >= 2


def test_operator_docs_forbid_secret_bearing_process_arguments() -> None:
    paths = (OPERATIONS, *sorted((REPOSITORY / "docs/runbooks").glob("*.md")))
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    names = "|".join(map(re.escape, SECRET_NAMES))

    assert re.search(rf"\bsudo\s+env\b[^\n]*(?:{names})\s*=", text) is None
    assert (
        re.search(
            r"\b(?:grep|rg)\b[^\n]*\$(?:\{)?[A-Za-z0-9_]*"
            r"(?:SECRET|PASSWORD|DATABASE_URL)",
            text,
        )
        is None
    )
    assert re.search(r"postgres(?:ql)?(?:\+[a-z0-9_]+)?://[^\s/:]+:[^\s@]+@", text) is None
    assert "--database-url" not in text
    assert "$KIVOU_DATABASE_URL" not in text
    assert "${KIVOU_DATABASE_URL}" not in text


def test_runbook_versions_the_complete_staging_only_rotation_and_rollback() -> None:
    body = RUNBOOK.read_text(encoding="utf-8")

    for required in (
        "tmpfs",
        "/run/kivou-secret-rotation",
        "old.values",
        "new.values",
        "staging.env.backup",
        "root:kivou",
        "0600",
        "KIVOU_DATABASE_URL",
        "SMTP_PASSWORD",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "replace-env",
        "audit-journal",
        "PostgreSQL",
        "API",
        "SMTP",
        "Stripe TEST Checkout",
        "webhook Stripe TEST signé",
        "journalctl --rotate",
        "journalctl --vacuum-time",
        "secret_values_checked",
        "matching_lines",
        "matching_occurrences",
        "EnvironmentFile=/etc/kivou/staging.env",
        "Rollback",
        "PRODUCTION",
        "LIVE",
    ):
        assert required in body

    lower = body.lower()
    for forbidden_channel in (
        "argv",
        "sudo env",
        "grep",
        "terminal",
        "shell history",
        "git",
        "github",
        "journald",
    ):
        assert forbidden_channel in lower


def test_ops_readme_points_operators_to_the_counter_only_cli_and_runbook() -> None:
    body = OPERATIONS.read_text(encoding="utf-8")

    assert "09-staging-secret-rotation.md" in body
    assert "kivou_secret_hygiene.py" in body
    assert "replace-env" in body
    assert "audit-journal" in body
    assert "valeurs uniquement depuis des fichiers `0600`" in body
