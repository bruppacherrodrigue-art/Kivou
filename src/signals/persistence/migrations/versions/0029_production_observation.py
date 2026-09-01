"""Allow a production observation while keeping staging QA-only.

Revision ID: 0029_production_observation
Revises: 0028_card_presentation

`ck_acquisition_runtime_observation_boundary` pinned `environment = 'STAGING'
AND qa_only IS TRUE` at the database level. Phase 1 of the acquisition
production rollout gives the runtime a real `PRODUCTION` environment with
`qa_only=False` (task 6). Under the old constraint, PostgreSQL rejected every
production observation at its very first write, before any stage ran.

The replacement expression is stricter, not looser, in both environments:
`mode = 'SHADOW'` and `native_tools = 0` stay required unconditionally;
staging still requires `qa_only IS TRUE`; production now requires
`qa_only IS FALSE`. No row the old constraint accepted becomes rejected, and
the only newly accepted shape is a production observation with `qa_only`
false — the database itself now refuses a production observation that
claims to be QA-only.

`downgrade()` restores the original STAGING-only expression exactly. It will
FAIL — with an integrity/check-constraint error — if a production
observation row already exists, because the restored constraint rejects
that row. This migration does not delete that row to make the downgrade
succeed: a migration that destroys data without announcing it is a trap for
whoever runs it. The rollback procedure must decide — delete the production
observation row first, or abandon the downgrade — before calling this.
"""

from __future__ import annotations

from alembic import op

revision = "0029_production_observation"
down_revision = "0028_card_presentation"
branch_labels = None
depends_on = None

TABLE_NAME = "acquisition_runtime_observation"
CONSTRAINT_NAME = "ck_acquisition_runtime_observation_boundary"

ORIGINAL_EXPRESSION = (
    "environment = 'STAGING' AND mode = 'SHADOW' "
    "AND qa_only IS TRUE AND native_tools = 0"
)
NEW_EXPRESSION = (
    "mode = 'SHADOW' AND native_tools = 0 AND ("
    "(environment = 'STAGING' AND qa_only IS TRUE) OR "
    "(environment = 'PRODUCTION' AND qa_only IS FALSE))"
)


def upgrade() -> None:
    with op.batch_alter_table(TABLE_NAME) as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch.create_check_constraint(CONSTRAINT_NAME, NEW_EXPRESSION)


def downgrade() -> None:
    with op.batch_alter_table(TABLE_NAME) as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch.create_check_constraint(CONSTRAINT_NAME, ORIGINAL_EXPRESSION)
