"""Adaptateur OpenRouter — un fournisseur de plus derrière la même interface.

Le domaine ne connaît que `RequirementClassifier`. Ce module ajoute un second
adaptateur concret, à côté de celui d'Anthropic, sans qu'aucune règle métier ne
change : même prompt, même schéma, même politique d'acceptation, même validateur
d'extrait déterministe.

Deux différences avec l'adaptateur Anthropic, toutes deux à l'avantage du
contrat :

- le **schéma JSON est transmis au fournisseur** (`response_format.json_schema`,
  `strict: true`), et `provider.require_parameters` écarte les hébergeurs qui ne
  savent pas l'appliquer — la sortie hors contrat devient rare au lieu d'être
  rattrapée après coup ;
- le coût réel de l'appel est renvoyé par l'API, il n'a donc pas à être estimé.

Le schéma reste **validé une seconde fois par Pydantic** : ce que le fournisseur
promet n'est jamais ce sur quoi Kivou s'appuie.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import httpx

from signals.documents.adversarial import (
    AdversarialResponse,
    adversarial_response_schema,
    build_adversarial_prompt,
    parse_adversarial,
)
from signals.documents.classification import (
    SCHEMA_REMINDER,
    CandidateContext,
    LlmUsage,
    SemanticClassification,
    api_failure_kind,
    build_classification_prompt,
    parse_classification,
)
from signals.documents.consensus import (
    VerifierResponse,
    build_verifier_prompt,
    verifier_response_schema,
)
from signals.documents.intelligence import RequirementCandidate
from signals.documents.snapshot import CandidateSnapshot
from signals.personalization.for_you import ForYouInput

COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


class CredentialMissing(RuntimeError):
    """Aucune credential configurée. On ne devine pas, on ne crée pas de compte."""


def response_schema() -> dict[str, object]:
    """Le schéma exact du contrat sémantique, dérivé du modèle Pydantic.

    Il n'est pas réécrit à la main : il **est** le modèle. Un champ qui changerait
    dans le contrat changerait ici sans intervention, et les deux validations
    resteraient d'accord.
    """
    schema = SemanticClassification.model_json_schema()
    schema["additionalProperties"] = False
    # `strict: true` exige que chaque propriété soit requise et sans définition
    # externe : on aplatit les énumérations que Pydantic sort en `$defs`.
    definitions = schema.pop("$defs", {})
    for name, prop in schema.get("properties", {}).items():
        reference = prop.pop("$ref", None) or (prop.pop("allOf", [{}])[0].get("$ref"))
        if reference:
            target = definitions.get(reference.rsplit("/", 1)[-1], {})
            schema["properties"][name] = {**target, **prop}
    schema["required"] = list(schema.get("properties", {}))
    return schema


MIN_REASONING_TOKENS = 4000
"""Le plancher du budget de sortie, mesuré et non deviné.

