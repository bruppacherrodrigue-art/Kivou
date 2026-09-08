# SPEC-009 Precision-First Document Requirements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and honestly validate a fail-closed document-requirement cascade whose auto-accepted precision is strictly above 95% and whose 95% Wilson lower bound is at least 95% on a new blind French DCE corpus.

**Architecture:** Keep the SPEC-006 extractor, snapshots, evidence validator, and DeepSeek primary unchanged. Add a deterministic eligibility guard, a sentence-only verifier, a contextual legal verifier, and a versioned acceptance policy that sends every ambiguity or technical failure to review. Select and freeze the verifier on DEV, use FR-DCE-FINAL only as a known regression, then make activation depend on a separately frozen held-out corpus.

**Tech Stack:** Python 3.12, Pydantic 2, dataclasses, `httpx`, OpenRouter structured outputs, `pytest`, Ruff, SHA-256 manifests, existing `CandidateSnapshot` and `SemanticClassification` contracts.

---

## Scope and file map

The implementation is one sequential subsystem: each task feeds the next and
no task activates the MVP by itself.

**New production modules**

- `src/signals/documents/eligibility.py` — deterministic, auditable abstention risks.
- `src/signals/documents/precision_verification.py` — the two closed semantic contracts and their prompts.
- `src/signals/documents/precision_policy.py` — fail-closed decision and system confidence.
- `src/signals/documents/precision_openrouter.py` — structured-output transport for both verifier views.
- `src/signals/documents/precision_pipeline.py` — ordered orchestration and decision traces.
- `src/signals/documents/precision_manifest.py` — selected configuration plus target-specific frozen run manifests.
- `src/signals/documents/precision_evaluation.py` — regression and activation metrics, Wilson bound, grouped diagnostics.
- `src/signals/documents/activation_corpus.py` — corpus/gold integrity and triple disjointness.
- `src/signals/research/spec009_model_selection.py` — reproducible DEV bake-off.
- `src/signals/research/spec009_run.py` — resumable regression/held-out runner.

**New tests and fixtures**

- `tests/test_spec009_eligibility.py`
- `tests/test_spec009_verification.py`
- `tests/test_spec009_policy.py`
- `tests/test_spec009_openrouter.py`
- `tests/test_spec009_pipeline.py`
- `tests/test_spec009_manifest.py`
- `tests/test_spec009_evaluation.py`
- `tests/test_spec009_activation_corpus.py`
- `tests/test_spec009_model_selection.py`
- `tests/test_spec009_run.py`
- `tests/test_spec009_final_regression.py`
- `tests/fixtures/documents/spec009_model_candidates.json`

**Existing files modified**

- `src/signals/documents/__init__.py` — export only the stable SPEC-009 domain API.
- `src/signals/research/fr_corpus_run.py` — add dynamic exclusion of every known consultation.
- `README.md` — describe SPEC-009 as experimental; keep automatic requirements disabled.

The existing large `adversarial.py`, `openrouter.py`, and `heldout3_build.py`
remain unchanged except where imported. SPEC-009 lives in focused modules so its
policy cannot silently change the historical R5 reference implementation.

### Task 1: Deterministic eligibility guard

**Files:**
- Create: `src/signals/documents/eligibility.py`
- Create: `tests/test_spec009_eligibility.py`

- [ ] **Step 1: Write failing tests for direct actors and structural abstention**

```python
# tests/test_spec009_eligibility.py
from dataclasses import replace

from signals.documents.eligibility import eligibility_guard
from signals.documents.snapshot import CandidateSnapshot


def snap(sentence: str, *, name: str = "CCAP.pdf", heading: str | None = "Exécution"):
    return CandidateSnapshot(
        candidate_id=1,
        award_reference="26-000001",
        document_hash="a" * 64,
        document_name=name,
        media_type="application/pdf",
        source_locator="page 4",
        heading=heading,
        previous_block="Le marché porte sur la maintenance.",
        current_block=sentence,
        next_block=None,
        logical_span=sentence,
        source_block_locators=("page 4",),
        excerpt=sentence,
        language="fr",
    )


def codes(sentence: str) -> set[str]:
    return {finding.code for finding in eligibility_guard(snap(sentence)).findings}


def test_an_explicit_contractor_subject_is_eligible() -> None:
    result = eligibility_guard(snap("Le titulaire doit assurer la maintenance."))
    assert result.eligible
    assert result.findings == ()


def test_a_leading_pronoun_is_not_self_contained() -> None:
    assert "external_pronoun" in codes("Il devra adapter ses approvisionnements.")


def test_a_demonstrative_depends_on_an_external_list() -> None:
    assert "external_demonstrative" in codes(
        "Ces trois éléments devront constituer un ensemble cohérent."
    )


def test_an_impersonal_clause_has_no_explicit_actor() -> None:
    assert "impersonal_actor" in codes("Il n'est procédé à aucune autre révision.")


def test_a_beneficiary_is_not_the_obligated_actor() -> None:
    assert "contractor_beneficiary" in codes(
        "Le titulaire ne pourra pas se voir notifier plus de quatre bons de commande."
    )


def test_an_incomplete_list_item_is_reviewed() -> None:
    assert "fragment" in codes("Une attention devra être portée afin d’être la plus écologique possible ;")


def test_the_existing_phase_guard_remains_authoritative() -> None:
    result = eligibility_guard(
        replace(snap("Le titulaire doit signer."), document_name="Acte_d_engagement.pdf")
    )
    assert "phase_guard_engagement_document" in {f.code for f in result.findings}


def test_lexical_trap_words_do_not_block_an_explicit_clause() -> None:
    result = eligibility_guard(
        snap("Le prestataire doit exécuter son engagement conformément aux normes.")
    )
    assert result.eligible
```

- [ ] **Step 2: Run the focused test and confirm the missing-module failure**

Run: `uv run pytest tests/test_spec009_eligibility.py -q`

Expected: collection fails with `ModuleNotFoundError: signals.documents.eligibility`.

- [ ] **Step 3: Implement the typed guard with generic, precision-first rules**

