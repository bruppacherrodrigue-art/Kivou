"""BOAMP — de l'avis publié au modèle canonique.

Le BOAMP diffuse son catalogue via l'API Opendatasoft du domaine
`boamp-datadila.opendatasoft.com`. Chaque enregistrement porte ses métadonnées
plates (`idweb`, `dateparution`, `nomacheteur`, …) et, dans `donnees`, le
document d'origine sérialisé en JSON.

    Quatre formes coexistent réellement dans le flux
    ────────────────────────────────────────────────
    EFORMS     avis eForms complet — la même norme que TED
    FNSimple   avis national simplifié
    MAPA       avis de marché à procédure adaptée

Seul `EFORMS` est adapté ici, et le refus des trois autres est délibéré.
`FNSimple` enferme le gagnant, son SIRET, le montant et la date de notification
dans **une seule phrase libre** :

    « Lot 1 : … - GRAGLIA BTP (43293695300012) Notifié le 05/06/2026
      Montant : 213400.41 euros »

En extraire des faits serait de l'inférence sur du texte, pas de l'adaptation ;
et un fait inféré n'a pas de provenance opposable. L'avis est donc compté et
écarté, jamais deviné.

    Le champ piège
    ──────────────
    `cac:TenderResult/cbc:AwardDate` porte le nom exact de ce qu'on cherche, est
    présent sur 100 % des avis eForms du BOAMP — et vaut `2000-01-01` ou
    `1970-01-01` dans 96 % des cas mesurés (SPEC-009E §19). Il n'est **jamais**
    lu. La date de décision d'attribution vient exclusivement de
    `efac:SettledContract/cbc:AwardDate`, BT-1451, la même que Kivou lit déjà
    sur TED.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from signals.domain.awards import Awardee, AwardeeParty, ContractAward, LotRef
from signals.domain.events import Provenance, PublicEvent, TenderNotice
from signals.domain.values import CpvCode, Location, Money, OrganizationIdentifier, OrganizationRef

BOAMP_SOURCE_SYSTEM = "boamp"
BOAMP_SOURCE_COUNTRY = "FR"
BOAMP_ADAPTER_VERSION = "boamp-adapter-v0.1"

#: Le chemin de l'extension eForms, invariant d'un avis à l'autre.
_EXTENSION_PATH = (
    "ext:UBLExtensions",
    "ext:UBLExtension",
    "ext:ExtensionContent",
    "efext:EformsExtension",
)

#: `nature` des avis d'attribution dans le catalogue BOAMP.
AWARD_NATURES = frozenset({"ATTRIBUTION"})

_SIRET = re.compile(r"^\d{14}$")
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


class BoampUnsupportedPayload(ValueError):
    """L'avis n'est pas de la forme eForms — il est écarté, pas interprété."""


def _listed(value: Any) -> list[Any]:
    """L'API rend un objet quand il y en a un, une liste quand il y en a plusieurs."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str | None:
    """Le contenu d'un nœud, qu'il soit une chaîne nue ou un objet `{@attr, #text}`."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("#text")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(value: Any) -> dt.date | None:
    """Une date eForms — `2026-07-17+02:00` — réduite au jour publié.

    Le décalage horaire est celui de l'émetteur de l'avis, pas une heure
    d'événement : le conserver donnerait une précision que la source ne
    revendique pas.
    """
    text = _text(value)
    if text is None:
        return None
    match = _DATE_PREFIX.match(text)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _dig(node: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(node, list):
            node = node[0] if node else None
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _payload(record: dict) -> dict | None:
    """Le document eForms d'un enregistrement, ou `None` si l'avis a une autre forme."""
    raw = record.get("donnees")
    if not raw:
        return None
    try:
        document = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    notice = _dig(document, "EFORMS", "ContractAwardNotice")
    return notice if isinstance(notice, dict) else None


def _tender_payload(record: dict) -> dict | None:
    raw = record.get("donnees")
    if not raw:
        return None
    try:
        document = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    notice = _dig(document, "EFORMS", "ContractNotice")
    return notice if isinstance(notice, dict) else None


def supported_payload(record: dict) -> bool:
    """L'avis porte-t-il un document eForms exploitable ?"""
    return _payload(record) is not None


