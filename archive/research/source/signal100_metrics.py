"""Métriques et gates SIGNAL-100 (SPEC-009 §31, §33–§45).

Ce module ne juge pas et ne règle rien : il compte. Il est appelé APRÈS le gel du
gold (§32), pour que la comparaison entre verdicts commerciaux et scores moteur
ne puisse pas rétroagir sur l'adjudication.

Un gate qui échoue est rapporté tel quel. SPEC-009 est une évaluation, pas une
boucle de tuning (§46) : aucune fonction ici ne propose de correction.
"""

from __future__ import annotations

import collections
import statistics
from collections.abc import Sequence
from typing import Any

VERDICTS = ("A", "B", "C", "D")
VERDICT_RANK = {verdict: index for index, verdict in enumerate(VERDICTS)}

USEFUL = ("A", "B")

#: Les gates de §34–§39. `min`/`max` sont exprimés en pourcentage du banc.
GATES = {
    "useful_precision": {"min": 90.0, "spec": "§34"},
    "actionable_rate": {"min": 60.0, "spec": "§35"},
    "weak_rate": {"max": 10.0, "spec": "§37"},
    "false_rate": {"max": 2.0, "spec": "§36"},
    "critical_false_signals": {"max": 0, "spec": "§36", "absolute": True},
    "factual_integrity_rate": {"min": 99.0, "spec": "§36"},
    "timing_errors": {"max": 0, "spec": "§36", "absolute": True},
    "proof_coverage": {"min": 100.0, "spec": "§36"},
    "critical_overclaiming": {"max": 0, "spec": "§36", "absolute": True},
    "top20_useful_precision": {"min": 95.0, "spec": "§39"},
    "top20_critical_false": {"max": 0, "spec": "§39", "absolute": True},
    "rubric_agreement_within_one": {"min": 90.0, "spec": "§31"},
}

#: Diagnostic fort, explicitement NON bloquant (§40).
DIAGNOSTIC_BOTTOM_THIRD_MIN = 80.0

#: Gate conditionnel : ne s'applique qu'aux sources d'au moins 20 signaux (§42).
SOURCE_GATE_MIN_SIGNALS = 20
SOURCE_GATE_MIN_PRECISION = 85.0


def _pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def _useful_precision(records: Sequence[dict]) -> float:
    return _pct(sum(1 for r in records if r["final_verdict"] in USEFUL), len(records))


def agreement(records: Sequence[dict]) -> dict[str, Any]:
    """La stabilité de la doctrine commerciale (§31).

    L'écart se mesure sur l'ordre A < B < C < D. « Dans un grade » veut dire
    distance <= 1 : c'est la tolérance que §31 gate à 90 %.
    """
    exact = within_one = 0
    distances: collections.Counter[int] = collections.Counter()
    for record in records:
        a = VERDICT_RANK[record["review_a"]["verdict"]]
        b = VERDICT_RANK[record["review_b"]["verdict"]]
        distance = abs(a - b)
        distances[distance] += 1
        exact += distance == 0
        within_one += distance <= 1
    total = len(records)
    return {
        "signals": total,
        "exact_agreement": exact,
        "exact_agreement_rate": _pct(exact, total),
        "agreement_within_one_grade": within_one,
        "agreement_within_one_grade_rate": _pct(within_one, total),
        "disagreements": total - exact,
        "distance_histogram": dict(sorted(distances.items())),
        "arbitrations": sum(1 for r in records if r.get("arbitration")),
        "distribution_a": dict(collections.Counter(r["review_a"]["verdict"] for r in records)),
        "distribution_b": dict(collections.Counter(r["review_b"]["verdict"] for r in records)),
        "distribution_final": dict(collections.Counter(r["final_verdict"] for r in records)),
    }


def _dimension_counts(records: Sequence[dict]) -> dict[str, Any]:
    dims = collections.defaultdict(collections.Counter)
    for record in records:
        for name, grade in record["final_dimensions"].items():
            dims[name][grade] += 1
    return {name: dict(counter) for name, counter in dims.items()}


def safety(records: Sequence[dict]) -> dict[str, Any]:
    """Les compteurs de sûreté de §36 — chacun est un gate absolu ou presque."""
    total = len(records)
    dims = [r["final_dimensions"] for r in records]
    factual_pass = sum(1 for d in dims if d.get("factual_integrity") == "pass")
    proof_ok = sum(1 for d in dims if d.get("proof") in ("strong", "adequate"))
    return {
        "critical_false_signals": sum(1 for r in records if r.get("critical_false_signal")),
        "factual_integrity_failures": total - factual_pass,
        "factual_integrity_rate": _pct(factual_pass, total),
        "timing_errors": sum(1 for d in dims if d.get("timing") == "wrong"),
        "proof_failures": total - proof_ok,
        "proof_coverage": _pct(proof_ok, total),
        "critical_overclaiming": sum(1 for r in records if r.get("critical_overclaiming")),
        "need_credibility_failures": sum(
            1 for d in dims if d.get("need") in ("unsupported", "contradicted")
        ),
        "icp_fit_failures": sum(1 for d in dims if d.get("icp_fit") == "no_fit"),
        "generic_signals": sum(1 for d in dims if d.get("specificity") == "generic"),
    }


