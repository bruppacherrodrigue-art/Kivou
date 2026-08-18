"""SPEC-009D — l'exécution de l'audit sur les artefacts gelés de SPEC-009C.

Hors ligne de bout en bout (§2, §38, §43). Aucune acquisition, aucun LLM,
aucune base : le corpus de 2001 award-lots, le banc de 100 signaux et le gold
sont relus sur disque, et le pipeline gelé est rejoué sur le corpus pour
retrouver les **110 SHOW naturels** — dont le banc ne conserve que 100.

Ce rejeu n'est pas une acquisition et ne règle rien : mêmes moteurs, même ICP,
même `as_of`. Le runner vérifie d'ailleurs qu'il reproduit exactement les
identités du banc et, pour les 100 signaux, exactement les mêmes dates
canoniques que le snapshot gelé. Si cette égalité tombait, l'audit s'arrêterait :
mesurer la fraîcheur sur un pipeline qui a bougé ne voudrait rien dire.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys
from typing import Any

from signals.matching import MATCH_POLICY_VERSION, SCORE_POLICY_VERSION
from signals.matching.reference import CONSTRUCTION_INPUTS_ICP
from signals.research.signal100 import load_rows, signal_id, workdir
from signals.research.signal100_pipeline import run_pipeline
from signals.research.spec009d import (
    AWARD_AGE_BUCKET_ORDER,
    COMPANY_ACTIVITY_FIELDS,
    JUST_WON_THRESHOLDS,
    MATCHING_FAILURE_STUDY,
    MISSING_INFORMATION,
    PUBLICATION_DELAY_BUCKET_ORDER,
    PURCHASE_CHANNEL_RELEVANT_FACTS,
    WINNER_IDENTIFIER_SCHEMES,
    RecencyRecord,
    admit_feature,
    channel_verdict,
    contingency,
    contracts_already_started,
    contracts_ending_soon,
    control_sample,
    decision_matrix,
    distribution,
    failure_reason_counts,
    field_coverage,
    just_won,
    matchability_candidate,
    observability_rate,
    parse_date,
    publication_delay_bucket,
    quality_breakdown,
    recency_verdict,
    sample_label,
    stale_but_recently_published,
    winner_activity_field_count,
)

CORPUS = "spec009c_corpus.json"
BENCH = "spec009c_bench.json"
GOLD = "spec009c_gold.json"
OUT = "spec009d_audit.json"

#: Codes CPV du banc qui désignent un **type de bâtiment** ou une catégorie de
#: travaux, et non un métier. Ils ne peuvent pas informer un canal d'achat.
GENERIC_CPV = frozenset({"45200000", "45210000", "45211000", "45211200", "45213000", "45220000"})


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value_band(amount: str | float | None) -> str:
    if amount is None:
        return "unpublished"
    value = float(amount)
    if value < 250_000:
        return "under_250k"
    if value < 1_000_000:
        return "250k_1m"
    if value < 5_000_000:
        return "1m_5m"
    return "over_5m"


def natural_shows(rows: list[dict], *, as_of: dt.date) -> dict[str, RecencyRecord]:
    """Les 110 SHOW naturels, rejoués sur le corpus gelé avec l'ICP du wedge."""
    records: dict[str, RecencyRecord] = {}
    for run in run_pipeline(rows, as_of=as_of, icps=(CONSTRUCTION_INPUTS_ICP,)):
        for match in run.matches:
            if match.decision != "show":
                continue
            timing = run.understanding.timing
            sid = signal_id(run.lot.key, match.icp_id, MATCH_POLICY_VERSION, SCORE_POLICY_VERSION)
            records[sid] = RecencyRecord(
                signal_id=sid,
                source=run.lot.source,
                as_of=as_of,
                award_date=parse_date(timing.award_date),
                publication_date=parse_date(timing.published_at),
                contract_start_date=parse_date(timing.contract_start_date),
                contract_end_date=parse_date(timing.contract_end_date),
            )
    return records


def assert_precondition(
    records: dict[str, RecencyRecord], signals: list[dict], expected_shows: int
) -> None:
    """§2, §39 — le rejeu doit rendre exactement le banc gelé, sinon on s'arrête."""
    if len(records) != expected_shows:
        raise SystemExit(f"rejeu : {len(records)} SHOW au lieu de {expected_shows}")
    for snapshot in signals:
        sid = snapshot["signal_id"]
        if sid not in records:
            raise SystemExit(f"signal du banc absent du rejeu : {sid}")
        frozen = snapshot["understanding"]["timing"]
        replayed = records[sid]
        pairs = (
            ("award_date", replayed.award_date),
            ("contract_start_date", replayed.contract_start_date),
            ("contract_end_date", replayed.contract_end_date),
            ("published_at", replayed.publication_date),
        )
        for field, value in pairs:
            if parse_date(frozen.get(field)) != value:
                raise SystemExit(f"{sid} : {field} du rejeu diffère du snapshot gelé")


