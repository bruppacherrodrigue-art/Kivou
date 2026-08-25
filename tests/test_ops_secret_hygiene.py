from __future__ import annotations

import ast
import errno
import fcntl
import importlib.util
import json
import os
import pathlib
import re
import select
import stat
import subprocess
import sys
import termios
import time
import types
import urllib.parse

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
PROVIDER_SECRET_NAMES = SECRET_NAMES[1:]
FAKE_OLD_ROLE_PASSWORD = "FAKE-old-role-password-81"
FAKE_NEW_ROLE_PASSWORD = "FAKE new/role:password@81"
FAKE_OLD_ROLE_URL = (
    "postgresql+psycopg://kivou_app:"
    f"{FAKE_OLD_ROLE_PASSWORD}@db.invalid:5432/kivou_staging?sslmode=require"
)


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


def _load_hygiene_module() -> types.ModuleType:
    specification = importlib.util.spec_from_file_location(
        "kivou_secret_hygiene_under_test",
        SCRIPT,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _assignments(path: pathlib.Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _call_main(module: types.ModuleType) -> int:
    try:
        return module.main()
    except SystemExit as error:
        return int(error.code)


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


def _run_cli_with_tty(
    *arguments: str | pathlib.Path,
    secret: str,
    timeout: float = 5,
) -> tuple[subprocess.CompletedProcess[str], str]:
    master_descriptor, slave_descriptor = os.openpty()

    def establish_controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(slave_descriptor, termios.TIOCSCTTY, 0)

    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(slave_descriptor,),
        preexec_fn=establish_controlling_tty,  # noqa: PLW1509 - isolated test process
    )
    os.close(slave_descriptor)
    tty_chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    prompt_seen = False
    try:
        while process.poll() is None and time.monotonic() < deadline:
            readable, _, _ = select.select(
                [master_descriptor],
                [],
                [],
                min(0.1, max(0.0, deadline - time.monotonic())),
            )
            if not readable:
                continue
            try:
                chunk = os.read(master_descriptor, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            tty_chunks.append(chunk)
            if b":" in b"".join(tty_chunks):
                prompt_seen = True
                break

        if prompt_seen:
            os.write(master_descriptor, secret.encode() + b"\n")
        stdout, stderr = process.communicate(timeout=max(0.1, deadline - time.monotonic()))

        while True:
            readable, _, _ = select.select([master_descriptor], [], [], 0)
            if not readable:
                break
            try:
                chunk = os.read(master_descriptor, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            tty_chunks.append(chunk)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master_descriptor)

    result = subprocess.CompletedProcess(
        process.args,
        process.returncode,
        stdout.decode(encoding="utf-8", errors="replace"),
        stderr.decode(encoding="utf-8", errors="replace"),
    )
    return result, b"".join(tty_chunks).decode(encoding="utf-8", errors="replace")


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


def test_audit_journal_requires_every_values_file_to_contain_all_four_names(
    tmp_path: pathlib.Path,
) -> None:
    complete_file = _write_values(tmp_path / "old.values", FAKE_OLD_SECRETS)
    incomplete_file = _write_values(
        tmp_path / "new.values",
        content="".join(
            f"{name}={FAKE_NEW_SECRETS[name]}\n" for name in SECRET_NAMES[:-1]
        ),
    )

    result = _run_cli(
        "audit-journal",
        complete_file,
        incomplete_file,
        stdin="clean\n",
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error=invalid_input\n"
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


def test_set_secret_reads_three_provider_values_from_tty_without_echo(
    tmp_path: pathlib.Path,
) -> None:
    values_file = _write_values(tmp_path / "new.values", content="")
    expected: dict[str, str] = {}

    for expected_count, name in enumerate(PROVIDER_SECRET_NAMES, start=1):
        value = FAKE_NEW_SECRETS[name]
        before = values_file.stat()

        result, tty_output = _run_cli_with_tty(
            "set-secret",
            name,
            "--values-file",
            values_file,
            secret=value,
        )

        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert json.loads(result.stdout) == {
            "secret_values_present": expected_count,
            "secret_values_stored": 1,
        }
        assert value not in tty_output
        _assert_no_fake_value(result)

        after = values_file.stat()
        assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
        assert stat.S_IMODE(after.st_mode) == 0o600
        assert (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        expected[name] = value
        assert values_file.read_text(encoding="utf-8") == "".join(
            f"{secret_name}={expected[secret_name]}\n"
            for secret_name in SECRET_NAMES
            if secret_name in expected
        )


def test_set_secret_rejects_a_live_stripe_key_without_echoing_it(
    tmp_path: pathlib.Path,
) -> None:
    values_file = _write_values(tmp_path / "new.values", content="")
    live_value = "sk_" + "live_FAKE_review_81"

    result, tty_output = _run_cli_with_tty(
        "set-secret",
        "STRIPE_SECRET_KEY",
        "--values-file",
        values_file,
        secret=live_value,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error=invalid_input\n"
    assert live_value not in tty_output + result.stdout + result.stderr
    assert values_file.read_text(encoding="utf-8") == ""


class _RecordingPasswordProtocol:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.password_changes: list[tuple[bytes, bytes]] = []

    def change_password(self, role: bytes, password: bytes) -> None:
        self.password_changes.append((role, password))
        if self.failure is not None:
            raise self.failure


class _RecordingPasswordConnection:
    def __init__(self, protocol: _RecordingPasswordProtocol) -> None:
        self.pgconn = protocol
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_rotate_postgres_writes_candidate_before_protocol_password_change(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_hygiene_module()
    old_env = tmp_path / "staging.env"
    old_env.write_text(
        f"KIVOU_DATABASE_URL={FAKE_OLD_ROLE_URL}\nOTHER_SETTING=preserved\n",
        encoding="utf-8",
    )
    old_env.chmod(0o600)
    provider_content = "".join(
        f"{name}={FAKE_NEW_SECRETS[name]}\n" for name in PROVIDER_SECRET_NAMES
    )
    values_file = _write_values(tmp_path / "new.values", content=provider_content)
    before = values_file.stat()
    protocol = _RecordingPasswordProtocol()
    connection = _RecordingPasswordConnection(protocol)
    connector_calls: list[tuple[str, bool]] = []

    def connector(url: str, *, autocommit: bool) -> _RecordingPasswordConnection:
        connector_calls.append((url, autocommit))
        candidate = _assignments(values_file)["KIVOU_DATABASE_URL"]
        candidate_password = urllib.parse.urlsplit(candidate).password or ""
        assert urllib.parse.unquote(candidate_password) == FAKE_NEW_ROLE_PASSWORD
        return connection

    monkeypatch.setattr(module, "_connect_postgres", connector)
    monkeypatch.setattr(
        module,
        "_generate_postgres_password",
        lambda: FAKE_NEW_ROLE_PASSWORD,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "rotate-postgres-password",
            "--old-env-file",
            str(old_env),
            "--values-file",
            str(values_file),
        ],
    )

    return_code = _call_main(module)

    captured = capsys.readouterr()
    assert return_code == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "database_password_rotated": 1,
        "secret_values_present": 4,
    }
    for secret in (*ALL_FAKE_VALUES, FAKE_OLD_ROLE_PASSWORD, FAKE_NEW_ROLE_PASSWORD):
        assert secret not in captured.out + captured.err

    assert len(connector_calls) == 1
    connection_url, autocommit = connector_calls[0]
    parsed_connection_url = urllib.parse.urlsplit(connection_url)
    assert parsed_connection_url.scheme == "postgresql"
    assert parsed_connection_url.username == "kivou_app"
    assert parsed_connection_url.password == FAKE_OLD_ROLE_PASSWORD
    assert autocommit is True
    assert protocol.password_changes == [
        (b"kivou_app", FAKE_NEW_ROLE_PASSWORD.encode())
    ]
    assert connection.closed

    after = values_file.stat()
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert stat.S_IMODE(after.st_mode) == 0o600
    assert (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
    stored = _assignments(values_file)
    assert tuple(stored) == SECRET_NAMES
    stored_password = urllib.parse.urlsplit(stored["KIVOU_DATABASE_URL"]).password or ""
    assert urllib.parse.unquote(stored_password) == FAKE_NEW_ROLE_PASSWORD
    for name in PROVIDER_SECRET_NAMES:
        assert stored[name] == FAKE_NEW_SECRETS[name]
    assert old_env.read_text(encoding="utf-8").endswith("OTHER_SETTING=preserved\n")


def test_rotate_postgres_restores_values_file_when_old_authentication_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_hygiene_module()
    old_env = tmp_path / "staging.env"
    old_env.write_text(f"KIVOU_DATABASE_URL={FAKE_OLD_ROLE_URL}\n", encoding="utf-8")
    old_env.chmod(0o600)
    original_content = "".join(
        f"{name}={FAKE_NEW_SECRETS[name]}\n" for name in PROVIDER_SECRET_NAMES
    )
    values_file = _write_values(tmp_path / "new.values", content=original_content)

    def connector(url: str, *, autocommit: bool) -> _RecordingPasswordConnection:
        del url, autocommit
        candidate = _assignments(values_file)["KIVOU_DATABASE_URL"]
        candidate_password = urllib.parse.urlsplit(candidate).password or ""
        assert urllib.parse.unquote(candidate_password) == FAKE_NEW_ROLE_PASSWORD
        raise ConnectionError(
            f"rejected old={FAKE_OLD_ROLE_PASSWORD} new={FAKE_NEW_ROLE_PASSWORD}"
        )

    monkeypatch.setattr(module, "_connect_postgres", connector)
    monkeypatch.setattr(
        module,
        "_generate_postgres_password",
        lambda: FAKE_NEW_ROLE_PASSWORD,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "rotate-postgres-password",
            "--old-env-file",
            str(old_env),
            "--values-file",
            str(values_file),
        ],
    )

    return_code = _call_main(module)

    captured = capsys.readouterr()
    assert return_code != 0
    assert captured.out == ""
    assert captured.err == "error=database_update_failed\n"
    for secret in (*ALL_FAKE_VALUES, FAKE_OLD_ROLE_PASSWORD, FAKE_NEW_ROLE_PASSWORD):
        assert secret not in captured.out + captured.err
    assert values_file.read_text(encoding="utf-8") == original_content
    assert not list(tmp_path.glob(f".{values_file.name}.*"))


def test_rotate_postgres_keeps_candidate_when_database_state_is_unknown(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_hygiene_module()
    old_env = tmp_path / "staging.env"
    old_env.write_text(f"KIVOU_DATABASE_URL={FAKE_OLD_ROLE_URL}\n", encoding="utf-8")
    old_env.chmod(0o600)
    original_content = "".join(
        f"{name}={FAKE_NEW_SECRETS[name]}\n" for name in PROVIDER_SECRET_NAMES
    )
    values_file = _write_values(tmp_path / "new.values", content=original_content)
    protocol = _RecordingPasswordProtocol(
        failure=ConnectionError(
            f"connection lost old={FAKE_OLD_ROLE_PASSWORD} new={FAKE_NEW_ROLE_PASSWORD}"
        )
    )
    connection = _RecordingPasswordConnection(protocol)

    def connector(url: str, *, autocommit: bool) -> _RecordingPasswordConnection:
        del url, autocommit
        return connection

    monkeypatch.setattr(module, "_connect_postgres", connector)
    monkeypatch.setattr(
        module,
        "_generate_postgres_password",
        lambda: FAKE_NEW_ROLE_PASSWORD,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "rotate-postgres-password",
            "--old-env-file",
            str(old_env),
            "--values-file",
            str(values_file),
        ],
    )

    return_code = _call_main(module)

    captured = capsys.readouterr()
    assert return_code != 0
    assert captured.out == ""
    assert captured.err == "error=database_state_unknown\n"
    for secret in (*ALL_FAKE_VALUES, FAKE_OLD_ROLE_PASSWORD, FAKE_NEW_ROLE_PASSWORD):
        assert secret not in captured.out + captured.err
    stored = _assignments(values_file)
    stored_password = urllib.parse.urlsplit(stored["KIVOU_DATABASE_URL"]).password or ""
    assert urllib.parse.unquote(stored_password) == FAKE_NEW_ROLE_PASSWORD
    for name in PROVIDER_SECRET_NAMES:
        assert stored[name] == FAKE_NEW_SECRETS[name]
    assert protocol.password_changes == [
        (b"kivou_app", FAKE_NEW_ROLE_PASSWORD.encode())
    ]
    assert connection.closed


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


def test_runbook_uses_executable_masked_provider_and_local_postgres_rotation() -> None:
    body = RUNBOOK.read_text(encoding="utf-8")

    for command_fragment in (
        "set-secret SMTP_PASSWORD",
        "set-secret STRIPE_SECRET_KEY",
        "set-secret STRIPE_WEBHOOK_SECRET",
        "rotate-postgres-password",
        "--old-env-file /etc/kivou/staging.env",
        "/srv/kivou/app/.venv/bin/python",
        "ALTER ROLE",
        "PGconn.change_password",
        "/dev/tty",
        "saisie masquée",
        "sudo awk -F=",
    ):
        assert command_fragment in body


def test_ops_readme_points_operators_to_the_counter_only_cli_and_runbook() -> None:
    body = OPERATIONS.read_text(encoding="utf-8")

    assert "09-staging-secret-rotation.md" in body
    assert "kivou_secret_hygiene.py" in body
    assert "replace-env" in body
    assert "audit-journal" in body
    assert "set-secret" in body
    assert "rotate-postgres-password" in body
    assert "valeurs uniquement depuis des fichiers `0600`" in body
