"""SPEC-008R §2-§4 — deux invariants de cohérence, géographique et présentationnel.

Deux configurations pouvaient jusqu'ici mentir sans que rien ne l'attrape :

- un ICP déclarant `geography_basis="ignore"` avec une politique active, ou une
  politique active sans aucun territoire — deux façons de demander une géographie
  qu'on ne peut pas évaluer ;
- une sortie affichant la bande `strong` alors que la décision n'est pas `show`,
  ce qui présente comme un signal fort ce que le moteur a refusé de montrer.

Les deux sont désormais refusées **à la construction**, donc impossibles à
produire aussi bien par le moteur que par un appelant.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from test_matching_engine import AS_OF, _cu, _icp, _match

from signals.domain import EventRef, Evidence
from signals.matching import (
    MATCH_POLICY_VERSION,
    SCORE_POLICY_VERSION,
    ScoredSignalMatch,
    SignalScoreComponent,
    Territory,
)
from signals.matching.engine import PROMISING_BAND, STRONG_BAND

# ─── §2 — invariants géographiques ────────────────────────────────────────


class TestGeographyInvariants:
    """`basis == ignore` si et seulement si `policy == ignored` (§2)."""

    def test_ignore_basis_with_ignored_policy_is_valid(self) -> None:
        """Le seul mariage cohérent : on ignore la géographie des deux côtés."""
        icp = _icp(geography_basis="ignore", geography_policy="ignored", territories=())
        assert icp.geography_basis == "ignore"
        assert icp.geography_policy == "ignored"

    def test_ignore_basis_with_required_policy_is_refused(self) -> None:
        """Exiger une géographie tout en déclarant n'en regarder aucune."""
        with pytest.raises(ValidationError, match="ignore"):
            _icp(
                geography_basis="ignore",
                geography_policy="required",
                territories=(Territory(country="CH"),),
            )

    def test_ignore_basis_with_preferred_policy_is_refused(self) -> None:
        """Préférer une géographie qu'on a déclaré ne pas regarder."""
        with pytest.raises(ValidationError, match="ignore"):
            _icp(
                geography_basis="ignore",
                geography_policy="preferred",
                territories=(Territory(country="CH"),),
            )

    @pytest.mark.parametrize("basis", ["place_of_performance", "winner_location", "either"])
    def test_active_basis_with_ignored_policy_is_refused(self, basis: str) -> None:
        """Nommer une base de localisation puis annoncer qu'on l'ignore."""
        with pytest.raises(ValidationError, match="ignore"):
            _icp(geography_basis=basis, geography_policy="ignored", territories=())

    def test_required_policy_without_territories_is_refused(self) -> None:
        """Une géographie requise sans territoire ne peut jamais être satisfaite."""
        with pytest.raises(ValidationError, match="territoire"):
            _icp(geography_policy="required", territories=())

    def test_preferred_policy_without_territories_is_refused(self) -> None:
        """Une préférence sans territoire est une configuration vide (§2)."""
        with pytest.raises(ValidationError, match="territoire"):
            _icp(geography_policy="preferred", territories=())


# ─── §3 — cohérence décision / bande ──────────────────────────────────────


def _component(**overrides) -> SignalScoreComponent:
    data = {
        "name": "need_offer_fit",
        "points": 45,
        "maximum_points": 45,
        "detail": "besoin primaire correspondant",
    }
    data.update(overrides)
    return SignalScoreComponent(**data)


def _scored(**overrides) -> ScoredSignalMatch:
    """Un résultat cohérent par défaut, que chaque test dégrade sur un point."""
    data = {
        "award_ref": EventRef(source_system="simap", source_notice_id="28066-04"),
        "icp_id": "icp-rental-ch",
        "as_of": AS_OF,
        "decision": "show",
        "band": "strong",
        "confidence": "medium",
        "raw_points": 45,
        "maximum_applicable_points": 45,
        "normalized_score": 100,
        "score_components": (_component(),),
        "hard_filter_results": (),
        "matched_needs": ("equipment_or_rental",),
        "positive_reasons": ("besoin primaire correspondant",),
        "limitations": (),
        "evidence_refs": (
            Evidence(
                source_system="simap",
                source_kind="publication_field",
                source_notice_id="28066-04",
                path="award.value",
                excerpt="valeur publiée",
            ),
        ),
        "match_policy_version": MATCH_POLICY_VERSION,
        "score_policy_version": SCORE_POLICY_VERSION,
    }
    data.update(overrides)
    return ScoredSignalMatch(**data)


class TestDecisionBandCoherence:
    """Aucune bande `strong` ne survit hors d'une décision `show` (§3)."""

    def test_a_borderline_signal_is_never_strong(self) -> None:
        """La bande annoncerait un signal fort que la décision a refusé."""
        with pytest.raises(ValidationError, match="strong"):
            _scored(decision="borderline", band="strong")

    def test_an_excluded_signal_carries_the_excluded_band(self) -> None:
        with pytest.raises(ValidationError, match="exclu"):
            _scored(decision="exclude", band="weak", positive_reasons=(), evidence_refs=())

    def test_insufficient_data_carries_the_excluded_band(self) -> None:
        """Une donnée manquante n'est pas un signal faible : elle n'est pas notée."""
        with pytest.raises(ValidationError, match="exclu"):
            _scored(
                decision="insufficient_data",
                band="weak",
                positive_reasons=(),
                evidence_refs=(),
            )

    def test_a_shown_signal_may_be_strong(self) -> None:
        assert _scored(decision="show", band="strong").band == "strong"

    def test_a_shown_signal_may_be_promising(self) -> None:
        assert _scored(decision="show", band="promising").band == "promising"

    def test_a_manually_contradictory_result_is_refused(self) -> None:
        """L'invariant vit dans le modèle : un appelant ne peut pas le contourner."""
        with pytest.raises(ValidationError):
            _scored(decision="insufficient_data", band="strong")


# ─── §4 — devise non couverte ─────────────────────────────────────────────


class TestUnsupportedCurrencyBand:
    def test_unsupported_currency_cannot_produce_a_strong_band(self) -> None:
        """§4 — score élevé, devise sans seuil : `borderline`, jamais `strong`.

        Le score, les points, le statut de devise, la décision et le filtre dur
        restent inchangés : seule la bande de présentation est corrigée.
        """
        result = _match(_cu(amount="2400000.00 EUR"), _icp())

        assert result.decision == "borderline"
        assert result.normalized_score >= STRONG_BAND, (
            "le cas perd son intérêt si le score ne franchit pas le seuil `strong`"
        )
        assert result.band != "strong"
        assert result.band in ("promising", "weak")

    def test_a_borderline_band_follows_the_promising_threshold(self) -> None:
        """En `borderline`, la bande se lit sur `PROMISING_BAND` (§3)."""
        result = _match(_cu(amount="2400000.00 EUR"), _icp())
        expected = "promising" if result.normalized_score >= PROMISING_BAND else "weak"
        assert result.band == expected
