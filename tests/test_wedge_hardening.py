"""WEDGE-HARDENING R1 — les trois corrections, et ce qu'elles ne touchent pas.

SPEC-009B a mesuré le wedge « intrants de chantier × `materials_or_components` »
à 80,5 % de précision utile, bloqué au vert par 4,5 points. Huit signaux faibles,
huit causes nommées : six de granularité métier, deux de sujet du besoin. Un
neuvième défaut — un objet publié réduit à l'intitulé d'une rubrique de
formulaire — a été tracé séparément.

Chaque règle ajoutée est éprouvée trois fois, comme l'exige §46 : sur le cas
qu'elle doit attraper, sur le cas voisin qu'elle ne doit PAS attraper, et sur un
cas qui ne la concerne pas. La dernière classe vérifie l'inverse de tout le
reste : les sept ICPs gelés de SPEC-008 ne déclarent aucun métier, et ne voient
donc rien changer.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from signals.domain import ContractAward, EventRef, Evidence, Location, Provenance, PublicEvent
from signals.domain.values import CpvCode
from signals.matching import (
    CONSTRUCTION_INPUTS_ICP,
    REFERENCE_ICPS,
    MatchingEngine,
    TargetICP,
    Territory,
    ValueThreshold,
)
from signals.needs import NeedGraphEngine
from signals.understanding import ContractUnderstandingEngine
from signals.understanding.cpv import trade_domain_for_cpv
from signals.understanding.model import (
    Claim,
    ContractGeography,
    ContractParties,
    ContractTiming,
    ContractUnderstanding,
)
from signals.understanding.object_text import describes_object, published_object

AS_OF = dt.date(2026, 8, 20)

_EV = Evidence(
    source_system="simap",
    source_kind="publication_field",
    source_notice_id="28066-04",
    path="award.value",
    excerpt="valeur publiée",
)


def _claim(value: str) -> Claim:
    return Claim(
        value=value, confidence="high", kind="source_fact", rule="valeur publiée", evidence=(_EV,)
    )


def _cu(
    *,
    cpv: str = "45210000",
    trade_domain: str | None = "general_building",
    published_object_text: str | None = "BKP 213 Montagenbau in Stahl",
) -> ContractUnderstanding:
    facts = {
        "winner": _claim("Entreprise Alpha SA"),
        "cpv": _claim(cpv),
        "amount": _claim("2400000.00 CHF"),
    }
    if published_object_text:
        facts["published_object"] = _claim(published_object_text)
    return ContractUnderstanding(
        award_ref=EventRef(source_system="simap", source_notice_id="28066-04"),
        source_system="simap",
        contract_type=_claim("construction"),
        sector=_claim("unknown"),
        trade_domain=_claim(trade_domain) if trade_domain else None,
        object_summary=_claim("Marché « Travaux »"),
        facts=facts,
        parties=ContractParties(),
        geography=ContractGeography(
            place_of_performance=Location(country="CH"), buyer_country="CH"
        ),
        timing=ContractTiming(published_at=dt.date(2026, 8, 1)),
        evidence_coverage=1.0,
        engine_version="contract-understanding-v0.2",
    )


def _icp(**overrides) -> TargetICP:
    data = {
        "icp_id": "icp-inputs-test",
        "name": "Négoce d'intrants — test",
        "primary_need_categories": ("materials_or_components",),
        "primary_trade_domains": ("general_building", "interior_finishing"),
        "secondary_trade_domains": ("roadworks_civil",),
        "geography_basis": "place_of_performance",
        "geography_policy": "required",
        "territories": (Territory(country="CH"),),
        "value_thresholds": (ValueThreshold(currency="CHF", minimum_amount=100_000),),
        "maximum_signal_age_days": 120,
    }
    data.update(overrides)
    return TargetICP(**data)


def _match(cu: ContractUnderstanding, icp: TargetICP):
    return MatchingEngine().match(cu, NeedGraphEngine().derive(cu), icp, as_of=AS_OF)


def _trade_filter(cu: ContractUnderstanding, icp: TargetICP):
    return next(f for f in _match(cu, icp).hard_filter_results if f.name == "trade_domain")


# ─── Correction 1 : granularité du corps de métier ──────────────────────────────


class TestTradeDomainFromCpv:
    """§11-§12 — le métier vient du CPV, et de rien d'autre."""

    def test_the_domains_that_caused_the_observed_failures_are_separated(self) -> None:
        """Les six signaux faibles de granularité, par leur CPV réel."""
        assert trade_domain_for_cpv("45234160") == "rail_infrastructure"  # caténaire tram
        assert trade_domain_for_cpv("45316110") == "technical_installation"  # éclairage public
        assert trade_domain_for_cpv("45331210") == "technical_installation"  # ventilation
        assert trade_domain_for_cpv("45240000") == "special_civil"  # fonçage sous autoroute
        assert trade_domain_for_cpv("45233220") == "roadworks_civil"  # chaussée
        assert trade_domain_for_cpv("45233142") == "roadworks_civil"

    def test_the_domains_that_must_stay_in_the_wedge_are_kept(self) -> None:
        """Négatif : les CPV des signaux utiles ne doivent PAS basculer ailleurs."""
        assert trade_domain_for_cpv("45210000") == "general_building"
        assert trade_domain_for_cpv("45212000") == "general_building"
        assert trade_domain_for_cpv("45262000") == "general_building"  # travaux spéciaux
        assert trade_domain_for_cpv("45420000") == "interior_finishing"
        assert trade_domain_for_cpv("45112000") == "earthworks_demolition"

    def test_the_longest_prefix_wins_so_rail_escapes_roadworks(self) -> None:
        """`45234` doit battre `4523` : c'est toute la correction sur la caténaire."""
        assert trade_domain_for_cpv("45234000") == "rail_infrastructure"
        assert trade_domain_for_cpv("45231000") == "roadworks_civil"

    def test_a_contract_outside_construction_gets_no_trade_domain(self) -> None:
        """Cas non concerné : demander le métier d'un marché de fournitures."""
        assert trade_domain_for_cpv("33600000") == "unknown_or_general"
        assert trade_domain_for_cpv("72000000") == "unknown_or_general"
        assert trade_domain_for_cpv(None) == "unknown_or_general"

    def test_a_generic_construction_code_admits_it_knows_nothing(self) -> None:
        """`45000000` annonce des travaux sans annoncer lesquels (§13)."""
        assert trade_domain_for_cpv("45000000") == "unknown_or_general"


