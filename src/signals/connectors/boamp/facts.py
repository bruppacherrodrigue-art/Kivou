"""Pure eForms facts extractor: exact graph joins and explicit text, never fetching."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from signals.client_value.notice_facts import (
    DEFAULT_SNAPSHOT_POLICY,
    DateFact,
    DecimalFact,
    DurationFact,
    IdentifierFact,
    MoneyFact,
    NoticeAwardFacts,
    NoticeFactRejection,
    NoticeFactsExtraction,
    NoticeFactSource,
    NoticeSourceSnapshot,
    OrganizationFacts,
    SnapshotPolicy,
    TextFact,
    WinningPartyFacts,
    prepare_notice_snapshot,
)
from signals.connectors.boamp.parser import BoampUnsupportedPayload
from signals.domain.awards import ContractAward
from signals.domain.events import PublicEvent
from signals.persistence.identity import award_key

BOAMP_FACTS_EXTRACTOR_VERSION = "boamp-notice-facts-v1"


@dataclasses.dataclass(frozen=True)
class _Node:
    value: Any
    path: str = ""

    def children(self, key: str) -> list[_Node]:
        if not isinstance(self.value, dict) or key not in self.value:
            return []
        value = self.value[key]
        path = self.path + "/" + key.replace("~", "~0").replace("/", "~1")
        return (
            [_Node(item, f"{path}/{index}") for index, item in enumerate(value)]
            if isinstance(value, list)
            else [_Node(value, path)]
        )

    def at(self, *keys: str) -> _Node:
        node = self
        for key in keys:
            candidates = node.children(key)
            node = candidates[0] if len(candidates) == 1 else _Node(None)
        return node

    def text(self) -> str | None:
        value = self.value.get("#text") if isinstance(self.value, dict) else self.value
        return (
            str(value).strip() or None
            if isinstance(value, (str, int)) and not isinstance(value, bool)
            else None
        )

    def fact(self) -> TextFact | None:
        value = self.text()
        return (
            TextFact(
                value=value,
                source_path=self.path + ("/#text" if isinstance(self.value, dict) else ""),
            )
            if value
            else None
        )


def _index(nodes: list[_Node], *id_path: str) -> dict[str, _Node | None]:
    indexed: dict[str, _Node | None] = {}
    for node in nodes:
        key = node.at(*(id_path or ("cbc:ID",))).text()
        if key:
            indexed[key] = None if key in indexed else node
    return indexed


def _refs(node: _Node, key: str) -> tuple[str, ...]:
    children = node.children(key)
    if not children and isinstance(node.value, dict) and key in node.value:
        raise ValueError("empty_source_reference")
    refs = tuple(child.at("cbc:ID").text() for child in children)
    if any(value is None for value in refs):
        raise ValueError("ambiguous_source_reference")
    return refs


def _matches_result(result: _Node, award: ContractAward) -> bool:
    try:
        return _refs(result, "efac:SettledContract") == (award.source_award_id,) and _refs(
            result, "efac:TenderLot"
        ) == (award.lot.identifier,)
    except ValueError:
        return False


def _appeal_refs(notice: _Node) -> set[str]:
    refs = set()
    for root in [notice, *notice.children("cac:ProcurementProjectLot")]:
        terms = root.at("cac:TenderingTerms", "cac:AppealTerms")
        for role in ("cac:AppealReceiverParty", "cac:AppealInformationParty", "cac:MediationParty"):
            for party in terms.children(role):
                value = party.at("cac:PartyIdentification", "cbc:ID").text()
                if value:
                    refs.add(value)
    return refs


def _money(node: _Node) -> MoneyFact | None:
    fact = node.fact()
    currency = node.at("@currencyID").text()
    if not fact or not currency:
        return None
    try:
        return MoneyFact(
            value=fact.value,
            source_path=fact.source_path,
            currency=currency,
            currency_source_path=node.path + "/@currencyID",
        )
    except ValidationError:
        return None


def _duration(project: _Node, *, scope: str = "contract") -> DurationFact | None:
    node = project.at("cac:PlannedPeriod", "cbc:DurationMeasure")
    fact = node.fact()
    if fact is None:
        return None
    try:
        return DurationFact(
            value=fact.value,
            source_path=fact.source_path,
            unit=node.at("@unitCode").text(),
            unit_source_path=node.path + "/@unitCode",
            scope=scope,
        )
    except ValidationError:
        return None


def _renewals(project: _Node) -> DecimalFact | None:
    fact = project.at("cac:ContractExtension", "cbc:MaximumNumberNumeric").fact()
    if not fact or not re.fullmatch(r"\d+", fact.value):
        return None
    return DecimalFact(**fact.model_dump())


_NUMBERS = {
    "un": "1",
    "une": "1",
    "deux": "2",
    "trois": "3",
    "quatre": "4",
    "cinq": "5",
    "six": "6",
    "sept": "7",
    "huit": "8",
    "neuf": "9",
    "dix": "10",
}
_NUMBER = r"(?P<value>\d+(?:[.,]\d+)?|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)"
_UNIT = r"\s+(?P<unit>mois|années?|ans?|semaines?|jours?)\b"
_INITIAL = re.compile(
    r"(?:durée\s*(?:initiale|\(hors reconduction\))\s*(?::|est de|de)?\s*|première période d[’'](?:une?\s+)?)(?P<value>\d+(?:[.,]\d+)?|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)"
    + _UNIT,
    re.IGNORECASE,
)
_MAXIMUM = re.compile(
    r"durée\s+(?:totale(?:\s+maximale)?|maximale)\s*(?:du marché|du contrat)?\s*(?:ne\s+(?:puisse|peut|pourra)\s+excéder|est de|:)\s*"
    + _NUMBER
    + _UNIT,
    re.IGNORECASE,
)
_ORDER = re.compile(
    r"durée maximale d[’']exécution des bons de commande est de\s*" + _NUMBER + _UNIT, re.IGNORECASE
)
_RENEWALS = re.compile(
    r"(?:nombre de reconductions(?: éventuelles)?\s*:\s*|(?:reconductible|renouvelable)\s+)"
    + _NUMBER
    + r"(?:\s+fois)?\b",
    re.IGNORECASE,
)


def _scope(project: _Node) -> str:
    description = project.at("cbc:Description").text() or ""
    broad_contract = re.search(
        r"accord[ -]cadre|marché de partenariat|financement|maintenance", description, re.IGNORECASE
    )
    return (
        "works"
        if project.at("cbc:ProcurementTypeCode").text() == "works" and not broad_contract
        else "contract"
    )


def _text_durations(
    project: _Node, pattern: re.Pattern, *, scope: str, period: str
) -> list[DurationFact]:
    found = []
    for field in ("cbc:Description", "cbc:Note"):
        text = project.at(field).fact()
        if text is None or len(text.value) > 20000:
            continue
        for match in pattern.finditer(text.value):
            value = match.group("value").lower()
            value = _NUMBERS.get(value, value.replace(",", "."))
            unit = match.group("unit").lower()
            unit = (
                "MONTH"
                if unit == "mois"
                else "YEAR"
                if unit.startswith("an")
                else "WEEK"
                if unit.startswith("semaine")
                else "DAY"
            )
            if Decimal(value) == 0:
                continue
            found.append(
                DurationFact(
                    value=value,
                    unit=unit,
                    scope=scope,
                    period_kind=period,
                    source_path=text.source_path,
                    unit_source_path=text.source_path,
                    source_excerpt=match.group(0),
                )
            )
    return found


def _unique_duration(values: list[DurationFact]) -> DurationFact | None:
    return (
        values[0]
        if values and len({(item.value, item.unit, item.scope) for item in values}) == 1
        else None
    )


def _duration_data(project: _Node, snapshot: NoticeSourceSnapshot, *, notice_kind: str) -> dict:
    scope = _scope(project)
    initial = _unique_duration(_text_durations(project, _INITIAL, scope=scope, period="initial"))
    maximum = _unique_duration(_text_durations(project, _MAXIMUM, scope=scope, period="maximum"))
    purchase_order = _unique_duration(
        _text_durations(project, _ORDER, scope="purchase_order", period="maximum")
    )
    structured = _duration(project, scope=scope)
    renewals = _renewals(project)
    textual_renewals = []
    for field in ("cbc:Description", "cbc:Note"):
        text = project.at(field).fact()
        if text and len(text.value) <= 20000:
            for match in _RENEWALS.finditer(text.value):
                number = match.group("value").lower()
                value = _NUMBERS.get(number, number)
                if re.fullmatch(r"\d+", value):
                    textual_renewals.append(
                        DecimalFact(
                            value=value, source_path=text.source_path, source_excerpt=match.group(0)
                        )
                    )
    candidates = ([renewals] if renewals else []) + textual_renewals
    renewals = (
        candidates[0] if candidates and len({item.value for item in candidates}) == 1 else None
    )
    values = {
        "duration": initial or structured or purchase_order or maximum,
        "initial_duration": initial,
        "maximum_duration": maximum or purchase_order,
        "maximum_renewals": renewals,
    }
    return {
        key: value.model_copy(
            update={
                "source_notice_id": snapshot.source_notice_id,
                "source_url": snapshot.source_url,
                "notice_kind": notice_kind,
                "source_snapshot_key": snapshot.snapshot_key,
            }
        )
        if value
        else None
        for key, value in values.items()
    }


def _procedure(record: dict, notice: _Node) -> str | None:
    values = {
        value
        for value in (
            _Node(record).at("contractfolderid").text(),
            notice.at("cbc:ContractFolderID").text(),
        )
        if value
    }
    return next(iter(values)) if len(values) == 1 else None


def _related_duration_data(
    record: dict,
    notice: _Node,
    event: PublicEvent,
    lot_id: str,
    buyers: tuple[OrganizationFacts, ...],
    related_records: tuple[dict, ...],
    *,
    collected_at: dt.datetime,
    policy: SnapshotPolicy,
    source_snapshots: dict[str, NoticeSourceSnapshot],
) -> tuple[dict, NoticeSourceSnapshot] | None:
    matches = []
    procedure = _procedure(record, notice)
    business_ref = notice.at("cac:ProcurementProject", "cbc:ID").text()
    buyer_ids = {(item.scheme, item.value) for buyer in buyers for item in buyer.identifiers}
    for related in related_records:
        if related.get("idweb") not in event.source_notice_links:
            continue
        raw = related.get("donnees")
        try:
            raw = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        tender = _Node(raw, "/donnees").at("EFORMS", "ContractNotice")
        if (
            not isinstance(tender.value, dict)
            or not procedure
            or _procedure(related, tender) != procedure
        ):
            continue
        if not business_ref or tender.at("cac:ProcurementProject", "cbc:ID").text() != business_ref:
            continue
        try:
            if dt.date.fromisoformat(related["dateparution"][:10]) >= dt.date.fromisoformat(
                record["dateparution"][:10]
            ):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        ext = tender.at(
            "ext:UBLExtensions", "ext:UBLExtension", "ext:ExtensionContent", "efext:EformsExtension"
        )
        organizations = _index(
            [
                org.at("efac:Company")
                for block in ext.children("efac:Organizations")
                for org in block.children("efac:Organization")
            ],
            "cac:PartyIdentification",
            "cbc:ID",
        )
        prior_buyers = []
        for party in tender.children("cac:ContractingParty"):
            ref = party.at("cac:Party", "cac:PartyIdentification", "cbc:ID").text()
            if (org := organizations.get(ref)) and (buyer := _organization(org, winner=False)):
                prior_buyers.append(buyer)
        prior_ids = {
            (item.scheme, item.value) for buyer in prior_buyers for item in buyer.identifiers
        }
        if not buyer_ids or prior_ids != buyer_ids:
            continue
        lot = _index(tender.children("cac:ProcurementProjectLot")).get(lot_id)
        if lot is None:
            continue
        snapshot = source_snapshots[related["idweb"]]
        data = _duration_data(
            lot.at("cac:ProcurementProject"), snapshot, notice_kind="contract_notice"
        )
        if data["duration"] is not None:
            matches.append((data, snapshot))
    return matches[0] if len(matches) == 1 else None


def _organization(node: _Node, *, winner: bool) -> OrganizationFacts | None:
    identity = node.at("cac:PartyIdentification", "cbc:ID").fact()
    name = node.at("cac:PartyName", "cbc:Name").fact()
    if not identity or not name:
        return None
    identifiers = []
    for entity in node.children("cac:PartyLegalEntity"):
        identifier_node = entity.at("cbc:CompanyID")
        identifier = identifier_node.fact()
        if identifier:
            compact = re.sub(r"\s+", "", identifier.value)
            siret = bool(re.fullmatch(r"\d{14}", compact))
            identifiers.append(
                IdentifierFact(
                    value=compact if siret else identifier.value,
                    source_path=identifier.source_path,
                    scheme="SIRET"
                    if siret
                    else identifier_node.at("@schemeName").text() or "BOAMP-COMPANY-ID",
                )
            )
    return OrganizationFacts(
        organization_ref=identity.value,
        identity_source_path=identity.source_path,
        name=name,
        identifiers=tuple(identifiers),
        contact_name=node.at("cac:Contact", "cbc:Name").fact() if winner else None,
        email=node.at("cac:Contact", "cbc:ElectronicMail").fact() if winner else None,
        phone=node.at("cac:Contact", "cbc:Telephone").fact() if winner else None,
        website=node.at("cbc:WebsiteURI").fact() if winner else None,
    )


def _aligned_winners(award: ContractAward, parties: tuple[WinningPartyFacts, ...]) -> bool:
    expected = sorted(
        sorted(
            (
                member.organization.legal_name,
                tuple(
                    sorted((item.scheme, item.value) for item in member.organization.identifiers)
                ),
            )
            for member in party.members
        )
        for party in award.awardee_parties
    )
    actual = sorted(
        sorted(
            (
                member.name.value,
                tuple(sorted((item.scheme, item.value) for item in member.identifiers)),
            )
            for member in party.members
        )
        for party in parties
    )
    return bool(expected) and expected == actual


def prepare_related_notice_snapshot(
    record: dict, *, collected_at: dt.datetime, policy: SnapshotPolicy = DEFAULT_SNAPSHOT_POLICY
) -> NoticeSourceSnapshot:
    """Archive a looked-up source with its own clock, without adapting its facts."""
    raw = record.get("donnees")
    document = json.loads(raw) if isinstance(raw, str) else raw
    forms = _Node(document, "/donnees").at("EFORMS")
    notice = forms.at("ContractNotice")
    if notice.value is None:
        notice = forms.at("ContractAwardNotice")
    return prepare_notice_snapshot(
        record,
        source_notice_id=record.get("idweb"),
        notice_version=notice.at("cbc:VersionID").text(),
        source_url=_Node(record).at("url_avis").text(),
        collected_at=collected_at,
        policy=policy,
    )


def extract_boamp_notice_facts(
    record: dict,
    *,
    event: PublicEvent,
    awards: tuple[ContractAward, ...],
    collected_at: dt.datetime,
    policy: SnapshotPolicy = DEFAULT_SNAPSHOT_POLICY,
    extractor_version: str = BOAMP_FACTS_EXTRACTOR_VERSION,
    related_records: tuple[dict, ...] = (),
    related_source_snapshots: tuple[NoticeSourceSnapshot, ...] = (),
) -> NoticeFactsExtraction:
    """Enrich only exact parser identities; inconsistent awards get explicit rejections.

    ``cbc:DurationMeasure`` states a contract period, but does not say whether
    renewals are included. Keep ``period_kind=unspecified`` and the published
    maximum renewal count separately. Never multiply a duration or estimate a start.
    """
    if len(related_records) > 3 or len(related_source_snapshots) > 3:
        raise ValueError("at most three explicitly related notices may be supplied")
    raw = record.get("donnees")
    try:
        document = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as error:
        raise BoampUnsupportedPayload("invalid BOAMP eForms document") from error
    notice = _Node(document, "/donnees").at("EFORMS", "ContractAwardNotice")
    if not isinstance(notice.value, dict):
        raise BoampUnsupportedPayload("only supported BOAMP award eForms are extracted")
    notice_id = _Node(record).at("idweb").text()
    version = notice.at("cbc:VersionID").text()
    if (
        event.provenance.source_system != "boamp"
        or event.provenance.source_notice_id != notice_id
        or (
            event.provenance.notice_version is not None
            and event.provenance.notice_version != version
        )
    ):
        raise ValueError("event and source notice identity/version disagree")
    snapshot = prepare_notice_snapshot(
        record,
        source_notice_id=notice_id,
        notice_version=version,
        source_url=_Node(record).at("url_avis").text(),
        collected_at=collected_at,
        policy=policy,
    )
    source = NoticeFactSource(
        source_notice_id=notice_id,
        notice_version=version,
        content_hash=snapshot.content_hash,
        source_url=snapshot.source_url,
        collected_at=snapshot.collected_at,
        extractor_version=extractor_version,
    )
    ext = notice.at(
        "ext:UBLExtensions", "ext:UBLExtension", "ext:ExtensionContent", "efext:EformsExtension"
    )
    organizations = _index(
        [
            organization.at("efac:Company")
            for block in ext.children("efac:Organizations")
            for organization in block.children("efac:Organization")
        ],
        "cac:PartyIdentification",
        "cbc:ID",
    )
    result_root = ext.at("efac:NoticeResult")
    contracts = _index(result_root.children("efac:SettledContract"))
    tenders = _index(result_root.children("efac:LotTender"))
    parties = _index(result_root.children("efac:TenderingParty"))
    lots = _index(notice.children("cac:ProcurementProjectLot"))
    buyer_refs = {
        party.at("cac:Party", "cac:PartyIdentification", "cbc:ID").text()
        for party in notice.children("cac:ContractingParty")
    }
    buyers = tuple(
        organization
        for ref in sorted(value for value in buyer_refs if value)
        if (node := organizations.get(ref)) and (organization := _organization(node, winner=False))
    )
    excluded_refs = buyer_refs | _appeal_refs(notice)
    publication = _Node(record).at("dateparution").fact()
    published_on = None
    if publication and re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T+-])", publication.value):
        try:
            published_on = DateFact(
                value=dt.date.fromisoformat(publication.value[:10]),
                source_path=publication.source_path,
            )
        except ValueError:
            pass
    reason = ext.at("efac:Changes", "efac:ChangeReason", "cbc:ReasonCode").text()
    status = "notice_cancelled" if reason == "cancel" else "corrected" if reason else "published"
    accepted, rejected = [], []
    related_ids = tuple(sorted(set(event.source_notice_links) - {notice_id}))
    provided_snapshots = {item.source_notice_id: item for item in related_source_snapshots}
    related_snapshots = {}
    sources_by_id = {}
    for related_record in related_records:
        identity = related_record.get("idweb")
        if identity not in related_ids:
            continue
        cached = provided_snapshots.get(identity)
        prepared = prepare_related_notice_snapshot(
            related_record,
            collected_at=cached.collected_at if cached else collected_at,
            policy=policy,
        )
        if cached and (
            cached.snapshot_key != prepared.snapshot_key or cached.source_url != prepared.source_url
        ):
            raise ValueError("related_source_snapshot_alignment_mismatch")
        archived = cached or prepared
        related_snapshots[archived.snapshot_key] = archived
        sources_by_id[identity] = archived
    related_checked = set(related_ids).issubset(sources_by_id)
    for award in awards:
        key = award_key(award)
        try:
            if award.event_ref != event.ref() or not award.source_award_id or not award.lot:
                raise ValueError("award_event_identity_mismatch")
            matches = [
                node
                for node in result_root.children("efac:LotResult")
                if _matches_result(node, award)
            ]
            if len(matches) != 1:
                raise ValueError("ambiguous_lot_result")
            result = matches[0]
            selection = result.at("cbc:TenderResultCode").text()
            if selection and selection != "selec-w":
                raise ValueError("lot_result_not_awarded")
            contract = contracts.get(award.source_award_id)
            lot = lots.get(award.lot.identifier)
            if contract is None or lot is None:
                raise ValueError("unresolved_contract_or_lot")
            if _refs(contract, "efac:TenderLot") and _refs(contract, "efac:TenderLot") != (
                award.lot.identifier,
            ):
                raise ValueError("contract_lot_mismatch")
            tender_refs = _refs(result, "efac:LotTender")
            contract_refs = _refs(contract, "efac:LotTender")
            if not tender_refs or (contract_refs and set(contract_refs) != set(tender_refs)):
                raise ValueError("contract_tender_mismatch")
            winning = []
            tender_nodes = []
            for tender_ref in tender_refs:
                tender = tenders.get(tender_ref)
                if tender is None or (
                    _refs(tender, "efac:TenderLot")
                    and _refs(tender, "efac:TenderLot") != (award.lot.identifier,)
                ):
                    raise ValueError("tender_lot_mismatch")
                tender_nodes.append(tender)
                party_refs = _refs(tender, "efac:TenderingParty")
                if len(party_refs) != 1 or not (party := parties.get(party_refs[0])):
                    raise ValueError("unresolved_winning_party")
                members = []
                for ref in _refs(party, "efac:Tenderer"):
                    if ref in excluded_refs or not (organization_node := organizations.get(ref)):
                        raise ValueError("unresolved_or_nonwinning_organization")
                    organization = _organization(organization_node, winner=True)
                    if organization is None:
                        raise ValueError("unresolved_organization_identity")
                    members.append(organization)
                if not members or len({member.organization_ref for member in members}) != len(
                    members
                ):
                    raise ValueError("ambiguous_winning_members")
                winning.append(
                    WinningPartyFacts(
                        party_ref=party_refs[0], source_path=party.path, members=tuple(members)
                    )
                )
            winning = tuple(winning)
            if not _aligned_winners(award, winning):
                raise ValueError("award_holder_mismatch")
            project = lot.at("cac:ProcurementProject")
            duration_data = _duration_data(project, snapshot, notice_kind="contract_award_notice")
            if duration_data["duration"] is None and related_records:
                related = _related_duration_data(
                    record,
                    notice,
                    event,
                    award.lot.identifier,
                    buyers,
                    related_records,
                    collected_at=collected_at,
                    policy=policy,
                    source_snapshots=sources_by_id,
                )
                if related:
                    prior_data, prior_snapshot = related
                    duration_data.update(
                        {key: value for key, value in prior_data.items() if value is not None}
                    )
                    related_snapshots[prior_snapshot.snapshot_key] = prior_snapshot
            accepted.append(
                NoticeAwardFacts(
                    snapshot_key=snapshot.snapshot_key,
                    event_key=event.ref().key(),
                    award_key=key,
                    source=source,
                    source_award_id=award.source_award_id,
                    lot_identifier=award.lot.identifier,
                    result_source_path=result.path,
                    title=contract.at("cbc:Title").fact()
                    or project.at("cbc:Name").fact()
                    or notice.at("cac:ProcurementProject", "cbc:Name").fact(),
                    lot_title=project.at("cbc:Name").fact(),
                    lot_description=project.at("cbc:Description").fact(),
                    published_on=published_on,
                    buyers=buyers,
                    winning_parties=winning,
                    awarded_value=_money(
                        tender_nodes[0].at("cac:LegalMonetaryTotal", "cbc:PayableAmount")
                    )
                    if len(tender_nodes) == 1
                    else None,
                    minimum_value=_money(
                        result.at("efac:FrameworkAgreementValues", "cbc:MinimumValueAmount")
                    ),
                    maximum_value=_money(
                        result.at("efac:FrameworkAgreementValues", "cbc:MaximumValueAmount")
                    ),
                    **duration_data,
                    coverage_gaps=("duration_not_verified",)
                    if duration_data["duration"] is None
                    else (),
                    related_notice_ids=related_ids,
                    related_notices_checked=related_checked,
                    notice_status=status,
                    notice_change_reason=ext.at(
                        "efac:Changes", "efac:Change", "efbc:ChangeDescription"
                    ).fact(),
                )
            )
        except ValueError as error:
            rejected.append(NoticeFactRejection(award_key=key, reason=str(error)))
    return NoticeFactsExtraction(
        snapshot=snapshot,
        awards=tuple(accepted),
        rejections=tuple(rejected),
        related_snapshots=tuple(related_snapshots.values()),
    )
