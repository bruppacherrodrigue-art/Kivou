from pathlib import Path

from test_ops_nginx_routes import _location_blocks

ROOT = Path(__file__).resolve().parents[1]


def test_publication_has_only_an_exact_production_alias_and_get_only_proxy():
    production = (ROOT / "ops/nginx/kivou-production.conf").read_text()
    locations = {block.selector: block.body for block in _location_blocks(production)}
    body = locations.get("= /api/internal/company-catalogue", "")
    assert body, "the catalogue worker URL must reach the production API"
    assert "proxy_pass http://127.0.0.1:KIVOU_API_PORT/internal/company-catalogue;" in body
    assert "if ($request_method != GET) { return 405; }" in body
    assert "proxy_buffering off;" in body
    assert "kivou-proxy-params.conf" in body
    staging = (ROOT / "ops/nginx/kivou-staging.conf").read_text()
    assert "location = /api/internal/company-catalogue" not in staging


def test_mirror_unit_is_staging_only_and_cannot_run_without_credential_file():
    directory = ROOT / "ops/systemd"
    service = (directory / "kivou-catalogue-mirror.service").read_text()
    timer = (directory / "kivou-catalogue-mirror.timer").read_text()
    assert "ConditionPathExists=/etc/kivou/catalogue-mirror.env" in service
    assert "EnvironmentFile=/etc/kivou/staging.env" in service
    assert "EnvironmentFile=/etc/kivou/production.env" not in service
    assert "--apply" in service
    assert "OnUnitInactiveSec=15min" in timer
    assert not (directory / "production/kivou-catalogue-mirror.service").exists()
