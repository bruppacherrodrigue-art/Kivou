"""Fixed-corpus scoring for the economic company-enrichment judge."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from signals.company_research.domain import domain_from_url
from signals.company_research.enrichment import CompanyEnrichmentInput
from signals.personalization.prospect_mail import normalize_director_name

BENCHMARK_FIELDS = (
    "website",
    "email",
    "family",
    "director_display_name",
)
DEFAULT_CORPUS_PATH = Path(__file__).with_name("company_enrichment_benchmark.json")


class _BenchmarkContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class BenchmarkExpected(_BenchmarkContract):
    website: str | None = Field(default=None, max_length=253)
    email: str | None = Field(default=None, max_length=320)
    family: str | None = Field(default=None, max_length=100)
    director_display_name: str | None = Field(default=None, max_length=256)


class BenchmarkCase(_BenchmarkContract):
    identity: CompanyEnrichmentInput
    expected: BenchmarkExpected
    truth_source: str = Field(pattern=r"^(manual_override|cached_sonnet_review)$")


def load_benchmark_cases(
    path: Path = DEFAULT_CORPUS_PATH,
) -> tuple[BenchmarkCase, ...]:
    import json

    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise TypeError("benchmark corpus must be a JSON array")
    cases = tuple(
        BenchmarkCase(
            identity=CompanyEnrichmentInput.model_validate(
                {key: value for key, value in raw.items() if key not in {"expected", "truth_source"}}
            ),
            expected=BenchmarkExpected.model_validate(raw.get("expected")),
            truth_source=raw.get("truth_source"),
        )
        for raw in raw_cases
    )
    if len(cases) != 30 or len({case.identity.siren for case in cases}) != 30:
        raise ValueError("benchmark corpus must contain 30 distinct SIRENs")
    return cases


def field_matches(
    expected: BenchmarkExpected,
    *,
    website: str | None,
    email: str | None,
    family: str | None,
    director_display_name: str | None,
) -> dict[str, bool]:
    parsed_website = domain_from_url(website)[0] if domain_from_url(website) else None
    parsed_expected = (
        domain_from_url(expected.website)[0] if domain_from_url(expected.website) else None
    )
    return {
        "website": parsed_website == parsed_expected,
        "email": (email.casefold() if email else None)
        == (expected.email.casefold() if expected.email else None),
        "family": family == expected.family,
        "director_display_name": normalize_director_name(director_display_name)
        == normalize_director_name(expected.director_display_name),
    }


@dataclass(frozen=True)
class BenchmarkObservation:
    model: str
    siren: str
    field_matches: dict[str, bool]
    invalid_json: bool
    latency_ms: int
    reserved_usd: Decimal
    actual_usd: Decimal
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class BenchmarkReport:
    model: str
    completed: int
    agreement: Decimal
    field_agreement: dict[str, Decimal]
    invalid_json: int
    median_latency_ms: int
    cost_usd: Decimal
    projected_cost_20k_usd: Decimal
    reservation_ratio: Decimal | None
    requires_reservation_adjustment: bool
    mean_input_tokens_last_20: Decimal


def benchmark_report(
    observations: tuple[BenchmarkObservation, ...],
) -> BenchmarkReport:
    if not observations:
        raise ValueError("benchmark observations are required")
    models = {item.model for item in observations}
    if len(models) != 1:
        raise ValueError("one benchmark report must contain exactly one model")
    completed = len(observations)
    field_agreement = {
        field: Decimal(sum(item.field_matches[field] for item in observations))
        / Decimal(completed)
        for field in BENCHMARK_FIELDS
    }
    agreement = sum(field_agreement.values(), start=Decimal("0")) / Decimal(
        len(BENCHMARK_FIELDS)
    )
    actual = sum((item.actual_usd for item in observations), start=Decimal("0"))
    reserved = sum(
        (item.reserved_usd for item in observations), start=Decimal("0")
    )
    ratio = reserved / actual if actual else None
    last_twenty = observations[-20:]
    return BenchmarkReport(
        model=next(iter(models)),
        completed=completed,
        agreement=agreement,
        field_agreement=field_agreement,
        invalid_json=sum(item.invalid_json for item in observations),
        median_latency_ms=round(statistics.median(item.latency_ms for item in observations)),
        cost_usd=actual,
        projected_cost_20k_usd=actual / Decimal(completed) * Decimal("20000"),
        reservation_ratio=ratio,
        requires_reservation_adjustment=ratio is not None and ratio > Decimal("3"),
        mean_input_tokens_last_20=Decimal(
            sum(item.input_tokens for item in last_twenty)
        )
        / Decimal(len(last_twenty)),
    )


def choose_model(
    observations: tuple[BenchmarkObservation, ...],
    *,
    threshold: Decimal,
    model_order: tuple[str, ...],
) -> str | None:
    grouped: dict[str, list[BenchmarkObservation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.model].append(observation)
    for model in model_order:
        items = tuple(grouped.get(model, ()))
        if items and benchmark_report(items).agreement >= threshold:
            return model
    return None


def mask_directors(
    identity: CompanyEnrichmentInput,
) -> tuple[CompanyEnrichmentInput, dict[str, str]]:
    names: dict[str, str] = {}
    directors: list[dict[str, object]] = []
    for index, source in enumerate(identity.directors_raw, 1):
        token = f"DIR_{index}"
        value = dict(source)
        name = str(value.get("name") or "").strip()
        if name:
            names[token] = name
        value["name"] = token
        value.pop("first_name", None)
        directors.append(value)
    return identity.model_copy(update={"directors_raw": tuple(directors)}), names


__all__ = [
    "BENCHMARK_FIELDS",
    "BenchmarkCase",
    "BenchmarkExpected",
    "BenchmarkObservation",
    "BenchmarkReport",
    "benchmark_report",
    "choose_model",
    "field_matches",
    "load_benchmark_cases",
    "mask_directors",
]
