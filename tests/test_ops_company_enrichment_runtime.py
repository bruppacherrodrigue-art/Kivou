from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("directory", ["ops/systemd", "ops/systemd/production"])
def test_manual_enrichment_timer_only_consumes_explicit_requests(directory):
    service = (ROOT / directory / "kivou-company-enrichment.service").read_text()
    timer = (ROOT / directory / "kivou-company-enrichment.timer").read_text()
    assert "signals.company_research.winner_worker --requests-only --limit 5" in service
    assert "winner-enrichment-systemd.lock" in service
    assert "PLAYWRIGHT_BROWSERS_PATH=/srv/kivou/playwright" in service
    assert "ProtectSystem=strict" in service
    assert "OnUnitInactiveSec=60s" in timer
    assert "Unit=kivou-company-enrichment.service" in timer
