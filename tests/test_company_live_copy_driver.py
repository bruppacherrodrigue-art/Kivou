from __future__ import annotations

import json
import runpy
import signal
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / (
    "docs/reports/prospecting-v11/company-live-copy-driver.py"
)
SHA = "a" * 40
SOURCE_SHA = "b" * 40
NAME = f"kivou_v11_rehearsal_{SHA[:12]}_0123456789abcdef"
SOURCE = "postgresql+psycopg://owner:p%40ss%3Aword@127.0.0.1:5432/kivou_staging"
ADMIN = "postgresql://admin:admin-secret@127.0.0.1:5432/postgres"
MAIL_HEAD = "0059_prospect_mail_word_limit_v2"


def driver():
    assert SCRIPT.is_file(), "versioned copy driver must exist"
    return SimpleNamespace(**runpy.run_path(str(SCRIPT)))


@pytest.mark.parametrize(
    "url",
    [
        SOURCE.replace("127.0.0.1", "localhost"),
        SOURCE.replace("127.0.0.1", "192.0.2.1"),
        SOURCE.replace(":5432", ":5433"),
        SOURCE.replace("kivou_staging", "kivou"),
        SOURCE + "?hostaddr=192.0.2.1",
        SOURCE + "?dbname=kivou",
        SOURCE + "?sslmode=disable",
        "dbname=kivou host=127.0.0.1",
    ],
)
def test_source_url_requires_literal_endpoint_database_and_no_query(url):
    module = driver()
    with pytest.raises(module.DriverFailure):
        module.parse_url(url, "kivou_staging")


@pytest.mark.parametrize("url,database", [(SOURCE, "kivou_staging"), (ADMIN, "postgres")])
@pytest.mark.parametrize("omit_port", [False, True])
def test_default_postgresql_port_is_normalized_to_explicit_5432(url, database, omit_port):
    module = driver()
    parsed = module.parse_url(url.replace(":5432", "") if omit_port else url, database)
    assert parsed.port == 5432
    assert parsed.host == "127.0.0.1" and parsed.database == database
    assert ":5432/" in parsed.render_as_string(hide_password=False)
    assert module.pg_environment(parsed)["PGPORT"] == "5432"


def test_source_and_admin_passwords_are_decoded_only_in_minimal_pg_environment(monkeypatch):
    module = driver()
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    monkeypatch.setenv("PGSERVICE", "production")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "never-forward")
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward")
    source = module.parse_url(SOURCE, "kivou_staging")
    environment = module.pg_environment(source)
    assert environment["PGPASSWORD"] == "p@ss:word"
    assert environment["PGHOST"] == "127.0.0.1"
    assert environment["PGPORT"] == "5432"
    assert environment["PGDATABASE"] == "kivou_staging"
    assert (
        not {"PGHOSTADDR", "PGSERVICE", "STRIPE_SECRET_KEY", "OPENAI_API_KEY"} & environment.keys()
    )


def test_checker_receives_only_copy_configuration_without_any_provider_or_admin(monkeypatch):
    module = driver()
    monkeypatch.setenv("KIVOU_DATABASE_URL", SOURCE)
    monkeypatch.setenv("KIVOU_MIGRATION_ADMIN_URL", ADMIN)
    monkeypatch.setenv("APOLLO_API_KEY", "never-forward")
    monkeypatch.setenv("PGOPTIONS", "bad-option")
    environment = module.checker_environment(module.parse_url(ADMIN, "postgres"), NAME, SHA)
    assert environment["KIVOU_DATABASE_URL"] == environment["KIVOU_V11_REHEARSAL_DATABASE_URL"]
    assert environment["KIVOU_DATABASE_URL"].endswith("/" + NAME)
    assert environment["KIVOU_V11_REHEARSAL_DATABASE_NAME"] == NAME
    assert environment["KIVOU_V11_CANDIDATE_SHA"] == SHA
    assert {key for key in environment if key.startswith("KIVOU_")} == {
        "KIVOU_DATABASE_URL",
        "KIVOU_V11_REHEARSAL_DATABASE_URL",
        "KIVOU_V11_REHEARSAL_DATABASE_NAME",
        "KIVOU_V11_CANDIDATE_SHA",
    }
    assert not any(key.startswith("PG") for key in environment)
    assert "APOLLO_API_KEY" not in environment


