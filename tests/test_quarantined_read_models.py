"""Retained alias evidence cannot authorize an unresolved private projection."""

import pytest
import sqlalchemy as sa
from test_saas_company_api import NOW, _insert_directory_company, _signup
from test_saas_company_api import app as app  # noqa: PLC0414 — fixture re-export
from test_saas_company_api import engine as engine  # noqa: PLC0414 — fixture re-export

from signals.dashboard.service import _week_activity_counts
from signals.engagement.company import set_contact
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    account_company_membership,
    company_subject_alias,
)
from signals.engagement.schema import company_contact

CANONICAL = "cmp_directory_331364729"
OTHER_CANONICAL = "cmp_directory_732829320"


def _override(connection, *, account_id, alias, canonical, private):
    connection.execute(
        company_subject_alias.insert().values(
            alias_company_key=alias,
            canonical_company_key=canonical,
            identifier_type="siren",
            identifier_value=canonical.removeprefix("cmp_directory_"),
            provenance="exact_official_identifier",
            resolution_status="exact",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    connection.execute(
        account_company_alias_override.insert().values(
            account_id=account_id,
            alias_company_key=alias,
            private_subject_key=private,
            mode="resolved" if private == canonical else "isolated",
            reason="preserved_private_work",
            created_at=NOW,
            updated_at=NOW,
        )
    )


def _follow(connection, *, account_id, company_key):
    connection.execute(
        account_company_membership.insert().values(
            account_id=account_id,
            company_key=company_key,
            origin="user",
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        )
    )


@pytest.mark.parametrize("binding", ["unresolved", "missing"])
@pytest.mark.parametrize(
    ("alias_status", "canonical_status", "after"),
    [("to_contact", "replied", 0), ("replied", "to_contact", 1)],
)
def test_scoped_week_reply_ignores_retained_override_without_exact_binding(
    app, engine, binding, alias_status, canonical_status, after
):
    client = _signup(app, email="quarantined-week@example.com")
    account_id = client.get("/me").json()["account_id"]
    alias = "cmp_historical_reply_alias"
    with engine.begin() as connection:
        _override(
            connection,
            account_id=account_id,
            alias=alias,
            canonical=CANONICAL,
            private=CANONICAL,
        )
        _follow(connection, account_id=account_id, company_key=alias)
        for key, status in [(alias, alias_status), (CANONICAL, canonical_status)]:
            set_contact(connection, account_id=account_id, company_key=key, status=status, now=NOW)
        assert _week_activity_counts(connection, account_id=account_id, now=NOW, signal_keys=())[
            "replied"
        ] == int(canonical_status == "replied")

        if binding == "missing":
            connection.execute(company_subject_alias.delete())
        else:
            connection.execute(
                company_subject_alias.update()
                .where(company_subject_alias.c.alias_company_key == alias)
                .values(resolution_status="unresolved")
            )
        assert (
            _week_activity_counts(connection, account_id=account_id, now=NOW, signal_keys=())[
                "replied"
            ]
            == after
        )
        # The reader must neither delete old evidence nor rewrite private work.
        assert connection.scalar(sa.select(sa.func.count()).select_from(company_contact)) == 2
        assert (
            connection.scalar(
                sa.select(account_company_alias_override.c.private_subject_key).where(
                    account_company_alias_override.c.account_id == account_id,
                    account_company_alias_override.c.alias_company_key == alias,
                )
            )
            == CANONICAL
        )


@pytest.mark.parametrize("binding", ["unresolved", "missing", "wrong_canonical"])
def test_directory_tracking_ignores_override_without_exact_self_binding(app, engine, binding):
    client = _signup(app, email="quarantined-directory@example.com")
    account_id = client.get("/me").json()["account_id"]
    private = "cmp_private_isolated_directory"
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="331364729", name="Société de recette")
        _override(
            connection,
            account_id=account_id,
            alias=CANONICAL,
            canonical=CANONICAL,
            private=private,
        )
        _follow(connection, account_id=account_id, company_key=private)
    first = client.get("/companies/directory").json()["items"][0]
    assert first["private_subject_key"] == private and first["tracked"] is True

    with engine.begin() as connection:
        if binding == "missing":
            connection.execute(company_subject_alias.delete())
        else:
            connection.execute(
                company_subject_alias.update()
                .where(company_subject_alias.c.alias_company_key == CANONICAL)
                .values(
                    **(
                        {"canonical_company_key": OTHER_CANONICAL}
                        if binding == "wrong_canonical"
                        else {"resolution_status": "unresolved"}
                    )
                )
            )
    response = client.get("/companies/directory")
    assert response.status_code == 200
    current = response.json()["items"][0]
    assert current["company_key"] == current["canonical_company_key"] == CANONICAL
    assert current["private_subject_key"] == CANONICAL
    assert current["tracked"] is False

    # The real directory identity can still be followed independently of the
    # retained historical private subject. The GET does not rewrite either row.
    with engine.begin() as connection:
        _follow(connection, account_id=account_id, company_key=CANONICAL)
    assert client.get("/companies/directory").json()["items"][0]["tracked"] is True
    with engine.connect() as connection:
        assert set(connection.scalars(sa.select(account_company_membership.c.company_key))) == {
            CANONICAL,
            private,
        }
        assert (
            connection.scalar(sa.select(account_company_alias_override.c.private_subject_key))
            == private
        )
