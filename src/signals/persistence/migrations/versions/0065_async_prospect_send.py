"""Add the durable Founder prospect-send queue and separate acceptance from delivery."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0065_async_prospect_send"
down_revision = "0064_company_mail_merge"
branch_labels = None
depends_on = None


_DELIVERY_TIMESTAMPS = (
    "sent_at",
    "opened_at",
    "clicked_at",
    "replied_at",
    "bounced_at",
    "unsubscribed_at",
)

_DELIVERY_PRECEDENCE = {
    "not_sent": 0,
    "delivered": 1,
    "opened": 2,
    "clicked": 3,
    "replied": 4,
    "bounced": 5,
    "unsubscribed": 6,
}

_EVENT_DELIVERY_PROJECTIONS = {
    "email_sent": ("delivered", "sent_at"),
    "email_opened": ("opened", "opened_at"),
    "email_link_clicked": ("clicked", "clicked_at"),
    "link_clicked": ("clicked", "clicked_at"),
    "reply_received": ("replied", "replied_at"),
    "auto_reply_received": ("replied", "replied_at"),
    "email_bounced": ("bounced", "bounced_at"),
    "lead_unsubscribed": ("unsubscribed", "unsubscribed_at"),
}


def _rebuild_delivery_state() -> None:
    """Replace legacy acceptance-as-delivery values with the webhook event projection."""
    bind = op.get_bind()
    target = sa.table(
        "prospect_target",
        sa.column("target_id", sa.String(36)),
        sa.column("status", sa.String(16)),
        sa.column("delivery_status", sa.String(16)),
        sa.column("instantly_accepted_at", sa.DateTime(timezone=True)),
        sa.column("sent_at", sa.DateTime(timezone=True)),
        sa.column("opened_at", sa.DateTime(timezone=True)),
        sa.column("clicked_at", sa.DateTime(timezone=True)),
        sa.column("replied_at", sa.DateTime(timezone=True)),
        sa.column("bounced_at", sa.DateTime(timezone=True)),
        sa.column("unsubscribed_at", sa.DateTime(timezone=True)),
        sa.column("reply_classification", sa.String(32)),
    )
    events = sa.table(
        "prospect_delivery_event",
        sa.column("event_fingerprint", sa.String(64)),
        sa.column("target_id", sa.String(36)),
        sa.column("provider_event_type", sa.String(64)),
        sa.column("occurred_at", sa.DateTime(timezone=True)),
    )

    bind.execute(
        sa.update(target).values(
            instantly_accepted_at=sa.case(
                (target.c.status == "sent", target.c.sent_at),
                else_=target.c.instantly_accepted_at,
            ),
            delivery_status=sa.case(
                (target.c.unsubscribed_at.is_not(None), "unsubscribed"),
                (target.c.clicked_at.is_not(None), "clicked"),
                else_="not_sent",
            ),
            sent_at=None,
            opened_at=None,
            replied_at=None,
            bounced_at=None,
            reply_classification=None,
        )
    )
    target_rows = {
        str(row["target_id"]): dict(row)
        for row in bind.execute(
            sa.select(
                target.c.target_id,
                target.c.delivery_status,
                target.c.clicked_at,
                target.c.unsubscribed_at,
            )
        ).mappings()
    }
    rows = bind.execute(
        sa.select(
            events.c.event_fingerprint,
            events.c.target_id,
            events.c.provider_event_type,
            events.c.occurred_at,
        )
        .where(events.c.target_id.is_not(None))
        .order_by(events.c.target_id, events.c.occurred_at, events.c.event_fingerprint)
    ).mappings()

    delivery_by_target: dict[str, dict[str, object]] = {}
    for row in rows:
        target_id = str(row["target_id"])
        event_type = str(row["provider_event_type"])
        occurred_at = row["occurred_at"]
        current = target_rows[target_id]
        values = delivery_by_target.setdefault(
            target_id,
            {
                "delivery_status": current["delivery_status"],
                **{column: None for column in _DELIVERY_TIMESTAMPS},
                "clicked_at": current["clicked_at"],
                "unsubscribed_at": current["unsubscribed_at"],
                "reply_classification": None,
            },
        )
        projection = _EVENT_DELIVERY_PROJECTIONS.get(event_type)
        if projection is None:
            continue
        status, timestamp_column = projection
        if values[timestamp_column] is None or occurred_at < values[timestamp_column]:
            values[timestamp_column] = occurred_at
        if event_type == "reply_received":
            values["reply_classification"] = "human_reply"
        elif event_type == "auto_reply_received":
            values["reply_classification"] = "auto_reply"
        if _DELIVERY_PRECEDENCE[status] > _DELIVERY_PRECEDENCE[values["delivery_status"]]:
            values["delivery_status"] = status

    for target_id, values in delivery_by_target.items():
        bind.execute(sa.update(target).where(target.c.target_id == target_id).values(**values))


def _drop_acceptance_timestamp() -> None:
    """Remove the target column without cascading SQLite's dependent audit rows."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("prospect_target") as batch:
            batch.drop_column("instantly_accepted_at")
        return

    context = op.get_context()
    with context.autocommit_block():
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("prospect_target") as batch:
            batch.drop_column("instantly_accepted_at")
    finally:
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")
    invalid_foreign_keys = bind.exec_driver_sql("PRAGMA foreign_key_check").all()
    if invalid_foreign_keys:
        raise RuntimeError(
            f"foreign key violations after prospect target rebuild: {invalid_foreign_keys}"
        )


