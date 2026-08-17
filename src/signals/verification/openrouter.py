"""Adaptateur OpenRouter → DeepSeek Flash (SPEC-009A §6, §8, §25, §26).

Le seul module du projet qui connaisse un fournisseur. Il implémente
`CommercialSignalVerificationModel` et rien d'autre : aucune règle commerciale
ne vit ici, aucune décision de feed n'y est prise.

Sur les secrets : la clé est lue **uniquement** depuis `OPENROUTER_API_KEY`. Elle
n'est jamais écrite dans un log, une exception, une fixture, un rapport ou le
cache. Les messages d'erreur ne citent que le code HTTP et un extrait de corps
tronqué.

Sur le budget de sortie : `max_tokens = 4000` n'est pas un confort. Mesuré sous
SPEC-006, un budget de 400 partait intégralement dans le canal `reasoning` de
DeepSeek Flash — `finish_reason: length`, `content: None`, et des échecs de
schéma attribués à tort au modèle. Le descendre casse silencieusement.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from typing import Any, Self

import httpx

from signals.verification.errors import CredentialMissing, api_failure_kind
from signals.verification.model import (
    CommercialVerification,
    verification_response_schema,
)
from signals.verification.prompt import build_verification_prompt
from signals.verification.protocol import ModelResponse
from signals.verification.view import VerifierInput

COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
MODELS_URL = "https://openrouter.ai/api/v1/models"

#: §6 — le seul modèle approuvé pour SPEC-009A.
APPROVED_MODEL = "deepseek/deepseek-v4-flash"

#: §26 — plancher mesuré, pas un réglage de confort.
MIN_OUTPUT_TOKENS = 4000

#: §8 — le libellé exact à rendre quand la clé manque. Il vit ici parce qu'il
#: nomme la variable d'environnement de CE fournisseur.
CREDENTIALS_REQUIRED_MESSAGE = "LIVE VERIFIER EVAL BLOCKED — OPENROUTER_API_KEY REQUIRED"

SCHEMA_REMINDER = (
    "Ta réponse précédente n'était pas un objet JSON conforme au schéma imposé. "
    "Réponds à nouveau, uniquement par l'objet JSON, sans prose ni bloc de code."
)


def _parse(payload: str) -> CommercialVerification | None:
    """Une réponse hors contrat rend `None` — jamais un objet à moitié rempli."""
    text = (payload or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return CommercialVerification.model_validate(json.loads(text[start : end + 1]))
    except (json.JSONDecodeError, ValueError):
        return None


@dataclasses.dataclass
class OpenRouterCommercialVerifier:
    """Vérificateur commercial via OpenRouter, sans rien changer à la question posée."""

    model_id: str = APPROVED_MODEL
    api_key: str | None = None
    max_tokens: int = MIN_OUTPUT_TOKENS
    timeout: float = 90.0
    provider: str = "openrouter"
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        if self.max_tokens < MIN_OUTPUT_TOKENS:
            raise ValueError(
                f"max_tokens={self.max_tokens} sous le plancher {MIN_OUTPUT_TOKENS} : "
                "les jetons de raisonnement consommeraient le budget avant le JSON"
            )
        key = self.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise CredentialMissing(
                "OPENROUTER_API_KEY absente : aucune clé n'est fabriquée ni codée en dur"
            )
        self.api_key = key

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            # §26 — déterminisme d'abord : on mesure un filtre, pas une créativité.
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "commercial_verification",
                    "strict": True,
                    "schema": verification_response_schema(),
                },
            },
            # Écarte les hébergeurs incapables d'appliquer le schéma strict.
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }

    def verify(self, view: VerifierInput) -> ModelResponse:
        """Une vue, une réponse. Une retentative de schéma, aucune retentative sémantique."""
        prompt = build_verification_prompt(view)
        started = time.monotonic()

        outcome = self._call(prompt)
        retried = False
        if outcome.get("failure") == "schema_failure":
            # §25 — une unique retentative de forme est autorisée : elle ne
            # change pas la question, seulement le rappel du format.
            retried = True
            second = self._call(f"{prompt}\n\n{SCHEMA_REMINDER}")
            second["input_tokens"] += outcome["input_tokens"]
            second["output_tokens"] += outcome["output_tokens"]
            second["cost_usd"] += outcome["cost_usd"]
            outcome = second

        latency_ms = (time.monotonic() - started) * 1000.0
        if outcome.get("failure"):
            return ModelResponse(
                failure_kind=outcome["failure"],
                input_tokens=outcome["input_tokens"],
                output_tokens=outcome["output_tokens"],
                cost_usd=outcome["cost_usd"],
                latency_ms=latency_ms,
                schema_retried=retried,
            )
        return ModelResponse(
            verification=outcome["verification"],
            input_tokens=outcome["input_tokens"],
            output_tokens=outcome["output_tokens"],
            cost_usd=outcome["cost_usd"],
            latency_ms=latency_ms,
            schema_retried=retried,
        )

    def _call(self, prompt: str) -> dict[str, Any]:
        empty: dict[str, Any] = {
            "verification": None,
            "failure": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        }
        try:
            response = self.client.post(
                COMPLETIONS_URL,
                json=self._payload(prompt),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException:
            return {**empty, "failure": "transport_failure"}
        except httpx.HTTPError:
            return {**empty, "failure": "transport_failure"}

        if response.status_code != 200:
            return {**empty, "failure": api_failure_kind(response.status_code)}

        body = response.json()
        usage = body.get("usage") or {}
        measured = {
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
            "cost_usd": float(usage.get("cost") or 0.0),
        }

        choices = body.get("choices") or []
        if not choices:
            return {**empty, **measured, "failure": "provider_failure"}
        text = (choices[0].get("message") or {}).get("content") or ""
        verification = _parse(text)
        if verification is None:
            return {**empty, **measured, "failure": "schema_failure"}
        return {**empty, **measured, "verification": verification}


def check_model_available(
    model_id: str = APPROVED_MODEL, *, timeout: float = 30.0
) -> dict[str, Any]:
    """Confirme que le modèle approuvé existe au catalogue, et rend son tarif (§6)."""
    with httpx.Client(timeout=timeout) as client:
        response = client.get(MODELS_URL)
        response.raise_for_status()
        for entry in response.json()["data"]:
            if entry["id"] == model_id:
                pricing = entry.get("pricing") or {}
                return {
                    "available": True,
                    "model_id": model_id,
                    "prompt_usd_per_token": float(pricing.get("prompt", 0.0)),
                    "completion_usd_per_token": float(pricing.get("completion", 0.0)),
                    "context_length": entry.get("context_length"),
                }
    return {"available": False, "model_id": model_id}


def check_credits(api_key: str | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    """Le solde disponible, à vérifier AVANT chaque course live (§9).

    Ne renvoie jamais la clé, et n'en fabrique aucune.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise CredentialMissing("OPENROUTER_API_KEY absente")
    with httpx.Client(timeout=timeout) as client:
        response = client.get(CREDITS_URL, headers={"Authorization": f"Bearer {key}"})
        if response.status_code != 200:
            return {
                "reachable": False,
                "status_code": response.status_code,
                "failure": api_failure_kind(response.status_code),
            }
        data = response.json().get("data") or {}
        total = float(data.get("total_credits", 0.0))
        used = float(data.get("total_usage", 0.0))
        return {
            "reachable": True,
            "total_credits_usd": total,
            "total_usage_usd": used,
            "remaining_usd": round(total - used, 4),
        }


