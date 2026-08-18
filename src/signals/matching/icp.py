"""TargetICP — ce que le client déclare vouloir recevoir, et rien de plus.

SPEC-008. Le modèle est **déclaratif** : il ne devine pas l'offre du client à
partir d'un texte libre, il ne consulte aucun modèle de langue, et il n'accueille
aucun champ de l'Acquisition Engine.

    TARGET ICP / SIGNAL MATCHING  =  produit client Kivou
    SUPPLIER DISCOVERY / CONTACTS =  Acquisition Engine interne

Cette frontière est structurelle : `extra="forbid"` empêche qu'un champ de
campagne, de contact ou de mailbox entre ici, et un test d'architecture vérifie
qu'aucun module de `signals.matching` ne nomme un outil d'acquisition.

`offer_summary` existe pour l'interface future : il est **déclaratif et inerte**
— deux textes différents avec les mêmes champs structurés produisent exactement
le même résultat (§8).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from signals.domain.values import CanonicalModel, NonEmptyStr
from signals.needs import NeedCategory, NeedTiming, SourceMode
from signals.understanding.cpv import ContractType, Sector, TradeDomain

MATCH_POLICY_VERSION = "icp-match-v0.2"

GeographyBasis = Literal["place_of_performance", "winner_location", "either", "ignore"]
"""Quelle localisation compte pour cet ICP.

`winner_location` est **modélisable mais sans données** : sur les 100 award-lots
mesurés, aucun ne publie l'adresse du gagnant (§14). Un ICP qui le choisit
obtient `insufficient_data`, jamais un faux positif."""

GeographyPolicy = Literal["required", "preferred", "ignored"]
"""`required` : une géographie connue et compatible est obligatoire — absente,
le verdict est `insufficient_data`. `preferred` : une correspondance rapporte
des points, une absence n'en rapporte aucun. `ignored` : la dimension sort des
filtres **et** du dénominateur du score."""

UnknownValuePolicy = Literal["exclude", "allow_with_penalty", "allow_neutral"]

MAX_SIGNAL_AGE_DAYS = 730
"""Deux ans : au-delà, un avis d'attribution n'est plus un signal commercial."""


class Territory(CanonicalModel):
    """Un territoire ciblé — pays, et subdivision seulement si son schéma est dit.

    Aucun géocodage, aucune latitude, aucun rayon : la comparaison est une
    égalité de codes. Sur le corpus mesuré, **aucun** lieu d'exécution ne publie
    de subdivision : le champ existe pour les sources qui le feront, il ne
    fabrique jamais de correspondance.
    """

    country: NonEmptyStr
    subdivision_code: NonEmptyStr | None = None
    subdivision_scheme: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _une_subdivision_nomme_son_schema(self) -> Territory:
        if self.subdivision_code and not self.subdivision_scheme:
            raise ValueError(
                f"subdivision « {self.subdivision_code} » sans schéma : deux codes de "
                "schémas différents ne se comparent pas"
            )
        return self


class ValueThreshold(CanonicalModel):
    """Un seuil monétaire, dans UNE devise. Aucune conversion n'est autorisée."""

    currency: NonEmptyStr
    minimum_amount: float = Field(ge=0)
    maximum_amount: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _un_minimum_ne_depasse_pas_son_maximum(self) -> ValueThreshold:
        if self.maximum_amount is not None and self.minimum_amount > self.maximum_amount:
            raise ValueError(
                f"seuil {self.currency} : minimum {self.minimum_amount} au-dessus du "
                f"maximum {self.maximum_amount}"
            )
        return self


