"""WEDGE-HARDENING R2 — le BKP publié prime le CPV du projet.

Le closeout R1 laissait trois signaux faibles rattachés à la même couche : le
CPV décrit le projet, pas le lot vendu. Le corpus le prouve — un même chantier
de piscine est publié en treize avis portant tous `45212212`, pour treize
métiers différents. Seul le code BKP distingue.

Ces tests éprouvent la règle, jamais les trois cas : aucun identifiant de
signal, de notice, d'award ni de titre du banc n'y figure (§16). Les trois
régressions réelles vivent en fin de fichier, reconstruites depuis leurs seuls
faits publics — code BKP, CPV, et le métier que l'autorité leur donne.
"""

from __future__ import annotations

import datetime as dt

import pytest

from signals.domain import ContractAward, EventRef, Provenance, PublicEvent
from signals.domain.values import CpvCode
from signals.understanding import ContractUnderstandingEngine
from signals.understanding.bkp import (
    BKP_TRADE_RULES,
    bkp_codes,
    resolve_trade_domain,
    trade_domain_for_bkp,
)

PUBLISHED = dt.date(2026, 3, 23)


def _award(*, title: str, description: str | None = None, cpv: str | None) -> ContractAward:
    return ContractAward(
        event_ref=EventRef(source_system="simap", source_notice_id="n-1"),
        title=title,
        description=description,
        cpv_main=CpvCode(code=cpv) if cpv else None,
        winner_status="undisclosed",
    )


def _event(system: str = "simap") -> PublicEvent:
    return PublicEvent(
        provenance=Provenance(
            source_system=system,
            source_notice_id="n-1",
            source_country="CH",
            source_url="https://example.invalid/n-1",
            retrieved_at=dt.datetime(2026, 8, 18, tzinfo=dt.UTC),
        ),
        published_at=PUBLISHED,
        event_type="award_notice",
    )


def _domain(award: ContractAward, *, system: str = "simap") -> str | None:
    claim = ContractUnderstandingEngine().understand(award, _event(system)).trade_domain
    return claim.value if claim else None


def _claim(award: ContractAward, *, system: str = "simap"):
    return ContractUnderstandingEngine().understand(award, _event(system)).trade_domain


# ─── Le parser (§12) ────────────────────────────────────────────────────────────


class TestBkpParser:
    def test_an_explicit_code_is_read(self) -> None:
        assert bkp_codes("BKP 230 Elektroinstallationen") == ("230",)

    def test_a_decimal_code_keeps_its_decimal(self) -> None:
        assert bkp_codes("BKP 272.8 Poolauskleidung") == ("272.8",)

    def test_a_two_digit_family_is_read(self) -> None:
        assert bkp_codes("BKP 23 Elektro") == ("23",)

    def test_codes_chained_on_a_real_separator_are_all_read(self) -> None:
        """Les avis écrivent « 222_224 », « 224, 221.1 », « 227/285 »."""
        assert bkp_codes("BKP 222_224 Spenglerarbeiten") == ("222", "224")
        assert bkp_codes("BKP224, 221.1 Montagebau") == ("224", "221.1")
        assert bkp_codes("BKP 227/285 Oberflächen") == ("227", "285")

    def test_the_marker_is_mandatory(self) -> None:
        """§12 — un nombre à trois chiffres n'est pas un BKP."""
        assert bkp_codes("Lot 230 Elektroinstallationen") == ()
        assert bkp_codes("Umbau Freibad 8424 Embrach / 272.8") == ()

    def test_a_year_or_a_reference_is_not_a_code(self) -> None:
        assert bkp_codes("Neubau Schulhaus 2026") == ()
        assert bkp_codes("Sanierung 2026/2027") == ()

    def test_the_marker_must_stand_alone_from_letters(self) -> None:
        assert bkp_codes("ABKP 230") == ()
        assert bkp_codes("BKPX 230") == ()

    def test_the_marker_survives_glue_characters_used_by_publishers(self) -> None:
        """« BKP224 » sans espace, « Q26.0169_BKP 211 » après un souligné."""
        assert bkp_codes("BKP224 Bedachung") == ("224",)
        assert bkp_codes("Q26.0169_BKP 211_Bern, Instandsetzung 2026/2027") == ("211",)

    def test_a_cpv_code_is_never_mistaken_for_a_bkp(self) -> None:
        assert bkp_codes("Marché CPV 45210000 travaux") == ()


# ─── La table d'autorité (§6, §15) ──────────────────────────────────────────────


