"""SPEC-013 §10, §23, §28, §30, §31, §34 — l'accès suit Stripe, et rien d'autre.

Le repli est toujours restrictif
────────────────────────────────
Pas d'abonnement, abonnement résilié, impayé, prix hors catalogue, statut
inattendu : tout mène à Discovery. Un défaut permissif — « en cas de doute,
on donne Pro » — est une faille qui attend son incident.

Une résiliation programmée ne retire rien
─────────────────────────────────────────
Stripe garde l'abonnement `active` jusqu'à la fin de la période déjà payée.
Inventer une date de coupure côté Kivou reviendrait à retirer un accès réglé.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import FakeStripe, subscribe
from fastapi.testclient import TestClient
from feed_helpers import COMPLETE_ICP_INPUT, ORIGIN, PASSWORD

from signals.accounts.schema import target_icp
from signals.api import ApiConfig, create_app
from signals.billing import catalogue, service
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
    migrate_to_latest,
)

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


class Clock:
    """Une horloge que le test avance : deux profils créés « en même temps » se
    départageraient par leur identifiant, ce qui rendrait l'ordre imprévisible
    alors que la règle, elle, parle d'ancienneté."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> dt.datetime:
        return self.now

    def tick(self, minutes: int = 1) -> None:
        self.now += dt.timedelta(minutes=minutes)


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(engine, clock: Clock):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            stripe_webhook_secret="whsec_test",
        ),
        now_override=clock,
        stripe_gateway=FakeStripe(),
    )


def signed_up(app, email: str = "alice@negoce-romand.ch") -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Negoce Romand SA",
            "locale": "fr",
        },
    )
    return client


@pytest.fixture
def alice(app) -> TestClient:
    return signed_up(app)


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def pay(engine, client: TestClient, **overrides) -> None:
    with engine.begin() as connection:
        subscribe(connection, account_id=account_of(client), now=NOW, **overrides)


def status(client: TestClient) -> dict:
    response = client.get("/billing/status")
    assert response.status_code == 200, response.text
    return response.json()


def add_icp(client: TestClient, label: str, clock: Clock | None = None) -> dict:
    created = client.post(
        "/target-icps", json={"label": label, "customer_input": COMPLETE_ICP_INPUT}
    ).json()
    if clock is not None:
        clock.tick()
    return created


# ─── §10 — quel statut ouvre quoi ─────────────────────────────────────────────


def test_an_account_without_any_subscription_is_discovery(alice):
    body = status(alice)
    assert body["plan_code"] == "discovery"
    assert body["subscription_status"] is None
    assert body["entitlements"]["max_active_icps"] == 1


@pytest.mark.parametrize("plan", ["essential", "pro", "scale"])
def test_an_active_subscription_unlocks_its_plan(alice, engine, plan: str):
    pay(engine, alice, plan=plan, status="active")
    body = status(alice)
    assert body["plan_code"] == plan
    assert body["subscription_status"] == "active"
    assert body["entitlements"]["max_active_icps"] == catalogue.PLANS[plan].max_active_icps


@pytest.mark.parametrize(
    "stripe_status",
    ["past_due", "unpaid", "incomplete", "incomplete_expired", "canceled", "paused", "trialing"],
)
def test_every_non_active_status_falls_back_to_discovery(alice, engine, stripe_status: str):
    pay(engine, alice, plan="scale", status=stripe_status)
    body = status(alice)
    assert body["plan_code"] == "discovery"
    assert body["subscription_status"] == stripe_status


def test_an_unknown_stripe_status_falls_back_to_discovery(alice, engine):
    pay(engine, alice, plan="pro", status="something_stripe_invented_later")
    assert status(alice)["plan_code"] == "discovery"


def test_a_cancel_at_period_end_subscription_keeps_its_access(alice, engine):
    """Stripe garde `active` jusqu'à la fin payée ; Kivou ne coupe pas avant lui."""
    pay(
        engine,
        alice,
        plan="pro",
        status="active",
        cancel_at_period_end=True,
        period_end=NOW + dt.timedelta(days=12),
    )
    body = status(alice)
    assert body["plan_code"] == "pro"
    assert body["cancel_at_period_end"] is True
    assert body["current_period_end"].startswith("2026-09-06")


def test_a_deleted_subscription_returns_the_account_to_discovery(alice, engine):
    pay(engine, alice, plan="pro", status="active")
    assert status(alice)["plan_code"] == "pro"
    pay(engine, alice, plan="pro", status="canceled", canceled_at=NOW)
    assert status(alice)["plan_code"] == "discovery"


def test_a_payment_issue_is_stated_plainly(alice, engine):
    pay(engine, alice, plan="pro", status="past_due")
    assert status(alice)["payment_issue"] == "payment_past_due"


