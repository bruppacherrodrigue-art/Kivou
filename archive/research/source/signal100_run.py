"""Acquisition fraîche SIGNAL-100 (SPEC-009 §9, §11) — script de recherche.

Ce module touche au réseau : il ne fait donc PAS partie de la suite normale
(§58). Il n'écrit qu'un corpus canonique ; aucun moteur n'est appelé ici, aucune
décision commerciale n'est prise.

Sources autorisées : les connecteurs de production TED et SIMAP, tels quels.
Aucun nouveau connecteur, aucun portail français (§9).

Discipline VPS (§55) : clients fermés par `with`, pagination bornée, pause entre
requêtes, écriture unique en fin de course sur un dossier de travail
déterministe, aucun cache disque laissé derrière.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime as dt
import json
import sys
import time
from collections.abc import Callable
from typing import Any

from signals.connectors.simap.client import SimapClient
from signals.connectors.simap.errors import SimapError
from signals.connectors.simap.mapping import map_publication
from signals.connectors.simap.parser import parse_publication
from signals.connectors.ted.client import NoticeRef, TedClient
from signals.connectors.ted.errors import TedError, TedHttpError
from signals.connectors.ted.mapping import map_notice
from signals.connectors.ted.parser import parse_notice
from signals.research.signal100 import (
    award_identity,
    identities,
    load_rows,
    prior_identities,
    workdir,
)

#: Fenêtre TED : `form-type=result` = les avis d'attribution. Le tri décroissant
#: rend la pagination stable pendant la course.
TED_QUERY = "form-type=result AND publication-date>=today(-{days}) SORT BY publication-number DESC"

#: Au plus deux award-lots par notice dès l'acquisition (§8) : une notice à
#: quarante lots ne doit pas coloniser le pool ni le banc.
MAX_AWARD_LOTS_PER_NOTICE = 2

#: Les seules familles SIMAP qui produisent un `ContractAward`. Concours et
#: mandats d'étude publient un classement et des prix, pas un contrat : le
#: mapping les refuse déjà (`not-a-contract-award`). Les interroger ne
#: sélectionne rien, cela dépense des requêtes pour zéro award-lot.
SIMAP_CONTRACT_AWARD_TYPES = ("award_tender", "direct_award")


@dataclasses.dataclass
class Acquisition:
    """Le compte rendu d'une source — ce qui est entré, ce qui a été écarté."""

    fetched: int = 0
    parsed: int = 0
    failed: int = 0
    skipped_used: int = 0
    notices_kept: int = 0
    award_lots: int = 0
    lots_capped: int = 0
    failures: list[str] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items() if k != "failures"}
        data["failures"] = self.failures[:20]
        return data


def _row(source: str, notice: str, event: Any, award: Any) -> dict[str, Any]:
    return {
        "source": source,
        "notice": notice,
        "event": event.model_dump(mode="json"),
        "award": award.model_dump(mode="json"),
    }


def _collides(row: dict, prior: dict[str, set]) -> str | None:
    """Le niveau d'identité par lequel une ligne fuite depuis un corpus antérieur."""
    provenance = row["event"]["provenance"]
    system = provenance["source_system"]
    if (row["source"], row["notice"]) in prior["publication"]:
        return "publication"
    if (system, provenance["source_notice_id"]) in prior["notice"]:
        return "notice"
    procedure = provenance.get("source_procedure_id")
    if procedure is not None and (system, procedure) in prior["procedure"]:
        return "procedure"
    if award_identity(row) in prior["award identity"]:
        return "award identity"
    return None


def _sleep(pause: float) -> None:
    if pause > 0:
        time.sleep(pause)


# ─── TED ────────────────────────────────────────────────────────────────────────


