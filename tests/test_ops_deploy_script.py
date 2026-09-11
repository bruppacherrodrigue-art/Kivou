from __future__ import annotations

import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "ops/bin/kivou-deploy.sh"


def test_deploy_synchronizes_environment_systemd_units_on_every_path() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "sync_systemd_units" in script
    assert 'unit_dir="$unit_dir/production"' in script
    assert 'ops/systemd' in script
    assert 'install -o root -g root -m 0644' in script
    assert 'systemctl daemon-reload' in script
    assert script.index("sync_systemd_units") < script.index("release déjà active")
    assert script.index("sync_systemd_units") < script.index('systemctl restart "$KIVOU_SYSTEMD_UNIT"')


def _fake_bin(directory: pathlib.Path, name: str, body: str) -> None:
    target = directory / name
    target.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
    target.chmod(0o755)


def _active_production_environment(
    tmp_path: pathlib.Path,
    *,
    curl_body: str = "exit 0\n",
    nginx_body: str = "exit 0\n",
    systemctl_body: str = "exit 0\n",
) -> tuple[dict[str, str], pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    source = tmp_path / "source"
    source.mkdir()
    releases = tmp_path / "releases"
    release = releases / f"production-{'a' * 40}"
    (release / "frontend/dist").mkdir(parents=True)
    (release / "frontend/dist-founder").mkdir()
    (release / ".git").write_text("gitdir: test\n", encoding="utf-8")
    (release / "ops/systemd/production").mkdir(parents=True)
    (release / "ops/systemd/production/kivou-api.service").write_text(
        "customer unit\n", encoding="utf-8"
    )
    (release / "ops/systemd/kivou-founder-api.service").write_text(
        "founder unit\n", encoding="utf-8"
    )
    (release / "ops/nginx").mkdir()
    (release / "ops/nginx/kivou-founder-control.conf").write_text(
        "founder nginx\n", encoding="utf-8"
    )

    live_backend = tmp_path / "app"
    live_frontend = tmp_path / "www"
    live_backend.symlink_to(release)
    live_frontend.symlink_to(release / "frontend/dist")
    old_founder = tmp_path / "old-founder"
    old_founder.mkdir()
    founder_frontend = tmp_path / "founder/frontend"
    founder_frontend.parent.mkdir()
    founder_frontend.symlink_to(old_founder)

    readiness = tmp_path / "readiness.sh"
    readiness.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    readiness.chmod(0o755)
    backup = tmp_path / "backup.sh"
    backup.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'mkdir -p "$KIVOU_BACKUP_DIR"\n'
        'touch "$KIVOU_BACKUP_DIR/test.dump"\n',
        encoding="utf-8",
    )
    backup.chmod(0o755)

    founder_secret = "a" * 64
    founder_env = tmp_path / "founder.env"
    founder_env.write_text(
        "KIVOU_FOUNDER_HOSTNAME=control.kivou.eu\n"
        "KIVOU_FOUNDER_ENVIRONMENT=PRODUCTION\n"
        "KIVOU_FOUNDER_ALLOWED_EMAIL=founder@example.com\n"
        "KIVOU_FOUNDER_ALLOWED_USER=rodrigue\n"
        f"KIVOU_FOUNDER_ORIGIN_SECRET={founder_secret}\n"
        "KIVOU_FOUNDER_DATABASE_URL=postgresql://readonly@example/kivou\n",
        encoding="utf-8",
    )
    origin_secret = tmp_path / "founder-origin-secret.conf"
    htpasswd = tmp_path / "founder.htpasswd"
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    origin_secret.write_text(
        f'set $kivou_founder_origin_secret "{founder_secret}";\n',
        encoding="utf-8",
    )
    htpasswd.write_text("rodrigue:$2y$test-only-hash\n", encoding="utf-8")
    for path in (
        cert_dir / "fullchain.pem",
        cert_dir / "privkey.pem",
        cert_dir / "chain.pem",
    ):
        path.write_text("present\n", encoding="utf-8")

    recorder = 'printf "%s %s\\n" "$(basename "$0")" "$*" >> "$KIVOU_TEST_LOG"\n'
    for command in ("uv", "npm", "createdb", "dropdb", "pg_restore"):
        _fake_bin(fake_bin, command, recorder)
    _fake_bin(
        fake_bin,
        "git",
        recorder
        + 'if [[ "$*" == *"rev-parse HEAD"* ]]; then printf "%s\\n" "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; fi\n',
    )
    _fake_bin(
        fake_bin,
        "runuser",
        recorder
        + 'if [[ "${KIVOU_TEST_DENY_READ_AS_USER:-}" == "$2" && "$4" == "test" && "$5" == "-r" ]]; then exit 77; fi\n'
        + 'shift 3\nexec "$@"\n',
    )
    _fake_bin(fake_bin, "stat", "printf 'kivou:kivou\\n'\n")
    _fake_bin(fake_bin, "systemctl", recorder + systemctl_body)
    _fake_bin(fake_bin, "curl", recorder + curl_body)
    _fake_bin(fake_bin, "nginx", recorder + nginx_body)
    _fake_bin(
        fake_bin,
        "cp",
        recorder
        + 'if [[ "${KIVOU_TEST_FAIL_NGINX_RESTORE:-0}" == "1" && "$1" == "-a" && "$4" == "$KIVOU_FOUNDER_NGINX_AVAILABLE" ]]; then exit 26; fi\n'
        + 'exec /usr/bin/cp "$@"\n',
    )
    _fake_bin(
        fake_bin,
        "install",
        recorder
        + 'if [[ "$1" == "-d" && "${@: -1}" == "$(dirname "$KIVOU_FOUNDER_FRONTEND_LINK")" ]]; then exec /usr/bin/install "$@"; fi\n'
        + 'if [[ "$1" == "-d" ]]; then shift; while [[ "$1" == -* ]]; do shift 2; done; mkdir -p -- "$1"; exit 0; fi\n'
        + 'while [[ $# -gt 0 ]]; do case "$1" in -o|-g|-m) shift 2;; *) break;; esac; done\n'
        + 'case "$2" in /etc/systemd/system/*) exit 0;; esac\n'
        + 'if [[ "${KIVOU_TEST_FAIL_NGINX_INSTALL:-0}" == "1" && "$2" == "$KIVOU_FOUNDER_NGINX_AVAILABLE" ]]; then printf "partial candidate\\n" > "$2"; exit 25; fi\n'
        + 'cp -- "$1" "$2"\n',
    )

    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir()
    sites_available = tmp_path / "nginx/sites-available"
    sites_enabled = tmp_path / "nginx/sites-enabled"
    sites_available.mkdir(parents=True)
    sites_enabled.mkdir(parents=True)
    nginx_available = sites_available / "kivou-founder-control.conf"
    nginx_enabled = sites_enabled / "kivou-founder-control.conf"

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "KIVOU_TEST_LOG": str(log),
        "KIVOU_SOURCE_DIR": str(source),
        "KIVOU_RELEASES_DIR": str(releases),
        "KIVOU_BACKEND_LINK": str(live_backend),
        "KIVOU_FRONTEND_LINK": str(live_frontend),
        "KIVOU_FOUNDER_FRONTEND_LINK": str(founder_frontend),
        "KIVOU_FOUNDER_FRONTEND_OWNER": str(os.getuid()),
        "KIVOU_FOUNDER_FRONTEND_GROUP": str(os.getgid()),
        "KIVOU_FOUNDER_NGINX_WORKER_USER": str(os.getuid()),
        "KIVOU_DATABASE_URL": "postgresql://kivou@localhost/kivou",
        "KIVOU_MIGRATION_ADMIN_URL": "postgresql://deploy@localhost/postgres",
        "KIVOU_BACKUP_SCRIPT": str(backup),
        "KIVOU_BACKUP_DIR": str(tmp_path / "backups"),
        "KIVOU_READINESS_SCRIPT": str(readiness),
        "KIVOU_PLAYWRIGHT_BROWSERS_DIR": str(tmp_path / "playwright"),
        "KIVOU_FOUNDER_ENV_FILE": str(founder_env),
        "KIVOU_FOUNDER_ORIGIN_SECRET_FILE": str(origin_secret),
        "KIVOU_FOUNDER_HTPASSWD_FILE": str(htpasswd),
        "KIVOU_FOUNDER_CERT_FULLCHAIN_FILE": str(cert_dir / "fullchain.pem"),
        "KIVOU_FOUNDER_CERT_PRIVATE_KEY_FILE": str(cert_dir / "privkey.pem"),
        "KIVOU_FOUNDER_CERT_CHAIN_FILE": str(cert_dir / "chain.pem"),
        "KIVOU_FOUNDER_SYSTEMD_UNIT_PATH": str(systemd_dir / "kivou-founder-api.service"),
        "KIVOU_FOUNDER_NGINX_AVAILABLE": str(nginx_available),
        "KIVOU_FOUNDER_NGINX_ENABLED": str(nginx_enabled),
        "KIVOU_FOUNDER_HEALTH_URL": "http://127.0.0.1:18011/healthz",
    }
    return env, log, release, founder_frontend, old_founder


