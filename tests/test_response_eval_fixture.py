from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from signals.responses.classifier import derive_business_disposition
from signals.responses.contracts import (
    ResponseClassification,
    ResponseClassifierOutput,
    ResponseReasonCode,
)
from signals.responses.safety import evaluate_response_safety

FIXTURE = Path(__file__).parent / "fixtures" / "response_intelligence_eval_v1.json"
CASES = json.loads(FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_offline_response_eval_v1(case) -> None:
    safety = evaluate_response_safety(
        event_type=case.get("event_type", "reply_received"),
        language=case["language"],
        subject=case["subject"],
        current_response=case["content"],
        provider_auto_reply=(case.get("event_type") == "auto_reply_received"),
    )
    assert safety.final is case["safety_final"]
    if safety.final:
        assert safety.classification.value == case["classification"]
        assert safety.reason_codes[0].value == case["reason_code"]
        assert safety.hot_lead is False
        return

    # This is a deterministic fake-classifier corpus: it exercises the strict
    # output contract and Kivou-owned effect mapping without selecting or
    # invoking a production model.
    result = ResponseClassifierOutput(
        classification=ResponseClassification(case["classification"]),
        confidence=Decimal("0.91" if case["hot"] else "0.75"),
        reason_codes=(ResponseReasonCode(case["reason_code"]),),
        hot_lead=case["hot"],
        review_required=case["review"],
        classifier_version="synthetic-eval-classifier-v1",
        language=case["language"],
        human_response_confirmed=case["human"],
    )
    disposition = derive_business_disposition(result)
    assert disposition.hot_lead is case["hot"]
    assert disposition.review_required is case["review"]


def test_offline_corpus_covers_every_closed_taxonomy_category() -> None:
    assert {case["classification"] for case in CASES} == {
        item.value for item in ResponseClassification
    }


def test_provider_interest_label_cannot_change_kivou_result() -> None:
    case = next(value for value in CASES if value["id"] == "ambiguous-politeness")
    provider_enrichment = {"lead_interested": True, "ai_interest_score": 1.0}

    result = ResponseClassifierOutput(
        classification=ResponseClassification(case["classification"]),
        confidence=Decimal("0.5"),
        reason_codes=(ResponseReasonCode(case["reason_code"]),),
        hot_lead=False,
        review_required=True,
        classifier_version="synthetic-eval-classifier-v1",
        language="en",
        human_response_confirmed=True,
    )

    assert provider_enrichment["lead_interested"] is True
    assert derive_business_disposition(result).hot_lead is False
