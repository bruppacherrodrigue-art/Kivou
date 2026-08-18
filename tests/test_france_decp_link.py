"""SPEC-009E R1 §5 — le rapprochement BOAMP × DECP, refait sur le jeu COURANT.

`tests/fixtures/france/boamp_decp2022_link.json` contient trois avis BOAMP réels
d'août 2026 et les onze enregistrements de `decp-2022-marches-valides` qui
partagent leur couple (acheteur, titulaire). Les périodes se recouvrent
réellement, ce qui n'était pas le cas dans SPEC-009E : le jeu hérité alors
mesuré s'arrêtait deux ans et demi plus tôt.

Le jeu couvre les trois situations d'un coup :

* **26-79799** — rapprochement exact : même date, même montant, même CPV.
* **26-79670** — même date et même CPV, montant divergent (200 000 contre
  100 000 €). Le schéma DECP dit « montant maximum » ; ce n'est pas la même
  grandeur que la valeur de l'offre publiée par le BOAMP.
* **26-79715** — six lots d'un marché de denrées alimentaires, et neuf
  enregistrements DECP du même couple acheteur/titulaire étalés de 2021 à 2025.
  Le leurre que SPEC-009E avait identifié se reproduit à l'identique sur le jeu
  courant.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from signals.connectors.boamp import parse_award_notice
from signals.connectors.decp import DECP_DATE_SEMANTICS, DECP_SOURCE_SYSTEM, parse_contract
from signals.france.link import (
    FIELD_PRIORITY,
    INDEPENDENT_CORROBORATORS,
    merge_award,
    resolve_candidates,
    unique_strong,
)

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "france"
PAYLOAD = json.loads((FIXTURE / "boamp_decp2022_link.json").read_text(encoding="utf-8"))
BOAMP = {record["idweb"]: record for record in PAYLOAD["boamp_records"]}
DECP = {record["id"]: record for record in PAYLOAD["decp_records"]}

RETRIEVED = dt.datetime(2026, 8, 18, 6, 0, tzinfo=dt.UTC)

EXACT_NOTICE = "26-79799"
EXACT_DECP = "178645481096900"
CONFLICT_NOTICE = "26-79670"
CONFLICT_DECP = "2026S02051"
DECOY_NOTICE = "26-79715"


def parsed(idweb: str):
    return parse_award_notice(BOAMP[idweb], retrieved_at=RETRIEVED)


def award_of(idweb: str, source_award_id: str = "CON-0001"):
    event, awards = parsed(idweb)
    return event, next(a for a in awards if a.source_award_id == source_award_id)


def test_the_fixture_really_uses_the_current_dataset():
    assert PAYLOAD["datasets"]["decp"] == "decp-2022-marches-valides"


# ─── §22 — DECP reste un contrat canonique autonome ────────────────────────────


def test_a_current_decp_record_stands_alone_without_a_boamp_parent():
    event, contract = parse_contract(DECP[EXACT_DECP], retrieved_at=RETRIEVED)
    assert event.provenance.source_system == DECP_SOURCE_SYSTEM
    assert contract.event_ref == event.ref()
    assert contract.contract_notification_date == dt.date(2026, 7, 16)
    assert contract.award_date is None


def test_no_decp_record_of_the_fixture_ever_produces_an_award_date():
    for record in DECP.values():
        _, contract = parse_contract(record, retrieved_at=RETRIEVED)
        assert contract.award_date is None
        assert contract.contract_signature_date is None


def test_the_declared_semantics_forbid_the_award_mapping():
    assert DECP_DATE_SEMANTICS["datenotification"]["can_represent_award_date"] == "NO"
    assert (
        DECP_DATE_SEMANTICS["datenotification"]["canonical_field"] == "contract_notification_date"
    )


# ─── §23 — résolution déterministe sur données courantes ───────────────────────


def test_a_same_buyer_winner_and_date_triple_is_a_strong_match():
    event, award = award_of(EXACT_NOTICE)
    candidates = resolve_candidates(award, event, DECP.values())
    strong = [c for c in candidates if c.strength == "strong"]
    assert [c.decp_id for c in strong] == [EXACT_DECP]
    assert {"buyer_siret", "winner_siret", "notification_date"} <= set(strong[0].matched_on)


def test_the_exact_match_agrees_on_amount_and_cpv_as_well():
    event, award = award_of(EXACT_NOTICE)
    candidate = next(
        c for c in resolve_candidates(award, event, DECP.values()) if c.decp_id == EXACT_DECP
    )
    assert "amount" in candidate.matched_on
    assert "cpv" in candidate.matched_on
    assert candidate.diverged_on == ()


def test_a_divergent_amount_does_not_prevent_a_strong_match():
    """La date et le CPV concordent : c'est le même contrat, vu par deux registres."""
    event, award = award_of(CONFLICT_NOTICE)
    candidate = next(
        c for c in resolve_candidates(award, event, DECP.values()) if c.decp_id == CONFLICT_DECP
    )
    assert candidate.strength == "strong"
    assert "amount" in candidate.diverged_on


