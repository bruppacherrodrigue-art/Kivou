"""Traduction d'une notice eForms vers le modèle canonique.

C'est ici, et nulle part ailleurs, que le vocabulaire TED disparaît.

**Règle de reconstruction du graphe.** eForms ne contient pas de relation
`contrat → gagnant` imbriquée : il faut la suivre par références.

    SettledContract ──BT-3202──▶ LotTender ──▶ TenderingParty ──▶ Tenderer ──▶ Organization
            │                        │
            │                        └──▶ TenderLot ──▶ ProcurementProjectLot
            └──▶ SignatoryParty ──▶ Organization (signataire DE CE CONTRAT)

    ContractingParty ──▶ Organization (acheteur de la PROCÉDURE, au niveau de l'avis)

Le contrat est le point de départ, pas le `LotResult` : sur un accord-cadre réel
(566075-2026), le `LotResult` référence les **27 offres reçues**, y compris des
offres classées 2ᵉ et 10ᵉ, dont 19 seulement ont donné un contrat. Partir du
`LotResult` reviendrait à traiter des perdants comme des gagnants.

De même, `/*/cac:TenderResult/cbc:AwardDate` existe à la racine de tout avis
(UBL l'impose) et vaut `2000-01-01` dans 33 des 41 avis observés : c'est un
bouchon, jamais une date d'adjudication. Il n'est pas lu.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from signals.connectors.ted.codes import alpha2
from signals.connectors.ted.errors import TedMappingError
from signals.connectors.ted.parser import (
    TedContract,
    TedLot,
    TedNotice,
    TedOrganization,
    TedTender,
)
from signals.domain import (
    Awardee,
    AwardeeParty,
    ContractAward,
    Duration,
    EventRef,
    Location,
    LotRef,
    Money,
    OrganizationIdentifier,
    OrganizationRef,
    Provenance,
    PublicEvent,
)

TED_XML_URL = "https://ted.europa.eu/en/notice/{publication_number}/xml"

# BT-142 — issue du lot. Seul `selec-w` signifie qu'un attributaire a été retenu.
WINNER_CHOSEN = "selec-w"

_DURATION_UNITS = {"DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}


@dataclass(frozen=True)
class MappingWarning:
    """Ce que le connecteur n'a pas pu faire proprement — jamais avalé en silence."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class NoticeExtraction:
    """Le produit d'une notice : des faits canoniques et le compte de ce qui manque."""

    event: PublicEvent
    awards: tuple[ContractAward, ...]
    warnings: tuple[MappingWarning, ...] = ()
    lots: int = 0
    lot_results: int = 0
    lots_not_awarded: int = 0
    contracts: int = 0


def map_notice(notice: TedNotice, *, retrieved_at: dt.datetime | None = None) -> NoticeExtraction:
    """Traduit une notice lue par `parser.parse_notice`."""
    warnings: list[MappingWarning] = []
    event = _event(notice, retrieved_at=retrieved_at, warnings=warnings)
    awards = tuple(_award(notice, contract, event.ref(), warnings) for contract in notice.contracts)

    not_awarded = 0
    for lot_result in notice.lot_results:
        if lot_result.winner_selection_status != WINNER_CHOSEN:
            not_awarded += 1
        elif not lot_result.contract_ids:
            # Non observé sur l'échantillon : un attributaire retenu produit toujours
            # un contrat. Si cela survient, aucun award n'est fabriqué — on ne sait
            # pas quel contrat il représenterait.
            warnings.append(MappingWarning("winner-without-contract", f"{lot_result.result_id}"))
    return NoticeExtraction(
        event=event,
        awards=awards,
        warnings=tuple(warnings),
        lots=len(notice.lots),
        lot_results=len(notice.lot_results),
        lots_not_awarded=not_awarded,
        contracts=len(notice.contracts),
    )


# ─── Événement public ───────────────────────────────────────────────────────────