def test_evidence_is_private_atomic_and_never_follows_existing_report_link(tmp_path):
    module = driver()
    tmp_path.chmod(0o700)
    outside = tmp_path.parent / "copy-driver-outside.txt"
    outside.write_text("unchanged")
    (tmp_path / "report.json").symlink_to(outside)
    module.persist_report(tmp_path, {"status": "running"})
    assert outside.read_text() == "unchanged"
    assert not (tmp_path / "report.json").is_symlink()
    assert stat.S_IMODE((tmp_path / "report.json").stat().st_mode) == 0o600
    assert json.loads((tmp_path / "report.json").read_text()) == {"status": "running"}
    assert list(tmp_path.glob("*.tmp")) == []
    tmp_path.chmod(0o755)
    with pytest.raises(module.DriverFailure, match="private_evidence_required"):
        module.persist_report(tmp_path, {})


def test_disk_space_checks_both_backup_and_postgres_volume(monkeypatch):
    module = driver()
    observed = []

    def usage(path):
        observed.append(str(path))
        return SimpleNamespace(free=10 * 1024**3 if str(path) == "/var/tmp" else 1)

    monkeypatch.setattr(module.shutil, "disk_usage", usage)
    with pytest.raises(module.DriverFailure, match="insufficient_disposable_restore_space"):
        module.check_space(1024)
    assert observed == ["/var/tmp", "/var/lib/postgresql"]


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Database:
    def __init__(self, database="postgres", head="0060_boamp_notice_facts"):
        self.database, self.head = database, head
        self.oid = None
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, parameters=None):
        text = statement if isinstance(statement, str) else statement.as_string()
        self.commands.append((text, parameters))
        if text == "SELECT current_database()":
            return Result([(self.database,)])
        if text == "SELECT version_num FROM alembic_version":
            return Result([(self.head,)])
        if text == "SELECT pg_database_size(current_database())":
            return Result([(4096,)])
        if text.startswith("SELECT oid FROM pg_database"):
            return Result([] if self.oid is None else [(self.oid,)])
        if text.startswith("CREATE DATABASE"):
            self.oid = 731
        if text.startswith("DROP DATABASE"):
            self.oid = None
        return Result([])


def patch_global(monkeypatch, module, name, value):
    module.main.__globals__[name]  # require the real orchestration boundary to exist
    monkeypatch.setitem(module.main.__globals__, name, value)


def test_source_inspection_is_explicitly_read_only_and_verifies_actual_database(monkeypatch):
    module = driver()
    database = Database("kivou_staging")
    patch_global(monkeypatch, module, "connect", lambda _url: database)
    actual = module.inspect_source(
        module.parse_url(SOURCE, "kivou_staging"), "0060_boamp_notice_facts"
    )
    assert actual == 4096
    assert database.commands[0][0] == "BEGIN READ ONLY"
    assert database.commands[-1][0] == "ROLLBACK"
    assert not any("CREATE" in text or "UPDATE" in text for text, _ in database.commands)
    database.database = "kivou"
    with pytest.raises(module.DriverFailure, match="connected_source_mismatch"):
        module.inspect_source(module.parse_url(SOURCE, "kivou_staging"), "0060_boamp_notice_facts")


def test_oid_cleanup_refuses_a_replaced_database_and_does_not_drop(monkeypatch):
    module = driver()
    database = Database()
    database.oid = 732
    patch_global(monkeypatch, module, "connect", lambda _url: database)
    with pytest.raises(module.DriverFailure, match="disposable_oid_changed_cleanup_refused"):
        module.drop_owned(module.parse_url(ADMIN, "postgres"), NAME, 731, SHA)
    assert not any(text.startswith("DROP") for text, _ in database.commands)


