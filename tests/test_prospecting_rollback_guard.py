"""Rollback keeps legacy writers away from revisioned private state."""

import re
from pathlib import Path

import pytest

NGINX = Path(__file__).resolve().parents[1] / "ops" / "nginx"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_environment_installs_the_write_guard_in_the_tls_server_only(environment):
    config = (NGINX / f"kivou-{environment}.conf").read_text()
    directive = "include /etc/nginx/kivou-prospecting-writes.conf;"
    assert config.count(directive) == 1
    assert config.index(directive) > config.index("listen 443")


@pytest.mark.parametrize(
    "method,path,blocked",
    [
        ("PUT", "/signals/sig/note", True),
        ("POST", "/signals/sig/contacted", True),
        ("PUT", "/signals/sig/status", True),
        ("DELETE", "/companies/cmp/manual-contact", True),
        ("POST", "/companies/cmp/contact-lookup", True),
        ("PUT", "/companies/cmp/prospection", True),
        ("PATCH", "/target-icps/icp", True),
        ("POST", "/target-icps", True),
        ("POST", "/target-icps/", True),
        ("PUT", "/target-icps/icp", True),
        ("DELETE", "/target-icps/icp", True),
        ("GET", "/target-icps", False),
        ("GET", "/target-icps/icp", False),
        ("OPTIONS", "/target-icps", False),
        ("POST", "/target-icps-other", False),
        ("GET", "/signals/sig/note", False),
        ("GET", "/companies/cmp", False),
        ("GET", "/me", False),
        ("POST", "/auth/login", False),
        ("POST", "/webhooks/stripe", False),
        ("GET", "/app/signals", False),
    ],
)
def test_guard_matches_writes_only(method, path, blocked):
    closed = (NGINX / "kivou-prospecting-maintenance.conf").read_text()
    patterns = re.findall(r'if \(\$kivou_prospecting_request ~ "([^"]+)"\)', closed)
    assert len(patterns) == 2
    assert any(re.search(pattern, f"{method}:{path}") for pattern in patterns) is blocked
    assert "return 503;" in closed


def test_open_guard_contains_no_active_directive():
    assert not any(
        line.strip() and not line.lstrip().startswith("#")
        for line in (NGINX / "kivou-prospecting-open.conf").read_text().splitlines()
    )
