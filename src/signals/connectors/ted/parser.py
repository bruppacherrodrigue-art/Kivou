"""Lecture d'une notice eForms TED — structure seulement, aucune traduction.

Ce module produit une image fidèle du GRAPHE eForms tel qu'il est publié, en
conservant le vocabulaire TED (`LotResult`, `LotTender`, `SettledContract`,
`TenderingParty`). Il ne connaît pas le modèle canonique : la traduction vit
dans `mapping.py`, et c'est cette frontière qui empêche TED de contaminer le
domaine.

Il ne fonctionne que sur du XML, jamais sur le réseau : un fichier suffit à le
tester intégralement.

Structure réellement observée sur des Contract Award Notices (eForms SDK 1.13) :

    ContractAwardNotice
      cbc:ID[@schemeName=notice-id]        BT-701  identifiant de notice (UUID)
      cbc:VersionID                        BT-757  version de la notice
      cbc:ContractFolderID                 BT-04   identifiant de PROCÉDURE
      cbc:IssueDate + cbc:IssueTime        BT-05   envoi de l'avis
      cbc:NoticeTypeCode[@listName=result]         can-standard / can-social / ...
      cac:ContractingParty/…/cbc:ID                acheteur(s) → ORG-xxxx
      cac:ProcurementProjectLot[@schemeName=Lot]   lots (titre, CPV, lieu, période)
      ext:…/efac:NoticeResult
        efac:LotResult                     résultat par lot (statut, références)
        efac:LotTender                     offre (valeur BT-720, partie soumissionnaire)
        efac:SettledContract               contrat conclu (dates, BT-150, offre(s))
        efac:TenderingParty                soumissionnaire (1..n opérateurs)
        efac:Organizations                 fiches des organisations
        efac:Publication                   numéro et date de publication au JOUE
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from defusedxml import ElementTree as DefusedET

from signals.connectors.ted.errors import TedParseError

CAC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
CBC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
EFAC = "{http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1}"
EFBC = "{http://data.europa.eu/p27/eforms-ubl-extension-basic-components/1}"

_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


# ─── Fragments du graphe eForms ─────────────────────────────────────────────────


@dataclass(frozen=True)
class TedOrganization:
    """`efac:Organizations/efac:Organization/efac:Company`."""

    org_id: str
    name: str | None = None
    country: str | None = None  # alpha-3, tel que publié
    company_id: str | None = None  # BT-501
    company_id_scheme: str | None = None
    website: str | None = None
    street: str | None = None
    city: str | None = None
    postal_zone: str | None = None
    nuts: str | None = None


@dataclass(frozen=True)
class TedLot:
    """`cac:ProcurementProjectLot[cbc:ID/@schemeName='Lot']`."""

    lot_id: str
    titles: dict[str, str] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    cpv_main: str | None = None
    cpv_additional: tuple[str, ...] = ()
    country: str | None = None
    nuts: str | None = None
    city: str | None = None
    postal_zone: str | None = None
    start_date: str | None = None  # BT-536
    end_date: str | None = None  # BT-537
    duration_value: int | None = None  # BT-36
    duration_unit: str | None = None


@dataclass(frozen=True)
class TedTenderingParty:
    """`efac:TenderingParty` — un soumissionnaire, seul ou groupement."""

    party_id: str
    name: str | None = None
    tenderers: tuple[tuple[str, bool | None], ...] = ()  # (org_id, chef de file ?)


@dataclass(frozen=True)
class TedTender:
    """`efac:LotTender` — une offre déposée sur un lot."""

    tender_id: str
    lot_id: str | None = None
    tendering_party_id: str | None = None
    tender_reference: str | None = None  # BT-3201
    amount: str | None = None  # BT-720, texte brut
    currency: str | None = None
    rank: str | None = None


@dataclass(frozen=True)
class TedContract:
    """`efac:SettledContract` — un contrat effectivement conclu."""

    contract_id: str
    tender_ids: tuple[str, ...] = ()  # BT-3202
    contract_reference: str | None = None  # BT-150
    award_date: str | None = None  # BT-1451
    issue_date: str | None = None  # BT-145
    signatory_org_ids: tuple[str, ...] = ()
    framework: bool | None = None


@dataclass(frozen=True)
class TedLotResult:
    """`efac:LotResult` — l'issue d'un lot."""

    result_id: str
    lot_id: str | None = None
    winner_selection_status: str | None = None  # BT-142 : selec-w, clos-nw, open-nw
    tender_ids: tuple[str, ...] = ()
    contract_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TedNotice:
    """Une notice eForms complète, encore entièrement en vocabulaire TED."""

    notice_uuid: str
    version: str | None
    procedure_id: str | None  # BT-04, partagé par tous les avis d'une procédure
    notice_type: str | None
    notice_subtype: str | None
    language: str | None
    issue_date: str | None
    issue_time: str | None
    publication_number: str | None
    publication_date: str | None
    gazette_id: str | None
    buyer_org_ids: tuple[str, ...]
    organizations: dict[str, TedOrganization]
    lots: dict[str, TedLot]
    lot_results: tuple[TedLotResult, ...]
    tenders: dict[str, TedTender]
    tendering_parties: dict[str, TedTenderingParty]
    contracts: tuple[TedContract, ...]


# ─── Lecture ────────────────────────────────────────────────────────────────────


def _text(node: Any, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def _iso_date(raw: str | None) -> str | None:
    """eForms date le tout avec un décalage (`2026-05-11+02:00`) sans jamais d'heure.

    On garde la date seule : ajouter une heure serait inventer une précision que
    la source ne donne pas.
    """
    if not raw:
        return None
    match = _ISO_DATE.match(raw.strip())
    return match.group(1) if match else None


def _i18n(node: Any, path: str) -> dict[str, str]:
    """Collecte les variantes linguistiques d'un texte (`@languageID`)."""
    out: dict[str, str] = {}
    for element in node.findall(path):
        if element.text and element.text.strip():
            out[element.get("languageID") or ""] = element.text.strip()
    return out