class TargetICP(CanonicalModel):
    """Le profil de signal que le client demande — explicite, jamais deviné."""

    icp_id: NonEmptyStr
    name: NonEmptyStr
    # Déclaratif, destiné à l'interface. N'entre JAMAIS dans le calcul (§8).
    offer_summary: str = ""

    primary_need_categories: tuple[NeedCategory, ...]
    secondary_need_categories: tuple[NeedCategory, ...] = ()

    geography_basis: GeographyBasis
    geography_policy: GeographyPolicy
    territories: tuple[Territory, ...] = ()

    # WEDGE-HARDENING R1 §14 — le corps de métier ciblé, quand le client en a un.
    # Laissés vides, ces champs n'introduisent AUCUNE règle : un ICP qui ne
    # déclare pas de métier se comporte exactement comme avant. C'est ce qui
    # permet aux sept ICPs de référence gelés de traverser cette correction sans
    # changer d'un signal.
    primary_trade_domains: tuple[TradeDomain, ...] = ()
    secondary_trade_domains: tuple[TradeDomain, ...] = ()

    included_contract_types: tuple[ContractType, ...] = ()
    excluded_contract_types: tuple[ContractType, ...] = ()
    included_sectors: tuple[Sector, ...] = ()
    excluded_sectors: tuple[Sector, ...] = ()

    value_thresholds: tuple[ValueThreshold, ...] = ()
    unknown_value_policy: UnknownValuePolicy = "allow_neutral"

    maximum_signal_age_days: int = Field(gt=0, le=MAX_SIGNAL_AGE_DAYS)
    preferred_timings: tuple[NeedTiming, ...] = ()
    source_modes_allowed: tuple[SourceMode, ...] = ("metadata_fallback",)

    @model_validator(mode="after")
    def _un_profil_coherent(self) -> TargetICP:
        if not self.primary_need_categories:
            raise ValueError(
                "un ICP sans catégorie primaire ne décrit aucune offre : le matching "
                "exige au moins un besoin correspondant exactement"
            )
        overlap = set(self.primary_need_categories) & set(self.secondary_need_categories)
        if overlap:
            raise ValueError(f"catégories à la fois primaires et secondaires : {sorted(overlap)}")
        trades = set(self.primary_trade_domains) & set(self.secondary_trade_domains)
        if trades:
            raise ValueError(
                f"corps de métier à la fois primaires et secondaires : {sorted(trades)}"
            )
        # §13 — `unknown_or_general` n'est pas un métier, c'est son absence. Le
        # déclarer cible reviendrait à demander les marchés dont on ne sait rien.
        declared = set(self.primary_trade_domains) | set(self.secondary_trade_domains)
        if "unknown_or_general" in declared:
            raise ValueError(
                "« unknown_or_general » ne se cible pas : un CPV muet sur le métier "
                "ne peut pas être une correspondance positive"
            )
        if self.secondary_trade_domains and not self.primary_trade_domains:
            raise ValueError(
                "corps de métier secondaires sans métier primaire : l'ICP dirait ce "
                "qu'il accepte à regret sans dire ce qu'il vise"
            )
        types = set(self.included_contract_types) & set(self.excluded_contract_types)
        if types:
            raise ValueError(f"types de contrat à la fois inclus et exclus : {sorted(types)}")
        sectors = set(self.included_sectors) & set(self.excluded_sectors)
        if sectors:
            raise ValueError(f"secteurs à la fois inclus et exclus : {sorted(sectors)}")
        # §2 — `ignore` et `ignored` vont ensemble ou pas du tout. Nommer une
        # base qu'on annonce ignorer, ou exiger une géographie qu'on a déclaré
        # ne pas regarder, décrit une intention que le moteur ne peut pas servir.
        ignoring_basis = self.geography_basis == "ignore"
        ignoring_policy = self.geography_policy == "ignored"
        if ignoring_basis != ignoring_policy:
            raise ValueError(
                f"géographie contradictoire : basis « {self.geography_basis} » avec "
                f"policy « {self.geography_policy} » — `ignore` et `ignored` se "
                "déclarent ensemble ou pas du tout"
            )
        if not ignoring_policy and not self.territories:
            raise ValueError(
                f"géographie « {self.geography_policy} » sans territoire : la règle "
                "serait inévaluable, et une préférence vide n'exprime aucune préférence"
            )
        currencies = [threshold.currency for threshold in self.value_thresholds]
        if len(currencies) != len(set(currencies)):
            raise ValueError(
                "deux seuils pour une même devise : aucune conversion n'étant "
                "autorisée, la règle serait ambiguë"
            )
        if not self.source_modes_allowed:
            raise ValueError("un ICP doit accepter au moins un mode de production")
        return self

    def threshold_for(self, currency: str) -> ValueThreshold | None:
        """Le seuil de CETTE devise, ou rien — jamais celui d'une autre."""
        for threshold in self.value_thresholds:
            if threshold.currency == currency:
                return threshold
        return None