class TestTradeDomainGate:
    """§17-§18 — une porte, jamais des points."""

    def test_a_targeted_trade_can_reach_the_feed(self) -> None:
        assert _match(_cu(trade_domain="general_building"), _icp()).decision == "show"

    def test_a_secondary_trade_falls_back_to_borderline(self) -> None:
        """Le routier achète parfois au négoce : pertinent, pas prioritaire."""
        result = _match(_cu(trade_domain="roadworks_civil"), _icp())
        assert result.decision == "borderline"
        assert result.band != "strong"

    def test_an_unknown_trade_is_never_a_positive_match(self) -> None:
        """§13 — un CPV muet ne prouve aucune compatibilité."""
        result = _match(_cu(cpv="45000000", trade_domain=None), _icp())
        assert result.decision != "show"

    def test_an_incompatible_trade_is_excluded_not_insufficient(self) -> None:
        """La donnée ne manque pas : elle dit non."""
        result = _match(_cu(trade_domain="technical_installation"), _icp())
        assert result.decision == "exclude"
        assert _trade_filter(_cu(trade_domain="technical_installation"), _icp()).evaluable

    def test_an_icp_without_declared_trades_keeps_its_previous_behaviour(self) -> None:
        """Cas non concerné — c'est la garantie de non-régression (§43)."""
        neutral = _icp(primary_trade_domains=(), secondary_trade_domains=())
        for domain in ("technical_installation", "rail_infrastructure", "general_building"):
            result = _match(_cu(trade_domain=domain), neutral)
            assert _trade_filter(_cu(trade_domain=domain), neutral).passed
            assert result.decision == "show"

    def test_the_decision_says_why_the_trade_held_it_back(self) -> None:
        result = _match(_cu(trade_domain="roadworks_civil"), _icp())
        assert any("canal d'achat" in limitation for limitation in result.limitations)