def part_a(
    records: dict[str, RecencyRecord],
    verdicts: dict[str, str],
) -> dict[str, Any]:
    """§4–§16 — fraîcheur observée, et ce qu'elle achète commercialement."""
    shows = list(records.values())
    adjudicated = [records[sid] for sid in sorted(verdicts)]

    def coverage(population: list[RecencyRecord], attr: str) -> dict[str, Any]:
        known = sum(1 for r in population if getattr(r, attr) is not None)
        return {
            "n": len(population),
            "known": known,
            "unknown": len(population) - known,
            "known_pct": round(100 * known / len(population), 1) if population else 0.0,
        }

    by_source = {
        source: coverage([r for r in shows if r.source == source], "award_date")
        for source in sorted({r.source for r in shows})
    }

    age_buckets = collections.Counter(r.award_age_bucket for r in shows)
    delay_buckets = collections.Counter(
        publication_delay_bucket(r.publication_delay_days) for r in shows
    )

    quality_by_bucket: dict[str, Any] = {}
    for bucket in AWARD_AGE_BUCKET_ORDER:
        members = [r for r in adjudicated if r.award_age_bucket == bucket]
        if members:
            quality_by_bucket[bucket] = quality_breakdown([verdicts[r.signal_id] for r in members])

    just_won_results: dict[str, Any] = {}
    for threshold in JUST_WON_THRESHOLDS:
        selected = just_won(adjudicated, max_age_days=threshold)
        just_won_results[str(threshold)] = quality_breakdown(
            [verdicts[r.signal_id] for r in selected]
        ) | {
            "share_of_shows": round(
                100 * len(just_won(shows, max_age_days=threshold)) / len(shows), 1
            )
        }

    fresh = just_won(adjudicated, max_age_days=30)
    older = [r for r in adjudicated if r.award_age_days is not None and r.award_age_days > 30]
    fresh_precision = quality_breakdown([verdicts[r.signal_id] for r in fresh])
    older_precision = quality_breakdown([verdicts[r.signal_id] for r in older])
    gradient = round(
        fresh_precision.get("useful_precision", 0.0) - older_precision.get("useful_precision", 0.0),
        1,
    )

    def brief(r: RecencyRecord) -> dict[str, Any]:
        return {
            "signal_id": r.signal_id,
            "source": r.source,
            "award_date": r.award_date.isoformat() if r.award_date else None,
            "publication_date": (r.publication_date.isoformat() if r.publication_date else None),
            "publication_delay_days": r.publication_delay_days,
            "award_age_days": r.award_age_days,
            "contract_start_date": (
                r.contract_start_date.isoformat() if r.contract_start_date else None
            ),
            "contract_end_date": r.contract_end_date.isoformat() if r.contract_end_date else None,
            "days_to_contract_start": r.days_to_contract_start,
            "days_until_contract_end": r.days_until_contract_end,
            "gold": verdicts.get(r.signal_id, "not adjudicated"),
        }

    just_won_30_share = just_won_results["30"]["share_of_shows"]
    award_coverage = coverage(shows, "award_date")

    return {
        "population": {"natural_shows": len(shows), "adjudicated": len(adjudicated)},
        "award_date_coverage": award_coverage | {"by_source": by_source},
        "publication_date_coverage": coverage(shows, "publication_date"),
        "contract_start_coverage": coverage(shows, "contract_start_date"),
        "contract_end_coverage": coverage(shows, "contract_end_date"),
        "award_age_buckets": {
            bucket: age_buckets[bucket] for bucket in AWARD_AGE_BUCKET_ORDER if age_buckets[bucket]
        },
        "award_age_distribution": distribution(
            [r.award_age_days for r in shows if r.award_age_days is not None]
        ),
        "publication_age_distribution": distribution(
            [r.publication_age_days for r in shows if r.publication_age_days is not None]
        ),
        "publication_delay_distribution": distribution(
            [r.publication_delay_days for r in shows if r.publication_delay_days is not None]
        ),
        "publication_delay_buckets": {
            bucket: delay_buckets[bucket]
            for bucket in PUBLICATION_DELAY_BUCKET_ORDER
            if delay_buckets[bucket]
        },
        "just_won": just_won_results,
        "quality_by_award_age_bucket": quality_by_bucket,
        "quality_gradient_30d": {
            "fresh_le_30d": fresh_precision,
            "older_gt_30d": older_precision,
            "gradient_points": gradient,
        },
        "stale_but_recently_published": [brief(r) for r in stale_but_recently_published(shows)],
        "contracts_already_started": [brief(r) for r in contracts_already_started(shows)],
        "contracts_ending_soon": [brief(r) for r in contracts_ending_soon(shows)],
        "verdict": recency_verdict(
            award_date_coverage=award_coverage["known_pct"],
            just_won_30_share=just_won_30_share,
            quality_gradient=gradient,
        ),
    }


