"""Allow ASSISTED runtime observations without permitting LIVE transport.

Revision ID: 0052_assisted_runtime_observation
Revises: 0051_assisted_prospection
"""

from __future__ import annotations

from alembic import op

revision = "0052_assisted_runtime_observation"
down_revision = "0051_assisted_prospection"
branch_labels = None
depends_on = None

TABLE_NAME = "acquisition_runtime_observation"
CONSTRAINT_NAME = "ck_acquisition_runtime_observation_boundary"

SHADOW_ONLY_EXPRESSION = (
    "mode = 'SHADOW' AND native_tools = 0 AND ("
    "(environment = 'STAGING' AND qa_only IS TRUE) OR "
    "(environment = 'PRODUCTION' AND qa_only IS FALSE))"
)
ASSISTED_EXPRESSION = (
    "mode IN ('SHADOW', 'ASSISTED') AND native_tools = 0 AND ("
    "(environment = 'STAGING' AND qa_only IS TRUE) OR "
    "(environment = 'PRODUCTION' AND qa_only IS FALSE))"
)


def upgrade() -> None:
    with op.batch_alter_table(TABLE_NAME) as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch.create_check_constraint(CONSTRAINT_NAME, ASSISTED_EXPRESSION)


def downgrade() -> None:
    # This intentionally fails if ASSISTED observations still exist; operators
    # must decide whether those audit rows may be rewritten before downgrading.
    with op.batch_alter_table(TABLE_NAME) as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch.create_check_constraint(CONSTRAINT_NAME, SHADOW_ONLY_EXPRESSION)
