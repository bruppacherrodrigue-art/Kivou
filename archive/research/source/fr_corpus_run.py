"""Constituer le corpus documentaire français depuis des consultations OUVERTES.

    uv run python -m signals.research.fr_corpus_run --consultations 25 --out corpus.json

Chaîne complète, toute en sources publiques :

    BOAMP (avis de marché, date limite non échue)
      → URI Achatpublic publiée par l'avis
      → GET fiche publique (cookie anonyme, dceId lu dans la page)
      → POST retrait DCE, champs de contact VIDES
      → ZIP → garde-fous d'archive SPEC-006 → extraction SPEC-006
      → candidats figés avec leur voisinage réel

Aucune identité fabriquée, aucun login, aucun CAPTCHA, aucun code de production
modifié. Le corpus sort **sans gold** : l'étiquetage revient à un humain.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time

import httpx

from signals.documents.archive import expand
from signals.documents.classification import _looks_like_heading
from signals.documents.extract import extract_text, sniff_media_type
from signals.documents.heldout3_build import (
    CORPUS_KINDS,
    known_awards,
    known_consultations,
    known_document_hashes,
    known_sentence_hashes,
)
from signals.documents.language import detect_modality, normalize_for_match, sentences
from signals.documents.snapshot import CandidateSnapshot, snapshot_candidate
from signals.documents.spans import logical_spans
from signals.documents.triage import detect_language, document_kind
from signals.research.achatpublic_dce import (
    USER_AGENT,
    DceAttempt,
    dce_id_from_page,
    detail_url,
    download_request,
    is_zip,
    pcslid_from_url,
)
from signals.research.fr_portal_spike import platform_of
from signals.research.france_spike import BOAMP_API, document_urls

MAX_DCE = 25
"""Plafond de retraits. Au-delà ce serait du crawl, pas la constitution d'un
corpus de mesure."""

MAX_BYTES = 60_000_000


def span_candidates(blocks, spans) -> list[tuple[int, str]]:
    """Les candidats d'un document : les phrases des spans recollés, jamais des pages.

    SPEC-006R5 §5 : l'ancien découpage (page brute → phrases) a produit 136
    étiquettes `context_fragment` sur les 400 candidats de FR-DCE-1 — des
    phrases coupées par la mise en page, pas par leur auteur. Le découpage se
    fait ici sur la vue recollée ; chaque phrase est rattachée au bloc où elle
    COMMENCE, pour que le voisinage figé du snapshot reste celui du document.
    """
    positions = {id(block): index for index, block in enumerate(blocks)}
    picked: list[tuple[int, str]] = []
    for span in spans:
        if _looks_like_heading(span.text):
            continue
        for sentence in sentences(span.text):
            # `detect_modality` rend None, jamais "none".
            if detect_modality(sentence) is None:
                continue
            pieces = span.pieces_for(sentence)
            if not pieces:
                continue
            picked.append((positions[id(pieces[0].block)], sentence))
    return picked


def open_consultations(
    client: httpx.Client, *, wanted: int, pause: float, exclude: set[str] | None = None
) -> list[dict]:
    """Des appels d'offres français encore ouverts, pointant vers Achatpublic.

    Le filtre sur la date limite est la correction centrale de cette SPEC : un
    avis d'attribution mène à une consultation close, dont le DCE a été retiré.
    """
    now = dt.datetime.now(dt.UTC).isoformat()
    found: list[dict] = []
    offset = 0
    while len(found) < wanted and offset < 1200:
        response = client.get(
            f"{BOAMP_API}/records",
            params={
                "where": f'nature="APPEL_OFFRE" AND datelimitereponse>"{now}"',
                "order_by": "dateparution DESC",
                "limit": 100,
                "offset": offset,
            },
        )
        if response.status_code != 200:
            break
        rows = response.json().get("results") or []
        if not rows:
            break
        for record in rows:
            for url in document_urls(record):
                if platform_of(url) != "achatpublic":
                    continue
                pcslid = pcslid_from_url(url)
                if not pcslid or any(f["pcslid"] == pcslid for f in found):
                    continue
                # Une extension de corpus doit venir de consultations neuves,
                # sinon elle rééchantillonnerait les mêmes dossiers.
                if exclude and pcslid in exclude:
                    continue
                found.append(
                    {
                        "pcslid": pcslid,
                        "url": url,
                        "idweb": record.get("idweb"),
                        "buyer": record.get("nomacheteur"),
                        "objet": (record.get("objet") or "")[:140],
                        "deadline": record.get("datelimitereponse"),
                    }
                )
                if len(found) >= wanted:
                    break
            if len(found) >= wanted:
                break
        offset += 100
        time.sleep(pause)
    return found


def retrieve_dce(client: httpx.Client, pcslid: str) -> tuple[DceAttempt, bytes | None]:
    """Le retrait anonyme, étape par étape, sans jamais remplir un champ."""
    attempt = DceAttempt(pcslid=pcslid)
    page = client.get(detail_url(pcslid))
    attempt.detail_status = page.status_code
    if page.status_code != 200:
        attempt.blocker = "fiche de consultation inaccessible"
        return attempt, None

    attempt.dce_id = dce_id_from_page(page.text)
    if not attempt.dce_id:
        attempt.blocker = "aucun bloc DCE dans la page publique"
        return attempt, None

    url, body = download_request(pcslid, attempt.dce_id)
    payload = bytearray()
    with client.stream("POST", url, data=body, headers={"Referer": detail_url(pcslid)}) as response:
        attempt.download_status = response.status_code
        attempt.content_type = response.headers.get("content-type")
        disposition = response.headers.get("content-disposition") or ""
        if "filename=" in disposition:
            raw = disposition.split("filename=")[-1]
            attempt.filename = raw.strip().strip('"').strip("'").strip()
        if response.status_code != 200:
            attempt.blocker = f"retrait refusé (HTTP {response.status_code})"
            return attempt, None
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload) > MAX_BYTES:
                attempt.blocker = "au-delà de la limite de taille"
                return attempt, None

    data = bytes(payload)
    attempt.byte_size = len(data)
    attempt.sha256 = hashlib.sha256(data).hexdigest()
    attempt.is_archive = is_zip(data)
    if not data:
        attempt.blocker = "réponse vide"
        return attempt, None
    return attempt, data


def members_of(name: str, data: bytes) -> list[tuple[str, bytes]]:
    """Le contenu de l'archive, avec les garde-fous SPEC-006 — jamais réécrits."""
    if not is_zip(data) or sniff_media_type(name, data) != "application/zip":
        return [(name, data)]
    out: list[tuple[str, bytes]] = []
    for entry in expand(data).accepted:
        if entry.content is not None:
            out.append((entry.path.split("/")[-1], entry.content))
    return out


