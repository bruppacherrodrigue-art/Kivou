"""RTL-03 / #39 — le runtime de sauvegarde, exercé sans base ni réseau.

Pourquoi des exécutables simulés
────────────────────────────────
Le script parle à `pg_dump` et `pg_restore`. Les appeler pour de vrai
demanderait un PostgreSQL vivant, et #39 interdit explicitement de toucher à
une base active pendant les tests. On place donc de faux binaires en tête de
`PATH` : ils enregistrent leurs arguments et rendent le code de sortie qu'on
leur demande. Ce qui est testé reste le VRAI script — sa normalisation d'URL,
son ordre d'opérations, ses permissions, sa rétention et son verrou.

Ce qui n'est pas testé ici
──────────────────────────
Qu'un dump PostgreSQL réel soit restaurable. Cela demande un serveur et une
base isolée : c'est la validation staging de #39, pas un test unitaire.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "ops" / "bin" / "kivou-backup.sh"

#: Les codes que `ops/README.md` promet à qui lira un journal systemd. Les
#: affirmer ici évite que la documentation dérive du script en silence.
EX_USAGE = 64
EX_UNAVAILABLE = 69
EX_SOFTWARE = 70
EX_TEMPFAIL = 75

#: Une URL SQLAlchemy de TEST. Le mot de passe est inventé et n'ouvre rien ;
#: il n'existe que pour prouver qu'aucune sortie ne le laisse filtrer.
TEST_PASSWORD = "s3cr3t-de-test-jamais-reel"
SQLALCHEMY_URL = f"postgresql+psycopg://kivou:{TEST_PASSWORD}@10.0.0.5:5432/kivou_staging"
#: La même URL en libpq, DÉBARRASSÉE du mot de passe : c'est la seule forme qui
#: a le droit d'atteindre la ligne de commande, où `ps` la rendrait publique.
LIBPQ_URL = "postgresql://kivou@10.0.0.5:5432/kivou_staging"

pytestmark = pytest.mark.skipif(
    shutil.which("flock") is None or shutil.which("bash") is None,
    reason="le runtime de sauvegarde suppose bash et flock (util-linux)",
)


# ─── Un environnement d'exécution jetable ─────────────────────────────────────


class Runtime:
    """Un `PATH` truqué, un répertoire de sauvegarde neuf, et rien d'autre."""

    def __init__(self, tmp_path: pathlib.Path) -> None:
        self.root = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.backup_dir = tmp_path / "backups"
        self.dump_args = tmp_path / "pg_dump.args"
        self.restore_args = tmp_path / "pg_restore.args"
        self._write_fakes()

    def _write_fakes(self) -> None:
        # Le faux `pg_dump` écrit un fichier de la taille demandée, à l'endroit
        # demandé : c'est tout ce dont le script a besoin pour être exercé.
        self._install(
            "pg_dump",
            f"""
            printf '%s\\n' "$*" >> {self.dump_args}
            out=""
            for arg in "$@"; do
                case "$arg" in --file=*) out="${{arg#--file=}}" ;; esac
            done
            [ -n "$out" ] || {{ echo "faux pg_dump : --file= absent" >&2; exit 2; }}
            printf 'PGPASSWORD=%s\n' "${{PGPASSWORD-<absent>}}" >> {self.dump_args}
            if [ "${{FAKE_PG_DUMP_EXIT:-0}}" -ne 0 ]; then
                # Un vrai outil est bavard quand il échoue : on le simule, pour
                # que la garde « aucun secret en sortie » ait quelque chose à
                # arrêter plutôt que de constater un silence.
                echo "faux pg_dump : échec de connexion sur $*" >&2
                exit "${{FAKE_PG_DUMP_EXIT}}"
            fi
            head -c "${{FAKE_DUMP_BYTES:-8192}}" /dev/zero > "$out"
            """,
        )
        self._install(
            "pg_restore",
            f"""
            printf '%s\\n' "$*" >> {self.restore_args}
            exit "${{FAKE_PG_RESTORE_EXIT:-0}}"
            """,
        )

    def _install(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -u\n" + textwrap.dedent(body))
        path.chmod(0o755)

    def run(self, *, url: str | None = SQLALCHEMY_URL, **env: str) -> subprocess.CompletedProcess:
        environment = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.root),
            "KIVOU_BACKUP_DIR": str(self.backup_dir),
        }
        if url is not None:
            environment["KIVOU_DATABASE_URL"] = url
        environment.update(env)
        return subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=60,
        )

    # ── lectures ──
    def dumps(self) -> list[pathlib.Path]:
        return sorted(self.backup_dir.glob("kivou-*.dump"))

    def leftovers(self) -> list[pathlib.Path]:
        """Tout fichier du répertoire qui n'est PAS un dump définitif."""
        return sorted(
            p
            for p in self.backup_dir.iterdir()
            if p.is_file() and not p.name.endswith(".dump") and not p.name.endswith(".lock")
        )

    def dump_command(self) -> str:
        return self.dump_args.read_text()

    def restore_command(self) -> str:
        return self.restore_args.read_text()