# ─── Point de composition (SPEC-009A §7) ────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """La CLI des deux commandes qui touchent au réseau.

    Elle vit ici et nulle part ailleurs : c'est le seul endroit du projet qui
    sache quel fournisseur est branché. Le harnais de recherche reçoit le modèle
    et les sondes en paramètres, ce qui lui permet d'ignorer jusqu'au nom de
    DeepSeek — et à la suite de tests de tourner sans clé ni réseau.
    """
    import argparse
    import json
    import pathlib
    import sys

    from signals.research.verifier_dev import build_dev_candidates, preflight, run_dev

    parser = argparse.ArgumentParser(
        description="Vérificateur commercial — commandes réseau (SPEC-009A)"
    )
    parser.add_argument("command", choices=("preflight", "run"))
    parser.add_argument("--max-workers", type=int, default=6)
    parser.add_argument("--cache", default=None)
    args = parser.parse_args(argv)

    if args.command == "preflight":
        candidates, _ = build_dev_candidates()
        report = preflight(
            candidates=len(candidates),
            approved_model=APPROVED_MODEL,
            model_check=check_model_available,
            credits_check=check_credits,
            credentials_required_message=CREDENTIALS_REQUIRED_MESSAGE,
        )
        print(json.dumps(report, ensure_ascii=False, indent=1))
        if report.get("blocked"):
            print(report["blocked"], file=sys.stderr)
            return 2
        return 0

    with OpenRouterCommercialVerifier() as model:
        report = run_dev(
            model=model,
            max_workers=args.max_workers,
            cache_path=pathlib.Path(args.cache) if args.cache else None,
        )
    print(json.dumps(report["headline"], ensure_ascii=False, indent=1))
    print(json.dumps(report["gates"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
