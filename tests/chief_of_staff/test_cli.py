from __future__ import annotations

import datetime as dt

from signals.chief_of_staff import cli
from signals.company_research.instance_lock import exclusive_instance_lock

from .test_service import Generator, OverviewReader


def test_cli_is_dry_run_by_default_and_outputs_no_context(
    migrated_sqlite_engine, monkeypatch, tmp_path, capsys
) -> None:
    service = cli.build_service_for_tests(
        engine=migrated_sqlite_engine,
        overview_reader=OverviewReader(),
        generator=Generator(),
        clock=lambda: dt.datetime(2026, 9, 15, 5, 30, tzinfo=dt.UTC),
    )
    monkeypatch.setattr(cli, "_runtime_service", lambda **_: service)
    code = cli.main(
        [
            "generate",
            "--cadence",
            "daily",
            "--at",
            "2026-09-15T05:30:00Z",
            "--lock-file",
            str(tmp_path / "chief.lock"),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert '"persisted": false' in output
    assert "business_memory" not in output


def test_cli_requires_explicit_persist_flag(
    migrated_sqlite_engine, monkeypatch, tmp_path
) -> None:
    service = cli.build_service_for_tests(
        engine=migrated_sqlite_engine,
        overview_reader=OverviewReader(),
        generator=Generator(),
        clock=lambda: dt.datetime(2026, 9, 15, 5, 30, tzinfo=dt.UTC),
    )
    monkeypatch.setattr(cli, "_runtime_service", lambda **_: service)
    assert (
        cli.main(
            [
                "generate",
                "--cadence",
                "daily",
                "--at",
                "2026-09-15T05:30:00Z",
                "--persist",
                "--lock-file",
                str(tmp_path / "chief.lock"),
            ]
        )
        == 0
    )
    assert service.store.latest() is not None


def test_cli_refuses_two_generations_with_same_host_lock(
    migrated_sqlite_engine, monkeypatch, tmp_path
) -> None:
    lock = tmp_path / "chief.lock"
    service = cli.build_service_for_tests(
        engine=migrated_sqlite_engine,
        overview_reader=OverviewReader(),
        generator=Generator(),
        clock=lambda: dt.datetime(2026, 9, 15, 5, 30, tzinfo=dt.UTC),
    )
    monkeypatch.setattr(cli, "_runtime_service", lambda **_: service)
    with exclusive_instance_lock(lock):
        assert (
            cli.main(
                [
                    "generate",
                    "--cadence",
                    "daily",
                    "--at",
                    "2026-09-15T05:30:00Z",
                    "--lock-file",
                    str(lock),
                ]
            )
            == 3
        )