@pytest.fixture
def runtime(tmp_path: pathlib.Path) -> Runtime:
    return Runtime(tmp_path)


# ─── Le chemin nominal ────────────────────────────────────────────────────────


def test_a_valid_sqlalchemy_url_is_normalized_for_postgresql_tools(runtime: Runtime):
    """`postgresql+psycopg://` nomme un pilote Python ; `pg_dump` l'ignore."""
    result = runtime.run()

    assert result.returncode == 0, result.stderr
    assert LIBPQ_URL in runtime.dump_command()
    assert "psycopg" not in runtime.dump_command()


def test_the_password_travels_by_environment_never_on_the_command_line(runtime: Runtime):
    """`ps` est public sur un hôte partagé : un mot de passe en argv fuit."""
    assert runtime.run().returncode == 0

    recorded = runtime.dump_command()
    assert f"PGPASSWORD={TEST_PASSWORD}" in recorded, "libpq doit recevoir le mot de passe"
    arguments = "\n".join(l for l in recorded.splitlines() if not l.startswith("PGPASSWORD="))
    assert TEST_PASSWORD not in arguments


def test_the_dump_is_custom_format_without_owner_or_privileges(runtime: Runtime):
    assert runtime.run().returncode == 0
    command = runtime.dump_command()
    assert "--format=custom" in command
    assert "--no-owner" in command
    assert "--no-privileges" in command


@pytest.mark.parametrize(
    "given",
    [
        "postgresql+psycopg://u:p@h:5432/d",
        "postgresql+asyncpg://u:p@h:5432/d",
        "postgres://u:p@h:5432/d",
        "postgresql://u:p@h:5432/d",
    ],
    ids=["psycopg", "asyncpg", "postgres-scheme", "already-libpq"],
)
def test_every_postgresql_variant_reaches_the_tools_as_libpq(runtime: Runtime, given: str):
    assert runtime.run(url=given).returncode == 0
    assert "postgresql://u@h:5432/d" in runtime.dump_command()


# ─── Configuration absente ou hors sujet ──────────────────────────────────────


def test_a_missing_url_fails_clearly_without_dumping(runtime: Runtime):
    result = runtime.run(url=None)

    assert result.returncode == EX_USAGE
    assert "KIVOU_DATABASE_URL" in result.stdout + result.stderr
    assert not runtime.dump_args.exists()


@pytest.mark.parametrize(
    "given",
    ["sqlite+pysqlite:///kivou.db", "mysql://u:p@h/d", "pas-une-url"],
    ids=["sqlite", "mysql", "garbage"],
)
def test_a_non_postgresql_url_is_refused(runtime: Runtime, given: str):
    """Défaut fermé : mieux vaut pas de sauvegarde qu'une sauvegarde de rien."""
    result = runtime.run(url=given)

    assert result.returncode == EX_USAGE
    assert not runtime.dump_args.exists()
    assert runtime.dumps() == []


@pytest.mark.parametrize(
    "override, missing",
    [("KIVOU_PG_DUMP", "pg_dump"), ("KIVOU_PG_RESTORE", "pg_restore")],
)
def test_a_missing_dependency_fails_clearly(runtime: Runtime, override: str, missing: str):
    """Sans l'outil, le script doit le DIRE, pas échouer obscurément.

    Le point d'injection sert aussi en production : plusieurs distributions
    n'exposent `pg_dump` que sous un chemin versionné.
    """
    result = runtime.run(**{override: "/nonexistent/bin/" + missing})

    assert result.returncode == EX_UNAVAILABLE
    assert missing in result.stdout + result.stderr
    assert runtime.dumps() == []


# ─── Les échecs de production d'un dump ───────────────────────────────────────


def test_a_failing_pg_dump_leaves_no_backup_behind(runtime: Runtime):
    result = runtime.run(FAKE_PG_DUMP_EXIT="1")

    assert result.returncode == EX_SOFTWARE
    assert runtime.dumps() == []
    assert runtime.leftovers() == []


def test_a_suspiciously_small_dump_is_refused(runtime: Runtime):
    """Un dump minuscule est un échec déguisé en succès."""
    result = runtime.run(FAKE_DUMP_BYTES="10", KIVOU_BACKUP_MIN_BYTES="4096")

    assert result.returncode == EX_SOFTWARE
    assert runtime.dumps() == []
    assert runtime.leftovers() == []


def test_a_dump_that_pg_restore_cannot_list_is_refused(runtime: Runtime):
    """Un fichier de la bonne taille peut être illisible : on le VÉRIFIE."""
    result = runtime.run(FAKE_PG_RESTORE_EXIT="1")

    assert result.returncode == EX_SOFTWARE
    assert runtime.dumps() == []
    assert runtime.leftovers() == []


def test_the_dump_is_listed_before_it_is_accepted(runtime: Runtime):
    assert runtime.run().returncode == 0
    assert "--list" in runtime.restore_command()


# ─── Permissions et atomicité ─────────────────────────────────────────────────


def test_the_backup_directory_is_created_and_private(runtime: Runtime):
    """Le répertoire n'existe pas encore : le script doit le poser, fermé."""
    assert not runtime.backup_dir.exists()

    assert runtime.run().returncode == 0

    assert runtime.backup_dir.is_dir()
    assert stat.S_IMODE(runtime.backup_dir.stat().st_mode) == 0o700