@pytest.mark.parametrize("source_award_id", ["CON-0001", "CON-0003", "CON-0005"])
def test_nine_older_contracts_between_the_same_parties_are_never_strong(source_award_id: str):
    """Le leurre de SPEC-009E se reproduit sur le jeu courant : 2021 à 2025."""
    event, award = award_of(DECOY_NOTICE, source_award_id)
    candidates = resolve_candidates(award, event, DECP.values())
    assert all(c.strength != "strong" for c in candidates)


def test_the_decoys_are_reported_as_diverging_on_the_date():
    event, award = award_of(DECOY_NOTICE)
    candidates = [c for c in resolve_candidates(award, event, DECP.values()) if c.matched_on]
    assert candidates, "le couple de parties concorde bien : c'est ce qui rend le leurre dangereux"
    assert all("notification_date" in c.diverged_on for c in candidates)


def test_resolution_is_deterministic_across_runs():
    event, award = award_of(EXACT_NOTICE)
    first = resolve_candidates(award, event, DECP.values())
    second = resolve_candidates(award, event, DECP.values())
    assert [(c.decp_id, c.strength, c.matched_on) for c in first] == [
        (c.decp_id, c.strength, c.matched_on) for c in second
    ]


def test_the_strongest_candidate_comes_first():
    event, award = award_of(EXACT_NOTICE)
    candidates = resolve_candidates(award, event, DECP.values())
    assert candidates[0].decp_id == EXACT_DECP


# ─── §24, §25 — fusion et conflits ─────────────────────────────────────────────


def test_the_field_priority_table_is_explicit_and_justified():
    for field, rule in FIELD_PRIORITY.items():
        assert rule["preferred"] in {"boamp", "decp"}
        assert rule["conflict_policy"] in {"diagnostic", "prefer_without_diagnostic"}
        assert rule["reason"], f"{field} fusionné sans justification"


def test_an_exact_match_merges_without_any_conflict():
    _, award = award_of(EXACT_NOTICE)
    merged = merge_award(award, DECP[EXACT_DECP])
    assert merged.conflicts == ()
    assert merged.winner_siret == "97975674900011"
    assert merged.buyer_siret == "22140118500014"


def test_a_conflicting_amount_is_reported_and_never_silently_overwritten():
    _, award = award_of(CONFLICT_NOTICE)
    merged = merge_award(award, DECP[CONFLICT_DECP])
    conflicts = {c.field: c for c in merged.conflicts}
    assert "amount" in conflicts
    assert conflicts["amount"].boamp_value == "200000"
    assert conflicts["amount"].decp_value == "100000.0"
    assert str(merged.award.value.amount) == "200000", "la valeur BOAMP reste en place"


def test_the_amount_conflict_names_the_reason_the_two_figures_differ():
    _, award = award_of(CONFLICT_NOTICE)
    merged = merge_award(award, DECP[CONFLICT_DECP])
    note = next(c.note for c in merged.conflicts if c.field == "amount")
    assert "maximum" in note


def test_the_merge_carries_the_notification_date_without_touching_the_award_date():
    """R1 §2 — la fusion enrichit ; elle ne fabrique aucune date de décision."""
    _, award = award_of(EXACT_NOTICE)
    merged = merge_award(award, DECP[EXACT_DECP])
    assert merged.contract_notification_date == dt.date(2026, 7, 16)
    assert merged.award.award_date == dt.date(2026, 7, 2), "la décision BOAMP est conservée"
    assert merged.award.contract_notification_date is None, "le contrat canonique n'est pas réécrit"


def test_every_merged_fact_keeps_the_source_that_produced_it():
    _, award = award_of(EXACT_NOTICE)
    merged = merge_award(award, DECP[EXACT_DECP])
    assert merged.provenance == {"boamp": EXACT_NOTICE, "decp": EXACT_DECP}


def test_merging_the_same_pair_twice_changes_nothing():
    _, award = award_of(CONFLICT_NOTICE)
    once = merge_award(award, DECP[CONFLICT_DECP])
    twice = merge_award(award, DECP[CONFLICT_DECP])
    assert [(c.field, c.boamp_value, c.decp_value) for c in once.conflicts] == [
        (c.field, c.boamp_value, c.decp_value) for c in twice.conflicts
    ]


def test_the_duration_comes_from_decp_because_boamp_eforms_omits_it():
    _, award = award_of(EXACT_NOTICE)
    merged = merge_award(award, DECP[EXACT_DECP])
    assert award.duration is None
    assert merged.duration_months == DECP[EXACT_DECP]["dureemois"]


