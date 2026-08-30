"""Upload hors hôte exercé sans réseau ni dépôt restic réel.

Les deux exécutables injectés ne font qu'enregistrer leurs arguments. Les
identifiants ci-dessous sont explicitement inventés et ne donnent accès à rien.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import stat
import subprocess
import textwrap
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "ops" / "bin" / "kivou-restic-upload.sh"

EX_DATAERR = 65
EX_NOINPUT = 66
EX_UNAVAILABLE = 69
EX_TEMPFAIL = 75

INVENTED_REPOSITORY = "swift:invented-kivou-tests:/invented-offsite"
INVENTED_RESTIC_PASSWORD = "invented-restic-password-never-real"
INVENTED_SWIFT_PASSWORD = "invented-swift-password-never-real"
INVENTED_SECRETS = (
    INVENTED_REPOSITORY,
    INVENTED_RESTIC_PASSWORD,
    INVENTED_SWIFT_PASSWORD,
)
VALID_DUMP = b"KIVOU-FAKE-CUSTOM-DUMP\n" + b"verified-payload" * 32


class Runtime:
    """Un répertoire de dumps et des binaires fake entièrement jetables."""

    def __init__(self, tmp_path: pathlib.Path) -> None:
        self.root = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.backup_dir = tmp_path / "backups"
        self.backup_dir.mkdir(mode=0o700)
        self.backup_dir.chmod(0o700)
        self.journal = tmp_path / "calls.tsv"
        self.hashes = tmp_path / "restic-hashes.tsv"
        self.restic = self._install(
            "restic",
            """
            printf 'restic' >> "$FAKE_CALLS"
            printf '\\t%s' "$@" >> "$FAKE_CALLS"
            printf '\\n' >> "$FAKE_CALLS"
            if [ "${FAKE_TOOL_LEAKS:-0}" -eq 1 ]; then
                printf '%s %s %s\\n' \
                    "$RESTIC_REPOSITORY" "$RESTIC_PASSWORD" "$OS_PASSWORD" >&2
            fi
            if [ "${1-}" = backup ]; then
                archive="${!#}"
                sha256sum -- "$archive" | cut -d ' ' -f 1 | \
                    tr -d '\\n' >> "$FAKE_HASHES"
                printf '\\t%s\\n' "$archive" >> "$FAKE_HASHES"
                exit "${FAKE_RESTIC_BACKUP_EXIT:-0}"
            fi
            """,
        )
        self.pg_restore = self._install(
            "pg_restore",
            """
            printf 'pg_restore' >> "$FAKE_CALLS"
            printf '\\t%s' "$@" >> "$FAKE_CALLS"
            printf '\\n' >> "$FAKE_CALLS"
            if [ "${FAKE_TOOL_LEAKS:-0}" -eq 1 ]; then
                printf '%s %s %s\\n' \
                    "$RESTIC_REPOSITORY" "$RESTIC_PASSWORD" "$OS_PASSWORD" >&2
            fi
            if [ -n "${FAKE_PG_RESTORE_READY:-}" ]; then
                : > "$FAKE_PG_RESTORE_READY"
                while [ ! -e "$FAKE_PG_RESTORE_CONTINUE" ]; do sleep 0.01; done
            fi
            archive="${!#}"
            IFS= read -r header < "$archive" || exit 41
            [ "$header" = KIVOU-FAKE-CUSTOM-DUMP ] || exit 41
            exit "${FAKE_PG_RESTORE_EXIT:-0}"
            """,
        )

    def _install(self, name: str, body: str) -> pathlib.Path:
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -u\n" + textwrap.dedent(body))
        path.chmod(0o755)
        return path

    def dump(
        self,
        name: str = "kivou-20260830T120000Z.dump",
        *,
        content: bytes = VALID_DUMP,
        mode: int = 0o600,
        mtime: float | None = None,
    ) -> pathlib.Path:
        path = self.backup_dir / name
        path.write_bytes(content)
        path.chmod(mode)
        timestamp = time.time() - 60 if mtime is None else mtime
        os.utime(path, (timestamp, timestamp))
        return path

    def environment(
        self,
        *,
        missing: tuple[str, ...] = (),
        overrides: dict[str, str] | None = None,
    ) -> dict[str, str]:
        environment = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.root),
            "KIVOU_BACKUP_DIR": str(self.backup_dir),
            "KIVOU_BACKUP_MAX_AGE_SECONDS": "7200",
            "KIVOU_RESTIC": str(self.restic),
            "KIVOU_PG_RESTORE": str(self.pg_restore),
            "RESTIC_REPOSITORY": INVENTED_REPOSITORY,
            "RESTIC_PASSWORD": INVENTED_RESTIC_PASSWORD,
            "OS_PASSWORD": INVENTED_SWIFT_PASSWORD,
            "FAKE_CALLS": str(self.journal),
            "FAKE_HASHES": str(self.hashes),
        }
        for name in missing:
            environment.pop(name)
        environment.update(overrides or {})
        return environment

    def run(
        self,
        *,
        missing: tuple[str, ...] = (),
        overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env=self.environment(missing=missing, overrides=overrides),
            timeout=30,
        )

    def start(self, *, overrides: dict[str, str]) -> subprocess.Popen[str]:
        return subprocess.Popen(
            ["bash", str(SCRIPT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.environment(overrides=overrides),
        )

    def calls(self) -> list[str]:
        if not self.journal.exists():
            return []
        return self.journal.read_text().splitlines()

    def uploaded_hashes(self) -> list[str]:
        if not self.hashes.exists():
            return []
        return self.hashes.read_text().splitlines()

    def snapshots(self) -> list[pathlib.Path]:
        return [
            path
            for path in self.backup_dir.glob(".kivou-restic-upload.*")
            if path.is_dir()
        ]


@pytest.fixture
def runtime(tmp_path: pathlib.Path) -> Runtime:
    return Runtime(tmp_path)


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def assert_secrets_absent(result: subprocess.CompletedProcess[str]) -> None:
    output = combined_output(result)
    for invented_secret in INVENTED_SECRETS:
        assert invented_secret not in output


def wait_for_file(path: pathlib.Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        assert time.monotonic() < deadline, f"timeout waiting for {path.name}"
        time.sleep(0.01)


def test_verified_dump_is_uploaded_before_remote_retention(runtime: Runtime) -> None:
    dump = runtime.dump()

    result = runtime.run()

    assert result.returncode == 0, result.stderr
    calls = runtime.calls()
    snapshot = pathlib.Path(calls[0].split("\t")[-1])
    assert snapshot.parent.parent == runtime.backup_dir
    assert snapshot.parent.name.startswith(".kivou-restic-upload.")
    assert snapshot.name == dump.name
    assert calls == [
        f"pg_restore\t--list\t{snapshot}",
        (
            "restic\tbackup\t--tag\tkivou-postgresql\t--host\t"
            f"kivou-production-01\t--\t{snapshot}"
        ),
        (
            "restic\tforget\t--tag\tkivou-postgresql\t--host\t"
            "kivou-production-01\t--group-by\thost,tags\t--keep-daily\t30\t"
            "--keep-monthly\t12\t--keep-yearly\t3\t--prune"
        ),
    ]
    assert runtime.uploaded_hashes()[0].split("\t")[0] == hashlib.sha256(
        VALID_DUMP
    ).hexdigest()
    assert dump.exists(), "l'upload ne doit jamais supprimer la copie locale"
    assert runtime.snapshots() == []


@pytest.mark.parametrize(
    "failure",
    [
        {"FAKE_PG_RESTORE_EXIT": "17"},
        {"FAKE_RESTIC_BACKUP_EXIT": "23"},
    ],
    ids=["pg-restore-list", "restic-backup"],
)
def test_verification_or_upload_failure_never_runs_forget(
    runtime: Runtime, failure: dict[str, str]
) -> None:
    dump = runtime.dump()

    result = runtime.run(overrides=failure)

    assert result.returncode != 0
    assert not any(call.startswith("restic\tforget\t") for call in runtime.calls())
    assert dump.exists()
    assert runtime.snapshots() == []


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("missing", EX_NOINPUT),
        ("empty", EX_NOINPUT),
        ("stale", EX_TEMPFAIL),
        ("future", EX_TEMPFAIL),
        ("symlink", EX_DATAERR),
        ("public-mode", EX_DATAERR),
    ],
)
def test_invalid_local_dump_is_rejected_before_restic(
    runtime: Runtime, kind: str, expected_code: int
) -> None:
    now = time.time()
    if kind == "empty":
        runtime.dump(content=b"")
    elif kind == "stale":
        runtime.dump(mtime=now - 8000)
    elif kind == "future":
        runtime.dump(mtime=now + 300)
    elif kind == "symlink":
        target = runtime.root / "invented.dump"
        target.write_bytes(VALID_DUMP)
        target.chmod(0o600)
        (runtime.backup_dir / "kivou-20260830T120000Z.dump").symlink_to(target)
    elif kind == "public-mode":
        runtime.dump(mode=0o640)

    result = runtime.run()

    assert result.returncode == expected_code, combined_output(result)
    assert not any(call.startswith("restic\t") for call in runtime.calls())


@pytest.mark.parametrize("kind", ["relative", "missing", "symlink", "noncanonical", "mode"])
def test_untrusted_backup_directory_is_rejected_before_tools(
    runtime: Runtime, kind: str
) -> None:
    backup_dir = runtime.backup_dir
    if kind == "relative":
        configured = "backups"
    elif kind == "missing":
        configured = str(runtime.root / "does-not-exist")
    elif kind == "symlink":
        link = runtime.root / "backup-link"
        link.symlink_to(backup_dir, target_is_directory=True)
        configured = str(link)
    elif kind == "noncanonical":
        configured = str(backup_dir / ".." / backup_dir.name)
    else:
        backup_dir.chmod(0o750)
        configured = str(backup_dir)

    result = runtime.run(overrides={"KIVOU_BACKUP_DIR": configured})

    assert result.returncode == EX_DATAERR
    assert runtime.calls() == []


@pytest.mark.parametrize(
    "kind", ["hardlink", "hostile-name", "invalid-calendar", "future-name"]
)
def test_untrusted_dump_identity_is_rejected_before_tools(runtime: Runtime, kind: str) -> None:
    if kind == "hardlink":
        dump = runtime.dump()
        os.link(dump, runtime.root / "second-link.dump")
    elif kind == "hostile-name":
        runtime.dump("kivou-20260830T120000Z\n.dump")
    elif kind == "invalid-calendar":
        runtime.dump("kivou-20261340T256199Z.dump")
    else:
        runtime.dump("kivou-20991231T235959Z.dump")

    result = runtime.run()

    assert result.returncode in (EX_DATAERR, EX_TEMPFAIL)
    assert runtime.calls() == []


def test_truncated_dump_is_rejected_by_pg_restore_before_upload(runtime: Runtime) -> None:
    runtime.dump(content=b"truncated")

    result = runtime.run()

    assert result.returncode != 0
    assert runtime.calls()[0].startswith("pg_restore\t--list\t")
    assert not any(call.startswith("restic\t") for call in runtime.calls())
    assert runtime.snapshots() == []


@pytest.mark.parametrize("missing_name", ["RESTIC_REPOSITORY", "RESTIC_PASSWORD"])
def test_missing_restic_configuration_names_only_the_variable(
    runtime: Runtime, missing_name: str
) -> None:
    runtime.dump()

    result = runtime.run(missing=(missing_name,))

    assert result.returncode == 64
    assert combined_output(result) == (
        f"[kivou-restic-upload] configuration_missing name={missing_name}\n"
    )
    assert_secrets_absent(result)
    assert runtime.calls() == []


@pytest.mark.parametrize(
    ("override_name", "missing_binary"),
    [
        ("KIVOU_RESTIC", "restic-missing"),
        ("KIVOU_PG_RESTORE", "pg-restore-missing"),
    ],
)
def test_missing_binary_fails_closed(
    runtime: Runtime, override_name: str, missing_binary: str
) -> None:
    runtime.dump()

    result = runtime.run(
        overrides={override_name: str(runtime.root / "absent" / missing_binary)}
    )

    assert result.returncode == EX_UNAVAILABLE
    assert missing_binary in combined_output(result)
    assert runtime.calls() == []
    assert_secrets_absent(result)


@pytest.mark.parametrize(
    "failure",
    [{}, {"FAKE_PG_RESTORE_EXIT": "17"}, {"FAKE_RESTIC_BACKUP_EXIT": "23"}],
    ids=["success", "verification-failure", "upload-failure"],
)
def test_output_never_exposes_restic_or_swift_secrets(
    runtime: Runtime, failure: dict[str, str]
) -> None:
    runtime.dump()
    failure["FAKE_TOOL_LEAKS"] = "1"

    result = runtime.run(overrides=failure)

    assert_secrets_absent(result)


def test_newest_dump_is_selected_by_mtime_not_lexical_name(runtime: Runtime) -> None:
    now = time.time()
    lexically_newer = runtime.dump(
        "kivou-20260830T130000Z.dump", mtime=now - 600
    )
    actually_newer = runtime.dump(
        "kivou-20260830T120000Z.dump", mtime=now - 60
    )

    result = runtime.run()

    assert result.returncode == 0, result.stderr
    snapshot = pathlib.Path(runtime.calls()[0].split("\t")[-1])
    assert snapshot.name == actually_newer.name
    assert runtime.calls()[0] == f"pg_restore\t--list\t{snapshot}"
    assert str(snapshot) in runtime.calls()[1]
    assert str(lexically_newer) not in "\n".join(runtime.calls())
    assert stat.S_IMODE(actually_newer.stat().st_mode) == 0o600


def test_replacing_original_path_after_snapshot_cannot_change_uploaded_bytes(
    runtime: Runtime,
) -> None:
    original_bytes = VALID_DUMP + b"original"
    replacement_bytes = VALID_DUMP + b"replacement"
    dump = runtime.dump(content=original_bytes)
    ready = runtime.root / "pg-restore-ready"
    proceed = runtime.root / "pg-restore-continue"
    process = runtime.start(
        overrides={
            "FAKE_PG_RESTORE_READY": str(ready),
            "FAKE_PG_RESTORE_CONTINUE": str(proceed),
        }
    )
    try:
        wait_for_file(ready)
        replacement = runtime.root / "replacement.dump"
        replacement.write_bytes(replacement_bytes)
        replacement.chmod(0o600)
        os.replace(replacement, dump)
        proceed.touch()
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    assert process.returncode == 0, stdout + stderr
    uploaded_digest = runtime.uploaded_hashes()[0].split("\t")[0]
    assert uploaded_digest == hashlib.sha256(original_bytes).hexdigest()
    assert uploaded_digest != hashlib.sha256(replacement_bytes).hexdigest()
    assert dump.read_bytes() == replacement_bytes
    assert runtime.snapshots() == []


def test_concurrent_upload_is_rejected_while_first_holds_local_lock(
    runtime: Runtime,
) -> None:
    runtime.dump()
    ready = runtime.root / "pg-restore-ready"
    proceed = runtime.root / "pg-restore-continue"
    first = runtime.start(
        overrides={
            "FAKE_PG_RESTORE_READY": str(ready),
            "FAKE_PG_RESTORE_CONTINUE": str(proceed),
        }
    )
    try:
        wait_for_file(ready)
        second = runtime.run()
        proceed.touch()
        first_stdout, first_stderr = first.communicate(timeout=10)
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()

    assert second.returncode == EX_TEMPFAIL
    assert "upload_already_running" in combined_output(second)
    assert first.returncode == 0, first_stdout + first_stderr
    assert sum(call.startswith("pg_restore\t") for call in runtime.calls()) == 1
