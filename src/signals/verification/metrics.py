"""Métriques et gates du vérificateur commercial (SPEC-009A §31, §32, §39–§45).

Ce module compte, il ne juge pas. Il confronte ce que le filtre a laissé passer
au gold commercial produit **avant** le premier appel au modèle, et rend un
verdict de gate sans jamais proposer de correction.

Vocabulaire : `useful` = un signal dont le verdict gold est `A` ou `B` (§31).
La précision se mesure sur ce que le feed montre ; le rappel, sur ce que le feed
aurait dû montrer.
"""

from __future__ import annotations

import collections
import statistics
from collections.abc import Sequence
from typing import Any

USEFUL_VERDICTS = ("A", "B")

#: §32 — les gates du DEV, plus sévères que ceux du held-out : on veut savoir si
#: l'approche tient avant de payer un corpus frais.
DEV_GATES = {
    "final_show_useful_precision": {"min": 95.0, "spec": "§32"},
    "critical_false_final_shows": {"max": 0, "spec": "§32"},
    "false_final_show_rate": {"max": 2.0, "spec": "§32"},
    "weak_final_show_rate": {"max": 8.0, "spec": "§32"},
    "useful_recall": {"min": 60.0, "spec": "§32"},
    "final_show_rate": {"min": 30.0, "spec": "§32"},
    "fact_reference_validity": {"min": 100.0, "spec": "§32"},
    "forbidden_wording": {"max": 0, "spec": "§32"},
    "top20_final_show_useful_precision": {"min": 95.0, "spec": "§32"},
}

#: §39 — les gates du held-out final, applicables seulement si le DEV passe.
FINAL_GATES = {
    "final_show_useful_precision": {"min": 90.0, "spec": "§39"},
    "critical_false_final_shows": {"max": 0, "spec": "§39"},
    "false_final_show_rate": {"max": 2.0, "spec": "§39"},
    "weak_final_show_rate": {"max": 10.0, "spec": "§39"},
    "useful_recall": {"min": 60.0, "spec": "§39"},
    "final_show_rate": {"min": 25.0, "spec": "§39"},
    "final_show_count": {"min": 50, "spec": "§39"},
    "fact_reference_validity": {"min": 100.0, "spec": "§39"},
    "forbidden_wording": {"max": 0, "spec": "§39"},
    "top20_final_show_useful_precision": {"min": 95.0, "spec": "§39"},
    "rubric_agreement_within_one": {"min": 90.0, "spec": "§39"},
}

#: §40 — gate conditionnel par source.
SOURCE_GATE_MIN_FINAL_SHOWS = 20
SOURCE_GATE_MIN_PRECISION = 85.0


def _pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def _useful(row: dict) -> bool:
    return row["gold_verdict"] in USEFUL_VERDICTS


def _shown(row: dict) -> bool:
    return row["final_decision"] == "final_show"


def headline(rows: Sequence[dict]) -> dict[str, Any]:
    """Ce que le filtre a laissé passer, et ce que cela valait (§31)."""
    shown = [row for row in rows if _shown(row)]
    gold = collections.Counter(row["gold_verdict"] for row in rows)
    shown_gold = collections.Counter(row["gold_verdict"] for row in shown)
    useful_total = sum(1 for row in rows if _useful(row))

    return {
        "candidates": len(rows),
        "gold_A": gold["A"],
        "gold_B": gold["B"],
        "gold_C": gold["C"],
        "gold_D": gold["D"],
        "final_shows": len(shown),
        "final_show_rate": _pct(len(shown), len(rows)),
        "true_useful_final_shows": shown_gold["A"] + shown_gold["B"],
        "weak_final_shows": shown_gold["C"],
        "false_final_shows": shown_gold["D"],
        "final_show_useful_precision": _pct(shown_gold["A"] + shown_gold["B"], len(shown)),
        "final_show_actionable_rate": _pct(shown_gold["A"], len(shown)),
        "weak_final_show_rate": _pct(shown_gold["C"], len(shown)),
        "false_final_show_rate": _pct(shown_gold["D"], len(shown)),
        "critical_false_final_shows": sum(
            1 for row in shown if row.get("gold_critical_false_signal")
        ),
        "useful_recall": _pct(shown_gold["A"] + shown_gold["B"], useful_total),
        "A_recall": _pct(shown_gold["A"], gold["A"]),
        "B_recall": _pct(shown_gold["B"], gold["B"]),
        "shown_distribution": dict(shown_gold),
    }


def origin_analysis(rows: Sequence[dict]) -> dict[str, Any]:
    """Ce que le filtre nettoie, et ce qu'il récupère (§41)."""
    result: dict[str, Any] = {}
    for origin in ("show", "borderline"):
        group = [row for row in rows if row["origin_decision"] == origin]
        shown = [row for row in group if _shown(row)]
        useful_total = sum(1 for row in group if _useful(row))
        result[origin] = {
            "candidates": len(group),
            "retained" if origin == "show" else "promoted": len(shown),
            "hidden": len(group) - len(shown),
            "useful_precision_after_verifier": _pct(
                sum(1 for row in shown if _useful(row)), len(shown)
            ),
            "useful_precision_before_verifier": _pct(useful_total, len(group)),
            "useful_recall": _pct(sum(1 for row in shown if _useful(row)), useful_total),
            "useful_opportunities_recovered": (
                sum(1 for row in shown if _useful(row)) if origin == "borderline" else None
            ),
        }
    return result


