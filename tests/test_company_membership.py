import sqlalchemy as sa
from test_company_entity_aliases import NOW, A
from test_company_entity_aliases import db as db  # noqa: PLC0414 — pytest fixture re-export

from signals.client_value.prospecting import company_membership, follow_company
from signals.engagement.prospecting_schema import account_company_membership


def test_follow_is_explicit_idempotent_and_private(db):
    with db.begin() as connection:
        assert (
            company_membership(connection, account_id="account_a", company_key=A)["tracked"]
            is False
        )
        one = follow_company(connection, account_id="account_a", company_key=A, now=NOW)
        two = follow_company(connection, account_id="account_a", company_key=A, now=NOW)
        assert one == two and one["tracked"] is True and one["revision"] == 1
        assert (
            company_membership(connection, account_id="account_b", company_key=A)["tracked"]
            is False
        )
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(account_company_membership)
            ).scalar_one()
            == 1
        )
