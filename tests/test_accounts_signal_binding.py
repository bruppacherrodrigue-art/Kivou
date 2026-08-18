"""SPEC-011 closeout §3 — quel client possède un signal matérialisé, et lequel n'a personne.

L'historique du dépôt crée un cas de transition qu'on ne peut pas effacer : les
signaux produits par SPEC-010 référencent des identifiants d'ICP de **recherche**,
créés avant qu'un compte client existe. Ils ont survécu à la migration, et c'est
voulu — mais ils n'appartiennent à personne.

La règle est donc binaire, et ne souffre aucune ressemblance de chaîne :

    le `target_icp_id` du signal désigne une ligne `target_icp`
        → le compte propriétaire est celui de cette ligne

    aucune ligne correspondante
        → NON LIÉ. Pas de client. Jamais visible.

`target_icp.account_id` est la **seule** source de propriété. Rien n'est déduit
du contenu du signal, du contenu de l'ICP, de ce que le compte a saisi, ni d'une
similarité de ciblage.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest
import sqlalchemy as sa
from alembic import command

from signals.accounts.icp_input import TargetIcpInput
from signals.accounts.ownership import (
    CustomerBinding,
    account_for_materialized_signal,
    customer_binding_for_signal,
    customer_signal_keys,
    signal_is_owned_by,
)
from signals.accounts.service import create_target_icp, sign_up
from signals.connectors.boamp import parse_award_notice
from signals.matching import MatchingEngine
from signals.matching.reference import CONSTRUCTION_INPUTS_ICP
from signals.needs import NeedGraphEngine
from signals.persistence.database import alembic_config, create_database_engine, migrate_to_latest
from signals.persistence.materialization import materialize_signal
from signals.persistence.repository import list_signals
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

#: L'identifiant d'ICP de RECHERCHE utilisé par SPEC-010, avant tout compte.
RESEARCH_ICP_ID = "icp-construction-inputs-ch-eu-v0"

COMPLETE_INPUT = {
    "offers": ["materials_and_components"],
    "buyer_trades": ["building_construction"],
    "territories": ["CH", "FR"],
    "minimum_contract_value": {"currency": "CHF", "minimum_amount": 100000},
}


def materialize(connection: sa.Connection, *, target_icp_id: str, index: int = 0):
    event, awards = parse_award_notice(RECORD, retrieved_at=NOW)
    award = awards[index]
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
    return create_target_icp(
        connection,
        account_id=account_id,
        label=label,
        customer_input=TargetIcpInput.model_validate(COMPLETE_INPUT),
        now=NOW,
    ).target_icp_id


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


# ─── A — le signal d'avant les comptes n'appartient à personne ─────────────────


@pytest.fixture
def legacy_engine(tmp_path: pathlib.Path):
    """Une base SPEC-010 peuplée AVANT les comptes, puis migrée en 0002."""
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    command.upgrade(alembic_config(engine), "0001_initial")
    with engine.begin() as connection:
        materialize(connection, target_icp_id=RESEARCH_ICP_ID)
    migrate_to_latest(engine)
    return engine


def test_a_pre_account_signal_survives_the_migration(legacy_engine):
    with legacy_engine.connect() as connection:
        signals = list_signals(connection)
    assert len(signals) == 1
    assert signals[0].target_icp_id == RESEARCH_ICP_ID


def test_a_pre_account_signal_is_unbound(legacy_engine):
    with legacy_engine.connect() as connection:
        signals = list_signals(connection)
        binding = customer_binding_for_signal(connection, signal_key=signals[0].signal_key)
    assert binding == CustomerBinding(
        signal_key=signals[0].signal_key, target_icp_id=RESEARCH_ICP_ID, account_id=None
    )
    assert not binding.is_bound


def test_a_pre_account_signal_resolves_to_no_account(legacy_engine):
    with legacy_engine.connect() as connection:
        signals = list_signals(connection)
        assert account_for_materialized_signal(connection, signal_key=signals[0].signal_key) is None


def test_no_account_can_claim_a_pre_account_signal(legacy_engine):
    """Un identifiant de recherche ne devient pas client parce qu'il y ressemble."""
    with legacy_engine.begin() as connection:
        account_id = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        signal_key = list_signals(connection)[0].signal_key
        assert not signal_is_owned_by(connection, signal_key=signal_key, account_id=account_id)


def test_creating_an_icp_whose_label_matches_the_research_profile_binds_nothing(legacy_engine):
    """Aucune liaison par similarité de ciblage : seul l'identifiant compte."""
    with legacy_engine.begin() as connection:
        account_id = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        make_icp(connection, account_id, "Intrants de chantier CH/UE")
        signal_key = list_signals(connection)[0].signal_key
        assert account_for_materialized_signal(connection, signal_key=signal_key) is None


