"""De l'award au dossier documentaire — en suivant ce que la source publie.

    ContractAward → source_procedure_id → avis d'appel d'offres → références documentaires

Le spike a mesuré chaque maillon sur des données réelles :

- **TED** — la recherche par `procedure-identifier` retrouve l'avis d'appel
  d'offres pour 19 procédures sur 22 ; celui-ci publie une URL documentaire
  (BT-15) dans **19 cas sur 19**. Mais cette URL mène à un fichier dans **1 cas
  sur 19**, puis **1 sur 39** sur un second échantillon : partout ailleurs, c'est
  la page d'accueil d'un portail national. `external` est donc l'état normal.
- **SIMAP** — `referencingPubId` donne l'appel d'offres, `hasProjectDocuments`
  dit que des documents existent, et **aucun endpoint public ne les sert** :
  `auth_required`. Aucun compte n'est créé, aucune permission contournée.

Rien n'est inventé : sans lien publié, il n'y a pas de dossier.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from defusedxml import ElementTree as DefusedET

from signals.documents.model import TenderDocument
from signals.domain import ContractAward, PublicEvent

CAC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
CBC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"


@dataclass
class DocumentReference:
    """Une référence documentaire publiée — pas encore un document récupéré."""

    url: str | None = None
    name: str | None = None
    tender_notice_id: str | None = None
    procedure_id: str | None = None


@dataclass
class DiscoveryResult:
    procedure_id: str | None = None
    tender_notice_id: str | None = None
    references: list[DocumentReference] = field(default_factory=list)
    documents_advertised: bool = False
    warnings: list[str] = field(default_factory=list)


def procedure_of(award: ContractAward, event: PublicEvent) -> str | None:
    """La procédure dont dépend le dossier. Aucun repli inventé."""
    return event.provenance.source_procedure_id


def references_from_ted_notice(xml: bytes | str) -> list[DocumentReference]:
    """Lit les URL documentaires (BT-15) d'un avis d'appel d'offres eForms.

    Le chemin est celui des données réelles :
    `ProcurementProjectLot/TenderingTerms/CallForTendersDocumentReference/
     Attachment/ExternalReference/URI`.
    """
    root = DefusedET.fromstring(xml)
    notice_id = root.findtext(f"{CBC}ID")
    references: list[DocumentReference] = []
    seen: set[str] = set()

    for lot in root.findall(f"{CAC}ProcurementProjectLot"):
        terms = f"{CAC}TenderingTerms/{CAC}CallForTendersDocumentReference"
        names = [
            node.text.strip()
            for node in lot.findall(f"{terms}/{CBC}ID")
            if node.text and node.text.strip()
        ]
        for node in lot.findall(f"{terms}/{CAC}Attachment/{CAC}ExternalReference/{CBC}URI"):
            url = (node.text or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            references.append(
                DocumentReference(
                    url=url,
                    name=names[0] if names else None,
                    tender_notice_id=notice_id,
                )
            )
    return references


def simap_dossier(
    award: ContractAward, event: PublicEvent, *, tender_has_documents: bool | None
) -> DiscoveryResult:
    """Le dossier SIMAP : signalé, jamais servi publiquement.

    `hasProjectDocuments=True` prouve que des documents existent. Il ne dit rien
    d'un accès anonyme — et l'API n'en offre aucun.
    """
    result = DiscoveryResult(
        procedure_id=procedure_of(award, event),
        documents_advertised=bool(tender_has_documents),
    )
    if tender_has_documents:
        result.warnings.append(
            "SIMAP : documents signalés par l'appel d'offres, accès réservé à un rôle "
            "authentifié (acheteur ou soumissionnaire)"
        )
    return result


def auth_required_document(
    award: ContractAward, event: PublicEvent, *, name: str = "dossier de marché"
) -> TenderDocument:
    """Le fait « il existe des documents, je n'y ai pas accès », rendu explicite.

    C'est un résultat, pas un échec : le confondre avec « pas de document »
    ferait dire à Kivou le contraire de ce que la plateforme publie.
    """
    return TenderDocument(
        source_system=event.provenance.source_system,
        source_procedure_id=event.provenance.source_procedure_id,
        source_notice_id=event.provenance.source_notice_id,
        name=name,
        access_status="auth_required",
    )


# ─── Mesure du rapprochement ────────────────────────────────────────────────────

LinkageStatus = Literal[
    "linked",
    "tender_not_publicly_resolvable",
    "no_procedure_id",
    "lookup_failed",
]
"""Ce qui est arrivé au rapprochement award → appel d'offres.

`tender_not_publicly_resolvable` est le cas majoritaire des échecs mesurés : la
procédure existe, l'avis d'attribution la nomme, et **aucun avis d'appel
d'offres ne porte cet identifiant dans TED** — marché négocié sans publication
préalable, ou appel publié avant la migration eForms. Ce n'est pas un lien raté :
il n'y a rien à rapprocher.
"""


@dataclass
class LinkageOutcome:
    """Le résultat d'un rapprochement, et ce qu'une revue humaine en a dit."""

    award: str
    procedure_id: str | None
    tender_notice_id: str | None
    status: LinkageStatus
    # Nombre d'avis partageant l'identifiant de procédure — la preuve qu'il n'y
    # avait rien à trouver quand il vaut 1 (l'avis d'attribution lui-même).
    notices_sharing_identifier: int | None = None
    # `None` = pas encore relu. Un lien non relu n'est jamais compté comme juste.
    verified: bool | None = None


def linkage_metrics(outcomes: Sequence[LinkageOutcome]) -> dict[str, object]:
    """Deux taux, jamais un seul.

    - `linkage_coverage` : part des attributions pour lesquelles un appel
      d'offres a été rattaché. Elle est plafonnée par ce que la source publie.
    - `linkage_accuracy_when_available` : justesse **là où le rapprochement était
      techniquement possible**. C'est le seul des deux qu'un défaut de code peut
      dégrader, et donc le seul auquel une cible de qualité s'applique.
    """
    evaluated = len(outcomes)
    linked = [o for o in outcomes if o.status == "linked"]
    eligible = [
        o for o in outcomes if o.status not in ("tender_not_publicly_resolvable", "no_procedure_id")
    ]
    reviewed = [o for o in eligible if o.verified is not None]
    correct = [o for o in reviewed if o.verified]

    return {
        "evaluated": evaluated,
        "linked": len(linked),
        "linkage_coverage": len(linked) / evaluated if evaluated else None,
        "eligible": len(eligible),
        "not_publicly_resolvable": sum(
            1 for o in outcomes if o.status == "tender_not_publicly_resolvable"
        ),
        "no_procedure_id": sum(1 for o in outcomes if o.status == "no_procedure_id"),
        "reviewed": len(reviewed),
        "correct": len(correct),
        "linkage_accuracy_when_available": (len(correct) / len(reviewed) if reviewed else None),
    }
