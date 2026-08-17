"""Le contradicteur — pourquoi cette phrase NE DOIT PAS devenir une exigence.

Le benchmark FR-DCE-1 (17 août 2026) a mesuré le classifieur primaire seul :
46,2 % de précision d'auto-acceptation, 42 fausses acceptations en haute
confiance. Les causes sont connues une à une — fragments de mise en page,
obligations de l'acheteur, clauses d'engagement, critères de jugement des
offres. SPEC-006R5 y répond par un second passage dont la mission est inverse
de celle du primaire :

    Chercher activement une raison pour laquelle cette phrase NE DOIT PAS être
    présentée comme une obligation explicite d'exécution portée par le
    titulaire du marché.

Trois règles structurelles (§15, §19, §20) :

- le contradicteur ne voit **jamais** la décision du primaire — pas d'ancrage ;
- il n'est appelé que sur les candidats que le primaire accepte ET dont
  l'extrait a passé la validation déterministe — il coûte le prix d'une
  minorité de candidats ;
- il n'existe que deux issues : `auto_accepted` ou `ignored`. Pas de file de
  review humaine dans le MVP — un doute, un blocage, une panne ou une évidence
  invalide produisent la même chose : **aucune exigence certaine**. L'absence
  d'auto-acceptation vaut toujours mieux qu'un faux fait.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from signals.documents.classification import (
    UNTRUSTED_PROMPT_HEADER,
    SemanticClassification,
    decide,
)
from signals.documents.requirements import Confidence
from signals.documents.snapshot import CandidateSnapshot, validate_excerpt
from signals.domain.values import CanonicalModel, NonEmptyStr

ADVERSARIAL_POLICY_VERSION = "r5-adversarial-final-v1"
"""Version de la politique R5. Les mesures des politiques précédentes (contrat
sémantique seul v0.1-v0.3, consensus à trois états v0.4) ne s'y comparent pas :
R5 n'a pas d'issue `review_required`."""

# ─── Contrat du contradicteur (§17) ─────────────────────────────────────────────

AdversarialVerdict = Literal["confirm", "block", "uncertain"]
"""`block` quand une raison de blocage tient, `uncertain` quand le doute
subsiste. Le doute ne se transforme jamais en confirmation."""

AdversarialBlocker = Literal[
    "procurement",
    "qualification",
    "contract_formation",
    "buyer_obligation",
    "third_party_obligation",
    "informational",
    "fragment",
    "insufficient_context",
    "none",
]
"""Ce que la phrase est À LA PLACE d'une obligation d'exécution du titulaire.
`none` n'est cohérent qu'avec `confirm` : un blocage sans raison nommée, ou une
confirmation avec une raison de blocage, sont des réponses incohérentes que la
politique ignore."""


class AdversarialResponse(CanonicalModel):
    """La réponse du contradicteur — schéma fermé, aucune reformulation.

    `supporting_excerpt` est le passage qui FONDE le verdict, tel que le modèle
    prétend l'avoir lu : c'est cette chaîne, et pas une paraphrase, qui sera
    confrontée au texte source par le validateur déterministe.
    """

    verdict: AdversarialVerdict
    blocker: AdversarialBlocker
    supporting_excerpt: NonEmptyStr
    confidence: Confidence


def adversarial_response_schema() -> dict[str, object]:
    """Le schéma exact envoyé au fournisseur, dérivé du modèle Pydantic.

    `strict: true` exige que chaque propriété soit requise et sans référence
    externe : les énumérations que Pydantic sort en `$defs` sont aplaties ici,
    comme pour le classifieur et le vérificateur R4.
    """
    schema = AdversarialResponse.model_json_schema()
    schema["additionalProperties"] = False
    definitions = schema.pop("$defs", {})
    for name, prop in schema.get("properties", {}).items():
        reference = prop.pop("$ref", None) or (prop.pop("allOf", [{}])[0].get("$ref"))
        if reference:
            target = definitions.get(reference.rsplit("/", 1)[-1], {})
            schema["properties"][name] = {**target, **prop}
    schema["required"] = list(schema.get("properties", {}))
    return schema


def parse_adversarial(payload: str) -> AdversarialResponse | None:
    """Lit la réponse. Hors contrat vaut « pas de réponse » — aucune réparation."""
    text = payload.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return AdversarialResponse(**json.loads(text[start : end + 1]))
    except Exception:  # noqa: BLE001 — sortie non conforme = pas de réponse
        return None


# ─── Prompt (§15-§16, §18) ──────────────────────────────────────────────────────

ADVERSARIAL_INSTRUCTIONS = """\
Tu es le CONTRADICTEUR. Une phrase extraite d'un document de marché public \
français a été proposée comme obligation d'exécution portée par le titulaire. \
Ta mission n'est PAS de confirmer gentiment : cherche activement une raison \
pour laquelle cette phrase NE DOIT PAS être présentée comme une obligation \
explicite d'exécution portée par le titulaire du marché.

