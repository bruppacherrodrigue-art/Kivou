"""SPEC-011 §13, §17 — un TargetICP appartient à un compte, et à un seul.

Deux familles de tests.

L'**isolation** : un compte ne doit pas pouvoir lire, modifier, ni même deviner
l'existence d'un profil voisin. La réponse à « profil d'un autre » et à « profil
inexistant » doit être la même, sinon l'API devient un oracle qu'on interroge
une adresse à la fois.

La **traduction** : ce que le client déclare devient un `TargetICP` moteur
déterministe, ou reste incomplet. Rien n'est deviné, et deux clients qui visent
exactement la même chose reçoivent deux profils distincts — sans quoi les
signaux de l'un apparaîtraient chez l'autre.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from signals.accounts.icp_input import (
    MonetaryThreshold,
    TargetIcpInput,
    to_target_icp,
)
from signals.accounts.schema import account, target_icp
from signals.accounts.service import onboarding_status
from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest

ORIGIN = "https://app.kivou.ch"
PASSWORD = "un-mot-de-passe-assez-long"

COMPLETE_INPUT = {
    "offer_summary": "Négoce de matériaux de gros œuvre livrés sur chantier",
    "offers": ["materials_and_components"],
    "buyer_trades": ["building_construction", "interior_finishing"],
    "territories": ["CH", "FR"],
    "minimum_contract_value": {"currency": "CHF", "minimum_amount": 100000},
}


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 8, 18, 9, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def app(engine):
    return create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN),
        now_override=Clock(),
    )


def account_client(app, email: str, company: str) -> TestClient:
    """Un client authentifié sur son propre compte."""
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "company_name": company, "locale": "fr"},
    )
    assert response.status_code == 201
    return client


@pytest.fixture
def alice(app) -> TestClient:
    return account_client(app, "alice@negoce-romand.ch", "Negoce Romand SA")


@pytest.fixture
def bob(app) -> TestClient:
    return account_client(app, "bob@materiaux-leman.ch", "Materiaux Leman SA")


def create_icp(client: TestClient, label: str = "Intrants de chantier", **overrides) -> dict:
    payload = {"label": label, "customer_input": {**COMPLETE_INPUT, **overrides}}
    response = client.post("/target-icps", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ─── §17 — appartenance ────────────────────────────────────────────────────────


def test_a_target_icp_belongs_to_exactly_one_account(alice: TestClient, engine):
    created = create_icp(alice)
    with engine.connect() as connection:
        owners = (
            connection.execute(
                sa.select(target_icp.c.account_id).where(
                    target_icp.c.target_icp_id == created["target_icp_id"]
                )
            )
            .scalars()
            .all()
        )
    assert len(owners) == 1


def test_two_accounts_defining_the_same_icp_receive_distinct_identifiers(
    alice: TestClient, bob: TestClient
):
    """§17 — aucune déduplication par contenu : les feeds ne doivent pas se mélanger."""
    first = create_icp(alice)
    second = create_icp(bob)
    assert first["target_icp_id"] != second["target_icp_id"]
    assert first["customer_input"] == second["customer_input"]


def test_one_account_may_own_several_target_icps(alice: TestClient):
    create_icp(alice, label="Gros œuvre")
    create_icp(alice, label="Second œuvre")
    listed = alice.get("/target-icps").json()
    assert len(listed) == 2
    assert {item["label"] for item in listed} == {"Gros œuvre", "Second œuvre"}


def test_the_list_only_shows_the_account_own_profiles(alice: TestClient, bob: TestClient):
    create_icp(alice, label="Chez Alice")
    create_icp(bob, label="Chez Bob")
    assert [item["label"] for item in alice.get("/target-icps").json()] == ["Chez Alice"]
    assert [item["label"] for item in bob.get("/target-icps").json()] == ["Chez Bob"]


# ─── §13, §16.15-17 — isolation inter-comptes ─────────────────────────────────


def test_one_account_cannot_read_another_accounts_icp(alice: TestClient, bob: TestClient):
    created = create_icp(alice)
    response = bob.get(f"/target-icps/{created['target_icp_id']}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "target_icp_not_found"


def test_one_account_cannot_update_another_accounts_icp(alice: TestClient, bob: TestClient):
    created = create_icp(alice)
    response = bob.patch(f"/target-icps/{created['target_icp_id']}", json={"label": "Détourné"})
    assert response.status_code == 404
    assert alice.get(f"/target-icps/{created['target_icp_id']}").json()["label"] != "Détourné"


def test_a_foreign_profile_is_indistinguishable_from_a_missing_one(
    alice: TestClient, bob: TestClient
):
    """Distinguer « interdit » de « inexistant » serait un oracle d'énumération."""
    created = create_icp(alice)
    foreign = bob.get(f"/target-icps/{created['target_icp_id']}")
    missing = bob.get("/target-icps/ticp_inexistant")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_an_account_id_supplied_by_the_client_is_refused_outright(alice: TestClient):
    """§13 — la propriété vient de la session ; le corps n'a pas de mot à dire."""
    response = alice.post(
        "/target-icps",
        json={"label": "Usurpation", "account_id": "acc_de_quelqu_un_dautre"},
    )
    assert response.status_code == 422


