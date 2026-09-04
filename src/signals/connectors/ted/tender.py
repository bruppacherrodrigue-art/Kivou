"""Adaptation factuelle des avis de mise en concurrence TED eForms."""

from __future__ import annotations

import datetime as dt

from defusedxml import ElementTree as DefusedET

from signals.documents.discovery import references_from_ted_notice
from signals.domain import OrganizationRef, Provenance, PublicEvent, TenderNotice

CAC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
CBC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
EFAC = "{http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1}"


def _text(root, path: str) -> str | None:
    value = root.findtext(path)
    return value.strip() if value and value.strip() else None


def _country(value: str | None) -> str:
    return {"FRA": "FR", "CHE": "CH"}.get(value or "", value or "EU")


def _buyers(root) -> tuple[OrganizationRef, ...]:
    references = {
        (node.text or "").strip()
        for node in root.findall(
            f"{CAC}ContractingParty/{CAC}Party/{CAC}PartyIdentification/{CBC}ID"
        )
    }
    buyers: list[OrganizationRef] = []
    for company in root.findall(f".//{EFAC}Company"):
        reference = _text(company, f"{CAC}PartyIdentification/{CBC}ID")
        if reference not in references:
            continue
        name = _text(company, f"{CAC}PartyName/{CBC}Name")
        if not name:
            continue
        buyers.append(
            OrganizationRef(
                legal_name=name,
                country=_country(
                    _text(
                        company,
                        f"{CAC}PostalAddress/{CAC}Country/{CBC}IdentificationCode",
                    )
                ),
                website=_text(company, f"{CBC}WebsiteURI"),
            )
        )
    return tuple(buyers)


def _deadline(root) -> dt.datetime | None:
    period = root.find(f".//{CAC}TenderSubmissionDeadlinePeriod")
    if period is None:
        return None
    date = _text(period, f"{CBC}EndDate")
    time = _text(period, f"{CBC}EndTime")
    if not date:
        return None
    day = date[:10]
    try:
        return dt.datetime.fromisoformat(f"{day}T{time}" if time else day)
    except ValueError:
        return None


def parse_tender_notice(
    xml: bytes | str,
    *,
    publication_number: str,
    retrieved_at: dt.datetime | None = None,
) -> TenderNotice:
    root = DefusedET.fromstring(xml)
    if not root.tag.endswith("}ContractNotice"):
        raise ValueError("TED notice is not a ContractNotice")
    buyers = _buyers(root)
    source_country = buyers[0].country if buyers and buyers[0].country else "EU"
    published = _text(root, f"{CBC}IssueDate")
    event = PublicEvent(
        provenance=Provenance(
            source_system="ted",
            source_country=source_country,
            source_notice_id=publication_number,
            source_procedure_id=_text(root, f"{CBC}ContractFolderID"),
            source_url=f"https://ted.europa.eu/en/notice/{publication_number}",
            retrieved_at=retrieved_at,
        ),
        event_type="tender_notice",
        published_at=dt.date.fromisoformat(published[:10]) if published else None,
        procedure_buyers=buyers,
    )
    project = root.find(f"{CAC}ProcurementProject")
    references = references_from_ted_notice(xml)
    return TenderNotice(
        event=event,
        title=_text(project, f"{CBC}Name") if project is not None else None,
        cpv_main=(
            _text(
                project,
                f"{CAC}MainCommodityClassification/{CBC}ItemClassificationCode",
            )
            if project is not None
            else None
        ),
        submission_deadline=_deadline(root),
        document_urls=tuple(reference.url for reference in references if reference.url),
    )