def _event(
    notice: TedNotice, *, retrieved_at: dt.datetime | None, warnings: list[MappingWarning]
) -> PublicEvent:
    """L'identité de l'événement est (UUID de notice, version), pas le n° de publication.

    L'UUID `BT-701` est stable d'une version à l'autre ; le numéro de publication
    au JOUE change à chaque republication. Le couple (UUID, version) désigne donc
    exactement « cette version de cet avis », et le numéro de publication reste
    joignable via `source_url`.
    """
    country = _buyer_country(notice)
    if country is None:
        raise TedMappingError(
            f"pays de l'acheteur introuvable ou non convertible pour {notice.notice_uuid}"
        )
    if not notice.publication_date:
        warnings.append(MappingWarning("publication-date-absent", notice.notice_uuid))

    return PublicEvent(
        provenance=Provenance(
            source_system="ted",
            source_country=country,
            source_notice_id=notice.notice_uuid,
            notice_version=notice.version,
            # BT-04 — la procédure, partagée avec l'appel d'offres d'origine et les
            # corrections. Présent sur 46 notices sur 46.
            source_procedure_id=notice.procedure_id,
            source_url=(
                TED_XML_URL.format(publication_number=notice.publication_number)
                if notice.publication_number
                else None
            ),
            retrieved_at=retrieved_at,
        ),
        event_type="award_notice",
        # TED publie une DATE de parution au JOUE, jamais une heure : la précision
        # s'arrête là. `cbc:IssueTime` existe mais date l'envoi par l'acheteur,
        # ce qui est un autre fait.
        published_at=notice.publication_date,
        # Aucune date d'événement au niveau de l'avis : l'adjudication est datée
        # contrat par contrat (BT-1451), pas notice par notice.
        event_date=None,
        procedure_buyers=_procedure_buyers(notice, warnings),
    )


def _buyer_country(notice: TedNotice) -> str | None:
    for org_id in notice.buyer_org_ids:
        organization = notice.organizations.get(org_id)
        if organization is not None:
            converted = alpha2(organization.country)
            if converted:
                return converted
    return None


# ─── Contrat attribué ───────────────────────────────────────────────────────────


def _award(
    notice: TedNotice,
    contract: TedContract,
    event_ref: EventRef,
    warnings: list[MappingWarning],
) -> ContractAward:
    tenders = [notice.tenders[t] for t in contract.tender_ids if t in notice.tenders]
    for missing in [t for t in contract.tender_ids if t not in notice.tenders]:
        warnings.append(
            MappingWarning("dangling-tender-reference", f"{contract.contract_id}→{missing}")
        )

    lot = _lot_of(notice, contract, tenders, warnings)
    awardee_parties, winner_status = _winners(notice, contract, tenders, warnings)
    value = _value(contract, tenders, warnings)

    lot_data = notice.lots.get(lot.identifier) if lot else None
    duration = _duration(lot_data)

    return ContractAward(
        event_ref=event_ref,
        # L'identifiant technique du contrat : attribué par la source, unique dans
        # la notice. BT-150 (`contract_reference`) est une référence métier libre
        # de l'acheteur — elle vaut parfois la référence de l'offre ou du projet.
        source_award_id=contract.contract_id,
        # BT-150 : référence métier du contrat, conservée telle quelle et jamais
        # utilisée comme identité ni comme clé de rapprochement.
        contract_reference=contract.contract_reference,
        lot=lot,
        title=_pick_language(lot_data.titles, notice.language) if lot_data else None,
        description=_pick_language(lot_data.descriptions, notice.language) if lot_data else None,
        cpv_main=lot_data.cpv_main if lot_data and lot_data.cpv_main else None,
        cpv_additional=tuple(lot_data.cpv_additional) if lot_data else (),
        value=value,
        contract_signatories=_signatories(notice, contract, warnings),
        winner_status=winner_status,
        awardee_parties=awardee_parties,
        place_of_performance=_place(lot_data, warnings),
        award_date=_date(contract.award_date),  # BT-1451 décision d'attribution
        contract_signature_date=_date(contract.issue_date),  # BT-145 conclusion
        contract_start_date=_date(lot_data.start_date) if lot_data else None,  # BT-536
        contract_end_date=_date(lot_data.end_date) if lot_data else None,  # BT-537
        duration=duration,
    )


