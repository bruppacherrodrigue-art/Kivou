from __future__ import annotations

import json
import pathlib

import httpx

from signals.documents import TenderDocument, coverage_for
from signals.domain import ContractAward, OrganizationRef, PublicEvent
from signals.resolution import CompanyResolver, ViesClient
from signals.understanding import ContractUnderstandingEngine

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _offline_vies() -> ViesClient:
    def handler(request: httpx.Request) -> httpx.Response:
        parts = str(request.url).rstrip("/").split("/")
        fixture = FIXTURES / "vies" / f"{parts[-3]}{parts[-1]}.json"
        if not fixture.exists():
            return httpx.Response(503)
        return httpx.Response(200, content=fixture.read_bytes())

    return ViesClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_winner_smoke_resolves_one_real_vies_mention() -> None:
    mentions = json.loads(
        (FIXTURES / "winner100" / "mentions.json").read_text(encoding="utf-8")
    )
    row = next(
        row
        for row in mentions
        if any(
            identifier["value"] == "LU26538172"
            for identifier in row["organization"]["identifiers"]
        )
    )

    resolution = CompanyResolver(vies=_offline_vies()).resolve(
        OrganizationRef.model_validate(row["organization"]),
        source_system=row["source"],
    )

    assert resolution.status == "verified"
    assert any(basis.method == "registry_lookup" and basis.supports for basis in resolution.basis)


def test_contract_smoke_understands_one_real_award() -> None:
    rows = json.loads(
        (FIXTURES / "contract100" / "awards.json").read_text(encoding="utf-8")
    )
    row = rows[0]
    award = ContractAward.model_validate(row["award"])
    event = PublicEvent.model_validate(row["event"])

    understanding = ContractUnderstandingEngine().understand(award, event)

    assert understanding.object_summary.value
    assert understanding.evidence_coverage == 1.0
    assert understanding.facts["cpv"].evidence[0].source_notice_id


def test_document_smoke_recomputes_coverage_for_one_real_record() -> None:
    corpus = json.loads(
        (FIXTURES / "documents" / "document100.json").read_text(encoding="utf-8")
    )
    record = corpus["records"][0]
    documents = tuple(
        TenderDocument(
            source_system="ted",
            source_procedure_id=record["procedure_id"],
            source_notice_id=record["tender_notice"],
            source_url=document["url"],
            media_type=document["media_type"],
            access_status=document["status"],
            content_hash=document["content_hash"],
            byte_size=document["bytes"],
        )
        for document in record["documents"]
    )

    assert documents
    assert coverage_for(documents, requirements=0) == "download_failed"