def supported_tender_payload(record: dict) -> bool:
    return record.get("nature") != "ATTRIBUTION" and _tender_payload(record) is not None


def _document_urls(node: Any) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "cbc:URI":
                candidate = _text(value)
                if candidate:
                    candidate = html.unescape(candidate)
                    if candidate.startswith(("http://", "https://")) and candidate not in found:
                        found.append(candidate)
            else:
                found.extend(url for url in _document_urls(value) if url not in found)
    elif isinstance(node, list):
        for value in node:
            found.extend(url for url in _document_urls(value) if url not in found)
    return tuple(found)


def parse_tender_notice(
    record: dict, *, retrieved_at: dt.datetime | None = None
) -> TenderNotice:
    """Adapte un AAPC eForms BOAMP sans fabriquer de contrat ni de fait absent."""
    notice = _tender_payload(record)
    if notice is None or record.get("nature") == "ATTRIBUTION":
        raise BoampUnsupportedPayload("avis BOAMP non AAPC eForms")
    idweb = _text(record.get("idweb"))
    if not idweb:
        raise BoampUnsupportedPayload("avis BOAMP sans `idweb`")
    extension: Any = notice
    for key in _EXTENSION_PATH:
        extension = _dig(extension, key)
    organizations = _Organizations.from_extension(extension if isinstance(extension, dict) else {})
    event = PublicEvent(
        provenance=Provenance(
            source_system=BOAMP_SOURCE_SYSTEM,
            source_country=BOAMP_SOURCE_COUNTRY,
            source_notice_id=idweb,
            source_procedure_id=_text(record.get("contractfolderid"))
            or _text(notice.get("cbc:ContractFolderID")),
            source_url=_text(record.get("url_avis")),
            retrieved_at=retrieved_at,
        ),
        event_type="tender_notice",
        published_at=_date(record.get("dateparution")),
        procedure_buyers=_buyers(notice, organizations),
        related_notice_ids=tuple(
            value
            for value in (_text(item) for item in _listed(record.get("annonce_lie")))
            if value
        ),
    )
    deadline = _text(record.get("datelimitereponse"))
    parsed_deadline = dt.datetime.fromisoformat(deadline) if deadline else None
    cpv = _cpv(notice)
    return TenderNotice(
        event=event,
        title=_text(record.get("objet")),
        cpv_main=cpv.code if cpv else None,
        submission_deadline=parsed_deadline,
        document_urls=_document_urls(notice),
    )


def payload_kind(record: dict) -> str:
    """La forme réelle de l'avis — utile pour compter ce qui est écarté."""
    raw = record.get("donnees")
    if not raw:
        return "empty"
    try:
        document = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return "unparseable"
    if not isinstance(document, dict) or not document:
        return "unparseable"
    if "EFORMS" in document:
        return "EFORMS"
    return next(iter(document))


@dataclasses.dataclass(frozen=True)
class _Organizations:
    """L'annuaire interne de l'avis : `ORG-0003` → l'organisation qu'il désigne."""

    by_ref: dict[str, OrganizationRef]

    @classmethod
    def from_extension(cls, extension: dict) -> _Organizations:
        by_ref: dict[str, OrganizationRef] = {}
        for block in _listed(_dig(extension, "efac:Organizations")):
            for organization in _listed(_dig(block, "efac:Organization")):
                company = _dig(organization, "efac:Company")
                if not isinstance(company, dict):
                    continue
                ref = _text(_dig(company, "cac:PartyIdentification", "cbc:ID"))
                name = _text(_dig(company, "cac:PartyName", "cbc:Name"))
                if not ref or not name:
                    continue
                by_ref[ref] = OrganizationRef(
                    legal_name=name,
                    identifiers=_identifiers(company),
                    country=_country(company),
                    address=_address(company),
                    website=_text(company.get("cbc:WebsiteURI")),
                )
        return cls(by_ref=by_ref)

    def get(self, ref: str | None) -> OrganizationRef | None:
        return self.by_ref.get(ref) if ref else None


