"""SPEC-011 §5, §17, §22 — la montée de version, et la propriété d'un signal.

Deux garanties.

La **migration** : une base SPEC-010 déjà peuplée doit atteindre le schéma
SPEC-011 sans perdre un signal. C'est le seul test qui protège les données d'un
déploiement existant, et il part d'une vraie base à `0001_initial` plutôt que
d'une base neuve.

La **propriété** : un signal appartient à un compte *par l'intermédiaire* de son
TargetICP, jamais directement. La chaîne est donc vérifiée de bout en bout, y
compris dans le sens négatif — le compte voisin ne doit rien pouvoir en tirer.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from signals.accounts.icp_input import TargetIcpInput
from signals.accounts.schema import (
    account,
    auth_session,
    auth_user,
    password_reset,
    target_icp,
)
from signals.accounts.service import create_target_icp, sign_up
from signals.connectors.boamp import parse_award_notice
from signals.matching import MatchingEngine
from signals.matching.reference import CONSTRUCTION_INPUTS_ICP
from signals.needs import NeedGraphEngine
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
    migrate_to_latest,
)
from signals.persistence.materialization import materialize_signal
from signals.persistence.repository import list_signals
from signals.persistence.schema import materialized_signal
from signals.recency import assess_recency
from signals.understanding import ContractUnderstandingEngine

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "france"
RECORD = next(
    record
    for record in json.loads((FIXTURE / "boamp_records.json").read_text(encoding="utf-8"))[
        "records"
    ]
    if record["idweb"] == "26-80978"
)

NOW = dt.datetime(2026, 8, 18, 9, 0, tzinfo=dt.UTC)
AS_OF = dt.date(2026, 8, 18)


def materialize(connection: sa.Connection, *, target_icp_id: str):
    """Fait passer un avis réel dans toute la chaîne, pour l'ICP indiqué."""
    event, awards = parse_award_notice(RECORD, retrieved_at=NOW)
    award = awards[0]
    understanding = ContractUnderstandingEngine().understand(award, event)
    needs = NeedGraphEngine().derive(understanding)
    profile = CONSTRUCTION_INPUTS_ICP.model_copy(update={"icp_id": target_icp_id})
    match = MatchingEngine().match(understanding, needs, profile, as_of=AS_OF)
    recency = assess_recency(
        award_date=award.award_date,
        contract_notification_date=award.contract_notification_date,
        publication_date=event.published_at,
        as_of=AS_OF,
    )
    return materialize_signal(
        connection,
        event=event,
        award=award,
        understanding=understanding,
        needs=needs,
        match=match,
        recency=recency,
        as_of=AS_OF,
        materialized_at=NOW,
    )


# ─── §22 — chemin de migration ─────────────────────────────────────────────────


def test_an_empty_database_reaches_the_latest_schema_through_every_migration(
    tmp_path: pathlib.Path,
):
    """La révision de tête est nommée : une SPEC qui en ajoute une doit le dire ici."""
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)

    with engine.connect() as connection:
        tables = set(sa.inspect(connection).get_table_names())
    assert {"source_event", "contract_award", "materialized_signal"} <= tables
    assert {"account", "auth_user", "auth_session", "password_reset", "target_icp"} <= tables
    # SPEC-013 — la facturation s'ajoute sans rien retirer de ce qui précède.
    assert {
        "billing_customer",
        "billing_subscription",
        "stripe_webhook_event",
        "discovery_signal_grant",
    } <= tables
    # SPEC-014 — retour client, analytique et alertes, également additifs.
    assert {
        "signal_feedback",
        "product_event",
        "account_notification_preference",
        "signal_alert_delivery",
    } <= tables
    # SPEC-016A — operational ingestion state remains an additive migration.
    assert {"ingestion_checkpoint", "ingestion_run"} <= tables
    assert current_revision(engine) == "0030_winner_enrichment"