def test_founder_frontend_parent_is_nginx_traversable(tmp_path: pathlib.Path) -> None:
    env, _, _, founder_frontend, _ = _active_production_environment(tmp_path)
    founder_parent = founder_frontend.parent
    founder_parent.chmod(0o700)

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert founder_parent.stat().st_mode & 0o777 == 0o755
    assert founder_parent.stat().st_uid == os.getuid()
    assert founder_parent.stat().st_gid == os.getgid()


def test_founder_health_retries_until_ready(tmp_path: pathlib.Path) -> None:
    counter = tmp_path / "curl-count"
    env, log, _, _, _ = _active_production_environment(
        tmp_path,
        curl_body=(
            'count=0; [[ ! -f "$KIVOU_TEST_CURL_COUNT" ]] || read -r count < "$KIVOU_TEST_CURL_COUNT"\n'
            'count=$((count + 1)); printf "%s\\n" "$count" > "$KIVOU_TEST_CURL_COUNT"\n'
            'if (( count < 3 )); then exit 22; fi\n'
        ),
    )
    env["KIVOU_TEST_CURL_COUNT"] = str(counter)
    env["KIVOU_FOUNDER_HEALTH_ATTEMPTS"] = "5"
    env["KIVOU_FOUNDER_HEALTH_DELAY_SECONDS"] = "0"

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8").count("curl --fail") == 3


