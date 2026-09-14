import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_ops_nginx_routes import _directives_starting_with, _location_blocks

ROOT = Path(__file__).resolve().parents[1]


def test_publication_has_only_an_exact_production_alias_and_get_only_proxy():
    production = (ROOT / "ops/nginx/kivou-production.conf").read_text()
    locations = {block.selector: block.body for block in _location_blocks(production)}
    body = locations.get("= /api/internal/company-catalogue", "")
    assert body, "the catalogue worker URL must reach the production API"
    assert "proxy_pass http://127.0.0.1:KIVOU_API_PORT/internal/company-catalogue;" in body
    assert "if ($request_method != GET) { return 405; }" in body
    proxy_include = "include /etc/nginx/kivou-proxy-params.conf;"
    assert proxy_include in body
    shared = (ROOT / "ops/nginx/kivou-proxy-params.conf").read_text()
    composed = body.replace(proxy_include, shared)
    assert _directives_starting_with(composed, "proxy_buffering ") == ("proxy_buffering off;",)
    staging = (ROOT / "ops/nginx/kivou-staging.conf").read_text()
    assert "location = /api/internal/company-catalogue" not in staging


def test_catalogue_proxy_loads_with_the_real_shared_nginx_include(tmp_path):
    nginx = os.environ.get("KIVOU_TEST_NGINX") or shutil.which("nginx")
    if not nginx:
        pytest.skip("set KIVOU_TEST_NGINX or install nginx to validate its configuration")
    production = (ROOT / "ops/nginx/kivou-production.conf").read_text()
    locations = {block.selector: block.body for block in _location_blocks(production)}
    body = locations["= /api/internal/company-catalogue"].replace("KIVOU_API_PORT", "8000")
    body = body.replace(
        "include /etc/nginx/kivou-proxy-params.conf;",
        f'include "{ROOT / "ops/nginx/kivou-proxy-params.conf"}";',
    )
    temp_paths = "\n".join(
        f'{module}_temp_path "{tmp_path / module}";'
        for module in ("client_body", "proxy", "fastcgi", "scgi", "uwsgi")
    )
    config = tmp_path / "nginx.conf"
    config.write_text(
        f'pid "{tmp_path / "nginx.pid"}";\n'
        "error_log stderr;\nevents {}\nhttp {\naccess_log off;\n"
        f"{temp_paths}\n"
        "limit_req_zone $binary_remote_addr zone=kivou_api:1m rate=120r/m;\n"
        "server {\nlisten 127.0.0.1:18089;\n"
        f"location = /api/internal/company-catalogue {{\n{body}\n}}\n}}\n}}\n"
    )
    result = subprocess.run(
        [nginx, "-t", "-e", "stderr", "-p", str(tmp_path), "-c", str(config)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
