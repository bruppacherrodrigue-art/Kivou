"""Le seul endroit du dépôt qui parle à un fournisseur de modèles.

Le domaine ne connaît que `RequirementClassifier` : un protocole, cinq champs de
sortie, aucune marque. Ce module fournit **un** adaptateur concret, nécessaire au
smoke réel, et rien de plus. En changer revient à écrire une autre classe, pas à
toucher au moteur.

Trois règles tenues ici :

- **aucune clé en dur, aucun compte créé** : la clé vient de l'environnement, et
  son absence est un état lisible (`CredentialMissing`), pas une exception nue ;
- **aucune tolérance de sortie** : une réponse hors contrat vaut « pas de
  classification » — le candidat est rejeté, jamais deviné ;
- **le texte du document n'est jamais une consigne** : le prompt est assemblé
  par `build_classification_prompt`, clôture `UNTRUSTED SOURCE TEXT` comprise.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from signals.documents.classification import (
    SCHEMA_REMINDER,
    CandidateContext,
    LlmUsage,
    SemanticClassification,
    api_failure_kind,
    build_classification_prompt,
    parse_classification,
)
from signals.personalization.for_you import ForYouInput, ForYouProvider


class CredentialMissing(RuntimeError):
    """Aucune credential configurée. On ne devine pas, on ne crée pas de compte."""


# Tarifs publics au 16 août 2026, en dollars par million de jetons. Ils ne sont
# qu'un paramètre : le coût rapporté est calculé, jamais estimé au doigt mouillé.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
}


def _price_of(model: str) -> tuple[float, float]:
    """Le tarif d'un modèle, alias daté ou non.

    Un tarif inconnu vaut zéro **et se voit** : un coût nul dans un rapport est
    un chiffre faux, pas une bonne nouvelle.
    """
    if model in DEFAULT_PRICES:
        return DEFAULT_PRICES[model]
    for known, prices in DEFAULT_PRICES.items():
        if model.startswith(known):
            return prices
    return (0.0, 0.0)


# Certains modèles refusent `temperature` (400 « deprecated for this model »).
# C'est un paramètre de transport : l'omettre ne change ni le prompt, ni le
# schéma, ni la question posée.
MODELS_WITHOUT_TEMPERATURE: tuple[str, ...] = ("claude-sonnet-5",)

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


@dataclass
class AnthropicClassifier:
    """Adaptateur HTTP minimal — pas de SDK, pas de dépendance supplémentaire.

    Le modèle par défaut est le plus petit qui fasse le travail : la tâche est un
    étiquetage à cinq champs sur une phrase et son voisinage, pas une rédaction.
    """

    model: str = "claude-haiku-4-5-20251001"
    api_key: str | None = None
    max_tokens: int = 300
    timeout: float = 30.0
    name: str = "anthropic"
    version: str = field(default="")
    usage: LlmUsage = field(default_factory=LlmUsage)
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        self.version = self.model
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise CredentialMissing(
                "ANTHROPIC_API_KEY absente : aucune clé n'est fabriquée ni codée en dur"
            )
        self.api_key = key
        prices = _price_of(self.model)
        self.usage.price_input_per_mtok = prices[0]
        self.usage.price_output_per_mtok = prices[1]

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
        """Un appel, et une seule retentative si la sortie n'est pas au schéma.

        La retentative n'est pas un parseur indulgent : elle redemande la même
        chose au modèle en lui rappelant les clés obligatoires, et la seconde
        réponse passe la même validation Pydantic. Deux échecs = panne.
        """
        prompt = build_classification_prompt(context)
        classification, failure = self._ask(prompt)
        if classification is not None:
            return classification
        # Une panne de transport ne se corrige pas en redemandant la même chose :
        # seule une sortie hors schéma mérite la retentative (SPEC-006R3 §10).
        if failure != "schema_failure":
            return None

        self.usage.retries += 1
        retried, _ = self._ask(f"{prompt}\n\n{SCHEMA_REMINDER}")
        if retried is not None:
            self.usage.retry_successes += 1
        return retried

    def _ask(self, prompt: str) -> tuple[SemanticClassification | None, str | None]:
        text, failure = self._request_text(prompt)
        if text is None:
            return None, failure
        classification = parse_classification(text)
        if classification is None:
            self.usage.fail("schema_failure")
            return None, "schema_failure"
        return classification, None

    def _request_text(self, prompt: str) -> tuple[str | None, str | None]:
        payload: dict[str, object] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if not self.model.startswith(MODELS_WITHOUT_TEMPERATURE):
            # Température nulle : la même phrase doit produire le même verdict.
            payload["temperature"] = 0
        try:
            response = self.client.post(
                MESSAGES_URL,
                json=payload,
                headers={
                    "x-api-key": self.api_key or "",
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
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
            input_tokens=int(tokens.get("input_tokens", 0)),
            output_tokens=int(tokens.get("output_tokens", 0)),
        )

        blocks = body.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        return text.strip(), None


@dataclass
class AnthropicTextGenerator(AnthropicClassifier):
    """Même transport et même modèle, avec un contrat de phrase unique."""

    max_tokens: int = 100

    def generate_sentence(self, value: ForYouInput) -> str | None:
        prompt = (
            "Rédige une seule phrase en français, 25 mots maximum, sans point "
            "d'exclamation ni superlatif. N'ajoute aucun fait.\n\n"
            "BEGIN UNTRUSTED VERIFIED INPUT\n"
            f"{value.model_dump_json()}\n"
            "END UNTRUSTED VERIFIED INPUT"
        )
        text, _ = self._request_text(prompt)
        return text


def text_generator_from_environment() -> ForYouProvider:
    """Construit l'adaptateur configuré sans exposer sa marque aux appelants."""
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        from signals.documents.openrouter import OpenRouterTextGenerator

        model = os.environ.get("KIVOU_FOR_YOU_MODEL", "anthropic/claude-sonnet-4.6")
        return OpenRouterTextGenerator(model=model)
    return AnthropicTextGenerator()
