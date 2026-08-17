"""SPEC-006R4 §3/§4/§13 — le transport du vérificateur, et le budget de jetons.

Le run DEV-3 a établi la cause d'un échec de schéma sur trois : `max_tokens=400`
était intégralement consommé par les jetons de raisonnement avant le premier
caractère de JSON. Ces tests interdisent le retour de ce défaut.
"""

from __future__ import annotations

import json

import httpx
import pytest

from signals.documents.consensus import VERIFIER_QUESTION, build_verifier_prompt
from signals.documents.openrouter import (
    MIN_REASONING_TOKENS,
    OpenRouterClassifier,
    OpenRouterVerifier,
    SnapshotClassifierAdapter,
)
from signals.documents.snapshot import CandidateSnapshot

BLOCK = "Izvajalec mora naročniku mesečno predložiti poročilo o opravljenih delih."
EXCERPT = "Izvajalec mora naročniku mesečno predložiti poročilo"


def snap() -> CandidateSnapshot:
    return CandidateSnapshot(
        candidate_id=7,
        award_reference="999999-2026",
        document_hash="c" * 64,
        document_name="pogodba.docx",
        media_type="application/pdf",
        source_locator="page 4",
        heading="13. člen",
        previous_block="Pogodbene obveznosti izvajalca.",
        current_block=BLOCK,
        next_block="Naročnik pregleda poročilo.",
        logical_span=BLOCK,
        source_block_locators=("page 4",),
        excerpt=EXCERPT,
        language="sl",
    )


def transport(capture: list[dict], payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def reply(content: dict) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40, "cost": 0.0001},
    }


CONFIRM = {
    "verdict": "confirm",
    "reason": "execution_contractor",
    "source_excerpt": EXCERPT,
    "confidence": "high",
}


class TestTheTokenBudgetIsNeverFourHundredAgain:
    def test_the_classifier_default_leaves_room_for_reasoning(self) -> None:
        """400 était consommé par le raisonnement : `content` revenait vide."""
        assert OpenRouterClassifier(model="x", api_key="k").max_tokens >= MIN_REASONING_TOKENS

    def test_the_verifier_default_leaves_room_for_reasoning(self) -> None:
        assert OpenRouterVerifier(model="x", api_key="k").max_tokens >= MIN_REASONING_TOKENS

    def test_the_floor_is_documented_and_well_above_four_hundred(self) -> None:
        assert MIN_REASONING_TOKENS >= 2000

    def test_a_budget_below_the_floor_is_refused(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            OpenRouterVerifier(model="x", api_key="k", max_tokens=400)


class TestTheVerifierPrompt:
    def test_it_asks_the_single_question(self) -> None:
        assert VERIFIER_QUESTION in build_verifier_prompt(snap())

    def test_the_document_text_is_fenced_as_untrusted(self) -> None:
        prompt = build_verifier_prompt(snap())
        assert "<<<UNTRUSTED SOURCE TEXT>>>" in prompt
        assert "<<<END UNTRUSTED SOURCE TEXT>>>" in prompt

    def test_the_excerpt_under_test_is_present(self) -> None:
        assert EXCERPT in build_verifier_prompt(snap())

    def test_the_neighbourhood_is_given(self) -> None:
        prompt = build_verifier_prompt(snap())
        assert "13. člen" in prompt
        assert "Naročnik pregleda poročilo." in prompt

    def test_it_forbids_rewriting_the_excerpt(self) -> None:
        """Le vérificateur juge un passage ; il ne rédige pas l'exigence."""
        prompt = build_verifier_prompt(snap())
        assert "TEL QUEL" in prompt
        assert "Ne le reformule pas" in prompt


class TestTheVerifierTransport:
    def test_it_sends_the_strict_schema(self) -> None:
        sent: list[dict] = []
        verifier = OpenRouterVerifier(model="deepseek/x", api_key="k")
        verifier._client = transport(sent, reply(CONFIRM))
        verifier.verify(snap())
        fmt = sent[0]["response_format"]["json_schema"]
        assert fmt["strict"] is True
        assert fmt["schema"]["additionalProperties"] is False

    def test_it_requires_a_capable_provider(self) -> None:
        sent: list[dict] = []
        verifier = OpenRouterVerifier(model="deepseek/x", api_key="k")
        verifier._client = transport(sent, reply(CONFIRM))
        verifier.verify(snap())
        assert sent[0]["provider"]["require_parameters"] is True

    def test_a_valid_answer_is_parsed(self) -> None:
        verifier = OpenRouterVerifier(model="deepseek/x", api_key="k")
        verifier._client = transport([], reply(CONFIRM))
        answer = verifier.verify(snap())
        assert answer is not None
        assert answer.verdict == "confirm"

    def test_an_answer_out_of_schema_is_no_answer(self) -> None:
        verifier = OpenRouterVerifier(model="deepseek/x", api_key="k")
        verifier._client = transport([], reply({"verdict": "maybe"}))
        assert verifier.verify(snap()) is None

    def test_an_http_failure_is_no_answer_and_never_a_rejection(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        verifier = OpenRouterVerifier(model="deepseek/x", api_key="k")
        verifier._client = httpx.Client(transport=httpx.MockTransport(handler))
        assert verifier.verify(snap()) is None
        assert verifier.usage.failures == 1

    def test_the_key_travels_only_in_the_authorization_header(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=reply(CONFIRM))

        verifier = OpenRouterVerifier(model="deepseek/x", api_key="secret-key")
        verifier._client = httpx.Client(transport=httpx.MockTransport(handler))
        verifier.verify(snap())
        assert seen[0].headers["Authorization"] == "Bearer secret-key"
        assert "secret-key" not in seen[0].content.decode()


class TestTheSnapshotClassifierAdapter:
    def test_it_feeds_the_snapshot_neighbourhood_to_the_primary(self) -> None:
        sent: list[dict] = []
        inner = OpenRouterClassifier(model="deepseek/x", api_key="k")
        inner._client = transport(
            sent,
            reply(
                {
                    "phase": "execution",
                    "obligated_actor": "contractor",
                    "modality": "mandatory",
                    "requirement_type": "other",
                    "context_status": "sufficient",
                    "source_excerpt": EXCERPT,
                    "confidence": "high",
                }
            ),
        )
        adapter = SnapshotClassifierAdapter(inner)
        result = adapter.classify_snapshot(snap())
        assert result is not None
        prompt = sent[0]["messages"][0]["content"]
        assert "13. člen" in prompt
        assert "Naročnik pregleda poročilo." in prompt