def _identifiers(company: dict) -> tuple[OrganizationIdentifier, ...]:
    """Le `CompanyID` publié, nommé pour ce qu'il est.

    BOAMP y met tantôt un SIRET à quatorze chiffres, tantôt un identifiant
    interne annoncé `@schemeName="eu"`. Les distinguer ici évite d'aller
    chercher un SIRET dans un champ qui n'en porte pas.
    """
    raw = _dig(company, "cac:PartyLegalEntity", "cbc:CompanyID")
    value = _text(raw)
    if not value:
        return ()
    declared = raw.get("@schemeName") if isinstance(raw, dict) else None
    scheme = "SIRET" if _SIRET.fullmatch(value) else (declared or "BOAMP-COMPANY-ID")
    return (OrganizationIdentifier(scheme=str(scheme), value=value),)


def _country(company: dict) -> str | None:
    code = _text(_dig(company, "cac:PostalAddress", "cac:Country", "cbc:IdentificationCode"))
    # eForms code les pays en ISO 3166-1 alpha-3 ; le domaine canonique attend alpha-2.
    return {"FRA": "FR"}.get(code or "", None) or (code[:2] if code and len(code) == 3 else code)


def _address(company: dict) -> str | None:
    address = _dig(company, "cac:PostalAddress")
    if not isinstance(address, dict):
        return None
    parts = [
        _text(address.get("cbc:StreetName")),
        _text(address.get("cbc:PostalZone")),
        _text(address.get("cbc:CityName")),
    ]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _money(node: Any) -> Money | None:
    amount = _dig(node, "cac:LegalMonetaryTotal", "cbc:PayableAmount")
    text = _text(amount)
    currency = amount.get("@currencyID") if isinstance(amount, dict) else None
    if text is None or not currency:
        return None
    try:
        return Money(amount=Decimal(text), currency=str(currency))
    except (InvalidOperation, ValueError):
        return None


def _cpv(notice: dict) -> CpvCode | None:
    code = _text(
        _dig(
            notice,
            "cac:ProcurementProject",
            "cac:MainCommodityClassification",
            "cbc:ItemClassificationCode",
        )
    )
    if not code:
        return None
    # Le CPV français est souvent publié avec sa clé de contrôle : `45421000-4`.
    root, _, check = code.partition("-")
    if not root.isdigit() or len(root) != 8:
        return None
    return CpvCode(code=root, check_digit=check if check.isdigit() and len(check) == 1 else None)


def _place(notice: dict) -> Location | None:
    address = _dig(notice, "cac:ProcurementProject", "cac:RealizedLocation", "cac:Address")
    if not isinstance(address, dict):
        return None
    nuts = _text(address.get("cbc:CountrySubentityCode"))
    city = _text(address.get("cbc:CityName"))
    postal = _text(address.get("cbc:PostalZone"))
    country = _text(_dig(address, "cac:Country", "cbc:IdentificationCode"))
    country = {"FRA": "FR"}.get(country or "", country)
    if not any((nuts, city, postal, country)):
        return None
    return Location(
        country=country if country and len(country) == 2 else None,
        subdivision_code=nuts,
        subdivision_scheme="NUTS" if nuts else None,
        locality=city,
        postal_code=postal,
    )


