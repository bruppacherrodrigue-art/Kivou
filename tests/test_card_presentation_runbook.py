from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "runbooks" / "11-staging-card-presentation-rollout.md"
OPERATIONS = ROOT / "ops" / "README.md"


def _body() -> str:
    assert RUNBOOK.is_file(), f"missing versioned rollout: {RUNBOOK}"
    return RUNBOOK.read_text(encoding="utf-8")


def _shell_blocks(body: str) -> tuple[str, ...]:
    blocks = re.findall(
        r"^~~~bash\n(.*?)^~~~$",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert blocks, "the rollout must contain executable bash blocks"
    return tuple(blocks)


def _commands(body: str) -> str:
    return "\n".join(_shell_blocks(body))


def _logical_shell(body: str) -> str:
    return re.sub(r"[ \t]*\\\n[ \t]*", " ", _commands(body))


def _assert_in_order(body: str, *fragments: str) -> None:
    cursor = -1
    for fragment in fragments:
        cursor = body.index(fragment, cursor + 1)


def _between(body: str, start: str, end: str) -> str:
    assert body.count(start) == 1
    assert body.count(end) == 1
    return body.split(start, 1)[1].split(end, 1)[0]


def _python_heredocs(body: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r"<<'PY'\n(.*?)^PY$",
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
    )


def _javascript_heredocs(body: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r"<<'JS'\n(.*?)^JS$",
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
    )


def _ci_jq_filter(body: str) -> str:
    prefix = 'jq -e --arg sha "$KIVOU_FINAL_SHA" \'\n'
    suffix = '\' <<<"$KIVOU_CI_JSON_PAYLOAD" >/dev/null'
    assert body.count(prefix) == 1
    assert body.count(suffix) == 1
    return body.split(prefix, 1)[1].split(suffix, 1)[0]


def _embedded_awk_after(commands: str, anchor: str) -> str:
    prefix = f'{anchor} | awk \'\n'
    suffix = "\n  '"
    assert commands.count(prefix) == 1
    return commands.split(prefix, 1)[1].split(suffix, 1)[0]


def _frontend_build_read_violations(section: str) -> tuple[str, ...]:
    """Find build-tree reads not executed across the documented user boundary."""
    logical = _logical_shell(section)
    logical = logical.split(
        'sudo install -o kivou -g kivou -m 700 -d "$KIVOU_FRONTEND_BUILD"',
        1,
    )[1]
    build_names = (
        "$KIVOU_FRONTEND_BUILD",
        "$KIVOU_FRONTEND_BUILD_MANIFEST",
        "$KIVOU_FRONTEND_MANIFEST",
        "$KIVOU_FRONTEND_RELEASE_MANIFEST",
        "$KIVOU_FRONTEND_RELEASE_RECHECK_MANIFEST",
        "$KIVOU_REVALIDATION_MANIFEST",
        "$KIVOU_FRONTEND_BUILD_REAL",
    )
    read_primitive = re.compile(
        r"(?:^|[ ($|;])(?:test|readlink|find|cmp|sha256sum|cat|grep|tar|tee)(?: |$)"
    )
    violations = []
    for line in logical.splitlines():
        if not any(
            re.search(re.escape(name) + r"(?![A-Z0-9_])", line)
            for name in build_names
        ):
            continue
        if not read_primitive.search(line):
            continue
        if (
            "kivou_frontend_build_owner" in line
            or "sudo -u kivou" in line
            or "--property=User=kivou" in line
        ):
            continue
        violations.append(line.strip())
    return tuple(violations)


def test_every_documented_shell_and_embedded_script_parses() -> None:
    body = _body()
    for index, block in enumerate(_shell_blocks(body)):
        parsed = subprocess.run(
            ["bash", "-n"],
            input=block,
            text=True,
            capture_output=True,
            check=False,
        )
        assert parsed.returncode == 0, f"bash block {index}: {parsed.stderr}"
    for index, script in enumerate(_python_heredocs(body)):
        compile(script, f"runbook-python-{index}", "exec")
    for index, script in enumerate(_javascript_heredocs(body)):
        parsed = subprocess.run(
            ["node", "--check"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert parsed.returncode == 0, f"javascript block {index}: {parsed.stderr}"


def test_qa_pregate_and_recovery_snapshot_accepts_live_revision_drift() -> None:
    scripts = _python_heredocs(_body())
    qa_pregate = next(
        script for script in scripts if "qa_read_only_scope_ok fingerprint=" in script
    )
    snapshot = next(script for script in scripts if "recovery_snapshot_failed" in script)
    common_modules = """
import sys
import types

def package(name):
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    return module

package("signals")
package("signals.persistence")
sqlalchemy = types.ModuleType("sqlalchemy")
sqlalchemy.text = lambda statement: statement
sys.modules["sqlalchemy"] = sqlalchemy
"""
    qa_pregate_prelude = common_modules + """
database = types.ModuleType("signals.persistence.database")

class Connection:
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def exec_driver_sql(self, _statement): return None
    def scalar(self, _statement, _parameters=None): return 1

class Engine:
    def connect(self): return Connection()

database.create_database_engine = lambda: Engine()
sys.modules["signals.persistence.database"] = database
"""
    qa_result = subprocess.run(
        [sys.executable, "-c", qa_pregate_prelude + qa_pregate],
        env={**os.environ, "KIVOU_CARD_QA_ACCOUNT_ID": "qa-account"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert qa_result.returncode == 0, qa_result.stderr

    account_id = "qa-account"
    fingerprint = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16]
    snapshot_prelude = common_modules + """
package("signals.card_intelligence")
package("signals.feed")
contracts = types.ModuleType("signals.card_intelligence.contracts")
factual = object()

class PresentationVariant:
    FACTUAL_FALLBACK = factual

class Claim:
    evidence_refs = ("evidence",)

class Payload:
    variant = factual
    claims = (Claim(),)

class CardPresentationPayload:
    @staticmethod
    def from_json_value(_value): return Payload()

contracts.CardPresentationPayload = CardPresentationPayload
contracts.PresentationVariant = PresentationVariant
sys.modules["signals.card_intelligence.contracts"] = contracts

class Presentation:
    status = "FALLBACK"
    content = Payload()
    def __init__(self, artifact_id): self.artifact_id = artifact_id

store = types.ModuleType("signals.card_intelligence.store")
store.published_for_signals = lambda _connection, **kwargs: {
    key: Presentation(f"a{index}")
    for index, key in enumerate(
        list(kwargs["bindings"])[:6] if kwargs["language"] == "fr" else []
    )
}
sys.modules["signals.card_intelligence.store"] = store

class Signal:
    def __init__(self, index):
        self.signal_key = f"s{index}"
        self.revision = 1

page = types.SimpleNamespace(
    limit=50,
    offset=0,
    items=tuple(types.SimpleNamespace(signal=Signal(index)) for index in range(49)),
    has_more=False,
    scan_truncated=False,
)
query = types.ModuleType("signals.feed.query")
query.feed_page = lambda *_args, **_kwargs: page
sys.modules["signals.feed.query"] = query

rows = [
    {
        "artifact_id": f"a{index}",
        "signal_key": f"s{index}",
        "signal_revision": 1 if index < 6 else 0,
        "target_icp_id": "target-icp",
        "target_icp_revision": 1,
        "language": "fr",
        "version": 1,
        "payload": {},
        "payload_variant": "FACTUAL_FALLBACK",
        "qa_status": "FALLBACK",
        "prompt_version": None,
        "model_id": None,
        "provider": None,
        "qa_model_id": None,
        "qa_provider": None,
        "superseded_at": None,
    }
    for index in range(8)
]

binding_rows = [
    {
        "signal_key": f"s{index}",
        "revision": 1,
        "target_icp_id": "target-icp",
        "target_icp_revision": 1,
    }
    for index in range(49)
]

class Result:
    def __init__(self, result_rows): self.result_rows = result_rows
    def mappings(self): return self
    def all(self): return self.result_rows

class Connection:
    def __init__(self):
        self.scalar_values = iter((0, 8, 0, 0, 0))
        self.result_rows = iter((rows, binding_rows))
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def exec_driver_sql(self, _statement): return None
    def execute(self, _statement, _parameters=None): return Result(next(self.result_rows))
    def scalar(self, _statement, _parameters=None): return next(self.scalar_values)

class Engine:
    def connect(self): return Connection()

database = types.ModuleType("signals.persistence.database")
database.create_database_engine = lambda: Engine()
database.current_revision = lambda _engine: "0028_card_presentation"
sys.modules["signals.persistence.database"] = database
"""
    snapshot_result = subprocess.run(
        [sys.executable, "-c", snapshot_prelude + snapshot],
        env={
            **os.environ,
            "KIVOU_CARD_QA_ACCOUNT_ID": account_id,
            "KIVOU_QA_APPROVED_FINGERPRINT": fingerprint,
            "KIVOU_RECOVERY_SNAPSHOT_PHASE": "baseline",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert snapshot_result.returncode == 0, snapshot_result.stderr
    snapshot_payload = json.loads(snapshot_result.stdout)
    assert snapshot_payload["candidate_count"] == 49
    assert snapshot_payload["active_counts"] == {"en": 0, "fr": 8}
    assert snapshot_payload["current_counts"] == {"en": 0, "fr": 6}
    assert len(snapshot_payload["artifacts"]) == 8
    assert [artifact["state"] for artifact in snapshot_payload["artifacts"]] == [
        "current",
        "current",
        "current",
        "current",
        "current",
        "current",
        "signal_revision_changed",
        "signal_revision_changed",
    ]
    assert all("target_icp_id" not in artifact for artifact in snapshot_payload["artifacts"])

    stale_target_prelude = snapshot_prelude.replace(
        '"target_icp_id": "target-icp",',
        '"target_icp_id": "stale-target",',
        1,
    )
    stale_target = subprocess.run(
        [sys.executable, "-c", stale_target_prelude + snapshot],
        env={
            **os.environ,
            "KIVOU_CARD_QA_ACCOUNT_ID": account_id,
            "KIVOU_QA_APPROVED_FINGERPRINT": fingerprint,
            "KIVOU_RECOVERY_SNAPSHOT_PHASE": "baseline",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert stale_target.returncode != 0
    assert stale_target.stderr == "recovery_snapshot_failed\n"

    stale_target_revision_prelude = snapshot_prelude.replace(
        '"target_icp_revision": 1,',
        '"target_icp_revision": 0,',
        1,
    )
    stale_target_revision = subprocess.run(
        [sys.executable, "-c", stale_target_revision_prelude + snapshot],
        env={
            **os.environ,
            "KIVOU_CARD_QA_ACCOUNT_ID": account_id,
            "KIVOU_QA_APPROVED_FINGERPRINT": fingerprint,
            "KIVOU_RECOVERY_SNAPSHOT_PHASE": "baseline",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert stale_target_revision.returncode != 0
    assert stale_target_revision.stderr == "recovery_snapshot_failed\n"


def test_rollout_proves_exact_main_ci_jobs_and_executed_steps_before_ssh() -> None:
    body = _body()
    commands = _commands(body)

    for fragment in (
        "git fetch origin main",
        "KIVOU_FINAL_SHA=$(git rev-parse origin/main)",
        '--event push --status success',
        '--json headSha,status,conclusion,jobs',
        "jq -e",
        '.steps | type == "array"',
        ".steps | length > 0",
        "Backend (Python 3.12 · uv)",
        "Frontend (Node 24 · npm)",
        "Installer uv",
        "Synchroniser les dépendances verrouillées",
        "Installer Node",
        "Installer Chromium verrouillé",
        "Régression visuelle des références",
        "Build Founder Console",
        "Typecheck",
        "Lint",
    ):
        assert fragment in commands

    _assert_in_order(
        commands,
        "KIVOU_FINAL_SHA=$(git rev-parse origin/main)",
        "KIVOU_CI_RUN_ID=",
        "gh run view",
        "jq -e",
        "repos/$KIVOU_REPOSITORY/commits/main",
        "ssh kivou-staging",
    )
    assert "kivou-production" not in body


def test_final_checkout_and_runbook_blob_are_exact_before_first_mutation_or_ssh() -> None:
    body = _body()
    step_one = _between(
        body,
        "## 1. Geler le SHA final et prouver la CI réellement exécutée",
        "## 2. Prouver staging et capturer les deux rollback targets",
    )
    commands = _commands(body)
    step_commands = _commands(step_one)

    assert "ssh " not in step_commands
    _assert_in_order(
        step_commands,
        "git fetch origin main",
        "KIVOU_FINAL_SHA=$(git rev-parse origin/main)",
        "KIVOU_CI_JSON_PAYLOAD=$(gh run view",
        "jq -e --arg sha",
        'repos/$KIVOU_REPOSITORY/commits/main',
        'test "$(git rev-parse HEAD)" = "$KIVOU_FINAL_SHA"',
        "git status --porcelain=v1 --untracked-files=all",
        'git hash-object "$KIVOU_RUNBOOK_PATH"',
        'git rev-parse "$KIVOU_FINAL_SHA:$KIVOU_RUNBOOK_PATH"',
        "kivou_validate_evidence_root",
        'install -m 700 -d "$KIVOU_EVIDENCE_DIR"',
    )
    first_ssh = commands.index("ssh kivou-staging")
    assert commands.index('test "$(git rev-parse HEAD)" = "$KIVOU_FINAL_SHA"') < first_ssh
    assert commands.index("git status --porcelain=v1 --untracked-files=all") < first_ssh


def test_evidence_root_is_absolute_external_private_and_semantically_guarded(
    tmp_path: Path,
) -> None:
    body = _body()
    commands = _commands(body)
    step_one = _between(
        body,
        "## 1. Geler le SHA final et prouver la CI réellement exécutée",
        "## 2. Prouver staging et capturer les deux rollback targets",
    )
    smoke = _between(
        body,
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )

    assert "artifacts/staging" not in body
    for fragment in (
        ': "${KIVOU_CARD_EVIDENCE_ROOT:?STOP:',
        'case "$KIVOU_CARD_EVIDENCE_ROOT" in',
        '(/*) ;;',
        'test ! -L "$KIVOU_CARD_EVIDENCE_ROOT"',
        'KIVOU_CARD_EVIDENCE_ROOT_REAL=$(readlink -f',
        'test "$KIVOU_CARD_EVIDENCE_ROOT_REAL" = "$KIVOU_CARD_EVIDENCE_ROOT"',
        '"$(id -un):700"',
        'KIVOU_OPERATOR_ROOT_REAL=$(readlink -f',
        '("$KIVOU_OPERATOR_ROOT_REAL"|"$KIVOU_OPERATOR_ROOT_REAL"/*)',
        'KIVOU_EVIDENCE_DIR="$KIVOU_CARD_EVIDENCE_ROOT_REAL/card-presentation-$KIVOU_FINAL_SHA"',
        'KIVOU_CI_JSON="$KIVOU_EVIDENCE_DIR/github-ci.json"',
        'chmod 600 "$KIVOU_CI_JSON"',
        'KIVOU_BROWSER_EVIDENCE_DIR="$KIVOU_EVIDENCE_DIR/browser"',
        'test "$(stat -c \'%U:%a\' "$KIVOU_BROWSER_EVIDENCE_DIR")" =',
        "umask 077",
        'sha256sum "$KIVOU_CI_JSON"',
        "verdict=ci_green",
        "verdict=visual_",
    ):
        assert fragment in commands or fragment in smoke
    assert '../$KIVOU_BROWSER_EVIDENCE_DIR' not in commands

    helper_start = "kivou_validate_evidence_root() {\n"
    assert step_one.count(helper_start) == 1
    helper = helper_start + step_one.split(helper_start, 1)[1].split("\n}\n", 1)[0]
    helper += "\n}\n"
    valid_root = tmp_path / "evidence"
    valid_root.mkdir(mode=0o700)
    harness = f"""
set -eu
KIVOU_CARD_EVIDENCE_ROOT=$1
{helper}
kivou_validate_evidence_root
test "$KIVOU_CARD_EVIDENCE_ROOT_REAL" = "$1"
"""
    valid = subprocess.run(
        ["bash", "-c", harness, "sh", str(valid_root)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr
    symlink = tmp_path / "evidence-link"
    symlink.symlink_to(valid_root, target_is_directory=True)
    rejected = subprocess.run(
        ["bash", "-c", harness, "sh", str(symlink)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0


def test_documented_ci_filter_accepts_executed_green_steps_and_rejects_empty_jobs() -> None:
    sha = "a" * 40
    checkout = {
        "name": "Run actions/checkout@v7",
        "status": "completed",
        "conclusion": "success",
    }
    payload = {
        "headSha": sha,
        "status": "completed",
        "conclusion": "success",
        "jobs": [
            {
                "name": "Backend (Python 3.12 · uv)",
                "status": "completed",
                "conclusion": "success",
                "steps": [
                    checkout,
                    *(
                        {
                            "name": name,
                            "status": "completed",
                            "conclusion": "success",
                        }
                        for name in (
                            "Installer uv",
                            "Synchroniser les dépendances verrouillées",
                            "Tests",
                            "Lint",
                        )
                    ),
                ],
            },
            {
                "name": "Frontend (Node 24 · npm)",
                "status": "completed",
                "conclusion": "success",
                "steps": [
                    checkout,
                    *(
                        {
                            "name": name,
                            "status": "completed",
                            "conclusion": "success",
                        }
                        for name in (
                            "Installer Node",
                            "Installer les dépendances verrouillées",
                            "Tests",
                            "Installer Chromium verrouillé",
                            "Régression visuelle des références",
                            "Build",
                            "Build Founder Console",
                            "Typecheck",
                            "Lint",
                        )
                    ),
                ],
            },
        ],
    }
    jq_filter = _ci_jq_filter(_body())

    def evaluate(candidate: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["jq", "-e", "--arg", "sha", sha, jq_filter],
            input=json.dumps(candidate),
            text=True,
            capture_output=True,
            check=False,
        )

    accepted = evaluate(payload)
    assert accepted.returncode == 0, accepted.stderr

    no_steps = json.loads(json.dumps(payload))
    no_steps["jobs"][0]["steps"] = []
    assert evaluate(no_steps).returncode != 0

    unexecuted_step = json.loads(json.dumps(payload))
    del unexecuted_step["jobs"][0]["steps"][0]["status"]
    assert evaluate(unexecuted_step).returncode != 0


def test_preflight_captures_both_releases_and_requires_selected_start_revision() -> None:
    body = _body()
    commands = _commands(
        _between(
            body,
            "## 2. Prouver staging et capturer les deux rollback targets",
            "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
        )
    )

    for fragment in (
        'test "$(hostname -s)" = "kivou-staging-01"',
        "KIVOU_PREVIOUS_BACKEND=$(readlink -f /srv/kivou/app)",
        "KIVOU_PREVIOUS_FRONTEND=$(readlink -f /srv/kivou/frontend)",
        "(/srv/kivou/releases/backend-*)",
        "(/srv/kivou/releases/frontend-*)",
        "expected_revision=os.environ[\"KIVOU_EXPECTED_START_REVISION\"]",
        "assert revision == expected_revision, (revision, expected_revision)",
        "kivou-backup.timer",
        "http://127.0.0.1:8000/openapi.json",
    ):
        assert fragment in commands

    assert "source /etc/kivou/staging.env" not in commands
    assert "cat /etc/kivou/staging.env" not in commands


def test_recovery_path_is_explicit_readonly_and_diff_limited() -> None:
    step_one = _between(
        _body(),
        "## 1. Geler le SHA final et prouver la CI réellement exécutée",
        "## 2. Prouver staging et capturer les deux rollback targets",
    )
    commands = _commands(step_one)

    for fragment in (
        "KIVOU_ROLLOUT_PATH=${KIVOU_ROLLOUT_PATH:-initial_0027}",
        "(initial_0027)",
        "(resume_51202525)",
        "KIVOU_EXPECTED_START_REVISION=0027_signal_notes",
        "KIVOU_EXPECTED_START_REVISION=0028_card_presentation",
        "KIVOU_RECOVERY_SOURCE_SHA=51202525d3163aeac259acbf9ac23086ed2cc256",
        "readonly KIVOU_ROLLOUT_PATH KIVOU_EXPECTED_START_REVISION",
        "src/signals/card_intelligence/backfill.py",
        "src/signals/card_intelligence/cli.py",
        "tests/test_card_intelligence_backfill.py",
        "tests/test_card_presentation_runbook.py",
        "docs/runbooks/11-staging-card-presentation-rollout.md",
        "KIVOU_RECOVERY_DIFF",
        "git merge-base --is-ancestor",
        "KIVOU_RECOVERY_STOP_FILE",
        "status=STOP_BACKFILL_SCAN_TRUNCATED",
        "KIVOU_ORIGINAL_ROLLOUT_STATUS=STOP_FAIL_CLOSED",
    ):
        assert fragment in commands
    assert "export KIVOU_ROLLOUT_PATH=resume_51202525" in step_one

    _assert_in_order(
        commands,
        "KIVOU_FINAL_SHA=$(git rev-parse origin/main)",
        "KIVOU_ROLLOUT_PATH=${KIVOU_ROLLOUT_PATH:-initial_0027}",
        "KIVOU_RECOVERY_DIFF",
        "KIVOU_CI_RUN_ID=",
        'readonly KIVOU_ROLLOUT_PATH KIVOU_EXPECTED_START_REVISION',
    )


def test_recovery_stop_file_parser_is_exact_complete_and_fail_closed(
    tmp_path: Path,
) -> None:
    step_one = _commands(
        _between(
            _body(),
            "## 1. Geler le SHA final et prouver la CI réellement exécutée",
            "## 2. Prouver staging et capturer les deux rollback targets",
        )
    )
    prefix = "kivou_validate_recovery_stop_file() {\n"
    assert step_one.count(prefix) == 1
    validator = prefix + step_one.split(prefix, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    expected = {
        "status": "STOP_BACKFILL_SCAN_TRUNCATED",
        "sha": "51202525d3163aeac259acbf9ac23086ed2cc256",
        "database_revision": "0028_card_presentation",
        "backend_release": "backend-20260831T221628Z-51202525d316",
        "frontend_release": "frontend-20260831T221628Z-51202525d316",
        "fr_factual_artifacts": "8",
        "en_factual_artifacts": "0",
        "other_tenant_artifacts": "0",
        "ai_bound_artifacts": "0",
        "current_owned_signals": "790",
        "get_candidate_scan_cap": "500",
        "get_page_items": "8",
        "get_page_excluded_without_display_name": "492",
        "get_page_scan_truncated": "1",
        "offline_diagnostic_cap": "1000",
        "offline_diagnostic_items": "44",
        "offline_diagnostic_scan_truncated": "0",
        "production_mutated": "0",
    }
    valid = "".join(f"{key}={value}\n" for key, value in expected.items())
    harness = (
        "set -euo pipefail\n"
        "KIVOU_RECOVERY_SOURCE_SHA="
        "51202525d3163aeac259acbf9ac23086ed2cc256\n"
        f"KIVOU_OPERATOR_ROOT_REAL={ROOT}\n"
        "KIVOU_RECOVERY_STOP_FILE=$1\n"
        + validator
        + "kivou_validate_recovery_stop_file\n"
        + 'test "$KIVOU_ORIGINAL_ROLLOUT_STATUS" = STOP_FAIL_CLOSED\n'
    )

    def evaluate(contents: str, *, mode: int = 0o600) -> subprocess.CompletedProcess[str]:
        case_dir = tmp_path / f"case-{len(tuple(tmp_path.iterdir()))}"
        case_dir.mkdir(mode=0o700)
        stop_file = case_dir / "rollout-stop.txt"
        stop_file.write_text(contents, encoding="utf-8")
        stop_file.chmod(mode)
        return subprocess.run(
            ["bash", "-c", harness, "bash", str(stop_file)],
            text=True,
            capture_output=True,
            check=False,
        )

    assert evaluate(valid).returncode == 0
    assert evaluate(valid + "status=STOP_BACKFILL_SCAN_TRUNCATED\n").returncode != 0
    assert evaluate(valid.replace("status=STOP_BACKFILL_SCAN_TRUNCATED\n", "")).returncode != 0
    assert evaluate(valid + "unknown_key=0\n").returncode != 0
    assert evaluate(valid.replace("current_owned_signals=790", "current_owned_signals=791")).returncode != 0
    assert evaluate(valid, mode=0o644).returncode != 0

    target = tmp_path / "target-rollout-stop.txt"
    target.write_text(valid, encoding="utf-8")
    target.chmod(0o600)
    symlink_dir = tmp_path / "symlink-case"
    symlink_dir.mkdir(mode=0o700)
    symlink = symlink_dir / "rollout-stop.txt"
    symlink.symlink_to(target)
    linked = subprocess.run(
        ["bash", "-c", harness, "bash", str(symlink)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert linked.returncode != 0


def test_recovery_preflight_proves_exact_partial_factual_state_before_backup() -> None:
    body = _body()
    preflight = _between(
        body,
        "## 2. Prouver staging et capturer les deux rollback targets",
        "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
    )
    commands = _commands(preflight)

    for fragment in (
        'test "$KIVOU_PREVIOUS_BACKEND_SHA" = "$KIVOU_RECOVERY_SOURCE_SHA"',
        'test "$(cat "$KIVOU_PREVIOUS_FRONTEND/KIVOU_RELEASE_SHA")" =',
        'assert revision == expected_revision, (revision, expected_revision)',
        'assert len(artifacts) == 8',
        'assert total_rows == 8',
        'assert all(row["language"] == "fr" for row in rows)',
        'assert foreign_rows == 0',
        'assert duplicates == 0',
        'assert all(row[field] is None for field in',
        "CardPresentationPayload.from_json_value",
        "PresentationVariant.FACTUAL_FALLBACK",
        "from signals.feed.query import feed_page",
        "from signals.card_intelligence.store import published_for_signals",
        "as_of=dt.date(2026, 8, 31)",
        'freshness="all"',
        "limit=50",
        "offset=0",
        "scan_cap=1000",
        "assert page.scan_truncated is False",
        "assert 1 <= len(page.items) <= 50",
        "page_bindings = {",
        'for language in ("fr", "en"):',
        "candidate_binding_digest = hashlib.sha256(json.dumps(sorted(",
        '"candidate_count": len(page_bindings)',
        '"active_digests": active_digests',
        '"current_digests": current_digests',
        '"active_outside_candidate_counts": active_outside_candidate_counts',
        "assert payload.claims",
        "assert all(claim.evidence_refs for claim in payload.claims)",
        'KIVOU_RECOVERY_BASELINE="$KIVOU_EVIDENCE_DIR/recovery-fr-baseline.json"',
        'chmod 600 "$KIVOU_RECOVERY_BASELINE"',
        "KIVOU_RECOVERY_BASELINE_SHA256=",
        ".candidate_count >= 8 and .candidate_count <= 50",
        "and (.artifacts | length) == 8",
        "kivou_capture_recovery_fr_snapshot()",
    ):
        assert fragment in commands

    _assert_in_order(
        body,
        'test "$(gh api "repos/$KIVOU_REPOSITORY/commits/main" --jq .sha)"',
        "KIVOU_RECOVERY_DIFF",
        'test "$KIVOU_PREVIOUS_BACKEND_SHA" = "$KIVOU_RECOVERY_SOURCE_SHA"',
        'KIVOU_RECOVERY_BASELINE="$KIVOU_EVIDENCE_DIR/recovery-fr-baseline.json"',
        "systemctl start kivou-backup.service",
    )


def test_backup_is_unique_verified_restored_and_dropped_before_migration() -> None:
    body = _body()
    commands = _commands(
        _between(
            body,
            "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
            "## 4. Préparer la release backend immuable et migrer vers 0028",
        )
    )

    for fragment in (
        "systemctl start kivou-backup.service",
        "KIVOU_BACKUP_FILES",
        'test "${#KIVOU_BACKUP_FILES[@]}" -eq 1',
        'kivou:kivou:600',
        'KIVOU_BACKUP_MIN_BYTES',
        'sha256sum "$KIVOU_BACKUP_FILE"',
        'pg_restore --list "$KIVOU_BACKUP_FILE"',
        'KIVOU_RESTORE_DB="kivou_card_restore_',
        "^[a-z0-9_]{1,63}$",
        "createdb --template=template0",
        "pg_restore --exit-on-error --no-owner --no-privileges",
        "KIVOU_EXPECTED_START_REVISION",
        "alembic_version",
        "account",
        "target_icp",
        "materialized_signal",
        "contract_award",
        "pg_database_size",
        'dropdb "$KIVOU_RESTORE_DB"',
    ):
        assert fragment in commands
    assert (
        'for KIVOU_DB_IDENTIFIER in "$KIVOU_LIVE_DB" "$KIVOU_LIVE_OWNER"; do'
        in commands
    )
    assert 'printf \'%s\\n\' "$KIVOU_DB_IDENTIFIER"' in commands

    _assert_in_order(
        _commands(body),
        "systemctl start kivou-backup.service",
        'sha256sum "$KIVOU_BACKUP_FILE"',
        'pg_restore --list "$KIVOU_BACKUP_FILE"',
        "createdb --template=template0",
        "pg_restore --exit-on-error --no-owner --no-privileges",
        'dropdb "$KIVOU_RESTORE_DB"',
        "migrate_to_latest(engine)",
    )


def test_recovery_backup_restores_0028_and_migration_is_not_replayed() -> None:
    body = _body()
    backup = _commands(
        _between(
            body,
            "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
            "## 4. Préparer la release backend immuable et migrer vers 0028",
        )
    )
    migration = _commands(
        _between(
            body,
            "## 4. Préparer la release backend immuable et migrer vers 0028",
            "## 5. Publier le backend par le blue/green versionné",
        )
    )

    assert '"$KIVOU_FINAL_SHORT" "$KIVOU_EXPECTED_START_REVISION"' in backup
    assert 'KIVOU_EXPECTED_START_REVISION=$2' in backup
    assert 'test "$KIVOU_RESTORED_REVISION" = "$KIVOU_EXPECTED_START_REVISION"' in backup
    assert 'restore_revision=%s' in backup
    assert 'test "$KIVOU_RESTORE_CARD_INVENTORY" = "8|8|0|0|1|0"' in backup

    for fragment in (
        'KIVOU_ROLLOUT_PATH=$3',
        'if rollout_path == "initial_0027":',
        'assert before == "0027_signal_notes", before',
        "migrate_to_latest(engine)",
        'elif rollout_path == "resume_51202525":',
        'assert before == "0028_card_presentation", before',
        'assert after == "0028_card_presentation", after',
        'print(f"database_transition={before}->{after}")',
    ):
        assert fragment in migration

    python = next(
        script
        for script in _python_heredocs(
            _between(
                body,
                "## 4. Préparer la release backend immuable et migrer vers 0028",
                "## 5. Publier le backend par le blue/green versionné",
            )
        )
        if "migrate_to_latest" in script
    )
    initial_branch, recovery_branch = python.split(
        'elif rollout_path == "resume_51202525":', 1
    )
    assert "migrate_to_latest(engine)" in initial_branch
    assert "migrate_to_latest(engine)" not in recovery_branch


def test_restore_catalog_checks_use_fail_closed_psql_stdin() -> None:
    commands = _commands(
        _between(
            _body(),
            "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
            "## 4. Préparer la release backend immuable et migrer vers 0028",
        )
    )

    assert commands.count("kivou_restore_db_count() {") == 1
    assert commands.count("kivou_restore_table_count() {") == 1
    assert commands.count("psql -X -qAt") == 4
    assert commands.count("--set=ON_ERROR_STOP=1") == 4
    assert '--set=db="$KIVOU_RESTORE_DB" <<\'SQL\'' in commands
    assert '--set=table="$KIVOU_TABLE" <<\'SQL\'' in commands
    assert "SELECT count(*) FROM pg_database WHERE datname = :'db';" in commands
    assert (
        "SELECT count(*) FROM pg_catalog.pg_class "
        "WHERE oid = to_regclass(:'table');"
    ) in commands
    assert commands.count(
        "KIVOU_RESTORE_DB_COUNT=$(kivou_restore_db_count)"
    ) == 2
    assert commands.count('test "$KIVOU_RESTORE_DB_COUNT" = 0') == 2
    assert commands.count(
        "KIVOU_RESTORE_TABLE_COUNT=$(kivou_restore_table_count)"
    ) == 1
    assert commands.count('test "$KIVOU_RESTORE_TABLE_COUNT" = 1') == 1
    assert 'test "$(kivou_restore_db_count)"' not in commands
    assert 'test "$(kivou_restore_table_count)"' not in commands
    assert '-c "SELECT count(*) FROM pg_database WHERE datname = :\'db\'"' not in commands
    assert "-c \"SELECT count(*) FROM pg_catalog.pg_class" not in commands


def test_remote_rollout_shells_use_shared_cwd_and_private_backup_identity() -> None:
    commands = _commands(
        _between(
            _body(),
            "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
            "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        )
    )

    shared_prefix = "set -euo pipefail\ncd /srv/kivou\n"
    assert commands.count(shared_prefix) == 6
    assert commands.count(shared_prefix + "KIVOU_FINAL_SHORT=$1") == 1
    assert commands.count(shared_prefix + "KIVOU_FINAL_SHA=$1") == 1
    assert commands.count(shared_prefix + "KIVOU_RELEASE_DIR=$1") == 4
    backup_identity_check = (
        'test "$(sudo -u kivou stat -c \'%U:%G:%a\' '
        '"$KIVOU_BACKUP_FILE")" = "kivou:kivou:600"'
    )
    unsafe_backup_identity_check = (
        'test "$(stat -c \'%U:%G:%a\' '
        '"$KIVOU_BACKUP_FILE")" = "kivou:kivou:600"'
    )
    backup_bytes_capture = (
        'KIVOU_BACKUP_BYTES=$(sudo -u kivou stat -c \'%s\' '
        '"$KIVOU_BACKUP_FILE")'
    )
    unsafe_backup_bytes_capture = (
        'KIVOU_BACKUP_BYTES=$(stat -c \'%s\' '
        '"$KIVOU_BACKUP_FILE")'
    )
    assert commands.count(backup_identity_check) == 1
    assert commands.count(backup_bytes_capture) == 1
    assert unsafe_backup_identity_check not in commands
    assert unsafe_backup_bytes_capture not in commands


def test_backend_release_migrates_0027_to_0028_before_versioned_blue_green() -> None:
    body = _body()

    for fragment in (
        "refs/heads/main",
        "ssh-keygen -lf",
        "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU",
        'test "$KIVOU_REMOTE_MAIN_SHA" = "$KIVOU_FINAL_SHA"',
        "backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT",
        'checkout --detach "$KIVOU_FINAL_SHA"',
        'sudo test ! -L "$KIVOU_RELEASE_DIR"',
        "uv sync --frozen --extra server --extra postgres",
        'assert script.get_current_head() == "0028_card_presentation"',
        'assert migration.down_revision == "0027_signal_notes"',
        'assert before == "0027_signal_notes", before',
        "migrate_to_latest(engine)",
        'assert after == "0028_card_presentation", after',
        "card_presentation_artifact",
        "ix_card_presentation_tenant_read",
        "uq_card_presentation_active_publication",
        r"Reverse proxy public de staging \(#84\)",
        "kivou-api-green.service 8001",
        "green_openapi_status=200",
        "green_me_status=401",
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
        "public-status.codes",
        'git show "$KIVOU_FINAL_SHA:ops/README.md"',
    ):
        assert fragment in body

    _assert_in_order(
        body,
        'assert after == "0028_card_presentation", after',
        "card_presentation_artifact",
        'print(f"migration={before}->{after}")',
        'git show "$KIVOU_FINAL_SHA:ops/README.md"',
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
    )

    backend_rollout = body.split(
        "## 5. Publier le backend par le blue/green versionné", 1
    )[1].split("## 6. Construire et basculer le frontend du même SHA", 1)[0]
    for fragment in (
        'test "$(readlink -f /srv/kivou/app)" = "$KIVOU_PREVIOUS_BACKEND"',
        'git show "$KIVOU_FINAL_SHA:ops/README.md"',
        "block >= 2 && block <= 6",
        "| ssh kivou-staging 'bash -s' --",
    ):
        assert fragment in backend_rollout
    _assert_in_order(
        backend_rollout,
        'test "$(readlink -f /srv/kivou/app)" = "$KIVOU_PREVIOUS_BACKEND"',
        "block >= 2 && block <= 6",
        "| ssh kivou-staging 'bash -s' --",
        'test "$(readlink -f /srv/kivou/app)" = "$KIVOU_RELEASE_DIR"',
    )


def test_blue_green_bootstrap_executes_authoritative_blocks_in_one_remote_shell() -> None:
    body = _body()
    rollout = _between(
        body,
        "## 5. Publier le backend par le blue/green versionné",
        "## 6. Construire et basculer le frontend du même SHA",
    )
    commands = _commands(rollout)

    for fragment in (
        'git show "$KIVOU_FINAL_SHA:ops/README.md"',
        r'/^## Reverse proxy public de staging \(#84\)$/',
        "block >= 2 && block <= 6",
        "if (emit && block == 3)",
        "$KIVOU_PREVIOUS_RELEASE",
        "$KIVOU_PREVIOUS_BACKEND",
        "| ssh kivou-staging 'bash -s' --",
        "KIVOU_RELEASE_DIR=$1",
        "KIVOU_RELEASE_SHA=$2",
        "KIVOU_STAGING_HOST=$3",
        "KIVOU_API_PORT=$4",
        "KIVOU_PREVIOUS_BACKEND=$5",
        'test "$(hostname -s)" = "kivou-staging-01"',
        'test "$KIVOU_STAGING_HOST" = "staging.kivou.eu"',
        'test "$KIVOU_API_PORT" = 8001',
        "kivou_git() {",
        'printf \'%s\\n\' "$KIVOU_BLUE_GREEN_SCRIPT" | bash -n',
    ):
        assert fragment in commands

    assert "reprendre au second bloc bash" not in rollout
    assert commands.count("| ssh kivou-staging 'bash -s' --") == 1
    _assert_in_order(
        commands,
        "KIVOU_RELEASE_DIR=$1",
        "kivou_git() {",
        'git show "$KIVOU_FINAL_SHA:ops/README.md"',
        'printf \'%s\\n\' "$KIVOU_BLUE_GREEN_SCRIPT" | bash -n',
        "| ssh kivou-staging 'bash -s' --",
    )

    awk_program = _embedded_awk_after(
        commands,
        'git show "$KIVOU_FINAL_SHA:ops/README.md"',
    )
    extracted = subprocess.run(
        ["awk", awk_program],
        input=OPERATIONS.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )
    assert extracted.returncode == 0, extracted.stderr
    for fragment in (
        "KIVOU_NGINX_CANDIDATE=",
        "KIVOU_ROLLOUT_STATE=",
        "--unit=kivou-api-green",
        "# single public reload to green",
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
        'test "$KIVOU_PREVIOUS_RELEASE" = "$KIVOU_PREVIOUS_BACKEND"',
    ):
        assert extracted.stdout.count(fragment) == 1
    assert "SHA main revu (40 hex)" not in extracted.stdout
    syntax = subprocess.run(
        ["bash", "-n"],
        input=extracted.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_backend_rollback_validates_root_only_state_against_captured_targets() -> None:
    rollback = _body().split("## 9. Rollback applicatif", 1)[1]
    commands = _commands(rollback)

    for fragment in (
        "KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state",
        (
            'test "$(sudo stat -c \'%U:%G:%a\' "$KIVOU_ROLLOUT_STATE")" = '
            '"root:root:600"'
        ),
        'sudo test ! -L "$KIVOU_ROLLOUT_STATE"',
        'KIVOU_ROLLOUT_STATE_CONTENT=$(sudo cat "$KIVOU_ROLLOUT_STATE")',
        'source /dev/stdin <<<"$KIVOU_ROLLOUT_STATE_CONTENT"',
        "unset KIVOU_ROLLOUT_STATE_CONTENT",
        'test "$KIVOU_SECURITY_RELEASE" = "$KIVOU_RELEASE_DIR"',
        'test "$KIVOU_PREVIOUS_RELEASE" = "$KIVOU_PREVIOUS_BACKEND"',
        'test "$KIVOU_RELEASE_SHA" = "$KIVOU_FINAL_SHA"',
        'test "$KIVOU_STAGING_HOST" = "staging.kivou.eu"',
        'printf \'%s\\n\' "$KIVOU_BACKEND_ROLLBACK_SCRIPT" | bash -n',
        "| ssh kivou-staging 'bash -s' --",
    ):
        assert fragment in commands

    assert 'printf \'%s\\n\' "$KIVOU_ROLLOUT_STATE_CONTENT"' not in commands
    assert 'echo "$KIVOU_ROLLOUT_STATE_CONTENT"' not in commands

    awk_program = _embedded_awk_after(
        commands,
        'git show "$KIVOU_FINAL_SHA:ops/README.md"',
    )
    extracted = subprocess.run(
        ["awk", awk_program],
        input=OPERATIONS.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )
    assert extracted.returncode == 0, extracted.stderr
    for fragment in (
        "KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state",
        "KIVOU_ROLLBACK_GREEN_UNIT=",
        'KIVOU_ROLLBACK_NEXT="$KIVOU_ROLLBACK_NEXT_DIR/app.next"',
        'sudo mv -Tf "$KIVOU_ROLLBACK_NEXT" /srv/kivou/app',
        'test "$KIVOU_ROLLBACK_NORMAL_OPENAPI_STATUS" = 200',
        'test "$KIVOU_ROLLBACK_NORMAL_ME_STATUS" = 401',
    ):
        assert fragment in extracted.stdout
    syntax = subprocess.run(
        ["bash", "-n"],
        input=extracted.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_frontend_uses_the_same_sha_and_switches_with_immediate_rollback() -> None:
    body = _body()
    commands = _commands(
        _between(
            body,
            "## 6. Construire et basculer le frontend du même SHA",
            "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        )
    )

    for fragment in (
        'KIVOU_RELEASE_SHORT=$(printf \'%s\' "$KIVOU_FINAL_SHA" | cut -c1-12)',
        "/srv/kivou/releases/.frontend-build-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT",
        "/srv/kivou/releases/frontend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT",
        'git -C "$KIVOU_RELEASE_DIR" archive "$KIVOU_FINAL_SHA" frontend',
        "HOME=/srv/kivou",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        '--chdir="$KIVOU_FRONTEND_BUILD/frontend"',
        "npm ci",
        "npm run build",
        "npm run typecheck",
        "npm run lint",
        'printf \'%s\\n\' "$KIVOU_FINAL_SHA"',
        "KIVOU_RELEASE_SHA",
        'sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend',
        'sudo mv -Tf "$KIVOU_FRONTEND_ROLLBACK" /srv/kivou/frontend',
        'sudo test ! -L "$KIVOU_FRONTEND_BUILD"',
        'sudo test ! -L "$KIVOU_FRONTEND_RELEASE"',
        'KIVOU_FRONTEND_NEXT="$KIVOU_FRONTEND_SWITCH_DIR/frontend.next"',
        'KIVOU_FRONTEND_ROLLBACK="$KIVOU_FRONTEND_SWITCH_DIR/frontend.rollback"',
        'kivou_frontend_http_smoke "$KIVOU_PREVIOUS_FRONTEND"',
        "/app/dashboard",
        "/app/companies",
        "/app/signals",
        "/assets/",
    ):
        assert fragment in commands
    assert 'KIVOU_RELEASE_SHA="$KIVOU_FINAL_SHA"' in body
    assert (
        '"$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_RELEASE_UTC"'
        in commands
    )

    _assert_in_order(
        commands,
        'git -C "$KIVOU_RELEASE_DIR" archive "$KIVOU_FINAL_SHA" frontend',
        "npm ci",
        "npm run build",
        'sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend',
        'kivou_frontend_http_smoke "$KIVOU_FRONTEND_RELEASE"',
        'sudo mv -Tf "$KIVOU_FRONTEND_ROLLBACK" /srv/kivou/frontend',
        'kivou_frontend_http_smoke "$KIVOU_PREVIOUS_FRONTEND"',
    )


def test_frontend_candidate_is_http_proven_before_live_switch() -> None:
    section = _between(
        _body(),
        "## 6. Construire et basculer le frontend du même SHA",
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
    )
    commands = _commands(section)

    for fragment in (
        "KIVOU_FRONTEND_PREVIEW_PORT=4174",
        'KIVOU_FRONTEND_PREVIEW_UNIT="kivou-frontend-preview-$KIVOU_RELEASE_SHORT"',
        "--strictPort",
        'trap kivou_stop_frontend_preview EXIT',
        "http://127.0.0.1:$KIVOU_FRONTEND_PREVIEW_PORT/",
        "/app/dashboard",
        "/app/companies",
        "/app/signals",
        "mapfile -t KIVOU_CANDIDATE_ASSET_PATHS",
        'for KIVOU_ASSET_PATH in "${KIVOU_CANDIDATE_ASSET_PATHS[@]}"; do',
        'test -f "$KIVOU_FRONTEND_RELEASE$KIVOU_ASSET_PATH"',
    ):
        assert fragment in commands

    _assert_in_order(
        commands,
        "KIVOU_FRONTEND_PREVIEW_PORT=4174",
        'trap kivou_stop_frontend_preview EXIT',
        "mapfile -t KIVOU_CANDIDATE_ASSET_PATHS",
        'for KIVOU_ASSET_PATH in "${KIVOU_CANDIDATE_ASSET_PATHS[@]}"; do',
        'sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend',
    )
    assert "head -n 1" not in commands.split(
        'sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend', 1
    )[0]


def test_frontend_preview_serves_exact_revalidated_immutable_release() -> None:
    section = _between(
        _body(),
        "## 6. Construire et basculer le frontend du même SHA",
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
    )
    commands = _commands(section)
    logical = _logical_shell(section)

    for fragment in (
        'KIVOU_FRONTEND_BUILD_MANIFEST=',
        'KIVOU_FRONTEND_RELEASE_MANIFEST=',
        'KIVOU_FRONTEND_RELEASE_RECHECK_MANIFEST=',
        'find . -xdev -type f -print0',
        '! -name KIVOU_RELEASE_SHA',
        'cmp --silent "$KIVOU_FRONTEND_BUILD_MANIFEST"',
        'KIVOU_EXPECTED_FRONTEND_MANIFEST_SHA=',
        'test ! -L "$KIVOU_FRONTEND_RELEASE"',
        'sudo find "$KIVOU_FRONTEND_RELEASE" -xdev ! -type d ! -type f',
        'sudo find "$KIVOU_FRONTEND_RELEASE" -xdev -type f -links +1',
        'kivou_revalidate_frontend_release',
        '--property=WorkingDirectory="$KIVOU_FRONTEND_RELEASE"',
        '--outDir "$KIVOU_FRONTEND_RELEASE"',
    ):
        assert fragment in logical

    preview = commands.split("sudo systemd-run --quiet --collect", 1)[1].split(
        "KIVOU_FRONTEND_PREVIEW_STATUS=000", 1
    )[0]
    assert 'WorkingDirectory="$KIVOU_FRONTEND_BUILD/frontend"' not in preview
    assert '--outDir "$KIVOU_FRONTEND_RELEASE"' in preview
    assert commands.count("kivou_revalidate_frontend_release") >= 3
    _assert_in_order(
        logical,
        'tar -C "$KIVOU_FRONTEND_RELEASE" -xf -',
        'cmp --silent "$KIVOU_FRONTEND_BUILD_MANIFEST"',
        '--property=WorkingDirectory="$KIVOU_FRONTEND_RELEASE"',
        "kivou_stop_frontend_preview",
        'kivou_revalidate_frontend_release "$KIVOU_FRONTEND_RELEASE_RECHECK_MANIFEST"',
        'test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_PREVIOUS_FRONTEND"',
        'sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend',
    )


def test_frontend_switch_prearms_unique_next_and_rollback_before_atomic_mv() -> None:
    section = _between(
        _body(),
        "## 6. Construire et basculer le frontend du même SHA",
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
    )
    commands = _commands(section)
    logical = _logical_shell(section)

    for fragment in (
        'KIVOU_FRONTEND_NEXT="$KIVOU_FRONTEND_SWITCH_DIR/frontend.next"',
        'KIVOU_FRONTEND_ROLLBACK="$KIVOU_FRONTEND_SWITCH_DIR/frontend.rollback"',
        'sudo ln -s "$KIVOU_FRONTEND_RELEASE" "$KIVOU_FRONTEND_NEXT"',
        'sudo ln -s "$KIVOU_PREVIOUS_FRONTEND" "$KIVOU_FRONTEND_ROLLBACK"',
        'test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_PREVIOUS_FRONTEND"',
        'case "$KIVOU_FRONTEND_SWITCH_DIR_REAL" in',
        "(/srv/kivou/.kivou-frontend-next.*)",
    ):
        assert fragment in commands
    assert "sudo mktemp -d /srv/kivou/.kivou-frontend-next.XXXXXX" in logical
    assert (
        'test "$(sudo readlink -f "$KIVOU_FRONTEND_NEXT")" = '
        '"$KIVOU_FRONTEND_RELEASE"'
    ) in logical
    assert (
        'test "$(sudo readlink -f "$KIVOU_FRONTEND_ROLLBACK")" = '
        '"$KIVOU_PREVIOUS_FRONTEND"'
    ) in logical

    assert "KIVOU_FRONTEND_NEXT=/srv/kivou/frontend.next" not in commands
    assert "KIVOU_FRONTEND_ROLLBACK=/srv/kivou/frontend.rollback" not in commands
    _assert_in_order(
        logical,
        'sudo ln -s "$KIVOU_FRONTEND_RELEASE" "$KIVOU_FRONTEND_NEXT"',
        'sudo ln -s "$KIVOU_PREVIOUS_FRONTEND" "$KIVOU_FRONTEND_ROLLBACK"',
        'test "$(sudo readlink -f "$KIVOU_FRONTEND_NEXT")" = '
        '"$KIVOU_FRONTEND_RELEASE"',
        'test "$(sudo readlink -f "$KIVOU_FRONTEND_ROLLBACK")" = '
        '"$KIVOU_PREVIOUS_FRONTEND"',
        'test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_PREVIOUS_FRONTEND"',
        'sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend',
    )


def test_every_closed_build_environment_sets_an_accessible_cwd_before_assignments() -> None:
    logical = _logical_shell(_body())
    invocations = tuple(
        line
        for line in logical.splitlines()
        if "/usr/bin/env -i" in line and "--chdir=" in line
    )

    assert len(invocations) >= 6
    for invocation in invocations:
        chdir = invocation.index("--chdir=")
        assert chdir < invocation.index("HOME=")
        assert chdir < invocation.index("PATH=")


def test_frontend_build_tree_reads_cross_the_kivou_700_permission_boundary(
    tmp_path: Path,
) -> None:
    section = _between(
        _body(),
        "## 6. Construire et basculer le frontend du même SHA",
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
    )
    commands = _commands(section)

    assert _frontend_build_read_violations(section) == ()
    assert 'sudo -u kivou tar -C "$KIVOU_FRONTEND_BUILD"' not in commands
    assert "kivou_frontend_build_owner tar -xf -" in commands
    unsafe_fixture = section.replace(
        'kivou_frontend_build_owner test -s "$KIVOU_FRONTEND_BUILD_MANIFEST"',
        'test -s "$KIVOU_FRONTEND_BUILD_MANIFEST"',
        1,
    )
    assert _frontend_build_read_violations(unsafe_fixture), (
        "the permission-boundary test must reject an operator-shell manifest read"
    )

    helper_start = "kivou_frontend_build_owner() {\n"
    assert commands.count(helper_start) == 1
    helper = helper_start + commands.split(helper_start, 1)[1].split("\n}\n", 1)[0]
    helper += "\n}\n"
    build = tmp_path / "build"
    dist = build / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("ok", encoding="utf-8")
    build.chmod(0o700)
    harness = f"""
sudo() {{
  test "$1" = -u
  test "$2" = kivou
  shift 2
  "$@"
}}
KIVOU_FRONTEND_BUILD=$1
{helper}
kivou_frontend_build_owner /bin/sh -eu -c '
  test "$PWD" = "$1"
  test -f frontend/dist/index.html
' sh "$KIVOU_FRONTEND_BUILD"
"""
    executed = subprocess.run(
        ["bash", "-eu", "-c", harness, "sh", str(build)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr


def test_read_only_qa_gate_precedes_rollout_mutations_and_each_backfill() -> None:
    body = _body()
    commands = _commands(body)
    qa_gate = _between(
        body,
        "kivou_validate_qa_read_only() {",
        "# Fin du garde-fou QA partagé en lecture seule.",
    )
    section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    section_commands = _commands(section)

    for fragment in (
        'connection.exec_driver_sql("SET TRANSACTION READ ONLY")',
        "!requests.some(({ method }) => !['GET', 'HEAD'].includes(method))",
        "context.request.get(`${origin}/me`)",
        'console.log("qa_read_only_gate_ok")',
        'console.error("qa_read_only_gate_failed")',
    ):
        assert fragment in qa_gate
    assert "/signals?" not in qa_gate
    assert "/app/signals" not in qa_gate
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "cli_main", "backfill-fallbacks"):
        assert forbidden not in qa_gate

    first_gate = 'kivou_validate_qa_read_only "$KIVOU_PREVIOUS_BACKEND"'
    assert commands.count(first_gate) == 1
    for first_mutation in (
        "sudo systemctl start kivou-backup.service",
        "sudo -u postgres createdb",
        "sudo -u postgres pg_restore",
        "sudo install -o kivou -g kivou -m 755 -d \"$KIVOU_RELEASE_DIR\"",
        "migrate_to_latest(engine)",
        "sudo mv -Tf",
    ):
        assert commands.index(first_gate) < commands.index(first_mutation)

    replay = 'kivou_validate_qa_read_only "$KIVOU_RELEASE_DIR"'
    assert section_commands.count(replay) == 1
    _assert_in_order(
        section_commands,
        replay,
        "KIVOU_WRITER_QUIESCENCE=",
        'kivou-card-backfill-fr-$KIVOU_FINAL_SHORT',
        'kivou-card-backfill-en-$KIVOU_FINAL_SHORT',
    )
    assert section_commands.count("kivou_revalidate_qa_binding") == 4


def test_qa_approved_fingerprint_is_frozen_once_and_compared_before_backfills() -> None:
    body = _body()
    commands = _commands(body)
    qa_gate = _between(
        body,
        "kivou_validate_qa_read_only() {",
        "# Fin du garde-fou QA partagé en lecture seule.",
    )
    section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    section_commands = _commands(section)

    assignments = re.findall(
        r"^\s*KIVOU_QA_APPROVED_FINGERPRINT="
        r"\$KIVOU_QA_READ_ONLY_FINGERPRINT$",
        commands,
        flags=re.MULTILINE,
    )
    assert len(assignments) == 1
    _assert_in_order(
        qa_gate,
        'if test -z "${KIVOU_QA_APPROVED_FINGERPRINT+x}"',
        "KIVOU_QA_APPROVED_FINGERPRINT=$KIVOU_QA_READ_ONLY_FINGERPRINT",
        'test "$KIVOU_QA_READ_ONLY_FINGERPRINT" =',
        '"$KIVOU_QA_APPROVED_FINGERPRINT"',
        "fi",
        "export KIVOU_QA_APPROVED_FINGERPRINT",
        "readonly KIVOU_QA_APPROVED_FINGERPRINT",
    )
    assert "KIVOU_QA_APPROVED_FINGERPRINT=$KIVOU_QA_READ_ONLY_FINGERPRINT" not in (
        qa_gate.split("else", 1)[1]
    )
    assert "KIVOU_QA_DB_FINGERPRINT=$KIVOU_QA_READ_ONLY_FINGERPRINT" not in body
    assert "KIVOU_QA_APPROVED_FINGERPRINT=$(" not in section_commands
    overwriting_mutant = section_commands.replace(
        "KIVOU_QA_SCOPE_FINGERPRINT=$(",
        "KIVOU_QA_APPROVED_FINGERPRINT=$(",
        1,
    )
    assert "KIVOU_QA_APPROVED_FINGERPRINT=$(" in overwriting_mutant

    replay = 'kivou_validate_qa_read_only "$KIVOU_RELEASE_DIR"'
    comparison = (
        'test "$KIVOU_QA_SCOPE_FINGERPRINT" = '
        '"$KIVOU_QA_APPROVED_FINGERPRINT"'
    )
    _assert_in_order(
        section_commands,
        comparison,
        replay,
        "KIVOU_WRITER_QUIESCENCE=",
        'kivou-card-backfill-fr-$KIVOU_FINAL_SHORT',
        'kivou-card-backfill-en-$KIVOU_FINAL_SHORT',
    )
    assert section_commands.count(comparison) >= 1
    backfill_commands = section_commands.split("KIVOU_QA_FACTUAL_PROOF=", 1)[0]
    assert backfill_commands.count(
        '--setenv="KIVOU_QA_APPROVED_FINGERPRINT='
        '$KIVOU_QA_APPROVED_FINGERPRINT"'
    ) == 2
    assert section_commands.count(
        'hmac.compare_digest(actual, expected)'
    ) >= 2


def test_preinitialized_approved_fingerprint_is_exported_and_readonly() -> None:
    qa_gate = _between(
        _body(),
        "kivou_validate_qa_read_only() {",
        "# Fin du garde-fou QA partagé en lecture seule.",
    )
    freeze = qa_gate.split(
        '  if test -z "${KIVOU_QA_APPROVED_FINGERPRINT+x}"; then\n', 1
    )[1].split("\n\n  (\n    cd frontend", 1)[0]
    freeze = (
        'if test -z "${KIVOU_QA_APPROVED_FINGERPRINT+x}"; then\n' + freeze
    )
    fingerprint = "0123456789abcdef"
    harness = f"""
set -eu
KIVOU_QA_APPROVED_FINGERPRINT={fingerprint}
KIVOU_QA_READ_ONLY_FINGERPRINT={fingerprint}
{freeze}
test "$KIVOU_QA_APPROVED_FINGERPRINT" = {fingerprint}
export -p | grep -Eq 'KIVOU_QA_APPROVED_FINGERPRINT="{fingerprint}"'
readonly -p | grep -Eq 'KIVOU_QA_APPROVED_FINGERPRINT="{fingerprint}"'
if (KIVOU_QA_APPROVED_FINGERPRINT=fedcba9876543210) 2>/dev/null; then
  exit 42
fi
"""
    executed = subprocess.run(
        ["bash", "-c", harness],
        text=True,
        capture_output=True,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr


def test_read_only_qa_gate_binds_to_the_exact_backend_currently_served() -> None:
    qa_gate = _between(
        _body(),
        "kivou_validate_qa_read_only() {",
        "# Fin du garde-fou QA partagé en lecture seule.",
    )
    for fragment in (
        "test -L /srv/kivou/app",
        "KIVOU_QA_SERVED_APP=$(readlink -f /srv/kivou/app)",
        'case "$KIVOU_QA_SERVED_APP" in',
        "(/srv/kivou/releases/backend-*)",
        'test "$KIVOU_QA_SERVED_APP" = "$KIVOU_QA_APP_DIR"',
        'test -d "$KIVOU_QA_SERVED_APP"',
    ):
        assert fragment in qa_gate
    _assert_in_order(
        qa_gate,
        "test -L /srv/kivou/app",
        "KIVOU_QA_SERVED_APP=$(readlink -f /srv/kivou/app)",
        'case "$KIVOU_QA_SERVED_APP" in',
        'test "$KIVOU_QA_SERVED_APP" = "$KIVOU_QA_APP_DIR"',
        "sudo systemd-run",
    )


def test_qa_gate_precedes_separate_bounded_fr_en_factual_backfills() -> None:
    body = _body()
    qa_section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )

    for fragment in (
        "/etc/kivou/card-presentation-qa.env",
        "root:kivou:640",
        "KIVOU_CARD_QA_ACCOUNT_ID",
        "ne crée pas ce fichier",
        "ne déduit jamais le compte",
        '"--language", "fr"',
        '"--language", "en"',
        "scan_truncated=0",
        "failed=0",
        "ne pas suivre `next_offset`",
        "FALLBACK",
        "FACTUAL_FALLBACK",
        "provider IS NULL",
        "model_id IS NULL",
        "prompt_version IS NULL",
        "qa_provider IS NULL",
        "qa_model_id IS NULL",
    ):
        assert fragment in qa_section

    _assert_in_order(
        qa_section,
        "KIVOU_CARD_QA_ACCOUNT_ID",
        '"--language", "fr"',
        '"--language", "en"',
        "provider IS NULL",
    )
    backfill_scripts = tuple(
        script for script in _python_heredocs(qa_section) if "cli_main" in script
    )
    assert len(backfill_scripts) == 2


def test_recovery_keeps_original_date_and_cumulative_fr_bound_before_en(
    tmp_path: Path,
) -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)

    for fragment in (
        'KIVOU_BACKFILL_AS_OF=2026-08-31',
        'KIVOU_FR_LIMIT=50',
        'KIVOU_EN_LIMIT=50',
        'readonly KIVOU_BACKFILL_AS_OF KIVOU_FR_LIMIT KIVOU_EN_LIMIT',
        'kivou_validate_backfill_summary "$KIVOU_FR_SUMMARY" "$KIVOU_FR_LIMIT"',
        'kivou_validate_backfill_summary "$KIVOU_EN_SUMMARY" "$KIVOU_EN_LIMIT"',
        '"--limit", os.environ["KIVOU_BACKFILL_LIMIT"]',
        'KIVOU_RECOVERY_POST_FR="$KIVOU_EVIDENCE_DIR/recovery-fr-post.json"',
        'kivou_capture_recovery_fr_snapshot "$KIVOU_RELEASE_DIR"',
        '--slurpfile baseline "$KIVOU_RECOVERY_BASELINE"',
        'all($baseline[0].artifacts[];',
        'del(.state) as $old',
        '| any($post.artifacts[]; del(.state) == $old))',
        '.candidate_count == $candidate_count',
        '.candidate_binding_digest == $prefr[0].candidate_binding_digest',
        'chmod 600 "$KIVOU_RECOVERY_POST_FR"',
        'recovery_fr_baseline_preserved=1',
        "KIVOU_RECOVERY_POST_FR_SHA256=",
    ):
        assert fragment in commands

    _assert_in_order(
        commands,
        'kivou_validate_qa_read_only "$KIVOU_RELEASE_DIR"',
        'kivou-card-backfill-fr-$KIVOU_FINAL_SHORT',
        'KIVOU_RECOVERY_POST_FR="$KIVOU_EVIDENCE_DIR/recovery-fr-post.json"',
        'recovery_fr_baseline_preserved=1',
        'kivou-card-backfill-en-$KIVOU_FINAL_SHORT',
    )

    backfills = tuple(
        script for script in _python_heredocs(section) if "cli_main" in script
    )
    assert len(backfills) == 2
    assert all('"--offset", "0"' in script for script in backfills)
    assert all('"--offset", "8"' not in script for script in backfills)
    assert all('"--offset", "500"' not in script for script in backfills)

    baseline_artifact = {
        "artifact_id": "a" * 64,
        "version": 1,
        "state": "current",
    }
    baseline = {"artifacts": [baseline_artifact]}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    subset_filter = (
        '($baseline[0] | type == "object" and (.artifacts | length) == 1) and '
        '(. as $post | all($baseline[0].artifacts[]; del(.state) as $old | '
        'any($post.artifacts[]; del(.state) == $old)))'
    )
    preserved = subprocess.run(
        ["jq", "-e", "--slurpfile", "baseline", str(baseline_path), subset_filter],
        input=json.dumps(
            {
                "artifacts": [
                    {**baseline_artifact, "state": "signal_revision_changed"},
                    {"artifact_id": "b" * 64, "version": 1},
                ]
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    removed = subprocess.run(
        ["jq", "-e", "--slurpfile", "baseline", str(baseline_path), subset_filter],
        input=json.dumps({"artifacts": []}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert preserved.returncode == 0, preserved.stderr
    assert removed.returncode != 0

    report = _between(
        _body(),
        "## 10. Rapport de preuve",
        "Le rapport doit aussi porter la ligne :",
    )
    assert "original_rollout_status=%s" in report
    assert "recovery_baseline_sha256=%s" in report
    assert "recovery_post_fr_sha256=%s" in report


def test_recovery_jq_ledgers_accept_state_drift_and_reject_mutations(
    tmp_path: Path,
) -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)

    def jq_filter_after(anchor: str, output_variable: str) -> str:
        tail = commands.split(anchor, 1)[1]
        jq_tail = tail.split("jq -e ", 1)[1]
        quoted_filter = jq_tail.split(" '\n", 1)[1]
        return quoted_filter.split(
            f'\n  \' "${output_variable}" >/dev/null',
            1,
        )[0]

    pre_fr_filter = jq_filter_after(
        'KIVOU_RECOVERY_PRE_FR="$KIVOU_EVIDENCE_DIR/recovery-fr-preflight.json"',
        "KIVOU_RECOVERY_PRE_FR",
    )
    post_fr_filter = jq_filter_after(
        'KIVOU_RECOVERY_POST_FR="$KIVOU_EVIDENCE_DIR/recovery-fr-post.json"',
        "KIVOU_RECOVERY_POST_FR",
    )
    post_en_filter = jq_filter_after(
        'KIVOU_RECOVERY_POST_EN="$KIVOU_EVIDENCE_DIR/recovery-post-en.json"',
        "KIVOU_RECOVERY_POST_EN",
    )
    assert "del(.state)" in pre_fr_filter
    assert "del(.state)" in post_fr_filter
    assert "del(.state)" in post_en_filter

    def artifact(index: int, *, state: str, language: str = "fr") -> dict[str, object]:
        return {
            "artifact_id": f"{index:064x}",
            "language": language,
            "version": 1,
            "signal_revision": 1,
            "target_icp_revision": 1,
            "state": state,
            "payload_sha256": f"{index + 100:064x}",
        }

    baseline_artifacts = [artifact(index, state="current") for index in range(8)]
    active_ids = {
        "en": [],
        "fr": [item["artifact_id"] for item in baseline_artifacts],
    }
    baseline = {
        "candidate_count": 10,
        "candidate_binding_digest": "a" * 64,
        "active_counts": {"en": 0, "fr": 8},
        "active_digests": {"en": "b" * 64, "fr": "c" * 64},
        "current_counts": {"en": 0, "fr": 8},
        "current_digests": {"en": "b" * 64, "fr": "c" * 64},
        "active_outside_candidate_counts": {"en": 0, "fr": 0},
        "active_artifact_ids": active_ids,
        "artifacts": baseline_artifacts,
    }
    pre_fr = {
        **baseline,
        "current_counts": {"en": 0, "fr": 6},
        "current_digests": {"en": "b" * 64, "fr": "d" * 64},
        "artifacts": [
            {**item, "state": "current" if index < 6 else "signal_revision_changed"}
            for index, item in enumerate(baseline_artifacts)
        ],
    }

    baseline_path = tmp_path / "baseline-object.json"
    pre_fr_path = tmp_path / "pre-fr-object.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    pre_fr_path.write_text(json.dumps(pre_fr), encoding="utf-8")

    def evaluate(
        jq_filter: str,
        payload: dict[str, object],
        *slurpfiles: tuple[str, Path],
    ) -> subprocess.CompletedProcess[str]:
        arguments = ["jq", "-e"]
        for name, path in slurpfiles:
            arguments.extend(("--slurpfile", name, str(path)))
        arguments.append(jq_filter)
        return subprocess.run(
            arguments,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    nominal_pre_fr = evaluate(
        pre_fr_filter,
        pre_fr,
        ("baseline", baseline_path),
    )
    assert nominal_pre_fr.returncode == 0, nominal_pre_fr.stderr

    mutated_ledger = json.loads(json.dumps(pre_fr))
    mutated_ledger["artifacts"][0]["payload_sha256"] = "f" * 64
    assert (
        evaluate(
            pre_fr_filter,
            mutated_ledger,
            ("baseline", baseline_path),
        ).returncode
        != 0
    )
    invalid_state_count = json.loads(json.dumps(pre_fr))
    invalid_state_count["artifacts"][7]["state"] = "current"
    assert (
        evaluate(
            pre_fr_filter,
            invalid_state_count,
            ("baseline", baseline_path),
        ).returncode
        != 0
    )

    post_fr_new = [artifact(index + 8, state="current") for index in range(4)]
    post_fr = {
        **pre_fr,
        "active_counts": {"en": 0, "fr": 10},
        "active_digests": {"en": "b" * 64, "fr": "e" * 64},
        "current_counts": {"en": 0, "fr": 10},
        "current_digests": {"en": "b" * 64, "fr": "e" * 64},
        "active_artifact_ids": {
            "en": [],
            "fr": [
                *(item["artifact_id"] for item in baseline_artifacts[:6]),
                *(item["artifact_id"] for item in post_fr_new),
            ],
        },
        "artifacts": [
            {
                **item,
                "state": "current" if index < 6 else "superseded",
            }
            for index, item in enumerate(baseline_artifacts)
        ]
        + post_fr_new,
    }
    nominal_post_fr = evaluate(
        post_fr_filter,
        post_fr,
        ("baseline", baseline_path),
        ("prefr", pre_fr_path),
    )
    assert nominal_post_fr.returncode == 0, nominal_post_fr.stderr

    stale_artifact_left_active = json.loads(json.dumps(post_fr))
    stale_artifact_left_active["active_artifact_ids"]["fr"][6] = (
        baseline_artifacts[6]["artifact_id"]
    )
    assert (
        evaluate(
            post_fr_filter,
            stale_artifact_left_active,
            ("baseline", baseline_path),
            ("prefr", pre_fr_path),
        ).returncode
        != 0
    )

    post_fr_path = tmp_path / "post-fr-object.json"
    post_fr_path.write_text(json.dumps(post_fr), encoding="utf-8")
    post_en_new = [
        artifact(index + 12, state="current", language="en") for index in range(10)
    ]
    post_en = {
        **post_fr,
        "active_counts": {"en": 10, "fr": 10},
        "active_digests": {"en": "f" * 64, "fr": "e" * 64},
        "current_counts": {"en": 10, "fr": 10},
        "current_digests": {"en": "f" * 64, "fr": "e" * 64},
        "active_artifact_ids": {
            "en": [item["artifact_id"] for item in post_en_new],
            "fr": post_fr["active_artifact_ids"]["fr"],
        },
        "artifacts": post_fr["artifacts"] + post_en_new,
    }
    nominal_post_en = evaluate(
        post_en_filter,
        post_en,
        ("baseline", baseline_path),
        ("post_fr", post_fr_path),
    )
    assert nominal_post_en.returncode == 0, nominal_post_en.stderr

    mutated_post_fr_ledger = json.loads(json.dumps(post_en))
    mutated_post_fr_ledger["artifacts"][0]["version"] = 2
    assert (
        evaluate(
            post_en_filter,
            mutated_post_fr_ledger,
            ("baseline", baseline_path),
            ("post_fr", post_fr_path),
        ).returncode
        != 0
    )


def test_writer_quiescence_is_fail_safe_and_ends_before_browser_smoke() -> None:
    body = _body()
    section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)

    for fragment in (
        "KIVOU_WRITER_STATE_FILE=",
        "kivou-acquisition.timer",
        "kivou-ingest-simap.timer",
        "kivou-ingest-boamp.timer",
        "kivou-ingest-decp.timer",
        "kivou-ingest-ted.timer",
        '--on-active=20m',
        'sudo systemctl stop kivou-api.service "${KIVOU_WRITER_SERVICES[@]}"',
        'KIVOU_WRITER_STATE=$(systemctl is-active "$KIVOU_WRITER_UNIT" ||',
        'test "$KIVOU_WRITER_STATE" = inactive',
        "kivou_resume_card_writers_on_exit() {",
        "KIVOU_ROLLOUT_EXIT_STATUS=$?",
        "if ! kivou_resume_card_writers; then",
        "KIVOU_ROLLOUT_EXIT_STATUS=1",
        'exit "$KIVOU_ROLLOUT_EXIT_STATUS"',
        "trap kivou_resume_card_writers_on_exit EXIT",
        'sudo systemctl stop "$KIVOU_WRITER_WATCHDOG.timer"',
        'sudo systemctl start kivou-api.service "${KIVOU_RESTART_TIMERS[@]}"',
        '"$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh"',
        "writer_resumed=1",
    ):
        assert fragment in commands

    _assert_in_order(
        section,
        'kivou_validate_qa_read_only "$KIVOU_RELEASE_DIR"',
        "KIVOU_WRITER_QUIESCENCE=",
        '--on-active=20m',
        'test "$KIVOU_WRITER_STATE" = inactive',
        "trap kivou_resume_card_writers_on_exit EXIT",
        "KIVOU_RECOVERY_PRE_FR=",
        "kivou-card-backfill-fr-$KIVOU_FINAL_SHORT",
        "kivou-card-backfill-en-$KIVOU_FINAL_SHORT",
        "KIVOU_RECOVERY_POST_EN=",
        "KIVOU_WRITER_RESUME=$(kivou_resume_card_writers)",
        "^writer_resumed=1 timer_states=[01]{5}",
        "trap - EXIT",
    )
    resume_proof = "KIVOU_WRITER_RESUME=$(kivou_resume_card_writers)"
    assert body.index(resume_proof) < body.index("## 8. Smoke navigateur desktop et mobile")

    function_prefix = "kivou_resume_card_writers_on_exit() {\n"
    trap_function = (
        function_prefix
        + commands.split(function_prefix, 1)[1].split("\n}\n", 1)[0]
        + "\n}\n"
    )

    def run_trap(*, rollout_status: int, resume_status: int) -> int:
        harness = (
            "set -u\n"
            f"kivou_resume_card_writers() {{ return {resume_status}; }}\n"
            + trap_function
            + "(\n"
            + "  trap kivou_resume_card_writers_on_exit EXIT\n"
            + f"  exit {rollout_status}\n"
            + ")\n"
        )
        return subprocess.run(
            ["bash", "-c", harness],
            text=True,
            capture_output=True,
            check=False,
        ).returncode

    assert run_trap(rollout_status=23, resume_status=0) == 23
    assert run_trap(rollout_status=0, resume_status=1) == 1
    assert run_trap(rollout_status=23, resume_status=1) == 1


def test_watchdog_is_rearmed_before_every_bounded_recovery_phase() -> None:
    body = _body()
    section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)
    all_commands = _commands(body)

    helper_prefix = "kivou_rearm_card_writer_watchdog() {\n"
    assert commands.count(helper_prefix) == 1
    helper = (
        helper_prefix
        + commands.split(helper_prefix, 1)[1].split("\n}\n", 1)[0]
        + "\n}\n"
    )
    for fragment in (
        "KIVOU_WRITER_WATCHDOG",
        "^kivou-card-writers-resume-[0-9a-f]{12}$",
        "kivou-api.service",
        "kivou-acquisition.timer",
        "kivou-ingest-simap.timer",
        "kivou-ingest-boamp.timer",
        "kivou-ingest-decp.timer",
        "kivou-ingest-ted.timer",
        "kivou-acquisition.service",
        "kivou-ingest-simap.service",
        "kivou-ingest-boamp.service",
        "kivou-ingest-decp.service",
        "kivou-ingest-ted.service",
        "KIVOU_WATCHDOG_TIMER_STATE=$(systemctl is-active",
        '"$KIVOU_WRITER_WATCHDOG.timer" ||',
        'test "$KIVOU_WATCHDOG_TIMER_STATE" = active',
        "KIVOU_WATCHDOG_SERVICE_STATE=$(systemctl is-active",
        '"$KIVOU_WRITER_WATCHDOG.service" ||',
        'test "$KIVOU_WATCHDOG_SERVICE_STATE" = inactive',
        'KIVOU_WRITER_STATE=$(systemctl is-active "$KIVOU_WRITER_UNIT" ||',
        'test "$KIVOU_WRITER_STATE" = inactive',
        'sudo systemctl restart "$KIVOU_WRITER_WATCHDOG.timer"',
    ):
        assert fragment in helper
    assert "! systemctl is-active" not in helper
    assert helper.count("KIVOU_WATCHDOG_TIMER_STATE=$(systemctl is-active") == 2
    assert helper.count('test "$KIVOU_WATCHDOG_TIMER_STATE" = active') == 2
    assert helper.count("KIVOU_WATCHDOG_SERVICE_STATE=$(systemctl is-active") == 2
    assert helper.count('test "$KIVOU_WATCHDOG_SERVICE_STATE" = inactive') == 2
    assert helper.count("KIVOU_WRITER_STATE=$(systemctl is-active") == 2
    assert helper.count('test "$KIVOU_WRITER_STATE" = inactive') == 2
    _assert_in_order(
        helper,
        'test "$KIVOU_WATCHDOG_TIMER_STATE" = active',
        'test "$KIVOU_WATCHDOG_SERVICE_STATE" = inactive',
        'test "$KIVOU_WRITER_STATE" = inactive',
        'sudo systemctl restart "$KIVOU_WRITER_WATCHDOG.timer"',
        'test "$KIVOU_WATCHDOG_TIMER_STATE" = active',
        'test "$KIVOU_WATCHDOG_SERVICE_STATE" = inactive',
        'test "$KIVOU_WRITER_STATE" = inactive',
    )

    remote_body = re.findall(
        r"<<'REMOTE'\n(.*?)^REMOTE$",
        helper,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert len(remote_body) == 1

    def run_rearm_with_states(
        *,
        writer_state: str = "inactive",
        timer_before: str = "active",
        service_before: str = "inactive",
        timer_after: str = "active",
        service_after: str = "inactive",
    ) -> subprocess.CompletedProcess[str]:
        harness = (
            "set -u\n"
            "KIVOU_FAKE_RESTARTED=0\n"
            "sudo() { \"$@\"; }\n"
            "systemctl() {\n"
            "  if test \"$1\" = show; then printf '%s\\n' loaded; return 0; fi\n"
            "  if test \"$1\" = restart; then\n"
            "    KIVOU_FAKE_RESTARTED=1\n"
            "    printf '%s\\n' restart_called\n"
            "    return 0\n"
            "  fi\n"
            "  if test \"$1\" = is-active; then\n"
            "    shift\n"
            "    if test \"${1:-}\" = --quiet; then shift; fi\n"
            "    case \"$1\" in\n"
            "      (*.timer) case \"$1\" in\n"
            "        (kivou-card-writers-resume-*.timer)\n"
            "          if test \"$KIVOU_FAKE_RESTARTED\" = 0; then\n"
            "            KIVOU_FAKE_STATE=$KIVOU_FAKE_TIMER_BEFORE\n"
            "          else KIVOU_FAKE_STATE=$KIVOU_FAKE_TIMER_AFTER; fi ;;\n"
            "        (*) KIVOU_FAKE_STATE=$KIVOU_FAKE_WRITER_STATE ;;\n"
            "      esac ;;\n"
            "      (kivou-card-writers-resume-*.service)\n"
            "        if test \"$KIVOU_FAKE_RESTARTED\" = 0; then\n"
            "          KIVOU_FAKE_STATE=$KIVOU_FAKE_SERVICE_BEFORE\n"
            "        else KIVOU_FAKE_STATE=$KIVOU_FAKE_SERVICE_AFTER; fi ;;\n"
            "      (*) KIVOU_FAKE_STATE=$KIVOU_FAKE_WRITER_STATE ;;\n"
            "    esac\n"
            "    printf '%s\\n' \"$KIVOU_FAKE_STATE\"\n"
            "    case \"$KIVOU_FAKE_STATE\" in (inactive|failed) return 3 ;; "
            "(*) return 0 ;; esac\n"
            "  fi\n"
            "  return 1\n"
            "}\n"
            + remote_body[0]
        )
        return subprocess.run(
            ["bash", "-c", harness, "bash", "kivou-card-writers-resume-abcdef123456"],
            env={
                **os.environ,
                "KIVOU_FAKE_WRITER_STATE": writer_state,
                "KIVOU_FAKE_TIMER_BEFORE": timer_before,
                "KIVOU_FAKE_SERVICE_BEFORE": service_before,
                "KIVOU_FAKE_TIMER_AFTER": timer_after,
                "KIVOU_FAKE_SERVICE_AFTER": service_after,
            },
            text=True,
            capture_output=True,
            check=False,
        )

    nominal = run_rearm_with_states()
    assert nominal.returncode == 0, nominal.stderr
    for pre_restart_mutant in (
        run_rearm_with_states(service_before="active"),
        run_rearm_with_states(timer_before="inactive"),
    ):
        assert pre_restart_mutant.returncode != 0
        assert "restart_called" not in pre_restart_mutant.stdout
    assert run_rearm_with_states(timer_after="inactive").returncode != 0
    assert run_rearm_with_states(service_after="active").returncode != 0
    for state in ("activating", "deactivating", "failed"):
        assert run_rearm_with_states(writer_state=state).returncode != 0

    rearm = "kivou_rearm_card_writer_watchdog"
    assert commands.count(rearm) == 6
    phase_patterns = (
        rf"{rearm}\n  KIVOU_RECOVERY_PRE_FR_PAYLOAD=",
        (
            rf"{rearm}\nssh kivou-staging 'bash -s' -- .*?"
            r"kivou-card-backfill-fr-\$KIVOU_FINAL_SHORT"
        ),
        rf"{rearm}\n  KIVOU_RECOVERY_POST_FR_PAYLOAD=",
        (
            rf"{rearm}\nssh kivou-staging 'bash -s' -- .*?"
            r"kivou-card-backfill-en-\$KIVOU_FINAL_SHORT"
        ),
        rf"{rearm}\n  KIVOU_RECOVERY_POST_EN_PAYLOAD=",
    )
    for pattern in phase_patterns:
        assert re.search(pattern, commands, flags=re.DOTALL)

    _assert_in_order(
        commands,
        "trap kivou_resume_card_writers_on_exit EXIT",
        rearm,
        "KIVOU_RECOVERY_PRE_FR_PAYLOAD=",
        rearm,
        "kivou-card-backfill-fr-$KIVOU_FINAL_SHORT",
        rearm,
        "KIVOU_RECOVERY_POST_FR_PAYLOAD=",
        rearm,
        "kivou-card-backfill-en-$KIVOU_FINAL_SHORT",
        rearm,
        "KIVOU_RECOVERY_POST_EN_PAYLOAD=",
    )

    assert all_commands.count("--property=RuntimeMaxSec=5min") == 3
    for unit in (
        'unit="kivou-card-recovery-snapshot-$$"',
        'unit="kivou-card-backfill-fr-$KIVOU_FINAL_SHORT"',
        'unit="kivou-card-backfill-en-$KIVOU_FINAL_SHORT"',
    ):
        invocation = all_commands.split(unit, 1)[1].split("<<'PY'", 1)[0]
        assert "--property=RuntimeMaxSec=5min" in invocation

    assert re.search(
        r"[ÉE]chec\s+(?:du\s+|de\s+)?"
        r"(?:réarmement|preuve de quiescence|timeout).*?"
        r"échoue\s+fermé.*?avant\s+la\s+phase\s+suivante",
        section,
        flags=re.DOTALL | re.IGNORECASE,
    )


def test_writer_resume_rejects_nonterminal_disabled_timer_states() -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)
    function_prefix = "kivou_resume_card_writers() {\n"
    resume_function = (
        function_prefix
        + commands.split(function_prefix, 1)[1].split("\n}\n", 1)[0]
        + "\n}\n"
    )
    remote_bodies = re.findall(
        r"<<'REMOTE'\n(.*?)^REMOTE$",
        resume_function,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert len(remote_bodies) == 1
    disabled_branch = remote_bodies[0].split("  else\n", 1)[1].split("\n  fi", 1)[0]
    assert "! systemctl is-active" not in disabled_branch
    assert (
        'KIVOU_WRITER_TIMER_STATE=$(systemctl is-active "$KIVOU_WRITER_TIMER" ||'
        in disabled_branch
    )
    assert 'test "$KIVOU_WRITER_TIMER_STATE" = inactive' in disabled_branch

    def run_disabled_branch(state: str) -> subprocess.CompletedProcess[str]:
        harness = (
            "set -euo pipefail\n"
            "KIVOU_WRITER_TIMER=kivou-acquisition.timer\n"
            "systemctl() {\n"
            "  printf '%s\\n' \"$KIVOU_FAKE_TIMER_STATE\"\n"
            "  case \"$KIVOU_FAKE_TIMER_STATE\" in\n"
            "    (inactive|failed) return 3 ;;\n"
            "    (*) return 0 ;;\n"
            "  esac\n"
            "}\n"
            + disabled_branch
            + "\n"
        )
        return subprocess.run(
            ["bash", "-c", harness],
            env={**os.environ, "KIVOU_FAKE_TIMER_STATE": state},
            text=True,
            capture_output=True,
            check=False,
        )

    nominal = run_disabled_branch("inactive")
    assert nominal.returncode == 0, nominal.stderr
    for state in ("activating", "deactivating", "failed"):
        assert run_disabled_branch(state).returncode != 0


def test_recovery_transaction_guard_and_exact_summaries_are_fail_closed() -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)
    all_commands = _commands(_body())
    for fragment in (
        "KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST",
        "KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST",
        "KIVOU_RECOVERY_CANDIDATE_COUNT",
        "KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST",
        "KIVOU_RECOVERY_FR_ACTIVE_DIGEST",
        "KIVOU_RECOVERY_FR_CURRENT_DIGEST",
        '"--expect-candidate-count",',
        'os.environ["KIVOU_EXPECTED_CANDIDATE_COUNT"]',
        '"--expect-active-publication-count",',
        '"--expect-current-factual-artifact-digest",',
        'os.environ["KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST"]',
        '"--expect-candidate-binding-digest",',
        'os.environ["KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST"]',
        '"--expect-active-artifact-digest",',
        'os.environ["KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST"]',
        ".candidate_count == $candidate_count",
        '.active_counts == {"en":$candidate_count,"fr":$candidate_count}',
    ):
        assert fragment in all_commands
    assert "`NOWAIT`" in section
    assert re.search(r"sans jamais\s+attendre ni sacrifier le writer", section)

    _assert_in_order(
        commands,
        'kivou_validate_qa_read_only "$KIVOU_RELEASE_DIR"',
        "KIVOU_RECOVERY_PRE_FR=",
        'kivou_capture_recovery_fr_snapshot "$KIVOU_RELEASE_DIR" baseline',
        "kivou-card-backfill-fr-$KIVOU_FINAL_SHORT",
        "KIVOU_RECOVERY_POST_FR=",
        "kivou-card-backfill-en-$KIVOU_FINAL_SHORT",
    )

    prefix = "kivou_validate_recovery_summary() {\n"
    assert commands.count(prefix) == 2
    validator_parts = commands.split(prefix)
    assert len(validator_parts) == 3
    fr_validator = prefix + validator_parts[1].split("\n}\n", 1)[0] + "\n}\n"
    en_validator = prefix + validator_parts[2].split("\n}\n", 1)[0] + "\n}\n"

    backfills = tuple(
        script for script in _python_heredocs(section) if "cli_main" in script
    )
    assert len(backfills) == 2
    primary_flags = (
        "--expect-candidate-count",
        "--expect-active-publication-count",
        "--expect-current-factual-artifact-digest",
        "--expect-candidate-binding-digest",
        "--expect-active-artifact-digest",
    )
    protected_flags = (
        "--expect-protected-language",
        "--expect-protected-active-publication-count",
        "--expect-protected-current-factual-artifact-digest",
        "--expect-protected-active-artifact-digest",
    )
    assert all(sum(flag in script for flag in primary_flags) == 5 for script in backfills)
    assert sum(flag in backfills[0] for flag in protected_flags) == 0
    assert sum(flag in backfills[1] for flag in protected_flags) == 4

    def validate(
        validator: str,
        language: str,
        summary: str,
    ) -> subprocess.CompletedProcess[str]:
        harness = (
            "set -euo pipefail\n"
            "KIVOU_ROLLOUT_PATH=resume_51202525\n"
            "KIVOU_EXPECTED_CANDIDATE_COUNT=17\n"
            "KIVOU_EXPECTED_CURRENT_COUNT=5\n"
            + validator
            + f"kivou_validate_recovery_summary {language} '{summary}'\n"
        )
        return subprocess.run(
            ["bash", "-c", harness],
            text=True,
            capture_output=True,
            check=False,
        )

    fr = (
        "scanned=17 published=12 unchanged=5 failed=0 "
        "next_offset=none scan_truncated=0"
    )
    en = (
        "scanned=17 published=17 unchanged=0 failed=0 "
        "next_offset=none scan_truncated=0"
    )
    assert validate(fr_validator, "fr", fr).returncode == 0
    assert validate(en_validator, "en", en).returncode == 0
    assert (
        validate(
            fr_validator,
            "fr",
            fr.replace("next_offset=none", "next_offset=50"),
        ).returncode
        != 0
    )
    assert (
        validate(
            en_validator,
            "en",
            en.replace("next_offset=none", "next_offset=58"),
        ).returncode
        != 0
    )
    assert (
        validate(
            fr_validator,
            "fr",
            fr.replace("unchanged=5", "unchanged=4"),
        ).returncode
        != 0
    )
    assert (
        validate(
            en_validator,
            "en",
            en.replace("published=17", "published=16"),
        ).returncode
        != 0
    )


def test_recovery_revalidates_complete_offline_feed_after_fr_and_en() -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _logical_shell(section)
    helper = _commands(
        _between(
            _body(),
            "## 2. Prouver staging et capturer les deux rollback targets",
            "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
        )
    )

    for fragment in (
        "(baseline|post_fr|post_en)",
        "assert 1 <= len(page.items) <= 50",
        "assert page.has_more is False",
        "assert page.scan_truncated is False",
        "limit=50",
        "scan_cap=1000",
        "page_bindings = {",
        'for language in ("fr", "en"):',
        "current = published_for_signals(",
        "candidate_binding_digest = hashlib.sha256(json.dumps(sorted(",
        '"candidate_count": len(page_bindings)',
        '"active_digests": active_digests',
        '"current_digests": current_digests',
    ):
        assert fragment in helper
    _assert_in_order(
        commands,
        "kivou-card-backfill-fr-$KIVOU_FINAL_SHORT",
        'kivou_capture_recovery_fr_snapshot "$KIVOU_RELEASE_DIR" post_fr',
        "kivou-card-backfill-en-$KIVOU_FINAL_SHORT",
        'kivou_capture_recovery_fr_snapshot "$KIVOU_RELEASE_DIR" post_en',
    )
    assert 'KIVOU_RECOVERY_POST_EN="$KIVOU_EVIDENCE_DIR/recovery-post-en.json"' in commands
    assert 'chmod 600 "$KIVOU_RECOVERY_POST_EN"' in commands
    post_en = commands.split("KIVOU_RECOVERY_POST_EN=", 1)[1]
    assert '--slurpfile baseline "$KIVOU_RECOVERY_BASELINE"' in post_en
    assert "all($baseline[0].artifacts[];" in post_en
    assert "del(.state) as $old" in post_en
    assert "| any($post.artifacts[]; del(.state) == $old))" in post_en
    assert '--slurpfile post_fr "$KIVOU_RECOVERY_POST_FR"' in post_en
    assert "all($post_fr[0].artifacts[];" in post_en
    assert "KIVOU_RECOVERY_POST_EN_SHA256=$(sha256sum" in post_en
    assert "KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST=$(jq -r" in commands
    assert "'.active_digests.fr'" in commands
    assert "KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST=${11}" in commands
    assert "KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST=${12}" in commands
    for fragment in (
        '"--expect-protected-language", "fr"',
        '"--expect-protected-active-publication-count",',
        'os.environ["KIVOU_EXPECTED_CANDIDATE_COUNT"]',
        '"--expect-protected-current-factual-artifact-digest"',
        'os.environ["KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST"]',
        '"--expect-protected-active-artifact-digest"',
        'os.environ["KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST"]',
    ):
        assert fragment in commands


def test_recovery_report_reseals_post_en_and_recaptures_exact_live_state() -> None:
    report = _logical_shell(
        _between(
            _body(),
            "## 10. Rapport de preuve",
            "Production : aucun déploiement, aucune mutation.",
        )
    )

    assert 'KIVOU_RECOVERY_POST_EN_SHA256=NOT_APPLICABLE' in report
    assert '"$KIVOU_RECOVERY_POST_EN"' in report
    assert (
        'test "$(sha256sum "$KIVOU_RECOVERY_POST_EN" | awk \'{print $1}\')" = '
        '"$KIVOU_RECOVERY_POST_EN_SHA256"'
    ) in report
    assert (
        'KIVOU_RECOVERY_FINAL_LIVE_PAYLOAD=$(kivou_capture_recovery_fr_snapshot '
        '"$KIVOU_RELEASE_DIR" post_en)'
    ) in report
    assert 'KIVOU_RECOVERY_FINAL_LIVE_SHA256=$(printf \'%s\\n\'' in report
    assert (
        'test "$KIVOU_RECOVERY_FINAL_LIVE_SHA256" = '
        '"$KIVOU_RECOVERY_POST_EN_SHA256"'
    ) in report
    assert "recovery_post_en_sha256=%s" in report


def test_post_en_digests_are_readonly_before_the_final_report() -> None:
    body = _body()
    logical = _logical_shell(body)
    readonly_line = (
        "readonly KIVOU_RECOVERY_POST_EN_SHA256 "
        "KIVOU_RECOVERY_POST_EN_FR_ARTIFACT_DIGEST "
        "KIVOU_RECOVERY_POST_EN_EN_ARTIFACT_DIGEST"
    )
    assert logical.count(readonly_line) == 1
    assert body.index("readonly KIVOU_RECOVERY_POST_EN_SHA256") < body.index(
        "## 10. Rapport de preuve"
    )

    harness = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\n"
            "KIVOU_RECOVERY_POST_EN_SHA256=$(printf a%.0s {1..64})\n"
            "KIVOU_RECOVERY_POST_EN_FR_ARTIFACT_DIGEST=$(printf b%.0s {1..64})\n"
            "KIVOU_RECOVERY_POST_EN_EN_ARTIFACT_DIGEST=$(printf c%.0s {1..64})\n"
            + readonly_line
            + "\n"
            "readonly -p | grep -q KIVOU_RECOVERY_POST_EN_SHA256\n"
            "KIVOU_RECOVERY_POST_EN_SHA256=mutable\n",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert harness.returncode != 0
    assert "KIVOU_RECOVERY_POST_EN_SHA256: readonly variable" in harness.stderr


def test_backfill_mode_and_remote_shells_are_executable_in_initial_and_recovery() -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)

    mode_prefix = 'case "$KIVOU_ROLLOUT_PATH" in\n'
    mode_suffix = "KIVOU_QA_SCOPE_SUMMARY="
    mode_block = mode_prefix + commands.split(mode_prefix, 1)[1].split(
        mode_suffix,
        1,
    )[0]
    initial = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\n"
            "KIVOU_ROLLOUT_PATH=initial_0027\n"
            + mode_block
            + 'test "$KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_CANDIDATE_COUNT" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_FR_ACTIVE_COUNT" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_FR_CURRENT_COUNT" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_FR_ACTIVE_DIGEST" = NOT_APPLICABLE\n'
            + 'test "$KIVOU_RECOVERY_FR_CURRENT_DIGEST" = NOT_APPLICABLE\n',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert initial.returncode == 0, initial.stderr

    baseline_digest = "a" * 64
    recovery = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\n"
            "KIVOU_ROLLOUT_PATH=resume_51202525\n"
            f"KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST={baseline_digest}\n"
            + mode_block
            + f'test "$KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST" = {baseline_digest}\n'
            + "printf '%s\\n' \"$KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST\" | "
            + "grep -Eq '^[0-9a-f]{64}$'\n"
            + 'test -z "$KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST"\n',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert recovery.returncode == 0, recovery.stderr

    assert commands.count("KIVOU_ROLLOUT_PATH=$6") == 2
    assert commands.count("KIVOU_EXPECTED_CANDIDATE_COUNT=$7") == 2
    assert commands.count("KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST=${10}") == 1
    assert commands.count("KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST=$8") == 1
    assert commands.count("KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST=${11}") == 1
    assert commands.count("KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST=$9") == 1
    assert commands.count("KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST=${12}") == 1
    assert commands.count("KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST=${10}") == 1
    assert commands.count("kivou_validate_recovery_summary() {") == 2
    assert commands.count(
        '--setenv="KIVOU_ROLLOUT_PATH=$KIVOU_ROLLOUT_PATH"'
    ) == 2
    assert commands.count(
        '--setenv="KIVOU_EXPECTED_CANDIDATE_COUNT=$KIVOU_EXPECTED_CANDIDATE_COUNT"'
    ) == 2
    assert commands.count(
        '--setenv="KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST=$KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST"'
    ) == 2
    assert commands.count(
        '--setenv="KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST=$KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST"'
    ) == 2
    assert commands.count(
        '--setenv="KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST=$KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST"'
    ) == 2
    assert commands.count("KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST=${11}") == 1
    assert commands.count("KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST=${12}") == 1
    assert commands.count(
        '--setenv="KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST=$KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST"'
    ) == 1
    assert commands.count(
        '--setenv="KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST=$KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST"'
    ) == 1

    remote_scripts = re.findall(
        r"<<'REMOTE'\n(.*?)^REMOTE$",
        section,
        flags=re.MULTILINE | re.DOTALL,
    )
    backfill_remotes = {
        language: next(
            script
            for script in remote_scripts
            if f"kivou-card-backfill-{language}-" in script
        )
        for language in ("fr", "en")
    }
    summaries = {
        "fr": (
            "scanned=17 published=12 unchanged=5 failed=0 "
            "next_offset=none scan_truncated=0"
        ),
        "en": (
            "scanned=17 published=17 unchanged=0 failed=0 "
            "next_offset=none scan_truncated=0"
        ),
    }
    for language, remote_script in backfill_remotes.items():
        preamble = remote_script.split("\nkivou_revalidate_qa_binding\n", 1)[0]
        for rollout_path in ("initial_0027", "resume_51202525"):
            if rollout_path == "initial_0027":
                recovery_arguments = ["NOT_APPLICABLE"] * 6
            elif language == "fr":
                recovery_arguments = ["17", "8", "5", "b" * 64, "c" * 64, "d" * 64]
            else:
                recovery_arguments = [
                    "17",
                    "b" * 64,
                    "e" * 64,
                    "e" * 64,
                    "c" * 64,
                    "c" * 64,
                ]
            harness = (
                preamble
                + "\n"
                + f"kivou_validate_recovery_summary {language} "
                + f"'{summaries[language]}'\n"
            )
            executed = subprocess.run(
                [
                    "bash",
                    "-c",
                    harness,
                    "runbook-harness",
                    "/srv/kivou/releases/backend-final",
                    "c" * 40,
                    "2026-08-31",
                    "d" * 16,
                    "50",
                    rollout_path,
                    *recovery_arguments,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            assert executed.returncode == 0, (
                language,
                rollout_path,
                executed.stderr,
            )


def test_every_qa_python_boundary_fails_with_only_an_opaque_error() -> None:
    qa_section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    scripts = _python_heredocs(qa_section)

    assert len(scripts) == 4
    for script in scripts:
        assert "def main() -> None:" in script
        assert "try:\n    main()\nexcept Exception:" in script
        assert re.search(r'print\("qa_[a-z_]+_failed", file=sys.stderr\)', script)
        assert "raise SystemExit(1)" in script
        assert "traceback" not in script.casefold()
        assert not re.search(r"(?m)^\s*raise\s*$", script)


def test_each_backfill_rebinds_approved_account_fingerprint_inside_unit() -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)
    scripts = _python_heredocs(section)
    backfills = tuple(script for script in scripts if "cli_main" in script)

    assert len(backfills) == 2
    for unit in ("kivou-card-backfill-fr-", "kivou-card-backfill-en-"):
        invocation = commands.split(unit, 1)[1].split("PY\n)", 1)[0]
        assert (
            '--setenv="KIVOU_QA_APPROVED_FINGERPRINT='
            '$KIVOU_QA_APPROVED_FINGERPRINT"'
            in invocation
        )
    assert '"$KIVOU_QA_APPROVED_FINGERPRINT" <<\'REMOTE\'' in commands
    assert commands.count("kivou_revalidate_qa_binding") >= 3
    for language, script in zip(("fr", "en"), backfills, strict=True):
        for fragment in (
            "file_descriptor = os.open(",
            "os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW",
            "qa_stat = os.fstat(file_descriptor)",
            'environment_account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]',
            "file_account_id",
            "hmac.compare_digest(file_account_id, environment_account_id)",
            'expected = os.environ["KIVOU_QA_APPROVED_FINGERPRINT"]',
            'hashlib.sha256(file_account_id.encode("utf-8")).hexdigest()[:16]',
            "hmac.compare_digest(actual, expected)",
            "exit_code = cli_main(arguments)",
            '"--account-id", file_account_id',
            '"--limit", os.environ["KIVOU_BACKFILL_LIMIT"]',
            '"--offset", "0"',
        ):
            assert fragment in script
        _assert_in_order(
            script,
            "file_descriptor = os.open(",
            "qa_stat = os.fstat(file_descriptor)",
            "hmac.compare_digest(file_account_id, environment_account_id)",
            "hmac.compare_digest(actual, expected)",
            "exit_code = cli_main(arguments)",
        )
        assert f'"--language", "{language}"' in script
        assert "print(account_id" not in script


def test_pre_backfill_browser_gate_matches_protected_session_to_db_scope() -> None:
    section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(section)
    scripts = _javascript_heredocs(section)

    assert len(scripts) == 1
    script = scripts[0]
    for fragment in (
        'KIVOU_QA_SCOPE_SUMMARY=$(ssh kivou-staging',
        'KIVOU_QA_STORAGE_STATE_REAL=$(readlink -f "$KIVOU_QA_STORAGE_STATE")',
        'test ! -L "$KIVOU_QA_STORAGE_STATE"',
        (
            'test "$(stat -c \'%U:%a\' "$KIVOU_QA_STORAGE_STATE")" = '
            '"$(id -un):600"'
        ),
        "const storageState = process.env.KIVOU_QA_STORAGE_STATE",
        "browser.newContext({ storageState })",
        "await page.goto(`${origin}/app/signals`",
        "await fetch('/me'",
        "crypto.subtle.digest('SHA-256'",
        "fingerprint !== expectedFingerprint",
        "`/signals?freshness=new&limit=20&offset=0`",
        "const readDate = process.env.KIVOU_QA_BROWSER_READ_DATE",
        "feed.read_at !== readDate",
        "feed.freshness !== 'new'",
        "feed.page?.limit !== 20",
        "feed.page.offset !== 0",
        "item.locked === false",
        'console.log("qa_browser_gate_ok")',
        'console.error("qa_browser_gate_failed")',
        "process.exitCode = 1",
    ):
        assert fragment in commands or fragment in script

    _assert_in_order(
        section,
        "qa_scope_ok fingerprint=",
        "KIVOU_QA_SCOPE_FINGERPRINT=",
        'test "$KIVOU_QA_SCOPE_FINGERPRINT" = "$KIVOU_QA_APPROVED_FINGERPRINT"',
        "qa_browser_gate_ok",
        '"--language", "fr"',
        '"--language", "en"',
    )
    assert "writeFile" not in script
    assert "copyFile" not in script
    assert "console.log(me.account_id)" not in script
    assert "console.error(error" not in script
    assert ".catch((error)" not in script
    syntax = subprocess.run(
        ["node", "--check"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_browser_smoke_is_executable_fail_closed_and_collects_two_viewports() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    commands = _commands(section)
    scripts = _javascript_heredocs(section)

    assert len(scripts) == 2
    script = scripts[0]
    for fragment in (
        "card-presentation-$KIVOU_FINAL_SHA",
        'install -m 700 -d "$KIVOU_BROWSER_EVIDENCE_DIR"',
        "storageState: process.env.KIVOU_QA_STORAGE_STATE",
        "{ name: 'desktop', width: 1440, height: 900 }",
        "{ name: 'mobile', width: 390, height: 844 }",
        "page.on('console'",
        "page.on('pageerror'",
        "page.on('requestfailed'",
        "page.on('response'",
        "response.status() >= 500",
        "await fetch('/me'",
        "crypto.subtle.digest('SHA-256'",
        "presentation_artifact_id",
        "detail.presentation.artifact_id !== artifact.artifact_id",
        "detail.presentation.version !== artifact.version",
        "Object.hasOwn(item, 'presentation')",
        "Object.hasOwn(item, 'company_key')",
        "await page.reload(",
        "await page.goBack(",
        "await page.goForward(",
        "document.activeElement",
        "scrollTop",
        "Retour aux attributions",
        "Retour aux signaux",
        "await page.screenshot",
        'console.log("card_current_smoke_ok")',
        'console.error("card_current_smoke_failed")',
        "process.exitCode = 1",
    ):
        assert fragment in commands or fragment in script
    assert "page.getByRole('link', { name: /attribution|award/i })" in script

    for route in ("/app/dashboard", "/app/companies", "/app/signals"):
        assert route in script
    assert "errors.length === 0" in script
    assert "browser.close()" in script
    assert "inspection visuelle humaine" in section
    assert "STOP" in section.split("inspection visuelle humaine", 1)[1]
    syntax = subprocess.run(
        ["node", "--check"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_current_proofs_complete_before_optional_history_gate_or_stop() -> None:
    body = _body()
    qa_section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    section = _between(
        body,
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    scripts = _javascript_heredocs(section)
    assert len(scripts) == 2
    current_script, historical_script = scripts

    for fragment in (
        '"status": "NOT_APPLICABLE_NO_LEGITIMATE_HISTORY"',
        '"status": "available"',
        "KIVOU_HISTORICAL_STATUS=",
        "SET TRANSACTION READ ONLY",
        "old.superseded_at IS NOT NULL",
        "current.superseded_at IS NULL",
        "current.input_fingerprint=old.input_fingerprint",
        "signal.revision=old.signal_revision",
        "icp.matching_revision=old.target_icp_revision",
    ):
        assert fragment in qa_section
    assert "assert historical is not None" not in qa_section
    historical_gate = qa_section.split("Un historique n'est jamais fabriqué", 1)[1]
    assert "INSERT " not in historical_gate
    assert "UPDATE " not in historical_gate
    assert "historical" not in current_script.casefold()

    _assert_in_order(
        section,
        'console.log("card_current_smoke_ok")',
        'printf "%s\\n" "card_get_journal_ok"',
        "inspection visuelle humaine",
        'test "$KIVOU_FINAL_REVISION" = "0028_card_presentation"',
        'case "$KIVOU_HISTORICAL_STATUS" in',
        "(NOT_APPLICABLE_NO_LEGITIMATE_HISTORY)",
        "KIVOU_ROLLOUT_STATUS=PASS",
        'console.log("card_historical_browser_ok")',
        'printf \'%s\\n\' "card_historical_smoke_ok"',
    )
    assert 'process.exitCode = 1' in current_script
    assert 'process.exitCode = 1' in historical_script


def test_no_legitimate_history_is_not_applicable_and_allows_global_pass() -> None:
    body = _body()
    smoke_section = _between(
        body,
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    history_commands = _commands(smoke_section).split(
        'case "$KIVOU_HISTORICAL_STATUS" in', 1
    )[1]
    not_applicable_branch = history_commands.split(
        "(NOT_APPLICABLE_NO_LEGITIMATE_HISTORY)", 1
    )[1].split(
        "(available)", 1
    )[0]
    available_branch = history_commands.split("(available)", 1)[1].split(
        "\n  (*)", 1
    )[0]

    for fragment in (
        "KIVOU_HISTORICAL_SMOKE_STATUS=NOT_APPLICABLE_NO_LEGITIMATE_HISTORY",
        "KIVOU_ROLLOUT_STATUS=PASS",
        "historical_smoke=NOT_APPLICABLE_NO_LEGITIMATE_HISTORY",
    ):
        assert fragment in not_applicable_branch
    assert not re.search(r"\b(?:exit|return|kill|unset)\b", not_applicable_branch)
    assert "node <<'JS'" not in not_applicable_branch

    _assert_in_order(
        available_branch,
        "KIVOU_HISTORICAL_ARTIFACT_VERSION",
        "node <<'JS'",
        'console.log("card_historical_browser_ok")',
        "kivou_audit_card_get_journal",
        'printf \'%s\\n\' "card_historical_smoke_ok"',
        "KIVOU_HISTORICAL_SMOKE_STATUS=PASS",
        "KIVOU_ROLLOUT_STATUS=PASS",
    )
    after_case = history_commands.split("esac", 1)[1]
    assert "export KIVOU_HISTORICAL_SMOKE_STATUS KIVOU_ROLLOUT_STATUS" in after_case

    report = body.split("## 10. Rapport de preuve", 1)[1]
    for fragment in (
        'case "$KIVOU_HISTORICAL_SMOKE_STATUS:$KIVOU_ROLLOUT_STATUS" in',
        "PASS:PASS",
        "NOT_APPLICABLE_NO_LEGITIMATE_HISTORY:PASS",
        "historical_smoke_status=%s rollout_status=%s",
        "aucun artefact supersédé légitime",
        "ne jamais fabriquer",
    ):
        assert fragment in report
    _assert_in_order(
        body,
        "KIVOU_HISTORICAL_SMOKE_STATUS=NOT_APPLICABLE_NO_LEGITIMATE_HISTORY",
        "## 9. Rollback applicatif",
        "## 10. Rapport de preuve",
        "historical_smoke_status=%s rollout_status=%s",
    )


def test_c003_never_selects_outside_exact_ui_first_page() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    current_script = _javascript_heredocs(section)[0]
    api_guard = current_script.split("async function verifyPublishedApi", 1)[1].split(
        "\nfunction installFailureCollectors", 1
    )[0]
    api_function = "async function verifyPublishedApi" + api_guard
    harness = r"""
const readDate = '2026-08-31'
const firstPagePath = '/signals?freshness=new&limit=20&offset=0'
const requests = []
global.fetch = async (path, options) => {
  requests.push(path)
  if (options?.credentials !== 'same-origin' || path !== firstPagePath) {
    return { status: 404 }
  }
  return {
    status: 200,
    json: async () => ({
      read_at: readDate,
      freshness: 'new',
      page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
      items: Array.from({ length: 20 }, (_, index) => ({
        signal_id: index.toString(16).padStart(64, '0'),
        locked: true,
        headline: `Locked ${index}`,
      })),
    }),
  }
}
const page = { evaluate: async (fn, argument) => fn(argument) }
verifyPublishedApi(page, readDate).then(
  () => process.exit(42),
  () => process.exit(
    requests.length === 1 && requests[0] === firstPagePath ? 0 : 43,
  ),
)
"""
    executed = subprocess.run(
        ["node"],
        input=api_function + harness,
        text=True,
        capture_output=True,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr
    assert "`/signals?freshness=new&limit=20&offset=0`" in api_guard
    assert "feed.read_at !== readDate" in api_guard
    assert "feed.freshness !== 'new'" in api_guard
    assert "feed.page?.limit !== 20" in api_guard
    assert "feed.page.offset !== 0" in api_guard
    assert "limit=50" not in api_guard
    assert "offset=20" not in api_guard
    assert "process.env.KIVOU_QA_BROWSER_READ_DATE" in current_script
    assert "process.env.KIVOU_BACKFILL_AS_OF" not in current_script


def test_c003_selects_ordered_row_when_headlines_are_duplicated() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    current_script = _javascript_heredocs(section)[0]
    api_guard = current_script.split("async function verifyPublishedApi", 1)[1].split(
        "\nfunction installFailureCollectors", 1
    )[0]
    api_function = "async function verifyPublishedApi" + api_guard
    harness = r"""
const readDate = '2026-08-31'
const feedPath = '/signals?freshness=new&limit=20&offset=0'
const lockedId = 'a'.repeat(64)
const firstId = 'b'.repeat(64)
const secondId = 'c'.repeat(64)
const firstArtifactId = 'd'.repeat(64)
const secondArtifactId = 'e'.repeat(64)
const headline = 'Same factual headline'
const presentation = (artifactId) => ({
  artifact_id: artifactId,
  version: 1,
  status: 'FALLBACK',
  content: {
    headline,
    variant: 'FACTUAL_FALLBACK',
    claims: [{ evidence_refs: ['source:1'] }],
  },
})
const firstPresentation = presentation(firstArtifactId)
const requests = []
global.fetch = async (path, options) => {
  requests.push(path)
  if (options?.credentials !== 'same-origin') return { status: 401 }
  if (path === feedPath) return {
    status: 200,
    json: async () => ({
      read_at: readDate,
      freshness: 'new',
      page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
      items: [
        { signal_id: lockedId, locked: true, headline: 'Locked' },
        { signal_id: firstId, locked: false, presentation: firstPresentation },
        { signal_id: secondId, locked: false, presentation: presentation(secondArtifactId) },
      ],
    }),
  }
  if (path === `/signals/${firstId}?presentation_artifact_id=${firstArtifactId}`) {
    return {
      status: 200,
      json: async () => ({ signal_id: firstId, presentation: firstPresentation }),
    }
  }
  return { status: 404 }
}
const page = { evaluate: async (fn, argument) => fn(argument) }
verifyPublishedApi(page, readDate).then(
  (result) => process.exit(
    result.pinnedIndex === 1 && result.pinnedSignalId === firstId &&
    result.pinnedHeadline === headline && requests.length === 2 ? 0 : 43,
  ),
  () => process.exit(44),
)
"""
    executed = subprocess.run(
        ["node"],
        input=api_function + harness,
        text=True,
        capture_output=True,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr
    for fragment in (
        "const pinnedIndex = feed.items.findIndex",
        "pinnedIndex,",
        "page.locator('.signal-list .signal-item').nth(api.pinnedIndex)",
        "selection.getByText(api.pinnedHeadline, { exact: true })",
        "await selectedHeadline.count() === 1",
    ):
        assert fragment in current_script
    assert ".filter({ hasText: api.pinnedHeadline })" not in current_script


def test_c003_rejects_detail_headline_drift_and_checks_visible_detail_pane() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    current_script = _javascript_heredocs(section)[0]
    api_guard = current_script.split("async function verifyPublishedApi", 1)[1].split(
        "\nfunction installFailureCollectors", 1
    )[0]
    api_function = "async function verifyPublishedApi" + api_guard
    harness = r"""
const readDate = '2026-08-31'
const feedPath = '/signals?freshness=new&limit=20&offset=0'
const signalId = 'a'.repeat(64)
const lockedId = 'b'.repeat(64)
const artifactId = 'c'.repeat(64)
const feedHeadline = 'Same factual headline'
const feedPresentation = {
  artifact_id: artifactId,
  version: 1,
  status: 'FALLBACK',
  content: {
    headline: feedHeadline,
    variant: 'FACTUAL_FALLBACK',
    claims: [{ evidence_refs: ['source:1'] }],
  },
}
global.fetch = async (path, options) => {
  if (options?.credentials !== 'same-origin') return { status: 401 }
  if (path === feedPath) return {
    status: 200,
    json: async () => ({
      read_at: readDate,
      freshness: 'new',
      page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
      items: [
        { signal_id: signalId, locked: false, presentation: feedPresentation },
        { signal_id: lockedId, locked: true, headline: 'Locked signal' },
      ],
    }),
  }
  if (path === `/signals/${signalId}?presentation_artifact_id=${artifactId}`) {
    return {
      status: 200,
      json: async () => ({
        signal_id: signalId,
        presentation: {
          ...feedPresentation,
          content: { ...feedPresentation.content, headline: 'DIFFERENT DETAIL HEADLINE' },
        },
      }),
    }
  }
  return { status: 404 }
}
const page = { evaluate: async (fn, argument) => fn(argument) }
verifyPublishedApi(page, readDate).then(
  () => process.exit(42),
  () => process.exit(0),
)
"""
    executed = subprocess.run(
        ["node"],
        input=api_function + harness,
        text=True,
        capture_output=True,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr
    assert (
        "detail.presentation.content?.headline !== artifact.content.headline"
        in api_guard
    )
    for fragment in (
        "const visibleDetailPane = page.locator(",
        '`[data-master-detail-pane="detail"]:visible`',
        "const detailHeadline = visibleDetailPane.getByRole('heading', {",
        "name: api.pinnedHeadline, exact: true,",
        "await detailHeadline.count() === 1",
        "await detailHeadline.waitFor()",
    ):
        assert fragment in current_script
    assert "page.getByText(api.pinnedHeadline, { exact: true }).first()" not in (
        current_script
    )


def test_current_and_optional_historical_signal_smokes_pin_exact_artifacts() -> None:
    body = _body()
    section = _between(
        body,
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    commands = _commands(section)
    current_script, historical_script = _javascript_heredocs(section)

    for fragment in (
        "KIVOU_HISTORICAL_SIGNAL_ID",
        "KIVOU_HISTORICAL_ARTIFACT_ID",
        "KIVOU_HISTORICAL_ARTIFACT_VERSION",
        "pinnedSignalId: item.signal_id",
        "pinnedIndex,",
        "pinnedHeadline:",
        "page.locator('.signal-list .signal-item').nth(api.pinnedIndex)",
        "selection.getByText(api.pinnedHeadline, { exact: true })",
        "url.pathname === `/app/signals/${encodeURIComponent(api.pinnedSignalId)}`",
        "selected.searchParams.get('presentation_artifact_id') === api.pinnedArtifactId",
        "const expectedDetailPath =",
        "path === expectedDetailPath",
        "const expectedNotePath =",
        "method === 'GET' && path === expectedNotePath",
        "responses.slice(selectionResponseStart)",
        "status === 200 && path === expectedNotePath",
        "method !== 'GET' && /\\/signals\\/[^/]+\\/note",
        "!requests.some(({ method }) => !['GET', 'HEAD'].includes(method))",
        "visibleDetailPane.getByRole('heading', {",
        "name: api.pinnedHeadline, exact: true,",
    ):
        assert fragment in commands or fragment in current_script

    assert "searchParams.get('presentation')" not in current_script
    _assert_in_order(
        current_script,
        "pinnedSignalId: item.signal_id",
        "page.locator('.signal-list .signal-item').nth(api.pinnedIndex)",
        "path === expectedDetailPath",
        "method === 'GET' && path === expectedNotePath",
    )
    for fragment in (
        "historicalSignalId",
        "historicalArtifactId",
        "historicalArtifactVersion",
        "detail.presentation.artifact_id !== artifactId",
        "detail.presentation.version !== artifactVersion",
        "historicalDetail.presentation.content.headline",
        "historicalUrl.searchParams.set('presentation_artifact_id', historicalArtifactId)",
        "url.searchParams.get('presentation_artifact_id') === historicalArtifactId",
        "const historicalDetailResponsePromise = waitForExactGetResponse(",
        "const historicalNoteResponsePromise = waitForExactGetResponse(",
        "historicalDetailResponse.status() === 200",
        "historicalNoteResponse.status() === 200",
        '`[data-master-detail-pane="detail"]:visible`',
        "await headline.count() === 1",
    ):
        assert fragment in historical_script
    assert "searchParams.get('presentation')" not in historical_script


def test_signal_detail_and_note_waiters_are_armed_before_navigation() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    current_script, historical_script = _javascript_heredocs(section)
    helper = current_script.split("function waitForExactGetResponse", 1)[1].split(
        "\n}\n", 1
    )[0]
    smoke = current_script.split("async function smokeSignals", 1)[1].split(
        "\n}\n", 1
    )[0]

    for fragment in (
        "page.waitForResponse",
        "response.request().method() === 'GET'",
        "url.origin === origin",
        "`${url.pathname}${url.search}` === expectedPath",
    ):
        assert fragment in helper

    _assert_in_order(
        smoke,
        "const expectedDetailPath =",
        "const expectedNotePath =",
        "const currentDetailResponsePromise = waitForExactGetResponse(",
        "const currentNoteResponsePromise = waitForExactGetResponse(",
        "await selection.evaluate((element) => element.click())",
        "const [currentDetailResponse, currentNoteResponse] = await Promise.all([",
        "currentDetailResponse.status() === 200",
        "currentNoteResponse.status() === 200",
    )
    _assert_in_order(
        historical_script,
        "const expectedHistoricalDetailPath =",
        "const expectedHistoricalNotePath =",
        "const historicalDetailResponsePromise = waitForExactGetResponse(",
        "const historicalNoteResponsePromise = waitForExactGetResponse(",
        "await page.goto(historicalUrl.toString()",
        "const [historicalDetailResponse, historicalNoteResponse] = await Promise.all([",
        "historicalDetailResponse.status() === 200",
        "historicalNoteResponse.status() === 200",
    )


def test_locked_teaser_is_unique_presentation_free_and_forbids_any_detail_get() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    current_script = _javascript_heredocs(section)[0]
    api_guard = current_script.split("async function verifyPublishedApi", 1)[1].split(
        "\nfunction installFailureCollectors", 1
    )[0]
    smoke = current_script.split("async function smokeSignals", 1)[1].split(
        "\n}\n", 1
    )[0]

    assert "`.signal-item.is-locked`" in section
    for fragment in (
        "const signalIds = feed.items.map((item) => item?.signal_id)",
        "signalIds.some((signalId) => (",
        "new Set(signalIds).size !== signalIds.length",
    ):
        assert fragment in api_guard
    _assert_in_order(
        current_script,
        "const signalIds = feed.items.map((item) => item?.signal_id)",
        "new Set(signalIds).size !== signalIds.length",
        "lockedSignalId: locked[0].signal_id",
        "async function smokeSignals",
        "page.locator('.signal-list .signal-item.is-locked')",
        "await lockedBinding.count() === 1",
    )
    api_function = "async function verifyPublishedApi" + api_guard
    uniqueness_guard = " || new Set(signalIds).size !== signalIds.length"
    assert api_function.count(uniqueness_guard) == 1
    mutant_api_function = api_function.replace(uniqueness_guard, "", 1)
    duplicate_payload_harness = """
const duplicateId = 'a'.repeat(64)
const artifactId = 'b'.repeat(64)
const asOf = '2026-08-31'
const artifact = {
  artifact_id: artifactId,
  version: 1,
  status: 'FALLBACK',
  content: {
    headline: 'Factual published signal',
    variant: 'FACTUAL_FALLBACK',
    claims: [{ evidence_refs: ['source:1'] }],
  },
}
const feedPath = '/signals?freshness=new&limit=20&offset=0'
const detailPath =
  `/signals/${duplicateId}?presentation_artifact_id=${artifactId}`
const requests = []
global.fetch = async (path, options) => {
  requests.push(path)
  if (options?.credentials !== 'same-origin') return { status: 401 }
  if (path === feedPath) {
    return {
      status: 200,
          json: async () => ({
            read_at: asOf,
            freshness: 'new',
            page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
            items: [
          { signal_id: duplicateId, locked: false, presentation: artifact },
          { signal_id: duplicateId, locked: true, headline: 'Locked signal' },
        ],
      }),
    }
  }
  if (path === detailPath) {
    return {
      status: 200,
      json: async () => ({ signal_id: duplicateId, presentation: artifact }),
    }
  }
  return { status: 404 }
}
const page = { evaluate: async (fn, argument) => fn(argument) }
verifyPublishedApi(page, asOf).then(
  (result) => {
    if (requests.length !== 2 ||
        requests[0] !== feedPath || requests[1] !== detailPath ||
        result.lockedSignalId !== duplicateId ||
        result.pinnedSignalId !== duplicateId ||
        result.pinnedArtifactId !== artifactId || result.pinnedVersion !== 1 ||
        result.pinnedHeadline !== artifact.content.headline) process.exit(43)
    process.exit(42)
  },
  () => process.exit(0),
)
"""
    def run_duplicate_payload_check(api_source: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node"],
            input=api_source + duplicate_payload_harness,
            text=True,
            capture_output=True,
            check=False,
        )

    mutant_check = run_duplicate_payload_check(mutant_api_function)
    assert mutant_check.returncode == 42, mutant_check.stderr
    real_check = run_duplicate_payload_check(api_function)
    assert real_check.returncode == 0, real_check.stderr
    for fragment in (
        "page.locator('.signal-list .signal-item.is-locked')",
        "await lockedBinding.count() === 1",
        "const lockedControl = lockedBinding",
        "element.tagName === 'BUTTON' || element.tagName === 'A'",
        "lockedControl.getByText(api.lockedHeadline, { exact: true })",
        "await lockedText.count() === 1",
        "!element.outerHTML.includes('presentation')",
        "!element.outerHTML.includes('company_key')",
        "!element.querySelector('a[href^=\"/app/companies/\"]')",
        "const lockedRequestStart = requests.length",
        "await lockedControl.click()",
        "await page.waitForURL(/\\/app\\/billing",
        "await page.waitForLoadState('networkidle')",
        "requests.slice(lockedRequestStart)",
        "method === 'GET'",
        "/^\\/signals\\/[^/?]+(?:\\/note)?(?:\\?|$)/.test(path)",
    ):
        assert fragment in smoke
    assert "data-signal-id" not in smoke
    assert "getByText(api.lockedHeadline, { exact: true }).first()" not in smoke
    _assert_in_order(
        smoke,
        "await lockedBinding.count() === 1",
        "const lockedControl = lockedBinding",
        "element.tagName === 'BUTTON' || element.tagName === 'A'",
        "const lockedRequestStart = requests.length",
        "await lockedControl.click()",
        "await page.waitForURL(/\\/app\\/billing",
        "await page.waitForLoadState('networkidle')",
        "requests.slice(lockedRequestStart)",
    )


def test_qa_signal_scope_uses_only_plan_limit_code_authority() -> None:
    body = _body()
    qa_section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )

    assert "plan_limited_at" not in body
    assert qa_section.count("plan_limit_code IS NULL") >= 3


def test_scroll_contract_mutates_and_restores_nonzero_positions() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    script = _javascript_heredocs(section)[0]

    assert "Number.isFinite(scrollTop)" not in script
    for fragment in (
        "async function setScrollContract",
        "async function expectScrollContractRestored",
        "element.scrollTop = target",
        "element.scrollTop > 0",
        "Math.abs(actual - expected.position)",
        "companyListScroll",
        "companyDetailScroll",
        "signalListScroll",
        "signalDetailScroll",
    ):
        assert fragment in script
    for function_name in ("smokeCompanies", "smokeSignals"):
        function = script.split(f"async function {function_name}", 1)[1].split(
            "\n}\n", 1
        )[0]
        _assert_in_order(
            function,
            "setScrollContract",
            "await page.goBack(",
            "expectScrollContractRestored",
            "await page.goForward(",
            "expectScrollContractRestored",
            "await page.reload(",
            "expectScrollContractRestored",
        )


def test_scroll_contract_targets_named_master_detail_panes_by_phase() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    script = _javascript_heredocs(section)[0]
    companies = script.split("async function smokeCompanies", 1)[1].split(
        "\n}\n", 1
    )[0]
    signals = script.split("async function smokeSignals", 1)[1].split(
        "\n}\n", 1
    )[0]

    assert "data-master-detail-pane" in section
    assert "page.locator('main *').evaluateAll" not in script
    for fragment in (
        "pane === 'list' || pane === 'detail'",
        "typeof phase === 'string' && phase.length > 0",
        '`[data-master-detail-pane="${pane}"]:visible`',
        "await locator.count() === 1",
        "if (viewport.name === 'mobile')",
        "const otherPane = pane === 'list' ? 'detail' : 'list'",
        '`[data-master-detail-pane="${otherPane}"]:visible`',
        "await otherLocator.count() === 0",
        "overflow === 'auto' || overflow === 'scroll'",
    ):
        assert fragment in script

    company_before_selection, company_after_selection = companies.split(
        "await award.evaluate((element) => element.click())", 1
    )
    assert (
        "setScrollContract(page, viewport, 'list', 'companies-initial-list')"
        in company_before_selection
    )
    assert "setScrollContract(page, 'detail'" not in company_before_selection
    _assert_in_order(
        company_after_selection,
        "if (viewport.name === 'desktop')",
        "setScrollContract(page, viewport, 'list', 'companies-selected-list')",
        "setScrollContract(page, viewport, 'detail', 'companies-selected-detail')",
        "companyListScroll.panePath !== companyDetailScroll.panePath",
    )

    signal_before_selection, signal_after_selection = signals.split(
        "await selection.evaluate((element) => element.click())", 1
    )
    assert (
        "setScrollContract(page, viewport, 'list', 'signals-initial-list')"
        in signal_before_selection
    )
    assert "setScrollContract(page, 'detail'" not in signal_before_selection
    _assert_in_order(
        signal_after_selection,
        "if (viewport.name === 'desktop')",
        "setScrollContract(page, viewport, 'list', 'signals-selected-list')",
        "setScrollContract(page, viewport, 'detail', 'signals-selected-detail')",
        "signalListScroll.panePath !== signalDetailScroll.panePath",
    )


def test_smoke_journal_boundary_and_card_worker_inventory_are_fail_closed() -> None:
    section = _between(
        _body(),
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    commands = _commands(section)
    logical = _logical_shell(section)

    for fragment in (
        "KIVOU_CARD_JOURNAL_CURSOR=",
        "KIVOU_CARD_JOURNAL_SINCE=",
        "journalctl -u kivou-api.service -n 0 --show-cursor",
        'journalctl -u kivou-api.service --after-cursor "$KIVOU_CARD_JOURNAL_CURSOR"',
        "kivou_assert_no_card_ai_runtime",
        "systemctl list-unit-files",
        "systemctl list-units",
        "/etc/kivou/staging.env",
        "KIVOU_CARD_(AI|INTELLIGENCE|GENERATION|GENERATOR|PROVIDER|QA_PROVIDER|WORKER)",
        "Traceback|unhandled|exception",
        "card[_ -]?(generation|provider|qa[_ -]?worker)",
        'printf "%s\\n" "card_get_journal_ok"',
    ):
        assert fragment in logical

    assert "journalctl -u kivou-acquisition" not in commands
    assert 'printf "%s\\n" "$KIVOU_CARD_GET_JOURNAL"' not in commands
    _assert_in_order(
        logical,
        "kivou_assert_no_card_ai_runtime",
        "journalctl -u kivou-api.service -n 0 --show-cursor",
        "KIVOU_QA_ORIGIN=https://staging.kivou.eu node <<'JS'",
        'journalctl -u kivou-api.service --after-cursor "$KIVOU_CARD_JOURNAL_CURSOR"',
        "kivou_assert_no_card_ai_runtime",
        'printf "%s\\n" "card_get_journal_ok"',
    )


def test_smoke_and_rollback_contract_retain_additive_migration() -> None:
    body = _body()

    for fragment in (
        "1440×900",
        "390×844",
        "Dashboard",
        "Entreprises",
        "Signaux",
        "desktop",
        "mobile",
        "deep-link",
        "Retour",
        "Back",
        "Forward",
        "focus",
        "scroll",
        "teaser verrouillé",
        "presentation",
        "console",
        "pageerror",
        "requestfailed",
        "date de publication comme date d’attribution",
        "Matériaux → personnel",
        "personne ni urgence inventée",
        "company_key",
        "application-only rollback",
        "ne pas exécuter de downgrade",
        "0028_card_presentation",
    ):
        assert fragment in body

    rollback = body.split("## 9. Rollback applicatif", 1)[1]
    assert "alembic downgrade" not in rollback
    assert "/srv/kivou/frontend" in rollback
    assert "/srv/kivou/app" in rollback

    smoke = body.split("## 8. Smoke navigateur desktop et mobile", 1)[1].split(
        "## 9. Rollback applicatif", 1
    )[0]
    for fragment in (
        'assert revision == "0028_card_presentation", revision',
        "KIVOU_FINAL_ASSET_PATH",
        "http://127.0.0.1:8000/me",
        '"$KIVOU_FINAL_ASSET_PATH"',
    ):
        assert fragment in smoke

    assert "Production : aucun déploiement, aucune mutation." in body


def test_cleanup_and_mutation_commands_are_narrow_and_staging_only() -> None:
    body = _body()
    commands = _commands(body)

    assert "rm -rf" not in body
    assert "DROP TABLE" not in body
    assert "DELETE FROM" not in body
    assert "UPDATE " not in commands
    assert "kivou-production" not in body
    direct_ssh_targets = re.findall(r"(?m)^\s*ssh\s+([^\s]+)", commands)
    assert direct_ssh_targets
    assert set(direct_ssh_targets) == {"kivou-staging"}
    for forbidden in ("Hermes", "openai", "anthropic", "ollama"):
        assert forbidden.casefold() not in commands.casefold()
    assert not re.search(r"systemctl\s+(?:start|enable).*kivou-card", commands)
    assert not re.search(
        r"python[^\n]*(?:generate|provider|worker)", commands, re.IGNORECASE
    )

    destructive_lines = tuple(
        line.strip()
        for line in commands.splitlines()
        if re.search(r"\b(?:dropdb|find .* -delete|rmdir)\b", line)
    )
    assert destructive_lines
    for line in destructive_lines:
        assert (
            "KIVOU_RESTORE_DB" in line
            or "KIVOU_FRONTEND_BUILD_REAL" in line
            or "KIVOU_FRONTEND_SWITCH_DIR_REAL" in line
            or "KIVOU_FRONTEND_ROLLBACK_DIR_REAL" in line
        ), line
    assert commands.count('case "$KIVOU_RESTORE_DB" in') >= 2
    assert commands.count('case "$KIVOU_FRONTEND_BUILD_REAL" in') >= 2
    assert commands.count('case "$KIVOU_FRONTEND_SWITCH_DIR_REAL" in') >= 2
    assert commands.count('case "$KIVOU_FRONTEND_ROLLBACK_DIR_REAL" in') >= 2


def test_ops_readme_points_to_the_single_versioned_staging_rollout() -> None:
    body = OPERATIONS.read_text(encoding="utf-8")

    assert body.count("../docs/runbooks/11-staging-card-presentation-rollout.md") == 1
    assert "Card Intelligence × QA Signals" in body