def test_an_unauthenticated_caller_sees_nothing(app):
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.get("/target-icps").status_code == 401
    assert anonymous.post("/target-icps", json={"label": "X"}).status_code == 401


# ─── §12, §14 — complétude et onboarding ───────────────────────────────────────


def test_an_incomplete_profile_stays_a_draft_and_says_what_is_missing(alice: TestClient):
    response = alice.post(
        "/target-icps",
        json={"label": "Brouillon", "customer_input": {"offers": ["safety_equipment"]}},
    )
    body = response.json()
    assert body["status"] == "draft"
    assert set(body["missing_fields"]) == {"territories", "minimum_contract_value"}


def test_completing_a_draft_makes_it_active(alice: TestClient):
    draft = alice.post(
        "/target-icps",
        json={"label": "Brouillon", "customer_input": {"offers": ["materials_and_components"]}},
    ).json()
    completed = alice.patch(
        f"/target-icps/{draft['target_icp_id']}", json={"customer_input": COMPLETE_INPUT}
    ).json()
    assert completed["status"] == "active"
    assert completed["missing_fields"] == []


def test_the_onboarding_state_follows_the_profiles(alice: TestClient):
    assert alice.get("/me").json()["onboarding_status"] == "account_created"

    draft = alice.post(
        "/target-icps",
        json={"label": "Brouillon", "customer_input": {"offers": ["materials_and_components"]}},
    ).json()
    assert alice.get("/me").json()["onboarding_status"] == "icp_incomplete"

    alice.patch(f"/target-icps/{draft['target_icp_id']}", json={"customer_input": COMPLETE_INPUT})
    assert alice.get("/me").json()["onboarding_status"] == "ready_for_signals"


def test_ready_for_signals_says_nothing_about_payment_or_activation(alice: TestClient):
    """§14 — complétude TECHNIQUE, jamais activation commerciale."""
    create_icp(alice)
    body = alice.get("/me").json()
    assert body["onboarding_status"] == "ready_for_signals"
    assert not any(key in body for key in ("plan", "subscription", "trial", "entitlement"))


# ─── §12 — le vocabulaire moteur ne fuit pas ───────────────────────────────────


def test_the_customer_never_sees_engine_vocabulary(alice: TestClient):
    body = create_icp(alice)
    serialized = str(body)
    for engine_term in (
        "need_categor",
        "trade_domain",
        "geography_basis",
        "unknown_value_policy",
        "source_modes",
        "maximum_signal_age",
        "score",
        "weight",
    ):
        assert engine_term not in serialized, engine_term


def test_an_unknown_customer_field_is_refused_rather_than_ignored(alice: TestClient):
    response = alice.post(
        "/target-icps",
        json={"label": "X", "customer_input": {**COMPLETE_INPUT, "score_weight": 3}},
    )
    assert response.status_code == 422


# ─── §12 — la traduction vers le moteur ────────────────────────────────────────


def test_a_complete_input_translates_into_a_valid_engine_profile():
    customer_input = TargetIcpInput.model_validate(COMPLETE_INPUT)
    profile = to_target_icp(customer_input, target_icp_id="ticp_test", label="Intrants")

    assert profile.icp_id == "ticp_test"
    assert profile.primary_need_categories == ("materials_or_components",)
    assert profile.primary_trade_domains == ("general_building", "interior_finishing")
    assert [territory.country for territory in profile.territories] == ["CH", "FR"]
    assert profile.value_thresholds[0].currency == "CHF"


def test_an_incomplete_input_refuses_to_produce_a_profile():
    """§12 — une case manquante ne se devine pas."""
    with pytest.raises(ValueError, match="incomplète"):
        to_target_icp(
            TargetIcpInput(offers=("materials_and_components",)),
            target_icp_id="ticp_test",
            label="Incomplet",
        )


def test_a_category_declared_twice_does_not_break_the_engine_profile():
    """Un client peut cocher la même offre en principal et en secondaire."""
    customer_input = TargetIcpInput(
        offers=("materials_and_components",),
        secondary_offers=("materials_and_components", "equipment_rental"),
        territories=("CH",),
        minimum_contract_value=MonetaryThreshold(currency="CHF", minimum_amount=1000),
    )
    profile = to_target_icp(customer_input, target_icp_id="ticp_test", label="Doublon")
    assert profile.primary_need_categories == ("materials_or_components",)
    assert profile.secondary_need_categories == ("equipment_or_rental",)


def test_secondary_trades_without_a_primary_one_are_incomplete():
    """Le moteur refuse ce profil ; l'onboarding doit le dire avant lui."""
    customer_input = TargetIcpInput(
        offers=("materials_and_components",),
        secondary_buyer_trades=("interior_finishing",),
        territories=("CH",),
        minimum_contract_value=MonetaryThreshold(currency="CHF", minimum_amount=1000),
    )
    assert "buyer_trades" in customer_input.missing_fields()