class TestTradeTargetingDeclaration:
    """§13-§14 — ce qu'un ICP a le droit de déclarer."""

    def test_targeting_the_unknown_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="unknown_or_general"):
            _icp(primary_trade_domains=("unknown_or_general",))

    def test_a_trade_cannot_be_primary_and_secondary_at_once(self) -> None:
        with pytest.raises(ValidationError, match="primaires et secondaires"):
            _icp(
                primary_trade_domains=("general_building",),
                secondary_trade_domains=("general_building",),
            )

    def test_a_secondary_trade_without_a_primary_one_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="sans métier primaire"):
            _icp(primary_trade_domains=(), secondary_trade_domains=("roadworks_civil",))

    def test_the_wedge_icp_targets_what_a_builders_merchant_delivers(self) -> None:
        """§15-§16 — et n'y met ni l'installation technique ni le ferroviaire."""
        icp = CONSTRUCTION_INPUTS_ICP
        assert icp.icp_id == "icp-construction-inputs-ch-eu-v0"
        assert set(icp.primary_trade_domains) == {
            "general_building",
            "interior_finishing",
            "earthworks_demolition",
        }
        declared = set(icp.primary_trade_domains) | set(icp.secondary_trade_domains)
        assert not declared & {"technical_installation", "rail_infrastructure", "equipment_hire"}


# ─── Correction 2 : le besoin nomme son sujet ───────────────────────────────────


class TestNeedSubject:
    """§19-§25 — une hypothèse qui ne nomme pas son sujet est incontestable."""

    def test_a_need_names_the_published_object_it_concerns(self) -> None:
        needs = NeedGraphEngine().derive(_cu()).needs
        assert needs
        for need in needs:
            assert need.subject is not None
            assert "BKP 213 Montagenbau in Stahl" in need.subject

    def test_the_reasoning_stays_hypothetical_about_that_subject(self) -> None:
        """§21 — la justification est révocable par l'objet qu'elle nomme."""
        need = NeedGraphEngine().derive(_cu()).needs[0]
        assert "si" in need.reasoning.lower()
        assert "ne tient pas" in need.reasoning

    def test_the_observed_failure_no_longer_asserts_earthworks_on_a_doors_lot(self) -> None:
        """Le reproche exact de SPEC-009B sur `0cffdfe9e5`."""
        cu = _cu(cpv="45210000", published_object_text="BKP 272.0 Innentüren aus Metall")
        for need in NeedGraphEngine().derive(cu).needs:
            assert "relèvent du terrassement" not in need.reasoning
            assert "Innentüren aus Metall" in (need.subject or "")

    def test_a_subject_is_one_line_even_when_the_notice_lists_items(self) -> None:
        """Négatif : un métré multiligne ne doit pas casser la phrase."""
        cu = _cu(published_object_text="Verglasungen: 24 Stk.\n- Holzzarge: 497 Stk.")
        subject = NeedGraphEngine().derive(cu).needs[0].subject
        assert subject is not None and "\n" not in subject

    def test_a_need_without_any_published_object_says_so(self) -> None:
        """Cas non concerné : l'avis ne publie rien d'exploitable."""
        cu = _cu(published_object_text=None)
        need = NeedGraphEngine().derive(cu).needs[0]
        assert need.subject is None
        assert "aucun objet exploitable" in need.reasoning

    def test_an_unknown_trade_is_not_pasted_next_to_the_subject(self) -> None:
        cu = _cu(cpv="45000000", trade_domain=None)
        assert "unknown_or_general" not in (NeedGraphEngine().derive(cu).needs[0].subject or "")


# ─── Correction 3 : un objet publié qui ne décrit rien ──────────────────────────