```python
# src/signals/documents/eligibility.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from signals.documents.adversarial import phase_guard
from signals.documents.snapshot import CandidateSnapshot

ELIGIBILITY_GUARD_VERSION = "spec009-eligibility-v1"

RiskCode = Literal[
    "external_pronoun",
    "external_demonstrative",
    "external_anaphora",
    "fragment",
    "impersonal_actor",
    "actor_not_explicit",
    "contractor_beneficiary",
    "phase_guard_engagement_document",
    "phase_guard_candidacy_document",
    "phase_guard_consultation_rules",
    "phase_guard_award_criteria_heading",
    "phase_guard_signature_heading",
    "phase_guard_form_identification_heading",
    "phase_guard_candidacy_heading",
]


@dataclass(frozen=True)
class EligibilityFinding:
    code: RiskCode
    matched_text: str


@dataclass(frozen=True)
class EligibilityResult:
    findings: tuple[EligibilityFinding, ...]
    version: str = ELIGIBILITY_GUARD_VERSION

    @property
    def eligible(self) -> bool:
        return not self.findings


_PRONOUN = re.compile(r"^\s*(?:il|elle|ils|elles)\b", re.IGNORECASE)
_DEMONSTRATIVE = re.compile(r"^\s*(?:ce|cet|cette|ces|ceux|celles)\b", re.IGNORECASE)
_ANAPHORA = re.compile(
    r"^\s*(?:à cette date|a cette date|dans ce cas|dans cette hypothèse|à ce titre)\b",
    re.IGNORECASE,
)
_IMPERSONAL = re.compile(
    r"\bil\s+(?:n['’]\s*)?(?:est|sera|doit être|devra être)\s+procédé\b"
    r"|^\s*une\s+attention\s+(?:particulière\s+)?devra\s+être\s+apportée\b",
    re.IGNORECASE,
)
_BENEFICIARY = re.compile(
    r"\b(?:titulaire|prestataire|attributaire|fournisseur)\b[^.!?]{0,100}"
    r"\bse\s+voir\b",
    re.IGNORECASE,
)
_EXPLICIT_CONTRACTOR = re.compile(
    r"\b(?:titulaire|prestataire|attributaire|fournisseur|entrepreneur|cocontractant)\b"
    r"|\b(?:par|à la charge de|a la charge de)\s+(?:l['’]|le |la )?"
    r"(?:titulaire|prestataire|attributaire|fournisseur|entrepreneur)\b",
    re.IGNORECASE,
)
_FRAGMENT_END = re.compile(r"[:;,]\s*$")


def _finding(code: RiskCode, match: re.Match[str] | str) -> EligibilityFinding:
    return EligibilityFinding(code, match if isinstance(match, str) else match.group(0))


def eligibility_guard(snapshot: CandidateSnapshot) -> EligibilityResult:
    sentence = snapshot.excerpt.strip()
    findings: list[EligibilityFinding] = []

    structural = phase_guard(snapshot)
    if structural.verdict == "BLOCK" and structural.reason:
        code = f"phase_guard_{structural.reason}"
        findings.append(_finding(code, snapshot.document_name or snapshot.heading or ""))  # type: ignore[arg-type]

    for code, pattern in (
        ("external_pronoun", _PRONOUN),
        ("external_demonstrative", _DEMONSTRATIVE),
        ("external_anaphora", _ANAPHORA),
        ("impersonal_actor", _IMPERSONAL),
        ("contractor_beneficiary", _BENEFICIARY),
        ("fragment", _FRAGMENT_END),
    ):
        match = pattern.search(sentence)
        if match:
            findings.append(_finding(code, match))  # type: ignore[arg-type]

    if not _EXPLICIT_CONTRACTOR.search(sentence):
        findings.append(_finding("actor_not_explicit", sentence[:120]))

    unique = {finding.code: finding for finding in findings}
    return EligibilityResult(tuple(unique.values()))
```

- [ ] **Step 4: Run the focused tests and lint the module**

Run: `uv run pytest tests/test_spec009_eligibility.py -q && uv run ruff check src/signals/documents/eligibility.py tests/test_spec009_eligibility.py`

Expected: all eligibility tests pass and Ruff prints `All checks passed!`.

- [ ] **Step 5: Commit the guard**

```bash
git add src/signals/documents/eligibility.py tests/test_spec009_eligibility.py
git commit -m "feat(spec009): add precision-first eligibility guard"
```

### Task 2: Sentence-only and contextual verification contracts

**Files:**
- Create: `src/signals/documents/precision_verification.py`
- Create: `tests/test_spec009_verification.py`

- [ ] **Step 1: Write failing contract and prompt-separation tests**

```python
# tests/test_spec009_verification.py
import json

from signals.documents.precision_verification import (
    ContextVerification,
    SentenceVerification,
    build_context_prompt,
    build_sentence_prompt,
    parse_context_verification,
    parse_sentence_verification,
    strict_schema,
)
from tests.test_spec009_eligibility import snap


def test_sentence_prompt_contains_only_the_candidate_sentence() -> None:
    snapshot = snap("Le titulaire doit assurer la maintenance.")
    prompt = build_sentence_prompt(snapshot)
    assert snapshot.excerpt in prompt
    assert snapshot.previous_block not in prompt
    assert "BLOC PRÉCÉDENT" not in prompt
    assert "UNTRUSTED SOURCE TEXT" in prompt


def test_context_prompt_contains_context_but_not_the_primary_decision() -> None:
    snapshot = snap("Le titulaire doit assurer la maintenance.")
    prompt = build_context_prompt(snapshot)
    assert snapshot.previous_block in prompt
    assert "obligated_actor" not in prompt
    assert "confidence" not in prompt.casefold()


def test_closed_sentence_schema_requires_every_field() -> None:
    schema = strict_schema(SentenceVerification)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_parsers_never_repair_an_invalid_answer() -> None:
    assert parse_sentence_verification('{"verdict":"confirm"}') is None
    assert parse_context_verification("je confirme") is None


def test_valid_answers_round_trip() -> None:
    sentence = parse_sentence_verification(json.dumps({
        "verdict": "confirm",
        "self_contained": True,
        "actor": "contractor",
        "actor_excerpt": "Le titulaire",
        "modality_excerpt": "doit",
        "reason": "explicit_execution_contractor",
    }))
    context = parse_context_verification(json.dumps({
        "verdict": "confirm",
        "phase": "execution",
        "actor": "contractor",
        "normative": True,
        "reason": "execution_contractor",
        "supporting_excerpt": "Le titulaire doit assurer la maintenance.",
    }))
    assert isinstance(sentence, SentenceVerification)
    assert isinstance(context, ContextVerification)
```

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: `uv run pytest tests/test_spec009_verification.py -q`

Expected: collection fails because `precision_verification` does not exist.

- [ ] **Step 3: Implement closed response types, strict schemas, exact parsers, and separated prompts**

Create `precision_verification.py` with:

```python
from __future__ import annotations

import json
import re
from typing import Literal, TypeVar

from pydantic import BaseModel

from signals.documents.classification import UNTRUSTED_PROMPT_HEADER
from signals.documents.snapshot import CandidateSnapshot
from signals.domain.values import CanonicalModel, NonEmptyStr

SENTENCE_PROMPT_VERSION = "spec009-sentence-v1"
CONTEXT_PROMPT_VERSION = "spec009-context-v1"

Actor = Literal["contractor", "buyer", "third_party", "mixed", "unknown"]
VerifierVerdict = Literal["confirm", "block", "uncertain"]


class SentenceVerification(CanonicalModel):
    verdict: VerifierVerdict
    self_contained: bool
    actor: Actor
    actor_excerpt: str | None
    modality_excerpt: str | None
    reason: Literal[
        "explicit_execution_contractor",
        "external_reference",
        "fragment",
        "actor_buyer",
        "actor_third_party",
        "actor_mixed",
        "actor_unknown",
        "not_normative",
    ]


class ContextVerification(CanonicalModel):
    verdict: VerifierVerdict
    phase: Literal["execution", "procurement", "qualification", "contract_formation", "unknown"]
    actor: Actor
    normative: bool
    reason: Literal[
        "execution_contractor",
        "procurement",
        "qualification",
        "contract_formation",
        "buyer_obligation",
        "third_party_obligation",
        "informational",
        "insufficient_context",
    ]
    supporting_excerpt: NonEmptyStr


T = TypeVar("T", bound=BaseModel)


def strict_schema(model: type[T]) -> dict[str, object]:
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    definitions = schema.pop("$defs", {})
    for name, prop in list(schema.get("properties", {}).items()):
        reference = prop.pop("$ref", None) or prop.pop("allOf", [{}])[0].get("$ref")
        if reference:
            schema["properties"][name] = {**definitions[reference.rsplit("/", 1)[-1]], **prop}
    schema["required"] = list(schema.get("properties", {}))
    return schema


def _parse(payload: str, model: type[T]) -> T | None:
    text = payload.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return model(**json.loads(text[start : end + 1]))
    except Exception:  # noqa: BLE001
        return None


def parse_sentence_verification(payload: str) -> SentenceVerification | None:
    return _parse(payload, SentenceVerification)


def parse_context_verification(payload: str) -> ContextVerification | None:
    return _parse(payload, ContextVerification)
```

Add two complete instruction constants. `SENTENCE_INSTRUCTIONS` must explicitly
forbid external reference resolution and require copied actor/modality spans.
`CONTEXT_INSTRUCTIONS` must ask the four legal-boundary questions and state that
context may block but cannot repair sentence-level actor or self-containment.
`build_sentence_prompt()` must interpolate only `[PHRASE] {snapshot.excerpt}`;
`build_context_prompt()` must interpolate document, heading, previous/current/
next blocks, and proposed sentence. Both wrap source text with
`UNTRUSTED_PROMPT_HEADER`.

- [ ] **Step 4: Run contract tests and existing prompt-injection tests**

Run: `uv run pytest tests/test_spec009_verification.py tests/test_document_adversarial.py::TestIPromptInjection -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the semantic contracts**

```bash
git add src/signals/documents/precision_verification.py tests/test_spec009_verification.py
git commit -m "feat(spec009): split sentence and context verification"
```

### Task 3: Fail-closed acceptance policy and system confidence

**Files:**
- Create: `src/signals/documents/precision_policy.py`
- Create: `tests/test_spec009_policy.py`

- [ ] **Step 1: Write failing policy tests for every acceptance condition**

Write helpers producing an accepted `SemanticClassification`, an empty
`EligibilityResult`, and confirming A/B responses. Assert:

```python
def test_every_condition_aligned_is_auto_accepted() -> None:
    decision = precision_decision(primary(), eligible(), sentence_ok(), context_ok(), snapshot=snap())
    assert decision.outcome == "auto_accepted"
    assert decision.reason is None
    assert decision.evidence


@pytest.mark.parametrize("missing,reason", [
    ("primary", "primary_failure"),
    ("sentence", "sentence_verifier_failure"),
    ("context", "context_verifier_failure"),
])
def test_missing_answers_are_technical_review(missing: str, reason: str) -> None:
    values = {"primary": primary(), "sentence": sentence_ok(), "context": context_ok()}
    values[missing] = None
    decision = precision_decision(
        values["primary"], eligible(), values["sentence"], values["context"], snapshot=snap()
    )
    assert decision.outcome == "review_required"
    assert decision.reason == reason
    assert decision.technical_failure


def test_an_actor_span_absent_from_the_sentence_is_reviewed() -> None:
    answer = sentence_ok(actor_excerpt="le fournisseur fantôme")
    assert precision_decision(primary(), eligible(), answer, context_ok(), snapshot=snap()).reason == "actor_excerpt_not_found"


def test_model_confidence_is_not_part_of_system_confidence() -> None:
    assert "confidence" not in SentenceVerification.model_fields
    assert "confidence" not in ContextVerification.model_fields
```

Also cover: primary rejection, invalid primary evidence, guard finding, A not
self-contained, A actor not contractor, missing modality span, B not execution,
B actor mismatch, B non-normative, B evidence failure, and `PhaseGuard` block.

- [ ] **Step 2: Run the policy tests and confirm the missing-module failure**

Run: `uv run pytest tests/test_spec009_policy.py -q`

Expected: collection fails because `precision_policy` does not exist.

- [ ] **Step 3: Implement the versioned two-outcome policy**

```python
# src/signals/documents/precision_policy.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from signals.documents.classification import SemanticClassification, decide, normalize_for_match
from signals.documents.eligibility import EligibilityResult
from signals.documents.precision_verification import ContextVerification, SentenceVerification
from signals.documents.snapshot import CandidateSnapshot, validate_excerpt

PRECISION_POLICY_VERSION = "spec009-precision-v1"
SystemConfidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class PrecisionDecision:
    outcome: Literal["auto_accepted", "review_required"]
    reason: str | None
    confidence: SystemConfidence
    technical_failure: bool = False
    evidence: tuple[tuple[str, str], ...] = ()
    policy_version: str = PRECISION_POLICY_VERSION


def _review(reason: str, *, technical: bool = False) -> PrecisionDecision:
    return PrecisionDecision("review_required", reason, "low", technical)


def _located(fragment: str | None, sentence: str) -> bool:
    return bool(fragment and normalize_for_match(fragment) in normalize_for_match(sentence))


