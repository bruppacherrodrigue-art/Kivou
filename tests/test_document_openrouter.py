"""L'adaptateur OpenRouter — même interface, même schéma, aucune règle nouvelle.

Ces tests ne touchent jamais le réseau : ils vérifient le contrat de l'appel
(schéma transmis, paramètres exigés, clé jamais fabriquée) et le traitement des
réponses réelles possibles, valides comme dégradées.
"""

from __future__ import annotations

import json
import pathlib
import re

import httpx
import pytest

from signals.documents.classification import (
    CandidateContext,
    build_classification_prompt,
    decide,
)
from signals.documents.intelligence import RequirementCandidate
from signals.documents.openrouter import (
    COMPLETIONS_URL,
    CredentialMissing,
    OpenRouterClassifier,
    response_schema,
)

SENTENCE = "Izvajalec mora zagotoviti vzdrževanje opreme ves čas trajanja pogodbe."

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
            source_locator="page 12",
        ),
        current_text=sentence,
        heading="4. Obveznosti izvajalca",
        previous_text="Pogodbene obveznosti se začnejo z uvedbo v delo.",
        next_text="Vzdrževanje obsega redne in izredne posege.",
        document_name="RD.docx",
        locator="page 12",
    )


def _classifier(handler, monkeypatch, model: str = "deepseek/deepseek-v4-flash"):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")
    classifier = OpenRouterClassifier(model=model)
    classifier._client = httpx.Client(transport=httpx.MockTransport(handler))
    return classifier


def _reply(content: dict | str, *, cost: float | None = 0.00012) -> dict:
    usage = {"prompt_tokens": 900, "completion_tokens": 60}
    if cost is not None:
        usage["cost"] = cost
    text = content if isinstance(content, str) else json.dumps(content)
    return {"choices": [{"message": {"content": text}}], "usage": usage}


class TestCredential:
    def test_a_missing_key_is_an_explicit_state(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(CredentialMissing):
            OpenRouterClassifier(model="deepseek/deepseek-v4-flash")

    def test_no_key_is_hard_coded_in_the_adapter(self) -> None:
        source = pathlib.Path("src/signals/documents/openrouter.py").read_text()
        assert not re.search(r"sk-[A-Za-z0-9_\-]{10,}", source)

    def test_the_key_travels_only_in_the_authorization_header(self, monkeypatch) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=_reply(VALID))

        classifier = _classifier(handler, monkeypatch)
        classifier.classify(_context())

        assert seen[0].headers["authorization"].startswith("Bearer ")
        assert b"test-local-not-a-real-key" not in seen[0].content


class TestRequestContract:
    def test_the_schema_of_the_domain_is_sent_to_the_provider(self, monkeypatch) -> None:
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, json=_reply(VALID))

        classifier = _classifier(handler, monkeypatch)
        classifier.classify(_context())

        body = sent[0]
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["provider"]["require_parameters"] is True

    def test_the_schema_names_the_seven_mandatory_keys(self) -> None:
        schema = response_schema()
        assert set(schema["required"]) == {  # type: ignore[arg-type]
            "phase",
            "obligated_actor",
            "modality",
            "requirement_type",
            "context_status",
            "source_excerpt",
            "confidence",
        }
        assert schema["additionalProperties"] is False

    def test_the_schema_carries_the_enumerations_inline(self) -> None:
        """`strict: true` n'accepte pas de renvoi vers `$defs`."""
        schema = response_schema()
        assert "$defs" not in schema
        assert "execution" in schema["properties"]["phase"]["enum"]  # type: ignore[index]
        assert "contract_formation" in schema["properties"]["phase"]["enum"]  # type: ignore[index]

    def test_the_call_goes_to_the_documented_endpoint(self, monkeypatch) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=_reply(VALID))

        classifier = _classifier(handler, monkeypatch)
        classifier.classify(_context())
        assert str(seen[0].url) == COMPLETIONS_URL

    def test_the_prompt_is_the_shared_one(self, monkeypatch) -> None:
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, json=_reply(VALID))

        classifier = _classifier(handler, monkeypatch)
        context = _context()
        classifier.classify(context)

        assert sent[0]["messages"][0]["content"] == build_classification_prompt(context)
        assert "<<<UNTRUSTED SOURCE TEXT>>>" in sent[0]["messages"][0]["content"]