def test_founder_health_retry_exhaustion_is_bounded(tmp_path: pathlib.Path) -> None:
    env, log, _, _, _ = _active_production_environment(
        tmp_path,
        curl_body="exit 22\n",
    )
    env["KIVOU_FOUNDER_HEALTH_ATTEMPTS"] = "3"
    env["KIVOU_FOUNDER_HEALTH_DELAY_SECONDS"] = "0"

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "readiness Founder" in result.stderr
    assert log.read_text(encoding="utf-8").count("curl --fail") == 3


def test_fresh_production_release_builds_and_activates_founder(
    tmp_path: pathlib.Path,
) -> None:
    env, log, release, founder_frontend, _ = _active_production_environment(tmp_path)
    backend = pathlib.Path(env["KIVOU_BACKEND_LINK"])
    frontend = pathlib.Path(env["KIVOU_FRONTEND_LINK"])
    old_backend = tmp_path / "old-backend"
    old_frontend = tmp_path / "old-frontend"
    old_backend.mkdir()
    old_frontend.mkdir()
    backend.unlink()
    frontend.unlink()
    backend.symlink_to(old_backend)
    frontend.symlink_to(old_frontend)

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands = log.read_text(encoding="utf-8")
    customer_build = f"npm --prefix {release / 'frontend'} run build"
    founder_build = f"npm --prefix {release / 'frontend'} run build:founder"
    assert customer_build in commands
    assert founder_build in commands
    assert commands.index(customer_build) < commands.index(founder_build)
    assert founder_frontend.resolve() == release / "frontend/dist-founder"


