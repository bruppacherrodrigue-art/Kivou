from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision


def test_session_template_is_a_database_at_head(
    migrated_sqlite_template: pathlib.Path,
) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{migrated_sqlite_template}")
    try:
        expected = ScriptDirectory.from_config(alembic_config(engine)).get_current_head()
        assert current_revision(engine) == expected
    finally:
        engine.dispose()


def test_isolated_copies_do_not_mutate_each_other_or_the_template(
    migrated_sqlite_template: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    from conftest import copy_migrated_sqlite_template

    first = copy_migrated_sqlite_template(migrated_sqlite_template, tmp_path / "first.db")
    second = copy_migrated_sqlite_template(migrated_sqlite_template, tmp_path / "second.db")
    first_engine = create_database_engine(f"sqlite+pysqlite:///{first}")
    second_engine = create_database_engine(f"sqlite+pysqlite:///{second}")
    template_engine = create_database_engine(f"sqlite+pysqlite:///{migrated_sqlite_template}")
    try:
        with first_engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE isolation_probe (id INTEGER PRIMARY KEY)"))

        assert sa.inspect(first_engine).has_table("isolation_probe")
        assert not sa.inspect(second_engine).has_table("isolation_probe")
        assert not sa.inspect(template_engine).has_table("isolation_probe")
    finally:
        first_engine.dispose()
        second_engine.dispose()
        template_engine.dispose()


def test_template_fixture_is_session_scoped_and_cached_once_per_run(
    migrated_sqlite_template: pathlib.Path,
    request,
) -> None:
    from conftest import migrated_sqlite_template as fixture_function

    assert fixture_function._fixture_function_marker.scope == "session"
    assert request.getfixturevalue("migrated_sqlite_template") is migrated_sqlite_template


def test_xdist_workers_resolve_the_same_session_template_path(tmp_path: pathlib.Path) -> None:
    from conftest import shared_migrated_sqlite_template_path

    session_root = tmp_path / "pytest-42"

    assert shared_migrated_sqlite_template_path(session_root / "popen-gw0") == (
        session_root / "kivou-migrated-head.db"
    )
    assert shared_migrated_sqlite_template_path(session_root / "popen-gw11") == (
        session_root / "kivou-migrated-head.db"
    )
