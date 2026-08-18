"""Combien d'opportunités la France produit-elle réellement par semaine ?

R1 avait répondu « 45 + 383 = 428 ». L'addition est fausse, et sa faute est
instructive : elle traite deux **registres** comme deux **marchés**. Le BOAMP
publie une décision d'attribution, DECP publie la notification du contrat qui
en découle. Quand les deux décrivent le même marché, cela fait une opportunité
commerciale, pas deux.

Ce module fait l'arithmétique honnête de ce constat. Il ne cherche pas à
produire un chiffre unique : quand le rapprochement ne couvre pas toute la
population, il rend un **encadrement**, et rien entre les deux bornes.

    borne haute   on ne retire que les doublons DÉMONTRÉS
    borne basse   on suppose que tout ce qui n'a pas pu être testé fait doublon
    exact         seulement quand chaque candidat a pu être testé

Inventer un milieu entre les deux serait présenter une hypothèse comme une
mesure — exactement ce que R1 a fait, en plus discret.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class LinkageAggregate:
    """Le bilan complet d'une passe de rapprochement BOAMP → DECP (R2 §4).

    `boamp_linkable` est le nombre d'award-lots qui portaient **les deux** SIRET
    nécessaires pour interroger DECP. Le reste n'a pas été testé, et cette
    distinction est le cœur de l'encadrement : un candidat non testable n'est
    pas un candidat non apparié.
    """

    boamp_candidates_tested: int
    boamp_linkable: int
    decp_candidates_returned: int
    strong: int
    probable: int
    unresolved: int
    conflicts: int
    decoys_rejected: int

    def __post_init__(self) -> None:
        outcomes = self.strong + self.probable + self.unresolved
        if outcomes != self.boamp_linkable:
            raise ValueError(
                f"somme des issues ({outcomes}) différente des candidats testables "
                f"({self.boamp_linkable}) : l'agrégat ne se referme pas"
            )
        if self.boamp_linkable > self.boamp_candidates_tested:
            raise ValueError("plus de candidats testables que de candidats testés")

    @property
    def boamp_not_linkable(self) -> int:
        """Ceux qu'on n'a pas pu tester — faute d'un SIRET acheteur ou titulaire."""
        return self.boamp_candidates_tested - self.boamp_linkable

    @property
    def strong_rate_over_linkable(self) -> float | None:
        if not self.boamp_linkable:
            return None
        return round(100 * self.strong / self.boamp_linkable, 1)

    @property
    def strong_rate_over_tested(self) -> float | None:
        if not self.boamp_candidates_tested:
            return None
        return round(100 * self.strong / self.boamp_candidates_tested, 1)


@dataclasses.dataclass(frozen=True)
class UniqueContractCount:
    """Le nombre de marchés distincts derrière deux flux d'événements."""

    raw_boamp: int
    raw_decp: int
    strong_overlap: int
    max_possible_overlap: int
    lower_bound: int
    upper_bound: int
    exact: int | None
    basis: str

    @property
    def raw_sum(self) -> int:
        """La somme naïve — conservée pour montrer ce qu'elle surestime."""
        return self.raw_boamp + self.raw_decp


def unique_contract_count(
    *, raw_boamp: int, raw_decp: int, linkage: LinkageAggregate
) -> UniqueContractCount:
    """Encadre le nombre de marchés distincts, sans jamais trancher au milieu.

    Le recouvrement démontré est le nombre de liens `strong`. Le recouvrement
    *possible* y ajoute les `probable` — non confirmés — et les candidats qu'on
    n'a pas pu tester du tout. Les deux sont plafonnés par la plus petite des
    deux populations : on ne peut pas apparier plus d'événements qu'il n'en
    existe du côté le moins fourni.
    """
    ceiling = min(raw_boamp, raw_decp)
    strong_overlap = min(linkage.strong, ceiling)
    max_possible = min(linkage.strong + linkage.probable + linkage.boamp_not_linkable, ceiling)
    total = raw_boamp + raw_decp
    lower = total - max_possible
    upper = total - strong_overlap

    complete = linkage.boamp_not_linkable == 0 and linkage.probable == 0
    return UniqueContractCount(
        raw_boamp=raw_boamp,
        raw_decp=raw_decp,
        strong_overlap=strong_overlap,
        max_possible_overlap=max_possible,
        lower_bound=lower,
        upper_bound=upper,
        exact=upper if complete else None,
        basis=(
            "rapprochement complet — chaque candidat a pu être testé"
            if complete
            else (
                f"rapprochement partiel — {linkage.boamp_not_linkable} candidats non "
                f"testables et {linkage.probable} liens seulement probables"
            )
        ),
    )


@dataclasses.dataclass(frozen=True)
class IdentityBreakdown:
    """Ce que Kivou peut réellement montrer d'une entreprise (R2 §5).

    Un SIRET n'est pas une identité client. Il identifie de façon stable, ce qui
    permet de dédupliquer et d'aller chercher un nom ailleurs — mais on ne
    présente pas un numéro à quatorze chiffres à un commercial. Les deux
    capacités sont donc comptées séparément, et seule la seconde compte comme
    « prête pour un client ».
    """

    n: int
    stable_identifier_available: int
    legal_name_available: int
    name_and_identifier_available: int
    name_recovered_via_link: int
    customer_ready: int
    internally_resolvable_only: int

    @property
    def customer_ready_pct(self) -> float | None:
        return round(100 * self.customer_ready / self.n, 1) if self.n else None

    @property
    def internally_resolvable_pct(self) -> float | None:
        return round(100 * self.internally_resolvable_only / self.n, 1) if self.n else None


def customer_ready_breakdown(
    *,
    named: int,
    identified: int,
    named_and_identified: int,
    name_recovered_via_link: int,
    total: int,
) -> IdentityBreakdown:
    """Sépare « identifiable » de « présentable ».

    `name_recovered_via_link` compte les événements dépourvus de nom publié dont
    un rapprochement fort avec l'autre registre a rendu le nom. Ils rejoignent
    les signaux présentables ; ceux qui restent ne portent qu'un numéro et
    demeurent des **candidats résolvables en interne**, jamais des signaux
    livrables.
    """
    unnamed = total - named
    if name_recovered_via_link > unnamed:
        raise ValueError(
            f"{name_recovered_via_link} noms récupérés pour seulement {unnamed} "
            "événements sans nom publié"
        )
    customer_ready = named + name_recovered_via_link
    return IdentityBreakdown(
        n=total,
        stable_identifier_available=identified,
        legal_name_available=named,
        name_and_identifier_available=named_and_identified,
        name_recovered_via_link=name_recovered_via_link,
        customer_ready=customer_ready,
        internally_resolvable_only=total - customer_ready,
    )