def precision_decision(
    primary: SemanticClassification | None,
    guard: EligibilityResult,
    sentence: SentenceVerification | None,
    context: ContextVerification | None,
    *,
    snapshot: CandidateSnapshot,
) -> PrecisionDecision:
    if guard.findings:
        return _review(guard.findings[0].code)
    if primary is None:
        return _review("primary_failure", technical=True)
    primary_policy = decide(primary, source_text=snapshot.logical_span or snapshot.current_block)
    if not primary_policy.accepted:
        return _review(primary_policy.reason or "primary_rejected")
    evidence = validate_excerpt(primary.source_excerpt, snapshot)
    if not evidence.ok:
        return _review("primary_evidence_failure")
    if sentence is None:
        return _review("sentence_verifier_failure", technical=True)
    if sentence.verdict != "confirm" or not sentence.self_contained:
        return _review(sentence.reason)
    if sentence.actor != "contractor":
        return _review(sentence.reason)
    if not _located(sentence.actor_excerpt, snapshot.excerpt):
        return _review("actor_excerpt_not_found")
    if not _located(sentence.modality_excerpt, snapshot.excerpt):
        return _review("modality_excerpt_not_found")
    if context is None:
        return _review("context_verifier_failure", technical=True)
    if context.verdict != "confirm":
        return _review(context.reason)
    if context.phase != "execution":
        return _review(f"phase_{context.phase}")
    if context.actor != "contractor":
        return _review(f"actor_{context.actor}")
    if not context.normative:
        return _review("not_normative")
    context_evidence = validate_excerpt(context.supporting_excerpt, snapshot)
    if not context_evidence.ok:
        return _review("context_evidence_failure")

    explicit_title = normalize_for_match(sentence.actor_excerpt or "") in {
        "le titulaire", "la titulaire", "le prestataire", "la prestataire",
        "l attributaire", "le fournisseur", "la fournisseuse",
    }
    confidence: SystemConfidence = "high" if explicit_title else "medium"
    return PrecisionDecision("auto_accepted", None, confidence, evidence=evidence.pieces)
```

- [ ] **Step 4: Run policy and historical evidence tests**

Run: `uv run pytest tests/test_spec009_policy.py tests/test_r5_adversarial.py::TestEvidenceValidator -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the policy**

```bash
git add src/signals/documents/precision_policy.py tests/test_spec009_policy.py
git commit -m "feat(spec009): add fail-closed precision policy"
```

### Task 4: Structured OpenRouter verifier transport

**Files:**
- Create: `src/signals/documents/precision_openrouter.py`
- Create: `tests/test_spec009_openrouter.py`

- [ ] **Step 1: Write failing transport tests with `httpx.MockTransport`**

Test both methods against captured request JSON. Assert exact model, temperature
zero when supported, `response_format.type == "json_schema"`,
`strict == True`, `provider.require_parameters == True`, and usage inclusion.
Also assert:

```python
def test_a_402_is_credit_failure_not_a_semantic_answer(monkeypatch) -> None:
    verifier = make_verifier(lambda _: httpx.Response(402, json={"error": "credits"}))
    assert verifier.verify_sentence(snap()) is None
    assert verifier.last_failure == "api_credit_failure"


def test_a_schema_failure_is_not_repaired() -> None:
    verifier = make_verifier(reply("not-json"))
    assert verifier.verify_context(snap()) is None
    assert verifier.last_failure == "schema_failure"


def test_a_changed_response_model_is_refused() -> None:
    verifier = make_verifier(reply(valid_sentence(), model="another/model"), expected_model="pinned/model")
    assert verifier.verify_sentence(snap()) is None
    assert verifier.last_failure == "model_version_mismatch"
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `uv run pytest tests/test_spec009_openrouter.py -q`

Expected: missing-module failure.

- [ ] **Step 3: Implement one reusable structured transport with two public methods**

Create a dataclass `OpenRouterPrecisionVerifier` with fields `model`,
`expected_response_model`, `api_key`, `max_tokens=4000`, `timeout=60.0`, separate
`LlmUsage` counters for sentence/context, total reported cost, `last_failure`,
and a lazy `httpx.Client`. Reject `max_tokens < MIN_REASONING_TOKENS` in
`__post_init__`.

Implement:

```python
def verify_sentence(self, snapshot: CandidateSnapshot) -> SentenceVerification | None:
    return self._ask(
        prompt=build_sentence_prompt(snapshot),
        schema_name="spec009_sentence_verification",
        schema=strict_schema(SentenceVerification),
        parser=parse_sentence_verification,
        usage=self.sentence_usage,
    )


def verify_context(self, snapshot: CandidateSnapshot) -> ContextVerification | None:
    return self._ask(
        prompt=build_context_prompt(snapshot),
        schema_name="spec009_context_verification",
        schema=strict_schema(ContextVerification),
        parser=parse_context_verification,
        usage=self.context_usage,
    )
```

`_ask()` must use the same HTTP error taxonomy as `OpenRouterClassifier`, refuse
empty choices, validate the returned model when `expected_response_model` is
set, parse with Pydantic, and record actual cost. It performs one request only;
the resumable harness in Task 9 owns bounded retries so an API failure never
becomes a semantic result.

- [ ] **Step 4: Run transport tests and existing API-failure regressions**

Run: `uv run pytest tests/test_spec009_openrouter.py tests/test_r5_api_failures.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the adapter**

```bash
git add src/signals/documents/precision_openrouter.py tests/test_spec009_openrouter.py
git commit -m "feat(spec009): add pinned structured verifier transport"
```

### Task 5: Precision cascade orchestration and trace

**Files:**
- Create: `src/signals/documents/precision_pipeline.py`
- Create: `tests/test_spec009_pipeline.py`

- [ ] **Step 1: Write failing call-order and fail-closed tests**

Define stubs that append `guard`, `primary`, `sentence`, and `context` to a list.
Assert:

- an ineligible sentence calls no model;
- primary rejection calls neither verifier;
- sentence rejection does not call the contextual verifier;
- a technical `None` is recorded as review and never retried inside the policy;
- a fully aligned candidate calls `guard → primary → sentence → context`;
- duplicate candidate IDs raise `ValueError`;
- input order is preserved;
- the trace serializes every model version, failure category, response, latency,
  evidence, and final reason.

- [ ] **Step 2: Run the pipeline tests and confirm failure**

Run: `uv run pytest tests/test_spec009_pipeline.py -q`

Expected: missing-module failure.

- [ ] **Step 3: Implement protocols and orchestration**

Define `SentenceVerifier` and `ContextVerifier` protocols, `CandidateTrace`, and
`PrecisionRun`. Implement `run_precision_candidates()` with this exact order:

