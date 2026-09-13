"""Copy synthetic fixture rows into a real historical schema, with foreign keys on.

Current materializers write columns introduced after the revision under test.
Preparing fixtures in a separate current-compatible database avoids requiring
unrelated later downgrades (including deliberately irreversible migrations).
"""

import sqlalchemy as sa


def copy_synthetic_rows_to_historical_schema(source_engine, historical_engine):
    source_metadata = sa.MetaData()
    source_metadata.reflect(bind=source_engine)
    historical_metadata = sa.MetaData()
    historical_metadata.reflect(bind=historical_engine)
    with source_engine.connect() as source, historical_engine.begin() as historical:
        for table in historical_metadata.sorted_tables:
            if table.name == "alembic_version":
                continue
            source_table = source_metadata.tables[table.name]
            names = [column.name for column in table.columns if column.name in source_table.c]
            rows = (
                source.execute(sa.select(*(source_table.c[name] for name in names)))
                .mappings()
                .all()
            )
            if rows:
                historical.execute(table.insert(), [dict(row) for row in rows])
            assert historical.scalar(sa.select(sa.func.count()).select_from(table)) == len(rows)
