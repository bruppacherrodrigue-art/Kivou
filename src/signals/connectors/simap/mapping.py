"""Traduction d'une publication SIMAP vers le modèle canonique.

C'est ici, et nulle part ailleurs, que le vocabulaire SIMAP disparaît.

**Ce que SIMAP publie, et ce qu'il ne publie pas.** Le connecteur suit les faits
suisses, pas la forme eForms :

- une publication d'adjudication porte **au plus un lot** ; un projet à lots
  produit donc plusieurs publications, chacune son événement ;
- `decision.vendors` est une **liste plate** : SIMAP n'a aucune structure de
  groupement. Chaque adjudicataire devient donc sa propre `AwardeeParty`, et
  jamais un membre de consortium — l'affirmer serait inventer ;
- chaque adjudicataire porte **son propre prix**, ce qui fait de chacun un
  contrat distinct ;
- SIMAP ne publie **aucun identifiant de contrat** : `source_award_id` reste
  `None`, et `source_identity()` avec lui. Une absence d'identité est un fait.

**Périmètre.** Seules les publications de `projectType == "tender"` produisent
des `ContractAward`. Un « Zuschlag » de concours ou de mandat d'étude publie un
classement de jury et des prix (rang 1 à 4, montants dégressifs) : ce n'est pas
un contrat attribué, et le nommer ainsi serait faux.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from signals.connectors.simap.errors import SimapMappingError
from signals.connectors.simap.parser import (
    SimapAddress,
    SimapPublication,
    SimapVendor,
)
from signals.domain import (
    Awardee,
    AwardeeParty,
    ContractAward,
    EventRef,
    Location,
    LotRef,
    Money,
    OrganizationIdentifier,
    OrganizationRef,
    Provenance,
    PublicEvent,
)

SIMAP_DETAIL_URL = (
    "https://www.simap.ch/api/publications/v1/project/{project_id}"
    "/publication-details/{publication_id}"
)

# Seul ce type de projet aboutit à un contrat attribué.
CONTRACT_PROJECT_TYPE = "tender"

# `VatType` de l'OpenAPI SIMAP → catégorie canonique. Correspondance stricte,
# une valeur pour une valeur : aucun taux n'est déduit, et rien n'est interprété
# comme « TTC » ou « HT ».
VAT_CATEGORIES = {
    "no_vat": "none",
    "full": "standard",
    "special": "special",
    "reduced": "reduced",
    "foreign_vat": "foreign",
}


@dataclass(frozen=True)
class MappingWarning:
    """Ce que le connecteur n'a pas pu faire proprement — jamais avalé en silence."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class PublicationExtraction:
    """Le produit d'une publication : des faits canoniques et le compte du reste."""

    event: PublicEvent
    awards: tuple[ContractAward, ...]
    warnings: tuple[MappingWarning, ...] = ()
    vendors_published: int = 0
    has_lot: bool = False
    has_project_documents: bool = False
    references_tender: bool = False


def map_publication(
    publication: SimapPublication, *, retrieved_at: dt.datetime | None = None
) -> PublicationExtraction:
    """Traduit une publication lue par `parser.parse_publication`."""
    warnings: list[MappingWarning] = []
    event = _event(publication, retrieved_at=retrieved_at, warnings=warnings)

    if publication.project_type != CONTRACT_PROJECT_TYPE:
        # Concours et mandats d'étude : classement et prix, pas de contrat.
        warnings.append(
            MappingWarning(
                "not-a-contract-award",
                f"{publication.publication_number}: projectType={publication.project_type}",
            )
        )
        awards: tuple[ContractAward, ...] = ()
    else:
        awards = tuple(
            _award(publication, vendor, event.ref(), warnings) for vendor in publication.vendors
        )
        if not publication.vendors:
            warnings.append(
                MappingWarning("no-vendor-published", str(publication.publication_number))
            )

    return PublicationExtraction(
        event=event,
        awards=awards,
        warnings=tuple(warnings),
        vendors_published=len(publication.vendors),
        has_lot=publication.lot is not None,
        has_project_documents=bool(publication.has_project_documents),
        references_tender=publication.referencing_pub_id is not None,
    )


