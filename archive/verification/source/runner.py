"""L'orchestration d'une passe de vérification (SPEC-009A §12, §23–§27).

Une seule responsabilité : faire passer des candidats déterministes par la
chaîne `vue → modèle → validation → politique`, en conservant tout ce qu'il faut
pour rejouer et facturer. Aucune règle commerciale n'est décidée ici ; elles
vivent dans `validation.py` et `policy.py`.

Trois garde-fous opérationnels :

* **La langue est vérifiée avant l'appel** — un candidat non représentable ne
  coûte rien (§16).
* **Le cache est consulté avant l'appel** — on ne repaie jamais une vérification
  identique (§11).
* **Le budget est un plafond dur** — la course s'arrête d'elle-même, elle ne
  déborde pas (§9).
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime as dt
from collections.abc import Sequence
from typing import Any

from signals.verification.cache import VerificationCache, cache_key, icp_hash
from signals.verification.model import (
    POLICY_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    VerificationRecord,
    VerifierUsage,
)
from signals.verification.policy import HIDE, apply_final_policy
from signals.verification.protocol import CommercialSignalVerificationModel
from signals.verification.validation import ValidationOutcome, validate_verification
from signals.verification.view import VerifierInput, build_verifier_input

#: §26 — concurrence live maximale.
MAX_WORKERS = 6

#: Fréquence de vidage du cache pendant une course. §10 exige de pouvoir
#: redémarrer après une interruption : un cache écrit seulement en fin de course
#: ferait repayer l'intégralité d'une course coupée.
CACHE_FLUSH_EVERY = 20


class BudgetExhausted(RuntimeError):
    """Le plafond de dépense est atteint. On s'arrête, on n'augmente pas (§9)."""


@dataclasses.dataclass
class Candidate:
    """Un candidat déterministe soumis au vérificateur (§12)."""

    blind: dict[str, Any]
    origin_decision: str

    def __post_init__(self) -> None:
        if self.origin_decision not in ("show", "borderline"):
            raise ValueError(
                f"origin_decision={self.origin_decision!r} : seuls `show` et `borderline` "
                "entrent dans le vérificateur en V0 (§12)"
            )


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _hidden(
    view: VerifierInput,
    candidate: Candidate,
    model: CommercialSignalVerificationModel,
    *,
    reason: str,
    failure_kind: str | None = None,
    validation_errors: tuple[str, ...] = (),
    **measured: Any,
) -> VerificationRecord:
    return VerificationRecord(
        signal_candidate_id=view.signal_candidate_id,
        origin_decision=candidate.origin_decision,
        verification=None,
        validation_errors=validation_errors,
        final_decision=HIDE,
        hide_reason=reason,
        model_id=model.model_id,
        provider=model.provider,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        input_hash=view.snapshot_hash(),
        created_at=_now(),
        failure_kind=failure_kind,
        **measured,
    )


def verify_candidate(
    candidate: Candidate,
    model: CommercialSignalVerificationModel,
    *,
    cache: VerificationCache | None = None,
    usage: VerifierUsage | None = None,
) -> VerificationRecord:
    """La chaîne complète pour un candidat, panne comprise."""
    view = build_verifier_input(candidate.blind)
    usage = usage if usage is not None else VerifierUsage()

    # §16 — une vue non représentable n'est pas envoyée : elle ne coûte rien.
    if not view.language_supported:
        return _hidden(view, candidate, model, reason="unsupported_language")

    key = cache_key(
        snapshot_hash=view.snapshot_hash(),
        icp_hash=icp_hash(view.target_icp),
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        model_id=model.model_id,
    )
    cached = cache.get(key) if cache is not None else None
    if cached is not None:
        usage.cache_hits += 1
        validation = validate_verification(cached, view)
        decision = apply_final_policy(cached, view, validation)
        return VerificationRecord(
            signal_candidate_id=view.signal_candidate_id,
            origin_decision=candidate.origin_decision,
            verification=cached,
            validation_errors=validation.errors,
            final_decision=decision.decision,
            hide_reason=decision.reason,
            model_id=model.model_id,
            provider=model.provider,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            policy_version=POLICY_VERSION,
            input_hash=view.snapshot_hash(),
            created_at=_now(),
            from_cache=True,
        )

    response = model.verify(view)
    measured = {
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_usd": response.cost_usd,
        "latency_ms": response.latency_ms,
    }
    if response.schema_retried:
        usage.schema_retries += 1
    usage.reported_cost_usd += response.cost_usd

    if response.failure_kind is not None:
        # §25 — une panne n'est jamais « le signal est mauvais ».
        usage.fail(response.failure_kind)
        return _hidden(
            view,
            candidate,
            model,
            reason=response.failure_kind,
            failure_kind=response.failure_kind,
            **measured,
        )

    usage.record(
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_ms=response.latency_ms,
    )
    if response.schema_retried:
        usage.retry_successes += 1

    verification = response.verification
    assert verification is not None  # garanti par ModelResponse.__post_init__
    validation: ValidationOutcome = validate_verification(verification, view)
    if not validation.valid:
        usage.fail("validation_failure")
    if cache is not None and validation.valid:
        cache.put(key, verification)

    decision = apply_final_policy(verification, view, validation)
    return VerificationRecord(
        signal_candidate_id=view.signal_candidate_id,
        origin_decision=candidate.origin_decision,
        verification=verification,
        validation_errors=validation.errors,
        final_decision=decision.decision,
        hide_reason=decision.reason,
        model_id=model.model_id,
        provider=model.provider,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        input_hash=view.snapshot_hash(),
        created_at=_now(),
        failure_kind="validation_failure" if not validation.valid else None,
        **measured,
    )


def verify_all(
    candidates: Sequence[Candidate],
    model: CommercialSignalVerificationModel,
    *,
    cache: VerificationCache | None = None,
    max_workers: int = MAX_WORKERS,
    budget_usd: float | None = None,
) -> tuple[list[VerificationRecord], VerifierUsage]:
    """Vérifie tous les candidats, dans l'ordre d'entrée, sans dépasser le budget.

    L'ordre de sortie suit l'ordre d'entrée quelle que soit la concurrence : un
    banc dont la composition dépendrait de l'ordonnancement des threads ne serait
    pas rejouable.
    """
    usage = VerifierUsage()
    records: list[VerificationRecord | None] = [None] * len(candidates)

    if max_workers <= 1:
        for index, candidate in enumerate(candidates):
            if budget_usd is not None and usage.reported_cost_usd >= budget_usd:
                raise BudgetExhausted(
                    f"STOP — SPEC-009A COST BUDGET EXHAUSTED "
                    f"({usage.reported_cost_usd:.4f} USD >= {budget_usd:.2f} USD)"
                )
            records[index] = verify_candidate(candidate, model, cache=cache, usage=usage)
            if cache is not None and (index + 1) % CACHE_FLUSH_EVERY == 0:
                cache.flush()
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(verify_candidate, candidate, model, cache=cache, usage=usage): index
                for index, candidate in enumerate(candidates)
            }
            for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                records[futures[future]] = future.result()
                if cache is not None and done % CACHE_FLUSH_EVERY == 0:
                    cache.flush()

    if cache is not None:
        cache.flush()
        usage.cache_hits = cache.hits
    return [record for record in records if record is not None], usage
