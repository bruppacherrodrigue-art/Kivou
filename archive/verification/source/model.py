"""Le contrat de sortie du vérificateur commercial (SPEC-009A §19, §27).

Un vocabulaire entièrement fermé, validé deux fois : par le fournisseur quand il
sait appliquer un JSON Schema strict, puis par Pydantic — ce que le fournisseur
promet n'est jamais ce sur quoi Kivou s'appuie.

Aucune prose libre hors schéma. `commercial_reason` est la seule chaîne libre, et
elle est elle-même contrainte par le validateur déterministe (§21).
"""

from __future__ import annotations

import collections
import dataclasses
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: v0.2 — itération 1 de §30. La v0.1 ne définissait aucun grade : le modèle
#: déduisait `credible` du seul nom de l'énumération et le lisait comme « prouvé »,
#: si bien que 111 besoins sur 149 tombaient en `plausible_but_weak` et que le
#: rappel utile plafonnait à 20 % par construction. Les définitions de la v0.2
#: sont celles de la rubrique qui a produit le gold — aucune règle nouvelle,
#: seulement la fin d'une devinette.
PROMPT_VERSION = "commercial-verifier-prompt-v0.2"
SCHEMA_VERSION = "commercial-verifier-schema-v0.1"
POLICY_VERSION = "commercial-verifier-policy-v0.1"

Verdict = Literal["approve", "downgrade", "reject", "insufficient_context"]
FactualConsistency = Literal["consistent", "uncertain", "contradicted"]
NeedCredibility = Literal["credible", "plausible_but_weak", "unsupported", "contradicted"]
DeliverableOverlap = Literal["none", "suspected", "confirmed"]
WinnerProvidesNeed = Literal["no", "possible", "yes", "unknown"]
IcpFit = Literal["strong", "plausible", "weak", "none"]
Actionability = Literal["actionable", "worth_investigating", "too_weak", "misleading"]
Specificity = Literal["specific", "acceptable", "generic"]
TimingStatus = Literal["current", "unknown", "stale", "ending_soon", "contradictory"]
Confidence = Literal["high", "medium", "low"]

Blocker = Literal[
    "no_exact_need_fit",
    "deliverable_overlap",
    "winner_is_provider",
    "wrong_contract_interpretation",
    "weak_need_support",
    "generic_signal",
    "wrong_actor",
    "geography_mismatch",
    "value_mismatch",
    "stale_award",
    "contract_ending",
    "timing_contradiction",
    "insufficient_facts",
    "unsupported_language",
    "evidence_problem",
]


class CommercialVerification(BaseModel):
    """La réponse structurée du vérificateur — rien d'autre n'est accepté."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Verdict
    factual_consistency: FactualConsistency
    need_credibility: NeedCredibility
    deliverable_overlap: DeliverableOverlap
    winner_already_provides_need: WinnerProvidesNeed
    icp_fit: IcpFit
    actionability: Actionability
    specificity: Specificity
    timing_status: TimingStatus
    blockers: tuple[Blocker, ...] = ()
    supporting_fact_ids: tuple[str, ...] = ()
    limiting_fact_ids: tuple[str, ...] = ()
    confidence: Confidence
    commercial_reason: str = Field(min_length=1, max_length=400)


def _flatten(schema: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    """Résout récursivement les `$ref` : `strict: true` interdit les définitions externes.

    Le schéma transmis au fournisseur n'est pas réécrit à la main : il **est** le
    modèle Pydantic. Un champ qui change ici change là-bas sans intervention, et
    les deux validations restent d'accord.
    """
    if not isinstance(schema, dict):
        return schema

    reference = schema.get("$ref")
    if reference:
        target = definitions.get(reference.rsplit("/", 1)[-1], {})
        merged = {
            **_flatten(target, definitions),
            **{k: v for k, v in schema.items() if k != "$ref"},
        }
        return merged

    resolved: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "allOf" and len(value) == 1:
            resolved.update(_flatten(value[0], definitions))
        elif isinstance(value, dict):
            resolved[key] = _flatten(value, definitions)
        elif isinstance(value, list):
            resolved[key] = [_flatten(item, definitions) for item in value]
        else:
            resolved[key] = value
    return resolved


def verification_response_schema() -> dict[str, Any]:
    """Le JSON Schema strict du contrat, dérivé du modèle Pydantic."""
    raw = CommercialVerification.model_json_schema()
    definitions = raw.pop("$defs", {})
    schema = _flatten(raw, definitions)
    schema["additionalProperties"] = False
    schema["required"] = list(schema.get("properties", {}))
    # `strict: true` n'accepte pas de valeur par défaut : un champ optionnel
    # deviendrait un champ que le modèle peut taire.
    for prop in schema.get("properties", {}).values():
        prop.pop("default", None)
    return schema


@dataclasses.dataclass
class VerifierUsage:
    """Ce que le vérificateur a réellement coûté — jamais une estimation cachée."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    schema_retries: int = 0
    retry_successes: int = 0
    cache_hits: int = 0
    reported_cost_usd: float = 0.0
    failure_kinds: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    latencies_ms: list[float] = dataclasses.field(default_factory=list)

    def record(self, *, input_tokens: int, output_tokens: int, latency_ms: float) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.latencies_ms.append(latency_ms)

    def fail(self, kind: str) -> None:
        """Une panne nommée. Le candidat reste non tranché, pas rejeté au fond (§25)."""
        self.failures += 1
        self.failure_kinds[kind] += 1

    def as_dict(self) -> dict[str, Any]:
        ordered = sorted(self.latencies_ms)

        def quantile(fraction: float) -> float:
            if not ordered:
                return 0.0
            index = min(len(ordered) - 1, int(fraction * len(ordered)))
            return round(ordered[index], 1)

        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "failures": self.failures,
            "schema_retries": self.schema_retries,
            "retry_successes": self.retry_successes,
            "reported_cost_usd": round(self.reported_cost_usd, 6),
            "failure_kinds": dict(self.failure_kinds),
            "latency_ms": {
                "p50": quantile(0.50),
                "p95": quantile(0.95),
                "max": round(ordered[-1], 1) if ordered else 0.0,
            },
        }


@dataclasses.dataclass(frozen=True)
class VerificationRecord:
    """Une vérification et toute sa traçabilité (§27).

    Sans ces champs, un résultat ne serait pas rejouable : on ne saurait pas quel
    modèle, quel prompt ni quelle politique l'ont produit.
    """

    signal_candidate_id: str
    origin_decision: str
    verification: CommercialVerification | None
    validation_errors: tuple[str, ...]
    final_decision: str
    hide_reason: str | None
    model_id: str
    provider: str
    prompt_version: str
    schema_version: str
    policy_version: str
    input_hash: str
    created_at: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    failure_kind: str | None = None
    from_cache: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal_candidate_id": self.signal_candidate_id,
            "origin_decision": self.origin_decision,
            "verification": (
                self.verification.model_dump(mode="json") if self.verification else None
            ),
            "validation_errors": list(self.validation_errors),
            "final_decision": self.final_decision,
            "hide_reason": self.hide_reason,
            "model_id": self.model_id,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "input_hash": self.input_hash,
            "created_at": self.created_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 8),
            "latency_ms": round(self.latency_ms, 1),
            "failure_kind": self.failure_kind,
            "from_cache": self.from_cache,
        }
