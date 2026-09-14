"""Actual candidate/legacy API round-trip on an operator-created PostgreSQL copy.

Run with the candidate interpreter, --execute, explicit --candidate-root,
--candidate-sha, --legacy-root, --legacy-sha, --source-environment and --report.
Both database environment URLs must name the same fenced rehearsal copy.
The copy must already be migrated. This tool never migrates, creates/drops a
database, changes a service/release link, or calls a provider. Reports are private.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import runpy
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from http.cookies import SimpleCookie
from pathlib import Path

import sqlalchemy as sa

COPY_KEYS = (
    "KIVOU_V11_CANDIDATE_SHA",
    "KIVOU_V11_REHEARSAL_DATABASE_URL",
    "KIVOU_DATABASE_URL",
    "KIVOU_V11_REHEARSAL_DATABASE_NAME",
)
BUSINESS_TABLES = (
    "company_note",
    "company_manual_contact",
    "company_contact",
    "account_company_membership",
    "signal_note",
    "signal_workflow",
    "signal_feedback",
)


class RollbackFailure(ValueError):
    """Only operator-owned closed reason codes cross the reporting boundary."""


def require(condition, code):
    if not condition:
        raise RollbackFailure(code)


def failure_report(error):
    return {
        "status": "failed",
        "code": str(error) if isinstance(error, RollbackFailure) else "rollback_execution_failed",
    }


def validate_environment(environment):
    sha, raw, default, name = (environment.get(key, "") for key in COPY_KEYS)
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "candidate_sha_invalid")
    require(
        bool(re.fullmatch(rf"kivou_v11_rehearsal_{sha[:12]}_[0-9a-f]{{16}}", name)),
        "copy_name_invalid",
    )
    try:
        target, other = sa.make_url(raw), sa.make_url(default)
    except (ValueError, sa.exc.ArgumentError) as error:
        raise RollbackFailure("copy_url_invalid") from error
    require(
        target.drivername in {"postgresql", "postgresql+psycopg"}
        and other.drivername in {"postgresql", "postgresql+psycopg"},
        "postgresql_required",
    )
    require(
        target.database == name and bool(target.host and target.username), "copy_identity_invalid"
    )
    require(
        target.set(drivername="postgresql+psycopg") == other.set(drivername="postgresql+psycopg"),
        "copy_urls_differ",
    )
    require(
        set(target.query)
        <= {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout", "application_name"},
        "copy_url_override",
    )
    return target.set(drivername="postgresql+psycopg"), sha, name


def child_environment(environment):
    validate_environment(environment)
    return {
        **{key: environment[key] for key in COPY_KEYS},
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def private_directory(path):
    info = path.lstat()
    require(
        path.is_absolute()
        and path.resolve() == path
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "private_directory_required",
    )


def persist_report(path, report):
    private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".rollback-report.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(report, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def git_environment():
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def verify_codebase(root, sha):
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha or "")), "artifact_sha_invalid")
    require(
        root is not None and root.is_absolute() and root.resolve(strict=True) == root,
        "physical_artifact_required",
    )
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=5,
        env=git_environment(),
    ).strip()
    require(actual == sha, "artifact_sha_mismatch")
    top = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=5,
        env=git_environment(),
    ).strip()
    require(Path(top) == root, "artifact_repository_mismatch")
    clean = subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
        env=git_environment(),
    )
    require(clean.returncode == 0, "artifact_dirty")
    require(
        (root / "src/signals/api/app.py").is_file() and (root / ".venv/bin/python").is_file(),
        "artifact_missing",
    )


def load_helpers(candidate):
    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(candidate),
            "ls-files",
            "--error-unmatch",
            "docs/reports/prospecting-v11/rehearsal-checks.py",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        env=git_environment(),
    )
    require(tracked.returncode == 0, "candidate_helper_not_tracked")
    sys.path.insert(0, str(candidate / "src"))
    import signals.api.app

    require(
        Path(signals.api.app.__file__).resolve() == candidate / "src/signals/api/app.py",
        "candidate_import_mismatch",
    )
    return runpy.run_path(str(candidate / "docs/reports/prospecting-v11/rehearsal-checks.py"))


def verify_copy(engine, name, head):
    require(engine.dialect.name == "postgresql", "postgresql_required")
    with engine.connect() as connection:
        require(
            connection.scalar(sa.text("SELECT current_database()")) == name,
            "connected_database_mismatch",
        )
        require(
            connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()
            == [head],
            "copy_schema_mismatch",
        )


def serve(arguments):
    target, _, name = validate_environment(os.environ)
    verify_codebase(arguments.code_root, arguments.code_sha)
    private_directory(arguments.socket.parent)
    require(
        arguments.socket.name == "api.sock"
        and not arguments.socket.exists()
        and not arguments.socket.is_symlink(),
        "socket_not_pristine",
    )
    sys.path.insert(0, str(arguments.code_root / "src"))
    import uvicorn

    import signals.api.app
    from signals.api import ApiConfig, create_app

    require(
        Path(signals.api.app.__file__).resolve() == arguments.code_root / "src/signals/api/app.py",
        "served_import_mismatch",
    )
    engine = sa.create_engine(target, hide_parameters=True)
    try:
        verify_copy(engine, name, arguments.schema_head)
        app = create_app(
            engine,
            ApiConfig(
                cookie_secure=False,
                allowed_origin="http://127.0.0.1",
                acquisition_environment=arguments.source_environment,
            ),
        )
        require(
            not app.dependency_overrides
            and app.state.stripe_gateway is None
            and app.state.company_contact_lookup_service is None,
            "external_service_or_auth_override",
        )
        uvicorn.run(
            app, uds=str(arguments.socket), workers=1, access_log=False, log_level="critical"
        )
    finally:
        engine.dispose()


def start_child(command, **kwargs):
    process = subprocess.Popen(command, start_new_session=True, **kwargs)
    process.rollback_pgid = process.pid
    return process


def stop_child(process):
    if process is None:
        return
    group = getattr(process, "rollback_pgid", None)
    require(
        group == process.pid and group > 1 and group != os.getpgrp(), "owned_process_group_required"
    )
    try:
        os.killpg(group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    # A reaped leader is insufficient: a forked descendant may keep a DB open.
    for number in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return
        try:
            os.killpg(group, number)
        except ProcessLookupError:
            return
        until = time.monotonic() + 5
        while time.monotonic() < until:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
    raise RollbackFailure("owned_process_group_survived")


@contextlib.contextmanager
def deadline():
    def interrupted(number, _frame):
        raise RollbackFailure(
            "operator_timeout" if number == signal.SIGALRM else "operator_interrupted"
        )

    previous = {
        number: signal.signal(number, interrupted)
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)
    }
    signal.alarm(240)
    try:
        yield
    finally:
        signal.alarm(0)
        for number, handler in previous.items():
            signal.signal(number, handler)


def nginx_config(directory, port, nonce):
    require(
        1024 <= port <= 65535 and bool(re.fullmatch(r"[A-Za-z0-9-]+", nonce)),
        "proxy_parameters_invalid",
    )
    require(bool(re.fullmatch(r"/[A-Za-z0-9_./-]+", str(directory))), "proxy_path_invalid")
    return f"""pid {directory}/nginx.pid;
