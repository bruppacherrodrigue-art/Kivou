"""Assemblage du gold SIGNAL-100 depuis les revues d'adjudication (SPEC-009 §30).

Collecte les lots produits par les deux perspectives indépendantes, exige un
arbitrage là où §30 l'impose, et écrit le gold. Toute revue malformée ou
manquante fait échouer bruyamment : un banc commercial ne se complète pas au
jugé.

Aucun réseau. Aucun score n'entre ici — les revues n'en ont jamais vu.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
from typing import Any

from signals.research.signal100 import workdir
from signals.research.signal100_adjudication import (
    AdjudicationError,
    assemble,
    needs_arbitration,
)


def load_reviews(directory: pathlib.Path, pattern: str) -> dict[str, dict]:
    """Fusionne les lots d'un rôle, en refusant tout doublon de `signal_id`."""
    reviews: dict[str, dict] = {}
    files = sorted(directory.glob(pattern))
    if not files:
        raise AdjudicationError(f"aucun lot ne correspond à {pattern} dans {directory}")
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("reviews", payload)
        for row in rows:
            sid = row["signal_id"]
            if sid in reviews:
                raise AdjudicationError(f"{sid} jugé deux fois dans {pattern}")
            reviews[sid] = row
    return reviews


def pending_arbitrations(
    signals: list[dict], reviews_a: dict[str, dict], reviews_b: dict[str, dict]
) -> list[dict[str, Any]]:
    """Les signaux qui exigent une troisième adjudication indépendante (§30)."""
    pending = []
    for snapshot in signals:
        sid = snapshot["signal_id"]
        if sid not in reviews_a or sid not in reviews_b:
            continue
        if needs_arbitration(reviews_a[sid], reviews_b[sid]):
            pending.append(
                {
                    "signal_id": sid,
                    "reason": (
                        "verdict D présent"
                        if "D" in (reviews_a[sid]["verdict"], reviews_b[sid]["verdict"])
                        else "divergence de plus d'un grade"
                    ),
                }
            )
    return pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemblage du gold SIGNAL-100")
    parser.add_argument("--reviews", required=True, help="dossier des lots d'adjudication")
    parser.add_argument("--corpus", default="signal100_corpus.json")
    parser.add_argument("--out", default="signal100_gold.json")
    parser.add_argument(
        "--list-arbitrations",
        action="store_true",
        help="n'écrit rien : liste les signaux qui exigent un arbitrage (§30)",
    )
    args = parser.parse_args(argv)

    out = workdir()
    signals = json.loads((out / args.corpus).read_text(encoding="utf-8"))["signals"]
    directory = pathlib.Path(args.reviews)

    reviews_a = load_reviews(directory, "reviewer_a_batch_*.json")
    reviews_b = load_reviews(directory, "reviewer_b_batch_*.json")

    if args.list_arbitrations:
        pending = pending_arbitrations(signals, reviews_a, reviews_b)
        print(json.dumps({"count": len(pending), "signals": pending}, ensure_ascii=False, indent=1))
        return 0

    arbitrations: dict[str, dict] = {}
    if list(directory.glob("arbitration_batch_*.json")):
        arbitrations = load_reviews(directory, "arbitration_batch_*.json")

    records = assemble(signals, reviews_a, reviews_b, arbitrations)
    payload = {
        "gold": "SIGNAL-100-GOLD",
        "rubric": "commercial-signal-rubric-v1",
        "size": len(records),
        "composition": dict(collections.Counter(r["final_verdict"] for r in records)),
        "records": records,
    }
    (out / args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "records"}, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
