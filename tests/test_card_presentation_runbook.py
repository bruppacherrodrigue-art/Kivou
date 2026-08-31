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


def _ci_jq_filter(body: str) -> str:
    prefix = 'jq -e --arg sha "$KIVOU_FINAL_SHA" \'\n'
    suffix = '\' "$KIVOU_CI_JSON" >/dev/null'
    assert body.count(prefix) == 1
    assert body.count(suffix) == 1
    return body.split(prefix, 1)[1].split(suffix, 1)[0]


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
        "Reverse proxy public de staging (#84)",
        "kivou-api-green.service 8001",
        "green_openapi_status=200",
        "green_me_status=401",
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
        "public-status.codes",
        "reprendre au second bloc bash",
    ):
        assert fragment in body

    _assert_in_order(
        body,
        'assert after == "0028_card_presentation", after',
        "card_presentation_artifact",
        'print(f"migration={before}->{after}")',
        "Démarrer et prouver le runtime vert sur 8001",
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
    )

    backend_rollout = body.split(
        "## 5. Publier le backend par le blue/green versionné", 1
    )[1].split("## 6. Construire et basculer le frontend du même SHA", 1)[0]
    for fragment in (
        'KIVOU_BLUE_GREEN_DOC="$KIVOU_RELEASE_DIR/ops/README.md"',
        'test "$(readlink -f /srv/kivou/app)" = "$KIVOU_PREVIOUS_BACKEND"',
        "### Démarrer et prouver le runtime vert sur 8001",
        "### Basculer l'application pendant le monitor public",
    ):
        assert fragment in backend_rollout
    _assert_in_order(
        backend_rollout,
        'test "$(readlink -f /srv/kivou/app)" = "$KIVOU_PREVIOUS_BACKEND"',
        "reprendre au second bloc bash",
        'test "$(readlink -f /srv/kivou/app)" = "$KIVOU_RELEASE_DIR"',
    )


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
        'sudo test ! -L "$KIVOU_FRONTEND_NEXT"',
        'sudo test ! -L "$KIVOU_FRONTEND_ROLLBACK"',
        "KIVOU_ROLLBACK_ASSET_PATH=",
        'kivou_frontend_http_smoke "$KIVOU_ROLLBACK_ASSET_PATH"',
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
        'sudo mv -Tf "$KIVOU_FRONTEND_ROLLBACK" /srv/kivou/frontend',
        "KIVOU_ROLLBACK_ASSET_PATH=",
        'kivou_frontend_http_smoke "$KIVOU_ROLLBACK_ASSET_PATH"',
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
        ), line
    assert commands.count('case "$KIVOU_RESTORE_DB" in') >= 2
    assert commands.count('case "$KIVOU_FRONTEND_BUILD_REAL" in') >= 2


def test_ops_readme_points_to_the_single_versioned_staging_rollout() -> None:
    body = OPERATIONS.read_text(encoding="utf-8")

    assert body.count("../docs/runbooks/11-staging-card-presentation-rollout.md") == 1
    assert "Card Intelligence × QA Signals" in body
