"""Construire HELD-OUT-3 : candidats figés, contexte réel, gold laissé vide.

    uv run python -m signals.documents.heldout3_build --awards 600 --out corpus.json

Ce module ne produit **aucune étiquette**. Il récupère des dossiers réels, en
extrait des candidats avec leur voisinage, vérifie que chaque extrait se retrouve
dans ses blocs sources, et écrit un corpus dont les colonnes `gold_*` restent à
poser par un humain. C'est délibéré : un gold écrit par un modèle de langue, puis
utilisé pour noter deux autres modèles appliquant le même contrat, mesurerait un
accord entre modèles et l'appellerait « précision ».

La disjonction est vérifiée automatiquement contre tous les corpus antérieurs,
par empreinte de document **et** par award — SPEC-006R4 §10.

Aucun identifiant n'est demandé ni fabriqué. Une plateforme qui exige un compte
produit `auth_required` : c'est une mesure, pas un obstacle à contourner.
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
from collections.abc import Collection, Sequence

from signals.connectors.ted.client import TedClient
from signals.connectors.ted.errors import TedError
from signals.connectors.ted.mapping import map_notice
from signals.connectors.ted.parser import parse_notice
from signals.documents.archive import expand
from signals.documents.classification import _looks_like_heading
from signals.documents.discovery import references_from_ted_notice
from signals.documents.extract import extract_text, sniff_media_type
from signals.documents.fetch import DocumentFetcher, FetchLimits, content_hash
from signals.documents.language import (
    MAX_SENTENCE_CHARS,
    MIN_SENTENCE_CHARS,
    detect_modality,
    normalize_for_match,
)
from signals.documents.snapshot import CandidateSnapshot, snapshot_candidate
from signals.documents.spans import logical_spans
from signals.documents.triage import detect_language, document_kind

FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "documents"

AWARD_QUERY = "form-type=result AND publication-date>=today(-{days})"
COUNTRY_CLAUSE = " AND buyer-country IN ({codes})"
QUERY_ORDER = " SORT BY publication-number DESC"


def award_query(*, days: int, countries: Sequence[str] = ()) -> str:
    """La requête TED. Le périmètre géographique est un paramètre, pas une constante.

    Prioriser un marché est une décision de go-to-market : elle vit dans l'appel,
    jamais dans le domaine. Aucun code pays n'est écrit en dur ici, et le modèle
    canonique n'en connaît aucun.
    """
    query = AWARD_QUERY.format(days=days)
    if countries:
        query += COUNTRY_CLAUSE.format(codes=" ".join(sorted(countries)))
    return query + QUERY_ORDER


def known_document_hashes(*, exclude: Collection[str] = ()) -> set[str]:
    """Toutes les empreintes déjà utilisées par un corpus antérieur.

    Un document réutilisé rendrait la mesure partiellement connue du contrat
    écrit sur les corpus précédents — elle ne serait plus held-out.

    `exclude` nomme les fixtures à ignorer : un corpus qui vérifie sa propre
    disjonction doit se retirer de la comparaison, sinon il se déclare lui-même
    déjà utilisé.
    """
    hashes: set[str] = set()

    manifest = FIXTURES / "MANIFEST.json"
    if manifest.exists() and "MANIFEST.json" not in exclude:
        for entry in json.loads(manifest.read_text()).values():
            if isinstance(entry, dict) and entry.get("sha256"):
                hashes.add(entry["sha256"])

    for name in (
        "heldout2_gold.json",
        "document100.json",
        "requirements_gold.json",
        "heldout3_candidates.json",
        "fr_dce_candidates.json",
        "fr_dce_candidates_ext.json",
    ):
        path = FIXTURES / name
        if not path.exists() or name in exclude:
            continue

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if "hash" in key.lower() and isinstance(value, str) and len(value) == 64:
                        hashes.add(value)
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(json.loads(path.read_text()))
    return hashes


def known_awards(*, exclude: Collection[str] = ()) -> set[str]:
    """Les awards déjà vus. HELD-OUT-1 et DEV-2 ne stockent pas d'empreinte :
    la disjonction par award est le seul garde-fou qui les couvre.

    `exclude` a le même rôle que pour les empreintes — voir ci-dessus.
    """
    awards: set[str] = set()
    for name in (
        "heldout2_gold.json",
        "heldout_classification.json",
        "requirements_gold.json",
    ):
        path = FIXTURES / name
        if not path.exists() or name in exclude:
            continue
        for row in json.loads(path.read_text()).get("rows", []):
            if isinstance(row, dict) and row.get("award"):
                awards.add(str(row["award"]))

    stratum_one = FIXTURES / "heldout3_candidates.json"
    if stratum_one.exists() and "heldout3_candidates.json" not in exclude:
        for row in json.loads(stratum_one.read_text()).get("rows", []):
            awards.add(str(row["award_reference"]))
    return awards


_SENTENCE_CORPORA = (
    "heldout3_candidates.json",
    "fr_dce_candidates.json",
    "fr_dce_candidates_ext.json",
)


def known_sentence_hashes(*, exclude: Collection[str] = ()) -> set[str]:
    """Les empreintes des phrases déjà échantillonnées par un corpus antérieur.

    SPEC-006R5 §25 : deux consultations distinctes peuvent partager un CCAP
    type mot pour mot — la disjonction par consultation et par document ne
    l'attrape pas, seule l'empreinte de la phrase normalisée le fait. Le hash
    porte sur `normalize_for_match(excerpt)` : la même phrase aux espaces près
    est la même phrase.
    """
    digests: set[str] = set()
    for name in _SENTENCE_CORPORA:
        path = FIXTURES / name
        if not path.exists() or name in exclude:
            continue
        for row in json.loads(path.read_text()).get("rows", []):
            excerpt = row.get("excerpt")
            if excerpt:
                digests.add(hashlib.sha256(normalize_for_match(excerpt).encode()).hexdigest())
    return digests


def known_consultations(*, exclude: Collection[str] = ()) -> set[str]:
    """Les identifiants de consultation (PCSLID) déjà échantillonnés.

    Le premier niveau de la disjonction §25 : une consultation dont un seul
    document a servi à DEV ne peut plus fournir le held-out final.
    """
    consultations: set[str] = set()
    for name in ("fr_dce_candidates.json", "fr_dce_candidates_ext.json"):
        path = FIXTURES / name
        if not path.exists() or name in exclude:
            continue
        for source in json.loads(path.read_text()).get("sources", []):
            if source.get("consultation"):
                consultations.add(str(source["consultation"]))
    return consultations


def candidate_indices(blocks) -> list[int]:
    """Les blocs qui portent un verbe normatif et une longueur plausible.

    Sélection **déterministe et large** : ce n'est pas encore un jugement, c'est
    le vivier que les modèles auront à trier. Filtrer plus finement ici
    reviendrait à décider d'avance ce qu'ils doivent trouver.
    """
    chosen: list[int] = []
    for index, block in enumerate(blocks):
        text = block.text.strip()
        if not (MIN_SENTENCE_CHARS <= len(text) <= MAX_SENTENCE_CHARS):
            continue
        # Un titre porte parfois un mot modal sans énoncer d'obligation
        # (« DOKUMENTACIJA V ZVEZI Z ODDAJO ») : il occuperait une place pour rien.
        if _looks_like_heading(text):
            continue
        # `detect_modality` rend None, jamais la chaîne "none" : comparer à
        # "none" ne filtrait rien et laissait passer titres et en-têtes.
        if detect_modality(text) is None:
            continue
        chosen.append(index)
    return chosen


def _members(name: str | None, data: bytes) -> list[tuple[str, bytes]]:
    """Le document, ou le contenu de l'archive qui le porte.

    Les dossiers de marché arrivent très souvent en ZIP. Les garde-fous de
    `archive.expand` s'appliquent : traversée de chemin, bombe, profondeur,
    exécutables — une entrée refusée n'est pas ouverte.
    """
    if data[:4] != b"PK\x03\x04" or sniff_media_type(name, data) != "application/zip":
        return [(name or "document", data)]
    members: list[tuple[str, bytes]] = []
    for entry in expand(data).accepted:
        if entry.content is None:
            continue
        members.append((entry.path.split("/")[-1], entry.content))
    return members


def sample_round_robin(rows: list[dict], *, wanted: int) -> list[dict]:
    """Tire `wanted` candidats à tour de rôle sur les dossiers, puis les documents.

    Déterministe et aveugle au contenu : on ne choisit ni sur la longueur, ni sur
    la présence d'un mot modal fort, ni sur rien qui ressemblerait à une
    difficulté. Un corpus dont on aurait retiré les cas durs mesurerait la
    politique sur un monde qui n'existe pas.
    """
    by_award: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        by_award.setdefault(row["award_reference"], {}).setdefault(row["document_hash"], []).append(
            row
        )

    queues = [[doc for doc in documents.values()] for _, documents in sorted(by_award.items())]
    picked: list[dict] = []
    depth = 0
    while len(picked) < wanted:
        progressed = False
        for documents in queues:
            for candidates in documents:
                if depth < len(candidates):
                    picked.append(candidates[depth])
                    progressed = True
                    if len(picked) == wanted:
                        return picked
        if not progressed:
            break
        depth += 1
    return picked


def _patient(call, tries: int = 3, pause: float = 2.0):
    last: Exception | None = None
    for attempt in range(tries):
        try:
            return call()
        except TedError as exc:
            last = exc
            time.sleep(pause * (attempt + 1))
    raise last  # type: ignore[misc]


CORPUS_KINDS = frozenset(
    {
        "technical_specification",
        "contract_conditions",
        "bill_of_quantities",
        "procedure_rules",
        "annex",
        # Un nom de fichier opaque n'est pas une preuve d'inutilité. Le stratum 2
        # a chiffré le coût de l'exclure : **un** document exploitable sur 500
        # avis, alors que `1_CE_CPI_100_2026.pdf` est un cahier des charges.
        "unknown",
    }
)
"""Les natures conservées à l'acquisition d'un corpus d'évaluation.

