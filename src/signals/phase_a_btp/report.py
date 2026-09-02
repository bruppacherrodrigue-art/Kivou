"""Build and serialize the real, provider-free Phase A BTP local report."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

from signals.phase_a_btp.contracts import (
    AwardSnapshot,
    FreshnessBucket,
    FreshnessDistribution,
    PhaseABtpReport,
)
from signals.phase_a_btp.eligibility import evaluate
from signals.phase_a_btp.reading import build_showcase_signal
from signals.phase_a_btp.selection import select_showcase


def _choice_rank(award: AwardSnapshot, *, as_of: dt.date) -> tuple[object, ...]:
    result = evaluate(award, as_of=as_of)
    materials_profile = "materials_and_components" in award.target_offers
    generic_profile = award.target_offer_summary.casefold().startswith("all operational")
    date_rank = -(award.event_date.toordinal() if award.event_date else 0)
    return (
        0 if result.visible_dashboard else 1,
        -len(result.concrete_information),
        -len(result.operational_elements),
        0 if materials_profile and not generic_profile else 1,
        date_rank,
        award.signal_key,
    )


def build_report(rows: Iterable[AwardSnapshot], *, as_of: dt.date) -> PhaseABtpReport:
    snapshots = tuple(rows)
    btp_rows = tuple(
        row for row in snapshots if row.cpv_main is not None and row.cpv_main.startswith("45")
    )
    grouped: dict[str, list[AwardSnapshot]] = defaultdict(list)
    for row in btp_rows:
        grouped[row.opportunity_key].append(row)
    unique = tuple(
        min(values, key=lambda value: _choice_rank(value, as_of=as_of))
        for _, values in sorted(grouped.items())
    )

    decisions = tuple((row, evaluate(row, as_of=as_of)) for row in unique)
    eligible = tuple(row for row, result in decisions if result.visible_dashboard)
    showcase_candidates = tuple(build_showcase_signal(row, as_of=as_of) for row in eligible)
    showcase = select_showcase(showcase_candidates, limit=10)

    bucket_counts = {bucket: 0 for bucket in FreshnessBucket}
    for _, result in decisions:
        if result.visible_dashboard:
            bucket_counts[result.freshness_bucket] += 1
    return PhaseABtpReport(
        evaluated_on=as_of,
        corpus_total=len(snapshots),
        btp_total=len(unique),
        exploitable_total=len(eligible),
        insufficient_total=len(unique) - len(eligible),
        siret_recovery_candidates=sum(
            result.recoverable_siret and not result.visible_dashboard for _, result in decisions
        ),
        dce_available=sum(bool(row.dce_document_ids) for row in unique),
        outbound_ready_total=sum(result.outbound_ready for _, result in decisions),
        freshness=FreshnessDistribution(
            days_0_90=bucket_counts[FreshnessBucket.DAYS_0_90],
            days_91_180=bucket_counts[FreshnessBucket.DAYS_91_180],
            days_181_365=bucket_counts[FreshnessBucket.DAYS_181_365],
            over_one_year=bucket_counts[FreshnessBucket.OVER_ONE_YEAR],
        ),
        showcase=showcase,
    )


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_ndjson(lines: Iterable[str]) -> tuple[AwardSnapshot, ...]:
    return tuple(
        AwardSnapshot.model_validate_json(line)
        for line in lines
        if line.strip()
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="NDJSON input path or - for stdin")
    parser.add_argument("--output", required=True)
    parser.add_argument("--mirror-output")
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    source = sys.stdin if args.input == "-" else open(args.input, encoding="utf-8")  # noqa: SIM115
    try:
        rows = _read_ndjson(source)
    finally:
        if source is not sys.stdin:
            source.close()
    report = build_report(rows, as_of=dt.date.fromisoformat(args.as_of))
    payload = report.model_dump_json(indent=2)
    _write_atomic(Path(args.output), payload)
    if args.mirror_output:
        _write_atomic(Path(args.mirror_output), payload)
    print(payload)
    return 0
