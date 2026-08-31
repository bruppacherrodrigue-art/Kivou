from __future__ import annotations

import json
import re
import subprocess
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


def test_preflight_captures_both_releases_and_requires_exact_0027() -> None:
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
        'assert revision == "0027_signal_notes", revision',
        "kivou-backup.timer",
        "http://127.0.0.1:8000/openapi.json",
    ):
        assert fragment in commands

    assert "source /etc/kivou/staging.env" not in commands
    assert "cat /etc/kivou/staging.env" not in commands


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
    assert commands.count("psql -X -qAt") == 2
    assert commands.count("--set=ON_ERROR_STOP=1") == 2
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
            '--setenv="KIVOU_QA_DB_FINGERPRINT=$KIVOU_QA_DB_FINGERPRINT"'
            in invocation
        )
    assert '"$KIVOU_QA_DB_FINGERPRINT" <<\'REMOTE\'' in commands
    assert commands.count("kivou_revalidate_qa_binding") >= 3
    for language, script in zip(("fr", "en"), backfills, strict=True):
        for fragment in (
            "file_descriptor = os.open(",
            "os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW",
            "qa_stat = os.fstat(file_descriptor)",
            'environment_account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]',
            "file_account_id",
            "hmac.compare_digest(file_account_id, environment_account_id)",
            'expected = os.environ["KIVOU_QA_DB_FINGERPRINT"]',
            'hashlib.sha256(file_account_id.encode("utf-8")).hexdigest()[:16]',
            "hmac.compare_digest(actual, expected)",
            "cli_main([",
            '"--account-id", file_account_id',
            '"--limit", "50"',
            '"--offset", "0"',
        ):
            assert fragment in script
        _assert_in_order(
            script,
            "file_descriptor = os.open(",
            "qa_stat = os.fstat(file_descriptor)",
            "hmac.compare_digest(file_account_id, environment_account_id)",
            "hmac.compare_digest(actual, expected)",
            "cli_main([",
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
        "`/signals?as_of=${encodeURIComponent(asOf)}&limit=50&offset=0`",
        "item.locked === false",
        'console.log("qa_browser_gate_ok")',
        'console.error("qa_browser_gate_failed")',
        "process.exitCode = 1",
    ):
        assert fragment in commands or fragment in script

    _assert_in_order(
        section,
        "qa_scope_ok fingerprint=",
        "KIVOU_QA_DB_FINGERPRINT=",
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
        '"status": "absent"',
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
        "(absent)",
        "STOP / NON-EXÉCUTABLE",
        "validation propriétaire",
        'console.log("card_historical_browser_ok")',
        'printf \'%s\\n\' "card_historical_smoke_ok"',
    )
    assert 'process.exitCode = 1' in current_script
    assert 'process.exitCode = 1' in historical_script


def test_absent_history_records_nonfatal_stop_and_reaches_rollback_report() -> None:
    body = _body()
    smoke_section = _between(
        body,
        "## 8. Smoke navigateur desktop et mobile",
        "## 9. Rollback applicatif",
    )
    history_commands = _commands(smoke_section).split(
        'case "$KIVOU_HISTORICAL_STATUS" in', 1
    )[1]
    absent_branch = history_commands.split("(absent)", 1)[1].split(
        "(available)", 1
    )[0]
    available_branch = history_commands.split("(available)", 1)[1].split(
        "\n  (*)", 1
    )[0]

    for fragment in (
        "KIVOU_HISTORICAL_SMOKE_STATUS=STOP_NON_EXECUTABLE",
        "KIVOU_ROLLOUT_STATUS=STOP_INCOMPLETE",
        "STOP / NON-EXÉCUTABLE",
        "validation propriétaire",
    ):
        assert fragment in absent_branch
    assert not re.search(r"\b(?:exit|return|kill|unset)\b", absent_branch)
    assert "node <<'JS'" not in absent_branch

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
        "STOP_NON_EXECUTABLE:STOP_INCOMPLETE",
        "historical_smoke_status=%s rollout_status=%s",
        "interdite",
        "KIVOU_HISTORICAL_SMOKE_STATUS != PASS",
    ):
        assert fragment in report
    _assert_in_order(
        body,
        "KIVOU_HISTORICAL_SMOKE_STATUS=STOP_NON_EXECUTABLE",
        "## 9. Rollback applicatif",
        "## 10. Rapport de preuve",
        "historical_smoke_status=%s rollout_status=%s",
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
        "pinnedHeadline:",
        ".signal-item:not(.is-locked)",
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
        "page.getByText(api.pinnedHeadline, { exact: true })",
    ):
        assert fragment in commands or fragment in current_script

    assert "searchParams.get('presentation')" not in current_script
    _assert_in_order(
        current_script,
        "pinnedSignalId: item.signal_id",
        ".signal-item:not(.is-locked)",
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
const asOf = '2026-08-31T00:00:00Z'
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
const feedPath = `/signals?as_of=${encodeURIComponent(asOf)}&limit=50&offset=0`
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
