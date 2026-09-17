from __future__ import annotations

import sqlalchemy as sa


def test_prospection_actions_schema_is_at_head(migrated_sqlite_engine) -> None:
    inspector = sa.inspect(migrated_sqlite_engine)

    assert {
        "prospect_target",
        "prospect_target_history",
        "prospect_send_request",
        "prospect_delivery_event",
        "prospect_send_item",
    } <= set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("prospect_target")}
    assert {
        "target_id",
        "version",
        "status",
        "email_verification_status",
        "mail_text",
        "mail_html",
        "signal_department",
        "mail_contract_status",
        "mail_contract_failure",
        "instantly_credit_units",
        "instantly_request_count",
        "reply_classification",
        "instantly_accepted_at",
    } <= columns
    request_columns = {column["name"] for column in inspector.get_columns("prospect_send_request")}
    assert {
        "processed_count",
        "failed_count",
        "provider_campaign_id",
        "next_attempt_at",
        "attempt_count",
        "claimed_by",
        "lease_id",
        "lease_expires_at",
        "started_at",
        "updated_at",
    } <= request_columns
    item_columns = {column["name"] for column in inspector.get_columns("prospect_send_item")}
    assert {
        "request_id",
        "target_id",
        "position",
        "expected_version",
        "status",
        "instantly_id",
        "verification_status",
        "error_code",
        "error_message",
        "next_attempt_at",
        "attempt_count",
        "created_at",
        "updated_at",
        "completed_at",
    } <= item_columns
    checks = {
        check["name"]: check["sqltext"]
        for check in inspector.get_check_constraints("prospect_target")
    }
    assert checks["ck_prospect_target_words"] == "mail_word_count BETWEEN 1 AND 110"
    assert "mail_contract_status" in checks["ck_prospect_target_mail_contract"]
    assert "prospect_target_id" in {
        column["name"] for column in inspector.get_columns("acquisition_conversion_event")
    }
