"""One current-head authority; explicit historical revisions stay in each test."""

from alembic.config import Config
from alembic.script import ScriptDirectory

from signals.persistence.database import MIGRATIONS_PATH


def current_migration_head() -> str:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None, "the application must have a migration head"
    return head


CURRENT_HEAD = current_migration_head()