# ─── Événement public ───────────────────────────────────────────────────────────


def _event(
    publication: SimapPublication,
    *,
    retrieved_at: dt.datetime | None,
    warnings: list[MappingWarning],
) -> PublicEvent:
    """Une publication = un événement. Le projet, lui, est la procédure.

    `notice_version` reste `None` : SIMAP ne versionne pas une publication, il en
    publie une nouvelle sous un numéro suivant (`33112-02`, `33112-03`). Le
    drapeau `corrected` dit qu'une publication corrige la précédente, il ne fait
    pas d'elle une version de celle-ci.
    """
    if not publication.publication_date:
        warnings.append(
            MappingWarning("publication-date-absent", str(publication.publication_number))
        )

    return PublicEvent(
        provenance=Provenance(
            source_system="simap",
            source_country="CH",
            # L'identité de l'événement est la publication, pas le projet.
            source_notice_id=publication.publication_id,
            notice_version=None,
            # Le projet est la procédure : appel d'offres, adjudication et
            # corrections le partagent. C'est par lui que passera le lien vers
            # l'appel d'offres d'origine et ses documents.
            source_procedure_id=publication.project_id,
            source_url=SIMAP_DETAIL_URL.format(
                project_id=publication.project_id, publication_id=publication.publication_id
            ),
            retrieved_at=retrieved_at,
        ),
        event_type="award_notice",
        published_at=publication.publication_date,
        # Contrairement à TED, la décision d'adjudication est datée AU NIVEAU DE
        # LA PUBLICATION : une publication, une décision.
        event_date=_date(publication.award_decision_date),
        # SIMAP ne publie aucune référence à la publication corrigée : `corrects`
        # resterait une invention.
        corrects=None,
        procedure_buyers=_procedure_buyers(publication, warnings),
        source_notice_links=(publication.referencing_pub_id,)
        if publication.referencing_pub_id
        else (),
    )


def _procedure_buyers(
    publication: SimapPublication, warnings: list[MappingWarning]
) -> tuple[OrganizationRef, ...]:
    """Les deux organisations publiées : l'adjudicateur et le service bénéficiaire.

    SIMAP publie systématiquement `procOfficeAddress` (qui mène la procédure) et
    `procurementRecipientAddress` (pour qui l'achat est fait). Elles sont souvent
    identiques, parfois non — n'en garder qu'une effacerait le second cas.
    Aucune n'est désignée comme principale.
    """
    buyers: list[OrganizationRef] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for address in (publication.proc_office, publication.procurement_recipient):
        reference = _organization(address, scheme="SIMAP-ORG-ID")
        if reference is None:
            if address is not None:
                warnings.append(
                    MappingWarning("buyer-without-name", str(publication.publication_number))
                )
            continue
        key = (reference.legal_name, reference.address, reference.country)
        if key in seen:
            continue
        seen.add(key)
        buyers.append(reference)
    if not buyers:
        warnings.append(MappingWarning("buyer-absent", str(publication.publication_number)))
    return tuple(buyers)


# ─── Contrat attribué ───────────────────────────────────────────────────────────


def _award(
    publication: SimapPublication,
    vendor: SimapVendor,
    event_ref: EventRef,
    warnings: list[MappingWarning],
) -> ContractAward:
    organization = _organization(
        vendor.address, scheme="SIMAP-VENDOR-ID", name=vendor.name, organization_id=vendor.vendor_id
    )
    if organization is None:
        raise SimapMappingError(
            f"adjudicataire sans raison sociale dans {publication.publication_number}"
        )

    return ContractAward(
        event_ref=event_ref,
        # SIMAP ne publie aucun identifiant de contrat : ni technique, ni métier.
        # `vendorId` identifie l'ENTREPRISE, pas le contrat — l'y placer dirait
        # que la source a identifié un contrat, ce qui est faux.
        source_award_id=None,
        contract_reference=None,
        lot=_lot(publication),
        title=publication.title,
        description=publication.order_description,
        cpv_main=publication.cpv_main or None,
        cpv_additional=publication.cpv_additional,
        value=_value(publication, vendor, warnings),
        contract_signatories=(),  # SIMAP ne publie pas de signataire de contrat
        winner_status="identified",
        awardee_parties=(AwardeeParty(members=(Awardee(organization=organization),)),),
        place_of_performance=_place(publication),
        award_date=_date(publication.award_decision_date),
        # Ni date de signature, ni période contractuelle sur l'adjudication : ces
        # champs vivent sur l'appel d'offres et décrivent une durée PRÉVUE, pas le
        # contrat conclu.
        contract_signature_date=None,
        contract_start_date=None,
        contract_end_date=None,
        duration=None,
    )


