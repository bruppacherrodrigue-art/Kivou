from __future__ import annotations

import re
from pathlib import Path

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
    tracked_fragments = (
        "kivou-limits.conf",
        "kivou-proxy-params.conf",
        "kivou-security-headers.conf",
        "kivou-sensitive-link-security-headers.conf",
        "kivou-sensitive-links-open.conf",
        "kivou-sensitive-links-closed.conf",
    )

    for fragment in tracked_fragments:
        assert fragment in body
    for substitution in (
        "s/STAGING_HOST/$KIVOU_STAGING_HOST/g",
        "s/KIVOU_API_PORT/$KIVOU_API_PORT/g",
        "s#/etc/nginx/kivou-proxy-params.conf#",
        "s#/etc/nginx/kivou-security-headers.conf#",
        "s#/etc/nginx/kivou-sensitive-link-security-headers.conf#",
        "s#/etc/nginx/kivou-sensitive-links-gate.conf#",
    ):
        assert substitution in body

    _assert_in_order(
        body,
        '"$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-open.conf"',
        '"$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf"',
        "sudo nginx -t -c",
        "/etc/nginx/kivou-proxy-params.conf.new",
    )
    assert "include $KIVOU_NGINX_CANDIDATE/kivou-limits.conf;" in body


def test_runbook_builds_an_exact_clean_reviewed_release_as_kivou() -> None:
    body = _runbook()

    _assert_in_order(
        body,
        "set KIVOU_RELEASE_SHA to the reviewed main SHA",
        "^[0-9a-f]{40}$",
        "KIVOU_RELEASE_ORIGIN=https://github.com/bruppacherrodrigue-art/Kivou.git",
        'remote get-url origin)" = "$KIVOU_RELEASE_ORIGIN"',
        "git -C /srv/kivou/app fetch --no-tags origin main",
        "/srv/kivou/releases/backend-",
        "bundle create",
        "refs/remotes/origin/main",
        "bundle verify",
        "git init --quiet --initial-branch=main",
        'fetch --no-tags "$KIVOU_RELEASE_BUNDLE"',
        "refs/remotes/origin/main",
        "checkout --detach",
        "remote add origin",
        "rev-parse HEAD",
        "uv sync --frozen --extra server --extra postgres",
    )
    assert "sudo -u kivou" in body
    assert "git status --porcelain" in body
    assert "remote set-url origin /srv/kivou/app" not in body
    assert "git clone --no-checkout" not in body


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


def test_snapshot_is_unique_root_only_and_evidence_only() -> None:
    body = _runbook()

    _assert_in_order(
        body,
        "mktemp -d /etc/nginx/.kivou-evidence.XXXXXX",
        'chmod 700 "$KIVOU_EVIDENCE_DIR"',
        "/etc/nginx/sites-available/kivou",
        "/etc/nginx/conf.d/kivou-limits.conf",
        "/etc/nginx/kivou-sensitive-links-gate.conf",
        "readlink -f /srv/kivou/app",
        "/etc/systemd/system/kivou-api.service",
        "EVIDENCE ONLY",
    )


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

    _assert_in_order(
        body,
        "KIVOU_PUBLIC_MONITOR_LOG=",
        'https://$KIVOU_STAGING_HOST/',
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
        "sudo systemctl stop kivou-api-green.service",
    )
    assert "all public monitor statuses must be 200" in body
    assert body.count("--connect-timeout 3") >= 2
    assert body.count("--max-time 5") >= 2
    _assert_in_order(
        body,
        "KIVOU_PUBLIC_MONITOR_PID=$!",
        "kivou_stop_public_monitor()",
        "trap kivou_stop_public_monitor EXIT",
        'sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app',
        "KIVOU_FINAL_PUBLIC_STATUS=",
        "kivou_stop_public_monitor",
        "trap - EXIT",
        "all public monitor statuses must be 200",
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
    _assert_in_order(
        reopen_shell,
        "/etc/nginx/kivou-sensitive-links-open.conf",
        "/etc/nginx/kivou-sensitive-links-gate.conf.new",
        "sudo mv -f",
        "sudo nginx -t",
        "sudo systemctl reload nginx",
    )


def test_rollback_keeps_the_security_floor_and_switches_only_the_application() -> None:
    body = _runbook()
    rollback = _subsection(body, "### Rollback applicatif préservant la sécurité")
    shell = _only_shell_block(rollback)

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
        "if sudo systemctl is-active --quiet kivou-api-green.service; then",
        'WorkingDirectory --value)" = "$KIVOU_SECURITY_RELEASE"',
        "else",
        "sudo systemctl stop kivou-api-green.service",
        "sudo systemctl reset-failed kivou-api-green.service",
        "! sudo systemctl is-active --quiet kivou-api-green.service",
        "sport = :8001",
        "kivou-api-rollback-green-",
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