```python
guard = eligibility_guard(snapshot)
if guard.findings:
    decision = precision_decision(None, guard, None, None, snapshot=snapshot)
else:
    primary_answer = primary.classify_snapshot(snapshot)
    provisional = precision_decision(primary_answer, guard, None, None, snapshot=snapshot)
    if provisional.reason in {"sentence_verifier_failure"}:
        sentence_answer = verifier.verify_sentence(snapshot)
        sentence_ready = precision_decision(
            primary_answer, guard, sentence_answer, None, snapshot=snapshot
        )
        if sentence_ready.reason == "context_verifier_failure":
            context_answer = verifier.verify_context(snapshot)
    decision = precision_decision(
        primary_answer, guard, sentence_answer, context_answer, snapshot=snapshot
    )
```

Initialize all answer variables to `None`; time each actual call with
`time.perf_counter()`. Do not infer a failure kind: copy `last_failure` from the
adapter after a missing answer. `PrecisionRun.as_dict()` must be JSON-safe and
preserve candidate order.

- [ ] **Step 4: Run pipeline tests and historical pipeline tests**

Run: `uv run pytest tests/test_spec009_pipeline.py tests/test_document_pipeline.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the orchestrator**

```bash
git add src/signals/documents/precision_pipeline.py tests/test_spec009_pipeline.py
git commit -m "feat(spec009): orchestrate the precision-first cascade"
```

### Task 6: Frozen configuration manifest

**Files:**
- Create: `src/signals/documents/precision_manifest.py`
- Create: `tests/test_spec009_manifest.py`
- Create: `tests/fixtures/documents/spec009_model_candidates.json`

- [ ] **Step 1: Write failing manifest tests**

Assert `SelectedConfiguration` requires prompt hashes, policy/guard versions,
requested and observed model IDs, model-catalog canonical slugs, parameters,
DEV report hash, and creation timestamp. Assert `FrozenRunManifest` additionally
binds one selected-configuration hash to one corpus hash and one gold hash.
Assert `assert_matches()` raises on one-byte corpus changes, prompt changes,
configuration changes, or observed-model drift.

- [ ] **Step 2: Add the model-candidate fixture sourced from the live catalog**

```json
{
  "retrieved_at": "2026-08-17",
  "catalog_url": "https://openrouter.ai/api/v1/models",
  "required_parameters": ["response_format", "structured_outputs"],
  "models": [
    "anthropic/claude-sonnet-5",
    "openai/gpt-5.5",
    "google/gemini-3.7-flash",
    "deepseek/deepseek-v4-pro-0813",
    "qwen/qwen3.8-2.4t-a95b"
  ],
  "baseline_primary": "deepseek/deepseek-v4-flash"
}
```

At execution time, verify these exact IDs still exist and still advertise both
required parameters. A missing candidate is recorded as unavailable; it is not
silently replaced after selection begins.

- [ ] **Step 3: Implement canonical JSON and SHA-256 helpers**

Create `SelectedConfiguration(CanonicalModel)`,
`FrozenRunManifest(CanonicalModel)`, and:

```python
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def prompt_hash(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def assert_matches(
    manifest: FrozenRunManifest,
    *,
    configuration: pathlib.Path,
    corpus: pathlib.Path,
    gold: pathlib.Path,
) -> None:
    selected = SelectedConfiguration.model_validate_json(configuration.read_text())
    if sha256_file(configuration) != manifest.configuration_sha256:
        raise ValueError("configuration différente du manifeste gelé")
    if sha256_file(corpus) != manifest.corpus_sha256:
        raise ValueError("corpus différent du manifeste gelé")
    if sha256_file(gold) != manifest.gold_sha256:
        raise ValueError("gold différent du manifeste gelé")
    if selected.guard_version != ELIGIBILITY_GUARD_VERSION:
        raise ValueError("version de garde différente du manifeste")
    if selected.policy_version != PRECISION_POLICY_VERSION:
        raise ValueError("version de politique différente du manifeste")
    if selected.sentence_prompt_sha256 != prompt_hash(SENTENCE_INSTRUCTIONS):
        raise ValueError("prompt phrase différent du manifeste")
    if selected.context_prompt_sha256 != prompt_hash(CONTEXT_INSTRUCTIONS):
        raise ValueError("prompt contexte différent du manifeste")
```

Add a CLI that creates a target-specific run manifest without making a model
call:

```text
python -m signals.documents.precision_manifest create-run \
  --configuration PATH --corpus PATH --gold PATH --out PATH
```

- [ ] **Step 4: Run manifest tests**

Run: `uv run pytest tests/test_spec009_manifest.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit reproducibility contracts**

```bash
git add src/signals/documents/precision_manifest.py tests/test_spec009_manifest.py tests/fixtures/documents/spec009_model_candidates.json
git commit -m "feat(spec009): freeze precision run configuration"
```

### Task 7: Honest precision metrics and statistical gates

**Files:**
- Create: `src/signals/documents/precision_evaluation.py`
- Create: `tests/test_spec009_evaluation.py`

- [ ] **Step 1: Write failing Wilson and gate tests**

```python
def test_wilson_dimensioning_matches_the_design() -> None:
    assert wilson_lower_bound(73, 73) >= 0.95
    assert wilson_lower_bound(72, 72) < 0.95
    assert wilson_lower_bound(109, 110) >= 0.95
    assert wilson_lower_bound(108, 109) < 0.95


def test_point_precision_must_be_strictly_above_95_percent() -> None:
    result = activation_gate(metrics(successes=95, accepted=100))
    assert "auto_accepted_precision" in result.failures


def test_one_high_system_confidence_false_accept_always_fails() -> None:
    result = activation_gate(metrics(successes=109, accepted=110, high_false=1))
    assert "high_confidence_false_auto_accepted" in result.failures


def test_regression_gate_does_not_claim_blind_statistical_proof() -> None:
    result = regression_gate(metrics(successes=52, accepted=52, consultations=8))
    assert result.passed
    assert result.kind == "known_regression"


def test_activation_requires_ten_covered_consultations() -> None:
    result = activation_gate(metrics(successes=73, accepted=73, consultations=9))
    assert "consultation_coverage" in result.failures
```

Also test zero accepted, evidence below 100%, invented excerpt, per-consultation
counts, per-document-kind counts, and an unlabeled candidate raising `KeyError`.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `uv run pytest tests/test_spec009_evaluation.py -q`

Expected: missing-module failure.

- [ ] **Step 3: Implement metrics without recall gates**

```python
def wilson_lower_bound(successes: int, total: int, *, z: float = 1.96) -> float | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return center - margin
```

Define `PrecisionMetrics`, `GroupedMetrics`, and `PrecisionGateResult`. `score()`
must treat only `gold_disposition == "auto_acceptable"` as true. A review or
reject gold row auto-accepted by the pipeline is false. `activation_gate()` must
require all of:

```python
metrics.auto_accepted_precision is not None
metrics.auto_accepted_precision > 0.95
metrics.wilson_lower_95 is not None
metrics.wilson_lower_95 >= 0.95
metrics.high_confidence_false_auto_accepted == 0
metrics.evidence_coverage == 1.0
metrics.excerpts_invented == 0
metrics.covered_consultations >= 10
```

`regression_gate()` uses the same requirements except Wilson and consultation
coverage, and labels its output `known_regression`.

- [ ] **Step 4: Run evaluation tests and existing metric regressions**

Run: `uv run pytest tests/test_spec009_evaluation.py tests/test_document_evaluation.py -q`

Expected: both historical and SPEC-009 tests pass.

- [ ] **Step 5: Commit the gates**

```bash
git add src/signals/documents/precision_evaluation.py tests/test_spec009_evaluation.py
git commit -m "feat(spec009): add blind precision activation gate"
```

### Task 8: Corpus loading, integrity, and triple disjointness

**Files:**
- Create: `src/signals/documents/activation_corpus.py`
- Create: `tests/test_spec009_activation_corpus.py`
- Modify: `src/signals/research/fr_corpus_run.py`

- [ ] **Step 1: Write failing corpus-contract tests**

Use temporary JSON fixtures to assert:

- every corpus row constructs a `CandidateSnapshot`;
- candidate IDs are unique and align one-to-one with gold rows;
- exact excerpt and document hash agree between corpus and gold;
- every source maps document hash to consultation and document kind;
- at least 25 distinct consultations exist before freeze;
- two adjudications and an arbitration record predate `first_model_call_at`;
- duplicate consultation, document hash, or normalized sentence against any
  historical corpus raises a named error;
- corpus and gold SHA-256 values are written only after validation.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `uv run pytest tests/test_spec009_activation_corpus.py -q`

Expected: missing-module failure.

- [ ] **Step 3: Implement dynamic historical-corpus scanning and freeze validation**

Implement:

```python
def sentence_hash(excerpt: str) -> str:
    return hashlib.sha256(normalize_for_match(excerpt).encode()).hexdigest()


def historical_keys(fixtures: pathlib.Path, *, exclude: frozenset[str] = frozenset()) -> CorpusKeys:
    consultations: set[str] = set()
    documents: set[str] = set()
    sentences: set[str] = set()
    for path in sorted(fixtures.glob("*.json")):
        if path.name in exclude:
            continue
        payload = json.loads(path.read_text())
        for source in payload.get("sources", []):
            if source.get("consultation"):
                consultations.add(str(source["consultation"]))
            if source.get("document_hash"):
                documents.add(str(source["document_hash"]))
        for row in payload.get("rows", []):
            if row.get("document_hash"):
                documents.add(str(row["document_hash"]))
            excerpt = row.get("excerpt") or row.get("gold_exact_excerpt")
            if excerpt:
                sentences.add(sentence_hash(str(excerpt)))
    return CorpusKeys(frozenset(consultations), frozenset(documents), frozenset(sentences))
```

`validate_activation_corpus()` must compare new keys to historical keys, validate
the adjudication metadata and alignments, and return a `FrozenCorpusManifest`.
It must not write when validation fails. `write_freeze_manifest()` writes
canonical JSON with corpus and gold hashes after validation.

Add an `--exclude-known` flag to `fr_corpus_run.py`. When set, merge the explicit
`--exclude-consultations` values with
`historical_keys(FIXTURES).consultations` before calling `run()`. Add a small CLI
to `activation_corpus.py`:

```text
python -m signals.documents.activation_corpus validate --corpus PATH --fixtures DIR
python -m signals.documents.activation_corpus freeze --corpus PATH --gold PATH --out PATH
```

`validate` performs triple disjointness and structural validation without
writing. `freeze` repeats validation and writes only the SHA manifest.

- [ ] **Step 4: Run corpus integrity and historical disjunction tests**

Run: `uv run pytest tests/test_spec009_activation_corpus.py tests/test_r5_disjunction.py tests/test_fr_dce_final_gold.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the corpus contract**

```bash
git add src/signals/documents/activation_corpus.py src/signals/research/fr_corpus_run.py tests/test_spec009_activation_corpus.py
git commit -m "feat(spec009): enforce blind corpus integrity"
```

### Task 9: Resumable run harness

**Files:**
- Create: `src/signals/research/spec009_run.py`
- Create: `tests/test_spec009_run.py`

- [ ] **Step 1: Write failing offline harness tests**

Assert the harness:

- loads candidate rows into snapshots;
- maps source document hashes to consultation and kind;
- refuses a manifest/hash mismatch before calling a model;
- checkpoints after each candidate using an atomic temporary-file replacement;
- resumes only missing candidates;
- preserves completed answers byte-for-byte;
- retries only `transport_failure`, `api_rate_limit`, and `provider_failure`, at
  most twice with the same frozen request;
- never retries semantic `block`/`uncertain` or schema-valid answers;
- writes failures as failures, not rejects;
- refuses to merge checkpoints with a different manifest hash.

- [ ] **Step 2: Run harness tests and confirm failure**

Run: `uv run pytest tests/test_spec009_run.py -q`

Expected: missing-module failure.

- [ ] **Step 3: Implement the CLI and atomic checkpointing**

The CLI must accept:

```text
--corpus PATH --gold PATH --configuration PATH --manifest PATH --out PATH
--checkpoint PATH --mode {dev,regression,activation} --workers N
```

It obtains model IDs and parameters only from the manifest. Use
`tempfile.NamedTemporaryFile(dir=target.parent, delete=False)` followed by
`Path.replace(target)` for atomic writes. A checkpoint entry contains the input
snapshot hash, request/prompt hashes, raw structured answers, model IDs,
failures, attempts, latency, cost, evidence, and final decision.

For `regression`, call `regression_gate`; for `activation`, call
`activation_gate`; for `dev`, report metrics without declaring activation.
Return exit code `0` only for a passed requested gate, `2` for a metric failure,
and `3` for corpus/manifest/configuration failure.

- [ ] **Step 4: Run offline harness tests**

Run: `uv run pytest tests/test_spec009_run.py -q`

Expected: all tests pass without network access.

- [ ] **Step 5: Commit the harness**

```bash
git add src/signals/research/spec009_run.py tests/test_spec009_run.py
git commit -m "feat(spec009): add resumable frozen evaluation runner"
```

### Task 10: DEV model selection

**Files:**
- Create: `src/signals/research/spec009_model_selection.py`
- Create: `tests/test_spec009_model_selection.py`

- [ ] **Step 1: Write failing deterministic-selection tests**

Assert that selection:

- uses only DEV fixtures (`fr_dce_gold_dev.json` plus the ordered union of
  `fr_dce_candidates.json` and `fr_dce_candidates_ext.json`);
- excludes FR-DCE-FINAL by filename and SHA;
- checks every candidate ID against the live model catalog before calls;
- shares one cached primary result set across verifier candidates;
- repeats each verifier three times on the same ordered survivors;
- measures exact-decision stability, precision by reason, schema failures, cost,
  and latency;
- chooses highest precision, then fewest high-confidence false accepts, then
  highest stability, then lowest cost as deterministic tie-breakers;
- refuses to choose any verifier with stability below 0.95 or a schema-failure
  rate above 0.01;
- emits the selected requested and observed model IDs into a frozen selected configuration.

- [ ] **Step 2: Run selection tests and confirm failure**

Run: `uv run pytest tests/test_spec009_model_selection.py -q`

Expected: missing-module failure.

- [ ] **Step 3: Implement the selection CLI**

The CLI accepts:

```text
--candidates tests/fixtures/documents/spec009_model_candidates.json
--corpus tests/fixtures/documents/fr_dce_candidates.json
--corpus tests/fixtures/documents/fr_dce_candidates_ext.json
--gold tests/fixtures/documents/fr_dce_gold_dev.json
--out work/spec009-model-selection.json
--configuration work/spec009-selected-configuration.json
--repetitions 3 --cost-cap-usd 25
```

Before the first paid call, require `gold["corpus"] == "DEV-FR-DCE"`, require
the two corpus basenames shown above, and verify that their combined candidate
IDs align exactly with the 400 gold rows. Refuse any reference to
`fr_dce_final_*`. Fetch the model catalog once, record its response SHA, validate
required structured-output parameters, and stop before exceeding the cost cap.
Do not replace unavailable models.

For each model, run the same guard, cached primary results, sentence prompt,
context prompt, and policy. Keep all raw answers. Select deterministically using
the ordered criteria from Step 1. The output report includes per-repeat and
aggregate results; the selected configuration contains only the winner, prompt/
policy hashes, catalog proof, parameters, and DEV report hash. It contains no
future corpus hash.

- [ ] **Step 4: Run selection tests and the complete offline suite before paid calls**

Run: `uv run pytest tests/test_spec009_model_selection.py -q && uv run pytest -q`

Expected: selection tests and the full suite pass.

- [ ] **Step 5: Commit the selection tool before observing model results**

```bash
git add src/signals/research/spec009_model_selection.py tests/test_spec009_model_selection.py
git commit -m "feat(spec009): add reproducible verifier bake-off"
```

- [ ] **Step 6: Run the paid DEV bake-off once and freeze the winner**

Run:

```bash
uv run python -m signals.research.spec009_model_selection \
  --candidates tests/fixtures/documents/spec009_model_candidates.json \
  --corpus tests/fixtures/documents/fr_dce_candidates.json \
  --corpus tests/fixtures/documents/fr_dce_candidates_ext.json \
  --gold tests/fixtures/documents/fr_dce_gold_dev.json \
  --out work/spec009-model-selection.json \
  --configuration work/spec009-selected-configuration.json \
  --repetitions 3 \
  --cost-cap-usd 25
```

Expected: exit `0`, one selected verifier, no use of FR-DCE-FINAL, and actual
cost at or below `$25`. If no candidate satisfies stability/schema criteria,
stop and write a failed DEV report; do not open the regression or held-out.

### Task 11: Known FR-DCE-FINAL regression

**Files:**
- Create: `tests/test_spec009_final_regression.py`
- Generated after the run: `docs/reports/2026-08-17-spec009-final-regression.md`

- [ ] **Step 1: Add deterministic regression tests for the eleven known errors**

Load candidate IDs `37, 104, 107, 110, 114, 116, 123, 125, 144, 147, 195`
from the immutable corpus. Apply `eligibility_guard()` and assert every one has
at least one generic blocking reason. Assert the expected category families,
not an ID-specific lookup table:

```python
EXPECTED = {
    37: "external_pronoun", 104: "external_demonstrative",
    107: "external_pronoun", 110: "actor_not_explicit",
    114: "external_pronoun", 116: "actor_not_explicit",
    123: "fragment", 125: "actor_not_explicit",
    144: "contractor_beneficiary", 147: "impersonal_actor",
    195: "impersonal_actor",
}
```

Also assert at least one clear explicit-contractor gold requirement remains
eligible, preventing the degenerate “block everything” implementation.

- [ ] **Step 2: Run deterministic regression tests**

Run: `uv run pytest tests/test_spec009_final_regression.py -q`

Expected: all tests pass without a model call.

- [ ] **Step 3: Create the target-specific regression manifest**

Run:

```bash
uv run python -m signals.documents.precision_manifest create-run \
  --configuration work/spec009-selected-configuration.json \
  --corpus tests/fixtures/documents/fr_dce_final_candidates.json \
  --gold tests/fixtures/documents/fr_dce_final_gold.json \
  --out work/spec009-final-manifest.json
```

Expected: the manifest binds the selected-configuration SHA and immutable
FR-DCE-FINAL corpus/gold SHA without making a model call.

- [ ] **Step 4: Run the frozen regression exactly once**

Run:

```bash
uv run python -m signals.research.spec009_run \
  --corpus tests/fixtures/documents/fr_dce_final_candidates.json \
  --gold tests/fixtures/documents/fr_dce_final_gold.json \
  --configuration work/spec009-selected-configuration.json \
  --manifest work/spec009-final-manifest.json \
  --checkpoint work/spec009-final-checkpoint.json \
  --out work/spec009-final-regression.json \
  --mode regression \
  --workers 6
```

Expected: precision strictly above 95%, zero high-system-confidence false
accepts, 100% evidence, zero invented excerpts. If it fails, stop; return to a
new DEV version rather than changing FR-DCE-FINAL.

- [ ] **Step 5: Write and commit the immutable regression report**

The report must copy the manifest SHA, corpus/gold SHA, exact command, counts,
precision, recall diagnostic, every false acceptance, abstention reasons, cost,
latency, and gate verdict from `work/spec009-final-regression.json`.

```bash
git add tests/test_spec009_final_regression.py docs/reports/2026-08-17-spec009-final-regression.md
git commit -m "test(spec009): record known final regression"
```

### Task 12: Build and freeze the blind activation corpus

**Files:**
- Generated: `tests/fixtures/documents/spec009_activation_candidates.json`
- Generated by independent adjudication: `tests/fixtures/documents/spec009_activation_gold.json`
- Generated: `tests/fixtures/documents/spec009_activation_freeze.json`
- Create after freeze: `tests/test_spec009_activation_freeze.py`

- [ ] **Step 1: Acquire at least 25 new consultations with the existing anonymous France path**

Run:

```bash
uv run python -m signals.research.fr_corpus_run \
  --consultations 35 \
  --per-document 25 \
  --exclude-known \
  --out work/spec009_activation_pool.json
```

The larger acquisition target provides room for corpus attrition without adding
candidates after model observation.

- [ ] **Step 2: Validate triple disjointness before annotation**

Run:

```bash
uv run python -m signals.documents.activation_corpus validate \
  --corpus work/spec009_activation_pool.json \
  --fixtures tests/fixtures/documents
```

Expected: zero consultation, document, or normalized-sentence overlap.
Remove only objectively duplicated rows reported by the validator; do not filter
on wording difficulty or expected model behavior.

- [ ] **Step 3: Perform two independent adjudications before any candidate-model call**

Each adjudicator writes all fields already used by FR-DCE-FINAL:
`gold_disposition`, `gold_phase`, `gold_obligated_actor`, `gold_modality`,
`gold_context_status`, `gold_reason`, `gold_exact_excerpt`, source locators, and
note. Neither adjudicator sees a model output. Resolve disagreements in a third
logged pass and store old/new values plus rationale.

- [ ] **Step 4: Freeze only after the statistical sample can be reached**

Before model calls, verify the gold contains enough explicit, self-contained
requirements that the conservative pipeline can plausibly yield at least 73
auto-accepts. This check may enlarge the blind corpus before freeze, but may not
select or remove individual candidates based on a model result.

Write final candidates and gold, then run `write_freeze_manifest()` to record
their SHA-256 hashes, adjudicator identities, arbitration time, and
`first_model_call_at: null`.

Run:

```bash
uv run python -m signals.documents.activation_corpus freeze \
  --corpus tests/fixtures/documents/spec009_activation_candidates.json \
  --gold tests/fixtures/documents/spec009_activation_gold.json \
  --out tests/fixtures/documents/spec009_activation_freeze.json
```

- [ ] **Step 5: Pin the frozen bytes in tests**

Create tests equivalent to `test_fr_dce_final_gold.py`: exact SHA assertions,
one-to-one IDs, excerpt/hash alignment, at least 25 consultations, triple
disjointness, two adjudications, journaled arbitration, and absence of model
calls before freeze.

Run: `uv run pytest tests/test_spec009_activation_freeze.py -q`

Expected: all freeze tests pass.

- [ ] **Step 6: Commit the blind corpus before opening it to the selected model**

```bash
git add tests/fixtures/documents/spec009_activation_candidates.json tests/fixtures/documents/spec009_activation_gold.json tests/fixtures/documents/spec009_activation_freeze.json tests/test_spec009_activation_freeze.py
git commit -m "test(spec009): freeze blind activation corpus"
```

### Task 13: Run the blind activation gate and report without auto-enabling MVP

**Files:**
- Generated: `docs/reports/2026-08-17-spec009-activation.md`
- Modify: `src/signals/documents/__init__.py`
- Modify: `README.md`

- [ ] **Step 1: Verify the frozen commit and clean tracked worktree**

Run: `git status --short && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

Expected: no tracked changes, all tests pass, Ruff lint and format pass. Existing
untracked user files may remain untouched and must not enter SPEC-009 commits.

- [ ] **Step 2: Create the target-specific activation manifest**

Run:

```bash
uv run python -m signals.documents.precision_manifest create-run \
  --configuration work/spec009-selected-configuration.json \
  --corpus tests/fixtures/documents/spec009_activation_candidates.json \
  --gold tests/fixtures/documents/spec009_activation_gold.json \
  --out work/spec009-activation-manifest.json
```

Expected: the manifest matches the previously committed freeze hashes and makes
no model call.

- [ ] **Step 3: Run the blind gate once**

```bash
uv run python -m signals.research.spec009_run \
  --corpus tests/fixtures/documents/spec009_activation_candidates.json \
  --gold tests/fixtures/documents/spec009_activation_gold.json \
  --configuration work/spec009-selected-configuration.json \
  --manifest work/spec009-activation-manifest.json \
  --checkpoint work/spec009-activation-checkpoint.json \
  --out work/spec009-activation.json \
  --mode activation \
  --workers 6
```

Expected gate conditions, all cumulative:

- observed precision `> 0.95`;
- 95% Wilson lower bound `>= 0.95`;
- zero false accepts in system confidence `high`;
- evidence coverage `1.0`;
- zero invented excerpts;
- at least 10 consultations represented among auto-accepts.

Exit `2` is a real version failure. Do not change the gold, rerun the completed
answers, or activate the MVP.

- [ ] **Step 4: Generate the activation report from frozen outputs**

Record manifest and fixture hashes, exact command, all global/grouped metrics,
Wilson calculation, false accepts, abstention distribution, API failures,
latency, tokens, cost, and the pass/fail verdict. State explicitly that
FR-DCE-FINAL was regression evidence and this corpus was the activation proof.

- [ ] **Step 5: Export the stable experimental API and update project status**

Export `EligibilityResult`, `eligibility_guard`, `PrecisionDecision`,
`precision_decision`, `PrecisionMetrics`, and gate functions from
`src/signals/documents/__init__.py`. Update README with SPEC-009's measured
verdict. Do not change `AUTO_DOCUMENT_REQUIREMENTS_ENABLED` or
`document_requirement_status()` in this task, even after a pass; activation is a
separate supervisor decision.

- [ ] **Step 6: Run final verification**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

Expected: all tests pass and both Ruff commands are clean.

- [ ] **Step 7: Commit the measured result**

```bash
git add src/signals/documents/__init__.py README.md docs/reports/2026-08-17-spec009-activation.md
git commit -m "docs(spec009): record blind precision gate"
```

After a passing commit, request an explicit supervisor decision before changing
`src/signals/documents/mvp.py`. A failed gate leaves the current safe fallback
untouched.
