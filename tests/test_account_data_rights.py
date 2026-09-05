from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from engagement_helpers import Clock, make_app, make_engine, signed_up
from feed_helpers import COMPLETE_ICP_INPUT

from signals.accounts.data_rights import purge_due_deletions
from signals.accounts.schema import account, account_deletion_request


def test_account_export_contains_owned_identity_and_profiles(tmp_path) -> None:
    engine = make_engine(tmp_path)
    client = signed_up(make_app(engine, Clock()))
    profile = client.post(
        "/target-icps",
        json={
            "label": "CVC Isère",
            "customer_input": COMPLETE_ICP_INPUT,
        },
    ).json()

    response = client.get("/account/export")

    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('"kivou-account-export.json"')
    payload = response.json()
    assert payload["account"]["display_name"] == "Negoce Romand SA"
    assert payload["profiles"][0]["target_icp_id"] == profile["target_icp_id"]
    assert "password_hash" not in response.text
    assert "token_hash" not in response.text


def test_confirmed_deletion_is_audited_and_purged_within_24_hours(tmp_path) -> None:
    engine = make_engine(tmp_path)
    clock = Clock()
    client = signed_up(make_app(engine, clock))
    account_id = client.get("/me").json()["account_id"]

    rejected = client.post("/account/deletion", json={"confirmation": "non"})
    assert rejected.status_code == 422

    accepted = client.post("/account/deletion", json={"confirmation": "SUPPRIMER"})
    assert accepted.status_code == 202
    assert accepted.json()["scheduled_for"] == (clock.now + dt.timedelta(hours=24)).isoformat()
    with engine.connect() as connection:
        request = connection.execute(sa.select(account_deletion_request)).mappings().one()
        assert request["account_id"] == account_id
        assert request["completed_at"] is None

    assert purge_due_deletions(engine, now=clock.now + dt.timedelta(hours=23)) == 0
    assert purge_due_deletions(engine, now=clock.now + dt.timedelta(hours=24)) == 1
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(account).where(account.c.account_id == account_id)
        ) == 0
        audit = connection.execute(sa.select(account_deletion_request)).mappings().one()
        assert audit["completed_at"] is not None