def _refs(node: Any, path: str) -> tuple[str, ...]:
    return tuple(e.text.strip() for e in node.findall(path) if e.text and e.text.strip())


def parse_notice(xml: str | bytes) -> TedNotice:
    """Lit une Contract Award Notice eForms. Lève `TedParseError` si inexploitable."""
    try:
        root = DefusedET.fromstring(xml)
    except Exception as exc:  # toute erreur XML est un refus net, sans exception
        raise TedParseError(f"XML illisible : {exc}") from exc

    if not root.tag.endswith("}ContractAwardNotice"):
        raise TedParseError(f"racine inattendue : {root.tag} (attendu ContractAwardNotice)")

    notice_uuid = _text(root, f"{CBC}ID")
    if not notice_uuid:
        raise TedParseError("notice sans identifiant (cbc:ID)")

    result = root.find(f".//{EFAC}NoticeResult")
    if result is None:
        raise TedParseError("notice sans efac:NoticeResult — pas un avis de résultat")

    publication = root.find(f".//{EFAC}Publication")

    return TedNotice(
        notice_uuid=notice_uuid,
        version=_text(root, f"{CBC}VersionID"),
        procedure_id=_text(root, f"{CBC}ContractFolderID"),
        notice_type=_text(root, f"{CBC}NoticeTypeCode"),
        notice_subtype=_text(root, f".//{EFAC}NoticeSubType/{CBC}SubTypeCode"),
        language=_text(root, f"{CBC}NoticeLanguageCode"),
        issue_date=_iso_date(_text(root, f"{CBC}IssueDate")),
        issue_time=_text(root, f"{CBC}IssueTime"),
        publication_number=_publication_number(publication),
        publication_date=_iso_date(_text(publication, f"{EFBC}PublicationDate")),
        gazette_id=_text(publication, f"{EFBC}GazetteID"),
        buyer_org_ids=_refs(
            root, f"{CAC}ContractingParty/{CAC}Party/{CAC}PartyIdentification/{CBC}ID"
        ),
        organizations=_organizations(root),
        lots=_lots(root),
        lot_results=_lot_results(result),
        tenders=_tenders(result),
        tendering_parties=_tendering_parties(result),
        contracts=_contracts(result),
    )


def _publication_number(publication: Any) -> str | None:
    """`00550374-2026` est publié zéro-préfixé ; TED l'expose partout en `550374-2026`."""
    raw = _text(publication, f"{EFBC}NoticePublicationID")
    return raw.lstrip("0") if raw else None


def _organizations(root: Any) -> dict[str, TedOrganization]:
    out: dict[str, TedOrganization] = {}
    for company in root.findall(f".//{EFAC}Organizations/{EFAC}Organization/{EFAC}Company"):
        org_id = _text(company, f"{CAC}PartyIdentification/{CBC}ID")
        if not org_id:
            continue
        company_id_node = company.find(f"{CAC}PartyLegalEntity/{CBC}CompanyID")
        address = f"{CAC}PostalAddress"
        out[org_id] = TedOrganization(
            org_id=org_id,
            name=_text(company, f"{CAC}PartyName/{CBC}Name"),
            country=_text(company, f"{address}/{CAC}Country/{CBC}IdentificationCode"),
            company_id=(company_id_node.text or "").strip() or None
            if company_id_node is not None
            else None,
            company_id_scheme=company_id_node.get("schemeName")
            if company_id_node is not None
            else None,
            website=_text(company, f"{CBC}WebsiteURI"),
            street=_text(company, f"{address}/{CBC}StreetName"),
            city=_text(company, f"{address}/{CBC}CityName"),
            postal_zone=_text(company, f"{address}/{CBC}PostalZone"),
            nuts=_text(company, f"{address}/{CBC}CountrySubentityCode"),
        )
    return out