# ─── CLOSEOUT §1 — un lien fort exige un corroborant indépendant ───────────────


def test_the_four_real_strong_links_survive_the_hardening():
    """Les quatre liens forts mesurés en R2 portent déjà tous un corroborant."""
    for notice, decp_id, corroborator in (
        (EXACT_NOTICE, EXACT_DECP, "cpv"),
        (CONFLICT_NOTICE, CONFLICT_DECP, "cpv"),
    ):
        event, award = award_of(notice)
        candidate = next(
            c for c in resolve_candidates(award, event, DECP.values()) if c.decp_id == decp_id
        )
        assert candidate.strength == "strong"
        assert corroborator in candidate.matched_on


def test_parties_and_date_alone_are_no_longer_enough_for_a_strong_link():
    """§1 — le triplet identifie une relation commerciale, pas un contrat.

    On retire au candidat DECP tout corroborant indépendant : mêmes parties,
    même date, mais plus rien qui rattache les deux enregistrements au même
    marché. Le lien doit retomber à `probable`.
    """
    event, award = award_of(EXACT_NOTICE)
    stripped = dict(DECP[EXACT_DECP])
    stripped["codecpv"] = "99999999-9"
    stripped["montant"] = 1.0
    stripped["idaccordcadre"] = "CDL"
    candidate = next(
        c for c in resolve_candidates(award, event, [stripped]) if c.decp_id == EXACT_DECP
    )
    assert candidate.strength == "probable"
    assert "notification_date" in candidate.matched_on
    assert INDEPENDENT_CORROBORATORS.isdisjoint(candidate.matched_on)


def test_a_corroborator_without_a_compatible_date_stays_probable():
    event, award = award_of(EXACT_NOTICE)
    shifted = dict(DECP[EXACT_DECP])
    shifted["datenotification"] = "2025-01-01"
    candidate = next(
        c for c in resolve_candidates(award, event, [shifted]) if c.decp_id == EXACT_DECP
    )
    assert candidate.strength == "probable"


def test_an_exact_contract_reference_is_an_accepted_corroborator():
    event, award = award_of(EXACT_NOTICE)
    stripped = dict(DECP[EXACT_DECP])
    stripped["codecpv"] = "99999999-9"
    stripped["montant"] = 1.0
    stripped["idaccordcadre"] = award.contract_reference
    candidate = next(
        c for c in resolve_candidates(award, event, [stripped]) if c.decp_id == EXACT_DECP
    )
    assert "contract_reference" in candidate.matched_on
    assert candidate.strength == "strong"


def test_company_name_similarity_is_never_a_corroborator():
    """§1 — aucune ressemblance de raison sociale n'entre dans la décision."""
    assert INDEPENDENT_CORROBORATORS == frozenset({"cpv", "amount", "contract_reference"})
    assert not any("name" in field for field in INDEPENDENT_CORROBORATORS)


@pytest.mark.parametrize("decoy", ["202221V1498-01", "202120V1417-01", "202423V1710"])
def test_the_existing_decoys_remain_rejected_after_hardening(decoy: str):
    event, award = award_of(DECOY_NOTICE)
    candidates = {c.decp_id: c for c in resolve_candidates(award, event, DECP.values())}
    assert candidates[decoy].strength != "strong"


# ─── CLOSEOUT §2 — jamais de fusion arbitraire ────────────────────────────────

AMBIGUOUS = PAYLOAD["ambiguous_decp_records"]


def ambiguous_side():
    """Un avis BOAMP décrivant le marché que les deux contrats DECP se disputent.

    Le côté DECP est **réel** : deux menuiseries extérieures notifiées le même
    jour, au même titulaire, par le même acheteur, sous le même CPV. Le côté
    BOAMP est construit ici parce qu'aucun avis de la fixture ne porte ce
    couple — mais il ne contient que ce que le résolveur lit.
    """
    from signals.domain.awards import Awardee, AwardeeParty, ContractAward
    from signals.domain.events import Provenance, PublicEvent
    from signals.domain.values import CpvCode, OrganizationIdentifier, OrganizationRef

    def party(siret: str, name: str) -> OrganizationRef:
        return OrganizationRef(
            legal_name=name,
            identifiers=(OrganizationIdentifier(scheme="SIRET", value=siret),),
            country="FR",
        )

    event = PublicEvent(
        provenance=Provenance(
            source_system="boamp",
            source_country="FR",
            source_notice_id="26-ambigu",
        ),
        event_type="award_notice",
        published_at=dt.date(2026, 7, 20),
        procedure_buyers=(party("05850232900053", "Acheteur"),),
    )
    award = ContractAward(
        event_ref=event.ref(),
        source_award_id="CON-0001",
        cpv_main=CpvCode(code="44220000"),
        contract_signature_date=dt.date(2026, 7, 8),
        awardee_parties=(
            AwardeeParty(members=(Awardee(organization=party("77557282900049", "Titulaire")),)),
        ),
    )
    return event, award


