"""Le résultat d'une résolution : un statut, une trace, et parfois une entreprise.

Un score seul ne dit rien d'exploitable. Ce qui compte, c'est **la catégorie**
(peut-on s'en servir ?) et **la raison** (pourquoi ?). Le score, quand il existe,
est un classement de candidats, jamais un critère de décision.

Règle structurelle : aucune `Company` n'est attachée sans au moins une preuve.
Le modèle refuse une résolution qui affirmerait une identité sans dire pourquoi.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from signals.domain import Company, OrganizationRef, SourceSystem
from signals.domain.values import CanonicalModel, NonEmptyStr

ResolutionStatus = Literal[
    "verified",
    "probable",
    "review_required",
    "unresolved",
    "conflict",
    "registry_unavailable",
]
"""Ce qu'on peut faire du résultat.

- `verified` : identité soutenue par un identifiant officiel ou un registre ;
- `probable` : correspondance très forte, sans preuve d'identité juridique ;
- `review_required` : plusieurs candidats crédibles — un humain doit trancher ;
- `unresolved` : trop peu d'information publiée pour conclure ;
- `conflict` : preuves incompatibles entre elles ;
- `registry_unavailable` : le registre n'a pas répondu. **Ce n'est pas un
  résultat négatif** : ne pas avoir pu vérifier n'est pas avoir vérifié que non.
"""

RESOLVED_STATUSES = ("verified", "probable")

MatchMethod = Literal[
    "official_identifier",
    "source_local_identifier",
    "unattributed_identifier",
    "registry_lookup",
    "name_and_address",
    "fuzzy_name",
]


class ResolutionBasis(CanonicalModel):
    """Une raison, pour ou contre. Toute décision automatique en porte au moins une.

    Ce n'est pas encore `Evidence` (SPEC-005) : pas d'ancrage dans un document,
    pas de passage cité. Juste de quoi rejouer le raisonnement.
    """

    method: MatchMethod
    detail: NonEmptyStr
    # `False` = preuve CONTRAIRE. Un conflit se lit dans la trace, il ne se
    # déduit pas d'un statut.
    supports: bool = True

    def __str__(self) -> str:
        return f"{'+' if self.supports else '−'} {self.method}: {self.detail}"


class CompanyCandidate(CanonicalModel):
    """Une entreprise envisagée, avec ce qui la soutient et son rang."""

    company: Company
    basis: tuple[ResolutionBasis, ...] = Field(min_length=1)
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class CompanyResolution(CanonicalModel):
    """Ce que le resolver a établi — à côté de la mention, jamais à sa place.

    `source_organization` est le fait publié, recopié tel quel. Il reste lisible
    même quand la résolution échoue, et surtout : il n'est pas modifié quand
    elle réussit.
    """

    source_organization: OrganizationRef
    source_system: SourceSystem
    status: ResolutionStatus
    company: Company | None = None
    # Classement, pas décision. Voir `resolver` : aucun seuil numérique ne
    # promeut à lui seul un statut.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    basis: tuple[ResolutionBasis, ...] = ()
    candidates: tuple[CompanyCandidate, ...] = ()

    @model_validator(mode="after")
    def _coherence(self) -> CompanyResolution:
        if self.status in RESOLVED_STATUSES:
            if self.company is None:
                raise ValueError(f"statut '{self.status}' sans entreprise résolue")
            if not self.basis:
                raise ValueError(
                    f"statut '{self.status}' sans trace : aucune résolution automatique "
                    "ne peut être inexplicable"
                )
        elif self.company is not None:
            raise ValueError(
                f"statut '{self.status}' ne doit porter aucune entreprise : "
                "une identité incertaine n'est pas une identité"
            )
        return self

    @property
    def is_resolved(self) -> bool:
        return self.status in RESOLVED_STATUSES

    @property
    def needs_human(self) -> bool:
        """Les cas qu'un opérateur doit regarder — jamais exploités tels quels."""
        return self.status in ("review_required", "conflict")


class PartyResolution(CanonicalModel):
    """Un soumissionnaire retenu, résolu MEMBRE PAR MEMBRE.

    Un groupement n'est pas une entreprise : ses membres le sont. Le nom du
    groupement est conservé s'il a été publié, mais il ne devient une `Company`
    que si la source publie pour lui une entité juridique propre — ce qui n'a
    pas été observé.
    """

    party_name: NonEmptyStr | None = None
    members: tuple[CompanyResolution, ...] = Field(min_length=1)