@pytest.mark.parametrize(
    "name", ["kivou", "postgres", "kivou_staging", NAME.replace("aaaa", "bbbb", 1)]
)
def test_cleanup_name_is_validated_before_connection(name, monkeypatch):
    module = driver()
    patch_global(monkeypatch, module, "connect", lambda _url: pytest.fail("must not connect"))
    with pytest.raises(module.DriverFailure, match="disposable_name_invalid"):
        module.drop_owned(module.parse_url(ADMIN, "postgres"), name, 731, SHA)


def test_orphaned_owned_group_is_reaped_and_reported_without_signalling_other_groups(monkeypatch):
    module = driver()
    calls = []
    active = True

    def killpg(group, sig):
        nonlocal active
        assert group == 12345
        calls.append(sig)
        if not active:
            raise ProcessLookupError
        if sig == signal.SIGTERM:
            active = False

    monkeypatch.setattr(module.os, "killpg", killpg)
    assert module.reap_group(12345) is True
    assert signal.SIGTERM in calls and signal.SIGKILL not in calls


def test_main_invalid_config_is_closed_without_subprocess_or_database(monkeypatch, capsys):
    module = driver()
    monkeypatch.setenv("KIVOU_DATABASE_URL", "SECRET-BAD-URL")
    monkeypatch.setenv("KIVOU_MIGRATION_ADMIN_URL", ADMIN)
    patch_global(monkeypatch, module, "connect", lambda _url: pytest.fail("must not connect"))
    result = module.main(
        [
            "--environment",
            "STAGING",
            "--sha",
            SHA,
            "--source-sha",
            SOURCE_SHA,
            "--source-root",
            f"/srv/kivou/releases/staging-{SOURCE_SHA}",
            "--candidate-root",
            "/does-not-exist",
        ]
    )
    assert result == 2
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "failed"
    assert "SECRET" not in output.out and output.err == ""


def flow(monkeypatch, tmp_path, *, failure=None, keep=False, environment="STAGING", head=None):
    module = driver()
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    database = Database()
    source_name, default_head = module.SOURCES[environment]
    source = module.parse_url(SOURCE.replace("kivou_staging", source_name), source_name)
    admin = module.parse_url(ADMIN, "postgres")
    config = SimpleNamespace(
        environment=environment,
        sha=SHA,
        source_sha=SOURCE_SHA,
        candidate=Path("/candidate"),
        source=source,
        admin=admin,
        head=head or default_head,
        keep_copy=keep,
    )
    report = {"status": "running", "copy_database": NAME}
    calls = []
    patch_global(monkeypatch, module, "connect", lambda _url: database)

    def run_child(argv, *, env, evidence, timeout, capture=False):
        kind = (
            "backup"
            if str(argv[0]).endswith("kivou-backup.sh")
            else ("restore" if argv[0] == "pg_restore" else "checker")
        )
        calls.append((kind, argv, env))
        assert "p@ss:word" not in " ".join(map(str, argv))
        if kind == "backup":
            assert env["PGPASSWORD"] == "p@ss:word"
            assert "p%40ss" not in env["KIVOU_DATABASE_URL"]
            assert env["KIVOU_BACKUP_DIR"] == str(evidence)
            dump = evidence / "kivou-20260914T010203Z.dump"
            dump.write_bytes(b"PGDMP" + b"X" * 5000)
            dump.chmod(0o600)
        if failure == kind:
            raise module.DriverFailure("child_failed")
        if failure == "orphan" and kind == "restore":
            raise module.ChildCleanupFailure("child_group_cleanup_unconfirmed")
        if kind == "checker":
            assert env["KIVOU_DATABASE_URL"].endswith("/" + NAME)
            assert not any(key.startswith("PG") for key in env)
            assert "KIVOU_MIGRATION_ADMIN_URL" not in env
            assert "--source-sha" in argv and SOURCE_SHA in argv
            return json.dumps(
                {
                    "status": "passed",
                    "sha": SHA,
                    "source_sha": SOURCE_SHA,
                    "source_environment": config.environment,
                    "restored_head": config.head,
                    "candidate_head": "0063_catalogue_mirror",
                    "legacy_preserved": True,
                    "replay_preserved": True,
                    "baseline_tables": 31,
                    "baseline_rows": 250001,
                    "legacy_accounts_exported": 2,
                    "shared_baseline_rows": {"supplier_directory": 876},
                }
            )
        return ""

    patch_global(monkeypatch, module, "run_child", run_child)
    patch_global(monkeypatch, module, "assert_source_unchanged", lambda _config: None)
    return module, config, evidence, database, report, calls


