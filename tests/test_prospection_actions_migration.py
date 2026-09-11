from __future__ import annotations

import sqlalchemy as sa


def test_prospection_actions_schema_is_at_head(migrated_sqlite_engine) -> None:
    inspector = sa.inspect(migrated_sqlite_engine)

    assert {
        "prospect_target",
        "prospect_target_history",
        "prospect_send_request",
    } <= set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("prospect_target")}
    assert {
        "target_id",
        "version",
        "status",
        "email_verification_status",
        "mail_text",
        "mail_html",
        "instantly_credit_units",
        "instantly_request_count",
    } <= columns
