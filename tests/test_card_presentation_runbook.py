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
    suffix = '\' "$KIVOU_CI_JSON" >/dev/null'
    assert body.count(prefix) == 1
    assert body.count(suffix) == 1
    return body.split(prefix, 1)[1].split(suffix, 1)[0]


def _embedded_awk_after(commands: str, anchor: str) -> str:
    prefix = f'{anchor} | awk \'\n'
    suffix = "\n  '"
    assert commands.count(prefix) == 1
    return commands.split(prefix, 1)[1].split(suffix, 1)[0]


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
    ):
        assert fragment in commands

    assert 'printf \'%s\\n\' "$KIVOU_ROLLOUT_STATE_CONTENT"' not in commands
    assert 'echo "$KIVOU_ROLLOUT_STATE_CONTENT"' not in commands


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


def test_qa_gate_precedes_separate_bounded_fr_en_factual_backfills() -> None:
    body = _body()
    qa_section = _between(
        body,
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    commands = _commands(qa_section)

    for fragment in (
        "/etc/kivou/card-presentation-qa.env",
        "root:kivou:640",
        "KIVOU_CARD_QA_ACCOUNT_ID",
        "ne crée pas ce fichier",
        "ne déduit jamais le compte",
        "--language fr --limit 50 --offset 0",
        "--language en --limit 50 --offset 0",
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
        "--language fr --limit 50 --offset 0",
        "--language en --limit 50 --offset 0",
        "provider IS NULL",
    )
    assert commands.count("python -m signals.card_intelligence backfill-fallbacks") == 2


def test_every_qa_python_boundary_fails_with_only_an_opaque_error() -> None:
    qa_section = _between(
        _body(),
        "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        "## 8. Smoke navigateur desktop et mobile",
    )
    scripts = _python_heredocs(qa_section)

    assert len(scripts) == 2
    for script in scripts:
        assert "def main() -> None:" in script
        assert "try:\n    main()\nexcept Exception:" in script
        assert re.search(r'print\("qa_[a-z_]+_failed", file=sys.stderr\)', script)
        assert "raise SystemExit(1)" in script
        assert "traceback" not in script.casefold()
        assert not re.search(r"(?m)^\s*raise\s*$", script)


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
        "--language fr --limit 50 --offset 0",
        "--language en --limit 50 --offset 0",
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

    assert len(scripts) == 1
    script = scripts[0]
    for fragment in (
        "card-presentation-$KIVOU_FINAL_SHORT",
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
        "Retour aux entreprises",
        "Retour aux signaux",
        "await page.screenshot",
        'console.log("card_smoke_ok")',
        'console.error("card_smoke_failed")',
        "process.exitCode = 1",
    ):
        assert fragment in commands or fragment in script

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
    for forbidden in ("Hermes", "openai", "anthropic", "ollama", "worker"):
        assert forbidden.casefold() not in commands.casefold()

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
