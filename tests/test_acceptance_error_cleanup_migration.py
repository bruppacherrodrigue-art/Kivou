from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from test_prospection_actions_send import _seed_second_target
from test_prospection_actions_service import NOW, TARGET_ID, seed

from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import prospect_target


def test_cleanup_clears_only_stale_errors_on_accepted_targets(tmp_path) -> None:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'acceptance-error-cleanup.sqlite'}"
    )
    config = alembic_config(engine)
    command.upgrade(config, "0066_async_chief_merge")
    seed(engine)
    invalid_target_id = _seed_second_target(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == TARGET_ID)
            .values(
                status="sent",
                instantly_accepted_at=NOW,
                delivery_error="instantly_email_verification_pending",
            )
        )
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == invalid_target_id)
            .values(status="approved", delivery_error="instantly email invalid")
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        errors = dict(
            connection.execute(
                sa.select(prospect_target.c.target_id, prospect_target.c.delivery_error)
            ).all()
        )
        revision = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    assert errors[TARGET_ID] is None
    assert errors[invalid_target_id] == "instantly email invalid"
    assert revision == "0067_acceptance_error_cleanup"
    engine.dispose()