def acquire_ted(
    *,
    wanted_lots: int,
    days: int,
    pause: float,
    prior: dict[str, set],
    max_notices: int,
) -> tuple[list[dict], Acquisition]:
    report = Acquisition()
    rows: list[dict] = []
    if wanted_lots <= 0 or max_notices <= 0:
        return rows, report

    with TedClient() as client:
        refs = _search_ted(client, TED_QUERY.format(days=days), wanted=max_notices, pause=pause)
        print(f"TED : {len(refs)} notices candidates (fenêtre {days} j)", file=sys.stderr)

        for index, ref in enumerate(refs, start=1):
            if report.award_lots >= wanted_lots:
                break
            if ("ted", ref.publication_number) in prior["publication"]:
                report.skipped_used += 1
                continue

            report.fetched += 1
            try:
                xml = _fetch_ted_xml(client, ref.publication_number, pause=pause)
                extraction = map_notice(parse_notice(xml), retrieved_at=dt.datetime.now(dt.UTC))
            except TedError as exc:
                report.failed += 1
                report.failures.append(f"{ref.publication_number}: {exc}")
                continue
            report.parsed += 1

            kept = 0
            for award in extraction.awards:
                if kept >= MAX_AWARD_LOTS_PER_NOTICE:
                    report.lots_capped += 1
                    continue
                row = _row("ted", ref.publication_number, extraction.event, award)
                if _collides(row, prior) is not None:
                    report.skipped_used += 1
                    continue
                rows.append(row)
                kept += 1
            if kept:
                report.notices_kept += 1
                report.award_lots += kept
            if index % 25 == 0:
                print(
                    f"TED [{index}/{len(refs)}] award-lots={report.award_lots}",
                    file=sys.stderr,
                )
    return rows, report