def test_active_production_release_synchronizes_founder_surface(tmp_path: pathlib.Path) -> None:
    env, log, release, founder_frontend, old_founder = _active_production_environment(
        tmp_path
    )

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert founder_frontend.resolve() == release / "frontend/dist-founder"
    assert pathlib.Path(f"{founder_frontend}.previous").resolve() == old_founder
    assert pathlib.Path(env["KIVOU_FOUNDER_SYSTEMD_UNIT_PATH"]).read_text(
        encoding="utf-8"
    ) == "founder unit\n"
    assert pathlib.Path(env["KIVOU_FOUNDER_NGINX_AVAILABLE"]).read_text(
        encoding="utf-8"
    ) == "founder nginx\n"
    assert pathlib.Path(env["KIVOU_FOUNDER_NGINX_ENABLED"]).resolve() == pathlib.Path(
        env["KIVOU_FOUNDER_NGINX_AVAILABLE"]
    )
    commands = log.read_text(encoding="utf-8")
    assert (
        f"runuser --user kivou -- test -r {env['KIVOU_FOUNDER_ENV_FILE']}" in commands
    )
    assert (
        "runuser --user "
        f"{env['KIVOU_FOUNDER_NGINX_WORKER_USER']} -- test -r "
        f"{env['KIVOU_FOUNDER_HTPASSWD_FILE']}"
    ) in commands
    assert "systemctl enable kivou-founder-api.service" in commands
    assert "systemctl restart kivou-founder-api.service" in commands
    assert "curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18011/healthz" in commands
    assert "nginx -t" in commands
    assert "systemctl reload nginx" in commands


def test_production_prerequisites_fail_before_founder_mutation(tmp_path: pathlib.Path) -> None:
    env, log, _, founder_frontend, old_founder = _active_production_environment(tmp_path)
    pathlib.Path(env["KIVOU_FOUNDER_ENV_FILE"]).unlink()

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Founder" in result.stderr
    assert founder_frontend.resolve() == old_founder
    assert not pathlib.Path(env["KIVOU_FOUNDER_SYSTEMD_UNIT_PATH"]).exists()
    assert not pathlib.Path(env["KIVOU_FOUNDER_NGINX_AVAILABLE"]).exists()
    assert "systemctl" not in log.read_text(encoding="utf-8")


