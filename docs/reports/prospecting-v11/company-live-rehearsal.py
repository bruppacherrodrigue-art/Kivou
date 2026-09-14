"""Offline release checks on an operator-restored copy; never backup/CREATE/DROP.

Required copy environment matches rehearsal-checks.py:
KIVOU_V11_REHEARSAL_DATABASE_URL, KIVOU_DATABASE_URL (the same copy),
KIVOU_V11_REHEARSAL_DATABASE_NAME and KIVOU_V11_CANDIDATE_SHA.
Source identity/head are explicit operator evidence, never inferred from a URL.
No provider, HTTP client, BOAMP backfill or live database is invoked here.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from alembic.runtime.migration import MigrationContext

CHECKOUT = Path(__file__).resolve().parents[3]
checks = SimpleNamespace(**runpy.run_path(str(Path(__file__).with_name("rehearsal-checks.py"))))
SHARED_TABLES = (
    "supplier_directory",
    "model_daily_budget",
    "model_call_journal",
    "notice_source_snapshot",
    "notice_award_facts",
)
DEPLOYED_HEADS = {
    "STAGING": ("0060_boamp_notice_facts",),
    "PRODUCTION": ("0058_model_call_budget", "0059_prospect_mail_word_limit_v2"),
}


def validate_configuration(
    target, default, name, sha, source_environment, expected_head, source_sha
):
    target = checks.validate_target_config(target, default, name, sha)
    checks.require(
        source_environment in DEPLOYED_HEADS
        and expected_head in DEPLOYED_HEADS[source_environment],
        "source_environment_head_mismatch",
    )
    checks.require(bool(re.fullmatch(r"[0-9a-f]{40}", source_sha)), "source_sha_invalid")
    return target


def verify_checkout(sha):
    actual = subprocess.check_output(
        ["git", "-C", str(CHECKOUT), "rev-parse", "HEAD"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    checks.require(actual == sha, "candidate_checkout_sha_mismatch")
    checks.require(
        Path(checks.MIGRATIONS_PATH).resolve() == CHECKOUT / "src/signals/persistence/migrations",
        "candidate_import_path_mismatch",
    )
    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(CHECKOUT),
            "ls-files",
            "--error-unmatch",
            "--",
            "docs/reports/prospecting-v11/company-live-rehearsal.py",
            "docs/reports/prospecting-v11/rehearsal-checks.py",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    checks.require(tracked.returncode == 0, "candidate_checker_untracked")
    clean = subprocess.run(
        ["git", "-C", str(CHECKOUT), "diff", "--quiet", "HEAD", "--"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    checks.require(clean.returncode == 0, "candidate_checkout_dirty")


def run_checks(engine, *, source_environment, expected_deployed_head, now, temp_dir=None):
    """The CLI verifies the actual database before this local checking workflow."""
    checks.require(
        source_environment in DEPLOYED_HEADS
        and expected_deployed_head in DEPLOYED_HEADS[source_environment],
        "source_environment_head_mismatch",
    )
    checks.require(now.tzinfo is not None and now.utcoffset() is not None, "clock_must_be_aware")
    with engine.connect() as connection:
        heads = MigrationContext.configure(connection).get_current_heads()
    checks.require(heads == (expected_deployed_head,), "restored_head_mismatch")
    with checks.capture_baseline(engine, extra_tables=SHARED_TABLES, temp_dir=temp_dir) as original:
        shared = {name: original[name]["row_count"] for name in SHARED_TABLES if name in original}
        report = checks.migrate_and_check(engine, now=now, baseline=original)
        # Include newly exercised CAS/tombstones in the replay proof as well as
        # every pre-existing shared/private row. New rows remain allowed.
        with checks.capture_baseline(
            engine, extra_tables=SHARED_TABLES, temp_dir=temp_dir
        ) as replay:
            checks.migrate_to_latest(engine)
            checks.require(
                checks.current_revision(engine) == checks.HEAD, "candidate_migration_head_mismatch"
            )
            checks.compare_baseline(engine, replay)
        checks.compare_baseline(engine, original)
        return {
            **report,
            "source_environment": source_environment,
            "restored_head": expected_deployed_head,
            "candidate_head": checks.HEAD,
            "shared_baseline_rows": shared,
            "replay_preserved": True,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-environment", choices=tuple(DEPLOYED_HEADS), required=True)
    parser.add_argument("--expected-deployed-head", required=True)
    parser.add_argument("--source-sha", required=True)
    arguments = parser.parse_args(argv)
    engine = None
    try:
        # Historical audits/migrations may log. Only the closed aggregate below
        # belongs on stdout/stderr; discard internal output rather than save it.
        with (
            open(os.devnull, "w") as quiet,
            contextlib.redirect_stdout(quiet),
            contextlib.redirect_stderr(quiet),
        ):
            name = os.environ.get("KIVOU_V11_REHEARSAL_DATABASE_NAME", "")
            sha = os.environ.get("KIVOU_V11_CANDIDATE_SHA", "")
            target = validate_configuration(
                os.environ.get("KIVOU_V11_REHEARSAL_DATABASE_URL", ""),
                os.environ.get("KIVOU_DATABASE_URL", ""),
                name,
                sha,
                arguments.source_environment,
                arguments.expected_deployed_head,
                arguments.source_sha,
            )
            verify_checkout(sha)
            engine = sa.create_engine(target, hide_parameters=True)
            checks.verify_database(engine, name)
            report = run_checks(
                engine,
                source_environment=arguments.source_environment,
                expected_deployed_head=arguments.expected_deployed_head,
                now=dt.datetime.now(dt.UTC),
            )
            checks.verify_database(engine, name)
        print(
            json.dumps(
                {"status": "passed", "sha": sha, "source_sha": arguments.source_sha, **report},
                sort_keys=True,
            )
        )
        return 0
    except checks.RehearsalFailure as error:
        print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
        return 2
    except Exception:  # noqa: BLE001 - never echo private SQL, credentials or tracebacks
        print(
            json.dumps(
                {"status": "failed", "code": "company_rehearsal_execution_failed"}, sort_keys=True
            )
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