def test_an_unknown_stripe_price_grants_no_paid_plan(alice, engine):
    pay(engine, alice, plan="pro", lookup_key="kivou_unknown_monthly_chf")
    body = status(alice)
    assert body["plan_code"] == "discovery", "aucun repli sur Pro"


# ─── §28 — ce que /billing/status ne dit pas ──────────────────────────────────


def test_the_status_exposes_no_secret_and_no_stripe_internals(alice, engine):
    pay(engine, alice, plan="pro")
    body = str(status(alice))
    for forbidden in ("sk_test", "sk_live", "whsec", "price_", "cus_", "sub_", "evt_", "coupon_"):
        assert forbidden not in body, forbidden


def test_the_status_needs_a_session(app):
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.get("/billing/status").status_code == 401


def test_one_account_never_reads_the_billing_of_another(app, engine):
    alice, bob = signed_up(app, "alice@negoce-romand.ch"), signed_up(app, "bob@materiaux-leman.ch")
    pay(engine, alice, plan="scale", subscription_id="sub_alice")
    assert status(alice)["plan_code"] == "scale"
    assert status(bob)["plan_code"] == "discovery"


# ─── §23 — les limites d'ICP ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("plan", "limit"), [("discovery", 1), ("essential", 1), ("pro", 3), ("scale", 10)]
)
def test_each_plan_declares_its_active_icp_limit(alice, engine, plan: str, limit: int):
    if plan != "discovery":
        pay(engine, alice, plan=plan)
    assert status(alice)["entitlements"]["max_active_icps"] == limit


def test_a_founding_account_receives_the_pro_limits(alice, engine):
    pay(engine, alice, plan="pro", coupon_id="coupon_test_f")
    body = status(alice)
    assert body["plan_code"] == "pro"
    assert body["offer_code"] == "founding"
    assert body["entitlements"]["max_active_icps"] == 3


def test_a_downgrade_deletes_nothing_and_names_what_is_over_the_limit(alice, engine, clock: Clock):
    """§23 — les données restent ; c'est au client de trancher."""
    pay(engine, alice, plan="pro")
    first = add_icp(alice, "Gros œuvre", clock)
    second = add_icp(alice, "Second œuvre", clock)
    third = add_icp(alice, "Génie civil", clock)
    assert status(alice)["target_icps_over_limit"] == []

    # Un changement de plan met à jour LE MÊME abonnement Stripe : le MVP
    # n'autorise qu'un abonnement payant par compte, et en créer un second
    # décrirait une situation que le produit refuse.
    pay(engine, alice, plan="essential")
    body = status(alice)
    assert body["plan_code"] == "essential"
    assert body["target_icps_over_limit"] == [
        second["target_icp_id"],
        third["target_icp_id"],
    ], "les plus anciens restent servis ; les suivants attendent une décision"

    with engine.connect() as connection:
        rows = connection.execute(sa.select(target_icp)).all()
    assert len(rows) == 3, "aucun profil supprimé"
    assert {row.status for row in rows} == {"active"}, "aucun profil désactivé d'office"
    assert first["target_icp_id"] in {row.target_icp_id for row in rows}


def test_the_feedable_subset_is_stable_across_reads(alice, engine, clock: Clock):
    pay(engine, alice, plan="pro")
    for label in ("A", "B", "C", "D"):
        add_icp(alice, label, clock)
    pay(engine, alice, plan="essential")

    account_id = account_of(alice)
    with engine.connect() as connection:
        first = service.feedable_target_icps(connection, account_id=account_id, limit=1)
        second = service.feedable_target_icps(connection, account_id=account_id, limit=1)
    assert first == second
    assert len(first) == 1


def test_an_upgrade_restores_every_profile_to_the_feed(alice, engine, clock: Clock):
    pay(engine, alice, plan="essential")
    for label in ("A", "B", "C"):
        add_icp(alice, label, clock)
    assert len(status(alice)["target_icps_over_limit"]) == 2

    pay(engine, alice, plan="scale")
    assert status(alice)["target_icps_over_limit"] == []


# ─── §7, §33 — l'offre fondateur est plafonnée par Kivou ─────────────────────


def test_kivou_counts_founding_accounts_itself(app, engine):
    """§7 — `max_redemptions` compte des coupons, pas des clients."""
    clients = [signed_up(app, f"founder{index}@negoce-romand.ch") for index in range(5)]
    for index, client in enumerate(clients):
        pay(engine, client, plan="pro", coupon_id="c", subscription_id=f"sub_f{index}")

    with engine.connect() as connection:
        assert service.founding_accounts(connection) == 5

    sixth = signed_up(app, "founder5@negoce-romand.ch")
    with engine.connect() as connection:
        assert service.founding_available(connection, account_id=account_of(sixth)) is False