def channel_features(snapshot: dict) -> dict[str, str]:
    """Les variables candidates de §21–§22, toutes tirées de faits admissibles.

    Chaque nom passe par `admit_feature` : une variable dérivée du nom du
    gagnant ou d'un verdict ne peut pas entrer ici sans lever.
    """
    contract = snapshot["contract"]
    member = snapshot["winner"]["parties"][0]["members"][0]
    place = contract.get("place_of_performance") or {}
    cpv = contract.get("cpv_main")
    derived = {
        "source": snapshot["source"],
        "trade_domain": snapshot["trade_domain"],
        "trade_domain_source": snapshot["trade_domain_source"],
        "bkp_codes": "present" if snapshot["bkp_codes"] else "absent",
        "cpv_main": "generic" if cpv in GENERIC_CPV else "trade_specific",
        "contract_type": snapshot["understanding"]["contract_type"]["value"],
        "amount": value_band((contract.get("value") or {}).get("amount")),
        "currency": (contract.get("value") or {}).get("currency") or "unknown",
        "winner_country": member.get("country") or "unknown",
        "winner_website": "known" if member.get("website") else "absent",
        "place_of_performance": "locality known" if place.get("locality") else "country only",
        "lot_title": "present" if contract.get("lot_title") else "absent",
        "award_date": "known" if snapshot["understanding"]["timing"]["award_date"] else "unknown",
        "need_categories": "|".join(
            sorted({need["category"] for need in snapshot["needs"]["needs"]})
        ),
    }
    for name in derived:
        admit_feature(name)
    return derived