error_log /dev/null;
events {{}}
http {{
 access_log off;
 client_body_temp_path {directory}/body;
 proxy_temp_path {directory}/proxy;
 fastcgi_temp_path {directory}/fastcgi;
 uwsgi_temp_path {directory}/uwsgi;
 scgi_temp_path {directory}/scgi;
 server {{
  listen 127.0.0.1:{port};
  server_name localhost;
  add_header X-Kivou-Rehearsal {nonce} always;
  include {directory}/mode.conf;
  location / {{ proxy_pass http://unix:{directory}/api.sock:; }}
 }}
}}
"""


def run_sequence(runtime):
    try:
        for stage in (
            "candidate_start",
            "prepare",
            "close_guard",
            "blocked_writes",
            "legacy_start",
            "legacy_read",
            "blocked_writes",
            "snapshot_check",
            "candidate_return",
            "candidate_read",
            "open_guard",
            "candidate_write",
            "baseline_check",
        ):
            getattr(runtime, stage)()
    finally:
        runtime.cleanup()


class Runtime:
    def __init__(self, arguments, environment, report):
        self.args, self.report = arguments, report
        self.api_process = self.proxy_process = self.engine = self.baseline = self.directory = None
        self.token = None
        self.closed, self.current = False, None
        self.nonce = secrets.token_hex(16)
        try:
            self.environment = child_environment(environment)
            target, _, name = validate_environment(environment)
            self.helper = load_helpers(arguments.candidate_root)
            self.head = self.helper["HEAD"]
            self.engine = sa.create_engine(target, hide_parameters=True)
            verify_copy(self.engine, name, self.head)
            # Original rows and helper-owned rows are never authenticated/mutated below.
            with self.helper["capture_baseline"](
                self.engine,
                temp_dir=arguments.report.parent,
                extra_tables=("supplier_directory", "company_directory_enrichment_job"),
            ) as original:
                self.report["private_contracts"] = self.helper["exercise_private_contracts"](
                    self.engine, now=dt.datetime.now(dt.UTC)
                )
                self.helper["compare_baseline"](self.engine, original)
            self.baseline = self.helper["capture_baseline"](
                self.engine,
                temp_dir=arguments.report.parent,
                extra_tables=("supplier_directory", "company_directory_enrichment_job"),
            )
            # Keep the owned Unix socket below its platform path-length limit.
            self.directory = Path(tempfile.mkdtemp(prefix="company-rollback.", dir="/tmp"))
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                self.port = reservation.getsockname()[1]
        except BaseException:
            self.cleanup()
            raise

    def request(
        self,
        method,
        path,
        body=None,
        *,
        expected=200,
        authenticated=True,
        json_result=True,
        if_match=None,
    ):
        require(
            self.proxy_process is not None and self.proxy_process.poll() is None, "proxy_exited"
        )
        headers = {"Origin": "http://127.0.0.1"}
        if if_match is not None:
            headers["If-Match"] = str(if_match)
        if authenticated and self.token:
            headers["Cookie"] = "kivou_session=" + self.token
        if body is not None:
            headers["Content-Type"] = "application/json"
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            client.request(
                method, path, body=None if body is None else json.dumps(body), headers=headers
            )
            response = client.getresponse()
            content = response.read(1024 * 1024 + 1)
            require(len(content) <= 1024 * 1024, "response_size_limit")
            require(
                response.getheader("X-Kivou-Rehearsal") == self.nonce, "proxy_identity_mismatch"
            )
            require(response.status == expected, "unexpected_http_status")
            if path == "/auth/signup" and expected == 201:
                cookie = SimpleCookie(response.getheader("Set-Cookie", ""))
                require("kivou_session" in cookie, "synthetic_session_missing")
                self.token = cookie["kivou_session"].value
            return json.loads(content) if json_result else content
        finally:
            client.close()

    def readiness(self):
        for _ in range(40):
            require(
                self.api_process.poll() is None and self.proxy_process.poll() is None,
                "child_exited",
            )
            try:
                self.request("GET", "/openapi.json", authenticated=False)
                return
            except (OSError, ValueError, http.client.HTTPException):
                time.sleep(0.25)
        raise RollbackFailure("readiness_timeout")

    def start_backend(self, root, sha):
        require(self.current is None or self.closed, "guard_must_precede_switch")
        stop_child(self.api_process)
        self.api_process = None
        path = self.directory / "api.sock"
        if path.exists():
            require(stat.S_ISSOCK(path.lstat().st_mode), "unexpected_socket_path")
            path.unlink()
        self.api_process = start_child(
            [
                str(root / ".venv/bin/python"),
                str(Path(__file__).resolve()),
                "--serve",
                "--code-root",
                str(root),
                "--code-sha",
                sha,
                "--socket",
                str(path),
                "--schema-head",
                self.head,
                "--source-environment",
                self.args.source_environment,
            ],
            cwd=root,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.current = root

    def start_proxy(self):
        stop_child(self.proxy_process)
        self.proxy_process = None
        command = [
            self.args.nginx,
            "-p",
            str(self.directory) + "/",
            "-c",
            str(self.directory / "nginx.conf"),
        ]
        subprocess.run(
            [*command, "-t"],
            check=True,
            timeout=5,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.proxy_process = start_child(
            [*command, "-g", "daemon off; master_process off;"],
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.readiness()

    def candidate_start(self):
        (self.directory / "nginx.conf").write_text(
            nginx_config(self.directory, self.port, self.nonce)
        )
        (self.directory / "mode.conf").write_bytes(
            (self.args.candidate_root / "ops/nginx/kivou-prospecting-open.conf").read_bytes()
        )
        self.start_backend(self.args.candidate_root, self.args.candidate_sha)
        self.start_proxy()

    def prepare(self):
        from signals.persistence.schema import supplier_directory
        from signals.supplier_directory.store import SupplierDirectoryStore

        # Pick an absent copy-only synthetic identifier; never overwrite a public row.
        sirens = [f"{secrets.randbelow(10**9):09d}" for _ in range(2)]
        for siren in sirens:
            with self.engine.connect() as connection:
                require(
                    connection.scalar(
                        sa.select(sa.func.count())
                        .select_from(supplier_directory)
                        .where(supplier_directory.c.siren == siren)
                    )
                    == 0,
                    "synthetic_identity_collision",
                )
            SupplierDirectoryStore(self.engine).upsert_identity(
                siren=siren,
                legal_name="Isolated rollback fixture",
                naf_code=None,
                family_key="",
                department=None,
                city=None,
                employees=None,
                observed_at=dt.datetime.now(dt.UTC),
            )
        identity = self.request(
            "POST",
            "/auth/signup",
            {
                "email": f"rollback-{secrets.token_hex(12)}@example.com",
                "password": secrets.token_urlsafe(32),
                "company_name": "Isolated rollback fixture",
                "locale": "fr",
            },
            expected=201,
            authenticated=False,
        )
        self.owner = identity["account_id"]
        self.company_path = f"/companies/cmp_directory_{sirens[0]}"
        self.long_company_path = f"/companies/cmp_directory_{sirens[1]}"
        self.long_directory_path = f"/companies/directory/{sirens[1]}"
        self.note_path = self.company_path + "/note"
        self.request("PUT", self.note_path, {"body": "x" * 2000, "expected_revision": 0})
        self.request("PUT", self.note_path, {"body": "", "expected_revision": 1})
        self.request(
            "PUT", self.long_company_path + "/note", {"body": "x" * 2000, "expected_revision": 0}
        )
        contact = self.company_path + "/manual-contact"
        self.request(
            "PUT",
            contact,
            {"name": "Synthetic contact", "email": "rollback@example.com", "expected_revision": 0},
        )
        self.request("DELETE", contact, if_match=1)
        self.snapshot = self.private_digest()
        self.candidate_read()

    def private_digest(self):
        metadata = sa.MetaData()
        state = {}
        with self.engine.connect() as connection:
            for name in BUSINESS_TABLES:
                table = sa.Table(name, metadata, autoload_with=connection)
                state[name] = [
                    dict(row)
                    for row in connection.execute(
                        sa.select(table)
                        .where(table.c.account_id == self.owner)
                        .order_by(*table.primary_key)
                    ).mappings()
                ]
        return hashlib.sha256(self.helper["canonical_bytes"](state)).digest()

    def set_guard(self, closed):
        name = "kivou-prospecting-maintenance.conf" if closed else "kivou-prospecting-open.conf"
        content = (self.args.candidate_root / "ops/nginx" / name).read_bytes()
        (self.directory / "mode.conf").write_bytes(content)
        self.start_proxy()
        self.request(
            "PUT",
            "/companies/rollback-probe/note",
            {"body": ""},
            expected=503 if closed else 401,
            authenticated=False,
            json_result=False,
        )
        self.closed = closed
        if closed:
            self.report["guard_sha256"] = hashlib.sha256(content).hexdigest()

    def close_guard(self):
        self.set_guard(True)

    def open_guard(self):
        self.set_guard(False)

    def blocked_writes(self):
        require(self.closed, "guard_not_closed")
        for method, path in (
            ("PUT", self.note_path),
            ("DELETE", self.company_path + "/manual-contact"),
            ("POST", self.company_path + "/directory-enrichment"),
            ("POST", self.company_path + "/contact-lookup"),
            ("PUT", "/signals/rollback-probe/status"),
            ("PUT", "/signals/rollback-probe/note"),
            ("POST", "/target-icps"),
            ("PATCH", "/target-icps/rollback-probe"),
        ):
            self.request(method, path, {}, expected=503, json_result=False)
        self.report["v11_writes_blocked"] = True

    def legacy_start(self):
        self.start_backend(self.args.legacy_root, self.args.legacy_sha)
        self.readiness()

    def legacy_read(self):
        require(self.request("GET", "/me")["account_id"] == self.owner, "legacy_auth_mismatch")
        require(bool(self.request("GET", "/billing/status")), "legacy_billing_read_failed")
        require(
            self.request("GET", self.long_directory_path)["note"] == "x" * 2000,
            "legacy_long_note_read_failed",
        )
        self.report["legacy_authenticated_reads"] = True
        self.report["legacy_note_2000_read"] = True

    def snapshot_check(self):
        require(
            secrets.compare_digest(self.private_digest(), self.snapshot), "private_state_changed"
        )
        self.helper["compare_baseline"](self.engine, self.baseline)
        self.report["private_state_preserved"] = True

    def candidate_return(self):
        self.start_backend(self.args.candidate_root, self.args.candidate_sha)
        self.readiness()

    def candidate_read(self):
        note = self.request("GET", self.company_path)
        require(
            note.get("note") is None and note["note_revision"] == 2, "candidate_tombstone_mismatch"
        )
        contact = self.request("GET", self.company_path + "/manual-contact")
        require(
            contact["contact"] is None and contact["revision"] == 2,
            "candidate_contact_tombstone_mismatch",
        )
        self.snapshot_check()

    def candidate_write(self):
        self.request("PUT", self.note_path, {"body": "old writer"}, expected=409)
        self.request("PUT", self.note_path, {"body": "stale", "expected_revision": 1}, expected=409)
        self.snapshot_check()
        note = self.request("PUT", self.note_path, {"body": "Resumed", "expected_revision": 2})
        require(note["revision"] == 3 and note["note"] == "Resumed", "candidate_write_failed")
        self.report["candidate_cas_writes_resumed"] = True

    def baseline_check(self):
        self.helper["compare_baseline"](self.engine, self.baseline)
        self.report["baseline_rows"] = sum(table["row_count"] for table in self.baseline.values())

    def cleanup(self):
        failures = []
        for process in (self.proxy_process, self.api_process):
            try:
                stop_child(process)
            except Exception:  # noqa: BLE001 - attempt every owned child before reporting failure
                failures.append("child")
        if self.engine is not None:
            self.engine.dispose()
        if self.baseline is not None:
            self.baseline.close()
        if self.directory is not None:
            # This exact directory was created by this instance, not operator input.
            for name in ("api.sock", "nginx.pid", "nginx.conf", "mode.conf"):
                path = self.directory / name
                if path.exists() or path.is_symlink():
                    path.unlink()
            for name in ("body", "proxy", "fastcgi", "uwsgi", "scgi"):
                path = self.directory / name
                if path.exists():
                    path.rmdir()
            self.directory.rmdir()
        require(not failures, "child_cleanup_failed")
        self.report["owned_runtime_removed"] = True


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source-environment", choices=("STAGING", "PRODUCTION"), required=True)
    for name in ("candidate-root", "legacy-root", "report", "code-root", "socket"):
        parser.add_argument("--" + name, type=Path)
    for name in ("candidate-sha", "legacy-sha", "code-sha", "schema-head"):
        parser.add_argument("--" + name)
    parser.add_argument("--nginx", default=shutil.which("nginx") or "/usr/sbin/nginx")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args(argv)
    report = {
        "status": "failed",
        "copy_only": True,
        "live_links_touched": False,
        "provider_calls": 0,
    }
    valid_report = False
    for key in tuple(os.environ):
        if key.startswith("PG"):
            del os.environ[key]
    try:
        with (
            open(os.devnull, "w") as quiet,
            contextlib.redirect_stdout(quiet),
            contextlib.redirect_stderr(quiet),
        ):
            if args.serve:
                require(not args.execute, "mode_conflict")
                serve(args)
                return 0
            require(args.execute and args.report is not None, "explicit_execution_required")
            private_directory(args.report.parent)
            valid_report = True
            _, sha, _ = validate_environment(os.environ)
            require(args.candidate_sha == sha, "candidate_environment_mismatch")
            verify_codebase(args.candidate_root, args.candidate_sha)
            verify_codebase(args.legacy_root, args.legacy_sha)
            require(
                args.candidate_root != args.legacy_root and args.candidate_sha != args.legacy_sha,
                "distinct_artifacts_required",
            )
            require(
                Path(args.nginx).is_file() and os.access(args.nginx, os.X_OK), "nginx_unavailable"
            )
            report.update(
                candidate_sha=sha,
                legacy_sha=args.legacy_sha,
                source_environment=args.source_environment,
            )
            with deadline():
                run_sequence(Runtime(args, os.environ, report))
            report["status"] = "passed"
    except Exception as error:  # noqa: BLE001 - private SQL and credentials never cross stdout
        report.update(failure_report(error))
    if valid_report:
        try:
            persist_report(args.report, report)
        except Exception:  # noqa: BLE001 - even report I/O failures have a closed public reason
            report.update(status="failed", code="report_persistence_failed")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


def main(argv=None):
    previous_umask = os.umask(0o077)
    try:
        return _main(argv)
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
