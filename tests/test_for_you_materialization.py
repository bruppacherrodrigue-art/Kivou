from __future__ import annotations

import sqlalchemy as sa
from test_attribution_landing import CLICKED_AT, client_for, land, prepared

from signals.persistence.schema import for_you_sentence


def test_landing_materialization_commits_fallback_without_provider(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    client = client_for(engine, attribution, now=CLICKED_AT)

    response = land(client, token.raw_token)

    assert response.status_code == 303
    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert row["state"] == "pending"
    assert row["provenance"] == "fallback"
    assert row["sentence"] == row["fallback_sentence"]
    assert row["sentence"]


def test_same_pair_and_fingerprints_enqueue_only_once(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    first = client_for(engine, attribution, now=CLICKED_AT)
    second = client_for(engine, attribution, now=CLICKED_AT)
    assert land(first, token.raw_token).status_code == 303
    assert land(second, token.raw_token).status_code == 303
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(for_you_sentence)) == 1
