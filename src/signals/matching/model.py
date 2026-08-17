"""Le résultat du matching — un score qui s'explique, une confiance à côté.

SPEC-008 §20-§29. Trois séparations structurelles :

    BESOIN PLAUSIBLE  ≠  FIT AVEC LE CLIENT  ≠  OPPORTUNITÉ CERTAINE

- la **décision** (`show` / `borderline` / `exclude` / `insufficient_data`) est
  distincte du **score** : un filtre dur échoué n'est jamais compensé ;
- le **score** mesure la pertinence relative pour cet ICP, jamais une
  probabilité d'achat ;
- la **confiance** est une dimension séparée, plafonnée à `medium` tant que les
  besoins viennent du mode `metadata_fallback` — elle n'est jamais fondue dans
  le score, sous peine d'en devenir un simple décalage (§24, §26).

Un score sans explication est un modèle invalide : `positive_reasons`,
`score_components`, `hard_filter_results` et `evidence_refs` sont obligatoires
dès qu'un signal est montré.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from signals.domain import EventRef, Evidence
from signals.domain.values import CanonicalModel, NonEmptyStr
from signals.needs import NeedCategory

SCORE_POLICY_VERSION = "signal-score-v0.2"
"""v0.2 (SPEC-008R §5) : la bande devient une lecture de la décision — `strong`
n'existe plus hors d'un `show`. Les scores, les poids, les seuils et les
décisions sont inchangés ; seule la sémantique publique de `ScoreBand` bouge."""

MatchDecision = Literal["show", "borderline", "exclude", "insufficient_data"]
"""`borderline` n'apparaît pas dans le feed principal du MVP : le besoin est
pertinent, mais un élément important manque ou le fit est secondaire.
`insufficient_data` conserve la raison exacte — il ne devient jamais `exclude`
par commodité (§20)."""

SignalConfidence = Literal["medium", "low"]
"""`high` n'existe pas : aucun besoin ne s'appuie aujourd'hui sur une exigence
documentaire validée (§26)."""

ScoreBand = Literal["strong", "promising", "weak", "excluded"]
"""Une bande lisible, qui accompagne la décision sans la remplacer (§27)."""


class HardFilterResult(CanonicalModel):
    """Un filtre dur et son verdict — passé, échoué, ou inévaluable."""

    name: NonEmptyStr
    passed: bool
    # `None` quand la règle n'a pas pu être évaluée faute de donnée : c'est ce
    # qui distingue `insufficient_data` d'un rejet de fond.
    evaluable: bool = True
    detail: NonEmptyStr


class SignalScoreComponent(CanonicalModel):
    """Une dimension notée, ses points, son plafond, et pourquoi."""

    name: NonEmptyStr
    points: int = Field(ge=0)
    maximum_points: int = Field(gt=0)
    detail: NonEmptyStr

    @model_validator(mode="after")
    def _un_composant_ne_depasse_pas_son_plafond(self) -> SignalScoreComponent:
        if self.points > self.maximum_points:
            raise ValueError(
                f"composant « {self.name} » : {self.points} points pour un plafond "
                f"de {self.maximum_points}"
            )
        return self


class ScoredSignalMatch(CanonicalModel):
    """Un award-lot confronté à un ICP — décision, score, explication, preuves.

    L'identité du résultat est le triplet (award, ICP, version de politique) :
    deux lots d'une même procédure restent deux résultats distincts (§5).
    """

    award_ref: EventRef
    icp_id: NonEmptyStr
    as_of: object

    decision: MatchDecision
    band: ScoreBand
    confidence: SignalConfidence

    raw_points: int = Field(ge=0)
    maximum_applicable_points: int = Field(ge=0)
    normalized_score: int = Field(ge=0, le=100)

    score_components: tuple[SignalScoreComponent, ...] = ()
    hard_filter_results: tuple[HardFilterResult, ...] = ()
    matched_needs: tuple[NeedCategory, ...] = ()
    positive_reasons: tuple[NonEmptyStr, ...] = ()
    limitations: tuple[NonEmptyStr, ...] = ()
    evidence_refs: tuple[Evidence, ...] = ()

    match_policy_version: NonEmptyStr
    score_policy_version: NonEmptyStr

    @model_validator(mode="after")
    def _un_score_se_justifie(self) -> ScoredSignalMatch:
        total = sum(component.points for component in self.score_components)
        if total != self.raw_points:
            raise ValueError(
                f"décomposition incohérente : {total} points cumulés pour "
                f"{self.raw_points} annoncés"
            )
        ceiling = sum(component.maximum_points for component in self.score_components)
        if ceiling != self.maximum_applicable_points:
            raise ValueError(
                f"maximum applicable incohérent : {ceiling} contre {self.maximum_applicable_points}"
            )
        expected = (
            round(100 * self.raw_points / self.maximum_applicable_points)
            if self.maximum_applicable_points
            else 0
        )
        if self.normalized_score != expected:
            raise ValueError(
                f"score normalisé {self.normalized_score} ≠ {expected} attendu depuis "
                f"{self.raw_points}/{self.maximum_applicable_points}"
            )
        if self.decision in ("show", "borderline"):
            if not self.positive_reasons:
                raise ValueError("un signal présenté sans raison positive n'est pas explicable")
            if not self.score_components:
                raise ValueError("un score sans composant n'est pas traçable")
            if not self.evidence_refs:
                raise ValueError("un signal présenté sans preuve des faits n'est pas vérifiable")
            if not self.matched_needs:
                raise ValueError("un signal présenté sans besoin correspondant n'a pas de sens")
        # §3 — la bande est une lecture de la décision, jamais une seconde
        # opinion. `strong` hors d'un `show` annoncerait comme fort ce que le
        # moteur a refusé de montrer.
        if self.decision == "show":
            if self.band not in ("strong", "promising"):
                raise ValueError(f"un signal montré ne porte pas la bande `{self.band}`")
        elif self.decision == "borderline":
            if self.band not in ("promising", "weak"):
                raise ValueError(
                    f"une décision « borderline » ne peut pas porter la bande "
                    f"`{self.band}` : seule `promising` ou `weak` la traduit"
                )
        elif self.band != "excluded":
            raise ValueError(
                f"un signal exclu ou inévaluable porte la bande `excluded`, pas `{self.band}`"
            )
        return self