Le filtre s'est ouvert au fil des mesures, et chaque ouverture a un motif chiffré :
sans filtre, 7 exigences réelles sur 150 ; avec un filtre à trois natures, un
document exploitable sur 500 avis. La règle retenue est donc l'inverse d'une
liste blanche — on ne rejette que ce qui est administratif **avec certitude**.

`schedule` — calendriers et documents de niveau de service — n'a pas de nature
propre dans `DocumentKind`, et on n'en invente pas une : ces pièces tombent en
`technical_specification`, `annex` ou `unknown`, toutes conservées.

Le filtre porte sur le **nom du fichier** et rien d'autre, avant tout appel de
modèle : il ne peut pas sélectionner sur ce qu'un modèle prédirait.
"""

EXCLUDED_KINDS = frozenset({"form", "notice_copy", "archive"})
"""Les seules exclusions : formulaires de candidature et ESPD, copies d'annonce
déjà lues dans l'avis, et conteneurs — une archive n'est pas un document, ses
membres le sont."""


def keeps_document(name: str | None, *, media_type: str | None = None) -> bool:
    """Ce document entre-t-il dans le corpus ? D'après son nom seul."""
    return document_kind(name, media_type=media_type) in CORPUS_KINDS


def keeps_language(detected: str | None, accepted: Sequence[str]) -> bool:
    """Garde tant qu'une AUTRE langue n'a pas été identifiée avec assez d'assurance.

    `detect_language` répond `None` dès que l'écart avec la deuxième langue est
    faible — et un bordereau de quantités, fait de nombres, ne rend jamais autre
    chose. Traiter `None` comme « langue non supportée » reviendrait à jeter
    précisément les pièces les plus denses en obligations chiffrées.
    """
    if not accepted:
        return True
    if detected is None:
        return True
    return detected in accepted


