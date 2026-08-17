"""SPEC-006R5 §32 — une panne API n'est jamais un verdict modèle.

Le benchmark FR-DCE-1 du 17 août 2026 a compté 10 « échecs de schéma » Kimi qui
étaient en réalité un épuisement de crédits OpenRouter (HTTP 402, ~0,1 s par
appel). La taxonomie du harnais doit distinguer ce que le MODÈLE a produit de ce
que le TRANSPORT ou le FOURNISSEUR n'a pas livré :

    api_credit_failure   compte épuisé (402)
    api_rate_limit       cadence refusée (429)
    transport_failure    timeout, réseau coupé
    provider_failure     5xx, réponse sans aucun choix
    schema_failure       le modèle a répondu, hors contrat

Seule la dernière catégorie parle du modèle. Les quatre autres n'entrent dans
aucune métrique qualité.
"""

from __future__ import annotations

import json

import httpx
import pytest

from signals.documents.classification import CandidateContext, api_failure_kind
from signals.documents.intelligence import RequirementCandidate
from signals.documents.openrouter import OpenRouterClassifier, OpenRouterVerifier
from signals.documents.providers import AnthropicClassifier
from signals.documents.snapshot import CandidateSnapshot

SENTENCE = (
    "Le titulaire doit assurer la maintenance des équipements pendant toute la durée du marché."
)

VALID = {
    "phase": "execution",
    "obligated_actor": "contractor",
    "modality": "mandatory",
    "requirement_type": "maintenance_obligation",
    "context_status": "sufficient",
    "source_excerpt": SENTENCE,
    "confidence": "high",
}


def _context(sentence: str = SENTENCE) -> CandidateContext:
    return CandidateContext(
        candidate=RequirementCandidate(
            requirement_type="other",
            modality="mandatory",
            statement=sentence,
            source_excerpt=sentence,
            source_locator="page 4",
        ),
        current_text=sentence,
        document_name="CCTP.pdf",
        locator="page 4",
    )


def _snapshot() -> CandidateSnapshot:
    return CandidateSnapshot(
        candidate_id=1,
        award_reference="26-TEST",
        document_hash="deadbeef",
        document_name="CCTP.pdf",
        media_type="application/pdf",
        source_locator="page 4",
        heading=None,
        previous_block=None,
        current_block=SENTENCE,
        next_block=None,
        logical_span=SENTENCE,
        source_block_locators=("page 4",),
        excerpt=SENTENCE,
    )


def _openrouter(handler, monkeypatch) -> OpenRouterClassifier:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")
    classifier = OpenRouterClassifier(model="deepseek/deepseek-v4-flash")
    classifier._client = httpx.Client(transport=httpx.MockTransport(handler))
    return classifier


def _reply(content: dict | str) -> dict:
    text = content if isinstance(content, str) else json.dumps(content)
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 60},
    }


class TestSharedTaxonomy:
    """Une seule fonction nomme les pannes HTTP, pour tous les adaptateurs."""

    @pytest.mark.parametrize(
        ("status", "kind"),
        [
            (402, "api_credit_failure"),
            (429, "api_rate_limit"),
            (500, "provider_failure"),
            (529, "provider_failure"),
            (401, "unauthorized"),
            (403, "unauthorized"),
            (404, "client_error"),
        ],
    )
    def test_status_codes_map_to_the_r5_taxonomy(self, status: int, kind: str) -> None:
        assert api_failure_kind(status) == kind


class TestOpenRouterClassifierFailures:
    def test_credit_exhaustion_is_an_api_failure_not_a_schema_failure(self, monkeypatch) -> None:
        """Le bug du 17 août : 10 appels à 402 comptés comme échecs de schéma."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

        classifier = _openrouter(handler, monkeypatch)

        assert classifier.classify(_context()) is None
        assert calls["n"] == 1  # une panne de crédit ne se retente pas
        assert classifier.usage.failure_kinds["api_credit_failure"] == 1
        assert "schema_failure" not in classifier.usage.failure_kinds
        assert classifier.last_failure == "api_credit_failure"

    def test_a_timeout_is_a_transport_failure(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("trop lent", request=request)

        classifier = _openrouter(handler, monkeypatch)
        assert classifier.classify(_context()) is None
        assert classifier.usage.failure_kinds["transport_failure"] == 1
        assert classifier.last_failure == "transport_failure"

    def test_a_network_cut_is_a_transport_failure(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("réseau coupé", request=request)

        classifier = _openrouter(handler, monkeypatch)
        assert classifier.classify(_context()) is None
        assert classifier.usage.failure_kinds["transport_failure"] == 1

    def test_a_model_reply_out_of_schema_is_a_schema_failure(self, monkeypatch) -> None:
        classifier = _openrouter(
            lambda request: httpx.Response(200, json=_reply('{"phase": "execution"}')), monkeypatch
        )
        assert classifier.classify(_context()) is None
        # Deux passages (retentative comprise), deux réponses hors contrat.
        assert classifier.usage.failure_kinds["schema_failure"] == 2
        assert classifier.usage.retries == 1
        assert classifier.last_failure == "schema_failure"

    def test_an_empty_choice_list_is_a_provider_failure(self, monkeypatch) -> None:
        """Aucun contenu produit : le modèle n'a pas « raté le schéma », le
        fournisseur n'a rien livré."""
        classifier = _openrouter(
            lambda request: httpx.Response(200, json={"choices": [], "usage": {}}), monkeypatch
        )
        assert classifier.classify(_context()) is None
        assert classifier.usage.failure_kinds["provider_failure"] == 1
        assert "schema_failure" not in classifier.usage.failure_kinds

    def test_a_success_leaves_no_failure_trace(self, monkeypatch) -> None:
        classifier = _openrouter(
            lambda request: httpx.Response(200, json=_reply(VALID)), monkeypatch
        )
        assert classifier.classify(_context()) is not None
        assert classifier.last_failure is None

    def test_a_recovered_schema_retry_clears_last_failure(self, monkeypatch) -> None:
        replies = iter(['{"phase": "execution"}', json.dumps(VALID)])
        classifier = _openrouter(
            lambda request: httpx.Response(200, json=_reply(next(replies))), monkeypatch
        )
        assert classifier.classify(_context()) is not None
        assert classifier.last_failure is None


class TestOpenRouterVerifierFailures:
    def test_the_verifier_shares_the_same_taxonomy(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")
        verifier = OpenRouterVerifier(model="deepseek/deepseek-v4-flash")
        verifier._client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(402, json={"error": {"message": "no credit"}})
            )
        )
        assert verifier.verify(_snapshot()) is None
        assert verifier.usage.failure_kinds["api_credit_failure"] == 1
        assert verifier.last_failure == "api_credit_failure"


class TestAnthropicClassifierFailures:
    def _classifier(self, handler, monkeypatch) -> AnthropicClassifier:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-local-not-a-real-key")
        classifier = AnthropicClassifier(model="claude-haiku-4-5")
        classifier._client = httpx.Client(transport=httpx.MockTransport(handler))
        return classifier

    @pytest.mark.parametrize(
        ("status", "kind"),
        [
            (402, "api_credit_failure"),
            (429, "api_rate_limit"),
            (500, "provider_failure"),
        ],
    )
    def test_the_anthropic_adapter_uses_the_same_names(
        self, status: int, kind: str, monkeypatch
    ) -> None:
        classifier = self._classifier(
            lambda request: httpx.Response(status, json={"error": {"type": "x"}}), monkeypatch
        )
        assert classifier.classify(_context()) is None
        assert classifier.usage.failure_kinds[kind] == 1