Mais une raison de blocage ne vaut que si elle TIENT : elle doit être \
démontrable par les mots de la phrase, jamais par une ressemblance lexicale. \
Si ta seule raison est qu'un mot ÉVOQUE un régime (« capacité », « norme », \
« reconduction », « offre »), la raison ne tient pas. Bloquer à tort une vraie \
obligation d'exécution est une erreur aussi grave que confirmer à tort.

Autre règle de lecture : l'obligation doit être DANS la phrase proposée \
elle-même. Le voisinage sert à l'interpréter, jamais à la remplacer.

Procédure — vérifie chaque étape contre le texte, dans cet ordre :

1. COMPLÉTUDE. La phrase proposée est-elle un énoncé complet et autoportant ? \
Indices d'un morceau : elle s'arrête sans ponctuation finale ou au milieu d'un \
complément ; elle se termine par deux-points (amorce de liste dont l'obligation \
est dans les items) ; elle commence par un pronom dont le référent n'est pas \
identifiable (« Ils doivent permettre l'accès… » — qui, « Ils » ?) ; c'est une \
ligne de tableau, un titre, un débris de mise en page. \
→ `block` / `fragment`. Si la phrase est complète mais que ce qui est exigé \
reste indéterminable même avec le voisinage → `block` / `insufficient_context`.

