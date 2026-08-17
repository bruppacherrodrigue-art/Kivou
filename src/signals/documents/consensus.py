"""Deux modèles, trois états — ce qu'un accord vaut, et ce qu'un désaccord ne vaut pas.

SPEC-006R3 a mesuré un classifieur seul sur DEV-3 : 84,6 % de précision et deux
fausses acceptations en haute confiance. Le même corpus, relu par un second
modèle qui ne répond qu'à *une* question, donne 94,7 % et **zéro** fausse
acceptation en haute confiance. Le gain ne vient pas d'un modèle plus fort : il
vient de ce qu'un désaccord cesse d'être tranché.

    candidat ──▶ PRIMAIRE (que dit la phrase ?)
                     │ accepte
                     ▼
                 VÉRIFICATEUR (une seule question, fermée)
                     │
                     ▼
             POLITIQUE déterministe ──▶ auto_accepted
                                        review_required
                                        rejected

Trois règles portent tout le reste :

- le vérificateur n'est appelé que si le primaire acceptait — il coûte donc le
  prix d'une minorité des candidats, pas de tous ;
- un désaccord ne produit **jamais** `rejected` : il produit `review_required`,
  avec le motif conservé. Rejeter sur désaccord reviendrait à laisser le second
  modèle réfuter le premier, alors qu'il ne fait que douter ;
- une panne — schéma invalide, fournisseur muet — n'est pas un verdict. Elle
  vaut `review_required/technical_failure`, jamais « ce n'était pas une exigence ».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from signals.documents.classification import (
    SemanticClassification,
    decide,
    normalize_for_match,
)
from signals.documents.requirements import Confidence
from signals.domain.values import CanonicalModel, NonEmptyStr

CONSENSUS_POLICY_VERSION = "consensus-two-model-v0.4"
"""Version de la politique à deux modèles.

v0.4 est la première : elle ajoute le vérificateur et le troisième état. Les
mesures faites sous le contrat sémantique seul (v0.1 à v0.3) ne s'y comparent
pas — elles n'avaient que deux issues.
"""

# ─── Contrat du vérificateur ────────────────────────────────────────────────────

VerifierVerdict = Literal["confirm", "reject", "uncertain"]
"""Le vérificateur confirme, réfute, ou dit qu'il ne sait pas.

`uncertain` n'est pas une politesse : c'est le seul moyen pour lui de ne pas
inventer une certitude, et la politique le traite exactement comme un désaccord.
"""

VerifierReason = Literal[
    "execution_contractor",
    "procurement",
    "qualification",
    "contract_formation",
    "buyer_obligation",
    "bidder_obligation",
    "third_party",
    "background",
    "fragment",
    "insufficient_context",
    "other",
]
"""Pourquoi. `execution_contractor` est le seul motif qui autorise l'acceptation ;
tous les autres nomment ce que la phrase est **à la place**, et ce motif survit
dans les diagnostics."""

VERIFIER_QUESTION = (
    "Le passage cité établit-il explicitement une obligation, une interdiction ou "
    "une option portant sur l'exécution effective du contrat par le titulaire ?"
)
"""La question unique. Le vérificateur ne reclasse pas le document et ne réécrit
aucune exigence : il répond à celle-ci, sur un passage déjà extrait."""

VERIFIER_INSTRUCTIONS = f"""\
Tu vérifies UNE phrase déjà extraite d'un document de marché public.

{VERIFIER_QUESTION}

Réponds `confirm` uniquement si les trois conditions tiennent ensemble :
- la phrase porte sur l'EXÉCUTION du marché, une fois celui-ci attribué ;
- l'obligation pèse sur le TITULAIRE, et non sur l'acheteur, le soumissionnaire
  ou un tiers ;
- le passage cité suffit à l'établir, sans supposer un contexte absent.

Réponds `reject` si la phrase relève d'autre chose, et nomme quoi : dépôt d'offre
(`procurement`), admission (`qualification`), formalités entre l'attribution et
l'entrée en vigueur (`contract_formation`), devoir de l'acheteur
(`buyer_obligation`), du soumissionnaire (`bidder_obligation`), d'un tiers
(`third_party`), contexte ou définition (`background`).

Réponds `uncertain` si la phrase est tronquée (`fragment`) ou si le contexte
manque pour trancher (`insufficient_context`). Ne devine pas.

Frontière offre / exécution — le prix et les données à INSCRIRE dans l'offre, les
fiches à JOINDRE, les formulaires à REMPLIR relèvent de `procurement`, même
rédigés avec « doit ». Une limite sonore à respecter pendant la prestation, un
coût de maintenance supporté pendant le contrat, un rapport remis durant
l'exécution, une assurance maintenue pendant la durée du marché relèvent de
l'exécution.