# ─── B — un signal client résout vers exactement son compte ───────────────────


def test_a_customer_bound_signal_resolves_to_the_owning_account(engine):
    with engine.begin() as connection:
        account_id = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        icp_id = make_icp(connection, account_id, "Intrants")
        signal = materialize(connection, target_icp_id=icp_id)

    with engine.connect() as connection:
        binding = customer_binding_for_signal(connection, signal_key=signal.signal_key)
        assert binding == CustomerBinding(
            signal_key=signal.signal_key, target_icp_id=icp_id, account_id=account_id
        )
        assert binding.is_bound
        assert (
            account_for_materialized_signal(connection, signal_key=signal.signal_key) == account_id
        )
        assert signal_is_owned_by(connection, signal_key=signal.signal_key, account_id=account_id)


def test_an_unknown_signal_key_resolves_to_nothing(engine):
    with engine.connect() as connection:
        assert customer_binding_for_signal(connection, signal_key="sig_inexistant") is None
        assert account_for_materialized_signal(connection, signal_key="sig_inexistant") is None


# ─── C — le compte voisin ne peut rien revendiquer ────────────────────────────


def test_account_b_cannot_claim_the_signal_of_account_a(engine):
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        bob = make_account(connection, "bob@materiaux-leman.ch", "Materiaux Leman")
        alice_icp = make_icp(connection, alice, "Intrants Alice")
        make_icp(connection, bob, "Intrants Bob")
        signal = materialize(connection, target_icp_id=alice_icp)

    with engine.connect() as connection:
        assert signal_is_owned_by(connection, signal_key=signal.signal_key, account_id=alice)
        assert not signal_is_owned_by(connection, signal_key=signal.signal_key, account_id=bob)
        assert account_for_materialized_signal(connection, signal_key=signal.signal_key) == alice


def test_ownership_never_comes_from_the_account_asking(engine):
    """§3 — la propriété se lit dans `target_icp.account_id`, pas dans la question."""
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        bob = make_account(connection, "bob@materiaux-leman.ch", "Materiaux Leman")
        alice_icp = make_icp(connection, alice, "Intrants")
        signal = materialize(connection, target_icp_id=alice_icp)

    with engine.connect() as connection:
        # La même question posée par deux comptes donne la même réponse.
        first = customer_binding_for_signal(connection, signal_key=signal.signal_key)
        second = customer_binding_for_signal(connection, signal_key=signal.signal_key)
        assert first == second == CustomerBinding(signal.signal_key, alice_icp, alice)
        assert bob != alice


# ─── D — deux ciblages identiques restent deux propriétés distinctes ──────────


def test_two_accounts_with_equivalent_icp_content_keep_distinct_ownership(engine):
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        bob = make_account(connection, "bob@materiaux-leman.ch", "Materiaux Leman")
        alice_icp = make_icp(connection, alice, "Intrants")
        bob_icp = make_icp(connection, bob, "Intrants")
        alice_signal = materialize(connection, target_icp_id=alice_icp)
        bob_signal = materialize(connection, target_icp_id=bob_icp)

    assert alice_icp != bob_icp
    assert alice_signal.signal_key != bob_signal.signal_key
    assert alice_signal.opportunity_key == bob_signal.opportunity_key, "un seul marché derrière"

    with engine.connect() as connection:
        assert (
            account_for_materialized_signal(connection, signal_key=alice_signal.signal_key) == alice
        )
        assert account_for_materialized_signal(connection, signal_key=bob_signal.signal_key) == bob
        assert not signal_is_owned_by(
            connection, signal_key=bob_signal.signal_key, account_id=alice
        )


def test_the_ownership_query_starts_from_the_account_not_from_the_signals(engine):
    """SPEC-012 — filtrer après coup laisserait passer les signaux non liés."""
    with engine.begin() as connection:
        alice = make_account(connection, "alice@negoce-romand.ch", "Negoce Romand")
        alice_icp = make_icp(connection, alice, "Intrants")
        materialize(connection, target_icp_id=alice_icp)
        materialize(connection, target_icp_id=RESEARCH_ICP_ID, index=1)

    with engine.connect() as connection:
        assert len(list_signals(connection)) == 2, "les deux existent bien en base"
        owned = customer_signal_keys(connection, account_id=alice)
        assert len(owned) == 1, "le signal non lié ne doit jamais entrer"
        assert all(
            signal_is_owned_by(connection, signal_key=key, account_id=alice) for key in owned
        )
