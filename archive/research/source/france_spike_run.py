"""Le run du SPIKE FRANCE — mesure, pas connecteur.

    uv run python -m signals.research.france_spike_run --awards 30 --json rapport.json

Parcours réel : award BOAMP → annonce liée → avis d'origine → URI documentaire →
téléchargement borné → extraction. Chaque étape est comptée séparément, de sorte
qu'un taux faible dise **où** la chaîne casse.

Accès : lecture seule, cadence lente, User-Agent identifiant, limites de taille
reprises de SPEC-006. Les documents publics peuvent être récupérés par les moyens
ordinaires offerts à un utilisateur, sans contournement d'authentification ni de
CAPTCHA et dans le respect des CGU et de robots.txt.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time

import httpx

from signals.documents.extract import extract_text
from signals.documents.fetch import DocumentFetcher, FetchLimits
from signals.documents.language import MAX_SENTENCE_CHARS, MIN_SENTENCE_CHARS, detect_modality
from signals.research.france_spike import (
    BOAMP_API,
    EXECUTION_DOC_TYPES,
    USER_AGENT,
    AwardProbe,
    amount_eur,
    buyer_name,
    classify_host,
    cpv_codes,
    document_urls,
    french_document_type,
    linkage,
    procedure_reference,
    winner_names,
)

MAX_DOCUMENTS = 50
"""Plafond de téléchargement du spike, imposé par la consigne. Un dépassement
serait du crawl, pas une mesure."""


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=45,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def sample_awards(client: httpx.Client, *, wanted: int, since: str) -> list[dict]:
    """Un échantillon reproductible, réparti sur les acheteurs et les secteurs.

    Le tri est déterministe (`dateparution` puis `idweb`), et la répartition se
    fait à tour de rôle sur le type de marché puis sur l'acheteur : prendre les
    30 premiers donnerait 30 avis du même jour et souvent du même acheteur, ce
    qui mesurerait un acheteur plutôt que la France.
    """
    pool: list[dict] = []
    for offset in range(0, 400, 100):
        response = client.get(
            f"{BOAMP_API}/records",
            params={
                "where": f'nature="ATTRIBUTION" AND dateparution>="{since}"',
                "order_by": "dateparution DESC, idweb ASC",
                "limit": 100,
                "offset": offset,
            },
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        pool.extend(results)
        if len(results) < 100:
            break
        time.sleep(0.4)

    by_sector: dict[str, list[dict]] = collections.OrderedDict()
    for record in pool:
        markets = record.get("type_marche") or ["INCONNU"]
        sector = markets[0] if isinstance(markets, list) and markets else "INCONNU"
        by_sector.setdefault(str(sector), []).append(record)

    picked: list[dict] = []
    seen_buyers: set[str] = set()
    depth = 0
    while len(picked) < wanted:
        progressed = False
        for records in by_sector.values():
            if depth >= len(records):
                continue
            record = records[depth]
            progressed = True
            buyer = (record.get("nomacheteur") or "").strip()
            # Un acheteur par tour : on veut plusieurs acheteurs, pas un seul.
            if buyer and buyer in seen_buyers and len(picked) < wanted:
                continue
            seen_buyers.add(buyer)
            picked.append(record)
            if len(picked) == wanted:
                break
        if not progressed:
            break
        depth += 1
    return picked[:wanted]


def fetch_notice(client: httpx.Client, idweb: str) -> dict | None:
    response = client.get(f"{BOAMP_API}/records", params={"where": f'idweb="{idweb}"', "limit": 1})
    if response.status_code != 200:
        return None
    results = response.json().get("results") or []
    return results[0] if results else None


def candidate_count(blocks) -> int:
    """Combien de phrases porteraient une modalité — le vivier, pas le verdict."""
    return sum(
        1
        for block in blocks
        if MIN_SENTENCE_CHARS <= len(block.text.strip()) <= MAX_SENTENCE_CHARS
        and detect_modality(block.text.strip()) != "none"
    )


def run(*, wanted: int, since: str, pause: float) -> dict:
    stats: collections.Counter[str] = collections.Counter()
    hosts: collections.Counter[str] = collections.Counter()
    fetch_status: collections.Counter[str] = collections.Counter()
    doc_types: collections.Counter[str] = collections.Counter()
    probes: list[AwardProbe] = []
    downloaded = 0

    with _client() as client, DocumentFetcher(limits=FetchLimits()) as fetcher:
        awards = sample_awards(client, wanted=wanted, since=since)
        print(f"{len(awards)} awards échantillonnés", file=sys.stderr)

        for position, award in enumerate(awards, start=1):
            probe = AwardProbe(idweb=award.get("idweb") or "?")
            probe.dateparution = award.get("dateparution")
            probe.buyer = buyer_name(award)
            probe.winners = winner_names(award)
            probe.amount = amount_eur(award)
            probe.cpv = cpv_codes(award)
            probe.procedure_reference = procedure_reference(award)

            stats["awards"] += 1
            stats["buyer_found"] += bool(probe.buyer)
            stats["winner_found"] += bool(probe.winners)
            stats["amount_found"] += probe.amount is not None
            stats["cpv_found"] += bool(probe.cpv)
            stats["procedure_reference_found"] += bool(probe.procedure_reference)

            link = linkage(award)
            probe.linkage_strength = link.strength
            stats[f"linkage_{link.strength}"] += 1

            tender = None
            if link.notice_ids:
                probe.linked_notice = link.notice_ids[0]
                tender = fetch_notice(client, link.notice_ids[0])
                stats["linked_notice_fetched"] += tender is not None
                time.sleep(pause)

            urls = document_urls(tender) if tender else []
            probe.document_urls = urls
            stats["source_consultation_url_found"] += bool(urls)
            for url in urls:
                host = classify_host(url)
                if host:
                    hosts[host] += 1
                    probe.hosts.append(host)
            stats["place_match"] += any(h == "place" for h in probe.hosts)

            for url in urls[:2]:
                if downloaded >= MAX_DOCUMENTS:
                    stats["download_budget_reached"] += 1
                    break
                fetched = fetcher.fetch(url)
                fetch_status[fetched.access_status] += 1
                probe.fetch_statuses.append(fetched.access_status)
                if fetched.access_status != "available" or not fetched.content:
                    continue
                downloaded += 1
                probe.documents_downloaded += 1
                result = extract_text(fetched.content, name=url.rsplit("/", 1)[-1])
                if not result.supported or not result.blocks:
                    continue
                probe.documents_extractable += 1
                kind = french_document_type(url)
                doc_types[kind] += 1
                if kind in EXECUTION_DOC_TYPES:
                    probe.execution_documents.append(kind)
                probe.candidates += candidate_count(result.blocks)
                time.sleep(pause)

            if probe.execution_documents:
                stats["awards_with_execution_document"] += 1
            probes.append(probe)
            print(
                f"[{position}/{len(awards)}] {probe.idweb} {link.strength} "
                f"{len(urls)} url(s) {probe.hosts[:2]}",
                file=sys.stderr,
            )
            time.sleep(pause)

    total = max(stats["awards"], 1)
    return {
        "spike": "FRANCE — BOAMP/PLACE/DECP",
        "sample_size": stats["awards"],
        "since": since,
        "boamp": dict(stats),
        "hosts": dict(hosts.most_common()),
        "fetch_status": dict(fetch_status),
        "document_types": dict(doc_types),
        "rates": {
            "boamp_linkage_rate": (stats["linkage_exact"] + stats["linkage_strong"]) / total,
            "document_url_rate": stats["source_consultation_url_found"] / total,
            "place_match_rate": stats["place_match"] / total,
            "public_document_rate": sum(1 for p in probes if p.documents_downloaded) / total,
            "execution_document_rate": stats["awards_with_execution_document"] / total,
            "document_access_rate": stats["awards_with_execution_document"] / total,
        },
        "documents_downloaded": downloaded,
        "probes": [p.as_dict() for p in probes],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--awards", type=int, default=30)
    parser.add_argument("--since", default="2026-05-01")
    parser.add_argument("--pause", type=float, default=0.5)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    report = run(wanted=args.awards, since=args.since, pause=args.pause)
    print(json.dumps(report["rates"], indent=1))
    print(json.dumps(report["boamp"], indent=1))
    print("hosts:", json.dumps(report["hosts"], ensure_ascii=False))
    print("fetch:", json.dumps(report["fetch_status"], ensure_ascii=False))
    if args.json_path:
        pathlib.Path(args.json_path).write_text(json.dumps(report, ensure_ascii=False, indent=1))
        print(f"écrit : {args.json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