def parse_award_notice(
    record: dict, *, retrieved_at: dt.datetime | None = None
) -> tuple[PublicEvent, tuple[ContractAward, ...]]:
    """Un enregistrement BOAMP → un `PublicEvent` et ses `ContractAward`.

    Un contrat attribué par lot : la chaîne eForms est
    `LotResult → LotTender → TenderingParty → Tenderer → Organizations`, et
    c'est elle qui nomme le gagnant. Aucun rapprochement par nom n'a lieu.
    """
    notice = _payload(record)
    if notice is None:
        raise BoampUnsupportedPayload(
            f"avis BOAMP {record.get('idweb')!r} de forme {payload_kind(record)!r} : "
            "seul le format eForms est adapté (les autres enferment les faits "
            "dans du texte libre)"
        )

    extension: Any = notice
    for key in _EXTENSION_PATH:
        extension = _dig(extension, key)
    extension = extension if isinstance(extension, dict) else {}
    organizations = _Organizations.from_extension(extension)
    notice_result = _dig(extension, "efac:NoticeResult") or {}

    idweb = _text(record.get("idweb"))
    if not idweb:
        raise BoampUnsupportedPayload("avis BOAMP sans `idweb` : aucune identité de notice")

    provenance = Provenance(
        source_system=BOAMP_SOURCE_SYSTEM,
        source_country=BOAMP_SOURCE_COUNTRY,
        source_notice_id=idweb,
        source_procedure_id=_text(record.get("contractfolderid"))
        or _text(notice.get("cbc:ContractFolderID")),
        source_url=_text(record.get("url_avis")),
        retrieved_at=retrieved_at,
    )
    event = PublicEvent(
        provenance=provenance,
        event_type="award_notice",
        published_at=_date(record.get("dateparution")),
        procedure_buyers=_buyers(notice, organizations),
        related_notice_ids=tuple(
            value
            for value in (_text(item) for item in _listed(record.get("annonce_lie")))
            if value
        ),
    )

    contracts = {
        _text(_dig(node, "cbc:ID")): node
        for node in _listed(notice_result.get("efac:SettledContract"))
        if isinstance(node, dict)
    }
    tenders = {
        _text(_dig(node, "cbc:ID")): node
        for node in _listed(notice_result.get("efac:LotTender"))
        if isinstance(node, dict)
    }
    parties = {
        _text(_dig(node, "cbc:ID")): node
        for node in _listed(notice_result.get("efac:TenderingParty"))
        if isinstance(node, dict)
    }

    cpv = _cpv(notice)
    place = _place(notice)
    awards: list[ContractAward] = []
    for result in _listed(notice_result.get("efac:LotResult")):
        if not isinstance(result, dict):
            continue
        contract = contracts.get(_text(_dig(result, "efac:SettledContract", "cbc:ID")))
        tender = tenders.get(_text(_dig(result, "efac:LotTender", "cbc:ID")))
        awards.append(
            _award(
                event=event,
                result=result,
                contract=contract,
                tender=tender,
                parties=parties,
                organizations=organizations,
                cpv=cpv,
                place=place,
            )
        )
    return event, tuple(awards)


def _buyers(notice: dict, organizations: _Organizations) -> tuple[OrganizationRef, ...]:
    """Les acheteurs de la procédure, désignés par référence dans `cac:ContractingParty`."""
    found: list[OrganizationRef] = []
    for party in _listed(notice.get("cac:ContractingParty")):
        ref = _text(_dig(party, "cac:Party", "cac:PartyIdentification", "cbc:ID"))
        organization = organizations.get(ref)
        if organization and organization not in found:
            found.append(organization)
    return tuple(found)


def _award(
    *,
    event: PublicEvent,
    result: dict,
    contract: dict | None,
    tender: dict | None,
    parties: dict,
    organizations: _Organizations,
    cpv: CpvCode | None,
    place: Location | None,
) -> ContractAward:
    winners: list[Awardee] = []
    if tender is not None:
        party = parties.get(_text(_dig(tender, "efac:TenderingParty", "cbc:ID")))
        for tenderer in _listed(_dig(party, "efac:Tenderer")) if party else []:
            organization = organizations.get(_text(_dig(tenderer, "cbc:ID")))
            if organization is not None:
                winners.append(Awardee(organization=organization, role="sole"))

    if len(winners) > 1:
        winners = [
            Awardee(organization=member.organization, role="consortium_member")
            for member in winners
        ]

    lot_identifier = _text(_dig(result, "efac:TenderLot", "cbc:ID"))
    return ContractAward(
        event_ref=event.ref(),
        source_award_id=_text(_dig(contract, "cbc:ID")) if contract else None,
        lot=LotRef(identifier=lot_identifier) if lot_identifier else None,
        contract_reference=_text(_dig(contract, "efac:ContractReference", "cbc:ID"))
        if contract
        else None,
        title=_text(_dig(contract, "cbc:Title")) if contract else None,
        cpv_main=cpv,
        value=_money(tender) if tender else None,
        winner_status="identified" if winners else "undisclosed",
        awardee_parties=(AwardeeParty(members=tuple(winners)),) if winners else (),
        place_of_performance=place,
        # BT-1451 — décision d'attribution. Jamais `cac:TenderResult/cbc:AwardDate`.
        award_date=_date(contract.get("cbc:AwardDate")) if contract else None,
        # BT-145 — conclusion du contrat. Un autre événement (§7).
        contract_signature_date=_date(contract.get("cbc:IssueDate")) if contract else None,
    )