def test_explicit_production_mail_head_reaches_copy_checker_and_aggregate(monkeypatch, tmp_path):
    module, config, evidence, _database, report, calls = flow(
        monkeypatch, tmp_path, environment="PRODUCTION", head=MAIL_HEAD
    )
    module.perform_copy(config, NAME, evidence, report)
    checker_call = next(call for call in calls if call[0] == "checker")
    argv = checker_call[1]
    assert argv[argv.index("--expected-deployed-head") + 1] == MAIL_HEAD
    assert argv[argv.index("--source-environment") + 1] == "PRODUCTION"
    assert report["checks"]["restored_head"] == MAIL_HEAD
    assert report["checks"]["source_sha"] == SOURCE_SHA
    assert report["cleanup_status"] == "dropped"


@pytest.mark.parametrize("failure", [None, "restore", "checker"])
def test_flow_retains_verified_dump_and_drops_only_owned_copy_even_after_failure(
    monkeypatch, tmp_path, failure
):
    module, config, evidence, database, report, calls = flow(monkeypatch, tmp_path, failure=failure)
    if failure:
        with pytest.raises(module.DriverFailure, match="child_failed"):
            module.perform_copy(config, NAME, evidence, report)
    else:
        module.perform_copy(config, NAME, evidence, report)
    assert report["cleanup_status"] == "dropped"
    assert database.oid is None
    assert report["backup_retained"] is True
    assert report["backup_sha256"] and report["backup_bytes"] == 5005
    assert len(list(evidence.glob("*.dump"))) == 1
    assert calls[0][0] == "backup"
    assert any(text.startswith("DROP DATABASE") for text, _ in database.commands)


@pytest.mark.parametrize("failure", [None, "restore"])
def test_keep_copy_retains_exact_owned_oid_on_success_or_failure(monkeypatch, tmp_path, failure):
    module, config, evidence, database, report, _ = flow(
        monkeypatch, tmp_path, failure=failure, keep=True
    )
    if failure:
        with pytest.raises(module.DriverFailure):
            module.perform_copy(config, NAME, evidence, report)
    else:
        module.perform_copy(config, NAME, evidence, report)
    assert report["cleanup_status"] == "retained_intentionally"
    assert report["copy_oid"] == database.oid == 731
    assert not any(text.startswith("DROP") for text, _ in database.commands)
    assert len(list(evidence.glob("*.dump"))) == 1


def test_existing_database_is_never_adopted_or_dropped(monkeypatch, tmp_path):
    module, config, evidence, database, report, calls = flow(monkeypatch, tmp_path)
    database.oid = 912
    with pytest.raises(module.DriverFailure, match="disposable_already_exists"):
        module.perform_copy(config, NAME, evidence, report)
    assert report["cleanup_status"] == "not_created"
    assert database.oid == 912
    assert not any(text.startswith(("CREATE", "DROP")) for text, _ in database.commands)
    assert [call[0] for call in calls] == ["backup"]
    assert len(list(evidence.glob("*.dump"))) == 1


