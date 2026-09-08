"""Acquisition fraîche SPEC-009C — un seul client, un seul ICP, un seul feed.

Ce module n'apporte aucun connecteur et n'en modifie aucun : il réutilise
`acquire_ted` et `acquire_simap` de SPEC-009 tels quels. Sa seule raison d'être
est l'ensemble des identités à éviter.

`prior_identities()` couvre SPEC-005, SPEC-007 et SPEC-008, mais **pas** le pool
SPEC-009 — qui est pourtant la source unique dont SPEC-009, SPEC-009A,
SPEC-009B, WEDGE-HARDENING R1 et R2 ont tous tiré. SPEC-009C §7 exige une
intersection nulle avec les cinq : c'est donc le pool qu'il faut ajouter, à ses
quatre niveaux d'identité.

    Fenêtre (§8)
    ────────────
    L'ICP du wedge refuse tout signal de plus de 120 jours. La fenêtre
    interrogée est donc exactement celle où ce client accepterait quelque
    chose — pas une fenêtre élargie pour gonfler le volume. Le pool de
    développement occupe une partie de cet intervalle ; ses identités sont
    écartées une à une, ce qui laisse le reste de la fenêtre, jamais utilisé.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from typing import Any

from signals.research.signal100 import (
    identities,
    load_rows,
    prior_identities,
    workdir,
)
from signals.research.signal100_run import (
    MAX_AWARD_LOTS_PER_NOTICE,
    acquire_simap,
    acquire_ted,
)

#: Le pool dont tout le développement du wedge est issu.
DEVELOPMENT_POOL = "signal100_pool_corpus.json"


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
    for level, values in identities(load_rows(workdir() / DEVELOPMENT_POOL)).items():
        prior[level] |= values

    existing: list[dict] = []
    if extend:
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
        "corpus": "SPEC-009C-FRESH",
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
                "SPEC-009 pool (tests/fixtures/signal100/signal100_pool_corpus.json)",
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
    parser = argparse.ArgumentParser(description="Acquisition fraîche SPEC-009C")
    parser.add_argument("--ted-lots", type=int, default=600)
    parser.add_argument("--simap-lots", type=int, default=400)
    parser.add_argument("--days", type=int, default=120, help="fenêtre TED en jours")
    parser.add_argument("--since", default="2026-04-20", help="date SIMAP la plus ancienne")
    parser.add_argument("--pause", type=float, default=0.35)
    parser.add_argument("--max-ted-notices", type=int, default=2500)
    parser.add_argument("--max-simap-publications", type=int, default=1500)
    parser.add_argument("--out", default="spec009c_corpus.json")
    parser.add_argument("--extend", default=None)
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