def _value(
    publication: SimapPublication, vendor: SimapVendor, warnings: list[MappingWarning]
) -> Money | None:
    """Le prix de l'offre retenue DE CET adjudicataire, et rien d'autre.

    Sont volontairement ignorés : `totalPriceRange` (fourchette de l'ensemble des
    offres retenues, publiée quand l'acheteur refuse de détailler) et toute
    valeur estimée de l'appel d'offres. Aucune somme entre adjudicataires.

    `vatType` qualifie ce montant et est conservé tel quel dans
    `Money.vat_category`. Une valeur inconnue du schéma n'est pas traduite au
    hasard : elle est signalée et la catégorie reste absente.
    """
    if vendor.price is None or vendor.currency is None:
        warnings.append(
            MappingWarning("value-absent", f"{publication.publication_number}: {vendor.name}")
        )
        return None
    if vendor.price < 0:
        warnings.append(
            MappingWarning("value-negative", f"{publication.publication_number}: {vendor.price}")
        )
        return None
    vat_category = VAT_CATEGORIES.get(vendor.vat_type) if vendor.vat_type else None
    if vendor.vat_type and vat_category is None:
        warnings.append(
            MappingWarning(
                "unknown-vat-type",
                f"{publication.publication_number}: vatType={vendor.vat_type}",
            )
        )
    return Money(amount=Decimal(vendor.price), currency=vendor.currency, vat_category=vat_category)


def _lot(publication: SimapPublication) -> LotRef | None:
    """L'identifiant du lot est son UUID : c'est celui que la source sait résoudre.

    `lotNumber` (1, 2, 3…) numérote le lot pour le lecteur ; l'UUID est ce qui
    permet d'interroger l'API pour ce lot (l'historique des publications l'exige).
    """
    if publication.lot is None:
        return None
    return LotRef(identifier=publication.lot.lot_id, title=publication.lot.title)


def _place(publication: SimapPublication) -> Location | None:
    """Le lieu d'exécution n'est PAS publié sur l'adjudication.

    Il vient de la ligne de recherche, seul endroit où l'API l'expose pour une
    publication d'adjudication. Sans elle, le lieu reste inconnu.
    """
    address = publication.order_address
    if address is None:
        return None
    if not any((address.country, address.canton, address.postal_code, address.city)):
        return None
    return Location(
        country=address.country,
        subdivision_code=f"CH-{address.canton}" if address.canton else None,
        subdivision_scheme="ISO-3166-2" if address.canton else None,
        locality=address.city,
        postal_code=address.postal_code,
    )


def _organization(
    address: SimapAddress | None,
    *,
    scheme: str,
    name: str | None = None,
    organization_id: str | None = None,
) -> OrganizationRef | None:
    """La mention brute, sans enrichissement : aucun registre n'est interrogé.

    SIMAP ne publie pas l'IDE/UID des entreprises : le seul identifiant
    disponible est l'identifiant interne de la plateforme.
    """
    legal_name = name or (address.name if address else None)
    if not legal_name:
        return None
    identifier = organization_id or (address.organization_id if address else None)
    postal = ", ".join(
        part
        for part in (
            address.street if address else None,
            address.postal_code if address else None,
            address.city if address else None,
        )
        if part
    )
    return OrganizationRef(
        legal_name=legal_name,
        identifiers=(
            (OrganizationIdentifier(scheme=scheme, value=identifier),) if identifier else ()
        ),
        country=(address.country if address else None),
        address=postal or None,
        website=(address.url if address else None),
    )


def _date(raw: str | None) -> dt.date | None:
    return dt.date.fromisoformat(raw) if raw else None
