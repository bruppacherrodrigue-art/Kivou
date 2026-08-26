from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "ops" / "README.md"
SECTION_HEADING = "## Reverse proxy public de staging (#84)"


def _runbook() -> str:
    document = RUNBOOK.read_text(encoding="utf-8")
    assert document.count(SECTION_HEADING) == 1
    return document.split(SECTION_HEADING, 1)[1]


def _subsection(body: str, heading: str) -> str:
    assert body.count(heading) == 1
    remainder = body.split(heading, 1)[1]
    return remainder.split("\n### ", 1)[0]


def _assert_in_order(body: str, *needles: str) -> None:
    cursor = -1
    for needle in needles:
        cursor = body.index(needle, cursor + 1)


def _shell_blocks(body: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r"^~~~bash\n(.*?)^~~~$",
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
    )


def _only_shell_block(body: str) -> str:
    blocks = _shell_blocks(body)
    assert len(blocks) == 1, f"expected one shell block, got {len(blocks)}"
    return blocks[0]


def _logical_shell(shell: str) -> str:
    return re.sub(r"[ \t]*\\\n[ \t]*", " ", shell)


def _publication_command_tokens(
    logical_shell: str,
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    commands: list[tuple[int, tuple[str, ...]]] = []
    offset = 0
    for raw_line in logical_shell.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        if line.startswith(("sudo install ", "sudo mv -f ")):
            commands.append((offset, tuple(shlex.split(line))))
        offset += len(raw_line)
    return tuple(commands)


def _assert_fresh_recovery_state(shell: str) -> None:
    _assert_in_order(
        shell,
        "set -euo pipefail",
        "KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state",
        "sudo -u kivou test ! -w /etc/kivou",
        'test ! -L "$KIVOU_ROLLOUT_STATE"',
        "root:root:600",
        "unset KIVOU_STAGING_HOST KIVOU_SECURITY_RELEASE",
        "KIVOU_PREVIOUS_RELEASE KIVOU_RELEASE_SHA",
        'KIVOU_STATE_CONTENT=$(sudo cat "$KIVOU_ROLLOUT_STATE")',
        '. /dev/stdin <<<"$KIVOU_STATE_CONTENT"',
        "unset KIVOU_STATE_CONTENT",
        'case "$KIVOU_STAGING_HOST" in',
        'case "$KIVOU_SECURITY_RELEASE" in',
        'case "$KIVOU_PREVIOUS_RELEASE" in',
        "^[0-9a-f]{40}$",
        "kivou_git()",
        "rev-parse HEAD",
        "status --porcelain",
    )
    assert shell.count('sudo cat "$KIVOU_ROLLOUT_STATE"') == 1


def test_runbook_validates_host_and_only_the_two_reviewed_api_ports() -> None:
    body = _runbook()

    assert "KIVOU_STAGING_HOST=staging.kivou.eu" in body
    assert 'case "$KIVOU_STAGING_HOST" in' in body
    assert "(*[!a-z0-9.-]*|'')" in body
    assert 'case "$KIVOU_API_PORT" in' in body
    assert "(8000|8001)" in body
    assert set(re.findall(r"^KIVOU_API_PORT=(\d+)$", body, flags=re.MULTILINE)) == {
        "8000",
        "8001",
    }


def test_runbook_renders_every_fragment_and_the_open_gate_before_publication() -> None:
    body = _runbook()
    preparation = _subsection(
        body, "### Préparer la release exacte et le candidat nginx isolé"
    )
    _, candidate_shell = _shell_blocks(preparation)
    tracked_fragments = (
        "kivou-limits.conf",
        "kivou-proxy-params.conf",
        "kivou-security-headers.conf",
        "kivou-sensitive-link-security-headers.conf",
        "kivou-sensitive-links-open.conf",
        "kivou-sensitive-links-closed.conf",
    )

    for fragment in tracked_fragments:
        source = f'"$KIVOU_RELEASE_DIR/ops/nginx/{fragment}"'
        assert candidate_shell.count(source) == 1
    for substitution in (
        "s/STAGING_HOST/$KIVOU_STAGING_HOST/g",
        "s/KIVOU_API_PORT/$KIVOU_API_PORT/g",
        "s#/etc/nginx/kivou-proxy-params.conf#",
        "s#/etc/nginx/kivou-security-headers.conf#",
        "s#/etc/nginx/kivou-sensitive-link-security-headers.conf#",
        "s#/etc/nginx/kivou-sensitive-links-gate.conf#",
    ):
        assert candidate_shell.count(substitution) == 1

    _assert_in_order(
        body,
        '"$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-open.conf"',
        '"$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf"',
        "sudo nginx -t -c",
        "/etc/nginx/kivou-proxy-params.conf.new",
    )
    assert (
        candidate_shell.count(
            "include $KIVOU_NGINX_CANDIDATE/kivou-limits.conf;"
        )
        == 1
    )
    _assert_in_order(
        candidate_shell,
        'git -C "$KIVOU_RELEASE_DIR" show',
        '"$KIVOU_RELEASE_SHA:ops/nginx/kivou-sensitive-links-open.conf"',
        "sha256sum",
        '"$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf"',
        'test "$KIVOU_CANDIDATE_OPEN_SHA" = "$KIVOU_REVIEWED_OPEN_SHA"',
        "test -z",
        "sudo nginx -t -c",
    )


def test_runbook_builds_an_exact_clean_reviewed_release_as_kivou() -> None:
    body = _runbook()
    preparation = _subsection(
        body, "### Préparer la release exacte et le candidat nginx isolé"
    )
    release_shell, _ = _shell_blocks(preparation)

    _assert_in_order(
        release_shell,
        "set KIVOU_RELEASE_SHA to the reviewed main SHA",
        "^[0-9a-f]{40}$",
        "KIVOU_RELEASE_REMOTE=git@github.com:bruppacherrodrigue-art/Kivou.git",
        "KIVOU_DEPLOY_KEY=/srv/kivou/.ssh/github_deploy",
        "kivou:kivou:600",
        "KIVOU_KNOWN_HOSTS=/etc/nginx/kivou-github-known-hosts",
        'sudo -u kivou test ! -w /etc/nginx',
        'test ! -L "$KIVOU_KNOWN_HOSTS"',
        "root:root:644",
        'sudo -u kivou test ! -w "$KIVOU_KNOWN_HOSTS"',
        "ssh-keygen -lf",
        "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU",
        "GIT_SSH_COMMAND=",
        "git ls-remote --exit-code",
        "refs/heads/main",
        'test "$KIVOU_REMOTE_MAIN_SHA" = "$KIVOU_RELEASE_SHA"',
        "/srv/kivou/releases/backend-",
        "git init --quiet --initial-branch=main",
        "remote add origin",
        "fetch --no-tags",
        "refs/heads/main:refs/kivou-rollout/reviewed-main",
        "rev-parse refs/kivou-rollout/reviewed-main",
        "checkout --detach",
        "rev-parse HEAD",
        "git status --porcelain",
        "uv sync --frozen --extra server --extra postgres",
    )
    assert "sudo -u kivou" in release_shell
    assert "/srv/kivou/app" not in release_shell
    assert "bundle" not in release_shell
    assert "https://github.com/bruppacherrodrigue-art/Kivou.git" not in release_shell
    for required in (
        "-F /dev/null",
        "BatchMode=yes",
        "IdentitiesOnly=yes",
        "StrictHostKeyChecking=yes",
        "UserKnownHostsFile=$KIVOU_KNOWN_HOSTS",
        "GlobalKnownHostsFile=/dev/null",
    ):
        assert required in release_shell
    assert release_shell.count("GIT_CONFIG_GLOBAL=/dev/null") == 3
    assert release_shell.count("GIT_CONFIG_NOSYSTEM=1") == 3
    assert "deploy key read-only" in preparation
    for forbidden in (
        "ssh-keyscan",
        "accept-new",
        "StrictHostKeyChecking=no",
    ):
        assert forbidden not in release_shell


def test_green_runtime_matches_the_versioned_service_and_is_proven_directly() -> None:
    body = _runbook()
    green = _subsection(body, "### Démarrer et prouver le runtime vert sur 8001")
    shell = _only_shell_block(green)

    _assert_in_order(
        shell,
        "sudo systemd-run",
        "--unit=kivou-api-green",
        "--property=EnvironmentFile=/etc/kivou/staging.env",
        "--port 8001",
        "--workers 2",
        "--no-access-log",
        "http://127.0.0.1:8001/openapi.json",
        "http://127.0.0.1:8001/me",
    )
    for hardening in (
        "NoNewPrivileges=yes",
        "PrivateTmp=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "ReadWritePaths=/srv/kivou/run",
        "ProtectKernelTunables=yes",
        "ProtectKernelModules=yes",
        "ProtectControlGroups=yes",
        "RestrictSUIDSGID=yes",
        "RestrictNamespaces=yes",
        "LockPersonality=yes",
        "MemoryDenyWriteExecute=yes",
    ):
        assert shell.count(f"--property={hardening}") == 1
    assert shell.count("--no-access-log") == 1
    assert 'test "$KIVOU_GREEN_OPENAPI_STATUS" = 200' in shell
    assert 'test "$KIVOU_GREEN_ME_STATUS" = 401' in shell


def test_bounded_readiness_precedes_every_direct_api_probe() -> None:
    body = _runbook()
    green = _logical_shell(
        _only_shell_block(
            _subsection(body, "### Démarrer et prouver le runtime vert sur 8001")
        )
    )
    normal = _logical_shell(
        _only_shell_block(
            _subsection(body, "### Basculer l'application pendant le monitor public")
        )
    )
    rollback = _logical_shell(
        _only_shell_block(
            _subsection(body, "### Rollback applicatif préservant la sécurité")
        )
    )

    _assert_in_order(
        green,
        "sudo systemd-run",
        '"$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" '
        "kivou-api-green.service 8001",
        "http://127.0.0.1:8001/openapi.json",
        "http://127.0.0.1:8001/me",
    )
    _assert_in_order(
        normal,
        "sudo systemctl restart kivou-api.service",
        '"$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" '
        "kivou-api.service 8000",
        "http://127.0.0.1:8000/openapi.json",
        "http://127.0.0.1:8000/me",
    )
    _assert_in_order(
        rollback,
        '--unit="$KIVOU_ROLLBACK_GREEN_UNIT"',
        '"$KIVOU_SECURITY_RELEASE/ops/bin/kivou-api-readiness.sh" '
        '"$KIVOU_ROLLBACK_GREEN_UNIT" 8001',
        "http://127.0.0.1:8001/openapi.json",
        "http://127.0.0.1:8001/me",
        "sudo systemctl restart kivou-api.service",
        '"$KIVOU_SECURITY_RELEASE/ops/bin/kivou-api-readiness.sh" '
        "kivou-api.service 8000",
        "http://127.0.0.1:8000/openapi.json",
        "http://127.0.0.1:8000/me",
    )
    assert rollback.count("ops/bin/kivou-api-readiness.sh") == 2


def test_readiness_helper_has_an_exact_unprivileged_execution_boundary() -> None:
    body = _logical_shell(_runbook())
    helper = (
        ROOT / "ops" / "bin" / "kivou-api-readiness.sh"
    ).read_text(encoding="utf-8")
    closed_environment = (
        "/usr/bin/sudo -u kivou -- /usr/bin/env -i PATH=/usr/bin:/bin "
    )

    assert "sudo" not in helper
    assert "timeout --foreground 1 systemctl is-active --quiet" in helper
    assert body.count(closed_environment) == 4
    assert body.count(
        closed_environment
        + '"$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh"'
    ) == 2
    assert body.count(
        closed_environment
        + '"$KIVOU_SECURITY_RELEASE/ops/bin/kivou-api-readiness.sh"'
    ) == 2


def test_every_direct_local_api_probe_has_connect_and_total_timeouts() -> None:
    logical = _logical_shell(_runbook())
    local_probes = tuple(
        line
        for line in logical.splitlines()
        if re.search(r"127\.0\.0\.1:800[01]/(?:openapi\.json|me)", line)
    )

    assert len(local_probes) == 8
    for probe in local_probes:
        assert "curl" in probe
        assert "--connect-timeout 1" in probe
        assert "--max-time 2" in probe
        assert "=$(curl" in probe
        assert ") || exit 1" in probe


def test_snapshot_is_unique_root_only_and_evidence_only() -> None:
    body = _runbook()
    snapshot = _subsection(
        body, "### Capturer la preuve antérieure sans en faire un rollback"
    )
    shell = _only_shell_block(snapshot)

    _assert_in_order(
        shell,
        "mktemp -d /etc/nginx/.kivou-evidence.XXXXXX",
        'chmod 700 "$KIVOU_EVIDENCE_DIR"',
        "/etc/nginx/sites-available/kivou",
        "/etc/nginx/conf.d/kivou-limits.conf",
        "/etc/nginx/kivou-sensitive-links-gate.conf",
        "/etc/systemd/system/kivou-api.service",
    )
    assert shell.count("readlink -f /srv/kivou/app") == 1
    assert "EVIDENCE ONLY" in snapshot


def test_non_secret_recovery_state_is_atomic_root_only_and_precedes_live_change() -> None:
    body = _runbook()
    snapshot = _subsection(
        body, "### Capturer la preuve antérieure sans en faire un rollback"
    )
    shell = _only_shell_block(snapshot)
    state_keys = tuple(
        re.findall(r"printf '([A-Z_]+)=%q\\n'", shell)
    )

    assert state_keys == (
        "KIVOU_STAGING_HOST",
        "KIVOU_SECURITY_RELEASE",
        "KIVOU_PREVIOUS_RELEASE",
        "KIVOU_RELEASE_SHA",
    )
    for forbidden in ("SECRET", "TOKEN", "PASSWORD", "DATABASE", "ENVIRONMENT"):
        assert forbidden not in state_keys
    _assert_in_order(
        shell,
        "KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state",
        "KIVOU_ROLLOUT_STATE_NEW=/etc/kivou/kivou-safe-rollout.state.new",
        "sudo -u kivou test ! -w /etc/kivou",
        "install -o root -g root -m 600 /dev/null",
        'tee "$KIVOU_ROLLOUT_STATE_NEW"',
        "root:root:600",
        'sudo mv -f "$KIVOU_ROLLOUT_STATE_NEW" "$KIVOU_ROLLOUT_STATE"',
    )
    assert body.index(
        'sudo mv -f "$KIVOU_ROLLOUT_STATE_NEW" "$KIVOU_ROLLOUT_STATE"'
    ) < body.index("--unit=kivou-api-green")


def test_safe_bundle_is_published_atomically_then_reloaded_once_to_green() -> None:
    body = _runbook()

    _assert_in_order(
        body,
        "sudo nginx -t -c",
        "/etc/nginx/kivou-proxy-params.conf.new",
        "sudo mv -f /etc/nginx/kivou-proxy-params.conf.new",
        "/etc/nginx/kivou-sensitive-links-gate.conf.new",
        "sudo mv -f /etc/nginx/kivou-sensitive-links-gate.conf.new",
        "sudo nginx -t",
        "single public reload to green",
        "sudo systemctl reload nginx",
    )
    assert "-m 600" in body
    assert "-m 644" in body


def test_public_monitor_spans_atomic_app_switch_and_normal_api_restart() -> None:
    body = _runbook()
    monitor = _subsection(body, "### Basculer l'application pendant le monitor public")
    shell = _only_shell_block(monitor)

    _assert_in_order(
        shell,
        "KIVOU_PUBLIC_MONITOR_LOG=",
        'https://$KIVOU_STAGING_HOST/',
        'https://$KIVOU_STAGING_HOST/me',
        "printf '%s %s\\n'",
        "KIVOU_PUBLIC_FIRST_SAMPLE=$(kivou_public_sample)",
        'test "$KIVOU_PUBLIC_FIRST_SAMPLE" = "200 401"',
        'printf \'%s\\n\' "$KIVOU_PUBLIC_FIRST_SAMPLE"',
        "KIVOU_PUBLIC_MONITOR_PID=$!",
        "KIVOU_APP_NEXT_DIR=",
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
        "/etc/systemd/system/kivou-api.service.new",
        "sudo systemctl daemon-reload",
        "sudo systemctl restart kivou-api.service",
        "http://127.0.0.1:8000/openapi.json",
        "http://127.0.0.1:8000/me",
        "KIVOU_API_PORT=8000",
        "sudo nginx -t -c",
        "sudo systemctl reload nginx",
        "KIVOU_FINAL_PUBLIC_SAMPLE=$(kivou_public_sample)",
        'test "$KIVOU_FINAL_PUBLIC_SAMPLE" = "200 401"',
        '$1 != "200" || $2 != "401"',
        "sudo systemctl stop kivou-api-green.service",
    )
    assert "all public monitor status pairs must be 200 401" in shell
    assert shell.count("--connect-timeout 3") == 2
    assert shell.count("--max-time 5") == 2
    assert "sleep 1" in shell
    assert "sleep 0.2" not in shell
    _assert_in_order(
        shell,
        "KIVOU_PUBLIC_MONITOR_PID=$!",
        "kivou_stop_public_monitor()",
        "trap kivou_stop_public_monitor EXIT",
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
        "KIVOU_FINAL_PUBLIC_SAMPLE=",
        'kill -0 "$KIVOU_PUBLIC_MONITOR_PID"',
        'wait "$KIVOU_PUBLIC_MONITOR_PID"',
        "trap - EXIT",
        "all public monitor status pairs must be 200 401",
    )


def test_synthetic_proof_covers_both_schemes_reset_referer_and_all_logs() -> None:
    body = _runbook()

    _assert_in_order(
        body,
        "KIVOU_SYNTHETIC_ATTRIBUTION_MARKER=",
        "KIVOU_SYNTHETIC_RESET_MARKER=",
        'http://$KIVOU_STAGING_HOST/a/$KIVOU_SYNTHETIC_ATTRIBUTION_MARKER',
        'https://$KIVOU_STAGING_HOST/a/$KIVOU_SYNTHETIC_ATTRIBUTION_MARKER',
        'http://$KIVOU_STAGING_HOST/reset-password?token=$KIVOU_SYNTHETIC_RESET_MARKER',
        'https://$KIVOU_STAGING_HOST/reset-password?token=$KIVOU_SYNTHETIC_RESET_MARKER',
        "KIVOU_ASSET_PATH=",
        "--referer",
        "/var/log/nginx/access.log",
        "/var/log/nginx/error.log",
        "journalctl -u kivou-api.service",
        "marker_occurrences=0",
        "sanitized_attribution_count=",
        "sanitized_reset_count=",
        "referrer_policy_count=1",
    )
    assert "/a/[redacted]" in body
    assert "/reset-password" in body
    assert "Only numeric or coded output is emitted." in body


def test_real_token_boundary_is_process_only_and_requires_no_reset_email() -> None:
    body = _runbook()

    _assert_in_order(
        body,
        "marker_occurrences=0",
        "separately authorized valid attribution proof",
        "real token stays entirely in process memory",
        "no new reset e-mail is needed",
    )
    assert "KIVOU_VALID_ATTRIBUTION_TOKEN=" not in body
    assert "--valid-token" not in body


def test_gate_close_and_open_are_atomic_validated_transitions() -> None:
    body = _runbook()
    close = _subsection(body, "### Fermer atomiquement les liens sensibles")
    reopen = _subsection(body, "### Réouvrir atomiquement les liens sensibles")
    close_shell = _only_shell_block(close)
    reopen_shell = _only_shell_block(reopen)

    _assert_in_order(
        close_shell,
        "/etc/nginx/kivou-sensitive-links-closed.conf",
        'test "$(sudo awk',
        '/etc/nginx/kivou-sensitive-links-gate.conf.new)" = "return 503;"',
        "sudo mv -f",
        "sudo nginx -t",
        "sudo systemctl reload nginx",
    )
    _assert_fresh_recovery_state(reopen_shell)
    _assert_in_order(
        reopen_shell,
        'git -C "$KIVOU_SECURITY_RELEASE" show',
        '"$KIVOU_RELEASE_SHA:ops/nginx/kivou-sensitive-links-open.conf"',
        "sha256sum",
        '"$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-links-open.conf"',
        "/etc/nginx/kivou-sensitive-links-gate.conf.new",
        "sha256sum",
        'test "$KIVOU_OPEN_GATE_SHA" = "$KIVOU_REVIEWED_OPEN_SHA"',
        "test -z",
        "sudo mv -f",
        "sudo nginx -t",
        "sudo systemctl reload nginx",
    )
    assert "/etc/nginx/kivou-sensitive-links-open.conf" not in reopen_shell
    assert 'sha256sum "$KIVOU_REVIEWED_OPEN"' not in reopen_shell


def test_fresh_rollback_rebuilds_the_complete_safe_nginx_bundle() -> None:
    body = _runbook()
    rollback = _subsection(body, "### Rollback applicatif préservant la sécurité")
    shell = _only_shell_block(rollback)
    recovery = shell.split("# Switch only to the recorded previous", 1)[0]
    logical = _logical_shell(recovery)
    source_paths = (
        "ops/nginx/kivou-limits.conf",
        "ops/nginx/kivou-proxy-params.conf",
        "ops/nginx/kivou-security-headers.conf",
        "ops/nginx/kivou-sensitive-link-security-headers.conf",
        "ops/nginx/kivou-sensitive-links-open.conf",
        "ops/nginx/kivou-sensitive-links-closed.conf",
        "ops/nginx/kivou-staging.conf",
    )
    publications = (
        (
            source_paths[1],
            "644",
            "/etc/nginx/kivou-proxy-params.conf.new",
            "/etc/nginx/kivou-proxy-params.conf",
        ),
        (
            source_paths[2],
            "644",
            "/etc/nginx/kivou-security-headers.conf.new",
            "/etc/nginx/kivou-security-headers.conf",
        ),
        (
            source_paths[3],
            "644",
            "/etc/nginx/kivou-sensitive-link-security-headers.conf.new",
            "/etc/nginx/kivou-sensitive-link-security-headers.conf",
        ),
        (
            source_paths[4],
            "644",
            "/etc/nginx/kivou-sensitive-links-open.conf.new",
            "/etc/nginx/kivou-sensitive-links-open.conf",
        ),
        (
            source_paths[5],
            "644",
            "/etc/nginx/kivou-sensitive-links-closed.conf.new",
            "/etc/nginx/kivou-sensitive-links-closed.conf",
        ),
        (
            source_paths[5],
            "600",
            "/etc/nginx/kivou-sensitive-links-gate.conf.new",
            "/etc/nginx/kivou-sensitive-links-gate.conf",
        ),
        (
            source_paths[0],
            "644",
            "/etc/nginx/conf.d/kivou-limits.conf.new",
            "/etc/nginx/conf.d/kivou-limits.conf",
        ),
    )
    manifest = recovery.split("KIVOU_SAFE_NGINX_SOURCE_PATHS=(", 1)[1].split(
        "\n)", 1
    )[0]

    assert tuple(re.findall(r'^\s*"([^"]+)"$', manifest, re.MULTILINE)) == source_paths
    _assert_in_order(
        logical,
        "for KIVOU_SAFE_NGINX_SOURCE_PATH in",
        'show "$KIVOU_RELEASE_SHA:$KIVOU_SAFE_NGINX_SOURCE_PATH"',
        'sha256sum "$KIVOU_SECURITY_RELEASE/$KIVOU_SAFE_NGINX_SOURCE_PATH"',
        'test "$KIVOU_WORKTREE_SOURCE_SHA" = "$KIVOU_GIT_SOURCE_SHA"',
        "test -z",
        'kivou-sensitive-links-open.conf")',
        'kivou-sensitive-links-closed.conf")',
        '"return 503;"',
    )

    def assert_publications(
        candidate_logical: str,
    ) -> tuple[set[str], list[int], list[int]]:
        recovered: set[str] = set()
        stages: list[int] = []
        moves: list[int] = []
        commands = _publication_command_tokens(candidate_logical)
        for source, mode, staged, live in publications:
            install = (
                "sudo",
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                mode,
                f"$KIVOU_SECURITY_RELEASE/{source}",
                staged,
            )
            move = ("sudo", "mv", "-f", staged, live)
            install_positions = [
                position for position, tokens in commands if tokens == install
            ]
            move_positions_for_file = [
                position for position, tokens in commands if tokens == move
            ]
            assert len(install_positions) == 1
            assert len(move_positions_for_file) == 1
            recovered.add(live)
            stages.append(install_positions[0])
            moves.append(move_positions_for_file[0])
        return recovered, stages, moves

    recovered_live_paths, stage_positions, move_positions = assert_publications(
        logical
    )

    site_stage = (
        '"$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-staging.conf" | '
        "sudo tee /etc/nginx/sites-available/kivou.new >/dev/null"
    )
    site_move = (
        "sudo",
        "mv",
        "-f",
        "/etc/nginx/sites-available/kivou.new",
        "/etc/nginx/sites-available/kivou",
    )
    assert logical.count(site_stage) == 1
    site_move_positions = [
        position
        for position, tokens in _publication_command_tokens(logical)
        if tokens == site_move
    ]
    assert len(site_move_positions) == 1
    recovered_live_paths.add("/etc/nginx/sites-available/kivou")
    stage_positions.append(logical.index(site_stage))
    move_positions.append(site_move_positions[0])

    expected_live_paths = {live for _, _, _, live in publications} | {
        "/etc/nginx/sites-available/kivou"
    }
    assert max(stage_positions) < min(move_positions)
    assert max(move_positions) < logical.index("sudo nginx -t")
    _assert_in_order(
        recovery,
        "KIVOU_API_PORT=8001",
        "s/STAGING_HOST/$KIVOU_STAGING_HOST/g",
        "s/KIVOU_API_PORT/$KIVOU_API_PORT/g",
        'gate.conf.new)" = "return 503;"',
        "sudo nginx -t",
        "sudo systemctl reload nginx",
    )
    assert recovered_live_paths == expected_live_paths
    for _, _, staged, _ in publications:
        mutant = logical.replace(
            f" {staged}\n",
            f" {staged}.broken\n",
            1,
        )
        assert mutant != logical
        with pytest.raises(AssertionError):
            assert_publications(mutant)
    assert "KIVOU_NGINX_CANDIDATE" not in recovery
    assert "KIVOU_EVIDENCE_DIR" not in recovery
    assert "le vieux processus nginx" in rollback
    assert "continue de servir jusqu'au nginx-t réussi" in rollback
    for live in expected_live_paths:
        assert f"test -e {live}" not in recovery
        assert f"cp -a {live}" not in recovery


def test_rollback_keeps_the_security_floor_and_switches_only_the_application() -> None:
    body = _runbook()
    rollback = _subsection(body, "### Rollback applicatif préservant la sécurité")
    shell = _only_shell_block(rollback)
    _assert_fresh_recovery_state(shell)

    for required in (
        "security floor",
        "EVIDENCE ONLY",
        "--no-access-log",
        "previous application release",
        "kivou-sensitive-links-closed.conf",
        "Never restore the old nginx access format or the old API unit.",
    ):
        assert required in rollback
    _assert_in_order(
        shell,
        '. /dev/stdin <<<"$KIVOU_STATE_CONTENT"',
        "kivou_validate_recovery_green_unit()",
        "if sudo systemctl is-active --quiet kivou-api-green.service; then",
        "KIVOU_ROLLBACK_GREEN_UNIT=kivou-api-green.service",
        'kivou_validate_recovery_green_unit "$KIVOU_ROLLBACK_GREEN_UNIT"',
        "elif sudo systemctl is-active --quiet",
        "kivou-api-rollback-green.service; then",
        "KIVOU_ROLLBACK_GREEN_UNIT=kivou-api-rollback-green.service",
        'kivou_validate_recovery_green_unit "$KIVOU_ROLLBACK_GREEN_UNIT"',
        "else",
        "KIVOU_ROLLBACK_GREEN_UNIT=kivou-api-rollback-green.service",
        "sudo systemctl stop kivou-api-green.service",
        'sudo systemctl stop "$KIVOU_ROLLBACK_GREEN_UNIT"',
        "sudo systemctl reset-failed kivou-api-green.service",
        'sudo systemctl reset-failed "$KIVOU_ROLLBACK_GREEN_UNIT"',
        "! sudo systemctl is-active --quiet kivou-api-green.service",
        '! sudo systemctl is-active --quiet "$KIVOU_ROLLBACK_GREEN_UNIT"',
        "sport = :8001",
        '--unit="$KIVOU_ROLLBACK_GREEN_UNIT"',
        "fi",
        "previous application release",
        'sudo mv -Tf "$KIVOU_ROLLBACK_NEXT" /srv/kivou/app',
        "/etc/systemd/system/kivou-api.service.new",
        "sudo systemctl restart kivou-api.service",
        "http://127.0.0.1:8000/openapi.json",
        "KIVOU_API_PORT=8000",
        'sudo systemctl stop "$KIVOU_ROLLBACK_GREEN_UNIT"',
    )
    reviewed_unit = '"$KIVOU_SECURITY_RELEASE/ops/systemd/kivou-api.service"'
    evidence_unit = '"$KIVOU_EVIDENCE_DIR/kivou-api.service"'
    assert shell.count(reviewed_unit) == 1
    assert evidence_unit not in shell
    assert 'cat "$KIVOU_EVIDENCE_DIR/reviewed-release-target"' not in shell
    assert 'cat "$KIVOU_EVIDENCE_DIR/app-target"' not in shell
    assert (
        shell.count(
            "--forwarded-allow-ips 127.0.0.1 --no-server-header "
            "--no-access-log"
        )
        == 1
    )


def test_runbook_forbids_mutating_or_secret_bearing_expansion() -> None:
    body = _runbook()

    assert (
        "No migration, provider call, e-mail, production action, or secret argument "
        "belongs to this procedure."
    ) in body
    for forbidden in (
        "KIVOU_VALID_ATTRIBUTION_TOKEN=",
        "--setenv=",
        "source /etc/kivou/staging.env",
        ". /etc/kivou/staging.env",
        "git reset",
        "git checkout -- .",
        "rm -rf",
        "alembic upgrade",
        "alembic downgrade",
        "TBD",
    ):
        assert forbidden not in body


def test_every_release_git_proof_ignores_user_and_system_configuration() -> None:
    body = _runbook()
    git_helpers = re.findall(r"kivou_git\(\) \{\n(.*?)\n\}", body, re.DOTALL)

    assert "sudo -u kivou git" not in body
    assert len(git_helpers) == 3
    for helper in git_helpers:
        assert "GIT_CONFIG_GLOBAL=/dev/null" in helper
        assert "GIT_CONFIG_NOSYSTEM=1" in helper
        assert "/usr/bin/env -i" in helper
        assert '/usr/bin/git "$@"' in helper