def test_incomplete_founder_environment_fails_before_mutation(
    tmp_path: pathlib.Path,
) -> None:
    env, log, _, founder_frontend, old_founder = _active_production_environment(tmp_path)
    pathlib.Path(env["KIVOU_FOUNDER_ENV_FILE"]).write_text(
        "KIVOU_FOUNDER_HOSTNAME=control.kivou.eu\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "environnement Founder incomplet" in result.stderr
    assert founder_frontend.resolve() == old_founder
    assert "systemctl" not in log.read_text(encoding="utf-8")


def test_mismatched_founder_origin_secret_fails_without_logging_values(
    tmp_path: pathlib.Path,
) -> None:
    env, log, _, founder_frontend, old_founder = _active_production_environment(tmp_path)
    mismatched_secret = "b" * 64
    pathlib.Path(env["KIVOU_FOUNDER_ORIGIN_SECRET_FILE"]).write_text(
        f'set $kivou_founder_origin_secret "{mismatched_secret}";\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "prérequis Founder invalide" in result.stderr
    assert "a" * 64 not in result.stderr
    assert mismatched_secret not in result.stderr
    assert founder_frontend.resolve() == old_founder
    assert "systemctl" not in log.read_text(encoding="utf-8")


def test_founder_env_must_be_readable_by_service_user(tmp_path: pathlib.Path) -> None:
    env, log, _, founder_frontend, old_founder = _active_production_environment(tmp_path)
    env["KIVOU_TEST_DENY_READ_AS_USER"] = "kivou"

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "illisible par l'utilisateur du service Founder" in result.stderr
    assert founder_frontend.resolve() == old_founder
    assert "systemctl" not in log.read_text(encoding="utf-8")


def test_nginx_validation_failure_restores_prior_founder_site(tmp_path: pathlib.Path) -> None:
    counter = tmp_path / "nginx-count"
    env, log, _, _, _ = _active_production_environment(
        tmp_path,
        nginx_body=(
            'count=0; [[ ! -f "$KIVOU_TEST_NGINX_COUNT" ]] || read -r count < "$KIVOU_TEST_NGINX_COUNT"\n'
            'count=$((count + 1)); printf "%s\\n" "$count" > "$KIVOU_TEST_NGINX_COUNT"\n'
            'if (( count == 1 )); then exit 23; fi\n'
        ),
    )
    env["KIVOU_TEST_NGINX_COUNT"] = str(counter)
    available = pathlib.Path(env["KIVOU_FOUNDER_NGINX_AVAILABLE"])
    enabled = pathlib.Path(env["KIVOU_FOUNDER_NGINX_ENABLED"])
    prior_target = tmp_path / "prior-founder-site.conf"
    prior_target.write_text("prior target\n", encoding="utf-8")
    available.write_text("prior available\n", encoding="utf-8")
    enabled.symlink_to(prior_target)

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert available.read_text(encoding="utf-8") == "prior available\n"
    assert enabled.is_symlink()
    assert os.readlink(enabled) == str(prior_target)
    commands = log.read_text(encoding="utf-8")
    assert commands.count("nginx -t") == 2
    assert commands.count("systemctl reload nginx") == 1
    assert "intervention manuelle" not in result.stderr


def test_nginx_candidate_mutation_failure_restores_prior_site(
    tmp_path: pathlib.Path,
) -> None:
    env, log, _, _, _ = _active_production_environment(tmp_path)
    env["KIVOU_TEST_FAIL_NGINX_INSTALL"] = "1"
    available = pathlib.Path(env["KIVOU_FOUNDER_NGINX_AVAILABLE"])
    enabled = pathlib.Path(env["KIVOU_FOUNDER_NGINX_ENABLED"])
    prior_target = tmp_path / "prior-founder-site.conf"
    prior_target.write_text("prior target\n", encoding="utf-8")
    available.write_text("prior available\n", encoding="utf-8")
    enabled.symlink_to(prior_target)

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert available.read_text(encoding="utf-8") == "prior available\n"
    assert enabled.is_symlink()
    assert os.readlink(enabled) == str(prior_target)
    assert not pathlib.Path(f"{enabled}.next").exists()
    commands = log.read_text(encoding="utf-8")
    assert commands.count("nginx -t") == 1
    assert commands.count("systemctl reload nginx") == 1


def test_nginx_restore_failure_preserves_and_reports_backups(
    tmp_path: pathlib.Path,
) -> None:
    env, _, _, _, _ = _active_production_environment(tmp_path)
    rollback_parent = tmp_path / "rollback"
    rollback_parent.mkdir()
    env["TMPDIR"] = str(rollback_parent)
    env["KIVOU_TEST_FAIL_NGINX_INSTALL"] = "1"
    env["KIVOU_TEST_FAIL_NGINX_RESTORE"] = "1"
    available = pathlib.Path(env["KIVOU_FOUNDER_NGINX_AVAILABLE"])
    enabled = pathlib.Path(env["KIVOU_FOUNDER_NGINX_ENABLED"])
    prior_target = tmp_path / "prior-founder-site.conf"
    prior_target.write_text("prior target\n", encoding="utf-8")
    available.write_text("prior available\n", encoding="utf-8")
    enabled.symlink_to(prior_target)

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    marker = "sauvegardes conservées : "
    assert marker in result.stderr
    reported_path = result.stderr.split(marker, 1)[1].split(" ;", 1)[0]
    rollback_dir = pathlib.Path(reported_path)
    assert rollback_dir.parent == rollback_parent
    assert rollback_dir.is_dir()
    assert (rollback_dir / "available").read_text(encoding="utf-8") == (
        "prior available\n"
    )
    assert (rollback_dir / "enabled").is_symlink()
    assert os.readlink(rollback_dir / "enabled") == str(prior_target)
    assert "intervention manuelle requise" in result.stderr


def test_nginx_reload_failure_restores_and_revalidates_prior_founder_site(
    tmp_path: pathlib.Path,
) -> None:
    counter = tmp_path / "reload-count"
    env, log, _, _, _ = _active_production_environment(
        tmp_path,
        systemctl_body=(
            'if [[ "$*" == "reload nginx" ]]; then '
            'count=0; [[ ! -f "$KIVOU_TEST_RELOAD_COUNT" ]] || read -r count < "$KIVOU_TEST_RELOAD_COUNT"; '
            'count=$((count + 1)); printf "%s\\n" "$count" > "$KIVOU_TEST_RELOAD_COUNT"; '
            'if (( count == 1 )); then exit 24; fi; fi\n'
        ),
    )
    env["KIVOU_TEST_RELOAD_COUNT"] = str(counter)
    available = pathlib.Path(env["KIVOU_FOUNDER_NGINX_AVAILABLE"])
    enabled = pathlib.Path(env["KIVOU_FOUNDER_NGINX_ENABLED"])
    prior_target = tmp_path / "prior-founder-site.conf"
    prior_target.write_text("prior target\n", encoding="utf-8")
    available.write_text("prior available\n", encoding="utf-8")
    enabled.symlink_to(prior_target)

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert available.read_text(encoding="utf-8") == "prior available\n"
    assert enabled.is_symlink()
    assert os.readlink(enabled) == str(prior_target)
    commands = log.read_text(encoding="utf-8")
    assert commands.count("nginx -t") == 2
    assert commands.count("systemctl reload nginx") == 2
    assert "intervention manuelle" not in result.stderr


def test_nginx_rollback_reload_failure_requires_manual_intervention(
    tmp_path: pathlib.Path,
) -> None:
    env, log, _, _, _ = _active_production_environment(
        tmp_path,
        systemctl_body='if [[ "$*" == "reload nginx" ]]; then exit 24; fi\n',
    )
    rollback_parent = tmp_path / "rollback"
    rollback_parent.mkdir()
    env["TMPDIR"] = str(rollback_parent)
    available = pathlib.Path(env["KIVOU_FOUNDER_NGINX_AVAILABLE"])
    enabled = pathlib.Path(env["KIVOU_FOUNDER_NGINX_ENABLED"])
    prior_target = tmp_path / "prior-founder-site.conf"
    prior_target.write_text("prior target\n", encoding="utf-8")
    available.write_text("prior available\n", encoding="utf-8")
    enabled.symlink_to(prior_target)

    result = subprocess.run(
        [str(SCRIPT), "production", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert available.read_text(encoding="utf-8") == "prior available\n"
    assert enabled.is_symlink()
    assert os.readlink(enabled) == str(prior_target)
    assert not pathlib.Path(f"{enabled}.next").exists()
    assert "ROLLBACK NGINX FOUNDER INCOMPLET" in result.stderr
    assert "intervention manuelle requise" in result.stderr
    reported_path = result.stderr.split("sauvegardes conservées : ", 1)[1].split(
        " ;", 1
    )[0]
    assert pathlib.Path(reported_path).parent == rollback_parent
    assert pathlib.Path(reported_path).is_dir()
    commands = log.read_text(encoding="utf-8")
    assert commands.count("nginx -t") == 2
    assert commands.count("systemctl reload nginx") == 2


def test_founder_build_is_guarded_to_production() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    founder_build = 'npm --prefix "$KIVOU_RELEASE_DIR/frontend" run build:founder'
    production_guard = 'if [[ "$KIVOU_ENVIRONMENT" == "production" ]]; then'
    assert founder_build in script
    assert script.rfind(production_guard, 0, script.index(founder_build)) >= 0


def test_invalid_source_checkout_stops_before_deploy_actions(tmp_path: pathlib.Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_bin(fake_bin, "git", "exit 1\n")
    source = tmp_path / "source"
    source.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "KIVOU_SOURCE_DIR": str(source),
        "KIVOU_DATABASE_URL": "postgresql://kivou@localhost/kivou",
        "KIVOU_MIGRATION_ADMIN_URL": "postgresql://deploy@localhost/postgres",
    }

    result = subprocess.run(
        [str(SCRIPT), "staging", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f"[kivou-deploy] ÉCHEC : checkout Git introuvable ou invalide : {source}"
    )


def test_source_checkout_must_be_owned_by_kivou(tmp_path: pathlib.Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_bin(fake_bin, "git", "exit 0\n")
    _fake_bin(fake_bin, "stat", "printf 'root:root\\n'\n")
    source = tmp_path / "source"
    source.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "KIVOU_SOURCE_DIR": str(source),
        "KIVOU_DATABASE_URL": "postgresql://kivou@localhost/kivou",
        "KIVOU_MIGRATION_ADMIN_URL": "postgresql://deploy@localhost/postgres",
    }

    result = subprocess.run(
        [str(SCRIPT), "staging", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == f"[kivou-deploy] ÉCHEC : propriétaire du checkout invalide : {source}"


def test_rehearsal_failure_never_touches_the_live_release(tmp_path: pathlib.Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    source = tmp_path / "source"
    source.mkdir()
    releases = tmp_path / "releases"
    live_backend = tmp_path / "app"
    live_frontend = tmp_path / "www"
    backup = tmp_path / "backup.sh"
    readiness = tmp_path / "readiness.sh"
    backup.write_text(
        "#!/usr/bin/env bash\nset -eu\nmkdir -p \"$KIVOU_BACKUP_DIR\"\ntouch \"$KIVOU_BACKUP_DIR/test.dump\"\n",
        encoding="utf-8",
    )
    readiness.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for helper in (backup, readiness):
        helper.chmod(0o755)

    recorder = 'printf "%s %s\\n" "$(basename "$0")" "$*" >> "$KIVOU_TEST_LOG"\n'
    for command in ("chmod", "install", "npm", "createdb", "dropdb", "pg_restore", "systemctl"):
        _fake_bin(fake_bin, command, recorder)
    _fake_bin(fake_bin, "stat", "printf 'kivou:kivou\\n'\n")
    _fake_bin(
        fake_bin,
        "runuser",
        recorder + 'shift 3\nexec "$@"\n',
    )
    _fake_bin(
        fake_bin,
        "git",
        recorder
            + 'if [[ "$*" == *"worktree add"* ]]; then release="$KIVOU_RELEASES_DIR/staging-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; mkdir -p "$release/frontend" "$release/ops/systemd" "$release/ops/bin"; touch "$release/ops/systemd/kivou-api.service" "$release/ops/systemd/kivou-founder-api.service" "$release/ops/bin/kivou-disk-alert" "$release/ops/bin/kivou-disk-maintenance"; /bin/chmod +x "$release/ops/bin/kivou-disk-alert" "$release/ops/bin/kivou-disk-maintenance"; fi\n'
        + 'if [[ "$*" == *"rev-parse HEAD"* ]]; then printf "%s\\n" "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; fi\n',
    )
    _fake_bin(
        fake_bin,
        "uv",
        recorder
        + 'printf "database_url %s\\n" "${KIVOU_DATABASE_URL:-}" >> "$KIVOU_TEST_LOG"\n'
        + 'case "${KIVOU_DATABASE_URL:-}" in (*kivou_rehearsal_*) exit 42;; esac\n',
    )

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "KIVOU_TEST_LOG": str(log),
        "KIVOU_SOURCE_DIR": str(source),
        "KIVOU_RELEASES_DIR": str(releases),
        "KIVOU_BACKEND_LINK": str(live_backend),
        "KIVOU_FRONTEND_LINK": str(live_frontend),
        "KIVOU_DATABASE_URL": "postgresql://kivou@localhost/kivou",
        "KIVOU_MIGRATION_ADMIN_URL": "postgresql://deploy:admin-secret@localhost/postgres",
        "KIVOU_BACKUP_SCRIPT": str(backup),
        "KIVOU_READINESS_SCRIPT": str(readiness),
        "KIVOU_BACKUP_DIR": str(tmp_path / "backups"),
        "KIVOU_PLAYWRIGHT_BROWSERS_DIR": str(tmp_path / "playwright"),
    }
    result = subprocess.run(
        [str(SCRIPT), "staging", "a" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    commands = log.read_text(encoding="utf-8")
    assert "kivou_rehearsal_" in commands
    assert "database_url postgresql+psycopg://deploy:admin-secret@localhost/kivou_rehearsal_" in commands
    assert "database_url postgresql://kivou@localhost/kivou_rehearsal_" not in commands
    assert "admin-secret" not in "\n".join(
        line for line in commands.splitlines() if not line.startswith("database_url ")
    )
    assert "runuser --user kivou --" in commands
    assert (
        "runuser --user kivou -- git "
        f"-c safe.directory={source} -C {source} fetch --no-tags origin main"
    ) in commands
    assert (
        "runuser --user kivou -- git "
        f"-c safe.directory={source} -C {source} worktree add --detach"
    ) in commands
    assert (
        "runuser --user kivou -- git -C "
        f"{releases / f'staging-{'a' * 40}'} rev-parse HEAD"
    ) in commands
    assert "systemctl restart" not in commands
    assert "migrate_to_latest" in commands
    assert not live_backend.exists()
    assert not live_frontend.exists()

    _fake_bin(fake_bin, "uv", recorder)
    _fake_bin(
        fake_bin,
        "git",
        recorder
            + 'if [[ "$*" == *"worktree add"* ]]; then release="$KIVOU_RELEASES_DIR/staging-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"; mkdir -p "$release/frontend/dist" "$release/ops/systemd" "$release/ops/bin"; touch "$release/ops/systemd/kivou-api.service" "$release/ops/systemd/kivou-founder-api.service" "$release/ops/bin/kivou-disk-alert" "$release/ops/bin/kivou-disk-maintenance"; /bin/chmod +x "$release/ops/bin/kivou-disk-alert" "$release/ops/bin/kivou-disk-maintenance"; fi\n'
        + 'if [[ "$*" == *"rev-parse HEAD"* ]]; then printf "%s\\n" "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"; fi\n',
    )
    success = subprocess.run(
        [str(SCRIPT), "staging", "b" * 40],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert success.returncode == 0, success.stderr
    success_commands = log.read_text(encoding="utf-8")
    assert "build:founder" not in success_commands
    assert "kivou-founder-api.service" not in success_commands
    assert "nginx -t" not in success_commands
    permission_command = f"chmod -R a+rX {releases / f'staging-{'b' * 40}'}"
    assert permission_command in success_commands
    assert success_commands.rfind(permission_command) > success_commands.rfind("uv run")
    assert live_backend.resolve() == releases / f"staging-{'b' * 40}"
    assert live_frontend.resolve() == releases / f"staging-{'b' * 40}" / "frontend/dist"
