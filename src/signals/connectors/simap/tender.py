"""Adaptation factuelle d'une publication d'appel d'offres SIMAP."""

from __future__ import annotations

import datetime as dt
from typing import Any

from signals.domain import OrganizationRef, Provenance, PublicEvent, TenderNotice

DETAIL_URL = (
    "https://www.simap.ch/api/publications/v1/project/{project_id}"
    "/publication-details/{publication_id}"
)


def _translated(value: Any, language: str | None) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    for code in (language, "de", "fr", "it", "en"):
        text = value.get(code) if code else None
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def extract_tender(
    payload: dict[str, Any], *, retrieved_at: dt.datetime | None = None
) -> TenderNotice:
    base = payload.get("base") or {}
    if (payload.get("type") or base.get("type")) != "tender":
        raise ValueError("SIMAP publication is not a tender")
    publication_id = base.get("id")
    project_id = base.get("projectId")
    if not publication_id or not project_id:
        raise ValueError("SIMAP tender has no stable publication/procedure identity")
    language = base.get("creationLanguage")
    project = payload.get("project-info") or {}
    procurement = payload.get("procurement") or {}
    address = project.get("procOfficeAddress") or {}
    buyer_name = _translated(address.get("name"), language)
    buyers = (
        (
            OrganizationRef(
                legal_name=buyer_name,
                country=address.get("countryId"),
                website=_translated(address.get("url"), language),
            ),
        )
        if buyer_name
        else ()
    )
    published = base.get("publicationDate")
    source_url = DETAIL_URL.format(project_id=project_id, publication_id=publication_id)
    event = PublicEvent(
        provenance=Provenance(
            source_system="simap",
            source_country="CH",
            source_notice_id=publication_id,
            source_procedure_id=project_id,
            source_url=source_url,
            retrieved_at=retrieved_at,
        ),
        event_type="tender_notice",
        published_at=dt.date.fromisoformat(published) if published else None,
        procedure_buyers=buyers,
    )
    deadline = (payload.get("dates") or {}).get("offerDeadline")
    cpv = procurement.get("cpvCode") or base.get("cpvCode") or {}
    has_documents = bool(payload.get("hasProjectDocuments"))
    return TenderNotice(
        event=event,
        title=_translated(base.get("title") or project.get("title"), language),
        cpv_main=cpv.get("code"),
        submission_deadline=dt.datetime.fromisoformat(deadline) if deadline else None,
        document_urls=(source_url,) if has_documents else (),
        document_access_status="auth_required" if has_documents else None,
    )
