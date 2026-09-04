from __future__ import annotations

import sqlalchemy as sa
from test_attribution_landing import CLICKED_AT, client_for, land, prepared

from signals.persistence.schema import acquisition_personalization_artifact, for_you_sentence
from signals.personalization.for_you import POLICY_VERSION
from signals.personalization.for_you_store import (
    enqueue_stored_for_you_sentence,
    sentence_for_opportunity,
)


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


def test_policy_v4_creates_a_new_cache_row_without_overwriting_v1(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    assert land(client_for(engine, attribution, now=CLICKED_AT), token.raw_token).status_code == 303
    with engine.begin() as connection:
        current = connection.execute(sa.select(for_you_sentence)).mappings().one()
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.for_you_id == current["for_you_id"])
            .values(for_you_id="f" * 64, policy_version="for-you-v1")
        )
        created = enqueue_stored_for_you_sentence(
            connection,
            signal_key=current["signal_key"],
            now=CLICKED_AT,
        )
        versions = connection.scalars(
            sa.select(for_you_sentence.c.policy_version).order_by(for_you_sentence.c.policy_version)
        ).all()
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.policy_version == "for-you-v1")
            .values(sentence="ancienne phrase", created_at=CLICKED_AT + __import__("datetime").timedelta(days=1))
        )
        served = sentence_for_opportunity(
            connection,
            opportunity_key=token.payload.opportunity_key,
        )

    assert POLICY_VERSION == "for-you-v4"
    assert created is not None and created != "f" * 64
    assert versions == ["for-you-v1", "for-you-v4"]
    assert served != "ancienne phrase"
