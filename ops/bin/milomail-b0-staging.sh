#!/usr/bin/env bash
# Operator-only wrapper. All secrets stay in the staging secret mechanism.
set -euo pipefail
set +x

[[ "$(hostname)" == "kivou-staging-01" ]] || { echo 'status=WRONG_HOST'; exit 2; }
[[ "$(id -u)" == 0 ]] || { echo 'status=ROOT_REQUIRED_FOR_EXISTING_SECRETS'; exit 2; }
# No URL or key is printed or passed as a process argument. The existing
# staging URL is redirected only within this process to the isolated database.
exec uv run python - "$@" <<'PY'
import os
import sys
from pathlib import Path
from sqlalchemy.engine import make_url

from signals.acquisition_programs.census_b0_cli import main

for path in ("/etc/kivou/staging.env", "/etc/kivou/acquisition-shadow.env"):
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key.isidentifier():
            raise SystemExit("status=INVALID_SECRET_CONFIGURATION")
        os.environ[key] = value.strip().strip('"').strip("'")

os.environ.update({
    "KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
    "MILOMAIL_CENSUS_APOLLO_SECRET_REF": "KIVOU_APOLLO_API_KEY",
    "MILOMAIL_CENSUS_ENABLED": "true",
    "MILOMAIL_CENSUS_AUTHORIZATION_REF": "user-prompt-2026-09-22-b0",
    "MILOMAIL_CENSUS_MAX_PARTITIONS": "9",
    "MILOMAIL_CENSUS_MAX_PAGES": "90",
    # A revoked, fully charged People Search without a company checkpoint
    # occupies a slot. Two reviewed orphan calls still permit at most 200
    # completed companies across all B0 permits.
    "MILOMAIL_CENSUS_MAX_CANDIDATES": "2452",
    "MILOMAIL_CENSUS_MAX_ENRICHMENTS": "400",
    "MILOMAIL_CENSUS_MAX_APOLLO_CREDITS": "1590",
    "MILOMAIL_CENSUS_MAX_COST_CHF": "0",
    "MILOMAIL_CENSUS_CHF_PER_CREDIT_CEILING": "0",
    "MILOMAIL_CENSUS_CREDITS_PEOPLE_SEARCH": "0",
    "MILOMAIL_CENSUS_CREDITS_PERSON_ENRICH_MAX": "9",
    "MILOMAIL_COMPANY_STATUS_ENABLED": "true",
    "MILOMAIL_COMPANY_STATUS_SOURCE": "ANNUAIRE_ENTREPRISES",
    "MILOMAIL_COMPANY_STATUS_MAX_REQUESTS": "600",
    "MILOMAIL_COMPANY_STATUS_RATE_LIMIT": "60",
    "MILOMAIL_COMPANY_STATUS_REQUEST_TIMEOUT_SECONDS": "5",
    "MILOMAIL_COMPANY_STATUS_CACHE_TTL_DAYS": "7",
})
old = make_url(os.environ["KIVOU_DATABASE_URL"])
if old.get_backend_name() != "postgresql":
    raise SystemExit("status=NOT_POSTGRESQL")
os.environ["KIVOU_DATABASE_URL"] = old.set(database="kivou_milomail_census_a0").render_as_string(
    hide_password=False
)
raise SystemExit(main(sys.argv[1:]))
PY