def integrity(rows: Sequence[dict]) -> dict[str, Any]:
    """Les compteurs de conformité de la réponse elle-même (§20–§22, §25)."""
    answered = [row for row in rows if row.get("verification") is not None]
    fact_errors = sum(
        1
        for row in rows
        if any("inexistants" in error for error in row.get("validation_errors") or ())
    )
    wording_errors = sum(
        1
        for row in rows
        if any("certitude" in error for error in row.get("validation_errors") or ())
    )
    return {
        "answered": len(answered),
        "fact_reference_errors": fact_errors,
        "fact_reference_validity": _pct(len(answered) - fact_errors, len(answered)),
        "forbidden_wording": wording_errors,
        "validation_failures": sum(
            1 for row in rows if row.get("failure_kind") == "validation_failure"
        ),
        "schema_failures": sum(1 for row in rows if row.get("failure_kind") == "schema_failure"),
        "api_failures": sum(
            1
            for row in rows
            if row.get("failure_kind")
            in ("api_credit_failure", "api_rate_limit", "transport_failure", "provider_failure")
        ),
        "unsupported_language": sum(
            1 for row in rows if row.get("hide_reason") == "unsupported_language"
        ),
        "hide_reasons": dict(
            collections.Counter(
                row["hide_reason"] for row in rows if row.get("hide_reason")
            ).most_common()
        ),
    }


def top20(rows: Sequence[dict]) -> dict[str, Any]:
    """Les vingt meilleurs signaux finaux, par score moteur (§32, §39)."""
    shown = sorted(
        (row for row in rows if _shown(row)),
        key=lambda row: (-row.get("normalized_score", 0), row["signal_candidate_id"]),
    )[:20]
    return {
        "final_shows": len(shown),
        "useful_precision": _pct(sum(1 for row in shown if _useful(row)), len(shown)),
        "critical_false": sum(1 for row in shown if row.get("gold_critical_false_signal")),
        "distribution": dict(collections.Counter(row["gold_verdict"] for row in shown)),
    }


def failure_analysis(rows: Sequence[dict]) -> dict[str, Any]:
    """Chaque faux final show, nommé et attribué (§42)."""
    false_shows = [row for row in rows if _shown(row) and row["gold_verdict"] in ("C", "D")]
    cases = []
    for row in sorted(
        false_shows, key=lambda r: (r["gold_verdict"], -r.get("normalized_score", 0))
    ):
        verification = row.get("verification") or {}
        cases.append(
            {
                "candidate_id": row["signal_candidate_id"],
                "origin": row["origin_decision"],
                "source": row.get("source"),
                "icp_id": row.get("icp_id"),
                "contract_type": row.get("contract_type"),
                "need_categories": row.get("matched_needs"),
                "gold_verdict": row["gold_verdict"],
                "gold_primary_failure_layer": row.get("gold_primary_failure_layer"),
                "verifier_verdict": verification.get("verdict"),
                "verifier_need_credibility": verification.get("need_credibility"),
                "verifier_icp_fit": verification.get("icp_fit"),
                "verifier_specificity": verification.get("specificity"),
                "verifier_timing": verification.get("timing_status"),
                "verifier_reason": verification.get("commercial_reason"),
                "gold_note": row.get("gold_note"),
            }
        )
    return {
        "false_final_shows": len(false_shows),
        "by_gold_verdict": dict(collections.Counter(r["gold_verdict"] for r in false_shows)),
        "by_gold_failure_layer": dict(
            collections.Counter(
                r.get("gold_primary_failure_layer") or "unattributed" for r in false_shows
            ).most_common()
        ),
        "cases": cases,
    }


def shadow_diagnostics(rows: Sequence[dict]) -> dict[str, Any]:
    """Le compromis précision/rappel rendu visible (§43)."""
    hidden = [row for row in rows if not _shown(row)]
    return {
        "useful_candidates_hidden": sum(1 for row in hidden if _useful(row)),
        "actionable_candidates_hidden": sum(1 for row in hidden if row["gold_verdict"] == "A"),
        "false_candidates_correctly_blocked": sum(
            1 for row in hidden if row["gold_verdict"] == "D"
        ),
        "weak_candidates_correctly_blocked": sum(1 for row in hidden if row["gold_verdict"] == "C"),
        "hidden_total": len(hidden),
        "hidden_distribution": dict(collections.Counter(r["gold_verdict"] for r in hidden)),
    }


