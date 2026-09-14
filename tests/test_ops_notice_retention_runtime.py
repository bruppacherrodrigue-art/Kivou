"""Both releases expire only bounded public source bytes, not commercial facts."""

from pathlib import Path

import pytest

SYSTEMD = Path(__file__).resolve().parents[1] / "ops" / "systemd"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_notice_retention_uses_the_explicit_environment_and_bounded_existing_worker(environment):
    root = SYSTEMD / "production" if environment == "production" else SYSTEMD
    service = (root / "kivou-notice-retention.service").read_text()
    timer = (root / "kivou-notice-retention.timer").read_text()
    assert f"EnvironmentFile=/etc/kivou/{environment}.env" in service
    assert "-m signals.client_value.notice_retention --execute --limit 1000" in service
    assert "ProtectSystem=strict" in service
    assert "TimeoutStartSec=5min" in service
    assert "OnCalendar=*-*-* 03:40:00 UTC" in timer
    assert "Persistent=true" in timer