def _lot_of(
    notice: TedNotice,
    contract: TedContract,
    tenders: list[TedTender],
    warnings: list[MappingWarning],
) -> LotRef | None:
    """Le lot vient de l'offre, jamais de la position du contrat dans le XML."""
    lot_ids = {t.lot_id for t in tenders if t.lot_id}
    if len(lot_ids) > 1:
        warnings.append(
            MappingWarning("contract-spans-lots", f"{contract.contract_id}: {sorted(lot_ids)}")
        )
        return None
    if not lot_ids:
        return None
    lot_id = lot_ids.pop()
    lot = notice.lots.get(lot_id)
    if lot is None:
        warnings.append(MappingWarning("unknown-lot-reference", f"{contract.contract_id}→{lot_id}"))
        return LotRef(identifier=lot_id)
    return LotRef(identifier=lot_id, title=_pick_language(lot.titles, notice.language))


def _winners(
    notice: TedNotice,
    contract: TedContract,
    tenders: list[TedTender],
    warnings: list[MappingWarning],
) -> tuple[tuple[AwardeeParty, ...], str]:
    """Une `TenderingParty` eForms = un `AwardeeParty` canonique. Rien de plus.

    Les trois situations réelles se traduisent sans rien affirmer de faux :

    - une `TenderingParty` d'un seul `Tenderer` → une party, un membre `sole` ;
    - une `TenderingParty` de plusieurs `Tenderer` → une party groupée, avec son
      chef de file quand `efbc:GroupLeadIndicator` le désigne ;
    - plusieurs `TenderingParty` sur le même contrat (566075-2026 : un
      contrat-cadre roumain référençant 9 offres de 9 opérateurs distincts) →
      **plusieurs parties**, chacune avec ses membres. Aucun lien n'est affirmé
      entre elles, et le statut reste `identified` : la source les nomme toutes,
      il n'y a rien d'ambigu à signaler.
    """
    party_ids = [t.tendering_party_id for t in tenders if t.tendering_party_id]
    unique_parties = list(dict.fromkeys(party_ids))
    if not unique_parties:
        return (), "undisclosed"

    parties: list[AwardeeParty] = []
    for party_id in unique_parties:
        party = notice.tendering_parties.get(party_id)
        if party is None:
            warnings.append(
                MappingWarning("unknown-tendering-party", f"{contract.contract_id}→{party_id}")
            )
            continue
        members = _members(notice, contract, party.tenderers, warnings)
        if members:
            parties.append(AwardeeParty(members=members, name=party.name))

    if not parties:
        return (), "undisclosed"
    if len(parties) > 1:
        # Fait notable, pas un défaut : plusieurs titulaires indépendants sur un
        # même contrat. Signalé pour la mesure, sans dégrader le statut.
        warnings.append(
            MappingWarning(
                "contract-with-several-awardee-parties",
                f"{contract.contract_id}: {unique_parties}",
            )
        )
    return tuple(parties), "identified"