2. PORTEUR. Qui porte le verbe normatif (doit, devra, ne peut, est tenu, \
s'engage, à la charge de) ?
- le titulaire / prestataire / attributaire — y compris par tournure passive ou \
impersonnelle qui le vise (« … sont à la charge du titulaire », « le titulaire \
ne peut s'opposer à… ») → continue ;
- l'acheteur, le pouvoir adjudicateur, la personne publique, le maître \
d'ouvrage → `block` / `buyer_obligation`. Qui PORTE l'obligation décide, \
jamais qui en bénéficie ; une clause qui encadre ce que l'acheteur peut faire \
(plafond de pénalités, émission des bons de commande) pèse sur l'acheteur ;
- un tiers — cessionnaire de créance, banque, assureur, organisme de \
contrôle → `block` / `third_party_obligation` ;
- personne : la phrase décrit, définit ou rappelle sans verbe normatif → \
`block` / `informational`. Attention : « doivent être conformes / répondre / \
correspondre aux normes », « sont à la charge de », « ne pourront avoir lieu \
que », « sont autorisés pour la seule durée du marché » SONT des énoncés \
normatifs — pas de l'information.

3. MOMENT. À quel régime l'obligation appartient-elle ?
- la réalisation effective du marché, une fois attribué → continue ;
- la constitution, le chiffrage, la présentation ou le dépôt de l'OFFRE, les \
pièces à joindre, les critères de jugement, le mémoire technique, la remise en \
concurrence de marchés subséquents → `block` / `procurement` — même rédigé \
avec « doit » ;
- une capacité à DÉMONTRER pour être ADMIS à concourir (références, \
certificats, justificatifs de candidature) → `block` / `qualification`. Mais \
une capacité opérationnelle à TENIR pendant le marché — effectif à fournir, \
astreinte, disponibilité 24h/24, compétences des intervenants qui exécutent — \
est une obligation d'EXÉCUTION, pas de la qualification ;
- une formalité entre l'attribution et l'entrée en vigueur — signer et \
retourner l'acte d'engagement, « s'engage … à exécuter les prestations » d'un \
formulaire AE ou DC, constituer la garantie initiale — → `block` / \
`contract_formation`. La reconduction ou la durée d'un marché déjà en cours \
n'est PAS une formalité de formation du contrat.

4. VERDICT.
- `block` si une raison a tenu — nomme-la dans `blocker` ;
- `confirm` si aucune raison ne tient ET que la phrase établit EXPLICITEMENT \
une obligation, une interdiction ou une option portant sur l'exécution du \
marché et pesant sur le titulaire, dans un contexte suffisant. `blocker` vaut \
alors `none` ;
- `uncertain` si tu hésites encore après la procédure. Le doute reste un \
doute : ne devine pas, ne confirme jamais par défaut. `blocker` porte alors la \
raison la plus proche, ou `insufficient_context`.

supporting_excerpt : le passage EXACT qui fonde ton verdict, copié TEL QUEL \
depuis le texte encadré — sans le reformuler, le compléter ni le raccourcir.
confidence : `high` seulement si un lecteur attentif ne pourrait \
raisonnablement pas conclure autrement ; `medium` sinon ; `low` si tu hésites."""


def build_adversarial_prompt(snapshot: CandidateSnapshot) -> str:
    """Le prompt du contradicteur : consignes hors de la clôture, dossier dedans.

    Le §15 est structurel : rien de la décision du primaire n'entre ici — ni sa
    classification, ni sa confiance, ni son extrait. Le contradicteur lit le
    même dossier que lui, et rien d'autre.
    """
    parts: list[str] = []
    if snapshot.document_name:
        parts.append(f"[DOCUMENT] {snapshot.document_name}")
    parts.append(f"[LOCALISATION] {', '.join(snapshot.source_block_locators)}")
    if snapshot.language:
        parts.append(f"[LANGUE] {snapshot.language}")
    if snapshot.heading:
        parts.append(f"[SECTION] {snapshot.heading}")
    if snapshot.previous_block:
        parts.append(f"[BLOC PRÉCÉDENT] {snapshot.previous_block}")
    parts.append(f"[BLOC COURANT] {snapshot.logical_span or snapshot.current_block}")
    if snapshot.next_block:
        parts.append(f"[BLOC SUIVANT] {snapshot.next_block}")
    parts.append(f"[PHRASE PROPOSÉE] {snapshot.excerpt}")

    return f"{ADVERSARIAL_INSTRUCTIONS}\n\n" + UNTRUSTED_PROMPT_HEADER.format(text="\n".join(parts))


# ─── Garde de phase déterministe (SPEC-006R5.1 §3-§4) ──────────────────────────


def _fold(text: str) -> str:
    """Minuscules sans accents : « Critères » et « criteres » sont le même mot."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


_ENGAGEMENT_TOKEN = re.compile(r"(?:^|[\s_\-./\\])AE(?=[A-Z0-9_\-\s.]|$)")
"""Le token « AE » d'un nom de fichier — « AE_03 », « AE CONSEIL »,
« AEMarcheCadreAMO ». Sensible à la casse : « aeration.pdf » n'est pas un acte
d'engagement."""

_ENGAGEMENT_NAME = re.compile(r"acte[\s_\-]*d.?[\s_\-]*engagement")
_CANDIDACY_NAME = re.compile(
    r"(?:^|[\s_\-./\\])dc[1-7](?![0-9])|lettre[\s_\-]*de[\s_\-]*candidature"
    r"|declaration[\s_\-]*(?:du[\s_\-]*)?candidat"
)
_CONSULTATION_NAME = re.compile(
    r"(?:^|[\s_\-./\\])rc(?=[\s_\-.0-9]|$)|reglement[\s_\-]*de[\s_\-]*(?:la[\s_\-]*)?consultation"
)

_HEADING_BLOCKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "award_criteria_heading",
        re.compile(
            r"criteres?[\s\S]{0,12}jugement|jugement[\s\S]{0,12}(?:des[\s]*offres|et[\s]*attribution)"
            r"|attribution[\s]*du[\s]*marche|classement[\s]*des[\s]*offres"
            r"|(?:presentation|contenu|remise)[\s]*des[\s]*offres"
        ),
    ),
    (
        "signature_heading",
        re.compile(
            r"signature|acceptation[\s\S]{0,6}l.offre|je[\s]*soussigne"
            r"|engagement[\s]*du[\s]*(?:candidat|soumissionnaire)"
        ),
    ),
    (
        "form_identification_heading",
        re.compile(r"tva[\s]*intracommunautaire|siret|siren|numero[\s\S]{0,4}d.identification"),
    ),
    (
        "candidacy_heading",
        re.compile(r"candidature|qualifications?\b[\s\S]{0,40}references?"),
    ),
)


@dataclass(frozen=True)
class PhaseGuard:
    """Le verdict de la garde. Un blocage porte toujours sa raison structurelle."""

    verdict: Literal["PASS", "BLOCK"]
    reason: str | None = None