def headline(records: Sequence[dict]) -> dict[str, Any]:
    """Les métriques principales de §33."""
    total = len(records)
    counts = collections.Counter(r["final_verdict"] for r in records)
    return {
        "signals_evaluated": total,
        "A_actionable": counts["A"],
        "B_useful": counts["B"],
        "C_weak": counts["C"],
        "D_false_or_misleading": counts["D"],
        "actionable_rate": _pct(counts["A"], total),
        "useful_precision": _pct(counts["A"] + counts["B"], total),
        "weak_rate": _pct(counts["C"], total),
        "false_rate": _pct(counts["D"], total),
        "dimensions": _dimension_counts(records),
    }


def _scores(records: Sequence[dict]) -> list[int]:
    return [r["normalized_score"] for r in records]


def calibration(records: Sequence[dict]) -> dict[str, Any]:
    """Le score prédit-il le verdict commercial ? (§38)"""
    by_verdict: dict[str, list[int]] = collections.defaultdict(list)
    for record in records:
        by_verdict[record["final_verdict"]].append(record["normalized_score"])

    per_verdict = {}
    for verdict in VERDICTS:
        values = sorted(by_verdict.get(verdict, []))
        if not values:
            per_verdict[verdict] = {"count": 0}
            continue
        quantiles = (
            statistics.quantiles(values, n=4)
            if len(values) >= 2
            else [values[0], values[0], values[0]]
        )
        per_verdict[verdict] = {
            "count": len(values),
            "median": statistics.median(values),
            "p25": round(quantiles[0], 1),
            "p75": round(quantiles[2], 1),
            "min": values[0],
            "max": values[-1],
        }

    by_tercile: dict[str, list[dict]] = collections.defaultdict(list)
    for record in records:
        by_tercile[record["tercile"]].append(record)

    per_tercile = {
        name: {
            "count": len(rows),
            "actionable_rate": _pct(sum(1 for r in rows if r["final_verdict"] == "A"), len(rows)),
            "useful_precision": _useful_precision(rows),
            "median_score": statistics.median(_scores(rows)) if rows else None,
        }
        for name, rows in sorted(by_tercile.items())
    }

    medians = {v: per_verdict[v].get("median") for v in VERDICTS}
    ordered = [medians[v] for v in VERDICTS if medians[v] is not None]
    return {
        "per_verdict": per_verdict,
        "per_tercile": per_tercile,
        "median_order_holds": ordered == sorted(ordered, reverse=True),
        "median_order_observed": medians,
    }