def _breakdown(rows: Sequence[dict], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        value = row.get(key)
        for item in value if isinstance(value, list) else [value]:
            groups[str(item)].append(row)
    result = {}
    for name, group in sorted(groups.items()):
        shown = [row for row in group if _shown(row)]
        result[name] = {
            "candidates": len(group),
            "final_shows": len(shown),
            "useful_precision": _pct(sum(1 for row in shown if _useful(row)), len(shown)),
            "useful_recall": _pct(
                sum(1 for row in shown if _useful(row)),
                sum(1 for row in group if _useful(row)),
            ),
        }
    return result


def distributions(rows: Sequence[dict]) -> dict[str, Any]:
    return {
        "source": _breakdown(rows, "source"),
        "icp": _breakdown(rows, "icp_id"),
        "contract_type": _breakdown(rows, "contract_type"),
        "need_category": _breakdown(rows, "matched_needs"),
    }


def cost_and_latency(rows: Sequence[dict], usage: dict[str, Any]) -> dict[str, Any]:
    """Ce que la course a réellement coûté, et ce qu'elle coûterait à l'échelle (§44, §45)."""
    latencies = sorted(row["latency_ms"] for row in rows if row.get("latency_ms"))
    measured_cost = sum(row.get("cost_usd", 0.0) for row in rows)
    shown = sum(1 for row in rows if _shown(row))

    def quantile(fraction: float) -> float:
        if not latencies:
            return 0.0
        return round(latencies[min(len(latencies) - 1, int(fraction * len(latencies)))], 1)

    per_candidate = measured_cost / len(rows) if rows else 0.0
    return {
        "MEASURED": {
            "requests": usage.get("calls", 0),
            "cache_hits": usage.get("cache_hits", 0),
            "schema_retries": usage.get("schema_retries", 0),
            "api_failures": usage.get("failures", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cost_usd": round(measured_cost, 6),
            "candidates": len(rows),
            "final_shows": shown,
            "latency_ms": {
                "p50": quantile(0.50),
                "p95": quantile(0.95),
                "max": round(latencies[-1], 1) if latencies else 0.0,
            },
            "total_wall_time_ms": round(sum(latencies), 1),
        },
        "PROJECTED": {
            "cost_per_100_candidates": round(per_candidate * 100, 4),
            "cost_per_100_final_shows": (round(measured_cost / shown * 100, 4) if shown else None),
            "cost_per_1000_deterministic_candidates": round(per_candidate * 1000, 4),
            "wall_time_100_candidates_s": round(
                statistics.mean(latencies) * 100 / 1000 if latencies else 0.0, 1
            ),
            "wall_time_1000_candidates_s": round(
                statistics.mean(latencies) * 1000 / 1000 if latencies else 0.0, 1
            ),
        },
    }


def source_gate(rows: Sequence[dict]) -> dict[str, Any]:
    """§40 — précision utile par source, quand la source a au moins 20 final shows."""
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        groups[str(row.get("source"))].append(row)
    result = {}
    for source, group in sorted(groups.items()):
        shown = [row for row in group if _shown(row)]
        precision = _pct(sum(1 for row in shown if _useful(row)), len(shown))
        applies = len(shown) >= SOURCE_GATE_MIN_FINAL_SHOWS
        result[source] = {
            "final_shows": len(shown),
            "useful_precision": precision,
            "gate_applies": applies,
            "gate_passed": (precision >= SOURCE_GATE_MIN_PRECISION) if applies else None,
        }
    return result


def evaluate_gates(
    rows: Sequence[dict], *, gates: dict[str, dict], agreement_within_one: float | None = None
) -> dict[str, Any]:
    """Confronte les métriques aux gates demandés et rend un verdict global."""
    head = headline(rows)
    checks = integrity(rows)
    best = top20(rows)

    observed = {
        "final_show_useful_precision": head["final_show_useful_precision"],
        "critical_false_final_shows": head["critical_false_final_shows"],
        "false_final_show_rate": head["false_final_show_rate"],
        "weak_final_show_rate": head["weak_final_show_rate"],
        "useful_recall": head["useful_recall"],
        "final_show_rate": head["final_show_rate"],
        "final_show_count": head["final_shows"],
        "fact_reference_validity": checks["fact_reference_validity"],
        "forbidden_wording": checks["forbidden_wording"],
        "top20_final_show_useful_precision": best["useful_precision"],
        "rubric_agreement_within_one": agreement_within_one,
    }

    results = {}
    for name, rule in gates.items():
        value = observed.get(name)
        if value is None:
            continue
        passed = value >= rule["min"] if "min" in rule else value <= rule["max"]
        results[name] = {
            "observed": value,
            "requirement": f">= {rule['min']}" if "min" in rule else f"<= {rule['max']}",
            "spec": rule["spec"],
            "passed": bool(passed),
        }

    failed = sorted(name for name, data in results.items() if not data["passed"])
    return {"gates": results, "failed_gates": failed, "passed": not failed}


def full_report(
    rows: Sequence[dict], usage: dict[str, Any], *, gates: dict[str, dict]
) -> dict[str, Any]:
    return {
        "headline": headline(rows),
        "origin": origin_analysis(rows),
        "integrity": integrity(rows),
        "top20": top20(rows),
        "shadow_diagnostics": shadow_diagnostics(rows),
        "distributions": distributions(rows),
        "source_gate": source_gate(rows),
        "failure_analysis": failure_analysis(rows),
        "cost_and_latency": cost_and_latency(rows, usage),
        "gates": evaluate_gates(rows, gates=gates),
    }