class TestPublishedObjectIsInformative:
    """§26-§31 — la couche fautive était la compréhension de contrat."""

    def test_the_observed_form_heading_is_not_an_object(self) -> None:
        assert describes_object("WEGLEITUNG INHALT UND ECKDATEN") is False

    def test_document_referrals_are_not_objects(self) -> None:
        for referral in (
            "Siehe Ausschreibungsunterlagen",
            "Zie bestek",
            "Lo indicado en los pliegos",
            "Conform Caiet de sarcini",
            "Se upphandlingsdokumentet",
        ):
            assert describes_object(referral) is False, referral

    def test_a_referral_trailing_a_reference_code_is_still_a_referral(self) -> None:
        assert describes_object("Se référer au cahier des charges C02C1.") is False

    def test_a_referral_followed_by_a_real_object_is_kept(self) -> None:
        """Négatif — la règle ne s'applique jamais en sous-chaîne."""
        assert describes_object("Voir cahier des charges : fourniture de 300 fenêtres bois")

    def test_bare_lot_numbers_are_not_objects(self) -> None:
        for placeholder in ("Default lot", "Lote 1", "Lot 3", "Pakiet Nr 1", "1", "Reihen"):
            assert describes_object(placeholder) is False, placeholder

    def test_short_real_objects_survive(self) -> None:
        """Négatif — la forme typographique ne décide rien (mesuré sur 800 lots)."""
        for real in (
            "Façades",
            "Echafaudages",
            "BOISSONS ET SIROPS",
            "EPICES ET SELS",
            "BKP 213 Montagenbau in Stahl",
            "Środki przeciwnowotworowe",
        ):
            assert describes_object(real) is True, real

    def test_an_ordinary_long_description_is_untouched(self) -> None:
        """Cas non concerné."""
        assert describes_object(
            "Gegenstand und Umfang dieser Ausschreibung sind Maler- und Gipserarbeiten "
            "im Rahmen der Dach- und Fassadensanierung."
        )


class TestPublishedObjectHierarchy:
    """§31 — quel champ établit l'objet, et lequel prend la main."""

    def test_the_lot_description_wins_because_it_carries_the_trade(self) -> None:
        text, field = published_object("Umbau Hallen- und Freibad Talegg", "BKP 213 Montagenbau")
        assert (text, field) == ("BKP 213 Montagenbau", "description")

    def test_the_title_takes_over_when_the_description_describes_nothing(self) -> None:
        """Le cas observé : titre informatif, description en gabarit."""
        text, field = published_object("BKP 230 Elektro", "WEGLEITUNG INHALT UND ECKDATEN")
        assert (text, field) == ("BKP 230 Elektro", "title")

    def test_nothing_is_established_when_neither_field_describes(self) -> None:
        assert published_object("Pakiet Nr 1", "Zie bestek") == (None, "none")

    def test_the_engine_keeps_the_boilerplate_out_of_the_object_summary(self) -> None:
        """Le cas tracé de bout en bout, sur l'award-lot réel du pool.

        La source publie bien « WEGLEITUNG INHALT UND ECKDATEN » dans
        `procurement.orderDescription` : le connecteur est fidèle, c'est la
        composition du résumé qui devait cesser de la reprendre.
        """
        award = ContractAward(
            event_ref=EventRef(source_system="simap", source_notice_id="0f0c7288"),
            title="BKP 230 Elektro",
            description="<p>WEGLEITUNG INHALT UND ECKDATEN</p>",
            cpv_main=CpvCode(code="45000000"),
            winner_status="undisclosed",
        )
        event = PublicEvent(
            provenance=Provenance(
                source_system="simap",
                source_notice_id="0f0c7288",
                source_country="CH",
                source_url="https://www.simap.ch/0f0c7288",
                retrieved_at=dt.datetime(2026, 8, 17, tzinfo=dt.UTC),
            ),
            published_at=dt.date(2026, 3, 23),
            event_type="award_notice",
        )
        understanding = ContractUnderstandingEngine().understand(award, event)
        assert "WEGLEITUNG" not in understanding.object_summary.value.upper()
        assert understanding.facts["published_object"].value == "BKP 230 Elektro"


# ─── Non-régression : ce que la correction ne touche pas (§43) ──────────────────


class TestFrozenIcpsAreUnaffected:
    def test_no_reference_icp_declares_a_trade_domain(self) -> None:
        """Les sept ICPs de SPEC-008 traversent la correction sans changer."""
        for icp in REFERENCE_ICPS:
            assert icp.primary_trade_domains == ()
            assert icp.secondary_trade_domains == ()

    def test_the_wedge_icp_lives_outside_the_frozen_library(self) -> None:
        """Ajouter un huitième profil rendrait le banc SPEC-008 incomparable."""
        assert CONSTRUCTION_INPUTS_ICP.icp_id not in {icp.icp_id for icp in REFERENCE_ICPS}
