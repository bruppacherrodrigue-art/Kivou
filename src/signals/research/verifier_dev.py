"""Le DEV set du vérificateur commercial (SPEC-009A §28–§32) — script de recherche.

Trois étapes, volontairement séparées par des commandes distinctes :

* `gold`      — assemble le gold des 50 borderline depuis les deux perspectives
                indépendantes, exige un arbitrage là où §30 l'impose, et le gèle.
                À faire AVANT le premier appel au modèle.
* `preflight` — vérifie le modèle approuvé, les crédits et le budget (§6, §9).
                Ne dépense rien.
* `run`       — fait passer les 150 candidats par le vérificateur, applique la
                politique, calcule les métriques et les gates du DEV.

Ce module reste **agnostique du fournisseur** (§7) : `preflight` et `run_dev`
reçoivent le modèle et les sondes en paramètres. La composition — la seule ligne
qui sait quel fournisseur est branché — vit dans l'adaptateur, qui porte aussi
la CLI des deux commandes réseau. `gold` tourne entièrement hors ligne.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
from collections.abc import Callable
from typing import Any

from signals.research.signal100 import workdir
from signals.research.signal100_adjudication import (
    AdjudicationError,
    needs_arbitration,
    resolve,
    validate_review,
)
from signals.verification.cache import VerificationCache
from signals.verification.metrics import DEV_GATES, full_report
from signals.verification.model import POLICY_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from signals.verification.protocol import CommercialSignalVerificationModel
from signals.verification.runner import Candidate, verify_all

#: §9 — plafond absolu de dépense pour toute SPEC-009A.
BUDGET_USD = 1.00

DEV_GOLD_NAME = "verifier_dev_gold.json"
DEV_RESULT_NAME = "verifier_dev_result.json"
DEV_REPORT_NAME = "verifier_dev_report.json"


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Gold des borderline (§29) ──────────────────────────────────────────────────


def _merge_reviews(directory: pathlib.Path, pattern: str) -> dict[str, dict]:
    reviews: dict[str, dict] = {}
    files = sorted(directory.glob(pattern))
    if not files:
        raise AdjudicationError(f"aucun lot ne correspond à {pattern} dans {directory}")
    for path in files:
        for row in _load(path):
            if row["signal_id"] in reviews:
                raise AdjudicationError(f"{row['signal_id']} jugé deux fois dans {pattern}")
            reviews[row["signal_id"]] = row
    return reviews


def assemble_gold(reviews_dir: pathlib.Path) -> dict[str, Any]:
    """Le gold des 50 borderline, avec la même doctrine d'arbitrage que SPEC-009."""
    out = workdir()
    shadow = _load(out / "signal100_shadow.json")["borderline"]
    blind_by_id = {item["blind"]["signal_id"]: item for item in shadow}

    reviews_a = _merge_reviews(reviews_dir, "dev_reviewer_a_batch_*.json")
    reviews_b = _merge_reviews(reviews_dir, "dev_reviewer_b_batch_*.json")
    arbitrations: dict[str, dict] = {}
    if list(reviews_dir.glob("dev_arbitration_batch_*.json")):
        arbitrations = _merge_reviews(reviews_dir, "dev_arbitration_batch_*.json")

    records = []
    pending: list[str] = []
    for signal_id, item in blind_by_id.items():
        if signal_id not in reviews_a or signal_id not in reviews_b:
            raise AdjudicationError(f"revue manquante pour {signal_id}")
        review_a = validate_review(reviews_a[signal_id], role="dev_reviewer_a")
        review_b = validate_review(reviews_b[signal_id], role="dev_reviewer_b")
        arbitration = arbitrations.get(signal_id)
        if arbitration is not None:
            arbitration = validate_review(arbitration, role="dev_arbitration")
        if needs_arbitration(review_a, review_b) and arbitration is None:
            pending.append(signal_id)
            continue

        record = {
            "signal_id": signal_id,
            "origin_decision": "borderline",
            "source": item["blind"]["source"],
            "icp_id": item["blind"]["icp"]["icp_id"],
            "contract_type": item["blind"]["contract_understanding"]["contract_type"],
            "matched_needs": [need["category"] for need in item["blind"]["derived_needs"]],
            "normalized_score": item["engine"]["normalized_score"],
            "review_a": review_a,
            "review_b": review_b,
            "arbitration": arbitration,
        }
        record.update(resolve(review_a, review_b, arbitration))
        records.append(record)

    if pending:
        return {"pending_arbitrations": pending, "count": len(pending)}

    payload = {
        "gold": "VERIFIER-DEV-BORDERLINE-GOLD",
        "rubric": "commercial-signal-rubric-v1",
        "size": len(records),
        "composition": dict(collections.Counter(r["final_verdict"] for r in records)),
        "agreement": _agreement(records),
        "records": records,
    }
    (out / DEV_GOLD_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    payload["sha256"] = _sha256(out / DEV_GOLD_NAME)
    return payload


def _agreement(records: list[dict]) -> dict[str, Any]:
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    distances = [
        abs(order[r["review_a"]["verdict"]] - order[r["review_b"]["verdict"]]) for r in records
    ]
    total = len(distances) or 1
    return {
        "signals": len(records),
        "exact_agreement_rate": round(100.0 * distances.count(0) / total, 2),
        "agreement_within_one_grade_rate": round(
            100.0 * sum(1 for d in distances if d <= 1) / total, 2
        ),
        "arbitrations": sum(1 for r in records if r["arbitration"]),
        "distance_histogram": dict(sorted(collections.Counter(distances).items())),
    }


# ─── Assemblage du DEV set (§28) ────────────────────────────────────────────────


def build_dev_candidates() -> tuple[list[Candidate], dict[str, dict]]:
    """Les 150 candidats du DEV : 100 SHOW de Signal-100 + 50 BORDERLINE."""
    out = workdir()
    blind_show = {s["signal_id"]: s for s in _load(out / "signal100_blind.json")["signals"]}
    gold_show = {r["signal_id"]: r for r in _load(out / "signal100_gold.json")["records"]}
    shadow = {
        i["blind"]["signal_id"]: i for i in _load(out / "signal100_shadow.json")["borderline"]
    }
    gold_border = {r["signal_id"]: r for r in _load(out / DEV_GOLD_NAME)["records"]}

    candidates: list[Candidate] = []
    gold: dict[str, dict] = {}

    for signal_id, blind in blind_show.items():
        record = gold_show[signal_id]
        candidates.append(Candidate(blind, "show"))
        gold[signal_id] = {
            "gold_verdict": record["final_verdict"],
            "gold_critical_false_signal": record["critical_false_signal"],
            "gold_primary_failure_layer": record["primary_failure_layer"],
            "gold_note": record["final_note"],
            "source": record["source"],
            "icp_id": record["icp_id"],
            "contract_type": record["contract_type"],
            "matched_needs": record["matched_needs"],
            "normalized_score": record["normalized_score"],
        }

    for signal_id, record in gold_border.items():
        candidates.append(Candidate(shadow[signal_id]["blind"], "borderline"))
        gold[signal_id] = {
            "gold_verdict": record["final_verdict"],
            "gold_critical_false_signal": record["critical_false_signal"],
            "gold_primary_failure_layer": record["primary_failure_layer"],
            "gold_note": record["final_note"],
            "source": record["source"],
            "icp_id": record["icp_id"],
            "contract_type": record["contract_type"],
            "matched_needs": record["matched_needs"],
            "normalized_score": record["normalized_score"],
        }

    return candidates, gold


# ─── Préflight (§6, §9) ─────────────────────────────────────────────────────────


def preflight(
    *,
    candidates: int,
    approved_model: str,
    model_check: Callable[[str], dict[str, Any]],
    credits_check: Callable[[], dict[str, Any]],
    credentials_required_message: str,
) -> dict[str, Any]:
    """Modèle approuvé, crédits, budget — avant de dépenser quoi que ce soit.

    Les sondes ET le libellé de blocage sont injectés : ce module ne sait pas
    quel fournisseur il interroge — pas même le nom de la variable
    d'environnement qui porterait sa clé — et la suite de tests peut tout
    remplacer sans réseau.
    """
    report: dict[str, Any] = {"approved_model": approved_model}
    report["model"] = model_check(approved_model)
    if not report["model"]["available"]:
        report["blocked"] = "SPEC-009A BLOCKED — APPROVED MODEL UNAVAILABLE"
        return report

    # Estimation haute : ~9 000 jetons d'entrée et 4 000 de sortie par candidat.
    price_in = report["model"]["prompt_usd_per_token"]
    price_out = report["model"]["completion_usd_per_token"]
    worst_case = candidates * (9000 * price_in + 4000 * price_out)
    report["estimated_max_cost_usd"] = round(worst_case, 4)
    report["budget_usd"] = BUDGET_USD

    try:
        report["credits"] = credits_check()
    except Exception as exc:  # noqa: BLE001 — la nature de l'échec est le résultat
        report["credits"] = {"reachable": False, "error": type(exc).__name__}
        report["blocked"] = credentials_required_message
        return report

    remaining = report["credits"].get("remaining_usd")
    if remaining is not None and remaining < worst_case:
        report["blocked"] = (
            f"LIVE VERIFIER EVAL BLOCKED — INSUFFICIENT CREDITS "
            f"({remaining:.4f} USD disponibles, {worst_case:.4f} USD nécessaires)"
        )
    if worst_case > BUDGET_USD:
        report["blocked"] = (
            f"STOP — SPEC-009A COST BUDGET EXHAUSTED avant départ "
            f"({worst_case:.4f} USD > {BUDGET_USD:.2f} USD)"
        )
    return report


# ─── Course DEV (§30–§32) ───────────────────────────────────────────────────────


def run_dev(
    *,
    model: CommercialSignalVerificationModel,
    max_workers: int,
    cache_path: pathlib.Path | None,
) -> dict[str, Any]:
    """La course DEV. Le modèle est reçu, jamais construit ici (§7)."""
    out = workdir()
    candidates, gold = build_dev_candidates()
    cache = VerificationCache(cache_path) if cache_path else VerificationCache()

    records, usage = verify_all(
        candidates, model, cache=cache, max_workers=max_workers, budget_usd=BUDGET_USD
    )

    rows = []
    for record in records:
        row = record.as_dict()
        row.update(gold[record.signal_candidate_id])
        rows.append(row)

    (out / DEV_RESULT_NAME).write_text(
        json.dumps({"rows": rows, "usage": usage.as_dict()}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    report = full_report(rows, usage.as_dict(), gates=DEV_GATES)
    report["versions"] = {
        "prompt": PROMPT_VERSION,
        "schema": SCHEMA_VERSION,
        "policy": POLICY_VERSION,
        "model_id": records[0].model_id if records else None,
    }
    report["run_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    (out / DEV_REPORT_NAME).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    """Seule la commande `gold` vit ici : elle n'a besoin d'aucun fournisseur.

    `preflight` et `run` sont exposées par l'adaptateur, qui est le point de
    composition — le seul endroit du projet qui sache quel modèle est branché.
    """
    parser = argparse.ArgumentParser(description="Gold DEV du vérificateur (SPEC-009A §29)")
    parser.add_argument("--reviews", required=True, help="dossier des lots d'adjudication")
    args = parser.parse_args(argv)

    result = assemble_gold(pathlib.Path(args.reviews))
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "records"}, ensure_ascii=False, indent=1
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
