"""Smoke test live SPEC-006 — volontaire, jamais lancé par la suite de tests.

    uv run python -m signals.documents.live_smoke --limit 25 --json rapport.json

Parcours réel : avis d'attribution → procédure (BT-04) → avis d'appel d'offres →
URL documentaires (BT-15) → téléchargement → exigences prouvées.

Aucun identifiant n'est demandé, lu ni fabriqué. Une plateforme qui exige un
compte produit `auth_required` : c'est un résultat mesuré, pas un échec à
contourner. Ce module ne crée aucun compte, ne simule aucun rôle et ne pilote
aucun navigateur.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time

from signals.connectors.ted.client import TedClient
from signals.connectors.ted.errors import TedError
from signals.connectors.ted.mapping import map_notice
from signals.connectors.ted.parser import parse_notice
from signals.documents.discovery import references_from_ted_notice
from signals.documents.fetch import DocumentFetcher, FetchLimits
from signals.documents.intelligence import analyze_dossier
from signals.documents.model import TenderDocument

AWARD_QUERY = (
    "form-type=result AND publication-date>=today(-{days}) SORT BY publication-number DESC"
)


def _patient(call, tries: int = 4, pause: float = 3.0):
    """TED répond 429 sous cadence soutenue : on ralentit au lieu d'abandonner."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            return call()
        except TedError as exc:
            last = exc
            time.sleep(pause * (attempt + 1))
    raise last  # type: ignore[misc]


def run(days: int, limit: int, pause: float, json_path: str | None) -> dict[str, object]:
    coverage: collections.Counter[str] = collections.Counter()
    requirement_types: collections.Counter[str] = collections.Counter()
    rows: list[dict[str, object]] = []
    requirements_total = 0
    documents_read = 0

    with TedClient() as client, DocumentFetcher(limits=FetchLimits()) as fetcher:
        refs = client.search_all(AWARD_QUERY.format(days=days), wanted=limit, page_size=50)
        print(f"{len(refs)} avis d'attribution", file=sys.stderr)

        for index, ref in enumerate(refs, start=1):
            row: dict[str, object] = {"award": ref.publication_number}
            try:
                number = ref.publication_number
                xml = _patient(lambda n=number: client.fetch_notice_xml(n))
                extraction = map_notice(parse_notice(xml), retrieved_at=dt.datetime.now(dt.UTC))
            except (TedError, ValueError) as exc:
                row["error"] = str(exc)[:200]
                rows.append(row)
                continue

            event = extraction.event
            procedure_id = event.provenance.source_procedure_id
            row["procedure_id"] = procedure_id
            items: list[tuple[TenderDocument, bytes | None]] = []

            if procedure_id:
                query = f'procedure-identifier="{procedure_id}" AND form-type=competition'
                found, _ = _patient(lambda q=query: client.search(q, limit=5))
                tenders = [
                    row_ref.publication_number
                    for row_ref in found
                    if row_ref.publication_number != ref.publication_number
                ]
                row["tender_notice"] = tenders[0] if tenders else None
                if tenders:
                    tender_number = tenders[0]
                    tender_xml = _patient(lambda n=tender_number: client.fetch_notice_xml(n))
                    for reference in references_from_ted_notice(tender_xml)[:2]:
                        if not reference.url:
                            continue
                        fetched = fetcher.fetch(reference.url)
                        document = TenderDocument(
                            source_system="ted",
                            source_procedure_id=procedure_id,
                            source_notice_id=tender_number,
                            name=reference.name,
                            source_url=reference.url,
                            media_type=fetched.media_type,
                            access_status=fetched.access_status,
                            content_hash=fetched.content_hash,
                            byte_size=fetched.byte_size,
                            retrieved_at=fetched.retrieved_at,
                        )
                        items.append((document, fetched.content))
                        time.sleep(pause)

            result = analyze_dossier(
                award_ref=event.ref(),
                source_system="ted",
                items=items,
                tender_procedure_id=procedure_id,
            )
            coverage[result.coverage_status] += 1
            requirements_total += len(result.requirements)
            documents_read += len(result.readable_documents)
            for requirement in result.requirements:
                requirement_types[requirement.requirement_type] += 1

            row["coverage"] = result.coverage_status
            row["documents"] = len(result.documents)
            row["requirements"] = len(result.requirements)
            rows.append(row)
            print(
                f"[{index}/{len(refs)}] {ref.publication_number} "
                f"{result.coverage_status} — {len(result.requirements)} exigence(s)",
                file=sys.stderr,
            )
            time.sleep(pause)

    metrics = {
        "awards": len(rows),
        "coverage": dict(coverage.most_common()),
        "documents_read": documents_read,
        "requirements": requirements_total,
        "requirement_types": dict(requirement_types.most_common()),
        "http_requests": fetcher.requests_sent,
        "cache_hits": fetcher.cache_hits,
    }
    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump({"metrics": metrics, "rows": rows}, handle, ensure_ascii=False, indent=1)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=25)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--pause", type=float, default=0.5)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    try:
        metrics = run(args.days, args.limit, args.pause, args.json_path)
    except TedError as exc:
        print(f"TED indisponible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