`source_excerpt` doit reprendre le passage cité TEL QUEL. Ne le reformule pas,
ne le complète pas, ne le raccourcis pas."""


def build_verifier_prompt(snapshot: object) -> str:
    """Le prompt du vérificateur : consignes hors de la clôture, document dedans.

    Même protection que le classifieur — le texte du dossier est encadré et
    déclaré non fiable, de sorte qu'une injection y soit au pire classée, jamais
    suivie.
    """
    from signals.documents.classification import UNTRUSTED_PROMPT_HEADER

    parts: list[str] = []
    for label, value in (
        ("SECTION", getattr(snapshot, "heading", None)),
        ("BLOC PRÉCÉDENT", getattr(snapshot, "previous_block", None)),
        (
            "BLOC COURANT",
            getattr(snapshot, "logical_span", None) or getattr(snapshot, "current_block", None),
        ),
        ("BLOC SUIVANT", getattr(snapshot, "next_block", None)),
    ):
        if value:
            parts.append(f"[{label}] {value}")
    parts.append(f"[PASSAGE À VÉRIFIER] {getattr(snapshot, 'excerpt', '')}")

    return f"{VERIFIER_INSTRUCTIONS}\n\n" + UNTRUSTED_PROMPT_HEADER.format(text="\n".join(parts))


class VerifierResponse(CanonicalModel):
    """La réponse du vérificateur — schéma fermé, aucune reformulation.

    `source_excerpt` est l'extrait tel que le vérificateur prétend l'avoir lu :
    c'est cette chaîne, et pas une paraphrase, qui sera confrontée au texte source.
    """

    verdict: VerifierVerdict
    reason: VerifierReason
    source_excerpt: NonEmptyStr
    confidence: Confidence


def verifier_response_schema() -> dict[str, object]:
    """Le schéma exact envoyé au fournisseur, dérivé du modèle Pydantic.

    Il n'est pas réécrit à la main : `strict: true` exige que chaque propriété
    soit requise et sans référence externe, donc les énumérations que Pydantic
    sort en `$defs` sont aplaties ici.
    """
    schema = VerifierResponse.model_json_schema()
    schema["additionalProperties"] = False
    definitions = schema.pop("$defs", {})
    for name, prop in schema.get("properties", {}).items():
        reference = prop.pop("$ref", None) or (prop.pop("allOf", [{}])[0].get("$ref"))
        if reference:
            target = definitions.get(reference.rsplit("/", 1)[-1], {})
            schema["properties"][name] = {**target, **prop}
    schema["required"] = list(schema.get("properties", {}))
    return schema


# ─── Le verdict à trois états ───────────────────────────────────────────────────

Outcome = Literal["auto_accepted", "review_required", "rejected"]
"""Ce qu'un candidat devient.

- `auto_accepted`   : assez sûr pour être exploité en aval, jamais « accepté par un LLM » ;
- `review_required` : conservé, visible en diagnostic, **pas** présenté comme certain ;
- `rejected`        : aucune `ExecutionRequirement` produite.
"""


@dataclass(frozen=True)
class ConsensusDecision:
    """Le verdict final. Tout ce qui n'est pas accepté porte son motif."""

    STATES: ClassVar[tuple[str, ...]] = ("auto_accepted", "review_required", "rejected")

    outcome: Outcome
    reason: str | None = None
    confidence: Confidence = "low"
    verifier_called: bool = False
    technical_failure: bool = False
    policy_version: str = CONSENSUS_POLICY_VERSION


def _review(reason: str, *, verifier_called: bool, technical: bool = False) -> ConsensusDecision:
    return ConsensusDecision(
        outcome="review_required",
        reason=reason,
        confidence="low",
        verifier_called=verifier_called,
        technical_failure=technical,
    )


def resolve(
    primary: SemanticClassification | None,
    verifier: VerifierResponse | None,
    *,
    source_text: str,
    evidence_complete: bool = False,
    locator_conflict: bool = False,
    verifier_called: bool = False,
) -> ConsensusDecision:
    """Applique la politique à deux modèles, dans un ordre lisible.

        auto_accepted ssi  le primaire passe la politique déterministe
                      ET   le vérificateur répond confirm/execution_contractor
                      ET   aucun conflit de localisation
                      ET   l'Evidence est complète
                      ET   l'extrait cité se retrouve dans le texte source

    L'ordre n'est pas cosmétique : le motif rendu est celui du **premier**
    obstacle rencontré, et un désaccord de fond doit se lire « procurement »,
    pas « evidence_incomplete ».
    """
    ran = verifier_called or verifier is not None

    # Une panne du primaire ne dit rien de la phrase.
    if primary is None:
        return _review("technical_failure", verifier_called=ran, technical=True)

    primary_decision = decide(primary, source_text=source_text)
    if not primary_decision.accepted:
        return ConsensusDecision(
            outcome="rejected",
            reason=primary_decision.reason,
            confidence="low",
            verifier_called=ran,
        )

    # Le primaire acceptait : l'absence de vérification est une panne, pas un rejet.
    if verifier is None:
        return _review("technical_failure", verifier_called=ran, technical=True)

    if verifier.verdict != "confirm":
        return _review(verifier.reason, verifier_called=True)
    if verifier.reason != "execution_contractor":
        return _review(verifier.reason, verifier_called=True)

    if locator_conflict:
        return _review("locator_conflict", verifier_called=True)
    if not evidence_complete:
        return _review("evidence_incomplete", verifier_called=True)

    # La garantie de SPEC-006, appliquée aussi au second modèle.
    if normalize_for_match(verifier.source_excerpt) not in normalize_for_match(source_text):
        return _review("excerpt_not_found", verifier_called=True)

    # SPEC-006R4 §6 : une haute confiance déclarée par un seul modèle n'a aucune
    # autorité. Il faut l'accord des deux, et toutes les conditions structurelles.
    both_high = primary.confidence == "high" and verifier.confidence == "high"
    return ConsensusDecision(
        outcome="auto_accepted",
        reason=None,
        confidence="high" if both_high else "medium",
        verifier_called=True,
    )
