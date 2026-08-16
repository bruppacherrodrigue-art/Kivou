"""L'entité entreprise — le résultat d'une résolution, jamais une mention source.

`OrganizationRef` est ce qu'un avis **imprime**. `Company` est ce qu'on a réussi
à **établir**. Les deux coexistent : la résolution n'écrase jamais le fait
publié, et une erreur du resolver ne peut donc pas détruire la donnée publique.

    OrganizationRef  (fait source, immuable)
            │
            ▼
      résolution ──▶ Company  (entité juridique suffisamment établie)

Une mention ambiguë ne devient pas une `Company` : elle reste une mention. Le
statut de la résolution le dit, et c'est lui qui porte l'incertitude — pas cet
objet, qui n'existe que lorsqu'une identité a été établie.
"""

from __future__ import annotations

from pydantic import model_validator

from signals.domain.values import (
    CanonicalModel,
    CountryCode,
    NonEmptyStr,
    OrganizationIdentifier,
    OrganizationRef,
)


class Company(CanonicalModel):
    """Une entité juridique établie, avec les mentions qui l'ont désignée.

    Les champs reprennent la forme d'`OrganizationRef` — même vocabulaire, même
    `OrganizationIdentifier` — parce qu'une entreprise établie et une entreprise
    mentionnée décrivent la même réalité à deux niveaux de certitude. La
    différence tient aux `aliases` : la trace des mentions réellement observées.
    """

    legal_name: NonEmptyStr
    identifiers: tuple[OrganizationIdentifier, ...] = ()
    country: CountryCode | None = None
    address: NonEmptyStr | None = None
    # Uniquement des mentions RÉELLEMENT observées dans des avis. Jamais une
    # variante générée : un alias inventé serait un faux fait.
    aliases: tuple[NonEmptyStr, ...] = ()
    # Réservé. La recherche de site web appartient à l'Acquisition Engine ;
    # `None` est ici la valeur normale, pas une lacune.
    website: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _alias_distinct_du_nom(self) -> Company:
        if self.legal_name in self.aliases:
            raise ValueError("la raison sociale ne se répète pas dans les alias")
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("alias dupliqué")
        return self

    def identifier(self, scheme: str) -> str | None:
        for candidate in self.identifiers:
            if candidate.scheme == scheme:
                return candidate.value
        return None

    def with_alias(self, mention: OrganizationRef) -> Company:
        """Ajoute la mention observée aux alias, si elle diffère du nom retenu."""
        if mention.legal_name == self.legal_name or mention.legal_name in self.aliases:
            return self
        return self.model_copy(update={"aliases": (*self.aliases, mention.legal_name)})
