"""Le document de marché — l'objet, pas son interprétation.

Le spike a établi le fait qui commande tout ce modèle : **TED n'héberge pas les
documents**. Il publie un pointeur vers l'un d'une trentaine de portails
nationaux, et sur deux échantillons indépendants, **1 URL sur 19 puis 1 sur 39**
mène réellement à un fichier téléchargeable. SIMAP, lui, exige un rôle
authentifié.

D'où la règle qui structure `DocumentAccessStatus` : « je ne peux pas y accéder »
et « il n'y en a pas » sont deux faits différents, et les confondre ferait dire à
Kivou qu'un marché est sans documents alors qu'il en a.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, model_validator

from signals.domain import SourceSystem
from signals.domain.values import CanonicalModel, NonEmptyStr

DocumentAccessStatus = Literal[
    "available",
    "external",
    "auth_required",
    "not_found",
    "unsupported",
    "download_failed",
    "too_large",
    "encrypted",
    "portal_blocked",
    "cgu_restricted",
]
"""État TECHNIQUE de l'accès. Aucun n'équivaut à « pas de document ».

- `available`       : le contenu a été récupéré ;
- `external`        : l'avis publie une adresse, mais elle mène à un portail —
  état **normal** sur TED, pas un échec ;
- `auth_required`   : la plateforme exige un compte (SIMAP, plusieurs portails) ;
- `not_found`       : l'adresse publiée ne répond plus ;
- `unsupported`     : format récupéré mais non traité par ce moteur ;
- `download_failed` : panne réseau ou refus serveur ;
- `too_large`       : au-delà de la limite configurée, arrêté avant lecture ;
- `encrypted`       : fichier protégé, jamais forcé.
- `portal_blocked`  : retrait automatisé suspendu (CAPTCHA, robots ou incident) ;
- `cgu_restricted`  : retrait automatisé interdit sans autorisation contractuelle.
"""

RETRIEVED_STATUSES = ("available", "unsupported", "encrypted")

AccessFamily = Literal[
    "direct_document_access",
    "external_portal",
    "auth_required",
    "not_found",
    "download_failed",
]
"""Regroupement de reporting — **où se trouve réellement le dossier**.

Les huit états techniques disent ce qui s'est passé sur une adresse ; ces cinq
familles disent ce que cela signifie pour le produit. Les tenir séparées est ce
qui permettra plus tard de choisir quels portails méritent un adaptateur, sans
confondre « le fichier a été servi » et « il a fallu un compte ».
"""

_ACCESS_FAMILIES: dict[str, AccessFamily] = {
    # Les octets ont été servis, même si le format n'est pas lisible ensuite.
    "available": "direct_document_access",
    "unsupported": "direct_document_access",
    "encrypted": "direct_document_access",
    "external": "external_portal",
    "auth_required": "auth_required",
    "not_found": "not_found",
    "download_failed": "download_failed",
    "too_large": "download_failed",
    "portal_blocked": "external_portal",
    "cgu_restricted": "external_portal",
}


def access_family(status: DocumentAccessStatus) -> AccessFamily:
    """La famille d'accès d'un état technique."""
    return _ACCESS_FAMILIES[status]


DocumentKind = Literal[
    "technical_specification",
    "contract_conditions",
    "bill_of_quantities",
    "procedure_rules",
    "form",
    "annex",
    "notice_copy",
    "archive",
    "unknown",
]
"""Nature du document, telle que son nom et son format la laissent voir.

Taxonomie tirée des deux dossiers réels (cahier des charges, programme de
procédure, bordereaux, ESPD, annonces), pas d'une théorie documentaire.
"""


class TenderDocument(CanonicalModel):
    """Un document du dossier de marché — ce qu'il est et d'où il vient.

    Il ne porte aucune interprétation : ni exigence, ni résumé. Son contenu
    textuel et les exigences qu'on en tire vivent dans d'autres objets.
    """

    source_system: SourceSystem
    source_procedure_id: NonEmptyStr | None = None
    source_notice_id: NonEmptyStr | None = None

    name: NonEmptyStr | None = None
    source_url: NonEmptyStr | None = None
    media_type: NonEmptyStr | None = None
    language: NonEmptyStr | None = None
    kind: DocumentKind = "unknown"

    access_status: DocumentAccessStatus
    # Empreinte des octets BRUTS. Ce n'est pas un identifiant métier : c'est ce
    # qui prouve quel fichier a été lu, et ce qui distingue deux versions
    # publiées sous le même nom.
    content_hash: NonEmptyStr | None = None
    byte_size: int | None = Field(default=None, ge=0)
    retrieved_at: dt.datetime | None = None

    # Localisation dans une archive, quand le document en vient.
    container_hash: NonEmptyStr | None = None
    path_in_container: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _coherence(self) -> TenderDocument:
        if self.access_status in RETRIEVED_STATUSES and not self.content_hash:
            raise ValueError(
                f"statut '{self.access_status}' sans content_hash : un document lu doit "
                "pouvoir être prouvé"
            )
        if self.access_status not in RETRIEVED_STATUSES and self.content_hash:
            raise ValueError(
                f"statut '{self.access_status}' avec content_hash : rien n'a été récupéré"
            )
        if not any((self.name, self.source_url, self.path_in_container)):
            raise ValueError("document sans nom, sans adresse et sans chemin d'archive")
        return self

    @property
    def is_retrieved(self) -> bool:
        return self.access_status in RETRIEVED_STATUSES

    @property
    def is_readable(self) -> bool:
        return self.access_status == "available"

    def identity(self) -> tuple[str | None, str | None, str | None]:
        """Ce qui distingue deux documents : nom, emplacement, empreinte.

        Deux fichiers de même nom mais de contenus différents restent deux
        documents — le nom ne versionne rien.
        """
        return (self.name, self.path_in_container or self.source_url, self.content_hash)


CoverageStatus = Literal[
    "documents_analyzed",
    "partial_documents",
    "external_only",
    "auth_required",
    "no_documents",
    "unsupported_documents",
    "download_failed",
]
"""Ce que le dossier a permis de faire. **Ce n'est pas une mesure de confiance** :
un dossier parfaitement analysé peut ne contenir aucune exigence claire, et un
dossier inaccessible n'invalide pas l'award.
"""