def test_a_spec010_database_upgrades_without_losing_its_signals(tmp_path: pathlib.Path):
    """Le seul test qui protège les données d'un déploiement déjà en service."""
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")

    # Construire la ligne avec le code courant, puis revenir au schéma SPEC-010,
    # évite qu'un helper courant tente d'écrire des colonnes qui n'existaient
    # pas encore. Le point de départ de l'upgrade reste bien une base 0001
    # peuplée, pas une base neuve.
    migrate_to_latest(engine)
    with engine.begin() as connection:
        result = materialize(connection, target_icp_id="icp-construction-inputs-ch-eu-v0")
    command.downgrade(alembic_config(engine), "0001_initial")
    assert current_revision(engine) == "0001_initial"
    with engine.connect() as connection:
        before = connection.execute(
            sa.select(sa.func.count()).select_from(materialized_signal)
        ).scalar()
    assert before == 1

    migrate_to_latest(engine)

    with engine.connect() as connection:
        after = list_signals(connection)
    assert len(after) == 1
    assert after[0].signal_key == result.signal_key
    assert after[0].target_icp_id == "icp-construction-inputs-ch-eu-v0"


def test_the_second_migration_creates_no_table_that_already_existed(tmp_path: pathlib.Path):
    """§22 — aucune table de `0001_initial` n'est recréée destructivement."""
    source = pathlib.Path("src/signals/persistence/migrations/versions").glob("0002_*.py")
    body = next(source).read_text(encoding="utf-8")
    upgrade = body[body.index("def upgrade()") : body.index("def downgrade()")]
    for spec010_table in (
        "source_event",
        "contract_award",
        "evidence",
        "opportunity_representation",
        "materialized_signal",
    ):
        assert f"'{spec010_table}'" not in upgrade, spec010_table
    assert "op.drop_table" not in upgrade
    assert "op.alter_column" not in upgrade