def test_unconfirmed_child_group_cleanup_refuses_drop_and_retains_evidence(monkeypatch, tmp_path):
    module, config, evidence, database, report, _ = flow(monkeypatch, tmp_path, failure="orphan")
    with pytest.raises(module.ChildCleanupFailure):
        module.perform_copy(config, NAME, evidence, report)
    assert report["cleanup_status"] == "cleanup_refused"
    assert database.oid == 731
    assert not any(text.startswith("DROP") for text, _ in database.commands)
    assert len(list(evidence.glob("*.dump"))) == 1


def test_report_io_failure_does_not_prevent_oid_checked_cleanup(monkeypatch, tmp_path):
    module, config, evidence, database, report, _ = flow(monkeypatch, tmp_path)

    def persist(_evidence, actual):
        if actual.get("copy_created"):
            raise OSError("private-path-not-for-output")

    patch_global(monkeypatch, module, "persist_report", persist)
    with pytest.raises(OSError):
        module.perform_copy(config, NAME, evidence, report)
    assert report["cleanup_status"] == "dropped"
    assert database.oid is None
    assert len(list(evidence.glob("*.dump"))) == 1


def test_child_timeout_reaps_only_the_owned_group_before_returning(monkeypatch, tmp_path):
    module = driver()
    observed = []

    class Child:
        pid = 42341
        returncode = None

        def wait(self, timeout):
            observed.append(("wait", timeout))
            if self.returncode is None:
                raise subprocess.TimeoutExpired("not-logged", timeout)
            return self.returncode

        def poll(self):
            return self.returncode

    child = Child()

    def launch(argv, **kwargs):
        assert kwargs["start_new_session"] is True
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        return child

    def reap(group, **_kwargs):
        assert group == child.pid
        observed.append(("reaped", group))
        child.returncode = -15
        return True

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    patch_global(monkeypatch, module, "reap_group", reap)
    with pytest.raises(module.DriverFailure, match="child_timeout"):
        module.run_child(
            ["test-child"], env={"PATH": "/usr/bin:/bin"}, evidence=tmp_path, timeout=2
        )
    assert observed == [("wait", 2), ("reaped", 42341), ("wait", 1)]


def test_successful_leader_with_orphan_cannot_pass(monkeypatch, tmp_path):
    module = driver()
    child = SimpleNamespace(pid=42341, returncode=0, wait=lambda **_kwargs: 0, poll=lambda: 0)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: child)
    patch_global(monkeypatch, module, "reap_group", lambda _group, **_kwargs: True)
    with pytest.raises(module.DriverFailure, match="child_orphan_group"):
        module.run_child(["test-child"], env={}, evidence=tmp_path, timeout=2)


