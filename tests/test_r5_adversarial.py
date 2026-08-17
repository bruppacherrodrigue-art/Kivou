"""SPEC-006R5 §13-§19 — le contradicteur et la politique finale sans review.

Le pipeline R5 n'a que deux issues : `auto_accepted` ou `ignored`. Pas de file
de review humaine dans le MVP (§20) — un doute, un blocage, une panne ou une
évidence invalide produisent la même chose : aucune exigence certaine.

Le vérificateur est un CONTRADICTEUR (§16) : il ne reçoit pas la décision du
primaire (§15), et sa mission est de chercher une raison de NE PAS présenter la
phrase comme une obligation d'exécution du titulaire.
"""

from __future__ import annotations

import json

import httpx
import pytest

from signals.documents.adversarial import (
    ADVERSARIAL_INSTRUCTIONS,
    AdversarialResponse,
    adversarial_response_schema,
    build_adversarial_prompt,
    final_decision,
    parse_adversarial,
)
from signals.documents.classification import SemanticClassification
from signals.documents.openrouter import OpenRouterAdversarialVerifier
from signals.documents.snapshot import CandidateSnapshot, validate_excerpt

SENTENCE = (
    "Le titulaire du marché devra tenir compte de l’évolution de la "
    "législation et informer la personne publique en cas de modification."
)
PAGE_4_PIECE = "Le titulaire du marché devra tenir compte de l’évolution de la"
PAGE_5_PIECE = "législation et informer la personne publique en cas de modification."


def _snapshot(**overrides) -> CandidateSnapshot:
    data = {
        "candidate_id": 62,
        "award_reference": "26-134567",
        "document_hash": "cafe",
        "document_name": "CCTP - fourniture de végétaux.pdf",
        "media_type": "application/pdf",
        "source_locator": "page 4",
        "heading": "ARTICLE 8 – NORMES",
        "previous_block": "Les fournitures respectent les normes en vigueur.",
        "current_block": f"Texte de page… {PAGE_4_PIECE}",
        "next_block": f"{PAGE_5_PIECE} Les indications portées sur les étiquettes.",
        "logical_span": f"Texte de page… {SENTENCE} Les indications portées sur les étiquettes.",
        "source_block_locators": ("page 4", "page 5"),
        "excerpt": SENTENCE,
        "evidence_pieces": (("page 4", PAGE_4_PIECE), ("page 5", PAGE_5_PIECE)),
    }
    data.update(overrides)
    return CandidateSnapshot(**data)


def _classification(**overrides) -> SemanticClassification:
    data = {
        "phase": "execution",
        "obligated_actor": "contractor",
        "modality": "mandatory",
        "requirement_type": "other",
        "context_status": "sufficient",
        "source_excerpt": SENTENCE,
        "confidence": "high",
    }
    data.update(overrides)
    return SemanticClassification(**data)


def _confirm(**overrides) -> AdversarialResponse:
    data = {
        "verdict": "confirm",
        "blocker": "none",
        "supporting_excerpt": SENTENCE,
        "confidence": "high",
    }
    data.update(overrides)
    return AdversarialResponse(**data)


# ─── §13 — validateur d'évidence déterministe ───────────────────────────────────


class TestEvidenceValidator:
    def test_a_single_block_excerpt_passes_with_its_locator(self) -> None:
        check = validate_excerpt(PAGE_4_PIECE, _snapshot())
        assert check.ok
        assert check.pieces == (("page 4", PAGE_4_PIECE),)

    def test_a_page_crossing_excerpt_passes_through_its_raw_pieces(self) -> None:
        check = validate_excerpt(SENTENCE, _snapshot())
        assert check.ok
        assert [locator for locator, _ in check.pieces] == ["page 4", "page 5"]

    def test_an_invented_excerpt_is_a_raw_excerpt_failure(self) -> None:
        check = validate_excerpt("Le titulaire recrutera quarante ingénieurs.", _snapshot())
        assert not check.ok
        assert check.failure == "raw_excerpt_failure"

    def test_a_span_match_without_stored_pieces_is_not_evidence(self) -> None:
        """L'extrait n'existe que dans la vue recollée et le candidat ne porte
        aucun morceau brut : une citation sans preuve brute est refusée."""
        snapshot = _snapshot(evidence_pieces=())
        check = validate_excerpt(SENTENCE, snapshot)
        assert not check.ok
        assert check.failure == "raw_excerpt_failure"


# ─── §17 — schéma fermé du contradicteur ────────────────────────────────────────


class TestAdversarialContract:
    def test_the_schema_requires_all_four_keys(self) -> None:
        schema = adversarial_response_schema()
        assert schema["additionalProperties"] is False
        assert sorted(schema["required"]) == [
            "blocker",
            "confidence",
            "supporting_excerpt",
            "verdict",
        ]

    def test_the_verdicts_and_blockers_are_closed_enumerations(self) -> None:
        schema = adversarial_response_schema()
        assert set(schema["properties"]["verdict"]["enum"]) == {"confirm", "block", "uncertain"}
        assert set(schema["properties"]["blocker"]["enum"]) == {
            "procurement",
            "qualification",
            "contract_formation",
            "buyer_obligation",
            "third_party_obligation",
            "informational",
            "fragment",
            "insufficient_context",
            "none",
        }

    def test_an_out_of_schema_reply_is_no_reply(self) -> None:
        assert parse_adversarial('{"verdict": "confirm"}') is None
        assert parse_adversarial("je confirme") is None

    def test_a_valid_reply_is_parsed(self) -> None:
        payload = json.dumps(
            {
                "verdict": "block",
                "blocker": "buyer_obligation",
                "supporting_excerpt": SENTENCE,
                "confidence": "medium",
            }
        )
        answer = parse_adversarial(payload)
        assert answer is not None
        assert answer.verdict == "block"