def test_migrating_twice_is_a_no_operation(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    with engine.connect() as connection:
        before = sorted(sa.inspect(connection).get_table_names())
    migrate_to_latest(engine)
    with engine.connect() as connection:
        assert sorted(sa.inspect(connection).get_table_names()) == before


# ─── §5, §17 — la propriété passe par le TargetICP ─────────────────────────────


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


def make_account(connection: sa.Connection, email: str, company: str) -> str:
    session = sign_up(
        connection,
        email=email,
        password="un-mot-de-passe-assez-long",
        company_name=company,
        locale="fr",
        now=NOW,
        session_ttl=dt.timedelta(days=1),
    )
    return session.account_id


def make_icp(connection: sa.Connection, account_id: str, label: str) -> str:
    stored = create_target_icp(
        connection,
        account_id=account_id,
        label=label,
        customer_input=TargetIcpInput.model_validate(
            {
                "offers": ["materials_and_components"],
                "territories": ["CH"],
                "minimum_contract_value": {"currency": "CHF", "minimum_amount": 100000},
            }
        ),
        now=NOW,
    )
    return stored.target_icp_id


def test_a_signal_is_owned_through_its_target_icp(engine):
    """§5 — la chaîne signal → TargetICP → compte, sans `account_id` redondant."""
    with engine.begin() as connection:
        account_id = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        icp_id = make_icp(connection, account_id, "Intrants")
        materialize(connection, target_icp_id=icp_id)

    with engine.connect() as connection:
        owner = connection.execute(
            sa.select(target_icp.c.account_id).select_from(
                materialized_signal.join(
                    target_icp, materialized_signal.c.target_icp_id == target_icp.c.target_icp_id
                )
            )
        ).scalar_one()
    assert owner == account_id


def test_no_redundant_account_column_exists_on_the_signal():
    """§5 — la propriété se dérive ; la dupliquer créerait deux vérités."""
    assert "account_id" not in {column.name for column in materialized_signal.columns}


def test_one_target_icp_may_carry_several_signals(engine):
    with engine.begin() as connection:
        account_id = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        icp_id = make_icp(connection, account_id, "Intrants")
        event, awards = parse_award_notice(RECORD, retrieved_at=NOW)
        assert len(awards) >= 2
        for award in awards[:2]:
            understanding = ContractUnderstandingEngine().understand(award, event)
            needs = NeedGraphEngine().derive(understanding)
            profile = CONSTRUCTION_INPUTS_ICP.model_copy(update={"icp_id": icp_id})
            match = MatchingEngine().match(understanding, needs, profile, as_of=AS_OF)
            recency = assess_recency(
                award_date=award.award_date,
                contract_notification_date=award.contract_notification_date,
                publication_date=event.published_at,
                as_of=AS_OF,
            )
            materialize_signal(
                connection,
                event=event,
                award=award,
                understanding=understanding,
                needs=needs,
                match=match,
                recency=recency,
                as_of=AS_OF,
                materialized_at=NOW,
            )

    with engine.connect() as connection:
        signals = list_signals(connection, target_icp_id=icp_id)
    assert len(signals) == 2


def test_an_icp_of_one_account_never_carries_the_signals_of_another(engine):
    """§17 — le feed de Bob ne doit rien contenir de celui d'Alice."""
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        bob = make_account(connection, "bob@materiaux-leman.ch", "Materiaux Leman")
        alice_icp = make_icp(connection, alice, "Intrants Alice")
        bob_icp = make_icp(connection, bob, "Intrants Bob")
        materialize(connection, target_icp_id=alice_icp)

    with engine.connect() as connection:
        assert len(list_signals(connection, target_icp_id=alice_icp)) == 1
        assert list_signals(connection, target_icp_id=bob_icp) == []


def test_two_accounts_targeting_the_same_market_get_two_signals(engine):
    """Le même marché, deux clients : deux signaux distincts, jamais partagés."""
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        bob = make_account(connection, "bob@materiaux-leman.ch", "Materiaux Leman")
        alice_icp = make_icp(connection, alice, "Intrants")
        bob_icp = make_icp(connection, bob, "Intrants")
        first = materialize(connection, target_icp_id=alice_icp)
        second = materialize(connection, target_icp_id=bob_icp)

    assert first.signal_key != second.signal_key
    assert first.opportunity_key == second.opportunity_key, "un seul marché derrière"


def test_the_account_of_a_signal_cannot_be_forged_by_relabelling_an_icp(engine):
    """Renommer un ICP ne change pas son propriétaire."""
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        icp_id = make_icp(connection, alice, "Intrants")
        materialize(connection, target_icp_id=icp_id)
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == icp_id)
            .values(label="Autre nom")
        )

    with engine.connect() as connection:
        owner = connection.execute(
            sa.select(target_icp.c.account_id).where(target_icp.c.target_icp_id == icp_id)
        ).scalar_one()
    assert owner == alice


def test_deleting_an_account_cascades_to_its_users_and_profiles(engine):
    """La cascade évite qu'un profil survive à son propriétaire."""
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        make_icp(connection, alice, "Intrants")
        connection.execute(sa.delete(account).where(account.c.account_id == alice))

    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(auth_user)).scalar() == 0
        assert connection.execute(sa.select(sa.func.count()).select_from(target_icp)).scalar() == 0


# ─── §3 (hérité de SPEC-010) — portabilité PostgreSQL des tables SPEC-011 ──────

ACCOUNT_TABLES = (account, auth_user, auth_session, password_reset, target_icp)


@pytest.mark.parametrize("table", ACCOUNT_TABLES, ids=lambda table: table.name)
def test_every_account_table_compiles_to_postgresql_ddl(table: sa.Table):
    """La production vise PostgreSQL ; la compilation le prouve sans serveur."""
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert ddl.startswith("\nCREATE TABLE")
    assert table.name in ddl


@pytest.mark.parametrize("table", ACCOUNT_TABLES, ids=lambda table: table.name)
def test_every_account_table_compiles_to_sqlite_ddl(table: sa.Table):
    assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=sqlite.dialect()))


def test_no_account_column_uses_a_dialect_specific_type():
    """Un type propre à un dialecte casserait la suite, qui tourne sur SQLite."""
    for table in ACCOUNT_TABLES:
        for column in table.columns:
            module = type(column.type).__module__
            assert "dialects" not in module, f"{table.name}.{column.name} : {column.type!r}"
