"""Offline checks for an actual-artifact operator; never access a live database."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "docs/reports/prospecting-v11/company-live-rollback-rehearsal.py"
SHA = "a" * 40
LEGACY = "b" * 40
NAME = f"kivou_v11_rehearsal_{SHA[:12]}_1234567890abcdef"
URL = f"postgresql+psycopg://synthetic:private@localhost/{NAME}"


def load():
    assert PATH.is_file(), "versioned actual-artifact rollback checker is missing"
    spec = importlib.util.spec_from_file_location("company_rollback", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment():
    return {
        "KIVOU_V11_CANDIDATE_SHA": SHA,
        "KIVOU_V11_REHEARSAL_DATABASE_NAME": NAME,
        "KIVOU_V11_REHEARSAL_DATABASE_URL": URL,
        "KIVOU_DATABASE_URL": URL,
    }


def test_versioned_operator_exists():
    assert callable(load().main)


@pytest.mark.parametrize(
    "key,value",
    [
        ("KIVOU_DATABASE_URL", "postgresql://u@localhost/kivou"),
        ("KIVOU_V11_REHEARSAL_DATABASE_NAME", "kivou_staging"),
        ("KIVOU_V11_CANDIDATE_SHA", "abc"),
        ("KIVOU_V11_REHEARSAL_DATABASE_URL", URL + "?hostaddr=192.0.2.1"),
    ],
)
def test_copy_fence_rejects_unsafe_configuration(key, value):
    module = load()
    env = {**environment(), key: value}
    with pytest.raises(module.RollbackFailure):
        module.validate_environment(env)


def test_child_environment_retains_only_copy_configuration():
    module = load()
    child = module.child_environment(
        {**environment(), "PGHOST": "evil", "KIVOU_APOLLO_API_KEY": "private", "PYTHONPATH": "evil"}
    )
    assert child["KIVOU_DATABASE_URL"] == URL
    assert not any(key.startswith("PG") for key in child)
    assert "KIVOU_APOLLO_API_KEY" not in child and "PYTHONPATH" not in child


@pytest.mark.parametrize("failure", [None, "legacy_read", "snapshot_check", "candidate_write"])
def test_real_sequence_guards_switches_and_always_cleans_up(failure):
    module = load()
    calls = []

    class Runtime:
        def __getattr__(self, name):
            def invoke():
                calls.append(name)
                if name == failure:
                    raise RuntimeError("private")

            return invoke

    if failure:
        with pytest.raises(RuntimeError):
            module.run_sequence(Runtime())
    else:
        module.run_sequence(Runtime())
    assert calls[-1] == "cleanup"
    assert calls.index("close_guard") < calls.index("legacy_start")
    if "open_guard" in calls:
        assert calls.index("candidate_read", calls.index("candidate_return")) < calls.index(
            "open_guard"
        )
    if failure in {"legacy_read", "snapshot_check"}:
        assert "open_guard" not in calls


def test_private_report_and_closed_errors(tmp_path, monkeypatch):
    module = load()
    tmp_path.chmod(0o700)
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    report = tmp_path / "report.json"
    report.symlink_to(outside)
    fsync = module.os.fsync
    synced = []

    def sync(descriptor):
        synced.append(descriptor)
        fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", sync)
    module.persist_report(report, module.failure_report(ValueError("private SQL and password")))
    assert outside.read_text() == "unchanged"
    assert report.stat().st_mode & 0o777 == 0o600
    assert json.loads(report.read_text())["code"] == "rollback_execution_failed"
    assert "private" not in report.read_text()
    assert len(synced) == 2  # Both file contents and the atomic rename are durable.


def test_nginx_and_cleanup_are_scoped_to_owned_runtime(tmp_path, monkeypatch):
    module = load()
    config = module.nginx_config(tmp_path, 18123, "nonce")
    assert "listen 127.0.0.1:18123" in config
    assert f"unix:{tmp_path}/api.sock" in config
    assert f"include {tmp_path}/mode.conf;" in config
    assert "/srv/kivou/app" not in config and "access_log off" in config
    calls = []

    def kill(group, number):
        calls.append((group, number))
        if number == 0:
            raise ProcessLookupError

    monkeypatch.setattr(module.os, "killpg", kill)
    process = SimpleNamespace(
        pid=999999,
        rollback_pgid=999999,
        wait=lambda timeout: calls.append(timeout),
    )
    module.stop_child(process)
    assert calls == [(999999, module.signal.SIGTERM), 5, (999999, 0)]


def test_synthetic_contracts_round_trip_through_real_candidate_api(tmp_path):
    import datetime as dt

    from fastapi.testclient import TestClient

    from signals.api import ApiConfig, create_app
    from signals.persistence.database import create_database_engine, migrate_to_latest

    module = load()
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'copy.db'}")
    migrate_to_latest(engine)
    runtime = module.Runtime.__new__(module.Runtime)
    runtime.engine, runtime.report = engine, {}
    runtime.helper = module.load_helpers(ROOT)
    runtime.helper["exercise_private_contracts"](engine, now=dt.datetime.now(dt.UTC))
    app = create_app(engine, ApiConfig(cookie_secure=False, allowed_origin="http://127.0.0.1"))
    assert not app.dependency_overrides and app.state.stripe_gateway is None
    with runtime.helper["capture_baseline"](engine, temp_dir=tmp_path) as baseline:
        runtime.baseline = baseline
        with TestClient(app, base_url="http://127.0.0.1") as client:

            def request(method, path, body=None, *, expected=200, if_match=None, **_kwargs):
                headers = {"Origin": "http://127.0.0.1"}
                if if_match is not None:
                    headers["If-Match"] = str(if_match)
                response = client.request(method, path, json=body, headers=headers)
                assert response.status_code == expected, response.text
                return response.json()

            runtime.request = request
            runtime.prepare()
            runtime.legacy_read()
            runtime.candidate_read()
            runtime.candidate_write()
            runtime.baseline_check()
            assert runtime.report["private_state_preserved"]
            assert runtime.report["candidate_cas_writes_resumed"]
    engine.dispose()


def test_artifact_sha_and_physical_root_required_before_git(tmp_path, monkeypatch):
    module = load()
    monkeypatch.setattr(
        module.subprocess, "check_output", lambda *_a, **_kw: pytest.fail("git must not run")
    )
    with pytest.raises(module.RollbackFailure, match="artifact_sha_invalid"):
        module.verify_codebase(tmp_path, "main")
    link = tmp_path / "current"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(module.RollbackFailure, match="physical_artifact_required"):
        module.verify_codebase(link, SHA)


def test_helper_must_be_tracked_by_the_explicit_candidate(tmp_path, monkeypatch):
    module = load()
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(returncode=1))
    with pytest.raises(module.RollbackFailure, match="candidate_helper_not_tracked"):
        module.load_helpers(tmp_path)


def test_artifact_git_checks_never_inherit_git_redirects(tmp_path, monkeypatch):
    module = load()
    for relative in ("src/signals/api/app.py", ".venv/bin/python"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic")
    monkeypatch.setenv("GIT_DIR", "/private/wrong.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/private/wrong")
    checked = []

    def output(command, **kwargs):
        checked.append(kwargs["env"])
        return str(tmp_path) if "--show-toplevel" in command else SHA

    def run(_command, **kwargs):
        checked.append(kwargs["env"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "check_output", output)
    monkeypatch.setattr(module.subprocess, "run", run)
    module.verify_codebase(tmp_path, SHA)
    assert len(checked) >= 2
    assert all("GIT_DIR" not in env and "GIT_WORK_TREE" not in env for env in checked)
    assert all(env["GIT_CONFIG_GLOBAL"] == "/dev/null" for env in checked)


def test_cleanup_terminates_forked_descendant_after_leader_exits():
    import os
    import subprocess
    import sys

    module = load()
    process = module.start_child(
        [
            sys.executable,
            "-c",
            "import os,time; child=os.fork(); print(child,flush=True) if child else time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    child = int(process.stdout.readline())
    process.wait(timeout=5)
    try:
        os.kill(child, 0)
        module.stop_child(process)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        try:
            os.killpg(process.pid, 9)
        except ProcessLookupError:
            pass


def test_cleanup_accepts_group_exit_between_probe_and_signal(monkeypatch):
    module = load()
    calls = []

    def kill(_group, number):
        calls.append(number)
        if len(calls) == 3:
            raise ProcessLookupError

    monkeypatch.setattr(module.os, "killpg", kill)
    process = SimpleNamespace(pid=999999, rollback_pgid=999999, wait=lambda timeout: None)
    module.stop_child(process)
    assert len(calls) == 3


def test_deadline_restores_handlers_after_failure():
    import signal

    module = load()
    previous = signal.getsignal(signal.SIGALRM)
    with pytest.raises(RuntimeError), module.deadline():
        raise RuntimeError("synthetic")
    assert signal.getsignal(signal.SIGALRM) is previous
    assert signal.alarm(0) == 0


def test_live_target_cli_fails_before_engine_and_redacts_secrets(tmp_path, monkeypatch, capsys):
    module = load()
    tmp_path.chmod(0o700)
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("KIVOU_DATABASE_URL", "postgresql://secret:password@localhost/kivou")
    monkeypatch.setattr(
        module.sa, "create_engine", lambda *_a, **_kw: pytest.fail("must not connect")
    )
    assert (
        module.main(
            [
                "--execute",
                "--source-environment",
                "PRODUCTION",
                "--report",
                str(tmp_path / "report.json"),
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "copy_urls_differ" in output and "password" not in output and "postgresql" not in output


def test_report_io_failure_does_not_expose_private_traceback(tmp_path, monkeypatch, capsys):
    module = load()
    tmp_path.chmod(0o700)

    def fail(*_args):
        raise OSError("private path or credential")

    monkeypatch.setattr(module, "persist_report", fail)
    assert (
        module.main(
            [
                "--execute",
                "--source-environment",
                "STAGING",
                "--report",
                str(tmp_path / "report.json"),
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["code"] == "report_persistence_failed"
    assert "credential" not in output.out and output.err == ""


def test_real_nginx_blocks_writers_but_keeps_gets_then_reopens():
    import http.server
    import os
    import shutil
    import socket
    import socketserver
    import subprocess
    import tempfile
    import threading

    module = load()
    nginx = os.environ.get("KIVOU_TEST_NGINX") or shutil.which("nginx")
    if not nginx:
        pytest.skip("local nginx binary not provided")
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(("GET", self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def do_PUT(self):
            seen.append(("PUT", self.path))
            self.send_response(401)
            self.end_headers()

        def log_message(self, *_args):
            pass

    with tempfile.TemporaryDirectory(prefix="rollback-nginx-", dir="/tmp") as directory:
        runtime = module.Runtime.__new__(module.Runtime)
        runtime.directory, runtime.nonce = Path(directory), "test-nonce"
        runtime.args = SimpleNamespace(nginx=nginx, candidate_root=ROOT)
        runtime.environment, runtime.report = module.child_environment(environment()), {}
        runtime.api_process, runtime.proxy_process = SimpleNamespace(poll=lambda: None), None
        runtime.token = None
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            runtime.port = reserve.getsockname()[1]
        (runtime.directory / "nginx.conf").write_text(
            module.nginx_config(runtime.directory, runtime.port, runtime.nonce)
        )
        server = socketserver.UnixStreamServer(str(runtime.directory / "api.sock"), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            runtime.set_guard(True)
            runtime.request("GET", "/me")
            runtime.request("GET", "/billing/status")
            runtime.request("PUT", "/companies/test/note", {}, expected=503, json_result=False)
            assert all(method == "GET" for method, _ in seen)
            runtime.set_guard(False)
            runtime.request("PUT", "/companies/test/note", {}, expected=401, json_result=False)
        except subprocess.CalledProcessError as error:
            diagnostic = subprocess.run(error.cmd, check=False, capture_output=True, timeout=5)
            pytest.fail(diagnostic.stderr.decode())
        finally:
            module.stop_child(runtime.proxy_process)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
