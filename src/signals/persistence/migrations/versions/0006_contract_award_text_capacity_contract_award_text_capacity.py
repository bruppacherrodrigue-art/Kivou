"""Widen the demonstrated free-form BOAMP contract reference without truncation."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_contract_award_text_capacity"
down_revision = "0005_ingestion_runtime"
branch_labels = None
depends_on = None


def _alter_contract_reference(*, current: sa.TypeEngine, target: sa.TypeEngine) -> None:
    with op.batch_alter_table("contract_award") as batch_op:
        batch_op.alter_column(
            "contract_reference",
            existing_type=current,
            type_=target,
            existing_nullable=True,
        )


def _alter_with_sqlite_foreign_keys_suspended(
    *, current: sa.TypeEngine, target: sa.TypeEngine
) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        _alter_contract_reference(current=current, target=target)
        return

    context = op.get_context()
    with context.autocommit_block():
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        _alter_contract_reference(current=current, target=target)
    finally:
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    _alter_with_sqlite_foreign_keys_suspended(
        current=sa.String(length=256),
        target=sa.Text(),
    )


def downgrade() -> None:
    _alter_with_sqlite_foreign_keys_suspended(
        current=sa.Text(),
        target=sa.String(length=256),
    )