class TestBkpAuthority:
    def test_a_recognized_code_maps_to_its_authority_family(self) -> None:
        assert trade_domain_for_bkp("213") == "general_building"  # 21 Rohbau 1
        assert trade_domain_for_bkp("230") == "technical_installation"  # 23 Elektroanlagen
        assert trade_domain_for_bkp("250") == "technical_installation"  # 25 Sanitäranlagen
        assert trade_domain_for_bkp("271") == "interior_finishing"  # 27 Ausbau 1
        assert trade_domain_for_bkp("201") == "earthworks_demolition"  # 20 Baugrube

    def test_a_decimal_code_is_read_through_its_family(self) -> None:
        assert trade_domain_for_bkp("272.8") == trade_domain_for_bkp("272") == "interior_finishing"
        assert trade_domain_for_bkp("231.5") == "technical_installation"  # 23 Starkstromanlagen

    def test_a_family_without_a_representable_domain_yields_nothing(self) -> None:
        """§15 — on ne crée pas un domaine pour faire entrer un cas.

        `42 Gartenanlagen` est un métier réel qu'aucun domaine de la taxonomie
        R1 ne représente : ni gros œuvre, ni second œuvre, ni terrassement.
        """
        assert trade_domain_for_bkp("421") is None
        assert BKP_TRADE_RULES["42"] is None

    def test_the_three_digit_exceptions_escape_their_family(self) -> None:
        """Nettoyage et jardinage vivent dans `28 Ausbau 2` sans en être."""
        assert trade_domain_for_bkp("281") == "interior_finishing"
        assert trade_domain_for_bkp("287") is None  # Baureinigung
        assert trade_domain_for_bkp("288") is None  # Gärtnerarbeiten (Gebäude)

    def test_an_unknown_code_invents_nothing(self) -> None:
        """§11 — pas de fuzzy matching, pas de code voisin, pas de devinette."""
        assert trade_domain_for_bkp("777") is None
        assert trade_domain_for_bkp("6") is None


# ─── La résolution multi-codes (§13) ────────────────────────────────────────────


class TestMultipleCodes:
    def test_several_codes_of_one_family_are_deterministic(self) -> None:
        assert resolve_trade_domain(("222", "224"))[0] == "general_building"
        assert resolve_trade_domain(("244", "246"))[0] == "technical_installation"

    def test_the_order_of_the_codes_does_not_change_the_answer(self) -> None:
        assert resolve_trade_domain(("224", "222"))[0] == resolve_trade_domain(("222", "224"))[0]

    def test_codes_of_different_trades_resolve_to_nothing(self) -> None:
        """§13 — prendre le premier serait arbitraire."""
        domain, reason = resolve_trade_domain(("227", "285"))
        assert domain is None
        assert "métiers différents" in reason

    def test_a_recognized_code_beside_an_unrepresentable_one_still_decides(self) -> None:
        assert resolve_trade_domain(("271", "287"))[0] == "interior_finishing"


# ─── La précédence sur le CPV (§9, §10, §11) ────────────────────────────────────


class TestPrecedenceOverCpv:
    def test_the_published_bkp_wins_over_the_project_cpv(self) -> None:
        """Le cas structurel : un CPV de projet, un BKP de métier."""
        award = _award(
            title="Neubau Schulanlage", description="BKP 250 Sanitärinstallationen", cpv="45210000"
        )
        assert _domain(award) == "technical_installation"

    def test_the_decision_says_that_it_overrode_the_cpv(self) -> None:
        """§10 — on doit pouvoir expliquer plus tard pourquoi BKP a primé."""
        award = _award(title="Neubau", description="BKP 250 Sanitärinstallationen", cpv="45210000")
        claim = _claim(award)
        assert "BKP" in claim.rule
        assert "prime" in claim.rule and "general_building" in claim.rule

    def test_the_override_carries_its_own_evidence_to_the_published_field(self) -> None:
        """§18 — la preuve démontre la CLASSIFICATION, pas un achat futur."""
        award = _award(title="Neubau", description="BKP 250 Sanitärinstallationen", cpv="45210000")
        claim = _claim(award)
        assert claim.evidence
        assert {e.path for e in claim.evidence} <= {"title", "description"}
        assert all("BKP" in (e.raw_value or "") for e in claim.evidence)

    def test_agreement_between_bkp_and_cpv_is_not_reported_as_a_conflict(self) -> None:
        award = _award(title="Rohbau", description="BKP 211 Baumeisterarbeiten", cpv="45210000")
        claim = _claim(award)
        assert claim.value == "general_building"
        assert "prime" not in claim.rule

    def test_a_bkp_fills_a_cpv_that_says_nothing(self) -> None:
        """`45000000` annonce des travaux sans annoncer lesquels."""
        award = _award(title="Neubau", description="BKP 230 Elektroanlagen", cpv="45000000")
        assert _domain(award) == "technical_installation"

    def test_an_unrepresentable_bkp_never_overrides(self) -> None:
        """§11 — on conserve le CPV, avec le diagnostic."""
        award = _award(
            title="Instandsetzung", description="BKP 421 Gärtnerarbeiten", cpv="45210000"
        )
        claim = _claim(award)
        assert claim.value == "general_building"
        assert "conservé" in claim.rule

    def test_conflicting_bkp_codes_never_override(self) -> None:
        award = _award(
            title="Oberflächen", description="BKP 227/285 Anstricharbeiten", cpv="45210000"
        )
        claim = _claim(award)
        assert claim.value == "general_building"
        assert "métiers différents" in claim.rule

    def test_a_title_and_a_description_naming_two_trades_do_not_decide(self) -> None:
        """Les deux champs sont fusionnés, pas mis en concurrence."""
        award = _award(
            title="BKP 230 Elektro", description="BKP 271 Gipserarbeiten", cpv="45210000"
        )
        assert _domain(award) == "general_building"


