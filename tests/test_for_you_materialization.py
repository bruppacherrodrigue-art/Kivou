from __future__ import annotations

import sqlalchemy as sa
from test_attribution_landing import CLICKED_AT, client_for, land, prepared

from signals.persistence.schema import acquisition_personalization_artifact, for_you_sentence


def test_landing_materialization_commits_visible_copy_without_provider(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    client = client_for(engine, attribution, now=CLICKED_AT)

    response = land(client, token.raw_token)

    assert response.status_code == 303
    with engine.connect() as connection:
        row = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert row["state"] == "completed"
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


def test_cold_mail_and_landing_pair_share_the_exact_sentence(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    with engine.connect() as connection:
        artifact = (
            connection.execute(sa.select(acquisition_personalization_artifact)).mappings().one()
        )
    sentence = artifact["input_snapshot"]["for_you_sentence"]
    assert sentence in artifact["body"]

    assert land(client_for(engine, attribution, now=CLICKED_AT), token.raw_token).status_code == 303

    with engine.connect() as connection:
        cached = connection.execute(sa.select(for_you_sentence)).mappings().one()
    assert cached["sentence"] == sentence
