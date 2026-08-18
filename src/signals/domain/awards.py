"""Le contrat attribué.

Unité retenue : **un contrat attribué, pour un lot, à un attributaire ou à un
consortium**. Ni « une notice », ni « un lot ».

Ce choix vient des faits, pas de l'esthétique :

- une notice peut porter plusieurs lots (donc `1 notice = 1 contrat` est faux) ;
- un accord-cadre peut attribuer un même lot à plusieurs fournisseurs distincts
  (donc `1 lot = 1 contrat` est faux aussi) ;
- un consortium est UN attributaire composé de plusieurs organisations (donc
  `plusieurs organisations = plusieurs contrats` est faux également) ;
- un même contrat peut être conclu avec plusieurs soumissionnaires retenus
  INDÉPENDANTS, sans qu'ils forment un groupement (donc `plusieurs organisations
  = un consortium` est faux aussi).

D'où : `PublicEvent` 1..N `ContractAward` 1..N `AwardeeParty` 1..N `Awardee`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Literal

from pydantic import Field, model_validator

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
"""Rôle d'une organisation À L'INTÉRIEUR d'un soumissionnaire retenu.

Il ne décrit jamais la relation entre deux soumissionnaires distincts : c'est
`AwardeeParty` qui porte le regroupement.
"""

WinnerStatus = Literal["identified", "ambiguous", "undisclosed"]
"""État de connaissance du gagnant — jamais une supposition.

- `identified` : l'avis nomme le ou les attributaires ;
- `ambiguous`  : l'avis nomme des candidats qu'on ne sait pas trancher (homonymie,
  mention tronquée, plusieurs entités possibles) → à vérifier avant exploitation ;
- `undisclosed`: l'avis ne publie pas d'attributaire (lot infructueux, mention
  absente) → aucun attributaire n'est inventé pour combler le vide.
"""


class Awardee(CanonicalModel):
    """Une organisation membre d'un soumissionnaire retenu."""

    organization: OrganizationRef
    role: AwardeeRole = "sole"


class AwardeeParty(CanonicalModel):
    """Un soumissionnaire retenu : une entreprise seule, ou un groupement.

    C'est le niveau qui manquait. Une liste plate d'organisations ne peut pas
    distinguer « trois entreprises groupées » de « trois entreprises retenues
    indépendamment » : elle force à qualifier de membres de consortium des
    opérateurs qui ne le sont pas.

    Le regroupement est donc **structurel** — une party = un soumissionnaire —
    et le rôle ne qualifie plus que la position à l'intérieur du groupement.
    Un contrat portant plusieurs parties n'affirme aucun lien entre elles.

    Notion source-agnostique : le groupement d'opérateurs existe dans tous les
    régimes de marchés publics, suisse comme européen, sous des noms différents.
    """

    members: tuple[Awardee, ...] = Field(min_length=1)
    # Nom du groupement quand la source le publie — jamais reconstitué à partir
    # des noms des membres.
    name: NonEmptyStr | None = None

    @property
    def is_group(self) -> bool:
        return len(self.members) > 1

    @model_validator(mode="after")
    def _membres_coherents(self) -> AwardeeParty:
        if len(self.members) == 1:
            if self.members[0].role != "sole":
                raise ValueError("un soumissionnaire à un seul membre porte le rôle 'sole'")
            return self
        if any(member.role == "sole" for member in self.members):
            raise ValueError("un groupement n'admet pas le rôle 'sole'")
        if sum(member.role == "consortium_lead" for member in self.members) > 1:
            raise ValueError("un groupement n'admet qu'un seul 'consortium_lead'")
        return self


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
    # Référence MÉTIER du contrat, telle que l'acheteur la publie (n° de marché).
    # Ce n'est pas une identité : elle est libre, parfois égale à la référence de
    # l'offre ou du projet. Elle n'entre ni dans `source_identity()` ni dans
    # `dedupe_fingerprint()`.
    contract_reference: NonEmptyStr | None = None

    # Objet du contrat
    title: NonEmptyStr | None = None
    description: str | None = None
    cpv_main: CpvCode | None = None
    cpv_additional: tuple[CpvCode, ...] = ()

    # Argent
    value: Money | None = None

    # Parties
    # Les organisations qui signent CE contrat du côté acheteur, quand la source
    # les désigne. Ce n'est pas la même chose que les acheteurs de la procédure,
    # qui vivent sur `PublicEvent.procedure_buyers` : une centrale d'achat mène
    # la procédure, l'entité bénéficiaire signe. Aucun des deux ensembles n'est
    # déduit de l'autre.
    contract_signatories: tuple[OrganizationRef, ...] = ()
    winner_status: WinnerStatus = "identified"
    awardee_parties: tuple[AwardeeParty, ...] = ()

    # Où
    place_of_performance: Location | None = None

    # Quand — quatre horloges distinctes, jamais fusionnées.
    #
    # `award_date`                 la DÉCISION : l'acheteur a retenu ce titulaire.
    # `contract_signature_date`    la CONCLUSION du contrat. C'est le champ
    #                              « conclusion » du modèle ; son nom historique dit
    #                              « signature » parce que le premier connecteur
    #                              l'appelait ainsi. Renommer casserait tous les
    #                              connecteurs, le moteur de compréhension et les
    #                              corpus déjà gelés, pour un gain nul : la
    #                              sémantique est celle de la conclusion, et elle
    #                              est écrite ici.
    # `contract_notification_date` la NOTIFICATION du contrat au titulaire — l'acte
    #                              qui rend le marché exécutoire dans certains
    #                              régimes. Elle SUIT la décision, parfois de
    #                              plusieurs semaines, et ne la date donc jamais.
    #                              Certains registres ne publient qu'elle : sans
    #                              champ propre, elle finirait dans `award_date` et
    #                              rajeunirait artificiellement chaque signal.
    # `contract_start_date`        le DÉBUT d'exécution.
    award_date: dt.date | None = None
    contract_signature_date: dt.date | None = None
    contract_notification_date: dt.date | None = None
    contract_start_date: dt.date | None = None
    contract_end_date: dt.date | None = None
    duration: Duration | None = None

    @model_validator(mode="after")
    def _gagnants_coherents(self) -> ContractAward:
        """La cohérence INTERNE d'un soumissionnaire est vérifiée par `AwardeeParty`.

        Ici, seule compte la relation entre le statut et la présence de
        soumissionnaires : plusieurs parties retenues est un état parfaitement
        normal, qui n'a plus besoin d'être signalé comme ambigu.
        """
        if self.winner_status == "undisclosed":
            if self.awardee_parties:
                raise ValueError("winner_status='undisclosed' n'admet aucun attributaire")
            return self
        if not self.awardee_parties:
            raise ValueError(
                f"winner_status='{self.winner_status}' exige au moins un attributaire ; "
                "utiliser 'undisclosed' quand la source n'en publie pas"
            )
        return self

    def awardee_organizations(self) -> tuple[OrganizationRef, ...]:
        """Toutes les organisations retenues, tous soumissionnaires confondus.

        Vue de commodité : elle aplatit, donc elle perd le regroupement. Ne pas
        l'utiliser pour raisonner sur qui est associé à qui.
        """
        return tuple(
            member.organization for party in self.awardee_parties for member in party.members
        )

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
        winners = sorted(_normalise_name(o.legal_name) for o in self.awardee_organizations())
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
