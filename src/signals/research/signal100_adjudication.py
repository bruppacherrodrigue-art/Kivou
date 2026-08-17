"""Adjudication commerciale SIGNAL-100 (SPEC-009 §27–§31).

Ce module ne juge pas : il pose le vocabulaire fermé, valide ce que les
adjudicateurs renvoient, et applique des règles de résolution **déclarées avant
toute adjudication**. C'est la condition pour que le gel de §32 ait un sens.

Deux perspectives indépendantes (§29), arbitrage sur divergence (§30), et une
règle de repli explicite : à égalité de distance 1 sans `D`, le verdict retenu
est le plus sévère des deux. Kivou est un produit *precision-first* — en cas de
doute, le banc ne doit pas se flatter lui-même.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

#: Vocabulaires fermés de la rubrique v1. Toute valeur hors liste est une
#: erreur d'adjudication, pas une nuance : elle est refusée bruyamment.
DIMENSIONS: dict[str, tuple[str, ...]] = {
    "factual_integrity": ("pass", "critical_failure"),
    "need": ("credible", "plausible_but_weak", "unsupported", "contradicted"),
    "icp_fit": ("strong_fit", "plausible_fit", "weak_fit", "no_fit"),
    "actionability": ("actionable", "worth_investigating", "too_weak", "misleading"),
    "specificity": ("specific", "acceptable", "generic"),
    "timing": ("clear", "acceptable", "unknown", "wrong"),
    "proof": ("strong", "adequate", "insufficient"),
}

VERDICTS = ("A", "B", "C", "D")
VERDICT_RANK = {verdict: index for index, verdict in enumerate(VERDICTS)}

#: Les couches auxquelles un échec peut être rattaché (§45).
FAILURE_LAYERS = (
    "source data",
    "winner resolution",
    "contract understanding",
    "need graph",
    "ICP configuration",
    "matching",
    "score threshold",
    "timing",
    "proof presentation",
    "rubric uncertainty",
)

REQUIRED_FIELDS = (
    "signal_id",
    *DIMENSIONS,
    "verdict",
    "critical_false_signal",
    "critical_overclaiming",
    "note",
)


class AdjudicationError(ValueError):
    """Une revue malformée. On préfère l'échec bruyant au verdict inventé."""


def validate_review(review: dict[str, Any], *, role: str) -> dict[str, Any]:
    """Valide une revue contre le vocabulaire fermé de la rubrique."""
    missing = [field for field in REQUIRED_FIELDS if field not in review]
    if missing:
        raise AdjudicationError(
            f"{role} : champs manquants {missing} sur {review.get('signal_id')}"
        )
    for dimension, allowed in DIMENSIONS.items():
        if review[dimension] not in allowed:
            raise AdjudicationError(
                f"{role} : {dimension}={review[dimension]!r} hors rubrique "
                f"pour {review['signal_id']} (attendu {allowed})"
            )
    if review["verdict"] not in VERDICTS:
        raise AdjudicationError(f"{role} : verdict {review['verdict']!r} hors rubrique")
    for layer in review.get("secondary_failure_layers") or []:
        if layer not in FAILURE_LAYERS:
            raise AdjudicationError(f"{role} : couche secondaire inconnue {layer!r}")
    primary = review.get("primary_failure_layer")
    if primary is not None and primary not in FAILURE_LAYERS:
        raise AdjudicationError(f"{role} : couche primaire inconnue {primary!r}")
    return review


def rubric_consistency(review: dict[str, Any]) -> list[str]:
    """Les incohérences entre dimensions et verdict, selon §21, §22 et §25.

    Elles ne corrigent rien : elles sont rapportées. Un adjudicateur qui met
    `generic` puis `actionable` a mal lu la rubrique (§22), et c'est le genre de
    dérive qu'un banc doit voir plutôt que lisser.
    """
    problems: list[str] = []
    if review["specificity"] == "generic" and review["actionability"] == "actionable":
        problems.append("§22 : un signal `generic` ne peut pas être `actionable`")
    hard_d = (
        review["factual_integrity"] == "critical_failure"
        or review["need"] in ("unsupported", "contradicted")
        or review["icp_fit"] == "no_fit"
        or review["actionability"] == "misleading"
        or review["timing"] == "wrong"
        or review["critical_overclaiming"]
    )
    if hard_d and review["verdict"] != "D":
        problems.append("§25 : un déclencheur `D` est présent mais le verdict ne l'est pas")
    if review["critical_false_signal"] and review["verdict"] != "D":
        problems.append("§26 : un critical false signal implique toujours `D`")
    if review["verdict"] == "A":
        required = (
            review["factual_integrity"] == "pass"
            and review["need"] == "credible"
            and review["icp_fit"] == "strong_fit"
            and review["actionability"] == "actionable"
            and review["specificity"] != "generic"
            and review["proof"] != "insufficient"
        )
        if not required:
            problems.append("§25 : verdict `A` sans remplir toutes ses conditions minimales")
    return problems