def upgrade() -> None:
    with op.batch_alter_table("prospect_target") as batch:
        batch.add_column(sa.Column("instantly_accepted_at", sa.DateTime(timezone=True)))

    with op.batch_alter_table("prospect_send_request") as batch:
        batch.add_column(
            sa.Column("processed_count", sa.Integer, nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("provider_campaign_id", sa.String(128)))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("claimed_by", sa.String(320)))
        batch.add_column(sa.Column("lease_id", sa.String(36)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )

    op.execute(
        sa.text(
            "UPDATE prospect_send_request SET "
            "failed_count = CASE "
            "WHEN status IN ('completed', 'partial', 'failed') THEN reserved_count - sent_count "
            "ELSE 0 END, "
            "processed_count = CASE "
            "WHEN status IN ('completed', 'partial', 'failed') THEN reserved_count "
            "ELSE sent_count END, "
            "started_at = created_at, "
            "updated_at = COALESCE(completed_at, created_at)"
        )
    )
    with op.batch_alter_table("prospect_send_request") as batch:
        batch.drop_constraint("ck_prospect_send_request_status", type_="check")
        batch.create_check_constraint(
            "ck_prospect_send_request_status",
            "status IN ('started', 'queued', 'running', 'waiting', 'completed', 'partial', 'failed')",
        )
        batch.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        )

    op.create_index(
        "ix_prospect_send_request_next_attempt_at",
        "prospect_send_request",
        ["next_attempt_at"],
    )
    op.create_index(
        "ix_prospect_send_request_lease_expires_at",
        "prospect_send_request",
        ["lease_expires_at"],
    )
    op.create_table(
        "prospect_send_item",
        sa.Column(
            "request_id",
            sa.String(36),
            sa.ForeignKey("prospect_send_request.request_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_id",
            sa.String(36),
            sa.ForeignKey("prospect_target.target_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("expected_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("instantly_id", sa.String(128)),
        sa.Column("verification_status", sa.Integer),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.Text),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'verification_pending', 'sent', 'failed')",
            name="ck_prospect_send_item_status",
        ),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 24",
            name="ck_prospect_send_item_position",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_prospect_send_item_attempts"),
    )
    op.create_index(
        "ix_prospect_send_item_next_attempt_at",
        "prospect_send_item",
        ["next_attempt_at"],
    )
    op.create_index(
        "ix_prospect_send_item_request_position",
        "prospect_send_item",
        ["request_id", "position"],
    )

    target = sa.table(
        "prospect_target",
        sa.column("status", sa.String(16)),
        sa.column("sent_at", sa.DateTime(timezone=True)),
        sa.column("instantly_accepted_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        sa.update(target)
        .where(target.c.status == "sent")
        .values(instantly_accepted_at=target.c.sent_at)
    )
    _rebuild_delivery_state()

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            DO $grants$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kivou_founder_rw') THEN
                GRANT SELECT, INSERT, UPDATE ON prospect_send_item TO kivou_founder_rw;
                GRANT SELECT (instantly_accepted_at), INSERT (instantly_accepted_at),
                  UPDATE (instantly_accepted_at) ON prospect_target TO kivou_founder_rw;
                GRANT SELECT (
                  processed_count, failed_count, provider_campaign_id, next_attempt_at,
                  attempt_count, claimed_by, lease_id, lease_expires_at, started_at, updated_at
                ), INSERT (
                  processed_count, failed_count, provider_campaign_id, next_attempt_at,
                  attempt_count, claimed_by, lease_id, lease_expires_at, started_at, updated_at
                ), UPDATE (
                  processed_count, failed_count, provider_campaign_id, next_attempt_at,
                  attempt_count, claimed_by, lease_id, lease_expires_at, started_at, updated_at
                ) ON prospect_send_request TO kivou_founder_rw;
              END IF;
            END
            $grants$;
            """
        )


def downgrade() -> None:
    op.drop_index("ix_prospect_send_item_request_position", table_name="prospect_send_item")
    op.drop_index("ix_prospect_send_item_next_attempt_at", table_name="prospect_send_item")
    op.drop_table("prospect_send_item")
    op.drop_index("ix_prospect_send_request_lease_expires_at", table_name="prospect_send_request")
    op.drop_index("ix_prospect_send_request_next_attempt_at", table_name="prospect_send_request")
    op.execute(
        sa.text(
            "UPDATE prospect_send_request SET "
            "status = 'failed', "
            "completed_at = COALESCE(completed_at, updated_at, started_at, created_at), "
            "error = COALESCE(error || '; ', '') || 'unfinished async state: ' || status "
            "WHERE status IN ('queued', 'running', 'waiting')"
        )
    )
    with op.batch_alter_table("prospect_send_request") as batch:
        batch.drop_constraint("ck_prospect_send_request_status", type_="check")
        batch.create_check_constraint(
            "ck_prospect_send_request_status",
            "status IN ('started', 'completed', 'partial', 'failed')",
        )
        batch.drop_column("updated_at")
        batch.drop_column("started_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_id")
        batch.drop_column("claimed_by")
        batch.drop_column("attempt_count")
        batch.drop_column("next_attempt_at")
        batch.drop_column("provider_campaign_id")
        batch.drop_column("failed_count")
        batch.drop_column("processed_count")
    target = sa.table(
        "prospect_target",
        sa.column("instantly_accepted_at", sa.DateTime(timezone=True)),
        sa.column("sent_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        sa.update(target)
        .where(target.c.instantly_accepted_at.is_not(None))
        .values(sent_at=target.c.instantly_accepted_at)
    )
    _drop_acceptance_timestamp()
