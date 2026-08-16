"""Le contrat attribué.

Unité retenue : **un contrat attribué, pour un lot, à un attributaire ou à un
consortium**. Ni « une notice », ni « un lot ».

Ce choix vient des faits, pas de l'esthétique :

- une notice peut porter plusieurs lots (donc `1 notice = 1 contrat` est faux) ;
- un accord-cadre peut attribuer un même lot à plusieurs fournisseurs distincts
  (donc `1 lot = 1 contrat` est faux aussi) ;
- un consortium est UN attributaire composé de plusieurs organisations (donc
  `plusieurs organisations = plusieurs contrats` est faux également).

D'où : `PublicEvent` 1..N `ContractAward`, et `ContractAward` 1..N `Awardee`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Literal

from pydantic import model_validator

from signals.domain.events import EventRef, SourceSystem
from signals.domain.values import (
    CanonicalModel,
    CpvCode,
    Duration,
    Location,
    Money,
    NonEmptyStr,
    OrganizationRef,
)

AwardeeRole = Literal["sole", "consortium_lead", "consortium_member"]

WinnerStatus = Literal["identified", "ambiguous", "undisclosed"]
"""État de connaissance du gagnant — jamais une supposition.

- `identified` : l'avis nomme le ou les attributaires ;
- `ambiguous`  : l'avis nomme des candidats qu'on ne sait pas trancher (homonymie,
  mention tronquée, plusieurs entités possibles) → à vérifier avant exploitation ;
- `undisclosed`: l'avis ne publie pas d'attributaire (lot infructueux, mention
  absente) → aucun attributaire n'est inventé pour combler le vide.
"""


class Awardee(CanonicalModel):
    """Une organisation partie prenante de l'attribution, avec son rôle."""

    organization: OrganizationRef
    role: AwardeeRole = "sole"


class LotRef(CanonicalModel):
    """Le lot tel que la source le numérote.

    Pas d'entité `Lot` séparée : elle supposerait de connaître la liste complète
    des lots de la notice, information qu'un avis d'adjudication ne garantit pas.
    L'identifiant imprimé suffit à distinguer les lots entre eux.
    """

    identifier: NonEmptyStr
    title: NonEmptyStr | None = None


class SourceIdentity(CanonicalModel):
    """Ce que la SOURCE identifie elle-même — aucune valeur calculée, aucune déduction.

    C'est le seul objet du domaine qui pourra un jour porter une contrainte
    d'unicité en base, et seulement après qu'un connecteur réel ait démontré que
    le portail publie bien un identifiant de contrat stable dans le temps.
    Tant que cette preuve n'existe pas, rien ici n'autorise à conclure.

    À ne pas confondre avec `ContractAward.dedupe_fingerprint()`, qui est une
    heuristique et le restera.
    """

    source_system: SourceSystem
    source_notice_id: NonEmptyStr
    notice_version: NonEmptyStr | None = None
    lot_identifier: NonEmptyStr | None = None
    source_award_id: NonEmptyStr


def _normalise_name(name: str) -> str:
    """Normalisation minimale et déterministe, pour comparaison uniquement.

    Ce n'est PAS de la résolution d'entité : elle absorbe la casse et les espaces
    surnuméraires, rien de plus. Aucune suppression de forme juridique, aucun
    fuzzy — ce serait une inférence, et elle appartiendra à `Company`.
    """
    return " ".join(name.split()).casefold()


