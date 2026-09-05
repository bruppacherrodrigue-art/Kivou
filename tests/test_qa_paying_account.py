from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from feed_helpers import COMPLETE_ICP_INPUT, materialize_simap

from signals.accounts.schema import account, auth_user, target_icp
from signals.billing.schema import billing_subscription
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.engagement.schema import company_contact, company_note
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import contract_award, materialized_signal
from signals.qa.paying_account import build_paying_recipe_account, main

NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.UTC)


def test_command_refuses_production_before_opening_database(monkeypatch, capsys):
    opened = False

    def forbidden_engine():
        nonlocal opened
        opened = True
        raise AssertionError("database must not be opened")

    result = main(
        environ={
            "KIVOU_ENV": "production",
            "KIVOU_QA_PAYING_EMAIL": "paying-qa@kivou-qa.ch",
            "KIVOU_QA_PAYING_PASSWORD": "unused-secret",
        },
        engine_factory=forbidden_engine,
    )

    assert result == 2
    assert opened is False
    assert capsys.readouterr().err == "error=production_forbidden\n"


def test_recipe_account_is_idempotent_and_has_requested_shape(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        source_account = connection.execute(
            sa.insert(account).values(
                account_id="acc_source",
                display_name="Source",
                locale="fr",
                onboarding_status="profile_confirmed",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        del source_account
        connection.execute(
            sa.insert(auth_user).values(
                user_id="usr_source",
                account_id="acc_source",
                email_normalized="source@kivou.test",
                password_hash="not-used",
                is_active=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.insert(target_icp).values(
                target_icp_id="ticp_source",
                account_id="acc_source",
                label="Source",
                status="active",
                matching_revision=1,
                plan_limit_code=None,
                plan_limited_at=None,
                customer_input=COMPLETE_ICP_INPUT,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for notice in ("29997-02", "33112-02", "33885-03"):
            materialize_simap(connection, notice, target_icp_id="ticp_source")
        run_winner_enrichment_batch(connection, now=NOW, worker_ref="qa-recipe-source", limit=10)
        unresolved_award = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key)
            .where(materialized_signal.c.target_icp_id == "ticp_source")
            .order_by(materialized_signal.c.signal_key)
            .limit(1)
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == unresolved_award)
            .values(awardee_parties=[])
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.materialization_award_key == unresolved_award)
            .values(company_identity_fingerprint=None)
        )

    for _ in range(2):
        result = build_paying_recipe_account(
            engine,
            email="paying-qa@kivou-qa.ch",
            password="fixture-password",
            now=NOW,
            signal_count=3,
            contact_count=2,
            note_count=1,
        )
        assert result.signal_count == 3
        assert result.profile_count == 2
        assert result.contact_count == 2
        assert result.note_count == 1

    with engine.connect() as connection:
        account_id = connection.scalar(
            sa.select(auth_user.c.account_id).where(
                auth_user.c.email_normalized == "paying-qa@kivou-qa.ch"
            )
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(target_icp)
                .where(target_icp.c.account_id == account_id)
            )
            == 2
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(materialized_signal)
                .join(target_icp, materialized_signal.c.target_icp_id == target_icp.c.target_icp_id)
                .where(target_icp.c.account_id == account_id)
            )
            == 3
        )
        subscription = connection.execute(
            sa.select(billing_subscription).where(billing_subscription.c.account_id == account_id)
        ).one()
        assert subscription.plan_code == "essential"
        assert subscription.current_period_start.replace(tzinfo=dt.UTC) == (
            NOW - dt.timedelta(days=90)
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(company_contact)
                .where(company_contact.c.account_id == account_id)
            )
            == 2
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(company_note)
                .where(company_note.c.account_id == account_id)
            )
            == 1
        )