def run(*, wanted: int, per_document: int, pause: float, exclude: set[str] | None = None) -> dict:
    stats: collections.Counter[str] = collections.Counter()
    seen_hashes = known_document_hashes()
    seen_awards = known_awards()
    # SPEC-006R5 §25 — disjonction à trois niveaux : consultation, document,
    # phrase. Les consultations déjà échantillonnées sont écartées d'office,
    # en plus de celles nommées à la ligne de commande.
    exclude = (exclude or set()) | known_consultations()
    seen_sentences = known_sentence_hashes()
    snapshots: list[CandidateSnapshot] = []
    sources: list[dict] = []
    attempts: list[dict] = []
    next_id = 1

    with httpx.Client(
        timeout=90, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        consultations = open_consultations(client, wanted=wanted, pause=pause, exclude=exclude)
        print(f"{len(consultations)} consultations ouvertes vers Achatpublic", file=sys.stderr)

        for position, consultation in enumerate(consultations[:MAX_DCE], start=1):
            stats["consultations"] += 1
            if consultation["idweb"] in seen_awards:
                stats["award_already_used"] += 1
                continue

            attempt, data = retrieve_dce(client, consultation["pcslid"])
            attempts.append({**attempt.as_dict(), "objet": consultation["objet"]})
            if attempt.blocker:
                stats[f"blocked_{attempt.blocker.split()[0]}"] += 1
            if data is None:
                print(f"[{position}] {consultation['pcslid']} — {attempt.blocker}", file=sys.stderr)
                time.sleep(pause)
                continue

            stats["dce_downloaded"] += 1
            stats["archive" if attempt.is_archive else "single_file"] += 1

            for member_name, member_bytes in members_of(
                attempt.filename or f"{consultation['pcslid']}.zip", data
            ):
                stats["members"] += 1
                kind = document_kind(member_name)
                stats[f"kind_{kind}"] += 1
                if kind not in CORPUS_KINDS:
                    stats["kind_excluded"] += 1
                    continue

                result = extract_text(member_bytes, name=member_name)
                stats[f"media_{result.media_type}"] += 1
                if not result.supported or len(result.blocks) < 5:
                    stats["unusable_media"] += 1
                    continue

                sample = " ".join(b.text for b in result.blocks[:60])
                language = detect_language(sample)
                stats[f"lang_{language}"] += 1

                member_hash = hashlib.sha256(member_bytes).hexdigest()
                if member_hash in seen_hashes:
                    stats["document_already_used"] += 1
                    continue

                blocks = result.blocks
                spans = logical_spans(blocks)
                # Découpage en PHRASES sur les spans recollés, comme la
                # production (`intelligence.py`) — jamais sur la page brute,
                # qui tronquait les phrases aux frontières de mise en page.
                picked: list[tuple[int, str]] = []
                for index, sentence in span_candidates(blocks, spans):
                    digest = hashlib.sha256(normalize_for_match(sentence).encode()).hexdigest()
                    if digest in seen_sentences:
                        stats["sentence_already_used"] += 1
                        continue
                    picked.append((index, sentence))
                picked = picked[:per_document]
                if not picked:
                    stats["no_candidate"] += 1
                    continue

                kept = 0
                for index, sentence in picked:
                    try:
                        snapshots.append(
                            snapshot_candidate(
                                candidate_id=next_id,
                                award_reference=consultation["idweb"] or consultation["pcslid"],
                                document_name=member_name,
                                document_hash=member_hash,
                                media_type=result.media_type,
                                blocks=blocks,
                                index=index,
                                excerpt=sentence,
                                spans=spans,
                            )
                        )
                    except ValueError:
                        stats["excerpt_not_located"] += 1
                        continue
                    next_id += 1
                    kept += 1

                seen_hashes.add(member_hash)
                stats["documents"] += 1
                sources.append(
                    {
                        "consultation": consultation["pcslid"],
                        "boamp": consultation["idweb"],
                        "buyer": consultation["buyer"],
                        "deadline": consultation["deadline"],
                        "document": member_name,
                        "kind": kind,
                        "media_type": result.media_type,
                        "language": language,
                        "document_hash": member_hash,
                        "blocks": len(blocks),
                        "candidates": kept,
                    }
                )
                print(
                    f"    ✓ {member_name[:60]} [{kind}/{language}] {kept} candidat(s)",
                    file=sys.stderr,
                )
            time.sleep(pause)

    return {
        "corpus": "FR-DCE-1",
        "built_at": dt.datetime.now(dt.UTC).date().isoformat(),
        "source": "BOAMP (appels d'offres ouverts) → Achatpublic, retrait anonyme sans identité",
        "gold_status": "ABSENT — à poser par un humain AVANT tout appel LLM",
        "access_note": (
            "GET fiche publique, cookie anonyme de session, POST telechargerDCE.action avec "
            "nomEntiteContact/nomPointContact/mailPointContact VIDES. Aucun login, aucun CAPTCHA, "
            "aucune identité fabriquée."
        ),
        "stats": dict(stats),
        "attempts": attempts,
        "sources": sources,
        "rows": [s.as_dict() for s in snapshots],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consultations", type=int, default=25)
    parser.add_argument("--per-document", type=int, default=25)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--exclude-consultations",
        default="",
        help="identifiants PCSLID déjà utilisés, séparés par une virgule",
    )
    args = parser.parse_args()

    report = run(
        wanted=args.consultations,
        per_document=args.per_document,
        pause=args.pause,
        exclude={c.strip() for c in args.exclude_consultations.split(",") if c.strip()},
    )
    print(json.dumps(report["stats"], ensure_ascii=False, indent=1))
    print(f"candidats : {len(report['rows'])}", file=sys.stderr)
    print(f"documents : {len(report['sources'])}", file=sys.stderr)
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1))
        print(f"écrit : {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