# ─── Ce qui ne doit pas bouger (§19) ────────────────────────────────────────────


class TestUntouchedWithoutBkp:
    def test_a_simap_award_without_bkp_keeps_its_cpv_domain(self) -> None:
        award = _award(title="Neubau Schulanlage", description="Rohbauarbeiten", cpv="45210000")
        claim = _claim(award)
        assert claim.value == "general_building"
        assert "CPV" in claim.rule and "BKP" not in claim.rule

    def test_a_ted_award_without_bkp_keeps_its_cpv_domain(self) -> None:
        award = _award(
            title="Travaux de voirie", description="Réfection de chaussée", cpv="45233220"
        )
        assert _domain(award, system="ted") == "roadworks_civil"

    def test_a_generic_construction_cpv_without_bkp_stays_silent(self) -> None:
        award = _award(title="Travaux", description="Voir cahier des charges", cpv="45000000")
        assert _claim(award) is None

    def test_a_contract_outside_construction_stays_silent(self) -> None:
        award = _award(title="Fourniture de réactifs", description=None, cpv="33696500")
        assert _claim(award) is None


# ─── Les trois régressions réelles (§21) ────────────────────────────────────────


class TestThreeRemainingCases:
    """Reconstruites de leurs seuls faits publics : code BKP et CPV.

    Aucun identifiant de signal, de notice ou d'award, aucun nom d'entreprise,
    aucun titre exact du banc (§16). La règle doit valoir pour toute occurrence
    équivalente, pas pour ces trois lignes.
    """

    @pytest.mark.parametrize(
        ("bkp", "cpv", "expected", "authority"),
        [
            # Le photovoltaïque est du courant fort : 23 Elektroanlagen.
            ("BKP 231.5 PVA", "45210000", "technical_installation", "231 Starkstromanlagen"),
            # Un revêtement de bassin est de la construction métallique : 27 Ausbau 1.
            (
                "BKP 272.8 Poolauskleidung",
                "45212212",
                "interior_finishing",
                "272 Metallbauarbeiten",
            ),
        ],
    )
    def test_a_specialist_lot_leaves_general_building(
        self, bkp: str, cpv: str, expected: str, authority: str
    ) -> None:
        award = _award(title="Projet", description=bkp, cpv=cpv)
        claim = _claim(award)
        assert claim.value == expected, authority
        assert claim.value != "general_building"

    def test_a_landscaping_lot_is_left_unresolved_rather_than_invented(self) -> None:
        """§15 — `42 Gartenanlagen` n'a pas de domaine dans la taxonomie R1.

        Le CPV reste en place et le diagnostic le dit. Ne pas résoudre est le
        résultat honnête : inventer un domaine pour ce seul cas serait
        exactement ce que §32 interdit.
        """
        award = _award(
            title="Instandsetzung", description="BKP 421 Gärtnerarbeiten", cpv="45210000"
        )
        claim = _claim(award)
        assert trade_domain_for_bkp("421") is None
        assert claim.value == "general_building"
        assert "sans domaine de métier correspondant" in claim.rule