def phase_guard(snapshot: CandidateSnapshot) -> PhaseGuard:
    """La garde de phase déterministe — structurelle, générique, aveugle au texte.

    Elle ne lit JAMAIS la phrase candidate : un mot (« doit », « engagement »,
    « exécuter ») ne bloque rien (§4). Elle lit le nom du document et le titre
    de section, et bloque les contextes qui appartiennent explicitement à la
    formation du contrat, à la candidature ou au jugement des offres (§3) :
    un acte d'engagement est un formulaire d'offre engagée, un règlement de
    consultation porte les critères de jugement, un titre « Signature » ou
    « Numéro de TVA » est un champ de formulaire. En cas de doute : BLOCK.
    """
    name = snapshot.document_name or ""
    folded_name = _fold(name)
    if _ENGAGEMENT_TOKEN.search(name) or _ENGAGEMENT_NAME.search(folded_name):
        return PhaseGuard("BLOCK", "engagement_document")
    if _CANDIDACY_NAME.search(folded_name):
        return PhaseGuard("BLOCK", "candidacy_document")
    if _CONSULTATION_NAME.search(folded_name):
        return PhaseGuard("BLOCK", "consultation_rules")

    if snapshot.heading:
        folded_heading = _fold(snapshot.heading)
        for reason, pattern in _HEADING_BLOCKS:
            if pattern.search(folded_heading):
                return PhaseGuard("BLOCK", reason)

    return PhaseGuard("PASS")


# ─── Politique finale (§19-§20) ─────────────────────────────────────────────────

FinalOutcome = Literal["auto_accepted", "ignored"]
"""Deux issues, pas trois. `ignored` couvre le rejet, le doute, le blocage, la
panne et l'évidence invalide : Kivou retombe alors sur le fallback
Award + ContractUnderstanding, à confiance réduite — jamais sur un faux fait."""


@dataclass(frozen=True)
class FinalDecision:
    """Le verdict final. Tout ce qui n'est pas accepté porte son premier obstacle."""

    outcome: FinalOutcome
    reason: str | None = None
    confidence: Confidence = "low"
    # Les morceaux bruts qui portent la preuve — (localisation, texte tel qu'il
    # figure dans le bloc source). Jamais une citation recomposée.
    evidence: tuple[tuple[str, str], ...] = ()
    policy_version: str = ADVERSARIAL_POLICY_VERSION


def final_decision(
    primary: SemanticClassification | None,
    verifier: AdversarialResponse | None,
    *,
    snapshot: CandidateSnapshot,
) -> FinalDecision:
    """La politique finale R5, appliquée dans un ordre lisible.

        AUTO_ACCEPTED ssi  le primaire passe la politique déterministe (§12)
                      ET   son extrait passe le validateur d'évidence (§13)
                      ET   le contradicteur répond `confirm` (§18)
                      ET   son blocker vaut `none`
                      ET   son extrait d'appui passe le même validateur

    Le motif rendu est celui du PREMIER obstacle : un désaccord de fond doit se
    lire « procurement », pas « evidence_incomplete ».
    """
    if primary is None:
        return FinalDecision("ignored", "primary_failure")

    source_text = snapshot.logical_span or snapshot.current_block
    decision = decide(primary, source_text=source_text)
    if not decision.accepted:
        reason = decision.reason or "rejected"
        # §13-§14 : un extrait introuvable est une défaillance d'évidence, sous
        # son nom de gate — la validation déterministe a précisément ce rôle.
        if reason == "excerpt_not_found":
            reason = "raw_excerpt_failure"
        return FinalDecision("ignored", reason)

    evidence = validate_excerpt(primary.source_excerpt, snapshot)
    if not evidence.ok:
        return FinalDecision("ignored", "raw_excerpt_failure")

    if verifier is None:
        return FinalDecision("ignored", "verifier_failure")
    if verifier.verdict == "block":
        return FinalDecision(
            "ignored", verifier.blocker if verifier.blocker != "none" else "verifier_incoherent"
        )
    if verifier.verdict == "uncertain":
        return FinalDecision(
            "ignored",
            f"uncertain_{verifier.blocker}" if verifier.blocker != "none" else "uncertain",
        )
    if verifier.blocker != "none":
        # `confirm` avec une raison de blocage : réponse incohérente, ignorée.
        return FinalDecision("ignored", "verifier_incoherent")

    verifier_evidence = validate_excerpt(verifier.supporting_excerpt, snapshot)
    if not verifier_evidence.ok:
        return FinalDecision("ignored", "verifier_evidence_failure")

    # SPEC-006R5.1 §3 : la garde de phase déterministe a le dernier mot — un
    # contexte documentaire de formation, de candidature ou de jugement des
    # offres ne produit jamais un fait certain, quel que soit l'avis des modèles.
    guard = phase_guard(snapshot)
    if guard.verdict == "BLOCK":
        return FinalDecision("ignored", f"phase_guard_{guard.reason}")

    # Une haute confiance déclarée par un seul modèle n'a aucune autorité :
    # il faut l'accord des deux (principe SPEC-006R4 §6, conservé en R5).
    both_high = primary.confidence == "high" and verifier.confidence == "high"
    return FinalDecision(
        "auto_accepted",
        None,
        "high" if both_high else "medium",
        evidence.pieces,
    )