@pytest.mark.parametrize(
    "environment,selected,expected",
    [
        ("STAGING", None, "0060_boamp_notice_facts"),
        ("PRODUCTION", None, "0058_model_call_budget"),
        ("STAGING", "0060_boamp_notice_facts", "0060_boamp_notice_facts"),
        ("PRODUCTION", "0058_model_call_budget", "0058_model_call_budget"),
        ("PRODUCTION", MAIL_HEAD, MAIL_HEAD),
    ],
)
def test_preflight_default_never_creates_evidence_or_runs_copy(
    monkeypatch, capsys, environment, selected, expected
):
    module = driver()
    source = SOURCE if environment == "STAGING" else SOURCE.replace("kivou_staging", "kivou")
    monkeypatch.setenv("KIVOU_DATABASE_URL", source)
    monkeypatch.setenv("KIVOU_MIGRATION_ADMIN_URL", ADMIN)

    def preflight(config):
        assert config.head == expected
        assert config.environment == environment
        assert config.source_sha == SOURCE_SHA
        assert config.source_root == Path(f"/srv/kivou/releases/staging-{SOURCE_SHA}")
        return {"source_database_bytes": 4096}

    patch_global(monkeypatch, module, "preflight", preflight)
    patch_global(monkeypatch, module, "perform_copy", lambda *_args: pytest.fail("must not mutate"))
    monkeypatch.setattr(
        module.tempfile, "mkdtemp", lambda **_kwargs: pytest.fail("must not create evidence")
    )
    assert (
        module.main(
            [
                "--environment",
                environment,
                "--sha",
                SHA,
                "--source-sha",
                SOURCE_SHA,
                "--source-root",
                f"/srv/kivou/releases/staging-{SOURCE_SHA}",
                "--candidate-root",
                "/candidate",
                *(["--expected-source-head", selected] if selected is not None else []),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "preflight_passed"
    assert report["source_head"] == expected


@pytest.mark.parametrize(
    "environment,head",
    [
        ("STAGING", MAIL_HEAD),
        ("STAGING", "0058_model_call_budget"),
        ("PRODUCTION", "0060_boamp_notice_facts"),
        ("PRODUCTION", "head"),
        ("PRODUCTION", ""),
    ],
)
def test_source_head_selector_rejects_wrong_environment_before_any_probe(
    monkeypatch, capsys, environment, head
):
    module = driver()
    patch_global(monkeypatch, module, "preflight", lambda _config: pytest.fail("must not probe"))
    patch_global(monkeypatch, module, "connect", lambda _url: pytest.fail("must not connect"))
    assert (
        module.main(
            [
                "--environment",
                environment,
                "--sha",
                SHA,
                "--source-sha",
                SOURCE_SHA,
                "--source-root",
                f"/srv/kivou/releases/production-{SOURCE_SHA}",
                "--candidate-root",
                "/candidate",
                "--expected-source-head",
                head,
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "status": "failed",
        "code": "source_environment_head_mismatch",
    }
    assert output.err == ""


def test_actual_new_source_head_requires_explicit_selection_not_the_old_default(monkeypatch):
    module = driver()
    database = Database("kivou", head=MAIL_HEAD)
    patch_global(monkeypatch, module, "connect", lambda _url: database)
    source = module.parse_url(SOURCE.replace("kivou_staging", "kivou"), "kivou")
    with pytest.raises(module.DriverFailure, match="source_head_mismatch"):
        module.inspect_source(source, module.SOURCES["PRODUCTION"][1])
    assert module.inspect_source(source, MAIL_HEAD) == 4096
    assert all(not text.startswith(("CREATE", "DROP", "UPDATE")) for text, _ in database.commands)


def test_group_cleanup_reaps_terminated_leader_while_waiting_for_disappearance(
    monkeypatch, tmp_path
):
    module = driver()
    terminated = False
    collected = False
    clock = 0

    class Child:
        pid = 42342
        returncode = None

        def wait(self, timeout):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("owned-child", timeout)
            return self.returncode

        def poll(self):
            nonlocal collected
            if terminated:
                collected = True
                self.returncode = -15
            return self.returncode

    child = Child()

    def killpg(group, sig):
        nonlocal terminated
        assert group == child.pid
        if collected:
            raise ProcessLookupError
        if sig in (signal.SIGTERM, signal.SIGKILL):
            terminated = True

    def advance(delay):
        nonlocal clock
        clock += delay

    monkeypatch.setattr(module.os, "killpg", killpg)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: child)
    patch_global(monkeypatch, module, "monotonic", lambda: clock)
    patch_global(monkeypatch, module, "sleep", advance)
    with pytest.raises(module.DriverFailure, match="^child_timeout$"):
        module.run_child(["owned-child"], env={}, evidence=tmp_path, timeout=2)
    assert collected is True
    assert clock <= 5


def test_keep_copy_also_refuses_replaced_oid(monkeypatch, tmp_path):
    module, config, evidence, database, report, _ = flow(monkeypatch, tmp_path, keep=True)
    original = module.main.__globals__["run_child"]

    def replace_oid(argv, **kwargs):
        result = original(argv, **kwargs)
        if str(argv[0]).endswith(".venv/bin/python"):
            database.oid = 732
        return result

    patch_global(monkeypatch, module, "run_child", replace_oid)
    with pytest.raises(module.DriverFailure, match="disposable_oid_changed_cleanup_refused"):
        module.perform_copy(config, NAME, evidence, report)
    assert report["cleanup_status"] == "cleanup_refused"
    assert not any(text.startswith("DROP") for text, _ in database.commands)


def test_backup_file_is_rejected_if_symlink_or_nonprivate(tmp_path):
    module = driver()
    destination = tmp_path / "target"
    destination.write_bytes(b"X" * 5000)
    path = tmp_path / "kivou-test.dump"
    path.symlink_to(destination)
    with pytest.raises(module.DriverFailure, match="invalid_private_dump"):
        module.accepted_dump(tmp_path)
    path.unlink()
    path.write_bytes(b"X" * 5000)
    path.chmod(0o644)
    with pytest.raises(module.DriverFailure, match="invalid_private_dump"):
        module.accepted_dump(tmp_path)


def test_artifact_requires_exact_sha_clean_tracked_candidate_helpers(monkeypatch, tmp_path):
    module = driver()
    calls = []

    def git(root, *args):
        assert root == tmp_path
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return SHA
        if args == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        return ""

    patch_global(monkeypatch, module, "git", git)
    monkeypatch.setattr(module.os, "access", lambda *_args: True)
    checker = tmp_path / module.CHECKER
    checker.parent.mkdir(parents=True)
    checker.write_text("# owned test fixture")
    module.verify_artifact(tmp_path, SHA, checker=True)
    assert ("diff", "--quiet", "HEAD", "--") in calls
    assert any(
        args[:2] == ("ls-files", "--error-unmatch") and module.BACKUP in args for args in calls
    )
    with pytest.raises(module.DriverFailure, match="artifact_sha_mismatch"):
        module.verify_artifact(tmp_path, SOURCE_SHA, checker=True)


def test_bad_checker_json_is_not_forwarded_and_own_copy_is_still_dropped(monkeypatch, tmp_path):
    module, config, evidence, database, report, _ = flow(monkeypatch, tmp_path)
    original = module.main.__globals__["run_child"]

    def bad_json(argv, **kwargs):
        result = original(argv, **kwargs)
        return "PRIVATE-ERROR" if str(argv[0]).endswith(".venv/bin/python") else result

    patch_global(monkeypatch, module, "run_child", bad_json)
    with pytest.raises(module.DriverFailure, match="candidate_report_invalid"):
        module.perform_copy(config, NAME, evidence, report)
    assert report["cleanup_status"] == "dropped" and database.oid is None
    assert "PRIVATE-ERROR" not in json.dumps(report)


def test_any_error_during_group_cleanup_becomes_drop_refusal(monkeypatch, tmp_path):
    module = driver()
    child = SimpleNamespace(pid=42341, returncode=0, wait=lambda **_kwargs: 0, poll=lambda: 0)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: child)

    def forbidden(_group, **_kwargs):
        raise PermissionError("private-system-details")

    patch_global(monkeypatch, module, "reap_group", forbidden)
    with pytest.raises(module.ChildCleanupFailure, match="child_group_cleanup_unconfirmed"):
        module.run_child(["owned-child"], env={}, evidence=tmp_path, timeout=2)


def test_group_cleanup_kills_unresponsive_owned_descendants_with_bounded_grace(monkeypatch):
    module = driver()
    clock, gone = 0, False
    signals = []

    def killpg(group, sig):
        nonlocal gone
        assert group == 42341
        if gone:
            raise ProcessLookupError
        signals.append(sig)
        if sig == signal.SIGKILL:
            gone = True

    def advance(delay):
        nonlocal clock
        clock += delay

    monkeypatch.setattr(module.os, "killpg", killpg)
    patch_global(monkeypatch, module, "monotonic", lambda: clock)
    patch_global(monkeypatch, module, "sleep", advance)
    assert module.reap_group(42341) is True
    assert signal.SIGTERM in signals and signal.SIGKILL in signals
    assert 5 <= clock <= 5.1


@pytest.mark.parametrize("exit_code", [0, 7])
def test_real_owned_child_closes_private_output_and_never_forwards_stderr(tmp_path, exit_code):
    module = driver()
    argv = [
        sys.executable,
        "-c",
        f"import sys; print('aggregate'); print('SECRET', file=sys.stderr); sys.exit({exit_code})",
    ]
    if exit_code:
        with pytest.raises(module.DriverFailure, match="^child_failed$"):
            module.run_child(
                argv, env=module.base_environment(), evidence=tmp_path, timeout=5, capture=True
            )
    else:
        assert (
            module.run_child(
                argv, env=module.base_environment(), evidence=tmp_path, timeout=5, capture=True
            )
            == "aggregate\n"
        )
    assert list(tmp_path.iterdir()) == []


def test_active_source_artifact_accepts_explicit_real_timestamped_production_path(monkeypatch):
    module = driver()
    actual_sha = "543793c7df22adfa1ff96a09d91df854ff9f1cfa"
    expected = Path("/srv/kivou/releases/production-20260914T081921Z-543793c7df22")
    config = SimpleNamespace(environment="PRODUCTION", source_sha=actual_sha, source_root=expected)
    observed = []
    original = Path.resolve

    def resolve(path, **kwargs):
        return expected if str(path) == "/srv/kivou/app" else original(path, **kwargs)

    monkeypatch.setattr(module.Path, "resolve", resolve)
    patch_global(
        monkeypatch, module, "verify_artifact", lambda path, sha: observed.append((path, sha))
    )
    module.source_artifact(config)
    assert observed == [(expected, actual_sha)]
    config.source_root = Path("/srv/kivou/releases/another-release")
    with pytest.raises(module.DriverFailure, match="active_source_artifact_mismatch"):
        module.source_artifact(config)


def test_artifact_rejects_git_toplevel_different_from_explicit_candidate(monkeypatch, tmp_path):
    module = driver()

    def git(_root, *args):
        return str(tmp_path.parent) if args == ("rev-parse", "--show-toplevel") else SHA

    patch_global(monkeypatch, module, "git", git)
    with pytest.raises(module.DriverFailure, match="artifact_git_root_mismatch"):
        module.verify_artifact(tmp_path, SHA)


def test_created_database_without_confirmed_oid_is_not_dropped(monkeypatch, tmp_path):
    module, config, evidence, database, report, _ = flow(monkeypatch, tmp_path)
    original = database.execute

    def missing_oid(statement, parameters=None):
        result = original(statement, parameters)
        if isinstance(statement, str) and statement.startswith("SELECT oid") and database.oid:
            return Result([])
        return result

    database.execute = missing_oid
    with pytest.raises(module.DriverFailure, match="created_oid_unconfirmed"):
        module.perform_copy(config, NAME, evidence, report)
    assert report["copy_created"] is True and report["cleanup_status"] == "cleanup_refused"
    assert not any(text.startswith("DROP") for text, _ in database.commands)
    assert len(list(evidence.glob("*.dump"))) == 1


def test_checker_report_ignores_untrusted_extra_keys_but_requires_boolean_proofs():
    module = driver()
    config = SimpleNamespace(
        sha=SHA, source_sha=SOURCE_SHA, environment="STAGING", head="0060_boamp_notice_facts"
    )
    value = {
        "status": "passed",
        "sha": SHA,
        "source_sha": SOURCE_SHA,
        "source_environment": "STAGING",
        "restored_head": config.head,
        "legacy_preserved": True,
        "replay_preserved": True,
        "candidate_head": "0063_catalogue_mirror",
        "baseline_rows": 1,
        "baseline_tables": 1,
        "legacy_accounts_exported": 0,
        "shared_baseline_rows": {},
        "private_debug": "SECRET",
    }
    assert "SECRET" not in json.dumps(module.checked_report(json.dumps(value), config))
    value["legacy_preserved"] = 1
    with pytest.raises(module.DriverFailure, match="candidate_checks_failed"):
        module.checked_report(json.dumps(value), config)