def _retry_429(call: Callable[[], Any], *, what: str, pause: float, attempts: int = 5) -> Any:
    """Rejoue un appel TED limité en débit, à délai croissant.

    TED plafonne le débit des réutilisateurs sur la recherche COMME sur le XML :
    un repli qui ne couvre que le téléchargement casse la course en pleine
    pagination. Le connecteur SPEC-002 est gelé (§6) — le repli vit donc ici,
    dans le script de recherche, et laisse remonter un échec durable.
    """
    delay = max(pause, 1.0)
    for attempt in range(attempts):
        try:
            return call()
        except TedHttpError as exc:
            if exc.status_code != 429 or attempt == attempts - 1:
                raise
            wait = delay * 2 ** (attempt + 1)
            print(f"TED 429 sur {what} — pause {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("boucle de repli TED sortie sans résultat")  # pragma: no cover


def _search_ted(client: TedClient, query: str, *, wanted: int, pause: float) -> list[NoticeRef]:
    """Pagination bornée avec repli 429, page par page.

    `TedClient.search_all` est gelé et ne sait pas rejouer une page refusée :
    on repagine ici en réutilisant sa méthode `search`, sans le modifier.
    """
    collected: list[NoticeRef] = []
    for page in range(1, 61):
        remaining = wanted - len(collected)
        if remaining <= 0:
            break
        size = min(50, remaining)
        rows, _total = _retry_429(
            lambda p=page, n=size: client.search(query, limit=n, page=p),
            what=f"recherche page {page}",
            pause=pause,
        )
        collected.extend(rows)
        if not rows:
            break
        _sleep(pause)
    return collected[:wanted]


def _fetch_ted_xml(client: TedClient, publication_number: str, *, pause: float) -> bytes:
    """Téléchargement d'un XML, même repli 429 que la recherche."""
    payload = _retry_429(
        lambda: client.fetch_notice_xml(publication_number),
        what=f"XML {publication_number}",
        pause=pause,
    )
    _sleep(pause)
    return payload


# ─── SIMAP ──────────────────────────────────────────────────────────────────────


def acquire_simap(
    *,
    wanted_lots: int,
    since: str,
    pause: float,
    prior: dict[str, set],
    max_publications: int,
    pub_types: tuple[str, ...] = SIMAP_CONTRACT_AWARD_TYPES,
) -> tuple[list[dict], Acquisition]:
    report = Acquisition()
    rows: list[dict] = []
    if wanted_lots <= 0 or max_publications <= 0:
        return rows, report

    with SimapClient() as client:
        refs = client.search_all_awards(
            wanted=max_publications,
            published_from=since,
            pub_type_filters=pub_types,
            max_pages_per_filter=40,
        )
        print(f"SIMAP : {len(refs)} publications candidates (depuis {since})", file=sys.stderr)

        for index, ref in enumerate(refs, start=1):
            if report.award_lots >= wanted_lots:
                break
            notice = f"{ref.project_id}/{ref.publication_id}"
            if ("simap", notice) in prior["publication"]:
                report.skipped_used += 1
                continue

            report.fetched += 1
            try:
                payload = client.fetch_publication(ref.project_id, ref.publication_id)
                publication = parse_publication(payload, search_entry=ref.search_entry)
                extraction = map_publication(publication, retrieved_at=dt.datetime.now(dt.UTC))
            except SimapError as exc:
                report.failed += 1
                report.failures.append(f"{notice}: {exc}")
                continue
            finally:
                _sleep(pause)
            report.parsed += 1

            kept = 0
            for award in extraction.awards:
                if kept >= MAX_AWARD_LOTS_PER_NOTICE:
                    report.lots_capped += 1
                    continue
                row = _row("simap", notice, extraction.event, award)
                if _collides(row, prior) is not None:
                    report.skipped_used += 1
                    continue
                rows.append(row)
                kept += 1
            if kept:
                report.notices_kept += 1
                report.award_lots += kept
            if index % 25 == 0:
                print(
                    f"SIMAP [{index}/{len(refs)}] award-lots={report.award_lots}",
                    file=sys.stderr,
                )
    return rows, report


# ─── Course ─────────────────────────────────────────────────────────────────────


def run(
    *,
    ted_lots: int,
    simap_lots: int,
    days: int,
    since: str,
    pause: float,
    max_ted_notices: int,
    max_simap_publications: int,
    out_name: str,
    extend: str | None = None,
) -> dict[str, Any]:
    prior = prior_identities()
    existing: list[dict] = []
    if extend:
        # Extension d'un pool déjà acquis (§11) : ses propres identités
        # rejoignent l'ensemble à éviter, sinon la course reprendrait les mêmes
        # notices en tête de liste et n'ajouterait rien.
        existing = load_rows(workdir() / extend)
        for level, values in identities(existing).items():
            prior[level] |= values
        print(f"extension : {len(existing)} award-lots déjà acquis", file=sys.stderr)
    print(
        "identités déjà consommées : "
        + ", ".join(f"{level}={len(values)}" for level, values in prior.items()),
        file=sys.stderr,
    )

    ted_rows, ted_report = acquire_ted(
        wanted_lots=ted_lots,
        days=days,
        pause=pause,
        prior=prior,
        max_notices=max_ted_notices,
    )
    simap_rows, simap_report = acquire_simap(
        wanted_lots=simap_lots,
        since=since,
        pause=pause,
        prior=prior,
        max_publications=max_simap_publications,
    )

    rows = existing + ted_rows + simap_rows
    payload = {
        "corpus": "SIGNAL-100-POOL",
        "extended_from": extend,
        "built_at": dt.datetime.now(dt.UTC).date().isoformat(),
        "unit": "award-lot",
        "window": {"ted_days": days, "simap_since": since},
        "acquisition": {
            "ted": ted_report.as_dict(),
            "simap": simap_report.as_dict(),
            "award_lots": len(rows),
            "max_award_lots_per_notice": MAX_AWARD_LOTS_PER_NOTICE,
        },
        "disjointness": {
            "levels": list(prior),
            "against": [
                "SPEC-005/007 DEV (tests/fixtures/contract100/awards.json)",
                "SPEC-007 DEV (tests/fixtures/needs/need100_dev.json)",
                "SPEC-007 held-out (tests/fixtures/needs/need100_heldout_corpus.json)",
                "SPEC-007 final (tests/fixtures/needs/need_final_corpus.json)",
                "SPEC-008 final (tests/fixtures/matching/signal_match_final_corpus.json)",
            ],
        },
        "rows": rows,
    }

    target = workdir() / out_name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    per_source = collections.Counter(row["source"] for row in rows)
    print(f"\n{len(rows)} award-lots écrits dans {target} — {dict(per_source)}", file=sys.stderr)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquisition fraîche SIGNAL-100 (SPEC-009)")
    parser.add_argument("--ted-lots", type=int, default=260)
    parser.add_argument("--simap-lots", type=int, default=240)
    parser.add_argument("--days", type=int, default=88, help="fenêtre TED en jours")
    parser.add_argument("--since", default="2026-05-21", help="date SIMAP la plus ancienne")
    parser.add_argument("--pause", type=float, default=0.35)
    parser.add_argument("--max-ted-notices", type=int, default=900)
    parser.add_argument("--max-simap-publications", type=int, default=900)
    parser.add_argument("--out", default="signal100_pool_corpus.json")
    parser.add_argument(
        "--extend",
        default=None,
        help="corpus existant a etendre : ses identites rejoignent l'ensemble evite",
    )
    args = parser.parse_args(argv)

    run(
        ted_lots=args.ted_lots,
        simap_lots=args.simap_lots,
        days=args.days,
        since=args.since,
        pause=args.pause,
        max_ted_notices=args.max_ted_notices,
        max_simap_publications=args.max_simap_publications,
        out_name=args.out,
        extend=args.extend,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
