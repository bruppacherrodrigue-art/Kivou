from __future__ import annotations

import fcntl
import os
import threading

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_prospection_actions_service import NOW, LinkIssuer, MxVerifier, seed

from signals.founder_api.access import FOUNDER_USER_HEADER, ORIGIN_SECRET_HEADER
from signals.founder_api.acquisition_actions import (
    FounderAcquisitionLaunch,
    FounderAcquisitionLauncher,
    FounderAcquisitionLaunchError,
)
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.persistence.schema import prospect_target
from signals.prospection_actions.service import ProspectionActions

ORIGIN_SECRET = "s" * 40


def _actions(engine):
    return ProspectionActions(
        engine,
        email_verifier=MxVerifier(),
        link_issuer=LinkIssuer(),
    )


class FinishedProcess:
    def __init__(self) -> None:
        self.waited = threading.Event()

    def wait(self) -> int:
        self.waited.set()
        return 0


def _launcher(engine, tmp_path, *, popen):
    return FounderAcquisitionLauncher(
        engine,
        clock=lambda: NOW,
        lock_path=tmp_path / "acquisition.lock",
        disabled_path=tmp_path / "acquisition.disabled",
        command=("python", "-m", "signals.acquisition_runtime", "run-once"),
        popen=popen,
    )


def _headers() -> dict[str, str]:
    return {
        FOUNDER_USER_HEADER: "rodrigue",
        ORIGIN_SECRET_HEADER: ORIGIN_SECRET,
    }


class StubLauncher:
    def __init__(self, result=None, error=None) -> None:
        self._result = result
        self._error = error

    def prepare(self):
        if self._error is not None:
            raise self._error
        return self._result


def test_prepare_launches_one_runtime_with_the_shared_lock(
    migrated_sqlite_engine,
    tmp_path,
) -> None:
    launched: list[tuple[tuple[str, ...], dict[str, object]]] = []
    process = FinishedProcess()

    def popen(command, **options):
        launched.append((tuple(command), options))
        return process

    result = _launcher(migrated_sqlite_engine, tmp_path, popen=popen).prepare()

    assert result.accepted is True
    assert result.prepared_today_count == 0
    assert result.daily_pending_cap == 25
    command, options = launched[0]
    assert command[-3:] == ("-m", "signals.acquisition_runtime", "run-once")
    assert len(options["pass_fds"]) == 1
    assert options["start_new_session"] is True
    assert process.waited.wait(timeout=1)


def test_prepare_refuses_a_lock_held_by_another_cycle(
    migrated_sqlite_engine,
    tmp_path,
) -> None:
    lock_path = tmp_path / "acquisition.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(FounderAcquisitionLaunchError) as caught:
            _launcher(
                migrated_sqlite_engine,
                tmp_path,
                popen=lambda *_args, **_options: pytest.fail("must not launch"),
            ).prepare()
    finally:
        os.close(lock_fd)

    assert caught.value.status_code == 409
    assert caught.value.code == "ACQUISITION_ALREADY_RUNNING"
    assert caught.value.message == "Une préparation est déjà en cours."


def test_prepare_refuses_the_zurich_daily_cap(
    migrated_sqlite_engine,
    tmp_path,
) -> None:
    seed(migrated_sqlite_engine)
    with migrated_sqlite_engine.begin() as connection:
        original = dict(connection.execute(sa.select(prospect_target)).mappings().one())
        rows = []
        for index in range(1, 25):
            row = dict(original)
            row.update(
                target_id=f"00000000-0000-0000-0000-{index:012d}",
                opportunity_key=f"opportunity-{index}",
                email_address=f"contact-{index}@example.fr",
                attribution_member_ref=f"{index:064x}",
            )
            rows.append(row)
        connection.execute(sa.insert(prospect_target), rows)

    with pytest.raises(FounderAcquisitionLaunchError) as caught:
        _launcher(
            migrated_sqlite_engine,
            tmp_path,
            popen=lambda *_args, **_options: pytest.fail("must not launch"),
        ).prepare()

    assert caught.value.status_code == 429
    assert caught.value.code == "DAILY_PENDING_CAP_REACHED"
    assert caught.value.message == "La file du jour a atteint son plafond de 25 cibles."


def test_prepare_refuses_the_acquisition_kill_switch(
    migrated_sqlite_engine,
    tmp_path,
) -> None:
    (tmp_path / "acquisition.disabled").touch()

    with pytest.raises(FounderAcquisitionLaunchError) as caught:
        _launcher(
            migrated_sqlite_engine,
            tmp_path,
            popen=lambda *_args, **_options: pytest.fail("must not launch"),
        ).prepare()

    assert caught.value.status_code == 423
    assert caught.value.code == "ACQUISITION_DISABLED"
    assert caught.value.message == "La préparation est suspendue par le coupe-circuit."


def test_founder_prepare_route_accepts_one_async_cycle(migrated_sqlite_engine) -> None:
    app = create_founder_app(
        FounderApiConfig(
            allowed_email="rodrigue.bruppacher@gmail.com",
            allowed_user="rodrigue",
            origin_secret=ORIGIN_SECRET,
        ),
        prospection_actions=_actions(migrated_sqlite_engine),
        acquisition_launcher=StubLauncher(
            result=FounderAcquisitionLaunch(
                accepted=True,
                prepared_today_count=3,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/founder/actions/prospection/prepare",
            headers=_headers(),
            json={},
        )

    assert response.status_code == 202
    assert response.json() == {
        "version": "founder-prospection-prepare-v1",
        "status": "accepted",
        "prepared_today_count": 3,
        "daily_pending_cap": 25,
    }


@pytest.mark.parametrize(
    ("status_code", "code", "message"),
    (
        (409, "ACQUISITION_ALREADY_RUNNING", "Une préparation est déjà en cours."),
        (
            423,
            "ACQUISITION_DISABLED",
            "La préparation est suspendue par le coupe-circuit.",
        ),
        (
            429,
            "DAILY_PENDING_CAP_REACHED",
            "La file du jour a atteint son plafond de 25 cibles.",
        ),
    ),
)
def test_founder_prepare_route_preserves_bounded_refusal_phrases(
    migrated_sqlite_engine,
    status_code: int,
    code: str,
    message: str,
) -> None:
    app = create_founder_app(
        FounderApiConfig(
            allowed_email="rodrigue.bruppacher@gmail.com",
            allowed_user="rodrigue",
            origin_secret=ORIGIN_SECRET,
        ),
        prospection_actions=_actions(migrated_sqlite_engine),
        acquisition_launcher=StubLauncher(
            error=FounderAcquisitionLaunchError(
                status_code=status_code,
                code=code,
                message=message,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/founder/actions/prospection/prepare",
            headers=_headers(),
            json={},
        )

    assert response.status_code == status_code
    assert response.json() == {
        "detail": {
            "code": code,
            "message": message,
            "target_ids": [],
        }
    }