class ContractAward(CanonicalModel):
    """Un contrat attribué, rattaché à l'événement public qui l'a révélé.

    Tous les champs métier sont optionnels sauf le rattachement : un avis réel
    publie ce qu'il veut. Une donnée absente reste absente.
    """

    event_ref: EventRef

    # Identité — telle que publiée, jamais fabriquée
    source_award_id: NonEmptyStr | None = None
    lot: LotRef | None = None

    # Objet du contrat
    title: NonEmptyStr | None = None
    description: str | None = None
    cpv_main: CpvCode | None = None
    cpv_additional: tuple[CpvCode, ...] = ()

    # Argent
    value: Money | None = None

    # Parties
    buyer: OrganizationRef | None = None
    winner_status: WinnerStatus = "identified"
    awardees: tuple[Awardee, ...] = ()

    # Où
    place_of_performance: Location | None = None

    # Quand — trois horloges distinctes, jamais fusionnées
    award_date: dt.date | None = None
    contract_signature_date: dt.date | None = None
    contract_start_date: dt.date | None = None
    contract_end_date: dt.date | None = None
    duration: Duration | None = None

    @model_validator(mode="after")
    def _gagnants_coherents(self) -> ContractAward:
        if self.winner_status == "undisclosed":
            if self.awardees:
                raise ValueError("winner_status='undisclosed' n'admet aucun attributaire")
            return self
        if not self.awardees:
            raise ValueError(
                f"winner_status='{self.winner_status}' exige au moins un attributaire ; "
                "utiliser 'undisclosed' quand la source n'en publie pas"
            )
        if len(self.awardees) == 1:
            if self.awardees[0].role != "sole":
                raise ValueError("un attributaire unique porte le rôle 'sole'")
            return self
        if any(a.role == "sole" for a in self.awardees):
            raise ValueError("un consortium n'admet pas le rôle 'sole'")
        if sum(a.role == "consortium_lead" for a in self.awardees) > 1:
            raise ValueError("un consortium n'admet qu'un seul 'consortium_lead'")
        return self

    @model_validator(mode="after")
    def _dates_coherentes(self) -> ContractAward:
        if (
            self.contract_start_date is not None
            and self.contract_end_date is not None
            and self.contract_end_date < self.contract_start_date
        ):
            raise ValueError("contract_end_date antérieure à contract_start_date")
        return self

    def source_identity(self) -> SourceIdentity | None:
        """Identité CERTAINE, ou `None` — jamais un substitut calculé.

        Certaine parce qu'elle ne contient que ce que le portail a lui-même
        identifié : système, notice, version, lot, identifiant de contrat.

        Retourne `None` dès que `source_award_id` est absent, et c'est le point
        important : sans identifiant publié, (notice, lot) ne suffit PAS à
        identifier un contrat — un accord-cadre attribue plusieurs contrats au
        même lot de la même notice. Une absence d'identité est un fait, pas un
        trou à combler.
        """
        if self.source_award_id is None:
            return None
        return SourceIdentity(
            source_system=self.event_ref.source_system,
            source_notice_id=self.event_ref.source_notice_id,
            notice_version=self.event_ref.notice_version,
            lot_identifier=self.lot.identifier if self.lot else None,
            source_award_id=self.source_award_id,
        )

    def dedupe_fingerprint(self) -> str | None:
        """**Heuristique** de rapprochement — jamais une identité, jamais une clé d'unicité.

        Deux enregistrements partageant cette empreinte *peuvent* être le même
        contrat : c'est une piste à vérifier, pas une démonstration. Deux contrats
        réellement distincts peuvent parfaitement partager lot, gagnant, montant
        et date — un accord-cadre attribuant deux contrats identiques en valeur le
        même jour au même titulaire suffit.

        Usage prévu : signaler des doublons *possibles*, rapprocher une
        republication de son original, déclencher une vérification. Jamais :
        fusionner automatiquement, ni servir de `UNIQUE` en base.

        Retourne `None` quand trop peu de faits sont publiés pour que le
        rapprochement veuille dire quoi que ce soit (moins de deux composantes
        renseignées) : une empreinte calculée sur du vide ferait collisionner tous
        les avis pauvres entre eux, ce qui est pire qu'une absence de piste.

        L'événement source est volontairement exclu de l'empreinte : deux avis
        distincts décrivant le même contrat doivent pouvoir se rapprocher.
        """
        winners = sorted(_normalise_name(a.organization.legal_name) for a in self.awardees)
        parts = (
            self.lot.identifier if self.lot else "",
            "|".join(winners),
            f"{self.value.canonical_amount()} {self.value.currency}" if self.value else "",
            self.award_date.isoformat() if self.award_date else "",
        )
        if sum(1 for part in parts if part) < 2:
            return None
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]

    def belongs_to(self, event_ref: EventRef) -> bool:
        """Rattachement explicite — futur contrôle de clé étrangère."""
        return self.event_ref == event_ref