class TestResponseHandling:
    def test_a_valid_reply_is_read_and_counted(self, monkeypatch) -> None:
        classifier = _classifier(
            lambda request: httpx.Response(200, json=_reply(VALID)), monkeypatch
        )
        classification = classifier.classify(_context())

        assert classification is not None
        assert classification.phase == "execution"
        assert classifier.usage.input_tokens == 900
        assert classifier.reported_cost_usd == pytest.approx(0.00012)

    def test_the_excerpt_is_still_validated_deterministically(self, monkeypatch) -> None:
        """Le fournisseur promet le schéma ; il ne promet pas la vérité."""
        invented = {**VALID, "source_excerpt": "Izvajalec mora zaposliti 40 inženirjev."}
        classifier = _classifier(
            lambda request: httpx.Response(200, json=_reply(invented)), monkeypatch
        )
        classification = classifier.classify(_context())

        assert classification is not None
        decision = decide(classification, source_text=SENTENCE)
        assert not decision.accepted
        assert decision.reason == "excerpt_not_found"

    def test_a_reply_out_of_schema_is_retried_once_then_abandoned(self, monkeypatch) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=_reply('{"phase": "execution"}'))

        classifier = _classifier(handler, monkeypatch)

        assert classifier.classify(_context()) is None
        assert calls["n"] == 2
        assert classifier.usage.retries == 1
        assert classifier.usage.retry_successes == 0

    def test_a_retry_that_succeeds_is_counted(self, monkeypatch) -> None:
        replies = iter(['{"phase": "execution"}', json.dumps(VALID)])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(next(replies)))

        classifier = _classifier(handler, monkeypatch)

        assert classifier.classify(_context()) is not None
        assert classifier.usage.retry_successes == 1

    @pytest.mark.parametrize(
        ("status", "kind"),
        [
            (402, "api_credit_failure"),
            (429, "api_rate_limit"),
            (500, "provider_failure"),
            (401, "unauthorized"),
            (404, "client_error"),
        ],
    )
    def test_http_failures_are_named_and_never_retried(
        self, status: int, kind: str, monkeypatch
    ) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(status, json={"error": {"message": "x"}})

        classifier = _classifier(handler, monkeypatch)

        assert classifier.classify(_context()) is None
        assert calls["n"] == 1
        assert classifier.usage.failure_kinds[kind] == 1

    def test_an_empty_choice_list_is_a_failure_not_a_verdict(self, monkeypatch) -> None:
        classifier = _classifier(
            lambda request: httpx.Response(200, json={"choices": [], "usage": {}}), monkeypatch
        )
        assert classifier.classify(_context()) is None
        # R5 §32 : aucun contenu livré = panne fournisseur, pas échec du modèle.
        assert classifier.usage.failure_kinds["provider_failure"] >= 1

    def test_a_missing_cost_field_does_not_invent_one(self, monkeypatch) -> None:
        classifier = _classifier(
            lambda request: httpx.Response(200, json=_reply(VALID, cost=None)), monkeypatch
        )
        classifier.classify(_context())
        assert classifier.reported_cost_usd == 0.0


class TestInterchangeability:
    def test_it_satisfies_the_same_protocol_as_the_other_adapter(self, monkeypatch) -> None:
        from signals.documents.classification import RequirementClassifier

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")
        classifier: RequirementClassifier = OpenRouterClassifier(model="qwen/qwen3.6-flash")

        assert classifier.name and classifier.version
        assert hasattr(classifier, "usage")
        assert callable(classifier.classify)

    def test_the_pipeline_accepts_it_without_any_change(self, monkeypatch) -> None:
        import datetime as dt

        from signals.documents import TenderDocument, content_hash
        from signals.documents.intelligence import analyze_document

        text = (
            "4. Obveznosti izvajalca\n"
            "Izvajalec mora zagotoviti vzdrževanje opreme ves čas trajanja pogodbe.\n"
        ).encode()

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            sentence = body["messages"][0]["content"].split("[PHRASE À CLASSER] ")[1].split("\n")[0]
            return httpx.Response(200, json=_reply({**VALID, "source_excerpt": sentence}))

        classifier = _classifier(handler, monkeypatch)
        document = TenderDocument(
            source_system="ted",
            name="RD.txt",
            access_status="available",
            content_hash=content_hash(text),
            kind="technical_specification",
            retrieved_at=dt.datetime(2026, 8, 16, tzinfo=dt.UTC),
        )
        analysis = analyze_document(document, text, classifier=classifier)

        assert len(analysis.requirements) == 1
        assert analysis.requirements[0].evidence[0].excerpt
