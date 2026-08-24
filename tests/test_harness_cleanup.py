"""Le nettoyage des bases jetables — et pourquoi il doit rendre la session rouge.

Le troc qu'il ne faut pas faire
───────────────────────────────
Une première version faisait échouer un test RÉUSSI quand son démontage
échouait, et abandonnait au passage les bases suivantes. En corrigeant cela, la
version suivante est tombée dans le travers inverse : tout échec devenait un
simple avertissement, et la suite restait VERTE pendant que les bases
s'accumulaient. La panne ressurgissait bien plus tard — épuisement de
`max_connections` ou de disque — dans une exécution sans rapport.

Les deux propriétés doivent tenir ENSEMBLE : nettoyer jusqu'au bout malgré un
échec, et le dire assez fort pour que personne ne l'ignore.
"""

from __future__ import annotations

import pathlib

import pytest
from conftest import _redact, drain_disposable_databases


class _Engine:
    """Un moteur qui note qu'on l'a libéré."""

    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Admin(_Engine):
    """Une connexion d'administration qui réussit — ou refuse — la suppression."""

    def __init__(self, *, fails: bool = False, message: str = "boom") -> None:
        super().__init__()
        self.fails = fails
        self.message = message
        self.dropped: list[str] = []

    def connect(self):
        if self.fails:
            raise RuntimeError(self.message)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def execution_options(self, **_kwargs):
        return self

    def execute(self, statement) -> None:
        self.dropped.append(str(statement))


def test_a_later_database_is_dropped_despite_an_earlier_failure() -> None:
    """La propriété qui compte : un échec ne doit rien laisser derrière lui.

    La pile est dépilée par la fin ; on inscrit donc la base « suivante » en
    premier pour qu'elle soit traitée APRÈS celle qui échoue.
    """
    survivor_admin = _Admin()
    failing_admin = _Admin(fails=True)
    survivor_engine, failing_engine = _Engine(), _Engine()
    registry = [
        (survivor_engine, survivor_admin, "kivou_test_survivante"),
        (failing_engine, failing_admin, "kivou_test_echouante"),
    ]

    failures = drain_disposable_databases(registry)

    assert registry == [], "toutes les entrées doivent être traitées"
    assert len(failures) == 1, f"un seul échec attendu : {failures}"
    assert "kivou_test_echouante" in failures[0]
    assert survivor_admin.dropped, "la base SUIVANTE doit tout de même être supprimée"
    assert "kivou_test_survivante" in survivor_admin.dropped[0]
    assert survivor_engine.disposed and failing_engine.disposed


def test_a_failed_cleanup_is_reported_not_swallowed() -> None:
    """Un échec doit ressortir — c'est ce qui rendra la session rouge."""
    registry = [(_Engine(), _Admin(fails=True, message="permission denied"), "kivou_test_x")]

    failures = drain_disposable_databases(registry)

    assert failures, "un échec silencieux laisserait la suite verte"
    assert "permission denied" in failures[0], "le motif doit être lisible"


def test_a_clean_run_reports_nothing() -> None:
    """La garde ne doit pas rendre rouge une session saine."""
    registry = [(_Engine(), _Admin(), "kivou_test_ok")]

    assert drain_disposable_databases(registry) == []


# ─── Aucun identifiant ne doit ressortir ──────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        'connection to "postgresql://kivou:s3cr3t@db:5432/x" failed',
        "FATAL: password=s3cr3t rejected",
        "could not connect: user=kivou password = s3cr3t",
    ],
    ids=["url", "password-kv", "password-spaced"],
)
def test_no_credential_survives_redaction(message: str) -> None:
    """Ces messages partent dans un avertissement puis dans un rapport de CI.

    Les pilotes citent volontiers l'URL qui a échoué, mot de passe compris.
    Rien de ce qui ouvre quoi que ce soit ne doit y survivre.
    """
    assert "s3cr3t" not in _redact(message)


def test_redaction_keeps_the_diagnosis_readable() -> None:
    """Masquer ne doit pas rendre le message inutile."""
    redacted = _redact('connection to "postgresql://kivou:s3cr3t@db:5432/x" failed')

    assert "failed" in redacted
    assert "db:5432" in redacted, "l'hôte reste utile au diagnostic"
    assert "<masque>" in redacted


def test_a_failure_message_reaches_the_report_without_its_credentials() -> None:
    """Bout en bout : l'échec collecté est déjà expurgé."""
    admin = _Admin(fails=True, message='auth to "postgresql://kivou:s3cr3t@db/x" failed')

    (failure,) = drain_disposable_databases([(_Engine(), admin, "kivou_test_y")])

    assert "s3cr3t" not in failure
    assert "kivou_test_y" in failure


# ─── La session doit devenir ROUGE ────────────────────────────────────────────


def test_a_failed_cleanup_turns_the_whole_session_red(tmp_path) -> None:
    """Le test réussit, et la SESSION échoue tout de même.

    C'est la propriété que la version précédente avait perdue : elle
    n'avertissait que par un `warning`, donc la suite restait verte pendant que
    les bases s'accumulaient. Ici une vraie session pytest est lancée en
    sous-processus — seule façon d'observer un code de sortie.

    Le test interne PASSE : on vérifie donc bien que c'est le NETTOYAGE, et non
    le test, qui rend la session rouge.
    """
    import subprocess
    import sys

    inner = tmp_path / "test_inner_cleanup.py"
    inner.write_text(
        "from conftest import register_disposable_database\n"
        "\n"
        "\n"
        "class _Boom:\n"
        "    def dispose(self):\n"
        "        pass\n"
        "\n"
        "    def connect(self):\n"
        '        raise RuntimeError(\'auth to "postgresql://u:s3cr3t@db/x" refused\')\n'
        "\n"
        "\n"
        "def test_passes_but_leaves_a_database_behind():\n"
        "    register_disposable_database(_Boom(), _Boom(), 'kivou_test_orpheline')\n"
        "    assert True\n"
    )

    completed = subprocess.run(
        # `-p conftest` : le fichier de test vit hors de `tests/`, donc pytest ne
        # ramasserait pas le conftest du dépôt. L'importer comme MODULE ne suffit
        # pas — ses hooks ne se déclencheraient pas. Il faut le charger comme
        # GREFFON pour que `pytest_sessionfinish` s'exécute.
        [
            sys.executable, "-m", "pytest", str(inner),
            "-q", "-p", "no:cacheprovider", "-p", "conftest",
        ],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).resolve().parent,
        timeout=180,
        check=False,
    )
    output = completed.stdout + completed.stderr

    assert "1 passed" in output, f"le test interne doit RÉUSSIR :\n{output}"
    assert completed.returncode != 0, (
        f"la session doit être ROUGE malgré le test réussi :\n{output}"
    )
    assert "kivou_test_orpheline" in output, "la base non supprimée doit être nommée"
    assert "s3cr3t" not in output, "aucun identifiant ne doit apparaître dans le rapport"
