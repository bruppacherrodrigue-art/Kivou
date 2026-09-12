from __future__ import annotations

import json
from decimal import Decimal

from signals.company_research.benchmark import (
    BenchmarkExpected,
    BenchmarkObservation,
    benchmark_report,
    choose_model,
    field_matches,
    load_benchmark_cases,
    mask_directors,
)
from signals.company_research.benchmark_run import main
from signals.company_research.enrichment import CompanyEnrichmentInput
from signals.company_research.providers import BENCHMARK_MODELS


def _observation(
    model: str,
    *,
    matches: int,
    reserved: str = "0.001",
    actual: str = "0.0005",
) -> BenchmarkObservation:
    return BenchmarkObservation(
        model=model,
        siren="123456789",
        field_matches={
            "website": matches >= 1,
            "email": matches >= 2,
            "family": matches >= 3,
            "director_display_name": matches >= 4,
        },
        invalid_json=False,
        latency_ms=100,
        reserved_usd=Decimal(reserved),
        actual_usd=Decimal(actual),
        input_tokens=900,
        output_tokens=80,
    )


def test_report_scores_each_field_latency_cost_projection_and_reservation_ratio() -> None:
    observations = tuple(
        _observation("mistralai/mistral-small", matches=4)
        for _ in range(30)
    )

    report = benchmark_report(observations)

    assert report.completed == 30
    assert report.agreement == Decimal("1")
    assert report.field_agreement == {
        "website": Decimal("1"),
        "email": Decimal("1"),
        "family": Decimal("1"),
        "director_display_name": Decimal("1"),
    }
    assert report.invalid_json == 0
    assert report.median_latency_ms == 100
    assert report.cost_usd == Decimal("0.0150")
    assert report.projected_cost_20k_usd == Decimal("10.0000")
    assert report.reservation_ratio == Decimal("2")
    assert report.requires_reservation_adjustment is False


def test_reservation_ratio_over_three_requires_recalibration() -> None:
    report = benchmark_report(
        (_observation("mistralai/mistral-small", matches=4, reserved="0.003", actual="0.0004"),)
    )

    assert report.reservation_ratio == Decimal("7.5")
    assert report.requires_reservation_adjustment is True


def test_first_model_at_95_percent_wins_with_mistral_priority() -> None:
    observations = (
        *(_observation("mistralai/mistral-small", matches=4) for _ in range(29)),
        _observation("mistralai/mistral-small", matches=2),
        *(_observation("google/gemini-flash-lite", matches=4) for _ in range(30)),
        *(_observation("deepseek/deepseek-chat", matches=4) for _ in range(30)),
    )

    assert choose_model(
        observations, threshold=Decimal("0.95"), model_order=BENCHMARK_MODELS
    ) == (
        "mistralai/mistral-small"
    )


def test_director_names_are_replaced_by_stable_tokens_for_deepseek() -> None:
    identity = CompanyEnrichmentInput(
        siren="950009944",
        legal_name="ENTREPRISE ALAIN LE NY",
        directors_raw=(
            {"name": "ADIL EL MANSOURI", "first_name": "ADIL", "title": "Président"},
            {"name": "SAS ORIAL", "title": "Autre", "entity_type": "personne morale"},
        ),
    )

    masked, names = mask_directors(identity)

    serialized = masked.model_dump_json()
    assert "ADIL EL MANSOURI" not in serialized
    assert "SAS ORIAL" not in serialized
    assert "ADIL" not in serialized
    assert "DIR_1" in serialized and "DIR_2" in serialized
    assert names == {"DIR_1": "ADIL EL MANSOURI", "DIR_2": "SAS ORIAL"}


def test_fixed_corpus_contains_thirty_cases_and_manual_corrections() -> None:
    cases = load_benchmark_cases()

    assert len(cases) == 30
    by_siren = {case.identity.siren: case for case in cases}
    assert by_siren["481153435"].expected.website == "alyabat.fr"
    assert by_siren["481153435"].expected.email == "alya.batiment@hotmail.fr"
    assert by_siren["572621712"].expected.website is None
    assert by_siren["393665179"].expected.family is None
    assert by_siren["512411604"].expected.website == "mhd05.fr"
    assert by_siren["950009944"].expected.director_display_name == "Adil El Mansouri"
    assert sum(case.truth_source == "manual_override" for case in cases) == 6


def test_field_matching_normalizes_domains_emails_and_display_names() -> None:
    expected = BenchmarkExpected(
        website="alyabat.fr",
        email="alya.batiment@hotmail.fr",
        family="subcontracted_structural_work",
        director_display_name="Adil El Mansouri",
    )

    assert field_matches(
        expected,
        website="https://www.alyabat.fr/",
        email="ALYA.BATIMENT@HOTMAIL.FR",
        family="subcontracted_structural_work",
        director_display_name="ADIL EL MANSOURI",
    ) == {
        "website": True,
        "email": True,
        "family": True,
        "director_display_name": True,
    }


def test_benchmark_command_is_dry_by_default(capsys) -> None:
    assert main(["--batch-id", "benchmark-test"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["planned_openrouter_calls"] == 90
    assert payload["execute_required"] is True
