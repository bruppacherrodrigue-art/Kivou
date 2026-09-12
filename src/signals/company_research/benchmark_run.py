"""Execute the fixed 30-company benchmark only after an explicit network opt-in."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, replace
from decimal import Decimal

import httpx
import sqlalchemy as sa

from signals.company_research.benchmark import (
    BENCHMARK_MODELS,
    BenchmarkObservation,
    benchmark_report,
    choose_model,
    field_matches,
    load_benchmark_cases,
    mask_directors,
)
from signals.company_research.enrichment import (
    CompanyEnrichmentDecision,
    CompanyWebCollector,
    InvalidCompanyEnrichmentDecision,
)
from signals.company_research.providers import (
    OpenRouterCompanyEnrichmentProvider,
    build_company_enrichment_messages,
)
from signals.model_runtime.budget import DailyModelBudgetExhausted, ModelBudgetStore
from signals.model_runtime.config import routes_from_environment
from signals.model_runtime.openrouter import OpenRouterGateway, estimate_input_tokens
from signals.persistence.database import create_database_engine
from signals.persistence.schema import supplier_directory

MAX_BENCHMARK_INPUT_TOKENS = 4_000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m signals.company_research.benchmark_run"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="autorise les collectes web et les 90 appels OpenRouter budgétés",
    )
    parser.add_argument("--batch-id")
    return parser


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _unmask_director(
    decision: CompanyEnrichmentDecision, names: dict[str, str]
) -> CompanyEnrichmentDecision:
    displayed = decision.director_display_name
    if displayed in names:
        return decision.model_copy(update={"director_display_name": names[displayed]})
    return decision


def _call_for(
    budgets: ModelBudgetStore, *, batch_id: str, model: str, siren: str
):
    matches = [
        call
        for call in budgets.calls()
        if call.batch_id == batch_id and call.model == model and call.siren == siren
    ]
    if not matches:
        raise RuntimeError("benchmark model call was not journaled")
    return matches[-1]


def execute_benchmark(*, batch_id: str) -> dict[str, object]:
    serper_key = os.environ.get("KIVOU_SERPER_API_KEY", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not serper_key or not openrouter_key:
        raise ValueError("KIVOU_SERPER_API_KEY and OPENROUTER_API_KEY are required")

    cases = load_benchmark_cases()
    routes = routes_from_environment(batch_id=batch_id)
    base_route = routes.route("enrichment_judge")
    engine = create_database_engine()
    with engine.connect() as connection:
        historical_tokens = tuple(
            connection.scalars(
                sa.select(supplier_directory.c.enrichment_input_tokens)
                .where(supplier_directory.c.enrichment_input_tokens.isnot(None))
                .order_by(supplier_directory.c.enrichment_observed_at.desc())
                .limit(20)
            )
        )
    historical_mean = (
        Decimal(sum(historical_tokens)) / Decimal(len(historical_tokens))
        if historical_tokens
        else None
    )
    budgets = ModelBudgetStore(engine)
    client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=True
    )
    gateway = OpenRouterGateway(api_key=openrouter_key, budgets=budgets, client=client)
    collector = CompanyWebCollector(serper_api_key=serper_key, client=client)
    observations: list[BenchmarkObservation] = []
    estimates: list[int] = []
    try:
        evidence_by_siren = {}
        for index, case in enumerate(cases, 1):
            print(
                f"evidence {index}/30 {case.identity.siren}", file=sys.stderr, flush=True
            )
            evidence_by_siren[case.identity.siren] = collector.collect(case.identity)

        for model in BENCHMARK_MODELS:
            route = replace(base_route, model=model)
            provider = OpenRouterCompanyEnrichmentProvider(
                gateway=gateway,
                route=route,
                batch_id=batch_id,
            )
            for index, case in enumerate(cases, 1):
                identity = case.identity
                names: dict[str, str] = {}
                if model == "deepseek/deepseek-chat":
                    identity, names = mask_directors(identity)
                evidence = evidence_by_siren[case.identity.siren]
                estimated_tokens = estimate_input_tokens(
                    build_company_enrichment_messages(identity, evidence)
                )
                if estimated_tokens >= MAX_BENCHMARK_INPUT_TOKENS:
                    raise RuntimeError(
                        f"REDUCED_INPUT_LIMIT_EXCEEDED: {case.identity.siren} "
                        f"estimated={estimated_tokens}"
                    )
                estimates.append(estimated_tokens)
                print(
                    f"model {model} {index}/30 {case.identity.siren}",
                    file=sys.stderr,
                    flush=True,
                )
                started = time.perf_counter()
                invalid_json = False
                decision: CompanyEnrichmentDecision | None = None
                try:
                    result = provider.enrich(identity, evidence)
                    decision = _unmask_director(result.decision, names)
                except InvalidCompanyEnrichmentDecision:
                    invalid_json = True
                latency_ms = round((time.perf_counter() - started) * 1_000)
                call = _call_for(
                    budgets,
                    batch_id=batch_id,
                    model=model,
                    siren=case.identity.siren,
                )
                if call.status != "succeeded" or call.actual_usd is None:
                    raise RuntimeError(
                        f"BENCHMARK_PROVIDER_FAILURE: {model} {case.identity.siren} "
                        f"{call.error_code or call.status}"
                    )
                if (call.input_tokens or 0) >= MAX_BENCHMARK_INPUT_TOKENS:
                    raise RuntimeError(
                        f"REDUCED_INPUT_LIMIT_EXCEEDED: {case.identity.siren} "
                        f"actual={call.input_tokens}"
                    )
                matches = (
                    field_matches(
                        case.expected,
                        website=decision.website,
                        email=decision.email,
                        family=decision.family,
                        director_display_name=decision.director_display_name,
                    )
                    if decision is not None
                    else {field: False for field in case.expected.model_fields}
                )
                observations.append(
                    BenchmarkObservation(
                        model=model,
                        siren=case.identity.siren,
                        field_matches=matches,
                        invalid_json=invalid_json,
                        latency_ms=latency_ms,
                        reserved_usd=call.reserved_usd,
                        actual_usd=call.actual_usd,
                        input_tokens=call.input_tokens or 0,
                        output_tokens=call.output_tokens or 0,
                    )
                )
    finally:
        close_renderer = getattr(collector._renderer, "close", None)
        if callable(close_renderer):
            close_renderer()
        client.close()
        engine.dispose()

    reports = [
        benchmark_report(tuple(item for item in observations if item.model == model))
        for model in BENCHMARK_MODELS
    ]
    selected = choose_model(tuple(observations), threshold=Decimal("0.95"))
    return {
        "status": "completed",
        "batch_id": batch_id,
        "timezone": routes.timezone,
        "models": [_jsonable(asdict(report)) for report in reports],
        "selected_model": selected,
        "fallback": "anthropic/claude-sonnet-4.6" if selected is None else None,
        "reservation_adjustment_required": any(
            report.requires_reservation_adjustment for report in reports
        ),
        "mean_input_tokens_before_last_20": _jsonable(historical_mean),
        "max_preflight_input_tokens": max(estimates),
        "observed_at": dt.datetime.now(dt.UTC).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    batch_id = arguments.batch_id or f"enrichment-benchmark-{uuid.uuid4().hex[:12]}"
    if not arguments.execute:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "batch_id": batch_id,
                    "companies": len(load_benchmark_cases()),
                    "models": BENCHMARK_MODELS,
                    "planned_openrouter_calls": 90,
                    "execute_required": True,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    try:
        report = execute_benchmark(batch_id=batch_id)
    except DailyModelBudgetExhausted as error:
        print(
            json.dumps(
                {
                    "status": "stopped_budget",
                    "batch_id": batch_id,
                    "usage": error.usage,
                    "error": error.code,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    except (RuntimeError, ValueError) as error:
        print(f"status=BENCHMARK_FAILED error={error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["MAX_BENCHMARK_INPUT_TOKENS", "execute_benchmark", "main"]
