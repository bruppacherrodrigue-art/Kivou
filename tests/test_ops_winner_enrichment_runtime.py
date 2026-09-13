from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("directory", "environment"),
    [
        (ROOT / "ops/systemd", "/etc/kivou/staging.env"),
        (ROOT / "ops/systemd/production", "/etc/kivou/production.env"),
    ],
)
def test_winner_enrichment_service_is_budgeted_serialized_and_hardened(
    directory: pathlib.Path, environment: str
) -> None:
    body = (directory / "kivou-winner-enrichment.service").read_text(encoding="utf-8")

    assert f"EnvironmentFile={environment}" in body
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 75 "
        "/srv/kivou/run/winner-enrichment-systemd.lock "
        "/srv/kivou/app/.venv/bin/python -m signals.company_research.winner_worker"
    ) in body
    assert "TimeoutStartSec=55min" in body
    assert "ReadWritePaths=/srv/kivou/run" in body
    assert "ProtectSystem=strict" in body
    assert "NoNewPrivileges=true" in body


@pytest.mark.parametrize(
    "directory", [ROOT / "ops/systemd", ROOT / "ops/systemd/production"]
)
def test_winner_enrichment_timer_runs_within_an_hour(directory: pathlib.Path) -> None:
    body = (directory / "kivou-winner-enrichment.timer").read_text(encoding="utf-8")

    assert "OnCalendar=*:0/30" in body
    assert "Persistent=true" in body
    assert "RandomizedDelaySec=300" in body
    assert "AccuracySec=60" in body
    assert "Unit=kivou-winner-enrichment.service" in body
    assert "WantedBy=timers.target" in body
