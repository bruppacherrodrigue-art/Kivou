"""Construction du banc SIGNAL-100 à partir du corpus frais (SPEC-009 §11–§16).

Enchaîne, sans réseau et sans aléa : pipeline gelé → pool `show` → déduplication
par award-lot → sélection stratifiée → snapshots → vues aveugles → shadow set.

Ce script ne juge rien. L'adjudication commerciale vient après, sur les vues
aveugles qu'il écrit, et ne doit jamais voir ce que le moteur a conclu (§28).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
from collections.abc import Sequence
from typing import Any

from signals.matching import MATCH_POLICY_VERSION, REFERENCE_ICPS, SCORE_POLICY_VERSION
from signals.research.signal100 import (
    best_match_per_award_lot,
    cap_award_lots_per_notice,
    disjointness_report,
    load_rows,
    prior_identities,
    signal_id,
    terciles,
    workdir,
)
from signals.research.signal100_pipeline import (
    LotRun,
    funnel,
    has_identified_winner,
    pool_entries,
    run_pipeline,
)
from signals.research.signal100_select import select_signal100
from signals.research.signal100_snapshot import blind_view, build_snapshot, render_signal_text

#: §12 — en deçà, le pool ne permet pas de composer un banc sans tout garder.
MIN_NATURAL_SHOW_SIGNALS = 120

#: §47 — contrôle négatif, hors gates.
SHADOW_PER_DECISION = 50

ICP_BY_ID = {icp.icp_id: icp for icp in REFERENCE_ICPS}


def _index(runs: Sequence[LotRun]) -> dict[tuple, LotRun]:
    return {run.lot.key: run for run in runs}


def _match_of(run: LotRun, icp_id: str) -> Any:
    for match in run.matches:
        if match.icp_id == icp_id:
            return match
    raise KeyError(f"aucun match {icp_id} pour {run.lot.key}")


def _snapshot_pair(run: LotRun, icp_id: str) -> tuple[dict, dict, str]:
    match = _match_of(run, icp_id)
    icp = ICP_BY_ID[icp_id]
    sid = signal_id(run.lot.key, icp_id, MATCH_POLICY_VERSION, SCORE_POLICY_VERSION)
    snapshot = build_snapshot(run, match, icp, signal_id=sid)
    return snapshot, blind_view(snapshot, run, match, icp), render_signal_text(snapshot)


def _shadow(runs: Sequence[LotRun], decision: str, *, size: int) -> list[dict]:
    """Un échantillon déterministe d'une décision non montrée (§47).

    Les `exclude` ont tous un score nul : les stratifier par score n'aurait pas
    de sens. L'ordre est donc (source, `signal_id`), et le tour de rôle entre
    sources évite un contrôle négatif entièrement suisse ou entièrement TED.
    """
    entries = best_match_per_award_lot(pool_entries(runs, decision=decision))
    by_source: dict[str, list] = collections.defaultdict(list)
    for entry in sorted(entries, key=lambda e: (e.source, e.signal_id)):
        by_source[entry.source].append(entry)

    picked: list = []
    cursor = 0
    while len(picked) < size and any(by_source.values()):
        for source in sorted(by_source):
            if len(picked) >= size:
                break
            if cursor < len(by_source[source]):
                picked.append(by_source[source][cursor])
        cursor += 1
        if all(cursor >= len(values) for values in by_source.values()):
            break

    index = _index(runs)
    shadow = []
    for entry in picked[:size]:
        snapshot, blind, _text = _snapshot_pair(index[entry.award_key], entry.icp_id)
        shadow.append({"decision": decision, "blind": blind, "engine": snapshot["score"]})
    return shadow


def build(*, corpus_name: str, as_of: dt.date) -> dict[str, Any]:
    out = workdir()
    rows = load_rows(out / corpus_name)

    prior = prior_identities()
    disjointness = disjointness_report(rows, prior)

    runs = run_pipeline(rows, as_of=as_of)
    report: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "disjointness": disjointness,
        "funnel": funnel(runs),
    }

    # §57 — un signal sans gagnant nommé n'a pas de « WHO » et ne peut pas
    # produire de snapshot. Le compte est publié, pas dissimulé.
    show_all = pool_entries(runs, decision="show")
    index = _index(runs)
    with_winner = [e for e in show_all if has_identified_winner(index[e.award_key].lot)]
    unique = cap_award_lots_per_notice(best_match_per_award_lot(with_winner))

    report["pool"] = {
        "show_pairs": len(show_all),
        "show_pairs_dropped_without_identified_winner": len(show_all) - len(with_winner),
        "unique_show_signals": len(unique),
        "minimum_required": MIN_NATURAL_SHOW_SIGNALS,
        "sufficient": len(unique) >= MIN_NATURAL_SHOW_SIGNALS,
        "score_distribution": dict(
            sorted(collections.Counter(e.normalized_score for e in unique).items())
        ),
    }
    if len(unique) < MIN_NATURAL_SHOW_SIGNALS:
        report["blocked"] = "SPEC-009 BLOCKED — INSUFFICIENT NATURAL SHOW VOLUME"
        (out / "signal100_pool_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return report

    selected, compliance = select_signal100(unique)
    report["selection"] = compliance

    zones = terciles(unique)
    tercile_of = {e.signal_id: name for name, entries in zones.items() for e in entries}

    snapshots, blinds, texts = [], [], {}
    for entry in selected:
        snapshot, blind, text = _snapshot_pair(index[entry.award_key], entry.icp_id)
        snapshot["tercile"] = tercile_of[entry.signal_id]
        snapshots.append(snapshot)
        blinds.append(blind)
        texts[snapshot["signal_id"]] = text

    (out / "signal100_corpus.json").write_text(
        json.dumps(
            {
                "corpus": "SIGNAL-100",
                "unit": "award-lot × TargetICP",
                "as_of": as_of.isoformat(),
                "size": len(snapshots),
                "selection_policy": compliance,
                "disjointness": disjointness,
                "signals": snapshots,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (out / "signal100_blind.json").write_text(
        json.dumps(
            {
                "view": "blind-commercial-review",
                "rubric": "commercial-signal-rubric-v1",
                "signals": blinds,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (out / "signal100_text.json").write_text(
        json.dumps(texts, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / "signal100_shadow.json").write_text(
        json.dumps(
            {
                "control": "shadow-negative",
                "note": "hors gates SPEC-009 (§47)",
                "borderline": _shadow(runs, "borderline", size=SHADOW_PER_DECISION),
                "exclude": _shadow(runs, "exclude", size=SHADOW_PER_DECISION),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (out / "signal100_pool_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construction du banc SIGNAL-100 (SPEC-009)")
    parser.add_argument("--corpus", default="signal100_pool_corpus.json")
    parser.add_argument("--as-of", default="2026-08-17")
    args = parser.parse_args(argv)

    report = build(corpus_name=args.corpus, as_of=dt.date.fromisoformat(args.as_of))
    print(json.dumps({k: v for k, v in report.items() if k != "disjointness"}, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
