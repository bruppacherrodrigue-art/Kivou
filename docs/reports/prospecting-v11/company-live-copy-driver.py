"""Operator-only copy creation/checks; default read-only preflight, never activation.

Credentials arrive only via protected KIVOU_DATABASE_URL and
KIVOU_MIGRATION_ADMIN_URL. Verified backups and private reports are retained.
--keep-copy retains the owned copy on success or failure for separate rollback
investigation. Root alone executes this tool on an explicitly selected host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

SOURCES = {
    "STAGING": ("kivou_staging", "0060_boamp_notice_facts"),
    "PRODUCTION": ("kivou", "0058_model_call_budget"),
}
CHECKER = "docs/reports/prospecting-v11/company-live-rehearsal.py"
BACKUP = "ops/bin/kivou-backup.sh"
SHARED = {
    "supplier_directory",
    "model_daily_budget",
    "model_call_journal",
    "notice_source_snapshot",
    "notice_award_facts",
}
MAX_OUTPUT = 65536


class DriverFailure(RuntimeError):
    """Only a closed operator code, never an external exception or private value."""


class ChildCleanupFailure(DriverFailure):
    """Copy DROP is unsafe until an owned child group is confirmed absent."""


def require(condition, code):
    if not condition:
        raise DriverFailure(code)


def base_environment():
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}


def parse_url(value, database):
    try:
        url = make_url(value)
        valid = (
            url.drivername in {"postgresql", "postgresql+psycopg"}
            and (url.host, url.database) == ("127.0.0.1", database)
            and url.port in {None, 5432}
            and not url.query
            and bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", url.username or ""))
            and bool(url.password)
            and "\x00" not in url.password
        )
    except Exception:  # noqa: BLE001 - URL parser errors must never echo credentials
        raise DriverFailure("database_url_invalid") from None
    require(valid, "database_url_invalid")
    return url.set(port=5432)


def pg_environment(url, *, database=None):
    return {
        **base_environment(),
        "PGHOST": "127.0.0.1",
        "PGPORT": "5432",
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
        "PGDATABASE": database or url.database,
        "PGCONNECT_TIMEOUT": "10",
    }


def checker_environment(admin, name, sha):
    validate_name(name, sha)
    copy = admin.set(database=name, drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )
    return {
        **base_environment(),
        "KIVOU_DATABASE_URL": copy,
        "KIVOU_V11_REHEARSAL_DATABASE_URL": copy,
        "KIVOU_V11_REHEARSAL_DATABASE_NAME": name,
        "KIVOU_V11_CANDIDATE_SHA": sha,
    }


def connect(url):
    return psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        connect_timeout=10,
        autocommit=True,
    )


def inspect_source(url, head):
    with connect(url) as connection:
        connection.execute("BEGIN READ ONLY")
        try:
            require(
                connection.execute("SELECT current_database()").fetchone() == (url.database,),
                "connected_source_mismatch",
            )
            require(
                connection.execute("SELECT version_num FROM alembic_version").fetchall()
                == [(head,)],
                "source_head_mismatch",
            )
            size = connection.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            require(type(size) is int and size > 0, "source_size_invalid")
            return size
        finally:
            connection.execute("ROLLBACK")


def check_admin(connection):
    require(
        connection.execute("SELECT current_database()").fetchone() == ("postgres",),
        "connected_admin_mismatch",
    )


def git(candidate, *arguments):
    result = subprocess.run(
        ["git", "-C", str(candidate), *arguments],
        env=base_environment(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    require(
        result.returncode == 0 and len(result.stdout) <= MAX_OUTPUT, "artifact_git_check_failed"
    )
    return result.stdout.strip()


def verify_artifact(candidate, sha, *, checker=False):
    require(
        candidate.is_absolute() and candidate.resolve(strict=True) == candidate,
        "physical_artifact_required",
    )
    require(git(candidate, "rev-parse", "HEAD") == sha, "artifact_sha_mismatch")
    require(
        git(candidate, "rev-parse", "--show-toplevel") == str(candidate),
        "artifact_git_root_mismatch",
    )
    git(candidate, "diff", "--quiet", "HEAD", "--")
    if checker:
        git(
            candidate,
            "ls-files",
            "--error-unmatch",
            "--",
            CHECKER,
            BACKUP,
            "docs/reports/prospecting-v11/rehearsal-checks.py",
        )
        require(
            (candidate / CHECKER).is_file()
            and os.access(candidate / BACKUP, os.X_OK)
            and os.access(candidate / ".venv/bin/python", os.X_OK),
            "candidate_tools_missing",
        )


def source_artifact(config):
    observed = Path("/srv/kivou/app").resolve(strict=True)
    expected = config.source_root
    require(
        expected.is_absolute() and expected.parent == Path("/srv/kivou/releases"),
        "source_release_root_invalid",
    )
    require(observed == expected, "active_source_artifact_mismatch")
    verify_artifact(observed, config.source_sha)


def check_space(database_bytes):
    free = min(shutil.disk_usage(path).free for path in ("/var/tmp", "/var/lib/postgresql"))
    require(free >= 2 * database_bytes + 2 * 1024**3, "insufficient_disposable_restore_space")
    return free


def preflight(config):
    verify_artifact(config.candidate, config.sha, checker=True)
    source_artifact(config)
    require(config.sha != config.source_sha, "candidate_already_active")
    size = inspect_source(config.source, config.head)
    with connect(config.admin) as connection:
        connection.execute("BEGIN READ ONLY")
        try:
            check_admin(connection)
        finally:
            connection.execute("ROLLBACK")
    return {"source_database_bytes": size, "free_bytes_before_rehearsal": check_space(size)}


def assert_source_unchanged(config):
    source_artifact(config)
    inspect_source(config.source, config.head)


def persist_report(evidence, report):
    info = evidence.lstat()
    require(
        stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077,
        "private_evidence_required",
    )
    fd, temporary = tempfile.mkstemp(prefix="report.", suffix=".tmp", dir=evidence)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, evidence / "report.json")
        directory = os.open(evidence, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reap_group(group, *, reap_leader=None):
    require(type(group) is int and group > 1, "child_group_invalid")

    def exists():
        if reap_leader is not None:
            reap_leader()
        try:
            os.killpg(group, 0)
            return True
        except ProcessLookupError:
            return False

    if not exists():
        return False
    for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 1)):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            return True
        deadline = monotonic() + grace
        while exists() and monotonic() < deadline:
            sleep(0.05)
        if not exists():
            return True
    raise ChildCleanupFailure("child_group_cleanup_unconfirmed")


def run_child(argv, *, env, evidence, timeout, capture=False):
    # Temporary output is private, never a diagnostic log; stderr is discarded.
    with tempfile.TemporaryFile(dir=evidence) as output:
        child = subprocess.Popen(
            argv,
            env=env,
            stdout=output if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        timed_out = False
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                orphaned = reap_group(child.pid, reap_leader=child.poll)
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    raise ChildCleanupFailure("child_reap_unconfirmed") from None
            except ChildCleanupFailure:
                raise
            except BaseException:  # noqa: BLE001 - any uncertain cleanup forbids DROP
                # Even an operator interruption during cleanup leaves process
                # ownership unconfirmed; the caller must not DROP the copy.
                raise ChildCleanupFailure("child_group_cleanup_unconfirmed") from None
        require(not timed_out, "child_timeout")
        require(child.returncode == 0, "child_failed")
        require(not orphaned, "child_orphan_group")
        output.seek(0)
        data = output.read(MAX_OUTPUT + 1)
        require(len(data) <= MAX_OUTPUT, "child_output_limit")
        return data.decode("utf-8")


def validate_name(name, sha):
    require(
        bool(re.fullmatch(r"[0-9a-f]{40}", sha))
        and bool(re.fullmatch(rf"kivou_v11_rehearsal_{sha[:12]}_[0-9a-f]{{16}}", name)),
        "disposable_name_invalid",
    )


def create_owned(admin, name, sha, report):
    validate_name(name, sha)
    with connect(admin) as connection:
        check_admin(connection)
        require(
            not connection.execute(
                "SELECT oid FROM pg_database WHERE datname=%s", (name,)
            ).fetchone(),
            "disposable_already_exists",
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
        )
        report["copy_created"] = True
        row = connection.execute("SELECT oid FROM pg_database WHERE datname=%s", (name,)).fetchone()
        require(row is not None and type(row[0]) is int and row[0] > 0, "created_oid_unconfirmed")
        report["copy_oid"] = row[0]


def drop_owned(admin, name, oid, sha):
    validate_name(name, sha)
    require(type(oid) is int and oid > 0, "created_oid_unconfirmed")
    with connect(admin) as connection:
        check_admin(connection)
        require(
            connection.execute("SELECT oid FROM pg_database WHERE datname=%s", (name,)).fetchone()
            == (oid,),
            "disposable_oid_changed_cleanup_refused",
        )
        connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        require(
            not connection.execute(
                "SELECT oid FROM pg_database WHERE datname=%s", (name,)
            ).fetchone(),
            "disposable_removal_unconfirmed",
        )


def accepted_dump(evidence):
    dumps = list(evidence.glob("kivou-*.dump"))
    require(len(dumps) == 1, "ambiguous_backup")
    dump = dumps[0]
    info = dump.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_size >= 4096,
        "invalid_private_dump",
    )
    digest = hashlib.sha256()
    with dump.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return dump, info.st_size, digest.hexdigest()


def checked_report(raw, config):
    try:
        result = json.loads(raw)
        expected = {
            "status": "passed",
            "sha": config.sha,
            "source_sha": config.source_sha,
            "source_environment": config.environment,
            "restored_head": config.head,
            "legacy_preserved": True,
            "replay_preserved": True,
        }
        require(
            all(
                type(result.get(key)) is type(value) and result[key] == value
                for key, value in expected.items()
            ),
            "candidate_checks_failed",
        )
        head = result["candidate_head"]
        require(
            isinstance(head, str) and bool(re.fullmatch(r"[0-9]{4}_[a-z0-9_]{1,27}", head)),
            "candidate_report_invalid",
        )
        counts = {
            key: result[key]
            for key in ("baseline_tables", "baseline_rows", "legacy_accounts_exported")
        }
        shared = result["shared_baseline_rows"]
        require(
            isinstance(shared, dict)
            and shared.keys() <= SHARED
            and all(
                type(value) is int and value >= 0 for value in (*counts.values(), *shared.values())
            ),
            "candidate_report_invalid",
        )
        return {**expected, **counts, "candidate_head": head, "shared_baseline_rows": shared}
    except DriverFailure:
        raise
    except Exception:  # noqa: BLE001 - malformed child output is never forwarded
        raise DriverFailure("candidate_report_invalid") from None


def perform_copy(config, name, evidence, report):
    child_cleanup_confirmed = True
    report["cleanup_status"] = "not_created"
    try:
        environment = pg_environment(config.source)
        environment.update(
            {
                "KIVOU_DATABASE_URL": config.source._replace(password=None).render_as_string(
                    hide_password=False
                ),
                "KIVOU_BACKUP_DIR": str(evidence),
                "KIVOU_BACKUP_LOCK_FILE": str(evidence / "backup.lock"),
                "KIVOU_BACKUP_RETENTION_DAYS": "14",
                "KIVOU_BACKUP_MIN_BYTES": "4096",
            }
        )
        run_child(
            [str(config.candidate / BACKUP)], env=environment, evidence=evidence, timeout=1800
        )
        dump, size, digest = accepted_dump(evidence)
        report.update(
            backup_retained=True,
            backup_path=str(dump),
            backup_bytes=size,
            backup_sha256=digest,
            stage="create",
        )
        persist_report(evidence, report)
        create_owned(config.admin, name, config.sha, report)
        report["stage"] = "restore"
        persist_report(evidence, report)
        run_child(
            [
                "pg_restore",
                "--dbname",
                name,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                str(dump),
            ],
            env=pg_environment(config.admin, database=name),
            evidence=evidence,
            timeout=1800,
        )
        report.update(copy_restored=True, stage="candidate_checks")
        persist_report(evidence, report)
        raw = run_child(
            [
                str(config.candidate / ".venv/bin/python"),
                str(config.candidate / CHECKER),
                "--source-environment",
                config.environment,
                "--expected-deployed-head",
                config.head,
                "--source-sha",
                config.source_sha,
            ],
            env=checker_environment(config.admin, name, config.sha),
            evidence=evidence,
            timeout=1800,
            capture=True,
        )
        report["checks"] = checked_report(raw, config)
    except ChildCleanupFailure:
        child_cleanup_confirmed = False
        raise
    finally:
        # No report write can prevent this cleanup attempt. Never delete dumps.
        if report.get("copy_created"):
            report["cleanup_status"] = "cleanup_refused"
            if child_cleanup_confirmed and config.keep_copy and report.get("copy_oid"):
                with connect(config.admin) as connection:
                    check_admin(connection)
                    require(
                        connection.execute(
                            "SELECT oid FROM pg_database WHERE datname=%s", (name,)
                        ).fetchone()
                        == (report["copy_oid"],),
                        "disposable_oid_changed_cleanup_refused",
                    )
                report["cleanup_status"] = "retained_intentionally"
            elif child_cleanup_confirmed and not config.keep_copy:
                drop_owned(config.admin, name, report.get("copy_oid"), config.sha)
                report["cleanup_status"] = "dropped"
        assert_source_unchanged(config)
        report["source_revision_and_artifact_unchanged"] = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=tuple(SOURCES), required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--keep-copy", action="store_true")
    args = parser.parse_args(argv)
    evidence, handlers = None, {}
    report = {"status": "failed"}
    try:
        for key in tuple(os.environ):
            if key.startswith("PG"):
                del os.environ[key]
        require(
            all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (args.sha, args.source_sha)),
            "sha_invalid",
        )
        database, head = SOURCES[args.environment]
        config = SimpleNamespace(
            environment=args.environment,
            sha=args.sha,
            source_sha=args.source_sha,
            source_root=Path(args.source_root),
            candidate=Path(args.candidate_root),
            head=head,
            keep_copy=args.keep_copy,
            source=parse_url(os.environ.get("KIVOU_DATABASE_URL", ""), database),
            admin=parse_url(os.environ.get("KIVOU_MIGRATION_ADMIN_URL", ""), "postgres"),
        )
        report.update(
            preflight(config),
            environment=args.environment,
            candidate_sha=args.sha,
            source_sha=args.source_sha,
            source_head=head,
        )
        if not args.execute:
            report["status"] = "preflight_passed"
        else:
            name = f"kivou_v11_rehearsal_{args.sha[:12]}_{secrets.token_hex(8)}"
            validate_name(name, args.sha)
            evidence = Path(tempfile.mkdtemp(prefix="kivou-company-copy.", dir="/var/tmp"))
            report.update(
                status="running",
                stage="backup",
                copy_database=name,
                private_evidence_directory=str(evidence),
            )
            persist_report(evidence, report)

            def interrupted(_number, _frame):
                raise DriverFailure("operator_interrupted")

            for sig in (signal.SIGTERM, signal.SIGINT):
                handlers[sig] = signal.signal(sig, interrupted)
            perform_copy(config, name, evidence, report)
            report.update(status="passed", stage="complete")
        code = 0
    except DriverFailure as error:
        report.update(status="failed", code=str(error))
        code = 2
    except Exception:  # noqa: BLE001 - operator boundary must not expose private diagnostics
        report.update(status="failed", code="copy_driver_failed")
        code = 2
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if evidence is not None:
            try:
                persist_report(evidence, report)
            except Exception:  # noqa: BLE001 - evidence failure is closed too
                report.update(status="failed", evidence_write_failed=True)
                code = 2
    print(json.dumps(report, sort_keys=True), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