def build(
    *,
    awards: int,
    days: int,
    per_document: int,
    target_dossiers: int,
    pause: float,
    kinds: frozenset[str] | None = None,
    countries: Sequence[str] = (),
    languages: Sequence[str] = (),
) -> dict[str, object]:
    seen_hashes = known_document_hashes()
    seen_awards = known_awards()
    stats: collections.Counter[str] = collections.Counter()
    snapshots: list[CandidateSnapshot] = []
    sources: list[dict[str, object]] = []
    next_id = 1

    with TedClient() as client, DocumentFetcher(limits=FetchLimits()) as fetcher:
        # TED répond 429 sous cadence soutenue, y compris sur la pagination
        # initiale : la recherche est aussi patiente que le reste du parcours.
        refs = _patient(
            lambda: client.search_all(
                award_query(days=days, countries=countries), wanted=awards, page_size=50
            ),
            tries=8,
            pause=45.0,
        )
        print(f"{len(refs)} avis d'attribution à parcourir", file=sys.stderr)

        for position, ref in enumerate(refs, start=1):
            if len({s.award_reference for s in snapshots}) >= target_dossiers:
                break
            stats["awards"] += 1
            award = ref.publication_number
            if award in seen_awards:
                stats["award_already_used"] += 1
                continue

            try:
                xml = _patient(lambda n=award: client.fetch_notice_xml(n))
                extraction = map_notice(parse_notice(xml), retrieved_at=dt.datetime.now(dt.UTC))
            except (TedError, ValueError):
                stats["award_error"] += 1
                continue

            procedure_id = extraction.event.provenance.source_procedure_id
            if not procedure_id:
                stats["no_procedure"] += 1
                continue

            try:
                query = f'procedure-identifier="{procedure_id}" AND form-type=competition'
                found, _ = _patient(lambda q=query: client.search(q, limit=5))
            except TedError:
                stats["search_error"] += 1
                continue
            tenders = [r.publication_number for r in found if r.publication_number != award]
            stats["tenders_linked"] += bool(tenders)
            if not tenders:
                stats["no_tender_notice"] += 1
                continue

            try:
                tender_xml = _patient(lambda n=tenders[0]: client.fetch_notice_xml(n))
            except TedError:
                stats["tender_fetch_error"] += 1
                continue

            for reference in [r for r in references_from_ted_notice(tender_xml) if r.url][:2]:
                fetched = fetcher.fetch(reference.url)
                stats[f"access_{fetched.access_status}"] += 1
                # `available` est le seul état qui porte des octets.
                if fetched.access_status != "available" or not fetched.content:
                    continue
                if fetched.content_hash in seen_hashes:
                    stats["document_already_used"] += 1
                    continue

                # Une archive n'est pas un document mais un contenant : les deux
                # seuls dossiers réels déjà connus du projet arrivent en ZIP.
                # Ne pas l'ouvrir revenait à jeter la quasi-totalité des pièces.
                for member_name, member_bytes in _members(reference.name, fetched.content):
                    stats["members"] += 1
                    kind = document_kind(member_name)
                    stats[f"kind_{kind}"] += 1
                    if kinds is not None and kind not in kinds:
                        stats["kind_excluded"] += 1
                        continue
                    result = extract_text(member_bytes, name=member_name)
                    stats[f"media_{result.media_type}"] += 1
                    if not result.supported or len(result.blocks) < 5:
                        stats["unusable_media"] += 1
                        continue

                    # Filtre de langue appliqué au texte EXTRAIT, avant tout appel
                    # de modèle : il ne peut donc pas sélectionner sur une sortie.
                    sample = " ".join(b.text for b in result.blocks[:60])
                    detected = detect_language(sample)
                    stats[f"lang_{detected}"] += 1
                    if not keeps_language(detected, languages):
                        stats["language_excluded"] += 1
                        continue

                    member_hash = content_hash(member_bytes)
                    if member_hash in seen_hashes:
                        stats["document_already_used"] += 1
                        continue

                    blocks = result.blocks
                    spans = logical_spans(blocks)
                    picked = candidate_indices(blocks)[:per_document]
                    if not picked:
                        stats["no_candidate"] += 1
                        continue

                    kept = 0
                    for index in picked:
                        excerpt = blocks[index].text.strip()
                        try:
                            snapshots.append(
                                snapshot_candidate(
                                    candidate_id=next_id,
                                    award_reference=award,
                                    document_name=member_name,
                                    document_hash=member_hash,
                                    media_type=result.media_type,
                                    blocks=blocks,
                                    index=index,
                                    excerpt=excerpt,
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
                            "award": award,
                            "tender_notice": tenders[0],
                            "container": reference.name,
                            "document": member_name,
                            "media_type": result.media_type,
                            "document_hash": member_hash,
                            "blocks": len(blocks),
                            "candidates": kept,
                        }
                    )
                    print(
                        f"  \u2713 {award} {member_name} {result.media_type} {kept} candidat(s)",
                        file=sys.stderr,
                    )
                time.sleep(pause)

            if position % 25 == 0:
                print(f"[{position}/{len(refs)}] {dict(stats)}", file=sys.stderr)
            time.sleep(pause)

    return {
        "corpus": "HELD-OUT-3",
        "built_at": dt.datetime.now(dt.UTC).date().isoformat(),
        "contract_version": "semantic-requirement-filter-v0.3",
        "consensus_policy_version": "consensus-two-model-v0.4",
        "gold_status": "ABSENT — à poser par un humain avant tout appel API",
        "provenance": (
            f"{stats['awards']} avis d'attribution TED parcourus ; disjonction vérifiée "
            "par empreinte de document et par award contre DEV, HELD-OUT-1, DEV-2 et DEV-3"
        ),
        "acquisition_stats": dict(stats),
        "sources": sources,
        "rows": [s.as_dict() for s in snapshots],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--awards", type=int, default=600)
    parser.add_argument("--days", type=int, default=40)
    parser.add_argument("--per-document", type=int, default=14)
    parser.add_argument("--target-dossiers", type=int, default=12)
    parser.add_argument("--pause", type=float, default=0.3)
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--execution-kinds",
        action="store_true",
        help="ne garder que cahiers des charges, projets de contrat et bordereaux",
    )
    parser.add_argument(
        "--countries",
        default="",
        help="codes pays TED (ISO-3) séparés par une virgule, ex. FRA,BEL,LUX,CHE",
    )
    parser.add_argument(
        "--languages",
        default="",
        help="codes langue à conserver, séparés par une virgule, ex. fr",
    )
    args = parser.parse_args()

    corpus = build(
        awards=args.awards,
        days=args.days,
        per_document=args.per_document,
        target_dossiers=args.target_dossiers,
        pause=args.pause,
        kinds=CORPUS_KINDS if args.execution_kinds else None,
        countries=[c.strip() for c in args.countries.split(",") if c.strip()],
        languages=[lang.strip() for lang in args.languages.split(",") if lang.strip()],
    )
    rows = corpus["rows"]
    dossiers = len({row["award_reference"] for row in rows})  # type: ignore[index]
    print(f"\ncandidats : {len(rows)}", file=sys.stderr)  # type: ignore[arg-type]
    print(f"dossiers  : {dossiers}", file=sys.stderr)
    print(f"stats     : {corpus['acquisition_stats']}", file=sys.stderr)

    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(corpus, ensure_ascii=False, indent=1))
        print(f"écrit : {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