# ─── §15-§16 — le prompt du contradicteur ───────────────────────────────────────


class TestAdversarialPrompt:
    def test_the_mission_is_to_refute_not_to_confirm(self) -> None:
        lowered = ADVERSARIAL_INSTRUCTIONS.casefold()
        assert "ne doit pas" in lowered

    def test_the_prompt_carries_the_snapshot_but_never_a_primary_decision(self) -> None:
        prompt = build_adversarial_prompt(_snapshot())
        assert SENTENCE in prompt
        assert "ARTICLE 8" in prompt
        assert "page 4" in prompt  # localisation
        assert "<<<UNTRUSTED SOURCE TEXT>>>" in prompt
        # Le §15 interdit l'ancrage : rien de la classification primaire.
        assert "obligated_actor" not in prompt
        assert "execution\n" not in prompt.split("<<<")[0].casefold()

    def test_doubt_is_told_to_stay_doubt(self) -> None:
        assert "uncertain" in ADVERSARIAL_INSTRUCTIONS


# ─── §19-§20 — la politique finale, sans review ─────────────────────────────────


class TestFinalPolicy:
    def test_everything_aligned_is_auto_accepted(self) -> None:
        decision = final_decision(_classification(), _confirm(), snapshot=_snapshot())
        assert decision.outcome == "auto_accepted"
        assert decision.confidence == "high"

    def test_high_confidence_requires_both_models(self) -> None:
        decision = final_decision(
            _classification(confidence="medium"), _confirm(), snapshot=_snapshot()
        )
        assert decision.outcome == "auto_accepted"
        assert decision.confidence == "medium"

    def test_a_primary_rejection_is_ignored_with_its_reason(self) -> None:
        decision = final_decision(_classification(phase="procurement"), None, snapshot=_snapshot())
        assert decision.outcome == "ignored"
        assert decision.reason == "phase_procurement"

    def test_a_primary_failure_is_ignored_as_technical(self) -> None:
        decision = final_decision(None, None, snapshot=_snapshot())
        assert decision.outcome == "ignored"
        assert decision.reason == "primary_failure"

    def test_an_invented_primary_excerpt_is_ignored_before_the_verifier(self) -> None:
        classification = _classification(
            source_excerpt="Le titulaire recrutera quarante ingénieurs."
        )
        decision = final_decision(classification, None, snapshot=_snapshot())
        assert decision.outcome == "ignored"
        assert decision.reason == "raw_excerpt_failure"

    def test_a_missing_verifier_answer_is_ignored_not_accepted(self) -> None:
        decision = final_decision(_classification(), None, snapshot=_snapshot())
        assert decision.outcome == "ignored"
        assert decision.reason == "verifier_failure"

    def test_a_block_is_ignored_with_the_blocker_as_reason(self) -> None:
        answer = _confirm(verdict="block", blocker="buyer_obligation")
        decision = final_decision(_classification(), answer, snapshot=_snapshot())
        assert decision.outcome == "ignored"
        assert decision.reason == "buyer_obligation"

    def test_uncertain_never_becomes_a_fact(self) -> None:
        answer = _confirm(verdict="uncertain", blocker="insufficient_context")
        decision = final_decision(_classification(), answer, snapshot=_snapshot())
        assert decision.outcome == "ignored"

    def test_a_confirm_with_a_blocker_is_incoherent_and_ignored(self) -> None:
        answer = _confirm(blocker="fragment")
        decision = final_decision(_classification(), answer, snapshot=_snapshot())
        assert decision.outcome == "ignored"
        assert decision.reason == "verifier_incoherent"

    def test_a_verifier_excerpt_absent_from_the_source_is_ignored(self) -> None:
        answer = _confirm(supporting_excerpt="Une phrase que le document ne contient pas.")
        decision = final_decision(_classification(), answer, snapshot=_snapshot())
        assert decision.outcome == "ignored"
        assert decision.reason == "verifier_evidence_failure"

    def test_the_accepted_requirement_carries_its_raw_pieces(self) -> None:
        decision = final_decision(_classification(), _confirm(), snapshot=_snapshot())
        assert [locator for locator, _ in decision.evidence] == ["page 4", "page 5"]


# ─── Transport OpenRouter du contradicteur ──────────────────────────────────────


class TestAdversarialTransport:
    def _verifier(self, handler, monkeypatch) -> OpenRouterAdversarialVerifier:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")
        verifier = OpenRouterAdversarialVerifier(model="deepseek/deepseek-v4-flash")
        verifier._client = httpx.Client(transport=httpx.MockTransport(handler))
        return verifier

    def test_a_valid_reply_is_parsed_and_costed(self, monkeypatch) -> None:
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "verdict": "confirm",
                                        "blocker": "none",
                                        "supporting_excerpt": SENTENCE,
                                        "confidence": "high",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 800, "completion_tokens": 90, "cost": 0.0001},
                },
            )

        verifier = self._verifier(handler, monkeypatch)
        answer = verifier.verify(_snapshot())

        assert answer is not None and answer.verdict == "confirm"
        assert verifier.reported_cost_usd == pytest.approx(0.0001)
        schema = sent[0]["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert sent[0]["provider"] == {"require_parameters": True}
        assert sent[0]["messages"][0]["content"] == build_adversarial_prompt(_snapshot())

    def test_a_credit_failure_is_named_not_blamed_on_the_model(self, monkeypatch) -> None:
        verifier = self._verifier(
            lambda request: httpx.Response(402, json={"error": {"message": "no credit"}}),
            monkeypatch,
        )
        assert verifier.verify(_snapshot()) is None
        assert verifier.usage.failure_kinds["api_credit_failure"] == 1
        assert verifier.last_failure == "api_credit_failure"
