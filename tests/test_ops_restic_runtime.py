"""Upload hors hôte exercé sans réseau ni dépôt restic réel.

Les deux exécutables injectés ne font qu'enregistrer leurs arguments. Les
identifiants ci-dessous sont explicitement inventés et ne donnent accès à rien.
"""

from __future__ import annotations

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


class Runtime:
    """Un répertoire de dumps et des binaires fake entièrement jetables."""

    def __init__(self, tmp_path: pathlib.Path) -> None:
        self.root = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.backup_dir = tmp_path / "backups"
        self.backup_dir.mkdir()
        self.journal = tmp_path / "calls.tsv"
        self.restic = self._install(
            "restic",
            """
            printf 'restic' >> "$FAKE_CALLS"
            printf '\\t%s' "$@" >> "$FAKE_CALLS"
            printf '\\n' >> "$FAKE_CALLS"
            if [ "${1-}" = backup ]; then
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
        content: bytes = b"invented-postgresql-dump-bytes",
        mode: int = 0o600,
        mtime: float | None = None,
    ) -> pathlib.Path:
        path = self.backup_dir / name
        path.write_bytes(content)
        path.chmod(mode)
        timestamp = time.time() - 60 if mtime is None else mtime
        os.utime(path, (timestamp, timestamp))
        return path

    def run(
        self,
        *,
        missing: tuple[str, ...] = (),
        overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
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
        }
        for name in missing:
            environment.pop(name)
        environment.update(overrides or {})
        return subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=30,
        )

    def calls(self) -> list[str]:
        if not self.journal.exists():
            return []
        return self.journal.read_text().splitlines()


@pytest.fixture
def runtime(tmp_path: pathlib.Path) -> Runtime:
    return Runtime(tmp_path)


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def assert_secrets_absent(result: subprocess.CompletedProcess[str]) -> None:
    output = combined_output(result)
    for invented_secret in INVENTED_SECRETS:
        assert invented_secret not in output


def test_verified_dump_is_uploaded_before_remote_retention(runtime: Runtime) -> None:
    dump = runtime.dump()

    result = runtime.run()

    assert result.returncode == 0, result.stderr
    assert runtime.calls() == [
        f"pg_restore\t--list\t{dump}",
        (
            "restic\tbackup\t--tag\tkivou-postgresql\t--host\t"
            f"kivou-production-01\t--\t{dump}"
        ),
        (
            "restic\tforget\t--tag\tkivou-postgresql\t--keep-daily\t30\t"
            "--keep-monthly\t12\t--keep-yearly\t3\t--prune"
        ),
    ]
    assert dump.exists(), "l'upload ne doit jamais supprimer la copie locale"


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
        target.write_bytes(b"invented-postgresql-dump-bytes")
        target.chmod(0o600)
        (runtime.backup_dir / "kivou-20260830T120000Z.dump").symlink_to(target)
    elif kind == "public-mode":
        runtime.dump(mode=0o640)

    result = runtime.run()

    assert result.returncode == expected_code, combined_output(result)
    assert not any(call.startswith("restic\t") for call in runtime.calls())


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
    assert runtime.calls()[0] == f"pg_restore\t--list\t{actually_newer}"
    assert str(actually_newer) in runtime.calls()[1]
    assert str(lexically_newer) not in "\n".join(runtime.calls())
    assert stat.S_IMODE(actually_newer.stat().st_mode) == 0o600