def test_the_offer_summary_stays_declarative(alice: TestClient):
    """SPEC-008 — deux textes différents, mêmes champs, même profil moteur."""
    first = TargetIcpInput.model_validate({**COMPLETE_INPUT, "offer_summary": "Texte A"})
    second = TargetIcpInput.model_validate({**COMPLETE_INPUT, "offer_summary": "Texte B"})
    profile_a = to_target_icp(first, target_icp_id="t", label="L")
    profile_b = to_target_icp(second, target_icp_id="t", label="L")
    assert profile_a.model_dump(exclude={"offer_summary"}) == profile_b.model_dump(
        exclude={"offer_summary"}
    )


# ─── closeout §5 — l'état d'onboarding redescend aussi ─────────────────────────

INCOMPLETE_INPUT = {"offers": ["materials_and_components"]}


def stored_status(engine, *, account_id: str) -> str:
    """§5 — `/me` lit la colonne stockée : c'est ELLE qui ne doit pas dériver."""
    with engine.connect() as connection:
        return connection.execute(
            sa.select(account.c.onboarding_status).where(account.c.account_id == account_id)
        ).scalar_one()


def computed_status(engine, *, account_id: str) -> str:
    with engine.connect() as connection:
        return onboarding_status(connection, account_id=account_id)


def account_id_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def test_an_account_falls_back_to_icp_incomplete_when_its_only_icp_regresses(
    alice: TestClient, engine
):
    """CAS A — un profil vidé de l'essentiel n'est plus prêt, et le compte non plus."""
    created = create_icp(alice)
    account_id = account_id_of(alice)
    assert alice.get("/me").json()["onboarding_status"] == "ready_for_signals"

    regressed = alice.patch(
        f"/target-icps/{created['target_icp_id']}", json={"customer_input": INCOMPLETE_INPUT}
    ).json()

    assert regressed["status"] == "draft"
    assert set(regressed["missing_fields"]) == {"territories", "minimum_contract_value"}
    assert alice.get("/me").json()["onboarding_status"] == "icp_incomplete"
    assert stored_status(engine, account_id=account_id) == "icp_incomplete"


def test_an_account_keeps_ready_for_signals_while_one_icp_stays_active(alice: TestClient, engine):
    """CAS B — un profil abîmé n'annule pas un profil sain."""
    first = create_icp(alice, label="Gros œuvre")
    create_icp(alice, label="Second œuvre")
    account_id = account_id_of(alice)

    alice.patch(f"/target-icps/{first['target_icp_id']}", json={"customer_input": INCOMPLETE_INPUT})

    assert alice.get("/me").json()["onboarding_status"] == "ready_for_signals"
    assert stored_status(engine, account_id=account_id) == "ready_for_signals"
    statuses = {item["label"]: item["status"] for item in alice.get("/target-icps").json()}
    assert statuses == {"Gros œuvre": "draft", "Second œuvre": "active"}


def test_the_state_goes_back_up_when_the_profile_is_repaired(alice: TestClient, engine):
    created = create_icp(alice)
    account_id = account_id_of(alice)
    alice.patch(
        f"/target-icps/{created['target_icp_id']}", json={"customer_input": INCOMPLETE_INPUT}
    )
    assert stored_status(engine, account_id=account_id) == "icp_incomplete"

    alice.patch(f"/target-icps/{created['target_icp_id']}", json={"customer_input": COMPLETE_INPUT})

    assert alice.get("/me").json()["onboarding_status"] == "ready_for_signals"
    assert stored_status(engine, account_id=account_id) == "ready_for_signals"


def test_relabelling_alone_never_moves_the_onboarding_state(alice: TestClient, engine):
    created = create_icp(alice)
    account_id = account_id_of(alice)

    alice.patch(f"/target-icps/{created['target_icp_id']}", json={"label": "Autre nom"})

    assert stored_status(engine, account_id=account_id) == "ready_for_signals"


@pytest.mark.parametrize(
    ("payloads", "expected"),
    [
        ((), "account_created"),
        ((INCOMPLETE_INPUT,), "icp_incomplete"),
        ((COMPLETE_INPUT,), "ready_for_signals"),
        ((INCOMPLETE_INPUT, COMPLETE_INPUT), "ready_for_signals"),
        ((INCOMPLETE_INPUT, INCOMPLETE_INPUT), "icp_incomplete"),
    ],
)
def test_the_stored_state_never_drifts_from_the_actual_profile_set(
    alice: TestClient, engine, payloads: tuple[dict, ...], expected: str
):
    """§5 — stocké et calculé doivent coïncider dans chaque configuration."""
    for index, payload in enumerate(payloads):
        alice.post("/target-icps", json={"label": f"Profil {index}", "customer_input": payload})
    account_id = account_id_of(alice)

    assert stored_status(engine, account_id=account_id) == expected
    assert computed_status(engine, account_id=account_id) == expected
    assert alice.get("/me").json()["onboarding_status"] == expected