def test_the_same_account_never_takes_two_founding_places(app, engine):
    client = signed_up(app)
    pay(engine, client, plan="pro", coupon_id="c", subscription_id="sub_f")
    with engine.connect() as connection:
        assert service.founding_available(connection, account_id=account_of(client)) is False
        assert service.founding_accounts(connection) == 1


def test_a_free_place_keeps_the_offer_available(app, engine):
    for index in range(4):
        pay(
            engine,
            signed_up(app, f"founder{index}@negoce-romand.ch"),
            plan="pro",
            coupon_id="c",
            subscription_id=f"sub_f{index}",
        )
    newcomer = signed_up(app, "newcomer@negoce-romand.ch")
    with engine.connect() as connection:
        assert service.founding_available(connection, account_id=account_of(newcomer)) is True


# ─── §30 — le mode Stripe ────────────────────────────────────────────────────


def test_a_live_object_is_refused_by_an_application_configured_for_test(alice, engine):
    from billing_helpers import subscription_state

    with engine.begin() as connection, pytest.raises(service.StripeModeMismatch):
        service.synchronize_subscription(
            connection,
            subscription_state(livemode=True),
            account_id=account_of(alice),
            event_created_at=NOW,
            expect_livemode=False,
            now=NOW,
        )


def test_the_configuration_refuses_a_live_key_in_test_mode(monkeypatch):
    monkeypatch.setenv("KIVOU_STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_exemple_de_cle_qui_ne_doit_pas_passer")
    with pytest.raises(ValueError, match="production"):
        ApiConfig.from_environment()


def test_the_configuration_refuses_a_test_key_in_live_mode(monkeypatch):
    monkeypatch.setenv("KIVOU_STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exemple_de_cle_qui_ne_doit_pas_passer")
    with pytest.raises(ValueError, match="test"):
        ApiConfig.from_environment()


def test_a_return_url_must_be_absolute_and_encrypted(monkeypatch):
    monkeypatch.setenv("STRIPE_SUCCESS_URL", "http://exemple.test/ok")
    with pytest.raises(ValueError, match="https"):
        ApiConfig.from_environment()


def test_automatic_tax_is_off_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("STRIPE_AUTOMATIC_TAX_ENABLED", raising=False)
    assert ApiConfig.from_environment().stripe_automatic_tax is False
    monkeypatch.setenv("STRIPE_AUTOMATIC_TAX_ENABLED", "true")
    assert ApiConfig.from_environment().stripe_automatic_tax is True


# ─── §34 — le chemin de migration ────────────────────────────────────────────


def test_an_empty_database_reaches_the_billing_schema_through_every_migration(
    tmp_path: pathlib.Path,
):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'chain.db'}")
    from alembic import command

    for revision in (
        "0001_initial",
        "0002_account_auth_target_icp",
        "0003_billing",
        "0004_alerts_feedback_analytics",
    ):
        command.upgrade(alembic_config(engine), revision)
        assert current_revision(engine) == revision
    migrate_to_latest(engine)
    assert current_revision(engine) == "0038_landing_journey"


def test_a_populated_spec012_database_upgrades_without_losing_anything(tmp_path: pathlib.Path):
    """Le seul test qui protège un déploiement déjà en service."""
    import sys

    sys.path.insert(0, "tests")
    from alembic import command
    from feed_helpers import COMPLETE_ICP_INPUT as ICP_INPUT
    from feed_helpers import SIMAP_RICH, make_account, make_icp, materialize_simap

    from signals.persistence.repository import list_signals

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'live.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        icp_id = make_icp(connection, account_id, "Intrants")
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
    assert ICP_INPUT

    command.downgrade(alembic_config(engine), "0002_account_auth_target_icp")
    migrate_to_latest(engine)

    with engine.connect() as connection:
        signals = list_signals(connection)
        icps = connection.execute(sa.select(target_icp)).all()
    assert [item.signal_key for item in signals] == [signal.signal_key]
    assert [row.target_icp_id for row in icps] == [icp_id]
    assert current_revision(engine) == "0038_landing_journey"


def test_the_billing_migration_touches_no_earlier_table(tmp_path: pathlib.Path):
    source = pathlib.Path("src/signals/persistence/migrations/versions").glob("0003_*.py")
    body = next(source).read_text(encoding="utf-8")
    upgrade = body[body.index("def upgrade()") : body.index("def downgrade()")]
    for earlier in (
        "source_event",
        "contract_award",
        "evidence",
        "opportunity_representation",
        "materialized_signal",
        "account",
        "auth_user",
        "auth_session",
        "password_reset",
        "target_icp",
    ):
        assert f"'{earlier}'" not in upgrade, earlier
    assert "op.drop_table" not in upgrade
    assert "op.alter_column" not in upgrade