def test_the_final_dump_is_readable_by_its_owner_only(runtime: Runtime):
    assert runtime.run().returncode == 0
    (dump,) = runtime.dumps()
    assert stat.S_IMODE(dump.stat().st_mode) == 0o600


def test_the_dump_is_written_elsewhere_then_renamed_into_place(runtime: Runtime):
    """`pg_dump` n'écrit JAMAIS directement le nom définitif.

    Sans cela, un dump interrompu laisse un fichier au nom d'une sauvegarde
    valide — et c'est celui-là qu'on restaurera le jour où il faudra.
    """
    assert runtime.run().returncode == 0
    (dump,) = runtime.dumps()

    (written_to,) = [
        word.removeprefix("--file=")
        for word in runtime.dump_command().split()
        if word.startswith("--file=")
    ]
    assert written_to != str(dump), "pg_dump ne doit pas écrire le nom définitif"
    assert written_to.endswith(".part")
    assert not pathlib.Path(written_to).exists(), "le fichier partiel doit disparaître"


# ─── Rétention ────────────────────────────────────────────────────────────────


def test_retention_removes_old_dumps_after_a_success(runtime: Runtime):
    runtime.backup_dir.mkdir(parents=True)
    old = runtime.backup_dir / "kivou-20200101T000000Z.dump"
    old.write_bytes(b"x" * 8192)
    os.utime(old, (0, 0))

    assert runtime.run(KIVOU_BACKUP_RETENTION_DAYS="14").returncode == 0

    assert not old.exists()
    assert len(runtime.dumps()) == 1


def test_retention_spares_old_dumps_when_the_backup_fails(runtime: Runtime):
    """Le piège mortel : purger après un échec, c'est perdre les bonnes copies."""
    runtime.backup_dir.mkdir(parents=True)
    old = runtime.backup_dir / "kivou-20200101T000000Z.dump"
    old.write_bytes(b"x" * 8192)
    os.utime(old, (0, 0))

    assert runtime.run(FAKE_PG_DUMP_EXIT="1", KIVOU_BACKUP_RETENTION_DAYS="14").returncode != 0

    assert old.exists(), "une sauvegarde ratée ne doit jamais supprimer les anciennes"


def test_retention_spares_dumps_that_pg_restore_rejected(runtime: Runtime):
    runtime.backup_dir.mkdir(parents=True)
    old = runtime.backup_dir / "kivou-20200101T000000Z.dump"
    old.write_bytes(b"x" * 8192)
    os.utime(old, (0, 0))

    assert runtime.run(FAKE_PG_RESTORE_EXIT="1").returncode != 0

    assert old.exists()


def test_retention_keeps_dumps_that_are_still_young(runtime: Runtime):
    runtime.backup_dir.mkdir(parents=True)
    recent = runtime.backup_dir / "kivou-20991231T235959Z.dump"
    recent.write_bytes(b"x" * 8192)

    assert runtime.run(KIVOU_BACKUP_RETENTION_DAYS="14").returncode == 0

    assert recent.exists()


# ─── Secrets ──────────────────────────────────────────────────────────────────


def test_no_output_ever_carries_the_database_password(runtime: Runtime):
    result = runtime.run()

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert TEST_PASSWORD not in output
    assert SQLALCHEMY_URL not in output
    assert LIBPQ_URL not in output


@pytest.mark.parametrize(
    "failure",
    [{"FAKE_PG_DUMP_EXIT": "1"}, {"FAKE_PG_RESTORE_EXIT": "1"}, {"FAKE_DUMP_BYTES": "10"}],
    ids=["dump-failed", "restore-list-failed", "too-small"],
)
def test_no_failure_path_leaks_the_password_either(runtime: Runtime, failure: dict[str, str]):
    """C'est en échouant qu'un script bavarde : c'est là qu'il faut regarder."""
    result = runtime.run(**failure)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert TEST_PASSWORD not in output
    assert SQLALCHEMY_URL not in output


# ─── Verrou ───────────────────────────────────────────────────────────────────


def test_a_second_run_gives_up_while_the_first_holds_the_lock(runtime: Runtime):
    """Deux sauvegardes concurrentes écriraient dans le même répertoire."""
    runtime.backup_dir.mkdir(parents=True, exist_ok=True)
    lock = runtime.backup_dir / "kivou-backup.lock"
    lock.touch()

    holder = subprocess.Popen(["flock", str(lock), "sleep", "10"])
    try:
        result = runtime.run()
    finally:
        holder.kill()
        holder.wait()

    assert result.returncode == EX_TEMPFAIL
    assert runtime.dumps() == []
    assert not runtime.dump_args.exists(), "le verrou doit précéder tout appel à pg_dump"


def test_the_lock_is_released_so_the_next_run_succeeds(runtime: Runtime):
    """Un verrou qui survit à son porteur transformerait le timer en panne."""
    assert runtime.run().returncode == 0
    assert runtime.run().returncode == 0
    assert runtime.dumps() != []