Le premier run SPEC-006R4 tournait à 400 — le défaut historique, calibré sur des
modèles sans raisonnement visible. Chez DeepSeek-v4-flash et GLM-4.7-flash, ces
400 jetons partaient **intégralement** dans le canal `reasoning` :
`finish_reason: length`, `content: None`, et 73 à 100 % d'échecs de schéma
attribués à tort aux modèles. Relevé à 4000, les mêmes modèles passent à zéro
échec — DeepSeek consomme 1233 jetons de sortie sur un candidat typique, GLM 2663.
Ce plancher est un contrat de transport : le descendre casse silencieusement tout
modèle à raisonnement.
"""


@dataclass
class OpenRouterClassifier:
    """Classe un candidat via OpenRouter, sans rien changer à la question posée."""

    model: str
    api_key: str | None = None
    max_tokens: int = MIN_REASONING_TOKENS
    timeout: float = 60.0
    name: str = "openrouter"
    version: str = field(default="")
    usage: LlmUsage = field(default_factory=LlmUsage)
    # OpenRouter renvoie le coût réel de chaque appel : on l'additionne au lieu
    # de le recalculer depuis une grille de prix qui pourrait être périmée.
    reported_cost_usd: float = 0.0
    # La nature de la dernière panne — `None` après un succès. SPEC-006R5 §32 :
    # c'est ce qui permet à un harnais de ne pas compter une panne API comme si
    # le modèle avait répondu.
    last_failure: str | None = None
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        self.version = self.model
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

    def classify(self, context: CandidateContext) -> SemanticClassification | None:
        prompt = build_classification_prompt(context)
        classification, failure = self._ask(prompt)
        if classification is not None:
            self.last_failure = None
            return classification
        if failure != "schema_failure":
            # Panne API : retenter la même requête sur un compte épuisé ou un
            # fournisseur muet ne produit que la même panne, en double.
            self.last_failure = failure
            return None

        self.usage.retries += 1
        retried, retry_failure = self._ask(f"{prompt}\n\n{SCHEMA_REMINDER}")
        if retried is not None:
            self.usage.retry_successes += 1
        self.last_failure = None if retried is not None else retry_failure
        return retried

    def _ask(self, prompt: str) -> tuple[SemanticClassification | None, str | None]:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "semantic_classification",
                    "strict": True,
                    "schema": response_schema(),
                },
            },
            # Écarte les hébergeurs incapables d'appliquer le schéma demandé.
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }
        try:
            response = self.client.post(
                COMPLETIONS_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException:
            self.usage.fail("transport_failure")
            return None, "transport_failure"
        except httpx.HTTPError:
            self.usage.fail("transport_failure")
            return None, "transport_failure"

        if response.status_code != 200:
            kind = api_failure_kind(response.status_code)
            self.usage.fail(kind)
            return None, kind

        body = response.json()
        tokens = body.get("usage") or {}
        self.usage.record(
            input_tokens=int(tokens.get("prompt_tokens", 0)),
            output_tokens=int(tokens.get("completion_tokens", 0)),
        )
        if tokens.get("cost") is not None:
            self.reported_cost_usd += float(tokens["cost"])

        choices = body.get("choices") or []
        if not choices:
            # Aucun contenu produit : le modèle n'a pas « raté le schéma »,
            # le fournisseur n'a rien livré.
            self.usage.fail("provider_failure")
            return None, "provider_failure"
        text = (choices[0].get("message") or {}).get("content") or ""

        # Aucun repli en texte libre : le schéma Pydantic tranche une seconde fois.
        classification = parse_classification(text)
        if classification is None:
            self.usage.fail("schema_failure")
            return None, "schema_failure"
        return classification, None

    def as_dict(self) -> dict[str, object]:
        data = self.usage.as_dict()
        data["reported_cost_usd"] = round(self.reported_cost_usd, 6)
        data["model"] = self.model
        return data


@dataclass
class OpenRouterTextGenerator(OpenRouterClassifier):
    """Rédige la phrase personnalisée via le même transport OpenRouter."""

    max_tokens: int = 100

    def generate_sentence(self, value: ForYouInput) -> str | None:
        prompt = (
            "Rédige une seule phrase en français, 25 mots maximum, sans point "
            "d'exclamation ni superlatif. N'ajoute aucun fait.\n\n"
            "BEGIN UNTRUSTED VERIFIED INPUT\n"
            f"{value.model_dump_json()}\n"
            "END UNTRUSTED VERIFIED INPUT"
        )
        try:
            response = self.client.post(
                COMPLETIONS_URL,
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                    "usage": {"include": True},
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError:
            self.usage.fail("transport_failure")
            return None
        if response.status_code != 200:
            self.usage.fail(api_failure_kind(response.status_code))
            return None
        body = response.json()
        tokens = body.get("usage") or {}
        self.usage.record(
            input_tokens=int(tokens.get("prompt_tokens", 0)),
            output_tokens=int(tokens.get("completion_tokens", 0)),
        )
        if tokens.get("cost") is not None:
            self.reported_cost_usd += float(tokens["cost"])
        choices = body.get("choices") or []
        if not choices:
            self.usage.fail("provider_failure")
            return None
        return ((choices[0].get("message") or {}).get("content") or "").strip() or None


# ─── Vérificateur ───────────────────────────────────────────────────────────────


@dataclass
class OpenRouterVerifier:
    """Le second avis, via le même transport et le même durcissement.

    Il ne partage rien avec le primaire sinon l'adaptateur : ni prompt, ni schéma,
    ni compteur d'usage. Deux modèles qui se relisent doivent pouvoir être
    facturés et diagnostiqués séparément.
    """

    model: str
    api_key: str | None = None
    max_tokens: int = MIN_REASONING_TOKENS
    timeout: float = 60.0
    name: str = "openrouter-verifier"
    version: str = field(default="")
    usage: LlmUsage = field(default_factory=LlmUsage)
    reported_cost_usd: float = 0.0
    last_failure: str | None = None
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        if self.max_tokens < MIN_REASONING_TOKENS:
            raise ValueError(
                f"max_tokens={self.max_tokens} sous le plancher {MIN_REASONING_TOKENS} : "
                "les jetons de raisonnement consommeraient le budget avant le JSON"
            )
        self.version = self.model
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

    def verify(self, snapshot: CandidateSnapshot) -> VerifierResponse | None:
        """Une question, une réponse. Une panne rend `None`, jamais un rejet."""
        prompt = build_verifier_prompt(snapshot)
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "verifier_response",
                    "strict": True,
                    "schema": verifier_response_schema(),
                },
            },
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }
        try:
            response = self.client.post(
                COMPLETIONS_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException:
            self.usage.fail("transport_failure")
            self.last_failure = "transport_failure"
            return None
        except httpx.HTTPError:
            self.usage.fail("transport_failure")
            self.last_failure = "transport_failure"
            return None

        if response.status_code != 200:
            kind = api_failure_kind(response.status_code)
            self.usage.fail(kind)
            self.last_failure = kind
            return None

        body = response.json()
        tokens = body.get("usage") or {}
        self.usage.record(
            input_tokens=int(tokens.get("prompt_tokens", 0)),
            output_tokens=int(tokens.get("completion_tokens", 0)),
        )
        if tokens.get("cost") is not None:
            self.reported_cost_usd += float(tokens["cost"])

        choices = body.get("choices") or []
        if not choices:
            self.usage.fail("provider_failure")
            self.last_failure = "provider_failure"
            return None
        text = (choices[0].get("message") or {}).get("content") or ""
        answer = _parse_verifier(text)
        if answer is None:
            self.usage.fail("schema_failure")
            self.last_failure = "schema_failure"
        else:
            self.last_failure = None
        return answer

    def as_dict(self) -> dict[str, object]:
        data = self.usage.as_dict()
        data["reported_cost_usd"] = round(self.reported_cost_usd, 6)
        data["model"] = self.model
        return data


def _parse_verifier(payload: str) -> VerifierResponse | None:
    """Lit la réponse. Hors contrat vaut « pas de réponse » — aucune réparation."""
    text = payload.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return VerifierResponse(**json.loads(text[start : end + 1]))
    except Exception:  # noqa: BLE001 — sortie non conforme = pas de réponse
        return None


# ─── Contradicteur R5 ───────────────────────────────────────────────────────────


@dataclass
class OpenRouterAdversarialVerifier:
    """Le contradicteur SPEC-006R5, via le même transport et le même durcissement.

    Il ne partage rien avec le primaire sinon l'adaptateur : ni prompt, ni
    schéma, ni compteur d'usage — et surtout pas la décision du primaire (§15).
    """

    model: str
    api_key: str | None = None
    max_tokens: int = MIN_REASONING_TOKENS
    timeout: float = 60.0
    name: str = "openrouter-adversarial"
    version: str = field(default="")
    usage: LlmUsage = field(default_factory=LlmUsage)
    reported_cost_usd: float = 0.0
    last_failure: str | None = None
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        if self.max_tokens < MIN_REASONING_TOKENS:
            raise ValueError(
                f"max_tokens={self.max_tokens} sous le plancher {MIN_REASONING_TOKENS} : "
                "les jetons de raisonnement consommeraient le budget avant le JSON"
            )
        self.version = self.model
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

    def verify(self, snapshot: CandidateSnapshot) -> AdversarialResponse | None:
        """Une question, une réponse. Une panne rend `None`, jamais un verdict."""
        prompt = build_adversarial_prompt(snapshot)
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "adversarial_response",
                    "strict": True,
                    "schema": adversarial_response_schema(),
                },
            },
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }
        try:
            response = self.client.post(
                COMPLETIONS_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException:
            self.usage.fail("transport_failure")
            self.last_failure = "transport_failure"
            return None
        except httpx.HTTPError:
            self.usage.fail("transport_failure")
            self.last_failure = "transport_failure"
            return None

        if response.status_code != 200:
            kind = api_failure_kind(response.status_code)
            self.usage.fail(kind)
            self.last_failure = kind
            return None

        body = response.json()
        tokens = body.get("usage") or {}
        self.usage.record(
            input_tokens=int(tokens.get("prompt_tokens", 0)),
            output_tokens=int(tokens.get("completion_tokens", 0)),
        )
        if tokens.get("cost") is not None:
            self.reported_cost_usd += float(tokens["cost"])

        choices = body.get("choices") or []
        if not choices:
            self.usage.fail("provider_failure")
            self.last_failure = "provider_failure"
            return None
        text = (choices[0].get("message") or {}).get("content") or ""
        answer = parse_adversarial(text)
        if answer is None:
            self.usage.fail("schema_failure")
            self.last_failure = "schema_failure"
        else:
            self.last_failure = None
        return answer

    def as_dict(self) -> dict[str, object]:
        data = self.usage.as_dict()
        data["reported_cost_usd"] = round(self.reported_cost_usd, 6)
        data["model"] = self.model
        return data


@dataclass
class SnapshotClassifierAdapter:
    """Fait voir à un classifieur existant le voisinage figé d'un snapshot.

    Le classifieur parle `CandidateContext`, le corpus d'évaluation parle
    `CandidateSnapshot`. Cet adaptateur les réconcilie sans toucher ni au prompt
    ni au schéma : c'est ce qui permet de mesurer le pipeline sur un corpus figé
    avec exactement le code de production.
    """

    inner: OpenRouterClassifier
    name: str = "openrouter"
    version: str = field(default="")

    def __post_init__(self) -> None:
        self.version = self.inner.model

    def classify_snapshot(self, snapshot: CandidateSnapshot) -> SemanticClassification | None:
        candidate = RequirementCandidate(
            requirement_type="other",
            modality="mandatory",
            statement=snapshot.excerpt,
            source_excerpt=snapshot.excerpt,
            source_locator=snapshot.source_locator,
        )
        context = CandidateContext(
            candidate=candidate,
            current_text=snapshot.logical_span or snapshot.current_block,
            heading=snapshot.heading,
            previous_text=snapshot.previous_block,
            next_text=snapshot.next_block,
            document_name=snapshot.document_name,
            locator=snapshot.source_locator,
        )
        return self.inner.classify(context)