def part_b(
    signals: dict[str, dict],
    verdicts: dict[str, str],
    records: dict[str, RecencyRecord],
) -> dict[str, Any]:
    """§17–§34 — ce que les données permettent réellement de savoir du canal d'achat."""
    useful_ids = {sid for sid, verdict in verdicts.items() if verdict in {"A", "B"}}

    presence = {
        "bkp_codes": lambda s: bool(s["bkp_codes"]),
        "lot_title": lambda s: bool(s["contract"].get("lot_title")),
        "contract_reference": lambda s: bool(s["contract"].get("contract_reference")),
        "cpv_additional": lambda s: bool(s["contract"].get("cpv_additional")),
        "characteristics": lambda s: bool(s["understanding"].get("characteristics")),
        "sector": lambda s: s["understanding"]["sector"]["value"] != "unknown",
        "award_date": lambda s: bool(s["understanding"]["timing"]["award_date"]),
        "contract_start_date": lambda s: bool(s["understanding"]["timing"]["contract_start_date"]),
        "contract_end_date": lambda s: bool(s["understanding"]["timing"]["contract_end_date"]),
        "winner_website": lambda s: bool(s["winner"]["parties"][0]["members"][0].get("website")),
        "winner_identifiers": lambda s: bool(
            s["winner"]["parties"][0]["members"][0].get("identifiers")
        ),
        "winner_address": lambda s: bool(s["winner"]["parties"][0]["members"][0].get("address")),
        "place_of_performance": lambda s: bool(
            (s["contract"].get("place_of_performance") or {}).get("locality")
        ),
        "amount": lambda s: bool((s["contract"].get("value") or {}).get("amount")),
    }
    coverage = {}
    for name, probe in presence.items():
        admit_feature(name)
        coverage[name] = field_coverage(signals, probe, useful_ids=useful_ids)

    features = {sid: channel_features(snapshot) for sid, snapshot in signals.items()}
    discrimination: dict[str, Any] = {}
    for name in next(iter(features.values())):
        table = contingency({sid: f[name] for sid, f in features.items()}, useful_ids=useful_ids)
        spread = [row["useful_precision"] for row in table.values() if row["n"] >= 10]
        discrimination[name] = {
            "path": admit_feature(name),
            "values": {
                value: row | {"sample": sample_label(row["n"])}
                for value, row in sorted(table.items(), key=lambda kv: -kv[1]["n"])
            },
            "spread_points": round(max(spread) - min(spread), 1) if len(spread) >= 2 else None,
        }

    failures = [case.signal_id for case in MATCHING_FAILURE_STUDY]
    failure_strata = [(signals[sid]["source"], signals[sid]["trade_domain"]) for sid in failures]
    candidates = {
        sid: (signals[sid]["source"], signals[sid]["trade_domain"])
        for sid in signals
        if sid in useful_ids
    }
    control = control_sample(candidates, failure_strata, size=len(failures))

    def profile(ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        return {
            "n": len(ids),
            "bkp_present": sum(1 for sid in ids if signals[sid]["bkp_codes"]),
            "cpv_trade_specific": sum(
                1 for sid in ids if signals[sid]["contract"]["cpv_main"] not in GENERIC_CPV
            ),
            "winner_website_known": sum(
                1
                for sid in ids
                if signals[sid]["winner"]["parties"][0]["members"][0].get("website")
            ),
            "trade_domain": dict(collections.Counter(signals[sid]["trade_domain"] for sid in ids)),
            "source": dict(collections.Counter(signals[sid]["source"] for sid in ids)),
        }

    observability = observability_rate([case.observability for case in MATCHING_FAILURE_STUDY])

    matchability = []
    for name, row in discrimination.items():
        spread = row["spread_points"]
        matchability.append(
            {
                "fact": name,
                "path": row["path"],
                "available_before_matching": True,
                "describes_purchase_channel": name in PURCHASE_CHANNEL_RELEVANT_FACTS,
                "coverage": coverage.get(name, {}).get("coverage"),
                "useful_precision_spread_points": spread,
                "candidate_for_future_use": matchability_candidate(name, spread_points=spread),
            }
        )

    activity_fields = winner_activity_field_count()
    verdict = channel_verdict(
        winner_activity_fields=activity_fields,
        fully_observable_rate=observability["yes_rate"],
    )

    return {
        "population": {
            "adjudicated": len(signals),
            "useful": len(useful_ids),
            "non_useful": len(signals) - len(useful_ids),
        },
        "fact_coverage": coverage,
        "company_information": {
            "fields": [dataclass_dict(field) for field in COMPANY_ACTIVITY_FIELDS],
            "activity_describing_fields": activity_fields,
            "identifier_schemes": {
                name: dataclass_dict(scheme) for name, scheme in WINNER_IDENTIFIER_SCHEMES.items()
            },
        },
        "discrimination": discrimination,
        "failure_study": {
            "n": len(MATCHING_FAILURE_STUDY),
            "by_channel_reason": failure_reason_counts(),
            "cases": [
                dataclass_dict(case)
                | {
                    "gold": verdicts[case.signal_id],
                    "award_age_days": records[case.signal_id].award_age_days,
                }
                for case in MATCHING_FAILURE_STUDY
            ],
        },
        "observability": observability,
        "control_sample": {
            "signal_ids": list(control),
            "profile": profile(control),
            "failure_profile": profile(failures),
        },
        "matchability_matrix": matchability,
        "missing_information": [dataclass_dict(gap) for gap in MISSING_INFORMATION],
        "verdict": verdict,
    }


def dataclass_dict(obj: Any) -> dict[str, Any]:
    import dataclasses as _dc

    return _dc.asdict(obj)


def run(*, out_name: str = OUT) -> dict[str, Any]:
    root = workdir()
    corpus_path, bench_path, gold_path = root / CORPUS, root / BENCH, root / GOLD
    bench = json.loads(bench_path.read_text(encoding="utf-8"))
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    as_of = dt.date.fromisoformat(bench["as_of"])

    rows = load_rows(corpus_path)
    records = natural_shows(rows, as_of=as_of)
    assert_precondition(records, bench["signals"], bench["natural_shows"])

    signals = {snapshot["signal_id"]: snapshot for snapshot in bench["signals"]}
    verdicts = {record["signal_id"]: record["final_verdict"] for record in gold["records"]}

    a = part_a(records, verdicts)
    b = part_b(signals, verdicts, records)
    decision = decision_matrix(a["verdict"], b["verdict"])

    payload = {
        "artefact": "spec009d-audit",
        "as_of": as_of.isoformat(),
        "note": "AUDIT ONLY — aucun moteur, aucun label commercial, aucun seuil n'est modifié",
        "inputs": {
            "corpus": {"file": CORPUS, "sha256": sha256(corpus_path), "award_lots": len(rows)},
            "bench": {"file": BENCH, "sha256": sha256(bench_path), "signals": len(signals)},
            "gold": {"file": GOLD, "sha256": sha256(gold_path), "records": len(verdicts)},
            "icp": CONSTRUCTION_INPUTS_ICP.icp_id,
            "engine_versions": bench["engine_versions"],
            "rubric": gold["rubric"],
        },
        "part_a_recency": a,
        "part_b_purchase_channel": b,
        "decision": decision,
    }
    target = root / out_name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"audit écrit dans {target}", file=sys.stderr)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit SPEC-009D (hors ligne)")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args(argv)
    payload = run(out_name=args.out)
    print(json.dumps(payload["decision"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
