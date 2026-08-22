"""target ICP matching revisions and traceable signal invalidation

Revision ID: 0017_target_icp_revision
Revises: 0016_campaign_factory
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_target_icp_revision"
down_revision = "0016_campaign_factory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("target_icp") as batch:
        batch.add_column(
            sa.Column(
                "matching_revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(sa.Column("plan_limit_code", sa.String(length=64)))
        batch.add_column(sa.Column("plan_limited_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_target_icp_plan_limit_code", ["plan_limit_code"])
        batch.create_check_constraint(
            "ck_target_icp_matching_revision", "matching_revision >= 1"
        )

    with op.batch_alter_table("materialized_signal") as batch:
        batch.add_column(
            sa.Column(
                "target_icp_revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(sa.Column("invalidated_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("invalidation_reason", sa.String(length=64)))
        batch.create_index("ix_materialized_signal_invalidated_at", ["invalidated_at"])
        batch.create_check_constraint(
            "ck_signal_target_icp_revision", "target_icp_revision >= 1"
        )


def downgrade() -> None:
    with op.batch_alter_table("materialized_signal") as batch:
        batch.drop_constraint("ck_signal_target_icp_revision", type_="check")
        batch.drop_index("ix_materialized_signal_invalidated_at")
        batch.drop_column("invalidation_reason")
        batch.drop_column("invalidated_at")
        batch.drop_column("target_icp_revision")

    with op.batch_alter_table("target_icp") as batch:
        batch.drop_constraint("ck_target_icp_matching_revision", type_="check")
        batch.drop_index("ix_target_icp_plan_limit_code")
        batch.drop_column("plan_limited_at")
        batch.drop_column("plan_limit_code")
        batch.drop_column("matching_revision")