def _members(
    notice: TedNotice,
    contract: TedContract,
    tenderers: tuple[tuple[str, bool | None], ...],
    warnings: list[MappingWarning],
) -> tuple[Awardee, ...]:
    """Les organisations d'UNE partie, avec leur rôle interne."""
    resolved: list[tuple[OrganizationRef, bool | None]] = []
    for org_id, lead in tenderers:
        organization = notice.organizations.get(org_id)
        if organization is None:
            warnings.append(
                MappingWarning("unknown-organization", f"{contract.contract_id}→{org_id}")
            )
            continue
        reference = _organization(organization)
        if reference is None:
            warnings.append(
                MappingWarning("organization-without-name", f"{contract.contract_id}→{org_id}")
            )
            continue
        resolved.append((reference, lead))

    if not resolved:
        return ()
    if len(resolved) == 1:
        return (Awardee(organization=resolved[0][0]),)

    members = tuple(
        Awardee(
            organization=reference,
            role="consortium_lead" if lead else "consortium_member",
        )
        for reference, lead in resolved
    )
    # Le domaine n'admet qu'un seul chef de file ; si la source en désigne
    # plusieurs, aucun n'est retenu plutôt que d'en choisir un arbitrairement.
    if sum(m.role == "consortium_lead" for m in members) > 1:
        warnings.append(MappingWarning("several-group-leads", contract.contract_id))
        members = tuple(m.model_copy(update={"role": "consortium_member"}) for m in members)
    return members


def _value(
    contract: TedContract, tenders: list[TedTender], warnings: list[MappingWarning]
) -> Money | None:
    """La valeur du contrat est celle de l'offre retenue (BT-720), et rien d'autre.

    Sont volontairement ignorés — ils décrivent autre chose que ce contrat :
    `NoticeResult/cbc:TotalAmount` (BT-161, somme de l'avis),
    `LotResult/cbc:HigherTenderAmount` et `LowerTenderAmount` (BT-711/BT-710,
    bornes des offres reçues), `FrameworkAgreementValues` (BT-118/BT-660,
    plafond et réestimation de l'accord-cadre), `OverallMaximum…` (niveau avis).

    Quand un contrat référence plusieurs offres, aucune addition n'est faite :
    rien dans eForms ne dit que la somme des offres est la valeur du contrat.
    """
    if len(tenders) != 1:
        if tenders:
            warnings.append(
                MappingWarning(
                    "value-not-attributable",
                    f"{contract.contract_id}: {len(tenders)} offres référencées",
                )
            )
        return None
    tender = tenders[0]
    if tender.amount is None or tender.currency is None:
        warnings.append(MappingWarning("value-absent", contract.contract_id))
        return None
    try:
        amount = Decimal(tender.amount)
    except InvalidOperation:
        warnings.append(
            MappingWarning("value-unreadable", f"{contract.contract_id}: {tender.amount!r}")
        )
        return None
    if amount < 0:
        # Observé sur 566117-2026 (DEU) : `-1` sert de marqueur « non communiqué ».
        # Un montant négatif n'est pas une valeur de contrat ; le stocker tel quel
        # reviendrait à publier un chiffre faux.
        warnings.append(
            MappingWarning("value-negative-sentinel", f"{contract.contract_id}: {tender.amount}")
        )
        return None
    try:
        return Money(amount=amount, currency=tender.currency)
    except ValueError as exc:
        warnings.append(
            MappingWarning("value-rejected", f"{contract.contract_id}: {tender.amount} ({exc})")
        )
        return None


def _procedure_buyers(
    notice: TedNotice, warnings: list[MappingWarning]
) -> tuple[OrganizationRef, ...]:
    """Les acheteurs de la procédure — `cac:ContractingParty`, au niveau de l'avis.

    Tous conservés, aucun promu : deux avis sur 41 déclarent un achat conjoint et
    ne désignent pas de chef de file.
    """
    return _organizations(notice, notice.buyer_org_ids, warnings, "buyer")


def _signatories(
    notice: TedNotice, contract: TedContract, warnings: list[MappingWarning]
) -> tuple[OrganizationRef, ...]:
    """Les signataires de CE contrat — `SettledContract/cac:SignatoryParty`.

    Publiés sur 27 contrats sur 289, jamais plus d'un à la fois. Ils ne sont
    jamais complétés par les acheteurs de la procédure : un contrat sans
    signataire publié reste un contrat sans signataire connu.
    """
    signatories = _organizations(notice, contract.signatory_org_ids, warnings, "signatory")
    hors_procedure = [
        org_id for org_id in contract.signatory_org_ids if org_id not in notice.buyer_org_ids
    ]
    if hors_procedure:
        # Cas réel (565986-2026) : une centrale d'achat mène la procédure, une
        # autre entité signe. Ce n'est pas une anomalie, c'est le fait le plus
        # intéressant de l'avis — il est signalé, jamais fusionné.
        warnings.append(
            MappingWarning(
                "signatory-outside-procedure-buyers",
                f"{contract.contract_id}: {hors_procedure}",
            )
        )
    return signatories


