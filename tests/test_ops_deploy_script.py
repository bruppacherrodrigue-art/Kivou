from __future__ import annotations

import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "ops/bin/kivou-deploy.sh"


def _fake_bin(directory: pathlib.Path, name: str, body: str) -> None:
    target = directory / name
    target.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
    target.chmod(0o755)


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
    for command in ("npm", "createdb", "dropdb", "pg_restore", "systemctl"):
        _fake_bin(fake_bin, command, recorder)
    _fake_bin(
        fake_bin,
        "runuser",
        recorder + 'shift 3\nexec "$@"\n',
    )
    _fake_bin(
        fake_bin,
        "git",
        recorder
        + 'if [[ "$*" == *"worktree add"* ]]; then mkdir -p "$6/frontend"; fi\n'
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
    assert "database_url postgresql://deploy:admin-secret@localhost/kivou_rehearsal_" in commands
    assert "database_url postgresql://kivou@localhost/kivou_rehearsal_" not in commands
    assert "admin-secret" not in "\n".join(
        line for line in commands.splitlines() if not line.startswith("database_url ")
    )
    assert "runuser --user kivou --" in commands
    assert "systemctl restart" not in commands
    assert "migrate_to_latest" in commands
    assert not live_backend.exists()
    assert not live_frontend.exists()
