import runpy
from pathlib import Path

import sqlalchemy as sa
from feed_helpers import SIMAP_RICH, make_icp, materialize_simap
from test_prospecting_migration import NOW, populated_0058
from test_prospecting_migration import engine as engine  # noqa: PLC0414 — pytest fixture re-export

from signals.companies.service import ensure_companies_for_signal_keys
from signals.persistence.database import current_revision


def test_live_legacy_preflight_writes_only_to_memory_and_keeps_input_private(engine):
    populated_0058(engine)
    script = (
        Path(__file__).resolve().parents[1] / "docs/reports/prospecting-v11/legacy-preflight.py"
    )
    inspect_legacy = runpy.run_path(str(script))["inspect_legacy"]
    before_tables = sa.inspect(engine).get_table_names()
    with engine.begin() as connection:
        signal = materialize_simap(
            connection, SIMAP_RICH, target_icp_id=make_icp(connection, "account_a")
        )
        ensure_companies_for_signal_keys(connection, signal_keys=(signal.signal_key,), now=NOW)
        company = sa.Table("saas_company", sa.MetaData(), autoload_with=connection)
        connection.execute(
            sa.update(company).values(
                company_key="cmp_legacy",
                official_country="FR",
                official_identifiers=[{"scheme": "SIREN", "value": "331364729"}],
            )
        )
        before_note = connection.execute(
            sa.text("select body from company_note where company_key='cmp_legacy'")
        ).scalar_one()
    result = inspect_legacy(engine)
    assert result["live_read_only"] and result["legacy_values_preserved"]
    assert result["reconciliation_target"] == "sqlite_memory"
    assert result["phases"]["registry"]["counts"] == {"registered": 1}
    assert result["phases"]["accounts"]["counts"] == {"resolved": 1}
    assert "Company" not in str(result) and "cmp_legacy" not in str(result)
    assert current_revision(engine) == "0058_client_location"
    assert sa.inspect(engine).get_table_names() == before_tables
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("select body from company_note where company_key='cmp_legacy'")
            ).scalar_one()
            == before_note
        )