def _breakdown(records: Sequence[dict], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for record in records:
        value = record.get(key)
        for item in value if isinstance(value, list) else [value]:
            groups[str(item)].append(record)
    return {
        name: {
            "signals": len(rows),
            "A": sum(1 for r in rows if r["final_verdict"] == "A"),
            "B": sum(1 for r in rows if r["final_verdict"] == "B"),
            "C": sum(1 for r in rows if r["final_verdict"] == "C"),
            "D": sum(1 for r in rows if r["final_verdict"] == "D"),
            "useful_precision": _useful_precision(rows),
            "median_score": statistics.median(_scores(rows)),
        }
        for name, rows in sorted(groups.items())
    }


def distributions(records: Sequence[dict]) -> dict[str, Any]:
    """Les analyses par source, ICP, catégorie de besoin et type de contrat."""
    return {
        "source": _breakdown(records, "source"),
        "icp": _breakdown(records, "icp_id"),
        "need_category": _breakdown(records, "matched_needs"),
        "contract_type": _breakdown(records, "contract_type"),
    }


def failure_attribution(records: Sequence[dict]) -> dict[str, Any]:
    """Chaque C et D rattaché à une seule couche responsable (§45)."""
    failures = [r for r in records if r["final_verdict"] in ("C", "D")]
    primary = collections.Counter(
        r.get("primary_failure_layer") or "unattributed" for r in failures
    )
    secondary: collections.Counter[str] = collections.Counter()
    for record in failures:
        secondary.update(record.get("secondary_failure_layers") or [])
    return {
        "failing_signals": len(failures),
        "primary_failure_layer": dict(primary.most_common()),
        "secondary_failure_layers": dict(secondary.most_common()),
        "cases": [
            {
                "signal_id": r["signal_id"],
                "verdict": r["final_verdict"],
                "icp_id": r["icp_id"],
                "source": r["source"],
                "normalized_score": r["normalized_score"],
                "primary_failure_layer": r.get("primary_failure_layer"),
                "secondary_failure_layers": r.get("secondary_failure_layers") or [],
                "why": r.get("final_note"),
            }
            for r in sorted(failures, key=lambda r: (r["final_verdict"], -r["normalized_score"]))
        ],
    }


def top20(records: Sequence[dict]) -> dict[str, Any]:
    """Les vingt meilleurs scores : ce que le futur feed mettrait en avant (§39)."""
    best = sorted(records, key=lambda r: (-r["normalized_score"], r["signal_id"]))[:20]
    return {
        "signals": len(best),
        "useful_precision": _useful_precision(best),
        "critical_false": sum(1 for r in best if r.get("critical_false_signal")),
        "distribution": dict(collections.Counter(r["final_verdict"] for r in best)),
        "score_range": [best[-1]["normalized_score"], best[0]["normalized_score"]] if best else [],
    }


def bottom_third(records: Sequence[dict]) -> dict[str, Any]:
    """Le tiers inférieur encore `show` — diagnostic de seuil, non bloquant (§40)."""
    rows = [r for r in records if r["tercile"] == "bottom"]
    precision = _useful_precision(rows)
    return {
        "signals": len(rows),
        "useful_precision": precision,
        "diagnostic_threshold": DIAGNOSTIC_BOTTOM_THIRD_MIN,
        "diagnostic_met": precision >= DIAGNOSTIC_BOTTOM_THIRD_MIN,
        "blocking": False,
        "distribution": dict(collections.Counter(r["final_verdict"] for r in rows)),
    }


def source_gate(records: Sequence[dict]) -> dict[str, Any]:
    """§42 — une source d'au moins 20 signaux doit tenir 85 % de précision utile."""
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for record in records:
        groups[record["source"]].append(record)
    results = {}
    for source, rows in sorted(groups.items()):
        precision = _useful_precision(rows)
        applies = len(rows) >= SOURCE_GATE_MIN_SIGNALS
        results[source] = {
            "signals": len(rows),
            "useful_precision": precision,
            "gate_applies": applies,
            "gate_passed": (precision >= SOURCE_GATE_MIN_PRECISION) if applies else None,
        }
    return results


def evaluate_gates(records: Sequence[dict]) -> dict[str, Any]:
    """Confronte les métriques aux gates de §59 et rend un verdict global."""
    head = headline(records)
    safe = safety(records)
    best = top20(records)
    agree = agreement(records)

    observed = {
        "useful_precision": head["useful_precision"],
        "actionable_rate": head["actionable_rate"],
        "weak_rate": head["weak_rate"],
        "false_rate": head["false_rate"],
        "critical_false_signals": safe["critical_false_signals"],
        "factual_integrity_rate": safe["factual_integrity_rate"],
        "timing_errors": safe["timing_errors"],
        "proof_coverage": safe["proof_coverage"],
        "critical_overclaiming": safe["critical_overclaiming"],
        "top20_useful_precision": best["useful_precision"],
        "top20_critical_false": best["critical_false"],
        "rubric_agreement_within_one": agree["agreement_within_one_grade_rate"],
    }

    results = {}
    for name, rule in GATES.items():
        value = observed[name]
        passed = value >= rule["min"] if "min" in rule else value <= rule["max"]
        results[name] = {
            "observed": value,
            "requirement": (f">= {rule['min']}" if "min" in rule else f"<= {rule['max']}"),
            "spec": rule["spec"],
            "passed": bool(passed),
        }

    sources = source_gate(records)
    for source, data in sources.items():
        if data["gate_applies"]:
            results[f"source_useful_precision[{source}]"] = {
                "observed": data["useful_precision"],
                "requirement": f">= {SOURCE_GATE_MIN_PRECISION}",
                "spec": "§42",
                "passed": bool(data["gate_passed"]),
            }

    failed = sorted(name for name, data in results.items() if not data["passed"])
    return {
        "gates": results,
        "failed_gates": failed,
        "signal_count_is_100": len(records) == 100,
        "verdict": "SPEC-009 DONE" if not failed and len(records) == 100 else "SPEC-009 NOT DONE",
    }


def full_report(records: Sequence[dict]) -> dict[str, Any]:
    """Le rapport complet, dans l'ordre des sections de §63."""
    return {
        "headline": headline(records),
        "agreement": agreement(records),
        "safety": safety(records),
        "top20": top20(records),
        "bottom_third": bottom_third(records),
        "calibration": calibration(records),
        "distributions": distributions(records),
        "source_gate": source_gate(records),
        "failure_attribution": failure_attribution(records),
        "gates": evaluate_gates(records),
    }