def _organizations(
    notice: TedNotice, org_ids: tuple[str, ...], warnings: list[MappingWarning], role: str
) -> tuple[OrganizationRef, ...]:
    resolved: list[OrganizationRef] = []
    for org_id in dict.fromkeys(org_ids):
        organization = notice.organizations.get(org_id)
        if organization is None:
            warnings.append(MappingWarning(f"unknown-{role}-organization", org_id))
            continue
        reference = _organization(organization)
        if reference is None:
            warnings.append(MappingWarning(f"{role}-without-name", org_id))
            continue
        resolved.append(reference)
    return tuple(resolved)


def _organization(organization: TedOrganization) -> OrganizationRef | None:
    """La mention brute, sans enrichissement : aucun registre n'est interrogé.

    Sans raison sociale publiée, aucune organisation n'est produite : un
    identifiant technique (`ORG-0003`) n'est pas un nom d'entreprise.
    """
    if not organization.name:
        return None
    identifiers = ()
    if organization.company_id:
        identifiers = (
            OrganizationIdentifier(
                # Le référentiel n'est presque jamais nommé par la source (`schemeName`
                # absent 180 fois sur 185) : on nomme donc l'origine du champ, pas un
                # registre qu'on ne connaît pas.
                scheme=organization.company_id_scheme or "TED-BT-501",
                value=organization.company_id,
            ),
        )
    address = ", ".join(
        part for part in (organization.street, organization.postal_zone, organization.city) if part
    )
    return OrganizationRef(
        legal_name=organization.name,
        identifiers=identifiers,
        country=alpha2(organization.country),
        address=address or None,
        website=organization.website,
    )


def _place(lot: TedLot | None, warnings: list[MappingWarning]) -> Location | None:
    """Le lieu d'exécution, ou rien — jamais une notice perdue pour un code inconnu.

    La table de conversion couvre l'espace européen. Un marché exécuté ailleurs
    (`CRI` pour le Costa Rica, rencontré sur la notice 565997-2026) n'a donc pas
    de pays convertible : si rien d'autre ne subsiste, le lieu vaut `None` et
    l'écart est signalé. Faire échouer l'attribution pour cela reviendrait à
    perdre des faits publiés à cause d'un champ accessoire.
    """
    if lot is None:
        return None
    country = alpha2(lot.country)
    if lot.country and not country:
        warnings.append(MappingWarning("unknown-country-code", lot.country))
    if not any((country, lot.nuts, lot.city, lot.postal_zone)):
        return None
    return Location(
        country=country,
        subdivision_code=lot.nuts,
        subdivision_scheme="NUTS" if lot.nuts else None,
        locality=lot.city,
        postal_code=lot.postal_zone,
    )


def _duration(lot: TedLot | None) -> Duration | None:
    """BT-36 seulement. Une durée déduite de start/end serait une inférence."""
    if lot is None:
        return None
    unit = _DURATION_UNITS.get((lot.duration_unit or "").upper())
    if lot.duration_value and unit:
        return Duration(value=lot.duration_value, unit=unit)
    return None


def _date(raw: str | None) -> dt.date | None:
    return dt.date.fromisoformat(raw) if raw else None


def _pick_language(texts: dict[str, str], language: str | None) -> str | None:
    """Langue de l'avis si disponible, sinon la première publiée — jamais de traduction."""
    if not texts:
        return None
    if language and language in texts:
        return texts[language]
    return next(iter(texts.values()))
