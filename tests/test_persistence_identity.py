"""SPEC-010 §7 — l'identité d'un signal, et pourquoi elle ne bouge pas.

Rematérialiser deux fois le même marché pour le même client ne doit pas créer
deux opportunités dans le feed. La clé logique répond donc à une seule
question : *de quel marché, pour quel client, s'agit-il ?* — et à aucune autre.

En particulier elle ne contient **aucune version de moteur**. Une amélioration
du Need Graph ne transforme pas un signal en un signal différent ; elle en
produit une nouvelle révision.
"""

from __future__ import annotations

import pytest

from signals.domain.awards import Awardee, AwardeeParty, ContractAward, LotRef
from signals.domain.events import EventRef, Provenance, PublicEvent
from signals.domain.values import OrganizationRef
from signals.persistence.identity import award_key, event_key, signal_key

ICP = "icp-construction-inputs-ch-eu-v0"


def signal_of(contract, *, icp: str = ICP) -> str:
    """La clé d'un signal, l'opportunité étant ici représentée par l'award lui-même.

    En production l'`opportunity_key` vient de la base (`resolve_or_create_opportunity`)
    ; ces tests portent sur la fonction de clé, pas sur la résolution.
    """
    return signal_key(award_key(contract), target_icp_id=icp)


def event(notice: str = "26-80978", version: str | None = None) -> PublicEvent:
    return PublicEvent(
        provenance=Provenance(
            source_system="boamp",
            source_country="FR",
            source_notice_id=notice,
            notice_version=version,
        ),
        event_type="award_notice",
    )


def award(
    *,
    notice: str = "26-80978",
    version: str | None = None,
    contract: str | None = "CON-0001",
    lot: str | None = "LOT-0001",
) -> ContractAward:
    return ContractAward(
        event_ref=EventRef(source_system="boamp", source_notice_id=notice, notice_version=version),
        source_award_id=contract,
        lot=LotRef(identifier=lot) if lot else None,
        awardee_parties=(
            AwardeeParty(members=(Awardee(organization=OrganizationRef(legal_name="Gagnant")),)),
        ),
    )


# ─── clé d'événement ───────────────────────────────────────────────────────────


def test_the_event_key_is_the_canonical_reference_the_domain_already_defines():
    """`EventRef.key()` existe depuis SPEC-005 — la persistance ne réinvente rien."""
    assert event_key(event()) == event().ref().key() == "boamp:26-80978:"


def test_two_notice_versions_are_two_events():
    """Une correction TED est un événement distinct, pas une mise à jour."""
    assert event_key(event(version="01")) != event_key(event(version="02"))


# ─── clé d'award-lot ───────────────────────────────────────────────────────────


def test_the_award_key_is_stable_across_runs():
    assert award_key(award()) == award_key(award())


def test_two_lots_of_the_same_notice_are_two_awards():
    assert award_key(award(lot="LOT-0001")) != award_key(award(lot="LOT-0002"))


def test_two_contracts_on_the_same_lot_are_two_awards():
    """Un accord-cadre attribue plusieurs contrats au même lot."""
    assert award_key(award(contract="CON-0001")) != award_key(award(contract="CON-0002"))


def test_an_award_without_a_published_contract_identifier_still_gets_a_key():
    """La clé de stockage doit exister même quand `source_identity()` rend `None`."""
    assert award_key(award(contract=None))


def test_an_award_without_identifiers_does_not_collide_with_a_sibling_lot():
    assert award_key(award(contract=None, lot="LOT-0001")) != award_key(
        award(contract=None, lot="LOT-0002")
    )


# ─── clé de signal ─────────────────────────────────────────────────────────────


def test_the_same_award_and_icp_always_yield_the_same_signal():
    """§7 — mêmes faits source + même gagnant + même lot + même ICP → même signal."""
    assert signal_of(award()) == signal_of(award())


def test_two_icp_contexts_produce_two_distinct_signals():
    """Le même marché intéresse deux clients différemment : deux signaux."""
    assert signal_of(award()) != signal_of(award(), icp="icp-autre-v0")


def test_two_lots_produce_two_distinct_signals():
    assert signal_of(award(lot="LOT-0001")) != signal_of(award(lot="LOT-0002"))


def test_the_signal_key_never_depends_on_an_engine_version():
    """§7 — une nouvelle version de moteur produit une RÉVISION, pas un signal neuf.

    Le test est structurel : la clé se calcule sans qu'aucune version ne lui
    soit passée, donc elle ne peut pas en dépendre.
    """
    import inspect

    parameters = set(inspect.signature(signal_key).parameters)
    assert parameters == {"opportunity_key", "target_icp_id"}


def test_an_empty_target_icp_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError, match="target_icp_id"):
        signal_key("une-opportunite", target_icp_id="")


def test_an_empty_opportunity_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError, match="opportunity_key"):
        signal_key("", target_icp_id=ICP)


def test_keys_are_url_safe_and_bounded():
    """Une clé sert d'identifiant stocké et, plus tard, d'identifiant d'URL."""
    for key in (event_key(event()), award_key(award()), signal_of(award())):
        assert key
        assert len(key) <= 128
        assert all(character.isalnum() or character in ":-_." for character in key)