def _lots(root: Any) -> dict[str, TedLot]:
    """Seuls les vrais lots. Un `LotsGroup` partage la balise mais n'est pas un lot."""
    out: dict[str, TedLot] = {}
    for lot in root.findall(f"{CAC}ProcurementProjectLot"):
        identifier = lot.find(f"{CBC}ID")
        if identifier is None or identifier.get("schemeName") != "Lot":
            continue
        lot_id = (identifier.text or "").strip()
        if not lot_id:
            continue
        project = lot.find(f"{CAC}ProcurementProject")
        period = lot.find(f"{CAC}ProcurementProject/{CAC}PlannedPeriod")
        duration = period.find(f"{CBC}DurationMeasure") if period is not None else None
        address = f"{CAC}RealizedLocation/{CAC}Address"
        out[lot_id] = TedLot(
            lot_id=lot_id,
            titles=_i18n(project, f"{CBC}Name") if project is not None else {},
            descriptions=_i18n(project, f"{CBC}Description") if project is not None else {},
            cpv_main=_text(
                project, f"{CAC}MainCommodityClassification/{CBC}ItemClassificationCode"
            ),
            cpv_additional=_refs(
                project, f"{CAC}AdditionalCommodityClassification/{CBC}ItemClassificationCode"
            )
            if project is not None
            else (),
            country=_text(project, f"{address}/{CAC}Country/{CBC}IdentificationCode"),
            nuts=_text(project, f"{address}/{CBC}CountrySubentityCode"),
            city=_text(project, f"{address}/{CBC}CityName"),
            postal_zone=_text(project, f"{address}/{CBC}PostalZone"),
            start_date=_iso_date(_text(period, f"{CBC}StartDate")),
            end_date=_iso_date(_text(period, f"{CBC}EndDate")),
            duration_value=int(duration.text)
            if duration is not None and (duration.text or "").strip().isdigit()
            else None,
            duration_unit=duration.get("unitCode") if duration is not None else None,
        )
    return out


def _lot_results(result: Any) -> tuple[TedLotResult, ...]:
    out = []
    for node in result.findall(f"{EFAC}LotResult"):
        result_id = _text(node, f"{CBC}ID")
        if not result_id:
            continue
        out.append(
            TedLotResult(
                result_id=result_id,
                lot_id=_text(node, f"{EFAC}TenderLot/{CBC}ID"),
                winner_selection_status=_text(node, f"{CBC}TenderResultCode"),
                tender_ids=_refs(node, f"{EFAC}LotTender/{CBC}ID"),
                contract_ids=_refs(node, f"{EFAC}SettledContract/{CBC}ID"),
            )
        )
    return tuple(out)


def _tenders(result: Any) -> dict[str, TedTender]:
    out: dict[str, TedTender] = {}
    for node in result.findall(f"{EFAC}LotTender"):
        tender_id = _text(node, f"{CBC}ID")
        if not tender_id:
            continue
        amount_node = node.find(f"{CAC}LegalMonetaryTotal/{CBC}PayableAmount")
        out[tender_id] = TedTender(
            tender_id=tender_id,
            lot_id=_text(node, f"{EFAC}TenderLot/{CBC}ID"),
            tendering_party_id=_text(node, f"{EFAC}TenderingParty/{CBC}ID"),
            tender_reference=_text(node, f"{EFAC}TenderReference/{CBC}ID"),
            amount=(amount_node.text or "").strip() or None if amount_node is not None else None,
            currency=amount_node.get("currencyID") if amount_node is not None else None,
            rank=_text(node, f"{CBC}RankCode"),
        )
    return out


def _tendering_parties(result: Any) -> dict[str, TedTenderingParty]:
    out: dict[str, TedTenderingParty] = {}
    for node in result.findall(f"{EFAC}TenderingParty"):
        party_id = _text(node, f"{CBC}ID")
        if not party_id:
            continue
        tenderers = []
        for tenderer in node.findall(f"{EFAC}Tenderer"):
            org_id = _text(tenderer, f"{CBC}ID")
            if not org_id:
                continue
            lead = _text(tenderer, f"{EFBC}GroupLeadIndicator")
            tenderers.append((org_id, None if lead is None else lead.lower() == "true"))
        out[party_id] = TedTenderingParty(
            party_id=party_id,
            name=_text(node, f"{CBC}Name"),
            tenderers=tuple(tenderers),
        )
    return out


def _contracts(result: Any) -> tuple[TedContract, ...]:
    out = []
    for node in result.findall(f"{EFAC}SettledContract"):
        contract_id = _text(node, f"{CBC}ID")
        if not contract_id:
            continue
        framework = _text(node, f"{EFBC}ContractFrameworkIndicator")
        out.append(
            TedContract(
                contract_id=contract_id,
                tender_ids=_refs(node, f"{EFAC}LotTender/{CBC}ID"),
                contract_reference=_text(node, f"{EFAC}ContractReference/{CBC}ID"),
                award_date=_iso_date(_text(node, f"{CBC}AwardDate")),
                issue_date=_iso_date(_text(node, f"{CBC}IssueDate")),
                signatory_org_ids=_refs(
                    node, f"{CAC}SignatoryParty/{CAC}PartyIdentification/{CBC}ID"
                ),
                framework=None if framework is None else framework.lower() == "true",
            )
        )
    return tuple(out)