def needs_arbitration(review_a: dict[str, Any], review_b: dict[str, Any]) -> bool:
    """§30 — divergence de plus d'un niveau, ou un `D` d'un côté."""
    distance = abs(VERDICT_RANK[review_a["verdict"]] - VERDICT_RANK[review_b["verdict"]])
    return distance > 1 or "D" in (review_a["verdict"], review_b["verdict"])


def resolve(
    review_a: dict[str, Any],
    review_b: dict[str, Any],
    arbitration: dict[str, Any] | None,
) -> dict[str, Any]:
    """Le verdict final et les dimensions retenues.

    Règle déclarée AVANT adjudication :

    * si un arbitrage a eu lieu, il tranche — il a vu la preuve brute sans les
      verdicts précédents (§30) ;
    * sinon, le plus sévère des deux l'emporte. Un banc *precision-first* ne
      doit jamais résoudre un désaccord en sa propre faveur.
    """
    if arbitration is not None:
        source, final = "arbitration", arbitration
    else:
        source = "most_severe"
        final = max((review_a, review_b), key=lambda r: VERDICT_RANK[r["verdict"]])
    return {
        "final_verdict": final["verdict"],
        "final_dimensions": {dimension: final[dimension] for dimension in DIMENSIONS},
        "final_source": source,
        "final_note": final.get("note"),
        "critical_false_signal": bool(final.get("critical_false_signal")),
        "critical_overclaiming": bool(final.get("critical_overclaiming")),
        "primary_failure_layer": final.get("primary_failure_layer"),
        "secondary_failure_layers": final.get("secondary_failure_layers") or [],
    }


def assemble(
    signals: Sequence[dict[str, Any]],
    reviews_a: dict[str, dict],
    reviews_b: dict[str, dict],
    arbitrations: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    """Assemble le gold : deux revues, l'arbitrage éventuel, le verdict final.

    Chaque enregistrement conserve aussi les faits moteur nécessaires aux
    analyses de §38 à §44 — score, bande, ICP, source, tercile — mais ceux-ci
    n'ont jamais été montrés aux adjudicateurs.
    """
    arbitrations = arbitrations or {}
    records = []
    for snapshot in signals:
        sid = snapshot["signal_id"]
        if sid not in reviews_a or sid not in reviews_b:
            raise AdjudicationError(f"revue manquante pour {sid}")
        review_a = validate_review(reviews_a[sid], role="reviewer_a")
        review_b = validate_review(reviews_b[sid], role="reviewer_b")
        arbitration = arbitrations.get(sid)
        if arbitration is not None:
            arbitration = validate_review(arbitration, role="arbitration")
        if needs_arbitration(review_a, review_b) and arbitration is None:
            raise AdjudicationError(f"arbitrage requis mais absent pour {sid} (§30)")

        record = {
            "signal_id": sid,
            "source": snapshot["source"],
            "icp_id": snapshot["icp"]["icp_id"],
            "contract_type": snapshot["understanding"]["contract_type"]["value"],
            "matched_needs": snapshot["matched_needs"],
            "normalized_score": snapshot["score"]["normalized_score"],
            "band": snapshot["score"]["band"],
            "confidence": snapshot["score"]["confidence"],
            "tercile": snapshot["tercile"],
            "review_a": review_a,
            "review_b": review_b,
            "arbitration": arbitration,
            "rubric_warnings": {
                "reviewer_a": rubric_consistency(review_a),
                "reviewer_b": rubric_consistency(review_b),
            },
        }
        record.update(resolve(review_a, review_b, arbitration))
        records.append(record)
    return records