def test_the_fixture_contains_two_real_contracts_impossible_to_tell_apart():
    """Même acheteur, même titulaire, même jour, même CPV — et deux marchés."""
    first, second = AMBIGUOUS
    assert first["acheteur_id"] == second["acheteur_id"]
    assert first["titulaire_id_1"] == second["titulaire_id_1"]
    assert first["datenotification"] == second["datenotification"] == "2026-07-08"
    assert first["codecpv"] == second["codecpv"]
    assert first["id"] != second["id"]
    assert first["montant"] != second["montant"]


def test_this_ambiguity_is_frequent_enough_to_matter():
    """61 groupes de ce type sur 600 contrats lus : le risque n'est pas théorique."""
    assert PAYLOAD["ambiguity_frequency"]["groups_sharing_buyer_winner_date_and_cpv"] == 61


def test_two_equally_strong_candidates_are_never_arbitrarily_merged():
    event, award = ambiguous_side()
    candidates = resolve_candidates(award, event, AMBIGUOUS)
    assert len(candidates) == 2, "les deux candidats sont conservés"
    assert all(c.strength != "strong" for c in candidates), "aucune fusion arbitraire"
    assert all(c.ambiguous for c in candidates)
    assert all("cpv" in c.matched_on for c in candidates), "les deux étaient bien corroborés"


def test_an_ambiguous_resolution_offers_no_unique_strong_link():
    event, award = ambiguous_side()
    assert unique_strong(resolve_candidates(award, event, AMBIGUOUS)) is None


def test_removing_the_competitor_restores_a_strong_link():
    """La preuve que le déclassement vient bien de l'ambiguïté, et de rien d'autre."""
    event, award = ambiguous_side()
    alone = resolve_candidates(award, event, AMBIGUOUS[:1])
    assert alone[0].strength == "strong"
    assert not alone[0].ambiguous


def test_a_single_strong_candidate_is_offered_for_merging():
    event, award = award_of(EXACT_NOTICE)
    candidate = unique_strong(resolve_candidates(award, event, DECP.values()))
    assert candidate is not None
    assert candidate.decp_id == EXACT_DECP
    assert not candidate.ambiguous


def test_no_candidate_is_dropped_when_the_guard_fires():
    event, award = ambiguous_side()
    candidates = resolve_candidates(award, event, AMBIGUOUS)
    assert {c.decp_id for c in candidates} == {record["id"] for record in AMBIGUOUS}


# ─── CLOSEOUT §2 — « également forts » se mesure, il ne se suppose pas ─────────

DOMINATED = PAYLOAD["dominated_decp_records"]
DOMINANT_NOTICE = "26-79293"


def test_the_fixture_contains_a_real_double_publication():
    """DECP publie deux fois le même contrat sous deux identifiants distincts."""
    first, second = DOMINATED
    assert {first["id"], second["id"]} == {"26-011", "20262601101"}
    assert first["datenotification"] == second["datenotification"]
    assert first["montant"] == second["montant"]
    assert first["codecpv"] == second["codecpv"]


def test_an_exact_contract_reference_breaks_the_tie_deterministically():
    """Un candidat strictement mieux corroboré n'est pas une ambiguïté."""
    event, award = award_of(DOMINANT_NOTICE)
    assert award.contract_reference == "26-011"
    candidates = {c.decp_id: c for c in resolve_candidates(award, event, DOMINATED)}
    assert candidates["26-011"].strength == "strong"
    assert "contract_reference" in candidates["26-011"].matched_on
    assert not candidates["26-011"].ambiguous


def test_the_dominated_duplicate_is_kept_but_never_strong():
    event, award = award_of(DOMINANT_NOTICE)
    candidates = {c.decp_id: c for c in resolve_candidates(award, event, DOMINATED)}
    assert candidates["20262601101"].strength == "probable"
    assert not candidates["20262601101"].ambiguous, "il est dominé, pas ambigu"


def test_a_dominant_candidate_is_offered_for_merging():
    event, award = award_of(DOMINANT_NOTICE)
    winner = unique_strong(resolve_candidates(award, event, DOMINATED))
    assert winner is not None
    assert winner.decp_id == "26-011"


def test_equal_corroboration_still_blocks_the_merge():
    """Le départage ne doit jamais dégénérer en « prendre le meilleur »."""
    event, award = ambiguous_side()
    assert unique_strong(resolve_candidates(award, event, AMBIGUOUS)) is None
